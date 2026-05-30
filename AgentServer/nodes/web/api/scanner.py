#!/usr/bin/env python3
"""
MarketScanner REST API
超短量化市场扫描器的控制接口
"""
import asyncio
import logging
import math
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel


def _sanitize(obj):
    """递归清理NaN/inf, 防止JSON序列化失败"""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    return obj


def _safe_read_shared(scanner, attr_name: str, copy: bool = True) -> dict:
    """【v2.9.11】线程安全读取scanner共享状态(trailing_stops/position_risk_levels/pending_sells)
    
    这些dict由风控线程写入, API端点读取, 必须加state_lock保护:
    - 读: dict浅拷贝后释放锁
    - 写: 在锁内修改原始dict
    
    Args:
        scanner: MarketScanner实例
        attr_name: '_trailing_stops' / '_position_risk_levels' / '_pending_sells'
        copy: True=深拷贝(安全), False=直接引用(仅用于已加锁的写场景)
    """
    state_lock = getattr(scanner, '_state_lock', None)
    data = getattr(scanner, attr_name, {})
    if state_lock:
        with state_lock:
            return dict(data) if copy else data
    return dict(data) if copy else data

logger = logging.getLogger("api.scanner")

router = APIRouter(prefix="/scanner", tags=["市场监听"])

# 全局扫描器实例
_scanner_instance = None


def _get_scanner():
    global _scanner_instance
    if _scanner_instance is None:
        from nodes.market_monitor.scanner import MarketScanner
        _scanner_instance = MarketScanner()
    # 确保熔断器存在(兼容旧实例)
    if not hasattr(_scanner_instance, '_circuit_breaker'):
        _scanner_instance._circuit_breaker = {
            "daily_start_assets": 1_000_000,
            "daily_max_drawdown": 0.05,
            "consecutive_losses": 0,
            "consecutive_loss_limit": 3,
            "trading_paused": False,
            "pause_reason": "",
            "today_trades": 0,
            "today_losses": 0,
        }
    return _scanner_instance


def _get_scanner_instance():
    """外部模块获取scanner实例(只读)"""
    return _scanner_instance


class ScannerStartRequest(BaseModel):
    account_id: str = "default"
    trade_date: Optional[str] = None
    trade_mode: str = "simulated"  # simulated | gm | dry_run | replay
    replay_date: Optional[str] = None  # 回放模式指定日期, 如 "20260526"
    config: Dict[str, Any] = {}


class ManualTradeRequest(BaseModel):
    ts_code: str
    stock_name: str = ""
    side: str  # buy | sell
    quantity: int = 0
    price: float = 0.0
    order_type: str = "market"
    strategy: str = "manual"
    reason: str = ""


# ==================== 状态 ====================

@router.get("/all")
async def get_all_scanner_data():
    """一次性获取所有扫描器数据(减少前端HTTP开销)
    
    合并: status + signals + positions + timeline + orders
    替代前端5次并发请求, 减少延迟和HTTP开销
    """
    scanner = _get_scanner()
    
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
    scanner = _get_scanner()
    status = scanner.get_status()
    
    # 交易时间判断
    now = datetime.now()
    ct = now.strftime("%H:%M")
    is_trading = ("09:15" <= ct <= "15:05")
    is_premarket = ("09:00" <= ct < "09:15")
    is_closed = ct > "15:05"
    
    if is_trading:
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
    """启动扫描"""
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
    result = await scanner.start(trade_date=req.trade_date)
    return {"success": True, "data": result}


class StopScannerRequest(BaseModel):
    sell_all: bool = False  # 是否清仓所有持仓


@router.post("/stop")
async def stop_scanner(req: StopScannerRequest = StopScannerRequest()):
    """停止扫描(可选清仓)"""
    scanner = _get_scanner()
    result = await scanner.stop(sell_all=req.sell_all)
    return {"success": True, "data": result}


# ==================== 数据 ====================

@router.get("/signals")
async def get_signals():
    """获取当前活跃信号"""
    scanner = _get_scanner()
    return _sanitize({"success": True, "data": scanner.get_signals()})


@router.get("/positions")
async def get_positions():
    """获取实时持仓"""
    scanner = _get_scanner()
    return _sanitize({"success": True, "data": scanner.get_positions()})


@router.get("/timeline")
async def get_timeline():
    """获取今日交易时间线"""
    scanner = _get_scanner()
    return _sanitize({"success": True, "data": scanner.get_timeline()})

@router.get("/timeline/history")
async def get_timeline_history(date: str = None, days: int = 7):
    """获取历史交易时间线
    
    Args:
        date: 指定日期(YYYYMMDD), 不传则返回最近N天
        days: 返回最近N天(默认7)
    """
    scanner = _get_scanner()
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
        
        return {"success": True, "data": items, "count": len(items)}
    except Exception as e:
        return {"success": True, "data": [], "message": str(e)}


@router.get("/account")
async def get_account():
    """获取账户信息(资金/持仓/盈亏)"""
    scanner = _get_scanner()
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

@router.post("/trade")
async def manual_trade(req: ManualTradeRequest):
    """手动交易(买入/卖出)
    
    用于实盘人工干预: 手动买入/卖出/调仓
    """
    scanner = _get_scanner()
    
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
    scanner = _get_scanner()
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
    scanner = _get_scanner()
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
    scanner = _get_scanner()
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
async def get_orders(limit: int = 50):
    """获取历史订单(从MongoDB)"""
    scanner = _get_scanner()
    if not scanner._broker:
        return {"success": True, "data": []}
    
    try:
        if not await scanner._broker._ensure_mongo():
            return {"success": True, "data": []}
        
        db = scanner._broker._mongo_db
        docs = await db["broker_orders"].find(
            {"account_id": scanner._broker.account.account_id}
        ).sort("create_time", -1).limit(limit).to_list(limit)
        
        # 转换ObjectId
        for d in docs:
            d.pop("_id", None)
        
        return {"success": True, "data": docs}
    except Exception as e:
        return {"success": True, "data": [], "message": str(e)}


@router.get("/limit-pools")
async def get_limit_pools():
    """获取今日涨停/跌停/炸板池"""
    scanner = _get_scanner()
    
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


