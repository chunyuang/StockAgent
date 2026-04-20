#!/usr/bin/env python3
import pymongo

client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']
coll = db['stock_daily_ak_full']

START_DATE = 20260105
END_DATE = 20260320

# 获取所有交易日
all_dates = sorted(coll.distinct('trade_date', {'trade_date': {'$gte': START_DATE, '$lte': END_DATE}}))
print(f"📅 统计区间: {START_DATE} ~ {END_DATE}，共{len(all_dates)}个交易日")
print("="*60)
print(f"{'日期':<10} | {'涨停股数':<8}")
print("-"*60)

total_limit_up = 0
date_stats = []
for date in all_dates:
    # 获取当日所有股票的涨停价（用平安银行的涨停价作为基准，涨跌幅10%）
    sample = coll.find_one({'trade_date': date, 'ts_code': '000001.SZ'})
    if not sample:
        continue
    up_limit_pct = (sample['up_limit'] - sample['pre_close']) / sample['pre_close']
    
    # 统计当日所有涨停的股票（close == up_limit）
    cnt = coll.count_documents({
        'trade_date': date,
        'close': {'$eq': {'$toDouble': '$up_limit'}}
    })
    
    total_limit_up += cnt
    date_stats.append({'date': date, 'count': cnt})
    print(f"{date:<10} | {cnt:<8}")

print("-"*60)
avg = total_limit_up / len(all_dates)
print(f"✅ 区间总涨停股: {total_limit_up}只，平均每日{avg:.1f}只")
print(f"📊 单日最高涨停: {max([d['count'] for d in date_stats])}只，单日最低涨停: {min([d['count'] for d in date_stats])}只")

# 统计涨停股≥10只的天数
high_days = len([d for d in date_stats if d['count'] >= 10])
print(f"📈 涨停股≥10只的天数: {high_days}天，占比{high_days/len(all_dates)*100:.1f}%")
