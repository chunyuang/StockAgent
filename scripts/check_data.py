#!/usr/bin/env python3
"""Check MongoDB data for the backtest period"""

import sys
import asyncio
from dotenv import load_dotenv

sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from core.managers import mongo_manager

load_dotenv('/root/.openclaw/workspace/StockAgent/AgentServer/.env')

async def check_data():
    print("=" * 60)
    print("Checking MongoDB data for 20260105 ~ 20260320")
    print("=" * 60)
    
    await mongo_manager.initialize()
    
    # Count total documents
    total = await mongo_manager.db.stock_daily_ak_full.count_documents({})
    print(f"\nTotal documents in stock_daily_ak_full: {total:,}")
    
    # Count documents in date range
    count = await mongo_manager.db.stock_daily_ak_full.count_documents({
        "trade_date": {"$gte": 20260105, "$lte": 20260320}
    })
    print(f"Documents in 20260105 ~ 20260320: {count:,}")
    
    # Count by date
    pipeline = [
        {"$match": {"trade_date": {"$gte": 20260105, "$lte": 20260320}}},
        {"$group": {"_id": "$trade_date", "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}}
    ]
    
    cursor = mongo_manager.db.stock_daily_ak_full.aggregate(pipeline)
    dates = await cursor.to_list(length=100)
    
    print(f"\nTrading days in range: {len(dates)}")
    print("\nFirst 10 days:")
    for d in dates[:10]:
        print(f"  {d['_id']}: {d['count']:,} stocks")
    
    print("\nLast 10 days:")
    for d in dates[-10:]:
        print(f"  {d['_id']}: {d['count']:,} stocks")
    
    # Check if we have any data with the required fields for factors
    print("\n" + "=" * 60)
    print("Checking factor required fields...")
    
    # Get a sample document
    sample = await mongo_manager.db.stock_daily_ak_full.find_one({
        "trade_date": {"$gte": 20260105}
    })
    
    if sample:
        print(f"\nSample document fields: {list(sample.keys())}")
        required_fields = ['open', 'high', 'low', 'close', 'volume', 'ts_code', 'trade_date']
        for f in required_fields:
            if f in sample:
                print(f"  ✅ {f}: {sample.get(f)}")
            else:
                print(f"  ❌ {f}: MISSING")
    
    await mongo_manager.close()
    print("\n" + "=" * 60)

if __name__ == "__main__":
    asyncio.run(check_data())
