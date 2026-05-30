"""
v2.9.18 审查优化测试 — stop()拆分 + QuoteManager封装 + pending_sells安全拷贝

变更项:
1. stop()拆分: _sell_all_positions + _persist_stop_state
2. QuoteManager属性封装: cache_lock_initialized/realtime_cache/prev_realtime_cache/data_router/quote_degrade_level
3. QuoteManager.warm_sources_cache: 缓存预热写入(替代scanner直接访问内部属性)
4. _safe_copy_pending_sells: 线程安全深拷贝
5. _build_emotion_sell_list: 传深拷贝+lock=None,防止回调修改内部状态
"""
import pytest
import os
import sys
import threading
import time

# 确保可以导入项目模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


# ============================================================================
# 1. stop()拆分验证
# ============================================================================

class TestStopMethodExtraction:
    """验证stop()方法拆分为_sell_all_positions + _persist_stop_state"""

    def test_sell_all_positions_method_exists(self):
        """_sell_all_positions方法存在且为async"""
        from nodes.market_monitor.scanner import MarketScanner
        import inspect
        assert hasattr(MarketScanner, '_sell_all_positions')
        assert inspect.iscoroutinefunction(MarketScanner._sell_all_positions)

    def test_persist_stop_state_method_exists(self):
        """_persist_stop_state方法存在且为async"""
        from nodes.market_monitor.scanner import MarketScanner
        import inspect
        assert hasattr(MarketScanner, '_persist_stop_state')
        assert inspect.iscoroutinefunction(MarketScanner._persist_stop_state)

    def test_stop_calls_extracted_methods(self):
        """stop()源码中调用了_sell_all_positions和_persist_stop_state"""
        import inspect
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner.stop)
        assert "_sell_all_positions" in source, "stop()应调用_sell_all_positions"
        assert "_persist_stop_state" in source, "stop()应调用_persist_stop_state"

    def test_stop_line_count_reduced(self):
        """stop()方法行数应显著减少(110→~30行)"""
        import inspect
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner.stop)
        lines = [l for l in source.split('\n') if l.strip() and not l.strip().startswith('#')]
        assert len(lines) < 45, f"stop()方法应<45行有效代码, 实际{len(lines)}行"


# ============================================================================
# 2. QuoteManager属性封装
# ============================================================================

class TestQuoteManagerEncapsulation:
    """验证QuoteManager封装属性替代直接访问内部属性"""

    def test_cache_lock_initialized_property(self):
        """cache_lock_initialized属性存在"""
        from nodes.market_monitor.quote_manager import QuoteManager
        qm = QuoteManager()
        assert hasattr(qm, 'cache_lock_initialized')
        assert qm.cache_lock_initialized is False
        qm.set_cache_lock(threading.Lock())
        assert qm.cache_lock_initialized is True

    def test_realtime_cache_property(self):
        """realtime_cache属性暴露"""
        from nodes.market_monitor.quote_manager import QuoteManager
        qm = QuoteManager()
        assert hasattr(qm, 'realtime_cache')
        assert isinstance(qm.realtime_cache, dict)

    def test_prev_realtime_cache_property(self):
        """prev_realtime_cache属性暴露"""
        from nodes.market_monitor.quote_manager import QuoteManager
        qm = QuoteManager()
        assert hasattr(qm, 'prev_realtime_cache')
        assert isinstance(qm.prev_realtime_cache, dict)

    def test_data_router_property(self):
        """data_router属性暴露"""
        from nodes.market_monitor.quote_manager import QuoteManager
        qm = QuoteManager()
        assert hasattr(qm, 'data_router')
        assert qm.data_router is None  # 未初始化时为None

    def test_quote_degrade_level_property(self):
        """quote_degrade_level属性暴露"""
        from nodes.market_monitor.quote_manager import QuoteManager
        qm = QuoteManager()
        assert hasattr(qm, 'quote_degrade_level')
        assert qm.quote_degrade_level == 0

    def test_scanner_no_private_access(self):
        """scanner.py不再直接访问_quote_manager._cache_lock等私有属性"""
        scanner_path = os.path.join(
            os.path.dirname(__file__), '..', '..', 'nodes', 'market_monitor', 'scanner.py'
        )
        if not os.path.exists(scanner_path):
            pytest.skip("scanner.py not found")
        with open(scanner_path) as f:
            source = f.read()
        # scanner不应直接访问_quote_manager的私有属性
        bad_patterns = [
            '_quote_manager._cache_lock',
            '_quote_manager._realtime_cache',
            '_quote_manager._prev_realtime_cache',
            '_quote_manager._data_router',
            '_quote_manager._quote_degrade_level',
        ]
        for pattern in bad_patterns:
            assert pattern not in source, f"scanner.py不应直接访问{pattern}, 应使用封装属性"


# ============================================================================
# 3. warm_sources_cache方法
# ============================================================================

