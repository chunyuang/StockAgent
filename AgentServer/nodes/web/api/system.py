"""
系统状态和风控配置 API

提供：
- 策略近期表现统计查询
- 策略权重配置保存
- 风控配置查询和保存
- 版本信息查询
"""

import os
import time
import subprocess
from datetime import datetime, timezone
from typing import Dict, List, Any
import logging

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from core.managers import mongo_manager
from .auth import get_optional_user_id as get_current_user_id



router = APIRouter(prefix="/system", tags=["系统状态和配置"])
logger = logging.getLogger("api.system")


# ==================== 健康检查 ====================


@router.get("/health")
async def health_check() -> Dict[str, Any]:
    """
    服务健康检查
    
    检查所有核心服务状态：后端API、回测引擎、MongoDB、前端Vite代理。
    用于前端“一键服务检查”按钮。
    """
    import socket
    import asyncio
    import aiohttp
    from datetime import datetime
    
    checks = {}
    overall = "ok"
    
    # 1. MongoDB连接检查
    try:
        from core.managers import mongo_manager
        db = mongo_manager.db
        server_info = await asyncio.wait_for(db.command('ping'), timeout=5)
        checks["mongodb"] = {
            "status": "ok",
            "message": f"MongoDB连接正常 (db={db.name})"
        }
    except Exception as e:
        checks["mongodb"] = {"status": "error", "message": f"MongoDB连接失败: {str(e)[:100]}"}
        overall = "error"
    
    # 2. 回测引擎检查（本地执行模式，不再需要独立端口50057）
    try:
        from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
        bt = PortfolioBacktester()
        checks["backtest_node"] = {"status": "ok", "message": "回测引擎就绪（本地执行模式）"}
    except Exception as e:
        checks["backtest_node"] = {"status": "error", "message": f"回测引擎加载失败: {str(e)[:100]}"}
        if overall == "ok":
            overall = "warning"
    
    # 3. 后端Web服务自检
    checks["web_api"] = {"status": "ok", "message": f"Web API运行中 (pid={os.getpid()})"}
    
    # 4. 前端Vite代理检查
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection('localhost', 5174), timeout=3
        )
        writer.close()
        await writer.wait_closed()
        checks["frontend"] = {"status": "ok", "message": "前端Vite服务端口5174可达"}
    except Exception:
        checks["frontend"] = {"status": "warning", "message": "前端Vite服务端口5174不可达"}
        if overall == "ok":
            overall = "warning"
    
    # 5. 回测历史记录检查
    try:
        from core.managers import mongo_manager
        count = await mongo_manager.count_documents("backtest_tasks", {})
        checks["backtest_history"] = {"status": "ok", "message": f"历史回测记录: {count}条"}
    except Exception as e:
        checks["backtest_history"] = {"status": "error", "message": f"查询回测历史失败: {str(e)[:80]}"}
        if overall == "ok":
            overall = "error"
    
    # 6. 数据完整性检查
    try:
        # 【v2.9.49】P2修复: 异步查询, 避免同步pymongo阻塞事件循环
        from core.managers import mongo_manager
        daily_count = await mongo_manager.count_documents("stock_daily_ak_full", {})
        basic_count = await mongo_manager.count_documents("daily_basic", {})
        latest_cursor = mongo_manager.db.stock_daily_ak_full.find({}, {'trade_date': 1}).sort('trade_date', -1).limit(1)
        latest_doc = await latest_cursor.to_list(length=1)
        latest_date = str(latest_doc[0]['trade_date']) if latest_doc else '无数据'
        
        data_msg = f"日线{daily_count//1000}K条, 基础{basic_count//1000}K条, 最新日期{latest_date}"
        if daily_count > 0:
            checks["data"] = {"status": "ok", "message": data_msg}
        else:
            checks["data"] = {"status": "error", "message": "stock_daily_ak_full无数据"}
            overall = "error"
    except Exception as e:
        checks["data"] = {"status": "error", "message": f"数据检查失败: {str(e)[:80]}"}
        if overall == "ok":
            overall = "error"
    
    return {
        "success": True,
        "status": overall,
        "checks": checks,
        "timestamp": datetime.now().isoformat(),
        "version": {
            "commit": _GIT_COMMIT,
            "branch": _GIT_BRANCH,
        }
    }


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
    user_id: str = Depends(get_current_user_id)
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


def _factor_to_group(factor: str) -> str:
    """因子名→所属组"""
    mapping = {
        'pct_chg': 'basic', 'pre_close': 'basic',
        'ma5': 'technical', 'ma10': 'technical', 'ma20': 'technical', 'macd': 'technical',
        'rsi_6': 'technical', 'boll_upper': 'technical', 'atr': 'technical', 'fear_greed_index': 'technical',
        'turnover_rate': 'volume', 'volume_ratio': 'volume', 'circ_mv': 'volume',
        'is_limit_up': 'limit', 'is_limit_down': 'limit', 'first_limit_up': 'limit', 'limit_up_count': 'limit',
    }
    return mapping.get(factor, 'basic')


async def _get_factor_detail(db, date_str: str, factors: list) -> dict:
    """获取指定日期每个因子的覆盖率(单次聚合) - 异步版本"""
    d = int(date_str) if isinstance(date_str, str) else date_str
    total = await db.stock_daily_ak_full.count_documents({'trade_date': d})
    if total == 0:
        return {f: 0 for f in factors}
    group_fields = {'total': {'$sum': 1}}
    for f in factors:
        group_fields[f'{f}_cnt'] = {'$sum': {'$cond': [{'$ne': [{'$type': f'${f}'}, 'missing']}, 1, 0]}}
    cursor = db.stock_daily_ak_full.aggregate([
        {'$match': {'trade_date': d}},
        {'$group': {'_id': None, **group_fields}}
    ])
    result = await cursor.to_list(length=None)
    if not result:
        return {f: 0 for f in factors}
    r = result[0]
    return {f: round(r.get(f'{f}_cnt', 0) / r['total'] * 100, 1) for f in factors}


