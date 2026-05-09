#!/usr/bin/env python3
"""补全不完整交易日 - 稳健版(小批量+GC)"""
import sys
import gc
import time
import logging
import akshare as ak
from pymongo import MongoClient, UpdateOne

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("fill")

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "stock_agent"

INCOMPLETE_DATES = [
    20260323, 20260324, 20260325, 20260326, 20260327,
    20260330, 20260331, 20260401, 20260402, 20260403,
    20260407, 20260408, 20260409, 20260410, 20260413,
    20260414, 20260415, 20260416, 20260417, 20260420,
    20260421, 20260422, 20260423, 20260424, 20260427,
    20260428, 20260429, 20260430, 20260506,
]

def fill_day(db, trade_date):
    col = db["stock_daily_ak_full"]
    existing = set(col.distinct("ts_code", {"trade_date": trade_date}))
    ref = set(col.distinct("ts_code", {"trade_date": 20260508}))
    missing = sorted(ref - existing)
    
    if not missing:
        log.info(f"{trade_date}: 已完整({len(existing)}只)")
        return len(existing), 0, 0
    
    log.info(f"{trade_date}: {len(existing)}只→需补{len(missing)}只")
    
    added = 0
    failed = 0
    batch = []
    
    for i, ts_code in enumerate(missing):
        code, suffix = ts_code.split(".")
        if suffix == "BJ":
            failed += 1
            continue
        symbol = f"sh{code}" if suffix == "SH" else f"sz{code}"
        
        try:
            df = ak.stock_zh_a_daily(symbol=symbol, start_date=str(trade_date), end_date=str(trade_date), adjust="")
            if df is None or df.empty:
                failed += 1
                continue
            row = df.iloc[0]
            batch.append(UpdateOne(
                {"ts_code": ts_code, "trade_date": trade_date},
                {"$set": {
                    "open": round(float(row["open"]), 2),
                    "high": round(float(row["high"]), 2),
                    "low": round(float(row["low"]), 2),
                    "close": round(float(row["close"]), 2),
                    "vol": int(float(row["volume"])),
                    "amount": round(float(row["amount"]), 2),
                }},
                upsert=True,
            ))
            added += 1
        except:
            failed += 1
        
        # 小批量写入(100条)+GC
        if len(batch) >= 100:
            col.bulk_write(batch, ordered=False)
            batch = []
            gc.collect()
        
        time.sleep(0.25)
        
        if (i + 1) % 500 == 0:
            log.info(f"  {i+1}/{len(missing)} 新增{added} 失败{failed}")
    
    if batch:
        col.bulk_write(batch, ordered=False)
    
    gc.collect()
    total = col.count_documents({"trade_date": trade_date})
    log.info(f"{trade_date} 完成: 总{total}只 新增{added} 失败{failed}")
    return total, added, failed


def main():
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    
    log.info("=" * 50)
    log.info(f"补全{len(INCOMPLETE_DATES)}天不完整数据")
    log.info("=" * 50)
    
    grand_added = 0
    grand_failed = 0
    start = time.time()
    
    for i, td in enumerate(INCOMPLETE_DATES):
        # 跳过已完整的日期
        count = db["stock_daily_ak_full"].count_documents({"trade_date": td})
        if count >= 5500:
            log.info(f"[{i+1}/{len(INCOMPLETE_DATES)}] {td}: 已完整({count}只) 跳过")
            continue
        
        log.info(f"\n[{i+1}/{len(INCOMPLETE_DATES)}] {td} ({count}只)")
        _, added, failed = fill_day(db, td)
        grand_added += added
        grand_failed += failed
    
    elapsed = time.time() - start
    log.info("=" * 50)
    log.info(f"全部完成! 新增{grand_added} 失败{grand_failed} 耗时{elapsed/60:.0f}min")
    log.info("=" * 50)


if __name__ == "__main__":
    main()
