
import sys
sys.path.insert(0, './AgentServer')
from pymongo import MongoClient

client = MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']
coll = db['stock_daily_ak_full']

print('测试单条更新:')
doc = coll.find_one({'trade_date': 20260106})
print(f'  找到记录: {doc["ts_code"]}')
print(f'  更新前is_limit_down: {doc.get("is_limit_down")}')

# 注意：这里必须用字典的形式，$set作为key
update_dict = {'$set': {'is_limit_down': 1}}
print(f'  更新操作: {update_dict}')

result = coll.update_one(
    {'_id': doc['_id']},
    update_dict
)
print(f'  匹配: {result.matched_count}, 更新: {result.modified_count}')

# 再查一遍
doc2 = coll.find_one({'_id': doc['_id']})
print(f'  更新后is_limit_down: {doc2.get("is_limit_down")}')

print()
print('✅ 单条更新测试完成！')
