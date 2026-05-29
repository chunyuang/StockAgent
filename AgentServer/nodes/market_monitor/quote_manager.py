"""
QuoteManager — 行情数据管理器

从MarketScanner拆分出来, 职责:
1. 双数据源初始化(东方财富+必盈)
2. 全市场实时行情获取
3. 降级+自动恢复(3次失败→降级,成功→恢复)
4. 缓存管理(_realtime_cache/_prev_realtime_cache)

数据源分工:
- 东方财富(免费无限): 全市场5400只的price/pct_chg/volume_ratio/turnover_rate/PE/PB
  → 半路追涨选股 + 持仓止损价格
- 必盈(200次/天): 涨停池/跌停池/炸板池(封板资金/连板/炸板次数)
  → 首板打板 + 跌停翘板 + 龙头低吸

单次消耗: 东方财富0次(全市场缓存) + 必盈3次(3个池)
"""

import asyncio
import logging
import threading
import time
from datetime import datetime
from typing import Dict, Optional, Any

logger = logging.getLogger("quote_manager")


class QuoteManager:
    """行情数据管理器"""

    def __init__(self):
        self._data_router = None
        self._realtime_cache: Dict[str, Dict] = {}
        self._prev_realtime_cache: Dict[str, Dict] = {}
        self._cache_lock: Optional[threading.Lock] = None
        
        # 降级状态
        self._quote_degrade_level = 0   # 0=正常, 1=东财降级, 2=日线缓存
        self._quote_fail_count = 0      # 连续失败次数
        
        # 【Phase2.2:5分钟自动恢复机制】
        self._degrade_since: float = 0.0     # 降级开始时间(monotonic)
        self._last_recover_attempt: float = 0.0  # 上次恢复尝试时间
        self._recover_interval: float = 300.0    # 5分钟尝试一次恢复
        self._last_fetch_time: float = 0.0      # 上次成功获取行情时间
        
        # 回放模式
        self._replay_mode = False
        self._replay_provider = None
        self._replay_date = None
        
        # 事件发射回调(v2.9:替代_scanner引用,消除循环依赖)
        self._event_emitter = None  # async函数: emit(event_name, data)

    @property
    def degrade_level(self) -> int:
        return self._quote_degrade_level

    @property
    def degrade_desc(self) -> str:
        return ["正常", "东财降级", "日线缓存"][self._quote_degrade_level]

    @property
    def cached_count(self) -> int:
        return len(self._realtime_cache)

    def set_cache_lock(self, lock: threading.Lock):
        """设置缓存锁(Scanner传入,线程安全)"""
        self._cache_lock = lock

    def set_event_emitter(self, emitter):
        """设置事件发射回调(v2.9:替代_scanner引用,消除循环依赖)
        
        Args:
            emitter: async函数 async emit(event_name: str, data: dict)
        """
        self._event_emitter = emitter

    def set_replay_mode(self, enabled: bool, provider=None, date: str = None):
        """设置回放模式"""
        self._replay_mode = enabled
        self._replay_provider = provider
        self._replay_date = date

    async def initialize(self) -> bool:
        """初始化数据源(东方财富+必盈)"""
        if self._data_router:
            return True

        try:
            from nodes.market_monitor.data_source_router import DataSourceRouter
            from src.data_sources.biying_adapter import BiyingAdapter
            from src.data_sources.eastmoney_adapter import EastmoneyAdapter

            router = DataSourceRouter()

            # 东方财富: 免费, 无限流, 全市场快照
            eastmoney = EastmoneyAdapter()
            router.register("eastmoney", eastmoney, priority=5)

            # 必盈: 涨停池/五档
            biying = BiyingAdapter(licence="E53CA0F0-3E85-4736-B22D-8FA41A5DB050")
            router.register("biying", biying, priority=10)

            results = await router.initialize_all()

            if not results.get("eastmoney") and not results.get("biying"):
                logger.error("[QUOTE] 两个数据源都初始化失败")
                return False

            self._data_router = router
            em_status = eastmoney.get_status()
            logger.info(f"[QUOTE] 数据源初始化: 东方财富{em_status['cached_stocks']}只 + 必盈")
            return True
        except Exception as e:
            logger.error(f"[QUOTE] 数据源初始化失败: {e}")
            return False

    async def fetch_realtime_batch(self, force: bool = False) -> Dict[str, Dict]:
        """批量获取实时行情 — 双数据源架构

        Returns:
            Dict[ts_code, {price, pct_chg, turnover_rate, ...}]
        """
        if not self._data_router:
            ok = await self.initialize()
            if not ok:
                return {}

        eastmoney = self._data_router._sources.get("eastmoney")
        biying = self._data_router._sources.get("biying")

        # 回放模式
        if self._replay_mode and self._replay_provider:
            replay_date = self._replay_date or datetime.now().strftime("%Y%m%d")
            replay_data = self._replay_provider.get_realtime(replay_date)
            logger.info(f"[REPLAY] 返回 {len(replay_data)} 只模拟行情(日期={replay_date})")
            return replay_data

        # 非交易时间检查
        now = datetime.now()
        ct = now.strftime("%H:%M")
        is_trading = ("09:15" <= ct <= "15:05")
        if not is_trading and not force:
            logger.info(f"[QUOTE] 非交易时间({ct}), 跳过(用force=True强制)")
            return {}

        realtime = {}
        today = datetime.now().strftime("%Y-%m-%d")

        # === 1. 东方财富: 全市场5400只 ===
        if eastmoney:
            try:
                em_data = await eastmoney.get_all_realtime(force_refresh=True)
                for ts_code, item in em_data.items():
                    realtime[ts_code] = {
                        "price": item.get("price"),
                        "pct_chg": item.get("pct_chg"),
                        "turnover_rate": item.get("turnover_rate"),
                        "volume_ratio": item.get("volume_ratio"),
                        "pe": item.get("pe"),
                        "pb": item.get("pb"),
                        "float_mv": item.get("float_mv"),
                        "open": item.get("open"),
                        "high": item.get("high"),
                        "low": item.get("low"),
                        "pre_close": item.get("pre_close"),
                        "name": item.get("name", ""),
                        "amplitude": item.get("amplitude"),
                    }
                logger.info(f"[QUOTE] 东方财富: {len(em_data)}只全市场快照")
                # 成功 → 重置失败计数, 尝试恢复降级
                self._quote_fail_count = 0
                self._last_fetch_time = time.monotonic()
                if self._quote_degrade_level > 0:
                    degrade_duration = time.monotonic() - self._degrade_since
                    self._quote_degrade_level = 0
                    self._degrade_since = 0
                    logger.info(f"[QUOTE] 行情恢复正常, 降级已恢复(持续{degrade_duration:.0f}秒)")
                    # 【v2.9:通过回调发射EventBus行情恢复事件(消除_scanner引用)】
                    if self._event_emitter:
                        asyncio.ensure_future(self._event_emitter("quote_recovered", {
                            "level": 0,
                            "degrade_duration_s": degrade_duration,
                            "source": "eastmoney",
                        }))
            except Exception as e:
                self._quote_fail_count += 1
                if self._quote_fail_count >= 3 and self._quote_degrade_level == 0:
                    self._quote_degrade_level = 1
                    self._degrade_since = time.monotonic()
                    self._last_recover_attempt = time.monotonic()  # 从降级时刻开始计时
                    logger.warning(f"[QUOTE] 东方财富连续3次失败,降级到level 1: {e}")
                    # 【v2.9:通过回调发射EventBus行情降级事件(消除_scanner引用)】
                    if self._event_emitter:
                        asyncio.ensure_future(self._event_emitter("quote_degraded", {
                            "level": 1,
                            "source": "eastmoney",
                            "error": str(e),
                        }))
                else:
                    logger.warning(f"[QUOTE] 东方财富获取失败({self._quote_fail_count}次): {e}")

        # === 2. 必盈涨停池 ===
        if biying:
            try:
                limit_ups = await biying.get_limit_up_pool(today)
                limit_up_count = 0
                for item in limit_ups:
                    ts_code = item.get("ts_code", "")
                    if not ts_code or "." not in ts_code:
                        continue
                    if ts_code in realtime:
                        realtime[ts_code].update({
                            "is_limit_up": True,
                            "limit_times": item.get("limit_times", 0),
                            "fd_amount": item.get("fd_amount", 0),
                            "first_limit_time": item.get("first_limit_time", ""),
                            "last_limit_time": item.get("last_limit_time", ""),
                            "limit_amount": item.get("limit_amount", 0),
                            "open_times": item.get("open_times", 0),
                            "up_stat": item.get("up_stat", ""),
                        })
                    limit_up_count += 1
                logger.info(f"[QUOTE] 必盈涨停池: {limit_up_count}只")

                # 跌停池
                limit_downs = await biying.get_limit_down_pool(today)
                for item in limit_downs:
                    ts_code = item.get("ts_code", "")
                    if ts_code and ts_code in realtime:
                        realtime[ts_code].update({
                            "is_limit_down": True,
                            "limit_down_amount": item.get("fd_amount", 0),
                        })

                # 炸板池
                try:
                    limit_opens = await biying.get_limit_open_pool(today)
                    for item in limit_opens:
                        ts_code = item.get("ts_code", "")
                        if ts_code and ts_code in realtime:
                            realtime[ts_code].update({
                                "is_limit_open": True,
                                "open_times": item.get("open_times", 0),
                            })
                except Exception:
                    pass

            except Exception as e:
                logger.warning(f"[QUOTE] 必盈不可用: {e}, 仅使用东方财富数据(无涨停池详情)")

        # 更新缓存(线程安全)
        if self._cache_lock:
            with self._cache_lock:
                self._prev_realtime_cache = dict(self._realtime_cache)
                self._realtime_cache = realtime
        else:
            self._prev_realtime_cache = dict(self._realtime_cache)
            self._realtime_cache = realtime

        return realtime

    def get_cached_price(self, ts_code: str) -> Optional[float]:
        """从缓存获取价格(风控线程用,线程安全)"""
        if self._cache_lock:
            with self._cache_lock:
                return self._realtime_cache.get(ts_code, {}).get("price")
        return self._realtime_cache.get(ts_code, {}).get("price")

    def get_cached_data(self, ts_code: str) -> Optional[Dict]:
        """从缓存获取完整行情(线程安全)"""
        if self._cache_lock:
            with self._cache_lock:
                return self._realtime_cache.get(ts_code)
        return self._realtime_cache.get(ts_code)

    def get_all_cached(self) -> Dict[str, Dict]:
        """获取全部缓存(线程安全拷贝)"""
        if self._cache_lock:
            with self._cache_lock:
                return dict(self._realtime_cache)
        return dict(self._realtime_cache)

    def get_prev_cached(self, ts_code: str) -> Optional[Dict]:
        """获取上轮缓存(用于急速拉升检测)"""
        if self._cache_lock:
            with self._cache_lock:
                return self._prev_realtime_cache.get(ts_code)
        return self._prev_realtime_cache.get(ts_code)

    @staticmethod
    def short_to_ts_code(short_code: str) -> str:
        """6位代码→ts_code"""
        if not short_code:
            return ""
        if short_code.startswith('6'):
            return f"{short_code}.SH"
        elif short_code.startswith('0') or short_code.startswith('3'):
            return f"{short_code}.SZ"
        elif short_code.startswith(('4', '8')):
            return f"{short_code}.BJ"
        return f"{short_code}.SZ"

    def get_staleness(self) -> float:
        """行情陈旧度(秒) — 上次成功获取到现在的秒数"""
        if self._last_fetch_time == 0:
            return 999.0
        return time.monotonic() - self._last_fetch_time
    
    def should_try_recover(self) -> bool:
        """【Phase2.2】是否应该尝试恢复到更高级别数据源
        
        降级后每5分钟尝试恢复:
        - level 1(东财降级): 每5分钟尝试重新连接东财
        - level 2(日线缓存): 每5分钟尝试重新连接东财
        
        Returns:
            True=应尝试恢复, False=尚未到恢复时间
        """
        if self._quote_degrade_level == 0:
            return False  # 已正常,无需恢复
        
        elapsed = time.monotonic() - self._last_recover_attempt
        if elapsed >= self._recover_interval:
            return True
        return False
    
    async def try_recover(self) -> bool:
        """【Phase2.2】尝试恢复到更高级别数据源
        
        降级链: 量脉实时 → 东财实时 → 东财日线缓存
        恢复链: 日线缓存 → 东财实时 → 量脉实时
        
        Returns:
            True=恢复成功, False=恢复失败
        """
        if self._quote_degrade_level == 0:
            return True  # 已正常
        
        self._last_recover_attempt = time.monotonic()
        old_level = self._quote_degrade_level
        
        # 尝试重新获取东财数据
        if self._data_router:
            eastmoney = self._data_router._sources.get("eastmoney")
            if eastmoney:
                try:
                    # 尝试获取行情来验证东财是否可用
                    test_data = await eastmoney.get_all_realtime(force_refresh=True)
                    if test_data and len(test_data) > 100:  # 至少100只=正常
                        self._quote_degrade_level = 0
                        self._quote_fail_count = 0
                        degrade_duration = time.monotonic() - self._degrade_since
                        logger.info(
                            f"[QUOTE] 🔄 行情自动恢复成功! "
                            f"level {old_level}→0, 降级持续{degrade_duration:.0f}秒"
                        )
                        return True
                except Exception as e:
                    logger.debug(f"[QUOTE] 恢复尝试失败(将在5分钟后重试): {e}")
        
        logger.info(f"[QUOTE] 行情恢复失败, 当前level={self._quote_degrade_level}, 5分钟后重试")
        return False

    def get_status(self) -> Dict[str, Any]:
        """状态(供Scanner.get_status使用)"""
        return {
            "degrade_level": self._quote_degrade_level,
            "degrade_desc": self.degrade_desc,
            "cached_stocks": len(self._realtime_cache),
            "data_sources": list(self._data_router._sources.keys()) if self._data_router else [],
            "staleness_seconds": round(self.get_staleness(), 1),
            "degrade_duration_seconds": round(time.monotonic() - self._degrade_since, 1) if self._degrade_since > 0 else 0,
            "next_recover_in_seconds": max(0, round(self._recover_interval - (time.monotonic() - self._last_recover_attempt), 1)) if self._quote_degrade_level > 0 else 0,
        }
