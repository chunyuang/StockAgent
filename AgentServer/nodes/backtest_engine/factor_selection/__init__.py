"""
因子选股回测模块

提供完整的因子选股回测功能:
- UniverseManager: 股票池管理
- FactorLibrary: 内置因子库
- FactorEngine: 因子批量计算
- PortfolioBacktester: 组合回测引擎
"""

from .factor_engine import FactorEngine
from .factor_library import FactorCategory, FactorDefinition, FactorLibrary
from .portfolio_backtest import PortfolioBacktester
from .universe import ExcludeRule, UniverseManager, UniverseType

__all__ = [
    "UniverseManager",
    "UniverseType",
    "ExcludeRule",
    "FactorLibrary",
    "FactorDefinition",
    "FactorCategory",
    "FactorEngine",
    "PortfolioBacktester",
]
