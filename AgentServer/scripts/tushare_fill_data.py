#!/usr/bin/env python3
"""
用Tushare补全MongoDB数据
1. daily_basic: 补turnover_rate/volume_ratio/pe_ttm/pb/circ_mv等
2. stock_daily_ak_full: 补日线OHLCV(pct_chg/pre_close/change等)
3. 交易日历补全

5000积分，每天约消耗:
  - daily_basic: ~2分/天 (5000积分可拉2500天)
  - daily: ~2分/天
"""

import tushare as ts
import pandas as pd
from pymongo import MongoClient
import time
import sys

TOKEN = '2876ea85cb005fb5fa17c809a98174f2d5aae8b1f830110a5ead6211'
pro = ts.pro_api(TOKEN)
db = MongoClient('localhost', 27017)['stock_agent']

BATCH_DELAY = 0.3  # 请求间隔秒数，避免限频


def get_trade_dates(start_date, end_date):
    """从Tushare获取交易日历"""
    df = pro.trade_cal(exchange='SSE', start_date=start_date, end_date=end_date, is_open=1)
    return sorted(df['cal_date'].tolist())


def fill_daily_basic(trade_dates, force=False):
    """补全daily_basic - 重点补turnover_rate/volume_ratio"""
    updated = 0
    inserted = 0
    skipped = 0
    
    for td in trade_dates:
        td_int = int(td)
        
        if not force:
            # 检查是否已有完整数据(turnover_rate非空)
            existing_with_tr = db.daily_basic.count_documents({
                'trade_date': td_int,
                'turnover_rate': {'$gt': 0}
            })
            if existing_with_tr >= 4000:
                skipped += 1
                continue
        
        try:
            df = pro.daily_basic(trade_date=td)
            if df is None or len(df) == 0:
                print(f'  {td}: 无数据(非交易日?)')
                continue
            
            time.sleep(BATCH_DELAY)
            
            for _, row in df.iterrows():
                ts_code = row['ts_code']
                update_fields = {}
                
                # 关键字段映射
                field_map = {
                    'turnover_rate': 'turnover_rate',
                    'turnover_rate_f': 'turnover_rate_f',
                    'volume_ratio': 'volume_ratio',
                    'pe_ttm': 'pe_ttm',
                    'pe': 'pe',
                    'pb': 'pb',
                    'ps': 'ps',
                    'ps_ttm': 'ps_ttm',
                    'total_mv': 'total_mv',
                    'circ_mv': 'circ_mv',
                    'close': 'close',
                }
                
                for tushare_field, mongo_field in field_map.items():
                    val = row.get(tushare_field)
                    if pd.notna(val):
                        update_fields[mongo_field] = float(val)
                
                if not update_fields:
                    continue
                
                result = db.daily_basic.update_one(
                    {'ts_code': ts_code, 'trade_date': td_int},
                    {'$set': update_fields}
                )
                if result.matched_count > 0:
                    updated += 1
                else:
                    # 不存在则插入
                    update_fields['ts_code'] = ts_code
                    update_fields['trade_date'] = td_int
                    db.daily_basic.insert_one(update_fields)
                    inserted += 1
            
            print(f'  {td}: {len(df)}只处理完成 (upsert)')
            
        except Exception as e:
            print(f'  {td}: 错误 - {e}')
            if '频率' in str(e) or 'limit' in str(e).lower():
                print('  触发限频，等待60秒...')
                time.sleep(60)
            continue
    
    print(f'\ndaily_basic汇总: 更新{updated}, 新增{inserted}, 跳过{skipped}')
    return updated, inserted, skipped


def fill_stock_daily(trade_dates, force=False):
    """补全stock_daily_ak_full - 补pct_chg/pre_close/change等"""
    updated = 0
    inserted = 0
    skipped = 0
    
    for td in trade_dates:
        td_int = int(td)
        
        if not force:
            existing = db.stock_daily_ak_full.count_documents({
                'trade_date': td_int,
                'pct_chg': {'$exists': True, '$ne': None}
            })
            if existing >= 4000:
                skipped += 1
                continue
        
        try:
            df = pro.daily(trade_date=td)
            if df is None or len(df) == 0:
                print(f'  {td}: 无数据')
                continue
            
            time.sleep(BATCH_DELAY)
            
            for _, row in df.iterrows():
                ts_code = row['ts_code']
                update_fields = {}
                
                field_map = {
                    'open': 'open',
                    'high': 'high',
                    'low': 'low',
                    'close': 'close',
                    'pre_close': 'pre_close',
                    'change': 'change',
                    'pct_chg': 'pct_chg',
                    'vol': 'vol',
                    'amount': 'amount',
                }
                
                for tushare_field, mongo_field in field_map.items():
                    val = row.get(tushare_field)
                    if pd.notna(val):
                        # Tushare vol单位是手(100股), amount单位是千元
                        if mongo_field == 'vol':
                            update_fields[mongo_field] = float(val) * 100  # 手→股
                        elif mongo_field == 'amount':
                            update_fields[mongo_field] = float(val) * 1000  # 千元→元
                        else:
                            update_fields[mongo_field] = float(val)
                
                if not update_fields:
                    continue
                
                result = db.stock_daily_ak_full.update_one(
                    {'ts_code': ts_code, 'trade_date': td_int},
                    {'$set': update_fields}
                )
                if result.matched_count > 0:
                    updated += 1
                else:
                    update_fields['ts_code'] = ts_code
                    update_fields['trade_date'] = td_int
                    # 初始化涨跌停字段
                    for f in ['is_limit_up','is_limit_down','first_limit_up','first_limit_down',
                               'limit_up_count','limit_down_count','limit_up_yesterday','limit_down_yesterday']:
                        update_fields[f] = 0
                    db.stock_daily_ak_full.insert_one(update_fields)
                    inserted += 1
            
            print(f'  {td}: {len(df)}只处理完成')
            
        except Exception as e:
            print(f'  {td}: 错误 - {e}')
            if '频率' in str(e) or 'limit' in str(e).lower():
                print('  触发限频，等待60秒...')
                time.sleep(60)
            continue
    
    print(f'\nstock_daily汇总: 更新{updated}, 新增{inserted}, 跳过{skipped}')
    return updated, inserted, skipped


