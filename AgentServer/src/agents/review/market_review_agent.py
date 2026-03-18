"""
大盘复盘 Agent

分析大盘指数表现、北向资金、整体涨跌情况。
"""

from typing import List
from src.agents.base import BaseAgent


class MarketReviewAgent(BaseAgent):
    """
    大盘复盘 Agent
    
    分析内容:
    - 三大指数涨跌幅
    - 北向资金流向
    - 涨跌家数比
    - 大盘强弱判定
    """
    
    name = "market_review"
    description = "分析大盘整体表现"
    prompt_template_name = "agent_market_review"
    
    @property
    def available_tools(self) -> List[str]:
        return [
            "get_market_overview",
            "get_index_daily",
            "get_northbound_flow",
            "get_limit_overview",
        ]
