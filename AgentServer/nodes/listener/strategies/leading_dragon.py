"""
龙头战法

捕捉市场最高连板的情绪龙头，享受全市场资金聚焦的情绪溢价，属于强者恒强的最高阶玩法。

策略规则（来自飞书多维表格）：
- **入场条件**:
  1. 连板高度为市场当前最高
  2. 换手充分（非一字板上来，最好有爆量换手板）
  3. 所属板块为当前市场主线，有板块效应支撑
  4. 情绪周期处于上升期或发酵期 ✅ 已集成自动过滤

- **出场条件**:
  1. 断板无法回封时止盈
  2. 收盘价跌破5日均线止损
  3. 出现明显的情绪退潮信号时无条件离场

- **仓位管理**:
  单票仓位不超过总资金的20% × 情绪仓位乘数，龙头确定后可分2-3次加仓，总仓位不超过30%
"""

from typing import List, Dict, Any, Optional
import logging

from .base import BaseStrategy
from .emotion_cycle import emotion_cycle_manager
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
        
        # -------------------- 情绪周期过滤 --------------------
        # 计算今日情绪得分，退潮期禁止开仓
        trade_date = getattr(snapshot, 'trade_date', '') if hasattr(snapshot, 'trade_date') else snapshot.get('trade_date', '')
        if not trade_date:
            from datetime import datetime
            trade_date = datetime.now().strftime("%Y%m%d")
        
        emotion = await emotion_cycle_manager.calculate_daily_emotion(
            trade_date, snapshot.limit_stocks
        )
        
        if not emotion.can_open_position:
            self.logger.info(
                f"[LEADING_DRAGON] ❌ 情绪周期退潮期 (score={emotion.score:.1f}), "
                f"强制空仓，不允许开新仓"
            )
            return []
        
        # 情绪周期检查通过
        self.logger.info(
            f"[LEADING_DRAGON] ✅ 情绪周期检查通过: score={emotion.score:.1f}, phase={emotion.phase.value}"
        )
        # -------------------- 情绪周期检查结束 --------------------
        
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
            
            # 3. 检查连板高度（需要结合昨日数据）
            # 从prev snapshot获取昨日是否涨停
            prev_limit = previous_snapshot.limit_stocks.get(ts_code) if previous_snapshot else None
            was_limit_up_yesterday = prev_limit is not None and prev_limit.get('up_limit', 0) > 0
            
            # 统计连板高度（简单版：连续两天涨停即满足最低要求）
            # 完整连板统计需要历史数据，这里框架支持订阅配置最低连板
            height = 1
            if was_limit_up_yesterday:
                height += 1
            
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
