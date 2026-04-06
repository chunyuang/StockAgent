#!/usr/bin/env python3
import pymongo
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# 连接MongoDB
client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client["stock_agent"]
collection = db["stock_daily"]

# 获取所有交易日（2026-01-01 ~ 2026-03-31）
all_dates = sorted(collection.distinct("trade_date", {"trade_date": {"$gte": 20260101, "$lte": 20260331}}))
print(f"共获取到 {len(all_dates)} 个交易日需要计算因子")

# 按股票分组处理
all_ts_codes = collection.distinct("ts_code", {"trade_date": {"$gte": 20260101, "$lte": 20260331}})
print(f"共 {len(all_ts_codes)} 只股票需要处理")

processed = 0
for ts_code in all_ts_codes:
    # 获取该股票的所有日K数据
    data = list(collection.find(
        {"ts_code": ts_code, "trade_date": {"$gte": 20260101, "$lte": 20260331}},
        {"trade_date": 1, "close": 1, "high": 1, "low": 1, "pre_close": 1, "vol": 1, "amount": 1, "pct_chg": 1}
    ).sort("trade_date", 1))
    
    if len(data) < 10:
        continue  # 数据不足跳过
    
    df = pd.DataFrame(data)
    df = df.sort_values("trade_date").reset_index(drop=True)
    
    # 计算涨停判断（涨幅>=9.8%算涨停）
    df["is_limit_up"] = df["pct_chg"] >= 9.8
    
    # 计算first_limit_up：当日涨停且昨日未涨停
    df["first_limit_up"] = ((df["is_limit_up"]) & (~df["is_limit_up"].shift(1).fillna(False))).astype(int)
    
    # 计算limit_up_yesterday：昨日是否涨停
    df["limit_up_yesterday"] = df["is_limit_up"].shift(1).fillna(False).astype(int)
    
    # 计算limit_up_count：连续涨停天数
    df["limit_up_count"] = df.groupby((~df["is_limit_up"]).cumsum()).cumcount() + 1
    df.loc[~df["is_limit_up"], "limit_up_count"] = 0
    
    # 计算量比：当日成交量/过去5日平均成交量
    df["volume_ratio"] = df["vol"] / df["vol"].rolling(5).mean().shift(1)
    
    # 计算振幅
    df["amplitude"] = (df["high"] - df["low"]) / df["pre_close"] * 100
    
    # 计算market_leader：连板>=3且当日成交额>5亿的股票
    df["market_leader"] = ((df["limit_up_count"] >= 3) & (df["amount"] > 50000)).astype(int)
    
    # 批量更新到数据库
    for _, row in df.iterrows():
        update_data = {
            "first_limit_up": int(row["first_limit_up"]),
            "limit_up_yesterday": int(row["limit_up_yesterday"]),
            "limit_up_count": int(row["limit_up_count"]),
            "volume_ratio": float(row["volume_ratio"]) if not pd.isna(row["volume_ratio"]) else 0,
            "amplitude": float(row["amplitude"]) if not pd.isna(row["amplitude"]) else 0,
            "market_leader": int(row["market_leader"])
        }
        
        collection.update_one(
            {"ts_code": ts_code, "trade_date": row["trade_date"]},
            {"$set": update_data}
        )
    
    processed += 1
    if processed % 100 == 0:
        print(f"已处理 {processed}/{len(all_ts_codes)} 只股票")

print("✅ 所有因子计算完成！")

# 验证计算结果
sample = collection.find_one({"first_limit_up": 1, "trade_date": 20260105})
if sample:
    print(f"\n验证：20260105有first_limit_up=1的股票：{sample['ts_code']}")
    print(f"因子值：first_limit_up={sample['first_limit_up']}, limit_up_count={sample['limit_up_count']}, volume_ratio={sample['volume_ratio']:.2f}")
else:
    print("\n验证：未查询到first_limit_up=1的股票")
