"""数据扫描详情 API — 扫描体系全链路可视化"""
import logging

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


# ===================== 1. 架构总览 =====================

@router.get("/architecture")
async def get_architecture():
    scanner = _get_scanner()
    # sub_modules: 返回数组(前端用v-for遍历)
    sub_modules = [
        {"name": "StrategyScorer", "file": "strategy_scorer.py", "purpose": "策略筛选引擎", "key_methods": ["merge_factors", "apply_strategies", "_compute_pullback_pct"]},
        {"name": "SignalManager", "file": "signal_manager.py", "purpose": "信号生命周期管理", "key_methods": ["add_signal", "execute_signals"]},
        {"name": "QuoteManager", "file": "quote_manager.py", "purpose": "行情数据管理", "key_methods": ["fetch_realtime_batch", "get_quote"]},
        {"name": "PositionManager", "file": "position_manager.py", "purpose": "持仓管理(止损止盈)", "key_methods": ["check_stop_loss", "check_trailing_stop"]},
        {"name": "LiveFilterPipeline", "file": "live_filter_pipeline.py", "purpose": "9层筛选管道", "key_methods": ["apply", "_apply_L1_force_empty"]},
        {"name": "EmotionCycleManager", "file": "emotion_cycle.py", "purpose": "情绪周期(7维→4阶段)", "key_methods": ["compute_emotion_score"]},
        {"name": "RiskWatchdog", "file": "risk_watchdog.py", "purpose": "风控看门狗", "key_methods": ["check_health", "force_empty"]},
        {"name": "RuntimePersistence", "file": "runtime_persistence.py", "purpose": "运行时状态持久化", "key_methods": ["save_snapshot", "restore_snapshot"]},
        {"name": "Broker", "file": "broker.py", "purpose": "模拟券商", "key_methods": ["buy", "sell", "get_account"]},
    ]
    # data_flow: 返回字符串数组(前端用step.label显示)
    data_flow = [
        "行情获取(东方财富push2)",
        "因子合并(merge_factors)",
        "策略筛选(5策略独立)",
        "9层管道(L1→L9)",
        "信号管理(new→executed)",
        "下单执行(模拟Broker)",
        "持仓风控(1秒级止损)",
    ]
    # mongo_collections: 返回数组(前端ElTable需要name/purpose/count)
    mongo_collections = [
        {"name": "scan_traces", "purpose": "扫描追踪(漏斗+候选+拒绝)", "count": 0},
        {"name": "scanner_signals", "purpose": "信号记录(策略+因子+层链路)", "count": 0},
        {"name": "scanner_timeline", "purpose": "时间线(信号/执行/风控事件)", "count": 0},
        {"name": "broker_orders", "purpose": "委托订单", "count": 0},
        {"name": "broker_positions", "purpose": "持仓记录", "count": 0},
        {"name": "broker_accounts", "purpose": "账户快照", "count": 0},
        {"name": "equity_curve", "purpose": "资金曲线", "count": 0},
        {"name": "risk_decisions", "purpose": "风控决策", "count": 0},
        {"name": "sentiment_scores", "purpose": "情绪评分", "count": 0},
        {"name": "scanner_runtime_snapshot", "purpose": "运行时快照", "count": 0},
    ]
    # 补充count
    try:
        from core.managers import mongo_manager
        if mongo_manager.is_initialized:
            db = mongo_manager.db
            for col in mongo_collections:
                try:
                    col["count"] = await db[col["name"]].count_documents({})
                except Exception:
                    pass
    except Exception:
        pass

    runtime = {"is_running": False}
    if scanner and scanner.is_running():
        runtime = {
            "is_running": True,
            "trade_date": scanner.get_trade_date(),
            "scan_thread": getattr(scanner, '_task', None) is not None and not getattr(scanner, '_task', None).done(),
            "risk_thread": scanner.is_risk_running(),
            "prefetch": getattr(scanner, '_prefetch_running', False),
            "circuit_breaker": scanner.get_circuit_breaker(),
            "sentiment": scanner.get_current_sentiment(),
            "position_ratio": scanner.get_current_position_ratio(),
            "scan_errors": scanner.get_scan_error_count(),
        }

    return {"success": True, "data": {
        "runtime": runtime,
        "sub_modules": sub_modules,
        "data_flow": data_flow,
        "mongo_collections": mongo_collections,
    }}


