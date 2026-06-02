#!/usr/bin/env python3
"""Scanner API - 扫描追踪/盘前/行情/风控"""
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

router = APIRouter(prefix="/scanner", tags=["扫描追踪/盘前/行情/风控"])


@router.get("/quote/{ts_code}")
async def get_realtime_quote(ts_code: str):
    """获取单只股票实时行情(用于手动下单自动填充)
    
    优先从scanner缓存获取, 缓存未命中则从东方财富/必盈获取
    """
    scanner = await _get_scanner()
    
    # 1. 从scanner缓存获取
    if scanner._realtime_cache:
        rt = scanner._realtime_cache.get(ts_code, {})
        if rt and rt.get("price", 0) > 0:
            return _sanitize({
                "success": True,
                "data": {
                    "ts_code": ts_code,
                    "name": rt.get("name", ""),
                    "price": rt.get("price", 0),
                    "pct_chg": rt.get("pct_chg", 0),
                    "volume_ratio": rt.get("volume_ratio", 0),
                    "turnover_rate": rt.get("turnover_rate", 0),
                    "source": "cache",
                },
            })
    
    # 2. 从broker缓存获取
    if scanner._broker and scanner._broker._realtime_prices:
        price = scanner._broker._realtime_prices.get(ts_code, 0)
        if price > 0:
            return _sanitize({
                "success": True,
                "data": {
                    "ts_code": ts_code,
                    "name": "",
                    "price": price,
                    "pct_chg": 0,
                    "source": "broker_cache",
                },
            })
    
    # 3. 从东方财富获取
    try:
        from nodes.market_monitor.data_source_router import DataSourceRouter
        router = DataSourceRouter()
        em_data = await router.fetch_eastmoney_snapshot([ts_code])
        if em_data and ts_code in em_data:
            rt = em_data[ts_code]
            return _sanitize({
                "success": True,
                "data": {
                    "ts_code": ts_code,
                    "name": rt.get("name", ""),
                    "price": rt.get("price", 0),
                    "pct_chg": rt.get("pct_chg", 0),
                    "volume_ratio": rt.get("volume_ratio", 0),
                    "turnover_rate": rt.get("turnover_rate", 0),
                    "source": "eastmoney",
                },
            })
    except Exception as e:
        logger.warning(f"[QUOTE] 东方财富获取失败: {e}")
    
    # 4. 从必盈获取
    try:
        from nodes.market_monitor.data_source_router import DataSourceRouter
        ds_router = DataSourceRouter()
        biying = ds_router.get_biying()
        if biying:
            # 必盈用纯数字代码
            dm = ts_code.split(".")[0]
            quote = await biying.get_realtime_quote(dm)
            if quote:
                price = float(quote.get("close", 0) if isinstance(quote, dict) else getattr(quote, 'close', 0))
                name = quote.get("name", "") if isinstance(quote, dict) else getattr(quote, 'name', '')
                pct = float(quote.get("pct_chg", 0) if isinstance(quote, dict) else getattr(quote, 'pct_chg', 0))
                if price > 0:
                    return _sanitize({
                        "success": True,
                        "data": {
                            "ts_code": ts_code,
                            "name": name,
                            "price": price,
                            "pct_chg": pct,
                            "source": "biying",
                        },
                    })
    except Exception as e:
        logger.warning(f"[QUOTE] 必盈获取失败: {e}")
    
    return {"success": False, "message": f"无法获取 {ts_code} 行情"}

# ==================== 【V50.1】扫描链路追踪 ====================

