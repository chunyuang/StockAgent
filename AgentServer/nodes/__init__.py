"""
分布式节点

节点类型:
- WebNode: Web 网关节点
- DataSyncNode: 数据同步节点
- MCPNode: MCP 服务节点
- InferenceNode: 分析智能体节点
"""

from .base import BaseNode
from .web.node import WebNode
from .data_sync.node import DataSyncNode
# 已移除: scheduler(被scanner+data_sync替代), inference/mcp(未启用已清理)

__all__ = [
    "BaseNode",
    "WebNode",
    "DataSyncNode",
]
