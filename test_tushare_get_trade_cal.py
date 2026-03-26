#!/usr/bin/env python3
"""
测试修复后的 get_trade_cal
"""

import asyncio
import sys

sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from core.managers.tushare_manager import tushare_manager

async def test():
    print("=== Testing get_trade_cal after fix ===")
    print()
    
    await tushare_manager.initialize()
    
    start_date = "20260105"
    end_date = "20260320"
    
    result = await tushare_manager.get_trade_cal(start_date, end_date)
    
    print(f"start_date={start_date}, end_date={end_date}")
    print(f"Got {len(result)} trading days")
    print()
    if len(result) > 0:
        print(f"First 10: {result[:10]}")
        print()
        print("✅ 测试成功！")
    else:
        print("❌ 获取失败，结果为空")

if __name__ == "__main__":
    asyncio.run(test())
