#!/usr/bin/env python3
import pymongo
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# 连接MongoDB
client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client["stock_agent"]
collection = db["stock_daily_ak_full"]

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
        {"trade_date": 1, "open": 1, "close": 1, "high": 1, "low": 1, "pre_close": 1, "vol": 1, "amount": 1, "pct_chg": 1}
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
    
    # 计算open_below_limit：当日开盘价 < 昨日涨停价（昨日收盘价*1.1），用于半路追涨策略
    df["prev_close"] = df["close"].shift(1)
    df["limit_up_price_yesterday"] = df["prev_close"] * 1.1
    df["open_below_limit"] = ((df["open"] < df["limit_up_price_yesterday"]) & (df["limit_up_yesterday"] == 1)).astype(int)
    
    # 计算open_above_limit：当日开盘价 > 昨日跌停价（昨日收盘价*0.9），用于跌停翘板策略
    df["limit_down_price_yesterday"] = df["prev_close"] * 0.9
    df["open_above_limit"] = ((df["open"] > df["limit_down_price_yesterday"]) & (df["pct_chg"].shift(1) <= -9.8)).astype(int)
    
    # 计算limit_up_open_amount：涨停开板成交金额，简化为当日成交额（如果是涨停开板）
    df["limit_up_open_amount"] = df.apply(
        lambda x: x["amount"] if (x["high"] == x["limit_up_price_yesterday"] and x["low"] < x["limit_up_price_yesterday"]) else 0, axis=1
    )
    
    # 计算limit_up_open_count：涨停开板次数，简化计算：开板则次数=1，否则0
    df["limit_up_open_count"] = ((df["high"] == df["limit_up_price_yesterday"]) & (df["low"] < df["limit_up_price_yesterday"])).astype(int)
    
    # 计算hot_sector：热门板块标记，简化计算：统一标记为1（后续可接入板块数据优化）
    df["hot_sector"] = 1
    
    # 计算limit_up_time：涨停时间，简化计算：首板标记为930，连板标记为1000
    df["limit_up_time"] = df.apply(lambda x: 930 if x["first_limit_up"] == 1 else 1000, axis=1)
    
    # 计算limit_up_open_duration：开板时长，简化计算：开板则为5分钟，否则0
    df["limit_up_open_duration"] = df.apply(lambda x: 5 if x["limit_up_open_count"] >= 1 else 0, axis=1)
    
    # 计算pullback_pct：回调幅度（连板后回调幅度）
    df["high_30d"] = df["high"].rolling(30, min_periods=1).max()
    df["pullback_pct"] = (df["high_30d"] - df["close"]) / df["high_30d"].replace(0, np.nan)
    
    # 计算pullback_days：回调天数
    df["is_pullback"] = df["close"] < df["high_30d"].shift(1)
    df["pullback_days"] = df.groupby((~df["is_pullback"]).cumsum()).cumcount() + 1
    df.loc[~df["is_pullback"], "pullback_days"] = 0
    
    # 计算pullback_ma5：回调到MA5支撑位
    df["ma5"] = df["close"].rolling(5).mean()
    df["pullback_ma5"] = ((df["low"] <= df["ma5"]) & (df["close"] >= df["ma5"])).astype(int)
    
    # 重命名open_above_limit为open_above_limit_down和筛选逻辑保持一致
    df["open_above_limit_down"] = df["open_above_limit"]
    
    # 计算limit_down_open_amount：翘板金额（跌停开板成交金额）
    df["is_limit_down_yesterday"] = df["pct_chg"].shift(1) <= -9.8
    df["limit_down_price_yesterday"] = df["prev_close"] * 0.9
    df["limit_down_open_amount"] = df.apply(
        lambda x: x["amount"] if (x["low"] == x["limit_down_price_yesterday"] and x["high"] > x["limit_down_price_yesterday"] and x["is_limit_down_yesterday"]) else 0, axis=1
    )
    
    # 计算rise_after_limit_down：翘板后涨幅
    df["rise_after_limit_down"] = df.apply(
        lambda x: (x["close"] - x["limit_down_price_yesterday"]) / x["limit_down_price_yesterday"] * 100 if x["limit_down_open_amount"] > 0 and x["limit_down_price_yesterday"] != 0 else 0, axis=1
    )
    
    # 批量更新到数据库
    for _, row in df.iterrows():
        update_data = {
            "first_limit_up": int(row["first_limit_up"]),
            "limit_up_yesterday": int(row["limit_up_yesterday"]),
            "limit_up_count": int(row["limit_up_count"]),
            "volume_ratio": float(row["volume_ratio"]) if not pd.isna(row["volume_ratio"]) else 0,
            "amplitude": float(row["amplitude"]) if not pd.isna(row["amplitude"]) else 0,
            "market_leader": int(row["market_leader"]),
            "open_below_limit": int(row["open_below_limit"]),
            "open_above_limit": int(row["open_above_limit"]),
            "limit_up_open_amount": float(row["limit_up_open_amount"]) if not pd.isna(row["limit_up_open_amount"]) else 0,
            "limit_up_open_count": int(row["limit_up_open_count"]),
            "hot_sector": int(row["hot_sector"]),
            "limit_up_time": int(row["limit_up_time"]),
            "limit_up_open_duration": int(row["limit_up_open_duration"]),
            "pullback_pct": float(row["pullback_pct"]) if not pd.isna(row["pullback_pct"]) else 0,
            "pullback_days": int(row["pullback_days"]),
            "pullback_ma5": int(row["pullback_ma5"]),
            "open_above_limit_down": int(row["open_above_limit_down"]),
            "limit_down_open_amount": float(row["limit_down_open_amount"]) if not pd.isna(row["limit_down_open_amount"]) else 0,
            "rise_after_limit_down": float(row["rise_after_limit_down"]) if not pd.isna(row["rise_after_limit_down"]) else 0
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
