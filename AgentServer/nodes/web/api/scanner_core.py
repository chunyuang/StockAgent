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
    _fill_stock_names(signals_data, scanner)
    
    # 持仓【v2.9.93】scanner.get_positions() 是主路径（字段最全）,
    # 但增加一道 broker_positions 一致性检查：如果二者持仓 ts_code 集合不一致，
    # 说明 scanner 内存被 scanner_timeline 污染 (P0事故 6/15) —— fallback 到 broker 真相源。
    positions_data = scanner.get_positions()
    try:
        from nodes.web.api.scanner_analysis import _compute_positions_from_broker
        from core.managers import mongo_manager
        if mongo_manager.db is not None:
            account_id = scanner.account_id if hasattr(scanner, 'account_id') else "default"
            broker_positions = await _compute_positions_from_broker(mongo_manager.db, account_id)
            broker_codes = {p.get("ts_code") for p in broker_positions}
            scanner_codes = {p.get("ts_code") for p in positions_data}
            if broker_codes != scanner_codes:
                # 不一致: 幽灵持仓警报 — 切为 broker 真相源 (代价: 丢失部分字段)
                ghost = scanner_codes - broker_codes
                missing = broker_codes - scanner_codes
                try:
                    from loguru import logger
                    logger.warning(
                        f"[/scanner/all] 持仓 drift! scanner={len(scanner_codes)} broker={len(broker_codes)} "
                        f"幽灵(scanner独有)={ghost} 丢失(broker独有)={missing} —— fallback 到 broker_positions"
                    )
                except Exception:
                    pass
                positions_data = broker_positions
    except Exception:
        # 一致性检查失败 不影响主路径
        pass
    _fill_stock_names(positions_data, scanner)
    
    # 时间线
    timeline_data = scanner.get_timeline()
    # 【v2.9.79】填充空stock_name(旧数据/行情无name时)
    _fill_stock_names(timeline_data, scanner)
    
    # 如果时间线为空(扫描器未启动)，尝试从MongoDB加载最近交易日数据
    if not timeline_data:
        try:
            from core.managers import mongo_manager
            if mongo_manager.db is not None:
                db = mongo_manager.db
                account_id = scanner.account_id if hasattr(scanner, 'account_id') else "default"
                # 优先查当天; 如果当天只有blocked记录(<3条), 回退到最近有完整数据的交易日
                today_str = __import__('datetime').datetime.now().strftime("%Y%m%d")
                today_count = await db["scanner_timeline"].count_documents(
                    {"account_id": account_id, "trade_date": today_str}
                )
                fallback_date = today_str
                if today_count < 3:
                    # 找数据最多的最近交易日
                    pipeline = [
                        {"$match": {"account_id": account_id}},
                        {"$group": {"_id": "$trade_date", "count": {"$sum": 1}}},
                        {"$sort": {"count": -1}},
                        {"$limit": 1}
                    ]
                    result = await db["scanner_timeline"].aggregate(pipeline).to_list(1)
                    if result:
                        fallback_date = result[0]["_id"]
                if fallback_date:
                    cursor = db["scanner_timeline"].find(
                        {"account_id": account_id, "trade_date": fallback_date}
                    ).sort("_id", 1)
                    async for doc in cursor:
                        doc.pop("_id", None)
                        doc.pop("account_id", None)
                        # 不删trade_date! 前端需要用它判断是否今天的数据
                        # 旧数据(trade_date!=today)显示时标注为历史回放
                        if doc.get("trade_date") and str(doc.get("trade_date")) != today_str:
                            doc["_historical_fallback"] = True
                        timeline_data.append(doc)
        except Exception:
            pass
    
    # 订单(最近N条，按scanner当前交易日期过滤)
    orders_data = []
    if scanner._broker:
        try:
            if await scanner._broker._ensure_mongo():
                db = scanner._broker._mongo_db
                orders_query = {"account_id": scanner._broker.account.account_id}
                # 【v2.9.92d】如果有trade_date，只返回当天的订单
                trade_date = getattr(scanner, '_trade_date', '')
                if trade_date:
                    orders_query["trade_date"] = {"$in": [str(trade_date), int(trade_date)] if str(trade_date).isdigit() else str(trade_date)}
                docs = await db["broker_orders"].find(
                    orders_query
                ).sort("create_time", 1).limit(50).to_list(50)
                for d in docs:
                    d.pop("_id", None)
                    orders_data.append(d)
        except Exception:
            pass
    
    # 填充空stock_name(从scanner的名称映射)
    _fill_stock_names(timeline_data, scanner)
    
    # 累计盈亏统计(优先从broker_orders profit_amount累加，更准确)
    total_profit_amount = 0
    # 方式1: 从timeline sell事件累加(实时数据)
    for item in timeline_data:
        if item.get("action") == "sell" and item.get("profit_amount"):
            total_profit_amount += item["profit_amount"]
    # 方式2: 如果timeline无profit_amount，从broker_orders补充(历史回放场景)
    if total_profit_amount == 0 and orders_data:
        for o in orders_data:
            if o.get("side") == "sell" and o.get("profit_amount"):
                total_profit_amount += o["profit_amount"]
    
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
    
    # 前端兼容字段(Pinia store refreshFromApi期望的字段名)
    status["sentiment"] = status.get("filter_pipeline", {}).get("sentiment", None)
    status["position_ratio"] = status.get("filter_pipeline", {}).get("position_ratio", 1.0)
    
    # 【v2.9.86修复】添加完整持仓列表+账户详情, 供REST轮询全量刷新
    # 之前positions只返回数量(数字), 导致前端refreshFromApi把数组覆盖为数字
    try:
        pos_list = scanner.get_positions()
        if pos_list:
            status["positions"] = pos_list  # 覆盖数量为完整持仓数组
            status["position_count"] = len(pos_list)  # 数量移到新字段
        else:
            # 【v2.9.92s】scanner未运行时broker内存为空，从MongoDB读取持仓
            scanner_not_running = not status.get("is_running", False)
            if scanner_not_running:
                try:
                    from core.managers import mongo_manager
                    if mongo_manager.is_initialized:
                        pos_docs = await mongo_manager.db["broker_positions"].find(
                            {"account_id": "default"}
                        ).to_list(length=50)
                        if pos_docs:
                            status["positions"] = [{
                                "ts_code": p.get("ts_code", ""),
                                "stock_name": p.get("stock_name", ""),
                                "strategy": p.get("strategy", ""),
                                "shares": p.get("total_qty", 0),
                                "available_qty": p.get("available_qty", 0),
                                "cost_price": p.get("avg_cost", 0),
                                "current_price": p.get("current_price", 0),
                                "profit_pct": round(p.get("profit_pct", 0), 2),
                                "profit_amount": round((p.get("current_price", 0) - p.get("avg_cost", 0)) * p.get("total_qty", 0), 2),
                                "market_value": round(p.get("current_price", 0) * p.get("total_qty", 0), 2),
                                "stop_loss_pct": 3.0,
                                "take_profit_pct": 12.0,
                                "stop_loss_price": round(p.get("avg_cost", 0) * 0.97, 2),
                                "take_profit_price": round(p.get("avg_cost", 0) * 1.12, 2),
                                "risk_level": "normal",
                            } for p in pos_docs]
                            status["position_count"] = len(pos_docs)
                except Exception:
                    pass
            if not status.get("positions"):
                status["positions"] = []
                status["position_count"] = 0
    except Exception:
        status["position_count"] = status.get("positions", 0)  # fallback: 保留原数字
    # 账户信息(完整对象)
    if scanner._broker:
        try:
            acct = scanner._broker.account
            status["account"] = {
                "total_assets": round(acct.total_assets, 2),
                "available_cash": round(acct.available_cash, 2),
                "market_value": round(acct.market_value, 2),
                "total_profit": round(acct.total_profit, 2),  # v2.9.92p: 改total_profit而非today_profit
            }
        except Exception:
            pass
    # 【v2.9.92q】scanner未运行时从MongoDB读真实账户数据
    # 之前只检查total_assets==1000000，但broker可能残留上次运行的cash(如266673)
    # 正确做法：scanner没运行时一律用MongoDB的broker_accounts(最权威)
    scanner_not_running = not status.get("is_running", False)
    if scanner_not_running or not status.get("account") or status["account"].get("total_assets") == 1000000:
        try:
            from core.managers import mongo_manager
            if mongo_manager.is_initialized:
                acct_doc = await mongo_manager.db["broker_accounts"].find_one({"account_id": "default"})
                if acct_doc and acct_doc.get("total_assets", 0) > 0:
                    # 直接用MongoDB中的账户数据(最权威)
                    # 不从broker_positions重新计算(因为scanner没运行时current_price=0会导致市值归零)
                    status["account"] = {
                        "total_assets": round(acct_doc.get("total_assets", 0), 2),
                        "available_cash": round(acct_doc.get("available_cash", 0), 2),
                        "market_value": round(acct_doc.get("market_value", 0), 2),
                        "total_profit": round(acct_doc.get("total_profit", 0), 2),
                    }
        except Exception:
            pass
    # 信号列表
    try:
        status["signals"] = [
            {"ts_code": s.ts_code, "stock_name": s.stock_name, "strategy": s.strategy,
             "strategy_name": getattr(s, 'strategy_name', ''), "price": s.price,
             "pct_chg": s.pct_chg, "reason": s.reason, "created_at": s.created_at,
             "signal_status": s.signal_status}
            for s in scanner._active_signals
        ] if scanner._active_signals else []
    except Exception:
        pass
    
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
    """启动扫描(后台线程初始化, 立即返回)
    
    【v2.9.92s】移除非交易时间启动限制
    之前v2.9.92b加了启动拒绝防止假数据，但根因已修(broker._virtual_mode + 数据完整性检查)
    而且阻碍了盘前准备(8:00-9:00无法启动)、收盘后调试等正常使用
    scanner内部scan_loop已有完整的phase门控，非交易时间不会执行交易
    """
    from nodes.web.api import scanner_shared

    if scanner_shared._scanner_instance is None or (
        req.trade_mode != scanner_shared._scanner_instance._trade_mode
    ):
        from nodes.market_monitor.scanner import MarketScanner
        config = dict(req.config)
        config["trade_mode"] = req.trade_mode
        if req.replay_date:
            config["replay_date"] = req.replay_date
        if req.trade_mode == 'gm':
            config.setdefault("gm_token", "")
            config.setdefault("gm_strategy_id", "")
        scanner_shared._scanner_instance = MarketScanner(account_id=req.account_id, config=config)

    scanner = scanner_shared._scanner_instance
    if scanner._is_running:
        return {"success": True, "data": {"message": "已在运行中"}}
    
    # 后台启动(用run_in_executor避免阻塞事件循环)
    loop = asyncio.get_event_loop()
    # 【v2.9.92s】replay模式下trade_date用replay_date，防止timeline写入错误的日期
    effective_trade_date = req.trade_date or req.replay_date
    loop.create_task(scanner.start(trade_date=effective_trade_date))
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
async def get_timeline_history(date: str = None, days: int = 7, source: str = "reconciled"):
    """获取历史交易时间线
    
    Args:
        date: 指定日期(YYYYMMDD), 不传则返回最近N天
        days: 返回最近N天(默认7)
        source: 数据源策略 (v2.9.96e)
          - 'reconciled' (默认): buy/sell仅返回有broker_orders对应的真实交易, blocked原样返回
          - 'all': 返回所有timeline记录(含可能的幽灵/调试记录, 仅供审计)
    """
    scanner = await _get_scanner()
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": []}
        
        # 【v2.9.83修复】account_id获取: 优先scanner._broker, fallback到scanner.account_id, 最后default
        account_id = "default"
        try:
            if scanner._broker and hasattr(scanner._broker, 'account') and scanner._broker.account:
                account_id = scanner._broker.account.account_id
            elif hasattr(scanner, 'account_id') and scanner.account_id:
                account_id = scanner.account_id
        except Exception:
            pass
        
        if date:
            # 指定日期
            # 【v2.9.95修复】trade_date在MongoDB中可能是int或string, 需兼容两种类型
            date_int = int(date) if date.isdigit() else date
            query = {"account_id": account_id, "trade_date": {"$in": [date, date_int]}}
        else:
            # 最近N天
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
            start_date_int = int(start_date)
            query = {"account_id": account_id, "$or": [{"trade_date": {"$gte": start_date}}, {"trade_date": {"$gte": start_date_int}}]}
        
        items = []
        # 【v2.9.97c】scanner_timeline 只含 blocked 等决策日志; buy/sell 从 broker_orders 读取
        # Step 1: 从 scanner_timeline 读 blocked 等非交易记录
        async for doc in mongo_manager.db["scanner_timeline"].find(query).sort("time", 1):
            doc.pop("_id", None)
            doc.pop("account_id", None)
            # 只取非 buy/sell 记录(blocked等)
            if doc.get("action") not in ("buy", "sell"):
                items.append(doc)
        
        # Step 2: 从 broker_orders 读 buy/sell (唯一真相源)
        bo_query = {"account_id": account_id, "status": "filled"}
        if date:
            bo_query["trade_date"] = {"$in": [date, date_int]}
        else:
            bo_query["$or"] = [{"trade_date": {"$gte": start_date}}, {"trade_date": {"$gte": start_date_int}}]
        async for doc in mongo_manager.db["broker_orders"].find(bo_query).sort("fill_time", 1):
            side = doc.get("side", "")
            if side not in ("buy", "sell"):
                continue
            items.append({
                "time": doc.get("fill_time", "") or doc.get("create_time", ""),
                "action": side,
                "ts_code": doc.get("ts_code", ""),
                "stock_name": doc.get("stock_name", ""),
                "strategy": doc.get("strategy", ""),
                "shares": doc.get("filled_qty", 0) or doc.get("quantity", 0),
                "price": doc.get("filled_price", 0) or doc.get("price", 0),
                "reason": doc.get("reason", ""),
                "profit_pct": doc.get("profit_pct"),
                "profit_amount": doc.get("profit_amount"),
                "trade_date": str(doc.get("trade_date", "")),
                "source": doc.get("source", "auto"),
                "decision_detail": doc.get("decision_detail", {}),
            })
        
        # 按时间排序
        # 【v2.9.97c】reconcile逻辑不再需要: buy/sell直接从broker_orders读,已确保真实
        
        return {"success": True, "data": _fill_stock_names(items, scanner), "count": len(items)}
    except Exception as e:
        return {"success": True, "data": [], "message": str(e)}



