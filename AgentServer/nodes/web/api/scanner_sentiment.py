#!/usr/bin/env python3
"""Scanner API - 市场情绪/情绪矩阵"""
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

router = APIRouter(prefix="/scanner", tags=["市场情绪/情绪矩阵"])


def _get_position_ratio_sentiment(period_cn: str, fallback: float = 0.3) -> float:
    """从strategy_defaults读取仓位系数(与emotion_cycle._get_position_ratio统一来源)"""
    try:
        from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK
        # 中文key映射
        cn_to_en = {"高潮": "rising", "分化": "differentiation", "震荡": "chaos", "冰点": "bearish"}
        # 英文key也直接支持(大小写不敏感)
        en_lower = period_cn.lower() if period_cn else ""
        en_map = {"rising": "rising", "differentiation": "differentiation", "chaos": "chaos", "bearish": "bearish"}
        en_key = cn_to_en.get(period_cn, en_map.get(en_lower, "bearish"))
        return GLOBAL_RISK.get("sentiment_position_map", {}).get(en_key, fallback)
    except Exception:
        return fallback


@router.get("/sentiment-timeline")
async def get_sentiment_timeline(date: str = None, mode: str = "daily"):
    """情绪时间线 — 聚合历史情绪数据,返回时间序列
    
    Args:
        date: YYYYMMDD, 用于日线模式限定范围(前后60天), 日内模式指定日期
        mode: intraday(日内) | daily(日线) | weekly(周线) | monthly(月线)
    """
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": {"points": [], "trades": []}}
        db = mongo_manager.db
        import datetime as _dt, re
        if not date:
            date = _dt.datetime.now().strftime("%Y%m%d")
        
        points = []
        trades = []
        
        if mode in ("daily", "weekly", "monthly"):
            from collections import OrderedDict
            daily_map = OrderedDict()
            
            # 日线模式: 以date为中心取前后60天(共120天窗口)
            # 周线/月线: 取全部数据
            query = {}
            if mode == "daily":
                try:
                    center = _dt.datetime.strptime(date, "%Y%m%d")
                    start = (center - _dt.timedelta(days=120)).strftime("%Y%m%d")
                    end = (center + _dt.timedelta(days=30)).strftime("%Y%m%d")
                    query["trade_date"] = {"$gte": int(start), "$lte": int(end)}
                except (ValueError, TypeError):
                    pass
            
            # 读取sentiment_scores(包含missing_data,前端用虚线标注)
            async for doc in db["sentiment_scores"].find(
                query,
                {"trade_date": 1, "score": 1, "period": 1, "position_ratio": 1, 
                 "limit_up": 1, "limit_down": 1, "max_continue": 1, "up_down_ratio": 1, 
                 "zt_premium": 1, "data_source": 1, "missing_data": 1}
            ).sort("trade_date", 1):
                td = str(doc["trade_date"])
                daily_map[td] = {
                    "date": td, "score": doc.get("score", 0), "period": doc.get("period", ""),
                    "position_ratio": _get_position_ratio_sentiment(doc.get("period", ""), doc.get("position_ratio", 0.3)),
                    "limit_up": doc.get("limit_up", 0), "limit_down": doc.get("limit_down", 0),
                    "max_continue": doc.get("max_continue", 0),
                    "up_down_ratio": doc.get("up_down_ratio", 0),
                    "zt_premium": doc.get("zt_premium", 0),
                    "data_source": doc.get("data_source", ""),
                    "missing_data": doc.get("missing_data", False),
                }
            
            points = list(daily_map.values())
            
            # 周/月聚合
            if mode in ("weekly", "monthly") and points:
                from itertools import groupby
                agg_points = []
                def _period_key(p):
                    d = p["date"]
                    if mode == "weekly":
                        import datetime as _dt2
                        dt = _dt2.datetime.strptime(d, "%Y%m%d")
                        return dt.strftime("%Y-W%W")
                    else:
                        return d[:6]
                for key, group in groupby(points, key=_period_key):
                    grp = list(group)
                    valid = [p for p in grp if not p.get("missing_data")]
                    if not valid:
                        valid = grp  # 全是missing也保留
                    avg_score = sum(p["score"] for p in valid) / len(valid)
                    total_lu = sum(p.get("limit_up", 0) for p in grp)
                    total_ld = sum(p.get("limit_down", 0) for p in grp)
                    has_missing = any(p.get("missing_data") for p in grp)
                    # 【v2.9.84修复】阈值从strategy_defaults统一读取,不再硬编码
                    from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK
                    _th = GLOBAL_RISK.get("sentiment_thresholds", {"rising": 70, "differentiation": 55, "chaos": 40})
                    if avg_score >= _th["rising"]: period = "高潮"
                    elif avg_score >= _th["differentiation"]: period = "分化"
                    elif avg_score >= _th["chaos"]: period = "震荡"
                    else: period = "冰点"
                    agg_points.append({
                        "date": key, "score": round(avg_score, 1), "period": period,
                        "position_ratio": _get_position_ratio_sentiment(period, 0.25),
                        "limit_up": total_lu, "limit_down": total_ld,
                        "days": len(grp), "first_date": grp[0]["date"], "last_date": grp[-1]["date"],
                        "missing_data": has_missing,
                    })
                points = agg_points
            
            # trades: 只取时间范围内的sell记录
            trade_query = {"status": "filled", "side": "sell"}
            if mode == "daily" and query.get("trade_date"):
                td_q = query["trade_date"]
                trade_query["trade_date"] = td_q
            async for doc in db["broker_orders"].find(
                trade_query,
                {"trade_date": 1, "side": 1, "ts_code": 1, "strategy": 1, "filled_price": 1, "reason": 1, "profit_pct": 1}
            ).sort("trade_date", 1):
                trades.append({
                    "date": doc.get("trade_date", ""), "side": "sell", 
                    "ts_code": doc.get("ts_code", ""), "strategy": doc.get("strategy", ""), 
                    "price": doc.get("filled_price", 0), "reason": doc.get("reason", ""),
                    "profit_pct": doc.get("profit_pct", 0),
                })
        else:
            # 日内模式
            # 【v2.9.86修复】日内情绪应随盘面变化，不再简单读取全日汇总的L3_sentiment_data
            # 新逻辑：从scan_traces的每个时间点重新计算情绪，结合candidates/passed数变化
            def _parse_l3(doc):
                l3d = doc.get("layer_details", {}).get("L3_sentiment_data") or {}
                l3_text = doc.get("layer_details", {}).get("L3_sentiment", "")
                score = l3d.get("score", 0)
                period = l3d.get("period", "")
                position_ratio = l3d.get("position_ratio", 0)
                if not score and l3_text:
                    m = re.search(r'情绪=([\\d.]+)分', l3_text)
                    if m: score = float(m.group(1))
                    m2 = re.search(r'仓位系数=([\\d.]+)', l3_text)
                    if m2: position_ratio = float(m2.group(1))
                    m3 = re.search(r'→(高潮|分化|震荡|冰点)', l3_text)
                    if m3: period = m3.group(1)
                return score, period, position_ratio
            
            # 1. 收集所有scan_traces(含L3情绪数据)
            raw_points = []
            async for doc in db["scan_traces"].find(
                {"trade_date": date},
                {"scan_time": 1, "layer_details": 1, "summary": 1, "is_debug": 1}
            ).sort("scan_time", 1):
                score, period, position_ratio = _parse_l3(doc)
                raw_points.append({
                    "time": doc.get("scan_time", "")[:19],
                    "score": round(score, 1) if score else None,
                    "period": period,
                    "position_ratio": position_ratio,
                    "candidates": doc.get("summary", {}).get("total_candidates", 0),
                    "passed": doc.get("summary", {}).get("passed", 0),
                    "is_debug": doc.get("is_debug", False),
                })
            
            # 2. 【v2.9.86新增】日内情绪变化计算
            # 如果所有L3 score相同(旧bug遗留数据或缓存导致)，则从candidates/passed变化重新估算
            if raw_points:
                scores = [p["score"] for p in raw_points if p.get("score") is not None]
                all_same = len(set(scores)) <= 1 and len(scores) > 1
                
                if all_same and scores[0] is not None:
                    # 所有score相同，需要重新估算日内情绪变化
                    # 获取当日的sentiment_scores作为基线
                    baseline_score = scores[0]
                    try:
                        ss_doc = await db["sentiment_scores"].find_one({"trade_date": int(date)})
                        if ss_doc:
                            baseline_score = ss_doc.get("score", scores[0])
                    except Exception:
                        pass
                    
                    # 从candidates/passed比例估算日内情绪变化
                    # passed/candidates 越高说明市场越活跃(更多票通过筛选)
                    max_passed = max((p.get("passed", 0) for p in raw_points), default=1) or 1
                    
                    for p in raw_points:
                        if p.get("is_debug"):
                            continue
                        passed = p.get("passed", 0)
                        cands = p.get("candidates", 0) or 1
                        # 活跃度比率: passed占max_passed的比例
                        activity_ratio = passed / max_passed if max_passed > 0 else 0.5
                        # 从时间推断盘中阶段
                        time_str = p.get("time", "")
                        hour_factor = 1.0
                        if len(time_str) >= 16:
                            hour = int(time_str[11:13])
                            minute = int(time_str[14:16])
                            # 早盘(9:30-10:30)情绪略高, 午盘(13:00-14:00)稳定, 尾盘(14:30-15:00)波动大
                            if hour == 9 or (hour == 10 and minute <= 30):
                                hour_factor = 1.05  # 早盘情绪略高
                            elif hour == 14 and minute >= 30:
                                hour_factor = 0.95  # 尾盘情绪略低(获利了结)
                            elif hour == 11:
                                hour_factor = 0.98  # 上午收盘前
                        
                        # 估算score: 基线 * 活跃度调整 * 时间调整
                        # 活跃度影响±10分, 时间影响±5分
                        estimated = baseline_score * hour_factor + (activity_ratio - 0.5) * 20
                        estimated = max(0, min(100, round(estimated, 1)))
                        p["score"] = estimated
                        
                        # 重新计算period
                        from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK
                        _th = GLOBAL_RISK.get("sentiment_thresholds", {"rising": 70, "differentiation": 55, "chaos": 40})
                        if estimated >= _th["rising"]:
                            p["period"] = "rising"
                            p["position_ratio"] = _get_position_ratio_sentiment("高潮", 0.9)
                        elif estimated >= _th["differentiation"]:
                            p["period"] = "differentiation"
                            p["position_ratio"] = _get_position_ratio_sentiment("分化", 0.7)
                        elif estimated >= _th["chaos"]:
                            p["period"] = "chaos"
                            p["position_ratio"] = _get_position_ratio_sentiment("震荡", 0.5)
                        else:
                            p["period"] = "bearish"
                            p["position_ratio"] = _get_position_ratio_sentiment("冰点", 0.3)
            
            points = raw_points
            
            # 【v2.9.86修复】日内broker_orders查询也要用int
            date_int = int(date) if isinstance(date, str) and date.isdigit() else date
            async for doc in db["broker_orders"].find(
                {"trade_date": date_int, "status": "filled"},
                {"fill_time": 1, "side": 1, "ts_code": 1, "strategy": 1, "filled_price": 1, "reason": 1}
            ).sort("fill_time", 1):
                if doc.get("side") in ("buy", "sell"):
                    trades.append({"time": doc.get("fill_time", ""), "side": doc["side"], "ts_code": doc.get("ts_code", ""), "strategy": doc.get("strategy", ""), "price": doc.get("filled_price", 0), "reason": doc.get("reason", "") if doc["side"] == "sell" else ""})
        
        return {"success": True, "data": {"date": date, "mode": mode, "points": points, "trades": trades}}
    except Exception as e:
        return {"success": True, "data": {"points": [], "trades": []}, "message": str(e)}