def _fix_funnel_summary(doc: dict):
    """修复旧数据漏斗: L2/L3/L6/L8不淘汰但output=0的bug
    
    旧版_build_trace_summary用passed计数,非淘汰层没人标记passed→output=0
    修复逻辑:
    1. 逐层传递: rejected=0的非淘汰层,output=input
    2. 修正断裂: 某层input=0但上层output>0 → input=上层output
    3. 修正output=0的断裂: 某层rejected=0但output=0且input=0 → output=prev_output
    """
    summary = doc.get("summary", {})
    if not summary:
        return
    
    layers = ["L1_force_empty", "L2_special_period", "L3_sentiment", 
              "L4_premarket", "L5_auction", "L6_strategy",
              "L7_ranking", "L8_position"]
    
    # 先清理None值(旧数据可能没有input/output字段)
    for layer in layers:
        ld = summary.get(layer)
        if isinstance(ld, dict):
            for k in ["input", "output", "rejected", "passed", "total"]:
                if ld.get(k) is None:
                    ld[k] = 0
    
    prev_output = 0
    for layer in layers:
        ld = summary.get(layer)
        if not isinstance(ld, dict):
            continue
        inp = ld.get("input", 0) or 0
        out = ld.get("output", 0) or 0
        rej = ld.get("rejected", 0) or 0
        
        # Step 1: 修正断裂input — 上层有output但本层input=0
        if inp == 0 and prev_output > 0:
            ld["input"] = prev_output
            inp = prev_output
        
        # Step 2: 不淘汰层(rejected=0): output=input
        if rej == 0:
            if inp > 0 and out != inp:
                ld["output"] = inp
            elif inp == 0 and prev_output > 0:
                # input还是0但上层有output → 本层也是非淘汰层
                ld["input"] = prev_output
                ld["output"] = prev_output
        
        prev_output = ld.get("output", 0)



@router.get("/scan-dates")
async def get_scan_trace_dates():
    """获取有扫描记录的日期列表（用于日期选择器标记）
    
    返回格式: [{"date": "YYYYMMDD", "is_debug": bool, "count": int}]
    非交易日标记is_debug=true，前端可区分显示
    """
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": []}
        pipeline = [
            {"$group": {
                "_id": "$trade_date",
                "count": {"$sum": 1},
                "is_debug": {"$max": {"$cond": [{"$eq": ["$is_debug", True]}, True, False]}}
            }},
            {"$sort": {"_id": 1}}
        ]
        results = await mongo_manager.db["scan_traces"].aggregate(pipeline).to_list(None)
        dates = [{"date": r["_id"], "count": r["count"], "is_debug": r.get("is_debug", False)} for r in results]
        return {"success": True, "data": dates}
    except Exception as e:
        return {"success": True, "data": [], "message": str(e)}



@router.get("/scan-traces")
async def get_scan_traces(date: str = None, limit: int = 10):
    """获取扫描链路追踪记录
    
    返回每次扫描的摘要信息，不含candidates详情（用于列表展示）
    点击单条记录时通过 /scan-traces/{scan_id} 获取详情
    
    Args:
        date: 指定日期(YYYYMMDD), 不传则返回最近N次
        limit: 返回最近N次扫描(默认10)
    """
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": [], "message": "MongoDB未连接"}
        
        query = {}
        if date:
            query["trade_date"] = date
        
        docs = []
        # 列表查询：排除candidates和rejected_summary字段，避免返回20MB+
        async for doc in mongo_manager.db["scan_traces"].find(
            query,
            {"candidates": 0, "rejected_summary": 0}  # 排除大字段
        ).sort("_id", -1).limit(limit):
            # 将_id转为scan_id供前端详情查询
            doc["scan_id"] = str(doc.pop("_id", ""))
            # 【v2.9.17:修复旧数据漏斗数字(L2/L3/L6/L8 output=0)】
            _fix_funnel_summary(doc)
            docs.append(doc)
        
        return {"success": True, "data": docs, "count": len(docs)}
    except Exception as e:
        return {"success": True, "data": [], "message": str(e)}



