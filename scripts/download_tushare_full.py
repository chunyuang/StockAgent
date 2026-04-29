#!/usr/bin/env python3
import os
import tushare as ts
import pymongo
import asyncio
import time

# 使用系统已有的 Token
TS_TOKEN = os.getenv("TUSHARE_TOKEN", "")
if not TS_TOKEN:
    raise ValueError("请设置环境变量 TUSHARE_TOKEN")
ts.set_token(TS_TOKEN)
pro = ts.pro_api()

client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client["stock_agent"]
collection = db["stock_daily_ak_full"]

print("=" * 60)
print("📥 全市场A股数据下载（20260105 ~ 20260320） via Tushare")
print("=" * 60)

# 1. 获取股票列表
print("\n📋 获取股票列表...")
stock_list = pro.stock_basic(exchange='', list_status='L', fields='ts_code,symbol,name')
print(f"✅ 获取到 {len(stock_list)} 只股票（全市场）")

start_date = "20260105"
end_date = "20260320"
print(f"\n📅 下载区间: {start_date} ~ {end_date}")

# 2. 清空原有测试数据
print("\n🗑️  清空原有测试数据...")
delete_result = collection.delete_many({})
print(f"   已删除 {delete_result.deleted_count} 条旧记录")

# 3. 按日期批量下载（效率更高）
print("\n⏳ 开始下载...（按日期批量获取，预计 2-3 分钟）")
print()

trade_cal = pro.trade_cal(exchange='SSE', start_date=start_date, end_date=end_date, is_open='1')
trade_dates = sorted(trade_cal['cal_date'].tolist())
print(f"📆 共 {len(trade_dates)} 个交易日需要下载")

total_inserted = 0
for i, trade_date in enumerate(trade_dates):
    try:
        # Tushare 限速 200次/分钟
        if i > 0 and i % 100 == 0:
            time.sleep(1)
            
        df = pro.daily(trade_date=trade_date)
        if df is None or df.empty:
            print(f"   {trade_date}: 无数据")
            continue
            
        records = df.to_dict('records')
        
        # 标准化字段名（保持和原有一致）
        for r in records:
            r['pct_chg'] = r.pop('pct_chg', 0)
            r['vol'] = r.pop('vol', 0)
            r['amount'] = r.pop('amount', 0)
            
        collection.insert_many(records)
        total_inserted += len(records)
        print(f"✅ {trade_date}: {len(records)} 只股票已下载 (累计 {total_inserted})")
        
    except Exception as e:
        print(f"❌ {trade_date}: 下载失败: {e}")
        time.sleep(2)
        continue

print(f"\n{'=' * 60}")
print(f"🎉 数据下载完成！")
print(f"   交易日: {len(trade_dates)} 天")
print(f"   总记录: {total_inserted} 条日线数据")
print(f"   股票数: {len(collection.distinct('ts_code'))} 只")
print(f"   日期范围: {min(collection.distinct('trade_date'))} ~ {max(collection.distinct('trade_date'))}")
print("=" * 60)

client.close()
