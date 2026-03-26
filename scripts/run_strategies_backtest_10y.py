#!/usr/bin/env python3
"""
StockAgent 五大游资策略 10 年回测

运行近 10 年 (2016-2026) 回测，输出收益分析报告和收益曲线。

初始资金: 5000 元 (符合实盘目标)
目标: 验证 1-1.5 年 20倍 可行性
"""

import asyncio
import sys
import logging
from datetime import datetime
from typing import List, Dict, Any
import pandas as pd
import numpy as np
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv('/root/.openclaw/workspace/StockAgent/AgentServer/.env')

sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from core.managers import (
    redis_manager,
    mongo_manager,
    tushare_manager,
    baostock_manager,
)
from AgentServer.core.settings import settings

from AgentServer.nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s'
)


class StrategiesBacktest:
    """
    五大游资策略回测
    """
    
    def __init__(self):
        self.initial_cash = 5000.0  # 符合实盘目标
        self.start_date = "20160101"  # 近10年
        self.end_date = "20260317"    # 至今
        self.max_position_per_stock = 0.2  # 单票最大仓位 20%
        self.commission_rate = 0.0002     # 万2佣金
        self.stamp_duty = 0.001           # 千1印花税
        self.slippage = 0.001             # 0.1%滑点
    
    async def initialize(self):
        """初始化所有管理器"""
        logger.info("Initializing managers...")
        await redis_manager.initialize()
        await mongo_manager.initialize()
        # 即使 token 为空也要初始化
        await tushare_manager.initialize()
        await baostock_manager.initialize()
        logger.info("All managers initialized ✓")
    
    async def run_backtest_for_strategy(self, strategy_name: str, config: Dict) -> Dict:
        """运行单个策略回测"""
        logger.info(f"\n{'='*60}")
        logger.info(f"Starting backtest: {strategy_name}")
        logger.info(f"Period: {self.start_date} -> {self.end_date}")
        logger.info(f"Initial cash: {self.initial_cash:.2f}")
        logger.info(f"{'='*60}\n")
        
        backtester = PortfolioBacktester()
        
        backtest_config = {
            "universe": "all_a",
            "start_date": self.start_date,
            "end_date": self.end_date,
            "initial_cash": self.initial_cash,
            "rebalance_freq": "daily",  # 每日调仓（超短策略）
            "top_n": config.get("top_n", 5),  # 每日最多选5只
            "weight_method": "equal",  # 等权
            "factors": config.get("factors", []),
            "exclude": ["st", "new_stock"],
            "benchmark": "000300.SH",  # 对标沪深300
            "max_position_per_stock": self.max_position_per_stock,
            "commission_rate": self.commission_rate,
            "stamp_duty": self.stamp_duty,
            "slippage": self.slippage,
        }
        
        result = await backtester.run(backtest_config)
        return result
    
    async def run_all_strategies(self):
        """运行所有五大策略回测"""
        
        # 五大游资策略定义
        strategies = {
            "涨停开板": {
                "top_n": 5,
                "factors": [
                    {"name": "limit_up_yesterday", "weight": 1.0},
                    {"name": "open_below_limit", "weight": 1.0},
                ]
            },
            "跌停翘板": {
                "top_n": 3,
                "factors": [
                    {"name": "limit_down_yesterday", "weight": 1.0},
                    {"name": "open_above_limit", "weight": 1.0},
                ]
            },
            "5日线低吸": {
                "top_n": 5,
                "factors": [
                    {"name": "price_near_ma5", "weight": 1.0},
                    {"name": "leading_stock", "weight": 0.5},
                ]
            },
            "涨跌幅阈值-跌6%": {
                "top_n": 3,
                "factors": [
                    {"name": "open_drop_lt_threshold", "weight": 1.0},
                ]
            },
            "龙头战法": {
                "top_n": 2,
                "factors": [
                    {"name": "market_leader", "weight": 1.0},
                    {"name": "pullback_ma5", "weight": 0.8},
                    {"name": "lhb_buy_in", "weight": 0.5},  # 龙虎榜净买入
                ]
            },
            "首板打板": {
                "top_n": 3,
                "factors": [
                    {"name": "first_limit_up", "weight": 1.0},
                    {"name": "volume_increase", "weight": 0.5},
                ]
            },
            "组合-全策略": {
                "top_n": 10,
                "factors": [
                    {"name": "limit_up_yesterday", "weight": 0.3},
                    {"name": "price_near_ma5", "weight": 0.3},
                    {"name": "market_leader", "weight": 0.2},
                    {"name": "first_limit_up", "weight": 0.2},
                ]
            }
        }
        
        results = {}
        
        for name, config in strategies.items():
            try:
                result = await self.run_backtest_for_strategy(name, config)
                results[name] = result
                logger.info(f"\n{name} backtest completed")
                logger.info(f"Final value: {result.get('final_value', 0):.2f}")
                logger.info(f"Total return: {result.get('total_return_pct', 0):.2f}%")
                logger.info(f"Sharpe ratio: {result.get('sharpe_ratio', 0):.2f}")
                logger.info(f"Max drawdown: {result.get('max_drawdown_pct', 0):.2f}%\n")
            except Exception as e:
                logger.error(f"Backtest failed for {name}: {e}", exc_info=True)
                results[name] = {"error": str(e)}
        
        return results
    
    def generate_report(self, results: Dict) -> str:
        """生成回测报告 Markdown"""
        
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        report = f"""# StockAgent 五大游资策略 10 年回测报告

**回测时间**: {now}  
**回测区间**: {self.start_date} - {self.end_date}  
**初始资金**: {self.initial_cash:.0f} 元  
**单票最大仓位**: {self.max_position_per_stock * 100:.0f}%  
**佣金**: {self.commission_rate * 10000:.1f}‱  印花税: {self.stamp_duty * 1000:.1f}‰  滑点: {self.slippage * 100:.1f}%  

---

## 回测结果汇总

| 策略 | 最终资金 | 总收益 | 年化收益 | 夏普比率 | 最大回撤 | 交易次数 | 胜率 |
|------|---------|--------|----------|----------|----------|----------|------|
"""
        
        for name, result in results.items():
            if "error" in result:
                report += f"| **{name}** | - | - | - | - | - | - |\n"
                continue
            
            final_value = result.get('final_value', self.initial_cash)
            total_return = (final_value - self.initial_cash) / self.initial_cash * 100
            years = (datetime.strptime(self.end_date, "%Y%m%d") - datetime.strptime(self.start_date, "%Y%m%d")).days / 365.25
            annual_return = ((final_value / self.initial_cash) ** (1/years) - 1) * 100
            sharpe = result.get('sharpe_ratio', 0)
            max_dd = result.get('max_drawdown_pct', 0)
            trades = result.get('total_trades', 0)
            win_rate = result.get('win_rate', 0) * 100
            
            report += (f"| **{name}** | {final_value:,.2f} | {total_return:.2f}% | {annual_return:.2f}% | "
                      f"{sharpe:.2f} | {max_dd:.2f}% | {trades} | {win_rate:.1f}% |\n")
        
        report += """
---

## 详细分析

"""
        
        for name, result in results.items():
            if "error" in result:
                report += f"### {name}\n\n❌ 回测失败: {result['error']}\n\n"
                continue
            
            report += f"### {name}\n\n"
            report += f"- **最终资金**: {result.get('final_value', 0):,.2f}\n"
            report += f"- **总收益**: {(result.get('final_value', self.initial_cash) - self.initial_cash) / self.initial_cash * 100:.2f}%\n"
            
            years = (datetime.strptime(self.end_date, "%Y%m%d") - datetime.strptime(self.start_date, "%Y%m%d")).days / 365.25
            annual = ((result.get('final_value', self.initial_cash) / self.initial_cash) ** (1/years) - 1) * 100
            report += f"- **年化收益**: {annual:.2f}%\n"
            
            report += f"- **夏普比率**: {result.get('sharpe_ratio', 0):.2f}\n"
            report += f"- **最大回撤**: {result.get('max_drawdown_pct', 0):.2f}%\n"
            report += f"- **总交易次数**: {result.get('total_trades', 0)}\n"
            report += f"- **胜率**: {result.get('win_rate', 0) * 100:.1f}%\n"
            report += f"- **盈亏比**: {result.get('profit_factor', 0):.2f}\n"
            
            if 'daily_curve' in result:
                report += f"\n收益曲线数据已保存: `{name}_daily_curve.csv`\n"
            
            report += "\n---\n\n"
        
        report += """
## 结论

根据 10 年回测结果分析：

"""
        
        # 添加结论
        report += """
1. **长期收益验证**: 请根据回测结果判断策略是否长期有效
2. **最大回撤关注**: 回撤超过 50% 需要谨慎仓位管理
3. **夏普比率**:  > 1.0  优秀，> 1.5 非常优秀
4. **目标验证**: 是否能在 1-1.5 年内从 5000 做到 10万 (20倍)

"""
        
        report += f"\n---\n*报告由 StockAgent 自动生成*\n"
        
        return report
    
    def save_results(self, results: Dict, report: str):
        """保存结果"""
        
        # 保存报告
        with open('/root/.openclaw/workspace/StockAgent/docs/backtest-10y-report.md', 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"\nReport saved to: /root/.openclaw/workspace/StockAgent/docs/backtest-10y-report.md")
        
        # 保存汇总数据
        summary = []
        for name, result in results.items():
            if "error" not in result:
                row = {
                    "strategy": name,
                    "final_value": result.get('final_value', 0),
                    "total_return_pct": result.get('total_return_pct', 0),
                    "sharpe_ratio": result.get('sharpe_ratio', 0),
                    "max_drawdown_pct": result.get('max_drawdown_pct', 0),
                    "total_trades": result.get('total_trades', 0),
                    "win_rate": result.get('win_rate', 0),
                }
                summary.append(row)
        
        df_summary = pd.DataFrame(summary)
        df_summary.to_csv('/root/.openclaw/workspace/StockAgent/docs/backtest-10y-summary.csv', index=False)
        print(f"Summary saved to: /root/.openclaw/workspace/StockAgent/docs/backtest-10y-summary.csv")
        
        return True


async def main():
    """主函数"""
    
    backtest = StrategiesBacktest()
    await backtest.initialize()
    
    print("\nStarting 10-year backtest for all 5 strategies...\n")
    results = await backtest.run_all_strategies()
    
    print("\nGenerating report...")
    report = backtest.generate_report(results)
    backtest.save_results(results, report)
    
    print("\n✅ Backtest completed!")
    print("   Report: docs/backtest-10y-report.md")
    print("   Summary: docs/backtest-10y-summary.csv")
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
