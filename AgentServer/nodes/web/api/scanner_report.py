#!/usr/bin/env python3
"""Scanner API - 日报/周报/历史复盘"""
import asyncio
import logging
import math
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from nodes.web.api.utils import sanitize_nan as _sanitize

# 从scanner共享模块导入
from nodes.web.api.scanner_shared import (
    _get_scanner, _get_scanner_instance, _clean_mongo,
    _fill_stock_names, _safe_read_shared, logger,
    ScannerStartRequest, ManualTradeRequest, PartialSellRequest,
    StopScannerRequest, ScanOnceRequest, PauseRequest,
)

router = APIRouter(prefix="/scanner", tags=["日报/周报/历史复盘"])


@router.get("/daily-report")
async def get_daily_report():
    """每日复盘报告"""
    scanner = await _get_scanner()
    if not scanner._broker:
        return {"success": True, "data": {}}
    
    try:
        acct = scanner._broker.get_account()
        positions = scanner._broker.get_positions()
        name_map = getattr(scanner, '_stock_name_map', {})
        cb = scanner._circuit_breaker
        stats = scanner._stats
        
        # 按策略汇总(含胜率和收益)
        strategy_summary = {}
        for pos in positions:
            # 确保pos有stock_name
            if not pos.stock_name and name_map:
                pos.stock_name = name_map.get(pos.ts_code, "")
            key = pos.strategy or "unknown"
            if key not in strategy_summary:
                strategy_summary[key] = {"count": 0, "market_value": 0, "total_profit": 0, "win_count": 0, "loss_count": 0}
            strategy_summary[key]["count"] += 1
            strategy_summary[key]["market_value"] += pos.current_price * pos.total_qty
            profit = (pos.current_price - pos.avg_cost) * pos.total_qty
            strategy_summary[key]["total_profit"] += profit
            if profit >= 0:
                strategy_summary[key]["win_count"] += 1
            else:
                strategy_summary[key]["loss_count"] += 1
        
        # 从时间线统计已平仓策略表现
        for item in scanner._timeline:
            if item.get("action") == "sell" and item.get("strategy"):
                key = item["strategy"]
                if key not in strategy_summary:
                    strategy_summary[key] = {"count": 0, "market_value": 0, "total_profit": 0, "win_count": 0, "loss_count": 0, "closed_profit": 0, "closed_count": 0}
                if "closed_count" not in strategy_summary[key]:
                    strategy_summary[key]["closed_count"] = 0
                    strategy_summary[key]["closed_profit"] = 0
                strategy_summary[key]["closed_count"] = strategy_summary[key].get("closed_count", 0) + 1
                strategy_summary[key]["closed_profit"] = strategy_summary[key].get("closed_profit", 0) + item.get("profit_amount", 0)
                if item.get("profit_pct", 0) >= 0:
                    strategy_summary[key]["win_count"] = strategy_summary[key].get("win_count", 0) + 1
                else:
                    strategy_summary[key]["loss_count"] = strategy_summary[key].get("loss_count", 0) + 1
        
        # 计算策略胜率 + 扩展归因指标
        for key in strategy_summary:
            total = strategy_summary[key].get("win_count", 0) + strategy_summary[key].get("loss_count", 0)
            strategy_summary[key]["win_rate"] = round(strategy_summary[key].get("win_count", 0) / max(total, 1) * 100, 1)
            # 以下指标供复盘归因展示
            closed = strategy_summary[key].get("closed_count", 0)
            strategy_summary[key]["closed_win_rate"] = round(strategy_summary[key].get("win_count", 0) / max(closed, 1) * 100, 1) if closed else 0
            # 从timeline按策略提取已平仓的pct列表(用于均盈均亏/盈亏比)
            strategy_pcts = {"wins": [], "losses": []}
            strategy_summary[key]["stop_loss_count"] = 0
            strategy_summary[key]["take_profit_count"] = 0
            for item in scanner._timeline:
                if item.get("action") != "sell" or item.get("strategy") != key:
                    continue
                pct = item.get("profit_pct", 0) or 0
                reason = item.get("reason", "")
                if pct >= 0:
                    strategy_pcts["wins"].append(pct)
                else:
                    strategy_pcts["losses"].append(pct)
                if "止损" in reason and "追踪" not in reason:
                    strategy_summary[key]["stop_loss_count"] += 1
                elif "止盈" in reason or "追踪止损" in reason:
                    strategy_summary[key]["take_profit_count"] += 1
            wins = strategy_pcts["wins"]
            losses = strategy_pcts["losses"]
            strategy_summary[key]["avg_win_pct"] = round(sum(wins) / len(wins), 1) if wins else 0
            strategy_summary[key]["avg_loss_pct"] = round(sum(losses) / len(losses), 1) if losses else 0
            strategy_summary[key]["profit_loss_ratio"] = round(abs(sum(wins)/len(wins) / (sum(losses)/len(losses))), 1) if wins and losses else 0
            strategy_summary[key]["max_win_pct"] = round(max(wins), 1) if wins else 0
            strategy_summary[key]["max_loss_pct"] = round(min(losses), 1) if losses else 0
        
        # 从MongoDB获取今日订单统计
        today_trades = {"buy": 0, "sell": 0, "total_amount": 0}
        if await scanner._broker._ensure_mongo():
            db = scanner._broker._mongo_db
            today = datetime.now().strftime("%Y%m%d")
            async for doc in db["broker_orders"].find({
                "account_id": scanner._broker.account.account_id,
                "trade_date": today,
                "status": "filled"
            }):
                side = doc.get("side", "")
                today_trades[side] = today_trades.get(side, 0) + 1
                today_trades["total_amount"] += doc.get("filled_price", 0) * doc.get("filled_qty", 0)
        
        report = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "account": {
                "total_assets": round(acct.total_assets, 2),
                "available_cash": round(acct.available_cash, 2),
                "market_value": round(acct.market_value, 2),
                "today_profit": round(acct.today_profit, 2),
                "total_profit": round(acct.total_profit, 2),
                "position_ratio": round(acct.market_value / max(acct.total_assets, 1) * 100, 1),
            },
            "positions": {
                "count": len(positions),
                "strategy_summary": strategy_summary,
                "top_profit": sorted(
                    [{"ts_code": p.ts_code, "name": p.stock_name or getattr(scanner, '_stock_name_map', {}).get(p.ts_code, ""), "pct": round(p.profit_pct, 1)} for p in positions],
                    key=lambda x: x["pct"], reverse=True
                )[:5],
                "top_loss": sorted(
                    [{"ts_code": p.ts_code, "name": p.stock_name or getattr(scanner, '_stock_name_map', {}).get(p.ts_code, ""), "pct": round(p.profit_pct, 1)} for p in positions],
                    key=lambda x: x["pct"]
                )[:5],
            },
            "trades": today_trades,
            "win_rate": round(stats.get("take_profits", 0) / max(stats.get("trades_executed", 1), 1) * 100, 1) if stats.get("trades_executed", 0) > 0 else 0,
            "stop_loss_count": stats.get("stop_losses", 0),
            "take_profit_count": stats.get("take_profits", 0),
            "risk": {
                "circuit_breaker": cb.get("trading_paused", False),
                "consecutive_losses": cb.get("consecutive_losses", 0),
                "today_losses": cb.get("today_losses", 0),
            },
            "scanner_stats": stats,
        }
        
        return {"success": True, "data": report}
    except Exception as e:
        return {"success": True, "data": {}, "message": str(e)}



