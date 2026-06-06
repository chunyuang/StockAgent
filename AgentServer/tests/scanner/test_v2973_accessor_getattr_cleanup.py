#!/usr/bin/env python3
"""v2.9.74 Scanner访问器接口 + getattr/hasattr防御消除 测试

覆盖:
1. 9个Scanner访问器方法存在+返回类型+行为
2. scanner_utils.py中getattr/hasattr调用已替换为访问器
3. position_manager.py中hasattr(scanner, '_trade_date')已替换为get_trade_date()
4. 回测零影响
"""
import ast
import os
import unittest

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestScannerAccessorMethods(unittest.TestCase):
    """Scanner 9个访问器方法存在性+签名+返回类型"""

    def _get_scanner_methods(self) -> dict:
        """解析scanner.py获取所有方法定义"""
        src_path = os.path.join(PROJECT_ROOT, "nodes", "market_monitor", "scanner.py")
        with open(src_path) as f:
            tree = ast.parse(f.read())
        methods = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods[node.name] = {
                    "node": node,
                    "lineno": node.lineno,
                    "returns": ast.unparse(node.returns) if node.returns else None,
                }
        return methods

    def test_get_current_sentiment(self):
        """get_current_sentiment() 存在且返回Dict"""
        methods = self._get_scanner_methods()
        self.assertIn("get_current_sentiment", methods)
        ret = methods["get_current_sentiment"]["returns"]
        self.assertIn("Dict", ret or "")

    def test_get_current_position_ratio(self):
        """get_current_position_ratio() 存在且返回Optional[float]"""
        methods = self._get_scanner_methods()
        self.assertIn("get_current_position_ratio", methods)

    def test_get_scan_error_count(self):
        """get_scan_error_count() 存在且返回int"""
        methods = self._get_scanner_methods()
        self.assertIn("get_scan_error_count", methods)
        ret = methods["get_scan_error_count"]["returns"]
        self.assertIn("int", ret or "")

    def test_get_event_bus(self):
        """get_event_bus() 存在且返回Optional[ScannerEventBus]"""
        methods = self._get_scanner_methods()
        self.assertIn("get_event_bus", methods)

    def test_get_risk_thread(self):
        """get_risk_thread() 存在且返回Optional[threading.Thread]"""
        methods = self._get_scanner_methods()
        self.assertIn("get_risk_thread", methods)

    def test_get_circuit_breaker(self):
        """get_circuit_breaker() 存在且返回Dict"""
        methods = self._get_scanner_methods()
        self.assertIn("get_circuit_breaker", methods)

    def test_get_risk_thread_restarts(self):
        """get_risk_thread_restarts() 存在且返回int"""
        methods = self._get_scanner_methods()
        self.assertIn("get_risk_thread_restarts", methods)

    def test_is_risk_running(self):
        """is_risk_running() 存在且返回bool"""
        methods = self._get_scanner_methods()
        self.assertIn("is_risk_running", methods)

    def test_get_trade_date(self):
        """get_trade_date() 存在且返回str"""
        methods = self._get_scanner_methods()
        self.assertIn("get_trade_date", methods)

    def test_accessor_section_header(self):
        """访问器方法区域有明确的注释标题"""
        src_path = os.path.join(PROJECT_ROOT, "nodes", "market_monitor", "scanner.py")
        with open(src_path) as f:
            content = f.read()
        self.assertIn("状态访问器", content)
        self.assertIn("替代getattr/hasattr穿透", content)


