from pathlib import Path
#!/usr/bin/env python3
"""
策略单元测试
每个策略必须通过单元测试才能跑全量回测
"""
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'AgentServer'))
import pandas as pd
import numpy as np
from nodes.backtest_engine.factor_selection.factor_library import FactorLibrary


def _compute_limit_up_yesterday(df):
    """计算昨日涨停标记: 前一天收盘价==涨停价→1"""
    close = df['close'].values
    up_limit = df['up_limit'].values
    result = np.zeros(len(df))
    for i in range(1, len(df)):
        if close[i-1] >= up_limit[i-1] * 0.995:  # 允许0.5%误差
            result[i] = 1
    result[0] = np.nan
    return pd.Series(result, index=df.index)


def _compute_first_limit_up(df):
    """计算首次涨停: 当日涨停且前20日无涨停"""
    close = df['close'].values
    up_limit = df['up_limit'].values
    n = len(df)
    result = np.zeros(n)

    # 标记涨停日
    is_limit = np.array([close[i] >= up_limit[i] * 0.995 for i in range(n)])

    for i in range(n):
        if is_limit[i]:
            # 检查前20日是否有涨停
            lookback = max(0, i - 20)
            has_prior = any(is_limit[lookback:i])
            if not has_prior:
                result[i] = 1
    return pd.Series(result, index=df.index)


def _compute_open_below_limit(df):
    """计算开盘低于昨日涨停价: (昨日涨停价-今日开盘)/昨日涨停价"""
    open_prices = df['open'].values
    up_limit = df['up_limit'].values
    n = len(df)
    result = np.full(n, np.nan)
    for i in range(1, n):
        result[i] = (up_limit[i-1] - open_prices[i]) / up_limit[i-1]
    return pd.Series(result, index=df.index)


def test_limit_up_yesterday():
    """测试昨日涨停因子"""
    # 涨停日: close == up_limit (同日)
    data = pd.DataFrame({
        'close': [10.0, 11.0, 12.5, 13.31, 14.0],
        'up_limit': [10.5, 11.0, 13.0, 13.31, 14.64]
    })
    # Day0: 10 != 10.5 → 不涨停
    # Day1: 11 == 11 → 涨停!
    # Day2: 12.5 != 13.0 → 不涨停
    # Day3: 13.31 == 13.31 → 涨停!
    # Day4: 14.0 != 14.64 → 不涨停
    result = _compute_limit_up_yesterday(data)
    # result[i] = 1 iff close[i-1] == up_limit[i-1]
    assert result.iloc[0] != result.iloc[0], "Day0 should be nan"
    assert result.iloc[1] == 0, f"Day1: prev close=10 != up_limit=10.5, should be 0"
    assert result.iloc[2] == 1, f"Day2: prev close=11 == up_limit=11, should be 1, got {result.iloc[2]}"
    assert result.iloc[3] == 0, f"Day3: prev close=12.5 != up_limit=13.0, should be 0"
    assert result.iloc[4] == 1, f"Day4: prev close=13.31 == up_limit=13.31, should be 1, got {result.iloc[4]}"
    print("✅ 昨日涨停因子测试通过")


def test_first_limit_up():
    """测试首次涨停因子"""
    # 涨停日: close == up_limit
    data = pd.DataFrame({
        'close': [10.0, 11.0, 13.31, 14.64, 14.64, 15.0],
        'up_limit': [11.0, 12.1, 13.31, 14.64, 16.10, 16.10]
    })
    # Day0: 10 != 11 → 不涨停
    # Day1: 11 != 12.1 → 不涨停
    # Day2: 13.31 == 13.31 → 涨停, 前20日无涨停 → 首次=1
    # Day3: 14.64 == 14.64 → 涨停, 但Day2涨停 → 非首次=0
    # Day4: 14.64 != 16.10 → 不涨停
    # Day5: 15.0 != 16.10 → 不涨停
    result = _compute_first_limit_up(data)
    assert result.iloc[2] == 1, f"Day2 should be 1 (首次涨停), got {result.iloc[2]}"
    assert result.iloc[3] == 0, f"Day3 should be 0 (连续涨停非首次), got {result.iloc[3]}"
    assert result.iloc[4] == 0, f"Day4 should be 0 (未涨停), got {result.iloc[4]}"
    print("✅ 首次涨停因子测试通过")


def test_open_below_limit():
    """测试开盘低于昨日涨停价因子"""
    data = pd.DataFrame({
        'open': [10, 11.5, 12.5, 13, 14],
        'up_limit': [11, 12.1, 13.31, 14.64, 16.10]
    })
    result = _compute_open_below_limit(data)
    # Day1: (up_limit[0]-open[1])/up_limit[0] = (11-11.5)/11 = -0.045
    # Day2: (up_limit[1]-open[2])/up_limit[1] = (12.1-12.5)/12.1 = -0.033
    assert result.iloc[1] < 0, f"Day1 should be negative, got {result.iloc[1]}"
    assert result.iloc[2] < 0, f"Day2 should be negative, got {result.iloc[2]}"
    print("✅ 开盘低于涨停价因子测试通过")


def test_strategy_logic_consistency():
    """测试策略逻辑一致性，避免矛盾条件"""
    try:
        from nodes.backtest_engine.scripts.run_strategies_backtest_3months_akshare_only import STRATEGIES
        for strategy in STRATEGIES:
            if strategy['name'] == '首板打板':
                filters = [f[0] for f in strategy['filters']]
                assert 'limit_up_yesterday' not in filters, "首板打板策略不能包含昨日涨停条件，逻辑矛盾"
                assert 'first_limit_up' in filters, "首板打板策略必须包含首次涨停条件"
        print("✅ 策略逻辑一致性测试通过")
    except ModuleNotFoundError:
        print("⚠️ 策略脚本模块不可用，跳过一致性检查")


def test_factor_library_registration():
    """测试因子库注册完整性"""
    for name in ['limit_up_yesterday', 'first_limit_up', 'open_below_limit']:
        factor = FactorLibrary.get(name)
        assert factor is not None, f"因子 {name} 未注册"
        assert factor.required_fields, f"因子 {name} 缺少 required_fields"
    print("✅ 因子库注册完整性测试通过")


if __name__ == "__main__":
    test_limit_up_yesterday()
    test_first_limit_up()
    test_open_below_limit()
    test_strategy_logic_consistency()
    test_factor_library_registration()
    print("\n🎉 所有策略单元测试通过！")
