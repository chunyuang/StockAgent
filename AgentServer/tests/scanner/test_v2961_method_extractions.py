"""v2.9.61 方法提取测试

覆盖6个提取:
1. live_filter_pipeline.apply → _apply_filter_layers + _finalize_traces
2. emotion_cycle.handle_emotion_phase_change → _execute_emotion_batch_sell + _emit_rebalance_event
3. scanner_delegate_router.resolve_delegate → _DISPATCH_TABLE路由表 + 6个_resolve_*方法
4. tiered_scanner._l3_builtin_check → _check_single_position_stop_profit
5. broker._match → _calc_dynamic_slippage
6. risk_watchdog._check_heartbeat → _judge_startup_heartbeat + _judge_heartbeat_elapsed
7. emotion_cycle._calculate_zt_premium → _get_prev_trade_date + _calc_avg_zt_premium
"""

import ast
import os
import unittest

# 基于__file__的绝对路径
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_AGENT_DIR = os.path.join(_BASE_DIR, "..", "..")
_NODES_DIR = os.path.join(_AGENT_DIR, "nodes", "market_monitor")


def _read_source(filename):
    """读取market_monitor模块源码"""
    filepath = os.path.join(_NODES_DIR, filename)
    with open(filepath) as f:
        return f.read()


def _parse_tree(filename):
    """解析模块AST"""
    return ast.parse(_read_source(filename))


def _get_method(tree, class_name, method_name):
    """获取指定类中指定方法的AST节点"""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == method_name:
                    return item
    return None


def _get_method_lines(tree, class_name, method_name):
    """获取方法行数"""
    m = _get_method(tree, class_name, method_name)
    if m:
        return m.end_lineno - m.lineno + 1
    return 0


class TestLiveFilterPipelineExtraction(unittest.TestCase):
    """live_filter_pipeline.apply → _apply_filter_layers + _finalize_traces"""

    def setUp(self):
        self.tree = _parse_tree("live_filter_pipeline.py")
        self.src = _read_source("live_filter_pipeline.py")

    def test_apply_filter_layers_exists(self):
        """_apply_filter_layers方法应存在"""
        m = _get_method(self.tree, "LiveFilterPipeline", "_apply_filter_layers")
        self.assertIsNotNone(m, "_apply_filter_layers方法不存在")

    def test_apply_filter_layers_is_async(self):
        """_apply_filter_layers应为async方法"""
        m = _get_method(self.tree, "LiveFilterPipeline", "_apply_filter_layers")
        self.assertIsNotNone(m)
        self.assertIsInstance(m, ast.AsyncFunctionDef)

    def test_apply_filter_layers_line_count(self):
        """_apply_filter_layers行数应≤55"""
        lines = _get_method_lines(self.tree, "LiveFilterPipeline", "_apply_filter_layers")
        self.assertLessEqual(lines, 55, f"_apply_filter_layers {lines}行, 应≤55")

    def test_apply_filter_layers_contains_L2_L7(self):
        """_apply_filter_layers应包含L2~L7层调用"""
        m = _get_method(self.tree, "LiveFilterPipeline", "_apply_filter_layers")
        self.assertIsNotNone(m)
        src = ast.get_source_segment(self.src, m)
        self.assertIn("_check_special_period", src)
        self.assertIn("_apply_L3_sentiment", src)
        self.assertIn("_apply_filter_layer", src)
        self.assertIn("_auction_filter", src)
        self.assertIn("_rank_and_dedup", src)

    def test_finalize_traces_exists(self):
        """_finalize_traces方法应存在"""
        m = _get_method(self.tree, "LiveFilterPipeline", "_finalize_traces")
        self.assertIsNotNone(m, "_finalize_traces方法不存在")

    def test_finalize_traces_line_count(self):
        """_finalize_traces行数应≤15"""
        lines = _get_method_lines(self.tree, "LiveFilterPipeline", "_finalize_traces")
        self.assertLessEqual(lines, 15, f"_finalize_traces {lines}行, 应≤15")

    def test_apply_line_count(self):
        """apply方法行数应≤50(v2.9.61:103→~48)"""
        lines = _get_method_lines(self.tree, "LiveFilterPipeline", "apply")
        self.assertLessEqual(lines, 50, f"apply {lines}行, 应≤50")

    def test_apply_delegates_to_apply_filter_layers(self):
        """apply应委托给_apply_filter_layers"""
        m = _get_method(self.tree, "LiveFilterPipeline", "apply")
        src = ast.get_source_segment(self.src, m)
        self.assertIn("_apply_filter_layers", src)

    def test_apply_delegates_to_finalize_traces(self):
        """apply应委托给_finalize_traces"""
        m = _get_method(self.tree, "LiveFilterPipeline", "apply")
        src = ast.get_source_segment(self.src, m)
        self.assertIn("_finalize_traces", src)


