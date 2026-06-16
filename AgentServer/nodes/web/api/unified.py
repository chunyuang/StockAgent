"""
Unified Data API — v2.9.97
统一数据层：所有交易/持仓 UI 共用的单一真相源。

设计原则：
1. broker_orders = 交易唯一真相源（status='filled' 才算）
2. broker_positions = 当前持仓真相源（status_at='now'）
3. 历史持仓 = 从 broker_orders 重建到当日收盘（status_at='date'）
4. 任何 UI 只调本模块的 3 个 API，不再各自查 MongoDB

防止数据漂移：
- 同一份"今日交易"数据，所有 UI 显示一致
- 同一份"持仓"，所有 UI 显示一致
- 日期选择器染色由本模块提供数据
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Query

logger = logging.getLogger("api.unified")
router = APIRouter(prefix="/unified", tags=["unified"])


# ============================================================
# 内部工具
# ============================================================

def _normalize_date(date: Optional[str]) -> Optional[int]:
    """日期参数标准化:
    - None / 'today' / '' → 当天 (返回当天 int 形式)
    - '20260616' / '2026-06-16' → 20260616
    """
    if not date or date == "today":
        return int(datetime.now().strftime("%Y%m%d"))
    s = str(date).replace("-", "").strip()
    if not s:
        return int(datetime.now().strftime("%Y%m%d"))
    try:
        return int(s)
    except Exception:
        return None


async def _get_db():
    from core.managers import mongo_manager
    if not mongo_manager.is_initialized:
        return None
    return mongo_manager.db


# ============================================================
# 核心函数: 统一交易查询 (broker_orders 为唯一真相)
# ============================================================

async def fetch_unified_trades(date: Optional[str] = None, account_id: str = "default") -> list[dict]:
    """获取指定日期的所有交易（buy + sell）

    单一来源: broker_orders (status='filled')
    返回标准格式, 所有 UI 共用此结构

    用于:
      - 分析每日明细
      - 复盘逐笔归因
      - 运维自动交易操作流
      - 实盘当日成交
    """
    db = await _get_db()
    if db is None:
        return []

    date_int = _normalize_date(date)
    if date_int is None:
        return []

    trades: list[dict] = []
    # broker_orders.trade_date 历史上有 int 和 str 两种格式, 用 $in 兼容
    cursor = db["broker_orders"].find({
        "account_id": account_id,
        "trade_date": {"$in": [date_int, str(date_int)]},
        "status": "filled",
    }).sort([("create_time", 1), ("fill_time", 1)])

    async for doc in cursor:
        side = doc.get("side", "")
        qty = doc.get("filled_qty") or doc.get("quantity") or 0
        price = float(doc.get("filled_price") or doc.get("price") or 0)
        ts_code = doc.get("ts_code", "")
        # fill_time 形如 "11:18:22" 或 ISO 字符串, 取后 8 位通用化
        ftime = str(doc.get("fill_time") or doc.get("create_time", ""))
        time_str = ftime[-8:] if len(ftime) >= 8 else ftime

        # 归因（仅 sell 有意义）
        profit_pct = doc.get("profit_pct")
        profit_amount = doc.get("profit_amount")
        why = None
        if side == "sell" and profit_pct is not None:
            reason = doc.get("reason", "")
            if profit_pct >= 0:
                if "追踪" in reason:
                    why = "趋势延续盈利锁定"
                elif "止盈" in reason:
                    why = "达到止盈目标"
                elif "冲高" in reason:
                    why = "冲高兑现"
                else:
                    why = "盈利卖出"
            else:
                if "止损" in reason and "追踪" not in reason:
                    why = "触发止损"
                elif "跳空" in reason:
                    why = "跳空低开止损"
                elif "追踪" in reason:
                    why = "追踪止损回撤"
                else:
                    why = "止损卖出"

        # 计算金额
        amount = qty * price

        trades.append({
            "trade_date": str(date_int),
            "time": time_str,
            "fill_time": ftime,
            "side": side,
            "ts_code": ts_code,
            "stock_name": doc.get("stock_name", ""),
            "quantity": qty,
            "price": round(price, 4),
            "amount": round(amount, 2),
            "strategy": doc.get("strategy", ""),
            "reason": doc.get("reason", ""),
            "source": doc.get("source", "auto"),
            "order_id": doc.get("order_id", ""),
            "profit_pct": profit_pct,
            "profit_amount": profit_amount,
            "why": why,
        })

    return trades


# ============================================================
# 核心函数: 统一持仓查询
# ============================================================

async def fetch_unified_positions(date: Optional[str] = None, account_id: str = "default") -> dict:
    """获取持仓快照

    date=None / 'today': 实时持仓 (broker_positions + 实时current_price)
    date=20260615: 历史持仓快照 (从 broker_orders 重建到当日收盘)

    返回:
      {
        "as_of": "20260616",
        "is_realtime": True/False,
        "positions": [...],
        "summary": { total_qty, total_market_value, total_cost, total_profit_pct, ... }
      }
    """
    db = await _get_db()
    if db is None:
        return {"as_of": None, "is_realtime": False, "positions": [], "summary": {}}

    today_int = int(datetime.now().strftime("%Y%m%d"))
    date_int = _normalize_date(date) if date else today_int
    is_realtime = (date is None or date == "today" or date_int == today_int)

    positions: list[dict] = []

    if is_realtime:
        # 走 broker_positions
        async for p in db["broker_positions"].find({"account_id": account_id}):
            qty = p.get("total_qty") or p.get("quantity") or 0
            if qty <= 0:
                continue
            tc = p.get("ts_code", "")
            avg_cost = float(p.get("avg_cost") or p.get("cost_price") or 0)
            cur_price = float(p.get("current_price") or 0)
            if cur_price <= 0:
                # fallback 历史 close
                latest = await db["stock_daily_ak_full"].find_one(
                    {"ts_code": tc}, {"close": 1}, sort=[("trade_date", -1)]
                )
                cur_price = float(latest.get("close", avg_cost)) if latest else avg_cost

            profit_pct = ((cur_price - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0
            positions.append(_build_position_dict(p, qty, avg_cost, cur_price, profit_pct))
    else:
        # 历史快照: 从 broker_orders 重建到 date 当日收盘
        # 用移动加权平均(MWAC)
        from collections import defaultdict
        holdings: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"qty": 0, "total_cost": 0.0, "name": "", "strategy": "", "buy_date": ""}
        )

        cursor = db["broker_orders"].find({
            "account_id": account_id,
            "trade_date": {"$lte": date_int},  # 包括 date 当日
            "status": "filled",
        }).sort([("trade_date", 1), ("create_time", 1)])

        async for doc in cursor:
            tc = doc.get("ts_code", "")
            side = doc.get("side", "")
            qty = doc.get("filled_qty") or doc.get("quantity") or 0
            price = float(doc.get("filled_price") or doc.get("price") or 0)
            if not tc or not qty:
                continue
            h = holdings[tc]
            if side == "buy":
                h["qty"] += qty
                h["total_cost"] += qty * price
                h["name"] = doc.get("stock_name") or h["name"]
                h["strategy"] = doc.get("strategy") or h["strategy"]
                h["buy_date"] = str(doc.get("trade_date", ""))
            elif side == "sell" and h["qty"] > 0:
                avg = h["total_cost"] / h["qty"]
                h["qty"] -= qty
                h["total_cost"] -= avg * qty
                if h["qty"] == 0:
                    h["total_cost"] = 0.0

        # 拿 date 当日收盘价
        for tc, h in holdings.items():
            if h["qty"] <= 0:
                continue
            avg_cost = h["total_cost"] / h["qty"]
            close_doc = await db["stock_daily_ak_full"].find_one(
                {"ts_code": tc, "trade_date": {"$lte": date_int}},
                {"close": 1, "trade_date": 1},
                sort=[("trade_date", -1)],
            )
            cur_price = float(close_doc.get("close", avg_cost)) if close_doc else avg_cost
            profit_pct = ((cur_price - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0
            p_doc = {
                "ts_code": tc,
                "stock_name": h["name"],
                "strategy": h["strategy"],
                "total_qty": h["qty"],
                "available_qty": h["qty"] if h["buy_date"] != str(date_int) else 0,
                "today_buy_qty": h["qty"] if h["buy_date"] == str(date_int) else 0,
                "buy_date": h["buy_date"],
                "avg_cost": avg_cost,
                "current_price": cur_price,
            }
            positions.append(_build_position_dict(p_doc, h["qty"], avg_cost, cur_price, profit_pct))

    # 汇总
    total_market_value = sum(p["market_value"] for p in positions)
    total_cost = sum(p["cost_price"] * p["shares"] for p in positions)
    total_profit = total_market_value - total_cost
    total_profit_pct = (total_profit / total_cost * 100) if total_cost > 0 else 0

    return {
        "as_of": str(date_int),
        "is_realtime": is_realtime,
        "positions": positions,
        "summary": {
            "count": len(positions),
            "total_market_value": round(total_market_value, 2),
            "total_cost": round(total_cost, 2),
            "total_profit": round(total_profit, 2),
            "total_profit_pct": round(total_profit_pct, 2),
            "loss_count": sum(1 for p in positions if p["profit_pct"] < 0),
            "gain_count": sum(1 for p in positions if p["profit_pct"] > 0),
            "broken_stop_count": sum(1 for p in positions if p["stop_loss_status"] == "broken"),
        },
    }


def _build_position_dict(p: dict, qty: int, avg_cost: float, cur_price: float, profit_pct: float) -> dict:
    """构建标准持仓字典(包含止损状态/风控)"""
    try:
        from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK, STRATEGY_CONFIGS
    except Exception:
        GLOBAL_RISK, STRATEGY_CONFIGS = {}, {}

    strategy = p.get("strategy", "")
    strat_en = strategy
    for k_, v_ in STRATEGY_CONFIGS.items():
        if v_.get("display_name") == strategy or k_ == strategy:
            strat_en = k_
            break
    strat_cfg = STRATEGY_CONFIGS.get(strat_en, {})
    sl_pct = strat_cfg.get("stop_loss_pct", GLOBAL_RISK.get("stop_loss_pct", 0.03))
    tp_pct = strat_cfg.get("take_profit_pct", GLOBAL_RISK.get("take_profit_pct", 0.07))
    stop_loss_price = round(avg_cost * (1 - sl_pct), 2)
    take_profit_price = round(avg_cost * (1 + tp_pct), 2)

    stop_loss_status = "safe"
    stop_loss_desc = ""
    if cur_price <= stop_loss_price:
        stop_loss_status = "broken"
        stop_loss_desc = f"已破止损 -{sl_pct*100:.0f}%, 当前 {profit_pct:.1f}%"
    elif cur_price <= stop_loss_price * 1.05:
        stop_loss_status = "near"
        stop_loss_desc = f"接近止损价 {stop_loss_price:.2f}"

    return {
        "ts_code": p.get("ts_code", ""),
        "stock_name": p.get("stock_name", ""),
        "strategy": strategy,
        "strategy_en": strat_en,
        "shares": qty,
        "available_qty": p.get("available_qty", 0),
        "today_buy_qty": p.get("today_buy_qty", 0),
        "cost_price": round(avg_cost, 2),
        "current_price": round(cur_price, 2),
        "profit_pct": round(profit_pct, 2),
        "profit_amount": round((cur_price - avg_cost) * qty, 2),
        "market_value": round(cur_price * qty, 2),
        "stop_loss_price": stop_loss_price,
        "stop_loss_pct": round(sl_pct * 100, 1),
        "take_profit_price": take_profit_price,
        "take_profit_pct": round(tp_pct * 100, 1),
        "stop_loss_status": stop_loss_status,
        "stop_loss_desc": stop_loss_desc,
        "buy_date": p.get("buy_date", ""),
    }


# ============================================================
# 核心函数: 日期可用性 (染色用)
# ============================================================

async def fetch_date_availability(days: int = 60, account_id: str = "default") -> dict:
    """返回近 N 天每日是否有交易/持仓数据

    用于前端日期选择器染色:
      "20260616": "trades"      # 当日有交易
      "20260615": "positions"   # 当日只有持仓没交易
      "20260614": "weekend"     # 周末
      "20260613": "no-data"     # 无数据
    """
    db = await _get_db()
    if db is None:
        return {}

    today = datetime.now()
    start = today - timedelta(days=days)
    start_int = int(start.strftime("%Y%m%d"))

    # 一次性聚合 broker_orders 看每日有几笔成交
    pipeline = [
        {"$match": {
            "account_id": account_id,
            "status": "filled",
            "trade_date": {"$gte": start_int},
        }},
        {"$group": {
            "_id": "$trade_date",
            "count": {"$sum": 1},
            "buys": {"$sum": {"$cond": [{"$eq": ["$side", "buy"]}, 1, 0]}},
            "sells": {"$sum": {"$cond": [{"$eq": ["$side", "sell"]}, 1, 0]}},
        }}
    ]

    daily_counts: dict[str, dict] = {}
    async for row in db["broker_orders"].aggregate(pipeline):
        td = str(row["_id"])
        daily_counts[td] = {
            "count": row["count"],
            "buys": row["buys"],
            "sells": row["sells"],
        }

    # 构建每日状态
    result: dict[str, dict] = {}
    for i in range(days + 1):
        d = today - timedelta(days=i)
        d_int = int(d.strftime("%Y%m%d"))
        d_str = d.strftime("%Y%m%d")
        weekday = d.weekday()  # 0=周一, 6=周日

        if weekday >= 5:
            status = "weekend"
        elif d_str in daily_counts:
            status = "trades"
        else:
            # 当日无交易, 但可能有持仓(交易日没动作)
            status = "no-trades"

        result[d_str] = {
            "status": status,
            "weekday": weekday,
            "is_today": (d_int == int(today.strftime("%Y%m%d"))),
            **daily_counts.get(d_str, {"count": 0, "buys": 0, "sells": 0}),
        }

    return result


# ============================================================
# FastAPI 路由
# ============================================================

@router.get("/trades")
async def api_unified_trades(
    date: Optional[str] = Query(None, description="日期 YYYYMMDD, 不传=今天"),
    account_id: str = Query("default"),
):
    """获取指定日期的所有交易(buy + sell), 单一来源 broker_orders"""
    try:
        trades = await fetch_unified_trades(date, account_id)
        buys = [t for t in trades if t["side"] == "buy"]
        sells = [t for t in trades if t["side"] == "sell"]
        return {
            "success": True,
            "data": {
                "date": _normalize_date(date),
                "trades": trades,
                "summary": {
                    "total": len(trades),
                    "buy_count": len(buys),
                    "sell_count": len(sells),
                    "buy_amount": round(sum(t["amount"] for t in buys), 2),
                    "sell_amount": round(sum(t["amount"] for t in sells), 2),
                    "realized_profit": round(sum(t.get("profit_amount") or 0 for t in sells), 2),
                },
            },
        }
    except Exception as e:
        logger.exception("api_unified_trades error")
        return {"success": False, "data": {"trades": [], "summary": {}}, "error": str(e)}


@router.get("/positions")
async def api_unified_positions(
    date: Optional[str] = Query(None, description="日期 YYYYMMDD, 不传=今天实时"),
    account_id: str = Query("default"),
):
    """获取持仓快照(实时或历史)"""
    try:
        snap = await fetch_unified_positions(date, account_id)
        return {"success": True, "data": snap}
    except Exception as e:
        logger.exception("api_unified_positions error")
        return {"success": False, "data": {"positions": [], "summary": {}}, "error": str(e)}


@router.get("/date-availability")
async def api_date_availability(
    days: int = Query(60, ge=1, le=365),
    account_id: str = Query("default"),
):
    """返回近 N 天每日数据可用性, 用于日期选择器染色"""
    try:
        avail = await fetch_date_availability(days, account_id)
        return {"success": True, "data": avail}
    except Exception as e:
        logger.exception("api_date_availability error")
        return {"success": False, "data": {}, "error": str(e)}
