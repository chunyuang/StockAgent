#!/usr/bin/env python3
import sys
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')

import asyncio
import pandas as pd
import numpy as np
from backtest_module.backtest_engine.factor_selection.factor_library import FactorLibrary
from backtest_module.backtest_engine.factor_selection.factor_engine import FactorEngine
from core.managers import mongo_manager

async def main():
    print("=== Debug date type issue v2 ===\n")
    
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
    print(f"Index: {list(df.index)}")
    
    # 测试 membership
    print(f"\nChecking membership: '{trade_date_str}' in index? {trade_date_str in df.index}")
    print(f"Checking membership: {trade_date_int} in index? {trade_date_int in df.index}")
    
    # 计算因子
    factor_def = FactorLibrary.get("limit_up_yesterday")
    factor_series = factor_def.compute_func(df)
    print(f"\nfactor_series shape: {factor_series.shape}")
    print(f"factor_series tail:\n{factor_series.tail(10)}")
    
    # get value
    if trade_date_int in factor_series.index:
        value = factor_series.loc[trade_date_int]
        print(f"\nValue at {trade_date_int} = {value}")
    elif len(factor_series) > 0:
        value = factor_series.iloc[-1]
        print(f"\nValue (iloc[-1]) = {value}")
    else:
        value = np.nan
        print("\nValue = NaN (len=0)")
    
    print(f"\nFinal value is NaN? {pd.isna(value)}")
    
    await mongo_manager.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
