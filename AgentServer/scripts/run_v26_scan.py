"""V26参数扫描 - 禁用首板打板"""
import asyncio, sys, os, types, json, time

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, BASE)

_nodes = types.ModuleType('nodes')
_nodes.__path__ = [os.path.join(BASE, 'nodes')]
_nodes.__package__ = 'nodes'
sys.modules['nodes'] = _nodes

from core.managers.mongo_manager import mongo_manager
from core.constants import C

async def run_bt(name, selected_strats):
    from nodes.backtest_engine.factor_selection import PortfolioBacktester
    from nodes.backtest_engine.factor_selection.universe import UniverseManager, ExcludeRule
    from nodes.backtest_engine.factor_selection.factor_engine import FactorEngine
    
    universe_mgr = UniverseManager()
    universe_mgr.start_date = '20260105'
    universe_mgr.end_date = '20260320'
    universe_mgr.exclude_rules = [ExcludeRule.ST, ExcludeRule.NEW_STOCK]
    universe_mgr.min_liquidity = 500
    
    config = {
        'start_date': '20260105', 'end_date': '20260320',
        'initial_cash': 1000000, 'max_position_percent': 0.2,
        'liquidity_threshold': 500, 'data_collection': C.STOCK_DAILY,
        'universe_mgr': universe_mgr, 'factor_engine': FactorEngine(),
        'exclude_rules': [ExcludeRule.ST, ExcludeRule.NEW_STOCK],
        'factors': [], 'top_n': 10, 'rebalance_freq': 'daily',
        'task_id': f'v26_scan_{name}',
        'push_log': lambda tid, msg: asyncio.sleep(0),
        'strategy_weights': {},
        'selected_strategies': selected_strats,
        'volume_threshold': 2.0, 'weight_method': 'equal',
        'commission_rate': 0.0003, 'stamp_duty_rate': 0.001, 'slippage_pct': 0.002,
        'stop_loss_pct': 0.03, 'take_profit_pct': 0.07,
        'max_hold_days': 3, 'max_position_per_stock': 0.2,
        'enable_auction_filter': True, 'enable_sentiment_cycle': True,
        'enable_force_empty': True, 'enable_stop_loss': True,
        'enable_take_profit': True, 'enable_ma60_filter': True,
        'enable_sector_concentration': True,
        'force_empty_config': {}, 'global_filter_config': {},
    }
    
    bt = PortfolioBacktester()
    result = await bt.run(config)
    
    if result and 'error' not in result:
        m = result.get('metrics', {})
        rd = m.get('returns', {})
        rk = m.get('risk', {})
        td = m.get('trades', {})
        print(f'{name}: 收益{rd.get("total_return",0):.2f}% 夏普{rk.get("sharpe_ratio",0):.2f} 回撤{rk.get("max_drawdown",0):.2f}% 胜率{rk.get("win_rate",0):.2f}% 盈亏比{rk.get("profit_loss_ratio",0):.2f} 交易{td.get("total_trades",0)}')
    else:
        print(f'{name}: ERROR {result}')

async def main():
    await mongo_manager.initialize()
    
    from nodes.backtest_engine.strategy_defaults import ALL_STRATEGIES, STRATEGY_CONFIGS
    
    # 方案1: 基线(4策略)
    s4 = []
    for s in ALL_STRATEGIES:
        sid = s.get('id', '')
        cfg = STRATEGY_CONFIGS.get(sid, {})
        s4.append({'id': sid, 'name': s.get('name', cfg.get('name', sid)),
                    'params': dict(cfg.get('params', {})), 'riskParams': dict(cfg.get('riskParams', {}))})
    
    # 方案2: 禁用首板打板(3策略) + 跌停TP25% (最优单参数)
    s3_base = []
    for s in s4:
        if s['id'] != 'first_limit_up':
            rp = dict(s['riskParams'])
            if s['id'] == 'limit_down_qiao': rp['take_profit_pct'] = 0.25
            s3_base.append({**s, 'riskParams': rp})
    
    # 方案3: 3策略 + 龙头TP8% + 跌停TP25%
    s3_combo1 = []
    for s in s4:
        if s['id'] != 'first_limit_up':
            rp = dict(s['riskParams'])
            if s['id'] == 'dragon_head': rp['take_profit_pct'] = 0.08
            if s['id'] == 'limit_down_qiao': rp['take_profit_pct'] = 0.25
            s3_combo1.append({**s, 'riskParams': rp})
    
    # 方案4: 3策略 + 龙头TP10% + 跌停TP25%
    s3_combo2 = []
    for s in s4:
        if s['id'] != 'first_limit_up':
            rp = dict(s['riskParams'])
            if s['id'] == 'dragon_head': rp['take_profit_pct'] = 0.10
            if s['id'] == 'limit_down_qiao': rp['take_profit_pct'] = 0.25
            s3_combo2.append({**s, 'riskParams': rp})
    
    # 方案5: 3策略 + 跌停TP25% + 半路追涨SL4%/TP15%
    s3_combo3 = []
    for s in s4:
        if s['id'] != 'first_limit_up':
            rp = dict(s['riskParams'])
            if s['id'] == 'limit_down_qiao': rp['take_profit_pct'] = 0.25
            if s['id'] == 'halfway_chase': rp['stop_loss_pct'] = 0.04; rp['take_profit_pct'] = 0.15
            s3_combo3.append({**s, 'riskParams': rp})
    
    # 方案6: 3策略 + 龙头TP8% + 跌停TP25% + 半路SL4%/TP15%
    s3_combo4 = []
    for s in s4:
        if s['id'] != 'first_limit_up':
            rp = dict(s['riskParams'])
            if s['id'] == 'dragon_head': rp['take_profit_pct'] = 0.08
            if s['id'] == 'limit_down_qiao': rp['take_profit_pct'] = 0.25
            if s['id'] == 'halfway_chase': rp['stop_loss_pct'] = 0.04; rp['take_profit_pct'] = 0.15
            s3_combo4.append({**s, 'riskParams': rp})
    
    await run_bt('基线(4策略)', s4)
    await run_bt('3策略+跌停TP25%', s3_base)
    await run_bt('3策略+龙头TP8%+跌停TP25%', s3_combo1)
    await run_bt('3策略+龙头TP10%+跌停TP25%', s3_combo2)
    await run_bt('3策略+跌停TP25%+半路SL4%/TP15%', s3_combo3)
    await run_bt('3策略+全调参', s3_combo4)
    
    await mongo_manager.shutdown()

asyncio.run(main())
