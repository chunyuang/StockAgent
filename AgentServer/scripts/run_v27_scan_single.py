"""V27参数扫描 - 简化版，每次独立进程"""
import asyncio, sys, os, types, json, time

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, BASE)

_nodes = types.ModuleType('nodes')
_nodes.__path__ = [os.path.join(BASE, 'nodes')]
_nodes.__package__ = 'nodes'
sys.modules['nodes'] = _nodes

from core.managers.mongo_manager import mongo_manager
from core.constants import C

async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--dragon-tp', type=float, default=0.10)
    parser.add_argument('--halfway-tp', type=float, default=0.12)
    parser.add_argument('--halfway-sl', type=float, default=0.05)
    parser.add_argument('--limitdown-sl', type=float, default=0.05)
    parser.add_argument('--limitdown-tp', type=float, default=0.25)
    parser.add_argument('--label', type=str, default='test')
    args = parser.parse_args()
    
    await mongo_manager.initialize()
    
    from nodes.backtest_engine.strategy_defaults import ALL_STRATEGIES, GLOBAL_RISK, STRATEGY_CONFIGS
    from nodes.backtest_engine.factor_selection import PortfolioBacktester
    from nodes.backtest_engine.factor_selection.universe import UniverseManager, ExcludeRule
    from nodes.backtest_engine.factor_selection.factor_engine import FactorEngine
    
    universe_mgr = UniverseManager()
    universe_mgr.start_date = '20260105'
    universe_mgr.end_date = '20260320'
    universe_mgr.exclude_rules = [ExcludeRule.ST, ExcludeRule.NEW_STOCK]
    universe_mgr.min_liquidity = 500
    
    selected = []
    for s in ALL_STRATEGIES:
        sid = s.get('id', '')
        cfg = STRATEGY_CONFIGS.get(sid, {})
        rp = dict(cfg.get("riskParams", {}))
        # Override
        if sid == 'dragon_head': rp['take_profit_pct'] = args.dragon_tp
        if sid == 'halfway_chase': 
            rp['take_profit_pct'] = args.halfway_tp
            rp['stop_loss_pct'] = args.halfway_sl
        if sid == 'limit_down_qiao': 
            rp['stop_loss_pct'] = args.limitdown_sl
            rp['take_profit_pct'] = args.limitdown_tp
        selected.append({
            "id": sid,
            "name": s.get("name", cfg.get("name", sid)),
            "params": dict(cfg.get("params", {})),
            "riskParams": rp,
        })
    
    config = {
        'start_date': '20260105', 'end_date': '20260320',
        'initial_cash': 1000000, 'max_position_percent': 0.2,
        'liquidity_threshold': 500, 'data_collection': C.STOCK_DAILY,
        'universe_mgr': universe_mgr, 'factor_engine': FactorEngine(),
        'exclude_rules': [ExcludeRule.ST, ExcludeRule.NEW_STOCK],
        'factors': [], 'top_n': 10, 'rebalance_freq': 'daily',
        'task_id': f'v27scan_{args.label}',
        'push_log': lambda tid, msg: asyncio.sleep(0),
        'strategy_weights': {},
        'selected_strategies': selected,
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
    
    t0 = time.time()
    bt = PortfolioBacktester()
    result = await bt.run(config)
    elapsed = time.time() - t0
    
    if result and 'error' not in result:
        m = result.get('metrics', {})
        rd = m.get('returns', {})
        rk = m.get('risk', {})
        td = m.get('trades', {})
        print(f'{args.label}|{rd.get("total_return", 0):.2f}|{rk.get("sharpe_ratio", 0):.2f}|{rk.get("max_drawdown", 0):.2f}|{rk.get("win_rate", 0):.2f}|{rk.get("profit_loss_ratio", 0):.2f}|{td.get("total_trades", 0)}|{elapsed:.0f}')
    
    await mongo_manager.shutdown()

asyncio.run(main())