# ===================== 2. 9层管道 =====================

@router.get("/pipeline")
async def get_pipeline_detail():
    # layers: 字段名对齐前端模板(name/description/enabled/input/output/rejected/condition/effect/icon/details)
    layers = [
        {"id": "L1", "name": "强制空仓", "icon": "🛑", "description": "涨停/跌停极端时清仓+冷却期", "enabled": True, "condition": "跌停≥80 或 涨停≤10且跌停>0 或 大盘跌≥3%", "effect": "卖出所有持仓, 冷却2交易日, 仓位上限60%"},
        {"id": "L2", "name": "特殊时期", "icon": "📅", "description": "月末/季末/年末/节前效应降仓", "enabled": True, "condition": "月末仓位70% / 季末60% / 年末50% / 节前50%", "effect": "仓位系数下调"},
        {"id": "L3", "name": "情绪周期", "icon": "🎭", "description": "7维评分→4阶段→仓位系数", "enabled": True, "condition": "高潮≥70→100% / 分化55-70→70% / 震荡40-55→50% / 冰点<40→25%", "effect": "仓位系数+可淘汰低优先级候选"},
        {"id": "L4", "name": "盘前预选", "icon": "🔍", "description": "排除ST/退市/次新/低流动", "enabled": True, "condition": "ST/退市排除 / 次新<60天排除 / 日均成交<500万排除", "effect": "候选精简"},
        {"id": "L5", "name": "竞价过滤", "icon": "⚡", "description": "真实竞价数据过滤(实盘优势)", "enabled": True, "condition": "高开>7%排除 / 低开<-5%排除 / 首板要求竞价≥2%", "effect": "排除极端竞价"},
        {"id": "L6", "name": "策略量能", "icon": "📐", "description": "5策略独立条件检查", "enabled": True, "condition": "半路:涨2-7%+量比>1.5 / 首板:涨停封板+10-500亿 / 龙头:连板回调5-22%+量比0.5-2 / 开板:2-4连板炸板 / 翘板:跌停撬板+量比>10", "effect": "核心筛选"},
        {"id": "L7", "name": "综合排序", "icon": "🏆", "description": "优先级排序+去重+截断", "enabled": True, "condition": "龙头>翘板>首板>半路 / 同股取最高优先级 / 最多10候选", "effect": "候选排序"},
        {"id": "L8", "name": "仓位控制", "icon": "⚖️", "description": "情绪×特殊×单票上限×冷却×MA60", "enabled": True, "condition": "min(情绪,特殊,硬上限70%) / 单票≤35% / 冷却期≤60% / MA60下×0.5 / 同板块≤3只", "effect": "最终仓位"},
        {"id": "L9", "name": "买入执行", "icon": "💰", "description": "T+1+跳空止损+成交概率+下单", "enabled": True, "condition": "T+1限制 / 跳空低开超止损即卖 / 滑点0.2% / 成交概率评估", "effect": "实际成交"},
    ]
    # 最新漏斗
    latest_funnel = {}
    try:
        from core.managers import mongo_manager
        if mongo_manager.is_initialized:
            db = mongo_manager.db
            cursor = db["scan_traces"].find({"candidates": {"$exists": True, "$ne": []}}).sort("_id", -1).limit(1)
            traces = await cursor.to_list(1)
            trace = traces[0] if traces else None
            if trace:
                latest_funnel = trace.get("summary", {})
    except Exception as e:
        logger.warning(f"获取最新scan_trace失败: {e}")
    return {"success": True, "data": {"layers": layers, "latest_funnel": latest_funnel}}


