"""
模拟交易执行器

用于模拟交易，验证策略信号，不连接真实券商。
特点:
- 内存模拟持仓，方便每日复盘
- 支持止损检查、仓位管理
- 支持情绪周期仓位调整
- 记录所有交易，方便回测
"""

import uuid
from datetime import datetime
from typing import List, Dict, Optional, Any

from .base_executor import (
    BaseExecutor,
    Order,
    OrderDirection,
    OrderStatus,
    Position,
    AccountInfo,
)

from core.managers import mongo_manager
from core.settings import settings


class SimulatorExecutor(BaseExecutor):
    """模拟交易执行器"""
    
    def __init__(self, initial_cash: float = None):
        super().__init__()
        # 初始资金
        self._initial_cash = initial_cash or settings.trading.initial_cash
        self._cash = self._initial_cash
        self._positions: Dict[str, Position] = {}  # ts_code -> Position
        self._orders: Dict[str, Order] = {}  # order_id -> Order
        self._total_profit = 0.0
        self._total_profit_pct = 0.0
    
    async def connect(self) -> bool:
        """连接模拟账户"""
        self.logger.info(f"Simulator connected, initial cash: {self._initial_cash:.2f}")
        return True
    
    async def send_order(
        self,
        ts_code: str,
        direction: OrderDirection,
        price: float,
        shares: int,
        strategy: str = "",
    ) -> Optional[Order]:
        """模拟下单，立即成交"""
        if shares <= 0:
            self.logger.warning(f"Invalid shares: {shares} for {ts_code}")
            return None
        
        commission = self.calculate_commission(direction, price, shares)
        amount = price * shares
        
        order_id = str(uuid.uuid4())
        order = Order(
            order_id=order_id,
            ts_code=ts_code,
            direction=direction,
            price=price,
            shares=shares,
            amount=amount,
            filled_shares=shares,
            filled_amount=amount,
            status=OrderStatus.FILLED,
            created_at=datetime.now(),
            filled_at=datetime.now(),
            commission=commission,
            reason=strategy,
        )
        
        # 扣除佣金
        self._cash -= commission
        
        if direction == OrderDirection.BUY:
            # 买入
            total_cost = amount + commission
            if self._cash < total_cost:
                self.logger.warning(
                    f"[BUY] {ts_code}: Insufficient cash, need {total_cost:.2f}, cash {self._cash:.2f}"
                )
                # 不添加佣金回退，模拟已经扣了
                return None
            
            # 更新持仓
            if ts_code in self._positions:
                # 加仓，计算平均成本
                pos = self._positions[ts_code]
                total_shares = pos.shares + shares
                total_cost = pos.shares * pos.cost_price + total_cost
                new_cost = total_cost / total_shares
                pos.shares = total_shares
                pos.cost_price = new_cost
            else:
                # 新建持仓
                from datetime import datetime
                pos = Position(
                    ts_code=ts_code,
                    shares=shares,
                    cost_price=(amount + commission) / shares,
                    buy_date=datetime.now(),
                    strategy=strategy,
                )
                # 计算止损：-5% 为止损
                pos.stop_loss = price * 0.95
                self._positions[ts_code] = pos
            
            # 扣除现金
            self._cash -= total_cost
            
        else:
            # 卖出
            if ts_code not in self._positions:
                self.logger.warning(f"[SELL] {ts_code}: No position to sell")
                return None
            
            pos = self._positions[ts_code]
            if pos.shares != shares:
                self.logger.warning(
                    f"[SELL] {ts_code}: share mismatch, have {pos.shares}, selling {shares}"
                )
            
            # 计算盈利
            profit = amount - (pos.shares * pos.cost_price) - commission
            self._total_profit += profit
            self._cash += amount - commission
            
            # 减少持仓，如果卖完移除
            pos.shares -= shares
            if pos.shares <= 0:
                del self._positions[ts_code]
        
        # 保存订单
        self._orders[order_id] = order
        
        self.logger.info(
            f"[SIMULATOR] {direction} {ts_code} filled: {shares} @ {price:.2f}, "
            f"commission={commission:.2f}"
        )
        
        return order
    
    async def cancel_order(self, order_id: str) -> bool:
        """模拟撤单"""
        if order_id not in self._orders:
            return False
        
        order = self._orders[order_id]
        if order.status in (OrderStatus.FILLED, OrderStatus.CANCELLED):
            return False
        
        order.status = OrderStatus.CANCELLED
        self.logger.info(f"[SIMULATOR] Order cancelled: {order_id}")
        return True
    
    async def get_position(self) -> List[Position]:
        """获取当前持仓"""
        return list(self._positions.values())
    
    async def get_account(self) -> Optional[AccountInfo]:
        """获取账户信息"""
        # 计算当前市值
        market_value = sum(pos.amount for pos in self._positions.values())
        total_asset = self._cash + market_value
        total_profit = self._total_profit
        if self._initial_cash > 0:
            total_profit_pct = total_profit / self._initial_cash * 100
        else:
            total_profit_pct = 0
        
        return AccountInfo(
            total_asset=total_asset,
            available_cash=self._cash,
            market_value=market_value,
            total_profit=total_profit,
            total_profit_pct=total_profit_pct,
            position_count=len(self._positions),
        )
    
    async def get_orders(self, status: Optional[OrderStatus] = None) -> List[Order]:
        """获取订单列表"""
        if status is None:
            return list(self._orders.values())
        
        return [o for o in self._orders.values() if o.status == status]
    
    async def update_current_prices(self) -> None:
        """更新当前持仓价格和盈亏
        
        从 MongoDB 获取最新收盘价，更新持仓盈亏
        """
        from datetime import date
        today = int(date.today().strftime("%Y%m%d"))
        
        ts_codes = list(self._positions.keys())
        if not ts_codes:
            return
        
        # 查询最新价格
        query = {
            "ts_code": {"$in": ts_codes},
            "trade_date": today,
        }
        result = await mongo_manager.find_many(
            "stock_daily",
            query,
            projection={"ts_code": 1, "close": 1},
        )
        
        price_map = {r["ts_code"]: r["close"] for r in result}
        
        for ts_code, pos in self._positions.items():
            if ts_code in price_map:
                pos.current_price = price_map[ts_code]
                # 计算盈亏
                pos.profit_pct = (pos.current_price - pos.cost_price) / pos.cost_price * 100
                pos.profit_amount = (pos.current_price - pos.cost_price) * pos.shares
    
    def get_position_by_tscode(self, ts_code: str) -> Optional[Position]:
        """获取指定股票持仓"""
        return self._positions.get(ts_code)
    
    def check_stop_loss(self) -> List[Position]:
        """检查持仓中需要止损的股票
        
        Returns:
            需要止损卖出的持仓列表
        """
        to_sell: List[Position] = []
        
        for ts_code, pos in self._positions.items():
            if pos.stop_loss > 0 and pos.current_price > 0:
                if pos.current_price <= pos.stop_loss:
                    self.logger.info(
                        f"[STOP_LOSS] {ts_code}: current {pos.current_price:.2f} "
                        f"<= stop {pos.stop_loss:.2f}, need sell"
                    )
                    to_sell.append(pos)
        
        return to_sell
    
    async def calculate_max_shares(
        self,
        price: float,
        max_pct: float = 0.2,
        emotion_multiplier: float = 1.0,
    ) -> int:
        """
        根据仓位限制计算可买最大股数
        
        Args:
            price: 当前价格
            max_pct: 最大仓位占比 (0-1)，默认单票 20%
            emotion_multiplier: 情绪周期仓位乘数 (0-1)
        
        Returns:
            可买股数（100的整数倍）
        """
        account = await self.get_account()
        available = account.available_cash
        max_amount = available * max_pct * emotion_multiplier
        
        # 佣金预估
        commission_estimate = max_amount * 0.0002
        max_amount -= commission_estimate
        
        # 100股整数倍
        shares = int(max_amount / price / 100) * 100
        
        return max(0, shares)
