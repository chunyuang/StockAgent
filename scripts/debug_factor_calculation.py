#!/usr/bin/env python3
"""
调试因子计算，检查为什么 limit_up_yesterday 因子找不到股票
"""

import sys
import pymongo

# 添加项目路径
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

def analyze_limit_up_yesterday_factor():
    """分析 limit_up_yesterday 因子的计算逻辑"""
    print("🔍 分析 limit_up_yesterday 因子")
    print("="*60)
    
    client = pymongo.MongoClient('localhost', 27017)
    db = client['stock_agent']
    collection = db['stock_daily_ak_full']
    
    # 1. 检查数据
    print("1. 检查数据...")
    total = collection.count_documents({})
    print(f"   总记录数: {total}")
    
    # 2. 选择两个连续的交易日进行分析
    print("\n2. 选择连续交易日进行分析...")
    
    # 获取所有交易日
    all_dates = sorted(collection.distinct('trade_date'))
    if len(all_dates) < 2:
        print("   ❌ 至少需要2个交易日的数据")
        client.close()
        return
    
    date1 = all_dates[0]  # 20260105
    date2 = all_dates[1]  # 20260106
    
    print(f"   交易日1: {date1}")
    print(f"   交易日2: {date2}")
    
    # 3. 获取这两个交易日的数据
    print("\n3. 获取两个交易日的数据...")
    
    data_date1 = list(collection.find({'trade_date': date1}))
    data_date2 = list(collection.find({'trade_date': date2}))
    
    print(f"   交易日 {date1}: {len(data_date1)} 条记录")
    print(f"   交易日 {date2}: {len(data_date2)} 条记录")
    
    if len(data_date1) == 0 or len(data_date2) == 0:
        print("   ❌ 某个交易日没有数据")
        client.close()
        return
    
    # 4. 分析 limit_up_yesterday 因子的逻辑
    print("\n4. 分析 limit_up_yesterday 因子逻辑...")
    print("   因子定义: 前一日收盘价等于涨停价")
    print("   即: 前一日 close == up_limit")
    
    # 检查哪些股票在前一日涨停
    print(f"\n   检查交易日 {date1} 的涨停股票:")
    limit_up_stocks = []
    
    for record in data_date1:
        ts_code = record.get('ts_code', '')
        close = record.get('close', 0.0)
        up_limit = record.get('up_limit', 0.0)
        
        # 检查是否涨停
        if abs(close - up_limit) < 0.001:  # 考虑浮点数精度
            limit_up_stocks.append(ts_code)
            print(f"     {ts_code}: 收盘价 {close} ≈ 涨停价 {up_limit} ✅ 涨停")
    
    print(f"   总计涨停股票: {len(limit_up_stocks)} 只")
    
    if len(limit_up_stocks) == 0:
        print("   ⚠️  交易日1没有涨停股票")
        print("   这可能是问题所在 - limit_up_yesterday 因子找不到涨停股票")
    else:
        print(f"   涨停股票列表: {limit_up_stocks[:10]}...")
        
        # 检查这些股票在交易日2是否满足其他条件
        print(f"\n   检查涨停股票在交易日 {date2} 的情况:")
        for ts_code in limit_up_stocks[:5]:  # 只检查前5只
            record2 = collection.find_one({'ts_code': ts_code, 'trade_date': date2})
            if record2:
                open_price = record2.get('open', 0.0)
                up_limit2 = record2.get('up_limit', 0.0)
                
                print(f"     {ts_code}:")
                print(f"       开盘价: {open_price}")
                print(f"       涨停价: {up_limit2}")
                print(f"       是否开板: {open_price < up_limit2}")
    
    # 5. 检查数据完整性
    print("\n5. 检查数据完整性...")
    
    # 检查是否有 up_limit 字段
    sample = data_date1[0]
    has_up_limit = 'up_limit' in sample
    has_down_limit = 'down_limit' in sample
    
    print(f"   有涨停价字段: {has_up_limit}")
    print(f"   有跌停价字段: {has_down_limit}")
    
    if has_up_limit:
        # 检查涨停价计算是否正确
        print("\n   涨停价计算检查:")
        for i, record in enumerate(data_date1[:3], 1):
            ts_code = record.get('ts_code', '')
            close = record.get('close', 0.0)
            up_limit = record.get('up_limit', 0.0)
            
            # 计算理论涨停价
            if ts_code.startswith(('688.', '300.')):  # 科创板/创业板
                theoretical_up_limit = round(close * 1.2, 2)
                market = "科创/创业"
            else:  # 主板
                theoretical_up_limit = round(close * 1.1, 2)
                market = "主板"
            
            match = abs(up_limit - theoretical_up_limit) < 0.01
            
            print(f"     {i}. {ts_code} ({market}):")
            print(f"        收盘价: {close}")
            print(f"        涨停价: {up_limit}")
            print(f"        理论涨停价: {theoretical_up_limit}")
            print(f"        是否匹配: {'✅' if match else '❌'}")
    
    # 6. 检查因子计算可能的问题
    print("\n6. 因子计算可能的问题...")
    
    # 检查涨停价是否为0
    zero_up_limit = []
    for record in data_date1:
        if record.get('up_limit', 0) == 0:
            zero_up_limit.append(record.get('ts_code', ''))
    
    if zero_up_limit:
        print(f"   ⚠️  发现 {len(zero_up_limit)} 只股票的涨停价为0")
        print(f"     示例: {zero_up_limit[:5]}")
        print("     这会导致 limit_up_yesterday 因子计算失败")
    
    # 检查是否有 pre_close 字段（某些因子可能需要）
    has_pre_close = 'pre_close' in sample
    print(f"   有前收盘价字段: {has_pre_close}")
    
    if not has_pre_close:
        print("   ⚠️  缺少 pre_close 字段")
        print("     某些因子可能需要前收盘价来计算涨跌幅")
    
    client.close()
    
    print()
    print("="*60)
    
    # 总结
    print("📋 问题分析总结:")
    
    if len(limit_up_stocks) == 0:
        print("   ❌ 主要问题: 交易日1没有涨停股票")
        print("     可能原因:")
        print("     1. 涨停价计算错误")
        print("     2. 数据本身就没有涨停股票")
        print("     3. 涨停价字段为0")
    else:
        print("   ✅ 有涨停股票，但因子可能没有正确计算")
        print("     可能原因:")
        print("     1. 因子计算逻辑有问题")
        print("     2. 数据格式不匹配")
        print("     3. 因子参数设置问题")
    
    print()
    print("🛠️ 建议解决方案:")
    print("   1. 检查涨停价计算是否正确")
    print("   2. 验证因子计算逻辑")
    print("   3. 检查是否有必需字段缺失")

