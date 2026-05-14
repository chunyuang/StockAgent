#!/usr/bin/env python3
"""
强制每日因子预计算 - 强制更新所有因子字段
"""

import sys
import os
import time
import argparse
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from pymongo import MongoClient, UpdateOne

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "stock_agent"

# 需要强制更新的因子（包括我们修复的因子）
FORCE_UPDATE_FACTORS = [
    # 基础因子
    "turnover_rate", "volume_ratio", "amount_20d",
    "ma5", "ma10", "ma20", "ma60",
    "rsi_6", "rsi_12",
    
    # 涨跌停相关
    "limit_up_yesterday", "limit_down_yesterday",
    "open_above_limit", "open_above_limit_down",
    "limit_up_count", "limit_down_count",
    
    # 我们修复的因子
    "volume_increase", "market_leader", "hot_sector", "sentiment_score",
    
    # 其他重要因子
    "first_limit_up", "circ_mv", "opening_pct_chg",
    "open_below_limit", "rise_after_limit_down",
    "amplitude", "momentum_5d", "volatility_20d",
    "fear_greed_index"
]

def force_precompute_factors(date_str: str):
    """强制预计算因子（即使字段已存在也更新）"""
    print(f"🔧 强制预计算因子: {date_str}")
    
    client = None
    try:
        # 1. 连接到MongoDB
        client = MongoClient(MONGO_URI)
        db = client[DB_NAME]
        
        trade_date = int(date_str)
        
        # 2. 获取该日期的所有股票数据
        print("  读取数据...")
        cursor = db.stock_daily_ak_full.find(
            {"trade_date": trade_date},
            {
                "ts_code": 1, "trade_date": 1,
                "open": 1, "high": 1, "low": 1, "close": 1,
                "vol": 1, "amount": 1, "pct_chg": 1,
                "circ_mv": 1, "turnover_rate": 1, "volume_ratio": 1
            }
        )
        
        data = list(cursor)
        if not data:
            print(f"  ℹ️  {date_str} 无数据")
            return 0
        
        print(f"  读取 {len(data)} 条记录, {len(set(d['ts_code'] for d in data))} 只股票")
        
        # 3. 转换为DataFrame
        df = pd.DataFrame(data)
        
        # 4. 导入因子计算函数
        from nodes.backtest_engine.factor_selection.factor_auto_compute import _compute_factors_for_stock
        
        # 5. 按股票分组计算因子
        print("  计算因子...")
        results = []
        
        # 按股票分组
        grouped = df.groupby('ts_code')
        
        for ts_code, group in grouped:
            try:
                # 获取该股票最近20天数据用于滚动计算
                hist_cursor = db.stock_daily_ak_full.find(
                    {"ts_code": ts_code, "trade_date": {"$lte": trade_date}},
                    {
                        "ts_code": 1, "trade_date": 1,
                        "open": 1, "high": 1, "low": 1, "close": 1,
                        "vol": 1, "amount": 1, "pct_chg": 1
                    }
                ).sort("trade_date", -1).limit(30)
                
                hist_data = list(hist_cursor)
                if len(hist_data) < 5:  # 至少需要5天数据
                    continue
                
                # 转换为DataFrame（按时间排序）
                hist_df = pd.DataFrame(hist_data)
                hist_df = hist_df.sort_values('trade_date')
                
                # 计算因子
                factor_result = _compute_factors_for_stock(hist_df, FORCE_UPDATE_FACTORS)
                
                # 取目标日期的因子值
                target_row = factor_result[factor_result['trade_date'] == trade_date]
                if not target_row.empty:
                    row = target_row.iloc[0]
                    
                    # 构建更新数据（强制更新所有因子字段）
                    update_data = {}
                    for factor in FORCE_UPDATE_FACTORS:
                        if factor in row and pd.notna(row[factor]):
                            val = row[factor]
                            
                            # 类型转换
                            if isinstance(val, (bool, np.bool_)):
                                val = float(val)
                            elif isinstance(val, (np.integer,)):
                                val = int(val)
                            elif isinstance(val, (np.floating,)):
                                val = float(val)
                            elif pd.isna(val):
                                continue
                            
                            update_data[factor] = val
                    
                    if update_data:
                        results.append(
                            UpdateOne(
                                {"ts_code": ts_code, "trade_date": trade_date},
                                {"$set": update_data},
                                upsert=False
                            )
                        )
                        
            except Exception as e:
                print(f"  ⚠️  计算 {ts_code} 失败: {e}")
                continue
        
        # 6. 批量写入
        if results:
            print(f"  准备写入 {len(results)} 条更新...")
            t1 = time.time()
            result = db.stock_daily_ak_full.bulk_write(results, ordered=False)
            t2 = time.time()
            
            print(f"  ✅ 成功更新 {result.modified_count} 条记录, 耗时{t2-t1:.1f}s")
            return result.modified_count
        else:
            print("  ℹ️  无更新需要执行")
            return 0
            
    except Exception as e:
        print(f"  ❌ 失败: {e}")
        import traceback
        traceback.print_exc()
        return 0
    finally:
        if client:
            client.close()

def main():
    parser = argparse.ArgumentParser(description="强制每日因子预计算")
    parser.add_argument("--date", type=str, required=True, help="日期，格式: YYYYMMDD")
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("🔧 强制每日因子预计算工具")
    print("=" * 60)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"日期: {args.date}")
    print(f"强制更新 {len(FORCE_UPDATE_FACTORS)} 个因子")
    print("=" * 60)
    
    start_time = time.time()
    updated = force_precompute_factors(args.date)
    total_time = time.time() - start_time
    
    print(f"\n总耗时: {total_time:.1f}s")
    
    if updated > 0:
        print(f"✅ 强制更新完成！更新了 {updated} 条记录")
    else:
        print(f"ℹ️  无记录被更新")
    
    return 0 if updated >= 0 else 1

if __name__ == "__main__":
    sys.exit(main())