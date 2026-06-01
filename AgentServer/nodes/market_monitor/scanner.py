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
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field

import pandas as pd

from nodes.market_monitor.broker import SimulatedBroker
from nodes.market_monitor.live_filter_pipeline import LiveFilterPipeline
from nodes.market_monitor.quote_manager import QuoteManager
from nodes.market_monitor.scanner_event_bus import ScannerEventBus, ScannerEvents

logger = logging.getLogger("scanner.market")


class MarketPhase:
    """市场时间阶段分类【v2.9.21】
    
    统一_scan_loop和_risk_loop_sync的时间门控逻辑,
    消除散布在两个方法中的魔术字符串比较。
    """
    WEEKEND = "weekend"          # 周末(调试模式)
    DEEP_NIGHT = "deep_night"    # 23:00-08:00 极低频
    PREMARKET = "premarket"      # 09:00-09:25 竞价前
    AUCTION = "auction"          # 09:25-09:30 竞价
    TRADING = "trading"          # 09:30-15:00 交易时间
    AFTER_CLOSE = "after_close"  # 15:05+ 收盘结算
    OFF_HOURS = "off_hours"      # 其他非交易时间

    @staticmethod
    def classify() -> str:
        """分类当前时间阶段(零副作用, 可随时调用)"""
        now = datetime.now()
        ct = now.strftime("%H:%M")
        if now.weekday() >= 5:
            return MarketPhase.WEEKEND
        if now.hour >= 23 or now.hour < 8:
            return MarketPhase.DEEP_NIGHT
        if "09:00" <= ct < "09:25":
            return MarketPhase.PREMARKET
        if "09:25" <= ct < "09:30":
            return MarketPhase.AUCTION
        if "09:30" <= ct <= "15:00":
            return MarketPhase.TRADING
        if ct >= "15:05":
            return MarketPhase.AFTER_CLOSE
        return MarketPhase.OFF_HOURS

    @staticmethod
    def is_trading_active(phase: str = None) -> bool:
        """当前是否处于交易活跃时段(竞价+交易)【v2.9.39】

        用于风控线程等需要快速判断是否应执行检查的场景。
        Args:
            phase: 传入阶段(省略则自动classify)
        """
        p = phase or MarketPhase.classify()
        return p in (MarketPhase.TRADING, MarketPhase.AUCTION)


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


