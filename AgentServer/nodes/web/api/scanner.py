#!/usr/bin/env python3
"""
MarketScanner REST API
超短量化市场扫描器的控制接口
"""
import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("api.scanner")

router = APIRouter(prefix="/scanner", tags=["市场监听"])

# 全局扫描器实例
_scanner_instance = None


def _get_scanner():
    global _scanner_instance
    if _scanner_instance is None:
        from nodes.market_monitor.scanner import MarketScanner
        _scanner_instance = MarketScanner()
    return _scanner_instance


def _get_scanner_instance():
    """外部模块获取scanner实例(只读)"""
    return _scanner_instance


class ScannerStartRequest(BaseModel):
    account_id: str = "default"
    trade_date: Optional[str] = None
    trade_mode: str = "simulated"  # simulated | gm
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
    """获取扫描器状态(含熔断状态)"""
    scanner = _get_scanner()
    status = scanner.get_status()
    # 追加熔断状态
    if hasattr(scanner, '_circuit_breaker'):
        status["circuit_breaker"] = {
            "trading_paused": scanner._circuit_breaker.get("trading_paused", False),
            "pause_reason": scanner._circuit_breaker.get("pause_reason", ""),
            "consecutive_losses": scanner._circuit_breaker.get("consecutive_losses", 0),
            "today_trades": scanner._circuit_breaker.get("today_trades", 0),
            "today_losses": scanner._circuit_breaker.get("today_losses", 0),
        }
    return {"success": True, "data": status}


# ==================== 控制 ====================

@router.post("/start")
async def start_scanner(req: ScannerStartRequest):
    """启动扫描"""
    global _scanner_instance

    if _scanner_instance is None or (
        req.trade_mode == 'gm' and _scanner_instance._trade_mode != 'gm'
    ) or (
        req.trade_mode == 'simulated' and _scanner_instance._trade_mode != 'simulated'
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
    return {"success": True, "data": scanner.get_signals()}


@router.get("/positions")
async def get_positions():
    """获取实时持仓"""
    scanner = _get_scanner()
    return {"success": True, "data": scanner.get_positions()}


@router.get("/timeline")
async def get_timeline():
    """获取今日交易时间线"""
    scanner = _get_scanner()
    return {"success": True, "data": scanner.get_timeline()}


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
        raise HTTPException(400, f"{req.ts_code} 无实时行情, 请先启动扫描器")
    
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


@router.post("/scan-once")
async def scan_once():
    """手动触发一次扫描"""
    scanner = _get_scanner()
    from datetime import datetime
    trade_date = datetime.now().strftime("%Y%m%d")
    await scanner.scan_once(trade_date)
    return {
        "success": True,
        "data": {
            "signals": len(scanner.get_signals()),
            "positions": len(scanner.get_positions()),
        },
    }
