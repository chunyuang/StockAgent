"""
向量化回测引擎 — 已废弃

VectorizedBacktester 已废弃，超短策略回测统一使用 PortfolioBacktester。
本文件仅保留数据类的向后兼容导入（实际定义在 models.py）。

如需单股回测功能，请使用 PortfolioBacktester 替代。
"""

# 向后兼容：从 models.py 重新导出数据类
from .models import TradeDirection, BacktestConfig, Trade, BacktestResult

# VectorizedBacktester 已废弃，不再提供
# 如需使用，请从 git history 恢复 backtester.py 的旧版本


def __getattr__(name):
    """延迟警告：尝试访问 VectorizedBacktester 时提示已废弃"""
    if name == "VectorizedBacktester":
        raise NotImplementedError(
            "VectorizedBacktester 已废弃，请使用 PortfolioBacktester。"
            "如需单股回测，请从 git history 恢复 backtester.py 的旧版本。"
        )
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
