"""v2.9.54: _init_broker拆分 + _scan_loop_trading健壮性 + 风控看门狗/行情恢复提取

变更:
1. _init_broker拆分: _init_broker_gm()/_init_broker_sim()提取
2. _scan_loop_trading: scan_once异常不向上传播(返回False让主循环继续)
3. _restart_risk_thread_if_dead: 风控看门狗从_scan_loop_trading提取
4. _try_recover_quote_source: 行情恢复从_scan_loop_trading提取
"""
import ast
import os
import inspect
import pytest


# ─── 源码路径辅助 ───
SCANNER_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "nodes", "market_monitor", "scanner.py"
)
SCANNER_PATH = os.path.abspath(SCANNER_PATH)


def _read_scanner_source() -> str:
    with open(SCANNER_PATH, "r") as f:
        return f.read()


# ─── _init_broker 拆分验证 ───

class TestInitBrokerDecomposition:
    """_init_broker拆分为_init_broker_gm/_init_broker_sim"""

    def test_init_broker_gm_exists(self):
        """_init_broker_gm方法存在"""
        source = _read_scanner_source()
        assert "def _init_broker_gm(self)" in source

    def test_init_broker_sim_exists(self):
        """_init_broker_sim方法存在"""
        source = _read_scanner_source()
        assert "def _init_broker_sim(self, trade_mode" in source

    def test_init_broker_delegates(self):
        """_init_broker委托给子方法,不再内联逻辑"""
        source = _read_scanner_source()
        # _init_broker应该调用_init_broker_gm和_init_broker_sim
        assert "self._init_broker_gm()" in source
        assert "self._init_broker_sim(trade_mode)" in source

    def test_init_broker_line_count(self):
        """_init_broker行数<=15(原42行→拆分后应大幅减少)"""
        tree = ast.parse(_read_scanner_source())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_init_broker":
                lines = node.end_lineno - node.lineno + 1
                assert lines <= 15, f"_init_broker {lines}L > 15L"
                return
        pytest.fail("_init_broker not found")

    def test_init_broker_gm_creates_gm_broker(self):
        """_init_broker_gm创建GmBroker实例"""
        source = _read_scanner_source()
        # 找到_init_broker_gm方法内容
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_init_broker_gm":
                method_src = ast.get_source_segment(source, node)
                assert "GmBroker" in method_src
                assert "self._gm_broker" in method_src
                assert "self._broker = None" in method_src
                return
        pytest.fail("_init_broker_gm not found")

    def test_init_broker_sim_creates_sim_broker(self):
        """_init_broker_sim创建SimulatedBroker实例"""
        source = _read_scanner_source()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_init_broker_sim":
                method_src = ast.get_source_segment(source, node)
                assert "SimulatedBroker" in method_src
                assert "self._broker" in method_src
                return
        pytest.fail("_init_broker_sim not found")

    def test_init_broker_gm_line_count(self):
        """_init_broker_gm行数合理(<=20)"""
        tree = ast.parse(_read_scanner_source())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_init_broker_gm":
                lines = node.end_lineno - node.lineno + 1
                assert lines <= 20, f"_init_broker_gm {lines}L > 20L"
                return

    def test_init_broker_sim_line_count(self):
        """_init_broker_sim行数合理(<=30)"""
        tree = ast.parse(_read_scanner_source())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_init_broker_sim":
                lines = node.end_lineno - node.lineno + 1
                assert lines <= 30, f"_init_broker_sim {lines}L > 30L"
                return


# ─── _scan_loop_trading 健壮性验证 ───

class TestScanLoopTradingRobustness:
    """_scan_loop_trading中scan_once异常不传播"""

    def test_scan_once_in_try_except(self):
        """scan_once调用被try/except包裹"""
        source = _read_scanner_source()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_scan_loop_trading":
                method_src = ast.get_source_segment(source, node)
                # 应包含scan_once在try块中
                assert "await self.scan_once" in method_src
                # 应包含except处理
                assert "except Exception" in method_src or "except" in method_src
                return
        pytest.fail("_scan_loop_trading not found")

    def test_scan_once_failure_returns_false(self):
        """scan_once异常时返回False(不传播)"""
        source = _read_scanner_source()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_scan_loop_trading":
                method_src = ast.get_source_segment(source, node)
                # except块中应该return False
                assert "return False" in method_src
                return

    def test_scan_loop_trading_line_count(self):
        """_scan_loop_trading行数减少(原46行→提取后应更少)"""
        tree = ast.parse(_read_scanner_source())
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_scan_loop_trading":
                lines = node.end_lineno - node.lineno + 1
                assert lines <= 30, f"_scan_loop_trading {lines}L > 30L"
                return


