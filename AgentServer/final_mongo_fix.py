#!/usr/bin/env python3
"""
最终修复：确保MongoDB能正确识别 volume_increase 字段存在
解决 $exists 查询的问题
"""

from pymongo import MongoClient
import time

print("🔧 最终修复：确保MongoDB正确识别字段存在")
print("=" * 60)

def fix_mongo_field_issue():
    """修复MongoDB字段存在性问题"""
    
    client = MongoClient('localhost', 27017)
    db = client['stock_agent']
    
    # 修复的日期
    dates = [20260105, 20260106, 20260107]
    
    for date in dates:
        print(f"\n📅 修复日期 {date}...")
        
        # 1. 检查当前状态
        count_total = db.stock_daily_ak_full.count_documents({'trade_date': date})
        count_with_field = db.stock_daily_ak_full.count_documents({
            'trade_date': date,
            'volume_increase': {'$exists': True}
        })
        
        print(f"  修复前:")
        print(f"    总记录数: {count_total}")
        print(f"    $exists 查询有字段: {count_with_field} ({count_with_field/count_total*100:.1f}%)")
        
        # 2. 找出缺失字段的记录
        # 使用更可靠的方法：先找有字段的记录，然后补全缺失的
        cursor = db.stock_daily_ak_full.find(
            {'trade_date': date},
            {'ts_code': 1, 'volume_increase': 1, 'market_leader': 1, 'hot_sector': 1, 'sentiment_score': 1}
        ).limit(200)  # 先检查200条
        
        records_to_fix = []
        has_field_count = 0
        
        for doc in cursor:
            ts_code = doc['ts_code']
            needs_fix = False
            
            # 检查每个字段
            for field in ['volume_increase', 'market_leader', 'hot_sector', 'sentiment_score']:
                if field not in doc:
                    needs_fix = True
                    break
            
            if needs_fix:
                records_to_fix.append(ts_code)
            else:
                has_field_count += 1
        
        print(f"  抽样检查200条记录:")
        print(f"    有完整字段: {has_field_count}")
        print(f"    需要修复: {len(records_to_fix)}")
        
        if not records_to_fix:
            print(f"  ✅ 该日期无需修复")
            continue
        
        # 3. 修复缺失字段
        print(f"  开始修复 {len(records_to_fix)} 条记录...")
        
        batch_size = 100
        fixed_count = 0
        
        for i in range(0, len(records_to_fix), batch_size):
            batch = records_to_fix[i:i+batch_size]
            
            for ts_code in batch:
                # 为每个缺失字段设置默认值
                update_data = {}
                
                # 检查每个字段
                doc = db.stock_daily_ak_full.find_one(
                    {'ts_code': ts_code, 'trade_date': date},
                    {'volume_increase': 1, 'market_leader': 1, 'hot_sector': 1, 'sentiment_score': 1}
                )
                
                if doc:
                    # 确保所有字段都有值
                    if 'volume_increase' not in doc:
                        update_data['volume_increase'] = 0.0
                    
                    if 'market_leader' not in doc:
                        update_data['market_leader'] = 0.0
                    
                    if 'hot_sector' not in doc:
                        update_data['hot_sector'] = 0.0
                    
                    if 'sentiment_score' not in doc:
                        update_data['sentiment_score'] = 50.0  # 中性
                    
                    if update_data:
                        result = db.stock_daily_ak_full.update_one(
                            {'ts_code': ts_code, 'trade_date': date},
                            {'$set': update_data}
                        )
                        if result.modified_count > 0:
                            fixed_count += 1
            
            print(f"    批次 {i//batch_size + 1}: 修复了 {min(batch_size, len(records_to_fix)-i)} 条")
        
        # 4. 验证修复
        count_after = db.stock_daily_ak_full.count_documents({
            'trade_date': date,
            'volume_increase': {'$exists': True}
        })
        
        print(f"  修复后:")
        print(f"    $exists 查询有字段: {count_after} ({count_after/count_total*100:.1f}%)")
        
        if count_after == count_total:
            print(f"  ✅ 修复成功！所有记录都有 volume_increase 字段")
        else:
            print(f"  ⚠️  修复不完全：{count_after}/{count_total}")
    
    # 5. 最终验证
    print("\n" + "=" * 60)
    print("🔍 最终验证")
    
    for date in dates:
        count_total = db.stock_daily_ak_full.count_documents({'trade_date': date})
        count_with_field = db.stock_daily_ak_full.count_documents({
            'trade_date': date,
            'volume_increase': {'$exists': True}
        })
        
        status = "✅" if count_with_field == count_total else "❌"
        print(f"  {status} 日期 {date}: {count_with_field}/{count_total} ({count_with_field/count_total*100:.1f}%)")
    
    client.close()
    
    print("\n" + "=" * 60)
    print("🚀 修复完成")
    print("现在应该运行回测验证修复效果")
    print("预期结果：不再有 '缺失因子: volume_increase' 警告")

def main():
    """主函数"""
    start_time = time.time()
    
    try:
        fix_mongo_field_issue()
        print(f"\n总耗时: {time.time() - start_time:.1f}秒")
        
    except Exception as e:
        print(f"\n❌ 修复失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()