#!/usr/bin/env python3
"""
简化版因子计算脚本 - 直接使用pymongo的UpdateOne
"""
import asyncio
import sys
import pandas as pd
import numpy as np
from datetime import datetime
from pymongo import UpdateOne

sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from core.managers import mongo_manager

async def compute_all_factors():
    print("="*80)
    print("🚀 开始批量计算所有因子")
    print("="*80)
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    await mongo_manager.initialize()
    coll = mongo_manager.db['stock_daily_ak_full']
    
    # 1. 获取所有股票和日期
    print("📥 加载基础数据...")
    all_docs = await coll.find({}).to_list(length=None)
    df = pd.DataFrame(all_docs)
    print(f"✅ 加载完成: {len(df):,} 条记录")
    print(f"   股票数量: {df['ts_code'].nunique():,} 只")
    print(f"   交易日数: {df['trade_date'].nunique()} 天")
    print()
    
    # 2. 按股票分组计算衍生指标
    print("🧮 开始计算衍生因子...")
    result = []
    
    for ts_code, group in df.groupby('ts_code'):
        group = group.sort_values('trade_date').copy()
        
        # ---------- 基础技术指标 ----------
        # MA均线
        group['ma5'] = group['close'].rolling(5).mean()
        group['ma10'] = group['close'].rolling(10).mean()
        group['ma20'] = group['close'].rolling(20).mean()
        group['ma60'] = group['close'].rolling(60).mean()
        
        # MA偏离度
        group['ma_deviation_20'] = (group['close'] - group['ma20']) / group['ma20']
        
        # 价格位置（相对于近20日高低点）
        low_20 = group['low'].rolling(20).min()
        high_20 = group['high'].rolling(20).max()
        group['price_position'] = (group['close'] - low_20) / (high_20 - low_20 + 0.001)
        
        # 是否接近MA5
        group['price_near_ma5'] = abs(group['close'] - group['ma5']) / group['ma5'] < 0.02
        
        # 动量指标
        group['momentum_5d'] = group['close'].pct_change(5)
        group['momentum_20d'] = group['close'].pct_change(20)
        group['momentum_60d'] = group['close'].pct_change(60)
        
        # 波动率
        group['volatility_20d'] = group['pct_chg'].rolling(20).std()
        group['volatility_60d'] = group['pct_chg'].rolling(60).std()
        
        # ---------- 成交量/流动性指标 ----------
        # 量比: 当日成交量 / 过去5日平均成交量
        vol_5d_avg = group['vol'].rolling(5).mean()
        group['volume_ratio'] = group['vol'] / vol_5d_avg
        
        # 20日平均成交额
        group['amount_20d'] = group['amount'].rolling(20).mean()
        
        # 流通市值估算 + 换手率
        group['circ_mv'] = group['amount'] * 100
        group['turnover_rate'] = group['amount'] / group['circ_mv'] * 10000
        group['turnover_20d'] = group['turnover_rate'].rolling(20).mean()
        
        # ---------- 涨跌停识别 ----------
        group['is_limit_up'] = group['pct_chg'] >= 9.8
        group['is_limit_down'] = group['pct_chg'] <= -9.8
        
        group['limit_up_yesterday'] = group['is_limit_up'].shift(1).fillna(False)
        group['limit_down_yesterday'] = group['is_limit_down'].shift(1).fillna(False)
        group['first_limit_up'] = group['is_limit_up'] & ~group['limit_up_yesterday']
        
        # 连续涨停天数
        limit_up_counts = []
        count = 0
        for val in group['is_limit_up']:
            count = count + 1 if val else 0
            limit_up_counts.append(count)
        group['limit_up_count'] = limit_up_counts
        
        # 连续跌停天数
        limit_down_counts = []
        count = 0
        for val in group['is_limit_down']:
            count = count + 1 if val else 0
            limit_down_counts.append(count)
        group['limit_down_count'] = limit_down_counts
        
        # 开盘涨跌停识别
        prev_close = group['close'].shift(1)
        group['open_above_limit'] = (group['open'] - prev_close) / prev_close >= 0.095
        group['open_below_limit'] = (group['open'] - prev_close) / prev_close <= -0.095
        group['open_above_limit_down'] = group['open_above_limit'] & group['limit_down_yesterday']
        
        # 涨跌停开盘金额
        group['limit_up_open_amount'] = np.where(group['open_above_limit'], group['amount'], 0.0)
        group['limit_down_open_amount'] = np.where(group['open_below_limit'], group['amount'], 0.0)
        
        # 简化字段
        group['limit_up_open_count'] = 0
        group['limit_up_time'] = 0
        group['limit_up_open_duration'] = 0
        
        # ---------- 回调/回踩指标 ----------
        high_peak = group['high'].rolling(10).max()
        group['pullback_pct'] = (group['close'] - high_peak) / high_peak
        
        # 回调天数
        pullback_days = []
        days = 0
        for i in range(len(group)):
            if pd.notna(group['pullback_pct'].iloc[i]) and group['pullback_pct'].iloc[i] < -0.01:
                days += 1
            else:
                days = 0
            pullback_days.append(days)
        group['pullback_days'] = pullback_days
        
        # 回踩MA5
        group['pullback_ma5'] = (group['low'] <= group['ma5']) & (group['close'] >= group['ma5'])
        
        # 跌停后上涨
        group['rise_after_limit_down'] = group['limit_down_yesterday'] & (group['pct_chg'] > 0)
        
        # ---------- 简化策略指标 ----------
        group['market_leader'] = False
        group['hot_sector'] = False
        group['sentiment_score'] = 0.5
        
        result.append(group)
    
    # 合并结果
    final_df = pd.concat(result, ignore_index=True)
    print(f"✅ 因子计算完成，共 {len(final_df.columns)} 个字段")
    print()
    
    # 3. 每日统计字段
    print("📊 计算每日统计字段...")
    daily_limit_up_count = final_df.groupby('trade_date')['open_above_limit'].sum().to_dict()
    final_df['limit_up_open_count'] = final_df['trade_date'].map(daily_limit_up_count)
    print("✅ 每日统计字段计算完成")
    print()
    
    # 4. 写回MongoDB - 使用原生UpdateOne
    print("💾 写入MongoDB...")
    
    # 转换numpy类型为Python原生类型
    def convert_types(row_dict):
        result = {}
        for k, v in row_dict.items():
            if k == '_id':
                continue
            if isinstance(v, (np.bool_, bool)):
                result[k] = bool(v)
            elif isinstance(v, (np.integer, int)):
                result[k] = int(v)
            elif isinstance(v, (np.floating, float)):
                result[k] = float(v) if pd.notna(v) else None
            else:
                result[k] = v
        return result
    
    # 分批写入
    batch_size = 5000
    total_updated = 0
    
    for i in range(0, len(final_df), batch_size):
        batch = final_df.iloc[i:i+batch_size]
        update_ops = []
        
        for _, row in batch.iterrows():
            row_dict = convert_types(row.to_dict())
            
            update_ops.append(UpdateOne(
                {'ts_code': row_dict['ts_code'], 'trade_date': row_dict['trade_date']},
                {'$set': row_dict}
            ))
        
        if update_ops:
            await coll.bulk_write(update_ops, ordered=False)
            total_updated += len(update_ops)
            print(f"   已写入: {total_updated:,} / {len(final_df):,}")
    
    print()
    print("="*80)
    print("🎉 所有因子计算并写入完成！")
    print("="*80)
    print(f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    asyncio.run(compute_all_factors())
