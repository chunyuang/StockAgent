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
from nodes.web.api.scanner_system import _build_limit_pools, _build_position_gaps, _build_premarket_analysis

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
    
    # 5. 从MongoDB回退(收盘后/非交易时间)
    try:
        from core.managers import mongo_manager
        if mongo_manager.is_initialized:
            db = mongo_manager.db
            # 最新日线
            daily = await db["stock_daily_ak_full"].find_one(
                {"ts_code": ts_code},
                {"_id": 0, "trade_date": 1, "close": 1, "pct_chg": 1, "vol": 1, "open": 1, "high": 1, "low": 1, "pre_close": 1},
                sort=[("trade_date", -1)]
            )
            if daily and daily.get("close", 0) > 0:
                # 补充名称
                name = ""
                basic = await db["stock_basic"].find_one(
                    {"ts_code": ts_code}, {"_id": 0, "name": 1}
                )
                if basic:
                    name = basic.get("name", "")
                # 补充换手率/量比
                turnover = 0
                dbasic = await db["daily_basic"].find_one(
                    {"ts_code": ts_code},
                    {"_id": 0, "turn": 1, "volume_ratio": 1},
                    sort=[("trade_date", -1)]
                )
                if dbasic:
                    turnover = dbasic.get("turn", 0) or 0
                return _sanitize({
                    "success": True,
                    "data": {
                        "ts_code": ts_code,
                        "name": name,
                        "price": daily["close"],
                        "pct_chg": daily.get("pct_chg", 0),
                        "volume_ratio": 0,
                        "turnover_rate": turnover,
                        "open": daily.get("open", 0),
                        "high": daily.get("high", 0),
                        "low": daily.get("low", 0),
                        "pre_close": daily.get("pre_close", 0),
                        "trade_date": daily.get("trade_date", 0),
                        "source": "mongodb",
                    },
                })
    except Exception as e:
        logger.warning(f"[QUOTE] MongoDB回退失败: {e}")
    
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
              "L7_ranking", "L8_position", "L9_execute"]
    
    # 先清理None值(旧数据可能没有input/output字段)
    # 兼容旧数据: total/passed -> input/output映射
    for layer in layers:
        ld = summary.get(layer)
        if isinstance(ld, dict):
            for k in ["input", "output", "rejected", "passed", "total"]:
                if ld.get(k) is None:
                    ld[k] = 0
            # 旧数据用total/passed, 前端期望input/output
            if ld.get("input", 0) == 0 and ld.get("total", 0) > 0:
                ld["input"] = ld["total"]
            if ld.get("output", 0) == 0 and ld.get("passed", 0) > 0:
                ld["output"] = ld["passed"]
    
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
            {"$sort": {"_id": -1}}
        ]
        results = await mongo_manager.db["scan_traces"].aggregate(pipeline).to_list(None)
        dates = [{"date": str(r["_id"]), "count": r["count"], "is_debug": r.get("is_debug", False)} for r in results]
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
            # scan_traces.trade_date is stored as string "YYYYMMDD"
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
        
        try:
            body = await request.json()
        except Exception:
            body = {}
        
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
    try:
        import time, psutil
        scanner = await _get_scanner()
        scanner_running = scanner is not None and getattr(scanner, '_is_running', False)
        # 【v2.9.80守卫】scanner未运行时不访问scanner属性
        uptime_seconds = 0
        if scanner_running:
            try:
                start_time = getattr(scanner, '_start_time', None)
                if start_time and start_time > 0:
                    uptime_seconds = time.time() - start_time
            except Exception:
                pass
        scanner_hb = {
            "is_running": scanner_running,
            "uptime_seconds": round(uptime_seconds, 0),
        }
        realtime_count = 0
        if scanner_running:
            try:
                cache = getattr(scanner, '_realtime_cache', None)
                realtime_count = len(cache) if cache else 0
            except Exception:
                pass
        data_sources = [{"name": "eastmoney", "available": True, "stocks": realtime_count, "note": "免费无限流"}]

        mongo_status = {"connected": False}
        try:
            from core.managers import mongo_manager
            if mongo_manager.is_initialized:
                coll_names = await mongo_manager.db.list_collection_names()
                mongo_status = {"connected": True, "collections": len(coll_names)}
        except Exception:
            pass

        redis_status = {"connected": False}
        try:
            # 【v2.9.81巡检修复】Redis健康检测不应依赖scanner_running
            # 优先用redis_manager直连，scanner未运行时也能检测Redis状态
            from core.managers.redis_manager import redis_manager
            if redis_manager.is_initialized and redis_manager._client:
                await redis_manager._client.ping()
                redis_status = {"connected": True}
            elif scanner_running:
                redis_obj = getattr(scanner, '_redis', None)
                if redis_obj:
                    await redis_obj.ping()
                    redis_status = {"connected": True}
        except Exception:
            pass

        # WebSocket状态(从Redis WS桥获取连接数)
        ws_status = {"connected": False, "client_count": 0}
        try:
            from nodes.web.redis_ws_bridge import RedisWSBridge
            bridge = RedisWSBridge._instance
            if bridge:
                ws_status = {"connected": True, "client_count": getattr(bridge, '_client_count', 0)}
        except Exception:
            pass

        alerts = []
        try:
            from core.managers import mongo_manager
            # 【v2.9.82修复】查询条件兼容: 有level字段的用level过滤，
            # 无level字段的用action/event_type中的critical/warning关键词匹配
            alerts_cursor = mongo_manager.db["audit_log"].find(
                {"$or": [
                    {"level": {"$in": ["warning", "critical"]}},
                    {"action": {"$in": ["circuit_breaker", "scanner_error", "risk_sell_executed"]}},
                    {"event_type": {"$in": ["circuit_breaker", "scanner_error", "risk_sell_executed"]}},
                ]},
                {"_id": 0}
            ).sort("timestamp", -1).limit(10)
            async for doc in alerts_cursor:
                alerts.append(doc)
        except Exception:
            pass

        return _sanitize({"success": True, "data": {
            "scanner": scanner_hb, "data_sources": data_sources,
            "mongo": mongo_status, "redis": redis_status,
            "websocket": ws_status,
            "system": {"cpu_pct": psutil.cpu_percent(interval=0.1), "memory_pct": psutil.virtual_memory().percent, "disk_pct": psutil.disk_usage('/').percent},
            "alerts": alerts, "health_score": 50,
        }})
    except Exception as e:
        return {"success": False, "message": str(e)}



