#!/usr/bin/env python3
"""独立补算5/15和5/19缺失的因子（无需导入backtest_engine模块）"""
import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'nodes'))

import pandas as pd
import numpy as np
from pymongo import MongoClient, UpdateOne

db = MongoClient('localhost', 27017)['stock_agent']

# ===== 策略因子(简单计算) =====
STRATEGY_FIELDS = [
    'ma5', 'ma10', 'ma20', 'ma60',
    'volume_ratio', 'circ_mv', 'turnover_rate',
    'is_limit_up', 'is_limit_down', 'first_limit_up', 'limit_up_count',
    'opening_pct_chg', 'limit_up_yesterday',
    'pullback_pct', 'pullback_days', 'rise_after_limit_down',
    'limit_down_open_amount', 'limit_up_open_amount',
]

# ===== 技术因子(需talib) =====
TECHNICAL_FIELDS = [
    'rsi_6', 'rsi_12', 'rsi_24',
    'macd', 'macd_signal', 'macd_hist',
    'boll_upper', 'boll_mid', 'boll_lower',
    'atr', 'natr', 'trange',
]

ALL_FIELDS = STRATEGY_FIELDS + TECHNICAL_FIELDS


def detect_missing(td):
    """检测某天缺失的因子"""
    total = db.stock_daily_ak_full.count_documents({'trade_date': td})
    if total == 0:
        return [], total
    missing = []
    for f in ALL_FIELDS:
        cnt = db.stock_daily_ak_full.count_documents({'trade_date': td, f: {'$exists': True}})
        if cnt < total * 0.5:
            missing.append(f)
    return missing, total


def compute_strategy_factors(td):
    """计算策略因子(MA/涨跌停/开盘涨幅等)"""
    total = db.stock_daily_ak_full.count_documents({'trade_date': td})
    if total == 0:
        return 0
    
    # 1. 从daily_basic同步基础字段
    basic_docs = list(db.daily_basic.find({'trade_date': td}, {
        'ts_code': 1, 'circ_mv': 1, 'turnover_rate': 1, 'volume_ratio': 1, 'pe_ttm': 1, 'pb': 1
    }))
    if basic_docs:
        ops = []
        for d in basic_docs:
            update = {}
            for k in ['circ_mv', 'turnover_rate', 'volume_ratio', 'pe_ttm', 'pb']:
                if d.get(k): update[k] = d[k]
            if update:
                ops.append(UpdateOne({'ts_code': d['ts_code'], 'trade_date': td}, {'$set': update}))
        if ops:
            db.stock_daily_ak_full.bulk_write(ops)
    
    # 2. 计算MA
    for ma_n in [5, 10, 20, 60]:
        ma_key = f'ma{ma_n}'
        # 获取前N天日期
        pipeline = [
            {'$match': {'trade_date': {'$lte': td}}},
            {'$group': {'_id': '$trade_date'}},
            {'$sort': {'_id': -1}},
            {'$limit': ma_n}
        ]
        recent_dates = sorted([d['_id'] for d in db.stock_daily_ak_full.aggregate(pipeline)])
        if len(recent_dates) < ma_n:
            continue
        
        cursor = db.stock_daily_ak_full.find(
            {'trade_date': {'$in': recent_dates}},
            {'ts_code': 1, 'trade_date': 1, 'close': 1}
        )
        stock_data = {}
        for doc in cursor:
            stock_data.setdefault(doc['ts_code'], []).append((doc['trade_date'], doc.get('close', 0)))
        
        ops = []
        for ts_code, data in stock_data.items():
            data.sort()
            close_vals = [d[1] for d in data[-ma_n:] if d[1] is not None and d[1] != 0]
            if len(close_vals) >= ma_n * 0.8:  # 至少80%有值
                ma_val = sum(close_vals) / len(close_vals)
                ops.append(UpdateOne({'ts_code': ts_code, 'trade_date': td}, {'$set': {ma_key: round(ma_val, 4)}}))
        
        if ops:
            r = db.stock_daily_ak_full.bulk_write(ops)
            print(f'  {ma_key}: {r.modified_count} records')
    
    # 3. 计算涨跌停标记
    cursor = db.stock_daily_ak_full.find({'trade_date': td}, {'ts_code': 1, 'pct_chg': 1, 'close': 1, 'pre_close': 1, 'open': 1})
    ops = []
    for doc in cursor:
        update = {}
        pct = doc.get('pct_chg') or 0
        close = doc.get('close') or 0
        pre_close = doc.get('pre_close') or 0
        open_price = doc.get('open') or 0
        
        # 涨停: pct_chg >= 9.9% (考虑四舍五入)
        is_limit_up = 1 if pct >= 9.9 else 0
        is_limit_down = 1 if pct <= -9.9 else 0
        update['is_limit_up'] = is_limit_up
        update['is_limit_down'] = is_limit_down
        
        # 开盘涨幅
        if pre_close and pre_close > 0:
            update['opening_pct_chg'] = round((open_price / pre_close - 1) * 100, 2)
        
        ops.append(UpdateOne({'ts_code': doc['ts_code'], 'trade_date': td}, {'$set': update}))
    
    if ops:
        r = db.stock_daily_ak_full.bulk_write(ops)
        print(f'  limit_flags: {r.modified_count} records')
    
    return total


