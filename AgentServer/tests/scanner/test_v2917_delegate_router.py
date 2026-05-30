"""v2.9.17 委托路由器 + state_lock统一 + 参数漂移告警 测试

覆盖:
1. DelegateRouter: 6种路由策略解析
2. RiskWatchdog._with_state_lock: 统一加锁辅助
3. scanner.py的__getattr__简化后行为一致
4. 回测零影响
"""

import pytest
import asyncio
import threading
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime


# ==================== DelegateRouter测试 ====================

class TestDelegateRouterBasic:
    """委托路由器基础功能"""

    def test_resolve_delegate_import(self):
        """DelegateRouter可正常导入"""
        from nodes.market_monitor.scanner_delegate_router import resolve_delegate
        assert callable(resolve_delegate)

    def test_async_delegate_methods_frozenset(self):
        """_ASYNC_DELEGATE_METHODS是frozenset(不可变)"""
        from nodes.market_monitor.scanner_delegate_router import _ASYNC_DELEGATE_METHODS
        assert isinstance(_ASYNC_DELEGATE_METHODS, frozenset)
        # 关键async方法必须包含
        assert "_save_timeline" in _ASYNC_DELEGATE_METHODS
        assert "_check_positions" in _ASYNC_DELEGATE_METHODS
        assert "_publish_scanner_event" in _ASYNC_DELEGATE_METHODS
        assert "_check_circuit_breaker" in _ASYNC_DELEGATE_METHODS

    def test_scorer_fallbacks_coverage(self):
        """_SCORER_FALLBACKS覆盖4个关键方法"""
        from nodes.market_monitor.scanner_delegate_router import _SCORER_FALLBACKS
        assert "_merge_factors" in _SCORER_FALLBACKS
        assert "_get_effective_strategy_config" in _SCORER_FALLBACKS
        assert "_get_strategy_risk" in _SCORER_FALLBACKS
        assert "_detect_anomalies" in _SCORER_FALLBACKS

    def test_utils_context_methods(self):
        """_UTILS_CONTEXT_METHODS覆盖4个方法"""
        from nodes.market_monitor.scanner_delegate_router import _UTILS_CONTEXT_METHODS
        assert "_position_to_dict" in _UTILS_CONTEXT_METHODS
        assert "_signal_to_dict" in _UTILS_CONTEXT_METHODS
        assert "generate_summary_report" in _UTILS_CONTEXT_METHODS
        assert "_compute_health_score" in _UTILS_CONTEXT_METHODS

    def test_watchdog_bindings(self):
        """_WATCHDOG_BINDINGS覆盖3个方法"""
        from nodes.market_monitor.scanner_delegate_router import _WATCHDOG_BINDINGS
        assert "check_circuit_breaker" in _WATCHDOG_BINDINGS
        assert "record_trade_result" in _WATCHDOG_BINDINGS
        assert "reset_circuit_breaker" in _WATCHDOG_BINDINGS


class TestDelegateRouterQuoteManager:
    """策略1: QuoteManager类方法"""

    def test_resolve_quote_manager_class(self):
        """_quote_manager_class路由到QuoteManager类"""
        from nodes.market_monitor.scanner_delegate_router import resolve_delegate
        scanner = MagicMock()
        result = resolve_delegate(scanner, "_short_to_ts_code", ("_quote_manager_class", "short_to_ts_code"))
        # 应该返回QuoteManager.short_to_ts_code类方法
        from nodes.market_monitor.quote_manager import QuoteManager
        assert result is QuoteManager.short_to_ts_code