@router.get("/daily-report")
async def get_daily_report():
    """每日复盘报告"""
    scanner = _get_scanner()
    if not scanner._broker:
        return {"success": True, "data": {}}
    
    try:
        acct = scanner._broker.get_account()
        positions = scanner._broker.get_positions()
        cb = scanner._circuit_breaker
        stats = scanner._stats
        
        # 按策略汇总(含胜率和收益)
        strategy_summary = {}
        for pos in positions:
            key = pos.strategy or "unknown"
            if key not in strategy_summary:
                strategy_summary[key] = {"count": 0, "market_value": 0, "total_profit": 0, "win_count": 0, "loss_count": 0}
            strategy_summary[key]["count"] += 1
            strategy_summary[key]["market_value"] += pos.current_price * pos.total_qty
            profit = (pos.current_price - pos.avg_cost) * pos.total_qty
            strategy_summary[key]["total_profit"] += profit
            if profit >= 0:
                strategy_summary[key]["win_count"] += 1
            else:
                strategy_summary[key]["loss_count"] += 1
        
        # 从时间线统计已平仓策略表现
        for item in scanner._timeline:
            if item.get("action") == "sell" and item.get("strategy"):
                key = item["strategy"]
                if key not in strategy_summary:
                    strategy_summary[key] = {"count": 0, "market_value": 0, "total_profit": 0, "win_count": 0, "loss_count": 0, "closed_profit": 0, "closed_count": 0}
                if "closed_count" not in strategy_summary[key]:
                    strategy_summary[key]["closed_count"] = 0
                    strategy_summary[key]["closed_profit"] = 0
                strategy_summary[key]["closed_count"] = strategy_summary[key].get("closed_count", 0) + 1
                strategy_summary[key]["closed_profit"] = strategy_summary[key].get("closed_profit", 0) + item.get("profit_amount", 0)
                if item.get("profit_pct", 0) >= 0:
                    strategy_summary[key]["win_count"] = strategy_summary[key].get("win_count", 0) + 1
                else:
                    strategy_summary[key]["loss_count"] = strategy_summary[key].get("loss_count", 0) + 1
        
        # 计算策略胜率
        for key in strategy_summary:
            total = strategy_summary[key].get("win_count", 0) + strategy_summary[key].get("loss_count", 0)
            strategy_summary[key]["win_rate"] = round(strategy_summary[key].get("win_count", 0) / max(total, 1) * 100, 1)
        
        # 从MongoDB获取今日订单统计
        today_trades = {"buy": 0, "sell": 0, "total_amount": 0}
        if await scanner._broker._ensure_mongo():
            db = scanner._broker._mongo_db
            today = datetime.now().strftime("%Y%m%d")
            async for doc in db["broker_orders"].find({
                "account_id": scanner._broker.account.account_id,
                "trade_date": today,
                "status": "filled"
            }):
                side = doc.get("side", "")
                today_trades[side] = today_trades.get(side, 0) + 1
                today_trades["total_amount"] += doc.get("filled_price", 0) * doc.get("filled_qty", 0)
        
        report = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "account": {
                "total_assets": round(acct.total_assets, 2),
                "available_cash": round(acct.available_cash, 2),
                "market_value": round(acct.market_value, 2),
                "today_profit": round(acct.today_profit, 2),
                "total_profit": round(acct.total_profit, 2),
                "position_ratio": round(acct.market_value / max(acct.total_assets, 1) * 100, 1),
            },
            "positions": {
                "count": len(positions),
                "strategy_summary": strategy_summary,
                "top_profit": sorted(
                    [{"ts_code": p.ts_code, "name": p.stock_name, "pct": round(p.profit_pct, 1)} for p in positions],
                    key=lambda x: x["pct"], reverse=True
                )[:5],
                "top_loss": sorted(
                    [{"ts_code": p.ts_code, "name": p.stock_name, "pct": round(p.profit_pct, 1)} for p in positions],
                    key=lambda x: x["pct"]
                )[:5],
            },
            "trades": today_trades,
            "win_rate": round(stats.get("take_profits", 0) / max(stats.get("trades_executed", 1), 1) * 100, 1) if stats.get("trades_executed", 0) > 0 else 0,
            "stop_loss_count": stats.get("stop_losses", 0),
            "take_profit_count": stats.get("take_profits", 0),
            "risk": {
                "circuit_breaker": cb.get("trading_paused", False),
                "consecutive_losses": cb.get("consecutive_losses", 0),
                "today_losses": cb.get("today_losses", 0),
            },
            "scanner_stats": stats,
        }
        
        return {"success": True, "data": report}
    except Exception as e:
        return {"success": True, "data": {}, "message": str(e)}


@router.post("/daily-settlement")
async def daily_settlement():
    """手动触发日结算(T+1解锁)"""
    scanner = _get_scanner()
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


@router.post("/reset")
async def reset_account():
    """清仓重置(清空所有持仓/订单, 恢复初始资金)"""
    scanner = _get_scanner()
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

@router.get("/trade-detail/{ts_code}")
async def get_trade_detail(ts_code: str):
    """获取指定股票的完整交易审查详情
    
    包含：买入原因、9层筛选决策链路、卖出原因、盈亏分析
    用于人工审查自动交易的决策是否合理
    """
    scanner = _get_scanner()
    
    detail = {
        "ts_code": ts_code,
        "buy": None,       # 买入决策详情
        "sell": None,      # 卖出决策详情
        "position": None,  # 当前持仓状态
        "signal": None,    # 当前信号状态
    }
    
    # 1. 从时间线查找买入/卖出记录
    for item in scanner._timeline:
        if item.get("ts_code") == ts_code:
            if item.get("action") == "buy" and not detail["buy"]:
                detail["buy"] = {
                    "time": item.get("time", ""),
                    "price": item.get("price", 0),
                    "shares": item.get("shares", 0),
                    "reason": item.get("reason", ""),
                    "strategy": item.get("strategy", ""),
                    "decision_detail": item.get("decision_detail", {}),
                }
            elif item.get("action") == "sell" and not detail["sell"]:
                detail["sell"] = {
                    "time": item.get("time", ""),
                    "price": item.get("price", 0),
                    "shares": item.get("shares", 0),
                    "reason": item.get("reason", ""),
                    "profit_pct": item.get("profit_pct", 0),
                    "decision_detail": item.get("decision_detail", {}),
                }
    
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
    
    # 4. 从历史订单查找
    orders = []
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
    
    return {"success": True, "data": detail}


@router.get("/trade-audit")
async def get_trade_audit():
    """获取全部交易的审查摘要
    
    每笔交易一行，包含买入/卖出原因和盈亏
    用于快速扫描所有自动交易的决策质量
    """
    scanner = _get_scanner()
    
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
    
    return {"success": True, "data": list(traded_stocks.values())}


@router.get("/backtest-compare")
async def backtest_compare():
    """实盘vs回测对比
    
    返回各策略的回测指标和实盘指标对比
    """
    scanner = _get_scanner()
    try:
        from core.managers import mongo_manager
        
        # 获取实盘统计
        stats = scanner._stats
        cb = scanner._circuit_breaker
        
        # 获取各策略的实盘表现
        live_performance = {}
        if scanner._broker:
            for pos in scanner._broker.get_positions():
                key = pos.strategy or "unknown"
                if key not in live_performance:
                    live_performance[key] = {"trades": 0, "wins": 0, "total_pnl": 0, "positions": 0}
                live_performance[key]["positions"] += 1
                live_performance[key]["total_pnl"] += (pos.current_price - pos.avg_cost) * pos.total_qty
        
        # 从时间线统计各策略交易
        for item in scanner._timeline:
            strategy = item.get("strategy", "unknown")
            if strategy not in live_performance:
                live_performance[strategy] = {"trades": 0, "wins": 0, "total_pnl": 0, "positions": 0}
            if item.get("action") == "buy":
                live_performance[strategy]["trades"] += 1
            elif item.get("action") == "sell":
                pnl = item.get("profit_pct", 0)
                if pnl > 0:
                    live_performance[strategy]["wins"] += 1
        
        # 获取最近回测结果
        backtest_results = {}
        if mongo_manager.db is not None:
            today = datetime.now().strftime("%Y%m%d")
            async for doc in mongo_manager.db["backtest_results"].find(
                {"status": "completed"},
                {"_id": 0, "task_id": 1, "params.strategy_ids": 1, "result.summary": 1, "created_at": 1}
            ).sort("created_at", -1).limit(5):
                strategies = doc.get("params", {}).get("strategy_ids", [])
                summary = doc.get("result", {}).get("summary", {})
                for sid in strategies:
                    if sid not in backtest_results:
                        backtest_results[sid] = {
                            "total_return": summary.get("total_return", 0),
                            "win_rate": summary.get("win_rate", 0),
                            "max_drawdown": summary.get("max_drawdown", 0),
                            "sharpe": summary.get("sharpe_ratio", 0),
                            "trades": summary.get("total_trades", 0),
                            "task_id": doc.get("task_id", ""),
                        }
        
        # 组装对比数据
        compare = []
        all_strategies = set(list(live_performance.keys()) + list(backtest_results.keys()))
        for sid in all_strategies:
            lp = live_performance.get(sid, {})
            bt = backtest_results.get(sid, {})
            compare.append({
                "strategy": sid,
                "live_trades": lp.get("trades", 0),
                "live_win_rate": round(lp.get("wins", 0) / max(lp.get("trades", 1), 1) * 100, 1),
                "live_pnl": round(lp.get("total_pnl", 0), 2),
                "live_positions": lp.get("positions", 0),
                "bt_return": round(bt.get("total_return", 0) * 100, 1),
                "bt_win_rate": round(bt.get("win_rate", 0) * 100, 1),
                "bt_drawdown": round(bt.get("max_drawdown", 0) * 100, 1),
                "bt_sharpe": round(bt.get("sharpe", 0), 2),
                "bt_trades": bt.get("trades", 0),
            })
        
        return {"success": True, "data": compare}
    except Exception as e:
        return {"success": True, "data": [], "message": str(e)}