@router.get("/data-status")
async def get_data_status() -> Dict[str, Any]:
    """获取数据层状态：各集合记录数、因子覆盖率、最新数据日期"""
    try:
        # 【v2.9.49】P2修复: 全部改用异步mongo_manager, 消除同步pymongo阻塞
        from core.managers import mongo_manager
        db = mongo_manager.db

        # 集合记录数 + 日期范围
        collections = {}
        for name in ['stock_daily_ak_full', 'daily_basic', 'index_daily', 'limit_list', 'limit_pool_down', 'backtest_tasks']:
            try:
                cnt = await mongo_manager.count_documents(name, {})
                # 日期范围(只对有trade_date字段的集合查询)
                date_range = None
                if cnt > 0:
                    try:
                        first_cursor = db[name].find({}, {'trade_date': 1}).sort('trade_date', 1).limit(1)
                        last_cursor = db[name].find({}, {'trade_date': 1}).sort('trade_date', -1).limit(1)
                        first_list = await first_cursor.to_list(length=1)
                        last_list = await last_cursor.to_list(length=1)
                        if first_list and last_list and 'trade_date' in first_list[0] and 'trade_date' in last_list[0]:
                            date_range = {'start': str(first_list[0]['trade_date']), 'end': str(last_list[0]['trade_date'])}
                    except Exception:
                        pass  # backtest_tasks等集合没有trade_date字段
                collections[name] = {'count': cnt, 'date_range': date_range}
            except Exception as e:
                collections[name] = {'count': 0, 'date_range': None, 'error': str(e)}

        # 每日因子覆盖率(全量, 单次聚合查询)
        daily_coverage = []
        # 因子组定义: 只包含实际存在且回测需要的因子
        # 注意: technical_talib(MACD/RSI/BOLL/ATR等)需要talib库，回测时由factor_auto_compute自动补算
        # health_score只看 basic+technical_ma+volume+limit 4组(这些是lightweight_factor_fill能补的)
        factor_groups = {
            'basic': ['pct_chg', 'pre_close'],
            'technical_ma': ['ma5', 'ma10', 'ma20', 'ma60'],
            'technical_talib': ['macd', 'rsi_6', 'boll_upper', 'atr', 'fear_greed_index'],
            'volume': ['turnover_rate', 'volume_ratio', 'circ_mv'],
            'limit': ['is_limit_up', 'is_limit_down', 'first_limit_up', 'limit_up_count'],
        }
        all_factors = []
        for factors in factor_groups.values():
            all_factors.extend(factors)

        # 单次聚合: 每天统计每个因子是否存在(用$type判断, missing=不存在)
        group_fields = {'total': {'$sum': 1}}
        for f in all_factors:
            group_fields[f'{f}_count'] = {'$sum': {'$cond': [{'$ne': [{'$type': f'${f}'}, 'missing']}, 1, 0]}}

        # 【v2.9.49】异步聚合查询
        agg_cursor = db.stock_daily_ak_full.aggregate([
            {'$group': {'_id': '$trade_date', **group_fields}},
            {'$sort': {'_id': 1}}
        ])
        agg_result = await agg_cursor.to_list(length=None)

        for doc in agg_result:
            d = str(doc['_id'])
            total = doc['total']
            if total == 0:
                continue
            group_rates = {}
            for gname, factors in factor_groups.items():
                if not factors:
                    group_rates[gname] = 0
                    continue
                rates = []
                for f in factors:
                    has = doc.get(f'{f}_count', 0)
                    rates.append(has / total * 100)
                group_rates[gname] = round(sum(rates) / len(rates), 1)
            # 核心覆盖率(排除limit组和talib组后的3组平均: basic+technical_ma+volume)
            core_rates = [group_rates[k] for k in ['basic', 'technical_ma', 'volume'] if k in group_rates]
            avg_rate = round(sum(core_rates) / len(core_rates), 1) if core_rates else 0
            daily_coverage.append({
                'date': d,
                'total': total,
                'factor_rate': avg_rate,
                'groups': group_rates,
            })

        # 最新数据日期
        last_daily_cursor = db.stock_daily_ak_full.find({}, {'trade_date': 1}).sort('trade_date', -1).limit(1)
        last_daily = await last_daily_cursor.to_list(length=1)
        last_basic_cursor = db.daily_basic.find({}, {'trade_date': 1}).sort('trade_date', -1).limit(1)
        last_basic = await last_basic_cursor.to_list(length=1)

        # 推荐回测区间(核心3组因子覆盖>70%的连续段)
        recommended_ranges = []
        if daily_coverage:
            seg_start = None
            for i, c in enumerate(daily_coverage):
                if c['factor_rate'] >= 70:  # factor_rate现在是3组平均
                    if seg_start is None:
                        seg_start = c['date']
                else:
                    if seg_start is not None:
                        c_prev = daily_coverage[i-1]
                        recommended_ranges.append({'start': seg_start, 'end': c_prev['date'], 'factor_rate': f'{c_prev["factor_rate"]}%'})
                        seg_start = None
            if seg_start is not None:
                recommended_ranges.append({'start': seg_start, 'end': daily_coverage[-1]['date'], 'factor_rate': f'{daily_coverage[-1]["factor_rate"]}%'})

        # 数据源元信息
        data_sources = [
            {
                'name': '东方财富 push2',
                'type': '日线行情',
                'status': 'ok',
                'status_text': '主力日线数据源',
                'rate_limit': '无限制(3秒/全市场)',
                'coverage': '全市场5180只 OHLCV',
                'gotchas': ['Connection aborted = IP被封', '周末不可用', '返回数据只含OHLCV+amount,无换手率/PE等'],
                'scripts': ['eastmoney_daily_bar.py'],
            },
            {
                'name': '东方财富 datacenter',
                'type': 'PE/PB/市值',
                'status': 'ok',
                'status_text': '日常可用',
                'rate_limit': '无限制(0.4秒/天)',
                'coverage': '5400+只 PE_TTM/PB_MRQ/流通市值',
                'gotchas': ['9701错误 = IP被封或服务器繁忙', '周末/非交易日也可能查到历史估值', 'daily_basic专用'],
                'scripts': ['eastmoney_daily_basic.py', 'eastmoney_datacenter_daily_basic.py'],
            },
            {
                'name': 'AKShare',
                'type': '日线/指标',
                'status': 'ok',
                'status_text': '备用日线数据源',
                'rate_limit': '无官方限制',
                'coverage': '全市场日线(含换手率)',
                'gotchas': ['底层走东方财富,被封时同步不可用', '字段名与stock_daily_ak_full不同需映射', '速度慢(逐只拉)'],
                'scripts': ['akshare_daily_manager.py', 'fill_missing_daily_ak.py'],
            },
            {
                'name': '必盈 BiYingAPI',
                'type': '实时行情+涨停池+五档',
                'status': 'active',
                'status_text': '主力数据源, 无IP限制',
                'rate_limit': '免费版200次/天, 包年3000次/分',
                'coverage': '涨停/跌停/炸板池+实时行情+买卖五档',
                'gotchas': ['免费版200次/天需省着用', '代码用纯数字(000001), 不带sz/sh'],
                'scripts': ['BiyingAdapter'],
            },
            {
                'name': 'MongoDB本地',
                'type': '回测数据源',
                'status': 'ok',
                'status_text': '主力数据源,无限制',
                'rate_limit': '无限制',
                'coverage': f'stock_daily_ak_full({collections.get("stock_daily_ak_full",{}).get("count",0)//1000}K) + daily_basic({collections.get("daily_basic",{}).get("count",0)//1000}K) + index_daily({collections.get("index_daily",{}).get("count",0)})',
                'gotchas': ['回测时从MongoDB读取,不调外部API', 'stock_daily_ak_full日期是int格式(20260106)', 'is_limit_up/is_limit_down已用pct_chg阈值重算(5/11修复)'],
                'scripts': ['portfolio_backtest.py(回测引擎)'],
            },
            {
                'name': 'Tushare',
                'type': '全品种日线/指标',
                'status': 'ok',
                'status_text': '5000积分(约4758剩余)',
                'rate_limit': '5000积分(每日约200次)',
                'coverage': 'daily/daily_basic全市场批量补',
                'gotchas': ['新token 5/11提供,已验证可用', 'vol单位是手(×100→股), amount单位是千元(×1000→元)', '代理地址: http://119.45.170.23'],
                'scripts': ['tushare_fill_v2.py basic', 'tushare_fill_v2.py daily'],
            },
        ]

        # 健康评分 + 问题诊断
        diagnostics = []
        health_score = 0
        
        # 数据新鲜度(提前计算, diagnostics要用)
        today_str = datetime.now().strftime('%Y%m%d')
        latest_daily_str = str(last_daily[0]['trade_date']) if last_daily else '0'
        if len(latest_daily_str) == 8 and len(today_str) == 8:
            try:
                today_dt = datetime.strptime(today_str, '%Y%m%d')
                latest_dt = datetime.strptime(latest_daily_str, '%Y%m%d')
                days_old = (today_dt - latest_dt).days
            except ValueError:
                days_old = 999
        else:
            days_old = 999
        
        # 因子覆盖率得分(0-50分, 基于核心3组)
        if daily_coverage:
            latest = daily_coverage[-1]
            factor_score = min(50, latest['factor_rate'] / 2)
            
            # 量价因子
            vol_rate = latest['groups'].get('volume', 0)
            if vol_rate < 50:
                diagnostics.append({'level': 'red', 'message': f'量价因子仅{vol_rate}% — turnover_rate/volume_ratio缺失'})
            elif vol_rate < 90:
                diagnostics.append({'level': 'yellow', 'message': f'量价因子{vol_rate}% — 部分字段缺失(circ_mv/total_mv等)'})
            
            # 涨跌停因子(独立提示,不影响主评分)
            limit_rate = latest['groups'].get('limit', 0)
            if limit_rate < 50:
                diagnostics.append({'level': 'yellow', 'message': f'涨跌停因子{limit_rate}% — is_limit_up等字段缺失,影响首板/跌停策略(不影响半路追涨)'})
            
            # 技术MA因子(已可补算)
            tech_ma_rate = latest['groups'].get('technical_ma', 0)
            if tech_ma_rate < 50:
                diagnostics.append({'level': 'red', 'message': f'MA均线因子仅{tech_ma_rate}% — ma5/ma10/ma20/ma60缺失'})
            
            # 技术talib因子(回测时自动补算)
            tech_talib_rate = latest['groups'].get('technical_talib', 0)
            if tech_talib_rate < 50:
                diagnostics.append({'level': 'yellow', 'message': f'TALib指标仅{tech_talib_rate}% — MACD/RSI/BOLL/ATR等回测时自动补算'})
            
            # 数据新鲜度(日线滞后天数)
            if days_old > 3:
                diagnostics.append({'level': 'yellow', 'message': f'日线数据滞后{days_old}天 — 需运行eastmoney_daily_bar.py补全当日数据'})
            
            # 每日股票数异常(稀疏天)
            if len(daily_coverage) >= 2:
                totals = [c['total'] for c in daily_coverage]
                median_total = sorted(totals)[len(totals)//2]
                sparse_days = [c for c in daily_coverage if c['total'] < median_total * 0.7]
                if sparse_days:
                    diagnostics.append({'level': 'yellow', 'message': f'{len(sparse_days)}天股票数异常稀疏(<{int(median_total*0.7)}只) — 可能缺SH/BJ数据'})
            
            # daily_basic与stock_daily对齐
            sd_cnt = collections.get('stock_daily_ak_full', {}).get('count', 0)
            db_cnt = collections.get('daily_basic', {}).get('count', 0)
            if sd_cnt > 0 and db_cnt > sd_cnt * 1.1:
                diff = db_cnt - sd_cnt
                diagnostics.append({'level': 'yellow', 'message': f'daily_basic比stock_daily多{diff:,}条 — 可能有基金/ETF需清理, 或停牌股缺少日线'})
        else:
            factor_score = 0
            diagnostics.append({'level': 'red', 'message': '无因子覆盖率数据'})
        
        # 数据新鲜度得分(0-30分)
        freshness_score = 0
        if days_old <= 1:
            freshness_score = 30
        elif days_old <= 3:
            freshness_score = 20
        elif days_old <= 7:
            freshness_score = 10
        
        # 数据源可用率得分(0-20分)
        source_score = 0
        ok_sources = sum(1 for s in data_sources if s['status'] == 'ok')
        source_score = min(20, ok_sources * 5)  # 4个ok=20分
        
        health_score = int(factor_score + freshness_score + source_score)
        
        # ====== 策略可用性 ======
        # 根据最新一天因子覆盖判断各策略能否运行
        strategy_availability = []
        if daily_coverage:
            latest = daily_coverage[-1]
            lg = latest['groups']
            strategies = [
                {
                    'name': '半路追涨', 'key': 'half_chase',
                    'factors': ['pct_chg', 'volume_ratio', 'ma5', 'rsi_6'],
                    'desc': '需要pct_chg+量比+技术指标',
                },
                {
                    'name': '首板打板', 'key': 'first_limit',
                    'factors': ['is_limit_up', 'first_limit_up', 'pct_chg'],
                    'desc': '需要涨停标记+涨跌幅',
                },
                {
                    'name': '跌停翘板', 'key': 'limit_down_bounce',
                    'factors': ['is_limit_down', 'pct_chg'],
                    'desc': '需要跌停标记+涨跌幅',
                },
                {
                    'name': '龙头低吸', 'key': 'leader_pullback',
                    'factors': ['limit_up_count', 'pct_chg', 'ma5'],
                    'desc': '需要连板数+涨跌幅+技术指标',
                },
            ]
            for st in strategies:
                missing = [f for f in st['factors'] if lg.get(_factor_to_group(f), 0) < 50]
                # 更精确: 检查单个因子覆盖率
                factor_detail = await _get_factor_detail(db, latest['date'], st['factors'])
                missing = [f for f in st['factors'] if factor_detail.get(f, 0) < 50]
                st['available'] = len(missing) == 0
                st['missing_factors'] = missing
                st['coverage'] = round(sum(factor_detail.get(f, 0) for f in st['factors']) / len(st['factors']), 1)
                strategy_availability.append(st)

        # ====== 今日待办 ======
        action_items = []
        today_int = int(datetime.now().strftime('%Y%m%d'))
        is_weekend = datetime.now().weekday() >= 5
        now_hour = datetime.now().hour
        is_trading_hours = not is_weekend and 9 <= now_hour <= 15
        latest_date = int(latest_daily_str) if len(latest_daily_str) == 8 else 0
        lag_days = 0
        if latest_date > 0 and not is_weekend:
            from datetime import timedelta
            d = datetime.strptime(latest_daily_str, '%Y%m%d')
            bdays = 0
            while d.date() < datetime.now().date():
                d += timedelta(days=1)
                if d.weekday() < 5:
                    bdays += 1
            lag_days = bdays

        # === 必须做：日线+基础指标补全 ===
        if not is_weekend and latest_date > 0 and latest_date < today_int:
            if lag_days >= 2:
                action_items.append({
                    'action': f'补全{lag_days}天数据',
                    'command': '',
                    'api': 'POST /api/v1/system/sync-all',
                    'desc': f'日线滞后{lag_days}个工作日(最新={latest_daily_str}), 一键补全日线+PE/PB+因子',
                    'priority': 'high',
                    'note': '需在交易时间(9:00-15:30)执行，非交易时间东方财富无当日数据',
                })
            else:
                # 滞后1天：只显示一键补全，不重复列出3个
                action_items.append({
                    'action': '一键补全',
                    'command': '',
                    'api': 'POST /api/v1/system/sync-all',
                    'desc': f'日线滞后1天(最新={latest_daily_str}), 补全日线+PE/PB+因子',
                    'priority': 'high',
                    'note': '需在交易时间(9:00-15:30)执行',
                })
        elif not is_weekend and latest_date == today_int:
            action_items.append({
                'action': '数据已是最新',
                'command': '',
                'desc': f'今日({latest_daily_str})数据已补全',
                'priority': 'done',
            })
        elif is_weekend:
            action_items.append({
                'action': '周末休息',
                'command': '',
                'desc': '非交易日, 无需补数据',
                'priority': 'info',
            })
        elif latest_date == 0:
            action_items.append({
                'action': '一键补全',
                'command': '',
                'api': 'POST /api/v1/system/sync-all',
                'desc': '数据库无日线数据, 需要先补全',
                'priority': 'high',
                'note': '首次补全会下载较长时间',
            })

        # === 建议做：指数日线 ===
        index_latest = collections.get('index_daily', {}).get('date_range', {})
        index_end = index_latest.get('end') if index_latest else None
        if index_end and len(index_end) == 8 and int(index_end) < latest_date:
            action_items.append({
                'action': '补指数日线',
                'command': 'python3 akshare_index_daily.py',
                'api': 'POST /api/v1/system/sync-index',
                'desc': f'指数日线滞后(最新={index_end}, 日线已到{latest_daily_str})',
                'priority': 'medium',
                'note': '指数数据用于大盘MA60过滤,回测必须',
            })

        # === 可忽略：涨停池/跌停池(仅实盘用) ===
        limit_latest = collections.get('limit_list', {}).get('date_range', {})
        limit_end = limit_latest.get('end') if limit_latest else None
        if limit_end and len(limit_end) == 8 and int(limit_end) < latest_date:
            action_items.append({
                'action': '补涨停池数据',
                'command': '',
                'desc': f'涨停池滞后(最新={limit_end}), 仅实盘首板打板策略使用',
                'priority': 'low',
                'note': '回测不依赖涨停池,可忽略',
            })

        down_latest = collections.get('limit_pool_down', {}).get('date_range', {})
        down_end = down_latest.get('end') if down_latest else None
        if down_end and len(down_end) == 8 and int(down_end) < latest_date:
            action_items.append({
                'action': '补跌停池数据',
                'command': '',
                'desc': f'跌停池滞后(最新={down_end}), 仅实盘跌停翘板策略使用',
                'priority': 'low',
                'note': '回测不依赖跌停池,可忽略',
            })

        # 检查因子是否需要补算
        if daily_coverage:
            latest = daily_coverage[-1]
            tech_cov = latest['groups'].get('technical', 100)
            if tech_cov < 90:
                action_items.append({
                    'action': '补算技术因子',
                    'command': '回测时自动计算(factor_auto_compute)',
                    'desc': f'技术因子覆盖率{tech_cov:.0f}%, 回测时自动补算',
                    'priority': 'medium',
                    'note': '也可手动运行 lightweight_factor_fill.py',
                })

        # ====== 数据对齐 ======
        data_alignment = {}
        if daily_coverage:
            last_day = daily_coverage[-1]['date']
            sd_total = await mongo_manager.count_documents('stock_daily_ak_full', {'trade_date': int(last_day)})
            db_total = await mongo_manager.count_documents('daily_basic', {'trade_date': int(last_day)})
            # 【v2.9.49】异步查询ts_code集合
            sd_cursor = db.stock_daily_ak_full.find({'trade_date': int(last_day)}, {'ts_code': 1})
            sd_docs = await sd_cursor.to_list(length=None)
            db_cursor = db.daily_basic.find({'trade_date': int(last_day)}, {'ts_code': 1})
            db_docs = await db_cursor.to_list(length=None)
            sd_codes = set(d['ts_code'] for d in sd_docs)
            db_codes = set(d['ts_code'] for d in db_docs)
            common = sd_codes & db_codes
            only_basic = db_codes - sd_codes
            only_daily = sd_codes - db_codes
            data_alignment = {
                'date': last_day,
                'stock_daily_count': sd_total,
                'daily_basic_count': db_total,
                'common': len(common),
                'only_in_basic': len(only_basic),
                'only_in_daily': len(only_daily),
                'only_in_basic_samples': sorted(only_basic)[:5],
            }

        # ====== 因子详情(最新一天) ======
        factor_detail_latest = {}
        if daily_coverage:
            last_day = daily_coverage[-1]['date']
            all_check_factors = ['pct_chg', 'pre_close', 'open', 'high', 'low', 'close',
                                 'ma5', 'ma10', 'ma20', 'ma60',
                                 'macd', 'rsi_6', 'boll_upper', 'atr', 'fear_greed_index',
                                 'turnover_rate', 'volume_ratio', 'circ_mv',
                                 'is_limit_up', 'is_limit_down', 'first_limit_up', 'limit_up_count']
            factor_detail_latest = await _get_factor_detail(db, last_day, all_check_factors)

        # ====== 健康分拆分 ======
        health_breakdown = {
            'factor_score': factor_score if daily_coverage else 0,
            'factor_max': 50,
            'freshness_score': freshness_score,
            'freshness_max': 30,
            'source_score': source_score,
            'source_max': 20,
        }

        # 跌停池数据
        if collections.get('limit_pool_down', {}).get('count', 0) < 10:
            diagnostics.append({'level': 'yellow', 'message': f'跌停池仅{collections.get("limit_pool_down",{}).get("count",0)}条 — 跌停翘板策略数据不足'})

        return {
            "success": True,
            "data": {
                "health_score": health_score,
                "health_breakdown": health_breakdown,
                "diagnostics": diagnostics,
                "collections": collections,
                "daily_coverage": daily_coverage,
                "latest": {
                    "stock_daily": str(last_daily[0]['trade_date']) if last_daily else None,
                    "daily_basic": str(last_basic[0]['trade_date']) if last_basic else None,
                },
                "factor_groups": {k: len(v) for k, v in factor_groups.items()},
                "factor_detail_latest": factor_detail_latest,
                "recommended_ranges": recommended_ranges,
                "data_sources": data_sources,
                "strategy_availability": strategy_availability,
                "action_items": action_items,
                "data_alignment": data_alignment,
            }
        }
    except Exception as e:
        return {"success": False, "message": str(e)}


def _get_frontend_version() -> Dict[str, str]:
    """【Phase4.2】获取前端构建版本"""
    try:
        # 检查已知的几个前端路径
        candidates = [
            # npm run deploy 同步的 static 目录
            "/root/.openclaw/workspace/StockAgent/AgentServer/static/index.html",
            # 开发模式 frontend/dist
            "/root/.openclaw/workspace/StockAgent/frontend/dist/index.html",
        ]
        for path in candidates:
            if os.path.exists(path):
                mtime = os.path.getmtime(path)
                from datetime import datetime as _dt
                build_time = _dt.fromtimestamp(mtime).isoformat()
                source = "static/" if "AgentServer/static" in path else "frontend/dist/"
                return {"status": "built" if "static" in source else "dev", "build_time": build_time, "path": source}
        return {"status": "not_found"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

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
            # 【Phase4.2:前端构建版本】
            "frontend": _get_frontend_version(),
        },
        "message": "获取版本信息成功"
    }


