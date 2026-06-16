#!/usr/bin/env python3
"""Scanner API - 交易/买卖/熔断/结算"""
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

router = APIRouter(prefix="/scanner", tags=["交易/买卖/熔断/结算"])


def _format_trade_time_display(trade_date: str, time_str: str) -> str:
    """【v2.9.94】统一格式化交易时间显示为 'YYYY-MM-DD HH:MM:SS'

    为了避免买入日/卖出日不同于当前扫描日时前端误以为两者同天，
    这里严格反映该订单本身的 trade_date，该项需要从 broker_orders 推送到前端。
    """
    if not time_str:
        return ""
    td = str(trade_date or "").strip()
    if len(td) == 8 and td.isdigit():
        return f"{td[0:4]}-{td[4:6]}-{td[6:8]} {time_str}"
    if len(td) == 10 and td.count("-") == 2:
        return f"{td} {time_str}"
    return time_str


@router.post("/trade")
async def manual_trade(req: ManualTradeRequest):
    """手动交易(买入/卖出)
    
    用于实盘人工干预: 手动买入/卖出/调仓
    """
    scanner = await _get_scanner()
    
    if not scanner._broker:
        raise HTTPException(400, "Broker未初始化")
    
    if not scanner._broker._realtime_prices.get(req.ts_code, 0) > 0:
        # 尝试从必盈获取实时行情
        try:
            if scanner._data_router:
                biying = scanner._data_router._sources.get("biying")
                if biying:
                    quote = await biying.get_realtime_quote(req.ts_code)
                    if quote:
                        price = float(quote.get("close", 0) if isinstance(quote, dict) else getattr(quote, 'close', 0))
                        pre_close = float(quote.get("pre_close", 0) if isinstance(quote, dict) else getattr(quote, 'pre_close', 0))
                        name = quote.get("name", "") if isinstance(quote, dict) else getattr(quote, 'name', '')
                        if price > 0:
                            scanner._broker.update_realtime(req.ts_code, price, pre_close=pre_close)
                            if name and not req.stock_name:
                                req.stock_name = name
                            logger.info(f"[TRADE] 自动获取 {req.ts_code} 行情: {price}")
        except Exception as e:
            logger.warning(f"[TRADE] 自动获取行情失败: {e}")
    
    # 再次检查
    if not scanner._broker._realtime_prices.get(req.ts_code, 0) > 0:
        raise HTTPException(400, f"{req.ts_code} 无实时行情, 请先启动扫描器")
    
    # 熔断器检查(买入时检查, 卖出允许止损)
    cb = scanner._circuit_breaker
    if req.side == "buy" and cb.get("trading_paused", False):
        raise HTTPException(403, f"交易已暂停: {cb.get('pause_reason', '熔断触发')}")
    
    # 数量校验
    if req.side == "buy":
        if req.quantity <= 0:
            # 自动计算: 用可用现金的15%
            acct = scanner._broker.get_account()
            price = req.price or scanner._broker._realtime_prices.get(req.ts_code, 0)
            if price <= 0:
                raise HTTPException(400, "无有效价格")
            lot = 200 if req.ts_code.startswith('688') else 100
            req.quantity = int(acct.available_cash * 0.15 / price / lot) * lot
            if req.quantity <= 0:
                raise HTTPException(400, "可用资金不足")
    elif req.side == "sell":
        if req.quantity <= 0:
            # 默认全部卖出
            pos = scanner._broker.positions.get(req.ts_code)
            if pos:
                req.quantity = pos.available_qty
                if req.quantity <= 0:
                    raise HTTPException(400, f"{req.ts_code} 无可卖数量(T+1限制, 请先日结算)")
            else:
                raise HTTPException(400, f"无持仓: {req.ts_code}")
    
    ok, msg, order = scanner._broker.place_order(
        ts_code=req.ts_code,
        stock_name=req.stock_name or req.ts_code,
        side=req.side,
        quantity=req.quantity,
        price=req.price,
        order_type=req.order_type,
        strategy=req.strategy,
        reason=req.reason or "手动操作",
        source="manual",
    )
    
    if ok:
        scanner._timeline.append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "action": req.side,
            "ts_code": req.ts_code,
            "stock_name": req.stock_name or req.ts_code,
            "strategy": req.strategy,
            "shares": req.quantity,
            "price": order.filled_price,
            "reason": req.reason or "手动操作",
        })
        # 异步保存时间线到MongoDB
        try:
            await scanner._save_timeline()
        except Exception:
            pass  # 非关键, 不影响交易
        scanner._stats["trades_executed"] += 1
    
    return {
        "success": ok,
        "data": {
            "order_id": order.order_id,
            "side": req.side,
            "ts_code": req.ts_code,
            "quantity": order.quantity,
            "filled_qty": order.filled_qty,
            "filled_price": order.filled_price,
            "status": order.status.value,
            "message": msg,
        },
    }



