#!/usr/bin/env python3
"""
调试 volume_increase 保存问题
"""

import sys
sys.path.insert(0, '.')

print("🔍 调试 volume_increase 保存问题")
print("=" * 50)

# 测试数据类型转换
import pandas as pd
import numpy as np

# 模拟计算的结果
test_values = {
    'volume_increase': False,  # 布尔值False
    'market_leader': False,    # 布尔值False
    'sentiment_score': 70.0,   # 浮点数
    'hot_sector': False        # 布尔值False
}

print("测试数据:")
for key, val in test_values.items():
    print(f"  {key}: {val} (类型: {type(val)})")

# 模拟类型转换逻辑
converted_update = {}
for key, val in test_values.items():
    if isinstance(val, (bool, np.bool_)):
        print(f"  {key}: 布尔值 -> 转换为float: {float(val)}")
        converted_update[key] = float(val)  # MongoDB中布尔值存为float
    elif isinstance(val, (np.integer,)):
        print(f"  {key}: numpy整数 -> 转换为int: {int(val)}")
        converted_update[key] = int(val)
    elif isinstance(val, (np.floating,)):
        print(f"  {key}: numpy浮点数 -> 转换为float: {float(val)}")
        converted_update[key] = float(val)
    elif pd.isna(val):
        print(f"  {key}: NaN值 -> 跳过")
        continue  # 跳过NaN值
    else:
        print(f"  {key}: 其他类型 -> 保持原样: {val}")
        converted_update[key] = val

print(f"\n转换后结果: {converted_update}")
print(f"converted_update是否为空: {len(converted_update) > 0}")

# 测试实际计算
print("\n" + "=" * 50)
print("测试实际计算流程")

import pandas as pd

# 创建测试数据
data = {
    'ts_code': ['000001.SZ'] * 10,
    'trade_date': [20260101 + i for i in range(10)],
    'vol': [100, 120, 80, 150, 200, 180, 90, 110, 300, 250],  # 第8天放量
    'close': [10.0] * 10
}

df = pd.DataFrame(data)
df['trade_date'] = df['trade_date'].astype(int)

print(f"\n测试数据形状: {df.shape}")

# 计算 volume_increase
if 'vol' in df.columns:
    avg_vol_5d = df['vol'].rolling(5, min_periods=1).mean()
    df['volume_increase'] = df['vol'] > (avg_vol_5d * 1.5)
    
    print(f"\n计算 volume_increase:")
    for i, row in df.iterrows():
        if i >= 5:  # 从第6天开始有5日平均数据
            print(f"  日期 {row['trade_date']}: vol={row['vol']}, 5日均量={avg_vol_5d[i]:.1f}, volume_increase={row['volume_increase']}")

print("\n" + "=" * 50)
print("结论分析:")
print("1. volume_increase 计算正常")
print("2. 布尔值转换正常 (False→0.0)")
print("3. 如果converted_update为空，可能是:")
print("   a) update字典中没有添加volume_increase")
print("   b) 所有字段都是NaN被跳过")
print("   c) 计算失败导致update为空")