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
        """获取当日最高连板高度
        
        【V50:从MongoDB limit_list读取真实连板数据,不再用估算】
        """
        try:
            # 尝试从limit_list集合读取(有limit_times字段)
            pipeline = [
                {"$match": {"trade_date": int(trade_date), "is_limit_up": True}},
                {"$group": {"_id": None, "max_limit": {"$max": "$limit_times"}}}
            ]
            result = await mongo_manager.aggregate(C.LIMIT_LIST, pipeline)
            if result and result[0].get("max_limit"):
                return result[0]["max_limit"]
        except Exception as e:
            logger.debug(f"[EMOTION] limit_list聚合失败, fallback估算: {e}")
        
        # Fallback: 根据涨停数量估算(简化版)
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
        """计算昨日涨停今日平均溢价率
        
        【V50:使用交易日历+批量查询,避免N+1问题】
        """
        # 获取前一个交易日
        try:
            prev_trade_date_doc = await mongo_manager.find_one(
                C.STOCK_DAILY,
                {"trade_date": {"$lt": int(trade_date)}},
                sort=[("trade_date", -1)],
                projection={"trade_date": 1},
            )
            if not prev_trade_date_doc:
                return 0.0
            yesterday = str(prev_trade_date_doc["trade_date"])
        except Exception:
            from datetime import timedelta
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
        
        # 【V50:批量查询替代逐只查询,从N+1次DB调用降为2次】
        zt_codes = [doc["ts_code"] for doc in yesterday_zt]
        today_data_list = await mongo_manager.find_many(
            C.STOCK_DAILY,
            {"ts_code": {"$in": zt_codes}, "trade_date": int(trade_date)},
            projection={"ts_code": 1, "close": 1, "pre_close": 1},
        )
        
        # 计算平均溢价
        total_premium = 0.0
        count = 0
        for doc in today_data_list:
            close = doc.get("close", 0)
            pre_close = doc.get("pre_close", 0)
            if close > 0 and pre_close > 0:
                premium = (close - pre_close) / pre_close * 100
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

    # ==================== Phase2.4: 情绪调仓规则 ====================

    # phase降级时的调仓规则
    DOWNGRADE_RULES = {
        # 退潮→混沌: 无需减仓(已在退潮时清过)
        # 分化→退潮: 清仓低利润
        (EmotionPhase.DIFFERENTIATION, EmotionPhase.BEARISH): {
            "action": "clear_low_profit", "min_profit": 0.03,
            "desc": "分化→退潮:清低利润",
        },
        # 上升→分化: 减仓(保留50%仓位)
        (EmotionPhase.RISING, EmotionPhase.DIFFERENTIATION): {
            "action": "reduce", "keep_ratio": 0.5,
            "desc": "上升→分化:减仓50%",
        },
        # 上升→退潮: 清仓低利润(急转直下, 保命优先)
        (EmotionPhase.RISING, EmotionPhase.BEARISH): {
            "action": "clear_low_profit", "min_profit": 0.03,
            "desc": "上升→退潮:清低利润",
        },
        # 混沌→退潮: 清仓低利润
        (EmotionPhase.CHAOS, EmotionPhase.BEARISH): {
            "action": "clear_low_profit", "min_profit": 0.05,
            "desc": "混沌→退潮:清低利润",
        },
        # 分化→混沌: 减仓(保留40%仓位)
        (EmotionPhase.DIFFERENTIATION, EmotionPhase.CHAOS): {
            "action": "reduce", "keep_ratio": 0.4,
            "desc": "分化→混沌:减仓60%",
        },
        # 上升→混沌: 减仓50%(市场转弱, 保留核心仓位)
        (EmotionPhase.RISING, EmotionPhase.CHAOS): {
            "action": "reduce", "keep_ratio": 0.5,
            "desc": "上升→混沌:减仓50%",
        },
    }

    def get_downgrade_rule(self, old_phase: EmotionPhase, new_phase: EmotionPhase) -> Optional[Dict]:
        """获取phase降级调仓规则
        
        Returns:
            {"action": "reduce"|"clear_low_profit", ...} or None(无需调仓)
        """
        return self.DOWNGRADE_RULES.get((old_phase, new_phase))

    @staticmethod
    def build_emotion_sell_list(positions, rule: Dict, old_phase: str, new_phase: str,
                                 is_limit_down_fn=None, pending_sells: Dict = None,
                                 state_lock=None, strategy_risk_fn=None) -> list:
        """根据情绪降级规则构建卖出列表【v2.9.16:从scanner提取】
        
        Args:
            positions: 当前持仓列表
            rule: DOWNGRADE_RULES中的规则
            old_phase: 原始阶段名称
            new_phase: 新阶段名称
            is_limit_down_fn: 判断跌停的回调 fn(ts_code) -> bool
            pending_sells: 跌停挂起卖出字典(可变引用, 直接写入)
            state_lock: 线程锁(保护pending_sells写入)
            strategy_risk_fn: 获取策略风控参数回调 fn(strategy) -> dict
        Returns:
            [(pos, reason, price, risk), ...] 卖出列表
        """
        import time as _time
        to_sell = []
        
        if rule["action"] == "reduce":
            keep_ratio = rule["keep_ratio"]
            sorted_pos = sorted(positions, key=lambda p: p.profit_pct)
            total_count = len(sorted_pos)
            target_count = max(1, int(total_count * keep_ratio))
            sell_count = total_count - target_count
            
            for pos in sorted_pos[:sell_count]:
                if pos.available_qty <= 0:
                    continue
                if is_limit_down_fn and is_limit_down_fn(pos.ts_code):
                    if pending_sells is not None:
                        entry = {"reason": f"情绪降级({old_phase}→{new_phase})", "price": pos.current_price,
                                 "added_at": _time.time(), "source": "emotion"}
                        if state_lock:
                            with state_lock:
                                pending_sells[pos.ts_code] = entry
                        else:
                            pending_sells[pos.ts_code] = entry
                    continue
                risk = strategy_risk_fn(pos.strategy) if strategy_risk_fn else {}
                to_sell.append((pos, f"情绪降级({rule['desc']})", pos.current_price, risk))
        
        elif rule["action"] == "clear_low_profit":
            min_profit = rule.get("min_profit", 0.03)
            for pos in positions:
                if pos.available_qty <= 0:
                    continue
                if pos.profit_pct < min_profit * 100:
                    if is_limit_down_fn and is_limit_down_fn(pos.ts_code):
                        if pending_sells is not None:
                            entry = {"reason": f"情绪清仓({old_phase}→{new_phase})", "price": pos.current_price,
                                     "added_at": _time.time(), "source": "emotion"}
                            if state_lock:
                                with state_lock:
                                    pending_sells[pos.ts_code] = entry
                            else:
                                pending_sells[pos.ts_code] = entry
                        continue
                    risk = strategy_risk_fn(pos.strategy) if strategy_risk_fn else {}
                    to_sell.append((pos, f"情绪清仓({rule['desc']}, 利润{pos.profit_pct:.1f}%<{min_profit*100:.0f}%)",
                                   pos.current_price, risk))
        
        return to_sell


# 全局单例
emotion_cycle_manager = EmotionCycleManager()