@router.get("/account")
async def get_account():
    """获取账户信息(资金/持仓/盈亏)"""
    scanner = await _get_scanner()
    # scanner未运行时从MongoDB读真实数据(broker内存数据不权威)
    if not scanner._is_running:
        try:
            from core.managers import mongo_manager
            if mongo_manager.is_initialized:
                acct_doc = await mongo_manager.db["broker_accounts"].find_one({"account_id": "default"})
                if acct_doc and acct_doc.get("total_assets", 0) > 0:
                    # 【v2.9.97c】position_count 从 broker_positions 实查, 不信任 broker_accounts 的缓存值
                    pos_count = await mongo_manager.db["broker_positions"].count_documents(
                        {"account_id": "default", "total_qty": {"$gt": 0}}
                    )
                    return {
                        "success": True,
                        "data": {
                            "account_id": acct_doc.get("account_id", "default"),
                            "total_assets": round(acct_doc.get("total_assets", 0), 2),
                            "available_cash": round(acct_doc.get("available_cash", 0), 2),
                            "market_value": round(acct_doc.get("market_value", 0), 2),
                            "today_profit": round(acct_doc.get("today_profit", 0), 2),
                            "total_profit": round(acct_doc.get("total_profit", 0), 2),
                            "position_count": pos_count,
                            "position_ratio": round(acct_doc.get("market_value", 0) / max(acct_doc.get("total_assets", 1), 1) * 100, 1),
                        },
                    }
        except Exception:
            pass
    if not scanner._broker:
        # 【v2.9.97e】Broker未初始化时返回空账户(而非None, 避免前端崩溃)
        return {
            "success": True,
            "data": {
                "account_id": "default",
                "total_assets": 0,
                "available_cash": 0,
                "market_value": 0,
                "today_profit": 0,
                "total_profit": 0,
                "position_count": 0,
                "position_ratio": 0,
            },
        }
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


