"""
首板打板

在股票第一次涨停瞬间买入，博弈次日的溢价或连板，属于低风险高胜率的打板入门玩法。

策略规则（来自飞书多维表格）：
- **入场条件**:
  1. 股价首次触及涨停价
  2. 涨停封单量足够（通常大于流通市值的1%）
  3. 所属板块有异动，最好有板块内其他个股助攻
  4. 成交量相较于前几日明显放大，换手充分

- **出场条件**:
  1. 次日高开3%以上可分批止盈
  2. 次日开盘不及预期（低开或平开），冲高无力时止盈
  3. 买入当日炸板无法回封，次日无条件止损

- **仓位管理**:
  单票仓位5%-10%，同时打3-5只首板分散风险，总仓位不超过30%
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