# ===================== 3. 策略配置 =====================

@router.get("/strategies")
async def get_strategy_detail():
    from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS, GLOBAL_RISK
    strategies = []
    for sid, cfg in STRATEGY_CONFIGS.items():
        # params: 转为前端ElTable需要的{name/value/desc}数组
        params_list = []
        raw_params = cfg.get("params", {})
        if isinstance(raw_params, dict):
            for pk, pv in raw_params.items():
                params_list.append({"name": pk, "value": str(pv), "desc": ""})
        # riskParams: 转为前端ElTable需要的数组
        risk_list = []
        raw_risk = cfg.get("riskParams", {})
        if isinstance(raw_risk, dict):
            for rk, rv in raw_risk.items():
                risk_list.append({"name": rk, "value": str(rv)})
        strategies.append({
            "id": sid,
            "name": cfg.get("name", sid),
            "enabled": cfg.get("enabled", True),
            "params": params_list,
            "risk_params": risk_list,
        })
    # globalRisk: 转为params数组
    global_risk_list = []
    if isinstance(GLOBAL_RISK, dict):
        for gk, gv in GLOBAL_RISK.items():
            global_risk_list.append({"name": gk, "value": str(gv), "desc": ""})
    return {"success": True, "data": {"strategies": strategies, "globalRisk": {"params": global_risk_list}}}


# ===================== 4. 情绪周期 =====================

@router.get("/emotion-cycle")
async def get_emotion_cycle():
    # dimensions: 前端ElTable需要name/weight/desc
    dimensions = [
        {"name": "涨停数", "weight": 0.25, "desc": "市场热度核心指标，涨停多=情绪高"},
        {"name": "跌停数", "weight": 0.25, "desc": "恐慌指标，跌停多=情绪低(负向)"},
        {"name": "涨跌比", "weight": 0.15, "desc": "上涨家数/下跌家数，反映广度"},
        {"name": "成交量", "weight": 0.10, "desc": "市场参与度，放量=活跃"},
        {"name": "北向资金", "weight": 0.10, "desc": "外资流向，净买入=看好"},
        {"name": "波动率", "weight": 0.05, "desc": "市场波动幅度"},
        {"name": "连板高度", "weight": 0.10, "desc": "最高连板数，龙头效应"},
    ]
    # periods: 前端需要name/color/span/score_min/score_max/position_ratio
    periods = [
        {"name": "高潮(rising)", "color": "#e74c3c", "span": 3, "score_min": 70, "score_max": 100, "position_ratio": 100},
        {"name": "分化(differentiation)", "color": "#e67e22", "span": 2, "score_min": 55, "score_max": 70, "position_ratio": 70},
        {"name": "震荡(chaos)", "color": "#3498db", "span": 2, "score_min": 40, "score_max": 55, "position_ratio": 50},
        {"name": "冰点(freezing)", "color": "#2c3e50", "span": 1, "score_min": 0, "score_max": 40, "position_ratio": 25},
    ]
    latest = {}
    try:
        from core.managers import mongo_manager
        if mongo_manager.is_initialized:
            db = mongo_manager.db
            cursor = db["sentiment_scores"].find().sort("_id", -1).limit(1)
            docs = await cursor.to_list(1)
            doc = docs[0] if docs else None
            if doc:
                latest = {
                    "score": doc.get("score"),
                    "period": doc.get("period"),
                    "limit_up_count": doc.get("limit_up_count"),
                    "limit_down_count": doc.get("limit_down_count"),
                    "broken_count": doc.get("broken_count"),
                    "broken_rate": doc.get("broken_rate"),
                    "trade_date": doc.get("trade_date"),
                }
    except Exception as e:
        logger.warning(f"获取情绪数据失败: {e}")
    return {"success": True, "data": {"dimensions": dimensions, "periods": periods, "latest": latest}}


# ===================== 5. 信号生命周期 =====================

