"""
策略迭代进化

基于每日交易结果，动态调整因子权重，优化选股模型。

原理:
- 记录每个因子的历史胜率
- 胜率高的因子增加权重
- 胜率低的因子减少权重
- 定期重新计算权重，让策略自动进化
"""

import logging
from datetime import datetime
from typing import List, Dict
from dataclasses import dataclass

from core.managers import mongo_manager


logger = logging.getLogger(__name__)


@dataclass
class FactorStatistics:
    """因子统计"""
    factor_name: str
    total_signals: int = 0
    winning_signals: int = 0
    losing_signals: int = 0
    total_profit: float = 0.0
    win_rate: float = 0.0
    current_weight: float = 0.0
    last_updated: datetime = None


class StrategyEvolution:
    """
    策略迭代进化
    
    功能:
    1. 记录每个因子的每次信号结果（赢/亏）
    2. 定期计算最新胜率
    3. 根据胜率动态调整因子权重
    4. 保存结果到 MongoDB
    5. 回测引擎自动使用最新权重
    """
    
    def __init__(self, strategy_id: str):
        self._strategy_id = strategy_id
        self._stats: Dict[str, FactorStatistics] = {}
        self._loaded = False
    
    async def load_from_db(self) -> None:
        """从 MongoDB 加载历史统计"""
        query = {
            "strategy_id": self._strategy_id,
        }
        result = await mongo_manager.find_one("strategy_evolution", query)
        
        if not result:
            logger.info(f"[EVOLUTION] No existing evolution data for {self._strategy_id}, starting fresh")
            self._loaded = True
            return
        
        # 加载统计
        stats_list = result.get("factors", [])
        for stat in stats_list:
            factor = FactorStatistics(
                factor_name=stat.get("factor_name", ""),
                total_signals=stat.get("total_signals", 0),
                winning_signals=stat.get("winning_signals", 0),
                losing_signals=stat.get("losing_signals", 0),
                total_profit=stat.get("total_profit", 0.0),
                win_rate=stat.get("win_rate", 0.0),
                current_weight=stat.get("current_weight", 0.0),
                last_updated=datetime.fromisoformat(stat.get("last_updated", "")),
            )
            self._stats[factor.factor_name] = factor
        
        self._loaded = True
        logger.info(f"[EVOLUTION] Loaded {len(self._stats)} factor statistics for {self._strategy_id}")
    
    def record_result(
        self,
        factor_name: str,
        is_win: bool,
        profit: float,
        current_weight: float,
    ) -> None:
        """
        记录一次因子信号结果
        
        Args:
            factor_name: 因子名称
            is_win: 是否盈利
            profit: 本次盈利金额
            current_weight: 当前权重
        """
        if factor_name not in self._stats:
            self._stats[factor_name] = FactorStatistics(
                factor_name=factor_name,
                current_weight=current_weight,
            )
        
        stat = self._stats[factor_name]
        stat.total_signals += 1
        stat.total_profit += profit
        if is_win:
            stat.winning_signals += 1
        else:
            stat.losing_signals += 1
        
        # 更新胜率
        if stat.total_signals > 0:
            stat.win_rate = stat.winning_signals / stat.total_signals
        
        stat.last_updated = datetime.now()
        
        logger.debug(
            f"[EVOLUTION] Recorded result for {factor_name}: "
            f"win={is_win}, profit={profit:.2f}, win_rate={stat.win_rate:.2%}"
        )
    
    def update_weights(self) -> Dict[str, float]:
        """
        根据胜率更新因子权重
        
        Returns:
            {factor_name: new_weight}
        """
        if not self._stats:
            logger.warning("[EVOLUTION] No factors to update")
            return {}
        
        # 计算总得分 = sum(win_rate)
        total_win_rate = sum(stat.win_rate for stat in self._stats.values())
        
        if total_win_rate == 0:
            # 还没有交易结果，保持原权重
            logger.warning("[EVOLUTION] Total win rate is zero, keeping original weights")
            return {name: stat.current_weight for name, stat in self._stats.items()}
        
        # 按胜率比例分配权重，总和归一化到 1.0
        new_weights: Dict[str, float] = {}
        for name, stat in self._stats.items():
            new_weight = stat.win_rate / total_win_rate
            new_weights[name] = round(new_weight, 4)
            # 更新统计
            stat.current_weight = new_weight
        
        logger.info(
            f"[EVOLUTION] Weights updated: "
            f"total_win_rate={total_win_rate:.2f}, new_weights={new_weights}"
        )
        
        # 保存到 MongoDB
        self._save_to_db()
        
        return new_weights
    
    def get_current_weights(self) -> Dict[str, float]:
        """获取当前权重"""
        return {name: stat.current_weight for name, stat in self._stats.items()}
    
    def get_statistics(self) -> List[FactorStatistics]:
        """获取所有因子统计"""
        return list(self._stats.values())
    
    async def _save_to_db(self) -> None:
        """保存到 MongoDB"""
        # 转换为可序列化字典
        stats_list = []
        for stat in self._stats.values():
            stats_list.append({
                "factor_name": stat.factor_name,
                "total_signals": stat.total_signals,
                "winning_signals": stat.winning_signals,
                "losing_signals": stat.losing_signals,
                "total_profit": stat.total_profit,
                "win_rate": stat.win_rate,
                "current_weight": stat.current_weight,
                "last_updated": stat.last_updated.isoformat() if stat.last_updated else "",
            })
        
        doc = {
            "strategy_id": self._strategy_id,
            "factors": stats_list,
            "updated_at": datetime.now().isoformat(),
        }
        
        await mongo_manager.replace_one(
            "strategy_evolution",
            {"strategy_id": self._strategy_id},
            doc,
            upsert=True,
        )
        
        logger.debug("[EVOLUTION] Saved to MongoDB")
    
    def get_factor_statistics_table(self) -> str:
        """生成统计表格 markdown"""
        if not self._stats:
            return "*No factor statistics yet*"
        
        lines = [
            "| 因子 | 信号数 | 胜率 | 总盈利 | 当前权重 |",
            "|------|-------:|-----:|-------:|---------:|",
        ]
        
        for name, stat in sorted(self._stats.items(), key=lambda x: -x[1].win_rate):
            lines.append(
                f"| {name} | {stat.total_signals} | {stat.win_rate:.2%} | {stat.total_profit:.2f} | {stat.current_weight:.4f} |"
            )
        
        return "\n".join(lines)


def get_evolution(strategy_id: str) -> StrategyEvolution:
    """获取策略进化实例"""
    evo = StrategyEvolution(strategy_id)
    # 异步加载，需要调用 evo.load_from_db()
    return evo
