"""
Test Thread Safety & Optimization — v2.5回归测试

验证:
1. PositionManager.check_stop_loss_take_profit 线程安全读取trailing_stops
2. PositionChecker._get_backtester 缓存实例
3. PositionChecker._calc_trade_days_held 缓存Backtester
4. PositionManager._get_trailing_stop_safe 深拷贝读取
5. PositionManager.check_moving_stop 线程安全读取覆盖参数
"""

import os
import sys
import threading
import time
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


class MockPosition:
    """模拟持仓对象"""
    def __init__(self, ts_code='600036.SH', strategy='涨停打板',
                 avg_cost=40.0, current_price=39.5, profit_pct=-1.25,
                 available_qty=100, stock_name='招商银行', buy_date='20260520'):
        self.ts_code = ts_code
        self.strategy = strategy
        self.avg_cost = avg_cost
        self.current_price = current_price
        self.profit_pct = profit_pct
        self.available_qty = available_qty
        self.stock_name = stock_name
        self.buy_date = buy_date


class TestPositionManagerThreadSafety:
    """PositionManager线程安全读取"""

    @pytest.fixture
    def position_manager(self):
        """创建PositionManager实例"""
        from nodes.market_monitor.position_manager import PositionManager

        scanner = MagicMock()
        scanner._trailing_stops = {}
        scanner._pending_sells = {}
        scanner._position_risk_levels = {}
        scanner._position_risk_overrides = {}
        scanner._state_lock = threading.Lock()
        scanner._get_strategy_risk.return_value = {
            'stop_loss_pct': 0.03,
            'take_profit_pct': 0.07,
            'trailing_stop_pct': 0.05,
        }
        scanner._is_limit_down.return_value = False
        scanner._get_open_price.return_value = 0.0

        broker = MagicMock()
        broker.get_positions.return_value = []
        scanner._broker = broker

        return PositionManager(scanner)

    def test_get_trailing_stop_safe_returns_copy(self, position_manager):
        """_get_trailing_stop_safe 返回深拷贝, 修改不影响原状态"""
        with position_manager.state_lock:
            position_manager.trailing_stops['600036.SH'] = {
                'stop_price': 40.17,
                'activated': True,
                'high_price': 41.2,
            }

        copy = position_manager._get_trailing_stop_safe('600036.SH')
        assert copy is not None
        assert copy['stop_price'] == 40.17

        # 修改拷贝不影响原始
        copy['stop_price'] = 99.99
        with position_manager.state_lock:
            original = position_manager.trailing_stops['600036.SH']
        assert original['stop_price'] == 40.17, "修改拷贝不应影响原始数据"

    def test_get_trailing_stop_safe_missing_key(self, position_manager):
        """_get_trailing_stop_safe 对不存在的key返回None"""
        result = position_manager._get_trailing_stop_safe('999999.SH')
        assert result is None

    def test_concurrent_trailing_stop_reads(self, position_manager):
        """并发读取trailing_stops不应crash"""
        with position_manager.state_lock:
            for i in range(50):
                position_manager.trailing_stops[f'{600000+i:06d}.SH'] = {
                    'stop_price': 40.0 + i * 0.1,
                    'activated': True,
                }

        errors = []

        def reader():
            try:
                for _ in range(100):
                    for i in range(50):
                        result = position_manager._get_trailing_stop_safe(f'{600000+i:06d}.SH')
                        if result is not None:
                            assert 'stop_price' in result
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=reader) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"并发读取crash: {errors}"

    def test_check_stop_loss_take_profit_trailing_safe(self, position_manager):
        """check_stop_loss_take_profit通过深拷贝读取trailing_stops(不直接引用)"""
        with position_manager.state_lock:
            position_manager.trailing_stops['600036.SH'] = {
                'stop_price': 39.5,
                'activated': True,
                'high_price': 41.2,
                'trailing_stop_pct': 0.05,
            }

        pos = MockPosition(ts_code='600036.SH', current_price=39.4, profit_pct=-1.5, avg_cost=40.0)
        position_manager.broker.get_positions.return_value = [pos]

        result = position_manager.check_stop_loss_take_profit([pos], {})
        # 追踪止损应该被触发
        assert len(result) > 0, "追踪止损应触发卖出"
        assert '追踪止损' in result[0][1]

    def test_check_moving_stop_locks_overrides(self, position_manager):
        """check_moving_stop读取覆盖参数时加锁"""
        with position_manager.state_lock:
            position_manager.position_risk_overrides['600036.SH'] = {
                'stop_loss_pct': 0.05,
            }

        # 盈利曾>2*SL(10%)但回撤到0以下 → 移动止损
        pos = MockPosition(ts_code='600036.SH', avg_cost=40.0, current_price=39.8,
                          profit_pct=-0.5, available_qty=100)
        result = position_manager.check_moving_stop([pos])
        # 不crash即可(具体触发取决于profit_pct和sl_pct的关系)
        assert isinstance(result, list)


