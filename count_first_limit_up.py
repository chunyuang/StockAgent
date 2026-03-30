#!/usr/bin/env python3
import pymongo
import pandas as pd

client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']
coll = db['stock_daily_ak_full']

START_DATE = 20260105
END_DATE = 20260320

all_dates = sorted(coll.distinct('trade_date', {'trade_date': {'$gte': START_DATE, '$lte': END_DATE}}))
print(f"📅 统计区间: {START_DATE} ~ {END_DATE}，共{len(all_dates)}个交易日")
print("="*60)
print(f"{'日期':<10} | {'总涨停':<6} | {'首板数量':<6} | {'连板数量':<6}")
print("-"*60)

total_first = 0
total_limit_up = 0

for date in all_dates:
    # 当日涨停股
    limit_up_stocks = list(coll.find({
        'trade_date': date,
        'close': {'$subtract': ['$up_limit', '$close']} <= 0.01
    }, {'ts_code': 1}))
    limit_up_codes = {s['ts_code'] for s in limit_up_stocks}
    total_limit_up += len(limit_up_codes)
    
    first_limit_up = 0
    for ts_code in limit_up_codes:
        # 查前3天有没有涨停
        prev_dates = [d for d in all_dates if d < date][-3:]
        has_prev_limit_up = False
        for d in prev_dates:
            prev_doc = coll.find_one({'trade_date': d, 'ts_code': ts_code})
            if prev_doc and abs(prev_doc['close'] - prev_doc['up_limit']) < 0.01:
                has_prev_limit_up = True
                break
        if not has_prev_limit_up:
            first_limit_up += 1
    
    total_first += first_limit_up
    print(f"{date:<10} | {len(limit_up_codes):<6} | {first_limit_up:<6} | {len(limit_up_codes)-first_limit_up:<6}")

print("-"*60)
print(f"✅ 总计: 总涨停{total_limit_up}只，首板{total_first}只，连板{total_limit_up-total_first}只")
print(f"平均每日首板: {total_first/len(all_dates):.1f}只")
