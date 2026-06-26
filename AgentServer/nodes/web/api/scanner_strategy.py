#!/usr/bin/env python3
"""Scanner API - 策略参数/绩效/快照"""
import asyncio
import logging
import math
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from nodes.web.api.utils import sanitize_nan as _sanitize

# 从scanner共享模块导入
from nodes.web.api.scanner_shared import (
    _get_scanner, _get_scanner_instance, _clean_mongo,
    _fill_stock_names, _safe_read_shared, logger,
    ScannerStartRequest, ManualTradeRequest, PartialSellRequest,
    StopScannerRequest, ScanOnceRequest, PauseRequest,
)

router = APIRouter(prefix="/scanner", tags=["策略参数/绩效/快照"])


@router.post("/snapshot")
async def save_performance_snapshot():
    """保存当前性能快照到MongoDB(用于历史追踪)
    
    记录: 账户状态/持仓/信号/时间线/统计
    用于后续复盘和回测对比
    """
    scanner = await _get_scanner()
    if not scanner._broker:
        return {"success": True, "data": {"message": "Broker未初始化"}}
    
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": {}}
        
        acct = scanner._broker.get_account()
        positions = scanner._broker.get_positions()
        name_map = getattr(scanner, '_stock_name_map', {})
        
        snapshot = {
            "account_id": scanner._broker.account.account_id,
            "timestamp": datetime.now().isoformat(),
            "trade_date": datetime.now().strftime("%Y%m%d"),
            "account": {
                "total_assets": acct.total_assets,
                "available_cash": acct.available_cash,
                "market_value": acct.market_value,
                "total_profit": acct.total_profit,
            },
            "positions": [{
                "ts_code": p.ts_code,
                "stock_name": p.stock_name,
                "shares": p.total_qty,
                "cost_price": p.avg_cost,
                "current_price": p.current_price,
                "profit_pct": p.profit_pct,
                "strategy": p.strategy,
            } for p in positions],
            "active_signals": len(scanner._active_signals),
            "timeline_count": len(scanner._timeline),
            "stats": dict(scanner._stats),
            "circuit_breaker": scanner._circuit_breaker,
            "sentiment": scanner._current_sentiment,
            "position_ratio": scanner._current_position_ratio,
        }
        
        await mongo_manager.db["performance_snapshots"].insert_one(snapshot)
        
        return {"success": True, "data": {"message": "快照已保存", "timestamp": snapshot["timestamp"]}}
    except Exception as e:
        return {"success": True, "data": {"message": f"保存失败: {e}"}}



@router.get("/performance-history")
async def get_performance_history(days: int = 30):
    """获取历史性能快照(资产曲线)"""
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": []}
        
        start = (datetime.now() - timedelta(days=days)).isoformat()
        
        snapshots = []
        async for doc in mongo_manager.db["performance_snapshots"].find(
            {"timestamp": {"$gte": start}}
        ).sort("timestamp", 1):
            doc.pop("_id", None)
            snapshots.append(doc)
        
        return {"success": True, "data": snapshots, "count": len(snapshots)}
    except Exception as e:
        return {"success": True, "data": [], "message": str(e)}



@router.get("/params/{strategy_id}")
async def get_strategy_params(strategy_id: str):
    """获取策略参数(从参数中心读取)"""
    try:
        from nodes.market_monitor.strategy_param_center import param_center
        params = await param_center.get_strategy_params(strategy_id)
        if not params:
            return {"success": True, "data": {}, "message": f"策略{strategy_id}无参数"}
        return {"success": True, "data": params}
    except Exception as e:
        return {"success": True, "data": {}, "message": str(e)}



@router.get("/params")
async def get_all_strategy_params():
    """获取所有策略参数"""
    try:
        from nodes.market_monitor.strategy_param_center import param_center
        params = await param_center.get_all_params()
        return {"success": True, "data": params, "count": len(params)}
    except Exception as e:
        return {"success": True, "data": {}, "message": str(e)}



