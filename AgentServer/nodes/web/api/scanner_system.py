#!/usr/bin/env python3
"""Scanner API - 系统健康/守护/Stream"""
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

router = APIRouter(prefix="/scanner", tags=["系统健康/守护/Stream"])


def _build_strategy_checks(scanner) -> dict:
    """构建策略状态checks(基于信号产出)【v2.9.71提取】"""
    checks: Dict[str, dict] = {}
    for strategy_key in ["halfway_chase", "first_limit_up", "dragon_head", "limit_down_qiao"]:
        strategy_signals = [s for s in scanner._active_signals if s.strategy == strategy_key]
        total_signals = getattr(scanner, '_scan_count', 0)
        if total_signals > 0 and len(strategy_signals) > 0:
            checks[strategy_key] = {
                "status": "healthy",
                "value": f"{len(strategy_signals)}个活跃信号",
                "threshold": ">0",
                "message": "策略正常产出信号",
            }
        elif total_signals > 0:
            checks[strategy_key] = {
                "status": "unknown",
                "value": "无信号",
                "threshold": ">0",
                "message": "当前无信号(可能正常)",
            }
        else:
            checks[strategy_key] = {
                "status": "unknown",
                "value": "未扫描",
                "threshold": ">0",
                "message": "尚未执行扫描",
            }
    return checks


def _build_datasource_checks(scanner) -> tuple:
    """构建数据源checks+ds_list【v2.9.71提取】"""
    checks: Dict[str, dict] = {}
    ds_list: List[dict] = []
    data_router = getattr(scanner, '_data_router', None)
    if not data_router:
        return checks, ds_list
    for name, src in data_router._sources.items():
        status_info = src.get_status() if hasattr(src, 'get_status') else {}
        ds_list.append({
            "name": name,
            "available": status_info.get('available', True),
            "stocks": status_info.get('cached_stocks', 0),
            "calls": status_info.get('api_calls_today', 0),
            "limit": status_info.get('api_limit', 0),
        })
        checks[f"datasource_{name}"] = {
            "status": "healthy" if status_info.get('available', True) else "critical",
            "value": f"{status_info.get('cached_stocks', 0)}只",
            "threshold": "在线",
            "message": status_info.get('note', ''),
        }
    return checks, ds_list


def _build_risk_metrics(scanner) -> dict:
    """构建风控指标(回撤/持仓比/熔断/连续亏损)【v2.9.71提取】"""
    broker = scanner._broker
    acc = broker.account if broker else None
    total_assets = acc.total_assets if acc else 0
    market_value = acc.market_value if acc else 0
    daily_profit = acc.today_profit if acc else 0

    daily_drawdown = abs(min(0, daily_profit / total_assets * 100)) if total_assets > 0 else 0
    position_ratio = market_value / total_assets if total_assets > 0 else 0

    cb = getattr(scanner, '_circuit_breaker', None) or {}
    consecutive_losses = cb.get('consecutive_losses', 0) if isinstance(cb, dict) else 0
    trading_paused = cb.get('trading_paused', False) if isinstance(cb, dict) else False

    # 线程安全读取pending_sells
    state_lock = getattr(scanner, '_state_lock', None)
    if state_lock:
        with state_lock:
            pending_sells_count = len(scanner._pending_sells)
    else:
        pending_sells_count = len(getattr(scanner, '_pending_sells', {}))
    pending_sells_detail: List[dict] = []
    if pending_sells_count > 0 and hasattr(scanner, '_position_manager') and scanner._position_manager:
        pending_sells_detail = scanner._position_manager.get_pending_sells_summary()

    risk_metrics = {
        "daily_drawdown_pct": round(daily_drawdown, 2),
        "max_drawdown_pct": 5.0,
        "position_ratio": round(position_ratio, 3),
        "consecutive_losses": consecutive_losses,
        "max_consecutive_losses": 3,
    }
    circuit_breaker = {
        "trading_paused": trading_paused,
        "pause_reason": cb.get('pause_reason', '') if isinstance(cb, dict) else '',
        "consecutive_losses": consecutive_losses,
        "max_consecutive_losses": 3,
    }
    return {
        "daily_drawdown": daily_drawdown,
        "position_ratio": position_ratio,
        "consecutive_losses": consecutive_losses,
        "trading_paused": trading_paused,
        "pending_sells_count": pending_sells_count,
        "pending_sells_detail": pending_sells_detail,
        "risk_metrics": risk_metrics,
        "circuit_breaker": circuit_breaker,
    }


