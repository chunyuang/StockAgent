#!/usr/bin/env python3
"""重算有Bug的因子字段并更新MongoDB (同步版本)"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from pymongo import MongoClient, UpdateOne
from core.constants import C

def recompute_factors(start_date: int, end_date: int):
    client = MongoClient('localhost', 27017)
    db = client['stock_agent']
    coll = db['stock_daily_ak_full']
    
    dates = sorted(coll.distinct('trade_date', {'trade_date': {'$gte': start_date, '$lte': end_date}}))
    print(f"日期: {dates[0]}~{dates[-1]}, {len(dates)}天")
    
    total_updated = 0
    total_oa = 0
    total_ld = 0
    
    for date in dates:
        docs = list(coll.find({'trade_date': date}, {
            'ts_code': 1, 'open': 1, 'high': 1, 'low': 1, 'close': 1,
            'pre_close': 1, 'amount': 1, 'limit_down_yesterday': 1, '_id': 0
        }))
        if not docs:
            continue
        
        df = pd.DataFrame(docs)
        pre_close = df['pre_close'].fillna(df['close'])
        limit_down_price = pre_close * 0.9
        
        # open_above_limit_down
        ld_yesterday = df.get('limit_down_yesterday', pd.Series([0]*len(df)))
        open_above_ld = (df['open'] > limit_down_price) & (ld_yesterday == 1)
        intraday_qiao = (df['low'] <= limit_down_price * 1.005) & (df['close'] > limit_down_price * 1.005)
        open_above_ld = open_above_ld | intraday_qiao
        
        # limit_down_open_amount
        ld_open_amount = np.where(
            (df['low'] <= limit_down_price * 1.005) & (df['close'] > limit_down_price * 1.005),
            df['amount'].fillna(0), 0
        )
        
        # rise_after_limit_down
        rise_after_ld = np.where(
            ld_open_amount > 0,
            (df['close'] - limit_down_price) / limit_down_price.clip(lower=0.01) * 100,
            0
        )
        
        updates = []
        for i in range(len(df)):
            updates.append(UpdateOne(
                {'ts_code': df.iloc[i]['ts_code'], 'trade_date': date},
                {'$set': {
                    'open_above_limit_down': int(open_above_ld.iloc[i]),
                    'limit_down_open_amount': float(ld_open_amount[i]),
                    'rise_after_limit_down': float(rise_after_ld[i]),
                }}
            ))
        
        if updates:
            result = coll.bulk_write(updates)
            total_updated += result.modified_count
        
        oa_count = int(open_above_ld.sum())
        ld_count = int((ld_open_amount > 0).sum())
        total_oa += oa_count
        total_ld += ld_count
        
        if date == dates[-1] or len(dates) < 10:
            print(f"  {date}: 更新{len(updates)}条, open_above_limit_down={oa_count}, ld_open_amount>0={ld_count}")
    
    print(f"\n✅ 完成! 更新{total_updated}条")
    print(f"  open_above_limit_down=1: {total_oa}条(旧5条)")
    print(f"  limit_down_open_amount>0: {total_ld}条(旧0条)")
    client.close()

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', type=int, default=20260105)
    parser.add_argument('--end', type=int, default=20260508)
    args = parser.parse_args()
    recompute_factors(args.start, args.end)
