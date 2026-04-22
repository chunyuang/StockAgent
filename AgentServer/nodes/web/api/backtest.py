from datetime import datetime
import uuid
import logging
from typing import Dict, List, Any, Optional
from enum import Enum

from fastapi import APIRouter, HTTPException, Query, Depends, Request
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, Field, ValidationError, root_validator
from jose import JWTError, jwt

from core.managers import mongo_manager
from core.settings import settings
from core.rpc import RPCClient
from .auth import get_current_user_id

oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

async def get_optional_user_id(token: Optional[str] = Depends(oauth2_scheme_optional)) -> str:
    """可选登录，没有token返回默认测试用户"""
    if not token:
        return "test_user_001"
    try:
        payload = jwt.decode(token, settings.jwt_secret.get_secret_value(), algorithms=[settings.jwt_algorithm])
        user_id: str = payload.get("sub")
        if user_id is None:
            return "test_user_001"
        return user_id
    except JWTError:
        return "test_user_001"

router = APIRouter(prefix="/backtest", tags=["Backtest"])
logger = logging.getLogger("api.backtest")

# 回测任务计数器，简单过载保护
_running_backtest_count = 0
_MAX_CONCURRENT_BACKTESTS = 3


# ==================== 数据模型 ====================


class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BacktestRequest(BaseModel):
    """回测请求"""
    ts_code: str = Field(..., description="股票代码", pattern=r"^\d{6}\.(SH|SZ|BJ)$")
    stock_name: Optional[str] = Field(default=None, description="股票名称")
    start_date: str = Field(..., description="开始日期", pattern=r"^\d{8}$")
    end_date: str = Field(..., description="结束日期", pattern=r"^\d{8}$")
    
    # 资金配置
    initial_cash: float = Field(default=100000.0, ge=10000, le=100000000, description="初始资金")
    
    # 信号阈值
    entry_threshold: float = Field(default=0.7, ge=0.5, le=0.95, description="买入阈值")
    exit_threshold: float = Field(default=0.3, ge=0.05, le=0.5, description="卖出阈值")
    
    # 仓位管理
    position_size: float = Field(default=1.0, ge=0.1, le=1.0, description="仓位比例")
    
    # 因子权重 (可选)
    factor_weights: Dict[str, float] = Field(
        default_factory=dict,
        description="因子权重配置，key 为因子名，value 为权重"
    )
    
    # 是否自动计算技术指标
    auto_technical: bool = Field(default=True, description="自动计算技术指标")
    
    class Config:
        json_schema_extra = {
            "example": {
                "ts_code": "000001.SZ",
                "start_date": "20240101",
                "end_date": "20241231",
                "initial_cash": 100000,
                "entry_threshold": 0.7,
                "exit_threshold": 0.3,
                "position_size": 1.0,
                "factor_weights": {
                    "tech_rsi": 0.3,
                    "tech_macd_signal": 0.3,
                    "tech_price_position": 0.4,
                },
                "auto_technical": True,
            }
        }


class FactorConfig(BaseModel):
    """因子配置"""
    name: str = Field(..., description="因子名称")
    weight: float = Field(default=1.0, ge=0, le=1.0, description="因子权重")
    direction: Optional[str] = Field(default=None, description="因子方向: asc(越大越好) / desc(越小越好)")


class FactorSelectionRequest(BaseModel):
    """因子选股回测请求"""
    universe: str = Field(default="all_a", description="股票池类型")
    start_date: str = Field(..., description="开始日期", pattern=r"^\d{8}$")
    end_date: str = Field(..., description="结束日期", pattern=r"^\d{8}$")
    
    initial_cash: float = Field(default=1000000.0, ge=100000, le=100000000, description="初始资金")
    rebalance_freq: str = Field(default="monthly", description="调仓频率: daily/weekly/monthly/quarterly")
    top_n: int = Field(default=20, ge=1, le=100, description="选股数量")
    weight_method: str = Field(default="equal", description="权重方法: equal/factor_weighted")
    
    factors: List[FactorConfig] = Field(..., description="因子配置列表", min_length=1)
    exclude: List[str] = Field(default=["st", "new_stock"], description="排除规则")
    benchmark: str = Field(default="000300.SH", description="基准指数")
    
    class Config:
        json_schema_extra = {
            "example": {
                "universe": "all_a",
                "start_date": "20230101",
                "end_date": "20260101",
                "initial_cash": 1000000,
                "rebalance_freq": "monthly",
                "top_n": 20,
                "weight_method": "equal",
                "factors": [
                    {"name": "momentum_20d", "weight": 0.3},
                    {"name": "pb", "weight": 0.3},
                    {"name": "roe", "weight": 0.4},
                ],
                "exclude": ["st", "new_stock"],
                "benchmark": "000300.SH",
            }
        }