def _compute_overall_health(scanner_health: dict, risk: dict) -> dict:
    """合并scanner健康度+金融指标, 计算综合健康度【v2.9.71提取】"""
    dd = risk["daily_drawdown"]
    cl = risk["consecutive_losses"]
    tp = risk["trading_paused"]

    # 统一健康分数(0-100)
    base_score = {"green": 100, "yellow": 60, "red": 30}.get(scanner_health.get('status', 'red'), 30)
    health_score = base_score
    if dd >= 3: health_score -= 15
    if dd >= 5: health_score -= 20
    if cl >= 2: health_score -= 10
    if tp: health_score -= 25
    health_score = max(0, health_score)

    # 合并warnings
    merged_warnings = list(scanner_health.get('warnings', []))
    if dd >= 3: merged_warnings.append(f"日回撤{dd:.1f}%")
    if cl >= 2: merged_warnings.append(f"连续亏损{cl}次")
    if risk["pending_sells_count"] > 0: merged_warnings.append(f"{risk['pending_sells_count']}只跌停挂起")
    if tp: merged_warnings.append("熔断器已触发")

    # 综合状态
    overall = scanner_health.get('status', 'unknown')
    if dd >= 5 or tp: overall = 'critical'
    elif dd >= 3 or cl >= 2: overall = 'degraded'

    scan_lag = scanner_health.get('scan_lag_seconds', 999)
    risk_lag = scanner_health.get('risk_check_lag_seconds', 999)
    data_freshness = "green" if scan_lag < 60 and risk_lag < 5 else (
        "yellow" if scan_lag < 120 and risk_lag < 30 else "red")

    return {
        "overall": overall,
        "health_score": health_score,
        "data_freshness": data_freshness,
        "warnings": merged_warnings,
        "is_healthy": scanner_health.get('is_healthy', False) and dd < 3 and not tp,
    }


def _dead_health_response() -> dict:
    """Scanner未运行时的健康响应【v2.9.71提取】"""
    return {"success": True, "health": {
        "overall_status": "dead", "message": "Scanner未运行",
        "checks": {}, "circuit_breaker": {"trading_paused": False},
        "risk_metrics": {"daily_drawdown_pct": 0, "max_drawdown_pct": 5, "position_ratio": 0},
        "health_score": 0, "scan_lag_seconds": -1, "risk_check_lag_seconds": -1,
        "data_freshness": "red",
        "warnings": ["Scanner未运行"], "data_sources": [],
        "version": _get_version_info(),
    }}


def _build_scanner_health_dict(scanner) -> dict:
    """获取Scanner内置健康度(权威来源)【v2.9.71提取】"""
    import time as _time
    scan_lag = _time.time() - scanner._last_scan_ts if getattr(scanner, '_last_scan_ts', 0) > 0 else 999
    risk_lag = _time.time() - getattr(scanner, '_last_risk_check_ts', 0) if getattr(scanner, '_last_risk_check_ts', 0) > 0 else 999
    return scanner._compute_health_score() if hasattr(scanner, '_compute_health_score') else {
        "status": "unknown", "is_healthy": False, "scan_lag_seconds": scan_lag,
        "risk_check_lag_seconds": risk_lag, "quote_staleness_seconds": 999,
        "risk_thread_alive": False, "risk_thread_restarts": 0, "warnings": [],
    }, scan_lag, risk_lag


def _build_health_response(watchdog_status, checks, ds_list, risk, scanner_health, scan_lag, risk_lag, overall_h) -> dict:
    """构建最终health响应字典【v2.9.71提取】"""
    return {
        "success": True,
        "health": {
            **watchdog_status,
            "overall_status": overall_h["overall"],
            "checks": checks,
            "circuit_breaker": risk["circuit_breaker"],
            "risk_metrics": risk["risk_metrics"],
            "data_sources": ds_list,
            "health_score": overall_h["health_score"],
            "data_freshness": overall_h["data_freshness"],
            "scan_lag_seconds": round(scan_lag, 1),
            "risk_check_lag_seconds": round(risk_lag, 1),
            "warnings": overall_h["warnings"],
            "is_healthy": overall_h["is_healthy"],
            "scanner_health": scanner_health,
            "pending_sells_detail": risk["pending_sells_detail"],
            "risk_thread": {
                "alive": scanner_health.get('risk_thread_alive', False),
                "restarts": scanner_health.get('risk_thread_restarts', 0),
            },
            "daemon": _get_daemon_status(),
            "version": _get_version_info(),
        },
    }