def compute_technical_factors(td):
    """计算技术因子(RSI/MACD/BOLL/ATR)，需talib"""
    try:
        import talib
    except ImportError:
        print('  talib未安装，跳过技术因子计算')
        return 0
    
    # 获取回溯数据(3个月)
    pipeline = [
        {'$match': {'trade_date': {'$lte': td}}},
        {'$group': {'_id': '$trade_date'}},
        {'$sort': {'_id': -1}},
        {'$limit': 90}
    ]
    recent_dates = sorted([d['_id'] for d in db.stock_daily_ak_full.aggregate(pipeline)])
    
    # 加载这些日期的OHLCV
    cursor = db.stock_daily_ak_full.find(
        {'trade_date': {'$in': recent_dates}},
        {'ts_code': 1, 'trade_date': 1, 'open': 1, 'high': 1, 'low': 1, 'close': 1, 'vol': 1, 'pct_chg': 1}
    )
    
    stock_data = {}
    for doc in cursor:
        stock_data.setdefault(doc['ts_code'], []).append(doc)
    
    ops = []
    computed = 0
    for ts_code, docs in stock_data.items():
        df = pd.DataFrame(docs).sort_values('trade_date')
        if len(df) < 30:
            continue
        
        close_arr = df['close'].fillna(0).values.astype(float)
        high_arr = df['high'].fillna(0).values.astype(float)
        low_arr = df['low'].fillna(0).values.astype(float)
        open_arr = df['open'].fillna(0).values.astype(float)
        vol_arr = df['vol'].fillna(0).values.astype(float)
        
        update = {}
        try:
            # RSI
            update['rsi_6'] = round(float(talib.RSI(close_arr, timeperiod=6)[-1]), 4)
            update['rsi_12'] = round(float(talib.RSI(close_arr, timeperiod=12)[-1]), 4)
            update['rsi_24'] = round(float(talib.RSI(close_arr, timeperiod=24)[-1]), 4)
            
            # MACD
            macd, macd_signal, macd_hist = talib.MACD(close_arr)
            update['macd'] = round(float(macd[-1]), 4)
            update['macd_signal'] = round(float(macd_signal[-1]), 4)
            update['macd_hist'] = round(float(macd_hist[-1]), 4)
            
            # BOLL
            upper, mid, lower = talib.BBANDS(close_arr, timeperiod=20)
            update['boll_upper'] = round(float(upper[-1]), 4)
            update['boll_mid'] = round(float(mid[-1]), 4)
            update['boll_lower'] = round(float(lower[-1]), 4)
            
            # ATR
            atr_val = talib.ATR(high_arr, low_arr, close_arr, timeperiod=14)
            update['atr'] = round(float(atr_val[-1]), 4)
            natr_val = talib.NATR(high_arr, low_arr, close_arr, timeperiod=14)
            update['natr'] = round(float(natr_val[-1]), 4)
            trange_val = talib.TRANGE(high_arr, low_arr, close_arr)
            update['trange'] = round(float(trange_val[-1]), 4)
            
            ops.append(UpdateOne({'ts_code': ts_code, 'trade_date': td}, {'$set': update}))
            computed += 1
        except Exception:
            continue
    
    if ops:
        r = db.stock_daily_ak_full.bulk_write(ops)
        print(f'  talib因子: {r.modified_count} records ({computed} stocks computed)')
    
    return computed


def main():
    dates = [20260515, 20260519]
    
    for td in dates:
        missing, total = detect_missing(td)
        if not missing:
            print(f'{td}: 所有因子已完整')
            continue
        
        print(f'\n=== {td}: 缺失{len(missing)}个因子 ===')
        print(f'  缺失: {missing}')
        
        # Step 1: 策略因子
        strategy_missing = [f for f in missing if f in STRATEGY_FIELDS]
        if strategy_missing:
            print(f'  策略因子({len(strategy_missing)}): {strategy_missing}')
            compute_strategy_factors(td)
        
        # Step 2: 技术因子
        tech_missing = [f for f in missing if f in TECHNICAL_FIELDS]
        if tech_missing:
            print(f'  技术因子({len(tech_missing)}): {tech_missing}')
            compute_technical_factors(td)
        
        # 验证
        new_missing, _ = detect_missing(td)
        print(f'  补算后剩余缺失: {len(new_missing)} -> {new_missing}')


if __name__ == '__main__':
    main()
