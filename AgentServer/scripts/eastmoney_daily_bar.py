#!/usr/bin/env python3
"""
东方财富全市场快照 → stock_daily_ak_full 补当日OHLCV

用stock_zh_a_spot_em字段: 最新价/开盘/最高/最低/成交量/成交额/涨跌幅/昨收
写入stock_daily_ak_full集合(与AKShare collector格式一致)

用法: python3 eastmoney_daily_bar.py [--date 20260507]
"""
import requests
import time
import sys
import os
from datetime import datetime
from pymongo import MongoClient, UpdateOne

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "stock_agent"

# 东方财富字段:
# f2=最新价 f3=涨跌幅 f4=涨跌额 f5=成交量(手) f6=成交额
# f7=振幅 f8=换手率 f9=PE f10=量比
# f12=代码 f14=名称 f15=最高 f16=最低 f17=开盘 f18=昨收
# f20=总市值 f21=流通市值 f23=PB

def code_to_ts_code(code_str):
    code = str(code_str).zfill(6)
    if code.startswith(('6', '9')):
        return f"{code}.SH"
    elif code.startswith(('8', '4')):
        return f"{code}.BJ"
    else:
        return f"{code}.SZ"

def safe_float(v, default=None):
    if v is None or v == '-' or v == '':
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default

def fetch_all():
    all_data = []
    for pn in range(1, 60):
        url = 'https://push2.eastmoney.com/api/qt/clist/get'
        params = {
            'pn': pn, 'pz': 200, 'po': 1, 'np': 1,
            'fltt': 2, 'invt': 2, 'fid': 'f3',
            'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048',
            'fields': 'f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f14,f15,f16,f17,f18,f20,f21,f23,f115'
        }
        r = requests.get(url, params=params, timeout=10)
        d = r.json()
        diff = d.get('data', {}).get('diff', [])
        if not diff:
            break
        all_data.extend(diff)
    return all_data

def write_daily_bar(trade_date=None):
    db = MongoClient(MONGO_URI)[DB_NAME]
    
    if trade_date is None:
        trade_date = int(datetime.now().strftime("%Y%m%d"))
    
    t0 = time.time()
    all_data = fetch_all()
    print(f"拉取 {len(all_data)} 只, 耗时 {time.time()-t0:.1f}s")
    
    # 检查已有
    existing = db.stock_daily_ak_full.count_documents({"trade_date": trade_date})
    if existing > 100:
        db.stock_daily_ak_full.delete_many({"trade_date": trade_date})
        print(f"删除已有 {existing} 条, 重新写入")
    
    updates = []
    for item in all_data:
        code = item.get('f12', '')
        if not code:
            continue
        ts_code = code_to_ts_code(code)
        name = item.get('f14', '')
        
        open_price = safe_float(item.get('f17'))
        high = safe_float(item.get('f15'))
        low = safe_float(item.get('f16'))
        close = safe_float(item.get('f2'))
        pre_close = safe_float(item.get('f18'))
        pct_chg = safe_float(item.get('f3'))
        vol_hand = safe_float(item.get('f5'), 0)  # 手
        amount = safe_float(item.get('f6'), 0)     # 元
        amplitude = safe_float(item.get('f7'))      # 振幅%
        turnover_rate = safe_float(item.get('f8'))  # 换手率%
        volume_ratio = safe_float(item.get('f10'))  # 量比
        circ_mv = safe_float(item.get('f21'))       # 流通市值(元)
        
        # 成交量: 手 → 股
        vol = int(vol_hand * 100) if vol_hand else 0
        
        # 流通市值: 元 → 万元 (stock_daily_ak_full的单位)
        circ_mv_wan = round(circ_mv / 1e4, 2) if circ_mv and circ_mv > 0 else 0
        
        # 涨跌判断
        is_limit_up = 0
        is_limit_down = 0
        if pre_close and pre_close > 0:
            pct = pct_chg if pct_chg is not None else 0
            if code.startswith(('300', '301')) or code.startswith('688'):
                if pct >= 19.9: is_limit_up = 1
                if pct <= -19.9: is_limit_down = 1
            elif code.startswith(('8', '4')):
                if pct >= 29.9: is_limit_up = 1
                if pct <= -29.9: is_limit_down = 1
            else:
                if pct >= 9.9: is_limit_up = 1
                if pct <= -9.9: is_limit_down = 1
        
        doc = {
            "ts_code": ts_code,
            "trade_date": trade_date,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "pre_close": pre_close,
            "pct_chg": pct_chg,
            "vol": vol,
            "amount": amount,
            "turnover_rate": turnover_rate,
            "volume_ratio": volume_ratio,
            "circ_mv": circ_mv_wan,
            "is_limit_up": is_limit_up,
            "is_limit_down": is_limit_down,
            "amplitude": amplitude,
        }
        
        updates.append(
            UpdateOne(
                {"ts_code": ts_code, "trade_date": trade_date},
                {"$set": doc},
                upsert=True,
            )
        )
    
    if updates:
        t1 = time.time()
        result = db.stock_daily_ak_full.bulk_write(updates, ordered=False)
        print(f"写入 {result.upserted_count + result.modified_count} 条, 耗时 {time.time()-t1:.1f}s")
    
    # 验证
    total = db.stock_daily_ak_full.count_documents({"trade_date": trade_date})
    print(f"\nstock_daily_ak_full {trade_date}: {total}只")
    
    # 看看之前的日期对比
    sample_old = db.stock_daily_ak_full.find_one({"trade_date": 20260506, "ts_code": "000001.SZ"})
    sample_new = db.stock_daily_ak_full.find_one({"trade_date": trade_date, "ts_code": "000001.SZ"})
    if sample_old:
        print(f"旧(5/6): open={sample_old.get('open')} high={sample_old.get('high')} low={sample_old.get('low')} close={sample_old.get('close')} vol={sample_old.get('vol')} amount={sample_old.get('amount')}")
    if sample_new:
        print(f"新({trade_date}): open={sample_new.get('open')} high={sample_new.get('high')} low={sample_new.get('low')} close={sample_new.get('close')} vol={sample_new.get('vol')} amount={sample_new.get('amount')}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=int, default=None, help="日期yyyymmdd，默认今天")
    args = parser.parse_args()
    write_daily_bar(args.date)