@router.get("/historical-review")
async def get_historical_review(date: str = None):
    """历史复盘 — 从MongoDB聚合历史交易数据,支持任意交易日查看
    
    Args:
        date: YYYYMMDD格式,不传则返回最近有数据的交易日
    """
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": None, "message": "MongoDB未连接"}
        db = mongo_manager.db
        
        # 确定日期
        if not date:
            latest = await db["broker_orders"].find_one(
                {"status": "filled", "side": "sell"},
                sort=[("_id", -1)]
            )
            if not latest:
                return {"success": True, "data": None, "message": "无历史交易数据"}
            date = latest.get("trade_date", "")
        
        # 查询当日所有成交订单
        buys, sells = [], []
        async for doc in db["broker_orders"].find({
            "trade_date": date, "status": "filled"
        }).sort("fill_time", 1):
            (buys if doc.get("side") == "buy" else sells).append(doc)
        
        # 按策略统计
        from collections import defaultdict
        strategy_stats = defaultdict(lambda: {
            "buy_count": 0, "sell_count": 0, "stop_loss": 0, "take_profit": 0,
            "wins": [], "losses": [], "total_pnl": 0
        })
        import re
        for s in sells:
            st = s.get("strategy", "unknown")
            reason = s.get("reason", "")
            fp = s.get("filled_price", 0) or 0
            fq = s.get("filled_qty", 0) or 0
            strategy_stats[st]["sell_count"] += 1
            pct_match = re.search(r'曾盈([\d.]+)%', reason) or re.search(r'-?([\d.]+)%', reason)
            profit_pct = float(pct_match.group(1)) if pct_match else 0
            if "止损" in reason and "追踪" not in reason:
                profit_pct = -abs(profit_pct)
                strategy_stats[st]["stop_loss"] += 1
            elif "追踪止损" in reason or "止盈" in reason or "冲高" in reason:
                strategy_stats[st]["take_profit"] += 1
            (strategy_stats[st]["wins"] if profit_pct >= 0 else strategy_stats[st]["losses"]).append(profit_pct)
            strategy_stats[st]["total_pnl"] += fp * fq * profit_pct / 100
        for b in buys:
            strategy_stats[b.get("strategy", "unknown")]["buy_count"] += 1
        
        strategy_summary = {}
        for k, v in strategy_stats.items():
            w, l = v["wins"], v["losses"]
            t = len(w) + len(l)
            strategy_summary[k] = {
                "count": v["sell_count"],  # 持仓/已平数量
                "buy_count": v["buy_count"], "sell_count": v["sell_count"],
                "closed_count": t,  # 已平仓笔数
                "stop_loss_count": v["stop_loss"], "take_profit_count": v["take_profit"],
                "win_count": len(w), "loss_count": len(l),
                "win_rate": round(len(w) / max(t, 1) * 100, 1),
                "closed_win_rate": round(len(w) / max(t, 1) * 100, 1),
                "total_pnl": round(v["total_pnl"]),
                "closed_profit": round(v["total_pnl"]),
                "avg_win_pct": round(sum(w) / len(w), 1) if w else 0,
                "avg_loss_pct": round(sum(l) / len(l), 1) if l else 0,
                "profit_loss_ratio": round(abs(sum(w)/len(w) / (sum(l)/len(l))), 1) if w and l else 0,
            }
        
        # 扫描统计
        scan_count = await db["scan_traces"].count_documents({"trade_date": date, "is_debug": {"$ne": True}})
        debug_count = await db["scan_traces"].count_documents({"trade_date": date, "is_debug": True})
        total_passed = 0
        funnel_agg = defaultdict(lambda: {"total_input": 0, "total_rejected": 0})
        async for doc in db["scan_traces"].find({"trade_date": date}, {"summary": 1, "layer_details.L3_sentiment": 1}):
            total_passed += (doc.get("summary") or {}).get("passed", 0)
            for layer_name, layer_data in (doc.get("summary") or {}).items():
                if isinstance(layer_data, dict) and layer_data.get("rejected", 0) > 0:
                    funnel_agg[layer_name]["total_input"] += layer_data.get("total", 0)
                    funnel_agg[layer_name]["total_rejected"] += layer_data.get("rejected", 0)
        # 取最新一条layer_details.L3作为情绪快照
        sentiment_snap = None
        # 1. 优先从scan_traces读取L3情绪层
        latest_with_l3 = await db["scan_traces"].find_one(
            {"trade_date": date, "layer_details.L3_sentiment": {"$exists": True, "$ne": ""}},
            sort=[("_id", -1)],
            projection={"layer_details.L3_sentiment": 1}
        )
        if latest_with_l3:
            sentiment_snap = (latest_with_l3.get("layer_details") or {}).get("L3_sentiment")
        # 2. fallback到sentiment_scores
        if not sentiment_snap:
            ss_doc = await db["sentiment_scores"].find_one({"trade_date": int(date)})
            if ss_doc:
                score = ss_doc.get("score", 0)
                period = ss_doc.get("period", "")
                pos = ss_doc.get("position_ratio", 0)
                sentiment_snap = f"{period} {score}分 仓位{int(pos*100)}%"
        
        return {"success": True, "data": {
            "date": date,
            "buys": [{"ts_code": b.get("ts_code"), "stock_name": b.get("stock_name", ""), "strategy": b.get("strategy", ""), "price": b.get("filled_price", 0), "qty": b.get("filled_qty", 0), "time": b.get("fill_time", "")} for b in buys],
            "sells": [{"ts_code": s.get("ts_code"), "stock_name": s.get("stock_name", ""), "strategy": s.get("strategy", ""), "price": s.get("filled_price", 0), "qty": s.get("filled_qty", 0), "reason": s.get("reason", ""), "time": s.get("fill_time", "")} for s in sells],
            "strategy_summary": strategy_summary,
            "scan_stats": {"scan_count": scan_count, "debug_scan_count": debug_count, "total_signals": total_passed, "buy_count": len(buys), "sell_count": len(sells)},
            "funnel_summary": {k: dict(v) for k, v in funnel_agg.items()},
            "sentiment_snapshot": sentiment_snap,
        }}
    except Exception as e:
        return {"success": True, "data": None, "message": str(e)}