# ==================== 调试增强 API ====================

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
    scanner = _get_scanner()
    
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
    scanner = _get_scanner()
    
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
    scanner = _get_scanner()
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


@router.get("/debug/strategy-filter")
async def get_strategy_filter_detail():
    """获取策略筛选层的详细trace
    
    返回每个策略:
    - 原始候选数(满足条件的)
    - 过滤原因(哪些条件不满足)
    - 最终候选数
    
    用于调试策略筛选条件是否合理
    """
    scanner = _get_scanner()
    
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
    scanner = _get_scanner()
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


@router.post("/sell")
async def sell_position(req: PartialSellRequest):
    """卖出持仓(支持部分卖出)
    
    - quantity=0: 全部卖出可用持仓
    - quantity>0: 卖出指定数量(必须为100的整数倍)
    """
    scanner = _get_scanner()
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
    scanner = _get_scanner()
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

@router.get("/weekly-report")
async def get_weekly_report():
    """周报: 最近5个交易日的汇总
    
    包含:
    - 每日盈亏
    - 累计收益曲线
    - 策略表现汇总
    - 最大回撤
    - 交易统计
    """
    scanner = _get_scanner()
    if not scanner._broker:
        return {"success": True, "data": {}}
    
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": {}}
        
        account_id = scanner._broker.account.account_id
        
        # 获取最近5个交易日的订单
        start_date = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
        
        daily_stats = {}
        async for doc in mongo_manager.db["broker_orders"].find({
            "account_id": account_id,
            "trade_date": {"$gte": start_date},
            "status": "filled",
        }).sort("trade_date", 1):
            td = doc.get("trade_date", "")
            if td not in daily_stats:
                daily_stats[td] = {"buys": 0, "sells": 0, "buy_amount": 0, "sell_amount": 0, "strategies": {}}
            
            side = doc.get("side", "")
            amount = doc.get("filled_price", 0) * doc.get("filled_qty", 0)
            strategy = doc.get("strategy", "unknown")
            
            if side == "buy":
                daily_stats[td]["buys"] += 1
                daily_stats[td]["buy_amount"] += amount
            else:
                daily_stats[td]["sells"] += 1
                daily_stats[td]["sell_amount"] += amount
            
            if strategy not in daily_stats[td]["strategies"]:
                daily_stats[td]["strategies"][strategy] = {"trades": 0, "amount": 0}
            daily_stats[td]["strategies"][strategy]["trades"] += 1
            daily_stats[td]["strategies"][strategy]["amount"] += amount
        
        # 获取账户快照(如果有)
        account_snapshots = {}
        async for doc in mongo_manager.db["broker_accounts"].find(
            {"account_id": account_id}
        ):
            account_snapshots[doc.get("updated_at", "")] = doc
        
        # 当前账户状态
        acct = scanner._broker.get_account()
        
        # 策略汇总
        strategy_summary = {}
        for td, stats in daily_stats.items():
            for strat, sdata in stats.get("strategies", {}).items():
                if strat not in strategy_summary:
                    strategy_summary[strat] = {"trades": 0, "amount": 0}
                strategy_summary[strat]["trades"] += sdata["trades"]
                strategy_summary[strat]["amount"] += sdata["amount"]
        
        # 总交易统计
        total_buys = sum(d["buys"] for d in daily_stats.values())
        total_sells = sum(d["sells"] for d in daily_stats.values())
        total_buy_amount = sum(d["buy_amount"] for d in daily_stats.values())
        total_sell_amount = sum(d["sell_amount"] for d in daily_stats.values())
        
        report = {
            "period": f"{start_date} ~ {datetime.now().strftime('%Y%m%d')}",
            "account": {
                "total_assets": round(acct.total_assets, 2),
                "total_profit": round(acct.total_profit, 2),
                "available_cash": round(acct.available_cash, 2),
            },
            "daily_stats": daily_stats,
            "strategy_summary": strategy_summary,
            "totals": {
                "trading_days": len(daily_stats),
                "total_buys": total_buys,
                "total_sells": total_sells,
                "total_buy_amount": round(total_buy_amount, 2),
                "total_sell_amount": round(total_sell_amount, 2),
                "net_flow": round(total_sell_amount - total_buy_amount, 2),
            },
            "scanner_stats": scanner._stats,
        }
        
        return {"success": True, "data": report}
    except Exception as e:
        return {"success": True, "data": {}, "message": str(e)}


@router.get("/trade-log")
async def get_trade_log(days: int = 30, format: str = "json"):
    """交易日志(可导出)
    
    Args:
        days: 最近N天
        format: json | csv
    """
    scanner = _get_scanner()
    if not scanner._broker:
        return {"success": True, "data": []}
    
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": []}
        
        account_id = scanner._broker.account.account_id
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
        
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

@router.post("/snapshot")
async def save_performance_snapshot():
    """保存当前性能快照到MongoDB(用于历史追踪)
    
    记录: 账户状态/持仓/信号/时间线/统计
    用于后续复盘和回测对比
    """
    scanner = _get_scanner()
    if not scanner._broker:
        return {"success": True, "data": {"message": "Broker未初始化"}}
    
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": {}}
        
        acct = scanner._broker.get_account()
        positions = scanner._broker.get_positions()
        
        snapshot = {
            "account_id": scanner._broker.account.account_id,
            "timestamp": datetime.now().isoformat(),
            "trade_date": datetime.now().strftime("%Y%m%d"),
            "account": {
                "total_assets": acct.total_assets,
                "available_cash": acct.available_cash,
                "market_value": acct.market_value,
                "total_profit": acct.total_profit,
            },
            "positions": [{
                "ts_code": p.ts_code,
                "stock_name": p.stock_name,
                "shares": p.total_qty,
                "cost_price": p.avg_cost,
                "current_price": p.current_price,
                "profit_pct": p.profit_pct,
                "strategy": p.strategy,
            } for p in positions],
            "active_signals": len(scanner._active_signals),
            "timeline_count": len(scanner._timeline),
            "stats": dict(scanner._stats),
            "circuit_breaker": scanner._circuit_breaker,
            "sentiment": scanner._current_sentiment,
            "position_ratio": scanner._current_position_ratio,
        }
        
        await mongo_manager.db["performance_snapshots"].insert_one(snapshot)
        
        return {"success": True, "data": {"message": "快照已保存", "timestamp": snapshot["timestamp"]}}
    except Exception as e:
        return {"success": True, "data": {"message": f"保存失败: {e}"}}


