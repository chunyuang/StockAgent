#!/usr/bin/env python3
import pymongo
import pandas as pd
import numpy as np

print("="*80)
print("🚀 用完整历史数据重新计算所有因子（真实 rolling，不取巧）")
print("="*80)
print()

client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']
coll = db['stock_daily_ak_full']

# 1. 获取所有股票和日期
codes = coll.distinct('ts_code')
dates = sorted(coll.distinct('trade_date'))
print(f"股票总数: {len(codes):,}")
print(f"交易日数: {len(dates)} 天")
print(f"日期范围: {dates[0]} ~ {dates[-1]}")
print()

total = 0
for idx, code in enumerate(codes, 1):
    data = list(coll.find(
        {'ts_code': code},
        {'ts_code': 1, 'trade_date': 1, 'open': 1, 'high': 1, 'low': 1, 'close': 1, 
         'amount': 1, 'pct_chg': 1}
    ).sort('trade_date', 1))
    
    df = pd.DataFrame(data)
    df = df.sort_values('trade_date').reset_index(drop=True)
    
    # ========== 真实的因子计算（不设 min_periods，数据足够才产生值）==========
    df['ma20'] = df['close'].rolling(20).mean()
    df['ma60'] = df['close'].rolling(60).mean()
    
    df['ema12'] = df['close'].ewm(span=12, adjust=False).mean()
    df['ema26'] = df['close'].ewm(span=26, adjust=False).mean()
    
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(24).mean()
    avg_loss = loss.rolling(24).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df['rsi_24'] = 100 - (100 / (1 + rs))
    
    df['boll_mid'] = df['close'].rolling(20).mean()
    boll_std = df['close'].rolling(20).std()
    df['boll_upper'] = df['boll_mid'] + 2 * boll_std
    df['boll_lower'] = df['boll_mid'] - 2 * boll_std
    
    df['tr1'] = df['high'] - df['low']
    df['tr2'] = abs(df['high'] - df['close'].shift(1))
    df['tr3'] = abs(df['low'] - df['close'].shift(1))
    df['trange'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
    df['atr_14'] = df['trange'].rolling(14).mean()
    df['atr'] = df['atr_14']
    df['natr'] = df['atr_14'] / df['close'] * 100
    
    df['amount_20d'] = df['amount'].rolling(20).mean()
    df['momentum_20d'] = df['close'].pct_change(20)
    df['volatility_20d'] = df['pct_chg'].rolling(20).std()
    
    # 更新所有日期
    cols = ['ma20', 'ma60', 'ema12', 'ema26', 'rsi_24',
            'boll_upper', 'boll_mid', 'boll_lower',
            'atr', 'atr_14', 'natr', 'amount_20d',
            'momentum_20d', 'volatility_20d']
    
    for _, row in df.iterrows():
        update_dict = {}
        for col in cols:
            val = row[col]
            if pd.notna(val) and val == val:
                update_dict[col] = float(val)
        
        if update_dict:
            result = coll.update_one(
                {'ts_code': code, 'trade_date': int(row['trade_date'])},
                {'$set': update_dict}
            )
            total += result.modified_count
    
    if idx % 500 == 0:
        print(f"  已处理 {idx:4d}/{len(codes)}, 累计更新 {total:7,d} 条")

print()
print("="*80)
print(f"✅ 完成! 总共更新 {total:,} 条记录")
print("="*80)
