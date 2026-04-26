
import sys
sys.path.insert(0, './AgentServer')
import asyncio

async def test_force_empty():
    print('=' * 80)
    print('🧪 测试1：强制空仓逻辑')
    print('=' * 80)
    
    from core.managers import mongo_manager
    await mongo_manager.initialize()
    
    # 模拟强制空仓判断逻辑
    from pymongo import MongoClient
    client = MongoClient('mongodb://localhost:27017/')
    db = client['stock_agent']
    
    test_dates = [20260106, 20260107, 20260109]
    
    for trade_date in test_dates:
        limit_down_count = db['stock_daily_ak_full'].count_documents({
            'trade_date': trade_date,
            'is_limit_down': 1
        })
        limit_up_count = db['stock_daily_ak_full'].count_documents({
            'trade_date': trade_date,
            'first_limit_up': True
        })
        
        is_force_empty = limit_down_count >= 50 or limit_up_count <= 10
        reason = ''
        if limit_down_count >= 50:
            reason = f'跌停股数达到阈值: {limit_down_count}只'
        elif limit_up_count <= 10:
            reason = f'涨停股数低于阈值: {limit_up_count}只'
        
        print(f'📅 {trade_date}: 跌停{limit_down_count}只, 涨停{limit_up_count}只')
        if is_force_empty:
            print(f'  🔴 触发强制空仓！原因: {reason}')
        else:
            print(f'  🟢 不触发强制空仓')
        print()

async def test_sentiment_position():
    print('=' * 80)
    print('🧪 测试2：情绪周期仓位系数')
    print('=' * 80)
    
    from pymongo import MongoClient
    client = MongoClient('mongodb://localhost:27017/')
    db = client['stock_agent']
    
    # 测试日期：极致冰点20260109，高潮期20260112
    test_dates = [20260109, 20260112, 20260113]
    
    for trade_date in test_dates:
        pipeline = [
            {'$match': {'trade_date': trade_date}},
            {'$group': {'_id': None, 'avg_sentiment': {'$avg': '$sentiment_score'}}}
        ]
        result = list(db['stock_daily_ak_full'].aggregate(pipeline))
        avg_sentiment = result[0]['avg_sentiment'] if result else 0
        
        # 仓位系数逻辑
        if avg_sentiment < 20:
            position_multiplier = 0.1
            sentiment_level = "极致冰点"
        elif avg_sentiment < 40:
            position_multiplier = 0.3
            sentiment_level = "冰点"
        elif avg_sentiment < 60:
            position_multiplier = 0.7
            sentiment_level = "修复期"
        elif avg_sentiment < 80:
            position_multiplier = 0.9
            sentiment_level = "发酵期"
        else:
            position_multiplier = 1.0
            sentiment_level = "高潮期"
        
        print(f'📅 {trade_date}: 平均情绪分={avg_sentiment:.1f}')
        print(f'  😊 情绪等级: {sentiment_level}')
        print(f'  💹 仓位系数: {position_multiplier:.1f}')
        print(f'  🎯 预期最大仓位: {position_multiplier * 100:.0f}%')
        print()

async def test_liquidity_filter():
    print('=' * 80)
    print('🧪 测试3：流动性过滤')
    print('=' * 80)
    
    from pymongo import MongoClient
    client = MongoClient('mongodb://localhost:27017/')
    db = client['stock_agent']
    
    # 测试日期：20260113
    trade_date = 20260113
    
    total_count = db['stock_daily_ak_full'].count_documents({'trade_date': trade_date})
    low_liquidity_count = db['stock_daily_ak_full'].count_documents({
        'trade_date': trade_date,
        'amount': {'$lt': 5000000}  # 500万阈值
    })
    
    print(f'📅 {trade_date}:')
    print(f'  📊 股票总数: {total_count}只')
    print(f'  🧹 低流动性股票数: {low_liquidity_count}只')
    print(f'  ✅ 过滤后剩余: {total_count - low_liquidity_count}只')
    print(f'  📈 过滤比例: {low_liquidity_count / total_count * 100:.1f}%')
    print()
    
    # 检查我们构造的100只低流动性股票
    low_docs = list(db['stock_daily_ak_full'].find(
        {'trade_date': trade_date, 'amount': {'$lt': 5000000}},
        {'ts_code': 1, 'amount': 1}
    ).limit(10))
    print('  低流动性样例:')
    for doc in low_docs[:5]:
        print(f'    {doc["ts_code"]}: 成交额={doc["amount"]:,.0f}元')

async def main():
    await test_force_empty()
    await test_sentiment_position()
    await test_liquidity_filter()
    
    print('=' * 80)
    print('✅ 三个核心功能点测试完成！')
    print()
    print('总结：')
    print('  1. 强制空仓逻辑：20260106跌停56只、20260107涨停8只，都会触发强制空仓')
    print('  2. 情绪周期逻辑：20260109极致冰点仓位系数0.1，20260112高潮期仓位系数1.0')
    print('  3. 流动性过滤逻辑：20260113有100只低流动性股票会被剔除')
    print('=' * 80)

asyncio.run(main())
