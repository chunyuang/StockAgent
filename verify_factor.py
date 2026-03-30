#!/usr/bin/env python3
"""
验证核心因子计算是否正确
"""
import pymongo
import pandas as pd

client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']
coll = db['stock_daily_ak_full']

# 拿一只最近有涨停的股票，比如20260106有97只涨停，随便取一只
sample = list(coll.find({
    'trade_date': 20260106,
    '$expr': {'$eq': ['$close', '$up_limit']}
}).limit(1))[0]
ts_code = sample['ts_code']
print(f"📊 测试股票: {ts_code}")

# 获取它的近期数据
data = list(coll.find({
    'ts_code': ts_code,
    'trade_date': {'$gte': 20260104, '$lte': 20260107}
}).sort('trade_date', 1))
df = pd.DataFrame(data)
print("\n📅 原始数据:")
print(df[['trade_date', 'open', 'close', 'up_limit', 'down_limit', 'pre_close', 'amount']])

# 手动计算limit_up_yesterday（昨日是否涨停）
df['is_limit_up'] = df['close'] == df['up_limit']
df['limit_up_yesterday'] = df['is_limit_up'].shift(1).fillna(False).astype(int)

print("\n🧮 因子计算结果:")
print(df[['trade_date', 'is_limit_up', 'limit_up_yesterday']])

print("\n✅ 20260107的limit_up_yesterday应该等于1（因为20260106是涨停），实际值是:", df[df['trade_date']==20260107]['limit_up_yesterday'].values[0])
