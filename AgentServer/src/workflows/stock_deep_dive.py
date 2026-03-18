"""
股票深度分析工作流

完整的个股分析流程：
1. 股票分析 Agent - 收集数据、技术分析
2. 报告撰写 Agent - 生成分析报告
"""

import time
from typing import Any, Dict

from .base import BaseWorkflow, WorkflowResult, WorkflowStep


class StockDeepDiveWorkflow(BaseWorkflow):
    """
    个股深度分析工作流
    
    执行流程:
    1. 使用 StockAnalyzerAgent 进行全面分析
    2. 使用 ReportWriterAgent 生成分析报告
    
    Example:
        workflow = StockDeepDiveWorkflow(agents)
        result = await workflow.execute({"stock_code": "600519.SH"})
    """
    
    name = "stock_deep_dive"
    description = "个股深度分析，包含技术面、基本面、资讯面分析，并生成完整报告"
    
    async def execute(self, input_data: Dict[str, Any]) -> WorkflowResult:
        """
        执行深度分析
        
        Args:
            input_data: {
                "stock_code": "股票代码",
                "stock_name": "股票名称（可选）",
            }
        """
        start_time = time.time()
        steps = []
        
        stock_code = input_data.get("stock_code")
        stock_name = input_data.get("stock_name", stock_code)
        
        if not stock_code:
            return WorkflowResult(
                success=False,
                error="Missing required parameter: stock_code",
            )
        
        self.logger.info(f"Starting deep dive analysis for {stock_code}")
        
        # ==================== Step 1: 股票分析 ====================
        step1, analysis_result = await self.run_step(
            step_name="stock_analysis",
            agent_name="stock_analyzer",
            task=f"详细分析股票 {stock_code} ({stock_name})",
        )
        steps.append(step1)
        
        if not analysis_result or not analysis_result.success:
            return WorkflowResult(
                success=False,
                steps=steps,
                error=step1.error or "股票分析失败",
                elapsed_ms=(time.time() - start_time) * 1000,
            )
        
        # ==================== Step 2: 生成报告 ====================
        step2, report_result = await self.run_step(
            step_name="report_generation",
            agent_name="report_writer",
            task=f"根据分析结果，为 {stock_code} 生成专业的股票分析报告",
            context={
                "stock_code": stock_code,
                "stock_name": stock_name,
                "analysis": analysis_result.data or analysis_result.content,
            },
        )
        steps.append(step2)
        
        # 即使报告生成失败，也返回分析结果
        if not report_result or not report_result.success:
            return WorkflowResult(
                success=True,  # 分析成功，报告失败
                data={
                    "stock_code": stock_code,
                    "analysis": analysis_result.data,
                    "report": None,
                    "report_error": step2.error,
                },
                steps=steps,
                total_steps=len(steps),
                elapsed_ms=(time.time() - start_time) * 1000,
            )
        
        # 成功完成
        return WorkflowResult(
            success=True,
            data={
                "stock_code": stock_code,
                "analysis": analysis_result.data,
                "report": report_result.content,
            },
            steps=steps,
            total_steps=len(steps),
            elapsed_ms=(time.time() - start_time) * 1000,
        )