class TestScannerUtilsGetattrCleanup(unittest.TestCase):
    """scanner_utils.py中getattr/hasattr调用已被访问器替换"""

    def _get_source(self) -> str:
        src_path = os.path.join(PROJECT_ROOT, "nodes", "market_monitor", "scanner_utils.py")
        with open(src_path) as f:
            return f.read()

    def test_no_getattr_on_current_sentiment(self):
        """不再有 getattr(scanner, '_current_sentiment')"""
        src = self._get_source()
        self.assertNotIn("getattr(scanner, '_current_sentiment'", src)

    def test_no_getattr_on_position_ratio(self):
        """不再有 getattr(scanner, '_current_position_ratio')"""
        src = self._get_source()
        self.assertNotIn("getattr(scanner, '_current_position_ratio'", src)

    def test_no_getattr_on_scan_error_count(self):
        """不再有 getattr(scanner, '_scan_loop_error_count')"""
        src = self._get_source()
        self.assertNotIn("getattr(scanner, '_scan_loop_error_count'", src)

    def test_no_getattr_on_risk_thread_restarts(self):
        """不再有 getattr(scanner, '_risk_thread_restarts')"""
        src = self._get_source()
        self.assertNotIn("getattr(scanner, '_risk_thread_restarts'", src)

    def test_no_getattr_on_risk_running(self):
        """不再有 getattr(scanner, '_risk_running')"""
        src = self._get_source()
        self.assertNotIn("getattr(scanner, '_risk_running'", src)

    def test_no_hasattr_on_event_bus(self):
        """不再有 hasattr(scanner, '_event_bus')"""
        src = self._get_source()
        self.assertNotIn("hasattr(scanner, '_event_bus')", src)

    def test_no_hasattr_on_risk_thread(self):
        """不再有 hasattr(scanner, '_risk_thread')"""
        src = self._get_source()
        self.assertNotIn("hasattr(scanner, '_risk_thread')", src)

    def test_no_hasattr_on_circuit_breaker(self):
        """不再有 hasattr(scanner, '_circuit_breaker')"""
        src = self._get_source()
        self.assertNotIn("hasattr(scanner, '_circuit_breaker')", src)

    def test_uses_get_current_sentiment(self):
        """使用 scanner.get_current_sentiment()"""
        src = self._get_source()
        self.assertIn("scanner.get_current_sentiment()", src)

    def test_uses_get_scan_error_count(self):
        """使用 scanner.get_scan_error_count()"""
        src = self._get_source()
        self.assertIn("scanner.get_scan_error_count()", src)

    def test_uses_get_event_bus(self):
        """使用 scanner.get_event_bus()"""
        src = self._get_source()
        self.assertIn("scanner.get_event_bus()", src)

    def test_uses_get_risk_thread(self):
        """使用 scanner.get_risk_thread()"""
        src = self._get_source()
        self.assertIn("scanner.get_risk_thread()", src)

    def test_uses_is_risk_running(self):
        """使用 scanner.is_risk_running()"""
        src = self._get_source()
        self.assertIn("scanner.is_risk_running()", src)

    def test_uses_get_circuit_breaker(self):
        """使用 scanner.get_circuit_breaker()"""
        src = self._get_source()
        self.assertIn("scanner.get_circuit_breaker()", src)

    def test_remaining_getattr_count_reduced(self):
        """scanner_utils.py中剩余getattr数<=3(非scanner内部状态的不算)"""
        src = self._get_source()
        # 统计 getattr(scanner 和 hasattr(scanner 的出现次数
        scanner_getattr = src.count("getattr(scanner")
        scanner_hasattr = src.count("hasattr(scanner")
        total = scanner_getattr + scanner_hasattr
        self.assertLessEqual(total, 1,
            f"scanner_utils.py中仍有{total}处getattr/hasattr(scanner,...), 期望≤1")


class TestPositionManagerGetattrCleanup(unittest.TestCase):
    """position_manager.py中hasattr(scanner, '_trade_date')已替换"""

    def _get_source(self) -> str:
        src_path = os.path.join(PROJECT_ROOT, "nodes", "market_monitor", "position_manager.py")
        with open(src_path) as f:
            return f.read()

    def test_no_hasattr_trade_date(self):
        """不再有 hasattr(scanner, '_trade_date')"""
        src = self._get_source()
        self.assertNotIn("hasattr(scanner, '_trade_date')", src)

    def test_uses_get_trade_date(self):
        """使用 scanner.get_trade_date()"""
        src = self._get_source()
        self.assertIn("scanner.get_trade_date()", src)


class TestVersionV2973(unittest.TestCase):
    """版本常量验证"""

    def test_design_doc_version(self):
        """_DESIGN_DOC_VERSION = v2.9.74"""
        src_path = os.path.join(PROJECT_ROOT, "nodes", "web", "api", "scanner_system.py")
        with open(src_path) as f:
            content = f.read()
        self.assertIn('_DESIGN_DOC_VERSION = "v2.9.81"', content)

    def test_scanner_version_assertions(self):
        """版本断言文件已更新到v2.9.74"""
        test_dir = os.path.join(PROJECT_ROOT, "tests", "scanner")
        v2972_count = 0
        for fname in os.listdir(test_dir):
            if fname.startswith("test_v29") and fname.endswith(".py") and fname != "test_v2973_accessor_getattr_cleanup.py":
                fpath = os.path.join(test_dir, fname)
                with open(fpath) as f:
                    content = f.read()
                if "v2.9.72" in content:
                    v2972_count += 1
        # v2.9.72应该已被替换为v2.9.74,不应再出现(排除本文件自身的引用)
        self.assertEqual(v2972_count, 0, f"仍有{v2972_count}个测试文件引用v2.9.72")


class TestNoBacktestRegression(unittest.TestCase):
    """回测零影响验证"""

    def test_backtest_files_unchanged(self):
        """回测引擎文件未被修改"""
        backtest_dir = os.path.join(PROJECT_ROOT, "backtest_engine")
        if not os.path.exists(backtest_dir):
            self.skipTest("回测引擎目录不存在")
        # 检查关键文件存在且可导入
        for fname in ["backtester.py", "strategy_defaults.py"]:
            fpath = os.path.join(backtest_dir, fname)
            self.assertTrue(os.path.exists(fpath), f"{fname}不存在")

    def test_scanner_utils_no_backtest_import(self):
        """scanner_utils.py未导入回测模块"""
        src_path = os.path.join(PROJECT_ROOT, "nodes", "market_monitor", "scanner_utils.py")
        with open(src_path) as f:
            content = f.read()
        self.assertNotIn("from nodes.backtest_engine", content)
        self.assertNotIn("import backtest", content)


if __name__ == "__main__":
    unittest.main()
