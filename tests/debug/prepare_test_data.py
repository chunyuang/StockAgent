
import sys
sys.path.insert(0, './AgentServer')
from pymongo import MongoClient

client = MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']
coll = db['stock_daily_ak_full']

print('=' * 70)
print('🧪 构造强制空仓测试数据')
print('=' * 70)

# 1. 把20260106设置55只跌停
stocks = coll.distinct('ts_code')[:100]
count = 0
for code in stocks[:55]:
    r = coll.update_one(
        {'trade_date': 20260106, 'ts_code': code},
        {'$set': {'is_limit_down': 1}}
    )
    count += r.modified_count

print(f'✅ 设置了 {count} 只跌停')

# 2. 把20260107的first_limit_up设置为只有8只
coll.update_many(
    {'trade_date': 20260107},
    {'$set': {'first_limit_up': False, 'is_limit_up': 0}}
)

count2 = 0
for code in stocks[:8]:
    r = coll.update_one(
        {'trade_date': 20260107, 'ts_code': code},
        {'$set': {'first_limit_up': True, 'is_limit_up': 1}}
    )
    count2 += r.modified_count

print(f'✅ 设置了 {count2} 只涨停')

# 验证
d1_down = coll.count_documents({'trade_date': 20260106, 'is_limit_down': 1})
d2_up = coll.count_documents({'trade_date': 20260107, 'first_limit_up': True})
print(f'  20260106: 跌停={d1_down}只（≥50，触发强制空仓）')
print(f'  20260107: 涨停={d2_up}只（≤10，触发强制空仓）')

print()
print('=' * 70)
print('🧪 构造情绪周期测试数据')
print('=' * 70)

# 把20260109设置为极致冰点（情绪分全设为5）
r3 = coll.update_many(
    {'trade_date': 20260109},
    {'$set': {'sentiment_score': 5}}
)
print(f'✅ 更新了 {r3.modified_count} 条极致冰点情绪分')

# 把20260112设置为高潮期（情绪分全设为95）
r4 = coll.update_many(
    {'trade_date': 20260112},
    {'$set': {'sentiment_score': 95}}
)
print(f'✅ 更新了 {r4.modified_count} 条高潮期情绪分')

# 验证
pipeline = [
    {'$match': {'trade_date': 20260109}},
    {'$group': {'_id': None, 'avg': {'$avg': '$sentiment_score'}}}
]
d3 = list(coll.aggregate(pipeline))

pipeline2 = [
    {'$match': {'trade_date': 20260112}},
    {'$group': {'_id': None, 'avg': {'$avg': '$sentiment_score'}}}
]
d4 = list(coll.aggregate(pipeline2))

print('  20260109: 平均情绪分 %.1f（极致冰点，预期仓位10%%）' % d3[0]['avg'])
print('  20260112: 平均情绪分 %.1f（高潮期，预期仓位100%%）' % d4[0]['avg'])

print()
print('=' * 70)
print('🧪 构造流动性过滤测试数据')
print('=' * 70)

# 把20260113的100只股票设置为成交额<500万（流动性不足）
count5 = 0
for code in stocks[:100]:
    r = coll.update_one(
        {'trade_date': 20260113, 'ts_code': code},
        {'$set': {'amount': 4000000}}  # 400万，<500万门槛
    )
    count5 += r.modified_count

# 其余的设置为>1000万
r6 = coll.update_many(
    {'trade_date': 20260113, 'amount': {'$ne': 4000000}},
    {'$set': {'amount': 10000000}}  # 1000万，满足门槛
)
print(f'✅ 设置了 {count5} 只流动性不足股票，{r6.modified_count} 只流动性达标')

# 验证
low_liq = coll.count_documents({'trade_date': 20260113, 'amount': {'$lt': 5000000}})
high_liq = coll.count_documents({'trade_date': 20260113, 'amount': {'$gte': 5000000}})
print(f'  20260113: 流动性不足={low_liq}只，流动性达标={high_liq}只')

print()
print('✅ 所有测试数据构造完成！可以开始跑回测验证了！')
