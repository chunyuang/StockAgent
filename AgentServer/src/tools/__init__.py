"""
工具层

提供 Agent 可调用的工具：
- 数据工具 (data): 股票行情、K线、财务数据
- 搜索工具 (search): Tavily、本地RAG
- 分析工具 (analysis): 技术指标、情感分析
- 复盘工具 (review): 大盘、板块、涨停、龙虎榜、情绪
"""

from .registry import (
    ToolParameter,
    ToolDefinition,
    ToolRegistry,
    tool_registry,
    tool,
)
from .base import BaseTool, ToolResult

__all__ = [
    "ToolParameter",
    "ToolDefinition",
    "ToolRegistry",
    "tool_registry",
    "tool",
    "BaseTool",
    "ToolResult",
]


def register_all_tools():
    """注册所有工具"""
    from .data import register_all_data_tools
    from .review import register_all_review_tools
    
    register_all_data_tools()
    register_all_review_tools()
