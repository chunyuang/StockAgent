#!/usr/bin/env python3
"""
全市场AKShare回测
使用stock_daily集合的全市场股票数据
"""
import asyncio
import sys
from datetime import datetime
import json

sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

class FullMarketAKShareBacktest:
    def __init__(self):
        self.start_date = "20260105"
        self.end_date = "20260320"
        self.initial_capital = 1000000  # 100万
        self.liquidity_threshold = 1000  # 1000万
        self.source = None  # 全市场数据没有source标记
        
    async def run(self):
        print("="*60)
        print("🚀 StockAgent 全市场AKShare回测")
        print("="*60)
        print(f"📅 回测区间: {self.start_date} ~ {self.end_date}")
        print(f"💰 初始资金: {self.initial_capital:,} 元")
        print(f"📊 数据来源: stock_daily集合(全市场)")
        print("="*60)
        
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
                "name": "涨停开板",
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
        
        # 先检查有没有涨停股票
        test_date = 20260105
        count = await mongo_manager.db.stock_daily.count_documents({
            "trade_date": test_date,
            "$expr": {"$gte": ["$close", {"$multiply": ["$up_limit", 0.995]}]}
        })
        print(f"\n📊 测试日期{test_date}涨停股票数量: {count}只")
        
        # 运行回测
        from backtest_module.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
        
        results = []
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
                "data_collection": "stock_daily"  # 使用全市场集合
            }
            
            result = await backtest.run(config)
            results.append(result)
            
            print(f"  📊 结果: 总收益率={result.get('total_return_pct', 0):.2f}%, "
                  f"交易数={result.get('total_trades', 0)}, "
                  f"胜率={result.get('win_rate', 0):.2f}%")
        
        # 输出报告
        print("\n" + "="*60)
        print("📊 全市场AKShare回测最终报告")
        print("="*60)
        
        for strategy, result in zip(strategies, results):
            print(f"| {strategy['name']:8} | "
                  f"{result.get('total_trades', 0):6} | "
                  f"{result.get('win_rate', 0):6.2f}% | "
                  f"{result.get('total_return_pct', 0):7.2f}% |")
        
        print("="*60)
        
        # 保存结果
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"/tmp/full_market_akshare_{timestamp}.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump({
                "strategies": [s["name"] for s in strategies],
                "results": results
            }, f, ensure_ascii=False, indent=2)
        
        print(f"\n💾 结果保存到: {output_file}")
        
        return results

if __name__ == "__main__":
    asyncio.run(FullMarketAKShareBacktest().run())