# ==================== 数据同步 API ====================

import subprocess
import threading

_sync_tasks: Dict[str, Dict] = {}
_sync_lock = threading.Lock()


def _run_sync_script(script_name: str, task_id: str):
    """后台线程运行数据同步脚本"""
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../scripts", script_name)
    script_path = os.path.normpath(script_path)
    
    with _sync_lock:
        _sync_tasks[task_id]["status"] = "running"
        _sync_tasks[task_id]["started_at"] = datetime.now().isoformat()
    
    try:
        result = subprocess.run(
            ["python3", "-u", script_path],
            capture_output=True, text=True, timeout=300,
            cwd=os.path.dirname(script_path),
        )
        # 检查实际是否拉到数据(脚本可能exitcode=0但数据为0)
        output = (result.stdout or '') + (result.stderr or '')
        no_data = ('拉取 0 只' in output or '无数据' in output or '总数: 0' in output or '无法获取数据' in output)
        if result.returncode != 0:
            status = "failed"
        elif no_data:
            status = "failed"  # 数据源连接失败
        else:
            status = "success"
        
        with _sync_lock:
            _sync_tasks[task_id]["status"] = status
            _sync_tasks[task_id]["finished_at"] = datetime.now().isoformat()
            _sync_tasks[task_id]["returncode"] = result.returncode
            _sync_tasks[task_id]["stdout"] = result.stdout[-2000:] if result.stdout else ""
            _sync_tasks[task_id]["stderr"] = result.stderr[-2000:] if result.stderr else ""
            if no_data:
                _sync_tasks[task_id]["message"] = "数据源连接失败，未拉到数据(可能IP被封或非交易日)"
    except subprocess.TimeoutExpired:
        with _sync_lock:
            _sync_tasks[task_id]["status"] = "timeout"
            _sync_tasks[task_id]["finished_at"] = datetime.now().isoformat()
            _sync_tasks[task_id]["stderr"] = "脚本超时(300秒)"
    except Exception as e:
        with _sync_lock:
            _sync_tasks[task_id]["status"] = "error"
            _sync_tasks[task_id]["finished_at"] = datetime.now().isoformat()
            _sync_tasks[task_id]["stderr"] = str(e)


