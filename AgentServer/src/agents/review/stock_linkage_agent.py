"""
个股联动分析 Agent

分析板块内个股联动关系，识别龙头、中军、补涨等角色。
"""

from typing import List
from src.agents.base import BaseAgent


class StockLinkageAgent(BaseAgent):
    """
    个股联动分析 Agent
    
    分析内容:
    - 龙头股识别（龙一、龙二）
    - 中军股识别（大市值核心）
    - 补涨股和跟风股
    - 板块内个股梯队
    """
    
    name = "stock_linkage"
    description = "分析板块内个股联动关系"
    prompt_template_name = "agent_stock_linkage"
    
    @property
    def available_tools(self) -> List[str]:
        return [
            "get_limit_list",
            "get_limit_step",
            "get_sector_limit_ranking",
            "get_sector_stocks",
            "get_stock_sectors",
            "get_common_sectors",
            "get_dragon_list",
        ]
