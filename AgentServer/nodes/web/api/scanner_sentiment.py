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
    normalize_data_mode,
)

router = APIRouter(prefix="/scanner", tags=["市场情绪/情绪矩阵"])


def _get_effective_sentiment_thresholds() -> Dict:
    """获取运行时有效的情绪阈值(默认+覆盖)"""
    from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK
    thresholds = dict(GLOBAL_RISK.get("sentiment_thresholds", {"rising": 70, "differentiation": 55, "chaos": 40}))
    try:
        from nodes.web.api.strategy_config import _override_global_risk, _overrides_loaded
        if _overrides_loaded and _override_global_risk:
            override_st = _override_global_risk.get("sentiment_thresholds", {})
            if override_st:
                thresholds.update(override_st)
    except Exception:
        pass
    return thresholds


def _get_position_ratio_sentiment(period_cn: str, fallback: float = 0.3) -> float:
    """从strategy_defaults读取仓位系数(与emotion_cycle._get_position_ratio统一来源)
    
    【V75-审计修复】优先从运行时覆盖读取,确保strategy-config API修改后立即生效。
    """
    try:
        from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK
        # 中文key映射
        cn_to_en = {"高潮": "rising", "分化": "differentiation", "震荡": "chaos", "冰点": "bearish"}
        # 英文key也直接支持(大小写不敏感)
        en_lower = period_cn.lower() if period_cn else ""
        en_map = {"rising": "rising", "differentiation": "differentiation", "chaos": "chaos", "bearish": "bearish"}
        en_key = cn_to_en.get(period_cn, en_map.get(en_lower, "bearish"))
        
        # 优先读运行时覆盖(strategy-config API修改的值)
        try:
            from nodes.web.api.strategy_config import _override_global_risk, _overrides_loaded
            if _overrides_loaded and _override_global_risk:
                override_spm = _override_global_risk.get("sentiment_position_map", {})
                if en_key in override_spm:
                    return float(override_spm[en_key])
        except Exception:
            pass
        
        return GLOBAL_RISK.get("sentiment_position_map", {}).get(en_key, fallback)
    except Exception:
        return fallback


