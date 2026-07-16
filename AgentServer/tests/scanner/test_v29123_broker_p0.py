"""
P0 broker.py 交易资金安全测试

覆盖broker核心交易逻辑:
1. 买入执行(_execute_buy) - 新仓/加仓/avg_cost计算/资金扣减
2. 卖出执行(_execute_sell) - 盈亏计算/资金回收/持仓更新/重复卖出防护
3. 订单成交(_execute_order_fill) - 滑点/佣金/印花税/REJECTED状态
4. 买入校验(_validate_and_adjust_buy) - 资金/仓位/数量调整
5. 卖出校验(_validate_sell) - 持仓/T+1/跌停
6. 账户重算(_recalc_account) - cash/mv/total计算
7. MongoDB重算现金(_calc_cash_from_mongo_orders)
8. 重复卖出防护(_today_sold去重)
9. 日结算(daily_settlement) - T+1解锁/缓存重置
10. 涨跌停价计算(_calc_limit_prices)
"""
import pytest
import threading
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime


@pytest.fixture
def broker():
    """构造一个不连MongoDB的broker实例"""
    from nodes.market_monitor.broker import SimulatedBroker
    b = SimulatedBroker(account_id="test", initial_cash=1_000_000, virtual_mode=True)
    # 阻止MongoDB连接
    b._ensure_sync_mongo = MagicMock(return_value=False)
    b._sync_save_order_and_position = MagicMock(return_value=False)
    b._calc_cash_from_mongo_orders = MagicMock(return_value=(0, 0))
    return b


@pytest.fixture
def broker_trading(broker):
    """broker + 交易时间patch(用于_validate_and_adjust_buy)"""
    import nodes.market_monitor.market_phase as mp_module
    orig_open = mp_module.MarketPhase.is_open_allowed
    orig_classify = mp_module.MarketPhase.classify
    mp_module.MarketPhase.is_open_allowed = staticmethod(lambda: True)
    mp_module.MarketPhase.classify = staticmethod(lambda: "continuous")
    yield broker
    mp_module.MarketPhase.is_open_allowed = orig_open
    mp_module.MarketPhase.classify = orig_classify


@pytest.fixture
def broker_with_mongo():
    """构造一个mock MongoDB的broker实例"""
    from nodes.market_monitor.broker import SimulatedBroker
    b = SimulatedBroker(account_id="test", initial_cash=1_000_000, virtual_mode=True)
    # mock同步MongoDB
    mock_db = MagicMock()
    b._sync_mongo_db = mock_db
    b._ensure_sync_mongo = MagicMock(return_value=True)
    b._sync_save_order_and_position = MagicMock(return_value=True)
    return b, mock_db


