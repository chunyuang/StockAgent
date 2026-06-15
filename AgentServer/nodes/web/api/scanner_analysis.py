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
        
        sells = await db["scanner_timeline"].find(tl_match).sort([("trade_date", 1), ("time", 1)]).to_list(5000)
        
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
        # FIX4: 盈亏比用profit_amount均值比(和回测一致)
        win_amounts = [a for a, p in zip(profit_amounts, profits) if p >= 0]
        loss_amounts = [a for a, p in zip(profit_amounts, profits) if p < 0]
        avg_win_amt = sum(win_amounts) / len(win_amounts) if win_amounts else 0
        avg_loss_amt = sum(loss_amounts) / len(loss_amounts) if loss_amounts else 0
        profit_loss_ratio = abs(avg_win_amt / avg_loss_amt) if avg_loss_amt != 0 else 99.99
        
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
            "win_count": len(wins),  # FIX6: 直接返回盈亏笔数
            "loss_count": len(losses),
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
            if "跳空止损" in reason or "gap_stop" in reason.lower():
                reason = "跳空止损"
            elif "追踪止损" in reason or "trailing_stop" in reason.lower():
                reason = "追踪止损"
            elif "止损" in reason or "stop" in reason.lower():
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
        
        # 7. 当前持仓【v2.9.93修复】改以broker_positions为唯一真相源，不再从scanner_timeline累加推算
        # P0事故：2026-06-15 scanner_timeline被污染(旧load_timeline回退到历史日重写today)后，虚合出13只幽灵持仓。
        # broker_positions / broker_orders 是唯一真实成交源，优先读这个。
        positions = []
        try:
            from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK, STRATEGY_CONFIGS
        except Exception:
            GLOBAL_RISK, STRATEGY_CONFIGS = {}, {}
        try:
            account_id_default = "default"
            # 从 broker_positions 读真实持仓
            pos_cursor = mongo_manager.db["broker_positions"].find(
                {"account_id": account_id_default}
            )
            async for p in pos_cursor:
                qty = p.get("total_qty") or p.get("quantity") or 0
                if qty <= 0:
                    continue
                tc = p.get("ts_code", "")
                avg_cost = float(p.get("avg_cost") or p.get("cost_price") or 0)
                stock_name = p.get("stock_name", "")
                strategy = p.get("strategy", "")

                # 取最新收盘价作为当前价
                cur_price = float(p.get("current_price") or 0) or avg_cost
                try:
                    latest = await mongo_manager.db["stock_daily_ak_full"].find_one(
                        {"ts_code": tc}, {"close": 1}, sort=[("trade_date", -1)]
                    )
                    if latest and latest.get("close"):
                        cur_price = float(latest["close"])
                except Exception:
                    pass

                profit_pct = (cur_price - avg_cost) / avg_cost * 100 if avg_cost > 0 else 0

                # 止损价/止盈价
                strat_en = strategy
                for k_, v_ in STRATEGY_CONFIGS.items():
                    if v_.get("display_name") == strategy or k_ == strategy:
                        strat_en = k_
                        break
                strat_cfg = STRATEGY_CONFIGS.get(strat_en, {})
                sl_pct = strat_cfg.get("stop_loss_pct", GLOBAL_RISK.get("stop_loss_pct", 0.03))
                stop_loss_price = round(avg_cost * (1 - sl_pct), 2)
                tp_pct = strat_cfg.get("take_profit_pct", GLOBAL_RISK.get("take_profit_pct", 0.07))
                take_profit_price = round(avg_cost * (1 + tp_pct), 2)

                stop_loss_status = "safe"
                stop_loss_desc = ""
                if cur_price <= stop_loss_price:
                    stop_loss_status = "broken"
                    stop_loss_desc = f"已跌破止损价{stop_loss_price:.2f}(-{sl_pct*100:.0f}%)，当前亏{profit_pct:.1f}%"
                elif cur_price <= stop_loss_price * 1.05:
                    stop_loss_status = "near"
                    stop_loss_desc = f"接近止损价{stop_loss_price:.2f}(-{sl_pct*100:.0f}%)"

                risk_monitor_active = False
                risk_monitor_desc = ""
                try:
                    from nodes.web.api.scanner_shared import _scanner_instance
                    if _scanner_instance and _scanner_instance._is_running:
                        risk_monitor_active = (
                            _scanner_instance._risk_running
                            and _scanner_instance._risk_thread
                            and _scanner_instance._risk_thread.is_alive()
                        )
                        if not risk_monitor_active:
                            risk_monitor_desc = "风控线程未运行，止损不会自动执行"
                    else:
                        risk_monitor_desc = "扫描器未启动，持仓无人监控"
                except Exception:
                    risk_monitor_desc = "无法获取风控状态"

                positions.append({
                    "ts_code": tc,
                    "stock_name": stock_name,
                    "strategy": _norm_strat(strategy),
                    "shares": qty,
                    "cost_price": round(avg_cost, 2),
                    "current_price": round(cur_price, 2),
                    "profit_pct": round(profit_pct, 2),
                    "profit_amount": round((cur_price - avg_cost) * qty, 0),
                    "market_value": round(cur_price * qty, 0),
                    "stop_loss_price": stop_loss_price,
                    "stop_loss_pct": round(sl_pct * 100, 1),
                    "take_profit_price": take_profit_price,
                    "stop_loss_status": stop_loss_status,
                    "stop_loss_desc": stop_loss_desc,
                    "risk_monitor_active": risk_monitor_active,
                    "risk_monitor_desc": risk_monitor_desc,
                })
        except Exception as e:
            import traceback
            try:
                logger.warning(f"[ANALYSIS] 读取broker_positions失败: {e}\n{traceback.format_exc()}")
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
            # 【v2.9.92n】全局风控监控状态
            "risk_monitor": _get_risk_monitor_status(),
            # 【v2.9.92o】账户信息(直接从MongoDB读，不依赖scanner运行)
            "account": await _get_account_from_mongo(),
        }}
    except Exception as e:
        import traceback
        return {"success": False, "message": str(e), "traceback": traceback.format_exc()}