class TestDelegateRouterRiskWatchdog:
    """策略2: RiskWatchdog类静态方法"""

    def test_resolve_check_circuit_breaker(self):
        """check_circuit_breaker绑定scanner实例"""
        from nodes.market_monitor.scanner_delegate_router import resolve_delegate
        scanner = MagicMock()
        result = resolve_delegate(scanner, "_check_circuit_breaker", ("_risk_watchdog_class", "check_circuit_breaker"))
        assert callable(result)

    def test_resolve_record_trade_result(self):
        """record_trade_result绑定scanner实例"""
        from nodes.market_monitor.scanner_delegate_router import resolve_delegate
        scanner = MagicMock()
        result = resolve_delegate(scanner, "record_trade_result", ("_risk_watchdog_class", "record_trade_result"))
        assert callable(result)

    def test_resolve_reset_circuit_breaker(self):
        """reset_circuit_breaker绑定scanner实例"""
        from nodes.market_monitor.scanner_delegate_router import resolve_delegate
        scanner = MagicMock()
        result = resolve_delegate(scanner, "reset_circuit_breaker", ("_risk_watchdog_class", "reset_circuit_breaker"))
        assert callable(result)


class TestDelegateRouterScannerUtils:
    """策略3: ScannerUtils"""

    def test_resolve_position_to_dict(self):
        """_position_to_dict绑定risk_getter"""
        from nodes.market_monitor.scanner_delegate_router import resolve_delegate
        scanner = MagicMock()
        scanner._get_strategy_risk = lambda x: {"stop_loss_pct": 0.03}
        result = resolve_delegate(scanner, "_position_to_dict", ("_scanner_utils", "position_to_dict"))
        assert callable(result)

    def test_resolve_signal_to_dict(self):
        """_signal_to_dict绑定SIGNAL_EXPIRE_SECONDS"""
        from nodes.market_monitor.scanner_delegate_router import resolve_delegate
        scanner = MagicMock()
        scanner.SIGNAL_EXPIRE_SECONDS = 300
        result = resolve_delegate(scanner, "_signal_to_dict", ("_scanner_utils", "signal_to_dict"))
        assert callable(result)


class TestDelegateRouterStrategyScorer:
    """策略4: StrategyScorer"""

    def test_resolve_scorer_with_module(self):
        """有_strategy_scorer实例时正常路由"""
        from nodes.market_monitor.scanner_delegate_router import resolve_delegate
        scanner = MagicMock()
        mock_scorer = MagicMock()
        mock_scorer.merge_factors = MagicMock(return_value="factors_result")
        scanner._strategy_scorer = mock_scorer
        result = resolve_delegate(scanner, "_merge_factors", ("_strategy_scorer", "merge_factors"))
        assert callable(result)

    def test_resolve_scorer_fallback_merge_factors(self):
        """无_strategy_scorer时_merge_factors返回空DataFrame"""
        from nodes.market_monitor.scanner_delegate_router import resolve_delegate
        import pandas as pd
        scanner = MagicMock(spec=[])  # 无_strategy_scorer属性
        result = resolve_delegate(scanner, "_merge_factors", ("_strategy_scorer", "merge_factors"))
        df = result()
        assert isinstance(df, pd.DataFrame)
        assert df.empty

    def test_resolve_scorer_fallback_strategy_risk(self):
        """无_strategy_scorer时_get_strategy_risk返回默认风控参数"""
        from nodes.market_monitor.scanner_delegate_router import resolve_delegate
        scanner = MagicMock(spec=[])
        result = resolve_delegate(scanner, "_get_strategy_risk", ("_strategy_scorer", "get_strategy_risk"))
        risk = result()
        assert risk["stop_loss_pct"] == 0.03
        assert risk["take_profit_pct"] == 0.07

    def test_resolve_detect_anomalies_with_context(self):
        """_detect_anomalies绑定scanner上下文"""
        from nodes.market_monitor.scanner_delegate_router import resolve_delegate
        scanner = MagicMock()
        scanner._active_signals = []
        scanner._prev_realtime_cache = {}
        mock_scorer = MagicMock()
        mock_scorer.detect_anomalies = MagicMock(return_value=[])
        scanner._strategy_scorer = mock_scorer
        result = resolve_delegate(scanner, "_detect_anomalies", ("_strategy_scorer", "detect_anomalies"))
        # 应该返回异步函数
        assert asyncio.iscoroutinefunction(result)


