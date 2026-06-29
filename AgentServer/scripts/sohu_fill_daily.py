#!/usr/bin/env python3
"""搜狐财经批量补日K线数据

从 q.stock.sohu.com/hisHq 批量拉历史日线,写入 stock_daily_ak_full
每批50只股票,每次请求约0.1秒

用法: python3 sohu_fill_daily.py --date 20260626
"""
import requests
import time
import sys
import json
from pymongo import MongoClient, UpdateOne
from datetime import datetime

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "stock_agent"

def get_all_codes():
    """获取所有A股代码"""
    mc = MongoClient(MONGO_URI)
    db = mc[DB_NAME]
    # 从 stock_daily_ak_full 最近有数据的日期获取股票列表
    latest = db.stock_daily_ak_full.find_one(sort=[("trade_date", -1)])
    if not latest:
        print("无法获取股票列表")
        return []
    
    latest_date = latest["trade_date"]
    codes = db.stock_daily_ak_full.distinct("ts_code", {"trade_date": latest_date})
    print(f"从 {latest_date} 获取 {len(codes)} 只股票代码")
    return codes

def ts_code_to_sohu(ts_code):
    """000001.SZ -> cn_000001, 600000.SH -> cn_600000"""
    code = ts_code.split(".")[0]
    return f"cn_{code}"

def sohu_to_ts_code(sohu_code):
    """cn_000001 -> 000001.SZ (根据代码前缀判断市场)"""
    code = sohu_code.replace("cn_", "")
    if code.startswith(("6", "9")):
        return f"{code}.SH"
    elif code.startswith(("8", "4")):
        return f"{code}.BJ"
    else:
        return f"{code}.SZ"

def fetch_batch(sohu_codes, date_str):
    """批量获取日线数据"""
    code_param = ",".join(sohu_codes)
    url = f"https://q.stock.sohu.com/hisHq"
    params = {
        "code": code_param,
        "start": date_str,
        "end": date_str,
        "stat": "1",
        "order": "A",
        "period": "d",
        "rt": "json"
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        return r.json()
    except Exception as e:
        print(f"  请求失败: {e}")
        return None

def parse_sohu_data(data, trade_date_int):
    """解析搜狐返回数据,返回MongoDB文档列表"""
    docs = []
    if not data or not isinstance(data, list):
        return docs
    
    for item in data:
        if item.get("status") != 0:
            continue
        sohu_code = item.get("code", "")
        ts_code = sohu_to_ts_code(sohu_code)
        hq = item.get("hq", [])
        if not hq:
            continue
        
        row = hq[0]  # [日期, 开盘, 收盘, 涨跌额, 涨跌幅%, 最低, 最高, 成交量(手), 成交额(万), 换手率%]
        if len(row) < 10:
            continue
        
        try:
            open_price = float(row[1]) if row[1] else 0
            close = float(row[2]) if row[2] else 0
            chg = float(row[3]) if row[3] else 0
            pct_chg_str = str(row[4]).replace("%", "").replace("-", "")
            pct_chg = float(row[4].replace("%", "")) if "%" in str(row[4]) else 0
            low = float(row[5]) if row[5] else 0
            high = float(row[6]) if row[6] else 0
            vol = float(row[7]) * 100 if row[7] else 0  # 手 -> 股
            amount = float(row[8]) * 10000 if row[8] else 0  # 万 -> 元
            turn = float(row[9].replace("%", "")) if "%" in str(row[9]) else 0
            
            if close == 0:
                continue
            
            doc = {
                "ts_code": ts_code,
                "trade_date": trade_date_int,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "pct_chg": pct_chg,
                "chg": chg,
                "vol": vol,
                "amount": amount,
                "turn": turn,
                "pre_close": round(close - chg, 2) if chg else 0,
            }
            docs.append(doc)
        except (ValueError, IndexError) as e:
            continue
    
    return docs

def fill_daily(trade_date_str, trade_date_int):
    """补全指定日期的日K线数据"""
    mc = MongoClient(MONGO_URI)
    db = mc[DB_NAME]
    
    # 检查已有数据
    existing = db.stock_daily_ak_full.count_documents({"trade_date": trade_date_int})
    if existing > 5000:
        print(f"已有 {existing} 条数据,跳过")
        return existing
    
    print(f"已有 {existing} 条,开始补采...")
    
    all_codes = get_all_codes()
    if not all_codes:
        return 0
    
    # 转换为搜狐格式
    sohu_codes = [ts_code_to_sohu(c) for c in all_codes]
    
    batch_size = 50
    total_inserted = 0
    total_failed = 0
    
    for i in range(0, len(sohu_codes), batch_size):
        batch = sohu_codes[i:i+batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(sohu_codes) + batch_size - 1) // batch_size
        
        data = fetch_batch(batch, trade_date_str)
        if not data:
            print(f"  批次 {batch_num}/{total_batches}: 请求失败")
            total_failed += len(batch)
            continue
        
        docs = parse_sohu_data(data, trade_date_int)
        if docs:
            ops = [UpdateOne(
                {"ts_code": d["ts_code"], "trade_date": d["trade_date"]},
                {"$set": d},
                upsert=True
            ) for d in docs]
            result = db.stock_daily_ak_full.bulk_write(ops, ordered=False)
            total_inserted += len(docs)
        
        if batch_num % 10 == 0:
            print(f"  批次 {batch_num}/{total_batches}: 累计 {total_inserted} 条")
        
        time.sleep(0.15)  # 限速
    
    print(f"\n完成: 插入/更新 {total_inserted} 条, 失败 {total_failed} 只")
    return total_inserted

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="日期 YYYYMMDD")
    args = parser.parse_args()
    
    date_str = f"{args.date[:4]}-{args.date[4:6]}-{args.date[6:8]}"
    date_int = int(args.date)
    
    print(f"=== 补采 {args.date} ({date_str}) 日K线数据 ===")
    fill_daily(date_str, date_int)
