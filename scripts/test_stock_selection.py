#!/usr/bin/env python3
"""
独立快速选股测试脚本
- 只测试选股逻辑，不执行完整回测
- 选取少量交易日验证是否能选出符合条件的股票
- 和正式回测脚本完全隔离
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pymongo
from backtest_module.backtest_engine.factor_selection.factor_calculator import FactorCalculator
from backtest_module.backtest_engine.config import BacktestConfig

# 数据库连接
client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']
coll = db['stock_daily_ak_full']

# 回测配置
config = BacktestConfig(
    start_date=20260318,  # 只测试最后3天，快速出结果
    end_date=20260320,
    initial_capital=1000000,
    liquidity_threshold=1000,  # 1000万成交额门槛
    max_position_per_stock=0.2,
    slippage=0.001,
    commission_rate=0.0002,
    stamp_duty_rate=0.001,
    min_commission=5,
    max_total_position=0.8
)

# 获取交易日列表
trade_dates = sorted(coll.distinct('trade_date', {
    'trade_date': {'$gte': config.start_date, '$lte': config.end_date}
}))
print(f"📅 测试交易日: {trade_dates}")

async def main():
    factor_calculator = FactorCalculator(config)
    
    for trade_date in trade_dates:
        print(f"\n{'='*60}")
        print(f"📅 交易日: {trade_date}")
        print(f"{'='*60}")
        
        # 获取所有股票数据
        stocks = coll.distinct('ts_code')
        print(f"📊 当日待筛选股票数: {len(stocks)}只")
        
        # 计算因子
        all_factors = []
        for ts_code in stocks:
            # 获取该股票最新数据
            stock_data = list(coll.find({
                'ts_code': ts_code,
                'trade_date': {'$lte': trade_date}
            }).sort('trade_date', -1).limit(30))  # 取最近30天数据计算因子
            
            if len(stock_data) < 10:  # 数据不足跳过
                continue
                
            # 转为DataFrame
            import pandas as pd
            df = pd.DataFrame(stock_data)
            df = df.sort_values('trade_date').reset_index(drop=True)
            
            # 计算因子
            factors = factor_calculator.calculate(df, trade_date)
            if not factors:
                continue
                
            factors['ts_code'] = ts_code
            all_factors.append(factors)
        
        print(f"✅ 完成因子计算，有效股票数: {len(all_factors)}只")
        
        # 测试半路追涨策略条件：limit_up_yesterday=1 AND open_below_limit=1 AND amount >= 1000
        banlu_candidates = [
            f for f in all_factors 
            if f.get('limit_up_yesterday', 0) == 1 
            and f.get('open_below_limit', 0) == 1
            and f.get('amount', 0) >= config.liquidity_threshold
        ]
        print(f"🚀 半路追涨候选股数: {len(banlu_candidates)}只")
        if banlu_candidates:
            for item in banlu_candidates[:10]:
                print(f"  ✅ {item['ts_code']} 成交额: {item['amount']:.0f}万")
        
        # 测试首板打板策略条件：limit_up_yesterday=1 AND first_limit_up=1 AND amount >= 1000
        shouban_candidates = [
            f for f in all_factors 
            if f.get('limit_up_yesterday', 0) == 1 
            and f.get('first_limit_up', 0) == 1
            and f.get('amount', 0) >= config.liquidity_threshold
        ]
        print(f"🚀 首板打板候选股数: {len(shouban_candidates)}只")
        if shouban_candidates:
            for item in shouban_candidates[:10]:
                print(f"  ✅ {item['ts_code']} 成交额: {item['amount']:.0f}万")
        
        # 测试MA5低吸策略条件：ma5_support=1 AND amount >= 1000
        ma5_candidates = [
            f for f in all_factors 
            if f.get('ma5_support', 0) == 1
            and f.get('amount', 0) >= config.liquidity_threshold
        ]
        print(f"🚀 MA5低吸候选股数: {len(ma5_candidates)}只")
        if ma5_candidates:
            for item in ma5_candidates[:10]:
                print(f"  ✅ {item['ts_code']} 成交额: {item['amount']:.0f}万")

if __name__ == "__main__":
    asyncio.run(main())
