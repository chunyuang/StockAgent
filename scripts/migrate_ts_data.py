#!/usr/bin/env python3
"""
数据迁移脚本：将 stock_daily_ak_full 中 source="ts" 的数据迁移到 stock_daily_ak_full_ts
"""
import pymongo
import sys

client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']

# 检查源数据
count_ts = db.stock_daily_ak_full.count_documents({"source": "ts"})
print(f"Found {count_ts} documents with source='ts' in stock_daily_ak_full")

if count_ts == 0:
    print("No TS data found, nothing to migrate")
    sys.exit(0)

# 新建集合，复制数据
print("Migrating to stock_daily_ak_full_ts...")
# 先清空目标集合（如果存在）
if "stock_daily_ak_full_ts" in db.list_collection_names():
    db.stock_daily_ak_full_ts.delete_many({})

# 复制数据（分批处理避免内存问题）
batch_size = 10000
total_migrated = 0

cursor = db.stock_daily_ak_full.find({"source": "ts"})
batch = []

for doc in cursor:
    batch.append(doc)
    if len(batch) >= batch_size:
        db.stock_daily_ak_full_ts.insert_many(batch)
        total_migrated += len(batch)
        print(f"  Migrated {total_migrated}/{count_ts} documents")
        batch = []

# 插入剩余文档
if batch:
    db.stock_daily_ak_full_ts.insert_many(batch)
    total_migrated += len(batch)

# 验证
count_ts_new = db.stock_daily_ak_full_ts.count_documents({})
print("\nMigration completed!")
print(f"  Original TS data in stock_daily_ak_full: {count_ts}")
print(f"  New data in stock_daily_ak_full_ts: {count_ts_new}")

if count_ts == count_ts_new:
    print("✅ 迁移成功！数据完整")
else:
    print(f"❌ 迁移失败！源 {count_ts} != 目标 {count_ts_new}")
    sys.exit(1)

# 可选：清理原始集合中的TS数据
cleanup = input("\n是否清理 stock_daily_ak_full 中的TS数据？(y/N): ")
if cleanup.lower() == 'y':
    result = db.stock_daily_ak_full.delete_many({"source": "ts"})
    print(f"已清理 stock_daily_ak_full 中的 {result.deleted_count} 条TS数据")
    
    # 检查是否还有数据
    remaining = db.stock_daily_ak_full.count_documents({})
    print(f"stock_daily_ak_full 中剩余数据: {remaining} 条")
    
    if remaining == 0:
        print("stock_daily_ak_full 已清空，可以考虑删除该集合")
    else:
        print("stock_daily_ak_full 中还有其他数据（可能是source=ak或其他）")
else:
    print("跳过清理，保留原始数据")