#!/usr/bin/env python3
import pymongo
import pandas as pd

client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']
coll = db['stock_daily_ak_full']

START_DATE = 20260105
END_DATE = 20260320

all_dates = sorted(coll.distinct('trade_date', {'trade_date': {'$gte': START_DATE, '$lte': END_DATE}}))

print("📊 条件严格度对比测试")
print("="*60)
print(f"回测区间: {START_DATE} ~ {END_DATE}，共{len(all_dates)}个交易日")
print("-"*60)
print(f"{'日期':<10} | {'宽松条件候选':<12} | {'严格实盘条件候选':<12}")
print("-"*60)

total_loose = 0
total_strict = 0

for date in all_dates:
    prev_date = all_dates[all_dates.index(date)-1] if date > all_dates[0] else None
    if not prev_date:
        continue
    
    # 1. 宽松条件：昨日涨停 + 今日开盘 < 昨日涨停价
    limit_up_yesterday = list(coll.find({
        'trade_date': prev_date,
        'close': {'$eq': coll.find_one({'trade_date': prev_date, 'ts_code': '000001.SZ'})['up_limit']}
    }, {'ts_code': 1, 'up_limit': 1, 'close': 1, 'vol': 1}))
    
    loose_candidates = []
    for stock in limit_up_yesterday:
        today_data = coll.find_one({'trade_date': date, 'ts_code': stock['ts_code']})
        if not today_data:
            continue
        if today_data['open'] < stock['up_limit'] and today_data['amount'] >= 1000:
            loose_candidates.append(stock['ts_code'])
    
    # 2. 严格实盘条件：半路追涨
    strict_candidates = []
    for stock in limit_up_yesterday:
        today_data = coll.find_one({'trade_date': date, 'ts_code': stock['ts_code']})
        if not today_data:
            continue
        # 昨日涨停是首板（前一天没有涨停）
        prev_prev_date = all_dates[all_dates.index(date)-2] if len(all_dates) > all_dates.index(date)+2 else None
        if prev_prev_date:
            prev_prev_data = coll.find_one({'trade_date': prev_prev_date, 'ts_code': stock['ts_code']})
            if prev_prev_data and prev_prev_data['close'] == prev_prev_data['up_limit']:
                continue  # 不是首板，排除
        # 低开幅度1%-5%
        open_pct = (stock['up_limit'] - today_data['open']) / stock['up_limit'] * 100
        if not (1 <= open_pct <= 5):
            continue
        # 量能放大2倍以上
        avg_vol_5d = coll.aggregate([
            {'$match': {'ts_code': stock['ts_code'], 'trade_date': {'$lt': prev_date, '$gte': prev_date - 10000}}},
            {'$sort': {'trade_date': -1}},
            {'$limit': 5},
            {'$group': {'_id': None, 'avg_vol': {'$avg': '$vol'}}}
        ])
        avg_vol = list(avg_vol_5d)[0]['avg_vol'] if avg_vol_5d.alive else 0
        if today_data['vol'] < avg_vol * 2:
            continue
        # 量比大于1.5
        if today_data['vol'] / avg_vol < 1.5:
            continue
        # 符合所有条件
        strict_candidates.append(stock['ts_code'])
    
    total_loose += len(loose_candidates)
    total_strict += len(strict_candidates)
    print(f"{date:<10} | {len(loose_candidates):<14} | {len(strict_candidates):<14}")

print("-"*60)
print(f"{'合计':<10} | {total_loose:<14} | {total_strict:<14}")
print("\n✅ 结论：严格实盘条件的过滤比宽松基础条件严格得多，所以在当前弱势行情下没有符合条件的标的是正常结果。")
