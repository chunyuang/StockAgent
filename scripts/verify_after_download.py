#!/usr/bin/env python3
"""
下载完成后验证回测是否能产生信号
"""

import sys
import asyncio
import pymongo

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
from backtest_module.backtest_engine.factor_selection.universe import ExcludeRule

async def verify_backtest():
    """验证回测是否正常工作"""
    print("🧪 下载完成后回测验证")
    print("="*60)
    
    # 1. 先验证数据质量
    print("1. 验证数据质量...")
    
    client = pymongo.MongoClient('localhost', 27017)
    db = client['stock_agent']
    collection = db['stock_daily_ak_full']
    
    total_records = collection.count_documents({})
    unique_stocks = len(collection.distinct('ts_code'))
    unique_dates = len(collection.distinct('trade_date'))
    
    print(f"   总记录数: {total_records:,}")
    print(f"   股票数量: {unique_stocks} 只")
    print(f"   交易日数: {unique_dates} 天")
    
    # 检查涨停数量
    print("\n2. 检查涨停股票数量...")
    
    dates = sorted(collection.distinct('trade_date'))
    limit_up_counts = {}
    
    for date in dates[:10]:  # 前10个交易日
        count = 0
        cursor = collection.find({'trade_date': date})
        for record in cursor:
            close = record.get('close', 0)
            up_limit = record.get('up_limit', 0)
            if abs(close - up_limit) < 0.001 and up_limit > 0:
                count += 1
        limit_up_counts[date] = count
        print(f"   {date}: {count} 只涨停")
    
    total_limit_up = sum(limit_up_counts.values())
    print(f"   前10个交易日总计: {total_limit_up} 只涨停")
    
    if total_limit_up == 0:
        print("\n❌ 仍然没有涨停股票，建议:")
        print("   1. 下载更多股票")
        print("   2. 调整时间范围")
        print("   3. 放宽策略条件")
        client.close()
        return False
    
    # 2. 初始化管理器
    print("\n3. 初始化管理器...")
    await redis_manager.initialize()
    await mongo_manager.initialize()
    await baostock_manager.initialize()
    await akshare_manager.initialize()
    
    print("   管理器初始化完成 ✓")
    
    # 3. 运行简化回测
    print("\n4. 运行简化回测...")
    
    start_date = str(min(dates))
    end_date = str(max(dates))
    
    print(f"   回测区间: {start_date} ~ {end_date}")
    print("   初始资金: 1,000,000 元")
    print("   流动性门槛: 100 万元")
    
    try:
        # 创建回测器
        backtester = PortfolioBacktester()
        
        # 配置回测参数
        config = {
            "start_date": start_date,
            "end_date": end_date,
            "initial_cash": 1000000,
            "max_position_percent": 0.2,
            "liquidity_threshold": 100,
            "exclude_rules": [ExcludeRule.ST, ExcludeRule.NEW_STOCK],
            "factors": [
                {"name": "limit_up_yesterday", "target": 1},
                {"name": "open_below_limit", "target": 1},
            ],
            "top_n": 3,
            "rebalance_freq": "daily",
        }
        
        result = await backtester.run(config)
        
        if result is None or "error" in result:
            error_msg = result.get('error', '未知错误') if result else '没有结果'
            print(f"   ❌ 回测失败: {error_msg}")
        else:
            print("   ✅ 回测成功!")
            print(f"     总交易日: {result.get('trade_days', 0)} 天")
            print(f"     交易信号数: {result.get('total_trades', 0)} 次")
            print(f"     胜率: {result.get('win_rate', 0):.2f}%")
            print(f"     总收益率: {result.get('total_return', 0):.2f}%")
            print(f"     最大回撤: {result.get('max_drawdown', 0):.2f}%")
            
            if result.get('total_trades', 0) > 0:
                print("\n🎉 成功产生交易信号! 问题已解决!")
                success = True
            else:
                print("\n⚠️  仍无交易信号，可能需要:")
                print("   1. 进一步扩大股票池")
                print("   2. 调整因子参数")
                success = False
    
    except Exception as e:
        print(f"   ❌ 回测异常: {e}")
        import traceback
        traceback.print_exc()
        success = False
    
    # 关闭连接
    await baostock_manager.shutdown()
    await akshare_manager.shutdown()
    await mongo_manager.shutdown()
    await redis_manager.shutdown()
    
    client.close()
    
    print()
    print("="*60)
    
    if success:
        print("✅ 验证成功! 回测可以正常产生信号")
    else:
        print("⚠️  验证部分完成，仍需要进一步调整")
    
    return success

async def main():
    await verify_backtest()

if __name__ == "__main__":
    asyncio.run(main())