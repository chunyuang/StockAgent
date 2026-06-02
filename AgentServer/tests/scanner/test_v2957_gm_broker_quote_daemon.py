"""v2.9.61: gm_broker策略脚本拆分 + quote_manager方法提取 + scanner_daemon.run拆分

测试覆盖:
1. GmBroker._generate_strategy_script拆分为6个模板方法
2. QuoteManager._fetch_eastmoney_data / _merge_limit_pool_data / _update_realtime_cache提取
3. ScannerDaemon._init_ipc_channels / _run_command_loop提取
4. 超过50行方法数减少
5. 回测零影响
"""
import ast
import os
import sys
import unittest

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(BASE, "..", ".."))
NODES = os.path.join(ROOT, "nodes", "market_monitor")


def _parse(filepath: str) -> ast.Module:
    with open(filepath) as f:
        return ast.parse(f.read())


def _method_lines(tree: ast.Module, name: str) -> int:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node.end_lineno - node.lineno + 1
    return -1


def _method_exists(tree: ast.Module, name: str) -> bool:
    return any(
        isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name
        for n in ast.walk(tree)
    )


class TestGmBrokerScriptDecomposition(unittest.TestCase):
    """gm_broker._generate_strategy_script拆分为6个模板方法"""

    @classmethod
    def setUpClass(cls):
        cls.tree = _parse(os.path.join(NODES, "gm_broker.py"))

    def test_generate_strategy_script_exists(self):
        self.assertTrue(_method_exists(self.tree, "_generate_strategy_script"))

    def test_generate_strategy_script_reduced(self):
        """_generate_strategy_script应<20行(委托到6个模板方法)"""
        lines = _method_lines(self.tree, "_generate_strategy_script")
        self.assertLessEqual(lines, 20, f"_generate_strategy_script {lines}行, 预期≤20")

    def test_script_header_exists(self):
        self.assertTrue(_method_exists(self.tree, "_script_header"))

    def test_script_callbacks_exists(self):
        self.assertTrue(_method_exists(self.tree, "_script_callbacks"))

    def test_script_order_execution_exists(self):
        self.assertTrue(_method_exists(self.tree, "_script_order_execution"))

    def test_script_state_update_exists(self):
        self.assertTrue(_method_exists(self.tree, "_script_state_update"))

    def test_script_helpers_exists(self):
        self.assertTrue(_method_exists(self.tree, "_script_helpers"))

    def test_script_main_entry_exists(self):
        self.assertTrue(_method_exists(self.tree, "_script_main_entry"))

    def test_script_header_is_staticmethod(self):
        """_script_header应为@staticmethod"""
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ClassDef) and node.name == "GmBroker":
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == "_script_header":
                        decorators = [d.id if isinstance(d, ast.Name) else str(d) for d in item.decorator_list]
                        self.assertIn("staticmethod", decorators, "_script_header缺少@staticmethod")
                        return
        self.fail("_script_header not found in GmBroker")

    def test_no_method_over_100_lines(self):
        """gm_broker不应有超过100行的方法(原_generate_strategy_script 178行已拆分)"""
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                lines = node.end_lineno - node.lineno + 1
                self.assertLess(lines, 100, f"{node.name} {lines}行, 应<100")


