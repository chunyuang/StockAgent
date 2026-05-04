"""
数据采集器
"""

from .stock_basic import StockBasicCollector
from .stock_daily_ak_full import StockDailyCollector
from .daily_basic import DailyBasicCollector
from .index_basic import IndexBasicCollector
from .index_daily import IndexDailyCollector
from .moneyflow_industry import MoneyflowIndustryCollector
from .moneyflow_concept import MoneyflowConceptCollector
from .limit_list import LimitListCollector
from .daily_stats import DailyStatsCollector
from .news import StockNewsCollector
from .fina_indicator import FinaIndicatorCollector
from .hot_news import HotNewsCollector
from .liangmai_collectors import (
    LiangMaiKlineCollector,
    LiangMaiLimitUpCollector,
    LiangMaiRealtimeCollector,
    LiangMaiIndexCollector,
)

__all__ = [
    "StockBasicCollector",
    "StockDailyCollector",
    "DailyBasicCollector",
    "IndexBasicCollector",
    "IndexDailyCollector",
    "MoneyflowIndustryCollector",
    "MoneyflowConceptCollector",
    "LimitListCollector",
    "DailyStatsCollector",
    "StockNewsCollector",
    "FinaIndicatorCollector",
    "HotNewsCollector",
    "LiangMaiKlineCollector",
    "LiangMaiLimitUpCollector",
    "LiangMaiRealtimeCollector",
    "LiangMaiIndexCollector",
]
