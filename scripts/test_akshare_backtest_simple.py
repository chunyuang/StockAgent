#!/usr/bin/env python3
import asyncio
import sys
from datetime import datetime

sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/backtest_module')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from backtest_module.portfolio_backtest import PortfolioBacktest
from config.strategy_config import STRATEGIES

async def run_akshare_backtest():
    print("🚀 开始AKShare回测验证...")
    print(f"回测时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 回测配置
    config = {
        "start_date": 20260105,
        "end_date": 20260320,
        "initial_cash": 1000000,  # 100万本金
        "commission_rate": 0.0005,  # 万五手续费
        "slippage_rate": 0.001,  # 千一滑点
        "max_position_per_stock": 0.1,  # 单票最大仓位10%
        "data_collection": "stock_daily_ak_full_ak",  # AKShare数据源集合
        "source_filter": "ak",  # 数据源过滤
        "strategies": STRATEGIES,
    }
    
    # 初始化回测
    backtest = PortfolioBacktest(config)
    
    # 运行回测
    try:
        result = await backtest.run()
        print("\n✅ 回测完成！")
        print(f"总收益率: {result['total_return']:.2%}")
        print(f"年化收益率: {result['annualized_return']:.2%}")
        print(f"最大回撤: {result['max_drawdown']:.2%}")
        print(f"夏普比率: {result['sharpe_ratio']:.2f}")
        print(f"总交易次数: {result['total_trades']}")
        print(f"胜率: {result['win_rate']:.2%}")
        
        # 按策略统计
        print("\n📊 各策略表现:")
        for strategy_name, stats in result['strategy_stats'].items():
            print(f"  {strategy_name}: {stats['trade_count']}次交易, 收益率{stats['total_return']:.2%}")
            
    except Exception as e:
        print(f"\n❌ 回测失败: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run_akshare_backtest())
