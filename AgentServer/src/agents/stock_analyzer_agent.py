"""
股票分析 Agent

负责对股票进行全面分析：
- 实时行情
- 技术面分析
- 资讯面分析
- 综合研判
"""

from typing import List
from .base import BaseAgent


class StockAnalyzerAgent(BaseAgent):
    """
    股票分析 Agent
    
    分析流程:
    1. 获取股票基本信息和实时行情
    2. 获取历史K线，计算技术指标
    3. 搜索相关新闻和公告
    4. 综合分析，给出投资建议
    
    Example:
        agent = StockAnalyzerAgent(llm_service, tool_registry)
        result = await agent.run("分析贵州茅台 600519.SH")
    """
    
    name = "stock_analyzer"
    description = "股票分析 Agent，提供技术面、基本面、资讯面综合分析"
    prompt_template_name = "agent_stock_analyzer"
    
    @property
    def available_tools(self) -> List[str]:
        return [
            # 数据工具
            "get_realtime_quote",
            "get_stock_info",
            "get_daily_kline",
            "get_financial_data",
            # 分析工具
            "calculate_technical_indicators",
            "analyze_trend",
            # 搜索工具
            "search_stock_news",
            "search_local_news",
            "get_stock_news",
        ]