@router.get("/health")
async def get_scanner_health():
    """获取风控看门狗健康状态
    
    返回:
    - overall_status: healthy/degraded/critical/dead
    - checks: 各项检查结果(心跳/信号产出/回撤/持仓/行情延迟/策略)
    - circuit_breaker: 熔断状态
    - risk_metrics: 风控指标(日回撤/持仓比/连续亏损)
    """
    try:
        scanner = _get_scanner_instance()
        if not scanner:
            return _dead_health_response()

        # 1. Watchdog基础状态
        watchdog = getattr(scanner, '_risk_watchdog', None)
        watchdog_status = watchdog.get_status() if watchdog else {
            "overall_status": "unknown", "checks": {}, "uptime_seconds": 0,
            "scanner_heartbeat_age": -1, "alert_count": 0,
        }
        checks = dict(watchdog_status.get("checks", {}))

        # 2. 策略+数据源checks
        checks.update(_build_strategy_checks(scanner))
        ds_checks, ds_list = _build_datasource_checks(scanner)
        checks.update(ds_checks)

        # 3. 风控指标
        risk = _build_risk_metrics(scanner)

        # 4. Scanner内置健康度(权威来源)
        scanner_health, scan_lag, risk_lag = _build_scanner_health_dict(scanner)

        # 5. 综合健康度
        overall_h = _compute_overall_health(scanner_health, risk)

        return _build_health_response(
            watchdog_status, checks, ds_list, risk, scanner_health, scan_lag, risk_lag, overall_h)
    except Exception as e:
        return {"success": True, "health": {"overall_status": "error", "message": str(e), "checks": {}}}


def _get_daemon_status() -> dict:
    """【v2.9.7】获取Daemon状态(如果可用)"""
    try:
        from nodes.market_monitor.scanner_daemon import ScannerDaemon
        daemon = ScannerDaemon._instance
        if daemon:
            return daemon.get_status()
    except Exception:
        pass
    return {"available": False}


# 【v2.9.10:版本信息缓存, 避免每次请求调git子进程】
_version_cache = {"value": None, "ts": 0}
_VERSION_CACHE_TTL = 300  # 5分钟缓存

# 【v2.9.10:设计文档版本常量, 与docs/MARKET_MONITOR_OPTIMIZATION_DESIGN.md保持同步】
_DESIGN_DOC_VERSION = "v2.9.71"
_BASELINE_TAG = "v2.8.0-backtest-ui-v2"

def _get_version_info() -> dict:
    """【Phase4.2】获取版本信息(部署验证) — v2.9.10:5分钟缓存+常量版本号"""
    import subprocess as _sp
    import time as _time
    now = _time.time()
    if _version_cache["value"] and (now - _version_cache["ts"]) < _VERSION_CACHE_TTL:
        return _version_cache["value"]
    try:
        git_hash = _sp.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=_sp.DEVNULL, timeout=3
        ).decode().strip()
    except Exception:
        git_hash = "unknown"
    try:
        git_branch = _sp.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=_sp.DEVNULL, timeout=3
        ).decode().strip()
    except Exception:
        git_branch = "unknown"
    result = {
        "git_hash": git_hash,
        "git_branch": git_branch,
        "design_doc_version": _DESIGN_DOC_VERSION,
        "baseline_tag": _BASELINE_TAG,
    }
    _version_cache["value"] = result
    _version_cache["ts"] = now
    return result



@router.get("/event-bus/stats")
async def get_event_bus_stats():
    """EventBus事件统计
    
    返回各事件的发布/处理/错误次数, 便于监控事件流健康度
    """
    try:
        scanner = _get_scanner_instance()
        if not scanner or not hasattr(scanner, 'event_bus'):
            return {"success": True, "stats": {}, "subscriber_count": 0,
                    "events": [], "enabled": False}
        
        bus = scanner.event_bus
        return _sanitize({
            "success": True,
            "stats": bus.get_stats(),
            "handler_latency": bus.get_handler_latency(),  # 【v2.9.7】
            "subscriber_count": sum(bus.handler_count(e) for e in bus.get_events()),
            "events": bus.get_events(),
            "enabled": bus._enabled,
        })
    except Exception as e:
        return {"success": False, "message": str(e)}



