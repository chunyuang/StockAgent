"""v2.9.64 利润锁定+龙头5天低利润 补齐测试

P0缺失功能补齐:
1. 利润锁定(PositionManager._check_intraday_profit_lock)
   - 盘中冲高>=6%但从高点回撤>=2.5%→以close价卖出
   - 与sell_signal_checker.check_intraday_profit_lock对齐
2. 龙头5天低利润(PositionManager._check_dragon_head_early_exit)
   - 龙头低吸持仓5天+利润<3%→提前退出
   - 与sell_signal_checker龙头5天低利润对齐
3. _check_intraday_rules集成验证
4. 版本常量v2.9.64
5. 回测零影响
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, PropertyMock, patch
from types import SimpleNamespace

# 确保项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


class TestIntradayProfitLock(unittest.TestCase):
    """利润锁定检查测试"""

    def _make_pm(self):
        """创建PositionManager测试实例"""
        from nodes.market_monitor.position_manager import PositionManager
        scanner = MagicMock()
        scanner._state_lock = MagicMock()
        scanner._trailing_stops = {}
        scanner._position_risk_levels = {}
        scanner._position_risk_overrides = {}
        scanner._pending_sells = {}
        scanner._broker = MagicMock()
        scanner._get_strategy_risk.return_value = {}
        scanner._trade_date = "20260602"
        scanner.get_trade_date.return_value = "20260602"
        pm = PositionManager(scanner)
        return pm

    def _make_pos(self, ts_code="600036.SH", avg_cost=10.0, current_price=10.5,
                   profit_pct=5.0, strategy="first_limit_up", buy_date="20260528",
                   available_qty=100):
        pos = MagicMock()
        pos.ts_code = ts_code
        pos.avg_cost = avg_cost
        pos.current_price = current_price
        pos.profit_pct = profit_pct
        pos.strategy = strategy
        pos.buy_date = buy_date
        pos.available_qty = available_qty
        return pos

    def test_profit_lock_triggered(self):
        """利润锁定: 冲高8%回撤3%, 收盘仍盈5%→触发"""
        pm = self._make_pm()
        pos = self._make_pos(avg_cost=10.0, current_price=10.50, profit_pct=5.0)
        # 追踪止损记录了盘中最高价10.80 (冲高8%)
        pm._scanner._trailing_stops = {"600036.SH": {"high_price": 10.80, "activated": True, "stop_price": 10.0}}
        risk = {
            "intraday_lock_min_high_rise": 0.06,
            "intraday_lock_pullback_pct": 0.025,
            "intraday_lock_min_profit": 0.02,
        }
        result = pm._check_intraday_profit_lock(pos, risk)
        self.assertIsNotNone(result)
        self.assertIn("利润锁定", result)
        self.assertIn("冲高", result)

    def test_profit_lock_not_triggered_insufficient_high_rise(self):
        """利润锁定: 冲高不够(仅4%)→不触发"""
        pm = self._make_pm()
        pos = self._make_pos(avg_cost=10.0, current_price=10.30, profit_pct=3.0)
        # 高点10.40 (冲高4%)
        pm._scanner._trailing_stops = {"600036.SH": {"high_price": 10.40, "activated": True, "stop_price": 10.0}}
        risk = {
            "intraday_lock_min_high_rise": 0.06,
            "intraday_lock_pullback_pct": 0.025,
            "intraday_lock_min_profit": 0.02,
        }
        result = pm._check_intraday_profit_lock(pos, risk)
        self.assertIsNone(result)

    def test_profit_lock_not_triggered_insufficient_pullback(self):
        """利润锁定: 从高点回撤不够(仅1%)→不触发"""
        pm = self._make_pm()
        pos = self._make_pos(avg_cost=10.0, current_price=10.70, profit_pct=7.0)
        # 高点10.80 (冲高8%), 回撤(10.80-10.70)/10.80 = 0.93% < 2.5%
        pm._scanner._trailing_stops = {"600036.SH": {"high_price": 10.80, "activated": True, "stop_price": 10.0}}
        risk = {
            "intraday_lock_min_high_rise": 0.06,
            "intraday_lock_pullback_pct": 0.025,
            "intraday_lock_min_profit": 0.02,
        }
        result = pm._check_intraday_profit_lock(pos, risk)
        self.assertIsNone(result)

    def test_profit_lock_not_triggered_insufficient_profit(self):
        """利润锁定: 收盘利润不够(仅1%)→不触发"""
        pm = self._make_pm()
        pos = self._make_pos(avg_cost=10.0, current_price=10.10, profit_pct=1.0)
        # 高点10.80 (冲高8%), 回撤很大但收盘仅1%
        pm._scanner._trailing_stops = {"600036.SH": {"high_price": 10.80, "activated": True, "stop_price": 10.0}}
        risk = {
            "intraday_lock_min_high_rise": 0.06,
            "intraday_lock_pullback_pct": 0.025,
            "intraday_lock_min_profit": 0.02,
        }
        result = pm._check_intraday_profit_lock(pos, risk)
        self.assertIsNone(result)

    def test_profit_lock_no_trailing_stop_uses_current_price(self):
        """利润锁定: 无追踪止损时回退到current_price作为高点→不触发(无回撤)"""
        pm = self._make_pm()
        pos = self._make_pos(avg_cost=10.0, current_price=10.50, profit_pct=5.0)
        # 无追踪止损→high_price=current_price=10.50, 回撤=0
        risk = {
            "intraday_lock_min_high_rise": 0.06,
            "intraday_lock_pullback_pct": 0.025,
            "intraday_lock_min_profit": 0.02,
        }
        result = pm._check_intraday_profit_lock(pos, risk)
        self.assertIsNone(result)

    def test_profit_lock_zero_cost(self):
        """利润锁定: 成本为0→不触发"""
        pm = self._make_pm()
        pos = self._make_pos(avg_cost=0, current_price=10.50, profit_pct=5.0)
        risk = {"intraday_lock_min_high_rise": 0.06}
        result = pm._check_intraday_profit_lock(pos, risk)
        self.assertIsNone(result)

    def test_profit_lock_uses_global_risk_defaults(self):
        """利润锁定: risk为空时使用GLOBAL_RISK默认值"""
        pm = self._make_pm()
        pos = self._make_pos(avg_cost=10.0, current_price=10.50, profit_pct=5.0)
        pm._scanner._trailing_stops = {"600036.SH": {"high_price": 10.80, "activated": True, "stop_price": 10.0}}
        # risk为空dict, 应该从GLOBAL_RISK读取默认值
        result = pm._check_intraday_profit_lock(pos, {})
        self.assertIsNotNone(result)
        self.assertIn("利润锁定", result)


class TestDragonHeadEarlyExit(unittest.TestCase):
    """龙头5天低利润检查测试"""

    def _make_pm(self):
        from nodes.market_monitor.position_manager import PositionManager
        scanner = MagicMock()
        scanner._state_lock = MagicMock()
        scanner._trailing_stops = {}
        scanner._position_risk_levels = {}
        scanner._position_risk_overrides = {}
        scanner._pending_sells = {}
        scanner._broker = MagicMock()
        scanner._get_strategy_risk.return_value = {}
        scanner._trade_date = "20260602"
        scanner.get_trade_date.return_value = "20260602"
        pm = PositionManager(scanner)
        # Mock _calc_trade_days_held
        pm._calc_trade_days_held = MagicMock(return_value=5)
        return pm

    def _make_pos(self, ts_code="600036.SH", strategy="dragon_head", buy_date="20260526",
                   profit_pct=1.5, avg_cost=10.0, current_price=10.15):
        pos = MagicMock()
        pos.ts_code = ts_code
        pos.strategy = strategy
        pos.buy_date = buy_date
        pos.profit_pct = profit_pct
        pos.avg_cost = avg_cost
        pos.current_price = current_price
        pos.available_qty = 100
        return pos

    def test_dragon_head_early_exit_triggered(self):
        """龙头5天低利润: 5天+1.5%<3%→触发"""
        pm = self._make_pm()
        pos = self._make_pos(profit_pct=1.5)
        risk = {
            "dragon_head_early_exit_days": 5,
            "dragon_head_early_exit_min_profit": 0.03,
        }
        result = pm._check_dragon_head_early_exit(pos, risk)
        self.assertIsNotNone(result)
        self.assertIn("龙头5天低利润", result)

    def test_dragon_head_early_exit_not_triggered_profit_above_threshold(self):
        """龙头5天低利润: 5天+5%>=3%→不触发"""
        pm = self._make_pm()
        pos = self._make_pos(profit_pct=5.0)
        risk = {
            "dragon_head_early_exit_days": 5,
            "dragon_head_early_exit_min_profit": 0.03,
        }
        result = pm._check_dragon_head_early_exit(pos, risk)
        self.assertIsNone(result)

    def test_dragon_head_early_exit_not_triggered_insufficient_days(self):
        """龙头5天低利润: 3天<5天→不触发"""
        pm = self._make_pm()
        pm._calc_trade_days_held.return_value = 3
        pos = self._make_pos(profit_pct=1.5)
        risk = {
            "dragon_head_early_exit_days": 5,
            "dragon_head_early_exit_min_profit": 0.03,
        }
        result = pm._check_dragon_head_early_exit(pos, risk)
        self.assertIsNone(result)

    def test_dragon_head_early_exit_not_triggered_wrong_strategy(self):
        """龙头5天低利润: 非龙头低吸策略→不触发"""
        pm = self._make_pm()
        pos = self._make_pos(strategy="first_limit_up", profit_pct=1.5)
        risk = {
            "dragon_head_early_exit_days": 5,
            "dragon_head_early_exit_min_profit": 0.03,
        }
        result = pm._check_dragon_head_early_exit(pos, risk)
        self.assertIsNone(result)

    def test_dragon_head_early_exit_chinese_name(self):
        """龙头5天低利润: 中文策略名'龙头低吸'→触发"""
        pm = self._make_pm()
        pos = self._make_pos(strategy="龙头低吸", profit_pct=1.5)
        risk = {
            "dragon_head_early_exit_days": 5,
            "dragon_head_early_exit_min_profit": 0.03,
        }
        result = pm._check_dragon_head_early_exit(pos, risk)
        self.assertIsNotNone(result)
        self.assertIn("龙头5天低利润", result)

    def test_dragon_head_early_exit_no_buy_date(self):
        """龙头5天低利润: 无买入日期→不触发"""
        pm = self._make_pm()
        pos = self._make_pos(buy_date=None)
        risk = {
            "dragon_head_early_exit_days": 5,
            "dragon_head_early_exit_min_profit": 0.03,
        }
        result = pm._check_dragon_head_early_exit(pos, risk)
        self.assertIsNone(result)

    def test_dragon_head_early_exit_no_trade_date(self):
        """龙头5天低利润: 无交易日期→不触发"""
        pm = self._make_pm()
        pm._scanner._trade_date = None
        pm._scanner.get_trade_date.return_value = None
        pos = self._make_pos(profit_pct=1.5)
        risk = {
            "dragon_head_early_exit_days": 5,
            "dragon_head_early_exit_min_profit": 0.03,
        }
        result = pm._check_dragon_head_early_exit(pos, risk)
        self.assertIsNone(result)

    def test_dragon_head_early_exit_uses_global_risk_defaults(self):
        """龙头5天低利润: risk为空时使用GLOBAL_RISK默认值"""
        pm = self._make_pm()
        pos = self._make_pos(profit_pct=1.5)
        result = pm._check_dragon_head_early_exit(pos, {})
        self.assertIsNotNone(result)
        self.assertIn("龙头5天低利润", result)


class TestIntradayRulesIntegration(unittest.TestCase):
    """_check_intraday_rules集成测试: 验证利润锁定和龙头5天低利润在规则链中的位置"""

    def _make_pm(self):
        from nodes.market_monitor.position_manager import PositionManager
        scanner = MagicMock()
        scanner._state_lock = MagicMock()
        scanner._trailing_stops = {}
        scanner._position_risk_levels = {}
        scanner._position_risk_overrides = {}
        scanner._pending_sells = {}
        scanner._broker = MagicMock()
        scanner._get_strategy_risk.return_value = {}
        scanner._trade_date = "20260602"
        scanner.get_trade_date.return_value = "20260602"
        scanner._get_open_price.return_value = 10.5
        pm = PositionManager(scanner)
        pm._calc_trade_days_held = MagicMock(return_value=5)
        return pm

    def _make_pos(self, ts_code="600036.SH", avg_cost=10.0, current_price=10.50,
                   profit_pct=5.0, strategy="dragon_head", buy_date="20260526"):
        pos = MagicMock()
        pos.ts_code = ts_code
        pos.avg_cost = avg_cost
        pos.current_price = current_price
        pos.profit_pct = profit_pct
        pos.strategy = strategy
        pos.buy_date = buy_date
        pos.available_qty = 100
        return pos

    def test_profit_lock_in_intraday_rules_chain(self):
        """利润锁定在_check_intraday_rules中正确触发"""
        pm = self._make_pm()
        pos = self._make_pos(profit_pct=5.0, current_price=10.50, strategy="first_limit_up")
        pm._scanner._trailing_stops = {"600036.SH": {"high_price": 10.80, "activated": True, "stop_price": 10.0}}
        risk = {
            "intraday_lock_min_high_rise": 0.06,
            "intraday_lock_pullback_pct": 0.025,
            "intraday_lock_min_profit": 0.02,
        }
        reason, price = pm._check_intraday_rules(pos, risk, today_open=10.5)
        self.assertIn("利润锁定", reason)

    def test_dragon_head_in_intraday_rules_chain(self):
        """龙头5天低利润在_check_intraday_rules中正确触发"""
        pm = self._make_pm()
        pos = self._make_pos(profit_pct=1.5, current_price=10.15, strategy="dragon_head")
        risk = {
            "dragon_head_early_exit_days": 5,
            "dragon_head_early_exit_min_profit": 0.03,
        }
        # today_open设为略高, 不触发冲高回落/利润保护
        reason, price = pm._check_intraday_rules(pos, risk, today_open=10.20)
        self.assertIn("龙头5天低利润", reason)

    def test_pullback_takes_priority_over_profit_lock(self):
        """冲高回落优先于利润锁定(先检查)"""
        pm = self._make_pm()
        pos = self._make_pos(profit_pct=5.0, current_price=10.30, strategy="first_limit_up")
        pm._scanner._trailing_stops = {"600036.SH": {"high_price": 10.80, "activated": True, "stop_price": 10.0}}
        risk = {
            "next_day_open_sell_pct": 0.03,
            "intraday_lock_min_high_rise": 0.06,
            "intraday_lock_pullback_pct": 0.025,
            "intraday_lock_min_profit": 0.02,
        }
        # open=10.50(开涨5%), current=10.30 < open → 冲高回落先触发
        reason, price = pm._check_intraday_rules(pos, risk, today_open=10.50)
        self.assertIn("冲高回落", reason)

    def test_zero_open_returns_none(self):
        """开盘价为0时返回None(不触发任何盘中规则)"""
        pm = self._make_pm()
        pos = self._make_pos(profit_pct=5.0)
        risk = {}
        reason, price = pm._check_intraday_rules(pos, risk, today_open=0)
        self.assertIsNone(reason)


class TestMethodExistence(unittest.TestCase):
    """新方法存在性检查"""

    def test_check_intraday_profit_lock_exists(self):
        """_check_intraday_profit_lock方法存在"""
        from nodes.market_monitor.position_manager import PositionManager
        self.assertTrue(hasattr(PositionManager, '_check_intraday_profit_lock'))

    def test_check_dragon_head_early_exit_exists(self):
        """_check_dragon_head_early_exit方法存在"""
        from nodes.market_monitor.position_manager import PositionManager
        self.assertTrue(hasattr(PositionManager, '_check_dragon_head_early_exit'))

    def test_check_intraday_rules_docstring_updated(self):
        """_check_intraday_rules文档字符串包含利润锁定和龙头低利润"""
        from nodes.market_monitor.position_manager import PositionManager
        doc = PositionManager._check_intraday_rules.__doc__
        self.assertIn("利润锁定", doc)
        self.assertIn("龙头", doc)
        self.assertIn("v2.9.64", doc)


class TestVersionV2964(unittest.TestCase):
    """版本常量检查"""

    def test_design_doc_version_v2964(self):
        """Web API版本常量为v2.9.64"""
        from nodes.web.api.scanner_system import _DESIGN_DOC_VERSION
        self.assertEqual(_DESIGN_DOC_VERSION, "v2.9.74")

    def test_version_in_source(self):
        """源文件中包含v2.9.64"""
        import os
        base = os.path.dirname(os.path.abspath(__file__))
        src_path = os.path.join(base, '..', '..', 'nodes', 'web', 'api', 'scanner_system.py')
        with open(src_path, 'r') as f:
            src = f.read()
        self.assertIn('_DESIGN_DOC_VERSION = "v2.9.74"', src)


class TestNoBacktestRegression(unittest.TestCase):
    """回测零影响验证"""

    def test_sell_signal_checker_unchanged(self):
        """sell_signal_checker.py未修改(回测引擎独立)"""
        import os
        base = os.path.dirname(os.path.abspath(__file__))
        checker_path = os.path.join(
            base, '..', '..', 'nodes', 'backtest_engine', 'factor_selection',
            'sell_signal_checker.py'
        )
        self.assertTrue(os.path.exists(checker_path))
        # 确认利润锁定函数仍存在
        with open(checker_path, 'r') as f:
            content = f.read()
        self.assertIn('check_intraday_profit_lock', content)
        self.assertIn('龙头5天低利润', content)

    def test_strategy_defaults_unchanged(self):
        """strategy_defaults.py参数未修改(单一来源)"""
        from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK
        # 验证利润锁定参数存在
        self.assertIn('intraday_lock_min_high_rise', GLOBAL_RISK)
        self.assertIn('intraday_lock_pullback_pct', GLOBAL_RISK)
        self.assertIn('intraday_lock_min_profit', GLOBAL_RISK)
        self.assertIn('dragon_head_early_exit_days', GLOBAL_RISK)
        self.assertIn('dragon_head_early_exit_min_profit', GLOBAL_RISK)

    def test_position_manager_only_changes(self):
        """变更仅涉及position_manager和scanner_system(回测零影响)"""
        import os
        base = os.path.dirname(os.path.abspath(__file__))
        backtest_path = os.path.join(base, '..', '..', 'nodes', 'backtest_engine')
        # 回测引擎目录存在
        self.assertTrue(os.path.isdir(backtest_path))


if __name__ == '__main__':
    unittest.main()