@router.get("/sentiment-strategy-matrix")
async def get_sentiment_strategy_matrix(date: str = None):
    """策略×情绪 效果矩阵 — 按情绪阶段分组统计每个策略的交易表现"""
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": {"matrix": {}, "recommendations": []}}
        db = mongo_manager.db
        import re
        from collections import defaultdict
        from nodes.backtest_engine.strategy_defaults import STRATEGY_ID_TO_NAME
        
        # 策略名映射: 统一使用STRATEGY_ID_TO_NAME, 缺省时用ID本身
        from nodes.backtest_engine.strategy_defaults import normalize_strategy_id as _normalize_sid
        def _strategy_display_name(sid: str) -> str:
            return STRATEGY_ID_TO_NAME.get(_normalize_sid(sid), sid)
        
        # 英文key fallback: MongoDB中如果存了英文period(RISING/BEARISH等),转成中文
        _en_to_cn_period = {
            "RISING": "高潮", "DIFFERENTIATION": "分化", "CHAOS": "震荡", "BEARISH": "冰点",
            "rising": "高潮", "differentiation": "分化", "chaos": "震荡", "bearish": "冰点",
        }
        # 获取每日情绪阶段
        daily_sentiment = {}
        # 从sentiment_scores读取,missing_data的日期用前一个有效期补
        last_valid_period = ""
        async for doc in db["sentiment_scores"].find({}, {"trade_date": 1, "period": 1, "missing_data": 1}).sort("trade_date", 1):
            td = str(doc["trade_date"])
            period = doc.get("period", "")
            # 英文key转中文
            if period in _en_to_cn_period:
                period = _en_to_cn_period[period]
            if doc.get("missing_data"):
                # 用前一个有效期补,没有则为数据缺失
                period = last_valid_period if last_valid_period else "数据缺失"
            else:
                last_valid_period = period
            if period:
                daily_sentiment[td] = period
        
        matrix = defaultdict(lambda: defaultdict(lambda: {"wins": 0, "losses": 0, "count": 0, "total_pnl": 0.0, "win_pnl": 0.0, "loss_pnl": 0.0}))
        strategy_totals = defaultdict(lambda: {"wins": 0, "losses": 0, "count": 0, "total_pnl": 0.0})
        
        # 构建查询条件: date参数时只统计该日期及之前的卖出
        sell_query = {"side": "sell", "status": "filled"}
        if date:
            try:
                # 【v2.9.86修复】broker_orders.trade_date是int，不能用str
                sell_query["trade_date"] = {"$lte": int(date)}
            except Exception:
                pass
        
        async for doc in db["broker_orders"].find(
            sell_query,
            {"trade_date": 1, "strategy": 1, "reason": 1, "filled_price": 1, "filled_qty": 1}
        ):
            strategy = _normalize_sid(doc.get("strategy", "unknown") or "unknown")
            # 强制空仓等系统指令归为"system_force"策略
            if not strategy or strategy == "unknown":
                reason_text = doc.get("reason", "") or ""
                if "强制" in reason_text or "空仓" in reason_text:
                    strategy = "system_force"
                else:
                    strategy = strategy or "unknown"
            td = doc.get("trade_date", "")
            reason = doc.get("reason", "")
            fp = doc.get("filled_price", 0) or 0
            fq = doc.get("filled_qty", 0) or 0
            period = daily_sentiment.get(td, "")
            if not period:
                period = "冰点" if "强制" in reason or "空仓" in reason else "未知"
            
            # 优先从broker_orders的profit_pct字段读取(真实盈亏)
            profit_pct = doc.get("profit_pct", 0) or 0
            profit_amount = doc.get("profit_amount", 0) or 0
            if not profit_pct and not profit_amount:
                # 无盈亏数据,从reason推断
                pct_match = re.search(r'曾盈([\\d.]+)%', reason)
                if not pct_match:
                    pct_match = re.search(r'-?([\\d.]+)%', reason)
                profit_pct = float(pct_match.group(1)) if pct_match else 0
                if "止损" in reason and "追踪" not in reason:
                    profit_pct = -abs(profit_pct)
            
            pnl = profit_amount if profit_amount else fp * fq * profit_pct / 100
            # profit_pct=0且无profit_amount的跳过(无法判断胜负)
            if profit_pct == 0 and profit_amount == 0 and not reason:
                continue
            # 有profit_pct时用真实盈亏判断胜负
            if profit_pct != 0:
                is_win = profit_pct > 0
            elif profit_amount != 0:
                is_win = profit_amount > 0
            else:
                # 从reason推断
                is_win = "止盈" in reason or "追踪止损" in reason or "冲高" in reason
            matrix[strategy][period]["count"] += 1
            matrix[strategy][period]["wins"] += int(is_win)
            matrix[strategy][period]["losses"] += int(not is_win)
            matrix[strategy][period]["total_pnl"] += pnl
            if is_win:
                matrix[strategy][period]["win_pnl"] += abs(pnl)
            else:
                matrix[strategy][period]["loss_pnl"] += abs(pnl)
            strategy_totals[strategy]["count"] += 1
            strategy_totals[strategy]["wins"] += int(is_win)
            strategy_totals[strategy]["losses"] += int(not is_win)
            strategy_totals[strategy]["total_pnl"] += pnl
        
        # 策略ID normalize: 将anomaly_surge等别名归并到正式策略
        # 合并normalize后的matrix数据(如anomaly_surge和halfway_chase合并)
        normalized_matrix = defaultdict(lambda: defaultdict(lambda: {"wins": 0, "losses": 0, "count": 0, "total_pnl": 0.0, "win_pnl": 0.0, "loss_pnl": 0.0}))
        for strat, periods in matrix.items():
            norm_sid = _normalize_sid(strat)
            for per, data in periods.items():
                nd = normalized_matrix[norm_sid][per]
                nd["wins"] += data["wins"]
                nd["losses"] += data["losses"]
                nd["count"] += data["count"]
                nd["total_pnl"] += data["total_pnl"]
                nd["win_pnl"] += data["win_pnl"]
                nd["loss_pnl"] += data["loss_pnl"]
        # 用normalize后的matrix替换原始matrix
        matrix = normalized_matrix
        strategy_totals_norm = defaultdict(lambda: {"wins": 0, "losses": 0, "count": 0, "total_pnl": 0.0})
        for strat, totals in strategy_totals.items():
            norm_sid = _normalize_sid(strat)
            nd = strategy_totals_norm[norm_sid]
            nd["wins"] += totals["wins"]
            nd["losses"] += totals["losses"]
            nd["count"] += totals["count"]
            nd["total_pnl"] += totals["total_pnl"]
        strategy_totals = strategy_totals_norm
        
        result_matrix = {}
        for strat, periods in matrix.items():
            result_matrix[strat] = {}
            for per, data in periods.items():
                # 盈亏比 = 平均盈利 / 平均亏损
                profit_loss_ratio = 0.0
                if data["wins"] > 0 and data["losses"] > 0 and data["loss_pnl"] > 0:
                    avg_win = data["win_pnl"] / data["wins"]
                    avg_loss = data["loss_pnl"] / data["losses"]
                    profit_loss_ratio = round(avg_win / max(avg_loss, 0.001), 2)
                result_matrix[strat][per] = {
                    "count": data["count"],
                    "win_rate": round(data["wins"]/max(data["count"],1)*100,1),
                    "total_pnl": round(data["total_pnl"]),
                    "wins": data["wins"],
                    "losses": data["losses"],
                    "profit_loss_ratio": profit_loss_ratio,
                }
        
        recommendations = []
        for strat, periods in result_matrix.items():
            best = max(periods.items(), key=lambda x: x[1]["win_rate"]*x[1]["count"] if x[1]["count"]>0 else 0)
            if best[1]["count"] >= 2:
                recommendations.append({"strategy": strat, "best_period": best[0], "win_rate": best[1]["win_rate"], "count": best[1]["count"], "pnl": best[1]["total_pnl"]})
        recommendations.sort(key=lambda x: x["pnl"], reverse=True)
        
        return {"success": True, "data": {
            "matrix": result_matrix,
            "strategy_names": {sid: _strategy_display_name(sid) for sid in result_matrix},
            "strategy_totals": {k: {"count": v["count"], "wins": v["wins"], "losses": v["losses"], "win_rate": round(v["wins"]/max(v["count"],1)*100,1), "total_pnl": round(v["total_pnl"])} for k,v in strategy_totals.items()},
            "recommendations": recommendations[:5],
        }}
    except Exception as e:
        return {"success": True, "data": {"matrix": {}, "recommendations": []}, "message": str(e)}



