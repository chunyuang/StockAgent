#!/usr/bin/env python3
"""
MarketScanner — 超短量化市场扫描器

核心: 把回测引擎的选股逻辑搬到实时数据上跑
- 每30秒扫描全市场(必盈实时行情)
- 合并日级因子(盘前预加载) + 实时因子(盘中提取)
- 策略筛选(复用 _build_strategy_filter_conditions)
- 信号→模拟执行→止损止盈
"""
import asyncio
import logging
import os
import threading
import time
from datetime import datetime
from typing import Callable, Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field

import pandas as pd

from nodes.market_monitor.quote_manager import QuoteManager
from nodes.market_monitor.scanner_event_bus import ScannerEventBus, ScannerEvents
from nodes.market_monitor.scanner_initializer import ScannerInitializer
from nodes.market_monitor.scan_loop_runner import ScanLoopRunner
from nodes.market_monitor.risk_loop_runner import RiskLoopRunner

logger = logging.getLogger("scanner.market")


class _StepTimer:
    """扫描步骤分步计时器【v2.9.55从scan_once提取】
    
    用法:
        timer = _StepTimer()
        with timer.step("行情"):
            data = await fetch()
        with timer.step("因子"):
            df = merge(data)
        timer.log_summary(scan_count, total_stocks, signal_count, elapsed)
    """
    __slots__ = ('_steps', '_current_name', '_current_t0')

    def __init__(self) -> None:
        self._steps: List[Tuple[str, float]] = []
        self._current_name: str = ""
        self._current_t0: float = 0.0

    def step(self, name: str) -> '_StepTimer':
        """返回上下文管理器,记录步骤耗时(ms)"""
        self._current_name = name
        self._current_t0 = time.time()
        return self

    def __enter__(self) -> '_StepTimer':
        return self

    def __exit__(self, *exc) -> None:
        elapsed_ms = (time.time() - self._current_t0) * 1000
        self._steps.append((self._current_name, elapsed_ms))

    def get_slow_info(self) -> str:
        """生成慢步骤日志摘要"""
        if not self._steps:
            return ""
        # 委托给ScannerUtils.format_slow_steps(如果可用), 否则内联
        parts = []
        for name, ms in self._steps:
            if ms > 500:
                parts.append(f"{name}={ms:.0f}ms")
        return f" | 慢:{','.join(parts)}" if parts else ""

    @property
    def steps(self) -> List[Tuple[str, float]]:
        return self._steps



from nodes.market_monitor.market_phase import MarketPhase  # 【v2.9.67提取到独立模块】
from nodes.market_monitor.scanner_accessors_mixin import ScannerAccessorsMixin  # 【v2.9.99提取只读访问器】


@dataclass
class ScanSignal:
    """扫描信号"""
    ts_code: str
    stock_name: str
    strategy: str
    strategy_name: str
    signal_type: str = "buy"  # buy/sell
    price: float = 0.0
    pct_chg: float = 0.0
    volume_ratio: float = 0.0
    turnover_rate: float = 0.0
    is_limit_up: bool = False
    limit_up_count: int = 0
    confidence: float = 0.8
    reason: str = ""
    scan_time: str = ""
    factors: Dict[str, float] = field(default_factory=dict)
    # 【实盘审查增强】决策详情
    decision_detail: Dict[str, Any] = field(default_factory=dict)  # 完整决策链路
    # 【调试增强】逐层筛选中间结果
    layer_trace: Dict[str, Any] = field(default_factory=dict)  # 每层筛选的输入/输出/过滤原因
    # 信号状态
    signal_status: str = "new"  # new/executed/expired/skipped
    # 信号创建时间(用于过期判断)
    created_at: float = 0.0  # time.time()戳

    def to_candidate(self) -> Dict[str, Any]:
        """转换为filter_pipeline候选格式【v2.9.35】"""
        return {
            "ts_code": self.ts_code,
            "stock_name": self.stock_name,
            "strategy": self.strategy,
            "strategy_name": self.strategy_name,
            "price": self.price,
            "pct_chg": self.pct_chg,
            "volume_ratio": self.volume_ratio,
            "turnover_rate": self.turnover_rate,
            "is_limit_up": self.is_limit_up,
            "limit_up_count": self.limit_up_count,
            "reason": self.reason,
            "confidence": self.confidence,
        }


@dataclass
class PositionStatus:
    """持仓状态"""
    ts_code: str
    stock_name: str
    strategy: str
    shares: int = 0
    cost_price: float = 0.0
    current_price: float = 0.0
    profit_pct: float = 0.0
    stop_loss_pct: float = -3.0   # 默认-3%(策略级覆盖:半路-4%/龙头-3%/跌停-5%,从STRATEGY_CONFIGS读取)
    take_profit_pct: float = 7.0   # 默认7%(策略级覆盖:半路12%/龙头30%/跌停20%,从STRATEGY_CONFIGS读取)
    hold_minutes: int = 0
    should_sell: bool = False
    sell_reason: str = ""


