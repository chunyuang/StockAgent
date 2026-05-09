#!/usr/bin/env python3
"""
补全3/23~5/6不完整交易日的缺失股票数据

问题: 这些日期只有2440只(AKShare旧数据)，缺少约3400只
方案: 用AKShare stock_zh_a_daily逐只补全，每日约5500只需补充3400只
      AKShare单只0.3s，3400只/天≈17min，29天≈8h
      优化: 只补缺失的股票，跳过已有的

用法: python3 fill_incomplete_days.py [--dry-run] [--day 20260323]
"""
import sys
import time
import logging
import argparse
from pymongo import MongoClient, UpdateOne
from datetime import datetime, timedelta

try:
    import akshare as ak
except ImportError:
    print("ERROR: akshare not installed")
    sys.exit(1)

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "stock_agent"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("fill_days")


def ts_code_to_symbol(ts_code):
    code, suffix = ts_code.split(".")
    if suffix == "SH":
        return f"sh{code}"
    elif suffix == "SZ":
        return f"sz{code}"
    else:
        return None


def fill_one_day(db, trade_date, dry_run=False):
    """补全单日缺失的股票数据"""
    col = db["stock_daily_ak_full"]
    
    # 当天已有的股票
    existing_codes = set(col.distinct("ts_code", {"trade_date": trade_date}))
    
    # 参考完整日的股票列表(用5/8的东方财富数据)
    ref_codes = set(col.distinct("ts_code", {"trade_date": 20260508}))
    
    # 需要补充的股票
    missing_codes = sorted(ref_codes - existing_codes)
    
    if not missing_codes:
        log.info(f"{trade_date}: 已完整({len(existing_codes)}只)，无需补充")
        return 0, 0
    
    log.info(f"{trade_date}: 已有{len(existing_codes)}只，缺失{len(missing_codes)}只")
    
    # 逐只从AKShare拉取
    added = 0
    failed = 0
    batch_updates = []
    
    for i, ts_code in enumerate(missing_codes):
        symbol = ts_code_to_symbol(ts_code)
        if not symbol:
            failed += 1
            continue
        
        try:
            td_str = str(trade_date)
            start = f"{td_str[:4]}-{td_str[4:6]}-{td_str[6:8]}"
            df = ak.stock_zh_a_daily(symbol=symbol, start_date=start, end_date=start, adjust="")
            
            if df is None or df.empty:
                failed += 1
                continue
            
            row = df.iloc[0]
            doc = {
                "ts_code": ts_code,
                "trade_date": trade_date,
                "open": round(float(row["open"]), 2),
                "high": round(float(row["high"]), 2),
                "low": round(float(row["low"]), 2),
                "close": round(float(row["close"]), 2),
                "vol": int(float(row["volume"])),
                "amount": round(float(row["amount"]), 2),
            }
            
            batch_updates.append(UpdateOne(
                {"ts_code": ts_code, "trade_date": trade_date},
                {"$set": doc},
                upsert=True,
            ))
            added += 1
            
        except Exception as e:
            failed += 1
            if i < 5 or failed <= 3:
                log.warning(f"  {ts_code}: {e}")
        
        # 每500只批量写入 + 限流
        if len(batch_updates) >= 500:
            if not dry_run:
                result = col.bulk_write(batch_updates, ordered=False)
                log.info(f"  批量写入: {result.upserted_count + result.modified_count} 条")
            batch_updates = []
        
        time.sleep(0.3)  # AKShare限流
        
        # 进度
        if (i + 1) % 500 == 0:
            log.info(f"  进度: {i+1}/{len(missing_codes)} (新增{added} 失败{failed})")
    
    # 写入剩余
    if batch_updates and not dry_run:
        result = col.bulk_write(batch_updates, ordered=False)
        log.info(f"  最终批量写入: {result.upserted_count + result.modified_count} 条")
    
    log.info(f"{trade_date} 完成: 新增{added} 失败{failed}")
    return added, failed


def main():
    parser = argparse.ArgumentParser(description="补全不完整交易日的缺失股票数据")
    parser.add_argument("--dry-run", action="store_true", help="只检测不修改")
    parser.add_argument("--day", type=int, default=0, help="只补指定日期(如20260323)")
    parser.add_argument("--start", type=int, default=20260323, help="起始日期")
    parser.add_argument("--end", type=int, default=20260506, help="结束日期")
    args = parser.parse_args()
    
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    col = db["stock_daily_ak_full"]
    
    log.info("=" * 60)
    log.info("补全不完整交易日缺失数据")
    log.info("=" * 60)
    
    if args.day:
        # 只补指定日期
        fill_one_day(db, args.day, dry_run=args.dry_run)
    else:
        # 找所有不完整交易日
        pipeline = [
            {"$match": {"trade_date": {"$gte": args.start, "$lte": args.end}}},
            {"$group": {"_id": "$trade_date", "count": {"$sum": 1}}},
            {"$sort": {"_id": 1}}
        ]
        by_date = {r["_id"]: r["count"] for r in col.aggregate(pipeline)}
        incomplete = sorted(d for d, c in by_date.items() if c < 5500)
        
        log.info(f"不完整交易日: {len(incomplete)} 天")
        
        total_added = 0
        total_failed = 0
        start_time = time.time()
        
        for i, td in enumerate(incomplete):
            log.info(f"\n--- [{i+1}/{len(incomplete)}] {td} ---")
            added, failed = fill_one_day(db, td, dry_run=args.dry_run)
            total_added += added
            total_failed += failed
        
        elapsed = time.time() - start_time
        log.info("=" * 60)
        log.info(f"全部完成! 新增{total_added}条 失败{total_failed}条 耗时{elapsed/60:.1f}min")
        if args.dry_run:
            log.info("(DRY-RUN 模式)")
        log.info("=" * 60)


if __name__ == "__main__":
    main()
