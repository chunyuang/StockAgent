"""
情绪周期复盘 Agent

分析市场情绪所处的周期阶段。
"""

from typing import List
from src.agents.base import BaseAgent


class SentimentCycleAgent(BaseAgent):
    """
    情绪周期复盘 Agent
    
    分析内容:
    - 当前情绪阶段判断
    - 情绪周期位置
    - 风险与机会提示
    """
    
    name = "sentiment_cycle"
    description = "分析市场情绪周期"
    prompt_template_name = "agent_sentiment_cycle"
    
    @property
    def available_tools(self) -> List[str]:
        return [
            "get_market_sentiment",
            "get_sentiment_history",
            "get_limit_overview",
            "get_limit_step",
            "get_market_overview",
        ]