@router.post("/circuit-breaker/reset")
async def reset_circuit_breaker():
    """重置风控熔断(手动恢复交易)"""
    scanner = await _get_scanner()
    if hasattr(scanner, 'reset_circuit_breaker'):
        scanner.reset_circuit_breaker()
        return {"success": True, "data": {"message": "熔断已重置, 交易恢复"}}
    else:
        raise HTTPException(400, "扫描器不支持熔断重置")


class PauseRequest(BaseModel):
    reason: str = "手动暂停"



@router.post("/circuit-breaker/pause")
async def pause_circuit_breaker(req: PauseRequest = None):
    """手动暂停交易(熔断)"""
    scanner = await _get_scanner()
    if not scanner._circuit_breaker:
        raise HTTPException(400, "熔断器未初始化")
    reason = req.reason if req else "手动暂停"
    scanner._circuit_breaker["trading_paused"] = True
    scanner._circuit_breaker["pause_reason"] = reason
    return {"success": True, "data": {"message": f"交易已暂停: {reason}"}}


class ScanOnceRequest(BaseModel):
    force: bool = False
    replay_date: Optional[str] = None  # 回放日期, 设置后使用历史数据



@router.post("/scan-once")
async def scan_once(req: ScanOnceRequest = ScanOnceRequest()):
    """手动触发一次扫描
    
    Body:
        force: 强制模式, 忽略交易时间检查(消耗必盈额度, 测试用)
    """
    scanner = await _get_scanner()
    # 回放模式: 自动force并设置replay_date
    if req.replay_date and scanner._replay_provider:
        scanner._replay_date = req.replay_date
    force = req.force or scanner._replay_mode
    trade_date = scanner._replay_date or datetime.now().strftime("%Y%m%d")
    try:
        await scanner.scan_once(trade_date, force=force)
    except Exception as e:
        logger.error(f"[API] scan_once失败: {e}")
        return {
            "success": False,
            "data": {"signals": 0, "positions": 0},
            "message": f"扫描失败: {str(e)}",
        }


@router.post("/premarket-scan")
async def trigger_premarket_scan():
    """手动触发一次盘前竞价扫描(L4+L5+L6全市场)
    
    使用场景:
    - 9:00-9:25 预选今日侯选股
    - 手动触发重新扫描(不依赖scan_loop)
    """
    from datetime import datetime
    scanner = await _get_scanner()
    trade_date = scanner._trade_date or datetime.now().strftime("%Y%m%d")
    try:
        n = await scanner.premarket_scan(trade_date)
        return {
            "success": True,
            "data": {
                "signals": n,
                "total_active_signals": len(scanner._active_signals),
                "trade_date": trade_date,
            },
        }
    except Exception as e:
        logger.error(f"[API] premarket_scan失败: {e}")
        return {"success": False, "data": {"signals": 0}, "message": f"竞价扫描失败: {str(e)}"}
    
    signals_count = len(scanner.get_signals())
    positions_count = len(scanner.get_positions())
    
    # 如果无数据，可能是数据源问题
    msg = None
    if signals_count == 0 and positions_count == 0:
        # 检查数据源状态
        if scanner._data_router:
            biying = scanner._data_router._sources.get("biying")
            if biying and not await biying.is_available():
                msg = "必盈API今日额度已用完，请明天再试或升级必盈套餐"
        if not msg:
            msg = "未发现信号，可能非交易时间或数据源异常"
    
    return {
        "success": True,
        "data": {
            "signals": signals_count,
            "positions": positions_count,
            "message": msg,
        },
    }



@router.get("/orders")
async def get_orders(limit: int = 50, date: str = None):
    """获取历史订单(从MongoDB)
    
    【v2.9.92d】支持date参数过滤指定日期的订单
    """
    scanner = await _get_scanner()
    if not scanner._broker:
        return {"success": True, "data": []}
    
    try:
        if not await scanner._broker._ensure_mongo():
            return {"success": True, "data": []}
        
        db = scanner._broker._mongo_db
        query = {"account_id": scanner._broker.account.account_id}
        if date:
            # 支持int和string两种格式
            query["trade_date"] = {"$in": [date, int(date)] if date.isdigit() else date}
        
        docs = await db["broker_orders"].find(
            query
        ).sort("create_time", 1).limit(limit).to_list(limit)
        
        # 转换ObjectId
        for d in docs:
            d.pop("_id", None)
        
        return {"success": True, "data": _fill_stock_names(docs, scanner)}
    except Exception as e:
        return {"success": True, "data": [], "message": str(e)}



@router.post("/daily-settlement")
async def daily_settlement():
    """手动触发日结算(T+1解锁)"""
    scanner = await _get_scanner()
    if not scanner._broker:
        raise HTTPException(400, "Broker未初始化")
    
    positions = scanner._broker.get_positions()
    t1_locked = len([p for p in positions if p.total_qty > 0 and p.available_qty <= 0])
    
    if not positions:
        return {"success": True, "data": {"message": "当前无持仓，无需结算", "positions_unlocked": 0}}
    
    scanner._broker.daily_settlement()
    
    # 保存状态
    try:
        await scanner._broker.save_state()
    except Exception:
        pass
    
    positions = scanner._broker.get_positions()
    unlocked = len([p for p in positions if p.available_qty > 0])
    return {
        "success": True,
        "data": {
            "message": f"日结算完成: {t1_locked}只T+1已解锁" if t1_locked > 0 else "无T+1持仓需要解锁",
            "positions_unlocked": unlocked,
        }
    }



