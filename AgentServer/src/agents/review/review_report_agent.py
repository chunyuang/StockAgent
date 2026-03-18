"""
复盘报告生成 Agent

汇总各维度分析结果，生成完整的复盘报告。
"""

from typing import List, Dict, Any
from src.agents.base import BaseAgent, AgentResult


class ReviewReportAgent(BaseAgent):
    """
    复盘报告生成 Agent
    
    汇总各维度分析结果，生成格式化的复盘报告。
    """
    
    name = "review_report"
    description = "汇总生成复盘报告"
    prompt_template_name = "agent_review_report"
    
    @property
    def available_tools(self) -> List[str]:
        return [
            "get_market_overview",
            "get_top_sectors",
            "get_limit_overview",
            "get_limit_step",
            "get_market_sentiment",
            "get_hot_stocks",
        ]
    
    async def generate_report(
        self,
        trade_date: str,
        analysis_results: Dict[str, AgentResult],
    ) -> AgentResult:
        """
        基于各维度分析结果生成报告
        
        Args:
            trade_date: 交易日期
            analysis_results: 各维度分析结果
                {
                    "market": AgentResult,
                    "sector": AgentResult,
                    "limit": AgentResult,
                    "linkage": AgentResult,
                    "sentiment": AgentResult,
                }
        
        Returns:
            包含完整报告的 AgentResult
        """
        context = {
            "trade_date": trade_date,
        }
        
        for key, result in analysis_results.items():
            if result and result.success:
                context[f"{key}_analysis"] = result.content
        
        task = f"""请基于以下各维度的分析结果，生成 {trade_date} 的完整复盘报告。

各维度分析已在上下文中提供，请整合这些内容，形成一份结构完整、重点突出的报告。

注意：
1. 不要简单堆砌，要有逻辑串联
2. 突出重点，避免面面俱到
3. 给出明确的操作建议
"""
        
        return await self.run(task, context)
    
    def format_for_wechat(self, content: str) -> str:
        """
        将报告格式化为企业微信兼容的 Markdown
        
        Args:
            content: 原始 Markdown 内容
            
        Returns:
            企业微信兼容的 Markdown
        """
        lines = content.split("\n")
        result = []
        
        for line in lines:
            # 移除四级及以下标题的 #
            if line.startswith("####"):
                line = "**" + line.lstrip("#").strip() + "**"
            
            result.append(line)
        
        return "\n".join(result)
