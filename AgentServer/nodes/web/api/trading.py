"""
实盘交易 API

提供模拟账户管理、持仓查询、交易信号、绩效报告等实盘相关接口。
"""

import uuid
import logging
from datetime import datetime, timezone
from typing import List, Optional
from enum import Enum

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel, Field

from core.constants import C
from core.managers import mongo_manager
from .auth import get_optional_user_id

router = APIRouter(prefix="/trading", tags=["Trading"])
logger = logging.getLogger("api.trading")

# ==================== 枚举定义 ====================

class TradeDirection(str, Enum):
    """交易方向"""
    BUY = "buy"
    SELL = "sell"

class SignalType(str, Enum):
    """信号类型"""
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"

class SignalStatus(str, Enum):
    """信号状态"""
    PENDING = "pending"
    EXECUTED = "executed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"

# ==================== 数据模型 ====================

class SimAccount(BaseModel):
    """模拟账户信息"""
    account_id: str
    name: str
    user_id: str
    initial_cash: float = Field(ge=10000, le=100000000)
    available_cash: float
    total_assets: float
    total_profit_pct: float
    total_profit: float
    position_value: float
    position_ratio: float
    created_at: datetime
    updated_at: datetime
    is_active: bool = True

class Position(BaseModel):
    """持仓信息"""
    position_id: str
    account_id: str
    ts_code: str
    stock_name: str
    quantity: int = Field(ge=0)
    available_quantity: int = Field(ge=0)
    avg_cost: float = Field(ge=0)
    current_price: Optional[float] = None
    profit_pct: Optional[float] = None
    profit: Optional[float] = None
    first_buy_date: Optional[datetime] = None
    hold_days: int = Field(ge=0, default=0)
    strategy: Optional[str] = None
    created_at: datetime
    updated_at: datetime

class TradeRecord(BaseModel):
    """交易记录"""
    trade_id: str
    account_id: str
    ts_code: str
    stock_name: str
    direction: TradeDirection
    quantity: int = Field(gt=0)
    price: float = Field(gt=0)
    amount: float = Field(ge=0)
    commission: float = Field(ge=0, default=0)
    stamp_duty: float = Field(ge=0, default=0)
    trade_time: datetime
    strategy: Optional[str] = None
    reason: Optional[str] = None
    signal_id: Optional[str] = None
    created_at: datetime

class TradingSignal(BaseModel):
    """交易信号"""
    signal_id: str
    ts_code: str
    stock_name: str
    strategy: str
    signal_type: SignalType
    price: float = Field(gt=0)
    suggest_quantity: int = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    reason: str
    generated_at: datetime
    expired_at: datetime
    status: SignalStatus = SignalStatus.PENDING
    executed_time: Optional[datetime] = None
    executed_account_id: Optional[str] = None
    executed_trade_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

class PerformanceReport(BaseModel):
    """绩效报告"""
    report_id: str
    account_id: str
    period: str
    start_date: str
    end_date: str
    total_return_pct: float
    annual_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    win_rate_pct: float
    profit_factor: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    max_consecutive_wins: int
    max_consecutive_losses: int
    avg_profit_per_trade: float
    avg_loss_per_trade: float
    created_at: datetime

# ==================== 请求/响应模型 ====================

class CreateSimAccountRequest(BaseModel):
    """创建模拟账户请求"""
    name: str = Field(..., min_length=1, max_length=50)
    initial_cash: float = Field(100000, ge=10000, le=100000000)

class ExecuteSignalRequest(BaseModel):
    """执行交易信号请求"""
    account_id: str
    quantity: Optional[int] = Field(None, gt=0)

# ==================== API 端点 ====================

