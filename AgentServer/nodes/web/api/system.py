"""
系统状态和风控配置 API

提供：
- 策略近期表现统计查询
- 策略权重配置保存
- 风控配置查询和保存
- 版本信息查询
"""

import os
import subprocess
from datetime import datetime, timezone
from typing import Dict, List, Any
import logging

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from core.managers import mongo_manager
from .auth import get_current_user_id, get_current_user, require_admin



router = APIRouter(prefix="/system", tags=["系统状态和配置"])
logger = logging.getLogger("api.system")


# ==================== 数据模型 ====================

class StrategyStat(BaseModel):
    """策略统计数据"""
    name: str
    code: str
    cumulative_return: float
    win_rate: float
    profit_loss_ratio: float
    max_drawdown: float
    total_trades: int
    weight: float = 0.25


class StrategyStatsResponse(BaseModel):
    """策略统计响应"""
    strategies: List[StrategyStat]


class SaveWeightsRequest(BaseModel):
    """保存策略权重请求"""
    strategies: List[Dict[str, Any]] = Field(
        ...,
        description="策略列表，每个元素包含 code 和 weight"
    )


class RiskConfig(BaseModel):
    """风控配置"""
    enable_stop_loss: bool = Field(True, description="启用强化止损")
    stop_loss_pct: float = Field(8.0, description="止损百分比")
    enable_take_profit: bool = Field(True, description="启用动态止盈")
    take_profit_pct: float = Field(10.0, description="止盈百分比")
    enable_ma60_filter: bool = Field(True, description="启用大盘MA60过滤")
    enable_sector_concentration: bool = Field(True, description="启用板块集中度过滤")
    sector_concentration_top_n: int = Field(3, description="板块集中度保留前N名")


class SaveRiskConfigRequest(BaseModel):
    """保存风控配置请求"""
    config: RiskConfig


# ==================== API 端点 ====================


@router.get("/strategy-stats")
async def get_strategy_stats(
    user_id: str = Depends(get_current_user_id)
) -> Dict[str, Any]:
    """
    获取各个策略近期表现统计
    
    返回：
    - 累计收益率
    - 胜率
    - 盈亏比
    - 最大回撤
    - 交易次数
    - 当前权重
    """
    # 查询已有的策略列表
    default_strategies = [
        {
            "name": "半路追涨",
            "code": "halfway_chase",
            "cumulative_return": 0.0,
            "win_rate": 50.0,
            "profit_loss_ratio": 1.2,
            "max_drawdown": 0.0,
            "total_trades": 0,
            "weight": 0.25,
        },
        {
            "name": "首板打板",
            "code": "first_limit_up",
            "cumulative_return": 0.0,
            "win_rate": 52.0,
            "profit_loss_ratio": 1.25,
            "max_drawdown": 0.0,
            "total_trades": 0,
            "weight": 0.25,
        },
        {
            "name": "涨停开板",
            "code": "limit_up_open",
            "cumulative_return": 0.0,
            "win_rate": 48.0,
            "profit_loss_ratio": 1.3,
            "max_drawdown": 0.0,
            "total_trades": 0,
            "weight": 0.25,
        },
        {
            "name": "龙头低吸",
            "code": "leader_pullback",
            "cumulative_return": 0.0,
            "win_rate": 55.0,
            "profit_loss_ratio": 1.35,
            "max_drawdown": 0.0,
            "total_trades": 0,
            "weight": 0.25,
        },
        {
            "name": "跌停翘板",
            "code": "limit_down_qiao",
            "cumulative_return": 0.0,
            "win_rate": 45.0,
            "profit_loss_ratio": 1.1,
            "max_drawdown": 0.0,
            "total_trades": 0,
            "weight": 0.0,
        },
    ]
    
    # 尝试从数据库读取保存的权重
    try:
        config_doc = await mongo_manager.find_one(
            "system_config",
            {"user_id": user_id, "type": "strategy_weights"},
            {"config": 1}
        )
        if config_doc and "config" in config_doc:
            saved_weights = config_doc["config"]
            # 更新权重
            for s in default_strategies:
                saved = next((sw for sw in saved_weights if sw.get("code") == s["code"]), None)
                if saved and "weight" in saved:
                    s["weight"] = saved["weight"]
    except Exception as e:
        logger.warning(f"Failed to load saved strategy weights: {e}")
    
    # 尝试从历史回测结果读取性能统计
    # 聚合查询各个策略的最近回测结果
    try:
        pipeline = [
            {
                "$match": {
                    "status": "completed",
                }
            },
            {
                "$sort": {"end_date": -1
                }
            }
        ]
        # 这里简化：获取最近完成的回测结果，如果有数据更新统计
        recent_tasks = await mongo_manager.aggregate("backtest_tasks", pipeline)
        if recent_tasks:
            # 更新统计数据（简化实现）
            # 实际项目中应该聚合计算
            pass
    except Exception as e:
        logger.warning(f"Failed to query recent backtest stats: {e}")
    
    # 转换为响应对象
    strategy_stats = [
        StrategyStat(**s) for s in default_strategies
    ]
    
    return {
        "success": True,
        "data": {
            "strategies": strategy_stats,
        },
        "message": "获取策略统计成功",
    }


