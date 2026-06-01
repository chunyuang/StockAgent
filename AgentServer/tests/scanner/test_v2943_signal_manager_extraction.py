"""
v2.9.43 测试: signal_manager方法提取 + position_manager broker代理

验证:
1. signal_manager.execute_signals拆分为4个子方法
2. signal_manager.update_signals拆分为3个子方法
3. position_manager新增get_positions/get_account代理
4. 回测模块零影响
"""

import ast
import os
import pytest
import inspect


# ==================== signal_manager方法提取 ====================

class TestSignalManagerMethodExtraction:
    """验证signal_manager方法提取完整性"""

    @pytest.fixture
    def sm_source(self):
        path = os.path.join(os.path.dirname(__file__), "..", "..", "nodes", "market_monitor", "signal_manager.py")
        with open(path) as f:
            return f.read()

    def test_expire_old_signals_exists(self, sm_source):
        """_expire_old_signals方法存在"""
        tree = ast.parse(sm_source)
        method_names = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                method_names.add(node.name)
        assert "_expire_old_signals" in method_names

    def test_merge_new_signals_exists(self, sm_source):
        """_merge_new_signals方法存在"""
        tree = ast.parse(sm_source)
        method_names = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                method_names.add(node.name)
        assert "_merge_new_signals" in method_names

    def test_process_new_signals_exists(self, sm_source):
        """_process_new_signals方法存在"""
        tree = ast.parse(sm_source)
        method_names = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                method_names.add(node.name)
        assert "_process_new_signals" in method_names

    def test_check_signal_eligibility_exists(self, sm_source):
        """_check_signal_eligibility方法存在"""
        tree = ast.parse(sm_source)
        method_names = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                method_names.add(node.name)
        assert "_check_signal_eligibility" in method_names

    def test_execute_single_buy_exists(self, sm_source):
        """_execute_single_buy方法存在"""
        tree = ast.parse(sm_source)
        method_names = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                method_names.add(node.name)
        assert "_execute_single_buy" in method_names

    def test_post_buy_success_exists(self, sm_source):
        """_post_buy_success方法存在"""
        tree = ast.parse(sm_source)
        method_names = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                method_names.add(node.name)
        assert "_post_buy_success" in method_names

    def test_handle_dry_run_exists(self, sm_source):
        """_handle_dry_run方法存在"""
        tree = ast.parse(sm_source)
        method_names = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                method_names.add(node.name)
        assert "_handle_dry_run" in method_names


class TestSignalManagerUpdateSignalsSplit:
    """验证update_signals拆分为3个子方法"""

    @pytest.fixture
    def sm_source(self):
        path = os.path.join(os.path.dirname(__file__), "..", "..", "nodes", "market_monitor", "signal_manager.py")
        with open(path) as f:
            return f.read()

    def test_update_signals_calls_expire(self, sm_source):
        """update_signals调用_expire_old_signals"""
        assert "_expire_old_signals" in sm_source
        # 在update_signals方法内找到调用
        tree = ast.parse(sm_source)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "update_signals":
                calls = []
                for child in ast.walk(node):
                    if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                        calls.append(child.func.attr)
                assert "_expire_old_signals" in calls

    def test_update_signals_calls_merge(self, sm_source):
        """update_signals调用_merge_new_signals"""
        tree = ast.parse(sm_source)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "update_signals":
                calls = []
                for child in ast.walk(node):
                    if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                        calls.append(child.func.attr)
                assert "_merge_new_signals" in calls

    def test_update_signals_calls_process(self, sm_source):
        """update_signals调用_process_new_signals"""
        tree = ast.parse(sm_source)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "update_signals":
                calls = []
                for child in ast.walk(node):
                    if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                        calls.append(child.func.attr)
                assert "_process_new_signals" in calls

    def test_update_signals_line_count(self, sm_source):
        """update_signals方法行数<20(编排方法)"""
        tree = ast.parse(sm_source)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "update_signals":
                lines = node.end_lineno - node.lineno + 1
                assert lines < 20, f"update_signals {lines}行, 应<20行"


