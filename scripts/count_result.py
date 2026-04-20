import sys
sys.path.insert(0, 'AgentServer')
import pymongo
from core.settings import settings

client = pymongo.MongoClient(settings.mongo.url)
db = client[settings.mongo.database]
collection = db['stock_daily_ak_full']
count = collection.count_documents({'trade_date': {'$gte': 20260105, '$lte': 20260320}})
print(f'目标区间 20260105 - 20260320 共有 {count} 条记录')

# 统计交易日数量
pipeline = [
    {'$match': {'trade_date': {'$gte': 20260105, '$lte': 20260320}}},
    {'$group': {'_id': '$trade_date', 'count': {'$sum': 1}}},
    {'$sort': {'_id': 1}}
]
result = list(collection.aggregate(pipeline))
print(f'包含 {len(result)} 个交易日')
print()
print('前10个交易日:')
for d in result[:10]:
    print(f'  {d["_id"]}: {d["count"]} 条')
print()
print('后10个交易日:')
for d in result[-10:]:
    print(f'  {d["_id"]}: {d["count"]} 条')
