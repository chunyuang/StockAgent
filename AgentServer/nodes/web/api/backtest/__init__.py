"""
回测API包

将原backtest.py拆分为模块化结构：
- models.py: Pydantic数据模型
- common.py: 认证辅助、常量、mock存储
- defaults.py: 超短回测默认配置
- ultra_short.py: 超短策略回测路由
- __init__.py: 路由注册与导入（单股回测、因子选股等路由定义在此）
"""

import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional

from fastapi import APIRouter, HTTPException, Query, Depends, Request
from pydantic import ValidationError

from core.managers import mongo_manager
from core.rpc import RPCClient
from ..auth import get_current_user_id
from .common import (
    logger,
    mock_tasks,
    get_optional_user_id,
    _MAX_CONCURRENT_BACKTESTS,
)
from .models import (
    BacktestRequest,
    BacktestTaskResponse,
    FactorSelectionRequest,
    strategy_name_map,
)
from .ultra_short import router as ultra_short_router


# 主路由（单股回测 + 因子选股 + 查询/取消）
router = APIRouter(prefix="/backtest", tags=["Backtest"])

# 合并超短策略路由
router.include_router(ultra_short_router)


# ==================== 单股回测 API ====================


@router.post("/submit", response_model=BacktestTaskResponse)
async def submit_backtest(
    request: BacktestRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    提交回测任务

    任务将通过 RPC 发送到 BacktestNode 异步执行，
    返回 task_id 用于查询进度。

    客户端需要轮询 /status/{task_id} 或 /result/{task_id} 获取结果。
    """
    task_id = f"bt_{uuid.uuid4().hex[:12]}"

    logger.info(f"[{task_id}] Backtest request from user {user_id}: {request.ts_code}")

    # 构建 RPC 参数
    rpc_params = {
        "task_id": task_id,
        "user_id": user_id,
        "ts_code": request.ts_code,
        "stock_name": request.stock_name,
        "start_date": request.start_date,
        "end_date": request.end_date,
        "initial_cash": request.initial_cash,
        "entry_threshold": request.entry_threshold,
        "exit_threshold": request.exit_threshold,
        "position_size": request.position_size,
        "factor_weights": request.factor_weights,
        "auto_technical": request.auto_technical,
    }

    # 通过 RPC 调用 BacktestNode (仅投递任务，不等待执行结果)
    rpc_client = RPCClient()

    try:
        results = await rpc_client.broadcast_by_type(
            node_type="backtest",
            method="run_backtest",
            params=rpc_params,
            timeout=10.0,  # 只等待任务投递确认，不等待执行结果
            source_node="web-node",
        )

        if not results:
            raise HTTPException(
                status_code=503,
                detail="No BacktestNode available. Please ensure backtest node is running."
            )

        # 取第一个响应
        first_result = results[0]

        if not first_result.get("success"):
            error_msg = first_result.get("error", "Unknown error")
            logger.error(f"[{task_id}] RPC failed: {error_msg}")
            raise HTTPException(status_code=500, detail=error_msg)

        rpc_response = first_result.get("result", {})

        return BacktestTaskResponse(
            task_id=task_id,
            status=rpc_response.get("status", "queued"),
            message="任务已提交到回测节点，请使用 task_id 查询进度"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[{task_id}] Failed to submit backtest: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 查询 API ====================


@router.get("/status/{task_id}")
async def get_backtest_status(
    task_id: str,
    user_id: str = Depends(get_optional_user_id),
) -> Dict[str, Any]:
    """查询回测任务状态
    
    【修复：统一从MongoDB读取，mock_tasks仅做临时缓存】
    优先级：MongoDB → mock_tasks（仅临时缓存）
    """
    # 1. 优先查 MongoDB（唯一可信源）
    record = await mongo_manager.find_one(
        "backtest_tasks",
        {"task_id": task_id},
    )

    # 2. 如果MongoDB没有，再查mock_tasks（仅作为临时缓存）
    if not record:
        if task_id in mock_tasks:
            task = mock_tasks[task_id]
            return {
                "success": True,
                "data": {
                    "task_id": task_id,
                    "status": task["status"],
                    "progress": task["progress"],
                    "logs": task["logs"],
                }
            }
        raise HTTPException(status_code=404, detail="任务不存在")

    # 【修复风险5：悬挂任务检测 - running超过10分钟且无新日志才标记failed，避免误杀长时间回测】
    if record.get("status") == "running":
        from datetime import datetime, timedelta, timezone
        started = record.get("started_at") or record.get("created_at")
        logs = record.get("logs", [])
        if started:
            if hasattr(started, 'tzinfo') and started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            elapsed = (datetime.now(timezone.utc) - started).total_seconds()
            # 只有运行超过10分钟 AND 日志少于5条（说明任务可能卡住/崩溃了）才标failed
            # 正常回测即使慢也会持续产出日志
            if elapsed > 600 and len(logs) < 5:
                record["status"] = "failed"
                record["error"] = f"任务超时（运行{int(elapsed/60)}分钟无日志输出），回测节点可能已崩溃"
                await mongo_manager.update_one(
                    "backtest_tasks",
                    {"task_id": task_id},
                    {"$set": {"status": "failed", "error": record["error"]}}
                )

    # 权限检查 (如果记录中有 user_id)
    if record.get("params", {}).get("user_id") and record["params"]["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="无权访问此任务")

    return {
        "success": True,
        "data": {
            "task_id": task_id,
            "status": record.get("status"),
            "progress": record.get("progress", 0),
            "logs": record.get("logs", []),
            "created_at": record.get("created_at", "").isoformat() if record.get("created_at") else None,
            "started_at": record.get("started_at", "").isoformat() if record.get("started_at") else None,
            "completed_at": record.get("completed_at", "").isoformat() if record.get("completed_at") else None,
            "error": record.get("error"),
        }
    }


@router.get("/result/{task_id}")
async def get_backtest_result(
    task_id: str,
    user_id: str = Depends(get_optional_user_id),
) -> Dict[str, Any]:
    """获取回测结果，仅当任务完成后可获取。"""
    # 先查Mock任务
    if task_id.startswith("us_") and task_id in mock_tasks:
        task = mock_tasks[task_id]
        if task["status"] != "completed":
            return {
                "success": True,
                "data": {
                    "task_id": task_id,
                    "status": task["status"],
                    "message": "任务执行中"
                }
            }
        return {
            "success": True,
            "data": {
                "task_id": task_id,
                "status": "completed",
                "result": task["result"],
            }
        }

    record = await mongo_manager.find_one(
        "backtest_tasks",
        {"task_id": task_id},
    )

    if not record:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 权限检查
    if record.get("params", {}).get("user_id") and record["params"]["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="无权访问此任务")

    status = record.get("status")

    if status == "pending" or status == "queued":
        return {
            "success": True,
            "data": {
                "task_id": task_id,
                "status": status,
                "message": "任务等待中"
            }
        }

    if status == "running":
        return {
            "success": True,
            "data": {
                "task_id": task_id,
                "status": "running",
                "message": "任务执行中"
            }
        }

    if status == "failed":
        return {
            "success": True,
            "data": {
                "task_id": task_id,
                "status": "failed",
                "error": record.get("error", "Unknown error"),
            }
        }

    if status == "cancelled":
        return {
            "success": True,
            "data": {
                "task_id": task_id,
                "status": "cancelled",
                "message": "任务已取消"
            }
        }

    return {
        "success": True,
        "data": {
            "task_id": task_id,
            "status": "completed",
            "result": record.get("result"),
        }
    }


@router.get("/history")
async def get_backtest_history(
    user_id: str = Depends(get_current_user_id),
    task_type: Optional[str] = Query(default=None, description="任务类型: single/factor_selection"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> Dict[str, Any]:
    """获取用户的回测历史"""
    query: Dict[str, Any] = {"params.user_id": user_id, "status": "completed"}

    # 根据任务类型筛选 (task_type 存储在顶层)
    if task_type == "single":
        query["$or"] = [
            {"task_type": {"$exists": False}},
            {"task_type": {"$ne": "factor_selection"}},
        ]
    elif task_type == "factor_selection":
        query["task_type"] = "factor_selection"

    records = await mongo_manager.find_many(
        "backtest_tasks",
        query,
        sort=[("created_at", -1)],
        skip=offset,
        limit=limit,
    )

    # 简化返回数据
    items = []
    for r in records:
        result = r.get("result", {})
        metrics = result.get("metrics", {})
        params = r.get("params", {})
        task_type_val = params.get("task_type", "single")

        item = {
            "task_id": r.get("task_id"),
            "task_type": task_type_val,
            "start_date": params.get("start_date"),
            "end_date": params.get("end_date"),
            "created_at": r.get("created_at", "").isoformat() if r.get("created_at") else None,
        }

        if task_type_val == "factor_selection":
            performance = result.get("performance", {})
            item.update({
                "top_n": params.get("top_n"),
                "rebalance_freq": params.get("rebalance_freq"),
                "factors_count": len(params.get("factors", [])),
                "total_return_pct": performance.get("total_return"),
                "sharpe_ratio": performance.get("sharpe_ratio"),
                "max_drawdown_pct": performance.get("max_drawdown"),
                "excess_return_pct": performance.get("excess_return"),
            })
        else:
            item.update({
                "ts_code": params.get("ts_code"),
                "stock_name": params.get("stock_name"),
                "total_return_pct": metrics.get("returns", {}).get("total_return_pct"),
                "sharpe_ratio": metrics.get("risk", {}).get("sharpe_ratio"),
                "max_drawdown_pct": metrics.get("risk", {}).get("max_drawdown_pct"),
            })

        items.append(item)

    return {
        "total": len(items),
        "items": items,
    }


@router.delete("/{task_id}")
async def cancel_backtest(
    task_id: str,
    user_id: str = Depends(get_optional_user_id),
) -> Dict[str, Any]:
    """取消回测任务"""
    # 先处理Mock超短回测任务
    if task_id.startswith("us_") and task_id in mock_tasks:
        mock_tasks[task_id]["status"] = "cancelled"
        mock_tasks[task_id]["logs"].append("⏹️ 用户手动取消回测")
        return {"task_id": task_id, "status": "cancelled", "message": "任务已取消"}

    # 查 MongoDB
    record = await mongo_manager.find_one(
        "backtest_tasks",
        {"task_id": task_id},
    )

    if not record:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 权限检查
    if record.get("params", {}).get("user_id") and record["params"]["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="无权操作此任务")

    status = record.get("status")
    if status not in ["pending", "queued", "running"]:
        raise HTTPException(
            status_code=400,
            detail=f"任务状态为 {status}，无法取消"
        )

    # 通过 RPC 取消任务
    rpc_client = RPCClient()

    try:
        results = await rpc_client.broadcast_by_type(
            node_type="backtest",
            method="cancel_task",
            params={"task_id": task_id},
            timeout=10.0,
            source_node="web-node",
        )

        if results and results[0].get("success"):
            return {"task_id": task_id, "status": "cancelled", "message": "任务已取消"}

    except Exception as e:
        logger.warning(f"Failed to cancel task via RPC: {e}")

    # 直接更新数据库
    await mongo_manager.update_one(
        "backtest_tasks",
        {"task_id": task_id},
        {"$set": {"status": "cancelled", "cancelled_at": datetime.now(timezone.utc)}},
    )

    return {"task_id": task_id, "status": "cancelled", "message": "任务已取消"}


# ==================== 因子选股回测 API ====================


@router.get("/factors")
async def list_available_factors() -> Dict[str, Any]:
    """获取可用的因子列表"""
    from nodes.backtest_engine.factor_selection.factor_library import FACTOR_DEFS

    # 按分类分组
    grouped = {}
    factors = FACTOR_DEFS
    for f in factors:
        category = f["category"]
        if category not in grouped:
            grouped[category] = []
        grouped[category].append(f)

    return {
        "factors": factors,
        "grouped": grouped,
    }


@router.post("/factor-selection", response_model=BacktestTaskResponse)
async def submit_factor_selection_backtest(
    raw_request: Request,
    user_id: str = Depends(get_current_user_id),
):
    """提交因子选股回测任务"""
    # 解析请求体并验证
    try:
        body = await raw_request.json()
        logger.info(f"Factor selection request body: {body}")
        request = FactorSelectionRequest(**body)
    except ValidationError as e:
        logger.error(f"Validation error: {e.errors()}")
        raise HTTPException(status_code=422, detail=e.errors())

    task_id = f"fs_{uuid.uuid4().hex[:12]}"

    logger.info(
        f"[{task_id}] Factor selection backtest from user {user_id}: "
        f"{request.start_date} ~ {request.end_date}, {len(request.factors)} factors"
    )

    # 构建 RPC 参数
    rpc_params = {
        "task_id": task_id,
        "user_id": user_id,
        "universe": request.universe,
        "start_date": request.start_date,
        "end_date": request.end_date,
        "initial_cash": request.initial_cash,
        "rebalance_freq": request.rebalance_freq,
        "top_n": request.top_n,
        "weight_method": request.weight_method,
        "factors": [f.model_dump() for f in request.factors],
        "exclude": request.exclude,
        "benchmark": request.benchmark,
    }

    # 通过 RPC 调用 BacktestNode
    rpc_client = RPCClient()

    try:
        results = await rpc_client.broadcast_by_type(
            node_type="backtest",
            method="run_factor_selection",
            params=rpc_params,
            timeout=10.0,
            source_node="web-node",
        )

        if not results:
            raise HTTPException(
                status_code=503,
                detail="No BacktestNode available. Please ensure backtest node is running."
            )

        first_result = results[0]

        if not first_result.get("success"):
            error_msg = first_result.get("error", "Unknown error")
            logger.error(f"[{task_id}] RPC failed: {error_msg}")
            raise HTTPException(status_code=500, detail=error_msg)

        rpc_response = first_result.get("result", {})

        return BacktestTaskResponse(
            task_id=task_id,
            status=rpc_response.get("status", "queued"),
            message="因子选股回测任务已提交，请使用 task_id 查询进度"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[{task_id}] Failed to submit factor selection: {e}")
        raise HTTPException(status_code=500, detail=str(e))
