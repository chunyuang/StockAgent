#!/usr/bin/env python3
import pymongo
import pandas as pd
import numpy as np

print("🚀 强制修复所有 ma20=None 的记录")
print()

client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']
coll = db['stock_daily_ak_full']

# 1. 获取所有股票代码
codes = coll.distinct('ts_code')
print(f"总股票数: {len(codes)}")
print()

total_updated = 0

for idx, code in enumerate(codes, 1):
    # 获取完整历史按日期排序
    cursor = coll.find(
        {'ts_code': code},
        {'ts_code': 1, 'trade_date': 1, 'close': 1}
    ).sort('trade_date', 1)
    
    data = list(cursor)
    if len(data) < 20:
        continue
    
    df = pd.DataFrame(data)
    
    # 计算技术指标
    df['ma20'] = df['close'].rolling(20).mean()
    df['amount_20d'] = df['close'].rolling(20).mean()  # 先随便用 close 代替
    
    # 只更新 ma20 是 None 的记录
    for _, row in df.iterrows():
        if pd.notna(row['ma20']):
            result = coll.update_one(
                {'ts_code': code, 'trade_date': int(row['trade_date']), 'ma20': None},
                {'$set': {'ma20': float(row['ma20'])}}
            )
            total_updated += result.modified_count
    
    if idx % 100 == 0:
        print(f"  已处理 {idx:4d}/{len(codes)}, 累计更新 {total_updated:6,d} 条")

print()
print("="*80)
print(f"✅ 完成! 总共更新 {total_updated:,} 条记录")
print("="*80)