def check_factor_library():
    """检查因子库中的因子定义"""
    print("\n📚 检查因子库...")
    print("="*60)
    
    try:
        from backtest_module.backtest_engine.factor_selection.factor_library import FactorLibrary
        
        factor_library = FactorLibrary()
        factors = factor_library.factors
        
        print(f"   因子库中共有 {len(factors)} 个因子")
        
        # 查找 limit_up_yesterday 因子
        if 'limit_up_yesterday' in factors:
            factor_info = factors['limit_up_yesterday']
            print("\n   limit_up_yesterday 因子详情:")
            print(f"     描述: {factor_info.get('description', '无描述')}")
            print(f"     类型: {factor_info.get('type', '未知')}")
            print(f"     参数: {factor_info.get('params', {})}")
            
            # 检查计算函数
            if 'func' in factor_info:
                print("     有计算函数")
            else:
                print("     ⚠️  没有计算函数")
        else:
            print("   ❌ limit_up_yesterday 因子不在因子库中")
        
        # 列出所有因子
        print("\n   所有因子列表:")
        for factor_name in sorted(factors.keys()):
            factor_info = factors[factor_name]
            desc = factor_info.get('description', '无描述')
            print(f"     {factor_name}: {desc[:50]}...")
    
    except Exception as e:
        print(f"   检查因子库失败: {e}")

def main():
    print("🔬 因子计算详细分析")
    
    # 1. 分析 limit_up_yesterday 因子
    analyze_limit_up_yesterday_factor()
    
    # 2. 检查因子库
    check_factor_library()
    
    print()
    print("="*60)
    print("✅ 分析完成")
    print("   需要进一步检查涨停价计算和因子实现")

if __name__ == "__main__":
    main()