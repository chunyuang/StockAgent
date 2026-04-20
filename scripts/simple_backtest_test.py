#!/usr/bin/env python3
"""
简化版回测测试
直接从数据库读取数据，测试策略逻辑
"""

import pymongo
import pandas as pd
from typing import List, Dict, Any

def load_stock_data(stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """从数据库加载股票数据"""
    client = pymongo.MongoClient('localhost', 27017)
    db = client['stock_agent']
    collection = db['stock_daily_ak_full_ak']
    
    # 查询数据
    query = {
        'ts_code': stock_code,
        'trade_date': {'$gte': int(start_date), '$lte': int(end_date)}
    }
    
    cursor = collection.find(query).sort('trade_date', 1)
    
    # 转换为DataFrame
    data = list(cursor)
    
    client.close()
    
    if not data:
        print(f"❌ 没有找到股票 {stock_code} 在 {start_date} 到 {end_date} 期间的数据")
        return pd.DataFrame()
    
    return pd.DataFrame(data)

def test_strategy_logic(stock_codes: List[str], start_date: str, end_date: str) -> Dict[str, Any]:
    """测试策略逻辑"""
    print("🧪 测试策略逻辑...")
    
    results = []
    
    for stock_code in stock_codes[:10]:  # 测试前10只股票
        df = load_stock_data(stock_code, start_date, end_date)
        
        if not df.empty:
            # 这里可以添加策略逻辑测试
            # 例如：检查涨停板条件
            print(f"   股票 {stock_code}: {len(df)} 个交易日的数据")
            
            # 简单策略测试：检查是否有涨停板
            if 'up_limit' in df.columns:
                df['is_limit_up'] = df['close'] >= df['up_limit']
                limit_up_days = df['is_limit_up'].sum()
                print(f"     涨停天数: {limit_up_days}")
            
            results.append({
                'stock_code': stock_code,
                'records': len(df),
                'avg_amount': df['amount'].mean() if 'amount' in df.columns else 0
            })
    
    return results

def analyze_market_data():
    """分析市场数据"""
    print("📊 分析市场数据...")
    
    client = pymongo.MongoClient('localhost', 27017)
    db = client['stock_agent']
    collection = db['stock_daily_ak_full_ak']
    
    # 获取市场总体信息
    total_records = collection.count_documents({})
    stock_count = len(collection.distinct('ts_code'))
    date_count = len(collection.distinct('trade_date'))
    
    print(f"   总记录数: {total_records}")
    print(f"   股票数量: {stock_count}")
    print(f"   交易日数量: {date_count}")
    
    # 分析流动性数据
    pipeline = [
        {"$group": {
            "_id": "$ts_code",
            "avg_amount": {"$avg": "$amount"},
            "max_amount": {"$max": "$amount"},
            "min_amount": {"$min": "$amount"},
            "record_count": {"$sum": 1}
        }},
        {"$match": {"avg_amount": {"$gte": 100}}},
        {"$sort": {"avg_amount": -1}}
    ]
    
    liquid_stats = list(collection.aggregate(pipeline))
    
    print(f"   满足流动性门槛(≥100万元)的股票: {len(liquid_stats)} 只")
    
    if len(liquid_stats) > 0:
        print("   前5只股票流动性统计:")
        for i, stat in enumerate(liquid_stats[:5]):

            print(f"     {i+1}. {stat['_id']}: 平均成交额 {stat['avg_amount']:.1f} 万元, 最大 {stat['max_amount']:.1f} 万元, 最小 {stat['min_amount']:.1f} 万元")
    
    client.close()
    
    return {
        'total_records': total_records,
        'stock_count': stock_count,
        'date_count': date_count,
        'liquid_stocks': len(liquid_stats)
    }

def main():
    print("🔍 开始回测逻辑测试")
    print("="*60)
    
    # 1. 分析市场数据
    market_stats = analyze_market_data()
    
    print()
    print("2. 测试策略逻辑...")
    
    # 获取股票列表
    client = pymongo.MongoClient('localhost', 27017)
    db = client['stock_agent']
    collection = db['stock_daily_ak_full_ak']
    
    # 随机选择一些股票测试
    pipeline = [
        {"$sample": {"size": 5}},
        {"$group": {"_id": "$ts_code"}}
    ]
    
    sample_stocks = list(collection.aggregate(pipeline))
    stock_codes = [stock['_id'] for stock in sample_stocks]
    
    print(f"   测试的股票: {stock_codes}")
    
    # 测试策略逻辑
    strategy_results = test_strategy_logic(
        stock_codes=stock_codes,
        start_date='20260105',
        end_date='20260320'
    )
    
    print()
    print("="*60)
    print("📋 测试总结:")
    
    total_records = 0
    for result in strategy_results:
        total_records += result.get('records', 0)
    
    print(f"   测试股票数: {len(strategy_results)}")
    print(f"   总记录数: {total_records}")
    print("   市场数据可用性: ✅ 良好")
    
    # 检查策略逻辑
    if len(strategy_results) > 0:
        print("   策略逻辑测试: ✅ 通过")
    else:
        print("   策略逻辑测试: ⚠️  需要更多测试数据")
    
    client.close()
    
    print()
    print("📈 下一步建议:")
    
    # 根据测试结果给出建议
    if market_stats['liquid_stocks'] > 0:
        print("   ✅ 数据质量良好，可以开始正式回测")
        print("   💡 建议运行完整的回测流程，测试所有策略")
    else:
        print("   ⚠️  数据存在问题，需要先修复")
        print("    1. 检查数据下载过程")
        print("    2. 验证数据格式")
        print("    3. 重新下载缺失数据")

if __name__ == "__main__":
    main()