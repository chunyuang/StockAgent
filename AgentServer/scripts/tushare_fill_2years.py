#!/usr/bin/env python3
"""
补2年历史数据 (2024-05 ~ 2026-05)
- daily_basic: turnover_rate/volume_ratio/pe_ttm/pb/circ_mv
- stock_daily_ak_full: OHLCV/pct_chg/pre_close
- 然后同步 daily_basic → stock_daily_ak_full

Tushare token: 2876ea85cb005fb5fa17c809a98174f2d5aae8b1f830110a5ead6211
积分: ~4758, 预估消耗 ~1952
"""
import tushare as ts
import pandas as pd
from pymongo import MongoClient, UpdateOne
import time
import sys
import traceback

TOKEN = '2876ea85cb005fb5fa17c809a98174f2d5aae8b1f830110a5ead6211'
pro = ts.pro_api(TOKEN)
db = MongoClient('localhost', 27017)['stock_agent']

DELAY = 0.35  # 请求间隔
MAX_RETRIES = 3


def get_trade_dates():
    """获取2年交易日历"""
    df = pro.trade_cal(exchange='SSE', start_date='20240501', end_date='20260511', is_open=1)
    return sorted(df['cal_date'].tolist())


def get_existing_dates(collection):
    """快速获取已有数据的日期集合"""
    dates = set()
    for d in collection.distinct('trade_date', {'trade_date': {'$gte': 20240501}}):
        dates.add(d)
    return dates


def fill_daily_basic(dates_to_fill):
    """补daily_basic - turnover_rate/volume_ratio/pe_ttm/pb/circ_mv"""
    total_updated = 0
    total_inserted = 0
    errors = 0
    
    for i, td in enumerate(dates_to_fill):
        td_int = int(td)
        retries = 0
        while retries < MAX_RETRIES:
            try:
                df = pro.daily_basic(trade_date=td)
                break
            except Exception as e:
                retries += 1
                if 'limit' in str(e).lower() or '频率' in str(e) or '每分钟' in str(e):
                    print(f'  {td}: 限频, 等待65秒... (重试{retries}/{MAX_RETRIES})')
                    time.sleep(65)
                else:
                    print(f'  {td}: API错误 {e} (重试{retries}/{MAX_RETRIES})')
                    time.sleep(5)
        else:
            print(f'  {td}: 重试用尽, 跳过')
            errors += 1
            continue
        
        if df is None or len(df) == 0:
            continue
        
        ops = []
        fields = ['turnover_rate','turnover_rate_f','volume_ratio','pe_ttm','pe','pb','ps','ps_ttm','total_mv','circ_mv','close']
        for _, row in df.iterrows():
            update = {}
            for f in fields:
                v = row.get(f)
                if pd.notna(v):
                    update[f] = float(v)
            if update:
                ops.append(UpdateOne(
                    {'ts_code': row['ts_code'], 'trade_date': td_int},
                    {'$set': update},
                    upsert=True
                ))
        
        if ops:
            try:
                result = db.daily_basic.bulk_write(ops, ordered=False)
                total_updated += result.modified_count
                total_inserted += result.upserted_count
            except Exception as e:
                print(f'  {td}: 写入错误 {e}')
                errors += 1
        
        if (i+1) % 50 == 0 or i == len(dates_to_fill)-1:
            print(f'  [{i+1}/{len(dates_to_fill)}] {td}: {len(df)}只 (累计更新{total_updated} 新增{total_inserted})')
        
        time.sleep(DELAY)
    
    return total_updated, total_inserted, errors


def fill_stock_daily(dates_to_fill):
    """补stock_daily_ak_full - OHLCV/pct_chg/pre_close"""
    total_updated = 0
    total_inserted = 0
    errors = 0
    
    for i, td in enumerate(dates_to_fill):
        td_int = int(td)
        retries = 0
        while retries < MAX_RETRIES:
            try:
                df = pro.daily(trade_date=td)
                break
            except Exception as e:
                retries += 1
                if 'limit' in str(e).lower() or '频率' in str(e) or '每分钟' in str(e):
                    print(f'  {td}: 限频, 等待65秒... (重试{retries}/{MAX_RETRIES})')
                    time.sleep(65)
                else:
                    print(f'  {td}: API错误 {e} (重试{retries}/{MAX_RETRIES})')
                    time.sleep(5)
        else:
            print(f'  {td}: 重试用尽, 跳过')
            errors += 1
            continue
        
        if df is None or len(df) == 0:
            continue
        
        ops = []
        for _, row in df.iterrows():
            update = {}
            for f in ['open','high','low','close','pre_close','change','pct_chg']:
                v = row.get(f)
                if pd.notna(v):
                    update[f] = float(v)
            if pd.notna(row.get('vol')):
                update['vol'] = float(row['vol']) * 100  # 手→股
            if pd.notna(row.get('amount')):
                update['amount'] = float(row['amount']) * 1000  # 千元→元
            
            if update:
                ops.append(UpdateOne(
                    {'ts_code': row['ts_code'], 'trade_date': td_int},
                    {'$set': update},
                    upsert=True
                ))
        
        if ops:
            try:
                result = db.stock_daily_ak_full.bulk_write(ops, ordered=False)
                total_updated += result.modified_count
                total_inserted += result.upserted_count
            except Exception as e:
                print(f'  {td}: 写入错误 {e}')
                errors += 1
        
        if (i+1) % 50 == 0 or i == len(dates_to_fill)-1:
            print(f'  [{i+1}/{len(dates_to_fill)}] {td}: {len(df)}只 (累计更新{total_updated} 新增{total_inserted})')
        
        time.sleep(DELAY)
    
    return total_updated, total_inserted, errors


