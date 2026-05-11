#!/usr/bin/env python3
"""
用ARKCLAW finance_history API补5月6-8日OHLCV到stock_daily_ak_full
因为东方财富push2/datacenter/AKShare全部不可用，只能逐只拉

用法: python3 finance_history_supplement.py [--start 2026-05-06] [--end 2026-05-08]
"""
import sys
import os
import time
import json
import requests
from datetime import datetime
from pymongo import MongoClient, UpdateOne

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "stock_agent"

# finance_history API endpoint
FH_URL = "http://localhost:8111/api/v1/knowledge/finance-history/runs"

def code_to_finance_code(ts_code):
    """000001.SZ -> 000001.SZ (同花顺格式)"""
    return ts_code

def finance_code_to_ts_code(code):
    """000001.SZ -> 000001.SZ"""
    return code

def fetch_one(code, start_date, end_date, indicators=None):
    """调用finance_history API获取一只股票数据"""
    if indicators is None:
        indicators = ["open", "close", "high", "low", "volume", "amt", "pct_chg", "pre_close", "turn"]
    
    payload = {
        "codes": code,
        "indicators": indicators,
        "startdate": start_date,
        "enddate": end_date
    }
    
    try:
        r = requests.post(FH_URL, json=payload, timeout=30)
        d = r.json()
        if d.get("errorcode") == 0 and d.get("tables"):
            return d["tables"][0]
    except Exception as e:
        return None
    return None

def table_to_records(table_data, ts_code):
    """将finance_history返回的table转为stock_daily_ak_full记录"""
    records = []
    table = table_data.get("table", {})
    times = table_data.get("time", [])
    
    if not times:
        return records
    
    n = len(times)
    for i in range(n):
        dt_str = times[i]  # "2026-05-06"
        trade_date = int(dt_str.replace("-", ""))
        
        record = {
            "ts_code": ts_code,
            "trade_date": trade_date,
            "open": table.get("open", [None]*n)[i],
            "close": table.get("close", [None]*n)[i],
            "high": table.get("high", [None]*n)[i],
            "low": table.get("low", [None]*n)[i],
            "volume": table.get("volume", [None]*n)[i],
            "amount": table.get("amt", [None]*n)[i],
            "pct_chg": table.get("pct_chg", [None]*n)[i],
            "pre_close": table.get("pre_close", [None]*n)[i],
            "turnover_rate": table.get("turn", [None]*n)[i],
        }
        # 去掉None值
        record = {k: v for k, v in record.items() if v is not None}
        records.append(record)
    
    return records

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2026-05-06")
    parser.add_argument("--end", default="2026-05-08")
    parser.add_argument("--batch-size", type=int, default=100, help="每N只提交一次MongoDB")
    args = parser.parse_args()
    
    db = MongoClient(MONGO_URI)[DB_NAME]
    coll = db.stock_daily_ak_full
    
    # 获取所有股票代码
    codes = coll.distinct("ts_code", {"trade_date": 20260430})
    print(f"共{len(codes)}只股票需要补数据 ({args.start} ~ {args.end})")
    
    # 检查已补的
    start_dt = int(args.start.replace("-", ""))
    end_dt = int(args.end.replace("-", ""))
    existing = set()
    for dt in range(start_dt, end_dt + 1):
        if dt in existing:
            continue
        done = coll.distinct("ts_code", {"trade_date": dt})
        if len(done) > 100:
            existing.update(done)
            print(f"  {dt}: 已有{len(done)}只")
    
    codes_to_fetch = [c for c in codes if c not in existing]
    print(f"  需补: {len(codes_to_fetch)}只")
    
    if not codes_to_fetch:
        print("无需补数据")
        return
    
    # 逐只拉取
    total_fetched = 0
    total_written = 0
    failed_codes = []
    ops = []
    t0 = time.time()
    
    for idx, code in enumerate(codes_to_fetch):
        table = fetch_one(code, args.start, args.end)
        if table is None:
            failed_codes.append(code)
            if idx % 500 == 0 and idx > 0:
                print(f"  [{idx}/{len(codes_to_fetch)}] {code} 失败, 跳过")
            continue
        
        records = table_to_records(table, code)
        if not records:
            failed_codes.append(code)
            continue
        
        total_fetched += len(records)
        
        for rec in records:
            ops.append(UpdateOne(
                {"ts_code": rec["ts_code"], "trade_date": rec["trade_date"]},
                {"$set": rec},
                upsert=True
            ))
        
        # 批量写入
        if len(ops) >= args.batch_size:
            try:
                result = coll.bulk_write(ops, ordered=False)
                total_written += result.upserted_count + result.modified_count
            except Exception as e:
                print(f"  bulk_write error: {e}")
            ops = []
        
        # 进度
        if (idx + 1) % 500 == 0:
            elapsed = time.time() - t0
            rate = (idx + 1) / elapsed
            eta = (len(codes_to_fetch) - idx - 1) / rate
            print(f"  [{idx+1}/{len(codes_to_fetch)}] 已拉{total_fetched}条, 失败{len(failed_codes)}, "
                  f"速率{rate:.0f}只/s, ETA {eta/60:.1f}min")
    
    # 写入剩余
    if ops:
        try:
            result = coll.bulk_write(ops, ordered=False)
            total_written += result.upserted_count + result.modified_count
        except Exception as e:
            print(f"  bulk_write error: {e}")
    
    elapsed = time.time() - t0
    print(f"\n===== 补数据完成 =====")
    print(f"股票: {len(codes_to_fetch)}只, 成功{len(codes_to_fetch)-len(failed_codes)}只, 失败{len(failed_codes)}只")
    print(f"记录: 拉取{total_fetched}条, 写入{total_written}条")
    print(f"耗时: {elapsed:.1f}s")
    
    # 验证
    for dt in range(start_dt, end_dt + 1):
        # 跳过非交易日(简单判断)
        try:
            d = datetime.strptime(str(dt), "%Y%m%d")
            if d.weekday() >= 5:
                continue
        except:
            continue
        c = coll.count_documents({"trade_date": dt})
        print(f"  {dt}: {c}只")
    
    if failed_codes and len(failed_codes) <= 20:
        print(f"失败代码: {failed_codes}")

if __name__ == "__main__":
    main()
