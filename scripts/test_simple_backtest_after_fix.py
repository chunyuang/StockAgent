#!/usr/bin/env python3
"""
简化回测测试 - 验证兼容性修复后是否能找到股票
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

from backtest_module.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
from backtest_module.backtest_engine.factor_selection.universe import UniverseManager, ExcludeRule
from backtest_module.backtest_engine.factor_selection.factor_engine import FactorEngine

async def test_simple_backtest():
    """运行简化回测测试"""
    print("🧪 简化回测测试 (验证兼容性修复)")
    print("="*60)
    
    # 配置
    start_date = "20260105"
    end_date = "20260110"  # 只测试5个交易日
    initial_capital = 1000000
    liquidity_threshold = 100  # 降低到100万元
    max_position_percent = 20
    
    print(f"📅 测试区间: {start_date} ~ {end_date}")
    print(f"💰 初始资金: {initial_capital:,} 元")
    print(f"💧 流动性门槛: {liquidity_threshold} 万元")
    print(f"📊 单票最大仓位: {max_position_percent}%")
    print()
    
    # 初始化管理器
    print("初始化管理器...")
    await redis_manager.initialize()
    await mongo_manager.initialize()
    await baostock_manager.initialize()
    await akshare_manager.initialize()
    
    print("管理器初始化完成 ✓")
    print()
    
    # 创建因子引擎 - 使用默认数据源
    factor_engine = FactorEngine()  # 不指定source，使用默认
    
    # 创建宇宙管理器
    universe_mgr = UniverseManager()
    
    # 获取调仓日期
    rebalance_dates = await baostock_manager.get_trade_dates(start_date, end_date)
    if not rebalance_dates:
        print("❌ 无法获取交易日历")
        return
    
    rebalance_dates = sorted(rebalance_dates)
    print(f"总调仓日期: {len(rebalance_dates)}")
    print(f"调仓日期: {rebalance_dates[:5]}...")
    print()
    
    # 测试1: 检查是否能找到可交易的股票
    print("测试1: 检查是否能找到可交易的股票...")
    test_date = rebalance_dates[0] if rebalance_dates else start_date
    print(f"  测试交易日: {test_date}")
    
    try:
        # 使用宇宙管理器获取可交易股票
        stocks = await universe_mgr.get_tradable_stocks(
            test_date, 
            liquidity_threshold=liquidity_threshold,
            exclude_rules=[ExcludeRule.ST, ExcludeRule.NEW_STOCK]
        )
        
        if stocks:
            print(f"  ✅ 成功找到 {len(stocks)} 只可交易股票")
            print("  股票示例 (前5只):")
            for i, stock in enumerate(stocks[:5], 1):
                print(f"    {i}. {stock}")
            
            # 检查数据源
            print("  数据源: stock_daily_ak_full 集合")
        else:
            print("  ❌ 没有找到可交易股票")
            print("  可能原因:")
            print("    1. 流动性门槛仍然太高")
            print("    2. 数据格式不匹配")
            print("    3. ST/新股排除规则太严格")
    
    except Exception as e:
        print(f"  ❌ 获取股票失败: {e}")
    
    print()
    
    # 测试2: 运行简化回测
    print("测试2: 运行简化回测...")
    
    # 使用最简单的策略
    strategy = {
        "name": "简化测试",
        "filters": [
            ("limit_up_yesterday", 1),
        ],
    }
    
    try:
        # 创建回测器
        backtester = PortfolioBacktester()  # 使用默认数据源
        
        # 配置回测参数
        config = {
            "start_date": start_date,
            "end_date": end_date,
            "initial_cash": initial_capital,
            "max_position_percent": max_position_percent / 100.0,
            "liquidity_threshold": liquidity_threshold,
            "universe_mgr": universe_mgr,
            "factor_engine": factor_engine,
            "exclude_rules": [ExcludeRule.ST, ExcludeRule.NEW_STOCK],
            "factors": [
                {"name": "limit_up_yesterday", "target": 1}
            ],
            "top_n": 1,
            "rebalance_freq": "daily",
        }
        
        print("  运行回测配置...")
        result = await backtester.run(config)
        
        if result is None or "error" in result:
            error_msg = result.get('error', '未知错误') if result else '没有结果'
            print(f"  ❌ 回测失败: {error_msg}")
        else:
            print("  ✅ 回测成功!")
            print(f"    信号数: {result.get('trade_days', 0)}")
            print(f"    胜率: {result.get('win_rate', 0):.2f}%")
            print(f"    总收益: {result.get('total_return', 0):.2f}%")
            
            if result.get('trade_days', 0) > 0:
                print("  🎉 成功产生交易信号!")
            else:
                print("  ⚠️  没有产生交易信号")
    
    except Exception as e:
        print(f"  ❌ 回测异常: {e}")
        import traceback
        traceback.print_exc()
    
    print()
    
    # 测试3: 检查数据源
    print("测试3: 检查数据源...")
    try:
        import pymongo
        client = pymongo.MongoClient('localhost', 27017)
        db = client['stock_agent']
        
        # 检查两个集合
        for coll_name in ['stock_daily_ak_full', 'stock_daily_ak_full_ak']:
            if coll_name in db.list_collection_names():
                coll = db[coll_name]
                count = coll.count_documents({})
                print(f"  {coll_name}: {count} 条记录")
                
                # 检查是否有数据
                if count > 0:
                    sample = coll.find_one({})
                    print(f"    示例股票: {sample.get('ts_code', 'N/A')}")
                    print(f"    示例日期: {sample.get('trade_date', 'N/A')}")
                    print(f"    成交额: {sample.get('amount', 0):,.2f} 万元")
            else:
                print(f"  {coll_name}: 集合不存在")
        
        client.close()
    
    except Exception as e:
        print(f"  ❌ 数据源检查失败: {e}")
    
    # 关闭连接
    print()
    print("关闭连接...")
    await baostock_manager.shutdown()
    await akshare_manager.shutdown()
    await mongo_manager.shutdown()
    await redis_manager.shutdown()
    
    print()
    print("="*60)
    print("✅ 简化测试完成")

async def main():
    await test_simple_backtest()

if __name__ == "__main__":
    asyncio.run(main())