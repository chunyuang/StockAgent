"""
交易归档 API — 参考掘金量化交易归档功能
按日期+账户查看: 摘要/资金/持仓/成交/委托/日志
"""
import logging
from typing import List
from fastapi import APIRouter, Query
from pydantic import BaseModel

from core.managers import mongo_manager

router = APIRouter(prefix="/trading-archive", tags=["TradingArchive"])
logger = logging.getLogger("api.trading_archive")

# 集合名 — 使用MongoDB中的实际集合名，不依赖C常量(避免名字不一致)
COL_ORDERS = "broker_orders"
COL_POSITIONS = "broker_positions"
COL_ACCOUNTS = "broker_accounts"
COL_EQUITY = "equity_curve"
COL_TIMELINE = "scanner_timeline"

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
    profit_amount: float = 0
    strategy: str = ""
    stop_loss_price: float = 0
    buy_time: str = ""
    hold_days: int = 0

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
    reason: str = ""

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

    ec_cursor = mongo_manager.db[COL_EQUITY].find({}, {"date": 1, "_id": 0}).sort("date", -1)
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

    # 2. 资金 — 优先从performance_snapshots(最完整), fallback到equity_curve, 再fallback到broker_accounts
    capital = ArchiveCapital(trade_date=trade_date)

    # 优先: performance_snapshots(取该日最后一条, 支持无account_id)
    ps = await mongo_manager.find_many(
        "performance_snapshots",
        {"$or": [{"account_id": account_id}, {"account_id": None}, {"account_id": {"$exists": False}}], "trade_date": trade_date},
        sort=[("timestamp", -1)],
        limit=1,
    )
    if ps:
        p = ps[0]
        capital = ArchiveCapital(
            trade_date=trade_date,
            available_cash=p.get("available_cash", 0) or 0,
            total_assets=p.get("total_assets", 0) or 0,
            market_value=p.get("market_value", 0) or 0,
            total_profit=p.get("total_profit", 0) or 0,
            realized_pnl=p.get("realized_profit", 0) or 0,
        )
    else:
        # 次选: equity_curve
        ec = await mongo_manager.find_one(COL_EQUITY, {"trade_date": trade_date})
        if not ec:
            ec = await mongo_manager.find_one(COL_EQUITY, {"date": trade_date})
        if ec:
            capital = ArchiveCapital(
                trade_date=trade_date,
                available_cash=ec.get("available_cash", 0) or ec.get("cash", 0) or 0,
                total_assets=ec.get("total_assets", 0) or ec.get("equity", 0) or 0,
                market_value=ec.get("market_value", 0) or 0,
                total_profit=ec.get("total_profit", 0) or 0,
                realized_pnl=ec.get("realized_pnl", 0) or 0,
            )
        else:
            # 兜底: broker_accounts(当前状态,只适合今天)
            acc = await mongo_manager.find_one(COL_ACCOUNTS, {"account_id": account_id})
            if acc:
                capital = ArchiveCapital(
                    trade_date=trade_date,
                    available_cash=acc.get("available_cash", 0) or 0,
                    total_assets=acc.get("total_assets", 0) or 0,
                    market_value=acc.get("market_value", 0) or 0,
                    total_profit=acc.get("total_profit", 0) or 0,
                )

    # 3. 持仓 — 从orders推算(历史日也能看到当日持仓)
    # 对于当天: 优先用broker_positions(有止损价等实时字段)
    # 对于历史日: 从所有filled orders推算到该日为止的持仓
    from datetime import datetime as _dt
    from collections import defaultdict

    # 获取当日所有filled orders(已有), 再加上之前的
    is_today = (trade_date == int(_dt.now().strftime("%Y%m%d")))

    positions = []
    if is_today:
        # 当天: 直接用broker_positions
        raw_positions = await mongo_manager.find_many(
            COL_POSITIONS,
            {"account_id": account_id, "total_qty": {"$gt": 0}},
        )
        for p in raw_positions:
            qty = p.get("total_qty") or p.get("qty") or 0
            buy_date = p.get("buy_date", "") or ""
            hold_days = 0
            if buy_date:
                try:
                    bd = _dt.strptime(str(buy_date), "%Y%m%d")
                    hold_days = (_dt.now() - bd).days
                except Exception:
                    pass
            positions.append(ArchivePosition(
                ts_code=p.get("ts_code", ""),
                stock_name=p.get("stock_name", ""),
                quantity=qty,
                available_qty=p.get("available_qty", 0) or 0,
                avg_cost=p.get("avg_cost", 0) or 0,
                current_price=p.get("current_price", 0) or 0,
                market_value=p.get("market_value", 0) or qty * (p.get("current_price", 0) or 0),
                profit_pct=p.get("profit_pct", 0) or 0,
                profit_amount=(p.get("current_price", 0) or 0 - p.get("avg_cost", 0) or 0) * qty,
                strategy=p.get("strategy", ""),
                stop_loss_price=p.get("stop_loss_price", 0) or 0,
                buy_time=str(buy_date),
                hold_days=hold_days,
            ))
    else:
        # 历史日: 从filled orders推算持仓
        all_filled = await mongo_manager.find_many(
            COL_ORDERS,
            {"account_id": account_id, "status": "filled", "trade_date": {"$lte": trade_date}},
            sort=[("trade_date", 1), ("create_time", 1)],
        )
        # 累积计算
        running = {}  # ts_code -> {qty, total_cost, stock_name, strategy, first_buy_date}
        for o in all_filled:
            tc = o.get("ts_code", "")
            if tc not in running:
                running[tc] = {"qty": 0, "total_cost": 0, "stock_name": o.get("stock_name", ""), "strategy": o.get("strategy", ""), "first_buy_date": o.get("trade_date", "")}
            pos = running[tc]
            if o.get("side") == "buy":
                pos["qty"] += o.get("filled_qty", 0) or 0
                pos["total_cost"] += o.get("filled_amount", 0) or 0
                pos["strategy"] = o.get("strategy", "")
            elif o.get("side") == "sell":
                sell_qty = o.get("filled_qty", 0) or 0
                if pos["qty"] > 0:
                    avg = pos["total_cost"] / pos["qty"]
                    pos["total_cost"] -= avg * sell_qty
                pos["qty"] -= sell_qty

        # 只保留qty>0的
        for tc, p in running.items():
            if p["qty"] <= 0:
                continue
            avg_cost = p["total_cost"] / p["qty"] if p["qty"] > 0 else 0
            buy_date = p.get("first_buy_date", "")
            hold_days = 0
            if buy_date:
                try:
                    bd = _dt.strptime(str(buy_date), "%Y%m%d")
                    td = _dt.strptime(str(trade_date), "%Y%m%d")
                    hold_days = (td - bd).days
                except Exception:
                    pass
            positions.append(ArchivePosition(
                ts_code=tc,
                stock_name=p.get("stock_name", ""),
                quantity=p["qty"],
                available_qty=0,
                avg_cost=round(avg_cost, 4),
                current_price=0,
                market_value=0,
                profit_pct=0,
                profit_amount=0,
                strategy=p.get("strategy", ""),
                stop_loss_price=0,
                buy_time=str(buy_date),
                hold_days=hold_days,
            ))

    # 4. 成交记录(已成交的orders)
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
            reason=o.get("reason", ""),
        ))

    # 5. 委托记录(所有orders, 排除rolled_back)
    orders = []
    for o in all_orders:
        if o.get("status") == "rolled_back":
            continue
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

    # 6. 日志(scanner_timeline - 显示所有action类型)
    raw_logs = await mongo_manager.find_many(
        COL_TIMELINE,
        {"trade_date": trade_date},
        sort=[("time", 1)],
        limit=500,
    )
    logs = []
    for t in raw_logs:
        action = t.get("action", "")
        # 构造可读消息
        tc = t.get("ts_code", "")
        name = t.get("stock_name", "") or t.get("name", "")
        reason = t.get("reason", "")
        strat = t.get("strategy_name", "") or t.get("strategy", "")
        msg_parts = []
        if tc: msg_parts.append(tc)
        if name: msg_parts.append(name)
        if strat: msg_parts.append(f"[{strat}]")
        if reason:
            # 截断过长的reason
            r = str(reason)
            if len(r) > 120: r = r[:120] + "..."
            msg_parts.append(f"— {r}")
        logs.append(ArchiveLog(
            timestamp=str(t.get("time", "") or t.get("created_at", "")),
            type=action,
            message=" ".join(msg_parts),
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
    )

    return TradingArchiveDay(
        summary=summary,
        capital=capital,
        positions=positions,
        trades=trades,
        orders=orders,
        logs=logs,
    )


# ==================== 扩展API(只读, 不影响实盘) ====================

@router.get("/equity-curve")
async def get_equity_curve(account_id: str = Query(default="default")):
    """净值曲线 — 从equity_curve+performance_snapshots合并"""
    # 优先用performance_snapshots(更频繁,有净值/回撤/仓位)
    # 按日去重: 每日取最后一条, 支持无account_id的记录
    ps_pipeline = [
        {"$match": {"$or": [{"account_id": account_id}, {"account_id": None}, {"account_id": {"$exists": False}}], "total_assets": {"$gt": 0}}},
        {"$sort": {"timestamp": -1}},
        {"$group": {
            "_id": "$trade_date",
            "total_assets": {"$first": "$total_assets"},
            "net_value": {"$first": "$net_value"},
            "drawdown_pct": {"$first": "$drawdown_pct"},
            "position_ratio": {"$first": "$position_ratio"},
            "position_count": {"$first": "$position_count"},
            "realized_profit": {"$first": "$realized_profit"},
            "unrealized_profit": {"$first": "$unrealized_profit"},
            "source": {"$first": "$source"},
        }},
        {"$sort": {"_id": 1}},
    ]
    ps_cursor = mongo_manager.db["performance_snapshots"].aggregate(ps_pipeline)
    ps_data = []
    async for doc in ps_cursor:
        ps_data.append({
            "date": doc["_id"],
            "total_assets": doc.get("total_assets", 0) or 0,
            "net_value": doc.get("net_value", 1.0) or 1.0,
            "drawdown_pct": doc.get("drawdown_pct", 0) or 0,
            "position_ratio": doc.get("position_ratio", 0) or 0,
            "position_count": doc.get("position_count", 0) or 0,
            "realized_profit": doc.get("realized_profit", 0) or 0,
            "unrealized_profit": doc.get("unrealized_profit", 0) or 0,
            "source": doc.get("source", ""),
        })

    # 规范化: position_ratio>1的是倍数需÷100, <=1的是比例直接用
    for p in ps_data:
        if p["position_ratio"] > 1:
            p["position_ratio"] = p["position_ratio"] / 100

    # 补充equity_curve(有更详细的资金分解)
    ec_cursor = mongo_manager.db[COL_EQUITY].find({"trade_date": {"$exists": True}}).sort("trade_date", 1)
    ec_data = []
    async for doc in ec_cursor:
        ec_data.append({
            "date": doc.get("trade_date", 0) or doc.get("date", 0),
            "equity": doc.get("total_assets", 0) or doc.get("equity", 0) or 0,
            "cash": doc.get("available_cash", 0) or doc.get("cash", 0) or 0,
            "market_value": doc.get("market_value", 0) or 0,
            "realized_pnl": doc.get("realized_pnl", 0) or 0,
        })

    return {"success": True, "data": {"performance": ps_data, "equity": ec_data}}


@router.get("/risk-decisions/{trade_date}")
async def get_risk_decisions(trade_date: int, account_id: str = Query(default="default")):
    """当日风控决策详情 — risk_decisions集合"""
    cursor = mongo_manager.db["risk_decisions"].find(
        {"account_id": account_id, "trade_date": trade_date}
    ).sort("timestamp", 1)
    decisions = []
    async for doc in cursor:
        decisions.append({
            "ts_code": doc.get("ts_code", ""),
            "stock_name": doc.get("stock_name", ""),
            "decision_type": doc.get("decision_type", ""),
            "trigger_reason": doc.get("trigger_reason", ""),
            "cost_price": doc.get("cost_price", 0) or 0,
            "trigger_price": doc.get("trigger_price", 0) or 0,
            "filled_price": doc.get("filled_price", 0) or 0,
            "quantity": doc.get("quantity", 0) or 0,
            "profit_pct": doc.get("profit_pct", 0) or 0,
            "profit_loss": doc.get("profit_loss", 0) or doc.get("profit_amount", 0) or 0,
            "strategy": doc.get("strategy", ""),
            "timestamp": str(doc.get("timestamp", "")),
        })

    # 按类型统计
    type_counts = {}
    for d in decisions:
        t = d["decision_type"]
        type_counts[t] = type_counts.get(t, 0) + 1

    return {"success": True, "data": {"decisions": decisions, "type_counts": type_counts, "total": len(decisions)}}


@router.get("/strategy-stats/{trade_date}")
async def get_strategy_stats(trade_date: int, account_id: str = Query(default="default")):
    """策略统计 — 按策略聚合成交数据"""
    pipeline = [
        {"$match": {"account_id": account_id, "trade_date": trade_date, "status": "filled"}},
        {"$group": {
            "_id": {"strategy": "$strategy", "side": "$side"},
            "count": {"$sum": 1},
            "total_amount": {"$sum": {"$ifNull": ["$filled_amount", 0]}},
            "total_pnl": {"$sum": {"$ifNull": ["$profit_amount", 0]}},
        }},
    ]
    cursor = mongo_manager.db[COL_ORDERS].aggregate(pipeline)
    stats = {}
    async for doc in cursor:
        strat = doc["_id"].get("strategy", "unknown")
        side = doc["_id"].get("side", "")
        if strat not in stats:
            stats[strat] = {"strategy": strat, "buys": 0, "sells": 0, "buy_amount": 0, "sell_amount": 0, "pnl": 0}
        s = stats[strat]
        if side == "buy":
            s["buys"] = doc["count"]
            s["buy_amount"] = doc["total_amount"]
        else:
            s["sells"] = doc["count"]
            s["sell_amount"] = doc["total_amount"]
            s["pnl"] = doc["total_pnl"]

    return {"success": True, "data": list(stats.values())}
