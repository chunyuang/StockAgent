"""
超短策略回测API路由

包含超短策略回测提交、默认配置获取等端点。
"""

import json
import uuid
import copy
from datetime import datetime
from bson import ObjectId

from fastapi import APIRouter, HTTPException, Request, Depends, Query
from pydantic import ValidationError

from core.managers import mongo_manager
from core.rpc import RPCClient
from ..auth import get_current_user_id
from .common import (
    logger,
    mock_tasks,
    get_optional_user_id,
    oauth2_scheme_optional,
)
from .models import (
    BacktestTaskResponse,
    UltraShortBacktestRequest,
    strategy_name_map,
    strategy_name_map_reverse,
)
from .defaults import get_ultra_short_defaults


router = APIRouter(tags=["UltraShort"])  # 不设prefix，由父router提供/backtest前缀


@router.post("/ultra-short", response_model=BacktestTaskResponse)
async def submit_ultra_short_backtest(
    raw_request: Request,
    user_id: str = Depends(get_optional_user_id),
):
    """
    提交超短策略回测任务
    支持5大超短策略：半路追涨、首板打板、涨停开板、龙头低吸、跌停翘板
    全市场回测，支持实时进度推送和完整结果分析
    返回 task_id 用于查询进度和结果。
    """
    # 手动解析请求体，捕获详细验证错误
    try:
        body = await raw_request.json()
        logger.info(f"[{uuid.uuid4().hex[:8]}] Ultra short request body: {body}")
        request = UltraShortBacktestRequest(**body)
    except ValidationError as e:
        logger.error(f"Validation error for ultra-short request: {e.errors()}")
        raise HTTPException(status_code=422, detail=e.errors())

    task_id = f"us_{uuid.uuid4().hex[:12]}"

    logger.info(
        f"[{task_id}] Ultra short backtest from user {user_id}: "
        f"strategies={request.strategies}, {request.start_date} ~ {request.end_date}"
    )

    # 构建选中策略列表：100%原封不动使用前端提交的selected_strategies，不做任何修改
    selected_strategies = []
    # 【修复】优先从请求顶层读selected_strategies，再从params读
    selected_from_top = getattr(request, 'selected_strategies', None)
    selected_from_params = getattr(request.params, 'selected_strategies', None)
    if selected_from_top and len(selected_from_top) > 0:
        selected_strategies = selected_from_top
    elif selected_from_params and len(selected_from_params) > 0:
        # 兼容前端将selected_strategies放在params内的情况
        selected_strategies = selected_from_params
    else:
        # 如果前端没有提交selected_strategies，从strategies字段读取，参数为空
        for s in request.strategies:
            selected_strategies.append({
                "id": s,
                "name": strategy_name_map_reverse.get(s, s),
                "params": {}
            })

    # 终极方案1：递归遍历整个字典，将所有 datetime/date/ObjectId 对象转换为字符串
    from datetime import date as datetime_date
    def convert_datetime_to_str(obj):
        if isinstance(obj, (datetime, datetime_date)):
            return obj.strftime('%Y%m%d')
        elif isinstance(obj, ObjectId):
            return str(obj)
        elif isinstance(obj, dict):
            return {k: convert_datetime_to_str(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_datetime_to_str(item) for item in obj]
        else:
            return obj

    # 终极方案2：自定义 JSON encoder，遇到 datetime/date/ObjectId 自动转换
    # 三重防护，不管 datetime/date/ObjectId 藏在哪里，json.dumps 都会自动转换，绝对不会出错
    class DateTimeEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, (datetime, datetime_date)):
                return obj.strftime('%Y%m%d')
            if isinstance(obj, ObjectId):
                return str(obj)
            return super().default(obj)

    # 构建初始 task_info
    task_info = {
        "task_id": task_id,
        "params": {
            "strategies": request.strategies,
            "start_date": request.start_date,
            "end_date": request.end_date,
            "initial_cash": request.initial_cash,
            "params": {
                "liquidity_threshold": request.params.liquidity_threshold,
                "volume_threshold": request.params.volume_threshold,
                "stop_loss_pct": request.params.stop_loss_pct,
                "take_profit_pct": request.params.take_profit_pct,
                "max_hold_days": request.params.max_hold_days,
                "max_position_per_stock": request.params.max_position_per_stock,
                "max_position": request.params.max_position,
                "commission_rate": request.params.commission_rate,
                "stamp_duty_rate": request.params.stamp_duty_rate,
                "slippage_pct": request.params.slippage_pct,
                "enable_force_empty": request.params.enable_force_empty,
                "sentiment_cycle": request.params.sentiment_cycle,
                "auction_filter": request.params.auction_filter,
                "enable_stop_loss": request.params.enable_stop_loss,
                "enable_take_profit": request.params.enable_take_profit,
                "enable_ma60_filter": request.params.enable_ma60_filter,
                "enable_sector_concentration": request.params.enable_sector_concentration,
                "selected_strategies": selected_strategies,
            },
            "enable_force_empty": request.params.enable_force_empty,
            "enable_sentiment_cycle": request.params.sentiment_cycle,
            "enable_auction_filter": request.params.auction_filter,
            "enable_stop_loss": request.params.enable_stop_loss,
            "enable_take_profit": request.params.enable_take_profit,
            "enable_ma60_filter": request.params.enable_ma60_filter,
            "enable_sector_concentration": request.params.enable_sector_concentration,
            "selected_strategies": selected_strategies
        }
    }

    # 递归转换所有 datetime/date 对象到字符串，双重防护确保序列化成功
    task_info = convert_datetime_to_str(task_info)

    # 【修复：日志只走一条路】
    # - Web层不再预生成日志，所有日志统一由回测引擎 push_log 推送
    # - mock_tasks 仅用于临时缓存，status接口优先从MongoDB读取
    # - 删除虚假"WebSocket已连接"日志
    # - 参数日志只在回测引擎打印一次
    mock_tasks[task_id] = {
        "task_id": task_id,
        "status": "queued",
        "progress": 0,
        "result": None
    }

    # 保存任务信息到MongoDB（注意：MongoDB会原地修改task_info，添加_id: ObjectId(...)）
    # 所以在保存到MongoDB之前，先深拷贝一份用于后续的RPC序列化，避免ObjectId导致序列化失败
    task_info_for_rpc = copy.deepcopy(task_info)
    await mongo_manager.insert_one("backtest_tasks", task_info)

    # ====== 修复：使用broadcast_by_type替代不存在的call_submit_ultra_short ======
    # 原BUG：RPCClient(backtest_host, backtest_port) 传参错误(TypeError)
    #       + call_submit_ultra_short() 方法不存在(AttributeError)
    #       + RPC失败时谎报status="running"
    # 修复：RPCClient()无参构造 + broadcast_by_type + 失败抛HTTPException
    rpc_client = RPCClient()

    try:
        # 问题根源：
        # 1. broadcast_by_type 内部添加 timestamp (datetime 对象) 导致 JSON 序列化失败
        # 2. MongoDB insert_one 会原地修改 task_info，添加 _id: ObjectId(...)，导致无法序列化
        # 解决方案：
        # 1. 使用深拷贝的 task_info_for_rpc，避免 MongoDB 修改影响
        # 2. 自定义 DateTimeEncoder 同时处理 datetime 和 ObjectId
        # 3. 手动 JSON dump/load 预序列化，双重转换所有对象为可序列化类型
        task_info_str = json.dumps(task_info_for_rpc, cls=DateTimeEncoder)
        task_info_serialized = json.loads(task_info_str)
        
        results = await rpc_client.broadcast_by_type(
            node_type="backtest",
            method="run_ultra_short_backtest",
            params=task_info_serialized,
            timeout=60.0,  # 【修复#30】RPC超时从10s增加到60s，避免大数据量投递超时
            source_node="web-node",
        )

        if not results:
            # 【修复#3：mock_logs格式统一，改成直接传空数组，真实日志由node统一格式
            # 无可用回测节点 — 致命错误，抛503而非谎报running
            mock_tasks[task_id] = {
                "task_id": task_id,
                "status": "failed",
                "progress": 0,
                "result": None
            }
            raise HTTPException(
                status_code=503,
                detail="No BacktestNode available. Please ensure backtest node is running."
            )

        # 问题根源：broadcast_by_type 返回的结果中包含 datetime 对象，无法 JSON 序列化
        # 手动提取可序列化字段，丢弃原始结果
        success = False
        error_msg = "Unknown error"
        if len(results) > 0:
            first_result = results[0]
            if isinstance(first_result, dict):
                success = bool(first_result.get("success", False))
                if "error" in first_result:
                    error_msg = str(first_result["error"])
        
        # 删除完整引用避免意外携带 datetime 对象
        del results
        
        if not success:
            logger.error(f"[{task_id}] RPC failed: {error_msg}")
            # 【修复#3：mock_logs格式统一，改成直接传空数组，真实日志由node统一格式
            mock_tasks[task_id] = {
                "task_id": task_id,
                "status": "failed",
                "progress": 0,
                "result": None
            }
            # 【修复#1：mock_tasks 任务完成删除残留，避免内存泄漏】
            del mock_tasks[task_id]
            raise HTTPException(status_code=500, detail=error_msg)

        logger.info(f"[{task_id}] 任务已成功投递到RPC回测节点")
        # 【修复#3：mock_logs格式统一，改成直接传空数组，真实日志由node统一格式
        mock_tasks[task_id] = {
            "task_id": task_id,
            "status": "running",
            "progress": 10,
            "result": None
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[{task_id}] RPC投递异常: {e}")
        error_msg = str(e)
        # 【修复#3：mock_logs格式统一，改成直接传空数组，真实日志由node统一格式
        mock_tasks[task_id] = {
            "task_id": task_id,
            "status": "failed",
            "progress": 0,
            "result": None
        }
        # 【修复#1：mock_tasks 任务完成删除残留，避免内存泄漏】
        del mock_tasks[task_id]
        raise HTTPException(status_code=500, detail=error_msg)

    return BacktestTaskResponse(
        task_id=task_id,
        status="running",
        message="回测任务提交成功，正在执行"
    )


@router.get("/ultra-short/defaults")
async def get_ultra_short_defaults_endpoint(
    user_id: str = Depends(get_optional_user_id),
):
    """
    获取超短回测页面的默认初始配置

    从环境变量/.env读取配置，返回给前端用于初始化表单。
    这样修改.env就能改变前端默认值，不需要重新编译前端代码。
    """
    defaults = get_ultra_short_defaults()
    return {
        "success": True,
        "data": defaults
    }


@router.get("/ultra-short/history")
async def get_ultra_short_history(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str = Query(default=None, description="状态筛选: completed/failed"),
):
    """获取超短策略回测历史列表"""
    query: dict = {"task_type": "ultra_short"}
    if status:
        query["status"] = status
    else:
        query["status"] = {"$in": ["completed", "failed"]}

    total = await mongo_manager.count_documents("backtest_tasks", query)
    records = await mongo_manager.find_many(
        "backtest_tasks",
        query,
        sort=[("created_at", -1)],
        skip=offset,
        limit=limit,
        projection={
            "task_id": 1, "status": 1, "created_at": 1, "completed_at": 1,
            "started_at": 1, "params": 1, "result.total_return": 1,
            "result.win_rate": 1, "result.sharpe_ratio": 1, "result.max_drawdown": 1,
            "result.total_signals": 1, "result.completed_trades": 1,
            "result.initial_cash": 1, "result.final_value": 1,
            "result.trades": 1,
        },
    )

    items = []
    for r in records:
        result = r.get("result", {})
        params = r.get("params", {})
        inner_params = params.get("params", {})  # 嵌套: params.params
        item = {
            "task_id": r.get("task_id"),
            "status": r.get("status"),
            "created_at": r.get("created_at", "").isoformat() if r.get("created_at") else None,
            "completed_at": r.get("completed_at", "").isoformat() if r.get("completed_at") else None,
            "started_at": r.get("started_at", "").isoformat() if r.get("started_at") else None,
            # 参数(从内层params取)
            "start_date": inner_params.get("start_date"),
            "end_date": inner_params.get("end_date"),
            "initial_cash": inner_params.get("initial_cash", 1000000),
            "strategies": inner_params.get("strategies", []),
            "strategy_params": inner_params.get("strategy_params", {}),
            # 结果
            "total_return": result.get("total_return"),
            "win_rate": result.get("win_rate"),
            "sharpe_ratio": result.get("sharpe_ratio"),
            "max_drawdown": result.get("max_drawdown"),
            "total_signals": result.get("total_signals"),
            "completed_trades": result.get("completed_trades"),
            "initial_cash_result": result.get("initial_cash"),
            "final_value": result.get("final_value"),
            "trades_count": len(result.get("trades", [])),
        }
        items.append(item)

    return {
        "total": total,
        "items": items,
    }
