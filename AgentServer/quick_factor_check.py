#!/usr/bin/env python3
"""
快速检查因子完整性：模拟回测系统的检查逻辑
"""

import sys
sys.path.insert(0, '.')

from pymongo import MongoClient
import numpy as np

print("🔍 快速检查因子完整性")
print("=" * 60)

def check_factor_integrity():
    """检查因子完整性，模拟回测系统的检查逻辑"""
    
    client = MongoClient('localhost', 27017)
    db = client['stock_agent']
    
    # 回测系统检查的因子列表（从回测代码中提取）
    required_factors = [
        'volume_increase', 'market_leader', 'hot_sector', 'sentiment_score',
        'is_limit_up', 'is_limit_down', 'limit_up_yesterday', 'limit_down_yesterday',
        'first_limit_up', 'first_limit_down', 'limit_up_count', 'limit_down_count',
        'open_above_limit', 'open_above_limit_down', 'pullback_pct', 'pullback_days',
        'pullback_ma5', 'boll_up', 'boll_down', 'boll_width', 'atr', 'atr_pct',
        'rsi_6', 'rsi_12', 'rsi_24', 'macd', 'macd_signal', 'macd_hist',
        'ma5', 'ma10', 'ma20', 'ma60', 'ma5_above_ma10', 'ma10_above_ma20',
        'ma20_above_ma60', 'turnover_rate', 'volume_ratio', 'fear_greed_index',
        'sentiment_period_in', 'sentiment_period_out'
    ]
    
    print(f"需要检查 {len(required_factors)} 个因子")
    print(f"重点关注: volume_increase, market_leader, hot_sector, sentiment_score")
    print()
    
    # 检查的日期
    dates = [20260105, 20260106, 20260107]
    
    missing_factors_by_date = {}
    
    for date in dates:
        print(f"📅 检查日期 {date}...")
        
        # 获取一条记录检查
        sample = db.stock_daily_ak_full.find_one(
            {'trade_date': date},
            {field: 1 for field in required_factors}
        )
        
        if not sample:
            print(f"  ❌ 无数据")
            continue
        
        # 检查每个因子
        missing_factors = []
        for factor in required_factors:
            if factor not in sample:
                missing_factors.append(factor)
            else:
                # 检查值是否有效
                value = sample[factor]
                if value is None:
                    missing_factors.append(f"{factor}(null)")
                elif isinstance(value, float) and (np.isnan(value) or np.isinf(value)):
                    missing_factors.append(f"{factor}(nan/inf)")
        
        if missing_factors:
            missing_factors_by_date[date] = missing_factors
            print(f"  ⚠️  缺失 {len(missing_factors)} 个因子")
            
            # 只显示我们关注的因子
            focus_factors = ['volume_increase', 'market_leader', 'hot_sector', 'sentiment_score']
            missing_focus = [f for f in missing_factors if f.split('(')[0] in focus_factors]
            
            if missing_focus:
                print(f"    重点关注因子缺失: {missing_focus}")
        else:
            print(f"  ✅ 所有因子完整")
        
        # 显示我们关注的因子的值
        print(f"    关注因子值:")
        for factor in ['volume_increase', 'market_leader', 'hot_sector', 'sentiment_score']:
            if factor in sample:
                value = sample[factor]
                status = "✅" if value is not None and not (isinstance(value, float) and (np.isnan(value) or np.isinf(value))) else "❌"
                print(f"      {status} {factor}: {value}")
            else:
                print(f"      ❌ {factor}: 字段不存在")
    
    client.close()
    
    print("\n" + "=" * 60)
    print("📊 检查结果总结")
    
    if missing_factors_by_date:
        print("❌ 发现缺失因子:")
        for date, factors in missing_factors_by_date.items():
            # 过滤出我们关注的因子
            focus_factors = ['volume_increase', 'market_leader', 'hot_sector', 'sentiment_score']
            missing_focus = [f for f in factors if f.split('(')[0] in focus_factors]
            
            if missing_focus:
                print(f"  日期 {date}: {missing_focus}")
    else:
        print("✅ 所有因子完整")
    
    print("\n" + "=" * 60)
    print("🔧 建议:")
    print("1. 如果 volume_increase 仍然缺失，需要检查回测系统的检查逻辑")
    print("2. 如果字段存在但值为null/nan，需要修复字段值")
    print("3. 运行回测验证实际效果")

def check_realtime_status():
    """检查实时状态：回测系统是否还在运行"""
    print("\n" + "=" * 60)
    print("🔍 检查实时状态")
    
    import subprocess
    import os
    
    # 检查是否有回测进程
    result = subprocess.run(['pgrep', '-f', 'backtest\|qk_'], 
                          capture_output=True, text=True)
    
    if result.stdout:
        pids = result.stdout.strip().split()
        print(f"⚠️  有 {len(pids)} 个回测进程在运行: {pids}")
        print("建议先停止这些进程再重新运行回测")
    else:
        print("✅ 无回测进程在运行")
    
    # 检查回测日志文件
    log_files = [
        '/tmp/final_validation_backtest.log',
        '/tmp/final_backtest_validation.log',
        '/tmp/factor_validation.log'
    ]
    
    for log_file in log_files:
        if os.path.exists(log_file):
            size = os.path.getsize(log_file)
            print(f"📄 日志文件 {log_file}: {size:,} 字节")
            
            # 检查最后几行
            try:
                with open(log_file, 'r') as f:
                    lines = f.readlines()[-5:]
                    print(f"  最后5行:")
                    for line in lines:
                        line = line.strip()
                        if line:
                            print(f"    {line[:100]}..." if len(line) > 100 else f"    {line}")
            except:
                pass
        else:
            print(f"📄 日志文件 {log_file}: 不存在")

if __name__ == "__main__":
    check_factor_integrity()
    check_realtime_status()