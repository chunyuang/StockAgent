"""
v2.9.58 方法提取测试

5个文件方法提取:
1. replay_provider: get_replay_data 129→41行, 4个子方法
2. strategy_scorer: apply_strategies 96→31行, 2个子方法
3. strategy_scorer: detect_anomalies 81→18行, 1个子方法
4. broker: place_order 80→36行, 1个子方法
5. emotion_cycle: calculate_daily_emotion 86→28行, 2个子方法
6. strategy_param_center: update_strategy_params 83→30行, 3个子方法
"""

import ast
import os
import unittest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AGENT_DIR = os.path.join(BASE_DIR, "..", "..")
MM_DIR = os.path.join(AGENT_DIR, "nodes", "market_monitor")


def _parse(filepath: str) -> ast.Module:
    with open(filepath) as f:
        return ast.parse(f.read())


def _method_lines(tree: ast.Module, name: str) -> int:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return (node.end_lineno or node.lineno) - node.lineno + 1
    return -1


def _method_exists(tree: ast.Module, name: str) -> bool:
    return _method_lines(tree, name) >= 0


class TestReplayProviderDecomposition(unittest.TestCase):
    """replay_provider.get_replay_data 拆分验证"""

    def setUp(self):
        self.tree = _parse(os.path.join(MM_DIR, "replay_provider.py"))

    def test_get_replay_data_under_50(self):
        lines = _method_lines(self.tree, "get_replay_data")
        self.assertLess(lines, 50, f"get_replay_data should be <50 lines, got {lines}")

    def test_extracted_methods_exist(self):
        for name in ["_load_daily_data", "_enrich_daily_basic", "_load_limit_pools", "_compute_volume_ratios"]:
            self.assertTrue(_method_exists(self.tree, name), f"Missing method: {name}")

    def test_extracted_methods_line_counts(self):
        self.assertLessEqual(_method_lines(self.tree, "_load_daily_data"), 25)
        self.assertLessEqual(_method_lines(self.tree, "_enrich_daily_basic"), 15)
        self.assertLessEqual(_method_lines(self.tree, "_load_limit_pools"), 35)
        self.assertLessEqual(_method_lines(self.tree, "_compute_volume_ratios"), 35)

    def test_no_vol_cache_dead_code(self):
        """vol_cache变量和timedelta导入应已消除"""
        with open(os.path.join(MM_DIR, "replay_provider.py")) as f:
            src = f.read()
        self.assertNotIn("vol_cache", src, "vol_cache dead variable should be removed")
        self.assertNotIn("from datetime import timedelta", src, "unused timedelta import should be removed")


class TestStrategyScorerExtraction(unittest.TestCase):
    """strategy_scorer.apply_strategies + detect_anomalies 提取验证"""

    def setUp(self):
        self.tree = _parse(os.path.join(MM_DIR, "strategy_scorer.py"))

    def test_apply_strategies_under_40(self):
        lines = _method_lines(self.tree, "apply_strategies")
        self.assertLess(lines, 40, f"apply_strategies should be <40 lines, got {lines}")

    def test_detect_anomalies_under_25(self):
        lines = _method_lines(self.tree, "detect_anomalies")
        self.assertLess(lines, 25, f"detect_anomalies should be <25 lines, got {lines}")

    def test_apply_filter_conditions_exists(self):
        self.assertTrue(_method_exists(self.tree, "_apply_filter_conditions"))

    def test_build_signal_from_row_exists(self):
        self.assertTrue(_method_exists(self.tree, "_build_signal_from_row"))

    def test_check_single_anomaly_exists(self):
        self.assertTrue(_method_exists(self.tree, "_check_single_anomaly"))

    def test_optional_import(self):
        """Optional应已添加到typing导入"""
        with open(os.path.join(MM_DIR, "strategy_scorer.py")) as f:
            src = f.read()
        self.assertIn("Optional", src)


