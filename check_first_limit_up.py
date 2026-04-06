#!/usr/bin/env python3
import pymongo

# 连接MongoDB
client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client["stock_agent"]
collection = db["stock_daily_ak_full"]

# 统计2026年1月-3月的数据
date_filter = {"trade_date": {"$gte": 20260105, "$lte": 20260320}}

# 1. 检查字段是否存在
sample = collection.find_one(date_filter)
print("✅ 字段检查：")
print(f"   first_limit_up存在: {'first_limit_up' in sample}")
print("="*80)

# 2. 统计first_limit_up分布
count_1 = collection.count_documents({**date_filter, "first_limit_up": 1})
count_0 = collection.count_documents({**date_filter, "first_limit_up": 0})
print(f"📊 first_limit_up分布（20260105~20260320）：")
print(f"   符合条件（=1）：{count_1} 条记录")
print(f"   不符合条件（=0）：{count_0} 条记录")

# 3. 查看示例
if count_1 > 0:
    doc = collection.find_one({**date_filter, "first_limit_up": 1})
    print(f"\n🔍 first_limit_up=1 示例：{doc['ts_code']} 日期:{doc['trade_date']}")
    print(f"   当日涨跌幅：{doc['pct_chg']:.2f}%")
    print(f"   昨日涨跌幅：{collection.find_one({'ts_code': doc['ts_code'], 'trade_date': doc['trade_date']-1}, {'pct_chg':1}).get('pct_chg', 'N/A'):.2f}%")
    print(f"   limit_up_yesterday：{doc['limit_up_yesterday']}")
else:
    print("\n❌ 没有first_limit_up=1的记录，检查计算逻辑：")
    # 检查计算逻辑：当日涨停且昨日未涨停
    sample_date = 20260106
    today_limit_up = collection.count_documents({"trade_date": sample_date, "pct_chg": {"$gte": 9.8}})
    yesterday_limit_up = collection.count_documents({"trade_date": sample_date-1, "pct_chg": {"$gte": 9.8}})
    print(f"   示例日期{sample_date}：当日涨停{today_limit_up}只，昨日涨停{yesterday_limit_up}只")
    print(f"   理论上first_limit_up=1的数量应该为：{max(0, today_limit_up - yesterday_limit_up)}只")
