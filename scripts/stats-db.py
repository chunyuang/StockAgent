#!/usr/bin/env python3
from pymongo import MongoClient

c = MongoClient('mongodb://localhost:27017/')
db = c['stock_agent']
count = db['stock_daily_ak_full'].count_documents({})
print(f'Total records: {count}')

min_doc = db['stock_daily_ak_full'].find_one(sort=[('trade_date', 1)])
max_doc = db['stock_daily_ak_full'].find_one(sort=[('trade_date', -1)])
if min_doc and max_doc:
    print(f'Date range: {min_doc["trade_date"]} ~ {max_doc["trade_date"]}')

type_counts = {}
cursor = db['stock_daily_ak_full'].find({}, {'trade_date': 1, '_id': 0}).limit(100)
for doc in cursor:
    t = type(doc['trade_date']).__name__
    type_counts[t] = type_counts.get(t, 0) + 1
print(f'Type counts in sample (100): {type_counts}')

# 统计所有不同日期
dates = db['stock_daily_ak_full'].distinct('trade_date')
print(f'Unique trading days: {len(dates)}')
