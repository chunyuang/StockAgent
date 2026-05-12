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


# ==================== 运行时覆盖存储(内存) ====================
# 用户从前端修改的参数存在这里, 重启后恢复默认
_override_params: Dict[str, Dict] = {}   # strategy_id → params
_override_risk: Dict[str, Dict] = {}     # strategy_id → riskParams
_override_enabled: Dict[str, bool] = {}  # strategy_id → enabled


def _get_effective_config(strategy_id: str) -> Dict:
    """获取策略有效配置(默认+覆盖)"""
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
        cfg = _get_effective_config(sid)
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
    cfg = _get_effective_config(strategy_id)
    return {"success": True, "data": cfg}


@router.put("/strategies/{strategy_id}")
async def update_strategy(strategy_id: str, req: StrategyParamUpdate):
    """更新策略参数/风控/启停"""
    if strategy_id not in STRATEGY_CONFIGS:
        raise HTTPException(404, f"策略 {strategy_id} 不存在")

    if req.params is not None:
        _override_params[strategy_id] = req.params
    if req.riskParams is not None:
        _override_risk[strategy_id] = req.riskParams
    if req.enabled is not None:
        _override_enabled[strategy_id] = req.enabled

    # 同步到MarketScanner(如果运行中)
    try:
        from nodes.web.api.scanner import _get_scanner_instance
        scanner = _get_scanner_instance()
        if scanner:
            scanner.update_strategy_config(strategy_id, _get_effective_config(strategy_id))
    except Exception:
        pass

    cfg = _get_effective_config(strategy_id)
    logger.info(f"[CONFIG] 更新策略 {strategy_id}: enabled={cfg.get('enabled')}")
    return {"success": True, "data": cfg}


@router.get("/global-risk")
async def get_global_risk():
    """获取全局风控参数"""
    return {"success": True, "data": GLOBAL_RISK}


@router.put("/global-risk")
async def update_global_risk(req: GlobalRiskUpdate):
    """更新全局风控参数"""
    for k, v in req.updates.items():
        if k in GLOBAL_RISK:
            GLOBAL_RISK[k] = v
    logger.info(f"[CONFIG] 更新全局风控: {req.updates}")
    return {"success": True, "data": GLOBAL_RISK}


@router.post("/reset/{strategy_id}")
async def reset_strategy(strategy_id: str):
    """重置策略为默认参数"""
    _override_params.pop(strategy_id, None)
    _override_risk.pop(strategy_id, None)
    _override_enabled.pop(strategy_id, None)
    cfg = _get_effective_config(strategy_id)
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
        display_val = v * scale if isinstance(v, (int, float)) and scale != 1 and not isinstance(v, bool) else v
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
        display_val = v * scale if isinstance(v, (int, float)) and scale != 1 and not isinstance(v, bool) else v
        result.append({
            "key": k,
            "label": label,
            "value": v,
            "displayValue": display_val,
            "unit": unit,
            "type": "number",
        })
    return result