@router.put("/params/{strategy_id}")
async def update_strategy_params(strategy_id: str, request: Request):
    """更新策略参数(热更新,无需重启Scanner)
    
    修改后自动推送到Scanner, 回测和实盘共用同一参数源。
    """
    try:
        try:
            body = await request.json()
        except Exception:
            body = {}
        updates = body.get("params", {})
        comment = body.get("comment", "")
        updated_by = body.get("updated_by", "api")
        
        if not updates:
            return {"success": False, "message": "无参数更新"}
        
        from nodes.market_monitor.strategy_param_center import param_center
        
        # 注册Scanner热更新回调(如果还没注册)
        scanner = _get_scanner_instance()
        if scanner and not param_center._on_update:
            param_center.set_on_update_callback(scanner.update_strategy_config)
        
        ok = await param_center.update_strategy_params(
            strategy_id, updates, updated_by=updated_by, comment=comment
        )
        
        if ok:
            return {"success": True, "message": f"策略{strategy_id}参数已更新(热更新)"}
        else:
            return {"success": False, "message": "更新失败"}
    except Exception as e:
        return {"success": False, "message": str(e)}



@router.get("/params/{strategy_id}/history")
async def get_params_history(strategy_id: str, limit: int = 20):
    """获取策略参数修改历史"""
    try:
        from nodes.market_monitor.strategy_param_center import param_center
        history = await param_center.get_params_history(strategy_id, limit)
        return {"success": True, "data": history, "count": len(history)}
    except Exception as e:
        return {"success": True, "data": [], "message": str(e)}



@router.post("/params/{strategy_id}/reset")
async def reset_strategy_params(strategy_id: str):
    """重置策略参数为默认值"""
    try:
        from nodes.market_monitor.strategy_param_center import param_center
        ok = await param_center.reset_to_defaults(strategy_id)
        if ok:
            return {"success": True, "message": f"策略{strategy_id}参数已重置为默认值"}
        else:
            return {"success": False, "message": "重置失败"}
    except Exception as e:
        return {"success": False, "message": str(e)}



@router.post("/params/validate")
async def validate_params_before_update(request: Request):
    """【v2.9.15】参数预检验证(不实际更新)
    
    前端提交参数更新前先调用此端点, 检查参数合理性。
    返回warnings数组(空=安全可直接提交, 非空=需用户确认)。
    
    Body: {strategy_id: str, params: {key: value, ...}}
    """
    try:
        try:
            body = await request.json()
        except Exception:
            body = {}
        strategy_id = body.get("strategy_id", "default")
        params = body.get("params", {})
        
        if not params:
            return {"success": True, "warnings": [], "is_safe": True, "message": "无参数需验证"}
        
        warnings = []
        
        # 1. 止损检查
        sl = params.get("stop_loss_pct")
        if sl is not None:
            if sl > 0.10:
                warnings.append(f"止损{sl*100:.1f}%过宽, 实盘建议≤8%")
            elif sl < 0.02:
                warnings.append(f"止损{sl*100:.1f}%过紧, 实盘建议≥2%(容易被震出)")
        
        # 2. 止盈检查
        tp = params.get("take_profit_pct")
        if tp is not None and tp < 0.03:
            warnings.append(f"止盈{tp*100:.1f}%过低, 实盘建议≥3%")
        
        # 3. 单票仓位上限检查
        max_ratio = params.get("max_position_ratio")
        if max_ratio is not None and max_ratio > 0.8:
            warnings.append(f"单票仓位{max_ratio*100:.0f}%过高, 实盘建议≤15%")
        
        # 4. 追踪止损步长检查
        trail = params.get("trailing_stop_step")
        if trail is not None and trail < 0.01:
            warnings.append(f"追踪止损步长{trail*100:.1f}%过紧, 可能被震出")
        
        # 5. 情绪调仓比例检查
        rebalance = params.get("emotion_rebalance_ratio")
        if rebalance is not None and rebalance > 0.5:
            warnings.append(f"情绪调仓比例{rebalance*100:.0f}%过高, 建议≤30%")
        
        return {
            "success": True,
            "strategy_id": strategy_id,
            "warnings": warnings,
            "is_safe": len(warnings) == 0,
        }
    except Exception as e:
        return {"success": False, "message": str(e), "warnings": []}


# ==================== V59:执行质量 & 追踪止损 API ====================


