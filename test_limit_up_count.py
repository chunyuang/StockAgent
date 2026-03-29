#!/usr/bin/env python3
"""
简单测试：统计每日涨停股数量，验证数据是否正常
"""
import pymongo
from datetime import datetime

client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']
coll = db['stock_daily_ak_full']

# 日期范围
start_date = 20260105
end_date = 20260320

# 获取所有交易日
trade_dates = sorted(coll.distinct('trade_date', {
    'trade_date': {'$gte': start_date, '$lte': end_date}
}))

print("📊 每日涨停股统计:")
print("="*50)

total_limit_up = 0
for date in trade_dates:
    # 查询当日涨停股（收盘价等于涨停价）
    limit_up_count = coll.count_documents({
        'trade_date': date,
        'close': {'$eq': '$up_limit'}  # 收盘价等于涨停价
    })
    
    # 查询当日成交额>=1000万的涨停股
    limit_up_1000w_count = coll.count_documents({
        'trade_date': date,
        'close': {'$eq': '$up_limit'},
        'amount': {'$gte': 1000}  # 成交额>=1000万
    })
    
    total_limit_up += limit_up_count
    print(f"📅 {date} | 涨停股: {limit_up_count:3d}只 | 成交额≥1000万: {limit_up_1000w_count:3d}只")

print("="*50)
print(f"✅ 总涨停股数: {total_limit_up}只")
print(f"✅ 平均每日涨停股: {total_limit_up/len(trade_dates):.1f}只")