@router.get("/weekly-report")
async def get_weekly_report(date: str = None):
    """周报: 指定日期所在周的5个交易日汇总
    
    Args:
        date: YYYYMMDD格式, 不传则当天
    """
    scanner = await _get_scanner()
    if not scanner._broker:
        return {"success": True, "data": {}}
    
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": {}}
        
        account_id = scanner._broker.account.account_id
        
        # 确定日期范围: 指定日期往前7天
        if date:
            end_date = date
            start_dt = datetime(int(date[:4]), int(date[4:6]), int(date[6:8])) - timedelta(days=7)
            start_date = start_dt.strftime("%Y%m%d")
        else:
            start_date = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
            end_date = datetime.now().strftime("%Y%m%d")
        
        daily_stats = {}
        async for doc in mongo_manager.db["broker_orders"].find({
            "account_id": account_id,
            "trade_date": {"$gte": start_date},
            "status": "filled",
        }).sort("trade_date", 1):
            td = doc.get("trade_date", "")
            if td not in daily_stats:
                daily_stats[td] = {"buys": 0, "sells": 0, "buy_amount": 0, "sell_amount": 0, "strategies": {}}
            
            side = doc.get("side", "")
            amount = doc.get("filled_price", 0) * doc.get("filled_qty", 0)
            strategy = doc.get("strategy", "unknown")
            
            if side == "buy":
                daily_stats[td]["buys"] += 1
                daily_stats[td]["buy_amount"] += amount
            else:
                daily_stats[td]["sells"] += 1
                daily_stats[td]["sell_amount"] += amount
            
            if strategy not in daily_stats[td]["strategies"]:
                daily_stats[td]["strategies"][strategy] = {"trades": 0, "amount": 0}
            daily_stats[td]["strategies"][strategy]["trades"] += 1
            daily_stats[td]["strategies"][strategy]["amount"] += amount
        
        # 获取账户快照(如果有)
        account_snapshots = {}
        async for doc in mongo_manager.db["broker_accounts"].find(
            {"account_id": account_id}
        ):
            account_snapshots[doc.get("updated_at", "")] = doc
        
        # 当前账户状态
        acct = scanner._broker.get_account()
        
        # 策略汇总
        strategy_summary = {}
        for td, stats in daily_stats.items():
            for strat, sdata in stats.get("strategies", {}).items():
                if strat not in strategy_summary:
                    strategy_summary[strat] = {"trades": 0, "amount": 0}
                strategy_summary[strat]["trades"] += sdata["trades"]
                strategy_summary[strat]["amount"] += sdata["amount"]
        
        # 总交易统计
        total_buys = sum(d["buys"] for d in daily_stats.values())
        total_sells = sum(d["sells"] for d in daily_stats.values())
        total_buy_amount = sum(d["buy_amount"] for d in daily_stats.values())
        total_sell_amount = sum(d["sell_amount"] for d in daily_stats.values())
        
        report = {
            "period": f"{start_date} ~ {datetime.now().strftime('%Y%m%d')}",
            "account": {
                "total_assets": round(acct.total_assets, 2),
                "total_profit": round(acct.total_profit, 2),
                "available_cash": round(acct.available_cash, 2),
            },
            "daily_stats": daily_stats,
            "strategy_summary": strategy_summary,
            "totals": {
                "trading_days": len(daily_stats),
                "total_buys": total_buys,
                "total_sells": total_sells,
                "total_buy_amount": round(total_buy_amount, 2),
                "total_sell_amount": round(total_sell_amount, 2),
                "net_flow": round(total_sell_amount - total_buy_amount, 2),
            },
            "scanner_stats": scanner._stats,
        }
        
        return {"success": True, "data": report}
    except Exception as e:
        return {"success": True, "data": {}, "message": str(e)}


