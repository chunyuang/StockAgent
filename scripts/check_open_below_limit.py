#!/usr/bin/env python3
import pymongo

# 连接MongoDB
client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client["stock_agent"]
collection = db["stock_daily_ak_full"]

# 检查20260106的open_below_limit字段
date = 20260106
print(f"📅 检查日期: {date}")
print("="*80)

# 1. 检查是否有该字段
sample = collection.find_one({"trade_date": date})
if "open_below_limit" in sample:
    print("✅ open_below_limit字段已存在")
else:
    print("❌ open_below_limit字段不存在")

# 2. 统计值分布
count_1 = collection.count_documents({"trade_date": date, "open_below_limit": 1})
count_0 = collection.count_documents({"trade_date": date, "open_below_limit": 0})
print(f"📊 值分布：1的数量={count_1}, 0的数量={count_0}")

# 3. 查看示例
if count_1 > 0:
    doc = collection.find_one({"trade_date": date, "open_below_limit": 1})
    print(f"\n🔍 示例：{doc['ts_code']}")
    print(f"   pct_chg(昨): {doc.get('pct_chg', 'N/A'):.2f}%")
    print(f"   open(今): {doc.get('open', 'N/A'):.2f}")
    print(f"   high(昨): {doc.get('high', 'N/A'):.2f}")
    print(f"   limit_up_price(昨): {doc.get('close', 'N/A') * 1.1:.2f}")
    print(f"   open_below_limit: {doc['open_below_limit']}")
else:
    print("\n❌ 没有open_below_limit=1的记录，检查计算逻辑")
