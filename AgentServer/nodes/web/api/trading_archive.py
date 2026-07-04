"""
交易归档 API — 参考掘金量化交易归档功能
按日期+账户查看: 摘要/资金/持仓/成交/委托/日志
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from core.constants import C
from core.managers import mongo_manager

router = APIRouter(prefix="/trading-archive", tags=["TradingArchive"])
logger = logging.getLogger("api.trading_archive")

# ==================== 响应模型 ====================

class ArchiveDaySummary(BaseModel):
    """某日交易摘要"""
    trade_date: int
    account_id: str
    # 委托统计
    total_orders: int = 0
    buy_orders: int = 0
    sell_orders: int = 0
    filled_orders: int = 0
    cancelled_orders: int = 0
    # 成交统计
    total_trades: int = 0
    total_buy_amount: float = 0
    total_sell_amount: float = 0
    # 盈亏
    realized_pnl: float = 0
    # 持仓
    position_count: int = 0
    position_value: float = 0
    # 资金
    available_cash: float = 0
    total_assets: float = 0
    # 异常
    anomaly_count: int = 0  # 持仓差异=(今日持仓-昨日持仓)-(今日买入-今日卖出) != 0

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
    side: str  # buy/sell
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
    """归档索引 — 可用日期列表"""
    dates: List[int] = []
    latest_date: int = 0

class ArchiveAnomaly(BaseModel):
    """异常合约"""
    ts_code: str
    stock_name: str = ""
    diff: int = 0
    today_position: int = 0
    yesterday_position: int = 0
    buy_qty: int = 0
    sell_qty: int = 0

# ==================== API ====================

@router.get("/dates", response_model=TradingArchiveIndex)
async def get_archive_dates(account_id: str = Query(default="default")):
    """获取有交易归档的日期列表"""
    db = await mongo_manager.get_db()
    
    # 从broker_orders获取有交易的日期
    pipeline = [
        {"$match": {"account_id": account_id, "status": "filled"}},
        {"$group": {"_id": "$trade_date"}},
        {"$sort": {"_id": -1}},
    ]
    cursor = db[C.ORDERS].aggregate(pipeline)
    trade_dates = []
    async for doc in cursor:
        if doc["_id"]:
            trade_dates.append(int(doc["_id"]))
    
    # 也从equity_curve获取
    ec_cursor = db["equity_curve"].find({}, {"date": 1, "_id": 0}).sort("date", -1)
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
    db = await mongo_manager.get_db()
    
    # 1. 委托/成交
    orders_cursor = db[C.ORDERS].find(
        {"account_id": account_id, "trade_date": trade_date}
    ).sort("create_time", 1)
    all_orders = await orders_cursor.to_list(length=1000)
    
    buy_orders = [o for o in all_orders if o.get("side") == "buy"]
    sell_orders = [o for o in all_orders if o.get("side") == "sell"]
    filled_orders = [o for o in all_orders if o.get("status") == "filled"]
    
    total_buy_amount = sum(o.get("filled_amount", 0) or 0 for o in filled_orders if o.get("side") == "buy")
    total_sell_amount = sum(o.get("filled_amount", 0) or 0 for o in filled_orders if o.get("side") == "sell")
    realized_pnl = sum(o.get("profit_amount", 0) or 0 for o in filled_orders if o.get("side") == "sell")
    
    # 2. 资金
    capital = ArchiveCapital(trade_date=trade_date)
    ec = await db["equity_curve"].find_one({"date": trade_date})
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
        # 从broker_accounts取
        acc = await db[C.ACCOUNTS].find_one({"account_id": account_id})
        if acc:
            capital = ArchiveCapital(
                trade_date=trade_date,
                available_cash=acc.get("available_cash", 0) or 0,
                total_assets=acc.get("total_assets", 0) or 0,
                market_value=acc.get("market_value", 0) or 0,
                total_profit=acc.get("total_profit", 0) or 0,
            )
    
    # 3. 持仓
    positions_cursor = db[C.POSITIONS].find(
        {"account_id": account_id, "total_qty": {"$gt": 0}}
    )
    positions = []
    async for p in positions_cursor:
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
    
    # 4. 成交记录(从filled orders)
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
    
    # 5. 委托记录(所有orders)
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
    
    # 6. 日志(从scanner_timeline)
    timeline_cursor = db["scanner_timeline"].find(
        {"trade_date": trade_date, "action": {"$in": ["buy", "sell", "signal", "risk", "circuit"]}}
    ).sort("ts_code", 1).limit(100)
    logs = []
    async for t in timeline_cursor:
        logs.append(ArchiveLog(
            timestamp=str(t.get("created_at", "")),
            type=t.get("action", ""),
            message=f"{t.get('ts_code', '')} {t.get('stock_name', '')} — {t.get('reason', '')}",
        ))
    
    # 7. 异常合约检测
    # 差值 = (今日持仓-昨日持仓) - (今日买入量-今日卖出量)
    # 如果差值 != 0, 说明有异常
    anomaly_count = 0
    anomalies = []
    # (简化: 只在positions>0且orders>0时检查)
    
    # 8. 摘要
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
        anomaly_count=anomaly_count,
    )
    
    return TradingArchiveDay(
        summary=summary,
        capital=capital,
        positions=positions,
        trades=trades,
        orders=orders,
        logs=logs,
    )


@router.get("/anomaly/{trade_date}", response_model=List[ArchiveAnomaly])
async def get_archive_anomaly(
    trade_date: int,
    account_id: str = Query(default="default"),
):
    """异常合约检测 — 差值=(今日持仓-昨日持仓)-(今日买入-今日卖出)"""
    db = await mongo_manager.get_db()
    
    # 获取前一个交易日的持仓(从backup或broker_positions快照)
    # 简化: 从broker_orders推算
    today_orders = await db[C.ORDERS].find(
        {"account_id": account_id, "trade_date": trade_date, "status": "filled"}
    ).to_list(length=500)
    
    # 计算每只票的今日净买入
    from collections import defaultdict
    net_buy = defaultdict(int)
    for o in today_orders:
        code = o.get("ts_code", "")
        qty = o.get("filled_qty", 0) or 0
        if o.get("side") == "buy":
            net_buy[code] += qty
        elif o.get("side") == "sell":
            net_buy[code] -= qty
    
    # 当前持仓
    current_positions = await db[C.POSITIONS].find(
        {"account_id": account_id, "total_qty": {"$gt": 0}}
    ).to_list(length=100)
    current_qty = {p.get("ts_code"): p.get("total_qty") or p.get("qty") or 0 for p in current_positions}
    
    # 所有涉及的票
    all_codes = set(net_buy.keys()) | set(current_qty.keys())
    
    anomalies = []
    for code in all_codes:
        today_pos = current_qty.get(code, 0)
        # 昨日持仓 = 今日持仓 - 今日净买入
        yesterday_pos = today_pos - net_buy.get(code, 0)
        diff = (today_pos - yesterday_pos) - net_buy.get(code, 0)
        if diff != 0:
            anomalies.append(ArchiveAnomaly(
                ts_code=code,
                stock_name="",
                diff=diff,
                today_position=today_pos,
                yesterday_position=yesterday_pos,
                buy_qty=net_buy.get(code, 0) if net_buy.get(code, 0) > 0 else 0,
                sell_qty=abs(net_buy.get(code, 0)) if net_buy.get(code, 0) < 0 else 0,
            ))
    
    return anomalies