@router.get("/scan-traces/{scan_id}")
async def get_scan_trace_detail(scan_id: str, status: str = None, limit: int = 50, offset: int = 0):
    """获取单次扫描的详细追踪
    
    v2.9.7优化：
    - 默认只返回passed候选(不加载淘汰数据，避免卡顿)
    - rejected需要显式请求status=rejected
    - 支持分页offset+limit
    - rejected候选按rejection_layer分组统计(不展开列表)
    
    Args:
        scan_id: 扫描记录ID
        status: 过滤候选状态 (passed/rejected/summary), 默认passed
                summary=只返回分组统计不返回候选列表
        limit: 返回候选数量上限(默认50)
        offset: 偏移量(分页)
    """
    try:
        from core.managers import mongo_manager
        from bson import ObjectId
        if not mongo_manager.is_initialized:
            return {"success": True, "data": None}
        
        doc = await mongo_manager.db["scan_traces"].find_one({"_id": ObjectId(scan_id)})
        if doc:
            doc["scan_id"] = str(doc.pop("_id", ""))
            # 【v2.9.17:修复旧数据漏斗数字】
            _fix_funnel_summary(doc)
            
            candidates = doc.get("candidates", [])
            rejected = doc.get("rejected_summary", [])
            
            filter_status = status or "passed"  # 【v2.9.7: 默认只返回passed, 不加载rejected】
            
            if filter_status == "summary":
                # 【v2.9.7: 只返回统计, 不返回候选列表】
                # 按rejection_layer分组统计
                layer_stats = {}
                for r in rejected:
                    layer = r.get("rejection_layer", "unknown")
                    layer_stats[layer] = layer_stats.get(layer, 0) + 1
                doc["candidates"] = []
                doc["rejected_layer_stats"] = layer_stats
                doc.pop("rejected_summary", None)
            elif filter_status == "passed":
                doc["candidates"] = candidates[offset:offset + limit]
                doc.pop("rejected_summary", None)
            elif filter_status == "rejected":
                doc["candidates"] = rejected[offset:offset + limit]
                doc.pop("rejected_summary", None)
            else:
                # all: 先放passed，再放rejected，合计不超过limit
                combined = list(candidates[offset:offset + limit])
                remaining = limit - len(combined)
                if remaining > 0:
                    combined.extend(rejected[:remaining])
                doc["candidates"] = combined
                doc.pop("rejected_summary", None)
            
            # 添加分页信息
            doc["_pagination"] = {
                "passed_count": len(candidates),
                "rejected_count": len(rejected),
                "returned_count": len(doc["candidates"]),
                "filter": filter_status,
                "limit": limit,
                "offset": offset,
                "has_more_passed": offset + limit < len(candidates),
                "has_more_rejected": offset + limit < len(rejected),
            }
        
        return {"success": True, "data": doc}
    except Exception as e:
        return {"success": True, "data": None, "message": str(e)}



# ==================== V51: 风控看门狗 + 紧急平仓 + 参数中心 ====================


@router.get("/execution-quality")
async def get_execution_quality(date: str = None):
    """执行质量统计 — 从broker_orders计算真实滑点/延迟/成交率
    
    Args:
        date: YYYYMMDD, 不传则当天
    """
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": {}}
        db = mongo_manager.db
        
        if not date:
            import datetime
            date = datetime.datetime.now().strftime("%Y%m%d")
        
        # 从broker_orders聚合
        total_orders = 0
        filled_orders = 0
        rejected_orders = 0
        slippages = []
        delays = []
        
        async for doc in db["broker_orders"].find({"trade_date": date}):
            total_orders += 1
            if doc.get("status") == "filled":
                filled_orders += 1
                # 滑点: (filled_price - price) / price * 100
                target = doc.get("price", 0) or 0
                filled = doc.get("filled_price", 0) or 0
                if target > 0:
                    slip = (filled - target) / target * 100
                    slippages.append(slip)
                # 延迟: fill_time - create_time
                ct = doc.get("create_time", "")
                ft = doc.get("fill_time", "")
                if ct and ft:
                    try:
                        from datetime import datetime as dt
                        c = dt.fromisoformat(ct.replace("Z", "+00:00")) if "T" in ct else None
                        f = dt.fromisoformat(ft.replace("Z", "+00:00")) if "T" in ft else None
                        if c and f:
                            delays.append((f - c).total_seconds() * 1000)
                    except Exception: pass
            elif doc.get("status") in ("rejected", "cancelled"):
                rejected_orders += 1
        
        avg_slip = sum(slippages) / len(slippages) if slippages else 0
        avg_delay = sum(delays) / len(delays) if delays else 0
        fill_rate = filled_orders / max(total_orders, 1) * 100
        
        return {
            "success": True,
            "data": {
                "avg_slippage_pct": round(avg_slip, 3),
                "max_slippage_pct": round(max(slippages, key=abs), 3) if slippages else 0,
                "avg_fill_delay_ms": round(avg_delay, 0),
                "fill_rate_pct": round(fill_rate, 1),
                "rejected_orders": rejected_orders,
                "total_orders": total_orders,
                "filled_orders": filled_orders,
                "date": date,
            }
        }
    except Exception as e:
        return {"success": True, "data": {}, "message": str(e)}



