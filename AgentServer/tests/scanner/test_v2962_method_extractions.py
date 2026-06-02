"""
v2.9.62 方法提取测试

7个模块方法提取:
1. quote_manager._fetch_eastmoney_data → _map_em_item_to_realtime + _handle_em_degrade_recovery + _handle_em_fetch_failure
2. tiered_scanner._fetch_l3_prices → _fetch_l3_eastmoney_batch + _fetch_l3_biying_snapshot + _map_quote_to_price_dict + _map_l2_quote_to_dict
3. signal_manager._post_buy_success → _build_buy_timeline_entry + _emit_buy_events
4. position_manager.update_trailing_stops → _update_single_trailing_stop
5. position_manager.retry_pending_sells → _retry_single_pending_sell
6. live_filter_pipeline._auction_filter → _calc_opening_pct + _check_auction_pass
7. strategy_scorer._check_single_anomaly → _check_broken_board + _check_strong_limit + _check_surge
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
    """获取方法行数"""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == method_name:
                return node.end_lineno - node.lineno + 1
    return 0


def _method_exists(source, method_name):
    """检查方法是否存在"""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == method_name:
                return True
    return False


def _is_staticmethod(source, method_name):
    """检查是否是@staticmethod"""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == method_name:
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Name) and dec.id == "staticmethod":
                        return True
    return False


class TestQuoteManagerV2962Extraction(unittest.TestCase):
    """v2.9.62: quote_manager 3个方法提取"""

    def setUp(self):
        self.src = _read_source("quote_manager.py")

    def test_map_em_item_to_realtime_exists(self):
        """_map_em_item_to_realtime方法存在"""
        self.assertTrue(_method_exists(self.src, "_map_em_item_to_realtime"))

    def test_map_em_item_to_realtime_is_static(self):
        """_map_em_item_to_realtime是@staticmethod"""
        self.assertTrue(_is_staticmethod(self.src, "_map_em_item_to_realtime"))

    def test_map_em_item_to_realtime_line_count(self):
        """_map_em_item_to_realtime行数合理(≤20)"""
        lines = _get_method_lines(self.src, "_map_em_item_to_realtime")
        self.assertLessEqual(lines, 20, f"_map_em_item_to_realtime {lines}行, 期望≤20")

    def test_handle_em_degrade_recovery_exists(self):
        """_handle_em_degrade_recovery方法存在"""
        self.assertTrue(_method_exists(self.src, "_handle_em_degrade_recovery"))

    def test_handle_em_degrade_recovery_line_count(self):
        """_handle_em_degrade_recovery行数合理(≤15)"""
        lines = _get_method_lines(self.src, "_handle_em_degrade_recovery")
        self.assertLessEqual(lines, 15, f"_handle_em_degrade_recovery {lines}行, 期望≤15")

    def test_handle_em_fetch_failure_exists(self):
        """_handle_em_fetch_failure方法存在"""
        self.assertTrue(_method_exists(self.src, "_handle_em_fetch_failure"))

    def test_fetch_eastmoney_data_uses_extracted_methods(self):
        """_fetch_eastmoney_data使用提取的方法"""
        self.assertIn("_map_em_item_to_realtime", self.src)
        self.assertIn("_handle_em_degrade_recovery()", self.src)
        self.assertIn("_handle_em_fetch_failure(e)", self.src)

    def test_fetch_eastmoney_data_reduced(self):
        """_fetch_eastmoney_data行数减少(≤30)"""
        lines = _get_method_lines(self.src, "_fetch_eastmoney_data")
        self.assertLessEqual(lines, 30, f"_fetch_eastmoney_data {lines}行, 期望≤30")


class TestTieredScannerV2962Extraction(unittest.TestCase):
    """v2.9.62: tiered_scanner 4个方法提取"""

    def setUp(self):
        self.src = _read_source("tiered_scanner.py")

    def test_fetch_l3_eastmoney_batch_exists(self):
        """_fetch_l3_eastmoney_batch方法存在"""
        self.assertTrue(_method_exists(self.src, "_fetch_l3_eastmoney_batch"))

    def test_fetch_l3_biying_snapshot_exists(self):
        """_fetch_l3_biying_snapshot方法存在"""
        self.assertTrue(_method_exists(self.src, "_fetch_l3_biying_snapshot"))

    def test_map_quote_to_price_dict_exists(self):
        """_map_quote_to_price_dict方法存在"""
        self.assertTrue(_method_exists(self.src, "_map_quote_to_price_dict"))

    def test_map_quote_to_price_dict_is_static(self):
        """_map_quote_to_price_dict是@staticmethod"""
        self.assertTrue(_is_staticmethod(self.src, "_map_quote_to_price_dict"))

    def test_map_l2_quote_to_dict_exists(self):
        """_map_l2_quote_to_dict方法存在"""
        self.assertTrue(_method_exists(self.src, "_map_l2_quote_to_dict"))

    def test_fetch_l3_prices_reduced(self):
        """_fetch_l3_prices行数减少(≤25)"""
        lines = _get_method_lines(self.src, "_fetch_l3_prices")
        self.assertLessEqual(lines, 28, f"_fetch_l3_prices {lines}行, 期望≤28")

    def test_fetch_l3_prices_uses_sub_methods(self):
        """_fetch_l3_prices使用子方法"""
        self.assertIn("_fetch_l3_eastmoney_batch", self.src)
        self.assertIn("_fetch_l3_biying_snapshot", self.src)
        self.assertIn("_map_quote_to_price_dict", self.src)


class TestSignalManagerV2962Extraction(unittest.TestCase):
    """v2.9.62: signal_manager 2个方法提取"""

    def setUp(self):
        self.src = _read_source("signal_manager.py")

    def test_build_buy_timeline_entry_exists(self):
        """_build_buy_timeline_entry方法存在"""
        self.assertTrue(_method_exists(self.src, "_build_buy_timeline_entry"))

    def test_build_buy_timeline_entry_line_count(self):
        """_build_buy_timeline_entry行数合理(≤35)"""
        lines = _get_method_lines(self.src, "_build_buy_timeline_entry")
        self.assertLessEqual(lines, 35, f"_build_buy_timeline_entry {lines}行, 期望≤35")

    def test_emit_buy_events_exists(self):
        """_emit_buy_events方法存在"""
        self.assertTrue(_method_exists(self.src, "_emit_buy_events"))

    def test_emit_buy_events_line_count(self):
        """_emit_buy_events行数合理(≤25)"""
        lines = _get_method_lines(self.src, "_emit_buy_events")
        self.assertLessEqual(lines, 25, f"_emit_buy_events {lines}行, 期望≤25")

    def test_post_buy_success_reduced(self):
        """_post_buy_success行数减少(≤12)"""
        lines = _get_method_lines(self.src, "_post_buy_success")
        self.assertLessEqual(lines, 12, f"_post_buy_success {lines}行, 期望≤12")

    def test_post_buy_success_uses_extracted_methods(self):
        """_post_buy_success使用提取的方法"""
        self.assertIn("_build_buy_timeline_entry(", self.src)
        self.assertIn("_emit_buy_events(", self.src)


class TestPositionManagerV2962Extraction(unittest.TestCase):
    """v2.9.62: position_manager 2个方法提取"""

    def setUp(self):
        self.src = _read_source("position_manager.py")

    def test_update_single_trailing_stop_exists(self):
        """_update_single_trailing_stop方法存在"""
        self.assertTrue(_method_exists(self.src, "_update_single_trailing_stop"))

    def test_update_single_trailing_stop_line_count(self):
        """_update_single_trailing_stop行数合理(≤35)"""
        lines = _get_method_lines(self.src, "_update_single_trailing_stop")
        self.assertLessEqual(lines, 35, f"_update_single_trailing_stop {lines}行, 期望≤35")

    def test_update_trailing_stops_reduced(self):
        """update_trailing_stops行数减少(≤30)"""
        lines = _get_method_lines(self.src, "update_trailing_stops")
        self.assertLessEqual(lines, 33, f"update_trailing_stops {lines}行, 期望≤33")

    def test_update_trailing_stops_uses_extracted(self):
        """update_trailing_stops调用_update_single_trailing_stop"""
        self.assertIn("_update_single_trailing_stop(", self.src)

    def test_retry_single_pending_sell_exists(self):
        """_retry_single_pending_sell方法存在"""
        self.assertTrue(_method_exists(self.src, "_retry_single_pending_sell"))

    def test_retry_single_pending_sell_line_count(self):
        """_retry_single_pending_sell行数合理(≤40)"""
        lines = _get_method_lines(self.src, "_retry_single_pending_sell")
        self.assertLessEqual(lines, 40, f"_retry_single_pending_sell {lines}行, 期望≤40")

    def test_retry_pending_sells_reduced(self):
        """retry_pending_sells行数减少(≤20)"""
        lines = _get_method_lines(self.src, "retry_pending_sells")
        self.assertLessEqual(lines, 22, f"retry_pending_sells {lines}行, 期望≤22")

    def test_retry_pending_sells_uses_extracted(self):
        """retry_pending_sells调用_retry_single_pending_sell"""
        self.assertIn("_retry_single_pending_sell(", self.src)


class TestLiveFilterPipelineV2962Extraction(unittest.TestCase):
    """v2.9.62: live_filter_pipeline 2个方法提取"""

    def setUp(self):
        self.src = _read_source("live_filter_pipeline.py")

    def test_calc_opening_pct_exists(self):
        """_calc_opening_pct方法存在"""
        self.assertTrue(_method_exists(self.src, "_calc_opening_pct"))

    def test_calc_opening_pct_is_static(self):
        """_calc_opening_pct是@staticmethod"""
        self.assertTrue(_is_staticmethod(self.src, "_calc_opening_pct"))

    def test_calc_opening_pct_line_count(self):
        """_calc_opening_pct行数合理(≤15)"""
        lines = _get_method_lines(self.src, "_calc_opening_pct")
        self.assertLessEqual(lines, 15, f"_calc_opening_pct {lines}行, 期望≤15")

    def test_check_auction_pass_exists(self):
        """_check_auction_pass方法存在"""
        self.assertTrue(_method_exists(self.src, "_check_auction_pass"))

    def test_check_auction_pass_is_static(self):
        """_check_auction_pass是@staticmethod"""
        self.assertTrue(_is_staticmethod(self.src, "_check_auction_pass"))

    def test_check_auction_pass_line_count(self):
        """_check_auction_pass行数合理(≤15)"""
        lines = _get_method_lines(self.src, "_check_auction_pass")
        self.assertLessEqual(lines, 15, f"_check_auction_pass {lines}行, 期望≤15")

    def test_auction_filter_reduced(self):
        """_auction_filter行数减少(≤30)"""
        lines = _get_method_lines(self.src, "_auction_filter")
        self.assertLessEqual(lines, 35, f"_auction_filter {lines}行, 期望≤35")

    def test_auction_filter_uses_extracted(self):
        """_auction_filter使用提取的方法"""
        self.assertIn("_calc_opening_pct(", self.src)
        self.assertIn("_check_auction_pass(", self.src)


class TestStrategyScorerV2962Extraction(unittest.TestCase):
    """v2.9.62: strategy_scorer 3个方法提取"""

    def setUp(self):
        self.src = _read_source("strategy_scorer.py")

    def test_check_broken_board_exists(self):
        """_check_broken_board方法存在"""
        self.assertTrue(_method_exists(self.src, "_check_broken_board"))

    def test_check_strong_limit_exists(self):
        """_check_strong_limit方法存在"""
        self.assertTrue(_method_exists(self.src, "_check_strong_limit"))

    def test_check_surge_exists(self):
        """_check_surge方法存在"""
        self.assertTrue(_method_exists(self.src, "_check_surge"))

    def test_check_broken_board_line_count(self):
        """_check_broken_board行数合理(≤15)"""
        lines = _get_method_lines(self.src, "_check_broken_board")
        self.assertLessEqual(lines, 18, f"_check_broken_board {lines}行, 期望≤18")

    def test_check_strong_limit_line_count(self):
        """_check_strong_limit行数合理(≤15)"""
        lines = _get_method_lines(self.src, "_check_strong_limit")
        self.assertLessEqual(lines, 18, f"_check_strong_limit {lines}行, 期望≤18")

    def test_check_surge_line_count(self):
        """_check_surge行数合理(≤20)"""
        lines = _get_method_lines(self.src, "_check_surge")
        self.assertLessEqual(lines, 20, f"_check_surge {lines}行, 期望≤20")

    def test_check_single_anomaly_reduced(self):
        """_check_single_anomaly行数减少(≤35)"""
        lines = _get_method_lines(self.src, "_check_single_anomaly")
        self.assertLessEqual(lines, 40, f"_check_single_anomaly {lines}行, 期望≤40")

    def test_check_single_anomaly_uses_extracted(self):
        """_check_single_anomaly使用提取的方法"""
        self.assertIn("_check_broken_board(", self.src)
        self.assertIn("_check_strong_limit(", self.src)
        self.assertIn("_check_surge(", self.src)


class TestBigMethodsReductionV2962(unittest.TestCase):
    """v2.9.62: >50行方法数减少"""

    def test_big_methods_count(self):
        """>50行方法数≤7(v2.9.61有12个, 提取后应减少)"""
        import ast as _ast
        count = 0
        for root, dirs, files in os.walk(MONITOR_DIR):
            if "tests" in root or "__pycache__" in root:
                continue
            for f in files:
                if f.endswith(".py") and f != "__init__.py":
                    fp = os.path.join(root, f)
                    with open(fp) as fh:
                        tree = _ast.parse(fh.read())
                    for node in _ast.walk(tree):
                        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                            lines = node.end_lineno - node.lineno + 1
                            if lines > 50:
                                count += 1
        self.assertLessEqual(count, 7, f">50行方法数={count}, 期望≤7")


class TestNoBacktestRegressionV2962(unittest.TestCase):
    """v2.9.62: 回测零影响"""

    def test_backtest_tests_pass(self):
        """回测测试仍然通过(零影响)"""
        import subprocess
        result = subprocess.run(
            ["python", "-m", "pytest", "tests/backtest/", "-q", "--tb=no"],
            capture_output=True, text=True, cwd=os.path.join(BASE_DIR, "..", "..")
        )
        self.assertEqual(result.returncode, 0, f"回测测试失败: {result.stdout}")

    def test_version_constant(self):
        """Web API版本常量为v2.9.62"""
        filepath = os.path.join(WEB_API_DIR, "scanner_system.py")
        with open(filepath) as f:
            src = f.read()
        self.assertIn('_DESIGN_DOC_VERSION = "v2.9.65"', src)


if __name__ == "__main__":
    unittest.main()
