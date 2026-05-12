#!/usr/bin/env python3
"""用Tushare补stock_daily_ak_full - 补pct_chg/pre_close/change，以及缺股票的日线"""
import tushare as ts
import pandas as pd
from pymongo import MongoClient
import time

TOKEN = '2876ea85cb005fb5fa17c809a98174f2d5aae8b1f830110a5ead6211'
pro = ts.pro_api(TOKEN)
db = MongoClient('localhost', 27017)['stock_agent']

def fill_daily_for_date(td_str):
    """补一天stock_daily"""
    td_int = int(td_str)
    try:
        df = pro.daily(trade_date=td_str)
    except Exception as e:
        print(f'  {td_str}: API错误 {e}')
        if 'limit' in str(e).lower() or '频率' in str(e):
            time.sleep(60)
        return 0, 0
    
    if df is None or len(df) == 0:
        return 0, 0
    
    updated = 0
    inserted = 0
    for _, row in df.iterrows():
        fields = {}
        for f in ['open','high','low','close','pre_close','change','pct_chg']:
            v = row.get(f)
            if pd.notna(v):
                fields[f] = float(v)
        
        # vol: 手→股
        if pd.notna(row.get('vol')):
            fields['vol'] = float(row['vol']) * 100
        # amount: 千元→元
        if pd.notna(row.get('amount')):
            fields['amount'] = float(row['amount']) * 1000
        
        if not fields:
            continue
        
        result = db.stock_daily_ak_full.update_one(
            {'ts_code': row['ts_code'], 'trade_date': td_int},
            {'$set': fields}
        )
        if result.matched_count > 0:
            updated += 1
        else:
            fields['ts_code'] = row['ts_code']
            fields['trade_date'] = td_int
            for f in ['is_limit_up','is_limit_down','first_limit_up','first_limit_down',
                       'limit_up_count','limit_down_count','limit_up_yesterday','limit_down_yesterday']:
                fields[f] = 0
            db.stock_daily_ak_full.insert_one(fields)
            inserted += 1
    
    return updated, inserted

# 找数据不足的日期(2026年1-5月)
print('查找stock_daily缺口...')
pipeline = [
    {'$match': {'trade_date': {'$gte': 20260101}}},
    {'$group': {
        '_id': '$trade_date', 
        'count': {'$sum': 1}
    }},
    {'$match': {'count': {'$lt': 5000}}},
    {'$sort': {'_id': 1}}
]
gaps = list(db.stock_daily_ak_full.aggregate(pipeline, allowDiskUse=True))
dates = [str(g['_id']) for g in gaps]
print(f'数据不足5000只的天数: {len(dates)}')
for g in gaps[:5]:
    print(f'  {g["_id"]}: {g["count"]}只')
if len(gaps) > 5:
    print(f'  ... 还有{len(gaps)-5}天')

total_updated = 0
total_inserted = 0
for i, td in enumerate(dates):
    u, ins = fill_daily_for_date(td)
    total_updated += u
    total_inserted += ins
    print(f'  [{i+1}/{len(dates)}] {td}: 更新{u}, 新增{ins}')
    time.sleep(0.35)

print(f'\n完成! 更新{total_updated}, 新增{total_inserted}')