class TestExecuteBuy:
    """买入执行测试"""

    def test_new_position(self, broker):
        """新仓买入: avg_cost含佣金, available_qty=0(T+1)"""
        from nodes.market_monitor.broker import Order, OrderSide, OrderStatus, OrderType
        order = Order(
            order_id="TEST001", account_id="test", ts_code="600036.SH",
            stock_name="招商银行", side=OrderSide.BUY, order_type=OrderType.MARKET,
            quantity=1000, price=10.0, filled_qty=1000, filled_price=10.0,
            status=OrderStatus.FILLED, strategy="halfway_chase", trade_date="20260714",
        )
        order.commission = 3.0
        order.stamp_duty = 0
        broker._execute_buy(order, 10.0, 3.0)

        pos = broker.positions.get("600036.SH")
        assert pos is not None
        assert pos.total_qty == 1000
        assert pos.available_qty == 0  # T+1
        assert pos.today_buy_qty == 1000
        # avg_cost = (10*1000+3)/1000 = 10.003
        assert abs(pos.avg_cost - 10.003) < 0.001
        # 资金扣减 = 10*1000 + 3 = 10003
        assert abs(broker.account.available_cash - (1_000_000 - 10003)) < 1

    def test_add_position(self, broker):
        """加仓: avg_cost重算(加权平均)"""
        from nodes.market_monitor.broker import Order, OrderSide, OrderStatus, OrderType, Position
        # 先建仓
        broker.positions["600036.SH"] = Position(
            ts_code="600036.SH", stock_name="招商银行",
            total_qty=1000, available_qty=1000, avg_cost=10.0,
            current_price=10.0, strategy="halfway_chase", buy_date="20260713",
        )
        # 加仓
        order = Order(
            order_id="TEST002", account_id="test", ts_code="600036.SH",
            stock_name="招商银行", side=OrderSide.BUY, order_type=OrderType.MARKET,
            quantity=1000, price=12.0, filled_qty=1000, filled_price=12.0,
            status=OrderStatus.FILLED, strategy="halfway_chase", trade_date="20260714",
        )
        order.commission = 3.6
        broker._execute_buy(order, 12.0, 3.6)

        pos = broker.positions["600036.SH"]
        assert pos.total_qty == 2000
        # avg_cost = (10*1000 + 12*1000 + 3.6) / 2000 = 11.0018
        assert abs(pos.avg_cost - 11.0018) < 0.001

    def test_buy_reduces_cash(self, broker):
        """买入必须扣减available_cash"""
        from nodes.market_monitor.broker import Order, OrderSide, OrderStatus, OrderType
        cash_before = broker.account.available_cash
        order = Order(
            order_id="TEST003", account_id="test", ts_code="000001.SZ",
            stock_name="平安银行", side=OrderSide.BUY, order_type=OrderType.MARKET,
            quantity=500, price=5.0, filled_qty=500, filled_price=5.0,
            status=OrderStatus.FILLED, strategy="halfway_chase", trade_date="20260714",
        )
        order.commission = 5.0  # 最低佣金
        broker._execute_buy(order, 5.0, 5.0)

        expected_cost = 5.0 * 500 + 5.0  # 2505
        assert abs(broker.account.available_cash - (cash_before - expected_cost)) < 1