@router.get("/trade-detail/{ts_code}")
async def get_trade_detail(ts_code: str, date: str = None):
    """获取指定股票的完整交易审查详情
    
    包含：买入原因、9层筛选决策链路、卖出原因、盈亏分析
    数据来源: 内存timeline → MongoDB scanner_timeline → MongoDB broker_orders
    【v2.9.92e】支持date参数，时间显示加日期前缀
    """
    scanner = await _get_scanner()
    
    # 当前scanner的trade_date
    scanner_date = getattr(scanner, '_trade_date', '') or ''
    target_date = date or scanner_date
    date_label = target_date[4:] if len(target_date) == 8 else target_date  # MMDD格式
    
    detail = {
        "ts_code": ts_code,
        "trade_date": target_date,
        "buy": None,       # 买入决策详情
        "sell": None,      # 卖出决策详情
        "position": None,  # 当前持仓状态
        "signal": None,    # 当前信号状态
    }
    
    # 1. 从内存时间线查找买入/卖出记录(只查target_date)
    for item in scanner._timeline:
        if item.get("ts_code") == ts_code:
            item_date = str(item.get("trade_date", ""))
            # 只匹配当天的记录
            if target_date and item_date and item_date != target_date:
                continue
            if item.get("action") == "buy" and not detail["buy"]:
                raw_time = item.get("time", "")
                td_str = str(item.get("trade_date", "") or target_date or "")
                detail["buy"] = {
                    "time": raw_time,
                    "time_display": _format_trade_time_display(td_str, raw_time),
                    "trade_date": td_str,
                    "price": item.get("price", 0),
                    "shares": item.get("shares", 0),
                    "reason": item.get("reason", ""),
                    "strategy": item.get("strategy", ""),
                    "stock_name": item.get("stock_name", ""),
                    "decision_detail": item.get("decision_detail", {}),
                }
            elif item.get("action") == "sell" and not detail["sell"]:
                raw_time = item.get("time", "")
                td_str = str(item.get("trade_date", "") or target_date or "")
                detail["sell"] = {
                    "time": raw_time,
                    "time_display": _format_trade_time_display(td_str, raw_time),
                    "trade_date": td_str,
                    "price": item.get("price", 0),
                    "shares": item.get("shares", 0),
                    "reason": item.get("reason", ""),
                    "strategy": item.get("strategy", ""),
                    "stock_name": item.get("stock_name", ""),
                    "profit_pct": item.get("profit_pct", 0),
                    "profit_amount": item.get("profit_amount", 0),
                    "decision_detail": item.get("decision_detail", {}),
                }
    
    # 1b. 从MongoDB历史时间线补充(跨session数据, 按target_date过滤)
    if not detail["buy"] or not detail["sell"]:
        try:
            from core.managers import mongo_manager
            if mongo_manager.is_initialized:
                account_id = scanner._broker.account.account_id if scanner._broker else "default"
                query = {"account_id": account_id, "ts_code": ts_code}
                if target_date:
                    query["trade_date"] = {"$in": [str(target_date), int(target_date)]} if str(target_date).isdigit() else str(target_date)
                async for doc in mongo_manager.db["scanner_timeline"].find(
                    query
                ).sort("time", 1):
                    if doc.get("action") == "buy" and not detail["buy"]:
                        doc_date = str(doc.get("trade_date", ""))
                        raw_time = doc.get("time", "")
                        detail["buy"] = {
                            "time": raw_time,
                            "time_display": _format_trade_time_display(doc_date, raw_time),
                            "trade_date": doc_date,
                            "price": doc.get("price", 0),
                            "shares": doc.get("shares", 0),
                            "reason": doc.get("reason", ""),
                            "strategy": doc.get("strategy", ""),
                            "stock_name": doc.get("stock_name", ""),
                            "decision_detail": doc.get("decision_detail", {}),
                        }
                    elif doc.get("action") == "sell" and not detail["sell"]:
                        doc_date = str(doc.get("trade_date", ""))
                        raw_time = doc.get("time", "")
                        detail["sell"] = {
                            "time": raw_time,
                            "time_display": _format_trade_time_display(doc_date, raw_time),
                            "trade_date": doc_date,
                            "price": doc.get("price", 0),
                            "shares": doc.get("shares", 0),
                            "reason": doc.get("reason", ""),
                            "strategy": doc.get("strategy", ""),
                            "stock_name": doc.get("stock_name", ""),
                            "profit_pct": doc.get("profit_pct", 0),
                            "profit_amount": doc.get("profit_amount", 0),
                            "decision_detail": doc.get("decision_detail", {}),
                        }
        except Exception:
            pass
    
    # 2. 从持仓查找当前状态(含止损止盈)
    for p in scanner._broker.get_positions():
        if p.ts_code == ts_code:
            # 获取策略风控参数
            risk = scanner._get_strategy_risk(p.strategy)
            detail["position"] = {
                "shares": p.total_qty,
                "cost_price": p.avg_cost,
                "current_price": p.current_price,
                "profit_pct": p.profit_pct,
                "strategy": p.strategy,
                "available_qty": p.available_qty,
                "today_buy": p.today_buy_qty,
                "stop_loss_pct": risk.get("stop_loss_pct", 0.03) * 100,  # 3%→3.0
                "take_profit_pct": risk.get("take_profit_pct", 0.07) * 100,  # 7%→7.0
            }
    
    # 3. 从活跃信号查找
    for s in scanner._active_signals:
        if s.ts_code == ts_code:
            detail["signal"] = scanner._signal_to_dict(s)
            break
    
    # 4. 从MongoDB历史订单查找(全量,跨session)
    orders = []
    try:
        if scanner._broker and await scanner._broker._ensure_mongo():
            db = scanner._broker._mongo_db
            account_id = scanner._broker.account.account_id
            async for doc in db["broker_orders"].find(
                {"account_id": account_id, "ts_code": ts_code}
            ).sort("create_time", 1):
                doc.pop("_id", None)
                orders.append(doc)
    except Exception:
        pass
    # fallback: 内存orders
    if not orders and scanner._broker:
        for o in scanner._broker.orders:
            if o.ts_code == ts_code:
                orders.append({
                    "order_id": o.order_id,
                    "side": o.side,
                    "quantity": o.quantity,
                    "filled_qty": o.filled_qty,
                    "filled_price": o.filled_price,
                    "strategy": o.strategy,
                    "reason": o.reason,
                    "trade_date": o.trade_date,
                    "create_time": o.create_time,
                })
    detail["orders"] = orders
    
    # 5. 如果买入信息缺失,从订单中补充
    # 【v2.9.94】补全 trade_date / fill_time / time_display，避免买入卖出跨日时前端误导
    if not detail["buy"] and orders:
        buy_order = next((o for o in orders if o["side"] == "buy"), None)
        if buy_order:
            buy_td = buy_order.get("trade_date") or ""
            buy_td_str = str(buy_td) if buy_td else ""
            buy_time = buy_order.get("fill_time") or buy_order.get("create_time") or ""
            # 格式化：如果 trade_date 是 8 位数字，贴上属于当天的未来日期。 'YYYY-MM-DD HH:MM:SS' 格式
            buy_display = _format_trade_time_display(buy_td_str, buy_time)
            detail["buy"] = {
                "time": buy_time,
                "time_display": buy_display,
                "trade_date": buy_td_str,
                "price": buy_order.get("filled_price", 0) or buy_order.get("price", 0),
                "shares": buy_order.get("filled_qty", 0) or buy_order.get("quantity", 0),
                "reason": buy_order.get("reason", ""),
                "strategy": buy_order.get("strategy", ""),
                "stock_name": buy_order.get("stock_name", ""),
                "decision_detail": {},
            }
    
    # 5b. 如果仍无买入信息,从卖出的decision_detail推断(cost_price)
    # 【v2.9.94】补全 trade_date / time_display。幽灵买入没有真实日期，用卖出日期为占位，加 inferred 标记
    if not detail["buy"] and detail["sell"]:
        sell_dd = detail["sell"].get("decision_detail", {})
        cost_price = sell_dd.get("cost_price", 0)
        if cost_price > 0:
            sell_td = detail["sell"].get("trade_date", "")
            detail["buy"] = {
                "time": "(历史记录)",
                "time_display": f"{_format_trade_time_display(sell_td, '')} 之前".strip() if sell_td else "(历史记录)",
                "trade_date": sell_td,
                "price": cost_price,
                "shares": detail["sell"].get("shares", 0),
                "reason": detail["sell"].get("reason", "").split("(")[0].strip() if detail["sell"].get("reason") else "",
                "strategy": detail["sell"].get("strategy", ""),
                "stock_name": "",
                "decision_detail": {},
                "inferred": True,  # 标记为推断数据
            }
    
    # 6. 如果卖出信息缺失,从订单中补充
    # 【v2.9.94】补全 trade_date / time_display
    if not detail["sell"] and orders:
        sell_order = next((o for o in orders if o["side"] == "sell"), None)
        if sell_order:
            profit_pct = 0
            if detail["buy"] and detail["buy"].get("price") and (sell_order.get("filled_price") or sell_order.get("price")):
                sell_px = sell_order.get("filled_price") or sell_order.get("price")
                profit_pct = (sell_px - detail["buy"]["price"]) / detail["buy"]["price"] * 100
            sell_td = sell_order.get("trade_date") or ""
            sell_td_str = str(sell_td) if sell_td else ""
            sell_time = sell_order.get("fill_time") or sell_order.get("create_time") or ""
            sell_display = _format_trade_time_display(sell_td_str, sell_time)
            detail["sell"] = {
                "time": sell_time,
                "time_display": sell_display,
                "trade_date": sell_td_str,
                "price": sell_order.get("filled_price", 0) or sell_order.get("price", 0),
                "shares": sell_order.get("filled_qty", 0) or sell_order.get("quantity", 0),
                "reason": sell_order.get("reason", ""),
                "strategy": sell_order.get("strategy", ""),
                "stock_name": sell_order.get("stock_name", ""),
                "profit_pct": profit_pct,
                "profit_amount": sell_order.get("profit_amount", 0),
                "decision_detail": {},
            }
    
    # 7. 填充stock_name
    stock_name = ""
    # 从名称映射
    if hasattr(scanner, '_stock_name_map'):
        stock_name = scanner._stock_name_map.get(ts_code, "")
    if not stock_name:
        # 从活跃信号
        for s in scanner._active_signals:
            if s.ts_code == ts_code and s.stock_name:
                stock_name = s.stock_name
                break
    if not stock_name:
        # 从持仓
        for p in scanner._broker.get_positions():
            if p.ts_code == ts_code and p.stock_name:
                stock_name = p.stock_name
                break
    detail["stock_name"] = stock_name
    
    # 把stock_name也填入buy/sell
    if detail["buy"] and not detail["buy"].get("stock_name"):
        detail["buy"]["stock_name"] = stock_name
    if detail["sell"] and not detail["sell"].get("stock_name"):
        detail["sell"]["stock_name"] = stock_name
    
    return {"success": True, "data": detail}


