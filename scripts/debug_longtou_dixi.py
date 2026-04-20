#!/usr/bin/env python3
"""Debug 龙头低吸 strategy"""

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

async def debug_longtou():
    print("=" * 60)
    print("Debug: 龙头低吸 - 20260226 (middle of the period)")
    print("条件: market_leader = 1 AND pullback_ma5 = 1 AND lhb_buy_in = 1")
    print("=" * 60)
    
    await redis_manager.initialize()
    await mongo_manager.initialize()
    await tushare_manager.initialize()
    await baostock_manager.initialize()
    
    universe_mgr = UniverseManager()
    
    trade_date = "20260226"
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
        {"name": "market_leader", "weight": 1.0},
        {"name": "pullback_ma5", "weight": 0.8},
        {"name": "lhb_buy_in", "weight": 0.5},
    ]
    
    factor_df = await factor_engine.compute_factors(
        universe,
        trade_date,
        factor_configs,
        liquidity_threshold=LIQUIDITY_THRESHOLD,
    )
    
    print(f"\nFactor DF shape: {factor_df.shape}")
    
    print("\n=== 三个条件全部满足统计 ===")
    mask = (
        (factor_df['market_leader'] == 1.0) & 
        (factor_df['pullback_ma5'] >= 0.8) & 
        (factor_df['lhb_buy_in'] == 1.0)
    )
    count_all = mask.sum()
    print(f"三个条件全部满足: {count_all} 只")
    
    if count_all > 0:
        result = factor_df[mask]
        print("\n满足条件的股票:")
        for _, row in result.iterrows():
            print(f"  {row['ts_code']}: ml={row['market_leader']:.0f} pm5={row['pullback_ma5']:.2f} lhb={row['lhb_buy_in']:.0f} amount={row['amount']:.0f}")
    
    print("\n" + "=" * 60)

if __name__ == "__main__":
    asyncio.run(debug_longtou())
