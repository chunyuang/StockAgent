
#!/usr/bin/env python3
"""
FactorEngine修复最终验证脚本
运行修复前和修复后的回测，生成对比报告
"""

import sys
sys.path.insert(0, './AgentServer')
import asyncio
import json
import time
from datetime import datetime

async def run_backtest(name, enable_1day_mode=False):
    """运行回测"""
    print(f"=" * 80)
    print(f"🚀 开始回测: {name}")
    print(f"=" * 80)
    print(f"  1天数据模式: {enable_1day_mode}")
    print()

    from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
    
    backtester = PortfolioBacktester()
    
    # 回测配置
    config = {
        "start_date": "20260105",
        "end_date": "20260320",
        "initial_cash": 1000000,
        "selected_strategies": [
            {"id": "leader_buy_dip", "name": "龙头低吸", "params": {}, "weight": 1.0}
        ],
        "factors": [
            {"name": "market_leader", "weight": 1.0}
        ]
    }
    
    start_time = time.time()
    
    # 设置1天数据模式标志（通过猴子补丁实现）
    if enable_1day_mode:
        # 保存原始方法
        original_load_data = backtester.factor_engine._load_all_data
        
        async def patched_load_data(stocks, end_date, factor_defs, lookback_days):
            # 强制只查1天数据，模拟之前的bug
            from datetime import datetime, timedelta
            end_dt = datetime.strptime(end_date, "%Y%m%d")
            start_dt = end_dt  # 只查当天，强制制造NaN！
            return await original_load_data(stocks, end_date, factor_defs, 0)
        
        backtester.factor_engine._load_all_data = patched_load_data
    
    try:
        result = await backtester.run(config)
        
        elapsed = time.time() - start_time
        print(f"✅ 回测完成！耗时: {elapsed:.2f}秒")
        print()
        
        if result and "success" in result:
            print(f"📊 回测结果:")
            for k, v in sorted(result.items()):
                if isinstance(v, (int, float)):
                    print(f"  {k}: {v}")
        else:
            print(f"❌ 回测失败: {result}")
        
        print()
        
        return result, elapsed
        
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"❌ 回测异常: {e}")
        import traceback
        traceback.print_exc()
        return None, elapsed

async def main():
    print("=" * 80)
    print("🧪 FactorEngine修复最终验证")
    print("=" * 80)
    print()
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # 先初始化MongoDB和Redis
    from core.managers import mongo_manager, redis_manager
    print("🔧 初始化MongoDB...")
    await mongo_manager.initialize()
    print("✅ MongoDB初始化完成")
    print()
    
    # 运行修复前回测（模拟1天数据bug模式）
    result_before, time_before = await run_backtest("修复前（模拟只查1天数据模式）", enable_1day_mode=True)
    
    # 运行修复后回测（正常模式）
    result_after, time_after = await run_backtest("修复后（正常查询历史数据模式）", enable_1day_mode=False)
    
    # 保存结果
    with open('/root/.openclaw/workspace/StockAgent/backtest_before.json', 'w', encoding='utf-8') as f:
        json.dump(result_before or {}, f, indent=2, ensure_ascii=False)
    
    with open('/root/.openclaw/workspace/StockAgent/backtest_after.json', 'w', encoding='utf-8') as f:
        json.dump(result_after or {}, f, indent=2, ensure_ascii=False)
    
    print("=" * 80)
    print("🏆 最终验证结果对比")
    print("=" * 80)
    print()
    
    if result_before and result_after:
        print(f"{'指标':<25} {'修复前':<15} {'修复后':<15} {'变化'}")
        print(f"{'-' * 70}")
        
        for key in ['total_return', 'annualized_return', 'max_drawdown', 'sharpe_ratio', 
                    'win_rate', 'profit_loss_ratio', 'total_trades']:
            before = result_before.get(key, 0) or 0
            after = result_after.get(key, 0) or 0
            
            if isinstance(before, float):
                before_str = f"{before:.2f}%" if 'return' in key or 'drawdown' in key or 'rate' in key else f"{before:.2f}"
                after_str = f"{after:.2f}%" if 'return' in key or 'drawdown' in key or 'rate' in key else f"{after:.2f}"
                change = f"{after - before:+.2f}%" if 'return' in key or 'drawdown' in key or 'rate' in key else f"{after - before:+.2f}"
            else:
                before_str = str(before)
                after_str = str(after)
                change = after - before
            
            print(f"{key:<25} {before_str:<15} {after_str:<15} {change}")
        
        print()
        print(f"回测耗时: 修复前 {time_before:.2f}s, 修复后 {time_after:.2f}s")
    
    print()
    print(f"结果文件已保存:")
    print(f"  - backtest_before.json")
    print(f"  - backtest_after.json")
    print()
    print(f"完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(main())
