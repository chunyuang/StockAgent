#!/usr/bin/env python3
"""Scanner API - 核心状态/控制/持仓/信号"""
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

router = APIRouter(prefix="/scanner", tags=["核心状态/控制/持仓/信号"])


@router.get("/all")
async def get_all_scanner_data():
    """一次性获取所有扫描器数据(减少前端HTTP开销)
    
    合并: status + signals + positions + timeline + orders
    替代前端5次并发请求, 减少延迟和HTTP开销
    """
    scanner = await _get_scanner()
    
    # 状态
    status_resp = await get_scanner_status()
    status_data = status_resp.get("data", {}) if isinstance(status_resp, dict) else {}
    
    # 信号
    signals_data = scanner.get_signals()
    
    # 持仓
    positions_data = scanner.get_positions()
    
    # 时间线
    timeline_data = scanner.get_timeline()
    
    # 订单(最近20条)
    orders_data = []
    if scanner._broker:
        try:
            if await scanner._broker._ensure_mongo():
                db = scanner._broker._mongo_db
                docs = await db["broker_orders"].find(
                    {"account_id": scanner._broker.account.account_id}
                ).sort("create_time", -1).limit(20).to_list(20)
                for d in docs:
                    d.pop("_id", None)
                    orders_data.append(d)
        except Exception:
            pass
    
    # 累计盈亏统计(从时间线计算)
    total_profit_amount = 0
    for item in timeline_data:
        if item.get("action") == "sell" and item.get("profit_amount"):
            total_profit_amount += item["profit_amount"]
    
    return _sanitize({
        "success": True,
        "data": {
            "status": status_data,
            "signals": signals_data,
            "positions": positions_data,
            "timeline": timeline_data,
            "orders": orders_data,
            "summary": {
                "total_profit_amount": round(total_profit_amount, 2),
                "today_trades": len([t for t in timeline_data if t.get("action") == "buy"]) + len([t for t in timeline_data if t.get("action") == "sell"]),
                "today_buys": len([t for t in timeline_data if t.get("action") == "buy"]),
                "today_sells": len([t for t in timeline_data if t.get("action") == "sell"]),
            },
        },
    })



@router.get("/status")
async def get_scanner_status():
    """获取扫描器状态(含熔断状态、交易时间、数据源)"""
    scanner = await _get_scanner()
    status = scanner.get_status()
    
    # 交易时间判断
    now = datetime.now()
    ct = now.strftime("%H:%M")
    is_weekend = now.weekday() >= 5
    is_trading = ("09:15" <= ct <= "15:05") and not is_weekend
    is_premarket = ("09:00" <= ct < "09:15") and not is_weekend
    is_closed = ct > "15:05" or is_weekend
    
    if is_weekend:
        market_status = "休市(调试)"
    elif is_trading:
        market_status = "交易中"
    elif is_premarket:
        market_status = "盘前"
    elif is_closed:
        market_status = "已收盘"
    else:
        market_status = "盘前"
    
    status["market_status"] = market_status
    status["current_time"] = now.strftime("%H:%M:%S")
    status["is_trading_time"] = is_trading
    status["dry_run"] = scanner._dry_run  # 【调试增强】dry_run状态
    status["signal_stats"] = {  # 【调试增强】信号统计
        "total": len(scanner._active_signals),
        "new": len([s for s in scanner._active_signals if s.signal_status == "new"]),
        "executed": len([s for s in scanner._active_signals if s.signal_status == "executed"]),
        "skipped": len([s for s in scanner._active_signals if s.signal_status == "skipped"]),
        "expired": len([s for s in scanner._active_signals if s.signal_status == "expired"]),
        "filtered": len([s for s in scanner._active_signals if s.signal_status == "filtered"]),
    }
    
    # 数据源状态
    ds_info = []
    if scanner._data_router:
        for name, adapter in scanner._data_router._sources.items():
            try:
                s = adapter.get_status()
                ds_info.append({
                    "name": name,
                    "available": s.get("available", s.get("initialized", True)),
                    "stocks": s.get("cached_stocks", s.get("total_stocks", 0)),
                    "calls": s.get("daily_calls", 0),
                    "limit": s.get("daily_limit", -1),
                    "note": s.get("note", ""),
                })
            except Exception:
                ds_info.append({"name": name, "available": False})
    status["data_sources"] = ds_info
    
    # 熔断状态
    if hasattr(scanner, '_circuit_breaker'):
        status["circuit_breaker"] = {
            "trading_paused": scanner._circuit_breaker.get("trading_paused", False),
            "pause_reason": scanner._circuit_breaker.get("pause_reason", ""),
            "consecutive_losses": scanner._circuit_breaker.get("consecutive_losses", 0),
            "today_trades": scanner._circuit_breaker.get("today_trades", 0),
            "today_losses": scanner._circuit_breaker.get("today_losses", 0),
        }
    return _sanitize({"success": True, "data": status})


