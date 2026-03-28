#!/usr/bin/env python3
"""
调试每日选股过滤流程，详细看每一步还剩多少股票
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
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/backtest_module')

from core.managers import (
    redis_manager,
    mongo_manager,
    tushare_manager,
    baostock_manager,
)
from backtest_module.backtest_engine.factor_selection.universe import UniverseManager, UniverseType, ExcludeRule
from backtest_module.backtest_engine.factor_selection.factor_engine import FactorEngine

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s'
)


async def debug_daily_filters(start_date: str, end_date: str):
    """调试每日过滤流程"""
    
    # 初始化管理器
    logger.info("Initializing managers...")
    await redis_manager.initialize()
    await mongo_manager.initialize()
    await tushare_manager.initialize()
    await baostock_manager.initialize()
    
    universe_mgr = UniverseManager()
    factor_engine = FactorEngine(source="ak")
    
    # 获取调仓日期
    rebalance_dates = await universe_mgr.get_rebalance_dates(start_date, end_date, "daily")
    logger.info(f"Total rebalance dates: {len(rebalance_dates)}")
    
    # 策略因子配置 - 半路追涨
    factors = [
        {"name": "limit_up_yesterday", "weight": 1.0},
        {"name": "open_below_limit", "weight": 1.0},
    ]
    
    results = []
    
    for trade_date in rebalance_dates:
        logger.info(f"\n{'='*60}")
        logger.info(f"Date: {trade_date}")
        logger.info(f"{'='*60}")
        
        # 步骤1: 获取基础股票池
        universe = await universe_mgr.get_universe(
            UniverseType.ALL_A,
            trade_date,
            [ExcludeRule.ST, ExcludeRule.NEW_STOCK],
        )
        
        logger.info(f"[Step 1] After base universe (exclude ST/new): {len(universe)} stocks")
        
        if not universe:
            continue
        
        # 步骤2: 计算因子
        factor_df = await factor_engine.compute_factors(
            universe,
            trade_date,
            factors,
            liquidity_threshold=None,
        )
        
        # 步骤3: 筛选 - 需要两个因子都 > 0
        # limit_up_yesterday > 0.5 表示昨日涨停
        # open_below_limit > 0 表示开盘低于涨停价
        mask = (
            (factor_df["limit_up_yesterday"] > 0.5) & 
            (factor_df["open_below_limit"] > 0)
        )
        selected = factor_df[mask]
        
        logger.info(f"[Step 2] After factor filter (limit_up_yesterday + open_below_limit): {len(selected)} stocks")
        
        if len(selected) > 0:
            # 列出选中的股票
            selected_codes = selected["ts_code"].tolist()
            logger.info(f"  Selected: {selected_codes[:10]}{'...' if len(selected_codes) > 10 else ''}")
        
        results.append({
            "date": trade_date,
            "base_universe": len(universe),
            "after_factor": len(selected),
        })
    
    # 汇总统计
    logger.info("\n" + "="*60)
    logger.info("SUMMARY")
    logger.info("="*60)
    
    result_df = pd.DataFrame(results)
    print(result_df.to_string(index=False))
    
    total_dates = len(result_df)
    total_selected = result_df["after_factor"].sum()
    dates_with_selection = (result_df["after_factor"] > 0).sum()
    
    logger.info(f"\nTotal dates: {total_dates}")
    logger.info(f"Dates with at least one selection: {dates_with_selection}")
    logger.info(f"Total selected stocks across all dates: {int(total_selected)}")
    logger.info(f"Average selections per date: {total_selected / total_dates:.2f}")
    
    # 保存结果
    result_df.to_csv(f"/tmp/debug_filter_{start_date}_{end_date}.csv", index=False)
    logger.info(f"\nResults saved to: /tmp/debug_filter_{start_date}_{end_date}.csv")
    
    await redis_manager.close()
    await mongo_manager.close()
    
    return result_df


if __name__ == "__main__":
    start_date = "20260105"
    end_date = "20260320"
    
    if len(sys.argv) > 2:
        start_date = sys.argv[1]
        end_date = sys.argv[2]
    
    asyncio.run(debug_daily_filters(start_date, end_date))
