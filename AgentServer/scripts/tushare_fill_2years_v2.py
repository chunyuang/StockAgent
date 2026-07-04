#!/usr/bin/env python3
"""
补2年历史数据 (2024-05 ~ 2026-05) - 优化版
不扫描已有数据，直接对每个交易日upsert，跳过无返回的日期

步骤:
1. 补 daily_basic (turnover_rate/volume_ratio/pe_ttm/pb/circ_mv)
2. 补 stock_daily_ak_full (OHLCV/pct_chg/pre_close)
3. 同步 daily_basic → stock_daily_ak_full
"""
import tushare as ts
import pandas as pd
from pymongo import MongoClient, UpdateOne
import time
import sys

TOKEN = '2876ea85cb005fb5fa17c809a98174f2d5aae8b1f830110a5ead6211'
pro = ts.pro_api(TOKEN)
db = MongoClient('localhost', 27017)['stock_agent']

DELAY = 0.35


def get_trade_dates():
    df = pro.trade_cal(exchange='SSE', start_date='20240501', end_date='20260511', is_open=1)
    return sorted(df['cal_date'].tolist())


def fill_daily_basic(dates):
    """补daily_basic - 全量upsert"""
    print(f'=== 补 daily_basic ({len(dates)}天) ===')
    total_mod = 0
    total_ups = 0
    skipped = 0
    
    for i, td in enumerate(dates):
        td_int = int(td)
        
        # 快速检查：如果已有且turnover_rate>0就跳过
        with_tr = db.daily_basic.count_documents({'trade_date': td_int, 'turnover_rate': {'$gt': 0}})
        if with_tr >= 4000:
            skipped += 1
            continue
        
        retries = 0
        while retries < 3:
            try:
                df = pro.daily_basic(trade_date=td)
                break
            except Exception as e:
                retries += 1
                if 'limit' in str(e).lower() or '频率' in str(e) or '每分钟' in str(e):
                    print(f'  {td}: 限频, 等65s (重试{retries})')
                    time.sleep(65)
                else:
                    print(f'  {td}: 错误 {e}')
                    time.sleep(5)
        else:
            print(f'  {td}: 重试用尽')
            continue
        
        if df is None or len(df) == 0:
            continue
        
        ops = []
        for _, row in df.iterrows():
            update = {}
            for f in ['turnover_rate','turnover_rate_f','volume_ratio','pe_ttm','pe','pb','ps','ps_ttm','close']:
                v = row.get(f)
                if pd.notna(v):
                    update[f] = float(v)
            # turnover_rate: Tushare返回小数→×100→百分数
            if 'turnover_rate' in update and update['turnover_rate'] > 0 and update['turnover_rate'] < 1:
                update['turnover_rate'] = update['turnover_rate'] * 100
            if 'turnover_rate_f' in update and update['turnover_rate_f'] > 0 and update['turnover_rate_f'] < 1:
                update['turnover_rate_f'] = update['turnover_rate_f'] * 100
            # circ_mv/total_mv: Tushare返回万元→daily_basic标准亿元→÷10000
            for k in ['circ_mv', 'total_mv']:
                v = row.get(k)
                if pd.notna(v):
                    update[k] = float(v) / 10000
            # close: 元→直接存
            v = row.get('close')
            if pd.notna(v):
                update['close'] = float(v)
            if update:
                ops.append(UpdateOne(
                    {'ts_code': row['ts_code'], 'trade_date': td_int},
                    {'$set': update},
                    upsert=True
                ))
        
        if ops:
            result = db.daily_basic.bulk_write(ops, ordered=False)
            total_mod += result.modified_count
            total_ups += result.upserted_count
        
        if (i+1) % 25 == 0 or i == len(dates)-1:
            print(f'  [{i+1}/{len(dates)}] {td}: {len(df)}只 | 累计更新{total_mod} 新增{total_ups} 跳过{skipped}')
        
        time.sleep(DELAY)
    
    print(f'daily_basic完成! 更新{total_mod} 新增{total_ups} 跳过{skipped}')
    return total_mod, total_ups


