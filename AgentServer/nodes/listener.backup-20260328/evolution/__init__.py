"""
策略迭代进化模块

基于历史交易结果动态调整因子权重，让策略自动进化。

- strategy_evolution: 核心类，记录胜率、调整权重
"""

from .strategy_evolution import (
    StrategyEvolution,
    FactorStatistics,
    get_evolution,
)

__all__ = [
    "StrategyEvolution",
    "FactorStatistics",
    "get_evolution",
]
