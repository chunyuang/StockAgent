#!/usr/bin/env python3
import asyncio
import sys

sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from core.managers import redis_manager, mongo_manager

async def simple_check():
    await redis_manager.initialize()
    await mongo_manager.initialize()
    
    # 数一数总记录
    total = await mongo_manager.db.daily.count_documents({})
    print(f"Total documents: {total}")
    
    # 数一数有多少不同日期
    pipeline = [
        {"$group": {"_id": "$trade_date_int"}},
        {"$count": "total"},
    ]
    cursor = mongo_manager.db.daily.aggregate(pipeline)
    result = await cursor.to_list(length=None)
    print(f"Total dates: {result}")
    
    # 看一下最新日期
    pipeline = [
        {"$group": {"_id": "$trade_date_int"}},
        {"$sort": {"_id": -1}},
        {"$limit": 10},
    ]
    cursor = mongo_manager.db.daily.aggregate(pipeline)
    result = await cursor.to_list(length=None)
    print(f"Latest 10 dates: {[d['_id'] for d in result]}")
    
    # 看一条样本
    sample = await mongo_manager.db.daily.find_one({"trade_date_int": {"$gte": 20260100}})
    if sample:
        print(f"\nSample document keys: {list(sample.keys())}")
        print(f"Sample document: {sample}")
    else:
        print("\nNo sample found for >= 20260100")
    
    # 计算 20260105 ~ 20260320 有多少条记录
    count = await mongo_manager.db.daily.count_documents({
        "trade_date_int": {"$gte": 20260105, "$lte": 20260320}
    })
    print(f"\nRecords in 20260105 ~ 20260320: {count}")
    
    await redis_manager.close()
    await mongo_manager.close()

if __name__ == "__main__":
    asyncio.run(simple_check())