@router.get("/audit-log")
async def get_audit_log(limit: int = 50):
    """操作审计日志
    
    字段规范(v2.9.80):
    - timestamp: ISO格式字符串(前端显示用)
    - action: 操作类型
    - reason: 操作原因
    - ts_code/stock_name/strategy: 标准字段
    """
    try:
        from core.managers import mongo_manager
        # mongo_manager auto-connected
        logs = []
        # 【v2.9.83修复】旧数据兼容: sort时优先timestamp，fallback到time/time_str
        # MongoDB复合排序确保新/旧数据都正确排列
        async for doc in mongo_manager.db["audit_log"].find(
            {}, {"_id": 0}
        ).sort(
            [("timestamp", -1), ("time", -1), ("time_str", -1)]
        ).limit(limit):
            # 统一字段: 确保timestamp/action/reason字段存在
            ts = doc.get("timestamp", "")
            if hasattr(ts, 'isoformat'):
                # datetime对象 → ISO字符串
                doc["timestamp"] = ts.isoformat()
            elif isinstance(ts, (int, float)):
                # float epoch → ISO字符串
                from datetime import datetime as _dt
                doc["timestamp"] = _dt.fromtimestamp(ts).isoformat()
            elif not ts:
                # 【v2.9.83修复】旧数据time字段→timestamp
                old_time = doc.get("time", "") or doc.get("time_str", "")
                if old_time:
                    doc["timestamp"] = str(old_time)
                else:
                    doc["timestamp"] = ""
            # 统一action字段: event_type → action
            if not doc.get("action") and doc.get("event_type"):
                doc["action"] = doc["event_type"]
            # 统一reason字段: detail/reason → reason
            if not doc.get("reason"):
                data = doc.get("data", {})
                if isinstance(data, dict):
                    doc["reason"] = data.get("reason", "") or data.get("message", "") or data.get("detail", "")
                elif isinstance(data, str):
                    doc["reason"] = data[:100]
                # 【v2.9.83修复】顶层detail字段→reason
                if not doc.get("reason") and doc.get("detail"):
                    doc["reason"] = doc["detail"]
            logs.append(doc)
        return _sanitize({"success": True, "data": logs})
    except Exception as e:
        return {"success": False, "message": str(e)}


