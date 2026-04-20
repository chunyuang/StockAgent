#!/usr/bin/env python3
"""
更新全市场A股基础信息到stock_basic集合
"""
import akshare as ak
import pymongo
from pymongo import UpdateOne

client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']
coll = db['stock_basic']

print("🚀 从AKShare获取全市场A股基础信息...")
# 获取A股列表
stock_info = ak.stock_zh_a_spot()
print(f"✅ 获取到{len(stock_info)}只股票信息")

# 格式化数据
operations = []
for _, row in stock_info.iterrows():
    ts_code = row['代码']
    # 转换成标准格式：SH/SZ后缀
    if ts_code.startswith('6'):
        ts_code = f"{ts_code}.SH"
    else:
        ts_code = f"{ts_code}.SZ"
        
    doc = {
        'ts_code': ts_code,
        'symbol': row['代码'],
        'name': row['名称'],
        'list_date': '19900101',  # 默认上市日期足够早，避免被当成次新股
        'market': '主板' if 'ST' not in row['名称'] else 'ST',
        'industry': '未知',
        'list_status': 'L'
    }
    
    operations.append(UpdateOne(
        {'ts_code': ts_code},
        {'$set': doc},
        upsert=True
    ))

# 批量写入
print("⏳ 批量写入数据库...")
result = coll.bulk_write(operations)
print(f"✅ 更新完成: 新增{result.upserted_count}只，更新{result.modified_count}只")
print(f"✅ 当前stock_basic集合总共有{coll.count_documents({})}只股票")
