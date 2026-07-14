"""
v2.9.123 跳空止损分级观察期测试

核心验证:
1. gap_pct基准是pre_close(昨收), 不是avg_cost(买入成本)
2. 微跳空(<3%) -> 30分钟观察期, 不立即执行
3. 中跳空(3-5%) -> 10分钟观察期, 不立即执行
4. 大跳空(>5%) -> 立即执行
5. 观察期内价格回升到止损线上 -> cancel
6. pre_close缺失时fallback到avg_cost
7. 卖出reason字符串显示昨收价和真实跳空幅度

历史教训:
- v2.9.112引入时gap_pct用avg_cost, 导致已亏损股永远被判定为大跳空
- 7/14实际影响: 5只微跳空(0.1%~2.8%)被立即止损, 少赚5000元
"""
import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch


class TestGapStopTieredObservation:
    """测试_check_gap_stop_with_tiered_observation方法"""

    def _make_position_manager(self):
        """构造PositionManager实例"""
        from nodes.market_monitor.position_manager import PositionManager
        import threading

        class MockScanner:
            SELL_LOGIC_MODE = "legacy"
            _trailing_stops = {}
            _pending_sells = {}
            _position_risk_levels = {}
            _position_risk_overrides = {}
            _state_lock = threading.Lock()
            _trade_date = "20260714"
            _realtime_cache = {}

            def _get_strategy_risk(self, strategy):
                return {"stop_loss_pct": 0.03, "take_profit_pct": 0.07,
                        "trailing_stop_pct": 0.02}

            def _get_open_price(self, ts_code):
                return 10.0

            def _is_limit_down(self, ts_code):
                return False

            def get_trade_date(self):
                return self._trade_date

        return PositionManager(MockScanner())

    # ========== gap_pct基准测试 ==========

    def test_gap_pct_uses_pre_close_not_avg_cost(self):
        """【P0】gap_pct必须用pre_close, 不是avg_cost

        场景: avg_cost=45.59, pre_close=43.01, open=43.11
        - 用avg_cost: gap=|43.11-45.59|/45.59=5.4% -> 大跳(立即止损) ❌
        - 用pre_close: gap=|43.11-43.01|/43.01=0.2% -> 微跳(30分观察) ✅
        """
        pm = self._make_position_manager()
        with patch('datetime.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 14, 9, 45, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = pm._check_gap_stop_with_tiered_observation(
                ts_code="603127.SH",
                avg_cost=45.59,
                today_open=43.11,
                stop_loss_price=43.54,
                current_price=43.0,
                pre_close=43.01,
            )
        # 0.2%是微跳空, 在观察期内应返回observe
        assert result == "observe", \
            f"微跳空0.2%应进入观察期, 但返回了{result}(gap_pct基准可能用错了avg_cost)"

    def test_gap_pct_micro_gap_with_large_loss(self):
        """微跳空+大浮亏: 必须进入观察期

        场景: avg_cost=75.42(买入价高), pre_close=73.57, open=71.49
        - 用avg_cost: gap=|71.49-75.42|/75.42=5.2% -> 大跳(立即) ❌
        - 用pre_close: gap=|71.49-73.57|/73.57=2.8% -> 微跳(30分) ✅
        这是7/14通富微电的真实case
        """
        pm = self._make_position_manager()
        with patch('datetime.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 14, 9, 45, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = pm._check_gap_stop_with_tiered_observation(
                ts_code="002156.SZ",
                avg_cost=75.42,
                today_open=71.49,
                stop_loss_price=72.03,
                current_price=71.0,
                pre_close=73.57,
            )
        assert result == "observe", \
            f"通富微电场景: 微跳空2.8%应观察, 返回了{result}"

    def test_gap_pct_large_gap_immediate_execute(self):
        """大跳空(>5% vs pre_close) -> 立即执行"""
        pm = self._make_position_manager()
        # patch _get_market_bread返回0(大盘不强势), 确保走立即执行路径
        with patch.object(pm, '_get_market_bread', return_value=0.0):
            result = pm._check_gap_stop_with_tiered_observation(
                ts_code="000001.SZ",
                avg_cost=10.0,
                today_open=9.4,      # open vs pre_close = -6%
                stop_loss_price=9.7,
                current_price=9.4,
                pre_close=10.0,
            )
        assert result == "execute", f"大跳空6%应立即执行, 返回了{result}"

    def test_gap_pct_medium_gap_observe(self):
        """中跳空(3-5% vs pre_close) -> 10分钟观察期"""
        pm = self._make_position_manager()
        with patch('datetime.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 14, 9, 35, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = pm._check_gap_stop_with_tiered_observation(
                ts_code="000001.SZ",
                avg_cost=10.0,
                today_open=9.6,      # open vs pre_close = -4%
                stop_loss_price=9.7,
                current_price=9.5,
                pre_close=10.0,
            )
        assert result == "observe", f"中跳空4%应观察, 返回了{result}"

    # ========== 观察期时间窗口测试 ==========

    def test_micro_gap_observe_during_30min_window(self):
        """微跳空在9:30-10:00内 -> observe"""
        pm = self._make_position_manager()
        with patch('datetime.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 14, 9, 45, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = pm._check_gap_stop_with_tiered_observation(
                ts_code="000001.SZ",
                avg_cost=10.0,
                today_open=9.9,      # -1% vs pre_close, 微跳
                stop_loss_price=9.7,
                current_price=9.5,   # 仍低于止损价
                pre_close=10.0,
            )
        assert result == "observe"

    def test_micro_gap_execute_after_30min_window(self):
        """微跳空在10:01后(观察期结束) -> execute(如果价格仍低于止损)"""
        pm = self._make_position_manager()
        with patch('datetime.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 14, 10, 1, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = pm._check_gap_stop_with_tiered_observation(
                ts_code="000001.SZ",
                avg_cost=10.0,
                today_open=9.9,
                stop_loss_price=9.7,
                current_price=9.5,   # 仍低于止损价
                pre_close=10.0,
            )
        assert result == "execute", f"观察期结束后仍低于止损应执行, 返回了{result}"

    def test_micro_gap_cancel_if_price_recovers(self):
        """微跳空在观察期内价格回升到止损线上 -> cancel"""
        pm = self._make_position_manager()
        result = pm._check_gap_stop_with_tiered_observation(
            ts_code="000001.SZ",
            avg_cost=10.0,
            today_open=9.9,       # -1% vs pre_close, 微跳
            stop_loss_price=9.7,
            current_price=9.8,    # 已回升到止损线上
            pre_close=10.0,
        )
        assert result == "cancel"

    def test_medium_gap_observe_during_10min_window(self):
        """中跳空在9:30-9:40内 -> observe"""
        pm = self._make_position_manager()
        with patch('datetime.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 14, 9, 35, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = pm._check_gap_stop_with_tiered_observation(
                ts_code="000001.SZ",
                avg_cost=10.0,
                today_open=9.6,      # -4% vs pre_close, 中跳
                stop_loss_price=9.7,
                current_price=9.5,
                pre_close=10.0,
            )
        assert result == "observe"

    def test_medium_gap_execute_after_10min_window(self):
        """中跳空在9:41后(观察期结束) -> execute"""
        pm = self._make_position_manager()
        with patch('datetime.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 14, 9, 41, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = pm._check_gap_stop_with_tiered_observation(
                ts_code="000001.SZ",
                avg_cost=10.0,
                today_open=9.6,
                stop_loss_price=9.7,
                current_price=9.5,
                pre_close=10.0,
            )
        assert result == "execute"

    # ========== fallback测试 ==========

    def test_fallback_to_avg_cost_when_no_pre_close(self):
        """pre_close=0时fallback到avg_cost"""
        pm = self._make_position_manager()
        with patch.object(pm, '_get_market_bread', return_value=0.0):
            # avg_cost=10, open=9.4 -> gap=6% via avg_cost fallback
            result = pm._check_gap_stop_with_tiered_observation(
                ts_code="000001.SZ",
                avg_cost=10.0,
                today_open=9.4,
                stop_loss_price=9.7,
                current_price=9.4,
                pre_close=0,  # 无昨收价
            )
        # fallback到avg_cost, gap=6% -> 大跳 -> execute
        assert result == "execute"

    def test_fallback_when_pre_close_none(self):
        """pre_close参数不传(默认值)时也能正常工作"""
        pm = self._make_position_manager()
        with patch.object(pm, '_get_market_bread', return_value=0.0):
            # 不传pre_close, 使用默认值0
            result = pm._check_gap_stop_with_tiered_observation(
                ts_code="000001.SZ",
                avg_cost=10.0,
                today_open=9.4,      # gap=6% via avg_cost
                stop_loss_price=9.7,
                current_price=9.4,
            )
        assert result == "execute"

    # ========== 集成测试: check_stop_loss_take_profit ==========

    def test_integration_micro_gap_does_not_trigger_immediate_stop(self):
        """集成测试: 微跳空+大浮亏不触发立即止损(7/14昭衍新药场景)

        avg_cost=45.59, pre_close=43.01, open=43.11, stop_loss=43.54
        旧逻辑(用avg_cost): gap=5.4% -> 大跳 -> 立即止损 ❌
        新逻辑(用pre_close): gap=0.2% -> 微跳 -> 观察 ✅
        """
        from nodes.market_monitor.position_manager import PositionManager
        import threading

        class MockPos:
            ts_code = "603127.SH"
            strategy = "halfway_chase"
            stock_name = "昭衍新药"
            avg_cost = 45.59
            current_price = 43.0
            profit_pct = -5.7
            available_qty = 800
            total_qty = 800
            buy_date = "20260711"

        class MockScanner:
            SELL_LOGIC_MODE = "legacy"
            _trailing_stops = {}
            _pending_sells = {}
            _position_risk_levels = {}
            _position_risk_overrides = {}
            _state_lock = threading.Lock()
            _trade_date = "20260714"
            _realtime_cache = {}

            def _get_strategy_risk(self, strategy):
                return {"stop_loss_pct": 0.03, "take_profit_pct": 0.07,
                        "trailing_stop_pct": 0.02}

            def _get_open_price(self, ts_code):
                return 43.11

            def _is_limit_down(self, ts_code):
                return False

            def get_trade_date(self):
                return "20260714"

        pm = PositionManager(MockScanner())
        pos = MockPos()
        rt = {"603127.SH": {"open": 43.11, "pre_close": 43.01, "price": 43.0}}

        with patch('datetime.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 14, 9, 45, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = pm.check_stop_loss_take_profit([pos], rt)
        # 微跳空0.2%应进入观察期, 不返回卖出信号
        assert len(result) == 0, \
            f"微跳空0.2%应观察不卖出, 但返回了{len(result)}个卖出信号"

    def test_integration_large_gap_triggers_stop(self):
        """集成测试: 真正的大跳空(>5% vs pre_close)触发止损"""
        from nodes.market_monitor.position_manager import PositionManager
        import threading

        class MockPos:
            ts_code = "000001.SZ"
            strategy = "halfway_chase"
            stock_name = "测试股"
            avg_cost = 10.0
            current_price = 9.3
            profit_pct = -7.0
            available_qty = 100
            total_qty = 100
            buy_date = "20260711"

        class MockScanner:
            SELL_LOGIC_MODE = "legacy"
            _trailing_stops = {}
            _pending_sells = {}
            _position_risk_levels = {}
            _position_risk_overrides = {}
            _state_lock = threading.Lock()
            _trade_date = "20260714"
            _realtime_cache = {}

            def _get_strategy_risk(self, strategy):
                return {"stop_loss_pct": 0.03, "take_profit_pct": 0.07,
                        "trailing_stop_pct": 0.02}

            def _get_open_price(self, ts_code):
                return 9.4

            def _is_limit_down(self, ts_code):
                return False

            def get_trade_date(self):
                return "20260714"

        pm = PositionManager(MockScanner())
        pos = MockPos()
        # open=9.4 vs pre_close=10.0 = -6% 大跳空
        rt = {"000001.SZ": {"open": 9.4, "pre_close": 10.0, "price": 9.3}}

        with patch.object(pm, '_get_market_bread', return_value=0.0):
            result = pm.check_stop_loss_take_profit([pos], rt)
        assert len(result) == 1
        assert "跳空" in result[0][1]

    # ========== 回归测试: 确保修复后旧case仍然工作 ==========

    def test_regression_normal_gap_stop_still_works(self):
        """回归: 正常跳空止损(open远低于止损价)仍然触发"""
        from nodes.market_monitor.position_manager import PositionManager
        import threading

        class MockPos:
            ts_code = "000001.SZ"
            strategy = "halfway_chase"
            stock_name = "测试股"
            avg_cost = 10.0
            current_price = 9.0
            profit_pct = -10.0
            available_qty = 100
            total_qty = 100
            buy_date = "20260711"

        class MockScanner:
            SELL_LOGIC_MODE = "legacy"
            _trailing_stops = {}
            _pending_sells = {}
            _position_risk_levels = {}
            _position_risk_overrides = {}
            _state_lock = threading.Lock()
            _trade_date = "20260714"
            _realtime_cache = {}

            def _get_strategy_risk(self, strategy):
                return {"stop_loss_pct": 0.03, "take_profit_pct": 0.07,
                        "trailing_stop_pct": 0.02}

            def _get_open_price(self, ts_code):
                return 9.0

            def _is_limit_down(self, ts_code):
                return False

            def get_trade_date(self):
                return "20260714"

        pm = PositionManager(MockScanner())
        pos = MockPos()
        # open=9.0 vs pre_close=10.0 = -10% 大跳空
        rt = {"000001.SZ": {"open": 9.0, "pre_close": 10.0, "price": 9.0}}

        with patch.object(pm, '_get_market_bread', return_value=0.0):
            result = pm.check_stop_loss_take_profit([pos], rt)
        assert len(result) == 1
        assert "跳空" in result[0][1]

    def test_regression_existing_gap_stop_test_with_pre_close(self):
        """回归: 原有test_check_gap_stop_loss加上pre_close后仍然通过"""
        from nodes.market_monitor.position_manager import PositionManager
        import threading

        class MockPos:
            ts_code = "600036.SH"
            strategy = "halfway_chase"
            stock_name = "测试股"
            avg_cost = 10.0
            current_price = 9.3
            profit_pct = -7.0
            available_qty = 100
            total_qty = 100
            buy_date = "20260528"

        class MockScanner:
            SELL_LOGIC_MODE = "legacy"
            _trailing_stops = {}
            _pending_sells = {}
            _position_risk_levels = {}
            _position_risk_overrides = {}
            _state_lock = threading.Lock()
            _trade_date = "20260602"
            _realtime_cache = {}

            def _get_strategy_risk(self, strategy):
                return {"stop_loss_pct": 0.03, "take_profit_pct": 0.07,
                        "trailing_stop_pct": 0.02}

            def _get_open_price(self, ts_code):
                return 10.0

            def _is_limit_down(self, ts_code):
                return False

            def get_trade_date(self):
                return "20260602"

        pm = PositionManager(MockScanner())
        pos = MockPos()
        # open=9.6 vs pre_close=10.0 = -4% 中跳空
        rt = {"600036.SH": {"open": 9.6, "pre_close": 10.0}}
        with patch('datetime.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 14, 9, 35, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = pm.check_stop_loss_take_profit([pos], rt)
        # 中跳空4%, 在9:35处于10分钟观察期内, 不应卖出
        assert len(result) == 0, \
            f"中跳空4%在观察期内不应卖出, 返回了{len(result)}个信号"
