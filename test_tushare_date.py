#!/usr/bin/env python3
"""
测试 Tushare 自定义节点 - 按日期获取
测试日期: 20260105
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'AgentServer'))

import asyncio
import pandas as pd
from core.managers.tushare_manager import tushare_manager

async def test_date_fetch():
    print("=== 测试 Tushare 按日期获取 ===")
    print(f"测试日期: 20260105")
    print()
    
    # 初始化
    await tushare_manager.initialize()
    
    if not tushare_manager._initialized:
        print("❌ 初始化失败")
        return
    
    print("✅ 初始化成功")
    print()
    
    # 获取日线数据
    result = await tushare_manager.get_daily(trade_date="20260105")
    
    print(f"获取到 {len(result)} 条记录")
    print()
    
    if len(result) > 0:
        print("前 5 条记录样例:")
        df = pd.DataFrame(result[:5])
        print(df[['ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'vol', 'amount']].to_string(index=False))
        print()
        print(f"✅ 按日期获取测试成功!")
    else:
        print("❌ 获取失败，没有记录")
    
    # 测试获取涨跌停列表
    print("\n=== 测试涨跌停数据 ===")
    limit_data = await tushare_manager.get_limit_list_d(trade_date="20260105")
    print(f"获取到 {len(limit_data)} 条涨跌停记录")
    if len(limit_data) > 0:
        print(f"涨停记录: {len([d for d in limit_data if d['limit'] == 'U'])}")
        print(f"跌停记录: {len([d for d in limit_data if d['limit'] == 'D'])}")
        print("✅ 涨跌停获取成功!")

if __name__ == "__main__":
    asyncio.run(test_date_fetch())
