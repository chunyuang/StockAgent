#!/usr/bin/env python3
"""
补全旧段(1/5~3/20)缺失股票的日线数据

旧段stock_daily_ak_full只有2445只/天，新段有5184只。
缺2743只，需用AKShare补全。

用法:
  python3 fill_old_segment.py --dry-run     # 查看缺多少
  python3 fill_old_segment.py               # 实际补全
  python3 fill_old_segment.py --batch 100   # 只补100只(测试)
"""

import sys
import time
import gc
import argparse
import logging
import akshare as ak
import pandas as pd
from pymongo import MongoClient, UpdateOne
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("fill")

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "stock_agent"
COLL_NAME = "stock_daily_ak_full"

# 回测区间
START_DATE = "20260105"
END_DATE = "20260320"


def get_missing_codes(db):
    """找出旧段缺失的股票代码"""
    # 新段有但旧段没有的
    new_codes = set(d['ts_code'] for d in db[COLL_NAME].find(
        {'trade_date': 20260415}, {'ts_code': 1}
    ))
    old_codes = set(d['ts_code'] for d in db[COLL_NAME].find(
        {'trade_date': 20260115}, {'ts_code': 1}
    ))
    missing = sorted(new_codes - old_codes)
    return missing


def ts_to_ak(code):
    """600036.SH -> 600036"""
    return code.split('.')[0]


def fetch_and_save(db, codes, start_date, end_date, dry_run=False, batch_size=50):
    """逐只拉取AKShare日线数据并写入MongoDB"""
    total = len(codes)
    total_inserted = 0
    total_failed = 0
    start_time = time.time()
    
    coll = db[COLL_NAME]
    
    for i, ts_code in enumerate(codes):
        ak_code = ts_to_ak(ts_code)
        
        try:
            df = ak.stock_zh_a_daily(symbol=ak_code, start_date=start_date, end_date=end_date, adjust="")
            
            if df is None or df.empty:
                total_failed += 1
                if i % 100 == 0:
                    log.warning(f"[{i+1}/{total}] {ts_code} 无数据")
                continue
            
            # AKShare字段映射
            records = []
            for _, row in df.iterrows():
                date_val = row.get('date')
                if hasattr(date_val, 'strftime'):
                    trade_date = int(date_val.strftime('%Y%m%d'))
                else:
                    trade_date = int(str(date_val).replace('-', ''))
                
                # 只保留回测区间的数据
                if trade_date < 20260105 or trade_date > 20260320:
                    continue
                
                record = {
                    'ts_code': ts_code,
                    'trade_date': trade_date,
                    'open': float(row.get('open', 0)),
                    'high': float(row.get('high', 0)),
                    'low': float(row.get('low', 0)),
                    'close': float(row.get('close', 0)),
                    'pre_close': float(row.get('pre_close', 0)) if row.get('pre_close') else None,
                    'pct_chg': float(row.get('pct_chg', 0)) if row.get('pct_chg') else None,
                    'vol': float(row.get('vol', 0)) * 100 if row.get('vol') else 0,  # 手→股
                    'amount': float(row.get('amount', 0)) * 1000 if row.get('amount') else 0,  # 千元→元
                }
                records.append(record)
            
            if not dry_run and records:
                ops = [
                    UpdateOne(
                        {'ts_code': r['ts_code'], 'trade_date': r['trade_date']},
                        {'$set': r},
                        upsert=True
                    ) for r in records
                ]
                result = coll.bulk_write(ops, ordered=False)
                total_inserted += result.upserted_count + result.modified_count
            
            if (i + 1) % 50 == 0:
                elapsed = time.time() - start_time
                rate = (i + 1) / elapsed
                eta = (total - i - 1) / rate / 60
                log.info(f"[{i+1}/{total}] 已插入{total_inserted}条 | 失败{total_failed} | 速度{rate:.1f}只/秒 | 剩余{eta:.0f}分钟")
            
            # 速率控制: AKShare限制约1次/秒
            time.sleep(0.3)
            
        except Exception as e:
            total_failed += 1
            if total_failed <= 10:
                log.warning(f"[{i+1}/{total}] {ts_code} 失败: {e}")
            continue
        
        # 每200只做一次GC
        if (i + 1) % 200 == 0:
            gc.collect()
    
    elapsed = time.time() - start_time
    log.info(f"完成! 插入{total_inserted}条 | 失败{total_failed}只 | 耗时{elapsed/60:.1f}分钟")
    return total_inserted


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='只查看缺多少')
    parser.add_argument('--batch', type=int, default=0, help='只补前N只(测试用)')
    args = parser.parse_args()
    
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    
    missing = get_missing_codes(db)
    log.info(f"旧段缺失股票: {len(missing)}只")
    
    if args.dry_run:
        log.info(f"预估需补: {len(missing)}只 × 49天 = {len(missing)*49:,}条")
        log.info(f"预估耗时: ~{len(missing)*0.3/60:.0f}分钟")
        return
    
    codes = missing[:args.batch] if args.batch > 0 else missing
    if args.batch:
        log.info(f"测试模式: 只补前{args.batch}只")
    
    fetch_and_save(db, codes, START_DATE, END_DATE, dry_run=args.dry_run)


if __name__ == '__main__':
    main()