class TestEmotionCycleExtraction(unittest.TestCase):
    """emotion_cycle.handle_emotion_phase_change → _execute_emotion_batch_sell + _emit_rebalance_event"""

    def setUp(self):
        self.tree = _parse_tree("emotion_cycle.py")
        self.src = _read_source("emotion_cycle.py")

    def test_execute_emotion_batch_sell_exists(self):
        """_execute_emotion_batch_sell方法应存在"""
        m = _get_method(self.tree, "EmotionCycleManager", "_execute_emotion_batch_sell")
        self.assertIsNotNone(m, "_execute_emotion_batch_sell方法不存在")

    def test_execute_emotion_batch_sell_is_async(self):
        """_execute_emotion_batch_sell应为async"""
        m = _get_method(self.tree, "EmotionCycleManager", "_execute_emotion_batch_sell")
        self.assertIsNotNone(m)
        self.assertIsInstance(m, ast.AsyncFunctionDef)

    def test_execute_emotion_batch_sell_returns_int(self):
        """_execute_emotion_batch_sell应返回int(卖出数量)"""
        m = _get_method(self.tree, "EmotionCycleManager", "_execute_emotion_batch_sell")
        self.assertIsNotNone(m)
        src = ast.get_source_segment(self.src, m)
        self.assertIn("return len(to_sell)", src)

    def test_emit_rebalance_event_exists(self):
        """_emit_rebalance_event方法应存在"""
        m = _get_method(self.tree, "EmotionCycleManager", "_emit_rebalance_event")
        self.assertIsNotNone(m, "_emit_rebalance_event方法不存在")

    def test_emit_rebalance_event_is_async(self):
        """_emit_rebalance_event应为async"""
        m = _get_method(self.tree, "EmotionCycleManager", "_emit_rebalance_event")
        self.assertIsNotNone(m)
        self.assertIsInstance(m, ast.AsyncFunctionDef)

    def test_handle_emotion_phase_change_line_count(self):
        """handle_emotion_phase_change行数应≤50(v2.9.61:64→~47)"""
        lines = _get_method_lines(self.tree, "EmotionCycleManager", "handle_emotion_phase_change")
        self.assertLessEqual(lines, 50, f"handle_emotion_phase_change {lines}行, 应≤50")

    def test_get_prev_trade_date_exists(self):
        """_get_prev_trade_date方法应存在"""
        m = _get_method(self.tree, "EmotionCycleManager", "_get_prev_trade_date")
        self.assertIsNotNone(m, "_get_prev_trade_date方法不存在")

    def test_calc_avg_zt_premium_exists(self):
        """_calc_avg_zt_premium方法应存在"""
        m = _get_method(self.tree, "EmotionCycleManager", "_calc_avg_zt_premium")
        self.assertIsNotNone(m, "_calc_avg_zt_premium方法不存在")

    def test_calculate_zt_premium_line_count(self):
        """_calculate_zt_premium行数应≤15(v2.9.61:54→~12)"""
        lines = _get_method_lines(self.tree, "EmotionCycleManager", "_calculate_zt_premium")
        self.assertLessEqual(lines, 15, f"_calculate_zt_premium {lines}行, 应≤15")


