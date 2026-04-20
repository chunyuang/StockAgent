#!/usr/bin/env python3
"""
数据迁移脚本：将 stock_daily_ak_full 中 source="ak" 的数据迁移到 stock_daily_ak_full_ak
"""
import pymongo

client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']

# 检查源数据
count_ak = db.stock_daily_ak_full.count_documents({"source": "ak"})
print(f"Found {count_ak} documents with source='ak' in stock_daily_ak_full")

if count_ak == 0:
    print("No AK data found, nothing to migrate")
    exit(0)

# 新建集合，复制数据
print("Migrating to stock_daily_ak_full_ak...")
# 先清空目标集合（如果存在）
if "stock_daily_ak_full_ak" in db.list_collection_names():
    db.stock_daily_ak_full_ak.delete_many({})

# 复制数据
docs = db.stock_daily_ak_full.find({"source": "ak"})
db.stock_daily_ak_full_ak.insert_many(docs)

# 验证
count_ak_new = db.stock_daily_ak_full_ak.count_documents({})
print(f"Migration completed! stock_daily_ak_full_ak has {count_ak_new} documents")

if count_ak == count_ak_new:
    print("✅ 迁移成功！数据完整")
else:
    print(f"❌ 迁移失败！源 {count_ak} != 目标 {count_ak_new}")
