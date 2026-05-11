#!/usr/bin/env python3
"""
补全 stock_daily_ak_full 中缺失的 pct_chg 和 pre_close

逻辑:
- pre_close = 前一交易日的 close
- pct_chg = (close - pre_close) / pre_close * 100

对 AKShare 补的数据(4/15~5/6, ~35571条)补充这两个字段

用法: python3 fix_pct_chg.py
"""

import time
from pymongo import MongoClient, UpdateOne

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "stock_agent"

def main():
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    col = db["stock_daily_ak_full"]

    # 获取所有交易日
    pipeline = [
        {"$group": {"_id": "$trade_date"}},
        {"$sort": {"_id": 1}}
    ]
    all_dates = [d["_id"] for d in col.aggregate(pipeline) if d["_id"]]
    date_set = set(all_dates)
    sorted_dates = sorted(all_dates)
    
    # 建立日期→前一交易日的映射
    prev_date_map = {}
    for i, d in enumerate(sorted_dates):
        if i > 0:
            prev_date_map[d] = sorted_dates[i - 1]
    
    print(f"交易日总数: {len(sorted_dates)}")
    
    # 找出所有缺pct_chg的记录
    missing = list(col.find(
        {
            "$or": [
                {"pct_chg": None},
                {"pct_chg": {"$exists": False}},
            ]
        },
        {"ts_code": 1, "trade_date": 1, "close": 1, "_id": 0}
    ).limit(100000))
    
    print(f"缺失pct_chg记录: {len(missing)}条")
    
    if not missing:
        print("无需补全!")
        return
    
    # 批量获取前一交易日close
    # 先按trade_date分组
    by_date = {}
    for rec in missing:
        dt = rec["trade_date"]
        if dt not in by_date:
            by_date[dt] = []
        by_date[dt].append(rec)
    
    # 对每个日期，批量查前日close
    total_fixed = 0
    total_failed = 0
    batch = []
    
    for dt in sorted(by_date.keys()):
        prev_dt = prev_date_map.get(dt)
        if not prev_dt:
            total_failed += len(by_date[dt])
            continue
        
        # 批量获取前日close
        codes_in_date = [r["ts_code"] for r in by_date[dt]]
        prev_closes = {}
        for doc in col.find(
            {"trade_date": prev_dt, "ts_code": {"$in": codes_in_date}},
            {"ts_code": 1, "close": 1, "_id": 0}
        ):
            if doc.get("close"):
                prev_closes[doc["ts_code"]] = doc["close"]
        
        for rec in by_date[dt]:
            ts_code = rec["ts_code"]
            close = rec.get("close")
            pre_close = prev_closes.get(ts_code)
            
            if not close or not pre_close or pre_close <= 0:
                total_failed += 1
                continue
            
            pct_chg = round((close - pre_close) / pre_close * 100, 2)
            
            batch.append(UpdateOne(
                {"ts_code": ts_code, "trade_date": dt},
                {"$set": {"pct_chg": pct_chg, "pre_close": pre_close}}
            ))
            total_fixed += 1
        
        # 批量写入
        if len(batch) >= 2000:
            col.bulk_write(batch, ordered=False)
            batch = []
            print(f"  已处理{total_fixed}条, 失败{total_failed}条")
    
    # 写入剩余
    if batch:
        col.bulk_write(batch, ordered=False)
    
    print(f"\n=== 完成 ===")
    print(f"补全: {total_fixed}条")
    print(f"失败: {total_failed}条")
    
    # 验证
    missing_after = col.count_documents({
        "$or": [{"pct_chg": None}, {"pct_chg": {"$exists": False}}]
    })
    print(f"剩余缺失pct_chg: {missing_after}条")
    
    # 验证样本
    for dt in [20260415, 20260420, 20260506]:
        sample = col.find_one({"trade_date": dt, "ts_code": "603288.SH"})
        if sample:
            print(f"  {dt} 603288.SH: close={sample.get('close')}, pre_close={sample.get('pre_close')}, pct_chg={sample.get('pct_chg')}%")


if __name__ == "__main__":
    main()
