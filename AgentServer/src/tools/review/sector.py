"""
板块分析工具

提供板块涨跌、板块成分、个股-板块映射等查询功能。
"""

from typing import Optional, List
from src.tools.registry import tool


@tool(
    name="get_top_sectors",
    description="获取当日涨幅/跌幅前N的板块",
    category="review",
    tags=["sector", "ranking"],
)
async def get_top_sectors(
    trade_date: Optional[str] = None,
    direction: str = "up",
    sector_type: Optional[str] = None,
    limit: int = 10,
) -> dict:
    """
    获取涨跌幅排名靠前的板块
    
    Args:
        trade_date: 交易日期 (YYYYMMDD)，默认最近交易日
        direction: up-涨幅榜, down-跌幅榜
        sector_type: N-概念, I-行业, 不传则全部
        limit: 返回数量
    
    Returns:
        板块排名列表
    """
    from core.managers import mongo_manager, data_source_manager
    
    try:
        if not trade_date:
            trade_date, _ = await data_source_manager.get_latest_trade_date()
        
        db = mongo_manager.db
        
        # 查询板块日线
        query = {"trade_date": trade_date}
        
        sort_order = -1 if direction == "up" else 1
        
        cursor = db["review_sector_daily"].find(query).sort("pct_change", sort_order).limit(limit)
        records = await cursor.to_list(limit)
        
        # 补充板块类型信息
        result = []
        for r in records:
            sector_info = await db["ths_sectors"].find_one({"ts_code": r.get("ts_code")})
            
            item = {
                "ts_code": r.get("ts_code"),
                "name": r.get("name") or (sector_info.get("name") if sector_info else ""),
                "pct_change": r.get("pct_change"),
                "close": r.get("close"),
                "vol": r.get("vol"),
                "turnover_rate": r.get("turnover_rate"),
                "sector_type": sector_info.get("sector_type") if sector_info else None,
                "type_name": sector_info.get("type_name") if sector_info else None,
            }
            
            # 如果指定了板块类型，则过滤
            if sector_type and item["sector_type"] != sector_type:
                continue
            
            result.append(item)
        
        return {
            "trade_date": trade_date,
            "direction": direction,
            "count": len(result),
            "sectors": result[:limit],
        }
        
    except Exception as e:
        return {"error": str(e)}


@tool(
    name="get_sector_detail",
    description="获取板块详细信息，包括涨停家数、成分股表现等",
    category="review",
    tags=["sector", "detail"],
)
async def get_sector_detail(
    ts_code: str,
    trade_date: Optional[str] = None,
) -> dict:
    """
    获取板块详细信息
    
    Args:
        ts_code: 板块代码
        trade_date: 交易日期 (YYYYMMDD)
    
    Returns:
        板块详细数据
    """
    from core.managers import mongo_manager, data_source_manager
    
    try:
        if not trade_date:
            trade_date, _ = await data_source_manager.get_latest_trade_date()
        
        db = mongo_manager.db
        
        result = {
            "ts_code": ts_code,
            "trade_date": trade_date,
        }
        
        # 1. 板块基本信息
        sector_info = await db["ths_sectors"].find_one({"ts_code": ts_code})
        if sector_info:
            result["name"] = sector_info.get("name")
            result["sector_type"] = sector_info.get("sector_type")
            result["stock_count"] = sector_info.get("count")
        
        # 2. 板块日线数据
        daily = await db["review_sector_daily"].find_one({
            "ts_code": ts_code,
            "trade_date": trade_date,
        })
        if daily:
            result["pct_change"] = daily.get("pct_change")
            result["close"] = daily.get("close")
            result["vol"] = daily.get("vol")
            result["turnover_rate"] = daily.get("turnover_rate")
        
        # 3. 板块涨停统计
        limit_stats = await db["review_sector_limit"].find_one({
            "ts_code": ts_code,
            "trade_date": trade_date,
        })
        if limit_stats:
            result["limit_up_num"] = limit_stats.get("up_num")
            result["limit_down_num"] = limit_stats.get("down_num")
            result["up_rate"] = limit_stats.get("up_rate")
        
        # 4. 板块成分股列表
        sector_stocks = await db["sector_stocks"].find_one({"ts_code": ts_code})
        if sector_stocks:
            result["component_stocks"] = sector_stocks.get("stocks", [])[:20]
        
        return result
        
    except Exception as e:
        return {"error": str(e)}


@tool(
    name="get_stock_sectors",
    description="查询个股所属的所有板块",
    category="review",
    tags=["sector", "mapping"],
)
async def get_stock_sectors(stock_code: str) -> dict:
    """
    查询个股所属板块
    
    Args:
        stock_code: 6位股票代码
    
    Returns:
        所属板块列表
    """
    from core.managers import mongo_manager
    
    try:
        db = mongo_manager.db
        
        doc = await db["stock_sector_map"].find_one({"code": stock_code})
        
        if not doc:
            return {"code": stock_code, "sectors": [], "count": 0}
        
        return {
            "code": stock_code,
            "sectors": doc.get("sectors", []),
            "count": doc.get("sector_count", 0),
        }
        
    except Exception as e:
        return {"error": str(e)}


@tool(
    name="get_sector_stocks",
    description="查询板块的成分股列表",
    category="review",
    tags=["sector", "mapping"],
)
async def get_sector_stocks(
    ts_code: str,
    limit: int = 50,
) -> dict:
    """
    查询板块成分股
    
    Args:
        ts_code: 板块代码
        limit: 返回数量
    
    Returns:
        成分股列表
    """
    from core.managers import mongo_manager
    
    try:
        db = mongo_manager.db
        
        doc = await db["sector_stocks"].find_one({"ts_code": ts_code})
        
        if not doc:
            return {"ts_code": ts_code, "stocks": [], "count": 0}
        
        stocks = doc.get("stocks", [])[:limit]
        
        return {
            "ts_code": ts_code,
            "name": doc.get("name"),
            "stocks": stocks,
            "count": len(stocks),
            "total_count": doc.get("stock_count", 0),
        }
        
    except Exception as e:
        return {"error": str(e)}


@tool(
    name="get_common_sectors",
    description="查找多只股票的共同板块",
    category="review",
    tags=["sector", "analysis"],
)
async def get_common_sectors(
    stock_codes: List[str],
    min_overlap: int = 2,
) -> dict:
    """
    查找多只股票的共同板块
    
    Args:
        stock_codes: 股票代码列表
        min_overlap: 最小重叠数量
    
    Returns:
        共同板块列表
    """
    from core.managers import mongo_manager
    
    try:
        db = mongo_manager.db
        
        # 获取每只股票的板块
        sector_counts = {}
        
        for code in stock_codes:
            doc = await db["stock_sector_map"].find_one({"code": code})
            if doc:
                for sector in doc.get("sectors", []):
                    ts_code = sector["ts_code"]
                    if ts_code not in sector_counts:
                        sector_counts[ts_code] = {
                            "ts_code": ts_code,
                            "name": sector["name"],
                            "count": 0,
                            "stocks": [],
                        }
                    sector_counts[ts_code]["count"] += 1
                    sector_counts[ts_code]["stocks"].append(code)
        
        # 过滤并排序
        result = [
            s for s in sector_counts.values()
            if s["count"] >= min_overlap
        ]
        result.sort(key=lambda x: x["count"], reverse=True)
        
        return {
            "input_stocks": stock_codes,
            "common_sectors": result,
            "count": len(result),
        }
        
    except Exception as e:
        return {"error": str(e)}
