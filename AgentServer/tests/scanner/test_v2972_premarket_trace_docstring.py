"""v2.9.74: 盘前研判子方法提取 + trace_id全链路 + docstring补齐"""
import ast
import inspect
import unittest


def _get_mod():
    import nodes.web.api.scanner_system as _mod
    return _mod


class TestPremarketScoringExtraction(unittest.TestCase):
    """验证_build_premarket_analysis拆分后的5个评分子方法"""

    def test_score_sentiment_bullish(self):
        mod = _get_mod()
        reasons = []
        score = mod._score_sentiment({"score": 60, "phase_name": "上升", "position_ratio": 0.7}, reasons)
        self.assertEqual(score, 1.0)
        self.assertTrue(any("偏强" in r["text"] for r in reasons))

    def test_score_sentiment_bearish(self):
        mod = _get_mod()
        reasons = []
        score = mod._score_sentiment({"score": 30, "phase_name": "下降", "position_ratio": 0.3}, reasons)
        self.assertEqual(score, -1.0)

    def test_score_sentiment_neutral(self):
        mod = _get_mod()
        reasons = []
        score = mod._score_sentiment({"score": 50, "phase_name": "震荡", "position_ratio": 0.5}, reasons)
        self.assertEqual(score, 0.0)

    def test_score_up_down_ratio_bullish(self):
        mod = _get_mod()
        reasons = []
        score = mod._score_up_down_ratio({"up_count": 3000, "down_count": 1000}, reasons)
        self.assertEqual(score, 1.0)

    def test_score_up_down_ratio_bearish(self):
        mod = _get_mod()
        reasons = []
        score = mod._score_up_down_ratio({"up_count": 1000, "down_count": 3000}, reasons)
        self.assertEqual(score, -1.0)

    def test_score_up_down_ratio_neutral(self):
        mod = _get_mod()
        reasons = []
        score = mod._score_up_down_ratio({"up_count": 2000, "down_count": 2000}, reasons)
        self.assertEqual(score, 0.0)

    def test_score_limit_pools_hot_market(self):
        mod = _get_mod()
        reasons = []
        score = mod._score_limit_pools(
            {"up_count": 60, "down_count": 5, "continue_stats": {"5": 3}, "sector_heat": [{"name": "AI", "count": 5}]},
            reasons,
        )
        self.assertGreater(score, 0)

    def test_score_limit_pools_cold_market(self):
        mod = _get_mod()
        reasons = []
        score = mod._score_limit_pools(
            {"up_count": 10, "down_count": 5, "continue_stats": {}, "sector_heat": []},
            reasons,
        )
        self.assertLess(score, 0)

    def test_score_position_gaps(self):
        mod = _get_mod()
        reasons = []
        score = mod._score_position_gaps([{"gap_pct": 3}, {"gap_pct": -3}], reasons)
        self.assertEqual(score, 0.0)  # +0.5 -0.5 = 0

    def test_score_strategy_hit_rate_good(self):
        mod = _get_mod()
        reasons = []
        mod._score_strategy_hit_rate({"momentum": {"total": 10, "win_rate": 70}}, reasons)
        self.assertTrue(any("70%" in r["text"] for r in reasons))

    def test_build_premarket_analysis_bullish(self):
        mod = _get_mod()
        result = mod._build_premarket_analysis(
            {"up_count": 3000, "down_count": 1000, "data_date": "20260603"},
            {"score": 60, "phase_name": "上升", "position_ratio": 0.7},
            {"up_count": 60, "down_count": 5, "continue_stats": {"5": 3, "3": 10}, "sector_heat": [{"name": "AI", "count": 5}]},
            [{"gap_pct": 3}],
            [], [],
            {"momentum": {"total": 10, "win_rate": 70}},
        )
        self.assertEqual(result["verdict"], "bullish")
        self.assertGreaterEqual(result["score"], 2.0)
        self.assertEqual(result["data_date"], "20260603")


