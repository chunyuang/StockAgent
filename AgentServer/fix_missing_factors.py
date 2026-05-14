#!/usr/bin/env python3
"""
修复缺失因子：批量计算并更新MongoDB中的因子数据
"""

import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.managers.mongo_manager import mongo_manager
from nodes.backtest_engine.factor_selection.factor_auto_compute import auto_compute_factors
import pandas as pd
from datetime import datetime

async def fix_missing_factors():
    """修复缺失因子数据"""
    print("🔧 开始修复缺失因子数据...")
    
    # 1. 初始化MongoDB连接
    await mongo_manager.initialize()
    print("✅ MongoDB连接已初始化")
    
    # 2. 回测区间：20260105 - 20260320
    start_date = 20260105
    end_date = 20260320
    
    # 3. 获取需要修复的日期
    dates_result = await mongo_manager.find(
        "stock_daily_ak_full",
        {
            "trade_date": {"$gte": start_date, "$lte": end_date},
            "ts_code": "000001.SZ"  # 用一只股票来获取日期列表
        },
        {"trade_date": 1}
    )
    dates_query = sorted(list(set([doc["trade_date"] for doc in dates_result])))
    
    print(f"📅 需要修复 {len(dates_query)} 个交易日的因子数据")
    
    # 4. 修复每个交易日
    fixed_count = 0
    for i, trade_date in enumerate(dates_query):
        print(f"\n处理第 {i+1}/{len(dates_query)} 天: {trade_date}")
        
        try:
            # 检查是否已经有因子数据
            missing_factors = await check_missing_factors(trade_date)
            
            if missing_factors:
                print(f"  ⚠️  缺失因子: {', '.join(missing_factors)}")
                
                # 运行因子计算
                print(f"  🔧 运行因子计算...")
                result = await auto_compute_factors(trade_date_str=str(trade_date))
                
                if result.get("success"):
                    updated = result.get("updated", 0)
                    print(f"  ✅ 更新了 {updated} 条记录")
                    fixed_count += 1
                else:
                    print(f"  ❌ 因子计算失败: {result.get('error', '未知错误')}")
            else:
                print(f"  ✅ 因子数据完整")
                
        except Exception as e:
            print(f"  ❌ 处理失败: {e}")
            continue
        
        # 每处理10天输出一次进度
        if (i + 1) % 10 == 0:
            print(f"\n📊 进度: {i+1}/{len(dates_query)} 天 ({((i+1)/len(dates_query))*100:.1f}%)")
    
    print(f"\n🎉 修复完成！")
    print(f"  总计处理: {len(dates_query)} 天")
    print(f"  成功修复: {fixed_count} 天")
    print(f"  缺失因子: volume_increase, market_leader, sentiment_score 等")
    
    return fixed_count

async def check_missing_factors(trade_date: int):
    """检查指定日期缺失的因子"""
    # 需要检查的因子列表
    required_factors = [
        "volume_increase", "market_leader", "hot_sector", "sentiment_score"
    ]
    
    missing = []
    
    for factor in required_factors:
        # 检查该因子是否有数据
        try:
            count = await mongo_manager.count_documents(
                "stock_daily_ak_full",
                {
                    "trade_date": trade_date,
                    factor: {"$ne": None, "$exists": True}
                }
            )
            
            if count == 0:
                missing.append(factor)
        except:
            # 如果字段不存在，会报错，直接视为缺失
            missing.append(factor)
    
    return missing

async def main():
    """主函数"""
    print("=" * 60)
    print("🔧 缺失因子修复工具")
    print("=" * 60)
    print("修复因子: volume_increase, market_leader, sentiment_score, hot_sector")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    try:
        fixed = await fix_missing_factors()
        
        if fixed > 0:
            print(f"\n✅ 修复成功！请重新运行回测验证。")
        else:
            print(f"\nℹ️  所有因子数据已完整，无需修复。")
            
    except Exception as e:
        print(f"\n❌ 修复失败: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)