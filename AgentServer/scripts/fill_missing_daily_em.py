#!/usr/bin/env python3
"""
用东方财富历史K线API补全 stock_daily_ak_full 缺失数据

比AKShare快10x+:
- AKShare: 逐只逐天, ~40000次调用, 预计3小时+
- 东方财富push2his: 逐只全时段, ~3140次调用, 预计15分钟

用法:
  python3 fill_missing_daily_em.py --dry-run    # 只看缺多少
  python3 fill_missing_daily_em.py              # 执行补全
"""

import requests
import time
import sys
import gc
from pymongo import MongoClient, UpdateOne

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "stock_agent"

# 东方财富历史K线API
KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

# 需要补全的日期范围
BEG = "20260415"
END = "20260506"


def ts_code_to_secid(ts_code):
    """ts_code → 东方财富secid (市场代码.股票代码)"""
    code, suffix = ts_code.split(".")
    if suffix == "SH":
        return f"1.{code}"
    elif suffix == "SZ":
        return f"0.{code}"
    elif suffix == "BJ":
        return f"0.{code}"  # BJ用0
    return None


def fetch_kline(secid, beg=BEG, end=END):
    """
    获取单只股票的历史K线数据
    
    返回: list of dicts, 每个dict包含一天的OHLCV数据
    klines格式: "日期,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率"
    """
    params = {
        'secid': secid,
        'fields1': 'f1,f2,f3,f4,f5,f6',
        'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
        'klt': 101,     # 日线
        'fqt': 0,       # 不复权
        'beg': beg,
        'end': end,
    }
    
    try:
        r = requests.get(KLINE_URL, params=params, timeout=10)
        d = r.json()
        klines = d.get('data', {}).get('klines', [])
        return klines
    except Exception as e:
        return None