@router.get("/export-trade-log")
async def export_trade_log():
    """导出交易日志CSV - 返回全部订单+时间线数据(含MongoDB历史)"""
    import csv
    import io
    scanner = await _get_scanner()
    
    rows = []
    # 1. 内存中的timeline
    for item in scanner._timeline:
        rows.append({
            "time": item.get("time", ""),
            "action": item.get("action", ""),
            "ts_code": item.get("ts_code", ""),
            "stock_name": item.get("stock_name", ""),
            "strategy": item.get("strategy", ""),
            "shares": item.get("shares", ""),
            "price": item.get("price", ""),
            "reason": item.get("reason", ""),
            "profit_pct": item.get("profit_pct", ""),
            "profit_amount": item.get("profit_amount", ""),
        })
    
    # 2. 内存中的orders(守卫: broker可能为None)
    if scanner._broker:
        for o in scanner._broker.get_orders():
            rows.append({
                "time": o.create_time or "",
                "action": o.side or "",
                "ts_code": o.ts_code or "",
                "stock_name": o.stock_name or "",
                "strategy": o.strategy or "",
                "shares": o.filled_qty or o.quantity or "",
                "price": o.filled_price or o.price or "",
                "reason": o.reason or "",
                "profit_pct": getattr(o, 'profit_pct', '') or "",
                "profit_amount": getattr(o, 'profit_amount', '') or "",
            })
    
    # 3. 【v2.9.80】补充MongoDB历史数据(scanner未运行时也能导出)
    try:
        from core.managers import mongo_manager
        if mongo_manager.is_initialized and scanner._broker:
            account_id = scanner._broker.account.account_id if scanner._broker else "default"
            existing_keys = {(r["ts_code"], r.get("time", "")) for r in rows if r.get("ts_code")}
            # 从scanner_timeline补充
            async for doc in mongo_manager.db["scanner_timeline"].find(
                {"account_id": account_id}
            ).sort("time", 1):
                key = (doc.get("ts_code", ""), doc.get("time", ""))
                if key in existing_keys:
                    continue  # 去重(内存数据优先)
                rows.append({
                    "time": doc.get("time", ""),
                    "action": doc.get("action", ""),
                    "ts_code": doc.get("ts_code", ""),
                    "stock_name": doc.get("stock_name", ""),
                    "strategy": doc.get("strategy", ""),
                    "shares": doc.get("shares", ""),
                    "price": doc.get("price", ""),
                    "reason": doc.get("reason", ""),
                    "profit_pct": doc.get("profit_pct", ""),
                    "profit_amount": doc.get("profit_amount", ""),
                })
                existing_keys.add(key)
            # 从broker_orders补充
            async for doc in mongo_manager.db["broker_orders"].find(
                {"account_id": account_id}
            ).sort("create_time", 1):
                key = (doc.get("ts_code", ""), doc.get("create_time", ""))
                if key in existing_keys:
                    continue
                rows.append({
                    "time": doc.get("create_time", ""),
                    "action": doc.get("side", ""),
                    "ts_code": doc.get("ts_code", ""),
                    "stock_name": doc.get("stock_name", ""),
                    "strategy": doc.get("strategy", ""),
                    "shares": doc.get("filled_qty", ""),
                    "price": doc.get("filled_price", ""),
                    "reason": doc.get("reason", ""),
                    "profit_pct": doc.get("profit_pct", ""),
                    "profit_amount": doc.get("profit_amount", ""),
                })
                existing_keys.add(key)
    except Exception:
        pass  # MongoDB不可用不影响已有数据导出
    
    if not rows:
        return {"success": True, "data": {"csv": "", "count": 0}}
    
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
    
    return {"success": True, "data": {"csv": output.getvalue(), "count": len(rows)}}




