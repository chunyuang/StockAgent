"""
v2.9.43 审查优化测试 — _save_param_snapshot提取 + _init_state类属性瘦身

变更项:
1. start()中参数快照保存逻辑提取为_save_param_snapshot()
2. _init_state()中21个标量默认值提升为类属性声明
3. start()有效代码行数从43→30, _init_state()从70→30
4. 回测零影响
"""
import pytest
import inspect
import os
import sys

# 确保可导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


class TestSaveParamSnapshotExtraction:
    """验证_save_param_snapshot提取【v2.9.42:委托到RuntimePersistence】"""

    def test_method_delegated(self):
        """_save_param_snapshot通过DELEGATE_MAP委托到RuntimePersistence【v2.9.42】"""
        from nodes.market_monitor.scanner import MarketScanner
        dm = MarketScanner._DELEGATE_MAP
        assert "_save_param_snapshot" in dm
        assert dm["_save_param_snapshot"] == ("_runtime_persistence", "save_param_snapshot")

    def test_runtime_persistence_has_method(self):
        """RuntimePersistence.save_param_snapshot存在且为async"""
        from nodes.market_monitor.runtime_persistence import RuntimePersistence
        assert hasattr(RuntimePersistence, 'save_param_snapshot')
        assert inspect.iscoroutinefunction(RuntimePersistence.save_param_snapshot)

    def test_start_calls_save_param_snapshot(self):
        """start()方法调用_save_param_snapshot"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner.start)
        assert '_save_param_snapshot' in source, "start()应调用_save_param_snapshot"

    def test_start_no_inline_param_snapshot_logic(self):
        """start()不再内联参数快照逻辑"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner.start)
        # 不应包含原来的内联逻辑
        assert 'STRATEGY_CONFIGS' not in source, 'start()不应内联STRATEGY_CONFIGS引用'
        assert 'param_snapshots' not in source, 'start()不应内联MongoDB操作'


class TestClassAttributeDefaults:
    """验证类属性默认值提升"""

    def test_class_has_default_attributes(self):
        """MarketScanner有类属性默认值"""
        from nodes.market_monitor.scanner import MarketScanner
        # 标量默认值应在类属性上
        assert MarketScanner._risk_running is False
        assert MarketScanner._risk_thread_restarts == 0
        assert MarketScanner._is_running is False
        assert MarketScanner._scan_count == 0
        assert MarketScanner._nav_peak == 1.0
        assert MarketScanner._trade_date == ""

    def test_instance_gets_class_defaults(self):
        """实例继承类属性默认值"""
        from nodes.market_monitor.scanner import MarketScanner
        scanner = MarketScanner.__new__(MarketScanner)
        # 不调__init__, 只检查类属性继承
        assert scanner._is_running is False
        assert scanner._scan_count == 0
        assert scanner._nav_peak == 1.0

    def test_instance_overrides_do_not_affect_class(self):
        """实例设置属性不影响类默认值"""
        from nodes.market_monitor.scanner import MarketScanner
        scanner = MarketScanner.__new__(MarketScanner)
        scanner._is_running = True
        scanner._scan_count = 5
        # 类默认值不变
        assert MarketScanner._is_running is False
        assert MarketScanner._scan_count == 0


class TestInitStateSlimmed:
    """验证_init_state瘦身"""

    def test_init_state_no_redundant_assignments(self):
        """_init_state不再包含已提升为类属性的赋值"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner._init_state)
        # 这些赋值已在类属性中，不应重复
        assert 'self._risk_thread = None' not in source
        assert 'self._is_running = False' not in source
        assert 'self._scan_count = 0' not in source
        assert 'self._nav_peak = 1.0' not in source

    def test_init_state_still_initializes_mutable_defaults(self):
        """_init_state仍然初始化可变默认值(dict/list)"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner._init_state)
        # 可变默认值必须在__init__中初始化，不能共享
        assert 'self._trailing_stops' in source
        assert 'self._pending_sells' in source
        assert 'self._execution_stats' in source
        assert 'self._realtime_cache' in source
        assert 'self._active_signals' in source

    def test_init_state_line_count(self):
        """_init_state有效代码行数应<35行"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner._init_state)
        lines = [l for l in source.split('\n') if l.strip() and not l.strip().startswith('#')]
        assert len(lines) < 35, f"_init_state()应<35行有效代码, 实际{len(lines)}行"


class TestStartMethodSlimmed:
    """验证start()方法瘦身"""

    def test_start_line_count(self):
        """start()方法有效代码行数应<35行"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner.start)
        lines = [l for l in source.split('\n') if l.strip() and not l.strip().startswith('#')]
        assert len(lines) < 35, f"start()方法应<35行有效代码, 实际{len(lines)}行"


class TestSaveParamSnapshotBehavior:
    """验证_save_param_snapshot行为【v2.9.42:委托到RuntimePersistence】"""

    def test_snapshot_writes_to_mongo(self):
        """参数快照写入MongoDB param_snapshots集合"""
        from nodes.market_monitor.runtime_persistence import RuntimePersistence
        source = inspect.getsource(RuntimePersistence.save_param_snapshot)
        assert 'param_snapshots' in source

    def test_snapshot_contains_date(self):
        """快照包含date字段"""
        from nodes.market_monitor.runtime_persistence import RuntimePersistence
        source = inspect.getsource(RuntimePersistence.save_param_snapshot)
        assert '"date"' in source or "'date'" in source

    def test_snapshot_handles_failure_gracefully(self):
        """快照保存失败不影响启动"""
        from nodes.market_monitor.runtime_persistence import RuntimePersistence
        source = inspect.getsource(RuntimePersistence.save_param_snapshot)
        assert 'except Exception' in source


class TestScannerLineCount:
    """scanner.py行数回归"""

    def test_scanner_line_count(self):
        """scanner.py行数应<1550行"""
        scanner_path = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "nodes", "market_monitor", "scanner.py"
        )
        scanner_path = os.path.normpath(scanner_path)
        with open(scanner_path) as f:
            line_count = len(f.readlines())
        assert line_count < 1550, f"scanner.py应<1550行, 实际{line_count}行"


class TestNoBacktestRegressionV2937:
    """回测模块零影响"""

    def test_sell_signal_checker_importable(self):
        """SellSignalChecker可导入"""
        from nodes.backtest_engine.factor_selection.sell_signal_checker import SellSignalChecker
        assert SellSignalChecker is not None

    def test_strategy_defaults_importable(self):
        """strategy_defaults可导入"""
        from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS, GLOBAL_RISK
        assert isinstance(STRATEGY_CONFIGS, dict)

    def test_portfolio_backtester_importable(self):
        """回测引擎可导入"""
        from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
        assert PortfolioBacktester is not None

    def test_scanner_class_attribute_isolation(self):
        """类属性不会导致实例间共享可变状态"""
        from nodes.market_monitor.scanner import MarketScanner
        s1 = MarketScanner.__new__(MarketScanner)
        s2 = MarketScanner.__new__(MarketScanner)
        # 初始化可变属性
        s1._init_state()
        s2._init_state()
        # 修改s1不应影响s2
        s1._trailing_stops["test"] = {"stop": 1.0}
        assert "test" not in s2._trailing_stops, "实例间不应共享可变状态"

    def test_version_constant(self):
        """版本常量已更新"""
        from nodes.web.api.scanner import _DESIGN_DOC_VERSION
        assert _DESIGN_DOC_VERSION == "v2.9.47"
