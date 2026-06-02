"""Scanner委托路由器 — __getattr__动态分派逻辑提取【v2.9.17】

将scanner.py的95行__getattr__方法拆分为可维护的路由策略模式。

设计原则:
- 6种路由策略(RiskWatchdog/ScannerUtils/StrategyScorer/QuoteManager/AsyncFallback/Simple)
- 每种策略一个清晰的resolve方法
- __getattr__缩减为3行调度
- 零行为变更(纯重构)
"""

import logging
from typing import Any
import pandas as pd

logger = logging.getLogger(__name__)


# ==================== 委托映射表【v2.9.52:从scanner.py外提】 ====================

DELEGATE_MAP = {
    # RuntimePersistence委托
    "_save_timeline": ("_runtime_persistence", "save_timeline"),
    "_save_scan_traces": ("_runtime_persistence", "save_scan_traces"),
    "_load_timeline": ("_runtime_persistence", "load_timeline"),
    "_load_runtime_snapshot": ("_runtime_persistence", "load_runtime_snapshot"),
    "_save_runtime_snapshot": ("_runtime_persistence", "save_runtime_snapshot"),
    "_premarket_auction": ("_runtime_persistence", "premarket_auction"),
    # QuoteManager委托
    "_short_to_ts_code": ("_quote_manager_class", "short_to_ts_code"),
    # StrategyScorer委托
    "_apply_strategies": ("_strategy_scorer", "apply_strategies"),
    # SignalManager委托
    "_update_signals": ("_signal_manager", "update_signals"),
    "_push_signals": ("_signal_manager", "_push_signals"),
    "_add_timeline_log": ("_signal_manager", "_add_timeline_log"),
    "_write_audit_log": ("_signal_manager", "_write_audit_log"),
    "_execute_signals": ("_signal_manager", "execute_signals"),
    # PositionChecker委托
    "_check_positions": ("_position_checker", "check_positions"),
    "_check_positions_quick": ("_position_checker", "check_positions_quick"),
    "_get_smart_check_interval": ("_position_checker", "get_smart_check_interval"),
    "_get_open_price": ("_position_checker", "_get_open_price"),
    # PositionManager委托
    "_get_effective_stop_price": ("_position_manager", "get_effective_stop_price"),
    "_update_trailing_stops": ("_position_manager", "update_trailing_stops"),
    "_calc_would_buy_shares": ("_position_manager", "calc_would_buy_shares"),
    "_calc_position_ratio": ("_position_manager", "calc_position_ratio"),
    "_calc_stop_loss_price": ("_position_manager", "calc_stop_loss_price"),
    "_calc_take_profit_price": ("_position_manager", "calc_take_profit_price"),
    # ScannerUtils委托
    "_safe_round": ("_scanner_utils", "safe_round"),
    "_publish_scanner_event": ("_scanner_utils", "publish_scanner_event"),
    "_position_to_dict": ("_scanner_utils", "position_to_dict"),
    "_signal_to_dict": ("_scanner_utils", "signal_to_dict"),
    "_extract_key_factors": ("_scanner_utils", "extract_key_factors"),
    "generate_summary_report": ("_scanner_utils", "generate_summary_report"),
    "_compute_health_score": ("_scanner_utils", "compute_health_score"),
    # StrategyScorer(更多委托)
    "_merge_factors": ("_strategy_scorer", "merge_factors"),
    "_get_effective_strategy_config": ("_strategy_scorer", "get_effective_strategy_config"),
    "_get_strategy_risk": ("_strategy_scorer", "get_strategy_risk"),
    "_detect_anomalies": ("_strategy_scorer", "detect_anomalies"),
    # RiskWatchdog委托
    "_check_circuit_breaker": ("_risk_watchdog_class", "check_circuit_breaker"),
    "_record_trade_result": ("_risk_watchdog_class", "record_trade_result"),
    "reset_circuit_breaker": ("_risk_watchdog_class", "reset_circuit_breaker"),
    # RuntimePersistence(更多委托)
    "_save_performance_snapshot": ("_runtime_persistence", "save_performance_snapshot"),
    "_push_daily_summary": ("_runtime_persistence", "push_daily_summary"),
    # 情绪调仓+诊断
    "diagnose": ("_scanner_utils", "diagnose"),
    "_handle_emotion_phase_change": ("_emotion_cycle_class", "handle_emotion_phase_change"),
    # 子模块方法提取
    "_build_account_info": ("_scanner_utils", "build_account_info"),
    "_build_timeline_entry": ("_runtime_persistence", "build_timeline_entry"),
    "_post_sell_cleanup": ("_runtime_persistence", "post_sell_cleanup"),
    "_retry_pending_sells": ("_position_manager", "retry_pending_sells"),
    "_execute_sell_list_from_risk": ("_position_manager", "execute_sell_list_from_risk"),
    "_merge_filter_result": ("_filter_pipeline", "merge_filter_result"),
    "_format_slow_steps": ("_scanner_utils", "format_slow_steps"),
    "_build_position_dict": ("_scanner_utils", "build_position_dict"),
    # 数据加载+停止持久化(显式定义方法,不通过DELEGATE_MAP路由)
    # _load_stock_list/_load_daily_factors/_load_stock_name_map/_warm_weekend_cache
    # 有self状态赋值逻辑,必须保留显式方法
    # _persist_stop_state/_restore_start_state/_load_positions 是纯存根但保留显式定义
    # _reset_daily_risk_state 有import,保留显式定义
    # 情绪得分+收盘同步
    "_update_sentiment_score": ("_emotion_cycle_class", "update_sentiment_score"),
    "_sync_close_data_to_mongo": ("_runtime_persistence", "sync_close_data_to_mongo"),
    # 卖出执行(显式定义存根,不通过DELEGATE_MAP路由)
    # _execute_risk_sell/_liquidate_positions 保留显式方法定义
    # 参数管理
    "_save_param_snapshot": ("_runtime_persistence", "save_param_snapshot"),
    "_detect_param_drift": ("_strategy_param_center_class", "detect_and_publish_drift"),
    "_validate_live_params": ("_strategy_param_center_class", "validate_live_params"),
    "update_strategy_config": ("_strategy_param_center_class", "apply_scanner_config_update"),
    "_load_strategy_overrides": ("_strategy_param_center_class", "load_and_apply_scanner_overrides"),
    "_persist_strategy_overrides": ("_strategy_param_center_class", "persist_scanner_overrides"),
}
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
    "_build_position_dict": lambda scanner, method: lambda pos, trailing_copy, risk_levels_copy: method(pos, scanner, trailing_copy, risk_levels_copy),  # v2.9.43
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


