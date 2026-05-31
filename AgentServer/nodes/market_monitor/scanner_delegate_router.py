"""Scanner委托路由器 — __getattr__动态分派逻辑提取【v2.9.17】

将scanner.py的95行__getattr__方法拆分为可维护的路由策略模式。

设计原则:
- 6种路由策略(RiskWatchdog/ScannerUtils/StrategyScorer/QuoteManager/AsyncFallback/Simple)
- 每种策略一个清晰的resolve方法
- __getattr__缩减为3行调度
- 零行为变更(纯重构)
"""

import logging
import pandas as pd

logger = logging.getLogger(__name__)


# 已知async委托方法集合(模块未初始化时返回coroutine noop)
_ASYNC_DELEGATE_METHODS = frozenset({
    # RuntimePersistence (all async)
    "_save_timeline", "_save_scan_traces", "_load_timeline",
    "_load_runtime_snapshot", "_save_runtime_snapshot", "_premarket_auction",
    "_save_performance_snapshot", "_push_daily_summary",
    "_post_sell_cleanup",  # v2.9.27: async
    "_save_param_snapshot",  # v2.9.42: async
    # SignalManager (partial async)
    "_update_signals", "_push_signals", "_execute_signals", "_write_audit_log",
    # PositionChecker (partial async)
    "_check_positions", "_check_positions_quick",
    # ScannerUtils (publish_scanner_event is async)
    "_publish_scanner_event",
    # StrategyScorer
    "_apply_strategies", "_detect_anomalies",
    # RiskWatchdog
    "_check_circuit_breaker",
    # EmotionCycleManager
    "_handle_emotion_phase_change",
    "_update_sentiment_score",  # v2.9.34
    # PositionManager (async sell execution)
    "_execute_risk_sell",  # v2.9.35
    "_liquidate_positions",  # v2.9.35
    # StrategyParamCenter (async)
    "_detect_param_drift",  # v2.9.42
    "_load_strategy_overrides",  # v2.9.42
    "_persist_strategy_overrides",  # v2.9.42
})

# StrategyScorer未初始化时的fallback返回值
_SCORER_FALLBACKS = {
    "_merge_factors": lambda *a, **kw: pd.DataFrame(),
    "_get_effective_strategy_config": lambda *a, **kw: {},
    "_get_strategy_risk": lambda *a, **kw: {
        "stop_loss_pct": 0.03, "take_profit_pct": 0.07, "trailing_stop_pct": 0.05
    },
    "_detect_anomalies": lambda *a, **kw: [],
}

# ScannerUtils需要self上下文绑定的方法
_UTILS_CONTEXT_METHODS = {
    "_position_to_dict": lambda scanner, method: lambda p: method(p, risk_getter=scanner._get_strategy_risk),
    "_signal_to_dict": lambda scanner, method: lambda s: method(s, scanner.SIGNAL_EXPIRE_SECONDS),
    "generate_summary_report": lambda scanner, method: lambda: method(scanner),
    "_compute_health_score": lambda scanner, method: lambda: method(scanner),
    "diagnose": lambda scanner, method: lambda: method(scanner),
    "_build_account_info": lambda scanner, method: lambda: method(scanner),  # v2.9.27
}

# RiskWatchdog静态方法绑定(第一个参数为scanner实例)
_WATCHDOG_BINDINGS = {
    "check_circuit_breaker": lambda method, scanner: lambda *a, **kw: method(scanner, *a, **kw) if a else method(scanner),
    "record_trade_result": lambda method, scanner: lambda profit_pct: method(scanner, profit_pct),
    "reset_circuit_breaker": lambda method, scanner: lambda: method(scanner),
}

# EmotionCycleManager静态方法绑定(第一个参数为scanner实例)
_EMOTION_BINDINGS = {
    "handle_emotion_phase_change": lambda method, scanner: lambda old_phase, new_phase: method(scanner, old_phase, new_phase),
    "update_sentiment_score": lambda method, scanner: lambda trade_date: method(scanner, trade_date),
}

