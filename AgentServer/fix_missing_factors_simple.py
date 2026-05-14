#!/usr/bin/env python3
"""
简单修复缺失因子：批量运行因子预计算脚本
"""

import subprocess
import sys
from datetime import datetime

def run_factor_precompute(date_str: str) -> bool:
    """运行因子预计算脚本"""
    cmd = [sys.executable, "scripts/daily_factor_precompute.py", "--date", date_str]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            # 检查输出
            if "更新" in result.stdout:
                # 提取更新数量
                import re
                match = re.search(r'更新(\d+)条因子', result.stdout)
                if match:
                    print(f"  ✅ 更新了 {match.group(1)} 条因子")
                    return True
                else:
                    print(f"  ✅ 已完成")
                    return True
            else:
                print(f"  ℹ️  无更新")
                return True
        else:
            print(f"  ❌ 失败: {result.stderr[:100] if result.stderr else '未知错误'}")
            return False
            
    except subprocess.TimeoutExpired:
        print(f"  ⏱️  超时")
        return False
    except Exception as e:
        print(f"  ❌ 异常: {e}")
        return False

def main():
    """主函数"""
    print("=" * 60)
    print("🔧 缺失因子修复工具 (简单版)")
    print("=" * 60)
    print("修复因子: volume_increase, market_leader, sentiment_score, hot_sector")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # 回测区间：20260105 - 20260320
    # 选取关键日期进行修复（每月取几个样本）
    sample_dates = [
        20260105, 20260106, 20260107, 20260108, 20260109,
        20260112, 20260113, 20260114, 20260115, 20260116,
        20260119, 20260120, 20260121, 20260122, 20260123,
        20260126, 20260127, 20260128, 20260129, 20260130,
        20260202, 20260203, 20260204, 20260205, 20260206,
        20260209, 20260210, 20260211, 20260212, 20260213,
        20260224, 20260225, 20260226, 20260227,
        20260302, 20260303, 20260304, 20260305, 20260306,
        20260309, 20260310, 20260311, 20260312, 20260313,
        20260316, 20260317, 20260318, 20260319, 20260320
    ]
    
    print(f"📅 将修复 {len(sample_dates)} 个交易日的因子数据")
    print("=" * 60)
    
    success_count = 0
    failed_dates = []
    
    for i, date_int in enumerate(sample_dates):
        date_str = str(date_int)
        print(f"\n[{i+1}/{len(sample_dates)}] 处理日期: {date_str}")
        
        if run_factor_precompute(date_str):
            success_count += 1
        else:
            failed_dates.append(date_str)
        
        # 每处理5天输出一次进度
        if (i + 1) % 5 == 0:
            progress = (i + 1) / len(sample_dates) * 100
            print(f"\n📊 进度: {i+1}/{len(sample_dates)} 天 ({progress:.1f}%)")
    
    print("\n" + "=" * 60)
    print("🎉 修复完成！")
    print(f"  总计处理: {len(sample_dates)} 天")
    print(f"  成功修复: {success_count} 天")
    
    if failed_dates:
        print(f"  失败日期: {', '.join(failed_dates[:5])}{'...' if len(failed_dates) > 5 else ''}")
    
    print("\n✅ 现在可以重新运行回测验证。")
    print("=" * 60)
    
    return 0 if success_count > 0 else 1

if __name__ == "__main__":
    sys.exit(main())