class TestDelegateRouterNoopFallback:
    """策略5+6: 模块未初始化时的noop"""

    def test_async_noop(self):
        """async委托方法返回noop coroutine"""
        from nodes.market_monitor.scanner_delegate_router import resolve_delegate
        scanner = MagicMock(spec=[])  # 无任何模块属性
        result = resolve_delegate(scanner, "_save_timeline", ("_runtime_persistence", "save_timeline"))
        assert asyncio.iscoroutinefunction(result)
        # 可以await
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(result())
        finally:
            loop.close()

    def test_sync_noop(self):
        """sync委托方法返回lambda None"""
        from nodes.market_monitor.scanner_delegate_router import resolve_delegate
        scanner = MagicMock(spec=[])
        result = resolve_delegate(scanner, "_get_effective_stop_price", ("_position_manager", "get_effective_stop_price"))
        assert callable(result)
        assert result() is None


class TestDelegateRouterAttributeError:
    """不在DELEGATE_MAP中的属性"""

    def test_unknown_attribute_returns_none_delegate(self):
        """delegate=None时resolve_delegate不解包(由scanner.__getattr__处理AttributeError)"""
        from nodes.market_monitor.scanner_delegate_router import resolve_delegate
        scanner = MagicMock()
        # resolve_delegate收到None委托时无法解包(这是预期行为)
        # scanner.__getattr__中已经检查delegate is None并抛AttributeError
        with pytest.raises(TypeError):
            resolve_delegate(scanner, "nonexistent_method", None)


# ==================== _with_state_lock测试 ====================

class TestWithStateLock:
    """RiskWatchdog._with_state_lock统一加锁辅助"""

    def test_with_state_lock_exists(self):
        """_with_state_lock方法存在"""
        from nodes.market_monitor.risk_watchdog import RiskWatchdog
        assert hasattr(RiskWatchdog, '_with_state_lock')

    def test_with_state_lock_calls_fn_under_lock(self):
        """有state_lock时fn在锁内执行"""
        from nodes.market_monitor.risk_watchdog import RiskWatchdog
        lock = threading.Lock()
        scanner = MagicMock()
        scanner._state_lock = lock
        called = []
        RiskWatchdog._with_state_lock(scanner, lambda: called.append(True))
        assert called == [True]

    def test_with_state_lock_no_lock(self):
        """无state_lock时直接执行fn"""
        from nodes.market_monitor.risk_watchdog import RiskWatchdog
        scanner = MagicMock(spec=['_circuit_breaker'])  # 无_state_lock
        called = []
        RiskWatchdog._with_state_lock(scanner, lambda: called.append(True))
        assert called == [True]

    def test_with_state_lock_returns_value(self):
        """_with_state_lock返回fn()的返回值"""
        from nodes.market_monitor.risk_watchdog import RiskWatchdog
        lock = threading.Lock()
        scanner = MagicMock()
        scanner._state_lock = lock
        result = RiskWatchdog._with_state_lock(scanner, lambda: 42)
        assert result == 42

    def test_with_state_lock_fallback(self):
        """fallback参数: 无lock时使用fallback"""
        from nodes.market_monitor.risk_watchdog import RiskWatchdog
        scanner = MagicMock(spec=['_circuit_breaker'])
        result = RiskWatchdog._with_state_lock(
            scanner, lambda: "primary", fallback=lambda: "fallback"
        )
        assert result == "fallback"

    def test_with_state_lock_fallback_not_used_with_lock(self):
        """有lock时不使用fallback"""
        from nodes.market_monitor.risk_watchdog import RiskWatchdog
        lock = threading.Lock()
        scanner = MagicMock()
        scanner._state_lock = lock
        result = RiskWatchdog._with_state_lock(
            scanner, lambda: "primary", fallback=lambda: "fallback"
        )
        assert result == "primary"


# ==================== RiskWatchdog方法简化验证 ====================

