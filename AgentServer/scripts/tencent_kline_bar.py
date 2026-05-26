#!/usr/bin/env python3
"""
腾讯K线API → stock_daily_ak_full 补历史日线数据

使用腾讯 ifzq.gtimg.cn K线接口获取历史日线。
适用于东方财富push2被封时作为备用数据源。

字段: 日期, 开盘, 收盘, 最高, 最低, 成交量(股)
"""
import requests
import json
import time
import sys
from datetime import datetime, date, timedelta
from pymongo import MongoClient, UpdateOne

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "stock_agent"

def ts_code_to_qq(ts_code):
    """000001.SZ → sz000001"""
    code, suffix = ts_code.split('.')
    prefix = 'sh' if suffix == 'SH' else ('bj' if suffix == 'BJ' else 'sz')
    return f'{prefix}{code}'

def fetch_kline(qq_code, start_date, end_date):
    """获取单只股票K线数据"""
    url = 'http://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
    # Format: code,period,start,end,count,fq_type
    param_str = f'{qq_code},day,{start_date},{end_date},100,qfq'
    var_name = 'kline_dayqfq'
    params = {'_var': var_name, 'param': param_str}
    
    try:
        r = requests.get(url, params=params, timeout=10)
        text = r.text
        if text.startswith(f'{var_name}='):
            text = text[len(f'{var_name}='):]
        data = json.loads(text)
        
        if data.get('code') != 0:
            return None
        
        # Navigate: data -> code -> qfqday
        code_key = qq_code
        if code_key in data.get('data', {}):
            klines = data['data'][code_key].get('qfqday', [])
            return klines
        # Try first key
        for k, v in data.get('data', {}).items():
            if isinstance(v, dict) and 'qfqday' in v:
                return v['qfqday']
        return None
    except Exception as e:
        return None

def main():
    target_date = sys.argv[1] if len(sys.argv) > 1 else date.today().strftime('%Y%m%d')
    target_date_int = int(target_date)
    # Format for Tencent API: 2026-05-25
    start_fmt = f'{target_date[:4]}-{target_date[4:6]}-{target_date[6:8]}'
    end_fmt = start_fmt
    
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    
    # Get all ts_codes
    all_codes = sorted(db['stock_daily_ak_full'].distinct('ts_code'))
    print(f"共 {len(all_codes)} 只股票，补日期 {target_date}")
    
    # Batch fetch - 50 stocks at a time with 0.2s delay
    batch_size = 50
    total_upserted = 0
    total_modified = 0
    total_fetched = 0
    errors = 0
    
    for i in range(0, len(all_codes), batch_size):
        batch_codes = all_codes[i:i+batch_size]
        ops = []
        
        for ts_code in batch_codes:
            qq_code = ts_code_to_qq(ts_code)
            klines = fetch_kline(qq_code, start_fmt, end_fmt)
            
            if not klines:
                errors += 1
                continue
            
            for k in klines:
                # k: [date, open, close, high, low, volume]
                kline_date = k[0].replace('-', '')  # 2026-05-25 -> 20260525
                if kline_date != target_date:
                    continue
                
                try:
                    doc = {
                        'ts_code': ts_code,
                        'trade_date': int(kline_date),
                        'open': float(k[1]),
                        'close': float(k[2]),
                        'high': float(k[3]),
                        'low': float(k[4]),
                        'vol': int(float(k[5])),
                        'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    }
                    
                    # Compute derived fields
                    # Get pre_close from previous day
                    prev_date_int = int((datetime.strptime(kline_date, '%Y%m%d') - timedelta(days=1)).strftime('%Y%m%d'))
                    prev = db['stock_daily_ak_full'].find_one({'ts_code': ts_code, 'trade_date': {'$lt': int(kline_date)}},
                                                              sort=[('trade_date', -1)])
                    if prev and prev.get('close'):
                        doc['pre_close'] = prev['close']
                        if prev['close'] > 0:
                            doc['pct_chg'] = round((doc['close'] / prev['close'] - 1) * 100, 2)
                    
                    ops.append(UpdateOne(
                        {'ts_code': ts_code, 'trade_date': int(kline_date)},
                        {'$set': doc},
                        upsert=True
                    ))
                    total_fetched += 1
                except (ValueError, IndexError) as e:
                    errors += 1
        
        if ops:
            result = db['stock_daily_ak_full'].bulk_write(ops, ordered=False)
            total_upserted += result.upserted_count
            total_modified += result.modified_count
        
        if (i + batch_size) % 500 == 0 or i + batch_size >= len(all_codes):
            print(f"  进度: {min(i+batch_size, len(all_codes))}/{len(all_codes)}, 已获取{total_fetched}只")
        
        time.sleep(0.15)  # Rate limit
    
    print(f"\n完成: 获取{total_fetched}只, upserted={total_upserted}, modified={total_modified}, errors={errors}")
    
    actual = db['stock_daily_ak_full'].count_documents({'trade_date': target_date_int})
    print(f"stock_daily_ak_full {target_date}: {actual} 只")
    
    client.close()

if __name__ == '__main__':
    main()
