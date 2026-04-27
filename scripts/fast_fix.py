#!/usr/bin/env python3
import pymongo
import pandas as pd
import numpy as np

print("="*80)
print("🚀 快速修复 - 只处理回测需要的日期: 20260101 ~ 20260122")
print("="*80)

client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']
coll = db['stock_daily_ak_full']

# 只加载需要的日期范围（往前多拿20天，因为ma20需要）
print("📥 加载数据...")
data = list(coll.find({
    'trade_date': {'$gte': 20251220, '$lte': 20260122}
}, {'ts_code': 1, 'trade_date': 1, 'open': 1, 'high': 1, 'low': 1, 'close': 1, 'amount': 1, 'pct_chg': 1}))

df = pd.DataFrame(data)
print(f"✅ 加载 {len(df):,} 条记录")
print(f"   股票: {df['ts_code'].nunique():,} 只")
print(f"   日期: {df['trade_date'].min()} ~ {df['trade_date'].max()}")
print()

# 按股票分组
codes = df['ts_code'].unique()
total_ops = 0

for idx, code in enumerate(codes, 1):
    group = df[df['ts_code'] == code].sort_values('trade_date').copy()
    
    if len(group) < 20:
        continue
    
    # 只计算回测真正需要的19个因子
    group['ma20'] = group['close'].rolling(20).mean()
    group['ma60'] = group['close'].rolling(60).mean()
    
    group['ema12'] = group['close'].ewm(span=12, adjust=False).mean()
    group['ema26'] = group['close'].ewm(span=26, adjust=False).mean()
    
    delta = group['close'].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(24).mean()
    avg_loss = loss.rolling(24).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    group['rsi_24'] = 100 - (100 / (1 + rs))
    
    group['boll_mid'] = group['close'].rolling(20).mean()
    boll_std = group['close'].rolling(20).std()
    group['boll_upper'] = group['boll_mid'] + 2 * boll_std
    group['boll_lower'] = group['boll_mid'] - 2 * boll_std
    
    group['tr1'] = group['high'] - group['low']
    group['tr2'] = abs(group['high'] - group['close'].shift(1))
    group['tr3'] = abs(group['low'] - group['close'].shift(1))
    group['trange'] = group[['tr1', 'tr2', 'tr3']].max(axis=1)
    group['atr_14'] = group['trange'].rolling(14).mean()
    group['atr'] = group['atr_14']
    group['natr'] = group['atr_14'] / group['close'] * 100
    
    group['amount_20d'] = group['amount'].rolling(20).mean()
    group['momentum_20d'] = group['close'].pct_change(20)
    group['volatility_20d'] = group['pct_chg'].rolling(20).std()
    
    if 'turnover_rate' in group.columns:
        group['turnover_20d'] = group['turnover_rate'].rolling(20).mean()
    
    # 只更新 20260120 之后的数据
    group_to_update = group[group['trade_date'] >= 20260120]
    
    ops = []
    cols = ['ma20', 'ma60', 'ema12', 'ema26', 'rsi_24',
            'boll_upper', 'boll_mid', 'boll_lower',
            'atr', 'atr_14', 'natr', 'amount_20d',
            'momentum_20d', 'volatility_20d', 'turnover_20d']
    
    for _, row in group_to_update.iterrows():
        update_dict = {}
        for col in cols:
            if col in row and pd.notna(row[col]) and row[col] == row[col]:
                update_dict[col] = float(row[col])
        
        if update_dict:
            ops.append(pymongo.UpdateOne(
                {'ts_code': row['ts_code'], 'trade_date': int(row['trade_date'])},
                {'$set': update_dict}
            ))
    
    if ops:
        coll.bulk_write(ops, ordered=False)
        total_ops += len(ops)
    
    if idx % 500 == 0:
        print(f"   已处理 {idx:,}/{len(codes):,} 只股票, 累计更新 {total_ops:,} 条")

print()
print("="*80)
print(f"✅ 完成! 总共更新 {total_ops:,} 条记录")
print("="*80)