@router.get("/signal-lifecycle")
async def get_signal_lifecycle():
    # states: 前端需要name/label/color/desc
    states = [
        {"name": "new", "label": "新信号", "color": "#409eff", "desc": "策略筛选通过，等待执行"},
        {"name": "deferred", "label": "延退", "color": "#e6a23c", "desc": "竞价/午休产生，等交易时段"},
        {"name": "dispatched", "label": "已派发", "color": "#00bcd4", "desc": "已发送给执行模块"},
        {"name": "executed", "label": "已执行", "color": "#67c23a", "desc": "已成功下单成交"},
        {"name": "expired", "label": "已过期", "color": "#909399", "desc": "超时未执行"},
        {"name": "skipped", "label": "跳过", "color": "#e6a23c", "desc": "L7截断或仓位不足"},
        {"name": "blocked", "label": "阻止", "color": "#f56c6c", "desc": "非交易时段/冷却期"},
    ]
    # expiry: 前端ElTable需要strategy/seconds/desc
    expiry = [
        {"strategy": "halfway_chase", "seconds": 300, "desc": "5分钟"},
        {"strategy": "first_limit_up", "seconds": 180, "desc": "3分钟"},
        {"strategy": "dragon_head", "seconds": 600, "desc": "10分钟"},
        {"strategy": "limit_down_qiao", "seconds": 1800, "desc": "30分钟(v2.9.112: 300→1800)"},
    ]
    # status_stats: 返回数组(前端v-for遍历)
    status_stats = []
    try:
        from core.managers import mongo_manager
        if mongo_manager.is_initialized:
            db = mongo_manager.db
            total = 0
            raw_stats = {}
            async for doc in db["scanner_signals"].aggregate([
                {"$group": {"_id": "$signal_status", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}}
            ]):
                status = doc["_id"] or "unknown"
                raw_stats[status] = doc["count"]
                total += doc["count"]
            color_map = {"new": "#409eff", "executed": "#67c23a", "skipped": "#e6a23c", "blocked": "#f56c6c", "expired": "#909399", "deferred": "#00bcd4"}
            for status, count in raw_stats.items():
                status_stats.append({
                    "status": status,
                    "count": count,
                    "pct": round(count / total * 100, 1) if total else 0,
                    "color": color_map.get(status, "#909399"),
                })
    except Exception as e:
        logger.warning(f"统计信号状态失败: {e}")
    return {"success": True, "data": {
        "states": states,
        "expiry": expiry,
        "status_stats": status_stats,
        "deferred_note": {"title": "v2.9.112 延退机制", "desc": "竞价/午休信号保持new不blocked，延退信号继续推送+持久化。limit_down_qiao过期时间从300秒延长到1800秒。"},
    }}


# ===================== 6. 行情管理 =====================

@router.get("/quote-manager")
async def get_quote_manager():
    # sources: 前端ElTable需要name/priority/purpose/fields/available
    sources = [
        {"name": "东方财富Push2", "priority": 1, "purpose": "盘中实时行情", "fields": "38字段(OHLCV+因子)", "available": "仅交易时间"},
        {"name": "东方财富DataCenter", "priority": 2, "purpose": "周末补采PE/PB", "fields": "PE/PB/流通市值", "available": "全时段"},
        {"name": "搜狐hisHq", "priority": 3, "purpose": "盘后fallback补采", "fields": "12字段(OHLCV+turn)", "available": "全时段"},
    ]
    # cache: 前端ElDescriptions需要直接key
    cache = {"max_age": "5秒(盘中)/30秒(盘后)", "time_source": "time.monotonic() (v2.9.112修复)"}
    # prefetch: 直接key
    prefetch = {"interval": "30秒/轮", "force": False, "anti_reentry": True}
    # degradation: steps数组
    degradation = {"steps": ["1. push2不可用→切datacenter", "2. 5分钟后重试push2", "3. 恢复后自动切回push2"]}
    # runtime: 直接key
    runtime = {"cache_size": 0, "source": "-"}
    scanner = _get_scanner()
    if scanner and hasattr(scanner, '_quote_manager'):
        qm = scanner._quote_manager
        runtime = {
            "cache_size": len(qm._cache) if hasattr(qm, '_cache') else 0,
            "source": getattr(qm, '_current_source', '-'),
        }
    return {"success": True, "data": {
        "sources": sources,
        "cache": cache,
        "prefetch": prefetch,
        "degradation": degradation,
        "runtime": runtime,
    }}


