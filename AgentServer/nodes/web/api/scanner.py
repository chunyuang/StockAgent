#!/usr/bin/env python3
"""
MarketScanner REST API
超短量化市场扫描器的控制接口
"""
import asyncio
import logging
import math
from datetime import datetime
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException
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
    trade_mode: str = "simulated"  # simulated | gm | dry_run
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

@router.get("/status")
async def get_scanner_status():
    """获取扫描器状态(含熔断状态、交易时间、数据源)"""
    scanner = _get_scanner()
    status = scanner.get_status()
    
    # 交易时间判断
    from datetime import datetime
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
        if req.trade_mode == 'gm':
            config.setdefault("gm_token", "")
            config.setdefault("gm_strategy_id", "")
        _scanner_instance = MarketScanner(account_id=req.account_id, config=config)

    scanner = _scanner_instance
    result = await scanner.start(trade_date=req.trade_date)
    return {"success": True, "data": result}


@router.post("/stop")
async def stop_scanner():
    """停止扫描"""
    scanner = _get_scanner()
    result = await scanner.stop()
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
        if mongo_manager.db is None:
            return {"success": True, "data": []}
        
        account_id = scanner._broker.account.account_id if scanner._broker else "default"
        
        if date:
            # 指定日期
            query = {"account_id": account_id, "trade_date": date}
        else:
            # 最近N天
            from datetime import datetime, timedelta
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
    )
    
    if ok:
        scanner._timeline.append({
            "time": __import__("datetime").datetime.now().strftime("%H:%M:%S"),
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


@router.post("/scan-once")
async def scan_once(req: ScanOnceRequest = ScanOnceRequest()):
    """手动触发一次扫描
    
    Body:
        force: 强制模式, 忽略交易时间检查(消耗必盈额度, 测试用)
    """
    scanner = _get_scanner()
    from datetime import datetime
    trade_date = datetime.now().strftime("%Y%m%d")
    try:
        await scanner.scan_once(trade_date, force=req.force)
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
        
        # 按策略汇总
        strategy_summary = {}
        for pos in positions:
            key = pos.strategy or "unknown"
            if key not in strategy_summary:
                strategy_summary[key] = {"count": 0, "market_value": 0, "total_profit": 0}
            strategy_summary[key]["count"] += 1
            strategy_summary[key]["market_value"] += pos.current_price * pos.total_qty
            strategy_summary[key]["total_profit"] += (pos.current_price - pos.avg_cost) * pos.total_qty
        
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
    
    # 清除MongoDB
    try:
        if await scanner._broker._ensure_mongo():
            db = scanner._broker._mongo_db
            await db["broker_positions"].delete_many({})
            await db["broker_orders"].delete_many({})
            await db["broker_accounts"].delete_one({"account_id": scanner._broker.account.account_id})
    except Exception:
        pass
    
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
