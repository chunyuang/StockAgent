#!/usr/bin/env python3
"""
策略配置 API — 超短量化策略统一配置入口

Single Source of Truth: strategy_defaults.py
前端只读/编辑这个来源，不再硬编码策略参数。
"""
import logging
from typing import Dict, List, Optional, Any

from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel

from nodes.backtest_engine.strategy_defaults import (
    STRATEGY_CONFIGS, GLOBAL_RISK, STRATEGY_IDS,
    merge_strategy_params, merge_strategy_risk_params,
)

logger = logging.getLogger("api.strategy_config")

router = APIRouter(prefix="/api/v1/strategy-config", tags=["策略配置"])


# ==================== 持久化覆盖存储(MongoDB) ====================
# P1-9修复: 用户从前端修改的参数持久化到MongoDB scanner_config集合
# 重启后自动恢复, 不再丢失
_override_params: Dict[str, Dict] = {}   # strategy_id → params
_override_risk: Dict[str, Dict] = {}     # strategy_id → riskParams
_override_enabled: Dict[str, bool] = {}  # strategy_id → enabled
_override_global_risk: Dict[str, Any] = {}  # 全局风控覆盖
_overrides_loaded: bool = False  # 是否已从MongoDB加载


async def _ensure_overrides_loaded() -> None:
    """从MongoDB加载覆盖参数(懒加载,首次访问时触发)
    
    修复: 加载失败时重置flag允许重试, 避免永久跳过
    """
    global _override_params, _override_risk, _override_enabled, _override_global_risk, _overrides_loaded
    if _overrides_loaded:
        return
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            logger.debug("[CONFIG] MongoDB未初始化, 跳过覆盖参数加载")
            _overrides_loaded = True  # MongoDB不可用是永久状态, 不重试
            return
        doc = await mongo_manager.db["scanner_config"].find_one({"_id": "strategy_config_overrides"})
        if doc and "data" in doc:
            data = doc["data"]
            _override_params = data.get("params", {})
            _override_risk = data.get("risk", {})
            _override_enabled = data.get("enabled", {})
            _override_global_risk = data.get("global_risk", {})
            logger.info(f"[CONFIG] 从MongoDB恢复策略覆盖: {len(_override_params)}个参数覆盖, {len(_override_enabled)}个启停覆盖")
        _overrides_loaded = True
    except Exception as e:
        # 关键修复: 加载失败时不设flag, 允许下次重试
        logger.warning(f"[CONFIG] 加载覆盖参数失败(下次重试): {e}")


async def _persist_overrides() -> None:
    """将覆盖参数持久化到MongoDB"""
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return
        from datetime import datetime
        data = {
            "params": _override_params,
            "risk": _override_risk,
            "enabled": _override_enabled,
            "global_risk": _override_global_risk,
        }
        await mongo_manager.db["scanner_config"].update_one(
            {"_id": "strategy_config_overrides"},
            {"$set": {"data": data, "updated_at": datetime.now().isoformat()}},
            upsert=True,
        )
    except Exception as e:
        logger.warning(f"[CONFIG] 覆盖参数持久化失败(非关键): {e}")


async def _get_effective_config(strategy_id: str) -> Dict:
    """获取策略有效配置(默认+覆盖)"""
    await _ensure_overrides_loaded()
    base = STRATEGY_CONFIGS.get(strategy_id)
    if not base:
        return {}
    cfg = dict(base)
    if strategy_id in _override_params:
        cfg["params"] = merge_strategy_params(strategy_id, _override_params[strategy_id])
    if strategy_id in _override_risk:
        cfg["riskParams"] = merge_strategy_risk_params(strategy_id, _override_risk[strategy_id])
    if strategy_id in _override_enabled:
        cfg["enabled"] = _override_enabled[strategy_id]
    return cfg


# ==================== Schemas ====================

class StrategyParamUpdate(BaseModel):
    params: Optional[Dict[str, Any]] = None
    riskParams: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None


class GlobalRiskUpdate(BaseModel):
    updates: Dict[str, Any]


# ==================== API ====================

