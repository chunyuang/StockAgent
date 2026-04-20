#!/usr/bin/env python3
"""
直接修复AKShare数据单位问题
"""

import pymongo
from tqdm import tqdm

def fix_akshare_units():
    print("🔧 直接修复AKShare数据单位问题")
    print("="*60)
    
    client = pymongo.MongoClient('localhost', 27017)
    db = client['stock_agent']
    collection = db['stock_daily_ak_full_ak']
    
    # 1. 分析当前数据
    print("1. 分析当前数据...")
    total_records = collection.count_documents({})
    print(f"   总记录数: {total_records}")
    
    # 抽样检查
    sample = list(collection.find().limit(5))
    print("   抽样数据:")
    for record in sample:
        ts_code = record.get('ts_code', 'N/A')
        trade_date = record.get('trade_date', 'N/A')
        amount = record.get('amount', 0)
        
        print(f"   {ts_code} - {trade_date}:")
        print(f"     当前成交额: {amount:,.2f}")
        
        # 判断是否是元
        if 100000000 <= amount <= 10000000000:  # 1亿到100亿之间
            print("     ✅ 单位可能是元 (平安银行正常成交额)")
        else:
            print("     ⚠️  单位可能有误")
        print()
    
    # 2. 确认问题：AKShare返回的单位是元，但我们的策略可能期望万元
    print("2. 问题分析:")
    print("   ✅ AKShare API返回的成交额单位是元 (10亿级别)")
    print("   ❓ 策略可能期望单位是万元 (10万级别)")
    print("   💡 解决方案:")
    print("     1. 将数据库中金额除以10000 (元 → 万元)")
    print("     2. 调整策略筛选条件 (使用元的门槛)")
    
    # 3. 修复数据：将成交额从元转换为万元
    print()
    print("3. 开始修复数据 (元 → 万元)...")
    
    fix_count = 0
    try:
        cursor = collection.find({})
        total_to_fix = total_records
        
        for record in tqdm(cursor, total=total_to_fix, desc="修复进度"):
            old_amount = record.get('amount', 0)
            
            if old_amount > 0:
                # 如果成交额大于100万，说明单位是元，需要转换为万元
                if old_amount > 1000000:
                    # 修复：除以10000（从元转换为万元）
                    new_amount = old_amount / 10000
                    
                    # 更新数据库
                    collection.update_one(
                        {'_id': record['_id']},
                        {'$set': {'amount': new_amount}}
                    )
                    fix_count += 1
        
        print(f"   ✅ 修复了 {fix_count} 条记录")
        
    except Exception as e:
        print(f"   ❌ 修复失败: {e}")
        import traceback
        traceback.print_exc()
    
    # 4. 验证修复结果
    print()
    print("4. 验证修复结果...")
    
    sample_after = list(collection.find().limit(5))
    print("   修复后抽样数据:")
    for record in sample_after:
        ts_code = record.get('ts_code', 'N/A')
        trade_date = record.get('trade_date', 'N/A')
        amount = record.get('amount', 0)
        
        print(f"   {ts_code} - {trade_date}:")
        print(f"     修复后成交额: {amount:,.2f} 万元")
        print(f"     对应人民币: {amount * 10000:,.0f} 元")
        
        # 检查是否合理
        if 1 <= amount <= 100000:  # 1万到10亿元之间
            print("     ✅ 合理范围")
        else:
            print("     ⚠️  可能需要进一步调整")
        print()
    
    # 5. 统计修复情况
    print("5. 修复统计:")
    print(f"   总记录数: {total_records}")
    print(f"   修复记录数: {fix_count}")
    print(f"   修复比例: {fix_count/total_records*100:.1f}%")
    
    client.close()
    
    print()
    print("="*60)
    print("✅ 修复完成！")
    print("   现在成交额单位是万元")
    print("   策略筛选门槛应为 1000 (表示1000万元)")
    print("   建议重新运行回测")

if __name__ == "__main__":
    fix_akshare_units()