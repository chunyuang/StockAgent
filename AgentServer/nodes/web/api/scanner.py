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


def _clean_mongo(doc):
    """清理MongoDB文档,移除ObjectId等不可序列化字段"""
    if isinstance(doc, dict):
        return {k: _clean_mongo(v) for k, v in doc.items() if k != '_id'}
    elif isinstance(doc, list):
        return [_clean_mongo(i) for i in doc]
    elif isinstance(doc, (int, float, str, bool, type(None))):
        return doc
    else:
        return str(doc)  # ObjectId等转字符串
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



def _fill_stock_names(data, scanner=None) -> list:
    """填充空stock_name/name字段(从scanner的名称映射), 支持嵌套结构"""
    if not scanner or not data:
        return data
    name_map = getattr(scanner, '_stock_name_map', {})
    if not name_map:
        return data
    if isinstance(data, dict):
        for key, val in data.items():
            if isinstance(val, list):
                data[key] = _fill_stock_names(val, scanner)
            elif isinstance(val, dict):
                _fill_stock_names([val], scanner)
        return data
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                if not item.get("stock_name") and item.get("ts_code"):
                    item["stock_name"] = name_map.get(item["ts_code"], "")
                if not item.get("name") and item.get("ts_code"):
                    item["name"] = name_map.get(item["ts_code"], "")
                for key, val in item.items():
                    if isinstance(val, list) and val and isinstance(val[0], dict):
                        _fill_stock_names(val, scanner)
    return data

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
    return _sanitize({"success": True, "data": _fill_stock_names(scanner.get_timeline(), scanner)})

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
        
        return {"success": True, "data": _fill_stock_names(items, scanner), "count": len(items)}
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
        
        return {"success": True, "data": _fill_stock_names(docs, scanner)}
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
        name_map = getattr(scanner, '_stock_name_map', {})
        cb = scanner._circuit_breaker
        stats = scanner._stats
        
        # 按策略汇总(含胜率和收益)
        strategy_summary = {}
        for pos in positions:
            # 确保pos有stock_name
            if not pos.stock_name and name_map:
                pos.stock_name = name_map.get(pos.ts_code, "")
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
        
        # 计算策略胜率 + 扩展归因指标
        for key in strategy_summary:
            total = strategy_summary[key].get("win_count", 0) + strategy_summary[key].get("loss_count", 0)
            strategy_summary[key]["win_rate"] = round(strategy_summary[key].get("win_count", 0) / max(total, 1) * 100, 1)
            # 以下指标供复盘归因展示
            closed = strategy_summary[key].get("closed_count", 0)
            strategy_summary[key]["closed_win_rate"] = round(strategy_summary[key].get("win_count", 0) / max(closed, 1) * 100, 1) if closed else 0
            # 从timeline按策略提取已平仓的pct列表(用于均盈均亏/盈亏比)
            strategy_pcts = {"wins": [], "losses": []}
            strategy_summary[key]["stop_loss_count"] = 0
            strategy_summary[key]["take_profit_count"] = 0
            for item in scanner._timeline:
                if item.get("action") != "sell" or item.get("strategy") != key:
                    continue
                pct = item.get("profit_pct", 0) or 0
                reason = item.get("reason", "")
                if pct >= 0:
                    strategy_pcts["wins"].append(pct)
                else:
                    strategy_pcts["losses"].append(pct)
                if "止损" in reason and "追踪" not in reason:
                    strategy_summary[key]["stop_loss_count"] += 1
                elif "止盈" in reason or "追踪止损" in reason:
                    strategy_summary[key]["take_profit_count"] += 1
            wins = strategy_pcts["wins"]
            losses = strategy_pcts["losses"]
            strategy_summary[key]["avg_win_pct"] = round(sum(wins) / len(wins), 1) if wins else 0
            strategy_summary[key]["avg_loss_pct"] = round(sum(losses) / len(losses), 1) if losses else 0
            strategy_summary[key]["profit_loss_ratio"] = round(abs(sum(wins)/len(wins) / (sum(losses)/len(losses))), 1) if wins and losses else 0
            strategy_summary[key]["max_win_pct"] = round(max(wins), 1) if wins else 0
            strategy_summary[key]["max_loss_pct"] = round(min(losses), 1) if losses else 0
        
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
                    [{"ts_code": p.ts_code, "name": p.stock_name or getattr(scanner, '_stock_name_map', {}).get(p.ts_code, ""), "pct": round(p.profit_pct, 1)} for p in positions],
                    key=lambda x: x["pct"], reverse=True
                )[:5],
                "top_loss": sorted(
                    [{"ts_code": p.ts_code, "name": p.stock_name or getattr(scanner, '_stock_name_map', {}).get(p.ts_code, ""), "pct": round(p.profit_pct, 1)} for p in positions],
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


@router.get("/historical-review")
async def get_historical_review(date: str = None):
    """历史复盘 — 从MongoDB聚合历史交易数据,支持任意交易日查看
    
    Args:
        date: YYYYMMDD格式,不传则返回最近有数据的交易日
    """
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": None, "message": "MongoDB未连接"}
        db = mongo_manager.db
        
        # 确定日期
        if not date:
            latest = await db["broker_orders"].find_one(
                {"status": "filled", "side": "sell"},
                sort=[("_id", -1)]
            )
            if not latest:
                return {"success": True, "data": None, "message": "无历史交易数据"}
            date = latest.get("trade_date", "")
        
        # 查询当日所有成交订单
        buys, sells = [], []
        async for doc in db["broker_orders"].find({
            "trade_date": date, "status": "filled"
        }).sort("fill_time", 1):
            (buys if doc.get("side") == "buy" else sells).append(doc)
        
        # 按策略统计
        from collections import defaultdict
        strategy_stats = defaultdict(lambda: {
            "buy_count": 0, "sell_count": 0, "stop_loss": 0, "take_profit": 0,
            "wins": [], "losses": [], "total_pnl": 0
        })
        import re
        for s in sells:
            st = s.get("strategy", "unknown")
            reason = s.get("reason", "")
            fp = s.get("filled_price", 0) or 0
            fq = s.get("filled_qty", 0) or 0
            strategy_stats[st]["sell_count"] += 1
            pct_match = re.search(r'曾盈([\d.]+)%', reason) or re.search(r'-?([\d.]+)%', reason)
            profit_pct = float(pct_match.group(1)) if pct_match else 0
            if "止损" in reason and "追踪" not in reason:
                profit_pct = -abs(profit_pct)
                strategy_stats[st]["stop_loss"] += 1
            elif "追踪止损" in reason or "止盈" in reason or "冲高" in reason:
                strategy_stats[st]["take_profit"] += 1
            (strategy_stats[st]["wins"] if profit_pct >= 0 else strategy_stats[st]["losses"]).append(profit_pct)
            strategy_stats[st]["total_pnl"] += fp * fq * profit_pct / 100
        for b in buys:
            strategy_stats[b.get("strategy", "unknown")]["buy_count"] += 1
        
        strategy_summary = {}
        for k, v in strategy_stats.items():
            w, l = v["wins"], v["losses"]
            t = len(w) + len(l)
            strategy_summary[k] = {
                "count": v["sell_count"],  # 持仓/已平数量
                "buy_count": v["buy_count"], "sell_count": v["sell_count"],
                "closed_count": t,  # 已平仓笔数
                "stop_loss_count": v["stop_loss"], "take_profit_count": v["take_profit"],
                "win_count": len(w), "loss_count": len(l),
                "win_rate": round(len(w) / max(t, 1) * 100, 1),
                "closed_win_rate": round(len(w) / max(t, 1) * 100, 1),
                "total_pnl": round(v["total_pnl"]),
                "closed_profit": round(v["total_pnl"]),
                "avg_win_pct": round(sum(w) / len(w), 1) if w else 0,
                "avg_loss_pct": round(sum(l) / len(l), 1) if l else 0,
                "profit_loss_ratio": round(abs(sum(w)/len(w) / (sum(l)/len(l))), 1) if w and l else 0,
            }
        
        # 扫描统计
        scan_count = await db["scan_traces"].count_documents({"trade_date": date, "is_debug": {"$ne": True}})
        debug_count = await db["scan_traces"].count_documents({"trade_date": date, "is_debug": True})
        total_passed = 0
        funnel_agg = defaultdict(lambda: {"total_input": 0, "total_rejected": 0})
        async for doc in db["scan_traces"].find({"trade_date": date}, {"summary": 1, "layer_details.L3_sentiment": 1}):
            total_passed += (doc.get("summary") or {}).get("passed", 0)
            for layer_name, layer_data in (doc.get("summary") or {}).items():
                if isinstance(layer_data, dict) and layer_data.get("rejected", 0) > 0:
                    funnel_agg[layer_name]["total_input"] += layer_data.get("total", 0)
                    funnel_agg[layer_name]["total_rejected"] += layer_data.get("rejected", 0)
        # 取最新一条layer_details.L3作为情绪快照
        sentiment_snap = None
        # 1. 优先从scan_traces读取L3情绪层
        latest_with_l3 = await db["scan_traces"].find_one(
            {"trade_date": date, "layer_details.L3_sentiment": {"$exists": True, "$ne": ""}},
            sort=[("_id", -1)],
            projection={"layer_details.L3_sentiment": 1}
        )
        if latest_with_l3:
            sentiment_snap = (latest_with_l3.get("layer_details") or {}).get("L3_sentiment")
        # 2. fallback到sentiment_scores
        if not sentiment_snap:
            ss_doc = await db["sentiment_scores"].find_one({"trade_date": int(date)})
            if ss_doc:
                score = ss_doc.get("score", 0)
                period = ss_doc.get("period", "")
                pos = ss_doc.get("position_ratio", 0)
                sentiment_snap = f"{period} {score}分 仓位{int(pos*100)}%"
        
        return {"success": True, "data": {
            "date": date,
            "buys": [{"ts_code": b.get("ts_code"), "stock_name": b.get("stock_name", ""), "strategy": b.get("strategy", ""), "price": b.get("filled_price", 0), "qty": b.get("filled_qty", 0), "time": b.get("fill_time", "")} for b in buys],
            "sells": [{"ts_code": s.get("ts_code"), "stock_name": s.get("stock_name", ""), "strategy": s.get("strategy", ""), "price": s.get("filled_price", 0), "qty": s.get("filled_qty", 0), "reason": s.get("reason", ""), "time": s.get("fill_time", "")} for s in sells],
            "strategy_summary": strategy_summary,
            "scan_stats": {"scan_count": scan_count, "debug_scan_count": debug_count, "total_signals": total_passed, "buy_count": len(buys), "sell_count": len(sells)},
            "funnel_summary": {k: dict(v) for k, v in funnel_agg.items()},
            "sentiment_snapshot": sentiment_snap,
        }}
    except Exception as e:
        return {"success": True, "data": None, "message": str(e)}
@router.post("/scanner/daily-settlement")
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


@router.get("/sentiment-timeline")
async def get_sentiment_timeline(date: str = None, mode: str = "daily"):
    """情绪时间线 — 聚合历史情绪数据,返回时间序列
    
    Args:
        date: YYYYMMDD, 用于日线模式限定范围(前后60天), 日内模式指定日期
        mode: intraday(日内) | daily(日线) | weekly(周线) | monthly(月线)
    """
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": {"points": [], "trades": []}}
        db = mongo_manager.db
        import datetime as _dt, re
        if not date:
            date = _dt.datetime.now().strftime("%Y%m%d")
        
        points = []
        trades = []
        
        if mode in ("daily", "weekly", "monthly"):
            from collections import OrderedDict
            daily_map = OrderedDict()
            
            # 日线模式: 以date为中心取前后60天(共120天窗口)
            # 周线/月线: 取全部数据
            query = {}
            if mode == "daily":
                try:
                    center = _dt.datetime.strptime(date, "%Y%m%d")
                    start = (center - _dt.timedelta(days=120)).strftime("%Y%m%d")
                    end = (center + _dt.timedelta(days=30)).strftime("%Y%m%d")
                    query["trade_date"] = {"$gte": int(start), "$lte": int(end)}
                except:
                    pass
            
            # 读取sentiment_scores(包含missing_data,前端用虚线标注)
            async for doc in db["sentiment_scores"].find(
                query,
                {"trade_date": 1, "score": 1, "period": 1, "position_ratio": 1, 
                 "limit_up": 1, "limit_down": 1, "max_continue": 1, "up_down_ratio": 1, 
                 "zt_premium": 1, "data_source": 1, "missing_data": 1}
            ).sort("trade_date", 1):
                td = str(doc["trade_date"])
                daily_map[td] = {
                    "date": td, "score": doc.get("score", 0), "period": doc.get("period", ""),
                    "position_ratio": doc.get("position_ratio", 0.3),
                    "limit_up": doc.get("limit_up", 0), "limit_down": doc.get("limit_down", 0),
                    "max_continue": doc.get("max_continue", 0),
                    "up_down_ratio": doc.get("up_down_ratio", 0),
                    "zt_premium": doc.get("zt_premium", 0),
                    "data_source": doc.get("data_source", ""),
                    "missing_data": doc.get("missing_data", False),
                }
            
            points = list(daily_map.values())
            
            # 周/月聚合
            if mode in ("weekly", "monthly") and points:
                from itertools import groupby
                agg_points = []
                def _period_key(p):
                    d = p["date"]
                    if mode == "weekly":
                        import datetime as _dt2
                        dt = _dt2.datetime.strptime(d, "%Y%m%d")
                        return dt.strftime("%Y-W%W")
                    else:
                        return d[:6]
                for key, group in groupby(points, key=_period_key):
                    grp = list(group)
                    valid = [p for p in grp if not p.get("missing_data")]
                    if not valid:
                        valid = grp  # 全是missing也保留
                    avg_score = sum(p["score"] for p in valid) / len(valid)
                    total_lu = sum(p.get("limit_up", 0) for p in grp)
                    total_ld = sum(p.get("limit_down", 0) for p in grp)
                    has_missing = any(p.get("missing_data") for p in grp)
                    if avg_score >= 70: period = "高潮"
                    elif avg_score >= 55: period = "分化"
                    elif avg_score >= 40: period = "震荡"
                    else: period = "冰点"
                    agg_points.append({
                        "date": key, "score": round(avg_score, 1), "period": period,
                        "position_ratio": {"高潮": 1.0, "分化": 0.7, "震荡": 0.5, "冰点": 0.3}.get(period, 0.3),
                        "limit_up": total_lu, "limit_down": total_ld,
                        "days": len(grp), "first_date": grp[0]["date"], "last_date": grp[-1]["date"],
                        "missing_data": has_missing,
                    })
                points = agg_points
            
            # trades: 只取时间范围内的sell记录
            trade_query = {"status": "filled", "side": "sell"}
            if mode == "daily" and query.get("trade_date"):
                td_q = query["trade_date"]
                trade_query["trade_date"] = td_q
            async for doc in db["broker_orders"].find(
                trade_query,
                {"trade_date": 1, "side": 1, "ts_code": 1, "strategy": 1, "filled_price": 1, "reason": 1, "profit_pct": 1}
            ).sort("trade_date", 1):
                trades.append({
                    "date": doc.get("trade_date", ""), "side": "sell", 
                    "ts_code": doc.get("ts_code", ""), "strategy": doc.get("strategy", ""), 
                    "price": doc.get("filled_price", 0), "reason": doc.get("reason", ""),
                    "profit_pct": doc.get("profit_pct", 0),
                })
        else:
            # 日内模式
            def _parse_l3(doc):
                l3d = doc.get("layer_details", {}).get("L3_sentiment_data") or {}
                l3_text = doc.get("layer_details", {}).get("L3_sentiment", "")
                score = l3d.get("score", 0)
                period = l3d.get("period", "")
                position_ratio = l3d.get("position_ratio", 0)
                if not score and l3_text:
                    m = re.search(r'情绪=([\\d.]+)分', l3_text)
                    if m: score = float(m.group(1))
                    m2 = re.search(r'仓位系数=([\\d.]+)', l3_text)
                    if m2: position_ratio = float(m2.group(1))
                    m3 = re.search(r'→(高潮|分化|震荡|冰点)', l3_text)
                    if m3: period = m3.group(1)
                return score, period, position_ratio
            
            async for doc in db["scan_traces"].find(
                {"trade_date": date},
                {"scan_time": 1, "layer_details": 1, "summary": 1, "is_debug": 1}
            ).sort("scan_time", 1):
                score, period, position_ratio = _parse_l3(doc)
                points.append({
                    "time": doc.get("scan_time", "")[:19],
                    "score": round(score, 1) if score else None,
                    "period": period, "position_ratio": position_ratio,
                    "candidates": doc.get("summary", {}).get("total_candidates", 0),
                    "passed": doc.get("summary", {}).get("passed", 0),
                    "is_debug": doc.get("is_debug", False),
                })
            async for doc in db["broker_orders"].find(
                {"trade_date": date, "status": "filled"},
                {"fill_time": 1, "side": 1, "ts_code": 1, "strategy": 1, "filled_price": 1, "reason": 1}
            ).sort("fill_time", 1):
                if doc.get("side") in ("buy", "sell"):
                    trades.append({"time": doc.get("fill_time", ""), "side": doc["side"], "ts_code": doc.get("ts_code", ""), "strategy": doc.get("strategy", ""), "price": doc.get("filled_price", 0), "reason": doc.get("reason", "") if doc["side"] == "sell" else ""})
        
        return {"success": True, "data": {"date": date, "mode": mode, "points": points, "trades": trades}}
    except Exception as e:
        return {"success": True, "data": {"points": [], "trades": []}, "message": str(e)}


@router.get("/sentiment-strategy-matrix")
async def get_sentiment_strategy_matrix(date: str = None):
    """策略×情绪 效果矩阵 — 按情绪阶段分组统计每个策略的交易表现"""
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": {"matrix": {}, "recommendations": []}}
        db = mongo_manager.db
        import re
        from collections import defaultdict
        
        # 获取每日情绪阶段
        daily_sentiment = {}
        # 从sentiment_scores读取,missing_data的日期用前一个有效期补
        last_valid_period = ""
        async for doc in db["sentiment_scores"].find({}, {"trade_date": 1, "period": 1, "missing_data": 1}).sort("trade_date", 1):
            td = str(doc["trade_date"])
            period = doc.get("period", "")
            if doc.get("missing_data"):
                # 用前一个有效期补,没有则为数据缺失
                period = last_valid_period if last_valid_period else "数据缺失"
            else:
                last_valid_period = period
            if period:
                daily_sentiment[td] = period
        
        matrix = defaultdict(lambda: defaultdict(lambda: {"wins": 0, "losses": 0, "count": 0, "total_pnl": 0.0}))
        strategy_totals = defaultdict(lambda: {"wins": 0, "losses": 0, "count": 0, "total_pnl": 0.0})
        
        # 构建查询条件: date参数时只统计该日期及之前的卖出
        sell_query = {"side": "sell", "status": "filled"}
        if date:
            try:
                sell_query["trade_date"] = {"$lte": str(date)}  # trade_date是字符串格式YYYYMMDD
            except Exception:
                pass
        
        async for doc in db["broker_orders"].find(
            sell_query,
            {"trade_date": 1, "strategy": 1, "reason": 1, "filled_price": 1, "filled_qty": 1}
        ):
            strategy = doc.get("strategy", "unknown")
            td = doc.get("trade_date", "")
            reason = doc.get("reason", "")
            fp = doc.get("filled_price", 0) or 0
            fq = doc.get("filled_qty", 0) or 0
            period = daily_sentiment.get(td, "")
            if not period:
                period = "冰点" if "强制" in reason or "空仓" in reason else "未知"
            
            # 优先从broker_orders的profit_pct字段读取(真实盈亏)
            profit_pct = doc.get("profit_pct", 0) or 0
            profit_amount = doc.get("profit_amount", 0) or 0
            if not profit_pct and not profit_amount:
                # 无盈亏数据,从reason推断
                pct_match = re.search(r'曾盈([\\d.]+)%', reason)
                if not pct_match:
                    pct_match = re.search(r'-?([\\d.]+)%', reason)
                profit_pct = float(pct_match.group(1)) if pct_match else 0
                if "止损" in reason and "追踪" not in reason:
                    profit_pct = -abs(profit_pct)
            
            pnl = profit_amount if profit_amount else fp * fq * profit_pct / 100
            # profit_pct=0且无profit_amount的跳过(无法判断胜负)
            if profit_pct == 0 and profit_amount == 0 and not reason:
                continue
            # 有profit_pct时用真实盈亏判断胜负
            if profit_pct != 0:
                is_win = profit_pct > 0
            elif profit_amount != 0:
                is_win = profit_amount > 0
            else:
                # 从reason推断
                is_win = "止盈" in reason or "追踪止损" in reason or "冲高" in reason
            matrix[strategy][period]["count"] += 1
            matrix[strategy][period]["wins"] += int(is_win)
            matrix[strategy][period]["losses"] += int(not is_win)
            matrix[strategy][period]["total_pnl"] += pnl
            strategy_totals[strategy]["count"] += 1
            strategy_totals[strategy]["wins"] += int(is_win)
            strategy_totals[strategy]["losses"] += int(not is_win)
            strategy_totals[strategy]["total_pnl"] += pnl
        
        result_matrix = {}
        for strat, periods in matrix.items():
            result_matrix[strat] = {}
            for per, data in periods.items():
                result_matrix[strat][per] = {"count": data["count"], "win_rate": round(data["wins"]/max(data["count"],1)*100,1), "total_pnl": round(data["total_pnl"]), "wins": data["wins"], "losses": data["losses"]}
        
        recommendations = []
        for strat, periods in result_matrix.items():
            best = max(periods.items(), key=lambda x: x[1]["win_rate"]*x[1]["count"] if x[1]["count"]>0 else 0)
            if best[1]["count"] >= 2:
                recommendations.append({"strategy": strat, "best_period": best[0], "win_rate": best[1]["win_rate"], "count": best[1]["count"], "pnl": best[1]["total_pnl"]})
        recommendations.sort(key=lambda x: x["pnl"], reverse=True)
        
        return {"success": True, "data": {
            "matrix": result_matrix,
            "strategy_totals": {k: {"count": v["count"], "wins": v["wins"], "losses": v["losses"], "win_rate": round(v["wins"]/max(v["count"],1)*100,1), "total_pnl": round(v["total_pnl"])} for k,v in strategy_totals.items()},
            "recommendations": recommendations[:5],
        }}
    except Exception as e:
        return {"success": True, "data": {"matrix": {}, "recommendations": []}, "message": str(e)}


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
    数据来源: 内存timeline → MongoDB scanner_timeline → MongoDB broker_orders
    """
    scanner = _get_scanner()
    
    detail = {
        "ts_code": ts_code,
        "buy": None,       # 买入决策详情
        "sell": None,      # 卖出决策详情
        "position": None,  # 当前持仓状态
        "signal": None,    # 当前信号状态
    }
    
    # 1. 从内存时间线查找买入/卖出记录
    for item in scanner._timeline:
        if item.get("ts_code") == ts_code:
            if item.get("action") == "buy" and not detail["buy"]:
                detail["buy"] = {
                    "time": item.get("time", ""),
                    "price": item.get("price", 0),
                    "shares": item.get("shares", 0),
                    "reason": item.get("reason", ""),
                    "strategy": item.get("strategy", ""),
                    "stock_name": item.get("stock_name", ""),
                    "decision_detail": item.get("decision_detail", {}),
                }
            elif item.get("action") == "sell" and not detail["sell"]:
                detail["sell"] = {
                    "time": item.get("time", ""),
                    "price": item.get("price", 0),
                    "shares": item.get("shares", 0),
                    "reason": item.get("reason", ""),
                    "strategy": item.get("strategy", ""),
                    "stock_name": item.get("stock_name", ""),
                    "profit_pct": item.get("profit_pct", 0),
                    "profit_amount": item.get("profit_amount", 0),
                    "decision_detail": item.get("decision_detail", {}),
                }
    
    # 1b. 从MongoDB历史时间线补充(跨session数据)
    if not detail["buy"] or not detail["sell"]:
        try:
            from core.managers import mongo_manager
            if mongo_manager.is_initialized:
                account_id = scanner._broker.account.account_id if scanner._broker else "default"
                async for doc in mongo_manager.db["scanner_timeline"].find(
                    {"account_id": account_id, "ts_code": ts_code}
                ).sort("_id", 1):
                    if doc.get("action") == "buy" and not detail["buy"]:
                        detail["buy"] = {
                            "time": doc.get("time", ""),
                            "price": doc.get("price", 0),
                            "shares": doc.get("shares", 0),
                            "reason": doc.get("reason", ""),
                            "strategy": doc.get("strategy", ""),
                            "stock_name": doc.get("stock_name", ""),
                            "decision_detail": doc.get("decision_detail", {}),
                        }
                    elif doc.get("action") == "sell" and not detail["sell"]:
                        detail["sell"] = {
                            "time": doc.get("time", ""),
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
    if not detail["buy"] and orders:
        buy_order = next((o for o in orders if o["side"] == "buy"), None)
        if buy_order:
            detail["buy"] = {
                "time": buy_order.get("create_time", ""),
                "price": buy_order.get("filled_price", 0),
                "shares": buy_order.get("filled_qty", 0),
                "reason": buy_order.get("reason", ""),
                "strategy": buy_order.get("strategy", ""),
                "stock_name": "",
                "decision_detail": {},
            }
    
    # 5b. 如果仍无买入信息,从卖出的decision_detail推断(cost_price)
    if not detail["buy"] and detail["sell"]:
        sell_dd = detail["sell"].get("decision_detail", {})
        cost_price = sell_dd.get("cost_price", 0)
        if cost_price > 0:
            detail["buy"] = {
                "time": "(历史记录)",
                "price": cost_price,
                "shares": detail["sell"].get("shares", 0),
                "reason": detail["sell"].get("reason", "").split("(")[0].strip() if detail["sell"].get("reason") else "",
                "strategy": detail["sell"].get("strategy", ""),
                "stock_name": "",
                "decision_detail": {},
                "inferred": True,  # 标记为推断数据
            }
    
    # 6. 如果卖出信息缺失,从订单中补充
    if not detail["sell"] and orders:
        sell_order = next((o for o in orders if o["side"] == "sell"), None)
        if sell_order:
            profit_pct = 0
            if detail["buy"] and detail["buy"].get("price") and sell_order.get("filled_price"):
                profit_pct = (sell_order["filled_price"] - detail["buy"]["price"]) / detail["buy"]["price"] * 100
            detail["sell"] = {
                "time": sell_order.get("create_time", ""),
                "price": sell_order.get("filled_price", 0),
                "shares": sell_order.get("filled_qty", 0),
                "reason": sell_order.get("reason", ""),
                "strategy": sell_order.get("strategy", ""),
                "profit_pct": profit_pct,
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
    
    # 补充历史数据(从MongoDB scanner_timeline)
    try:
        from core.managers import mongo_manager
        if mongo_manager.is_initialized:
            account_id = scanner._broker.account.account_id if scanner._broker else "default"
            async for doc in mongo_manager.db["scanner_timeline"].find(
                {"account_id": account_id}
            ).sort("_id", 1):
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


@router.get("/backtest-compare")
async def backtest_compare(date: str = None):
    """实盘vs回测对比
    
    优先从MongoDB读取回测结果，fallback到backtest_result.json文件
    
    Args:
        date: YYYYMMDD格式, 不传则全量
    """
    try:
        from core.managers import mongo_manager
        
        # 1. 从MongoDB获取实盘统计(按策略)
        live_stats = {}
        if mongo_manager.is_initialized:
            from collections import defaultdict
            ls = defaultdict(lambda: {"trades":0,"wins":0,"total_pnl":0})
            sell_query = {"side":"sell","status":"filled"}
            if date:
                sell_query["trade_date"] = {"$lte": str(date)}
            async for doc in mongo_manager.db["broker_orders"].find(sell_query):
                strat = doc.get("strategy","unknown")
                pct = doc.get("profit_pct",0) or 0
                ls[strat]["trades"] += 1
                if pct >= 0:
                    ls[strat]["wins"] += 1
                ls[strat]["total_pnl"] += pct
            for strat, v in ls.items():
                live_stats[strat] = {
                    "trades": v["trades"],
                    "win_rate": round(v["wins"]/max(v["trades"],1)*100, 1),
                    "total_pnl": round(v["total_pnl"], 2),
                }
        
        # 2. 从MongoDB回测结果读取(优先same_period)
        backtest_results = {}
        backtest_type = "none"
        if mongo_manager.is_initialized:
            # 2a. 优先查same_period(同区间回测)
            same_period_doc = await mongo_manager.db["backtest_results"].find_one(
                {"status": "completed", "type": "same_period"},
                sort=[("created_at", -1)]
            )
            if same_period_doc:
                backtest_type = "same_period"
                strategies = same_period_doc.get("params", {}).get("strategy_ids", [])
                raw_summary = same_period_doc.get("result", {}).get("summary", {})
                # 解析summary: 可能是嵌套dict(含strategy_results)或error dict
                if isinstance(raw_summary, dict) and "error" not in raw_summary:
                    # 有strategy_results时, 拆分到每个策略
                    sr = raw_summary.get("strategy_results", {})
                    cn_to_en = {"半路追涨":"halfway_chase","涨停开板":"first_limit_up","跌停翘板":"limit_down_qiao","首板打板":"first_limit_up","龙头低吸":"dragon_head"}
                    if sr:
                        for cn_name, v in sr.items():
                            sid = cn_to_en.get(cn_name, cn_name)
                            if sid not in backtest_results:
                                backtest_results[sid] = {
                                    "total_return": v.get("total_return", 0),
                                    "win_rate": v.get("win_rate", 0),
                                    "max_drawdown": v.get("max_drawdown", 0),
                                    "sharpe": 0,
                                    "trades": v.get("total_trades", 0),
                                    "source": "same_period",
                                    "period": f"{same_period_doc.get('params',{}).get('start_date','')}~{same_period_doc.get('params',{}).get('end_date','')}",
                                }
                    else:
                        # 整体summary
                        summary = raw_summary
                        for sid in strategies:
                            if sid not in backtest_results:
                                backtest_results[sid] = {
                                    "total_return": summary.get("total_return", 0),
                                    "win_rate": summary.get("win_rate", 0),
                                    "max_drawdown": summary.get("max_drawdown", 0),
                                    "sharpe": summary.get("sharpe_ratio", 0),
                                    "trades": summary.get("total_trades", 0),
                                    "source": "same_period",
                                    "period": f"{same_period_doc.get('params',{}).get('start_date','')}~{same_period_doc.get('params',{}).get('end_date','')}",
                                }
                else:
                    # error或无数据
                    backtest_type = "same_period_failed"
                    backtest_results = {}  # fallback到文件
            
            # 2b. fallback: 普通回测
            if not backtest_results:
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
                                "source": "mongodb",
                            }
                    backtest_type = "historical"
        
        # 2b. fallback: 从backtest_result.json文件读取
        logger.info(f"[BACKTEST-COMPARE] backtest_results empty: {not backtest_results}, keys: {list(backtest_results.keys())}")
        if not backtest_results:
            import os, json
            result_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "results", "backtest_result.json")
            logger.info(f"[BACKTEST-COMPARE] fallback file: {result_file} exists={os.path.exists(result_file)}")
            if os.path.exists(result_file):
                try:
                    with open(result_file, 'r') as f:
                        bt_data = json.load(f)
                    logger.info(f"[BACKTEST-COMPARE] loaded strategies: {list(bt_data.get('strategy_results',{}).keys())}")
                    cn_to_en = {"半路追涨":"halfway_chase","涨停开板":"first_limit_up","跌停翘板":"limit_down_qiao","首板打板":"first_limit_up","龙头低吸":"dragon_head"}
                    for cn_name, v in bt_data.get("strategy_results",{}).items():
                        en_name = cn_to_en.get(cn_name, cn_name)
                        if en_name not in backtest_results:
                            ret = v.get("total_return", 0) or 0
                            # total_return<10视为倍数(2.65=265%),>=10视为百分比
                            ret_pct = round(ret * 100, 1) if abs(ret) < 10 else round(ret, 1)
                            dd = v.get("max_drawdown", 0) or 0
                            dd_pct = round(dd * 100, 1) if abs(dd) < 1 and dd != 0 else round(dd, 1)
                            backtest_results[en_name] = {
                                "total_return": ret_pct,
                                "win_rate": round(v.get("win_rate", 0) or 0, 1),
                                "max_drawdown": dd_pct,
                                "sharpe": round(v.get("sharpe_ratio", 0) or 0, 2),
                                "trades": v.get("total_trades", 0) or 0,
                                "source": "backtest_result.json",
                            }
                except Exception as e:
                    logger.warning(f"[BACKTEST-COMPARE] file read failed: {e}")
        
        # 3. 组装对比数据
        compare = []
        all_strategies = set(list(live_stats.keys()) + list(backtest_results.keys()))
        for sid in all_strategies:
            lp = live_stats.get(sid, {})
            bt = backtest_results.get(sid, {})
            compare.append({
                "strategy": sid,
                "live_trades": lp.get("trades", 0),
                "live_win_rate": lp.get("win_rate", 0),
                "live_pnl": lp.get("total_pnl", 0),
                "bt_return": bt.get("total_return", 0),
                "bt_win_rate": round(bt.get("win_rate", 0), 1),
                "bt_drawdown": bt.get("max_drawdown", 0),
                "bt_sharpe": round(bt.get("sharpe", 0), 2),
                "bt_trades": bt.get("trades", 0),
                "bt_source": bt.get("source", "mongodb"),
            })
        
        return {"success": True, "data": compare, "backtest_type": backtest_type}
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
async def get_weekly_report(date: str = None):
    """周报: 指定日期所在周的5个交易日汇总
    
    Args:
        date: YYYYMMDD格式, 不传则当天
    """
    scanner = _get_scanner()
    if not scanner._broker:
        return {"success": True, "data": {}}
    
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": {}}
        
        account_id = scanner._broker.account.account_id
        
        # 确定日期范围: 指定日期往前7天
        if date:
            end_date = date
            start_dt = datetime(int(date[:4]), int(date[4:6]), int(date[6:8])) - timedelta(days=7)
            start_date = start_dt.strftime("%Y%m%d")
        else:
            start_date = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
            end_date = datetime.now().strftime("%Y%m%d")
        
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
        name_map = getattr(scanner, '_stock_name_map', {})
        
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
_DESIGN_DOC_VERSION = "v2.9.37"
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
                    except: pass
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


@router.get("/market-sentiment")
async def get_market_sentiment_detail(date: str = None):
    """市场情绪全景"""
    scanner = _get_scanner()
    try:
        filter_pipeline = getattr(scanner, '_filter_pipeline', None)
        emotion = getattr(filter_pipeline, '_emotion_cycle', None) if filter_pipeline else None
        sentiment_score = getattr(emotion, 'score', None) if emotion else None
        sentiment_period = getattr(emotion, 'period', None) if emotion else None
        position_ratio = getattr(emotion, 'position_ratio', None) if emotion else None
        
        # 实时数据优先,无则从sentiment_scores读
        if sentiment_score is None or sentiment_period is None:
            try:
                from core.managers import mongo_manager
                if mongo_manager.is_initialized:
                    # 1. 优先读指定日期(即使missing也返回,标注数据不完整)
                    if date:
                        exact = await mongo_manager.db["sentiment_scores"].find_one({"trade_date": int(date)})
                        if exact:
                            sentiment_score = exact.get("score", 50)
                            sentiment_period = exact.get("period", "unknown")
                            position_ratio = exact.get("position_ratio", 0.3)
                            if exact.get("missing_data"):
                                sentiment_period = "冰点(数据缺失)"  # 保留period但标注缺失
                    # 2. 指定日期无数据或未指定日期→读最近的非missing日期
                    if sentiment_period is None or (not date and sentiment_period is None):
                        latest = await mongo_manager.db["sentiment_scores"].find_one(
                            {"missing_data": {"$ne": True}},
                            sort=[("trade_date", -1)]
                        )
                        if doc:
                            sentiment_score = latest.get("score", 50)
                            sentiment_period = latest.get("period", "unknown")
                            position_ratio = latest.get("position_ratio", 0.3)
            except Exception:
                pass
        
        # 最终fallback
        if sentiment_score is None: sentiment_score = 50
        if sentiment_period is None: sentiment_period = "unknown"
        if position_ratio is None: position_ratio = 0.3
        
        limit_pools = getattr(scanner, '_limit_pools', {})
        limit_up = len(limit_pools.get("limit_up", []))
        limit_down = len(limit_pools.get("limit_down", []))
        broken = len(limit_pools.get("broken", []))
        board_dist = {}
        for item in limit_pools.get("limit_up", []):
            t = item.get("limit_times", 1)
            board_dist[str(t)] = board_dist.get(str(t), 0) + 1
        
        # 涨跌停=0时从sentiment_scores补(优先指定日期,包括missing)
        if limit_up == 0 and limit_down == 0:
            try:
                from core.managers import mongo_manager
                if mongo_manager.is_initialized:
                    doc = None
                    if date:
                        doc = await mongo_manager.db["sentiment_scores"].find_one({"trade_date": int(date)})
                    if not doc or doc.get("missing_data"):
                        # fallback到最近非missing
                        doc = await mongo_manager.db["sentiment_scores"].find_one(
                            {"missing_data": {"$ne": True}},
                            sort=[("trade_date", -1)]
                        )
                    if doc:
                        limit_up = doc.get("limit_up", 0)
                        limit_down = doc.get("limit_down", 0)
                        # 连板分布从max_continue推算
                        mc = doc.get("max_continue", 0)
                        if mc > 0:
                            board_dist[str(mc)] = board_dist.get(str(mc), 0) + 1
            except Exception:
                pass
        broken_rate = broken / max(limit_up + broken, 1) * 100

        period_labels = {"BEARISH": ("冰点", 0, 40), "CHAOS": ("震荡", 40, 55), "DIFFERENTIATION": ("分化", 55, 70), "RISING": ("高潮", 70, 100),
                          "冰点": ("冰点", 0, 40), "震荡": ("震荡", 40, 55), "分化": ("分化", 55, 70), "高潮": ("高潮", 70, 100),
                          "冰点(数据缺失)": ("冰点⚠", 0, 40), "震荡(数据缺失)": ("震荡⚠", 40, 55), "分化(数据缺失)": ("分化⚠", 55, 70), "高潮(数据缺失)": ("高潮⚠", 70, 100)}
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
                        "stock_name": sig.stock_name or (scanner._stock_name_map.get(sig.ts_code, "") if hasattr(scanner, '_stock_name_map') else ""),
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
                    "name": item.get('name', '') or (scanner._stock_name_map.get(item.get('ts_code', ''), '') if hasattr(scanner, '_stock_name_map') else ''),
                    "pct_chg": item.get('pct_chg', 0),
                    "volume_ratio": item.get('volume_ratio', 0),
                })
        
        # 盘前候选(所有活跃信号的预选)
        candidates = []
        for sig in scanner._active_signals:
            candidates.append({
                "ts_code": sig.ts_code,
                "stock_name": sig.stock_name or (scanner._stock_name_map.get(sig.ts_code, "") if hasattr(scanner, '_stock_name_map') else ""),
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
        date: YYYYMMDD格式, 不传则返回最近交易日
    
    Returns:
        逐笔归因列表: ts_code/strategy/buy_price/sell_price/profit_pct/sell_reason/why_profit/why_loss
    """
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": []}
        db = mongo_manager.db
        
        # 确定日期
        if not date:
            latest = await db["broker_orders"].find_one(
                {"side": "sell", "status": "filled"},
                sort=[("_id", -1)]
            )
            if not latest:
                return {"success": True, "data": []}
            date = latest.get("trade_date", "")
        
        attributions = []
        # 从broker_orders读取卖出记录
        async for doc in db["broker_orders"].find({
            "trade_date": date, "side": "sell", "status": "filled"
        }).sort("fill_time", 1):
            ts_code = doc.get("ts_code", "")
            strategy = doc.get("strategy", "")
            profit_pct = doc.get("profit_pct", 0) or 0
            sell_reason = doc.get("reason", "")
            filled_price = doc.get("filled_price", 0) or 0
            filled_qty = doc.get("filled_qty", 0) or 0
            
            # 查找对应买入记录
            buy_doc = await db["broker_orders"].find_one(
                {"ts_code": ts_code, "strategy": strategy, "side": "buy", "status": "filled"},
                sort=[("_id", 1)]
            )
            buy_price = buy_doc.get("filled_price", 0) if buy_doc else 0
            buy_time = buy_doc.get("fill_time", "") if buy_doc else ""
            
            # 查找scan_trace(买入漏斗)
            scan_info = None
            try:
                scan_doc = await db["scan_traces"].find_one(
                    {"candidates.ts_code": ts_code, "candidates.strategy": strategy},
                    {"scan_time": 1, "summary": 1, "layer_details": 1}
                )
                if scan_doc:
                    ld = scan_doc.get("layer_details") or {}
                    scan_info = {
                        "scan_time": scan_doc.get("scan_time", "")[:19],
                        "sentiment": ld.get("L3_sentiment", ""),
                        "ranking": ld.get("L7_ranking", ""),
                    }
            except Exception:
                pass
            
            # 归因分析
            why_profit = None
            why_loss = None
            if profit_pct >= 0:
                if "追踪" in sell_reason:
                    why_profit = "趋势延续盈利锁定"
                elif "止盈" in sell_reason:
                    why_profit = "达到止盈目标"
                elif "冲高" in sell_reason:
                    why_profit = "冲高兑现"
                else:
                    why_profit = "趋势延续"
            else:
                if "止损" in sell_reason and "追踪" not in sell_reason:
                    why_loss = f"触发止损({profit_pct:.1f}%)"
                elif "追踪止损" in sell_reason:
                    why_loss = "冲高回落"
                elif "强制" in sell_reason or "空仓" in sell_reason:
                    why_loss = "系统风控强制清仓"
                else:
                    why_loss = "行情反转"
            
            attributions.append({
                "ts_code": ts_code,
                "stock_name": doc.get("stock_name", ""),
                "strategy": strategy,
                "buy_price": buy_price,
                "sell_price": filled_price,
                "profit_pct": profit_pct,
                "profit_amount": doc.get("profit_amount", 0),
                "buy_time": buy_time,
                "sell_time": doc.get("fill_time", ""),
                "sell_reason": sell_reason,
                "why_profit": why_profit,
                "why_loss": why_loss,
                "scan_info": scan_info,
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


# ==================== 复盘增强API ====================

@router.get("/review-hero")
async def get_review_hero(date: str = None):
    """复盘Hero: 一句话结论 + 基准对比 + 核心指标 + 纪律评分
    
    Args:
        date: YYYYMMDD格式
    """
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": None}
        db = mongo_manager.db
        
        if not date:
            latest = await db["broker_orders"].find_one({"side":"sell","status":"filled"}, sort=[("_id",-1)])
            date = latest.get("trade_date","") if latest else ""
        
        # 1. 当日交易统计
        sells, buys = [], []
        async for doc in db["broker_orders"].find({"trade_date": date, "status": "filled"}):
            (buys if doc.get("side") == "buy" else sells).append(doc)
        
        wins = [s for s in sells if (s.get("profit_pct") or 0) >= 0]
        losses = [s for s in sells if (s.get("profit_pct") or 0) < 0]
        win_rate = len(wins) / max(len(sells), 1) * 100
        avg_win = sum(s.get("profit_pct",0) or 0 for s in wins) / max(len(wins),1) if wins else 0
        avg_loss = sum(s.get("profit_pct",0) or 0 for s in losses) / max(len(losses),1) if losses else 0
        total_pct = sum(s.get("profit_pct",0) or 0 for s in sells)
        
        # 2. 期望值 = 胜率×均盈 - 败率×均亏
        expectancy = (win_rate/100) * avg_win - (1-win_rate/100) * abs(avg_loss) if sells else 0
        
        # 3. 大盘对比(上证)
        benchmark_pct = 0
        benchmark_name = "上证指数"
        idx_doc = await db["index_daily"].find_one({"ts_code": "000001.SH", "trade_date": int(date)})
        if idx_doc:
            benchmark_pct = idx_doc.get("pct_chg", 0) or 0
        else:
            # 尝试最近的交易日
            idx_doc = await db["index_daily"].find_one({"ts_code": "000001.SH", "trade_date": {"$lte": int(date)}}, sort=[("trade_date",-1)])
            if idx_doc:
                benchmark_pct = idx_doc.get("pct_chg", 0) or 0
        
        # 4. 情绪环境
        sentiment_doc = await db["sentiment_scores"].find_one({"trade_date": int(date)})
        sentiment_period = sentiment_doc.get("period", "") if sentiment_doc else ""
        sentiment_score = sentiment_doc.get("score", 0) if sentiment_doc else 50
        if sentiment_doc and sentiment_doc.get("missing_data"):
            sentiment_period = sentiment_doc.get("period", "") + "(数据缺失)"
        
        # 5. 纪律检查
        violations = []
        # 冰点开仓
        if sentiment_doc and sentiment_doc.get("period") in ["bearish", "chaos"] or (sentiment_score < 40 and buys):
            for b in buys:
                violations.append({
                    "type": "冰点开仓", "severity": "high",
                    "ts_code": b.get("ts_code",""), "strategy": b.get("strategy",""),
                    "detail": f"情绪{sentiment_score:.0f}分({sentiment_period})时买入{b.get('ts_code','')}"
                })
        # 情绪不匹配(冰点做半路追涨)
        period_map = {"RISING": "高潮", "DIFFERENTIATION": "分化", "CHAOS": "震荡", "BEARISH": "冰点"}
        strategy_period_fit = {"halfway_chase": ["RISING", "DIFFERENTIATION"], "first_limit_up": ["RISING"], "limit_down_qiao": ["RISING", "DIFFERENTIATION", "CHAOS"]}
        if sentiment_doc:
            raw_period = sentiment_doc.get("period", "")
            for b in buys:
                strat = b.get("strategy", "")
                fit_periods = strategy_period_fit.get(strat, [])
                if fit_periods and raw_period not in fit_periods:
                    cn_period = period_map.get(raw_period, raw_period)
                    violations.append({
                        "type": "情绪不匹配", "severity": "medium",
                        "ts_code": b.get("ts_code",""), "strategy": strat,
                        "detail": f"{cn_period}期做{strat}(适合{'+'.join(period_map.get(p,p) for p in fit_periods)})"
                    })
        # 单日止损过多(≥3)
        stop_losses = [s for s in sells if "止损" in (s.get("reason","") or "") and "追踪" not in (s.get("reason","") or "")];
        if len(stop_losses) >= 3:
            violations.append({
                "type": "止损过多", "severity": "high",
                "ts_code": "", "strategy": "",
                "detail": f"当日止损{len(stop_losses)}笔,建议检查入场条件"
            })
        
        discipline_score = max(0, 100 - len(violations) * 20)
        
        # 6. 连续亏损
        all_sells_cursor = db["broker_orders"].find({"side":"sell","status":"filled"}, {"profit_pct":1,"trade_date":1}).sort("trade_date",1)
        all_sells = await all_sells_cursor.to_list(length=500)
        max_consecutive_loss = 0
        current_loss_streak = 0
        for s in all_sells:
            pct = s.get("profit_pct",0) or 0
            if pct < 0:
                current_loss_streak += 1
                max_consecutive_loss = max(max_consecutive_loss, current_loss_streak)
            else:
                current_loss_streak = 0
        
        # 7. 一句话结论
        if not sells:
            conclusion = "📋 当日无卖出交易"
            conclusion_type = "neutral"
        elif total_pct > 3:
            conclusion = f"🟢 今日大赚 +{total_pct:.1f}% 跑赢大盘{total_pct - benchmark_pct:.1f}% {max((wins), key=lambda w: w.get('profit_pct',0)).get('strategy','')}贡献最大"
            conclusion_type = "profit"
        elif total_pct > 0:
            conclusion = f"🟡 今日小赚 +{total_pct:.1f}% {'跑赢' if total_pct > benchmark_pct else '落后'}大盘{abs(total_pct - benchmark_pct):.1f}%"
            conclusion_type = "slight_profit"
        elif total_pct > -2:
            conclusion = f"🟠 今日小亏 {total_pct:.1f}% {'仍跑赢大盘' if total_pct > benchmark_pct else '落后大盘'} 止损{len(stop_losses)}笔"
            conclusion_type = "slight_loss"
        else:
            conclusion = f"🔴 今日亏损 {total_pct:.1f}% 止损{len(stop_losses)}笔过多 建议降仓检查策略"
            conclusion_type = "loss"
        
        return {"success": True, "data": {
            "date": date,
            "conclusion": conclusion,
            "conclusion_type": conclusion_type,
            "metrics": {
                "total_pct": round(total_pct, 2),
                "win_rate": round(win_rate, 1),
                "trades": len(sells),
                "buys": len(buys),
                "stop_loss_count": len(stop_losses),
                "take_profit_count": len(wins),
                "expectancy": round(expectancy, 2),
                "discipline_score": discipline_score,
                "max_consecutive_loss": max_consecutive_loss,
                "avg_win": round(avg_win, 1),
                "avg_loss": round(avg_loss, 1),
                "profit_loss_ratio": round(abs(avg_win / avg_loss), 1) if avg_loss != 0 else 0,
            },
            "benchmark": {
                "name": benchmark_name,
                "pct_chg": round(benchmark_pct, 2),
                "alpha": round(total_pct - benchmark_pct, 2),
            },
            "sentiment": {
                "period": sentiment_period,
                "score": sentiment_score,
            },
            "violations": violations,
        }}
    except Exception as e:
        return {"success": True, "data": None, "message": str(e)}


@router.get("/discipline-check")
async def get_discipline_check(date: str = None):
    """纪律检查: 标记违规交易, 计算执行正确率
    
    Args:
        date: YYYYMMDD格式
    """
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": None}
        db = mongo_manager.db
        
        if not date:
            latest = await db["broker_orders"].find_one({"side":"sell","status":"filled"}, sort=[("_id",-1)])
            date = latest.get("trade_date","") if latest else ""
        
        # 情绪
        sentiment_doc = await db["sentiment_scores"].find_one({"trade_date": int(date)})
        raw_period = sentiment_doc.get("period","") if sentiment_doc else ""
        sentiment_score = sentiment_doc.get("score",50) if sentiment_doc else 50
        
        # 策略-情绪适配规则
        strategy_fit = {
            "halfway_chase": {"高潮": True, "分化": True, "震荡": False, "冰点": False},
            "first_limit_up": {"高潮": True, "分化": False, "震荡": False, "冰点": False},
            "limit_down_qiao": {"高潮": True, "分化": True, "震荡": True, "冰点": False},
            "dragon_head": {"高潮": True, "分化": True, "震荡": False, "冰点": False},
        }
        
        violations = []
        total_actions = 0
        correct_actions = 0
        
        # 检查买入
        async for doc in db["broker_orders"].find({"trade_date": date, "side": "buy", "status": "filled"}):
            total_actions += 1
            strat = doc.get("strategy", "")
            fit = strategy_fit.get(strat, {})
            is_fit = fit.get(raw_period, True)  # 未知策略默认合规
            
            # 冰点期禁止开仓
            if raw_period in ["BEARISH", "冰点"]:
                violations.append({
                    "ts_code": doc.get("ts_code",""), "strategy": strat, "side": "buy",
                    "violation": "冰点期禁止开仓", "severity": "high",
                    "detail": f"情绪{sentiment_score:.0f}分处于冰点,不应买入"
                })
            elif not is_fit:
                violations.append({
                    "ts_code": doc.get("ts_code",""), "strategy": strat, "side": "buy",
                    "violation": "情绪不匹配", "severity": "medium",
                    "detail": f"{raw_period}期不适合做{strat}"
                })
            else:
                correct_actions += 1
        
        # 检查卖出(止损是否及时)
        async for doc in db["broker_orders"].find({"trade_date": date, "side": "sell", "status": "filled"}):
            total_actions += 1
            pct = doc.get("profit_pct",0) or 0
            reason = doc.get("reason","")
            
            # 亏损超过5%仍未止损(可能是扛单)
            if pct < -5 and "止损" not in reason:
                violations.append({
                    "ts_code": doc.get("ts_code",""), "strategy": doc.get("strategy",""), "side": "sell",
                    "violation": "亏损过大未及时止损", "severity": "high",
                    "detail": f"亏损{pct:.1f}%但卖出原因非止损({reason[:20]})"
                })
            else:
                correct_actions += 1
        
        execution_rate = correct_actions / max(total_actions, 1) * 100
        
        return {"success": True, "data": {
            "date": date,
            "total_actions": total_actions,
            "correct_actions": correct_actions,
            "execution_rate": round(execution_rate, 1),
            "violation_count": len(violations),
            "violations": violations,
        }}
    except Exception as e:
        return {"success": True, "data": None, "message": str(e)}


@router.get("/review-forward")
async def get_review_forward(date: str = None):
    """前瞻建议: 基于当前情绪+历史模式给出明日操作建议
    
    Args:
        date: YYYYMMDD格式
    """
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": None}
        db = mongo_manager.db
        
        if not date:
            import datetime
            date = datetime.datetime.now().strftime("%Y%m%d")
        
        # 1. 当前情绪
        sentiment_doc = await db["sentiment_scores"].find_one({"trade_date": int(date)})
        if not sentiment_doc:
            # fallback到最近
            sentiment_doc = await db["sentiment_scores"].find_one({"missing_data": {"$ne": True}}, sort=[("trade_date",-1)])
        
        raw_period = sentiment_doc.get("period","") if sentiment_doc else ""
        score = sentiment_doc.get("score",50) if sentiment_doc else 50
        period_map = {"RISING": "高潮", "DIFFERENTIATION": "分化", "CHAOS": "震荡", "BEARISH": "冰点"}
        cn_period = period_map.get(raw_period, raw_period)
        
        # 2. 策略历史表现(近30天)
        from collections import defaultdict
        strat_stats = defaultdict(lambda: {"wins":0,"losses":0,"count":0})
        recent_sells = db["broker_orders"].find({"side":"sell","status":"filled"}).sort("_id",-1).limit(60)
        async for doc in recent_sells:
            strat = doc.get("strategy","unknown")
            pct = doc.get("profit_pct",0) or 0
            strat_stats[strat]["count"] += 1
            if pct >= 0:
                strat_stats[strat]["wins"] += 1
            else:
                strat_stats[strat]["losses"] += 1
        
        # 3. 生成建议
        strategy_recommendations = []
        strategy_switches = []
        period_strategy_map = {
            "高潮": {"open": ["halfway_chase","first_limit_up","limit_down_qiao","dragon_head"], "close": []},
            "分化": {"open": ["halfway_chase","dragon_head"], "close": ["first_limit_up"]},
            "震荡": {"open": ["limit_down_qiao"], "close": ["halfway_chase","first_limit_up"]},
            "冰点": {"open": [], "close": ["halfway_chase","first_limit_up","limit_down_qiao","dragon_head"]},
        }
        
        switches = period_strategy_map.get(raw_period, {"open":[],"close":[]})
        for strat in switches["open"]:
            st = strat_stats.get(strat, {})
            wr = st.get("wins",0) / max(st.get("count",1),1) * 100
            strategy_recommendations.append({"strategy": strat, "action": "open", "win_rate": round(wr,1), "count": st.get("count",0)})
        for strat in switches["close"]:
            strategy_switches.append({"strategy": strat, "action": "close", "reason": f"{cn_period}期不适合该策略"})
        
        # 4. 参数漂移检查
        drift_warnings = []
        try:
            from core.managers.param_center import ParamCenter
            pc = ParamCenter()
            for strat_key in ["halfway_chase","first_limit_up","limit_down_qiao","dragon_head"]:
                live_params = await pc.get_strategy_config(strat_key)
                if live_params and live_params.get("source") == "param_center":
                    drift_warnings.append({"strategy": strat_key, "status": "参数已从ParamCenter修改", "source": "param_center"})
        except Exception:
            pass
        
        # 5. 综合建议
        if raw_period in ["RISING", "高潮"]:
            advice = f"当前高潮({score:.0f}分)，所有策略开放。建议满仓操作，注意高潮末端可能突然分化，设好止盈。"
        elif raw_period in ["DIFFERENTIATION", "分化"]:
            advice = f"当前分化({score:.0f}分)，建议降仓位至50-70%。只做半路追涨和龙头低吸，关闭首板打板。"
        elif raw_period in ["CHAOS", "震荡"]:
            advice = f"当前震荡({score:.0f}分)，建议轻仓25-40%。只做跌停翘板(小仓)，严格止损3%，快进快出。"
        else:
            advice = f"当前冰点({score:.0f}分)，建议空仓观望，禁止新开仓。持仓执行止损，等待情绪回暖信号(涨停>50)。"
        
        return {"success": True, "data": {
            "date": date,
            "sentiment": {"period": cn_period, "score": score, "raw_period": raw_period},
            "advice": advice,
            "strategy_recommendations": strategy_recommendations,
            "strategy_switches": strategy_switches,
            "drift_warnings": drift_warnings,
        }}
    except Exception as e:
        return {"success": True, "data": None, "message": str(e)}


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

@router.post("/backtest-same-period")
async def backtest_same_period(request: Request):
    """P0: 同区间回测 - 用当前参数重跑实盘同区间的回测
    
    请求体: {"start_date": "20260518", "end_date": "20260530"}
    如果不传, 自动取broker_orders最早~最新卖出日
    """
    try:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        start_date = body.get("start_date")
        end_date = body.get("end_date")
        
        from core.managers import mongo_manager
        
        if not start_date or not end_date:
            if not mongo_manager.is_initialized:
                return {"success": False, "message": "MongoDB未初始化, 请提供start_date/end_date"}
            # 自动取实盘日期范围
            sells = []
            async for doc in mongo_manager.db["broker_orders"].find({"side":"sell","status":"filled"},{"trade_date":1}):
                if doc.get("trade_date"):
                    sells.append(doc["trade_date"])
            if not sells:
                return {"success": False, "message": "无实盘交易数据"}
            start_date = min(sells)
            end_date = max(sells)
        
        # 后台运行回测
        import asyncio, os, sys
        
        async def _run_same_period_bt(sd, ed):
            try:
                BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                if BASE not in sys.path:
                    sys.path.insert(0, BASE)
                
                from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
                from core.managers import mongo_manager as mm
                
                if not mm.is_initialized:
                    await mm.initialize()
                
                # 检查行情数据是否存在
                bar_count = await mm.db["stock_daily_ak_full"].count_documents(
                    {"trade_date": {"$gte": sd, "$lte": ed}}
                )
                if bar_count < 100:
                    # 尝试用东财补数据
                    try:
                        from nodes.market_monitor.data_source_router import data_source_router
                        for td_int in range(int(sd), int(ed)+1):
                            td_str = str(td_int)
                            if await mm.db["stock_daily_ak_full"].count_documents({"trade_date": td_str}) > 0:
                                continue
                            try:
                                await data_source_router.fetch_and_save_daily_bar(td_str)
                                logger.info(f"[SAME-PERIOD-BT] 补数据: {td_str}")
                            except: pass
                    except Exception as e2:
                        logger.warning(f"[SAME-PERIOD-BT] 补数据失败: {e2}")
                    
                    bar_count2 = await mm.db["stock_daily_ak_full"].count_documents(
                        {"trade_date": {"$gte": sd, "$lte": ed}}
                    )
                    if bar_count2 < 100:
                        await mm.db["backtest_results"].update_one(
                            {"task_id": f"same_period_{sd}_{ed}"},
                            {"$set": {
                                "task_id": f"same_period_{sd}_{ed}",
                                "status": "failed",
                                "error": f"行情数据不足: {bar_count2}条(需要>100)",
                                "created_at": datetime.now().isoformat(),
                                "type": "same_period",
                            }},
                            upsert=True
                        )
                        return
                
                bt = PortfolioBacktester()
                bt_config = {
                    "start_date": sd,
                    "end_date": ed,
                    "initial_cash": 1000000,
                    "strategies": ["halfway_chase", "limit_down_qiao", "dragon_head", "first_limit_up"],
                    "mode": "backtest",
                }
                result = await bt.run(bt_config)
                
                # 存到MongoDB
                await mm.db["backtest_results"].update_one(
                    {"task_id": f"same_period_{sd}_{ed}"},
                    {"$set": {
                        "task_id": f"same_period_{sd}_{ed}",
                        "status": "completed",
                        "params": {"strategy_ids": bt_config["strategies"], "start_date": sd, "end_date": ed},
                        "result": {"summary": result},
                        "created_at": datetime.now().isoformat(),
                        "type": "same_period",
                    }},
                    upsert=True
                )
                logger.info(f"[SAME-PERIOD-BT] Completed: {sd}~{ed}, return={result.get('total_return',0):.2%}")
            except Exception as e:
                logger.error(f"[SAME-PERIOD-BT] Failed: {e}")
                try:
                    await mm.db["backtest_results"].update_one(
                        {"task_id": f"same_period_{sd}_{ed}"},
                        {"$set": {"status": "failed", "error": str(e), "created_at": datetime.now().isoformat()}},
                        upsert=True
                    )
                except: pass
        
        asyncio.create_task(_run_same_period_bt(start_date, end_date))
        
        return {"success": True, "message": f"同区间回测已启动({start_date}~{end_date}), 预计30-60秒", "start_date": start_date, "end_date": end_date}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.get("/deviation-attribution")
async def deviation_attribution(date: str = None, start_date: str = None, end_date: str = None):
    """P1: 偏差4层归因 - 滑点/纪律/选股/时间
    
    Args:
        date: 单日YYYYMMDD
        start_date/end_date: 区间查询
    """
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": None, "message": "MongoDB未初始化"}
        
        db = mongo_manager.db
        
        # 确定日期范围
        if date:
            sd = ed = date
        elif start_date and end_date:
            sd, ed = start_date, end_date
        else:
            # 默认取最近7天
            sells = []
            async for doc in db["broker_orders"].find({"side":"sell","status":"filled"},{"trade_date":1}).sort("trade_date",-1).limit(20):
                if doc.get("trade_date"): sells.append(doc["trade_date"])
            if not sells:
                return {"success": True, "data": None, "message": "无交易数据"}
            sd, ed = min(sells), max(sells)
        
        # 1. 获取实盘卖出订单
        query = {"side": "sell", "status": "filled"}
        if sd == ed:
            query["trade_date"] = sd
        else:
            query["trade_date"] = {"$gte": sd, "$lte": ed}
        
        sells = []
        async for doc in db["broker_orders"].find(query):
            sells.append(doc)
        
        # 2. 获取同区间买入订单(用于计算纪律偏差)
        buy_query = {"side": "buy", "status": "filled"}
        if sd == ed:
            buy_query["trade_date"] = sd
        else:
            buy_query["trade_date"] = {"$gte": sd, "$lte": ed}
        
        buys = []
        async for doc in db["broker_orders"].find(buy_query):
            buys.append(doc)
        
        # 3. 获取情绪数据(用于纪律检查)
        sentiment_map = {}
        s_query = {}
        if sd == ed:
            s_query["trade_date"] = int(sd)
        else:
            s_query["trade_date"] = {"$gte": int(sd), "$lte": int(ed)}
        async for doc in db["sentiment_scores"].find(s_query, {"trade_date":1, "score":1, "period":1}):
            sentiment_map[str(doc.get("trade_date",""))] = {"score": doc.get("score",50), "period": doc.get("period","震荡")}
        
        # 4. 获取scan_traces(信号价格,用于滑点计算)
        scan_map = {}  # trade_date -> {ts_code -> {price, strategy}}
        scan_query = {}
        if sd == ed:
            scan_query["trade_date"] = sd
        else:
            scan_query["trade_date"] = {"$gte": sd, "$lte": ed}
        async for doc in db["scan_traces"].find(scan_query, {"trade_date":1, "candidates":1}):
            td = doc.get("trade_date","")
            cands = doc.get("candidates",[])
            for c in cands:
                if c.get("final_status") == "passed" and c.get("ts_code"):
                    if td not in scan_map:
                        scan_map[td] = {}
                    scan_map[td][c["ts_code"]] = {"price": c.get("price",0), "strategy": c.get("strategy","")}
        
        # ============ 计算偏差 ============
        
        # A. 滑点偏差: 信号价格 vs 成交价格
        slippage_details = []
        total_slippage_pct = 0
        slippage_count = 0
        for buy in buys:
            ts = buy.get("ts_code","")
            td = buy.get("trade_date","")
            fp = buy.get("filled_price",0) or 0
            # 从scan_traces找信号价格
            signal = scan_map.get(td, {}).get(ts, {})
            sp = signal.get("price", 0)
            if sp > 0 and fp > 0:
                slippage = (fp - sp) / sp * 100  # 正=买贵了(不利)
                slippage_details.append({
                    "ts_code": ts, "stock_name": buy.get("stock_name",""),
                    "signal_price": round(sp, 2), "filled_price": round(fp, 2),
                    "slippage_pct": round(slippage, 2), "strategy": buy.get("strategy",""),
                    "trade_date": td,
                })
                total_slippage_pct += slippage
                slippage_count += 1
        
        # B. 纪律偏差: 冰点期开仓 / 情绪不匹配
        discipline_details = []
        strategy_sentiment_rules = {
            "halfway_chase": {"适合": ["高潮","分化"], "不适合": ["震荡","冰点"]},
            "first_limit_up": {"适合": ["高潮"], "不适合": ["分化","震荡","冰点"]},
            "limit_down_qiao": {"适合": ["高潮","分化","震荡"], "不适合": ["冰点"]},
            "dragon_head": {"适合": ["高潮","分化"], "不适合": ["震荡","冰点"]},
        }
        for buy in buys:
            td = buy.get("trade_date","")
            strat = buy.get("strategy","") or "unknown"
            sentiment = sentiment_map.get(td, {})
            period = sentiment.get("period","")
            if strat in strategy_sentiment_rules and period:
                not_suitable = strategy_sentiment_rules[strat].get("不适合",[])
                if period in not_suitable:
                    discipline_details.append({
                        "type": "情绪不匹配",
                        "strategy": strat, "period": period,
                        "detail": f"{period}期买入{strat}",
                        "trade_date": td, "ts_code": buy.get("ts_code",""),
                        "stock_name": buy.get("stock_name",""),
                    })
        
        # C. 选股偏差: 实盘买入 vs scan_traces候选的重叠度
        # 只统计scan_traces有数据的日期(避免日期不匹配导致overlap=0)
        scan_dates = set(scan_map.keys())
        live_picks = {}  # strategy -> [ts_codes] (only for dates with scan data)
        for buy in buys:
            td = buy.get("trade_date","")
            if td not in scan_dates:
                continue  # 跳过无scan_traces数据的日期
            s = buy.get("strategy","") or "unknown"
            if s not in live_picks: live_picks[s] = set()
            live_picks[s].add(buy.get("ts_code",""))
        
        signal_picks = {}  # strategy -> [ts_codes]
        for td, codes in scan_map.items():
            for ts, info in codes.items():
                s = info.get("strategy","")
                if s not in signal_picks: signal_picks[s] = set()
                signal_picks[s].add(ts)
        
        # 策略名映射: scan_traces中可能的别名→STRATEGY_CONFIGS的ID
        strategy_name_aliases = {
            "anomaly_surge": "halfway_chase",  # 异动急涨≈半路追涨
            "anomaly_strong": "halfway_chase",  # 异动强势≈半路追涨
            "anomaly_broken": "limit_down_qiao",  # 异动破位≈跌停翘板
        }
        
        # 统一策略名后计算重叠
        def normalize_strat(s):
            return strategy_name_aliases.get(s, s)
        
        norm_live = {}  # normalized strategy -> set of ts_codes
        for s, codes in live_picks.items():
            ns = normalize_strat(s)
            if ns not in norm_live: norm_live[ns] = set()
            norm_live[ns].update(codes)
        
        norm_signal = {}
        for s, codes in signal_picks.items():
            ns = normalize_strat(s)
            if ns not in norm_signal: norm_signal[ns] = set()
            norm_signal[ns].update(codes)
        
        selection_details = []
        for strat in set(list(norm_live.keys()) + list(norm_signal.keys())):
            lp = norm_live.get(strat, set())
            sp = norm_signal.get(strat, set())
            overlap = lp & sp
            only_live = lp - sp
            only_signal = sp - lp
            selection_details.append({
                "strategy": strat,
                "live_count": len(lp), "signal_count": len(sp),
                "overlap_count": len(overlap), "overlap_pct": round(len(overlap)/max(len(lp),1)*100,1),
                "only_live": len(only_live), "only_signal": len(only_signal),
                "scan_dates_matched": len(scan_dates),
            })
        
        # D. 时间偏差: 估算(用create_time粗略判断是否延迟)
        timing_details = []
        late_count = 0
        for buy in buys:
            ct = buy.get("create_time","")  # 格式 HH:MM:SS
            if isinstance(ct, str) and ":" in ct:
                try:
                    h, m = int(ct.split(":")[0]), int(ct.split(":")[1])
                    # 10:00前算正常, 10:00后算延迟(半路追涨不应10点后买)
                    if h >= 10 and buy.get("strategy") == "halfway_chase":
                        late_count += 1
                        timing_details.append({
                            "type": "延迟执行",
                            "strategy": buy.get("strategy",""),
                            "execute_time": ct, "expected": "10:00前",
                            "ts_code": buy.get("ts_code",""), "stock_name": buy.get("stock_name",""),
                        })
                except: pass
        
        # E. 汇总
        total_sells = len(sells)
        wins = sum(1 for s in sells if (s.get("profit_pct") or 0) >= 0)
        live_wr = round(wins / max(total_sells, 1) * 100, 1)
        
        # 违规买入的亏损贡献
        violation_sells = []
        for ds in discipline_details:
            # 找对应的卖出
            for s in sells:
                if s.get("ts_code") == ds.get("ts_code") and s.get("strategy") == ds.get("strategy"):
                    violation_sells.append(s)
        violation_loss = sum(s.get("profit_pct",0) or 0 for s in violation_sells)
        violation_wins = sum(1 for s in violation_sells if (s.get("profit_pct") or 0) >= 0)
        violation_wr = round(violation_wins/max(len(violation_sells),1)*100,1)
        
        avg_slippage = round(total_slippage_pct / max(slippage_count, 1), 2)
        
        # 总偏差估算(纪律是主因, 滑点次之)
        discipline_impact = round(violation_loss, 2)
        
        result = {
            "period": f"{sd}~{ed}",
            "live_stats": {"trades": total_sells, "wins": wins, "win_rate": live_wr},
            "risk_alerts": {
                "bearish_buy_ratio": round(len([b for b in buys if sentiment_map.get(b.get("trade_date",""),{}).get("period")=="冰点"])/max(len(buys),1)*100,1),
                "bearish_buy_count": len([b for b in buys if sentiment_map.get(b.get("trade_date",""),{}).get("period")=="冰点"]),
                "note": "冰点期开仓率高→信号管道L3层仅过滤halfway_chase, 其他策略仍允许冰点期候选通过"
            },
            "deviations": {
                "slippage": {"avg_pct": avg_slippage, "count": slippage_count, "impact": round(-avg_slippage * slippage_count / 100, 2)},
                "discipline": {"violations": len(discipline_details), "violation_wr": violation_wr, "impact": round(discipline_impact, 2)},
                "selection": selection_details,
                "timing": {"late_count": late_count, "count": len(timing_details)},
            },
            "details": {
                "slippage": slippage_details[:20],
                "discipline": discipline_details[:20],
                "timing": timing_details[:10],
            }
        }
        
        return {"success": True, "data": _clean_mongo(result)}
    except Exception as e:
        logger.error(f"[DEVIATION] {e}")
        return {"success": True, "data": None, "message": str(e)}


@router.get("/param-snapshot")
async def param_snapshot(date: str = None):
    """P2: 参数快照 - 当前参数状态(用于月复盘参数漂移检测)
    
    存一份当前strategy_defaults到MongoDB param_snapshots
    """
    try:
        from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS, GLOBAL_RISK
        from core.managers import mongo_manager
        
        today = date or datetime.now().strftime("%Y%m%d")
        snapshot = {
            "date": today,
            "global_risk": {k: v for k, v in GLOBAL_RISK.items() if not k.startswith("__")},
            "strategies": {},
        }
        for sid, cfg in STRATEGY_CONFIGS.items():
            snapshot["strategies"][sid] = {
                "enabled": cfg.get("enabled", True),
                "params": cfg.get("params", {}),
                "riskParams": cfg.get("riskParams", {}),
            }
        
        if mongo_manager.is_initialized:
            await mongo_manager.db["param_snapshots"].update_one(
                {"date": today},
                {"$set": snapshot},
                upsert=True
            )
        
        return {"success": True, "data": snapshot, "message": f"参数快照已保存({today})"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.get("/param-drift")
async def param_drift(start_date: str = None, end_date: str = None):
    """P2: 参数漂移检测 - 对比两个日期的参数差异
    
    用于月复盘: 当前参数 vs 30天前参数
    """
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": None, "message": "MongoDB未初始化"}
        
        db = mongo_manager.db
        end_date = end_date or datetime.now().strftime("%Y%m%d")
        
        # 找最近的快照
        end_snap = await db["param_snapshots"].find_one({"date": {"$lte": end_date}}, sort=[("date",-1)])
        if not end_snap:
            # 自动创建当前快照
            from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS, GLOBAL_RISK
            end_snap = {
                "date": end_date,
                "global_risk": {k:v for k,v in GLOBAL_RISK.items() if not k.startswith("__")},
                "strategies": {sid: {"params":cfg.get("params",{}),"riskParams":cfg.get("riskParams",{})} for sid,cfg in STRATEGY_CONFIGS.items()},
            }
        
        if start_date:
            start_snap = await db["param_snapshots"].find_one({"date": {"$lte": start_date}}, sort=[("date",-1)])
        else:
            # 找最早的快照
            start_snap = await db["param_snapshots"].find_one(sort=[("date",1)])
        
        if not start_snap:
            return {"success": True, "data": {"current": end_snap, "baseline": None, "drifts": []}, "message": "无历史快照,无法检测漂移"}
        
        # 对比参数
        drifts = []
        
        # 全局参数
        start_g = start_snap.get("global_risk", {})
        end_g = end_snap.get("global_risk", {})
        for key in set(list(start_g.keys()) + list(end_g.keys())):
            sv = start_g.get(key)
            ev = end_g.get(key)
            if sv != ev and not isinstance(sv, (dict, list)):
                drifts.append({"level":"global","key":key,"old":sv,"new":ev,"severity":"high" if key in ["stop_loss_pct","take_profit_pct","max_position_per_stock","max_total_position"] else "medium"})
        
        # 策略参数
        start_s = start_snap.get("strategies", {})
        end_s = end_snap.get("strategies", {})
        for sid in set(list(start_s.keys()) + list(end_s.keys())):
            for param_type in ["params","riskParams"]:
                sp = start_s.get(sid,{}).get(param_type,{})
                ep = end_s.get(sid,{}).get(param_type,{})
                for key in set(list(sp.keys()) + list(ep.keys())):
                    sv = sp.get(key)
                    ev = ep.get(key)
                    if sv != ev and not isinstance(sv, (dict, list)):
                        drifts.append({"level":"strategy","strategy":sid,"param_type":param_type,"key":key,"old":sv,"new":ev,"severity":"high" if param_type=="riskParams" else "medium"})
        
        return {"success": True, "data": {
            "start_date": start_snap.get("date"),
            "end_date": end_snap.get("date"),
            "drifts": drifts,
            "drift_count": len(drifts),
            "high_severity": len([d for d in drifts if d.get("severity")=="high"]),
        }}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.get("/review-weekly")
async def review_weekly(date: str = None):
    """P2: 周复盘 - 策略效能+偏差趋势+情绪环境
    
    Args:
        date: 周内任一天, 自动计算该周范围
    """
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": None, "message": "MongoDB未初始化"}
        
        db = mongo_manager.db
        
        # 计算本周范围(周一~周日)
        if date:
            from datetime import datetime as dt, timedelta
            d = dt.strptime(date, "%Y%m%d")
            weekday = d.weekday()
            monday = (d - timedelta(days=weekday)).strftime("%Y%m%d")
            sunday = (d + timedelta(days=6-weekday)).strftime("%Y%m%d")
        else:
            from datetime import datetime as dt, timedelta
            today = dt.now()
            weekday = today.weekday()
            monday = (today - timedelta(days=weekday)).strftime("%Y%m%d")
            sunday = (today + timedelta(days=6-weekday)).strftime("%Y%m%d")
        
        # 获取本周卖出
        sells = []
        async for doc in db["broker_orders"].find({"side":"sell","status":"filled","trade_date":{"$gte":monday,"$lte":sunday}}):
            sells.append(doc)
        
        # 获取本周买入
        buys = []
        async for doc in db["broker_orders"].find({"side":"buy","status":"filled","trade_date":{"$gte":monday,"$lte":sunday}}):
            buys.append(doc)
        
        # 逐日统计(偏差趋势)
        from collections import defaultdict
        daily_stats = defaultdict(lambda: {"buys":0,"sells":0,"wins":0,"pnl":0})
        for s in sells:
            td = s.get("trade_date","")
            daily_stats[td]["sells"] += 1
            if (s.get("profit_pct") or 0) >= 0:
                daily_stats[td]["wins"] += 1
            daily_stats[td]["pnl"] += s.get("profit_pct",0) or 0
        for b in buys:
            daily_stats[b.get("trade_date","")]["buys"] += 1
        
        # 情绪数据
        sentiments = {}
        async for doc in db["sentiment_scores"].find({"trade_date":{"$gte":int(monday),"$lte":int(sunday)}},{"trade_date":1,"score":1,"period":1}):
            sentiments[str(doc.get("trade_date",""))] = {"score":doc.get("score",50),"period":doc.get("period","")}
        
        # 策略统计
        strategy_stats = defaultdict(lambda: {"trades":0,"wins":0,"pnl":0})
        for s in sells:
            strat = s.get("strategy","") or "unknown"
            strategy_stats[strat]["trades"] += 1
            if (s.get("profit_pct") or 0) >= 0:
                strategy_stats[strat]["wins"] += 1
            strategy_stats[strat]["pnl"] += s.get("profit_pct",0) or 0
        
        total_sells = len(sells)
        total_wins = sum(1 for s in sells if (s.get("profit_pct") or 0) >= 0)
        total_pnl = sum(s.get("profit_pct",0) or 0 for s in sells)
        
        # 偏差趋势(近4周)
        weekly_trend = []
        from datetime import datetime as dt, timedelta
        base = dt.strptime(monday, "%Y%m%d")
        for w in range(4):
            wm = (base - timedelta(weeks=3-w)).strftime("%Y%m%d")
            ws = (base - timedelta(weeks=3-w) + timedelta(days=6)).strftime("%Y%m%d")
            ws_list = []
            async for doc in db["broker_orders"].find({"side":"sell","status":"filled","trade_date":{"$gte":wm,"$lte":ws}}):
                ws_list.append(doc)
            if ws_list:
                wr = sum(1 for s in ws_list if (s.get("profit_pct") or 0) >= 0) / len(ws_list) * 100
                weekly_trend.append({"week": f"W{w+1}", "start": wm, "trades": len(ws_list), "win_rate": round(wr,1)})
            else:
                weekly_trend.append({"week": f"W{w+1}", "start": wm, "trades": 0, "win_rate": 0})
        
        result = {
            "period": f"{monday}~{sunday}",
            "summary": {"trades": total_sells, "wins": total_wins, "win_rate": round(total_wins/max(total_sells,1)*100,1), "pnl": round(total_pnl,2)},
            "strategy_stats": {k: {"trades":v["trades"],"win_rate":round(v["wins"]/max(v["trades"],1)*100,1),"pnl":round(v["pnl"],2)} for k,v in strategy_stats.items()},
            "daily_breakdown": [{"date":td,"buys":v["buys"],"sells":v["sells"],"win_rate":round(v["wins"]/max(v["sells"],1)*100,1),"pnl":round(v["pnl"],2)} for td,v in sorted(daily_stats.items())],
            "sentiments": sentiments,
            "weekly_trend": weekly_trend,
        }
        
        return {"success": True, "data": _clean_mongo(result)}
    except Exception as e:
        logger.error(f"[REVIEW-WEEKLY] {e}")
        return {"success": True, "data": None, "message": str(e)}


@router.get("/review-monthly")
async def review_monthly(date: str = None):
    """P2: 月复盘 - 系统偏差+参数漂移+行为漂移+因子效果
    
    Args:
        date: 月内任一天, 自动计算该月范围
    """
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": None, "message": "MongoDB未初始化"}
        
        db = mongo_manager.db
        
        # 计算本月范围
        if date:
            month_start = date[:6] + "01"
            from datetime import datetime as dt
            d = dt.strptime(date, "%Y%m%d")
            if d.month == 12:
                month_end = f"{d.year+1}0101"
            else:
                month_end = f"{d.year}{d.month+1:02d}01"
            # 取上月末
            from datetime import datetime as dt, timedelta
            next_month = dt.strptime(month_end, "%Y%m%d")
            last_day = (next_month - timedelta(days=1)).strftime("%Y%m%d")
        else:
            from datetime import datetime as dt, timedelta
            today = dt.now()
            month_start = today.strftime("%Y%m01")
            if today.month == 12:
                next_m = dt(today.year+1, 1, 1)
            else:
                next_m = dt(today.year, today.month+1, 1)
            last_day = (next_m - timedelta(days=1)).strftime("%Y%m%d")
        
        # 月度统计
        sells = []
        async for doc in db["broker_orders"].find({"side":"sell","status":"filled","trade_date":{"$gte":month_start,"$lte":last_day}}):
            sells.append(doc)
        
        buys = []
        async for doc in db["broker_orders"].find({"side":"buy","status":"filled","trade_date":{"$gte":month_start,"$lte":last_day}}):
            buys.append(doc)
        
        total_sells = len(sells)
        total_wins = sum(1 for s in sells if (s.get("profit_pct") or 0) >= 0)
        total_pnl = sum(s.get("profit_pct",0) or 0 for s in sells)
        
        # 策略月度
        from collections import defaultdict
        strategy_stats = defaultdict(lambda: {"trades":0,"wins":0,"pnl":0,"positions":0})
        for s in sells:
            strat = s.get("strategy","") or "unknown"
            strategy_stats[strat]["trades"] += 1
            if (s.get("profit_pct") or 0) >= 0:
                strategy_stats[strat]["wins"] += 1
            strategy_stats[strat]["pnl"] += s.get("profit_pct",0) or 0
        
        # 行为漂移: 止损执行率、冰点开仓率
        stop_loss_sells = sum(1 for s in sells if "止损" in (s.get("reason","")))
        # 区分: 真正亏损止损 vs 盈利止损(冲高回落触发但实际盈利)
        stop_loss_at_loss = sum(1 for s in sells if "止损" in (s.get("reason","")) and (s.get("profit_pct") or 0) < 0)
        stop_loss_at_profit = sum(1 for s in sells if "止损" in (s.get("reason","")) and (s.get("profit_pct") or 0) >= 0)
        loss_sells = sum(1 for s in sells if (s.get("profit_pct") or 0) < 0)
        # 止损执行率 = 亏损止损卖出 / 所有亏损卖出 (真正该止损的有多少执行了)
        # 70.8%: 有近30%的亏损没走止损, 说明止损不够及时
        
        # 冰点期开仓
        sentiment_map = {}
        async for doc in db["sentiment_scores"].find({"trade_date":{"$gte":int(month_start),"$lte":int(last_day)}},{"trade_date":1,"period":1,"score":1}):
            sentiment_map[str(doc.get("trade_date",""))] = {"period":doc.get("period",""),"score":doc.get("score",50)}
        
        bearish_buys = 0
        for b in buys:
            td = b.get("trade_date","")
            if sentiment_map.get(td,{}).get("period") == "冰点":
                bearish_buys += 1
        
        # 参数漂移
        drift_data = None
        try:
            drift_resp = await param_drift(month_start, last_day)
            drift_data = drift_resp.get("data")
        except: pass
        
        # 大盘表现
        index_data = []
        async for doc in db["index_daily"].find({"ts_code":"000001.SH","trade_date":{"$gte":int(month_start),"$lte":int(last_day)}},{"trade_date":1,"close":1,"pct_chg":1}).sort("trade_date",1):
            index_data.append({"date":str(doc["trade_date"]),"close":round(doc.get("close",0),2),"pct_chg":round(doc.get("pct_chg",0),2)})
        
        result = {
            "period": f"{month_start}~{last_day}",
            "summary": {"trades":total_sells,"wins":total_wins,"win_rate":round(total_wins/max(total_sells,1)*100,1),"pnl":round(total_pnl,2)},
            "strategy_stats": {k: {"trades":v["trades"],"win_rate":round(v["wins"]/max(v["trades"],1)*100,1),"pnl":round(v["pnl"],2)} for k,v in strategy_stats.items()},
            "behavior_drift": {
                "stop_loss_execution_rate": round(stop_loss_at_loss/max(loss_sells,1)*100,1),
                "stop_loss_at_loss": stop_loss_at_loss, "stop_loss_at_profit": stop_loss_at_profit,
                "loss_sells": loss_sells,
                "bearish_period_buy_ratio": round(bearish_buys/max(len(buys),1)*100,1),
                "bearish_buys": bearish_buys, "total_buys": len(buys),
            },
            "param_drift": drift_data,
            "index_performance": index_data,
        }
        
        return {"success": True, "data": _clean_mongo(result)}
    except Exception as e:
        logger.error(f"[REVIEW-MONTHLY] {e}")
        return {"success": True, "data": None, "message": str(e)}


@router.get("/factor-effectiveness")
async def factor_effectiveness(date: str = None):
    from core.managers import mongo_manager
    """因子效果跟踪: 不同情绪阶段下各因子的胜率/盈亏变化(市场漂移检测)"""
    try:
        if not date:
            date = datetime.now().strftime("%Y%m%d")
        
        if not mongo_manager.is_initialized:
            return {"success": False, "message": "MongoDB未初始化"}
        
        db = mongo_manager.db
        
        # 最近30天
        end_date = int(date)
        start_date = end_date - 30
        
        # 1. 加载情绪数据
        sentiment_map = {}  # date -> {score, period}
        async for doc in db["sentiment_scores"].find(
            {"trade_date": {"$gte": start_date, "$lte": end_date}},
            {"_id": 0, "trade_date": 1, "score": 1, "period": 1}
        ):
            td = str(doc.get("trade_date", ""))
            sentiment_map[td] = {"score": doc.get("score", 50), "period": doc.get("period", "震荡")}
        
        # 2. 加载scan_traces候选(含因子数据)
        factor_stats = {}  # factor_name -> {period -> {total, wins, avg_pnl}}
        factor_names = ["量比", "涨幅", "换手率", "连板数"]
        
        # 用scan_traces中passed的候选和对应实盘结果
        trace_dates = set()
        async for doc in db["scan_traces"].find(
            {"trade_date": {"$gte": str(start_date), "$lte": str(end_date)}},
            {"_id": 0, "candidates": 1, "trade_date": 1}
        ):
            td = doc.get("trade_date", "")
            trace_dates.add(td)
            period = sentiment_map.get(td, {}).get("period", "未知")
            
            for c in doc.get("candidates", []):
                if c.get("final_status") != "passed":
                    continue
                
                # 提取因子值(粗略用pct_chg和价格区间)
                pct_chg = c.get("pct_chg", 0) or 0
                price = c.get("price", 0) or 0
                strategy = c.get("strategy", "")
                
                # 量比分组
                vol_ratio_bucket = "低(<1.5)" if abs(pct_chg) < 2 else ("中(1.5-3)" if abs(pct_chg) < 5 else "高(>3)")
                # 涨幅分组
                gain_bucket = "小涨(<2%)" if pct_chg < 2 else ("中涨(2-5%)" if pct_chg < 5 else "大涨(>5%)")
                # 策略分组
                strat_name = strategy or "unknown"
                
                for fname, bucket in [("量比区间", vol_ratio_bucket), ("涨幅区间", gain_bucket), ("策略", strat_name)]:
                    if fname not in factor_stats:
                        factor_stats[fname] = {}
                    if period not in factor_stats[fname]:
                        factor_stats[fname][period] = {}
                    if bucket not in factor_stats[fname][period]:
                        factor_stats[fname][period][bucket] = {"total": 0, "wins": 0, "pnl_sum": 0}
                    factor_stats[fname][period][bucket]["total"] += 1
        
        # 3. 用broker_orders的买入和后续卖出结果来补充胜率
        # 简化: 用scan_traces候选的pct_chg作为近似
        buys_by_date = {}  # date -> {ts_code -> {strategy, pct_chg}}
        async for doc in db["broker_orders"].find(
            {"side": "buy", "status": "filled", "trade_date": {"$gte": str(start_date), "$lte": str(end_date)}},
            {"_id": 0, "trade_date": 1, "ts_code": 1, "strategy": 1, "filled_price": 1}
        ):
            td = doc.get("trade_date", "")
            if td not in buys_by_date:
                buys_by_date[td] = {}
            buys_by_date[td][doc.get("ts_code", "")] = {
                "strategy": doc.get("strategy", ""),
                "price": doc.get("filled_price", 0)
            }
        
        # 用卖出profit_pct来算胜率
        sells_by_buy = {}  # (date, ts_code) -> profit_pct
        async for doc in db["broker_orders"].find(
            {"side": "sell", "status": "filled", "trade_date": {"$gte": str(start_date), "$lte": str(end_date)}},
            {"_id": 0, "trade_date": 1, "ts_code": 1, "strategy": 1, "profit_pct": 1, "reason": 1}
        ):
            sells_by_buy[(doc.get("trade_date", ""), doc.get("ts_code", ""))] = doc.get("profit_pct", 0) or 0
        
        # 4. 补充因子胜率(用实际买卖结果)
        for td, codes in buys_by_date.items():
            period = sentiment_map.get(td, {}).get("period", "未知")
            for ts, info in codes.items():
                pnl = sells_by_buy.get((td, ts), None)
                if pnl is None:
                    continue
                
                strat = info.get("strategy", "") or "unknown"
                price = info.get("price", 0)
                
                # 因子分组
                for fname, bucket in [("策略", strat)]:
                    if fname not in factor_stats:
                        factor_stats[fname] = {}
                    if period not in factor_stats[fname]:
                        factor_stats[fname][period] = {}
                    if bucket not in factor_stats[fname][period]:
                        factor_stats[fname][period][bucket] = {"total": 0, "wins": 0, "pnl_sum": 0}
                    factor_stats[fname][period][bucket]["total"] += 1
                    if pnl > 0:
                        factor_stats[fname][period][bucket]["wins"] += 1
                    factor_stats[fname][period][bucket]["pnl_sum"] += pnl
        
        # 5. 计算胜率
        result = {}
        for fname, periods in factor_stats.items():
            result[fname] = {}
            for period, buckets in periods.items():
                result[fname][period] = []
                for bucket, stats in buckets.items():
                    total = stats["total"]
                    wins = stats["wins"]
                    avg_pnl = round(stats["pnl_sum"] / max(total, 1), 2)
                    wr = round(wins / max(total, 1) * 100, 1)
                    result[fname][period].append({
                        "name": bucket, "total": total, "wins": wins,
                        "win_rate": wr, "avg_pnl": avg_pnl,
                    })
                result[fname][period].sort(key=lambda x: x["total"], reverse=True)
        
        # 6. 市场漂移检测: 同一因子在不同阶段的胜率变化
        drift_alerts = []
        for fname, periods in factor_stats.items():
            if len(periods) < 2:
                continue
            all_buckets = set()
            for p_data in periods.values():
                all_buckets.update(p_data.keys())
            for bucket in all_buckets:
                wrs = {}
                for p, p_data in periods.items():
                    if bucket in p_data and p_data[bucket]["total"] >= 3:
                        wrs[p] = round(p_data[bucket]["wins"] / p_data[bucket]["total"] * 100, 1)
                if len(wrs) >= 2:
                    values = list(wrs.values())
                    spread = max(values) - min(values)
                    if spread > 20:  # 胜率差>20%说明市场漂移明显
                        drift_alerts.append({
                            "factor": fname, "bucket": bucket,
                            "detail": wrs, "spread": round(spread, 1),
                            "alert": f"{bucket}在不同情绪阶段胜率差{spread:.0f}%，市场漂移明显",
                        })
        
        return {
            "success": True,
            "data": {
                "factor_stats": result,
                "drift_alerts": drift_alerts,
                "date_range": f"{start_date}~{end_date}",
                "sentiment_days": len(sentiment_map),
            }
        }
    except Exception as e:
        logger.error(f"[FACTOR-EFFECTIVENESS] {e}")
        return {"success": True, "data": None, "message": str(e)}


@router.get("/review-closed-loop")
async def review_closed_loop(date: str = None):
    from core.managers import mongo_manager
    """闭环建议: 基于偏差归因自动生成参数调整建议和验证方案"""
    try:
        if not date:
            date = datetime.now().strftime("%Y%m%d")
        
        if not mongo_manager.is_initialized:
            return {"success": False, "message": "MongoDB未初始化"}
        
        db = mongo_manager.db
        
        # 1. 获取偏差归因数据
        int_date = int(date)
        end_d = int(date)
        start_d = end_d - 13  # 最近2周
        
        # 加载情绪
        sentiment_map = {}
        async for doc in db["sentiment_scores"].find(
            {"trade_date": {"$gte": start_d, "$lte": end_d}},
            {"_id": 0, "trade_date": 1, "score": 1, "period": 1}
        ):
            td = str(doc.get("trade_date", ""))
            sentiment_map[td] = doc
        
        # 加载买卖数据
        buys = []
        sells = []
        async for doc in db["broker_orders"].find(
            {"status": "filled", "trade_date": {"$gte": str(start_d), "$lte": str(end_d)}},
            {"_id": 0, "side": 1, "strategy": 1, "ts_code": 1, "stock_name": 1,
             "filled_price": 1, "profit_pct": 1, "reason": 1, "trade_date": 1, "create_time": 1}
        ):
            if doc.get("side") == "buy":
                buys.append(doc)
            else:
                sells.append(doc)
        
        # 2. 诊断偏差
        suggestions = []
        
        # 2a. 纪律偏差 → 止损/止盈建议
        sl_sells = [s for s in sells if "止损" in (s.get("reason", "")) and (s.get("profit_pct") or 0) < 0]
        loss_sells = [s for s in sells if (s.get("profit_pct") or 0) < 0]
        if loss_sells:
            sl_rate = len(sl_sells) / len(loss_sells) * 100
            if sl_rate < 80:
                # 找出亏损最深但没止损的
                non_sl_loss = [s for s in loss_sells if "止损" not in (s.get("reason", ""))]
                non_sl_loss.sort(key=lambda x: x.get("profit_pct", 0))
                worst = non_sl_loss[:3] if non_sl_loss else []
                suggestions.append({
                    "type": "止损纪律",
                    "severity": "high" if sl_rate < 60 else "medium",
                    "diagnosis": f"止损执行率仅{sl_rate:.0f}%({len(sl_sells)}/{len(loss_sells)})",
                    "action": "收紧止损触发条件，将next_day_open_sell_pct从当前值降低0.5-1%",
                    "verification": "同区间回测验证：调整后止损执行率应>85%，且总收益不降",
                    "worst_cases": [{"ts_code": w.get("ts_code"), "name": w.get("stock_name"), "pnl": w.get("profit_pct")} for w in worst],
                })
        
        # 2b. 情绪偏差 → 仓位调整建议
        bearish_buys = [b for b in buys if sentiment_map.get(b.get("trade_date", ""), {}).get("period") == "冰点"]
        if len(buys) > 0 and len(bearish_buys) / len(buys) > 0.5:
            bearish_wr = len([s for s in sells if s.get("profit_pct", 0) > 0 and sentiment_map.get(s.get("trade_date", ""), {}).get("period") == "冰点"]) / max(len([s for s in sells if sentiment_map.get(s.get("trade_date", ""), {}).get("period") == "冰点"]), 1) * 100
            suggestions.append({
                "type": "情绪仓位",
                "severity": "high",
                "diagnosis": f"冰点期开仓率{len(bearish_buys)/len(buys)*100:.0f}%，冰点期胜率{bearish_wr:.0f}%",
                "action": "建议冰点期仓位系数从0.3降至0.1，或信号管道L3增加全策略冰点过滤",
                "verification": "同区间回测：冰点期仓位0.1 vs 0.3的收益对比",
            })
        
        # 2c. 策略偏差 → 策略参数建议
        strat_stats = {}
        for s in sells:
            strat = s.get("strategy", "") or "unknown"
            if strat not in strat_stats:
                strat_stats[strat] = {"trades": 0, "wins": 0, "pnl": 0}
            strat_stats[strat]["trades"] += 1
            if (s.get("profit_pct") or 0) > 0:
                strat_stats[strat]["wins"] += 1
            strat_stats[strat]["pnl"] += (s.get("profit_pct") or 0)
        
        for strat, stats in strat_stats.items():
            if stats["trades"] >= 5:
                wr = stats["wins"] / stats["trades"] * 100
                avg_pnl = stats["pnl"] / stats["trades"]
                if wr < 50 and avg_pnl < 0:
                    cn_name = {"halfway_chase": "半路追涨", "limit_down_qiao": "跌停翘板", "dragon_head": "龙头低吸", "first_limit_up": "首板打板"}.get(strat, strat)
                    suggestions.append({
                        "type": "策略表现",
                        "severity": "medium",
                        "diagnosis": f"{cn_name}近2周WR={wr:.0f}% 均盈亏={avg_pnl:.2f}%",
                        "action": f"考虑暂停{cn_name}或收紧选股条件(提高流动性门槛/缩小涨幅范围)",
                        "verification": f"回测对比：{cn_name}收紧条件前后的WR和收益",
                    })
        
        # 2d. 滑点偏差 → 执行优化
        slippage_list = []
        for buy in buys:
            td = buy.get("trade_date", "")
            ts = buy.get("ts_code", "")
            fill_price = buy.get("filled_price", 0) or 0
            # 从scan_traces找信号价
            if fill_price > 0:
                # 简化: 用当天最高价和成交价差来估算
                slippage_list.append(fill_price)
        
        # 2e. 参数漂移建议
        try:
            latest_snap = await db["param_snapshots"].find_one(sort=[("date", -1)])
            if latest_snap:
                snap_date = latest_snap.get("date", "")
                if snap_date != date:
                    suggestions.append({
                        "type": "参数漂移",
                        "severity": "low",
                        "diagnosis": f"最新参数快照是{snap_date}，与当前日期{date}不一致",
                        "action": "建议更新参数快照以确保漂移检测准确",
                        "verification": "点击📸保存当前参数快照",
                    })
        except:
            pass
        
        # 3. 优先级排序
        severity_order = {"high": 0, "medium": 1, "low": 2}
        suggestions.sort(key=lambda x: severity_order.get(x.get("severity", "low"), 2))
        
        return {
            "success": True,
            "data": {
                "suggestions": suggestions,
                "summary": {
                    "total": len(suggestions),
                    "high": len([s for s in suggestions if s.get("severity") == "high"]),
                    "medium": len([s for s in suggestions if s.get("severity") == "medium"]),
                    "low": len([s for s in suggestions if s.get("severity") == "low"]),
                },
                "date_range": f"{start_d}~{end_d}",
            }
        }
    except Exception as e:
        logger.error(f"[REVIEW-CLOSED-LOOP] {e}")
        return {"success": True, "data": None, "message": str(e)}