@router.get("/trade-audit")
async def get_trade_audit():
    """获取全部交易的审查摘要
    
    每笔交易一行，包含买入/卖出原因和盈亏
    用于快速扫描所有自动交易的决策质量
    """
    scanner = await _get_scanner()
    
    # 收集所有交易过的股票
    traded_stocks = {}
    for item in scanner._timeline:
        ts_code = item.get("ts_code", "")
        if not ts_code:
            continue
        if ts_code not in traded_stocks:
            traded_stocks[ts_code] = {
                "ts_code": ts_code,
                "stock_name": item.get("stock_name", ""),
                "strategy": item.get("strategy", ""),
                "buy_time": "", "buy_price": 0, "buy_reason": "",
                "buy_detail": None,
                "sell_time": "", "sell_price": 0, "sell_reason": "",
                "sell_detail": None,
                "profit_pct": None,
                "status": "持仓中",
            }
        
        entry = traded_stocks[ts_code]
        if item.get("action") == "buy":
            entry["buy_time"] = item.get("time", "")
            entry["buy_price"] = item.get("price", 0)
            entry["buy_reason"] = item.get("reason", "")
            entry["buy_detail"] = item.get("decision_detail")
        elif item.get("action") == "sell":
            entry["sell_time"] = item.get("time", "")
            entry["sell_price"] = item.get("price", 0)
            entry["sell_reason"] = item.get("reason", "")
            entry["sell_detail"] = item.get("decision_detail")
            entry["profit_pct"] = item.get("profit_pct")
            entry["status"] = "已卖出"
    
    # 标记当前持仓
    for p in scanner._broker.get_positions():
        if p.ts_code in traded_stocks:
            traded_stocks[p.ts_code]["status"] = f"持仓中 {p.profit_pct:+.1f}%"
    
    # 补充历史数据(从MongoDB scanner_timeline)
    try:
        from core.managers import mongo_manager
        if mongo_manager.is_initialized:
            account_id = scanner._broker.account.account_id if scanner._broker else "default"
            async for doc in mongo_manager.db["scanner_timeline"].find(
                {"account_id": account_id}
            ).sort("time", 1):
                ts_code = doc.get("ts_code", "")
                if not ts_code or ts_code in traded_stocks:
                    continue
                if ts_code not in traded_stocks:
                    traded_stocks[ts_code] = {
                        "ts_code": ts_code,
                        "stock_name": doc.get("stock_name", ""),
                        "strategy": doc.get("strategy", ""),
                        "buy_time": "", "buy_price": 0, "buy_reason": "",
                        "buy_detail": None,
                        "sell_time": "", "sell_price": 0, "sell_reason": "",
                        "sell_detail": None,
                        "profit_pct": None,
                        "status": "已卖出",
                    }
                entry = traded_stocks[ts_code]
                if doc.get("action") == "buy" and not entry["buy_time"]:
                    entry["buy_time"] = doc.get("time", "")
                    entry["buy_price"] = doc.get("price", 0)
                    entry["buy_reason"] = doc.get("reason", "")
                    entry["buy_detail"] = doc.get("decision_detail")
                elif doc.get("action") == "sell" and not entry["sell_time"]:
                    entry["sell_time"] = doc.get("time", "")
                    entry["sell_price"] = doc.get("price", 0)
                    entry["sell_reason"] = doc.get("reason", "")
                    entry["sell_detail"] = doc.get("decision_detail")
                    entry["profit_pct"] = doc.get("profit_pct")
    except Exception:
        pass
    
    result = list(traded_stocks.values())
    return {"success": True, "data": _fill_stock_names(result, scanner)}