class TestWarmSourcesCache:
    """验证QuoteManager.warm_sources_cache封装缓存写入"""

    def test_warm_sources_cache_method_exists(self):
        """warm_sources_cache方法存在"""
        from nodes.market_monitor.quote_manager import QuoteManager
        assert hasattr(QuoteManager, 'warm_sources_cache')

    def test_warm_sources_cache_no_data_router(self):
        """无data_router时不报错"""
        from nodes.market_monitor.quote_manager import QuoteManager
        qm = QuoteManager()
        qm.warm_sources_cache({"600036.SH": {"price": 40.0, "pct_chg": 2.0,
            "pre_close": 39.2, "open": 39.5, "high": 40.5, "low": 39.0,
            "vol": 1000, "amount": 40000, "name": "招商银行"}})
        # 不报错即通过

    def test_scanner_uses_warm_sources_cache(self):
        """scanner.py中使用warm_sources_cache替代直接访问"""
        scanner_path = os.path.join(
            os.path.dirname(__file__), '..', '..', 'nodes', 'market_monitor', 'scanner.py'
        )
        if not os.path.exists(scanner_path):
            pytest.skip("scanner.py not found")
        with open(scanner_path) as f:
            source = f.read()
        assert "warm_sources_cache" in source, "scanner应使用warm_sources_cache"
        assert "_data_router._sources" not in source, "scanner不应直接访问_data_router._sources"


# ============================================================================
# 4. _safe_copy_pending_sells
# ============================================================================

class TestSafeCopyPendingSells:
    """验证_safe_copy_pending_sells线程安全深拷贝"""

    def test_safe_copy_pending_sells_exists(self):
        """方法存在"""
        from nodes.market_monitor.scanner import MarketScanner
        assert hasattr(MarketScanner, '_safe_copy_pending_sells')

    def test_safe_copy_returns_independent_copy(self):
        """深拷贝不影响原始数据"""
        from nodes.market_monitor.scanner import MarketScanner
        scanner = MarketScanner.__new__(MarketScanner)
        scanner._pending_sells = {"600036.SH": {"reason": "跌停挂起"}}
        scanner._state_lock = threading.Lock()
        copy = scanner._safe_copy_pending_sells()
        copy["000001.SZ"] = {"reason": "新加入"}
        assert "000001.SZ" not in scanner._pending_sells

    def test_safe_copy_concurrent_access(self):
        """多线程并发安全读取"""
        from nodes.market_monitor.scanner import MarketScanner
        scanner = MarketScanner.__new__(MarketScanner)
        scanner._pending_sells = {}
        scanner._state_lock = threading.Lock()
        errors = []

        def writer():
            for i in range(100):
                with scanner._state_lock:
                    scanner._pending_sells[f"60{i:04d}.SH"] = {"reason": "test"}

        def reader():
            for _ in range(100):
                try:
                    scanner._safe_copy_pending_sells()
                except Exception as e:
                    errors.append(e)

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=reader)
        t1.start(); t2.start()
        t1.join(); t2.join()
        assert not errors, f"并发读取错误: {errors}"

    def test_safe_copy_no_lock(self):
        """无锁时仍返回拷贝"""
        from nodes.market_monitor.scanner import MarketScanner
        scanner = MarketScanner.__new__(MarketScanner)
        scanner._pending_sells = {"600036.SH": {"reason": "test"}}
        scanner._state_lock = None
        copy = scanner._safe_copy_pending_sells()
        assert copy == {"600036.SH": {"reason": "test"}}


# ============================================================================
# 5. _build_emotion_sell_list安全性
# ============================================================================

class TestEmotionSellListSafety:
    """验证_build_emotion_sell_list传深拷贝+不传锁"""

    def test_emotion_sell_list_source_uses_safe_copy(self):
        """scanner源码中_build_emotion_sell_list使用_safe_copy_pending_sells"""
        scanner_path = os.path.join(
            os.path.dirname(__file__), '..', '..', 'nodes', 'market_monitor', 'scanner.py'
        )
        if not os.path.exists(scanner_path):
            pytest.skip("scanner.py not found")
        with open(scanner_path) as f:
            source = f.read()
        # 找_build_emotion_sell_list方法
        assert "_safe_copy_pending_sells" in source, "应使用_safe_copy_pending_sells"
        # 确认state_lock=None传入(已深拷贝,不需要外部锁)
        assert "state_lock=None" in source or "state_lock = None" in source, \
            "已深拷贝后应传state_lock=None"


# ============================================================================
# 6. 回测零影响
# ============================================================================

