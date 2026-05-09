#!/usr/bin/env python3
"""
用AKShare不复权数据覆盖段1(20251008~20260320)的全部OHLCV

策略: 信任AKShare adjust=""的真实价,直接覆盖MongoDB中的段1数据
不需要检测哪些是前复权——全量覆盖最可靠

用法: python3 fix_qfq_overwrite.py [--dry-run] [--limit N] [--start-from CODE]
"""
import sys
import time
import logging
import argparse
from pymongo import MongoClient, UpdateOne

try:
    import akshare as ak
except ImportError:
    print("ERROR: akshare not installed")
    sys.exit(1)

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "stock_agent"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("fix_qfq")


def ts_code_to_symbol(ts_code):
    code, suffix = ts_code.split(".")
    if suffix == "SH":
        return f"sh{code}"
    elif suffix == "SZ":
        return f"sz{code}"
    else:
        return None  # 北交所AKShare不支持


def fix_stock(db, ts_code, dry_run=False):
    """用AKShare覆盖单只股票的段1数据"""
    symbol = ts_code_to_symbol(ts_code)
    if not symbol:
        return 0, 0, "bj_skip"

    try:
        df = ak.stock_zh_a_daily(
            symbol=symbol,
            start_date="20251008",
            end_date="20260320",
            adjust=""  # 不复权
        )
    except Exception as e:
        return 0, 0, f"ak_error: {e}"

    if df is None or df.empty:
        return 0, 0, "empty"

    # 构建更新
    updates = []
    prev_close = None
    for idx, row in df.iterrows():
        d = row["date"]
        if hasattr(d, "year"):
            td = int(f"{d.year:04d}{d.month:02d}{d.day:02d}")
        else:
            td = int(str(d).replace("-", ""))

        close = round(float(row["close"]), 2)
        open_ = round(float(row["open"]), 2)
        high = round(float(row["high"]), 2)
        low = round(float(row["low"]), 2)
        vol = int(float(row["volume"]))
        amount = round(float(row["amount"]), 2)

        # 计算pre_close和pct_chg
        if prev_close and prev_close > 0:
            pre_close = prev_close
            pct_chg = round((close - pre_close) / pre_close * 100, 2)
        else:
            pre_close = open_  # 首日无前日，用open近似
            pct_chg = 0.0

        updates.append(UpdateOne(
            {"ts_code": ts_code, "trade_date": td},
            {"$set": {
                "close": close,
                "open": open_,
                "high": high,
                "low": low,
                "vol": vol,
                "amount": amount,
                "pre_close": pre_close,
                "pct_chg": pct_chg,
            }}
        ))
        prev_close = close

    if not updates:
        return 0, 0, "no_updates"

    if dry_run:
        return len(updates), 0, "dry_run"

    try:
        result = db.stock_daily_ak_full.bulk_write(updates, ordered=False)
        return result.modified_count + result.upserted_count, 0, "ok"
    except Exception as e:
        return 0, len(updates), f"write_error: {e}"


def main():
    parser = argparse.ArgumentParser(description="用AKShare不复权数据覆盖段1")
    parser.add_argument("--dry-run", action="store_true", help="只检测不修改")
    parser.add_argument("--limit", type=int, default=0, help="最多处理N只(0=全部)")
    parser.add_argument("--start-from", type=str, default="", help="从指定ts_code开始")
    args = parser.parse_args()

    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]

    # 获取段1所有不重复的ts_code
    codes = db.stock_daily_ak_full.distinct("ts_code", {
        "trade_date": {"$gte": 20251008, "$lte": 20260320}
    })
    # 只处理SH/SZ(北交所AKShare不支持)
    codes = sorted([c for c in codes if c.endswith((".SH", ".SZ"))])
    total = len(codes)
    log.info(f"段1股票: {total} 只(SH+SZ)")

    if args.start_from:
        idx = next((i for i, c in enumerate(codes) if c >= args.start_from), 0)
        codes = codes[idx:]
        log.info(f"从 {args.start_from} 开始, 跳过 {idx} 只")

    if args.limit > 0:
        codes = codes[:args.limit]
        log.info(f"限制处理 {args.limit} 只")

    total_updated = 0
    total_failed = 0
    start_time = time.time()

    for i, code in enumerate(codes):
        updated, failed, status = fix_stock(db, code, dry_run=args.dry_run)

        if status == "ok":
            total_updated += updated
            log.info(f"[{i+1}/{total}] {code}: 更新 {updated} 条")
        elif status == "bj_skip":
            pass  # 静默跳过北交所
        elif status == "dry_run":
            total_updated += updated
            log.info(f"[{i+1}/{total}] {code}: [DRY-RUN] 将更新 {updated} 条")
        else:
            total_failed += failed
            log.warning(f"[{i+1}/{total}] {code}: 跳过 ({status})")

        # AKShare限流
        if i < len(codes) - 1:
            time.sleep(1.0)

        # 进度报告(每100只)
        if (i + 1) % 100 == 0:
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed
            eta = (len(codes) - i - 1) / rate / 60
            log.info(f"--- 进度: {i+1}/{len(codes)} ({(i+1)/len(codes)*100:.0f}%) "
                     f"速率: {rate:.1f}只/s ETA: {eta:.0f}min ---")

    elapsed = time.time() - start_time
    log.info("=" * 60)
    log.info(f"完成! 更新 {total_updated} 条, 失败 {total_failed} 条, 耗时 {elapsed/60:.1f}min")
    if args.dry_run:
        log.info("(DRY-RUN 模式)")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
