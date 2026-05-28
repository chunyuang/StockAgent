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
    EMOTION_DOWNGRADE_RULES = {
        ("rising", "differentiation"): {"action": "reduce", "keep_ratio": 0.7, "desc": "高潮→分化: 减仓30%"},
        ("rising", "chaos"):          {"action": "reduce", "keep_ratio": 0.5, "desc": "高潮→震荡: 减仓50%"},
        ("rising", "bearish"):        {"action": "clear_low_profit", "min_profit": 0.03, "desc": "高潮→冰点: 低利润(<3%)清仓"},
        ("differentiation", "chaos"):  {"action": "reduce", "keep_ratio": 0.7, "desc": "分化→震荡: 减仓30%"},
        ("differentiation", "bearish"): {"action": "clear_low_profit", "min_profit": 0.03, "desc": "分化→冰点: 低利润(<3%)清仓"},
        ("chaos", "bearish"):         {"action": "clear_low_profit", "min_profit": 0.02, "desc": "震荡→冰点: 低利润(<2%)清仓"},
    }

    # 交易模式
    MODE_SIMULATED = "simulated"  # 内置仿真撮合
    MODE_GM = "gm"                # 掘金量化
    MODE_DRY_RUN = "dry_run"      # 调试模式: 只扫描不交易
    MODE_REPLAY = "replay"        # 回放模式: 用历史数据模拟实时行情

    def __init__(self, account_id: str = "default", config: Dict = None):
        self.account_id = account_id
        self.config = config or {}

        # 单票风控覆盖(用户手动调整止损止盈)
        self._position_risk_overrides: Dict[str, Dict] = {}

        # 【V59:追踪止损状态】
        # key=ts_code, value={high_price: 最高价, trailing_stop_pct: 追踪止损比例, activated: 是否激活}
        self._trailing_stops: Dict[str, Dict] = {}

        # 【V59:持仓风险等级(决定检查频率)】
        # key=ts_code, value="normal"/"warning"/"critical"
        self._position_risk_levels: Dict[str, str] = {}

        # 【V59:订单状态跟踪】
        self._pending_orders: Dict[str, Dict] = {}  # order_id → {status, retry_count, ...}

        # 【Phase1.1:运行时状态持久化——跌停挂起的卖出指令】
        self._pending_sells: Dict[str, Tuple] = {}  # ts_code → (reason, price)

        # 【Phase1.1:运行时状态持久化——快照节流】
        self._last_snapshot_save: float = 0.0
        self._snapshot_dirty: bool = False

        # 【Phase1.2:风控独立线程】
        self._risk_thread = None
        self._risk_running = False
        self._cache_lock = None  # threading.Lock(在start时初始化)
        self._loop = None       # asyncio事件循环引用
        
        # 【Phase1.3:卖出逻辑灰度开关】
        import os
        self.SELL_LOGIC_MODE = os.getenv("SELL_LOGIC_MODE", "legacy")
        # "legacy"  = Scanner内嵌(旧)
        # "checker" = sell_signal_checker(新)
        # "compare" = 两者都跑,只执行旧逻辑,记录差异(灰度)
        
        # 【Phase2.2:行情降级状态】
        self._quote_degrade_level = 0   # 0=正常, 1=东财降级, 2=日线缓存
        self._quote_fail_count = 0     # 连续失败次数
        self._quote_last_recover_check = 0  # 上次恢复检查时间
        # _quote_staleness已迁移到QuoteManager.get_staleness()

        # 【V59:执行质量统计】
        self._execution_stats = {
            "total_slippage_pct": 0.0,  # 累计滑点
            "total_fills": 0,           # 成交次数
            "partial_fills": 0,         # 部分成交次数
            "avg_fill_latency_ms": 0.0, # 平均成交延迟
            "stop_loss_response_times": [],  # 止损响应时间(ms)
        }

        # 状态
        self._is_running = False
        self._task: Optional[asyncio.Task] = None
        self._scan_count = 0
        self._last_scan_time = ""
        # 【Phase4.3:健康度】
        self._last_scan_ts: float = 0.0      # 上次全量扫描时间戳(monotonic)
        self._last_risk_check_ts: float = 0.0 # 上次风控检查时间戳(monotonic)

        # 数据
        # 【Phase3.1:QuoteManager+PositionManager+StrategyScorer+SignalManager】
        self._quote_manager = QuoteManager()
        self._position_manager = None  # 延迟初始化(需要self引用)
        self._strategy_scorer = None   # 延迟初始化
        self._signal_manager = None    # 延迟初始化
        self._data_router: Optional[Any] = None  # DataSourceRouter实例(兼容,委托给QuoteManager)
        self._daily_factors_df: Optional[pd.DataFrame] = None
        self._realtime_cache: Dict[str, Dict] = {}  # ts_code → 实时行情(由QuoteManager维护)
        self._prev_realtime_cache: Dict[str, Dict] = {}  # ts_code → 上轮实时行情(由QuoteManager维护)
        self._all_codes: List[str] = []  # 全市场代码

        # 撮合引擎: 根据模式选择
        trade_mode = self.config.get("trade_mode", self.MODE_SIMULATED)
        self._trade_mode = trade_mode
        initial_cash = self.config.get("initial_cash", 1_000_000)

        # 【调试增强】dry_run模式: 只扫描不交易
        self._dry_run = (trade_mode == self.MODE_DRY_RUN)

        # 【回放模式】用MongoDB历史数据模拟实时行情
        self._replay_mode = (trade_mode == self.MODE_REPLAY)
        self._replay_date = self.config.get("replay_date", None)
        self._replay_provider = None

        if trade_mode == self.MODE_GM:
            # 掘金模式
            from nodes.market_monitor.gm_broker import GmBroker
            self._gm_broker = GmBroker(
                token=self.config.get("gm_token", ""),
                strategy_id=self.config.get("gm_strategy_id", ""),
                mode=1,  # MODE_LIVE
                serv_addr=self.config.get("gm_serv_addr", ""),
                account_id=account_id,
            )
            self._broker = None  # 掘金模式下不用SimulatedBroker
            logger.info(f"[SCANNER] 交易模式: 掘金量化")
        elif self._dry_run:
            # 调试模式: 仍创建broker用于模拟, 但不实际下单
            self._broker = SimulatedBroker(account_id=account_id, initial_cash=initial_cash)
            self._gm_broker = None
            logger.info(f"[SCANNER] 交易模式: 🔍调试模式(只扫描不交易)")
        elif self._replay_mode:
            # 回放模式: 用历史数据模拟实时行情
            self._broker = SimulatedBroker(account_id=account_id, initial_cash=initial_cash)
            self._gm_broker = None
            try:
                from nodes.market_monitor.replay_provider import ReplayDataProvider
                self._replay_provider = ReplayDataProvider()
                if self._replay_date:
                    # 预加载数据
                    self._replay_provider.get_replay_data(self._replay_date)
            except Exception as e:
                logger.error(f"[SCANNER] 回放数据加载失败: {e}")
            logger.info(f"[SCANNER] 交易模式: 🔄回放模式(日期={self._replay_date or '自动'})")
        else:
            # 内置仿真模式
            self._broker = SimulatedBroker(account_id=account_id, initial_cash=initial_cash)
            self._gm_broker = None
            logger.info(f"[SCANNER] 交易模式: 内置仿真撮合")

        # 信号
        self._active_signals: List[ScanSignal] = []
        self._timeline: List[Dict] = []  # 今日交易时间线

        # 9层筛选管道
        self._filter_pipeline = LiveFilterPipeline(
            scanner=self,
            config={
                "enable_force_empty": True,
                "enable_special_period": True,
                "enable_sentiment_cycle": True,
                "enable_premarket_filter": True,
                "enable_auction_filter": True,
                "max_total_position": 0.7,
                "max_position_per_stock": 0.35,  # 【V50:与回测V49对齐,从0.20→0.35提升资金利用率】
                "max_candidates_per_scan": 10,
            }
        )
        self._current_position_ratio = 1.0  # 默认满仓
        self._current_sentiment = {"score": 50, "period": "chaos"}

        # 统计
        self._stats = {
            "scans": 0,
            "signals_found": 0,
            "trades_executed": 0,
            "stop_losses": 0,
            "take_profits": 0,
            "stocks_scanned": 0,
        }

        # 【V51:统一信号分发器+参数中心+风控看门狗】
        from nodes.market_monitor.signal_dispatcher import (
            SignalDispatcher, redis_channel_handler, feishu_channel_handler, log_channel_handler
        )
        self._signal_dispatcher = SignalDispatcher(scanner=self)
        self._signal_dispatcher.register_channel("log", log_channel_handler)
        self._signal_dispatcher.register_channel("redis", redis_channel_handler)
        # 飞书通道延迟注册(notification_manager可能未初始化)
        self._feishu_registered = False

        # 参数中心
        from nodes.market_monitor.strategy_param_center import param_center
        self._param_center = param_center

        # 风控看门狗
        from nodes.market_monitor.risk_watchdog import RiskWatchdog
        self._risk_watchdog = RiskWatchdog(scanner=self)
        self._risk_watchdog.register_alert_channel(self._signal_dispatcher.dispatch)
        # 【Phase3.1:PositionManager+StrategyScorer+SignalManager+PositionChecker】
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

        # 【V54:分级行情扫描器】
        self._use_tiered = self.config.get("use_tiered_scanner", False)  # 默认关闭, 显式启用
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

        # 风控熔断
        self._circuit_breaker = {
            "daily_start_assets": initial_cash,  # 今日开盘资产
            "daily_max_drawdown": 0.05,          # 单日最大回撤5%
            "consecutive_losses": 0,              # 连续亏损次数
            "consecutive_loss_limit": 3,          # 连续亏损3次熔断
            "trading_paused": False,              # 是否暂停交易
            "pause_reason": "",                  # 暂停原因
            "today_trades": 0,                    # 今日交易次数
            "today_losses": 0,                    # 今日亏损次数
        }

    @property
    def is_running(self):
        return self._is_running

    def get_status(self) -> Dict[str, Any]:
        if self._trade_mode == self.MODE_GM and self._gm_broker:
            gm_acct = self._gm_broker.get_account()
            gm_positions = self._gm_broker.get_positions()
            account_info = {
                "total_assets": gm_acct.get("total_assets", 0),
                "available_cash": gm_acct.get("available_cash", 0),
                "market_value": gm_acct.get("market_value", 0),
                "total_profit": 0,
            }
        else:
            acct = self._broker.get_account()
            account_info = {
                "total_assets": round(acct.total_assets, 2),
                "available_cash": round(acct.available_cash, 2),
                "market_value": round(acct.market_value, 2),
                "total_profit": round(acct.total_profit, 2),
            }
        return {
            "is_running": self._is_running,
            "scan_count": self._scan_count,
            "last_scan_time": self._last_scan_time,
            "active_signals": len(self._active_signals),
            "positions": len(self.get_positions()),
            "stocks_scanned": len(self._realtime_cache),
            "account": account_info,
            "stats": self._stats,
            "account_id": self.account_id,
            "trade_mode": self._trade_mode,
            "filter_pipeline": {
                "position_ratio": self._current_position_ratio,
                "sentiment": self._current_sentiment,
            },
            # 【V51:看门狗+分发器状态】
            "risk_watchdog": self._risk_watchdog.get_status() if hasattr(self, '_risk_watchdog') else {},
            "signal_dispatcher": self._signal_dispatcher.get_stats() if hasattr(self, '_signal_dispatcher') else {},
            "tiered_scanner": self._tiered_scanner.get_status() if self._tiered_scanner else {},
            # 【V59:追踪止损+执行质量】
            "trailing_stops": {k: v for k, v in self._trailing_stops.items() if v.get("activated")},
            "position_risk_levels": dict(self._position_risk_levels),
            "execution_stats": dict(self._execution_stats),
            "smart_check_interval": self._get_smart_check_interval() if self._is_running else None,
            # 【Phase2.2:行情降级状态】
            "quote_degrade_level": self._quote_manager.degrade_level,
            "quote_degrade_desc": self._quote_manager.degrade_desc,
            "sell_logic_mode": self.SELL_LOGIC_MODE,
            # 【Phase4.3:健康度评分】
            "health": self._compute_health_score(),
        }

    def get_signals(self) -> List[Dict]:
        return [self._signal_to_dict(s) for s in self._active_signals]

    def get_positions(self) -> List[Dict]:
        if self._trade_mode == self.MODE_GM and self._gm_broker:
            return self._gm_broker.get_positions()
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
                "ts_code": p.ts_code, "stock_name": p.stock_name,
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
                # 【V59:追踪止损+风险等级】
                "trailing_stop": self._trailing_stops.get(p.ts_code),
                "risk_level": self._position_risk_levels.get(p.ts_code, "normal"),
                "effective_stop_price": self._get_effective_stop_price(p, risk),
            })
        return result

    def get_timeline(self) -> List[Dict]:
        return list(self._timeline)

    async def _save_timeline(self):
        """保存时间线 — 委托给RuntimePersistence【Phase3.1】"""
    async def _save_scan_traces(self, filter_result):
        """保存扫描链路追踪 — 委托给RuntimePersistence【Phase3.1】"""
    async def _load_timeline(self):
        """加载时间线 — 委托给RuntimePersistence【Phase3.1】"""
    async def start(self, trade_date: str = None):
        """启动扫描"""
        if self._is_running:
            return {"success": True, "message": "已在运行中"}

        # 互斥: 检查DailyScheduler是否在运行
        try:
            from nodes.scheduler.daily_scheduler import DailyScheduler
            # 如果scheduler在同一进程中运行, 检查状态
            # (不同进程则无法检测, 需要用户自行保证)
        except ImportError:
            pass

        if not trade_date:
            trade_date = datetime.now().strftime("%Y%m%d")

        # 实盘参数校验
        self._validate_live_params()

        # 【P1-4】从MongoDB恢复策略参数覆盖
        await self._load_strategy_overrides()

        # 盘前准备
        await self.premarket_prepare(trade_date)
        
        # 【Phase3.4:审计日志TTL索引(90天自动过期)】
        try:
            from core.managers import mongo_manager
            if mongo_manager.db:
                await mongo_manager.db["audit_log"].create_index(
                    "timestamp", expireAfterSeconds=7776000  # 90天
                )
        except Exception:
            pass

        self._is_running = True
        self._task = asyncio.create_task(self._scan_loop(trade_date))
        
        # 【Phase1.2:启动风控独立线程】
        import threading
        self._loop = asyncio.get_event_loop()
        self._cache_lock = threading.Lock()
        self._risk_running = True
        self._risk_thread = threading.Thread(
            target=self._risk_loop_sync, daemon=True,
            name="scanner-risk-thread"
        )
        self._risk_thread.start()
        logger.info("[SCANNER] 风控独立线程已启动")
        
        # 【V54:启动分级行情扫描器】
        if self._tiered_scanner:
            await self._tiered_scanner.start(trade_date)
        # 恢复今日时间线
        await self._load_timeline()
        logger.info(f"[SCANNER] 启动, account={self.account_id}, date={trade_date}")
        return {"success": True, "message": "扫描器启动成功"}

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
            positions = self._broker.get_positions()
            for pos in positions:
                if pos.available_qty > 0:
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
            # 清仓后强制保存
            try:
                await self._broker.save_state(force=True)
            except Exception:
                pass
        
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
        
        # 关闭数据源
        if self._data_router:
            try:
                await self._data_router.close_all()
            except Exception as e:
                logger.warning(f"[SCANNER] 数据源关闭失败: {e}")
            self._data_router = None
        logger.info(f"[SCANNER] 已停止 (清仓={sell_all})")
        return {"success": True, "message": f"扫描器已停止" + ("并清仓" if sell_all else "")}

    # ==================== 盘前准备 ====================

    async def premarket_prepare(self, trade_date: str):
        """盘前: 加载全市场代码 + 预加载日级因子"""
        logger.info(f"[SCANNER] 盘前准备 {trade_date}")

        # 【V50:重置每日风控状态——daily_start_assets/熔断计数器】
        if self._broker:
            try:
                acct = self._broker.get_account()
                if acct:
                    self._circuit_breaker["daily_start_assets"] = acct.total_assets
                    self._circuit_breaker["today_trades"] = 0
                    self._circuit_breaker["today_losses"] = 0
                    self._circuit_breaker["trading_paused"] = False
                    self._circuit_breaker["pause_reason"] = ""
                    logger.info(f"[SCANNER] 每日风控重置: start_asset={acct.total_assets:.2f}")
            except Exception as e:
                logger.warning(f"[SCANNER] 每日风控重置失败: {e}")

        # 【V59→Phase1.1优化:追踪止损+风险等级不再无条件清除】
        # _load_positions()→_load_runtime_snapshot()会根据快照日期判断:
        #   同一天重启 → 从快照恢复(保留盘中状态)
        #   新的一天 → 清除(在_load_runtime_snapshot中snap_date!=trade_date时不恢复)
        # 这里只清除执行统计(每次启动都重置)
        self._execution_stats["stop_loss_response_times"] = []
        self._pending_sells.clear()  # 跌停挂起每次启动都清空(重启后行情可能已变)
        logger.info("[SCANNER] 执行统计+跌停挂起已重置(追踪止损/风险等级将在加载持仓时恢复)")

        # 1. 获取全市场代码
        await self._load_stock_list()

        # 2. 预加载前日因子(ma5/rsi/macd/boll/atr等需要历史数据的因子)
        await self._load_daily_factors(trade_date)

        # 3. 加载当前持仓
        await self._load_positions()

        # 4. 竞价预选(仅交易时间9:15-9:30)
        now = datetime.now()
        ct = now.strftime("%H:%M")
        if "09:15" <= ct <= "09:30":
            await self._premarket_auction(trade_date)
        else:
            logger.debug(f"[SCANNER] 非竞价时间({ct}), 跳过竞价预选")

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
        
        logger.info(f"[SCANNER] 持仓: {len(self._broker.get_positions()) if self._broker else 0}个, "
                    f"追踪止损: {len(self._trailing_stops)}个")

    # ==================== Phase1.1: 运行时状态持久化 ====================

    async def _load_runtime_snapshot(self):
        """从MongoDB恢复Scanner运行时状态(追踪止损/风险等级/情绪/熔断器/跌停挂起)
        
        设计原则: Broker是持仓唯一权威, 本快照只存Scanner独有状态。
        恢复后做一致性校验: 清理Broker已无持仓的追踪止损。
        """
        try:
            from core.database.mongo_manager import mongo_manager
            if not mongo_manager or not hasattr(mongo_manager, 'db'):
                logger.debug("[SNAPSHOT] MongoDB不可用,跳过运行时状态恢复")
                return
            
            snapshot = await mongo_manager.db.scanner_runtime_snapshot.find_one(
                {"_id": self.account_id}
            )
            
            if not snapshot:
                logger.info("[SNAPSHOT] 无历史快照,使用空运行时状态")
                return
            
            trade_date = datetime.now().strftime("%Y%m%d")
            snap_date = snapshot.get("trade_date", "")
            
            if snap_date != trade_date:
                # 新的一天 → 不恢复(昨天的状态已过期)
                logger.info(f"[SNAPSHOT] 快照日期={snap_date}≠今日={trade_date}, 不恢复")
                return
            
            # 恢复追踪止损
            self._trailing_stops = snapshot.get("trailing_stops", {})
            
            # 恢复风险等级
            self._position_risk_levels = snapshot.get("position_risk_levels", {})
            
            # 恢复单票风控覆盖
            overrides = snapshot.get("position_risk_overrides", {})
            if overrides:
                self._position_risk_overrides = overrides
            
            # 恢复跌停挂起的卖出
            pending = snapshot.get("pending_sells", {})
            if pending:
                # 将list转回tuple(MongoDB序列化tuple→list)
                self._pending_sells = {k: tuple(v) if isinstance(v, list) else v 
                                       for k, v in pending.items()}
            
            # 一致性校验: 清理Broker已无持仓的追踪止损
            if self._broker:
                broker_codes = {p.ts_code for p in self._broker.get_positions()}
                stale_trailing = [k for k in self._trailing_stops if k not in broker_codes]
                stale_risk = [k for k in self._position_risk_levels if k not in broker_codes]
                for k in stale_trailing:
                    del self._trailing_stops[k]
                for k in stale_risk:
                    del self._position_risk_levels[k]
                if stale_trailing or stale_risk:
                    logger.info(f"[SNAPSHOT] 清理过期状态: 追踪止损{len(stale_trailing)}个, "
                                f"风险等级{len(stale_risk)}个")
            
            logger.info(f"[SNAPSHOT] 运行时状态恢复: 追踪止损{len(self._trailing_stops)}个, "
                        f"风险等级{len(self._position_risk_levels)}个, "
                        f"跌停挂起{len(self._pending_sells)}个")
            
        except Exception as e:
            logger.warning(f"[SNAPSHOT] 运行时状态恢复失败: {e}")

    async def _save_runtime_snapshot(self, force: bool = False):
        """持久化Scanner运行时状态到MongoDB
        
        节流: 5秒内不重复保存(force=True跳过,用于资金变动场景)
        降级: MongoDB不可用时写本地文件
        
        只存Scanner独有状态,不存Broker已有数据(持仓/账户)。
        """
        now = time.time()
        if not force and now - self._last_snapshot_save < 5:
            self._snapshot_dirty = True
            return
        self._last_snapshot_save = now
        
        trade_date = datetime.now().strftime("%Y%m%d")
        
        # 序列化跌停挂起(tuple→list for MongoDB)
        pending_sells_serializable = {}
        for k, v in self._pending_sells.items():
            pending_sells_serializable[k] = list(v) if isinstance(v, tuple) else v
        
        snapshot = {
            "_id": self.account_id,
            "trailing_stops": dict(self._trailing_stops),
            "position_risk_levels": dict(self._position_risk_levels),
            "position_risk_overrides": dict(self._position_risk_overrides),
            "pending_sells": pending_sells_serializable,
            "trade_date": trade_date,
            "updated_at": datetime.now().isoformat(),
        }
        
        try:
            from core.database.mongo_manager import mongo_manager
            if mongo_manager and hasattr(mongo_manager, 'db'):
                await mongo_manager.db.scanner_runtime_snapshot.replace_one(
                    {"_id": self.account_id}, snapshot, upsert=True
                )
                self._snapshot_dirty = False
                logger.debug(f"[SNAPSHOT] 运行时状态已持久化(trailing={len(self._trailing_stops)}, "
                            f"risk={len(self._position_risk_levels)})")
                return
        except Exception as e:
            logger.error(f"[SNAPSHOT] MongoDB写入失败, 降级写本地文件: {e}")
        
        # 降级: 写本地文件(保证重启可恢复)
        try:
            import json
            local_path = f"/tmp/scanner_snapshot_{self.account_id}.json"
            with open(local_path, "w") as f:
                json.dump(snapshot, f, default=str, ensure_ascii=False)
            self._snapshot_dirty = False
            logger.info(f"[SNAPSHOT] 已降级写本地文件: {local_path}")
        except Exception as e2:
            logger.error(f"[SNAPSHOT] 本地文件写入也失败: {e2}")

    async def _premarket_auction(self, trade_date: str):
        """竞价预选(9:15-9:25集合竞价分析)
        
        数据源:
        1. 昨日涨停池 → 连板候选(必盈ztgc, 不占今日额度)
        2. 今日强势股池 → 竞价强势确认(必盈qsgc)
        3. 实时行情 → 竞价涨幅>3%确认(逐只, 仅候选股)
        
        策略:
        - 昨日涨停+今竞价继续强势 → 龙头连板候选
        - 昨日连板≥2 → 强势股继续关注
        """
        try:
            if not self._data_router:
                return
                
            biying = self._data_router._sources.get("biying")
            if not biying:
                return
            
            today = datetime.now().strftime("%Y-%m-%d")
            
            # === 1. 今日强势股池(1次API) ===
            strong_stocks = set()
            try:
                strong_pool = await biying.get_strong_pool(today)
                for item in strong_pool:
                    dm = item.get("dm", "")
                    ts_code = self._short_to_ts_code(dm) if dm else ""
                    if ts_code:
                        strong_stocks.add(ts_code)
                logger.info(f"[AUCTION] 今日强势股池: {len(strong_stocks)}只")
            except Exception as e:
                logger.warning(f"[AUCTION] 强势股池获取失败: {e}")
            
            # === 2. 昨日涨停池(1次API, 非今日额度) ===
            from datetime import timedelta
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            yesterday_limit_ups = await biying.get_limit_up_pool(yesterday)
            
            if not yesterday_limit_ups:
                logger.info("[AUCTION] 昨日无涨停数据")
                return
            
            # === 3. 对昨日涨停+今日强势的交叉验证 ===
            for item in yesterday_limit_ups:
                limit_times = item.get("limit_times", 0) if isinstance(item, dict) else getattr(item, 'limit_times', 0)
                ts_code = item.get("ts_code", "") if isinstance(item, dict) else getattr(item, 'ts_code', "")
                name = item.get("name", "") if isinstance(item, dict) else getattr(item, 'name', "")
                pct = item.get("pct_chg", 0) if isinstance(item, dict) else getattr(item, 'pct_chg', 0)
                fd = item.get("fd_amount", 0) if isinstance(item, dict) else getattr(item, 'fd_amount', 0)
                fd = float(fd or 0)
                open_times = item.get("open_times", 0) if isinstance(item, dict) else getattr(item, 'open_times', 0)
                
                if not ts_code:
                    continue
                
                # 连板≥2 或 今日强势确认
                is_strong = ts_code in strong_stocks
                if limit_times >= 2 or is_strong:
                    existing = {s.ts_code + s.strategy for s in self._active_signals}
                    key = ts_code + "limit_up"
                    if key not in existing:
                        # 获取实时行情确认价格(仅候选股, 1次/只)
                        price = 0.0
                        try:
                            quote = await biying.get_realtime_quote(ts_code)
                            if quote:
                                price = float(quote.get("close", 0) if isinstance(quote, dict) else getattr(quote, 'close', 0))
                        except Exception:
                            pass
                        
                        self._active_signals.append(ScanSignal(
                            ts_code=ts_code,
                            stock_name=name,
                            strategy="limit_up",
                            strategy_name="竞价连板" + ("+强势" if is_strong else ""),
                            signal_type="buy",
                            price=price,  # 实时竞价价格
                            pct_chg=pct,
                            volume_ratio=0,
                            turnover_rate=0,
                            is_limit_up=True,
                            reason=f"昨{limit_times}连板 封单{fd/1000:.0f}万 炸板{open_times}次" + (" 今强势确认" if is_strong else ""),
                        ))
            
            auction_count = len([s for s in self._active_signals if s.strategy_name.startswith("竞价")])
            logger.info(f"[AUCTION] 竞价预选: {auction_count}只候选")
            
        except Exception as e:
            logger.warning(f"[AUCTION] 竞价预选失败: {e}")

    # ==================== 扫描循环 ====================

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
            logger.info(f"[REPLAY] 回放循环启动, 日期={self._replay_date}")
            while self._is_running:
                trade_date = self._replay_date or datetime.now().strftime("%Y%m%d")
                await self.scan_once(trade_date, force=True)
                await asyncio.sleep(self.SCAN_INTERVAL)  # 5分钟间隔
            return

        try:
            while self._is_running:
                now = datetime.now()
                ct = now.strftime("%H:%M")
                h = now.hour

                # === 交易时间(9:30-15:00) ===
                if "09:30" <= ct <= "15:00":
                    settled = False
                    
                    # 【Phase2.2:行情降级自动恢复】每5分钟尝试恢复
                    if self._quote_manager.should_try_recover():
                        try:
                            recovered = await self._quote_manager.try_recover()
                            if recovered:
                                # 恢复成功, 更新scanner本地状态
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
                        last_full_scan = time.time()
                    else:
                        # 【Phase1.2:持仓检查已由风控线程接管,扫描循环只做sleep等待下一次全量扫描】
                        check_interval = self._get_smart_check_interval()
                        await asyncio.sleep(check_interval)
                        continue
                
                # === 盘前(9:00-9:30): 竞价预选 ===
                elif "09:00" <= ct < "09:30":
                    settled = False
                    await self._premarket_auction(trade_date)
                    await asyncio.sleep(120)  # 2分钟
                    
                # === 收盘后(15:05+): 自动结算+报告 ===
                elif ct >= "15:05" and not settled and self._broker:
                    self._broker.daily_settlement(trade_date)
                    settled = True
                    try:
                        await self._broker.save_state()
                    except Exception:
                        pass
                    logger.info("[SCANNER] 收盘自动结算+持久化完成")
                    # 保存timeline到MongoDB
                    try:
                        await self._save_timeline()
                    except Exception:
                        pass
                    # 保存绩效快照(供净值曲线使用)
                    try:
                        await self._save_performance_snapshot(trade_date)
                    except Exception as e:
                        logger.warning(f"[SCANNER] 保存绩效快照失败: {e}")
                    # 推送结算报告到飞书
                    try:
                        await self._push_daily_summary(trade_date)
                    except Exception as e:
                        logger.warning(f"[SCANNER] 推送日报失败: {e}")
                    await asyncio.sleep(60)
                    
                # === 深夜(23:00-8:00): 极低频 ===
                elif h >= 23 or h < 8:
                    await asyncio.sleep(1800)  # 30分钟
                    
                # === 其他非交易时间: 低频 ===
                else:
                    # 【Phase1.2:持仓检查已由风控线程接管】
                    await asyncio.sleep(300)  # 5分钟

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[SCANNER] 异常: {e}", exc_info=True)
            self._is_running = False

    # ==================== Phase1.2: 风控独立线程 ====================

    def _risk_loop_sync(self):
        """风控独立线程(分级节奏，不受asyncio事件循环影响)
        
        设计原则:
        - threading.Thread(真并行, 不受asyncio协作式调度影响)
        - 1秒止损检查(用缓存数据, 零API成本)
        - 30秒完整quick check(东财缓存, 零额度)
        - 职责: 只负责卖出, 不负责买入
        - 跌停不可卖: 挂起pending_sells, 不丢追踪止损
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
                if ct < "09:25" or ct > "15:05":
                    time.sleep(30)  # 非交易时间30秒检查一次
                    continue
                
                # 从共享缓存读取(线程安全, 浅拷贝)
                with self._cache_lock:
                    realtime_data = dict(self._realtime_cache) if self._realtime_cache else {}

                if not realtime_data or not self._broker:
                    time.sleep(1)
                    continue

                # ── 每1秒: 止损检查(用缓存数据, 零成本) ──
                self._check_stop_loss_only(realtime_data)
                self._last_risk_check_ts = time.time()  # 【Phase4.3】

                # ── 每30秒: 完整quick check(东财缓存, 零额度) ──
                if tick % 30 == 0 and self._loop and not self._loop.is_closed():
                    try:
                        trade_date = datetime.now().strftime("%Y%m%d")
                        future = asyncio.run_coroutine_threadsafe(
                            self._check_positions_quick(trade_date),
                            self._loop
                        )
                        future.result(timeout=10)
                    except Exception as e:
                        logger.debug(f"[RISK_THREAD] quick check异常: {e}")

            except Exception as e:
                logger.error(f"[RISK_THREAD] 风控线程异常: {e}")
            time.sleep(1)  # 真sleep,不受asyncio影响
        
        logger.info("[RISK_THREAD] 风控线程已退出")

    def _check_stop_loss_only(self, realtime_data: Dict):
        """1秒级止损检查 — 委托给PositionManager【Phase3.1】
        
        跌停挂起+卖出执行仍在此处(PositionManager只做检查,不执行)
        """
        if not self._broker:
            return
        
        positions = self._broker.get_positions()
        if not positions:
            return
        
        # 委托检查
        if self._position_manager:
            to_sell = self._position_manager.check_stop_loss_only(realtime_data)
        else:
            to_sell = []
        
        # 跌停挂起+执行卖出(PositionManager不直接执行交易)
        if to_sell:
            for pos, reason, price, risk in to_sell:
                # 跌停不可卖检查
                if self._is_limit_down(pos.ts_code):
                    self._pending_sells[pos.ts_code] = (reason, price)
                    logger.warning(f"[RISK_THREAD] 跌停不可卖: {pos.ts_code}, {reason}挂起")
                    continue
                
                # 通过asyncio提交到主循环执行卖出
                if self._loop and not self._loop.is_closed():
                    try:
                        sell_qty = pos.available_qty
                        future = asyncio.run_coroutine_threadsafe(
                            self._execute_risk_sell(pos, reason, price, sell_qty),
                            self._loop
                        )
                        future.result(timeout=5)
                    except Exception as e:
                        logger.error(f"[RISK_THREAD] 卖出执行失败: {pos.ts_code} {e}")

    async def _execute_risk_sell(self, pos, reason: str, price: float, quantity: int):
        """风控线程触发的卖出执行(在asyncio主循环中运行)"""
        if pos.available_qty <= 0:
            return
        
        # 保存卖出前关键值
        sell_profit_pct = pos.profit_pct
        sell_profit_amount = (pos.current_price - pos.avg_cost) * quantity
        
        self._broker.update_realtime(pos.ts_code, pos.current_price)
        ok, msg, order = self._broker.place_order(
            ts_code=pos.ts_code,
            stock_name=pos.stock_name,
            side="sell",
            quantity=quantity,
            price=price,
            order_type="market",
            strategy=pos.strategy,
            reason=reason,
        )
        if ok:
            self._timeline.append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "action": "sell",
                "ts_code": pos.ts_code,
                "stock_name": pos.stock_name,
                "strategy": pos.strategy,
                "shares": quantity,
                "price": order.filled_price,
                "reason": reason,
                "profit_pct": round(sell_profit_pct, 2),
                "profit_amount": round(sell_profit_amount, 2),
            })
            self._stats["stop_losses"] += 1
            # 清理追踪止损
            self._trailing_stops.pop(pos.ts_code, None)
            self._position_risk_levels.pop(pos.ts_code, None)
            await self._publish_scanner_event("timeline", {"item": self._timeline[-1]})
            logger.info(f"[RISK_THREAD] {reason}: {pos.ts_code} {quantity}股@{order.filled_price:.2f}")
            # 持久化
            try:
                await self._broker.save_state(force=True)
            except Exception:
                pass
            await self._save_runtime_snapshot(force=True)

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
        merged_df = self._merge_factors(realtime_data)

        # Step 3: 策略筛选
        new_signals = await self._apply_strategies(merged_df, trade_date)

        # Step 3.5: 9层筛选管道(强制空仓/情绪/竞价/排序/仓位)
        new_signals = await self._apply_filter_pipeline(
            new_signals, trade_date, realtime_data
        )

        # Step 3.6: 异动检测(从realtime_data检测, 不消耗额外API)
        # 【安全修复】异动信号也必须经过9层筛选管道(特别是强制空仓检查)
        anomaly_signals = await self._detect_anomalies(realtime_data)
        if anomaly_signals:
            anomaly_signals = await self._apply_filter_pipeline(
                anomaly_signals, trade_date, realtime_data
            )
        new_signals.extend(anomaly_signals)

        # Step 4: 增量更新信号
        await self._update_signals(new_signals, scan_time)

        # Step 5: 持仓检查(止损止盈)
        await self._check_positions(realtime_data, trade_date)

        # Step 6: 更新broker实时价格(用于持仓估值和涨跌停判断)
        for ts_code, rt in realtime_data.items():
            name = rt.get("name", "")
            is_st = bool(name and ("ST" in name or "*ST" in name))
            self._broker.update_realtime(
                ts_code=ts_code,
                price=rt.get("price", 0),
                pre_close=rt.get("pre_close", 0),
                is_st=is_st,
            )

        elapsed = time.time() - t0
        self._last_scan_time = scan_time
        self._stats["scans"] += 1
        self._stats["stocks_scanned"] = len(realtime_data)

        # 【V51:看门狗心跳】
        if hasattr(self, '_risk_watchdog'):
            self._risk_watchdog.update_heartbeat()
        self._last_scan_duration_ms = elapsed * 1000  # 看门狗用
        self._last_scan_ts = time.time()  # 【Phase4.3:健康度用】

        logger.info(f"[SCAN #{self._scan_count}] 完成: "
                     f"{len(realtime_data)}只 | {len(self._active_signals)}信号 | "
                     f"{elapsed:.1f}秒")
        
        # 持久化到MongoDB
        try:
            saved = await self._broker.save_state()
            logger.info(f"[SCAN] save_state={saved} positions={len(self._broker.positions)} orders={len(self._broker.orders)}")
            # 保存时间线到MongoDB
            await self._save_timeline()
            # 【Phase1.1】扫描后保存运行时状态(节流5秒)
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
        if self._cache_lock and not self._quote_manager._cache_lock:
            self._quote_manager.set_cache_lock(self._cache_lock)
        
        realtime = await self._quote_manager.fetch_realtime_batch(force=force)
        
        # 同步缓存引用(Scanner其他方法可能直接读self._realtime_cache)
        self._realtime_cache = self._quote_manager._realtime_cache
        self._prev_realtime_cache = self._quote_manager._prev_realtime_cache
        self._data_router = self._quote_manager._data_router
        self._quote_degrade_level = self._quote_manager._quote_degrade_level
        
        return realtime

    def _short_to_ts_code(self, short_code: str) -> str:
        """6位代码→ts_code — 委托给QuoteManager【Phase3.1】"""
        return QuoteManager.short_to_ts_code(short_code)

    # ==================== 因子合并 ====================

    def _merge_factors(self, realtime_data: Dict[str, Dict]) -> pd.DataFrame:
        """合并日级因子+实时数据 — 委托给StrategyScorer【Phase3.1】"""
        if self._strategy_scorer:
            return self._strategy_scorer.merge_factors(realtime_data)
        # fallback: 不再保留旧实现(已完整迁移到StrategyScorer)
    def _get_effective_strategy_config(self, strategy_key: str) -> Dict:
        """获取策略有效配置 — 委托给StrategyScorer【Phase3.1】"""
        if self._strategy_scorer:
            return self._strategy_scorer.get_effective_strategy_config(strategy_key)
        # fallback: 不再保留旧实现(已完整迁移到StrategyScorer)
    def _get_strategy_risk(self, strategy_key: str) -> Dict:
        """获取策略风控参数 — 委托给StrategyScorer【Phase3.1】"""
        if self._strategy_scorer:
            return self._strategy_scorer.get_strategy_risk(strategy_key)
        # fallback: 不再保留旧实现(已完整迁移到StrategyScorer)
    async def _apply_strategies(self, merged_df: pd.DataFrame, trade_date: str) -> List[ScanSignal]:
        """策略筛选 — 委托给StrategyScorer【Phase3.1】"""
        if self._strategy_scorer:
            return await self._strategy_scorer.apply_strategies(merged_df, trade_date)
        return []
    async def _apply_filter_pipeline(
        self, signals: List[ScanSignal], trade_date: str, realtime_data: Dict
    ) -> List[ScanSignal]:
        """9层筛选管道: 强制空仓/情绪/竞价/排序/仓位"""
        if not signals:
            return signals

        # 转换为管道输入格式
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
            logger.warning(f"[FILTER] ⚠️ 强制空仓: {result.force_empty_reason}")
            if self._broker:
                for p in self._broker.get_positions():
                    self._broker.sell(
                        ts_code=p.ts_code,
                        shares=p.total_qty,
                        price=p.current_price,
                        reason=f"强制空仓: {result.force_empty_reason}",
                    )
            return []

        # 转回ScanSignal，注入筛选决策详情+逐层trace
        candidate_map = {c["ts_code"]: c for c in result.candidates}
        filtered_signals = []
        for s in signals:
            if s.ts_code in candidate_map:
                # 【实盘审查增强】注入9层筛选决策详情
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
                # 【调试增强】逐层trace: 合并9层筛选结果到layer_trace
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
                # 被过滤掉的信号: 记录被哪层过滤
                s.signal_status = "filtered"
                s.layer_trace["filter_result"] = {
                    "filtered_out": True,
                    "reason": "9层筛选管道过滤",
                    "layer_details": result.layer_details,
                }

        # 存储仓位系数和情绪信息(供execute_signals使用)
        old_phase = self._current_sentiment.get("period", "")
        self._current_position_ratio = result.position_ratio
        self._current_sentiment = self._filter_pipeline.get_sentiment_info()
        new_phase = self._current_sentiment.get("period", "")

        logger.info(f"[FILTER] 筛选完成: {len(signals)}→{len(filtered_signals)}个信号, "
                     f"仓位系数={result.position_ratio:.0%}")
        
        # 【Phase2.4:情绪phase变化→动态调仓】
        if old_phase and old_phase != new_phase:
            await self._handle_emotion_phase_change(old_phase, new_phase)

        return filtered_signals

    # ==================== 信号管理 ====================

    async def _update_signals(self, new_signals: List[ScanSignal], scan_time: str):
        """增量更新信号+过期清理 — 委托给SignalManager【Phase3.1】"""
        if self._signal_manager:
            return await self._signal_manager.update_signals(new_signals, scan_time)
        # fallback: 不再保留旧实现(已完整迁移到SignalManager)
    async def _push_signals(self, signals: List[ScanSignal]):
        """推送信号 — 委托给SignalManager【Phase3.1】"""
        if self._signal_manager:
            return await self._signal_manager._push_signals(signals)
        # fallback: 不再保留旧实现(已完整迁移到SignalManager)
    def _add_timeline_log(self, action, ts_code, stock_name, strategy, reason, sig):
        """添加执行日志 — 委托给SignalManager【Phase3.1】"""
        if self._signal_manager:
            return self._signal_manager._add_timeline_log(action, ts_code, stock_name, strategy, reason, sig)
        # fallback: 不再保留旧实现(已完整迁移到SignalManager)
    async def _write_audit_log(self, action: str, ts_code: str, stock_name: str, 
                                strategy: str, reason: str):
        """写入审计日志 — 委托给SignalManager【Phase3.1】"""
        if self._signal_manager:
            return await self._signal_manager._write_audit_log(action, ts_code, stock_name, strategy, reason)

    async def _execute_signals(self, signals: List[ScanSignal]):
        """执行信号 — 委托给SignalManager【Phase3.1】"""
        if self._signal_manager:
            return await self._signal_manager.execute_signals(signals)
        # fallback: 原逻辑已完整迁移到SignalManager

    # ==================== 公共止损止盈方法 ====================

    def _calc_stop_loss_price(self, pos_or_cost, risk: Dict) -> float:
        """统一止损价计算 — 委托给PositionManager【Phase3.1】"""
        if self._position_manager:
            return self._position_manager.calc_stop_loss_price(pos_or_cost, risk)
        # fallback
        cost = pos_or_cost.avg_cost if hasattr(pos_or_cost, 'avg_cost') else pos_or_cost
        sl_pct = risk.get("stop_loss_pct", 0.03)
        if sl_pct > 1: sl_pct = sl_pct / 100
        return round(cost * (1 - sl_pct), 2)

    def _calc_take_profit_price(self, pos_or_cost, risk: Dict) -> float:
        """统一止盈价计算 — 委托给PositionManager【Phase3.1】"""
        if self._position_manager:
            return self._position_manager.calc_take_profit_price(pos_or_cost, risk)
        # fallback
        cost = pos_or_cost.avg_cost if hasattr(pos_or_cost, 'avg_cost') else pos_or_cost
        tp_pct = risk.get("take_profit_pct", 0.07)
        if tp_pct > 1: tp_pct = tp_pct / 100
        return round(cost * (1 + tp_pct), 2)

    def _check_stop_loss_take_profit(self, positions, realtime_data: Dict) -> List[Tuple]:
        """止损止盈检查 — 委托给PositionManager【Phase3.1】"""
        # 更新追踪止损状态(仍在Scanner,因为状态属于Scanner)
        self._update_trailing_stops(positions, realtime_data)
        
        if self._position_manager:
            return self._position_manager.check_stop_loss_take_profit(positions, realtime_data)
        return []  # fallback(不应到达)

    # ==================== 持仓检查 ====================

    async def _check_positions(self, realtime_data: Dict[str, Dict], trade_date: str):
        """止损止盈+超时强卖检查 — 委托给PositionChecker【Phase3.1】"""
        if self._position_checker:
            return await self._position_checker.check_positions(realtime_data, trade_date)

    async def _check_positions_quick(self, trade_date: str):
        """持仓快速检查 — 委托给PositionChecker【Phase3.1】"""
        if self._position_checker:
            return await self._position_checker.check_positions_quick(trade_date)
    async def _handle_emotion_phase_change(self, old_phase: str, new_phase: str):
        """情绪phase变化时的动态调仓
        
        规则: phase降级时减仓/清仓低利润, 升级时不做操作(自然加仓)
        分批执行: max_per_round=2, 间隔0.5秒(避免冲击)
        """
        key = (old_phase, new_phase)
        rule = self.EMOTION_DOWNGRADE_RULES.get(key)
        if not rule:
            # phase升级(如chaos→rising)或不支持的组合 → 不做操作
            logger.info(f"[EMOTION] phase变化 {old_phase}→{new_phase}, 无需调仓")
            return
        
        logger.warning(f"[EMOTION] phase降级 {old_phase}→{new_phase}: {rule['desc']}")
        
        if not self._broker:
            return
        
        positions = self._broker.get_positions()
        if not positions:
            return
        
        to_sell = []
        
        if rule["action"] == "reduce":
            # 按比例减仓(低利润优先)
            keep_ratio = rule["keep_ratio"]
            sorted_pos = sorted(positions, key=lambda p: p.profit_pct)  # 利润从低到高
            total_count = len(sorted_pos)
            target_count = max(1, int(total_count * keep_ratio))
            sell_count = total_count - target_count
            
            for pos in sorted_pos[:sell_count]:
                if pos.available_qty <= 0:
                    continue
                if self._is_limit_down(pos.ts_code):
                    self._pending_sells[pos.ts_code] = (f"情绪降级({old_phase}→{new_phase})", pos.current_price)
                    continue
                to_sell.append((pos, f"情绪降级({rule['desc']})", pos.current_price, 
                               self._get_strategy_risk(pos.strategy)))
        
        elif rule["action"] == "clear_low_profit":
            # 清仓低利润持仓
            min_profit = rule.get("min_profit", 0.03)
            for pos in positions:
                if pos.available_qty <= 0:
                    continue
                if pos.profit_pct < min_profit * 100:  # profit_pct是百分比
                    if self._is_limit_down(pos.ts_code):
                        self._pending_sells[pos.ts_code] = (f"情绪清仓({old_phase}→{new_phase})", pos.current_price)
                        continue
                    to_sell.append((pos, f"情绪清仓({rule['desc']}, 利润{pos.profit_pct:.1f}%<{min_profit*100:.0f}%)", 
                                   pos.current_price, self._get_strategy_risk(pos.strategy)))
        
        if not to_sell:
            logger.info(f"[EMOTION] phase降级无需调仓(无符合条件持仓)")
            return
        
        # 分批执行(max_per_round=2, 间隔0.5秒)
        batch_size = 2
        for i in range(0, len(to_sell), batch_size):
            batch = to_sell[i:i+batch_size]
            await self._execute_sell_list(batch, self._trade_date or datetime.now().strftime("%Y%m%d"))
            if i + batch_size < len(to_sell):
                await asyncio.sleep(0.5)
        
        logger.warning(f"[EMOTION] 调仓完成: 卖出{len(to_sell)}只, {rule['desc']}")
        
        # 推送事件
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

    def _compute_health_score(self) -> Dict[str, Any]:
        """Scanner健康度评分(绿/黄/红)
        
        维度:
        - scan_lag: 全量扫描延迟(上次到现在)
        - risk_check_lag: 风控检查延迟
        - quote_staleness: 行情数据陈旧度
        - warnings: 告警列表
        """
        now = time.time()
        warnings = []
        
        # 1. 扫描延迟
        scan_lag = (now - self._last_scan_ts) if self._last_scan_ts > 0 else 999
        if scan_lag > 600:  # 10分钟没扫描
            warnings.append(f"扫描延迟{scan_lag:.0f}秒")
        
        # 2. 风控检查延迟
        risk_lag = (now - self._last_risk_check_ts) if self._last_risk_check_ts > 0 else 999
        if risk_lag > 10:  # 10秒没做风控检查
            warnings.append(f"风控延迟{risk_lag:.0f}秒")
        
        # 3. 行情陈旧度
        quote_staleness = self._quote_manager.get_staleness() if self._quote_manager else 999.0
        if quote_staleness > 60:  # 行情超过1分钟没更新
            warnings.append(f"行情陈旧{quote_staleness:.0f}秒")
        
        # 4. 行情降级
        if self._quote_manager and self._quote_manager.degrade_level > 0:
            warnings.append(f"行情降级level={self._quote_manager.degrade_level}")
        
        # 5. 跌停挂起
        if self._pending_sells:
            warnings.append(f"跌停挂起{len(self._pending_sells)}只")
        
        # 6. 熔断器
        if hasattr(self, '_circuit_breaker') and self._circuit_breaker.get('is_triggered'):
            warnings.append("熔断器已触发")
        
        # 健康判定
        is_healthy = (
            scan_lag < 360 and      # 6分钟内有扫描
            risk_lag < 5 and         # 5秒内有风控检查
            quote_staleness < 30 and # 行情30秒内更新
            len(warnings) == 0
        )
        is_warning = not is_healthy and (
            scan_lag < 600 and      # 10分钟内
            risk_lag < 30 and       # 30秒内
            quote_staleness < 120   # 2分钟内
        )
        
        if is_healthy:
            status = "green"
        elif is_warning:
            status = "yellow"
        else:
            status = "red"
        
        return {
            "status": status,          # green/yellow/red
            "is_healthy": is_healthy,
            "scan_lag_seconds": round(scan_lag, 1),
            "risk_check_lag_seconds": round(risk_lag, 1),
            "quote_staleness_seconds": round(quote_staleness, 1),
            "warnings": warnings,
        }

    # ==================== V59:智能持仓检查频率 ====================

    def _get_effective_stop_price(self, pos, risk: Dict) -> Optional[float]:
        """获取有效止损价 — 委托给PositionManager【Phase3.1】"""
        if self._position_manager:
            return self._position_manager.get_effective_stop_price(pos, risk)
        return None


    def _get_smart_check_interval(self) -> int:
        """智能持仓检查间隔
        
        根据持仓风险等级动态调整检查频率:
        - 全部normal: 30秒(省资源)
        - 有warning(距止损<1%): 10秒
        - 有critical(已触及止损区): 5秒
        
        对标真实量化: 事件驱动做不到(无WebSocket行情), 但分级轮询是实用方案
        """
        if not self._broker:
            return self.POSITION_CHECK_INTERVAL

        positions = self._broker.get_positions()
        if not positions:
            return self.POSITION_CHECK_INTERVAL

        max_risk = "normal"
        for pos in positions:
            risk = self._get_strategy_risk(pos.strategy)
            pos_overrides = getattr(self, '_position_risk_overrides', {}).get(pos.ts_code, {})
            if 'stop_loss_pct' in pos_overrides:
                risk['stop_loss_pct'] = pos_overrides['stop_loss_pct']
            stop_loss_pct = -risk.get("stop_loss_pct", 0.03) * 100
            
            # 追踪止损
            trailing = self._trailing_stops.get(pos.ts_code)
            effective_sl = stop_loss_pct
            if trailing and trailing.get("activated"):
                trailing_sl = -(trailing.get("trailing_stop_pct", 0.03)) * 100
                # 追踪止损可能更紧
                effective_sl = max(stop_loss_pct, trailing_sl)  # 更接近0的值(如-2% vs -3%, 取-2%)

            # 计算距止损空间
            distance_to_sl = pos.profit_pct - effective_sl  # 如: 当前-1%, 止损-3%, 距离=2%
            
            if distance_to_sl <= 0:
                # 已触及止损区
                level = "critical"
            elif distance_to_sl <= 1.0:
                # 距止损<1%
                level = "warning"
            else:
                level = "normal"
            
            self._position_risk_levels[pos.ts_code] = level
            
            if level == "critical":
                max_risk = "critical"
            elif level == "warning" and max_risk != "critical":
                max_risk = "warning"

        interval_map = {
            "normal": self.POSITION_CHECK_INTERVAL,
            "warning": self.POSITION_CHECK_FAST,
            "critical": self.POSITION_CHECK_CRITICAL,
        }
        return interval_map.get(max_risk, self.POSITION_CHECK_INTERVAL)

    def _update_trailing_stops(self, positions, realtime_data: Dict):
        """更新追踪止损状态 — 委托给PositionManager【Phase3.1】"""
        if self._position_manager:
            self._position_manager.update_trailing_stops(positions, realtime_data)
            return
        # fallback: 不更新

    def _get_open_price(self, ts_code: str) -> Optional[float]:
        """获取当日开盘价(从实时缓存)"""
        cached = (self._realtime_cache or {}).get(ts_code, {})
        open_price = cached.get("open", 0)
        if open_price and open_price > 0:
            return open_price
        # 回退: 东方财富缓存
        if self._data_router:
            eastmoney = self._data_router._sources.get("eastmoney")
            if eastmoney and hasattr(eastmoney, '_cache'):
                snap = eastmoney._cache.get(ts_code, {})
                return snap.get("open", 0) or None
        return None

    def _is_limit_down(self, ts_code: str) -> bool:
        """判断是否跌停 — 委托给PositionChecker【Phase3.1】"""
        if self._position_checker:
            return self._position_checker._is_limit_down(ts_code)
    def _validate_live_params(self):
        """实盘参数校验
        
        检查回测参数是否合理, 避免用不切实际的参数跑实盘。
        """
        warnings = []
        
        # 1. 滑点检查
        if self._broker and hasattr(self._broker, 'SLIPPAGE_RATE'):
            if self._broker.SLIPPAGE_RATE < 0.001:
                warnings.append(f"滑点{self._broker.SLIPPAGE_RATE*100:.2f}%过低, 实盘建议≥0.1%")
        
        # 2. 仓位上限
        if self._broker and hasattr(self._broker, 'MAX_TOTAL_RATIO'):
            if self._broker.MAX_TOTAL_RATIO > 0.8:
                warnings.append(f"总仓位上限{self._broker.MAX_TOTAL_RATIO*100:.0f}%过高, 实盘建议≤70%")
        
        # 3. 止损检查
        risk = self._get_strategy_risk("default")
        if risk.get("stop_loss_pct", 0.03) < 0.02:
            warnings.append("止损<2%过紧, 实盘容易被震出")
        
        if warnings:
            for w in warnings:
                logger.warning(f"[VALIDATE] ⚠️ {w}")

    def update_strategy_config(self, strategy_key: str, updates: Dict[str, Any]):
        """策略参数热更新(无需重启scanner) + 持久化到MongoDB
        
        updates格式: {"params": {...}, "riskParams": {...}, "enabled": True}
        下次扫描时自动生效(因为_get_effective_strategy_config读取strategy_overrides)
        重启后从MongoDB恢复(不再丢失)
        """
        if "strategy_overrides" not in self.config:
            self.config["strategy_overrides"] = {}
        
        existing = self.config["strategy_overrides"].get(strategy_key, {})
        
        if "params" in updates:
            if "params" not in existing:
                existing["params"] = {}
            existing["params"].update(updates["params"])
        
        if "riskParams" in updates:
            if "riskParams" not in existing:
                existing["riskParams"] = {}
            existing["riskParams"].update(updates["riskParams"])
        
        if "enabled" in updates:
            existing["enabled"] = updates["enabled"]
        
        self.config["strategy_overrides"][strategy_key] = existing
        logger.info(f"[SCANNER] 策略参数热更新: {strategy_key} → {existing}")
        
        # 【P1-4】持久化到MongoDB
        try:
            asyncio.ensure_future(self._persist_strategy_overrides())
        except Exception:
            logger.debug("[SCANNER] 策略参数持久化异步任务创建失败")
    
    async def _persist_strategy_overrides(self):
        """将strategy_overrides持久化到MongoDB"""
        try:
            from core.managers import mongo_manager
            if mongo_manager.db is None:
                return
            overrides = self.config.get("strategy_overrides", {})
            await mongo_manager.db["scanner_config"].update_one(
                {"_id": "strategy_overrides"},
                {"$set": {"data": overrides, "updated_at": datetime.now().isoformat()}},
                upsert=True,
            )
            logger.info(f"[SCANNER] 策略参数已持久化到MongoDB")
        except Exception as e:
            logger.warning(f"[SCANNER] 策略参数持久化失败(非关键): {e}")
    
    async def _load_strategy_overrides(self):
        """从MongoDB恢复strategy_overrides"""
        try:
            from core.managers import mongo_manager
            if mongo_manager.db is None:
                return
            doc = await mongo_manager.db["scanner_config"].find_one({"_id": "strategy_overrides"})
            if doc and "data" in doc:
                if "strategy_overrides" not in self.config:
                    self.config["strategy_overrides"] = {}
                self.config["strategy_overrides"].update(doc["data"])
                logger.info(f"[SCANNER] 从MongoDB恢复策略参数: {len(doc['data'])}个策略")
        except Exception as e:
            logger.warning(f"[SCANNER] 策略参数恢复失败(非关键): {e}")

    # ==================== 盘中异动监控 ====================

    async def _detect_anomalies(self, realtime_data: Dict[str, Dict]) -> List[ScanSignal]:
        """盘中异动检测
        
        检测类型:
        1. 急速拉升: 5分钟内涨幅>3%
        2. 跌停打开: 跌停后打开(撬板机会)
        3. 量比突变: 量比>5(资金异动)
        4. 封板松动: 涨停后炸板(炸板股池)
        
        不消耗额外必盈额度, 从已有的realtime_data里检测
        """
        signals = []
        
        for ts_code, rt in realtime_data.items():
            key = ts_code + "|anomaly"
            if key in {s.ts_code + "|" + s.strategy for s in self._active_signals}:
                continue  # 已有信号, 跳过
                
            pct_chg = rt.get("pct_chg", 0)
            is_limit_up = rt.get("is_limit_up", False)
            is_limit_down = rt.get("is_limit_down", False)
            is_broken = rt.get("is_broken_board", False)
            open_times = rt.get("open_times", 0)
            limit_times = rt.get("limit_times", 0)
            name = rt.get("name", "")
            price = rt.get("price", 0)
            turnover = rt.get("turnover_rate", 0)
            fd_amount = rt.get("fd_amount", 0)
            
            # === 1. 跌停撬板(从必盈跌停/炸板池检测) ===
            if is_broken and not is_limit_down:
                # 炸板股: 涨停后打开 → 可能是炸板回封或龙头分歧
                if pct_chg > 5 and open_times <= 2:
                    signals.append(ScanSignal(
                        ts_code=ts_code, stock_name=name,
                        strategy="anomaly_broken", strategy_name="涨停炸板",
                        signal_type="buy", price=price,
                        pct_chg=pct_chg, volume_ratio=0,
                        turnover_rate=turnover,
                        is_limit_up=False,
                        reason=f"涨停炸板2次内 涨{pct_chg:.1f}%",
                    ))
                    continue
            
            # === 2. 量比突变(从涨停池里的换手率/封单判断) ===
            if is_limit_up:
                # 涨停股: 封单缩小+换手率高 → 可能开板
                if turnover > 10 and fd_amount < 50000 and limit_times >= 2:
                    # 高换手+封单小+连板 → 可能开板, 观望
                    pass
                elif fd_amount > 100000 and open_times == 0:
                    # 大封单+无炸板 → 强势涨停, 次日溢价
                    signals.append(ScanSignal(
                        ts_code=ts_code, stock_name=name,
                        strategy="anomaly_strong", strategy_name="强势涨停",
                        signal_type="buy", price=price,
                        pct_chg=pct_chg, volume_ratio=0,
                        turnover_rate=turnover, is_limit_up=True,
                        reason=f"连板{limit_times} 封单{fd_amount/1000:.0f}万 无炸板",
                    ))
                    continue
            
            # === 3. 急速拉升(5分钟内涨幅>3%) ===
            # 对比上轮扫描缓存的价格变化(真正的5分钟涨幅)
            prev_cached = self._prev_realtime_cache.get(ts_code, {})
            prev_price = prev_cached.get("price", 0)
            if prev_price > 0 and price > 0:
                price_change_pct = (price - prev_price) / prev_price * 100
                if price_change_pct > 3 and not is_limit_up:
                    signals.append(ScanSignal(
                        ts_code=ts_code, stock_name=name,
                        strategy="anomaly_surge", strategy_name="急速拉升",
                        signal_type="buy", price=price,
                        pct_chg=pct_chg, volume_ratio=0,
                        turnover_rate=turnover, is_limit_up=False,
                        reason=f"5分钟涨{price_change_pct:.1f}%",
                    ))
                    continue
        
        if signals:
            logger.info(f"[ANOMALY] 异动检测: {len(signals)}只")
        
        return signals

    # ==================== 仓位管理 ====================

    def _calc_would_buy_shares(self, signal: ScanSignal) -> int:
        """计算dry_run模式下会买入多少股(不实际下单)"""
        if not self._broker or signal.price <= 0:
            return 0
        acct = self._broker.get_account()
        position_ratio = self._calc_position_ratio(signal)
        max_amount = acct.available_cash * position_ratio
        lot = 200 if signal.ts_code.startswith('688') else 100
        shares = int(max_amount / signal.price / lot) * lot
        return shares

    def _calc_position_ratio(self, signal: ScanSignal) -> float:
        """根据信号特征计算仓位比例
        
        逻辑:
        - 涨停+连板≥2 → 重仓40% (确定性高)
        - 涨停+首板 → 中仓25% (有确定性)
        - 半路追涨 → 中仓25% (主力策略)
        - 跌停翘板 → 轻仓15% (高风险)
        - 龙头低吸 → 轻仓15% (高风险)
        
        总仓位限制: 单票≤总资产15%, 总仓位≤70%
        """
        strategy = signal.strategy or ""
        
        # 策略级仓位
        if "涨停" in strategy or "limit_up" in strategy:
            # 连板股重仓
            if signal.is_limit_up and getattr(signal, 'limit_times', 0) >= 2:
                ratio = 0.40
            else:
                ratio = 0.25
        elif "半路" in strategy or "mid_chase" in strategy:
            ratio = 0.25
        elif "跌停" in strategy or "limit_down" in strategy:
            ratio = 0.15
        elif "龙头" in strategy or "leader" in strategy:
            ratio = 0.15
        elif "anomaly" in strategy:
            ratio = 0.10  # 异动信号: 观察仓, 轻仓试探
        else:
            ratio = 0.20  # 默认
        
        # 动态调整: 持仓多时减仓
        if self._broker:
            acct = self._broker.get_account()
            if acct.total_assets > 0:
                current_ratio = acct.market_value / acct.total_assets
                if current_ratio > 0.5:
                    ratio *= 0.7  # 已半仓, 减量
                if current_ratio > 0.65:
                    ratio *= 0.5  # 接近满仓, 减半
        
        # 情绪仓位系数: 9层筛选L3情绪周期/L2特殊时期的仓位调整
        pipeline_ratio = getattr(self, '_current_position_ratio', None)
        if pipeline_ratio is not None and pipeline_ratio < 1.0:
            ratio *= pipeline_ratio  # 情绪低迷/特殊时期降仓
        
        return ratio

    # ==================== 风控熔断 ====================

    async def _check_circuit_breaker(self) -> bool:
        """风控熔断检查
        
        规则:
        1. 单日回撤>5% → 暂停所有交易
        2. 连续亏损3次 → 暂停买入(可卖出止损)
        3. 手动暂停 → 尊重人工干预
        
        Returns: True=允许交易, False=应暂停
        """
        cb = self._circuit_breaker
        
        if cb["trading_paused"]:
            logger.debug(f"[CIRCUIT] 交易已暂停: {cb['pause_reason']}")
            return False
        
        # 单日回撤检查
        if self._broker:
            acct = self._broker.get_account()
            if cb["daily_start_assets"] > 0:
                drawdown = (cb["daily_start_assets"] - acct.total_assets) / cb["daily_start_assets"]
                if drawdown >= cb["daily_max_drawdown"]:
                    cb["trading_paused"] = True
                    cb["pause_reason"] = f"单日回撤{drawdown*100:.1f}%超限({cb['daily_max_drawdown']*100:.0f}%)"
                    logger.warning(f"[CIRCUIT] ⚠️ 熔断触发: {cb['pause_reason']}")
                    # 主动推送熔断通知(使用标准_publish_scanner_event)
                    try:
                        await self._publish_scanner_event("status", {
                            "circuit_breaker": True,
                            "message": cb["pause_reason"],
                            "trading_paused": True,
                        })
                    except Exception:
                        pass
                    return False
        
        # 连续亏损检查(只限制买入, 不限制卖出)
        if cb["consecutive_losses"] >= cb["consecutive_loss_limit"]:
            logger.info(f"[CIRCUIT] 连续亏损{cb['consecutive_losses']}次, 暂停买入")
            return False
        
        return True

    def _record_trade_result(self, profit_pct: float):
        """记录交易结果(用于连续亏损统计)"""
        cb = self._circuit_breaker
        cb["today_trades"] += 1
        
        if profit_pct < 0:
            cb["consecutive_losses"] += 1
            cb["today_losses"] += 1
        else:
            cb["consecutive_losses"] = 0  # 盈利重置

    def reset_circuit_breaker(self):
        """重置熔断(手动恢复)"""
        self._circuit_breaker["trading_paused"] = False
        self._circuit_breaker["pause_reason"] = ""
        self._circuit_breaker["consecutive_losses"] = 0
        logger.info("[CIRCUIT] 熔断已重置")

    # ==================== 工具方法 ====================

    @staticmethod
    def _safe_round(v, digits=2):
        """安全round — 委托给ScannerUtils【Phase3.1】"""
        from nodes.market_monitor.scanner_utils import ScannerUtils
        return ScannerUtils.safe_round(v, digits)

    async def _publish_scanner_event(self, event_type: str, data: Dict):
        """推送scanner事件 — 委托给ScannerUtils【Phase3.1】"""
    def _position_to_dict(self, p) -> Dict:
        """Position对象转dict — 委托给ScannerUtils【Phase3.1】"""
    def _signal_to_dict(self, s: ScanSignal) -> Dict:
        """ScanSignal对象转dict — 委托给ScannerUtils【Phase3.1】"""
    def _extract_key_factors(self, s: ScanSignal) -> Dict[str, Any]:
        """提取关键因子 — 委托给ScannerUtils【Phase3.1】"""
    def generate_summary_report(self) -> Dict[str, Any]:
        """生成交易摘要报告 — 委托给ScannerUtils【Phase3.1】"""
    async def _save_performance_snapshot(self, trade_date: str):
        """保存绩效快照到MongoDB(供净值曲线使用)"""
        from core.managers import mongo_manager
        if not mongo_manager.db:
            return
        acct = self._broker.get_account()
        positions = self._broker.get_positions()
        total_profit = acct.total_profit
        net_value = acct.total_assets / 1_000_000  # 初始100万
        peak = max(getattr(self, "_nav_peak", 1.0), net_value)
        self._nav_peak = peak
        drawdown_pct = (net_value / peak - 1) * 100 if peak > 0 else 0

        doc = {
            "timestamp": datetime.now().isoformat(),
            "date": trade_date,
            "total_assets": acct.total_assets,
            "available_cash": acct.available_cash,
            "market_value": acct.market_value,
            "total_profit": total_profit,
            "net_value": net_value,
            "drawdown_pct": drawdown_pct,
            "position_count": len(positions),
            "position_ratio": sum(p.current_price * p.total_qty for p in positions) / acct.total_assets * 100 if acct.total_assets > 0 else 0,
        }
        await mongo_manager.db["performance_snapshots"].insert_one(doc)
        logger.info(f"[SNAPSHOT] 绩效快照已保存: 净值={net_value:.4f} 回撤={drawdown_pct:.1f}%")

    async def _push_daily_summary(self, trade_date: str):
        """推送每日结算摘要(飞书/webhook)"""
        acct = self._broker.get_account()
        positions = self._broker.get_positions()
        # 今日买卖统计
        buys = [t for t in self._timeline if t.get("action") == "buy"]
        sells = [t for t in self._timeline if t.get("action") == "sell"]
        wins = [t for t in sells if t.get("profit_pct", 0) > 0]
        losses = [t for t in sells if t.get("profit_pct", 0) <= 0]
        profit_sign = '+' if acct.total_profit >= 0 else ''
        win_rate = f"{len(wins)/len(sells)*100:.0f}%" if sells else "-"
        pos_value = sum(p.current_price * p.total_qty for p in positions)
        pos_ratio = pos_value / acct.total_assets * 100 if acct.total_assets > 0 else 0

        summary = (
            f"📊 每日结算 {trade_date}\n"
            f"💰 总资产: ¥{acct.total_assets:,.0f} | 盈亏: {profit_sign}¥{acct.total_profit:,.0f}\n"
            f"📈 买入: {len(buys)}笔 | 卖出: {len(sells)}笔\n"
            f"✅ 盈利: {len(wins)}笔 | ❌ 亏损: {len(losses)}笔\n"
            f"📊 胜率: {win_rate}\n"
            f"📂 持仓: {len(positions)}只 | 仓位: {pos_ratio:.0f}%"
        )

        # 推送到飞书(如果有webhook)
        try:
            from core.managers.signal_dispatcher import SignalDispatcher
            dispatcher = SignalDispatcher.get_instance()
            if dispatcher:
                await dispatcher.push_message(summary, channel="feishu")
        except Exception:
            pass
        logger.info(f"[DAILY] {summary}")

