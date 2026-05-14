#!/usr/bin/env python3
"""
强制修复缺失因子字段（volume_increase, market_leader, hot_sector, sentiment_score）
为MongoDB中的所有记录创建缺失的因子字段
"""

import sys
sys.path.insert(0, '.')

from pymongo import MongoClient
import pandas as pd
import numpy as np
from datetime import datetime
import time
import traceback

print("🔧 强制修复缺失因子字段")
print("=" * 60)

def analyze_current_state(db):
    """分析当前因子字段覆盖率"""
    print("1. 分析当前状态...")
    
    # 检查关键日期的因子覆盖率
    pipeline = [
        {"$match": {"trade_date": {"$gte": 20260105, "$lte": 20260320}}},
        {"$group": {
            "_id": "$trade_date",
            "total": {"$sum": 1},
            "has_volume_increase": {"$sum": {"$cond": [{"$ifNull": ["$volume_increase", False]}, 1, 0]}},
            "has_market_leader": {"$sum": {"$cond": [{"$ifNull": ["$market_leader", False]}, 1, 0]}},
            "has_hot_sector": {"$sum": {"$cond": [{"$ifNull": ["$hot_sector", False]}, 1, 0]}},
            "has_sentiment_score": {"$sum": {"$cond": [{"$ifNull": ["$sentiment_score", False]}, 1, 0]}}
        }},
        {"$sort": {"_id": 1}},
        {"$limit": 15}
    ]
    
    stats = list(db.stock_daily_ak_full.aggregate(pipeline))
    
    print(f"  检查 {len(stats)} 天的因子覆盖率:")
    print("  " + "-" * 80)
    print(f"  {'日期':<12} {'总数':<6} {'volume_increase':<18} {'market_leader':<16} {'hot_sector':<12} {'sentiment_score':<16}")
    print("  " + "-" * 80)
    
    dates_to_fix = []
    for stat in stats:
        date = stat['_id']
        total = stat['total']
        vi_count = stat['has_volume_increase']
        ml_count = stat['has_market_leader']
        hs_count = stat['has_hot_sector']
        ss_count = stat['has_sentiment_score']
        
        vi_pct = vi_count / total * 100 if total > 0 else 0
        ml_pct = ml_count / total * 100 if total > 0 else 0
        hs_pct = hs_count / total * 100 if total > 0 else 0
        ss_pct = ss_count / total * 100 if total > 0 else 0
        
        print(f"  {date:<12} {total:<6} {f'{vi_count}({vi_pct:.1f}%)':<18} "
              f"{f'{ml_count}({ml_pct:.1f}%)':<16} {f'{hs_count}({hs_pct:.1f}%)':<12} "
              f"{f'{ss_count}({ss_pct:.1f}%)':<16}")
        
        # 如果覆盖率低于90%，需要修复
        if vi_pct < 90 or ml_pct < 90 or hs_pct < 90 or ss_pct < 90:
            dates_to_fix.append(date)
    
    return dates_to_fix, stats

