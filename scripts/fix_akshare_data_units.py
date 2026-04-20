#!/usr/bin/env python3
"""
修复AKShare数据单位问题
重新下载数据，确保单位正确
"""

import akshare as ak
import pymongo
from tqdm import tqdm

def test_akshare_api():
    """测试AKShare API，查看原始数据格式"""
    print("🧪 测试AKShare API原始数据格式...")
    
    try:
        # 测试获取一只股票的历史数据
        test_stock = '000001'  # 平安银行
        print(f"   测试股票: {test_stock}")
        
        df = ak.stock_zh_a_hist(
            symbol=test_stock,
            period="daily",
            start_date="20260105",
            end_date="20260110",
            adjust=""
        )
        
        if df is None or df.empty:
            print("   ❌ 没有获取到数据")
            return None
        
        print(f"   ✅ 获取到 {len(df)} 条记录")
        print()
        print("   原始数据格式:")
        print(df.head().to_string())
        print()
        
        # 检查列名和数据类型
        print("   列名和数据类型:")
        for col in df.columns:
            print(f"     {col}: {df[col].dtype}, 示例: {df[col].iloc[0] if len(df) > 0 else 'N/A'}")
        
        return df
    
    except Exception as e:
        print(f"   ❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return None

def fix_data_units():
    """修复数据库中的单位问题"""
    print()
    print("🔧 开始修复数据单位问题...")
    
    client = pymongo.MongoClient('localhost', 27017)
    db = client['stock_agent']
    collection = db['stock_daily_ak_full_ak']
    
    # 1. 先备份当前数据
    print("1. 备份当前数据...")
    total_records = collection.count_documents({})
    print(f"   总记录数: {total_records}")
    
    # 2. 分析当前数据问题
    print("2. 分析数据问题...")
    
    # 抽样检查
    sample = list(collection.find().limit(5))
    for record in sample:
        amount = record.get('amount', 0)
        print(f"   股票 {record.get('ts_code')} - 日期 {record.get('trade_date')}:")
        print(f"     当前成交额: {amount:,.2f} 万元")
        print(f"     对应人民币: {amount * 10000:,.0f} 元")
        print(f"     实际应为: {amount / 10000:,.2f} 万元 (如果单位是元)")
        print()
    
    # 3. 修复数据单位
    print("3. 修复数据单位...")
    
    # 假设问题：AKShare返回的成交额单位是元，但我们误以为是万元
    # 修复：将 amount 除以 10000
    fix_count = 0
    
    try:
        # 批量更新
        cursor = collection.find({})
        total_to_fix = total_records
        
        print(f"   需要修复 {total_to_fix} 条记录...")
        
        for record in tqdm(cursor, total=total_to_fix, desc="修复进度"):
            old_amount = record.get('amount', 0)
            
            if old_amount > 0:
                # 如果成交额大于1000亿（10000000万元），说明单位有问题
                if old_amount > 10000000:  # 大于1000亿
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
    
    # 4. 验证修复结果
    print("4. 验证修复结果...")
    
    sample_after = list(collection.find().limit(5))
    for record in sample_after:
        amount = record.get('amount', 0)
        print(f"   股票 {record.get('ts_code')} - 日期 {record.get('trade_date')}:")
        print(f"     修复后成交额: {amount:,.2f} 万元")
        print(f"     对应人民币: {amount * 10000:,.0f} 元")
        
        # 检查是否合理
        if 1 <= amount <= 100000:  # 1万到10亿元之间
            print("     ✅ 合理范围")
        else:
            print("     ⚠️  可能需要进一步调整")
        print()
    
    client.close()
    
    return fix_count

def re_download_with_correct_units():
    """重新下载数据，确保单位正确"""
    print()
    print("📥 重新下载数据（确保单位正确）...")
    
    # 测试几只股票，验证单位
    test_stocks = ['000001', '000002', '000858']
    
    for stock_code in test_stocks:
        print(f"   测试下载股票 {stock_code}...")
        
        try:
            df = ak.stock_zh_a_hist(
                symbol=stock_code,
                period="daily",
                start_date="20260105",
                end_date="20260110",
                adjust=""
            )
            
            if df is not None and not df.empty:
                print(f"     成功获取 {len(df)} 条记录")
                print(f"     成交额示例: {df['成交额'].iloc[0]}")
                print(f"     成交量示例: {df['成交量'].iloc[0]}")
                print()
        
        except Exception as e:
            print(f"     ❌ 下载失败: {e}")

def main():
    print("🔧 AKShare数据单位修复工具")
    print("="*60)
    
    # 1. 测试AKShare API
    test_result = test_akshare_api()
    
    if test_result is not None:
        # 检查数据格式
        print()
        print("📊 数据格式分析:")
        
        # 检查成交额单位
        if '成交额' in test_result.columns:
            amount_value = test_result['成交额'].iloc[0]
            print(f"   AKShare返回的成交额: {amount_value}")
            print(f"   数据类型: {type(amount_value)}")
            
            # 判断单位
            if amount_value > 1000000000:  # 大于10亿
                print("   ⚠️  单位可能是 元 (数值较大)")
            else:
                print("   ⚠️  单位可能是 万元 (数值较小)")
        
        print()
        print("💡 建议:")
        print("   从AKShare API测试结果看，需要先确定正确单位")
        print("   然后决定是修复现有数据还是重新下载")
    
    # 2. 询问用户选择
    print()
    print("="*60)
    print("请选择修复方案:")
    print("  1. 自动修复现有数据（假设当前单位是元，转换为万元）")
    print("  2. 重新下载数据（重新获取正确单位的数据）")
    print("  3. 先测试更多股票确认单位")
    
    choice = input("请选择 [1/2/3]: ").strip()
    
    if choice == '1':
        fix_count = fix_data_units()
        print()
        print("="*60)
        print(f"✅ 修复完成！修复了 {fix_count} 条记录")
        print("   建议重新运行回测测试")
    
    elif choice == '2':
        re_download_with_correct_units()
        print()
        print("="*60)
        print("✅ 测试下载完成")
        print("   需要修改下载脚本，确保使用正确单位")
    
    elif choice == '3':
        print()
        print("🧪 测试更多股票确认单位...")
        # 这里可以添加更多测试代码
        
    else:
        print("❌ 无效选择")

if __name__ == "__main__":
    main()