def sync_basic_to_daily():
    """同步daily_basic的关键字段到stock_daily_ak_full"""
    print('\n=== 同步 daily_basic → stock_daily_ak_full ===')
    dates = sorted(db.daily_basic.distinct('trade_date', {'trade_date': {'$gte': 20240501}}))
    print(f'需要同步 {len(dates)} 天')
    
    total_synced = 0
    for i, td in enumerate(dates):
        basics = list(db.daily_basic.find(
            {'trade_date': td, 'turnover_rate': {'$gt': 0}},
            {'ts_code': 1, 'turnover_rate': 1, 'volume_ratio': 1, 'circ_mv': 1, 'pe_ttm': 1, 'pb': 1, '_id': 0}
        ))
        
        if not basics:
            continue
        
        ops = []
        for b in basics:
            update = {}
            for f in ['turnover_rate','volume_ratio','circ_mv','pe_ttm','pb']:
                if f in b and b[f] is not None and b[f] > 0:
                    update[f] = b[f]
            if update:
                ops.append(UpdateOne(
                    {'ts_code': b['ts_code'], 'trade_date': td},
                    {'$set': update}
                ))
        
        if ops:
            try:
                result = db.stock_daily_ak_full.bulk_write(ops, ordered=False)
                total_synced += result.modified_count
            except Exception as e:
                print(f'  {td}: 同步错误 {e}')
        
        if (i+1) % 50 == 0 or i == len(dates)-1:
            print(f'  [{i+1}/{len(dates)}] {td}: 累计同步{total_synced}')
    
    print(f'同步完成! 共{total_synced}条')


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'all'
    
    # 获取交易日历
    print('获取交易日历...')
    all_trade_dates = get_trade_dates()
    print(f'2年交易日: {len(all_trade_dates)}天')
    
    if mode in ('all', 'basic'):
        print('\n=== 补 daily_basic ===')
        # 找缺数据的日期
        existing = get_existing_dates(db.daily_basic)
        # 对于已存在的日期，检查turnover_rate是否为0
        dates_with_tr = set()
        for d in db.daily_basic.distinct('trade_date', {
            'trade_date': {'$gte': 20240501},
            'turnover_rate': {'$gt': 0}
        }):
            dates_with_tr.add(d)
        
        missing_dates = []
        for td in all_trade_dates:
            td_int = int(td)
            if td_int not in existing:
                missing_dates.append(td)
            elif td_int not in dates_with_tr:
                missing_dates.append(td)
        
        print(f'缺daily_basic/turnover_rate: {len(missing_dates)}天')
        if missing_dates:
            fill_daily_basic(missing_dates)
    
    if mode in ('all', 'daily'):
        print('\n=== 补 stock_daily_ak_full ===')
        # 找缺数据的日期(不足4000只)
        existing_dates = {}
        for d in db.stock_daily_ak_full.distinct('trade_date', {'trade_date': {'$gte': 20240501}}):
            existing_dates[d] = db.stock_daily_ak_full.count_documents({'trade_date': d})
        
        missing_dates = []
        for td in all_trade_dates:
            td_int = int(td)
            if td_int not in existing_dates:
                missing_dates.append(td)
            elif existing_dates[td_int] < 4000:
                missing_dates.append(td)
        
        print(f'缺stock_daily: {len(missing_dates)}天')
        if missing_dates:
            fill_stock_daily(missing_dates)
    
    if mode in ('all', 'sync'):
        sync_basic_to_daily()
    
    # 最终统计
    print('\n' + '='*60)
    print('  最终数据统计')
    print('='*60)
    total_daily = db.stock_daily_ak_full.count_documents({})
    total_basic = db.daily_basic.count_documents({})
    total_stocks = len(db.stock_daily_ak_full.distinct('ts_code'))
    total_dates = len(db.stock_daily_ak_full.distinct('trade_date'))
    print(f'  stock_daily_ak_full: {total_daily:,}条 ({total_stocks}只 × {total_dates}天)')
    print(f'  daily_basic: {total_basic:,}条')


if __name__ == '__main__':
    main()
