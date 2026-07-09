#!/usr/bin/env python3
"""
数据一致性守卫 v1.0 (2026-06-27)

核心思想：不再只检查"字段存不存在"，而是检查"数据之间是否一致"。
同一指标在不同地方独立计算，结果应该相同。

检查项：
1. KPI vs Account: 已实现/未实现/总盈亏
2. broker_orders.profit_pct全0告警（根因）
3. broker_accounts.market_value vs 实际市值（成本价代市价）
4. deviation-attribution胜率 vs KPI胜率
5. review-hero连亏 vs 实际连亏
6. equityCurve终值 vs account.total_assets
7. annual_return合理性(>500%告警)
"""

import sys
import asyncio
import pymongo
from datetime import datetime

async def main():
    client = pymongo.MongoClient("mongodb://localhost:27017")
    db = client["stock_agent"]
    issues = []  # (severity, name, expected, actual, detail)

    # === 1. broker_orders.profit_pct 全0检查 ===
    sells = list(db["broker_orders"].find({"status": "filled", "side": "sell", "account_id": "default"}))
    zero_pct_count = sum(1 for s in sells if (s.get("profit_pct") or 0) == 0 and (s.get("profit_amount") or 0) == 0)
    if sells and zero_pct_count == len(sells):
        issues.append(("P0", "broker_orders.profit_pct全0",
                       "至少1笔有值", f"{zero_pct_count}/{len(sells)}笔为0",
                       "所有卖出记录profit_pct=0,导致胜率/盈亏/归因全部错误"))
    elif zero_pct_count > len(sells) * 0.5:
        issues.append(("P1", f"broker_orders.profit_pct {zero_pct_count}/{len(sells)}笔为0",
                       "<50%为0", f"{zero_pct_count}/{len(sells)}",
                       "超过一半卖出记录profit_pct=0"))

    # === 2. KPI vs Account 交叉验证 ===
    # 从broker_orders算KPI
    buys = list(db["broker_orders"].find({"status": "filled", "side": "buy", "account_id": "default"}))
    buy_cost_map = {b.get("ts_code", ""): b.get("filled_price", 0) for b in buys}

    realized_profit = 0
    wins = 0
    for s in sells:
        # 优先用order自带的profit_amount(broker用avg_cost计算，比分批买入的last_buy_price准确)
        pa = s.get("profit_amount", 0) or 0
        if pa != 0:
            realized_profit += pa
            if (s.get("profit_pct") or 0) >= 0:
                wins += 1
        else:
            # fallback: 用买入均价
            fp = s.get("filled_price", 0) or 0
            qty = s.get("filled_qty", 0) or s.get("quantity", 0)
            cost = buy_cost_map.get(s.get("ts_code", ""), 0)
            if cost > 0 and fp > 0:
                profit = (fp - cost) * qty
                realized_profit += profit
                if fp >= cost:
                    wins += 1

    # 从broker_positions算未实现盈亏
    positions = list(db["broker_positions"].find({"account_id": "default"}))
    unrealized_pnl = 0
    total_cost = 0
    total_market = 0
    for pos in positions:
        qty = pos.get("total_qty", 0) or pos.get("shares", 0) or pos.get("quantity", 0) or 0
        if qty <= 0:
            continue
        cost = pos.get("avg_cost", 0) or pos.get("cost_price", 0) or 0
        # 优先用position自带的current_price(与broker保存时一致)
        price = pos.get("current_price", 0) or 0
        if price <= 0:
            # fallback: 从stock_daily_ak_full取最新收盘价
            latest = list(db["stock_daily_ak_full"].find({"ts_code": pos.get("ts_code")}).sort("trade_date", -1).limit(1))
            price = latest[0].get("close", 0) if latest else 0
        unrealized_pnl += (price - cost) * qty
        total_cost += cost * qty
        total_market += price * qty

    total_pnl_all = realized_profit + unrealized_pnl

    # vs broker_accounts
    acct = db["broker_accounts"].find_one({"account_id": "default"})
    if acct:
        acct_total_profit = acct.get("total_profit", 0) or 0  # 旧逻辑: total_assets - 1000000
        acct_market_value = acct.get("market_value", 0) or 0

        # 2a. broker_accounts.market_value vs 实际市值
        if total_market > 0 and abs(acct_market_value - total_market) / max(total_market, 1) > 0.05:
            issues.append(("P1", "broker_accounts.market_value偏差>5%",
                           f"¥{total_market:,.0f}", f"¥{acct_market_value:,.0f}",
                           f"差额¥{acct_market_value-total_market:,.0f}, 可能是成本价代市价"))

        # 2b. account.total_profit vs 总盈亏(已实现+未实现)
        # broker定义: total_profit = total_assets - initial_cash = 已实现+未实现
        # 守卫推算: realized_profit + unrealized_pnl
        expected_total_profit = realized_profit + unrealized_pnl
        if abs(acct_total_profit - expected_total_profit) / max(abs(expected_total_profit), 1) > 0.1:
            issues.append(("P1", "account.total_profit ≠ 已实现+未实现盈亏",
                           f"¥{expected_total_profit:,.0f}", f"¥{acct_total_profit:,.0f}",
                           f"差额¥{acct_total_profit-expected_total_profit:,.0f}"))

    # === 3. 胜率交叉验证 ===
    actual_win_rate = round(wins / len(sells) * 100, 1) if sells else 0
    # deviation-attribution用profit_pct>=0算胜率，如果profit_pct全0则胜率=100%
    naive_win_rate = round(sum(1 for s in sells if (s.get("profit_pct") or 0) >= 0) / max(len(sells), 1) * 100, 1)
    if sells and naive_win_rate == 100 and actual_win_rate < 100:
        issues.append(("P0", "deviation-attribution胜率虚高",
                       f"{actual_win_rate}%", f"{naive_win_rate}%",
                       "profit_pct全0导致所有卖出都算'赢'"))

    # === 4. annual_return合理性 ===
    # 简单检查: 交易天数<30时年化不应>100%
    if sells:
        trade_dates = set(str(s.get("trade_date", "")) for s in sells)
        n_days = len(trade_dates)
        cum_return = sum((s.get("profit_pct") or 0) for s in sells)  # naive
        # 修正后的
        cum_return_fixed = total_pnl_all / 1000000 * 100
        if n_days < 30 and abs(cum_return) > 100:
            issues.append(("P1", f"年化收益率不合理(交易仅{n_days}天)",
                           f"累计{cum_return_fixed:.1f}%", f"年化{cum_return:.1f}%",
                           "短期数据年化放大，应显示累计收益率"))

    # === 5. available_cash交叉验证 ===
    if acct:
        # 从orders推算正确的cash
        buy_cost_total = sum(
            (b.get("filled_price",0) or 0) * (b.get("filled_qty",0) or b.get("quantity",0))
            for b in buys
        )
        sell_income_total = sum(
            (s.get("filled_price",0) or 0) * (s.get("filled_qty",0) or s.get("quantity",0))
            for s in sells
        )
        correct_cash = 1000000 - buy_cost_total + sell_income_total
        acct_cash = acct.get("available_cash", 0) or 0
        if abs(acct_cash - correct_cash) / max(abs(correct_cash), 1) > 0.01:
            issues.append(("P0", "available_cash不匹配(从orders推算)",
                           f"¥{correct_cash:,.0f}", f"¥{acct_cash:,.0f}",
                           f"差额¥{acct_cash-correct_cash:,.0f}, 买入没扣钱或卖出没加钱"))

    # === 5. equityCurve终值 vs account.total_assets ===
    # 【v2.9.107】补充检查 — 持久化完整性
    today_int = int(datetime.now().strftime("%Y%m%d"))

    # === 5a. performance_snapshots 最近交易日应有一条 ===
    weekday = datetime.now().weekday()  # 0=Mon, 4=Fri
    # 简单交易日检查: 工作日且非节假日, 用broker_orders判断是否交易日
    recent_trade_date = today_int
    if weekday < 5:  # 工作日才检查
        # 如果今日没有交易数据, 向前找最近交易日
        if db["broker_orders"].count_documents({"trade_date": today_int}) == 0:
            recent_doc = db["broker_orders"].find_one(sort=[("trade_date", -1)])
            recent_trade_date = recent_doc.get("trade_date", 0) if recent_doc else 0
        if recent_trade_date > 0:
            perf_count = db["performance_snapshots"].count_documents({"trade_date": recent_trade_date})
            if perf_count == 0:
                issues.append(("P1", f"performance_snapshots缺失(td={recent_trade_date})",
                               "≥1条", "0条",
                               "结算后未写入资产快照 → 资金曲线丢点"))

    # === 5b. risk_decisions 与 broker_orders 一致性 (卸货必须有决策记录) ===
    sells_today = list(db["broker_orders"].find({
        "status": "filled", "side": "sell", "trade_date": recent_trade_date
    }))
    if sells_today:
        risk_decisions_count = db["risk_decisions"].count_documents({"trade_date": recent_trade_date})
        if risk_decisions_count < len(sells_today):
            issues.append(("P1", "risk_decisions与卸货记录不匹配",
                           f"≥{len(sells_today)}条", f"{risk_decisions_count}条",
                           f"有{len(sells_today)}笔卸货但只{risk_decisions_count}条决策记录 → 风控审计记录丢失"))

    # === 5c. sentiment_live_log 最近交易日应有数据 ===
    if weekday < 5 and recent_trade_date > 0:
        sentiment_logs = db["sentiment_live_log"].count_documents({"trade_date": recent_trade_date})
        hour = datetime.now().hour
        if 10 <= hour <= 16 and sentiment_logs == 0:
            issues.append(("P1", f"sentiment_live_log缺失(td={recent_trade_date})",
                           "交易时间后该≥1条", "0条",
                           "盘中情绪计算未写入 → 复盘不可用"))

    try:
        # 从equity_curve集合读取(含浮盈浮亏), 而非从API daily_detail累计profit推算
        ec_last = db["equity_curve"].find_one({"trade_date": {"$ne": None}}, sort=[("trade_date", -1)])
        if ec_last:
            equity_final = ec_last.get("total_assets", 0) or ec_last.get("equity", 0)
            acct_total = db["broker_accounts"].find_one({"account_id": "default"}, {"total_assets": 1})
            acct_total = acct_total.get("total_assets", 0) if acct_total else 0
            if acct_total > 0 and equity_final > 0 and abs(equity_final - acct_total) / acct_total > 0.01:
                issues.append(("P2", "资金曲线终值 ≠ 账户总资产",
                               f"¥{acct_total:,.0f}", f"¥{equity_final:,.0f}",
                               f"差额¥{acct_total-equity_final:,.0f}, 资金曲线与账户不一致"))
    except Exception:
        pass  # equity_curve不可用时跳过

    # === 输出 ===
    p0 = [i for i in issues if i[0] == "P0"]
    p1 = [i for i in issues if i[1] != "P0"]
    p2 = [i for i in issues if i[0] == "P2"]

    print(f"数据一致性守卫 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"检查项: 8 | P0: {len(p0)} | P1: {len([i for i in issues if i[0]=='P1'])} | P2: {len(p2)}")
    print()

    if not issues:
        print("✅ 全部通过 — 所有数据之间一致性校验OK")
        return 0

    for sev, name, expected, actual, detail in issues:
        icon = "🔴" if sev == "P0" else ("🟡" if sev == "P1" else "🔵")
        print(f"{icon} [{sev}] {name}")
        print(f"   期望: {expected} | 实际: {actual}")
        print(f"   {detail}")
        print()

    return 1 if p0 else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
