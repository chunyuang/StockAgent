#!/usr/bin/env python3
import asyncio
import sys
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from core.settings import settings
from core.managers.tushare_manager import tushare_manager

async def test():
    print("=== Testing after fix ===\n")
    
    await tushare_manager.initialize()
    
    result = await tushare_manager.get_trade_cal("20260105", "20260320")
    
    print(f"start=20260105, end=20260320")
    print(f"got {len(result)} trading days")
    if len(result) > 0:
        print(f"first 10: {result[:10]}")
        print("\n✅ 测试成功！")
    else:
        print("\n❌ 测试失败，结果为空")

if __name__ == "__main__":
    asyncio.run(test())