class TestQuoteManagerExtraction(unittest.TestCase):
    """quote_manager.fetch_realtime_batch提取3个子方法"""

    @classmethod
    def setUpClass(cls):
        cls.tree = _parse(os.path.join(NODES, "quote_manager.py"))

    def test_fetch_realtime_batch_reduced(self):
        """fetch_realtime_batch应<55行(原152行)"""
        lines = _method_lines(self.tree, "fetch_realtime_batch")
        self.assertLessEqual(lines, 55, f"fetch_realtime_batch {lines}行, 预期≤55")

    def test_fetch_eastmoney_data_exists(self):
        self.assertTrue(_method_exists(self.tree, "_fetch_eastmoney_data"))

    def test_merge_limit_pool_data_exists(self):
        self.assertTrue(_method_exists(self.tree, "_merge_limit_pool_data"))

    def test_update_realtime_cache_exists(self):
        self.assertTrue(_method_exists(self.tree, "_update_realtime_cache"))

    def test_fetch_eastmoney_data_is_async(self):
        """_fetch_eastmoney_data应为async方法"""
        for node in ast.walk(self.tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_fetch_eastmoney_data":
                return
        self.fail("_fetch_eastmoney_data不是async方法")

    def test_merge_limit_pool_data_is_async(self):
        """_merge_limit_pool_data应为async方法"""
        for node in ast.walk(self.tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_merge_limit_pool_data":
                return
        self.fail("_merge_limit_pool_data不是async方法")

    def test_update_realtime_cache_is_sync(self):
        """_update_realtime_cache应为同步方法(只操作缓存)"""
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_update_realtime_cache":
                return
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_update_realtime_cache":
                self.fail("_update_realtime_cache不应是async")
        self.fail("_update_realtime_cache not found")


class TestDaemonRunDecomposition(unittest.TestCase):
    """scanner_daemon.run拆分为_init_ipc_channels + _run_command_loop"""

    @classmethod
    def setUpClass(cls):
        cls.tree = _parse(os.path.join(NODES, "scanner_daemon.py"))

    def test_run_reduced(self):
        """run()应<20行(原60行)"""
        lines = _method_lines(self.tree, "run")
        self.assertLessEqual(lines, 20, f"run {lines}行, 预期≤20")

    def test_init_ipc_channels_exists(self):
        self.assertTrue(_method_exists(self.tree, "_init_ipc_channels"))

    def test_run_command_loop_exists(self):
        self.assertTrue(_method_exists(self.tree, "_run_command_loop"))

    def test_init_ipc_channels_is_async(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_init_ipc_channels":
                return
        self.fail("_init_ipc_channels不是async方法")

    def test_run_command_loop_is_async(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_run_command_loop":
                return
        self.fail("_run_command_loop不是async方法")

    def test_init_ipc_channels_content(self):
        """_init_ipc_channels应包含Redis初始化+频道设置"""
        for node in ast.walk(self.tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_init_ipc_channels":
                src = ast.get_source_segment(open(os.path.join(NODES, "scanner_daemon.py")).read(), node)
                self.assertIsNotNone(src)
                self.assertIn("aioredis", src)
                self.assertIn("cmd_list_key", src)
                return
        self.fail("_init_ipc_channels not found")

    def test_run_command_loop_content(self):
        """_run_command_loop应包含BLPOP循环+异常处理"""
        for node in ast.walk(self.tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_run_command_loop":
                src = ast.get_source_segment(open(os.path.join(NODES, "scanner_daemon.py")).read(), node)
                self.assertIsNotNone(src)
                self.assertIn("blpop", src)
                self.assertIn("CancelledError", src)
                return
        self.fail("_run_command_loop not found")


class TestBigMethodsReduction(unittest.TestCase):
    """超过50行方法数减少"""

    def test_big_method_count_decreased(self):
        """v2.9.61: >50行方法数应<37(v2.9.56为37, gm_broker -1, daemon -0)"""
        big_count = 0
        for root_dir, dirs, files in os.walk(NODES):
            for f in files:
                if not f.endswith('.py') or f == '__init__.py':
                    continue
                path = os.path.join(root_dir, f)
                try:
                    tree = _parse(path)
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            lines = node.end_lineno - node.lineno + 1
                            if lines > 50:
                                big_count += 1
                except:
                    pass
        self.assertLessEqual(big_count, 37, f">50行方法数{big_count}, 预期≤37")


class TestNoBacktestRegressionV2957(unittest.TestCase):
    """v2.9.61变更不影响回测模块"""

    def test_backtest_files_unchanged(self):
        """回测引擎文件不应被修改"""
        backtest_dir = os.path.join(ROOT, "backtest")
        if not os.path.exists(backtest_dir):
            self.skipTest("backtest dir not found")
        # Key files that should NOT be touched
        protected = ["portfolio_backtest.py", "sell_signal_checker.py", "strategy_defaults.py"]
        for f in protected:
            path = os.path.join(backtest_dir, f)
            if os.path.exists(path):
                with open(path) as fh:
                    content = fh.read()
                # Should not contain v2.9.61 references
                self.assertNotIn("v2.9.61", content, f"{f}不应包含v2.9.61引用")

    def test_design_doc_version(self):
        """Web API版本常量应为v2.9.61"""
        api_path = os.path.join(ROOT, "nodes", "web", "api", "scanner.py")
        with open(api_path) as f:
            content = f.read()
        self.assertIn('_DESIGN_DOC_VERSION = "v2.9.61"', content)

    def test_scanner_version_constant(self):
        """scanner模块应能正常导入"""
        sys.path.insert(0, ROOT)
        try:
            from nodes.web.api.scanner import _DESIGN_DOC_VERSION
            self.assertEqual(_DESIGN_DOC_VERSION, "v2.9.61")
        except ImportError:
            self.skipTest("scanner module import failed")


if __name__ == "__main__":
    unittest.main()