@router.get("/strategy-performance")
async def get_strategy_performance():
    """策略实时绩效看板"""
    scanner = await _get_scanner()
    if not scanner._broker:
        return {"success": True, "data": []}

    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": []}
        positions = scanner._broker.get_positions()
        timeline = scanner._timeline
        from nodes.backtest_engine.strategy_defaults import STRATEGY_ID_TO_NAME
        strategy_names = dict(STRATEGY_ID_TO_NAME)
        strategy_names["manual"] = "手动"

        strategies = {}
        for key, name in strategy_names.items():
            strategies[key] = {"key": key, "name": name, "today_profit": 0, "total_profit": 0, "win_count": 0, "loss_count": 0, "position_count": 0, "closed_count": 0, "max_win_pct": 0, "max_loss_pct": 0, "sparkline": []}

        for pos in positions:
            key = pos.strategy or "manual"
            if key not in strategies:
                strategies[key] = {"key": key, "name": strategy_names.get(key, key), "today_profit": 0, "total_profit": 0, "win_count": 0, "loss_count": 0, "position_count": 0, "closed_count": 0, "max_win_pct": 0, "max_loss_pct": 0, "sparkline": []}
            profit = (pos.current_price - pos.avg_cost) * pos.total_qty
            strategies[key]["position_count"] += 1
            strategies[key]["total_profit"] += profit
            strategies[key]["today_profit"] += profit
            if profit >= 0: strategies[key]["win_count"] += 1
            else: strategies[key]["loss_count"] += 1

        all_profits = {}
        for item in (timeline or []):
            if item.get("action") == "sell" and item.get("strategy"):
                key = item["strategy"]
                pct = item.get("profit_pct", 0)
                all_profits.setdefault(key, []).append(pct)
                if key in strategies:
                    strategies[key]["closed_count"] += 1
                    if pct >= 0:
                        strategies[key]["win_count"] += 1
                        strategies[key]["max_win_pct"] = max(strategies[key]["max_win_pct"], pct)
                    else:
                        strategies[key]["loss_count"] += 1
                        strategies[key]["max_loss_pct"] = min(strategies[key]["max_loss_pct"], pct)

        for key, s in strategies.items():
            total = s["win_count"] + s["loss_count"]
            s["win_rate"] = round(s["win_count"] / max(total, 1) * 100, 1)
            profits = all_profits.get(key, [])
            avg_win = sum(p for p in profits if p >= 0) / max(sum(1 for p in profits if p >= 0), 1)
            avg_loss = abs(sum(p for p in profits if p < 0) / max(sum(1 for p in profits if p < 0), 1))
            s["profit_loss_ratio"] = round(avg_win / max(avg_loss, 0.01), 2)
            s["avg_profit_pct"] = round(sum(profits) / max(len(profits), 1), 2) if profits else 0

        # Sparkline from performance snapshots
        try:
            from datetime import datetime, timedelta
            start = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d")
            perf_data = []
            async for doc in mongo_manager.db["scanner_performance"].find({"date": {"$gte": start}}, {"_id": 0, "date": 1, "total_assets": 1}).sort("date", 1):
                perf_data.append(doc)
            if perf_data:
                baseline = perf_data[0].get("total_assets", 1000000)
                sparkline = [round((d.get("total_assets", baseline) / baseline - 1) * 100, 2) for d in perf_data]
                for key in strategies: strategies[key]["sparkline"] = sparkline
        except Exception:
            pass

        result = [s for s in strategies.values() if s["position_count"] > 0 or s["closed_count"] > 0]
        total_row = {"key": "total", "name": "合计", "today_profit": sum(s["today_profit"] for s in result), "total_profit": sum(s["total_profit"] for s in result),
                     "win_count": sum(s["win_count"] for s in result), "loss_count": sum(s["loss_count"] for s in result),
                     "win_rate": 0, "profit_loss_ratio": 0, "position_count": sum(s["position_count"] for s in result),
                     "closed_count": sum(s["closed_count"] for s in result), "max_win_pct": max((s["max_win_pct"] for s in result), default=0),
                     "max_loss_pct": min((s["max_loss_pct"] for s in result), default=0), "avg_profit_pct": 0, "sparkline": []}
        tt = total_row["win_count"] + total_row["loss_count"]
        total_row["win_rate"] = round(total_row["win_count"] / max(tt, 1) * 100, 1)
        result.append(total_row)
        return _sanitize({"success": True, "data": result})
    except Exception as e:
        return {"success": False, "message": str(e)}



