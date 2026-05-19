"""V14 backtest test script"""
import asyncio
from core.managers import mongo_manager, redis_manager
from nodes.backtest_engine.ultra_short import execute_ultra_short_backtest
from core.utils.logger import logger

async def push_log(task_id, msg):
    pass

async def run():
    await mongo_manager.initialize()
    try:
        await redis_manager.initialize()
    except:
        pass
    task_info = {
        'task_id': 'v14_p0_5pct',
        'params': {
            'start_date': '20260105',
            'end_date': '20260320',
            'initial_cash': 1000000,
            'strategies': ['halfway_chase', 'limit_down_qiao'],
            'selected_strategies': [
                {'name': '半路追涨', 'id': 'halfway_chase', 'params': {}, 'riskParams': {}},
                {'name': '跌停翘板', 'id': 'limit_down_qiao', 'params': {}, 'riskParams': {}},
            ],
        }
    }
    result = await execute_ultra_short_backtest(task_info, push_log, logger, 'v14_p0_test1')
    if isinstance(result, dict) and 'error' in result:
        print(f'ERROR: {result["error"]}')
    else:
        m = result.get('metrics', {})
        ret = m.get('returns', {})
        risk = m.get('risk', {})
        trd = m.get('trades', {})
        total_ret = ret.get('total_return_pct', 0)
        sharpe = risk.get('sharpe_ratio', 0)
        dd = risk.get('max_drawdown_pct', 0)
        wr = risk.get('win_rate_pct', 0)
        plr = risk.get('profit_loss_ratio', 0)
        trades = trd.get('total_trades', 0)
        signals = result.get('total_signals', 0)
        print(f'收益:{total_ret:.2f}% 夏普:{sharpe:.2f} 回撤:{dd:.2f}% 胜率:{wr:.2f}% 盈亏比:{plr:.2f} 交易:{trades} 信号:{signals}')
        sr = result.get('strategy_results', {})
        for sname, sdata in sr.items():
            swr = sdata.get('win_rate', 0)
            sret = sdata.get('total_return', 0)
            strd = sdata.get('trades_count', 0)
            print(f'  {sname}: 胜率{swr:.1f}% 收益{sret:.2f}% 交易{strd}笔')
    try:
        await mongo_manager.close()
    except:
        pass

asyncio.run(run())
