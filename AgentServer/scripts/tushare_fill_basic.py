#!/usr/bin/env python3
"""简洁版：用Tushare补daily_basic的turnover_rate/volume_ratio等"""
import tushare as ts
import pandas as pd
from pymongo import MongoClient
import time

TOKEN = '2876ea85cb005fb5fa17c809a98174f2d5aae8b1f830110a5ead6211'
pro = ts.pro_api(TOKEN)
db = MongoClient('localhost', 27017)['stock_agent']

def fill_basic_for_date(td_str):
    """补一天daily_basic"""
    td_int = int(td_str)
    try:
        df = pro.daily_basic(trade_date=td_str)
    except Exception as e:
        print(f'  {td_str}: API错误 {e}')
        if 'limit' in str(e).lower() or '频率' in str(e):
            time.sleep(60)
        return 0
    
    if df is None or len(df) == 0:
        return 0
    
    updated = 0
    for _, row in df.iterrows():
        fields = {}
        for f in ['turnover_rate','turnover_rate_f','volume_ratio','pe_ttm','pe','pb','ps','ps_ttm','close']:
            v = row.get(f)
            if pd.notna(v):
                fields[f] = float(v)
        # turnover_rate: Tushare返回小数(0.0531)→需×100→百分数(5.31)
        if 'turnover_rate' in fields and fields['turnover_rate'] > 0 and fields['turnover_rate'] < 1:
            fields['turnover_rate'] = fields['turnover_rate'] * 100
        if 'turnover_rate_f' in fields and fields['turnover_rate_f'] > 0 and fields['turnover_rate_f'] < 1:
            fields['turnover_rate_f'] = fields['turnover_rate_f'] * 100
        # circ_mv/total_mv: Tushare返回万元, daily_basic标准=亿元, ÷10000
        for k in ['circ_mv', 'total_mv']:
            v = row.get(k)
            if pd.notna(v):
                fields[k] = float(v) / 10000
        # close: 元, 直接存
        v = row.get('close')
        if pd.notna(v):
            fields['close'] = float(v)
        
        if not fields:
            continue
        
        result = db.daily_basic.update_one(
            {'ts_code': row['ts_code'], 'trade_date': td_int},
            {'$set': fields}
        )
        if result.modified_count > 0:
            updated += 1
    
    return updated

# 找缺turnover_rate的日期
print('查找数据缺口...')
pipeline = [
    {'$match': {'trade_date': {'$gte': 20260101}}},
    {'$group': {
        '_id': '$trade_date',
        'total': {'$sum': 1},
        'with_tr': {'$sum': {'$cond': [{'$gt': ['$turnover_rate', 0]}, 1, 0]}}
    }},
    {'$match': {'with_tr': 0}},
    {'$sort': {'_id': 1}}
]
gaps = list(db.daily_basic.aggregate(pipeline, allowDiskUse=True))
dates = [str(g['_id']) for g in gaps]
print(f'需要补 {len(dates)} 天: {dates[0]}~{dates[-1]}')

total_updated = 0
for i, td in enumerate(dates):
    n = fill_basic_for_date(td)
    total_updated += n
    print(f'  [{i+1}/{len(dates)}] {td}: {n}条更新')
    time.sleep(0.35)

print(f'\n完成! 共更新 {total_updated} 条')
