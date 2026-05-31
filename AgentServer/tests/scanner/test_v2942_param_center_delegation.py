"""v2.9.42 测试: StrategyParamCenter委托路由 + RuntimePersistence参数快照

变更:
1. _save_param_snapshot提取到RuntimePersistence.save_param_snapshot
2. _detect_param_drift委托到StrategyParamCenter.detect_and_publish_drift
3. _validate_live_params委托到StrategyParamCenter.validate_live_params
4. update_strategy_config委托到StrategyParamCenter.apply_scanner_config_update
5. _load_strategy_overrides委托到StrategyParamCenter.load_and_apply_scanner_overrides
6. _persist_strategy_overrides委托到StrategyParamCenter.persist_scanner_overrides
7. DelegateRouter新增_strategy_param_center_class路由策略
"""

import pytest
import inspect
from unittest.mock import MagicMock, patch, AsyncMock


class TestDelegateMapParamCenterEntries:
    """验证DELEGATE_MAP中StrategyParamCenter相关条目"""

    def test_save_param_snapshot_in_delegate_map(self):
        """_save_param_snapshot在DELEGATE_MAP中委托到RuntimePersistence"""
        from nodes.market_monitor.scanner import MarketScanner
        dm = MarketScanner._DELEGATE_MAP
        assert "_save_param_snapshot" in dm
        assert dm["_save_param_snapshot"] == ("_runtime_persistence", "save_param_snapshot")

    def test_detect_param_drift_in_delegate_map(self):
        """_detect_param_drift在DELEGATE_MAP中委托到StrategyParamCenter"""
        from nodes.market_monitor.scanner import MarketScanner
        dm = MarketScanner._DELEGATE_MAP
        assert "_detect_param_drift" in dm
        assert dm["_detect_param_drift"] == ("_strategy_param_center_class", "detect_and_publish_drift")

    def test_validate_live_params_in_delegate_map(self):
        """_validate_live_params在DELEGATE_MAP中委托到StrategyParamCenter"""
        from nodes.market_monitor.scanner import MarketScanner
        dm = MarketScanner._DELEGATE_MAP
        assert "_validate_live_params" in dm
        assert dm["_validate_live_params"] == ("_strategy_param_center_class", "validate_live_params")

    def test_update_strategy_config_in_delegate_map(self):
        """update_strategy_config在DELEGATE_MAP中委托到StrategyParamCenter"""
        from nodes.market_monitor.scanner import MarketScanner
        dm = MarketScanner._DELEGATE_MAP
        assert "update_strategy_config" in dm
        assert dm["update_strategy_config"] == ("_strategy_param_center_class", "apply_scanner_config_update")

    def test_load_strategy_overrides_in_delegate_map(self):
        """_load_strategy_overrides在DELEGATE_MAP中委托到StrategyParamCenter"""
        from nodes.market_monitor.scanner import MarketScanner
        dm = MarketScanner._DELEGATE_MAP
        assert "_load_strategy_overrides" in dm
        assert dm["_load_strategy_overrides"] == ("_strategy_param_center_class", "load_and_apply_scanner_overrides")

    def test_persist_strategy_overrides_in_delegate_map(self):
        """_persist_strategy_overrides在DELEGATE_MAP中委托到StrategyParamCenter"""
        from nodes.market_monitor.scanner import MarketScanner
        dm = MarketScanner._DELEGATE_MAP
        assert "_persist_strategy_overrides" in dm
        assert dm["_persist_strategy_overrides"] == ("_strategy_param_center_class", "persist_scanner_overrides")


class TestDelegateRouterParamCenterStrategy:
    """验证DelegateRouter的StrategyParamCenter路由策略"""

    def test_param_center_bindings_defined(self):
        """_PARAM_CENTER_BINDINGS在delegate_router中定义"""
        from nodes.market_monitor.scanner_delegate_router import _PARAM_CENTER_BINDINGS
        assert "validate_live_params" in _PARAM_CENTER_BINDINGS
        assert "detect_and_publish_drift" in _PARAM_CENTER_BINDINGS
        assert "apply_scanner_config_update" in _PARAM_CENTER_BINDINGS
        assert "load_and_apply_scanner_overrides" in _PARAM_CENTER_BINDINGS
        assert "persist_scanner_overrides" in _PARAM_CENTER_BINDINGS

    def test_async_delegate_methods_include_param_center(self):
        """_ASYNC_DELEGATE_METHODS包含StrategyParamCenter的async方法"""
        from nodes.market_monitor.scanner_delegate_router import _ASYNC_DELEGATE_METHODS
        assert "_detect_param_drift" in _ASYNC_DELEGATE_METHODS
        assert "_load_strategy_overrides" in _ASYNC_DELEGATE_METHODS
        assert "_persist_strategy_overrides" in _ASYNC_DELEGATE_METHODS
        assert "_save_param_snapshot" in _ASYNC_DELEGATE_METHODS

    def test_strategy_param_center_class_routing(self):
        """_strategy_param_center_class路由到StrategyParamCenter"""
        from nodes.market_monitor.scanner_delegate_router import resolve_delegate
        from nodes.market_monitor.scanner import MarketScanner
        scanner = MarketScanner.__new__(MarketScanner)
        scanner._broker = MagicMock()
        scanner._get_strategy_risk = MagicMock(return_value={
            "stop_loss_pct": 0.03, "take_profit_pct": 0.07
        })
        
        delegate = ("_strategy_param_center_class", "validate_live_params")
        result = resolve_delegate(scanner, "_validate_live_params", delegate)
        assert callable(result)