class TestTraceIdFullChain(unittest.TestCase):
    """验证卖出trace_id贯穿所有调用方"""

    def test_position_manager_risk_trace(self):
        """execute_risk_sell生成risk-trace_id"""
        src = inspect.getsource(__import__('nodes.market_monitor.position_manager', fromlist=['PositionManager']).PositionManager.execute_risk_sell)
        self.assertIn("trace_id", src)
        self.assertIn("risk-", src)

    def test_position_manager_liq_trace(self):
        """liquidate_positions生成liq-trace_id"""
        src = inspect.getsource(__import__('nodes.market_monitor.position_manager', fromlist=['PositionManager']).PositionManager.liquidate_positions)
        self.assertIn("trace_id", src)
        self.assertIn("liq-", src)

    def test_position_checker_trace(self):
        """_execute_sell_list生成chk-trace_id"""
        src = inspect.getsource(__import__('nodes.market_monitor.position_checker', fromlist=['PositionChecker']).PositionChecker._execute_sell_list)
        self.assertIn("trace_id", src)
        self.assertIn("chk-", src)

    def test_risk_watchdog_trace(self):
        """_liquidate_positions生成emg-trace_id"""
        src = inspect.getsource(__import__('nodes.market_monitor.risk_watchdog', fromlist=['RiskWatchdog']).RiskWatchdog._liquidate_positions)
        self.assertIn("trace_id", src)
        self.assertIn("emg-", src)

    def test_runtime_persistence_trace_in_timeline(self):
        """build_timeline_entry包含trace_id字段"""
        src = inspect.getsource(__import__('nodes.market_monitor.runtime_persistence', fromlist=['RuntimePersistence']).RuntimePersistence.build_timeline_entry)
        self.assertIn("trace_id", src)


class TestDocstringCompleteness(unittest.TestCase):
    """验证v2.9.74 docstring补齐"""

    def test_event_subscribers_handlers_have_docstrings(self):
        """EventBus handler函数都有docstring"""
        from nodes.market_monitor import scanner_event_subscribers
        src = inspect.getsource(scanner_event_subscribers)
        tree = ast.parse(src)
        handlers_without_doc = []
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name.startswith("on_"):
                if not ast.get_docstring(node):
                    handlers_without_doc.append(node.name)
        self.assertEqual(len(handlers_without_doc), 0,
                         f"EventBus handlers missing docstring: {handlers_without_doc}")

    def test_scanner_get_positions_has_docstring(self):
        """scanner.get_positions有docstring"""
        from nodes.market_monitor.scanner import MarketScanner
        self.assertIsNotNone(MarketScanner.get_positions.__doc__)


class TestMethodSizeV2972(unittest.TestCase):
    """验证v2.9.74拆分后的方法行数"""

    def test_build_premarket_analysis_under_40(self):
        """_build_premarket_analysis < 40行"""
        mod = _get_mod()
        lines = len(inspect.getsource(mod._build_premarket_analysis).split('\n'))
        self.assertLess(lines, 40, f"_build_premarket_analysis should be <40L, got {lines}")

    def test_build_limit_pools_under_35(self):
        """_build_limit_pools < 35行"""
        mod = _get_mod()
        lines = len(inspect.getsource(mod._build_limit_pools).split('\n'))
        self.assertLess(lines, 35, f"_build_limit_pools should be <35L, got {lines}")

    def test_scoring_submethods_exist(self):
        """5个评分子方法存在"""
        mod = _get_mod()
        for name in ['_score_sentiment', '_score_up_down_ratio', '_score_limit_pools',
                      '_score_position_gaps', '_score_strategy_hit_rate']:
            self.assertTrue(hasattr(mod, name), f"Missing sub-method: {name}")

    def test_limit_pools_helpers_exist(self):
        """limit_pools辅助方法存在"""
        mod = _get_mod()
        self.assertTrue(hasattr(mod, '_build_name_industry_maps'))
        self.assertTrue(hasattr(mod, '_aggregate_limit_stats'))


class TestVersionV2972(unittest.TestCase):
    """版本常量"""

    def test_version_is_v2972(self):
        from nodes.web.api.scanner_system import _DESIGN_DOC_VERSION
        self.assertEqual(_DESIGN_DOC_VERSION, "v2.9.74")


class TestNoBacktestRegressionV2972(unittest.TestCase):
    """v2.9.74对回测模块零影响"""

    def test_backtest_files_unchanged(self):
        """回测相关文件未被v2.9.74修改"""
        import os
        backtest_dirs = ['nodes/backtest/', 'core/backtest/']
        for d in backtest_dirs:
            if os.path.exists(d):
                for root, dirs, files in os.walk(d):
                    for f in files:
                        if f.endswith('.py'):
                            path = os.path.join(root, f)
                            with open(path) as fh:
                                if 'v2.9.74' in fh.read():
                                    self.fail(f"Backtest file modified: {path}")
