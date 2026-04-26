
import sys
sys.path.insert(0, './AgentServer/nodes/backtest_engine/factor_selection')

# 先初始化manager
from core.managers import mongo_manager, redis_manager
import asyncio

async def init_managers():
    await mongo_manager.initialize()
    await redis_manager.initialize()
    print('✅ MongoDB和Redis初始化完成')

asyncio.run(init_managers())

# 直接导入
print('导入回测器...')
import importlib.util
spec = importlib.util.spec_from_file_location(
    'portfolio_backtest', 
    './AgentServer/nodes/backtest_engine/factor_selection/portfolio_backtest.py'
)
pb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pb)
PortfolioBacktester = pb.PortfolioBacktester

print('=' * 80)
print('🚀 开始集成测试回测（20260105-20260115，共11天）')
print('=' * 80)

async def run_test():
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
    return result

result = asyncio.run(run_test())
print()
print('=' * 80)
print('✅ 回测完成！现在分析风控效果...')
print('=' * 80)