@router.get("/strategies")
async def get_strategies():
    """获取所有超短策略配置(含当前覆盖)"""
    strategies = []
    for sid in STRATEGY_IDS:
        cfg = await _get_effective_config(sid)
        # 参数描述(加中文label)
        param_descriptions = _describe_params(sid, cfg.get("params", {}))
        risk_descriptions = _describe_risk(cfg.get("riskParams", {}))
        strategies.append({
            "id": sid,
            "name": cfg["name"],
            "enabled": cfg["enabled"],
            "params": cfg["params"],
            "riskParams": cfg["riskParams"],
            "paramDescriptions": param_descriptions,
            "riskDescriptions": risk_descriptions,
        })
    return {"success": True, "data": strategies}


@router.get("/strategies/{strategy_id}")
async def get_strategy(strategy_id: str):
    """获取单个策略配置"""
    if strategy_id not in STRATEGY_CONFIGS:
        raise HTTPException(404, f"策略 {strategy_id} 不存在")
    cfg = await _get_effective_config(strategy_id)
    return {"success": True, "data": cfg}


@router.put("/strategies/{strategy_id}")
async def update_strategy(strategy_id: str, req: StrategyParamUpdate):
    """更新策略参数/风控/启停(P1-9: 持久化到MongoDB)"""
    if strategy_id not in STRATEGY_CONFIGS:
        raise HTTPException(404, f"策略 {strategy_id} 不存在")

    await _ensure_overrides_loaded()

    if req.params is not None:
        _override_params[strategy_id] = req.params
    if req.riskParams is not None:
        _override_risk[strategy_id] = req.riskParams
    if req.enabled is not None:
        _override_enabled[strategy_id] = req.enabled

    # 持久化到MongoDB
    await _persist_overrides()

    # 同步到MarketScanner(如果运行中)
    try:
        from nodes.web.api.scanner import _get_scanner_instance
        scanner = _get_scanner_instance()
        if scanner:
            effective_cfg = await _get_effective_config(strategy_id)
            scanner.update_strategy_config(strategy_id, effective_cfg)
    except Exception:
        pass

    cfg = await _get_effective_config(strategy_id)
    logger.info(f"[CONFIG] 更新策略 {strategy_id}: enabled={cfg.get('enabled')} (已持久化)")
    return {"success": True, "data": cfg}


@router.get("/global-risk")
async def get_global_risk():
    """获取全局风控参数(含覆盖)"""
    await _ensure_overrides_loaded()
    result = dict(GLOBAL_RISK)
    result.update(_override_global_risk)
    return {"success": True, "data": result}


@router.put("/global-risk")
async def update_global_risk(req: GlobalRiskUpdate):
    """更新全局风控参数(P1-9: 持久化到MongoDB)
    
    修复: 同时同步到strategy_params集合, 确保param_center读到的全局风控也是最新
    """
    await _ensure_overrides_loaded()
    for k, v in req.updates.items():
        if k in GLOBAL_RISK:
            _override_global_risk[k] = v
    # 持久化到MongoDB (strategy_config_overrides文档)
    await _persist_overrides()
    
    # 【修复】同步到strategy_params集合中每个策略的globalRisk字段
    try:
        from core.managers import mongo_manager
        if mongo_manager.is_initialized:
            effective_gr = dict(GLOBAL_RISK)
            effective_gr.update(_override_global_risk)
            from datetime import datetime as _dt
            await mongo_manager.db["strategy_params"].update_many(
                {},
                {"$set": {"globalRisk": effective_gr, "updated_at": _dt.now().isoformat()}}
            )
            logger.info(f"[CONFIG] 全局风控已同步到strategy_params: {req.updates}")
    except Exception as e:
        logger.warning(f"[CONFIG] 全局风控同步strategy_params失败(非关键): {e}")
    
    # 同步到运行中的Scanner
    try:
        from nodes.web.api.scanner import _get_scanner_instance
        scanner = _get_scanner_instance()
        if scanner and hasattr(scanner, 'config'):
            scanner.config.setdefault("global_risk", {})
            scanner.config["global_risk"].update(req.updates)
    except Exception:
        pass
    
    logger.info(f"[CONFIG] 更新全局风控: {req.updates} (已持久化)")
    result = dict(GLOBAL_RISK)
    result.update(_override_global_risk)
    return {"success": True, "data": result}


