"""验证_prev因子有效率"""
import asyncio, sys, os, types
import pandas as pd

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, BASE)

_nodes = types.ModuleType('nodes')
_nodes.__path__ = [os.path.join(BASE, 'nodes')]
_nodes.__package__ = 'nodes'
sys.modules['nodes'] = _nodes

from core.managers.mongo_manager import mongo_manager
from core.constants import C

async def main():
    await mongo_manager.initialize()
    from nodes.backtest_engine.factor_selection.universe import UniverseManager, ExcludeRule
    
    um = UniverseManager()
    um.start_date = '20260105'
    um.end_date = '20260320'
    um.exclude_rules = [ExcludeRule.ST, ExcludeRule.NEW_STOCK]
    um.min_liquidity = 500
    
    trade_date = 20260210
    universe = await um.get_universe(trade_date)
    
    # 查T日数据
    docs = await mongo_manager.db[C.STOCK_DAILY].find(
        {'trade_date': trade_date, 'ts_code': {'$in': universe}},
        {'ts_code': 1, 'circ_mv': 1, 'turnover_rate': 1, 'volume_ratio': 1, '_id': 0}
    ).to_list(length=len(universe))
    df = pd.DataFrame(docs)
    
    # 查T-1日
    prev_doc = await mongo_manager.db[C.STOCK_DAILY].aggregate([
        {'$match': {'trade_date': {'$lt': trade_date}}},
        {'$group': {'_id': None, 'max_date': {'$max': '$trade_date'}}}
    ]).to_list(length=1)
    prev_date = prev_doc[0]['max_date'] if prev_doc else None
    print(f'T日={trade_date}, T-1日={prev_date}')
    
    if prev_date:
        prev_docs = await mongo_manager.db[C.STOCK_DAILY].find(
            {'trade_date': prev_date, 'ts_code': {'$in': universe}},
            {'ts_code': 1, 'circ_mv': 1, 'turnover_rate': 1, 'volume_ratio': 1, '_id': 0}
        ).to_list(length=len(universe))
        prev_df = pd.DataFrame(prev_docs)
        
        for col in ['circ_mv', 'turnover_rate', 'volume_ratio']:
            if col in prev_df.columns:
                prev_map = dict(zip(prev_df['ts_code'], prev_df[col]))
                df[f'{col}_prev'] = df['ts_code'].map(prev_map).fillna(0)
        
        total = len(df)
        for col in ['circ_mv', 'turnover_rate', 'volume_ratio']:
            t_valid = (df[col] > 0).sum() if col in df.columns else 0
            p_valid = (df[f'{col}_prev'] > 0).sum() if f'{col}_prev' in df.columns else 0
            print(f'{col}: T日有效{t_valid}/{total}({t_valid/total*100:.1f}%), T-1日有效{p_valid}/{total}({p_valid/total*100:.1f}%)')
        
        for col in ['circ_mv', 'turnover_rate', 'volume_ratio']:
            if f'{col}_prev' in df.columns and col in df.columns:
                missing_prev = ((df[f'{col}_prev'] == 0) & (df[col] > 0)).sum()
                print(f'{col}: T-1=0但T日>0: {missing_prev}只({missing_prev/total*100:.1f}%)')
    
    await mongo_manager.shutdown()

asyncio.run(main())
