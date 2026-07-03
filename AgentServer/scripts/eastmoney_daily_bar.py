#!/usr/bin/env python3
"""
东方财富全市场快照 → stock_daily_ak_full 补当日OHLCV

用stock_zh_a_spot_em字段: 最新价/开盘/最高/最低/成交量/成交额/涨跌幅/昨收
写入stock_daily_ak_full集合(与AKShare collector格式一致)

用法: python3 eastmoney_daily_bar.py [--date 20260507]
"""
import requests
import time
import sys
import os
from datetime import datetime
from pymongo import MongoClient, UpdateOne

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "stock_agent"

# 东方财富字段:
# f2=最新价 f3=涨跌幅 f4=涨跌额 f5=成交量(手) f6=成交额
# f7=振幅 f8=换手率 f9=PE f10=量比
# f12=代码 f14=名称 f15=最高 f16=最低 f17=开盘 f18=昨收
# f20=总市值 f21=流通市值 f23=PB

def code_to_ts_code(code_str):
    code = str(code_str).zfill(6)
    if code.startswith(('6', '9')):
        return f"{code}.SH"
    elif code.startswith(('8', '4')):
        return f"{code}.BJ"
    else:
        return f"{code}.SZ"

def safe_float(v, default=None):
    if v is None or v == '-' or v == '':
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default

