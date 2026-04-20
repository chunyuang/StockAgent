"""
热股分析工具

提供同花顺热股排行榜查询功能。
"""

from typing import Optional
from src.tools.registry import tool


@tool(
    name="get_hot_stocks",
    description="获取同花顺热股排行榜",
    category="review",
    tags=["hot", "ranking"],
)
async def get_hot_stocks(
    trade_date: Optional[str] = None,
    limit: int = 30,
) -> dict:
    """
    获取热股排行榜
    
    Args:
        trade_date: 交易日期 (YYYYMMDD)，默认最近交易日
        limit: 返回数量
    
    Returns:
        热股排行数据
    """
    from core.managers import mongo_manager, data_source_manager
    
    try:
        if not trade_date:
            trade_date, _ = await data_source_manager.get_latest_trade_date()
        
        db = mongo_manager.db
        
        cursor = db["review_hot"].find({
            "trade_date": trade_date
        }).sort("rank", 1).limit(limit)
        
        records = await cursor.to_list(limit)
        
        return {
            "trade_date": trade_date,
            "count": len(records),
            "stocks": [
                {
                    "rank": r.get("rank"),
                    "ts_code": r.get("ts_code"),
                    "name": r.get("name"),
                    "pct_change": r.get("pct_change"),
                    "hot": r.get("hot"),
                    "tag": r.get("tag"),
                }
                for r in records
            ],
        }
        
    except Exception as e:
        return {"error": str(e)}


@tool(
    name="get_stock_hot_history",
    description="获取个股的热度历史变化",
    category="review",
    tags=["hot", "history"],
)
async def get_stock_hot_history(
    ts_code: str,
    limit: int = 20,
) -> dict:
    """
    获取个股热度历史
    
    Args:
        ts_code: 股票代码
        limit: 返回天数
    
    Returns:
        个股热度历史
    """
    from core.managers import mongo_manager
    
    try:
        db = mongo_manager.db
        
        cursor = db["review_hot"].find({
            "ts_code": ts_code
        }).sort("trade_date", -1).limit(limit)
        
        records = await cursor.to_list(limit)
        
        return {
            "ts_code": ts_code,
            "count": len(records),
            "history": [
                {
                    "trade_date": r.get("trade_date"),
                    "rank": r.get("rank"),
                    "hot": r.get("hot"),
                    "pct_change": r.get("pct_change"),
                    "tag": r.get("tag"),
                }
                for r in records
            ],
        }
        
    except Exception as e:
        return {"error": str(e)}


@tool(
    name="search_hot_stocks_by_tag",
    description="按标签搜索热股（如涨停、连板等）",
    category="review",
    tags=["hot", "search"],
)
async def search_hot_stocks_by_tag(
    tag: str,
    trade_date: Optional[str] = None,
    limit: int = 20,
) -> dict:
    """
    按标签搜索热股
    
    Args:
        tag: 标签关键词（如 涨停、连板、热门）
        trade_date: 交易日期 (YYYYMMDD)
        limit: 返回数量
    
    Returns:
        匹配的热股列表
    """
    from core.managers import mongo_manager, data_source_manager
    
    try:
        if not trade_date:
            trade_date, _ = await data_source_manager.get_latest_trade_date()
        
        db = mongo_manager.db
        
        cursor = db["review_hot"].find({
            "trade_date": trade_date,
            "tag": {"$regex": tag, "$options": "i"},
        }).sort("rank", 1).limit(limit)
        
        records = await cursor.to_list(limit)
        
        return {
            "trade_date": trade_date,
            "tag_filter": tag,
            "count": len(records),
            "stocks": [
                {
                    "rank": r.get("rank"),
                    "ts_code": r.get("ts_code"),
                    "name": r.get("name"),
                    "pct_change": r.get("pct_change"),
                    "hot": r.get("hot"),
                    "tag": r.get("tag"),
                }
                for r in records
            ],
        }
        
    except Exception as e:
        return {"error": str(e)}