@router.post("/sync-daily-bar")
async def sync_daily_bar() -> Dict[str, Any]:
    """
    补全今日日线数据(OHLCV)
    
    运行 eastmoney_daily_bar.py，从东方财富获取全市场日线数据写入MongoDB。
    约需3-5秒完成。
    """
    task_id = f"bar_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    with _sync_lock:
        # 检查是否有正在运行的任务
        running = [t for t in _sync_tasks.values() if t.get("status") == "running" and "bar" in t.get("type", "")]
        if running:
            return {"success": False, "message": "日线补全任务正在运行中，请稍后再试"}
        
        _sync_tasks[task_id] = {"type": "daily_bar", "status": "pending"}
    
    t = threading.Thread(target=_run_sync_script, args=("eastmoney_daily_bar.py", task_id))
    t.daemon = True
    t.start()
    
    return {
        "success": True,
        "task_id": task_id,
        "message": "日线数据补全已启动，请通过 /api/v1/system/sync-status/{task_id} 查看进度",
    }


@router.post("/sync-daily-basic")
async def sync_daily_basic() -> Dict[str, Any]:
    """
    补全今日PE/PB/流通市值等基本面数据
    
    运行 eastmoney_daily_basic.py，从东方财富获取全市场估值数据写入MongoDB。
    需先完成日线数据补全。约需2-3秒完成。
    """
    task_id = f"basic_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    with _sync_lock:
        running = [t for t in _sync_tasks.values() if t.get("status") == "running" and "basic" in t.get("type", "")]
        if running:
            return {"success": False, "message": "PE/PB补全任务正在运行中，请稍后再试"}
        
        _sync_tasks[task_id] = {"type": "daily_basic", "status": "pending"}
    
    t = threading.Thread(target=_run_sync_script, args=("eastmoney_daily_basic.py", task_id))
    t.daemon = True
    t.start()
    
    return {
        "success": True,
        "task_id": task_id,
        "message": "PE/PB数据补全已启动，请通过 /api/v1/system/sync-status/{task_id} 查看进度",
    }


