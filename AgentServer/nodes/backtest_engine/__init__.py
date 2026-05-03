"""
量化回测引擎模块

核心组件：
- BacktestNode: 回测引擎节点
- PortfolioBacktester: 组合回测引擎（主引擎）
- 数据模型: BacktestResult, Trade, TradeDirection, BacktestConfig

已弃用（移至 _deprecated/）：
- PerformanceAnalyzer: 绩效评估与回撤系统（portfolio_backtest.py内置计算）
- factors.py / incremental_backtest.py / walk_forward.py: 无导入者的死代码
"""

from .models import BacktestConfig, BacktestResult, Trade, TradeDirection
from .node import BacktestNode

# PerformanceAnalyzer 已弃用，移至 _deprecated/performance.py
# 如需使用：from nodes.backtest_engine._deprecated.performance import PerformanceAnalyzer, PerformanceMetrics

__all__ = [
    # 节点
    "BacktestNode",
    # 数据模型（从 models.py 导出）
    "BacktestConfig",
    "BacktestResult",
    "Trade",
    "TradeDirection",
]
