#!/usr/bin/env python3
"""
调度器 REST API 接口

为 DailyScheduler 提供 REST 控制接口：
  POST /api/v1/scheduler/start          — 启动定时调度
  POST /api/v1/scheduler/stop           — 停止定时调度
  GET  /api/v1/scheduler/status         — 获取调度器状态
  POST /api/v1/scheduler/trigger/{phase} — 手动触发指定阶段

状态变更通过 Redis Pub/Sub 推送到前端 WebSocket：
  - scheduler:status 频道：调度器启停状态
  - scheduler:phase 频道：阶段执行进度（开始/步骤/完成/失败）
"""

import json
import asyncio
import logging
from datetime import datetime
from typing import Dict, Optional, Any, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("api.scheduler")


# ==================== Redis 频道常量 ====================

CHANNEL_SCHEDULER_STATUS = "scheduler:status"
CHANNEL_SCHEDULER_PHASE = "scheduler:phase"


# ==================== 请求/响应模型 ====================

class SchedulerStartRequest(BaseModel):
    """启动调度请求"""
    account_id: Optional[str] = Field(None, description="模拟账户ID，不填则使用默认活跃账户")
    config: Optional[Dict[str, Any]] = Field(None, description="覆盖默认配置")


class SchedulerStopRequest(BaseModel):
    """停止调度请求"""
    force: bool = Field(False, description="是否强制停止（等待当前任务完成）")


class TriggerRequest(BaseModel):
    """手动触发请求"""
    trade_date: Optional[str] = Field(None, description="交易日期YYYYMMDD，不填则使用当天")
    account_id: Optional[str] = Field(None, description="模拟账户ID")


class TriggerResponse(BaseModel):
    """手动触发响应"""
    success: bool
    phase: str
    trade_date: str
    result: Optional[Dict] = None
    message: str


# ==================== 调度器单例管理 ====================

# 全局调度器实例（延迟初始化）
_scheduler_instance: Optional[Any] = None
_scheduler_lock = asyncio.Lock()


async def get_scheduler() -> Any:
    """获取调度器实例(回测模式下返回占位对象)"""
    global _scheduler_instance
    async with _scheduler_lock:
        if _scheduler_instance is not None:
            return _scheduler_instance
        try:
            from nodes.scheduler.daily_scheduler import DailyScheduler
            _scheduler_instance = DailyScheduler()
            logger.info("DailyScheduler(实盘调度)加载成功")
            return _scheduler_instance
        except ImportError:
            pass
        try:
            from daily_scheduler import DailyScheduler
            _scheduler_instance = DailyScheduler()
            return _scheduler_instance
        except ImportError:
            logger.info("DailyScheduler未安装, 使用回测模式占位")
            _scheduler_instance = _StubScheduler()
            return _scheduler_instance
        except Exception as e:
            logger.error(f"DailyScheduler初始化失败: {e}")
            raise HTTPException(status_code=500, detail=f"调度器初始化失败: {str(e)}")


class _StubScheduler:
    """调度器占位: 回测模式不需要实盘调度"""
    is_stub = True
    
    async def run_premarket(self, trade_date):
        return {"success": False, "steps": [], "errors": ["回测模式: 调度器未安装"], "message": "请使用交易信号页面手动生成信号"}
    
    async def run_intraday(self, trade_date):
        return {"success": False, "steps": [], "errors": ["回测模式: 调度器未安装"], "message": "请使用今日持仓页面查看持仓"}
    
    async def run_postmarket(self, trade_date):
        return {"success": False, "steps": [], "errors": ["回测模式: 调度器未安装"], "message": "请使用绩效报告页面查看报告"}
    
    async def run_full_day(self, trade_date):
        return {"success": False, "steps": [], "errors": ["回测模式: 调度器未安装"], "message": "回测模式不支持全天调度"}
    
    async def start(self):
        return {"success": True, "message": "回测模式: 调度器占位启动"}
    
    async def stop(self):
        return {"success": True, "message": "回测模式: 调度器占位停止"}
    
    def get_status(self):
        return {"is_running": False, "mode": "backtest", "message": "回测模式, 无实盘调度"}
    
    @property
    def account_id(self):
        return "backtest_mode"
    
    SCHEDULE_TIMES = {}
    
    def get_data_alerts(self, severity=None):
        return []
    
    def clear_data_alerts(self, before_date=None):
        pass
    
    def get_schedule_history(self, days=7):
        return []

