"""
工作流编排层

定义多步骤任务的执行流程，协调多个 Agent 协作。

工作流模式：
1. BaseWorkflow - 简单工作流基类，适合固定流程
2. LangGraph（graph/）- 可配置图引擎，支持并行、条件分支、迭代

报告模块：
- ReviewReportFormatter - 报告格式化
- ReviewReportPusher - 报告推送
"""

from .base import BaseWorkflow, WorkflowResult, WorkflowStep
from .stock_deep_dive import StockDeepDiveWorkflow
from .review_workflow import ReviewWorkflow
from .report import ReviewReportFormatter, ReviewReportPusher

# LangGraph 核心
from .graph import (
    GraphBuilder,
    ReviewState,
    BaseWorkflowState,
    create_agent_node,
    create_async_node,
)

__all__ = [
    # 简单工作流
    "BaseWorkflow",
    "WorkflowResult",
    "WorkflowStep",
    "StockDeepDiveWorkflow",
    # LangGraph 工作流
    "ReviewWorkflow",
    "GraphBuilder",
    "ReviewState",
    "BaseWorkflowState",
    "create_agent_node",
    "create_async_node",
    # 报告模块
    "ReviewReportFormatter",
    "ReviewReportPusher",
]
