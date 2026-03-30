"""
风险平价 (Risk Parity) 资金分配算法

让每个策略对组合的风险贡献相等，降低整体组合波动率

适用于：
- 多策略组合
- 不同波动率的策略混合
- 降低整体回撤，提高夏普比率

参考：
- 原始论文："Risk Parity" by Edward Qian
- 实现：简化版等风险贡献分配
"""

import numpy as np
from typing import List, Dict, Tuple, Optional
import logging


logger = logging.getLogger(__name__)


def calculate_volatility(returns: List[float]) -> float:
    """计算策略年化波动率"""
    if len(returns) < 2:
        return 0.01  # 默认最小波动率
    
    returns_np = np.array(returns)
    daily_vol = np.std(returns_np)
    
    # 年化波动率 (252交易日)
    annual_vol = daily_vol * np.sqrt(252)
    
    return max(annual_vol, 0.01)  # 避免除以0


def risk_parity_weights(
    strategy_returns: Dict[str, List[float]],
    target_vol: Optional[float] = None,
) -> Dict[str, float]:
    """
    计算风险平价权重
    
    Args:
        strategy_returns: {strategy_name: [daily_return_list]}
        target_vol: 目标组合年化波动率 (如果 None 不杠杆，只做风险平价分配)
    
    Returns:
        {strategy_name: weight} 权重字典，总和 = 1
    """
    # 计算每个策略的波动率
    vols: Dict[str, float] = {}
    for name, returns in strategy_returns.items():
        vol = calculate_volatility(returns)
        vols[name] = vol
    
    # 风险平价 = 权重 = 1 / 波动率
    # 这样风险贡献 = 权重 × 波动率 = (1/vol) × vol = 1 → 相等
    inv_vols = {name: 1.0 / vol for name, vol in vols.items()}
    total_inv_vol = sum(inv_vols.values())
    
    # 归一化权重，总和 = 1
    weights = {name: inv_vol / total_inv_vol for name, inv_vol in inv_vols.items()}
    
    # 如果指定了目标波动率，杠杆调整
    if target_vol is not None:
        # 计算当前组合波动率
        current_vol = 0.0
        for name, w in weights.items():
            current_vol += (w * vols[name]) ** 2
        current_vol = np.sqrt(current_vol)
        
        # 杠杆调整到目标波动率
        leverage = target_vol / current_vol if current_vol > 0 else 1.0
        weights = {name: w * leverage for name, w in weights.items()}
    
    logger.info(
        f"Risk parity weights calculated: {len(weights)} strategies, "
        f"total weights sum = {sum(weights.values()):.2f}"
    )
    
    return weights


def equal_weight_weights(strategy_names: List[str]) -> Dict[str, float]:
    """等权权重 (简单替代风险平价)"""
    n = len(strategy_names)
    if n == 0:
        return {}
    w = 1.0 / n
    return {name: w for name in strategy_names}


def factor_weight_weights(
    strategy_scores: Dict[str, float],
) -> Dict[str, float]:
    """因子加权 (根据夏普/IR打分加权)"""
    total_score = sum(max(score, 0) for score in strategy_scores.values())
    if total_score == 0:
        n = len(strategy_scores)
        return {name: 1.0 / n for name in strategy_scores}
    
    return {name: max(score, 0) / total_score for name, score in strategy_scores.items()}


def mc_simulation_random_weights(
    strategy_names: List[str],
    n_simulations: int = 1000,
) -> List[Dict[str, float]]:
    """蒙特卡洛模拟随机权重，用于寻找最优组合"""
    import random
    results: List[Dict[str, float]] = []
    
    for _ in range(n_simulations):
        # 随机生成权重
        raw_weights = [random.random() for _ in strategy_names]
        total_raw = sum(raw_weights)
        weights = {
            name: raw / total_raw
            for name, raw in zip(strategy_names, raw_weights)
        }
        results.append(weights)
    
    return results


def calculate_portfolio_volatility(
    weights: Dict[str, float],
    cov_matrix: np.ndarray,
) -> float:
    """计算组合波动率"""
    # w^T * cov * w
    w = np.array(list(weights.values()))
    variance = w.T @ cov_matrix @ w
    return np.sqrt(variance)
