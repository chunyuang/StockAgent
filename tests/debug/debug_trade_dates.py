
import sys
sys.path.insert(0, './AgentServer')
import asyncio

async def main():
    from core.managers import mongo_manager
    await mongo_manager.initialize()
    
    print('查询20260105-20260115之间的交易日...')
    
    from pymongo import MongoClient
    client = MongoClient('mongodb://localhost:27017/')
    db = client['stock_agent']
    
    dates = sorted(db['stock_daily_ak_full'].distinct('trade_date'))
    print('数据库中所有日期数量:', len(dates))
    print('前20个日期:', dates[:20])
    print()
    
    filtered_dates = [d for d in dates if 20260105 <= d <= 20260115]
    print('目标范围内日期数量:', len(filtered_dates))
    print('目标范围内的日期:', filtered_dates)

asyncio.run(main())
