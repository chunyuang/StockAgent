#!/usr/bin/env python3
"""
最简化全市场AKShare回测脚本
100%使用全市场5490只A股，绕过所有默认小股票池配置
"""
import sys
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')

import pymongo
import pandas as pd
from backtest_module.backtest_engine.factor_selection.factor_calculator import FactorCalculator
from backtest_module.backtest_engine.config import BacktestConfig

# 数据库连接
client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['stock_agent']
coll = db['stock_daily_ak_full']

# 回测配置
config = BacktestConfig(
    start_date=20260106,
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

# 先获取全市场股票列表和所有交易日
print("🚀 全市场AKShare回测启动")
print("="*70)
all_stocks = sorted(coll.distinct('ts_code'))
all_dates = sorted(coll.distinct('trade_date', {
    'trade_date': {'$gte': config.start_date, '$lte': config.end_date}
}))
print(f"📊 全市场股票数: {len(all_stocks)}只")
print(f"📅 回测交易日: {len(all_dates)}天")
print(f"💵 初始资金: {config.initial_capital:,}元")
print("="*70)

# 预加载所有股票数据到内存，加速计算
print("⏳ 预加载全市场数据...")
all_data = {}
for ts_code in all_stocks:
    data = list(coll.find({
        'ts_code': ts_code,
        'trade_date': {'$gte': 20260101, '$lte': config.end_date}
    }).sort('trade_date', 1))
    if len(data) >= 30:  # 至少有30天数据
        df = pd.DataFrame(data)
        df = df.sort_values('trade_date').reset_index(drop=True)
        all_data[ts_code] = df
print(f"✅ 预加载完成，有效股票数: {len(all_data)}只")

# 初始化因子计算器
factor_calculator = FactorCalculator(config)

# 统计每日候选股
print("\n📈 开始选股统计：")
print("="*70)

total_candidates = {
    '半路追涨': 0,
    '首板打板': 0,
    'MA5低吸': 0
}

for idx, trade_date in enumerate(all_dates):
    print(f"\n📅 {trade_date} ({idx+1}/{len(all_dates)})")
    
    # 计算当日所有股票的因子
    candidates_banlu = []
    candidates_shouban = []
    candidates_ma5 = []
    
    for ts_code, df in all_data.items():
        # 找到当前日期的位置
        pos = df[df['trade_date'] == trade_date].index
        if len(pos) == 0:
            continue
        pos = pos[0]
        if pos < 10:  # 需要至少前10天数据计算因子
            continue
            
        # 取截止到当日的历史数据
        history_df = df.iloc[:pos+1].copy()
        
        # 计算因子
        factors = factor_calculator.calculate(history_df, trade_date)
        if not factors:
            continue
            
        # 半路追涨条件
        if (factors.get('limit_up_yesterday', 0) == 1 
            and factors.get('open_below_limit', 0) == 1
            and factors.get('amount', 0) >= config.liquidity_threshold):
            candidates_banlu.append(ts_code)
            
        # 首板打板条件
        if (factors.get('limit_up_yesterday', 0) == 1 
            and factors.get('first_limit_up', 0) == 1
            and factors.get('amount', 0) >= config.liquidity_threshold):
            candidates_shouban.append(ts_code)
            
        # MA5低吸条件
        if (factors.get('pullback_ma5', 0) == 1
            and factors.get('amount', 0) >= config.liquidity_threshold):
            candidates_ma5.append(ts_code)
    
    print(f"  半路追涨候选: {len(candidates_banlu)}只")
    print(f"  首板打板候选: {len(candidates_shouban)}只")
    print(f"  MA5低吸候选: {len(candidates_ma5)}只")
    
    total_candidates['半路追涨'] += len(candidates_banlu)
    total_candidates['首板打板'] += len(candidates_shouban)
    total_candidates['MA5低吸'] += len(candidates_ma5)

print("\n" + "="*70)
print("📊 最终统计结果")
print("="*70)
print("总候选股数:")
print(f"  半路追涨: {total_candidates['半路追涨']}只")
print(f"  首板打板: {total_candidates['首板打板']}只")
print(f"  MA5低吸: {total_candidates['MA5低吸']}只")
print("\n✅ 全市场选股验证完成！")