@router.get("/performance-history")
async def get_performance_history(days: int = 30):
    """获取历史性能快照(资产曲线)"""
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": []}
        
        start = (datetime.now() - timedelta(days=days)).isoformat()
        
        snapshots = []
        async for doc in mongo_manager.db["performance_snapshots"].find(
            {"timestamp": {"$gte": start}}
        ).sort("timestamp", 1):
            doc.pop("_id", None)
            snapshots.append(doc)
        
        return {"success": True, "data": snapshots, "count": len(snapshots)}
    except Exception as e:
        return {"success": True, "data": [], "message": str(e)}


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
    scanner = _get_scanner()
    report = scanner.generate_summary_report()
    return _sanitize({"success": True, "data": report})


@router.get("/quote/{ts_code}")
async def get_realtime_quote(ts_code: str):
    """获取单只股票实时行情(用于手动下单自动填充)
    
    优先从scanner缓存获取, 缓存未命中则从东方财富/必盈获取
    """
    scanner = _get_scanner()
    
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
            return {"success": True, "health": {
                "overall_status": "dead", "message": "Scanner未运行",
                "checks": {}, "circuit_breaker": {"trading_paused": False},
                "risk_metrics": {"daily_drawdown_pct": 0, "max_drawdown_pct": 5, "position_ratio": 0},
                "health_score": 0, "scan_lag_seconds": -1, "risk_check_lag_seconds": -1,
                "data_freshness": "red",
                "warnings": ["Scanner未运行"], "data_sources": [],
                "version": _get_version_info(),
            }}
        
        # 基础状态
        watchdog = getattr(scanner, '_risk_watchdog', None)
        watchdog_status = watchdog.get_status() if watchdog else {
            "overall_status": "unknown", "checks": {}, "uptime_seconds": 0,
            "scanner_heartbeat_age": -1, "alert_count": 0
        }
        
        # 补充scanner级别的checks(策略+数据源)
        checks = watchdog_status.get("checks", {})
        
        # 策略状态 — 基于信号产出
        for strategy_key in ["halfway_chase", "first_limit_up", "dragon_head", "limit_down_qiao"]:
            strategy_signals = [s for s in scanner._active_signals if s.strategy == strategy_key]
            total_signals = getattr(scanner, '_scan_count', 0)
            if total_signals > 0 and len(strategy_signals) > 0:
                checks[strategy_key] = {
                    "status": "healthy",
                    "value": f"{len(strategy_signals)}个活跃信号",
                    "threshold": ">0",
                    "message": "策略正常产出信号"
                }
            elif total_signals > 0:
                checks[strategy_key] = {
                    "status": "unknown",
                    "value": "无信号",
                    "threshold": ">0",
                    "message": "当前无信号(可能正常)"
                }
            else:
                checks[strategy_key] = {
                    "status": "unknown",
                    "value": "未扫描",
                    "threshold": ">0",
                    "message": "尚未执行扫描"
                }
        
        # 数据源状态
        data_router = getattr(scanner, '_data_router', None)
        ds_list = []
        if data_router:
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
                    "message": status_info.get('note', '')
                }
        
        # 风控指标
        broker = scanner._broker
        acc = broker.account if broker else None
        total_assets = acc.total_assets if acc else 0
        market_value = acc.market_value if acc else 0
        daily_profit = acc.today_profit if acc else 0
        positions = broker.positions if broker else {}
        daily_drawdown = abs(min(0, daily_profit / total_assets * 100)) if total_assets > 0 else 0
        position_ratio = market_value / total_assets if total_assets > 0 else 0
        
        # 【v2.9.10:统一健康度计算 — 合并API层与ScannerUtils两套重复逻辑】
        # 之前: API层自算health_score(100扣减) + scanner_health(ScannerUtils绿黄红), 两套逻辑不一致
        # 现在: 以ScannerUtils.compute_health_score()为权威, API层只补充金融指标(回撤/熔断)
        import time as _time
        now = _time.time()
        scan_lag = now - scanner._last_scan_ts if getattr(scanner, '_last_scan_ts', 0) > 0 else 999
        risk_check_lag = now - getattr(scanner, '_last_risk_check_ts', 0) if getattr(scanner, '_last_risk_check_ts', 0) > 0 else 999
        
        # 1. Scanner内置健康度(权威来源: 绿/黄/红 + warnings)
        scanner_health = scanner._compute_health_score() if hasattr(scanner, '_compute_health_score') else {
            "status": "unknown", "is_healthy": False, "scan_lag_seconds": scan_lag,
            "risk_check_lag_seconds": risk_check_lag, "quote_staleness_seconds": 999,
            "risk_thread_alive": False, "risk_thread_restarts": 0, "warnings": []
        }
        
        # 2. 金融指标(API层独有, ScannerUtils不涉及)
        cb = getattr(scanner, '_circuit_breaker', None) or {}
        consecutive_losses = cb.get('consecutive_losses', 0) if isinstance(cb, dict) else 0
        trading_paused = cb.get('trading_paused', False) if isinstance(cb, dict) else False
        
        # 3. 【v2.9.10:线程安全读取pending_sells】之前无锁, 与风控线程竞态
        state_lock = getattr(scanner, '_state_lock', None)
        if state_lock:
            with state_lock:
                pending_sells_count = len(scanner._pending_sells)
        else:
            pending_sells_count = len(getattr(scanner, '_pending_sells', {}))
        pending_sells_detail = []
        if pending_sells_count > 0 and hasattr(scanner, '_position_manager') and scanner._position_manager:
            pending_sells_detail = scanner._position_manager.get_pending_sells_summary()
        
        # 4. 合并warnings(ScannerUtils + 金融指标)
        merged_warnings = list(scanner_health.get('warnings', []))
        if daily_drawdown >= 3:
            merged_warnings.append(f"日回撤{daily_drawdown:.1f}%")
        if consecutive_losses >= 2:
            merged_warnings.append(f"连续亏损{consecutive_losses}次")
        if pending_sells_count > 0:
            merged_warnings.append(f"{pending_sells_count}只跌停挂起")
        if trading_paused:
            merged_warnings.append("熔断器已触发")
        
        # 5. 统一健康分数(0-100, 基于scanner_health的绿/黄/红 + 金融扣减)
        base_score = {"green": 100, "yellow": 60, "red": 30}.get(scanner_health.get('status', 'red'), 30)
        health_score = base_score
        if daily_drawdown >= 3:
            health_score -= 15
        if daily_drawdown >= 5:
            health_score -= 20
        if consecutive_losses >= 2:
            health_score -= 10
        if trading_paused:
            health_score -= 25
        health_score = max(0, health_score)
        
        # 6. 数据新鲜度标记(3s绿/5s黄/>5s红 — 前端UI用)
        data_freshness = "green" if scan_lag < 60 and risk_check_lag < 5 else (
            "yellow" if scan_lag < 120 and risk_check_lag < 30 else "red")
        
        # 风控线程状态(从scanner_health提取, 避免重复读取)
        risk_thread_alive = scanner_health.get('risk_thread_alive', False)
        risk_thread_restarts = scanner_health.get('risk_thread_restarts', 0)
        
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
        
        # 综合状态判断(基于scanner_health + 金融指标)
        overall = scanner_health.get('status', 'unknown')
        if daily_drawdown >= 5 or trading_paused:
            overall = 'critical'
        elif daily_drawdown >= 3 or consecutive_losses >= 2:
            overall = 'degraded'
        
        return {
            "success": True, 
            "health": {
                **watchdog_status,
                "overall_status": overall,
                "checks": checks,
                "circuit_breaker": circuit_breaker,
                "risk_metrics": risk_metrics,
                "data_sources": ds_list,
                # 【v2.9.10:统一健康度 — health_score基于scanner_health+金融扣减】
                "health_score": health_score,
                "data_freshness": data_freshness,
                "scan_lag_seconds": round(scan_lag, 1),
                "risk_check_lag_seconds": round(risk_check_lag, 1),
                "warnings": merged_warnings,
                "is_healthy": scanner_health.get('is_healthy', False) and daily_drawdown < 3 and not trading_paused,
                # Scanner内置健康度(绿/黄/红) — 权威来源
                "scanner_health": scanner_health,
                # 跌停挂起明细(v2.9.4)
                "pending_sells_detail": pending_sells_detail,
                # 风控线程状态
                "risk_thread": {
                    "alive": risk_thread_alive,
                    "restarts": risk_thread_restarts,
                },
                # 【v2.9.7: Daemon状态(如果可用)】
                "daemon": _get_daemon_status(),
                # 【Phase4.2: 版本信息(部署验证)】
                "version": _get_version_info(),
            }
        }
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
_DESIGN_DOC_VERSION = "v2.9.15"
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


