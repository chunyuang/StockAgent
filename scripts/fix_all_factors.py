#!/usr/bin/env python3
import pymongo
import pandas as pd
import numpy as np

print("="*80)
print("🚀 修复所有剩余因子")
print("="*80)

client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']
coll = db['stock_daily_ak_full']

# 找出还缺因子的股票
to_fix = list(coll.find(
    {'trade_date': 20260120, 'ma60': None},
    {'ts_code': 1}
))

print(f"需要修复: {len(to_fix)} 只股票")
print()

total = 0
for idx, item in enumerate(to_fix, 1):
    code = item['ts_code']
    
    data = list(coll.find(
        {'ts_code': code},
        {'trade_date': 1, 'close': 1, 'high': 1, 'low': 1, 'amount': 1, 'pct_chg': 1}
    ).sort('trade_date', 1))
    
    df = pd.DataFrame(data)
    
    # 计算所有因子，用 min_periods=1
    df['ma60'] = df['close'].rolling(60, min_periods=1).mean()
    df['ema12'] = df['close'].ewm(span=12, adjust=False).mean()
    df['ema26'] = df['close'].ewm(span=26, adjust=False).mean()
    
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(24, min_periods=1).mean()
    avg_loss = loss.rolling(24, min_periods=1).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df['rsi_24'] = 100 - (100 / (1 + rs))
    
    df['boll_mid'] = df['close'].rolling(20, min_periods=1).mean()
    boll_std = df['close'].rolling(20, min_periods=1).std()
    df['boll_upper'] = df['boll_mid'] + 2 * boll_std
    df['boll_lower'] = df['boll_mid'] - 2 * boll_std
    
    df['tr1'] = df['high'] - df['low']
    df['tr2'] = abs(df['high'] - df['close'].shift(1))
    df['tr3'] = abs(df['low'] - df['close'].shift(1))
    df['trange'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
    df['atr_14'] = df['trange'].rolling(14, min_periods=1).mean()
    df['atr'] = df['atr_14']
    df['natr'] = df['atr_14'] / df['close'] * 100
    
    df['momentum_20d'] = df['close'].pct_change(20)
    df['volatility_20d'] = df['pct_chg'].rolling(20, min_periods=1).std()
    
    # 更新这三天
    cols = ['ma60', 'ema12', 'ema26', 'rsi_24', 'boll_upper', 'boll_mid', 'boll_lower',
            'atr', 'atr_14', 'natr', 'momentum_20d', 'volatility_20d']
    
    for dt in [20260120, 20260121, 20260122]:
        row = df[df['trade_date'] == dt]
        if len(row) > 0:
            update_dict = {}
            for col in cols:
                val = row.iloc[0][col]
                if pd.notna(val) and val == val:
                    update_dict[col] = float(val)
            
            if update_dict:
                result = coll.update_one(
                    {'ts_code': code, 'trade_date': dt},
                    {'$set': update_dict}
                )
                total += result.modified_count
    
    if idx % 200 == 0:
        print(f"  已处理 {idx}/{len(to_fix)}, 累计更新 {total:,} 条")

print()
print(f"✅ 完成! 总共更新 {total:,} 条记录")