@router.post("/sell")
async def sell_position(req: PartialSellRequest):
    """卖出持仓(支持部分卖出)
    
    - quantity=0: 全部卖出可用持仓
    - quantity>0: 卖出指定数量(必须为100的整数倍)
    """
    scanner = await _get_scanner()
    if not scanner._broker:
        raise HTTPException(400, "Broker未初始化")
    
    pos = scanner._broker.positions.get(req.ts_code)
    if not pos:
        raise HTTPException(404, f"无持仓: {req.ts_code}")
    
    if pos.available_qty <= 0:
        raise HTTPException(400, f"T+1限制: {req.ts_code} 今日买入不可卖")
    
    # 确定卖出数量
    sell_qty = req.quantity if req.quantity > 0 else pos.available_qty
    lot = 200 if req.ts_code.startswith('688') else 100
    sell_qty = min(sell_qty, pos.available_qty)
    sell_qty = (sell_qty // lot) * lot  # 整手
    
    if sell_qty <= 0:
        raise HTTPException(400, "卖出数量不足1手")
    
    # 熔断检查(卖出允许, 但记录)
    reason = req.reason or f"手动卖出{sell_qty}股"
    
    ok, msg, order = scanner._broker.place_order(
        ts_code=req.ts_code,
        stock_name=pos.stock_name,
        side="sell",
        quantity=sell_qty,
        price=pos.current_price,
        order_type="market",
        strategy=pos.strategy,
        reason=reason,
        source="manual",
    )
    
    if ok:
        scanner._timeline.append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "action": "sell",
            "ts_code": req.ts_code,
            "stock_name": pos.stock_name,
            "strategy": pos.strategy,
            "shares": sell_qty,
            "price": order.filled_price,
            "reason": reason,
            "profit_pct": round(pos.profit_pct, 2),
        })
        try:
            await scanner._save_timeline()
        except Exception:
            pass
        scanner._stats["trades_executed"] += 1
    
    return {
        "success": ok,
        "data": {
            "order_id": order.order_id,
            "ts_code": req.ts_code,
            "quantity": sell_qty,
            "filled_qty": order.filled_qty,
            "filled_price": order.filled_price,
            "remaining_qty": pos.total_qty - sell_qty if ok else pos.total_qty,
            "message": msg,
        },
    }



