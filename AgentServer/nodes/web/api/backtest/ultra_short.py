"""
超短策略回测API路由

包含超短策略回测提交、默认配置获取等端点。
"""

import json
import uuid
import copy
import time
from datetime import datetime
from bson import ObjectId

from fastapi import APIRouter, HTTPException, Request, Depends, Query
from pydantic import ValidationError

from core.managers import mongo_manager
from ..auth import get_current_user_id
from .common import (
    logger,
    mock_tasks,
    get_optional_user_id,
    oauth2_scheme_optional,
    cleanup_expired_mock_tasks,
)
from .models import (
    BacktestTaskResponse,
    UltraShortBacktestRequest,
    strategy_name_map,
    strategy_name_map_reverse,
)
from .defaults import get_ultra_short_defaults
from nodes.backtest_engine.validation.backtest_validator import BacktestValidator
from nodes.backtest_engine.node import BacktestNode
import asyncio


router = APIRouter(tags=["UltraShort"])  # 不设prefix，由父router提供/backtest前缀

# 本地回测引擎实例（不启动RPC服务，仅用于执行回测逻辑）
_backtest_node = BacktestNode()


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
        logger.info(f"[{uuid.uuid4().hex[:8]}] 超短回测请求体: {body}")
        request = UltraShortBacktestRequest(**body)
    except ValidationError as e:
        logger.error(f"超短回测请求校验失败: {e.errors()}")
        # 将Pydantic英文错误翻译为中文
        cn_errors = []
        for err in e.errors():
            field = '.'.join(str(loc) for loc in err.get('loc', []))
            msg = err.get('msg', '')
            # 常见字段翻译
            field_cn = {
                'strategies': '策略列表', 'start_date': '开始日期', 'end_date': '结束日期',
                'initial_cash': '初始资金', 'params.stop_loss_pct': '止损比例',
                'params.take_profit_pct': '止盈比例', 'params.max_hold_days': '最大持仓天数',
                'params.max_position_per_stock': '单票最大仓位', 'params.max_position': '总仓位上限',
                'params.liquidity_threshold': '流动性门槛', 'params.volume_threshold': '量能阈值',
                'params.commission_rate': '佣金率', 'params.stamp_duty_rate': '印花税率',
                'params.slippage_pct': '滑点比例',
            }.get(field, field)
            cn_errors.append({"field": field, "field_cn": field_cn, "message": msg})
        raise HTTPException(status_code=422, detail={"message": "参数校验失败", "errors": cn_errors})

    task_id = f"us_{uuid.uuid4().hex[:12]}"

    logger.info(
        f"[{task_id}] Ultra short backtest from user {user_id}: "
        f"strategies={request.strategies}, {request.start_date} ~ {request.end_date}"
    )

    # 【P3-36优化：参数校验，防止异常输入】
    validator = BacktestValidator()
    request_dict = request.dict()
    is_valid, validation_errors = validator.validate_backtest_request(request_dict)
    
    if not is_valid:
        error_summary = validator.get_error_summary(validation_errors)
        logger.error(f"[{task_id}] 参数校验失败:\n{error_summary}")
        raise HTTPException(
            status_code=400,
            detail={
                "message": "参数校验失败",
                "errors": [{"field": e.field, "message": e.message, "value": str(e.value)} for e in validation_errors]
            }
        )
    
    logger.info(f"[{task_id}] ✅ 参数校验通过")

    # 构建选中策略列表：100%原封不动使用前端提交的selected_strategies，不做任何修改
    selected_strategies = []
    # 【P1-2修复：selected_strategies读取统一为单一来源】
    # 优先级：1.顶层selected_strategies → 2.params内selected_strategies → 3.从strategies构建
    selected_strategies = []
    selected_from_top = getattr(request, 'selected_strategies', None)
    selected_from_params = getattr(request.params, 'selected_strategies', None)
    
    if selected_from_top and len(selected_from_top) > 0:
        selected_strategies = selected_from_top
    elif selected_from_params and len(selected_from_params) > 0:
        selected_strategies = selected_from_params
    else:
        # 兜底：从strategies字段构建空参数策略列表
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
    # 【P2-4文档化：参数嵌套规范】
    # task_info.params.params = 前端params字段(流动性/止损/止盈/佣金等全局参数)
    # task_info.params = 顶层参数(策略/日期/开关/selected_strategies等)
    # 引擎侧 ultra_short.py 通过 req_params=params.params 读取全局参数
    # 引擎侧 portfolio_backtest.py 通过 config 读取所有参数(合并flatten)
    #
    # 【P1-3/P1-4修复：透传forceEmpty/sentimentCycle/auctionFilter/globalFilter细粒度参数】
    # 提取前端细粒度配置（从前端提交的原始body中读取，不经过Pydantic过滤）
    force_empty_config = body.get("forceEmpty", {})
    sentiment_cycle_config = body.get("sentimentCycle", {})
    auction_filter_config = body.get("auctionFilter", {})
    global_filter_config = body.get("globalFilter", {})

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
                "enable_force_empty": request.enable_force_empty,
                "sentiment_cycle": request.params.sentiment_cycle,
                "auction_filter": request.params.auction_filter,
                "enable_stop_loss": request.params.enable_stop_loss,
                "enable_take_profit": request.params.enable_take_profit,
                "enable_ma60_filter": request.params.enable_ma60_filter,
                "enable_sector_concentration": request.params.enable_sector_concentration,
                "selected_strategies": selected_strategies,
                # 【P1-3修复】透传强制空仓细粒度阈值
                "force_empty_config": {
                    "limit_down_count": force_empty_config.get("limit_down_count", 50),
                    "limit_up_count": force_empty_config.get("limit_up_count", 10),
                    "index_drop_pct": force_empty_config.get("index_drop_pct", 0.02),
                } if force_empty_config.get("enabled", True) else {},
                # 【P1-4修复】透传全局筛选细粒度参数
                "global_filter_config": {
                    "exclude_st": global_filter_config.get("exclude_st", True),
                    "exclude_delisting": global_filter_config.get("exclude_delisting", True),
                    "exclude_new_stock_days": global_filter_config.get("exclude_new_stock_days", 60),
                    "min_turnover_rate": global_filter_config.get("min_turnover_rate", 1.5),
                },
            },
            "enable_force_empty": request.enable_force_empty,
            "enable_sentiment_cycle": request.enable_sentiment_cycle,
            "enable_auction_filter": request.enable_auction_filter,
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
    # 【N03修复：写入前先清理过期缓存】
    cleanup_expired_mock_tasks()
    mock_tasks[task_id] = {
        "task_id": task_id,
        "status": "queued",
        "progress": 0,
        "result": None,
        "_created_at": time.time(),  # 【P2-3修复：添加TTL时间戳】
    }

    # 保存任务信息到MongoDB
    task_info_with_type = copy.deepcopy(task_info)
    task_info_with_type["task_type"] = "ultra_short"  # 【P1-1修复：写入task_type，ultra-short/history查询依赖此字段】
    await mongo_manager.insert_one("backtest_tasks", task_info_with_type)

    # ====== 本地异步执行（不依赖RPC，不需要独立backtest节点）======
    # 历史问题：RPC方式需要额外启动backtest节点，序列化datetime/ObjectId容易出错
    # 恢复4月11日用户验证OK的本地执行方案
    mock_tasks[task_id]["status"] = "running"
    mock_tasks[task_id]["progress"] = 5

    async def run_backtest_async():
        """本地异步执行回测逻辑"""
        try:
            logger.info(f"[{task_id}] 开始本地执行回测逻辑")

            # 执行真实回测（直接调用回测引擎核心函数）
            from nodes.backtest_engine.ultra_short import execute_ultra_short_backtest
            result = await execute_ultra_short_backtest(task_info, _backtest_node._push_log, _backtest_node.logger, task_id)

            # 更新mock_tasks
            if task_id in mock_tasks:
                mock_tasks[task_id]["status"] = "completed"
                mock_tasks[task_id]["progress"] = 100
                mock_tasks[task_id]["result"] = result

            # 写回MongoDB
            try:
                await mongo_manager.update_one(
                    "backtest_tasks",
                    {"task_id": task_id},
                    {"$set": {"status": "completed", "progress": 100, "result": result, "completed_at": datetime.utcnow()}}
                )
            except Exception as e:
                logger.warning(f"[{task_id}] 写回MongoDB失败: {e}")

            # 推送完成消息到前端
            try:
                from nodes.web.websocket import manager as ws_manager
                await ws_manager.broadcast_task_update(task_id, {
                    "type": "status",
                    "status": "completed",
                    "result": result
                })
            except Exception:
                pass

            logger.info(f"[{task_id}] 回测执行完成")

        except Exception as e:
            logger.exception(f"[{task_id}] 回测执行失败: {e}")
            if task_id in mock_tasks:
                mock_tasks[task_id]["status"] = "failed"
                mock_tasks[task_id]["progress"] = 100  # 失败也是终态，进度应为100
            try:
                await mongo_manager.update_one(
                    "backtest_tasks",
                    {"task_id": task_id},
                    {"$set": {"status": "failed", "error": str(e), "completed_at": datetime.utcnow()}}
                )
            except Exception:
                pass
            try:
                from nodes.web.websocket import manager as ws_manager
                await ws_manager.broadcast_task_update(task_id, {
                    "type": "status",
                    "status": "failed",
                    "error": str(e)
                })
            except Exception:
                pass

    # 启动异步回测任务（不阻塞HTTP请求）
    asyncio.create_task(run_backtest_async())

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
            "result.total_trades": 1, "result.profit_loss_ratio": 1,
            "result.initial_cash": 1, "result.final_value": 1,
            "result.trades": 1, "result.merged_trades": 1,
            # 【P2-4修复：添加嵌套字段projection】
            "result.performance": 1, "result.strategies": 1,
            "result.summary": 1, "result.charts": 1,
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
            # 参数: start_date/strategies/initial_cash在params顶层, 风控在内层
            "start_date": params.get("start_date") or inner_params.get("start_date"),
            "end_date": params.get("end_date") or inner_params.get("end_date"),
            "initial_cash": params.get("initial_cash") or inner_params.get("initial_cash", 1000000),
            "strategies": params.get("strategies") or inner_params.get("strategies", []),
            "strategy_params": inner_params,
            # 结果
            "total_return": result.get("total_return"),
            "win_rate": result.get("win_rate"),
            "sharpe_ratio": result.get("sharpe_ratio"),
            "max_drawdown": result.get("max_drawdown"),
            "total_signals": result.get("total_signals"),
            "profit_loss_ratio": result.get("profit_loss_ratio"),
            "completed_trades": result.get("completed_trades"),
            "initial_cash_result": result.get("initial_cash"),
            "final_value": result.get("final_value"),
            "trades_count": result.get("total_trades") or len(result.get("merged_trades", [])) or len(result.get("trades", [])),
        }
        items.append(item)

    return {
        "total": total,
        "items": items,
    }


