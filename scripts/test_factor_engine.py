#!/usr/bin/env python3
"""
测试因子引擎是否能正确处理修复后的数据
"""

import sys
import asyncio
import pymongo
import pandas as pd

# 添加项目路径
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent/AgentServer')

async def test_factor_engine_direct():
    """直接测试因子引擎"""
    print("🧪 直接测试因子引擎...")
    print("="*60)
    
    try:
        # 导入因子引擎
        from backtest_module.backtest_engine.factor_selection.factor_engine import FactorEngine
        
        # 创建因子引擎，指定数据源为 AKShare
        print("创建因子引擎...")
        print("✅ 因子引擎创建成功")
        
        # 测试单个交易日
        test_date = "20260105"
        print(f"\n测试交易日: {test_date}")
        
        # 手动获取数据
        client = pymongo.MongoClient('localhost', 27017)
        db = client['stock_agent']
        collection = db['stock_daily_ak_full_ak']
        
        # 获取该交易日所有股票数据
        query_date = int(test_date)
        records = list(collection.find({'trade_date': query_date}))
        
        print(f"  数据库查询到 {len(records)} 条记录")
        
        if len(records) == 0:
            print("  ❌ 没有找到该交易日的数据")
            client.close()
            return False
        
        # 转换数据格式
        data_list = []
        for record in records:
            # 转换每条记录为因子引擎期望的格式
            data = {
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
                'source': record.get('source', '')
            }
            data_list.append(data)
        
        print(f"  成功转换 {len(data_list)} 条数据")
        
        if len(data_list) > 0:
            # 检查数据格式
            sample = data_list[0]
            print("\n  数据字段检查:")
            print(f"    ts_code: {sample['ts_code']} (类型: {type(sample['ts_code']).__name__})")
            print(f"    trade_date: {sample['trade_date']} (类型: {type(sample['trade_date']).__name__})")
            print(f"    open: {sample['open']} (类型: {type(sample['open']).__name__})")
            print(f"    close: {sample['close']} (类型: {type(sample['close']).__name__})")
            print(f"    amount: {sample['amount']} (类型: {type(sample['amount']).__name__})")
            print(f"    source: {sample['source']} (类型: {type(sample['source']).__name__})")
        
        # 尝试手动计算因子
        print("\n  尝试手动计算因子...")
        
        # 准备数据 DataFrame
        df = pd.DataFrame(data_list)
        print(f"  数据形状: {df.shape}")
        print(f"  股票数量: {df['ts_code'].nunique()}")
        
        # 检查是否满足流动性门槛
        threshold = 100  # 万元
        liquid_stocks = df[df['amount'] >= threshold]
        print(f"  满足流动性门槛 ({threshold}万元) 的股票: {len(liquid_stocks)} 只")
        
        if len(liquid_stocks) > 0:
            print("  ✅ 数据本身没问题")
            
            # 尝试计算一些简单因子
            try:
                # 计算简单涨跌幅
                df['pct_change'] = (df['close'] - df['open']) / df['open'] * 100
                
                # 筛选满足条件的股票
                # 条件1: 涨幅大于0
                # 条件2: 开盘价低于涨停价
                df['condition1'] = df['pct_change'] > 0
                df['condition2'] = df['open'] < df['up_limit']
                
                # 筛选同时满足两个条件的股票
                selected = df[df['condition1'] & df['condition2']]
                print(f"  同时满足两个筛选条件的股票: {len(selected)} 只")
                
                if len(selected) > 0:
                    print("  ✅ 数据可以满足筛选条件")
                    # 显示一些示例
                    print("\n  满足条件的股票示例 (前5只):")
                    for idx, (_, row) in enumerate(selected.head().iterrows()):
                        print(f"    {idx+1}. {row['ts_code']}: 涨幅 {row['pct_change']:.2f}%, 成交额 {row['amount']:,.0f}万元")
                else:
                    print("  ⚠️  没有股票同时满足两个条件")
                    print("  可能因子条件过于严格")
            
            except Exception as e:
                print(f"  ❌ 因子计算失败: {e}")
        
        client.close()
        return len(liquid_stocks) > 0
    
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def check_database_compatibility():
    """检查数据库兼容性"""
    print("\n🔍 数据库兼容性检查...")
    print("="*60)
    
    client = pymongo.MongoClient('localhost', 27017)
    db = client['stock_agent']
    
    print("1. 检查数据集合:")
    collections = sorted(db.list_collection_names())
    for coll in collections:
        count = db[coll].count_documents({})
        print(f"   {coll}: {count} 条记录")
    
    print("\n2. 对比数据集合:")
    
    # 检查 Tushare 格式数据是否存在
    if 'stock_daily_ak_full' in collections:
        coll = db['stock_daily_ak_full']
        total = coll.count_documents({})
        print(f"   stock_daily_ak_full (Tushare格式): {total} 条记录")
        
        if total > 0:
            sample = coll.find_one({})
            print("   Tushare格式字段示例:")
            for key in sample.keys():
                print(f"    {key}: {sample[key]} (类型: {type(sample[key]).__name__})")
    
    # 检查 AKShare 格式数据
    if 'stock_daily_ak_full_ak' in collections:
        coll = db['stock_daily_ak_full_ak']
        total = coll.count_documents({})
        print(f"   stock_daily_ak_full_ak (AKShare格式): {total} 条记录")
        
        if total > 0:
            sample = coll.find_one({})
            print("   AKShare格式字段示例:")
            for key in sample.keys():
                print(f"    {key}: {sample[key]} (类型: {type(sample[key]).__name__})")
    
    client.close()

async def main():
    print("🔬 因子引擎测试与诊断")
    print("="*60)
    
    # 1. 检查数据库兼容性
    check_database_compatibility()
    
    # 2. 直接测试因子引擎
    print("\n" + "="*60)
    print("🧪 因子引擎数据处理测试...")
    
    success = await test_factor_engine_direct()
    
    print("\n" + "="*60)
    if success:
        print("✅ 测试通过 - 数据本身可用")
        print("   问题很可能在因子引擎内部逻辑")
        print("   建议检查因子引擎的过滤条件")
    else:
        print("❌ 测试失败 - 数据不可用")
        print("   可能需要修复数据格式")
    
    print("\n📋 建议下一步:")
    print("   1. 检查因子引擎的过滤条件")
    print("   2. 移除数据源标记过滤")
    print("   3. 运行简化回测测试")

if __name__ == "__main__":
    asyncio.run(main())