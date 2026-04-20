#!/usr/bin/env python3
"""
检查 limit_up 数据：抽查几个交易日，看看昨日涨停实际有多少只
"""

import asyncio
import sys
import logging
import pandas as pd

from dotenv import load_dotenv
load_dotenv('/root/.openclaw/workspace/StockAgent/AgentServer/.env')

sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/backtest_module')

from core.managers import (
    redis_manager,
    mongo_manager,
)

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s'
)


async def check_limit_up_data(check_date: str):
    """检查某一天有多少只昨日涨停"""
    
    await redis_manager.initialize()
    await mongo_manager.initialize()
    
    # 获取基础股票池
    from backtest_module.backtest_engine.factor_selection.universe import UniverseManager, UniverseType, ExcludeRule
    universe_mgr = UniverseManager()
    
    universe = await universe_mgr.get_universe(
        UniverseType.ALL_A,
        check_date,
        [ExcludeRule.ST, ExcludeRule.NEW_STOCK],
    )
    
    logger.info(f"[{check_date}] Base universe: {len(universe)} stocks")
    
    # 查询这些股票昨日的数据
    # 计算 trade_date_prev
    from datetime import datetime
    
    # 查询 MongoDB 获取所有股票的 close 和 up_limit
    docs = await mongo_manager.db.daily.find(
        {"trade_date_int": int(check_date)},
        {"ts_code": 1, "close": 1, "up_limit": 1}
    ).to_list(length=None)
    
    df = pd.DataFrame(docs)
    
    logger.info(f"[{check_date}] Total daily records in MongoDB: {len(df)}")
    
    # 计算涨停
    df["is_limit_up"] = df["close"] >= df["up_limit"] * 0.998
    
    limit_up_count = df["is_limit_up"].sum()
    logger.info(f"[{check_date}] Number of limit up: {limit_up_count}")
    
    # 列出涨停的股票
    limit_up_codes = df[df["is_limit_up"]]["ts_code"].head(20).tolist()
    logger.info(f"[{check_date}] First 20 limit up: {limit_up_codes}")
    
    await redis_manager.close()
    await mongo_manager.close()
    
    return limit_up_count


if __name__ == "__main__":
    check_date = "20260106"
    if len(sys.argv) > 1:
        check_date = sys.argv[1]
    
    asyncio.run(check_limit_up_data(check_date))
