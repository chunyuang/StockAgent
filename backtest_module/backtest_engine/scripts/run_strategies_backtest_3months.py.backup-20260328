#!/usr/bin/env python3
"""
StockAgent 五大游资策略 3个月回归测试

运行区间: {start_date} ~ {end_date}
初始资金: {initial_cash:,.0f}
手续费: 佣金 {commission_rate*10000:.2f}‰ + 印花税 {stamp_duty*1000:.1f}‰ + 滑点 {slippage*1000:.1f}‰
单票最大仓位: {max_position*100:.0f}%
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
    五大游资策略回测 - 三个月版本
    """
    
    def __init__(self):
        self.initial_cash = 100000.0  # 10万初始资金方便统计
        self.start_date = "20260105"  # 近三个月开始
        self.end_date = "20260320"    # 近三个月结束
        self.max_position_per_stock = 0.2  # 单票最大仓位 20%
        self.commission_rate = 0.0002     # 佣金万二
        self.stamp_duty = 0.001      # 印花税千一
        self.slippage = 0.001        # 0.1% 滑点
    
    async def initialize(self):
        """初始化所有管理器"""
        logger.info("Initializing managers...")
        await redis_manager.initialize()
        await mongo_manager.initialize()
        # 即使 token 为空也要初始化，tushare_manager 自己会处理
        await tushare_manager.initialize()
        await baostock_manager.initialize()
        logger.info("All managers initialized ✓")
    
    async def run_backtest_for_strategy(self, strategy_name: str, config: Dict) -> Dict:
        """运行单个策略回测"""
        logger.info(f"\n{'='*60}")
        logger.info(f"Starting backtest: {strategy_name}")
        logger.info(f"  Period: {self.start_date} -> {self.end_date}")
        logger.info(f"  Initial cash: {self.initial_cash:.2f}")
        logger.info(f"{'='*60}\n")
        
        # Tushare 版本数据源标记为 "ts"，只查询 Tushare 下载的数据
        backtester = PortfolioBacktester(source="ts")
        
        backtest_config = {
            "universe": "all_a",
            "start_date": self.start_date,
            "end_date": self.end_date,
            "initial_cash": self.initial_cash,
            "rebalance_freq": "daily",  # 每日调仓（超短策略）
            "top_n": config.get("top_n", 5),  # 每日最多选N只
            "weight_method": "equal",  # 等权配置
            "factors": config.get("factors", []),
            "exclude": ["st", "new_stock"],
            "benchmark": "000300.SH",  # 对标沪深300
            "max_position_per_stock": self.max_position_per_stock,
            "commission_rate": self.commission_rate,
            "stamp_duty": self.stamp_duty,
            "slippage": self.slippage,
        }
        
        result = await backtester.run(backtest_config)
        result["strategy_name"] = strategy_name
        return result
    
    async def run_all_strategies(self) -> List[Dict]:
        """运行所有五大策略回测"""
        
        # 五大游资策略定义
        strategies = {
            "半路追涨": {
                "top_n": 5,
                "factors": [
                    {"name": "limit_up_yesterday", "weight": 1.0},
                    {"name": "open_below_limit", "weight": 1.0},
                ],
            },
            "涨停开板": {
                "top_n": 5,
                "factors": [
                    {"name": "limit_up_yesterday", "weight": 1.0},
                    {"name": "open_below_limit", "weight": 1.0},
                ],
            },
            "跌停翘板": {
                "top_n": 3,
                "factors": [
                    {"name": "limit_down_yesterday", "weight": 1.0},
                    {"name": "open_above_limit", "weight": 1.0},
                ],
            },
            "MA5低吸": {
                "top_n": 5,
                "factors": [
                    {"name": "price_near_ma5", "weight": 1.0},
                    {"name": "leading_stock", "weight": 0.5},
                ],
            },
            "龙头低吸": {
                "top_n": 2,
                "factors": [
                    {"name": "market_leader", "weight": 1.0},
                    {"name": "pullback_ma5", "weight": 0.8},
                    {"name": "lhb_buy_in", "weight": 0.5},  # 龙虎榜净买入
                ],
            },
            "首板打板": {
                "top_n": 3,
                "factors": [
                    {"name": "first_limit_up", "weight": 1.0},
                    {"name": "volume_increase", "weight": 0.5},
                ],
            },
        }
        
        all_results = []
        
        for strategy_name, config in strategies.items():
            try:
                result = await self.run_backtest_for_strategy(strategy_name, config)
                all_results.append(result)
                
                # 打印当前结果
                logger.info(f"\n{'='*60}")
                logger.info(f"Backtest result for {strategy_name}:")
                logger.info(f"  Total return: {result.get('total_return_pct', 0):.2f}%")
                logger.info(f"  Sharpe ratio: {result.get('sharpe_ratio', 0):.2f}")
                logger.info(f"  Max drawdown: {result.get('max_drawdown_pct', 0):.2f}%")
                logger.info(f"  Win rate: {result.get('win_rate', 0)*100:.2f}%")
                logger.info(f"  Total trades: {result.get('total_trades', 0)}")
                logger.info(f"{'='*60}")
            except Exception as e:
                logger.error(f"Backtest failed for {strategy_name}: {e}", exc_info=True)
                continue
        
        return all_results