# ==================== 控制 ====================


@router.post("/start")
async def start_scanner(req: ScannerStartRequest):
    """启动扫描(后台线程初始化, 立即返回)"""
    global _scanner_instance

    if _scanner_instance is None or (
        req.trade_mode != _scanner_instance._trade_mode
    ):
        from nodes.market_monitor.scanner import MarketScanner
        config = dict(req.config)
        config["trade_mode"] = req.trade_mode
        if req.replay_date:
            config["replay_date"] = req.replay_date
        if req.trade_mode == 'gm':
            config.setdefault("gm_token", "")
            config.setdefault("gm_strategy_id", "")
        _scanner_instance = MarketScanner(account_id=req.account_id, config=config)

    scanner = _scanner_instance
    if scanner._is_running:
        return {"success": True, "data": {"message": "已在运行中"}}
    
    # 后台启动(用run_in_executor避免阻塞事件循环)
    loop = asyncio.get_event_loop()
    loop.create_task(scanner.start(trade_date=req.trade_date))
    return {"success": True, "data": {"message": "扫描器启动中..."}}


class StopScannerRequest(BaseModel):
    sell_all: bool = False  # 是否清仓所有持仓



@router.post("/stop")
async def stop_scanner(req: StopScannerRequest = StopScannerRequest()):
    """停止扫描(可选清仓)"""
    scanner = await _get_scanner()
    result = await scanner.stop(sell_all=req.sell_all)
    return {"success": True, "data": result}


# ==================== 数据 ====================


@router.get("/signals")
async def get_signals():
    """获取当前活跃信号"""
    scanner = await _get_scanner()
    return _sanitize({"success": True, "data": scanner.get_signals()})



@router.get("/positions")
async def get_positions():
    """获取实时持仓"""
    scanner = await _get_scanner()
    return _sanitize({"success": True, "data": scanner.get_positions()})



@router.get("/timeline")
async def get_timeline():
    """获取今日交易时间线"""
    scanner = await _get_scanner()
    return _sanitize({"success": True, "data": _fill_stock_names(scanner.get_timeline(), scanner)})


@router.get("/timeline/history")
async def get_timeline_history(date: str = None, days: int = 7):
    """获取历史交易时间线
    
    Args:
        date: 指定日期(YYYYMMDD), 不传则返回最近N天
        days: 返回最近N天(默认7)
    """
    scanner = await _get_scanner()
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": []}
        
        account_id = scanner._broker.account.account_id if scanner._broker else "default"
        
        if date:
            # 指定日期
            query = {"account_id": account_id, "trade_date": date}
        else:
            # 最近N天
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
            query = {"account_id": account_id, "trade_date": {"$gte": start_date}}
        
        items = []
        async for doc in mongo_manager.db["scanner_timeline"].find(query).sort("_id", 1):
            doc.pop("_id", None)
            doc.pop("account_id", None)
            items.append(doc)
        
        return {"success": True, "data": _fill_stock_names(items, scanner), "count": len(items)}
    except Exception as e:
        return {"success": True, "data": [], "message": str(e)}