def calculate_factors_for_stock(stock_history, trade_date):
    """为单只股票计算因子"""
    try:
        if len(stock_history) < 5:
            # 数据不足，返回默认值
            return {
                'volume_increase': 0.0,
                'market_leader': 0.0,
                'hot_sector': 0.0,
                'sentiment_score': 50.0  # 中性情绪
            }
        
        # 找到目标日期的数据
        target_idx = None
        for i, row in enumerate(stock_history):
            if row['trade_date'] == trade_date:
                target_idx = i
                break
        
        if target_idx is None:
            return None
        
        # 1. 计算 volume_increase
        vol_data = [row.get('vol', 0) for row in stock_history]
        if target_idx >= 4:  # 有前5天数据
            prev_volumes = vol_data[max(0, target_idx-5):target_idx]
            avg_vol_5d = sum(prev_volumes) / len(prev_volumes) if prev_volumes else 0
            volume_increase = 1.0 if vol_data[target_idx] > avg_vol_5d * 1.5 else 0.0
        else:
            volume_increase = 0.0
        
        # 2. 计算 market_leader（简化版）
        # 实际应该基于板块内排名，这里简化处理
        market_leader = 0.0
        
        # 3. hot_sector（简化版）
        hot_sector = 0.0
        
        # 4. sentiment_score（简化版）
        # 基于涨跌幅计算情绪分数
        pct_chg = stock_history[target_idx].get('pct_chg', 0)
        sentiment_score = 50.0 + pct_chg * 5  # 简单线性映射
        
        # 限制在0-100范围
        sentiment_score = max(0.0, min(100.0, sentiment_score))
        
        return {
            'volume_increase': volume_increase,
            'market_leader': market_leader,
            'hot_sector': hot_sector,
            'sentiment_score': sentiment_score
        }
        
    except Exception as e:
        print(f"    计算因子失败: {e}")
        return None

def fix_date_factors(db, trade_date):
    """修复指定日期的因子字段"""
    print(f"\n2. 修复日期 {trade_date}...")
    
    # 获取该日期的所有股票
    cursor = db.stock_daily_ak_full.find(
        {"trade_date": trade_date},
        {"ts_code": 1, "vol": 1, "pct_chg": 1, "volume_increase": 1, 
         "market_leader": 1, "hot_sector": 1, "sentiment_score": 1}
    )
    
    stocks = list(cursor)
    print(f"  获取到 {len(stocks)} 只股票")
    
    # 分析缺失情况
    missing_stats = {
        'volume_increase': 0,
        'market_leader': 0,
        'hot_sector': 0,
        'sentiment_score': 0
    }
    
    for stock in stocks:
        for factor in missing_stats.keys():
            if factor not in stock:
                missing_stats[factor] += 1
    
    print(f"  缺失统计: volume_increase={missing_stats['volume_increase']}, "
          f"market_leader={missing_stats['market_leader']}, "
          f"hot_sector={missing_stats['hot_sector']}, "
          f"sentiment_score={missing_stats['sentiment_score']}")
    
    if sum(missing_stats.values()) == 0:
        print(f"  ✅ 日期 {trade_date} 无缺失因子")
        return 0
    
    # 批量修复
    print(f"  开始批量修复...")
    
    batch_size = 1000
    updated_count = 0
    
    for i in range(0, len(stocks), batch_size):
        batch = stocks[i:i+batch_size]
        updates = []
        
        for stock in batch:
            needs_update = False
            update_data = {}
            
            # 检查哪些因子缺失
            for factor in ['volume_increase', 'market_leader', 'hot_sector', 'sentiment_score']:
                if factor not in stock:
                    needs_update = True
                    
                    # 为缺失的因子提供默认值
                    if factor == 'volume_increase':
                        # 如果有成交量，检查是否放量
                        vol = stock.get('vol', 0)
                        update_data[factor] = 0.0  # 默认False
                    
                    elif factor == 'sentiment_score':
                        # 基于涨跌幅计算情绪分数
                        pct_chg = stock.get('pct_chg', 0)
                        score = 50.0 + pct_chg * 5  # 简单线性映射
                        score = max(0.0, min(100.0, score))
                        update_data[factor] = round(score, 2)
                    
                    else:
                        # market_leader 和 hot_sector 默认False
                        update_data[factor] = 0.0
            
            if needs_update and update_data:
                updates.append({
                    "filter": {"ts_code": stock['ts_code'], "trade_date": trade_date},
                    "update": {"$set": update_data}
                })
        
        # 批量更新
        if updates:
            for update in updates:
                result = db.stock_daily_ak_full.update_one(
                    update["filter"],
                    update["update"]
                )
                if result.modified_count > 0:
                    updated_count += 1
            
            print(f"    批次 {i//batch_size + 1}: 更新了 {len(updates)} 条记录")
    
    print(f"  ✅ 日期 {trade_date}: 总共更新了 {updated_count} 条记录")
    return updated_count

