#!/usr/bin/env python3
"""
五大超短策略回测 - AKShare 独立流程
物理层面完全分离，不与 Tushare 混用，避免类型混用问题

说明:
- 直接使用 Baostock 获取交易日历（不需要 Tushare Token）
- 所有数据来自本地 MongoDB
- 所有 trade_date 都是 int 类型，避免混用
- 回测参数：每日调仓，五大超短策略
"""

import sys
import os

# 添加 workspace 根目录和 StockAgent 项目根目录到 path
sys.path.insert(0, '/root/.openclaw/workspace')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

import asyncio
import logging
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Any

from core.settings import settings
from core.managers import (
    redis_manager,
    mongo_manager,
    baostock_manager,
    akshare_manager,
)

from backtest_module.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
from backtest_module.backtest_engine.factor_selection.universe import UniverseManager, UniverseType, ExcludeRule
from backtest_module.backtest_engine.factor_selection.factor_engine import FactorEngine
from backtest_module.backtest_engine.factor_selection.factor_library import FactorLibrary

# ========== 配置 ==========
# 如果从 run_backtest_wizard.py 运行，参数从全局获取
# 否则使用默认值
if 'START_DATE' in globals():
    START_DATE = START_DATE
else:
    START_DATE = "20260105"

if 'END_DATE' in globals():
    END_DATE = END_DATE
else:
    END_DATE = "20260320"

if 'INITIAL_CAPITAL' in globals():
    INITIAL_CAPITAL = INITIAL_CAPITAL
else:
    INITIAL_CAPITAL = 1000000  # 初始资金 100万

if 'LIQUIDITY_THRESHOLD' in globals():
    LIQUIDITY_THRESHOLD = LIQUIDITY_THRESHOLD
else:
    LIQUIDITY_THRESHOLD = 1000  # 流动性门槛 1000万

if 'MAX_POSITION_PERCENT' in globals():
    MAX_POSITION_PERCENT = MAX_POSITION_PERCENT
else:
    MAX_POSITION_PERCENT = 20  # 单票最大仓位 20%

# ========== 策略定义 ==========
STRATEGIES = [
    {
        "name": "半路追涨",
        "filters": [
            ("limit_up_yesterday", 1),
            ("open_below_limit", 1),
            ("volume_increase", 1),
        ],
    },
    {
        "name": "涨停开板",
        "filters": [
            ("limit_up_yesterday", 1),
            ("first_limit_up", 0),
        ],
    },
    {
        "name": "跌停翘板",
        "filters": [
            ("limit_down_yesterday", 1),
            ("open_above_limit", 1),
        ],
    },
    {
        "name": "MA5低吸",
        "filters": [
            ("pullback_ma5", 1),
        ],
    },
    {
        "name": "龙头低吸",
        "filters": [
            ("market_leader", 1),
            ("pullback_ma5", 1),
            ("lhb_buy_in", 1),
        ],
    },
    {
        "name": "首板打板",
        "filters": [
            ("limit_up_yesterday", 1),
            ("first_limit_up", 1),
        ],
    },
]

