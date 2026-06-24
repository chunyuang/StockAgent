#!/usr/bin/env python3
"""Scanner API - 调试/模拟/热更新"""
import asyncio
import logging
import math
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from nodes.web.api.utils import sanitize_nan as _sanitize
from nodes.web.api.unified import aggregate_trades

# 从scanner共享模块导入
from nodes.web.api.scanner_shared import (
    _get_scanner, _get_scanner_instance, _clean_mongo,
    _fill_stock_names, _safe_read_shared, logger,
    ScannerStartRequest, ManualTradeRequest, PartialSellRequest,
    StopScannerRequest, ScanOnceRequest, PauseRequest,
)
from nodes.web.api.scanner_system import _build_limit_pools, _build_position_gaps, _build_premarket_analysis, _build_name_industry_maps, _aggregate_limit_stats

router = APIRouter(prefix="/scanner", tags=["调试/模拟/热更新"])


@router.get("/debug/layers")
async def get_debug_layers():
    """获取9层筛选管道的逐层调试信息
    
    返回每层的:
    - 输入候选数
    - 过滤后候选数
    - 过滤原因(具体哪些股票被哪层过滤)
    - 层开关状态
    
    用于前端可视化展示筛选过程
    """
    scanner = await _get_scanner()
    
    # 收集所有信号的layer_trace
    all_traces = []
    for sig in scanner._active_signals:
        if sig.layer_trace:
            all_traces.append({
                "ts_code": sig.ts_code,
                "stock_name": sig.stock_name,
                "strategy": sig.strategy_name,
                "signal_status": sig.signal_status,
                "layer_trace": sig.layer_trace,
            })
    
    # 管道配置
    pipeline_config = {}
    if scanner._filter_pipeline:
        pipeline_config = {
            "layer_enabled": scanner._filter_pipeline._layer_enabled,
            "sentiment": scanner._filter_pipeline.get_sentiment_info(),
            "position_ratio": scanner._current_position_ratio,
        }
    
    # 策略筛选层trace(来自_apply_strategies)
    strategy_traces = []
    for sig in scanner._active_signals:
        if sig.layer_trace.get("L6_strategy"):
            strategy_traces.append(sig.layer_trace["L6_strategy"])
    
    return {
        "success": True,
        "data": {
            "signal_traces": all_traces,
            "pipeline_config": pipeline_config,
            "strategy_traces": strategy_traces,
            "total_signals": len(scanner._active_signals),
            "expired_signals": len([s for s in scanner._active_signals if s.signal_status == "expired"]),
            "executed_signals": len([s for s in scanner._active_signals if s.signal_status == "executed"]),
            "skipped_signals": len([s for s in scanner._active_signals if s.signal_status == "skipped"]),
            "dry_run": scanner._dry_run,
        }
    }



@router.get("/debug/scan-trace/{ts_code}")
async def get_scan_trace(ts_code: str):
    """获取指定股票的完整扫描+筛选trace
    
    从选股→9层筛选→执行, 每一步的详细记录
    用于调试某只股票为什么被选中/被过滤
    """
    scanner = await _get_scanner()
    
    # 从活跃信号中查找
    signal = None
    for sig in scanner._active_signals:
        if sig.ts_code == ts_code:
            signal = sig
            break
    
    if not signal:
        # 检查是否在持仓中(可能已执行)
        for p in scanner._broker.get_positions() if scanner._broker else []:
            if p.ts_code == ts_code:
                return {
                    "success": True,
                    "data": {
                        "ts_code": ts_code,
                        "status": "executed",
                        "message": f"已买入并持仓, 当前盈亏{p.profit_pct:+.1f}%",
                        "position": scanner._position_to_dict(p) if hasattr(scanner, '_position_to_dict') else {},
                    }
                }
        return {
            "success": True,
            "data": {
                "ts_code": ts_code,
                "status": "not_found",
                "message": "不在活跃信号或持仓中",
            }
        }
    
    return {
        "success": True,
        "data": {
            "ts_code": ts_code,
            "stock_name": signal.stock_name,
            "strategy": signal.strategy,
            "strategy_name": signal.strategy_name,
            "signal_status": signal.signal_status,
            "price": signal.price,
            "pct_chg": signal.pct_chg,
            "reason": signal.reason,
            "decision_detail": signal.decision_detail,
            "layer_trace": signal.layer_trace,
            "factors": signal.factors,
            "created_at": signal.created_at,
            "age_seconds": round(time.time() - signal.created_at, 1) if signal.created_at > 0 else None,
        }
    }



