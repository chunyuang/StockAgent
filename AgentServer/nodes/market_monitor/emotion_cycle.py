"""
情绪周期管理器

基于每日涨跌停数据、连板高度、涨跌家数计算市场情绪得分，判断情绪周期阶段。

【V67:情绪仓位单一来源】所有仓位系数从strategy_defaults.GLOBAL_RISK["sentiment_position_map"]读取。
"""


def _get_position_ratio(period_cn: str) -> float:
    """从strategy_defaults读取仓位系数(单一来源)"""
    from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK
    cn_to_en = {"高潮": "rising", "分化": "differentiation", "震荡": "chaos", "冰点": "bearish"}
    en_key = cn_to_en.get(period_cn, "bearish")
    return GLOBAL_RISK.get("sentiment_position_map", {}).get(en_key, 0.3)

# 情绪周期四阶段:
# 1. 上升期/发酵期: 满仓开仓，所有策略开放
# 2. 分化期: 降低仓位，只做最强龙头
# 3. 退潮期: 禁止开仓，强制空仓
# 4. 混沌期: 轻仓试错
#
# 情绪得分计算维度:
# - 涨停数量 / 跌停数量
# - 连板高度(最高连板数)
# - 涨跌家数比
# - 昨日涨停今日溢价
# - 板块效应强度

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
    
    # 情绪阶段阈值 — 从strategy_defaults读取(单一来源)
    # 旧值: {rising:70, differentiation:50, chaos:30} → 与回测不一致
    # 新值: 从GLOBAL_RISK["sentiment_thresholds"]统一读取
    @property
    def THRESHOLD(self) -> Dict:
        from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK
        return GLOBAL_RISK.get("sentiment_thresholds", {"rising": 70, "differentiation": 55, "chaos": 40})
    
    # 仓位乘数 — 从strategy_defaults读取(单一来源)
    # 旧值: {RISING:1.0, DIFFERENTIATION:0.5, CHAOS:0.25, BEARISH:0.0} → 与回测不一致
    # 新值: 从GLOBAL_RISK["sentiment_position_map"]统一读取
    @property
    def POSITION_MULTIPLIER(self) -> Dict:
        from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK
        m = GLOBAL_RISK.get("sentiment_position_map", {})
        return {
            EmotionPhase.RISING: m.get("rising", 1.0),
            EmotionPhase.DIFFERENTIATION: m.get("differentiation", 0.7),
            EmotionPhase.CHAOS: m.get("chaos", 0.5),
            EmotionPhase.BEARISH: m.get("bearish", 0.3),
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
        """计算当日市场情绪得分(编排方法)"""
        if trade_date in self._cache:
            return self._cache[trade_date]

        # 1-4. 收集情绪因子数据
        factors = await self._collect_emotion_factors(trade_date, limit_stocks)

        # 5. 综合打分
        score = self._compute_score(**factors)

        # 6. 判断情绪阶段
        phase = self._score_to_phase(score)

        # 7. 构建结果
        result = self._build_emotion_score(trade_date, score, phase, factors)
        self._cache[trade_date] = result

        logger.info(
            f"[EMOTION] {trade_date}: score={score:.1f}, phase={phase.value}, "
            f"涨停={factors['limit_up_count']}, 跌停={factors['limit_down_count']}, "
            f"最高连板={factors['max_continue_limit']}, 仓位乘数={result.position_multiplier:.2f}"
        )
        return result

    async def _collect_emotion_factors(
        self, trade_date: str, limit_stocks: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """收集情绪计算所需的5个因子"""
        # 涨跌停数量
        if limit_stocks is not None:
            limit_up_count = sum(1 for v in limit_stocks.values() if v.get("limit_type") == "U")
            limit_down_count = sum(1 for v in limit_stocks.values() if v.get("limit_type") == "D")
        else:
            query = {"trade_date": int(trade_date), "is_limit_up": True}
            limit_up_count = await mongo_manager.count(C.LIMIT_LIST, query)
            query = {"trade_date": int(trade_date), "is_limit_down": True}
            limit_down_count = await mongo_manager.count(C.LIMIT_LIST, query)

        # 最高连板高度
        max_continue_limit = await self._get_max_continuation_limit(trade_date, limit_up_count)

        # 涨跌家数
        up_count, down_count = await self._get_up_down_counts(trade_date)
        up_down_ratio = up_count / (up_count + down_count) if (up_count + down_count) > 0 else 0.5

        # 昨日涨停溢价
        zt_premium = await self._calculate_zt_premium(trade_date)

        return {
            "limit_up_count": limit_up_count,
            "limit_down_count": limit_down_count,
            "max_continue_limit": max_continue_limit,
            "up_down_ratio": up_down_ratio,
            "zt_premium": zt_premium,
            "up_count": up_count,
            "down_count": down_count,
        }

    def _build_emotion_score(
        self, trade_date: str, score: float, phase: EmotionPhase, factors: Dict,
    ) -> EmotionScore:
        """构建EmotionScore结果对象"""
        position_multiplier = self.POSITION_MULTIPLIER[phase]
        can_open_position = self.CAN_OPEN[phase]
        zt_premium = factors["zt_premium"]

        return EmotionScore(
            date=trade_date,
            score=score,
            phase=phase,
            limit_up_count=factors["limit_up_count"],
            limit_down_count=factors["limit_down_count"],
            max_continue_limit=factors["max_continue_limit"],
            up_count=factors["up_count"],
            down_count=factors["down_count"],
            up_down_ratio=factors["up_down_ratio"],
            ZT_premium=zt_premium,
            zt_premium=zt_premium,
            position_multiplier=position_multiplier,
            can_open_position=can_open_position,
        )
    
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
        except Exception as _e:
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

    @staticmethod
    async def handle_emotion_phase_change(scanner, old_phase: str, new_phase: str) -> None:
        """情绪phase变化时的动态调仓【v2.9.6→v2.9.24提取到EmotionCycleManager】
        
        规则来源: EmotionCycleManager.DOWNGRADE_RULES
        执行: phase降级时减仓/清仓低利润, 升级时不做操作
        分批执行: max_per_round=2, 间隔0.5秒(避免冲击)
        
        Args:
            scanner: MarketScanner实例
            old_phase: 原始阶段名称
            new_phase: 新阶段名称
        """
        try:
            old_enum = EmotionPhase(old_phase)
            new_enum = EmotionPhase(new_phase)
        except ValueError:
            logger.info(f"[EMOTION] phase变化 {old_phase}→{new_phase}, 无法识别的阶段")
            return
        
        rule = emotion_cycle_manager.get_downgrade_rule(old_enum, new_enum)
        if not rule:
            logger.info(f"[EMOTION] phase变化 {old_phase}→{new_phase}, 无需调仓")
            return
        
        logger.warning(f"[EMOTION] phase降级 {old_phase}→{new_phase}: {rule['desc']}")
        
        if not scanner._broker:
            return
        
        positions = scanner._broker.get_positions()
        if not positions:
            return
        
        # 委托给_build_emotion_sell_list构建卖出列表
        to_sell = scanner._build_emotion_sell_list(positions, rule, old_phase, new_phase)
        
        if not to_sell:
            logger.info(f"[EMOTION] phase降级无需调仓(无符合条件持仓)")
            return
        
        import asyncio
        batch_size = 2
        from datetime import datetime
        trade_date = scanner._trade_date or datetime.now().strftime("%Y%m%d")
        for i in range(0, len(to_sell), batch_size):
            batch = to_sell[i:i+batch_size]
            if scanner._position_checker:
                await scanner._position_checker.execute_sell_list(batch, trade_date, source="emotion")
            if i + batch_size < len(to_sell):
                await asyncio.sleep(0.5)
        
        logger.warning(f"[EMOTION] 调仓完成: 卖出{len(to_sell)}只, {rule['desc']}")
        
        # 推送事件 + 审计日志
        await scanner._publish_scanner_event("timeline", {
            "item": {
                "time": datetime.now().strftime("%H:%M:%S"),
                "action": "emotion_rebalance",
                "reason": rule['desc'],
                "old_phase": old_phase,
                "new_phase": new_phase,
                "sold_count": len(to_sell),
            }
        })

    @staticmethod
    async def update_sentiment_score(scanner, trade_date: str) -> None:
        """收盘后更新当日情绪预计算(写入sentiment_scores集合)
        
        【v2.9.34从scanner提取】从scanner实时状态或MongoDB获取涨跌停数据,
        计算情绪得分并写入sentiment_scores集合。
        """
        if not mongo_manager.is_initialized:
            return
        db = mongo_manager.db
        td_int = int(trade_date)
        
        # 从scanner实时状态获取涨跌停
        limit_pools = scanner._limit_pools
        lu = len(limit_pools.get("limit_up", []))
        ld = len(limit_pools.get("limit_down", []))
        max_lb = 1
        if limit_pools.get("limit_up"):
            max_lb = max((item.get("limit_times", 1) for item in limit_pools["limit_up"]), default=1)
        
        # 没有实时数据则从limit_list/daily_basic查
        data_source = "scanner_realtime"
        if lu == 0 and ld == 0:
            lu = await db["limit_list"].count_documents({"trade_date": td_int, "limit": "U"})
            ld = await db["limit_list"].count_documents({"trade_date": td_int, "limit": "D"})
            max_lb_doc = await db["limit_list"].find_one(
                {"trade_date": td_int, "limit": "U"},
                sort=[("limit_times", -1)], projection={"limit_times": 1}
            )
            max_lb = max_lb_doc.get("limit_times", 1) if max_lb_doc else 1
            data_source = "limit_list"
        if lu == 0 and ld == 0:
            lu = await db["daily_basic"].count_documents({"trade_date": td_int, "pct_chg": {"$gte": 9.8}})
            ld = await db["daily_basic"].count_documents({"trade_date": td_int, "pct_chg": {"$lte": -9.8}})
            max_lb = 1
            data_source = "daily_basic"
        
        missing_data = (lu == 0 and ld == 0)
        
        # 涨跌家数
        up_count = await db["daily_basic"].count_documents({"trade_date": td_int, "pct_chg": {"$gt": 0}})
        down_count = await db["daily_basic"].count_documents({"trade_date": td_int, "pct_chg": {"$lt": 0}})
        up_down_ratio = up_count / max(up_count + down_count, 1)
        
        # 情绪公式
        score = min(100, max(0, min(30,lu) + max(0,20-ld*2) + min(20,max_lb*2) + int(up_down_ratio*15)))
        if score >= 70: period = "高潮"
        elif score >= 55: period = "分化"
        elif score >= 40: period = "震荡"
        else: period = "冰点"
        
        from datetime import datetime as _dt
        await db["sentiment_scores"].update_one(
            {"trade_date": td_int},
            {"$set": {
                "trade_date": td_int, "score": score, "period": period,
                "position_ratio": _get_position_ratio(period),
                "limit_up": lu, "limit_down": ld, "max_continue": max_lb,
                "up_count": up_count, "down_count": down_count,
                "up_down_ratio": round(up_down_ratio, 3), "zt_premium": 0,
                "data_source": data_source, "missing_data": missing_data,
                "updated_at": _dt.now().isoformat(),
            }},
            upsert=True
        )


# 全局单例
emotion_cycle_manager = EmotionCycleManager()
