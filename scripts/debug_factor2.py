#!/usr/bin/env python3
import sys
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')

import asyncio
from backtest_module.backtest_engine.factor_selection.factor_library import FactorLibrary
from backtest_module.backtest_engine.factor_selection.factor_engine import FactorEngine
from core.managers import mongo_manager

async def main():
    print("=== Debug factor calculation v2 ===\n")
    
    factor_engine = FactorEngine(source="ak")
    
    trade_date = "20260105"
    
    await mongo_manager.initialize()
    
    # 获取一只股票看看数据
    # 找一个有历史数据的股票
    result = await mongo_manager.find_many(
        "stock_daily_ak_full",
        {"trade_date": {"$lte": int(trade_date)}, "source": "ak", "ts_code": {"$regex": "^\\d"}},
        projection={"ts_code": 1},
        limit=1
    )
    
    if not result:
        print("No stock found")
        return
    
    test_stock = result[0]["ts_code"]
    print(f"Testing with stock: {test_stock}\n")
    
    # 加载它的数据看看
    factor_def = FactorLibrary.get("limit_up_yesterday")
    data = await factor_engine._load_daily_data([test_stock], "20251201", trade_date, "ak")
    
    print(f"Data loaded: {len(data)} stocks")
    df = data[test_stock]
    print(f"Data shape: {df.shape}")
    print("\nLast 10 rows:")
    print(df.tail(10)[['open', 'close', 'up_limit', 'down_limit']])
    
    # 计算因子
    values = factor_engine._compute_single_factor(data, factor_def, trade_date)
    print(f"\nComputed value: {test_stock} = {values[test_stock]}")
    
    # 看计算过程
    print("\nCalculation: (df['close'] >= df['up_limit'] * 0.998).shift(1).fillna(0)")
    calc = (df['close'] >= df['up_limit'] * 0.998).shift(1).fillna(0)
    print("\nLast 10 values of the calculation:")
    print(calc.tail(10))
    
    await mongo_manager.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