def fetch_all():
    """从东方财富push2拉全市场数据，失败时回退push2delay→AKShare spot"""
    all_data = []
    
    # === 方案1: 东方财富push2 (盘中实时, 盘后不可用) ===
    try:
        for pn in range(1, 60):
            url = 'https://push2.eastmoney.com/api/qt/clist/get'
            params = {
                'pn': pn, 'pz': 200, 'po': 1, 'np': 1,
                'fltt': 2, 'invt': 2, 'fid': 'f3',
                'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048',
                'fields': 'f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f14,f15,f16,f17,f18,f20,f21,f23,f115'
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
    
    # === 方案2: 东方财富push2delay (盘后可用, 15秒延迟, 有量比) ===
    try:
        for pn in range(1, 60):
            url = 'https://push2delay.eastmoney.com/api/qt/clist/get'
            params = {
                'pn': pn, 'pz': 200, 'po': 1, 'np': 1,
                'fltt': 2, 'invt': 2, 'fid': 'f3',
                'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048',
                'fields': 'f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f14,f15,f16,f17,f18,f20,f21,f23,f115'
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
        print(f"push2delay也失败({e}), 尝试AKShare回退...")
    
    # === 方案3: AKShare stock_zh_a_spot (盘后可用, 无PE/PB但有OHLCV) ===
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot()
        print(f"AKShare spot回退: 获取{len(df)}只")
        for _, row in df.iterrows():
            all_data.append({
                'f12': str(row.get('代码', '')),
                'f14': row.get('名称', ''),
                'f2': row.get('最新价'),
                'f3': row.get('涨跌幅'),
                'f4': row.get('涨跌额'),
                'f5': row.get('成交量'),  # 股
                'f6': row.get('成交额'),  # 元
                'f8': row.get('换手率'),
                'f10': row.get('量比'),
                'f15': row.get('最高'),
                'f16': row.get('最低'),
                'f17': row.get('今开'),
                'f18': row.get('昨收'),
            })
        return all_data
    except Exception as e2:
        print(f"AKShare也失败({e2}), 无法获取数据")
        return []

def write_daily_bar(trade_date=None):
    db = MongoClient(MONGO_URI)[DB_NAME]
    
    if trade_date is None:
        trade_date = int(datetime.now().strftime("%Y%m%d"))
    
    t0 = time.time()
    all_data = fetch_all()
    print(f"拉取 {len(all_data)} 只, 耗时 {time.time()-t0:.1f}s")
    
    # 检查已有
    existing = db.stock_daily_ak_full.count_documents({"trade_date": trade_date})
    if existing > 100:
        # 已有数据跳过
        pass
    
    updates = []
    for item in all_data:
        code = item.get('f12', '')
        if not code:
            continue
        ts_code = code_to_ts_code(code)
        name = item.get('f14', '')
        
        open_price = safe_float(item.get('f17'))
        high = safe_float(item.get('f15'))
        low = safe_float(item.get('f16'))
        close = safe_float(item.get('f2'))
        pre_close = safe_float(item.get('f18'))
        pct_chg = safe_float(item.get('f3'))
        vol_hand = safe_float(item.get('f5'), 0)  # 手
        amount = safe_float(item.get('f6'), 0)     # 元
        amplitude = safe_float(item.get('f7'))      # 振幅%
        turnover_rate = safe_float(item.get('f8'))  # 换手率%
        volume_ratio = safe_float(item.get('f10'))  # 量比
        circ_mv = safe_float(item.get('f21'))       # 流通市值(元)
        
        # AKShare spot返回的vol是股, push2返回的是手
        # 统一: push2delay和push2返回手, AKShare spot返回股
        # 通过判断来源决定转换
        # push2/push2delay的f5已经是手, AKShare spot的f5是股需要÷100
        # 简单处理: 如果vol>1e8可能是股(大成交量), ÷100转手
        # 更可靠: AKShare spot无f7(振幅)和f9(PE), 用这个判断
        is_akshare = 'f7' not in item and 'f9' not in item
        if is_akshare:
            vol_hand = vol_hand / 100  # 股→手
        
        # 成交量: 手 → 股 (MongoDB标准单位)
        vol = int(vol_hand * 100) if vol_hand else 0
        
        # 流通市值: 元 → 万元 (stock_daily_ak_full的单位)
        circ_mv_wan = round(circ_mv / 1e4, 2) if circ_mv and circ_mv > 0 else 0
        
        # 涨跌判断
        # 【v2.9.76修复】阈值从9.9/19.9/29.9改为9.8/19.8/29.8
        # 原因: 有些涨停股pct_chg=9.8x%(四舍五入未到9.9%), 被遗漏
        # 如000068.SZ pct_chg=9.8765%实际是涨停
        is_limit_up = 0
        is_limit_down = 0
        if pre_close and pre_close > 0:
            pct = pct_chg if pct_chg is not None else 0
            if code.startswith(('300', '301')) or code.startswith('688'):
                if pct >= 19.8: is_limit_up = 1
                if pct <= -19.8: is_limit_down = 1
            elif code.startswith(('8', '4')):
                if pct >= 29.8: is_limit_up = 1
                if pct <= -29.8: is_limit_down = 1
            else:
                if pct >= 9.8: is_limit_up = 1
                if pct <= -9.8: is_limit_down = 1
        
        doc = {
            "ts_code": ts_code,
            "trade_date": trade_date,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "pre_close": pre_close,
            "pct_chg": pct_chg,
            "vol": vol,
            "amount": amount,
            "turnover_rate": turnover_rate,
            "volume_ratio": volume_ratio,
            "circ_mv": circ_mv_wan,
            "is_limit_up": is_limit_up,
            "is_limit_down": is_limit_down,
            "amplitude": amplitude,
        }
        
        updates.append(
            UpdateOne(
                {"ts_code": ts_code, "trade_date": trade_date},
                {"$set": doc},
                upsert=True,
            )
        )
    
    if updates:
        # 【数据完整性校验】写入前检查关键字段单位是否正确
        sample = updates[0]  # 取第一条检查
        doc = sample._doc if hasattr(sample, '_doc') else {}
        # UpdateOne的filter/update结构
        if hasattr(sample, '_doc') and '$set' in sample._doc:
            check = sample._doc['$set']
        elif isinstance(doc, dict) and '$set' in doc:
            check = doc['$set']
        else:
            check = {}
        
        tr = check.get('turnover_rate', 0)
        if tr and tr > 100:
            print(f"⚠️ 警告: turnover_rate={tr}% >100%! 可能被×100了, 跳过写入!")
            print(f"  标准单位: 百分数(如5.31表示5.31%), 不是531")
            return
        
        circ = check.get('circ_mv', 0)
        if circ and circ > 0:
            # 用大盘股做参照: 工商银行流通市值约1.9万亿=190000000万元
            # 如果circ_mv<10000(=1亿万元), 大概率是亿元或百万元单位
            # 但小盘股确实可能<1亿, 所以用600519.SH(茅台)做参照
            # 茅台流通市值约1.5万亿=150000000万元, 如果circ_mv<1e6且是主板票, 异常
            # 简单规则: circ_mv<100(万元=100万)肯定是错的
            if circ < 100:
                print(f"⚠️ 警告: circ_mv={circ}万元 <100万! 单位明显错误, 跳过写入!")
                return
        
        t1 = time.time()
        result = db.stock_daily_ak_full.bulk_write(updates, ordered=False)
        print(f"写入 {result.upserted_count + result.modified_count} 条, 耗时 {time.time()-t1:.1f}s")
    
    # 验证
    total = db.stock_daily_ak_full.count_documents({"trade_date": trade_date})
    print(f"\nstock_daily_ak_full {trade_date}: {total}只")
    
    # 看看之前的日期对比
    sample_old = db.stock_daily_ak_full.find_one({"trade_date": 20260506, "ts_code": "000001.SZ"})
    sample_new = db.stock_daily_ak_full.find_one({"trade_date": trade_date, "ts_code": "000001.SZ"})
    if sample_old:
        print(f"旧(5/6): open={sample_old.get('open')} high={sample_old.get('high')} low={sample_old.get('low')} close={sample_old.get('close')} vol={sample_old.get('vol')} amount={sample_old.get('amount')}")
    if sample_new:
        print(f"新({trade_date}): open={sample_new.get('open')} high={sample_new.get('high')} low={sample_new.get('low')} close={sample_new.get('close')} vol={sample_new.get('vol')} amount={sample_new.get('amount')}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=int, default=None, help="日期yyyymmdd，默认今天")
    args = parser.parse_args()
    write_daily_bar(args.date)