class MarketScanner(ScannerInitializer, ScanLoopRunner, RiskLoopRunner, ScannerAccessorsMixin):
    """超短量化市场扫描器"""

    # 扫描配置
    SCAN_INTERVAL = 300    # 全量扫描间隔(秒): 涨停池+策略筛选, 5分钟
    POSITION_CHECK_INTERVAL = 30  # 持仓检查间隔(秒): 常规30秒
    POSITION_CHECK_FAST = 10      # 持仓快速检查(秒): 接近止损位10秒级
    POSITION_CHECK_CRITICAL = 5   # 持仓紧急检查(秒): 已触及止损区5秒级
    BATCH_SIZE = 100    # 批量行情每批处理数
    MAX_POSITIONS = 10  # 最大持仓数
    MAX_POSITION_RATIO = 0.7  # 最大仓位比例
    SIGNAL_EXPIRE_SECONDS = 300  # 信号过期时间(秒): 5分钟后信号失效
    SIGNAL_EXPIRE_ACTION = True   # 过期信号是否自动取消买入(后端强制)

    EMOTION_DOWNGRADE_RULES: Optional[Dict] = None  # 已迁移至EmotionCycleManager.DOWNGRADE_RULES【v3.0】,保留类属性兼容

    # 交易模式
    MODE_SIMULATED = "simulated"  # 内置仿真撮合
    MODE_GM = "gm"                # 掘金量化
    MODE_DRY_RUN = "dry_run"      # 调试模式: 只扫描不交易
    MODE_REPLAY = "replay"        # 回放模式: 用历史数据模拟实时行情

    # ==================== 类属性默认值(不可变/标量)【v2.9.37, v2.9.73补齐访问器依赖】 ====================
    _risk_thread = None
    _risk_running: bool = False
    _risk_thread_restarts: int = 0
    _cache_lock = None
    _state_lock: threading.Lock = None  # type: ignore[assignment]  # 初始化在__init__中完成
    _loop = None
    _last_snapshot_save: float = 0.0
    _snapshot_dirty: bool = False
    _trade_date: str = ""
    _nav_peak: float = 1.0
    _quote_degrade_level: int = 0
    _quote_fail_count: int = 0
    _quote_last_recover_check: float = 0.0
    _is_running: bool = False
    _start_time: float = 0.0  # v2.9.86: 启动时间戳(供uptime计算)
    _task = None
    _scan_count: int = 0
    _last_scan_time: str = ""
    _last_scan_ts: float = 0.0
    _last_risk_check_ts: float = 0.0
    _last_realtime_update_ts: float = 0.0
    _scan_loop_error_count: int = 0
    _event_bus: Optional[ScannerEventBus] = None
    _circuit_breaker: Optional[Dict] = None  # v2.9.73: 类属性默认值(原在_init_state) 【v2.9.85: Dict→None防共享可变状态】
    _current_sentiment: Optional[Dict] = None  # v2.9.73 【v2.9.85: Dict→None防共享可变状态】
    _current_position_ratio: Optional[float] = None  # v2.9.73

    def __init__(self, account_id: str = "default", config: Dict = None):
        self.account_id = account_id
        self.config = config or {}

        # 分阶段初始化
        self._init_state()
        self._init_broker()
        self._init_pipeline()
        self._init_modules()
        self._init_risk()

    # ==================== 初始化子方法 ====================

    # ==================== 初始化方法(ScannerInitializer混入) ====================
    # _init_state/_init_broker/_init_pipeline/_init_modules/_init_risk
    # 已提取到 scanner_initializer.py ScannerInitializer 混入类【v2.9.67】

    # 保留_DELEGATE_MAP类属性作为兼容别名(测试代码引用MarketScanner._DELEGATE_MAP)
    @classmethod
    @property
    def _DELEGATE_MAP(cls) -> Dict:
        """兼容别名: 指向scanner_delegate_router.DELEGATE_MAP【v2.9.52】"""
        from nodes.market_monitor.scanner_delegate_router import DELEGATE_MAP
        return DELEGATE_MAP

    def __getattr__(self, name):
        """动态委托分派 — 纯转发方法不再需要显式定义【v2.9.3, v2.9.17:委托路由提取, v2.9.52:MAP外提】"""
        from nodes.market_monitor.scanner_delegate_router import DELEGATE_MAP, resolve_delegate
        delegate = DELEGATE_MAP.get(name)
        if delegate is None:
            raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")
        return resolve_delegate(self, name, delegate)


    @property
    def event_bus(self) -> ScannerEventBus:
        """事件总线(只读)"""
        return self._event_bus

    def is_running(self) -> bool:
        return self._is_running

    # ==================== 📚 生命周期 ====================
    def get_status(self) -> Dict[str, Any]:
        """Scanner完整状态快照"""
        # 子模块状态(安全读取, 无boker时返回空dict)
        module_status = self._build_module_status()
        return {
            "is_running": self._is_running,
            "scan_count": self._stats.get("scans", self._scan_count),  # 【v2.9.89修复】优先用持久化的stats.scans,避免重启后归零
            "last_scan_time": self._last_scan_time,
            "active_signals": len(self._active_signals),
            "positions": len(self.get_positions()),
            "stocks_scanned": len(self._realtime_cache),
            "account": self._build_account_info(),
            "stats": self._stats,
            "account_id": self.account_id,
            "trade_mode": self._trade_mode,
            "filter_pipeline": {
                "position_ratio": self._current_position_ratio,
                "sentiment": self._current_sentiment or {},
            },
            **module_status,
            "trailing_stops": self._get_activated_trailing_stops_safe(),
            "position_risk_levels": self._safe_copy_position_risk_levels(),
            "execution_stats": dict(self._execution_stats),
            "scan_loop_errors": self._scan_loop_error_count,
            "last_realtime_update_ts": self._last_realtime_update_ts,
            "realtime_cache_age_sec": round(time.time() - (self._last_realtime_update_ts or 0), 1) if self._last_realtime_update_ts else None,
            "smart_check_interval": self._get_smart_check_interval(self._broker.get_positions() if self._broker else []) if self._is_running else None,
            "sell_logic_mode": self.SELL_LOGIC_MODE,
            "health": self._compute_health_score(),
        }

    def _build_module_status(self) -> Dict[str, Any]:
        """读取子模块状态(risk_watchdog/signal_dispatcher/tiered_scanner/quote)【v2.9.33提取】"""
        result = {}
        result["risk_watchdog"] = self._risk_watchdog.get_status() if self._risk_watchdog else {}
        result["signal_dispatcher"] = self._signal_dispatcher.get_stats() if self._signal_dispatcher else {}
        result["tiered_scanner"] = self._tiered_scanner.get_status() if self._tiered_scanner else {}
        result["quote_degrade_level"] = self._quote_manager.degrade_level
        result["quote_degrade_desc"] = self._quote_manager.degrade_desc
        return result

    # _build_account_info已提取到ScannerUtils【v2.9.27:DELEGATE_MAP动态委托】

    def get_signals(self) -> List[Dict]:
        result = [self._signal_to_dict(s) for s in self._active_signals]
        # 填充空名称
        for r in result:
            if not r.get("stock_name"):
                r["stock_name"] = self._stock_name_map.get(r.get("ts_code", ""), "")
        return result

    def get_positions(self) -> List[Dict]:
        """获取当前持仓列表(含追踪止损+风险等级)"""
        if self._trade_mode == self.MODE_GM and self._gm_broker:
            return self._gm_broker.get_positions()
        if not self._broker:
            return []
        trailing_copy = self._safe_copy_trailing_stops()
        risk_levels_copy = self._safe_copy_position_risk_levels()
        return [
            self._build_position_dict(p, trailing_copy, risk_levels_copy)
            for p in self._broker.get_positions()
        ]

    def get_timeline(self) -> List[Dict]:
        result = list(self._timeline)
        # 【v2.9.79】补全空stock_name(旧数据或实时行情无name时)
        # 如果name_map为空, 先从MongoDB加载(首次调用时)
        if not self._stock_name_map:
            try:
                from pymongo import MongoClient
                client = MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=2000)
                docs = list(client["stock_agent"]["stock_basic"].find(
                    {}, {"ts_code": 1, "name": 1, "_id": 0}
                ).limit(10000))
                for doc in docs:
                    if doc.get("ts_code") and doc.get("name"):
                        self._stock_name_map[doc["ts_code"]] = doc["name"]
                pass
            except Exception as _e:
                logger.debug(f"[GUARD] scanner: {_e}")
        # 补全空stock_name
        for t in result:
            if not t.get("stock_name"):
                t["stock_name"] = self._stock_name_map.get(t.get("ts_code", ""), "")
        return result
    async def start(self, trade_date: str = None) -> Dict:
        """启动扫描【v2.9.55: 初始化序列提取到_start_init_sequence】"""
        if self._is_running:
            return {"success": True, "message": "已在运行中"}

        # 【Phase1.2:提前初始化线程锁(被premarket_prepare/_load_positions使用)】
        if self._state_lock is None:
            self._state_lock = threading.Lock()

        if not trade_date:
            trade_date = datetime.now().strftime("%Y%m%d")
        self._trade_date = trade_date

        # 初始化序列(参数校验+加载+恢复+注册)
        await self._start_init_sequence(trade_date)
        
        # 启动主循环
        self._is_running = True
        self._start_time = time.time()  # v2.9.86: 记录启动时间
        self._task = asyncio.create_task(self._scan_loop(trade_date))
        
        # 【Phase1.2:启动风控独立线程】
        self._start_risk_thread()
        
        # 【V54:启动分级行情扫描器】
        if self._tiered_scanner:
            await self._tiered_scanner.start(trade_date)
        # 恢复今日时间线
        logger.info("[SCANNER] 加载时间线...")
        await self._load_timeline()
        logger.info(f"[SCANNER] 启动完成, account={self.account_id}, date={trade_date}")
        
        # 【V67:启动时自动保存参数快照(供月复盘参数漂移检测)】
        await self._save_param_snapshot(trade_date)
        
        return {"success": True, "message": "扫描器启动成功"}

    async def _start_init_sequence(self, trade_date: str) -> None:
        """启动前初始化序列【v2.9.55从start()提取】
        
        包含: 参数校验→策略加载→漂移检测→盘前准备→资产记录→状态恢复→事件订阅
        """
        # 实盘参数校验
        self._validate_live_params()

        # 【P1-4】从MongoDB恢复策略参数覆盖
        await self._load_strategy_overrides()
        
        # 【Phase2.3:参数漂移检测(启动时)】
        await self._detect_param_drift()

        # 盘前准备
        await self.premarket_prepare(trade_date)
        
        # 【v2.9.51】记录日内起始资产(供RiskWatchdog日内回撤检查)
        account = self._broker.get_account()
        self._daily_start_asset = account.total_assets
        
        # 【Phase3.4+v2.9.4】审计日志TTL索引+恢复pending_sells
        await self._restore_start_state()

        # 【v2.8:EventBus订阅器注册(在scan_loop启动前)】
        try:
            from nodes.market_monitor.scanner_event_subscribers import register_subscribers
            register_subscribers(self)
        except (ImportError, AttributeError) as e:
            logger.warning(f"[EVENT_BUS] 订阅器注册失败(非关键): {e}")

    # DELEGATE_MAP条目即委托文档, 不再逐一注释
    # 【v2.9.42: _save_param_snapshot/_detect_param_drift/_validate_live_params/update_strategy_config
    #   /_persist_strategy_overrides/_load_strategy_overrides 均已加入DELEGATE_MAP动态委托】

    async def _restore_start_state(self) -> None:
        """启动时恢复状态 — 委托给RuntimePersistence【v2.9.32提取】"""
        await self._runtime_persistence.restore_start_state()

    def _start_risk_thread(self) -> None:
        """启动风控独立线程【v2.9.18:从start()提取】"""
        self._loop = asyncio.get_event_loop()
        self._cache_lock = threading.Lock()
        if self._state_lock is None:
            self._state_lock = threading.Lock()
        self._risk_running = True
        self._risk_thread_restarts = 0
        self._risk_thread = threading.Thread(
            target=self._risk_loop_sync, daemon=True,
            name="scanner-risk-thread"
        )
        self._risk_thread.start()
        logger.info("[SCANNER] 风控独立线程已启动")

    async def stop(self, sell_all: bool = False) -> Dict:
        """停止扫描【v2.9.55:清理逻辑提取到_stop_cleanup】"""
        self._is_running = False
        
        # 停止风控独立线程
        self._risk_running = False
        if self._risk_thread and self._risk_thread.is_alive():
            self._risk_thread.join(timeout=5)
            logger.info("[SCANNER] 风控线程已停止")
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # 停止分级行情扫描器
        if self._tiered_scanner:
            await self._tiered_scanner.stop()
        
        # 清仓+持久化+数据源清理
        await self._stop_cleanup(sell_all)
        
        logger.info(f"[SCANNER] 已停止 (清仓={sell_all})")
        return {"success": True, "message": f"扫描器已停止" + ("并清仓" if sell_all else "")}

    async def _stop_cleanup(self, sell_all: bool) -> None:
        """停止后清理(清仓+持久化+数据源关闭)【v2.9.55从stop()提取】"""
        # 清仓选项
        if sell_all and self._broker:
            await self._sell_all_positions()
        
        # 持久化+清理
        await self._persist_stop_state()
        
        # 关闭数据源
        if self._data_router:
            try:
                await self._data_router.close_all()
            except (OSError, RuntimeError) as e:
                logger.warning(f"[SCANNER] 数据源关闭失败: {e}")
            self._data_router = None

    async def _liquidate_positions(self, reason: str, source: str) -> Tuple[int, int]:
        """批量清仓 — 委托给PositionManager【v2.9.35提取】"""
        return await self._position_manager.liquidate_positions(reason, source)

    async def _sell_all_positions(self) -> None:
        """停止时清仓所有持仓【v2.9.18:从stop()提取, v2.9.20:复用_liquidate_positions】"""
        await self._liquidate_positions(reason="停止清仓", source="stop_sell")

    async def emergency_liquidate(self, reason: str = "手动触发") -> Dict:
        """紧急清仓 — 委托给RiskWatchdog【v2.9.45:修复Daemon IPC路径断裂】

        之前: Daemon._cmd_emergency_liquidate 调用 scanner.emergency_liquidate()
              但scanner上无此方法,通过Daemon IPC发送紧急清仓会静默失败。
        修复: scanner新增emergency_liquidate方法,委托给RiskWatchdog。
        """
        if self._risk_watchdog:
            return await self._risk_watchdog.emergency_liquidate(reason)
        return {"success": False, "error": "RiskWatchdog未初始化"}

    async def _persist_stop_state(self) -> None:
        """停止时持久化状态 — 委托给RuntimePersistence【v2.9.32提取】"""
        # 【v2.9.92x】收盘后刷新持仓收盘价(解决收盘后current_price不更新问题)
        if self._broker and self.get_positions():
            try:
                await self._broker.refresh_close_prices()
            except Exception as e:
                logger.debug(f"[SCANNER] 收盘价刷新异常: {e}")
        await self._runtime_persistence.persist_stop_state()

    # ==================== 盘前准备 ====================


    def _update_name_map(self, realtime_data: Dict[str, Dict]) -> None:
        """从实时行情数据更新ts_code→stock_name映射
        
        【v2.9.79】增强: 当_name_map为空时, 从MongoDB stock_basic加载全量名称映射
        """
        # 首次调用时从MongoDB加载全量名称映射(非阻塞同步fallback)
        names_loaded = False
        if not self._stock_name_map:
            try:
                from pymongo import MongoClient
                client = MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=2000)
                docs = list(client["stock_agent"]["stock_basic"].find(
                    {}, {"ts_code": 1, "name": 1, "_id": 0}
                ).limit(10000))
                for doc in docs:
                    if doc.get("ts_code") and doc.get("name"):
                        self._stock_name_map[doc["ts_code"]] = doc["name"]
                names_loaded = len(self._stock_name_map) > 0
                logger.info(f"[SCANNER] 从stock_basic加载{len(self._stock_name_map)}只股票名称映射")
            except Exception as e:
                logger.warning(f"[SCANNER] 从stock_basic加载名称映射失败: {e}")
        
        # 从实时行情补充名称(优先级更高)
        updated = False
        for ts_code, rt in realtime_data.items():
            name = rt.get("name", "")
            if name and ts_code not in self._stock_name_map:
                self._stock_name_map[ts_code] = name
                updated = True
        # 同步名称映射到strategy_scorer(每次scan都同步, 确保scorer名称映射最新)
        if self._strategy_scorer:
            self._strategy_scorer.update_name_map(self._stock_name_map)

    def _get_stock_name(self, ts_code: str) -> str:
        """获取股票名称(带缓存)"""
        if ts_code in self._stock_name_map:
            return self._stock_name_map[ts_code]
        return ""

    async def _load_stock_name_map(self) -> None:
        """加载名称映射 — 委托给RuntimePersistence【v2.9.32提取】"""
        names = await self._runtime_persistence.load_stock_name_map()
        self._stock_name_map.update(names)
    async def _warm_weekend_cache(self) -> None:
        """周末调试: 用日级因子填充行情缓存 — 委托给RuntimePersistence【v2.9.32提取】"""
        realtime = self._runtime_persistence.warm_weekend_cache(
            self._daily_factors_df, self._stock_name_map, self._quote_manager
        )
        self._realtime_cache = realtime
        self._last_realtime_update_ts = time.time()

    def _reset_daily_risk_state(self) -> None:
        """重置每日风控状态 — 委托给RiskWatchdog【v2.9.32提取】"""
        from nodes.market_monitor.risk_watchdog import RiskWatchdog
        RiskWatchdog.reset_daily_risk_state(self)

    async def premarket_prepare(self, trade_date: str) -> None:
        """盘前: 加载全市场代码 + 预加载日级因子【v2.9.55:步骤提取为_load_premarket_data】"""
        logger.info(f"[SCANNER] 盘前准备 {trade_date}")

        # 重置每日风控(circuit_breaker+pending_sells+执行统计)
        self._reset_daily_risk_state()

        # 加载数据(代码+因子+名称+持仓)
        await self._load_premarket_data(trade_date)

        # 竞价预选(仅竞价阶段9:15-9:30)
        await self._check_premarket_auction(trade_date)

        # 周末调试: 用日级因子填充行情缓存
        if datetime.now().weekday() >= 5 and self._daily_factors_df is not None:
            await self._warm_weekend_cache()
        
        logger.info(f"[SCANNER] 准备完成: {len(self._all_codes)}只股票, "
                     f"{len(self._daily_factors_df) if self._daily_factors_df is not None else 0}条因子, "
                     f"{len(self._active_signals)}个竞价信号")

    async def _load_premarket_data(self, trade_date: str) -> None:
        """盘前数据加载(代码+因子+名称+持仓)【v2.9.55从premarket_prepare提取】"""
        # 1. 获取全市场代码
        await self._load_stock_list()

        # 2. 预加载前日因子
        await self._load_daily_factors(trade_date)
        await self._load_stock_name_map()
        if self._strategy_scorer:
            self._strategy_scorer.update_name_map(self._stock_name_map)

        # 3. 加载当前持仓
        logger.info("[SCANNER] 开始加载持仓...")
        await self._load_positions()
        logger.info("[SCANNER] 持仓加载完成")

    async def _check_premarket_auction(self, trade_date: str) -> None:
        """竞价预选检查【v2.9.55从premarket_prepare提取】
        
        9:00-9:15: 仅检查持仓跳空
        9:15-9:30: 运行premarket_scan生成今日全市场候选
        """
        now = datetime.now()
        ct = now.strftime("%H:%M")
        if "09:15" <= ct <= "09:30":
            await self._runtime_persistence.premarket_auction()
            # 启动时如果在竞价窗口, 立即运行一次premarket_scan
            try:
                await self.premarket_scan(trade_date)
            except Exception as e:
                logger.warning(f"[SCANNER] 启动时premarket_scan失败: {e}")
        else:
            logger.debug(f"[SCANNER] 非竞价时间({ct}), 跳过竞价预选")

    async def premarket_scan(self, trade_date: str) -> int:
        """盘前竞价扫描【9:00-9:25用】
        
        运行L4(盘前预选)+L5(竞价过滤)+L6(策略量能)生成今日竞价候选。
        不执行交易, 仅生成预览信号供premarket-status API返回。
        
        与scan_once区别:
        - 不检测异动(detect_anomalies)
        - 不执行交易(不进入下单环节)
        - 不检查持仓止损
        - 只生成信号+过滤运算
        
        Returns:
            生成的预览候选数
        """
        import time
        from datetime import datetime
        t0 = time.time()
        scan_dt = datetime.now()
        scan_time = scan_dt.strftime("%H:%M:%S")
        scan_time_iso = scan_dt.isoformat()
        logger.info(f"[PREMARKET-SCAN] 开始竞价扫描 {scan_time}")
        
        try:
            # Step 1: 获取实时行情(force=True忽略交易时间检查)
            realtime_data = await self._fetch_realtime_batch(force=True)
            if not realtime_data:
                logger.warning("[PREMARKET-SCAN] 实时数据为空, 跳过")
                await self._save_premarket_snapshot(trade_date, scan_time_iso, note="实时数据为空")
                return 0
            
            # Step 2: 补充auction_pct字段(竞价阶段: open=auction_price)
            for ts_code, rt in realtime_data.items():
                op = rt.get("open", 0)
                pc = rt.get("pre_close", 0)
                if op and pc and pc > 0:
                    rt["opening_pct_chg"] = round((op - pc) / pc * 100, 2)
                    rt["auction_price"] = op
                    rt["auction_pct"] = rt["opening_pct_chg"]
            
            # 【v2.9.108】竞价风控状态机: 更新force_empty_confirm
            # 之前premarket_scan不调用此方法, 导致data_quality永远=unknown
            self._update_premarket_force_empty_state(None, realtime_data)
            
            # Step 3: 合并日级因子+实时数据
            self._update_name_map(realtime_data)
            merged_df = self._merge_factors(realtime_data)
            if merged_df is None or len(merged_df) == 0:
                logger.warning("[PREMARKET-SCAN] 合并后数据为空")
                await self._save_premarket_snapshot(trade_date, scan_time_iso, realtime_data=realtime_data, note="合并后数据为空")
                return 0
            
            # Step 4: 运行策略筛选
            new_signals = await self._apply_strategies(merged_df, trade_date)
            if not new_signals:
                logger.info("[PREMARKET-SCAN] 无策略信号")
                await self._save_premarket_snapshot(trade_date, scan_time_iso, realtime_data=realtime_data, strategy_candidates=[], passed_signals=[], note="无策略信号")
                return 0
            
            # Step 5: 运行筛选管道(L1-L9)
            strategy_candidates = list(new_signals)
            new_signals = await self._apply_filter_pipeline(new_signals, trade_date, realtime_data)
            await self._save_premarket_snapshot(
                trade_date, scan_time_iso,
                realtime_data=realtime_data,
                strategy_candidates=strategy_candidates,
                passed_signals=new_signals,
            )
            
            # Step 6: 增量更新信号(使之出premarket-status API)
            await self._update_signals(new_signals, scan_time)
            
            elapsed = time.time() - t0
            logger.info(f"[PREMARKET-SCAN] 完成: {len(realtime_data)}只 | "
                       f"{len(new_signals)}信号 | {len(self._active_signals)}总信号 | {elapsed:.1f}秒")
            return len(new_signals)
        except Exception as e:
            logger.error(f"[PREMARKET-SCAN] 扫描异常: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            try:
                await self._save_premarket_snapshot(trade_date, datetime.now().isoformat(), note=f"扫描异常: {e}")
            except Exception as _e:
                logger.debug(f"[GUARD] scanner: {_e}")
            return 0

    async def _save_premarket_snapshot(self, trade_date: str, scan_time_iso: str, realtime_data: Dict = None,
                                       strategy_candidates: List[ScanSignal] = None,
                                       passed_signals: List[ScanSignal] = None,
                                       note: str = "") -> None:
        """保存竞价阶段每次扫描快照。

        用于前端展示9:00-9:30竞价变化时间线；即使本轮无候选，也保留空快照。
        """
        try:
            from core.managers import mongo_manager
            if mongo_manager.db is None:
                return
            realtime_data = realtime_data or {}
            strategy_candidates = strategy_candidates or []
            passed_signals = passed_signals or []
            pcts = [float(v.get("pct_chg", v.get("auction_pct", 0)) or 0) for v in realtime_data.values() if isinstance(v, dict)]
            # 按板块区分涨跌停阈值统计
            def _count_limits_by_board(rtd):
                lu, ld = 0, 0
                for code, data in rtd.items():
                    if not isinstance(data, dict):
                        continue
                    pct = data.get("pct_chg", data.get("auction_pct", 0))
                    if not isinstance(pct, (int, float)):
                        continue
                    prefix = code.split(".")[0][:3] if "." in code else code[:3]
                    if prefix in ('688', '30'):
                        lu_t, ld_t = 19.5, -19.5
                    elif prefix in ('8', '4') and code[:1] in ('8', '4'):
                        lu_t, ld_t = 29.5, -29.5
                    else:
                        lu_t, ld_t = 9.5, -9.5
                    if pct >= lu_t:
                        lu += 1
                    elif pct <= ld_t:
                        ld += 1
                return lu, ld
            _lu_cnt, _ld_cnt = _count_limits_by_board(realtime_data)
            def _sig(s):
                return {
                    "ts_code": getattr(s, "ts_code", ""),
                    "stock_name": getattr(s, "stock_name", ""),
                    "strategy": getattr(s, "strategy", ""),
                    "price": getattr(s, "price", 0),
                    "pct_chg": getattr(s, "pct_chg", 0),
                    "reason": getattr(s, "reason", ""),
                }
            today_int = int(trade_date) if str(trade_date).isdigit() else trade_date
            snapshot = {
                "trade_date": today_int,
                "scan_time": scan_time_iso,
                "account_id": self.account_id,
                "source": "premarket_scan",
                "note": note,
                "market_snapshot": {
                    "total_stocks": len(realtime_data),
                    "up_count": sum(1 for p in pcts if p > 0),
                    "down_count": sum(1 for p in pcts if p < 0),
                    "flat_count": sum(1 for p in pcts if p == 0),
                    "limit_up_count": _lu_cnt,
                    "limit_down_count": _ld_cnt,
                    "avg_pct_chg": round(sum(pcts) / len(pcts), 2) if pcts else 0,
                },
                "force_empty_confirm": dict(getattr(self, "_premarket_force_empty_state", {}) or {}),
                "funnel": {
                    "total_scanned": len(realtime_data),
                    "strategy_candidates": len(strategy_candidates),
                    "after_pipeline": len(passed_signals),
                },
                "candidates": [_sig(s) for s in passed_signals[:20]],
            }
            await mongo_manager.db["premarket_snapshots"].insert_one(snapshot)
        except Exception as e:
            logger.debug(f"[PREMARKET-SCAN] 保存竞价快照失败: {e}")

    async def _load_stock_list(self) -> None:
        """加载全市场代码 — 委托给RuntimePersistence【v2.9.32提取】"""
        self._all_codes = await self._runtime_persistence.load_stock_list()

    async def _load_daily_factors(self, trade_date: str) -> None:
        """预加载日级因子 — 委托给RuntimePersistence【v2.9.32提取】"""
        self._daily_factors_df = await self._runtime_persistence.load_daily_factors(trade_date)

    async def _load_positions(self) -> None:
        """加载当前持仓 — 委托给RuntimePersistence【v2.9.32提取】"""
        await self._runtime_persistence.load_positions()

    # ==================== Phase1.1: 运行时状态持久化 ====================
    # ==================== 🔄 扫描循环 + 🛡️ 风控循环 ====================
    # _scan_loop/_scan_loop_trading/_scan_loop_error_recovery等
    # _risk_loop_sync/_risk_tick_body/_risk_periodic_checks等
    # 已提取到 scan_loop_runner.py + risk_loop_runner.py 混入类【v2.9.67】


    # ==================== 💰 交易执行+止损止盈 ====================
    def _check_stop_loss_only(self, realtime_data: Dict) -> None:
        """1秒级止损检查 — 委托给PositionManager【v2.9.41简化】
        
        v2.9.41: 移除冗余的broker/positions检查(PM内部已处理), 
        scanner只负责调用PM和执行卖出结果。
        
        v2.9.98: 增加交易时间检查(risk_loop在AFTER_CLOSE仍可能被API触发的scan_once唤醒)
        """
        # 【v2.9.98→v2.9.100】非连续竞价时段不执行止损卖出
        # 旧: is_in_trading() 含午休(11:30-13:00), broker.place_order会因非连续竞价拒单
        # 新: is_continuous_auction() 仅早盘/午盘/尾盘, 与broker门控对齐
        from nodes.market_monitor.market_phase import MarketPhase
        if not MarketPhase.is_continuous_auction():
            return

        # 【v2.9.22:跌停恢复重试pending_sells】
        self._retry_pending_sells(realtime_data)
        
        # 委托检查(PM内部已处理: broker检查+持仓获取+跌停挂起+跌停恢复)
        if self._position_manager:
            to_sell = self._position_manager.check_stop_loss_only(realtime_data)
        else:
            to_sell = []
        
        # 执行卖出(PositionManager只做检查,不执行交易)
        self._execute_sell_list_from_risk(to_sell)



    async def _execute_risk_sell(self, pos, reason: str, price: float, quantity: int) -> None:
        """风控卖出执行 — 委托给PositionManager【v2.9.35提取】"""
        await self._position_manager.execute_risk_sell(pos, reason, price, quantity)


    def _reset_scan_error_state(self) -> None:
        """成功扫描后重置错误计数【v2.9.63提取】"""
        if self._scan_loop_error_count > 0:
            logger.info(f"[SCAN] 恢复成功(之前连续{self._scan_loop_error_count}次异常)")
            self._scan_loop_error_count = 0

    async def scan_once(self, trade_date: str, force: bool = False) -> None:
        """单次扫描
        
        Args:
            trade_date: 交易日期
            force: 强制模式, 忽略交易时间检查(测试用)
        
        【v2.9.63】错误状态重置+完成日志提取子方法
        """
        t0 = time.time()
        self._scan_count += 1
        scan_time = datetime.now().strftime("%H:%M:%S")

        self._reset_scan_error_state()
        logger.info(f"[SCAN #{self._scan_count}] 开始扫描 {scan_time}")

        timer = _StepTimer()

        # Step 1: 获取实时行情
        with timer.step("行情"):
            realtime_data = await self._fetch_realtime_batch(force=force)

        # Step 2: 合并日级因子+实时数据
        with timer.step("因子"):
            self._update_name_map(realtime_data)
            merged_df = self._merge_factors(realtime_data)

        # Step 3: 策略筛选 + 异动检测 + 9层筛选管道
        with timer.step("策略+筛选"):
            new_signals = await self._apply_strategies_and_filters(merged_df, trade_date, realtime_data)

        # Step 4: 增量更新信号
        with timer.step("信号"):
            await self._update_signals(new_signals, scan_time)

        # Step 5: 持仓检查(止损止盈)
        with timer.step("持仓检查"):
            await self._check_positions(realtime_data, trade_date)

        # Step 6: 同步broker实时价格
        self._sync_broker_prices(realtime_data)

        # Step 7: 统计+持久化+完成日志
        elapsed = time.time() - t0
        self._update_scan_stats(scan_time, len(realtime_data), elapsed)
        await self._persist_scan_result()
        logger.info(f"[SCAN #{self._scan_count}] 完成: "
                     f"{len(realtime_data)}只 | {len(self._active_signals)}信号 | "
                     f"{elapsed:.1f}秒{timer.get_slow_info()}")

    async def _apply_strategies_and_filters(
        self, merged_df, trade_date: str, realtime_data: Dict
    ) -> List[ScanSignal]:
        """策略筛选 + 异动检测 + 9层筛选管道【v2.9.33提取】
        
        合并scan_once中Step3的策略+筛选+异动三步,
        减少scan_once的行数, 使扫描流程更清晰。
        """
        # 策略筛选 → 筛选管道
        new_signals = await self._apply_strategies(merged_df, trade_date)
        new_signals = await self._apply_filter_pipeline(new_signals, trade_date, realtime_data)

        # 异动检测(也经过筛选管道，但 trace 标记为 anomaly)【v2.9.105】
        anomaly_signals = await self._detect_anomalies(realtime_data)
        if anomaly_signals:
            anomaly_signals = await self._apply_filter_pipeline(
                anomaly_signals, trade_date, realtime_data, source="anomaly"
            )
        new_signals.extend(anomaly_signals)

        return new_signals

    # ==================== 📋 状态同步+辅助方法 ====================
    def _sync_broker_prices(self, realtime_data: Dict[str, Dict]) -> None:
        """同步broker实时价格(用于持仓估值和涨跌停判断)【v2.9.19提取】"""
        if not self._broker:
            return
        for ts_code, rt in realtime_data.items():
            name = rt.get("name", "")
            is_st = bool(name and ("ST" in name or "*ST" in name))
            self._broker.update_realtime(
                ts_code=ts_code,
                price=rt.get("price", 0),
                pre_close=rt.get("pre_close", 0),
                is_st=is_st,
            )

    def _update_scan_stats(self, scan_time: str, stocks_count: int, elapsed: float) -> None:
        """更新扫描统计+看门狗心跳【v2.9.19提取】"""
        self._last_scan_time = scan_time
        self._stats["scans"] += 1
        self._stats["stocks_scanned"] = stocks_count
        if self._risk_watchdog:
            self._risk_watchdog.update_heartbeat()
        self._last_scan_duration_ms = elapsed * 1000
        self._last_scan_ts = time.time()

    async def _persist_scan_result(self) -> None:
        """扫描结果持久化 — 委托给RuntimePersistence【v2.9.41提取】"""
        await self._runtime_persistence.persist_scan_result()

    # ==================== 实时行情 ====================

    async def _fetch_realtime_batch(self, force: bool = False) -> Dict[str, Dict]:
        """批量获取实时行情 — 委托给QuoteManager【Phase3.1】"""
        # 同步回放模式到QuoteManager
        self._quote_manager.set_replay_mode(
            self._replay_mode, self._replay_provider, self._replay_date
        )
        # 同步缓存锁
        if self._cache_lock and not self._quote_manager.cache_lock_initialized:
            self._quote_manager.set_cache_lock(self._cache_lock)
        
        realtime = await self._quote_manager.fetch_realtime_batch(force=force)
        
        # 同步缓存引用(Scanner其他方法可能直接读self._realtime_cache)
        self._realtime_cache = self._quote_manager.realtime_cache
        self._prev_realtime_cache = self._quote_manager.prev_realtime_cache
        self._last_realtime_update_ts = time.time()  # 【v2.9.23:记录行情更新时间】
        self._data_router = self._quote_manager.data_router
        self._quote_degrade_level = self._quote_manager.quote_degrade_level
        
        return realtime

    # ==================== 因子合并 ====================

    async def _apply_filter_pipeline(
        self, signals: List[ScanSignal], trade_date: str, realtime_data: Dict,
        source: str = "full",
    ) -> List[ScanSignal]:
        """9层筛选管道: 强制空仓/情绪/竞价/排序/仓位

        Args:
            source: 信号源 - 'full' (主扫 5min/轮) / 'anomaly' (异动扫)
                    以便 trace 区分两类记录【v2.9.105】
        """
        # 【v2.9.104】即使 signals 为空也走一遍，以便写入含 total_stocks 的空 trace
        # 注意: 这不会增加策略计算量，只是使 L1-L9 层调用 + 记录 trace
        if signals is None:
            signals = []

        # 记录本次 trace 的信号源, _build_trace_doc 读取
        self._current_trace_source = source

        # 转换为管道输入格式
        candidates = self._signals_to_candidates(signals)

        # 执行管道(v2.9.40:positions/account由pipeline自动从broker获取)
        result = await self._filter_pipeline.apply(
            trade_date=trade_date,
            candidates=candidates,
            realtime_data=realtime_data,
        )

        # 日志+链路追踪 (无论是否有信号都记录, 到一下一轮可见)
        for layer, detail in result.layer_details.items():
            logger.info(f"[FILTER] {layer}: {detail}")
        await self._save_scan_traces(result)

        # 【v2.9.104】即使0信号也要同步情绪和仓位，否则复盘会读旧sentiment_scores
        old_phase = (self._current_sentiment or {}).get("period", "")
        self._current_position_ratio = result.position_ratio
        self._current_sentiment = self._filter_pipeline.get_sentiment_info()
        new_phase = (self._current_sentiment or {}).get("period", "")
        await self._persist_realtime_sentiment(trade_date)

        # 空信号时策略上下文走不下去, 结束返回；但情绪更新/落库已经完成
        if not signals:
            if old_phase and old_phase != new_phase:
                await self._event_bus.emit(ScannerEvents.EMOTION_CHANGED, {
                    "old_phase": old_phase, "new_phase": new_phase,
                })
                await self._handle_emotion_phase_change(old_phase, new_phase)
            return signals

        # 竞价风险状态机: 数据质量+多轮确认+风险分级+开盘执行+新开仓联动
        self._update_premarket_force_empty_state(result, realtime_data)
        if self._should_execute_pending_force_empty():
            await self._execute_pending_premarket_risk_action()
            return []

        # 强制空仓 → 清所有持仓
        if result.action == "empty":
            if not self._can_execute_force_empty_now():
                logger.warning(
                    f"[FILTER] ⚠️ 强制空仓仅记录不执行: {result.force_empty_reason} "
                    f"(竞价/非连续竞价阶段数据不完整, 等待开盘后确认)"
                )
                return []
            await self._execute_force_empty(result.force_empty_reason)
            return []

        # 处理筛选结果(合并+情绪调仓+EventBus事件)
        return await self._process_filter_result(signals, result, trade_date)

    async def _process_filter_result(
        self, signals: List[ScanSignal], result, trade_date: str
    ) -> List[ScanSignal]:
        """处理筛选管道结果: 合并信号+情绪调仓+板块集中度过滤+EventBus事件"""
        # 转回ScanSignal，注入筛选决策详情+逐层trace
        filtered_signals = self._merge_filter_result(signals, result)

        # 【v2.9.92x】板块集中度过滤(与回测sector_concentration对齐)
        # 同行业最多保留N只(默认3只)，避免同行业过度集中
        filtered_signals = await self._apply_sector_concentration(filtered_signals)

        # 更新仓位系数和情绪信息
        old_phase = (self._current_sentiment or {}).get("period", "")
        self._current_position_ratio = result.position_ratio
        self._current_sentiment = self._filter_pipeline.get_sentiment_info()
        new_phase = (self._current_sentiment or {}).get("period", "")

        logger.info(f"[FILTER] 筛选完成: {len(signals)}→{len(filtered_signals)}个信号, "
                     f"仓位系数={result.position_ratio:.0%}")

        # 情绪phase变化→动态调仓
        if old_phase and old_phase != new_phase:
            await self._event_bus.emit(ScannerEvents.EMOTION_CHANGED, {
                "old_phase": old_phase, "new_phase": new_phase,
            })
            await self._handle_emotion_phase_change(old_phase, new_phase)

        # EventBus: 扫描完成事件
        await self._event_bus.emit(ScannerEvents.SCAN_COMPLETED, {
            "trade_date": trade_date, "signals_count": len(filtered_signals),
        })

        return filtered_signals

    async def _apply_sector_concentration(self, signals: List) -> List:
        """【v2.9.92x】板块集中度过滤(与回测sector_concentration对齐)
        
        同行业最多保留N只(默认3只)，避免同行业过度集中同涨同跌
        优先保留评分高的(pct_chg/volume_ratio大的)
        """
        if not signals or len(signals) <= 1:
            return signals
        
        from nodes.market_monitor.position_manager import _get_global_risk as _pgr
        sector_top_n = _pgr().get("sector_concentration_top_n", 3)
        
        try:
            from core.managers import mongo_manager
            if not mongo_manager.is_initialized:
                return signals
            
            # 构建行业映射
            industry_map = {}
            ts_codes = [s.ts_code for s in signals if hasattr(s, 'ts_code')]
            if ts_codes:
                async for doc in mongo_manager.db["stock_basic"].find(
                    {"ts_code": {"$in": ts_codes}},
                    {"_id": 0, "ts_code": 1, "industry": 1}
                ):
                    industry_map[doc.get("ts_code", "")] = doc.get("industry", "未知")
            
            # 加上已持仓的行业(防止持仓+新信号同行业过多)
            existing_positions = self._broker.get_positions() if self._broker else []
            existing_industries = {}
            for pos in existing_positions:
                ind = industry_map.get(pos.ts_code)
                if not ind:
                    async for doc in mongo_manager.db["stock_basic"].find(
                        {"ts_code": pos.ts_code}, {"_id": 0, "ts_code": 1, "industry": 1}
                    ):
                        ind = doc.get("industry", "未知")
                        industry_map[pos.ts_code] = ind
                if ind:
                    existing_industries[ind] = existing_industries.get(ind, 0) + 1
            
            # 按行业分组信号
            industry_signals = {}
            for s in signals:
                ind = industry_map.get(getattr(s, 'ts_code', ''), '未知')
                if ind not in industry_signals:
                    industry_signals[ind] = []
                industry_signals[ind].append(s)
            
            # 每个行业最多保留 sector_top_n - 已持仓数 只
            filtered = []
            removed = 0
            for ind, sigs in industry_signals.items():
                existing_count = existing_industries.get(ind, 0)
                remaining_slots = max(1, sector_top_n - existing_count)
                if len(sigs) <= remaining_slots:
                    filtered.extend(sigs)
                else:
                    # 按涨跌幅排序，保留最强势的
                    sigs.sort(key=lambda s: getattr(s, 'pct_chg', 0) or 0, reverse=True)
                    filtered.extend(sigs[:remaining_slots])
                    removed += len(sigs) - remaining_slots
                    # 【v2.9.95d】为被板块集中度过滤剔除的信号写 timeline
                    for dropped_sig in sigs[remaining_slots:]:
                        try:
                            self._add_timeline_log("blocked", dropped_sig.ts_code,
                                getattr(dropped_sig, 'stock_name', ''),
                                getattr(dropped_sig, 'strategy_name', ''),
                                f"同行业「{ind}」已选{remaining_slots}只信号,本只被集中度过滤剔除",
                                dropped_sig)
                        except Exception as _e:
                            logger.debug(f"[GUARD] scanner: {_e}")
            
            if removed > 0:
                logger.info(f"[FILTER] 板块集中度: 移除{removed}只同行业过多信号(每行业≤{sector_top_n}只)")
            
            return filtered
        except Exception as e:
            logger.debug(f"[FILTER] 板块集中度过滤异常: {e}")
            return signals

    def _signals_to_candidates(self, signals: List[ScanSignal]) -> List[Dict]:
        """将ScanSignal列表转换为filter_pipeline候选格式【v2.9.35:委托给ScanSignal.to_candidate】"""
        return [s.to_candidate() for s in signals]

    def _can_execute_force_empty_now(self) -> bool:
        """强制空仓执行时间门禁: 只有连续竞价阶段才允许真实清仓。"""
        try:
            from nodes.market_monitor.market_phase import MarketPhase
            return MarketPhase.is_continuous_auction()
        except Exception as e:
            logger.warning(f"[FILTER] 强制空仓时间校验异常, 为安全禁止执行: {e}")
            return False

    def _build_premarket_position_risk(self, realtime_data: Dict = None) -> Dict[str, Any]:
        """构建竞价持仓风险预览: 用于风险评分、Level2降仓和TAB证据链。"""
        realtime_data = realtime_data or {}
        positions = self._broker.get_positions() if self._broker else []
        items = []
        pcts = []
        weak_codes = []
        near_limit_down = 0
        red_count = 0
        for p in positions:
            q = realtime_data.get(p.ts_code, {}) if isinstance(realtime_data, dict) else {}
            pct = q.get("pct_chg", q.get("auction_pct", p.profit_pct)) if isinstance(q, dict) else p.profit_pct
            try:
                pct = float(pct or 0)
            except Exception as _e:
                pct = 0.0
            pcts.append(pct)
            if pct >= 0:
                red_count += 1
            if pct <= -8.5:
                near_limit_down += 1
            if pct <= -3 or (p.profit_pct or 0) <= -5:
                weak_codes.append(p.ts_code)
            items.append({
                "ts_code": p.ts_code, "stock_name": p.stock_name, "strategy": p.strategy,
                "available_qty": p.available_qty, "profit_pct": round(float(p.profit_pct or 0), 2),
                "auction_pct_chg": round(pct, 2), "weak": pct <= -3 or (p.profit_pct or 0) <= -5,
                "near_limit_down": pct <= -8.5,
            })
        avg_pct = round(sum(pcts) / len(pcts), 2) if pcts else 0
        return {
            "count": len(items), "red_count": red_count, "weak_count": len(weak_codes),
            "near_limit_down_count": near_limit_down, "avg_pct_chg": avg_pct,
            "weak_codes": weak_codes, "items": items[:20],
        }

    def _score_premarket_risk(self, metrics: Dict[str, Any], result, position_risk: Dict[str, Any], valid: bool = True) -> Tuple[int, str, List[str], str]:
        """竞价风险评分: 市场宽度+短线情绪+持仓风险+原L1强制空仓信号。
        
        【v2.9.99-r13】valid=False (竞价数据未到, total<3000) 时跳过市场宽度/涨跌停评分,
        避免 "limit_up仅 0 只" 这种数据缺失被误读成情绪冷。仅保留持仓风险+L1强制空仓评分。
        """
        score = 0
        reasons = []
        if valid:
            total = max(int(metrics.get("total_stocks") or 0), 1)
            down_ratio = metrics.get("down_count", 0) / total
            avg_pct = float(metrics.get("avg_pct_chg") or 0)
            limit_up = int(metrics.get("limit_up_count") or 0)
            limit_down = int(metrics.get("limit_down_count") or 0)
            if down_ratio >= 0.70:
                score += 20; reasons.append(f"下跌占比{down_ratio:.0%}")
            if avg_pct <= -1.0:
                score += 15; reasons.append(f"竞价均幅{avg_pct:.2f}%")
            if limit_up <= 10:
                score += 10; reasons.append(f"涨停仅{limit_up}只")
            if limit_down >= 10:
                score += 20; reasons.append(f"跌停{limit_down}只")
            if limit_down >= 30:
                score += 20; reasons.append("跌停扩散")
            sentiment = self._filter_pipeline.get_sentiment_info() if self._filter_pipeline else {}
            sentiment_score = float(sentiment.get("score", sentiment.get("emotion_score", 50)) or 50)
            if sentiment_score < 35:
                score += 20; reasons.append(f"情绪{sentiment_score:.0f}分")
        else:
            reasons.append("竞价数据未就绪(跳过市场宽度评分)")
        if getattr(result, "action", "") == "empty":
            score += 25; reasons.append(getattr(result, "force_empty_reason", "L1强制空仓信号") or "L1强制空仓信号")
        if position_risk.get("avg_pct_chg", 0) <= -4:
            score += 20; reasons.append(f"持仓均跌{position_risk.get('avg_pct_chg')}%")
        if position_risk.get("near_limit_down_count", 0) > 0:
            score += 15; reasons.append(f"持仓近跌停{position_risk.get('near_limit_down_count')}只")
        if position_risk.get("weak_count", 0) >= max(1, position_risk.get("count", 0) // 2):
            score += 10; reasons.append(f"弱势持仓{position_risk.get('weak_count')}只")
        if score >= 80:
            return score, "L3", reasons, "force_empty"
        if score >= 55:
            return score, "L2", reasons, "reduce_position"
        if score >= 35:
            return score, "L1", reasons, "warn"
        return score, "L0", reasons, "none"

    def _collect_premarket_metrics(self, realtime_data: Dict) -> Tuple[Dict, List[str]]:
        """收集竞价期间市场指标并检测异常【v2.9.75提取】"""
        pcts = []
        limit_up = 0
        limit_down = 0
        for code, v in realtime_data.items():
            if not isinstance(v, dict):
                continue
            try:
                pct = float(v.get("pct_chg", v.get("auction_pct", 0)) or 0)
                pcts.append(pct)
            except Exception as _e:
                logger.debug(f"[GUARD] scanner: {_e}")
                continue
            # 按板块区分涨跌停阈值
            prefix = code.split(".")[0][:3] if "." in code else code[:3]
            if prefix in ('688', '30'):
                lu_t, ld_t = 19.5, -19.5
            elif prefix in ('8', '4') and code[:1] in ('8', '4'):
                lu_t, ld_t = 29.5, -29.5
            else:
                lu_t, ld_t = 9.5, -9.5
            if pct >= lu_t:
                limit_up += 1
            elif pct <= ld_t:
                limit_down += 1
        total = len(pcts)
        up_count = sum(1 for p in pcts if p > 0)
        down_count = sum(1 for p in pcts if p < 0)
        avg_pct = round(sum(pcts) / total, 2) if total else 0
        metrics = {
            "total_stocks": total, "up_count": up_count, "down_count": down_count,
            "limit_up_count": limit_up, "limit_down_count": limit_down, "avg_pct_chg": avg_pct,
        }
        anomalies = []
        if total < 3000:
            anomalies.append(f"样本数不足({total})")
        state = self._premarket_force_empty_state
        last_total = state.get("last_total_stocks")
        last_up = state.get("last_limit_up")
        last_down = state.get("last_limit_down")
        if last_total and total and abs(total - last_total) / max(last_total, 1) > 0.25:
            anomalies.append(f"样本数跳变({last_total}→{total})")
        if last_up is not None and abs(limit_up - last_up) >= 30:
            anomalies.append(f"涨停数跳变({last_up}→{limit_up})")
        if last_down is not None and abs(limit_down - last_down) >= 20:
            anomalies.append(f"跌停数跳变({last_down}→{limit_down})")
        state.update({"last_total_stocks": total, "last_limit_up": limit_up, "last_limit_down": limit_down})
        return metrics, anomalies

    def _update_premarket_history_and_state(
        self, state: Dict, ct: str, metrics: Dict, valid: bool,
        anomalies: List, score, level, reasons, action, position_risk
    ) -> None:
        """更新竞价风控历史记录和状态摘要【v2.9.75提取】"""
        item = {
            "time": ct, **metrics, "valid": valid, "anomalies": anomalies,
            "risk_score": score, "risk_level": level, "action": action,
            "triggered": action in ("force_empty", "reduce_position"), "reasons": reasons[:6],
            "position_risk": position_risk,
        }
        state.setdefault("history", []).append(item)
        state["history"] = state.get("history", [])[-30:]
        state.update({
            "risk_score": score, "risk_level": level, "action": action,
            "reasons": reasons[:8], "reason": "；".join(reasons[:4]),
            "market_snapshot": metrics, "position_risk": position_risk,
            "data_quality": "ok" if valid else "bad",
        })

    def _check_premarket_multi_round_confirm(self, state: Dict, ct: str, valid: bool, level: str) -> None:
        """竞价风控多轮确认: 09:20-09:25累计确认+09:25-09:30最终确认【v2.9.75提取】"""
        if "09:20:00" <= ct < "09:30:00" and valid and level in ("L2", "L3"):
            state["confirm_count"] = int(state.get("confirm_count", 0)) + 1
            if "09:25:00" <= ct < "09:30:00":
                state["final_confirm_count"] = int(state.get("final_confirm_count", 0)) + 1
            if state.get("confirm_count", 0) >= 2 and state.get("final_confirm_count", 0) >= 1:
                state["pending"] = True
                state["pending_action"] = "force_empty" if level == "L3" else "reduce_position"
                cap = 0.0 if level == "L3" else 0.3
                self._cooldown_info = {
                    "trigger_date": datetime.now().strftime("%Y%m%d"),
                    "cooldown_days": 1 if level == "L2" else 2,
                    "position_cap": cap,
                    "reason": f"竞价风险{level}: {state.get('reason')}",
                    "risk_level": level,
                    "block_new_buys": True,
                }

    def _update_premarket_force_empty_state(self, result, realtime_data: Dict = None) -> None:
        """竞价风控状态机: 数据质量层+多轮确认层+风险分级层+执行层。

        09:15-09:20观察；09:20-09:25累计确认；09:25-09:30最终确认；
        09:30后如Level2/Level3 pending则执行降仓/清仓，并联动新开仓控制。
        """
        try:
            ct = datetime.now().strftime("%H:%M:%S")
            if not ("09:15:00" <= ct < "09:30:00"):
                return
            state = self._premarket_force_empty_state
            realtime_data = realtime_data or {}
            metrics, anomalies = self._collect_premarket_metrics(realtime_data)
            total = metrics["total_stocks"]
            state["scan_count"] = int(state.get("scan_count", 0)) + 1
            valid = total >= 3000 and not anomalies
            if valid:
                state["valid_scan_count"] = int(state.get("valid_scan_count", 0)) + 1
            else:
                state["data_quality"] = "bad"
            if anomalies:
                state.setdefault("anomalies", []).extend(anomalies)
                state["anomalies"] = state.get("anomalies", [])[-20:]

            position_risk = self._build_premarket_position_risk(realtime_data)
            score, level, reasons, action = self._score_premarket_risk(metrics, result, position_risk, valid=valid)
            self._update_premarket_history_and_state(
                state, ct, metrics, valid, anomalies, score, level, reasons, action, position_risk)
            self._check_premarket_multi_round_confirm(state, ct, valid, level)
            if state.get("pending"):
                logger.warning(
                    f"[FILTER] 竞价风险待执行: level={state.get('risk_level')} score={state.get('risk_score')} "
                    f"action={state.get('pending_action')} 确认{state.get('confirm_count')}次/最终{state.get('final_confirm_count')}次"
                )
        except Exception as e:
            logger.debug(f"[FILTER] 更新竞价风险状态失败: {e}")

    def _should_execute_pending_force_empty(self) -> bool:
        """09:30后如竞价阶段已充分确认Level2/Level3风险, 立即执行pending动作。"""
        try:
            if not self._premarket_force_empty_state.get("pending"):
                return False
            from nodes.market_monitor.market_phase import MarketPhase
            return MarketPhase.is_continuous_auction()
        except Exception as _e:
            return False

    async def _execute_pending_premarket_risk_action(self) -> None:
        """执行竞价pending动作: Level3全清；Level2卖弱势持仓并禁开仓。"""
        state = self._premarket_force_empty_state
        action = state.get("pending_action") or state.get("action")
        reason = state.get("reason") or "竞价风险确认"
        if action == "force_empty":
            await self._execute_force_empty(f"竞价L3强制空仓: {reason}")
        elif action == "reduce_position":
            weak_codes = set((state.get("position_risk") or {}).get("weak_codes") or [])
            if weak_codes:
                await self._liquidate_positions_by_codes(weak_codes, reason=f"竞价L2降仓: {reason}", source="auction_reduce")
            self._cooldown_info = {
                "trigger_date": datetime.now().strftime("%Y%m%d"),
                "cooldown_days": 1,
                "position_cap": 0.3,
                "reason": f"竞价L2防守: {reason}",
                "risk_level": "L2",
                "block_new_buys": True,
            }
        state["executed"] = True
        state["executed_at"] = datetime.now().isoformat()
        state["pending"] = False

    async def _liquidate_positions_by_codes(self, codes, reason: str, source: str) -> Tuple[int, int]:
        """按代码卖出弱势持仓, 用于竞价Level2降仓。
        
        v2.9.106: 增加is_continuous_auction()检查, 与其他卖出路径对齐
        """
        from nodes.market_monitor.market_phase import MarketPhase
        if not MarketPhase.is_continuous_auction():
            logger.warning(f"[{source.upper()}] 非连续竞价时段跳过按代码卖出: {reason}")
            return 0, 0
        if not self._broker:
            return 0, 0
        sold = failed = 0
        for p in self._broker.get_positions():
            if p.ts_code not in codes or p.available_qty <= 0:
                continue
            try:
                self._broker.update_realtime(p.ts_code, p.current_price)
                ok, msg, order = self._broker.place_order(
                    ts_code=p.ts_code, stock_name=p.stock_name, side="sell",
                    quantity=p.available_qty, price=p.current_price, order_type="market",
                    strategy=p.strategy, reason=reason,
                )
                if ok:
                    sold += 1
                    await self._post_sell_cleanup(p, reason, order, p.available_qty, order.profit_pct, order.profit_amount, source=source)
                else:
                    failed += 1
                    logger.warning(f"[{source.upper()}] {p.ts_code} 卖出失败: {msg}")
            except Exception as e:
                failed += 1
                logger.error(f"[{source.upper()}] {p.ts_code} 异常: {e}")
        logger.warning(f"[{source.upper()}] Level2降仓完成: 卖出{sold}只, 失败{failed}只")
        return sold, failed

    async def _execute_force_empty(self, reason: str) -> None:
        """强制空仓: 卖出所有持仓+启动冷却期【v2.9.92w:与回测对齐】"""
        logger.warning(f"[FILTER] ⚠️ 强制空仓: {reason}")
        await self._liquidate_positions(reason=f"强制空仓: {reason}", source="force_empty")
        
        # 【v2.9.92w】冷却期: 强制空仓后N天内仓位上限60%(与回测GLOBAL_RISK对齐)
        from nodes.market_monitor.position_manager import _get_global_risk as _pgr
        _gr = _pgr()
        cooldown_days = _gr.get("force_empty_cooldown_days", 2)
        cooldown_cap = _gr.get("force_empty_cooldown_position_cap", 0.6)
        self._force_empty_cooldown_until = datetime.now().strftime("%Y%m%d")  # 当天
        # 简单实现: 标记冷却期开始日期，在仓位系数计算时检查
        self._cooldown_info = {
            "trigger_date": datetime.now().strftime("%Y%m%d"),
            "cooldown_days": cooldown_days,
            "position_cap": cooldown_cap,
            "reason": reason,
        }
        logger.warning(f"[FILTER] 🧊 冷却期启动: {cooldown_days}个交易日内仓位上限{cooldown_cap*100:.0f}%")


    # ==================== 信号管理+止损止盈 ====================

        # _check_stop_loss_take_profit: 先更新追踪止损再委托检查
        # 已在DELEGATE_MAP中声明, 但scanner仍保留显式定义以在检查前调用_update_trailing_stops
        # _update_trailing_stops已在DELEGATE_MAP中声明

    def _check_stop_loss_take_profit(self, positions, realtime_data: Dict) -> List[Tuple]:
        """止损止盈检查 — 先更新追踪止损再委托PositionManager"""
        self._update_trailing_stops(positions, realtime_data)
        return self._position_manager.check_stop_loss_take_profit(positions, realtime_data) if self._position_manager else []

    # ==================== 持仓检查 + 情绪调仓 ====================
    
    def _build_emotion_sell_list(self, positions, rule: Dict, old_phase: str, new_phase: str) -> List[Tuple]:
        """根据情绪降级规则构建卖出列表 — 委托给EmotionCycleManager【v2.9.16】"""
        from nodes.market_monitor.emotion_cycle import EmotionCycleManager
        # 【v2.9.18:传深拷贝,防止回调函数意外修改scanner内部状态】
        pending_copy = self._safe_copy_pending_sells() if self._state_lock else dict(self._pending_sells)
        return EmotionCycleManager.build_emotion_sell_list(
            positions=positions,
            rule=rule,
            old_phase=old_phase,
            new_phase=new_phase,
            is_limit_down_fn=self._is_limit_down,
            pending_sells=pending_copy,
            state_lock=None,  # 已深拷贝,不需要外部锁
            strategy_risk_fn=self._get_strategy_risk,
        )
    
    # 【v2.9.24: _handle_emotion_phase_change提取到EmotionCycleManager.handle_emotion_phase_change】
    # 通过DELEGATE_MAP+__getattr__动态委托

    # ==================== 健康度+线程安全 ====================

    # ==================== 🔒 线程安全+健康度 ====================
    # 状态访问器(替代getattr/hasattr穿透)已提取到 ScannerAccessorsMixin【v2.9.99】

    # ==================== 智能持仓检查频率 ====================

    def _make_quote_event_emitter(self) -> Callable:
        """创建行情事件发射回调(v2.9:消除QuoteManager对Scanner的循环引用)
        
        之前QuoteManager直接持有scanner引用来发射EventBus事件,
        造成QuoteManager→Scanner循环依赖。改用回调函数解耦:
        - QuoteManager只依赖回调接口,不知道Scanner存在
        - Scanner提供回调,内部调用EventBus.emit
        """
        scanner = self
        async def emit_quote_event(event_name: str, data: dict) -> None:
            try:
                await scanner._event_bus.emit(event_name, data)
            except Exception as _e:
                logger.debug(f"[QUOTE] 行情事件发射失败({event_name}): {_e}")
        return emit_quote_event

    def _is_limit_down(self, ts_code: str) -> bool:
        """判断是否跌停 — 委托给PositionChecker【v2.9.6移除fallback, v2.9.18公开接口】"""
        if self._position_checker:
            return self._position_checker.is_limit_down(ts_code)
        return False  # 无PositionChecker时默认非跌停(保守策略)

    # DELEGATE_MAP条目即委托文档