@router.post("/reset/{strategy_id}")
async def reset_strategy(strategy_id: str):
    """重置策略为默认参数(P1-9: 同步清除MongoDB覆盖)"""
    await _ensure_overrides_loaded()
    _override_params.pop(strategy_id, None)
    _override_risk.pop(strategy_id, None)
    _override_enabled.pop(strategy_id, None)
    # 持久化清除到MongoDB
    await _persist_overrides()
    cfg = await _get_effective_config(strategy_id)
    logger.info(f"[CONFIG] 重置策略 {strategy_id} (已持久化)")
    return {"success": True, "data": cfg}


# ==================== 参数描述 ====================

PARAM_LABELS = {
    # 半路追涨
    "min_rise_pct": ("最小涨幅", "%", 100),
    "max_rise_pct": ("最大涨幅", "%", 100),
    "min_volume_ratio": ("最小量比", "", 1),
    "allow_after_10am": ("允许10点后", "", 1),
    # 首板打板
    "min_seal_amount": ("最小封单", "万元", 1),
    "max_limit_up_time": ("最晚涨停时间", "", 1),
    "min_circulation_market_cap": ("最小流通市值", "亿", 1),
    "max_circulation_market_cap": ("最大流通市值", "亿", 1),
    "max_blast_count": ("最大开板次数", "", 1),
    "require_hot_sector": ("要求热门板块", "", 1),
    "opening_pct_min": ("竞价涨幅下限", "%", 1),
    "opening_pct_max": ("竞价涨幅上限", "%", 1),
    "min_turnover_rate": ("最小换手率", "%", 1),
    "max_turnover_rate": ("最大换手率", "%", 1),
    # 涨停开板
    "min_consecutive_limit": ("最小连板数", "", 1),
    "max_open_duration": ("最大开板时长", "分钟", 1),
    "min_seal_after_open": ("开板后封单", "万元", 1),
    # 龙头低吸
    "min_correction_pct": ("最小回调", "%", 100),
    "max_correction_pct": ("最大回调", "%", 100),
    "correction_days_min": ("回调天数下限", "天", 1),
    "correction_days_max": ("回调天数上限", "天", 1),
    "support_level": ("支撑位", "", 1),
    # 跌停翘板
    "min_qiao_amount": ("翘板金额", "万元", 1),
    "min_rise_after_qiao": ("翘板后涨幅", "%", 100),
    "require_high_sentiment": ("要求高情绪", "", 1),
    # 风控
    "stop_loss_pct": ("止损", "%", 100),
    "take_profit_pct": ("止盈", "%", 100),
    "max_hold_days": ("最大持仓", "天", 1),
    "slippage_pct": ("滑点", "%", 100),
}

RISK_LABELS = {
    "stop_loss_pct": ("止损", "%", 100),
    "take_profit_pct": ("止盈", "%", 100),
    "max_hold_days": ("最大持仓天数", "天", 1),
    "slippage_pct": ("滑点", "%", 100),
}


def _describe_params(strategy_id: str, params: Dict) -> List[Dict]:
    """给参数加中文label和单位"""
    result = []
    for k, v in params.items():
        label_info = PARAM_LABELS.get(k, (k, "", 1))
        label, unit, scale = label_info
        display_val = round(v * scale, 4) if isinstance(v, (int, float)) and scale != 1 and not isinstance(v, bool) else v
        result.append({
            "key": k,
            "label": label,
            "value": v,
            "displayValue": display_val,
            "unit": unit,
            "type": "boolean" if isinstance(v, bool) else "string" if isinstance(v, str) else "number",
        })
    return result


def _describe_risk(risk_params: Dict) -> List[Dict]:
    result = []
    for k, v in risk_params.items():
        label_info = RISK_LABELS.get(k, (k, "", 1))
        label, unit, scale = label_info
        display_val = round(v * scale, 4) if isinstance(v, (int, float)) and scale != 1 and not isinstance(v, bool) else v
        result.append({
            "key": k,
            "label": label,
            "value": v,
            "displayValue": display_val,
            "unit": unit,
            "type": "number",
        })
    return result