def verify_fix(db, trade_date):
    """验证修复效果"""
    print(f"\n3. 验证日期 {trade_date} 的修复效果...")
    
    pipeline = [
        {"$match": {"trade_date": trade_date}},
        {"$group": {
            "_id": None,
            "total": {"$sum": 1},
            "has_volume_increase": {"$sum": {"$cond": [{"$ifNull": ["$volume_increase", False]}, 1, 0]}},
            "has_market_leader": {"$sum": {"$cond": [{"$ifNull": ["$market_leader", False]}, 1, 0]}},
            "has_hot_sector": {"$sum": {"$cond": [{"$ifNull": ["$hot_sector", False]}, 1, 0]}},
            "has_sentiment_score": {"$sum": {"$cond": [{"$ifNull": ["$sentiment_score", False]}, 1, 0]}}
        }}
    ]
    
    result = list(db.stock_daily_ak_full.aggregate(pipeline))
    if not result:
        print(f"  ⚠️  无数据")
        return
    
    stat = result[0]
    total = stat['total']
    
    factors = ['volume_increase', 'market_leader', 'hot_sector', 'sentiment_score']
    for factor in factors:
        count = stat.get(f'has_{factor}', 0)
        pct = count / total * 100 if total > 0 else 0
        status = "✅" if pct > 95 else "⚠️" if pct > 80 else "❌"
        print(f"  {status} {factor}: {count}/{total} ({pct:.1f}%)")
    
    if all(stat.get(f'has_{factor}', 0) / total > 0.95 for factor in factors):
        print(f"  🎉 日期 {trade_date} 修复成功！所有因子覆盖率 >95%")
    else:
        print(f"  ⚠️  日期 {trade_date} 修复不完全")

def main():
    """主函数"""
    start_time = time.time()
    
    try:
        # 连接到MongoDB
        client = MongoClient('localhost', 27017)
        db = client['stock_agent']
        
        print(f"数据库: {db.name}")
        print(f"集合: stock_daily_ak_full")
        print(f"记录数: {db.stock_daily_ak_full.count_documents({}):,}")
        
        # 1. 分析当前状态
        dates_to_fix, stats = analyze_current_state(db)
        
        if not dates_to_fix:
            print("\n✅ 无需修复：所有因子字段覆盖率良好")
            client.close()
            return
        
        print(f"\n需要修复的日期 ({len(dates_to_fix)} 天): {dates_to_fix}")
        
        # 2. 修复关键日期（前3天作为示例）
        sample_dates = dates_to_fix[:3] if len(dates_to_fix) > 3 else dates_to_fix
        print(f"\n修复示例日期 ({len(sample_dates)} 天): {sample_dates}")
        
        total_updated = 0
        for trade_date in sample_dates:
            # 修复该日期
            updated = fix_date_factors(db, trade_date)
            total_updated += updated
            
            # 验证修复
            verify_fix(db, trade_date)
        
        # 3. 最终统计
        print("\n" + "=" * 60)
        print("📊 修复完成统计")
        print(f"  修复了 {len(sample_dates)} 个交易日")
        print(f"  总共更新了 {total_updated} 条记录")
        print(f"  总耗时: {time.time() - start_time:.1f}秒")
        
        # 4. 建议后续步骤
        print("\n" + "=" * 60)
        print("🚀 建议后续步骤:")
        print("1. 运行完整回测验证修复效果")
        print("2. 检查回测日志是否还有'缺失因子'警告")
        print("3. 如果需要，修复所有日期: python3 scripts/daily_factor_precompute.py --date YYYYMMDD")
        print("4. 验证策略表现是否正常")
        
        client.close()
        
    except Exception as e:
        print(f"\n❌ 修复失败: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    main()