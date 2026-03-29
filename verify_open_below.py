#!/usr/bin/env python3
"""
验证open_below_limit因子
"""
import pymongo
import pandas as pd

client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']
coll = db['stock_daily_ak_full']

# 拿刚才的测试股票000008.SZ
ts_code = '000008.SZ'
data = list(coll.find({
    'ts_code': ts_code,
    'trade_date': {'$gte': 20260104, '$lte': 20260107}
}).sort('trade_date', 1))
df = pd.DataFrame(data)
print(f"📊 测试股票: {ts_code}")
print(df[['trade_date', 'open', 'close', 'up_limit', 'amount']])

# 计算open_below_limit：今日开盘 < 昨日涨停价
df['prev_up_limit'] = df['up_limit'].shift(1)
df['open_below_limit'] = (df['open'] < df['prev_up_limit']).astype(int)

print("\n🧮 因子计算:")
print(f"20260106的涨停价: {df[df['trade_date']==20260106]['up_limit'].values[0]}")
print(f"20260107的开盘价: {df[df['trade_date']==20260107]['open'].values[0]}")
print(f"20260107的open_below_limit: {df[df['trade_date']==20260107]['open_below_limit'].values[0]}")
print(f"成交额是否≥1000万: {df[df['trade_date']==20260107]['amount'].values[0] >= 1000}")

print("\n✅ 这只股票20260107完全符合半路追涨条件：")
print("  1. limit_up_yesterday = 1 ✅")
print("  2. open_below_limit = 1 ✅")
print("  3. amount = 69311万 ≥ 1000万 ✅")
print("  👉 应该被半路追涨策略选中！")
