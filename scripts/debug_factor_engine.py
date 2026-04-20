#!/usr/bin/env python3
"""
调试因子引擎，检查为什么找不到可交易的股票
"""

import sys
import asyncio

# 添加项目路径
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

from core.managers import (
    redis_manager,
    mongo_manager,
    baostock_manager,
    akshare_manager,
)

from backtest_module.backtest_engine.factor_selection.universe import ExcludeRule
from backtest_module.backtest_engine.factor_selection.factor_engine import FactorEngine

async def debug_factor_engine():
    """调试因子引擎"""
    print("🔧 调试因子引擎")
    print("="*60)
    
    # 初始化管理器
    print("初始化管理器...")
    await redis_manager.initialize()
    await mongo_manager.initialize()
    await baostock_manager.initialize()
    await akshare_manager.initialize()
    
    print("管理器初始化完成 ✓")
    print()
    
    # 创建因子引擎，指定AKShare数据源
    
    # 获取因子列表
    try:
        print("📋 可用因子列表:")
        
        # 获取因子库中的所有因子
        from backtest_module.backtest_engine.factor_selection.factor_library import FactorLibrary
        
        factor_library = FactorLibrary()
        factors = factor_library.factors
        
        for factor_name, factor_info in factors.items():
            print(f"  {factor_name}: {factor_info.get('description', '无描述')}")
        
        print()
        
    except Exception as e:
        print(f"获取因子列表失败: {e}")
    
    # 选择一个特定的交易日进行测试
    test_date = "20260105"
    
    print(f"🧪 测试特定交易日: {test_date}")
    print()
    
    try:
        # 测试获取可用股票
        print("1. 测试获取可用股票...")
        from backtest_module.backtest_engine.factor_selection.universe import UniverseManager
        
        universe_mgr = UniverseManager()
        
        # 尝试获取该交易日的可用股票
        print(f"  尝试获取交易日 {test_date} 的可用股票...")
        stocks = await universe_mgr.get_tradable_stocks(test_date, liquidity_threshold=100, exclude_rules=[ExcludeRule.ST, ExcludeRule.NEW_STOCK])
        
        if stocks:
            print(f"  成功获取 {len(stocks)} 只股票:")
            for stock in stocks[:10]:  # 只显示前10只
                print(f"    {stock}")
        else:
            print("  ⚠️  没有找到可用股票")
            
            # 检查具体原因
            print("  可能原因:")
            
            # 检查流动性门槛
            print("  - 流动性门槛太高 (100万元)")
            
            # 检查数据是否存在
            import pymongo
            client = pymongo.MongoClient('localhost', 27017)
            db = client['stock_agent']
            collection = db['stock_daily_ak_full_ak']
            
            # 检查该交易日是否有数据
            records = list(collection.find({'trade_date': int(test_date)}))
            print(f"  - 该交易日数据库记录数: {len(records)}")
            
            if len(records) > 0:
                print("  - 流动性数据示例 (前5只股票):")
                for i, record in enumerate(records[:5], 1):
                    amount = record.get('amount', 0)
                    ts_code = record.get('ts_code', 'N/A')
                    print(f"    {i}. {ts_code}: 成交额 {amount:,.2f} 万元")
                    
                    # 检查是否满足流动性门槛
                    if amount >= 100:
                        print("       ✅ 满足门槛 (100万元)")
                    else:
                        print("       ❌ 不满足门槛 (100万元)")
            
            client.close()
    
    except Exception as e:
        print(f"  测试失败: {e}")
        import traceback
        traceback.print_exc()
    
    print()
    print("="*60)
    
    # 关闭连接
    await baostock_manager.shutdown()
    await akshare_manager.shutdown()
    await mongo_manager.shutdown()
    await redis_manager.shutdown()
    
    print("✅ 调试完成")

async def main():
    await debug_factor_engine()

if __name__ == "__main__":
    asyncio.run(main())