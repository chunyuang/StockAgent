#!/usr/bin/env python3
"""
只修复回测真正用到的关键因子
"""
import pymongo
import pandas as pd
import numpy as np
from datetime import datetime

print("="*80)
print("🚀 修复回测关键因子")
print("="*80)

client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']
coll = db['stock_daily_ak_full']

# 获取所有数据
print("📥 加载数据...")
data = list(coll.find({}, {'ts_code': 1, 'trade_date': 1, 'open': 1, 'high': 1, 'low': 1, 'close': 1, 'amount': 1, 'pct_chg': 1}))
df = pd.DataFrame(data)
print(f"✅ 加载 {len(df):,} 条记录")
print(f"   股票: {df['ts_code'].nunique():,} 只")
print()

# 按股票分组处理
codes = df['ts_code'].unique()
total_ops = 0

for idx, code in enumerate(codes, 1):
    group = df[df['ts_code'] == code].sort_values('trade_date').copy()
    
    if len(group) < 60:
        continue
    
    # 只计算回测真正用到的因子
    group['ma20'] = group['close'].rolling(20).mean()
    group['ma60'] = group['close'].rolling(60).mean()
    group['amount_20d'] = group['amount'].rolling(20).mean()
    
    # RSI 24
    delta = group['close'].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(24).mean()
    avg_loss = loss.rolling(24).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    group['rsi_24'] = 100 - (100 / (1 + rs))
    
    # EMA 12, 26
    group['ema12'] = group['close'].ewm(span=12, adjust=False).mean()
    group['ema26'] = group['close'].ewm(span=26, adjust=False).mean()
    
    # BOLL
    group['boll_mid'] = group['close'].rolling(20).mean()
    boll_std = group['close'].rolling(20).std()
    group['boll_upper'] = group['boll_mid'] + 2 * boll_std
    group['boll_lower'] = group['boll_mid'] - 2 * boll_std
    
    # ATR
    group['tr1'] = group['high'] - group['low']
    group['tr2'] = abs(group['high'] - group['close'].shift(1))
    group['tr3'] = abs(group['low'] - group['close'].shift(1))
    group['trange'] = group[['tr1', 'tr2', 'tr3']].max(axis=1)
    group['atr_14'] = group['trange'].rolling(14).mean()
    group['atr'] = group['atr_14']
    group['natr'] = group['atr_14'] / group['close'] * 100
    
    # 动量和波动率
    group['momentum_20d'] = group['close'].pct_change(20)
    group['volatility_20d'] = group['pct_chg'].rolling(20).std()
    
    # 换手率均线（如果有）
    if 'turnover_rate' in group.columns:
        group['turnover_20d'] = group['turnover_rate'].rolling(20).mean()
    
    # 批量更新
    ops = []
    cols_to_update = ['ma20', 'ma60', 'ema12', 'ema26', 'rsi_24', 
                      'boll_upper', 'boll_mid', 'boll_lower',
                      'atr', 'atr_14', 'natr', 'amount_20d',
                      'momentum_20d', 'volatility_20d', 'turnover_20d']
    
    for _, row in group.iterrows():
        update_dict = {}
        for col in cols_to_update:
            if col in row and pd.notna(row[col]) and row[col] == row[col]:  # 不是NaN
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
print(f"✅ 全部完成! 总共更新了 {total_ops:,} 条记录")
print("="*80)
