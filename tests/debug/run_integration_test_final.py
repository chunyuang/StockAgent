
import sys
sys.path.insert(0, './AgentServer')
import asyncio

async def main():
    # 先初始化manager
    from core.managers import mongo_manager, redis_manager
    await mongo_manager.initialize()
    await redis_manager.initialize()
    print('✅ MongoDB和Redis初始化完成')

    # 导入回测器
    from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester

    print('=' * 80)
    print('🚀 开始集成测试回测（20260105-20260115，共11天）')
    print('=' * 80)

    bt = PortfolioBacktester()
    config = {
        'start_date': '20260105',
        'end_date': '20260115',
        'initial_cash': 1000000,
        'universe': 'all_a',
        'top_n': 20,
        'liquidity_threshold': 5000000,  # 500万
        'enable_force_empty': True,
        'enable_sentiment_cycle': True,
    }
    
    result = await bt.run(config)
    
    print()
    print('=' * 80)
    print('✅ 回测完成！现在分析风控效果...')
    print('=' * 80)
    
    # 分析结果
    print()
    print('===== 📊 风控验证结果 =====')
    print()
    
    # 1. 检查强制空仓日
    rebalance_records = result.get('rebalance_records', [])
    for record in rebalance_records:
        date = record.get('date', '')
        print(f'📅 {date}:')
        
        # 强制空仓检查
        is_force_empty = record.get('is_force_empty', False)
        if is_force_empty:
            print(f'  ✅ 触发强制空仓！')
        else:
            print(f'  ⚠️  未触发强制空仓')
            
        # 检查实际仓位
        total_position = record.get('total_position_ratio', 0)
        print(f'  实际仓位: {total_position:.1%}')
        
        # 情绪周期检查
        sentiment = record.get('sentiment', '未知')
        print(f'  情绪周期: {sentiment}')
        print()

asyncio.run(main())