class TestExecuteSell:
    """卖出执行测试"""

    def test_sell_calculates_profit(self, broker):
        """卖出盈亏计算: profit = (fill_price - avg_cost) * qty - cost"""
        from nodes.market_monitor.broker import Order, OrderSide, OrderStatus, OrderType, Position
        # 建仓
        broker.positions["600036.SH"] = Position(
            ts_code="600036.SH", stock_name="招商银行",
            total_qty=1000, available_qty=1000, avg_cost=10.0,
            current_price=11.0, strategy="halfway_chase", buy_date="20260713",
        )
        order = Order(
            order_id="TEST004", account_id="test", ts_code="600036.SH",
            stock_name="招商银行", side=OrderSide.SELL, order_type=OrderType.MARKET,
            quantity=1000, price=11.0, filled_qty=1000, filled_price=11.0,
            status=OrderStatus.FILLED, strategy="halfway_chase", trade_date="20260714",
        )
        # 卖出: 佣金=max(11*1000*0.0003, 5)=5, 印花税=11*1000*0.001=11
        order.commission = 5.0
        order.stamp_duty = 11.0
        broker._execute_sell(order, 11.0, 16.0)

        # profit = (11-10)*1000 - 16 = 984
        assert abs(order.profit_amount - 984) < 1
        # profit_pct = 984 / (10*1000) * 100 = 9.84%
        assert abs(order.profit_pct - 9.84) < 0.1

    def test_sell_recovers_cash(self, broker):
        """卖出必须回收资金 = fill_price * qty - cost"""
        from nodes.market_monitor.broker import Order, OrderSide, OrderStatus, OrderType, Position
        broker.positions["600036.SH"] = Position(
            ts_code="600036.SH", stock_name="招商银行",
            total_qty=1000, available_qty=1000, avg_cost=10.0,
            current_price=11.0, strategy="halfway_chase", buy_date="20260713",
        )
        cash_before = broker.account.available_cash
        order = Order(
            order_id="TEST005", account_id="test", ts_code="600036.SH",
            stock_name="招商银行", side=OrderSide.SELL, order_type=OrderType.MARKET,
            quantity=1000, price=11.0, filled_qty=1000, filled_price=11.0,
            status=OrderStatus.FILLED, strategy="halfway_chase", trade_date="20260714",
        )
        order.commission = 5.0
        order.stamp_duty = 11.0
        broker._execute_sell(order, 11.0, 16.0)

        # 回收 = 11*1000 - 16 = 10984
        expected_recovery = 11.0 * 1000 - 16.0
        assert abs(broker.account.available_cash - (cash_before + expected_recovery)) < 1

    def test_sell_updates_position(self, broker):
        """卖出后持仓数量减少"""
        from nodes.market_monitor.broker import Order, OrderSide, OrderStatus, OrderType, Position
        broker.positions["600036.SH"] = Position(
            ts_code="600036.SH", stock_name="招商银行",
            total_qty=1000, available_qty=1000, avg_cost=10.0,
            current_price=11.0, strategy="halfway_chase", buy_date="20260713",
        )
        order = Order(
            order_id="TEST006", account_id="test", ts_code="600036.SH",
            stock_name="招商银行", side=OrderSide.SELL, order_type=OrderType.MARKET,
            quantity=500, price=11.0, filled_qty=500, filled_price=11.0,
            status=OrderStatus.FILLED, strategy="halfway_chase", trade_date="20260714",
        )
        order.commission = 5.0
        order.stamp_duty = 5.5
        broker._execute_sell(order, 11.0, 10.5)

        pos = broker.positions["600036.SH"]
        assert pos.total_qty == 500
        assert pos.available_qty == 500

    def test_sell_clears_position(self, broker):
        """全部卖出后position删除"""
        from nodes.market_monitor.broker import Order, OrderSide, OrderStatus, OrderType, Position
        broker.positions["600036.SH"] = Position(
            ts_code="600036.SH", stock_name="招商银行",
            total_qty=1000, available_qty=1000, avg_cost=10.0,
            current_price=11.0, strategy="halfway_chase", buy_date="20260713",
        )
        order = Order(
            order_id="TEST007", account_id="test", ts_code="600036.SH",
            stock_name="招商银行", side=OrderSide.SELL, order_type=OrderType.MARKET,
            quantity=1000, price=11.0, filled_qty=1000, filled_price=11.0,
            status=OrderStatus.FILLED, strategy="halfway_chase", trade_date="20260714",
        )
        order.commission = 5.0
        order.stamp_duty = 11.0
        broker._execute_sell(order, 11.0, 16.0)

        assert "600036.SH" not in broker.positions

    def test_duplicate_sell_blocked(self, broker):
        """【v2.9.122】同一ts_code当日第二次卖出被拦截"""
        from nodes.market_monitor.broker import Order, OrderSide, OrderStatus, OrderType, Position
        broker.positions["600036.SH"] = Position(
            ts_code="600036.SH", stock_name="招商银行",
            total_qty=1000, available_qty=1000, avg_cost=10.0,
            current_price=11.0, strategy="halfway_chase", buy_date="20260713",
        )
        # 第一次卖出(全部卖完)
        order1 = Order(
            order_id="TEST008A", account_id="test", ts_code="600036.SH",
            stock_name="招商银行", side=OrderSide.SELL, order_type=OrderType.MARKET,
            quantity=1000, price=11.0, filled_qty=1000, filled_price=11.0,
            status=OrderStatus.FILLED, strategy="halfway_chase", trade_date="20260714",
        )
        order1.commission = 5.0
        order1.stamp_duty = 11.0
        broker._execute_sell(order1, 11.0, 16.0)
        assert order1.status == OrderStatus.FILLED

        # 第二次卖出同一标的 -> 应被REJECTED
        order2 = Order(
            order_id="TEST008B", account_id="test", ts_code="600036.SH",
            stock_name="招商银行", side=OrderSide.SELL, order_type=OrderType.MARKET,
            quantity=1000, price=11.0, filled_qty=1000, filled_price=11.0,
            status=OrderStatus.FILLED, strategy="halfway_chase", trade_date="20260714",
        )
        order2.commission = 5.0
        order2.stamp_duty = 11.0
        broker._execute_sell(order2, 11.0, 16.0)
        assert order2.status == OrderStatus.REJECTED
        assert "重复" in order2.reason

    def test_sell_records_avg_cost_to_order(self, broker):
        """卖出order应记录avg_cost(供MongoDB持久化)"""
        from nodes.market_monitor.broker import Order, OrderSide, OrderStatus, OrderType, Position
        broker.positions["600036.SH"] = Position(
            ts_code="600036.SH", stock_name="招商银行",
            total_qty=1000, available_qty=1000, avg_cost=10.5,
            current_price=11.0, strategy="halfway_chase", buy_date="20260713",
        )
        order = Order(
            order_id="TEST009", account_id="test", ts_code="600036.SH",
            stock_name="招商银行", side=OrderSide.SELL, order_type=OrderType.MARKET,
            quantity=1000, price=11.0, filled_qty=1000, filled_price=11.0,
            status=OrderStatus.FILLED, strategy="halfway_chase", trade_date="20260714",
        )
        order.commission = 5.0
        order.stamp_duty = 11.0
        broker._execute_sell(order, 11.0, 16.0)

        assert order.avg_cost == 10.5


