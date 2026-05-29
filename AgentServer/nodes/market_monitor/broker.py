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
    MAX_POSITION_RATIO = 0.15  # 单票最大15%仓位
    MAX_TOTAL_RATIO = 0.7      # 总仓位上限70%

    # 涨跌停比例
    LIMIT_RATIO_MAIN = 0.10       # 主板±10%
    LIMIT_RATIO_KCB = 0.20        # 科创板±20%
    LIMIT_RATIO_CYB = 0.20        # 创业板±20%
    LIMIT_RATIO_BJB = 0.30        # 北交所±30%
    LIMIT_RATIO_ST = 0.05         # ST股±5%

    def __init__(self, account_id: str = "default", initial_cash: float = 1_000_000):
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

    # ==================== 持久化 ====================

    async def _ensure_mongo(self):
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

    async def save_state(self, force: bool = False):
        """持久化当前状态到MongoDB(带节流: 30秒内不重复保存, force=True跳过节流)"""
        now = time.time()
        if not force and hasattr(self, '_last_save_time') and now - self._last_save_time < 30:
            logger.debug(f"[BROKER] save_state节流: {now - self._last_save_time:.0f}s < 30s")
            return True  # 节流: 30秒内不重复保存
        self._last_save_time = now

        if not await self._ensure_mongo():
            return False

        try:
            # 账户
            account_doc = {
                "account_id": self.account.account_id,
                "total_assets": self.account.total_assets,
                "available_cash": self.account.available_cash,
                "frozen_cash": self.account.frozen_cash,
                "market_value": self.account.market_value,
                "today_profit": self.account.today_profit,
                "total_profit": self.account.total_profit,
                "updated_at": datetime.now().isoformat(),
            }
            await self._mongo_db["broker_accounts"].update_one(
                {"account_id": self.account.account_id},
                {"$set": account_doc},
                upsert=True,
            )

            # 持仓
            positions_docs = []
            for ts_code, pos in self.positions.items():
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

            # 今日订单(追加,不删)
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
                    "trade_date": o.trade_date,
                    "create_time": o.create_time,
                    "fill_time": getattr(o, 'fill_time', ''),
                    "source": getattr(o, 'source', 'auto'),
                }
                for o in self.orders if o.trade_date == today
            ]
            if today_orders:
                existing_ids = set()
                async for doc in self._mongo_db["broker_orders"].find(
                    {"account_id": self.account.account_id, "trade_date": today},
                    {"order_id": 1}
                ):
                    existing_ids.add(doc["order_id"])
                new_orders = [o for o in today_orders if o["order_id"] not in existing_ids]
                if new_orders:
                    await self._mongo_db["broker_orders"].insert_many(new_orders)

            return True
        except Exception as e:
            logger.error(f"[BROKER] 状态保存失败: {e}")
            return False

    async def load_state(self) -> bool:
        """从MongoDB恢复状态(断电/重启后)"""
        if not await self._ensure_mongo():
            return False

        try:
            # 恢复账户
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

            # 恢复持仓
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

            # 恢复今日订单
            today = datetime.now().strftime("%Y%m%d")
            cursor = self._mongo_db["broker_orders"].find(
                {"account_id": self.account.account_id, "trade_date": today}
            )
            loaded_orders = 0
            async for doc in cursor:
                order = Order(
                    order_id=doc["order_id"],
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
                    trade_date=doc.get("trade_date", today),
                    create_time=doc.get("create_time", ""),
                    source=doc.get("source", "auto"),
                )
                order.fill_time = doc.get("fill_time", "")
                self.orders.append(order)
                loaded_orders += 1
            if loaded_orders:
                logger.info(f"[BROKER] 订单恢复: {loaded_orders}笔")

            return True
        except Exception as e:
            logger.error(f"[BROKER] 状态恢复失败: {e}")
            return False

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
                        suspended: bool = False, is_st: bool = False):
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

    def get_account(self) -> Account:
        """获取账户信息"""
        self._recalc_account()
        return self.account

    def get_positions(self) -> List[Position]:
        """获取所有持仓"""
        return list(self.positions.values())

    def get_orders(self, trade_date: str = None) -> List[Order]:
        """获取委托"""
        if trade_date:
            return [o for o in self.orders if o.trade_date == trade_date]
        return self.orders

    def place_order(self, ts_code: str, stock_name: str,
                    side: str, quantity: int,
                    price: float = 0.0,
                    order_type: str = "market",
                    strategy: str = "",
                    reason: str = "",
                    source: str = "auto") -> Tuple[bool, str, Order]:
        """
        下单

        Args:
            ts_code: 股票代码
            stock_name: 股票名称
        """
        # 记录stock_name用于ST判断
        if stock_name:
            self._stock_names[ts_code] = stock_name

        """
        Args:
            side: buy/sell
            quantity: 委托数量(股)
            price: 委托价格(市价单=0)
            order_type: market/limit
            strategy: 策略名
            reason: 下单原因

        Returns:
            (success, message, order)
        """
        now = datetime.now()
        trade_date = now.strftime("%Y%m%d")
        order_id = f"ORD{now.strftime('%H%M%S')}{len(self.orders):04d}"

        side_enum = OrderSide.BUY if side == "buy" else OrderSide.SELL
        type_enum = OrderType.MARKET if order_type == "market" else OrderType.LIMIT

        order = Order(
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

        # ==================== 前置检查 ====================

        # 1. 停牌检查
        if ts_code in self._suspended:
            order.status = OrderStatus.REJECTED
            order.reason = "停牌不可交易"
            self.orders.append(order)
            return False, "停牌不可交易", order

        # 2. 实时价格检查
        current_price = self._realtime_prices.get(ts_code, 0)
        if current_price <= 0:
            order.status = OrderStatus.REJECTED
            order.reason = "无实时行情"
            self.orders.append(order)
            return False, "无实时行情", order

        # 3. 整手检查
        lot_size = self.KCB_LOT_SIZE if ts_code.startswith('688') else self.LOT_SIZE
        if quantity % lot_size != 0 or quantity <= 0:
            order.status = OrderStatus.REJECTED
            order.reason = f"数量必须为{lot_size}的整数倍"
            self.orders.append(order)
            return False, f"数量必须为{lot_size}的整数倍", order

        # ==================== 买入检查 ====================
        if side_enum == OrderSide.BUY:
            # 4. 涨停不可市价买入
            limit_info = self._limit_prices.get(ts_code, {})
            if limit_info and current_price >= limit_info.get("upper", 999999):
                order.status = OrderStatus.REJECTED
                order.reason = "涨停不可买入"
                self.orders.append(order)
                return False, "涨停不可买入", order

            # 5. 仓位检查
            est_amount = quantity * current_price
            if est_amount > self.account.available_cash:
                # 缩减到可用现金能买到的数量
                quantity = int(self.account.available_cash / current_price / lot_size) * lot_size
                if quantity <= 0:
                    order.status = OrderStatus.REJECTED
                    order.reason = "可用资金不足"
                    self.orders.append(order)
                    return False, "可用资金不足", order

            # 6. 单票仓位上限
            if self.account.total_assets > 0:
                single_max = self.account.total_assets * self.MAX_POSITION_RATIO
                existing = self.positions.get(ts_code)
                existing_value = existing.avg_cost * existing.total_qty if existing else 0
                if existing_value + est_amount > single_max:
                    max_qty = int((single_max - existing_value) / current_price / lot_size) * lot_size
                    quantity = max(0, min(quantity, max_qty))
                    if quantity <= 0:
                        order.status = OrderStatus.REJECTED
                        order.reason = "单票仓位超限"
                        self.orders.append(order)
                        return False, "单票仓位超限", order

            # 7. 总仓位上限
            self._recalc_account()
            if self.account.market_value / max(self.account.total_assets, 1) > self.MAX_TOTAL_RATIO:
                order.status = OrderStatus.REJECTED
                order.reason = "总仓位超限"
                self.orders.append(order)
                return False, "总仓位超限", order

        # ==================== 卖出检查 ====================
        elif side_enum == OrderSide.SELL:
            pos = self.positions.get(ts_code)
            if not pos or pos.available_qty <= 0:
                order.status = OrderStatus.REJECTED
                order.reason = "无可用持仓(T+1限制)" if pos and pos.total_qty > 0 else "无持仓"
                self.orders.append(order)
                return False, order.reason, order

            # 跌停不可市价卖出
            limit_info = self._limit_prices.get(ts_code, {})
            if limit_info and current_price <= limit_info.get("lower", 0):
                order.status = OrderStatus.REJECTED
                order.reason = "跌停不可卖出"
                self.orders.append(order)
                return False, "跌停不可卖出", order

            # 数量不可超过可卖
            quantity = min(quantity, pos.available_qty)

        # ==================== 撮合 ====================
        order.quantity = quantity  # 可能被调整
        fill_price, commission, stamp_duty = self._match(order, current_price)

        if fill_price <= 0:
            order.status = OrderStatus.REJECTED
            order.reason = "撮合失败"
            self.orders.append(order)
            return False, "撮合失败", order

        # 成交
        order.filled_qty = quantity
        order.filled_price = fill_price
        order.status = OrderStatus.FILLED
        order.fill_time = datetime.now().strftime("%H:%M:%S")
        total_cost = commission + stamp_duty

        # ==================== 更新持仓/资金 ====================
        if side_enum == OrderSide.BUY:
            self._execute_buy(order, fill_price, total_cost)
        else:
            self._execute_sell(order, fill_price, total_cost)

        self.orders.append(order)
        self._recalc_account()

        action = "买入" if side_enum == OrderSide.BUY else "卖出"
        logger.info(f"[BROKER] {action} {ts_code} {quantity}股@{fill_price:.2f} "
                     f"佣金{commission:.0f} 印花税{stamp_duty:.0f} ({strategy})")

        # 持久化(异步, 不阻塞)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.save_state())
        except RuntimeError:
            # 没有running loop, 延迟保存(下次async上下文时save)
            self._pending_save = True
        except Exception as e:
            logger.debug(f"[BROKER] 异步保存失败: {e}")

        return True, f"{action}{quantity}股@{fill_price:.2f}", order

    def _match(self, order: Order, current_price: float) -> Tuple[float, float, float]:
        """
        撮合引擎(动态滑点)
        
        滑点规则:
        - 基础: 0.1% (流动性充裕)
        - 涨停附近: 0.5% (涨停价附近买盘拥挤)
        - 大量成交: 0.3% (委托量>成交量10%)
        - 跌停卖出: 0.5% (跌停卖盘拥挤)
        
        Returns: (fill_price, commission, stamp_duty)
        """
        # 动态滑点
        slippage = self.SLIPPAGE_RATE  # 默认0.1%
        
        # 涨停/跌停附近加大滑点
        limit_info = self._limit_prices.get(order.ts_code, {})
        if limit_info:
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

    def _execute_buy(self, order: Order, fill_price: float, total_cost: float):
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

    def _execute_sell(self, order: Order, fill_price: float, total_cost: float):
        """执行卖出"""
        pos = self.positions.get(order.ts_code)
        if not pos:
            return

        # 计算本笔盈亏
        profit = (fill_price - pos.avg_cost) * order.quantity - total_cost
        self.account.total_profit += profit

        # 收回资金
        amount = fill_price * order.quantity - total_cost
        self.account.available_cash += amount

        # 更新持仓
        pos.available_qty -= order.quantity
        pos.total_qty -= order.quantity

        if pos.total_qty <= 0:
            del self.positions[order.ts_code]
        # 部分卖出: 盈亏已在上方计入total_profit

    def daily_settlement(self, trade_date: str = None):
        """
        每日结算: T+1解锁可卖

        前日买入的股票, 次日结算后可卖
        """
        for pos in self.positions.values():
            # 解锁T+1: 前日买入的变为可卖
            pos.available_qty = pos.total_qty
            pos.today_buy_qty = 0

        # 重算账户
        self._recalc_account()
        self.account.today_profit = 0
        logger.info(f"[BROKER] 日结算: {len(self.positions)}持仓, 可用{self.account.available_cash:.0f}")

    def _recalc_account(self):
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
            "source": getattr(o, 'source', 'auto'),
        } for o in self.orders if o.trade_date == today and o.status == OrderStatus.FILLED]