@router.put("/trailing-stop/{ts_code}")
async def set_trailing_stop(ts_code: str, request: Request):
    """设置/修改单票追踪止损
    
    body: {
        "trailing_stop_pct": 0.03,  // 追踪止损比例(3%)
        "activated": true           // 是否激活
    }
    """
    try:
        scanner = _get_scanner_instance()
        if not scanner:
            return {"success": False, "message": "Scanner未运行"}
        
        body = await request.json()
        
        # 【v2.9.11:写操作必须在state_lock内完成】
        state_lock = getattr(scanner, '_state_lock', None)
        if state_lock:
            with state_lock:
                trailing = scanner._trailing_stops
                
                if ts_code not in trailing:
                    positions = scanner._broker.get_positions() if scanner._broker else []
                    pos = next((p for p in positions if p.ts_code == ts_code), None)
                    if not pos:
                        return {"success": False, "message": f"未找到持仓 {ts_code}"}
                    trailing[ts_code] = {
                        "high_price": pos.current_price,
                        "trailing_stop_pct": body.get("trailing_stop_pct", 0.03),
                        "activated": body.get("activated", True),
                        "stop_price": 0.0,
                    }
                else:
                    if "trailing_stop_pct" in body:
                        trailing[ts_code]["trailing_stop_pct"] = float(body["trailing_stop_pct"])
                    if "activated" in body:
                        trailing[ts_code]["activated"] = bool(body["activated"])
                
                # 重新计算止损价
                if trailing[ts_code].get("activated"):
                    high = trailing[ts_code].get("high_price", 0)
                    pct = trailing[ts_code].get("trailing_stop_pct", 0.03)
                    trailing[ts_code]["stop_price"] = high * (1 - pct)
                
                result_data = {"ts_code": ts_code, **trailing[ts_code]}
        else:
            trailing = scanner._trailing_stops
            
            if ts_code not in trailing:
                positions = scanner._broker.get_positions() if scanner._broker else []
                pos = next((p for p in positions if p.ts_code == ts_code), None)
                if not pos:
                    return {"success": False, "message": f"未找到持仓 {ts_code}"}
                trailing[ts_code] = {
                    "high_price": pos.current_price,
                    "trailing_stop_pct": body.get("trailing_stop_pct", 0.03),
                    "activated": body.get("activated", True),
                    "stop_price": 0.0,
                }
            else:
                if "trailing_stop_pct" in body:
                    trailing[ts_code]["trailing_stop_pct"] = float(body["trailing_stop_pct"])
                if "activated" in body:
                    trailing[ts_code]["activated"] = bool(body["activated"])
            
            if trailing[ts_code].get("activated"):
                high = trailing[ts_code].get("high_price", 0)
                pct = trailing[ts_code].get("trailing_stop_pct", 0.03)
                trailing[ts_code]["stop_price"] = high * (1 - pct)
            
            result_data = {"ts_code": ts_code, **trailing[ts_code]}
        
        return {
            "success": True,
            "data": {"ts_code": ts_code, **trailing[ts_code]}
        }
    except Exception as e:
        return {"success": False, "message": str(e)}



