#!/usr/bin/env python3
import pymongo

# 连接MongoDB
client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client["stock_agent"]
collection = db["stock_daily_ak_full"]

# 1. 检查字段是否存在
sample = collection.find_one({"trade_date": 20260106})
print("="*80)
print("🔍 检查20260106的记录字段：")
if sample:
    fields = list(sample.keys())
    print("包含涨跌停相关字段：")
    for f in ["limit_up_yesterday", "first_limit_up", "limit_up_count", "volume_ratio", "market_leader"]:
        if f in fields:
            print(f"   ✅ {f}: {sample[f]}")
        else:
            print(f"   ❌ {f}: 字段不存在")
else:
    print("❌ 20260106无记录")

# 2. 统计有多少条limit_up_yesterday=1的记录
count = collection.count_documents({"limit_up_yesterday": 1})
print(f"\n📊 全库中limit_up_yesterday=1的记录数：{count}条")

# 3. 查看20260106的limit_up_yesterday=1的记录数
count_20260106 = collection.count_documents({"trade_date": 20260106, "limit_up_yesterday": 1})
print(f"📅 20260106的limit_up_yesterday=1的记录数：{count_20260106}条")

# 4. 查看具体的几条记录
if count_20260106 > 0:
    print("\n🔍 20260106的limit_up_yesterday=1的示例：")
    docs = collection.find({"trade_date": 20260106, "limit_up_yesterday": 1}).limit(5)
    for doc in docs:
        print(f"   {doc['ts_code']}: limit_up_yesterday={doc['limit_up_yesterday']}, pct_chg={doc.get('pct_chg', 'N/A'):.2f}%")
