#!/usr/bin/env python3
"""
全市场AKShare回测 - 修复版
调整起始日期为20260106，保证有昨日数据
"""
import asyncio
import sys
from datetime import datetime

sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

class FullMarketAKShareBacktest:
    def __init__(self):
        self.start_date = "20260107"  # 调整起始日期到1月7日，1月6日有5只涨停
        self.end_date = "20260320"
        self.initial_capital = 1000000  # 100万
        self.liquidity_threshold = 1000  # 1000万
        self.source = None
        
    async def run(self):
        print("="*70)
        print("🚀 StockAgent 全市场AKShare回测 (修复版)")
        print("="*70)
        print(f"📅 回测区间: {self.start_date} ~ {self.end_date}")
        print(f"💰 初始资金: {self.initial_capital:,} 元")
        print(f"📊 数据: stock_daily集合(266只股票，已补全所有衍生字段)")
        print("="*70)
        
        # 策略配置
        strategies = [
            {
                "name": "半路追涨",
                "factors": [
                    {"name": "limit_up_yesterday", "weight": 0.4, "direction": "asc"},
                    {"name": "open_below_limit", "weight": 0.3, "direction": "asc"},
                    {"name": "volume_increase", "weight": 0.3, "direction": "desc"}
                ],
                "n_stocks": 5,
                "weight_method": "equal"
            },
            {
                "name": "首板打板",
                "factors": [
                    {"name": "first_limit_up", "weight": 0.6, "direction": "asc"},
                    {"name": "volume_increase", "weight": 0.4, "direction": "desc"}
                ],
                "n_stocks": 3,
                "weight_method": "equal"
            }
        ]
        
        print(f"\n📈 运行策略: {len(strategies)}个")
        
        # 初始化管理器
        from core.managers import mongo_manager, redis_manager
        await mongo_manager.initialize()
        await redis_manager.initialize()
        
        print("✅ 管理器初始化完成")
        
        # 运行回测
        from backtest_module.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
        
        total_trades = 0
        for strategy in strategies:
            print(f"\n🔍 运行策略: {strategy['name']}")
            
            backtest = PortfolioBacktester(source=self.source)
            
            config = {
                "strategy_name": strategy["name"],
                "universe": "all_a",
                "start_date": self.start_date,
                "end_date": self.end_date,
                "initial_cash": self.initial_capital,
                "rebalance_freq": "daily",
                "top_n": strategy["n_stocks"],
                "weight_method": strategy["weight_method"],
                "liquidity_threshold": self.liquidity_threshold,
                "factors": strategy["factors"],
                "data_collection": "stock_daily_ak_full",
                "verbose": True  # 开启详细日志，看看哪里有问题
            }
            
            result = await backtest.run(config)
            
            trades = result.get('total_trades', 0)
            total_trades += trades
            
            print(f"  📊 结果: 总收益率={result.get('total_return_pct', 0):.2f}%, "
                  f"交易数={trades}, 胜率={result.get('win_rate', 0):.2f}%")
        
        print("\n" + "="*70)
        print("📊 回测完成总结")
        print("="*70)
        print(f"总交易次数: {total_trades}次")
        
        if total_trades > 0:
            print("✅ AKShare回测流程完全跑通，能够正常产生交易信号！")
        else:
            print("⚠️  仍然没有交易信号，需要进一步调试因子逻辑")
        
        return total_trades > 0

if __name__ == "__main__":
    success = asyncio.run(FullMarketAKShareBacktest().run())
    sys.exit(0 if success else 1)
