#!/usr/bin/env python3
import akshare as ak
import pymongo
from datetime import datetime

client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client["stock_agent"]
collection = db["stock_daily_ak_full"]

print("📋 获取股票列表...")
try:
    stock_list = ak.stock_info_a_code_name()
    stock_codes = stock_list['code'].tolist()[:500]
    print(f"✅ 获取到 {len(stock_codes)} 只股票")
except Exception as e:
    print(f"❌ 获取列表失败: {e}")
    stock_codes = ['000001', '000002', '600519', '300750', '601318']

start_date = "20260101"
end_date = datetime.now().strftime("%Y%m%d")
print(f"📅 下载区间: {start_date} ~ {end_date}")

total_inserted = 0
for i, code in enumerate(stock_codes):
    try:
        df = ak.stock_zh_a_hist(symbol=code, period="daily", 
                                start_date=start_date, end_date=end_date, adjust="")
        if df is None or df.empty:
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
            print(f"✅ {code}: {len(records)} 条记录已插入")
            
    except Exception as e:
        print(f"❌ {code}: 下载失败: {e}")
        continue

print(f"\n🎉 数据下载完成！共插入 {total_inserted} 条记录")