class TestValidateBuy:
    """买入校验测试"""

    def test_validate_buy_ok(self, broker_trading):
        """正常买入通过校验"""
        broker_trading.update_realtime("600036.SH", 10.0)
        ok, reason, qty = broker_trading._validate_and_adjust_buy("600036.SH", 1000, 10.0)
        assert ok is True
        assert qty == 1000

    def test_validate_buy_insufficient_cash(self, broker_trading):
        """资金不足时调整数量"""
        broker_trading.account.available_cash = 5000
        broker_trading.update_realtime("600036.SH", 10.0)
        ok, reason, qty = broker_trading._validate_and_adjust_buy("600036.SH", 1000, 10.0)
        # 5000/10/100=5手=500股
        assert ok is True
        assert qty == 500

    def test_validate_buy_no_cash(self, broker_trading):
        """完全没钱拒绝"""
        broker_trading.account.available_cash = 0
        broker_trading.update_realtime("600036.SH", 10.0)
        ok, reason, qty = broker_trading._validate_and_adjust_buy("600036.SH", 1000, 10.0)
        assert ok is False
        assert "资金" in reason

    def test_validate_buy_max_positions(self, broker_trading):
        """持仓数达上限拒绝新开仓"""
        from nodes.market_monitor.broker import Position
        broker_trading._dynamic_max_positions = 3
        for i in range(3):
            broker_trading.positions[f"00000{i}.SZ"] = Position(
                ts_code=f"00000{i}.SZ", stock_name=f"测试{i}",
                total_qty=100, available_qty=100, avg_cost=10.0,
                current_price=10.0, strategy="halfway_chase", buy_date="20260713",
            )
        broker_trading.update_realtime("600036.SH", 10.0)
        ok, reason, qty = broker_trading._validate_and_adjust_buy("600036.SH", 1000, 10.0)
        assert ok is False
        assert "上限" in reason

    def test_validate_buy_single_position_limit(self, broker_trading):
        """单票仓位超限调整数量"""
        from nodes.market_monitor.broker import Position
        # 已有持仓占90%
        broker_trading.positions["600036.SH"] = Position(
            ts_code="600036.SH", stock_name="招商银行",
            total_qty=90000, available_qty=90000, avg_cost=10.0,
            current_price=10.0, strategy="halfway_chase", buy_date="20260713",
        )
        broker_trading.update_realtime("600036.SH", 10.0)
        # 35%上限 = 100万*0.35=35万, 已有90万 -> 超限
        ok, reason, qty = broker_trading._validate_and_adjust_buy("600036.SH", 1000, 10.0)
        assert ok is False
        assert "仓位" in reason


