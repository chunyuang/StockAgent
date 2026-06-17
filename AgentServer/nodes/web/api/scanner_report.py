#!/usr/bin/env python3
"""Scanner API - 日报/周报/历史复盘"""
import asyncio
import logging
import math
from nodes.web.api.unified import query_trades, query_latest_trade
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from nodes.web.api.utils import sanitize_nan as _sanitize

# 【v2.9.88】统一日期规范化函数
from nodes.web.api.scanner_review import _normalize_date

# 从scanner共享模块导入
from nodes.web.api.scanner_shared import (
    _get_scanner, _get_scanner_instance, _clean_mongo,
    _fill_stock_names, _safe_read_shared, logger,
    ScannerStartRequest, ManualTradeRequest, PartialSellRequest,
    StopScannerRequest, ScanOnceRequest, PauseRequest,
    prod_scan_query, normalize_data_mode, is_debug_scan_doc,
)

# 策略ID归一化(anomaly_surge→halfway_chase等)
try:
    from nodes.backtest_engine.strategy_defaults import normalize_strategy_id as _norm_strat
except ImportError:
    def _norm_strat(s): return s

router = APIRouter(prefix="/scanner", tags=["日报/周报/历史复盘"])


@router.get("/daily-report")
async def get_daily_report(date: str = None, mode: str = "production", include_debug: bool = False):
    """每日复盘报告 — scanner运行时取实时数据,否则从MongoDB聚合
    
    Args:
        date: 指定日期(YYYYMMDD或YYYY-MM-DD), 不传=今天
    """
    scanner = await _get_scanner()
    # 检查scanner是否真正在运行(有真实持仓或今天的timeline记录)
    # 【v2.9.94修复】增加账户有效性检查: scanner重启后timeline可能非空但broker状态无效(total_assets=0)
    has_live = False
    try:
        if scanner._broker is not None:
            positions = scanner._broker.get_positions()
            acct = scanner._broker.get_account()
            # 有效条件: 有持仓 OR (有timeline AND 账户状态有效)
            has_live = len(positions) > 0 or (
                hasattr(scanner, '_timeline') and len(scanner._timeline) > 0
                and acct.total_assets > 0  # 账户必须有效(重启后timeline加载了但broker未恢复)
            )
    except Exception:
        pass
    
    if not has_live:
        # Scanner未运行: 从MongoDB聚合今日数据
        return await _daily_report_from_mongo()
    
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
            key = _norm_strat(pos.strategy or "unknown")
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
                if item.get("action") != "sell" or _norm_strat(item.get("strategy", "")) != key:
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
        # 【v2.9.97h】统一查询: 使用 query_trades
        today_trades = {"buy": 0, "sell": 0, "total_amount": 0}
        try:
            from core.managers import mongo_manager
            if mongo_manager.is_initialized:
                today_int = int(datetime.now().strftime("%Y%m%d"))
                docs = await query_trades(mongo_manager.db, date=today_int)
                for doc in docs:
                    side = doc.get("side", "")
                    today_trades[side] = today_trades.get(side, 0) + 1
                    today_trades["total_amount"] += doc.get("filled_price", 0) * doc.get("filled_qty", 0)
        except Exception:
            pass
        
        # 情绪环境(funnel+sentiment for daily report)
        funnel_summary = None
        sentiment_snapshot = None
        try:
            if await scanner._broker._ensure_mongo():
                db2 = scanner._broker._mongo_db
                # funnel
                from collections import defaultdict as _dd2
                funnel_agg = _dd2(lambda: {"total_input": 0, "total_rejected": 0})
                async for doc in db2["scan_traces"].find({"trade_date": today_int}, {"summary": 1}):
                    for layer_name, layer_data in (doc.get("summary") or {}).items():
                        if isinstance(layer_data, dict) and layer_data.get("rejected", 0) > 0:
                            funnel_agg[layer_name]["total_input"] += layer_data.get("total", 0)
                            funnel_agg[layer_name]["total_rejected"] += layer_data.get("rejected", 0)
                funnel_summary = {k: dict(v) for k, v in funnel_agg.items()} or None
                # sentiment
                sent_doc = await db2["sentiment_scores"].find_one({"trade_date": today_int})
                if sent_doc:
                    sentiment_snapshot = f"{sent_doc.get('period', '')} {sent_doc.get('score', 0)}分"
        except Exception:
            pass

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
            # scanner_stats: 添加前端兼容字段(scan_count/total_signals/buy_count/sell_count)
            "scanner_stats": {**stats, "scan_count": stats.get("scans", 0), "total_signals": stats.get("signals_found", 0), "buy_count": today_trades.get("buy", 0), "sell_count": today_trades.get("sell", 0)},
            "funnel_summary": funnel_summary,
            "sentiment_snapshot": sentiment_snapshot,
        }
        
        return {"success": True, "data": report}
    except Exception as e:
        return {"success": True, "data": {}, "message": str(e)}