@router.post("/sell-all")
async def sell_all_positions():
    """一键清仓(卖出所有可用持仓)
    
    遍历所有持仓, 逐个卖出可用部分。
    跌停股自动跳过(无法成交)。
    """
    scanner = await _get_scanner()
    if not scanner._broker:
        raise HTTPException(400, "Broker未初始化")
    
    positions = scanner._broker.get_positions()
    if not positions:
        return {"success": True, "data": {"message": "无持仓", "sold": 0, "skipped": 0}}
    
    results = []
    sold = 0
    skipped = 0
    
    for pos in positions:
        if pos.available_qty <= 0:
            skipped += 1
            results.append({"ts_code": pos.ts_code, "status": "skipped", "reason": "T+1限制"})
            continue
        
        # 检查跌停
        if scanner._is_limit_down(pos.ts_code):
            skipped += 1
            results.append({"ts_code": pos.ts_code, "status": "skipped", "reason": "跌停不可卖"})
            continue
        
        ok, msg, order = scanner._broker.place_order(
            ts_code=pos.ts_code,
            stock_name=pos.stock_name,
            side="sell",
            quantity=pos.available_qty,
            price=pos.current_price,
            order_type="market",
            strategy=pos.strategy,
            reason="一键清仓",
        )
        
        if ok:
            sold += 1
            scanner._timeline.append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "action": "sell",
                "ts_code": pos.ts_code,
                "stock_name": pos.stock_name,
                "strategy": pos.strategy,
                "shares": pos.available_qty,
                "price": order.filled_price,
                "reason": "一键清仓",
                "profit_pct": round(pos.profit_pct, 2),
            })
            results.append({"ts_code": pos.ts_code, "status": "sold", "price": order.filled_price, "qty": order.filled_qty})
        else:
            skipped += 1
            results.append({"ts_code": pos.ts_code, "status": "failed", "reason": msg})
    
    # 保存
    try:
        await scanner._save_timeline()
        await scanner._broker.save_state()
    except Exception:
        pass
    
    return {
        "success": True,
        "data": {
            "sold": sold,
            "skipped": skipped,
            "results": results,
            "message": f"清仓完成: 卖出{sold}只, 跳过{skipped}只",
        },
    }


# ==================== 交易报告增强 ====================


@router.get("/trade-log")
async def get_trade_log(days: int = 30, format: str = "json"):
    """交易日志(可导出)
    
    Args:
        days: 最近N天
        format: json | csv
    """
    scanner = await _get_scanner()
    if not scanner._broker:
        return {"success": True, "data": []}
    
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": []}
        
        account_id = scanner._broker.account.account_id
        start_date = int((datetime.now() - timedelta(days=days)).strftime("%Y%m%d"))
        
        orders = []
        async for doc in mongo_manager.db["broker_orders"].find({
            "account_id": account_id,
            "trade_date": {"$gte": start_date},
            "status": "filled",
        }).sort("trade_date", -1).limit(500):
            doc.pop("_id", None)
            orders.append(doc)
        
        if format == "csv":
            # 生成CSV
            import io
            import csv
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["日期", "时间", "代码", "名称", "方向", "数量", "价格", "金额", "策略", "原因"])
            for o in orders:
                writer.writerow([
                    o.get("trade_date", ""),
                    o.get("create_time", ""),
                    o.get("ts_code", ""),
                    o.get("stock_name", ""),
                    "买入" if o.get("side") == "buy" else "卖出",
                    o.get("filled_qty", 0),
                    o.get("filled_price", 0),
                    round(o.get("filled_price", 0) * o.get("filled_qty", 0), 2),
                    o.get("strategy", ""),
                    o.get("reason", ""),
                ])
            return {
                "success": True,
                "data": output.getvalue(),
                "format": "csv",
                "filename": f"trade_log_{datetime.now().strftime('%Y%m%d')}.csv",
            }
        
        return {"success": True, "data": orders, "count": len(orders)}
    except Exception as e:
        return {"success": True, "data": [], "message": str(e)}


