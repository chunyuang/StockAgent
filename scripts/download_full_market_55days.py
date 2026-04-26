#!/usr/bin/env python3
import akshare as ak
import pymongo

client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client["stock_agent"]
collection = db["stock_daily_ak_full"]

print("=" * 60)
print("📥 全市场A股数据下载（20260105 ~ 20260320）")
print("=" * 60)

print("\n📋 获取股票列表...")
try:
    stock_list = ak.stock_info_a_code_name()
    stock_codes = stock_list['code'].tolist()  # 全市场，不限制数量
    print(f"✅ 获取到 {len(stock_codes)} 只股票（全市场）")
except Exception as e:
    print(f"❌ 获取列表失败: {e}")
    stock_codes = ['000001', '000002', '600519', '300750', '601318']

start_date = "20260105"
end_date = "20260320"
print(f"\n📅 下载区间: {start_date} ~ {end_date}")
print(f"   共 {len(stock_codes)} 只股票需要下载")
print(f"\n⏳ 开始下载...（预计需要 10-20 分钟）\n")

total_inserted = 0
success_count = 0
fail_count = 0

for i, code in enumerate(stock_codes):
    try:
        df = ak.stock_zh_a_hist(symbol=code, period="daily", 
                                start_date=start_date, end_date=end_date, adjust="")
        if df is None or df.empty:
            fail_count += 1
            continue
            
        records = []
        for _, row in df.iterrows():
            record = {
                "ts_code": code + ".SH" if code.startswith('6') else code + ".SZ",
                "trade_date": int(row['日期'].replace('-', '')),
                "open": float(row['开盘']),
                "high": float(row['最高']),
                "low": float(row['最低']),
                "close": float(row['收盘']),
                "vol": float(row['成交量']),
                "amount": float(row['成交额']),
                "pct_chg": float(row['涨跌幅']),
            }
            records.append(record)
        
        if records:
            collection.delete_many({"ts_code": records[0]['ts_code'], 
                                    "trade_date": {"$gte": int(start_date), "$lte": int(end_date)}})
            collection.insert_many(records)
            total_inserted += len(records)
            success_count += 1
            if success_count % 50 == 0:
                print(f"✅ 进度: {success_count}/{len(stock_codes)}, 已插入 {total_inserted} 条记录")
            
    except Exception as e:
        fail_count += 1
        continue

print(f"\n{'=' * 60}")
print(f"🎉 数据下载完成！")
print(f"   成功: {success_count} 只股票")
print(f"   失败: {fail_count} 只股票")
print(f"   总记录: {total_inserted} 条日线数据")
print("=" * 60)
