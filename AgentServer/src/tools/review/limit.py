"""
涨停分析工具

提供涨停概况、连板天梯、涨停列表等查询功能。
"""

from typing import Optional, List
from src.tools.registry import tool


@tool(
    name="get_limit_overview",
    description="获取涨停概况，包括涨停家数、炸板率、连板数分布等",
    category="review",
    tags=["limit", "overview"],
)
async def get_limit_overview(trade_date: Optional[str] = None) -> dict:
    """
    获取涨停概况
    
    Args:
        trade_date: 交易日期 (YYYYMMDD)，默认最近交易日
    
    Returns:
        涨停概况数据
    """
    from core.managers import mongo_manager, data_source_manager
    
    try:
        if not trade_date:
            trade_date, _ = await data_source_manager.get_latest_trade_date()
        
        db = mongo_manager.db
        
        result = {
            "trade_date": trade_date,
            "limit_up": 0,
            "limit_down": 0,
            "broken_rate": 0,
            "step_distribution": {},
            "first_board": 0,
            "continuous_board": 0,
        }
        
        # 1. 涨跌停统计
        limit_up_count = await db["review_limit"].count_documents({
            "trade_date": trade_date,
            "limit": "U"
        })
        limit_down_count = await db["review_limit"].count_documents({
            "trade_date": trade_date,
            "limit": "D"
        })
        
        result["limit_up"] = limit_up_count
        result["limit_down"] = limit_down_count
        
        # 2. 炸板率（需要从涨停列表中统计）
        limit_list = await db["review_limit"].find({
            "trade_date": trade_date,
            "limit": "U"
        }).to_list(None)
        
        broken_count = sum(1 for item in limit_list if (item.get("open_times") or 0) > 0)
        if limit_up_count > 0:
            result["broken_rate"] = round(broken_count / limit_up_count * 100, 1)
        
        # 3. 连板天梯分布
        step_data = await db["review_limit_step"].find({
            "trade_date": trade_date
        }).to_list(None)
        
        step_dist = {}
        for item in step_data:
            step = item.get("step", 1)
            if step not in step_dist:
                step_dist[step] = 0
            step_dist[step] += 1
        
        result["step_distribution"] = step_dist
        result["first_board"] = step_dist.get(1, 0)
        result["continuous_board"] = sum(
            count for step, count in step_dist.items() if step > 1
        )
        
        # 4. 最高板
        if step_data:
            max_step = max(item.get("step", 1) for item in step_data)
            result["max_step"] = max_step
            result["max_step_stocks"] = [
                {"ts_code": item.get("ts_code"), "name": item.get("name")}
                for item in step_data if item.get("step") == max_step
            ]
        
        return result
        
    except Exception as e:
        return {"error": str(e)}


@tool(
    name="get_limit_step",
    description="获取连板天梯，按连板数分层显示",
    category="review",
    tags=["limit", "step"],
)
async def get_limit_step(
    trade_date: Optional[str] = None,
    min_step: int = 1,
) -> dict:
    """
    获取连板天梯
    
    Args:
        trade_date: 交易日期 (YYYYMMDD)
        min_step: 最小连板数
    
    Returns:
        按连板数分层的股票列表
    """
    from core.managers import mongo_manager, data_source_manager
    
    try:
        if not trade_date:
            trade_date, _ = await data_source_manager.get_latest_trade_date()
        
        db = mongo_manager.db
        
        cursor = db["review_limit_step"].find({
            "trade_date": trade_date,
            "step": {"$gte": min_step}
        }).sort("step", -1)
        
        records = await cursor.to_list(None)
        
        # 按连板数分组
        step_groups = {}
        for r in records:
            step = r.get("step", 1)
            if step not in step_groups:
                step_groups[step] = []
            
            step_groups[step].append({
                "ts_code": r.get("ts_code"),
                "name": r.get("name"),
                "close": r.get("close"),
                "pct_chg": r.get("pct_chg"),
            })
        
        # 转换为有序列表
        result_list = [
            {"step": step, "stocks": stocks}
            for step, stocks in sorted(step_groups.items(), reverse=True)
        ]
        
        return {
            "trade_date": trade_date,
            "total": len(records),
            "steps": result_list,
        }
        
    except Exception as e:
        return {"error": str(e)}


@tool(
    name="get_limit_list",
    description="获取涨停/跌停股票列表",
    category="review",
    tags=["limit", "list"],
)
async def get_limit_list(
    trade_date: Optional[str] = None,
    limit_type: str = "U",
    sort_by: str = "first_time",
    limit: int = 50,
) -> dict:
    """
    获取涨停/跌停列表
    
    Args:
        trade_date: 交易日期 (YYYYMMDD)
        limit_type: U-涨停, D-跌停
        sort_by: first_time-首封时间, amount-成交额, limit_times-连板数
        limit: 返回数量
    
    Returns:
        涨跌停股票列表
    """
    from core.managers import mongo_manager, data_source_manager
    
    try:
        if not trade_date:
            trade_date, _ = await data_source_manager.get_latest_trade_date()
        
        db = mongo_manager.db
        
        query = {
            "trade_date": trade_date,
            "limit": limit_type,
        }
        
        # 排序
        sort_map = {
            "first_time": ("first_time", 1),
            "amount": ("amount", -1),
            "limit_times": ("limit_times", -1),
        }
        sort_field, sort_order = sort_map.get(sort_by, ("first_time", 1))
        
        cursor = db["review_limit"].find(query).sort(sort_field, sort_order).limit(limit)
        records = await cursor.to_list(limit)
        
        return {
            "trade_date": trade_date,
            "limit_type": "涨停" if limit_type == "U" else "跌停",
            "count": len(records),
            "stocks": [
                {
                    "ts_code": r.get("ts_code"),
                    "name": r.get("name"),
                    "industry": r.get("industry"),
                    "close": r.get("close"),
                    "pct_chg": r.get("pct_chg"),
                    "amount": r.get("amount"),
                    "first_time": r.get("first_time"),
                    "last_time": r.get("last_time"),
                    "open_times": r.get("open_times"),
                    "limit_times": r.get("limit_times"),
                    "up_stat": r.get("up_stat"),
                }
                for r in records
            ],
        }
        
    except Exception as e:
        return {"error": str(e)}


@tool(
    name="get_sector_limit_ranking",
    description="获取板块涨停家数排名",
    category="review",
    tags=["limit", "sector"],
)
async def get_sector_limit_ranking(
    trade_date: Optional[str] = None,
    limit: int = 20,
) -> dict:
    """
    获取板块涨停家数排名
    
    Args:
        trade_date: 交易日期 (YYYYMMDD)
        limit: 返回数量
    
    Returns:
        板块涨停排名列表
    """
    from core.managers import mongo_manager, data_source_manager
    
    try:
        if not trade_date:
            trade_date, _ = await data_source_manager.get_latest_trade_date()
        
        db = mongo_manager.db
        
        cursor = db["review_sector_limit"].find({
            "trade_date": trade_date
        }).sort("up_num", -1).limit(limit)
        
        records = await cursor.to_list(limit)
        
        return {
            "trade_date": trade_date,
            "count": len(records),
            "sectors": [
                {
                    "ts_code": r.get("ts_code"),
                    "name": r.get("name"),
                    "up_num": r.get("up_num"),
                    "down_num": r.get("down_num"),
                    "up_rate": r.get("up_rate"),
                }
                for r in records
            ],
        }
        
    except Exception as e:
        return {"error": str(e)}
