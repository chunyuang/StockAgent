"""
复盘分析工具

提供复盘所需的各类数据查询和分析工具。
工具从 MongoDB 读取已采集的数据，供 Agent 调用。
"""

from .market import (
    get_market_overview,
    get_index_daily,
    get_northbound_flow,
)
from .sector import (
    get_top_sectors,
    get_sector_detail,
    get_stock_sectors,
    get_sector_stocks,
)
from .limit import (
    get_limit_overview,
    get_limit_step,
    get_limit_list,
)
from .dragon import (
    get_dragon_list,
    get_hot_money_tracks,
)
from .sentiment import (
    get_market_sentiment,
)
from .hot_stock import (
    get_hot_stocks,
)


def register_all_review_tools():
    """注册所有复盘工具（工具在导入时自动注册）"""
    pass


__all__ = [
    # 大盘
    "get_market_overview",
    "get_index_daily",
    "get_northbound_flow",
    # 板块
    "get_top_sectors",
    "get_sector_detail",
    "get_stock_sectors",
    "get_sector_stocks",
    # 涨停
    "get_limit_overview",
    "get_limit_step",
    "get_limit_list",
    # 龙虎榜
    "get_dragon_list",
    "get_hot_money_tracks",
    # 情绪
    "get_market_sentiment",
    # 热股
    "get_hot_stocks",
    # 注册函数
    "register_all_review_tools",
]