@router.get("/accounts", response_model=List[SimAccount])
async def get_sim_accounts(
    user_id: str = Depends(get_optional_user_id),
):
    """
    获取当前用户的模拟账户列表
    """
    try:
        records = await mongo_manager.find_many(
            "sim_accounts",
            {"user_id": user_id, "is_active": True},
            sort=[("created_at", -1)]
        )
        
        accounts = []
        for record in records:
            # 计算实时资产
            total_position_value = 0
            positions = await mongo_manager.find_many(
                C.POSITIONS,
                {"account_id": record["account_id"]}
            )
            
            for pos in positions:
                # TODO: 获取最新价格计算当前市值
                total_position_value += pos.get("quantity", 0) * pos.get("avg_cost", 0)
            
            total_assets = record["available_cash"] + total_position_value
            total_profit = total_assets - record["initial_cash"]
            total_profit_pct = total_profit / record["initial_cash"] if record["initial_cash"] > 0 else 0
            position_ratio = total_position_value / total_assets if total_assets > 0 else 0
            
            account = SimAccount(
                account_id=record["account_id"],
                name=record["name"],
                user_id=record["user_id"],
                initial_cash=record["initial_cash"],
                available_cash=record["available_cash"],
                total_assets=total_assets,
                total_profit_pct=total_profit_pct,
                total_profit=total_profit,
                position_value=total_position_value,
                position_ratio=position_ratio,
                created_at=record["created_at"],
                updated_at=record["updated_at"],
                is_active=record.get("is_active", True)
            )
            accounts.append(account)
        
        # 如果没有账户，自动创建默认账户
        if not accounts:
            default_account = SimAccount(
                account_id=f"sim_{uuid.uuid4().hex[:12]}",
                name="默认模拟账户",
                user_id=user_id,
                initial_cash=1000000.0,
                available_cash=1000000.0,
                total_assets=1000000.0,
                total_profit_pct=0.0,
                total_profit=0.0,
                position_value=0.0,
                position_ratio=0.0,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )
            
            await mongo_manager.insert_one(
                "sim_accounts",
                default_account.model_dump()
            )
            accounts.append(default_account)
        
        return accounts
        
    except Exception as e:
        logger.exception(f"Failed to get sim accounts for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/accounts", response_model=SimAccount)
async def create_sim_account(
    request: CreateSimAccountRequest,
    user_id: str = Depends(get_optional_user_id),
):
    """
    创建新的模拟账户
    """
    try:
        account_id = f"sim_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)
        
        account = SimAccount(
            account_id=account_id,
            name=request.name,
            user_id=user_id,
            initial_cash=request.initial_cash,
            available_cash=request.initial_cash,
            total_assets=request.initial_cash,
            total_profit_pct=0.0,
            total_profit=0.0,
            position_value=0.0,
            position_ratio=0.0,
            created_at=now,
            updated_at=now
        )
        
        await mongo_manager.insert_one(
            "sim_accounts",
            account.model_dump()
        )
        
        return account
        
    except Exception as e:
        logger.exception(f"Failed to create sim account for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/accounts/{account_id}/positions", response_model=List[Position])
