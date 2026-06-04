#!/usr/bin/env python3
"""
Scanner API 共享模块
- 工具函数(_clean_mongo, _fill_stock_names, _safe_read_shared)
- Scanner单例管理(_get_scanner, _get_scanner_instance)
- Pydantic Request Models
- 公共logger

所有scanner子模块从这里导入共享依赖, 避免循环引用。
"""
import asyncio
import logging
from typing import Dict, Any, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from nodes.web.api.utils import sanitize_nan as _sanitize

logger = logging.getLogger("api.scanner")


# ==================== Scanner单例管理 ====================

_scanner_lock = asyncio.Lock()
_scanner_instance = None


async def _get_scanner():
    """获取Scanner单例, 用asyncio.Lock保护防止并发创建"""
    global _scanner_instance
    if _scanner_instance is not None:
        pass  # 快速路径
    else:
        async with _scanner_lock:
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


# ==================== 工具函数 ====================

def _clean_mongo(doc):
    """清理MongoDB文档,移除ObjectId等不可序列化字段"""
    if isinstance(doc, dict):
        return {k: _clean_mongo(v) for k, v in doc.items() if k != '_id'}
    elif isinstance(doc, list):
        return [_clean_mongo(i) for i in doc]
    elif isinstance(doc, (int, float, str, bool, type(None))):
        return doc
    else:
        return str(doc)


def _fill_stock_names(data, scanner=None) -> list:
    """填充空stock_name/name字段(从scanner的名称映射), 支持嵌套结构
    
    【v2.9.79】增强: name_map为空时从MongoDB stock_basic加载
    """
    if not scanner or not data:
        return data
    name_map = getattr(scanner, '_stock_name_map', {})
    if not name_map:
        # 从MongoDB加载全量名称映射
        try:
            from pymongo import MongoClient
            client = MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=2000)
            docs = list(client["stock_agent"]["stock_basic"].find(
                {}, {"ts_code": 1, "name": 1, "_id": 0}
            ).limit(10000))
            for doc in docs:
                if doc.get("ts_code") and doc.get("name"):
                    name_map[doc["ts_code"]] = doc["name"]
            if name_map:
                scanner._stock_name_map = name_map
        except Exception:
            pass
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
    """【v2.9.11】线程安全读取scanner共享状态"""
    state_lock = getattr(scanner, '_state_lock', None)
    data = getattr(scanner, attr_name, {})
    if state_lock:
        with state_lock:
            return dict(data) if copy else data
    return dict(data) if copy else data


# ==================== Pydantic Models ====================

class ScannerStartRequest(BaseModel):
    account_id: str = "default"
    trade_date: Optional[str] = None
    trade_mode: str = "simulated"  # simulated | gm | dry_run | replay
    replay_date: Optional[str] = None
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


class StopScannerRequest(BaseModel):
    sell_all: bool = False


class PauseRequest(BaseModel):
    reason: str = "手动暂停"


class ScanOnceRequest(BaseModel):
    strategy: Optional[str] = None
    force: bool = False


class PartialSellRequest(BaseModel):
    ts_code: str
    quantity: int = 0  # 0=全部卖出
    reason: str = ""
