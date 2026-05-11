#!/usr/bin/env python3
"""
每日因子预计算 - 在数据补全后运行

从stock_daily_ak_full + daily_basic计算缺失的因子并写回MongoDB
这样回测时不需要再等factor_auto_compute

用法: python3 daily_factor_precompute.py [--date 20260508]
"""
import sys
import os
import time
import argparse
from datetime import datetime, timedelta

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from pymongo import MongoClient, UpdateOne
import numpy as np
import pandas as pd

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "stock_agent"

# 需要预计算的关键因子(回测高频使用)
KEY_FACTORS = [
    "turnover_rate", "volume_ratio", "amount_20d",
    "ma5", "ma10", "ma20", "ma60",
    "rsi_6", "rsi_12",
    "limit_up_yesterday", "limit_down_yesterday",
    "open_above_limit", "open_above_limit_down",
    "limit_up_count", "limit_down_count",
    "first_limit_up",
    "is_limit_up", "is_limit_down",
    "pullback_pct", "pullback_days", "pullback_ma5",
]

def precompute_factors(trade_date: int):
    """预计算指定日期的因子"""
    db = MongoClient(MONGO_URI)[DB_NAME]
    
    print(f"预计算因子: {trade_date}")
    t0 = time.time()
    
    # 1. 读取最近60天数据(计算MA60需要)
    start_date = trade_date - 300  # 粗略估计，取足够多的交易日
    pipeline = [
        {"$match": {"trade_date": {"$gte": start_date, "$lte": trade_date}}},
        {"$sort": {"ts_code": 1, "trade_date": 1}},
    ]
    
    raw = list(db.stock_daily_ak_full.aggregate(pipeline, allowDiskUse=True))
    if not raw:
        print(f"  ⚠️ 无数据")
        return 0
    
    df = pd.DataFrame(raw)
    print(f"  读取{len(df)}条记录, {df['ts_code'].nunique()}只股票")
    
    # 2. 合并daily_basic数据
    basic_data = list(db.daily_basic.find({"trade_date": {"$gte": start_date, "$lte": trade_date}}))
    if basic_data:
        basic_df = pd.DataFrame(basic_data)[['ts_code', 'trade_date', 'turnover_rate', 'volume_ratio', 'circ_mv', 'pe_ttm', 'pb']]
        df = df.merge(basic_df, on=['ts_code', 'trade_date'], how='left', suffixes=('', '_basic'))
        # 优先用daily_basic的字段
        for col in ['turnover_rate', 'volume_ratio', 'circ_mv']:
            basic_col = col + '_basic' if col + '_basic' in df.columns else None
            if basic_col:
                df[col] = df[basic_col].fillna(df.get(col))
    
    # 3. 按股票分组计算因子
    results = []
    grouped = df.groupby('ts_code')
    
    for code, group in grouped:
        group = group.sort_values('trade_date')
        
        # 只处理目标日期
        target = group[group['trade_date'] == trade_date]
        if target.empty:
            continue
        
        row = target.iloc[0]
        update = {}
        
        # MA5/10/20/60
        close_series = group['close'].astype(float)
        for period, name in [(5, 'ma5'), (10, 'ma10'), (20, 'ma20'), (60, 'ma60')]:
            if len(close_series) >= period:
                ma = close_series.rolling(period).mean().iloc[-1]
                if pd.notna(ma):
                    update[name] = round(ma, 2)
        
        # 涨跌停判断
        close = float(row.get('close', 0))
        pre_close = float(row.get('pre_close', 0))
        pct_chg = float(row.get('pct_chg', 0)) if pd.notna(row.get('pct_chg')) else 0
        
        if pre_close > 0:
            code_str = row['ts_code'].split('.')[0]
            if code_str.startswith(('300', '301', '688')):
                limit_pct = 20
            elif code_str.startswith(('8', '4')):
                limit_pct = 30
            else:
                limit_pct = 10
            
            update['is_limit_up'] = 1 if pct_chg >= (limit_pct - 0.5) else 0
            update['is_limit_down'] = 1 if pct_chg <= -(limit_pct - 0.5) else 0
        
        # 昨日涨跌停
        if len(group) >= 2:
            yesterday = group.iloc[-2]
            y_pct = float(yesterday.get('pct_chg', 0)) if pd.notna(yesterday.get('pct_chg')) else 0
            update['limit_up_yesterday'] = 1 if y_pct >= 9.5 else 0
            update['limit_down_yesterday'] = 1 if y_pct <= -9.5 else 0
            
            # 开盘高于/低于涨跌停价
            y_close = float(yesterday.get('close', 0))
            today_open = float(row.get('open', 0))
            if y_close > 0:
                limit_up_price = y_close * 1.1
                limit_down_price = y_close * 0.9
                update['open_above_limit'] = 1 if today_open >= limit_up_price * 0.995 else 0
                update['open_above_limit_down'] = 1 if (today_open > limit_down_price and update.get('limit_down_yesterday') == 1) else 0
        
        # 近5日涨停/跌停次数
        if len(group) >= 5:
            last5 = group.tail(5)
            update['limit_up_count'] = int(last5.get('is_limit_up', pd.Series([0]*5)).sum())
            update['limit_down_count'] = int(last5.get('is_limit_down', pd.Series([0]*5)).sum())
        
        # 涨停/跌停打开 (简化版)
        update['first_limit_up'] = update.get('is_limit_up', 0)
        
        # 回调指标(pullback_pct/pullback_days/pullback_ma5)
        if len(group) >= 10:
            high_10 = group['high'].astype(float).tail(10).max()
            close_val = float(row.get('close', 0))
            if high_10 > 0:
                update['pullback_pct'] = round((close_val - high_10) / high_10, 4)
            
            # pullback_days: 连续回调天数
            pb_days = 0
            for j in range(len(group) - 1, max(len(group) - 10, -1), -1):
                pb_val = (float(group.iloc[j]['close']) - float(group.iloc[j-max(0,j-len(group)+10):j+1]['high'].max())) / float(group.iloc[j-max(0,j-len(group)+10):j+1]['high'].max()) if len(group) > 0 else 0
                if pb_val < -0.01:
                    pb_days += 1
                else:
                    break
            update['pullback_days'] = pb_days
            
            # pullback_ma5: 最低价<=MA5 且 收盘价>=MA5
            ma5_val = update.get('ma5')
            low_val = float(row.get('low', 0))
            if ma5_val and ma5_val > 0:
                update['pullback_ma5'] = 1 if (low_val <= ma5_val and close_val >= ma5_val) else 0
        
        if update:
            results.append(
                UpdateOne(
                    {"ts_code": row['ts_code'], "trade_date": trade_date},
                    {"$set": update},
                    upsert=False,
                )
            )
    
    # 4. 批量写入
    if results:
        t1 = time.time()
        r = db.stock_daily_ak_full.bulk_write(results, ordered=False)
        print(f"  更新{r.modified_count}条因子, 耗时{time.time()-t1:.1f}s")
    
    total_time = time.time() - t0
    print(f"  总耗时: {total_time:.1f}s")
    return len(results)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=int, default=None, help="日期yyyymmdd，默认最近交易日")
    parser.add_argument("--days", type=int, default=1, help="补算最近N天")
    args = parser.parse_args()
    
    if args.date:
        precompute_factors(args.date)
    else:
        # 默认补最近N天
        db = MongoClient(MONGO_URI)[DB_NAME]
        # 找最近有数据的交易日
        latest = list(db.stock_daily_ak_full.find({}, {"trade_date": 1}).sort("trade_date", -1).limit(1))
        if latest:
            latest_date = latest[0]['trade_date']
            print(f"最新交易日: {latest_date}, 补算最近{args.days}天")
            # 简单处理：只补最新一天
            precompute_factors(latest_date)
