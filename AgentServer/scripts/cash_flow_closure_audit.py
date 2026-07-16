#!/usr/bin/env python3
"""
资金流闭环审查 v1.0 (2026-07-16)

审查盲区: 现有审查检查账户等式(assets = cash + mv), 不检查逐笔交易的资金流是否闭环。

近期bug:
- v2.9.122 重复卖出虚增19.4万(同一股票被卖2次, 资金回收2次)
- v2.9.109 卖出资金不回收到available_cash
- 多次幽灵持仓(有买入无卖出无position, 资金凭空消失)

检查项:
1. 逐笔交易资金流追踪: buy->sell(s)->资金净变化是否等于profit
2. 同一ts_code持仓生命周期追踪: buy->持有N天->sell, 持仓数/成本变化是否连续
3. available_cash变化序列与所有orders的资金流一致性
4. 账户等式验证: assets = cash + sum(position mv)
5. 重复卖出检测: 同一ts_code同一天是否有多笔filled sell
6. 幽灵持仓检测: 有buy order但无position且无sell order
7. 孤儿卖出检测: 有sell order但无对应buy order
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

CRITICAL = []
WARNING = []
INFO = []

def p0(msg): CRITICAL.append(msg); print(f"  ❌ P0: {msg}")
def p1(msg): WARNING.append(msg); print(f"  ⚠️  P1: {msg}")
def ok(msg): print(f"  ✅ {msg}")
def info(msg): INFO.append(msg); print(f"  ℹ️  {msg}")


def get_mongo():
    try:
        import pymongo
        client = pymongo.MongoClient("localhost", 27017, serverSelectionTimeoutMS=5000)
        db = client["stock_agent"]
        db.command("ping")  # 验证连接
        return db
    except Exception as e:
        print(f"❌ MongoDB连接失败: {e}")
        return None


# ── 1. 逐笔交易资金流追踪 ──
def check_trade_cash_flow():
    print("\n═══ 1. 逐笔交易资金流追踪 ═══")
    db = get_mongo()
    if db is None:
        return
    
    # 获取最近30天的所有filled orders
    cutoff = int((datetime.now() - timedelta(days=30)).strftime("%Y%m%d"))
    orders = list(db["broker_orders"].find({
        "status": "filled",
        "trade_date": {"$gte": cutoff}
    }).sort("trade_date", 1))
    
    info(f"最近30天filled orders: {len(orders)}笔")
    
    # 按ts_code分组, 追踪每只股票的资金流
    by_stock = defaultdict(list)
    for o in orders:
        by_stock[o["ts_code"]].append(o)
    
    total_drift = 0
    drift_stocks = []
    
    for ts_code, ords in by_stock.items():
        if len(ords) < 2:
            continue  # 只有1笔, 无法验证闭环
        
        buy_cost = 0
        sell_income = 0
        buy_qty = 0
        sell_qty = 0
        
        for o in ords:
            side = o.get("side", "")
            qty = o.get("filled_qty", 0) or o.get("quantity", 0)
            price = o.get("filled_price", 0) or o.get("price", 0)
            commission = o.get("commission", 0) or 0
            stamp_duty = o.get("stamp_duty", 0) or 0
            
            if side == "buy":
                buy_cost += qty * price + commission
                buy_qty += qty
            elif side == "sell":
                sell_income += qty * price - commission - stamp_duty
                sell_qty += qty
        
        net_cash = sell_income - buy_cost
        
        # 如果全部已平仓(sell_qty == buy_qty), 净资金流应该等于总profit
        if sell_qty == buy_qty and buy_qty > 0:
            total_profit = sum(o.get("profit_amount", 0) or 0 for o in ords if o.get("side") == "sell")
            drift = net_cash - total_profit
            if abs(drift) > 1:  # 1元误差容忍
                p1(f"{ts_code}: 资金流漂移 {drift:+.2f}元 (net_cash={net_cash:.2f}, profit_sum={total_profit:.2f})")
                drift_stocks.append((ts_code, drift))
                total_drift += drift
            else:
                ok(f"{ts_code}: 资金流闭环 (net={net_cash:+.2f}, profit={total_profit:+.2f})")
        elif buy_qty > sell_qty:
            # 还有持仓, 检查未平仓部分
            remaining = buy_qty - sell_qty
            info(f"{ts_code}: 未完全平仓 (buy={buy_qty}, sell={sell_qty}, 剩余{remaining})")
        elif sell_qty > buy_qty:
            p0(f"{ts_code}: 卖出超过买入! buy_qty={buy_qty}, sell_qty={sell_qty} (重复卖出?)")
    
    if total_drift != 0:
        info(f"总资金流漂移: {total_drift:+.2f}元")
    if drift_stocks:
        info(f"漂移股票: {len(drift_stocks)}只")


# ── 2. 同一ts_code持仓生命周期追踪 ──
def check_position_lifecycle():
    print("\n═══ 2. 同一ts_code持仓生命周期追踪 ═══")
    db = get_mongo()
    if db is None:
        return
    
    orders = list(db["broker_orders"].find({
        "status": "filled",
    }).sort("trade_date", 1))
    
    by_stock = defaultdict(list)
    for o in orders:
        by_stock[o["ts_code"]].append(o)
    
    for ts_code, ords in by_stock.items():
        if len(ords) < 2:
            continue
        
        # 同一天内先buy后sell(避免同日买卖的顺序不确定导致误报超卖)
        ords.sort(key=lambda x: (x.get('trade_date', ''), 0 if x.get('side') == 'buy' else 1))
        
        # 追踪持仓数量变化
        holding_qty = 0
        avg_cost = 0
        lifecycle_issues = []
        
        for o in ords:
            side = o.get("side", "")
            qty = o.get("filled_qty", 0) or o.get("quantity", 0)
            price = o.get("filled_price", 0) or o.get("price", 0)
            trade_date = o.get("trade_date", "")
            
            if side == "buy":
                if holding_qty > 0:
                    # 加仓: 重算均价
                    total_base = avg_cost * holding_qty + qty * price
                    holding_qty += qty
                    avg_cost = total_base / holding_qty if holding_qty > 0 else 0
                else:
                    holding_qty = qty
                    avg_cost = price
            elif side == "sell":
                if qty > holding_qty:
                    # 检查是否是同日买卖(v2.9.121兜底路径)
                    same_day_buy = any(
                        oo.get('side') == 'buy' and oo.get('trade_date') == trade_date
                        for oo in ords
                    )
                    if same_day_buy:
                        info(f"{ts_code}: {trade_date}: 同日买卖{qty}股(非超卖, v2.9.121兜底)")
                    else:
                        lifecycle_issues.append(
                            f"{trade_date}: 卖出{qty}但持仓只有{holding_qty} (超卖)"
                        )
                else:
                    holding_qty -= qty
                    if holding_qty <= 0:
                        holding_qty = 0
                        avg_cost = 0
        
        if lifecycle_issues:
            for issue in lifecycle_issues:
                p0(f"{ts_code}: {issue}")


# ── 3. available_cash与orders推算一致性 ──
def check_cash_vs_orders():
    print("\n═══ 3. available_cash与orders推算一致性 ═══")
    db = get_mongo()
    if db is None:
        return
    
    # 获取账户
    account = db["broker_accounts"].find_one({"account_id": "default"})
    if not account:
        p0("找不到default账户")
        return
    
    cash_actual = account.get("available_cash", 0)
    initial_cash = 1_000_000  # 初始资金
    
    # 从orders推算cash
    orders = list(db["broker_orders"].find({"status": "filled", "account_id": "default"}).sort("trade_date", 1))
    
    cash_calc = initial_cash
    for o in orders:
        side = o.get("side", "")
        qty = o.get("filled_qty", 0) or o.get("quantity", 0)
        price = o.get("filled_price", 0) or o.get("price", 0)
        commission = o.get("commission", 0) or 0
        stamp_duty = o.get("stamp_duty", 0) or 0
        
        if side == "buy":
            cash_calc -= qty * price + commission
        elif side == "sell":
            cash_calc += qty * price - commission - stamp_duty
    
    drift = cash_actual - cash_calc
    
    info(f"账户cash: {cash_actual:,.2f}")
    info(f"orders推算: {cash_calc:,.2f}")
    info(f"漂移: {drift:+,.2f}元")
    
    if abs(drift) < 100:
        ok(f"cash与orders一致 (漂移<{100}元, 可接受的佣金误差)")
    elif abs(drift) < 1000:
        p1(f"cash与orders有{drift:+,.2f}元漂移 (可能是佣金计算差异)")
    else:
        p0(f"cash与orders有{drift:+,.2f}元大漂移 (可能存在重复卖出/资金虚增/丢失)")


# ── 4. 账户等式验证 ──
def check_account_equation():
    print("\n═══ 4. 账户等式验证 ═══")
    db = get_mongo()
    if db is None:
        return
    
    account = db["broker_accounts"].find_one({"account_id": "default"})
    if not account:
        p0("找不到default账户")
        return
    
    total_assets = account.get("total_assets", 0)
    cash = account.get("available_cash", 0)
    mv = account.get("market_value", 0)
    
    # 方法1: assets = cash + mv
    eq1_drift = total_assets - (cash + mv)
    info(f"等式1: total_assets({total_assets:,.2f}) = cash({cash:,.2f}) + mv({mv:,.2f}), 漂移={eq1_drift:+.2f}")
    if abs(eq1_drift) > 1:
        p0(f"账户等式不平衡: assets != cash + mv, 漂移{eq1_drift:+.2f}元")
    else:
        ok("账户等式: assets = cash + mv ✅")
    
    # 方法2: 从positions重算mv
    positions = list(db["broker_positions"].find({"account_id": "default"}))
    mv_calc = sum(
        p.get("current_price", 0) * p.get("total_qty", 0)
        for p in positions
    )
    mv_drift = mv - mv_calc
    info(f"等式2: mv({mv:,.2f}) vs positions推算({mv_calc:,.2f}), 漂移={mv_drift:+.2f}")
    if abs(mv_drift) > 1:
        p1(f"market_value与positions推算不一致, 漂移{mv_drift:+.2f}元")
    else:
        ok("market_value与positions推算一致")
    
    # 方法3: total_profit = total_assets - initial_cash
    total_profit_stored = account.get("total_profit", 0)
    total_profit_calc = total_assets - 1_000_000
    profit_drift = total_profit_stored - total_profit_calc
    info(f"等式3: total_profit({total_profit_stored:,.2f}) vs assets-initial({total_profit_calc:,.2f}), 漂移={profit_drift:+.2f}")
    if abs(profit_drift) > 1:
        p1(f"total_profit与assets-initial不一致, 漂移{profit_drift:+.2f}元")


# ── 5. 重复卖出检测 ──
def check_duplicate_sells():
    print("\n═══ 5. 重复卖出检测 ═══")
    db = get_mongo()
    if db is None:
        return
    
    # 按ts_code + trade_date分组, 检查同一天同一股票是否有多笔filled sell
    pipeline = [
        {"$match": {"status": "filled", "side": "sell"}},
        {"$group": {
            "_id": {"ts_code": "$ts_code", "trade_date": "$trade_date"},
            "count": {"$sum": 1},
            "orders": {"$push": {"order_id": "$order_id", "qty": "$filled_qty", "price": "$filled_price"}}
        }},
        {"$match": {"count": {"$gte": 2}}}
    ]
    
    duplicates = list(db["broker_orders"].aggregate(pipeline))
    
    if not duplicates:
        ok("无重复卖出记录 (同一ts_code同一天无多笔filled sell)")
    else:
        for dup in duplicates:
            ts_code = dup["_id"]["ts_code"]
            trade_date = dup["_id"]["trade_date"]
            count = dup["count"]
            p0(f"重复卖出: {ts_code} 日期{trade_date} 有{count}笔filled sell: {dup['orders']}")


# ── 6. 幽灵持仓检测 ──
def check_ghost_positions():
    print("\n═══ 6. 幽灵持仓检测 ═══")
    db = get_mongo()
    if db is None:
        return
    
    # 获取所有filled buy orders的ts_code
    buy_codes = set()
    for o in db["broker_orders"].find({"status": "filled", "side": "buy", "account_id": "default"}):
        buy_codes.add(o["ts_code"])
    
    # 获取所有filled sell orders的ts_code
    sell_codes = set()
    for o in db["broker_orders"].find({"status": "filled", "side": "sell", "account_id": "default"}):
        sell_codes.add(o["ts_code"])
    
    # 获取当前持仓的ts_code
    position_codes = set()
    for p in db["broker_positions"].find({"account_id": "default"}):
        position_codes.add(p["ts_code"])
    
    # 幽灵持仓: 有buy但无sell且不在positions
    ghost = buy_codes - sell_codes - position_codes
    if ghost:
        for ts_code in ghost:
            # 查看最后一笔buy的详情
            last_buy = db["broker_orders"].find_one(
                {"ts_code": ts_code, "side": "buy", "status": "filled"},
                sort=[("trade_date", -1)]
            )
            if last_buy:
                p1(f"幽灵持仓: {ts_code} 有buy({last_buy['trade_date']}@{last_buy.get('filled_price',0)}) "
                    f"但无sell且不在positions中, 资金凭空消失")
    else:
        ok("无幽灵持仓")
    
    # 孤儿卖出: 有sell但无buy
    orphan = sell_codes - buy_codes
    if orphan:
        for ts_code in orphan:
            p0(f"孤儿卖出: {ts_code} 有sell但无buy (数据损坏或test_account残留)")
    else:
        ok("无孤儿卖出")


# ── 7. 持仓数量一致性 ──
def check_position_qty_consistency():
    print("\n═══ 7. 持仓数量一致性 ═══")
    db = get_mongo()
    if db is None:
        return
    
    # 对每个当前持仓, 从orders推算数量是否一致
    positions = list(db["broker_positions"].find({"account_id": "default"}))
    
    for pos in positions:
        ts_code = pos["ts_code"]
        pos_qty = pos.get("total_qty", 0)
        
        # 从orders推算
        buy_qty = 0
        sell_qty = 0
        for o in db["broker_orders"].find({
            "ts_code": ts_code, "status": "filled", "account_id": "default"
        }).sort("trade_date", 1):
            if o["side"] == "buy":
                buy_qty += o.get("filled_qty", 0) or 0
            elif o["side"] == "sell":
                sell_qty += o.get("filled_qty", 0) or 0
        
        calc_qty = buy_qty - sell_qty
        
        if calc_qty != pos_qty:
            p0(f"{ts_code}: 持仓数量不一致 (positions={pos_qty}, orders推算={calc_qty}, "
                f"buy={buy_qty}, sell={sell_qty})")
        else:
            ok(f"{ts_code}: 持仓数量一致 ({pos_qty})")
    
    # 检查持仓数是否超限
    MAX_POSITIONS = 10
    if len(positions) > MAX_POSITIONS:
        p1(f"持仓数{len(positions)}超过上限{MAX_POSITIONS}")
    else:
        ok(f"持仓数{len(positions)} <= 上限{MAX_POSITIONS}")


def main():
    print("=" * 60)
    print("资金流闭环审查 v1.0 - 2026-07-16")
    print("=" * 60)
    
    check_trade_cash_flow()
    check_position_lifecycle()
    check_cash_vs_orders()
    check_account_equation()
    check_duplicate_sells()
    check_ghost_positions()
    check_position_qty_consistency()
    
    print("\n" + "=" * 60)
    print(f"汇总: P0={len(CRITICAL)}, P1={len(WARNING)}, Info={len(INFO)}")
    if CRITICAL:
        print("\n❌ P0问题:")
        for c in CRITICAL:
            print(f"  - {c}")
    if WARNING:
        print("\n⚠️  P1问题:")
        for w in WARNING:
            print(f"  - {w}")
    print("=" * 60)
    
    return 1 if CRITICAL else (2 if WARNING else 0)


if __name__ == "__main__":
    sys.exit(main())