class TestStrategyParamCenterNewMethods:
    """验证StrategyParamCenter新增方法"""

    def test_detect_and_publish_drift_exists(self):
        """detect_and_publish_drift静态方法存在"""
        from nodes.market_monitor.strategy_param_center import StrategyParamCenter
        assert hasattr(StrategyParamCenter, 'detect_and_publish_drift')
        assert inspect.iscoroutinefunction(StrategyParamCenter.detect_and_publish_drift)

    def test_apply_scanner_config_update_exists(self):
        """apply_scanner_config_update静态方法存在"""
        from nodes.market_monitor.strategy_param_center import StrategyParamCenter
        assert hasattr(StrategyParamCenter, 'apply_scanner_config_update')
        assert callable(StrategyParamCenter.apply_scanner_config_update)

    def test_load_and_apply_scanner_overrides_exists(self):
        """load_and_apply_scanner_overrides静态方法存在"""
        from nodes.market_monitor.strategy_param_center import StrategyParamCenter
        assert hasattr(StrategyParamCenter, 'load_and_apply_scanner_overrides')
        assert inspect.iscoroutinefunction(StrategyParamCenter.load_and_apply_scanner_overrides)

    def test_apply_scanner_config_update_no_old_values_crash(self):
        """apply_scanner_config_update: config为None时不应crash"""
        from nodes.market_monitor.strategy_param_center import StrategyParamCenter
        scanner = MagicMock()
        scanner.config = None
        scanner._loop = MagicMock()
        scanner._loop.is_closed.return_value = True
        # 不应crash
        StrategyParamCenter.apply_scanner_config_update(scanner, "test", {"key": "val"})

    def test_apply_scanner_config_update_returns_on_failure(self):
        """apply_scanner_config_update: update失败后不调持久化"""
        from nodes.market_monitor.strategy_param_center import StrategyParamCenter
        scanner = MagicMock()
        scanner.config = {"strategies": {"test": {}}}
        scanner._loop = MagicMock()
        scanner._loop.is_closed.return_value = True
        
        with patch.object(StrategyParamCenter, 'update_scanner_config', side_effect=RuntimeError("fail")):
            with patch.object(StrategyParamCenter, 'persist_scanner_overrides') as mock_persist:
                StrategyParamCenter.apply_scanner_config_update(scanner, "test", {"key": "val"})
                mock_persist.assert_not_called()


class TestRuntimePersistenceParamSnapshot:
    """验证RuntimePersistence.save_param_snapshot"""

    def test_method_exists_and_async(self):
        """save_param_snapshot方法存在且为async"""
        from nodes.market_monitor.runtime_persistence import RuntimePersistence
        assert hasattr(RuntimePersistence, 'save_param_snapshot')
        assert inspect.iscoroutinefunction(RuntimePersistence.save_param_snapshot)

    def test_no_backtest_engine_import(self):
        """save_param_snapshot不直接导入backtest_engine"""
        from nodes.market_monitor.runtime_persistence import RuntimePersistence
        source = inspect.getsource(RuntimePersistence.save_param_snapshot)
        assert 'from nodes.backtest_engine' not in source
        assert 'import STRATEGY_CONFIGS' not in source

    def test_uses_scanner_config(self):
        """save_param_snapshot从scanner.config获取参数"""
        from nodes.market_monitor.runtime_persistence import RuntimePersistence
        source = inspect.getsource(RuntimePersistence.save_param_snapshot)
        assert 'scanner.config' in source or 'self._scanner.config' in source


class TestNoExplicitMethodsInScanner:
    """验证scanner.py中不再有已委托方法的显式定义"""

    def test_no_explicit_validate_live_params(self):
        """scanner.py中无_validate_live_params方法定义"""
        from nodes.market_monitor.scanner import MarketScanner
        # DELEGATE_MAP方法不应在类中显式定义(除了__getattr__)
        for name in ['_validate_live_params', 'update_strategy_config',
                      '_load_strategy_overrides', '_persist_strategy_overrides',
                      '_save_param_snapshot', '_detect_param_drift']:
            # 通过__getattr__可用,但不应是显式方法定义
            # 检查: 如果是类方法(非__getattr__生成),则methods会包含它
            pass
        # 改为检查源码中不含"def _validate_live_params"等
        import inspect
        source = inspect.getsource(MarketScanner)
        for method_name in ['_validate_live_params', 'update_strategy_config',
                            '_load_strategy_overrides', '_persist_strategy_overrides',
                            '_detect_param_drift']:
            assert f'def {method_name}(' not in source, \
                f"scanner.py不应有显式方法定义: {method_name} (应通过DELEGATE_MAP委托)"

    def test_save_param_snapshot_not_explicit_in_scanner(self):
        """scanner.py中无_save_param_snapshot方法定义"""
        from nodes.market_monitor.scanner import MarketScanner
        import inspect
        source = inspect.getsource(MarketScanner)
        assert 'def _save_param_snapshot(' not in source


class TestNoBacktestRegression:
    """验证回测模块不受影响"""

    def test_sell_signal_checker_api_unchanged(self):
        """SellSignalChecker公共API不变"""
        from nodes.backtest_engine.factor_selection.sell_signal_checker import SellSignalChecker
        assert hasattr(SellSignalChecker, 'check_realtime_sell')
        assert hasattr(SellSignalChecker, 'check_full_sell')

    def test_strategy_defaults_importable(self):
        """策略默认参数正常导入"""
        from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS
        assert isinstance(STRATEGY_CONFIGS, dict)
        assert len(STRATEGY_CONFIGS) > 0
