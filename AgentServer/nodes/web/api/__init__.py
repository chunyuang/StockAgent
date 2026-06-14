"""
Web API 路由
"""

from .auth import router as auth_router
from .user import router as user_router
from .task import router as task_router
from .stock import router as stock_router
from .market import router as market_router
from .subscription import router as subscription_router
from .backtest import router as backtest_router
from .trading import router as trading_router
from .system import router as system_router
from .scanner import router as scanner_router
from .strategy_config import router as strategy_config_router
from .datasource import router as datasource_router
from .factor import router as factor_router

__all__ = [
    "auth_router", "user_router", "task_router", "stock_router",
    "market_router", "subscription_router", "backtest_router",
    "trading_router", "system_router",
    "scanner_router", "strategy_config_router", "datasource_router",
    "factor_router",
]
