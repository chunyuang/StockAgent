#!/usr/bin/env python3
import pymongo

client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']

check_date = 20260106
# Find previous trading day
pipeline = [
    {'$match': {'trade_date': {'$lt': check_date}, 'source': 'ak'}},
    {'$group': {'_id': None, 'max_date': {'$max': '$trade_date'}}},
]
result = list(db.stock_daily.aggregate(pipeline))
yesterday = result[0]['max_date']
print(f"Yesterday: {yesterday}")

# Count limit up yesterday - do it in Python
cursor = db.stock_daily.find(
    {'trade_date': yesterday, 'source': 'ak'},
    {'ts_code': 1, 'close': 1, 'up_limit': 1}
)

count = 0
for doc in cursor:
    if doc['close'] >= doc['up_limit'] * 0.998:
        count += 1

print(f"Yesterday {yesterday} has {count} limit-up stocks")
