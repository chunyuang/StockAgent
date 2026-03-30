#!/usr/bin/env python3
"""
直接运行AKShare数据源回测 - 初始资金100万
"""
import sys
import asyncio
import logging
import pandas as pd
import numpy as np
from datetime import datetime

# 添加项目路径
sys.path.insert(0, '/root/.openclaw/workspace')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from core.settings import settings
from core.managers import mongo_manager, redis_manager, tushare_manager, baostock_manager
from backtest_module.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester

async def run_backtest():
    """运行回测"""
    
    # 配置参数
    config = {
        "strategy_name": "半路追涨",
        "universe": "all_a",
        "start_date": "20260105",
        "end_date": "20260320",
        "initial_cash": 1000000,  # 100万
        "rebalance_freq": "daily",
        "top_n": 5,
        "weight_method": "equal",
        "liquidity_threshold": 1000,
        "max_workers": 10,
        "enable_checkpoint": True,
        "verbose": False,
        "factors": [
            {"name": "limit_up_yesterday", "weight": 0.4, "direction": "asc"},
            {"name": "open_below_limit", "weight": 0.3, "direction": "asc"},
            {"name": "volume_increase", "weight": 0.3, "direction": "desc"}
        ]
    }
    
    print("="*60)
    print("🚀 StockAgent AKShare数据源回测")
    print("="*60)
    print(f"📅 回测区间: {config['start_date']} ~ {config['end_date']}")
    print(f"💰 初始资金: {config['initial_cash']:,} 元")
    print(f"📊 数据源: ak (物理隔离)")
    print("="*60)
    print("⏳ 开始回测...\n")
    
    # 初始化管理器
    await mongo_manager.initialize()
    await redis_manager.initialize()
    await tushare_manager.initialize()
    await baostock_manager.initialize()
    print("✅ 管理器初始化完成")
    
    # 运行回测
    backtester = PortfolioBacktester(source="ak")
    result = await backtester.run(config)
    
    # 输出结果
    print("\n" + "="*60)
    print("📊 回测结果")
    print("="*60)
    
    print(f"策略名称: {result.get('strategy_name', 'N/A')}")
    print(f"总收益率: {result.get('total_return_pct', 0):.2f}%")
    print(f"总交易次数: {result.get('total_trades', 0)}")
    print(f"胜率: {result.get('win_rate', 0):.2f}%")
    print(f"平均收益率: {result.get('avg_daily_return_pct', 0):.3f}%")
    print(f"最大回撤: {result.get('max_drawdown_pct', 0):.2f}%")
    print(f"夏普比率: {result.get('sharpe_ratio', 0):.3f}")
    print(f"最大组合回撤: {result.get('max_portfolio_drawdown_pct', 0):.2f}%")
    
    # 保存结果
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_file = f"/tmp/akshare_1m_backtest_result_{timestamp}.json"
    
    import json
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"\n💾 结果已保存: {result_file}")
    
    return result

def main():
    asyncio.run(run_backtest())

if __name__ == "__main__":
    main()