#!/usr/bin/env python3
"""
策略单元测试
每个策略必须通过单元测试才能跑全量回测
"""
import sys
sys.path.insert(0, '/root/.openclaw/workspace/StockAgent')
import pandas as pd
import numpy as np
from backtest_module.backtest_engine.factor_selection.factor_library import FactorLibrary

def test_limit_up_yesterday():
    """测试昨日涨停因子"""
    data = pd.DataFrame({
        'close': [10, 11, 12.1, 12.1, 13.31],
        'up_limit': [11, 12.1, 13.31, 13.31, 14.64]
    })
    factor = FactorLibrary.get('limit_up_yesterday')
    result = factor.compute_func(data)
    # 第1天: 无前一天 → 0
    # 第2天: 前一天10→11，涨停 → 0（当日的信号，shift1后第2天是第1天的结果）
    # 第3天: 前一天11→12.1，涨停 → 1（第3天的信号是第2天的涨停）
    # 第4天: 前一天12.1→12.1，未涨停 → 0
    # 第5天: 前一天12.1→12.1，未涨停 → 0
    assert list(result.values) == [np.nan, 0, 1, 0, 0], f"昨日涨停因子计算错误: {result.values}"
    print("✅ 昨日涨停因子测试通过")

def test_first_limit_up():
    """测试首次涨停因子"""
    data = pd.DataFrame({
        'close': [10, 11, 12.1, 13.31, 14.64, 14.64],
        'up_limit': [11, 12.1, 13.31, 14.64, 16.10, 16.10]
    })
    factor = FactorLibrary.get('first_limit_up')
    result = factor.compute_func(data)
    # 第3天: 首次涨停（前20天没有涨停）→ 1
    # 第4天: 连续涨停，不是首次 → 0
    # 第5天: 连续涨停，不是首次 → 0
    # 第6天: 未涨停 → 0
    assert list(result.values[-4:]) == [1, 0, 0, 0], f"首次涨停因子计算错误: {result.values[-4:]}"
    print("✅ 首次涨停因子测试通过")

def test_open_below_limit():
    """测试开盘低于昨日涨停价因子"""
    data = pd.DataFrame({
        'open': [10, 11.5, 12.5, 13, 14],
        'up_limit': [11, 12.1, 13.31, 14.64, 16.10]
    })
    factor = FactorLibrary.get('open_below_limit')
    result = factor.compute_func(data)
    # 第2天: 昨日涨停价11，今日开盘11.5 → (11-11.5)/11 = -0.045
    # 第3天: 昨日涨停价12.1，今日开盘12.5 → (12.1-12.5)/12.1 = -0.033
    assert result.iloc[1] < 0, f"开盘低于涨停价因子计算错误: {result.iloc[1]}"
    print("✅ 开盘低于涨停价因子测试通过")

def test_strategy_logic_consistency():
    """测试策略逻辑一致性，避免矛盾条件"""
    # 首板打板不能同时有limit_up_yesterday条件
    from backtest_module.backtest_engine.scripts.run_strategies_backtest_3months_akshare_only import STRATEGIES
    for strategy in STRATEGIES:
        if strategy['name'] == '首板打板':
            filters = [f[0] for f in strategy['filters']]
            assert 'limit_up_yesterday' not in filters, "首板打板策略不能包含昨日涨停条件，逻辑矛盾"
            assert 'first_limit_up' in filters, "首板打板策略必须包含首次涨停条件"
    print("✅ 策略逻辑一致性测试通过")

if __name__ == "__main__":
    test_limit_up_yesterday()
    test_first_limit_up()
    test_open_below_limit()
    test_strategy_logic_consistency()
    print("\n🎉 所有策略单元测试通过！")
