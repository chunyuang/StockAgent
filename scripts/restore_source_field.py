#!/usr/bin/env python3
import pymongo

client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']
collection = db['stock_daily_ak_full_ak']

# 遍历所有记录，添加source字段为'ak'
cursor = collection.find({}, {'_id': 1})
count = 0
for record in cursor:
    collection.update_one(
        {'_id': record['_id']},
        {'$set': {'source': 'ak'}}
    )
    count += 1

print(f'完成，共恢复{count}条记录的source字段为"ak"')

# 验证
sample = collection.find_one()
print('修改后字段：', list(sample.keys()))
print('source字段值：', sample.get('source'))