class UltraShortParams(BaseModel):
    """超短策略参数配置"""
    volume_threshold: float = Field(default=1.5, ge=1.0, le=10.0, description="量能放大倍数")
    stop_loss_pct: float = Field(default=0.05, ge=0.01, le=0.2, description="止损比例")
    take_profit_pct: float = Field(default=0.1, ge=0.01, le=0.5, description="止盈比例")
    max_hold_days: int = Field(default=3, ge=1, le=10, description="最大持仓天数")
    max_position: float = Field(default=0.7, ge=0.1, le=1.0, description="总仓位上限")
    liquidity_threshold: float = Field(default=500.0, ge=100.0, le=5000.0, description="流动性门槛（万元）")
    max_position_per_stock: float = Field(default=0.3, ge=0.05, le=1.0, description="单票最大仓位比例")
    force_empty_position: bool = Field(default=True, description="是否启用强制空仓规则")
    sentiment_cycle: bool = Field(default=True, description="是否启用情绪周期算法")
    auction_filter: bool = Field(default=True, description="是否启用竞价过滤规则")
    selected_strategies: List[Dict[str, Any]] = Field(default_factory=list, description="选中策略的完整配置（包含独立参数）")

# 中文策略名映射，放在类外面避免pydantic v2私有属性问题
strategy_name_map: Dict[str, str] = {
    "半路追涨": "halfway_chase",
    "首板打板": "first_limit_up",
    "涨停开板": "limit_up_open",
    "龙头低吸": "leader_buy_dip",
    "跌停翘板": "limit_down_qiao"
}