# StrategyParamCenter静态方法绑定
_PARAM_CENTER_BINDINGS = {
    "validate_live_params": lambda method, scanner: lambda: method(scanner._broker, scanner._get_strategy_risk),
    "detect_and_publish_drift": lambda method, scanner: lambda: method(scanner),
    "apply_scanner_config_update": lambda method, scanner: lambda strategy_key, updates: method(scanner, strategy_key, updates),
    "load_and_apply_scanner_overrides": lambda method, scanner: lambda: method(scanner),
    "persist_scanner_overrides": lambda method, scanner: lambda: method(scanner.config),
}


def resolve_delegate(scanner, name: str, delegate: tuple):
    """解析委托调用 — 根据模块类型分派到对应策略

    Args:
        scanner: MarketScanner实例
        name: 被调用的方法名
        delegate: (module_attr, method_name) 委托映射
    Returns:
        可调用对象或属性
    """
    module_attr, method_name = delegate

    # 策略1: QuoteManager类方法(不是实例)
    if module_attr == "_quote_manager_class":
        from nodes.market_monitor.quote_manager import QuoteManager
        return getattr(QuoteManager, method_name)

    # 策略2: RiskWatchdog类静态方法
    if module_attr == "_risk_watchdog_class":
        from nodes.market_monitor.risk_watchdog import RiskWatchdog
        method = getattr(RiskWatchdog, method_name)
        binder = _WATCHDOG_BINDINGS.get(method_name)
        if binder:
            return binder(method, scanner)
        return method

    # 策略3: ScannerUtils(部分方法需要scanner上下文绑定)
    if module_attr == "_scanner_utils":
        from nodes.market_monitor.scanner_utils import ScannerUtils
        method = getattr(ScannerUtils, method_name)
        binder = _UTILS_CONTEXT_METHODS.get(name)
        if binder:
            return binder(scanner, method)
        return method

    # 策略3.5: EmotionCycleManager(类静态方法, 绑定scanner上下文)
    if module_attr == "_emotion_cycle_class":
        from nodes.market_monitor.emotion_cycle import EmotionCycleManager
        method = getattr(EmotionCycleManager, method_name)
        binder = _EMOTION_BINDINGS.get(method_name)
        if binder:
            return binder(method, scanner)
        return method

    # 策略3.6: StrategyParamCenter(类静态方法, 绑定scanner上下文)【v2.9.42】
    if module_attr == "_strategy_param_center_class":
        from nodes.market_monitor.strategy_param_center import StrategyParamCenter
        method = getattr(StrategyParamCenter, method_name)
        binder = _PARAM_CENTER_BINDINGS.get(method_name)
        if binder:
            return binder(method, scanner)
        return method

    # 策略4: StrategyScorer(需要fallback + 上下文绑定)
    if module_attr == "_strategy_scorer":
        return _resolve_scorer(scanner, name, module_attr, method_name)

    # 策略5+6: 普通模块委托(含未初始化fallback)
    module = getattr(scanner, module_attr, None)
    if module is None:
        return _resolve_noop_fallback(module_attr, name)
    return getattr(module, method_name)


def _resolve_scorer(scanner, name: str, module_attr: str, method_name: str):
    """策略4: StrategyScorer委托解析"""
    module = getattr(scanner, module_attr, None)
    if module is None:
        # 未初始化fallback
        fallback = _SCORER_FALLBACKS.get(name)
        if fallback:
            return fallback
        return lambda *a, **kw: None

    method = getattr(module, method_name)
    # _detect_anomalies需要scanner上下文
    if name == "_detect_anomalies":
        async def _async_detect_anomalies(realtime_data):
            return method(realtime_data, scanner._active_signals, scanner._prev_realtime_cache)
        return _async_detect_anomalies
    return method


def _resolve_noop_fallback(module_attr: str, name: str):
    """策略5+6: 模块未初始化时的noop fallback"""
    if name in _ASYNC_DELEGATE_METHODS:
        logger.warning(f"[SCANNER] 委托模块 {module_attr} 未初始化, 异步方法 {name} 返回noop coroutine")
        async def _async_noop(*args, **kwargs):
            return None
        return _async_noop
    else:
        logger.warning(f"[SCANNER] 委托模块 {module_attr} 未初始化, 同步方法 {name} 返回None")
        return lambda *args, **kwargs: None
