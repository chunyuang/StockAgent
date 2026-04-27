#!/usr/bin/env python3
import pymongo
import pandas as pd
import numpy as np

print("测试 UpdateOne...")

client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']
coll = db['stock_daily_ak_full']

# 只取一只股票
code = '000001.SZ'
data = list(coll.find(
    {'ts_code': code},
    {'ts_code': 1, 'trade_date': 1, 'close': 1, 'amount': 1}
).sort('trade_date', 1))

print(f"股票: {code}, 数据量: {len(data)}")

df = pd.DataFrame(data)
df['ma20'] = df['close'].rolling(20).mean()

# 测试单条更新
last_row = df.iloc[-1]
print(f"最后一条: trade_date={last_row['trade_date']}, ma20={last_row['ma20']}")

# 单条更新
result = coll.update_one(
    {'ts_code': code, 'trade_date': int(last_row['trade_date'])},
    {'$set': {'ma20': float(last_row['ma20'])}}
)
print(f"单条更新结果: matched={result.matched_count}, modified={result.modified_count}")

# 验证
verify = coll.find_one({'ts_code': code, 'trade_date': int(last_row['trade_date'])})
print(f"验证: ma20={verify.get('ma20')}")

print("✅ 成功!")
