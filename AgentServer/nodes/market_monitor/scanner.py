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

        # 数据
        self._data_router: Optional[Any] = None  # DataSourceRouter实例
        self._daily_factors_df: Optional[pd.DataFrame] = None
        self._realtime_cache: Dict[str, Dict] = {}  # ts_code → 实时行情
        self._prev_realtime_cache: Dict[str, Dict] = {}  # ts_code → 上轮实时行情(用于急速拉升检测)
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
        """保存时间线到MongoDB(追加模式, 不删除历史)"""
        try:
            from core.managers import mongo_manager
            if mongo_manager.db is None:
                return
            today = datetime.now().strftime("%Y%m%d")
            if not self._timeline:
                return
            # 只保存今天的时间线
            docs = []
            for item in self._timeline:
                doc = dict(item)
                doc["account_id"] = self._broker.account.account_id if self._broker else "default"
                doc["trade_date"] = today
                # decision_detail可能很大, 但值得保存
                docs.append(doc)
            # 去重: 查已有记录的time+ts_code+action组合, 只插入新的
            existing_keys = set()
            async for doc in mongo_manager.db["scanner_timeline"].find(
                {"account_id": docs[0]["account_id"], "trade_date": today},
                {"time": 1, "ts_code": 1, "action": 1, "_id": 0}
            ):
                existing_keys.add(f"{doc.get('time','')}|{doc.get('ts_code','')}|{doc.get('action','')}")
            new_docs = [d for d in docs if f"{d.get('time','')}|{d.get('ts_code','')}|{d.get('action','')}" not in existing_keys]
            if new_docs:
                await mongo_manager.db["scanner_timeline"].insert_many(new_docs)
                logger.info(f"[SCAN] 保存时间线: {len(new_docs)}条新增")
        except Exception as e:
            logger.info(f"[SCAN] 保存时间线失败(非关键): {e}")

    async def _save_scan_traces(self, filter_result):
        """【V50.1】保存扫描链路追踪到MongoDB
        
        记录每层筛选的完整候选状态, 用于复盘选股全流程
        """
        try:
            from core.managers import mongo_manager
            if mongo_manager.db is None:
                return
            if not filter_result or not filter_result.trace_candidates:
                return
            
            today = datetime.now().strftime("%Y%m%d")
            trace_doc = {
                "trade_date": today,
                "scan_time": datetime.now().isoformat(),
                "account_id": self._broker.account.account_id if self._broker else "default",
                "summary": {},
                "candidates": [],
            }
            
            # 汇总
            for layer, stats in filter_result.trace_summary.items():
                trace_doc["summary"][layer] = dict(stats)
            trace_doc["summary"]["total_candidates"] = len(filter_result.trace_candidates)
            trace_doc["summary"]["passed"] = len([t for t in filter_result.trace_candidates if t.final_status == "passed"])
            trace_doc["summary"]["rejected"] = len([t for t in filter_result.trace_candidates if t.final_status == "rejected"])
            
            # 逐候选明细
            for t in filter_result.trace_candidates:
                trace_doc["candidates"].append({
                    "ts_code": t.ts_code,
                    "stock_name": t.stock_name,
                    "strategy": t.strategy,
                    "strategy_name": t.strategy_name,
                    "price": t.price,
                    "pct_chg": t.pct_chg,
                    "final_status": t.final_status,
                    "rejection_layer": t.final_rejection_layer,
                    "rejection_reason": t.final_rejection_reason,
                    "layer_results": t.layer_results,
                })
            
            await mongo_manager.db["scan_traces"].insert_one(trace_doc)
            logger.info(f"[SCAN] 保存链路追踪: {trace_doc['summary']['total_candidates']}候选, "
                       f"{trace_doc['summary']['passed']}通过/{trace_doc['summary']['rejected']}拒绝")
        except Exception as e:
            logger.warning(f"[SCAN] 保存链路追踪失败(非关键): {e}")

    async def _load_timeline(self):
        """从MongoDB加载时间线(启动时恢复)"""
        try:
            from core.managers import mongo_manager
            if mongo_manager.db is None:
                return
            today = datetime.now().strftime("%Y%m%d")
            account_id = self._broker.account.account_id if self._broker else "default"
            cursor = mongo_manager.db["scanner_timeline"].find(
                {"account_id": account_id, "trade_date": today}
            ).sort("_id", 1)  # 按插入顺序
            async for doc in cursor:
                doc.pop("_id", None)
                doc.pop("account_id", None)
                doc.pop("trade_date", None)
                self._timeline.append(doc)
            if self._timeline:
                logger.info(f"[SCAN] 恢复时间线: {len(self._timeline)}条")
        except Exception as e:
            logger.debug(f"[SCAN] 加载时间线失败(非关键): {e}")

    # (update_strategy_config moved to end of class — see hot-update version)

    # ==================== 生命周期 ====================

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

        self._is_running = True
        self._task = asyncio.create_task(self._scan_loop(trade_date))
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

        # 【V59:每日重置追踪止损+风险等级+执行统计】
        self._trailing_stops.clear()
        self._position_risk_levels.clear()
        # 清理已了结持仓的追踪止损
        if self._broker:
            active_codes = {p.ts_code for p in self._broker.get_positions()}
            stale = [k for k in self._trailing_stops if k not in active_codes]
            for k in stale:
                del self._trailing_stops[k]
        self._execution_stats["stop_loss_response_times"] = []
        logger.info("[SCANNER] 追踪止损+风险等级+执行统计已重置")

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
        """加载当前持仓(优先从MongoDB恢复, 否则从broker获取)"""
        if self._broker:
            # 尝试从MongoDB恢复
            try:
                restored = await self._broker.load_state()
                if restored and self._broker.positions:
                    logger.info(f"[SCANNER] 持仓已从MongoDB恢复: {len(self._broker.positions)}个")
                    return
            except Exception as e:
                logger.warning(f"[SCANNER] 持仓恢复失败(使用空持仓): {e}")
        
        logger.info(f"[SCANNER] 持仓: {len(self._broker.get_positions()) if self._broker else 0}个")

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
                    elapsed = time.time() - last_full_scan
                    
                    if elapsed >= self.SCAN_INTERVAL:
                        await self.scan_once(trade_date)
                        last_full_scan = time.time()
                    else:
                        # 【V59:智能持仓检查频率】
                        check_interval = self._get_smart_check_interval()
                        await self._check_positions_quick(trade_date)
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
                    
                # === 其他非交易时间: 低频持仓检查 ===
                else:
                    # 只检查持仓(不拉行情), 5分钟
                    if self._broker and self._broker.get_positions():
                        await self._check_positions_quick(trade_date)
                    await asyncio.sleep(300)  # 5分钟

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[SCANNER] 异常: {e}", exc_info=True)
            self._is_running = False

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

        logger.info(f"[SCAN #{self._scan_count}] 完成: "
                     f"{len(realtime_data)}只 | {len(self._active_signals)}信号 | "
                     f"{elapsed:.1f}秒")
        
        # 持久化到MongoDB
        try:
            saved = await self._broker.save_state()
            logger.info(f"[SCAN] save_state={saved} positions={len(self._broker.positions)} orders={len(self._broker.orders)}")
            # 保存时间线到MongoDB
            await self._save_timeline()
        except Exception as e:
            logger.warning(f"[SCAN] save_state失败: {e}")

    # ==================== 实时行情 ====================

    async def _fetch_realtime_batch(self, force: bool = False) -> Dict[str, Dict]:
        """批量获取实时行情 — 双数据源架构
        
        数据源分工:
        - 东方财富(免费无限): 全市场5400只的price/pct_chg/volume_ratio/turnover_rate/PE/PB
          → 半路追涨选股 + 持仓止损价格
        - 必盈(200次/天): 涨停池/跌停池/炸板池(封板资金/连板/炸板次数)
          → 首板打板 + 跌停翘板 + 龙头低吸
        
        单次消耗: 东方财富0次(全市场缓存) + 必盈3次(3个池)
        """
        # === 初始化数据源 ===
        if not self._data_router:
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
                    logger.error("[REALTIME] 两个数据源都初始化失败")
                    return {}
                    
                self._data_router = router
                em_status = eastmoney.get_status()
                logger.info(f"[REALTIME] 数据源初始化: 东方财富{em_status['cached_stocks']}只 + 必盈")
            except Exception as e:
                logger.error(f"[REALTIME] 数据源初始化失败: {e}")
                return {}

        # === 获取数据源 ===
        eastmoney = self._data_router._sources.get("eastmoney")
        biying = self._data_router._sources.get("biying")
        
        # === 回放模式: 直接返回历史数据 ===
        if self._replay_mode and self._replay_provider:
            replay_date = self._replay_date or datetime.now().strftime("%Y%m%d")
            replay_data = self._replay_provider.get_realtime(replay_date)
            logger.info(f"[REPLAY] 返回 {len(replay_data)} 只股票的模拟行情(日期={replay_date})")
            return replay_data
        
        # 非交易时间检查: 盘中才有实时数据
        now = datetime.now()
        ct = now.strftime("%H:%M")
        is_trading = ("09:15" <= ct <= "15:05")  # 含竞价和收盘后5分钟
        if not is_trading and not force:
            logger.info(f"[REALTIME] 非交易时间({ct}), 跳过API调用(用force=True强制)")
            return {}

        realtime = {}
        today = datetime.now().strftime("%Y-%m-%d")

        # === 1. 东方财富: 全市场5400只实时行情 (1次请求, 3秒, 0必盈额度) ===
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
                logger.info(f"[REALTIME] 东方财富: {len(em_data)}只全市场快照")
            except Exception as e:
                logger.warning(f"[REALTIME] 东方财富获取失败: {e}, 将依赖必盈")

        # === 2. 必赢涨停池: 封板资金/连板/炸板次数 (3次API, 涨停池独有数据) ===
        # 回放模式: 用MongoDB涨停池数据代替必赢API
        limit_up_count = 0
        if self._replay_mode and self._replay_provider:
            replay_date = self._replay_date or datetime.now().strftime("%Y%m%d")
            pools = self._replay_provider.get_limit_pools(replay_date)
            for item in pools.get('limit_up', []):
                ts_code = item.get('ts_code', '')
                if ts_code in realtime:
                    realtime[ts_code].update({
                        "is_limit_up": True,
                        "limit_times": item.get("limit_times", 0),
                        "fd_amount": item.get("fd_amount", 0),
                    })
            limit_up_count = len(pools.get('limit_up', []))
            logger.info(f"[REPLAY] 涨停池: {limit_up_count}只, 跌停池: {len(pools.get('limit_down', []))}只")
        elif biying:
            try:
                limit_ups = await biying.get_limit_up_pool(today)
                for item in limit_ups:
                    ts_code = item.get("ts_code", "")
                    if not ts_code or "." not in ts_code:
                        continue
                    # 用必盈涨停池数据补充/覆盖东方财富数据
                    if ts_code in realtime:
                        # 已有东方财富基础数据, 补充涨停池特有字段
                        realtime[ts_code].update({
                            "is_limit_up": True,
                            "limit_times": item.get("limit_times", 0),
                            "open_times": item.get("open_times", 0),
                            "fd_amount": item.get("fd_amount", 0),
                        })
                    else:
                        # 东方财富没有(可能刚涨停), 用必盈数据
                        realtime[ts_code] = {
                            "price": float(item.get("close", 0)),
                            "pct_chg": float(item.get("pct_chg", 0)),
                            "turnover_rate": float(item.get("turnover_ratio", 0)),
                            "float_mv": float(item.get("float_mv", 0)) * 1e4,
                            "name": item.get("name", ""),
                            "is_limit_up": True,
                            "limit_times": item.get("limit_times", 0),
                            "open_times": item.get("open_times", 0),
                            "fd_amount": item.get("fd_amount", 0),
                        }
                limit_up_count = len(limit_ups)
                logger.info(f"[REALTIME] 必盈涨停池: {limit_up_count}只")
            except Exception as e:
                logger.warning(f"[REALTIME] 涨停池获取失败: {e}")

            # === 3. 必盈跌停池 (1次API) ===
            try:
                limit_downs = await biying.get_limit_down_pool(today)
                for item in limit_downs:
                    ts_code = item.get("ts_code", "")
                    if not ts_code or "." not in ts_code:
                        continue
                    if ts_code not in realtime:
                        realtime[ts_code] = {
                            "price": float(item.get("close", 0)),
                            "pct_chg": float(item.get("pct_chg", 0)),
                            "name": item.get("name", ""),
                            "is_limit_down": True,
                        }
                    else:
                        realtime[ts_code]["is_limit_down"] = True
                logger.info(f"[REALTIME] 必盈跌停池: {len(limit_downs)}只")
            except Exception as e:
                logger.warning(f"[REALTIME] 跌停池获取失败: {e}")

            # === 4. 必盈炸板池 (1次API) ===
            try:
                broken = await biying.get_broken_board_pool(today)
                for item in broken:
                    ts_code = item.get("ts_code", "")
                    if not ts_code or "." not in ts_code:
                        continue
                    if ts_code not in realtime:
                        realtime[ts_code] = {
                            "price": float(item.get("close", 0)),
                            "pct_chg": float(item.get("pct_chg", 0)),
                            "name": item.get("name", ""),
                            "is_broken_board": True,
                            "open_times": item.get("open_times", 0),
                        }
                    else:
                        realtime[ts_code].update({
                            "is_broken_board": True,
                            "open_times": item.get("open_times", 0),
                        })
                logger.info(f"[REALTIME] 必盈炸板池: {len(broken)}只")
            except Exception as e:
                logger.warning(f"[REALTIME] 炸板池获取失败: {e}")
        else:
            logger.warning("[REALTIME] 必盈不可用, 仅使用东方财富数据(无涨停池详情)")

        self._prev_realtime_cache = dict(self._realtime_cache)  # 保存上轮快照(用于急速拉升检测)
        self._realtime_cache = realtime
        
        # 状态汇报
        em_info = ""
        if eastmoney:
            em_s = eastmoney.get_status()
            em_info = f"东方财富{em_s['cached_stocks']}只 "
        biying_info = ""
        if biying:
            bs = biying.get_status()
            biying_info = f"必盈{bs['daily_calls']}/{bs['daily_limit']}次"
        logger.info(
            f"[REALTIME] 完成: {len(realtime)}只 "
            f"({em_info}{biying_info}) "
            f"涨停{limit_up_count}"
        )
        
        return realtime

    def _short_to_ts_code(self, short_code: str) -> str:
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

    # ==================== 因子合并 ====================

    def _merge_factors(self, realtime_data: Dict[str, Dict]) -> pd.DataFrame:
        """合并日级因子+实时数据"""
        if not realtime_data:
            return pd.DataFrame()

        # 实时数据→DataFrame
        rt_rows = []
        for ts_code, rt in realtime_data.items():
            row = {"ts_code": ts_code}
            # 实时因子(覆盖日级)
            row["pct_chg"] = rt.get("pct_chg", 0)
            row["volume_ratio"] = rt.get("volume_ratio", 0)
            row["turnover_rate"] = rt.get("turnover_rate", 0)
            row["circ_mv"] = rt.get("circ_mv", 0)
            row["open"] = rt.get("open", 0)
            row["high"] = rt.get("high", 0)
            row["low"] = rt.get("low", 0)
            row["close"] = rt.get("price", 0)
            row["pre_close"] = rt.get("pre_close", 0)
            row["stock_name"] = rt.get("name", "")

            # 涨停判断(实时)
            pct = abs(rt.get("pct_chg", 0))
            if ts_code.startswith('688'):
                row["is_limit_up"] = 1 if rt.get("pct_chg", 0) >= 19.5 else 0
                row["is_limit_down"] = 1 if rt.get("pct_chg", 0) <= -19.5 else 0
            elif ts_code.startswith(('4', '8')):
                row["is_limit_up"] = 1 if rt.get("pct_chg", 0) >= 29.5 else 0
                row["is_limit_down"] = 1 if rt.get("pct_chg", 0) <= -29.5 else 0
            else:
                row["is_limit_up"] = 1 if rt.get("pct_chg", 0) >= 9.5 else 0
                row["is_limit_down"] = 1 if rt.get("pct_chg", 0) <= -9.5 else 0

            rt_rows.append(row)

        rt_df = pd.DataFrame(rt_rows)
        rt_df.set_index("ts_code", inplace=False)

        # 合并日级因子(ma5/macd/rsi/boll/atr等)
        if self._daily_factors_df is not None and not self._daily_factors_df.empty:
            # 日级因子列(实时数据没有的)
            daily_cols = ["ts_code", "ma5", "macd", "rsi_6", "boll_upper", "atr",
                          "limit_up_count", "limit_up_yesterday", "limit_down_yesterday",
                          "first_limit_up", "fear_greed_index"]
            available_cols = [c for c in daily_cols if c in self._daily_factors_df.columns]
            if available_cols:
                daily_sub = self._daily_factors_df[available_cols].copy()
                # 用ts_code做merge key
                merged = rt_df.merge(daily_sub, on="ts_code", how="left", suffixes=("", "_daily"))
                # 填充缺失
                for col in ["ma5", "macd", "rsi_6", "boll_upper", "atr", "limit_up_count",
                            "limit_up_yesterday", "limit_down_yesterday", "first_limit_up"]:
                    if col in merged.columns:
                        merged[col] = merged[col].fillna(0)
                return merged

        return rt_df

    # ==================== 策略筛选 ====================

    def _get_effective_strategy_config(self, strategy_key: str) -> Dict:
        """获取策略有效配置(ParamCenter > 前端覆盖 > strategy_defaults)"""
        # 优先级1: ParamCenter(MongoDB, 支持热更新)
        if hasattr(self, '_param_center') and self._param_center._initialized:
            pc_params = self._param_center._cache.get(strategy_key)
            if pc_params:
                return pc_params  # ParamCenter已包含完整配置
        
        # 优先级2: strategy_defaults + 前端覆盖
        from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS
        base = dict(STRATEGY_CONFIGS.get(strategy_key, {}))
        overrides = self.config.get("strategy_overrides", {}).get(strategy_key)
        if overrides:
            if "params" in overrides:
                base["params"] = {**base.get("params", {}), **overrides["params"]}
            if "riskParams" in overrides:
                base["riskParams"] = {**base.get("riskParams", {}), **overrides["riskParams"]}
            if "enabled" in overrides:
                base["enabled"] = overrides["enabled"]
        return base

    def _get_strategy_risk(self, strategy_key: str) -> Dict:
        """获取策略风控参数(小数形式: 0.03=3%)"""
        from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK
        cfg = self._get_effective_strategy_config(strategy_key)
        risk = dict(GLOBAL_RISK)  # 全局兜底
        risk.update(cfg.get("riskParams", {}))  # 策略级覆盖
        # 防御: 如果传了百分比形式(>1), 自动转小数
        if risk.get("stop_loss_pct", 0) > 1:
            risk["stop_loss_pct"] = risk["stop_loss_pct"] / 100
        if risk.get("take_profit_pct", 0) > 1:
            risk["take_profit_pct"] = risk["take_profit_pct"] / 100
        return risk

    async def _apply_strategies(self, merged_df: pd.DataFrame, trade_date: str) -> List[ScanSignal]:
        """策略筛选(复用回测逻辑, 读取前端覆盖参数)"""
        if merged_df is None or len(merged_df) == 0:
            return []

        from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS
        from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester

        bt = PortfolioBacktester()
        signals = []

        for strategy_key in STRATEGY_CONFIGS:
            # 读取有效配置(含前端覆盖)
            cfg = self._get_effective_strategy_config(strategy_key)
            if not cfg.get("enabled", True):
                continue

            strategy_name = cfg["name"]
            params = cfg["params"]

            # 复用回测的筛选条件
            conditions = bt._build_strategy_filter_conditions(strategy_name, params)

            # 应用条件
            mask = pd.Series(True, index=merged_df.index)
            for cond in conditions:
                col = cond.get("name") or cond.get("column")
                op = cond.get("operator", ">=")
                val = cond.get("target") or cond.get("value")
                if col and val is not None and col in merged_df.columns:
                    try:
                        col_data = merged_df[col].fillna(0)
                        if op == ">=":   mask &= (col_data >= val)
                        elif op == "<=": mask &= (col_data <= val)
                        elif op == ">":  mask &= (col_data > val)
                        elif op == "<":  mask &= (col_data < val)
                        elif op == "==": mask &= (col_data == val)
                    except TypeError:
                        pass

            selected = merged_df[mask]

            # 排除已有持仓
            for _, row in selected.iterrows():
                ts_code = row.get("ts_code", "")
                existing_positions = {p.ts_code for p in self._broker.get_positions()}
                if ts_code in existing_positions:
                    continue  # 已持仓, 跳过

                # 构造详细reason
                pct = row.get('pct_chg', 0)
                vr = row.get('volume_ratio', 0)
                tr = row.get('turnover_rate', 0)
                is_lu = bool(row.get('is_limit_up', 0))
                lbc = int(row.get('limit_up_count', 0))
                
                if strategy_key == 'halfway_chase':
                    reason = f"涨{pct:.1f}% 量比{vr:.1f} 换手{tr:.1f}%{' ⚠️ST' if 'ST' in row.get('stock_name','') else ''}"
                elif strategy_key == 'first_limit_up':
                    reason = f"首板涨停 封单强 炸板{lbc}次"
                elif strategy_key == 'dragon_head':
                    reason = f"{lbc}连板龙头 回调{pct:.1f}%"
                elif strategy_key == 'limit_down_qiao':
                    reason = f"跌停撬板 反弹{pct:.1f}%"
                else:
                    reason = f"{strategy_name} 涨{pct:.1f}%"

                signals.append(ScanSignal(
                    ts_code=ts_code,
                    stock_name=row.get("stock_name", ""),
                    strategy=strategy_key,
                    strategy_name=strategy_name,
                    price=row.get("close", 0) or row.get("price", 0),
                    pct_chg=row.get("pct_chg", 0),
                    volume_ratio=row.get("volume_ratio", 0),
                    turnover_rate=row.get("turnover_rate", 0),
                    is_limit_up=bool(row.get("is_limit_up", 0)),
                    limit_up_count=int(row.get("limit_up_count", 0)),
                    reason=reason,
                    scan_time=datetime.now().strftime("%H:%M:%S"),
                    factors={k: row.get(k, 0) for k in
                             ["pct_chg", "volume_ratio", "turnover_rate", "circ_mv",
                              "ma5", "rsi_6", "is_limit_up", "limit_up_count"]
                             if k in row.index},
                    # 【调试增强】策略筛选层trace
                    layer_trace={
                        "L6_strategy": {
                            "strategy": strategy_key,
                            "strategy_name": strategy_name,
                            "conditions_applied": len(conditions),
                            "candidates_before": len(merged_df),
                            "candidates_after": len(selected),
                            "passed": True,
                        }
                    },
                ))

        return signals

    # ==================== 9层筛选管道 ====================

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
        self._current_position_ratio = result.position_ratio
        self._current_sentiment = self._filter_pipeline.get_sentiment_info()

        logger.info(f"[FILTER] 筛选完成: {len(signals)}→{len(filtered_signals)}个信号, "
                     f"仓位系数={result.position_ratio:.0%}")

        return filtered_signals

    # ==================== 信号管理 ====================

    async def _update_signals(self, new_signals: List[ScanSignal], scan_time: str):
        """增量更新信号 + 过期清理"""
        # === 1. 过期清理: 超过SIGNAL_EXPIRE_SECONDS的信号标记为expired ===
        now = time.time()
        expired_keys = set()
        for s in self._active_signals:
            if s.created_at > 0 and (now - s.created_at) > self.SIGNAL_EXPIRE_SECONDS:
                if s.signal_status == "new":  # 只过期未执行的信号
                    s.signal_status = "expired"
                    expired_keys.add(s.ts_code + "|" + s.strategy)
                    logger.debug(f"[SIGNAL] 过期: {s.ts_code} {s.strategy_name} ({now - s.created_at:.0f}s)")
                    # 推送过期事件
                    try:
                        await self._publish_scanner_event("signal_expired", {
                            "ts_code": s.ts_code,
                            "strategy": s.strategy,
                            "expired_after": round(now - s.created_at, 0),
                        })
                    except Exception:
                        pass
        # 移除已过期且已执行的信号(保留expired状态供前端展示)
        self._active_signals = [s for s in self._active_signals
                                 if s.signal_status not in ("expired",) or s.created_at == 0]

        # === 2. 增量更新 ===
        existing_keys = {s.ts_code + "|" + s.strategy for s in self._active_signals}
        added = []

        for sig in new_signals:
            key = sig.ts_code + "|" + sig.strategy
            sig.created_at = now  # 设置创建时间
            if key not in existing_keys:
                self._active_signals.append(sig)
                existing_keys.add(key)
                added.append(sig)
            else:
                # 已存在: 刷新价格和因子(信号可能价格变了)
                for s in self._active_signals:
                    if s.ts_code + "|" + s.strategy == key:
                        s.price = sig.price
                        s.pct_chg = sig.pct_chg
                        s.volume_ratio = sig.volume_ratio
                        s.turnover_rate = sig.turnover_rate
                        s.scan_time = sig.scan_time
                        # 不刷新created_at: 保留原始创建时间, 让信号正常过期
                        # 如果需要续期, 用户可以手动买入
                        break

        if added:
            self._stats["signals_found"] += len(added)
            logger.info(f"[SIGNAL] 新增{len(added)}个信号: "
                         f"{', '.join(s.ts_code for s in added[:5])}")

            # 推送新信号
            await self._push_signals(added)

            # 执行新信号
            await self._execute_signals(added)
            
            # 执行后立即持久化(防止崩溃丢数据)
            if self._broker:
                try:
                    await self._broker.save_state()
                except Exception:
                    pass  # 持久化失败不影响交易
            
            # WebSocket推送(通过Redis PubSub) — 使用标准_publish_scanner_event
            try:
                await self._publish_scanner_event("signal", {
                    "signals": [{
                        "ts_code": s.ts_code,
                        "name": s.stock_name,
                        "strategy": s.strategy_name,
                        "pct_chg": round(s.pct_chg, 1),
                        "reason": s.reason,
                    } for s in added[:10]],
                    "count": len(added),
                    "time": scan_time,
                })
            except Exception:
                pass  # 推送失败不影响交易

    async def _push_signals(self, signals: List[ScanSignal]):
        """推送信号"""
        try:
            from core.managers.live.signal_pusher import SignalPusher
            pusher = SignalPusher(self.config.get("push", {}))
            lines = [f"🎯 **实时信号** ({datetime.now().strftime('%H:%M:%S')})"]
            for sig in signals[:10]:
                pct = f"+{sig.pct_chg:.1f}%" if sig.pct_chg > 0 else f"{sig.pct_chg:.1f}%"
                lines.append(f"- {sig.ts_code} {sig.stock_name} | {sig.strategy_name} | {pct}")
            if len(signals) > 10:
                lines.append(f"... 共{len(signals)}个")
            await asyncio.to_thread(pusher.push_signal, "\n".join(lines))
        except Exception as e:
            logger.debug(f"[PUSH] 推送失败(可忽略): {e}")

    def _add_timeline_log(self, action, ts_code, stock_name, strategy, reason, sig):
        """【V50.1】添加执行日志到时间线(含blocked状态)"""
        self._timeline.append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "action": action,
            "ts_code": ts_code,
            "stock_name": stock_name,
            "strategy": strategy,
            "reason": reason,
            "decision_detail": getattr(sig, "decision_detail", {}),
            "layer_trace": getattr(sig, "layer_trace", {}),
        })

    async def _execute_signals(self, signals: List[ScanSignal]):
        """执行信号(SimulatedBroker撮合)
        
        仓位管理(PositionSizer):
        - 信号强度高(涨停+连板) → 重仓(可用现金40%)
        - 信号强度中(半路追涨/首板) → 中仓(可用现金25%)
        - 信号强度低(跌停翘板/低吸) → 轻仓(可用现金15%)
        - 总仓位上限70%, 单票上限15%

        【调试增强】dry_run模式: 只记录信号, 不实际下单
        """
        # dry_run模式: 标记信号为skipped, 不执行交易
        if self._dry_run:
            for sig in signals:
                sig.signal_status = "skipped"
                sig.layer_trace["execution"] = {
                    "mode": "dry_run",
                    "reason": "调试模式, 不执行交易",
                    "would_buy_shares": self._calc_would_buy_shares(sig),
                    "would_buy_amount": round(sig.price * self._calc_would_buy_shares(sig), 2),
                }
                self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                    sig.strategy_name, "调试模式, 未实际下单", sig)
                logger.info(f"[DRY-RUN] 跳过买入 {sig.ts_code} {sig.stock_name} ({sig.strategy_name})")
            return

        stop_loss = self.config.get("stop_loss", -3.0)  # 【V50:默认-3%对齐GLOBAL_RISK,原-5%过低】
        take_profit = self.config.get("take_profit", 7.0)

        for sig in signals:
            # 【安全】异动信号只观察不自动买入(历史bug: 曾绕过强制空仓造成重大损失)
            if "anomaly" in sig.strategy:
                sig.signal_status = "skipped"
                self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                    sig.strategy_name, "异动信号, 仅观察不自动交易", sig)
                logger.info(f"[EXEC] 异动信号仅观察: {sig.ts_code} {sig.stock_name} ({sig.strategy_name})")
                continue

            # 【去重】同票已有持仓则跳过(不同策略推荐同一只股不重复买入)
            existing = self._broker.get_positions()
            if any(p.ts_code == sig.ts_code for p in existing):
                sig.signal_status = "skipped"
                self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                    sig.strategy_name, "已有持仓, 跳过", sig)
                logger.info(f"[EXEC] {sig.ts_code} 已有持仓, 跳过")
                continue

            # 熔断检查
            if not await self._check_circuit_breaker():
                self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                    sig.strategy_name, "风控熔断中, 暂停买入", sig)
                logger.info(f"[EXEC] 风控熔断, 跳过买入")
                break
                
            if len(self._broker.get_positions()) >= self.MAX_POSITIONS:
                self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                    sig.strategy_name, f"已达最大持仓{self.MAX_POSITIONS}只", sig)
                logger.info(f"[EXEC] 已达最大持仓{self.MAX_POSITIONS}, 跳过")
                break

            if sig.price <= 0:
                self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                    sig.strategy_name, f"价格异常(price={sig.price})", sig)
                continue

            # === PositionSizer: 按策略和信号强度分配仓位 ===
            acct = self._broker.get_account()
            position_ratio = self._calc_position_ratio(sig)
            max_amount = acct.available_cash * position_ratio
            shares = int(max_amount / sig.price / 100) * 100
            
            # 科创板最小200股
            if sig.ts_code.startswith('688'):
                shares = int(max_amount / sig.price / 200) * 200
                if shares <= 0 and max_amount > 0:
                    self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                        sig.strategy_name, f"科创板资金不足200股(需≥{sig.price*200:.0f}元, 可用{max_amount:.0f}元)", sig)
                    logger.info(f"[EXEC] {sig.ts_code} 科创板资金不足200股(需≥{sig.price*200:.0f}元, 可用{max_amount:.0f}元)")
                    continue
                
            if shares <= 0:
                self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                    sig.strategy_name, f"资金不足({max_amount:.0f}元<{sig.price*100:.0f}元)", sig)
                continue

            # 更新实时价格到broker
            self._broker.update_realtime(sig.ts_code, sig.price)

            # 【V51:下单前执行质量检查】
            if self._pre_trade_checker:
                self._pre_trade_checker._broker = self._broker  # 更新broker引用
                ok_pre, pre_reason = self._pre_trade_checker.check_buy(
                    ts_code=sig.ts_code,
                    price=sig.price,
                    quantity=shares,
                    stock_name=sig.stock_name,
                    strategy=sig.strategy,
                )
                if not ok_pre:
                    self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                        sig.strategy_name, f"执行质量检查拒绝: {pre_reason}", sig)
                    logger.info(f"[EXEC] 买入被拒: {sig.ts_code} {pre_reason}")
                    continue

            # 【V51:滑点估算】
            daily_vol = self._realtime_cache.get(sig.ts_code, {}).get("volume", 0)
            slippage = self._slippage_model.estimate(
                price=sig.price, quantity=shares,
                daily_volume=daily_vol * 100 if daily_vol else 0,  # 万手→股
                side="buy", reason=sig.reason,
            )
            adjusted_price = self._slippage_model.apply_slippage(sig.price, slippage)
            if abs(slippage) > 0.001:
                logger.info(f"[EXEC] 滑点调整: {sig.ts_code} {sig.price:.2f}→{adjusted_price:.2f} (slippage={slippage*100:.3f}%)")

            ok, msg, order = self._broker.place_order(
                ts_code=sig.ts_code,
                stock_name=sig.stock_name,
                side="buy",
                quantity=shares,
                price=sig.price,
                order_type="market",
                strategy=sig.strategy,
                reason=sig.reason,
            )

            if ok:
                self._timeline.append({
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "action": "buy",
                    "ts_code": sig.ts_code,
                    "stock_name": sig.stock_name,
                    "strategy": sig.strategy_name,
                    "shares": shares,
                    "price": order.filled_price,
                    "reason": sig.reason,
                    "decision_detail": {
                        **sig.decision_detail,
                        "execution": {
                            "position_ratio": position_ratio,
                            "available_cash": round(acct.available_cash, 2),
                            "max_amount": round(max_amount, 2),
                            "shares": shares,
                            "filled_price": order.filled_price,
                            "total_cost": round(order.filled_price * shares, 2),
                            "circuit_breaker": {
                                "paused": self._circuit_breaker.get("trading_paused", False),
                                "consecutive_losses": self._circuit_breaker.get("consecutive_losses", 0),
                            },
                            "sentiment": self._current_sentiment if hasattr(self, '_current_sentiment') else {},
                            "position_count_before": len(self._broker.get_positions()),
                        },
                    },
                })
                sig.signal_status = "executed"
                self._stats["trades_executed"] += 1
                # 推送信号+时间线到Redis
                await self._publish_scanner_event("signal", {
                    "signals": [self._signal_to_dict(sig)],
                })
                await self._publish_scanner_event("timeline", {
                    "item": self._timeline[-1],
                })
                logger.info(f"[EXEC] 买入 {sig.ts_code} {shares}股@{order.filled_price:.2f} ({sig.strategy_name})")
            else:
                self._add_timeline_log("blocked", sig.ts_code, sig.stock_name,
                    sig.strategy_name, f"下单失败: {msg}", sig)
                logger.warning(f"[EXEC] 买入被拒 {sig.ts_code}: {msg}")

    # ==================== 公共止损止盈方法 ====================

    def _calc_stop_loss_price(self, pos_or_cost, risk: Dict) -> float:
        """统一止损价计算(小数形式)
        
        Args:
            pos_or_cost: Position对象或cost_price(float)
            risk: 策略风控参数(小数形式: stop_loss_pct=0.03)
        Returns:
            止损价(float)
        """
        cost = pos_or_cost.avg_cost if hasattr(pos_or_cost, 'avg_cost') else pos_or_cost
        sl_pct = risk.get("stop_loss_pct", 0.03)
        # 防御: 百分比形式(>1)自动转小数
        if sl_pct > 1:
            sl_pct = sl_pct / 100
        return round(cost * (1 - sl_pct), 2)

    def _calc_take_profit_price(self, pos_or_cost, risk: Dict) -> float:
        """统一止盈价计算(小数形式)
        
        Args:
            pos_or_cost: Position对象或cost_price(float)
            risk: 策略风控参数(小数形式: take_profit_pct=0.07)
        Returns:
            止盈价(float)
        """
        cost = pos_or_cost.avg_cost if hasattr(pos_or_cost, 'avg_cost') else pos_or_cost
        tp_pct = risk.get("take_profit_pct", 0.07)
        # 防御: 百分比形式(>1)自动转小数
        if tp_pct > 1:
            tp_pct = tp_pct / 100
        return round(cost * (1 + tp_pct), 2)

    def _check_stop_loss_take_profit(self, positions, realtime_data: Dict) -> List[Tuple]:
        """公共止损止盈检查(提取重复逻辑)
        
        V59增强: 追踪止损 + 智能风险分级
        
        Returns: List of (pos, sell_reason, sell_price, risk_dict)
        """
        # 【V59:更新追踪止损状态】
        self._update_trailing_stops(positions, realtime_data)
        
        to_sell = []
        for pos in positions:
            if pos.available_qty <= 0:
                continue  # T+1: 今日买入不可卖

            # 获取策略级风控参数
            risk = self._get_strategy_risk(pos.strategy)
            # 单票风控覆盖(用户手动调整)
            pos_overrides = getattr(self, '_position_risk_overrides', {}).get(pos.ts_code, {})
            if 'stop_loss_pct' in pos_overrides:
                risk['stop_loss_pct'] = pos_overrides['stop_loss_pct']
            if 'take_profit_pct' in pos_overrides:
                risk['take_profit_pct'] = pos_overrides['take_profit_pct']
            stop_loss_pct = -risk.get("stop_loss_pct", 0.03) * 100   # 0.03→-3.0%
            take_profit_pct = risk.get("take_profit_pct", 0.07) * 100  # 0.07→7.0%

            # 统一止损价计算
            stop_loss_price = self._calc_stop_loss_price(pos, risk)
            take_profit_price = self._calc_take_profit_price(pos, risk)

            sell_reason = None
            sell_price = pos.current_price  # 默认市价

            # 【V59:追踪止损检查】
            trailing = self._trailing_stops.get(pos.ts_code)
            trailing_triggered = False
            if trailing and trailing.get("activated") and trailing.get("stop_price", 0) > 0:
                trailing_stop_price = trailing["stop_price"]
                if pos.current_price <= trailing_stop_price:
                    # 追踪止损触发
                    high_price = trailing.get("high_price", pos.avg_cost)
                    trailing_pct = trailing.get("trailing_stop_pct", 0)
                    profit_at_high = (high_price / pos.avg_cost - 1) * 100 if pos.avg_cost > 0 else 0
                    sell_reason = f"追踪止损(最高{high_price:.2f}→{trailing_pct*100:.0f}%回撤, 曾盈{profit_at_high:.1f}%)"
                    sell_price = trailing_stop_price
                    trailing_triggered = True

            # 常规止损止盈(仅在追踪止损未触发时检查)
            if not trailing_triggered:
                # 跳空止损检查(与回测一致)
                rt = realtime_data.get(pos.ts_code, {})
                today_open = rt.get("open", 0) if rt else self._get_open_price(pos.ts_code)

                if pos.profit_pct <= stop_loss_pct:
                    if today_open and today_open > 0 and today_open < stop_loss_price:
                        sell_reason = f"跳空止损(开{today_open:.2f}<止损{stop_loss_price:.2f})"
                        sell_price = today_open
                    else:
                        sell_reason = f"止损 {pos.profit_pct:.1f}%"
                elif pos.profit_pct >= take_profit_pct:
                    sell_reason = f"止盈 {pos.profit_pct:.1f}%"

                # 【V42:冲高回落/利润保护/利润锁定——与回测sell_signal_checker对齐】
                if not sell_reason and pos.avg_cost > 0:
                    open_rise = (today_open / pos.avg_cost - 1) if today_open > 0 else 0
                    close_rise = pos.profit_pct / 100  # 小数形式
                    next_day_sell_pct = risk.get("next_day_open_sell_pct", 0.03)

                    if open_rise >= next_day_sell_pct and pos.current_price < today_open:
                        if open_rise >= 0.05:
                            sell_reason = f"冲高回落(开涨{open_rise*100:.1f}%)"
                            sell_price = today_open
                        elif (today_open - pos.current_price) / today_open >= 0.01:
                            sell_reason = f"冲高回落(开涨{open_rise*100:.1f}%回落)"
                            sell_price = today_open

                    if not sell_reason and open_rise >= 0.02 and close_rise >= 0.02 and pos.current_price < today_open:
                        sell_reason = f"利润保护(收涨{close_rise*100:.1f}%)"
                        sell_price = pos.current_price

                    if not sell_reason and open_rise >= next_day_sell_pct:
                        strategy_name = getattr(pos, 'strategy', '')
                        if strategy_name in ('first_limit_up', '首板打板'):
                            sell_reason = f"高开即卖(开涨{open_rise*100:.1f}%)"
                            sell_price = today_open

            if sell_reason:
                to_sell.append((pos, sell_reason, sell_price, risk))

        return to_sell

    # ==================== 持仓检查 ====================

    async def _check_positions(self, realtime_data: Dict[str, Dict], trade_date: str):
        """止损止盈+超时强卖检查
        
        与回测portfolio_backtest.py一致的卖出逻辑:
        1. 跳空止损: 当日开盘价<止损价 → 用开盘价卖出
        2. 正常止损: 当前价触发止损 → 市价卖出
        3. 止盈: 当前价触发止盈 → 市价卖出
        4. 冲高回落/利润保护/高开即卖
        5. 超时强卖: 持仓天数≥max_hold_days → 市价卖出
        6. 移动止损: 盈利超过阈值后,止损线上移保护利润
        """
        # 使用公共止损止盈检查方法
        to_sell = self._check_stop_loss_take_profit(
            self._broker.get_positions(), realtime_data
        )

        # === 超时强卖(与回测对齐) ===
        from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK
        for pos in self._broker.get_positions():
            if pos.available_qty <= 0 or not pos.buy_date:
                continue
            risk = self._get_strategy_risk(pos.strategy)
            max_hold = risk.get("max_hold_days", GLOBAL_RISK.get("max_hold_days", 999))
            if max_hold >= 999:
                continue
            try:
                buy_dt = int(pos.buy_date)
                cur_dt = int(trade_date)
                # 简单计算交易日差(含首尾)
                from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
                bt = PortfolioBacktester()
                days_held = bt._calc_trade_days_held(buy_dt, cur_dt)
                if days_held >= max_hold:
                    # 检查是否已经在to_sell里
                    already = any(p.ts_code == pos.ts_code for p, _, _, _ in to_sell)
                    if not already:
                        to_sell.append((pos, f"超时({days_held}日≥{max_hold}日)", pos.current_price, risk))
                        logger.info(f"[TIMEOUT] {pos.ts_code} 持仓{days_held}日≥{max_hold}日, 强制卖出")
            except (ValueError, TypeError):
                pass

        # === 移动止损(盈利保护) ===
        for pos in self._broker.get_positions():
            if pos.available_qty <= 0:
                continue
            risk = self._get_strategy_risk(pos.strategy)
            # 单票覆盖
            pos_overrides = getattr(self, '_position_risk_overrides', {}).get(pos.ts_code, {})
            sl_pct = pos_overrides.get('stop_loss_pct', risk.get('stop_loss_pct', 0.03))
            # 盈利超过2倍止损时, 止损线上移到成本价(保本出局)
            if pos.profit_pct / 100 > sl_pct * 2:  # 盈利>2倍止损线
                # 检查是否已经在to_sell(不要覆盖已有止损)
                already = any(p.ts_code == pos.ts_code for p, _, _, _ in to_sell)
                if not already and pos.profit_pct <= 0:
                    # 盈利回撤到0以下, 但原本止损线在-3%, 现在应该保本出局
                    to_sell.append((pos, f"移动止损(盈利回撤至{pos.profit_pct:.1f}%)", pos.current_price, risk))
                    logger.info(f"[TRAILING] {pos.ts_code} 盈利回撤至{pos.profit_pct:.1f}%, 移动止损触发")

        # 执行卖出
        for pos, reason, sell_price, risk in to_sell:
            if pos.available_qty <= 0:
                continue  # T+1: 今日买入不可卖

            # 【P1-7修复】在卖出前保存关键值(place_order会修改pos对象)
            sell_qty = pos.available_qty
            sell_profit_pct = pos.profit_pct
            sell_profit_amount = (pos.current_price - pos.avg_cost) * sell_qty
            sell_avg_cost = pos.avg_cost
            sell_current_price = pos.current_price

            self._broker.update_realtime(pos.ts_code, pos.current_price)
            ok, msg, order = self._broker.place_order(
                ts_code=pos.ts_code,
                stock_name=pos.stock_name,
                side="sell",
                quantity=sell_qty,
                price=sell_price,
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
                    "shares": sell_qty,
                    "price": order.filled_price,
                    "reason": reason,
                    "profit_pct": round(sell_profit_pct, 2),
                    "profit_amount": round(sell_profit_amount, 2),  # 【P1-7修复】用卖出前保存的值
                    "decision_detail": {  # 【实盘审查增强】卖出决策详情(使用正确的risk)
                        "sell_reason": reason,
                        "profit_pct": round(sell_profit_pct, 2),
                        "profit_amount": round(sell_profit_amount, 2),
                        "cost_price": sell_avg_cost,
                        "sell_price": order.filled_price,
                        "current_price": sell_current_price,
                        "stop_loss_pct": round(-risk.get("stop_loss_pct", 0.03) * 100, 1),
                        "take_profit_pct": round(risk.get("take_profit_pct", 0.07) * 100, 1),
                        "stop_loss_price": self._calc_stop_loss_price(pos, risk),
                        "take_profit_price": self._calc_take_profit_price(pos, risk),
                        "hold_minutes": 0,
                    },
                })
                if "止损" in reason:
                    self._stats["stop_losses"] += 1
                    # 【V59:止损响应时间追踪】
                    try:
                        self._execution_stats["stop_loss_response_times"].append(time.time())
                        if len(self._execution_stats["stop_loss_response_times"]) > 50:
                            self._execution_stats["stop_loss_response_times"] = self._execution_stats["stop_loss_response_times"][-50:]
                    except Exception:
                        pass
                else:
                    self._stats["take_profits"] += 1
                await self._publish_scanner_event("timeline", {"item": self._timeline[-1]})
                logger.info(f"[RISK] {reason}: {pos.ts_code} {pos.available_qty}股@{order.filled_price:.2f}")
        
        # 【V59:卖出后清理追踪止损和风险等级】
        for pos, reason, _, _ in to_sell:
            self._trailing_stops.pop(pos.ts_code, None)
            self._position_risk_levels.pop(pos.ts_code, None)
        
        # 止损止盈后强制持久化(跳过节流)
        if to_sell and self._broker:
            try:
                await self._broker.save_state(force=True)
            except Exception:
                pass

    async def _check_positions_quick(self, trade_date: str):
        """持仓快速检查(30秒级, 用东方财富全市场缓存)
        
        东方财富3秒获取全市场5400只价格, 不消耗必盈额度。
        只从缓存提取持仓股价格, 然后检查止损止盈。
        
        【增强】
        - 跳空止损: 当日open<止损价→open卖出(与回测一致)
        - 跌停不可卖: 跌停股不执行卖出(挂单无法成交)
        - dry_run模式: 不执行卖出, 只记录
        """
        if not self._broker:
            return
            
        positions = self._broker.get_positions()
        if not positions:
            return
        
        # 风控熔断检查
        if not await self._check_circuit_breaker():
            return
        
        # 东方财富: 从缓存获取持仓股价格(0额外API)
        pos_codes = [pos.ts_code for pos in positions]
        if self._data_router:
            eastmoney = self._data_router._sources.get("eastmoney")
            if eastmoney:
                prices = await eastmoney.get_position_prices(pos_codes)
                for ts_code, price in prices.items():
                    if price and price > 0:
                        self._broker.update_realtime(ts_code=ts_code, price=price)
                logger.debug(f"[QUICK] 东方财富更新: {len(prices)}/{len(pos_codes)}只持仓价")
        
        # 回退: 用全量扫描缓存
        for pos in positions:
            if pos.ts_code not in (self._realtime_cache or {}):
                continue
            cached = self._realtime_cache.get(pos.ts_code, {})
            if cached.get("price", 0) > 0 and pos.current_price <= 0:
                self._broker.update_realtime(
                    ts_code=pos.ts_code,
                    price=cached["price"],
                    pre_close=cached.get("pre_close", 0),
                )
        
        # 使用公共止损止盈检查方法
        to_sell = self._check_stop_loss_take_profit(
            self._broker.get_positions(), self._realtime_cache or {}
        )
        
        # 执行卖出
        for pos, reason, force_price, risk in to_sell:
            if pos.available_qty <= 0:
                continue
            
            # 【增强】跌停不可卖: 检查是否跌停
            if self._is_limit_down(pos.ts_code):
                self._add_timeline_log("blocked", pos.ts_code, pos.stock_name,
                    pos.strategy, f"跌停不可卖(触发{reason}但跌停挂单无法成交)", None)
                logger.warning(f"[QUICK] 跌停不可卖: {pos.ts_code} {pos.stock_name}")
                continue
            
            # 【增强】dry_run模式: 不执行卖出
            if self._dry_run:
                self._add_timeline_log("blocked", pos.ts_code, pos.stock_name,
                    pos.strategy, f"调试模式跳过卖出({reason})", None)
                logger.info(f"[DRY-RUN] 跳过卖出 {pos.ts_code} {reason}")
                continue
            
            # 【P1-7修复】在卖出前保存关键值
            sell_qty = pos.available_qty
            sell_profit_pct = pos.profit_pct
            sell_profit_amount = (pos.current_price - pos.avg_cost) * sell_qty
            sell_avg_cost = pos.avg_cost
            sell_current_price = pos.current_price
            
            sell_price = force_price if force_price else sell_current_price
            self._broker.update_realtime(pos.ts_code, sell_price)
            ok, msg, order = self._broker.place_order(
                ts_code=pos.ts_code,
                stock_name=pos.stock_name,
                side="sell",
                quantity=sell_qty,
                price=sell_price,
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
                    "shares": sell_qty,
                    "price": order.filled_price,
                    "reason": reason,
                    "profit_pct": round(sell_profit_pct, 2),
                    "profit_amount": round(sell_profit_amount, 2),  # 【P1-7修复】用卖出前保存的值
                })
                if "止损" in reason:
                    self._stats["stop_losses"] += 1
                else:
                    self._stats["take_profits"] += 1
                await self._publish_scanner_event("timeline", {"item": self._timeline[-1]})
                logger.info(f"[QUICK] {reason}: {pos.ts_code} {pos.available_qty}股@{order.filled_price:.2f}")
        
        # 止损止盈后强制持久化(跳过节流)
        if to_sell and self._broker:
            try:
                await self._broker.save_state(force=True)
            except Exception:
                pass

    # ==================== V59:智能持仓检查频率 ====================

    def _get_effective_stop_price(self, pos, risk: Dict) -> Optional[float]:
        """获取有效止损价(考虑追踪止损)
        
        追踪止损激活后, 取固定止损价和追踪止损价中较高的那个(更紧的)
        """
        fixed_sl = self._calc_stop_loss_price(pos, risk)
        trailing = self._trailing_stops.get(pos.ts_code)
        if trailing and trailing.get("activated") and trailing.get("stop_price", 0) > 0:
            trailing_sl = trailing["stop_price"]
            # 取较高的止损价(更紧)
            return max(fixed_sl, trailing_sl) if fixed_sl > 0 else trailing_sl
        return fixed_sl

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
        """更新追踪止损状态
        
        规则(与真实超短量化对齐):
        1. 买入后, 初始止损=固定止损(如-3%)
        2. 当盈利>=2%时, 激活追踪止损, 止损线=最高价×(1-trailing_pct)
        3. 价格创新高时, 止损线上移
        4. 价格回落触发追踪止损时卖出, 锁住大部分利润
        
        trailing_pct由策略参数决定:
        - 半路追涨: 2%(盈利后保住更多利润)
        - 龙头低吸: 3%(给更多波动空间)
        - 跌停翘板: 4%(波动极大, 不能太紧)
        """
        for pos in positions:
            ts_code = pos.ts_code
            current_price = pos.current_price
            
            if current_price <= 0 or pos.avg_cost <= 0:
                continue
            
            profit_pct = pos.profit_pct  # 如: 5.0 = +5%
            
            # 获取策略追踪止损比例
            risk = self._get_strategy_risk(pos.strategy)
            trailing_stop_pct = risk.get("trailing_stop_pct", 0.0)  # 0=不启用
            
            if trailing_stop_pct <= 0:
                # 策略未启用追踪止损, 跳过
                continue
            
            state = self._trailing_stops.get(ts_code, {
                "high_price": pos.avg_cost,  # 初始=成本价
                "trailing_stop_pct": trailing_stop_pct,
                "activated": False,
                "activated_at": None,  # 激活时间
                "stop_price": 0.0,  # 当前追踪止损价
            })
            
            # 更新最高价
            if current_price > state["high_price"]:
                state["high_price"] = current_price
                logger.debug(f"[TRAILING] {ts_code} 新高: {current_price:.2f}")
            
            # 盈利>=2%时激活追踪止损
            if not state["activated"] and profit_pct >= 2.0:
                state["activated"] = True
                state["activated_at"] = datetime.now().strftime("%H:%M:%S")
                logger.info(f"[TRAILING] {ts_code} 追踪止损激活: 盈利{profit_pct:.1f}%>=2%")
            
            # 计算追踪止损价
            if state["activated"]:
                state["stop_price"] = state["high_price"] * (1 - trailing_stop_pct)
            
            self._trailing_stops[ts_code] = state

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
        """检查是否跌停(跌停不可卖)"""
        cached = (self._realtime_cache or {}).get(ts_code, {})
        pct = cached.get("pct_chg", 0)
        # ST股跌停-5%, 普通-10%, 科创/创业板-20%
        if ts_code.startswith(('688', '300')):
            return pct <= -19.5  # -20%跌停
        elif cached.get("is_st", False):
            return pct <= -4.5  # -5%跌停
        else:
            return pct <= -9.5  # -10%跌停

    # ==================== 参数校验 ====================

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
        """安全round, 处理None/NaN/inf"""
        if v is None:
            return None
        try:
            import math
            if math.isnan(v) or math.isinf(v):
                return None
            return round(v, digits)
        except (TypeError, ValueError):
            return None

    async def _publish_scanner_event(self, event_type: str, data: Dict):
        """推送scanner事件到Redis Pub/Sub(→WebSocket实时推送)"""
        try:
            from core.managers import redis_manager
            if redis_manager._client:
                channel = f"scanner:{event_type}"
                data["timestamp"] = datetime.now().strftime("%H:%M:%S")
                await redis_manager._client.publish(channel, json.dumps(data, ensure_ascii=False))
        except Exception as e:
            logger.debug(f"[PUSH] Redis推送失败(可忽略): {e}")

    def _position_to_dict(self, p) -> Dict:
        """Position对象转dict"""
        risk = self._get_strategy_risk(p.strategy)
        sl_price = self._calc_stop_loss_price(p, risk)
        tp_price = self._calc_take_profit_price(p, risk)
        sl_pct = risk.get("stop_loss_pct", 0.03) * 100
        tp_pct = risk.get("take_profit_pct", 0.07) * 100
        mv = round(p.current_price * p.total_qty, 2)
        profit_amt = round((p.current_price - p.avg_cost) * p.total_qty, 2)
        # 策略中文名映射
        strategy_cn = {
            "halfway_chase": "半路追涨", "first_limit_up": "首板打板",
            "dragon_head": "龙头低吸", "limit_down_qiao": "跌停翘板",
            "limit_up_open": "涨停开板",
            "anomaly_surge": "急速拉升", "anomaly_broken": "涨停炸板", "anomaly_strong": "强势涨停",
            "manual": "手动操作",
        }.get(p.strategy, p.strategy)
        return {
            "ts_code": p.ts_code, "stock_name": p.stock_name,
            "strategy": p.strategy, "strategy_name": strategy_cn, "shares": p.total_qty,
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
        }

    def _signal_to_dict(self, s: ScanSignal) -> Dict:
        """ScanSignal对象转dict"""
        d = {
            "ts_code": s.ts_code, "stock_name": s.stock_name,
            "strategy": s.strategy, "strategy_name": s.strategy_name,
            "signal_type": s.signal_type, "price": MarketScanner._safe_round(s.price),
            "pct_chg": MarketScanner._safe_round(s.pct_chg),
            "volume_ratio": MarketScanner._safe_round(s.volume_ratio),
            "turnover_rate": MarketScanner._safe_round(s.turnover_rate),
            "is_limit_up": s.is_limit_up,
            "limit_up_count": s.limit_up_count,
            "confidence": s.confidence, "reason": s.reason,
            "scan_time": s.scan_time, "factors": s.factors,
            "signal_status": s.signal_status,
            "created_at": s.created_at,
            "expire_remaining": max(0, self.SIGNAL_EXPIRE_SECONDS - (time.time() - s.created_at)) if s.created_at > 0 else -1,
            # 【P1-1】关键因子摘要(前端可直接展示)
            "key_factors": self._extract_key_factors(s),
        }
        if s.decision_detail:
            d["decision_detail"] = s.decision_detail
        if s.layer_trace:
            d["layer_trace"] = s.layer_trace
        return d

    def _extract_key_factors(self, s: ScanSignal) -> Dict[str, Any]:
        """提取信号的关键因子摘要(前端卡片展示用)"""
        factors = s.factors or {}
        key = {}
        # 流通市值(小盘股优先)
        if factors.get("circ_mv"):
            mv = factors["circ_mv"]
            key["circ_mv"] = f"{mv/10000:.0f}亿" if mv >= 10000 else f"{mv/100:.0f}万"
        # PE/PB(估值)
        if factors.get("pe") and factors["pe"] > 0:
            key["pe"] = f"PE{factors['pe']:.0f}"
        if factors.get("pb") and factors["pb"] > 0:
            key["pb"] = f"PB{factors['pb']:.1f}"
        # 连板数
        if s.limit_up_count > 0:
            key["limit_count"] = f"{s.limit_up_count}连板"
        # 封单资金(涨停信号)
        if factors.get("fd_amount"):
            key["fd_amount"] = f"封单{factors['fd_amount']/1000:.0f}万"
        # 量比/换手(核心量能指标)
        if s.volume_ratio > 0:
            key["volume_ratio"] = f"量比{s.volume_ratio:.1f}"
        if s.turnover_rate > 0:
            key["turnover_rate"] = f"换手{s.turnover_rate:.1f}%"
        return key

    def generate_summary_report(self) -> Dict[str, Any]:
        """生成完整交易摘要报告(供API调用)
        
        包含:
        - 账户概览(资产/现金/仓位/盈亏)
        - 持仓详情(每只股票的成本/现价/盈亏/止损止盈)
        - 今日交易统计(买入/卖出/胜率/盈亏比)
        - 策略表现(每策略的交易数/胜率/盈亏)
        - 风控状态(熔断/连续亏损/最大回撤)
        - 信号统计(活跃/过期/执行/跳过)
        """
        if not self._broker:
            return {"error": "Broker未初始化"}
        
        acct = self._broker.get_account()
        positions = self._broker.get_positions()
        
        # === 账户概览 ===
        account_summary = {
            "total_assets": round(acct.total_assets, 2),
            "available_cash": round(acct.available_cash, 2),
            "market_value": round(acct.market_value, 2),
            "total_profit": round(acct.total_profit, 2),
            "position_ratio": round(acct.market_value / max(acct.total_assets, 1) * 100, 1),
            "position_count": len(positions),
        }
        
        # === 持仓详情 ===
        position_details = []
        for p in positions:
            risk = self._get_strategy_risk(p.strategy)
            sl_pct = risk.get("stop_loss_pct", 0.03) * 100
            tp_pct = risk.get("take_profit_pct", 0.07) * 100
            position_details.append({
                "ts_code": p.ts_code,
                "stock_name": p.stock_name,
                "strategy": p.strategy,
                "shares": p.total_qty,
                "available_qty": p.available_qty,
                "cost_price": round(p.avg_cost, 2),
                "current_price": round(p.current_price, 2),
                "profit_pct": round(p.profit_pct, 2),
                "market_value": round(p.current_price * p.total_qty, 2),
                "stop_loss_price": round(p.avg_cost * (1 - risk.get("stop_loss_pct", 0.03)), 2),
                "take_profit_price": round(p.avg_cost * (1 + risk.get("take_profit_pct", 0.07)), 2),
                "stop_loss_pct": round(sl_pct, 1),
                "take_profit_pct": round(tp_pct, 1),
                "distance_to_stop": round(p.profit_pct + sl_pct, 1),
                "is_t1_locked": p.today_buy_qty > 0,
            })
        
        # === 今日交易统计 ===
        today_buys = [t for t in self._timeline if t.get("action") == "buy"]
        today_sells = [t for t in self._timeline if t.get("action") == "sell"]
        profitable_sells = [t for t in today_sells if t.get("profit_pct", 0) > 0]
        losing_sells = [t for t in today_sells if t.get("profit_pct", 0) < 0]
        
        trade_stats = {
            "total_trades": len(today_buys) + len(today_sells),
            "buys": len(today_buys),
            "sells": len(today_sells),
            "win_trades": len(profitable_sells),
            "loss_trades": len(losing_sells),
            "win_rate": round(len(profitable_sells) / max(len(today_sells), 1) * 100, 1),
            "avg_profit_pct": round(
                sum(t.get("profit_pct", 0) for t in profitable_sells) / max(len(profitable_sells), 1), 2
            ) if profitable_sells else 0,
            "avg_loss_pct": round(
                sum(t.get("profit_pct", 0) for t in losing_sells) / max(len(losing_sells), 1), 2
            ) if losing_sells else 0,
        }
        
        # === 策略表现 ===
        strategy_performance = {}
        for t in self._timeline:
            strat = t.get("strategy", "unknown")
            if strat not in strategy_performance:
                strategy_performance[strat] = {"trades": 0, "wins": 0, "total_pnl": 0}
            strategy_performance[strat]["trades"] += 1
            if t.get("action") == "sell":
                pnl = t.get("profit_pct", 0)
                strategy_performance[strat]["total_pnl"] += pnl
                if pnl > 0:
                    strategy_performance[strat]["wins"] += 1
        
        # === 风控状态 ===
        risk_status = {
            "circuit_breaker_active": self._circuit_breaker.get("trading_paused", False),
            "circuit_breaker_reason": self._circuit_breaker.get("pause_reason", ""),
            "consecutive_losses": self._circuit_breaker.get("consecutive_losses", 0),
            "today_trades": self._circuit_breaker.get("today_trades", 0),
            "today_losses": self._circuit_breaker.get("today_losses", 0),
            "dry_run": self._dry_run,
        }
        
        # === 信号统计 ===
        signal_stats = {
            "total": len(self._active_signals),
            "new": len([s for s in self._active_signals if s.signal_status == "new"]),
            "executed": len([s for s in self._active_signals if s.signal_status == "executed"]),
            "skipped": len([s for s in self._active_signals if s.signal_status == "skipped"]),
            "expired": len([s for s in self._active_signals if s.signal_status == "expired"]),
            "filtered": len([s for s in self._active_signals if s.signal_status == "filtered"]),
        }
        
        return {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "account": account_summary,
            "positions": position_details,
            "trade_stats": trade_stats,
            "strategy_performance": strategy_performance,
            "risk_status": risk_status,
            "signal_stats": signal_stats,
            "scanner_stats": dict(self._stats),
            "sentiment": self._current_sentiment,
            "position_ratio": self._current_position_ratio,
        }


    # ==================== 收盘报告 ====================

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