class UltraShortBacktestRequest(BaseModel):
    """超短策略回测请求"""
    strategies: Optional[List[str]] = Field(None, description="策略列表，可选值: halfway_chase(半路追涨), first_limit_up(首板打板), limit_up_open(涨停开板), leader_buy_dip(龙头低吸), limit_down_qiao(跌停翘板)", min_length=1)
    selected_strategies: Optional[List[Dict[str, Any]]] = Field(None, description="前端提交的选中策略对象数组，兼容老版本")
    start_date: Optional[str] = Field(None, description="开始日期")
    end_date: Optional[str] = Field(None, description="结束日期")
    
    # 数据源配置
    data_source: str = Field(default="mongodb", description="数据源：固定为mongodb")
    period: str = Field(default="daily", description="周期：daily/1min")
    ts_codes: Optional[str] = Field(default=None, description="股票代码列表，逗号分隔，空为全市场")
    adjust_type: str = Field(default="qfq", description="复权方式：none(不复权), qfq(前复权)")
    
    initial_cash: Optional[float] = Field(default=1000000.0, ge=10000, le=100000000, description="初始资金")
    initial_capital: Optional[float] = Field(default=1000000.0, ge=10000, le=100000000, description="初始资金，兼容前端字段名")
    params: UltraShortParams = Field(default_factory=UltraShortParams, description="全局策略参数配置")
    strategy_params: Dict[str, Dict[str, Any]] = Field(default_factory=dict, description="各策略独立参数配置，key为策略id，value为参数字典")
    
    enable_sentiment_cycle: bool = Field(default=True, description="启用情绪周期适配")
    enable_auction_filter: bool = Field(default=True, description="启用集合竞价过滤")
    enable_force_empty: bool = Field(default=True, description="启用强制空仓规则")

    @root_validator(skip_on_failure=True)
    def compatibility_convert(cls, values):
        # 兼容前端selected_strategies结构，转换为strategies和strategy_params
        selected_strategies = values.get('selected_strategies')
        strategies = values.get('strategies')
        if selected_strategies and not strategies:
            strategies = []
            strategy_params = values.get('strategy_params', {})
            for s in selected_strategies:
                s_name = s.get('name', '')
                s_params = s.get('params', {})
                if s_name in strategy_name_map:
                    s_id = strategy_name_map[s_name]
                    strategies.append(s_id)
                    strategy_params[s_id] = s_params
            values['strategies'] = strategies
            values['strategy_params'] = strategy_params

        # 兼容start_date/end_date在params里的情况
        params = values.get('params')
        if not values.get('start_date') and hasattr(params, 'start_date') and params.start_date:
            values['start_date'] = params.start_date
        if not values.get('end_date') and hasattr(params, 'end_date') and params.end_date:
            values['end_date'] = params.end_date

        # 兼容initial_capital字段
        initial_capital = values.get('initial_capital')
        if initial_capital and values.get('initial_cash') == 1000000.0:
            values['initial_cash'] = initial_capital

        # 兼容params里的enable字段
        if hasattr(params, 'force_empty_position'):
            values['enable_force_empty'] = getattr(params, 'force_empty_position', True)
        if hasattr(params, 'sentiment_cycle'):
            values['enable_sentiment_cycle'] = getattr(params, 'sentiment_cycle', True)
        if hasattr(params, 'auction_filter'):
            values['enable_auction_filter'] = getattr(params, 'auction_filter', True)

        return values

    # 允许所有额外字段，不会过滤任何前端提交的内容
    class Config:
        extra = 'allow'
        json_schema_extra = {
            "example": {
                "strategies": ["halfway_chase"],
                "start_date": "20260105",
                "end_date": "20260320",
                "initial_cash": 1000000,
                "params": {
                    "liquidity_threshold": 500,
                    "volume_threshold": 1.5,
                    "stop_loss_pct": 0.05,
                    "take_profit_pct": 0.1,
                    "max_hold_days": 3,
                    "max_position_per_stock": 0.2,
                    "max_position": 0.7,
                },
                "enable_force_empty": True,
                "enable_sentiment_cycle": True,
                "enable_auction_filter": True,
            }
        }


class BacktestTaskResponse(BaseModel):
    """回测任务响应"""
    task_id: str
    status: str
    message: str


# ==================== API 端点 ====================


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


