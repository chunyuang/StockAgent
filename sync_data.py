#!/usr/bin/env python3
import pymongo
from datetime import datetime
import sys

# 连接MongoDB
client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client["stock_agent"]

print("=== 开始数据同步 ===")
print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# 1. 同步全量数据到stock_daily集合
print("\n1. 同步全量数据到stock_daily集合...")
source_collection = db["stock_daily_ak_full"]
target_collection = db["stock_daily"]

# 清空目标集合
target_collection.drop()

# 获取全量数据插入
total_count = source_collection.count_documents({})
print(f"源集合总记录数: {total_count}条")

# 批量插入
batch_size = 10000
inserted = 0
cursor = source_collection.find({}, batch_size=batch_size)
batch = []
for doc in cursor:
    batch.append(doc)
    if len(batch) >= batch_size:
        target_collection.insert_many(batch, ordered=False)
        inserted += len(batch)
        print(f"已插入: {inserted}/{total_count}条 ({inserted/total_count*100:.1f}%)")
        batch = []
if batch:
    target_collection.insert_many(batch, ordered=False)
    inserted += len(batch)
    print(f"已插入: {inserted}/{total_count}条 ({inserted/total_count*100:.1f}%)")

# 2. 创建索引
print("\n2. 创建索引...")
target_collection.create_index([("ts_code", 1), ("trade_date", -1)], unique=True)
target_collection.create_index([("trade_date", -1)])
print("✅ 索引创建完成")

# 3. 验证同步结果
print("\n3. 验证同步结果...")
target_count = target_collection.count_documents({})
print(f"目标集合总记录数: {target_count}条")
print(f"同步状态: {'✅ 完全同步' if target_count == total_count else '❌ 同步失败'}")

# 4. 检查涨停股票数量
print("\n4. 检查涨停股票数量...")
dates = sorted(target_collection.distinct("trade_date"))
print(f"覆盖交易日: {len(dates)}天，范围: {dates[0]} ~ {dates[-1]}")

# 统计最近10天涨停数量
for date in dates[:10]:
    limit_up_count = target_collection.count_documents({
        "trade_date": date,
        "pct_chg": {"$gte": 9.8}
    })
    print(f"  {date}: 涨停{limit_up_count}只")

# 5. 运行因子计算
print("\n5. 开始计算策略依赖因子...")
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')
exec(open("/root/.openclaw/workspace/StockAgent/compute_factors.py").read())

print("\n=== 全部完成 ===")
print(f"完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
