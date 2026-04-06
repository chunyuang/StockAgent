#!/usr/bin/env python3
import pymongo

# 连接MongoDB
client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client["stock_agent"]
collection = db["stock_daily_ak_full"]

# 统计2026年1月-3月的数据
date_filter = {"trade_date": {"$gte": 20260101, "$lte": 20260331}}

# 1. 检查字段是否存在
sample = collection.find_one(date_filter)
print("✅ 字段检查：")
print(f"   open_below_limit存在: {'open_below_limit' in sample}")
print(f"   open_above_limit存在: {'open_above_limit' in sample}")
print(f"   limit_up_yesterday存在: {'limit_up_yesterday' in sample}")
print("="*80)

# 2. 统计open_below_limit分布
obl_count_1 = collection.count_documents({"trade_date": {"$gte": 20260105, "$lte": 20260320}, "open_below_limit": 1})
obl_count_0 = collection.count_documents({"trade_date": {"$gte": 20260105, "$lte": 20260320}, "open_below_limit": 0})
print(f"📊 open_below_limit分布（20260105~20260320）：")
print(f"   符合条件（=1）：{obl_count_1} 条记录")
print(f"   不符合条件（=0）：{obl_count_0} 条记录")

# 3. 统计open_above_limit分布
oal_count_1 = collection.count_documents({"trade_date": {"$gte": 20260105, "$lte": 20260320}, "open_above_limit": 1})
oal_count_0 = collection.count_documents({"trade_date": {"$gte": 20260105, "$lte": 20260320}, "open_above_limit": 0})
print(f"\n📊 open_above_limit分布（20260105~20260320）：")
print(f"   符合条件（=1）：{oal_count_1} 条记录")
print(f"   不符合条件（=0）：{oal_count_0} 条记录")

# 4. 查看示例
if obl_count_1 > 0:
    doc = collection.find_one({"trade_date": {"$gte": 20260105, "$lte": 20260320}, "open_below_limit": 1})
    print(f"\n🔍 open_below_limit=1 示例：{doc['ts_code']} 日期:{doc['trade_date']}")
    print(f"   昨日收盘价：{doc['prev_close']:.2f}")
    print(f"   昨日涨停价：{doc['limit_up_price_yesterday']:.2f}")
    print(f"   今日开盘价：{doc['open']:.2f}")
    print(f"   昨日是否涨停：{doc['limit_up_yesterday']}")
