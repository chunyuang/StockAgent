"""
复盘工作流（LangGraph 实现）

使用 LangGraph 编排复盘分析的各个 Agent。
"""

import logging
from typing import Any, Dict, Optional
from langgraph.graph import END, START

from src.config import config_manager
from src.agents import (
    MarketReviewAgent,
    SectorReviewAgent,
    LimitUpReviewAgent,
    StockLinkageAgent,
    SentimentCycleAgent,
    ReviewReportAgent,
)
from src.tools.registry import tool_registry
from .graph import GraphBuilder, ReviewState, create_agent_node


logger = logging.getLogger(__name__)


class ReviewWorkflow:
    """
    复盘工作流（LangGraph 版本）
    
    整合各维度分析 Agent，使用 LangGraph 编排执行流程。
    
    图结构：
        START → market → [sector, limit] (并行) → linkage → sentiment → report → END
    
    Example:
        workflow = ReviewWorkflow(llm_service)
        result = await workflow.run(trade_date="20260305")
        print(result["report"])
    """
    
    def __init__(self, llm_service, config: Dict[str, Any] = None):
        self.llm = llm_service
        self.config = config or config_manager.get("review.workflow", {})
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        # 初始化 Agent
        self._init_agents()
        
        # 构建 LangGraph
        self._build_graph()
    
    def _init_agents(self):
        """初始化各分析 Agent"""
        self.market_agent = MarketReviewAgent(self.llm, tool_registry)
        self.sector_agent = SectorReviewAgent(self.llm, tool_registry)
        self.limit_agent = LimitUpReviewAgent(self.llm, tool_registry)
        self.linkage_agent = StockLinkageAgent(self.llm, tool_registry)
        self.sentiment_agent = SentimentCycleAgent(self.llm, tool_registry)
        self.report_agent = ReviewReportAgent(self.llm, tool_registry)
    
    def _build_graph(self):
        """构建 LangGraph 工作流"""
        builder = GraphBuilder(ReviewState)
        
        # ==================== 添加节点 ====================
        
        # 大盘分析
        builder.add_node("market", create_agent_node(
            agent=self.market_agent,
            result_key="market_result",
            task_template="请分析 {trade_date} 的大盘表现，给出市场强弱判断。",
            context_keys=["trade_date"],
        ))
        
        # 板块分析
        builder.add_node("sector", create_agent_node(
            agent=self.sector_agent,
            result_key="sector_result",
            task_template="请分析 {trade_date} 的板块表现，识别主线和热点。",
            context_keys=["trade_date"],
        ))
        
        # 涨停分析
        builder.add_node("limit", create_agent_node(
            agent=self.limit_agent,
            result_key="limit_result",
            task_template="请分析 {trade_date} 的涨停数据，包括连板天梯和赚钱效应。",
            context_keys=["trade_date"],
        ))
        
        # 个股联动分析
        builder.add_node("linkage", create_agent_node(
            agent=self.linkage_agent,
            result_key="linkage_result",
            task_template="请分析 {trade_date} 主线板块内的个股联动关系，识别龙头和中军。",
            context_keys=["trade_date"],
        ))
        
        # 情绪周期分析
        builder.add_node("sentiment", create_agent_node(
            agent=self.sentiment_agent,
            result_key="sentiment_result",
            task_template="请判断 {trade_date} 市场所处的情绪周期阶段。",
            context_keys=["trade_date"],
        ))
        
        # 报告生成
        builder.add_node("report", self._report_node)
        
        # ==================== 构建边 ====================
        
        # START → market
        builder.add_edge(START, "market")
        
        # market → [sector, limit] (并行) → linkage
        builder.add_parallel(["sector", "limit"], after="market", before="linkage")
        
        # linkage → sentiment
        builder.add_edge("linkage", "sentiment")
        
        # sentiment → report
        builder.add_edge("sentiment", "report")
        
        # report → END
        builder.add_edge("report", END)
        
        # 编译图
        self.graph = builder.compile()
        
        self.logger.info("ReviewWorkflow graph built successfully")
    
    async def _report_node(self, state: ReviewState) -> dict:
        """
        报告生成节点
        
        汇总各维度分析结果，生成最终报告。
        """
        trade_date = state.get("trade_date", "")
        
        # 收集各维度分析结果
        analysis_results = {}
        
        for key in ["market", "sector", "limit", "linkage", "sentiment"]:
            result_key = f"{key}_result"
            if result_key in state and state[result_key]:
                result = state[result_key]
                # 从 dict 重建 AgentResult 类似结构
                from src.agents.base import AgentResult
                if isinstance(result, dict):
                    analysis_results[key] = AgentResult(
                        success=True,
                        content=result.get("content", ""),
                        data=result.get("data"),
                    )
        
        # 调用报告生成 Agent
        result = await self.report_agent.generate_report(trade_date, analysis_results)
        
        if result.success:
            return {
                "report": result.content,
            }
        else:
            return {
                "report": None,
                "errors": [f"report: {result.error}"],
            }
    
    async def run(
        self,
        trade_date: Optional[str] = None,
    ) -> ReviewState:
        """
        执行复盘工作流
        
        Args:
            trade_date: 交易日期，默认最近交易日
        
        Returns:
            完整的工作流状态（包含所有分析结果）
        """
        from core.managers import data_source_manager
        
        # 获取交易日期
        if not trade_date:
            trade_date, _ = await data_source_manager.get_latest_trade_date()
        
        self.logger.info(f"Starting review workflow for {trade_date}")
        
        # 初始状态
        initial_state: ReviewState = {
            "trade_date": trade_date,
            "market_result": None,
            "sector_result": None,
            "limit_result": None,
            "linkage_result": None,
            "sentiment_result": None,
            "report": None,
            "confidence": 0,
            "errors": [],
            "round_count": 0,
            "conflicts": [],
        }
        
        # 执行图
        try:
            result = await self.graph.ainvoke(initial_state)
            
            # 检查是否成功
            errors = result.get("errors", [])
            if errors:
                self.logger.warning(f"Workflow completed with {len(errors)} errors: {errors}")
            else:
                self.logger.info("Workflow completed successfully")
            
            return result
            
        except Exception as e:
            self.logger.error(f"Workflow failed: {e}")
            initial_state["errors"] = [str(e)]
            return initial_state
    
    @property
    def success(self) -> bool:
        """检查最近一次运行是否成功"""
        # 注意：这个属性在 LangGraph 中不太适用
        # 因为状态是每次调用时传递的
        return True
    
    def get_graph_structure(self) -> Dict[str, Any]:
        """获取图结构（用于调试）"""
        return {
            "nodes": [
                "market", "sector", "limit", 
                "linkage", "sentiment", "report"
            ],
            "edges": [
                ("START", "market"),
                ("market", "sector"),
                ("market", "limit"),
                ("sector", "linkage"),
                ("limit", "linkage"),
                ("linkage", "sentiment"),
                ("sentiment", "report"),
                ("report", "END"),
            ],
            "parallel_groups": [
                ["sector", "limit"],
            ],
        }
