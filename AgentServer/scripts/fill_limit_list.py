"""
补全limit_list集合中缺失的涨跌停数据

用法: python3 fill_limit_list.py [--start 20251009] [--end 20260508]
"""
import sys
import time
import argparse
from pymongo import MongoClient, UpdateOne
from datetime import datetime

import akshare as ak


def get_missing_dates(db, start=None, end=None):
    """获取缺失涨跌停数据的交易日列表"""
    bar_dates = set(d['_id'] for d in db.stock_daily_ak_full.aggregate([
        {"$group": {"_id": "$trade_date"}}
    ]))
    ll_dates = set(d['_id'] for d in db.limit_list.aggregate([
        {"$group": {"_id": "$trade_date"}}
    ]))
    missing = sorted(bar_dates - ll_dates)
    
    if start:
        missing = [d for d in missing if d >= int(start)]
    if end:
        missing = [d for d in missing if d <= int(end)]
    
    return missing


def fetch_zt_pool(date_str):
    """获取涨停池数据"""
    try:
        df = ak.stock_zt_pool_em(date=date_str)
        return df, "zt"
    except Exception as e:
        if "数据" in str(e) and "不存在" in str(e):
            return None, "no_data"
        return None, f"error: {e}"


def fetch_dt_pool(date_str):
    """获取跌停池数据"""
    try:
        df = ak.stock_zt_pool_dtgc_em(date=date_str)
        return df, "dt"
    except Exception as e:
        if "数据" in str(e) and "不存在" in str(e):
            return None, "no_data"
        return None, f"error: {e}"


def _infer_open_times(ts_code: str, ak_doc: dict) -> int:
    """从ak_full的high/close推算炸板次数(0或1)
    
    如果high触过涨停价但close没封住=炸板(open_times=1)
    否则封板(open_times=0)
    """
    high = ak_doc.get('high', 0)
    pre_close = ak_doc.get('pre_close', 0)
    close_pct = ak_doc.get('pct_chg', 0)
    
    if not high or not pre_close or pre_close <= 0:
        return 0
    
    high_pct = (high - pre_close) / pre_close * 100
    
    if ts_code.startswith(('30', '688')):
        threshold = 20
    elif ts_code.startswith(('8', '4', '920')):
        threshold = 30
    else:
        threshold = 10
    
    # 盘中触涨停但收盘未封=炸板
    if high_pct >= threshold * 0.99 and close_pct < threshold * 0.99:
        return 1
    return 0


def code_to_tscode(code, name=""):
    """6位代码→ts_code格式"""
    if len(code) != 6:
        return None
    if code.startswith(('6', '9')):
        return f"{code}.SH"
    elif code.startswith(('0', '2', '3')):
        return f"{code}.SZ"
    elif code.startswith(('4', '8')):
        return f"{code}.BJ"
    return f"{code}.SZ"  # fallback


def process_zt_df(df, trade_date):
    """处理涨停DataFrame→MongoDB文档"""
    docs = []
    for _, row in df.iterrows():
        code = str(row.get('代码', '')).zfill(6)
        ts_code = code_to_tscode(code)
        if not ts_code:
            continue
        
        first_time = str(row.get('首次封板时间', '')).strip()
        last_time = str(row.get('最后封板时间', '')).strip()
        # 格式化时间: "92500" → "09:25:00"
        if len(first_time) == 5 or len(first_time) == 6:
            ft = first_time.zfill(6)
            first_time = f"{ft[:2]}:{ft[2:4]}:{ft[4:6]}"
        if len(last_time) == 5 or len(last_time) == 6:
            lt = last_time.zfill(6)
            last_time = f"{lt[:2]}:{lt[2:4]}:{lt[4:6]}"
        
        open_times = int(row.get('炸板次数', 0))  # 炸板次数=开板次数
        limit_times = int(row.get('连板数', 1))  # 连板数
        
        # 封单资金(元→万元)
        seal_amount = row.get('封板资金', 0)
        if seal_amount and seal_amount > 1e8:  # 可能是元
            seal_amount = round(seal_amount / 10000, 2)
        
        docs.append({
            "trade_date": trade_date,
            "ts_code": ts_code,
            "name": str(row.get('名称', '')),
            "limit": "U",  # 涨停
            "close": float(row.get('最新价', 0)),
            "amp": float(row.get('涨跌幅', 0)),
            "fc_ratio": float(row.get('换手率', 0)),
            "first_time": first_time,
            "last_time": last_time,
            "open_times": open_times,
            "limit_times": limit_times,
            "seal_amount": seal_amount,  # 封单资金(万元)
            "sector": str(row.get('所属行业', '')),
        })
    return docs


def process_dt_df(df, trade_date):
    """处理跌停DataFrame→MongoDB文档"""
    docs = []
    for _, row in df.iterrows():
        code = str(row.get('代码', '')).zfill(6)
        ts_code = code_to_tscode(code)
        if not ts_code:
            continue
        
        last_time = str(row.get('最后封板时间', '')).strip()
        if len(last_time) == 5 or len(last_time) == 6:
            lt = last_time.zfill(6)
            last_time = f"{lt[:2]}:{lt[2:4]}:{lt[4:6]}"
        
        open_times = int(row.get('开板次数', 0))
        limit_times = int(row.get('连续跌停', 1))
        
        seal_amount = row.get('封单资金', 0)
        if seal_amount and seal_amount > 1e8:
            seal_amount = round(seal_amount / 10000, 2)
        
        docs.append({
            "trade_date": trade_date,
            "ts_code": ts_code,
            "name": str(row.get('名称', '')),
            "limit": "D",  # 跌停
            "close": float(row.get('最新价', 0)),
            "amp": float(row.get('涨跌幅', 0)),
            "fc_ratio": float(row.get('换手率', 0)),
            "first_time": "",
            "last_time": last_time,
            "open_times": open_times,
            "limit_times": limit_times,
            "seal_amount": seal_amount,
            "sector": str(row.get('所属行业', '')),
        })
    return docs


