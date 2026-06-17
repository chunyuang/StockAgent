#!/usr/bin/env python3
"""
SimulatedBroker — 仿真撮合引擎

模拟真实交易所撮合规则:
- T+1: 当日买入不可卖出
- 涨跌停价格限制(不可市价买入涨停股/卖出跌停股)
- 停牌股不可交易
- 100股整手交易
- 手续费: 佣金万3(含规费)+印花税千1(卖出)
- 滑点: ±0.1%
- 撮合: 限价单 → 当日VWAP成交, 市价单 → 最新价

不依赖任何外部券商API, 纯Python+MongoDB实现
"""
import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK

logger = logging.getLogger("broker.simulated")


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    MARKET = "market"      # 市价单
    LIMIT = "limit"        # 限价单


class OrderStatus(Enum):
    PENDING = "pending"     # 待撮合
    FILLED = "filled"       # 已成交
    PARTIAL = "partial"     # 部分成交
    REJECTED = "rejected"   # 已拒绝
    CANCELED = "canceled"   # 已撤单
    ROLLED_BACK = "rolled_back"  # 【v2.9.96i】已回滚(人为后枢, 本位订单不计入成交)


@dataclass
class Order:
    """委托单"""
    order_id: str
    account_id: str
    ts_code: str
    stock_name: str
    side: OrderSide
    order_type: OrderType
    quantity: int           # 委托数量(股)
    price: float = 0.0      # 委托价格(市价单=0)
    filled_qty: int = 0     # 已成交数量
    filled_price: float = 0.0  # 成交均价
    status: OrderStatus = OrderStatus.PENDING
    reason: str = ""
    strategy: str = ""
    trade_date: str = ""
    create_time: str = ""
    fill_time: str = ""
    source: str = "auto"     # auto=自动交易 / manual=手动下单
    profit_pct: float = 0.0
    profit_amount: float = 0.0
    decision_trace: dict = field(default_factory=dict)  # 【v2.9.96】完整决策轨迹: 选股参数+风控参数+L1-L9+情绪+仓位


@dataclass
class Position:
    """持仓"""
    ts_code: str
    stock_name: str
    total_qty: int = 0      # 总持仓
    available_qty: int = 0  # 可卖数量(T+1: 今日买入不可卖)
    avg_cost: float = 0.0   # 平均成本
    current_price: float = 0.0
    profit_pct: float = 0.0
    today_buy_qty: int = 0  # 今日买入(不可卖)
    strategy: str = ""
    buy_date: str = ""       # 买入日期(YYYYMMDD)，用于超时强卖


@dataclass
class Account:
    """账户"""
    account_id: str
    total_assets: float = 1_000_000.0
    available_cash: float = 1_000_000.0
    frozen_cash: float = 0.0
    market_value: float = 0.0
    today_profit: float = 0.0
    total_profit: float = 0.0


