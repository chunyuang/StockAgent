#!/usr/bin/env python3
"""V28 baseline backtest - shorter range for quick verification"""
import asyncio, sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from core.managers import mongo_manager

async def main():
    t0 = time.time()
    await mongo_manager.initialize()
    from nodes.backtest_engine.factor_selection import PortfolioBacktester
    
    async def push_log(tid, msg):
        pass  # silent - no logging overhead
    
    bt = PortfolioBacktester()
    config = {
        'start_date': '20250901', 'end_date': '20260320',
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
    elapsed = time.time() - t0
    await mongo_manager.shutdown()
    
    if result and 'error' not in result:
        m = result.get('metrics', {})
        r = m.get('returns', {})
        ri = m.get('risk', {})
        t = m.get('trades', {})
        tr = r.get('total_return',0)
        sr2 = ri.get('sharpe_ratio',0)
        md = ri.get('max_drawdown',0)
        wr = ri.get('win_rate',0)
        plr = ri.get('profit_loss_ratio',0)
        tt = t.get('total_trades',0)
        print(f"RESULT: 收益{tr:.2f}% 夏普{sr2:.2f} 回撤{md:.2f}% 胜率{wr:.2f}% 盈亏比{plr:.2f} 交易{tt}笔 耗时{elapsed:.0f}s")
        sr = result.get('strategy_results', {})
        for sn, sd in sr.items():
            print(f"STRAT: {sn}: 胜率{sd.get('win_rate',0):.1f}% 笔数{sd.get('trades_count',0)} 盈亏比{sd.get('profit_loss_ratio',0):.2f} 总收益{sd.get('total_return',0):.2f}%")
        srs = result.get('sell_reason_stats', {})
        print(f"SELL: {srs}")
        # Sell reason details
        mt = result.get('merged_trades', [])
        # Count profit protection sells
        pp_sells = [t2 for t2 in mt if t2.get('sell_reason','') == '利润保护']
        print(f"PROFIT_PROTECT: {len(pp_sells)}笔")
        for s in pp_sells[:5]:
            print(f"  PP: {s['ts_code']} {s['strategy']} {s['buy_date']}->{s['sell_date']} {s['profit_pct']:.2f}%")
    else:
        print(f"ERROR: {result}")

asyncio.run(main())