@router.get("/event-bus/history")
async def get_event_bus_history(event: str = None, limit: int = 50):
    """EventBus事件历史
    
    Args:
        event: 过滤特定事件类型(None=全部)
        limit: 最大返回条数(1-200)
    """
    try:
        limit = min(max(1, limit), 200)
        scanner = _get_scanner_instance()
        if not scanner or not hasattr(scanner, 'event_bus'):
            return {"success": True, "history": [], "total": 0}
        
        bus = scanner.event_bus
        history = bus.get_history(event=event, limit=limit)
        return _sanitize({
            "success": True,
            "history": history,
            "total": len(history),
        })
    except Exception as e:
        return {"success": False, "message": str(e)}



# ==================== 盘前竞价 + 逐笔归因 API ====================

async def _build_limit_pools(scanner) -> dict:
    """涨停池+连板分布+板块热力"""
    from core.managers import mongo_manager
    result = {"up_count": 0, "down_count": 0, "limit_up_list": [], "continue_stats": {}, "sector_heat": []}
    try:
        if not mongo_manager.is_initialized:
            return result
        db = mongo_manager.db
        # 最新交易日
        latest = await db["limit_list"].find_one(sort=[("trade_date", -1)])
        if not latest:
            return result
        td = latest["trade_date"]
        
        # 预加载stock_basic的name和industry
        name_map = {}
        industry_map = {}
        async for doc in db["stock_basic"].find({}, {"_id": 0, "ts_code": 1, "name": 1, "industry": 1}):
            name_map[doc["ts_code"]] = doc.get("name", "")
            industry_map[doc["ts_code"]] = doc.get("industry", "")
        # 也从scanner的缓存补
        if hasattr(scanner, '_stock_name_map') and scanner._stock_name_map:
            for k, v in scanner._stock_name_map.items():
                if v and not name_map.get(k):
                    name_map[k] = v
        
        # 涨停列表
        limit_ups = []
        sector_count = {}
        continue_count = {}
        async for doc in db["limit_list"].find({"trade_date": td, "limit": "U"}, {"_id": 0}):
            ts_code = doc.get("ts_code", "")
            name = doc.get("name", "") or name_map.get(ts_code, ts_code[:6])
            industry = industry_map.get(ts_code, doc.get("sector", ""))
            limit_ups.append({"ts_code": ts_code, "name": name,
                              "open_times": doc.get("open_times", 0), "limit_times": doc.get("limit_times", 1),
                              "first_time": doc.get("first_time", ""), "sector": industry})
            # 连板统计
            lt = doc.get("limit_times", 1) or 1
            continue_count[str(lt)] = continue_count.get(str(lt), 0) + 1
            # 板块统计
            if industry:
                sector_count[industry] = sector_count.get(industry, 0) + 1
        
        down_count = await db["limit_list"].count_documents({"trade_date": td, "limit": "D"})
        
        result["up_count"] = len(limit_ups)
        result["down_count"] = down_count
        result["limit_up_list"] = limit_ups[:30]
        result["continue_stats"] = dict(sorted(continue_count.items()))
        result["sector_heat"] = sorted([{"name": k, "count": v} for k, v in sector_count.items()], key=lambda x: x["count"], reverse=True)[:10]
        result["trade_date"] = str(td)
    except Exception:
        pass
    return result

def _build_position_gaps(scanner) -> list:
    """持仓竞价跳空影响"""
    gaps = []
    try:
        if not scanner._broker or not scanner._realtime_cache:
            return gaps
        positions = scanner._broker.get_positions()
        for pos in positions:
            rt = scanner._realtime_cache.get(pos.ts_code, {})
            if not rt:
                continue
            current = rt.get("price", 0) or rt.get("close", 0) or pos.current_price
            pre_close = rt.get("pre_close", 0) or pos.current_price
            gap_pct = ((current - pre_close) / pre_close * 100) if pre_close > 0 else 0
            if abs(gap_pct) >= 0.5:  # 只显示跳空>0.5%的
                gaps.append({"ts_code": pos.ts_code, "stock_name": pos.stock_name,
                             "gap_pct": round(gap_pct, 1), "strategy": pos.strategy,
                             "profit_pct": round(pos.profit_pct, 1) if hasattr(pos, 'profit_pct') else 0})
        gaps.sort(key=lambda x: abs(x["gap_pct"]), reverse=True)
    except Exception:
        pass
    return gaps