def fill_stock_daily(dates):
    """补stock_daily_ak_full - 全量upsert"""
    print(f'\n=== 补 stock_daily_ak_full ({len(dates)}天) ===')
    total_mod = 0
    total_ups = 0
    skipped = 0
    
    for i, td in enumerate(dates):
        td_int = int(td)
        
        # 快速检查
        count = db.stock_daily_ak_full.count_documents({'trade_date': td_int})
        if count >= 5000:
            skipped += 1
            continue
        
        retries = 0
        while retries < 3:
            try:
                df = pro.daily(trade_date=td)
                break
            except Exception as e:
                retries += 1
                if 'limit' in str(e).lower() or '频率' in str(e) or '每分钟' in str(e):
                    print(f'  {td}: 限频, 等65s (重试{retries})')
                    time.sleep(65)
                else:
                    print(f'  {td}: 错误 {e}')
                    time.sleep(5)
        else:
            print(f'  {td}: 重试用尽')
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
            # vol: Tushare daily返回手, MongoDB标准也是手, 直接存
            if pd.notna(row.get('vol')):
                update['vol'] = float(row['vol'])
            # amount: Tushare daily返回千元, MongoDB标准是百元, ×10
            if pd.notna(row.get('amount')):
                update['amount'] = float(row['amount']) * 10
            
            if update:
                ops.append(UpdateOne(
                    {'ts_code': row['ts_code'], 'trade_date': td_int},
                    {'$set': update},
                    upsert=True
                ))
        
        if ops:
            result = db.stock_daily_ak_full.bulk_write(ops, ordered=False)
            total_mod += result.modified_count
            total_ups += result.upserted_count
        
        if (i+1) % 25 == 0 or i == len(dates)-1:
            print(f'  [{i+1}/{len(dates)}] {td}: {len(df)}只 | 累计更新{total_mod} 新增{total_ups} 跳过{skipped}')
        
        time.sleep(DELAY)
    
    print(f'stock_daily完成! 更新{total_mod} 新增{total_ups} 跳过{skipped}')
    return total_mod, total_ups


def sync_basic_to_daily():
    """同步daily_basic因子到stock_daily_ak_full"""
    print(f'\n=== 同步 daily_basic → stock_daily_ak_full ===')
    
    # 只同步2024-05之后的新数据
    dates = sorted(db.daily_basic.distinct('trade_date', {'trade_date': {'$gte': 20240501}}))
    # 过滤掉已同步的(通过抽样判断)
    total_synced = 0
    
    for i, td in enumerate(dates):
        # 检查是否已同步
        with_tr = db.stock_daily_ak_full.count_documents({'trade_date': td, 'turnover_rate': {'$gt': 0}})
        if with_tr >= 4000:
            continue
        
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
            result = db.stock_daily_ak_full.bulk_write(ops, ordered=False)
            total_synced += result.modified_count
        
        if (i+1) % 50 == 0 or i == len(dates)-1:
            print(f'  [{i+1}/{len(dates)}] 累计同步{total_synced}')
    
    print(f'同步完成! 共{total_synced}条')


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'all'
    
    print('获取交易日历...')
    dates = get_trade_dates()
    print(f'2年交易日: {len(dates)}天 ({dates[0]}~{dates[-1]})')
    
    start_time = time.time()
    
    if mode in ('all', 'basic'):
        fill_daily_basic(dates)
    
    if mode in ('all', 'daily'):
        fill_stock_daily(dates)
    
    if mode in ('all', 'sync'):
        sync_basic_to_daily()
    
    elapsed = time.time() - start_time
    print(f'\n总耗时: {elapsed/60:.1f}分钟')
    
    # 最终统计
    total_daily = db.stock_daily_ak_full.count_documents({})
    total_basic = db.daily_basic.count_documents({})
    total_stocks = len(db.stock_daily_ak_full.distinct('ts_code'))
    total_dates = len(db.stock_daily_ak_full.distinct('trade_date'))
    print(f'\nstock_daily_ak_full: {total_daily:,}条 ({total_stocks}只 × {total_dates}天)')
    print(f'daily_basic: {total_basic:,}条')


if __name__ == '__main__':
    main()