class MarketScanner:
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

    # 情绪降级规则: phase降级时的动态调仓策略
    # EMOTION_DOWNGRADE_RULES已迁移至EmotionCycleManager.DOWNGRADE_RULES【v3.0】
    # 保持类属性兼容旧代码引用
    EMOTION_DOWNGRADE_RULES = None  # type: ignore

    # 交易模式
    MODE_SIMULATED = "simulated"  # 内置仿真撮合
    MODE_GM = "gm"                # 掘金量化
    MODE_DRY_RUN = "dry_run"      # 调试模式: 只扫描不交易
    MODE_REPLAY = "replay"        # 回放模式: 用历史数据模拟实时行情

    # ==================== 类属性默认值(不可变/标量)【v2.9.37】 ====================
    _risk_thread = None
    _risk_running: bool = False
    _risk_thread_restarts: int = 0
    _cache_lock = None
    _state_lock = None
    _loop = None
    _last_snapshot_save: float = 0.0
    _snapshot_dirty: bool = False
    _trade_date: str = ""
    _nav_peak: float = 1.0
    _quote_degrade_level: int = 0
    _quote_fail_count: int = 0
    _quote_last_recover_check: float = 0.0
    _is_running: bool = False
    _task = None
    _scan_count: int = 0
    _last_scan_time: str = ""
    _last_scan_ts: float = 0.0
    _last_risk_check_ts: float = 0.0
    _last_realtime_update_ts: float = 0.0
    _scan_loop_error_count: int = 0

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

    def _init_state(self):
        """初始化基础状态变量【v2.9.3提取, v2.9.37:标量默认值提升为类属性】"""
        # ── 风控状态(风控线程+主循环并发读写, _state_lock保护) ──
        self._position_risk_overrides: Dict[str, Dict] = {}
        self._trailing_stops: Dict[str, Dict] = {}
        self._position_risk_levels: Dict[str, str] = {}
        self._pending_orders: Dict[str, Dict] = {}
        self._pending_sells: Dict[str, Dict] = {}

        # ── 执行质量统计 ──
        self._execution_stats = {
            "total_slippage_pct": 0.0,
            "total_fills": 0,
            "partial_fills": 0,
            "avg_fill_latency_ms": 0.0,
            "stop_loss_response_times": [],
        }

        # ── 卖出逻辑灰度开关 ──
        self.SELL_LOGIC_MODE = os.getenv("SELL_LOGIC_MODE", "legacy")

        # ── 数据缓存(主循环写, 风控线程读, _cache_lock保护) ──
        self._daily_factors_df: Optional[pd.DataFrame] = None
        self._realtime_cache: Dict[str, Dict] = {}
        self._prev_realtime_cache: Dict[str, Dict] = {}
        self._all_codes: List[str] = []

        # ── 信号与时间线 ──
        self._active_signals: List[ScanSignal] = []
        self._timeline: List[Dict] = []

        # ── 交易统计 ──
        self._stats = {
            "scans": 0,
            "signals_found": 0,
            "trades_executed": 0,
            "stop_losses": 0,
            "take_profits": 0,
            "stocks_scanned": 0,
        }
        self._last_scan_duration_ms: float = 0.0
        self._daily_start_asset: float = 0.0

    def _init_broker(self):
        """初始化撮合引擎【v2.9.3提取】"""
        trade_mode = self.config.get("trade_mode", self.MODE_SIMULATED)
        self._trade_mode = trade_mode
        initial_cash = self.config.get("initial_cash", 1_000_000)

        self._dry_run = (trade_mode == self.MODE_DRY_RUN)
        self._replay_mode = (trade_mode == self.MODE_REPLAY)
        self._replay_date = self.config.get("replay_date", None)
        self._replay_provider = None
        self._stock_name_map: Dict[str, str] = {}  # ts_code→stock_name缓存

        if trade_mode == self.MODE_GM:
            from nodes.market_monitor.gm_broker import GmBroker
            self._gm_broker = GmBroker(
                token=self.config.get("gm_token", ""),
                strategy_id=self.config.get("gm_strategy_id", ""),
                mode=1,
                serv_addr=self.config.get("gm_serv_addr", ""),
                account_id=self.account_id,
            )
            self._broker = None
            logger.info("[SCANNER] 交易模式: 掘金量化")
        elif self._dry_run:
            self._broker = SimulatedBroker(account_id=self.account_id, initial_cash=initial_cash)
            self._gm_broker = None
            logger.info("[SCANNER] 交易模式: 🔍调试模式(只扫描不交易)")
        elif self._replay_mode:
            self._broker = SimulatedBroker(account_id=self.account_id, initial_cash=initial_cash)
            self._gm_broker = None
            try:
                from nodes.market_monitor.replay_provider import ReplayDataProvider
                self._replay_provider = ReplayDataProvider()
                if self._replay_date:
                    self._replay_provider.get_replay_data(self._replay_date)
            except (ImportError, OSError, ValueError) as e:
                logger.error(f"[SCANNER] 回放数据加载失败: {e}")
            logger.info(f"[SCANNER] 交易模式: 🔄回放模式(日期={self._replay_date or '自动'})")
        else:
            self._broker = SimulatedBroker(account_id=self.account_id, initial_cash=initial_cash)
            self._gm_broker = None
            logger.info("[SCANNER] 交易模式: 内置仿真撮合")

    def _init_pipeline(self):
        """初始化9层筛选管道【v2.9.3提取】"""
        self._filter_pipeline = LiveFilterPipeline(
            scanner=self,
            config={
                "enable_force_empty": True,
                "enable_special_period": True,
                "enable_sentiment_cycle": True,
                "enable_premarket_filter": True,
                "enable_auction_filter": True,
                "max_total_position": 0.7,
                "max_position_per_stock": 0.35,
                "max_candidates_per_scan": 10,
            }
        )
        self._current_position_ratio = 1.0
        self._current_sentiment = {"score": 50, "period": "chaos"}

    def _init_modules(self):
        """初始化EventBus+QuoteManager+核心模块+风控+执行质量【v2.9.3提取, v2.9.25拆分为子方法】"""
        self._init_event_and_quote()
        self._init_signal_and_risk()
        self._init_core_modules()
        self._init_execution_quality()

    def _init_event_and_quote(self):
        """初始化EventBus+QuoteManager【v2.9.25提取】"""
        self._event_bus = ScannerEventBus()
        self._quote_manager = QuoteManager()
        self._quote_manager.set_event_emitter(self._make_quote_event_emitter())
        self._position_manager = None  # 延迟初始化
        self._strategy_scorer = None
        self._signal_manager = None
        self._data_router: Optional[Any] = None

    def _init_signal_and_risk(self):
        """初始化信号分发器+参数中心+风控看门狗【v2.9.25提取】"""
        from nodes.market_monitor.signal_dispatcher import (
            SignalDispatcher, redis_channel_handler, feishu_channel_handler, log_channel_handler
        )
        self._signal_dispatcher = SignalDispatcher(scanner=self)
        self._signal_dispatcher.register_channel("log", log_channel_handler)
        self._signal_dispatcher.register_channel("redis", redis_channel_handler)
        self._feishu_registered = False

        from nodes.market_monitor.strategy_param_center import param_center
        self._param_center = param_center

        from nodes.market_monitor.risk_watchdog import RiskWatchdog
        self._risk_watchdog = RiskWatchdog(scanner=self)
        self._risk_watchdog.register_alert_channel(self._signal_dispatcher.dispatch)

    def _init_core_modules(self):
        """初始化PositionManager+StrategyScorer+SignalManager+PositionChecker+RuntimePersistence【v2.9.25提取】"""
        from nodes.market_monitor.position_manager import PositionManager
        self._position_manager = PositionManager(self)
        from nodes.market_monitor.strategy_scorer import StrategyScorer
        self._strategy_scorer = StrategyScorer(self)
        from nodes.market_monitor.signal_manager import SignalManager
        self._signal_manager = SignalManager(self)
        from nodes.market_monitor.position_checker import PositionChecker
        self._position_checker = PositionChecker(self)
        from nodes.market_monitor.runtime_persistence import RuntimePersistence
        self._runtime_persistence = RuntimePersistence(self)

        # 分级行情扫描器
        self._use_tiered = self.config.get("use_tiered_scanner", False)
        self._tiered_scanner = None
        if self._use_tiered:
            from nodes.market_monitor.tiered_scanner import TieredScanner
            self._tiered_scanner = TieredScanner(scanner=self)
            logger.info("[SCANNER] 分级行情: L1(5min全市场) → L2(30s候选池) → L3(5s持仓)")

    def _init_execution_quality(self):
        """初始化执行质量检查+滑点模型【v2.9.25提取】"""
        from nodes.market_monitor.execution_quality import PreTradeChecker, SlippageModel
        self._pre_trade_checker = PreTradeChecker(broker=self._broker, config={
            "max_position_per_stock": 0.35,
            "max_total_position": 0.70,
        })
        self._slippage_model = SlippageModel

    def _init_risk(self):
        """初始化风控熔断参数【v2.9.3提取】"""
        initial_cash = self.config.get("initial_cash", 1_000_000)
        self._circuit_breaker = {
            "daily_start_assets": initial_cash,
            "daily_max_drawdown": 0.05,
            "consecutive_losses": 0,
            "consecutive_loss_limit": 3,
            "trading_paused": False,
            "pause_reason": "",
            "today_trades": 0,
            "today_losses": 0,
        }

    # ==================== 动态委托分派 ====================

    # 委托映射已移至scanner_delegate_router.DELEGATE_MAP【v2.9.52】
    # 保留_DELEGATE_MAP类属性作为兼容别名(测试代码引用MarketScanner._DELEGATE_MAP)
    @classmethod
    @property
    def _DELEGATE_MAP(cls):
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

    def is_running(self):
        return self._is_running

    def get_status(self) -> Dict[str, Any]:
        """Scanner完整状态快照"""
        # 子模块状态(安全读取, 无boker时返回空dict)
        module_status = self._build_module_status()
        return {
            "is_running": self._is_running,
            "scan_count": self._scan_count,
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
                "sentiment": self._current_sentiment,
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
        return list(self._timeline)
    async def start(self, trade_date: str = None):
        """启动扫描"""
        if self._is_running:
            return {"success": True, "message": "已在运行中"}

        # 【Phase1.2:提前初始化线程锁(被premarket_prepare/_load_positions使用)】
        if self._state_lock is None:
            self._state_lock = threading.Lock()

        if not trade_date:
            trade_date = datetime.now().strftime("%Y%m%d")
        self._trade_date = trade_date

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

        self._is_running = True
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

    # DELEGATE_MAP条目即委托文档, 不再逐一注释
    # 【v2.9.42: _save_param_snapshot/_detect_param_drift/_validate_live_params/update_strategy_config
    #   /_persist_strategy_overrides/_load_strategy_overrides 均已加入DELEGATE_MAP动态委托】

    async def _restore_start_state(self):
        """启动时恢复状态 — 委托给RuntimePersistence【v2.9.32提取】"""
        await self._runtime_persistence.restore_start_state()

    def _start_risk_thread(self):
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

    async def stop(self, sell_all: bool = False):
        """停止扫描
        
        Args:
            sell_all: 是否清仓所有持仓(默认只停止扫描,保留持仓)
        """
        self._is_running = False
        
        # 【Phase1.2:停止风控独立线程】
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
        # 【V54:停止分级行情扫描器】
        if self._tiered_scanner:
            await self._tiered_scanner.stop()
        
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
        logger.info(f"[SCANNER] 已停止 (清仓={sell_all})")
        return {"success": True, "message": f"扫描器已停止" + ("并清仓" if sell_all else "")}

    async def _liquidate_positions(self, reason: str, source: str) -> Tuple[int, int]:
        """批量清仓 — 委托给PositionManager【v2.9.35提取】"""
        return await self._position_manager.liquidate_positions(reason, source)

    async def _sell_all_positions(self):
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

    async def _persist_stop_state(self):
        """停止时持久化状态 — 委托给RuntimePersistence【v2.9.32提取】"""
        await self._runtime_persistence.persist_stop_state()

    # ==================== 盘前准备 ====================


    def _update_name_map(self, realtime_data: Dict[str, Dict]):
        """从实时行情数据更新ts_code→stock_name映射"""
        updated = False
        for ts_code, rt in realtime_data.items():
            name = rt.get("name", "")
            if name and ts_code not in self._stock_name_map:
                self._stock_name_map[ts_code] = name
                updated = True
        if updated and self._strategy_scorer:
            self._strategy_scorer.update_name_map(self._stock_name_map)

    def _get_stock_name(self, ts_code: str) -> str:
        """获取股票名称(带缓存)"""
        if ts_code in self._stock_name_map:
            return self._stock_name_map[ts_code]
        return ""

    async def _load_stock_name_map(self):
        """加载名称映射 — 委托给RuntimePersistence【v2.9.32提取】"""
        names = await self._runtime_persistence.load_stock_name_map()
        self._stock_name_map.update(names)
    async def _warm_weekend_cache(self):
        """周末调试: 用日级因子填充行情缓存 — 委托给RuntimePersistence【v2.9.32提取】"""
        realtime = self._runtime_persistence.warm_weekend_cache(
            self._daily_factors_df, self._stock_name_map, self._quote_manager
        )
        self._realtime_cache = realtime
        self._last_realtime_update_ts = time.time()

    def _reset_daily_risk_state(self):
        """重置每日风控状态 — 委托给RiskWatchdog【v2.9.32提取】"""
        from nodes.market_monitor.risk_watchdog import RiskWatchdog
        RiskWatchdog.reset_daily_risk_state(self)

    async def premarket_prepare(self, trade_date: str):
        """盘前: 加载全市场代码 + 预加载日级因子"""
        logger.info(f"[SCANNER] 盘前准备 {trade_date}")

        # 【v2.9.21:提取_reset_daily_risk_state, 简化本方法】
        # 重置每日风控(circuit_breaker+pending_sells+执行统计)
        # 追踪止损/风险等级: _load_positions→_load_runtime_snapshot根据快照日期判断
        self._reset_daily_risk_state()

        # 1. 获取全市场代码
        await self._load_stock_list()

        # 2. 预加载前日因子(ma5/rsi/macd/boll/atr等需要历史数据的因子)
        await self._load_daily_factors(trade_date)
        # 加载股票名称映射(从stock_basic)
        await self._load_stock_name_map()
        if self._strategy_scorer:
            self._strategy_scorer.update_name_map(self._stock_name_map)

        # 3. 加载当前持仓
        logger.info("[SCANNER] 开始加载持仓...")
        await self._load_positions()
        logger.info("[SCANNER] 持仓加载完成")

        # 4. 竞价预选(仅竞价阶段9:15-9:30)
        now = datetime.now()
        ct = now.strftime("%H:%M")
        if "09:15" <= ct <= "09:30":
            await self._premarket_auction(trade_date)
        else:
            logger.debug(f"[SCANNER] 非竞价时间({ct}), 跳过竞价预选")

        logger.info("[SCANNER] premarket_prepare 即将完成")
        
        # 【周末调试】用日级因子填充行情缓存, 使周末也能操作
        if datetime.now().weekday() >= 5 and self._daily_factors_df is not None:
            await self._warm_weekend_cache()
        
        logger.info(f"[SCANNER] 准备完成: {len(self._all_codes)}只股票, "
                     f"{len(self._daily_factors_df) if self._daily_factors_df is not None else 0}条因子, "
                     f"{len(self._active_signals)}个竞价信号")

    async def _load_stock_list(self):
        """加载全市场代码 — 委托给RuntimePersistence【v2.9.32提取】"""
        self._all_codes = await self._runtime_persistence.load_stock_list()

    async def _load_daily_factors(self, trade_date: str):
        """预加载日级因子 — 委托给RuntimePersistence【v2.9.32提取】"""
        self._daily_factors_df = await self._runtime_persistence.load_daily_factors(trade_date)

    async def _load_positions(self):
        """加载当前持仓 — 委托给RuntimePersistence【v2.9.32提取】"""
        await self._runtime_persistence.load_positions()

    # ==================== Phase1.1: 运行时状态持久化 ====================
    async def _scan_loop(self, trade_date: str):
        """主扫描循环(双层节奏 + 智能刷新)
        
        全量扫描(5分钟): 涨停池+策略筛选 → 发现新信号
        持仓检查(30秒): 只查持仓股行情 → 止损止盈
        
        【v2.9.28】提取_scan_loop_phase_sleep, 错误恢复简化
        """
        settled = False
        last_full_scan = 0

        if self._replay_mode:
            await self._scan_loop_replay()
            return

        try:
            while self._is_running:
                phase = MarketPhase.classify()
                
                if phase == MarketPhase.WEEKEND:
                    pos_count = len(self.get_positions())
                    if pos_count > 0:
                        try:
                            await self._check_positions_quick(trade_date)
                        except (RuntimeError, KeyError, ValueError) as e:
                            logger.debug(f"[SCANNER] 周末持仓检查异常: {e}")
                    await asyncio.sleep(60)
                    continue

                elif phase == MarketPhase.TRADING:
                    settled = False
                    did_full_scan = await self._scan_loop_trading(trade_date, last_full_scan)
                    if did_full_scan:
                        last_full_scan = time.time()
                    else:
                        continue
                    
                elif phase in (MarketPhase.PREMARKET, MarketPhase.AUCTION):
                    settled = False
                    await self._premarket_auction(trade_date)
                    await asyncio.sleep(120)
                    
                elif phase == MarketPhase.AFTER_CLOSE and not settled and self._broker:
                    await self._scan_loop_settlement(trade_date)
                    settled = True
                    await asyncio.sleep(60)
                    
                else:
                    # 非交易时间(含DEEP_NIGHT/其他)
                    sleep_s = self._scan_loop_phase_sleep(phase)
                    await asyncio.sleep(sleep_s)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            await self._scan_loop_error_recovery(e)

    @staticmethod
    def _scan_loop_phase_sleep(phase) -> int:
        """非交易时间scan_loop的sleep秒数【v2.9.28提取】"""
        if phase == MarketPhase.DEEP_NIGHT:
            return 1800
        return 300

    async def _scan_loop_error_recovery(self, error: Exception):
        """_scan_loop异常恢复【v2.9.28从_scan_loop提取】"""
        logger.error(f"[SCANNER] _scan_loop异常: {error}", exc_info=True)
        self._scan_loop_error_count += 1
        if self._scan_loop_error_count >= 3:
            logger.error(f"[SCANNER] 连续{self._scan_loop_error_count}次异常, scanner退出")
            self._is_running = False
        else:
            logger.warning(f"[SCANNER] 第{self._scan_loop_error_count}次异常, 30秒后尝试恢复")
            await asyncio.sleep(30)
        try:
            if self._loop and not self._loop.is_closed():
                self._loop.call_soon_threadsafe(
                    lambda: self._loop.create_task(self._event_bus.emit(ScannerEvents.SCANNER_ERROR, {
                        "error": str(error),
                        "error_type": type(error).__name__,
                        "timestamp": time.time(),
                        "consecutive_errors": self._scan_loop_error_count,
                    }))
                )
        except Exception as _e:
            logger.debug(f"[SCAN_LOOP] 错误恢复事件发射失败: {_e}")

    async def _scan_loop_trading(self, trade_date: str, last_full_scan: float) -> bool:
        """交易时间(9:30-15:00)处理逻辑
        
        职责: 风控线程看门狗 + 行情恢复 + 全量扫描/等待
        """
        # 【v2.9.5:风控线程健康看门狗】检测风控线程存活, 崩溃自动重启
        if self._risk_running and self._risk_thread and not self._risk_thread.is_alive():
            self._risk_thread_restarts += 1
            logger.warning(
                f"[RISK_WATCHDOG] 风控线程已退出(第{self._risk_thread_restarts}次重启)"
            )
            self._risk_running = True
            self._risk_thread = threading.Thread(
                target=self._risk_loop_sync, daemon=True,
                name="scanner-risk-thread"
            )
            self._risk_thread.start()
            # 重启超过3次告警
            if self._risk_thread_restarts >= 3:
                await self._publish_scanner_event("status", {
                    "event": "risk_thread_unstable",
                    "restarts": self._risk_thread_restarts,
                })
        
        # 【Phase2.2:行情降级自动恢复】每5分钟尝试恢复
        if self._quote_manager.should_try_recover():
            try:
                recovered = await self._quote_manager.try_recover()
                if recovered:
                    self._quote_degrade_level = self._quote_manager.degrade_level
                    await self._publish_scanner_event("status", {
                        "event": "quote_recovered",
                        "degrade_level": 0,
                    })
            except (ConnectionError, OSError, TimeoutError) as e:
                logger.debug(f"[SCAN] 行情恢复尝试异常: {e}")
        
        elapsed = time.time() - last_full_scan
        if elapsed >= self.SCAN_INTERVAL:
            await self.scan_once(trade_date)
            return True
        else:
            # 【Phase1.2:持仓检查已由风控线程接管,扫描循环只做sleep等待下一次全量扫描】
            check_interval = self._get_smart_check_interval(self._broker.get_positions() if self._broker else [])
            await asyncio.sleep(check_interval)
            return False

    async def _scan_loop_settlement(self, trade_date: str):
        """盘后结算(15:05+) — 委托给RuntimePersistence【v2.9.39提取】"""
        await self._runtime_persistence.daily_settlement(trade_date)

    async def _scan_loop_replay(self):
        """回放模式循环: 不受交易时间限制, 持续扫描【v2.9.19提取】"""
        logger.info(f"[REPLAY] 回放循环启动, 日期={self._replay_date}")
        while self._is_running:
            trade_date = self._replay_date or datetime.now().strftime("%Y%m%d")
            await self.scan_once(trade_date, force=True)
            await asyncio.sleep(self.SCAN_INTERVAL)

    def _risk_loop_sync(self):
        """风控独立线程(分级节奏，不受asyncio事件循环影响)
        
        设计原则:
        - threading.Thread(真并行, 不受asyncio协作式调度影响)
        - 1秒止损检查(用缓存数据, 零API成本)
        - 30秒完整quick check(东财缓存, 零额度)
        - 职责: 只负责卖出, 不负责买入
        - 跌停不可卖: 挂起pending_sells, 不丢追踪止损
        - 【v2.9.28】提取_risk_non_trading_sleep/_check_stale_quote_cache/_risk_periodic_checks
        """
        tick = 0
        consecutive_errors = 0
        logger.info("[RISK_THREAD] 风控线程启动")
        
        while self._risk_running:
            try:
                tick += 1
                consecutive_errors = 0
                
                phase = MarketPhase.classify()
                sleep_s = self._risk_non_trading_sleep(phase)
                if sleep_s > 0:
                    time.sleep(sleep_s)
                    continue
                
                with self._cache_lock:
                    realtime_data = dict(self._realtime_cache) if self._realtime_cache else {}

                if not realtime_data or not self._broker:
                    time.sleep(1)
                    continue
                
                self._check_stale_quote_cache(tick, phase)

                # 每1秒: 止损检查
                self._check_stop_loss_only(realtime_data)
                self._last_risk_check_ts = time.time()

                # 周期性检查(60秒/30秒)
                self._risk_periodic_checks(tick)

            except Exception as e:
                consecutive_errors += 1
                logger.error(f"[RISK_THREAD] 风控线程异常({consecutive_errors}次): {e}")
                self._emit_risk_thread_error(e, consecutive_errors)
                sleep_s = self._risk_error_backoff(consecutive_errors, e)
                time.sleep(sleep_s)
                continue
            time.sleep(1)
        
        logger.info("[RISK_THREAD] 风控线程已退出")

    def _risk_periodic_checks(self, tick: int):
        """风控线程周期性检查(60秒跌停超时+30秒quick check)【v2.9.30提取】"""
        # 60秒: 跌停挂起超时检查
        if tick % 60 == 0 and self._position_manager:
            try:
                self._position_manager.check_pending_sells_timeout()
            except (RuntimeError, KeyError, AttributeError) as e:
                logger.debug(f"[RISK_THREAD] pending_sells超时检查异常: {e}")

        # 30秒: 完整quick check(东财缓存, 零额度)
        if tick % 30 == 0 and self._loop and not self._loop.is_closed():
            try:
                risk_trade_date = self._trade_date or datetime.now().strftime("%Y%m%d")
                future = asyncio.run_coroutine_threadsafe(
                    self._check_positions_quick(risk_trade_date),
                    self._loop
                )
                future.result(timeout=10)
            except (RuntimeError, KeyError, TimeoutError, asyncio.TimeoutError) as e:
                logger.debug(f"[RISK_THREAD] quick check异常: {e}")

    @staticmethod
    def _risk_non_trading_sleep(phase: str) -> int:
        """非交易时间返回sleep秒数, 交易时间返回0【v2.9.28提取】"""
        if phase == MarketPhase.WEEKEND:
            return 60
        elif phase == MarketPhase.DEEP_NIGHT:
            return 300
        elif phase not in (MarketPhase.TRADING, MarketPhase.AUCTION):
            return 30
        return 0

    def _check_stale_quote_cache(self, tick: int, phase: str):
        """交易时间内行情缓存过期检测+告警【v2.9.28从_risk_loop_sync提取】"""
        if phase != MarketPhase.TRADING:
            return
        if not self._last_realtime_update_ts:
            return
        cache_age = time.time() - (self._last_realtime_update_ts or 0)
        if cache_age <= 120:
            return
        logger.warning(f"[RISK_THREAD] 行情缓存过期({cache_age:.0f}秒), 风控精度下降")
        # 每5分钟只告警一次(避免刷日志)
        if tick % 300 == 0:
            try:
                if self._loop and not self._loop.is_closed():
                    self._loop.call_soon_threadsafe(
                        lambda: self._loop.create_task(self._event_bus.emit(ScannerEvents.SCANNER_ERROR, {
                            "error": f"行情缓存过期{cache_age:.0f}秒",
                            "error_type": "StaleQuoteCache",
                            "timestamp": time.time(),
                        }))
                    )
            except Exception as _e:
                logger.debug(f"[RISK] 行情缓存过期事件发射失败: {_e}")
    def _risk_error_backoff(consecutive_errors: int, error: Exception) -> int:
        """风控线程错误退避sleep秒数【v2.9.28从_risk_loop_sync提取】
        
        Returns: sleep秒数
        """
        # 3次以内1秒; 3-10次5秒; >10次30秒
        if consecutive_errors >= 10:
            return 30
        elif consecutive_errors >= 3:
            return 5
        return 1

    def _emit_risk_thread_error(self, error: Exception, consecutive_errors: int):
        """风控线程异常事件发射 — 委托给RiskWatchdog【v2.9.39提取】"""
        from nodes.market_monitor.risk_watchdog import RiskWatchdog
        RiskWatchdog.emit_risk_thread_error(self, error, consecutive_errors)

    def _check_stop_loss_only(self, realtime_data: Dict):
        """1秒级止损检查 — 委托给PositionManager【v2.9.41简化】
        
        v2.9.41: 移除冗余的broker/positions检查(PM内部已处理), 
        scanner只负责调用PM和执行卖出结果。
        """
        # 【v2.9.22:跌停恢复重试pending_sells】
        self._retry_pending_sells(realtime_data)
        
        # 委托检查(PM内部已处理: broker检查+持仓获取+跌停挂起+跌停恢复)
        if self._position_manager:
            to_sell = self._position_manager.check_stop_loss_only(realtime_data)
        else:
            to_sell = []
        
        # 执行卖出(PositionManager只做检查,不执行交易)
        self._execute_sell_list_from_risk(to_sell)



    async def _execute_risk_sell(self, pos, reason: str, price: float, quantity: int):
        """风控卖出执行 — 委托给PositionManager【v2.9.35提取】"""
        await self._position_manager.execute_risk_sell(pos, reason, price, quantity)


    async def scan_once(self, trade_date: str, force: bool = False):
        """单次扫描
        
        Args:
            trade_date: 交易日期
            force: 强制模式, 忽略交易时间检查(测试用)
        
        【v2.9.22】新增分步计时, 性能瓶颈可追踪
        """
        t0 = time.time()
        self._scan_count += 1
        scan_time = datetime.now().strftime("%H:%M:%S")

        # 【v2.9.22:成功扫描时重置_scan_loop连续错误计数】
        if self._scan_loop_error_count > 0:
            logger.info(f"[SCAN] 恢复成功(之前连续{self._scan_loop_error_count}次异常)")
            self._scan_loop_error_count = 0

        logger.info(f"[SCAN #{self._scan_count}] 开始扫描 {scan_time}")

        # Step 1: 获取实时行情
        t1 = time.time()
        realtime_data = await self._fetch_realtime_batch(force=force)
        step1_ms = (time.time() - t1) * 1000

        # Step 2: 合并日级因子+实时数据
        t2 = time.time()
        self._update_name_map(realtime_data)
        merged_df = self._merge_factors(realtime_data)
        step2_ms = (time.time() - t2) * 1000

        # Step 3: 策略筛选 + 异动检测 + 9层筛选管道
        t3 = time.time()
        new_signals = await self._apply_strategies_and_filters(merged_df, trade_date, realtime_data)
        step3_ms = (time.time() - t3) * 1000

        # Step 4: 增量更新信号
        t4 = time.time()
        await self._update_signals(new_signals, scan_time)
        step4_ms = (time.time() - t4) * 1000

        # Step 5: 持仓检查(止损止盈)
        t5 = time.time()
        await self._check_positions(realtime_data, trade_date)
        step5_ms = (time.time() - t5) * 1000

        # Step 6: 同步broker实时价格
        self._sync_broker_prices(realtime_data)

        # Step 7: 统计+持久化
        elapsed = time.time() - t0
        self._update_scan_stats(scan_time, len(realtime_data), elapsed)
        await self._persist_scan_result()

        # 【v2.9.28:慢步骤日志提取到ScannerUtils.format_slow_steps】
        slow_info = self._format_slow_steps([
            ("行情", step1_ms), ("因子", step2_ms),
            ("策略+筛选", step3_ms), ("信号", step4_ms),
            ("持仓检查", step5_ms),
        ])

        logger.info(f"[SCAN #{self._scan_count}] 完成: "
                     f"{len(realtime_data)}只 | {len(self._active_signals)}信号 | "
                     f"{elapsed:.1f}秒{slow_info}")

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

        # 异动检测(也经过筛选管道)
        anomaly_signals = await self._detect_anomalies(realtime_data)
        if anomaly_signals:
            anomaly_signals = await self._apply_filter_pipeline(anomaly_signals, trade_date, realtime_data)
        new_signals.extend(anomaly_signals)

        return new_signals

    def _sync_broker_prices(self, realtime_data: Dict[str, Dict]):
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

    def _update_scan_stats(self, scan_time: str, stocks_count: int, elapsed: float):
        """更新扫描统计+看门狗心跳【v2.9.19提取】"""
        self._last_scan_time = scan_time
        self._stats["scans"] += 1
        self._stats["stocks_scanned"] = stocks_count
        if self._risk_watchdog:
            self._risk_watchdog.update_heartbeat()
        self._last_scan_duration_ms = elapsed * 1000
        self._last_scan_ts = time.time()

    async def _persist_scan_result(self):
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
        self, signals: List[ScanSignal], trade_date: str, realtime_data: Dict
    ) -> List[ScanSignal]:
        """9层筛选管道: 强制空仓/情绪/竞价/排序/仓位"""
        if not signals:
            return signals

        # 转换为管道输入格式
        candidates = self._signals_to_candidates(signals)

        # 执行管道(v2.9.40:positions/account由pipeline自动从broker获取)
        result = await self._filter_pipeline.apply(
            trade_date=trade_date,
            candidates=candidates,
            realtime_data=realtime_data,
        )

        # 日志+链路追踪
        for layer, detail in result.layer_details.items():
            logger.info(f"[FILTER] {layer}: {detail}")
        await self._save_scan_traces(result)

        # 强制空仓 → 清所有持仓
        if result.action == "empty":
            await self._execute_force_empty(result.force_empty_reason)
            return []

        # 处理筛选结果(合并+情绪调仓+EventBus事件)
        return await self._process_filter_result(signals, result, trade_date)

    async def _process_filter_result(
        self, signals: List[ScanSignal], result, trade_date: str
    ) -> List[ScanSignal]:
        """处理筛选管道结果: 合并信号+情绪调仓+EventBus事件【v2.9.31提取】"""
        # 转回ScanSignal，注入筛选决策详情+逐层trace
        filtered_signals = self._merge_filter_result(signals, result)

        # 更新仓位系数和情绪信息
        old_phase = self._current_sentiment.get("period", "")
        self._current_position_ratio = result.position_ratio
        self._current_sentiment = self._filter_pipeline.get_sentiment_info()
        new_phase = self._current_sentiment.get("period", "")

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

    def _signals_to_candidates(self, signals: List[ScanSignal]) -> List[Dict]:
        """将ScanSignal列表转换为filter_pipeline候选格式【v2.9.35:委托给ScanSignal.to_candidate】"""
        return [s.to_candidate() for s in signals]

    async def _execute_force_empty(self, reason: str):
        """强制空仓: 卖出所有持仓【v2.9.20:复用_liquidate_positions, 修复total_qty→available_qty(T+1合规)】"""
        logger.warning(f"[FILTER] ⚠️ 强制空仓: {reason}")
        await self._liquidate_positions(reason=f"强制空仓: {reason}", source="force_empty")


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

    def _safe_read_state(self, attr_name: str) -> Dict:
        """线程安全深拷贝共享状态(统一辅助)【v2.9.31提取】
        
        替代4个_safe_copy_*方法, 统一state_lock保护读取模式:
        - _state_lock未初始化 → 直接浅拷贝(启动前无并发风险)
        - _state_lock已初始化 → 加锁后浅拷贝再释放
        
        Args:
            attr_name: 共享状态属性名(trailing_stops/position_risk_levels/pending_sells等)
        Returns:
            dict浅拷贝(调用方可安全修改不影响原始状态)
        """
        source = getattr(self, attr_name, {})
        if self._state_lock is None:
            return dict(source)
        with self._state_lock:
            return dict(source)

    def _get_activated_trailing_stops_safe(self) -> Dict:
        """线程安全读取已激活的追踪止损(深拷贝+过滤)"""
        all_stops = self._safe_read_state("_trailing_stops")
        return {k: v for k, v in all_stops.items() if v.get("activated")}

    def _safe_copy_position_risk_levels(self) -> Dict:
        """线程安全深拷贝position_risk_levels"""
        return self._safe_read_state("_position_risk_levels")

    def _safe_copy_trailing_stops(self) -> Dict:
        """线程安全深拷贝trailing_stops"""
        return self._safe_read_state("_trailing_stops")

    def _safe_copy_pending_sells(self) -> Dict:
        """线程安全深拷贝pending_sells"""
        return self._safe_read_state("_pending_sells")

    # ==================== 智能持仓检查频率 ====================

    def _make_quote_event_emitter(self):
        """创建行情事件发射回调(v2.9:消除QuoteManager对Scanner的循环引用)
        
        之前QuoteManager直接持有scanner引用来发射EventBus事件,
        造成QuoteManager→Scanner循环依赖。改用回调函数解耦:
        - QuoteManager只依赖回调接口,不知道Scanner存在
        - Scanner提供回调,内部调用EventBus.emit
        """
        scanner = self
        async def emit_quote_event(event_name: str, data: dict):
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

