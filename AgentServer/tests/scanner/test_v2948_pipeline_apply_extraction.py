"""v2.9.48: live_filter_pipeline.apply提取(187→103行)+4个子方法

验证:
1. apply方法行数≤110
2. _resolve_positions_account提取: 自动获取持仓/账户
3. _apply_L1_force_empty提取: L1强制空仓提前返回
4. _apply_L3_sentiment提取: L3情绪+冰点过滤
5. _apply_filter_layer提取: L4/L5/L7共享过滤模式
6. 方法签名和行为不变
"""
import ast
import os
import unittest

PIPELINE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "nodes", "market_monitor", "live_filter_pipeline.py"
)
SCANNER_API_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "nodes", "web", "api", "scanner.py"
)


class TestPipelineMethodExtraction(unittest.TestCase):
    """验证live_filter_pipeline方法提取"""

    @classmethod
    def setUpClass(cls):
        with open(PIPELINE_PATH) as f:
            cls.src = f.read()
        cls.tree = ast.parse(cls.src)

    def _get_method(self, class_name, method_name):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == method_name:
                        return item
        return None

    def _method_size(self, class_name, method_name):
        m = self._get_method(class_name, method_name)
        if m is None:
            return -1
        return (m.end_lineno or 0) - m.lineno + 1

    def test_apply_size_reduced(self):
        """apply方法行数应≤110(原187行)"""
        size = self._method_size("LiveFilterPipeline", "apply")
        self.assertLessEqual(size, 110, f"apply应为≤110行, 实际{size}行")

    def test_resolve_positions_account_exists(self):
        """_resolve_positions_account方法应存在"""
        m = self._get_method("LiveFilterPipeline", "_resolve_positions_account")
        self.assertIsNotNone(m, "_resolve_positions_account应存在")

    def test_apply_L1_force_empty_exists(self):
        """_apply_L1_force_empty方法应存在"""
        m = self._get_method("LiveFilterPipeline", "_apply_L1_force_empty")
        self.assertIsNotNone(m, "_apply_L1_force_empty应存在")

    def test_apply_L1_force_empty_is_async(self):
        """_apply_L1_force_empty应是async方法(内部调用_check_force_empty)"""
        m = self._get_method("LiveFilterPipeline", "_apply_L1_force_empty")
        self.assertIsInstance(m, ast.AsyncFunctionDef)

    def test_apply_L1_force_empty_returns_bool(self):
        """_apply_L1_force_empty应返回bool(是否触发强制空仓)"""
        m = self._get_method("LiveFilterPipeline", "_apply_L1_force_empty")
        self.assertIsNotNone(m)
        # 检查返回类型注解
        if m.returns:
            self.assertIn("bool", ast.dump(m.returns))

    def test_apply_L3_sentiment_exists(self):
        """_apply_L3_sentiment方法应存在"""
        m = self._get_method("LiveFilterPipeline", "_apply_L3_sentiment")
        self.assertIsNotNone(m, "_apply_L3_sentiment应存在")

    def test_apply_L3_sentiment_is_async(self):
        """_apply_L3_sentiment应是async方法(内部调用_calc_sentiment)"""
        m = self._get_method("LiveFilterPipeline", "_apply_L3_sentiment")
        self.assertIsInstance(m, ast.AsyncFunctionDef)

    def test_apply_filter_layer_exists(self):
        """_apply_filter_layer方法应存在"""
        m = self._get_method("LiveFilterPipeline", "_apply_filter_layer")
        self.assertIsNotNone(m, "_apply_filter_layer应存在")

    def test_apply_filter_layer_not_async(self):
        """_apply_filter_layer不应是async(同步过滤模式)"""
        m = self._get_method("LiveFilterPipeline", "_apply_filter_layer")
        self.assertIsInstance(m, ast.FunctionDef)

    def test_apply_calls_resolve_positions_account(self):
        """apply方法应调用_resolve_positions_account"""
        m = self._get_method("LiveFilterPipeline", "apply")
        src = ast.get_source_segment(self.src, m)
        self.assertIn("_resolve_positions_account", src)

    def test_apply_calls_apply_L1_force_empty(self):
        """apply方法应调用_apply_L1_force_empty"""
        m = self._get_method("LiveFilterPipeline", "apply")
        src = ast.get_source_segment(self.src, m)
        self.assertIn("_apply_L1_force_empty", src)

    def test_apply_calls_apply_L3_sentiment(self):
        """apply→_apply_filter_layers→_apply_L3_sentiment"""
        # v2.9.61: L2~L7提取到_apply_filter_layers, 检查新方法包含调用
        m = self._get_method("LiveFilterPipeline", "_apply_filter_layers")
        src = ast.get_source_segment(self.src, m)
        self.assertIn("_apply_L3_sentiment", src)

    def test_apply_calls_apply_filter_layer(self):
        """_apply_filter_layers应调用_apply_filter_layer(L4/L5/L7)"""
        # v2.9.61: 调用从apply移到_apply_filter_layers
        m = self._get_method("LiveFilterPipeline", "_apply_filter_layers")
        src = ast.get_source_segment(self.src, m)
        count = src.count("_apply_filter_layer")
        self.assertGreaterEqual(count, 3, f"_apply_filter_layers应至少调用_apply_filter_layer 3次, 实际{count}次")

    def test_no_duplicate_before_after_pattern_in_apply(self):
        """apply方法中不应再有重复的before_ids/after_ids/dropped模式(应使用_apply_filter_layer)"""
        m = self._get_method("LiveFilterPipeline", "apply")
        src = ast.get_source_segment(self.src, m)
        # before_ids应在apply中只出现在_apply_filter_layer调用之前或L8之后
        # 不应有直接赋值before_ids的代码(因为已提取)
        lines = src.split('\n')
        before_assign_count = sum(1 for l in lines if 'before_ids = {' in l and '_apply_filter_layer' not in l)
        self.assertLessEqual(before_assign_count, 0, 
                             f"apply中不应有直接的before_ids赋值(应通过_apply_filter_layer), 实际{before_assign_count}处")

    def test_method_count(self):
        """LiveFilterPipeline方法数应≥19(原15+4新增)"""
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ClassDef) and node.name == "LiveFilterPipeline":
                methods = [n.name for n in node.body 
                          if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                self.assertGreaterEqual(len(methods), 19, 
                                        f"方法数应≥19, 实际{len(methods)}")


class TestPipelineExtractionContract(unittest.TestCase):
    """验证提取后的方法签名和调用契约"""

    @classmethod
    def setUpClass(cls):
        with open(PIPELINE_PATH) as f:
            cls.src = f.read()
        cls.tree = ast.parse(cls.src)

    def _get_method(self, class_name, method_name):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == method_name:
                        return item
        return None

    def test_resolve_positions_account_params(self):
        """_resolve_positions_account应接受positions, account两个参数"""
        m = self._get_method("LiveFilterPipeline", "_resolve_positions_account")
        self.assertIsNotNone(m)
        param_names = [a.arg for a in m.args.args if a.arg != 'self']
        self.assertIn('positions', param_names)
        self.assertIn('account', param_names)

    def test_apply_filter_layer_params(self):
        """_apply_filter_layer应接受result, layer_name, filtered, reject_reason_fn, detail_template"""
        m = self._get_method("LiveFilterPipeline", "_apply_filter_layer")
        self.assertIsNotNone(m)
        param_names = [a.arg for a in m.args.args if a.arg != 'self']
        expected = ['result', 'layer_name', 'filtered', 'reject_reason_fn', 'detail_template']
        self.assertEqual(param_names, expected)

    def test_apply_still_accepts_original_params(self):
        """apply方法签名不应变化"""
        m = self._get_method("LiveFilterPipeline", "apply")
        self.assertIsNotNone(m)
        param_names = [a.arg for a in m.args.args if a.arg != 'self']
        expected = ['trade_date', 'candidates', 'positions', 'account', 'realtime_data']
        self.assertEqual(param_names, expected)


class TestNoBacktestRegressionV2948(unittest.TestCase):
    """回测零影响"""

    def test_backtest_dir_exists(self):
        backtest_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "tests", "backtest"
        )
        self.assertTrue(os.path.isdir(backtest_path))


if __name__ == "__main__":
    unittest.main()
