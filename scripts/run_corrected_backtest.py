#!/usr/bin/env python3
"""
修正后的AKShare回测脚本
使用修复后的数据（单位：万元）
"""

import sys
import asyncio
from datetime import datetime
import json

# 添加项目路径
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

try:
    from backtest_module.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
    print("✅ 成功导入模块")
except Exception as e:
    print(f"❌ 导入失败: {e}")
    sys.exit(1)

class CorrectedBacktest:
    def __init__(self):
        self.start_date = "20260105"
        self.end_date = "20260320"
        self.initial_capital = 1000000  # 100万
        self.liquidity_threshold = 1000  # 1000万元（单位：万元）
        self.max_position_percent = 20  # 20%
        self.source = "ak"  # 使用AKShare数据源
        self.verbose = True
    
    async def run_strategies_backtest(self):
        """运行五大超短策略回测"""
        print("="*60)
        print("🚀 修正后AKShare回测 (单位：万元)")
        print("="*60)
        print(f"📅 回测区间: {self.start_date} ~ {self.end_date}")
        print(f"💰 初始资金: {self.initial_capital:,} 元")
        print(f"💧 流动性门槛: {self.liquidity_threshold} 万元")
        print(f"📊 单票最大仓位: {self.max_position_percent}%")
        print("="*60)
        
        # 定义五大超短策略
        strategies = [
            {
                "name": "半路追涨",
                "factors": [
                    {"name": "limit_up_yesterday", "target": 1, "weight": 1.0},
                    {"name": "open_below_limit", "target": 1, "weight": 1.0},
                    {"name": "volume_increase", "target": 1, "weight": 1.0}
                ],
                "top_n": 1,
                "position_limit": self.max_position_percent / 100.0
            },
            {
                "name": "涨停开板",
                "factors": [
                    {"name": "limit_up_yesterday", "target": 1, "weight": 1.0},
                    {"name": "first_limit_up", "target": 0, "weight": 1.0}
                ],
                "top_n": 1,
                "position_limit": self.max_position_percent / 100.0
            },
            {
                "name": "跌停翘板",
                "factors": [
                    {"name": "limit_down_yesterday", "target": 1, "weight": 1.0},
                    {"name": "open_above_limit", "target": 1, "weight": 1.0}
                ],
                "top_n": 1,
                "position_limit": self.max_position_percent / 100.0
            },
            {
                "name": "MA5低吸",
                "factors": [
                    {"name": "pullback_ma5", "target": 1, "weight": 1.0}
                ],
                "top_n": 1,
                "position_limit": self.max_position_percent / 100.0
            },
            {
                "name": "龙头低吸",
                "factors": [
                    {"name": "market_leader", "target": 1, "weight": 1.0},
                    {"name": "pullback_ma5", "target": 1, "weight": 1.0},
                    {"name": "lhb_buy_in", "target": 1, "weight": 1.0}
                ],
                "top_n": 1,
                "position_limit": self.max_position_percent / 100.0
            },
            {
                "name": "首板打板",
                "factors": [
                    {"name": "limit_up_yesterday", "target": 1, "weight": 1.0},
                    {"name": "first_limit_up", "target": 1, "weight": 1.0}
                ],
                "top_n": 1,
                "position_limit": self.max_position_percent / 100.0
            }
        ]
        
        print()
        print("📈 策略配置:")
        for i, strategy in enumerate(strategies, 1):
            print(f"  {i}. {strategy['name']} - {strategy['top_n']}只股票")
        
        print()
        print("⏳ 开始回测...")
        
        all_results = {}
        
        for strategy in strategies:
            print(f"\n🧪 测试策略: {strategy['name']}")
            
            try:
                # 创建回测器
                backtester = PortfolioBacktester(source=self.source)
                
                # 配置回测参数
                config = {
                    "start_date": self.start_date,
                    "end_date": self.end_date,
                    "initial_cash": self.initial_capital,
                    "max_position_percent": self.max_position_percent / 100.0,
                    "liquidity_threshold": self.liquidity_threshold,  # 单位：万元，直接使用
                    "factors": strategy["factors"],
                    "top_n": strategy["top_n"],
                    "position_limit": strategy["position_limit"],
                    "stop_loss": -0.05,
                    "take_profit": 0.10
                }
                
                # 运行回测
                result = await backtester.run(config)
                
                if result and "error" not in result:
                    all_results[strategy["name"]] = result
                    # 修正：信号数取调仓记录的数量，绩效数据从performance字段取
                    trade_count = len(result.get('rebalance_records', []))
                    print(f"  ✅ 成功 - 信号数: {trade_count}")
                else:
                    error_msg = result.get('error', '未知错误') if result else '没有结果'
                    print(f"  ❌ 失败: {error_msg}")
            
            except Exception as e:
                print(f"  ❌ 异常: {e}")
        
        return all_results
    
    def analyze_results(self, results):
        """分析回测结果"""
        print()
        print("="*60)
        print("📊 回测结果分析")
        print("="*60)
        
        if not results:
            print("❌ 没有可分析的结果")
            return
        
        total_trades = 0
        profitable_trades = 0
        
        print("\n| Strategy     | Signals | Win Rate | Total Return | Max Drawdown | Sharpe |")
        print("|--------------|---------|----------|--------------|--------------|--------|")
        
        for strategy_name, result in results.items():
            perf = result.get('performance', {})
            trades = len(result.get('rebalance_records', []))
            win_rate = perf.get('win_rate', 0)
            total_return = perf.get('total_return', 0)
            max_drawdown = perf.get('max_drawdown', 0)
            sharpe = perf.get('sharpe_ratio', 0)
            
            # 格式化输出
            print(f"| {strategy_name:<12} | {trades:>7} | {win_rate:>7.1f}% | {total_return:>11.1f}% | {max_drawdown:>11.1f}% | {sharpe:>6.2f} |")
            
            total_trades += trades
            if total_return > 0:
                profitable_trades += 1
        
        print()
        print("📋 总结:")
        print(f"   总策略数: {len(results)} 个")
        print(f"   总信号数: {total_trades} 次")
        print(f"   盈利策略: {profitable_trades} 个")
        
        # 找到最佳策略
        if results:
            best_strategy = max(results.items(), key=lambda x: x[1].get('total_return', -9999))
            best_name = best_strategy[0]
            best_return = best_strategy[1].get('total_return', 0)
            
            print(f"   最佳策略: {best_name} ({best_return:.1f}%)")
        
        return results
    
    def save_results(self, results):
        """保存结果到文件"""
        if not results:
            print("❌ 没有结果可保存")
            return
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # 保存为JSON
        json_file = f"/tmp/corrected_backtest_{timestamp}.json"
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"💾 JSON结果已保存: {json_file}")
        
        # 保存为CSV
        import pandas as pd
        csv_data = []
        for strategy_name, result in results.items():
            perf = result.get('performance', {})
            row = {
                'strategy': strategy_name,
                'signals': len(result.get('rebalance_records', [])),
                'win_rate': perf.get('win_rate', 0),
                'total_return': perf.get('total_return', 0),
                'max_drawdown': perf.get('max_drawdown', 0),
                'sharpe': perf.get('sharpe_ratio', 0)
            }
            csv_data.append(row)
        
        if csv_data:
            df = pd.DataFrame(csv_data)
            csv_file = f"/tmp/corrected_backtest_{timestamp}.csv"
            df.to_csv(csv_file, index=False, encoding='utf-8')
            print(f"📄 CSV结果已保存: {csv_file}")
        
        return json_file, csv_file if 'csv_file' in locals() else None
    
    async def main(self):
        """主函数"""
        print("🔧 AKShare数据修复后回测")
        
        # 运行回测
        results = await self.run_strategies_backtest()
        
        if not results:
            print("❌ 回测失败，没有结果")
            return
        
        # 分析结果
        analyzed = self.analyze_results(results)
        
        # 保存结果
        json_file, csv_file = self.save_results(analyzed)
        
        print()
        print("="*60)
        print("✅ 回测完成!")
        print(f"   JSON文件: {json_file}")
        if csv_file:
            print(f"   CSV文件: {csv_file}")
        print("="*60)

async def main_wrapper():
    """包装主函数"""
    backtest = CorrectedBacktest()
    await backtest.main()

if __name__ == "__main__":
    asyncio.run(main_wrapper())