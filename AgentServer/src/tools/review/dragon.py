"""
龙虎榜分析工具

提供龙虎榜数据、游资追踪等功能。
"""

from typing import Optional, List
from src.tools.registry import tool


@tool(
    name="get_dragon_list",
    description="获取龙虎榜数据，包括机构和游资买卖情况",
    category="review",
    tags=["dragon", "institution"],
)
async def get_dragon_list(
    trade_date: Optional[str] = None,
    ts_code: Optional[str] = None,
    sort_by: str = "net_buy",
    limit: int = 30,
) -> dict:
    """
    获取龙虎榜数据
    
    Args:
        trade_date: 交易日期 (YYYYMMDD)
        ts_code: 股票代码（可选，不传则返回全部）
        sort_by: net_buy-净买入, buy-买入额
        limit: 返回数量
    
    Returns:
        龙虎榜数据
    """
    from core.managers import mongo_manager, data_source_manager
    
    try:
        if not trade_date:
            trade_date, _ = await data_source_manager.get_latest_trade_date()
        
        db = mongo_manager.db
        
        query = {"trade_date": trade_date}
        if ts_code:
            query["ts_code"] = ts_code
        
        sort_field = "net_buy" if sort_by == "net_buy" else "buy"
        
        cursor = db["review_dragon"].find(query).sort(sort_field, -1).limit(limit)
        records = await cursor.to_list(limit)
        
        return {
            "trade_date": trade_date,
            "count": len(records),
            "data": [
                {
                    "ts_code": r.get("ts_code"),
                    "exalter": r.get("exalter"),
                    "buy": r.get("buy"),
                    "buy_rate": r.get("buy_rate"),
                    "sell": r.get("sell"),
                    "sell_rate": r.get("sell_rate"),
                    "net_buy": r.get("net_buy"),
                    "side": "买入" if r.get("side") == 0 else "卖出",
                }
                for r in records
            ],
        }
        
    except Exception as e:
        return {"error": str(e)}


@tool(
    name="get_hot_money_tracks",
    description="获取知名游资营业部的近期操作",
    category="review",
    tags=["dragon", "hot_money"],
)
async def get_hot_money_tracks(
    exalter: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 30,
) -> dict:
    """
    获取游资操作记录
    
    Args:
        exalter: 营业部名称（模糊匹配）
        start_date: 开始日期 (YYYYMMDD)
        end_date: 结束日期 (YYYYMMDD)
        limit: 返回数量
    
    Returns:
        游资操作记录
    """
    from core.managers import mongo_manager
    
    try:
        db = mongo_manager.db
        
        query = {}
        
        if exalter:
            query["exalter"] = {"$regex": exalter, "$options": "i"}
        
        if start_date:
            query["trade_date"] = {"$gte": start_date}
        if end_date:
            if "trade_date" in query:
                query["trade_date"]["$lte"] = end_date
            else:
                query["trade_date"] = {"$lte": end_date}
        
        cursor = db["review_dragon"].find(query).sort("trade_date", -1).limit(limit)
        records = await cursor.to_list(limit)
        
        return {
            "exalter_filter": exalter,
            "count": len(records),
            "data": [
                {
                    "trade_date": r.get("trade_date"),
                    "ts_code": r.get("ts_code"),
                    "exalter": r.get("exalter"),
                    "buy": r.get("buy"),
                    "sell": r.get("sell"),
                    "net_buy": r.get("net_buy"),
                    "side": "买入" if r.get("side") == 0 else "卖出",
                }
                for r in records
            ],
        }
        
    except Exception as e:
        return {"error": str(e)}


@tool(
    name="get_stock_dragon_history",
    description="获取个股的龙虎榜历史",
    category="review",
    tags=["dragon", "stock"],
)
async def get_stock_dragon_history(
    ts_code: str,
    limit: int = 20,
) -> dict:
    """
    获取个股龙虎榜历史
    
    Args:
        ts_code: 股票代码
        limit: 返回数量
    
    Returns:
        个股龙虎榜历史
    """
    from core.managers import mongo_manager
    
    try:
        db = mongo_manager.db
        
        cursor = db["review_dragon"].find({
            "ts_code": ts_code
        }).sort("trade_date", -1).limit(limit)
        
        records = await cursor.to_list(limit)
        
        # 按日期聚合
        date_groups = {}
        for r in records:
            trade_date = r.get("trade_date")
            if trade_date not in date_groups:
                date_groups[trade_date] = {
                    "trade_date": trade_date,
                    "buyers": [],
                    "sellers": [],
                    "net_buy_total": 0,
                }
            
            item = {
                "exalter": r.get("exalter"),
                "buy": r.get("buy"),
                "sell": r.get("sell"),
                "net_buy": r.get("net_buy"),
            }
            
            if r.get("side") == 0:
                date_groups[trade_date]["buyers"].append(item)
            else:
                date_groups[trade_date]["sellers"].append(item)
            
            date_groups[trade_date]["net_buy_total"] += r.get("net_buy", 0)
        
        result_list = sorted(date_groups.values(), key=lambda x: x["trade_date"], reverse=True)
        
        return {
            "ts_code": ts_code,
            "count": len(result_list),
            "history": result_list,
        }
        
    except Exception as e:
        return {"error": str(e)}
