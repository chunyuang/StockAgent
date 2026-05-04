"""
情绪周期管理器

基于每日涨跌停数据、连板高度、涨跌家数计算市场情绪得分，判断情绪周期阶段。

**情绪周期四阶段:**
1.  **上升期/发酵期** ✅ 满仓开仓，所有策略开放
2.  **分化期** ⚠️ 降低仓位，只做最强龙头
3.  **退潮期** ❌ 禁止开仓，强制空仓
4.  **混沌期** ⚠️ 轻仓试错

**情绪得分计算维度:**
- 涨停数量 / 跌停数量
- 连板高度（最高连板数）
- 涨跌家数比
- 昨日涨停今日溢价
- 板块效应强度
"""

from enum import Enum
from typing import Dict, Any, Optional
from dataclasses import dataclass
import logging

from core.constants import C
from core.managers import mongo_manager


logger = logging.getLogger(__name__)


class EmotionPhase(str, Enum):
    """情绪周期阶段"""
    RISING = "rising"          # 上升期/发酵期 - 满仓
    DIFFERENTIATION = "differentiation"  # 分化期 - 降仓
    CHAOS = "chaos"            # 混沌期 - 轻仓
    BEARISH = "bearish"        # 退潮期 - 空仓


@dataclass
class EmotionScore:
    """情绪得分结果"""
    date: str                    # 日期 YYYYMMDD
    score: float                 # 综合得分 0-100
    phase: EmotionPhase          # 情绪阶段
    limit_up_count: int          # 今日涨停数
    limit_down_count: int        # 今日跌停数
    max_continue_limit: int      # 最高连板高度
    up_count: int                # 上涨家数
    down_count: int              # 下跌家数
    up_down_ratio: float         # 涨跌家数比
    ZT_premium: float            # 昨日涨停溢价
    zt_premium: float            # 昨日涨停今日溢价率
    position_multiplier: float  # 仓位乘数 (0.0 - 1.0)
    can_open_position: bool     # 是否允许开仓


