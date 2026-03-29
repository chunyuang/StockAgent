#!/usr/bin/env python3
import pymongo
client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']
coll = db['stock_daily_ak_full']

# 检查数据里有没有source字段
doc = coll.find_one()
print("📊 数据字段:", list(doc.keys()))
print("是否有source字段:", "source" in doc)
if "source" in doc:
    print("source字段值:", doc["source"])

# 模拟FactorEngine的查询：加source过滤
cnt_with_source = coll.count_documents({'trade_date': 20260106, 'source': 'ak'})
cnt_without_source = coll.count_documents({'trade_date': 20260106})
print(f"\n🔍 查询测试：")
print(f"加source='ak'过滤，20260106记录数: {cnt_with_source}")
print(f"不加过滤，20260106记录数: {cnt_without_source}")
