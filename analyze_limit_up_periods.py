#!/usr/bin/env python3
"""
分析哪个时间段有涨停股
"""
import pymongo
from collections import defaultdict

client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']
coll = db['stock_daily_ak_full']

# 获取所有交易日
all_dates = sorted(coll.distinct('trade_date'))
print(f"📅 当前数据库日期范围: {all_dates[0]} ~ {all_dates[-1]}")
print(f"📊 总交易日: {len(all_dates)}天")

# 按月统计涨停股数量
monthly_counts = defaultdict(int)
daily_counts = {}

for date in all_dates:
    # 统计当日涨停股
    count = coll.count_documents({
        'trade_date': date,
        '$expr': {'$eq': ['$close', '$up_limit']}
    })
    
    daily_counts[date] = count
    month = str(date)[:6]  # 取YYYYMM
    monthly_counts[month] += count

print("\n📊 按月涨停股统计:")
print("="*40)
for month in sorted(monthly_counts.keys()):
    print(f"📅 {month}月 | 总涨停股: {monthly_counts[month]:4d}只")

# 找出有涨停的日期
has_limit_up_dates = [d for d, cnt in daily_counts.items() if cnt > 0]
print(f"\n✅ 有涨停的交易日数量: {len(has_limit_up_dates)}天")
if has_limit_up_dates:
    print(f"📅 有涨停的日期示例: {has_limit_up_dates[:20]}")
else:
    print("❌ 当前数据库所有日期都没有涨停股！")

# 检查一下其他集合有没有数据
other_collections = sorted(db.list_collection_names())
print(f"\n🗄️ 数据库集合列表: {other_collections}")
for coll_name in other_collections:
    if 'stock_daily' in coll_name and coll_name != 'stock_daily_ak_full':
        cnt = db[coll_name].count_documents({})
        print(f"  📂 {coll_name}: {cnt}条记录")