class EmotionCycleManager:
    """
    情绪周期管理器
    
    计算每日市场情绪得分，判断情绪周期阶段，提供仓位建议。
    """
    
    # 情绪阶段阈值
    THRESHOLD = {
        "rising": 70,        # >70 上升期
        "differentiation": 50,  # 50-70 分化期
        "chaos": 30,          # 30-50 混沌期
        # <30 退潮期
    }
    
    # 仓位乘数
    POSITION_MULTIPLIER = {
        EmotionPhase.RISING: 1.0,         # 满仓
        EmotionPhase.DIFFERENTIATION: 0.5,  # 半仓
        EmotionPhase.CHAOS: 0.25,        # 1/4仓
        EmotionPhase.BEARISH: 0.0,        # 空仓
    }
    
    # 开仓允许
    CAN_OPEN = {
        EmotionPhase.RISING: True,
        EmotionPhase.DIFFERENTIATION: True,
        EmotionPhase.CHAOS: True,
        EmotionPhase.BEARISH: False,
    }
    
    def __init__(self):
        self._cache: Dict[str, EmotionScore] = {}
    
    async def calculate_daily_emotion(
        self,
        trade_date: str,
        limit_stocks: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> EmotionScore:
        """
        计算当日市场情绪得分
        
        Args:
            trade_date: 交易日 YYYYMMDD
            limit_stocks: 当日涨跌停列表（可选，从 snapshot 获取）
            
        Returns:
            EmotionScore 情绪得分结果
        """
        # 检查缓存
        if trade_date in self._cache:
            return self._cache[trade_date]
        
        # 1. 获取涨跌停数量
        if limit_stocks is not None:
            # 从 snapshot 中统计
            limit_up_count = sum(1 for v in limit_stocks.values() if v.get("limit_type") == "U")
            limit_down_count = sum(1 for v in limit_stocks.values() if v.get("limit_type") == "D")
        else:
            # 从 MongoDB 查询
            query = {"trade_date": int(trade_date), "is_limit_up": True}
            limit_up_count = await mongo_manager.count(C.LIMIT_LIST, query)
            query = {"trade_date": int(trade_date), "is_limit_down": True}
            limit_down_count = await mongo_manager.count(C.LIMIT_LIST, query)
        
        # 2. 获取最高连板高度
        max_continue_limit = await self._get_max_continuation_limit(trade_date, limit_up_count)
        
        # 3. 获取涨跌家数
        up_count, down_count = await self._get_up_down_counts(trade_date)
        if up_count + down_count > 0:
            up_down_ratio = up_count / (up_count + down_count)
        else:
            up_down_ratio = 0.5
        
        # 4. 计算昨日涨停溢价
        zt_premium = await self._calculate_zt_premium(trade_date)
        
        # 5. 综合打分
        score = self._compute_score(
            limit_up_count=limit_up_count,
            limit_down_count=limit_down_count,
            max_continue_limit=max_continue_limit,
            up_down_ratio=up_down_ratio,
            zt_premium=zt_premium,
        )
        
        # 6. 判断情绪阶段
        phase = self._score_to_phase(score)
        
        # 7. 获取仓位建议
        position_multiplier = self.POSITION_MULTIPLIER[phase]
        can_open_position = self.CAN_OPEN[phase]
        
        result = EmotionScore(
            date=trade_date,
            score=score,
            phase=phase,
            limit_up_count=limit_up_count,
            limit_down_count=limit_down_count,
            max_continue_limit=max_continue_limit,
            up_count=up_count,
            down_count=down_count,
            up_down_ratio=up_down_ratio,
            ZT_premium=zt_premium,
            zt_premium=zt_premium,
            position_multiplier=position_multiplier,
            can_open_position=can_open_position,
        )
        
        # 缓存
        self._cache[trade_date] = result
        
        logger.info(
            f"[EMOTION] {trade_date}: score={score:.1f}, phase={phase.value}, "
            f"涨停={limit_up_count}, 跌停={limit_down_count}, "
            f"最高连板={max_continue_limit}, 仓位乘数={position_multiplier:.2f}"
        )
        
        return result
    
    async def _get_max_continuation_limit(self, trade_date: str, limit_up_count: int) -> int:
        """获取当日最高连板高度"""
        # 需要统计每只股票的连续涨停天数
        # 简化版：根据涨停数量估算，最高连板数
        # 完整版本需要每日连板高度表，这里简化处理
        return max(1, min(10, limit_up_count // 5 + 1))
    
    async def _get_up_down_counts(self, trade_date: str) -> tuple[int, int]:
        """获取涨跌家数"""
        # 统计今日涨幅 > 0 的股票数量
        query = {"trade_date": int(trade_date), "pct_chg": {"$gt": 0}}
        up_count = await mongo_manager.count(C.STOCK_DAILY, query)
        query = {"trade_date": int(trade_date), "pct_chg": {"$lt": 0}}
        down_count = await mongo_manager.count(C.STOCK_DAILY, query)
        return up_count, down_count
    
    async def _calculate_zt_premium(self, trade_date: str) -> float:
        """计算昨日涨停今日平均溢价率"""
        # 获取昨日涨停股票今日表现
        from datetime import datetime, timedelta
        
        # 计算昨日
        # 简化：实际应该交易日历，这里简单减一天
        date_obj = datetime(int(trade_date[:4]), int(trade_date[4:6]), int(trade_date[6:8]))
        yesterday = (date_obj - timedelta(days=1)).strftime("%Y%m%d")
        
        # 查询昨日涨停
        yesterday_zt = await mongo_manager.find_many(
            C.LIMIT_LIST,
            {"trade_date": int(yesterday), "is_limit_up": True},
            projection={"ts_code": 1},
        )
        
        if not yesterday_zt:
            return 0.0
        
        # 获取今日收盘价和昨日收盘价
        total_premium = 0.0
        count = 0
        
        for doc in yesterday_zt:
            ts_code = doc["ts_code"]
            today_data = await mongo_manager.find_one(
                C.STOCK_DAILY,
                {"ts_code": ts_code, "trade_date": int(trade_date)},
                projection={"close": 1, "pre_close": 1},
            )
            if today_data and "close" in today_data and "pre_close" in today_data:
                premium = (today_data["close"] - today_data["pre_close"]) / today_data["pre_close"] * 100
                total_premium += premium
                count += 1
        
        if count == 0:
            return 0.0
        
        return total_premium / count
    
    def _compute_score(
        self,
        limit_up_count: int,
        limit_down_count: int,
        max_continue_limit: int,
        up_down_ratio: float,
        zt_premium: float,
    ) -> float:
        """
        计算综合情绪得分
        
        满分 100 分：
        - 涨停数量: 0-30分 (越多越好)
        - 跌停数量: 0-20分 (越少越好)
        - 最高连板: 0-20分 (越高越好)
        - 涨跌家数比: 0-15分 (上涨越多越好)
        - 昨日涨停溢价: 0-15分 (正溢价越好)
        """
        # 1. 涨停数量得分: 50 个以上满分 30
        score_zu = min(30, limit_up_count)
        
        # 2. 跌停数量得分: 0 个跌停满分 20，每个跌停扣 2 分
        score_zd = max(0, 20 - limit_down_count * 2)
        
        # 3. 最高连板得分: 10板满分 20
        score_lb = min(20, max_continue_limit * 2)
        
        # 4. 涨跌家数比得分: 0-15，上涨比例 * 15
        score_ud = int(up_down_ratio * 15)
        
        # 5. 昨日涨停溢价得分: 溢价每1%给1分，满分 15
        score_ym = min(15, max(0, int(zt_premium)))
        
        total = score_zu + score_zd + score_lb + score_ud + score_ym
        
        return min(100, max(0, total))
    
    def _score_to_phase(self, score: float) -> EmotionPhase:
        """得分转情绪阶段"""
        if score >= self.THRESHOLD["rising"]:
            return EmotionPhase.RISING
        elif score >= self.THRESHOLD["differentiation"]:
            return EmotionPhase.DIFFERENTIATION
        elif score >= self.THRESHOLD["chaos"]:
            return EmotionPhase.CHAOS
        else:
            return EmotionPhase.BEARISH
    
    def get_position_multiplier(self, score: float) -> float:
        """根据得分获取仓位乘数"""
        phase = self._score_to_phase(score)
        return self.POSITION_MULTIPLIER[phase]
    
    def can_open_position(self, score: float) -> bool:
        """根据得分判断是否允许开仓"""
        phase = self._score_to_phase(score)
        return self.CAN_OPEN[phase]


# 全局单例
emotion_cycle_manager = EmotionCycleManager()
