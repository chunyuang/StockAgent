"""
市场情绪分析工具

根据涨跌停数据、连板高度、炸板率等指标判断市场情绪周期。
"""

from typing import Optional, List
from src.tools.registry import tool


@tool(
    name="get_market_sentiment",
    description="获取市场情绪分析，判断当前所处的情绪周期阶段",
    category="review",
    tags=["sentiment", "analysis"],
)
async def get_market_sentiment(
    trade_date: Optional[str] = None,
    history_days: int = 5,
) -> dict:
    """
    获取市场情绪分析
    
    Args:
        trade_date: 交易日期 (YYYYMMDD)，默认最近交易日
        history_days: 历史数据天数（用于判断趋势）
    
    Returns:
        市场情绪数据和周期判断
    """
    from core.managers import mongo_manager, data_source_manager
    from src.config import config_manager
    
    try:
        if not trade_date:
            trade_date, _ = await data_source_manager.get_latest_trade_date()
        
        db = mongo_manager.db
        
        result = {
            "trade_date": trade_date,
            "indicators": {},
            "phase": None,
            "phase_description": None,
            "signals": [],
        }
        
        # 1. 获取当日涨停数据
        limit_up_count = await db["review_limit"].count_documents({
            "trade_date": trade_date,
            "limit": "U"
        })
        
        limit_down_count = await db["review_limit"].count_documents({
            "trade_date": trade_date,
            "limit": "D"
        })
        
        # 2. 获取连板数据
        step_data = await db["review_limit_step"].find({
            "trade_date": trade_date
        }).to_list(None)
        
        first_board = sum(1 for s in step_data if s.get("step") == 1)
        continuous_board = sum(1 for s in step_data if s.get("step", 1) > 1)
        max_step = max((s.get("step", 1) for s in step_data), default=0)
        
        # 3. 计算炸板率
        limit_list = await db["review_limit"].find({
            "trade_date": trade_date,
            "limit": "U"
        }).to_list(None)
        
        broken_count = sum(1 for item in limit_list if (item.get("open_times") or 0) > 0)
        broken_rate = round(broken_count / limit_up_count * 100, 1) if limit_up_count > 0 else 0
        
        # 4. 填充指标
        result["indicators"] = {
            "limit_up": limit_up_count,
            "limit_down": limit_down_count,
            "first_board": first_board,
            "continuous_board": continuous_board,
            "max_step": max_step,
            "broken_rate": broken_rate,
            "limit_ratio": round(limit_up_count / max(limit_down_count, 1), 2),
        }
        
        # 5. 获取配置阈值
        sentiment_config = config_manager.get("review.sentiment", {})
        phases = sentiment_config.get("phases", {})
        
        # 6. 判断情绪阶段
        phase, description, signals = _determine_phase(
            result["indicators"],
            phases,
        )
        
        result["phase"] = phase
        result["phase_description"] = description
        result["signals"] = signals
        
        return result
        
    except Exception as e:
        return {"error": str(e)}


def _determine_phase(indicators: dict, phases_config: dict) -> tuple:
    """
    根据指标判断情绪阶段
    
    Returns:
        (phase_name, description, signals)
    """
    signals = []
    
    first_board = indicators.get("first_board", 0)
    max_step = indicators.get("max_step", 0)
    broken_rate = indicators.get("broken_rate", 0)
    limit_ratio = indicators.get("limit_ratio", 1)
    
    # 默认阈值
    ice_config = phases_config.get("ice_point", {})
    recovery_config = phases_config.get("recovery", {})
    high_tide_config = phases_config.get("high_tide", {})
    ebb_config = phases_config.get("ebb", {})
    
    # 冰点判断
    if first_board <= ice_config.get("first_board_max", 20):
        if broken_rate >= ice_config.get("high_open_rate_min", 0.6) * 100:
            signals.append("首板数量极少")
            signals.append("炸板率高")
            return (
                "ice_point",
                ice_config.get("description", "市场极度恐慌，机会大于风险"),
                signals,
            )
    
    # 高潮判断
    if first_board >= high_tide_config.get("first_board_min", 60):
        signals.append("首板数量较多")
        if max_step >= 5:
            signals.append(f"出现{max_step}连板高度股")
        return (
            "high_tide",
            high_tide_config.get("description", "市场情绪高涨，注意风险"),
            signals,
        )
    
    # 退潮判断
    if broken_rate >= 40:
        signals.append(f"炸板率高达{broken_rate}%")
        if max_step >= 5 and limit_ratio < 2:
            signals.append("高位股走弱")
            return (
                "ebb",
                ebb_config.get("description", "高位股退潮，注意回避"),
                signals,
            )
    
    # 修复期
    recovery_range = recovery_config.get("first_board_range", [20, 50])
    if recovery_range[0] <= first_board <= recovery_range[1]:
        signals.append("涨停数量适中")
        if broken_rate < 30:
            signals.append("炸板率可控")
        return (
            "recovery",
            recovery_config.get("description", "情绪逐步修复，可试探性参与"),
            signals,
        )
    
    # 默认返回中性
    return (
        "neutral",
        "市场情绪中性",
        signals,
    )


@tool(
    name="get_sentiment_history",
    description="获取市场情绪历史变化趋势",
    category="review",
    tags=["sentiment", "history"],
)
async def get_sentiment_history(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 10,
) -> dict:
    """
    获取市场情绪历史
    
    Args:
        start_date: 开始日期 (YYYYMMDD)
        end_date: 结束日期 (YYYYMMDD)
        limit: 返回天数
    
    Returns:
        历史情绪数据
    """
    from core.managers import mongo_manager, data_source_manager
    
    try:
        db = mongo_manager.db
        
        # 获取交易日列表
        if not end_date:
            end_date, _ = await data_source_manager.get_latest_trade_date()
        
        # 查询涨停统计
        pipeline = [
            {"$match": {"limit": "U"}},
            {"$group": {
                "_id": "$trade_date",
                "limit_up": {"$sum": 1},
            }},
            {"$sort": {"_id": -1}},
            {"$limit": limit},
        ]
        
        limit_stats = await db["review_limit"].aggregate(pipeline).to_list(None)
        
        # 查询连板数据
        result = []
        for stat in limit_stats:
            trade_date = stat["_id"]
            
            step_data = await db["review_limit_step"].find({
                "trade_date": trade_date
            }).to_list(None)
            
            first_board = sum(1 for s in step_data if s.get("step") == 1)
            max_step = max((s.get("step", 1) for s in step_data), default=0)
            
            result.append({
                "trade_date": trade_date,
                "limit_up": stat["limit_up"],
                "first_board": first_board,
                "max_step": max_step,
            })
        
        return {
            "count": len(result),
            "history": result,
        }
        
    except Exception as e:
        return {"error": str(e)}
