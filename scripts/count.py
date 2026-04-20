import sys
sys.path.insert(0, 'AgentServer')
import pymongo
from core.settings import settings

client = pymongo.MongoClient(settings.mongo.url)
db = client[settings.mongo.database]
collection = db['daily_data']
count = collection.count_documents({})
print(f"Total records: {count}")

# 统计时间范围
pipeline = [
    {"$group": {"_id": "$trade_date", "count": {"$sum": 1}}},
    {"$sort": {"_id": 1}}
]
result = list(collection.aggregate(pipeline))
print(f"\n交易日统计（共 {len(result)} 个交易日）:")
for d in result:
    print(f"  {d['_id']}: {d['count']} 条")
