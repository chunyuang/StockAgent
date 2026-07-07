"""
止损止盈分析 API — 展示策略配置、实盘执行、优化前后对比
用于交易归档页面下的止损止盈子页面
"""
import logging
from typing import List, Optional
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from core.managers import mongo_manager

router = APIRouter(prefix="/stop-loss-analysis", tags=["StopLossAnalysis"])
logger = logging.getLogger("api.stop_loss_analysis")

COL_ORDERS = "broker_orders"
COL_RISK_DECISIONS = "risk_decisions"

# ==================== 优化前后的参数配置 ====================

# 优化前(v2.9.115之前): 固定止损, 无ATR, 无分批止盈
PRE_OPTIMIZATION_CONFIG = {
    "version": "v2.9.115 (优化前)",
    "stop_loss": {
        "type": "固定止损",
        "default_pct": 3.0,
        "strategy_pct": {
            "halfway_chase": 3.0,
            "first_limit_up": 3.5,
            "limit_up_open": 5.0,
            "dragon_head": 3.0,
            "limit_down_qiao": 5.0,
        },
        "atr_adaptive": False,
        "description": "所有股票统一固定止损百分比, 不考虑个股波动率差异",
    },
    "take_profit": {
        "type": "固定止盈",
        "default_pct": 7.0,
        "strategy_pct": {
            "halfway_chase": 12.0,
            "first_limit_up": 10.0,
            "limit_up_open": 6.0,
            "dragon_head": 30.0,
            "limit_down_qiao": 20.0,
        },
        "partial_take_profit": False,
        "description": "到达止盈线一次性全部卖出",
    },
    "trailing_stop": {
        "type": "追踪止损",
        "base_pct": 5.0,
        "activate_threshold": {
            "halfway_chase": 2.0,
            "first_limit_up": 2.0,
            "limit_up_open": 2.0,
            "dragon_head": 3.0,
            "limit_down_qiao": 4.0,
        },
        "strategy_offsets": "无差异化(统一5%base)",
        "high_profit_tighten": False,
        "description": "盈利达激活阈值后, 从最高价回撤5%触发卖出",
    },
    "gap_stop": {
        "type": "跳空止损",
        "observation_period": "无观察期, 立即止损",
        "market_filter": False,
        "description": "开盘价低于止损价立即以开盘价卖出",
    },
}

# 优化后(v2.9.119): ATR自适应 + 分批止盈 + 高盈利紧缩 + 分级追踪
POST_OPTIMIZATION_CONFIG = {
    "version": "v2.9.119 (优化后)",
    "stop_loss": {
        "type": "ATR自适应止损",
        "default_pct": 3.0,
        "atr_multiplier": 1.2,
        "atr_period": 14,
        "strategy_atr_ranges": {
            "halfway_chase": {"min": 3.0, "max": 6.0},
            "first_limit_up": {"min": 3.5, "max": 7.0},
            "limit_up_open": {"min": 4.0, "max": 7.0},
            "dragon_head": {"min": 3.0, "max": 7.0},
            "limit_down_qiao": {"min": 5.0, "max": 8.0},
        },
        "atr_adaptive": True,
        "description": "stop_loss = min(max(strategy_min, 1.2*ATR14%), strategy_max), 封顶防止高波动股单笔亏损过大",
    },
    "take_profit": {
        "type": "分批止盈",
        "default_pct": 7.0,
        "strategy_pct": {
            "halfway_chase": 12.0,
            "first_limit_up": 10.0,
            "limit_up_open": 6.0,
            "dragon_head": 30.0,
            "limit_down_qiao": 20.0,
        },
        "partial_take_profit": True,
        "partial_threshold": 8.0,
        "partial_ratio": 0.5,
        "description": "盈利≥8%先卖50%锁定利润, 剩余继续持有等止盈或追踪止损",
    },
    "trailing_stop": {
        "type": "分级追踪止损",
        "base_pct": 5.0,
        "min_activate_pct": 3.0,
        "activate_threshold": {
            "halfway_chase": "max(2%, 3%)=3%",
            "first_limit_up": "max(2%, 3%)=3%",
            "limit_up_open": "max(2%, 3%)=3%",
            "dragon_head": "max(3%, 3%)=3%",
            "limit_down_qiao": "max(4%, 3%)=4%",
        },
        "strategy_offsets": {
            "first_limit_up": [0.03, 0.06, 0.10, 0.13],
            "limit_up_open": [0.00, 0.03, 0.06, 0.09],
            "dragon_head": [0.02, 0.04, 0.07, 0.10],
            "halfway_chase": [0.01, 0.03, 0.06, 0.09],
            "limit_down_qiao": [0.00, 0.02, 0.05, 0.08],
        },
        "high_profit_tighten": True,
        "high_profit_threshold": 8.0,
        "high_profit_tighten_pct": 3.0,
        "description": "盈利≥3%激活; 5策略差异化回撤; 盈利≥8%回撤收紧到3%",
    },
    "gap_stop": {
        "type": "分级跳空止损",
        "observation_period": {
            "micro_gap": "<3% → 观察30min",
            "medium_gap": "3-5% → 观察10min",
            "large_gap": ">5% → 立即止损(大盘强势>0.5%且跳空<8%时观察5min)",
        },
        "market_filter": True,
        "description": "按跳空幅度分级处理, 大盘强势时给观察期避免误杀",
    },
}


# ==================== 响应模型 ====================

class StopLossConfigItem(BaseModel):
    """止损止盈配置项"""
    category: str
    pre_optimization: dict
    post_optimization: dict