# 【v2.9.96】limit-pools 内存缓存(60秒TTL): 避免必盈被反复调用
_limit_pools_cache = {"data": None, "ts": 0}
_LIMIT_POOLS_TTL = 60  # 秒

@router.get("/limit-pools")
async def get_limit_pools():
    """获取今日涨停/跌停/炸板池
    
    非开盘时间优先从MongoDB limit_list读取(历史数据), 
    开盘时间从必盈实时接口获取。
    
    【v2.9.96】60秒内存缓存防止反复打必盈API(超限会卡30秒)
    """
    import time as _time
    # 优先返回缓存
    if _limit_pools_cache["data"] and _time.time() - _limit_pools_cache["ts"] < _LIMIT_POOLS_TTL:
        return _limit_pools_cache["data"]
    
    async def _build_result():
        scanner = await _get_scanner()
        try:
            from core.settings import settings
            now = datetime.now()
            is_trading = (now.hour >= 9 and now.hour < 15) or (now.hour == 9 and now.minute >= 15)
            
            # 非交易时间或必盈不可用: 从MongoDB回退
            if not is_trading or not scanner._data_router:
                return await _limit_pools_from_mongo()
            
            biying = scanner._data_router._sources.get("biying")
            if not biying:
                return await _limit_pools_from_mongo()
            
            # 【v2.9.96】429熔断短路: 必盈被熔断则直接走MongoDB
            if getattr(biying, '_throttled_until_date', None):
                from datetime import date as _date
                if _date.today() <= biying._throttled_until_date:
                    return await _limit_pools_from_mongo()
            
            today = now.strftime("%Y-%m-%d")
            limit_ups = await biying.get_limit_up_pool(today)
            limit_downs = await biying.get_limit_down_pool(today)
            brokens = await biying.get_broken_board_pool(today)
            
            if not limit_ups and not limit_downs and not brokens:
                return await _limit_pools_from_mongo()
            
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
                        "fd_amount": round(d.get("fd_amount", 0) / 1000, 0),
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
        except Exception:
            return await _limit_pools_from_mongo()
    
    result = await _build_result()
    # 写入缓存
    _limit_pools_cache["data"] = result
    _limit_pools_cache["ts"] = _time.time()
    return result


