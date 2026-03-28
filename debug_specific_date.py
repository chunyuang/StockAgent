#!/usr/bin/env python3
import asyncio
import sys
import pandas as pd
import numpy as np

sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from core.managers import redis_manager, mongo_manager
from backtest_module.backtest_engine.factor_selection.factor_library import FactorLibrary

async def debug_date(check_date):
    await redis_manager.initialize()
    await mongo_manager.initialize()
    
    print(f"Checking date: {check_date}")
    
    # 获取这个交易日所有股票的limit_up_yesterday
    # 我们需要 limit_up_yesterday，它应该等于昨日是否涨停
    # 今日 = check_date，昨日 = check_date - 1 交易日
    
    # 获取今日所有股票
    result = await mongo_manager.find_many(
        "stock_daily",
        {"trade_date": int(check_date), "source": "ak"},
        projection={"ts_code": 1, "open": 1, "close": 1, "up_limit": 1},
    )
    
    print(f"Total stocks on {check_date}: {len(result)}")
    
    # 我们需要获取昨日的数据来计算limit_up_yesterday
    # 查询昨日所有股票
    from datetime import datetime, timedelta
    
    # 简单方法：直接查询昨日所有股票，计算哪些涨停
    # 获取昨日日期
    # 我们按日期顺序找前一个交易日
    pipeline = [
        {"$match": {"trade_date": {"$lt": int(check_date)}},
        {"$group": {"_id": None, "max_date": {"$max": "$trade_date"}}},
    ]
    
    cursor = mongo_manager.db.stock_daily.aggregate(pipeline)
    last_date_doc = await cursor.to_list(length=1)
    if not last_date_doc:
        print("No previous date found")
        return
    
    yesterday_date = last_date_doc[0]["max_date"]
    print(f"Yesterday date: {yesterday_date}")
    
    # 获取昨日所有股票，哪些满足 close >= up_limit * 0.998
    yesterday_result = await mongo_manager.find_many(
        "stock_daily",
        {"trade_date": yesterday_date, "source": "ak"},
        projection={"ts_code": 1, "close": 1, "up_limit": 1},
    )
    
    limit_up_yesterday = {}
    count = 0
    for doc in yesterday_result:
        if doc["close"] >= doc["up_limit"] * 0.998:
            limit_up_yesterday[doc["ts_code"]] = 1
            count += 1
    
    print(f"昨日涨停股票数量: {count}")
    
    # 现在检查这些涨停股票今日是否满足 open < up_limit_yesterday
    if count == 0:
        print("昨日没有涨停股票，今日自然选不出")
        return
    
    # 今日这些涨停股票中，有多少满足 open < up_limit
    satisfy = []
    for doc in result:
        ts_code = doc["ts_code"]
        if ts_code in limit_up_yesterday:
            # doc["up_limit"] 就是今日的up_limit？不对！
            # up_limit 是股票每日都一样吗？不，up_limit 是涨跌停价格，每日都变，昨日涨停对应的up_limit是昨日的
            # 我们需要获取昨日的up_limit，然后今日开盘 < 昨日up_limit
            # 所以我们需要从yesterday_result获取昨日的up_limit
            pass
    
    # 重新来：我们需要对于今日选股，
    # limit_up_yesterday = 昨日是否涨停 → 来自昨日数据
    # open_below_limit = (昨日up_limit - 今日open) / 昨日up_limit > 0
    # 所以今日open < 昨日up_limit → 才有信号
    
    yesterday_map = {
        doc["ts_code"]: doc["up_limit"] 
        for doc in yesterday_result
        if doc["close"] >= doc["up_limit"] * 0.998
    }
    
    satisfy = []
    for today_doc in result:
        ts_code = today_doc["ts_code"]
        if ts_code not in yesterday_map:
            continue
        yesterday_up_limit = yesterday_map[ts_code]
        if today_doc["open"] < yesterday_up_limit:
            satisfy.append(ts_code)
    
    print(f"满足 limit_up_yesterday + open_below_limit: {len(satisfy)} 只")
    print(f"前 10 只: {satisfy[:10]}")

if __name__ == "__main__":
    check_date = 20260106
    if len(sys.argv) > 1:
        check_date = int(sys.argv[1])
    asyncio.run(debug_date(check_date))