class TestDelegateRouterDispatchTable(unittest.TestCase):
    """scanner_delegate_router.resolve_delegate → _DISPATCH_TABLE路由表"""

    def setUp(self):
        self.src = _read_source("scanner_delegate_router.py")

    def test_dispatch_table_exists(self):
        """_DISPATCH_TABLE应存在"""
        self.assertIn("_DISPATCH_TABLE", self.src)

    def test_dispatch_table_has_entries(self):
        """_DISPATCH_TABLE应包含6个策略"""
        # 检查延迟绑定
        self.assertIn('_DISPATCH_TABLE["_quote_manager_class"]', self.src)
        self.assertIn('_DISPATCH_TABLE["_risk_watchdog_class"]', self.src)
        self.assertIn('_DISPATCH_TABLE["_scanner_utils"]', self.src)
        self.assertIn('_DISPATCH_TABLE["_emotion_cycle_class"]', self.src)
        self.assertIn('_DISPATCH_TABLE["_strategy_param_center_class"]', self.src)
        self.assertIn('_DISPATCH_TABLE["_strategy_scorer"]', self.src)

    def test_resolve_class_method_exists(self):
        """_resolve_class_method函数应存在"""
        self.assertIn("def _resolve_class_method(", self.src)

    def test_resolve_watchdog_exists(self):
        """_resolve_watchdog函数应存在"""
        self.assertIn("def _resolve_watchdog(", self.src)

    def test_resolve_utils_exists(self):
        """_resolve_utils函数应存在"""
        self.assertIn("def _resolve_utils(", self.src)

    def test_resolve_emotion_exists(self):
        """_resolve_emotion函数应存在"""
        self.assertIn("def _resolve_emotion(", self.src)

    def test_resolve_param_center_exists(self):
        """_resolve_param_center函数应存在"""
        self.assertIn("def _resolve_param_center(", self.src)

    def test_resolve_module_delegate_exists(self):
        """_resolve_module_delegate函数应存在"""
        self.assertIn("def _resolve_module_delegate(", self.src)

    def test_resolve_delegate_uses_dispatch_table(self):
        """resolve_delegate应使用_DISPATCH_TABLE"""
        self.assertIn("_DISPATCH_TABLE.get(module_attr)", self.src)

    def test_resolve_delegate_line_count(self):
        """resolve_delegate行数应≤20(v2.9.61:62→~16)"""
        tree = ast.parse(self.src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "resolve_delegate":
                lines = node.end_lineno - node.lineno + 1
                self.assertLessEqual(lines, 20, f"resolve_delegate {lines}行, 应≤20")
                break


class TestTieredScannerExtraction(unittest.TestCase):
    """tiered_scanner._l3_builtin_check → _check_single_position_stop_profit"""

    def setUp(self):
        self.tree = _parse_tree("tiered_scanner.py")
        self.src = _read_source("tiered_scanner.py")

    def test_check_single_position_stop_profit_exists(self):
        """_check_single_position_stop_profit方法应存在"""
        m = _get_method(self.tree, "TieredScanner", "_check_single_position_stop_profit")
        self.assertIsNotNone(m, "_check_single_position_stop_profit方法不存在")

    def test_check_single_returns_sell_signal_or_none(self):
        """_check_single_position_stop_profit应返回Optional[SellSignal]"""
        m = _get_method(self.tree, "TieredScanner", "_check_single_position_stop_profit")
        self.assertIsNotNone(m)
        src = ast.get_source_segment(self.src, m)
        # 应包含stop_loss和take_profit判断
        self.assertIn("stop_loss", src)
        self.assertIn("take_profit", src)
        self.assertIn("return None", src)

    def test_l3_builtin_check_line_count(self):
        """_l3_builtin_check行数应≤20(v2.9.61:58→~17)"""
        lines = _get_method_lines(self.tree, "TieredScanner", "_l3_builtin_check")
        self.assertLessEqual(lines, 20, f"_l3_builtin_check {lines}行, 应≤20")

    def test_l3_builtin_check_delegates(self):
        """_l3_builtin_check应委托给_check_single_position_stop_profit"""
        m = _get_method(self.tree, "TieredScanner", "_l3_builtin_check")
        self.assertIsNotNone(m)
        src = ast.get_source_segment(self.src, m)
        self.assertIn("_check_single_position_stop_profit", src)

    def test_check_single_line_count(self):
        """_check_single_position_stop_profit行数应≤40"""
        lines = _get_method_lines(self.tree, "TieredScanner", "_check_single_position_stop_profit")
        self.assertLessEqual(lines, 40, f"_check_single_position_stop_profit {lines}行, 应≤40")


class TestBrokerMatchExtraction(unittest.TestCase):
    """broker._match → _calc_dynamic_slippage"""

    def setUp(self):
        self.tree = _parse_tree("broker.py")
        self.src = _read_source("broker.py")

    def test_calc_dynamic_slippage_exists(self):
        """_calc_dynamic_slippage方法应存在"""
        m = _get_method(self.tree, "SimulatedBroker", "_calc_dynamic_slippage")
        self.assertIsNotNone(m, "_calc_dynamic_slippage方法不存在")

    def test_calc_dynamic_slippage_returns_float(self):
        """_calc_dynamic_slippage应返回float"""
        m = _get_method(self.tree, "SimulatedBroker", "_calc_dynamic_slippage")
        self.assertIsNotNone(m)
        src = ast.get_source_segment(self.src, m)
        self.assertIn("return slippage", src)

    def test_match_uses_calc_dynamic_slippage(self):
        """_match应调用_calc_dynamic_slippage"""
        m = _get_method(self.tree, "SimulatedBroker", "_match")
        self.assertIsNotNone(m)
        src = ast.get_source_segment(self.src, m)
        self.assertIn("_calc_dynamic_slippage", src)

    def test_match_line_count(self):
        """_match行数应≤30(v2.9.61:57→~28)"""
        lines = _get_method_lines(self.tree, "SimulatedBroker", "_match")
        self.assertLessEqual(lines, 30, f"_match {lines}行, 应≤30")

    def test_calc_dynamic_slippage_line_count(self):
        """_calc_dynamic_slippage行数应≤35"""
        lines = _get_method_lines(self.tree, "SimulatedBroker", "_calc_dynamic_slippage")
        self.assertLessEqual(lines, 35, f"_calc_dynamic_slippage {lines}行, 应≤35")

    def test_slippage_rules_preserved(self):
        """滑点规则应保留(涨停0.5%/0.3%/跌停0.5%/0.3%)"""
        m = _get_method(self.tree, "SimulatedBroker", "_calc_dynamic_slippage")
        self.assertIsNotNone(m)
        src = ast.get_source_segment(self.src, m)
        self.assertIn("0.005", src)  # 0.5%
        self.assertIn("0.003", src)  # 0.3%


class TestRiskWatchdogHeartbeatExtraction(unittest.TestCase):
    """risk_watchdog._check_heartbeat → _judge_startup_heartbeat + _judge_heartbeat_elapsed"""

    def setUp(self):
        self.tree = _parse_tree("risk_watchdog.py")
        self.src = _read_source("risk_watchdog.py")

    def test_judge_startup_heartbeat_exists(self):
        """_judge_startup_heartbeat方法应存在"""
        m = _get_method(self.tree, "RiskWatchdog", "_judge_startup_heartbeat")
        self.assertIsNotNone(m, "_judge_startup_heartbeat方法不存在")

    def test_judge_heartbeat_elapsed_exists(self):
        """_judge_heartbeat_elapsed方法应存在"""
        m = _get_method(self.tree, "RiskWatchdog", "_judge_heartbeat_elapsed")
        self.assertIsNotNone(m, "_judge_heartbeat_elapsed方法不存在")

    def test_check_heartbeat_line_count(self):
        """_check_heartbeat行数应≤15(v2.9.61:51→~13)"""
        lines = _get_method_lines(self.tree, "RiskWatchdog", "_check_heartbeat")
        self.assertLessEqual(lines, 15, f"_check_heartbeat {lines}行, 应≤15")

    def test_judge_startup_returns_health_check(self):
        """_judge_startup_heartbeat应返回HealthCheck"""
        m = _get_method(self.tree, "RiskWatchdog", "_judge_startup_heartbeat")
        self.assertIsNotNone(m)
        src = ast.get_source_segment(self.src, m)
        self.assertIn("HealthCheck(", src)
        self.assertIn("HEALTHY", src)
        self.assertIn("DEAD", src)

    def test_judge_elapsed_returns_health_check(self):
        """_judge_heartbeat_elapsed应返回HealthCheck"""
        m = _get_method(self.tree, "RiskWatchdog", "_judge_heartbeat_elapsed")
        self.assertIsNotNone(m)
        src = ast.get_source_segment(self.src, m)
        self.assertIn("HealthCheck(", src)
        self.assertIn("HEALTHY", src)
        self.assertIn("DEAD", src)
        self.assertIn("DEGRADED", src)


class TestBigMethodsReduction(unittest.TestCase):
    """超过50行方法数应减少"""

    def test_methods_over_50_lines_decreased(self):
        """v2.9.60有18个方法超50行, v2.9.61应≤12"""
        count = 0
        for fname in os.listdir(_NODES_DIR):
            if not fname.endswith('.py') or fname.startswith('__'):
                continue
            fpath = os.path.join(_NODES_DIR, fname)
            with open(fpath) as f:
                tree = ast.parse(f.read())
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    lines = node.end_lineno - node.lineno + 1
                    if lines > 50:
                        count += 1
        self.assertLessEqual(count, 12, f"超50行方法{count}个, 应≤12")


class TestNoBacktestRegressionV2961(unittest.TestCase):
    """回测零影响验证"""

    def test_backtest_files_unchanged(self):
        """回测引擎文件应无修改"""
        backtest_dir = os.path.join(_AGENT_DIR, "nodes", "backtest_engine")
        if not os.path.isdir(backtest_dir):
            self.skipTest("backtest_engine目录不存在")
        # 检查portfolio_backtest.py和sell_signal_checker.py无v2.9.61标记
        for fname in ["portfolio_backtest.py", "sell_signal_checker.py", "strategy_defaults.py"]:
            fpath = os.path.join(backtest_dir, fname)
            if os.path.exists(fpath):
                with open(fpath) as f:
                    content = f.read()
                self.assertNotIn("v2.9.61", content, f"{fname}不应包含v2.9.61标记")

    def test_version_constant(self):
        """_DESIGN_DOC_VERSION应为v2.9.61"""
        scanner_api = os.path.join(_AGENT_DIR, "nodes", "web", "api", "scanner.py")
        with open(scanner_api) as f:
            content = f.read()
        self.assertIn('v2.9.61', content)


if __name__ == "__main__":
    unittest.main()
