"""
统一Broker基类

所有券商/仿真引擎必须实现此接口。
解决当前4套Broker接口不统一的问题:
- SimulatedBroker (nodes/market_monitor/broker.py): Scanner用
- SimTradingEngine (core/managers/sim_trading_engine.py): 回测用
- GmBroker (nodes/market_monitor/gm_broker.py): 掘金用
- BaseTradeGateway (core/managers/live/trade_gateway.py): 框架设计

统一接口: place_order / cancel_order / get_positions / get_account / save_state / load_state
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum

logger = logging.getLogger("broker.base")


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"   # 已提交券商
    PARTIAL = "partial"       # 部分成交
    FILLED = "filled"         # 全部成交
    REJECTED = "rejected"     # 已拒绝
    CANCELED = "canceled"     # 已撤单


@dataclass
class UnifiedPosition:
    """统一持仓数据结构
    
    所有Broker必须返回此格式的持仓数据。
    """
    ts_code: str
    stock_name: str
    total_qty: int = 0
    available_qty: int = 0       # T+1: 可卖数量
    avg_cost: float = 0.0
    current_price: float = 0.0
    profit_pct: float = 0.0
    today_buy_qty: int = 0
    strategy: str = ""
    # 扩展字段(不同broker可能有额外信息)
    extra: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.extra is None:
            self.extra = {}


@dataclass
class UnifiedAccount:
    """统一账户数据结构"""
    account_id: str
    total_assets: float = 0.0
    available_cash: float = 0.0
    frozen_cash: float = 0.0
    market_value: float = 0.0
    today_profit: float = 0.0
    total_profit: float = 0.0


@dataclass
class UnifiedOrder:
    """统一订单数据结构"""
    order_id: str
    account_id: str
    ts_code: str
    stock_name: str
    side: OrderSide
    order_type: str = "market"    # market/limit
    quantity: int = 0
    price: float = 0.0
    filled_qty: int = 0
    filled_price: float = 0.0
    status: OrderStatus = OrderStatus.PENDING
    strategy: str = ""
    reason: str = ""
    trade_date: str = ""
    create_time: str = ""
    fill_time: str = ""


class BaseBroker(ABC):
    """统一Broker基类
    
    所有券商/仿真引擎必须实现此接口。
    
    实现者:
    - SimulatedBroker (仿真撮合, Scanner用)
    - SimBacktestBroker (回测撮合, 回测引擎用) 
    - GmBroker (掘金量化)
    - QmtBroker (QMT实盘, 待实现)
    """
    
    @property
    @abstractmethod
    def broker_type(self) -> str:
        """券商类型: simulated/gm_paper/qmt"""
        pass
    
    @abstractmethod
    def place_order(self, ts_code: str, stock_name: str,
                    side: str, quantity: int,
                    price: float = 0.0, order_type: str = "market",
                    strategy: str = "", reason: str = "") -> Tuple[bool, str, Any]:
        """下单
        
        Returns: (success, message, order)
        """
        pass
    
    @abstractmethod
    def cancel_order(self, order_id: str) -> Tuple[bool, str]:
        """撤单
        
        Returns: (success, message)
        """
        pass
    
    @abstractmethod
    def get_positions(self) -> List[UnifiedPosition]:
        """获取持仓列表(统一格式)"""
        pass
    
    @abstractmethod
    def get_account(self) -> UnifiedAccount:
        """获取账户信息(统一格式)"""
        pass
    
    @abstractmethod
    def get_orders(self, trade_date: str = None) -> List[UnifiedOrder]:
        """获取订单列表"""
        pass
    
    @abstractmethod
    def update_realtime(self, ts_code: str, price: float,
                        pre_close: float = None, **kwargs):
        """更新实时行情(由Scanner调用)"""
        pass
    
    async def save_state(self) -> bool:
        """持久化状态(可选实现)"""
        return True
    
    async def load_state(self) -> bool:
        """恢复状态(可选实现)"""
        return True
    
    def daily_settlement(self, trade_date: str = None):
        """每日结算(T+1解锁)"""
        pass