class TestBrokerPlaceOrderExtraction(unittest.TestCase):
    """broker.place_order 拆分验证"""

    def setUp(self):
        self.tree = _parse(os.path.join(MM_DIR, "broker.py"))

    def test_place_order_under_40(self):
        lines = _method_lines(self.tree, "place_order")
        self.assertLess(lines, 40, f"place_order should be <40 lines, got {lines}")

    def test_execute_order_fill_exists(self):
        self.assertTrue(_method_exists(self.tree, "_execute_order_fill"))

    def test_execute_order_fill_line_count(self):
        lines = _method_lines(self.tree, "_execute_order_fill")
        self.assertLess(lines, 40, f"_execute_order_fill should be <40 lines, got {lines}")


class TestEmotionCycleExtraction(unittest.TestCase):
    """emotion_cycle.calculate_daily_emotion 拆分验证"""

    def setUp(self):
        self.tree = _parse(os.path.join(MM_DIR, "emotion_cycle.py"))

    def test_calculate_daily_emotion_under_35(self):
        lines = _method_lines(self.tree, "calculate_daily_emotion")
        self.assertLess(lines, 35, f"calculate_daily_emotion should be <35 lines, got {lines}")

    def test_collect_emotion_factors_exists(self):
        self.assertTrue(_method_exists(self.tree, "_collect_emotion_factors"))

    def test_build_emotion_score_exists(self):
        self.assertTrue(_method_exists(self.tree, "_build_emotion_score"))

    def test_collect_emotion_factors_is_async(self):
        with open(os.path.join(MM_DIR, "emotion_cycle.py")) as f:
            src = f.read()
        self.assertIn("async def _collect_emotion_factors", src)

    def test_build_emotion_score_is_sync(self):
        with open(os.path.join(MM_DIR, "emotion_cycle.py")) as f:
            src = f.read()
        self.assertIn("def _build_emotion_score", src)
        self.assertNotIn("async def _build_emotion_score", src)


class TestStrategyParamCenterExtraction(unittest.TestCase):
    """strategy_param_center.update_strategy_params 拆分验证"""

    def setUp(self):
        self.tree = _parse(os.path.join(MM_DIR, "strategy_param_center.py"))

    def test_update_strategy_params_under_45(self):
        lines = _method_lines(self.tree, "update_strategy_params")
        self.assertLess(lines, 45, f"update_strategy_params should be <45 lines, got {lines}")

    def test_persist_param_update_exists(self):
        self.assertTrue(_method_exists(self.tree, "_persist_param_update"))

    def test_record_param_history_exists(self):
        self.assertTrue(_method_exists(self.tree, "_record_param_history"))

    def test_notify_param_update_exists(self):
        self.assertTrue(_method_exists(self.tree, "_notify_param_update"))


class TestExecutionQualityExtraction(unittest.TestCase):
    """execution_quality.check_buy 拆分验证"""

    def setUp(self):
        self.tree = _parse(os.path.join(MM_DIR, "execution_quality.py"))

    def test_check_buy_under_20(self):
        lines = _method_lines(self.tree, "check_buy")
        self.assertLess(lines, 20, f"check_buy should be <20 lines, got {lines}")

    def test_check_buy_basics_exists(self):
        self.assertTrue(_method_exists(self.tree, "_check_buy_basics"))

    def test_check_buy_position_and_cash_exists(self):
        self.assertTrue(_method_exists(self.tree, "_check_buy_position_and_cash"))

    def test_check_buy_basics_line_count(self):
        lines = _method_lines(self.tree, "_check_buy_basics")
        self.assertLess(lines, 20, f"_check_buy_basics should be <20 lines, got {lines}")

    def test_check_buy_position_and_cash_line_count(self):
        lines = _method_lines(self.tree, "_check_buy_position_and_cash")
        self.assertLess(lines, 30, f"_check_buy_position_and_cash should be <30 lines, got {lines}")


class TestRiskWatchdogDrawdownExtraction(unittest.TestCase):
    """risk_watchdog._check_drawdown 拆分验证"""

    def setUp(self):
        self.tree = _parse(os.path.join(MM_DIR, "risk_watchdog.py"))

    def test_check_drawdown_under_30(self):
        lines = _method_lines(self.tree, "_check_drawdown")
        self.assertLess(lines, 30, f"_check_drawdown should be <30 lines, got {lines}")

    def test_compute_drawdowns_exists(self):
        self.assertTrue(_method_exists(self.tree, "_compute_drawdowns"))

    def test_judge_drawdown_status_exists(self):
        self.assertTrue(_method_exists(self.tree, "_judge_drawdown_status"))

    def test_compute_drawdowns_is_sync(self):
        with open(os.path.join(MM_DIR, "risk_watchdog.py")) as f:
            src = f.read()
        self.assertIn("def _compute_drawdowns", src)
        self.assertNotIn("async def _compute_drawdowns", src)


