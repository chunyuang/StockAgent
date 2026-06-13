"""scanner_analysis.py — 结果分析API
从MongoDB聚合多日交易数据，计算KPI、策略贡献、卖出原因、月度收益等
"""
from fastapi import APIRouter
from typing import Optional

router = APIRouter(prefix="/scanner", tags=["analysis"])

STRAT_MAP = {"halfway_chase": "半路追涨", "first_limit": "首板打板", "dragon_head": "龙头回调", "limit_bounce": "跌停翘板"}

def _norm_strat(s):
    return STRAT_MAP.get(s, s or "未知")

def _date_filter(start_date: str = None, end_date: str = None):
    """生成兼容int/string的trade_date过滤条件"""
    if not start_date and not end_date:
        return {}
    # 收集所有需要匹配的日期值(int + string)
    # 简化: 用 $gte/$lte 同时查int和string
    conditions = []
    sd = start_date.replace("-", "") if start_date else None
    ed = end_date.replace("-", "") if end_date else None
    
    if sd and ed:
        # 同时匹配string和int范围
        conditions.append({"trade_date": {"$gte": sd, "$lte": ed}})  # string比较
        conditions.append({"trade_date": {"$gte": int(sd), "$lte": int(ed)}})  # int比较
        return {"$or": conditions}
    elif sd:
        return {"$or": [{"trade_date": {"$gte": sd}}, {"trade_date": {"$gte": int(sd)}}]}
    elif ed:
        return {"$or": [{"trade_date": {"$lte": ed}}, {"trade_date": {"$lte": int(ed)}}]}
    return {}

