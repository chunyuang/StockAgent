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
# MCPNode / InferenceNode: 保留目录但不在启动时导入，需单独 NODE_TYPE=mcp/inference 启动
# from .mcp.node import MCPNode
# from .inference.node import InferenceNode
# ListenerNode已废弃(V54), 由MarketScanner取代

__all__ = [
    "BaseNode",
    "WebNode",
    "DataSyncNode",
    # "MCPNode",      # 需 NODE_TYPE=mcp 单独启动
    # "InferenceNode", # 需 NODE_TYPE=inference 单独启动
]
