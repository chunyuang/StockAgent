#!/usr/bin/env python3
"""
数据源与券商管理 REST API

提供数据源切换、状态监控、券商管理的接口。
"""
import logging
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("api.datasource")

router = APIRouter(prefix="/datasource", tags=["数据源管理"])

# 全局路由器实例
_router_instance = None


def _get_router():
    global _router_instance
    if _router_instance is None:
        from nodes.market_monitor.data_source_router import DataSourceRouter
        _router_instance = DataSourceRouter()
    return _router_instance


def set_router(router_instance):
    """外部设置router实例(由app.py调用)"""
    global _router_instance
    _router_instance = router_instance


# ==================== 数据源管理 ====================

@router.get("/sources")
async def list_data_sources():
    """列出所有数据源及状态"""
    result = []
    
    # 尝试从scanner获取实际数据源状态
    try:
        from nodes.web.api.scanner_shared import _get_scanner_instance
        scanner = _get_scanner_instance()
        if scanner and scanner._data_router:
            for name, adapter in scanner._data_router._sources.items():
                try:
                    status = adapter.get_status()
                    result.append({
                        "name": name,
                        "available": status.get("available", status.get("initialized", True)),
                        "initialized": status.get("initialized", True),
                        "priority": adapter._get_default_priority(),
                        "active": True,
                        "daily_calls": status.get("daily_calls", 0),
                        "daily_limit": status.get("daily_limit", -1),
                        "daily_remaining": status.get("daily_limit", 0) - status.get("daily_calls", 0) if status.get("daily_limit", -1) > 0 else -1,
                        "total_stocks": status.get("total_stocks", 0),
                        "cached_stocks": status.get("cached_stocks", 0),
                        "note": status.get("note", ""),
                        "capabilities": "",
                    })
                except Exception as e:
                    result.append({"name": name, "available": False, "error": str(e)})
    except Exception:
        pass
    
    if not result:
        router = _get_router()
        statuses = router.get_all_statuses()
        for name, status in statuses.items():
            result.append({
                "name": name,
                "available": status.available,
                "initialized": status.initialized,
                "priority": status.priority,
                "active": name == router.get_active_source(),
                "daily_calls": status.daily_calls,
                "daily_limit": status.daily_limit,
                "daily_remaining": status.daily_remaining,
                "capabilities": status.capabilities,
            })

    return {"success": True, "data": result}


@router.post("/switch")
async def switch_data_source(req: Dict[str, str]):
    """切换数据源"""
    source = req.get("source")
    if not source:
        raise HTTPException(400, "缺少source参数")

    router = _get_router()
    ok = router.set_active_source(source)
    if not ok:
        raise HTTPException(400, f"数据源 {source} 不可用")

    return {"success": True, "data": {"active_source": router.get_active_source()}}


@router.get("/active")
async def get_active_source():
    """获取当前活跃数据源"""
    router = _get_router()
    return {"success": True, "data": {"active_source": router.get_active_source()}}


# ==================== 数据源能力对比 ====================

@router.get("/comparison")
async def get_data_source_comparison():
    """数据源能力对比表"""
    comparison = [
        {
            "dimension": "Linux可用",
            "biying": True,
            "gm": False,
        },
        {
            "dimension": "IP限制",
            "biying": "无限制",
            "gm": "无(但用不了)",
        },
        {
            "dimension": "实时行情",
            "biying": "实时(200次/天免费)",
            "gm": "免费版无",
        },
        {
            "dimension": "涨停股池",
            "biying": "✅(封板资金/连板/炸板次数)",
            "gm": "❌ 无直接API",
        },
        {
            "dimension": "买卖五档",
            "biying": "✅ 批量",
            "gm": "免费版无",
        },
        {
            "dimension": "资金流向",
            "biying": "待确认URL",
            "gm": "免费版无",
        },
        {
            "dimension": "交易接口",
            "biying": "❌ 纯数据",
            "gm": "✅(需终端)",
        },
        {
            "dimension": "费用",
            "biying": "免费/¥688年",
            "gm": "免费(数据少)",
        },
    ]
    return {"success": True, "data": comparison}


# ==================== 券商管理 ====================

@router.get("/brokers")
async def list_brokers():
    """列出所有券商及状态"""
    from nodes.market_monitor.data_source_router import BrokerType

    brokers = [
        {
            "name": "simulated",
            "label": "仿真撮合",
            "type": "simulated",
            "available": True,
            "description": "内存撮合引擎, 开发/测试用",
            "requires": "无",
        },
        {
            "name": "gm_paper",
            "label": "掘金仿真",
            "type": "gm_paper",
            "available": False,
            "description": "掘金量化仿真交易, 需gm3_node终端",
            "requires": "掘金终端 + Token",
        },
        {
            "name": "qmt",
            "label": "QMT实盘",
            "type": "qmt",
            "available": False,
            "description": "券商QMT实盘交易, 需开户+量化权限",
            "requires": "券商开户 + 50万门槛 + QMT权限",
        },
    ]

    return {"success": True, "data": brokers}


# ==================== 必盈API测试 ====================

@router.post("/biying/test")
async def test_biying_api(req: Dict[str, str]):
    """测试必盈API接口"""
    router = _get_router()
    statuses = router.get_all_statuses()

    if "biying" not in statuses or not statuses["biying"].available:
        raise HTTPException(400, "必盈数据源未初始化")

    biying = router._sources.get("biying")
    if not biying:
        raise HTTPException(400, "必盈适配器不存在")

    test_type = req.get("type", "status")

    if test_type == "stock_list":
        data = await biying.get_stock_list()
        return {"success": True, "data": {"count": len(data), "sample": data[:5] if data else []}}

    elif test_type == "limit_up":
        data = await biying.get_limit_up_pool()
        return {"success": True, "data": {"count": len(data), "sample": data[:5] if data else []}}

    elif test_type == "limit_down":
        data = await biying.get_limit_down_pool()
        return {"success": True, "data": {"count": len(data), "sample": data[:5] if data else []}}

    elif test_type == "broken_board":
        data = await biying.get_broken_board_pool()
        return {"success": True, "data": {"count": len(data), "sample": data[:5] if data else []}}

    elif test_type == "realtime":
        ts_code = req.get("ts_code", "000001.SZ")
        data = await biying.get_realtime_quote(ts_code)
        return {"success": True, "data": data}

    elif test_type == "order_book":
        ts_code = req.get("ts_code", "000001.SZ")
        data = await biying.get_order_book(ts_code)
        return {"success": True, "data": data}

    elif test_type == "status":
        return {"success": True, "data": biying.get_status()}

    else:
        raise HTTPException(400, f"未知测试类型: {test_type}")
