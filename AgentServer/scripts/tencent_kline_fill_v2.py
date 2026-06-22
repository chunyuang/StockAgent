#!/usr/bin/env python3
"""
优化版：用腾讯K线接口补全指定日期的stock_daily_ak_full数据
- 一次预加载所有股票的pre_close
- 分批写入
"""
import requests
import time
from pymongo import MongoClient, UpdateOne
from datetime import datetime

db = MongoClient('localhost', 27017)['stock_agent']

def ts_to_tencent(ts_code):
    code, market = ts_code.split('.')
    return f'{"sz" if market == "SZ" else "sh"}{code}'

def get_kline(tencent_code, start, end):
    url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={tencent_code},day,{start},{end},10,qfq'
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        if data.get('data') and data['data'].get(tencent_code):
            return data['data'][tencent_code].get('qfqday') or data['data'][tencent_code].get('day') or []
    except:
        pass
    return []

def fill_dates(target_dates):
    codes = list(set(
        db.stock_daily_ak_full.distinct('ts_code') + 
        db.stock_basic.distinct('ts_code')
    ))
    print(f'总股票: {len(codes)}, 目标日期: {target_dates}')
    
    # 预加载所有股票的pre_close (最新收盘价)
    print('预加载pre_close...')
    pre_close_map = {}
    min_td = min(target_dates)
    for doc in db.stock_daily_ak_full.find(
        {'trade_date': {'$lt': min_td}},
        {'ts_code': 1, 'trade_date': 1, 'close': 1}
    ).sort('trade_date', -1):
        tc = doc['ts_code']
        if tc not in pre_close_map:
            pre_close_map[tc] = (doc['trade_date'], doc['close'])
    print(f'  预加载 {len(pre_close_map)} 只股票的pre_close')
    
    start_str = str(min(target_dates))
    start_fmt = f'{start_str[:4]}-{start_str[4:6]}-{start_str[6:8]}'
    end_str = str(max(target_dates))
    end_fmt = f'{end_str[:4]}-{end_str[4:6]}-{end_str[6:8]}'
    
    daily_ops = {d: [] for d in target_dates}
    basic_ops = {d: [] for d in target_dates}
    success = 0
    fail = 0
    
    for i, ts_code in enumerate(codes):
        tc = ts_to_tencent(ts_code)
        klines = get_kline(tc, start_fmt, end_fmt)
        
        if not klines:
            fail += 1
            time.sleep(0.08)
            continue
        
        success += 1
        
        for k in klines:
            if len(k) < 6:
                continue
            trade_date = int(k[0].replace('-', ''))
            if trade_date not in target_dates:
                continue
            
            open_p = float(k[1]) if k[1] else None
            close_p = float(k[2]) if k[2] else None
            high_p = float(k[3]) if k[3] else None
            low_p = float(k[4]) if k[4] else None
            vol = float(k[5]) if k[5] else None
            
            if not close_p:
                continue
            
            pre_close = pre_close_map.get(ts_code, (None, None))[1]
            pct_chg = round((close_p - pre_close) / pre_close * 100, 2) if pre_close and pre_close > 0 else None
            
            daily_ops[trade_date].append(UpdateOne(
                {'ts_code': ts_code, 'trade_date': trade_date},
                {'$set': {
                    'open': open_p, 'high': high_p, 'low': low_p, 'close': close_p,
                    'vol': vol, 'pct_chg': pct_chg, 'pre_close': pre_close,
                    'change': round(close_p - pre_close, 2) if pre_close else None,
                    'updated_at': datetime.now(),
                }},
                upsert=True
            ))
            basic_ops[trade_date].append(UpdateOne(
                {'ts_code': ts_code, 'trade_date': trade_date},
                {'$set': {
                    'close': close_p, 'pct_chg': pct_chg,
                    'updated_at': datetime.now(),
                }},
                upsert=True
            ))
        
        # 每500只写一批
        for td in target_dates:
            if len(daily_ops[td]) >= 500:
                r = db.stock_daily_ak_full.bulk_write(daily_ops[td], ordered=False)
                r2 = db.daily_basic.bulk_write(basic_ops[td], ordered=False)
                c = db.stock_daily_ak_full.count_documents({'trade_date': td})
                print(f'  批次写入 {td}: +{r.upserted_count} 累计={c}')
                daily_ops[td] = []
                basic_ops[td] = []
        
        if (i + 1) % 1000 == 0:
            print(f'  进度: {i+1}/{len(codes)} ok:{success} fail:{fail}')
        
        time.sleep(0.08)
    
    # 写入剩余
    for td in target_dates:
        if daily_ops[td]:
            r = db.stock_daily_ak_full.bulk_write(daily_ops[td], ordered=False)
            r2 = db.daily_basic.bulk_write(basic_ops[td], ordered=False)
            c = db.stock_daily_ak_full.count_documents({'trade_date': td})
            print(f'  最终写入 {td}: +{r.upserted_count} 累计={c}')
    
    # 验证
    print('\n验证:')
    for td in target_dates:
        c1 = db.stock_daily_ak_full.count_documents({'trade_date': td})
        c2 = db.daily_basic.count_documents({'trade_date': td})
        print(f'  {td}: stock_daily={c1}, daily_basic={c2}')

if __name__ == '__main__':
    import sys
    dates = [int(d) for d in sys.argv[1:]] if len(sys.argv) > 1 else [20260616, 20260617]
    fill_dates(dates)