def supplement_bj_from_ak_full(db, start=None, end=None):
    """从ak_full的is_limit_up=1补充北交所/科创板涨停到limit_list
    
    必盈API不覆盖北交所(920xxx/8xxxxx/4xxxxx)，导致limit_list缺这些股票。
    从ak_full的pct_chg+is_limit_up反向补充。
    """
    # 确定日期范围
    pipeline = [{"$match": {"is_limit_up": 1, "ts_code": {"$regex": "^(920|8|4)"}}},
                {"$group": {"_id": "$trade_date"}},
                {"$sort": {"_id": -1}}]
    dates = [d["_id"] for d in db.stock_daily_ak_full.aggregate(pipeline)]
    
    if start:
        dates = [d for d in dates if d >= int(start)]
    if end:
        dates = [d for d in dates if d <= int(end)]
    
    total_added = 0
    for td in sorted(dates):
        # 找ak_full中涨停但limit_list中没有的
        lu_codes = set(d["ts_code"] for d in db.stock_daily_ak_full.find(
            {"trade_date": td, "is_limit_up": 1, "ts_code": {"$regex": "^(920|8|4)"}},
            {"ts_code": 1, "_id": 0}
        ))
        ll_codes = set(d["ts_code"] for d in db.limit_list.find(
            {"trade_date": td, "limit": "U", "ts_code": {"$regex": "^(920|8|4)"}},
            {"ts_code": 1, "_id": 0}
        ))
        missing_codes = lu_codes - ll_codes
        if not missing_codes:
            continue
        
        docs = []
        for code in sorted(missing_codes):
            doc = db.stock_daily_ak_full.find_one(
                {"ts_code": code, "trade_date": td},
                {"pct_chg": 1, "close": 1, "open": 1, "pre_close": 1, "_id": 0}
            )
            if not doc:
                continue
            docs.append({
                "trade_date": td,
                "ts_code": code,
                "name": "",
                "limit": "U",
                "close": doc.get("close", 0),
                "amp": doc.get("pct_chg", 0),
                "fc_ratio": 0,
                "first_time": "",
                "last_time": "",
                "open_times": _infer_open_times(code, doc),
                "limit_times": 1,
                "seal_amount": 0,
                "sector": "北交所" if not code.startswith("688") else "科创板",
                "data_source": "ak_full_supplement",
            })
        
        if docs:
            try:
                db.limit_list.insert_many(docs, ordered=False)
                total_added += len(docs)
                print(f"  {td}: 补充{len(docs)}只北交所涨停")
            except Exception as e:
                # 可能重复插入，跳过
                pass
    
    print(f"\n✅ 北交所涨停补充完成: 共{total_added}条")
    return total_added


def main():
    parser = argparse.ArgumentParser(description='补全limit_list涨跌停数据')
    parser.add_argument('--start', help='起始日期 20251009')
    parser.add_argument('--end', help='结束日期 20260508')
    parser.add_argument('--dry-run', action='store_true', help='只显示缺失,不写入')
    args = parser.parse_args()
    
    client = MongoClient('localhost', 27017)
    db = client.stock_agent
    
    missing = get_missing_dates(db, args.start, args.end)
    print(f"缺失涨跌停数据: {len(missing)}天")
    
    if args.dry_run:
        for d in missing:
            print(f"  {d}")
        return
    
    total_zt = 0
    total_dt = 0
    failed = []
    
    for i, td in enumerate(missing):
        date_str = str(td)
        print(f"[{i+1}/{len(missing)}] {date_str}...", end=" ", flush=True)
        
        zt_count = 0
        dt_count = 0
        
        # 涨停
        zt_df, status = fetch_zt_pool(date_str)
        if zt_df is not None and len(zt_df) > 0:
            docs = process_zt_df(zt_df, td)
            if docs:
                result = db.limit_list.insert_many(docs, ordered=False)
                zt_count = len(docs)
                total_zt += zt_count
        elif "no_data" in str(status):
            pass  # 非交易日或无涨停
        else:
            print(f"zt_error({status})", end=" ")
        
        time.sleep(0.3)  # 避免请求过快
        
        # 跌停
        dt_df, status = fetch_dt_pool(date_str)
        if dt_df is not None and len(dt_df) > 0:
            docs = process_dt_df(dt_df, td)
            if docs:
                result = db.limit_list.insert_many(docs, ordered=False)
                dt_count = len(docs)
                total_dt += dt_count
        elif "no_data" in str(status):
            pass
        else:
            print(f"dt_error({status})", end=" ")
        
        print(f"涨停={zt_count} 跌停={dt_count}")
        time.sleep(0.5)
    
    print(f"\n✅ 完成! 涨停{total_zt}条 跌停{total_dt}条")
    if failed:
        print(f"⚠️ 失败{len(failed)}天: {failed}")
    
    # 补充北交所涨停(必盈API不覆盖)
    print(f"\n=== 补充北交所涨停(ak_full→limit_list) ===")
    supplement_bj_from_ak_full(db, args.start, args.end)


if __name__ == "__main__":
    main()