class TestValidateSell:
    """卖出校验测试"""

    def test_validate_sell_ok(self, broker):
        """正常卖出通过"""
        from nodes.market_monitor.broker import Position
        broker.positions["600036.SH"] = Position(
            ts_code="600036.SH", stock_name="招商银行",
            total_qty=1000, available_qty=1000, avg_cost=10.0,
            current_price=11.0, strategy="halfway_chase", buy_date="20260713",
        )
        broker.update_realtime("600036.SH", 11.0)
        ok, reason, qty = broker._validate_sell("600036.SH", 500, 11.0)
        assert ok is True
        assert qty == 500

    def test_validate_sell_no_position(self, broker):
        """无持仓拒绝"""
        broker.update_realtime("000001.SZ", 5.0)
        ok, reason, qty = broker._validate_sell("000001.SZ", 100, 5.0)
        assert ok is False
        assert "持仓" in reason

    def test_validate_sell_t1_restricted(self, broker):
        """T+1限制: available_qty=0时拒绝"""
        from nodes.market_monitor.broker import Position
        broker.positions["600036.SH"] = Position(
            ts_code="600036.SH", stock_name="招商银行",
            total_qty=1000, available_qty=0, avg_cost=10.0,
            current_price=10.0, strategy="halfway_chase", buy_date="20260714",
        )
        broker.update_realtime("600036.SH", 10.0)
        ok, reason, qty = broker._validate_sell("600036.SH", 100, 10.0)
        assert ok is False
        assert "T+1" in reason

    def test_validate_sell_limit_down(self, broker):
        """跌停不可卖出"""
        from nodes.market_monitor.broker import Position
        broker.positions["600036.SH"] = Position(
            ts_code="600036.SH", stock_name="招商银行",
            total_qty=1000, available_qty=1000, avg_cost=10.0,
            current_price=9.0, strategy="halfway_chase", buy_date="20260713",
        )
        broker.update_realtime("600036.SH", 9.0)
        broker._limit_prices["600036.SH"] = {"upper": 11.0, "lower": 9.0}
        ok, reason, qty = broker._validate_sell("600036.SH", 100, 9.0)
        assert ok is False
        assert "跌停" in reason

    def test_validate_sell_quantity_capped(self, broker):
        """卖出数量不可超过可卖"""
        from nodes.market_monitor.broker import Position
        broker.positions["600036.SH"] = Position(
            ts_code="600036.SH", stock_name="招商银行",
            total_qty=500, available_qty=500, avg_cost=10.0,
            current_price=11.0, strategy="halfway_chase", buy_date="20260713",
        )
        broker.update_realtime("600036.SH", 11.0)
        ok, reason, qty = broker._validate_sell("600036.SH", 1000, 11.0)
        assert ok is True
        assert qty == 500  # 限制为可卖量


class TestRecalcAccount:
    """账户重算测试"""

    def test_recalc_with_positions(self, broker):
        """有持仓时重算"""
        from nodes.market_monitor.broker import Position
        broker.positions["600036.SH"] = Position(
            ts_code="600036.SH", stock_name="招商银行",
            total_qty=1000, available_qty=1000, avg_cost=10.0,
            current_price=11.0, strategy="halfway_chase", buy_date="20260713",
        )
        broker._calc_cash_from_mongo_orders = MagicMock(return_value=(10000, 0))
        broker._recalc_account()

        assert broker.account.market_value == 11000  # 11*1000
        assert broker.account.available_cash == 1_000_000 - 10000
        assert broker.account.total_assets == 1_000_000 - 10000 + 11000
        assert broker.account.total_profit == -10000 + 11000  # 1000

    def test_recalc_no_positions(self, broker):
        """空仓时重算"""
        broker._calc_cash_from_mongo_orders = MagicMock(return_value=(0, 0))
        broker._recalc_account()

        assert broker.account.market_value == 0
        assert broker.account.available_cash == 1_000_000
        assert broker.account.total_assets == 1_000_000
        assert broker.account.total_profit == 0

    def test_recalc_uses_current_price_not_avg_cost(self, broker):
        """重算用current_price, 不用avg_cost"""
        from nodes.market_monitor.broker import Position
        broker.positions["600036.SH"] = Position(
            ts_code="600036.SH", stock_name="招商银行",
            total_qty=1000, available_qty=1000, avg_cost=10.0,
            current_price=15.0, strategy="halfway_chase", buy_date="20260713",
        )
        broker._calc_cash_from_mongo_orders = MagicMock(return_value=(10000, 0))
        broker._recalc_account()

        # mv用current_price=15, 不是avg_cost=10
        assert broker.account.market_value == 15000


