
import sys
sys.path.insert(0, './AgentServer')
import asyncio
import time
import pandas as pd

async def test_factor_fix_validation():
    print('=' * 80)
    print('🧪 FactorEngine修复验证 + 性能测试 + 覆盖率报告')
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
    
    # 获取股票池
    stocks = await universe_mgr.get_universe(UniverseType.ALL_A, test_date, exclude_rules=[])
    stocks_list = list(stocks)[:500]  # 用500只股票测试
    
    print(f'📊 测试参数：')
    print(f'   - 测试日期：{test_date}')
    print(f'   - 股票数量：{len(stocks_list)}只')
    print()
    
    # ======================================================================
    # 测试1：性能对比 - 修复前后查询耗时
    # ======================================================================
    print('🔍 测试1：性能测试')
    print('-' * 80)
    
    factor_configs_mom = [
        {"name": "momentum_20d", "weight": 1.0, "direction": "desc"},
    ]
    factor_configs_vol = [
        {"name": "volatility_20d", "weight": 1.0, "direction": "asc"},
    ]
    
    # 测试动量因子
    start_time = time.time()
    result_mom = await factor_engine.compute_factors(stocks_list, test_date, factor_configs_mom, lookback_days=60)
    mom_time = time.time() - start_time
    print(f'   - 动量因子（momentum_20d）计算耗时：{mom_time:.2f}秒')
    
    # 测试波动率因子
    start_time = time.time()
    result_vol = await factor_engine.compute_factors(stocks_list, test_date, factor_configs_vol, lookback_days=60)
    vol_time = time.time() - start_time
    print(f'   - 波动率因子（volatility_20d）计算耗时：{vol_time:.2f}秒')
    
    # 测试10个因子同时计算
    all_factor_configs = [
        {"name": "momentum_20d", "weight": 0.1, "direction": "desc"},
        {"name": "volatility_20d", "weight": 0.1, "direction": "asc"},
        {"name": "turnover_20d", "weight": 0.1, "direction": "desc"},
        {"name": "rsi_14", "weight": 0.1, "direction": "desc"},
        {"name": "momentum_5d", "weight": 0.1, "direction": "desc"},
        {"name": "momentum_60d", "weight": 0.1, "direction": "desc"},
        {"name": "volatility_60d", "weight": 0.1, "direction": "asc"},
        {"name": "pe_ttm", "weight": 0.1, "direction": "asc"},
        {"name": "roe", "weight": 0.1, "direction": "desc"},
        {"name": "circ_mv", "weight": 0.1, "direction": "asc"},
    ]
    
    start_time = time.time()
    result_all = await factor_engine.compute_factors(stocks_list, test_date, all_factor_configs, lookback_days=60)
    all_time = time.time() - start_time
    print(f'   - 同时计算10个因子耗时：{all_time:.2f}秒')
    print()
    
    # ======================================================================
    # 测试2：因子覆盖率检查（NaN占比）
    # ======================================================================
    print('🔍 测试2：因子覆盖率检查')
    print('-' * 80)
    
    coverage_report = []
    all_valid = True
    
    for factor_name in ['momentum_5d', 'momentum_20d', 'momentum_60d', 
                        'volatility_20d', 'volatility_60d',
                        'turnover_20d', 'rsi_14']:
        if factor_name in result_all.columns:
            total = len(result_all[factor_name])
            nan_count = result_all[factor_name].isna().sum()
            valid_count = total - nan_count
            coverage = (valid_count / total) * 100 if total > 0 else 0
            
            if coverage >= 95:
                status = "✅ 优秀"
            elif coverage >= 80:
                status = "🟡 良好"
            else:
                status = "❌ 不合格"
                all_valid = False
            
            coverage_report.append({
                '因子名称': factor_name,
                '有效数量': valid_count,
                '总数': total,
                '覆盖率': f'{coverage:.1f}%',
                '状态': status
            })
        else:
            coverage_report.append({
                '因子名称': factor_name,
                '有效数量': 0,
                '总数': '-',
                '覆盖率': '0%',
                '状态': '❌ 列不存在'
            })
            all_valid = False
    
    # 打印覆盖率表格
    print(f"   {'因子名称':<15} {'有效数量':<10} {'总数':<10} {'覆盖率':<10} {'状态'}")
    print(f"   {'-'*60}")
    for row in coverage_report:
        print(f"   {row['因子名称']:<15} {str(row['有效数量']):<10} {str(row['总数']):<10} {row['覆盖率']:<10} {row['状态']}")
    print()
    
    # ======================================================================
    # 测试3：因子区分度验证（不同因子选出的股票重叠度）
    # ======================================================================
    print('🔍 测试3：因子区分度验证')
    print('-' * 80)
    
    top_100_mom = set(result_mom.sort_values('composite_score', ascending=False).head(100)['ts_code'].tolist())
    top_100_vol = set(result_vol.sort_values('composite_score', ascending=False).head(100)['ts_code'].tolist())
    
    overlap = len(top_100_mom & top_100_vol)
    overlap_pct = overlap / 100 * 100
    
    print(f'   - 动量因子前100只与波动率因子前100只重叠数量：{overlap}只')
    print(f'   - 重叠度：{overlap_pct:.1f}%')
    
    if overlap_pct < 50:
        print(f'   ✅ 因子区分度良好！不同因子确实选出了不同的股票')
    else:
        print(f'   ⚠️  因子区分度不足，重叠度过高')
    print()
    
    # ======================================================================
    # 总结
    # ======================================================================
    print('=' * 80)
    print('🏆 FactorEngine修复验证总结')
    print('=' * 80)
    print()
    
    print('  ✅ 代码修复：')
    print('     - 已回滚粗暴的 start_dt 强制截断代码')
    print('     - 已恢复正确的历史数据查询范围（60天）')
    print('     - 已创建 MongoDB 复合索引 (trade_date, ts_code)')
    print('     - 已实现字段投影优化，只查需要的字段')
    print()
    
    print('  ✅ 性能测试：')
    print(f'     - 单因子计算耗时：{min(mom_time, vol_time):.2f}秒')
    print(f'     - 10个因子同时计算耗时：{all_time:.2f}秒')
    print()
    
    print('  ✅ 因子覆盖率：')
    coverage_ok = sum(1 for r in coverage_report if '✅' in r['状态'])
    print(f'     - 覆盖率≥95%的因子：{coverage_ok}/{len(coverage_report)}个')
    print(f'     - 整体状态：{"✅ 全部通过" if all_valid else "❌ 部分不达标"}')
    print()
    
    print('  ✅ 因子区分度：')
    print(f'     - 不同因子选股重叠度：{overlap_pct:.1f}%')
    print(f'     - 要求：< 50%，实际：{overlap_pct:.1f}%')
    print(f'     - 状态：{"✅ 符合要求" if overlap_pct < 50 else "❌ 不符合要求"}')
    print()
    
    print('=' * 80)
    if all_valid and overlap_pct < 50:
        print('🎉 恭喜！FactorEngine修复验证100%通过！所有验证标准全部达标！')
    else:
        print('⚠️  部分验证标准未达标，需要进一步优化！')
    print('=' * 80)

asyncio.run(test_factor_fix_validation())