async def get_positions(
    account_id: str,
    user_id: str = Depends(get_optional_user_id),
):
    """
    获取指定账户的持仓列表
    """
    try:
        # 验证账户归属
        account = await mongo_manager.find_one(
            "sim_accounts",
            {"account_id": account_id, "user_id": user_id}
        )
        
        if not account:
            raise HTTPException(status_code=404, detail="账户不存在或无权限访问")
        
        records = await mongo_manager.find_many(
            C.POSITIONS,
            {"account_id": account_id, "quantity": {"$gt": 0}},
            sort=[("created_at", -1)]
        )
        
        positions = []
        for record in records:
            # TODO: 补充实时价格和收益计算
            pos = Position(
                position_id=record["position_id"],
                account_id=record["account_id"],
                ts_code=record["ts_code"],
                stock_name=record["stock_name"],
                quantity=record["quantity"],
                available_quantity=record["available_quantity"],
                avg_cost=record["avg_cost"],
                first_buy_date=record.get("first_buy_date"),
                hold_days=record.get("hold_days", 0),
                strategy=record.get("strategy"),
                created_at=record["created_at"],
                updated_at=record["updated_at"]
            )
            positions.append(pos)
        
        return positions
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get positions for account {account_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/accounts/{account_id}/trades")
async def get_trade_records(
    account_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user_id: str = Depends(get_optional_user_id),
):
    """
    获取指定账户的交易记录
    """
    try:
        # 验证账户归属
        account = await mongo_manager.find_one(
            "sim_accounts",
            {"account_id": account_id, "user_id": user_id}
        )
        
        if not account:
            raise HTTPException(status_code=404, detail="账户不存在或无权限访问")
        
        total = await mongo_manager.count(
            "trade_records",
            {"account_id": account_id}
        )
        
        records = await mongo_manager.find_many(
            "trade_records",
            {"account_id": account_id},
            sort=[("trade_time", -1)],
            skip=offset,
            limit=limit
        )
        
        trades = []
        for record in records:
            trades.append(TradeRecord(
                trade_id=record["trade_id"],
                account_id=record["account_id"],
                ts_code=record["ts_code"],
                stock_name=record["stock_name"],
                direction=record["direction"],
                quantity=record["quantity"],
                price=record["price"],
                amount=record["amount"],
                commission=record.get("commission", 0),
                stamp_duty=record.get("stamp_duty", 0),
                trade_time=record["trade_time"],
                strategy=record.get("strategy"),
                reason=record.get("reason"),
                signal_id=record.get("signal_id"),
                created_at=record["created_at"]
            ))
        
        return {
            "total": total,
            "items": trades
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get trade records for account {account_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/signals")
async def get_trading_signals(
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    only_unexecuted: bool = Query(default=False),
    user_id: str = Depends(get_optional_user_id),
):
    """
    获取交易信号列表
    """
    try:
        query = {}
        if only_unexecuted:
            query["status"] = SignalStatus.PENDING
        
        total = await mongo_manager.count(C.TRADING_SIGNALS, query)
        
        records = await mongo_manager.find_many(
            C.TRADING_SIGNALS,
            query,
            sort=[("generated_at", -1)],
            skip=offset,
            limit=limit
        )
        
        signals = []
        for record in records:
            signals.append(TradingSignal(
                signal_id=record["signal_id"],
                ts_code=record["ts_code"],
                stock_name=record["stock_name"],
                strategy=record["strategy"],
                signal_type=record["signal_type"],
                price=record["price"],
                suggest_quantity=record["suggest_quantity"],
                confidence=record["confidence"],
                reason=record["reason"],
                generated_at=record["generated_at"],
                expired_at=record["expired_at"],
                status=record.get("status", SignalStatus.PENDING),
                executed_time=record.get("executed_time"),
                executed_account_id=record.get("executed_account_id"),
                executed_trade_id=record.get("executed_trade_id"),
                created_at=record["created_at"],
                updated_at=record["updated_at"]
            ))
        
        return {
            "total": total,
            "items": signals
        }
        
    except Exception as e:
        logger.exception(f"Failed to get trading signals: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/signals/{signal_id}/execute")
async def execute_signal(
    signal_id: str,
    request: ExecuteSignalRequest,
    user_id: str = Depends(get_optional_user_id),
):
    """
    执行指定交易信号
    """
    try:
        # 验证账户归属
        account = await mongo_manager.find_one(
            "sim_accounts",
            {"account_id": request.account_id, "user_id": user_id}
        )
        
        if not account:
            raise HTTPException(status_code=404, detail="账户不存在或无权限访问")
        
        # 获取信号
        signal = await mongo_manager.find_one(
            C.TRADING_SIGNALS,
            {"signal_id": signal_id}
        )
        
        if not signal:
            raise HTTPException(status_code=404, detail="信号不存在")
        
        if signal.get("status") != SignalStatus.PENDING:
            raise HTTPException(status_code=400, detail="信号已执行或已过期")
        
        if signal.get("expired_at", datetime.max) < datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="信号已过期")
        
        # 调用模拟交易引擎执行交易
        from core.managers.sim_trading_engine import sim_trading_engine
        
        quantity = request.quantity if request.quantity else signal["suggest_quantity"]
        
        success, message, trade_record = await sim_trading_engine.place_order(
            account_id=request.account_id,
            ts_code=signal["ts_code"],
            stock_name=signal["stock_name"],
            direction=signal["signal_type"],
            quantity=quantity,
            price=signal["price"],
            strategy=signal["strategy"],
            reason=f"执行信号：{signal['reason']}",
            signal_id=signal_id,
        )
        
        if not success:
            raise HTTPException(status_code=400, detail=message)
        
        # 更新信号状态
        now = datetime.now(timezone.utc)
        await mongo_manager.update_one(
            C.TRADING_SIGNALS,
            {"signal_id": signal_id},
            {
                "$set": {
                    "status": SignalStatus.EXECUTED,
                    "executed_time": now,
                    "executed_account_id": request.account_id,
                    "executed_trade_id": trade_record["trade_id"],
                    "updated_at": now
                }
            }
        )
        
        return {
            "success": True,
            "trade_id": trade_record["trade_id"],
            "message": message
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to execute signal {signal_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/signals/generate")
async def trigger_signal_generation(
    trade_date: Optional[str] = Query(default=None, description="指定交易日期，格式YYYYMMDD，默认最近一个交易日"),
    user_id: str = Depends(get_optional_user_id),
):
    """
    手动触发交易信号生成
    """
    try:
        from core.managers.signal_generator import signal_generator
        
        # 生成信号
        signals = await signal_generator.generate_daily_signals(trade_date)
        
        return {
            "success": True,
            "message": f"信号生成完成，共生成 {len(signals)} 个信号",
            "signal_count": len(signals)
        }
        
    except Exception as e:
        logger.exception(f"Failed to trigger signal generation: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/performance/reports")
async def get_performance_reports(
    account_id: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user_id: str = Depends(get_optional_user_id),
):
    """
    获取绩效报告列表
    """
    try:
        query = {}
        if account_id:
            # 验证账户归属
            account = await mongo_manager.find_one(
                "sim_accounts",
                {"account_id": account_id, "user_id": user_id}
            )
            
            if not account:
                raise HTTPException(status_code=404, detail="账户不存在或无权限访问")
            
            query["account_id"] = account_id
        
        total = await mongo_manager.count("performance_reports", query)
        
        records = await mongo_manager.find_many(
            "performance_reports",
            query,
            sort=[("created_at", -1)],
            skip=offset,
            limit=limit
        )
        
        reports = []
        for record in records:
            reports.append(PerformanceReport(
                report_id=record["report_id"],
                account_id=record["account_id"],
                period=record["period"],
                start_date=record["start_date"],
                end_date=record["end_date"],
                total_return_pct=record["total_return_pct"],
                annual_return_pct=record["annual_return_pct"],
                max_drawdown_pct=record["max_drawdown_pct"],
                sharpe_ratio=record["sharpe_ratio"],
                sortino_ratio=record["sortino_ratio"],
                win_rate_pct=record["win_rate_pct"],
                profit_factor=record["profit_factor"],
                total_trades=record["total_trades"],
                winning_trades=record["winning_trades"],
                losing_trades=record["losing_trades"],
                max_consecutive_wins=record["max_consecutive_wins"],
                max_consecutive_losses=record["max_consecutive_losses"],
                avg_profit_per_trade=record["avg_profit_per_trade"],
                avg_loss_per_trade=record["avg_loss_per_trade"],
                created_at=record["created_at"]
            ))
        
        return {
            "total": total,
            "items": reports
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get performance reports: {e}")
        raise HTTPException(status_code=500, detail=str(e))
