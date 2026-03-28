#!/usr/bin/env python3
import asyncio
import sys

sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from core.managers import redis_manager, mongo_manager

async def debug(check_date):
    await redis_manager.initialize()
    await mongo_manager.initialize()
    
    check_date = int(check_date)
    print(f"Checking date: {check_date}")
    
    # Get previous trading day
    pipeline = [
        {"$match": {"trade_date": {"$lt": check_date}},
        {"$group": {"_id": None, "max_date": {"$max": "$trade_date"}}},
    ]
    cursor = mongo_manager.db.stock_daily.aggregate(pipeline)
    result = await cursor.to_list(length=1)
    yesterday = result[0]["max_date"]
    print(f"Yesterday: {yesterday}")
    
    # Count how many limit up yesterday
    query = {
        "trade_date": yesterday,
        "source": "ak",
    }
    projection = {"ts_code": 1, "close": 1, "up_limit": 1}
    docs = await mongo_manager.find_many("stock_daily", query, projection)
    
    limit_up_count = 0
    yesterday_up = {}
    for doc in docs:
        if doc["close"] >= doc["up_limit"] * 0.998:
            limit_up_count += 1
            yesterday_up[doc["ts_code"]] = doc["up_limit"]
    
    print(f"Yesterday {yesterday} has {limit_up_count} limit-up stocks")
    
    if limit_up_count == 0:
        return
    
    # Count how many satisfy open_below_limit today
    query = {
        "trade_date": check_date,
        "source": "ak",
    }
    projection = {"ts_code": 1, "open": 1}
    today_docs = await mongo_manager.find_many("stock_daily", query, projection)
    
    satisfy = []
    for doc in today_docs:
        ts_code = doc["ts_code"]
        if ts_code in yesterday_up:
            if doc["open"] < yesterday_up[ts_code]:
                satisfy.append(ts_code)
    
    print(f"Today {check_date} has {len(satisfy)} stocks that satisfy both conditions:")
    print(f"  {satisfy[:20]}")

if __name__ == "__main__":
    check_date = "20260106"
    if len(sys.argv) > 1:
        check_date = sys.argv[1]
    asyncio.run(debug(check_date))
