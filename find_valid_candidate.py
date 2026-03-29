#!/usr/bin/env python3
"""
找一个完全符合半路追涨条件的股票
"""
import pymongo
import pandas as pd

client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']
coll = db['stock_daily_ak_full']

# 遍历20260106的涨停股，找它们次日开盘低于涨停价的
limit_up_20260106 = list(coll.find({
    'trade_date': 20260106,
    '$expr': {'$eq': ['$close', '$up_limit']}
}))

print(f"🔍 20260106共有{len(limit_up_20260106)}只涨停股，正在找次日符合条件的...")

found = False
for stock in limit_up_20260106:
    ts_code = stock['ts_code']
    up_limit_106 = stock['up_limit']
    
    # 查次日数据
    next_day = coll.find_one({
        'ts_code': ts_code,
        'trade_date': 20260107
    })
    
    if not next_day:
        continue
        
    open_107 = next_day['open']
    amount_107 = next_day['amount']
    
    if open_107 < up_limit_106 and amount_107 >= 1000:
        print(f"\n✅ 找到符合条件的股票: {ts_code}")
        print(f"   20260106 涨停价: {up_limit_106}")
        print(f"   20260107 开盘价: {open_107}")
        print(f"   20260107 成交额: {amount_107:.0f}万")
        print(f"   👉 完全符合半路追涨条件！")
        
        # 获取两天的完整数据
        data = list(coll.find({
            'ts_code': ts_code,
            'trade_date': {'$in': [20260106, 20260107]}
        }))
        df = pd.DataFrame(data)
        print("\n📊 完整数据:")
        print(df[['trade_date', 'open', 'close', 'up_limit', 'pre_close', 'amount']])
        found = True
        break

if not found:
    print("\n❌ 20260106的涨停股次日全部高开，没有符合条件的")
    # 换一天找
    dates = sorted(coll.distinct('trade_date', {'trade_date': {'$gte': 20260106, '$lte': 20260120}}))
    for date in dates[1:]:
        prev_date = dates[dates.index(date)-1]
        limit_up_prev = list(coll.find({
            'trade_date': prev_date,
            '$expr': {'$eq': ['$close', '$up_limit']}
        }))
        
        for stock in limit_up_prev:
            ts_code = stock['ts_code']
            up_limit_prev = stock['up_limit']
            current = coll.find_one({'ts_code': ts_code, 'trade_date': date})
            if current and current['open'] < up_limit_prev and current['amount'] >= 1000:
                print(f"\n✅ 找到符合条件的股票: {ts_code}")
                print(f"   日期: {prev_date} 涨停，{date} 开盘低于涨停价")
                print(f"   昨日涨停价: {up_limit_prev}")
                print(f"   今日开盘价: {current['open']}")
                print(f"   今日成交额: {current['amount']:.0f}万")
                exit()
