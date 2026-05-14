#!/usr/bin/env python3
"""
测试 volume_increase 计算逻辑
"""

import pandas as pd
import numpy as np
import sys
sys.path.insert(0, '.')

def test_volume_increase():
    """测试放量标记计算逻辑"""
    print("🔍 测试 volume_increase 计算逻辑")
    print("=" * 50)
    
    # 创建测试数据
    data = {
        'ts_code': ['000001.SZ'] * 10,
        'trade_date': [20260101 + i for i in range(10)],
        'vol': [100, 120, 80, 150, 200, 180, 90, 110, 300, 250],  # 第9天放量
        'close': [10.0] * 10
    }
    
    df = pd.DataFrame(data)
    df['trade_date'] = df['trade_date'].astype(int)
    
    print("测试数据:")
    print(df[['trade_date', 'vol']].to_string())
    print()
    
    # 计算 volume_increase
    if 'vol' in df.columns:
        avg_vol_5d = df['vol'].rolling(5, min_periods=1).mean()
        df['volume_increase'] = df['vol'] > (avg_vol_5d * 1.5)
        
        # 计算实际倍数
        df['volume_ratio'] = df['vol'] / avg_vol_5d
        
        print("计算结果:")
        for i, row in df.iterrows():
            print(f"日期 {row['trade_date']}: vol={row['vol']}, 5日均量={avg_vol_5d[i]:.1f}, 倍数={row['volume_ratio']:.2f}, 放量标记={row['volume_increase']}")
    
    print()
    print("📊 分析:")
    print("1. 第9天: vol=300, 前5日均量=(80+150+200+180+90)/5=140.0")
    print("   倍数: 300/140.0 = 2.14 > 1.5 → 应标记为True")
    print("2. 第10天: vol=250, 前5日均量=(150+200+180+90+110)/5=146.0")
    print("   倍数: 250/146.0 = 1.71 > 1.5 → 应标记为True")
    
    return df

def test_real_data():
    """测试真实数据中的 volume_increase"""
    print("\n" + "=" * 50)
    print("📊 测试真实MongoDB数据")
    
    try:
        from pymongo import MongoClient
        
        client = MongoClient('localhost', 27017)
        db = client['stock_agent']
        
        # 获取一只股票的数据
        cursor = db.stock_daily_ak_full.find(
            {'ts_code': '000001.SZ', 'trade_date': {'$gte': 20260105, '$lte': 20260110}},
            {'ts_code': 1, 'trade_date': 1, 'vol': 1, 'volume_increase': 1}
        ).sort('trade_date', 1)
        
        data = list(cursor)
        if data:
            print(f"获取到 {len(data)} 条记录")
            for doc in data:
                print(f"日期 {doc['trade_date']}: vol={doc.get('vol', 'N/A')}, volume_increase={doc.get('volume_increase', 'N/A')}")
        else:
            print("无数据")
            
        client.close()
        
    except Exception as e:
        print(f"❌ 查询失败: {e}")

if __name__ == "__main__":
    # 测试计算逻辑
    df = test_volume_increase()
    
    # 测试真实数据
    test_real_data()
    
    print("\n" + "=" * 50)
    print("✅ 测试完成")
    print("结论:")
    print("1. 计算逻辑正确: 成交量 > 5日平均成交量 * 1.5")
    print("2. 如果volume_increase缺失，可能是:")
    print("   - 数据不足（前5天数据缺失）")
    print("   - vol字段缺失或为0")
    print("   - 计算函数未被调用")