def _build_premarket_analysis(market_snapshot: dict, sentiment: dict, limit_pools: dict,
                              position_gaps: list, candidates: list, strategy_groups: list,
                              hit_rate: dict) -> dict:
    """盘前综合研判 — 把所有数据串成一条判断链"""
    reasons = []
    score = 0  # -3~+3
    
    # 1. 情绪周期
    sent_score = sentiment.get("score", 50)
    sent_phase = sentiment.get("phase_name", "震荡")
    pos_ratio = sentiment.get("position_ratio", 0.5)
    if sent_score >= 55:
        reasons.append({"icon": "📈", "text": f"情绪{sent_score}分({sent_phase})，偏强，仓位系数{pos_ratio*100:.0f}%"})
        score += 1
    elif sent_score < 40:
        reasons.append({"icon": "📉", "text": f"情绪{sent_score}分({sent_phase})，偏弱，仓位系数仅{pos_ratio*100:.0f}%"})
        score -= 1
    else:
        reasons.append({"icon": "📊", "text": f"情绪{sent_score}分({sent_phase})，中性，仓位系数{pos_ratio*100:.0f}%"})
    
    # 2. 涨跌比
    up = market_snapshot.get("up_count", 0)
    down = market_snapshot.get("down_count", 0)
    total = up + down
    if total > 0:
        up_ratio = up / total
        if up_ratio >= 0.6:
            reasons.append({"icon": "🟢", "text": f"涨跌比 {up}:{down}，涨占{up_ratio*100:.0f}%，多头占优"})
            score += 1
        elif up_ratio <= 0.35:
            reasons.append({"icon": "🔴", "text": f"涨跌比 {up}:{down}，涨仅占{up_ratio*100:.0f}%，空头明显"})
            score -= 1
        else:
            reasons.append({"icon": "⚖️", "text": f"涨跌比 {up}:{down}，多空均衡"})
    
    # 3. 涨停池
    zt_count = limit_pools.get("up_count", 0)
    dt_count = limit_pools.get("down_count", 0)
    if zt_count > 0 or dt_count > 0:
        if zt_count >= 50:
            reasons.append({"icon": "🔥", "text": f"涨停{zt_count}只/跌停{dt_count}只，赚钱效应强"})
            score += 1
        elif zt_count < 15:
            reasons.append({"icon": "❄️", "text": f"涨停仅{zt_count}只/跌停{dt_count}只，赚钱效应弱"})
            score -= 1
        else:
            reasons.append({"icon": "📋", "text": f"涨停{zt_count}只/跌停{dt_count}只，正常水平"})
    
    # 4. 连板高度
    cont = limit_pools.get("continue_stats", {})
    max_board = max([int(k) for k in cont.keys()], default=0)
    if max_board >= 5:
        reasons.append({"icon": "🚀", "text": f"最高{max_board}连板，市场高度够，短线情绪好"})
        score += 1
    elif max_board <= 2 and zt_count > 0:
        reasons.append({"icon": "⚠️", "text": f"最高仅{max_board}连板，市场高度不够，追高需谨慎"})
        score -= 0.5
    
    # 5. 板块集中度
    sectors = limit_pools.get("sector_heat", [])
    if sectors and sectors[0].get("count", 0) >= 3:
        reasons.append({"icon": "🎯", "text": f"{sectors[0]['name']}板块{sectors[0]['count']}只涨停，有明确主线"})
        score += 0.5
    
    # 6. 持仓竞价影响
    gap_ups = [p for p in position_gaps if p.get("gap_pct", 0) > 2]
    gap_downs = [p for p in position_gaps if p.get("gap_pct", 0) < -2]
    if gap_ups:
        reasons.append({"icon": "⬆️", "text": f"{len(gap_ups)}只持仓竞价高开>+2%，持仓偏强"})
        score += 0.5
    if gap_downs:
        reasons.append({"icon": "⬇️", "text": f"{len(gap_downs)}只持仓竞价低开<-2%，需关注风险"})
        score -= 0.5
    
    # 7. 策略胜率
    best_wr = 0
    for s, hr in hit_rate.items():
        if hr.get("total", 0) >= 5:
            best_wr = max(best_wr, hr.get("win_rate", 0))
    if best_wr >= 65:
        reasons.append({"icon": "✅", "text": f"策略历史最高胜率{best_wr}%，近期表现好"})
    elif best_wr > 0 and best_wr < 50:
        reasons.append({"icon": "⛔", "text": f"策略历史胜率仅{best_wr}%，需谨慎"})
        score -= 0.5
    
    # 结论
    if score >= 2:
        verdict = "bullish"
        conclusion = "偏多 — 情绪强+赚钱效应好，可以积极操作"
    elif score >= 0.5:
        verdict = "neutral"
        conclusion = "中性 — 有结构性机会，精选策略+控制仓位"
    elif score >= -0.5:
        verdict = "neutral"
        conclusion = "中性偏弱 — 机会有限，小仓位试探为主"
    else:
        verdict = "bearish"
        conclusion = "偏空 — 情绪弱+赚钱效应差，建议防守为主"
    
    # 操作建议
    if verdict == "bullish":
        suggestion = f"仓位可用{pos_ratio*100:.0f}%，各策略可正常开仓，注意追高标的风险"
    elif verdict == "neutral":
        suggestion = f"仓位控制在{pos_ratio*100:.0f}%以内，优先选择胜率高的策略，避开弱势板块"
    else:
        suggestion = f"仓位严控{pos_ratio*100:.0f}%，只做确定性高的机会，已有持仓设好止损"
    
    # 数据日期
    data_date = market_snapshot.get("data_date") or str(limit_pools.get("trade_date", ""))
    
    return {
        "verdict": verdict,
        "conclusion": conclusion,
        "reasons": reasons,
        "suggestion": suggestion,
        "score": round(score, 1),
        "data_date": data_date,
    }