def _get_risk_monitor_status():
    """【v2.9.92n】获取全局风控监控状态"""
    try:
        from nodes.web.api.scanner_shared import _scanner_instance
        if _scanner_instance is None:
            return {"scanner_alive": False, "scan_loop_active": False, "risk_thread_alive": False,
                    "status": "scanner_not_created", "desc": "Scanner实例未创建，持仓无人监控"}
        
        is_running = _scanner_instance._is_running
        risk_alive = _scanner_instance._risk_running and \
                     _scanner_instance._risk_thread and \
                     _scanner_instance._risk_thread.is_alive()
        
        status = "healthy"
        desc = "风控监控正常运行"
        if not is_running and not risk_alive:
            status = "scanner_stopped"
            desc = "扫描器未启动，风控线程未运行，止损不会自动执行"
        elif is_running and not risk_alive:
            status = "risk_thread_dead"
            desc = "风控线程已退出，止损不会自动执行！请重启扫描器"
        elif not is_running and risk_alive:
            status = "scanner_loop_dead"
            desc = "扫描循环已停止，但风控线程仍在运行(部分监控)"
        
        return {
            "scanner_alive": True,
            "scan_loop_active": is_running,
            "risk_thread_alive": risk_alive,
            "status": status,
            "desc": desc,
        }
    except Exception as e:
        return {"scanner_alive": False, "scan_loop_active": False, "risk_thread_alive": False,
                "status": "error", "desc": f"无法获取风控状态: {e}"}


async def _get_account_from_mongo():
    """【v2.9.92o】直接从MongoDB读取账户信息(不依赖scanner运行)"""
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return None
        db = mongo_manager.db
        
        # 从broker_accounts读账户
        acct_doc = await db["broker_accounts"].find_one({"account_id": "default"})
        if not acct_doc:
            return None
        
        # 从broker_positions读持仓列表
        pos_list = []
        total_market_value = 0
        total_cost = 0
        async for doc in db["broker_positions"].find({"account_id": "default"}):
            cost = doc.get("avg_cost", 0)
            qty = doc.get("total_qty", 0)
            cur = doc.get("current_price", cost)
            mkt_val = cur * qty
            total_market_value += mkt_val
            total_cost += cost * qty
            pos_list.append({
                "ts_code": doc.get("ts_code", ""),
                "stock_name": doc.get("stock_name", ""),
                "shares": qty,
                "cost_price": round(cost, 2),
                "current_price": round(cur, 2),
                "profit_pct": round((cur - cost) / cost * 100, 2) if cost > 0 else 0,
                "profit_amount": round((cur - cost) * qty, 0),
                "market_value": round(mkt_val, 0),
                "strategy": doc.get("strategy", ""),
            })
        
        available_cash = acct_doc.get("available_cash", 0)
        total_assets = available_cash + total_market_value
        
        return {
            "account_id": "default",
            "total_assets": round(total_assets, 2),
            "available_cash": round(available_cash, 2),
            "market_value": round(total_market_value, 2),
            "total_cost": round(total_cost, 2),
            "total_profit": round(total_assets - 1000000, 2),  # 初始100万
            "position_count": len(pos_list),
            "position_ratio": round(total_market_value / max(total_assets, 1) * 100, 1),
            "positions": pos_list,
        }
    except Exception:
        return None


def _empty_result():
    return {
        "kpi": {"total_trades": 0, "total_profit": 0, "win_rate": 0, "profit_loss_ratio": 0, "max_drawdown": 0, "avg_profit_pct": 0, "avg_win_pct": 0, "avg_loss_pct": 0},
        "strategy_contrib": [], "sell_reasons": [], "monthly": [], "daily_detail": [], "positions": [],
        "date_range": "",
    }


