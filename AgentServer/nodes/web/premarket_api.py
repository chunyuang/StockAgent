"""
盘前信号 API 端点

提供手动触发信号生成、查询信号、调度器管理的 REST API。
集成到 Web 节点的 FastAPI 路由中。

端点：
  POST /api/v1/premarket/signals/generate   — 手动触发盘前信号生成
  POST /api/v1/premarket/signals/review      — 手动触发盘后回顾
  GET  /api/v1/premarket/signals             — 查询盘前信号列表
  GET  /api/v1/premarket/signals/{date}      — 查询指定日期的信号
  GET  /api/v1/premarket/scheduler/status    — 查询调度器状态
  POST /api/v1/premarket/scheduler/start     — 启动定时调度
  POST /api/v1/premarket/scheduler/stop      — 停止定时调度
"""

import logging
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel, Field

from core.managers import mongo_manager
from .auth import get_optional_user_id

logger = logging.getLogger("api.premarket")

router = APIRouter(prefix="/premarket", tags=["Premarket Signals"])


# ==================== 数据模型 ====================

class SignalGenerateRequest(BaseModel):
    """手动触发信号生成请求"""
    trade_date: Optional[str] = Field(None, description="交易日期(YYYYMMDD)，默认最近交易日")


class SignalGenerateResponse(BaseModel):
    """信号生成响应"""
    success: bool
    signal_id: str
    date: str
    force_empty: bool
    signal_count: int
    trading_plan: str
    message: str


class ReviewRequest(BaseModel):
    """盘后回顾请求"""
    trade_date: Optional[str] = Field(None, description="交易日期(YYYYMMDD)")


class ReviewResponse(BaseModel):
    """盘后回顾响应"""
    success: bool
    date: str
    signal_count: int
    executed_count: int
    expired_count: int
    message: str


class SchedulerStatusResponse(BaseModel):
    """调度器状态响应"""
    running: bool
    jobs: List[dict]


# ==================== API 端点 ====================

@router.post("/signals/generate", response_model=SignalGenerateResponse)
async def generate_signals(
    request: SignalGenerateRequest = SignalGenerateRequest(),
    user_id: str = Depends(get_optional_user_id),
):
    """手动触发盘前信号生成"""
    try:
        from nodes.web.premarket_signal_scheduler import get_premarket_scheduler
        scheduler = get_premarket_scheduler()
        result = await scheduler.generate_premarket_signals(request.trade_date)

        return SignalGenerateResponse(
            success=True,
            signal_id=result["signal_id"],
            date=result["date"],
            force_empty=result["force_empty"],
            signal_count=result.get("signal_count", 0),
            trading_plan=result.get("trading_plan", ""),
            message=f"盘前信号生成完成，选中{result.get('signal_count', 0)}只标的",
        )
    except Exception as e:
        logger.exception(f"盘前信号生成失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/signals/review", response_model=ReviewResponse)
async def generate_review(
    request: ReviewRequest = ReviewRequest(),
    user_id: str = Depends(get_optional_user_id),
):
    """手动触发盘后回顾"""
    try:
        from nodes.web.premarket_signal_scheduler import get_premarket_scheduler
        scheduler = get_premarket_scheduler()
        result = await scheduler.generate_postmarket_review(request.trade_date)

        return ReviewResponse(
            success=True,
            date=result["date"],
            signal_count=result.get("signal_count", 0),
            executed_count=result.get("executed_count", 0),
            expired_count=result.get("expired_count", 0),
            message=f"盘后回顾完成，信号{result.get('signal_count', 0)}个，执行{result.get('executed_count', 0)}笔",
        )
    except Exception as e:
        logger.exception(f"盘后回顾失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/signals")
async def get_signals(
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    date: Optional[str] = Query(default=None, description="指定日期(YYYYMMDD)"),
    user_id: str = Depends(get_optional_user_id),
):
    """查询盘前信号列表"""
    try:
        query = {}
        if date:
            query["date"] = date

        total = await mongo_manager.count("daily_premarket_signals", query)

        records = await mongo_manager.find_many(
            "daily_premarket_signals",
            query,
            sort=[("generated_at", -1)],
            skip=offset,
            limit=limit,
        )

        # 精简返回：signals数组只保留关键字段
        for record in records:
            if "signals" in record:
                record["signals"] = [
                    {
                        "ts_code": s.get("ts_code"),
                        "name": s.get("name"),
                        "strategy": s.get("strategy"),
                        "close": s.get("close"),
                        "pct_chg": s.get("pct_chg"),
                    }
                    for s in record["signals"]
                ]
            # 移除过长的交易计划文本
            record.pop("trading_plan", None)

        return {"total": total, "items": records}
    except Exception as e:
        logger.exception(f"查询盘前信号失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/signals/{date}")
async def get_signal_by_date(
    date: str,
    user_id: str = Depends(get_optional_user_id),
):
    """查询指定日期的完整信号详情"""
    try:
        record = await mongo_manager.find_one(
            "daily_premarket_signals",
            {"date": date},
        )

        if not record:
            raise HTTPException(status_code=404, detail=f"未找到 {date} 的信号记录")

        return record
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"查询盘前信号详情失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scheduler/status", response_model=SchedulerStatusResponse)
async def get_scheduler_status(
    user_id: str = Depends(get_optional_user_id),
):
    """查询调度器状态"""
    try:
        from nodes.web.premarket_signal_scheduler import get_premarket_scheduler
        scheduler = get_premarket_scheduler()
        info = scheduler.get_scheduler_info()
        return SchedulerStatusResponse(
            running=info.get("running", False),
            jobs=info.get("jobs", []),
        )
    except Exception as e:
        logger.exception(f"查询调度器状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/scheduler/start")
async def start_scheduler(
    user_id: str = Depends(get_optional_user_id),
):
    """启动定时调度"""
    try:
        from nodes.web.premarket_signal_scheduler import get_premarket_scheduler
        scheduler = get_premarket_scheduler()

        if scheduler.is_running:
            return {"success": True, "message": "调度器已在运行中"}

        await scheduler.start_scheduler()
        return {"success": True, "message": "定时调度已启动"}
    except Exception as e:
        logger.exception(f"启动调度器失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/scheduler/stop")
async def stop_scheduler(
    user_id: str = Depends(get_optional_user_id),
):
    """停止定时调度"""
    try:
        from nodes.web.premarket_signal_scheduler import get_premarket_scheduler
        scheduler = get_premarket_scheduler()
        await scheduler.stop_scheduler()
        return {"success": True, "message": "定时调度已停止"}
    except Exception as e:
        logger.exception(f"停止调度器失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# 导出路由
premarket_router = router