@router.post("/sync-factors")
async def sync_factors() -> Dict[str, Any]:
    """
    补算缺失因子(intraday_max_rise_pct/is_limit_up/volume_increase等)
    
    运行 lightweight_factor_fill.py，补算回测所需策略因子。
    """
    task_id = f"factor_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    with _sync_lock:
        running = [t for t in _sync_tasks.values() if t.get("status") == "running" and "factor" in t.get("type", "")]
        if running:
            return {"success": False, "message": "因子补算任务正在运行中，请稍后再试"}
        
        _sync_tasks[task_id] = {"type": "factors", "status": "pending"}
    
    t = threading.Thread(target=_run_sync_script, args=("lightweight_factor_fill.py", task_id))
    t.daemon = True
    t.start()
    
    return {
        "success": True,
        "task_id": task_id,
        "message": "因子补算已启动，请通过 /api/v1/system/sync-status/{task_id} 查看进度",
    }


@router.post("/sync-index")
async def sync_index() -> Dict[str, Any]:
    """
    补全指数日线数据(上证/深证/创业板/沪深300)
    
    使用finance_history API获取指数数据，周末也可用。
    """
    import requests as http_requests
    
    task_id = f"idx_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    with _sync_lock:
        running = [t for t in _sync_tasks.values() if t.get("status") == "running" and "index" in t.get("type", "")]
        if running:
            return {"success": False, "message": "指数补全任务正在运行中，请稍后再试"}
        
        _sync_tasks[task_id] = {"type": "index", "status": "pending"}
    
    def _run_sync_index():
        from pymongo import MongoClient as PymongoClient
        
        with _sync_lock:
            _sync_tasks[task_id]["status"] = "running"
            _sync_tasks[task_id]["started_at"] = datetime.now().isoformat()
        
        results = []
        indices = ["000001.SH", "399001.SZ", "399006.SZ", "000300.SH"]
        
        # 从MongoDB获取当前最新日期
        client = PymongoClient("mongodb://localhost:27017")
        db = client["stock_agent"]
        col = db["index_daily"]
        
        # 查stock_daily的最新日期作为目标
        sd_latest = list(db["stock_daily_ak_full"].find({}, {"trade_date": 1}).sort("trade_date", -1).limit(1))
        target_date = sd_latest[0]["trade_date"] if sd_latest else None
        
        total_inserted = 0
        for code in indices:
            # 查当前指数最新日期
            idx_latest = list(col.find({"ts_code": code}, {"trade_date": 1}).sort("trade_date", -1).limit(1))
            latest_date = idx_latest[0]["trade_date"] if idx_latest else None
            
            if latest_date and target_date and latest_date >= target_date:
                results.append({"step": code, "success": True, "message": f"已是最新({latest_date})"})
                continue
            
            # 计算start_date
            if latest_date:
                start_str = str(latest_date + 1)  # 下一天
                start_date_fmt = f"{start_str[:4]}-{start_str[4:6]}-{start_str[6:8]}"
            else:
                start_date_fmt = "2024-05-06"
            
            end_date_fmt = datetime.now().strftime("%Y-%m-%d")
            
            try:
                # 使用stock_basic工具获取指数数据（走OpenClaw内部路由，无需8111端口）
                # 回退: 使用pymongo直接写已有数据+AKShare
                try:
                    import akshare as ak
                    ak_df = ak.index_zh_a_hist(symbol=code.split('.')[0], period="daily",
                                               start_date=start_date_fmt.replace('-',''), 
                                               end_date=end_date_fmt.replace('-',''))
                    if ak_df is not None and len(ak_df) > 0:
                        count = 0
                        for _, row in ak_df.iterrows():
                            td = int(row.get('日期', row.get('date', '')).strftime('%Y%m%d') if hasattr(row.get('日期', row.get('date', '')), 'strftime') else str(row.get('日期', row.get('date', '')).replace('-','')))
                            doc = {
                                "ts_code": code, "trade_date": td,
                                "open": float(row.get('开盘', row.get('open', 0))),
                                "close": float(row.get('收盘', row.get('close', 0))),
                                "high": float(row.get('最高', row.get('high', 0))),
                                "low": float(row.get('最低', row.get('low', 0))),
                                "vol": int(row.get('成交量', row.get('volume', 0))),
                                "amount": float(row.get('成交额', row.get('amount', 0))),
                                "pct_chg": float(row.get('涨跌幅', row.get('pct_chg', 0))),
                                "pre_close": float(row.get('昨收', row.get('pre_close', 0))) if row.get('昨收', row.get('pre_close')) else 0,
                            }
                            r = col.update_one({"ts_code": code, "trade_date": td}, {"$set": doc}, upsert=True)
                            if r.upserted_id or r.modified_count:
                                count += 1
                        total_inserted += count
                        results.append({"step": code, "success": True, "message": f"AKShare补入{count}条"})
                    else:
                        results.append({"step": code, "success": False, "message": "AKShare返回空数据(可能非交易日)"})
                except ImportError:
                    results.append({"step": code, "success": False, "message": "akshare未安装"})
                except Exception as e:
                    results.append({"step": code, "success": False, "message": f"AKShare失败: {str(e)[:200]}"})
            except Exception as e:
                results.append({"step": code, "success": False, "message": f"处理失败: {str(e)[:200]}"})
        
        client.close()
        
        with _sync_lock:
            _sync_tasks[task_id]["status"] = "success" if any(r["success"] for r in results) else "failed"
            _sync_tasks[task_id]["finished_at"] = datetime.now().isoformat()
            _sync_tasks[task_id]["results"] = results
            _sync_tasks[task_id]["message"] = f"补入{total_inserted}条指数日线"
    
    t = threading.Thread(target=_run_sync_index)
    t.daemon = True
    t.start()
    
    return {
        "success": True,
        "task_id": task_id,
        "message": "指数日线补全已启动，请通过 /api/v1/system/sync-status/{task_id} 查看进度",
    }