@router.post("/debug/dry-run")
async def toggle_dry_run():
    """切换dry_run模式(只扫描不交易)
    
    用于调试:
    - 开启: 扫描器只选股不下单, 信号标记为skipped
    - 关闭: 恢复正常交易
    
    不影响已持仓的止损止盈检查
    """
    scanner = await _get_scanner()
    scanner._dry_run = not scanner._dry_run
    mode = "dry_run(只扫描不交易)" if scanner._dry_run else "正常交易"
    logger.info(f"[API] 模式切换: {mode}")
    return {
        "success": True,
        "data": {
            "dry_run": scanner._dry_run,
            "mode": mode,
        }
    }



@router.get("/debug/premarket-sim")
async def debug_premarket_sim(date: str = None):
    """调试模式: 模拟盘前预选(非交易时间可用)
    
    两种策略:
    1. 如果scanner有realtime_cache(交易日), 直接用缓存行情
    2. 如果没有(非交易时间), 用daily_factors_df模拟全市场快照+策略预选
    
    返回:
    - market_snapshot: 用daily_factors_df填充涨跌分布(非交易时间也能看)
    - 实际产生的信号(active_signals)+被blocked的原因
    - 各策略的漏斗: 粗筛数 → 9层过滤后数
    - 情绪+历史命中率
    """
    scanner = await _get_scanner()
    scanner_running = scanner is not None and getattr(scanner, '_is_running', False)
    
    from core.managers import mongo_manager
    import pandas as pd
    
    # 非交易时间: 如果scanner未运行, 直接从MongoDB构建数据
    if not scanner_running:
        if not mongo_manager.is_initialized:
            return {"success": False, "message": "MongoDB未初始化，无法获取盘前数据"}
        
        # 从MongoDB读取最新日线数据作为daily_factors_df的替代
        try:
            latest_doc = await mongo_manager.db["stock_daily_ak_full"].find_one(
                {"trade_date": {"$exists": True}}, sort=[("trade_date", -1)],
                projection={"trade_date": 1}
            )
            if not latest_doc:
                return {"success": False, "message": "无历史日线数据"}
            latest_date = str(latest_doc["trade_date"])
            
            # 如果用户指定了日期, 用指定日期; 否则用最新交易日
            target_date = date.replace("-", "") if date else latest_date
            
            # 读取该日全市场数据
            docs = []
            async for doc in mongo_manager.db["stock_daily_ak_full"].find(
                {"trade_date": int(target_date)},
                {"ts_code": 1, "pct_chg": 1, "close": 1, "vol": 1, "amount": 1}
            ):
                docs.append(doc)
            
            # 指定日期无数据(周末/节假日), 自动回退到最近交易日
            if not docs and target_date != latest_date:
                logger.info(f"[premarket-sim] {target_date}无数据, 回退到{latest_date}")
                target_date = latest_date
                async for doc in mongo_manager.db["stock_daily_ak_full"].find(
                    {"trade_date": int(target_date)},
                    {"ts_code": 1, "pct_chg": 1, "close": 1, "vol": 1, "amount": 1}
                ):
                    docs.append(doc)
            
            if not docs:
                return {"success": False, "message": f"无{target_date}日线数据"}
            
            df = pd.DataFrame(docs)
            
            # 构建market_snapshot
            pcts = df['pct_chg'].dropna() if 'pct_chg' in df.columns else pd.Series()
            market_snapshot = {
                "up_count": int((pcts > 0).sum()) if len(pcts) else 0,
                "down_count": int((pcts < 0).sum()) if len(pcts) else 0,
                "flat_count": int((pcts == 0).sum()) if len(pcts) else 0,
                "limit_up_count": int((pcts >= 9.9).sum()) if len(pcts) else 0,
                "limit_down_count": int((pcts <= -9.9).sum()) if len(pcts) else 0,
                "avg_pct_chg": round(float(pcts.mean()), 2) if len(pcts) else 0,
                "volume_ratio_gt2": 0, "total_stocks": len(docs),
                "data_date": target_date,
            }
            
            # 构建candidates(粗筛预览)
            candidates = []
            strategy_map = {}
            if 'pct_chg' in df.columns:
                hc = df[(df['pct_chg'] >= 3) & (df['pct_chg'] <= 7)].nlargest(10, 'pct_chg')
                for _, row in hc.iterrows():
                    c = {"ts_code": row.get('ts_code', ''), "stock_name": '',
                         "strategy": "halfway_chase", "pct_chg": round(row.get('pct_chg', 0), 2),
                         "volume_ratio": 0, "turnover_rate": 0,
                         "signal_status": "preview",
                         "reason": f"涨{row.get('pct_chg',0):.1f}% (粗筛Top10)"}
                    candidates.append(c)
                    strategy_map.setdefault("halfway_chase", []).append(c)
                
                zt = df[df['pct_chg'] >= 9.9].nlargest(5, 'pct_chg')
                for _, row in zt.iterrows():
                    c = {"ts_code": row.get('ts_code', ''), "stock_name": '',
                         "strategy": "first_limit_up", "pct_chg": round(row.get('pct_chg', 0), 2),
                         "volume_ratio": 0, "turnover_rate": 0,
                         "signal_status": "preview",
                         "reason": f"涨停 {row.get('pct_chg',0):.1f}%"}
                    candidates.append(c)
                    strategy_map.setdefault("first_limit_up", []).append(c)
            
            # 填充股票名称(从stock_basic集合获取)
            ts_codes = [c['ts_code'] for c in candidates if c['ts_code']]
            name_map = {}
            if ts_codes:
                async for doc in mongo_manager.db["stock_basic"].find(
                    {"ts_code": {"$in": ts_codes}},
                    {"ts_code": 1, "name": 1}
                ):
                    if doc.get("name"):
                        name_map[doc["ts_code"]] = doc["name"]
                for c in candidates:
                    if not c.get("stock_name"):
                        c["stock_name"] = name_map.get(c['ts_code'], '')
            
            # 构建strategy_groups
            strategy_groups = []
            for s, group in strategy_map.items():
                avg_pct = sum(c['pct_chg'] for c in group) / len(group) if group else 0
                strategy_groups.append({"strategy": s, "count": len(group), "executed": 0, "blocked": 0,
                    "avg_pct_chg": round(avg_pct, 2), "candidates": group[:15]})
            
            # 情绪
            sentiment = {"score": 50, "period": "chaos", "position_ratio": 0.5, "phase_name": "震荡"}
            try:
                ss = await mongo_manager.db["sentiment_scores"].find_one(sort=[("updated_at", -1)])
                if ss:
                    raw_period = ss.get("period", "chaos")
                    period_map = {"RISING": "高潮", "DIFFERENTIATION": "分化",
                                  "CHAOS": "震荡", "BEARISH": "冰点",
                                  "rising": "高潮", "differentiation": "分化",
                                  "chaos": "震荡", "bearish": "冰点",
                                  "高潮": "高潮", "分化": "分化", "震荡": "震荡", "冰点": "冰点"}
                    sentiment = {"score": ss.get("score", 50), "period": raw_period,
                                 "position_ratio": ss.get("position_ratio", 0.5),
                                 "phase_name": period_map.get(raw_period, raw_period or "震荡")}
            except Exception:
                pass
            
            # 历史命中率
            historical_hit_rate = {}
            try:
                pipeline = [
                    {"$match": {"side": "sell", "profit_pct": {"$ne": None}}},
                    {"$group": {"_id": "$strategy", "total": {"$sum": 1},
                                "wins": {"$sum": {"$cond": [{"$gt": ["$profit_pct", 0]}, 1, 0]}},
                                "avg_profit": {"$avg": "$profit_pct"}}},
                ]
                # 【v2.9.97h-v4】使用aggregate_trades统一查询(自动注入account_id+filled)
                docs = await aggregate_trades(mongo_manager.db, pipeline, auto_filter=False)
                # pipeline已有自定义的$match, 不需要auto_filter
                for doc in docs:
                    s = doc["_id"] or "unknown"
                    total = doc["total"] or 1
                    historical_hit_rate[s] = {"total": total, "wins": doc["wins"],
                        "win_rate": round(doc["wins"] / total * 100, 1),
                        "avg_profit": round(doc.get("avg_profit", 0), 2)}
            except Exception:
                pass
            
            # 涨幅TOP
            top_gainers = []
            if 'pct_chg' in df.columns:
                for _, row in df.nlargest(10, 'pct_chg').iterrows():
                    top_gainers.append({"ts_code": row.get('ts_code', ''), "name": '',
                        "pct_chg": round(row.get('pct_chg', 0), 2), "volume_ratio": 0})
            # 填top_gainers名称(从stock_basic集合)
            tg_codes = [g['ts_code'] for g in top_gainers]
            if tg_codes:
                async for doc in mongo_manager.db["stock_basic"].find(
                    {"ts_code": {"$in": tg_codes}},
                    {"ts_code": 1, "name": 1}
                ):
                    if doc.get("name"):
                        for g in top_gainers:
                            if g['ts_code'] == doc['ts_code']:
                                g['name'] = doc['name']
            
            # 漏斗
            funnel = {"total_scanned": len(docs), "strategy_candidates": len(candidates),
                       "after_pipeline": len(candidates), "blocked": 0, "executed": 0}
            
            # 涨停池 - 优先从limit_list集合获取(含炸板/连板数据), 回退到日线pct_chg
            limit_up_list = []
            limit_down_list = []
            continue_stats = {}
            sector_heat = []
            limit_from_db = False
            try:
                # 查找该日期或最近有数据的日期
                td_query = int(target_date)
                ll_doc = await mongo_manager.db["limit_list"].find_one({"trade_date": td_query, "limit": "U"})
                if not ll_doc:
                    # 回退到最近有涨停数据的日期
                    ll_doc = await mongo_manager.db["limit_list"].find_one({"limit": "U"}, sort=[("trade_date", -1)])
                if ll_doc:
                    ll_td = ll_doc["trade_date"]
                    from nodes.web.api.scanner_system import _enrich_limit_times_from_history, _trade_date_match
                    ll_name_map, ll_industry_map = await _build_name_industry_maps()
                    ll_docs = [doc async for doc in mongo_manager.db["limit_list"].find({"trade_date": _trade_date_match(ll_td), "limit": "U"}, {"_id": 0})]
                    ll_docs = await _enrich_limit_times_from_history(mongo_manager.db, ll_td, ll_docs)
                    ll_ups, ll_continue, ll_sectors = _aggregate_limit_stats(ll_docs, ll_name_map, ll_industry_map)
                    ll_down = await mongo_manager.db["limit_list"].count_documents({"trade_date": _trade_date_match(ll_td), "limit": "D"})
                    limit_up_list = ll_ups[:20]
                    limit_down_count = ll_down
                    continue_stats = dict(sorted(ll_continue.items()))
                    sector_heat = sorted([{"name": k, "count": v} for k, v in ll_sectors.items()], key=lambda x: x["count"], reverse=True)[:8]
                    market_snapshot["limit_up_count"] = len(ll_ups)
                    market_snapshot["limit_down_count"] = ll_down
                    limit_from_db = True
            except Exception:
                pass
            
            if not limit_from_db and 'pct_chg' in df.columns:
                zt_df = df[df['pct_chg'] >= 9.9]
                for _, row in zt_df.nlargest(20, 'pct_chg').iterrows():
                    limit_up_list.append({
                        "ts_code": row.get('ts_code', ''), "name": name_map.get(row.get('ts_code', ''), ''),
                        "pct_chg": round(row.get('pct_chg', 0), 2), "open_times": 0,
                    })
                dt_df = df[df['pct_chg'] <= -9.9]
                for _, row in dt_df.nlargest(10, 'pct_chg').iterrows():
                    limit_down_list.append({
                        "ts_code": row.get('ts_code', ''), "name": name_map.get(row.get('ts_code', ''), ''),
                        "pct_chg": round(row.get('pct_chg', 0), 2),
                    })
            
            limit_pools = {"up_count": market_snapshot["limit_up_count"], "down_count": market_snapshot["limit_down_count"],
                "continue_stats": continue_stats, "sector_heat": sector_heat,
                "limit_up_list": limit_up_list, "limit_down_list": limit_down_list}
            
            result_data = {
                "status": "debug", "market_snapshot": market_snapshot, "sentiment": sentiment,
                "candidates": candidates[:30], "strategy_groups": strategy_groups[:6],
                "auction_signals": [], "top_gainers": top_gainers[:10],
                "historical_hit_rate": historical_hit_rate, "blocked_reasons": {},
                "funnel": funnel, "is_simulated": True, "cache_source": "mongodb_offline",
                "limit_pools": limit_pools, "position_gaps": [],
            }
            result_data["analysis"] = _build_premarket_analysis(
                result_data["market_snapshot"], result_data["sentiment"], result_data["limit_pools"],
                result_data["position_gaps"], result_data["candidates"], result_data["strategy_groups"], result_data["historical_hit_rate"])
            return _sanitize({"success": True, "data": result_data})
        except Exception as e:
            logger.error(f"[premarket-sim] offline模式失败: {e}")
            return {"success": False, "message": f"获取盘前数据失败: {e}"}
    
    # ===== 用daily_factors_df填充市场快照(不依赖realtime_cache) =====
    market_snapshot = {"up_count": 0, "down_count": 0, "flat_count": 0, 
                       "limit_up_count": 0, "limit_down_count": 0,
                       "avg_pct_chg": 0, "volume_ratio_gt2": 0, "total_stocks": 0,
                       "data_date": None}
    
    # 优先用realtime_cache(交易时间有实时行情)
    cache_source = "realtime"
    if scanner._realtime_cache and len(scanner._realtime_cache) > 100:
        pct_list = []
        for ts_code, rt in scanner._realtime_cache.items():
            pct = rt.get("pct_chg", 0) or 0
            pct_list.append(pct)
            if pct > 0: market_snapshot["up_count"] += 1
            elif pct < 0: market_snapshot["down_count"] += 1
            else: market_snapshot["flat_count"] += 1
            if pct >= 9.9: market_snapshot["limit_up_count"] += 1
            if pct <= -9.9: market_snapshot["limit_down_count"] += 1
            if (rt.get("volume_ratio") or 0) >= 2: market_snapshot["volume_ratio_gt2"] += 1
        market_snapshot["total_stocks"] = len(pct_list)
        market_snapshot["avg_pct_chg"] = round(sum(pct_list) / len(pct_list), 2) if pct_list else 0
    elif scanner._daily_factors_df is not None and len(scanner._daily_factors_df) > 0:
        # 用日级因子填充(非交易时间)
        cache_source = "daily_factors"
        df = scanner._daily_factors_df
        if 'pct_chg' in df.columns:
            pcts = df['pct_chg'].dropna()
            market_snapshot["up_count"] = int((pcts > 0).sum())
            market_snapshot["down_count"] = int((pcts < 0).sum())
            market_snapshot["flat_count"] = int((pcts == 0).sum())
            market_snapshot["limit_up_count"] = int((pcts >= 9.9).sum())
            market_snapshot["limit_down_count"] = int((pcts <= -9.9).sum())
            market_snapshot["avg_pct_chg"] = round(float(pcts.mean()), 2)
            market_snapshot["total_stocks"] = len(pcts)
        if 'volume_ratio' in df.columns:
            market_snapshot["volume_ratio_gt2"] = int((df['volume_ratio'].fillna(0) >= 2).sum())
        # 标记数据日期(从MongoDB读最新日期)
        if not market_snapshot.get("data_date") and mongo_manager.is_initialized:
            try:
                latest = await mongo_manager.db["stock_daily_ak_full"].find_one(
                    {"trade_date": {"$exists": True}}, sort=[("trade_date", -1)],
                    projection={"trade_date": 1}
                )
                if latest and latest.get("trade_date"):
                    market_snapshot["data_date"] = str(latest["trade_date"])
            except Exception:
                pass
    
    # ===== 情绪(从MongoDB读最新) =====
    sentiment = {"score": 50, "period": "chaos", "position_ratio": 0.5, "phase_name": "震荡"}
    _period_map = {"RISING": "高潮", "DIFFERENTIATION": "分化",
                     "CHAOS": "震荡", "BEARISH": "冰点",
                     # 小写英文(来自live_filter_pipeline._calc_sentiment)
                     "rising": "高潮", "differentiation": "分化",
                     "chaos": "震荡", "bearish": "冰点",
                     # 中文(来自emotion_cycle_manager._persist_sentiment_score)
                     "高潮": "高潮", "分化": "分化", "震荡": "震荡", "冰点": "冰点"}
    try:
        if hasattr(scanner, '_current_sentiment') and scanner._current_sentiment:
            raw_period = scanner._current_sentiment.get("period", "chaos")
            sentiment = {"score": scanner._current_sentiment.get("score", 50),
                         "period": raw_period,
                         "position_ratio": scanner._current_position_ratio or 0.5,
                         "phase_name": _period_map.get(raw_period, raw_period or "震荡")}
        # 尝试从MongoDB读最新情绪
        if sentiment.get("score") == 50 and mongo_manager.is_initialized:
            ss = await mongo_manager.db["sentiment_scores"].find_one(sort=[("updated_at", -1)])
            if ss:
                raw_period = ss.get("period", "chaos")
                sentiment = {"score": ss.get("score", 50), "period": raw_period,
                             "position_ratio": ss.get("position_ratio", 0.5),
                             "phase_name": _period_map.get(raw_period, raw_period or "震荡")}
    except Exception:
        pass
    
    # ===== 实际信号(来自9层筛选管道, 不是粗筛) =====
    candidates = []
    strategy_map = {}
    blocked_reasons = {}  # 被block的原因统计
    
    for sig in scanner._active_signals:
        s = sig.strategy or "system_force"
        c = {"ts_code": sig.ts_code,
             "stock_name": sig.stock_name or (scanner._stock_name_map.get(sig.ts_code, "") if hasattr(scanner, '_stock_name_map') else ""),
             "strategy": s,
             "pct_chg": sig.pct_chg or 0,
             "volume_ratio": sig.factors.get('volume_ratio', 0),
             "turnover_rate": sig.factors.get('turnover_rate', 0),
             "signal_status": sig.signal_status,
             "reason": sig.reason[:80] if sig.reason else '',}
        candidates.append(c)
        strategy_map.setdefault(s, []).append(c)
        
        # 统计blocked原因
        if sig.signal_status in ('blocked', 'skipped') and sig.reason:
            # 提取blocked的关键原因
            reason_key = sig.reason.split('|')[0].strip()[:30] if '|' in sig.reason else sig.reason[:30]
            blocked_reasons[reason_key] = blocked_reasons.get(reason_key, 0) + 1
    
    # ===== 漏斗统计(从scan_traces或时间线推断) =====
    funnel = {"total_scanned": 0, "strategy_candidates": 0, "after_pipeline": 0, "blocked": 0, "executed": 0}
    funnel["total_scanned"] = len(scanner._realtime_cache) if scanner._realtime_cache else (len(scanner._daily_factors_df) if scanner._daily_factors_df is not None else 0)
    funnel["strategy_candidates"] = len(candidates)
    funnel["after_pipeline"] = len([c for c in candidates if c["signal_status"] in ('new', 'executed')])
    funnel["blocked"] = len([c for c in candidates if c["signal_status"] in ('blocked', 'skipped', 'filtered')])
    funnel["executed"] = len([c for c in candidates if c["signal_status"] == 'executed'])
    
    # 如果active_signals为0, 用日级因子做粗筛预览(标注为preview)
    if not candidates and scanner._daily_factors_df is not None and len(scanner._daily_factors_df) > 0:
        df = scanner._daily_factors_df
        # 半路追涨Top10(涨幅+换手排序)
        if 'pct_chg' in df.columns:
            hc = df[(df['pct_chg'] >= 3) & (df['pct_chg'] <= 7)]
            if 'turnover_rate' in hc.columns:
                hc = hc.nlargest(10, 'turnover_rate')
            else:
                hc = hc.nlargest(10, 'pct_chg')
            for _, row in hc.iterrows():
                ts_code = row.get('ts_code', '')
                c = {"ts_code": ts_code, "stock_name": scanner._stock_name_map.get(ts_code, ''),
                     "strategy": "halfway_chase", "pct_chg": round(row.get('pct_chg', 0), 2),
                     "volume_ratio": round(row.get('volume_ratio', 0), 2),
                     "turnover_rate": round(row.get('turnover_rate', 0), 2),
                     "signal_status": "preview",
                     "reason": f"涨{row.get('pct_chg',0):.1f}% 换手{row.get('turnover_rate',0):.1f}% (粗筛Top10)"}
                candidates.append(c)
                strategy_map.setdefault("halfway_chase", []).append(c)
            funnel["strategy_candidates"] += len(hc)
        
        # 涨停Top5
        zt_df = df[df['pct_chg'] >= 9.9] if 'pct_chg' in df.columns else pd.DataFrame()
        zt = zt_df.nlargest(5, 'turnover_rate') if len(zt_df) > 0 and 'turnover_rate' in zt_df.columns else (zt_df.head(5) if len(zt_df) > 0 else pd.DataFrame())
        for _, row in zt.iterrows():
            ts_code = row.get('ts_code', '')
            c = {"ts_code": ts_code, "stock_name": scanner._stock_name_map.get(ts_code, ''),
                 "strategy": "first_limit_up", "pct_chg": round(row.get('pct_chg', 0), 2),
                 "volume_ratio": round(row.get('volume_ratio', 0), 2),
                 "turnover_rate": round(row.get('turnover_rate', 0), 2),
                 "signal_status": "preview",
                 "reason": f"涨停 {row.get('pct_chg',0):.1f}% 换手{row.get('turnover_rate',0):.1f}%"}
            candidates.append(c)
            strategy_map.setdefault("first_limit_up", []).append(c)
        funnel["strategy_candidates"] += len(zt)
    
    # ===== 策略分组 =====
    strategy_groups = []
    for s, group in strategy_map.items():
        avg_pct = sum(c['pct_chg'] for c in group) / len(group) if group else 0
        executed = sum(1 for c in group if c['signal_status'] == 'executed')
        blocked = sum(1 for c in group if c['signal_status'] in ('blocked', 'skipped', 'filtered'))
        strategy_groups.append({
            "strategy": s, "count": len(group), "executed": executed, "blocked": blocked,
            "avg_pct_chg": round(avg_pct, 2), "candidates": group[:15],
        })
    strategy_groups.sort(key=lambda x: x["count"], reverse=True)
    
    # ===== 历史命中率 =====
    historical_hit_rate = {}
    try:
        if mongo_manager.is_initialized:
            pipeline = [
                {"$match": {"side": "sell", "profit_pct": {"$ne": None}}},
                {"$group": {"_id": "$strategy", "total": {"$sum": 1}, 
                            "wins": {"$sum": {"$cond": [{"$gt": ["$profit_pct", 0]}, 1, 0]}}, 
                            "avg_profit": {"$avg": "$profit_pct"}}},
            ]
            # 【v2.9.97h-v4】使用aggregate_trades统一查询
            docs = await aggregate_trades(mongo_manager.db, pipeline, auto_filter=False)
            for doc in docs:
                s = doc["_id"] or "unknown"
                total = doc["total"] or 1
                historical_hit_rate[s] = {"total": total, "wins": doc["wins"], 
                    "win_rate": round(doc["wins"] / total * 100, 1), 
                    "avg_profit": round(doc.get("avg_profit", 0), 2)}
    except Exception:
        pass
    
    # ===== 涨幅TOP =====
    top_gainers = []
    if scanner._daily_factors_df is not None and len(scanner._daily_factors_df) > 0:
        df = scanner._daily_factors_df
        if 'pct_chg' in df.columns:
            top = df.nlargest(10, 'pct_chg')
            for _, row in top.iterrows():
                ts_code = row.get('ts_code', '')
                top_gainers.append({
                    "ts_code": ts_code, "name": scanner._stock_name_map.get(ts_code, ''),
                    "pct_chg": round(row.get('pct_chg', 0), 2),
                    "volume_ratio": round(row.get('volume_ratio', 0), 2),
                })
    
    result_data = {
        "status": "debug",
        "market_snapshot": market_snapshot,
        "sentiment": sentiment,
        "candidates": candidates[:30],
        "strategy_groups": strategy_groups[:6],
        "auction_signals": [],
        "top_gainers": top_gainers[:10],
        "historical_hit_rate": historical_hit_rate,
        "blocked_reasons": blocked_reasons,
        "funnel": funnel,
        "is_simulated": True,
        "cache_source": cache_source,
        "limit_pools": await _build_limit_pools(scanner),
        "position_gaps": _build_position_gaps(scanner),
    }
    result_data["analysis"] = _build_premarket_analysis(
        result_data["market_snapshot"], result_data["sentiment"], result_data["limit_pools"],
        result_data["position_gaps"], result_data["candidates"], result_data["strategy_groups"], result_data["historical_hit_rate"])
    
    return _sanitize({"success": True, "data": result_data})