@router.post("/emergency-liquidate")
async def emergency_liquidate(request: Request):
    """🚨 紧急平仓 — 独立于Scanner主循环, 直连Broker执行
    
    用途: GUI红色按钮 / API紧急调用
    安全: 需要确认参数 reason
    """
    try:
        body = await request.json()
        reason = body.get("reason", "API手动触发")
        
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


@router.get("/params/{strategy_id}")
async def get_strategy_params(strategy_id: str):
    """获取策略参数(从参数中心读取)"""
    try:
        from nodes.market_monitor.strategy_param_center import param_center
        params = await param_center.get_strategy_params(strategy_id)
        if not params:
            return {"success": True, "data": {}, "message": f"策略{strategy_id}无参数"}
        return {"success": True, "data": params}
    except Exception as e:
        return {"success": True, "data": {}, "message": str(e)}


@router.get("/params")
async def get_all_strategy_params():
    """获取所有策略参数"""
    try:
        from nodes.market_monitor.strategy_param_center import param_center
        params = await param_center.get_all_params()
        return {"success": True, "data": params, "count": len(params)}
    except Exception as e:
        return {"success": True, "data": {}, "message": str(e)}


@router.put("/params/{strategy_id}")
async def update_strategy_params(strategy_id: str, request: Request):
    """更新策略参数(热更新,无需重启Scanner)
    
    修改后自动推送到Scanner, 回测和实盘共用同一参数源。
    """
    try:
        body = await request.json()
        updates = body.get("params", {})
        comment = body.get("comment", "")
        updated_by = body.get("updated_by", "api")
        
        if not updates:
            return {"success": False, "message": "无参数更新"}
        
        from nodes.market_monitor.strategy_param_center import param_center
        
        # 注册Scanner热更新回调(如果还没注册)
        scanner = _get_scanner_instance()
        if scanner and not param_center._on_update:
            param_center.set_on_update_callback(scanner.update_strategy_config)
        
        ok = await param_center.update_strategy_params(
            strategy_id, updates, updated_by=updated_by, comment=comment
        )
        
        if ok:
            return {"success": True, "message": f"策略{strategy_id}参数已更新(热更新)"}
        else:
            return {"success": False, "message": "更新失败"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.get("/params/{strategy_id}/history")
async def get_params_history(strategy_id: str, limit: int = 20):
    """获取策略参数修改历史"""
    try:
        from nodes.market_monitor.strategy_param_center import param_center
        history = await param_center.get_params_history(strategy_id, limit)
        return {"success": True, "data": history, "count": len(history)}
    except Exception as e:
        return {"success": True, "data": [], "message": str(e)}


@router.post("/params/{strategy_id}/reset")
async def reset_strategy_params(strategy_id: str):
    """重置策略参数为默认值"""
    try:
        from nodes.market_monitor.strategy_param_center import param_center
        ok = await param_center.reset_to_defaults(strategy_id)
        if ok:
            return {"success": True, "message": f"策略{strategy_id}参数已重置为默认值"}
        else:
            return {"success": False, "message": "重置失败"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/params/validate")
async def validate_params_before_update(request: Request):
    """【v2.9.15】参数预检验证(不实际更新)
    
    前端提交参数更新前先调用此端点, 检查参数合理性。
    返回warnings数组(空=安全可直接提交, 非空=需用户确认)。
    
    Body: {strategy_id: str, params: {key: value, ...}}
    """
    try:
        body = await request.json()
        strategy_id = body.get("strategy_id", "default")
        params = body.get("params", {})
        
        if not params:
            return {"success": True, "warnings": [], "is_safe": True, "message": "无参数需验证"}
        
        warnings = []
        
        # 1. 止损检查
        sl = params.get("stop_loss_pct")
        if sl is not None:
            if sl > 0.10:
                warnings.append(f"止损{sl*100:.1f}%过宽, 实盘建议≤8%")
            elif sl < 0.02:
                warnings.append(f"止损{sl*100:.1f}%过紧, 实盘建议≥2%(容易被震出)")
        
        # 2. 止盈检查
        tp = params.get("take_profit_pct")
        if tp is not None and tp < 0.03:
            warnings.append(f"止盈{tp*100:.1f}%过低, 实盘建议≥3%")
        
        # 3. 单票仓位上限检查
        max_ratio = params.get("max_position_ratio")
        if max_ratio is not None and max_ratio > 0.8:
            warnings.append(f"单票仓位{max_ratio*100:.0f}%过高, 实盘建议≤15%")
        
        # 4. 追踪止损步长检查
        trail = params.get("trailing_stop_step")
        if trail is not None and trail < 0.01:
            warnings.append(f"追踪止损步长{trail*100:.1f}%过紧, 可能被震出")
        
        # 5. 情绪调仓比例检查
        rebalance = params.get("emotion_rebalance_ratio")
        if rebalance is not None and rebalance > 0.5:
            warnings.append(f"情绪调仓比例{rebalance*100:.0f}%过高, 建议≤30%")
        
        return {
            "success": True,
            "strategy_id": strategy_id,
            "warnings": warnings,
            "is_safe": len(warnings) == 0,
        }
    except Exception as e:
        return {"success": False, "message": str(e), "warnings": []}


# ==================== V59:执行质量 & 追踪止损 API ====================

@router.get("/execution-quality")
async def get_execution_quality():
    """获取执行质量统计
    
    对标真实量化: 执行质量是衡量量化系统水平的关键指标
    - 滑点: 实际成交价vs预期价的偏差
    - 止损响应: 信号触发到实际成交的时间
    - 成交率: 下单成功率vs拒绝率
    """
    try:
        scanner = _get_scanner_instance()
        if not scanner:
            return {"success": False, "message": "Scanner未运行"}
        
        stats = getattr(scanner, '_execution_stats', {})
        trailing = _safe_read_shared(scanner, '_trailing_stops')
        risk_levels = _safe_read_shared(scanner, '_position_risk_levels')
        
        return {
            "success": True,
            "data": {
                "execution_stats": stats,
                "trailing_stops_active": {k: v for k, v in trailing.items() if v.get("activated")},
                "risk_levels": risk_levels,
                "smart_check_interval": scanner._get_smart_check_interval() if hasattr(scanner, '_get_smart_check_interval') else 30,
            }
        }
    except Exception as e:
        return {"success": False, "message": str(e)}


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
        scanner = _get_scanner()
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


@router.get("/strategy-performance")
async def get_strategy_performance():
    """策略实时绩效看板"""
    scanner = _get_scanner()
    if not scanner._broker:
        return {"success": True, "data": []}

    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": []}
        positions = scanner._broker.get_positions()
        timeline = scanner._timeline
        strategy_names = {"halfway_chase": "半路追涨", "first_limit_up": "首板打板", "dragon_head": "龙头低吸", "limit_down_qiao": "跌停翘板", "limit_up_open": "涨停开板", "manual": "手动"}

        strategies = {}
        for key, name in strategy_names.items():
            strategies[key] = {"key": key, "name": name, "today_profit": 0, "total_profit": 0, "win_count": 0, "loss_count": 0, "position_count": 0, "closed_count": 0, "max_win_pct": 0, "max_loss_pct": 0, "sparkline": []}

        for pos in positions:
            key = pos.strategy or "manual"
            if key not in strategies:
                strategies[key] = {"key": key, "name": strategy_names.get(key, key), "today_profit": 0, "total_profit": 0, "win_count": 0, "loss_count": 0, "position_count": 0, "closed_count": 0, "max_win_pct": 0, "max_loss_pct": 0, "sparkline": []}
            profit = (pos.current_price - pos.avg_cost) * pos.total_qty
            strategies[key]["position_count"] += 1
            strategies[key]["total_profit"] += profit
            strategies[key]["today_profit"] += profit
            if profit >= 0: strategies[key]["win_count"] += 1
            else: strategies[key]["loss_count"] += 1

        all_profits = {}
        for item in (timeline or []):
            if item.get("action") == "sell" and item.get("strategy"):
                key = item["strategy"]
                pct = item.get("profit_pct", 0)
                all_profits.setdefault(key, []).append(pct)
                if key in strategies:
                    strategies[key]["closed_count"] += 1
                    if pct >= 0:
                        strategies[key]["win_count"] += 1
                        strategies[key]["max_win_pct"] = max(strategies[key]["max_win_pct"], pct)
                    else:
                        strategies[key]["loss_count"] += 1
                        strategies[key]["max_loss_pct"] = min(strategies[key]["max_loss_pct"], pct)

        for key, s in strategies.items():
            total = s["win_count"] + s["loss_count"]
            s["win_rate"] = round(s["win_count"] / max(total, 1) * 100, 1)
            profits = all_profits.get(key, [])
            avg_win = sum(p for p in profits if p >= 0) / max(sum(1 for p in profits if p >= 0), 1)
            avg_loss = abs(sum(p for p in profits if p < 0) / max(sum(1 for p in profits if p < 0), 1))
            s["profit_loss_ratio"] = round(avg_win / max(avg_loss, 0.01), 2)
            s["avg_profit_pct"] = round(sum(profits) / max(len(profits), 1), 2) if profits else 0

        # Sparkline from performance snapshots
        try:
            from datetime import datetime, timedelta
            start = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d")
            perf_data = []
            async for doc in mongo_manager.db["scanner_performance"].find({"date": {"$gte": start}}, {"_id": 0, "date": 1, "total_assets": 1}).sort("date", 1):
                perf_data.append(doc)
            if perf_data:
                baseline = perf_data[0].get("total_assets", 1000000)
                sparkline = [round((d.get("total_assets", baseline) / baseline - 1) * 100, 2) for d in perf_data]
                for key in strategies: strategies[key]["sparkline"] = sparkline
        except Exception:
            pass

        result = [s for s in strategies.values() if s["position_count"] > 0 or s["closed_count"] > 0]
        total_row = {"key": "total", "name": "合计", "today_profit": sum(s["today_profit"] for s in result), "total_profit": sum(s["total_profit"] for s in result),
                     "win_count": sum(s["win_count"] for s in result), "loss_count": sum(s["loss_count"] for s in result),
                     "win_rate": 0, "profit_loss_ratio": 0, "position_count": sum(s["position_count"] for s in result),
                     "closed_count": sum(s["closed_count"] for s in result), "max_win_pct": max((s["max_win_pct"] for s in result), default=0),
                     "max_loss_pct": min((s["max_loss_pct"] for s in result), default=0), "avg_profit_pct": 0, "sparkline": []}
        tt = total_row["win_count"] + total_row["loss_count"]
        total_row["win_rate"] = round(total_row["win_count"] / max(tt, 1) * 100, 1)
        result.append(total_row)
        return _sanitize({"success": True, "data": result})
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.get("/position-risk-matrix")
async def get_position_risk_matrix():
    """持仓风控矩阵 + 全局风险仪表"""
    scanner = _get_scanner()
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
                "ts_code": pos.ts_code, "stock_name": pos.stock_name,
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


@router.get("/market-sentiment")
async def get_market_sentiment_detail():
    """市场情绪全景"""
    scanner = _get_scanner()
    try:
        filter_pipeline = getattr(scanner, '_filter_pipeline', None)
        emotion = getattr(filter_pipeline, '_emotion_cycle', None) if filter_pipeline else None
        sentiment_score = getattr(emotion, 'score', 50) if emotion else 50
        sentiment_period = getattr(emotion, 'period', 'unknown') if emotion else 'unknown'
        position_ratio = getattr(emotion, 'position_ratio', 1.0) if emotion else 1.0
        limit_pools = getattr(scanner, '_limit_pools', {})
        limit_up = len(limit_pools.get("limit_up", []))
        limit_down = len(limit_pools.get("limit_down", []))
        broken = len(limit_pools.get("broken", []))
        broken_rate = broken / max(limit_up + broken, 1) * 100
        board_dist = {}
        for item in limit_pools.get("limit_up", []):
            t = item.get("limit_times", 1)
            board_dist[str(t)] = board_dist.get(str(t), 0) + 1

        period_labels = {"BEARISH": ("冰点", 0, 40), "CHAOS": ("震荡", 40, 55), "DIFFERENTIATION": ("分化", 55, 70), "RISING": ("高潮", 70, 100)}
        pi = period_labels.get(sentiment_period, ("未知", 0, 100))

        return _sanitize({"success": True, "data": {
            "score": sentiment_score, "period": sentiment_period, "period_label": pi[0],
            "position_ratio": position_ratio,
            "limit_up_count": limit_up, "limit_down_count": limit_down, "broken_count": broken,
            "broken_rate": round(broken_rate, 1), "board_distribution": board_dist,
            "ranges": [
                {"label": "冰点", "min": 0, "max": 40, "color": "#67c23a"},
                {"label": "震荡", "min": 40, "max": 55, "color": "#e6a23c"},
                {"label": "分化", "min": 55, "max": 70, "color": "#409eff"},
                {"label": "高潮", "min": 70, "max": 100, "color": "#f56c6c"},
            ],
        }})
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.get("/system-health-detail")
async def get_system_health_detail():
    """系统健康运维面板"""
    scanner = _get_scanner()
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

@router.get("/premarket-status")
async def get_premarket_status():
    """盘前竞价状态、预选候选、竞价异动、竞价信号
    
    Returns:
        status: waiting/active/ended/off
        candidates: 盘前预选候选列表
        auction_signals: 竞价过滤后的信号
        top_gainers: 竞价涨幅/量比排名
    """
    try:
        scanner = _get_scanner_instance()
        if not scanner:
            return {"success": True, "data": {"status": "off", "candidates": [], "auction_signals": [], "top_gainers": []}}
        
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
        
        # 从活跃信号中提取竞价信号
        auction_signals = []
        for sig in scanner._active_signals:
            if sig.signal_status in ('new', 'executed') and sig.factors:
                # 检查是否为竞价阶段产生的信号
                if sig.factors.get('auction_pct') is not None or sig.factors.get('is_auction'):
                    auction_signals.append({
                        "ts_code": sig.ts_code,
                        "stock_name": sig.stock_name,
                        "strategy": sig.strategy,
                        "pct_chg": sig.pct_chg,
                        "volume_ratio": sig.factors.get('volume_ratio', 0),
                        "signal_status": sig.signal_status,
                    })
        
        # 竞价涨幅排名(从limit_pools或信号提取)
        top_gainers = []
        if hasattr(scanner, '_limit_pools'):
            for item in scanner._limit_pools.get('limit_up', [])[:10]:
                top_gainers.append({
                    "ts_code": item.get('ts_code', ''),
                    "name": item.get('name', ''),
                    "pct_chg": item.get('pct_chg', 0),
                    "volume_ratio": item.get('volume_ratio', 0),
                })
        
        # 盘前候选(所有活跃信号的预选)
        candidates = []
        for sig in scanner._active_signals:
            candidates.append({
                "ts_code": sig.ts_code,
                "stock_name": sig.stock_name,
                "strategy": sig.strategy,
                "auction_pct": sig.factors.get('auction_pct'),
                "reason": sig.reason[:50] if sig.reason else '',
            })
        
        return {"success": True, "data": {
            "status": status,
            "candidates": candidates[:20],
            "auction_signals": auction_signals,
            "top_gainers": top_gainers[:15],
        }}
    except Exception as e:
        return {"success": True, "data": {"status": "off", "candidates": [], "auction_signals": [], "top_gainers": [], "error": str(e)}}


@router.get("/trade-attribution")
async def get_trade_attribution(date: str = None):
    """逐笔归因分析 — 每笔交易赚在哪/亏在哪
    
    Args:
        date: 指定日期(YYYY-MM-DD), 不传则返回最近交易日
    
    Returns:
        逐笔归因列表: ts_code/strategy/buy_price/sell_price/profit_pct/sell_reason/why_profit/why_loss
    """
    try:
        scanner = _get_scanner_instance()
        if not scanner:
            return {"success": True, "data": []}
        
        attributions = []
        
        # 从timeline中提取已卖出交易
        for item in scanner._timeline:
            if item.get("action") != "sell" or not item.get("ts_code"):
                continue
            if date and not item.get("time", "").startswith(date.replace("-", "")):
                continue
            
            ts_code = item["ts_code"]
            strategy = item.get("strategy", "")
            profit_pct = item.get("profit_pct", 0)
            sell_reason = item.get("reason", "")
            
            # 归因分析
            why_profit = None
            why_loss = None
            
            if profit_pct >= 0:
                # 赚在哪: 基于策略类型和卖出原因归因
                profit_factors = []
                if "半路" in strategy or "pullback" in strategy:
                    profit_factors.append("突破均线+量能配合")
                if "龙头" in strategy or "dragon" in strategy:
                    profit_factors.append("龙头缩量回踩+板块共振")
                if "跌停" in strategy or "limit_down" in strategy:
                    profit_factors.append("翘板成功+恐慌反转")
                if "止盈" in sell_reason:
                    profit_factors.append("达到止盈目标")
                if "冲高" in sell_reason:
                    profit_factors.append("冲高兑现")
                if "利润" in sell_reason:
                    profit_factors.append("利润锁定")
                if not profit_factors:
                    profit_factors.append("趋势延续")
                why_profit = "+".join(profit_factors)
            else:
                # 亏在哪
                loss_factors = []
                if "止损" in sell_reason:
                    loss_factors.append("触发止损线")
                if "跳空" in sell_reason:
                    loss_factors.append("隔夜跳空低开")
                if "超时" in sell_reason:
                    loss_factors.append("超时未达预期")
                if "强制空仓" in sell_reason:
                    loss_factors.append("系统性风险强制清仓")
                # 策略层面归因
                if "龙头" in strategy and profit_pct < -3:
                    loss_factors.append("龙头低吸追高")
                if "半路" in strategy and profit_pct < -2:
                    loss_factors.append("突破失败假信号")
                if "跌停" in strategy:
                    loss_factors.append("翘板失败继续下跌")
                if not loss_factors:
                    loss_factors.append("行情反转")
                why_loss = "+".join(loss_factors)
            
            attributions.append({
                "ts_code": ts_code,
                "stock_name": item.get("stock_name", ""),
                "strategy": strategy,
                "buy_price": item.get("buy_price", 0),
                "sell_price": item.get("price", 0),
                "profit_pct": profit_pct,
                "profit_amount": item.get("profit_amount", 0),
                "buy_time": item.get("buy_time", ""),
                "sell_time": item.get("time", ""),
                "sell_reason": sell_reason,
                "why_profit": why_profit,
                "why_loss": why_loss,
            })
        
        return {"success": True, "data": attributions}
    except Exception as e:
        return {"success": True, "data": [], "message": str(e)}


# ==================== 自动交易操作流 + 策略参数对比 ====================

@router.get("/auto-trades")
async def get_auto_trades(date: str = None, limit: int = 50):
    """自动交易操作流 — 查看自动交易系统执行的所有操作
    
    区别于手动操作, 这是Scanner自动触发的买入/卖出
    返回带source标记的订单列表
    
    Args:
        date: 指定日期(YYYYMMDD)
        limit: 最大返回数
    """
    try:
        scanner = _get_scanner_instance()
        if not scanner:
            return {"success": True, "data": []}
        
        trades = []
        for o in scanner._broker.orders if scanner._broker else []:
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
            })
        
        # 按时间倒序
        trades.sort(key=lambda x: x.get("time", ""), reverse=True)
        return {"success": True, "data": trades[:limit]}
    except Exception as e:
        return {"success": True, "data": [], "message": str(e)}