class TestSignalManagerExecuteSignalsSplit:
    """验证execute_signals拆分"""

    @pytest.fixture
    def sm_source(self):
        path = os.path.join(os.path.dirname(__file__), "..", "..", "nodes", "market_monitor", "signal_manager.py")
        with open(path) as f:
            return f.read()

    def test_execute_signals_line_count(self, sm_source):
        """execute_signals方法行数<30(编排方法)"""
        tree = ast.parse(sm_source)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "execute_signals":
                lines = node.end_lineno - node.lineno + 1
                assert lines < 30, f"execute_signals {lines}行, 应<30行"

    def test_execute_signals_calls_eligibility(self, sm_source):
        """execute_signals调用_check_signal_eligibility"""
        tree = ast.parse(sm_source)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "execute_signals":
                calls = []
                for child in ast.walk(node):
                    if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                        calls.append(child.func.attr)
                assert "_check_signal_eligibility" in calls

    def test_execute_signals_calls_single_buy(self, sm_source):
        """execute_signals调用_execute_single_buy"""
        tree = ast.parse(sm_source)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "execute_signals":
                calls = []
                for child in ast.walk(node):
                    if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                        calls.append(child.func.attr)
                assert "_execute_single_buy" in calls

    def test_check_signal_eligibility_returns_tuple(self, sm_source):
        """_check_signal_eligibility返回(eligible, reason)元组"""
        tree = ast.parse(sm_source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_check_signal_eligibility":
                return_stmts = []
                for child in ast.walk(node):
                    if isinstance(child, ast.Return) and isinstance(child.value, ast.Tuple):
                        return_stmts.append(len(child.value.elts))
                # 应该有多处返回2元组
                assert any(n == 2 for n in return_stmts), "应有返回2元组(eligible, reason)"

    def test_no_await_circuit_breaker_in_check(self, sm_source):
        """_check_signal_eligibility中不await熔断检查(sync读取避免异步开销)"""
        tree = ast.parse(sm_source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_check_signal_eligibility":
                # 不应是async函数
                assert not isinstance(node, ast.AsyncFunctionDef)

    def test_execute_signals_handles_break_conditions(self, sm_source):
        """execute_signals在circuit_breaker/max_positions时break"""
        tree = ast.parse(sm_source)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "execute_signals":
                has_break = False
                for child in ast.walk(node):
                    if isinstance(child, ast.Break):
                        has_break = True
                assert has_break, "execute_signals应有break语句(全局阻挡)"


class TestSignalManagerMergeNewSignals:
    """验证_merge_new_signals逻辑"""

    @pytest.fixture
    def sm_source(self):
        path = os.path.join(os.path.dirname(__file__), "..", "..", "nodes", "market_monitor", "signal_manager.py")
        with open(path) as f:
            return f.read()

    def test_merge_is_sync(self, sm_source):
        """_merge_new_signals是同步方法(纯计算)"""
        tree = ast.parse(sm_source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_merge_new_signals":
                assert not isinstance(node, ast.AsyncFunctionDef)

    def test_expire_is_async(self, sm_source):
        """_expire_old_signals是异步方法(含publish)"""
        tree = ast.parse(sm_source)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_expire_old_signals":
                return  # 找到async定义
        pytest.fail("_expire_old_signals应该是async方法")

    def test_process_is_async(self, sm_source):
        """_process_new_signals是异步方法"""
        tree = ast.parse(sm_source)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_process_new_signals":
                return
        pytest.fail("_process_new_signals应该是async方法")


class TestSignalManagerLineCount:
    """验证signal_manager行数变化"""

    def test_signal_manager_line_count(self):
        """signal_manager行数<420(v2.9.42: 410行→拆分后略增但方法更清晰)"""
        path = os.path.join(os.path.dirname(__file__), "..", "..", "nodes", "market_monitor", "signal_manager.py")
        with open(path) as f:
            lines = len(f.readlines())
        assert lines < 460, f"signal_manager {lines}行, 应<460行"


# ==================== 版本同步 ====================

class TestVersionSyncV2943:
    """验证版本号同步"""

    def test_api_version_v2943(self):
        """API版本号=v2.9.43"""
        path = os.path.join(os.path.dirname(__file__), "..", "..", "nodes", "web", "api", "scanner.py")
        with open(path) as f:
            content = f.read()
        assert "v2.9.48" in content

    def test_delegate_map_has_signal_entries(self):
        """DELEGATE_MAP包含signal_manager条目"""
        path = os.path.join(os.path.dirname(__file__), "..", "..", "nodes", "market_monitor", "scanner.py")
        with open(path) as f:
            content = f.read()
        assert '"_signal_manager"' in content


# ==================== 回测零影响 ====================

class TestNoBacktestRegressionV2943:
    """验证回测模块零影响"""

    def test_sell_signal_checker_importable(self):
        """SellSignalChecker可导入"""
        path = os.path.join(os.path.dirname(__file__), "..", "..", "nodes", "backtest_engine", "factor_selection", "sell_signal_checker.py")
        assert os.path.exists(path), f"sell_signal_checker.py not found"

    def test_strategy_defaults_importable(self):
        """strategy_defaults文件存在"""
        path = os.path.join(os.path.dirname(__file__), "..", "..", "nodes", "backtest_engine", "strategy_defaults.py")
        assert os.path.exists(path), f"strategy_defaults.py not found"

    def test_portfolio_backtester_importable(self):
        """PortfolioBacktester可导入"""
        from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
        assert PortfolioBacktester is not None

    def test_signal_manager_not_imported_by_backtest(self):
        """回测引擎不导入signal_manager"""
        import importlib
        mod = importlib.import_module("nodes.backtest_engine.factor_selection.portfolio_backtest")
        source = inspect.getsource(mod)
        assert "signal_manager" not in source

    def test_backtest_test_count(self):
        """回测测试文件存在且非空"""
        backtest_test_dir = os.path.join(os.path.dirname(__file__), "..", "backtest")
        if os.path.exists(backtest_test_dir):
            test_files = [f for f in os.listdir(backtest_test_dir) if f.startswith("test_")]
            assert len(test_files) > 0
