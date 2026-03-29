#!/usr/bin/env python3
"""
正确查询涨停股
"""
import pymongo

client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']
coll = db['stock_daily_ak_full']

# 查20260105日的涨停股
pipeline = [
    {'$match': {'trade_date': 20260105}},
    {'$addFields': {'is_limit_up': {'$eq': ['$close', '$up_limit']}}},
    {'$match': {'is_limit_up': True}}
]

limit_up_stocks = list(coll.aggregate(pipeline))
print(f"📅 20260105 涨停股数量: {len(limit_up_stocks)}只")
print(f"\n✅ 前10只涨停股:")
for s in limit_up_stocks[:10]:
    print(f"  {s['ts_code']} | 收盘价: {s['close']} | 涨停价: {s['up_limit']} | 成交额: {s['amount']:.0f}万")

# 统计成交额>=1000万的涨停股
pipeline2 = [
    {'$match': {'trade_date': 20260105, 'amount': {'$gte': 1000}}},
    {'$addFields': {'is_limit_up': {'$eq': ['$close', '$up_limit']}}},
    {'$match': {'is_limit_up': True}}
]
limit_up_1000w = list(coll.aggregate(pipeline2))
print(f"\n✅ 20260105 成交额>=1000万的涨停股: {len(limit_up_1000w)}只")
