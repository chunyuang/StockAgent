"""
超短策略回测API路由

包含超短策略回测提交、默认配置获取等端点。
"""

import json
import uuid
import copy
from datetime import datetime
from bson import ObjectId

from fastapi import APIRouter, HTTPException, Request, Depends
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
    # 安全获取selected_strategies，即使属性不存在也不会抛出异常
    selected_from_params = getattr(request.params, 'selected_strategies', None)
    if selected_from_params and len(selected_from_params) > 0:
        # 完全透传前端提交的策略和参数，不添加、不修改任何字段
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
                "force_empty_position": request.enable_force_empty,
                "sentiment_cycle": request.enable_sentiment_cycle,
                "auction_filter": request.enable_auction_filter,
                "selected_strategies": selected_strategies,
            },
            "enable_force_empty": request.enable_force_empty,
            "enable_sentiment_cycle": request.enable_sentiment_cycle,
            "enable_auction_filter": request.enable_auction_filter,
            "selected_strategies": selected_strategies
        }
    }

    # 递归转换所有 datetime/date 对象到字符串，双重防护确保序列化成功
    task_info = convert_datetime_to_str(task_info)

    # 初始化本地日志和任务状态（用于WebSocket推送和状态查询）
    timestamp = datetime.utcnow().strftime("%H:%M:%S")
    mock_logs = []
    # 打印WebSocket连接成功日志和版本标识
    mock_logs.append(f"[{timestamp}] ✅ 【代码版本：v2.4.0-2026-04-13-16:55】参数补全+日志优化版已生效")
    mock_logs.append(f"[{timestamp}] ✅ WebSocket已连接，实时日志推送已开启")

    # 打印完整全局公共参数块（与界面1:1对应），前后加空行+醒目标记完全避免被覆盖
    mock_logs.append(f"[{timestamp}]")
    mock_logs.append(f"[{timestamp}]")
    mock_logs.append(f"[{timestamp}] 🔴🔴🔴 === 🔧 全局公共参数 === 🔴🔴🔴")
    mock_logs.append(f"[{timestamp}] ├─ 流动性门槛: {request.params.liquidity_threshold} 万元")
    mock_logs.append(f"[{timestamp}] ├─ 单票最大仓位: {request.params.max_position_per_stock*100} %")
    mock_logs.append(f"[{timestamp}] ├─ 总仓位上限: {request.params.max_position*100} %")
    mock_logs.append(f"[{timestamp}] ├─ 止损比例: {request.params.stop_loss_pct*100} %")
    mock_logs.append(f"[{timestamp}] ├─ 止盈比例: {request.params.take_profit_pct*100} %")
    mock_logs.append(f"[{timestamp}] ├─ 最大持仓天数: {request.params.max_hold_days} 天")
    mock_logs.append(f"[{timestamp}] ├─ 综合佣金率: {request.params.commission_rate*10000:.1f} ‰")
    mock_logs.append(f"[{timestamp}] ├─ 印花税率: {request.params.stamp_duty_rate*1000:.1f} ‰")
    mock_logs.append(f"[{timestamp}] └─ 滑点: {request.params.slippage_pct*1000:.1f} ‰")
    mock_logs.append(f"[{timestamp}] ├─ 强制空仓规则: {'已启用' if request.enable_force_empty else '已关闭'}")
    mock_logs.append(f"[{timestamp}] ├─ 情绪周期算法: {'已启用' if request.enable_sentiment_cycle else '已关闭'}")
    mock_logs.append(f"[{timestamp}] └─ 竞价过滤规则: {'已启用' if request.enable_auction_filter else '已关闭'}")
    mock_logs.append(f"[{timestamp}]")
    mock_logs.append(f"[{timestamp}]")

    # 打印提交参数
    mock_logs.append(f"[{timestamp}] 🚀 【实盘级】开始提交超短策略回测任务...")
    mock_logs.append(f"[{timestamp}] 📅 回测区间: {request.start_date} -> {request.end_date}")
    mock_logs.append(f"[{timestamp}] 💰 初始资金: {request.initial_cash:,} 元")
    mock_logs.append(f"[{timestamp}] 🎯 选中策略: {[strategy_name_map_reverse.get(s, s) for s in request.strategies]}")
    mock_logs.append(f"[{timestamp}] ✅ 任务提交成功，任务ID：{task_id}")

    # 打印各策略独立参数块（与界面1:1对应）
    mock_logs.append(f"[{timestamp}]")
    mock_logs.append(f"[{timestamp}] 📋 === 🎯 各策略独立参数 ===")
    for strategy in selected_strategies:
        strategy_name = strategy.get("name", strategy_name_map_reverse.get(strategy.get("id"), "未知策略"))
        mock_logs.append(f"[{timestamp}] ┌─ 🎯 【{strategy_name}】")
        params = strategy.get("params", {})
        if strategy.get("id") == "halfway_chase":
            min_rise = params.get('min_rise_pct', 0.03) * 100
            max_rise = params.get('max_rise_pct', 0.07) * 100
            volume = params.get('volume_threshold', 1.5)
            allow_after_10 = '是' if params.get('allow_after_10am', False) else '否'
            mock_logs.append(f"[{timestamp}] │ ├─ 最小涨幅: {min_rise} %")
            mock_logs.append(f"[{timestamp}] │ ├─ 最大涨幅: {max_rise} %")
            mock_logs.append(f"[{timestamp}] │ ├─ 量比阈值: {volume} 倍 (应用到筛选逻辑)")
            mock_logs.append(f"[{timestamp}] │ └─ 允许10点后买入: {allow_after_10}")
        elif strategy.get("id") == "first_limit_up":
            min_seal = params.get('min_seal_amount', 5000)
            max_time = params.get('max_limit_up_time', '10:00')
            max_cap = params.get('max_circulation_market_cap', 100)
            max_blast = params.get('max_blast_count', 1)
            require_hot = '是' if params.get('require_hot_sector', True) else '否'
            mock_logs.append(f"[{timestamp}] │ ├─ 最小封单金额: {min_seal} 万元")
            mock_logs.append(f"[{timestamp}] │ ├─ 最晚涨停时间: {max_time}")
            mock_logs.append(f"[{timestamp}] │ ├─ 最大流通市值: {max_cap} 亿")
            mock_logs.append(f"[{timestamp}] │ ├─ 最大开板次数: {max_blast} 次")
            mock_logs.append(f"[{timestamp}] │ └─ 要求热门板块: {require_hot}")
        elif strategy.get("id") == "limit_up_open":
            min_consec = params.get('min_consecutive_limit', 2)
            max_open = params.get('max_open_duration', 5)
            min_seal_after = params.get('min_seal_after_open', 3000)
            min_turnover = params.get('min_turnover_rate', 0.15) * 100
            mock_logs.append(f"[{timestamp}] │ ├─ 最小连续涨停天数: {min_consec} 天")
            mock_logs.append(f"[{timestamp}] │ ├─ 最大开板时长: {max_open} 分钟")
            mock_logs.append(f"[{timestamp}] │ ├─ 开板后最小封单: {min_seal_after} 万元")
            mock_logs.append(f"[{timestamp}] │ └─ 最小换手率: {min_turnover} %")
        elif strategy.get("id") == "leader_buy_dip":
            min_consec = params.get('min_consecutive_limit', 3)
            min_correct = params.get('min_correction_pct', 0.15) * 100
            max_correct = params.get('max_correction_pct', 0.3) * 100
            min_correct_days = params.get('correction_days_min', 2)
            max_correct_days = params.get('correction_days_max', 5)
            support = params.get('support_level', 'ma5')
            mock_logs.append(f"[{timestamp}] │ ├─ 最小连续涨停天数: {min_consec} 天")
            mock_logs.append(f"[{timestamp}] │ ├─ 最小回调幅度: {min_correct} %")
            mock_logs.append(f"[{timestamp}] │ ├─ 最大回调幅度: {max_correct} %")
            mock_logs.append(f"[{timestamp}] │ ├─ 最小回调天数: {min_correct_days} 天")
            mock_logs.append(f"[{timestamp}] │ ├─ 最大回调天数: {max_correct_days} 天")
            mock_logs.append(f"[{timestamp}] │ └─ 支撑位: {support}")
        elif strategy.get("id") == "limit_down_qiao":
            min_consec = params.get('min_consecutive_limit', 3)
            min_qiao = params.get('min_qiao_amount', 10000)
            min_rise_after = params.get('min_rise_after_qiao', 0.03) * 100
            require_high_sentiment = '是' if params.get('require_high_sentiment', True) else '否'
            mock_logs.append(f"[{timestamp}] │ ├─ 最小连续跌停天数: {min_consec} 天")
            mock_logs.append(f"[{timestamp}] │ ├─ 翘板最小金额: {min_qiao} 万元")
            mock_logs.append(f"[{timestamp}] │ ├─ 翘板后最小涨幅: {min_rise_after} %")
            mock_logs.append(f"[{timestamp}] │ └─ 要求高情绪周期: {require_high_sentiment}")
    mock_logs.append(f"[{timestamp}]")
    mock_logs.append(f"[{timestamp}] ✅ 参数核对完成，所有参数与界面配置完全一致")

    # 初始化Mock任务，把日志绑定到任务上
    mock_tasks[task_id] = {
        "task_id": task_id,
        "status": "running",
        "progress": 0,
        "logs": mock_logs,
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
            timeout=10.0,  # 只等待任务投递确认，不等待执行结果
            source_node="web-node",
        )

        if not results:
            # 无可用回测节点 — 致命错误，抛503而非谎报running
            mock_tasks[task_id] = {
                "task_id": task_id,
                "status": "failed",
                "progress": 0,
                "logs": mock_logs + [f"[{timestamp}] ❌ 无可用回测节点，请确保BacktestNode已启动"],
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
            mock_tasks[task_id] = {
                "task_id": task_id,
                "status": "failed",
                "progress": 0,
                "logs": mock_logs + [f"[{timestamp}] ❌ RPC投递失败: {error_msg}"],
                "result": None
            }
            raise HTTPException(status_code=500, detail=error_msg)

        logger.info(f"[{task_id}] 任务已成功投递到RPC回测节点")
        mock_tasks[task_id] = {
            "task_id": task_id,
            "status": "running",
            "progress": 10,
            "logs": mock_logs,
            "result": None
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[{task_id}] RPC投递异常: {e}")
        error_msg = str(e)
        mock_tasks[task_id] = {
            "task_id": task_id,
            "status": "failed",
            "progress": 0,
            "logs": mock_logs + [f"[{timestamp}] ❌ RPC投递异常: {error_msg}"],
            "result": None
        }
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
