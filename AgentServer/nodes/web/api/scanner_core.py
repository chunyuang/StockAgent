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
    mark_timeline_session, normalize_data_mode,
)

router = APIRouter(prefix="/scanner", tags=["核心状态/控制/持仓/信号"])


async def _load_recent_signal_history(scanner, date_int: Optional[int] = None, limit: int = 500) -> List[Dict[str, Any]]:
    """从MongoDB读取最近一次扫描信号，供非交易时间/重启后回看。"""
    try:
        from core.managers import mongo_manager
        if not getattr(mongo_manager, "is_initialized", False):
            return []
        db = mongo_manager.db
        account_id = getattr(scanner, "account_id", "default") or "default"
        if date_int:
            query = {"account_id": account_id, "trade_date": {"$in": [date_int, str(date_int)]}}
        else:
            latest = await db["scanner_signals"].find_one(
                {"account_id": account_id}, sort=[("trade_date", -1), ("created_at", -1)]
            )
            if not latest:
                return []
            latest_date = latest.get("trade_date")
            query = {"account_id": account_id, "trade_date": {"$in": [latest_date, str(latest_date), int(latest_date)] if str(latest_date).isdigit() else [latest_date]}}
        docs = await db["scanner_signals"].find(query).sort("scan_time", 1).limit(limit).to_list(limit)
        result = []
        for d in docs:
            d.pop("_id", None)
            d.pop("account_id", None)
            d["_historical_signal"] = True
            result.append(d)
        _fill_stock_names(result, scanner)
        return result
    except Exception as e:
        logger.debug(f"读取历史信号失败: {e}")
        return []


