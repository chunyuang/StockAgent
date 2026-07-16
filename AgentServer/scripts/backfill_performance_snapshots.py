#!/usr/bin/env python3
"""【v2.9.107】performance_snapshots 历史回填脚本

用途:
- v2.9.106 之前主循环未稳定调用 save_performance_snapshot, 导致集合长期为空
- 本脚本从 broker_orders/broker_accounts 重建过去 N 天的每日资产快照
- 一次性运行,后续由 daily_settlement 接管

使用:
    python scripts/backfill_performance_snapshots.py [--days 30] [--dry-run]
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.managers import mongo_manager


INITIAL_CASH = 1_000_000.0  # 初始资金


async def get_trading_days(db, days_back: int) -> list:
    """从 stock_daily_ak_full 取最近 N 个交易日"""
    cursor = db["stock_daily_ak_full"].aggregate([
        {"$group": {"_id": "$trade_date"}},
        {"$sort": {"_id": -1}},
        {"$limit": days_back},
    ])
    docs = await cursor.to_list(length=days_back)
    return sorted([int(d["_id"]) for d in docs if isinstance(d["_id"], (int, str))])


async def build_snapshot_for_date(db, trade_date: int, account_id: str = "default") -> dict:
    """重建某一天的绩效快照"""
    # 1. 当日及之前的所有 filled orders
    orders = await db["broker_orders"].find({
        "account_id": account_id,
        "status": "filled",
        "trade_date": {"$lte": trade_date},
    }).sort("trade_date", 1).to_list(length=10000)

    # 2. 从 orders 推算到此日为止的现金/持仓
    cash = INITIAL_CASH
    positions = {}  # ts_code -> {'qty': int, 'cost': float}
    realized_profit = 0.0

    for o in orders:
        side = o.get("side")
        qty = int(o.get("filled_qty") or o.get("quantity") or 0)
        price = float(o.get("filled_price") or o.get("price") or 0)
        commission = float(o.get("commission") or 0)
        if side == "buy":
            cash -= qty * price + commission
            p = positions.setdefault(o["ts_code"], {"qty": 0, "cost": 0.0})
            new_qty = p["qty"] + qty
            p["cost"] = (p["cost"] * p["qty"] + price * qty) / max(new_qty, 1)
            p["qty"] = new_qty
        elif side == "sell":
            cash += qty * price - commission
            p = positions.get(o["ts_code"])
            if p:
                realized_profit += (price - p["cost"]) * qty - commission
                p["qty"] -= qty
                if p["qty"] <= 0:
                    positions.pop(o["ts_code"], None)

    # 3. 当日收盘价计算 market_value
    market_value = 0.0
    pos_list = []
    for ts_code, p in positions.items():
        if p["qty"] <= 0:
            continue
        # 查当日收盘价
        daily = await db["stock_daily_ak_full"].find_one(
            {"ts_code": ts_code, "trade_date": trade_date},
            {"close": 1}
        )
        close = float(daily.get("close")) if daily and daily.get("close") else p["cost"]
        market_value += close * p["qty"]
        pos_list.append({"ts_code": ts_code, "qty": p["qty"], "cost": p["cost"], "close": close})

    total_assets = cash + market_value
    net_value = total_assets / INITIAL_CASH
    total_profit = total_assets - INITIAL_CASH

    return {
        "account_id": account_id,
        "trade_date": trade_date,
        "timestamp": f"{trade_date}T15:00:00",
        "total_assets": round(total_assets, 2),
        "available_cash": round(cash, 2),
        "market_value": round(market_value, 2),
        "total_profit": round(total_profit, 2),
        "realized_profit": round(realized_profit, 2),
        "unrealized_profit": round(total_profit - realized_profit, 2),
        "net_value": round(net_value, 6),
        "position_count": len(pos_list),
        "position_ratio": round(market_value / total_assets * 100, 2) if total_assets > 0 else 0,
        "source": "backfill_v2.9.107",
    }


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--account-id", default="default")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    await mongo_manager.initialize()
    db = mongo_manager.db

    days = await get_trading_days(db, args.days)
    print(f"[backfill] 待回填交易日: {days[0]} ~ {days[-1]} ({len(days)} 天)")

    # 计算 nav_peak (累计高点)
    nav_peak = 1.0
    snapshots = []
    for td in days:
        snap = await build_snapshot_for_date(db, td, args.account_id)
        nav_peak = max(nav_peak, snap["net_value"])
        snap["drawdown_pct"] = round((snap["net_value"] / nav_peak - 1) * 100, 3)
        snapshots.append(snap)
        print(f"  {td}: 总资产={snap['total_assets']:>10.2f} 净值={snap['net_value']:.4f} 回撤={snap['drawdown_pct']:>6.2f}% 持仓={snap['position_count']}")

    if args.dry_run:
        print(f"[backfill] DRY RUN, 共 {len(snapshots)} 条未写入")
        return

    # 删除旧的 backfill 记录, upsert 新数据
    deleted = await db["performance_snapshots"].delete_many({
        "account_id": args.account_id,
        "trade_date": {"$in": days},
        "source": "backfill_v2.9.107",
    })
    print(f"[backfill] 清除旧 backfill 记录: {deleted.deleted_count}")

    for snap in snapshots:
        await db["performance_snapshots"].update_one(
            {"account_id": snap["account_id"], "trade_date": snap["trade_date"], "source": "backfill_v2.9.107"},
            {"$set": snap},
            upsert=True,
        )
    print(f"[backfill] ✅ 完成, upsert {len(snapshots)} 条到 performance_snapshots")


if __name__ == "__main__":
    asyncio.run(main())
