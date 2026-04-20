#!/usr/bin/env python3
import asyncio
import sys

sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from core.managers import redis_manager, mongo_manager

async def check_mongo():
    await redis_manager.initialize()
    await mongo_manager.initialize()
    
    print(f"Current database: {mongo_manager.db.name}")
    
    collections = await mongo_manager.db.list_collection_names()
    print(f"Collections: {collections}")
    
    for coll in collections:
        count = await mongo_manager.db[coll].count_documents({})
        print(f"  {coll}: {count} documents")
    
    await redis_manager.close()
    # mongo_manager doesn't need close

if __name__ == "__main__":
    asyncio.run(check_mongo())