def print_final_report(all_results: List[Dict], start_date: str, end_date: str, initial_cash: float, commission_rate: float, stamp_duty: float, slippage: float, max_position: float):
    """打印最终汇总报告"""
    print("\n")
    print("=" * 80)
    print(f"📊  StockAgent 五大策略 {start_date} ~ {end_date} 回归测试 最终报告")
    print(f"    初始资金: {initial_cash:,.0f}")
    print(f"    手续费: 佣金 {commission_rate*10000:.2f}‰ + 印花税 {stamp_duty*1000:.1f}‰ + 滑点 {slippage*1000:.1f}‰")
    print(f"    单票最大仓位: {max_position*100:.0f}%")
    print("=" * 80)
    print()
    
    print(f"| {'Strategy':<12s} | {'signals':>6s} | {'winrate':>6s} | {'avg return':>12s} | {'max drawdown':>7s} | {'total return':>7s} | {'sharpe':>7s} |")
    print(f"|{'-------'}|{'-------'}|{'-------'}|{'-------------'}|{'---------------'}|{'-----------'}|{'-------'}|{'-------'}|")
    for result in sorted(all_results, key=lambda x: x.get('win_rate', 0), reverse=True):
        name = result['strategy_name'].ljust(12)
        trades = f"{result.get('total_trades', 0):,d}".rjust(6)
        win_rate = f"{result.get('win_rate', 0)*100:.2f}%".rjust(6)
        avg_return = f"{result.get('avg_daily_return_pct', 0):+.3f}%".rjust(12)
        max_dd = f"{result.get('max_drawdown_pct', 0):.2f}%".rjust(7)
        total_ret = f"{result.get('total_return_pct', 0):+.2f}%".rjust(7)
        sharpe = f"{result.get('sharpe_ratio', 0):.2f}".rjust(7)
        print(f"| {name} | {trades} | {win_rate} | {avg_return} | {max_dd} | {total_ret} | {sharpe} |")
    print(f"{'-------'}|{'-------'}|{'-------'}|{'-------------'}|{'---------------'}|{'-----------'}|{'-------'}|")
    print("\n" + "=" * 80)
    print("\n✅ 回归测试完成!")


async def main():
    """主函数"""
    backtest = StrategiesBacktest()
    await backtest.initialize()
    all_results = await backtest.run_all_strategies()
    print_final_report(
        all_results, 
        backtest.start_date, 
        backtest.end_date, 
        backtest.initial_cash, 
        backtest.commission_rate, 
        backtest.stamp_duty, 
        backtest.slippage, 
        backtest.max_position_per_stock
    )
    
    # 保存结果到文件
    df = pd.DataFrame([
        {
            "strategy": r["strategy_name"],
            "total_trades": r.get("total_trades", 0),
            "win_rate": r.get("win_rate", 0) * 100,
            "avg_daily_return_pct": r.get("avg_daily_return_pct", 0),
            "max_drawdown_pct": r.get("max_drawdown_pct", 0),
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
