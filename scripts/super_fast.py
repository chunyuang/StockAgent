#!/usr/bin/env python3
import pymongo
import pandas as pd
import numpy as np

print("🚀 超级快速修复 - 直接更新所有 None 字段")

client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']
coll = db['stock_daily_ak_full']

# 1. 先获取所有股票代码
codes = coll.distinct('ts_code')
print(f"总股票数: {len(codes)}")

total = 0

for idx, code in enumerate(codes, 1):
    # 2. 获取单只股票所有数据
    data = list(coll.find(
        {'ts_code': code},
        {'ts_code': 1, 'trade_date': 1, 'open': 1, 'high': 1, 'low': 1, 'close': 1, 'amount': 1, 'pct_chg': 1}
    ).sort('trade_date', 1))
    
    if len(data) < 60:
        continue
    
    df = pd.DataFrame(data)
    
    # 3. 计算所有技术指标
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
    
    # 批量更新
    ops = []
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
            ops.append(pymongo.UpdateOne(
                {'ts_code': code, 'trade_date': int(row['trade_date'])},
                {'$set': update_dict}
            ))
    
    if ops:
        coll.bulk_write(ops, ordered=False)
        total += len(ops)
    
    if idx % 100 == 0:
        print(f"  已处理 {idx}, 累计更新 {total:,}")

print()
print(f"✅ 完成! 总共更新 {total:,} 条记录")