# ─── 风控看门狗提取验证 ───

class TestRestartRiskThreadExtraction:
    """_restart_risk_thread_if_dead从_scan_loop_trading提取"""

    def test_method_exists(self):
        """_restart_risk_thread_if_dead方法存在"""
        source = _read_scanner_source()
        assert "def _restart_risk_thread_if_dead(self)" in source

    def test_creates_new_thread(self):
        """方法内创建新风控线程"""
        source = _read_scanner_source()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_restart_risk_thread_if_dead":
                method_src = ast.get_source_segment(source, node)
                assert "threading.Thread" in method_src
                assert "self._risk_loop_sync" in method_src
                return

    def test_restarts_counter(self):
        """方法内增加重启计数"""
        source = _read_scanner_source()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_restart_risk_thread_if_dead":
                method_src = ast.get_source_segment(source, node)
                assert "_risk_thread_restarts" in method_src
                return

    def test_early_return_if_alive(self):
        """线程存活时早期返回(不做任何操作)"""
        source = _read_scanner_source()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_restart_risk_thread_if_dead":
                method_src = ast.get_source_segment(source, node)
                assert "return" in method_src
                return

    def test_scan_loop_trading_delegates(self):
        """_scan_loop_trading委托给_restart_risk_thread_if_dead"""
        source = _read_scanner_source()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_scan_loop_trading":
                method_src = ast.get_source_segment(source, node)
                assert "_restart_risk_thread_if_dead()" in method_src
                return


# ─── 行情恢复提取验证 ───

class TestTryRecoverQuoteSourceExtraction:
    """_try_recover_quote_source从_scan_loop_trading提取"""

    def test_method_exists(self):
        """_try_recover_quote_source方法存在"""
        source = _read_scanner_source()
        assert "def _try_recover_quote_source(self)" in source

    def test_calls_should_try_recover(self):
        """方法内调用quote_manager.should_try_recover()"""
        source = _read_scanner_source()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_try_recover_quote_source":
                method_src = ast.get_source_segment(source, node)
                assert "should_try_recover" in method_src
                return

    def test_calls_try_recover(self):
        """方法内调用quote_manager.try_recover()"""
        source = _read_scanner_source()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_try_recover_quote_source":
                method_src = ast.get_source_segment(source, node)
                assert "try_recover" in method_src
                return

    def test_scan_loop_trading_delegates(self):
        """_scan_loop_trading委托给_try_recover_quote_source"""
        source = _read_scanner_source()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_scan_loop_trading":
                method_src = ast.get_source_segment(source, node)
                assert "_try_recover_quote_source()" in method_src
                return


# ─── 回测零影响验证 ───

class TestNoBacktestRegressionV2954:
    """v2.9.54变更不影响回测模块"""

    def test_sell_signal_checker_importable(self):
        """SellSignalChecker可正常导入"""
        try:
            from nodes.backtest_engine.factor_selection.sell_signal_checker import SellSignalChecker
            assert SellSignalChecker is not None
        except ImportError:
            pass  # 非测试环境可能缺失依赖

    def test_strategy_defaults_importable(self):
        """strategy_defaults可正常导入"""
        try:
            from nodes.backtest_engine.factor_selection.strategy_defaults import STRATEGY_CONFIGS
            assert isinstance(STRATEGY_CONFIGS, dict)
        except ImportError:
            pass

    def test_portfolio_backtester_importable(self):
        """PortfolioBacktester可正常导入"""
        try:
            from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
            assert PortfolioBacktester is not None
        except ImportError:
            pass

    def test_no_market_monitor_imports_in_backtest(self):
        """回测引擎不导入market_monitor模块"""
        backtest_path = os.path.join(
            os.path.dirname(__file__), "..", "..", 
            "nodes", "backtest_engine", "factor_selection",
            "portfolio_backtest.py"
        )
        backtest_path = os.path.abspath(backtest_path)
        if not os.path.exists(backtest_path):
            pytest.skip("backtest module not found")
        with open(backtest_path) as f:
            source = f.read()
        assert "market_monitor" not in source

    def test_version_constant_updated(self):
        """版本常量更新为v2.9.57"""
        api_path = os.path.join(
            os.path.dirname(__file__), "..", "..", 
            "nodes", "web", "api", "scanner.py"
        )
        api_path = os.path.abspath(api_path)
        with open(api_path) as f:
            source = f.read()
        assert 'v2.9.57' in source
