#!/usr/bin/env python3
"""
强制更新因子数据：确保所有因子字段都被创建和更新
"""

import asyncio
import sys
import os
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pymongo import MongoClient, UpdateOne
from datetime import datetime

def force_update_factors_for_date(date_str: str):
    """强制更新指定日期的所有因子数据"""
    print(f"\n🔧 强制更新因子: {date_str}")
    
    client = None
    try:
        # 1. 连接到MongoDB
        client = MongoClient('localhost', 27017)
        db = client['stock_agent']
        collection = db['stock_daily_ak_full']
        
        # 2. 获取该日期的所有股票
        date_int = int(date_str)
        cursor = collection.find(
            {'trade_date': date_int},
            {'ts_code': 1, 'open': 1, 'high': 1, 'low': 1, 'close': 1, 
             'vol': 1, 'amount': 1, 'pct_chg': 1}
        ).limit(100)  # 先测试100只股票
        
        stocks = list(cursor)
        print(f"  读取 {len(stocks)} 只股票数据")
        
        if not stocks:
            print("  ℹ️  无数据")
            return 0
        
        # 3. 导入因子计算函数
        from nodes.backtest_engine.factor_selection.factor_auto_compute import _compute_factors_for_stock
        import pandas as pd
        
        # 4. 为每只股票计算因子
        updates = []
        updated_count = 0
        
        for stock in stocks:
            try:
                # 创建DataFrame（需要多日数据用于滚动计算）
                # 先获取该股票最近10天的数据
                ts_code = stock['ts_code']
                hist_cursor = collection.find(
                    {'ts_code': ts_code, 'trade_date': {'$lte': date_int}},
                    {'ts_code': 1, 'trade_date': 1, 'open': 1, 'high': 1, 'low': 1, 
                     'close': 1, 'vol': 1, 'amount': 1, 'pct_chg': 1}
                ).sort('trade_date', -1).limit(20)  # 取最近20天
                
                hist_data = list(hist_cursor)
                if len(hist_data) < 5:  # 至少需要5天数据
                    continue
                
                # 转换为DataFrame
                df = pd.DataFrame(hist_data)
                df = df.sort_values('trade_date')
                
                # 计算因子
                factor_fields = ['volume_increase', 'market_leader', 'hot_sector', 'sentiment_score']
                result = _compute_factors_for_stock(df, factor_fields)
                
                # 取最新一天（目标日期）的因子值
                latest = result[result['trade_date'] == date_int]
                if not latest.empty:
                    factors = latest.iloc[0]
                    
                    # 创建更新操作
                    update_data = {}
                    for field in factor_fields:
                        if field in factors and pd.notna(factors[field]):
                            update_data[field] = factors[field]
                    
                    if update_data:
                        updates.append(
                            UpdateOne(
                                {'ts_code': ts_code, 'trade_date': date_int},
                                {'$set': update_data}
                            )
                        )
                        updated_count += 1
                        
            except Exception as e:
                print(f"  ❌ 计算 {stock.get('ts_code', '未知')} 失败: {e}")
                continue
        
        # 5. 批量更新
        if updates:
            print(f"  准备更新 {len(updates)} 条记录...")
            result = collection.bulk_write(updates, ordered=False)
            print(f"  ✅ 成功更新 {result.modified_count} 条记录")
            return result.modified_count
        else:
            print("  ℹ️  无更新需要执行")
            return 0
            
    except Exception as e:
        print(f"  ❌ 更新失败: {e}")
        import traceback
        traceback.print_exc()
        return 0
    finally:
        if client:
            client.close()

def main():
    """主函数"""
    print("=" * 60)
    print("🔧 强制更新因子数据工具")
    print("=" * 60)
    print("确保创建和更新以下因子字段:")
    print("  - volume_increase (放量标记)")
    print("  - market_leader (龙头股标记)")  
    print("  - hot_sector (热点板块)")
    print("  - sentiment_score (情绪评分 0-100)")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # 关键日期：回测开始的第一天
    key_dates = ['20260105', '20260106', '20260107']
    
    total_updated = 0
    for date_str in key_dates:
        updated = force_update_factors_for_date(date_str)
        total_updated += updated
    
    print("\n" + "=" * 60)
    print("🎉 强制更新完成！")
    print(f"  总计更新: {total_updated} 条记录")
    print(f"  更新日期: {', '.join(key_dates)}")
    print("\n✅ 现在可以重新运行回测验证。")
    print("=" * 60)
    
    return 0 if total_updated > 0 else 1

if __name__ == "__main__":
    sys.exit(main())