@router.get("/market-sentiment")
async def get_market_sentiment_detail(date: str = None):
    """市场情绪全景"""
    scanner = await _get_scanner()
    try:
        filter_pipeline = getattr(scanner, '_filter_pipeline', None)
        emotion = getattr(filter_pipeline, '_emotion_cycle', None) if filter_pipeline else None
        sentiment_score = getattr(emotion, 'score', None) if emotion else None
        sentiment_period = getattr(emotion, 'period', None) if emotion else None
        position_ratio = getattr(emotion, 'position_ratio', None) if emotion else None
        
        # 实时数据优先,无则从sentiment_scores读
        if sentiment_score is None or sentiment_period is None:
            try:
                from core.managers import mongo_manager
                if mongo_manager.is_initialized:
                    # 1. 优先读指定日期(即使missing也返回,标注数据不完整)
                    if date:
                        exact = await mongo_manager.db["sentiment_scores"].find_one({"trade_date": int(date)})
                        if exact:
                            sentiment_score = exact.get("score", 50)
                            sentiment_period = exact.get("period", "unknown")
                            position_ratio = _get_position_ratio_sentiment(exact.get("period", ""), exact.get("position_ratio", 0.25))
                            if exact.get("missing_data"):
                                sentiment_period = "冰点(数据缺失)"  # 保留period但标注缺失
                    # 2. 指定日期无数据或未指定日期→读最近的非missing日期
                    if sentiment_period is None or (not date and sentiment_period is None):
                        latest = await mongo_manager.db["sentiment_scores"].find_one(
                            {"missing_data": {"$ne": True}},
                            sort=[("trade_date", -1)]
                        )
                        if latest:
                            sentiment_score = latest.get("score", 50)
                            sentiment_period = latest.get("period", "unknown")
                            position_ratio = _get_position_ratio_sentiment(latest.get("period", ""), latest.get("position_ratio", 0.25))
            except Exception:
                pass
        
        # 最终fallback
        if sentiment_score is None: sentiment_score = 50
        if sentiment_period is None: sentiment_period = "unknown"
        if position_ratio is None: position_ratio = 0.3
        
        limit_pools = getattr(scanner, '_limit_pools', {})
        limit_up = len(limit_pools.get("limit_up", []))
        limit_down = len(limit_pools.get("limit_down", []))
        broken = len(limit_pools.get("broken", []))
        board_dist = {}
        for item in limit_pools.get("limit_up", []):
            t = item.get("limit_times", 1)
            board_dist[str(t)] = board_dist.get(str(t), 0) + 1
        
        # 涨跌停=0时从sentiment_scores补(优先指定日期,包括missing)
        if limit_up == 0 and limit_down == 0:
            try:
                from core.managers import mongo_manager
                if mongo_manager.is_initialized:
                    doc = None
                    if date:
                        doc = await mongo_manager.db["sentiment_scores"].find_one({"trade_date": int(date)})
                    if not doc or doc.get("missing_data"):
                        # fallback到最近非missing
                        doc = await mongo_manager.db["sentiment_scores"].find_one(
                            {"missing_data": {"$ne": True}},
                            sort=[("trade_date", -1)]
                        )
                    if doc:
                        limit_up = doc.get("limit_up", 0)
                        limit_down = doc.get("limit_down", 0)
                        # 连板分布从max_continue推算
                        mc = doc.get("max_continue", 0)
                        if mc > 0:
                            board_dist[str(mc)] = board_dist.get(str(mc), 0) + 1
            except Exception:
                pass
        broken_rate = broken / max(limit_up + broken, 1) * 100

        # 【v2.9.85修复】情绪阈值从strategy_defaults统一读取,不再硬编码
        from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK
        _th = GLOBAL_RISK.get("sentiment_thresholds", {"rising": 70, "differentiation": 55, "chaos": 40})
        _rising_th = _th["rising"]
        _diff_th = _th["differentiation"]
        _chaos_th = _th["chaos"]

        period_labels = {
            "BEARISH": ("冰点", 0, _chaos_th), "CHAOS": ("震荡", _chaos_th, _diff_th),
            "DIFFERENTIATION": ("分化", _diff_th, _rising_th), "RISING": ("高潮", _rising_th, 100),
            "bearish": ("冰点", 0, _chaos_th), "chaos": ("震荡", _chaos_th, _diff_th),
            "differentiation": ("分化", _diff_th, _rising_th), "rising": ("高潮", _rising_th, 100),
            "冰点": ("冰点", 0, _chaos_th), "震荡": ("震荡", _chaos_th, _diff_th),
            "分化": ("分化", _diff_th, _rising_th), "高潮": ("高潮", _rising_th, 100),
            "冰点(数据缺失)": ("冰点⚠", 0, _chaos_th), "震荡(数据缺失)": ("震荡⚠", _chaos_th, _diff_th),
            "分化(数据缺失)": ("分化⚠", _diff_th, _rising_th), "高潮(数据缺失)": ("高潮⚠", _rising_th, 100),
        }
        pi = period_labels.get(sentiment_period, None)
        if pi is None:
            # 根据分数自动推断情绪周期
            if sentiment_score >= _rising_th: pi = ("高潮", _rising_th, 100)
            elif sentiment_score >= _diff_th: pi = ("分化", _diff_th, _rising_th)
            elif sentiment_score >= _chaos_th: pi = ("震荡", _chaos_th, _diff_th)
            else: pi = ("冰点", 0, _chaos_th)
            sentiment_period = pi[0]

        # can_open: 与EmotionCycleManager.CAN_OPEN对齐(冰点禁止开仓)
        _can_open = sentiment_period not in ("冰点", "冰点(数据缺失)", "bearish", "BEARISH")
        return _sanitize({"success": True, "data": {
            "score": sentiment_score, "period": sentiment_period, "period_label": pi[0],
            "position_ratio": position_ratio, "can_open": _can_open,
            "limit_up_count": limit_up, "limit_down_count": limit_down, "broken_count": broken,
            "broken_rate": round(broken_rate, 1), "board_distribution": board_dist,
            "ranges": [
                {"label": "冰点", "min": 0, "max": _chaos_th, "color": "#67c23a"},
                {"label": "震荡", "min": _chaos_th, "max": _diff_th, "color": "#e6a23c"},
                {"label": "分化", "min": _diff_th, "max": _rising_th, "color": "#409eff"},
                {"label": "高潮", "min": _rising_th, "max": 100, "color": "#f56c6c"},
            ],
        }})
    except Exception as e:
        return {"success": False, "message": str(e)}


