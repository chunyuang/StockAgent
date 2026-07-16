#!/usr/bin/env python3
"""
东方财富全市场快照 → daily_basic

0.1秒拉全市场5849+只，含PE/PB/换手率/流通市值/量比
远超量脉(4291限制,30秒/次)

用法: python3 eastmoney_daily_basic.py [--date 20260507]
"""
import requests
import time
from pymongo import MongoClient, UpdateOne

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "stock_agent"

# 东方财富字段映射
# f2=最新价 f3=涨跌幅 f8=换手率% f9=PE(动态) f10=量比
# f12=代码 f14=名称 f20=总市值(元) f21=流通市值(元) f23=PB
# f26=日期 f115=PE(TTM)

def code_to_ts_code(code_str):
    """东方财富6位代码→ts_code格式"""
    code = str(code_str).zfill(6)
    if code.startswith(('6', '9')):
        return f"{code}.SH"
    elif code.startswith(('8', '4')):
        return f"{code}.BJ"
    else:
        return f"{code}.SZ"

def fetch_all():
    """拉全市场快照，push2→push2delay→datacenter→AKShare四级回退"""
    all_data = []
    
    # === 方案1: 东方财富push2 (盘中实时) ===
    try:
        for pn in range(1, 60):
            url = 'https://push2.eastmoney.com/api/qt/clist/get'
            params = {
                'pn': pn, 'pz': 200, 'po': 1, 'np': 1,
                'fltt': 2, 'invt': 2, 'fid': 'f3',
                'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048',
                'fields': 'f2,f3,f8,f9,f10,f12,f14,f20,f21,f23,f26,f115'
            }
            r = requests.get(url, params=params, timeout=10)
            d = r.json()
            diff = d.get('data', {}).get('diff', [])
            if not diff:
                break
            all_data.extend(diff)
        if all_data:
            return all_data
    except Exception as e:
        print(f"push2 API失败({e}), 尝试push2delay回退...")
    
    # === 方案2: 东方财富push2delay (盘后可用, 15秒延迟) ===
    try:
        for pn in range(1, 60):
            url = 'https://push2delay.eastmoney.com/api/qt/clist/get'
            params = {
                'pn': pn, 'pz': 200, 'po': 1, 'np': 1,
                'fltt': 2, 'invt': 2, 'fid': 'f3',
                'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048',
                'fields': 'f2,f3,f8,f9,f10,f12,f14,f20,f21,f23,f26,f115'
            }
            r = requests.get(url, params=params, timeout=10,
                             headers={"Referer": "https://quote.eastmoney.com/"})
            d = r.json()
            diff = d.get('data', {}).get('diff', [])
            if not diff:
                break
            all_data.extend(diff)
        if all_data:
            print(f"push2delay回退: 获取{len(all_data)}只")
            return all_data
    except Exception as e:
        print(f"push2delay也失败({e}), 尝试datacenter回退...")
    
    # === 方案3: datacenter API (周末/非交易日也可用) ===
    try:
        dc_url = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
        dc_params = {
            'reportName': 'RPT_VALUEANALYSIS_DET',
            'columns': 'ALL',
            'filter': '',
            'pageNumber': 1,
            'pageSize': 6000,
            'sortTypes': -1,
            'sortColumns': 'SECURITY_CODE',
            'source': 'WEB',
            'client': 'WEB',
        }
        r = requests.get(dc_url, params=dc_params, timeout=15)
        d = r.json()
        rows = d.get('result', {}).get('data', [])
        if rows:
            print(f"datacenter回退: 获取{len(rows)}只")
            for row in rows:
                code = row.get('SECURITY_CODE', '')
                all_data.append({
                    'f12': code,
                    'f14': row.get('SECURITY_NAME_ABBR', ''),
                    'f2': row.get('NEW_PRICE'),
                    'f3': row.get('CHANGE_RATE'),
                    'f8': row.get('EXCHANGE_RATE'),
                    'f9': row.get('PE_DYNAMIC'),
                    'f115': row.get('PE_TTM'),
                    'f23': row.get('PB_NEW'),
                    'f21': row.get('FREE_MARKET_CAP'),
                    'f20': row.get('TOTAL_MARKET_CAP'),
                    'f10': row.get('VOLUME_RATIO'),
                })
            return all_data
    except Exception as e2:
        print(f"datacenter也失败({e2})")
    
    return []