@router.get("/all")
async def get_all_scanner_data(date: str = None, mode: str = "production", include_debug: bool = False):
    """一次性获取所有扫描器数据(减少前端HTTP开销)
    
    合并: status + signals + positions + timeline + orders
    替代前端5次并发请求, 减少延迟和HTTP开销
    
    Args:
        date: 历史日期(YYYYMMDD或YYYY-MM-DD), 不传或today=实时数据
        mode: production(默认) / debug
        include_debug: 是否包含非交易时段/调试timeline记录，默认False
    """
    # 【v2.9.97h】日期参数: 支持历史查询
    from nodes.web.api.unified import _normalize_date
    date_int = _normalize_date(date)
    today_int = int(__import__('datetime').datetime.now().strftime("%Y%m%d"))
    is_historical = date_int is not None and date_int != today_int
    
    scanner = await _get_scanner()
    
    # 状态
    status_resp = await get_scanner_status()
    status_data = status_resp.get("data", {}) if isinstance(status_resp, dict) else {}
    
    # 信号: 实时优先；无实时信号时回退最近一次历史信号，方便非交易时间回看
    signals_data = scanner.get_signals()
    _fill_stock_names(signals_data, scanner)
    signals_is_history = False
    if not signals_data:
        signals_data = await _load_recent_signal_history(scanner, date_int=date_int)
        signals_is_history = bool(signals_data)
    else:
        # 【v2.9.99-r5】scanner 内存只保留最近信号, 合并 DB 全天历史信号供前端按小时分组
        # 去重键: ts_code + strategy + scan_time, 内存优先 (拿最新状态 new/executed/skipped)
        try:
            history_signals = await _load_recent_signal_history(scanner, date_int=date_int)
            if history_signals:
                seen = {(s.get("ts_code"), s.get("strategy"), s.get("scan_time")) for s in signals_data}
                for hs in history_signals:
                    k = (hs.get("ts_code"), hs.get("strategy"), hs.get("scan_time"))
                    if k not in seen:
                        hs["_historical_signal"] = True
                        signals_data.append(hs)
                        seen.add(k)
        except Exception as _e:
            logger.debug(f"合并历史信号失败: {_e}")
    
    # 【v2.9.97h】持仓: 历史日期从broker_orders重建, 当日从broker_positions读
    positions_data = []
    today_closed = []  # 【v2.9.97h-v19 恢复】今日已平仓, 默认空避免历史路径 NameError
    try:
        from core.managers import mongo_manager
        if mongo_manager.db is not None:
            account_id = scanner.account_id if hasattr(scanner, 'account_id') else "default"
            if is_historical:
                # 历史: 从broker_orders重建到指定日期收盘的持仓快照
                from nodes.web.api.unified import fetch_unified_positions
                pos_result = await fetch_unified_positions(date=str(date_int), account_id=account_id)
                positions_data = pos_result if isinstance(pos_result, list) else pos_result.get("positions", []) if isinstance(pos_result, dict) else []
                for p in positions_data:
                    p["_historical"] = True
                    p["status_at"] = str(date_int)
            else:
                # 当日: 从broker_positions读(唯一真相源)
                from nodes.web.api.scanner_analysis import _compute_positions_from_broker
                positions_data = await _compute_positions_from_broker(mongo_manager.db, account_id)
                # 【v2.9.97h-v19 恢复】补充今日已平仓记录 (涵盖是否当日买入均可)
                try:
                    today_int_v = int(datetime.now().strftime('%Y%m%d'))
                    # 1. 找今天所有 filled 卖出
                    from nodes.web.api.unified import query_trades, query_trade_one
                    today_sells = await query_trades(
                        mongo_manager.db, account_id=account_id, side="sell",
                        date=today_int_v, status="filled",
                        sort=[("create_time", 1)], limit=500)
                    for sell in today_sells:
                        tc = sell.get("ts_code", "")
                        if not tc:
                            continue
                        # 【v2.9.120】跳过 filled_amount=0 的空订单(强制空仓但持仓已被其他原因卖出)
                        sell_qty_check = int(sell.get("filled_qty") or sell.get("quantity") or 0)
                        if sell_qty_check <= 0:
                            continue
                        # 2. 找对应的买入记录 (按 ts_code, trade_date <= today, side=buy, 最近一次)
                        buy = await query_trade_one(
                            mongo_manager.db, account_id=account_id,
                            ts_code=tc, side="buy",
                            date_lte=today_int_v, status="filled",
                            sort=[("trade_date", -1), ("create_time", -1)])
                        # 【v2.9.99-r3】broker 不填 profit_pct/profit_amount → 自己用 buy/sell 算
                        buy_price = float(buy.get("filled_price") or buy.get("price") or 0) if buy else 0
                        buy_qty = int(buy.get("filled_qty") or buy.get("quantity") or 0) if buy else 0
                        sell_price = float(sell.get("filled_price") or sell.get("price") or 0)
                        sell_qty = int(sell.get("filled_qty") or sell.get("quantity") or 0)
                        # 优先用 broker 的 profit_*; 没填则自己算
                        raw_pct = float(sell.get("profit_pct") or 0)
                        raw_amt = float(sell.get("profit_amount") or 0)
                        if raw_pct == 0 and buy_price > 0 and sell_price > 0:
                            raw_pct = (sell_price - buy_price) / buy_price * 100
                        if raw_amt == 0 and buy_price > 0 and sell_price > 0 and sell_qty > 0:
                            raw_amt = (sell_price - buy_price) * sell_qty
                        entry = {
                            "ts_code": tc,
                            "stock_name": sell.get("stock_name", ""),
                            "buy_time": (buy.get("create_time") or buy.get("fill_time") or "") if buy else "",
                            "buy_price": round(buy_price, 2),
                            "buy_qty": buy_qty,
                            "buy_date": buy.get("trade_date", "") if buy else "",
                            "sell_time": sell.get("create_time") or sell.get("fill_time") or "",
                            "sell_price": round(sell_price, 2),
                            "sell_qty": sell_qty,
                            "profit_pct": round(raw_pct, 2),
                            "profit_amount": round(raw_amt, 0),
                            "reason": sell.get("reason", ""),  # 卖出原因 (止损/止盈/手动等)
                        }
                        today_closed.append(entry)
                    today_closed.sort(key=lambda x: x.get("sell_time") or "")
                except Exception as _e:
                    today_closed = []
                # 用scanner内存补充实时字段
                if scanner._broker:
                    scanner_positions = {p.get("ts_code"): p for p in scanner.get_positions()}
                    for i, p in enumerate(positions_data):
                        tc = p.get("ts_code")
                        sp = scanner_positions.get(tc)
                        if sp:
                            for key in ["trailing_stop_activated", "trailing_stop_pct",
                                         "risk_level", "risk_desc", "hold_hours",
                                         "stop_loss_reason", "take_profit_reason"]:
                                if sp.get(key) is not None and p.get(key) is None:
                                    positions_data[i][key] = sp[key]
    except Exception:
        if not is_historical:
            positions_data = scanner.get_positions()
    _fill_stock_names(positions_data, scanner)
    
    # 【v2.9.97h】时间线: 历史从MongoDB读, 当日从scanner内存+fallback
    timeline_data = []
    debug_filtered_count = 0
    try:
        from core.managers import mongo_manager
        if mongo_manager.db is not None:
            db = mongo_manager.db
            account_id = scanner.account_id if hasattr(scanner, 'account_id') else "default"
            query_date = str(date_int) if is_historical else __import__('datetime').datetime.now().strftime("%Y%m%d")
            # 1. 从scanner_timeline读blocked等决策日志
            async for doc in db["scanner_timeline"].find(
                {"account_id": account_id, "trade_date": {"$in": [query_date, int(query_date)]}}
            ).sort("_id", 1):
                doc.pop("_id", None)
                doc.pop("account_id", None)
                doc = mark_timeline_session(doc)
                if normalize_data_mode(mode, include_debug) != "debug" and doc.get("action") == "blocked" and doc.get("session") == "off_session":
                    debug_filtered_count += 1
                    continue
                if is_historical:
                    doc["_historical"] = True
                timeline_data.append(doc)
            # 2. 从broker_orders读buy/sell交易(唯一真相源)
            from nodes.web.api.unified import fetch_unified_trades
            trades = await fetch_unified_trades(date=query_date, account_id=account_id)
            for t in trades:
                entry = {
                    "action": t.get("side"),
                    "ts_code": t.get("ts_code"),
                    "stock_name": t.get("stock_name"),
                    "price": t.get("filled_price"),
                    "shares": t.get("filled_qty"),
                    "strategy": t.get("strategy"),
                    "reason": t.get("reason"),
                    "time": t.get("fill_time") or t.get("create_time"),
                    "trade_date": t.get("trade_date"),
                    "profit_pct": t.get("profit_pct"),
                    "profit_amount": t.get("profit_amount"),
                }
                entry = mark_timeline_session(entry)
                if is_historical:
                    entry["_historical"] = True
                timeline_data.append(entry)
            timeline_data.sort(key=lambda x: str(x.get("time") or x.get("fill_time") or x.get("create_time") or ""))
            # 当日fallback: 如果scanner内存有数据且MongoDB没有
            if not is_historical and not timeline_data:
                timeline_data = scanner.get_timeline()
    except Exception:
        if not is_historical:
            timeline_data = scanner.get_timeline()
    _fill_stock_names(timeline_data, scanner)
    
    # 【v2.9.97h】订单: 历史日期从broker_orders读, 当日保持现有逻辑
    orders_data = []
    try:
        from core.managers import mongo_manager
        if mongo_manager.db is not None:
            db = mongo_manager.db
            account_id = scanner.account_id if hasattr(scanner, 'account_id') else "default"
            if is_historical:
                query_date = str(date_int)
                docs = await db["broker_orders"].find({
                    "account_id": account_id,
                    "trade_date": {"$in": [query_date, int(query_date)]},
                }).sort("create_time", 1).limit(50).to_list(50)
                for d in docs:
                    d.pop("_id", None)
                    d["_historical"] = True
                    orders_data.append(d)
            elif scanner._broker and await scanner._broker._ensure_mongo():
                db = scanner._broker._mongo_db
                orders_query = {"account_id": scanner._broker.account.account_id}
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
    
    # 累计盈亏统计
    total_profit_amount = 0
    for o in orders_data:
        if o.get("side") == "sell" and o.get("profit_amount"):
            total_profit_amount += o["profit_amount"]
    if total_profit_amount == 0:
        for item in timeline_data:
            if item.get("action") == "sell" and item.get("profit_amount"):
                total_profit_amount += item["profit_amount"]
    
    return _sanitize({
        "success": True,
        "data": {
            "status": status_data,
            "signals": signals_data,
            "positions": positions_data,
            "today_closed_trades": today_closed,  # 【v2.9.97h-v19 恢复】今日已平仓记录
            "timeline": timeline_data,
            "orders": orders_data,
            "_historical": is_historical,
            "_query_date": date_int,
            "_signals_historical": signals_is_history,
            "summary": {
                "total_profit_amount": round(total_profit_amount, 2),
                "debug_filtered_count": debug_filtered_count,
                "mode": normalize_data_mode(mode, include_debug),
                "include_debug": normalize_data_mode(mode, include_debug) == "debug",
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
                            from nodes.web.api.unified import _build_position_dict
                            # 【v2.9.97h-v7】使用unified统一的position字段生成，避免与AccountTab/AnalysisTab不一致
                            built = []
                            for p in pos_docs:
                                qty = p.get("total_qty", 0) or 0
                                avg_cost = float(p.get("avg_cost", 0) or 0)
                                cur_price = float(p.get("current_price", 0) or 0)
                                profit_pct = (cur_price - avg_cost) / avg_cost * 100 if avg_cost > 0 else 0.0
                                pos = _build_position_dict(p, qty, avg_cost, cur_price, profit_pct)
                                # 补充scanner_core专有字段
                                pos["strategy_name"] = p.get("strategy_name", "") or pos.get("strategy", "")
                                pos["today_buy"] = p.get("today_buy_qty", 0) or 0
                                pos["risk_level"] = pos.get("risk_level") or ("high" if pos["stop_loss_status"] == "broken" else "elevated" if pos["stop_loss_status"] == "near" else "normal")
                                built.append(pos)
                            status["positions"] = built
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
async def get_signals(date: str = None):
    """获取当前活跃信号；无实时信号时回退最近历史信号。"""
    scanner = await _get_scanner()
    data = scanner.get_signals()
    history = False
    if not data:
        try:
            from nodes.web.api.unified import _normalize_date
            date_int = _normalize_date(date)
        except Exception:
            date_int = None
        data = await _load_recent_signal_history(scanner, date_int=date_int)
        history = bool(data)
    return _sanitize({"success": True, "data": data, "historical": history})



@router.get("/positions")
async def get_positions():
    """获取实时持仓

    【v2.9.99-r8 fix P1 #5】统一使用 _compute_positions_from_broker, 与 /scanner/analysis 合并数据源
    以前用 scanner.get_positions() 返回的 不包含 risk_monitor_active 等风控字段, 导致前端误报“风控❌”
    """
    scanner = await _get_scanner()
    try:
        from core.managers import mongo_manager
        from nodes.web.api.scanner_analysis import _compute_positions_from_broker
        account_id = "default"
        if scanner._broker and hasattr(scanner._broker, 'account') and scanner._broker.account:
            account_id = scanner._broker.account.account_id
        positions = await _compute_positions_from_broker(mongo_manager.db, account_id)
        return _sanitize({"success": True, "data": positions})
    except Exception as e:
        from loguru import logger
        logger.warning(f"[POSITIONS] _compute_positions_from_broker 失败, 回退到 scanner.get_positions(): {e}")
        # 回退方案: 避免完全丢数据
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
    """获取账户信息(资金/持仓/盈亏) — 通过unified层"""
    scanner = await _get_scanner()
    # 【v2.9.110】统一走unified层, 消除6次MongoDB直查
    try:
        from .unified import fetch_unified_account
        data = await fetch_unified_account(account_id="default")
        if data.get("total_assets", 0) > 0:
            return {"success": True, "data": data}
    except Exception as e:
        from loguru import logger
        import traceback
        logger.error(f"[ACCOUNT] unified层失败, 回退到内存: {e}\n{traceback.format_exc()}")
    
    # Fallback: scanner运行中时从内存读
    if scanner._broker:
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
    
    # 最终兜底
    return {
        "success": True,
        "data": {
            "account_id": "default",
            "total_assets": 0.0,
            "available_cash": 0.0,
            "market_value": 0.0,
            "today_profit": 0.0,
            "total_profit": 0.0,
            "position_count": 0,
            "position_ratio": 0.0,
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
        
        from nodes.web.api.scanner_system import _enrich_limit_times_from_history
        limit_ups = await _enrich_limit_times_from_history(db, td, limit_ups)

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
async def reset_account(request: Request):
    """清仓重置(清空所有持仓/订单, 恢复初始资金)
    
    【v2.9.99-r7 数据保护】
    1. 必须传 confirm=I-UNDERSTAND-DATA-WILL-BE-LOST (二次确认)
    2. 记录完整审计日志 (调用时间/IP/被删数量/UA)
    3. 删除前自动备份 broker_orders / broker_positions / broker_accounts 到备份集合
    """
    from fastapi import Request as _Req  # noqa: F401
    import json as _json
    from datetime import datetime as _dt
    
    # 【防护1】二次确认
    try:
        body = await request.json()
    except Exception:
        body = {}
    confirm = body.get("confirm") or request.query_params.get("confirm", "")
    if confirm != "I-UNDERSTAND-DATA-WILL-BE-LOST":
        raise HTTPException(
            400,
            "拒绝重置: 必须传递 confirm='I-UNDERSTAND-DATA-WILL-BE-LOST' 以确认清空所有交易数据. "
            "请调用者注意: 此操作不可逆! "
        )
    
    scanner = await _get_scanner()
    if not scanner._broker:
        raise HTTPException(400, "Broker未初始化")
    
    # 【防护2】重置前先记录当前状态 + 备份到备份集合
    audit_log = {
        "event": "scanner_reset",
        "timestamp": _dt.now().isoformat(),
        "caller_ip": request.client.host if request.client else "unknown",
        "user_agent": request.headers.get("user-agent", "unknown"),
        "x_forwarded_for": request.headers.get("x-forwarded-for", ""),
        "x_real_ip": request.headers.get("x-real-ip", ""),
        "account_id": scanner._broker.account.account_id,
        "before_state": {},
        "backup_count": {},
    }
    
    try:
        if await scanner._broker._ensure_mongo():
            db = scanner._broker._mongo_db
            account_id = scanner._broker.account.account_id
            backup_suffix = _dt.now().strftime("%Y%m%d_%H%M%S")
            
            # 记录被删数量
            audit_log["before_state"] = {
                "broker_orders": await db["broker_orders"].count_documents({"account_id": account_id}),
                "broker_positions": await db["broker_positions"].count_documents({"account_id": account_id}),
                "broker_accounts": await db["broker_accounts"].count_documents({"account_id": account_id}),
                "scanner_timeline": await db["scanner_timeline"].count_documents({"account_id": account_id}),
                "performance_snapshots": await db["performance_snapshots"].count_documents({"account_id": account_id}),
            }
            audit_log["total_account"] = await db["broker_accounts"].find_one({"account_id": account_id})
            
            # 备份到【备份集合】 broker_orders_reset_backup_<时间戳>
            for src_coll in ["broker_orders", "broker_positions", "broker_accounts", "scanner_timeline", "performance_snapshots"]:
                backup_coll = f"{src_coll}_reset_backup_{backup_suffix}"
                src_count = audit_log["before_state"].get(src_coll, 0)
                if src_count > 0:
                    # aggregate $out 复制到备份集合
                    try:
                        await db[src_coll].aggregate([
                            {"$match": {"account_id": account_id}},
                            {"$out": backup_coll}
                        ]).to_list(None)
                        audit_log["backup_count"][src_coll] = src_count
                        logger.info(f"[RESET-BACKUP] {src_coll}({src_count}条) -> {backup_coll}")
                    except Exception as _be:
                        logger.error(f"[RESET-BACKUP] {src_coll} 备份失败: {_be}")
                        # 备份失败不能重置!
                        raise HTTPException(500, f"备份 {src_coll} 失败: {_be}, 重置已取消")
            
            # 写入审计日志表 (独立于被删表外)
            await db["scanner_reset_audit_log"].insert_one(audit_log)
            logger.warning(f"[RESET-AUDIT] /scanner/reset 调用: "
                          f"IP={audit_log['caller_ip']}, 将清空 {sum(audit_log['before_state'].values())} 条记录")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[RESET-AUDIT] 审计+备份阶段失败: {e}")
        raise HTTPException(500, f"审计备份失败, 重置取消: {e}")
    
    # 以下才是原实际重置逻辑
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
async def rollback_today_orders(request: Request, reason: str = "手动回滚今日订单"):
    """【v2.9.96i】回滚今日所有 filled 订单
    
    与 /reset 区别: /reset 是全量重置(删除所有历史订单).
    本接口只回滚今日, 保留历史订单.
    
    【v2.9.99-r7 数据保护】必须传 confirm=I-UNDERSTAND-DATA-WILL-BE-LOST 以二次确认
    
    同步处理:
    1. broker_orders 今日 status=filled → rolled_back
    2. broker_positions 今日中产生的持仓 → 重算不包含今日变化
    3. scanner_timeline 今日 buy/sell → 删除
    4. broker_accounts 代码作为是否需要重算 (现金应该倒滑今日交易)
    
    使用场景: 非交易时段误下单 / scanner bug 产生错误订单 / 手动测试后清理
    """
    from datetime import datetime
    
    # 【v2.9.99-r7 防护】2次确认
    try:
        body = await request.json()
    except Exception:
        body = {}
    confirm = body.get("confirm") or request.query_params.get("confirm", "")
    if confirm != "I-UNDERSTAND-DATA-WILL-BE-LOST":
        raise HTTPException(
            400,
            "拒绝回滚: 必须传递 confirm='I-UNDERSTAND-DATA-WILL-BE-LOST' 以确认回滚今日订单. "
            "请调用者注意: 今日所有 filled 订单会被标为 rolled_back, 不可逆! "
        )
    
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
            if mongo_manager.db is not None:
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
                "open": round(doc.get("open", 0), 2), "high": round(doc.get("high", 0), 2),
                "low": round(doc.get("low", 0), 2), "close": round(doc.get("close", 0), 2),
                "volume": doc.get("vol", 0), "pct_chg": round(doc.get("pct_chg", 0), 2),
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
async def get_position_risk_matrix(date: str = None):
    """持仓风控矩阵 + 全局风险仪表，支持历史日期查询"""
    from nodes.web.api.unified import _normalize_date
    date_int = _normalize_date(date)
    today_int = int(__import__('datetime').datetime.now().strftime("%Y%m%d"))
    is_historical = date_int is not None and date_int != today_int
    scanner = await _get_scanner()
    if not scanner._broker:
        # Scanner未运行时: 从MongoDB直接构建风控矩阵(和analysis API同源)
        try:
            from core.managers import mongo_manager
            if not mongo_manager.is_initialized:
                return {"success": True, "data": {"positions": [], "global": {}}}
            db = mongo_manager.db
            
            # 读账户
            # 【v2.9.110】统一通过unified层获取账户数据
            from nodes.web.api.unified import fetch_unified_account
            acct_unified = await fetch_unified_account(account_id="default")
            # 构造兼容acct_doc的结构(后续代码读available_cash)
            acct_doc = {"available_cash": acct_unified.get("available_cash", 0)} if acct_unified else None
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
            if is_historical:
                # 历史日期: 从broker_orders重建持仓
                from nodes.web.api.unified import fetch_unified_positions
                account_id = scanner.account_id if hasattr(scanner, 'account_id') else "default"
                pos_result = await fetch_unified_positions(date=str(date_int), account_id=account_id)
                positions_data = pos_result if isinstance(pos_result, list) else pos_result.get("positions", []) if isinstance(pos_result, dict) else []
            else:
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
                
                # 【v2.9.120】current_price=0时从ak_full补取最近收盘价
                if cur <= 0:
                    ak_doc = await db["stock_daily_ak_full"].find_one(
                        {"ts_code": ts_code},
                        {"close": 1, "trade_date": 1},
                        sort=[("trade_date", -1)]
                    )
                    if ak_doc and ak_doc.get("close", 0) > 0:
                        cur = float(ak_doc["close"])
                        # 同步更新MongoDB
                        await db["broker_positions"].update_one(
                            {"_id": pos_doc["_id"]},
                            {"$set": {"current_price": cur}}
                        )
                
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
                
                # 【v2.9.100+审计】15维度风险评分 (MongoDB回退模式, D10-D15简化默认)
                d1_sl = max(0, 25 - dist_sl * 5)
                d2_pos = min(position_pct / 2, 15)
                d3_loss = min(abs(profit_pct) * 2, 15)
                d4_turnover = 5  # 无换手率数据, 默认中值
                d5_vol = min(abs(profit_pct) * 0.8, 10)
                d6_trail = 0  # 无追踪止损数据
                d7_industry = min(industry_exp.get(industry, 0) / max(total_mv, 1) * 100 / 2, 5) if industry else 0
                d8_new = 0  # 无today_buy_qty数据
                d9_streak = min(max(0, -profit_pct) * 0.5, 5) if profit_pct < 0 else 0
                d10_holding_days = 0  # 无持仓天数数据
                d11_zt_premium = 0  # 无涨停溢价数据
                d12_market_risk = 0  # 无实时情绪数据
                d13_liquidity = 0  # 无成交额数据
                d14_profit_reversal = min(max(0, profit_pct - 8) * 0.3, 2) if profit_pct > 8 else 0
                d15_strategy_wr = 0  # 无策略胜率数据
                risk_score = min(d1_sl + d2_pos + d3_loss + d4_turnover + d5_vol + d6_trail + d7_industry + d8_new + d9_streak + d10_holding_days + d11_zt_premium + d12_market_risk + d13_liquidity + d14_profit_reversal + d15_strategy_wr, 100)
                
                matrix.append({
                    "ts_code": ts_code, "stock_name": stock_name,
                    "strategy": strategy, "strategy_name": strategy_cn.get(strat_key, strategy),
                    "industry": industry, "current_price": cur, "cost_price": cost,
                    "profit_pct": round(profit_pct, 2), "profit_amount": round(profit_amount, 0),
                    "market_value": round(mv, 0), "position_pct": 0,  # placeholder
                    "stop_loss_price": round(sl_price, 2), "take_profit_price": round(tp_price, 2),
                    "dist_stop_loss": round(dist_sl, 1), "dist_take_profit": round(dist_tp, 1),
                    "risk_level": risk_level, "risk_score": round(risk_score, 0),
                    "trailing_stop": None,
                })
            
            # Fill position_pct and recalc risk scores with correct values
            total_assets = acct_doc.get("available_cash", 0) + total_mv
            for m in matrix:
                m["position_pct"] = round(m["market_value"] / max(total_assets, 1) * 100, 1)
                max_single_pct = max(max_single_pct, m["position_pct"])
                # 【v2.9.120】重算依赖position_pct的风险维度
                d2_pos = min(m["position_pct"] / 2, 15)
                d7_industry = min(industry_exp.get(m.get("industry", ""), 0) / max(total_mv, 1) * 100 / 2, 5) if m.get("industry") else 0
                # 重算risk_score
                old_score = m["risk_score"]
                # d2_pos原来=0, d7_industry原来=0, 差值加上
                m["risk_score"] = round(min(old_score + d2_pos + d7_industry, 100), 0)
            
            top_industry = max(industry_exp, key=industry_exp.get) if industry_exp else "无"
            top_industry_pct = industry_exp.get(top_industry, 0) / max(total_assets, 1) * 100 if industry_exp else 0
            
            normal = len([m for m in matrix if m["risk_level"] == "normal"])
            warning = len([m for m in matrix if m["risk_level"] == "warning"])
            critical = len([m for m in matrix if m["risk_level"] == "critical"])
            
            return {"success": True, "data": {
                "positions": matrix,
                "global": {
                    "total_assets": round(total_assets, 0),
                    "total_market_value": round(total_mv, 0),
                    "cash_ratio": round(acct_doc.get("available_cash", 0) / max(total_assets, 1) * 100, 1),
                    "position_ratio": round(total_mv / max(total_assets, 1) * 100, 1),
                    "max_single_pct": round(max_single_pct, 1),
                    "top_industry_concentration": round(top_industry_pct, 1),
                    "industry_exposure": {k: round(v / max(total_mv, 1) * 100, 1) for k, v in industry_exp.items()},
                    "position_count": len(matrix),
                    "stop_loss_exec_rate": 0,  # MongoDB回退模式无此数据
                    "risk_summary": {"normal": normal, "warning": warning, "critical": critical},
                    "risk_score": round(min(sum(m["risk_score"] for m in matrix) / max(len(matrix), 1), 100), 0),
                    "risk_level": "critical" if critical > 0 else ("warning" if warning > 0 else "normal"),
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
        
        # 【v2.9.98z】历史日期: 从broker_orders重建持仓，不走实时broker
        if is_historical:
            from nodes.web.api.unified import fetch_unified_positions
            account_id = scanner.account_id if hasattr(scanner, 'account_id') else "default"
            pos_result = await fetch_unified_positions(date=str(date_int), account_id=account_id)
            positions_historical = pos_result if isinstance(pos_result, list) else pos_result.get("positions", []) if isinstance(pos_result, dict) else []
            # 用历史持仓构建风控矩阵(复用fallback逻辑)
            industry_map = {}
            try:
                async for doc in mongo_manager.db["stock_basic"].find({}, {"_id": 0, "ts_code": 1, "industry": 1}):
                    industry_map[doc.get("ts_code", "")] = doc.get("industry", "")
            except Exception:
                pass
            from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK, STRATEGY_CONFIGS
            strategy_cn = {"halfway_chase": "半路追涨", "first_limit_up": "首板打板", "dragon_head": "龙头低吸", "limit_down_qiao": "跌停翘板"}
            matrix = []
            industry_exp = {}
            max_single_pct = 0
            total_mv = 0
            for p in positions_historical:
                cost = p.get("avg_cost", p.get("cost_price", 0))
                cur = p.get("current_price", 0)
                qty = p.get("total_qty", p.get("shares", 0))
                ts_code = p.get("ts_code", "")
                stock_name = p.get("stock_name", "")
                strategy = p.get("strategy", "halfway_chase")
                if cost <= 0 or qty <= 0:
                    continue
                mv = cur * qty
                total_mv += mv
                strat_key = strategy
                for k, v in STRATEGY_CONFIGS.items():
                    if v.get("display_name") == strategy or k == strategy:
                        strat_key = k; break
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
                industry = industry_map.get(ts_code, "未知")
                industry_exp[industry] = industry_exp.get(industry, 0) + mv
                if cur <= sl_price: risk_level = "critical"
                elif dist_sl < 2: risk_level = "warning"
                else: risk_level = "normal"
                d1_sl = max(0, 25 - dist_sl * 5)
                d2_pos = 0  # position_pct尚待计算
                d3_loss = min(abs(profit_pct) * 2, 15)
                d4_turnover = 5
                d5_vol = min(abs(profit_pct) * 0.8, 10)
                d6_trail = 0
                d7_industry = min(industry_exp.get(industry, 0) / max(total_mv, 1) * 100 / 2, 5) if industry else 0
                d8_new = 0
                d9_streak = min(max(0, -profit_pct) * 0.5, 5) if profit_pct < 0 else 0
                d10_holding_days = 0
                d11_zt_premium = 0
                d12_market_risk = 0
                d13_liquidity = 0
                d14_profit_reversal = min(max(0, profit_pct - 8) * 0.3, 2) if profit_pct > 8 else 0
                d15_strategy_wr = 0
                risk_score = min(d1_sl + d2_pos + d3_loss + d4_turnover + d5_vol + d6_trail + d7_industry + d8_new + d9_streak + d10_holding_days + d11_zt_premium + d12_market_risk + d13_liquidity + d14_profit_reversal + d15_strategy_wr, 100)
                matrix.append({
                    "ts_code": ts_code, "stock_name": stock_name,
                    "strategy": strategy, "strategy_name": strategy_cn.get(strat_key, strategy),
                    "industry": industry, "current_price": cur, "cost_price": cost,
                    "profit_pct": round(profit_pct, 2), "profit_amount": round(profit_amount, 0),
                    "market_value": round(mv, 0), "position_pct": 0,
                    "stop_loss_price": round(sl_price, 2), "take_profit_price": round(tp_price, 2),
                    "dist_stop_loss": round(dist_sl, 1), "dist_take_profit": round(dist_tp, 1),
                    "risk_level": risk_level, "risk_score": round(risk_score, 0),
                    "trailing_stop": None, "total_qty": qty,
                })
            # 【v2.9.110】获取账户信息计算position_pct — 通过unified层
            from nodes.web.api.unified import fetch_unified_account
            _acct_u = await fetch_unified_account(account_id="default")
            total_assets = (_acct_u.get("available_cash", 0) if _acct_u else 0) + total_mv
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
                    "cash_ratio": round((acct_doc.get("available_cash", 0) if acct_doc else 0) / max(total_assets, 1) * 100, 1),
                    "position_ratio": round(total_mv / max(total_assets, 1) * 100, 1),
                    "max_single_pct": round(max_single_pct, 1),
                    "top_industry_concentration": round(top_industry_pct, 1),
                    "industry_exposure": {k: round(v / max(total_mv, 1) * 100, 1) for k, v in industry_exp.items()},
                    "position_count": len(matrix),
                    "stop_loss_exec_rate": 0,  # 历史回退模式无此数据
                    "risk_summary": {"normal": normal, "warning": warning, "critical": critical},
                },
                "_fallback": True, "_historical": True,
            }}
        
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
                    # 【v2.9.110】通过unified层
                    from nodes.web.api.unified import fetch_unified_account as _fua2
                    _acct_u2 = await _fua2(account_id="default")
                    acct_doc = {"available_cash": _acct_u2.get("available_cash", 0)} if _acct_u2 else None
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
            # 【v2.9.100】15维度风险评分 (在线模式)
            # D1: 距止损距离 (0-25分) — 核心指标
            d1_sl = max(0, 25 - dist_sl * 5)
            # D2: 仓位集中度 (0-15分)
            d2_pos = min(position_pct / 2, 15)
            # D3: 浮亏深度 (0-15分)
            d3_loss = min(abs(pos.profit_pct) * 2, 15)
            # D4: 换手率/流动性 (0-10分) — 高换手风险大
            d4_turnover = max(0, 10 - turnover * 2) if turnover > 0 else 5
            # D5: 波动率 (0-10分)
            d5_vol = min(abs(pos.profit_pct) * 0.8, 10)
            # 【v2.9.105】追踪止损 trail 必须在 d6_trail 使用前赋值【修复NameError】
            trail = trailing_stops.get(pos.ts_code, {})
            # D6: 追踪止损激活 (0-5分)
            d6_trail = 5 if trail.get('activated') else 0
            # D7: 行业集中度 (0-5分) — 同行业持仓过多
            d7_industry = min(industry_exp.get(industry, 0) / max(total_mv, 1) * 100 / 2, 5) if industry else 0
            # D8: 新仓风险 (0-5分) — today_buy_qty>0表示今天买入【v2.9.105修复AttributeError】
            d8_new = 5 if getattr(pos, 'today_buy_qty', 0) > 0 else 0
            # D9: 连亏 (0-5分)
            d9_streak = min(max(0, -pos.profit_pct) * 0.5, 5) if pos.profit_pct < 0 else 0
            # D10: 持仓天数 (0-3分) — 持仓越久不确定性越高
            d10_holding_days = 0
            try:
                from nodes.web.api.unified import _normalize_date as _nd2
                buy_date_int = getattr(pos, 'buy_date_int', 0) or 0
                if buy_date_int > 0:
                    import datetime as _dt3
                    buy_dt = _dt3.datetime.strptime(str(buy_date_int), "%Y%m%d")
                    hold_days = (_dt3.datetime.now() - buy_dt).days
                    d10_holding_days = min(hold_days * 0.3, 3)
            except Exception:
                pass
            # D11: 涨停溢价风险 (0-2分) — 涨停板股票次日溢价不确定性
            d11_zt_premium = 0
            try:
                if scanner._realtime_cache and pos.ts_code in scanner._realtime_cache:
                    zt_p = scanner._realtime_cache[pos.ts_code].get("zt_premium", 0)
                    if zt_p > 5: d11_zt_premium = 2
                    elif zt_p > 0: d11_zt_premium = 1
            except Exception:
                pass
            # D12: 大盘系统性风险 (0-2分) — 全市场下跌时个股难以独善
            d12_market_risk = 0
            try:
                from nodes.market_monitor.emotion_cycle import emotion_cycle_manager as _ecm
                if _ecm and hasattr(_ecm, 'score'):
                    if _ecm.score < 30: d12_market_risk = 2
                    elif _ecm.score < 45: d12_market_risk = 1
            except Exception:
                pass
            # D13: 流动性风险 (0-2分) — 小市值/低成交额难以及时止损
            d13_liquidity = 0
            try:
                if scanner._realtime_cache and pos.ts_code in scanner._realtime_cache:
                    amt = scanner._realtime_cache[pos.ts_code].get("amount", 0)
                    if amt > 0 and amt < 50_000_000: d13_liquidity = 2  # <5000万
                    elif amt > 0 and amt < 200_000_000: d13_liquidity = 1  # <2亿
            except Exception:
                pass
            # D14: 盈亏比偏离 (0-2分) — 浮盈过大时回撤风险
            d14_profit_reversal = min(max(0, pos.profit_pct - 8) * 0.3, 2) if pos.profit_pct > 8 else 0
            # D15: 策略胜率偏差 (0-2分) — 策略近期胜率低时风险更高
            d15_strategy_wr = 0
            try:
                _strat = pos.strategy or "unknown"
                if hasattr(scanner, '_stats') and scanner._stats:
                    strat_key = _norm_strat(_strat) if 'norm_strat' in dir() else _strat
                    # 从scanner._stats取策略胜率(粗略)
                    _s_wr = scanner._stats.get(f"{strat_key}_win_rate", 0)
                    if _s_wr and _s_wr < 30: d15_strategy_wr = 2
                    elif _s_wr and _s_wr < 45: d15_strategy_wr = 1
            except Exception:
                pass
            risk_score = min(d1_sl + d2_pos + d3_loss + d4_turnover + d5_vol + d6_trail + d7_industry + d8_new + d9_streak + d10_holding_days + d11_zt_premium + d12_market_risk + d13_liquidity + d14_profit_reversal + d15_strategy_wr, 100)

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

        # 【v2.9.120】止损执行率: 亏损卖出中走止损的占比
        sl_exec_rate = 0
        try:
            loss_sells = await mongo_manager.db["broker_orders"].count_documents(
                {"account_id": "default", "side": "sell", "profit_pct": {"$lt": 0}}
            )
            sl_sells = await mongo_manager.db["broker_orders"].count_documents(
                {"account_id": "default", "side": "sell", "profit_pct": {"$lt": 0}, "reason": {"$regex": "止损"}}
            )
            sl_exec_rate = round(sl_sells / max(loss_sells, 1) * 100, 0) if loss_sells > 0 else 0
        except Exception:
            pass

        return _sanitize({"success": True, "data": {
            "positions": sorted(matrix, key=lambda x: -x["risk_score"]),
            "global": {
                "total_assets": round(acct.total_assets, 2), "total_market_value": round(total_mv, 0),
                "cash_ratio": round(cash_ratio, 1),
                "position_ratio": round(100 - cash_ratio, 1), "max_single_pct": round(max_single_pct, 1),
                "top_industry_concentration": round(top_ind, 1),
                "industry_exposure": {k: round(v / max(total_mv, 1) * 100, 1) for k, v in sorted(industry_exp.items(), key=lambda x: -x[1])},
                "position_count": len(positions),
                "stop_loss_exec_rate": sl_exec_rate,
                "risk_score": round(min(sum(m["risk_score"] for m in matrix) / max(len(matrix), 1), 100), 0),
                "risk_level": "critical" if any(m.get("risk_level") == "critical" for m in matrix) else ("warning" if any(m.get("risk_level") == "warning" for m in matrix) else "normal"),
                "risk_summary": {
                    "normal": sum(1 for m in matrix if m.get("risk_level") == "normal"),
                    "warning": sum(1 for m in matrix if m.get("risk_level") == "warning"),
                    "critical": sum(1 for m in matrix if m.get("risk_level") == "critical"),
                }
            }
        }})
    except Exception as e:
        return {"success": False, "message": str(e)}




# 【v2.9.97h】盘后收盘价刷新 - 不依赖scanner运行
@router.post("/refresh-close-prices")
async def refresh_close_prices_standalone():
    """盘后刷新持仓收盘价(不依赖scanner运行, 可由cron调用)
    
    逻辑:
    1. 从broker_positions读当前持仓
    2. 从stock_daily_ak_full读当日收盘价
    3. 更新broker_positions的current_price
    """
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": False, "message": "MongoDB未初始化"}
        
        db = mongo_manager.db
        today_int = int(__import__('datetime').datetime.now().strftime("%Y%m%d"))
        updated = 0
        
        async for pos in db["broker_positions"].find({"account_id": "default"}):
            tc = pos.get("ts_code")
            if not tc:
                continue
            # 找最近收盘价(不一定是今天, 可能是非交易日)
            doc = await db["stock_daily_ak_full"].find_one(
                {"ts_code": tc},
                {"close": 1, "trade_date": 1},
                sort=[("trade_date", -1)]
            )
            if doc and doc.get("close", 0) > 0:
                close = float(doc["close"])
                await db["broker_positions"].update_one(
                    {"_id": pos["_id"]},
                    {"$set": {"current_price": close}}
                )
                updated += 1
        
        return {"success": True, "data": {"updated": updated, "date": today_int}}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/reload-positions")
async def reload_positions_standalone():
    """重新从MongoDB加载持仓到scanner内存(盘中修复持仓丢失)
    
    场景: scanner进程未重启但内存中持仓不完整(如幻影卖出删除了position)
    逻辑: 从MongoDB broker_positions读取所有total_qty>0的记录, 补充到broker内存
    """
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": False, "message": "MongoDB未初始化"}
        
        db = mongo_manager.db
        scanner = await _get_scanner()
        if not scanner or not scanner._broker:
            return {"success": False, "message": "scanner未运行"}
        
        broker = scanner._broker
        before = set(broker.positions.keys())
        
        # 从MongoDB加载所有持仓
        from nodes.market_monitor.broker import Position
        added = 0
        updated = 0
        async for doc in db["broker_positions"].find({"account_id": "default", "total_qty": {"$gt": 0}}):
            tc = doc.get("ts_code", "")
            if not tc:
                continue
            if tc in broker.positions:
                # 已在内存中, 更新current_price
                broker.positions[tc].current_price = float(doc.get("current_price", 0) or 0)
                broker.positions[tc].total_qty = int(doc.get("total_qty", 0) or 0)
                broker.positions[tc].available_qty = int(doc.get("available_qty", 0) or 0)
                updated += 1
            else:
                # 缺失的, 重新创建
                broker.positions[tc] = Position(
                    ts_code=tc,
                    stock_name=doc.get("stock_name", ""),
                    total_qty=int(doc.get("total_qty", 0) or 0),
                    available_qty=int(doc.get("available_qty", 0) or 0),
                    avg_cost=float(doc.get("avg_cost", 0) or 0),
                    current_price=float(doc.get("current_price", 0) or 0),
                    profit_pct=float(doc.get("profit_pct", 0) or 0),
                    today_buy_qty=int(doc.get("today_buy_qty", 0) or 0),
                    strategy=doc.get("strategy", "halfway_chase"),
                    buy_date=doc.get("buy_date", ""),
                )
                added += 1
        
        # 删除MongoDB中不存在的position(已清仓但内存残留)
        removed = 0
        mongo_codes = set()
        async for doc in db["broker_positions"].find({"account_id": "default", "total_qty": {"$gt": 0}}, {"ts_code": 1}):
            mongo_codes.add(doc.get("ts_code", ""))
        for tc in list(broker.positions.keys()):
            if tc not in mongo_codes and broker.positions[tc].total_qty <= 0:
                del broker.positions[tc]
                removed += 1
        
        # 重算账户
        broker._recalc_account()
        after = set(broker.positions.keys())
        
        return {
            "success": True, 
            "data": {
                "before": list(sorted(before)), 
                "after": list(sorted(after)), 
                "added": added, 
                "updated": updated, 
                "removed": removed,
                "total": len(after),
            }
        }
    except Exception as e:
        return {"success": False, "message": str(e)}
