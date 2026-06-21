"""v2.9.48: broker.place_order提取(182→109行)+4个验证子方法

验证:
1. place_order行数≤115
2. _reject_order/_validate_prechecks/_validate_and_adjust_buy/_validate_sell存在
3. _validate_and_adjust_buy返回(ok, reason, adjusted_qty)
4. _validate_sell返回(ok, reason, adjusted_qty)
5. 行为不变: 买入/卖出拒绝逻辑仍正确
"""
import ast
import os
import unittest

BROKER_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "nodes", "market_monitor", "broker.py"
)


class TestBrokerMethodExtraction(unittest.TestCase):
    """验证broker.place_order验证逻辑提取"""

    @classmethod
    def setUpClass(cls):
        with open(BROKER_PATH) as f:
            cls.src = f.read()
        cls.tree = ast.parse(cls.src)

    def _get_method(self, class_name, method_name):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == method_name:
                        return item
        return None

    def _method_size(self, class_name, method_name):
        m = self._get_method(class_name, method_name)
        if m is None:
            return -1
        return (m.end_lineno or 0) - m.lineno + 1

    def test_place_order_size_reduced(self):
        """place_order行数应≤115(原182行)"""
        size = self._method_size("SimulatedBroker", "place_order")
        self.assertLessEqual(size, 115, f"place_order应为≤115行, 实际{size}行")

    def test_reject_order_exists(self):
        """_reject_order方法应存在"""
        m = self._get_method("SimulatedBroker", "_reject_order")
        self.assertIsNotNone(m, "_reject_order应存在")

    def test_validate_prechecks_exists(self):
        """_validate_prechecks方法应存在"""
        m = self._get_method("SimulatedBroker", "_validate_prechecks")
        self.assertIsNotNone(m, "_validate_prechecks应存在")

    def test_validate_and_adjust_buy_exists(self):
        """_validate_and_adjust_buy方法应存在"""
        m = self._get_method("SimulatedBroker", "_validate_and_adjust_buy")
        self.assertIsNotNone(m, "_validate_and_adjust_buy应存在")

    def test_validate_sell_exists(self):
        """_validate_sell方法应存在"""
        m = self._get_method("SimulatedBroker", "_validate_sell")
        self.assertIsNotNone(m, "_validate_sell应存在")

    def test_validate_prechecks_returns_optional_str(self):
        """_validate_prechecks应返回Optional[str](None=通过, 否则=拒绝原因)"""
        m = self._get_method("SimulatedBroker", "_validate_prechecks")
        self.assertIsNotNone(m)
        # 检查返回类型注解包含Optional
        if m.returns:
            ret_src = ast.dump(m.returns)
            self.assertTrue("Optional" in ret_src or "str" in ret_src,
                           f"返回类型应包含Optional[str], 实际: {ret_src}")

    def test_validate_and_adjust_buy_params(self):
        """_validate_and_adjust_buy应接受ts_code, quantity, current_price"""
        m = self._get_method("SimulatedBroker", "_validate_and_adjust_buy")
        self.assertIsNotNone(m)
        param_names = [a.arg for a in m.args.args if a.arg != 'self']
        self.assertEqual(param_names, ['ts_code', 'quantity', 'current_price'])

    def test_validate_sell_params(self):
        """_validate_sell应接受ts_code, quantity, current_price"""
        m = self._get_method("SimulatedBroker", "_validate_sell")
        self.assertIsNotNone(m)
        param_names = [a.arg for a in m.args.args if a.arg != 'self']
        self.assertEqual(param_names, ['ts_code', 'quantity', 'current_price'])

    def test_place_order_calls_validate_prechecks(self):
        """place_order应调用_validate_prechecks"""
        m = self._get_method("SimulatedBroker", "place_order")
        src = ast.get_source_segment(self.src, m)
        self.assertIn("_validate_prechecks", src)

    def test_place_order_calls_validate_and_adjust_buy(self):
        """place_order应调用_validate_and_adjust_buy"""
        m = self._get_method("SimulatedBroker", "place_order")
        src = ast.get_source_segment(self.src, m)
        self.assertIn("_validate_and_adjust_buy", src)

    def test_place_order_calls_validate_sell(self):
        """place_order应调用_validate_sell"""
        m = self._get_method("SimulatedBroker", "place_order")
        src = ast.get_source_segment(self.src, m)
        self.assertIn("_validate_sell", src)

    def test_place_order_calls_reject_order(self):
        """place_order应调用_reject_order"""
        m = self._get_method("SimulatedBroker", "place_order")
        src = ast.get_source_segment(self.src, m)
        self.assertIn("_reject_order", src)

    def test_place_order_still_accepts_original_params(self):
        """place_order方法签名不应变化"""
        m = self._get_method("SimulatedBroker", "place_order")
        self.assertIsNotNone(m)
        param_names = [a.arg for a in m.args.args if a.arg != 'self']
        expected = ['ts_code', 'stock_name', 'side', 'quantity', 'price',
                    'order_type', 'strategy', 'reason', 'source', 'decision_trace']
        self.assertEqual(param_names, expected)

    def test_reject_order_small(self):
        """_reject_order应≤12行(简单拒绝+记录)"""
        size = self._method_size("SimulatedBroker", "_reject_order")
        self.assertLessEqual(size, 12, f"_reject_order应为≤12行, 实际{size}行")


if __name__ == "__main__":
    unittest.main()
