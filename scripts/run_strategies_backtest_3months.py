#!/usr/bin/env python3
"""
StockAgent 五大游资策略 3个月回归测试

运行近 3个月 (2025-12-24 - 2026-03-24) 回测，输出收益分析报告。

目标: 验证策略逻辑在近期的有效性，统计胜率和平均收益。
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
from core.settings import settings

# 直接导入回测模块，绕过 nodes/__init__.py
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer/nodes')
from backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s'
)


class StrategiesBacktest:
    """
    五大游资策略回测 - 3个月版本
    """
    
    def __init__(self):
        self.initial_cash = 100000.0  # 10万初始资金方便统计
        self.start_date = "20251224"  # 近3个月开始
        self.end_date = "20260324"    # 至今
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
            "top_n": config.get("top_n", 5),  # 每日最多选N只
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
            "半路追涨": {
                "top_n": 5,
                "factors": [
                    {"name": "limit_up_yesterday", "weight": 1.0},
                    {"name": "open_below_limit", "weight": 1.0},
                ]
            },
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
            "MA5低吸": {
                "top_n": 5,
                "factors": [
                    {"name": "price_near_ma5", "weight": 1.0},
                    {"name": "leading_stock", "weight": 0.5},
                ]
            },
            "龙头低吸": {
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
        }
        
        all_results = []
        
        for strategy_name, config in strategies.items():
            try:
                result = await self.run_backtest_for_strategy(strategy_name, config)
                result["strategy_name"] = strategy_name
                all_results.append(result)
                
                # 打印当前结果
                logger.info(f"\n{'='*60}")
                logger.info(f"Backtest result for {strategy_name}:")
                logger.info(f"  Total return: {result.get('total_return_pct', 0):.2f}%")
                logger.info(f"  Sharpe ratio: {result.get('sharpe_ratio', 0):.2f}")
                logger.info(f"  Max drawdown: {result.get('max_drawdown', 0):.2f}%")
                logger.info(f"  Win rate: {result.get('win_rate', 0):.2f}%")
                logger.info(f"  Total trades: {result.get('total_trades', 0)}")
                logger.info(f"{'='*60}")
            except Exception as e:
                logger.error(f"Backtest failed for {strategy_name}: {e}", exc_info=True)
                continue
        
        return all_results


def print_final_report(all_results: List[Dict]):
    """打印最终汇总报告"""
    print("\n")
    print("=" * 80)
    print("📊  StockAgent 五大策略 3个月回归测试 最终报告")
    print(f"    回测区间: 2025-12-24 ~ 2026-03-24")
    print("    初始资金: 100,000")
    print("    手续费: 佣金万2 + 印花税千1 + 滑点0.1%")
    print("    单票最大仓位: 20%")
    print("=" * 80)
    print("\n")
    
    print(f"| 策略         | 信号数 | 胜率    | 平均次日涨幅 | 最大回撤 | 总收益   | 夏普比率 |")
    print(f"|--------------|-------:|--------:|-------------:|---------:|---------:|---------:|")
    
    for result in sorted(all_results, key=lambda x: x.get('win_rate', 0), reverse=True):
        name = result['strategy_name'].ljust(12)
        trades = f"{result.get('total_trades', 0):>6d}"
        win_rate = f"{result.get('win_rate', 0)*100:.2f}%"
        avg_pct = f"{result.get('avg_daily_return_pct', 0):+.3f}%"
        max_dd = f"{result.get('max_drawdown', 0):.2f}%"
        total_ret = f"{result.get('total_return_pct', 0):+.2f}%"
        sharpe = f"{result.get('sharpe_ratio', 0):.2f}"
        print(f"| {name} | {trades} | {win_rate:>7} | {avg_pct:>12} | {max_dd:>7} | {total_ret:>7} | {sharpe:>7} |")
    
    print("\n" + "=" * 80)
    print("\n✅ 回归测试完成！")


async def main():
    """主函数"""
    backtest = StrategiesBacktest()
    await backtest.initialize()
    all_results = await backtest.run_all_strategies()
    print_final_report(all_results)
    
    # 保存结果到文件
    df = pd.DataFrame([
        {
            "strategy": r["strategy_name"],
            "total_trades": r.get("total_trades", 0),
            "win_rate": r.get("win_rate", 0) * 100,
            "avg_daily_return_pct": r.get("avg_daily_return_pct", 0),
            "max_drawdown": r.get("max_drawdown", 0),
            "total_return_pct": r.get("total_return_pct", 0),
            "sharpe_ratio": r.get("sharpe_ratio", 0),
        }
        for r in all_results
    ])
    
    output_file = f"/tmp/backtest_result_3months_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    df.to_csv(output_file, index=False)
    logger.info(f"\nResults saved to: {output_file}")
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
