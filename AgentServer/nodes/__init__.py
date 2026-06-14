"""
分布式节点

节点类型:
- WebNode: Web 网关节点
- DataSyncNode: 数据同步节点
"""

from .base import BaseNode
from .web.node import WebNode
from .data_sync.node import DataSyncNode

__all__ = [
    "BaseNode",
    "WebNode",
    "DataSyncNode",
]