class TestRiskWatchdogSimplification:
    """v2.9.17: RiskWatchdog方法使用_with_state_lock"""

    def test_check_circuit_breaker_uses_helper(self):
        """check_circuit_breaker使用_with_state_lock"""
        import inspect
        from nodes.market_monitor.risk_watchdog import RiskWatchdog
        src = inspect.getsource(RiskWatchdog.check_circuit_breaker)
        assert '_with_state_lock' in src, "check_circuit_breaker应使用_with_state_lock"
        # 不再有 if state_lock: with state_lock: else: 重复模式
        assert 'if state_lock:' not in src, "check_circuit_breaker不应有if state_lock:重复模式"

    def test_record_trade_result_uses_helper(self):
        """record_trade_result使用_with_state_lock"""
        import inspect
        from nodes.market_monitor.risk_watchdog import RiskWatchdog
        src = inspect.getsource(RiskWatchdog.record_trade_result)
        assert '_with_state_lock' in src
        assert 'if state_lock:' not in src

    def test_reset_circuit_breaker_uses_helper(self):
        """reset_circuit_breaker使用_with_state_lock"""
        import inspect
        from nodes.market_monitor.risk_watchdog import RiskWatchdog
        src = inspect.getsource(RiskWatchdog.reset_circuit_breaker)
        assert '_with_state_lock' in src
        assert 'if state_lock:' not in src


# ==================== scanner.py简化验证 ====================

class TestScannerGetattrSimplification:
    """v2.9.17: scanner.py的__getattr__简化"""

    def test_getattr_is_short(self):
        """__getattr__方法行数≤15行(原95行)"""
        import inspect
        from nodes.market_monitor.scanner import MarketScanner
        src = inspect.getsource(MarketScanner.__getattr__)
        lines = [l for l in src.split('\n') if l.strip() and not l.strip().startswith('#')]
        assert len(lines) <= 15, f"__getattr__应≤15行有效代码, 实际{len(lines)}行"

    def test_getattr_uses_delegate_router(self):
        """__getattr__使用resolve_delegate"""
        import inspect
        from nodes.market_monitor.scanner import MarketScanner
        src = inspect.getsource(MarketScanner.__getattr__)
        assert 'resolve_delegate' in src

    def test_scanner_uses_with_state_lock(self):
        """scanner.py通过RiskWatchdog委托使用_with_state_lock【v2.9.32:已提取到RiskWatchdog.reset_daily_risk_state】"""
        import inspect
        from nodes.market_monitor.risk_watchdog import RiskWatchdog
        src = inspect.getsource(RiskWatchdog.reset_daily_risk_state)
        assert '_with_state_lock' in src


# ==================== 回测零影响验证 ====================

class TestNoBacktestRegressionV2917:
    """v2.9.17: 回测零影响"""

    def test_backtest_engine_importable(self):
        """回测引擎正常导入"""
        from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
        assert PortfolioBacktester is not None

    def test_sell_signal_checker_api_unchanged(self):
        """SellSignalChecker API未变"""
        from nodes.backtest_engine.factor_selection.sell_signal_checker import SellSignalChecker
        # SellSignalChecker需要参数,检查类有check_realtime_sell方法
        assert hasattr(SellSignalChecker, 'check_realtime_sell')
        # 检查签名包含trailing_stop_state参数
        import inspect
        sig = inspect.signature(SellSignalChecker.check_realtime_sell)
        assert 'trailing_stop_state' in sig.parameters

    def test_strategy_defaults_importable(self):
        """strategy_defaults正常导入"""
        from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS
        assert isinstance(STRATEGY_CONFIGS, dict)
        assert len(STRATEGY_CONFIGS) > 0

    def test_delegate_router_not_imported_by_backtest(self):
        """delegate_router不被回测模块引用"""
        import inspect
        from nodes.backtest_engine.factor_selection import sell_signal_checker
        src = inspect.getsource(sell_signal_checker)
        assert 'delegate_router' not in src

    def test_risk_watchdog_not_imported_by_backtest(self):
        """risk_watchdog不被回测模块引用"""
        import inspect
        from nodes.backtest_engine.factor_selection import sell_signal_checker
        src = inspect.getsource(sell_signal_checker)
        assert 'risk_watchdog' not in src
