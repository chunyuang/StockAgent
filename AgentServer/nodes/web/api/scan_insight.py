"""数据扫描详情 API — 扫描体系全链路可视化"""
import logging
from typing import Dict

from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/scan-insight", tags=["scan-insight"])


def _get_scanner():
    """获取scanner实例(可能为None)"""
    try:
        from nodes.web.api.scanner_shared import _get_scanner_instance
        return _get_scanner_instance()
    except Exception:
        return None


async def _get_db():
    """获取MongoDB数据库实例(异步Motor)"""
    try:
        from core.managers import mongo_manager
        db = mongo_manager.db
        if db is not None:
            return db
    except Exception:
        pass
    return None


# ===================== 1. 架构总览 =====================

@router.get("/architecture")
async def get_architecture():
    scanner = _get_scanner()
    arch = {
        "core": {
            "name": "MarketScanner",
            "bases": ["ScannerInitializer", "ScanLoopRunner", "RiskLoopRunner", "ScannerAccessorsMixin"],
            "threads": {
                "scan_loop": {"purpose": "主扫描循环", "interval": "动态(120-300秒)", "phase_aware": True},
                "risk_loop": {"purpose": "风控循环(1秒级止损)", "interval": "1秒", "always_on": True},
                "prefetch": {"purpose": "行情预取(v2.9.112)", "interval": "30秒", "force": False},
                "daemon_ipc": {"purpose": "守护进程通信", "trigger": "event"},
            },
        },
        "sub_modules": {
            "StrategyScorer": {"file": "strategy_scorer.py", "purpose": "策略筛选引擎", "key_methods": ["merge_factors", "apply_strategies", "_compute_pullback_pct"]},
            "SignalManager": {"file": "signal_manager.py", "purpose": "信号生命周期管理", "key_methods": ["add_signal", "execute_signals"]},
            "QuoteManager": {"file": "quote_manager.py", "purpose": "行情数据管理", "key_methods": ["fetch_realtime_batch", "get_quote"]},
            "PositionManager": {"file": "position_manager.py", "purpose": "持仓管理(止损止盈)", "key_methods": ["check_stop_loss", "check_trailing_stop"]},
            "LiveFilterPipeline": {"file": "live_filter_pipeline.py", "purpose": "9层筛选管道", "key_methods": ["apply", "_apply_L1_force_empty"]},
            "EmotionCycleManager": {"file": "emotion_cycle.py", "purpose": "情绪周期(7维→4阶段)", "key_methods": ["compute_emotion_score"]},
            "RiskWatchdog": {"file": "risk_watchdog.py", "purpose": "风控看门狗", "key_methods": ["check_health", "force_empty"]},
            "RuntimePersistence": {"file": "runtime_persistence.py", "purpose": "运行时状态持久化", "key_methods": ["save_snapshot", "restore_snapshot"]},
            "Broker": {"file": "broker.py", "purpose": "模拟券商", "key_methods": ["buy", "sell", "get_account"]},
        },
        "data_flow": [
            {"step": 1, "name": "行情获取", "from": "QuoteManager", "to": "Scanner", "desc": "东方财富push2批量获取实时行情"},
            {"step": 2, "name": "因子合并", "from": "merge_factors", "to": "merged_df", "desc": "实时行情+日级因子合并，补算技术指标"},
            {"step": 3, "name": "策略筛选", "from": "apply_strategies", "to": "candidates", "desc": "5策略独立筛选"},
            {"step": 4, "name": "9层管道", "from": "LiveFilterPipeline", "to": "filtered", "desc": "L1→L2→L3→L4→L5→L6→L7→L8→L9"},
            {"step": 5, "name": "信号管理", "from": "SignalManager", "to": "signals", "desc": "new→dispatched→executed/expired/skipped/blocked"},
            {"step": 6, "name": "下单执行", "from": "Broker", "to": "orders", "desc": "模拟券商执行买入/卖出"},
            {"step": 7, "name": "持仓风控", "from": "PositionManager", "to": "positions", "desc": "1秒级止损止盈+追踪止损"},
        ],
        "mongo_collections": {
            "scan_traces": "扫描追踪(漏斗+候选+拒绝)",
            "scanner_signals": "信号记录(策略+因子+层链路)",
            "scanner_timeline": "时间线(信号/执行/风控事件)",
            "broker_orders": "委托订单", "broker_positions": "持仓记录",
            "broker_accounts": "账户快照", "equity_curve": "资金曲线",
            "risk_decisions": "风控决策", "sentiment_scores": "情绪评分",
            "scanner_runtime_snapshot": "运行时快照",
        },
    }
    if scanner and scanner.is_running():
        arch["runtime"] = {
            "is_running": True, "trade_date": scanner.get_trade_date(),
            "scan_thread": scanner._scan_thread is not None and scanner._scan_thread.is_alive(),
            "risk_thread": scanner.is_risk_running(),
            "prefetch": getattr(scanner, '_prefetch_running', False),
            "circuit_breaker": scanner.get_circuit_breaker(),
            "sentiment": scanner.get_current_sentiment(),
            "position_ratio": scanner.get_current_position_ratio(),
            "scan_errors": scanner.get_scan_error_count(),
        }
    else:
        arch["runtime"] = {"is_running": False}
    return {"success": True, "data": arch}


