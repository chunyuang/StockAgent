"""
交易归档 API — 参考掘金量化交易归档功能
按日期+账户查看: 摘要/资金/持仓/成交/委托/日志
"""
import logging
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from core.constants import C
from core.managers import mongo_manager

# 集合名常量(不在C中定义的)
COL_ORDERS = "broker_orders"
COL_ACCOUNTS = "broker_accounts"

router = APIRouter(prefix="/trading-archive", tags=["TradingArchive"])
logger = logging.getLogger("api.trading_archive")

# ==================== 响应模型 ====================

class ArchiveDaySummary(BaseModel):
    """某日交易摘要"""
    trade_date: int
    account_id: str
    total_orders: int = 0
    buy_orders: int = 0
    sell_orders: int = 0
    filled_orders: int = 0
    cancelled_orders: int = 0
    total_trades: int = 0
    total_buy_amount: float = 0
    total_sell_amount: float = 0
    realized_pnl: float = 0
    position_count: int = 0
    position_value: float = 0
    available_cash: float = 0
    total_assets: float = 0
    anomaly_count: int = 0

class ArchiveCapital(BaseModel):
    """资金快照"""
    trade_date: int
    available_cash: float = 0
    total_assets: float = 0
    market_value: float = 0
    total_profit: float = 0
    realized_pnl: float = 0

class ArchivePosition(BaseModel):
    """归档持仓"""
    ts_code: str
    stock_name: str = ""
    quantity: int = 0
    available_qty: int = 0
    avg_cost: float = 0
    current_price: float = 0
    market_value: float = 0
    profit_pct: float = 0
    strategy: str = ""

class ArchiveTrade(BaseModel):
    """归档成交"""
    order_id: str = ""
    ts_code: str
    stock_name: str = ""
    side: str = ""
    filled_qty: int = 0
    filled_price: float = 0
    filled_amount: float = 0
    profit_amount: float = 0
    profit_pct: float = 0
    strategy: str = ""
    fill_time: str = ""
    trade_date: int = 0

class ArchiveOrder(BaseModel):
    """归档委托"""
    order_id: str = ""
    ts_code: str = ""
    stock_name: str = ""
    side: str = ""
    price: float = 0
    quantity: int = 0
    filled_qty: int = 0
    filled_price: float = 0
    status: str = ""
    reason: str = ""
    strategy: str = ""
    create_time: str = ""
    fill_time: str = ""
    trade_date: int = 0

class ArchiveLog(BaseModel):
    """归档日志条目"""
    timestamp: str
    type: str = ""
    message: str = ""

class TradingArchiveDay(BaseModel):
    """某日完整交易归档"""
    summary: ArchiveDaySummary
    capital: ArchiveCapital
    positions: List[ArchivePosition] = []
    trades: List[ArchiveTrade] = []
    orders: List[ArchiveOrder] = []
    logs: List[ArchiveLog] = []

class TradingArchiveIndex(BaseModel):
    """归档索引"""
    dates: List[int] = []
    latest_date: int = 0

# ==================== API ====================

@router.get("/dates", response_model=TradingArchiveIndex)
async def get_archive_dates(account_id: str = Query(default="default")):
    """获取有交易归档的日期列表"""
    # 从broker_orders聚合
    pipeline = [
        {"$match": {"account_id": account_id, "status": "filled"}},
        {"$group": {"_id": "$trade_date"}},
        {"$sort": {"_id": -1}},
    ]
    cursor = mongo_manager.db[COL_ORDERS].aggregate(pipeline)
    trade_dates = []
    async for doc in cursor:
        if doc["_id"]:
            trade_dates.append(int(doc["_id"]))

    # 也从equity_curve获取
    ec_cursor = mongo_manager.db["equity_curve"].find({}, {"date": 1, "_id": 0}).sort("date", -1)
    ec_dates = set()
    async for doc in ec_cursor:
        d = doc.get("date")
        if d:
            ec_dates.add(int(str(d)[:8]) if len(str(d)) > 8 else int(d))

    all_dates = sorted(set(trade_dates) | ec_dates, reverse=True)

    return TradingArchiveIndex(
        dates=all_dates,
        latest_date=all_dates[0] if all_dates else 0,
    )