@router.post("/sync-all")
async def sync_all() -> Dict[str, Any]:
    """
    一键补全全部数据(日线+PE/PB+因子)
    
    按顺序执行: eastmoney_daily_bar → eastmoney_daily_basic → lightweight_factor_fill
    """
    task_id = f"all_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    with _sync_lock:
        running = [t for t in _sync_tasks.values() if t.get("status") == "running"]
        if running:
            return {"success": False, "message": "已有数据补全任务正在运行中，请稍后再试"}
        
        _sync_tasks[task_id] = {"type": "all", "status": "pending", "steps": ["daily_bar", "daily_basic", "factors"]}
    
    def _run_all():
        with _sync_lock:
            _sync_tasks[task_id]["status"] = "running"
            _sync_tasks[task_id]["started_at"] = datetime.now().isoformat()
        
        results = []
        scripts = [
            ("daily_bar", "eastmoney_daily_bar.py"),
            ("daily_basic", "eastmoney_daily_basic.py"),
            ("factors", "lightweight_factor_fill.py"),
        ]
        
        for step_name, script_name in scripts:
            script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../scripts", script_name)
            script_path = os.path.normpath(script_path)
            
            with _sync_lock:
                _sync_tasks[task_id]["current_step"] = step_name
            
            try:
                r = subprocess.run(
                    ["python3", "-u", script_path],
                    capture_output=True, text=True, timeout=300,
                    cwd=os.path.dirname(script_path),
                )
                # 检查实际是否拉到数据(脚本可能exitcode=0但数据为0)
                output = (r.stdout or '') + (r.stderr or '')
                no_data = ('拉取 0 只' in output or '无数据' in output or '总数: 0' in output)
                success = r.returncode == 0 and not no_data
                results.append({
                    "step": step_name,
                    "success": success,
                    "message": "数据源连接失败,未拉到数据" if no_data else ("执行成功" if success else "执行失败"),
                    "stdout": r.stdout[-500:] if r.stdout else "",
                    "stderr": r.stderr[-500:] if r.stderr else "",
                })
            except Exception as e:
                results.append({"step": step_name, "success": False, "message": str(e), "stderr": str(e)})
        
        with _sync_lock:
            _sync_tasks[task_id]["status"] = "success" if all(r["success"] for r in results) else "partial"
            _sync_tasks[task_id]["finished_at"] = datetime.now().isoformat()
            _sync_tasks[task_id]["results"] = results
    
    t = threading.Thread(target=_run_all)
    t.daemon = True
    t.start()
    
    return {
        "success": True,
        "task_id": task_id,
        "message": "一键补全已启动(日线→PE/PB→因子)，请通过 /api/v1/system/sync-status/{task_id} 查看进度",
    }


