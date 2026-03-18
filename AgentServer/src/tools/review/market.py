"""
大盘分析工具

提供指数行情、北向资金等大盘相关数据查询。
"""

from typing import Optional, List
from src.tools.registry import tool


@tool(
    name="get_market_overview",
    description="获取大盘整体概况，包括三大指数涨跌、涨跌家数、北向资金等",
    category="review",
    tags=["market", "overview"],
)
async def get_market_overview(trade_date: Optional[str] = None) -> dict:
    """
    获取大盘整体概况
    
    Args:
        trade_date: 交易日期 (YYYYMMDD)，默认最近交易日
    
    Returns:
        大盘概况数据
    """
    from core.managers import mongo_manager, data_source_manager
    
    try:
        # 获取交易日期
        if not trade_date:
            trade_date, _ = await data_source_manager.get_latest_trade_date()
        
        db = mongo_manager.db
        
        result = {
            "trade_date": trade_date,
            "indices": [],
            "northbound": None,
            "limit_stats": None,
        }
        
        # 1. 获取指数数据
        indices = await db["review_index"].find(
            {"trade_date": trade_date}
        ).to_list(None)
        
        index_names = {
            "000001.SH": "上证指数",
            "399001.SZ": "深证成指",
            "399006.SZ": "创业板指",
        }
        
        for idx in indices:
            result["indices"].append({
                "code": idx.get("ts_code"),
                "name": index_names.get(idx.get("ts_code"), idx.get("ts_code")),
                "close": idx.get("close"),
                "change": idx.get("change"),
                "pct_chg": idx.get("pct_chg"),
                "vol": idx.get("vol"),
                "amount": idx.get("amount"),
            })
        
        # 2. 获取北向资金
        northbound = await db["review_northbound"].find_one({"trade_date": trade_date})
        if northbound:
            result["northbound"] = {
                "north_money": northbound.get("north_money"),
                "south_money": northbound.get("south_money"),
                "ggt_ss": northbound.get("ggt_ss"),
                "ggt_sz": northbound.get("ggt_sz"),
            }
        
        # 3. 获取涨跌停统计
        limit_up = await db["review_limit"].count_documents({
            "trade_date": trade_date,
            "limit": "U"
        })
        limit_down = await db["review_limit"].count_documents({
            "trade_date": trade_date,
            "limit": "D"
        })
        
        result["limit_stats"] = {
            "limit_up": limit_up,
            "limit_down": limit_down,
        }
        
        return result
        
    except Exception as e:
        return {"error": str(e)}


@tool(
    name="get_index_daily",
    description="获取指数日线数据，支持查询历史数据",
    category="review",
    tags=["market", "index"],
)
async def get_index_daily(
    ts_code: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 20,
) -> dict:
    """
    获取指数日线数据
    
    Args:
        ts_code: 指数代码 (000001.SH/399001.SZ/399006.SZ)
        start_date: 开始日期 (YYYYMMDD)
        end_date: 结束日期 (YYYYMMDD)
        limit: 返回条数
    
    Returns:
        指数日线数据列表
    """
    from core.managers import mongo_manager
    
    try:
        db = mongo_manager.db
        
        query = {"ts_code": ts_code}
        if start_date:
            query["trade_date"] = {"$gte": start_date}
        if end_date:
            if "trade_date" in query:
                query["trade_date"]["$lte"] = end_date
            else:
                query["trade_date"] = {"$lte": end_date}
        
        cursor = db["review_index"].find(query).sort("trade_date", -1).limit(limit)
        records = await cursor.to_list(limit)
        
        return {
            "ts_code": ts_code,
            "count": len(records),
            "data": [
                {
                    "trade_date": r.get("trade_date"),
                    "open": r.get("open"),
                    "high": r.get("high"),
                    "low": r.get("low"),
                    "close": r.get("close"),
                    "pct_chg": r.get("pct_chg"),
                    "vol": r.get("vol"),
                    "amount": r.get("amount"),
                }
                for r in records
            ],
        }
        
    except Exception as e:
        return {"error": str(e)}


@tool(
    name="get_northbound_flow",
    description="获取北向资金流向数据，支持查询历史数据",
    category="review",
    tags=["market", "northbound"],
)
async def get_northbound_flow(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 20,
) -> dict:
    """
    获取北向资金流向
    
    Args:
        start_date: 开始日期 (YYYYMMDD)
        end_date: 结束日期 (YYYYMMDD)
        limit: 返回条数
    
    Returns:
        北向资金数据列表
    """
    from core.managers import mongo_manager
    
    try:
        db = mongo_manager.db
        
        query = {}
        if start_date:
            query["trade_date"] = {"$gte": start_date}
        if end_date:
            if "trade_date" in query:
                query["trade_date"]["$lte"] = end_date
            else:
                query["trade_date"] = {"$lte": end_date}
        
        cursor = db["review_northbound"].find(query).sort("trade_date", -1).limit(limit)
        records = await cursor.to_list(limit)
        
        return {
            "count": len(records),
            "data": [
                {
                    "trade_date": r.get("trade_date"),
                    "north_money": r.get("north_money"),
                    "south_money": r.get("south_money"),
                    "ggt_ss": r.get("ggt_ss"),
                    "ggt_sz": r.get("ggt_sz"),
                }
                for r in records
            ],
        }
        
    except Exception as e:
        return {"error": str(e)}