@router.get("/day/{trade_date}", response_model=TradingArchiveDay)
async def get_archive_day(
    trade_date: int,
    account_id: str = Query(default="default"),
):
    """获取某日的完整交易归档"""
    db = mongo_manager.db

    # 1. 委托/成交
    all_orders = await mongo_manager.find_many(
        COL_ORDERS,
        {"account_id": account_id, "trade_date": trade_date},
        sort=[("create_time", 1)],
    )

    buy_orders = [o for o in all_orders if o.get("side") == "buy"]
    sell_orders = [o for o in all_orders if o.get("side") == "sell"]
    filled_orders = [o for o in all_orders if o.get("status") == "filled"]

    total_buy_amount = sum(o.get("filled_amount", 0) or 0 for o in filled_orders if o.get("side") == "buy")
    total_sell_amount = sum(o.get("filled_amount", 0) or 0 for o in filled_orders if o.get("side") == "sell")
    realized_pnl = sum(o.get("profit_amount", 0) or 0 for o in filled_orders if o.get("side") == "sell")

    # 2. 资金
    capital = ArchiveCapital(trade_date=trade_date)
    ec = await mongo_manager.find_one("equity_curve", {"date": trade_date})
    if ec:
        capital = ArchiveCapital(
            trade_date=trade_date,
            available_cash=ec.get("cash", 0) or 0,
            total_assets=ec.get("equity", 0) or 0,
            market_value=ec.get("market_value", 0) or 0,
            total_profit=(ec.get("equity", 0) or 0) - 1000000,
            realized_pnl=ec.get("realized_pnl", 0) or 0,
        )
    else:
        acc = await mongo_manager.find_one(COL_ACCOUNTS, {"account_id": account_id})
        if acc:
            capital = ArchiveCapital(
                trade_date=trade_date,
                available_cash=acc.get("available_cash", 0) or 0,
                total_assets=acc.get("total_assets", 0) or 0,
                market_value=acc.get("market_value", 0) or 0,
                total_profit=acc.get("total_profit", 0) or 0,
            )

    # 3. 持仓
    raw_positions = await mongo_manager.find_many(
        C.POSITIONS,
        {"account_id": account_id, "total_qty": {"$gt": 0}},
    )
    positions = []
    for p in raw_positions:
        qty = p.get("total_qty") or p.get("qty") or 0
        positions.append(ArchivePosition(
            ts_code=p.get("ts_code", ""),
            stock_name=p.get("stock_name", ""),
            quantity=qty,
            available_qty=p.get("available_qty", 0) or 0,
            avg_cost=p.get("avg_cost", 0) or 0,
            current_price=p.get("current_price", 0) or 0,
            market_value=p.get("market_value", 0) or qty * (p.get("current_price", 0) or 0),
            profit_pct=p.get("profit_pct", 0) or 0,
            strategy=p.get("strategy", ""),
        ))

    # 4. 成交记录
    trades = []
    for o in filled_orders:
        trades.append(ArchiveTrade(
            order_id=o.get("order_id", ""),
            ts_code=o.get("ts_code", ""),
            stock_name=o.get("stock_name", ""),
            side=o.get("side", ""),
            filled_qty=o.get("filled_qty", 0) or 0,
            filled_price=o.get("filled_price", 0) or 0,
            filled_amount=o.get("filled_amount", 0) or 0,
            profit_amount=o.get("profit_amount", 0) or 0,
            profit_pct=o.get("profit_pct", 0) or 0,
            strategy=o.get("strategy", ""),
            fill_time=o.get("fill_time", "") or str(o.get("created_at", "")),
            trade_date=int(o.get("trade_date", 0) or 0),
        ))

    # 5. 委托记录
    orders = []
    for o in all_orders:
        orders.append(ArchiveOrder(
            order_id=o.get("order_id", ""),
            ts_code=o.get("ts_code", ""),
            stock_name=o.get("stock_name", ""),
            side=o.get("side", ""),
            price=o.get("price", 0) or 0,
            quantity=o.get("quantity", 0) or o.get("filled_qty", 0) or 0,
            filled_qty=o.get("filled_qty", 0) or 0,
            filled_price=o.get("filled_price", 0) or 0,
            status=o.get("status", ""),
            reason=o.get("reason", ""),
            strategy=o.get("strategy", ""),
            create_time=str(o.get("create_time", "") or o.get("created_at", "")),
            fill_time=str(o.get("fill_time", "") or ""),
            trade_date=int(o.get("trade_date", 0) or 0),
        ))

    # 6. 日志
    raw_logs = await mongo_manager.find_many(
        "scanner_timeline",
        {"trade_date": trade_date, "action": {"$in": ["buy", "sell", "signal", "risk", "circuit"]}},
        sort=[("ts_code", 1)],
        limit=100,
    )
    logs = []
    for t in raw_logs:
        logs.append(ArchiveLog(
            timestamp=str(t.get("created_at", "")),
            type=t.get("action", ""),
            message=f"{t.get('ts_code', '')} {t.get('stock_name', '')} — {t.get('reason', '')}",
        ))

    # 7. 摘要
    summary = ArchiveDaySummary(
        trade_date=trade_date,
        account_id=account_id,
        total_orders=len(all_orders),
        buy_orders=len(buy_orders),
        sell_orders=len(sell_orders),
        filled_orders=len(filled_orders),
        cancelled_orders=len([o for o in all_orders if o.get("status") == "cancelled"]),
        total_trades=len(trades),
        total_buy_amount=total_buy_amount,
        total_sell_amount=total_sell_amount,
        realized_pnl=realized_pnl,
        position_count=len(positions),
        position_value=sum(p.market_value for p in positions),
        available_cash=capital.available_cash,
        total_assets=capital.total_assets,
        anomaly_count=0,
    )

    return TradingArchiveDay(
        summary=summary,
        capital=capital,
        positions=positions,
        trades=trades,
        orders=orders,
        logs=logs,
    )
