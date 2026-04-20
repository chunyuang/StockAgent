#!/usr/bin/env python3
import sys
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')

import asyncio
from backtest_module.backtest_engine.factor_selection.factor_engine import FactorEngine

async def main():
    print("=== Debug factor calculation ===\n")
    
    factor_engine = FactorEngine(source="ak")
    
    # 随便选一个日期
    trade_date = "20260105"
    # 取 10 只股票测试
    from core.managers import mongo_manager
    await mongo_manager.initialize()
    
    # 获取当日所有股票
    result = await mongo_manager.find_many(
        "stock_daily_ak_full",
        {"trade_date": int(trade_date), "source": "ak"},
        projection={"ts_code": 1},
    )
    
    all_stocks = [doc["ts_code"] for doc in result]
    print(f"Total stocks on {trade_date}: {len(all_stocks)}")
    
    # 测试计算 limit_up_yesterday
    # 我们需要 limit_up_yesterday = 1
    factor_configs = [
        {"name": "limit_up_yesterday", "weight": 1, "direction": "asc"},
        {"name": "open_below_limit", "weight": 1, "direction": "asc"},
    ]
    
    # 只取前 50 只测试计算速度
    test_stocks = all_stocks[:50]
    print(f"\nTesting with first {len(test_stocks)} stocks...")
    
    df = await factor_engine.compute_factors(set(test_stocks), trade_date, factor_configs, lookback_days=10)
    
    print(f"\nResult shape: {df.shape}")
    print("\nFirst 20 rows:")
    print(df[["ts_code", "limit_up_yesterday", "open_below_limit"]].head(20))
    
    # 统计有多少 limit_up_yesterday = 1
    count_1 = len(df[df["limit_up_yesterday"] == 1])
    print(f"\ncount where limit_up_yesterday = 1: {count_1}")
    
    await mongo_manager.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
