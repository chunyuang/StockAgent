
import sys
sys.path.insert(0, './AgentServer')
import asyncio

async def debug_factor_loading():
    print('=' * 80)
    print('🔍 深度调试：为什么因子还是全NaN？')
    print('=' * 80)
    print()
    
    from core.managers import mongo_manager
    await mongo_manager.initialize()
    
    from nodes.backtest_engine.factor_selection.factor_engine import FactorEngine
    from nodes.backtest_engine.factor_selection.universe import UniverseManager, UniverseType
    from nodes.backtest_engine.factor_selection.factor_library import FactorLibrary
    
    universe_mgr = UniverseManager()
    factor_engine = FactorEngine()
    
    test_date = "20260108"
    
    # 只用1只股票调试
    test_code = "000001.SZ"
    stocks_list = [test_code]
    
    print(f'📊 调试参数：')
    print(f'   - 测试日期：{test_date}')
    print(f'   - 测试股票：{test_code}')
    print()
    
    # ======================================================================
    # 调试1：先看MongoDB里这只股票有多少天历史数据
    # ======================================================================
    print('🔍 调试1：检查MongoDB中这只股票的历史数据')
    print('-' * 80)
    
    docs = await mongo_manager.find_many(
        "stock_daily_ak_full",
        {"ts_code": test_code, "trade_date": {"$gte": 20251101, "$lte": 20260108}},
        projection={"trade_date": 1, "close": 1, "_id": 0}
    )
    docs_sorted = sorted(docs, key=lambda x: x['trade_date'])
    print(f'   - MongoDB中 {test_code} 在20251101-20260108期间的记录数：{len(docs_sorted)}条')
    if len(docs_sorted) > 0:
        print(f'   - 日期范围：{docs_sorted[0]["trade_date"]} 到 {docs_sorted[-1]["trade_date"]}')
        print(f'   - 最近3条数据：')
        for d in docs_sorted[-3:]:
            print(f'     * {d["trade_date"]}: close={d.get("close", "N/A")}')
    print()
    
    # ======================================================================
    # 调试2：手动调用_load_all_data，看看实际加载了多少数据
    # ======================================================================
    print('🔍 调试2：检查FactorEngine._load_all_data 实际加载的数据')
    print('-' * 80)
    
    factor_def = FactorLibrary.get("momentum_20d")
    factor_defs = [factor_def]
    
    print(f'   - 因子 {factor_def.name}: lookback_days={factor_def.lookback_days}, data_source={factor_def.data_source}')
    print()
    
    # 调用_load_all_data
    loaded_data = await factor_engine._load_all_data(stocks_list, test_date, factor_defs, 60)
    
    daily_data = loaded_data.get("daily", {})
    print(f'   - 加载了 {len(daily_data)} 只股票的数据')
    if daily_data and test_code in daily_data:
        df = daily_data[test_code]
        print(f'   - {test_code} 的数据天数：{len(df)}天')
        if len(df) > 0:
            print(f'   - 数据日期范围：{df.index.min()} 到 {df.index.max()}')
            print(f'   - 数据列：{list(df.columns)}')
            print(f'   - 最近5天数据：')
            print(df.tail())
    else:
        print(f'   ❌ 没有加载到 {test_code} 的数据！')
    print()
    
    # ======================================================================
    # 调试3：检查日期转换问题
    # ======================================================================
    print('🔍 调试3：检查日期转换问题')
    print('-' * 80)
    
    from datetime import datetime, timedelta
    end_dt = datetime.strptime(test_date, "%Y%m%d")
    max_lookback = factor_def.lookback_days
    start_dt = end_dt - timedelta(days=max_lookback * 2)
    start_date = start_dt.strftime("%Y%m%d")
    
    print(f'   - end_dt={end_dt}, start_dt={start_dt}')
    print(f'   - start_date={start_date}, end_date={test_date}')
    print(f'   - 理论查询天数：{(end_dt - start_dt).days}天')
    print()
    
    # 手动按天查询，看看能不能查到数据
    print('   - 手动按天查询测试：')
    current_dt = start_dt
    found_count = 0
    while current_dt <= end_dt:
        current_date_str = current_dt.strftime("%Y%m%d")
        result_day = await mongo_manager.find_many(
            "stock_daily_ak_full",
            {
                "trade_date": int(current_date_str),
                "ts_code": test_code
            }
        )
        if len(result_day) > 0:
            found_count += 1
            print(f'     ✅ {current_date_str}: 找到 {len(result_day)} 条记录')
        else:
            print(f'     ❌ {current_date_str}: 没有找到记录')
        current_dt += timedelta(days=1)
    
    print(f'   - 总共找到 {found_count} 天有数据')
    print()
    
    # ======================================================================
    # 调试4：检查_compute_single_factor
    # ======================================================================
    print('🔍 调试4：检查 _compute_single_factor')
    print('-' * 80)
    
    if daily_data and test_code in daily_data:
        df = daily_data[test_code]
        print(f'   - 输入DataFrame形状：{df.shape}')
        print(f'   - 输入DataFrame索引：{df.index.tolist() if len(df) < 20 else str(df.index[:10].tolist()) + "..."}')
        print()
        
        # 手动调用compute_func
        try:
            factor_series = factor_def.compute_func(df)
            print(f'   - compute_func返回类型：{type(factor_series)}')
            print(f'   - compute_func返回长度：{len(factor_series)}')
            print(f'   - compute_func返回值：{factor_series.tolist() if len(factor_series) < 20 else factor_series.tail()}')
            print()
            
            # 模拟取指定日期的值
            trade_date_int = int(test_date)
            print(f'   - 要取的日期：{trade_date_int}')
            if trade_date_int in factor_series.index:
                value = factor_series.loc[trade_date_int]
                print(f'   ✅ 找到因子值：{value}')
            elif len(factor_series) > 0:
                value = factor_series.iloc[-1]
                print(f'   ⚠️  指定日期不在索引中，取最后一个值：{value}')
            else:
                print('   ❌ factor_series是空的！')
        except Exception as e:
            print(f'   ❌ compute_func执行报错：{e}')
            import traceback
            traceback.print_exc()

asyncio.run(debug_factor_loading())