@router.get("/sentiment-timeline")
async def get_sentiment_timeline(date: str = None, mode: str = "daily", data_mode: str = "production", include_debug: bool = False):
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
                raw_period = doc.get("period", "")
                raw_score = doc.get("score", 0)
                # 非标准period兜底: 根据score推断(如period="daily"→按阈值推断)
                _cn_periods = {"高潮", "分化", "震荡", "冰点"}
                _en_to_cn = {"RISING": "高潮", "DIFFERENTIATION": "分化", "CHAOS": "震荡", "BEARISH": "冰点", "rising": "高潮", "differentiation": "分化", "chaos": "震荡", "bearish": "冰点"}
                if raw_period in _en_to_cn:
                    raw_period = _en_to_cn[raw_period]
                if raw_period not in _cn_periods:
                    _th = _get_effective_sentiment_thresholds()
                    if raw_score >= _th["rising"]: raw_period = "高潮"
                    elif raw_score >= _th["differentiation"]: raw_period = "分化"
                    elif raw_score >= _th["chaos"]: raw_period = "震荡"
                    else: raw_period = "冰点"
                daily_map[td] = {
                    "date": td, "score": raw_score, "period": raw_period,
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
                    # 【V75-审计修复】读取运行时覆盖后的有效阈值
                    _th = _get_effective_sentiment_thresholds()
                    if avg_score >= _th["rising"]: period = "高潮"
                    elif avg_score >= _th["differentiation"]: period = "分化"
                    elif avg_score >= _th["chaos"]: period = "震荡"
                    else: period = "冰点"
                    agg_points.append({
                        "date": key, "score": round(avg_score, 1), "period": period,
                        "position_ratio": _get_position_ratio_sentiment(period, 0.3),
                        "limit_up": total_lu, "limit_down": total_ld,
                        "days": len(grp), "first_date": grp[0]["date"], "last_date": grp[-1]["date"],
                        "missing_data": has_missing,
                    })
                points = agg_points
            
            # trades: 只取时间范围内的sell记录
            # 【v2.9.99-r6】预加载 buy_index (broker_orders.profit_pct 经常为0)
            try:
                from nodes.web.api.pnl_helper import build_buy_price_index, fallback_pnl
                _buy_idx_tl = await build_buy_price_index(db)
            except Exception:
                _buy_idx_tl = {}
                def fallback_pnl(d, idx): return (d.get("profit_pct", 0) or 0, d.get("profit_amount", 0) or 0)
            trade_query = {"status": "filled", "side": "sell"}
            if mode == "daily" and query.get("trade_date"):
                td_q = query["trade_date"]
                trade_query["trade_date"] = td_q
            async for doc in db["broker_orders"].find(
                trade_query,
                {"trade_date": 1, "side": 1, "ts_code": 1, "strategy": 1, "filled_price": 1, "reason": 1, "profit_pct": 1, "profit_amount": 1, "filled_qty": 1, "avg_cost": 1}
            ).sort("trade_date", 1):
                # fallback 计算 sell profit_pct=0 的情况
                pct_fb, amt_fb = fallback_pnl(doc, _buy_idx_tl)
                trades.append({
                    "date": doc.get("trade_date", ""), "side": "sell", 
                    "ts_code": doc.get("ts_code", ""), "strategy": doc.get("strategy", ""), 
                    "price": doc.get("filled_price", 0), "reason": doc.get("reason", ""),
                    "profit_pct": pct_fb,
                    "profit_amount": amt_fb,
                })
        else:
            # 日内模式 — v2.9.92: 多指标展示(涨跌停柱状图+涨跌比+情绪score)
            from nodes.web.api.scanner_sentiment_intraday import get_intraday_timeline
            result = await get_intraday_timeline(db, date, data_mode=normalize_data_mode(data_mode, include_debug))
            points = result["points"]
            trades = result.get("trades", [])
        
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
        _cn_periods = {"高潮", "分化", "震荡", "冰点"}
        # 获取每日情绪阶段
        daily_sentiment = {}
        # 从sentiment_scores读取,missing_data的日期用前一个有效期补
        last_valid_period = ""
        async for doc in db["sentiment_scores"].find({}, {"trade_date": 1, "period": 1, "score": 1, "missing_data": 1}).sort("trade_date", 1):
            td = str(doc["trade_date"])
            period = doc.get("period", "")
            score = doc.get("score", 50)
            # 英文key转中文
            if period in _en_to_cn_period:
                period = _en_to_cn_period[period]
            # 非标准period(如"daily")兜底: 根据score推断
            if period not in _cn_periods and period not in ("数据缺失", ""):
                _th = _get_effective_sentiment_thresholds()
                if score >= _th["rising"]: period = "高潮"
                elif score >= _th["differentiation"]: period = "分化"
                elif score >= _th["chaos"]: period = "震荡"
                else: period = "冰点"
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
        
        # 【v2.9.99-r6】预加载 buy_index (broker_orders.profit_pct 经常为0)
        try:
            from nodes.web.api.pnl_helper import build_buy_price_index, fallback_pnl
            _buy_idx_ssm = await build_buy_price_index(db)
        except Exception:
            _buy_idx_ssm = {}

        async for doc in db["broker_orders"].find(
            sell_query,
            {"trade_date": 1, "strategy": 1, "reason": 1, "filled_price": 1, "filled_qty": 1,
             "ts_code": 1, "side": 1, "profit_pct": 1, "profit_amount": 1, "avg_cost": 1}
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
            # 【v2.9.99-r6】broker_orders.profit_pct 经常为0 (broker 时序问题) → fallback 自算
            if not profit_pct and not profit_amount:
                try:
                    _pct_fb, _amt_fb = fallback_pnl(doc, _buy_idx_ssm)
                    if _pct_fb != 0 or _amt_fb != 0:
                        profit_pct = _pct_fb
                        profit_amount = _amt_fb
                except Exception:
                    pass
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
                    # 1. 优先读指定日期, 但 missing_data=True 时不使用它的 score, 只作为【该日有记录】的提示
                    if date:
                        exact = await mongo_manager.db["sentiment_scores"].find_one({"trade_date": int(date)})
                        # 【v2.9.96g修复】只有 missing_data!=True 时才使用 exact 的 score
                        if exact and not exact.get("missing_data"):
                            sentiment_score = exact.get("score", 50)
                            sentiment_period = exact.get("period", "unknown")
                            position_ratio = _get_position_ratio_sentiment(exact.get("period", ""), exact.get("position_ratio", 0.3))
                    # 2. 指定日期无数据、或指定日期被标 missing_data, 都走这里 fallback 到最近非 missing
                    if sentiment_period is None or sentiment_score is None:
                        latest = await mongo_manager.db["sentiment_scores"].find_one(
                            {"missing_data": {"$ne": True}},
                            sort=[("trade_date", -1)]
                        )
                        if latest:
                            sentiment_score = latest.get("score", 50)
                            sentiment_period = latest.get("period", "unknown")
                            position_ratio = _get_position_ratio_sentiment(latest.get("period", ""), latest.get("position_ratio", 0.3))
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
        # 【V75-审计修复】读取运行时覆盖后的有效阈值
        _th = _get_effective_sentiment_thresholds()
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
        # 【v2.9.99修复】统一period返回中文(之前英文period如DIFFERENTIATION直接返回)
        sentiment_period = pi[0]

        # 【v2.9.96g】充补 5维拆解字段(max_continue/up_down_ratio/zt_premium)供前端得分拆解展示
        max_continue = 0
        up_down_ratio = 0.0
        zt_premium = 0.0
        try:
            from core.managers import mongo_manager
            if mongo_manager.is_initialized:
                doc = None
                if date:
                    doc = await mongo_manager.db["sentiment_scores"].find_one({"trade_date": int(date)})
                if not doc or doc.get("missing_data"):
                    doc = await mongo_manager.db["sentiment_scores"].find_one(
                        {"missing_data": {"$ne": True}},
                        sort=[("trade_date", -1)]
                    )
                if doc:
                    max_continue = doc.get("max_continue", 0)
                    up_down_ratio = doc.get("up_down_ratio", 0.0)
                    zt_premium = doc.get("zt_premium", 0.0)
        except Exception:
            pass
        # 盘中 实时取优先从 scanner 拿(优于 MongoDB)
        try:
            if filter_pipeline and emotion:
                lc = getattr(emotion, '_last_compute', None) or {}
                if lc.get('max_continue') is not None: max_continue = lc.get('max_continue', max_continue)
                if lc.get('up_down_ratio') is not None: up_down_ratio = lc.get('up_down_ratio', up_down_ratio)
                if lc.get('today_premium') is not None: zt_premium = lc.get('today_premium', zt_premium)
        except Exception:
            pass

        # 【v2.9.98修复-Issue3a53d130d1bc】增加date和is_stale标记
        _actual_date = None
        _is_stale = False
        try:
            from core.managers import mongo_manager
            if mongo_manager.is_initialized:
                _requested_date = int(date) if date else int(datetime.now().strftime("%Y%m%d"))
                _exact_doc = await mongo_manager.db["sentiment_scores"].find_one({"trade_date": _requested_date})
                if _exact_doc and not _exact_doc.get("missing_data"):
                    _actual_date = _requested_date
                    _is_stale = False
                elif _exact_doc and _exact_doc.get("missing_data"):
                    _actual_date = _requested_date
                    _is_stale = True
                else:
                    # 无当日数据，用的是fallback数据
                    _latest_doc = await mongo_manager.db["sentiment_scores"].find_one(
                        {"missing_data": {"$ne": True}}, sort=[("trade_date", -1)]
                    )
                    _actual_date = _latest_doc.get("trade_date") if _latest_doc else None
                    _is_stale = True
        except Exception:
            pass

        # can_open: 与EmotionCycleManager.CAN_OPEN对齐(冰点禁止开仓)
        _can_open = sentiment_period not in ("冰点", "冰点(数据缺失)", "bearish", "BEARISH")
        return _sanitize({"success": True, "data": {
            "score": sentiment_score, "period": sentiment_period, "period_label": pi[0],
            "position_ratio": position_ratio, "can_open": _can_open,
            "limit_up_count": limit_up, "limit_down_count": limit_down, "broken_count": broken,
            "broken_rate": round(broken_rate, 1), "board_distribution": board_dist,
            # 【v2.9.96g】5维拆解补充
            "max_continue": max_continue,
            "up_down_ratio": round(up_down_ratio, 3),
            "zt_premium": round(zt_premium, 2),
            # 【v2.9.98新增-Issue3a53d130d1bc】日期+新鲜度标记
            "date": _actual_date,
            "is_stale": _is_stale,
            "ranges": [
                {"label": "冰点", "min": 0, "max": _chaos_th, "color": "#67c23a"},
                {"label": "震荡", "min": _chaos_th, "max": _diff_th, "color": "#e6a23c"},
                {"label": "分化", "min": _diff_th, "max": _rising_th, "color": "#409eff"},
                {"label": "高潮", "min": _rising_th, "max": 100, "color": "#f56c6c"},
            ],
        }})
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.get("/sentiment-live-log")
async def get_sentiment_live_log(limit: int = 50):
    """【v2.9.96h】盘中情绪实时计算日志
    
    返回 scanner 运行过程中每次情绪计算的快照(时间、得分、周期、净倒仓、涨跌停、连板、涨跌比、溢价、炸板).
    供 SentimentTab 展示“近 N 次计算日志”面板.
    
    环形缓冲 maxlen=300 (在 emotion_cycle.py __init__ 中初始化).
    只记录实时模式(limit_stocks!=None), 避免夜间调用污染.
    """
    scanner = await _get_scanner()
    try:
        # 【v2.9.96h】直接读全局单例 emotion_cycle_manager (不依赖 filter_pipeline)
        from nodes.market_monitor.emotion_cycle import emotion_cycle_manager as emotion
        if not emotion:
            return {"success": True, "data": {"logs": [], "count": 0, "reason": "emotion_cycle_not_initialized"}}
        
        log = getattr(emotion, '_compute_log', None)
        if log is None:
            return {"success": True, "data": {"logs": [], "count": 0, "reason": "no_compute_log"}}
        
        # 返回最近 N 条(逆序, 最新在前)
        items = list(log)
        items.reverse()
        items = items[:max(1, min(limit, 300))]
        
        return _sanitize({"success": True, "data": {
            "logs": items,
            "count": len(items),
            "total_buffer": len(log),
        }})
    except Exception as e:
        return {"success": False, "message": str(e)}

