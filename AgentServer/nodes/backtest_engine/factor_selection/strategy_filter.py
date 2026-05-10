"""
策略筛选纯函数 — 无日志、无副作用

从 portfolio_backtest._print_single_strategy_filtering 提取的纯筛选逻辑
回测引擎和实盘信号共用，保证选股一致
"""
import pandas as pd
from typing import List, Dict, Set, Optional


def apply_strategy_filter(
    factor_df: pd.DataFrame,
    conditions: List[Dict],
) -> Set[str]:
    """将策略筛选条件应用到factor_df，返回候选股票集合
    
    Args:
        factor_df: 因子数据DataFrame，必须包含ts_code列
        conditions: 筛选条件列表，每个元素是 {name, target, operator, label}
            - name: 因子列名
            - target: 目标值
            - operator: 比较运算符 (>=, <=, >, <, ==, in)
            - label: 条件描述(仅用于调试)
    
    Returns:
        候选股票的ts_code集合
    """
    if factor_df.empty:
        return set()
    
    current_df = factor_df.copy()
    
    for cond in conditions:
        factor_name = cond.get("name")
        target_value = cond.get("target")
        operator = cond.get("operator", ">=")
        
        if not factor_name or factor_name not in current_df.columns:
            continue
        
        # 因子列全NaN则跳过
        if current_df[factor_name].isna().all():
            continue
        
        try:
            target_float = float(target_value)
            current_df[factor_name] = current_df[factor_name].astype(float)
            target_value = target_float
        except (ValueError, TypeError):
            pass
        
        if operator == ">=":
            current_df = current_df[current_df[factor_name] >= target_value]
        elif operator == "<=":
            current_df = current_df[current_df[factor_name] <= target_value]
        elif operator == ">":
            current_df = current_df[current_df[factor_name] > target_value]
        elif operator == "<":
            current_df = current_df[current_df[factor_name] < target_value]
        elif operator == "==":
            current_df = current_df[current_df[factor_name] == target_value]
        elif operator == "in":
            if isinstance(target_value, list) and len(target_value) == 0:
                continue
            current_df = current_df[current_df[factor_name].isin(target_value)]
        
        if len(current_df) == 0:
            break
    
    return set(current_df["ts_code"].tolist())


def filter_stocks_by_strategies(
    factor_df: pd.DataFrame,
    strategy_configs: Dict[str, List[Dict]],
    allowed_strategies: Optional[List[str]] = None,
) -> Dict[str, Set[str]]:
    """多策略筛选，返回每个策略的候选集
    
    Args:
        factor_df: 因子数据
        strategy_configs: {策略名: 条件列表}
        allowed_strategies: 只筛选这些策略，None则全部
    
    Returns:
        {策略名: 候选ts_code集合}
    """
    results = {}
    for strategy_name, conditions in strategy_configs.items():
        if allowed_strategies and strategy_name not in allowed_strategies:
            continue
        candidates = apply_strategy_filter(factor_df, conditions)
        if candidates:
            results[strategy_name] = candidates
    return results
