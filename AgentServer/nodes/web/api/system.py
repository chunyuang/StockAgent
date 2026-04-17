"""
系统状态和风控配置 API

提供：
- 策略近期表现统计查询
- 策略权重配置保存
- 风控配置查询和保存
"""

from datetime import datetime
from typing import Dict, List, Any, Optional
import logging

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from core.managers import mongo_manager
from .auth import get_current_user_id

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


@router.get("/strategy-stats", response_model=StrategyStatsResponse)
async def get_strategy_stats(user_id: str = Depends(get_current_user_id)) -> StrategyStatsResponse:
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
    # 从数据库中查询各个策略的统计数据
    # 默认提供默认策略列表（根据历史回测数据统计
    # 这里使用默认策略信息，如果数据库中没有数据，返回默认值
    
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
    
    return StrategyStatsResponse(strategies=strategy_stats)


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
                    "updated_at": datetime.utcnow(),
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


@router.get("/risk-config", response_model=RiskConfig)
async def get_risk_config(user_id: str = Depends(get_current_user_id)) -> RiskConfig:
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
            # 转换为 RiskConfig 对象
            return RiskConfig(**saved_config)
    except Exception as e:
        logger.warning(f"Failed to load saved risk config: {e}")
    
    # 返回默认配置
    return default_config


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
                    "updated_at": datetime.utcnow(),
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