class SimulatedBroker:
    """仿真撮合引擎 — 模拟真实交易所规则"""

    # 费用
    COMMISSION_RATE = 0.0003   # 【V50:佣金万3(含规费),与回测BUY_COMMISSION/SELL_COMMISSION对齐】
    STAMP_DUTY_RATE = 0.001    # 印花税千1(仅卖出)
    MIN_COMMISSION = 5.0       # 最低佣金5元
    SLIPPAGE_RATE = 0.002      # 【V50:滑点0.2%,与回测strategy_defaults对齐(原0.1%偏低)】

    # 限制
    LOT_SIZE = 100             # 整手
    KCB_LOT_SIZE = 200         # 科创板最小200股
    # 【v2.9.92w】从strategy_defaults读取，不硬编码(与回测对齐)
    MAX_POSITION_RATIO = GLOBAL_RISK.get("max_position_per_stock", 0.35)  # 单票最大仓位(回测35%)
    MAX_TOTAL_RATIO = GLOBAL_RISK.get("max_total_position", 0.75)       # 总仓位上限(回测75%)

    # 涨跌停比例
    LIMIT_RATIO_MAIN = 0.10       # 主板±10%
    LIMIT_RATIO_KCB = 0.20        # 科创板±20%
    LIMIT_RATIO_CYB = 0.20        # 创业板±20%
    LIMIT_RATIO_BJB = 0.30        # 北交所±30%
    LIMIT_RATIO_ST = 0.05         # ST股±5%

    def __init__(self, account_id: str = "default", initial_cash: float = 1_000_000, virtual_mode: bool = False):
        self.account = Account(account_id=account_id, total_assets=initial_cash, available_cash=initial_cash)
        self.positions: Dict[str, Position] = {}
        self.orders: List[Order] = []
        self._realtime_prices: Dict[str, float] = {}
        self._limit_prices: Dict[str, Dict] = {}  # ts_code → {upper, lower}
        self._stock_names: Dict[str, str] = {}  # ts_code → stock_name (ST判断用)
        self._suspended: set = set()  # 停牌股
        self._mongo_db = None  # MongoDB句柄(懒初始化)
        self._pending_save = False  # 标记有待保存的状态
        self._last_save_time = 0  # 上次保存时间(节流用)
        self._virtual_mode = virtual_mode  # 【v2.9.92s】replay/dry_run模式标记，防止覆盖实盘数据
        self._sync_mongo_client = None  # 【v2.9.97f】同步MongoDB客户端(用于关键写入,不依赖事件循环)
        self._sync_mongo_db = None      # 同步MongoDB数据库句柄
        self._today_rejected: set = set()  # 【v2.9.95f】当日已拒绝的ts_code去重缓存，避免同一股同日重复下单

    # ==================== 持久化 ====================

    async def _ensure_mongo(self) -> bool:
        """懒初始化MongoDB连接"""
        if self._mongo_db is not None:
            return True
        try:
            from core.managers import mongo_manager
            if not mongo_manager._client:
                await mongo_manager.initialize()
            self._mongo_db = mongo_manager.db
            return True
        except Exception as e:
            logger.warning(f"[BROKER] MongoDB连接失败: {e}")
            return False

    def _ensure_sync_mongo(self) -> bool:
        """【v2.9.97f】懒初始化同步MongoDB客户端(不依赖事件循环,可用于sync方法)"""
        if self._sync_mongo_db is not None:
            return True
        try:
            from pymongo import MongoClient as SyncClient
            from core.settings import settings
            # 复用同一连接配置,但用同步客户端
            uri = getattr(settings, 'MONGO_URI', 'mongodb://localhost:27017')
            self._sync_mongo_client = SyncClient(uri, serverSelectionTimeoutMS=2000)
            db_name = getattr(settings, 'MONGO_DB', 'stock_agent')
            self._sync_mongo_db = self._sync_mongo_client[db_name]
            return True
        except Exception as e:
            logger.warning(f"[BROKER] 同步MongoDB连接失败: {e}")
            return False

    def _sync_save_order_and_position(self, order, position) -> bool:
        """【v2.9.97f】同步写入单笔订单+持仓到MongoDB(关键路径,不依赖事件循环)
        
        解决: place_order是sync方法, create_task(save_state)不保证在崩溃前完成。
        此方法用pymongo同步客户端直接写入, 保证进程崩溃时交易数据不丢失。
        非关键数据(broker_accounts等)仍由异步save_state处理。
        """
        if self._virtual_mode:
            return True  # 虚拟模式不写
        if not self._ensure_sync_mongo():
            return False
        try:
            db = self._sync_mongo_db
            account_id = self.account.account_id
            
            # 1. 写入订单 (upsert by order_id)
            if order is not None:
                order_doc = {
                    "order_id": order.order_id,
                    "account_id": account_id,
                    "ts_code": order.ts_code,
                    "stock_name": order.stock_name,
                    "side": order.side.value if hasattr(order.side, 'value') else str(order.side),
                    "quantity": order.quantity,
                    "filled_qty": order.filled_qty,
                    "price": order.price,
                    "filled_price": order.filled_price,
                    "order_type": order.order_type.value if hasattr(order.order_type, 'value') else str(order.order_type),
                    "strategy": order.strategy,
                    "reason": order.reason,
                    "source": getattr(order, 'source', 'auto'),
                    "status": order.status.value if hasattr(order.status, 'value') else str(order.status),
                    "commission": getattr(order, 'commission', 0),
                    "stamp_duty": getattr(order, 'stamp_duty', 0),
                    "trade_date": order.trade_date,
                    "create_time": order.create_time,
                    "fill_time": order.fill_time,
                    "profit_pct": getattr(order, 'profit_pct', 0),
                    "profit_amount": getattr(order, 'profit_amount', 0),
                    "decision_trace": getattr(order, 'decision_trace', {}) or {},
                }
                db["broker_orders"].update_one(
                    {"order_id": order.order_id},
                    {"$set": order_doc},
                    upsert=True,
                )
            
            # 2. 写入/更新持仓 (upsert by ts_code)
            if position is not None:
                pos_doc = {
                    "account_id": account_id,
                    "ts_code": position.ts_code,
                    "stock_name": position.stock_name,
                    "total_qty": position.total_qty,
                    "available_qty": position.available_qty,
                    "today_buy_qty": position.today_buy_qty,
                    "avg_cost": position.avg_cost,
                    "current_price": position.current_price,
                    "strategy": position.strategy,
                    "buy_date": position.buy_date,
                    "stop_loss_price": getattr(position, 'stop_loss_price', 0),
                    "take_profit_price": getattr(position, 'take_profit_price', 0),
                }
                db["broker_positions"].update_one(
                    {"account_id": account_id, "ts_code": position.ts_code},
                    {"$set": pos_doc},
                    upsert=True,
                )
            
            # 3. 如果持仓qty=0, 删除
            if position is not None and position.total_qty <= 0:
                db["broker_positions"].delete_one(
                    {"account_id": account_id, "ts_code": position.ts_code}
                )
            
            return True
        except Exception as e:
            logger.error(f"[BROKER] 同步写入订单+持仓失败: {e}")
            return False

    async def save_state(self, force: bool = False, skip_if_virtual: bool = False) -> None:
        """持久化当前状态到MongoDB(带节流: 30秒内不重复保存, force=True跳过节流)
        
        Args:
            force: 跳过节流，强制保存
            skip_if_virtual: 如果是虚拟模式(replay/dry_run)，跳过保存防止覆盖实盘数据
        """
        # 【v2.9.92s】replay/dry_run模式的SimulatedBroker不应覆盖MongoDB实盘数据
        if skip_if_virtual or self._virtual_mode:
            logger.info("[BROKER] 跳过save_state: 虚拟模式(replay/dry_run)不应覆盖实盘数据")
            return True
        now = time.time()
        if not force and now - self._last_save_time < 30:
            logger.debug(f"[BROKER] save_state节流: {now - self._last_save_time:.0f}s < 30s")
            return True  # 节流: 30秒内不重复保存
        self._last_save_time = now

        if not await self._ensure_mongo():
            return False

        try:
            # 账户
            account_doc = self._build_account_doc()
            await self._mongo_db["broker_accounts"].update_one(
                {"account_id": self.account.account_id},
                {"$set": account_doc},
                upsert=True,
            )

            # 持仓
            await self._save_positions_to_mongo()

            # 今日订单
            await self._save_today_orders_to_mongo()

            return True
        except Exception as e:
            logger.error(f"[BROKER] 状态保存失败: {e}")
            return False

    def _build_account_doc(self) -> dict:
        """【v2.9.57提取】构建账户文档"""
        return {
            "account_id": self.account.account_id,
            "total_assets": self.account.total_assets,
            "available_cash": self.account.available_cash,
            "frozen_cash": self.account.frozen_cash,
            "market_value": self.account.market_value,
            "today_profit": self.account.today_profit,
            "total_profit": self.account.total_profit,
            "updated_at": datetime.now().isoformat(),
        }

    async def _save_positions_to_mongo(self) -> None:
        """【v2.9.57提取】持久化持仓到MongoDB"""
        positions_docs = []
        for ts_code, pos in self.positions.items():
            # 【v2.9.95f】买入时写入止损价/止盈价，确保scanner崩溃后止损监控不失效
            stop_loss_pct = GLOBAL_RISK.get("stop_loss_pct", 0.03) if GLOBAL_RISK else 0.03
            take_profit_pct = GLOBAL_RISK.get("take_profit_pct", 0.07) if GLOBAL_RISK else 0.07
            try:
                from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS
                strat_cfg = STRATEGY_CONFIGS.get(pos.strategy, {})
                stop_loss_pct = strat_cfg.get("stop_loss_pct", stop_loss_pct)
                take_profit_pct = strat_cfg.get("take_profit_pct", take_profit_pct)
            except Exception:
                pass

            positions_docs.append({
                "account_id": self.account.account_id,
                "ts_code": ts_code,
                "stock_name": pos.stock_name,
                "total_qty": pos.total_qty,
                "available_qty": pos.available_qty,
                "avg_cost": pos.avg_cost,
                "current_price": pos.current_price,
                "profit_pct": pos.profit_pct,
                "today_buy_qty": pos.today_buy_qty,
                "strategy": pos.strategy,
                "stop_loss_price": round(pos.avg_cost * (1 - stop_loss_pct), 2),
                "take_profit_price": round(pos.avg_cost * (1 + take_profit_pct), 2),
            })

        # Upsert持仓(避免并发重复)
        for doc in positions_docs:
            await self._mongo_db["broker_positions"].update_one(
                {"account_id": doc["account_id"], "ts_code": doc["ts_code"]},
                {"$set": doc},
                upsert=True,
            )

        # 清理已平仓的持仓(内存里没有但MongoDB还留着的)
        current_codes = set(self.positions.keys())
        await self._mongo_db["broker_positions"].delete_many({
            "account_id": self.account.account_id,
            "ts_code": {"$nin": list(current_codes)} if current_codes else {"$exists": True},
        })

    async def _save_today_orders_to_mongo(self) -> None:
        """【v2.9.57提取】持久化今日订单到MongoDB"""
        today = datetime.now().strftime("%Y%m%d")
        today_orders = [
            {
                "account_id": self.account.account_id,
                "order_id": o.order_id,
                "ts_code": o.ts_code,
                "stock_name": o.stock_name,
                "side": o.side.value,
                "order_type": o.order_type.value,
                "quantity": o.quantity,
                "price": o.price,
                "filled_qty": o.filled_qty,
                "filled_price": o.filled_price,
                "status": o.status.value,
                "strategy": o.strategy,
                "reason": o.reason,
                "trade_date": int(o.trade_date) if o.trade_date else 0,
                "create_time": o.create_time,
                "fill_time": o.fill_time,
                "profit_pct": o.profit_pct,
                "profit_amount": o.profit_amount,
                "source": o.source,
                "decision_trace": o.decision_trace if hasattr(o, 'decision_trace') else {},
            }
            for o in self.orders if o.trade_date == today
        ]
        if today_orders:
            # 【v2.9.92x】改用upsert防止并发重复写入(000517重复订单根因)
            # 旧逻辑: 先查existing_ids再insert_many，两个并发save_state都查到空集→重复insert
            # 新逻辑: 用update_one+upsert逐条写入，order_id唯一索引做最终保底
            for o in today_orders:
                await self._mongo_db["broker_orders"].update_one(
                    {"order_id": o["order_id"]},
                    {"$set": o},
                    upsert=True,
                )

    async def load_state(self) -> bool:
        """从MongoDB恢复状态(断电/重启后)"""
        if not await self._ensure_mongo():
            return False

        try:
            # 恢复账户
            await self._restore_account_from_mongo()

            # 恢复持仓
            await self._restore_positions_from_mongo()

            # 恢复今日订单
            await self._restore_orders_from_mongo()

            return True
        except Exception as e:
            logger.error(f"[BROKER] 状态恢复失败: {e}")
            return False

    async def _restore_account_from_mongo(self) -> None:
        """【v2.9.57提取】从MongoDB恢复账户"""
        account_doc = await self._mongo_db["broker_accounts"].find_one(
            {"account_id": self.account.account_id}
        )
        if account_doc:
            self.account.total_assets = account_doc.get("total_assets", self.account.total_assets)
            self.account.available_cash = account_doc.get("available_cash", self.account.available_cash)
            self.account.frozen_cash = account_doc.get("frozen_cash", 0)
            self.account.market_value = account_doc.get("market_value", 0)
            self.account.today_profit = account_doc.get("today_profit", 0)
            self.account.total_profit = account_doc.get("total_profit", 0)
            logger.info(f"[BROKER] 账户恢复: 资产{self.account.total_assets:.0f} 现金{self.account.available_cash:.0f}")

    async def _restore_positions_from_mongo(self) -> None:
        """【v2.9.57提取】从MongoDB恢复持仓"""
        cursor = self._mongo_db["broker_positions"].find(
            {"account_id": self.account.account_id}
        )
        loaded = 0
        async for doc in cursor:
            self.positions[doc["ts_code"]] = Position(
                ts_code=doc["ts_code"],
                stock_name=doc.get("stock_name", ""),
                total_qty=doc.get("total_qty", 0),
                available_qty=doc.get("available_qty", 0),
                avg_cost=doc.get("avg_cost", 0),
                current_price=doc.get("current_price", 0),
                profit_pct=doc.get("profit_pct", 0),
                today_buy_qty=doc.get("today_buy_qty", 0),
                strategy=doc.get("strategy", ""),
            )
            loaded += 1
        if loaded:
            logger.info(f"[BROKER] 持仓恢复: {loaded}只")

    async def _restore_orders_from_mongo(self) -> None:
        """【v2.9.57提取】从MongoDB恢复今日订单
        【v2.9.96c】去重保护: 多次调用load_state不会重复追加
        """
        today = datetime.now().strftime("%Y%m%d")
        # 【v2.9.96c】清除已存在的今日orders, 避免重复追加
        before_count = len(self.orders)
        self.orders = [o for o in self.orders if o.trade_date != today and o.trade_date != int(today) if hasattr(o, 'trade_date')]
        cleared = before_count - len(self.orders)
        if cleared > 0:
            logger.info(f"[BROKER] 恢复前清除今日内存orders: {cleared}笔")
        
        cursor = self._mongo_db["broker_orders"].find(
            {"account_id": self.account.account_id, "trade_date": {"$in": [today, int(today)]}}
        )
        loaded_orders = 0
        existing_ids = set(o.order_id for o in self.orders)  # 防御性
        async for doc in cursor:
            oid = doc["order_id"]
            if oid in existing_ids:
                continue  # 跳过重复
            order = Order(
                order_id=oid,
                account_id=doc.get("account_id", self.account.account_id),
                ts_code=doc["ts_code"],
                stock_name=doc.get("stock_name", ""),
                side=OrderSide(doc.get("side", "buy")),
                order_type=OrderType(doc.get("order_type", "market")),
                quantity=doc.get("quantity", 0),
                price=doc.get("price", 0),
                filled_qty=doc.get("filled_qty", 0),
                filled_price=doc.get("filled_price", 0),
                status=OrderStatus(doc.get("status", "filled")),
                strategy=doc.get("strategy", ""),
                reason=doc.get("reason", ""),
                decision_trace=doc.get("decision_trace", {}),
                trade_date=str(doc.get("trade_date", today)),
                create_time=doc.get("create_time", ""),
                source=doc.get("source", "auto"),
            )
            order.fill_time = doc.get("fill_time", "")
            self.orders.append(order)
            existing_ids.add(oid)
            loaded_orders += 1
        if loaded_orders:
            logger.info(f"[BROKER] 订单恢复: {loaded_orders}笔")

    def _calc_limit_prices(self, ts_code: str, pre_close: float) -> Dict[str, float]:
        """根据板块计算涨跌停价"""
        if pre_close <= 0:
            return {"upper": 0, "lower": 0}

        # 科创板688xxx: ±20%
        if ts_code.startswith('688'):
            ratio = 0.20
        # 北交所4xx/8xx.BJ: ±30%
        elif ts_code.startswith(('4', '8')) and ts_code.endswith('.BJ'):
            ratio = 0.30
        # 创业板300xxx: ±20%
        elif ts_code.startswith('300'):
            ratio = 0.20
        # 主板: ±10%
        else:
            ratio = 0.10

        # ST股: ±5% (从持仓stock_name或实时行情判断)
        stock_name = self._stock_names.get(ts_code, '')
        if 'ST' in stock_name or '*ST' in stock_name:
            ratio = 0.05

        upper = round(pre_close * (1 + ratio), 2)
        lower = round(pre_close * (1 - ratio), 2)
        return {"upper": upper, "lower": lower}

    def update_realtime(self, ts_code: str, price: float,
                        pre_close: float = None,
                        upper_limit: float = None, lower_limit: float = None,
                        suspended: bool = False, is_st: bool = False) -> None:
        """更新实时行情(由MarketScanner调用)"""
        self._realtime_prices[ts_code] = price

        # 自动计算涨跌停价
        if pre_close and pre_close > 0:
            calc = self._calc_limit_prices(ts_code, pre_close)
            if is_st:  # ST股±5%
                calc["upper"] = round(pre_close * 1.05, 2)
                calc["lower"] = round(pre_close * 0.95, 2)
            self._limit_prices[ts_code] = calc
        elif upper_limit is not None or lower_limit is not None:
            self._limit_prices[ts_code] = {
                "upper": upper_limit or price * 1.1,
                "lower": lower_limit or price * 0.9,
            }
        if suspended:
            self._suspended.add(ts_code)
        elif ts_code in self._suspended:
            self._suspended.discard(ts_code)
        
        # 自动检测停牌: pre_close>0但price=0 → 停牌
        if pre_close and pre_close > 0 and price <= 0:
            self._suspended.add(ts_code)
            logger.debug(f"[BROKER] {ts_code} 疑似停牌(price=0, pre_close={pre_close})")

        # 更新持仓价格
        if ts_code in self.positions:
            pos = self.positions[ts_code]
            pos.current_price = price
            if pos.avg_cost > 0:
                pos.profit_pct = (price - pos.avg_cost) / pos.avg_cost * 100

    async def refresh_close_prices(self) -> int:
        """【v2.9.92x】收盘后用MongoDB当日收盘价刷新持仓(解决收盘后current_price不更新问题)"""
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return 0
        
        from datetime import datetime
        today = int(datetime.now().strftime("%Y%m%d"))
        
        updated = 0
        for ts_code, pos in self.positions.items():
            try:
                doc = await mongo_manager.find_one(
                    "stock_daily_ak_full",
                    {"ts_code": ts_code, "trade_date": today},
                    {"_id": 0, "close": 1}
                )
                if doc and doc.get("close", 0) > 0:
                    close_price = doc["close"]
                    self._realtime_prices[ts_code] = close_price
                    pos.current_price = close_price
                    pos.profit_pct = (close_price - pos.avg_cost) / pos.avg_cost * 100 if pos.avg_cost > 0 else 0
                    updated += 1
            except Exception:
                pass
        
        if updated > 0:
            self._recalc_account()
            await self.save_state(force=True)
            logger.info(f"[BROKER] 收盘价刷新: {updated}只持仓已更新")
        
        return updated

    def get_account(self) -> Account:
        """获取账户信息"""
        self._recalc_account()
        return self.account

    def get_positions(self) -> List[Position]:
        """获取所有持仓"""
        return list(self.positions.values())

    def get_limit_prices(self, ts_code: str = None) -> Dict:
        """获取涨跌停价格(ts_code=None时返回全量dict)【v2.9.51:正式接口替代getattr(_limit_prices)】"""
        if ts_code is not None:
            return self._limit_prices.get(ts_code, {})
        return dict(self._limit_prices)

    def get_realtime_prices(self, ts_code: str = None) -> Dict:
        """获取实时价格(ts_code=None时返回全量dict)【v2.9.51:正式接口替代getattr(_realtime_prices)】"""
        if ts_code is not None:
            return self._realtime_prices.get(ts_code, 0)
        return dict(self._realtime_prices)

    def get_orders(self, trade_date: str = None) -> List[Order]:
        """获取委托"""
        if trade_date:
            return [o for o in self.orders if o.trade_date == trade_date]
        return self.orders

    def _reject_order(self, order: Order, reason: str) -> Tuple[bool, str, Order]:
        """拒绝委托并记录【v2.9.48:从place_order提取】"""
        order.status = OrderStatus.REJECTED
        order.reason = reason
        # 【v2.9.95f】去重: 同一ts_code同日已拒绝过则不再写入orders列表(防止786条重复rejected堆积)
        reject_key = f"{order.ts_code}:{order.side.value}"
        if reject_key in self._today_rejected:
            return False, reason, order  # 已拒绝过，不再append
        self._today_rejected.add(reject_key)
        self.orders.append(order)
        return False, reason, order

    def _validate_prechecks(
        self,
        ts_code: str,
        quantity: int,
    ) -> Optional[str]:
        """前置检查: 停牌+行情+整手, 返回None=通过, 否则=拒绝原因【v2.9.48:从place_order提取】"""
        # 1. 停牌
        if ts_code in self._suspended:
            return "停牌不可交易"

        # 2. 实时价格
        current_price = self._realtime_prices.get(ts_code, 0)
        if current_price <= 0:
            return "无实时行情"

        # 3. 整手
        lot_size = self.KCB_LOT_SIZE if ts_code.startswith('688') else self.LOT_SIZE
        if quantity % lot_size != 0 or quantity <= 0:
            return f"数量必须为{lot_size}的整数倍"

        return None  # 通过

    def _validate_and_adjust_buy(
        self,
        ts_code: str,
        quantity: int,
        current_price: float,
    ) -> Tuple[bool, str, int]:
        """买入检查+数量调整, 返回(ok, reason, adjusted_quantity)【v2.9.48:从place_order提取】"""
        lot_size = self.KCB_LOT_SIZE if ts_code.startswith('688') else self.LOT_SIZE

        # 【v2.9.92w】涨停可下单但成交不确定(与回测hit_probability对齐，与实盘一致)
        # 旧: 硬拒绝涨停买入 → 842笔首板打板全被拒
        # 新: 允许下单，在_execute_buy中模拟成交概率(按strategy_defaults的hit_probability)
        # 实盘中涨停价可以挂买单，能不能成交看排单情况
        limit_info = self._limit_prices.get(ts_code, {})
        at_limit_up = limit_info and current_price >= limit_info.get("upper", 999999)
        if at_limit_up:
            # 标记涨停买入，后续_execute_buy按概率决定是否成交
            pass

        # 仓位检查(【v2.9.84修复】估算金额含佣金, 避免扣费后资金不足)
        est_amount = quantity * current_price * (1 + self.COMMISSION_RATE)
        if est_amount > self.account.available_cash:
            quantity = int(self.account.available_cash / current_price / lot_size) * lot_size
            if quantity <= 0:
                return False, "可用资金不足", 0
            # 【v2.9.88修复】数量调整后重算est_amount, 避免后续单票仓位检查用过期估算
            est_amount = quantity * current_price * (1 + self.COMMISSION_RATE)

        # 单票仓位上限
        if self.account.total_assets > 0:
            single_max = self.account.total_assets * self.MAX_POSITION_RATIO
            existing = self.positions.get(ts_code)
            existing_value = existing.avg_cost * existing.total_qty if existing else 0
            if existing_value + est_amount > single_max:
                max_qty = int((single_max - existing_value) / current_price / lot_size) * lot_size
                quantity = max(0, min(quantity, max_qty))
                if quantity <= 0:
                    return False, "单票仓位超限", 0

        # 总仓位上限
        self._recalc_account()
        if self.account.market_value / max(self.account.total_assets, 1) > self.MAX_TOTAL_RATIO:
            return False, "总仓位超限", quantity

        return True, "", quantity

    def _validate_sell(
        self,
        ts_code: str,
        quantity: int,
        current_price: float,
    ) -> Tuple[bool, str, int]:
        """卖出检查+数量调整, 返回(ok, reason, adjusted_quantity)【v2.9.48:从place_order提取】"""
        pos = self.positions.get(ts_code)
        if not pos or pos.available_qty <= 0:
            reason = "无可用持仓(T+1限制)" if pos and pos.total_qty > 0 else "无持仓"
            return False, reason, quantity

        # 跌停不可市价卖出
        limit_info = self._limit_prices.get(ts_code, {})
        if limit_info and current_price <= limit_info.get("lower", 0):
            return False, "跌停不可卖出", quantity

        # 数量不可超过可卖
        quantity = min(quantity, pos.available_qty)
        return True, "", quantity

    def place_order(self, ts_code: str, stock_name: str,
                    side: str, quantity: int,
                    price: float = 0.0,
                    order_type: str = "market",
                    strategy: str = "",
                    reason: str = "",
                    source: str = "auto",
                    decision_trace: dict = None) -> Tuple[bool, str, Order]:
        """下单(编排方法: 前置检查→买入/卖出校验→撮合→执行)"""
        if stock_name:
            self._stock_names[ts_code] = stock_name

        order = self._create_order_instance(
            ts_code, stock_name, side, quantity, price, order_type, strategy, reason, source)
        order.decision_trace = decision_trace or {}

        # 前置检查
        reject_reason = self._validate_prechecks(ts_code, quantity)
        if reject_reason is not None:
            return self._reject_order(order, reject_reason)

        current_price = self._realtime_prices.get(ts_code, 0)

        # 买入校验
        side_enum = order.side
        if side_enum == OrderSide.BUY:
            ok, reject_reason, quantity = self._validate_and_adjust_buy(ts_code, quantity, current_price)
            if not ok:
                return self._reject_order(order, reject_reason)

        # 卖出校验
        elif side_enum == OrderSide.SELL:
            ok, reject_reason, quantity = self._validate_sell(ts_code, quantity, current_price)
            if not ok:
                return self._reject_order(order, reject_reason)

        # 撮合+执行
        return self._execute_order_fill(order, quantity, current_price, side_enum, strategy)

    def _execute_order_fill(
        self, order: Order, quantity: int, current_price: float,
        side_enum, strategy: str,
    ) -> Tuple[bool, str, Order]:
        """撮合+执行成交+更新持仓/资金+持久化"""
        order.quantity = quantity
        fill_price, commission, stamp_duty = self._match(order, current_price)

        if fill_price <= 0:
            return self._reject_order(order, "撮合失败")

        # 【v2.9.92w】涨停成交概率模拟(与回测hit_probability对齐)
        # 实盘中涨停可以下单但未必成交，这里按回测的成交概率模型模拟
        if side_enum == OrderSide.BUY:
            limit_info = self._limit_prices.get(order.ts_code, {})
            at_limit_up = limit_info and current_price >= limit_info.get("upper", 999999)
            if at_limit_up:
                import random
                from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS
                strat_cfg = STRATEGY_CONFIGS.get(strategy, {})
                params = strat_cfg.get("params", {})
                # 判断涨停类型和成交概率
                opening_pct = 0  # 简化：用实时数据无法精确判断开盘涨幅
                if hasattr(self, '_realtime_cache') and order.ts_code in (self._realtime_cache or {}):
                    rt = self._realtime_cache[order.ts_code]
                    pre_close = rt.get("pre_close", 0)
                    if pre_close > 0:
                        opening_pct = (current_price / pre_close - 1) * 100
                
                if opening_pct >= 8:
                    hit_prob = params.get("hit_probability_fast", 0.20)
                elif opening_pct >= 2:
                    hit_prob = params.get("hit_probability_normal", 0.45)
                else:
                    hit_prob = params.get("hit_probability_slow", 0.55)
                
                if random.random() > hit_prob:
                    return self._reject_order(order, f"涨停未成交(成交概率{hit_prob*100:.0f}%)")
                logger.info(f"[BROKER] 涨停成交! {order.ts_code} 概率{hit_prob*100:.0f}% 策略={strategy}")

        order.filled_qty = quantity
        order.filled_price = fill_price
        order.status = OrderStatus.FILLED
        order.fill_time = datetime.now().strftime("%H:%M:%S")
        total_cost = commission + stamp_duty

        if side_enum == OrderSide.BUY:
            self._execute_buy(order, fill_price, total_cost)
        else:
            self._execute_sell(order, fill_price, total_cost)

        self.orders.append(order)
        self._recalc_account()

        action = "买入" if side_enum == OrderSide.BUY else "卖出"
        logger.info(f"[BROKER] {action} {order.ts_code} {quantity}股@{fill_price:.2f} "
                     f"佣金{commission:.0f} 印花税{stamp_duty:.0f} ({strategy})")

        # 【v2.9.97f】同步写入关键数据(订单+持仓), 不依赖事件循环
        # 解决: create_task(save_state)不保证在崩溃前完成 → 进程崩溃时交易丢失
        pos = self.positions.get(order.ts_code)
        sync_ok = self._sync_save_order_and_position(order, pos)
        if not sync_ok:
            # 同步写入失败时仍走异步(降级, 但不会block交易)
            logger.warning(f"[BROKER] 同步写入失败, 降级到异步save_state")
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.save_state(force=True))
            except Exception:
                self._pending_save = True
        else:
            # 同步写入成功, 异步save_state仍需运行(broker_accounts等非关键数据)
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.save_state(force=True))
            except Exception:
                self._pending_save = True
        return True, f"{action}{quantity}股@{fill_price:.2f}", order

    def _create_order_instance(self, ts_code: str, stock_name: str,
                                side: str, quantity: int, price: float,
                                order_type: str, strategy: str, reason: str,
                                source: str) -> 'Order':
        """【v2.9.57提取】创建订单实例"""
        now = datetime.now()
        trade_date = now.strftime("%Y%m%d")
        order_id = f"ORD{now.strftime('%H%M%S')}{len(self.orders):04d}"

        side_enum = OrderSide.BUY if side == "buy" else OrderSide.SELL
        type_enum = OrderType.MARKET if order_type == "market" else OrderType.LIMIT

        return Order(
            order_id=order_id,
            account_id=self.account.account_id,
            ts_code=ts_code,
            stock_name=stock_name,
            side=side_enum,
            order_type=type_enum,
            quantity=quantity,
            price=price,
            strategy=strategy,
            reason=reason,
            trade_date=trade_date,
            create_time=now.strftime("%H:%M:%S"),
            source=source,
        )

    def _async_save_state(self) -> None:
        """【v2.9.57提取】异步持久化状态(不阻塞)"""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.save_state())
        except RuntimeError:
            # 没有running loop, 延迟保存(下次async上下文时save)
            self._pending_save = True
        except Exception as e:
            logger.debug(f"[BROKER] 异步保存失败: {e}")

    def _match(self, order: Order, current_price: float) -> Tuple[float, float, float]:
        """撮合引擎(动态滑点)【v2.9.61:滑点提取到_calc_dynamic_slippage】

        Returns: (fill_price, commission, stamp_duty)
        """
        slippage = self._calc_dynamic_slippage(order, current_price)

        if order.order_type == OrderType.MARKET:
            # 市价单: 用最新价 + 滑点
            if order.side == OrderSide.BUY:
                fill_price = current_price * (1 + slippage)
            else:
                fill_price = current_price * (1 - slippage)
        else:
            # 限价单: 检查是否触发
            if order.side == OrderSide.BUY:
                if current_price > order.price:
                    return 0, 0, 0
                fill_price = order.price
            else:
                if current_price < order.price:
                    return 0, 0, 0
                fill_price = order.price

        # 计算费用
        amount = fill_price * order.quantity
        commission = max(amount * self.COMMISSION_RATE, self.MIN_COMMISSION)
        stamp_duty = amount * self.STAMP_DUTY_RATE if order.side == OrderSide.SELL else 0

        return round(fill_price, 2), round(commission, 2), round(stamp_duty, 2)

    def _calc_dynamic_slippage(self, order: Order, current_price: float) -> float:
        """计算动态滑点【v2.9.61:从_match提取】

        滑点规则:
        - 基础: 0.1% (流动性充裕)
        - 涨停附近: 0.5% (涨停价附近买盘拥挤)
        - 大量成交: 0.3% (委托量>成交量10%)
        - 跌停卖出: 0.5% (跌停卖盘拥挤)
        """
        slippage = self.SLIPPAGE_RATE  # 默认0.2%

        limit_info = self._limit_prices.get(order.ts_code, {})
        if not limit_info:
            return slippage

        upper = limit_info.get("upper", 999999)
        lower = limit_info.get("lower", 0)

        if order.side == OrderSide.BUY:
            # 买入: 接近涨停加大滑点
            if current_price >= upper * 0.98:  # 距涨停2%以内
                slippage = 0.005  # 0.5%
            elif current_price >= upper * 0.95:  # 距涨停5%以内
                slippage = 0.003  # 0.3%
        else:
            # 卖出: 接近跌停加大滑点
            if current_price <= lower * 1.02:
                slippage = 0.005
            elif current_price <= lower * 1.05:
                slippage = 0.003

        return slippage

    def _execute_buy(self, order: Order, fill_price: float, total_cost: float) -> None:
        """执行买入"""
        # 买入成本含佣金, 计入avg_cost
        amount = fill_price * order.quantity + total_cost
        self.account.available_cash -= amount

        if order.ts_code in self.positions:
            pos = self.positions[order.ts_code]
            # 加仓: 重算均价(含佣金)
            total_cost_base = pos.avg_cost * pos.total_qty + fill_price * order.quantity + total_cost
            pos.total_qty += order.quantity
            pos.today_buy_qty += order.quantity  # T+1: 今日买入不可卖
            pos.avg_cost = total_cost_base / pos.total_qty
            pos.current_price = fill_price
            pos.strategy = order.strategy
        else:
            # 新仓: avg_cost含佣金
            avg_cost_with_fee = (fill_price * order.quantity + total_cost) / order.quantity
            self.positions[order.ts_code] = Position(
                ts_code=order.ts_code,
                stock_name=order.stock_name,
                total_qty=order.quantity,
                available_qty=0,  # T+1: 今日买入不可卖
                avg_cost=avg_cost_with_fee,
                current_price=fill_price,
                today_buy_qty=order.quantity,
                strategy=order.strategy,
                buy_date=order.trade_date,
            )

    def _execute_sell(self, order: Order, fill_price: float, total_cost: float) -> None:
        """执行卖出"""
        pos = self.positions.get(order.ts_code)
        if not pos:
            return

        # 计算本笔盈亏
        profit = (fill_price - pos.avg_cost) * order.quantity - total_cost
        # 【v2.9.91修复】profit_pct含佣金,与profit_amount对齐
        # 旧: profit_pct = (fill_price - avg_cost) / avg_cost * 100 (不含佣金)
        # 新: profit_pct = profit / (avg_cost * quantity) * 100 (含佣金,与profit_amount一致)
        profit_pct = (profit / (pos.avg_cost * order.quantity) * 100) if pos.avg_cost > 0 and order.quantity > 0 else 0
        profit_amount = profit
        # [v2.9.41] write pnl to order for broker_orders
        order.profit_pct = round(profit_pct, 2)
        order.profit_amount = round(profit_amount, 2)
        self.account.total_profit += profit
        self.account.today_profit += profit  # 【v2.9.88修复】今日盈亏需同步累加

        # 收回资金
        amount = fill_price * order.quantity - total_cost
        self.account.available_cash += amount

        # 更新持仓
        pos.available_qty -= order.quantity
        pos.total_qty -= order.quantity

        if pos.total_qty <= 0:
            del self.positions[order.ts_code]
        # 部分卖出: 盈亏已在上方计入total_profit

    def daily_settlement(self, trade_date: str = None) -> None:
        """
        每日结算: T+1解锁可卖

        前日买入的股票, 次日结算后可卖
        """
        for pos in self.positions.values():
            # 解锁T+1: 前日买入的变为可卖
            pos.available_qty = pos.total_qty
            pos.today_buy_qty = 0

        # 【v2.9.95f】重置当日拒绝缓存，允许次日重新尝试
        self._today_rejected.clear()

        # 重算账户
        self._recalc_account()
        self.account.today_profit = 0
        logger.info(f"[BROKER] 日结算: {len(self.positions)}持仓, 可用{self.account.available_cash:.0f}")

    def _recalc_account(self) -> None:
        """重算账户总值"""
        market_value = 0
        for pos in self.positions.values():
            if pos.current_price > 0:
                market_value += pos.current_price * pos.total_qty
            elif pos.avg_cost > 0:
                market_value += pos.avg_cost * pos.total_qty

        self.account.market_value = market_value
        self.account.total_assets = self.account.available_cash + market_value

    def get_today_trades(self) -> List[Dict]:
        """获取今日成交"""
        today = datetime.now().strftime("%Y%m%d")
        return [{
            "order_id": o.order_id,
            "time": o.fill_time or o.create_time,
            "ts_code": o.ts_code,
            "stock_name": o.stock_name,
            "side": o.side.value,
            "quantity": o.filled_qty,
            "price": o.filled_price,
            "amount": o.filled_price * o.filled_qty,
            "strategy": o.strategy,
            "reason": o.reason,
            "status": o.status.value,
            "source": o.source,
        } for o in self.orders if o.trade_date == today and o.status == OrderStatus.FILLED]
