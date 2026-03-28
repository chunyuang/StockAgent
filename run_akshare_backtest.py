#!/usr/bin/env python3
"""
直接运行AKShare数据源回测
回测区间: 2026-01-05 ~ 2026-03-20
初始资金: 100万 (1,000,000)
"""
import asyncio
import sys
from datetime import datetime
import json
import os

# 添加项目路径
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from core.settings import settings
from backtest_module.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
from backtest_module.backtest_engine.factor_selection.universe import UniverseManager, UniverseType, ExcludeRule
from backtest_module.backtest_engine.factor_selection.factor_engine import FactorEngine

class DirectAKShareBacktest:
    def __init__(self):
        self.start_date = "20260105"
        self.end_date = "20260320"
        self.initial_capital = 1000000  # 100万
        self.liquidity_threshold = 1000  # 流动性门槛 1000万
        self.max_workers = 10
        self.enable_checkpoint = True
        self.verbose = False
        self.source = "ak"  # 使用AKShare数据源
        
    async def run(self):
        print("="*60)
        print("🚀 StockAgent AKShare数据源回测")
        print("="*60)
        print(f"📅 回测区间: {self.start_date} ~ {self.end_date}")
        print(f"💰 初始资金: {self.initial_capital:,} 元")
        print(f"📊 数据源: {self.source} (AKShare)")
        print("="*60)
        
        # 配置策略
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
                "name": "龙头战法",
                "factors": [
                    {"name": "market_leader", "weight": 0.5, "direction": "asc"},
                    {"name": "pullback_ma5", "weight": 0.3, "direction": "asc"},
                    {"name": "lhb_buy_in", "weight": 0.2, "direction": "desc"}
                ],
                "n_stocks": 2,
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
        
        print(f"\n📈 回测策略: {len(strategies)} 个")
        for i, strategy in enumerate(strategies):
            print(f"  {i+1}. {strategy['name']} - {strategy['n_stocks']}只股票")
        
        print("\n⏳ 开始回测...")
        
        # 初始化管理器
        from core.managers import mongo_manager, redis_manager, tushare_manager, baostock_manager
        
        await mongo_manager.initialize()
        await redis_manager.initialize()
        await tushare_manager.initialize()
        await baostock_manager.initialize()
        
        print("✅ 管理器初始化完成")
        
        # 运行每个策略的回测
        results = []
        for strategy in strategies:
            print(f"\n🔍 运行策略: {strategy['name']}")
            
            # 创建回测实例
            backtest = PortfolioBacktester(source=self.source)
            
            # 准备配置
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
                "max_workers": self.max_workers,
                "enable_checkpoint": self.enable_checkpoint,
                "verbose": self.verbose,
                "factors": strategy["factors"]
            }
            
            # 运行回测
            result = await backtest.run(config)
            results.append(result)
            
            print(f"  📊 结果: 总收益率={result.get('total_return_pct', 0):.2f}%, "
                  f"交易数={result.get('total_trades', 0)}, "
                  f"胜率={result.get('win_rate', 0):.2f}%")
        
        # 生成汇总报告
        print("\n" + "="*60)
        print("📊 StockAgent AKShare数据源回测最终报告")
        print("="*60)
        
        summary = {
            "回测时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "回测区间": f"{self.start_date} ~ {self.end_date}",
            "初始资金": self.initial_capital,
            "数据源": self.source,
            "策略结果": []
        }
        
        for i, (strategy, result) in enumerate(zip(strategies, results)):
            summary["策略结果"].append({
                "策略名称": strategy["name"],
                "总收益率": f"{result.get('total_return_pct', 0):.2f}%",
                "交易数": result.get("total_trades", 0),
                "胜率": f"{result.get('win_rate', 0):.2f}%",
                "平均收益率": f"{result.get('avg_daily_return_pct', 0):.2f}%",
                "最大回撤": f"{result.get('max_drawdown_pct', 0):.2f}%",
                "夏普比率": f"{result.get('sharpe_ratio', 0):.2f}"
            })
            
            print(f"| {strategy['name']:10} | "
                  f"{result.get('total_trades', 0):6} | "
                  f"{result.get('win_rate', 0):6.2f}% | "
                  f"{result.get('avg_daily_return_pct', 0):8.3f}% | "
                  f"{result.get('max_drawdown_pct', 0):7.2f}% | "
                  f"{result.get('total_return_pct', 0):7.2f}% | "
                  f"{result.get('sharpe_ratio', 0):7.2f} |")
        
        print("="*60)
        
        # 保存结果
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"/tmp/akshare_backtest_{timestamp}.json"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        
        print(f"\n💾 结果已保存: {output_file}")
        
        # 保存CSV格式
        csv_file = f"/tmp/akshare_backtest_{timestamp}.csv"
        import csv
        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['strategy', 'total_trades', 'win_rate', 'avg_daily_return_pct', 
                            'max_drawdown_pct', 'total_return_pct', 'sharpe_ratio'])
            for i, (strategy, result) in enumerate(zip(strategies, results)):
                writer.writerow([
                    strategy['name'],
                    result.get('total_trades', 0),
                    result.get('win_rate', 0),
                    result.get('avg_daily_return_pct', 0),
                    result.get('max_drawdown_pct', 0),
                    result.get('total_return_pct', 0),
                    result.get('sharpe_ratio', 0)
                ])
        
        print(f"📄 CSV已保存: {csv_file}")
        
        return summary

def main():
    backtest = DirectAKShareBacktest()
    asyncio.run(backtest.run())

if __name__ == "__main__":
    main()