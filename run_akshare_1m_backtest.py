#!/usr/bin/env python3
"""
AKShare数据源回测 - 初始资金100万
回测区间: 2026-01-05 ~ 2026-03-20
"""
import sys
import asyncio
import os

# 设置正确的初始资金
os.environ['INITIAL_CAPITAL'] = '1000000'  # 100万

sys.path.insert(0, '/root/.openclaw/workspace')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from backtest_module.backtest_engine.scripts.run_strategies_backtest_3months_akshare_only import main

if __name__ == "__main__":
    print("="*60)
    print("🚀 AKShare数据源回测启动")
    print("="*60)
    print("📅 回测区间: 2026-01-05 ~ 2026-03-20")
    print("💰 初始资金: 1,000,000 元")
    print("📊 数据源: AKShare (物理隔离)")
    print("="*60)
    
    asyncio.run(main())