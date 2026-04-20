#!/usr/bin/env python3
"""Debug why first strategy has zero signals"""

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

STRATEGY_FILTERS = [
    ("limit_up_yesterday", 1.0),
    ("open_below_limit", 1.0),
]

LIQUIDITY_THRESHOLD = 1000 * 10000  # 1000万

async def debug_first_strategy():
    print("=" * 60)
    print("Debug: 半路追涨 strategy on 20260105 (first day)")
    print("=" * 60)
    
    await redis_manager.initialize()
    await mongo_manager.initialize()
    await tushare_manager.initialize()
    await baostock_manager.initialize()
    
    universe_mgr = UniverseManager()
    
    trade_date = "20260105"
    exclude_rules = [ExcludeRule.ST, ExcludeRule.NEW_STOCK]
    
    print(f"\nGetting universe for {trade_date}...")
    universe = await universe_mgr.get_universe(
        UniverseType.ALL_A,
        trade_date,
        exclude_rules,
    )
    
    print(f"Base universe after exclusion: {len(universe)} stocks")
    
    # Now compute factors
    print("\nComputing factors...")
    factor_engine = FactorEngine(source="ak")
    factor_configs = [
        {"name": "limit_up_yesterday", "weight": 1.0},
        {"name": "open_below_limit", "weight": 1.0},
    ]
    
    factor_df = await factor_engine.compute_factors(
        universe,
        trade_date,
        factor_configs,
        liquidity_threshold=LIQUIDITY_THRESHOLD,
    )
    
    print(f"\nFactor DF shape: {factor_df.shape}")
    print(f"Columns: {list(factor_df.columns)}")
    
    if 'amount' in factor_df.columns:
        print("\namount column present ✓")
        print(f"Number of stocks with amount >= {LIQUIDITY_THRESHOLD}: {(factor_df['amount'] >= LIQUIDITY_THRESHOLD).sum()}")
        print(f"amount min: {factor_df['amount'].min()}, max: {factor_df['amount'].max()}")
        print(f"amount mean: {factor_df['amount'].mean():.2f}")
    else:
        print("\n❌ amount column missing! This is the bug!")
    
    if 'limit_up_yesterday' in factor_df.columns:
        print("\nlimit_up_yesterday value counts:")
        print(factor_df['limit_up_yesterday'].value_counts())
    
    if 'open_below_limit' in factor_df.columns:
        print("\nopen_below_limit value counts:")
        print(factor_df['open_below_limit'].value_counts())
    
    # Select top stocks
    selected = factor_engine.select_top_stocks(factor_df, 5, LIQUIDITY_THRESHOLD)
    print(f"\nSelected {len(selected)} stocks after liquidity filter: {selected}")
    
    # Show details of selected
    if len(selected) > 0 and 'amount' in factor_df.columns:
        print("\nSelected stocks amount:")
        for ts_code in selected:
            amount = factor_df[factor_df['ts_code'] == ts_code]['amount'].iloc[0]
            print(f"  {ts_code}: amount = {amount:.0f} (>= {LIQUIDITY_THRESHOLD})")
    
    await mongo_manager.close()
    print("\n" + "=" * 60)

if __name__ == "__main__":
    asyncio.run(debug_first_strategy())