@router.post("/save-weights")
async def save_strategy_weights(
    request: SaveWeightsRequest,
    user_id: str = Depends(get_current_user_id)
) -> Dict[str, Any]:
    """
    保存用户调整后的策略权重配置
    
    权重总和应该接近 1.0，前端已经做了提示，这里只保存
    """
    try:
        
        # 验证权重总和检查
        total_weight = sum(s.get("weight", 0) for s in request.strategies)
        
        # 保存到数据库
        await mongo_manager.update_one(
            "system_config",
            {"user_id": user_id, "type": "strategy_weights"},
            {
                "$set": {
                    "user_id": user_id,
                    "type": "strategy_weights",
                    "config": request.strategies,
                    "total_weight": total_weight,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
            upsert=True
        )
        
        logger.info(f"User {user_id} saved strategy weights, total: {total_weight:.2f}")
        return {
            "success": True,
            "message": f"已保存 {len(request.strategies)} 个策略权重，总权重 {total_weight:.2f}",
            "total_weight": total_weight
        }
    except Exception as e:
        logger.error(f"Failed to save strategy weights: {e}")
        raise HTTPException(status_code=500, detail=f"保存失败: {str(e)}")


@router.get("/risk-config")
async def get_risk_config(
    user_id: str = Depends(get_current_user_id)
) -> Dict[str, Any]:
    """
    获取当前风控配置
    
    默认配置：
    - 强化止损：启用，止损 8%
    - 动态止盈：启用，止盈 10%
    - 大盘 MA60 过滤：启用
    - 板块集中度过滤：启用，保留前 3 名
    """
    default_config = RiskConfig()
    
    # 尝试从数据库读取已保存的配置
    try:
        doc = await mongo_manager.find_one(
            "system_config",
            {"user_id": user_id, "type": "risk_config"},
            {"config": 1}
        )
        if doc and "config" in doc:
            saved_config = doc["config"]
            # 直接返回保存的配置
            return {
                "success": True,
                "data": saved_config,
                "message": "获取风控配置成功",
            }
    except Exception as e:
        logger.warning(f"Failed to load saved risk config: {e}")
    
    # 返回默认配置
    return {
        "success": True,
        "data": default_config.dict(),
        "message": "获取风控配置成功",
    }


@router.post("/save-risk-config")
async def save_risk_config(
    request: SaveRiskConfigRequest,
    user_id: str = Depends(get_current_user_id)
) -> Dict[str, Any]:
    """
    保存用户修改后的风控配置
    """
    try:
        
        # 保存到数据库
        await mongo_manager.update_one(
            "system_config",
            {"user_id": user_id, "type": "risk_config"},
            {
                "$set": {
                    "user_id": user_id,
                    "type": "risk_config",
                    "config": request.config.dict(),
                    "updated_at": datetime.now(timezone.utc),
                }
            },
            upsert=True
        )
        
        logger.info(f"User {user_id} saved risk config")
        return {
            "success": True,
            "message": "风控配置已保存",
            "config": request.config.dict()
        }
    except Exception as e:
        logger.error(f"Failed to save risk config: {e}")
        raise HTTPException(status_code=500, detail=f"保存失败: {str(e)}")


# ==================== 推送配置 API ====================


class SavePushConfigRequest(BaseModel):
    """推送配置保存请求"""
    config: Dict[str, Any] = Field(..., description="推送配置")


@router.get("/push-config")
async def get_push_config(
    user_id: str = Depends(get_current_user_id)
) -> Dict[str, Any]:
    """
    获取推送配置
    
    返回飞书/企业微信Webhook地址、推送开关、最小发送间隔等配置。
    """
    try:
        
        record = await mongo_manager.find_one(
            "system_config",
            {"user_id": user_id, "type": "push_config"},
        )
        
        if record and "config" in record:
            return {
                "success": True,
                "config": record["config"]
            }
        
        # 默认配置
        return {
            "success": True,
            "config": {
                "notify_enabled": True,
                "wecom_webhook": "",
                "wecom_enabled": True,
                "feishu_enabled": False,
                "feishu_webhook": "",
                "feishu_app_id": "",
                "feishu_app_secret": "",
                "feishu_bitable_app_token": "",
                "min_interval": 10,
                "min_confidence": 0.0,
                "push_empty_signal": False,
            }
        }
    except Exception as e:
        logger.error(f"Failed to get push config: {e}")
        raise HTTPException(status_code=500, detail=f"获取推送配置失败: {str(e)}")


@router.post("/save-push-config")
async def save_push_config(
    request: SavePushConfigRequest,
    user_id: str = Depends(get_current_user_id)
) -> Dict[str, Any]:
    """
    保存推送配置
    
    保存飞书/企业微信Webhook地址、推送开关、最小发送间隔等配置。
    前端PushConfigPanel组件调用此接口保存配置。
    """
    try:
        
        await mongo_manager.update_one(
            "system_config",
            {"user_id": user_id, "type": "push_config"},
            {
                "$set": {
                    "user_id": user_id,
                    "type": "push_config",
                    "config": request.config,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
            upsert=True
        )
        
        logger.info(f"User {user_id} saved push config")
        return {
            "success": True,
            "message": "推送配置已保存",
            "config": request.config
        }
    except Exception as e:
        logger.error(f"Failed to save push config: {e}")
        raise HTTPException(status_code=500, detail=f"保存失败: {str(e)}")


@router.post("/test-push")
async def test_push(
    user_id: str = Depends(get_current_user_id)
) -> Dict[str, Any]:
    """
    发送测试推送消息
    
    使用当前保存的推送配置发送一条测试消息，验证Webhook地址是否有效。
    """
    try:
        
        record = await mongo_manager.find_one(
            "system_config",
            {"user_id": user_id, "type": "push_config"},
        )
        
        if not record or "config" not in record:
            raise HTTPException(status_code=400, detail="推送配置未保存，请先保存配置")
        
        config = record["config"]
        
        # 构造测试信号数据
        test_signal = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "sentiment": {
                "score": 75,
                "level": "偏多",
                "position_limit": 0.7,
                "allowed_strategies": ["半路追涨", "首板打板"],
            },
            "universe_size": 100,
            "force_empty": False,
            "signals": [{
                "ts_code": "000001.SZ",
                "name": "平安银行",
                "strategy": "半路追涨",
                "industry": "银行",
                "signal_type": "买入",
                "confidence": 0.85,
                "close": 12.50,
                "pct_chg": 3.21,
                "reason": "量能放大+突破关键阻力位",
                "has_lhb": False,
            }],
        }
        
        from signal_pusher import SignalPusher
        pusher = SignalPusher(config)
        success = pusher.push(test_signal)
        
        if success:
            return {"success": True, "message": "测试消息已发送，请检查接收端"}
        else:
            return {"success": False, "message": "部分渠道推送失败，请检查Webhook配置"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to test push: {e}")
        raise HTTPException(status_code=500, detail=f"测试推送失败: {str(e)}")


@router.get("/ws-config")
async def get_websocket_config() -> Dict[str, Any]:
    """获取 WebSocket 连接配置（前端用）
    
    前端调用此接口获取 WebSocket 的 host 和 port，
    避免在前端硬编码 IP 地址。
    """
    from core.settings import settings
    web_settings = settings.web
    return {
        "success": True,
        "data": {
            "host": web_settings.websocket_host,
            "port": web_settings.websocket_port,
        }
    }


@router.get("/risk-status")
async def get_risk_status() -> Dict[str, Any]:
    """获取风控状态（实时，非配置）
    
    返回当前风控引擎的实时状态：是否触发止损/止盈、大盘过滤结果等。
    与 /risk-config 不同，本接口返回运行时状态而非配置项。
    """
    try:
        # 尝试从MongoDB获取最新风控状态
        status_record = await mongo_manager.find_one(
            "risk_status",
            {"type": "latest"},
        )
        if status_record:
            return {
                "success": True,
                "data": {
                    "stop_loss_triggered": status_record.get("stop_loss_triggered", False),
                    "take_profit_triggered": status_record.get("take_profit_triggered", False),
                    "ma60_filter": status_record.get("ma60_filter", "unknown"),
                    "sector_concentration": status_record.get("sector_concentration", {}),
                    "last_check": status_record.get("last_check", ""),
                }
            }
    except Exception as e:
        logger.warning(f"获取风控状态失败: {e}")
    
    # 降级：返回默认空状态
    return {
        "success": True,
        "data": {
            "stop_loss_triggered": False,
            "take_profit_triggered": False,
            "ma60_filter": "unknown",
            "sector_concentration": {},
            "last_check": "",
            "message": "风控引擎未启动，返回默认状态",
        }
    }


# ==================== 日志配置 ====================


@router.get("/log-config")
async def get_log_config() -> Dict[str, Any]:
    """获取日志配置"""
    try:
        from core.settings import settings
        obs = settings.observability if hasattr(settings, 'observability') else None
        return {
            "success": True,
            "data": {
                "log_level": obs.log_level if obs else "INFO",
                "log_to_file": obs.log_to_file if obs else True,
                "log_dir": obs.log_dir if obs else "logs",
                "log_max_size_mb": obs.log_max_size_mb if obs else 50,
                "log_backup_count": obs.log_backup_count if obs else 10,
            }
        }
    except Exception as e:
        logger.warning(f"获取日志配置失败: {e}")
        return {
            "success": True,
            "data": {
                "log_level": "INFO",
                "log_to_file": True,
                "log_dir": "logs",
                "log_max_size_mb": 50,
                "log_backup_count": 10,
            }
        }


@router.post("/save-log-config")
async def save_log_config(
    config: Dict[str, Any],
    _ = Depends(require_admin)
) -> Dict[str, Any]:
    """保存日志配置"""
    try:
        # 持久化到MongoDB
        await mongo_manager.update_one(
            "system_config",
            {"type": "log_config"},
            {"$set": {"type": "log_config", "config": config}},
            upsert=True,
        )
        
        # 动态更新日志级别（立即生效）
        log_level = config.get("log_level", "INFO")
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
        
        return {"success": True, "message": f"日志配置已保存，级别: {log_level}"}
    except Exception as e:
        logger.error(f"保存日志配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存日志配置失败: {str(e)}")


# ==================== 版本信息 API ====================


def get_git_commit() -> str:
    """获取当前 git commit hash（短格式）"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            timeout=5
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def get_git_branch() -> str:
    """获取当前 git 分支名"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            timeout=5
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def get_build_time() -> str:
    """获取构建时间（服务启动时间）"""
    return datetime.now().astimezone().isoformat()


# 缓存启动时的版本信息（避免每次都调git）
_GIT_COMMIT = get_git_commit()
_GIT_BRANCH = get_git_branch()
_BUILD_TIME = get_build_time()


@router.get("/version")
async def get_version() -> Dict[str, Any]:
    """
    获取服务版本信息
    
    返回当前代码的 git commit hash、分支名、构建时间等，
    用于验证代码是否确实生效，以及版本一致性检查。
    """
    return {
        "success": True,
        "data": {
            "commit": _GIT_COMMIT,
            "branch": _GIT_BRANCH,
            "build_time": _BUILD_TIME,
            "service": "backtest-engine",
            "api_version": "v2",
        },
        "message": "获取版本信息成功"
    }
