#!/usr/bin/env python3
"""
测试因子计算功能是否正常工作
"""

import sys
sys.path.insert(0, '.')

print("🔍 测试因子计算功能")
print("=" * 50)

# 1. 测试能否导入因子计算函数
try:
    from nodes.backtest_engine.factor_selection.factor_auto_compute import _compute_factors_for_stock
    print("✅ 成功导入 _compute_factors_for_stock")
except Exception as e:
    print(f"❌ 导入失败: {e}")
    sys.exit(1)

# 2. 创建测试数据
import pandas as pd
import numpy as np

print("\n📊 创建测试数据...")
data = {
    'ts_code': ['000001.SZ'] * 10,
    'trade_date': [20260101 + i for i in range(10)],
    'open': [10.0] * 10,
    'high': [11.0] * 10,
    'low': [9.0] * 10,
    'close': [10.0, 10.2, 9.8, 10.5, 10.8, 10.3, 9.9, 10.1, 10.6, 10.4],
    'vol': [100, 120, 80, 150, 200, 180, 90, 110, 300, 250],  # 第8天放量
    'amount': [1000, 1224, 784, 1575, 2160, 1854, 891, 1111, 3180, 2600],
    'pct_chg': [0.0, 2.0, -2.0, 5.0, 3.0, -1.0, -2.0, 1.0, 4.0, -1.0]
}

df = pd.DataFrame(data)
print(f"测试数据形状: {df.shape}")
print(df[['trade_date', 'vol', 'close', 'pct_chg']].to_string())

# 3. 测试计算新修复的因子
print("\n🔧 测试计算新修复的因子...")
new_factors = ['volume_increase', 'market_leader', 'hot_sector', 'sentiment_score']

try:
    result = _compute_factors_for_stock(df, new_factors)
    print(f"✅ 计算成功！结果形状: {result.shape}")
    
    print("\n📈 计算结果:")
    for factor in new_factors:
        if factor in result.columns:
            # 取最后一天的值
            last_value = result[factor].iloc[-1]
            print(f"  {factor}: {last_value}")
        else:
            print(f"  {factor}: ❌ 未计算")
    
    # 显示详细的 volume_increase 计算
    print("\n🔍 volume_increase 详细计算:")
    if 'volume_increase' in result.columns:
        for i in range(5, len(result)):
            trade_date = result['trade_date'].iloc[i]
            vol = result['vol'].iloc[i]
            vol_increase = result['volume_increase'].iloc[i]
            
            # 计算5日平均成交量
            if i >= 5:
                avg_vol_5d = result['vol'].iloc[i-5:i].mean()
                ratio = vol / avg_vol_5d if avg_vol_5d > 0 else 0
                print(f"  日期 {trade_date}: vol={vol:.0f}, 5日均量={avg_vol_5d:.1f}, 倍数={ratio:.2f}, 放量标记={vol_increase}")
    
except Exception as e:
    print(f"❌ 计算失败: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 50)
print("✅ 测试完成")
print("\n结论:")
print("1. 如果因子计算成功 → daily_factor_precompute.py 修复有效")
print("2. 如果计算失败 → 需要检查 _compute_factors_for_stock 函数")
print("3. 修复后，MongoDB中的因子数据将被正确计算和写入")