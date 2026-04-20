#!/usr/bin/env python3
"""
创建兼容性数据层
将 stock_daily_ak_full_ak 数据复制到 stock_daily_ak_full 集合
确保因子引擎能找到数据
"""

import pymongo
from tqdm import tqdm

def create_compatibility_layer():
    print("🔧 创建兼容性数据层")
    print("="*60)
    
    client = pymongo.MongoClient('localhost', 27017)
    db = client['stock_agent']
    
    source_collection = db['stock_daily_ak_full_ak']
    target_collection = db['stock_daily_ak_full']
    
    # 1. 检查源数据
    print("1. 检查源数据...")
    source_count = source_collection.count_documents({})
    print(f"   源数据 (stock_daily_ak_full_ak): {source_count} 条记录")
    
    if source_count == 0:
        print("   ❌ 源数据为空，无法继续")
        client.close()
        return False
    
    # 2. 清空目标集合（如果存在）
    print("2. 准备目标集合...")
    target_count = target_collection.count_documents({})
    if target_count > 0:
        print(f"   目标集合已有 {target_count} 条记录，清空...")
        target_collection.delete_many({})
        print("   ✅ 目标集合已清空")
    
    # 3. 复制数据，移除或修改 source 字段
    print("3. 复制数据并调整格式...")
    
    total_copied = 0
    batch_size = 100
    operations = []
    
    # 分批处理
    cursor = source_collection.find({})
    total_to_copy = source_count
    
    for record in tqdm(cursor, total=total_to_copy, desc="复制进度"):
        # 创建新记录，移除或修改 source 字段
        new_record = {
            '_id': record['_id'],  # 保持相同的_id
            'ts_code': record.get('ts_code', ''),
            'trade_date': record.get('trade_date', 0),
            'open': record.get('open', 0.0),
            'high': record.get('high', 0.0),
            'low': record.get('low', 0.0),
            'close': record.get('close', 0.0),
            'vol': record.get('vol', 0.0),
            'amount': record.get('amount', 0.0),
            'up_limit': record.get('up_limit', 0.0),
            'down_limit': record.get('down_limit', 0.0),
            # 移除 source 字段，或者设置为空字符串
            # 'source': ''  # 不添加 source 字段
        }
        
        operations.append(pymongo.ReplaceOne({'_id': new_record['_id']}, new_record, upsert=True))
        
        # 批量插入
        if len(operations) >= batch_size:
            result = target_collection.bulk_write(operations)
            total_copied += result.upserted_count + result.modified_count
            operations = []
    
    # 处理剩余的记录
    if operations:
        result = target_collection.bulk_write(operations)
        total_copied += result.upserted_count + result.modified_count
    
    print(f"   ✅ 复制完成: {total_copied} 条记录")
    
    # 4. 验证复制结果
    print("4. 验证复制结果...")
    final_count = target_collection.count_documents({})
    print(f"   目标集合 (stock_daily_ak_full): {final_count} 条记录")
    
    if final_count == source_count:
        print("   ✅ 数据量匹配")
    else:
        print(f"   ⚠️  数据量不匹配: 源 {source_count} vs 目标 {final_count}")
    
    # 5. 检查数据格式
    print("5. 检查数据格式...")
    sample = target_collection.find_one({})
    if sample:
        print("   目标集合字段示例:")
        for key, value in sample.items():
            if key != '_id':
                print(f"     {key}: {value} (类型: {type(value).__name__})")
        
        # 检查是否还有 source 字段
        if 'source' in sample:
            print(f"   ⚠️  仍然包含 source 字段: {sample['source']}")
        else:
            print("   ✅ 已移除 source 字段")
    
    # 6. 创建索引
    print("6. 创建索引...")
    try:
        target_collection.create_index([('ts_code', 1), ('trade_date', -1)])
        target_collection.create_index([('trade_date', -1)])
        print("   ✅ 索引创建完成")
    except Exception as e:
        print(f"   ❌ 创建索引失败: {e}")
    
    client.close()
    
    print()
    print("="*60)
    print("✅ 兼容性数据层创建完成!")
    print(f"   源数据: {source_count} 条记录")
    print(f"   目标数据: {final_count} 条记录")
    print("   现在可以运行回测测试了")
    
    return final_count > 0

def test_compatibility():
    """测试兼容性"""
    print("\n🧪 测试兼容性...")
    print("="*60)
    
    client = pymongo.MongoClient('localhost', 27017)
    db = client['stock_agent']
    
    # 检查两个集合
    collections = ['stock_daily_ak_full', 'stock_daily_ak_full_ak']
    
    for coll_name in collections:
        if coll_name in db.list_collection_names():
            coll = db[coll_name]
            count = coll.count_documents({})
            print(f"{coll_name}: {count} 条记录")
            
            # 检查字段
            if count > 0:
                sample = coll.find_one({})
                fields = list(sample.keys())
                fields.remove('_id')
                print(f"  字段: {', '.join(fields)}")
        else:
            print(f"{coll_name}: 集合不存在")
    
    client.close()

def main():
    print("🚀 开始执行兼容性测试")
    print("="*60)
    
    # 1. 创建兼容性数据层
    success = create_compatibility_layer()
    
    if not success:
        print("❌ 创建兼容性数据层失败")
        return
    
    # 2. 测试兼容性
    test_compatibility()
    
    print("\n" + "="*60)
    print("📋 下一步:")
    print("   1. 运行简化回测测试")
    print("   2. 验证是否能找到可交易的股票")
    print("   3. 如果成功，说明问题已解决")
    print("   4. 如果失败，需要进一步调试")

if __name__ == "__main__":
    main()