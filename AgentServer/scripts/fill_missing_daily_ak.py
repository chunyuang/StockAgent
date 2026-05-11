#!/usr/bin/env python3
"""
用AKShare补全 stock_daily_ak_full 缺失股票的日线数据

策略: 对每只缺失股票，一次拉 4/15~5/6 全部数据，比逐天拉快13x

用法:
  python3 fill_missing_daily_ak.py --dry-run
  python3 fill_missing_daily_ak.py
"""

import time
import gc
import logging
import akshare as ak
from pymongo import MongoClient, UpdateOne

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("fill")

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "stock_agent"

# 需要补全的日期范围
START_DATE = "20260415"
END_DATE = "20260506"

# 不完整日期(3/20后, <5000只)
INCOMPLETE_DATES = {
    20260415, 20260416, 20260417, 20260420, 20260421,
    20260422, 20260423, 20260424, 20260427, 20260428,
    20260429, 20260430, 20260506,
}


def ts_code_to_symbol(ts_code):
    """ts_code → AKShare symbol"""
    code, suffix = ts_code.split(".")
    if suffix == "SH":
        return f"sh{code}"
    elif suffix == "SZ":
        return f"sz{code}"
    else:  # BJ等暂不支持
        return None


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    col = db["stock_daily_ak_full"]
    
    # 参考完整日
    full_codes = set(col.distinct("ts_code", {"trade_date": 20260508}))
    log.info(f"参考完整日(5/8): {len(full_codes)}只")
    
    # 找出4/15的缺失股票(代表所有不完整日)
    existing_0415 = set(col.distinct("ts_code", {"trade_date": 20260415}))
    missing = sorted(full_codes - existing_0415)
    
    sh = [c for c in missing if c.endswith('.SH')]
    sz = [c for c in missing if c.endswith('.SZ')]
    bj = [c for c in missing if c.endswith('.BJ')]
    
    log.info(f"缺失: {len(missing)}只 (SH:{len(sh)}, SZ:{len(sz)}, BJ:{len(bj)})")
    
    if args.dry_run:
        log.info(f"预计耗时: {len(sh+sz)}只 × 0.3s ≈ {len(sh+sz)*0.3/60:.0f}分钟")
        log.info(f"BJ股({len(bj)}只)暂不支持AKShare, 跳过")
        return
    
    # 过滤掉BJ
    fillable = [c for c in missing if not c.endswith('.BJ')]
    log.info(f"可补: {len(fillable)}只 (跳过{len(bj)}只BJ)")
    
    total_upserted = 0
    total_errors = 0
    total_rows = 0
    start_time = time.time()
    batch = []
    
    for i, ts_code in enumerate(fillable):
        symbol = ts_code_to_symbol(ts_code)
        if not symbol:
            total_errors += 1
            continue
        
        try:
            df = ak.stock_zh_a_daily(
                symbol=symbol,
                start_date=START_DATE,
                end_date=END_DATE,
                adjust=""  # 不复权
            )
            
            if df is None or df.empty:
                total_errors += 1
                continue
            
            for _, row in df.iterrows():
                # 日期处理
                date_val = row['date']
                if hasattr(date_val, 'strftime'):
                    trade_date = int(date_val.strftime('%Y%m%d'))
                else:
                    trade_date = int(str(date_val).replace('-', ''))
                
                # 只写入我们需要的日期
                if trade_date not in INCOMPLETE_DATES:
                    continue
                
                # vol: AKShare返回的volume单位是股
                vol = int(float(row['volume'])) if row['volume'] else 0
                amount = float(row['amount']) if row['amount'] else 0
                
                doc = {
                    "ts_code": ts_code,
                    "trade_date": trade_date,
                    "open": round(float(row['open']), 2) if row['open'] else None,
                    "high": round(float(row['high']), 2) if row['high'] else None,
                    "low": round(float(row['low']), 2) if row['low'] else None,
                    "close": round(float(row['close']), 2) if row['close'] else None,
                    "vol": vol,
                    "amount": round(amount, 2),
                }
                
                # pre_close和pct_chg (如果有的话)
                if 'close' in row and hasattr(row, 'change') and row.get('change'):
                    doc['pre_close'] = round(float(row['close']) - float(row['change']), 2)
                
                batch.append(UpdateOne(
                    {"ts_code": ts_code, "trade_date": trade_date},
                    {"$set": doc},
                    upsert=True
                ))
                total_rows += 1
            
        except Exception as e:
            total_errors += 1
            if total_errors <= 10:
                log.info(f"  {ts_code}: {e}")
        
        # 批量写入
        if len(batch) >= 300:
            try:
                result = col.bulk_write(batch, ordered=False)
                total_upserted += result.upserted_count + result.modified_count
            except Exception as e:
                total_errors += len(batch)
            batch = []
            gc.collect()
        
        # 限流 + 进度
        time.sleep(0.25)
        
        if (i + 1) % 200 == 0:
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed
            eta = (len(fillable) - i - 1) / rate / 60
            log.info(f"[{i+1}/{len(fillable)}] 写入{total_upserted}条, 行{total_rows}, 错{total_errors}, {rate:.1f}只/s, ETA {eta:.1f}min")
    
    # 写入剩余
    if batch:
        try:
            result = col.bulk_write(batch, ordered=False)
            total_upserted += result.upserted_count + result.modified_count
        except:
            total_errors += len(batch)
    
    elapsed = time.time() - start_time
    log.info(f"=== 完成 ===")
    log.info(f"写入: {total_upserted}条, 行: {total_rows}, 错误: {total_errors}")
    log.info(f"耗时: {elapsed/60:.1f}分钟")
    
    # 验证
    log.info(f"=== 验证 ===")
    for dt in sorted(INCOMPLETE_DATES):
        cnt = col.count_documents({"trade_date": dt})
        status = "✅" if cnt >= 4500 else "⚠️"
        log.info(f"  {dt}: {cnt}只 {status}")


if __name__ == "__main__":
    main()