@router.post("/ultra-short/sweep")
async def submit_sweep_backtest(raw_request: Request, user_id: str = Depends(get_optional_user_id)):
    """
    参数敏感性扫描回测
    
    对指定参数在给定范围内进行扫描，每组参数执行一次回测，汇总结果对比。
    """
    try:
        body = await raw_request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求体格式错误")

    # 提取sweep参数
    sweep_param = body.pop("sweep_param", None)
    sweep_start = body.pop("sweep_start", None)
    sweep_end = body.pop("sweep_end", None)
    sweep_step = body.pop("sweep_step", None)

    if not sweep_param:
        raise HTTPException(status_code=400, detail="缺少扫描参数(sweep_param)")
    if sweep_start is None or sweep_end is None or sweep_step is None:
        raise HTTPException(status_code=400, detail="扫描起始值/结束值/步长均为必填")

    try:
        sweep_start = float(sweep_start)
        sweep_end = float(sweep_end)
        sweep_step = float(sweep_step)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="扫描起始值/结束值/步长必须为数值")

    if sweep_step == 0:
        raise HTTPException(status_code=400, detail="扫描步长不能为0")

    # 生成扫描值列表(用整数步数避免浮点累加精度问题)
    sweep_values = []
    if sweep_step > 0:
        n = int(round((sweep_end - sweep_start) / sweep_step)) + 1
        sweep_values = [round(sweep_start + i * sweep_step, 10) for i in range(n)]
    else:
        n = int(round((sweep_start - sweep_end) / (-sweep_step))) + 1
        sweep_values = [round(sweep_start + i * sweep_step, 10) for i in range(n)]

    if not sweep_values:
        raise HTTPException(status_code=400, detail="扫描参数范围无效(检查start/end/step)")

    if len(sweep_values) > 50:
        raise HTTPException(status_code=400, detail=f"扫描值过多({len(sweep_values)}个)，最多50个")

    logger.info(f"[sweep] param={sweep_param}, values={sweep_values}, user={user_id}")

    # 解析基础请求参数（和ultra-short相同的验证流程）
    try:
        request = UltraShortBacktestRequest(**body)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail={"message": "参数校验失败", "errors": [{"field": str(err['loc']), "message": err['msg']} for err in e.errors()]})

    # ---- \u6784\u5efa\u57fa\u7840task_info\uff08\u590d\u7528submit_ultra_short_backtest\u7684\u903b\u8f91\uff09----
    selected_strategies = []
    selected_from_top = getattr(request, 'selected_strategies', None)
    selected_from_params = getattr(request.params, 'selected_strategies', None)
    if selected_from_top and len(selected_from_top) > 0:
        selected_strategies = selected_from_top
    elif selected_from_params and len(selected_from_params) > 0:
        selected_strategies = selected_from_params
    else:
        for s in request.strategies:
            selected_strategies.append({
                "id": s,
                "name": strategy_name_map_reverse.get(s, s),
                "params": {}
            })

    force_empty_config = body.get("forceEmpty", {})
    global_filter_config = body.get("globalFilter", {})

    base_task_info = {
        "task_id": "",  # 会被每组覆盖
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
                "enable_force_empty": request.enable_force_empty,
                "sentiment_cycle": request.params.sentiment_cycle,
                "auction_filter": request.params.auction_filter,
                "enable_stop_loss": request.params.enable_stop_loss,
                "enable_take_profit": request.params.enable_take_profit,
                "enable_ma60_filter": request.params.enable_ma60_filter,
                "enable_sector_concentration": request.params.enable_sector_concentration,
                "selected_strategies": copy.deepcopy(selected_strategies),
                "force_empty_config": {
                    "limit_down_count": force_empty_config.get("limit_down_count", 50),
                    "limit_up_count": force_empty_config.get("limit_up_count", 10),
                    "index_drop_pct": force_empty_config.get("index_drop_pct", 0.02),
                } if force_empty_config.get("enabled", True) else {},
                "global_filter_config": {
                    "exclude_st": global_filter_config.get("exclude_st", True),
                    "exclude_delisting": global_filter_config.get("exclude_delisting", True),
                    "exclude_new_stock_days": global_filter_config.get("exclude_new_stock_days", 60),
                    "min_turnover_rate": global_filter_config.get("min_turnover_rate", 1.5),
                },
            },
            "enable_force_empty": request.enable_force_empty,
            "enable_sentiment_cycle": request.enable_sentiment_cycle,
            "enable_auction_filter": request.enable_auction_filter,
            "enable_stop_loss": request.params.enable_stop_loss,
            "enable_take_profit": request.params.enable_take_profit,
            "enable_ma60_filter": request.params.enable_ma60_filter,
            "enable_sector_concentration": request.params.enable_sector_concentration,
            "selected_strategies": copy.deepcopy(selected_strategies),
        }
    }

    # ---- 参数映射：根据sweep_param修改对应位置 ----
    def apply_sweep_param(task_info: dict, param_name: str, value: float) -> dict:
        """将sweep参数值应用到task_info的对应位置，返回修改后的副本"""
        info = copy.deepcopy(task_info)
        inner_params = info["params"]["params"]
        sel_strats = info["params"].get("selected_strategies", [])
        inner_sel_strats = inner_params.get("selected_strategies", [])

        if param_name == "stop_loss_pct":
            inner_params["stop_loss_pct"] = value
            # 同步到每个策略的riskParams
            for s in sel_strats:
                s.setdefault("riskParams", {})["stop_loss_pct"] = value
            for s in inner_sel_strats:
                s.setdefault("riskParams", {})["stop_loss_pct"] = value
        elif param_name == "take_profit_pct":
            inner_params["take_profit_pct"] = value
            for s in sel_strats:
                s.setdefault("riskParams", {})["take_profit_pct"] = value
            for s in inner_sel_strats:
                s.setdefault("riskParams", {})["take_profit_pct"] = value
        elif param_name == "max_hold_days":
            inner_params["max_hold_days"] = int(value)
        elif param_name == "max_position_per_stock":
            inner_params["max_position_per_stock"] = value
        elif param_name == "max_position":
            inner_params["max_position"] = value
        elif param_name == "min_rise_pct":
            # 修改halfway_chase策略的min_rise_pct
            for s in sel_strats:
                if s.get("id") == "halfway_chase":
                    s.setdefault("params", {})["min_rise_pct"] = value
            for s in inner_sel_strats:
                if s.get("id") == "halfway_chase":
                    s.setdefault("params", {})["min_rise_pct"] = value
        elif param_name == "min_volume_ratio":
            # 修改halfway_chase策略的min_volume_ratio
            for s in sel_strats:
                if s.get("id") == "halfway_chase":
                    s.setdefault("params", {})["min_volume_ratio"] = value
            for s in inner_sel_strats:
                if s.get("id") == "halfway_chase":
                    s.setdefault("params", {})["min_volume_ratio"] = value
        else:
            raise HTTPException(status_code=400, detail=f"未知扫描参数: {param_name}")

        return info

    # ---- 生成N组参数并执行回测 ----
    from nodes.backtest_engine.ultra_short import execute_ultra_short_backtest

    sweep_task_id = f"sw_{uuid.uuid4().hex[:8]}"
    logger.info(f"[{sweep_task_id}] Starting sweep: param={sweep_param}, {len(sweep_values)} values")

    # 注意：execute_ultra_short_backtest内部使用全局logger.set_task_id(),
    # 并行执行会导致task_id互相覆盖，因此sweep必须串行执行
    async def run_single_sweep(sweep_value: float, idx: int) -> dict:
        """执行单组sweep回测"""
        sub_task_id = f"sw_{uuid.uuid4().hex[:8]}_{idx}"
        try:
            task_info = apply_sweep_param(base_task_info, sweep_param, sweep_value)
            task_info["task_id"] = sub_task_id
            result = await execute_ultra_short_backtest(
                task_info,
                _backtest_node._push_log,
                _backtest_node.logger,
                sub_task_id,
            )
            # 提取关键指标
            perf_list = result.get("performance", [])
            perf = perf_list[0] if perf_list else {}
            return {
                "value": sweep_value,
                "total_return": round(perf.get("total_return", 0.0), 2),
                "win_rate": round(perf.get("win_rate", 0.0), 2),
                "max_drawdown": round(perf.get("max_drawdown", 0.0), 2),
                "sharpe_ratio": round(perf.get("sharpe_ratio", 0.0), 2),
                "total_trades": perf.get("total_trades", 0),
                "execution_time_ms": result.get("execution_time_ms", 0),
                "sell_reason_stats": result.get("sell_reason_stats", {}),
                "success": True,
            }
        except Exception as e:
            logger.error(f"[{sweep_task_id}] sweep value={sweep_value} failed: {e}")
            return {
                "value": sweep_value,
                "total_return": 0.0,
                "win_rate": 0.0,
                "max_drawdown": 0.0,
                "sharpe_ratio": 0.0,
                "total_trades": 0,
                "execution_time_ms": 0,
                "sell_reason_stats": {},
                "success": False,
                "error": str(e),
            }

    # 串行执行sweep回测（因logger全局状态限制，不可并行）
    results = []
    for i, v in enumerate(sweep_values):
        r = await run_single_sweep(v, i)
        results.append(r)

    return {
        "sweep_param": sweep_param,
        "sweep_values": sweep_values,
        "results": list(results),
    }
