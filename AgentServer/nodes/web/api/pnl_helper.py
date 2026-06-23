"""
【v2.9.99-r6】broker_orders 盈亏 fallback 工具

背景:
broker._sync_save_order_and_position 在 _execute_sell 之后调用,
但 _execute_sell 会删除已清仓的持仓 → 写入 MongoDB 时 pos 已被清理 →
broker_orders.profit_pct / profit_amount 经常被写成 0。

之前 v2.9.98f 只在 /scanner/analysis 修了, v2.9.99-r3 在 /scanner/all 修了,
v2.9.99-r5 在 /unified/trades 修了。本文件统一抽出, 供所有端点使用:

- /scanner/orders               (scanner_trading.py)
- /scanner/export-trade-log     (scanner_trading.py)
- /scanner/trade-attribution    (scanner_review.py)
- /scanner/sentiment-timeline   (scanner_sentiment.py)
- /scanner/review-hero / discipline-check / review-forward (scanner_review.py)

使用方式:
    from .pnl_helper import build_buy_price_index, fallback_pnl

    buy_index = await build_buy_price_index(db, account_id="default")
    for sell_doc in sell_docs:
        pct, amt = fallback_pnl(sell_doc, buy_index)
"""
from __future__ import annotations

from typing import Optional


async def build_buy_price_index(
    db,
    account_id: str = "default",
    date_lte: Optional[int] = None,
) -> dict[str, dict]:
    """构建 ts_code -> 最近一笔 buy 订单的索引

    Args:
        db: motor async db 对象
        account_id: 账户 ID
        date_lte: 只取 trade_date <= date_lte 的买单 (None 表示所有历史)

    Returns:
        {ts_code: buy_order_doc} 每只股票最近一笔 buy
    """
    query: dict = {
        "account_id": account_id,
        "status": "filled",
        "side": {"$in": ["buy", "BUY"]},
    }
    if date_lte is not None:
        query["trade_date"] = {"$in": [date_lte, str(date_lte), {"$lte": date_lte}]}
        # 上面 $in 含 dict 不合法, 改用 $lte 直接(兼容 int + str)
        query["trade_date"] = {"$lte": date_lte}

    buy_index: dict[str, dict] = {}
    cursor = db["broker_orders"].find(query).sort([
        ("trade_date", -1),
        ("create_time", -1),
        ("fill_time", -1),
    ])
    async for bd in cursor:
        tc = bd.get("ts_code", "")
        if tc and tc not in buy_index:
            buy_index[tc] = bd  # 只留最近一笔
    return buy_index


def build_buy_price_index_sync(
    db,
    account_id: str = "default",
    date_lte: Optional[int] = None,
) -> dict[str, dict]:
    """同步版本 (pymongo, 给 sync 端点用)"""
    query: dict = {
        "account_id": account_id,
        "status": "filled",
        "side": {"$in": ["buy", "BUY"]},
    }
    if date_lte is not None:
        query["trade_date"] = {"$lte": date_lte}

    buy_index: dict[str, dict] = {}
    cursor = db["broker_orders"].find(query).sort([
        ("trade_date", -1),
        ("create_time", -1),
        ("fill_time", -1),
    ])
    for bd in cursor:
        tc = bd.get("ts_code", "")
        if tc and tc not in buy_index:
            buy_index[tc] = bd
    return buy_index


def fallback_pnl(
    sell_doc: dict,
    buy_index: dict[str, dict],
) -> tuple[float, float]:
    """计算 sell 订单的盈亏 (优先用 broker 存储, 为 0 时 fallback 自算)

    Returns:
        (profit_pct, profit_amount): 单位 % 和 元 (含 round)
    """
    pct_raw = sell_doc.get("profit_pct")
    amt_raw = sell_doc.get("profit_amount")

    # broker 已正确填充, 直接返回
    try:
        pct = float(pct_raw) if pct_raw not in (None, "") else 0.0
    except (TypeError, ValueError):
        pct = 0.0
    try:
        amt = float(amt_raw) if amt_raw not in (None, "") else 0.0
    except (TypeError, ValueError):
        amt = 0.0
    if pct != 0 or amt != 0:
        return round(pct, 2), round(amt, 2)

    # 需要 fallback: 从 buy_index 找买入价
    ts_code = sell_doc.get("ts_code", "")
    sell_price = float(sell_doc.get("filled_price") or sell_doc.get("price") or 0)
    qty = sell_doc.get("filled_qty") or sell_doc.get("quantity") or 0
    try:
        qty = int(qty)
    except (TypeError, ValueError):
        qty = 0

    # 优先用 sell 单自带的 avg_cost (v2.9.98f 之后 broker 会写入)
    avg_cost = sell_doc.get("avg_cost")
    try:
        avg_cost = float(avg_cost) if avg_cost not in (None, "") else 0.0
    except (TypeError, ValueError):
        avg_cost = 0.0

    if avg_cost <= 0:
        # 从 buy_index 取最近一笔 buy
        buy_doc = buy_index.get(ts_code)
        if buy_doc:
            try:
                avg_cost = float(buy_doc.get("filled_price") or buy_doc.get("price") or 0)
            except (TypeError, ValueError):
                avg_cost = 0.0

    if avg_cost > 0 and sell_price > 0:
        pct = (sell_price - avg_cost) / avg_cost * 100
        amt = (sell_price - avg_cost) * qty
        return round(pct, 2), round(amt, 2)

    return 0.0, 0.0
