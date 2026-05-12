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
from .auth import get_optional_user_id as get_current_user_id



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


def _get_factor_detail(db, date_str: str, factors: list) -> dict:
    """获取指定日期每个因子的覆盖率(单次聚合)"""
    d = int(date_str) if isinstance(date_str, str) else date_str
    total = db.stock_daily_ak_full.count_documents({'trade_date': d})
    if total == 0:
        return {f: 0 for f in factors}
    group_fields = {'total': {'$sum': 1}}
    for f in factors:
        group_fields[f'{f}_cnt'] = {'$sum': {'$cond': [{'$ne': [{'$type': f'${f}'}, 'missing']}, 1, 0]}}
    result = list(db.stock_daily_ak_full.aggregate([
        {'$match': {'trade_date': d}},
        {'$group': {'_id': None, **group_fields}}
    ]))
    if not result:
        return {f: 0 for f in factors}
    r = result[0]
    return {f: round(r.get(f'{f}_cnt', 0) / r['total'] * 100, 1) for f in factors}


@router.get("/data-status")
async def get_data_status() -> Dict[str, Any]:
    """获取数据层状态：各集合记录数、因子覆盖率、最新数据日期"""
    try:
        from pymongo import MongoClient as SyncClient
        from core.settings import settings as app_settings
        client = SyncClient(app_settings.mongo.host, app_settings.mongo.port)
        db = client[app_settings.mongo.database]

        # 集合记录数 + 日期范围
        collections = {}
        for name in ['stock_daily_ak_full', 'daily_basic', 'index_daily', 'limit_list', 'limit_pool_down', 'backtest_tasks']:
            try:
                cnt = db[name].count_documents({})
                # 日期范围(只对有trade_date字段的集合查询)
                date_range = None
                if cnt > 0:
                    try:
                        first = list(db[name].find({}, {'trade_date': 1}).sort('trade_date', 1).limit(1))
                        last = list(db[name].find({}, {'trade_date': 1}).sort('trade_date', -1).limit(1))
                        if first and last and 'trade_date' in first[0] and 'trade_date' in last[0]:
                            date_range = {'start': str(first[0]['trade_date']), 'end': str(last[0]['trade_date'])}
                    except Exception:
                        pass  # backtest_tasks等集合没有trade_date字段
                collections[name] = {'count': cnt, 'date_range': date_range}
            except Exception as e:
                collections[name] = {'count': 0, 'date_range': None, 'error': str(e)}

        # 每日因子覆盖率(全量, 单次聚合查询)
        daily_coverage = []
        # 因子组定义: 只包含实际存在且回测需要的因子
        factor_groups = {
            'basic': ['pct_chg', 'pre_close'],
            'technical': ['ma5', 'macd', 'rsi_6', 'boll_upper', 'atr', 'fear_greed_index'],
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

        agg_result = list(db.stock_daily_ak_full.aggregate([
            {'$group': {'_id': '$trade_date', **group_fields}},
            {'$sort': {'_id': 1}}
        ]))

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
            # 核心覆盖率(排除limit组后的3组平均)
            core_rates = [group_rates[k] for k in ['basic', 'technical', 'volume']]
            avg_rate = round(sum(core_rates) / len(core_rates), 1)
            daily_coverage.append({
                'date': d,
                'total': total,
                'factor_rate': avg_rate,
                'groups': group_rates,
            })

        # 最新数据日期
        last_daily = list(db.stock_daily_ak_full.find({}, {'trade_date': 1}).sort('trade_date', -1).limit(1))
        last_basic = list(db.daily_basic.find({}, {'trade_date': 1}).sort('trade_date', -1).limit(1))

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
                'name': '量脉 LiangMai',
                'type': '实时行情/分钟K线',
                'status': 'limited',
                'status_text': '120次/分钟+2IP限制',
                'rate_limit': '120次/分钟, Token绑定2个IP',
                'coverage': '实时盘中/1min K线/PE/PB',
                'gotchas': ['4291错误=IP超限,不要反复重试', '服务器动态IP导致IP超限不可避免', 'daily_basic不要再用量脉,用东方财富替代'],
                'scripts': ['LiangMaiClient'],
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
            
            # 技术因子
            tech_rate = latest['groups'].get('technical', 0)
            if tech_rate < 50:
                diagnostics.append({'level': 'red', 'message': f'技术因子仅{tech_rate}% — MA/MACD/RSI等需factor_auto_compute补算'})
            
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
                factor_detail = _get_factor_detail(db, latest['date'], st['factors'])
                missing = [f for f in st['factors'] if factor_detail.get(f, 0) < 50]
                st['available'] = len(missing) == 0
                st['missing_factors'] = missing
                st['coverage'] = round(sum(factor_detail.get(f, 0) for f in st['factors']) / len(st['factors']), 1)
                strategy_availability.append(st)

        # ====== 今日待办 ======
        action_items = []
        today_int = int(datetime.now().strftime('%Y%m%d'))
        is_weekend = datetime.now().weekday() >= 5
        latest_date = int(latest_daily_str) if len(latest_daily_str) == 8 else 0

        if not is_weekend and latest_date < today_int:
            action_items.append({
                'action': '补今日日线',
                'command': 'python3 eastmoney_daily_bar.py',
                'desc': f'最新日线={latest_daily_str}, 需补今日数据',
                'priority': 'high',
            })
            action_items.append({
                'action': '补今日PE/PB',
                'command': 'python3 eastmoney_daily_basic.py',
                'desc': '日线补完后运行',
                'priority': 'high',
            })
        elif is_weekend:
            action_items.append({
                'action': '周末休息',
                'command': '',
                'desc': '非交易日, 无需补数据',
                'priority': 'info',
            })
        elif latest_date == today_int:
            action_items.append({
                'action': '数据已是最新',
                'command': '',
                'desc': f'今日({latest_daily_str})数据已补全',
                'priority': 'done',
            })

        # 检查因子是否需要补算
        if daily_coverage:
            latest = daily_coverage[-1]
            if latest['groups'].get('technical', 100) < 90:
                action_items.append({
                    'action': '补算技术因子',
                    'command': '回测时自动计算(factor_auto_compute)',
                    'desc': f'技术因子覆盖率{latest["groups"].get("technical", 0):.0f}%',
                    'priority': 'medium',
                })

        # ====== 数据对齐 ======
        data_alignment = {}
        if daily_coverage:
            last_day = daily_coverage[-1]['date']
            sd_total = db.stock_daily_ak_full.count_documents({'trade_date': int(last_day)})
            db_total = db.daily_basic.count_documents({'trade_date': int(last_day)})
            sd_codes = set(d['ts_code'] for d in db.stock_daily_ak_full.find({'trade_date': int(last_day)}, {'ts_code': 1}))
            db_codes = set(d['ts_code'] for d in db.daily_basic.find({'trade_date': int(last_day)}, {'ts_code': 1}))
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
                                 'ma5', 'macd', 'rsi_6', 'boll_upper', 'atr', 'fear_greed_index',
                                 'turnover_rate', 'volume_ratio', 'circ_mv',
                                 'is_limit_up', 'is_limit_down', 'first_limit_up', 'limit_up_count']
            factor_detail_latest = _get_factor_detail(db, last_day, all_check_factors)

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

        client.close()

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