@router.get("/debug/strategy-filter")
async def get_strategy_filter_detail():
    """获取策略筛选层的详细trace
    
    返回每个策略:
    - 原始候选数(满足条件的)
    - 过滤原因(哪些条件不满足)
    - 最终候选数
    
    用于调试策略筛选条件是否合理
    """
    scanner = await _get_scanner()
    
    # 从活跃信号的layer_trace中提取策略筛选信息
    strategy_details = {}
    for sig in scanner._active_signals:
        l6 = sig.layer_trace.get("L6_strategy", {})
        if l6:
            strategy_key = l6.get("strategy", sig.strategy)
            if strategy_key not in strategy_details:
                strategy_details[strategy_key] = {
                    "strategy": strategy_key,
                    "strategy_name": l6.get("strategy_name", sig.strategy_name),
                    "candidates_found": 0,
                    "conditions_applied": l6.get("conditions_applied", []),
                    "signals": [],
                }
            strategy_details[strategy_key]["candidates_found"] += 1
            strategy_details[strategy_key]["signals"].append({
                "ts_code": sig.ts_code,
                "stock_name": sig.stock_name,
                "pct_chg": sig.pct_chg,
                "volume_ratio": sig.volume_ratio,
                "turnover_rate": sig.turnover_rate,
                "reason": sig.reason,
            })
    
    # 策略配置
    from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS
    configs = {}
    for key, cfg in STRATEGY_CONFIGS.items():
        effective = scanner._get_effective_strategy_config(key)
        configs[key] = {
            "name": effective.get("name", ""),
            "enabled": effective.get("enabled", True),
            "params": effective.get("params", {}),
            "riskParams": effective.get("riskParams", {}),
        }
    
    return {
        "success": True,
        "data": {
            "strategy_details": strategy_details,
            "strategy_configs": configs,
        }
    }


import time



@router.put("/debug/strategy-hot-update/{strategy_key}")
async def strategy_hot_update(strategy_key: str, updates: Dict[str, Any] = {}):
    """策略参数热更新(无需重启scanner)
    
    updates格式: {"params": {"min_rise_pct": 0.05}, "riskParams": {"stop_loss_pct": 0.03}, "enabled": True}
    下次扫描时自动生效。
    
    注意: 仅影响内存配置, 不持久化到数据库。重启后恢复默认。
    """
    scanner = await _get_scanner()
    scanner.update_strategy_config(strategy_key, updates)
    
    # 返回更新后的配置
    effective = scanner._get_effective_strategy_config(strategy_key)
    return {
        "success": True,
        "data": {
            "strategy_key": strategy_key,
            "effective_config": effective,
            "message": f"策略{strategy_key}参数已热更新, 下次扫描生效",
        }
    }


# ==================== 交易终止增强 ====================

class PartialSellRequest(BaseModel):
    ts_code: str
    quantity: int = 0  # 0=全部卖出
    reason: str = ""


