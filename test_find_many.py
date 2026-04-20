
import asyncio
import sys
import os

# Add the project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'AgentServer'))

from core.managers.mongo_manager import mongo_manager

async def test():
    await mongo_manager.initialize()
    
    query = {'trade_date': 20260113}
    print(f'Querying stock_daily_ak_full with {query}')
    
    docs = await mongo_manager.find_many('stock_daily_ak_full', query)
    print(f'Total docs found: {len(docs)}')
    
    if len(docs) > 0:
        print(f'First doc ts_code: {docs[0]["ts_code"]}, trade_date: {docs[0]["trade_date"]}, type: {type(docs[0]["trade_date"])}')
    
    # Check if our two candidates are in it
    candidates = ['002207.SZ', '003007.SZ']
    found = 0
    for doc in docs:
        if doc['ts_code'] in candidates:
            print(f'✅ Found candidate: {doc["ts_code"]}, close={doc["close"]}, ts_code type: {type(doc["ts_code"])}')
            found += 1
    
    print(f'Total candidates found: {found}/{len(candidates)}')
    
asyncio.run(test())
