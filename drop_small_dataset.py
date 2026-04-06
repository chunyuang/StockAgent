#!/usr/bin/env python3
import pymongo

# 连接MongoDB
client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client["stock_agent"]

# 删除小测试集合stock_daily
if "stock_daily" in db.list_collection_names():
    db["stock_daily"].drop()
    print("✅ 小测试集合stock_daily已成功删除，彻底避免误用！")
else:
    print("ℹ️ 小测试集合stock_daily不存在，无需删除")

# 验证全量集合存在
if "stock_daily_ak_full" in db.list_collection_names():
    count = db["stock_daily_ak_full"].count_documents({})
    print(f"✅ 全量数据集stock_daily_ak_full正常，总记录数: {count}条")
else:
    print("❌ 全量数据集stock_daily_ak_full不存在，请检查")
