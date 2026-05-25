"""
首板打板 — ⚠️ 已废弃

此策略已被 MarketScanner 的 first_limit_up 策略取代。
Scanner 复用回测的 _build_strategy_filter_conditions，确保实盘与回测对齐。

关键差异(已修复):
- Listener: 仅检查触及涨停+换手率+量比，缺少circ_mv/情绪过滤等回测条件
- Scanner: 完整复用回测条件(含circ_mv/情绪/特殊时期过滤)

迁移: nodes/market_monitor/scanner.py → _apply_strategies()
废弃时间: 2026-05-26

原始策略规则(仅供参考):
入场: 首次触及涨停+封单量>=1%流通市值+板块异动+成交量放大
出场: 次日高开3%止盈/不及预期止盈/炸板次日止损
仓位: 单票5-10%,总仓位30%
"""

from typing import List, Optional
import logging

from .base import BaseStrategy
from core.protocols import (
    StrategySubscription,
    StrategyAlert,
    MarketSnapshot,
    StrategyType,
)


class FirstBoardStrategy(BaseStrategy):
    """
    首板打板
    
    在股票首次涨停时买入，博弈次日溢价。
    订阅参数:
    - min_turnover: 最低换手率百分比 (default: 8)
    - min_volume_ratio: 最低成交量相较于5日均量比值 (default: 1.5)
    - require_board_energy: 是否需要封单足够 (default: True)
    """
    
    def __init__(self):
        self.logger = logging.getLogger("strategy.first_board")
    
    @property
    def strategy_type(self) -> str:
        return StrategyType.FIRST_BOARD.value
    
    async def evaluate(
        self,
        subscription: StrategySubscription,
        snapshot: MarketSnapshot,
        previous_snapshot: Optional[MarketSnapshot] = None,
    ) -> List[StrategyAlert]:
        """
        评估首板打板入场条件
        
        逻辑:
        1. 今天第一次涨停（之前没涨停过）
        2. 换手率足够，成交量放量
        3. 当前价格触及涨停价
        """
        if not snapshot.limit_stocks:
            self.logger.warning("[FIRST_BOARD] No limit stocks data in snapshot")
            return []
        
        alerts = []
        params = subscription.params
        min_turnover = params.get("min_turnover", 8)
        min_volume_ratio = params.get("min_volume_ratio", 1.5)
        
        watch_stocks = self._get_watch_stocks(subscription, snapshot)
        checked = 0
        
        for ts_code, quote in watch_stocks.items():
            # 获取涨跌停信息
            limit_info = snapshot.limit_stocks.get(ts_code)
            if not limit_info:
                continue
            
            up_limit = limit_info.get("up_limit", 0)
            current_price = quote.get("price", 0)
            turnover = quote.get("turnover", 0)  # 换手率百分比
            volume = quote.get("volume", 0)
            volume_5d_avg = quote.get("volume_5d_avg", volume)  # 5日平均成交量
            
            checked += 1
            
            # 条件判断
            # 1. 当前价格触及涨停
            is_touching_limit = current_price >= up_limit * 0.99  # 允许1%以内误差
            
            # 2. 换手率达标
            sufficient_turnover = turnover >= min_turnover
            
            # 3. 成交量放量
            volume_ratio = volume / volume_5d_avg if volume_5d_avg > 0 else 2
            sufficient_volume = volume_ratio >= min_volume_ratio
            
            # 所有条件满足
            if is_touching_limit and sufficient_turnover and sufficient_volume:
                stock_name = quote.get("name", ts_code)
                self.logger.info(
                    f"[FIRST_BOARD] ★ 首板打板触发: {ts_code} {stock_name}, "
                    f"turnover={turnover:.1f}%, volume_ratio={volume_ratio:.1f}x"
                )
                alert = self._create_alert(
                    subscription=subscription,
                    ts_code=ts_code,
                    stock_name=stock_name,
                    price=current_price,
                    reason=f"首次涨停，换手率{turnover:.1f}%，成交量{volume_ratio:.1f}倍放量",
                    extra_data={
                        "up_limit": up_limit,
                        "turnover": turnover,
                        "volume_ratio": volume_ratio,
                        "pct_chg": quote.get("pct_chg", 0),
                    },
                )
                alerts.append(alert)
        
        self.logger.info(
            f"[FIRST_BOARD] evaluate done: checked={checked}, alerts={len(alerts)}"
        )
        
        return alerts