async def _limit_pools_from_mongo():
    """从MongoDB limit_list集合读取涨停池(收盘后/非交易时间回退)
    
    limit_list有两种数据格式:
    1. 旧格式(limit="U"/"D"): name, close, fc_ratio, first_time, limit_times等
    2. 新格式(up_limit/down_limit): 只有涨跌停价格,需要从日线数据判断是否涨停
    """
    from core.managers import mongo_manager
    
    if not mongo_manager.is_initialized:
        return {"success": True, "data": {"limit_up": [], "limit_down": [], "broken": []}}
    
    try:
        db = mongo_manager.db
        # 找最新有数据的交易日
        latest = await db["limit_list"].find_one(sort=[("trade_date", -1)])
        if not latest:
            return {"success": True, "data": {"limit_up": [], "limit_down": [], "broken": []}}
        
        td = latest["trade_date"]
        
        # 预加载当天日线(用于补pct_chg和判断涨停)
        pct_map = {}
        daily_cursor = db["stock_daily_ak_full"].find(
            {"trade_date": td}, {"_id": 0, "ts_code": 1, "pct_chg": 1, "close": 1}
        )
        async for doc in daily_cursor:
            pct_map[doc["ts_code"]] = {"pct_chg": doc.get("pct_chg", 0), "close": doc.get("close", 0)}
        
        # 预加载股票名称
        name_map = {}
        async for doc in db["stock_basic"].find({}, {"_id": 0, "ts_code": 1, "name": 1}):
            name_map[doc["ts_code"]] = doc.get("name", "")
        
        limit_ups, limit_downs, brokens = [], [], []
        async for doc in db["limit_list"].find({"trade_date": td}, {"_id": 0}):
            ts = doc.get("ts_code", "")
            daily = pct_map.get(ts, {})
            
            # 格式1: limit字段存在(旧格式)
            lim = doc.get("limit")
            if lim:
                item = {
                    "ts_code": ts,
                    "name": doc.get("name", "") or name_map.get(ts, ""),
                    "close": daily.get("close") or doc.get("close", 0),
                    "pct_chg": daily.get("pct_chg", 0),
                    "limit_times": doc.get("limit_times", 1),
                    "open_times": doc.get("open_times", 0),
                    "fd_amount": 0,
                    "turnover": doc.get("fc_ratio", 0),
                    "first_time": doc.get("first_time", ""),
                    "industry": "",
                }
                if lim == "U":
                    limit_ups.append(item)
                elif lim == "D":
                    limit_downs.append(item)
                elif lim == "B":
                    brokens.append(item)
            else:
                # 格式2: up_limit/down_limit(新格式)
                # 从日线pct_chg判断是否涨停
                pct = daily.get("pct_chg", 0)
                close_price = daily.get("close", 0)
                up_limit = doc.get("up_limit", 0)
                down_limit = doc.get("down_limit", 0)
                
                item = {
                    "ts_code": ts,
                    "name": name_map.get(ts, ""),
                    "close": close_price,
                    "pct_chg": pct,
                    "limit_times": 0,
                    "open_times": 0,
                    "fd_amount": 0,
                    "turnover": 0,
                    "first_time": "",
                    "industry": "",
                }
                # 涨停判断: 收盘价>=涨停价 或 涨幅>=9.8%(考虑四舍五入)
                if close_price > 0 and up_limit > 0 and close_price >= up_limit * 0.998:
                    limit_ups.append(item)
                elif close_price > 0 and down_limit > 0 and close_price <= down_limit * 1.002:
                    limit_downs.append(item)
        
        return {
            "success": True,
            "data": {
                "limit_up": limit_ups,
                "limit_down": limit_downs,
                "broken": brokens,
                "trade_date": str(td),
                "source": "mongodb",
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


@router.post("/rollback-today-orders")
async def rollback_today_orders(reason: str = "手动回滚今日订单"):
    """【v2.9.96i】回滚今日所有 filled 订单
    
    与 /reset 区别: /reset 是全量重置(删除所有历史订单).
    本接口只回滚今日, 保留历史订单.
    
    同步处理:
    1. broker_orders 今日 status=filled → rolled_back
    2. broker_positions 今日中产生的持仓 → 重算不包含今日变化
    3. scanner_timeline 今日 buy/sell → 删除
    4. broker_accounts 代码作为是否需要重算 (现金应该倒滑今日交易)
    
    使用场景: 非交易时段误下单 / scanner bug 产生错误订单 / 手动测试后清理
    """
    from datetime import datetime
    scanner = await _get_scanner()
    if not scanner._broker:
        raise HTTPException(400, "Broker未初始化")
    
    today = datetime.now().strftime("%Y%m%d")
    today_int = int(today)
    account_id = scanner._broker.account.account_id
    rollback_at = datetime.now().isoformat()
    
    summary = {"orders_rolled_back": 0, "timeline_cleaned": 0, "cash_credit": 0.0, "cash_debit": 0.0}
    
    try:
        if not await scanner._broker._ensure_mongo():
            raise HTTPException(500, "MongoDB不可用")
        db = scanner._broker._mongo_db
        
        # 1. 计算今日资金变动 (为了重算 cash)
        net_cash_change = 0.0  # 买出现金, 卖入现金
        async for o in db.broker_orders.find({
            "account_id": account_id, 
            "trade_date": {"$in": [today, today_int]},
            "status": "filled"
        }):
            qty = o.get("filled_qty") or o.get("quantity") or 0
            price = o.get("filled_price") or o.get("price") or 0
            amount = qty * price
            comm = o.get("commission", 0) or 0
            tax = o.get("stamp_tax", 0) or 0
            if o.get("side") == "buy":
                net_cash_change += amount + comm   # 买出
                summary["cash_credit"] += amount + comm
            elif o.get("side") == "sell":
                net_cash_change -= (amount - comm - tax)  # 卖入
                summary["cash_debit"] += amount - comm - tax
        
        # 2. 标记今日订单为 rolled_back
        result = await db.broker_orders.update_many(
            {"account_id": account_id, "trade_date": {"$in": [today, today_int]}, "status": "filled"},
            {"$set": {
                "status": "rolled_back",
                "rolled_back": True,
                "rolled_back_at": rollback_at,
                "rolled_back_reason": reason,
                "filled_status_original": "filled",
            }}
        )
        summary["orders_rolled_back"] = result.modified_count
        
        # 3. 清理今日 timeline buy/sell
        result2 = await db.scanner_timeline.delete_many({
            "account_id": account_id, 
            "trade_date": {"$in": [today, today_int]},
            "action": {"$in": ["buy", "sell"]}
        })
        summary["timeline_cleaned"] = result2.deleted_count
        
        # 4. 清理今日中产生的今日买入持仓 (today_buy_qty>0 的或 buy_date=今天 的仅今日交易)
        # 这里简化: 只处理 broker_orders 重算后净为0的股票
        from collections import defaultdict
        net_qty = defaultdict(int)
        async for o in db.broker_orders.find(
            {"account_id": account_id, "status": "filled"},
            {"ts_code": 1, "side": 1, "filled_qty": 1, "quantity": 1}
        ):
            tc = o.get("ts_code", "")
            if not tc: continue
            qty = o.get("filled_qty") or o.get("quantity") or 0
            if o.get("side") == "buy":
                net_qty[tc] += qty
            elif o.get("side") == "sell":
                net_qty[tc] -= qty
        # 对净量<=0 的在 broker_positions 中删除
        cleared = 0
        for tc in list(net_qty.keys()):
            if net_qty[tc] <= 0:
                r = await db.broker_positions.delete_one({"account_id": account_id, "ts_code": tc})
                if r.deleted_count > 0: cleared += 1
        summary["positions_cleared"] = cleared
        
        # 5. 重算 broker_accounts 现金
        # 原现金 + 今日净变化(反向) = 回滚后现金
        acc = await db.broker_accounts.find_one({"account_id": account_id})
        if acc:
            new_cash = (acc.get("available_cash", 0) or 0) + net_cash_change  # 反向倒滑
            await db.broker_accounts.update_one(
                {"account_id": account_id},
                {"$set": {
                    "available_cash": new_cash,
                    "updated_at": rollback_at,
                    "rollback_at": rollback_at,
                    "rollback_reason": reason,
                }}
            )
            # 同步到内存
            scanner._broker.account.available_cash = new_cash
            summary["cash_after_rollback"] = new_cash
        
        # 6. 清理内存 _timeline 中今日 buy/sell
        try:
            scanner._timeline = [t for t in scanner._timeline 
                if not (t.get("action") in ("buy", "sell") and 
                       str(t.get("trade_date", "")) == today)]
            # 同步重载 positions 到内存
            scanner._broker.positions = {tc: p for tc, p in scanner._broker.positions.items() if net_qty.get(tc, 0) > 0}
        except Exception:
            pass
        
        logger.warning(f"[ROLLBACK] {reason}: {summary}")
        return {"success": True, "data": {"message": "今日订单已回滚", "summary": summary}}
    
    except Exception as e:
        logger.error(f"[ROLLBACK] 失败: {e}", exc_info=True)
        return {"success": False, "message": str(e), "summary": summary}


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
        try:
            body = await request.json()
        except Exception:
            body = {}
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
    
    v2.9.92v: 始终从position-risk-matrix获取数据(scanner未运行时也能显示)
    """
    try:
        matrix_resp = await get_position_risk_matrix()
        matrix_data = matrix_resp.get('data', {}) if isinstance(matrix_resp, dict) else {}
        matrix_positions = matrix_data.get('positions', [])
        grouped = {"normal": [], "warning": [], "critical": []}
        for p in matrix_positions:
            level = p.get('risk_level', 'normal')
            grouped.setdefault(level, []).append(p)
        return {
            "success": True,
            "data": {
                "levels": grouped,
                "summary": {
                    "total": len(matrix_positions),
                    "normal": len(grouped.get('normal', [])),
                    "warning": len(grouped.get('warning', [])),
                    "critical": len(grouped.get('critical', [])),
                },
                "check_interval": 30,
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
        start_date = int((datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d"))

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
        # Scanner未运行时: 从MongoDB直接构建风控矩阵(和analysis API同源)
        try:
            from core.managers import mongo_manager
            if not mongo_manager.is_initialized:
                return {"success": True, "data": {"positions": [], "global": {}}}
            db = mongo_manager.db
            
            # 读账户
            acct_doc = await db["broker_accounts"].find_one({"account_id": "default"})
            if not acct_doc:
                return {"success": True, "data": {"positions": [], "global": {}}}
            
            # 读行业映射
            industry_map = {}
            async for doc in db["stock_basic"].find({}, {"_id": 0, "ts_code": 1, "industry": 1}):
                industry_map[doc.get("ts_code", "")] = doc.get("industry", "")
            
            # 策略风控参数
            from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK, STRATEGY_CONFIGS
            strategy_cn = {"halfway_chase": "半路追涨", "first_limit_up": "首板打板", "dragon_head": "龙头低吸", "limit_down_qiao": "跌停翘板"}
            
            # 构建矩阵
            matrix = []
            industry_exp = {}
            max_single_pct = 0
            total_mv = 0
            
            positions_data = []
            async for doc in db["broker_positions"].find({"account_id": "default"}):
                positions_data.append(doc)
            
            for pos_doc in positions_data:
                cost = pos_doc.get("avg_cost", 0)
                cur = pos_doc.get("current_price", 0)
                qty = pos_doc.get("total_qty", 0)
                ts_code = pos_doc.get("ts_code", "")
                stock_name = pos_doc.get("stock_name", "")
                strategy = pos_doc.get("strategy", "halfway_chase")
                
                if cost <= 0 or qty <= 0:
                    continue
                
                mv = cur * qty
                total_mv += mv
                
                strat_key = strategy
                for k, v in STRATEGY_CONFIGS.items():
                    if v.get("display_name") == strategy or k == strategy:
                        strat_key = k
                        break
                strat_cfg = STRATEGY_CONFIGS.get(strat_key, {})
                sl_pct = strat_cfg.get("stop_loss_pct", GLOBAL_RISK.get("stop_loss_pct", 0.03))
                tp_pct = strat_cfg.get("take_profit_pct", GLOBAL_RISK.get("take_profit_pct", 0.12))
                if sl_pct > 1: sl_pct /= 100
                if tp_pct > 1: tp_pct /= 100
                
                sl_price = cost * (1 - sl_pct)
                tp_price = cost * (1 + tp_pct)
                dist_sl = (cur - sl_price) / cur * 100 if cur > 0 else 0
                dist_tp = (tp_price - cur) / cur * 100 if cur > 0 else 0
                profit_pct = (cur - cost) / cost * 100 if cost > 0 else 0
                profit_amount = (cur - cost) * qty
                
                position_pct = 0  # will calc after total_mv
                industry = industry_map.get(ts_code, "未知")
                industry_exp[industry] = industry_exp.get(industry, 0) + mv
                
                # Risk level
                if cur <= sl_price:
                    risk_level = "critical"
                elif dist_sl < 2:
                    risk_level = "warning"
                else:
                    risk_level = "normal"
                
                risk_score = min(max(0, 30 - dist_sl * 3) + min(abs(profit_pct), 20) + (10 if risk_level == "critical" else 0), 100)
                
                matrix.append({
                    "ts_code": ts_code, "stock_name": stock_name,
                    "strategy": strategy, "strategy_name": strategy_cn.get(strat_key, strategy),
                    "industry": industry, "current_price": cur, "cost_price": cost,
                    "profit_pct": round(profit_pct, 2), "profit_amount": round(profit_amount, 0),
                    "market_value": round(mv, 0), "position_pct": 0,  # placeholder
                    "stop_loss_price": round(sl_price, 2), "take_profit_price": round(tp_price, 2),
                    "dist_to_stop": round(dist_sl, 1), "dist_to_take": round(dist_tp, 1),
                    "risk_level": risk_level, "risk_score": round(risk_score, 0),
                    "trailing_stop": None,
                })
            
            # Fill position_pct
            total_assets = acct_doc.get("available_cash", 0) + total_mv
            for m in matrix:
                m["position_pct"] = round(m["market_value"] / max(total_assets, 1) * 100, 1)
                max_single_pct = max(max_single_pct, m["position_pct"])
            
            top_industry = max(industry_exp, key=industry_exp.get) if industry_exp else "无"
            top_industry_pct = industry_exp.get(top_industry, 0) / max(total_assets, 1) * 100 if industry_exp else 0
            
            normal = len([m for m in matrix if m["risk_level"] == "normal"])
            warning = len([m for m in matrix if m["risk_level"] == "warning"])
            critical = len([m for m in matrix if m["risk_level"] == "critical"])
            
            return {"success": True, "data": {
                "positions": matrix,
                "global": {
                    "total_assets": round(total_assets, 0),
                    "cash_ratio": round(acct_doc.get("available_cash", 0) / max(total_assets, 1) * 100, 1),
                    "position_ratio": round(total_mv / max(total_assets, 1) * 100, 1),
                    "max_single_pct": round(max_single_pct, 1),
                    "top_industry_concentration": round(top_industry_pct, 1),
                    "industry_exposure": {k: round(v / max(total_mv, 1) * 100, 1) for k, v in industry_exp.items()},
                    "position_count": len(matrix),
                    "risk_summary": {"normal": normal, "warning": warning, "critical": critical},
                },
                "_fallback": True,
            }}
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"success": True, "data": {"positions": [], "global": {}}}

    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": []}
        positions = scanner._broker.get_positions()
        acct = scanner._broker.get_account()
        
        # 【v2.9.92v】如果broker持仓为0或market_value=0但MongoDB有数据(scanner未load_state)
        if not positions or (acct.market_value == 0 and positions):
            try:
                positions_data = []
                async for doc in mongo_manager.db["broker_positions"].find({"account_id": "default"}):
                    positions_data.append(doc)
                if positions_data and (not positions or acct.market_value == 0):
                    if not positions:
                        # 用MongoDB数据构建positions列表
                        from nodes.market_monitor.broker import Position
                        for doc in positions_data:
                            if doc.get("total_qty", 0) > 0:
                                pos = Position(
                                    ts_code=doc.get("ts_code", ""),
                                    stock_name=doc.get("stock_name", ""),
                                    total_qty=doc.get("total_qty", 0),
                                    available_qty=doc.get("available_qty", 0),
                                    avg_cost=doc.get("avg_cost", 0),
                                    current_price=doc.get("current_price", 0),
                                    profit_pct=((doc.get("current_price", 0) - doc.get("avg_cost", 0)) / doc.get("avg_cost", 1) * 100) if doc.get("avg_cost", 0) > 0 else 0,
                                    strategy=doc.get("strategy", "halfway_chase"),
                                )
                                positions.append(pos)
                    # 重建account数据(从MongoDB)
                    acct_doc = await mongo_manager.db["broker_accounts"].find_one({"account_id": "default"})
                    if acct_doc:
                        mv = sum(doc.get("current_price", 0) * doc.get("total_qty", 0) for doc in positions_data if doc.get("total_qty", 0) > 0)
                        cash = acct_doc.get("available_cash", 0)
                        acct.total_assets = cash + mv
                        acct.available_cash = cash
                        acct.market_value = mv
            except Exception:
                pass
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
            # 从策略风控参数读取SL/TP百分比(fallback 3%/12%)
            try:
                risk_params = scanner._get_strategy_risk(pos.strategy or "unknown") if hasattr(scanner, '_get_strategy_risk') else {}
            except Exception:
                risk_params = {}
            sl_pct = risk_params.get("stop_loss_pct", 0.03)
            tp_pct = risk_params.get("take_profit_pct", 0.12)
            # 防御: 百分比形式(>1)自动转小数
            if sl_pct > 1: sl_pct = sl_pct / 100
            if tp_pct > 1: tp_pct = tp_pct / 100
            sl_price = cost * (1 - sl_pct) if cost > 0 else 0
            tp_price = cost * (1 + tp_pct) if cost > 0 else 0
            # 防御除零: cur=0时dist设为0(不产生NaN)
            if cur > 0 and cost > 0:
                dist_sl = (cur - sl_price) / cur * 100
                dist_tp = (tp_price - cur) / cur * 100
            else:
                dist_sl = 0.0
                dist_tp = 0.0
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
                "stop_loss_price": round(sl_price, 2), "take_profit_price": round(tp_price, 2),
                "volatility": round(abs(pos.profit_pct), 2), "turnover_rate": turnover,
                "risk_score": round(risk_score, 0), "risk_level": risk_levels.get(pos.ts_code) or ("critical" if cur <= sl_price else "warning" if dist_sl < 2 else "normal"),
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