@router.get("/analysis/stock/{ts_code}")
async def get_stock_detail(ts_code: str):
    """个股交易详情 — 查看某只股票的所有买卖记录、盈亏、持有天数"""
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": False, "message": "MongoDB未初始化"}
        
        db = mongo_manager.db
        
        # 获取该股票所有交易记录
        records = await db["scanner_timeline"].find(
            {"ts_code": ts_code, "action": {"$in": ["buy", "sell"]}}
        ).sort([("trade_date", 1), ("time", 1)]).to_list(100)
        
        if not records:
            return {"success": False, "message": f"无{ts_code}交易记录"}
        
        trades = []
        total_buy_qty = 0
        total_sell_qty = 0
        total_buy_amount = 0
        total_sell_amount = 0
        buy_count = 0
        sell_count = 0
        profit_pcts = []
        profit_amounts = []
        first_buy_date = None
        last_sell_date = None
        
        for r in records:
            action = r.get("action")
            shares = r.get("shares", 0) or 0
            price = r.get("price", 0) or 0
            td = str(r.get("trade_date", ""))
            t = r.get("time", "")
            
            trades.append({
                "date": f"{td[:4]}-{td[4:6]}-{td[6:]}" if len(td) == 8 else td,
                "time": t,
                "action": action,
                "shares": shares,
                "price": price,
                "amount": round(shares * price, 0),
                "profit_pct": r.get("profit_pct"),
                "profit_amount": r.get("profit_amount"),
                "reason": r.get("reason", ""),
                "strategy": _norm_strat(r.get("strategy", "")),
            })
            
            if action == "buy":
                total_buy_qty += shares
                total_buy_amount += shares * price
                buy_count += 1
                if not first_buy_date:
                    first_buy_date = td
            elif action == "sell":
                total_sell_qty += shares
                total_sell_amount += shares * price
                sell_count += 1
                last_sell_date = td
                if r.get("profit_pct") is not None:
                    profit_pcts.append(r["profit_pct"])
                if r.get("profit_amount") is not None:
                    profit_amounts.append(r["profit_amount"])
        
        # 当前持仓(用剩余持仓均价,和持仓表一致)
        holding_qty = total_buy_qty - total_sell_qty
        # FIX3: 用剩余持仓均价而非总买入均价
        qty_remaining = 0; cost_remaining = 0
        for r in records:
            action = r.get("action")
            shares = r.get("shares", 0) or 0
            price = r.get("price", 0) or 0
            if action == "buy":
                qty_remaining += shares
                cost_remaining += shares * price
            elif action == "sell":
                avg_before = cost_remaining / qty_remaining if qty_remaining > 0 else 0
                qty_remaining -= shares
                if qty_remaining > 0:
                    cost_remaining = qty_remaining * avg_before
                else:
                    cost_remaining = 0
        avg_cost = cost_remaining / qty_remaining if qty_remaining > 0 else (total_buy_amount / total_buy_qty if total_buy_qty > 0 else 0)
        
        # 当前价格
        cur_price = avg_cost
        try:
            latest = await db["stock_daily_ak_full"].find_one(
                {"ts_code": ts_code}, {"close": 1}, sort=[("trade_date", -1)]
            )
            if latest and latest.get("close"):
                cur_price = float(latest["close"])
        except Exception:
            pass
        
        # 持仓盈亏
        holding_profit_pct = (cur_price - avg_cost) / avg_cost * 100 if avg_cost > 0 and holding_qty > 0 else None
        holding_profit_amount = (cur_price - avg_cost) * holding_qty if holding_qty > 0 else None
        
        # 已实现盈亏
        realized_profit = sum(profit_amounts) if profit_amounts else 0
        realized_win_rate = len([p for p in profit_pcts if p >= 0]) / len(profit_pcts) * 100 if profit_pcts else 0
        
        # 持有天数
        hold_days = None
        if first_buy_date and (last_sell_date or holding_qty > 0):
            from datetime import datetime
            end = last_sell_date or datetime.now().strftime("%Y%m%d")
            try:
                d1 = datetime.strptime(first_buy_date, "%Y%m%d")
                d2 = datetime.strptime(end, "%Y%m%d")
                hold_days = (d2 - d1).days
            except Exception:
                pass
        
        # 股票名称
        stock_name = records[0].get("stock_name", "") or records[0].get("name", "")
        
        return {"success": True, "data": {
            "ts_code": ts_code,
            "stock_name": stock_name,
            "strategy": _norm_strat(records[0].get("strategy", "")),
            "trades": trades,
            "summary": {
                "buy_count": buy_count,
                "sell_count": sell_count,
                "total_buy_qty": total_buy_qty,
                "total_sell_qty": total_sell_qty,
                "avg_cost": round(avg_cost, 2),
                "holding_qty": holding_qty,
                "current_price": round(cur_price, 2),
                "holding_profit_pct": round(holding_profit_pct, 2) if holding_profit_pct is not None else None,
                "holding_profit_amount": round(holding_profit_amount, 0) if holding_profit_amount is not None else None,
                "realized_profit": round(realized_profit, 0),
                "realized_win_rate": round(realized_win_rate, 1),
                "hold_days": hold_days,
                "market_value": round(cur_price * holding_qty, 0) if holding_qty > 0 else 0,
            }
        }}
    except Exception as e:
        import traceback
        return {"success": False, "message": str(e), "traceback": traceback.format_exc()}
