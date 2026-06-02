"""
v2.9.64 方法提取测试 - 最终清零>50行方法

5个剩余方法提取:
1. quote_manager._merge_limit_pool_data → _merge_limit_up_items + _merge_limit_down_items + _merge_limit_open_items (3个@staticmethod)
2. tiered_scanner._l3_scan → _collect_l3_refresh_codes (@staticmethod)
3. tiered_scanner._l2_scan → _build_price_cache_from_refreshed (@staticmethod)
4. scanner.scan_once → _reset_scan_error_state
5. live_filter_pipeline._apply_filter_layers → _describe_special_period (@staticmethod) + _mark_layer_passed
"""

import ast
import os
import unittest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MONITOR_DIR = os.path.join(BASE_DIR, "..", "..", "nodes", "market_monitor")
WEB_API_DIR = os.path.join(BASE_DIR, "..", "..", "nodes", "web", "api")


def _read_source(filename):
    filepath = os.path.join(MONITOR_DIR, filename)
    with open(filepath) as f:
        return f.read()


def _get_method_lines(source, method_name):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == method_name:
                return node.end_lineno - node.lineno + 1
    return 0


def _method_exists(source, method_name):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == method_name:
                return True
    return False


def _is_staticmethod(source, method_name):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == method_name:
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Name) and dec.id == "staticmethod":
                        return True
    return False


class TestQuoteManagerV2963Extraction(unittest.TestCase):
    """v2.9.64: quote_manager 3个@staticmethod提取"""

    def setUp(self):
        self.src = _read_source("quote_manager.py")

    def test_merge_limit_up_items_exists(self):
        """_merge_limit_up_items方法存在"""
        self.assertTrue(_method_exists(self.src, "_merge_limit_up_items"))

    def test_merge_limit_up_items_is_static(self):
        """_merge_limit_up_items是@staticmethod"""
        self.assertTrue(_is_staticmethod(self.src, "_merge_limit_up_items"))

    def test_merge_limit_down_items_exists(self):
        """_merge_limit_down_items方法存在"""
        self.assertTrue(_method_exists(self.src, "_merge_limit_down_items"))

    def test_merge_limit_down_items_is_static(self):
        """_merge_limit_down_items是@staticmethod"""
        self.assertTrue(_is_staticmethod(self.src, "_merge_limit_down_items"))

    def test_merge_limit_open_items_exists(self):
        """_merge_limit_open_items方法存在"""
        self.assertTrue(_method_exists(self.src, "_merge_limit_open_items"))

    def test_merge_limit_open_items_is_static(self):
        """_merge_limit_open_items是@staticmethod"""
        self.assertTrue(_is_staticmethod(self.src, "_merge_limit_open_items"))

    def test_merge_limit_pool_data_uses_sub_methods(self):
        """_merge_limit_pool_data使用提取的子方法"""
        self.assertIn("_merge_limit_up_items(", self.src)
        self.assertIn("_merge_limit_down_items(", self.src)
        self.assertIn("_merge_limit_open_items(", self.src)

    def test_merge_limit_pool_data_under_50(self):
        """_merge_limit_pool_data行数≤50"""
        lines = _get_method_lines(self.src, "_merge_limit_pool_data")
        self.assertLessEqual(lines, 50, f"_merge_limit_pool_data {lines}行, 期望≤50")