@router.get("/analysis")
async def get_analysis(start_date: str = None, end_date: str = None):
    """市场监听结果分析 — 综合KPI + 策略贡献 + 卖出原因 + 月度收益 + 持仓分析 + 每日明细"""
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": False, "message": "MongoDB未初始化"}
        
        db = mongo_manager.db
        
        # 1. 从scanner_timeline获取卖出记录(含profit)
        df = _date_filter(start_date, end_date)
        tl_match = {"action": "sell"}
        if df:
            tl_match = {"$and": [{"action": "sell"}, df]} if "$or" in df else {"action": "sell", **df}
        
        sells = await db["scanner_timeline"].find(tl_match).sort("time", 1).to_list(5000)
        
        # 2. 计算KPI
        total_trades = len(sells)
        if total_trades == 0:
            return {"success": True, "data": _empty_result()}
        
        profits = [s.get("profit_pct", 0) or 0 for s in sells]
        profit_amounts = [s.get("profit_amount", 0) or 0 for s in sells]
        wins = [p for p in profits if p >= 0]
        losses = [p for p in profits if p < 0]
        
        total_profit = sum(profit_amounts)
        win_rate = len(wins) / total_trades * 100 if total_trades > 0 else 0
        avg_profit = sum(wins) / len(wins) if wins else 0
        avg_loss = sum(losses) / len(losses) if losses else 0
        profit_loss_ratio = abs(avg_profit / avg_loss) if avg_loss != 0 else 99.99
        
        # 最大回撤(基于profit_pct收益率序列)
        cur_eq = 1.0  # 当前权益(1.0=100%起始)
        eq_peak = 1.0  # 权益峰值
        max_dd = 0
        for pct in profits:
            cur_eq *= (1 + pct / 100)  # 每笔交易后权益变化
            if cur_eq > eq_peak:
                eq_peak = cur_eq
            if eq_peak > 0:
                dd = (eq_peak - cur_eq) / eq_peak * 100
                if dd > max_dd:
                    max_dd = dd
        
        kpi = {
            "total_trades": total_trades,
            "total_profit": round(total_profit, 0),
            "win_rate": round(win_rate, 1),
            "profit_loss_ratio": round(min(profit_loss_ratio, 99.99), 2),
            "max_drawdown": round(max_dd, 2),
            "avg_profit_pct": round(sum(profits) / len(profits), 2) if profits else 0,
            "avg_win_pct": round(avg_profit, 2),
            "avg_loss_pct": round(avg_loss, 2),
        }
        
        # 3. 策略贡献
        strat_data = {}
        for s in sells:
            strat = _norm_strat(s.get("strategy", "未知"))
            if strat not in strat_data:
                strat_data[strat] = {"trades": 0, "wins": 0, "profit": 0, "profit_pct_sum": 0}
            strat_data[strat]["trades"] += 1
            strat_data[strat]["profit"] += s.get("profit_amount", 0) or 0
            strat_data[strat]["profit_pct_sum"] += s.get("profit_pct", 0) or 0
            if (s.get("profit_pct", 0) or 0) >= 0:
                strat_data[strat]["wins"] += 1
        
        strategy_contrib = []
        for name, d in sorted(strat_data.items(), key=lambda x: x[1]["profit"], reverse=True):
            strategy_contrib.append({
                "strategy": name,
                "trades": d["trades"],
                "win_rate": round(d["wins"] / d["trades"] * 100, 1) if d["trades"] else 0,
                "profit": round(d["profit"], 0),
                "avg_profit_pct": round(d["profit_pct_sum"] / d["trades"], 2) if d["trades"] else 0,
            })
        
        # 4. 卖出原因统计
        reason_data = {}
        for s in sells:
            reason = s.get("reason", "其他") or "其他"
            if "止损" in reason or "stop" in reason.lower():
                reason = "止损"
            elif "止盈" in reason or "take_profit" in reason.lower():
                reason = "止盈"
            elif "冲高回落" in reason or "pullback" in reason.lower():
                reason = "冲高回落"
            elif "调仓" in reason or "rebalance" in reason.lower():
                reason = "调仓"
            elif "保护" in reason or "protect" in reason.lower():
                reason = "利润保护"
            elif "到期" in reason or "max_hold" in reason.lower():
                reason = "到期"
            else:
                reason = reason[:8]
            
            if reason not in reason_data:
                reason_data[reason] = {"count": 0, "profit": 0}
            reason_data[reason]["count"] += 1
            reason_data[reason]["profit"] += s.get("profit_amount", 0) or 0
        
        sell_reasons = []
        for name, d in sorted(reason_data.items(), key=lambda x: x[1]["count"], reverse=True):
            sell_reasons.append({"reason": name, "count": d["count"], "profit": round(d["profit"], 0)})
        
        # 5. 月度收益
        monthly_data = {}
        for s in sells:
            td = str(s.get("trade_date", ""))
            if len(td) >= 6:
                month_key = td[:6]
                if month_key not in monthly_data:
                    monthly_data[month_key] = {"profit": 0, "trades": 0, "wins": 0}
                monthly_data[month_key]["profit"] += s.get("profit_amount", 0) or 0
                monthly_data[month_key]["trades"] += 1
                if (s.get("profit_pct", 0) or 0) >= 0:
                    monthly_data[month_key]["wins"] += 1
        
        monthly = []
        cum_profit = 0
        for m in sorted(monthly_data.keys()):
            d = monthly_data[m]
            cum_profit += d["profit"]
            monthly.append({
                "month": f"{m[:4]}-{m[4:]}",
                "profit": round(d["profit"], 0),
                "cum_profit": round(cum_profit, 0),
                "trades": d["trades"],
                "win_rate": round(d["wins"] / d["trades"] * 100, 1) if d["trades"] else 0,
            })
        
        # 6. 每日明细
        daily_data = {}
        for s in sells:
            td = str(s.get("trade_date", ""))
            if td:
                if td not in daily_data:
                    daily_data[td] = {"profit": 0, "trades": 0, "wins": 0}
                daily_data[td]["profit"] += s.get("profit_amount", 0) or 0
                daily_data[td]["trades"] += 1
                if (s.get("profit_pct", 0) or 0) >= 0:
                    daily_data[td]["wins"] += 1
        
        daily_detail = []
        for d in sorted(daily_data.keys()):
            info = daily_data[d]
            daily_detail.append({
                "date": f"{d[:4]}-{d[4:6]}-{d[6:]}" if len(d) == 8 else d,
                "trades": info["trades"],
                "profit": round(info["profit"], 0),
                "win_rate": round(info["wins"] / info["trades"] * 100, 1) if info["trades"] else 0,
            })
        
        # 7. 当前持仓(从scanner_timeline推算: buy累计-sell累计)
        positions = []
        try:
            # 从timeline汇总每只股票的净持仓
            holdings = {}  # ts_code -> {qty, total_cost, name, strategy}
            async for doc in mongo_manager.db["scanner_timeline"].find({"action": {"$in": ["buy", "sell"]}}).sort("time", 1):
                tc = doc.get("ts_code", "")
                if not tc:
                    continue
                action = doc.get("action")
                shares = doc.get("shares", 0) or 0
                price = doc.get("price", 0) or doc.get("filled_price", 0) or 0
                
                if tc not in holdings:
                    holdings[tc] = {"qty": 0, "total_cost": 0, "name": doc.get("stock_name", ""), "strategy": doc.get("strategy", ""), "trades": 0}
                
                if action == "buy":
                    holdings[tc]["qty"] += shares
                    holdings[tc]["total_cost"] += shares * price
                    holdings[tc]["strategy"] = doc.get("strategy", holdings[tc]["strategy"])
                    holdings[tc]["trades"] += 1
                elif action == "sell":
                    holdings[tc]["qty"] -= shares
                    if holdings[tc]["qty"] > 0:
                        holdings[tc]["total_cost"] -= shares * price
                    else:
                        holdings[tc]["total_cost"] = 0
            
            # 获取最新价格(从daily_basic或current)
            for tc, h in holdings.items():
                if h["qty"] <= 0:
                    continue
                avg_cost = h["total_cost"] / h["qty"] if h["qty"] > 0 else 0
                # 尝试获取当前价格
                cur_price = avg_cost  # 默认用成本价
                try:
                    latest = await mongo_manager.db["stock_daily_ak_full"].find_one(
                        {"ts_code": tc}, {"close": 1}, sort=[("trade_date", -1)]
                    )
                    if latest and latest.get("close"):
                        cur_price = float(latest["close"])
                except Exception:
                    pass
                
                profit_pct = (cur_price - avg_cost) / avg_cost * 100 if avg_cost > 0 else 0
                positions.append({
                    "ts_code": tc,
                    "stock_name": h["name"],
                    "strategy": _norm_strat(h["strategy"]),
                    "shares": h["qty"],
                    "cost_price": round(avg_cost, 2),
                    "current_price": round(cur_price, 2),
                    "profit_pct": round(profit_pct, 2),
                    "profit_amount": round((cur_price - avg_cost) * h["qty"], 0),
                    "market_value": round(cur_price * h["qty"], 0),
                })
        except Exception:
            pass
        
        return {"success": True, "data": {
            "kpi": kpi,
            "strategy_contrib": strategy_contrib,
            "sell_reasons": sell_reasons,
            "monthly": monthly,
            "daily_detail": daily_detail,
            "positions": positions,
            "date_range": f"{start_date or '全部'} ~ {end_date or '全部'}",
        }}
    except Exception as e:
        import traceback
        return {"success": False, "message": str(e), "traceback": traceback.format_exc()}

def _empty_result():
    return {
        "kpi": {"total_trades": 0, "total_profit": 0, "win_rate": 0, "profit_loss_ratio": 0, "max_drawdown": 0, "avg_profit_pct": 0, "avg_win_pct": 0, "avg_loss_pct": 0},
        "strategy_contrib": [], "sell_reasons": [], "monthly": [], "daily_detail": [], "positions": [],
        "date_range": "",
    }
