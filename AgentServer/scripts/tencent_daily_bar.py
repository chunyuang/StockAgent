#!/usr/bin/env python3
"""
腾讯行情API → stock_daily_ak_full 补当日OHLCV

当东方财富push2被封时，使用腾讯qt.gtimg.cn接口补数据。
腾讯接口返回盘中实时数据，收盘后即为当日日线。

字段映射:
腾讯: 名称~代码~现价~昨收~开~成交量(手)~外盘~内盘~买1~...~最高~最低~...~成交额(万)~...
位置: 1=名称 3=现价 4=昨收 5=开 6=成交量(手) 32=最高 33=最低 37=成交额(万) 38=换手率

注意: 腾讯接口一次最多请求约800只，分批获取。
"""
import requests
import re
import time
import sys
from datetime import datetime, date
from pymongo import MongoClient, UpdateOne

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "stock_agent"

def ts_code_to_qq(ts_code):
    """000001.SZ → sz000001, 600036.SH → sh600036"""
    code, suffix = ts_code.split('.')
    prefix = 'sh' if suffix == 'SH' else ('bj' if suffix == 'BJ' else 'sz')
    return f'{prefix}{code}'

def qq_to_ts_code(qq_code):
    """sh600036 → 600036.SH"""
    prefix = qq_code[:2]
    code = qq_code[2:]
    suffix = 'SH' if prefix == 'sh' else ('BJ' if prefix == 'bj' else 'SZ')
    return f'{code}.{suffix}'

def safe_float(v, default=None):
    if v is None or v == '-' or v == '':
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default

def fetch_batch(qq_codes):
    """批量获取腾讯行情，一次最多约800只"""
    all_data = {}
    url = f'http://qt.gtimg.cn/q={",".join(qq_codes)}'
    try:
        r = requests.get(url, timeout=15)
        lines = r.text.strip().split(';')
        for line in lines:
            line = line.strip()
            if not line:
                continue
            m = re.match(r'v_(\w+)="(.+)"', line)
            if not m:
                continue
            qq_code = m.group(1)
            fields = m.group(2).split('~')
            if len(fields) < 40:
                continue
            # 腾讯字段位置:
            # 1=名称 3=现价 4=昨收 5=开 6=成交量(手) 
            # 32=最高 33=最低 37=成交额(万) 38=换手率
            name = fields[1]
            price = safe_float(fields[3])       # 现价=收盘价(盘中)
            pre_close = safe_float(fields[4])   # 昨收
            open_price = safe_float(fields[5])  # 开盘
            vol = safe_float(fields[6])         # 成交量(手)
            high = safe_float(fields[32])       # 最高
            low = safe_float(fields[33])        # 最低
            amount_wan = safe_float(fields[37]) # 成交额(万)
            turnover = safe_float(fields[38])   # 换手率
            
            if price and price > 0:
                all_data[qq_code] = {
                    'name': name,
                    'close': price,
                    'pre_close': pre_close,
                    'open': open_price,
                    'high': high,
                    'low': low,
                    'vol': int(vol) if vol else 0,  # 手, MongoDB标准也是手, 直接存
                    'amount': amount_wan * 100 if amount_wan else 0,  # 万元→百元(×100)
                    'turnover_rate': turnover,
                    'pct_chg': round((price / pre_close - 1) * 100, 2) if pre_close and pre_close > 0 else None,
                }
    except Exception as e:
        print(f"腾讯API错误: {e}")
    return all_data

def main():
    target_date = sys.argv[1] if len(sys.argv) > 1 else date.today().strftime('%Y%m%d')
    target_date_int = int(target_date)
    
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    
    # 获取所有ts_code
    all_codes = sorted(db['stock_daily_ak_full'].distinct('ts_code'))
    print(f"共 {len(all_codes)} 只股票，目标日期 {target_date}")
    
    # 转换为腾讯代码
    qq_codes = [ts_code_to_qq(c) for c in all_codes]
    ts_code_map = {ts_code_to_qq(c): c for c in all_codes}
    
    # 分批获取 (每批500只)
    batch_size = 500
    all_fetched = {}
    for i in range(0, len(qq_codes), batch_size):
        batch = qq_codes[i:i+batch_size]
        data = fetch_batch(batch)
        all_fetched.update(data)
        if i % 2000 == 0:
            print(f"  已获取 {len(all_fetched)}/{len(qq_codes)}...")
        time.sleep(0.3)  # 避免过快
    
    print(f"共获取 {len(all_fetched)} 只股票行情")
    
    # 写入MongoDB
    ops = []
    count = 0
    for qq_code, info in all_fetched.items():
        ts_code = ts_code_map.get(qq_code)
        if not ts_code or not info.get('close') or info['close'] <= 0:
            continue
        
        doc = {
            'ts_code': ts_code,
            'trade_date': target_date_int,
            'open': info['open'],
            'high': info['high'],
            'low': info['low'],
            'close': info['close'],
            'pre_close': info.get('pre_close'),
            'vol': info['vol'],
            'amount': info['amount'],
            'pct_chg': info.get('pct_chg'),
            'turnover_rate': info.get('turnover_rate'),
            'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        
        ops.append(UpdateOne(
            {'ts_code': ts_code, 'trade_date': target_date_int},
            {'$set': doc},
            upsert=True
        ))
        count += 1
    
    if ops:
        result = db['stock_daily_ak_full'].bulk_write(ops, ordered=False)
        print(f"写入完成: upserted={result.upserted_count}, modified={result.modified_count}")
    
    # 同时补 daily_basic (PE/PB从腾讯获取不到，只补基础字段)
    # 检查结果
    actual_count = db['stock_daily_ak_full'].count_documents({'trade_date': target_date_int})
    print(f"stock_daily_ak_full {target_date}: {actual_count} 只")
    
    client.close()

if __name__ == '__main__':
    main()