# 策略路由表: module_attr → 解析函数【v2.9.61:if/elif链→路由表】
# 新增策略只需加一行, 不再需要改resolve_delegate函数体
_DISPATCH_TABLE = {
    "_quote_manager_class": None,  # 延迟绑定(函数尚未定义)
    "_risk_watchdog_class": None,
    "_scanner_utils": None,
    "_emotion_cycle_class": None,
    "_strategy_param_center_class": None,
    "_strategy_scorer": None,
}


def resolve_delegate(scanner, name: str, delegate: tuple) -> Any:
    """解析委托调用 — 策略路由表分派【v2.9.61:if/elif链→路由表】

    Args:
        scanner: MarketScanner实例
        name: 被调用的方法名
        delegate: (module_attr, method_name) 委托映射
    Returns:
        可调用对象或属性
    """
    module_attr, method_name = delegate

    # 先查路由表
    resolver = _DISPATCH_TABLE.get(module_attr)
    if resolver:
        return resolver(scanner, name, module_attr, method_name)

    # 兜底: 普通模块委托
    return _resolve_module_delegate(scanner, name, module_attr, method_name)


# ==================== 路由策略实现 ====================


def _resolve_class_method(scanner, name: str, module_attr: str, method_name: str) -> Any:
    """策略1: QuoteManager类方法(不是实例)"""
    from nodes.market_monitor.quote_manager import QuoteManager
    return getattr(QuoteManager, method_name)