# ===================== 7. 风控体系 =====================

@router.get("/risk-system")
async def get_risk_system():
    scanner = _get_scanner()
    # 从代码动态读取实际参数, 替代硬编码
    from nodes.market_monitor.position_manager import (
        STRATEGY_ATR_RANGES, ATR_STOP_MULTIPLIER, ATR_STOP_PERIOD,
        ATR_STOP_CAP_PCT, ATR_STOP_MIN_PCT,
        PARTIAL_TAKE_PROFIT_THRESHOLD, PARTIAL_TAKE_PROFIT_RATIO,
        MIN_TRAILING_ACTIVATE_PCT,
    )
    try:
        from nodes.market_monitor.position_manager import _TRAILING_BASE, _DEFAULT_TRAILING_OFFSETS, STRATEGY_TRAILING_OFFSETS
    except ImportError:
        _TRAILING_BASE, _DEFAULT_TRAILING_OFFSETS = 0.05, (0.00, 0.02, 0.05, 0.08)
        STRATEGY_TRAILING_OFFSETS = {}

    STRAT_CN = {
        "halfway_chase": "半路追涨", "first_limit_up": "首板打板",
        "limit_up_open": "涨停开板", "dragon_head": "龙头低吸", "limit_down_qiao": "跌停翘板",
    }

    # 1. ATR自适应止损(实际参数)
    stop_loss = {}
    for sid, (lo, hi) in STRATEGY_ATR_RANGES.items():
        stop_loss[STRAT_CN.get(sid, sid)] = f"{lo:.1f}%-{hi:.1f}% (ATR×{ATR_STOP_MULTIPLIER})"

    # 2. 止盈(固定阈值)
    take_profit = {"半路追涨": "12%", "首板打板": "10%", "龙头低吸": "30%", "涨停开板": "6%", "跌停翘板": "20%"}

    # 3. 追踪止损(分级逻辑)
    trailing_stop = {}
    for sid in STRATEGY_ATR_RANGES:
        cn = STRAT_CN.get(sid, sid)
        offsets = STRATEGY_TRAILING_OFFSETS.get(sid, _DEFAULT_TRAILING_OFFSETS)
        base_pct = _TRAILING_BASE * 100
        tiers = []
        for i, label in enumerate(["<2%", "2-4%", "4-8%", "≥8%"]):
            if i < len(offsets):
                tiers.append(f"{label}→回撤{(base_pct + offsets[i]*100):.0f}%")
        trailing_stop[cn] = f"激活≥{MIN_TRAILING_ACTIVATE_PCT:.0f}% | " + " | ".join(tiers)

    # 4. 持仓天数
    max_hold_days = {"半路追涨": "3天", "首板打板": "2天", "龙头低吸": "7天", "涨停开板": "2天", "跌停翘板": "3天"}

    # 5. 高级风控规则(v2.9.118+新增)
    advanced_rules = [
        {"name": "ATR自适应止损", "version": "v2.9.119", "formula": f"min(max(策略下限, {ATR_STOP_MULTIPLIER}×ATR{ATR_STOP_PERIOD}), 策略上限)", "cap": f"全局封顶{ATR_STOP_CAP_PCT}%", "min": f"下限{ATR_STOP_MIN_PCT}%", "desc": "高波动股ATR大→止损宽, 低波动股ATR小→止损紧"},
        {"name": "跳空止损分级观察期", "version": "v2.9.118", "formula": "基于pre_close(非avg_cost)", "tiers": [{"range": "微跳<3%", "obs": "30分钟", "hit": "75%可避免假摔"}, {"range": "中跳3-5%", "obs": "10分钟", "hit": "部分可避免"}, {"range": "大跳>5%", "obs": "立即止损", "hit": "极端行情"}], "desc": "防止已亏损持仓被微跳空误杀"},
        {"name": "快速跌幅紧急止损", "version": "v2.9.124", "formula": "开盘vs当前跌幅>5%且持仓亏损", "action": "立即卖出", "desc": "防止开盘后急跌造成大亏损"},
        {"name": "分批止盈", "version": "v2.9.118", "formula": f"盈利≥{PARTIAL_TAKE_PROFIT_THRESHOLD:.0f}%时卖{PARTIAL_TAKE_PROFIT_RATIO*100:.0f}%仓位", "desc": "先落袋一半，剩余继续追踪"},
        {"name": "追踪止损高盈利紧缩", "version": "v2.9.116", "formula": "盈利≥8%时回撤容忍收紧到3%", "desc": "解决6-8%盈利被宽追踪洗出的问题"},
        {"name": "日内盈利锁定", "version": "v2.9.115", "formula": "日内盈利达到阈值时锁定", "desc": "防止日内盈利回吐"},
        {"name": "halfway_chase止损收窄", "version": "v2.9.124", "formula": "ATR上限4.5%→3.5%", "desc": "-5%~-8%区间20笔占18.3%, 收窄后跳空穿破最多-4.5%~-5%"},
    ]

    runtime = {}
    if scanner and scanner.is_running():
        try:
            runtime = {
                "circuit_breaker": scanner.get_circuit_breaker(),
                "position_ratio": scanner.get_current_position_ratio(),
                "force_empty": getattr(scanner, '_force_empty_active', False),
            }
        except Exception:
            pass
    return {"success": True, "data": {
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "trailing_stop": trailing_stop,
        "max_hold_days": max_hold_days,
        "advanced_rules": advanced_rules,
        "ma60_filter": True,
        "sector_top_n": 3,
        "runtime": runtime,
    }}