@router.get("/account")
async def get_account():
    """获取账户信息(资金/持仓/盈亏)"""
    scanner = await _get_scanner()
    if not scanner._broker:
        return {"success": True, "data": None}
    acct = scanner._broker.get_account()
    return {
        "success": True,
        "data": {
            "account_id": acct.account_id,
            "total_assets": round(acct.total_assets, 2),
            "available_cash": round(acct.available_cash, 2),
            "market_value": round(acct.market_value, 2),
            "today_profit": round(acct.today_profit, 2),
            "total_profit": round(acct.total_profit, 2),
            "position_count": len(scanner._broker.get_positions()),
            "position_ratio": round(acct.market_value / max(acct.total_assets, 1) * 100, 1),
        },
    }


# ==================== 手动交易 ====================


@router.get("/limit-pools")
async def get_limit_pools():
    """获取今日涨停/跌停/炸板池"""
    scanner = await _get_scanner()
    
    try:
        if not scanner._data_router:
            return {"success": True, "data": {"limit_up": [], "limit_down": [], "broken": []}}
        
        biying = scanner._data_router._sources.get("biying")
        if not biying:
            return {"success": True, "data": {"limit_up": [], "limit_down": [], "broken": []}}
        
        today = datetime.now().strftime("%Y-%m-%d")
        
        limit_ups = await biying.get_limit_up_pool(today)
        limit_downs = await biying.get_limit_down_pool(today)
        brokens = await biying.get_broken_board_pool(today)
        
        def to_list(items):
            result = []
            for item in items:
                d = item if isinstance(item, dict) else item.__dict__ if hasattr(item, '__dict__') else {}
                result.append({
                    "ts_code": d.get("ts_code", ""),
                    "name": d.get("name", ""),
                    "close": d.get("close", 0),
                    "pct_chg": d.get("pct_chg", 0),
                    "limit_times": d.get("limit_times", 0),
                    "open_times": d.get("open_times", 0),
                    "fd_amount": round(d.get("fd_amount", 0) / 1000, 0),  # 千元→万元
                    "turnover": d.get("turnover_ratio", 0),
                    "first_time": d.get("first_time", ""),
                    "industry": d.get("industry", ""),
                })
            return result
        
        return {
            "success": True,
            "data": {
                "limit_up": to_list(limit_ups),
                "limit_down": to_list(limit_downs),
                "broken": to_list(brokens),
            }
        }
    except Exception as e:
        return {"success": True, "data": {"limit_up": [], "limit_down": [], "broken": []}, "message": str(e)}



