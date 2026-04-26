
import sys
sys.path.insert(0, './AgentServer')
import asyncio

async def diagnose_factor_nan():
    print('=' * 80)
    print('🔍 深度诊断：为什么因子计算全是NaN？')
    print('=' * 80)
    print()
    
    from core.managers import mongo_manager
    await mongo_manager.initialize()
    
    import pandas as pd
    from pymongo import MongoClient
    client = MongoClient('mongodb://localhost:27017/')
    db = client['stock_agent']
    
    test_date = "20260108"
    test_code = "000001.SZ"
    
    print('🔍 调查1：单只股票的历史数据情况')
    print('-' * 80)
    
    # 查20260101到20260115的数据，看有多少天
    docs = list(db['stock_daily_ak_full'].find(
        {"ts_code": test_code, "trade_date": {"$gte": 20260101, "$lte": 20260115}},
        {"trade_date": 1, "close": 1}
    ).sort("trade_date", 1))
    
    print(f'  股票 {test_code} 在 20260101-20260115 期间:')
    print(f'    有 {len(docs)} 条数据')
    print(f'    日期列表: {[d["trade_date"] for d in docs]}')
    print()
    
    print('🔍 调查2：看FactorEngine加载了多少天数据')
    print('-' * 80)
    
    # 模拟FactorEngine的数据加载逻辑
    from nodes.backtest_engine.factor_selection.factor_engine import FactorEngine
    from nodes.backtest_engine.factor_selection.universe import UniverseManager, UniverseType
    from nodes.backtest_engine.factor_selection.factor_library import FactorLibrary
    
    universe_mgr = UniverseManager()
    factor_engine = FactorEngine()
    
    stocks = await universe_mgr.get_universe(UniverseType.ALL_A, test_date, exclude_rules=[])
    stocks_list = list(stocks)[:10]
    
    # 加载momentum_20d因子需要的数据
    factor_def = FactorLibrary.get("momentum_20d")
    print(f'  因子 {factor_def.name}, lookback_days = {factor_def.lookback_days}')
    print()
    
    # 手动调用_load_all_data，看看实际加载了多少天
    factor_defs = [factor_def]
    loaded_data = await factor_engine._load_all_data(stocks_list, test_date, factor_defs, 60)
    
    daily_data = loaded_data.get("daily", {})
    print(f'  加载了 {len(daily_data)} 只股票的数据')
    if daily_data:
        first_code = list(daily_data.keys())[0]
        df = daily_data[first_code]
        print(f'  {first_code} 的数据天数: {len(df)}天')
        print(f'  数据日期范围: {df.index.min()} 到 {df.index.max()}')
        print(f'  数据列: {list(df.columns)}')
        print(f'  行数: {len(df)}')
    
    print()
    print('=' * 80)
    print('💡 根因分析')
    print('=' * 80)
    print()
    print('  问题定位：factor_engine.py 第216-217行')
    print()
    print('  代码写死了：')
    print('    # 🔥 修复：保证 start_dt 不早于当前交易日')
    print('    start_dt = max(start_dt, end_dt)')
    print()
    print('  这样做的后果：')
    print('    - 原本需要查 60 天历史数据计算动量')
    print('    - 结果强制只查 1 天数据')
    print('    - 只靠 1 天数据算不出 20 天动量，全是 NaN！')
    print()
    print('  这就是为什么"代码有，能运行，有日志，但结果全是 NaN"')
    print('  典型的"好心办坏事"修复，修了查询问题，废了整个因子计算！')

asyncio.run(diagnose_factor_nan())
