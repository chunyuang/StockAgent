#!/usr/bin/env python3
import sys
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')

import asyncio
from backtest_module.backtest_engine.factor_selection.factor_engine import FactorEngine
from core.managers import mongo_manager

async def main():
    print("=== Debug limit_up_yesterday count ===\n")
    
    factor_engine = FactorEngine(source="ak")
    
    trade_date = "20260105"
    
    await mongo_manager.initialize()
    
    # 获取今日所有股票
    result = await mongo_manager.find_many(
        "stock_daily_ak_full",
        {"trade_date": int(trade_date), "source": "ak"},
        projection={"ts_code": 1},
    )
    
    all_stocks = [doc["ts_code"] for doc in result]
    print(f"Total stocks on {trade_date}: {len(all_stocks)}")
    
    # 计算因子
    factor_configs = [
        {"name": "limit_up_yesterday", "weight": 1, "direction": "asc"},
    ]
    
    df = await factor_engine.compute_factors(set(all_stocks), trade_date, factor_configs, lookback_days=10)
    
    count_1 = len(df[df["limit_up_yesterday"] == 1])
    count_na = df["limit_up_yesterday"].isna().sum()
    
    print("\nStatistics:")
    print(f"  Total: {len(df)}")
    print(f"  limit_up_yesterday is NaN: {count_na}")
    
    if count_1 > 0:
        print(df[df["limit_up_yesterday"] == 1].head(10))
    
    await mongo_manager.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
