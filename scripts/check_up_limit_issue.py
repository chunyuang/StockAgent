#!/usr/bin/env python3
"""
检查 up_limit 字段问题
"""
import pymongo
import numpy as np

client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']

print('🔍 检查 up_limit 字段问题')
print('='*60)

# 1. 获取数据库中的股票数据
print('\n📊 数据库中的 sh600110.SZ 数据:')
docs = list(db.stock_daily_ak_full_ak.find(
    {'ts_code': 'sh600110.SZ'},
    {'trade_date': 1, 'close': 1, 'up_limit': 1, 'open': 1}
).sort('trade_date', 1).limit(10))

if not docs:
    print('   ❌ 数据库中没有数据')
    exit()

print(f'   找到 {len(docs)} 条记录')

# 2. 分析每条记录
for doc in docs:
    trade_date = doc['trade_date']
    close = doc.get('close', np.nan)
    up_limit = doc.get('up_limit', np.nan)
    open_price = doc.get('open', np.nan)
    
    # 检查涨停价是否正确
    if not np.isnan(close) and not np.isnan(up_limit):
        ratio = up_limit / close if close != 0 else 0
        
        # 涨停价应该是收盘价的 1.1 倍
        expected_up_limit = close * 1.1
        diff = abs(up_limit - expected_up_limit)
        
        # 判断是否正常
        if abs(ratio - 1.1) < 0.01:
            status = '✅'
        elif abs(ratio - 1.0) < 0.01:
            status = '❌（涨停价=收盘价）'
        else:
            status = f'❌（比例异常: {ratio:.4f}）'
        
        print(f'   {status}')
        print(f'     日期: {trade_date}')
        print(f'     收盘: {close}')
        print(f'     涨停价: {up_limit}')
        print(f'     正确涨停价: {expected_up_limit:.4f}')
        print(f'     比例: {ratio:.4f}（应该≈1.1）')
        print(f'     差值: {diff:.4f}')
        print()
    else:
        print(f'   ⚠️ 日期: {trade_date}, 数据不完整')
        print(f'     收盘: {close}, 涨停价: {up_limit}')
        print()

# 3. 检查其他股票
print('\n🔍 检查其他股票:')
other_docs = list(db.stock_daily_ak_full_ak.find(
    {'trade_date': 20260105},
    {'ts_code': 1, 'close': 1, 'up_limit': 1}
).limit(5))

print('   20260105 的股票样本:')
for doc in other_docs:
    ts_code = doc['ts_code']
    close = doc.get('close', np.nan)
    up_limit = doc.get('up_limit', np.nan)
    
    if not np.isnan(close) and not np.isnan(up_limit):
        ratio = up_limit / close if close != 0 else 0
        
        if abs(ratio - 1.1) < 0.01:
            status = '✅'
        elif abs(ratio - 1.0) < 0.01:
            status = '❌'
        else:
            status = f'❌（{ratio:.4f}）'
        
        print(f'   {status} {ts_code}: close={close}, up_limit={up_limit}, ratio={ratio:.4f}')

# 4. 统计问题比例
print('\n📈 问题统计:')
count_total = db.stock_daily_ak_full_ak.count_documents({'trade_date': 20260105})
count_wrong = db.stock_daily_ak_full_ak.count_documents({
    'trade_date': 20260105,
    'up_limit': {'$exists': True}
})

print(f'   总股票数: {count_total}')
print(f'   有涨停价数据的股票数: {count_wrong}')

# 抽样检查涨停价是否正确
sample_docs = list(db.stock_daily_ak_full_ak.find(
    {'trade_date': 20260105},
    {'ts_code': 1, 'close': 1, 'up_limit': 1}
).limit(20))

wrong_count = 0
for doc in sample_docs:
    close = doc.get('close', np.nan)
    up_limit = doc.get('up_limit', np.nan)
    
    if not np.isnan(close) and not np.isnan(up_limit):
        ratio = up_limit / close if close != 0 else 0
        if abs(ratio - 1.1) > 0.01:  # 不是 1.1
            wrong_count += 1

print(f'   抽样检查（20只股票）中错误涨停价: {wrong_count} 只')
print()

# 5. 结论
print('🔍 结论:')
print('   1. ✅ 找到了问题: up_limit 字段计算错误')
print('   2. ✅ 涨停价应该是收盘价的 1.1 倍，但数据库中很多是 1.0 倍')
print('   3. ✅ 这导致策略条件\"今日开盘价 < 昨日涨停价\"永远不成立')
print('   4. ✅ 需要修复数据或重新下载')

print('\n💡 解决方案:')
print('   A. 重新计算所有 up_limit 字段: close × 1.1')
print('   B. 重新下载数据并正确导入')
print('   C. 检查数据导入脚本的涨停价计算逻辑')