@router.get("/scan-config")
async def get_scan_config():
    """获取扫描器配置信息 — 间隔、模式、参数等
    
    用于前端展示扫描器运行参数，方便用户了解自动扫描行为
    """
    scanner = await _get_scanner()
    try:
        config = {
            "scan_interval_sec": scanner.SCAN_INTERVAL,
            "scan_interval_desc": f"{scanner.SCAN_INTERVAL // 60}分钟",
            "position_check_interval_sec": scanner.POSITION_CHECK_INTERVAL,
            "position_check_fast_sec": scanner.POSITION_CHECK_FAST,
            "position_check_critical_sec": scanner.POSITION_CHECK_CRITICAL,
            "signal_expire_sec": scanner.SIGNAL_EXPIRE_SECONDS,
            "signal_expire_desc": f"{scanner.SIGNAL_EXPIRE_SECONDS // 60}分钟",
            "max_positions": scanner.MAX_POSITIONS,
            "max_position_ratio": scanner.MAX_POSITION_RATIO,
            "is_running": scanner._is_running,
            "trade_mode": scanner._trade_mode if hasattr(scanner, '_trade_mode') else "simulated",
            "account_id": scanner._broker.account.account_id if scanner._broker else "default",
            "current_smart_interval": scanner._get_smart_check_interval(scanner._broker.get_positions()) if scanner._is_running and scanner._broker else None,
        }
        return {"success": True, "data": config}
    except Exception as e:
        return {"success": True, "data": {"error": str(e)}}


# ==================== V2.9.7: Daemon管理端点 ====================


@router.get("/daemon/status")
async def get_daemon_status():
    """【v2.9.7】获取ScannerDaemon守护进程详细状态
    
    返回子进程存活/状态/重启次数/ACK等待数等
    仅当Daemon模式运行时有效
    """
    try:
        from nodes.market_monitor.scanner_daemon import ScannerDaemon
        daemon = ScannerDaemon._instance
        if not daemon:
            return {"success": True, "available": False, "message": "Daemon未启动(非Daemon模式)"}
        
        status = daemon.get_status()
        return {"success": True, "available": True, "data": status}
    except Exception as e:
        return {"success": True, "available": False, "error": str(e)}



