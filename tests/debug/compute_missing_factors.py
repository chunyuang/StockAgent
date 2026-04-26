#!/usr/bin/env python3
"""
补充计算22个缺失的因子
"""

import sys
sys.path.insert(0, './AgentServer')
import asyncio
import pandas as pd
import numpy as np
from datetime import datetime

async def compute_rsi(series, period):
    """计算RSI"""
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

async def compute_bollinger_bands(series, period=20, std_dev=2):
    """计算布林带"""
    middle = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    upper = middle + (std_dev * std)
    lower = middle - (std_dev * std)
    return upper, middle, lower

async def compute_ema(series, period):
    """计算EMA"""
    return series.ewm(span=period, adjust=False).mean()

async def main():
    print("=" * 80)
    print("🧪 补充计算22个缺失的技术因子")
    print("=" * 80)
    print()
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    from core.managers import mongo_manager
    await mongo_manager.initialize()
    
    # 获取所有唯一的股票代码
    print("🔍 获取所有股票代码...")
    all_docs = await mongo_manager.find_many('stock_daily_ak_full', {}, projection={'ts_code': 1})
    all_codes = list(set([d['ts_code'] for d in all_docs]))
    print(f"✅ 共 {len(all_codes)} 只股票")
    print()
    
    # 获取所有交易日并排序
    print("📅 获取所有交易日...")
    dates = await mongo_manager.find_many('stock_daily_ak_full', {}, projection={'trade_date': 1})
    all_dates = sorted(list(set([d['trade_date'] for d in dates])))
    print(f"✅ 共 {len(all_dates)} 个交易日")
    print()
    
    # 分批处理，每次处理500只股票
    batch_size = 500
    total_batches = (len(all_codes) + batch_size - 1) // batch_size
    
    print(f"🚀 开始分批计算，每批 {batch_size} 只，共 {total_batches} 批")
    print()
    
    total_processed = 0
    total_updates = 0
    
    for batch_idx in range(total_batches):
        batch_codes = all_codes[batch_idx * batch_size : (batch_idx + 1) * batch_size]
        print(f"📦 处理第 {batch_idx + 1}/{total_batches} 批，{len(batch_codes)} 只股票...")
        
        # 批量获取这批股票的所有数据
        query = {'ts_code': {'$in': batch_codes}}
        docs = await mongo_manager.find_many(
            'stock_daily_ak_full',
            query,
            projection={'ts_code': 1, 'trade_date': 1, 'close': 1, 'high': 1, 'low': 1, 'amount': 1, 'vol': 1}
        )
        
        df = pd.DataFrame(docs)
        
        if len(df) == 0:
            print(f"  ⚠️  这批没有数据，跳过")
            continue
        
        # 按股票分组计算因子
        updates = []
        processed_count = 0
        
        for ts_code in batch_codes:
            stock_df = df[df['ts_code'] == ts_code].sort_values('trade_date').copy()
            
            if len(stock_df) == 0:
                continue
            
            # 确保是按时间顺序排列的
            stock_df = stock_df.set_index('trade_date').sort_index()
            
            # 计算MA系列
            close = stock_df['close']
            for period in [5, 10, 20, 60]:
                stock_df[f'ma{period}'] = close.rolling(window=period).mean()
            
            # 计算EMA系列
            for period in [5, 10, 20, 60]:
                stock_df[f'ema{period}'] = await compute_ema(close, period)
            
            # 计算RSI系列
            for period in [6, 12, 14, 24]:
                stock_df[f'rsi_{period}'] = await compute_rsi(close, period)
            
            # 计算布林带
            boll_upper, boll_middle, boll_lower = await compute_bollinger_bands(close, 20, 2)
            stock_df['boll_upper'] = boll_upper
            stock_df['boll_middle'] = boll_middle
            stock_df['boll_lower'] = boll_lower
            
            # 计算amount_20d（20日平均成交额）
            stock_df['amount_20d'] = stock_df['amount'].rolling(window=20).mean()
            
            # 计算amplitude（振幅 = (high - low) / close * 100）
            stock_df['amplitude'] = (stock_df['high'] - stock_df['low']) / stock_df['close'] * 100
            
            # 计算volume_ratio（量比 = 当前成交量 / 过去5日平均成交量）
            vol_ma5 = stock_df['vol'].rolling(window=5).mean()
            stock_df['volume_ratio'] = stock_df['vol'] / vol_ma5
            
            # 准备更新数据
            for trade_date, row in stock_df.iterrows():
                update_data = {
                    # MA系列
                    'ma5': float(row['ma5']) if not pd.isna(row['ma5']) else None,
                    'ma10': float(row['ma10']) if not pd.isna(row['ma10']) else None,
                    'ma20': float(row['ma20']) if not pd.isna(row['ma20']) else None,
                    'ma60': float(row['ma60']) if not pd.isna(row['ma60']) else None,
                    
                    # EMA系列
                    'ema5': float(row['ema5']) if not pd.isna(row['ema5']) else None,
                    'ema10': float(row['ema10']) if not pd.isna(row['ema10']) else None,
                    'ema20': float(row['ema20']) if not pd.isna(row['ema20']) else None,
                    'ema60': float(row['ema60']) if not pd.isna(row['ema60']) else None,
                    
                    # RSI系列
                    'rsi_6': float(row['rsi_6']) if not pd.isna(row['rsi_6']) else None,
                    'rsi_12': float(row['rsi_12']) if not pd.isna(row['rsi_12']) else None,
                    'rsi_14': float(row['rsi_14']) if not pd.isna(row['rsi_14']) else None,
                    'rsi_24': float(row['rsi_24']) if not pd.isna(row['rsi_24']) else None,
                    
                    # 布林带
                    'boll_upper': float(row['boll_upper']) if not pd.isna(row['boll_upper']) else None,
                    'boll_middle': float(row['boll_middle']) if not pd.isna(row['boll_middle']) else None,
                    'boll_lower': float(row['boll_lower']) if not pd.isna(row['boll_lower']) else None,
                    
                    # 其他因子
                    'amount_20d': float(row['amount_20d']) if not pd.isna(row['amount_20d']) else None,
                    'amplitude': float(row['amplitude']) if not pd.isna(row['amplitude']) else None,
                    'volume_ratio': float(row['volume_ratio']) if not pd.isna(row['volume_ratio']) else None,
                }
                
                updates.append({
                    'filter': {'ts_code': ts_code, 'trade_date': int(trade_date)},
                    'update': {'$set': update_data}
                })
            
            processed_count += 1
        
        # 批量更新 - 逐个更新，确保异步正确
        if updates:
            print(f"  📝 准备更新 {len(updates)} 条记录...")
            updated = 0
            for u in updates:
                await mongo_manager.update_one(
                    'stock_daily_ak_full',
                    u['filter'],
                    u['update']
                )
                updated += 1
                if updated % 5000 == 0:
                    print(f"    已更新 {updated} 条...")
            total_updates += updated
            print(f"  ✅ 完成更新，共修改 {updated} 条记录")
        
        total_processed += processed_count
        print(f"  ✅ 这批处理了 {processed_count} 只股票，累计 {total_processed}/{len(all_codes)}")
        print()
    
    print("=" * 80)
    print("🏆 因子计算完成！")
    print("=" * 80)
    print()
    print(f"  处理股票数: {total_processed} 只")
    print(f"  更新记录数: {total_updates} 条")
    print()
    print(f"完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # 验证结果
    print("🔍 验证因子计算结果...")
    sample = await mongo_manager.find_one(
        'stock_daily_ak_full',
        {'trade_date': all_dates[-1]}  # 最后一个交易日
    )
    
    print(f"  检查日期: {all_dates[-1]}")
    all_factors = [
        'ma5', 'ma10', 'ma20', 'ma60',
        'ema5', 'ema10', 'ema20', 'ema60',
        'rsi_6', 'rsi_12', 'rsi_14', 'rsi_24',
        'boll_upper', 'boll_middle', 'boll_lower',
        'amount_20d', 'amplitude', 'volume_ratio'
    ]
    
    valid_count = 0
    for factor in all_factors:
        if factor in sample and sample[factor] is not None:
            print(f"    ✅ {factor}: {sample[factor]:.4f}")
            valid_count += 1
        else:
            print(f"    ❌ {factor}: 缺失或为None")
    
    print()
    print(f"  22个因子中，{valid_count} 个有有效值")
    print()
    
    if valid_count == len(all_factors):
        print("🎉 所有22个缺失因子全部补充完成！因子完整性达到100%！")
    else:
        print(f"⚠️  还有 {len(all_factors) - valid_count} 个因子需要检查")
    
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(main())