@router.get("/system-health-detail")
async def get_system_health_detail():
    """系统健康运维面板"""
    scanner = await _get_scanner()
    try:
        import time, psutil
        scanner_hb = {
            "is_running": getattr(scanner, '_is_running', False),
            "uptime_seconds": time.time() - scanner._start_time if hasattr(scanner, '_start_time') and scanner._start_time else 0,
        }
        data_sources = [{"name": "eastmoney", "available": True, "stocks": len(scanner._realtime_cache) if hasattr(scanner, '_realtime_cache') and scanner._realtime_cache else 0, "note": "免费无限流"}]

        mongo_status = {"connected": False}
        try:
            from core.managers import mongo_manager
            # mongo_manager auto-connected
            mongo_status = {"connected": True, "collections": len(await mongo_manager.db.list_collections())}
        except Exception:
            pass

        redis_status = {"connected": False}
        try:
            if hasattr(scanner, '_redis') and scanner._redis:
                await scanner._redis.ping()
                redis_status = {"connected": True}
        except Exception:
            pass

        alerts = []
        try:
            from core.managers import mongo_manager
            async for doc in mongo_manager.db["audit_log"].find({"level": {"$in": ["warning", "critical"]}}, {"_id": 0}).sort("timestamp", -1).limit(10):
                alerts.append(doc)
        except Exception:
            pass

        return _sanitize({"success": True, "data": {
            "scanner": scanner_hb, "data_sources": data_sources,
            "mongo": mongo_status, "redis": redis_status,
            "system": {"cpu_pct": psutil.cpu_percent(interval=0.1), "memory_pct": psutil.virtual_memory().percent, "disk_pct": psutil.disk_usage('/').percent},
            "alerts": alerts, "health_score": 50,
        }})
    except Exception as e:
        return {"success": False, "message": str(e)}



@router.get("/audit-log")
async def get_audit_log(limit: int = 50):
    """操作审计日志"""
    try:
        from core.managers import mongo_manager
        # mongo_manager auto-connected
        logs = []
        async for doc in mongo_manager.db["audit_log"].find({}, {"_id": 0}).sort("timestamp", -1).limit(limit):
            logs.append(doc)
        return _sanitize({"success": True, "data": logs})
    except Exception as e:
        return {"success": False, "message": str(e)}


# ==================== V2.8: EventBus统计与历史 ====================