@router.post("/daemon/restart")
async def restart_daemon():
    """【v2.9.7】重启ScannerDaemon子进程(手动重启,重置计数器)
    
    安全: 不会影响Broker持仓, 只重启扫描进程
    """
    try:
        from nodes.market_monitor.scanner_daemon import ScannerDaemon
        daemon = ScannerDaemon._instance
        if not daemon:
            return {"success": False, "message": "Daemon未启动"}
        
        result = await daemon.restart()
        return {"success": result, "message": "重启成功" if result else "重启失败"}
    except Exception as e:
        return {"success": False, "message": str(e)}



@router.get("/stream/signals")
async def get_stream_signals(count: int = 20):
    """【v2.9.14】从Redis Stream读取最近信号(scanner:signal)
    
    Phase2.1: signal通道已升级为Redis Stream(xadd), 消息不丢失。
    Web节点可通过此端点消费Stream数据, 支持断线后回补。
    
    Args:
        count: 读取条数(默认20, 最大100)
    """
    try:
        from core.managers.redis_manager import redis_manager
        if not redis_manager._initialized:
            return {"success": False, "message": "Redis未初始化"}
        
        count = min(max(count, 1), 100)
        # XRANGE从最早到最新, 然后取最后count条
        messages = await redis_manager._client.xrange(
            "scanner:signal", count=count
        )
        # 返回最新的count条(如果总数超过count)
        if len(messages) > count:
            messages = messages[-count:]
        
        result = []
        for msg_id, fields in messages:
            result.append({
                "id": msg_id,
                "data": fields,
            })
        return {"success": True, "count": len(result), "data": result}
    except Exception as e:
        return {"success": False, "message": str(e)}



@router.get("/stream/positions")
async def get_stream_positions(count: int = 20):
    """【v2.9.14】从Redis Stream读取最近持仓变更(scanner:position)
    
    Phase2.1: position通道已升级为Redis Stream(xadd), 消息不丢失。
    
    Args:
        count: 读取条数(默认20, 最大100)
    """
    try:
        from core.managers.redis_manager import redis_manager
        if not redis_manager._initialized:
            return {"success": False, "message": "Redis未初始化"}
        
        count = min(max(count, 1), 100)
        messages = await redis_manager._client.xrange(
            "scanner:position", count=count
        )
        if len(messages) > count:
            messages = messages[-count:]
        
        result = []
        for msg_id, fields in messages:
            result.append({
                "id": msg_id,
                "data": fields,
            })
        return {"success": True, "count": len(result), "data": result}
    except Exception as e:
        return {"success": False, "message": str(e)}


# ==================== 复盘增强API ====================


# ==================== 灰度对齐API【v2.9.69】 ====================

@router.get("/alignment-stats")
async def get_alignment_stats():
    """【v2.9.69】获取compare模式灰度对齐统计
    
    量化legacy与checker卖出逻辑的对齐程度。
    当对齐率>=95%且连续20次一致时, 可安全切换到checker模式。
    仅当SELL_LOGIC_MODE=compare时累积数据。
    """
    try:
        from nodes.web.api.scanner import _get_scanner_instance
        scanner = _get_scanner_instance()
        if not scanner:
            return {"success": True, "available": False, "message": "Scanner未启动"}
        
        checker = scanner._position_checker
        stats = checker.alignment_stats.to_dict()
        stats["sell_logic_mode"] = checker.sell_logic_mode
        
        # 切换建议
        if checker.sell_logic_mode == "compare":
            if stats["switch_ready"]:
                stats["recommendation"] = "可安全切换: 设置 SELL_LOGIC_MODE=checker"
            elif stats["total_checks"] < 50:
                stats["recommendation"] = f"数据不足: 还需{50 - stats['total_checks']}次compare"
            elif stats["consecutive_agree"] < 20:
                stats["recommendation"] = f"连续一致不足: 还需{20 - stats['consecutive_agree']}次"
            else:
                stats["recommendation"] = f"对齐率{stats['alignment_rate']*100:.1f}%<95%, 继续观察"
        elif checker.sell_logic_mode == "legacy":
            stats["recommendation"] = "当前legacy模式, 设置 SELL_LOGIC_MODE=compare 开启灰度"
        elif checker.sell_logic_mode == "checker":
            stats["recommendation"] = "已切换到checker模式"
        else:
            stats["recommendation"] = f"未知模式: {checker.sell_logic_mode}"
        
        return {"success": True, "available": True, "data": stats}
    except Exception as e:
        return {"success": False, "message": str(e)}