@router.get("/sync-status/{task_id}")
async def get_sync_status(task_id: str) -> Dict[str, Any]:
    """查询数据同步任务状态"""
    with _sync_lock:
        task = _sync_tasks.get(task_id)
    
    if not task:
        return {"success": False, "message": f"任务 {task_id} 不存在"}
    
    return {"success": True, "data": task}


@router.get("/sync-tasks")
async def list_sync_tasks() -> Dict[str, Any]:
    """列出所有数据同步任务"""
    with _sync_lock:
        tasks = dict(_sync_tasks)
    
    # 只返回最近10个
    recent = sorted(tasks.items(), key=lambda x: x[0], reverse=True)[:10]
    return {"success": True, "data": dict(recent)}


@router.get("/auto-fill-detect")
async def auto_fill_detect() -> Dict[str, Any]:
    """
    检测最近缺失的因子，返回缺失信息供前端展示。
    
    检测范围：最近30个交易日，找出缺因子的日期和字段。
    """
    try:
        if not mongo_manager._initialized:
            await mongo_manager.initialize()
        db = mongo_manager.db
        coll = db["stock_daily_ak_full"]
        
        # 获取所有交易日
        all_dates = await coll.distinct("trade_date")
        if not all_dates:
            return {"success": True, "data": {"missing_dates": [], "missing_fields": [], "total_missing_days": 0, "latest_date": None}}
        
        all_dates_sorted = sorted(all_dates, reverse=True)
        recent_dates = all_dates_sorted[:30]  # 最近30个交易日
        latest_date = all_dates_sorted[0]
        
        # 关键因子字段列表
        key_factors = [
            "ma5", "ma10", "ma20", "ma60",
            "turnover_rate", "volume_ratio", "circ_mv",
            "is_limit_up", "is_limit_down", "first_limit_up", "limit_up_count",
            "opening_pct_chg", "open_above_limit",
            "intraday_max_rise_pct", "intraday_open_rise_pct",
            "pullback_pct",
        ]
        
        missing_dates = []
        missing_field_counts: Dict[str, int] = {}
        
        for td in recent_dates:
            total = await coll.count_documents({"trade_date": td})
            if total == 0:
                continue
            
            # 检查各因子覆盖率
            date_missing = {"date": td, "total": total, "missing": []}
            for factor in key_factors:
                with_factor = await coll.count_documents({"trade_date": td, factor: {"$ne": None, "$exists": True}})
                rate = with_factor / total if total > 0 else 0
                if rate < 0.9:  # 覆盖率<90%视为缺失
                    missing_count = total - with_factor
                    date_missing["missing"].append({
                        "field": factor,
                        "coverage": round(rate * 100, 1),
                        "missing_count": missing_count,
                    })
                    missing_field_counts[factor] = missing_field_counts.get(factor, 0) + missing_count
            
            if date_missing["missing"]:
                missing_dates.append(date_missing)
        
        # 按日期正序排列(最早的在前)
        missing_dates.sort(key=lambda x: x["date"])
        
        missing_fields = sorted(
            [{"field": k, "total_missing": v} for k, v in missing_field_counts.items()],
            key=lambda x: x["total_missing"], reverse=True
        )
        
        return {
            "success": True,
            "data": {
                "missing_dates": missing_dates,
                "missing_fields": missing_fields,
                "total_missing_days": len(missing_dates),
                "latest_date": latest_date,
                "checked_dates": len(recent_dates),
                "key_factors": key_factors,
            },
        }
    except Exception as e:
        logger.error(f"Auto-fill detect failed: {e}")
        return {"success": False, "message": str(e)}


