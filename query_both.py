#!/usr/bin/env python3
import pymongo

client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']

check_date = 20260106

# Find previous trading day
pipeline = [
    {'$match': {'trade_date': {'$lt': check_date}, 'source': 'ak'}},
    {'$group': {'_id': None, 'max_date': {'$max': '$trade_date'}},
]
result = list(db.stock_daily.aggregate(pipeline))
yesterday = result[0]['max_date']
print(f"Yesterday: {yesterday}, Today: {check_date}")

# Get all limit up from yesterday
yesterday_limit_up = {}
cursor = db.stock_daily.find(
    {'trade_date': yesterday, 'source': 'ak'},
    {'ts_code': 1, 'close': 1, 'up_limit': 1}
)
for doc in cursor:
    if doc['close'] >= doc['up_limit'] * 0.998:
        yesterday_limit_up[doc['ts_code']] = doc['up_limit']

print(f"Yesterday limit-up count: {len(yesterday_limit_up)}")

# Check today: how many satisfy open < yesterday up_limit
satisfy = []
cursor = db.stock_daily.find(
    {'trade_date': check_date, 'source': 'ak'},
    {'ts_code': 1, 'open': 1}
)
for doc in cursor:
    ts_code = doc['ts_code']
    if ts_code in yesterday_limit_up:
        yesterday_up = yesterday_limit_up[ts_code]
        if doc['open'] < yesterday_up:
            satisfy.append(ts_code)

print(f"\nToday satisfy (limit_up_yesterday AND open_below_limit): {len(satisfy)}")
print(f"Satisfy codes: {satisfy[:20]}")
