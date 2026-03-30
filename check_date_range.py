#!/usr/bin/env python3
"""
检查数据库中的日期范围
"""

import asyncio
import sys
import logging
from typing import List, Dict, Set
import pandas as pd
import numpy as np

from dotenv import load_dotenv
load_dotenv('/root/.openclaw/workspace/StockAgent/AgentServer/.env')

sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from core.managers import (
    redis_manager,
    mongo_manager,
)

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s'
)


async def check_date_range():
    await redis_manager.initialize()
    await mongo_manager.initialize()
    
    # 获取不同日期的记录数
    pipeline = [
        {"$group": {"_id": "$trade_date_int", "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]
    
    cursor = mongo_manager.db.daily.aggregate(pipeline)
    result = await cursor.to_list(length=None)
    
    df = pd.DataFrame(result)
    df.columns = ["trade_date", "count"]
    
    logger.info(f"Total distinct dates: {len(df)}")
    logger.info(f"Min date: {df['trade_date'].min()}, Max date: {df['trade_date'].max()}")
    
    # 查看最新的 20 个日期
    latest = df.tail(30)
    print("\nLatest 30 dates:")
    print(latest.to_string(index=False))
    
    # 检查我们需要的区间有多少天
    target_dates = df[(df['trade_date'] >= 20260105) & (df['trade_date'] <= 20260320)]
    logger.info(f"\nIn target range 20260105 ~ 20260320: {len(target_dates)} dates")
    
    # 检查哪些日期缺失
    all_target = list(range(20260105, 20260321))
    existing = set(target_dates['trade_date'].tolist())
    missing = [d for d in all_target if d not in existing]
    logger.info(f"Missing {len(missing)} dates in target range: {missing[:20]}")
    
    # 检查 up_limit 字段
    sample = await mongo_manager.db.daily.find_one({"trade_date_int": {"$gte": 20260100}})
    if sample:
        logger.info(f"\nSample document fields: {list(sample.keys())}")
        for k, v in sample.items():
            if k in ['up_limit', 'down_limit', 'close', 'open', 'trade_date_int', 'ts_code']:
                logger.info(f"  {k}: {v}")
    
    await redis_manager.close()
    await mongo_manager.close()


if __name__ == "__main__":
    asyncio.run(check_date_range())