# ==================== 性能追踪 ====================


@router.post("/emergency-liquidate")
async def emergency_liquidate(request: Request):
    """🚨 紧急平仓 — 独立于Scanner主循环, 直连Broker执行
    
    用途: GUI红色按钮 / API紧急调用
    安全: 需要确认参数 reason
    """
    try:
        try:
            body = await request.json()
        except Exception:
            body = {}
        reason = body.get("reason", "API手动触发") if isinstance(body, dict) else "API手动触发"
        
        scanner = _get_scanner_instance()
        if not scanner:
            return {"success": False, "message": "Scanner未运行"}
        
        watchdog = getattr(scanner, '_risk_watchdog', None)
        if not watchdog:
            return {"success": False, "message": "看门狗未初始化"}
        
        result = await watchdog.emergency_liquidate(reason)
        
        logger.critical(f"[API] 🚨 紧急平仓: reason={reason}, result={result}")
        
        return {"success": result.get("success", False), "data": result}
    except Exception as e:
        return {"success": False, "message": str(e)}



@router.get("/auto-trades")
async def get_auto_trades(date: str = None, limit: int = 50):
    """自动交易操作流 — 查看自动交易系统执行的所有操作
    
    区别于手动操作, 这是Scanner自动触发的买入/卖出
    返回带source标记的订单列表
    
    Args:
        date: 指定日期(YYYYMMDD), 不传则返回全部今日记录
        limit: 最大返回数
    
    数据源优先级:
    1. 当日且scanner运行中 → 内存orders(最实时)
    2. 其他情况 → MongoDB broker_orders(历史真相源)
    """
    try:
        from datetime import datetime
        today_str = datetime.now().strftime("%Y%m%d")
        target_date = date or today_str
        is_today = (target_date == today_str)
        
        trades = []
        scanner = _get_scanner_instance()
        
        # 今日 + scanner运行中: 优先用内存orders(最实时状态)
        if is_today and scanner and scanner._broker:
            for o in scanner._broker.orders:
                if o.status.value != "filled":
                    continue
                if date and o.trade_date != date:
                    continue
                trades.append({
                    "time": o.fill_time or o.create_time,
                    "ts_code": o.ts_code,
                    "stock_name": o.stock_name,
                    "side": o.side.value,
                    "quantity": o.filled_qty,
                    "price": o.filled_price,
                    "amount": o.filled_price * o.filled_qty,
                    "strategy": o.strategy,
                    "reason": o.reason,
                    "source": getattr(o, 'source', 'auto'),
                    "trade_date": o.trade_date,
                    "order_id": o.order_id,
                    "decision_trace": getattr(o, 'decision_trace', {}),
                })
        
        # 历史日期 或 今日scanner未运行: 从MongoDB读取
        if not trades:
            try:
                from core.managers import mongo_manager
                if mongo_manager.is_initialized:
                    db = mongo_manager.db
                    # 兼容string和int两种格式
                    target_int = int(target_date) if target_date.isdigit() else target_date
                    query = {
                        "trade_date": {"$in": [target_date, target_int]},
                        "status": "filled",
                    }
                    cursor = db["broker_orders"].find(query).sort("create_time", -1).limit(limit * 2)
                    async for o in cursor:
                        trades.append({
                            "time": o.get("fill_time") or o.get("create_time", ""),
                            "ts_code": o.get("ts_code", ""),
                            "stock_name": o.get("stock_name", ""),
                            "side": o.get("side", ""),
                            "quantity": o.get("filled_qty", 0) or o.get("quantity", 0),
                            "price": o.get("filled_price", 0) or o.get("price", 0),
                            "amount": (o.get("filled_price", 0) or 0) * (o.get("filled_qty", 0) or 0),
                            "strategy": o.get("strategy", ""),
                            "reason": o.get("reason", ""),
                            "source": o.get("source", "auto"),
                            "trade_date": str(o.get("trade_date", "")),
                            "order_id": o.get("order_id", ""),
                            "profit_pct": o.get("profit_pct"),
                            "profit_amount": o.get("profit_amount"),
                            "decision_trace": o.get("decision_trace", {}),
                        })
            except Exception as e:
                logger.error(f"[auto-trades] MongoDB读取失败: {e}")
        
        # 按时间倒序
        trades.sort(key=lambda x: x.get("time", ""), reverse=True)
        return {"success": True, "data": trades[:limit]}
    except Exception as e:
        return {"success": True, "data": [], "message": str(e)}