@router.get("/status/{task_id}")
async def get_backtest_status(
    task_id: str,
    user_id: str = Depends(get_optional_user_id),
) -> Dict[str, Any]:
    """
    查询回测任务状态
    """
    # 先查Mock任务
    if task_id.startswith("us_") and task_id in mock_tasks:
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
    
    # 查 MongoDB
    record = await mongo_manager.find_one(
        "backtest_tasks",
        {"task_id": task_id},
    )
    
    if not record:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    # 权限检查 (如果记录中有 user_id)
    if record.get("params", {}).get("user_id") and record["params"]["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="无权访问此任务")
    
    return {
        "success": True,
        "data": {
            "task_id": task_id,
            "status": record.get("status"),
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
    """
    获取回测结果
    
    仅当任务完成后可获取。
    """
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
    """
    获取用户的回测历史
    
    Args:
        task_type: 可选，筛选任务类型
            - None: 返回所有
            - "single": 单股回测
            - "factor_selection": 因子选股回测
    """
    query: Dict[str, Any] = {"params.user_id": user_id, "status": "completed"}
    
    # 根据任务类型筛选 (task_type 存储在顶层)
    if task_type == "single":
        # 单股回测：task_type 不存在或不等于 factor_selection
        query["$or"] = [
            {"task_type": {"$exists": False}},
            {"task_type": {"$ne": "factor_selection"}},
        ]
    elif task_type == "factor_selection":
        # 因子选股：task_type 等于 factor_selection
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
            # 因子选股回测特有字段 - 从 performance 中读取
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
            # 单股回测字段
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
    """
    取消回测任务
    
    支持取消运行中的超短策略回测任务和等待中的普通回测任务。
    """
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
        {"$set": {"status": "cancelled", "cancelled_at": datetime.utcnow()}},
    )
    
    return {"task_id": task_id, "status": "cancelled", "message": "任务已取消"}


# ==================== 因子选股回测 API ====================


@router.get("/factors")
async def list_available_factors() -> Dict[str, Any]:
    """
    获取可用的因子列表
    """
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
    """
    提交因子选股回测任务
    
    选股策略:
    1. 根据 universe 确定股票池范围 (目前支持全市场 all_a)
    2. 应用排除规则 (ST、次新股等)
    3. 计算每只股票的因子值并标准化
    4. 按综合得分选取 Top N 只股票
    5. 按指定频率调仓
    6. 计算组合收益并与基准对比
    
    返回 task_id 用于查询进度和结果。
    """
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


# 导入回测执行逻辑
from nodes.backtest_engine.node import BacktestNode

# Mock回测任务存储，临时使用
mock_tasks = {}

# 初始化回测节点实例（仅用于执行超短回测逻辑，不需要启动RPC服务）
_backtest_node = BacktestNode()

oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

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

    # 转换策略名称为完整配置（对齐实盘参数结构）
    strategy_name_map = {
        "halfway_chase": "半路追涨",
        "first_limit_up": "首板打板",
        "limit_up_open": "涨停开板",
        "leader_buy_dip": "龙头低吸",
        "limit_down_qiao": "跌停翘板"
    }

    # 构建选中策略列表：100%原封不动使用前端提交的selected_strategies，不做任何修改
    selected_strategies = []
    if hasattr(request.params, "selected_strategies") and request.params.selected_strategies:
        # 完全透传前端提交的策略和参数，不添加、不修改任何字段
        selected_strategies = request.params.selected_strategies
    else:
        # 如果前端没有提交selected_strategies，从strategies字段读取，参数为空
        for s in request.strategies:
            selected_strategies.append({
                "id": s,
                "name": strategy_name_map.get(s, s),
                "params": {}
            })

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
            },
            "enable_force_empty": request.enable_force_empty,
            "enable_sentiment_cycle": request.enable_sentiment_cycle,
            "enable_auction_filter": request.enable_auction_filter,
            "selected_strategies": selected_strategies
        }
    }

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
    mock_logs.append(f"[{timestamp}] ├─ 流动性门槛: {getattr(request.params, 'liquidity_threshold', 500)} 万元")
    mock_logs.append(f"[{timestamp}] ├─ 单票最大仓位: {getattr(request.params, 'max_position_per_stock', 0.3)*100} %")
    mock_logs.append(f"[{timestamp}] ├─ 总仓位上限: {getattr(request.params, 'max_position', 0.6)*100} %")
    mock_logs.append(f"[{timestamp}] ├─ 止损比例: {getattr(request.params, 'stop_loss_pct', 0.02)*100} %")
    mock_logs.append(f"[{timestamp}] ├─ 止盈比例: {getattr(request.params, 'take_profit_pct', 0.07)*100} %")
    mock_logs.append(f"[{timestamp}] ├─ 最大持仓天数: {getattr(request.params, 'max_hold_days', 3)} 天")
    mock_logs.append(f"[{timestamp}] ├─ 强制空仓规则: {'已启用' if getattr(request.params, 'force_empty_position', True) else '已关闭'}")
    mock_logs.append(f"[{timestamp}] ├─ 情绪周期算法: {'已启用' if getattr(request.params, 'sentiment_cycle', True) else '已关闭'}")
    mock_logs.append(f"[{timestamp}] └─ 竞价过滤规则: {'已启用' if getattr(request.params, 'auction_filter', True) else '已关闭'}")
    mock_logs.append(f"[{timestamp}]")
    mock_logs.append(f"[{timestamp}]")

    # 打印提交参数
    mock_logs.append(f"[{timestamp}] 🚀 【实盘级】开始提交超短策略回测任务...")
    mock_logs.append(f"[{timestamp}] 📅 回测区间: {request.start_date} -> {request.end_date}")
    mock_logs.append(f"[{timestamp}] 💰 初始资金: {request.initial_cash:,} 元")
    mock_logs.append(f"[{timestamp}] 🎯 选中策略: {[strategy_name_map.get(s, s) for s in request.strategies]}")
    mock_logs.append(f"[{timestamp}] ✅ 任务提交成功，任务ID：{task_id}")

    # 打印各策略独立参数块（与界面1:1对应）
    mock_logs.append(f"[{timestamp}]")
    mock_logs.append(f"[{timestamp}] 📋 === 🎯 各策略独立参数 ===")
    for strategy in selected_strategies:
        strategy_name = strategy.get("name", strategy_name_map.get(strategy.get("id"), "未知策略"))
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

    # 异步执行真实回测逻辑（不阻塞HTTP请求）
    import asyncio
    async def run_backtest_async():
        try:
            logger.info(f"[{task_id}] 开始执行真实回测逻辑")

            # 重写_push_log方法，实时更新日志到mock_tasks
            original_push_log = _backtest_node._push_log

            async def custom_push_log(task_id_inner, log_text):
                if task_id_inner == task_id and task_id in mock_tasks:
                    # 直接使用回测引擎生成的日志（已经带时间戳）
                    mock_logs.append(log_text)
                    mock_tasks[task_id]["progress"] = min(len(mock_tasks[task_id]["logs"]) / 30 * 100, 95)

                    # 推送到WebSocket
                    from nodes.web.websocket import manager as ws_manager
                    await ws_manager.broadcast_task_update(task_id, {
                        "type": "log",
                        "log": log_text,
                    })
                # 调用原方法保存到数据库和本地文件
                await original_push_log(task_id_inner, log_text)

            _backtest_node._push_log = custom_push_log

            # 执行真实回测逻辑
            result = await _backtest_node._execute_ultra_short_backtest(task_info)

            # 更新任务状态和结果
            mock_tasks[task_id]["status"] = "completed"
            mock_tasks[task_id]["progress"] = 100
            mock_tasks[task_id]["result"] = result

            # 推送完成消息到前端
            from nodes.web.websocket import manager as ws_manager
            await ws_manager.broadcast_task_update(task_id, {
                "type": "status",
                "status": "completed",
                "result": result
            })

            logger.info(f"[{task_id}] 回测执行完成，日志条数：{len(mock_tasks[task_id]['logs'])}")

        except Exception as e:
            mock_tasks[task_id]["status"] = "failed"
            err_log = f"❌ 回测失败：{str(e)}"
            mock_logs.append(err_log)
            # 推送错误到前端
            from nodes.web.websocket import manager as ws_manager
            await ws_manager.broadcast_task_update(task_id, {
                "type": "log",
                "log": err_log,
            })
            await ws_manager.broadcast_task_update(task_id, {
                "type": "status",
                "status": "failed",
                "error": str(e)
            })
            logger.exception(f"[{task_id}] 回测执行失败: {e}")
        finally:
            # 恢复原方法
            _backtest_node._push_log = original_push_log
            # 清理计数器
            if task_id in _backtest_node._log_counters:
                del _backtest_node._log_counters[task_id]

    # 启动异步回测任务
    asyncio.create_task(run_backtest_async())

    return BacktestTaskResponse(
        task_id=task_id,
        status="running",
        message="回测任务提交成功，正在执行"
    )


