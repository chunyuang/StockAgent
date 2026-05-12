#!/usr/bin/env python3
"""
SimulatedBroker — 仿真撮合引擎

模拟真实交易所撮合规则:
- T+1: 当日买入不可卖出
- 涨跌停价格限制(不可市价买入涨停股/卖出跌停股)
- 停牌股不可交易
- 100股整手交易
- 手续费: 佣金万2+印花税千1(卖出)
- 滑点: ±0.1%
- 撮合: 限价单 → 当日VWAP成交, 市价单 → 最新价

不依赖任何外部券商API, 纯Python+MongoDB实现
"""
import asyncio
import logging
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
    COMMISSION_RATE = 0.0002   # 佣金万2
    STAMP_DUTY_RATE = 0.001    # 印花税千1(仅卖出)
    MIN_COMMISSION = 5.0       # 最低佣金5元
    SLIPPAGE_RATE = 0.001      # 滑点0.1%

    # 限制
    LOT_SIZE = 100             # 整手
    MAX_POSITION_RATIO = 0.15  # 单票最大15%仓位
    MAX_TOTAL_RATIO = 0.7      # 总仓位上限70%

    def __init__(self, account_id: str = "default", initial_cash: float = 1_000_000):
        self.account = Account(account_id=account_id, total_assets=initial_cash, available_cash=initial_cash)
        self.positions: Dict[str, Position] = {}
        self.orders: List[Order] = []
        self._realtime_prices: Dict[str, float] = {}
        self._limit_prices: Dict[str, Dict] = {}  # ts_code → {upper, lower}
        self._suspended: set = set()  # 停牌股

    def update_realtime(self, ts_code: str, price: float,
                        upper_limit: float = None, lower_limit: float = None,
                        suspended: bool = False):
        """更新实时行情(由MarketScanner调用)"""
        self._realtime_prices[ts_code] = price
        if upper_limit is not None or lower_limit is not None:
            self._limit_prices[ts_code] = {
                "upper": upper_limit or price * 1.1,
                "lower": lower_limit or price * 0.9,
            }
        if suspended:
            self._suspended.add(ts_code)
        elif ts_code in self._suspended:
            self._suspended.discard(ts_code)

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
                    reason: str = "") -> Tuple[bool, str, Order]:
        """
        下单

        Args:
            ts_code: 股票代码
            stock_name: 股票名称
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
        if quantity % self.LOT_SIZE != 0 or quantity <= 0:
            order.status = OrderStatus.REJECTED
            order.reason = f"数量必须为{self.LOT_SIZE}的整数倍"
            self.orders.append(order)
            return False, f"数量必须为{self.LOT_SIZE}的整数倍", order

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
                quantity = int(self.account.available_cash / current_price / self.LOT_SIZE) * self.LOT_SIZE
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
                    max_qty = int((single_max - existing_value) / current_price / self.LOT_SIZE) * self.LOT_SIZE
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

        return True, f"{action}{quantity}股@{fill_price:.2f}", order

    def _match(self, order: Order, current_price: float) -> Tuple[float, float, float]:
        """
        撮合引擎

        Returns:
            (fill_price, commission, stamp_duty)
        """
        if order.order_type == OrderType.MARKET:
            # 市价单: 用最新价 + 滑点
            if order.side == OrderSide.BUY:
                fill_price = current_price * (1 + self.SLIPPAGE_RATE)  # 买入滑点上浮
            else:
                fill_price = current_price * (1 - self.SLIPPAGE_RATE)  # 卖出滑点下浮
        else:
            # 限价单: 检查是否触发
            if order.side == OrderSide.BUY:
                if current_price > order.price:
                    return 0, 0, 0  # 未到限价
                fill_price = order.price
            else:
                if current_price < order.price:
                    return 0, 0, 0  # 未到限价
                fill_price = order.price

        # 计算费用
        amount = fill_price * order.quantity
        commission = max(amount * self.COMMISSION_RATE, self.MIN_COMMISSION)
        stamp_duty = amount * self.STAMP_DUTY_RATE if order.side == OrderSide.SELL else 0

        return round(fill_price, 2), round(commission, 2), round(stamp_duty, 2)

    def _execute_buy(self, order: Order, fill_price: float, total_cost: float):
        """执行买入"""
        amount = fill_price * order.quantity + total_cost
        self.account.available_cash -= amount
        self.account.frozen_cash += 0  # 简化: 不冻结

        if order.ts_code in self.positions:
            pos = self.positions[order.ts_code]
            # 加仓: 重算均价
            total_cost_base = pos.avg_cost * pos.total_qty + fill_price * order.quantity
            pos.total_qty += order.quantity
            pos.today_buy_qty += order.quantity  # T+1: 今日买入不可卖
            pos.avg_cost = total_cost_base / pos.total_qty
            pos.current_price = fill_price
            pos.strategy = order.strategy
        else:
            self.positions[order.ts_code] = Position(
                ts_code=order.ts_code,
                stock_name=order.stock_name,
                total_qty=order.quantity,
                available_qty=0,  # T+1: 今日买入不可卖
                avg_cost=fill_price,
                current_price=fill_price,
                today_buy_qty=order.quantity,
                strategy=order.strategy,
            )

    def _execute_sell(self, order: Order, fill_price: float, total_cost: float):
        """执行卖出"""
        pos = self.positions.get(order.ts_code)
        if not pos:
            return

        # 收回资金
        amount = fill_price * order.quantity - total_cost
        self.account.available_cash += amount

        # 更新持仓
        pos.available_qty -= order.quantity
        pos.total_qty -= order.quantity

        # 计算盈亏
        if pos.total_qty <= 0:
            profit = (fill_price - pos.avg_cost) * order.quantity
            self.account.total_profit += profit
            del self.positions[order.ts_code]
        else:
            # 部分卖出
            pass

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
        } for o in self.orders if o.trade_date == today and o.status == OrderStatus.FILLED]
