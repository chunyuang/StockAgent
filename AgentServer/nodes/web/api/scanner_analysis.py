"""scanner_analysis.py — 结果分析API
从MongoDB聚合多日交易数据，计算KPI、策略贡献、卖出原因、月度收益等
"""
from fastapi import APIRouter
from typing import Optional

router = APIRouter(prefix="/scanner", tags=["analysis"])

def _norm_strat(s):
    """统一策略名"""
    mapping = {"halfway_chase": "半路追涨", "first_limit": "首板打板", "dragon_head": "龙头回调", "limit_bounce": "跌停翘板"}
    return mapping.get(s, s or "未知")

@router.get("/analysis")
async def get_analysis(start_date: str = None, end_date: str = None):
    """市场监听结果分析 — 综合KPI + 策略贡献 + 卖出原因 + 月度收益 + 持仓分析"""
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": False, "message": "MongoDB未初始化"}
        
        db = mongo_manager.db
        
        # 1. 从broker_orders获取所有成交订单
        match = {"status": "filled", "filled_qty": {"$gt": 0}}
        if start_date:
            sd = int(start_date.replace("-", "")) if start_date.isdigit() or "-" in start_date else start_date
            match["trade_date"] = match.get("trade_date", {})
            if isinstance(match["trade_date"], dict):
                match["trade_date"]["$gte"] = sd if isinstance(sd, int) else sd
        if end_date:
            ed = int(end_date.replace("-", "")) if end_date.isdigit() or "-" in end_date else end_date
            if "trade_date" not in match:
                match["trade_date"] = {}
            match["trade_date"]["$lte"] = ed if isinstance(ed, int) else ed
        
        orders = await db["broker_orders"].find(match).sort("create_time", 1).to_list(5000)
        
        # 2. 从scanner_timeline获取所有卖出记录(含profit)
        tl_match = {"action": "sell"}
        if start_date:
            sd = start_date.replace("-", "")
            tl_match["trade_date"] = tl_match.get("trade_date", {})
            tl_match["trade_date"]["$gte"] = {"$in": [sd, int(sd)]} if sd.isdigit() else sd
        if end_date:
            ed = end_date.replace("-", "")
            if "trade_date" not in tl_match:
                tl_match["trade_date"] = {}
            tl_match["trade_date"]["$lte"] = {"$in": [ed, int(ed)]} if ed.isdigit() else ed
        
        sells = await db["scanner_timeline"].find(tl_match).sort("time", 1).to_list(5000)
        
        # 3. 计算KPI
        total_trades = len(sells)
        if total_trades == 0:
            return {"success": True, "data": {"kpi": _empty_kpi(), "strategy_contrib": [], "sell_reasons": [], "monthly": [], "positions": []}}
        
        profits = [s.get("profit_pct", 0) or 0 for s in sells]
        profit_amounts = [s.get("profit_amount", 0) or 0 for s in sells]
        wins = [p for p in profits if p >= 0]
        losses = [p for p in profits if p < 0]
        
        total_profit = sum(profit_amounts)
        win_rate = len(wins) / total_trades * 100 if total_trades > 0 else 0
        avg_profit = sum(wins) / len(wins) if wins else 0
        avg_loss = sum(losses) / len(losses) if losses else 0
        profit_loss_ratio = abs(avg_profit / avg_loss) if avg_loss != 0 else float('inf')
        
        # 最大回撤(累计收益序列)
        cum = 0
        peak = 0
        max_dd = 0
        for amt in profit_amounts:
            cum += amt
            if cum > peak:
                peak = cum
            if peak > 0:
                dd = (peak - cum) / peak * 100
                if dd > max_dd:
                    max_dd = dd
        
        # 4. 策略贡献
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
                "win_rate": d["wins"] / d["trades"] * 100 if d["trades"] else 0,
                "profit": round(d["profit"], 0),
                "avg_profit_pct": round(d["profit_pct_sum"] / d["trades"], 2) if d["trades"] else 0,
            })
        
        # 5. 卖出原因统计
        reason_data = {}
        for s in sells:
            reason = s.get("reason", "其他") or "其他"
            # 标准化
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
        
        # 6. 月度收益
        monthly_data = {}
        for s in sells:
            td = str(s.get("trade_date", ""))
            if len(td) >= 6:
                month_key = td[:6]  # YYYYMM
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
        
        # 7. 当前持仓分析
        positions = []
        try:
            scanner = await _get_scanner()
            if scanner._broker:
                name_map = getattr(scanner, '_stock_name_map', {})
                for p in scanner._broker.get_positions():
                    positions.append({
                        "ts_code": p.ts_code,
                        "stock_name": p.stock_name or name_map.get(p.ts_code, ""),
                        "strategy": _norm_strat(p.strategy),
                        "shares": p.total_qty,
                        "cost_price": p.avg_cost,
                        "current_price": p.current_price,
                        "profit_pct": round(p.profit_pct, 2),
                        "profit_amount": round((p.current_price - p.avg_cost) * p.total_qty, 0),
                        "market_value": round(p.current_price * p.total_qty, 0),
                    })
        except Exception:
            pass
        
        kpi = {
            "total_trades": total_trades,
            "total_profit": round(total_profit, 0),
            "win_rate": round(win_rate, 1),
            "profit_loss_ratio": round(min(profit_loss_ratio, 99.99), 2) if profit_loss_ratio != float('inf') else 99.99,
            "max_drawdown": round(max_dd, 2),
            "avg_profit_pct": round(sum(profits) / len(profits), 2) if profits else 0,
            "avg_win_pct": round(avg_profit, 2),
            "avg_loss_pct": round(avg_loss, 2),
        }
        
        return {"success": True, "data": {
            "kpi": kpi,
            "strategy_contrib": strategy_contrib,
            "sell_reasons": sell_reasons,
            "monthly": monthly,
            "positions": positions,
        }}
    except Exception as e:
        return {"success": False, "message": str(e)}

def _empty_kpi():
    return {
        "total_trades": 0, "total_profit": 0, "win_rate": 0,
        "profit_loss_ratio": 0, "max_drawdown": 0, "avg_profit_pct": 0,
        "avg_win_pct": 0, "avg_loss_pct": 0,
    }

async def _get_scanner():
    from nodes.web.api.scanner_shared import _scanner_instance
    return _scanner_instance
