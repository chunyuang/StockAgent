"""
回撤控制模块

复利的核心在于控制回撤，严格的回撤控制机制：
1. 总最大回撤限制 → 总回撤超过阈值 → 强制停止交易
2. 单日最大亏损限制 → 单日回撤超过 → 当日不再开新仓
3. 连续亏损限制 → 连续 N 笔亏损 → 降低仓位
4. 月度亏损限制 → 月度亏损超过 → 本月剩余时间停止交易
5. 动态仓位调整 → 根据最近回撤调整仓位大小
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from core.settings import settings
from core.managers import mongo_manager


logger = logging.getLogger(__name__)


class DrawdownController:
    """
    回撤控制器
    
    配置:
    - max_total_drawdown_pct: 最大总回撤百分比 (默认 20%)
    - max_daily_drawdown_pct: 单日最大回撤百分比 (默认 5%)
    - max_consecutive_losses: 最大连续亏损次数 (默认 3)
    - max_monthly_drawdown_pct: 月度最大回撤百分比 (默认 10%)
    - cooling_days_after_loss: 亏损后冷却天数 (默认 3)
    """
    
    def __init__(
        self,
        max_total_drawdown_pct: float = 20.0,
        max_daily_drawdown_pct: float = 5.0,
        max_consecutive_losses: int = 3,
        max_monthly_drawdown_pct: float = 10.0,
        cooling_days_after_loss: int = 3,
    ):
        self._max_total_drawdown_pct = max_total_drawdown_pct
        self._max_daily_drawdown_pct = max_daily_drawdown_pct
        self._max_consecutive_losses = max_consecutive_losses
        self._max_monthly_drawdown_pct = max_monthly_drawdown_pct
        self._cooling_days_after_loss = cooling_days_after_loss
        
        # 状态缓存
        self._total_peak_asset: float = 0
        self._current_total_drawdown: float = 0
        self._current_consecutive_losses: int = 0
        self._current_monthly_drawdown: float = 0
        self._last_loss_date: Optional[datetime] = None
    
    async def initialize(self) -> None:
        """初始化，从 MongoDB 加载历史交易计算当前状态"""
        # 获取初始账户峰值
        from ...position_manager import PositionManager
        # 从历史交易计算当前状态
        await self._calculate_current_state()
        logger.info(f"DrawdownController initialized: peak_asset={self._total_peak_asset:.2f}, drawdown={self._current_total_drawdown:.2f}%")
    
    async def _calculate_current_state(self) -> None:
        """从历史交易记录计算当前状态"""
        # 获取所有交易记录，计算净值曲线
        # 简化：根据每日复盘报告计算峰值和回撤
        start_date = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")
        query = {
            "date": {"$gte": start_date},
        }
        reports = await mongo_manager.find_many("daily_reports", query)
        
        if not reports:
            # 没有历史记录，使用初始资金
            self._total_peak_asset = settings.trading.initial_cash
            return
        
        # 找到峰值
        daily_values = sorted(reports, key=lambda x: x["date"])
        max_total = max(r.get("total_asset", 0) for r in daily_values)
        if max_total > 0:
            self._total_peak_asset = max_total
        
        # 计算当前回撤
        latest = daily_values[-1]
        current_total = latest.get("total_asset", self._total_peak_asset)
        if self._total_peak_asset > 0:
            self._current_total_drawdown = (1 - current_total / self._total_peak_asset) * 100
        
        # 计算连续亏损
        # 从最近交易统计
        recent_trades = await self._get_recent_trades(10)
        consecutive = 0
        for trade in reversed(recent_trades):
            if trade.get("profit_amount", 0) < 0:
                consecutive += 1
            else:
                break
        self._current_consecutive_losses = consecutive
        
        # 计算月度回撤
        today = datetime.now()
        first_day = today.replace(day=1)
        monthly_reports = [r for r in reports if r["date"] >= first_day.strftime("%Y%m%d")]
        if monthly_reports:
            monthly_start = monthly_reports[0].get("total_asset", self._total_peak_asset)
            monthly_current = monthly_reports[-1].get("total_asset", monthly_start)
            if monthly_start > 0:
                self._current_monthly_drawdown = (1 - monthly_current / monthly_start) * 100
    
    async def _get_recent_trades(self, days: int) -> List[Dict[str, Any]]:
        """获取最近 N 天交易"""
        from datetime import datetime, timedelta
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
        query = {
            "created_at": {"$gte": start_date},
            "action": "sell",
        }
        result = await mongo_manager.find_many("trading_records", query)
        return list(result)
    
    def can_open_new_position(self, current_daily_profit_pct: float = 0) -> bool:
        """
        检查是否允许开新仓
        
        Args:
            current_daily_profit_pct: 当日当前收益百分比
        
        Returns:
            True 允许开仓，False 不允许
        """
        # 1. 检查单日回撤
        if current_daily_profit_pct <= -self._max_daily_drawdown_pct:
            logger.warning(
                f"[DRAWDOWN] Daily drawdown {current_daily_profit_pct:.2f}% exceeds max {self._max_daily_drawdown_pct:.2f}%, "
                f"stop opening new positions today"
            )
            return False
        
        # 2. 检查连续亏损
        if self._current_consecutive_losses >= self._max_consecutive_losses:
            logger.warning(
                f"[DRAWDOWN] Consecutive losses {self._current_consecutive_losses} exceeds max {self._max_consecutive_losses}, "
                f"stop opening new positions"
            )
            return False
        
        # 3. 检查月度回撤
        if self._current_monthly_drawdown >= self._max_monthly_drawdown_pct:
            logger.warning(
                f"[DRAWDOWN] Monthly drawdown {self._current_monthly_drawdown:.2f}% exceeds max {self._max_monthly_drawdown_pct:.2f}%, "
                f"stop opening new positions this month"
            )
            return False
        
        # 4. 检查总回撤
        if self._current_total_drawdown >= self._max_total_drawdown_pct:
            logger.warning(
                f"[DRAWDOWN] Total drawdown {self._current_total_drawdown:.2f}% exceeds max {self._max_total_drawdown_pct:.2f}%, "
                f"stop opening new positions until new high"
            )
            return False
        
        # 5. 检查冷却期
        if self._last_loss_date is not None:
            days_since_loss = (datetime.now() - self._last_loss_date).days
            if days_since_loss < self._cooling_days_after_loss:
                logger.debug(
                    f"[DRAWDOWN] In cooling period after loss: {days_since_loss}/{self._cooling_days_after_loss} days, "
                    f"skip opening"
                )
                return False
        
        return True
    
    def record_loss(self, is_loss: bool) -> None:
        """记录一次交易结果，更新状态"""
        if is_loss:
            self._current_consecutive_losses += 1
            self._last_loss_date = datetime.now()
        else:
            self._current_consecutive_losses = 0
    
    def update_peak(self, current_total_asset: float) -> None:
        """更新资产峰值，回撤会自动缩小"""
        if current_total_asset > self._total_peak_asset:
            self._total_peak_asset = current_total_asset
            # 更新回撤
            if self._total_peak_asset > 0:
                self._current_total_drawdown = (1 - current_total_asset / self._total_peak_asset) * 100
    
    def get_current_drawdown(self) -> float:
        """获取当前总回撤百分比"""
        return self._current_total_drawdown
    
    def get_position_multiplier(self) -> float:
        """
        获取当前仓位乘数，根据回撤动态调整
        
        回撤越大，仓位越小
        """
        # 线性降低仓位: 回撤 0% → 1.0x, 回撤 20% → 0.0x
        if self._current_total_drawdown >= self._max_total_drawdown_pct:
            return 0.0
        
        multiplier = 1.0 - (self._current_total_drawdown / self._max_total_drawdown_pct)
        
        # 连续亏损额外降低
        if self._current_consecutive_losses > 0:
            multiplier *= (1.0 - self._current_consecutive_losses * 0.2)
        
        return max(0.0, multiplier)
    
    def check_cooling_period(self) -> bool:
        """检查是否在冷却期，不能开仓"""
        if self._last_loss_date is None:
            return False
        
        days_since_loss = (datetime.now() - self._last_loss_date).days
        return days_since_loss < self._cooling_days_after_loss
    
    def monthly_reset(self) -> None:
        """月初重置月度回撤统计"""
        self._current_monthly_drawdown = 0
    
    def update_monthly_drawdown(self, monthly_pct: float) -> None:
        """更新月度回撤"""
        self._current_monthly_drawdown = -monthly_pct


# 全局默认控制器
default_drawdown_controller = DrawdownController()
