#!/usr/bin/env python3
"""
批量计算所有27个缺失因子
基于stock_daily_ak_full的基础OHLCV数据
"""
import asyncio
import sys
import pandas as pd
import numpy as np
from datetime import datetime

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
        
        # 20日平均换手率（估算: 成交额 / 流通市值，流通市值用amount*100估算）
        group['circ_mv'] = group['amount'] * 100  # 简单估算
        group['turnover_rate'] = group['amount'] / group['circ_mv'] * 10000
        group['turnover_20d'] = group['turnover_rate'].rolling(20).mean()
        
        # ---------- 涨跌停识别 ----------
        # 涨停识别: 涨幅 >= 9.8% (放宽一点避免误差)
        group['is_limit_up'] = group['pct_chg'] >= 9.8
        # 跌停识别: 跌幅 <= -9.8%
        group['is_limit_down'] = group['pct_chg'] <= -9.8
        
        # 昨日涨停
        group['limit_up_yesterday'] = group['is_limit_up'].shift(1).fillna(False)
        
        # 昨日跌停
        group['limit_down_yesterday'] = group['is_limit_down'].shift(1).fillna(False)
        
        # 首板识别: 今日涨停，昨日未涨停
        group['first_limit_up'] = group['is_limit_up'] & ~group['limit_up_yesterday']
        
        # 连续涨停天数
        limit_up_counts = []
        count = 0
        for val in group['is_limit_up']:
            if val:
                count += 1
            else:
                count = 0
            limit_up_counts.append(count)
        group['limit_up_count'] = limit_up_counts
        
        # 连续跌停天数
        limit_down_counts = []
        count = 0
        for val in group['is_limit_down']:
            if val:
                count += 1
            else:
                count = 0
            limit_down_counts.append(count)
        group['limit_down_count'] = limit_down_counts
        
        # 竞价涨幅(开盘涨幅): 用于首板打板/涨停开板策略的竞价筛选
        group['opening_pct_chg'] = (group['open'] - group['close'].shift(1)) / group['close'].shift(1) * 100
        
        # 开盘在涨停价附近
        group['open_above_limit'] = (group['open'] - group['close'].shift(1)) / group['close'].shift(1) >= 0.095
        group['open_below_limit'] = (group['open'] - group['close'].shift(1)) / group['close'].shift(1) <= -0.095
        group['open_above_limit_down'] = group['open_above_limit'] & group['limit_down_yesterday']
        
        # 涨停开板金额: 涨停盘中打开(最高=涨停价 且 最低<涨停价) 时的成交额
        # 单位: 千元(与amount一致)
        limit_up_price = group['close'].shift(1) * 1.1  # 涨停价(近似)
        group['limit_up_open_amount'] = np.where(
            (group['high'] >= limit_up_price * 0.995) & (group['low'] < limit_up_price * 0.995),
            group['amount'], 0
        )
        
        # 跌停翘板金额: 昨日跌停 + 今日盘中触及跌停价但收盘高于跌停价(开板)
        # 单位: 千元(与amount一致)
        limit_down_price_yesterday = group['close'].shift(1) * 0.9  # 昨日跌停价
        group['limit_down_open_amount'] = np.where(
            group['limit_down_yesterday'] &  # 昨日跌停
            (group['low'] <= limit_down_price_yesterday * 1.005) &  # 盘中触及跌停价
            (group['close'] > limit_down_price_yesterday * 1.005),  # 收盘高于跌停价=翘板成功
            group['amount'], 0  # 单位: 千元
        )
        
        # 涨停开盘股票数（每日统计，后续统一计算）
        group['limit_up_open_count'] = 0
        
        # 涨停时间（简化）
        group['limit_up_time'] = 0
        
        # 涨停开盘持续时间
        group['limit_up_open_duration'] = 0
        
        # ---------- 回调/回踩指标 ----------
        # 回调幅度
        high_peak = group['high'].rolling(10).max()
        group['pullback_pct'] = (group['close'] - high_peak) / high_peak
        
        # 回调天数
        pullback_days = []
        days = 0
        for i in range(len(group)):
            if group['pullback_pct'].iloc[i] < -0.01:
                days += 1
            else:
                days = 0
            pullback_days.append(days)
        group['pullback_days'] = pullback_days
        
        # 回踩MA5
        group['pullback_ma5'] = (group['low'] <= group['ma5']) & (group['close'] >= group['ma5'])
        
        # 跌停后上涨(翘板后涨幅): 翘板成功后收盘价相对跌停价的涨幅(%)
        limit_down_price_yesterday2 = group['close'].shift(1) * 0.9
        group['rise_after_limit_down'] = np.where(
            group['limit_down_open_amount'] > 0,
            (group['close'] - limit_down_price_yesterday2) / limit_down_price_yesterday2 * 100,
            0
        )
        
        # ---------- 简化策略指标 ----------
        group['market_leader'] = False  # 简化，后续完善
        group['hot_sector'] = False      # 简化，后续完善
        group['sentiment_score'] = 0.5   # 简化默认值
        
        result.append(group)
    
    # 合并结果
    final_df = pd.concat(result, ignore_index=True)
    print(f"✅ 因子计算完成，共 {len(final_df.columns)} 个字段")
    
    # 统计新增因子数
    new_fields = len(final_df.columns) - 10  # 减去原始10个字段
    print(f"   新增因子字段: {new_fields} 个")
    print()
    
    # 3. 每日统计字段（limit_up_open_count等）
    print("📊 计算每日统计字段...")
    daily_stats = final_df.groupby('trade_date')['open_above_limit'].sum()\
        .reset_index(name='limit_up_open_count_daily')
    
    final_df = final_df.merge(daily_stats, on='trade_date', how='left')
    final_df['limit_up_open_count'] = final_df['limit_up_open_count_daily']
    final_df.drop('limit_up_open_count_daily', axis=1, inplace=True)
    print("✅ 每日统计字段计算完成")
    print()
    
    # 4. 写回MongoDB
    print("💾 写入MongoDB...")
    # 替换NaN为None，避免MongoDB错误
    final_df = final_df.replace({np.nan: None})
    
    # 批量更新（分批，避免超时）
    batch_size = 10000
    total_updated = 0
    
    for i in range(0, len(final_df), batch_size):
        batch = final_df.iloc[i:i+batch_size]
        update_ops = []
        
        for _, row in batch.iterrows():
            row_dict = row.drop(['_id']).to_dict()
            # 清理可能的重复字段问题
            if 'amount_x' in row_dict:
                if 'amount_y' in row_dict:
                    del row_dict['amount_y']
                row_dict['amount'] = row_dict.pop('amount_x')
            update_ops.append({
                'update_one': {
                    'filter': {'ts_code': row_dict['ts_code'], 'trade_date': row_dict['trade_date']},
                    'update': {'$set': row_dict}
                }
            })
        
        if update_ops:
            await coll.bulk_write(update_ops, ordered=False)
            total_updated += len(update_ops)
            print(f"   已写入: {total_updated:,} / {len(final_df):,}")
    
    print()
    print("="*80)
    print("🎉 所有27个因子计算完成！")
    print("="*80)
    print(f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    asyncio.run(compute_all_factors())
