#!/usr/bin/env python3
"""
分析每个过滤步骤，找出为什么选不出股票
"""
import pymongo
import pandas as pd
import numpy as np

# 连接 MongoDB
client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']

def analyze_first_few_dates():
    """分析前几个交易日"""
    
    # 获取前几个交易日
    dates_cursor = db.stock_daily_ak.distinct("trade_date", {})
    dates = sorted(dates_cursor)
    
    print(f"总交易日数: {len(dates)}")
    print(f"日期范围: {dates[0]} ~ {dates[-1]}")
    
    # 分析前10个交易日
    for i, today_int in enumerate(dates[:20]):
        today_str = str(today_int)
        
        # 找到前一日
        prev_dates = [d for d in dates if d < today_int]
        if not prev_dates:
            continue
            
        prev_int = max(prev_dates)
        prev_str = str(prev_int)
        
        print(f"\n{'='*60}")
        print(f"📅 交易日 {i+1}: {today_str}")
        print(f"📆 前一日: {prev_str}")
        print(f"{'='*60}")
        
        # 步骤1: 获取昨日所有股票
        prev_docs = list(db.stock_daily_ak.find(
            {"trade_date": prev_int},
            {"ts_code": 1, "close": 1, "up_limit": 1}
        ))
        
        print(f"1️⃣ 昨日股票总数: {len(prev_docs)}")
        
        # 步骤2: 计算哪些股票昨日涨停
        limit_up_count = 0
        limit_up_stocks = []
        for doc in prev_docs:
            close = doc.get("close", 0)
            up_limit = doc.get("up_limit", 0)
            if up_limit > 0 and close >= up_limit * 0.998:
                limit_up_count += 1
                limit_up_stocks.append(doc["ts_code"])
        
        print(f"2️⃣ 昨日涨停股票数: {limit_up_count}")
        
        if limit_up_count == 0:
            print("   🚫 昨日没有涨停股票 → 策略空仓")
            continue
        
        # 步骤3: 检查这些股票今日开盘价
        today_docs = list(db.stock_daily_ak.find(
            {"trade_date": today_int, "ts_code": {"$in": limit_up_stocks}},
            {"ts_code": 1, "open": 1, "up_limit": 1}
        ))
        
        print(f"3️⃣ 今日有数据的涨停股票数: {len(today_docs)}")
        
        if not today_docs:
            print("   🚫 今日没有涨停股票数据 → 可能停牌")
            continue
        
        # 构建字典方便查找
        prev_data = {doc["ts_code"]: doc for doc in prev_docs}
        today_data = {doc["ts_code"]: doc for doc in today_docs}
        
        # 步骤4: 检查条件: 今日开盘价 < 昨日涨停价
        selected = []
        for ts_code in limit_up_stocks:
            if ts_code in prev_data and ts_code in today_data:
                prev_close = prev_data[ts_code].get("close", 0)
                prev_up_limit = prev_data[ts_code].get("up_limit", 0)
                today_open = today_data[ts_code].get("open", 0)
                
                # 确认昨日确实涨停
                if prev_close >= prev_up_limit * 0.998:
                    # 检查今日开盘价 < 昨日涨停价
                    if today_open < prev_up_limit:
                        selected.append(ts_code)
        
        print(f"4️⃣ 满足条件的股票数: {len(selected)}")
        
        if selected:
            print(f"   ✅ 选中股票: {selected[:5]}")
            
            # 展示第一个选中股票的详细数据
            sample = selected[0]
            print(f"\n   🔍 示例股票 {sample}:")
            print(f"      昨日收盘价: {prev_data[sample].get('close')}")
            print(f"      昨日涨停价: {prev_data[sample].get('up_limit')}")
            print(f"      今日开盘价: {today_data[sample].get('open')}")
            print(f"      差价（涨停价 - 开盘价）: {prev_data[sample].get('up_limit') - today_data[sample].get('open')}")
        else:
            print("   🚫 没有股票满足条件")
            
            # 分析为什么不满足
            if limit_up_stocks:
                sample = limit_up_stocks[0]
                if sample in prev_data and sample in today_data:
                    print(f"\n   🔍 示例股票 {sample} 为什么不满足:")
                    print(f"      昨日收盘价: {prev_data[sample].get('close')}")
                    print(f"      昨日涨停价: {prev_data[sample].get('up_limit')}")
                    print(f"      今日开盘价: {today_data[sample].get('open')}")
                    
                    diff = today_data[sample].get('open', 0) - prev_data[sample].get('up_limit', 0)
                    if diff >= 0:
                        print(f"      ❌ 今日开盘价 >= 昨日涨停价 (差: {diff:.2f})")
                        print(f"          开盘就涨停或高开，不满足策略条件")
                    else:
                        print(f"      ⚠️ 今日开盘价 < 昨日涨停价 (差: {diff:.2f})")
                        print(f"          满足价格条件，但可能被其他条件过滤")
        
        print(f"\n📊 总结: {limit_up_count} 只涨停 → {len(selected)} 只满足条件")

if __name__ == "__main__":
    print("🔍 StockAgent 策略过滤步骤详细分析")
    print("分析每个交易日从基础股票池到最终选股的每一步")
    print("="*60)
    
    analyze_first_few_dates()