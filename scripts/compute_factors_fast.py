#!/usr/bin/env python3
"""
快速批量计算所有缺失因子（同步版本，更稳定）
"""
import pandas as pd
import numpy as np
import pymongo
from datetime import datetime

print("="*80)
print("🚀 开始快速批量计算所有因子")
print("="*80)
print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# 连接MongoDB
client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']
coll = db['stock_daily_ak_full']

# 1. 获取所有数据
print("📥 加载基础数据...")
all_docs = list(coll.find({}))
df = pd.DataFrame(all_docs)
print(f"✅ 加载完成: {len(df):,} 条记录")
print(f"   股票数量: {df['ts_code'].nunique():,} 只")
print(f"   交易日数: {df['trade_date'].nunique()} 天")
print()

# 2. 按股票分组计算衍生指标
print("🧮 开始计算衍生因子...")
result_dfs = []

all_codes = df['ts_code'].unique()
for idx, ts_code in enumerate(all_codes, 1):
    group = df[df['ts_code'] == ts_code].sort_values('trade_date').copy()
    
    # ---------- MA均线 ----------
    group['ma5'] = group['close'].rolling(5).mean()
    group['ma10'] = group['close'].rolling(10).mean()
    group['ma20'] = group['close'].rolling(20).mean()
    group['ma60'] = group['close'].rolling(60).mean()
    
    # ---------- EMA指数均线 ----------
    group['ema5'] = group['close'].ewm(span=5, adjust=False).mean()
    group['ema10'] = group['close'].ewm(span=10, adjust=False).mean()
    group['ema20'] = group['close'].ewm(span=20, adjust=False).mean()
    group['ema60'] = group['close'].ewm(span=60, adjust=False).mean()
    group['ema12'] = group['close'].ewm(span=12, adjust=False).mean()
    group['ema26'] = group['close'].ewm(span=26, adjust=False).mean()
    
    # ---------- RSI相对强弱 ----------
    def compute_rsi(close, period=14):
        delta = close.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    group['rsi_6'] = compute_rsi(group['close'], 6)
    group['rsi_12'] = compute_rsi(group['close'], 12)
    group['rsi_24'] = compute_rsi(group['close'], 24)
    
    # ---------- MACD ----------
    group['macd'] = group['ema12'] - group['ema26']
    group['macd_signal'] = group['macd'].ewm(span=9, adjust=False).mean()
    group['macd_hist'] = group['macd'] - group['macd_signal']
    
    # ---------- BOLL布林带 ----------
    group['boll_mid'] = group['close'].rolling(20).mean()
    boll_std = group['close'].rolling(20).std()
    group['boll_upper'] = group['boll_mid'] + 2 * boll_std
    group['boll_lower'] = group['boll_mid'] - 2 * boll_std
    
    # ---------- ATR真实波幅 ----------
    group['tr1'] = group['high'] - group['low']
    group['tr2'] = abs(group['high'] - group['close'].shift(1))
    group['tr3'] = abs(group['low'] - group['close'].shift(1))
    group['trange'] = group[['tr1', 'tr2', 'tr3']].max(axis=1)
    group['atr_14'] = group['trange'].rolling(14).mean()
    group['atr'] = group['atr_14']  # 别名
    group['natr'] = group['atr_14'] / group['close'] * 100
    
    # ---------- 成交额均线 ----------
    group['amount_20d'] = group['amount'].rolling(20).mean()
    
    # ---------- 动量 ----------
    group['momentum_5d'] = group['close'].pct_change(5)
    group['momentum_10d'] = group['close'].pct_change(10)
    group['momentum_20d'] = group['close'].pct_change(20)
    
    # ---------- 波动率 ----------
    group['volatility_5d'] = group['pct_chg'].rolling(5).std()
    group['volatility_10d'] = group['pct_chg'].rolling(10).std()
    group['volatility_20d'] = group['pct_chg'].rolling(20).std()
    
    # ---------- 换手率均线 ----------
    if 'turnover_rate' in group.columns:
        group['turnover_20d'] = group['turnover_rate'].rolling(20).mean()
    
    # ---------- 振幅 ----------
    group['amplitude'] = (group['high'] - group['low']) / group['close'].shift(1) * 100
    
    # 清理临时列
    group = group.drop(columns=['tr1', 'tr2', 'tr3'], errors='ignore')
    
    result_dfs.append(group)
    
    if idx % 500 == 0:
        print(f"   已处理: {idx:,} / {len(all_codes):,} 只股票")

print(f"✅ 所有 {len(all_codes):,} 只股票因子计算完成")
print()

# 合并所有结果
final_df = pd.concat(result_dfs, ignore_index=True)
print(f"📊 总记录数: {len(final_df):,}")
print()

# 批量更新
print("💾 开始写入MongoDB...")

# 只选择需要更新的列
factor_cols = [
    'ma5', 'ma10', 'ma20', 'ma60',
    'ema5', 'ema10', 'ema20', 'ema60', 'ema12', 'ema26',
    'rsi_6', 'rsi_12', 'rsi_24',
    'boll_upper', 'boll_mid', 'boll_lower',
    'atr', 'atr_14', 'natr', 'trange',
    'macd', 'macd_signal', 'macd_hist',
    'amount_20d',
    'momentum_5d', 'momentum_10d', 'momentum_20d',
    'volatility_5d', 'volatility_10d', 'volatility_20d',
    'turnover_20d',
    'amplitude',
]

batch_size = 1000
total_updated = 0

for i in range(0, len(final_df), batch_size):
    batch = final_df.iloc[i:i+batch_size]
    operations = []
    
    for _, row in batch.iterrows():
        update_dict = {col: row[col] for col in factor_cols if col in row and pd.notna(row[col])}
        
        if update_dict:
            operations.append(
                pymongo.UpdateOne(
                    {'ts_code': row['ts_code'], 'trade_date': int(row['trade_date'])},
                    {'$set': update_dict}
                )
            )
    
    if operations:
        coll.bulk_write(operations, ordered=False)
        total_updated += len(operations)
        print(f"   已写入: {total_updated:,} / {len(final_df):,}")

print()
print("="*80)
print("🎉 所有因子计算完成！")
print("="*80)
print(f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"总共更新: {total_updated:,} 条记录")
print()
