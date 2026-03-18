"""
本地 RAG 搜索工具

使用 Milvus 向量库进行语义搜索。
"""

import logging
from typing import Optional, List
from datetime import datetime, timedelta

from src.tools.registry import tool

logger = logging.getLogger(__name__)


@tool(
    name="search_local_news",
    description="从本地新闻库搜索相关新闻（基于语义相似度）",
    category="search",
    tags=["rag", "semantic", "news"],
)
async def search_local_news(
    query: str,
    ts_code: str = None,
    limit: int = 10,
) -> dict:
    """
    本地新闻语义搜索
    
    Args:
        query: 搜索关键词/描述
        ts_code: 股票代码 (可选，用于过滤)
        limit: 返回数量 (默认10)
    
    Returns:
        相似新闻列表
    """
    try:
        from core.managers import milvus_manager
        from src.llm import llm_service
        
        # 检查 Milvus 是否可用
        if not milvus_manager.is_initialized:
            await milvus_manager.initialize()
        
        # 生成查询向量
        if not llm_service._initialized:
            await llm_service.initialize()
        
        query_vector = await llm_service.embedding(query)
        
        # 构建过滤条件
        filter_expr = None
        if ts_code:
            filter_expr = f'ts_code == "{ts_code}"'
        
        # 搜索 Milvus
        collection_name = milvus_manager._config.market_snippets_collection
        results = await milvus_manager.search(
            collection=collection_name,
            vector=query_vector,
            limit=limit,
            filter_expr=filter_expr,
        )
        
        return {
            "query": query,
            "ts_code": ts_code,
            "count": len(results),
            "results": [
                {
                    "title": r.get("title"),
                    "content": r.get("content", "")[:300],
                    "source": r.get("source"),
                    "date": str(r.get("news_datetime")) if r.get("news_datetime") else None,
                    "score": r.get("score"),
                    "ts_codes": r.get("ts_codes", []),
                }
                for r in results
            ],
        }
    except Exception as e:
        logger.error(f"Local RAG search error: {e}")
        return {"error": str(e), "query": query}


@tool(
    name="search_similar_events",
    description="搜索与给定事件相似的历史事件",
    category="search",
    tags=["rag", "event", "historical"],
)
async def search_similar_events(
    event_description: str,
    category: str = None,
    limit: int = 5,
) -> dict:
    """
    搜索相似历史事件
    
    Args:
        event_description: 事件描述
        category: 事件分类 (policy/international/intl_economy/intl_commodity/industry/company/market/tech)
        limit: 返回数量 (默认5)
    
    Returns:
        相似事件列表
    """
    try:
        from core.managers import milvus_manager
        from src.llm import llm_service
        
        if not milvus_manager.is_initialized:
            await milvus_manager.initialize()
        
        if not llm_service._initialized:
            await llm_service.initialize()
        
        # 生成查询向量
        query_vector = await llm_service.embedding(event_description)
        
        # 构建过滤条件
        filter_expr = None
        if category:
            filter_expr = f'category == "{category}"'
        
        # 搜索事件集合
        collection_name = milvus_manager._config.event_collection
        results = await milvus_manager.search(
            collection=collection_name,
            vector=query_vector,
            limit=limit,
            filter_expr=filter_expr,
        )
        
        return {
            "query": event_description,
            "category": category,
            "count": len(results),
            "events": [
                {
                    "title": r.get("title"),
                    "summary": r.get("summary", "")[:200],
                    "category": r.get("category"),
                    "date": str(r.get("event_time")) if r.get("event_time") else None,
                    "score": r.get("score"),
                    "importance": r.get("importance"),
                }
                for r in results
            ],
        }
    except Exception as e:
        logger.error(f"Similar events search error: {e}")
        return {"error": str(e)}