async def main():
    # 初始化日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    )
    
    logger = logging.getLogger(__name__)
    logger.info("🚀 AKShare 独立流程 - 五大超短策略回测启动")
    logger.info(f"   回测区间: {START_DATE} -> {END_DATE}")
    logger.info(f"   初始资金: {INITIAL_CAPITAL}")
    logger.info(f"   单票最大仓位: {MAX_POSITION_PERCENT}%")
    logger.info(f"   流动性门槛: {LIQUIDITY_THRESHOLD} 万元")
    
    # 初始化管理器 - 只初始化需要的，不初始化 Tushare
    logger.info("Initializing managers...")
    await redis_manager.initialize()
    await mongo_manager.initialize()
    await baostock_manager.initialize()
    await akshare_manager.initialize()
    
    logger.info("All managers initialized ✓")
    logger.info("")
    print("=" * 80)
    
    # 初始化因子引擎 - 指定数据源为 AKShare (source="ak")
    # 这会强制过滤只查询 AKShare 下载的数据，避免与 Tushare 数据混用
    factor_engine = FactorEngine(source="ak")
    
    # 初始化宇宙管理器
    universe_mgr = UniverseManager()
    
    # 获取调仓日期 - 直接使用 baostock，不依赖 tushare
    rebalance_dates = await baostock_manager.get_trade_dates(START_DATE, END_DATE)
    if not rebalance_dates:
        logger.error("Failed to get trade dates from baostock, exiting")
        return
    
    rebalance_dates = sorted(rebalance_dates)
    logger.info(f"Total rebalance dates: {len(rebalance_dates)}")
    
    # 结果收集
    all_results = []
    
    # 遍历每个策略
    for strategy in STRATEGIES:
        logger.info("")
        print("=" * 80)
        logger.info(f"Starting backtest: {strategy['name']}")
        logger.info(f"   Period: {START_DATE} -> {END_DATE}")
        logger.info(f"   Initial cash: {INITIAL_CAPITAL}")
        print("=" * 80)
        logger.info("")
        
        # 创建回测器 - 指定数据源为 AKShare (source="ak")
        # 这会强制过滤只查询 AKShare 下载的数据，避免与 Tushare 数据混用
        config = {
            "start_date": START_DATE,
            "end_date": END_DATE,
            "initial_cash": INITIAL_CAPITAL,
            "max_position_percent": MAX_POSITION_PERCENT / 100.0,
            "liquidity_threshold": LIQUIDITY_THRESHOLD,  # AKShare amount 单位已经是万元，直接使用即可
            "data_collection": "stock_daily_ak_full",  # 使用全市场AKShare数据集合
            "universe_mgr": universe_mgr,
            "factor_engine": factor_engine,
            "exclude_rules": [ExcludeRule.ST, ExcludeRule.NEW_STOCK],
            "factors": [
                {"name": factor_name, "target": target}
                for factor_name, target in strategy["filters"]
            ],
            "top_n": 1,  # 每天选一个 - 超短模式
            "rebalance_freq": "daily",  # 每日调仓 - 超短策略本来就是每日调仓
        }
        backtester = PortfolioBacktester(source="ak")
        
        # 运行回测
        result = await backtester.run(config)
        
        if result is None or "error" in result:
            logger.error(f"Backtest failed for {strategy['name']}: {result.get('error', 'unknown error')}")
            continue
        
        # 检查必要字段
        required_fields = ['trade_days', 'win_rate', 'avg_daily_return', 'total_return', 'max_drawdown', 'sharpe_ratio']
        missing = [f for f in required_fields if f not in result]
        if missing:
            logger.error(f"Backtest missing fields: {missing}")
            continue
        
        # 保存结果
        result["strategy_name"] = strategy["name"]
        all_results.append(result)
        
        logger.info(f"Backtest completed for {strategy['name']}")
        logger.info(f"   signals: {result['trade_days']}")
        logger.info(f"   winrate: {result['win_rate']:.2f}%")
        logger.info(f"   avg return: {result['avg_daily_return']:.4f}")
        logger.info(f"   total return: {result['total_return']:.2f}%")
        logger.info(f"   max drawdown: {result['max_drawdown']:.2f}%")
        logger.info(f"   sharpe: {result['sharpe_ratio']:.2f}")
        logger.info("")
    
    # 生成报告
    print("\n")
    print("=" * 80)
    print(f"📊  StockAgent 五大策略 {START_DATE} ~ {END_DATE} 回归测试 最终报告")
    print(f"    初始资金: {INITIAL_CAPITAL:,}")
    print("    手续费: 佣金 2.00‰ + 印花税 1.0‰ + 滑点 1.0‰")
    print(f"    单票最大仓位: {MAX_POSITION_PERCENT}%")
    print("=" * 80)
    print()
    print("| Strategy     | signals | winrate |   avg return | max drawdown | total return |  sharpe |")
    print("|-------|-------|-------|-------------|---------------|-----------|-------|-------|")
    
    for result in sorted(all_results, key=lambda x: -x['total_return']):
        print(f"| {result['strategy_name']:<12} | {result['trade_days']:>6} | {result['win_rate']:>6.2f}% | {result['avg_daily_return']:>11.4f} | {result['max_drawdown']:>11.2f}% | {result['total_return']:>11.2f}% | {result['sharpe_ratio']:>6.2f} |")
    
    print("\n" + "=" * 80)
    print("✅ 回归测试完成!")
    
    # 关闭连接
    await baostock_manager.shutdown()
    await akshare_manager.shutdown()
    await mongo_manager.shutdown()
    await redis_manager.shutdown()
    
    logger.info("Done!")


if __name__ == "__main__":
    asyncio.run(main())
