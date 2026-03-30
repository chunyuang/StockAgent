#!/usr/bin/env python3
"""
全市场回测简单版
直接修改回测的数据集合为stock_agent_full数据库
"""
import sys
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

import asyncio
from datetime import datetime
from core.managers import mongo_manager, redis_manager, baostock_manager
from backtest_module.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester

async def run():
    print("🚀 全市场回测开始...")
    print(f"时间: {datetime.now()}")
    
    # 初始化所有管理器
    await mongo_manager.initialize()
    await redis_manager.initialize()
    await baostock_manager.initialize()
    
    # 临时修改数据库连接到全市场库
    mongo_manager.db = mongo_manager.client["stock_agent_full"]
    
    # 测试数据
    count = await mongo_manager.db.stock_daily.count_documents({})
    stocks = await mongo_manager.db.stock_daily.distinct("ts_code")
    print(f"✅ 数据库连接成功，共{count}条记录，{len(stocks)}只股票")
    
    # 简化策略，先看有没有信号
    config = {
        "strategy_name": "测试策略",
        "universe": "all_a",
        "start_date": "20260107",
        "end_date": "20260131",
        "initial_cash": 1000000,
        "rebalance_freq": "daily",
        "top_n": 10,
        "weight_method": "equal",
        "liquidity_threshold": 1000,
        "factors": [
            {"name": "limit_up_yesterday", "weight": 1.0, "direction": "asc"},
        ],
        "slippage": 0.001,
        "max_position": 0.8,
        "data_collection": "stock_daily",
    }
    
    backtester = PortfolioBacktester(source=None)
    result = await backtester.run(config)
    
    print(f"\n✅ 回测完成:")
    print(f"总收益: {result.get('performance', {}).get('total_return', 0):.2f}%")
    print(f"交易次数: {len(result.get('rebalance_records', []))}次")
    
    if result.get('rebalance_records'):
        print("\n交易明细:")
        for r in result['rebalance_records'][:10]:
            print(f"  {r['date']} {r['action']} {r['ts_code']} {r['shares']}股 @ {r['price']:.2f}元")

if __name__ == "__main__":
    asyncio.run(run())