class StopLossExecution(BaseModel):
    """实盘止损止盈执行记录"""
    ts_code: str = ""
    stock_name: str = ""
    strategy: str = ""
    side: str = ""
    filled_price: float = 0
    filled_qty: int = 0
    profit_pct: float = 0
    profit_amount: float = 0
    reason: str = ""
    trade_date: int = 0
    fill_time: str = ""
    sell_type: str = ""  # 跳空止损/固定止损/追踪止损/止盈/冲高回落/分批止盈/强制空仓


class StopLossStats(BaseModel):
    """止损止盈统计"""
    total_sells: int = 0
    total_pnl: float = 0
    win_rate: float = 0
    by_type: List[dict] = []


class StopLossAnalysisResponse(BaseModel):
    """止损止盈分析响应"""
    config: List[StopLossConfigItem] = []
    executions: List[StopLossExecution] = []
    stats: StopLossStats = StopLossStats()


# ==================== API ====================

@router.get("/config", response_model=List[StopLossConfigItem])
async def get_stop_loss_config():
    """获取止损止盈配置(优化前后对比)"""
    items = []
    for category in ["stop_loss", "take_profit", "trailing_stop", "gap_stop"]:
        items.append(StopLossConfigItem(
            category=category,
            pre_optimization=PRE_OPTIMIZATION_CONFIG.get(category, {}),
            post_optimization=POST_OPTIMIZATION_CONFIG.get(category, {}),
        ))
    return items


@router.get("/executions", response_model=List[StopLossExecution])
async def get_stop_loss_executions(
    trade_date: Optional[int] = Query(default=None, description="交易日, 不传则返回全部"),
    limit: int = Query(default=200, ge=1, le=500),
):
    """获取实盘止损止盈执行记录"""
    query = {"side": "sell", "status": "filled"}
    if trade_date:
        query["trade_date"] = trade_date

    cursor = mongo_manager.db[COL_ORDERS].find(query).sort("trade_date", -1).limit(limit)
    results = []
    async for doc in cursor:
        reason = doc.get("reason", "") or ""
        sell_type = _classify_sell_reason(reason)
        results.append(StopLossExecution(
            ts_code=doc.get("ts_code", ""),
            stock_name=doc.get("stock_name", ""),
            strategy=doc.get("strategy", ""),
            side=doc.get("side", ""),
            filled_price=doc.get("filled_price", 0) or 0,
            filled_qty=doc.get("filled_qty", 0) or 0,
            profit_pct=doc.get("profit_pct", 0) or 0,
            profit_amount=doc.get("profit_amount", 0) or 0,
            reason=reason,
            trade_date=int(doc.get("trade_date", 0) or 0),
            fill_time=str(doc.get("fill_time", "") or doc.get("created_at", "")),
            sell_type=sell_type,
        ))
    return results


@router.get("/stats", response_model=StopLossStats)
async def get_stop_loss_stats(
    trade_date: Optional[int] = Query(default=None, description="交易日, 不传则返回全部"),
):
    """获取止损止盈统计"""
    query = {"side": "sell", "status": "filled"}
    if trade_date:
        query["trade_date"] = trade_date

    cursor = mongo_manager.db[COL_ORDERS].find(query)
    sells = []
    async for doc in cursor:
        reason = doc.get("reason", "") or ""
        sells.append({
            "profit_amount": doc.get("profit_amount", 0) or 0,
            "profit_pct": doc.get("profit_pct", 0) or 0,
            "sell_type": _classify_sell_reason(reason),
            "reason": reason,
        })

    total = len(sells)
    total_pnl = sum(s["profit_amount"] for s in sells)
    wins = sum(1 for s in sells if s["profit_amount"] > 0)
    win_rate = (wins / total * 100) if total > 0 else 0

    # 按类型分组
    type_map = {}
    for s in sells:
        st = s["sell_type"]
        if st not in type_map:
            type_map[st] = {"sell_type": st, "count": 0, "total_pnl": 0.0, "wins": 0, "avg_pct": 0.0}
        type_map[st]["count"] += 1
        type_map[st]["total_pnl"] += s["profit_amount"]
        if s["profit_amount"] > 0:
            type_map[st]["wins"] += 1
        type_map[st]["avg_pct"] += s["profit_pct"]

    by_type = []
    for st, v in sorted(type_map.items(), key=lambda x: x[1]["count"], reverse=True):
        by_type.append({
            "sell_type": st,
            "count": v["count"],
            "total_pnl": round(v["total_pnl"], 0),
            "win_rate": round(v["wins"] / v["count"] * 100, 1) if v["count"] else 0,
            "avg_pct": round(v["avg_pct"] / v["count"], 1) if v["count"] else 0,
        })

    return StopLossStats(
        total_sells=total,
        total_pnl=round(total_pnl, 0),
        win_rate=round(win_rate, 1),
        by_type=by_type,
    )


def _classify_sell_reason(reason: str) -> str:
    """将卖出reason分类为标准类型"""
    if not reason:
        return "其他"
    if "跳空" in reason:
        return "跳空止损"
    if "追踪" in reason:
        return "追踪止损"
    if "分批" in reason:
        return "分批止盈"
    if "止盈" in reason:
        return "止盈"
    if "冲高" in reason or "利润保护" in reason or "利润锁定" in reason:
        return "冲高回落"
    if "强制" in reason or "空仓" in reason:
        return "强制空仓"
    if "超时" in reason or "强卖" in reason:
        return "超时强卖"
    if "止损" in reason:
        return "固定止损"
    return "其他"