# ==================== V2.8: EventBus统计与历史 ====================


@router.get("/premarket-status")
async def get_premarket_status(date: str = None):
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
        from datetime import datetime
        now = datetime.now()
        ct = now.strftime("%H:%M")
        
        if not scanner:
            # Scanner未运行: 从MongoDB回退构建盘前数据
            from core.managers import mongo_manager
            if mongo_manager.is_initialized:
                db = mongo_manager.db
                import pandas as pd
                today = now.strftime("%Y%m%d")
                
                # 尝试取今天数据, 无则取最近交易日
                target_date = today
                docs = []
                async for doc in db["stock_daily_ak_full"].find(
                    {"trade_date": int(today)},
                    {"ts_code": 1, "pct_chg": 1, "close": 1, "vol": 1, "amount": 1}
                ):
                    docs.append(doc)
                
                if not docs:
                    latest = await db["stock_daily_ak_full"].find_one(
                        {}, sort=[("trade_date", -1)], projection={"trade_date": 1}
                    )
                    if latest:
                        target_date = str(latest["trade_date"])
                        async for doc in db["stock_daily_ak_full"].find(
                            {"trade_date": int(target_date)},
                            {"ts_code": 1, "pct_chg": 1, "close": 1, "vol": 1, "amount": 1}
                        ):
                            docs.append(doc)
                
                if docs:
                    df = pd.DataFrame(docs)
                    pcts = df['pct_chg'].dropna() if 'pct_chg' in df.columns else pd.Series()
                    market_snapshot = {
                        "up_count": int((pcts > 0).sum()) if len(pcts) else 0,
                        "down_count": int((pcts < 0).sum()) if len(pcts) else 0,
                        "flat_count": int((pcts == 0).sum()) if len(pcts) else 0,
                        "limit_up_count": int((pcts >= 9.9).sum()) if len(pcts) else 0,
                        "limit_down_count": int((pcts <= -9.9).sum()) if len(pcts) else 0,
                        "avg_pct_chg": round(float(pcts.mean()), 2) if len(pcts) else 0,
                        "total_stocks": len(docs),
                        "data_date": target_date,
                    }
                    
                    # 构建candidates
                    candidates = []
                    strategy_map = {}
                    if 'pct_chg' in df.columns:
                        hc = df[(df['pct_chg'] >= 3) & (df['pct_chg'] <= 7)].nlargest(10, 'pct_chg')
                        for _, row in hc.iterrows():
                            c = {"ts_code": row.get('ts_code', ''), "stock_name": '',
                                 "strategy": "halfway_chase", "pct_chg": round(row.get('pct_chg', 0), 2),
                                 "signal_status": "preview",
                                 "reason": f"涨{row.get('pct_chg',0):.1f}% (Top10)"}
                            candidates.append(c)
                            strategy_map.setdefault("halfway_chase", []).append(c)
                        
                        fu = df[df['pct_chg'] >= 9.9].nlargest(10, 'pct_chg')
                        for _, row in fu.iterrows():
                            c = {"ts_code": row.get('ts_code', ''), "stock_name": '',
                                 "strategy": "first_limit_up", "pct_chg": round(row.get('pct_chg', 0), 2),
                                 "signal_status": "preview",
                                 "reason": f"涨停{row.get('pct_chg',0):.1f}%"}
                            candidates.append(c)
                            strategy_map.setdefault("first_limit_up", []).append(c)
                    
                    strategy_groups = []
                    for strat, items in strategy_map.items():
                        strategy_groups.append({"strategy": strat, "candidates": items, "count": len(items)})
                    
                    # 【v2.9.83修复】scanner未运行时补全缺失字段: stock_name/phase_name/volume_ratio_gt2/limit_pools/analysis
                    # 1. 填充股票名称(从stock_basic集合获取)
                    ts_codes = [c['ts_code'] for c in candidates if c.get('ts_code')]
                    name_map = {}
                    if ts_codes:
                        async for ndoc in db["stock_basic"].find(
                            {"ts_code": {"$in": ts_codes}},
                            {"ts_code": 1, "name": 1}
                        ):
                            if ndoc.get("name"):
                                name_map[ndoc["ts_code"]] = ndoc["name"]
                    for c in candidates:
                        if not c.get("stock_name"):
                            c["stock_name"] = name_map.get(c.get('ts_code', ''), '')
                    
                    # 2. 补volume_ratio_gt2(日线无此字段,标0)
                    market_snapshot["volume_ratio_gt2"] = 0
                    
                    # 3. 情绪+phase_name双向映射
                    _period_map = {"RISING": "高潮", "DIFFERENTIATION": "分化",
                                   "CHAOS": "震荡", "BEARISH": "冰点",
                                   "rising": "高潮", "differentiation": "分化",
                                   "chaos": "震荡", "bearish": "冰点",
                                   "高潮": "高潮", "分化": "分化", "震荡": "震荡", "冰点": "冰点"}
                    sent_doc = await db["sentiment_scores"].find_one({"trade_date": int(target_date)})
                    sentiment = {"score": 50, "period": "chaos", "position_ratio": 0.5, "phase_name": "震荡"}
                    if sent_doc:
                        raw_period = sent_doc.get("period", "chaos")
                        sentiment = {"score": sent_doc.get("score", 50), "period": raw_period,
                                     "position_ratio": sent_doc.get("position_ratio", 0.5),
                                     "phase_name": _period_map.get(raw_period, raw_period or "震荡")}
                    
                    # 4. 涨停池(从limit_list集合)
                    limit_pools = {"up_count": 0, "down_count": 0, "limit_up_list": [], "continue_stats": {}, "sector_heat": []}
                    try:
                        from nodes.web.api.scanner_system import _build_name_industry_maps, _aggregate_limit_stats
                        ll_doc = await db["limit_list"].find_one({"limit": "U"}, sort=[("trade_date", -1)])
                        if ll_doc:
                            ll_td = ll_doc["trade_date"]
                            ll_name_map, ll_industry_map = await _build_name_industry_maps()
                            ll_docs = [d async for d in db["limit_list"].find({"trade_date": ll_td, "limit": "U"}, {"_id": 0})]
                            ll_ups, ll_continue, ll_sectors = _aggregate_limit_stats(ll_docs, ll_name_map, ll_industry_map)
                            ll_down = await db["limit_list"].count_documents({"trade_date": ll_td, "limit": "D"})
                            limit_pools = {"up_count": len(ll_ups), "down_count": ll_down,
                                           "limit_up_list": ll_ups[:20], "continue_stats": dict(sorted(ll_continue.items())),
                                           "sector_heat": sorted([{"name": k, "count": v} for k, v in ll_sectors.items()], key=lambda x: x["count"], reverse=True)[:8]}
                            market_snapshot["limit_up_count"] = len(ll_ups)
                            market_snapshot["limit_down_count"] = ll_down
                    except Exception:
                        pass
                    
                    # 5. 策略分组补全(executed/blocked/avg_pct_chg)
                    strategy_groups = []
                    for strat, items in strategy_map.items():
                        avg_pct = sum(c['pct_chg'] for c in items) / len(items) if items else 0
                        strategy_groups.append({"strategy": strat, "candidates": items, "count": len(items),
                                                "executed": 0, "blocked": 0, "avg_pct_chg": round(avg_pct, 2)})
                    
                    # 6. 盘前研判
                    analysis = None
                    try:
                        analysis = _build_premarket_analysis(
                            market_snapshot, sentiment, limit_pools, [], candidates, strategy_groups, {})
                    except Exception:
                        pass
                    
                    day_of_week = now.weekday()
                    if day_of_week < 5:
                        if "09:15" <= ct < "09:25":
                            status = "active"
                        else:
                            status = "ended"
                    else:
                        status = "debug"
                    
                    return _sanitize({"success": True, "data": {
                        "status": status,
                        "market_snapshot": market_snapshot,
                        "sentiment": sentiment,
                        "candidates": candidates[:30],
                        "strategy_groups": strategy_groups[:6],
                        "auction_signals": [],
                        "top_gainers": candidates[:15],
                        "historical_hit_rate": {},
                        "limit_pools": limit_pools,
                        "position_gaps": [],
                        "analysis": analysis,
                    }})
            return {"success": True, "data": {"status": "off", "candidates": [], "auction_signals": [], "top_gainers": [], "strategy_groups": [], "market_snapshot": {}, "sentiment": {}, "historical_hit_rate": {}}}
        
        from datetime import datetime
        now = datetime.now()
        ct = now.strftime("%H:%M")
        
        # 判断盘前状态
        if not scanner._is_running:
            # Scanner实例存在但未运行: 交易日显示ended(可查看预选数据)
            day_of_week = now.weekday()
            status = "ended" if day_of_week < 5 else "debug"
        elif "09:00" <= ct < "09:15":
            status = "waiting"
        elif "09:15" <= ct < "09:25":
            status = "active"
        elif "09:25" <= ct < "09:30":
            status = "ended"
        else:
            # 竞价时段外但scanner运行中: 交易日也显示ended
            day_of_week = now.weekday()
            status = "ended" if day_of_week < 5 else "off"
        
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
                             "phase_name": {"RISING": "高潮", "DIFFERENTIATION": "分化", "CHAOS": "震荡", "BEARISH": "冰点",
                                              "rising": "高潮", "differentiation": "分化", "chaos": "震荡", "bearish": "冰点",
                                              "高潮": "高潮", "分化": "分化", "震荡": "震荡", "冰点": "冰点"}.get(scanner._current_sentiment.get("period", ""), "震荡")}
        except Exception:
            pass
        
        # ===== 候选列表(带完整因子) =====
        candidates = []
        strategy_map = {}  # strategy -> [candidates]
        for sig in scanner._active_signals:
            s = sig.strategy or "system_force"
            c = {
                "ts_code": sig.ts_code,
                "stock_name": sig.stock_name or (scanner._stock_name_map.get(sig.ts_code, "") if hasattr(scanner, '_stock_name_map') else ""),
                "strategy": s,
                "pct_chg": sig.pct_chg or 0,
                "auction_pct": sig.factors.get('auction_pct'),
                "volume_ratio": sig.factors.get('volume_ratio', 0),
                "turnover_rate": sig.factors.get('turnover_rate', 0),
                "signal_status": sig.signal_status,
                "reason": sig.reason[:80] if sig.reason else '',
            }
            candidates.append(c)
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
        try:
            body = await request.json()
        except Exception:
            body = {}
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

