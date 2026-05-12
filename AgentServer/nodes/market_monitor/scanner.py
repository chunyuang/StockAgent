#!/usr/bin/env python3
"""
MarketScanner — 超短量化市场扫描器

核心: 把回测引擎的选股逻辑搬到实时数据上跑
- 每30秒扫描全市场(量脉批量行情)
- 合并日级因子(盘前预加载) + 实时因子(盘中提取)
- 策略筛选(复用 _build_strategy_filter_conditions)
- 信号→模拟执行→止损止盈
"""
import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

import pandas as pd

from nodes.market_monitor.broker import SimulatedBroker

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
    stop_loss_pct: float = -5.0
    take_profit_pct: float = 7.0
    hold_minutes: int = 0
    should_sell: bool = False
    sell_reason: str = ""


class MarketScanner:
    """超短量化市场扫描器"""

    # 扫描配置
    SCAN_INTERVAL = 30  # 秒
    BATCH_SIZE = 20     # 量脉批量行情每批20只
    MAX_POSITIONS = 10  # 最大持仓数
    MAX_POSITION_RATIO = 0.7  # 最大仓位比例

    # 交易模式
    MODE_SIMULATED = "simulated"  # 内置仿真撮合
    MODE_GM = "gm"                # 掘金量化

    def __init__(self, account_id: str = "default", config: Dict = None):
        self.account_id = account_id
        self.config = config or {}

        # 状态
        self._is_running = False
        self._task: Optional[asyncio.Task] = None
        self._scan_count = 0
        self._last_scan_time = ""

        # 数据
        self._liangmai = None
        self._daily_factors_df: Optional[pd.DataFrame] = None
        self._realtime_cache: Dict[str, Dict] = {}  # ts_code → 实时行情
        self._all_codes: List[str] = []  # 全市场代码

        # 撮合引擎: 根据模式选择
        trade_mode = self.config.get("trade_mode", self.MODE_SIMULATED)
        self._trade_mode = trade_mode
        initial_cash = self.config.get("initial_cash", 1_000_000)

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
        else:
            # 内置仿真模式
            self._broker = SimulatedBroker(account_id=account_id, initial_cash=initial_cash)
            self._gm_broker = None
            logger.info(f"[SCANNER] 交易模式: 内置仿真撮合")

        # 信号
        self._active_signals: List[ScanSignal] = []
        self._timeline: List[Dict] = []  # 今日交易时间线

        # 统计
        self._stats = {
            "scans": 0,
            "signals_found": 0,
            "trades_executed": 0,
            "stop_losses": 0,
            "take_profits": 0,
            "stocks_scanned": 0,
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
        }

    def get_signals(self) -> List[Dict]:
        return [self._signal_to_dict(s) for s in self._active_signals]

    def get_positions(self) -> List[Dict]:
        if self._trade_mode == self.MODE_GM and self._gm_broker:
            return self._gm_broker.get_positions()
        return [{
            "ts_code": p.ts_code, "stock_name": p.stock_name,
            "strategy": p.strategy, "shares": p.total_qty,
            "available_qty": p.available_qty,
            "cost_price": round(p.avg_cost, 2),
            "current_price": round(p.current_price, 2),
            "profit_pct": round(p.profit_pct, 2),
            "today_buy": p.today_buy_qty,
        } for p in self._broker.get_positions()]

    def get_timeline(self) -> List[Dict]:
        return list(self._timeline)

    def update_strategy_config(self, strategy_id: str, config: Dict):
        """运行时更新策略配置(来自前端策略配置页)"""
        if "strategy_overrides" not in self.config:
            self.config["strategy_overrides"] = {}
        self.config["strategy_overrides"][strategy_id] = config
        logger.info(f"[SCANNER] 策略配置更新: {strategy_id} enabled={config.get('enabled')}")

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

        # 盘前准备
        await self.premarket_prepare(trade_date)

        self._is_running = True
        self._task = asyncio.create_task(self._scan_loop(trade_date))
        logger.info(f"[SCANNER] 启动, account={self.account_id}, date={trade_date}")
        return {"success": True, "message": "扫描器启动成功"}

    async def stop(self):
        """停止扫描"""
        self._is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # 关闭量脉
        if self._liangmai:
            await self._liangmai.close()
            self._liangmai = None
        logger.info("[SCANNER] 已停止")
        return {"success": True, "message": "扫描器已停止"}

    # ==================== 盘前准备 ====================

    async def premarket_prepare(self, trade_date: str):
        """盘前: 加载全市场代码 + 预加载日级因子"""
        logger.info(f"[SCANNER] 盘前准备 {trade_date}")

        # 1. 获取全市场代码
        await self._load_stock_list()

        # 2. 预加载前日因子(ma5/rsi/macd/boll/atr等需要历史数据的因子)
        await self._load_daily_factors(trade_date)

        # 3. 加载当前持仓
        await self._load_positions()

        logger.info(f"[SCANNER] 准备完成: {len(self._all_codes)}只股票, "
                     f"{len(self._daily_factors_df) if self._daily_factors_df is not None else 0}条因子")

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
        """加载当前持仓(从broker获取, 初始为空)"""
        # SimulatedBroker 内存管理, 无需从MongoDB加载
        logger.info(f"[SCANNER] 持仓: {len(self._broker.get_positions())}个")

    # ==================== 扫描循环 ====================

    async def _scan_loop(self, trade_date: str):
        """主扫描循环"""
        settled = False  # 今日是否已结算

        try:
            while self._is_running:
                now = datetime.now()
                ct = now.strftime("%H:%M")

                # 仅在交易时间扫描
                if "09:30" <= ct <= "15:00":
                    settled = False  # 交易时间内重置结算标记
                    await self.scan_once(trade_date)
                    await asyncio.sleep(self.SCAN_INTERVAL)
                elif ct >= "15:05" and not settled and self._broker:
                    # 收盘后自动结算(T+1解锁)
                    self._broker.daily_settlement(trade_date)
                    settled = True
                    logger.info("[SCANNER] 收盘自动结算完成")
                    await asyncio.sleep(60)
                else:
                    # 非交易时间, 降低频率
                    await asyncio.sleep(60)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[SCANNER] 异常: {e}", exc_info=True)
            self._is_running = False

    async def scan_once(self, trade_date: str):
        """单次扫描"""
        t0 = time.time()
        self._scan_count += 1
        scan_time = datetime.now().strftime("%H:%M:%S")

        logger.info(f"[SCAN #{self._scan_count}] 开始扫描 {scan_time}")

        # Step 1: 获取实时行情
        realtime_data = await self._fetch_realtime_batch()

        # Step 2: 合并日级因子+实时数据
        merged_df = self._merge_factors(realtime_data)

        # Step 3: 策略筛选
        new_signals = await self._apply_strategies(merged_df, trade_date)

        # Step 4: 增量更新信号
        await self._update_signals(new_signals, scan_time)

        # Step 5: 持仓检查(止损止盈)
        await self._check_positions(realtime_data, trade_date)

        # Step 6: 更新broker实时价格(用于持仓估值和涨跌停判断)
        for ts_code, rt in realtime_data.items():
            self._broker.update_realtime(
                ts_code=ts_code,
                price=rt.get("price", 0),
                pre_close=rt.get("pre_close", 0),
            )

        elapsed = time.time() - t0
        self._last_scan_time = scan_time
        self._stats["scans"] += 1
        self._stats["stocks_scanned"] = len(realtime_data)

        logger.info(f"[SCAN #{self._scan_count}] 完成: "
                     f"{len(realtime_data)}只 | {len(self._active_signals)}信号 | "
                     f"{elapsed:.1f}秒")

    # ==================== 实时行情 ====================

    async def _fetch_realtime_batch(self) -> Dict[str, Dict]:
        """批量获取实时行情(量脉)"""
        if not self._liangmai:
            try:
                from core.data_fetchers.liangmai_client import LiangMaiClient
                self._liangmai = LiangMaiClient()
                await self._liangmai.initialize()
            except Exception as e:
                logger.error(f"[REALTIME] 量脉初始化失败: {e}")
                return {}

        realtime = {}
        codes = self._all_codes

        # 量脉 stock_realtime_multi 一次20只
        for i in range(0, len(codes), self.BATCH_SIZE):
            batch = codes[i:i + self.BATCH_SIZE]
            # 转换格式: 600519.SH → 600519 (量脉用6位代码)
            short_codes = [c.split('.')[0] for c in batch]

            try:
                result = await self._liangmai.get_realtime_multi(short_codes)
                if result:
                    for item in result:
                        # 找回原始ts_code
                        dm = item.get("dm", "")
                        ts_code = self._short_to_ts_code(dm)
                        if ts_code:
                            realtime[ts_code] = {
                                "price": float(item.get("p", 0)),
                                "pct_chg": float(item.get("zdf", 0)),
                                "volume_ratio": float(item.get("lb", 0)),
                                "turnover_rate": float(item.get("hs", 0)),
                                "circ_mv": float(item.get("lt", 0)),  # 流通市值(万)
                                "open": float(item.get("o", 0)),
                                "high": float(item.get("h", 0)),
                                "low": float(item.get("l", 0)),
                                "pre_close": float(item.get("pc", 0)),
                                "name": item.get("mc", ""),
                            }
            except Exception as e:
                logger.warning(f"[REALTIME] 批次{i//self.BATCH_SIZE}失败: {e}")

            # 频率控制: 120次/分钟
            await asyncio.sleep(0.5)

        self._realtime_cache = realtime
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
        """获取策略有效配置(默认+前端覆盖)"""
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
        """获取策略级风控参数"""
        from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK
        cfg = self._get_effective_strategy_config(strategy_key)
        risk = dict(GLOBAL_RISK)  # 全局兜底
        risk.update(cfg.get("riskParams", {}))  # 策略级覆盖
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
                    reason=f"{strategy_name}筛选",
                    scan_time=datetime.now().strftime("%H:%M:%S"),
                    factors={k: row.get(k, 0) for k in
                             ["pct_chg", "volume_ratio", "turnover_rate", "circ_mv",
                              "ma5", "rsi_6", "is_limit_up", "limit_up_count"]
                             if k in row.index},
                ))

        return signals

    # ==================== 信号管理 ====================

    async def _update_signals(self, new_signals: List[ScanSignal], scan_time: str):
        """增量更新信号"""
        # 去重: 已存在的信号不重复
        existing_codes = {s.ts_code for s in self._active_signals}
        added = []

        for sig in new_signals:
            if sig.ts_code not in existing_codes:
                self._active_signals.append(sig)
                existing_codes.add(sig.ts_code)
                added.append(sig)

        # 过期信号: 超过5分钟没刷新的信号移除
        # (简化: 每次扫描重建, 不做时间过期)

        if added:
            self._stats["signals_found"] += len(added)
            logger.info(f"[SIGNAL] 新增{len(added)}个信号: "
                         f"{', '.join(s.ts_code for s in added[:5])}")

            # 推送新信号
            await self._push_signals(added)

            # 执行新信号
            await self._execute_signals(added)

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

    async def _execute_signals(self, signals: List[ScanSignal]):
        """执行信号(SimulatedBroker撮合)"""
        stop_loss = self.config.get("stop_loss", -5.0)
        take_profit = self.config.get("take_profit", 7.0)

        for sig in signals:
            if len(self._broker.get_positions()) >= self.MAX_POSITIONS:
                logger.info(f"[EXEC] 已达最大持仓{self.MAX_POSITIONS}, 跳过")
                break

            if sig.price <= 0:
                continue

            # 计算买入量: 单票最大15%仓位
            acct = self._broker.get_account()
            max_amount = acct.available_cash * 0.3
            shares = int(max_amount / sig.price / 100) * 100
            if shares <= 0:
                continue

            # 更新实时价格到broker
            self._broker.update_realtime(sig.ts_code, sig.price)

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
                })
                self._stats["trades_executed"] += 1
                logger.info(f"[EXEC] 买入 {sig.ts_code} {shares}股@{order.filled_price:.2f} ({sig.strategy_name})")
            else:
                logger.warning(f"[EXEC] 买入被拒 {sig.ts_code}: {msg}")

    # ==================== 持仓检查 ====================

    async def _check_positions(self, realtime_data: Dict[str, Dict], trade_date: str):
        """止损止盈检查(策略级风控参数)"""
        to_sell = []
        for pos in self._broker.get_positions():
            # 更新实时价格
            if pos.ts_code in realtime_data:
                self._broker.update_realtime(pos.ts_code, realtime_data[pos.ts_code].get("price", pos.current_price))

            # 获取策略级风控参数
            risk = self._get_strategy_risk(pos.strategy)
            stop_loss_pct = -risk.get("stop_loss_pct", 0.03) * 100   # 转为负百分比
            take_profit_pct = risk.get("take_profit_pct", 0.07) * 100  # 转为正百分比

            # 检查止损/止盈
            if pos.profit_pct <= stop_loss_pct:
                to_sell.append((pos, f"止损 {pos.profit_pct:.1f}%"))
            elif pos.profit_pct >= take_profit_pct:
                to_sell.append((pos, f"止盈 {pos.profit_pct:.1f}%"))

        # 执行卖出
        for pos, reason in to_sell:
            if pos.available_qty <= 0:
                continue  # T+1: 今日买入不可卖

            self._broker.update_realtime(pos.ts_code, pos.current_price)
            ok, msg, order = self._broker.place_order(
                ts_code=pos.ts_code,
                stock_name=pos.stock_name,
                side="sell",
                quantity=pos.available_qty,
                price=pos.current_price,
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
                    "shares": pos.available_qty,
                    "price": order.filled_price,
                    "reason": reason,
                    "profit_pct": round(pos.profit_pct, 2),
                })
                if "止损" in reason:
                    self._stats["stop_losses"] += 1
                else:
                    self._stats["take_profits"] += 1
                logger.info(f"[RISK] {reason}: {pos.ts_code} {pos.available_qty}股@{order.filled_price:.2f}")

    # ==================== 工具方法 ====================

    @staticmethod
    def _signal_to_dict(s: ScanSignal) -> Dict:
        return {
            "ts_code": s.ts_code, "stock_name": s.stock_name,
            "strategy": s.strategy, "strategy_name": s.strategy_name,
            "signal_type": s.signal_type, "price": s.price,
            "pct_chg": round(s.pct_chg, 2),
            "volume_ratio": round(s.volume_ratio, 2),
            "turnover_rate": round(s.turnover_rate, 2),
            "is_limit_up": s.is_limit_up,
            "limit_up_count": s.limit_up_count,
            "confidence": s.confidence, "reason": s.reason,
            "scan_time": s.scan_time, "factors": s.factors,
        }

    @staticmethod
    def _position_to_dict(p: PositionStatus) -> Dict:
        return {
            "ts_code": p.ts_code, "stock_name": p.stock_name,
            "strategy": p.strategy, "shares": p.shares,
            "cost_price": round(p.cost_price, 2),
            "current_price": round(p.current_price, 2),
            "profit_pct": round(p.profit_pct, 2),
            "stop_loss_pct": p.stop_loss_pct,
            "take_profit_pct": p.take_profit_pct,
            "should_sell": p.should_sell, "sell_reason": p.sell_reason,
        }