@router.get("/strategy-params-compare")
async def get_strategy_params_compare():
    """策略参数对比 — 实盘(MongoDB) vs 回测(defaults.py)
    
    返回每个策略的所有参数, 标注与回测基线不同的字段
    用于诊断实盘-回测不一致问题
    """
    # 全局风控参数中文映射
    GLOBAL_RISK_LABELS = {
        "stop_loss_pct": "全局止损比例",
        "take_profit_pct": "全局止盈比例",
        "max_hold_days": "最大持仓天数",
        "slippage_pct": "滑点比例",
        "commission_rate": "综合佣金率",
        "stamp_duty_rate": "印花税率",
        "max_position_per_stock": "单票最大仓位",
        "max_total_position": "总仓位上限",
        "liquidity_threshold": "流动性门槛(万元)",
        "volume_threshold": "量能放大倍数",
        "force_empty_limit_down": "强制空仓-跌停数阈值",
        "force_empty_limit_up": "强制空仓-涨停数阈值",
        "force_empty_index_drop_pct": "强制空仓-大盘跌幅阈值",
        "force_empty_cooldown_days": "强制空仓冷却期(天)",
        "force_empty_cooldown_position_cap": "冷却期仓位上限",
        "dragon_head_early_exit_days": "龙头低吸-提前退出天数",
        "dragon_head_early_exit_min_profit": "龙头低吸-提前退出最低利润",
        "intraday_lock_min_high_rise": "盘中锁定-冲高幅度阈值",
        "intraday_lock_pullback_pct": "盘中锁定-回撤幅度阈值",
        "intraday_lock_min_profit": "盘中锁定-最低利润阈值",
        "hold_protection_threshold": "持仓保护阈值",
        "live_trading_mode": "实盘模式开关",
        "risk_free_rate": "无风险利率",
    }
    
    # 策略级参数中文映射(常用key)
    STRATEGY_PARAM_LABELS = {
        "stop_loss_pct": "止损比例",
        "take_profit_pct": "止盈比例",
        "max_hold_days": "最大持仓天数",
        "slippage_pct": "滑点比例",
        "pullback_sl_pct": "追踪止损比例",
        "pullback_mid_fallback": "回调中继回撤阈值",
        "hit_probability_slow": "慢板成交概率",
        "hit_probability_fast": "快板成交概率",
        "hit_probability_instant": "秒板成交概率",
        "hit_probability_one_char": "一字板成交概率",
        "next_day_open_sell_pct": "次日高开卖出阈值",
        "opening_pct_max": "开盘涨幅上限",
        "min_turnover_rate": "最低换手率",
        "min_rise_pct": "最低涨幅",
        "max_rise_pct": "最高涨幅",
        "min_volume_ratio": "最低量比",
        "max_volume_ratio": "最高量比",
        "min_close_pct": "最低收盘涨幅",
        "max_open_pct": "最高开盘涨幅",
        "before_10am_only": "仅10点前买入",
        "min_consecutive_limit": "最低连板数",
        "min_circ_mv": "最低流通市值(亿)",
        "max_circ_mv": "最高流通市值(亿)",
        "pullback_min_pct": "最低回调幅度",
        "pullback_max_pct": "最高回调幅度",
        "pullback_min_days": "最少回调天数",
        "pullback_max_days": "最多回调天数",
        "support_ma": "支撑均线",
        "consecutive_limit_down_days": "最低连跌天数",
        "min_qiaoban_amount": "最低翘板金额(万)",
        "min_qiaoban_rise_pct": "最低翘板后涨幅",
        "sentiment_override": "不限情绪周期",
    }
    
    try:
        from nodes.market_monitor.strategy_param_center import param_center
        await param_center.initialize()
        
        # 检测漂移
        drifts = await param_center.detect_drift()
        
        # 获取所有策略参数(实盘)
        live_params = {}
        for strategy_id in ['halfway_chase', 'first_limit_up', 'dragon_head', 'limit_down_qiao']:
            params = await param_center.get_strategy_params(strategy_id)
            if params:
                live_params[strategy_id] = params
        
        # 获取回测基线
        from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS, GLOBAL_RISK
        backtest_params = {}
        for strategy_id, config in STRATEGY_CONFIGS.items():
            backtest_params[strategy_id] = config
        
        # 逐策略逐参数对比
        comparisons = []
        all_strategy_ids = set(list(live_params.keys()) + list(backtest_params.keys()))
        for sid in sorted(all_strategy_ids):
            live = live_params.get(sid, {})
            bt = backtest_params.get(sid, {})
            all_keys = set(list(live.keys()) + list(bt.keys()))
            
            param_diffs = []
            for key in sorted(all_keys):
                live_val = live.get(key)
                bt_val = bt.get(key)
                label = STRATEGY_PARAM_LABELS.get(key, key)
                if live_val != bt_val and live_val is not None and bt_val is not None:
                    param_diffs.append({
                        "key": key,
                        "label": label,
                        "live_value": live_val,
                        "backtest_value": bt_val,
                        "diff": True,
                    })
                elif live_val is not None:
                    param_diffs.append({
                        "key": key,
                        "label": label,
                        "live_value": live_val,
                        "backtest_value": bt_val,
                        "diff": False,
                    })
            
            comparisons.append({
                "strategy_id": sid,
                "strategy_name": {"halfway_chase": "半路追涨", "first_limit_up": "首板打板", 
                                   "dragon_head": "龙头低吸", "limit_down_qiao": "跌停翘板",
                                   "limit_up_open": "涨停开板"}.get(sid, sid),
                "live_params": live,
                "backtest_params": bt,
                "param_diffs": param_diffs,
                "drift_count": len([d for d in param_diffs if d.get("diff")]),
            })
        
        # 全局风控参数对比
        # 修复: globalRisk嵌在每个策略文档中, 不是独立文档
        # 从第一个可用策略的globalRisk字段读取实盘值
        live_gr = {}
        for sid in ['halfway_chase', 'first_limit_up', 'dragon_head', 'limit_down_qiao']:
            strategy_doc = live_params.get(sid, {})
            if isinstance(strategy_doc, dict) and strategy_doc.get('globalRisk'):
                live_gr = strategy_doc['globalRisk']
                break
        
        global_diffs = []
        global_sames = []
        for key, bt_val in GLOBAL_RISK.items():
            live_val = live_gr.get(key)
            label = GLOBAL_RISK_LABELS.get(key, key)
            if live_val is None:
                # 实盘缺失此参数 = 使用回测默认值, 不算漂移
                global_sames.append({
                    "key": key,
                    "label": label,
                    "live_value": "(未配置,用默认值)",
                    "backtest_value": bt_val,
                    "diff": False,
                    "missing_in_live": True,
                })
            elif live_val != bt_val:
                global_diffs.append({
                    "key": key,
                    "label": label,
                    "live_value": live_val,
                    "backtest_value": bt_val,
                    "diff": True,
                    "missing_in_live": False,
                })
            else:
                global_sames.append({
                    "key": key,
                    "label": label,
                    "live_value": live_val,
                    "backtest_value": bt_val,
                    "diff": False,
                    "missing_in_live": False,
                })
        
        return {"success": True, "data": {
            "strategy_comparisons": comparisons,
            "global_risk": {
                "live": live_gr,
                "backtest": GLOBAL_RISK,
                "diffs": global_diffs,
                "sames": global_sames,
                "labels": GLOBAL_RISK_LABELS,
            },
            "drifts_detected": drifts,
            "drift_count": len(drifts) + len(global_diffs),
        }}
    except Exception as e:
        return {"success": True, "data": {"strategy_comparisons": [], "global_risk": {}, "drifts_detected": [], "drift_count": 0, "error": str(e)}}


# ==================== 扫描配置查询端点 ====================

@router.get("/scan-config")
async def get_scan_config():
    """获取扫描器配置信息 — 间隔、模式、参数等
    
    用于前端展示扫描器运行参数，方便用户了解自动扫描行为
    """
    scanner = _get_scanner()
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
