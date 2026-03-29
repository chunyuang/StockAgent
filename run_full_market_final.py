#!/usr/bin/env python3
"""
全市场真实回测 - 最终版
"""
import asyncio
import sys
from datetime import datetime

sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

async def run_verification():
    print("="*80)
    print("🚀 全市场真实回测（已包含滑点、涨跌停、仓位管理）")
    print("="*80)
    print(f"回测区间: 20260107 ~ 20260320")
    print(f"初始资金: 1,000,000 元")
    print(f"流动性门槛: 1000万元")
    print("="*80)
    
    # 初始化管理器
    from core.managers import mongo_manager, redis_manager
    await mongo_manager.initialize()
    await redis_manager.initialize()
    
    print("✅ 管理器初始化完成")
    
    # 运行回测
    from backtest_module.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
    
    config = {
        "universe": "all_a",
        "start_date": "20260107",
        "end_date": "20260320",
        "initial_cash": 1000000,
        "rebalance_freq": "daily",
        "top_n": 5,
        "weight_method": "equal",
        "liquidity_threshold": 1000,
        "max_position_per_stock": 0.2,
        "slippage": 0.001,
        "max_position": 0.8,
        "factors": [
            {"name": "limit_up_yesterday", "weight": 1.0, "direction": "asc"},
        ],
        "data_collection": "stock_daily_full",  # 使用导入的全市场数据
    }
    
    backtester = PortfolioBacktester(source=None)
    result = await backtester.run(config)
    
    perf = result.get('performance', {})
    records = result.get('rebalance_records', [])
    
    print("\n📊 回测结果:")
    print(f"  总收益率: {perf.get('total_return', 0):.2f}%")
    print(f"  总交易次数: {len(records)}次")
    print(f"  最大回撤: {perf.get('max_drawdown', 0):.2f}%")
    print(f"  夏普比率: {perf.get('sharpe_ratio', 0):.2f}")
    print(f"  胜率: {perf.get('win_rate', 0):.2f}%")
    
    if records:
        print("\n💹 最近10笔交易:")
        print("  日期       | 动作 | 股票代码 | 数量  | 成交价   | 金额")
        print("  ----------|------|----------|-------|----------|---------")
        for r in records[-10:]:
            print(f"  {r['date']} | {r['action']:4} | {r['ts_code']:8} | {r['shares']:5} | {r['price']:8.2f} | {r['amount']:8.2f}")
    
    print("\n" + "="*80)
    if len(records) > 0:
        print("✅ 全市场回测流程完全正常，已成功产生真实交易信号！")
    else:
        print("ℹ️  本次回测区间内没有符合策略条件的交易机会，策略空仓是正常结果。")
    
    return len(records) > 0

if __name__ == "__main__":
    success = asyncio.run(run_verification())
    sys.exit(0 if success else 1)