class TestNoBacktestRegressionV2918:
    """验证v2.9.18改动不影响回测模块"""

    def test_sell_signal_checker_importable(self):
        """回测卖出检查器可导入"""
        from nodes.backtest_engine.factor_selection.sell_signal_checker import SellSignalChecker
        assert SellSignalChecker is not None

    def test_portfolio_backtester_importable(self):
        """回测引擎可导入"""
        from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
        assert PortfolioBacktester is not None

    def test_strategy_defaults_importable(self):
        """策略默认参数可导入"""
        from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS
        assert isinstance(STRATEGY_CONFIGS, dict)

    def test_quote_manager_not_in_backtest(self):
        """QuoteManager不在回测引擎中"""
        from nodes.backtest_engine import factor_selection
        import inspect
        source = inspect.getsource(factor_selection)
        assert "QuoteManager" not in source

    def test_scanner_line_count(self):
        """scanner.py行数应≤1930(v2.9.19:提取_post_sell_cleanup+_scan_loop_replay等)"""
        scanner_path = os.path.join(
            os.path.dirname(__file__), '..', '..', 'nodes', 'market_monitor', 'scanner.py'
        )
        if not os.path.exists(scanner_path):
            pytest.skip("scanner.py not found")
        with open(scanner_path) as f:
            line_count = sum(1 for _ in f)
        # v2.9.19: 提取4个方法增加签名,但scan_once/_execute_risk_sell/get_status大幅简化
        assert line_count <= 1970, f"scanner.py行数{line_count}>1970 (v2.9.22:分步计时+错误恢复)"


# ============================================================================
# 7. start()拆分验证
# ============================================================================

class TestStartMethodExtraction:
    """验证start()方法拆分为_detect_param_drift + _restore_start_state + _start_risk_thread"""

    def test_detect_param_drift_method_exists(self):
        """_detect_param_drift方法存在且为async"""
        from nodes.market_monitor.scanner import MarketScanner
        import inspect
        assert hasattr(MarketScanner, '_detect_param_drift')
        assert inspect.iscoroutinefunction(MarketScanner._detect_param_drift)

    def test_restore_start_state_method_exists(self):
        """_restore_start_state方法存在且为async"""
        from nodes.market_monitor.scanner import MarketScanner
        import inspect
        assert hasattr(MarketScanner, '_restore_start_state')
        assert inspect.iscoroutinefunction(MarketScanner._restore_start_state)

    def test_start_risk_thread_method_exists(self):
        """_start_risk_thread方法存在且为同步方法"""
        from nodes.market_monitor.scanner import MarketScanner
        import inspect
        assert hasattr(MarketScanner, '_start_risk_thread')
        assert not inspect.iscoroutinefunction(MarketScanner._start_risk_thread)

    def test_start_calls_extracted_methods(self):
        """start()源码中调用了3个提取方法"""
        import inspect
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner.start)
        assert "_detect_param_drift" in source
        assert "_restore_start_state" in source
        assert "_start_risk_thread" in source

    def test_start_line_count(self):
        """start()方法行数应<40行有效代码"""
        import inspect
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner.start)
        lines = [l for l in source.split('\n') if l.strip() and not l.strip().startswith('#')]
        assert len(lines) < 40, f"start()方法应<40行有效代码, 实际{len(lines)}行"


# ============================================================================
# 8. PositionChecker公开接口
# ============================================================================

class TestPositionCheckerPublicInterface:
    """验证PositionChecker公开接口替代私有方法调用"""

    def test_is_limit_down_public_exists(self):
        """is_limit_down公开方法存在"""
        from nodes.market_monitor.position_checker import PositionChecker
        assert hasattr(PositionChecker, 'is_limit_down')

    def test_execute_sell_list_public_exists(self):
        """execute_sell_list公开方法存在且为async"""
        from nodes.market_monitor.position_checker import PositionChecker
        import inspect
        assert hasattr(PositionChecker, 'execute_sell_list')
        assert inspect.iscoroutinefunction(PositionChecker.execute_sell_list)

    def test_is_limit_down_delegates_to_private(self):
        """is_limit_down公开方法委托给_is_limit_down"""
        from nodes.market_monitor.position_checker import PositionChecker
        import inspect
        source = inspect.getsource(PositionChecker.is_limit_down)
        assert "_is_limit_down" in source

    def test_scanner_uses_public_interface(self):
        """scanner.py不再直接调用_position_checker._is_limit_down/_execute_sell_list"""
        scanner_path = os.path.join(
            os.path.dirname(__file__), '..', '..', 'nodes', 'market_monitor', 'scanner.py'
        )
        if not os.path.exists(scanner_path):
            pytest.skip("scanner.py not found")
        with open(scanner_path) as f:
            source = f.read()
        assert "_position_checker._is_limit_down" not in source, \
            "scanner应使用_position_checker.is_limit_down而非私有方法"
        assert "_position_checker._execute_sell_list" not in source, \
            "scanner应使用_position_checker.execute_sell_list而非私有方法"

    def test_is_limit_down_returns_bool(self):
        """is_limit_down返回bool"""
        from nodes.market_monitor.position_checker import PositionChecker
        pc = PositionChecker.__new__(PositionChecker)
        pc._scanner = None
        # Mock realtime_cache
        pc._realtime_cache_prop = {}
        type(pc).realtime_cache = property(lambda self: self._realtime_cache_prop)
        result = pc.is_limit_down("600036.SH")
        assert isinstance(result, bool)
