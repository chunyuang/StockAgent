import pymongo
client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client["stock_agent"]
collection = db["stock_daily_ak_full"]

# 统计有多少文档已经有first_limit_up字段
count = 0
cursor = collection.find({'first_limit_up': {'$exists': True}})
for doc in cursor:
    count += 1
print(f'Number of documents with first_limit_up: {count}')

# 检查一个已知应该有的文档
doc = collection.find_one({'ts_code': '000426.SZ', 'trade_date': 20260105})
if doc:
    print('000426.SZ 20260105 fields:')
    for k in sorted(doc.keys()):
        if k.startswith('first') or k.startswith('limit') or k.startswith('open') or k.startswith('pull'):
            print(f'  {k}: {doc[k]}')
else:
    print('Not found')
