"""
量化回测引擎模块

核心组件：
- BacktestNode: 回测引擎节点
- PortfolioBacktester: 组合回测引擎（主引擎）
- PerformanceAnalyzer: 绩效评估与回撤系统（已弃用，portfolio_backtest.py内置计算）
- 数据模型: BacktestResult, Trade, TradeDirection, BacktestConfig
"""

from .models import BacktestConfig, BacktestResult, Trade, TradeDirection
from .performance import PerformanceAnalyzer, PerformanceMetrics
from .node import BacktestNode

__all__ = [
    # 节点
    "BacktestNode",
    # 数据模型（从 models.py 导出）
    "BacktestConfig",
    "BacktestResult",
    "Trade",
    "TradeDirection",
    # 绩效分析
    "PerformanceAnalyzer",
    "PerformanceMetrics",
]
