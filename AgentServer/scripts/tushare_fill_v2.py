#!/usr/bin/env python3
"""
高效版：用Tushare补全MongoDB数据
- daily_basic: 补turnover_rate/volume_ratio/pe_ttm/pb/circ_mv
- stock_daily_ak_full: 补pct_chg/pre_close + 缺失股票日线
"""
import tushare as ts
import pandas as pd
from pymongo import MongoClient, UpdateOne
import time
import sys

TOKEN = '2876ea85cb005fb5fa17c809a98174f2d5aae8b1f830110a5ead6211'
pro = ts.pro_api(TOKEN)
db = MongoClient('localhost', 27017)['stock_agent']

def get_missing_dates_basic():
    """快速找缺turnover_rate的日期 - 用distinct而不是聚合"""
    all_dates = sorted(db.daily_basic.distinct('trade_date', {'trade_date': {'$gte': 20260101}}))
    missing = []
    for td in all_dates:
        with_tr = db.daily_basic.count_documents({'trade_date': td, 'turnover_rate': {'$gt': 0}})
        total = db.daily_basic.count_documents({'trade_date': td})
        if with_tr < total * 0.5:  # 少于50%有换手率
            missing.append(td)
    return missing

def fill_basic_bulk(td_int):
    """用bulk_write批量更新一天daily_basic"""
    td_str = str(td_int)
    try:
        df = pro.daily_basic(trade_date=td_str)
    except Exception as e:
        print(f'  {td_str}: API错误 {e}')
        if 'limit' in str(e).lower() or '频率' in str(e) or '每分钟' in str(e):
            time.sleep(65)
        return 0, 0
    
    if df is None or len(df) == 0:
        return 0, 0
    
    ops = []
    fields = ['turnover_rate','turnover_rate_f','volume_ratio','pe_ttm','pe','pb','ps','ps_ttm','total_mv','circ_mv','close']
    for _, row in df.iterrows():
        update = {}
        for f in fields:
            v = row.get(f)
            if pd.notna(v):
                update[f] = float(v)
        # Tushare circ_mv/total_mv单位是万元, daily_basic集合标准是亿元, ÷10000
        for k in ['circ_mv', 'total_mv']:
            if k in update and update[k] > 0:
                update[k] = update[k] / 10000
                # 验证: 亿元单位下, circ_mv不应>10万亿(100000亿)
                if update[k] > 100000:
                    print(f'  ⚠️ {row["ts_code"]} {k}={update[k]:.0f}亿 >10万亿! 跳过')
                    del update[k]
        # 跳过close=None/0的记录
        if 'close' not in update or update.get('close', 0) <= 0:
            continue
        if update:
            ops.append(UpdateOne(
                {'ts_code': row['ts_code'], 'trade_date': td_int},
                {'$set': update}
            ))
    
    if ops:
        result = db.daily_basic.bulk_write(ops, ordered=False)
        return result.modified_count, result.upserted_count
    return 0, 0

def get_missing_dates_daily():
    """找stock_daily数据不足的日期"""
    all_dates = sorted(db.stock_daily_ak_full.distinct('trade_date', {'trade_date': {'$gte': 20260101}}))
    missing = []
    for td in all_dates:
        count = db.stock_daily_ak_full.count_documents({'trade_date': td})
        if count < 5000:
            missing.append(td)
    return missing

def fill_daily_bulk(td_int):
    """用bulk_write批量更新一天stock_daily"""
    td_str = str(td_int)
    try:
        df = pro.daily(trade_date=td_str)
    except Exception as e:
        print(f'  {td_str}: API错误 {e}')
        if 'limit' in str(e).lower() or '频率' in str(e) or '每分钟' in str(e):
            time.sleep(65)
        return 0, 0
    
    if df is None or len(df) == 0:
        return 0, 0
    
    ops = []
    for _, row in df.iterrows():
        update = {}
        for f in ['open','high','low','close','pre_close','change','pct_chg']:
            v = row.get(f)
            if pd.notna(v):
                update[f] = float(v)
        if pd.notna(row.get('vol')):
            update['vol'] = float(row['vol'])  # Tushare vol=手, MongoDB标准=手, 不需转换
        if pd.notna(row.get('amount')):
            update['amount'] = float(row['amount']) * 10  # 千元→百元(MongoDB标准)
        
        # 跳过close=None/0的记录(停牌/退市)
        if 'close' not in update or update.get('close', 0) <= 0:
            continue
        
        if update:
            ops.append(UpdateOne(
                {'ts_code': row['ts_code'], 'trade_date': td_int},
                {'$set': update},
                upsert=True  # 不存在就插入
            ))
    
    if ops:
        result = db.stock_daily_ak_full.bulk_write(ops, ordered=False)
        return result.modified_count, result.upserted_count
    return 0, 0

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'basic'
    
    if mode == 'basic':
        print('=== 补 daily_basic (turnover_rate/volume_ratio) ===')
        dates = get_missing_dates_basic()
        print(f'缺turnover_rate的天数: {len(dates)}')
        
        total_mod = 0
        total_ups = 0
        for i, td in enumerate(dates):
            mod, ups = fill_basic_bulk(td)
            total_mod += mod
            total_ups += ups
            print(f'  [{i+1}/{len(dates)}] {td}: 更新{mod} 新增{ups}')
            time.sleep(0.4)
        
        print(f'\ndaily_basic完成! 更新{total_mod}, 新增{total_ups}')
        
    elif mode == 'daily':
        print('=== 补 stock_daily_ak_full ===')
        dates = get_missing_dates_daily()
        print(f'数据不足5000只的天数: {len(dates)}')
        
        total_mod = 0
        total_ups = 0
        for i, td in enumerate(dates):
            mod, ups = fill_daily_bulk(td)
            total_mod += mod
            total_ups += ups
            print(f'  [{i+1}/{len(dates)}] {td}: 更新{mod} 新增{ups}')
            time.sleep(0.4)
        
        print(f'\nstock_daily完成! 更新{total_mod}, 新增{total_ups}')
    
    elif mode == 'both':
        print('=== 全面补全 ===')
        # daily_basic
        print('\n--- daily_basic ---')
        dates = get_missing_dates_basic()
        print(f'缺turnover_rate: {len(dates)}天')
        for i, td in enumerate(dates):
            mod, ups = fill_basic_bulk(td)
            print(f'  [{i+1}/{len(dates)}] {td}: 更新{mod} 新增{ups}')
            time.sleep(0.4)
        
        # stock_daily
        print('\n--- stock_daily_ak_full ---')
        dates = get_missing_dates_daily()
        print(f'数据不足: {len(dates)}天')
        for i, td in enumerate(dates):
            mod, ups = fill_daily_bulk(td)
            print(f'  [{i+1}/{len(dates)}] {td}: 更新{mod} 新增{ups}')
            time.sleep(0.4)

if __name__ == '__main__':
    main()