@router.get("/historical-review")
async def get_historical_review(date: str = None, mode: str = "production", include_debug: bool = False):
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
        
        # 【v2.9.88修复】统一所有集合trade_date为int，用_normalize_date处理
        date_int = _normalize_date(date)
        if date_int is None:
            return {"success": True, "data": None, "message": "日期格式无效"}
        
        # 查询当日所有成交订单
        buys, sells = [], []
        async for doc in db["broker_orders"].find({
            "trade_date": date_int, "status": "filled"
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
            st = _norm_strat(s.get("strategy", "unknown"))
            reason = s.get("reason", "")
            fp = s.get("filled_price", 0) or 0
            fq = s.get("filled_qty", 0) or 0
            strategy_stats[st]["sell_count"] += 1
            # 优先使用已存的profit_pct字段, fallback到reason正则提取
            profit_pct = s.get("profit_pct", 0) or 0
            if profit_pct == 0:
                pct_match = re.search(r'曾盈([\d.]+)%', reason) or re.search(r'(-?[\d.]+)%', reason)
                profit_pct = float(pct_match.group(1)) if pct_match else 0
            if "止损" in reason and "追踪" not in reason:
                if profit_pct > 0:
                    profit_pct = -abs(profit_pct)  # 止损应为负值
                strategy_stats[st]["stop_loss"] += 1
            elif "追踪止损" in reason or "止盈" in reason or "冲高" in reason:
                strategy_stats[st]["take_profit"] += 1
            (strategy_stats[st]["wins"] if profit_pct >= 0 else strategy_stats[st]["losses"]).append(profit_pct)
            strategy_stats[st]["total_pnl"] += fp * fq * profit_pct / 100
        for b in buys:
            strategy_stats[_norm_strat(b.get("strategy", "unknown"))]["buy_count"] += 1
        
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
        # 【v2.9.88修复】scan_traces.trade_date已迁移为int，统一用date_int
        # 【v2.9.89优化】scan_traces含2.7MB大文档,避免全量扫描超时:
        # 1. 优先从scan_date_cache读取count(写入时同步维护)
        # 2. funnel/total_passed从最新50条采样
        # 3. 情绪快照仅取1条
        scan_count = 0
        debug_count = 0
        cache_entry = await db["scan_date_cache"].find_one({"date": date_int})
        if cache_entry:
            total_count = cache_entry.get("count", 0)
            is_debug_day = cache_entry.get("is_debug", False)
            # debug_count从cache估算: is_debug=True的日期是debug日, 非debug日debug_count=0
            # 更精确的做法: 维护debug_count字段, 但is_debug日期少且不影响核心逻辑
            debug_count = 1 if is_debug_day else 0
            scan_count = total_count - debug_count
        else:
            # 回退到count_documents(较慢,仅首次)
            scan_count = await db["scan_traces"].count_documents({"trade_date": date_int, **prod_scan_query(mode, include_debug)})
            debug_count = await db["scan_traces"].count_documents({"trade_date": date_int, "is_debug": True})
        total_passed = 0
        funnel_agg = defaultdict(lambda: {"total_input": 0, "total_rejected": 0})
        # 【v2.9.89】采样最近50条计算funnel(避免2413条×2.7MB全扫描)
        # 注意: 不用sort, 因为sort+limit在大集合上会全扫。自然顺序已按插入时间
        sample_size = min(scan_count + debug_count, 50)
        if sample_size > 0:
            async for doc in db["scan_traces"].find(
                {"trade_date": date_int, **prod_scan_query(mode, include_debug)},
                {"summary": 1, "scan_time": 1, "is_debug": 1}
            ).limit(sample_size):
                if normalize_data_mode(mode, include_debug) != "debug" and is_debug_scan_doc(doc):
                    continue
                total_passed += (doc.get("summary") or {}).get("passed", 0)
                for layer_name, layer_data in (doc.get("summary") or {}).items():
                    if isinstance(layer_data, dict) and layer_data.get("rejected", 0) > 0:
                        funnel_agg[layer_name]["total_input"] += layer_data.get("total", 0)
                        funnel_agg[layer_name]["total_rejected"] += layer_data.get("rejected", 0)
            # 按采样比例放大total_passed
            if scan_count > sample_size:
                total_passed = int(total_passed * scan_count / sample_size)
        # 取最新一条layer_details.L3作为情绪快照
        sentiment_snap = None
        # 1. 优先从scan_traces读取L3情绪层
        # 【v2.9.89修复】scan_traces.trade_date是int，必须用date_int而非date字符串
        latest_with_l3 = await db["scan_traces"].find_one(
            {"trade_date": date_int, "layer_details.L3_sentiment": {"$exists": True, "$ne": ""}, **prod_scan_query(mode, include_debug)},
            sort=[("_id", -1)],
            projection={"layer_details.L3_sentiment": 1}
        )
        if latest_with_l3:
            sentiment_snap = (latest_with_l3.get("layer_details") or {}).get("L3_sentiment")
        # 2. fallback到sentiment_scores
        if not sentiment_snap:
            ss_doc = await db["sentiment_scores"].find_one({"trade_date": date_int})
            if ss_doc:
                score = ss_doc.get("score", 0)
                period = ss_doc.get("period", "")
                pos = ss_doc.get("position_ratio", 0)
                sentiment_snap = f"{period} {score}分 仓位{int(pos*100)}%"
        
        return {"success": True, "data": {
            "date": date,
            "buys": [{"ts_code": b.get("ts_code"), "stock_name": b.get("stock_name", ""), "strategy": b.get("strategy", ""), "price": b.get("filled_price", 0), "qty": b.get("filled_qty", 0), "time": b.get("fill_time", "")} for b in buys],
            "sells": [{"ts_code": s.get("ts_code"), "stock_name": s.get("stock_name", ""), "strategy": s.get("strategy", ""), "price": s.get("filled_price", 0), "qty": s.get("filled_qty", 0), "reason": s.get("reason", ""), "time": s.get("fill_time", ""), "profit_pct": s.get("profit_pct", 0), "profit_amount": s.get("profit_amount", 0)} for s in sells],
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
    
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": {}}
        
        account_id = scanner._broker.account.account_id if scanner and scanner._broker else "default"
        
        # 确定日期范围: 指定日期往前7天
        if date:
            end_date = date
            start_dt = datetime(int(date[:4]), int(date[4:6]), int(date[6:8])) - timedelta(days=7)
            start_date = start_dt.strftime("%Y%m%d")
        else:
            start_date = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
            end_date = datetime.now().strftime("%Y%m%d")
        
        # 【v2.9.86修复】broker_orders.trade_date是int，范围查询必须用int
        start_date_int = int(start_date)
        end_date_int = int(end_date)
        
        daily_stats = {}
        async for doc in mongo_manager.db["broker_orders"].find({
            "account_id": account_id,
            # 【v2.9.97f】兼容 trade_date int/string 格式
            "$or": [
                {"trade_date": {"$gte": start_date_int, "$lte": end_date_int}},
                {"trade_date": {"$gte": str(start_date_int), "$lte": str(end_date_int)}},
            ],
            "status": "filled",
        }).sort("trade_date", 1):
            td = doc.get("trade_date", "")
            if td not in daily_stats:
                daily_stats[td] = {"buys": 0, "sells": 0, "buy_amount": 0, "sell_amount": 0, "strategies": {}}
            
            side = doc.get("side", "")
            amount = doc.get("filled_price", 0) * doc.get("filled_qty", 0)
            strategy = _norm_strat(doc.get("strategy", "unknown"))
            
            if side == "buy":
                daily_stats[td]["buys"] += 1
                daily_stats[td]["buy_amount"] += amount
            else:
                daily_stats[td]["sells"] += 1
                daily_stats[td]["sell_amount"] += amount
            
            if strategy not in daily_stats[td]["strategies"]:
                daily_stats[td]["strategies"][strategy] = {"trades": 0, "sell_count": 0, "amount": 0, "wins": 0, "pnl": 0}
            daily_stats[td]["strategies"][strategy]["trades"] += 1
            daily_stats[td]["strategies"][strategy]["amount"] += amount
            if side == "sell":
                daily_stats[td]["strategies"][strategy]["sell_count"] += 1
                pct = doc.get("profit_pct", 0) or 0
                if pct >= 0:
                    daily_stats[td]["strategies"][strategy]["wins"] += 1
                daily_stats[td]["strategies"][strategy]["pnl"] += pct
        
        # 获取账户快照(如果有)
        account_snapshots = {}
        async for doc in mongo_manager.db["broker_accounts"].find(
            {"account_id": account_id}
        ):
            account_snapshots[doc.get("updated_at", "")] = doc
        
        # 当前账户状态(scanner未运行时用0填充)
        acct = None
        if scanner and scanner._broker:
            try:
                acct = scanner._broker.get_account()
            except Exception:
                pass
        
        # 策略汇总(含胜率和盈亏)
        strategy_summary = {}
        for td, stats in daily_stats.items():
            for strat, sdata in stats.get("strategies", {}).items():
                if strat not in strategy_summary:
                    strategy_summary[strat] = {"trades": 0, "sell_count": 0, "amount": 0, "wins": 0, "pnl": 0}
                strategy_summary[strat]["trades"] += sdata["trades"]
                strategy_summary[strat]["sell_count"] += sdata.get("sell_count", 0)
                strategy_summary[strat]["amount"] += sdata["amount"]
        # 从卖出订单补充胜率/盈亏
        # 【v2.9.86修复】broker_orders.trade_date是int，范围查询必须用int
        async for doc in mongo_manager.db["broker_orders"].find({
            "account_id": account_id,
            "$or": [
                {"trade_date": {"$gte": start_date_int, "$lte": end_date_int}},
                {"trade_date": {"$gte": str(start_date_int), "$lte": str(end_date_int)}},
            ],
            "status": "filled",
            "side": "sell",
        }):
            strat = _norm_strat(doc.get("strategy", "unknown"))
            if strat not in strategy_summary:
                strategy_summary[strat] = {"trades": 0, "amount": 0, "wins": 0, "pnl": 0}
            pct = doc.get("profit_pct", 0) or 0
            if pct >= 0:
                strategy_summary[strat]["wins"] += 1
            strategy_summary[strat]["pnl"] += pct
        # 计算胜率(用sell_count微分母,不是trades)
        for strat in strategy_summary:
            t = strategy_summary[strat].get("sell_count", 0) or strategy_summary[strat].get("trades", 0)
            w = strategy_summary[strat].get("wins", 0)
            strategy_summary[strat]["win_rate"] = round(w / max(t, 1) * 100, 1)
        
        # 总交易统计
        total_buys = sum(d["buys"] for d in daily_stats.values())
        total_sells = sum(d["sells"] for d in daily_stats.values())
        total_buy_amount = sum(d["buy_amount"] for d in daily_stats.values())
        total_sell_amount = sum(d["sell_amount"] for d in daily_stats.values())
        
        report = {
            "period": f"{start_date} ~ {datetime.now().strftime('%Y%m%d')}",
            "account": {
                "total_assets": round(acct.total_assets, 2) if acct else 0,
                "total_profit": round(acct.total_profit, 2) if acct else 0,
                "available_cash": round(acct.available_cash, 2) if acct else 0,
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
            "scanner_stats": scanner._stats if scanner else {},
        }
        
        return {"success": True, "data": report}
    except Exception as e:
        return {"success": True, "data": {}, "message": str(e)}




async def _daily_report_from_mongo():
    """Scanner未运行时从MongoDB聚合今日复盘数据"""
    from core.managers import mongo_manager
    from collections import defaultdict
    
    if not mongo_manager.is_initialized:
        return {"success": True, "data": {}}
    
    db = mongo_manager.db
    today = datetime.now().strftime("%Y%m%d")
    
    # 【v2.9.88修复】scan_traces.trade_date已迁移为int，统一用today_int
    today_int = int(today)

    # 1. 今日订单 【v2.9.97h】使用 query_trades
    buys, sells = [], []
    docs = await query_trades(db, date=today_int, sort=[("fill_time", 1)])
    for doc in docs:
        (buys if doc.get("side") == "buy" else sells).append(doc)
    
    if not buys and not sells:
        return {"success": True, "data": {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "account": {"total_assets": 0, "available_cash": 0, "market_value": 0, "today_profit": 0, "total_profit": 0, "position_ratio": 0},
            "positions": {"count": 0, "strategy_summary": {}, "top_profit": [], "top_loss": []},
            "trades": {"buy": 0, "sell": 0, "total_amount": 0},
            "scanner_stats": {}, "funnel_summary": None, "sentiment_snapshot": None,
        }}
    
    # 2. 按策略汇总
    strategy_summary = defaultdict(lambda: {"count": 0, "market_value": 0, "total_profit": 0, "win_count": 0, "loss_count": 0, "closed_count": 0, "closed_profit": 0, "stop_loss_count": 0, "take_profit_count": 0, "wins_pcts": [], "losses_pcts": []})
    
    for s in sells:
        key = _norm_strat(s.get("strategy", "") or "unknown")
        strategy_summary[key]["closed_count"] += 1
        pnl = s.get("profit_pct", 0) or 0
        strategy_summary[key]["closed_profit"] += s.get("profit_amount", 0) or 0
        reason = s.get("reason", "")
        if pnl >= 0:
            strategy_summary[key]["win_count"] += 1
            strategy_summary[key]["wins_pcts"].append(pnl)
        else:
            strategy_summary[key]["loss_count"] += 1
            strategy_summary[key]["losses_pcts"].append(pnl)
        if "止损" in reason and "追踪" not in reason:
            strategy_summary[key]["stop_loss_count"] += 1
        elif "止盈" in reason or "追踪止损" in reason:
            strategy_summary[key]["take_profit_count"] += 1
    
    # 清理+计算派生指标
    for key in strategy_summary:
        v = strategy_summary[key]
        total = v["win_count"] + v["loss_count"]
        v["win_rate"] = round(v["win_count"] / max(total, 1) * 100, 1)
        v["closed_win_rate"] = round(v["win_count"] / max(v["closed_count"], 1) * 100, 1)
        v["avg_win_pct"] = round(sum(v["wins_pcts"]) / len(v["wins_pcts"]), 1) if v["wins_pcts"] else 0
        v["avg_loss_pct"] = round(sum(v["losses_pcts"]) / len(v["losses_pcts"]), 1) if v["losses_pcts"] else 0
        v["profit_loss_ratio"] = round(abs(v["avg_win_pct"] / v["avg_loss_pct"]), 1) if v["avg_loss_pct"] and v["avg_win_pct"] else 0
        v["max_win_pct"] = round(max(v["wins_pcts"]), 1) if v["wins_pcts"] else 0
        v["max_loss_pct"] = round(min(v["losses_pcts"]), 1) if v["losses_pcts"] else 0
        # Remove temp lists
        del v["wins_pcts"]
        del v["losses_pcts"]
    
    # 3. 扫描统计(从scan_traces)
    scan_stats = {}
    scan_query = {"trade_date": today_int, **prod_scan_query(mode, include_debug)}
    data_mode = normalize_data_mode(mode, include_debug)
    async for doc in db["scan_traces"].find(scan_query):
        if data_mode != "debug" and is_debug_scan_doc(doc):
            continue
        cands = doc.get("candidates", [])
        scan_stats["scans"] = scan_stats.get("scans", 0) + 1
        scan_stats["signals_found"] = scan_stats.get("signals_found", 0) + len([c for c in cands if c.get("final_status") == "passed"])
    scan_stats["scan_count"] = scan_stats.get("scans", 0)
    scan_stats["total_signals"] = scan_stats.get("signals_found", 0)
    scan_stats["buy_count"] = len(buys)
    scan_stats["sell_count"] = len(sells)
    scan_stats["trades_executed"] = len(buys)
    scan_stats["stop_losses"] = sum(1 for s in sells if "止损" in (s.get("reason", "")) and "追踪" not in (s.get("reason", "")))
    scan_stats["take_profits"] = sum(1 for s in sells if "止盈" in (s.get("reason", "")) or "追踪止损" in (s.get("reason", "")))
    
    # 4. 情绪快照(优先从scan_traces L3读取, fallback到sentiment_scores)
    sentiment_snap = None
    latest_with_l3 = await db["scan_traces"].find_one(
        {"trade_date": today_int, "layer_details.L3_sentiment": {"$exists": True, "$ne": ""}, **prod_scan_query(mode, include_debug)},
        sort=[("_id", -1)],
        projection={"layer_details.L3_sentiment": 1}
    )
    if latest_with_l3:
        sentiment_snap = (latest_with_l3.get("layer_details") or {}).get("L3_sentiment")
    if not sentiment_snap:
        sent_doc = await db["sentiment_scores"].find_one({"trade_date": today_int})
        if sent_doc:
            sentiment_snap = f"{sent_doc.get('period', '')} {sent_doc.get('score', 0)}分"
    
    # 4b. 漏斗聚合(从scan_traces)
    funnel_agg = defaultdict(lambda: {"total_input": 0, "total_rejected": 0})
    async for doc in db["scan_traces"].find(scan_query, {"summary": 1, "scan_time": 1, "is_debug": 1}):
        if data_mode != "debug" and is_debug_scan_doc(doc):
            continue
        for layer_name, layer_data in (doc.get("summary") or {}).items():
            if isinstance(layer_data, dict) and layer_data.get("rejected", 0) > 0:
                funnel_agg[layer_name]["total_input"] += layer_data.get("total", 0)
                funnel_agg[layer_name]["total_rejected"] += layer_data.get("rejected", 0)
    funnel_summary = {k: dict(v) for k, v in funnel_agg.items()} or None
    
    # 5. 账户概算(从broker_accounts读取，不再返回全0)
    # 【v2.9.94修复】之前返回全0导致前端显示异常，现在从broker_accounts集合读取
    account_info = {"total_assets": 0, "available_cash": 0, "market_value": 0,
                     "today_profit": 0, "total_profit": 0, "position_ratio": 0}
    try:
        acct_doc = await db["broker_accounts"].find_one({"account_id": "default"})
        if acct_doc:
            account_info = {
                "total_assets": round(acct_doc.get("total_assets", 0) or 0, 2),
                "available_cash": round(acct_doc.get("available_cash", 0) or 0, 2),
                "market_value": round(acct_doc.get("market_value", 0) or 0, 2),
                "today_profit": round(sum(s.get("profit_amount", 0) or 0 for s in sells), 2),
                "total_profit": round(acct_doc.get("total_profit", 0) or 0, 2),
                "position_ratio": round((acct_doc.get("market_value", 0) or 0) / max(acct_doc.get("total_assets", 1), 1) * 100, 1),
            }
    except Exception:
        account_info["today_profit"] = round(sum(s.get("profit_amount", 0) or 0 for s in sells), 2)
    
    # 计算成交金额
    total_sell_amount = sum((s.get("filled_price", 0) or 0) * (s.get("filled_qty", 0) or 0) for s in sells)
    total_buy_amount = sum((b.get("filled_price", 0) or 0) * (b.get("filled_qty", 0) or 0) for b in buys)
    
    report = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "account": account_info,
        "positions": {
            "count": 0,  # 需要scanner运行时才精确
            "strategy_summary": dict(strategy_summary),
            "top_profit": [],
            "top_loss": [],
        },
        "trades": {
            "buy": len(buys),
            "sell": len(sells),
            "total_amount": round(total_buy_amount + total_sell_amount, 2),
        },
        "scanner_stats": scan_stats,
        "funnel_summary": funnel_summary,
        "sentiment_snapshot": sentiment_snap,
    }
    
    return {"success": True, "data": _clean_mongo(report)}