class TestPositionCheckerBacktesterCache:
    """PositionChecker缓存PortfolioBacktester实例"""

    @pytest.fixture
    def checker(self):
        """创建PositionChecker实例"""
        from nodes.market_monitor.position_checker import PositionChecker

        scanner = MagicMock()
        scanner.SELL_LOGIC_MODE = 'legacy'
        scanner._dry_run = True
        scanner._realtime_cache = {}
        scanner._trailing_stops = {}
        scanner._position_risk_levels = {}
        scanner._pending_sells = {}
        scanner._state_lock = threading.Lock()
        scanner._execution_stats = {}
        scanner._get_strategy_risk.return_value = {
            'stop_loss_pct': 0.03,
            'take_profit_pct': 0.07,
        }
        scanner._check_stop_loss_take_profit.return_value = []
        scanner._check_circuit_breaker = AsyncMock(return_value=True)
        scanner._save_runtime_snapshot = AsyncMock()
        scanner._publish_scanner_event = AsyncMock()
        scanner._add_timeline_log = MagicMock()

        broker = MagicMock()
        broker.get_positions.return_value = []
        scanner._broker = broker
        scanner._data_router = None

        return PositionChecker(scanner)

    def test_backtester_cached(self, checker):
        """_get_backtester应缓存实例, 多次调用返回同一对象"""
        bt1 = checker._get_backtester()
        bt2 = checker._get_backtester()
        assert bt1 is bt2, "PortfolioBacktester应被缓存, 但返回了不同实例"

    def test_calc_trade_days_held(self, checker):
        """_calc_trade_days_held使用缓存的Backtester"""
        result = checker._calc_trade_days_held('20260520', '20260528')
        assert result is not None, "_calc_trade_days_held应返回有效结果"
        assert isinstance(result, int)

    def test_calc_trade_days_held_invalid(self, checker):
        """_calc_trade_days_held对无效输入返回None"""
        result = checker._calc_trade_days_held('invalid', '20260528')
        assert result is None, "无效输入应返回None"

    def test_calc_trade_days_held_cached(self, checker):
        """_calc_trade_days_held多次调用使用同一Backtester"""
        # 先预热缓存
        checker._calc_trade_days_held('20260520', '20260528')
        bt_cached = checker._backtester

        # 再次调用
        result = checker._calc_trade_days_held('20260519', '20260528')
        assert checker._backtester is bt_cached, "Backtester实例不应被替换"


class TestPositionCheckerPropertiesSafety:
    """PositionChecker属性安全性"""

    def test_trailing_stops_property_documented(self):
        """trailing_stops属性有文档说明(仅用于内部加锁场景)"""
        from nodes.market_monitor.position_checker import PositionChecker
        doc = PositionChecker.trailing_stops.fget.__doc__
        assert doc is not None, "trailing_stops属性缺少文档"
        assert '内部' in doc or '加锁' in doc, "trailing_stops属性文档应说明仅在加锁场景使用"

    def test_realtime_cache_property_documented(self):
        """realtime_cache属性有文档说明"""
        from nodes.market_monitor.position_checker import PositionChecker
        doc = PositionChecker.realtime_cache.fget.__doc__
        assert doc is not None, "realtime_cache属性缺少文档"
        assert '内部' in doc or '加锁' in doc or '直接引用' in doc


class TestNoBacktestRegression:
    """验证回测模块不受此次修改影响"""

    def test_sell_signal_checker_api_unchanged(self):
        """SellSignalChecker API未变"""
        from nodes.backtest_engine.factor_selection.sell_signal_checker import SellSignalChecker
        from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS, GLOBAL_RISK

        strategy_params = {}
        strategy_risk_params = {}
        for k, cfg in STRATEGY_CONFIGS.items():
            strategy_params[k] = cfg.get("params", {})
            strategy_risk_params[k] = cfg.get("riskParams", {})

        checker = SellSignalChecker(strategy_params, strategy_risk_params, dict(GLOBAL_RISK))
        assert hasattr(checker, 'check_realtime_sell')
        assert hasattr(checker, 'check_early_sell')

    def test_strategy_defaults_importable(self):
        """strategy_defaults模块正常导入"""
        from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS, GLOBAL_RISK
        assert isinstance(STRATEGY_CONFIGS, dict)
        assert isinstance(GLOBAL_RISK, dict)
