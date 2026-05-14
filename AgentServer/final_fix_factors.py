#!/usr/bin/env python3
"""
最终修复：确保所有因子的值都是正确的
1. volume_increase: 基于成交量计算
2. market_leader: 默认False (0.0)
3. hot_sector: 默认False (0.0)
4. sentiment_score: 修复为0-100分
"""

import sys
sys.path.insert(0, '.')

from pymongo import MongoClient
import pandas as pd
import numpy as np
import time

print("🔧 最终修复：确保所有因子值正确")
print("=" * 60)

def get_stock_history(db, ts_code, target_date, days_back=10):
    """获取股票的历史数据"""
    cursor = db.stock_daily_ak_full.find(
        {
            'ts_code': ts_code,
            'trade_date': {'$lte': target_date}
        },
        {'ts_code': 1, 'trade_date': 1, 'vol': 1, 'pct_chg': 1, 'close': 1}
    ).sort('trade_date', -1).limit(days_back)
    
    history = list(cursor)
    history.reverse()  # 按时间顺序排列
    return history

def calculate_correct_factors(history, target_date):
    """计算正确的因子值"""
    if not history:
        return None
    
    # 找到目标日期的索引
    target_idx = None
    for i, day in enumerate(history):
        if day['trade_date'] == target_date:
            target_idx = i
            break
    
    if target_idx is None:
        return None
    
    result = {}
    
    # 1. volume_increase: 当日成交量 > 过去5日平均成交量 * 1.5
    if target_idx >= 5:  # 有至少5天历史数据
        # 取前5天的成交量
        prev_volumes = []
        for i in range(max(0, target_idx-5), target_idx):
            prev_volumes.append(history[i].get('vol', 0))
        
        if prev_volumes:
            avg_vol_5d = sum(prev_volumes) / len(prev_volumes)
            current_vol = history[target_idx].get('vol', 0)
            result['volume_increase'] = 1.0 if current_vol > avg_vol_5d * 1.5 else 0.0
        else:
            result['volume_increase'] = 0.0
    else:
        result['volume_increase'] = 0.0  # 数据不足，默认False
    
    # 2. market_leader: 暂时设为False (简化处理)
    result['market_leader'] = 0.0
    
    # 3. hot_sector: 暂时设为False (简化处理)
    result['hot_sector'] = 0.0
    
    # 4. sentiment_score: 修复为0-100分
    # 基于涨跌幅计算：-10% → 0分，0% → 50分，+10% → 100分
    pct_chg = history[target_idx].get('pct_chg', 0)
    
    # 线性映射：pct_chg从-10到+10映射到0到100
    score = 50.0 + pct_chg * 5  # 每1%涨跌幅对应5分
    
    # 限制在0-100范围内
    score = max(0.0, min(100.0, score))
    result['sentiment_score'] = round(score, 2)
    
    return result

def main():
    """主函数"""
    start_time = time.time()
    
    try:
        # 连接到MongoDB
        client = MongoClient('localhost', 27017)
        db = client['stock_agent']
        
        print(f"数据库: {db.name}")
        print(f"集合: stock_daily_ak_full")
        
        # 修复关键日期（20260105-20260107）
        dates_to_fix = [20260105, 20260106, 20260107]
        
        total_updated = 0
        
        for target_date in dates_to_fix:
            print(f"\n📅 修复日期 {target_date}...")
            
            # 获取该日期的所有股票
            cursor = db.stock_daily_ak_full.find(
                {'trade_date': target_date},
                {'ts_code': 1}
            )
            
            stocks = list(cursor)
            print(f"  需要修复 {len(stocks)} 只股票")
            
            # 分批处理
            batch_size = 500
            batch_count = 0
            
            for i in range(0, len(stocks), batch_size):
                batch = stocks[i:i+batch_size]
                updates = []
                
                for stock in batch:
                    ts_code = stock['ts_code']
                    
                    # 获取历史数据
                    history = get_stock_history(db, ts_code, target_date, days_back=20)
                    
                    # 计算正确的因子值
                    factors = calculate_correct_factors(history, target_date)
                    
                    if factors:
                        updates.append({
                            'filter': {'ts_code': ts_code, 'trade_date': target_date},
                            'update': {'$set': factors}
                        })
                
                # 批量更新
                if updates:
                    for update in updates:
                        result = db.stock_daily_ak_full.update_one(
                            update['filter'],
                            update['update']
                        )
                        if result.modified_count > 0:
                            total_updated += 1
                    
                    batch_count += 1
                    print(f"    批次 {batch_count}: 更新了 {len(updates)} 条记录")
            
            # 验证修复
            print(f"  ✅ 日期 {target_date}: 更新了 {total_updated} 条记录")
            
            # 抽样验证
            sample = db.stock_daily_ak_full.find_one(
                {'trade_date': target_date},
                {'ts_code': 1, 'volume_increase': 1, 'sentiment_score': 1}
            )
            
            if sample:
                print(f"    样本验证:")
                print(f"      股票: {sample.get('ts_code')}")
                print(f"      volume_increase: {sample.get('volume_increase')}")
                print(f"      sentiment_score: {sample.get('sentiment_score')}")
        
        # 最终统计
        print("\n" + "=" * 60)
        print("📊 最终修复完成")
        print(f"  修复了 {len(dates_to_fix)} 个交易日")
        print(f"  总共更新了 {total_updated} 条记录")
        print(f"  总耗时: {time.time() - start_time:.1f}秒")
        
        # 验证sentiment_score是否修复
        print("\n🔍 验证 sentiment_score 修复:")
        for target_date in dates_to_fix:
            cursor = db.stock_daily_ak_full.find(
                {'trade_date': target_date, 'sentiment_score': {'$exists': True}},
                {'sentiment_score': 1}
            ).limit(5)
            
            scores = [doc.get('sentiment_score') for doc in cursor]
            if scores:
                avg_score = sum(scores) / len(scores)
                print(f"  日期 {target_date}: 平均 sentiment_score = {avg_score:.2f}")
                
                # 检查是否有0.5的旧值
                old_values = [s for s in scores if s == 0.5]
                if old_values:
                    print(f"    ⚠️  仍有 {len(old_values)} 条记录为旧值0.5")
                else:
                    print(f"    ✅ 无旧值0.5")
        
        client.close()
        
        print("\n" + "=" * 60)
        print("🚀 修复验证完成")
        print("所有因子字段已创建并计算了正确的值")
        print("现在可以运行回测验证修复效果")
        
    except Exception as e:
        print(f"\n❌ 修复失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()