@router.post("/reset")
async def reset_account():
    """清仓重置(清空所有持仓/订单, 恢复初始资金)"""
    scanner = await _get_scanner()
    if not scanner._broker:
        raise HTTPException(400, "Broker未初始化")
    
    # 清空持仓
    scanner._broker.positions.clear()
    scanner._broker.orders.clear()
    
    # 重置账户为初始资金100万
    initial_cash = scanner.config.get("initial_cash", 1_000_000)
    scanner._broker.account.available_cash = initial_cash
    scanner._broker.account.total_assets = initial_cash
    scanner._broker.account.market_value = 0
    scanner._broker.account.total_profit = 0
    scanner._broker.account.today_profit = 0
    
    # 重置熔断
    scanner._circuit_breaker["trading_paused"] = False
    scanner._circuit_breaker["pause_reason"] = ""
    scanner._circuit_breaker["consecutive_losses"] = 0
    scanner._circuit_breaker["today_trades"] = 0
    scanner._circuit_breaker["today_losses"] = 0
    
    # 清空信号和时间线
    scanner._active_signals.clear()
    scanner._timeline.clear()
    
    # 重置统计
    scanner._stats = {"scans": 0, "signals_found": 0, "trades_executed": 0, "stop_losses": 0, "take_profits": 0, "stocks_scanned": 0}
    scanner._scan_count = 0
    scanner._last_scan_time = ""
    
    # 清除MongoDB(更彻底的清理)
    try:
        if await scanner._broker._ensure_mongo():
            db = scanner._broker._mongo_db
            account_id = scanner._broker.account.account_id
            await db["broker_positions"].delete_many({"account_id": account_id})
            await db["broker_orders"].delete_many({"account_id": account_id})
            await db["broker_accounts"].delete_many({"account_id": account_id})
            # 【P0-5修复】清理timeline残留
            await db["scanner_timeline"].delete_many({"account_id": account_id})
            # 清理performance_snapshots残留
            await db["performance_snapshots"].delete_many({"account_id": account_id})
    except Exception as e:
        logger.warning(f"[RESET] MongoDB清理失败(非关键): {e}")
    
    # 保存状态
    try:
        await scanner._broker.save_state()
    except Exception:
        pass
    
    return {"success": True, "data": {"message": "账户已重置"}}


# ==================== 交易审查详情 ====================


@router.get("/summary")
async def get_summary_report():
    """完整交易摘要报告
    
    一站式获取所有关键信息:
    - 账户概览(资产/现金/仓位/盈亏)
    - 持仓详情(每只股票的成本/现价/盈亏/止损止盈/距止损距离)
    - 今日交易统计(买入/卖出/胜率/盈亏比)
    - 策略表现(每策略的交易数/胜率/盈亏)
    - 风控状态(熔断/连续亏损)
    - 信号统计(活跃/过期/执行/跳过)
    """
    scanner = await _get_scanner()
    report = scanner.generate_summary_report()
    return _sanitize({"success": True, "data": report})



@router.put("/position-risk/{ts_code}")
async def adjust_position_risk(ts_code: str, request: Request):
    """调整单票止损止盈参数
    
    覆盖策略默认值，仅对该持仓生效。
    """
    try:
        body = await request.json()
        scanner = _get_scanner_instance()
        if not scanner:
            return {"success": False, "message": "Scanner未运行"}
        
        # 找到该持仓
        pos = None
        for p in scanner._broker.get_positions():
            if p.ts_code == ts_code:
                pos = p
                break
        
        if not pos:
            return {"success": False, "message": f"未找到持仓 {ts_code}"}
        
        # 更新风控覆盖
        overrides = scanner._position_risk_overrides  # Dict[str, Dict]
        if not hasattr(scanner, '_position_risk_overrides'):
            scanner._position_risk_overrides = {}
            overrides = scanner._position_risk_overrides
        
        if ts_code not in overrides:
            overrides[ts_code] = {}
        
        if 'stop_loss_pct' in body:
            overrides[ts_code]['stop_loss_pct'] = float(body['stop_loss_pct'])
        if 'take_profit_pct' in body:
            overrides[ts_code]['take_profit_pct'] = float(body['take_profit_pct'])
        
        # 持久化到MongoDB
        try:
            from core.managers import mongo_manager
            if mongo_manager.db:
                await mongo_manager.db["position_risk_overrides"].replace_one(
                    {"ts_code": ts_code},
                    {"ts_code": ts_code, **overrides[ts_code], "updated_at": datetime.now().isoformat()},
                    upsert=True
                )
        except Exception:
            pass
        
        return {"success": True, "data": {"ts_code": ts_code, **overrides[ts_code]}}
    except Exception as e:
        return {"success": False, "message": str(e)}



