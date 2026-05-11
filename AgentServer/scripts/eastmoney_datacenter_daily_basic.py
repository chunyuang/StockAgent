#!/usr/bin/env python3
"""
东方财富数据中心 → daily_basic (PE_TTM / PB_MRQ / 流通市值)

周末可用！使用 datacenter-web.eastmoney.com 接口
替代 push2 行情接口(周末不可用)

补全 daily_basic 中缺失的历史数据:
- 1-2月: 每天10只 → 需补到5400+
- 3月: 每天1200只 → 需补到5400+
- 4月: 每天1300只 → 需补到5400+

用法:
  python3 eastmoney_datacenter_daily_basic.py                    # 补所有缺失日期
  python3 eastmoney_datacenter_daily_basic.py --date 20260106    # 补指定日期
  python3 eastmoney_datacenter_daily_basic.py --dry-run          # 只看缺多少
"""

import requests
import time
import sys
import os
from datetime import datetime, timedelta
from pymongo import MongoClient, UpdateOne

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "stock_agent"

# 东方财富数据中心API
DC_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

def get_trade_dates_from_mongo(db):
    """从stock_daily获取所有交易日"""
    dates = db.stock_daily_ak_full.distinct("trade_date")
    return sorted([str(d) for d in dates])


def get_sparse_dates(db):
    """获取daily_basic中股票数<100的日期"""
    pipeline = [
        {"$group": {"_id": "$trade_date", "count": {"$sum": 1}}},
        {"$match": {"count": {"$lt": 100}}},
        {"$sort": {"_id": 1}}
    ]
    sparse = list(db.daily_basic.aggregate(pipeline))
    return [str(doc["_id"]) for doc in sparse]


def fetch_valuation_data(trade_date_str):
    """
    从东方财富数据中心获取全市场估值数据
    
    参数: trade_date_str 格式 "2026-01-06" 或 "20260106"
    返回: list of dicts
    """
    # 统一为 "YYYY-MM-DD" 格式
    if len(trade_date_str) == 8:
        td = f"{trade_date_str[:4]}-{trade_date_str[4:6]}-{trade_date_str[6:8]}"
    else:
        td = trade_date_str
    
    all_data = []
    page = 1
    page_size = 6000
    
    while True:
        params = {
            'reportName': 'RPT_VALUEANALYSIS_DET',
            'columns': 'SECURITY_CODE,SECUCODE,PE_TTM,PB_MRQ,TOTAL_MARKET_CAP,NOTLIMITED_MARKETCAP_A,CLOSE_PRICE,CHANGE_RATE,TOTAL_SHARES,FREE_SHARES_A,TRADE_DATE',
            'filter': f"(TRADE_DATE='{td}')",
            'pageNumber': page,
            'pageSize': page_size,
            'sortColumns': 'SECURITY_CODE',
            'sortTypes': 1,
        }
        
        try:
            r = requests.get(DC_URL, params=params, timeout=15)
            d = r.json()
        except Exception as e:
            print(f"  请求失败: {e}")
            break
        
        if not d.get('result') or not d['result'].get('data'):
            break
        
        data = d['result']['data']
        all_data.extend(data)
        
        count = d['result'].get('count', 0)
        if len(all_data) >= count:
            break
        
        page += 1
        time.sleep(0.1)  # 避免请求过快
    
    return all_data


def code_to_ts_code(code_str):
    """东方财富代码→ts_code格式"""
    code = str(code_str).zfill(6)
    if code.startswith(('6', '9')):
        return f"{code}.SH"
    else:
        return f"{code}.SZ"


