#!/usr/bin/env python3
import pymongo
from tqdm import tqdm

# 连接MongoDB
client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']
collection = db['stock_daily_ak_full_ak']

print("开始补全缺失字段...")
print(f"总记录数：{collection.count_documents({})}")

# 1. 获取所有股票代码
stocks = collection.distinct('ts_code')
print(f"股票数量：{len(stocks)}")

# 2. 逐个股票处理
updated_count = 0
for ts_code in tqdm(stocks, desc="处理股票"):
    # 获取该股票的所有交易日，按日期升序排序
    records = list(collection.find(
        {'ts_code': ts_code},
        {'trade_date': 1, 'close': 1}
    ).sort('trade_date', 1))
    
    if len(records) < 2:
        continue  # 不足两天数据，无法计算前收盘价
    
    # 逐个记录补全前收盘价、涨跌额、涨跌幅
    for i in range(len(records)):
        current = records[i]
        update_data = {}
        
        # 计算pre_close
        if i == 0:
            # 第一天没有前收盘价，用当天开盘价？或者留空？这里用当天开盘价填充
            pre_close = current['close']
        else:
            pre_close = records[i-1]['close']
        
        update_data['pre_close'] = pre_close
        
        # 计算涨跌额
        update_data['change'] = current['close'] - pre_close
        
        # 计算涨跌幅（%）
        if pre_close > 0:
            update_data['pct_chg'] = (update_data['change'] / pre_close) * 100
        else:
            update_data['pct_chg'] = 0
        
        # 更新数据库
        result = collection.update_one(
            {'_id': current['_id']},
            {'$set': update_data}
        )
        
        if result.modified_count > 0:
            updated_count += 1

print(f"补全完成，共更新{updated_count}条记录")

# 验证补全结果
sample = collection.find_one()
print("\n补全后字段示例：")
for k, v in sample.items():
    if k != '_id':
        print(f"  {k}: {v}")