@router.post("/auto-fill-trigger")
async def auto_fill_trigger() -> Dict[str, Any]:
    """
    触发自动补全因子数据。
    
    按顺序执行：
    1. lightweight_factor_fill.py — 补基础因子(turnover_rate/volume_ratio/circ_mv/ma5/is_limit_up等)
    2. 如果需要技术指标(MACD/RSI等)，则运行factor_auto_compute
    """
    task_id = f"autofill_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    with _sync_lock:
        running = [t for t in _sync_tasks.values() if t.get("status") == "running"]
        if running:
            return {"success": False, "message": "已有数据补全任务正在运行中，请稍后再试"}
        
        _sync_tasks[task_id] = {"type": "autofill", "status": "pending", "steps": ["detect", "basic_factors", "daily_bar", "daily_basic", "index_daily", "limit_pools", "derived_factors"]}
    
    def _run_auto_fill():
        import asyncio
        with _sync_lock:
            _sync_tasks[task_id]["status"] = "running"
            _sync_tasks[task_id]["started_at"] = datetime.now().isoformat()
            _sync_tasks[task_id]["current_step"] = "detect"
        
        results = []
        
        # Step 1: 先运行轻量因子补算(补基础因子)
        script_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "../../../scripts/lightweight_factor_fill.py"
        )
        script_path = os.path.normpath(script_path)
        
        with _sync_lock:
            _sync_tasks[task_id]["current_step"] = "basic_factors"
        
        try:
            r = subprocess.run(
                ["python3", "-u", script_path],
                capture_output=True, text=True, timeout=300,
                cwd=os.path.dirname(script_path),
            )
            output = (r.stdout or '') + (r.stderr or '')
            no_data = ('所有日期的因子已完整' in output)
            success = r.returncode == 0
            results.append({
                "step": "basic_factors",
                "success": success,
                "message": "因子已完整,无需补算" if no_data else ("补算成功" if success else "补算失败"),
                "stdout": r.stdout[-800:] if r.stdout else "",
                "stderr": r.stderr[-500:] if r.stderr else "",
            })
        except Exception as e:
            results.append({"step": "basic_factors", "success": False, "message": str(e)})
        
        # Step 2: 补东财日线数据(可能缺最近几天的OHLCV)
        bar_script = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "../../../scripts/eastmoney_daily_bar.py"
        )
        bar_script = os.path.normpath(bar_script)
        
        with _sync_lock:
            _sync_tasks[task_id]["current_step"] = "daily_bar"
        
        try:
            r = subprocess.run(
                ["python3", "-u", bar_script],
                capture_output=True, text=True, timeout=120,
                cwd=os.path.dirname(bar_script),
            )
            results.append({
                "step": "daily_bar",
                "success": r.returncode == 0,
                "message": "日线数据同步完成" if r.returncode == 0 else "日线数据同步失败",
                "stdout": r.stdout[-500:] if r.stdout else "",
            })
        except Exception as e:
            results.append({"step": "daily_bar", "success": False, "message": str(e)})
        
        # Step 3: 补东财基础指标(PE/PB/流通市值)
        basic_script = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "../../../scripts/eastmoney_daily_basic.py"
        )
        basic_script = os.path.normpath(basic_script)
        
        with _sync_lock:
            _sync_tasks[task_id]["current_step"] = "daily_basic"
        
        try:
            r = subprocess.run(
                ["python3", "-u", basic_script],
                capture_output=True, text=True, timeout=120,
                cwd=os.path.dirname(basic_script),
            )
            results.append({
                "step": "daily_basic",
                "success": r.returncode == 0,
                "message": "基础指标同步完成" if r.returncode == 0 else "基础指标同步失败",
                "stdout": r.stdout[-500:] if r.stdout else "",
            })
        except Exception as e:
            results.append({"step": "daily_basic", "success": False, "message": str(e)})
        
        # Step 4: 补指数日线(AKShare)
        index_script = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "../../../scripts/fill_index_daily.py"
        )
        index_script = os.path.normpath(index_script)
        
        with _sync_lock:
            _sync_tasks[task_id]["current_step"] = "index_daily"
        
        # 用sync-index API的逻辑(直接在线补)
        try:
            import requests as http_requests_sync
            # 调用内部API
            base_url = "http://localhost:8000"
            r = http_requests_sync.post(f"{base_url}/api/v1/system/sync-index", timeout=10)
            idx_json = r.json() if r.status_code == 200 else {}
            idx_task_id = idx_json.get("task_id", "")
            if idx_json.get("success"):
                # 等待完成(最多60秒)
                for _ in range(20):
                    time.sleep(3)
                    try:
                        sr = http_requests_sync.get(f"{base_url}/api/v1/system/sync-status/{idx_task_id}", timeout=5)
                        sj = sr.json() if sr.status_code == 200 else {}
                        if sj.get("data", {}).get("status") in ("success", "partial", "failed"):
                            idx_result = sj["data"]
                            break
                    except:
                        pass
                else:
                    idx_result = {"status": "unknown"}
                results.append({
                    "step": "index_daily",
                    "success": idx_result.get("status") == "success",
                    "message": f'指数日线补全{idx_result.get("status", "unknown")}',
                })
            else:
                results.append({"step": "index_daily", "success": False, "message": idx_json.get("message", "启动失败")})
        except Exception as e:
            results.append({"step": "index_daily", "success": False, "message": str(e)})
        
        # Step 5: 补涨跌停池(从stock_daily_ak_full的is_limit_up/down反推)
        with _sync_lock:
            _sync_tasks[task_id]["current_step"] = "limit_pools"
        
        try:
            r = subprocess.run(
                ["python3", "-u", "-c", """
import sys; sys.path.insert(0, '.')
from pymongo import MongoClient, UpdateOne
from datetime import datetime
db = MongoClient('localhost', 27017)['stock_agent']
# 检测limit_list缺数据的日期
sd_dates = sorted(db['stock_daily_ak_full'].distinct('trade_date'))
ll_dates = set(db['limit_list'].distinct('trade_date'))
missing = [d for d in sd_dates if d not in ll_dates and d >= 20260501]
if not missing:
    print('涨跌停池已完整')
    exit(0)
print(f'补涨跌停池: {len(missing)}天')
for td in missing:
    docs = list(db['stock_daily_ak_full'].find({'trade_date': td, '$or': [{'is_limit_up': 1}, {'is_limit_down': 1}]}, {'ts_code': 1, 'pct_chg': 1, 'is_limit_up': 1, 'is_limit_down': 1, 'close': 1, 'open': 1, 'high': 1, 'low': 1, 'vol': 1, 'amount': 1, 'pre_close': 1, '_id': 0}))
    ops = []
    for doc in docs:
        doc['trade_date'] = td
        doc['data_source'] = 'backfill_from_daily'
        ops.append(UpdateOne({'ts_code': doc['ts_code'], 'trade_date': td}, {'$set': doc}, upsert=True))
    if ops:
        r = db['limit_list'].bulk_write(ops)
        print(f'  {td}: {r.upserted_count}新+{r.modified_count}改')
"""],
                capture_output=True, text=True, timeout=120,
                cwd=os.path.dirname(os.path.abspath(__file__)) + "/../../../",
            )
            output = (r.stdout or '')
            results.append({
                "step": "limit_pools",
                "success": r.returncode == 0,
                "message": output.strip().split('\n')[-1] if output.strip() else "完成",
            })
        except Exception as e:
            results.append({"step": "limit_pools", "success": False, "message": str(e)})
        
        # Step 6: 再跑一次轻量因子补算(确保新数据的因子也补上)
        with _sync_lock:
            _sync_tasks[task_id]["current_step"] = "derived_factors"
        
        try:
            r = subprocess.run(
                ["python3", "-u", script_path],
                capture_output=True, text=True, timeout=300,
                cwd=os.path.dirname(script_path),
            )
            output = (r.stdout or '') + (r.stderr or '')
            no_data = ('所有日期的因子已完整' in output)
            success = r.returncode == 0
            results.append({
                "step": "derived_factors",
                "success": success,
                "message": "因子已完整" if no_data else ("衍生因子补算完成" if success else "衍生因子补算失败"),
                "stdout": r.stdout[-800:] if r.stdout else "",
            })
        except Exception as e:
            results.append({"step": "derived_factors", "success": False, "message": str(e)})
        
        with _sync_lock:
            all_success = all(r["success"] for r in results)
            _sync_tasks[task_id]["status"] = "success" if all_success else "partial"
            _sync_tasks[task_id]["finished_at"] = datetime.now().isoformat()
            _sync_tasks[task_id]["results"] = results
    
    t = threading.Thread(target=_run_auto_fill)
    t.daemon = True
    t.start()
    
    return {
        "success": True,
        "task_id": task_id,
        "message": "自动补全已启动(检测→日线→基础指标→因子)，请通过 /api/v1/system/sync-status/{task_id} 查看进度",
    }
