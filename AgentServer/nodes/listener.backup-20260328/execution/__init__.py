"""
交易执行模块

- base_executor: 基类定义，支持对接不同券商
- simulator_executor: 模拟交易执行器，用于复盘验证
- position_manager: 持仓管理器，整合信号、止损、仓位管理
- daily_reporter: 每日收盘复盘报告
"""

from .base_executor import (
    BaseExecutor,
    Order,
    Position,
    AccountInfo,
    OrderDirection,
    OrderStatus,
)
from .simulator_executor import SimulatorExecutor
from .position_manager import PositionManager
from .daily_reporter import DailyReporter, get_daily_reporter

__all__ = [
    "BaseExecutor",
    "Order",
    "Position",
    "AccountInfo",
    "OrderDirection",
    "OrderStatus",
    "SimulatorExecutor",
    "PositionManager",
    "DailyReporter",
    "get_daily_reporter",
]
