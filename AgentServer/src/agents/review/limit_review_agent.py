"""
涨停复盘 Agent

分析涨停数据、连板天梯、炸板率等。
"""

from typing import List
from src.agents.base import BaseAgent


class LimitUpReviewAgent(BaseAgent):
    """
    涨停复盘 Agent
    
    分析内容:
    - 涨停家数、跌停家数
    - 连板天梯（首板、二板、三板...）
    - 炸板率
    - 最高板及空间股
    """
    
    name = "limit_review"
    description = "分析涨停数据和连板情况"
    prompt_template_name = "agent_limit_review"
    
    @property
    def available_tools(self) -> List[str]:
        return [
            "get_limit_overview",
            "get_limit_step",
            "get_limit_list",
            "get_sector_limit_ranking",
            "get_stock_sectors",
        ]
