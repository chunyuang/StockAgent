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
result = list(db.stock_daily_ak_full.aggregate(pipeline))
yesterday = result[0]['max_date']
print(f"Yesterday: {yesterday}")

# Count limit up yesterday
count = db.stock_daily_ak_full.count_documents({
    'trade_date': yesterday,
    'source': 'ak',
    '$where': 'this.close >= this.up_limit * 0.998'
})

print(f"Yesterday {yesterday} has {count} limit-up stocks")
