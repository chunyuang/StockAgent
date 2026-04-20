#!/usr/bin/env python3
"""Check field names in MongoDB"""

import sys
import asyncio
from dotenv import load_dotenv

sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from core.managers import mongo_manager

load_dotenv('/root/.openclaw/workspace/StockAgent/AgentServer/.env')

async def check_fields():
    print("=" * 60)
    print("Checking field names for factor computation")
    print("=" * 60)
    
    await mongo_manager.initialize()
    
    # Get a sample
    sample = await mongo_manager.db.stock_daily_ak_full.find_one({
        "trade_date": {"$gte": 20260105}
    })
    
    print("\nFull sample document:")
    for key, value in sample.items():
        print(f"  {key:15s} = {value}")
    
    # Check limit_up_yesterday factor needs up_limit/down_limit
    print("\n" + "=" * 60)
    print("Checking required fields for key factors:")
    
    required_checks = [
        ("up_limit", "昨日涨停需要 (limit_up_yesterday)"),
        ("down_limit", "昨日跌停需要 (limit_down_yesterday)"),
        ("vol", "AKShare 保存的成交量"), 
        ("volume", "代码预期的成交量"),
    ]
    
    for field, description in required_checks:
        if field in sample:
            print(f"  ✅ {field}: {sample.get(field)} - {description}")
        else:
            print(f"  ❌ {field}: MISSING - {description}")
    
    # Count how many have up_limit not null
    count_has_up_limit = await mongo_manager.db.stock_daily_ak_full.count_documents({
        "trade_date": {"$gte": 20260105},
        "up_limit": {"$ne": None}
    })
    
    total_in_range = await mongo_manager.db.stock_daily_ak_full.count_documents({
        "trade_date": {"$gte": 20260105, "$lte": 20260320}
    })
    
    print(f"\nup_limit not null: {count_has_up_limit:,} / {total_in_range:,}")
    
    # Check some limit_up_yesterday candidates
    print("\nChecking recent stocks that had limit up:")
    cursor = mongo_manager.db.stock_daily_ak_full.find({
        "trade_date": {"$gte": 20260310, "$lte": 20260318},
        "up_limit": {"$ne": None}
    }).limit(5)
    
    docs = await cursor.to_list(length=5)
    for doc in docs:
        pct = (doc['close'] - doc['pre_close']) / doc['pre_close'] * 100
        print(f"  {doc['ts_code']} {doc['trade_date']}: close={doc['close']} pre_close={doc['pre_close']} up_limit={doc['up_limit']} pct={pct:.2f}%")
    
    await mongo_manager.initialize()

if __name__ == "__main__":
    asyncio.run(check_fields())