# ===================== 2. 9层管道 =====================

@router.get("/pipeline")
async def get_pipeline_detail():
    scanner = _get_scanner()
    layers = [
        {"id": "L1", "name": "强制空仓", "icon": "🛑", "desc": "涨停/跌停极端时清仓+冷却期", "conditions": ["跌停≥80", "涨停≤10且跌停>0", "大盘跌≥3%"], "effect": "卖出所有持仓, 冷却2交易日, 仓位上限60%"},
        {"id": "L2", "name": "特殊时期", "icon": "📅", "desc": "月末/季末/年末/节前效应降仓", "conditions": ["月末仓位70%", "季末60%", "年末50%", "节前50%"], "effect": "仓位系数下调"},
        {"id": "L3", "name": "情绪周期", "icon": "🎭", "desc": "7维评分→4阶段→仓位系数", "conditions": ["高潮≥70→100%", "分化55-70→70%", "震荡40-55→50%", "冰点<40→25%"], "effect": "仓位系数+可淘汰低优先级候选"},
        {"id": "L4", "name": "盘前预选", "icon": "🔍", "desc": "排除ST/退市/次新/低流动", "conditions": ["ST/退市排除", "次新<60天排除", "日均成交<500万排除"], "effect": "候选精简"},
        {"id": "L5", "name": "竞价过滤", "icon": "⚡", "desc": "真实竞价数据过滤(实盘优势)", "conditions": ["高开>7%排除", "低开<-5%排除", "首板要求竞价≥2%"], "effect": "排除极端竞价"},
        {"id": "L6", "name": "策略量能", "icon": "📐", "desc": "5策略独立条件检查", "conditions": ["半路:涨2-7%+量比>1.5", "首板:涨停封板+10-500亿", "龙头:连板回调5-22%+量比0.5-2", "开板:2-4连板炸板", "翘板:跌停撬板+量比>10"], "effect": "核心筛选"},
        {"id": "L7", "name": "综合排序", "icon": "🏆", "desc": "优先级排序+去重+截断", "conditions": ["龙头>翘板>首板>半路", "同股取最高优先级", "最多10候选"], "effect": "候选排序"},
        {"id": "L8", "name": "仓位控制", "icon": "⚖️", "desc": "情绪×特殊×单票上限×冷却×MA60", "conditions": ["min(情绪,特殊,硬上限70%)", "单票≤35%", "冷却期≤60%", "MA60下×0.5", "同板块≤3只"], "effect": "最终仓位"},
        {"id": "L9", "name": "买入执行", "icon": "💰", "desc": "T+1+跳空止损+成交概率+下单", "conditions": ["T+1限制", "跳空低开超止损即卖", "滑点0.2%", "成交概率评估"], "effect": "实际成交"},
    ]
    # 最新漏斗
    latest_funnel, latest_details = {}, {}
    try:
        db = await _get_db()
        if db is not None:
            cursor = db["scan_traces"].find({"candidates": {"$exists": True, "$ne": []}}).sort("_id", -1).limit(1)
            traces = await cursor.to_list(1)
            trace = traces[0] if traces else None
            if trace:
                latest_funnel = trace.get("summary", {})
                latest_details = trace.get("layer_details", {})
    except Exception as e:
        logger.warning(f"获取最新scan_trace失败: {e}")
    return {"success": True, "data": {"layers": layers, "latest_funnel": latest_funnel, "latest_details": latest_details}}


# ===================== 3. 策略配置 =====================

@router.get("/strategies")
async def get_strategy_detail():
    from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS, GLOBAL_RISK
    strategies = []
    for sid, cfg in STRATEGY_CONFIGS.items():
        strategies.append({"id": sid, "name": cfg.get("name", sid), "enabled": cfg.get("enabled", True), "params": cfg.get("params", {}), "riskParams": cfg.get("riskParams", {})})
    return {"success": True, "data": {"strategies": strategies, "globalRisk": GLOBAL_RISK}}