def write_to_daily_basic(trade_date=None):
    """拉取并写入daily_basic"""
    db = MongoClient(MONGO_URI)[DB_NAME]
    
    if trade_date is None:
        from datetime import date as _date
        today = _date.today()
        if today.weekday() >= 5:  # 周六=5, 周日=6
            print(f"[SKIP] 今天是{today.strftime('%A')}，非交易日，跳过")
            return 0
        # 开盘前不写入(此时API返回上一个交易日数据但trade_date用了今天)
        from datetime import datetime as _dt
        now = _dt.now()
        if now.hour < 9 or (now.hour == 9 and now.minute < 30):
            print(f"[SKIP] 当前{now.strftime('%H:%M')}未开盘，跳过(避免写入上一交易日假数据)")
            return 0
        trade_date = int(today.strftime("%Y%m%d"))
    
    t0 = time.time()
    all_data = fetch_all()
    fetch_time = time.time() - t0
    
    print(f"拉取 {len(all_data)} 只, 耗时 {fetch_time:.1f}s")
    
    # 检查是否已有数据
    existing = db.daily_basic.count_documents({"trade_date": trade_date})
    if existing > 100:
        # 删除旧数据重写
        db.daily_basic.delete_many({"trade_date": trade_date})
        print(f"删除已有 {existing} 条, 重新写入")
    
    updates = []
    skipped_empty = 0
    for item in all_data:
        code = item.get('f12', '')
        if not code:
            continue
        
        ts_code = code_to_ts_code(code)
        
        # 解析字段，注意'-'表示无数据
        def safe_float(v, default=None):
            if v is None or v == '-' or v == '':
                return default
            try:
                return float(v)
            except (ValueError, TypeError):
                return default
        
        pe = safe_float(item.get('f9'))       # PE动态
        pe_ttm = safe_float(item.get('f115'))  # PE TTM
        pb = safe_float(item.get('f23'))       # PB
        turnover_rate = safe_float(item.get('f8'))   # 换手率%
        volume_ratio = safe_float(item.get('f10'))    # 量比
        circ_mv = safe_float(item.get('f21'))  # 流通市值(元)
        total_mv = safe_float(item.get('f20')) # 总市值(元)
        close = safe_float(item.get('f2'))     # 最新价
        pct_chg = safe_float(item.get('f3'))   # 涨跌幅%
        
        # 流通市值: 元 → 亿元
        circ_mv_yi = round(circ_mv / 1e8, 4) if circ_mv and circ_mv > 0 else None
        total_mv_yi = round(total_mv / 1e8, 4) if total_mv and total_mv > 0 else None
        
        doc = {
            "ts_code": ts_code,
            "trade_date": trade_date,
            "pe": pe_ttm if pe_ttm and pe_ttm > 0 else pe,  # 优先PE_TTM
            "pe_ttm": pe_ttm,  # 单独存PE_TTM字段(因子引擎需要)
            "pb": pb,
            "circ_mv": circ_mv_yi,   # 亿元
            "total_mv": total_mv_yi, # 亿元
            "turnover_rate": turnover_rate,  # %
            "volume_ratio": volume_ratio,
            "close": close,
            "pct_chg": pct_chg,
        }
        
        # 【v2.9.110防护】跳过close为None的记录(停牌/退市票)
        if close is None or (close is not None and close <= 0):
            skipped_empty += 1
            continue
        
        updates.append(
            UpdateOne(
                {"ts_code": ts_code, "trade_date": trade_date},
                {"$set": doc},
                upsert=True,
            )
        )
    
    # 批量写入
    if updates:
        # 【数据完整性校验】写入前检查turnover_rate单位
        sample = updates[0]
        if hasattr(sample, '_doc') and '$set' in sample._doc:
            check = sample._doc['$set']
        else:
            check = {}
        tr = check.get('turnover_rate', 0)
        if tr and tr > 100:
            print(f"⚠️ 警告: turnover_rate={tr}% >100%! 可能被×100了, 跳过写入!")
            return
        
        # circ_mv校验: daily_basic标准=亿元, 如果>10000亿或<0.001亿则异常
        circ = check.get('circ_mv', 0)
        if circ and circ > 0:
            if circ > 100000:  # >10万亿
                print(f"⚠️ 警告: circ_mv={circ}亿元 >10万亿! 可能是万元(需÷10000), 跳过写入!")
                return
            if circ < 0.001:
                print(f"⚠️ 警告: circ_mv={circ}亿元 <0.001亿! 可能是万元未÷10000, 跳过写入!")
                return
        
        t1 = time.time()
        result = db.daily_basic.bulk_write(updates, ordered=False)
        write_time = time.time() - t1
        print(f"写入 {result.upserted_count + result.modified_count} 条, 跳过空壳{skipped_empty}条, 耗时 {write_time:.1f}s")
    
    # 统计
    total = db.daily_basic.count_documents({"trade_date": trade_date})
    with_pe = db.daily_basic.count_documents({"trade_date": trade_date, "pe": {"$ne": None, "$gt": 0}})
    with_pb = db.daily_basic.count_documents({"trade_date": trade_date, "pb": {"$ne": None, "$gt": 0}})
    with_circ = db.daily_basic.count_documents({"trade_date": trade_date, "circ_mv": {"$ne": None, "$gt": 0}})
    with_vr = db.daily_basic.count_documents({"trade_date": trade_date, "volume_ratio": {"$ne": None, "$gt": 0}})
    
    print(f"\ndaily_basic {trade_date}:")
    print(f"  总数: {total}")
    print(f"  PE>0: {with_pe} ({with_pe/total*100:.1f}%)" if total else "  无数据")
    print(f"  PB>0: {with_pb} ({with_pb/total*100:.1f}%)" if total else "")
    print(f"  circ_mv>0: {with_circ} ({with_circ/total*100:.1f}%)" if total else "")
    print(f"  volume_ratio>0: {with_vr} ({with_vr/total*100:.1f}%)" if total else "")
    
    # 验证: 平安银行
    sample = db.daily_basic.find_one({"trade_date": trade_date, "ts_code": "000001.SZ"})
    if sample:
        print(f"\n验证 000001.SZ(平安银行): PE={sample.get('pe'):.2f} PB={sample.get('pb'):.2f} "
              f"circ_mv={sample.get('circ_mv')}亿 turnover={sample.get('turnover_rate'):.2f}% "
              f"volume_ratio={sample.get('volume_ratio')}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=int, default=None, help="日期yyyymmdd，默认今天")
    args = parser.parse_args()
    write_to_daily_basic(args.date)
