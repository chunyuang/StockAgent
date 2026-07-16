"""v2.9.122 重复卖出防护测试"""
import sys
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from unittest.mock import patch
from nodes.market_monitor.broker import SimulatedBroker, Order, OrderSide, OrderStatus

# 盘后跑测试时, mock 交易时间为连续竞价
@patch('nodes.market_monitor.market_phase.MarketPhase.is_continuous_auction', return_value=True)
def test_duplicate_sell_blocked(mock_phase):
    """同一ts_code同日卖出第2次应被拦截"""
    broker = SimulatedBroker(account_id='test', initial_cash=100000, virtual_mode=True)
    
    # 模拟买入
    broker._realtime_prices['600000.SH'] = 10.0
    broker._limit_prices['600000.SH'] = {'upper': 11.0, 'lower': 9.0}
    broker._stock_names['600000.SH'] = '浦发银行'
    
    # 手动创建position(T+1 bypass: 设available_qty)
    from nodes.market_monitor.broker import Position
    broker.positions['600000.SH'] = Position(
        ts_code='600000.SH', stock_name='浦发银行',
        total_qty=1000, available_qty=1000,
        avg_cost=10.0, current_price=10.0,
        today_buy_qty=0, strategy='test', buy_date='20260714',
    )
    
    # 第1次卖出 - 应成功
    ok1, msg1, order1 = broker.place_order(
        ts_code='600000.SH', stock_name='浦发银行',
        side='sell', quantity=1000, price=10.0,
        order_type='market', strategy='test', reason='stop_loss',
    )
    assert ok1, f'第1次卖出应成功: {msg1}'
    assert order1.status == OrderStatus.FILLED
    assert '600000.SH' in broker._today_sold
    print('✅ 第1次卖出成功')
    
    # 模拟另一路径: position已被清空, 第2次卖出同一标的
    # pos已不在内存(全部卖完被del), 走兜底路径被_today_sold拦截
    
    # 第2次卖出 - 应被拦截
    ok2, msg2, order2 = broker.place_order(
        ts_code='600000.SH', stock_name='浦发银行',
        side='sell', quantity=1000, price=10.0,
        order_type='market', strategy='test', reason='force_empty',
    )
    assert not ok2, f'第2次卖出应被拦截, 但成功了: {order2}'
    print(f'✅ 第2次卖出被拦截: {msg2}')

@patch('nodes.market_monitor.market_phase.MarketPhase.is_continuous_auction', return_value=True)
def test_different_stocks_not_blocked(mock_phase):
    """不同ts_code的卖出不应互相影响"""
    broker = SimulatedBroker(account_id='test', initial_cash=100000, virtual_mode=True)
    from nodes.market_monitor.broker import Position
    
    for code in ['600000.SH', '000001.SZ']:
        broker._realtime_prices[code] = 10.0
        broker._limit_prices[code] = {'upper': 11.0, 'lower': 9.0}
        broker._stock_names[code] = '测试'
        broker.positions[code] = Position(
            ts_code=code, stock_name='测试',
            total_qty=1000, available_qty=1000,
            avg_cost=10.0, current_price=10.0,
            today_buy_qty=0, strategy='test', buy_date='20260714',
        )
    
    # 卖出第1只
    ok1, _, _ = broker.place_order('600000.SH', '测试', 'sell', 1000, 10.0, 'market', 'test', 'stop_loss')
    assert ok1
    
    # 卖出第2只 - 不应被拦截
    ok2, _, _ = broker.place_order('000001.SZ', '测试', 'sell', 1000, 10.0, 'market', 'test', 'stop_loss')
    assert ok2, '不同标的卖出不应被拦截'
    print('✅ 不同标的卖出正常')

def test_daily_settlement_resets():
    """日结算应重置_today_sold"""
    broker = SimulatedBroker(account_id='test', initial_cash=100000, virtual_mode=True)
    broker._today_sold.add('600000.SH')
    broker.daily_settlement()
    assert len(broker._today_sold) == 0
    print('✅ 日结算重置_today_sold')

if __name__ == '__main__':
    test_duplicate_sell_blocked()
    test_different_stocks_not_blocked()
    test_daily_settlement_resets()
    print('\n🎉 全部测试通过!')
