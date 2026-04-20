#!/usr/bin/env python3
"""Debug 首板打板 strategy"""

import sys
import asyncio
import logging
from dotenv import load_dotenv

sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from core.managers import (
    redis_manager,
    mongo_manager,
    tushare_manager,
    baostock_manager,
)

from backtest_module.backtest_engine.factor_selection.universe import UniverseManager, UniverseType, ExcludeRule
from backtest_module.backtest_engine.factor_selection.factor_engine import FactorEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv('/root/.openclaw/workspace/StockAgent/AgentServer/.env')

LIQUIDITY_THRESHOLD = 1000 * 10000  # 1000万

async def debug_shouban():
    print("=" * 60)
    print("Debug: 首板打板 strategy - check 20260106")
    print("条件: limit_up_yesterday = 1 AND first_limit_up = 1")
    print("=" * 60)
    
    await redis_manager.initialize()
    await mongo_manager.initialize()
    await tushare_manager.initialize()
    await baostock_manager.initialize()
    
    universe_mgr = UniverseManager()
    
    trade_date = "20260106"
    exclude_rules = [ExcludeRule.ST, ExcludeRule.NEW_STOCK]
    
    print(f"\nGetting universe for {trade_date}...")
    universe = await universe_mgr.get_universe(
        UniverseType.ALL_A,
        trade_date,
        exclude_rules,
    )
    
    print(f"Base universe after exclusion: {len(universe)} stocks")
    
    print("\nComputing factors...")
    factor_engine = FactorEngine(source="ak")
    factor_configs = [
        {"name": "limit_up_yesterday", "weight": 1.0},
        {"name": "first_limit_up", "weight": 1.0},
    ]
    
    factor_df = await factor_engine.compute_factors(
        universe,
        trade_date,
        factor_configs,
        liquidity_threshold=LIQUIDITY_THRESHOLD,
    )
    
    print(f"\nFactor DF shape: {factor_df.shape}")
    print(f"Columns: {list(factor_df.columns)}")
    
    print("\n=== limit_up_yesterday == 1 统计 ===")
    count_limit_up = (factor_df['limit_up_yesterday'] == 1.0).sum()
    print(f"limit_up_yesterday = 1: {count_limit_up} 只")
    
    print("\n=== limit_up_yesterday == 1 AND first_limit_up == 1 统计 ===")
    mask = (factor_df['limit_up_yesterday'] == 1.0) & (factor_df['first_limit_up'] == 1.0)
    count_both = mask.sum()
    print(f"两个条件都满足: {count_both} 只")
    
    if count_both > 0:
        result = factor_df[mask]
        print("\n满足条件的股票:")
        for _, row in result.iterrows():
            print(f"  {row['ts_code']}: limit_up={row['limit_up_yesterday']:.0f}, first_limit_up={row['first_limit_up']:.0f}, amount={row['amount']:.0f}")
    
    print("\n" + "=" * 60)

if __name__ == "__main__":
    asyncio.run(debug_shouban())
