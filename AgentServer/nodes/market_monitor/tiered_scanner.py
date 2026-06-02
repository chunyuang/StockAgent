#!/usr/bin/env python3
"""
TieredScanner — 三级行情扫描器

核心: 把全市场扫描拆成三级, 不同频率不同数据源, 降低延迟

Level 1 (全市场5400只, 5分钟): 东方财富免费接口
  - 初筛: 涨幅>3% + 量比>1.5 + 非ST + 流通市值>10亿
  - 输出: 候选池(约50-200只)

Level 2 (候选池50-200只, 30秒): 东方财富批量行情(仍免费)
  - 详细策略筛选: 复用回测 _build_strategy_filter_conditions
  - 输出: 策略信号(约5-20只)

Level 3 (持仓+信号股, 5秒): 东方财富实时(免费) + 必盈快照(有限次, 仅持仓股)
  - 止损止盈检查
  - 冲高回落检测
  - 跳空止损检测
  - 输出: 卖出信号 + 价格更新

设计原则:
1. 三级扫描独立运行, 各有自己的asyncio.Task
2. L1输出写入 self._candidate_pool (Dict[str, Dict])
3. L2从candidate_pool读取, 输出写入signals
4. L3从positions+signals读取, 输出止损止盈
5. 每级有独立的心跳时间戳, 供RiskWatchdog监控
6. 通过 set_scanner(scanner) 方法引用外层MarketScanner实例
7. start()/stop() 生命周期管理
8. get_status() 返回各级状态(上次扫描时间/候选数/信号数/延迟)

回调接口:
- on_l1_filter(candidates) -> filtered_candidates  (L1初筛后的回调)
- on_l2_strategy(candidates) -> signals            (L2策略筛选回调)
- on_l3_check(positions, signals) -> sell_signals  (L3止损止盈回调)
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable, Awaitable
from dataclasses import dataclass, field

logger = logging.getLogger("scanner.tiered")


# ──────────────────────────── 数据结构 ────────────────────────────

@dataclass
class LevelStatus:
    """单级扫描状态"""
    name: str = ""
    last_scan_time: float = 0.0        # time.time() 戳
    last_scan_time_str: str = ""       # 可读时间
    scan_count: int = 0
    candidate_count: int = 0
    signal_count: int = 0
    avg_latency_ms: float = 0.0
    error_count: int = 0
    last_error: str = ""
    is_running: bool = False


@dataclass
class TieredScanResult:
    """单次扫描结果"""
    level: int
    ts: float = 0.0
    input_count: int = 0
    output_count: int = 0
    latency_ms: float = 0.0
    error: str = ""


@dataclass
class SellSignal:
    """L3卖出信号"""
    ts_code: str
    stock_name: str = ""
    strategy: str = ""
    sell_reason: str = ""        # stop_loss / take_profit / surge_fall / gap_down / profit_lock
    current_price: float = 0.0
    cost_price: float = 0.0
    profit_pct: float = 0.0
    stop_loss_pct: float = 0.0
    take_profit_pct: float = 0.0
    scan_time: str = ""


# ──────────────────────────── 回调类型 ────────────────────────────

# L1回调: 全市场数据 -> 初筛后候选
L1FilterCallback = Callable[[Dict[str, Dict]], Awaitable[Dict[str, Dict]]]
# L2回调: 候选池 -> 策略信号列表
L2StrategyCallback = Callable[[Dict[str, Dict]], Awaitable[List[Dict]]]
# L3回调: 持仓+信号 -> 卖出信号列表
L3CheckCallback = Callable[[List[Dict], List[Dict]], Awaitable[List[SellSignal]]]


# ──────────────────────────── 主类 ────────────────────────────

class TieredScanner:
    """
    三级行情扫描器

    Level 1 (全市场5400只, 5分钟): 东方财富免费接口
      - 初筛: 涨幅>3% + 量比>1.5 + 非ST + 流通市值>10亿
      - 输出: 候选池(约50-200只)

    Level 2 (候选池50-200只, 30秒): 东方财富批量行情(仍免费)
      - 详细策略筛选: 复用回测 _build_strategy_filter_conditions
      - 输出: 策略信号(约5-20只)

    Level 3 (持仓+信号股, 5秒): 东方财富实时(免费) + 必盈快照(有限次, 仅持仓股)
      - 止损止盈检查
      - 冲高回落检测
      - 跳空止损检测
      - 输出: 卖出信号 + 价格更新
    """

    # ── 扫描间隔 ──
    L1_INTERVAL = 300   # 5分钟: 全市场初筛
    L2_INTERVAL = 30    # 30秒: 候选池策略筛选
    L3_INTERVAL = 5     # 5秒: 持仓止损止盈

    # ── L1初筛阈值(默认值, 可通过config覆盖) ──
    L1_MIN_PCT_CHG = 3.0           # 涨幅>3%
    L1_MIN_VOLUME_RATIO = 1.5      # 量比>1.5
    L1_MIN_FLOAT_MV = 10.0         # 流通市值>10亿(亿元)
    L1_EXCLUDE_ST = True           # 排除ST
    L1_EXCLUDE_NEW_STOCK_DAYS = 60  # 排除上市60天内新股

    def __init__(self, config: Dict = None):
        self._config = config or {}

        # ── 外部引用 ──
        self._scanner: Optional[Any] = None   # MarketScanner实例
        self._data_router: Optional[Any] = None  # DataSourceRouter

        # ── 数据存储 ──
        # L1候选池: {ts_code: {price, pct_chg, volume_ratio, ...}}
        self._candidate_pool: Dict[str, Dict] = {}
        # L2策略信号: [{ts_code, strategy, ...}]
        self._strategy_signals: List[Dict] = []
        # L3卖出信号: [SellSignal]
        self._sell_signals: List[SellSignal] = []
        # L3价格缓存: {ts_code: {price, high, low, ...}}
        self._price_cache: Dict[str, Dict] = {}

        # ── 回调 ──
        self._on_l1_filter: Optional[L1FilterCallback] = None
        self._on_l2_strategy: Optional[L2StrategyCallback] = None
        self._on_l3_check: Optional[L3CheckCallback] = None

        # ── 异步任务 ──
        self._l1_task: Optional[asyncio.Task] = None
        self._l2_task: Optional[asyncio.Task] = None
        self._l3_task: Optional[asyncio.Task] = None
        self._is_running = False

        # ── 各级状态 ──
        self._l1_status = LevelStatus(name="L1-全市场初筛")
        self._l2_status = LevelStatus(name="L2-策略筛选")
        self._l3_status = LevelStatus(name="L3-止损止盈")

        # ── 延迟统计 ──
        self._latency_history: Dict[int, List[float]] = {
            1: [], 2: [], 3: []
        }
        self._max_latency_samples = 20  # 保留最近20次延迟

        # ── 覆盖配置 ──
        self._apply_config()

    # ──────────────────────────── 配置 ────────────────────────────

    def _apply_config(self) -> None:
        """应用配置覆盖"""
        cfg = self._config.get("tiered_scanner", {})
        if not cfg:
            return

        for key, attr_name in [
            ("l1_interval", "L1_INTERVAL"),
            ("l2_interval", "L2_INTERVAL"),
            ("l3_interval", "L3_INTERVAL"),
            ("l1_min_pct_chg", "L1_MIN_PCT_CHG"),
            ("l1_min_volume_ratio", "L1_MIN_VOLUME_RATIO"),
            ("l1_min_float_mv", "L1_MIN_FLOAT_MV"),
            ("l1_exclude_st", "L1_EXCLUDE_ST"),
            ("l1_exclude_new_stock_days", "L1_EXCLUDE_NEW_STOCK_DAYS"),
        ]:
            if key in cfg:
                setattr(self, attr_name, cfg[key])

    # ──────────────────────────── 外部引用 ────────────────────────

    def set_scanner(self, scanner: Any) -> None:
        """设置外层MarketScanner实例引用"""
        self._scanner = scanner
        # 复用scanner的数据路由
        if hasattr(scanner, "_data_router") and scanner._data_router:
            self._data_router = scanner._data_router
        logger.info("[TIERED] 设置Scanner引用完成")

    # ──────────────────────────── 回调注册 ────────────────────────

    def on_l1_filter(self, callback: L1FilterCallback) -> None:
        """注册L1初筛回调: candidates -> filtered_candidates"""
        self._on_l1_filter = callback

    def on_l2_strategy(self, callback: L2StrategyCallback) -> None:
        """注册L2策略筛选回调: candidates -> signals"""
        self._on_l2_strategy = callback

    def on_l3_check(self, callback: L3CheckCallback) -> None:
        """注册L3止损止盈回调: positions+signals -> sell_signals"""
        self._on_l3_check = callback

    # ──────────────────────────── 生命周期 ────────────────────────

    async def start(self) -> None:
        """启动三级扫描"""
        if self._is_running:
            logger.warning("[TIERED] 已在运行, 忽略重复启动")
            return

        self._is_running = True
        logger.info(
            f"[TIERED] 启动三级行情扫描: "
            f"L1={self.L1_INTERVAL}s L2={self.L2_INTERVAL}s L3={self.L3_INTERVAL}s"
        )

        # 确保数据路由初始化
        await self._ensure_data_router()

        # 启动三级任务
        self._l1_task = asyncio.create_task(self._l1_loop(), name="tiered-l1")
        self._l2_task = asyncio.create_task(self._l2_loop(), name="tiered-l2")
        self._l3_task = asyncio.create_task(self._l3_loop(), name="tiered-l3")

        self._l1_status.is_running = True
        self._l2_status.is_running = True
        self._l3_status.is_running = True

    async def stop(self) -> None:
        """停止三级扫描"""
        if not self._is_running:
            return

        self._is_running = False
        logger.info("[TIERED] 停止三级行情扫描...")

        for task, name in [
            (self._l1_task, "L1"), (self._l2_task, "L2"), (self._l3_task, "L3")
        ]:
            if task and not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=5.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass

        self._l1_task = None
        self._l2_task = None
        self._l3_task = None

        self._l1_status.is_running = False
        self._l2_status.is_running = False
        self._l3_status.is_running = False

        logger.info("[TIERED] 已停止")

    # ──────────────────────────── 数据路由 ────────────────────────

    async def _ensure_data_router(self) -> None:
        """确保数据路由已初始化"""
        if self._data_router:
            return

        # 尝试从scanner获取
        if self._scanner and hasattr(self._scanner, "_data_router") and self._scanner._data_router:
            self._data_router = self._scanner._data_router
            return

        # 自行初始化
        try:
            from nodes.market_monitor.data_source_router import DataSourceRouter
            from src.data_sources.biying_adapter import BiyingAdapter
            from src.data_sources.eastmoney_adapter import EastmoneyAdapter

            router = DataSourceRouter()

            eastmoney = EastmoneyAdapter()
            router.register("eastmoney", eastmoney, priority=5)

            biying = BiyingAdapter(licence="E53CA0F0-3E85-4736-B22D-8FA41A5DB050")
            router.register("biying", biying, priority=10)

            await router.initialize_all()
            self._data_router = router
            logger.info("[TIERED] 数据路由初始化完成")
        except Exception as e:
            logger.error(f"[TIERED] 数据路由初始化失败: {e}")

    # ──────────────────────────── 辅助方法 ────────────────────────

    def _is_trading_time(self) -> bool:
        """是否在交易时间"""
        ct = datetime.now().strftime("%H:%M")
        return "09:15" <= ct <= "15:05"

    def _record_latency(self, level: int, latency_ms: float) -> None:
        """记录延迟"""
        history = self._latency_history.get(level, [])
        history.append(latency_ms)
        if len(history) > self._max_latency_samples:
            history.pop(0)
        self._latency_history[level] = history

    def _avg_latency(self, level: int) -> float:
        """平均延迟"""
        history = self._latency_history.get(level, [])
        if not history:
            return 0.0
        return sum(history) / len(history)

    def _update_status(self, status: LevelStatus, result: TieredScanResult) -> None:
        """更新扫描状态"""
        status.last_scan_time = result.ts
        status.last_scan_time_str = datetime.fromtimestamp(result.ts).strftime("%Y-%m-%d %H:%M:%S")
        status.scan_count += 1
        status.candidate_count = result.output_count
        if result.error:
            status.error_count += 1
            status.last_error = result.error
        else:
            status.last_error = ""

    # ──────────────────────────── L1: 全市场初筛 ─────────────────

    async def _l1_loop(self) -> None:
        """L1扫描循环: 全市场5分钟初筛"""
        logger.info(f"[L1] 全市场初筛循环启动, 间隔={self.L1_INTERVAL}s")

        while self._is_running:
            try:
                if not self._is_trading_time():
                    await asyncio.sleep(30)
                    continue

                result = await self._l1_scan()
                self._update_status(self._l1_status, result)

                if result.error:
                    logger.warning(f"[L1] 扫描出错: {result.error}")
                else:
                    logger.info(
                        f"[L1] 初筛完成: {result.input_count}只 → "
                        f"{result.output_count}只候选, "
                        f"延迟{result.latency_ms:.0f}ms"
                    )

                await asyncio.sleep(self.L1_INTERVAL)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[L1] 循环异常: {e}", exc_info=True)
                self._l1_status.error_count += 1
                self._l1_status.last_error = str(e)
                await asyncio.sleep(60)  # 出错后等待1分钟再重试

    async def _l1_scan(self) -> TieredScanResult:
        """L1单次扫描: 全市场初筛"""
        t0 = time.time()
        result = TieredScanResult(level=1, ts=t0)

        try:
            # 1. 获取全市场行情(东方财富, 免费)
            all_data = await self._fetch_l1_data()
            result.input_count = len(all_data)

            if not all_data:
                result.error = "东方财富全市场数据为空"
                return result

            # 2. 内置初筛: 涨幅>3% + 量比>1.5 + 非ST + 流通市值>10亿
            filtered = self._l1_builtin_filter(all_data)

            # 3. 回调筛选(如果有)
            if self._on_l1_filter:
                try:
                    filtered = await self._on_l1_filter(filtered)
                except Exception as e:
                    logger.warning(f"[L1] 回调异常: {e}")

            # 4. 写入候选池
            self._candidate_pool = filtered
            result.output_count = len(filtered)

        except Exception as e:
            result.error = str(e)
            logger.error(f"[L1] 扫描异常: {e}", exc_info=True)

        latency = (time.time() - t0) * 1000
        result.latency_ms = latency
        self._record_latency(1, latency)

        return result

    async def _fetch_l1_data(self) -> Dict[str, Dict]:
        """获取L1全市场行情数据"""
        # 优先从scanner获取
        if self._scanner and hasattr(self._scanner, "_fetch_realtime_batch"):
            try:
                data = await self._scanner._fetch_realtime_batch(force=True)
                if data:
                    return data
            except Exception as e:
                logger.warning(f"[L1] scanner._fetch_realtime_batch失败: {e}")

        # 从数据路由直接获取
        if self._data_router:
            eastmoney = self._data_router._sources.get("eastmoney")
            if eastmoney and hasattr(eastmoney, "get_all_realtime"):
                try:
                    return await eastmoney.get_all_realtime(force_refresh=True)
                except Exception as e:
                    logger.warning(f"[L1] 东方财富全市场获取失败: {e}")

        return {}

    def _l1_builtin_filter(self, data: Dict[str, Dict]) -> Dict[str, Dict]:
        """L1内置初筛逻辑

        筛选条件:
        - 涨幅 > L1_MIN_PCT_CHG (默认3%)
        - 量比 > L1_MIN_VOLUME_RATIO (默认1.5)
        - 非ST (如果L1_EXCLUDE_ST)
        - 流通市值 > L1_MIN_FLOAT_MV 亿 (默认10亿)
        """
        filtered = {}
        for ts_code, item in data.items():
            try:
                pct_chg = item.get("pct_chg", 0.0)
                if pct_chg is None:
                    continue
                if float(pct_chg) < self.L1_MIN_PCT_CHG:
                    continue

                volume_ratio = item.get("volume_ratio", 0.0)
                if volume_ratio is None:
                    continue
                if float(volume_ratio) < self.L1_MIN_VOLUME_RATIO:
                    continue

                # 非ST
                if self.L1_EXCLUDE_ST:
                    name = item.get("name", "")
                    if name and ("ST" in name.upper() or "*ST" in name):
                        continue

                # 流通市值
                float_mv = item.get("float_mv", 0.0)
                if float_mv is not None and float(float_mv) < self.L1_MIN_FLOAT_MV:
                    continue

                filtered[ts_code] = item

            except (ValueError, TypeError):
                continue

        return filtered

    # ──────────────────────────── L2: 策略筛选 ──────────────────

    async def _l2_loop(self) -> None:
        """L2扫描循环: 候选池策略筛选"""
        logger.info(f"[L2] 策略筛选循环启动, 间隔={self.L2_INTERVAL}s")

        while self._is_running:
            try:
                if not self._is_trading_time():
                    await asyncio.sleep(15)
                    continue

                result = await self._l2_scan()
                self._update_status(self._l2_status, result)

                if result.error:
                    logger.warning(f"[L2] 扫描出错: {result.error}")
                elif result.output_count > 0:
                    logger.info(
                        f"[L2] 策略筛选完成: {result.input_count}只候选 → "
                        f"{result.output_count}只信号, "
                        f"延迟{result.latency_ms:.0f}ms"
                    )

                await asyncio.sleep(self.L2_INTERVAL)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[L2] 循环异常: {e}", exc_info=True)
                self._l2_status.error_count += 1
                self._l2_status.last_error = str(e)
                await asyncio.sleep(30)

    @staticmethod
    def _build_price_cache_from_refreshed(refreshed: Dict) -> Dict:
        """从刷新行情构建价格缓存(供L3使用)【v2.9.63提取@staticmethod】"""
        cache = {}
        for code, item in refreshed.items():
            cache[code] = {
                "price": item.get("price"),
                "high": item.get("high"),
                "low": item.get("low"),
                "pct_chg": item.get("pct_chg"),
            }
        return cache

    async def _l2_scan(self) -> TieredScanResult:
        """L2单次扫描: 候选池策略筛选【v2.9.63: 价格缓存构建提取@staticmethod】"""
        t0 = time.time()
        result = TieredScanResult(level=2, ts=t0)

        try:
            candidates = self._candidate_pool
            result.input_count = len(candidates)

            if not candidates:
                # 无候选, 不算错误
                return result

            # 1. 刷新候选池行情(东方财富批量, 仍免费)
            refreshed = await self._refresh_l2_data(candidates)

            # 2. 回调策略筛选
            signals = []
            if self._on_l2_strategy:
                try:
                    signals = await self._on_l2_strategy(refreshed)
                except Exception as e:
                    logger.warning(f"[L2] 策略回调异常: {e}")
            else:
                # 无回调, 候选池直接作为信号
                signals = [
                    {"ts_code": code, "price": d.get("price", 0), **d}
                    for code, d in refreshed.items()
                ]

            # 3. 写入策略信号
            self._strategy_signals = signals
            result.output_count = len(signals)

            # 4. 更新价格缓存(供L3使用)
            self._price_cache.update(self._build_price_cache_from_refreshed(refreshed))

        except Exception as e:
            result.error = str(e)
            logger.error(f"[L2] 扫描异常: {e}", exc_info=True)

        latency = (time.time() - t0) * 1000
        result.latency_ms = latency
        self._record_latency(2, latency)

        return result

    async def _refresh_l2_data(self, candidates: Dict[str, Dict]) -> Dict[str, Dict]:
        """刷新L2候选池行情数据(东方财富批量接口)"""
        if not candidates:
            return {}

        codes = list(candidates.keys())

        # 从东方财富批量获取
        if self._data_router:
            eastmoney = self._data_router._sources.get("eastmoney")
            if eastmoney and hasattr(eastmoney, "get_realtime_quotes_batch"):
                try:
                    quotes = await eastmoney.get_realtime_quotes_batch(codes)
                    refreshed = {}
                    for ts_code, quote in quotes.items():
                        refreshed[ts_code] = {
                            **candidates.get(ts_code, {}),
                            **self._map_l2_quote_to_dict(quote),
                        }
                    return refreshed
                except Exception as e:
                    logger.warning(f"[L2] 东方财富批量获取失败: {e}, 使用缓存数据")

        # fallback: 使用候选池中的缓存数据
        return dict(candidates)

    # ──────────────────────────── L3: 止损止盈 ──────────────────

    async def _l3_loop(self) -> None:
        """L3扫描循环: 持仓止损止盈检查"""
        logger.info(f"[L3] 止损止盈循环启动, 间隔={self.L3_INTERVAL}s")

        while self._is_running:
            try:
                if not self._is_trading_time():
                    await asyncio.sleep(10)
                    continue

                result = await self._l3_scan()
                self._update_status(self._l3_status, result)

                if result.output_count > 0:
                    logger.info(
                        f"[L3] 止损止盈检查: {result.input_count}只持仓 → "
                        f"{result.output_count}只卖出信号, "
                        f"延迟{result.latency_ms:.0f}ms"
                    )

                await asyncio.sleep(self.L3_INTERVAL)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[L3] 循环异常: {e}", exc_info=True)
                self._l3_status.error_count += 1
                self._l3_status.last_error = str(e)
                await asyncio.sleep(10)

    @staticmethod
    def _collect_l3_refresh_codes(positions: list, signals: list) -> list:
        """收集L3需要刷新行情的代码列表(持仓+信号股)【v2.9.63提取】"""
        codes = [p.get("ts_code", "") for p in positions if p.get("ts_code")]
        for s in signals:
            code = s.get("ts_code", "")
            if code and code not in codes:
                codes.append(code)
        return codes

    async def _l3_scan(self) -> TieredScanResult:
        """L3单次扫描: 持仓止损止盈【v2.9.63: 代码收集提取@staticmethod】"""
        t0 = time.time()
        result = TieredScanResult(level=3, ts=t0)

        try:
            # 1. 获取当前持仓
            positions = self._get_positions()
            # 2. 获取当前策略信号(用于检查买入后回撤)
            signals = list(self._strategy_signals)

            result.input_count = len(positions)

            if not positions:
                self._sell_signals = []
                return result

            # 3. 刷新持仓+信号股行情
            codes_to_refresh = self._collect_l3_refresh_codes(positions, signals)
            prices = await self._fetch_l3_prices(codes_to_refresh)
            self._price_cache.update(prices)

            # 4. 回调止损止盈检查
            sell_signals = []
            if self._on_l3_check:
                try:
                    sell_signals = await self._on_l3_check(positions, signals)
                except Exception as e:
                    logger.warning(f"[L3] 止损止盈回调异常: {e}")
            else:
                # 内置基本止损止盈
                sell_signals = self._l3_builtin_check(positions, prices)

            # 5. 写入卖出信号
            self._sell_signals = sell_signals
            result.output_count = len(sell_signals)

        except Exception as e:
            result.error = str(e)
            logger.error(f"[L3] 扫描异常: {e}", exc_info=True)

        latency = (time.time() - t0) * 1000
        result.latency_ms = latency
        self._record_latency(3, latency)

        return result

    def _get_positions(self) -> List[Dict]:
        """获取当前持仓列表"""
        if self._scanner:
            # 从scanner获取持仓
            try:
                positions = self._scanner.get_positions()
                if positions:
                    return positions
            except Exception as e:
                logger.warning(f"[L3] 获取scanner持仓失败: {e}")

        return []

    @staticmethod
    def _map_quote_to_price_dict(quote: Any) -> Dict:
        """统一quote对象(属性/dict)→价格字典【v2.9.62提取】"""
        return {
            "price": getattr(quote, "price", None) or quote.get("price"),
            "pct_chg": getattr(quote, "pct_chg", None) or quote.get("pct_chg"),
            "high": getattr(quote, "high", None) or quote.get("high"),
            "low": getattr(quote, "low", None) or quote.get("low"),
            "open": getattr(quote, "open", None) or quote.get("open"),
            "pre_close": getattr(quote, "pre_close", None) or quote.get("pre_close"),
        }

    @staticmethod
    def _map_l2_quote_to_dict(quote: Any) -> Dict:
        """L2 quote→缓存字典【v2.9.62提取】"""
        return {
            "price": getattr(quote, "price", None) or quote.get("price"),
            "pct_chg": getattr(quote, "pct_chg", None) or quote.get("pct_chg"),
            "high": getattr(quote, "high", None) or quote.get("high"),
            "low": getattr(quote, "low", None) or quote.get("low"),
            "volume_ratio": getattr(quote, "volume_ratio", None) or quote.get("volume_ratio"),
            "turnover_rate": getattr(quote, "turnover_rate", None) or quote.get("turnover_rate"),
        }

    async def _fetch_l3_eastmoney_batch(self, codes: List[str]) -> Dict[str, Dict]:
        """L3东方财富批量获取【v2.9.62提取】"""
        prices = {}
        if not self._data_router:
            return prices
        eastmoney = self._data_router._sources.get("eastmoney")
        if not (eastmoney and hasattr(eastmoney, "get_realtime_quotes_batch")):
            return prices
        try:
            quotes = await eastmoney.get_realtime_quotes_batch(codes)
            for ts_code, quote in quotes.items():
                prices[ts_code] = self._map_quote_to_price_dict(quote)
        except Exception as e:
            logger.warning(f"[L3] 东方财富批量获取失败: {e}")
        return prices

    async def _fetch_l3_biying_snapshot(self, biying_codes: List[str]) -> Dict[str, Dict]:
        """L3必盈快照获取(仅持仓股)【v2.9.62提取】"""
        prices = {}
        if not biying_codes or not self._data_router:
            return prices
        biying = self._data_router._sources.get("biying")
        if not (biying and hasattr(biying, "get_realtime_quotes_batch")):
            return prices
        try:
            quotes = await biying.get_realtime_quotes_batch(biying_codes)
            for ts_code, quote in quotes.items():
                if ts_code not in prices:
                    prices[ts_code] = {}
                prices[ts_code].update({
                    "biying_price": getattr(quote, "price", None) or quote.get("price"),
                    "bid_price": getattr(quote, "bid1_price", None) or quote.get("bid1_price"),
                    "ask_price": getattr(quote, "ask1_price", None) or quote.get("ask1_price"),
                })
        except Exception as e:
            logger.warning(f"[L3] 必盈快照获取失败: {e}")
        return prices

    async def _fetch_l3_prices(self, codes: List[str]) -> Dict[str, Dict]:
        """L3价格获取: 东方财富实时 + 必盈快照(仅持仓股)

        东方财富: 免费, 无限次, 全部codes
        必盈: 有限次(~200次/天), 仅用于持仓股快照(5秒一次, 约10-30只)
        【v2.9.62重构: 提取两个子方法】
        """
        if not codes:
            return {}

        # 1. 东方财富批量实时(免费, 所有codes)
        prices = await self._fetch_l3_eastmoney_batch(codes)

        # 2. 必盈快照(仅持仓股, 5秒一次约10-30只, 远低于200次/天)
        positions = self._get_positions()
        position_codes = {p.get("ts_code", "") for p in positions}
        biying_codes = [c for c in codes if c in position_codes]
        biying_prices = await self._fetch_l3_biying_snapshot(biying_codes)

        # 必盈数据覆盖东方财富(更精确的买卖盘)
        for ts_code, bp in biying_prices.items():
            if ts_code not in prices:
                prices[ts_code] = {}
            prices[ts_code].update(bp)

        return prices

    def _l3_builtin_check(
        self, positions: List[Dict], prices: Dict[str, Dict]
    ) -> List[SellSignal]:
        """L3内置基本止损止盈检查(无回调时的fallback)

        仅做最基本的止损止盈, 复杂策略(冲高回落/利润保护)通过回调实现
        """
        sell_signals = []

        for pos in positions:
            signal = self._check_single_position_stop_profit(pos, prices)
            if signal:
                sell_signals.append(signal)

        return sell_signals

    def _check_single_position_stop_profit(
        self, pos: Dict, prices: Dict[str, Dict]
    ) -> Optional[SellSignal]:
        """单只持仓止损止盈检查【v2.9.61:从_l3_builtin_check提取】"""
        ts_code = pos.get("ts_code", "")
        if not ts_code:
            return None

        price_info = prices.get(ts_code, {})
        current_price = price_info.get("price") or price_info.get("biying_price")
        if not current_price:
            return None

        cost_price = pos.get("cost_price", 0)
        if not cost_price:
            return None

        profit_pct = (current_price - cost_price) / cost_price * 100
        stop_loss_pct = pos.get("stop_loss_pct", -3.0)
        take_profit_pct = pos.get("take_profit_pct", 7.0)

        if profit_pct <= stop_loss_pct:
            sell_reason = "stop_loss"
        elif profit_pct >= take_profit_pct:
            sell_reason = "take_profit"
        else:
            return None

        return SellSignal(
            ts_code=ts_code,
            stock_name=pos.get("stock_name", ""),
            strategy=pos.get("strategy", ""),
            sell_reason=sell_reason,
            current_price=current_price,
            cost_price=cost_price,
            profit_pct=profit_pct,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            scan_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

    # ──────────────────────────── 状态查询 ────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """获取三级扫描器状态"""
        return {
            "is_running": self._is_running,
            "l1": self._level_status_dict(self._l1_status),
            "l2": self._level_status_dict(self._l2_status),
            "l3": self._level_status_dict(self._l3_status),
            "candidate_pool_size": len(self._candidate_pool),
            "strategy_signal_count": len(self._strategy_signals),
            "sell_signal_count": len(self._sell_signals),
            "price_cache_size": len(self._price_cache),
            "config": {
                "l1_interval": self.L1_INTERVAL,
                "l2_interval": self.L2_INTERVAL,
                "l3_interval": self.L3_INTERVAL,
                "l1_min_pct_chg": self.L1_MIN_PCT_CHG,
                "l1_min_volume_ratio": self.L1_MIN_VOLUME_RATIO,
                "l1_min_float_mv": self.L1_MIN_FLOAT_MV,
            },
        }

    def _level_status_dict(self, status: LevelStatus) -> Dict[str, Any]:
        """LevelStatus转dict"""
        return {
            "name": status.name,
            "is_running": status.is_running,
            "last_scan_time": status.last_scan_time_str,
            "scan_count": status.scan_count,
            "candidate_count": status.candidate_count,
            "signal_count": status.signal_count,
            "avg_latency_ms": round(self._avg_latency(
                {"L1-全市场初筛": 1, "L2-策略筛选": 2, "L3-止损止盈": 3}.get(status.name, 0)
            ), 1),
            "error_count": status.error_count,
            "last_error": status.last_error,
        }

    def get_candidate_pool(self) -> Dict[str, Dict]:
        """获取L1候选池"""
        return dict(self._candidate_pool)

    def get_strategy_signals(self) -> List[Dict]:
        """获取L2策略信号"""
        return list(self._strategy_signals)

    def get_sell_signals(self) -> List[SellSignal]:
        """获取L3卖出信号"""
        return list(self._sell_signals)

    def get_price_cache(self) -> Dict[str, Dict]:
        """获取L3价格缓存"""
        return dict(self._price_cache)

    def get_heartbeats(self) -> Dict[str, float]:
        """获取各级心跳时间戳(供RiskWatchdog监控)"""
        return {
            "l1": self._l1_status.last_scan_time,
            "l2": self._l2_status.last_scan_time,
            "l3": self._l3_status.last_scan_time,
        }

    # ──────────────────────────── 手动触发 ────────────────────────

    async def force_l1_scan(self) -> TieredScanResult:
        """手动触发L1扫描"""
        logger.info("[TIERED] 手动触发L1扫描")
        result = await self._l1_scan()
        self._update_status(self._l1_status, result)
        return result

    async def force_l2_scan(self) -> TieredScanResult:
        """手动触发L2扫描"""
        logger.info("[TIERED] 手动触发L2扫描")
        result = await self._l2_scan()
        self._update_status(self._l2_status, result)
        return result

    async def force_l3_scan(self) -> TieredScanResult:
        """手动触发L3扫描"""
        logger.info("[TIERED] 手动触发L3扫描")
        result = await self._l3_scan()
        self._update_status(self._l3_status, result)
        return result