# ===================== 8. 扫描时序 =====================

@router.get("/timing")
async def get_scan_timing():
    # phases: 前端ElTable需要phase/time/action/scan/purpose + key_operations展开
    phases = [
        {"phase": "PREMARKET", "time": "07:00-09:00", "action": "盘前准备: 加载代码+因子", "scan": False, "purpose": "加载全市场5000+股票代码和日级因子，为实时扫描准备数据底座", "key_operations": ["mongo_manager恢复连接", "ak_full+daily_basic加载到内存", "必盈API初始化(涨停池)", "scanner.restore_snapshot()恢复昨日状态"]},
        {"phase": "AUCTION", "time": "09:00-09:25", "action": "竞价扫描: L4+L5+L6", "scan": True, "purpose": "集合竞价期间做预筛选，竞价数据是实盘独有优势", "key_operations": ["L4盘前预选: 排除ST/退市/次新/低流动", "L5竞价过滤: 排除高开>7%/低开<-5%", "L6策略量能: 5策略条件检查", "limit_down_qiao信号产生但延退(v2.9.112)"]},
        {"phase": "MORNING", "time": "09:30-11:30", "action": "早盘连续竞价扫描", "scan": True, "purpose": "核心交易时段，扫描间隔动态调整", "key_operations": ["09:30-10:00: 120秒/次(开盘剧烈)", "10:00-11:00: 180秒/次(趋势确认)", "11:00-11:30: 300秒/次(午盘清淡)", "行情预取线程30秒/轮", "风控循环1秒/次(止损止盈)"]},
        {"phase": "LUNCH", "time": "11:30-13:00", "action": "午休(信号可延退)", "scan": False, "purpose": "不触发新扫描，延退信号保持等待状态", "key_operations": ["scan_loop暂停", "延退信号保持new状态(v2.9.112)", "风控循环继续(止损不停)", "行情预取可能降频"]},
        {"phase": "AFTERNOON", "time": "13:00-15:00", "action": "下午盘扫描", "scan": True, "purpose": "下午盘扫描，尾盘加密", "key_operations": ["13:00-14:00: 300秒/次(盘初)", "14:00-14:30: 180秒/次(趋势加速)", "14:30-15:00: 120秒/次(尾盘冲刺)", "L1熔断检查: 尾盘极端行情清仓"]},
        {"phase": "AFTER_CLOSE", "time": "15:00+", "action": "盘后: 采补+持久化", "scan": False, "purpose": "盘后数据补采和状态持久化", "key_operations": ["东方财富daily_bar补采(3秒/全市场)", "东方财富daily_basic补PE/PB(2.4秒)", "fill_limit_list补涨停池", "scanner.save_snapshot()持久化运行时状态", "lightweight_factor_fill补技术指标"]},
    ]
    # intervals: 返回数组(前端v-for遍历)
    intervals = [
        {"time_range": "09:30-10:00", "seconds": 120, "reason": "开盘剧烈，高频捕捉"},
        {"time_range": "10:00-11:00", "seconds": 180, "reason": "趋势确认期，适度加密"},
        {"time_range": "11:00-11:30", "seconds": 300, "reason": "午盘清淡，降低频率"},
        {"time_range": "13:00-14:00", "seconds": 300, "reason": "盘初观察，频率适中"},
        {"time_range": "14:00-14:30", "seconds": 180, "reason": "趋势加速，适度加密"},
        {"time_range": "14:30-15:00", "seconds": 120, "reason": "尾盘冲刺，高频捕捉"},
    ]
    # premarket: 前端需要step/time/action/detail
    premarket = [
        {"step": 1, "time": "07:00", "action": "加载全市场代码列表", "detail": "从MongoDB stock_daily_ak_full获取最新交易日全市场代码"},
        {"step": 2, "time": "08:30", "action": "预加载日级因子", "detail": "daily_basic+ak_full: PE/PB/换手率/流通市值/连板数"},
        {"step": 3, "time": "09:00", "action": "竞价数据获取+L4预选", "detail": "东方财富push2获取竞价数据，L4排除ST/退市/次新"},
        {"step": 4, "time": "09:15", "action": "竞价风控观察", "detail": "多轮竞价数据确认趋势，避免单一时点误判"},
        {"step": 5, "time": "09:20", "action": "竞价风控确认+风险分级", "detail": "最终竞价确认，L1熔断判断，风险等级评估"},
        {"step": 6, "time": "09:25", "action": "最终确认+执行pending动作", "detail": "生成信号，派发给执行模块，准备9:30开盘"},
    ]
    return {"success": True, "data": {
        "phases": phases,
        "intervals": intervals,
        "premarket": premarket,
        "error_recovery": "盘中5秒/非交易30秒(v2.9.112)",
    }}


# ===================== 9. 最近扫描概览 =====================

@router.get("/recent-scans")
async def get_recent_scans(days: int = Query(default=5, ge=1, le=30)):
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return {"success": True, "data": []}
        db = mongo_manager.db
        cache_docs = await db["scan_date_cache"].find({}).sort("date", -1).limit(days).to_list(None)
        results = []
        for cache_doc in (cache_docs or []):
            td = cache_doc["date"]
            scan_count = cache_doc.get("count", 0)
            sig_stats = {}
            try:
                async for s in db["scanner_signals"].aggregate([
                    {"$match": {"trade_date": td}},
                    {"$group": {"_id": "$signal_status", "count": {"$sum": 1}}}
                ]):
                    sig_stats[s["_id"] or "unknown"] = s["count"]
            except Exception:
                pass
            results.append({
                "scan_date": td,
                "total_scans": scan_count,
                "signal_stats": sig_stats,
            })
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
        {"name": "pullback_pct", "unit": "小数(-0.15=回调15%)", "source": "实时计算(v2.9.112)", "used_by": "龙头", "formula": "1 - close/max(high_today, high_daily)", "note": "v2.9.112前补0导致dragon_head 0信号"},
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