@router.get("/premarket-status")
async def get_premarket_status():
    """盘前竞价增强版 — 策略分组+情绪背景+量能排名+历史统计
    
    Returns:
        status: waiting/active/ended/off
        market_snapshot: 全市场快照(涨跌分布/涨跌停数/量比分布)
        strategy_groups: 按策略分组的候选+统计
        candidates: 全量预选候选(带完整因子)
        auction_signals: 竞价过滤后的信号
        top_gainers: 竞价涨幅/量比排名
        sentiment: 当前情绪周期+仓位系数
        historical_hit_rate: 策略历史命中率
    """
    try:
        scanner = _get_scanner_instance()
        if not scanner:
            return {"success": True, "data": {"status": "off", "candidates": [], "auction_signals": [], "top_gainers": [], "strategy_groups": [], "market_snapshot": {}, "sentiment": {}, "historical_hit_rate": {}}}
        
        from datetime import datetime
        now = datetime.now()
        ct = now.strftime("%H:%M")
        
        # 判断盘前状态
        if not scanner._is_running:
            status = "off"
        elif "09:00" <= ct < "09:15":
            status = "waiting"
        elif "09:15" <= ct < "09:25":
            status = "active"
        elif "09:25" <= ct < "09:30":
            status = "ended"
        else:
            status = "off"
        
        # ===== 全市场快照 =====
        market_snapshot = {"up_count": 0, "down_count": 0, "flat_count": 0, "limit_up_count": 0, "limit_down_count": 0,
                           "avg_pct_chg": 0, "volume_ratio_gt2": 0, "total_stocks": 0}
        if scanner._realtime_cache:
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
        
        # ===== 情绪背景 =====
        sentiment = {"score": 50, "period": "chaos", "position_ratio": 0.5, "phase_name": "震荡"}
        try:
            if hasattr(scanner, '_current_sentiment') and scanner._current_sentiment:
                sentiment = {"score": scanner._current_sentiment.get("score", 50),
                             "period": scanner._current_sentiment.get("period", "chaos"),
                             "position_ratio": scanner._current_position_ratio or 0.5,
                             "phase_name": {"RISING": "高潮", "DIFFERENTIATION": "分化", "CHAOS": "震荡", "BEARISH": "冰点"}.get(scanner._current_sentiment.get("period", ""), "震荡")}
        except Exception:
            pass
        
        # ===== 候选列表(带完整因子) =====
        candidates = []
        strategy_map = {}  # strategy -> [candidates]
        for sig in scanner._active_signals:
            c = {
                "ts_code": sig.ts_code,
                "stock_name": sig.stock_name or (scanner._stock_name_map.get(sig.ts_code, "") if hasattr(scanner, '_stock_name_map') else ""),
                "strategy": sig.strategy,
                "pct_chg": sig.pct_chg or 0,
                "auction_pct": sig.factors.get('auction_pct'),
                "volume_ratio": sig.factors.get('volume_ratio', 0),
                "turnover_rate": sig.factors.get('turnover_rate', 0),
                "signal_status": sig.signal_status,
                "reason": sig.reason[:80] if sig.reason else '',
            }
            candidates.append(c)
            s = sig.strategy
            if s not in strategy_map:
                strategy_map[s] = []
            strategy_map[s].append(c)
        
        # ===== 策略分组统计 =====
        strategy_groups = []
        for s, group in strategy_map.items():
            avg_pct = sum(c['pct_chg'] for c in group) / len(group) if group else 0
            executed = sum(1 for c in group if c['signal_status'] == 'executed')
            strategy_groups.append({
                "strategy": s, "count": len(group), "executed": executed,
                "avg_pct_chg": round(avg_pct, 2), "candidates": group,
            })
        strategy_groups.sort(key=lambda x: x["count"], reverse=True)
        
        # ===== 竞价信号 =====
        auction_signals = []
        for sig in scanner._active_signals:
            if sig.signal_status in ('new', 'executed') and sig.factors:
                if sig.factors.get('auction_pct') is not None or sig.factors.get('is_auction'):
                    auction_signals.append({
                        "ts_code": sig.ts_code,
                        "stock_name": sig.stock_name or (scanner._stock_name_map.get(sig.ts_code, "") if hasattr(scanner, '_stock_name_map') else ""),
                        "strategy": sig.strategy,
                        "pct_chg": sig.pct_chg,
                        "volume_ratio": sig.factors.get('volume_ratio', 0),
                        "signal_status": sig.signal_status,
                    })
        
        # ===== 竞价涨幅排名 =====
        top_gainers = []
        if hasattr(scanner, '_limit_pools'):
            for item in scanner._limit_pools.get('limit_up', [])[:10]:
                top_gainers.append({
                    "ts_code": item.get('ts_code', ''),
                    "name": item.get('name', '') or (scanner._stock_name_map.get(item.get('ts_code', ''), '') if hasattr(scanner, '_stock_name_map') else ''),
                    "pct_chg": item.get('pct_chg', 0),
                    "volume_ratio": item.get('volume_ratio', 0),
                })
        
        # ===== 历史命中率(从MongoDB) =====
        historical_hit_rate = {}
        try:
            from core.managers import mongo_manager
            if mongo_manager.is_initialized:
                db = mongo_manager.db
                pipeline = [
                    {"$match": {"side": "sell", "profit_pct": {"$ne": None}}},
                    {"$group": {"_id": "$strategy", "total": {"$sum": 1}, "wins": {"$sum": {"$cond": [{"$gt": ["$profit_pct", 0]}, 1, 0]}}, "avg_profit": {"$avg": "$profit_pct"}}},
                ]
                async for doc in db["broker_orders"].aggregate(pipeline):
                    s = doc["_id"] or "unknown"
                    total = doc["total"] or 1
                    historical_hit_rate[s] = {"total": total, "wins": doc["wins"], "win_rate": round(doc["wins"] / total * 100, 1), "avg_profit": round(doc.get("avg_profit", 0), 2)}
        except Exception:
            pass
        
        data = {
            "status": status,
            "market_snapshot": market_snapshot,
            "sentiment": sentiment,
            "candidates": candidates[:30],
            "strategy_groups": strategy_groups[:6],
            "auction_signals": auction_signals,
            "top_gainers": top_gainers[:15],
            "historical_hit_rate": historical_hit_rate,
            "limit_pools": await _build_limit_pools(scanner),
            "position_gaps": _build_position_gaps(scanner),
        }
        data["analysis"] = _build_premarket_analysis(
            data["market_snapshot"], data["sentiment"], data["limit_pools"],
            data["position_gaps"], data["candidates"], data["strategy_groups"], data["historical_hit_rate"])
        return {"success": True, "data": data}
    except Exception as e:
        return {"success": True, "data": {"status": "off", "candidates": [], "auction_signals": [], "top_gainers": [], "strategy_groups": [], "market_snapshot": {}, "sentiment": {}, "historical_hit_rate": {}, "limit_pools": {}, "position_gaps": [], "analysis": None, "error": str(e)}}



