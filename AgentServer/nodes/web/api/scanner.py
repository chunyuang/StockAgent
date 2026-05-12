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


# ==================== 状态 ====================

@router.get("/status")
async def get_scanner_status():
    """获取扫描器状态"""
    scanner = _get_scanner()
    return {
        "success": True,
        "data": scanner.get_status(),
    }


# ==================== 控制 ====================

@router.post("/start")
async def start_scanner(req: ScannerStartRequest):
    """启动扫描"""
    global _scanner_instance

    # 如果请求的trade_mode与当前实例不一致, 需要重建
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
    return {
        "success": True,
        "data": scanner.get_signals(),
    }


@router.get("/positions")
async def get_positions():
    """获取实时持仓"""
    scanner = _get_scanner()
    return {
        "success": True,
        "data": scanner.get_positions(),
    }


@router.get("/timeline")
async def get_timeline():
    """获取今日交易时间线"""
    scanner = _get_scanner()
    return {
        "success": True,
        "data": scanner.get_timeline(),
    }


# ==================== 手动操作 ====================

@router.post("/scan-once")
async def scan_once():
    """手动触发一次扫描"""
    scanner = _get_scanner()
    trade_date = req.trade_date if 'req' in dir() else None
    if not trade_date:
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
