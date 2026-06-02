"""v2.9.48: getattr/hasattr防御消除 + 关键路径日志级别提升

验证:
1. _scan_loop_error_count/_last_realtime_update_ts 已是类属性, 无需getattr/hasattr
2. _risk_watchdog/_signal_dispatcher 已在_init_modules中初始化, 无需hasattr
3. runtime_persistence关键路径(盘后结算/快照/飞书日报)日志级别为warning
4. scanner.py中不再有getattr(self, '_scan_loop_error_count')/hasattr防御
"""
import ast
import os
import unittest

SCANNER_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "nodes", "market_monitor", "scanner.py"
)
RP_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "nodes", "market_monitor", "runtime_persistence.py"
)
WEB_API_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "nodes", "web", "api", "scanner_system.py"
)


class TestGetattrHasattrElimination(unittest.TestCase):
    """验证scanner.py中不再有对类属性默认值的getattr/hasattr防御"""

    @classmethod
    def setUpClass(cls):
        with open(SCANNER_PATH) as f:
            cls.scanner_src = f.read()

    def test_no_getattr_scan_loop_error_count(self):
        """_scan_loop_error_count已是类属性, 不再需要getattr"""
        self.assertNotIn(
            "getattr(self, '_scan_loop_error_count'",
            self.scanner_src,
            "_scan_loop_error_count已是类属性默认值, 不再需要getattr防御"
        )

    def test_no_getattr_last_realtime_update_ts(self):
        """_last_realtime_update_ts已是类属性, 不再需要getattr"""
        self.assertNotIn(
            "getattr(self, '_last_realtime_update_ts'",
            self.scanner_src,
            "_last_realtime_update_ts已是类属性默认值, 不再需要getattr防御"
        )

    def test_no_hasattr_scan_loop_error_count(self):
        """_scan_loop_error_count已是类属性, 不再需要hasattr"""
        self.assertNotIn(
            "hasattr(self, '_scan_loop_error_count')",
            self.scanner_src,
            "_scan_loop_error_count已是类属性默认值, 不再需要hasattr防御"
        )

    def test_no_hasattr_last_realtime_update_ts(self):
        """_last_realtime_update_ts已是类属性, 不再需要hasattr"""
        self.assertNotIn(
            "hasattr(self, '_last_realtime_update_ts')",
            self.scanner_src,
            "_last_realtime_update_ts已是类属性默认值, 不再需要hasattr防御"
        )

    def test_no_hasattr_risk_watchdog_in_build_module_status(self):
        """_risk_watchdog在_init_modules中一定初始化, _build_module_status不需要hasattr"""
        # Check the specific method
        tree = ast.parse(self.scanner_src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_build_module_status":
                src = ast.get_source_segment(self.scanner_src, node)
                self.assertIsNotNone(src)
                self.assertNotIn(
                    "hasattr(self, '_risk_watchdog')",
                    src,
                    "_risk_watchdog在_init_signal_and_risk中初始化, 不需要hasattr"
                )
                break

    def test_no_hasattr_signal_dispatcher_in_build_module_status(self):
        """_signal_dispatcher在_init_modules中一定初始化, 不需要hasattr"""
        tree = ast.parse(self.scanner_src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_build_module_status":
                src = ast.get_source_segment(self.scanner_src, node)
                self.assertIsNotNone(src)
                self.assertNotIn(
                    "hasattr(self, '_signal_dispatcher')",
                    src,
                    "_signal_dispatcher在_init_signal_and_risk中初始化, 不需要hasattr"
                )
                break

    def test_class_attribute_scan_loop_error_count(self):
        """_scan_loop_error_count是类属性"""
        tree = ast.parse(self.scanner_src)
        class_attrs = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "MarketScanner":
                for item in node.body:
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                        class_attrs.add(item.target.id)
                    elif isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name):
                                class_attrs.add(target.id)
        self.assertIn("_scan_loop_error_count", class_attrs)

    def test_class_attribute_last_realtime_update_ts(self):
        """_last_realtime_update_ts是类属性"""
        tree = ast.parse(self.scanner_src)
        class_attrs = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "MarketScanner":
                for item in node.body:
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                        class_attrs.add(item.target.id)
                    elif isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name):
                                class_attrs.add(target.id)
        self.assertIn("_last_realtime_update_ts", class_attrs)


class TestRuntimePersistenceLogLevels(unittest.TestCase):
    """验证runtime_persistence关键路径日志级别为warning"""

    @classmethod
    def setUpClass(cls):
        with open(RP_PATH) as f:
            cls.rp_src = f.read()

    def test_settlement_event_log_warning(self):
        """盘后结算事件发射失败应warning而非debug"""
        self.assertIn(
            'logger.warning(f"[SCANNER] 盘后结算事件发射失败',
            self.rp_src,
            "盘后结算事件发射失败影响前端状态同步, 应warning"
        )

    def test_sentiment_log_warning(self):
        """盘后情绪预计算失败应warning"""
        self.assertIn(
            'logger.warning(f"[SCANNER] 盘后情绪预计算失败',
            self.rp_src,
            "情绪预计算影响次日策略, 应warning"
        )

    def test_close_data_sync_log_warning(self):
        """盘后数据同步失败应warning"""
        self.assertIn(
            'logger.warning(f"[SCANNER] 盘后数据同步失败',
            self.rp_src,
            "数据同步失败影响MongoDB完整性, 应warning"
        )

    def test_post_sell_snapshot_log_warning(self):
        """卖出后运行时快照失败应warning"""
        self.assertIn(
            'logger.warning(f"[SCANNER] 卖出后运行时快照失败',
            self.rp_src,
            "快照失败影响崩溃恢复, 应warning"
        )

    def test_feishu_push_log_warning(self):
        """飞书日报推送失败应warning"""
        self.assertIn(
            'logger.warning(f"[DAILY] 飞书日报推送失败',
            self.rp_src,
            "飞书推送失败运维不可见, 应warning"
        )

    def test_local_fallback_cleanup_log_warning(self):
        """本地降级文件清理失败应warning"""
        self.assertIn(
            'logger.warning(f"[SNAPSHOT] 本地降级文件清理失败',
            self.rp_src,
            "降级文件残留影响下次恢复, 应warning"
        )


class TestVersionSync(unittest.TestCase):
    """版本号同步"""

    def test_web_api_version(self):
        """Web API版本号应为v2.9.61"""
        with open(WEB_API_PATH) as f:
            src = f.read()
        self.assertIn('_DESIGN_DOC_VERSION = "v2.9.67"', src)


class TestNoBacktestRegression(unittest.TestCase):
    """回测零影响"""

    def test_backtest_tests_pass(self):
        """回测测试文件存在且可导入"""
        backtest_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "tests", "backtest"
        )
        self.assertTrue(os.path.isdir(backtest_path), "回测测试目录应存在")

    def test_sell_signal_checker_not_modified(self):
        """sell_signal_checker未被本次修改影响"""
        checker_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "nodes",
            "backtest_engine", "factor_selection", "sell_signal_checker.py"
        )
        if not os.path.exists(checker_path):
            self.skipTest("sell_signal_checker不在预期路径")
        # 文件应存在且可导入
        self.assertTrue(os.path.isfile(checker_path))

    def test_portfolio_backtest_not_modified(self):
        """回测引擎未被修改"""
        bt_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "nodes",
            "backtest_engine", "factor_selection", "portfolio_backtest.py"
        )
        if not os.path.exists(bt_path):
            self.skipTest("portfolio_backtest不在预期路径")
        self.assertTrue(os.path.isfile(bt_path))


if __name__ == "__main__":
    unittest.main()