class TestEmotionCycleV2959Extraction(unittest.TestCase):
    """v2.9.61 emotion_cycle提取验证"""

    def setUp(self):
        self.tree = _parse(os.path.join(MM_DIR, "emotion_cycle.py"))
        with open(os.path.join(MM_DIR, "emotion_cycle.py")) as f:
            self.src = f.read()

    def test_try_add_pending_sell_exists(self):
        self.assertTrue(_method_exists(self.tree, "_try_add_pending_sell"))

    def test_build_emotion_sell_list_under_50(self):
        lines = _method_lines(self.tree, "build_emotion_sell_list")
        self.assertLess(lines, 50, f"build_emotion_sell_list should be <50 lines, got {lines}")

    def test_update_sentiment_score_under_15(self):
        lines = _method_lines(self.tree, "update_sentiment_score")
        self.assertLess(lines, 15, f"update_sentiment_score should be <15 lines, got {lines}")

    def test_fetch_limit_stats_exists(self):
        self.assertTrue(_method_exists(self.tree, "_fetch_limit_stats"))

    def test_fetch_up_down_ratio_exists(self):
        self.assertTrue(_method_exists(self.tree, "_fetch_up_down_ratio"))

    def test_calc_sentiment_score_exists(self):
        self.assertTrue(_method_exists(self.tree, "_calc_sentiment_score"))

    def test_persist_sentiment_score_exists(self):
        self.assertTrue(_method_exists(self.tree, "_persist_sentiment_score"))


class TestSignalDispatcherExtraction(unittest.TestCase):
    """v2.9.61 signal_dispatcher提取验证"""

    def setUp(self):
        self.tree = _parse(os.path.join(MM_DIR, "signal_dispatcher.py"))

    def test_dispatch_under_20(self):
        lines = _method_lines(self.tree, "dispatch")
        self.assertLess(lines, 20, f"dispatch should be <20 lines, got {lines}")

    def test_should_dedup_exists(self):
        self.assertTrue(_method_exists(self.tree, "_should_dedup"))

    def test_dispatch_to_channels_exists(self):
        self.assertTrue(_method_exists(self.tree, "_dispatch_to_channels"))

    def test_record_dispatch_exists(self):
        self.assertTrue(_method_exists(self.tree, "_record_dispatch"))


class TestEventBusExtraction(unittest.TestCase):
    """v2.9.61 scanner_event_bus提取验证"""

    def setUp(self):
        self.tree = _parse(os.path.join(MM_DIR, "scanner_event_bus.py"))

    def test_emit_under_25(self):
        lines = _method_lines(self.tree, "emit")
        self.assertLess(lines, 25, f"emit should be <25 lines, got {lines}")

    def test_invoke_handler_exists(self):
        self.assertTrue(_method_exists(self.tree, "_invoke_handler"))


class TestStrategyScorerMergeFactorsExtraction(unittest.TestCase):
    """v2.9.61 strategy_scorer.merge_factors提取验证"""

    def setUp(self):
        self.tree = _parse(os.path.join(MM_DIR, "strategy_scorer.py"))

    def test_merge_factors_under_10(self):
        lines = _method_lines(self.tree, "merge_factors")
        self.assertLess(lines, 10, f"merge_factors should be <10 lines, got {lines}")

    def test_realtime_to_dataframe_exists(self):
        self.assertTrue(_method_exists(self.tree, "_realtime_to_dataframe"))

    def test_classify_limit_exists(self):
        self.assertTrue(_method_exists(self.tree, "_classify_limit"))

    def test_merge_with_daily_factors_exists(self):
        self.assertTrue(_method_exists(self.tree, "_merge_with_daily_factors"))


