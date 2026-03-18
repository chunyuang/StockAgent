"""
Tavily 搜索工具

使用 Tavily API 进行互联网搜索。
"""

import logging
from typing import Optional, List
from urllib.parse import urlparse

from src.tools.registry import tool

logger = logging.getLogger(__name__)


def _extract_domain(url: str) -> str:
    """提取域名"""
    try:
        parsed = urlparse(url)
        return parsed.netloc.replace("www.", "")
    except Exception:
        return ""


async def _search_tavily(
    query: str,
    max_results: int = 5,
    search_depth: str = "advanced",
    days: int = 7,
) -> dict:
    """
    调用 Tavily API 搜索
    
    Args:
        query: 搜索关键词
        max_results: 最大结果数
        search_depth: 搜索深度 (basic/advanced)
        days: 限制最近几天
    
    Returns:
        搜索结果
    """
    from core.settings import settings
    
    api_keys = getattr(settings, "tavily_api_keys", None)
    if not api_keys:
        return {"error": "Tavily API key not configured"}
    
    try:
        from tavily import TavilyClient
        
        client = TavilyClient(api_key=api_keys[0])
        response = client.search(
            query=query,
            search_depth=search_depth,
            max_results=max_results,
            days=days,
        )
        
        return {
            "query": query,
            "results": [
                {
                    "title": r.get("title"),
                    "snippet": (r.get("content") or "")[:500],
                    "url": r.get("url"),
                    "source": _extract_domain(r.get("url", "")),
                    "score": r.get("score"),
                }
                for r in response.get("results", [])
            ],
        }
    except ImportError:
        return {"error": "tavily package not installed. Run: pip install tavily-python"}
    except Exception as e:
        logger.error(f"Tavily search error: {e}")
        return {"error": str(e)}


@tool(
    name="search_web",
    description="使用互联网搜索引擎搜索最新信息",
    category="search",
    tags=["web", "internet"],
)
async def search_web(
    query: str,
    max_results: int = 5,
    days: int = 7,
) -> dict:
    """
    互联网搜索
    
    Args:
        query: 搜索关键词
        max_results: 最大返回数量 (默认5)
        days: 限制最近几天的结果 (默认7天)
    
    Returns:
        搜索结果列表
    """
    return await _search_tavily(query, max_results=max_results, days=days)


@tool(
    name="search_stock_news",
    description="搜索股票相关的最新新闻和公告",
    category="search",
    tags=["stock", "news", "web"],
)
async def search_stock_news(
    stock_name: str,
    stock_code: str = None,
    max_results: int = 5,
) -> dict:
    """
    搜索股票相关新闻
    
    Args:
        stock_name: 股票名称
        stock_code: 股票代码 (可选，提高准确性)
        max_results: 最大返回数量 (默认5)
    
    Returns:
        新闻搜索结果
    """
    # 构建搜索词
    search_terms = [stock_name]
    if stock_code:
        # 去掉后缀
        code = stock_code.split(".")[0] if "." in stock_code else stock_code
        search_terms.append(code)
    
    query = f"{' '.join(search_terms)} 股票 最新消息"
    
    result = await _search_tavily(query, max_results=max_results, days=3)
    
    if "error" not in result:
        result["stock_name"] = stock_name
        result["stock_code"] = stock_code
    
    return result