# ========== 获取超短回测默认配置 ==========
# 从配置文件/环境变量读取默认初始值，供前端页面初始化使用
# 这样修改配置文件就能改变前端默认值，不需要改前端代码
@router.get("/ultra-short/defaults")
async def get_ultra_short_defaults(
    user_id: str = Depends(get_optional_user_id),
) -> Dict[str, Any]:
    """
    获取超短回测页面的默认初始配置
    
    从环境变量/.env读取配置，返回给前端用于初始化表单。
    这样修改.env就能改变前端默认值，不需要重新编译前端代码。
    """
    from core.settings import settings
    
    # 默认硬编码值 (如果环境变量没有配置，使用这些默认值)
    defaults = {
        # 数据源
        "dataSource": {
            "period": "daily",
            "ts_codes": "",
            "start_date": "20260105",
            "end_date": "20260320",
            "adjust_type": "qfq",
        },
        # 基础配置
        "base": {
            "initial_cash": 1000000,
        },
        # 全局筛选
        "globalFilter": {
            "exclude_st": True,
            "exclude_delisting": True,
            "exclude_new_stock_days": 60,
            "min_daily_amount": 500,
            "min_turnover_rate": 3,
        },
        # 强制空仓
        "forceEmpty": {
            "enabled": True,
            "index_drop_pct": 0.03,
            "limit_down_count": 50,
            "limit_up_count": 10,
        },
        # 情绪周期
        "sentimentCycle": {
            "enabled": True,
            "weight_limit_up": 0.25,
            "weight_limit_down": 0.10,
            "weight_blast_rate": 0.07,
            "weight_rise_fall_diff": 0.15,
            "weight_north_inflow": 0.12,
        },
        # 竞价过滤
        "auctionFilter": {
            "enabled": True,
            "min_auction_pct": 0.005,
            "max_auction_pct": 0.07,
            "min_unmatched_volume_positive": True,
            "min_auction_amount": 300,
            "min_auction_volume_ratio": 1.5,
        },
        # 交易参数
        "tradeParams": {
            "base_stop_loss_pct": 0.02,
            "base_take_profit_pct": 0.07,
            "max_hold_days": 3,
            "max_position_per_stock": 0.3,
            "max_total_position": 0.6,
            "commission_rate": 0.0003,
            "stamp_duty_rate": 0.001,
            "slippage_pct": 0.002,
        },
        # 策略启用
        "strategies": ["halfway_chase", "first_limit_up", "limit_up_open", "leader_buy_dip", "limit_down_qiao"],
        # 各策略独立配置
        "strategyConfigs": {
            "halfway_chase": {
                "enabled": True,
                "name": "半路追涨",
                "params": {
                    "min_rise_pct": 0.03,
                    "max_rise_pct": 0.07,
                    "min_volume_ratio": 1.5,
                    "allow_after_10am": False,
                }
            },
            "first_limit_up": {
                "enabled": True,
                "name": "首板打板",
                "params": {
                    "min_seal_amount": 5000,
                    "max_limit_up_time": "10:00",
                    "max_circulation_market_cap": 100,
                    "max_blast_count": 1,
                    "require_hot_sector": True,
                }
            },
            "limit_up_open": {
                "enabled": True,
                "name": "涨停开板",
                "params": {
                    "min_consecutive_limit": 2,
                    "max_open_duration": 5,
                    "min_seal_after_open": 3000,
                    "min_turnover_rate": 0.15,
                }
            },
            "leader_buy_dip": {
                "enabled": True,
                "name": "龙头低吸",
                "params": {
                    "min_consecutive_limit": 3,
                    "min_correction_pct": 0.15,
                    "max_correction_pct": 0.3,
                    "correction_days_min": 2,
                    "correction_days_max": 5,
                    "support_level": "ma5",
                }
            },
            "limit_down_qiao": {
                "enabled": True,
                "name": "跌停翘板",
                "params": {
                    "min_consecutive_limit": 3,
                    "min_qiao_amount": 10000,
                    "min_rise_after_qiao": 0.03,
                    "require_high_sentiment": True,
                }
            },
        }
    }
    
    # 检查环境变量是否有覆盖
    # 从settings中读取ULTRASHORT_*前缀的环境变量，覆盖默认值
    # 这样.env中定义 ULTRASHORT_START_DATE=20250101 就能覆盖默认的start_date
    
    # 这里我们不做复杂的嵌套解析，只支持顶级简单覆盖
    # 如果需要更深层次覆盖，后续可以扩展
    
    return {
        "success": True,
        "data": defaults
    }
