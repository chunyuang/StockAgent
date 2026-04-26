
#!/usr/bin/env python3
"""
简单因子测试：直接用pct_chg来选股，验证FactorEngine修复效果
"""

import sys
sys.path.insert(0, './AgentServer')
import asyncio
import json
import time
from datetime import datetime

async def run_factor_test(name, enable_1day_mode=False):
    """运行因子测试"""
    print(f"=" * 80)
    print(f"🚀 开始测试: {name}")
    print(f"=" * 80)
    print()

    from nodes.backtest_engine.factor_selection.factor_engine import FactorEngine
    
    factor_engine = FactorEngine()
    
    # 先初始化MongoDB
    from core.managers import mongo_manager
    await mongo_manager.initialize()
    
    # 获取一些股票
    docs = await mongo_manager.find_many(
        'stock_daily_ak_full',
        {'trade_date': 20260108},
        projection={'ts_code': 1}
    )
    stocks_list = [doc['ts_code'] for doc in docs][:100]  # 前100只
    
    print(f"测试股票数量: {len(stocks_list)}只")
    print(f"测试日期: 20260108")
    print()
    
    # 计算因子配置 - 用需要历史数据的momentum_20d来测试！
    factor_configs = [
        {"name": "momentum_20d", "weight": 1.0, "direction": "desc"},
    ]
    
    start_time = time.time()
    
    try:
        # 设置1天数据模式
        if enable_1day_mode:
            original_load_data = factor_engine._load_all_data
            
            async def patched_load_data(stocks, end_date, factor_defs, lookback_days):
                print(f"  ⚠️  模拟bug模式：强制只查1天数据（lookback_days=0）")
                return await original_load_data(stocks, end_date, factor_defs, 0)
            
            factor_engine._load_all_data = patched_load_data
        
        result = await factor_engine.compute_factors(stocks_list, "20260108", factor_configs, lookback_days=20)
        
        elapsed = time.time() - start_time
        print(f"✅ 因子计算完成！耗时: {elapsed:.2f}秒")
        print()
        
        # 检查因子值
        print(f"📊 因子值分析:")
        nan_count = result['momentum_20d'].isna().sum()
        valid_count = len(result) - nan_count
        print(f"  总股票数: {len(result)}")
        print(f"  有效因子值: {valid_count}只")
        print(f"  NaN数量: {nan_count}只")
        print(f"  因子覆盖率: {valid_count / len(result) * 100:.1f}%")
        print()
        
        if valid_count > 0:
            print(f"  momentum_20d 统计:")
            print(f"    平均值: {result['momentum_20d'].mean():.2f}%")
            print(f"    最大值: {result['momentum_20d'].max():.2f}%")
            print(f"    最小值: {result['momentum_20d'].min():.2f}%")
            print()
            
            # 看排名前5的股票
            top5 = result.sort_values('composite_score', ascending=False).head(5)
            print(f"  综合得分前5名:")
            for _, row in top5.iterrows():
                print(f"    {row['ts_code']}: {row['momentum_20d']:.2f}%")
        
        print()
        
        return {
            "success": True,
            "total_stocks": len(result),
            "valid_factor_count": int(valid_count),
            "nan_count": int(nan_count),
            "coverage": float(valid_count / len(result) * 100),
            "elapsed_time": elapsed,
        }
        
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"❌ 因子计算异常: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}

async def main():
    print("=" * 80)
    print("🧪 FactorEngine修复前后因子计算对比测试")
    print("=" * 80)
    print()
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # 运行修复前测试（模拟1天数据bug模式）
    result_before = await run_factor_test("修复前（模拟只查1天数据模式）", enable_1day_mode=True)
    
    print()
    print()
    
    # 运行修复后测试（正常模式）
    result_after = await run_factor_test("修复后（正常查询历史数据模式）", enable_1day_mode=False)
    
    # 保存结果
    with open('/root/.openclaw/workspace/StockAgent/factor_test_before.json', 'w', encoding='utf-8') as f:
        json.dump(result_before, f, indent=2, ensure_ascii=False)
    
    with open('/root/.openclaw/workspace/StockAgent/factor_test_after.json', 'w', encoding='utf-8') as f:
        json.dump(result_after, f, indent=2, ensure_ascii=False)
    
    print()
    print("=" * 80)
    print("🏆 最终验证结果对比")
    print("=" * 80)
    print()
    
    if result_before and result_after:
        print(f"{'指标':<25} {'修复前':<15} {'修复后':<15} {'变化'}")
        print(f"{'-' * 70}")
        
        for key in ['coverage', 'valid_factor_count', 'nan_count', 'elapsed_time']:
            before = result_before.get(key, 0) or 0
            after = result_after.get(key, 0) or 0
            
            if key == 'coverage':
                before_str = f"{before:.1f}%"
                after_str = f"{after:.1f}%"
                change = f"{after - before:+.1f}%"
            elif key == 'elapsed_time':
                before_str = f"{before:.2f}s"
                after_str = f"{after:.2f}s"
                change = f"{after - before:+.2f}s"
            else:
                before_str = str(before)
                after_str = str(after)
                change = after - before
            
            print(f"{key:<25} {before_str:<15} {after_str:<15} {change}")
    
    print()
    print("=" * 80)
    
    # 关键结论
    print()
    print("🎯 关键结论:")
    if result_after.get('coverage', 0) > 90:
        print("  ✅ 修复成功！因子覆盖率达到90%以上")
    else:
        print("  ❌ 修复后因子覆盖率仍然不足")
    
    if result_before.get('coverage', 0) < result_after.get('coverage', 0):
        print("  ✅ 修复后覆盖率明显提升，修复有效！")
    else:
        print("  ⚠️  修复前后覆盖率没有明显变化")
    
    print()
    print(f"完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(main())