def _resolve_watchdog(scanner, name: str, module_attr: str, method_name: str) -> Any:
    """策略2: RiskWatchdog类静态方法"""
    from nodes.market_monitor.risk_watchdog import RiskWatchdog
    method = getattr(RiskWatchdog, method_name)
    binder = _WATCHDOG_BINDINGS.get(method_name)
    if binder:
        return binder(method, scanner)
    return method


def _resolve_utils(scanner, name: str, module_attr: str, method_name: str) -> Any:
    """策略3: ScannerUtils(部分方法需要scanner上下文绑定)"""
    from nodes.market_monitor.scanner_utils import ScannerUtils
    method = getattr(ScannerUtils, method_name)
    binder = _UTILS_CONTEXT_METHODS.get(name)
    if binder:
        return binder(scanner, method)
    return method


def _resolve_emotion(scanner, name: str, module_attr: str, method_name: str) -> Any:
    """策略3.5: EmotionCycleManager(类静态方法, 绑定scanner上下文)"""
    from nodes.market_monitor.emotion_cycle import EmotionCycleManager
    method = getattr(EmotionCycleManager, method_name)
    binder = _EMOTION_BINDINGS.get(method_name)
    if binder:
        return binder(method, scanner)
    return method


def _resolve_param_center(scanner, name: str, module_attr: str, method_name: str) -> Any:
    """策略3.6: StrategyParamCenter(类静态方法, 绑定scanner上下文)"""
    from nodes.market_monitor.strategy_param_center import StrategyParamCenter
    method = getattr(StrategyParamCenter, method_name)
    binder = _PARAM_CENTER_BINDINGS.get(method_name)
    if binder:
        return binder(method, scanner)
    return method


def _resolve_module_delegate(scanner, name: str, module_attr: str, method_name: str) -> Any:
    """策略5+6: 普通模块委托(含未初始化fallback)"""
    module = getattr(scanner, module_attr, None)
    if module is None:
        return _resolve_noop_fallback(module_attr, name)
    return getattr(module, method_name)


def _resolve_scorer(scanner, name: str, module_attr: str, method_name: str) -> Any:
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
        async def _async_detect_anomalies(realtime_data) -> Any:
            return method(realtime_data, scanner._active_signals, scanner._prev_realtime_cache)
        return _async_detect_anomalies
    return method


def _resolve_noop_fallback(module_attr: str, name: str) -> Any:
    """策略5+6: 模块未初始化时的noop fallback"""
    if name in _ASYNC_DELEGATE_METHODS:
        logger.warning(f"[SCANNER] 委托模块 {module_attr} 未初始化, 异步方法 {name} 返回noop coroutine")
        async def _async_noop(*args, **kwargs) -> None:
            return None
        return _async_noop
    else:
        logger.warning(f"[SCANNER] 委托模块 {module_attr} 未初始化, 同步方法 {name} 返回None")
        return lambda *args, **kwargs: None


# ==================== 延迟绑定路由表 ====================
# 函数定义完成后, 将路由表指向实际函数
_DISPATCH_TABLE["_quote_manager_class"] = _resolve_class_method
_DISPATCH_TABLE["_risk_watchdog_class"] = _resolve_watchdog
_DISPATCH_TABLE["_scanner_utils"] = _resolve_utils
_DISPATCH_TABLE["_emotion_cycle_class"] = _resolve_emotion
_DISPATCH_TABLE["_strategy_param_center_class"] = _resolve_param_center
_DISPATCH_TABLE["_strategy_scorer"] = _resolve_scorer
