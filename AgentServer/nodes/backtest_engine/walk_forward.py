"""
Walk Forward Analysis 滚动窗口回测

避免过度拟合，验证策略有效性:
- 滚动窗口训练
- 样本外测试
- 参数稳定性分析
- 样本内/样本外绩效对比
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple, Optional
import numpy as np

from core.managers import mongo_manager


logger = logging.getLogger(__name__)


class WalkForwardAnalyzer:
    """
    Walk Forward Analysis 滚动窗口回测分析
    
    功能:
    1. 滚动划分训练/测试窗口
    2. 每个窗口训练参数优化
    3. 在测试窗口验证性能
    4. 综合计算整体绩效
    5. 检测参数过拟合程度
    """
    
    def __init__(
        self,
        start_date: str,
        end_date: str,
        window_size: int = 252,  # 训练窗口大小（交易日）
        step_size: int = 21,     # 步长（交易日）
    ):
        self._start_date = start_date
        self._end_date = end_date
        self._window_size = window_size
        self._step_size = step_size
        self._windows: List[Dict[str, str]] = []
        self._generate_windows()
    
    def _generate_windows(self) -> None:
        """生成滚动窗口"""
        # 获取交易日历
        # 简化：按月滚动
        start_dt = datetime.strptime(self._start_date, "%Y%m%d")
        end_dt = datetime.strptime(self._end_date, "%Y%m%d")
        
        current = start_dt
        while current + timedelta(days=self._window_size) <= end_dt:
            train_end = current + timedelta(days=self._window_size)
            test_end = train_end + timedelta(days=self._step_size)
            
            window = {
                "train_start": current.strftime("%Y%m%d"),
                "train_end": train_end.strftime("%Y%m%d"),
                "test_start": (train_end + timedelta(days=1)).strftime("%Y%m%d"),
                "test_end": test_end.strftime("%Y%m%d"),
            }
            self._windows.append(window)
            current = train_end + timedelta(days=1)
        
        logger.info(f"Generated {len(self._windows)} walk-forward windows")
    
    async def run_analysis(
        self,
        backtest_func,
        factor_name: str,
        param_grid: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        运行滚动分析
        
        Args:
            backtest_func: 回测函数，callable( train_start, train_end, test_start, test_end ) -> result
            factor_name: 因子名称
            param_grid: 参数网格搜索列表
        
        Returns:
            分析结果字典
        """
        sample_in_results: List[Dict[str, Any]] = []
        sample_out_results: List[Dict[str, Any]] = []
        
        for window in self._windows:
            train_start = window["train_start"]
            train_end = window["train_end"]
            test_start = window["test_start"]
            test_end = window["test_end"]
            
            logger.info(f"Processing window: {train_start} -> {test_end}")
            
            # 在训练窗口优化参数
            best_params, best_result = await self._optimize_window(
                train_start, train_end, factor_name, param_grid, backtest_func
            )
            
            sample_in_results.append({
                "window": window,
                "best_params": best_params,
                "performance": best_result,
            })
            
            # 在测试窗口验证
            test_result = backtest_func(
                test_start, test_end, factor_name, best_params
            )
            sample_out_results.append({
                "window": window,
                "params": best_params,
                "performance": test_result,
            })
        
        # 汇总结果
        summary = self._summarize_results(sample_in_results, sample_out_results)
        
        # 保存结果到 MongoDB
        await self._save_result(factor_name, summary)
        
        return summary
    
    async def _optimize_grid(
        self,
        train_start: str,
        train_end: str,
        factor_name: str,
        param_grid: List[Dict[str, Any]],
        backtest_func,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """网格搜索最优参数"""
        best_sharpe = -np.inf
        best_params = None
        best_result = None
        
        for params in param_grid:
            # 运行回测
            result = backtest_func(train_start, train_end, factor_name, params)
            
            sharpe = result.get("sharpe_ratio", 0)
            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best_params = params
                best_result = result
        
        return best_params, best_result
    
    def _summarize_results(
        self,
        sample_in_results: List[Dict[str, Any]],
        sample_out_results: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """汇总结果"""
        # 汇总样本内绩效
        sample_in_returns = [r["performance"].get("total_return", 0) for r in sample_in_results]
        sample_in_sharpe = [r["performance"].get("sharpe_ratio", 0) for r in sample_in_results]
        
        # 汇总样本外绩效
        sample_out_returns = [r["performance"].get("total_return", 0) for r in sample_out_results]
        sample_out_sharpe = [r["performance"].get("sharpe_ratio", 0) for r in sample_out_results]
        
        # 计算过拟合程度 = 样本内收益 - 样本外收益
        overfitting_score = np.mean(sample_in_returns) - np.mean(sample_out_returns)
        
        summary = {
            "factor_name": factor_name,
            "num_windows": len(self._windows),
            "sample_in": {
                "mean_return": np.mean(sample_in_returns),
                "mean_sharpe": np.mean(sample_in_sharpe),
                "results": sample_in_results,
            },
            "sample_out": {
                "mean_return": np.mean(sample_out_returns),
                "mean_sharpe": np.mean(sample_out_sharpe),
                "results": sample_out_results,
            },
            "overfitting_score": overfitting_score,
            "timestamp": datetime.now().isoformat(),
        }
        
        logger.info(
            f"WFA completed: overfitting_score={overfitting_score:.4f}, "
            f"sample_out_sharpe={summary['sample_out']['mean_sharpe']:.4f}"
        )
        
        return summary
    
    async def _save_result(
        self,
        factor_name: str,
        summary: Dict[str, Any],
    ) -> None:
        """保存结果到 MongoDB"""
        doc = summary.copy()
        doc["factor_name"] = factor_name
        await mongo_manager.replace_one(
            "walk_forward_analysis",
            {"factor_name": factor_name},
            doc,
            upsert=True,
        )
        logger.info("Result saved to MongoDB")


async def get_wfa_analyzer(factor_name: str) -> Optional[Dict[str, Any]]:
    """从数据库获取已有 WFA 分析结果"""
    return await mongo_manager.find_one(
        "walk_forward_analysis",
        {"factor_name": factor_name},
    )
