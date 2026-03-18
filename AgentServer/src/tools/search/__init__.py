"""
搜索工具

提供互联网搜索和本地 RAG 搜索能力。
"""

from .tavily import search_web, search_stock_news
from .local_rag import search_local_news, search_similar_events

__all__ = [
    "search_web",
    "search_stock_news",
    "search_local_news",
    "search_similar_events",
]
