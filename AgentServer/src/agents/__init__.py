"""
Agent 层

定义各类 Agent，每个 Agent 包含：
- System Prompt（角色定义）
- 可用工具列表
- ReAct 循环逻辑
"""

from .base import BaseAgent, AgentResult, AgentConfig, ToolCall
from .stock_analyzer_agent import StockAnalyzerAgent
from .report_writer_agent import ReportWriterAgent
from .review import (
    MarketReviewAgent,
    SectorReviewAgent,
    LimitUpReviewAgent,
    StockLinkageAgent,
    SentimentCycleAgent,
    ReviewReportAgent,
)

__all__ = [
    "BaseAgent",
    "AgentResult",
    "AgentConfig",
    "ToolCall",
    "StockAnalyzerAgent",
    "ReportWriterAgent",
    # 复盘 Agent
    "MarketReviewAgent",
    "SectorReviewAgent",
    "LimitUpReviewAgent",
    "StockLinkageAgent",
    "SentimentCycleAgent",
    "ReviewReportAgent",
]
