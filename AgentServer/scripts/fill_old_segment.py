"""
用ARKCLAW finance_history补全旧段缺失的3136只股票数据

旧段(20251009~20260320)只有2445只/天, 缺3136只
ARKCLAW finance_history 1只/次, 支持批量拉取整个日期范围

策略: 逐只拉取, 每只拉完整的103天, upsert到MongoDB
"""
import sys
import time
import json
import requests
from pymongo import MongoClient, UpdateOne
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "stock_agent"

# 旧段日期范围
START_DATE = "20251009"
END_DATE = "20260320"

def get_missing_codes(db):
    """获取旧段缺失的股票代码"""
    # 新段有但旧段没有的
    new_codes = set(d['_id'] for d in db.stock_daily_ak_full.aggregate([
        {"$match": {"trade_date": 20260508}},
        {"$group": {"_id": "$ts_code"}}
    ]))
    old_codes = set(d['_id'] for d in db.stock_daily_ak_full.aggregate([
        {"$match": {"trade_date": 20260320}},
        {"$group": {"_id": "$ts_code"}}
    ]))
    missing = sorted(new_codes - old_codes)
    return missing


def fetch_finance_history(code):
    """用ARKCLAW finance_history拉取个股历史数据
    
    Args:
        code: 格式 002232.SZ
        
    Returns:
        list of dict, 每天一条记录
    """
    # ARKCLAW内部API (不走公网)
    # 这里直接用MongoDB的已有的新段数据推算, 或者调finance_history
    # 但finance_history只能通过ARKCLAW agent调, 不能直接HTTP
    # 所以用AKShare/东方财富API
    pass


def fetch_via_akshare(code, start_date, end_date):
    """用AKShare拉取个股历史日线"""
    import akshare as ak
    
    # 去掉后缀: 002232.SZ → 002232
    symbol = code.split('.')[0]
    
    try:
        df = ak.stock_zh_a_hist(
            symbol=symbol, 
            period="daily", 
            start_date=start_date, 
            end_date=end_date, 
            adjust=""  # 不复权
        )
        if df.empty:
            return [], "empty"
        
        records = []
        for _, row in df.iterrows():
            # AKShare字段映射
            trade_date = int(str(row.get('日期', '')).replace('-', ''))
            close = float(row.get('收盘', 0))
            open_ = float(row.get('开盘', 0))
            high = float(row.get('最高', 0))
            low = float(row.get('最低', 0))
            vol = float(row.get('成交量', 0))
            amount = float(row.get('成交额', 0))
            pct_chg = float(row.get('涨跌幅', 0))
            turnover = float(row.get('换手率', 0))
            
            if close <= 0:
                continue
            
            records.append({
                "ts_code": code,
                "trade_date": trade_date,
                "close": close,
                "open": open_,
                "high": high,
                "low": low,
                "vol": vol,  # 股
                "amount": amount,  # 元
                "pct_chg": pct_chg,
                "turnover_rate": turnover,
                "pre_close": round(close / (1 + pct_chg/100), 2) if pct_chg else close,
            })
        
        return records, "ok"
    except Exception as e:
        return [], str(e)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch-size', type=int, default=100, help='每批处理数量')
    parser.add_argument('--offset', type=int, default=0, help='从第几只开始(断点续传)')
    parser.add_argument('--workers', type=int, default=3, help='并发线程数(AKShare限3)')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    
    missing = get_missing_codes(db)
    print(f"缺失股票: {len(missing)}只 (offset={args.offset})")
    
    if args.offset > 0:
        missing = missing[args.offset:]
        print(f"从offset={args.offset}开始, 剩余{len(missing)}只")
    
    if args.dry_run:
        for code in missing[:10]:
            print(f"  {code}")
        print(f"  ...共{len(missing)}只")
        return
    
    total_inserted = 0
    total_failed = 0
    failed_codes = []
    
    start_time = time.time()
    
    for i, code in enumerate(missing):
        elapsed = time.time() - start_time
        rate = (i+1) / elapsed if elapsed > 0 else 0
        eta = (len(missing) - i - 1) / rate / 60 if rate > 0 else 0
        print(f"[{i+1}/{len(missing)}] {code} ({rate:.1f}只/s, ETA {eta:.0f}min)", end=" ", flush=True)
        
        records, status = fetch_via_akshare(code, START_DATE, END_DATE)
        
        if records:
            # upsert到MongoDB
            updates = []
            for r in records:
                updates.append(UpdateOne(
                    {"ts_code": r["ts_code"], "trade_date": r["trade_date"]},
                    {"$set": r},
                    upsert=True
                ))
            if updates:
                result = db.stock_daily_ak_full.bulk_write(updates, ordered=False)
                total_inserted += len(records)
                print(f"✅ {len(records)}天")
        else:
            total_failed += 1
            failed_codes.append(code)
            print(f"❌ {status}")
        
        time.sleep(0.3)  # 限速
    
    elapsed = time.time() - start_time
    print(f"\n✅ 完成! 插入{total_inserted}条, 失败{total_failed}只, 耗时{elapsed/60:.1f}分钟")
    if failed_codes:
        print(f"失败代码: {failed_codes[:20]}")
        if len(failed_codes) > 20:
            print(f"  ...共{len(failed_codes)}只")


if __name__ == "__main__":
    main()