@router.get("/position-risk-levels")
async def get_position_risk_levels():
    """获取持仓风险等级分布
    
    对标真实量化: 风险分级是实时监控的核心
    - normal: 安全, 30秒检查
    - warning: 距止损<1%, 10秒检查
    - critical: 已触及止损区, 5秒检查
    """
    try:
        scanner = _get_scanner_instance()
        if not scanner:
            return {"success": False, "message": "Scanner未运行"}
        
        risk_levels = _safe_read_shared(scanner, '_position_risk_levels')
        trailing = _safe_read_shared(scanner, '_trailing_stops')
        positions = scanner.get_positions() if hasattr(scanner, 'get_positions') else []
        
        # 按风险等级分组
        grouped = {"normal": [], "warning": [], "critical": []}
        for pos in positions:
            ts_code = pos.get("ts_code", "")
            level = risk_levels.get(ts_code, "normal")
            info = {
                **pos,
                "risk_level": level,
                "trailing_stop": trailing.get(ts_code),
            }
            grouped.setdefault(level, []).append(info)
        
        return {
            "success": True,
            "data": {
                "levels": grouped,
                "summary": {
                    "total": len(positions),
                    "normal": len(grouped.get("normal", [])),
                    "warning": len(grouped.get("warning", [])),
                    "critical": len(grouped.get("critical", [])),
                },
                "check_interval": scanner._get_smart_check_interval() if hasattr(scanner, '_get_smart_check_interval') else 30,
            }
        }
    except Exception as e:
        return {"success": False, "message": str(e)}


# ==================== 【专业运维增强】新增API ====================


@router.get("/kline/{ts_code}")
async def get_kline_data(ts_code: str, days: int = 30):
    """K线数据（MongoDB读取，用于迷你K线和大图）"""
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": {"ts_code": ts_code, "kline": [], "annotations": []}}
        from datetime import datetime, timedelta
        start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")

        cursor = mongo_manager.db["stock_daily_ak_full"].find(
            {"ts_code": ts_code, "trade_date": {"$gte": start_date}},
            {"_id": 0, "trade_date": 1, "open": 1, "high": 1, "low": 1, "close": 1, "vol": 1, "pct_chg": 1}
        ).sort("trade_date", 1).limit(days + 10)

        kline = []
        async for doc in cursor:
            kline.append({
                "date": doc.get("trade_date", ""),
                "open": doc.get("open", 0), "high": doc.get("high", 0),
                "low": doc.get("low", 0), "close": doc.get("close", 0),
                "volume": doc.get("vol", 0), "pct_chg": doc.get("pct_chg", 0),
            })
        kline = kline[-days:] if len(kline) > days else kline

        # 均线
        for i in range(len(kline)):
            if i >= 4: kline[i]["ma5"] = round(sum(d["close"] for d in kline[i-4:i+1]) / 5, 2)
            if i >= 9: kline[i]["ma10"] = round(sum(d["close"] for d in kline[i-9:i+1]) / 10, 2)
            if i >= 19: kline[i]["ma20"] = round(sum(d["close"] for d in kline[i-19:i+1]) / 20, 2)

        # 买卖点标注
        scanner = await _get_scanner()
        annotations = []
        for item in (scanner._timeline or []):
            if item.get("ts_code") == ts_code:
                annotations.append({
                    "date": item.get("time", "")[:10].replace("-", ""),
                    "action": item.get("action", ""), "price": item.get("price", 0),
                    "strategy": item.get("strategy", ""),
                })

        return _sanitize({"success": True, "data": {"ts_code": ts_code, "kline": kline, "annotations": annotations}})
    except Exception as e:
        return {"success": False, "message": str(e)}