def reset_scheduler():
    """重置调度器单例（测试用）"""
    global _scheduler_instance
    _scheduler_instance = None


# ==================== Redis 推送辅助 ====================

async def _publish_scheduler_event(channel: str, data: Dict):
    """发布调度器事件到 Redis"""
    try:
        from core.managers import redis_manager
        await redis_manager.publish(channel, json.dumps(data, ensure_ascii=False, default=str))
    except Exception as e:
        logger.warning(f"Redis 发布失败 [{channel}]: {e}")


async def _publish_status_change(action: str, details: Dict = None):
    """发布调度器状态变更"""
    await _publish_scheduler_event(CHANNEL_SCHEDULER_STATUS, {
        "action": action,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "details": details or {},
    })


async def _publish_phase_event(phase: str, event: str, trade_date: str, data: Dict = None):
    """发布阶段执行事件"""
    await _publish_scheduler_event(CHANNEL_SCHEDULER_PHASE, {
        "phase": phase,
        "event": event,  # started / step_completed / completed / failed
        "trade_date": trade_date,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data": data or {},
    })


# ==================== 路由 ====================

router = APIRouter(prefix="/scheduler", tags=["调度器管理"])


@router.post("/start")
async def start_scheduler(req: SchedulerStartRequest = None):
    """启动定时调度

    启动 APScheduler 定时调度，按配置的时间点自动执行盘前/盘中/盘后流程。
    状态变更通过 Redis scheduler:status 频道推送。
    """
    if req is None:
        req = SchedulerStartRequest()

    scheduler = await get_scheduler()

    if scheduler.is_running:
        return {
            "success": False,
            "message": "调度器已在运行中",
            "status": scheduler.get_status(),
        }

    try:
        # 如果指定了 account_id，重建调度器
        if req.account_id:
            global _scheduler_instance
            try:
                from daily_scheduler import DailyScheduler
                config = req.config or {}
                _scheduler_instance = DailyScheduler(account_id=req.account_id, config=config)
                scheduler = _scheduler_instance
            except ImportError:
                _scheduler_instance = _StubScheduler()
                scheduler = _scheduler_instance
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"调度器重建失败: {str(e)}")

        await scheduler.start()

        # 推送状态变更
        await _publish_status_change("started", {
            "account_id": scheduler.account_id,
            "schedule_times": scheduler.SCHEDULE_TIMES,
        })

        return {
            "success": True,
            "message": "调度器已启动",
            "status": scheduler.get_status(),
        }

    except Exception as e:
        logger.error(f"启动调度器失败: {e}")
        raise HTTPException(status_code=500, detail=f"启动调度器失败: {str(e)}")


@router.post("/stop")
async def stop_scheduler(req: SchedulerStopRequest = None):
    """停止定时调度

    停止 APScheduler 定时调度。可选择强制停止或等待当前任务完成。
    状态变更通过 Redis scheduler:status 频道推送。
    """
    if req is None:
        req = SchedulerStopRequest()

    scheduler = await get_scheduler()

    if not scheduler.is_running:
        return {
            "success": False,
            "message": "调度器未在运行",
            "status": scheduler.get_status(),
        }

    try:
        await scheduler.stop()

        # 推送状态变更
        await _publish_status_change("stopped", {
            "force": req.force,
            "account_id": scheduler.account_id,
        })

        return {
            "success": True,
            "message": "调度器已停止",
            "status": scheduler.get_status(),
        }

    except Exception as e:
        logger.error(f"停止调度器失败: {e}")
        raise HTTPException(status_code=500, detail=f"停止调度器失败: {str(e)}")


@router.get("/status")
async def get_scheduler_status():
    """获取调度器状态

    返回调度器运行状态、各模块就绪情况、定时任务列表、数据告警统计。
    """
    try:
        scheduler = await get_scheduler()
        status = scheduler.get_status()
        return {
            "success": True,
            "data": status,
        }
    except Exception as e:
        logger.error(f"获取调度器状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取状态失败: {str(e)}")