class TestCalcCashFromMongoOrders:
    """从MongoDB订单重算现金测试"""

    def test_calc_cash_buy_only(self, broker_with_mongo):
        """只有买入: cash = initial - buy_cost(含佣金)"""
        broker, mock_db = broker_with_mongo
        buy_cursor = MagicMock()
        buy_cursor.__iter__ = MagicMock(return_value=iter([
            {"filled_qty": 1000, "filled_price": 10.0, "side": "buy"},
        ]))
        sell_cursor = MagicMock()
        sell_cursor.__iter__ = MagicMock(return_value=iter([]))

        def find_side(query):
            if query.get("side") == "buy":
                return buy_cursor
            else:
                return sell_cursor
        mock_db["broker_orders"].find.side_effect = find_side

        buy_cost, sell_income = broker._calc_cash_from_mongo_orders()
        # buy_cost = 10*1000 + max(10000*0.0003, 5) = 10000 + 5 = 10005
        assert abs(buy_cost - 10005) < 1
        assert sell_income == 0

    def test_calc_cash_sell_only(self, broker_with_mongo):
        """只有卖出: sell_income = price*qty - 佣金 - 印花税"""
        broker, mock_db = broker_with_mongo
        # 需要分别返回buy和sell的cursor
        buy_cursor = MagicMock()
        buy_cursor.__iter__ = MagicMock(return_value=iter([]))
        sell_cursor = MagicMock()
        sell_cursor.__iter__ = MagicMock(return_value=iter([
            {"filled_qty": 1000, "filled_price": 11.0, "side": "sell"},
        ]))

        def find_side(query):
            if query.get("side") == "buy":
                return buy_cursor
            else:
                return sell_cursor

        mock_db["broker_orders"].find.side_effect = find_side
        buy_cost, sell_income = broker._calc_cash_from_mongo_orders()

        # sell_income = 11*1000 - max(11000*0.0003, 5) - 11000*0.001 = 11000 - 5 - 11 = 10984
        assert buy_cost == 0
        assert abs(sell_income - 10984) < 1

    def test_calc_cash_both(self, broker_with_mongo):
        """同时有买卖: cash = initial - buy_cost + sell_income"""
        broker, mock_db = broker_with_mongo
        buy_cursor = MagicMock()
        buy_cursor.__iter__ = MagicMock(return_value=iter([
            {"filled_qty": 1000, "filled_price": 10.0, "side": "buy"},
        ]))
        sell_cursor = MagicMock()
        sell_cursor.__iter__ = MagicMock(return_value=iter([
            {"filled_qty": 1000, "filled_price": 11.0, "side": "sell"},
        ]))

        def find_side(query):
            if query.get("side") == "buy":
                return buy_cursor
            else:
                return sell_cursor

        mock_db["broker_orders"].find.side_effect = find_side
        buy_cost, sell_income = broker._calc_cash_from_mongo_orders()

        # buy_cost = 10005, sell_income = 10984
        assert abs(buy_cost - 10005) < 1
        assert abs(sell_income - 10984) < 1


class TestDailySettlement:
    """日结算测试"""

    def test_t1_unlock(self, broker):
        """T+1解锁: available_qty = total_qty"""
        from nodes.market_monitor.broker import Position
        broker.positions["600036.SH"] = Position(
            ts_code="600036.SH", stock_name="招商银行",
            total_qty=1000, available_qty=0, avg_cost=10.0,
            current_price=10.0, strategy="halfway_chase", buy_date="20260714",
            today_buy_qty=1000,
        )
        broker.daily_settlement()

        assert broker.positions["600036.SH"].available_qty == 1000
        assert broker.positions["600036.SH"].today_buy_qty == 0

    def test_daily_settlement_resets_caches(self, broker):
        """日结算重置_today_sold和_today_rejected"""
        broker._today_sold.add("600036.SH")
        broker._today_rejected.add("600036.SH:sell")
        broker.daily_settlement()

        assert len(broker._today_sold) == 0
        assert len(broker._today_rejected) == 0

    def test_daily_settlement_resets_today_profit(self, broker):
        """日结算重置today_profit"""
        broker.account.today_profit = 5000
        broker.daily_settlement()
        assert broker.account.today_profit == 0


