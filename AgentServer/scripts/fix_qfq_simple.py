#!/usr/bin/env python3
"""
简单前复权数据修复脚本

只修复段1(20251008~20260320)中确实前复权的记录
策略: 用AKShare stock_zh_a_daily逐只拉真实价
"""
import sys
import time
import logging
from pymongo import MongoClient, UpdateOne
import akshare as ak

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "stock_agent"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("fix_qfq")

qfq_range = {"$gte": 20251008, "$lte": 20260320}

def fix_qfq_with_akshare(db, start_date, end_date):
    """用AKShare拉真实价数据"""
    total_updated = 0
    total_failed = 0
    
    # 只处理需要修复的股票（检测到的QFQ记录）
    codes = list(db.stock_daily_ak_full.find(
        {"trade_date": {"$gte": 20251008, "$lte": 20260320}},
        "ts_code": 1,
        "close": {"$gt": 50}
    ).sort("ts_code", 1).limit(100)
    )
    
    log.info(f"找到 {len(codes)} 只需要修复的股票")
    
    for i, ts_code in enumerate(codes):
        code, suffix = ts_code.split(".")
        
        if suffix == "SH":
            symbol = f"sh{code}"
        elif suffix == "SZ":
            symbol = f"sz{code}"
        else:
            continue  # 跳过北交所
        
        try:
            # 用AKShare拉取真实价数据
            df = ak.stock_zh_a_daily(
                symbol=symbol,
                start_date=str(start_date),
                end_date=str(end_date),
                adjust=""  # 不复权
            )
            
            if df.empty:
                continue
            
            # 更新close/open/high/low/pct_chg字段
            updates = []
            for idx, row in df.iterrows():
                d = row["date"]
                td = int(f"{d.year:04d}{d.month:02d}{d.day:02d}")
                close = round(float(row["close"]), 2)
                
                # 计算pre_close和pct_chg（用当前行的前一日close）
                if idx > 0:
                    prev_close = round(float(df.iloc[idx-1]["close"]), 2)
                else:
                    # 第一天用open近似
                    prev_close = round(float(row["open"]), 2)
                
                pct_chg = round((close - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0.0
                
                updates.append(UpdateOne(
                    {"ts_code": ts_code, "trade_date": td},
                    {"$set": {
                        "open": round(float(row["open"]), 2),
                        "high": round(float(row["high"]), 2),
                        "low": round(float(row["low"]), 2),
                        "close": close,
                        "pct_chg": pct_chg,
                    }}
                ))
            
            if updates:
                result = db.stock_daily_ak_full.bulk_write(updates, ordered=False)
                total_updated += result.modified_count
                if result.modified_count > 0:
                    log.info(f"  {ts_code}: {result.modified_count}条已更新")
            
        except Exception as e:
            total_failed += 1
            log.warning(f"  {ts_code}: {e}")
        
        time.sleep(0.1)
        if (i + 1) % 50 == 0:
            log.info(f"  进度: {i+1}/{len(codes)}, 更新={total_updated} 失败={total_failed}")
    
    log.info(f"修复完成: 更新={total_updated}条, 失败={total_failed}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=20251008)
    parser.add_argument("--end", type=int, default=20260320)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="限制处理股票数")
    args = parser.parse_args()
    
    db = MongoClient(MONGO_URI)[DB_NAME]
    
    log.info(f"开始修复: {args.start}~{args.end}")
    if args.limit > 0:
        log.info(f"限制: 只处理前{args.limit}只股票")
    
    fix_qfq_with_akshare(db, args.start, args.end)
