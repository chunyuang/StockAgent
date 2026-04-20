"""
交易执行器基类

定义通用交易执行接口，支持不同券商对接。
所有具体券商实现必须继承此类。

接口:
- send_order: 下单
- cancel_order: 撤单
- get_position: 获取持仓
- get_account: 获取账户信息
- get_orders: 获取订单列表
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional
from dataclasses import dataclass
from enum import Enum


class OrderDirection(str, Enum):
    """订单方向"""
    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, Enum):
    """订单状态"""
    PENDING = "pending"
    FILLED = "filled"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass
class Order:
    """订单"""
    order_id: str
    ts_code: str
    direction: OrderDirection
    price: float
    shares: int
    amount: float  # 总金额
    filled_shares: int = 0
    filled_amount: float = 0
    status: OrderStatus = OrderStatus.PENDING
    created_at: datetime = None
    filled_at: Optional[datetime] = None
    commission: float = 0
    reason: str = ""
    
    @property
    def is_filled(self) -> bool:
        return self.status == OrderStatus.FILLED
    
    @property
    def is_partial(self) -> bool:
        return self.status == OrderStatus.PARTIAL


@dataclass
class Position:
    """持仓"""
    ts_code: str
    shares: int  # 持股数量
    cost_price: float  # 平均成本
    buy_date: datetime  # 买入日期
    current_price: float = 0  # 当前价格
    profit_pct: float = 0  # 当前盈亏百分比
    profit_amount: float = 0  # 当前盈亏金额
    strategy: str = ""  # 策略类型
    stop_loss: float = 0  # 止损价
    
    @property
    def amount(self) -> float:
        """当前持仓市值 = 持仓数量 × 当前价格"""
        return self.shares * self.current_price
    
    @property
    def profit_total_cost(self) -> float:
        """总成本"""
        return self.shares * self.cost_price


@dataclass
class AccountInfo:
    """账户信息"""
    total_asset: float  # 总资产
    available_cash: float  # 可用资金
    market_value: float  # 持仓市值
    total_profit: float  # 累计盈亏
    total_profit_pct: float  # 累计盈亏百分比
    position_count: int  # 持仓数量


class BaseExecutor(ABC):
    """交易执行器基类"""
    
    def __init__(self):
        import logging
        self.logger = logging.getLogger(self.__class__.__name__)
    
    @abstractmethod
    async def connect(self) -> bool:
        """连接券商接口，成功返回 True"""
        pass
    
    @abstractmethod
    async def send_order(
        self,
        ts_code: str,
        direction: OrderDirection,
        price: float,
        shares: int,
        strategy: str = "",
    ) -> Optional[Order]:
        """
        下单
        
        Args:
            ts_code: 股票代码
            direction: buy/sell
            price: 委托价格
            shares: 股数
            strategy: 策略名称
            
        Returns:
            Order 对象，失败返回 None
        """
        pass
    
    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """撤单"""
        pass
    
    @abstractmethod
    async def get_position(self) -> List[Position]:
        """获取当前持仓"""
        pass
    
    @abstractmethod
    async def get_account(self) -> Optional[AccountInfo]:
        """获取账户信息"""
        pass
    
    @abstractmethod
    async def get_orders(self, status: Optional[OrderStatus] = None) -> List[Order]:
        """获取订单列表"""
        pass
    
    async def update_current_prices(self, positions: List[Position]) -> None:
        """更新当前持仓价格（从行情获取更新盈亏"""
        pass
    
    def calculate_commission(
        self,
        direction: OrderDirection,
        price: float,
        shares: int,
    ) -> float:
        """计算佣金
        
        A股标准佣金计算:
        - 买入: 佣金万2，最低5元
        - 卖出: 佣金万2 + 印花税千1
        """
        amount = price * shares
        commission = amount * 0.0002  # 万2
        
        if commission < 5 and amount > 0:
            commission = 5.0
            
        if direction == OrderDirection.SELL:
            # 印花税 千1
            commission += amount * 0.001
            
        return commission