class TestCalcLimitPrices:
    """涨跌停价计算测试"""

    def test_main_board(self, broker):
        """主板±10%"""
        prices = broker._calc_limit_prices("600036.SH", 10.0)
        assert prices["upper"] == 11.0
        assert prices["lower"] == 9.0

    def test_kcb_board(self, broker):
        """科创板±20%"""
        prices = broker._calc_limit_prices("688001.SH", 10.0)
        assert prices["upper"] == 12.0
        assert prices["lower"] == 8.0

    def test_cyb_board(self, broker):
        """创业板±20%"""
        prices = broker._calc_limit_prices("300001.SZ", 10.0)
        assert prices["upper"] == 12.0
        assert prices["lower"] == 8.0

    def test_bjb_board(self, broker):
        """北交所±30%"""
        prices = broker._calc_limit_prices("820001.BJ", 10.0)
        assert prices["upper"] == 13.0
        assert prices["lower"] == 7.0

    def test_zero_pre_close(self, broker):
        """pre_close=0返回upper=0/lower=0"""
        prices = broker._calc_limit_prices("600036.SH", 0)
        assert prices["upper"] == 0
        assert prices["lower"] == 0


class TestMatchAndSlippage:
    """撮合+滑点测试"""

    def test_match_buy_slippage(self, broker):
        """买入滑点: fill_price略高于current_price"""
        from nodes.market_monitor.broker import Order, OrderSide, OrderType
        order = Order(
            order_id="TEST010", account_id="test", ts_code="600036.SH",
            stock_name="招商银行", side=OrderSide.BUY, order_type=OrderType.MARKET,
            quantity=1000, price=10.0, strategy="halfway_chase", trade_date="20260714",
        )
        fill_price, commission, stamp_duty = broker._match(order, 10.0)

        # 买入滑点向上
        assert fill_price >= 10.0
        # 佣金 = max(amount*0.0003, 5)
        assert commission >= 5.0
        # 买入无印花税
        assert stamp_duty == 0

    def test_match_sell_slippage(self, broker):
        """卖出滑点: fill_price略低于current_price"""
        from nodes.market_monitor.broker import Order, OrderSide, OrderType
        order = Order(
            order_id="TEST011", account_id="test", ts_code="600036.SH",
            stock_name="招商银行", side=OrderSide.SELL, order_type=OrderType.MARKET,
            quantity=1000, price=10.0, strategy="halfway_chase", trade_date="20260714",
        )
        fill_price, commission, stamp_duty = broker._match(order, 10.0)

        # 卖出滑点向下
        assert fill_price <= 10.0
        # 佣金
        assert commission >= 5.0
        # 卖出有印花税
        assert stamp_duty > 0

    def test_match_commission_min(self, broker):
        """小额交易佣金取最低5元"""
        from nodes.market_monitor.broker import Order, OrderSide, OrderType
        order = Order(
            order_id="TEST012", account_id="test", ts_code="600036.SH",
            stock_name="招商银行", side=OrderSide.BUY, order_type=OrderType.MARKET,
            quantity=100, price=1.0, strategy="halfway_chase", trade_date="20260714",
        )
        _, commission, _ = broker._match(order, 1.0)
        # 100*1*0.0003=0.03 < 5 -> 取5
        assert commission == 5.0


class TestValidatePrechecks:
    """前置校验测试"""

    def test_suspended(self, broker):
        """停牌不可交易"""
        broker._suspended.add("600036.SH")
        result = broker._validate_prechecks("600036.SH", 1000)
        assert result is not None
        assert "停牌" in result

    def test_no_price(self, broker):
        """无行情不可交易"""
        result = broker._validate_prechecks("600036.SH", 1000)
        assert result is not None
        assert "行情" in result

    def test_wrong_lot_size(self, broker):
        """非整手不可交易"""
        broker.update_realtime("600036.SH", 10.0)
        result = broker._validate_prechecks("600036.SH", 150)
        assert result is not None
        assert "100" in result

    def test_kcb_lot_size(self, broker):
        """科创板200股整数倍"""
        broker.update_realtime("688001.SH", 10.0)
        # 100不是200的倍数
        result = broker._validate_prechecks("688001.SH", 100)
        assert result is not None
        assert "200" in result

    def test_prechecks_pass(self, broker):
        """正常通过"""
        broker.update_realtime("600036.SH", 10.0)
        result = broker._validate_prechecks("600036.SH", 1000)
        assert result is None
