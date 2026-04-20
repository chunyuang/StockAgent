#!/usr/bin/env python3
import pymongo
import sys

sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')
from core.settings import settings

client = pymongo.MongoClient(settings.mongo.url)
db = client[settings.mongo.database]

print('Adding source="ak" to all stock_daily_ak_full documents...')
result = db['stock_daily_ak_full'].update_many(
    {'source': {'$exists': False}},
    [
        {'$set': {'source': 'ak'}}
    ]
)
print(f'  Modified: {result.modified_count} documents')

print('\nAdding source="ak" to all daily_basic documents...')
result_basic = db['daily_basic'].update_many(
    {'source': {'$exists': False}},
    [
        {'$set': {'source': 'ak'}}
    ]
)
print(f'  Modified: {result_basic.modified_count} documents')

print('\n✅ Done!')
print(f' stock_daily_ak_full: {result.modified_count} updated')
print(f' daily_basic: {result_basic.modified_count} updated')

# 验证
print('\nVerification:')
count_after = db['stock_daily_ak_full'].count_documents({'source': 'ak'})
print(f'  stock_daily_ak_full with source="ak": {count_after}')
count_after_basic = db['daily_basic'].count_documents({'source': 'ak'})
print(f'  daily_basic with source="ak": {count_after_basic}')

client.close()