@router.post("/trigger/{phase}")
async def trigger_phase(phase: str, req: TriggerRequest = None):
    """手动触发指定阶段

    Args:
        phase: 调度阶段 — premarket / intraday / postmarket / full
        trade_date: 交易日期（可选，默认当天）

    阶段执行进度通过 Redis scheduler:phase 频道推送：
    - started: 阶段开始
    - step_completed: 每个步骤完成
    - completed: 阶段完成
    - failed: 阶段失败
    """
    if req is None:
        req = TriggerRequest()

    valid_phases = ["premarket", "intraday", "postmarket", "full"]
    if phase not in valid_phases:
        raise HTTPException(
            status_code=400,
            detail=f"无效阶段: {phase}，可选: {', '.join(valid_phases)}",
        )

    trade_date = req.trade_date or datetime.now().strftime("%Y%m%d")

    # 如果指定了不同的 account_id，重建调度器
    if req.account_id:
        global _scheduler_instance
        try:
            from daily_scheduler import DailyScheduler
            _scheduler_instance = DailyScheduler(account_id=req.account_id)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"调度器重建失败: {str(e)}")

    scheduler = await get_scheduler()

    # 发布阶段开始事件
    await _publish_phase_event(phase, "started", trade_date)

    try:
        if phase == "premarket":
            result = await scheduler.run_premarket(trade_date)
        elif phase == "intraday":
            result = await scheduler.run_intraday(trade_date)
        elif phase == "postmarket":
            result = await scheduler.run_postmarket(trade_date)
        elif phase == "full":
            result = await scheduler.run_full_day(trade_date)

        # 转换结果
        from dataclasses import asdict
        result_dict = asdict(result) if hasattr(result, '__dataclass_fields__') else result

        # 发布完成事件
        event_type = "completed" if result_dict.get("success", True) else "failed"
        await _publish_phase_event(phase, event_type, trade_date, {
            "steps_count": len(result_dict.get("steps", [])),
            "errors_count": len(result_dict.get("errors", [])),
            "errors": result_dict.get("errors", []),
        })

        return TriggerResponse(
            success=result_dict.get("success", True),
            phase=phase,
            trade_date=trade_date,
            result=result_dict,
            message=f"阶段 {phase} 执行{'成功' if result_dict.get('success', True) else '失败'}",
        )

    except Exception as e:
        logger.error(f"手动触发 {phase} 失败: {e}")

        # 发布失败事件
        await _publish_phase_event(phase, "failed", trade_date, {
            "error": str(e),
        })

        raise HTTPException(status_code=500, detail=f"阶段 {phase} 执行失败: {str(e)}")


# ==================== 数据告警接口 ====================

@router.get("/alerts")
async def get_data_alerts(severity: str = None):
    """获取数据告警列表

    Args:
        severity: 过滤级别 critical/warning/info，不填返回全部
    """
    try:
        scheduler = await get_scheduler()
        alerts = scheduler.get_data_alerts(severity=severity)
        return {
            "success": True,
            "data": alerts,
            "total": len(alerts),
        }
    except Exception as e:
        logger.error(f"获取数据告警失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取告警失败: {str(e)}")


@router.delete("/alerts")
async def clear_data_alerts(before_date: str = None):
    """清除数据告警

    Args:
        before_date: 清除此日期之前的告警（YYYYMMDD），不填则清除全部
    """
    try:
        scheduler = await get_scheduler()
        scheduler.clear_data_alerts(before_date=before_date)
        return {
            "success": True,
            "message": f"告警已清除{f'（{before_date}之前）' if before_date else ''}",
        }
    except Exception as e:
        logger.error(f"清除告警失败: {e}")
        raise HTTPException(status_code=500, detail=f"清除告警失败: {str(e)}")


# ==================== 调度历史接口 ====================

@router.get("/history")
async def get_schedule_history(days: int = 7):
    """获取最近N天的调度执行历史

    从 MongoDB daily_schedule_results 集合查询。
    """
    try:
        from core.managers import mongo_manager

        if not mongo_manager.mongo_client:
            return {"success": True, "data": [], "message": "MongoDB未连接"}

        db = mongo_manager.mongo_client[mongo_manager.database_name]
        collection = db["daily_schedule_results"]

        from datetime import timedelta
        since = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

        cursor = collection.find(
            {"trade_date": {"$gte": since}},
            {"_id": 0}
        ).sort("trade_date", -1).limit(100)

        results = await cursor.to_list(length=100)
        return {
            "success": True,
            "data": results,
            "total": len(results),
        }

    except Exception as e:
        logger.error(f"获取调度历史失败: {e}")
        return {"success": True, "data": [], "message": f"查询失败: {str(e)}"}