class TestTieredScannerV2963Extraction(unittest.TestCase):
    """v2.9.64: tiered_scanner 2个@staticmethod提取"""

    def setUp(self):
        self.src = _read_source("tiered_scanner.py")

    def test_collect_l3_refresh_codes_exists(self):
        """_collect_l3_refresh_codes方法存在"""
        self.assertTrue(_method_exists(self.src, "_collect_l3_refresh_codes"))

    def test_collect_l3_refresh_codes_is_static(self):
        """_collect_l3_refresh_codes是@staticmethod"""
        self.assertTrue(_is_staticmethod(self.src, "_collect_l3_refresh_codes"))

    def test_l3_scan_uses_collect(self):
        """_l3_scan使用_collect_l3_refresh_codes"""
        self.assertIn("_collect_l3_refresh_codes(", self.src)

    def test_l3_scan_under_50(self):
        """_l3_scan行数≤50"""
        lines = _get_method_lines(self.src, "_l3_scan")
        self.assertLessEqual(lines, 50, f"_l3_scan {lines}行, 期望≤50")

    def test_build_price_cache_from_refreshed_exists(self):
        """_build_price_cache_from_refreshed方法存在"""
        self.assertTrue(_method_exists(self.src, "_build_price_cache_from_refreshed"))

    def test_build_price_cache_from_refreshed_is_static(self):
        """_build_price_cache_from_refreshed是@staticmethod"""
        self.assertTrue(_is_staticmethod(self.src, "_build_price_cache_from_refreshed"))

    def test_l2_scan_uses_build_cache(self):
        """_l2_scan使用_build_price_cache_from_refreshed"""
        self.assertIn("_build_price_cache_from_refreshed(", self.src)

    def test_l2_scan_under_50(self):
        """_l2_scan行数≤50"""
        lines = _get_method_lines(self.src, "_l2_scan")
        self.assertLessEqual(lines, 50, f"_l2_scan {lines}行, 期望≤50")


class TestScannerV2963Extraction(unittest.TestCase):
    """v2.9.64: scanner 1个方法提取"""

    def setUp(self):
        self.src = _read_source("scanner.py")

    def test_reset_scan_error_state_exists(self):
        """_reset_scan_error_state方法存在"""
        self.assertTrue(_method_exists(self.src, "_reset_scan_error_state"))

    def test_scan_once_uses_reset(self):
        """scan_once调用_reset_scan_error_state"""
        self.assertIn("_reset_scan_error_state()", self.src)

    def test_scan_once_under_50(self):
        """scan_once行数≤50"""
        lines = _get_method_lines(self.src, "scan_once")
        self.assertLessEqual(lines, 50, f"scan_once {lines}行, 期望≤50")


class TestLiveFilterPipelineV2963Extraction(unittest.TestCase):
    """v2.9.64: live_filter_pipeline 2个方法提取"""

    def setUp(self):
        self.src = _read_source("live_filter_pipeline.py")

    def test_describe_special_period_exists(self):
        """_describe_special_period方法存在"""
        self.assertTrue(_method_exists(self.src, "_describe_special_period"))

    def test_describe_special_period_is_static(self):
        """_describe_special_period是@staticmethod"""
        self.assertTrue(_is_staticmethod(self.src, "_describe_special_period"))

    def test_mark_layer_passed_exists(self):
        """_mark_layer_passed方法存在"""
        self.assertTrue(_method_exists(self.src, "_mark_layer_passed"))

    def test_apply_filter_layers_uses_sub_methods(self):
        """_apply_filter_layers使用提取的子方法"""
        self.assertIn("_describe_special_period(", self.src)
        self.assertIn("_mark_layer_passed(", self.src)

    def test_apply_filter_layers_under_50(self):
        """_apply_filter_layers行数≤50"""
        lines = _get_method_lines(self.src, "_apply_filter_layers")
        self.assertLessEqual(lines, 50, f"_apply_filter_layers {lines}行, 期望≤50")


class TestBigMethodsZeroV2963(unittest.TestCase):
    """v2.9.64: >50行方法数为0"""

    def test_no_methods_over_50_lines(self):
        """market_monitor模块无>50行方法"""
        count = 0
        for root, dirs, files in os.walk(MONITOR_DIR):
            if "tests" in root or "__pycache__" in root:
                continue
            for f in files:
                if f.endswith(".py") and f != "__init__.py":
                    fp = os.path.join(root, f)
                    with open(fp) as fh:
                        tree = ast.parse(fh.read())
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            lines = node.end_lineno - node.lineno + 1
                            if lines > 50:
                                count += 1
                                print(f"  {f}: {node.name} ({lines}L)")
        self.assertEqual(count, 0, f">50行方法数={count}, 期望0")


class TestVersionV2963(unittest.TestCase):
    """v2.9.64: 版本常量"""

    def test_version_constant(self):
        """Web API版本常量为v2.9.64"""
        filepath = os.path.join(WEB_API_DIR, "scanner_system.py")
        with open(filepath) as f:
            src = f.read()
        self.assertIn('_DESIGN_DOC_VERSION = "v2.9.65"', src)


if __name__ == "__main__":
    unittest.main()
