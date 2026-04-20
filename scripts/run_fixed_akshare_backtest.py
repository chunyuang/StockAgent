#!/usr/bin/env python3
"""
修复后的AKShare回测脚本
降低流动性门槛，修复数据单位问题
"""

import asyncio
import sys
from datetime import datetime
import json

# 添加项目路径
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from backtest_module.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester

class FixedAKShareBacktest:
    def __init__(self):
        self.start_date = "20260105"
        self.end_date = "20260320"
        self.initial_capital = 1000000  # 100万
        self.liquidity_threshold = 100  # 降低到100万元（AKShare amount单位是万元）
        self.max_workers = 10
        self.enable_checkpoint = True
        self.verbose = True  # 开启详细日志
        self.source = "ak"  # 使用AKShare数据源
        
    async def run(self):
        print("="*60)
        print("🚀 StockAgent AKShare数据源回测 (修复版)")
        print("="*60)
        print(f"📅 回测区间: {self.start_date} ~ {self.end_date}")
        print(f"💰 初始资金: {self.initial_capital:,} 元")
        print(f"📊 数据源: {self.source} (AKShare)")
        print(f"💧 流动性门槛: {self.liquidity_threshold} 万元 (AKShare单位)")
        print("="*60)
        
        # 配置策略 - 降低门槛，增加股票数量
        strategies = [
            {
                "name": "半路追涨",
                "factors": [
                    {"name": "limit_up_yesterday", "weight": 0.4, "direction": "asc"},
                    {"name": "open_below_limit", "weight": 0.3, "direction": "asc"},
                    {"name": "volume_increase", "weight": 0.3, "direction": "desc"}
                ],
                "top_n": 10,  # 增加到10只股票
                "position_limit": 0.2,
                "stop_loss": -0.05,
                "take_profit": 0.1
            },
            {
                "name": "涨停开板",
                "factors": [
                    {"name": "limit_up_yesterday", "weight": 0.5, "direction": "asc"},
                    {"name": "open_below_limit", "weight": 0.5, "direction": "asc"}
                ],
                "top_n": 5,
                "position_limit": 0.15,
                "stop_loss": -0.03,
                "take_profit": 0.08
            },
            {
                "name": "龙头战法",
                "factors": [
                    {"name": "market_leader", "weight": 0.6, "direction": "asc"},
                    {"name": "volume_increase", "weight": 0.4, "direction": "desc"}
                ],
                "top_n": 3,
                "position_limit": 0.25,
                "stop_loss": -0.07,
                "take_profit": 0.15
            },
            {
                "name": "首板打板",
                "factors": [
                    {"name": "first_limit_up", "weight": 0.7, "direction": "asc"},
                    {"name": "volume_increase", "weight": 0.3, "direction": "desc"}
                ],
                "top_n": 3,
                "position_limit": 0.15,
                "stop_loss": -0.04,
                "take_profit": 0.1
            }
        ]
        
        print()
        print("📈 回测策略配置:")
        for i, strategy in enumerate(strategies, 1):
            print(f"  {i}. {strategy['name']} - {strategy['top_n']}只股票")
        
        print()
        print("⏳ 开始回测...")
        
        try:
            # 创建回测器
            backtester = PortfolioBacktester(
                start_date=self.start_date,
                end_date=self.end_date,
                initial_capital=self.initial_capital,
                liquidity_threshold=self.liquidity_threshold,
                max_workers=self.max_workers,
                enable_checkpoint=self.enable_checkpoint,
                verbose=self.verbose,
                source=self.source
            )
            
            # 运行回测
            results = await backtester.run(strategies)
            
            # 打印结果
            print()
            print("="*60)
            print("📊 StockAgent AKShare数据源回测最终报告")
            print("="*60)
            
            total_trades = 0
            total_return = 0
            
            for strategy_name, result in results.items():
                trades = result.get("trades", 0)
                win_rate = result.get("win_rate", 0)
                avg_return = result.get("avg_return", 0)
                total_return = result.get("total_return", 0)
                max_drawdown = result.get("max_drawdown", 0)
                sharpe = result.get("sharpe", 0)
                
                print(f"| {strategy_name:14} | {trades:6} | {win_rate:7} | {avg_return:10} | {total_return:7} | {max_drawdown:7} | {sharpe:7} |")
                
                total_trades += trades
            
            print("="*60)
            
            # 保存结果
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_json = f"/tmp/akshare_backtest_fixed_{timestamp}.json"
            output_csv = f"/tmp/akshare_backtest_fixed_{timestamp}.csv"
            
            with open(output_json, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            
            # 保存CSV
            import pandas as pd
            df_results = []
            for strategy_name, result in results.items():
                result['strategy'] = strategy_name
                df_results.append(result)
            
            if df_results:
                df = pd.DataFrame(df_results)
                df.to_csv(output_csv, index=False, encoding='utf-8')
            
            print(f"\n💾 结果已保存: {output_json}")
            print(f"📄 CSV已保存: {output_csv}")
            
            # 总结
            print()
            print("📋 回测总结:")
            print(f"   总交易数: {total_trades}")
            if total_trades > 0:
                print("   ✅ 成功生成交易信号")
            else:
                print("   ⚠️  没有生成任何交易信号")
                print("   可能原因:")
                print("     1. 流动性门槛仍然太高")
                print("     2. 策略条件太严格")
                print("     3. 数据量不足（只有100只股票）")
                print("     4. AKShare数据格式问题")
            
        except Exception as e:
            print(f"❌ 回测失败: {e}")
            import traceback
            traceback.print_exc()
    
    def check_data(self):
        """检查数据可用性"""
        print()
        print("🔍 检查数据可用性...")
        
        import pymongo
        client = pymongo.MongoClient('localhost', 27017)
        db = client['stock_agent']
        
        try:
            # 检查数据
            if 'stock_daily_ak_full_ak' in db.list_collection_names():
                coll = db['stock_daily_ak_full_ak']
                
                # 基本统计
                total = coll.count_documents({})
                distinct_stocks = len(coll.distinct('ts_code'))
                distinct_dates = len(coll.distinct('trade_date'))
                
                print("   数据库检查:")
                print(f"     总记录数: {total}")
                print(f"     唯一股票数: {distinct_stocks}")
                print(f"     交易日数量: {distinct_dates}")
                
                if total > 0:
                    # 检查流动性数据
                    sample = coll.find_one({})
                    if sample:
                        amount = sample.get('amount', 0)
                        print("\n   数据字段检查:")
                        print(f"     成交额(amount): {amount} (AKShare单位: 万元)")
                        print(f"     对应人民币: {amount * 10000:,.0f} 元")
                        
                        if amount > 0:
                            print("     ✅ 有成交额数据")
                        else:
                            print("     ⚠️  成交额为0")
                    
                    # 检查流动性门槛
                    print("\n   流动性门槛分析:")
                    print(f"     设置门槛: {self.liquidity_threshold} 万元")
                    
                    # 统计满足门槛的股票
                    pipeline = [
                        {"$match": {"amount": {"$gte": self.liquidity_threshold}}},
                        {"$group": {"_id": "$ts_code"}}
                    ]
                    
                    liquid_stocks = list(coll.aggregate(pipeline))
                    print(f"     满足门槛的股票数: {len(liquid_stocks)}")
                    
                    if len(liquid_stocks) == 0:
                        print("     ❌ 没有股票满足流动性门槛！")
                        print("     建议降低门槛或检查数据")
                    else:
                        print(f"     ✅ 有 {len(liquid_stocks)} 只股票满足门槛")
                
                else:
                    print("     ❌ 数据库为空")
            
            else:
                print("     ❌ stock_daily_ak_full_ak 集合不存在")
        
        finally:
            client.close()

async def main():
    backtest = FixedAKShareBacktest()
    
    # 先检查数据
    backtest.check_data()
    
    # 运行回测
    await backtest.run()

if __name__ == "__main__":
    asyncio.run(main())