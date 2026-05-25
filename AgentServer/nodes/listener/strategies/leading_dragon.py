"""
龙头战法 — ⚠️ 已废弃

此策略已被 MarketScanner 的 dragon_head 策略取代。
Scanner 复用回测的 _build_strategy_filter_conditions，确保实盘与回测对齐。

关键差异(已修复):
- Listener: 仅检查涨停+换手率+连板高度，缺少量比/circ_mv等回测条件
- Scanner: 完整复用回测条件(pct_chg/volume_ratio/circ_mv/max_correction等)

迁移: nodes/market_monitor/scanner.py → _apply_strategies()
废弃时间: 2026-05-26

原始策略规则(仅供参考):
入场: 连板最高+换手充分+板块主线+情绪上升期
出场: 断板止盈/跌破5日线止损/情绪退潮离场
仓位: 单票20%,总仓位30%
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


class LeadingDragonStrategy(BaseStrategy):
    """
    龙头战法
    
    捕捉市场最高连板情绪龙头，博弈情绪溢价。
    需要订阅时配置:
    - limit_up: True 只监控连板涨停股
    - max_height: 要求最低连板高度 (default: 3)
    - min_turnover: 最低换手率百分比 (default: 15)
    """
    
    def __init__(self):
        self.logger = logging.getLogger("strategy.leading_dragon")
    
    @property
    def strategy_type(self) -> str:
        return StrategyType.LEADING_DRAGON.value
    
    async def evaluate(
        self,
        subscription: StrategySubscription,
        snapshot: MarketSnapshot,
        previous_snapshot: Optional[MarketSnapshot] = None,
    ) -> List[StrategyAlert]:
        """
        评估龙头战法入场条件
        
        需要:
        - snapshot 包含涨跌停信息和实时报价
        - previous_snapshot 用于对比
        """
        if not previous_snapshot:
            self.logger.warning("[LEADING_DRAGON] No previous snapshot, skip")
            return []
        
        if not snapshot.limit_stocks:
            self.logger.warning("[LEADING_DRAGON] No limit stocks data in snapshot")
            return []
        
        alerts = []
        params = subscription.params
        min_height = params.get("min_height", 3)
        min_turnover = params.get("min_turnover", 15)
        
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
            
            checked += 1
            
            # 条件判断
            # 1. 当前涨停
            is_limit_up = current_price >= up_limit
            
            # 2. 换手率达标
            sufficient_turnover = turnover >= min_turnover
            
            # 3. 检查连板高度（从limit_stocks数据获取）
            # 【V50:从limit_info读取limit_times(连板数),不再只看2天】
            limit_times = limit_info.get('limit_times', 1)  # 连板高度(默认1=首板)
            height = max(1, limit_times)
            
            if height < min_height:
                continue
            
            # 所有条件满足
            if is_limit_up and sufficient_turnover and height >= min_height:
                stock_name = quote.get("name", ts_code)
                self.logger.info(
                    f"[LEADING_DRAGON] ★ 龙头战法触发: {ts_code} {stock_name}, "
                    f"height={height}, turnover={turnover:.1f}%"
                )
                alert = self._create_alert(
                    subscription=subscription,
                    ts_code=ts_code,
                    stock_name=stock_name,
                    price=current_price,
                    reason=f"市场最高连板龙头，{height}连板，换手率{turnover:.1f}% 换手充分",
                    extra_data={
                        "height": height,
                        "turnover": turnover,
                        "up_limit": up_limit,
                        "pct_chg": quote.get("pct_chg", 0),
                    },
                )
                alerts.append(alert)
        
        self.logger.info(
            f"[LEADING_DRAGON] evaluate done: checked={checked}, alerts={len(alerts)}"
        )
        
        return alerts