@router.get("/strategy-params-compare")
async def get_strategy_params_compare():
    """策略参数对比 — 实盘(MongoDB) vs 回测(defaults.py)
    
    返回每个策略的所有参数, 标注与回测基线不同的字段
    用于诊断实盘-回测不一致问题
    """
    # 全局风控参数中文映射
    GLOBAL_RISK_LABELS = {
        "stop_loss_pct": "全局止损比例",
        "take_profit_pct": "全局止盈比例",
        "max_hold_days": "最大持仓天数",
        "slippage_pct": "滑点比例",
        "commission_rate": "综合佣金率",
        "stamp_duty_rate": "印花税率",
        "max_position_per_stock": "单票最大仓位",
        "max_total_position": "总仓位上限",
        "liquidity_threshold": "流动性门槛(万元)",
        "volume_threshold": "量能放大倍数",
        "force_empty_limit_down": "强制空仓-跌停数阈值",
        "force_empty_limit_up": "强制空仓-涨停数阈值",
        "force_empty_index_drop_pct": "强制空仓-大盘跌幅阈值",
        "force_empty_cooldown_days": "强制空仓冷却期(天)",
        "force_empty_cooldown_position_cap": "冷却期仓位上限",
        "dragon_head_early_exit_days": "龙头低吸-提前退出天数",
        "dragon_head_early_exit_min_profit": "龙头低吸-提前退出最低利润",
        "intraday_lock_min_high_rise": "盘中锁定-冲高幅度阈值",
        "intraday_lock_pullback_pct": "盘中锁定-回撤幅度阈值",
        "intraday_lock_min_profit": "盘中锁定-最低利润阈值",
        "hold_protection_threshold": "持仓保护阈值",
        "live_trading_mode": "实盘模式开关",
        "risk_free_rate": "无风险利率",
    }
    
    # 策略级参数中文映射(常用key)
    STRATEGY_PARAM_LABELS = {
        "stop_loss_pct": "止损比例",
        "take_profit_pct": "止盈比例",
        "max_hold_days": "最大持仓天数",
        "slippage_pct": "滑点比例",
        "pullback_sl_pct": "追踪止损比例",
        "pullback_mid_fallback": "回调中继回撤阈值",
        "hit_probability_slow": "慢板成交概率",
        "hit_probability_fast": "快板成交概率",
        "hit_probability_instant": "秒板成交概率",
        "hit_probability_one_char": "一字板成交概率",
        "next_day_open_sell_pct": "次日高开卖出阈值",
        "opening_pct_max": "开盘涨幅上限",
        "min_turnover_rate": "最低换手率",
        "min_rise_pct": "最低涨幅",
        "max_rise_pct": "最高涨幅",
        "min_volume_ratio": "最低量比",
        "max_volume_ratio": "最高量比",
        "min_close_pct": "最低收盘涨幅",
        "max_open_pct": "最高开盘涨幅",
        "before_10am_only": "仅10点前买入",
        "min_consecutive_limit": "最低连板数",
        "min_circ_mv": "最低流通市值(亿)",
        "max_circ_mv": "最高流通市值(亿)",
        "pullback_min_pct": "最低回调幅度",
        "pullback_max_pct": "最高回调幅度",
        "pullback_min_days": "最少回调天数",
        "pullback_max_days": "最多回调天数",
        "support_ma": "支撑均线",
        "consecutive_limit_down_days": "最低连跌天数",
        "min_qiaoban_amount": "最低翘板金额(万)",
        "min_qiaoban_rise_pct": "最低翘板后涨幅",
        "sentiment_override": "不限情绪周期",
    }
    
    try:
        from nodes.market_monitor.strategy_param_center import param_center
        await param_center.initialize()
        
        # 检测漂移
        drifts = await param_center.detect_drift()
        
        # 【V76-审计修复】读取strategy-config API的运行时覆盖(scanner_config.strategy_config_overrides)
        # 之前只读strategy_params集合,漏了前端API修改的覆盖,导致compare页面不准
        api_param_overrides = {}
        api_risk_overrides = {}
        api_enabled_overrides = {}
        api_global_risk_override = {}
        try:
            from core.managers import mongo_manager as _mm
            if _mm.is_initialized:
                override_doc = await _mm.db["scanner_config"].find_one(
                    {"_id": "strategy_config_overrides"}
                )
                if override_doc and "data" in override_doc:
                    api_param_overrides = override_doc["data"].get("params", {})
                    api_risk_overrides = override_doc["data"].get("risk", {})
                    api_enabled_overrides = override_doc["data"].get("enabled", {})
                    api_global_risk_override = override_doc["data"].get("global_risk", {})
        except Exception:
            pass
        
        # 获取所有策略参数(实盘)
        live_params = {}
        for strategy_id in ['halfway_chase', 'first_limit_up', 'limit_up_open', 'dragon_head', 'limit_down_qiao']:
            params = await param_center.get_strategy_params(strategy_id)
            if params:
                # 【V76-审计修复】合并strategy-config API的覆盖到live_params
                # strategy_params集合可能未包含前端API修改的参数,需合并
                if strategy_id in api_param_overrides:
                    params.setdefault("params", {}).update(api_param_overrides[strategy_id])
                if strategy_id in api_risk_overrides:
                    params.setdefault("riskParams", {}).update(api_risk_overrides[strategy_id])
                if strategy_id in api_enabled_overrides:
                    params["enabled"] = api_enabled_overrides[strategy_id]
                live_params[strategy_id] = params
        
        # 获取回测基线
        from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS, GLOBAL_RISK, STRATEGY_ID_TO_NAME
        backtest_params = {}
        for strategy_id, config in STRATEGY_CONFIGS.items():
            backtest_params[strategy_id] = config
        
        # 逐策略逐参数对比
        comparisons = []
        all_strategy_ids = set(list(live_params.keys()) + list(backtest_params.keys()))
        for sid in sorted(all_strategy_ids):
            live = live_params.get(sid, {})
            bt = backtest_params.get(sid, {})
            all_keys = set(list(live.keys()) + list(bt.keys()))
            
            param_diffs = []
            for key in sorted(all_keys):
                live_val = live.get(key)
                bt_val = bt.get(key)
                label = STRATEGY_PARAM_LABELS.get(key, key)
                if live_val != bt_val and live_val is not None and bt_val is not None:
                    param_diffs.append({
                        "key": key,
                        "label": label,
                        "live_value": live_val,
                        "backtest_value": bt_val,
                        "diff": True,
                    })
                elif live_val is not None:
                    param_diffs.append({
                        "key": key,
                        "label": label,
                        "live_value": live_val,
                        "backtest_value": bt_val,
                        "diff": False,
                    })
            
            comparisons.append({
                "strategy_id": sid,
                "strategy_name": STRATEGY_ID_TO_NAME.get(sid, sid),
                "live_params": live,
                "backtest_params": bt,
                "param_diffs": param_diffs,
                "drift_count": len([d for d in param_diffs if d.get("diff")]),
            })
        
        # 全局风控参数对比
        # 修复: globalRisk嵌在每个策略文档中, 不是独立文档
        # 从第一个可用策略的globalRisk字段读取实盘值
        live_gr = {}
        for sid in ['halfway_chase', 'first_limit_up', 'dragon_head', 'limit_down_qiao']:
            strategy_doc = live_params.get(sid, {})
            if isinstance(strategy_doc, dict) and strategy_doc.get('globalRisk'):
                live_gr = strategy_doc['globalRisk']
                break
        
        # 【V76-审计修复】合并strategy-config API的全局风控覆盖
        # 之前只读strategy_params中的globalRisk,漏了前端API修改的覆盖
        if api_global_risk_override:
            for k, v in api_global_risk_override.items():
                if k in live_gr and isinstance(live_gr[k], dict) and isinstance(v, dict):
                    merged = dict(live_gr[k])
                    merged.update(v)
                    live_gr[k] = merged
                else:
                    live_gr[k] = v
        
        global_diffs = []
        global_sames = []
        for key, bt_val in GLOBAL_RISK.items():
            live_val = live_gr.get(key)
            label = GLOBAL_RISK_LABELS.get(key, key)
            if live_val is None:
                # 实盘缺失此参数 = 使用回测默认值, 不算漂移
                global_sames.append({
                    "key": key,
                    "label": label,
                    "live_value": "(未配置,用默认值)",
                    "backtest_value": bt_val,
                    "diff": False,
                    "missing_in_live": True,
                })
            elif live_val != bt_val:
                global_diffs.append({
                    "key": key,
                    "label": label,
                    "live_value": live_val,
                    "backtest_value": bt_val,
                    "diff": True,
                    "missing_in_live": False,
                })
            else:
                global_sames.append({
                    "key": key,
                    "label": label,
                    "live_value": live_val,
                    "backtest_value": bt_val,
                    "diff": False,
                    "missing_in_live": False,
                })
        
        return {"success": True, "data": {
            "strategy_comparisons": comparisons,
            "global_risk": {
                "live": live_gr,
                "backtest": GLOBAL_RISK,
                "diffs": global_diffs,
                "sames": global_sames,
                "labels": GLOBAL_RISK_LABELS,
            },
            "drifts_detected": drifts,
            "drift_count": len(drifts) + len(global_diffs),
        }}
    except Exception as e:
        return {"success": True, "data": {"strategy_comparisons": [], "global_risk": {}, "drifts_detected": [], "drift_count": 0, "error": str(e)}}