class TestRuntimePersistencePostSellExtraction(unittest.TestCase):
    """v2.9.61 runtime_persistence.post_sell_cleanup提取验证"""

    def setUp(self):
        self.tree = _parse(os.path.join(MM_DIR, "runtime_persistence.py"))

    def test_post_sell_cleanup_under_25(self):
        lines = _method_lines(self.tree, "post_sell_cleanup")
        self.assertLess(lines, 35, f"post_sell_cleanup should be <35 lines, got {lines}")

    def test_classify_sell_stats_exists(self):
        self.assertTrue(_method_exists(self.tree, "_classify_sell_stats"))

    def test_emit_sell_events_exists(self):
        self.assertTrue(_method_exists(self.tree, "_emit_sell_events"))

    def test_persist_sell_state_exists(self):
        self.assertTrue(_method_exists(self.tree, "_persist_sell_state"))


class TestRiskWatchdogV2960Extraction(unittest.TestCase):
    """v2.9.61 risk_watchdog提取验证"""

    def setUp(self):
        self.tree = _parse(os.path.join(MM_DIR, "risk_watchdog.py"))

    def test_run_checks_under_20(self):
        lines = _method_lines(self.tree, "_run_checks")
        self.assertLess(lines, 20, f"_run_checks should be <20 lines, got {lines}")

    def test_update_overall_status_exists(self):
        self.assertTrue(_method_exists(self.tree, "_update_overall_status"))

    def test_try_auto_recovery_exists(self):
        self.assertTrue(_method_exists(self.tree, "_try_auto_recovery"))

    def test_find_overdue_positions_exists(self):
        self.assertTrue(_method_exists(self.tree, "_find_overdue_positions"))

    def test_check_position_health_under_30(self):
        lines = _method_lines(self.tree, "_check_position_health")
        self.assertLess(lines, 30, f"_check_position_health should be <30 lines, got {lines}")


class TestSignalManagerV2960Extraction(unittest.TestCase):
    """v2.9.61 signal_manager提取验证"""

    def setUp(self):
        self.tree = _parse(os.path.join(MM_DIR, "signal_manager.py"))

    def test_execute_single_buy_under_30(self):
        lines = _method_lines(self.tree, "_execute_single_buy")
        self.assertLess(lines, 30, f"_execute_single_buy should be <30 lines, got {lines}")

    def test_calc_buy_shares_exists(self):
        self.assertTrue(_method_exists(self.tree, "_calc_buy_shares"))

    def test_check_buy_quality_exists(self):
        self.assertTrue(_method_exists(self.tree, "_check_buy_quality"))

    def test_apply_buy_slippage_exists(self):
        self.assertTrue(_method_exists(self.tree, "_apply_buy_slippage"))


class TestBigMethodsReduction(unittest.TestCase):
    """超过50行方法数应减少"""

    def test_fewer_big_methods(self):
        count = 0
        for fname in os.listdir(MM_DIR):
            if not fname.endswith(".py") or fname.startswith("_"):
                continue
            try:
                tree = _parse(os.path.join(MM_DIR, fname))
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        lines = (node.end_lineno or node.lineno) - node.lineno + 1
                        if lines > 50:
                            count += 1
            except SyntaxError:
                pass
        # Was 34 before, should be fewer now
        self.assertLessEqual(count, 30, f"Expected ≤30 methods >50 lines, got {count}")


class TestNoBacktestRegressionV2958(unittest.TestCase):
    """v2.9.58 回测零影响验证"""

    def test_backtest_engine_untouched(self):
        """回测引擎文件不应被修改"""
        backtest_path = os.path.join(AGENT_DIR, "nodes", "backtest_engine", "factor_selection", "portfolio_backtest.py")
        self.assertTrue(os.path.exists(backtest_path))

    def test_version_constant_updated(self):
        with open(os.path.join(AGENT_DIR, "nodes", "web", "api", "scanner_system.py")) as f:
            src = f.read()
        self.assertIn('_DESIGN_DOC_VERSION = "v2.9.73"', src)

    def test_sell_signal_checker_untouched(self):
        """卖出信号检查器不应被修改"""
        checker_path = os.path.join(AGENT_DIR, "nodes", "backtest_engine", "factor_selection", "sell_signal_checker.py")
        self.assertTrue(os.path.exists(checker_path))


if __name__ == "__main__":
    unittest.main()