def fill_trade_calendar():
    """补全交易日历"""
    df = pro.trade_cal(exchange='SSE', start_date='20250101', end_date='20261231')
    count = 0
    for _, row in df.iterrows():
        result = db.trade_cal.update_one(
            {'exchange': row['exchange'], 'cal_date': int(row['cal_date'])},
            {'$set': {
                'exchange': row['exchange'],
                'cal_date': int(row['cal_date']),
                'is_open': int(row['is_open']),
                'pretrade_date': int(row['pretrade_date']) if pd.notna(row.get('pretrade_date')) else None
            }},
            upsert=True
        )
        if result.upserted_id:
            count += 1
    print(f'交易日历: 新增{count}条')


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'basic'
    force = '--force' in sys.argv
    
    if mode == 'cal':
        print('=== 补全交易日历 ===')
        fill_trade_calendar()
        return
    
    # 获取交易日列表
    # 优先从已有的stock_daily找日期
    if mode == 'basic':
        print('=== 补全 daily_basic (turnover_rate/volume_ratio/PE/PB) ===')
        # 找有数据但缺turnover_rate的日期
        # 先看哪些日期有数据但turnover_rate=0
        pipeline = [
            {'$match': {'trade_date': {'$gte': 20260101}}},
            {'$group': {
                '_id': '$trade_date',
                'total': {'$sum': 1},
                'with_tr': {'$sum': {'$cond': [{'$gt': ['$turnover_rate', 0]}, 1, 0]}}
            }},
            {'$match': {'$or': [{'with_tr': 0}, {'total': {'$lt': 4000}}]}},
            {'$sort': {'_id': 1}}
        ]
        gaps = list(db.daily_basic.aggregate(pipeline))
        
        if not gaps and not force:
            print('daily_basic似乎已完整，用 --force 强制刷新')
            return
        
        trade_dates = [str(g['_id']) for g in gaps]
        print(f'需要补全 {len(trade_dates)} 天')
        if trade_dates:
            print(f'  范围: {trade_dates[0]} ~ {trade_dates[-1]}')
        
        fill_daily_basic(trade_dates, force=force)
        
    elif mode == 'daily':
        print('=== 补全 stock_daily_ak_full (OHLCV/pct_chg) ===')
        # 找缺数据的日期
        pipeline = [
            {'$match': {'trade_date': {'$gte': 20260101}}},
            {'$group': {
                '_id': '$trade_date',
                'total': {'$sum': 1},
                'with_pct': {'$sum': {'$cond': [{'$and': [
                    {'$ne': ['$pct_chg', None]},
                    {'$gt': ['$pct_chg', -100]}
                ]}, 1, 0]}}
            }},
            {'$match': {'total': {'$lt': 4000}}},
            {'$sort': {'_id': 1}}
        ]
        gaps = list(db.stock_daily_ak_full.aggregate(pipeline))
        trade_dates = [str(g['_id']) for g in gaps]
        
        print(f'需要补全 {len(trade_dates)} 天')
        fill_stock_daily(trade_dates, force=force)
        
    elif mode == 'all':
        print('=== 全面补全 ===')
        # 1. 交易日历
        fill_trade_calendar()
        
        # 2. 获取完整交易日列表
        trade_dates = get_trade_dates('20260101', '20260511')
        print(f'\n交易日共 {len(trade_dates)} 天')
        
        # 3. 补daily_basic
        print('\n--- 补 daily_basic ---')
        fill_daily_basic(trade_dates, force=force)
        
        # 4. 补stock_daily
        print('\n--- 补 stock_daily_ak_full ---')
        fill_stock_daily(trade_dates, force=force)
    
    elif mode == 'history':
        # 补更早的历史数据(2025年)
        start = sys.argv[2] if len(sys.argv) > 2 else '20251001'
        end = sys.argv[3] if len(sys.argv) > 3 else '20251231'
        print(f'=== 补历史数据 {start}~{end} ===')
        trade_dates = get_trade_dates(start, end)
        print(f'交易日共 {len(trade_dates)} 天')
        fill_daily_basic(trade_dates, force=True)
        fill_stock_daily(trade_dates, force=True)


if __name__ == '__main__':
    main()
