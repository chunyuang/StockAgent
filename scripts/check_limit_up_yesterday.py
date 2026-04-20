#!/usr/bin/env python3
import pymongo

# 连接MongoDB
client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client["stock_agent"]
collection = db["stock_daily_ak_full"]

# 检查最近10天的涨停和昨日涨停数据
dates = sorted(collection.distinct("trade_date", {"trade_date": {"$gte": 20260101, "$lte": 20260120}}))
print("="*80)
print("📅 检查最近20天的涨停统计：")
print("="*80)

for date in dates:
    # 统计当日涨停数（pct_chg >=9.8）
    limit_up_today = collection.count_documents({"trade_date": date, "pct_chg": {"$gte": 9.8}})
    
    # 统计昨日涨停字段为1的数量
    limit_up_yesterday_count = collection.count_documents({"trade_date": date, "limit_up_yesterday": 1})
    
    # 统计前一日真实涨停数
    prev_date = dates[dates.index(date)-1] if dates.index(date) > 0 else None
    limit_up_prev_day = 0
    if prev_date:
        limit_up_prev_day = collection.count_documents({"trade_date": prev_date, "pct_chg": {"$gte": 9.8}})
    
    print(f"📅 日期: {date}")
    print(f"   当日涨停数（pct_chg>=9.8）: {limit_up_today}只")
    print(f"   limit_up_yesterday=1数量: {limit_up_yesterday_count}只")
    if prev_date:
        print(f"   前一交易日真实涨停数: {limit_up_prev_day}只")
        if limit_up_yesterday_count == limit_up_prev_day:
            print("   ✅ limit_up_yesterday计算正确")
        else:
            print("   ❌ limit_up_yesterday计算错误，数量不匹配")
    print("-"*60)

# 随机抽取一个有涨停的日期看具体数据
sample_date = None
for date in dates:
    if collection.count_documents({"trade_date": date, "pct_chg": {"$gte": 9.8}}) > 0:
        sample_date = date
        break

if sample_date:
    print(f"\n🔍 抽样检查日期 {sample_date} 的昨日涨停个股：")
    sample_docs = list(collection.find(
        {"trade_date": sample_date, "limit_up_yesterday": 1},
        {"ts_code": 1, "pct_chg": 1, "limit_up_yesterday": 1}
    ).limit(10))
    
    for doc in sample_docs:
        print(f"   {doc['ts_code']}: pct_chg={doc['pct_chg']:.2f}%, limit_up_yesterday={doc['limit_up_yesterday']}")
