"""
QuoteManager — 行情数据管理器

从MarketScanner拆分出来, 职责:
1. 三数据源初始化(东方财富+新浪+必盈)
2. 全市场实时行情获取
3. 降级+自动恢复(东财失败→新浪→MongoDB日线)
4. 缓存管理(_realtime_cache/_prev_realtime_cache)
5. 行情告警通知(降级/陈旧时通知用户)

数据源分工:
- 东方财富(免费无限): 全市场5400只的price/pct_chg/volume_ratio/turnover_rate/PE/PB
  → 半路追涨选股 + 持仓止损价格
- 新浪财经(免费无限): 全市场快照(无量比, 从MongoDB补) — 东财不可用时回退
- 必盈(200次/天): 涨停池/跌停池/炸板池(封板资金/连板/炸板次数)
  → 首板打板 + 跌停翘板 + 龙头低吸

单次消耗: 东方财富0次(全市场缓存) + 新浪0次 + 必盈3次(3个池)
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
        self._last_pool_fetch_time: float = 0.0  # 【v2.9.126】上次必盈池刷新时间
        
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
        return ["正常", "东财降级(用缓存)", "日线缓存"][min(self._quote_degrade_level, 2)]

    @property
    def cache_lock_initialized(self) -> bool:
        """缓存锁是否已初始化【v2.9.18】"""
        return self._cache_lock is not None

    @property
    def realtime_cache(self) -> Dict:
        """实时行情缓存(直接引用,仅用于内部加锁场景)【v2.9.18】"""
        return self._realtime_cache

    @property
    def prev_realtime_cache(self) -> Dict:
        """上一帧行情缓存(直接引用)【v2.9.18】"""
        return self._prev_realtime_cache

    @property
    def data_router(self) -> Any:
        """数据源路由器(直接引用)【v2.9.18】"""
        return self._data_router

    @property
    def quote_degrade_level(self) -> int:
        """行情降级等级(直接引用)【v2.9.18】"""
        return self._quote_degrade_level

    @property
    def cached_count(self) -> int:
        return len(self._realtime_cache)

    def set_cache_lock(self, lock: threading.Lock) -> None:
        """设置缓存锁(Scanner传入,线程安全)"""
        self._cache_lock = lock

    def set_event_emitter(self, emitter) -> None:
        """设置事件发射回调(v2.9:替代_scanner引用,消除循环依赖)
        
        Args:
            emitter: async函数 async emit(event_name: str, data: dict)
        """
        self._event_emitter = emitter

    def set_replay_mode(self, enabled: bool, provider=None, date: str = None) -> None:
        """设置回放模式"""
        self._replay_mode = enabled
        self._replay_provider = provider
        self._replay_date = date

    def warm_sources_cache(self, realtime: Dict[str, Dict]) -> None:
        """将预热行情数据写入数据源缓存(供scanner周末预热调用)【v2.9.18】"""
        if not self._data_router:
            return
        for source in self._data_router._sources.values():
            if hasattr(source, '_cache') and hasattr(source, '_cache_time'):
                source._cache = {k: {"price": v["price"], "pct_chg": v["pct_chg"],
                                     "pre_close": v["pre_close"], "open": v["open"],
                                     "high": v["high"], "low": v["low"],
                                     "vol": v["vol"], "amount": v["amount"],
                                     "turnover_rate": v.get("turnover_rate", 0),
                                     "volume_ratio": v.get("volume_ratio", 0),
                                     "name": v.get("name", "")}
                                for k, v in realtime.items()}
                source._cache_time = __import__('time').time()
                source._total_stocks = len(realtime)

    async def initialize(self) -> bool:
        """初始化数据源(东方财富+必盈)"""
        if self._data_router:
            return True

        try:
            from nodes.market_monitor.data_source_router import DataSourceRouter
            from src.data_sources.biying_adapter import BiyingAdapter
            from src.data_sources.eastmoney_adapter import EastmoneyAdapter

            from src.data_sources.sina_adapter import SinaAdapter

            router = DataSourceRouter()

            # 东方财富: 免费, 无限流, 全市场快照(主力)
            eastmoney = EastmoneyAdapter()
            router.register("eastmoney", eastmoney, priority=5)

            # 新浪财经: 免费, 无限流, 全市场快照(备选实时源)
            sina = SinaAdapter()
            router.register("sina", sina, priority=8)

            # 必盈: 涨停池/五档
            biying = BiyingAdapter(licence="E53CA0F0-3E85-4736-B22D-8FA41A5DB050")
            router.register("biying", biying, priority=10)

            results = await router.initialize_all()

            if not results.get("eastmoney") and not results.get("biying"):
                logger.error("[QUOTE] 两个数据源都初始化失败")
                return False

            self._data_router = router
            em_status = eastmoney.get_status()
            sina_status = sina.get_status()
            logger.info(f"[QUOTE] 数据源初始化: 东方财富{em_status['cached_stocks']}只 + 新浪{sina_status['cached_stocks']}只 + 必盈")
            return True
        except Exception as e:
            logger.error(f"[QUOTE] 数据源初始化失败: {e}")
            return False

    async def fetch_realtime_batch(self, force: bool = False) -> Dict[str, Dict]:
        """批量获取实时行情 — 双数据源架构 + 降级链路

        降级链: L0正常(东财实时) → L1东财降级+新浪回退(用缓存) → L2日线缓存(MongoDB)
        行情降级时通过事件发射器通知前端/飞书

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

        # 非交易时间检查(周末/收盘后: 用缓存数据,不阻塞)
        now = datetime.now()
        ct = now.strftime("%H:%M")
        is_weekend = now.weekday() >= 5
        is_trading = ("09:15" <= ct <= "15:05") and not is_weekend

        if not is_trading and not force:
            logger.info(f"[QUOTE] 非交易时间({ct}{' 周末' if is_weekend else ''}), 使用缓存")
            if eastmoney and eastmoney._cache:
                cache_age = time.time() - eastmoney._cache_time if eastmoney._cache_time > 0 else 9999
                logger.info(f"[QUOTE] 东财缓存: {len(eastmoney._cache)}只, {cache_age:.0f}秒前")
                return self._build_realtime_from_cache(eastmoney._cache)
            # 【v2.9.86修复】非交易时间缓存为空时, 无论degrade_level都尝试MongoDB
            # 之前只在degrade_level>=1时才fallback, 重启后正常状态会返回空{}
            mongo_data = await self._fallback_to_mongo_daily()
            if mongo_data:
                return mongo_data
            return {}

        # 降级level 2: 尝试从MongoDB读取最近日线数据
        if self._quote_degrade_level >= 2:
            logger.info("[QUOTE] Level 2降级: 使用MongoDB日线数据")
            mongo_data = await self._fallback_to_mongo_daily()
            if mongo_data:
                return mongo_data
            # MongoDB也没数据, 仍尝试东财

        realtime: Dict[str, Dict] = {}
        today = datetime.now().strftime("%Y-%m-%d")

        # === 1. 东方财富: 全市场5400只 ===
        await self._fetch_eastmoney_data(eastmoney, realtime)

        # L1降级: 东财获取失败后尝试MongoDB
        if not realtime and self._quote_degrade_level >= 1:
            logger.warning("[QUOTE] 东财数据为空且已降级, 尝试MongoDB日线")
            mongo_data = await self._fallback_to_mongo_daily()
            if mongo_data:
                return mongo_data

        # === 2. 必盈涨停/跌停/炸板池 ===
        await self._merge_limit_pool_data(biying, realtime, today)

        # 更新缓存(线程安全)
        self._update_realtime_cache(realtime)

        return realtime

    @staticmethod
    def _map_em_item_to_realtime(item: Dict) -> Dict:
        """东方财富单条数据映射到realtime格式【v2.9.62提取】"""
        return {
            "price": item.get("price"),
            "pct_chg": item.get("pct_chg"),
            "turnover_rate": item.get("turnover_rate"),
            "volume_ratio": item.get("volume_ratio"),
            "pe": item.get("pe"),
            "pb": item.get("pb"),
            "float_mv": item.get("float_mv"),
            "open": item.get("open") or 0,
            "high": item.get("high") or 0,
            "low": item.get("low") or 0,
            "pre_close": item.get("pre_close") or 0,
            "name": item.get("name", ""),
            "amplitude": item.get("amplitude"),
        }

    def _handle_em_degrade_recovery(self) -> None:
        """行情降级恢复处理【v2.9.62提取】"""
        if self._quote_degrade_level <= 0:
            return
        degrade_duration = time.monotonic() - self._degrade_since
        from_level = self._quote_degrade_level
        self._quote_degrade_level = 0
        self._degrade_since = 0
        logger.info(f"[QUOTE] 行情恢复正常, 降级已恢复(持续{degrade_duration:.0f}秒)")
        # 【v2.9.107】持久化恢复事件
        try:
            from .market_event_log import log_quote_degrade
            asyncio.get_event_loop().create_task(log_quote_degrade(
                from_level=from_level, to_level=0,
                reason=f"恢复正常, 持续{degrade_duration:.0f}秒",
                fail_count=self._quote_fail_count,
            ))
        except Exception:
            pass
        self._quote_fail_count = 0
        if self._event_emitter:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._event_emitter("quote_recovered", {
                    "level": 0,
                    "degrade_duration_s": degrade_duration,
                    "source": "eastmoney",
                }))
            except RuntimeError:
                logger.debug("[QUOTE] 无运行中事件循环, 跳过quote_recovered事件发射")

    def _handle_em_fetch_failure(self, error: Exception) -> None:
        """行情获取失败处理(降级判断)【v2.9.62提取, v2.9.75:增加level2】"""
        self._quote_fail_count += 1
        if self._quote_fail_count >= 6 and self._quote_degrade_level < 2:
            # 连续6次失败(约2个扫描周期), 升级到level 2(MongoDB日线)
            from_lv = self._quote_degrade_level
            self._quote_degrade_level = 2
            self._degrade_since = time.monotonic()
            self._last_recover_attempt = time.monotonic()
            logger.warning(f"[QUOTE] 东方财富连续{self._quote_fail_count}次失败,降级到level 2(日线缓存): {error}")
            # 【v2.9.107】持久化降级事件
            try:
                from .market_event_log import log_quote_degrade
                asyncio.get_event_loop().create_task(log_quote_degrade(
                    from_level=from_lv, to_level=2,
                    reason=str(error)[:300], fail_count=self._quote_fail_count,
                ))
            except Exception:
                pass
            if self._event_emitter:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._event_emitter("quote_degraded", {
                        "level": 2,
                        "source": "eastmoney",
                        "error": str(error),
                    }))
                except RuntimeError:
                    logger.debug("[QUOTE] 无运行中事件循环, 跳过quote_degraded事件发射")
        elif self._quote_fail_count >= 3 and self._quote_degrade_level == 0:
            self._quote_degrade_level = 1
            self._degrade_since = time.monotonic()
            self._last_recover_attempt = time.monotonic()
            logger.warning(f"[QUOTE] 东方财富连续3次失败,降级到level 1(缓存模式): {error}")
            # 【v2.9.107】持久化降级事件
            try:
                from .market_event_log import log_quote_degrade
                asyncio.get_event_loop().create_task(log_quote_degrade(
                    from_level=0, to_level=1,
                    reason=str(error)[:300], fail_count=self._quote_fail_count,
                ))
            except Exception:
                pass
            if self._event_emitter:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._event_emitter("quote_degraded", {
                        "level": 1,
                        "source": "eastmoney",
                        "error": str(error),
                    }))
                except RuntimeError:
                    logger.debug("[QUOTE] 无运行中事件循环, 跳过quote_degraded事件发射")
        else:
            logger.warning(f"[QUOTE] 东方财富获取失败({self._quote_fail_count}次): {error}")

    async def _fetch_eastmoney_data(
        self, eastmoney: Any, realtime: Dict[str, Dict]
    ) -> None:
        """【v2.9.57提取, v2.9.62重构, v2.9.105:三源降级】全市场数据获取 + 降级处理

        降级链: 东方财富push2 → 新浪财经 → MongoDB日线
        """
        # === 1. 尝试东方财富 ===
        if eastmoney:
            try:
                em_data = await eastmoney.get_all_realtime(force_refresh=True)
                if em_data:
                    for ts_code, item in em_data.items():
                        realtime[ts_code] = self._map_em_item_to_realtime(item)
                    logger.info(f"[QUOTE] 东方财富: {len(em_data)}只全市场快照")
                    self._quote_fail_count = 0
                    self._last_fetch_time = time.monotonic()
                    self._handle_em_degrade_recovery()
                    return
            except Exception as e:
                self._handle_em_fetch_failure(e)

        # 东方财富失败 → 尝试新浪
        logger.warning("[QUOTE] 东方财富不可用, 尝试新浪财经...")
        sina = self._data_router._sources.get("sina") if self._data_router else None
        if sina:
            try:
                sina_data = await sina.get_all_realtime(force_refresh=True)
                if sina_data:
                    for ts_code, item in sina_data.items():
                        realtime[ts_code] = self._map_em_item_to_realtime(item)
                    logger.info(f"[QUOTE] 新浪财经回退: {len(sina_data)}只")
                    self._quote_fail_count = 0
                    self._last_fetch_time = time.monotonic()
                    # 不恢复降级(东财仍不可用), 但新浪数据可用
                    self._emit_quote_warning(
                        "东方财富push2不可用, 已切换到新浪财经",
                        {"source": "sina_fallback", "stocks": len(sina_data)}
                    )
                    return
            except Exception as e:
                logger.warning(f"[QUOTE] 新浪也失败: {e}")

        # 东财+新浪都失败 → 用缓存或MongoDB
        if not realtime and self._quote_degrade_level >= 1:
            logger.warning("[QUOTE] 东财+新浪均不可用, 尝试MongoDB日线")
            mongo_data = await self._fallback_to_mongo_daily()
            if mongo_data:
                realtime.update(mongo_data)
                self._emit_quote_warning(
                    "东财+新浪均不可用, 已降级到MongoDB日线数据(策略筛选可能受影响)",
                    {"source": "mongo_fallback", "stocks": len(mongo_data)}
                )
                return

        # 所有源都失败
        if not realtime:
            self._emit_quote_warning(
                "⚠️ 所有行情源不可用! 东方财富+新浪+MongoDB均失败, 策略筛选将产出0候选",
                {"source": "all_failed"}
            )

    @staticmethod
    def _merge_limit_up_items(items: list, realtime: Dict[str, Dict]) -> int:
        """合并涨停池数据到realtime, 返回有效数量【v2.9.63提取】"""
        count = 0
        for item in items:
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
            count += 1
        return count

    @staticmethod
    def _merge_limit_down_items(items: list, realtime: Dict[str, Dict]) -> None:
        """合并跌停池数据到realtime【v2.9.63提取】"""
        for item in items:
            ts_code = item.get("ts_code", "")
            if ts_code and ts_code in realtime:
                realtime[ts_code].update({
                    "is_limit_down": True,
                    "limit_down_amount": item.get("fd_amount", 0),
                })

    @staticmethod
    def _merge_limit_open_items(items: list, realtime: Dict[str, Dict]) -> None:
        """合并炸板池数据到realtime【v2.9.63提取】"""
        for item in items:
            ts_code = item.get("ts_code", "")
            if ts_code and ts_code in realtime:
                realtime[ts_code].update({
                    "is_limit_open": True,
                    "open_times": item.get("open_times", 0),
                })

    async def _merge_limit_pool_data(
        self, biying: Any, realtime: Dict[str, Dict], today: str,
        force: bool = False
    ) -> None:
        """必盈涨停/跌停/炸板池数据合并【v2.9.126: 5分钟限流】
        
        涨停池变化慢(分钟级), 不需要15秒刷新一次。
        必盈免费版200次/天, 3池×4次/分=720次/天 → 严重超标。
        改为5分钟刷新一次: 3池×12次/h×4h=144次/天 ✅
        """
        if not biying:
            return
        
        # 【v2.9.126】5分钟限流: 必盈200次/天, 不随行情高频刷新
        pool_age = time.monotonic() - self._last_pool_fetch_time
        if pool_age < 300 and not force:  # 5分钟内不重复拉
            return
        self._last_pool_fetch_time = time.monotonic()
        
        try:
            # 涨停池
            limit_ups = await biying.get_limit_up_pool(today)
            count = self._merge_limit_up_items(limit_ups, realtime)
            logger.info(f"[QUOTE] 必盈涨停池: {count}只")

            # 跌停池
            limit_downs = await biying.get_limit_down_pool(today)
            self._merge_limit_down_items(limit_downs, realtime)

            # 炸板池
            try:
                limit_opens = await biying.get_limit_open_pool(today)
                self._merge_limit_open_items(limit_opens, realtime)
            except Exception as _e:
                logger.debug(f"operation failed: {_e}")

        except Exception as e:
            logger.warning(f"[QUOTE] 必盈不可用: {e}, 仅使用东方财富数据(无涨停池详情)")

    def _update_realtime_cache(self, realtime: Dict[str, Dict]) -> None:
        """【v2.9.57提取】线程安全地更新行情缓存"""
        if self._cache_lock:
            with self._cache_lock:
                self._prev_realtime_cache = dict(self._realtime_cache)
                self._realtime_cache = realtime
        else:
            self._prev_realtime_cache = dict(self._realtime_cache)
            self._realtime_cache = realtime

    def _build_realtime_from_cache(self, em_cache: Dict) -> Dict[str, Dict]:
        """从东方财富缓存构建realtime格式数据"""
        realtime = {}
        for ts_code, item in em_cache.items():
            realtime[ts_code] = {
                "price": item.get("price"),
                "pct_chg": item.get("pct_chg"),
                "turnover_rate": item.get("turnover_rate"),
                "volume_ratio": item.get("volume_ratio"),
                "open": item.get("open") or 0,
                "high": item.get("high") or 0,
                "low": item.get("low") or 0,
                "pre_close": item.get("pre_close") or 0,
                "vol": item.get("vol"),
                "amount": item.get("amount"),
            }
        # 更新本地缓存
        self._realtime_cache = realtime
        self._last_fetch_time = time.monotonic()  # 【v2.9.112修复】统一用monotonic(与L365/L382一致)
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

    def _emit_quote_warning(self, message: str, extra: dict = None) -> None:
        """【v2.9.105】行情告警通知 — 发送事件 + 飞书通知

        行情降级/陈旧时通知用户, 让用户知道策略筛选可能受影响。
        """
        import asyncio as _asyncio
        logger.warning(f"[QUOTE] {message}")
        if self._event_emitter:
            try:
                loop = _asyncio.get_running_loop()
                payload = {"message": message, "level": "warning"}
                if extra:
                    payload.update(extra)
                loop.create_task(self._event_emitter("quote_warning", payload))
            except RuntimeError:
                logger.debug("[QUOTE] 无运行中事件循环, 跳过quote_warning事件")

    def get_staleness(self) -> float:
        """行情陈旧度(秒) — 上次成功获取到现在的秒数，超过30秒标记为stale"""
        if self._last_fetch_time == 0:
            return 999.0
        elapsed = time.monotonic() - self._last_fetch_time
        if elapsed > 60 and self._quote_degrade_level == 0:
            logger.warning(f"[QUOTE] 行情数据陈旧: {elapsed:.0f}秒(>60s阈值)")
            # v2.9.105: 陈旧度>60秒时通知用户
            if elapsed > 60 and not getattr(self, '_stale_warned', False):
                self._stale_warned = True
                self._emit_quote_warning(
                    f"行情数据陈旧 {elapsed:.0f}秒, 策略筛选可能产出0候选",
                    {"staleness_s": round(elapsed, 0)}
                )
        elif elapsed <= 10:
            self._stale_warned = False
        return elapsed
    
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
        """【Phase2.2, v2.9.105】尝试恢复到更高级别数据源
        
        恢复链: MongoDB日线 → 新浪 → 东财
        
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
                    test_data = await eastmoney.get_all_realtime(force_refresh=True)
                    if test_data and len(test_data) > 100:
                        self._quote_degrade_level = 0
                        self._quote_fail_count = 0
                        degrade_duration = time.monotonic() - self._degrade_since
                        logger.info(
                            f"[QUOTE] 🔄 行情自动恢复成功(东方财富)! "
                            f"level {old_level}→0, 降级持续{degrade_duration:.0f}秒"
                        )
                        self._emit_quote_warning(
                            "行情已恢复正常(东方财富)",
                            {"recovered": True, "source": "eastmoney"}
                        )
                        return True
                except Exception as e:
                    logger.debug(f"[QUOTE] 东财恢复尝试失败(5分钟后重试): {e}")
            
            # 东财不行, 试新浪
            sina = self._data_router._sources.get("sina")
            if sina:
                try:
                    test_data = await sina.get_all_realtime(force_refresh=True)
                    if test_data and len(test_data) > 100:
                        # 新浪可用, 降级到 level 1(新浪回退模式)
                        if self._quote_degrade_level > 1:
                            self._quote_degrade_level = 1
                            degrade_duration = time.monotonic() - self._degrade_since
                            logger.info(
                                f"[QUOTE] 🔄 行情部分恢复(新浪)! "
                                f"level {old_level}→1, 降级持续{degrade_duration:.0f}秒"
                            )
                        return True
                except Exception as e:
                    logger.debug(f"[QUOTE] 新浪恢复尝试失败(5分钟后重试): {e}")
        
        logger.info(f"[QUOTE] 行情恢复失败, 当前level={self._quote_degrade_level}, 5分钟后重试")
        return False

    def get_status(self) -> Dict[str, Any]:
        """状态(供Scanner.get_status使用)"""
        staleness = self.get_staleness()
        # v2.9.105: 获取各数据源状态
        source_details = {}
        if self._data_router:
            for name, adapter in self._data_router._sources.items():
                if hasattr(adapter, 'get_status'):
                    source_details[name] = adapter.get_status()
        return {
            "degrade_level": self._quote_degrade_level,
            "degrade_desc": self.degrade_desc,
            "cached_stocks": len(self._realtime_cache),
            "data_sources": list(self._data_router._sources.keys()) if self._data_router else [],
            "source_details": source_details,
            "staleness_seconds": round(staleness, 1),
            "is_stale": staleness > 60,
            "degrade_duration_seconds": round(time.monotonic() - self._degrade_since, 1) if self._degrade_since > 0 else 0,
            "next_recover_in_seconds": max(0, round(self._recover_interval - (time.monotonic() - self._last_recover_attempt), 1)) if self._quote_degrade_level > 0 else 0,
        }

    async def _fallback_to_mongo_daily(self) -> Dict[str, Dict]:
        """【v2.9.75】Level 2降级: 从MongoDB stock_daily_ak_full读取最新日线作为行情源

        当东方财富实时和缓存都不可用时, 从MongoDB读取最近交易日日线数据。
        日线数据没有量比/换手率等盘中指标, 但有价格和涨跌幅, 足够止损止盈。
        """
        try:
            from core.managers import mongo_manager
            if not mongo_manager.is_initialized:
                return {}
            db = mongo_manager.get_database()

            # 找最近交易日
            latest = await db["stock_daily_ak_full"].find_one(
                sort=[("trade_date", -1)],
                projection={"trade_date": 1}
            )
            if not latest:
                return {}

            td_int = latest["trade_date"]
            cursor = db["stock_daily_ak_full"].find(
                {"trade_date": td_int},
                {"ts_code": 1, "close": 1, "pct_chg": 1, "open": 1, "high": 1,
                 "low": 1, "pre_close": 1, "vol": 1, "amount": 1}
            )

            realtime = {}
            async for doc in cursor:
                ts_code = doc.get("ts_code", "")
                if not ts_code:
                    continue
                realtime[ts_code] = {
                    "price": doc.get("close", 0),
                    "pct_chg": doc.get("pct_chg", 0),
                    "open": doc.get("open", 0),
                    "high": doc.get("high", 0),
                    "low": doc.get("low", 0),
                    "pre_close": doc.get("pre_close", 0),
                    "vol": doc.get("vol", 0),
                    "amount": doc.get("amount", 0),
                    "data_source": "mongo_daily",
                }

            if realtime:
                logger.info(f"[QUOTE] MongoDB日线fallback: {len(realtime)}只(日期={td_int})")
                # 更新缓存
                self._realtime_cache = realtime
                self._last_fetch_time = time.monotonic()
            return realtime
        except Exception as e:
            logger.warning(f"[QUOTE] MongoDB日线fallback失败: {e}")
            return {}
