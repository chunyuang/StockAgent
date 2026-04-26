
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
    print('✅ 回测完成！result.keys():', list(result.keys()))
    print('=' * 80)
    
    # 详细打印所有结果
    print()
    print('总收益率:', result.get('total_return', 0))
    print('夏普比率:', result.get('sharpe_ratio', 0))
    print('最大回撤:', result.get('max_drawdown', 0))
    print('交易次数:', result.get('total_trades', 0))
    print()
    
    rebalance_records = result.get('rebalance_records', [])
    print('调仓记录数:', len(rebalance_records))
    print()
    
    for record in rebalance_records:
        print('-' * 60)
        date = record.get('date', '未知日期')
        print('📅 %s:' % date)
        
        # 强制空仓检查
        is_force_empty = record.get('is_force_empty', False)
        force_empty_reason = record.get('force_empty_reason', '')
        if is_force_empty:
            print('  🔴 强制空仓触发！原因: %s' % force_empty_reason)
        else:
            print('  🟢 未触发强制空仓')
            
        # 检查实际持仓数量
        holdings = record.get('holdings', [])
        print('  持仓数量: %d只' % len(holdings))
        
        # 检查实际仓位
        total_position = record.get('total_position_ratio', 0)
        print('  实际仓位: %.1f%%' % (total_position * 100))
        
        # 情绪周期检查
        sentiment = record.get('sentiment', '未知')
        sentiment_score = record.get('sentiment_score', 0)
        position_multiplier = record.get('position_multiplier', 1.0)
        print('  情绪周期: %s' % sentiment)
        print('  情绪分数: %.1f' % sentiment_score)
        print('  仓位乘数: %.2f' % position_multiplier)
        
        # 流动性过滤检查
        low_liquidity_count = record.get('low_liquidity_filtered', 0)
        if low_liquidity_count > 0:
            print('  🧹 流动性过滤: 剔除 %d 只低流动性股票' % low_liquidity_count)
        
        print()

asyncio.run(main())
