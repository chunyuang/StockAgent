#!/usr/bin/env python3
import sys
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

print("="*80)
print("🚀 因子批量补算 - 简化版")
print("="*80)
print()

import pandas as pd
import numpy as np
import pymongo
from datetime import datetime

print("连接MongoDB...")
client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']
coll = db['stock_daily_ak_full']

print("加载数据...")
all_docs = list(coll.find({}, {'ts_code': 1, 'trade_date': 1, 'open': 1, 'high': 1, 'low': 1, 'close': 1, 'vol': 1, 'amount': 1, 'pct_chg': 1}))
df = pd.DataFrame(all_docs)
print(f"总记录数: {len(df):,}")
print(f"股票数量: {df['ts_code'].nunique():,}")
print()

print("开始计算因子...")
all_codes = df['ts_code'].unique()

batch_size = 100
total_updated = 0

for idx in range(0, len(all_codes), 10):
    code_batch = all_codes[idx:idx+10]
    print(f"处理 {idx}-{idx+10} / {len(all_codes)}...")
    
    for ts_code in code_batch:
        group = df[df['ts_code'] == ts_code].sort_values('trade_date').copy()
        
        if len(group) < 60:
            continue
        
        # 计算所有因子
        group['ma5'] = group['close'].rolling(5).mean()
        group['ma10'] = group['close'].rolling(10).mean()
        group['ma20'] = group['close'].rolling(20).mean()
        group['ma60'] = group['close'].rolling(60).mean()
        
        group['ema5'] = group['close'].ewm(span=5, adjust=False).mean()
        group['ema10'] = group['close'].ewm(span=10, adjust=False).mean()
        group['ema20'] = group['close'].ewm(span=20, adjust=False).mean()
        group['ema60'] = group['close'].ewm(span=60, adjust=False).mean()
        group['ema12'] = group['close'].ewm(span=12, adjust=False).mean()
        group['ema26'] = group['close'].ewm(span=26, adjust=False).mean()
        
        # RSI
        delta = group['close'].diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        for period in [6, 12, 24]:
            avg_gain = gain.rolling(window=period).mean()
            avg_loss = loss.rolling(window=period).mean()
            rs = avg_gain / avg_loss.replace(0, np.nan)
            group[f'rsi_{period}'] = 100 - (100 / (1 + rs))
        
        # MACD
        group['macd'] = group['ema12'] - group['ema26']
        group['macd_signal'] = group['macd'].ewm(span=9, adjust=False).mean()
        group['macd_hist'] = group['macd'] - group['macd_signal']
        
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
        
        # 其他
        group['amount_20d'] = group['amount'].rolling(20).mean()
        group['momentum_5d'] = group['close'].pct_change(5)
        group['momentum_10d'] = group['close'].pct_change(10)
        group['momentum_20d'] = group['close'].pct_change(20)
        group['volatility_5d'] = group['pct_chg'].rolling(5).std()
        group['volatility_10d'] = group['pct_chg'].rolling(10).std()
        group['volatility_20d'] = group['pct_chg'].rolling(20).std()
        
        # 批量更新
        ops = []
        for _, row in group.iterrows():
            update_dict = {}
            for col in ['ma5','ma10','ma20','ma60','ema5','ema10','ema20','ema60','ema12','ema26',
                       'rsi_6','rsi_12','rsi_24','boll_upper','boll_mid','boll_lower','atr','atr_14','natr','trange',
                       'macd','macd_signal','macd_hist','amount_20d',
                       'momentum_5d','momentum_10d','momentum_20d',
                       'volatility_5d','volatility_10d','volatility_20d']:
                if col in row and pd.notna(row[col]):
                    update_dict[col] = float(row[col])
            
            if update_dict:
                ops.append(pymongo.UpdateOne(
                    {'ts_code': row['ts_code'], 'trade_date': int(row['trade_date'])},
                    {'$set': update_dict}
                ))
        
        if ops:
            coll.bulk_write(ops, ordered=False)
            total_updated += len(ops)
            print(f"  {ts_code}: {len(ops)} 条")

print()
print("="*80)
print(f"✅ 完成! 总共更新 {total_updated:,} 条记录")
print("="*80)