def upsert_daily_basic(db, items, trade_date_int):
    """批量写入daily_basic"""
    if not items:
        return 0
    
    operations = []
    for item in items:
        code = item.get('SECURITY_CODE', '')
        ts_code = code_to_ts_code(code)
        
        # 流通市值: FREE_SHARES_A * CLOSE_PRICE (元)
        free_shares = item.get('FREE_SHARES_A')
        close = item.get('CLOSE_PRICE')
        circ_mv = None
        total_mv = None
        if free_shares and close and free_shares > 0 and close > 0:
            circ_mv = round(free_shares * close / 1e8, 4)  # 元→亿元
        
        total_market_cap = item.get('TOTAL_MARKET_CAP')
        if total_market_cap and total_market_cap > 0:
            total_mv = round(total_market_cap / 1e8, 4)  # 元→亿元
        
        doc = {
            "trade_date": trade_date_int,
            "ts_code": ts_code,
            "pe": item.get('PE_TTM'),          # PE(TTM)
            "pe_ttm": item.get('PE_TTM'),      # PE(TTM)
            "pb": item.get('PB_MRQ'),           # PB(MRQ)
            "close": item.get('CLOSE_PRICE'),
            "pct_chg": item.get('CHANGE_RATE'),
            "total_mv": total_mv,               # 总市值(亿元)
            "circ_mv": circ_mv,                 # 流通市值(亿元)
        }
        
        # 过滤掉全空的
        if not any([doc['pe'], doc['pb'], doc['circ_mv'], doc['close']]):
            continue
        
        operations.append(UpdateOne(
            {"trade_date": trade_date_int, "ts_code": ts_code},
            {"$set": doc},
            upsert=True
        ))
    
    if not operations:
        return 0
    
    result = db.daily_basic.bulk_write(operations, ordered=False)
    return result.upserted_count + result.modified_count


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', help='指定日期(20260106)', default=None)
    parser.add_argument('--dry-run', action='store_true', help='只看缺多少')
    parser.add_argument('--delete-sparse', action='store_true', help='先删除稀疏日期的旧数据')
    args = parser.parse_args()
    
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    
    # 获取缺失日期
    if args.date:
        sparse_dates = [args.date]
    else:
        sparse_dates = get_sparse_dates(db)
    
    print(f"=== 东方财富数据中心 → daily_basic ===")
    print(f"缺失日期: {len(sparse_dates)}天")
    
    if args.dry_run:
        for d in sparse_dates:
            cnt = db.daily_basic.count_documents({"trade_date": int(d)})
            print(f"  {d}: {cnt}只")
        return
    
    if not sparse_dates:
        print("无需补全!")
        return
    
    # 可选：先删除稀疏日期的旧数据(每天只有10只的残缺数据)
    if args.delete_sparse:
        deleted = 0
        for d in sparse_dates:
            r = db.daily_basic.delete_many({"trade_date": int(d), "ts_code": {"$exists": True}})
            deleted += r.deleted_count
        print(f"删除旧稀疏数据: {deleted}条")
    
    total_upserted = 0
    total_time = 0
    
    for i, date_str in enumerate(sparse_dates):
        t0 = time.time()
        
        data = fetch_valuation_data(date_str)
        if not data:
            print(f"  [{i+1}/{len(sparse_dates)}] {date_str}: 0只 ❌")
            continue
        
        trade_date_int = int(date_str.replace("-", ""))
        upserted = upsert_daily_basic(db, data, trade_date_int)
        total_upserted += upserted
        
        t1 = time.time()
        total_time += t1 - t0
        print(f"  [{i+1}/{len(sparse_dates)}] {date_str}: {len(data)}只 → upsert {upserted}条 ({t1-t0:.1f}s)")
    
    print(f"\n完成! 补全{total_upserted}条, 总耗时{total_time:.1f}s")
    
    # 验证
    print(f"\n=== 验证 ===")
    for month in ["202601", "202602", "202603", "202604", "202605"]:
        cnt = db.daily_basic.count_documents({"trade_date": {"$regex": f"^{month}"}})
        # 统计该月每天平均只数
        pipeline = [
            {"$match": {"trade_date": {"$regex": f"^{month}"}}},
            {"$group": {"_id": "$trade_date", "count": {"$sum": 1}}},
            {"$group": {"_id": None, "avg": {"$avg": "$count"}, "days": {"$sum": 1}}}
        ]
        result = list(db.daily_basic.aggregate(pipeline))
        if result:
            r = result[0]
            print(f"  {month}: {r['days']}天 × 平均{r['avg']:.0f}只/天")
        else:
            print(f"  {month}: 无数据")


if __name__ == "__main__":
    main()
