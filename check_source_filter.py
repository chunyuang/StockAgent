#!/usr/bin/env python3
import asyncio
import sys

sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/backtest_module')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from core.managers import redis_manager, mongo_manager

async def check_source():
    await redis_manager.initialize()
    await mongo_manager.initialize()
    
    # 统计不同 source 的数据量
    for source in [None, "ak", "ts"]:
        if source is None:
            query = {"trade_date": {"$gte": 20260105, "$lte": 20260320}}
        else:
            query = {"trade_date": {"$gte": 20260105, "$lte": 20260320}, "source": source}
        
        count = await mongo_manager.db.stock_daily.count_documents(query)
        print(f"source={source}: {count} records")
    
    # 看看 sample
    result = await mongo_manager.find_many(
        "stock_daily",
        {"trade_date": {"$gte": 20260105, "$lte": 20260320}, "source": "ak"},
        projection={"ts_code": 1, "source": 1},
    )
    
    print(f"\nFirst 5 samples with source=ak:")
    for r in result[:5]:
        print(f"  {r}")

if __name__ == "__main__":
    asyncio.run(check_source())