# ==================== 扫描配置查询端点 ====================



# ==================== 风控决策审计 trail ====================

@router.get("/risk-decisions")
async def get_risk_decisions(trade_date: str = None, limit: int = 50):
    """查询风控决策审计记录
    
    Args:
        trade_date: 交易日期 YYYYMMDD (可选, 默认最近)
        limit: 返回条数 (默认50)
    """
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": []}
        
        query = {}
        if trade_date:
            td_int = int(trade_date) if trade_date.isdigit() else trade_date
            query["trade_date"] = td_int
        
        decisions = []
        cursor = mongo_manager.db["risk_decisions"].find(query).sort("timestamp", -1).limit(limit)
        async for doc in cursor:
            doc.pop("_id", None)
            decisions.append(doc)
        
        return {"success": True, "data": decisions, "count": len(decisions)}
    except Exception as e:
        return {"success": True, "data": [], "message": str(e)}


# ==================== 风控决策审计 trail ====================

@router.get("/risk-decisions")
async def get_risk_decisions(trade_date: str = None, limit: int = 50):
    """查询风控决策审计记录
    
    Args:
        trade_date: 交易日期 YYYYMMDD (可选, 默认最近)
        limit: 返回条数 (默认50)
    """
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": []}
        
        query = {}
        if trade_date:
            td_int = int(trade_date) if trade_date.isdigit() else trade_date
            query["trade_date"] = td_int
        
        decisions = []
        cursor = mongo_manager.db["risk_decisions"].find(query).sort("timestamp", -1).limit(limit)
        async for doc in cursor:
            doc.pop("_id", None)
            decisions.append(doc)
        
        return {"success": True, "data": decisions, "count": len(decisions)}
    except Exception as e:
        return {"success": True, "data": [], "message": str(e)}


# ==================== 风控决策审计 trail ====================

@router.get("/risk-decisions")
async def get_risk_decisions(trade_date: str = None, limit: int = 50):
    """查询风控决策审计记录
    
    Args:
        trade_date: 交易日期 YYYYMMDD (可选, 默认最近)
        limit: 返回条数 (默认50)
    """
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": []}
        
        query = {}
        if trade_date:
            td_int = int(trade_date) if trade_date.isdigit() else trade_date
            query["trade_date"] = td_int
        
        decisions = []
        cursor = mongo_manager.db["risk_decisions"].find(query).sort("timestamp", -1).limit(limit)
        async for doc in cursor:
            doc.pop("_id", None)
            decisions.append(doc)
        
        return {"success": True, "data": decisions, "count": len(decisions)}
    except Exception as e:
        return {"success": True, "data": [], "message": str(e)}