@router.get("/position-risk-matrix")
async def get_position_risk_matrix():
    """持仓风控矩阵 + 全局风险仪表"""
    scanner = await _get_scanner()
    if not scanner._broker:
        return {"success": True, "data": {"positions": [], "global": {}}}

    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": []}
        positions = scanner._broker.get_positions()
        acct = scanner._broker.get_account()
        risk_levels = _safe_read_shared(scanner, '_position_risk_levels')
        trailing_stops = _safe_read_shared(scanner, '_trailing_stops')
        strategy_cn = {"halfway_chase": "半路追涨", "first_limit_up": "首板打板", "dragon_head": "龙头低吸", "limit_down_qiao": "跌停翘板"}

        industry_map = {}
        try:
            async for doc in mongo_manager.db["stock_basic"].find({}, {"_id": 0, "ts_code": 1, "industry": 1}):
                industry_map[doc.get("ts_code", "")] = doc.get("industry", "")
        except Exception:
            pass

        matrix = []
        industry_exp = {}
        max_single_pct = 0
        total_mv = acct.market_value

        for pos in positions:
            cost, cur = pos.avg_cost, pos.current_price
            mv = cur * pos.total_qty
            dist_sl = (cur - cost * 0.97) / max(cur, 0.01) * 100
            dist_tp = (cost * 1.12 - cur) / max(cur, 0.01) * 100
            position_pct = mv / max(total_mv, 1) * 100
            max_single_pct = max(max_single_pct, position_pct)
            industry = industry_map.get(pos.ts_code, "未知")
            industry_exp[industry] = industry_exp.get(industry, 0) + mv
            turnover = 0
            if scanner._realtime_cache and pos.ts_code in scanner._realtime_cache:
                turnover = scanner._realtime_cache[pos.ts_code].get("turnover_rate", 0)
            risk_score = min(max(0, 30 - dist_sl * 3) + min(position_pct / 2, 20) + min(abs(pos.profit_pct) * 2, 20) + (max(0, 20 - turnover * 2) if turnover > 0 else 10), 100)
            trail = trailing_stops.get(pos.ts_code, {})

            matrix.append({
                "ts_code": pos.ts_code, "stock_name": pos.stock_name or getattr(scanner, '_stock_name_map', {}).get(pos.ts_code, ""),
                "strategy": pos.strategy or "unknown", "strategy_name": strategy_cn.get(pos.strategy, pos.strategy or "未知"),
                "industry": industry, "current_price": cur, "cost_price": cost,
                "profit_pct": round(pos.profit_pct, 2), "profit_amount": round((cur - cost) * pos.total_qty, 0),
                "market_value": round(mv, 0), "position_pct": round(position_pct, 1),
                "dist_stop_loss": round(dist_sl, 2), "dist_take_profit": round(dist_tp, 2),
                "stop_loss_price": round(cost * 0.97, 2), "take_profit_price": round(cost * 1.12, 2),
                "volatility": round(abs(pos.profit_pct), 2), "turnover_rate": turnover,
                "risk_score": round(risk_score, 0), "risk_level": risk_levels.get(pos.ts_code, "normal"),
                "trailing_stop": trail, "total_qty": pos.total_qty,
            })

        top_ind = max(industry_exp.values()) / max(total_mv, 1) * 100 if industry_exp else 0
        cash_ratio = acct.available_cash / max(acct.total_assets, 1) * 100

        return _sanitize({"success": True, "data": {
            "positions": sorted(matrix, key=lambda x: -x["risk_score"]),
            "global": {
                "total_assets": round(acct.total_assets, 2), "cash_ratio": round(cash_ratio, 1),
                "position_ratio": round(100 - cash_ratio, 1), "max_single_pct": round(max_single_pct, 1),
                "top_industry_concentration": round(top_ind, 1),
                "industry_exposure": {k: round(v / max(total_mv, 1) * 100, 1) for k, v in sorted(industry_exp.items(), key=lambda x: -x[1])},
                "position_count": len(positions),
                "risk_summary": {
                    "normal": sum(1 for m in matrix if m["risk_score"] < 40),
                    "warning": sum(1 for m in matrix if 40 <= m["risk_score"] < 70),
                    "critical": sum(1 for m in matrix if m["risk_score"] >= 70),
                }
            }
        }})
    except Exception as e:
        return {"success": False, "message": str(e)}


