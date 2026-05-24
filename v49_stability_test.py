#!/usr/bin/env python3
"""V49 stability test - run backtest 3 times to measure non-determinism"""
import asyncio, json, sys, time
sys.path.insert(0, 'AgentServer')
from core.managers import mongo_manager
from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS, GLOBAL_RISK

async def run_once(label):
    selected_strategies = []
    for cfg in STRATEGY_CONFIGS.values():
        if cfg.get('enabled', True):
            selected_strategies.append({
                'id': cfg['id'],
                'name': cfg['name'],
                'params': dict(cfg['params']),
                'riskParams': dict(cfg['riskParams']),
            })
    config = {
        'start_date': '20250101',
        'end_date': '20250331',
        'initial_cash': 1000000,
        'top_n': 3,
        'max_stocks': 3,
        'selected_strategies': selected_strategies,
        'strategy_weights': {},
        'max_position_per_stock': GLOBAL_RISK['max_position_per_stock'],
        'stop_loss_pct': GLOBAL_RISK['stop_loss_pct'],
        'take_profit_pct': GLOBAL_RISK['take_profit_pct'],
        'max_hold_days': GLOBAL_RISK['max_hold_days'],
        'slippage_pct': GLOBAL_RISK['slippage_pct'],
        'risk_config': {},
        'task_id': f'v49_stability_{label}',
        'push_log': None,
    }
    bt = PortfolioBacktester()
    result = await bt.run(config)
    if 'error' in result:
        return None
    m = result.get('metrics', {})
    r = m.get('returns', {})
    ri = m.get('risk', {})
    t = m.get('trades', {})
    sell_reasons = {}
    for rec in result.get('rebalance_records', []):
        if isinstance(rec, dict):
            action = rec.get('action', '')
            reason_raw = rec.get('reason', '')
        else:
            action = rec.action
            reason_raw = rec.reason
        if action == 'sell':
            reason = reason_raw.split('(')[0] if '(' in reason_raw else reason_raw
            sell_reasons[reason] = sell_reasons.get(reason, 0) + 1
    return {
        'return': r.get('total_return_pct', 0),
        'drawdown': ri.get('max_drawdown_pct', 0),
        'win_rate': ri.get('win_rate_pct', 0),
        'sharpe': ri.get('sharpe_ratio', 0),
        'trades': t.get('total_trades', 0),
        'sell_reasons': sell_reasons,
    }

async def main():
    await mongo_manager.initialize()
    results = []
    for i in range(3):
        r = await run_once(i)
        if r:
            results.append(r)
            ret = r['return']
            dd = r['drawdown']
            wr = r['win_rate']
            sh = r['sharpe']
            tr = r['trades']
            sr = json.dumps(r['sell_reasons'], ensure_ascii=False)
            print(f'Run {i}: ret={ret:.2f}%, dd={dd:.2f}%, wr={wr:.1f}%, sharpe={sh:.2f}, trades={tr}, reasons={sr}')
    
    if len(results) >= 2:
        rets = [r['return'] for r in results]
        spread = max(rets) - min(rets)
        print(f'\nReturn variance: {min(rets):.2f}% ~ {max(rets):.2f}% (spread: {spread:.2f}%)')
    await mongo_manager.shutdown()

if __name__ == '__main__':
    asyncio.run(main())
