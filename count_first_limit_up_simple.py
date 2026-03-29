#!/usr/bin/env python3
import pymongo
import pandas as pd
from tqdm import tqdm

client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']
coll = db['stock_daily_ak_full']

START_DATE = 20260105
END_DATE = 20260320

# 预加载所有股票的所有数据
print("⏳ 预加载数据...")
all_data = {}
all_ts_codes = coll.distinct('ts_code')
for ts_code in tqdm(all_ts_codes[:1000]):  # 先取1000只统计，足够反映情况
    data = list(coll.find({
        'ts_code': ts_code,
        'trade_date': {'$gte': 20251201, '$lte': END_DATE}
    }).sort('trade_date', 1))
    if len(data) >= 20:
        df = pd.DataFrame(data)
        df['is_limit_up'] = abs(df['close'] - df['up_limit']) < 0.01
        all_data[ts_code] = df

print(f"✅ 加载完成，共{len(all_data)}只股票")

all_dates = sorted(coll.distinct('trade_date', {'trade_date': {'$gte': START_DATE, '$lte': END_DATE}}))
print(f"📅 统计区间: {START_DATE} ~ {END_DATE}，共{len(all_dates)}个交易日")

print("="*60)
print(f"{'日期':<10} | {'涨停数':<6} | {'首板数':<6}")
print("-"*60)

total_first = 0
total_limit_up = 0

for date in all_dates:
    limit_up = 0
    first_limit_up = 0
    for ts_code, df in all_data.items():
        pos = df[df['trade_date'] == date].index
        if len(pos) == 0:
            continue
        pos = pos[0]
        if pos < 3:
            continue
        if df.iloc[pos]['is_limit_up']:
            limit_up += 1
            # 前3天没有涨停就是首板
            if not df.iloc[pos-3:pos]['is_limit_up'].any():
                first_limit_up += 1
    total_limit_up += limit_up
    total_first += first_limit_up
    print(f"{date:<10} | {limit_up:<6} | {first_limit_up:<6}")

print("-"*60)
print(f"平均每日涨停: {total_limit_up/len(all_dates):.1f}只")
print(f"平均每日首板: {total_first/len(all_dates):.1f}只")