# ===================== 4. 情绪周期 =====================

@router.get("/emotion-cycle")
async def get_emotion_cycle():
    scanner = _get_scanner()
    dims = [
        {"id": "limit_up", "name": "涨停数", "weight": "高"},
        {"id": "limit_down", "name": "跌停数", "weight": "高(负)"},
        {"id": "up_down", "name": "涨跌比", "weight": "中"},
        {"id": "volume", "name": "成交量", "weight": "中"},
        {"id": "north", "name": "北向资金", "weight": "中"},
        {"id": "volatility", "name": "波动率", "weight": "低"},
        {"id": "consecutive", "name": "连板高度", "weight": "高"},
    ]
    periods = [
        {"name": "高潮(rising)", "min": 70, "ratio": "100%", "desc": "市场亢奋，满仓"},
        {"name": "分化(differentiation)", "min": 55, "ratio": "70%", "desc": "板块分化，适度参与"},
        {"name": "震荡(chaos)", "min": 40, "ratio": "50%", "desc": "方向不明，半仓防守"},
        {"name": "冰点(freezing)", "min": 0, "ratio": "25%", "desc": "市场低迷，低仓观望"},
    ]
    latest = {}
    try:
        db = await _get_db()
        if db:
            cursor = db["sentiment_scores"].find().sort("_id", -1).limit(1)
            docs = await cursor.to_list(1)
            doc = docs[0] if docs else None
            if doc:
                latest = {"score": doc.get("score"), "period": doc.get("period"), "limit_up": doc.get("limit_up_count"), "limit_down": doc.get("limit_down_count"), "broken": doc.get("broken_count"), "broken_rate": doc.get("broken_rate"), "trade_date": doc.get("trade_date"), "factors": doc.get("factors", {})}
        else:
            logger.warning("emotion-cycle: db is None")
    except Exception as e:
        logger.warning(f"获取情绪数据失败: {e}")
    return {"success": True, "data": {"dimensions": dims, "periods": periods, "latest": latest}}


# ===================== 5. 信号生命周期 =====================

