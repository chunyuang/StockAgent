"""
最大夏普比率资金分配 (Maximum Sharpe Ratio)

在给定协方差矩阵和预期收益的情况下，寻找最大化组合夏普比率的权重分配。

公式：
max Sharpe = (w^T * μ - r_f) / sqrt(w^T * Σ * w)

其中：
- w: 权重向量
- μ: 预期收益向量
- Σ: 协方差矩阵
- r_f: 无风险利率
"""

import numpy as np
from typing import List, Dict, Tuple, Optional
import logging


logger = logging.getLogger(__name__)


def max_sharpe_weights(
    expected_returns: Dict[str, float],
    cov_matrix: np.ndarray,
    risk_free_rate: float = 0.03,  # 年化无风险利率 默认 3%
) -> Dict[str, float]:
    """
    计算最大夏普比率权重
    
    Args:
        expected_returns: {strategy_name: expected_return} 预期收益（年化）
        cov_matrix: 协方差矩阵 (n x n)
        risk_free_rate: 年化无风险利率
    
    Returns:
        {strategy_name: weight} 权重字典，总和 = 1
    """
    names = list(expected_returns.keys())
    n = len(names)
    
    if n == 0:
        return {}
    
    mu = np.array([expected_returns[name] for name in names])
    rf = risk_free_rate / 252  # 转化为日度
    
    # 解决最大夏普比率问题
    # 使用公式：w ∝ Σ^{-1} (μ - rf)
    try:
        inv_cov = np.linalg.inv(cov_matrix)
    except np.linalg.LinAlgError:
        # 如果协方差矩阵不可逆，使用伪逆
        inv_cov = np.linalg.pinv(cov_matrix)
    
    # 计算原始权重
    raw_weights = inv_cov @ (mu - rf)
    
    # 归一化到总和 = 1，并且所有权重 >= 0（不允许做空）
    # 移除负权重，重新归一化
    raw_weights = np.maximum(raw_weights, 0.0)
    sum_weights = np.sum(raw_weights)
    
    if sum_weights <= 0:
        # 所有预期收益都小于无风险利率，平均分配
        w = 1.0 / n
        weights = {name: w for name in names}
        logger.warning("All strategies have expected return < risk free rate, using equal weight")
        return weights
    
    # 归一化
    weights = raw_weights / sum_weights
    
    # 转换为字典
    result = {name: float(weight) for name, weight in zip(names, weights)}
    
    # 计算最终夏普比率
    final_sharpe = calculate_portfolio_sharpe(result, expected_returns, cov_matrix, risk_free_rate)
    logger.info(f"Max Sharpe weights calculated: {len(result)} strategies, Sharpe = {final_sharpe:.4f}")
    
    return result


def calculate_portfolio_sharpe(
    weights: Dict[str, float],
    expected_returns: Dict[str, float],
    cov_matrix: np.ndarray,
    risk_free_rate: float,
) -> float:
    """计算组合夏普比率"""
    names = list(weights.keys())
    w = np.array([weights[name] for name in names])
    mu = np.array([expected_returns[name] for name in names])
    
    # 组合预期收益
    portfolio_return = w.T @ mu
    
    # 组合波动率
    portfolio_vol = np.sqrt(w.T @ cov_matrix @ w)
    
    if portfolio_vol == 0:
        return 0.0
    
    # 夏普比率
    sharpe = (portfolio_return - risk_free_rate) / portfolio_vol
    
    return float(sharpe)


def equal_weight_max_sharpe_approx(
    strategy_names: List[str],
    expected_returns: Dict[str, float],
) -> Dict[str, float]:
    """
    近似最大夏普 - 等权
    
    当没有协方差矩阵时，退化为等权
    """
    n = len(strategy_names)
    if n == 0:
        return {}
    w = 1.0 / n
    return {name: w for name in strategy_names}


def get_covariance_matrix(
    historical_returns: Dict[str, List[float]],
) -> Tuple[List[str], np.ndarray]:
    """
    从历史收益计算协方差矩阵
    
    Args:
        historical_returns: {strategy_name: [daily_return_list]}
    
    Returns:
        (names, cov_matrix)
    """
    names = list(historical_returns.keys())
    returns_matrix = np.array([historical_returns[name] for name in names]).T
    
    # 计算协方差
    cov = np.cov(returns_matrix, rowvar=False)
    
    return names, cov
