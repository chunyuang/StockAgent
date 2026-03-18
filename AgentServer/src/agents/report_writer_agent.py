"""
报告撰写 Agent

负责根据分析结果生成结构化报告。
"""

from typing import List
from .base import BaseAgent


class ReportWriterAgent(BaseAgent):
    """
    报告撰写 Agent
    
    根据股票分析结果或市场数据，生成专业的分析报告。
    
    Example:
        agent = ReportWriterAgent(llm_service, tool_registry)
        result = await agent.run(
            "生成股票分析报告",
            context={"analysis": analysis_data}
        )
    """
    
    name = "report_writer"
    description = "报告撰写 Agent，生成专业的股票分析报告"
    prompt_template_name = "agent_report_writer"
    
    @property
    def available_tools(self) -> List[str]:
        # 报告撰写主要依赖上下文数据，工具较少
        return [
            "get_stock_info",
            "get_realtime_quote",
            "get_market_sentiment",
        ]
