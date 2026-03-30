"""
策略执行器（只保留核心5个策略）

内置策略:
- LimitOpenStrategy: 涨跌停打开策略（只启用涨停开板）
- PriceChangeStrategy: 涨跌幅阈值策略（半路追涨）
- LeadingDragonStrategy: 龙头战法（龙头低吸）
- FirstBoardStrategy: 首板打板

已移除:
- MA5BuyStrategy: 5日线低吸策略（回测表现差，已移除）
- 跌停翘板: 通过 LimitOpenStrategy 参数控制关闭，不需删除代码
"""

from .base import BaseStrategy
from .limit_open import LimitOpenStrategy
from .price_change import PriceChangeStrategy
from .leading_dragon import LeadingDragonStrategy
from .first_board import FirstBoardStrategy

__all__ = [
    "BaseStrategy",
    "LimitOpenStrategy",
    "PriceChangeStrategy",
    "LeadingDragonStrategy",
    "FirstBoardStrategy",
]
