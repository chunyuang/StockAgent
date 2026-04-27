#!/usr/bin/env python3
import pymongo
import pandas as pd
import numpy as np

print("="*80)
print("🚀 批量修复：一次性计算所有缺失因子")
print("="*80)
print()

client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']
coll = db['stock_daily_ak_full']

# 1. 一次性读入所有数据
print("正在读取所有数据...")
all_data = list(coll.find({}, {
    'ts_code': 1, 'trade_date': 1, 'close': 1, 'high': 1, 'low': 1, 
    'turnover_rate': 1
}))
print(f"共 {len(all_data):,} 条记录")
print()

# 2. 转为 DataFrame 批量计算
df = pd.DataFrame(all_data)
df = df.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)

print("正在批量计算所有因子...")

# 按股票分组计算
def calc_factors(group):
    # RSI 14
    delta = group['close'].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    group['rsi_14'] = 100 - (100 / (1 + rs))
    
    # TRANGE
    group['tr1'] = group['high'] - group['low']
    group['tr2'] = abs(group['high'] - group['close'].shift(1))
    group['tr3'] = abs(group['low'] - group['close'].shift(1))
    group['trange'] = group[['tr1', 'tr2', 'tr3']].max(axis=1)
    
    # MACD
    group['ema12_macd'] = group['close'].ewm(span=12, adjust=False).mean()
    group['ema26_macd'] = group['close'].ewm(span=26, adjust=False).mean()
    group['macd'] = group['ema12_macd'] - group['ema26_macd']
    group['macd_signal'] = group['macd'].ewm(span=9, adjust=False).mean()
    group['macd_hist'] = group['macd'] - group['macd_signal']
    
    # 动量
    group['momentum_10d'] = group['close'].pct_change(10)
    group['momentum_60d'] = group['close'].pct_change(60)
    
    # 换手率
    group['turnover_20d'] = group['turnover_rate'].rolling(20).mean()
    
    # 布林中轨别名
    group['boll_middle'] = group['close'].rolling(20).mean()
    
    return group

df = df.groupby('ts_code', group_keys=False).apply(calc_factors)
print("计算完成!")
print()

# 3. 批量更新数据库
cols = ['rsi_14', 'trange', 'macd', 'macd_signal', 'macd_hist',
        'momentum_10d', 'momentum_60d', 'turnover_20d', 'boll_middle']

print(f"准备批量更新 {len(df):,} 条记录...")
print()

total = 0
batch_ops = []
BATCH_SIZE = 1000

for _, row in df.iterrows():
    update_dict = {}
    for col in cols:
        val = row[col]
        if pd.notna(val) and val == val:
            update_dict[col] = float(val)
    
    if update_dict:
        batch_ops.append(pymongo.UpdateOne(
            {'ts_code': row['ts_code'], 'trade_date': int(row['trade_date'])},
            {'$set': update_dict}
        ))
    
    if len(batch_ops) >= BATCH_SIZE:
        result = coll.bulk_write(batch_ops, ordered=False)
        total += result.modified_count
        print(f"  已提交 {total:7,d} 条更新...")
        batch_ops = []

# 最后一批
if batch_ops:
    result = coll.bulk_write(batch_ops, ordered=False)
    total += result.modified_count

print()
print("="*80)
print(f"✅ 全部完成! 总共更新了 {total:,} 条记录")
print("="*80)
