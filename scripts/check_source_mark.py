#!/usr/bin/env python3
"""Check if all AKShare data has source mark"""

import sys
import asyncio
from dotenv import load_dotenv

sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from core.managers import mongo_manager

load_dotenv('/root/.openclaw/workspace/StockAgent/AgentServer/.env')

async def check_source():
    print("=" * 60)
    print("Checking source marking for AKShare data")
    print("=" * 60)
    
    await mongo_manager.initialize()
    
    # Check stock_daily_ak_full
    print("\n1. Checking stock_daily_ak_full:")
    total_ak = await mongo_manager.db.stock_daily_ak_full.count_documents({"source": "ak"})
    total_all = await mongo_manager.db.stock_daily_ak_full.count_documents({})
    print(f"   Total documents: {total_all:,}")
    print(f"   AKShare marked: {total_ak:,}")
    print(f"   Percentage: {total_ak/total_all*100:.1f}%")
    
    # Check daily_basic
    print("\n2. Checking daily_basic:")
    total_ak_db = await mongo_manager.db.daily_basic.count_documents({"source": "ak"})
    total_all_db = await mongo_manager.db.daily_basic.count_documents({})
    print(f"   Total documents: {total_all_db:,}")
    print(f"   AKShare marked: {total_ak_db:,}")
    print(f"   Percentage: {total_ak_db/total_all_db*100:.1f}%")
    
    # Check if any unmarked in date range
    print("\n3. Checking 20260105 ~ 20260320 in daily_basic (should all be AK):")
    count_unmarked = await mongo_manager.db.daily_basic.count_documents({
        "trade_date": {"$gte": 20260105, "$lte": 20260320},
        "source": {"$ne": "ak"}
    })
    count_ak = await mongo_manager.db.daily_basic.count_documents({
        "trade_date": {"$gte": 20260105, "$lte": 20260320},
        "source": "ak"
    })
    print(f"   AKShare marked: {count_ak:,}")
    print(f"   Not marked (possible Tushare): {count_unmarked:,}")
    
    # Add source mark if needed
    if count_unmarked > 0:
        print("\n⚠️  Found unmarked documents in date range! Need to add source mark.")
        result = await mongo_manager.db.daily_basic.update_many(
            {"trade_date": {"$gte": 20260105, "$lte": 20260320}, "source": {"$ne": "ak"}},
            {"$set": {"source": "ak"}}
        )
        print(f"   ✅ Updated {result.modified_count} documents")
    else:
        print("\n✅ All documents already marked as source='ak'")
    
    await mongo_manager.close()
    
    print("\n" + "=" * 60)

if __name__ == "__main__":
    asyncio.run(check_source())