@router.get("/signal-lifecycle")
async def get_signal_lifecycle():
    scanner = _get_scanner()
    states = [
        {"name": "new", "label": "新信号", "icon": "🆕", "color": "blue", "desc": "策略筛选通过，等待执行"},
        {"name": "deferred", "label": "延退", "icon": "⏳", "color": "orange", "desc": "竞价/午休产生，等交易时段"},
        {"name": "dispatched", "label": "已派发", "icon": "📤", "color": "cyan", "desc": "已发送给执行模块"},
        {"name": "executed", "label": "已执行", "icon": "✅", "color": "green", "desc": "已成功下单成交"},
        {"name": "expired", "label": "已过期", "icon": "⏰", "color": "gray", "desc": "超时未执行"},
        {"name": "skipped", "label": "跳过", "icon": "⏭️", "color": "yellow", "desc": "L7截断或仓位不足"},
        {"name": "blocked", "label": "阻止", "icon": "🚫", "color": "red", "desc": "非交易时段/冷却期"},
    ]
    expiry = [
        {"strategy": "halfway_chase", "seconds": 300, "desc": "5分钟"},
        {"strategy": "first_limit_up", "seconds": 180, "desc": "3分钟"},
        {"strategy": "dragon_head", "seconds": 600, "desc": "10分钟"},
        {"strategy": "limit_down_qiao", "seconds": 1800, "desc": "30分钟(v2.9.112: 300→1800)"},
    ]
    status_stats = {}
    try:
        db = await _get_db()
        if db:
            async for doc in db["scanner_signals"].aggregate([{"$group": {"_id": "$signal_status", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}]):
                status_stats[doc["_id"] or "unknown"] = doc["count"]
    except Exception as e:
        logger.warning(f"统计信号状态失败: {e}")
    return {"success": True, "data": {"states": states, "expiry": expiry, "status_stats": status_stats, "deferred_note": "v2.9.112: 竞价/午休信号保持new不blocked，延退信号继续推送+持久化"}}


# ===================== 6. 行情管理 =====================

@router.get("/quote-manager")
async def get_quote_manager():
    scanner = _get_scanner()
    sources = [
        {"name": "东方财富Push2", "priority": 1, "usage": "盘中实时", "fields": "38字段", "limit": "无限~3秒/次", "avail": "仅交易时间"},
        {"name": "东方财富DataCenter", "priority": 2, "usage": "周末补采PE/PB", "fields": "PE/PB/流通市值", "avail": "全时段"},
        {"name": "搜狐hisHq", "priority": 3, "usage": "盘后fallback", "fields": "12字段", "avail": "全时段"},
    ]
    cache = {"max_age": "5秒(盘中)/30秒(盘后)", "time_source": "time.monotonic() (v2.9.112修复)"}
    prefetch = {"interval": "30秒/轮", "force": False, "anti_reentry": "_prefetch_in_progress标志", "purpose": "提前拉取候选股行情"}
    degradation = {"steps": ["push2不可用→datacenter", "5分钟重试push2", "恢复后自动切回"]}
    runtime = {}
    if scanner and hasattr(scanner, '_quote_manager'):
        qm = scanner._quote_manager
        runtime = {"cache_size": len(qm._cache) if hasattr(qm, '_cache') else 0, "source": getattr(qm, '_current_source', 'unknown')}
    return {"success": True, "data": {"sources": sources, "cache": cache, "prefetch": prefetch, "degradation": degradation, "runtime": runtime}}


# ===================== 7. 风控体系 =====================

@router.get("/risk-system")
async def get_risk_system():
    scanner = _get_scanner()
    stop_loss = {"halfway_chase": "3%", "first_limit_up": "3.5%", "dragon_head": "3%", "limit_up_open": "5%", "limit_down_qiao": "5%"}
    take_profit = {"halfway_chase": "12%", "first_limit_up": "10%", "dragon_head": "30%", "limit_up_open": "6%", "limit_down_qiao": "20%"}
    trailing = {"halfway_chase": "保护4%回撤2%", "first_limit_up": "回撤2%", "dragon_head": "保护4%回撤3%", "limit_down_qiao": "回撤4%"}
    hold_days = {"halfway_chase": 3, "first_limit_up": 2, "dragon_head": 7, "limit_up_open": 2, "limit_down_qiao": 3}
    runtime = {}
    if scanner and scanner.is_running():
        try:
            runtime = {"circuit_breaker": scanner.get_circuit_breaker(), "position_ratio": scanner.get_current_position_ratio(), "cooldown": getattr(scanner, '_cooldown_info', None), "force_empty": getattr(scanner, '_force_empty_active', False)}
        except Exception:
            pass
    return {"success": True, "data": {"stop_loss": stop_loss, "take_profit": take_profit, "trailing_stop": trailing, "max_hold_days": hold_days, "ma60_filter": True, "sector_top_n": 3, "runtime": runtime}}


# ===================== 8. 扫描时序 =====================

@router.get("/timing")
async def get_scan_timing():
    phases = [
        {"phase": "PREMARKET", "time": "07:00-09:00", "action": "盘前准备: 加载代码+因子", "scan": False},
        {"phase": "AUCTION", "time": "09:00-09:25", "action": "竞价扫描: L4+L5+L6", "scan": True},
        {"phase": "MORNING", "time": "09:30-11:30", "action": "早盘连续竞价扫描", "scan": True},
        {"phase": "LUNCH", "time": "11:30-13:00", "action": "午休(信号可延退)", "scan": False},
        {"phase": "AFTERNOON", "time": "13:00-15:00", "action": "下午盘扫描", "scan": True},
        {"phase": "AFTER_CLOSE", "time": "15:00+", "action": "盘后: 采补+持久化", "scan": False},
    ]
    intervals = {"09:30-10:00": 120, "10:00-11:00": 180, "11:00-11:30": 300, "13:00-14:00": 300, "14:00-14:30": 180, "14:30-15:00": 120}
    premarket = [
        {"step": 1, "time": "07:00", "action": "加载全市场代码列表"},
        {"step": 2, "time": "08:30", "action": "预加载日级因子(daily_basic+ak_full)"},
        {"step": 3, "time": "09:00", "action": "竞价数据获取+L4预选"},
        {"step": 4, "time": "09:15", "action": "竞价风控观察(多轮确认)"},
        {"step": 5, "time": "09:20", "action": "竞价风控确认+风险分级"},
        {"step": 6, "time": "09:25", "action": "最终确认+执行pending动作"},
    ]
    return {"success": True, "data": {"phases": phases, "intervals": intervals, "premarket": premarket, "error_recovery": "盘中5秒/非交易30秒(v2.9.112)"}}


# ===================== 9. 最近扫描概览 =====================

@router.get("/recent-scans")
async def get_recent_scans(days: int = Query(default=5, ge=1, le=30)):
    try:
        db = await _get_db()
        if db is None:
            return {"success": True, "data": []}
        pipeline = [
            {"$sort": {"_id": -1}},
            {"$group": {"_id": "$trade_date", "scan_count": {"$sum": 1}, "candidates": {"$sum": {"$size": {"$ifNull": ["$candidates", []]}}}, "rejected": {"$sum": {"$size": {"$ifNull": ["$rejected_summary", []]}}}}},
            {"$sort": {"_id": -1}}, {"$limit": days},
        ]
        results = []
        async for doc in db["scan_traces"].aggregate(pipeline):
            td = doc["_id"]
            sig_stats, strat_stats = {}, {}
            try:
                async for s in db["scanner_signals"].aggregate([{"$match": {"trade_date": td}}, {"$group": {"_id": "$signal_status", "count": {"$sum": 1}}}]):
                    sig_stats[s["_id"] or "unknown"] = s["count"]
                async for s in db["scanner_signals"].aggregate([{"$match": {"trade_date": td}}, {"$group": {"_id": "$strategy", "count": {"$sum": 1}}}]):
                    strat_stats[s["_id"] or "unknown"] = s["count"]
            except Exception:
                pass
            results.append({"trade_date": td, "scan_count": doc["scan_count"], "candidates": doc["candidates"], "rejected": doc["rejected"], "signal_stats": sig_stats, "strategy_stats": strat_stats})
        return {"success": True, "data": results}
    except Exception as e:
        logger.error(f"获取最近扫描概览失败: {e}")
        return {"success": True, "data": []}


# ===================== 10. 因子详情 =====================

@router.get("/factors")
async def get_factor_detail():
    factors = [
        {"name": "pct_chg", "unit": "百分数(3.5=涨3.5%)", "source": "实时行情", "used_by": "所有策略"},
        {"name": "volume_ratio", "unit": "倍数(1.5=1.5倍量)", "source": "实时行情/daily_basic", "used_by": "所有策略"},
        {"name": "turnover_rate", "unit": "百分数(25.0=换手25%)", "source": "实时行情/daily_basic", "used_by": "首板,翘板"},
        {"name": "circ_mv", "unit": "万元(merged_df统一)", "source": "push2(元)→daily_basic(亿)→统一万元", "used_by": "首板,龙头,翘板", "warning": "3个来源单位不同, merge时需转换"},
        {"name": "is_limit_up", "unit": "0/1", "source": "ak_full", "used_by": "首板"},
        {"name": "limit_up_count", "unit": "连板数(1,2,3...)", "source": "ak_full(必盈limit_times优先)", "used_by": "龙头,开板", "note": "v2.9.112: 旧代码用is_limit_up(0/1)覆盖, 修复为fallback到daily_df"},
        {"name": "pullback_pct", "unit": "小数(-0.15=回调15%)", "source": "实时计算(v2.9.112)", "used_by": "龙头", "formula": "1 - close/high_max(high_today, high_daily)", "note": "v2.9.112前补0导致dragon_head 0信号"},
        {"name": "pullback_days", "unit": "天数(1-7)", "source": "实时计算(v2.9.112)", "used_by": "龙头", "formula": "从T-1涨停日到T日回调天数"},
        {"name": "pe_ttm", "unit": "倍", "source": "daily_basic", "used_by": "展示"},
        {"name": "pb_mrq", "unit": "倍", "source": "daily_basic", "used_by": "展示"},
        {"name": "intraday_limit_up", "unit": "0/1(盘中触涨停)", "source": "ak_high>=pre_close*1.1推算", "used_by": "展示", "note": "盘中触涨停但收盘未封=炸板"},
    ]
    merge_flow = [
        {"step": 1, "source": "实时行情(push2)", "fields": "OHLCV+pct_chg+turnover_rate+volume_ratio+circ_mv", "note": "circ_mv=元"},
        {"step": 2, "source": "daily_basic(MongoDB)", "fields": "pe_ttm+pb_mrq+circ_mv", "note": "circ_mv=亿元(×10000→万元)"},
        {"step": 3, "source": "ak_full(MongoDB)", "fields": "is_limit_up+limit_up_count+limit_times+high", "note": "limit_times=必盈连板数(优先)"},
        {"step": 4, "source": "实时计算", "fields": "pullback_pct+pullback_days", "note": "v2.9.112新增"},
    ]
    return {"success": True, "data": {"factors": factors, "merge_flow": merge_flow}}
