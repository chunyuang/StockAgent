#!/usr/bin/env python3
"""
修复段1(20251008~20260320)前复权残留数据

检测方法: 段1 close / 段2首日close > 3 → 前复权
修复方法: AKShare stock_zh_a_daily(adjust="") 拉不复权真实价

用法: python3 fix_qfq_batch.py [--dry-run] [--limit N]
"""
import sys
import time
import logging
import argparse
from pymongo import MongoClient, UpdateOne
from datetime import datetime

try:
    import akshare as ak
    HAS_AKSHARE = True
except ImportError:
    HAS_AKSHARE = False
    print("ERROR: akshare not installed. pip install akshare")
    sys.exit(1)

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "stock_agent"
QFQ_RATIO_THRESHOLD = 3.0  # close/参考价 > 3 视为前复权

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("fix_qfq")


def get_qfq_candidates(db):
    """找到所有疑似前复权的股票"""
    # 段2首日参考价
    p2_ref = {}
    for r in db.stock_daily_ak_full.find(
        {"trade_date": {"$gte": 20260321}},
        ["ts_code", "trade_date", "close"]
    ).sort("trade_date", 1):
        if r["ts_code"] not in p2_ref and r.get("close") and r["close"] > 0:
            p2_ref[r["ts_code"]] = r["close"]

    log.info(f"段2参考价: {len(p2_ref)} 只股票")

    # 找段1中前复权记录
    candidates = {}  # ts_code -> list of (trade_date, current_close, ref_close, ratio)
    for r in db.stock_daily_ak_full.find(
        {"trade_date": {"$gte": 20251008, "$lte": 20260320}},
        ["ts_code", "trade_date", "close"]
    ):
        code = r["ts_code"]
        close = r.get("close", 0)
        if close <= 0:
            continue
        ref = p2_ref.get(code, 0)
        if ref <= 0:
            continue
        ratio = close / ref
        if ratio > QFQ_RATIO_THRESHOLD:
            if code not in candidates:
                candidates[code] = []
            candidates[code].append((r["trade_date"], close, ref, ratio))

    return candidates


def ts_code_to_symbol(ts_code):
    """ts_code → AKShare symbol"""
    code, suffix = ts_code.split(".")
    if suffix == "SH":
        return f"sh{code}"
    elif suffix == "SZ":
        return f"sz{code}"
    else:
        return None  # 北交所AKShare不支持


def fix_stock(db, ts_code, qfq_records, dry_run=False):
    """用AKShare修复单只股票的前复权数据"""
    symbol = ts_code_to_symbol(ts_code)
    if not symbol:
        log.warning(f"  {ts_code} 北交所跳过(AKShare不支持)")
        return 0, 0

    try:
        df = ak.stock_zh_a_daily(
            symbol=symbol,
            start_date="20251008",
            end_date="20260320",
            adjust=""  # 不复权
        )
    except Exception as e:
        log.warning(f"  {ts_code} AKShare获取失败: {e}")
        return 0, len(qfq_records)

    if df is None or df.empty:
        log.warning(f"  {ts_code} AKShare返回空数据")
        return 0, len(qfq_records)

    # 构建AKShare数据映射: trade_date → row
    ak_data = {}
    for _, row in df.iterrows():
        d = row["date"]
        if hasattr(d, "year"):
            td = int(f"{d.year:04d}{d.month:02d}{d.day:02d}")
        else:
            td = int(str(d).replace("-", ""))
        ak_data[td] = row

    # 只更新前复权的日期
    updates = []
    fixed = 0
    for trade_date, old_close, ref_close, ratio in qfq_records:
        if trade_date not in ak_data:
            continue
        row = ak_data[trade_date]
        new_close = round(float(row["close"]), 2)
        new_open = round(float(row["open"]), 2)
        new_high = round(float(row["high"]), 2)
        new_low = round(float(row["low"]), 2)
        new_vol = int(float(row["volume"]))
        new_amount = round(float(row["amount"]), 2)

        # 验证：新close应该接近参考价量级
        if ref_close > 0 and new_close / ref_close > QFQ_RATIO_THRESHOLD:
            log.warning(f"  {ts_code} {trade_date}: 修复后close={new_close}仍偏高(/{ref_close}={new_close/ref_close:.1f}x), 跳过")
            continue

        updates.append(UpdateOne(
            {"ts_code": ts_code, "trade_date": trade_date},
            {"$set": {
                "close": new_close,
                "open": new_open,
                "high": new_high,
                "low": new_low,
                "vol": new_vol,
                "amount": new_amount,
            }}
        ))
        fixed += 1

    if updates and not dry_run:
        result = db.stock_daily_ak_full.bulk_write(updates, ordered=False)
        log.info(f"  {ts_code}: 修复 {result.modified_count} 条 (尝试 {len(updates)} 条)")
    elif dry_run:
        log.info(f"  {ts_code}: [DRY-RUN] 将修复 {len(updates)} 条")

    return fixed, len(qfq_records) - fixed


def main():
    parser = argparse.ArgumentParser(description="修复段1前复权残留数据")
    parser.add_argument("--dry-run", action="store_true", help="只检测不修改")
    parser.add_argument("--limit", type=int, default=0, help="最多处理N只股票(0=全部)")
    args = parser.parse_args()

    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]

    log.info("=" * 60)
    log.info("前复权残留数据批量修复")
    log.info("=" * 60)

    # Step 1: 检测
    candidates = get_qfq_candidates(db)
    total_records = sum(len(v) for v in candidates.values())
    log.info(f"疑似前复权: {len(candidates)} 只股票, {total_records} 条记录")

    if not candidates:
        log.info("无需修复！")
        return

    # 按受影响记录数排序(多的先修)
    sorted_codes = sorted(candidates.keys(), key=lambda c: -len(candidates[c]))

    if args.limit > 0:
        sorted_codes = sorted_codes[:args.limit]
        log.info(f"限制处理前 {args.limit} 只股票")

    # Step 2: 逐只修复
    total_fixed = 0
    total_failed = 0
    start = time.time()

    for i, code in enumerate(sorted_codes):
        records = candidates[code]
        log.info(f"[{i+1}/{len(sorted_codes)}] {code}: {len(records)} 条前复权记录")
        fixed, failed = fix_stock(db, code, records, dry_run=args.dry_run)
        total_fixed += fixed
        total_failed += failed

        # AKShare限流: 每只间隔1秒
        if i < len(sorted_codes) - 1:
            time.sleep(1)

    elapsed = time.time() - start
    log.info("=" * 60)
    log.info(f"完成! 修复 {total_fixed} 条, 失败 {total_failed} 条, 耗时 {elapsed:.0f}s")
    if args.dry_run:
        log.info("(DRY-RUN 模式, 未实际修改数据)")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
