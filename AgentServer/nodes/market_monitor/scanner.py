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
import json
import logging
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
        """初始化基础状态变量【v2.9.3提取】"""
        # 单票风控覆盖
        self._position_risk_overrides: Dict[str, Dict] = {}

        # 追踪止损状态
        self._trailing_stops: Dict[str, Dict] = {}

        # 持仓风险等级
        self._position_risk_levels: Dict[str, str] = {}

        # 订单状态跟踪
        self._pending_orders: Dict[str, Dict] = {}

        # 跌停挂起的卖出指令
        self._pending_sells: Dict[str, Dict] = {}

        # 快照节流
        self._last_snapshot_save: float = 0.0
        self._snapshot_dirty: bool = False

        # 交易日(由start()设置)
        self._trade_date: str = ""

        # 净值峰值
        self._nav_peak: float = 1.0

        # 风控独立线程
        self._risk_thread = None
        self._risk_running = False
        self._risk_thread_restarts = 0  # 【v2.9.5:风控线程重启计数】
        self._cache_lock = None
        self._state_lock = None
        self._loop = None

        # 卖出逻辑灰度开关
        import os
        self.SELL_LOGIC_MODE = os.getenv("SELL_LOGIC_MODE", "legacy")

        # 行情降级状态
        self._quote_degrade_level = 0
        self._quote_fail_count = 0
        self._quote_last_recover_check = 0

        # 执行质量统计
        self._execution_stats = {
            "total_slippage_pct": 0.0,
            "total_fills": 0,
            "partial_fills": 0,
            "avg_fill_latency_ms": 0.0,
            "stop_loss_response_times": [],
        }

        # 运行状态
        self._is_running = False
        self._task: Optional[asyncio.Task] = None
        self._scan_count = 0
        self._last_scan_time = ""
        self._last_scan_ts: float = 0.0
        self._last_risk_check_ts: float = 0.0

        # 数据缓存
        self._daily_factors_df: Optional[pd.DataFrame] = None
        self._realtime_cache: Dict[str, Dict] = {}
        self._prev_realtime_cache: Dict[str, Dict] = {}
        self._all_codes: List[str] = []

        # 信号与时间线
        self._active_signals: List[ScanSignal] = []
        self._timeline: List[Dict] = []

        # 统计
        self._stats = {
            "scans": 0,
            "signals_found": 0,
            "trades_executed": 0,
            "stop_losses": 0,
            "take_profits": 0,
            "stocks_scanned": 0,
        }

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
            except Exception as e:
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
        """初始化EventBus+QuoteManager+PositionManager+SignalManager等模块【v2.9.3提取】"""
        # EventBus
        self._event_bus = ScannerEventBus()

        # QuoteManager(回调模式,无scanner引用)
        self._quote_manager = QuoteManager()
        self._quote_manager.set_event_emitter(self._make_quote_event_emitter())
        self._position_manager = None  # 延迟初始化
        self._strategy_scorer = None
        self._signal_manager = None
        self._data_router: Optional[Any] = None

        # 信号分发器
        from nodes.market_monitor.signal_dispatcher import (
            SignalDispatcher, redis_channel_handler, feishu_channel_handler, log_channel_handler
        )
        self._signal_dispatcher = SignalDispatcher(scanner=self)
        self._signal_dispatcher.register_channel("log", log_channel_handler)
        self._signal_dispatcher.register_channel("redis", redis_channel_handler)
        self._feishu_registered = False

        # 参数中心
        from nodes.market_monitor.strategy_param_center import param_center
        self._param_center = param_center

        # 风控看门狗
        from nodes.market_monitor.risk_watchdog import RiskWatchdog
        self._risk_watchdog = RiskWatchdog(scanner=self)
        self._risk_watchdog.register_alert_channel(self._signal_dispatcher.dispatch)

        # PositionManager+StrategyScorer+SignalManager+PositionChecker
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

        # 执行质量检查
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

    # 委托映射: 方法名 → (子模块属性, 子模块方法名)
    # 不再需要为每个委托写一个存根方法, __getattr__自动路由
    _DELEGATE_MAP = {
        # RuntimePersistence委托
        "_save_timeline": ("_runtime_persistence", "save_timeline"),
        "_save_scan_traces": ("_runtime_persistence", "save_scan_traces"),
        "_load_timeline": ("_runtime_persistence", "load_timeline"),
        "_load_runtime_snapshot": ("_runtime_persistence", "load_runtime_snapshot"),
        "_save_runtime_snapshot": ("_runtime_persistence", "save_runtime_snapshot"),
        "_premarket_auction": ("_runtime_persistence", "premarket_auction"),
        # QuoteManager委托
        "_short_to_ts_code": ("_quote_manager_class", "short_to_ts_code"),
        # StrategyScorer委托
        "_apply_strategies": ("_strategy_scorer", "apply_strategies"),
        # SignalManager委托
        "_update_signals": ("_signal_manager", "update_signals"),
        "_push_signals": ("_signal_manager", "_push_signals"),
        "_add_timeline_log": ("_signal_manager", "_add_timeline_log"),
        "_write_audit_log": ("_signal_manager", "_write_audit_log"),
        "_execute_signals": ("_signal_manager", "execute_signals"),
        # PositionChecker委托
        "_check_positions": ("_position_checker", "check_positions"),
        "_check_positions_quick": ("_position_checker", "check_positions_quick"),
        "_get_smart_check_interval": ("_position_checker", "get_smart_check_interval"),
        "_get_open_price": ("_position_checker", "_get_open_price"),
        # _is_limit_down保留显式定义(有False fallback),不放入DELEGATE_MAP
        # PositionManager委托
        "_get_effective_stop_price": ("_position_manager", "get_effective_stop_price"),
        "_update_trailing_stops": ("_position_manager", "update_trailing_stops"),
        "_calc_would_buy_shares": ("_position_manager", "calc_would_buy_shares"),
        "_calc_position_ratio": ("_position_manager", "calc_position_ratio"),
        "_calc_stop_loss_price": ("_position_manager", "calc_stop_loss_price"),
        "_calc_take_profit_price": ("_position_manager", "calc_take_profit_price"),
        # ScannerUtils委托
        "_safe_round": ("_scanner_utils", "safe_round"),
        "_publish_scanner_event": ("_scanner_utils", "publish_scanner_event"),
        "_position_to_dict": ("_scanner_utils", "position_to_dict"),
        "_signal_to_dict": ("_scanner_utils", "signal_to_dict"),
        "_extract_key_factors": ("_scanner_utils", "extract_key_factors"),
        "generate_summary_report": ("_scanner_utils", "generate_summary_report"),
        # 【v2.9.9:更多委托消除显式存根】
        "_merge_factors": ("_strategy_scorer", "merge_factors"),
        "_get_effective_strategy_config": ("_strategy_scorer", "get_effective_strategy_config"),
        "_get_strategy_risk": ("_strategy_scorer", "get_strategy_risk"),
        "_detect_anomalies": ("_strategy_scorer", "detect_anomalies"),
        "_check_circuit_breaker": ("_risk_watchdog_class", "check_circuit_breaker"),
        "_record_trade_result": ("_risk_watchdog_class", "record_trade_result"),
        "reset_circuit_breaker": ("_risk_watchdog_class", "reset_circuit_breaker"),
        "_compute_health_score": ("_scanner_utils", "compute_health_score"),
        "_save_performance_snapshot": ("_runtime_persistence", "save_performance_snapshot"),
        "_push_daily_summary": ("_runtime_persistence", "push_daily_summary"),
    }

    def __getattr__(self, name):
        """动态委托分派 — 纯转发方法不再需要显式定义【v2.9.3, v2.9.17:委托路由提取】"""
        delegate = self._DELEGATE_MAP.get(name)
        if delegate is None:
            raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")
        from nodes.market_monitor.scanner_delegate_router import resolve_delegate
        return resolve_delegate(self, name, delegate)


    @property
    def event_bus(self) -> ScannerEventBus:
        """事件总线(只读)"""
        return self._event_bus

    def is_running(self):
        return self._is_running

    def get_status(self) -> Dict[str, Any]:
        """Scanner完整状态快照"""
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
            "risk_watchdog": self._risk_watchdog.get_status() if hasattr(self, '_risk_watchdog') else {},
            "signal_dispatcher": self._signal_dispatcher.get_stats() if hasattr(self, '_signal_dispatcher') else {},
            "tiered_scanner": self._tiered_scanner.get_status() if self._tiered_scanner else {},
            "trailing_stops": self._get_activated_trailing_stops_safe(),
            "position_risk_levels": self._safe_copy_position_risk_levels(),
            "execution_stats": dict(self._execution_stats),
            "smart_check_interval": self._get_smart_check_interval(self._broker.get_positions()) if self._is_running else None,
            "quote_degrade_level": self._quote_manager.degrade_level,
            "quote_degrade_desc": self._quote_manager.degrade_desc,
            "sell_logic_mode": self.SELL_LOGIC_MODE,
            "health": self._compute_health_score(),
        }

    def _build_account_info(self) -> Dict[str, Any]:
        """构建账户信息(兼容掘金+模拟broker)【v2.9.19提取】"""
        default = {"total_assets": 0, "available_cash": 0, "market_value": 0, "total_profit": 0}
        if self._trade_mode == self.MODE_GM and self._gm_broker:
            gm_acct = self._gm_broker.get_account()
            return {
                "total_assets": gm_acct.get("total_assets", 0),
                "available_cash": gm_acct.get("available_cash", 0),
                "market_value": gm_acct.get("market_value", 0),
                "total_profit": 0,
            }
        elif self._broker:
            acct = self._broker.get_account()
            return {
                "total_assets": round(acct.total_assets, 2),
                "available_cash": round(acct.available_cash, 2),
                "market_value": round(acct.market_value, 2),
                "total_profit": round(acct.total_profit, 2),
            }
        return default

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
        if not self._broker:  # 【v2.9.9:None guard】
            return []
        result = []
        for p in self._broker.get_positions():
            risk = self._get_strategy_risk(p.strategy)
            sl_price = self._calc_stop_loss_price(p, risk)
            tp_price = self._calc_take_profit_price(p, risk)
            sl_pct = risk.get("stop_loss_pct", 0.03) * 100
            tp_pct = risk.get("take_profit_pct", 0.07) * 100
            mv = round(p.current_price * p.total_qty, 2)
            profit_amt = round((p.current_price - p.avg_cost) * p.total_qty, 2)
            result.append({
                "ts_code": p.ts_code, "stock_name": p.stock_name or self._stock_name_map.get(p.ts_code, ""),
                "strategy": p.strategy, "shares": p.total_qty,
                "available_qty": p.available_qty,
                "cost_price": round(p.avg_cost, 2),
                "current_price": round(p.current_price, 2),
                "profit_pct": round(p.profit_pct, 2),
                "profit_amount": profit_amt,  # 【P1-2】盈亏金额
                "market_value": mv,  # 【P1-2】持仓市值
                "today_buy": p.today_buy_qty,
                "stop_loss_pct": round(sl_pct, 1),
                "take_profit_pct": round(tp_pct, 1),
                "stop_loss_price": sl_price,
                "take_profit_price": tp_price,
                "distance_to_stop": round(p.profit_pct + sl_pct, 1),  # 【P1-2】距止损距离
                "buy_date": p.buy_date,
                # 【V59:追踪止损+风险等级】(线程安全读取)
                "trailing_stop": self._safe_copy_trailing_stops().get(p.ts_code),
                "risk_level": self._safe_copy_position_risk_levels().get(p.ts_code, "normal"),
                "effective_stop_price": self._get_effective_stop_price(p, risk),
            })
        return result

    def get_timeline(self) -> List[Dict]:
        return list(self._timeline)
    async def start(self, trade_date: str = None):
        """启动扫描"""
        if self._is_running:
            return {"success": True, "message": "已在运行中"}

        # 【Phase1.2:提前初始化线程锁(被premarket_prepare/_load_positions使用)】
        import threading
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
        
        # 【Phase3.4+v2.9.4】审计日志TTL索引+恢复pending_sells
        await self._restore_start_state()

        # 【v2.8:EventBus订阅器注册(在scan_loop启动前)】
        try:
            from nodes.market_monitor.scanner_event_subscribers import register_subscribers
            register_subscribers(self)
        except Exception as e:
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
        return {"success": True, "message": "扫描器启动成功"}

    async def _detect_param_drift(self):
        """启动时检测参数漂移【v2.9.18:从start()提取】"""
        try:
            from nodes.market_monitor.strategy_param_center import param_center
            drifts = await param_center.detect_drift()
            if drifts:
                logger.warning(f"[PARAMS] 检测到{len(drifts)}个参数漂移: {drifts[:3]}")
                await self._publish_scanner_event("status", {
                    "type": "param_drift", "drifts": drifts[:5],
                })
        except Exception as e:
            logger.debug(f"[PARAMS] 漂移检测失败(非关键): {e}")

    async def _restore_start_state(self):
        """启动时恢复状态(审计索引+pending_sells)【v2.9.18:从start()提取】"""
        # 【Phase3.4:审计日志TTL索引(90天自动过期)】
        try:
            from core.managers import mongo_manager
            if mongo_manager.db:
                await mongo_manager.db["audit_log"].create_index(
                    "timestamp", expireAfterSeconds=7776000  # 90天
                )
        except Exception:
            pass

        # 【v2.9.4:从MongoDB恢复pending_sells(上次停机时保存的跌停挂起)】
        try:
            from core.managers import mongo_manager
            if mongo_manager.db:
                doc = await mongo_manager.db["scanner_state"].find_one({"_id": "pending_sells"})
                if doc and doc.get("items"):
                    with self._state_lock:
                        self._pending_sells.update(doc["items"])
                    logger.info(f"[START] 恢复{len(doc['items'])}个pending_sells")
        except Exception as e:
            logger.debug(f"[START] pending_sells恢复失败(非关键): {e}")

    def _start_risk_thread(self):
        """启动风控独立线程【v2.9.18:从start()提取】"""
        import threading
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
            except Exception as e:
                logger.warning(f"[SCANNER] 数据源关闭失败: {e}")
            self._data_router = None
        logger.info(f"[SCANNER] 已停止 (清仓={sell_all})")
        return {"success": True, "message": f"扫描器已停止" + ("并清仓" if sell_all else "")}

    async def _sell_all_positions(self):
        """停止时清仓所有持仓【v2.9.18:从stop()提取】"""
        positions = self._broker.get_positions()
        for pos in positions:
            if pos.available_qty > 0:
                try:
                    self._broker.update_realtime(pos.ts_code, pos.current_price)
                    ok, msg, order = self._broker.place_order(
                        ts_code=pos.ts_code,
                        stock_name=pos.stock_name,
                        side="sell",
                        quantity=pos.available_qty,
                        price=pos.current_price,
                        order_type="market",
                        strategy=pos.strategy,
                        reason="停止清仓",
                    )
                    if ok:
                        self._timeline.append({
                            "time": datetime.now().strftime("%H:%M:%S"),
                            "action": "sell",
                            "ts_code": pos.ts_code,
                            "stock_name": pos.stock_name,
                            "strategy": pos.strategy,
                            "shares": pos.available_qty,
                            "price": order.filled_price,
                            "reason": "停止清仓",
                            "profit_pct": round(pos.profit_pct, 2),
                            "profit_amount": round((pos.current_price - pos.avg_cost) * pos.available_qty, 2),
                        })
                        logger.info(f"[STOP] 清仓卖出 {pos.ts_code} {pos.available_qty}股@{order.filled_price:.2f}")
                    else:
                        logger.warning(f"[STOP] 清仓卖出失败 {pos.ts_code}: {msg}")
                except Exception as e:
                    logger.error(f"[STOP] 清仓卖出异常 {pos.ts_code}: {e}")
        # 清仓后强制保存
        try:
            await self._broker.save_state(force=True)
        except Exception:
            pass

    async def _persist_stop_state(self):
        """停止时持久化状态【v2.9.18:从stop()提取】"""
        # 强制保存当前状态(跳过节流)
        if self._broker:
            try:
                await self._broker.save_state(force=True)
            except Exception:
                pass
            # 【Phase1.1】同步保存Scanner运行时状态
            await self._save_runtime_snapshot(force=True)
        
        # 保存时间线到MongoDB
        try:
            await self._save_timeline()
        except Exception:
            pass
        
        # 【v2.9.4:保存pending_sells状态到MongoDB(防止重启丢失)】
        # 【v2.9.17:使用_with_state_lock统一加锁模式】
        try:
            from core.managers import mongo_manager
            if mongo_manager.db:
                from nodes.market_monitor.risk_watchdog import RiskWatchdog
                pending = RiskWatchdog._with_state_lock(
                    self, lambda: dict(self._pending_sells),
                    fallback=lambda: dict(self._pending_sells),
                )
                if pending:
                    await mongo_manager.db["scanner_state"].update_one(
                        {"_id": "pending_sells"},
                        {"$set": {"items": pending, "saved_at": datetime.now().isoformat()}},
                        upsert=True,
                    )
                    logger.info(f"[STOP] 保存{len(pending)}个pending_sells到MongoDB")
        except Exception as e:
            logger.debug(f"[STOP] pending_sells保存失败(非关键): {e}")

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
        """从MongoDB stock_basic加载ts_code→名称映射"""
        try:
            from core.managers import mongo_manager
            if not mongo_manager.is_initialized:
                return
            docs = await mongo_manager.db["stock_basic"].find(
                {}, {"ts_code": 1, "name": 1, "_id": 0}
            ).to_list(length=None)
            for doc in docs:
                if doc.get("ts_code") and doc.get("name"):
                    self._stock_name_map[doc["ts_code"]] = doc["name"]
            logger.info(f"[SCANNER] 加载{len(self._stock_name_map)}只股票名称映射")
        except Exception as e:
            logger.warning(f"[SCANNER] 加载名称映射失败: {e}")
    async def _warm_weekend_cache(self):
        """周末调试: 用日级因子(上一交易日收盘)填充行情缓存"""
        import time as _time
        warmed = 0
        realtime = {}
        df = self._daily_factors_df
        if df is None or df.empty:
            return
        
        for _, row in df.iterrows():
            ts_code = row.get("ts_code")
            if not ts_code:
                continue
            close = row.get("close")
            pre_close = row.get("pre_close")
            pct_chg = row.get("pct_chg")
            if close and close > 0:
                realtime[ts_code] = {
                    "price": close,
                    "pct_chg": pct_chg if pct_chg else 0,
                    "pre_close": pre_close if pre_close else close,
                    "open": row.get("open", close),
                    "high": row.get("high", close),
                    "low": row.get("low", close),
                    "vol": row.get("vol", 0),
                    "amount": row.get("amount", 0),
                    "turnover_rate": row.get("turnover_rate", 0),
                    "volume_ratio": row.get("volume_ratio", 0),
                    "name": self._stock_name_map.get(ts_code, ""),
                }
                warmed += 1
        
        # 写入本地缓存
        self._realtime_cache = realtime
        
        # 也写入东方财富缓存(如果存在)
        if self._quote_manager:
            self._quote_manager.warm_sources_cache(realtime)
        
        logger.info(f"[SCANNER] 周末缓存预热: {warmed}只(上一交易日收盘价)")

    async def premarket_prepare(self, trade_date: str):
        """盘前: 加载全市场代码 + 预加载日级因子"""
        logger.info(f"[SCANNER] 盘前准备 {trade_date}")

        # 【V50:重置每日风控状态——daily_start_assets/熔断计数器】
        # 【v2.9.17:使用_with_state_lock统一加锁模式】
        if self._broker:
            try:
                acct = self._broker.get_account()
                if acct:
                    from nodes.market_monitor.risk_watchdog import RiskWatchdog
                    def _reset_cb():
                        self._circuit_breaker["daily_start_assets"] = acct.total_assets
                        self._circuit_breaker["today_trades"] = 0
                        self._circuit_breaker["today_losses"] = 0
                        self._circuit_breaker["trading_paused"] = False
                        self._circuit_breaker["pause_reason"] = ""
                    RiskWatchdog._with_state_lock(self, _reset_cb, fallback=_reset_cb)
                    logger.info(f"[SCANNER] 每日风控重置: start_asset={acct.total_assets:.2f}")
            except Exception as e:
                logger.warning(f"[SCANNER] 每日风控重置失败: {e}")

        # 【V59→Phase1.1优化:追踪止损+风险等级不再无条件清除】
        # _load_positions()→_load_runtime_snapshot()会根据快照日期判断:
        #   同一天重启 → 从快照恢复(保留盘中状态)
        #   新的一天 → 清除(在_load_runtime_snapshot中snap_date!=trade_date时不恢复)
        # 这里只清除执行统计(每次启动都重置)
        self._execution_stats["stop_loss_response_times"] = []
        # 【v2.9.17:使用_with_state_lock统一加锁模式】
        from nodes.market_monitor.risk_watchdog import RiskWatchdog
        RiskWatchdog._with_state_lock(self, lambda: self._pending_sells.clear(),
                                       fallback=lambda: self._pending_sells.clear())
        logger.info("[SCANNER] 执行统计+跌停挂起已重置(追踪止损/风险等级将在加载持仓时恢复)")

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

        # 4. 竞价预选(仅交易时间9:15-9:30)
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
        """加载全市场代码"""
        try:
            from core.managers import mongo_manager
            await mongo_manager.initialize()

            # 从stock_daily_ak_full获取当日有数据的所有股票
            today = datetime.now().strftime("%Y%m%d")
            # 如果今天没数据, 用最近一个交易日
            cursor = mongo_manager.db["stock_daily_ak_full"].find(
                {"trade_date": int(today)},
                {"ts_code": 1, "_id": 0}
            )
            docs = await cursor.to_list(length=6000)
            if not docs:
                # 取最近交易日
                latest = await mongo_manager.db["stock_daily_ak_full"].find_one(
                    sort=[("trade_date", -1)],
                    projection={"trade_date": 1, "_id": 0}
                )
                if latest:
                    cursor = mongo_manager.db["stock_daily_ak_full"].find(
                        {"trade_date": latest["trade_date"]},
                        {"ts_code": 1, "_id": 0}
                    )
                    docs = await cursor.to_list(length=6000)

            self._all_codes = [d["ts_code"] for d in docs if d.get("ts_code")]
            logger.info(f"[SCANNER] 加载{len(self._all_codes)}只股票代码")
        except Exception as e:
            logger.error(f"[SCANNER] 加载股票列表失败: {e}")
            self._all_codes = []

    async def _load_daily_factors(self, trade_date: str):
        """预加载日级因子(从MongoDB读取)"""
        try:
            from core.managers import mongo_manager
            await mongo_manager.initialize()

            # 读取前一个交易日的因子(已计算好的)
            # 取最近的trade_date <= trade_date
            latest_doc = await mongo_manager.db["stock_daily_ak_full"].find_one(
                {"trade_date": {"$lte": int(trade_date)}},
                sort=[("trade_date", -1)],
                projection={"trade_date": 1, "_id": 0}
            )
            if not latest_doc:
                return

            factor_date = latest_doc["trade_date"]

            # 读取关键因子
            factor_fields = [
                "ts_code", "pct_chg", "pre_close", "close", "open", "high", "low",
                "ma5", "macd", "rsi_6", "boll_upper", "atr",
                "turnover_rate", "volume_ratio", "circ_mv",
                "is_limit_up", "is_limit_down", "first_limit_up", "limit_up_count",
                "fear_greed_index"
            ]
            projection = {"_id": 0}
            for f in factor_fields:
                projection[f] = 1

            cursor = mongo_manager.db["stock_daily_ak_full"].find(
                {"trade_date": factor_date},
                projection
            )
            docs = await cursor.to_list(length=6000)
            if docs:
                self._daily_factors_df = pd.DataFrame(docs)
                logger.info(f"[SCANNER] 加载{len(docs)}只股票日级因子(date={factor_date})")
        except Exception as e:
            logger.error(f"[SCANNER] 加载日级因子失败: {e}")

    async def _load_positions(self):
        """加载当前持仓(优先从MongoDB恢复, 否则从broker获取)
        
        【Phase1.1增强】恢复后同时恢复Scanner运行时状态(追踪止损/风险等级/跌停挂起等)
        Broker是持仓唯一权威来源, Scanner快照只存Scanner独有状态。
        """
        if self._broker:
            # Step 1: Broker恢复(权威持仓)
            try:
                restored = await self._broker.load_state()
                if restored and self._broker.positions:
                    logger.info(f"[SCANNER] 持仓已从MongoDB恢复: {len(self._broker.positions)}个")
            except Exception as e:
                logger.warning(f"[SCANNER] 持仓恢复失败(使用空持仓): {e}")
        
        # Step 2: Scanner运行时状态恢复
        await self._load_runtime_snapshot()
        
        # 【v2.9.13:trailing_stops线程安全读取(日志输出)】
        _ts_count = len(self._safe_copy_trailing_stops())
        logger.info(f"[SCANNER] 持仓: {len(self._broker.get_positions()) if self._broker else 0}个, "
                    f"追踪止损: {_ts_count}个")

    # ==================== Phase1.1: 运行时状态持久化 ====================
    async def _scan_loop(self, trade_date: str):
        """主扫描循环(双层节奏 + 智能刷新)
        
        全量扫描(5分钟): 涨停池+策略筛选 → 发现新信号
        持仓检查(30秒): 只查持仓股行情 → 止损止盈
        
        【智能刷新】
        - 交易时间(9:30-15:00): 正常5分钟全量+30秒持仓
        - 盘前(9:00-9:30): 2分钟检查一次(竞价预选)
        - 非交易时间: 5分钟检查一次(只检查持仓,不拉行情)
        - 深夜(23:00-8:00): 30分钟检查一次(几乎不刷新)
        
        必盈200次/天:
        - 全量: 23次/轮 × 8轮(4h/5min) = 184次 → 合理
        - 持仓检查: 不消耗必盈额度(用东方财富缓存)
        """
        settled = False
        last_full_scan = 0  # 上次全量扫描时间

        # 回放模式: 不受交易时间限制, 持续扫描
        if self._replay_mode:
            await self._scan_loop_replay()
            return

        try:
            while self._is_running:
                now = datetime.now()
                ct = now.strftime("%H:%M")
                h = now.hour
                
                # === 周末: 调试模式(60秒循环, 用缓存数据) ===
                if now.weekday() >= 5:
                    pos_count = len(self._broker.get_positions()) if self._broker else 0
                    if pos_count > 0:
                        try:
                            await self._check_positions_quick(trade_date)
                        except Exception as e:
                            logger.debug(f"[SCANNER] 周末持仓检查异常: {e}")
                    await asyncio.sleep(60)  # 周末60秒循环
                    continue

                # === 交易时间(9:30-15:00) ===
                if "09:30" <= ct <= "15:00":
                    settled = False
                    did_full_scan = await self._scan_loop_trading(trade_date, last_full_scan)
                    if did_full_scan:
                        last_full_scan = time.time()
                    else:
                        continue
                
                # === 盘前(9:00-9:30): 竞价预选 ===
                elif "09:00" <= ct < "09:30":
                    settled = False
                    await self._premarket_auction(trade_date)
                    await asyncio.sleep(120)  # 2分钟
                    
                # === 收盘后(15:05+): 自动结算+报告 ===
                elif ct >= "15:05" and not settled and self._broker:
                    await self._scan_loop_settlement(trade_date)
                    settled = True
                    await asyncio.sleep(60)
                    
                # === 深夜(23:00-8:00): 极低频 ===
                elif h >= 23 or h < 8:
                    await asyncio.sleep(1800)  # 30分钟
                    
                # === 其他非交易时间: 低频 ===
                else:
                    await asyncio.sleep(300)  # 5分钟

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[SCANNER] 异常: {e}", exc_info=True)
            self._is_running = False
            # 【v2.9.15】发射异常事件(前端可感知)
            try:
                asyncio.ensure_future(self._event_bus.emit(ScannerEvents.SCANNER_ERROR, {
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "timestamp": time.time(),
                }))
            except Exception:
                pass

    # ==================== v2.9.13: _scan_loop时间段提取 ====================

    async def _scan_loop_trading(self, trade_date: str, last_full_scan: float) -> bool:
        """交易时间(9:30-15:00)处理逻辑\n        \n        职责: 风控线程看门狗 + 行情恢复 + 全量扫描/等待
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
            except Exception as e:
                logger.debug(f"[SCAN] 行情恢复尝试异常: {e}")
        
        elapsed = time.time() - last_full_scan
        if elapsed >= self.SCAN_INTERVAL:
            await self.scan_once(trade_date)
            return True
        else:
            # 【Phase1.2:持仓检查已由风控线程接管,扫描循环只做sleep等待下一次全量扫描】
            check_interval = self._get_smart_check_interval(self._broker.get_positions())
            await asyncio.sleep(check_interval)
            return False

    async def _scan_loop_settlement(self, trade_date: str):
        """盘后结算(15:05+)处理逻辑\n        \n        职责: Broker结算+持久化 + EventBus盘后结算 + Timeline保存
        """
        if self._broker:
            self._broker.daily_settlement(trade_date)
        try:
            await self._broker.save_state()
        except Exception:
            pass
        logger.info("[SCANNER] 收盘自动结算+持久化完成")
        # 【v2.9:盘后结算通过EventBus驱动,解耦scanner主循环】
        try:
            account = self._broker.account if self._broker else None
            await self._event_bus.emit(ScannerEvents.DAILY_SETTLED, {
                "trade_date": trade_date,
                "total_profit": getattr(account, 'today_profit', 0) if account else 0,
                "total_assets": getattr(account, 'total_assets', 0) if account else 0,
            })
        except Exception:
            pass
        # 保存timeline到MongoDB
        try:
            await self._save_timeline()
        except Exception:
            pass

    async def _scan_loop_replay(self):
        """回放模式循环: 不受交易时间限制, 持续扫描【v2.9.19提取】"""
        logger.info(f"[REPLAY] 回放循环启动, 日期={self._replay_date}")
        while self._is_running:
            trade_date = self._replay_date or datetime.now().strftime("%Y%m%d")
            await self.scan_once(trade_date, force=True)
            await asyncio.sleep(self.SCAN_INTERVAL)

    # ==================== Phase1.2: 风控独立线程 ====================

    def _risk_loop_sync(self):
        """风控独立线程(分级节奏，不受asyncio事件循环影响)
        
        设计原则:
        - threading.Thread(真并行, 不受asyncio协作式调度影响)
        - 1秒止损检查(用缓存数据, 零API成本)
        - 30秒完整quick check(东财缓存, 零额度)
        - 职责: 只负责卖出, 不负责买入
        - 跌停不可卖: 挂起pending_sells, 不丢追踪止损
        - 【v2.9.5】使用self._trade_date保证交易日一致性
        """
        import threading
        tick = 0
        logger.info("[RISK_THREAD] 风控线程启动")
        
        while self._risk_running:
            try:
                tick += 1
                
                # 非交易时间不做检查(与scan_loop同样的时间判断)
                now = datetime.now()
                ct = now.strftime("%H:%M")
                is_weekend = now.weekday() >= 5
                if (ct < "09:25" or ct > "15:05") and not is_weekend:
                    time.sleep(30)  # 工作日非交易时间30秒检查一次
                    continue
                
                # 周末: 60秒检查一次(调试模式)
                if is_weekend:
                    time.sleep(60)
                    # 继续执行检查(用缓存数据)
                
                # 从共享缓存读取(线程安全, 浅拷贝)
                with self._cache_lock:
                    realtime_data = dict(self._realtime_cache) if self._realtime_cache else {}

                if not realtime_data or not self._broker:
                    time.sleep(1)
                    continue

                # ── 每1秒: 止损检查(用缓存数据, 零成本) ──
                self._check_stop_loss_only(realtime_data)
                self._last_risk_check_ts = time.time()  # 【Phase4.3】

                # ── 每60秒: 跌停挂起超时检查(2小时超时自动清除) ──
                if tick % 60 == 0 and self._position_manager:
                    try:
                        self._position_manager.check_pending_sells_timeout()
                    except Exception as e:
                        logger.debug(f"[RISK_THREAD] pending_sells超时检查异常: {e}")

                # ── 每30秒: 完整quick check(东财缓存, 零额度) ──
                if tick % 30 == 0 and self._loop and not self._loop.is_closed():
                    try:
                        # 【v2.9.5:优先使用scanner统一的_trade_date, 保证与主循环一致】
                        risk_trade_date = self._trade_date or datetime.now().strftime("%Y%m%d")
                        future = asyncio.run_coroutine_threadsafe(
                            self._check_positions_quick(risk_trade_date),
                            self._loop
                        )
                        future.result(timeout=10)
                    except Exception as e:
                        logger.debug(f"[RISK_THREAD] quick check异常: {e}")

            except Exception as e:
                logger.error(f"[RISK_THREAD] 风控线程异常: {e}")
                # 【v2.9.15】风控线程异常也发射事件
                try:
                    asyncio.ensure_future(self._event_bus.emit(ScannerEvents.SCANNER_ERROR, {
                        "error": f"风控线程异常: {e}",
                        "error_type": "RiskThreadError",
                        "timestamp": time.time(),
                    }))
                except Exception:
                    pass
            time.sleep(1)  # 真sleep,不受asyncio影响
        
        logger.info("[RISK_THREAD] 风控线程已退出")

    def _check_stop_loss_only(self, realtime_data: Dict):
        """1秒级止损检查 — 委托给PositionManager【Phase3.1】
        
        v2.9修复: PositionManager.check_stop_loss_only已处理跌停挂起+恢复,
        scanner不再重复检查跌停(之前scanner和PM双重检查导致逻辑混乱)
        
        v2.9.5增强: _execute_risk_sell超时时记录待执行卖出, 避免丢失风控指令
        
        执行流程: PM返回to_sell → scanner执行卖出(通过asyncio主循环)
        """
        if not self._broker:
            return
        
        positions = self._broker.get_positions()
        if not positions:
            return
        
        # 委托检查(PM已处理跌停挂起+跌停恢复)
        if self._position_manager:
            to_sell = self._position_manager.check_stop_loss_only(realtime_data)
        else:
            to_sell = []
        
        # 执行卖出(PositionManager只做检查,不执行交易)
        for pos, reason, price, risk in to_sell:
            if self._loop and not self._loop.is_closed():
                try:
                    sell_qty = pos.available_qty
                    future = asyncio.run_coroutine_threadsafe(
                        self._execute_risk_sell(pos, reason, price, sell_qty),
                        self._loop
                    )
                    future.result(timeout=5)
                except asyncio.TimeoutError:
                    # 【v2.9.5:超时不丢弃,记录到pending_sells待下次执行】
                    logger.warning(
                        f"[RISK_THREAD] 卖出执行超时(5秒): {pos.ts_code} {reason}, "
                        f"加入pending_sells待下次执行"
                    )
                    with self._state_lock:
                        if pos.ts_code not in self._pending_sells:
                            self._pending_sells[pos.ts_code] = {
                                "reason": reason, "price": price,
                                "added_at": time.time(),
                                "source": "risk_thread_timeout",
                            }
                except Exception as e:
                    logger.error(f"[RISK_THREAD] 卖出执行失败: {pos.ts_code} {e}")

    async def _execute_risk_sell(self, pos, reason: str, price: float, quantity: int):
        """风控线程触发的卖出执行(在asyncio主循环中运行)【v2.9.12:try/except保护, v2.9.19:提取_post_sell_cleanup】"""
        if pos.available_qty <= 0:
            return
        
        sell_profit_pct = pos.profit_pct
        sell_profit_amount = (pos.current_price - pos.avg_cost) * quantity
        
        try:
            self._broker.update_realtime(pos.ts_code, pos.current_price)
            ok, msg, order = self._broker.place_order(
                ts_code=pos.ts_code, stock_name=pos.stock_name,
                side="sell", quantity=quantity, price=price,
                order_type="market", strategy=pos.strategy, reason=reason,
            )
        except Exception as e:
            logger.error(f"[RISK_SELL] place_order异常 {pos.ts_code}: {e}")
            return
        
        if ok:
            await self._post_sell_cleanup(
                pos, reason, order, quantity,
                sell_profit_pct, sell_profit_amount, source="risk_sell",
            )
        else:
            logger.warning(f"[RISK_SELL] 卖出失败 {pos.ts_code}: {msg}")

    async def _post_sell_cleanup(
        self, pos, reason: str, order, quantity: int,
        profit_pct: float, profit_amount: float, *, source: str = "sell",
    ):
        """卖出成功后统一清理: timeline+统计+状态清理+事件+持久化【v2.9.19提取】"""
        # Timeline记录
        self._timeline.append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "action": "sell",
            "ts_code": pos.ts_code,
            "stock_name": pos.stock_name,
            "strategy": pos.strategy,
            "shares": quantity,
            "price": order.filled_price,
            "reason": reason,
            "profit_pct": round(profit_pct, 2),
            "profit_amount": round(profit_amount, 2),
            "decision_detail": {
                "sell_reason": reason,
                "profit_pct": round(profit_pct, 2),
                "profit_amount": round(profit_amount, 2),
                "cost_price": pos.avg_cost,
                "sell_price": order.filled_price,
                "current_price": pos.current_price,
                "source": source,
            },
        })
        self._stats["stop_losses"] += 1
        # 记录交易结果到circuit_breaker(v2.9.9:profit_pct/100转比率)
        self._record_trade_result(profit_pct / 100.0)
        # 清理追踪止损(线程安全)
        with self._state_lock:
            self._trailing_stops.pop(pos.ts_code, None)
            self._position_risk_levels.pop(pos.ts_code, None)
        # 事件通知(timeline + EventBus)
        try:
            await self._publish_scanner_event("timeline", {"item": self._timeline[-1]})
        except Exception:
            pass
        try:
            await self._event_bus.emit(ScannerEvents.RISK_SELL_EXECUTED, {
                "ts_code": pos.ts_code, "reason": reason,
                "price": order.filled_price, "profit_pct": profit_pct,
            })
            await self._event_bus.emit(ScannerEvents.POSITION_CHANGED, {
                "ts_code": pos.ts_code, "action": "sell", "reason": reason,
            })
        except Exception:
            pass
        logger.info(f"[{source.upper()}] {reason}: {pos.ts_code} {quantity}股@{order.filled_price:.2f}")
        # 持久化(broker + 运行时快照)
        try:
            await self._broker.save_state(force=True)
        except Exception:
            pass
        try:
            await self._save_runtime_snapshot(force=True)
        except Exception:
            pass

    async def scan_once(self, trade_date: str, force: bool = False):
        """单次扫描
        
        Args:
            trade_date: 交易日期
            force: 强制模式, 忽略交易时间检查(测试用)
        """
        t0 = time.time()
        self._scan_count += 1
        scan_time = datetime.now().strftime("%H:%M:%S")

        logger.info(f"[SCAN #{self._scan_count}] 开始扫描 {scan_time}")

        # Step 1: 获取实时行情
        realtime_data = await self._fetch_realtime_batch(force=force)

        # Step 2: 合并日级因子+实时数据
        self._update_name_map(realtime_data)
        merged_df = self._merge_factors(realtime_data)

        # Step 3: 策略筛选 + 9层筛选管道
        new_signals = await self._apply_strategies(merged_df, trade_date)
        new_signals = await self._apply_filter_pipeline(new_signals, trade_date, realtime_data)

        # Step 3.6: 异动检测(也经过筛选管道)
        anomaly_signals = await self._detect_anomalies(realtime_data)
        if anomaly_signals:
            anomaly_signals = await self._apply_filter_pipeline(anomaly_signals, trade_date, realtime_data)
        new_signals.extend(anomaly_signals)

        # Step 4: 增量更新信号
        await self._update_signals(new_signals, scan_time)

        # Step 5: 持仓检查(止损止盈)
        await self._check_positions(realtime_data, trade_date)

        # Step 6: 同步broker实时价格
        self._sync_broker_prices(realtime_data)

        # Step 7: 统计+持久化
        elapsed = time.time() - t0
        self._update_scan_stats(scan_time, len(realtime_data), elapsed)
        await self._persist_scan_result()

        logger.info(f"[SCAN #{self._scan_count}] 完成: "
                     f"{len(realtime_data)}只 | {len(self._active_signals)}信号 | "
                     f"{elapsed:.1f}秒")

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
        if hasattr(self, '_risk_watchdog'):
            self._risk_watchdog.update_heartbeat()
        self._last_scan_duration_ms = elapsed * 1000
        self._last_scan_ts = time.time()

    async def _persist_scan_result(self):
        """扫描结果持久化: broker状态+时间线+运行时快照【v2.9.19提取】"""
        try:
            saved = await self._broker.save_state()
            logger.info(f"[SCAN] save_state={saved} positions={len(self._broker.positions)} orders={len(self._broker.orders)}")
            await self._save_timeline()
            await self._save_runtime_snapshot(force=False)
        except Exception as e:
            logger.warning(f"[SCAN] save_state失败: {e}")

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

        # 获取持仓信息
        positions = []
        if self._broker:
            for p in self._broker.get_positions():
                positions.append({"ts_code": p.ts_code, "strategy": p.strategy})

        # 执行管道
        result = await self._filter_pipeline.apply(
            trade_date=trade_date,
            candidates=candidates,
            positions=positions,
            account={"cash": self._broker.account.available_cash if self._broker else 0},
            realtime_data=realtime_data,
        )

        # 日志
        for layer, detail in result.layer_details.items():
            logger.info(f"[FILTER] {layer}: {detail}")

        # 【V50.1】保存完整链路追踪到MongoDB(含被淘汰候选)
        await self._save_scan_traces(result)

        # 强制空仓 → 清所有持仓
        if result.action == "empty":
            await self._execute_force_empty(result.force_empty_reason)
            return []

        # 转回ScanSignal，注入筛选决策详情+逐层trace
        filtered_signals = self._merge_filter_result(signals, result)

        # 存储仓位系数和情绪信息(供execute_signals使用)
        old_phase = self._current_sentiment.get("period", "")
        self._current_position_ratio = result.position_ratio
        self._current_sentiment = self._filter_pipeline.get_sentiment_info()
        new_phase = self._current_sentiment.get("period", "")

        logger.info(f"[FILTER] 筛选完成: {len(signals)}→{len(filtered_signals)}个信号, "
                     f"仓位系数={result.position_ratio:.0%}")
        
        # 【Phase2.4:情绪phase变化→动态调仓】
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
        """将ScanSignal列表转换为filter_pipeline候选格式【v2.9提取】"""
        candidates = []
        for s in signals:
            candidates.append({
                "ts_code": s.ts_code,
                "stock_name": s.stock_name,
                "strategy": s.strategy,
                "strategy_name": s.strategy_name,
                "price": s.price,
                "pct_chg": s.pct_chg,
                "volume_ratio": s.volume_ratio,
                "turnover_rate": s.turnover_rate,
                "is_limit_up": s.is_limit_up,
                "limit_up_count": s.limit_up_count,
                "reason": s.reason,
                "confidence": s.confidence,
            })
        return candidates

    async def _execute_force_empty(self, reason: str):
        """强制空仓: 卖出所有持仓【v2.9.19:复用_post_sell_cleanup统一善后】"""
        logger.warning(f"[FILTER] ⚠️ 强制空仓: {reason}")
        if not self._broker:
            return
        positions = self._broker.get_positions()
        sold, failed = 0, 0
        for p in positions:
            try:
                self._broker.update_realtime(p.ts_code, p.current_price)
                profit_pct = p.profit_pct
                profit_amount = (p.current_price - p.avg_cost) * p.total_qty
                ok, msg, order = self._broker.place_order(
                    ts_code=p.ts_code,
                    stock_name=p.stock_name if hasattr(p, 'stock_name') else p.ts_code,
                    side="sell",
                    quantity=p.total_qty,
                    price=p.current_price,
                    reason=f"强制空仓: {reason}",
                )
                if ok:
                    sold += 1
                    await self._post_sell_cleanup(
                        p, f"强制空仓: {reason}", order, p.total_qty,
                        profit_pct, profit_amount, source="force_empty",
                    )
                else:
                    failed += 1
                    logger.warning(f"[FORCE_EMPTY] {p.ts_code} 卖出失败: {msg}")
            except Exception as e:
                failed += 1
                logger.error(f"[FORCE_EMPTY] {p.ts_code} 异常: {e}")
        logger.info(f"[FORCE_EMPTY] 完成: 卖出{sold}只, 失败{failed}只")

    def _merge_filter_result(self, signals: List[ScanSignal], result) -> List[ScanSignal]:
        """将filter_pipeline结果合并回ScanSignal【v2.9提取】"""
        candidate_map = {c["ts_code"]: c for c in result.candidates}
        filtered_signals = []
        for s in signals:
            if s.ts_code in candidate_map:
                # 注入9层筛选决策详情
                s.decision_detail = {
                    "filter_pipeline": {
                        "layers_applied": result.layers_applied,
                        "layer_details": result.layer_details,
                        "position_ratio": result.position_ratio,
                        "action": result.action,
                    },
                    "signal_reason": s.reason,
                    "strategy": s.strategy,
                    "strategy_name": s.strategy_name,
                    "price": s.price,
                    "pct_chg": s.pct_chg,
                    "volume_ratio": s.volume_ratio,
                    "turnover_rate": s.turnover_rate,
                    "factors": s.factors,
                    "scan_time": s.scan_time,
                }
                # 逐层trace
                for layer_name, detail in result.layer_details.items():
                    s.layer_trace[layer_name] = {
                        "detail": detail,
                        "applied": result.layers_applied.get(layer_name, False),
                    }
                s.layer_trace["L8_position"] = {
                    "position_ratio": result.position_ratio,
                    "action": result.action,
                }
                filtered_signals.append(s)
            else:
                # 被过滤掉的信号
                s.signal_status = "filtered"
                s.layer_trace["filter_result"] = {
                    "filtered_out": True,
                    "reason": "9层筛选管道过滤",
                    "layer_details": result.layer_details,
                }
        return filtered_signals

    # ==================== 信号管理 ====================

    # ==================== 公共止损止盈方法 ====================

        # PositionManager委托 (止损价/止盈价已在DELEGATE_MAP中声明)
        # _check_stop_loss_take_profit 保留在scanner中因为需要先更新追踪止损状态

    def _check_stop_loss_take_profit(self, positions, realtime_data: Dict) -> List[Tuple]:
        """止损止盈检查 — 委托给PositionManager【Phase3.1】"""
        # 更新追踪止损状态(仍在Scanner,因为状态属于Scanner)
        self._update_trailing_stops(positions, realtime_data)
        
        if self._position_manager:
            return self._position_manager.check_stop_loss_take_profit(positions, realtime_data)
        return []  # fallback(不应到达)

    # ==================== 持仓检查 ====================
    # ==================== 情绪调仓执行(v2.9.6提取核心逻辑到EmotionCycle) ====================
    
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
    
    async def _handle_emotion_phase_change(self, old_phase: str, new_phase: str):
        """情绪phase变化时的动态调仓【v2.9.6重构】
        
        规则来源: EmotionCycleManager.DOWNGRADE_RULES
        执行: phase降级时减仓/清仓低利润, 升级时不做操作
        分批执行: max_per_round=2, 间隔0.5秒(避免冲击)
        """
        from nodes.market_monitor.emotion_cycle import EmotionPhase, emotion_cycle_manager
        
        # 将字符串转为EmotionPhase枚举
        try:
            old_enum = EmotionPhase(old_phase)
            new_enum = EmotionPhase(new_phase)
        except ValueError:
            logger.info(f"[EMOTION] phase变化 {old_phase}→{new_phase}, 无法识别的阶段")
            return
        
        rule = emotion_cycle_manager.get_downgrade_rule(old_enum, new_enum)
        if not rule:
            logger.info(f"[EMOTION] phase变化 {old_phase}→{new_phase}, 无需调仓")
            return
        
        logger.warning(f"[EMOTION] phase降级 {old_phase}→{new_phase}: {rule['desc']}")
        
        if not self._broker:
            return
        
        positions = self._broker.get_positions()
        if not positions:
            return
        
        # 委托给_build_emotion_sell_list构建卖出列表
        to_sell = self._build_emotion_sell_list(positions, rule, old_phase, new_phase)
        
        if not to_sell:
            logger.info(f"[EMOTION] phase降级无需调仓(无符合条件持仓)")
            return
        
        batch_size = 2
        trade_date = self._trade_date or datetime.now().strftime("%Y%m%d")
        for i in range(0, len(to_sell), batch_size):
            batch = to_sell[i:i+batch_size]
            if self._position_checker:
                await self._position_checker.execute_sell_list(batch, trade_date, source="emotion")
            if i + batch_size < len(to_sell):
                await asyncio.sleep(0.5)
        
        logger.warning(f"[EMOTION] 调仓完成: 卖出{len(to_sell)}只, {rule['desc']}")
        
        # 推送事件 + 审计日志
        await self._publish_scanner_event("timeline", {
            "item": {
                "time": datetime.now().strftime("%H:%M:%S"),
                "action": "emotion_rebalance",
                "reason": rule['desc'],
                "old_phase": old_phase,
                "new_phase": new_phase,
                "sold_count": len(to_sell),
            }
        })

    # ==================== Phase4.3: 健康度评分 ====================

    # ==================== 线程安全辅助方法(v2.5) ====================

    def _get_activated_trailing_stops_safe(self) -> Dict:
        """线程安全读取已激活的追踪止损(深拷贝+过滤)"""
        if self._state_lock is None:
            all_stops = dict(self._trailing_stops)
        else:
            with self._state_lock:
                all_stops = dict(self._trailing_stops)
        return {k: v for k, v in all_stops.items() if v.get("activated")}

    def _safe_copy_position_risk_levels(self) -> Dict:
        """线程安全深拷贝position_risk_levels"""
        if self._state_lock is None:
            return dict(self._position_risk_levels)
        with self._state_lock:
            return dict(self._position_risk_levels)

    def _safe_copy_trailing_stops(self) -> Dict:
        """线程安全深拷贝trailing_stops"""
        if self._state_lock is None:
            return dict(self._trailing_stops)
        with self._state_lock:
            return dict(self._trailing_stops)

    def _safe_copy_pending_sells(self) -> Dict:
        """线程安全深拷贝pending_sells【v2.9.18】"""
        if self._state_lock is None:
            return dict(self._pending_sells)
        with self._state_lock:
            return dict(self._pending_sells)

    # ==================== V59:智能持仓检查频率 ====================

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
            except Exception:
                pass
        return emit_quote_event

    def _is_limit_down(self, ts_code: str) -> bool:
        """判断是否跌停 — 委托给PositionChecker【v2.9.6移除fallback, v2.9.18公开接口】"""
        if self._position_checker:
            return self._position_checker.is_limit_down(ts_code)
        return False  # 无PositionChecker时默认非跌停(保守策略)

    def _validate_live_params(self):
        """实盘参数校验 — 委托给StrategyParamCenter【v2.9.16:简化try/except】"""
        try:
            from nodes.market_monitor.strategy_param_center import StrategyParamCenter
            StrategyParamCenter.validate_live_params(self._broker, self._get_strategy_risk)
        except Exception:
            pass  # fallback: 不校验(StrategyParamCenter不可用时不阻塞)

    def update_strategy_config(self, strategy_key: str, updates: Dict[str, Any]):
        """策略参数热更新(无需重启scanner) + 持久化到MongoDB — 委托给StrategyParamCenter【v2.9.16:简化, v2.9.17:审计增强】"""
        # 【v2.9.17:记录变更前后的值,用于审计日志】
        old_values = {}
        try:
            strategy_config = self.config.get("strategies", {}).get(strategy_key, {})
            for k in updates:
                if k in strategy_config:
                    old_values[k] = strategy_config[k]
        except Exception:
            pass

        try:
            from nodes.market_monitor.strategy_param_center import StrategyParamCenter
            StrategyParamCenter.update_scanner_config(self.config, strategy_key, updates)
            logger.info(f"[SCANNER] 策略参数热更新: {strategy_key}")
        except Exception:
            logger.warning(f"[SCANNER] 策略参数热更新失败: {strategy_key}")
            return
        # EventBus: 参数更新事件(含old_values审计) + 持久化(非阻塞)
        try:
            asyncio.ensure_future(self._event_bus.emit(ScannerEvents.PARAM_UPDATED, {
                "strategy_key": strategy_key, "updates": updates,
                "old_values": old_values,  # 【v2.9.17:审计增强】
            }))
        except Exception:
            pass
        try:
            asyncio.ensure_future(StrategyParamCenter.persist_scanner_overrides(self.config))
        except Exception:
            pass

    async def _persist_strategy_overrides(self):
        """将strategy_overrides持久化到MongoDB — 委托给StrategyParamCenter"""
        try:
            from nodes.market_monitor.strategy_param_center import StrategyParamCenter
            await StrategyParamCenter.persist_scanner_overrides(self.config)
        except Exception:
            pass

    async def _load_strategy_overrides(self):
        """从MongoDB恢复strategy_overrides — 委托给StrategyParamCenter"""
        try:
            from nodes.market_monitor.strategy_param_center import StrategyParamCenter
            data = await StrategyParamCenter.load_scanner_overrides()
            if data:
                if "strategy_overrides" not in self.config:
                    self.config["strategy_overrides"] = {}
                self.config["strategy_overrides"].update(data)
                logger.info(f"[SCANNER] 从MongoDB恢复策略参数: {len(data)}个策略")
        except Exception:
            pass

    # 【v2.9.9:以下方法已移至DELEGATE_MAP+__getattr__动态委托,不再显式定义】
    # _compute_health_score → ScannerUtils.compute_health_score(self)
    # _detect_anomalies → StrategyScorer.detect_anomalies(rt, active_signals, prev_cache)
    # _check_circuit_breaker → RiskWatchdog.check_circuit_breaker(self)
    # _record_trade_result → RiskWatchdog.record_trade_result(self, profit_pct)
    # reset_circuit_breaker → RiskWatchdog.reset_circuit_breaker(self)
    # _save_performance_snapshot → RuntimePersistence.save_performance_snapshot(trade_date)
    # _push_daily_summary → RuntimePersistence.push_daily_summary(trade_date)
    # _merge_factors → StrategyScorer.merge_factors(realtime_data)
    # _get_effective_strategy_config → StrategyScorer.get_effective_strategy_config(strategy_key)
    # _get_strategy_risk → StrategyScorer.get_strategy_risk(strategy_key)

