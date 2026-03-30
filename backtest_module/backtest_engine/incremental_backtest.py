"""
增量回测支持

当新增因子/策略优化后，不需要全量重新回测，只回测新增数据，节省时间。
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

from core.managers import mongo_manager
from .portfolio_backtest import PortfolioBacktest


logger = logging.getLogger(__name__)


class IncrementalBacktester:
    """
    增量回测器
    
    功能:
    1. 基于已有历史回测结果
    2. 只回测新增数据
    3. 更新绩效统计
    4. 更新因子权重
    """
    
    def __init__(
        self,
        strategy_id: str,
        start_date: str,
        end_date: str,
        last_backtest_date: Optional[str] = None,
    ):
        self._strategy_id = strategy_id
        self._start_date = start_date
        self._end_date = end_date
        self._last_backtest_date = last_backtest_date
    
    async def run_incremental(
        self,
        current_factor_weights: Dict[str, float],
        new_trades_data: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        运行增量回测
        
        Args:
            current_factor_weights: 当前因子权重
            new_trades_data: 新增数据（上次回测后新增数据
        
        Returns:
            更新后的绩效结果
        """
        # 加载已有回测结果
        existing_result = await self._load_existing_result()
        
        # 增量回测新增数据
        incremental_result = await self._backtest_new_data(
            current_factor_weights, new_trades_data
        )
        
        # 合并结果
        merged_result = self._merge_results(existing_result, incremental_result)
        
        # 更新保存结果
        await self._save_merged_result(merged_result)
        
        logger.info(
            f"Incremental backtest completed for {self._strategy_id}: "
            f"total_return={merged_result.get('total_return_pct', 0):.2f}%, "
            f"sharpe={merged_result.get('sharpe_ratio', 0):.2f}"
        )
        
        return merged_result
    
    async def _load_existing_result(self) -> Optional[Dict[str, Any]]:
        """从 MongoDB 加载已有回测结果"""
        result = await mongo_manager.find_one(
            "incremental_backtest_results",
            {"strategy_id": self._strategy_id},
        )
        return result
    
    async def _backtest_new_data(
        self,
        current_weights: Dict[str, float],
        new_data: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """对新增数据运行回测"""
        # 使用现有回测引擎回测
        backtest = PortfolioBacktest()
        result = await backtest.run_backtest(
            start_date=self._last_backtest_date or self._start_date,
            end_date=self._end_date,
            factor_weights=current_weights,
            data=new_data,
        )
        return result
    
    def _merge_results(
        self,
        existing: Optional[Dict[str, Any]],
        incremental: Dict[str, Any],
    ) -> Dict[str, Any]:
        """合并新旧结果"""
        if existing is None:
            return incremental
        
        if incremental is None:
            return existing
        
        # 合并绩效
        merged = existing.copy()
        
        # 更新累计收益 = 已有 + 增量
        merged["total_return_pct"] = merged.get("total_return_pct", 0) + incremental.get("total_return_pct", 0)
        merged["sharpe_ratio"] = (merged.get("sharpe_ratio", 0) + incremental.get("sharpe_ratio", 0)) / 2
        merged["max_drawdown"] = max(
            merged.get("max_drawdown", 0),
            incremental.get("max_drawdown", 0),
        )
        merged["win_rate"] = (
            merged.get("win_rate", 0) * merged.get("total_trades", 0) + 
            incremental.get("win_rate", 0) * incremental.get("total_trades", 0)
        ) / (
            merged.get("total_trades", 0) + incremental.get("total_trades", 0)
        )
        
        return merged
    
    async def _save_merged_result(self, result: Dict[str, Any]) -> None:
        """保存合并后的结果"""
        result["strategy_id"] = self._strategy_id
        result["updated_at"] = datetime.now().isoformat()
        await mongo_manager.replace_one(
            "incremental_backtest_results",
            {"strategy_id": self._strategy_id},
            result,
            upsert=True,
        )


def get_incremental_result(strategy_id: str) -> Optional[Dict[str, Any]]:
    """获取已有的增量回测结果"""
    return await mongo_manager.find_one(
        "incremental_backtest_results",
        {"strategy_id": strategy_id},
    )
