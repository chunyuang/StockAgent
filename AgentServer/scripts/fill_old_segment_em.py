"""
用东方财富push2his补全旧段缺失的3136只股票日线数据

旧段(20251009~20260320)只有2445只/天, 缺3136只
push2his接口: 每只0.3秒, 3136只≈16分钟

字段格式: 日期,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率
"""
import sys
import time
import argparse
import requests
from pymongo import MongoClient, UpdateOne
from datetime import datetime

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "stock_agent"

START_DATE = 20251009
END_DATE = 20260320


def code_to_secid(ts_code):
    """ts_code → secid (东方财富格式)
    002232.SZ → 0.002232
    600519.SH → 1.600519
    """
    code, suffix = ts_code.split('.')
    market = "1" if suffix == "SH" else "0"
    return f"{market}.{code}"


def get_missing_codes(db):
    """获取旧段缺失的股票代码"""
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


def fetch_kline(secid, start_date, end_date, retries=3):
    """从东方财富push2his拉取历史K线"""
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid,
        "ut": "fa5fd1943c7b386f172d6893dbfba10b",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",   # 日线
        "fqt": "0",     # 不复权
        "beg": str(start_date),
        "end": str(end_date),
        "lmt": "1000",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://quote.eastmoney.com/",
    }
    
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=15)
            data = r.json()
            klines = data.get("data", {}).get("klines", [])
            return klines, "ok"
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2)
            else:
                return [], str(e)


def parse_kline(kline_str, ts_code):
    """解析K线字符串 → MongoDB文档
    
    格式: 日期,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率
    """
    parts = kline_str.split(',')
    if len(parts) < 11:
        return None
    
    try:
        trade_date = int(parts[0].replace('-', ''))
        open_ = float(parts[1])
        close = float(parts[2])
        high = float(parts[3])
        low = float(parts[4])
        vol = float(parts[5])     # 手 → 需要×100
        amount = float(parts[6])  # 元
        amplitude = float(parts[7])  # 振幅%
        pct_chg = float(parts[8])    # 涨跌幅%
        chg = float(parts[9])        # 涨跌额
        turnover = float(parts[10])  # 换手率%
        
        if close <= 0:
            return None
        
        pre_close = round(close - chg, 2) if chg else close
        
        return {
            "ts_code": ts_code,
            "trade_date": trade_date,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "pre_close": pre_close,
            "vol": vol * 100,        # 手→股
            "amount": amount,        # 元
            "pct_chg": pct_chg,
            "turnover_rate": turnover,
            "amplitude": amplitude,
        }
    except (ValueError, IndexError):
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--offset', type=int, default=0, help='从第几只开始(断点续传)')
    parser.add_argument('--limit', type=int, default=0, help='最多处理几只(0=全部)')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    
    missing = get_missing_codes(db)
    print(f"缺失股票: {len(missing)}只")
    
    if args.offset > 0:
        missing = missing[args.offset:]
        print(f"从offset={args.offset}开始, 剩余{len(missing)}只")
    
    if args.limit > 0:
        missing = missing[:args.limit]
        print(f"限制处理{args.limit}只")
    
    if args.dry_run:
        for code in missing[:10]:
            print(f"  {code} → secid={code_to_secid(code)}")
        print(f"  ...共{len(missing)}只")
        return
    
    total_inserted = 0
    total_days = 0
    total_failed = 0
    failed_codes = []
    start_time = time.time()
    
    for i, code in enumerate(missing):
        elapsed = time.time() - start_time
        rate = (i+1) / elapsed if elapsed > 0 else 0
        eta = (len(missing) - i - 1) / rate / 60 if rate > 0 else 0
        print(f"[{i+1}/{len(missing)}] {code} (ETA {eta:.0f}min)", end=" ", flush=True)
        
        secid = code_to_secid(code)
        klines, status = fetch_kline(secid, START_DATE, END_DATE)
        
        if not klines:
            total_failed += 1
            failed_codes.append(code)
            print(f"❌ {status}")
            time.sleep(0.8)
            continue
        
        # 解析并写入MongoDB
        updates = []
        for kline_str in klines:
            doc = parse_kline(kline_str, code)
            if doc and START_DATE <= doc["trade_date"] <= END_DATE:
                updates.append(UpdateOne(
                    {"ts_code": doc["ts_code"], "trade_date": doc["trade_date"]},
                    {"$set": doc},
                    upsert=True
                ))
        
        if updates:
            result = db.stock_daily_ak_full.bulk_write(updates, ordered=False)
            total_inserted += result.upserted_count
            total_days += len(updates)
            print(f"✅ {len(updates)}天")
        else:
            print(f"⚠️ 0天(无有效数据)")
        
        time.sleep(0.8)  # 限速(东方财富防爬)
    
    elapsed = time.time() - start_time
    print(f"\n✅ 完成! 写入{total_days}天{total_inserted}条, 失败{total_failed}只, 耗时{elapsed/60:.1f}分钟")
    if failed_codes:
        with open('/tmp/failed_codes.txt', 'w') as f:
            for c in failed_codes:
                f.write(c + '\n')
        print(f"失败代码已保存到 /tmp/failed_codes.txt ({len(failed_codes)}只)")


if __name__ == "__main__":
    main()
