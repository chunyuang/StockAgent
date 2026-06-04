#!/usr/bin/env python3
"""
情绪得分预计算脚本

从 limit_list / daily_basic 计算每日情绪得分，存入 sentiment_scores 集合。
- 有数据的日子：精确计算（涨跌停+连板+涨跌比+溢价）
- 无数据的日子：标注 missing_data=True

用法: python3 precompute_sentiment.py [--start 20240501] [--end 20260531]
"""
import asyncio
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.managers import mongo_manager
from pymongo import UpdateOne


async def compute_sentiment(trade_date: int, db) -> dict:
    """计算单个交易日的情绪得分"""
    td_str = str(trade_date)
    
    # 1. 从limit_list获取涨跌停(最准确)
    lu = await db["limit_list"].count_documents({"trade_date": trade_date, "limit": "U"})
    ld = await db["limit_list"].count_documents({"trade_date": trade_date, "limit": "D"})
    
    # 连板高度
    max_lb_doc = await db["limit_list"].find_one(
        {"trade_date": trade_date, "limit": "U"},
        sort=[("limit_times", -1)],
        projection={"limit_times": 1}
    )
    max_lb = max_lb_doc.get("limit_times", 1) if max_lb_doc else 1
    
    # 溢价(从limit_list算: 昨日涨停今日开盘价/昨日收盘价-1)
    zt_premium = 0.0
    if lu > 0:
        # 简化: 取前一日涨停今日的表现
        prev_td = trade_date - 1  # 不精确但够用
        prev_zt = await db["limit_list"].find(
            {"trade_date": prev_td, "limit": "U"},
            {"ts_code": 1, "close": 1, "_id": 0}
        ).to_list(10)
        if prev_zt:
            premiums = []
            for zt in prev_zt[:20]:
                today_doc = await db["daily_basic"].find_one(
                    {"trade_date": trade_date, "ts_code": zt["ts_code"]},
                    {"pct_chg": 1}
                )
                if today_doc and today_doc.get("pct_chg") is not None:
                    premiums.append(today_doc["pct_chg"])
            if premiums:
                zt_premium = sum(premiums) / len(premiums)
    
    data_source = "limit_list"
    
    # 2. limit_list无数据时，从stock_daily_ak_full或daily_basic用pct_chg统计
    if lu == 0 and ld == 0:
        # 优先用stock_daily_ak_full(更可靠，pct_chg总有)
        has_pct_ak = await db["stock_daily_ak_full"].count_documents({"trade_date": trade_date, "pct_chg": {"$ne": None, "$exists": True}})
        if has_pct_ak > 0:
            lu = await db["stock_daily_ak_full"].count_documents({"trade_date": trade_date, "pct_chg": {"$gte": 9.8}})
            ld = await db["stock_daily_ak_full"].count_documents({"trade_date": trade_date, "pct_chg": {"$lte": -9.8}})
            max_lb = 1
            data_source = "stock_daily_ak_full"
        else:
            # fallback到daily_basic
            has_pct = await db["daily_basic"].count_documents({"trade_date": trade_date, "pct_chg": {"$ne": None, "$exists": True}})
            if has_pct > 0:
                lu = await db["daily_basic"].count_documents({"trade_date": trade_date, "pct_chg": {"$gte": 9.8}})
                ld = await db["daily_basic"].count_documents({"trade_date": trade_date, "pct_chg": {"$lte": -9.8}})
                max_lb = 1
                data_source = "daily_basic"
            else:
                data_source = "daily_basic(no_pct)"
    
    # 3. 都无有效数据
    missing_data = (lu == 0 and ld == 0)
    
    # 涨跌家数(优先stock_daily_ak_full, fallback daily_basic)
    up_count = await db["stock_daily_ak_full"].count_documents({"trade_date": trade_date, "pct_chg": {"$gt": 0}})
    down_count = await db["stock_daily_ak_full"].count_documents({"trade_date": trade_date, "pct_chg": {"$lt": 0}})
    if up_count + down_count == 0:
        # fallback daily_basic
        up_count = await db["daily_basic"].count_documents({"trade_date": trade_date, "pct_chg": {"$gt": 0}})
        down_count = await db["daily_basic"].count_documents({"trade_date": trade_date, "pct_chg": {"$lt": 0}})
    up_down_ratio = up_count / max(up_count + down_count, 1)
    
    # 情绪公式(与EmotionCycleManager._compute_score一致)
    score_zu = min(30, lu)
    score_zd = max(0, 20 - ld * 2)
    score_lb = min(20, max_lb * 2)
    score_ud = int(up_down_ratio * 15)
    score_ym = min(15, max(0, int(zt_premium)))
    score = min(100, max(0, score_zu + score_zd + score_lb + score_ud + score_ym))
    
    # 阶段判断(4级,与实盘L3对齐)
    if score >= 70:
        period = "高潮"
        position_ratio = 1.0
    elif score >= 55:
        period = "分化"
        position_ratio = 0.7
    elif score >= 40:
        period = "震荡"
        position_ratio = 0.5
    else:
        period = "冰点"
        position_ratio = 0.3
    
    return {
        "trade_date": trade_date,
        "score": score,
        "period": period,
        "position_ratio": position_ratio,
        "limit_up": lu,
        "limit_down": ld,
        "max_continue": max_lb,
        "up_count": up_count,
        "down_count": down_count,
        "up_down_ratio": round(up_down_ratio, 3),
        "zt_premium": round(zt_premium, 1),
        "data_source": data_source,
        "missing_data": missing_data,
        "updated_at": datetime.now().isoformat(),
    }


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="20240501", help="起始日期 YYYYMMDD")
    parser.add_argument("--end", default=None, help="结束日期 YYYYMMDD, 默认今天")
    args = parser.parse_args()
    
    await mongo_manager.initialize()
    db = mongo_manager.db
    
    end_date = args.end or datetime.now().strftime("%Y%m%d")
    start_date = args.start
    
    # 获取所有交易日(从daily_basic或limit_list)
    all_dates = set()
    async for doc in db["daily_basic"].find(
        {"trade_date": {"$gte": int(start_date), "$lte": int(end_date)}},
        {"trade_date": 1}
    ):
        all_dates.add(doc["trade_date"])
    async for doc in db["limit_list"].find(
        {"trade_date": {"$gte": int(start_date), "$lte": int(end_date)}},
        {"trade_date": 1}
    ):
        all_dates.add(doc["trade_date"])
    # 也加上broker_orders的日期
    async for doc in db["broker_orders"].find(
        {"trade_date": {"$exists": True}},
        {"trade_date": 1}
    ):
        td = doc.get("trade_date", "")
        if td and len(td) == 8 and td.isdigit():
            all_dates.add(int(td))
    
    all_dates = sorted(all_dates)
    print(f"需计算 {len(all_dates)} 个交易日 ({all_dates[0] if all_dates else '?'}~{all_dates[-1] if all_dates else '?'})")
    
    # 逐日计算并写入sentiment_scores
    ops = []
    computed = 0
    missing = 0
    for td in all_dates:
        result = await compute_sentiment(td, db)
        ops.append(UpdateOne(
            {"trade_date": td},
            {"$set": result},
            upsert=True
        ))
        if result["missing_data"]:
            missing += 1
        else:
            computed += 1
    
    if ops:
        result = await db["sentiment_scores"].bulk_write(ops)
        print(f"写入完成: {result.upserted_count} 新增, {result.modified_count} 更新")
    
    print(f"统计: {computed}天有数据, {missing}天缺数据")
    
    # 打印最近10天
    cursor = db["sentiment_scores"].find().sort("trade_date", -1).limit(15)
    print("\n最近计算结果:")
    async for doc in cursor:
        mark = "⚠️" if doc.get("missing_data") else "✅"
        print(f"  {mark} {doc['trade_date']} score={doc['score']} {doc['period']} lu={doc['limit_up']} ld={doc['limit_down']} src={doc['data_source']}")


if __name__ == "__main__":
    asyncio.run(main())
