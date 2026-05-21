#!/usr/bin/env python3
"""V28 baseline backtest - silent mode"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from core.managers import mongo_manager

async def main():
    await mongo_manager.initialize()
    from nodes.backtest_engine.factor_selection import PortfolioBacktester
    
    async def push_log(tid, msg):
        pass  # silent
    
    bt = PortfolioBacktester()
    config = {
        'start_date': '20250105', 'end_date': '20260320',
        'initial_cash': 1000000, 'max_stocks': 3,
        'rebalance_freq': 'daily', 'weight_method': 'equal',
        'task_id': 'audit_v28', 'push_log': push_log,
        'selected_strategies': [
            {'id': 'halfway_chase', 'name': '半路追涨', 'params': {}, 'riskParams': {}},
            {'id': 'dragon_head', 'name': '龙头低吸', 'params': {}, 'riskParams': {}},
            {'id': 'limit_down_qiao', 'name': '跌停翘板', 'params': {}, 'riskParams': {}},
        ],
    }
    result = await bt.run(config)
    await mongo_manager.shutdown()
    
    if result and 'error' not in result:
        m = result.get('metrics', {})
        r = m.get('returns', {})
        ri = m.get('risk', {})
        t = m.get('trades', {})
        print(f"RESULT: 收益{r.get('total_return',0):.2f}% 夏普{ri.get('sharpe_ratio',0):.2f} 回撤{ri.get('max_drawdown',0):.2f}% 胜率{ri.get('win_rate',0):.2f}% 盈亏比{ri.get('profit_loss_ratio',0):.2f} 交易{t.get('total_trades',0)}笔")
        sr = result.get('strategy_results', {})
        for sn, sd in sr.items():
            print(f"STRAT: {sn}: 胜率{sd.get('win_rate',0):.1f}% 笔数{sd.get('trades_count',0)} 盈亏比{sd.get('profit_loss_ratio',0):.2f} 总收益{sd.get('total_return',0):.2f}%")
        srs = result.get('sell_reason_stats', {})
        print(f"SELL: {srs}")
        mt = result.get('merged_trades', [])
        losers = [t2 for t2 in mt if t2.get('profit_pct') is not None and t2.get('profit_pct',0) < -4]
        losers.sort(key=lambda x: x['profit_pct'])
        print(f"LOSERS: {len(losers)}笔")
        for l in losers[:8]:
            print(f"LOSER: {l['ts_code']} {l['strategy']} {l['buy_date']}->{l['sell_date']} {l['profit_pct']:.2f}% {l['sell_reason']}")
        winners = [t2 for t2 in mt if t2.get('profit_pct') is not None and t2.get('profit_pct',0) > 15]
        winners.sort(key=lambda x: x['profit_pct'], reverse=True)
        print(f"BIGWINS: {len(winners)}笔")
        for w in winners[:5]:
            print(f"WINNER: {w['ts_code']} {w['strategy']} {w['buy_date']}->{w['sell_date']} {w['profit_pct']:.2f}% {w['sell_reason']}")
    else:
        print(f"ERROR: {result}")

asyncio.run(main())
