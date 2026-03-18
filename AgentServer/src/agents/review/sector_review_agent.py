"""
板块复盘 Agent

分析当日板块表现、板块轮动、资金流向。
"""

from typing import List
from src.agents.base import BaseAgent


class SectorReviewAgent(BaseAgent):
    """
    板块复盘 Agent
    
    分析内容:
    - 领涨/领跌板块
    - 板块涨停家数排名
    - 板块轮动情况
    - 热点板块识别
    """
    
    name = "sector_review"
    description = "分析板块表现和轮动"
    prompt_template_name = "agent_sector_review"
    
    @property
    def available_tools(self) -> List[str]:
        return [
            "get_top_sectors",
            "get_sector_detail",
            "get_sector_limit_ranking",
            "get_stock_sectors",
            "get_sector_stocks",
        ]