def parse_kline(kline_str, ts_code):
    """解析K线字符串 → MongoDB文档"""
    parts = kline_str.split(",")
    if len(parts) < 11:
        return None
    
    date_str = parts[0].replace("-", "")  # "2026-04-15" → "20260415"
    
    try:
        open_price = float(parts[1]) if parts[1] != "-" else None
        close_price = float(parts[2]) if parts[2] != "-" else None
        high = float(parts[3]) if parts[3] != "-" else None
        low = float(parts[4]) if parts[4] != "-" else None
        vol = int(float(parts[5])) if parts[5] != "-" else 0
        amount = float(parts[6]) if parts[6] != "-" else 0
        amplitude = float(parts[7]) if parts[7] != "-" else None
        pct_chg = float(parts[8]) if parts[8] != "-" else None
        chg = float(parts[9]) if parts[9] != "-" else None
        turnover_rate = float(parts[10]) if parts[10] != "-" else None
    except (ValueError, IndexError):
        return None
    
    trade_date = int(date_str)
    
    # 涨跌停判断
    code = ts_code.split(".")[0]
    is_limit_up = 0
    is_limit_down = 0
    if pct_chg is not None and close_price and close_price > 0:
        if code.startswith(('300', '301')) or code.startswith('688'):
            if pct_chg >= 19.9: is_limit_up = 1
            if pct_chg <= -19.9: is_limit_down = 1
        elif code.startswith(('8', '4')):
            if pct_chg >= 29.9: is_limit_up = 1
            if pct_chg <= -29.9: is_limit_down = 1
        else:
            if pct_chg >= 9.9: is_limit_up = 1
            if pct_chg <= -9.9: is_limit_down = 1
    
    # pre_close估算
    pre_close = None
    if close_price and chg is not None:
        pre_close = round(close_price - chg, 2)
    
    return {
        "ts_code": ts_code,
        "trade_date": trade_date,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close_price,
        "pre_close": pre_close,
        "pct_chg": pct_chg,
        "vol": vol,
        "amount": amount,
        "turnover_rate": turnover_rate,
        "amplitude": amplitude,
        "is_limit_up": is_limit_up,
        "is_limit_down": is_limit_down,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    col = db["stock_daily_ak_full"]
    
    # 找出缺失的股票
    full_codes = set(col.distinct("ts_code", {"trade_date": 20260508}))
    
    # 找出所有不完整日期
    incomplete_dates = []
    pipeline = [
        {"$group": {"_id": "$trade_date", "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}}
    ]
    for d in col.aggregate(pipeline, allowDiskUse=True):
        if d['_id'] and d['count'] < 5000 and d['_id'] > 20260320:
            incomplete_dates.append(d['_id'])
    
    print(f"=== 东方财富历史K线 → stock_daily_ak_full ===")
    print(f"不完整日期: {len(incomplete_dates)}天")
    print(f"参考完整日(5/8): {len(full_codes)}只")
    
    # 对每个不完整日期找缺失股票
    all_missing = set()
    for dt in incomplete_dates:
        existing = set(col.distinct("ts_code", {"trade_date": dt}))
        missing = full_codes - existing
        all_missing.update(missing)
        if args.dry_run:
            print(f"  {dt}: {len(existing)}只, 缺{len(missing)}只")
    
    missing_sorted = sorted(all_missing)
    print(f"\n总计需补: {len(missing_sorted)}只股票 (×{len(incomplete_dates)}天)")
    
    if args.dry_run:
        # 按交易所分类
        sh = [c for c in missing_sorted if c.endswith('.SH')]
        sz = [c for c in missing_sorted if c.endswith('.SZ')]
        bj = [c for c in missing_sorted if c.endswith('.BJ')]
        print(f"  SH: {len(sh)}, SZ: {len(sz)}, BJ: {len(bj)}")
        return
    
    if not missing_sorted:
        print("无需补全!")
        return
    
    total_upserted = 0
    total_errors = 0
    start_time = time.time()
    
    batch = []
    
    for i, ts_code in enumerate(missing_sorted):
        secid = ts_code_to_secid(ts_code)
        if not secid:
            total_errors += 1
            continue
        
        klines = fetch_kline(secid)
        if klines is None:
            total_errors += 1
            if (i + 1) % 100 == 0:
                print(f"  [{i+1}/{len(missing_sorted)}] {ts_code}: 请求失败")
            time.sleep(0.15)
            continue
        
        for kline_str in klines:
            doc = parse_kline(kline_str, ts_code)
            if doc and doc['trade_date'] in incomplete_dates:
                batch.append(UpdateOne(
                    {"ts_code": ts_code, "trade_date": doc['trade_date']},
                    {"$set": doc},
                    upsert=True
                ))
        
        # 小批量写入
        if len(batch) >= 500:
            try:
                result = col.bulk_write(batch, ordered=False)
                total_upserted += result.upserted_count + result.modified_count
            except Exception as e:
                total_errors += len(batch)
                print(f"  批量写入失败: {e}")
            batch = []
            gc.collect()
        
        # 进度
        if (i + 1) % 200 == 0:
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed
            eta = (len(missing_sorted) - i - 1) / rate / 60
            print(f"  [{i+1}/{len(missing_sorted)}] 已写入{total_upserted}条, 失败{total_errors}, {rate:.0f}只/s, ETA {eta:.1f}min")
        
        time.sleep(0.15)  # ~6-7次/秒, 避免限流
    
    # 写入剩余
    if batch:
        try:
            result = col.bulk_write(batch, ordered=False)
            total_upserted += result.upserted_count + result.modified_count
        except Exception as e:
            total_errors += len(batch)
            print(f"  最后一批写入失败: {e}")
    
    elapsed = time.time() - start_time
    print(f"\n=== 完成 ===")
    print(f"写入: {total_upserted}条")
    print(f"失败: {total_errors}只")
    print(f"耗时: {elapsed/60:.1f}分钟")
    
    # 验证
    print(f"\n=== 验证 ===")
    for dt in incomplete_dates:
        cnt = col.count_documents({"trade_date": dt})
        status = "✅" if cnt >= 5000 else "⚠️"
        print(f"  {dt}: {cnt}只 {status}")


if __name__ == "__main__":
    main()
