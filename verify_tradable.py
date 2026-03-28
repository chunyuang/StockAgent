#!/usr/bin/env python3
import asyncio
import sys

sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from core.managers import redis_manager, mongo_manager

async def verify():
    await redis_manager.initialize()
    await mongo_manager.initialize()
    
    date = 20260106
    result = await mongo_manager.find_many(
        "stock_daily",
        {"trade_date": date},
        projection={"ts_code": 1},
    )
    
    print(f"Date {date}: {len(result)} stocks")
    
    if len(result) > 0:
        codes = [doc["ts_code"] for doc in result]
        print(f"First 10 codes: {codes[:10]}")
    
    # 检查日期范围
    pipeline = [
        {"$group": {"_id": "$trade_date"}},
        {"$sort": {"_id": -1}},
        {"$limit": 20},
    ]
    cursor = mongo_manager.db.stock_daily.aggregate(pipeline)
    dates = await cursor.to_list(length=None)
    print(f"\nLatest 20 dates: {[d['_id'] for d in dates]}")
    
    # 检查 20260105 ~ 20260320
    count = await mongo_manager.db.stock_daily.count_documents({
        "trade_date": {"$gte": 20260105, "$lte": 20260320}
    })
    print(f"\nTotal records in 20260105 ~ 20260320: {count}")
    
    # 检查一条样本，看看 up_limit 是否存在
    sample = await mongo_manager.db.stock_daily.find_one({"trade_date": {"$gte": 20260100}})
    if sample:
        print(f"\nSample document keys: {list(sample.keys())}")
        print(f"Sample: {sample}")
        if 'up_limit' in sample:
            print(f"up_limit: {sample['up_limit']}")
        if 'close' in sample:
            print(f"close: {sample['close']}")

if __name__ == "__main__":
    asyncio.run(verify())
