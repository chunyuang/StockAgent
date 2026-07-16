"""
ScannerInitializer — MarketScanner初始化逻辑

从scanner.py提取的初始化方法集，职责:
1. 状态变量初始化(_init_state)
2. Broker初始化(_init_broker)
3. 管道初始化(_init_pipeline)
4. 模块初始化(_init_modules)
5. 风控初始化(_init_risk)

设计原则:
- 所有方法都是同步的(初始化阶段无需async)
- 通过scanner引用访问属性，不持有状态
- __init__仍留在scanner.py(构造器不可提取)
"""

import logging
import os
import threading
from typing import Dict, Any, Optional, List

logger = logging.getLogger("scanner.init")


class ScannerInitializer:
    """Scanner初始化方法集(混入类)
    
    用法: MarketScanner继承此类，自动获得_init_*系列方法。
    不需要实例化，方法通过self访问scanner的属性。
    """

    def _init_state(self) -> None:
        """初始化基础状态变量【v2.9.3提取, v2.9.37:标量默认值提升为类属性, v2.9.56:分组初始化, v2.9.67:提取到ScannerInitializer】"""
        self._init_risk_state()
        self._init_execution_state()
        self._init_cache_state()
        self._init_signal_state()

    def _init_risk_state(self) -> None:
        """初始化风控+交易状态【v2.9.56从_init_state提取】"""
        self._position_risk_overrides: Dict[str, Dict] = {}
        self._trailing_stops: Dict[str, Dict] = {}
        self._position_risk_levels: Dict[str, str] = {}
        self._pending_orders: Dict[str, Dict] = {}
        self._pending_sells: Dict[str, Dict] = {}
        # 【v2.9.92w】冷却期信息(与回测对齐)
        self._cooldown_info: Dict[str, Any] = {}  # {trigger_date, cooldown_days, position_cap, reason}
        self._force_empty_cooldown_until: str = ""
        # 【v2.9.97h-v10】竞价强制空仓确认状态: 09:20后累计确认, 09:30开盘后立即执行pending
        self._premarket_force_empty_state: Dict[str, Any] = {
            "pending": False, "pending_action": "none", "executed": False, "executed_at": "",
            "reason": "", "reasons": [], "risk_level": "L0", "risk_score": 0, "action": "none",
            "confirm_count": 0, "final_confirm_count": 0,
            "scan_count": 0, "valid_scan_count": 0, "data_quality": "unknown",
            "market_snapshot": {}, "position_risk": {}, "anomalies": [], "history": [],
            "last_limit_up": None, "last_limit_down": None, "last_total_stocks": None,
        }
        self.SELL_LOGIC_MODE = os.getenv("SELL_LOGIC_MODE", "legacy")

    def _init_execution_state(self) -> None:
        """初始化执行质量统计【v2.9.56从_init_state提取】"""
        self._execution_stats = {
            "total_slippage_pct": 0.0,
            "total_fills": 0,
            "partial_fills": 0,
            "avg_fill_latency_ms": 0.0,
            "stop_loss_response_times": [],
        }

    def _init_cache_state(self) -> None:
        """初始化数据缓存【v2.9.56从_init_state提取】"""
        import pandas as pd
        # 【v2.9.79:提前初始化_state_lock, 避免scan_once在未start时state_lock=None崩溃】
        if self._state_lock is None:
            self._state_lock = threading.Lock()
        self._daily_factors_df: Optional[pd.DataFrame] = None
        self._realtime_cache: Dict[str, Dict] = {}
        self._prev_realtime_cache: Dict[str, Dict] = {}
        self._all_codes: List[str] = []

    def _init_signal_state(self) -> None:
        """初始化信号+时间线+交易统计【v2.9.56从_init_state提取】"""
        self._active_signals: List = []
        self._timeline: List[Dict] = []
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

    def _init_broker(self) -> None:
        """初始化撮合引擎【v2.9.3提取, v2.9.54:提取_init_broker_gm/_init_broker_sim, v2.9.67:提取到ScannerInitializer】"""
        trade_mode = self.config.get("trade_mode", self.MODE_SIMULATED)
        self._trade_mode = trade_mode
        self._stock_name_map: Dict[str, str] = {}

        if trade_mode == self.MODE_GM:
            self._init_broker_gm()
        else:
            self._init_broker_sim(trade_mode)

    def _init_broker_gm(self) -> None:
        """初始化掘金量化Broker【v2.9.54从_init_broker提取】"""
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

    def _init_broker_sim(self, trade_mode: str) -> None:
        """初始化仿真Broker(含调试/回放/标准模式)【v2.9.54从_init_broker提取】"""
        from nodes.market_monitor.broker import SimulatedBroker
        initial_cash = self.config.get("initial_cash", 1_000_000)
        self._dry_run = (trade_mode == self.MODE_DRY_RUN)
        self._replay_mode = (trade_mode == self.MODE_REPLAY)
        self._replay_date = self.config.get("replay_date", None)
        self._replay_provider = None
        self._gm_broker = None

        is_virtual = trade_mode in (self.MODE_DRY_RUN, self.MODE_REPLAY)
        self._broker = SimulatedBroker(account_id=self.account_id, initial_cash=initial_cash, virtual_mode=is_virtual)

        if self._dry_run:
            logger.info("[SCANNER] 交易模式: 🔍调试模式(只扫描不交易)")
        elif self._replay_mode:
            try:
                from nodes.market_monitor.replay_provider import ReplayDataProvider
                self._replay_provider = ReplayDataProvider()
                if self._replay_date:
                    self._replay_provider.get_replay_data(self._replay_date)
            except (ImportError, OSError, ValueError) as e:
                logger.error(f"[SCANNER] 回放数据加载失败: {e}")
            logger.info(f"[SCANNER] 交易模式: 🔄回放模式(日期={self._replay_date or '自动'})")
        else:
            logger.info("[SCANNER] 交易模式: 内置仿真撮合")

    def _init_pipeline(self) -> None:
        """初始化9层筛选管道【v2.9.3提取, v2.9.67:提取到ScannerInitializer】"""
        from nodes.market_monitor.live_filter_pipeline import LiveFilterPipeline
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

    def _init_modules(self) -> None:
        """初始化EventBus+QuoteManager+核心模块+风控+执行质量【v2.9.3提取, v2.9.25拆分为子方法, v2.9.67:提取到ScannerInitializer】"""
        self._init_event_and_quote()
        self._init_signal_and_risk()
        self._init_core_modules()
        self._init_execution_quality()

    def _init_event_and_quote(self) -> None:
        """初始化EventBus+QuoteManager【v2.9.25提取】"""
        from nodes.market_monitor.scanner_event_bus import ScannerEventBus
        from nodes.market_monitor.quote_manager import QuoteManager
        self._event_bus = ScannerEventBus()
        self._quote_manager = QuoteManager()
        self._quote_manager.set_event_emitter(self._make_quote_event_emitter())
        self._position_manager = None
        self._strategy_scorer = None
        self._signal_manager = None
        self._data_router: Optional[Any] = None

    def _init_signal_and_risk(self) -> None:
        """初始化信号分发器+参数中心+风控看门狗【v2.9.25提取】"""
        from nodes.market_monitor.signal_dispatcher import (
            SignalDispatcher, redis_channel_handler, log_channel_handler
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

    def _init_core_modules(self) -> None:
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

        self._use_tiered = self.config.get("use_tiered_scanner", False)
        self._tiered_scanner = None
        if self._use_tiered:
            from nodes.market_monitor.tiered_scanner import TieredScanner
            self._tiered_scanner = TieredScanner(scanner=self)
            logger.info("[SCANNER] 分级行情: L1(5min全市场) → L2(30s候选池) → L3(5s持仓)")

    def _init_execution_quality(self) -> None:
        """初始化执行质量检查+滑点模型【v2.9.25提取】"""
        from nodes.market_monitor.execution_quality import PreTradeChecker, SlippageModel
        self._pre_trade_checker = PreTradeChecker(broker=self._broker, config={
            "max_position_per_stock": 0.35,
            "max_total_position": 0.70,
        })
        self._slippage_model = SlippageModel

    def _init_risk(self) -> None:
        """初始化风控熔断参数【v2.9.3提取, v2.9.67:提取到ScannerInitializer】"""
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