@router.post("/run-backtest")
async def run_quick_backtest(request: Request):
    """一键回测: 在后台运行快速回测(2025Q1, 半路追涨), 结果写入backtest_result.json
    
    请求体: {"period": "2025Q1"}  # 可选, 默认2025Q1
    """
    try:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        period = body.get("period", "2025Q1")
        
        period_config = {
            "2025Q1": {"start": "20250101", "end": "20250331"},
            "2025H1": {"start": "20250101", "end": "20250630"},
            "2025": {"start": "20250101", "end": "20251231"},
            "recent3m": {"start": "20260301", "end": "20260531"},
        }
        
        config = period_config.get(period, period_config["2025Q1"])
        
        # 在后台运行回测
        import subprocess, os
        script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "scripts", "run_backtest_quick.py")
        
        # 使用subprocess启动后台回测
        result_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "results", "backtest_result.json")
        
        # 直接用PortfolioBacktester在asyncio中运行
        import asyncio
        
        async def _run_backtest():
            try:
                import sys, types
                BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                if BASE not in sys.path:
                    sys.path.insert(0, BASE)
                
                from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
                from core.managers.mongo_manager import mongo_manager
                
                await mongo_manager.initialize()
                
                bt = PortfolioBacktester()
                bt_config = {
                    "start_date": config["start"],
                    "end_date": config["end"],
                    "initial_cash": 1000000,
                    "strategies": ["halfway_chase", "limit_down_qiao", "dragon_head"],
                    "mode": "backtest",
                }
                result = await bt.run(bt_config)
                
                # 写入文件
                with open(result_file, 'w') as f:
                    json.dump(result, f, ensure_ascii=False, default=str)
                
                logger.info(f"[BACKTEST] Quick backtest completed: {result.get('total_return', 0):.2%}")
            except Exception as e:
                logger.error(f"[BACKTEST] Quick backtest failed: {e}")
        
        asyncio.create_task(_run_backtest())
        
        return {"success": True, "message": f"回测已启动({period}: {config['start']}~{config['end']}), 预计30-60秒完成", "period": period}
    except Exception as e:
        return {"success": False, "message": str(e)}


# ============================================================================
# P0+P1: 同区间回测对比 + 偏差归因
# ============================================================================

