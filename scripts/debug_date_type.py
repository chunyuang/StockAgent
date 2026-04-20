#!/usr/bin/env python3
import sys
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')

import asyncio
from backtest_module.backtest_engine.factor_selection.factor_library import FactorLibrary
from backtest_module.backtest_engine.factor_selection.factor_engine import FactorEngine
from core.managers import mongo_manager

async def main():
    print("=== Debug date type issue ===\n")
    
    factor_engine = FactorEngine(source="ak")
    
    trade_date_str = "20260106"
    trade_date_int = int(trade_date_str)
    
    await mongo_manager.initialize()
    
    # 获取一只股票
    result = await mongo_manager.find_many(
        "stock_daily_ak_full",
        {"trade_date": trade_date_int, "source": "ak"},
        projection={"ts_code": 1},
        limit=1
    )
    
    if not result:
        print("No stock found")
        return
    
    test_stock = result[0]["ts_code"]
    print(f"Testing with stock: {test_stock}, date: {trade_date_str}")
    
    # 加载数据
    data = await factor_engine._load_daily_data([test_stock], "20251215", trade_date_str, "ak")
    
    print(f"\nLoaded data: {len(data)} stocks")
    df = data[test_stock]
    print(f"DataFrame shape: {df.shape}")
    print(f"Index type: {df.index.dtype}")
    print(f"First 5 index: {list(df.index[:5])}")
    print(f"Last 5 index: {list(df.index[-5:])}")
    
    # 计算 limit_up_yesterday
    factor_def = FactorLibrary.get("limit_up_yesterday")
    values = factor_engine._compute_single_factor(data, factor_def, trade_date_str)
    
    print(f"\nComputed value: {values}")
    print(f"Value for {test_stock}: {values[test_stock]}")
    
    # 看计算过程
    calc = factor_def.compute_func(df)
    print("\nLast 10 calculation results (limit_up_yesterday):")
    print(calc.tail(10))
    
    await mongo_manager.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
