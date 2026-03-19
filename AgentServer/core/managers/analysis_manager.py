"""
市场情绪周期量化分析引擎 (双评分动态情绪周期系统 V2.1)

优化特性:
- 3日EMA平滑: 核心分经过 3 日 EMA 平滑，消除单日跳变
- 10日EMA基准: 基准值使用 EMA 而非算术平均，更稳定
- 宽松趋势阈值: ±10% 划分走强/走弱，减少频繁切换
- 权重聚焦: 核心因子权重更高，减少小因子噪音
- 真背离过滤: 强弱差 ≥10 分才视为有效背离

评分结构:
- 情绪评分 = EMA平滑核心分(70) + 趋势分(30)
- 强度评分 = EMA平滑核心分(70) + 趋势分(30)
- 周期判定: 冰点/修复/主升/分歧/退潮
"""

import logging
import math
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime

from core.base import BaseManager
from common.enums import MarketCycle


# 周期中文描述 (V2)
CYCLE_DESCRIPTIONS = {
    MarketCycle.ICE_POINT: "冰点期 - 极度悲观，双评分极低，空仓观望",
    MarketCycle.RECOVERY: "修复期 - 情绪回暖，双评分走强，轻仓试错",
    MarketCycle.MAIN_UPWARD: "主升期 - 赚钱效应爆棚，双评分强势，重仓做多",
    MarketCycle.DIVERGENCE: "分歧期 - 评分背离或趋势背离，半仓龙头",
    MarketCycle.DECLINE: "退潮期 - 情绪快速降温，双评分走弱，空仓等待",
    MarketCycle.CHAOS: "混沌期 - 无明确主线，轮动行情，观望为主",
    MarketCycle.UNKNOWN: "未知 - 数据不足，无法判断",
}

# 仓位建议
POSITION_ADVICE = {
    MarketCycle.MAIN_UPWARD: {"level": "重仓", "range": "7~10成", "note": "顺势做多，追强不追弱"},
    MarketCycle.DIVERGENCE: {"level": "半仓", "range": "3~5成", "note": "只做核心龙头，警惕补跌"},
    MarketCycle.DECLINE: {"level": "空仓", "range": "0~1成", "note": "等待企稳，不抄底"},
    MarketCycle.ICE_POINT: {"level": "空仓", "range": "0成", "note": "极小仓试错首板，等待修复"},
    MarketCycle.RECOVERY: {"level": "轻仓", "range": "2~3成", "note": "试错先锋龙，逐步加仓"},
    MarketCycle.CHAOS: {"level": "观望", "range": "1~3成", "note": "轮动行情，快进快出"},
    MarketCycle.UNKNOWN: {"level": "观望", "range": "0~2成", "note": "数据不足，谨慎操作"},
}

# 趋势分档位 (V2.2 收紧版: 弱化温和走强)
TREND_THRESHOLDS = {
    "strong_up": 0.15,    # >= +15% 明显走强
    "mild_up": 0.10,      # >= +10% 温和走强
    "flat": -0.10,        # >= -10% 横盘震荡
    # < -10% 明显走弱
}

TREND_SCORES = {
    "strong_up": 30,      # 明显走强
    "mild_up": 10,        # 温和走强 (原20分，减半)
    "flat": 5,            # 横盘区间 (原15分，弱化)
    "strong_down": 0,     # 明显走弱
}

# 强弱差显示阈值 (V2.3: 提高到15分 + 需要趋势方向相反)
DIVERGENCE_THRESHOLD = 15  # 强弱差 ≥15 分才视为有效背离

# 3日EMA平滑系数 (用于核心分)
EMA_WEIGHTS_3D = {
    "day0": 0.6,  # 今日权重
    "day1": 0.3,  # 昨日权重
    "day2": 0.1,  # 前日权重
}

# 5日EMA平滑系数 (用于最终评分，强平滑)
EMA_WEIGHTS_5D = {
    "day0": 0.30,  # 今日
    "day1": 0.25,  # 昨日
    "day2": 0.20,  # 前日
    "day3": 0.15,  # 大前日
    "day4": 0.10,  # 大大前日
}


class AnalysisManager(BaseManager):
    """
    市场分析管理器 (双评分动态情绪周期系统 V2.1)
    
    V2.1 优化:
    1. 核心分 3 日 EMA 平滑，消除单日脉冲
    2. 10 日 EMA 基准，过滤极端值
    3. 趋势阈值放宽到 ±10%，减少频繁切换
    4. 强弱差 ≥10 分才显示，图表更干净
    5. 因子权重聚焦核心，减少噪音
    """
    
    # MA 周期配置
    MA_PERIOD = 10  # 10日 EMA 基准
    
    # 默认基准值 (当历史数据不足时使用)
    DEFAULT_AVG_AMOUNT = 10000 * 1e8  # 1万亿（千元单位）
    DEFAULT_AVG_LIMIT_UP = 80         # 80家涨停
    
    def __init__(self):
        super().__init__()
        self._ma_cache = {}  # 缓存 MA 数据，key 为 trade_date
    
    @staticmethod
    def _safe_float(val, default: float = 0.0) -> float:
        """安全转换为浮点数"""
        if val is None:
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default
    
    async def initialize(self) -> None:
        """初始化"""
        self._initialized = True
        self.logger.info(f"AnalysisManager initialized (MA{self.MA_PERIOD} dynamic baseline V2)")
    
    async def shutdown(self) -> None:
        """关闭"""
        self._initialized = False
        self._ma_cache.clear()
        self.logger.info("AnalysisManager shutdown")
    
    async def health_check(self) -> bool:
        """健康检查"""
        return self._initialized
    
    async def load_ma10_baseline(
        self,
        trade_date: str,
        mongo_manager,
    ) -> Dict[str, Any]:
        """
        加载 MA10 动态基准值 (V2)
        
        从 MongoDB 加载最近 10 个交易日的历史统计数据，计算各项指标均值
        
        Args:
            trade_date: 当前交易日 (不包含在计算中，使用之前10天)
            mongo_manager: MongoDB 管理器实例
        
        Returns:
            包含 MA10 基准值的字典 (情绪评分因子 + 强度评分因子)
        """
        cache_key = f"ma10_{trade_date}"
        if cache_key in self._ma_cache:
            return self._ma_cache[cache_key]
        
        # 从 MongoDB 加载最近 MA_PERIOD 个交易日的数据
        history_data = await mongo_manager.find_many(
            "daily_stats",
            {"trade_date": {"$lt": trade_date}},
            projection={
                "trade_date": 1,
                # 情绪评分因子
                "max_limit_height": 1,
                "limit_up_count": 1,
                "seal_rate": 1,
                "cont_board_count": 1,
                "promotion_rate": 1,
                "limit_down_count": 1,
                # 强度评分因子
                "total_amount": 1,
                "up_ratio": 1,
                "pct_chg_median": 1,
                "up_5pct_count": 1,
                "down_5pct_count": 1,
                "index_pct_chg": 1,
                "_id": 0,
            },
            sort=[("trade_date", -1)],
            limit=self.MA_PERIOD,
        )
        
        data_count = len(history_data) if history_data else 0
        
        def calc_avg(field: str) -> Optional[float]:
            """计算字段均值"""
            if not history_data:
                return None
            values = [self._safe_float(d.get(field)) for d in history_data if d.get(field) is not None]
            return sum(values) / len(values) if values else None
        
        baseline = {
            "data_count": data_count,
            
            # === 情绪评分因子均值 ===
            "avg_max_height": calc_avg("max_limit_height"),
            "avg_limit_up": calc_avg("limit_up_count"),
            "avg_seal_rate": calc_avg("seal_rate"),
            "avg_cont_board": calc_avg("cont_board_count"),
            "avg_promo_rate": calc_avg("promotion_rate"),
            "avg_limit_down": calc_avg("limit_down_count"),
            
            # === 强度评分因子均值 ===
            "avg_amount": calc_avg("total_amount"),
            "avg_up_ratio": calc_avg("up_ratio"),
            "avg_pct_median": calc_avg("pct_chg_median"),
            "avg_index_chg": calc_avg("index_pct_chg"),
        }
        
        # 计算涨跌5%比均值
        if history_data:
            ratios = []
            for d in history_data:
                up5 = self._safe_float(d.get("up_5pct_count"))
                down5 = self._safe_float(d.get("down_5pct_count"))
                if down5 > 0:
                    ratios.append(up5 / down5)
                elif up5 > 0:
                    ratios.append(up5)  # 无跌超5%时，使用涨超5%数量
            baseline["avg_up5_down5_ratio"] = sum(ratios) / len(ratios) if ratios else None
        else:
            baseline["avg_up5_down5_ratio"] = None
        
        if data_count >= 5:
            self.logger.debug(
                f"MA{self.MA_PERIOD} baseline loaded ({data_count} days)"
            )
        else:
            self.logger.info(f"MA{self.MA_PERIOD} baseline: only {data_count} days available")
        
        self._ma_cache[cache_key] = baseline
        return baseline
    
    async def load_ma30_baseline(
        self,
        trade_date: str,
        mongo_manager,
    ) -> Dict[str, float]:
        """兼容旧接口: 加载 MA30 基准 (内部调用 MA10)"""
        baseline = await self.load_ma10_baseline(trade_date, mongo_manager)
        return {
            "avg_amount_30d": baseline.get("avg_amount"),
            "avg_limit_up_30d": baseline.get("avg_limit_up"),
            "avg_limit_down_30d": baseline.get("avg_limit_down"),
            "data_count": baseline.get("data_count", 0),
        }
    
    async def load_recent_v_ratios(
        self,
        trade_date: str,
        mongo_manager,
        days: int = 3,
    ) -> List[float]:
        """
        加载最近 N 天的量能偏离比 (v_ratio)
        
        用于判断趋势（如连续下降）
        
        Returns:
            v_ratio 列表，按日期从新到旧排序
        """
        history = await mongo_manager.find_many(
            "market_analysis",
            {"trade_date": {"$lt": trade_date}},
            projection={"trade_date": 1, "v_ratio": 1, "_id": 0},
            sort=[("trade_date", -1)],
            limit=days,
        )
        
        return [self._safe_float(d.get("v_ratio", 1.0)) for d in history if d.get("v_ratio")]
    
    async def load_prev_sentiment(
        self,
        trade_date: str,
        mongo_manager,
    ) -> Optional[float]:
        """
        加载前一天的情绪评分（用于 EMA 平滑）
        
        Returns:
            前一天的 sentiment_score_ema，如果没有则返回 None
        """
        prev = await mongo_manager.find_one(
            "market_analysis",
            {"trade_date": {"$lt": trade_date}},
            projection={"sentiment_score_ema": 1, "sentiment_score": 1, "_id": 0},
            sort=[("trade_date", -1)],
        )
        
        if prev:
            # 优先使用 EMA 值，如果没有则用原始值
            return self._safe_float(
                prev.get("sentiment_score_ema") or prev.get("sentiment_score"),
                default=None
            )
        return None
    
    def apply_ema_smoothing(
        self,
        current_score: float,
        prev_ema: Optional[float],
        alpha: float = 0.8,
    ) -> float:
        """
        应用 EMA 平滑
        
        公式: EMA = current * alpha + prev_ema * (1 - alpha)
        """
        if prev_ema is None:
            return current_score
        return round(current_score * alpha + prev_ema * (1 - alpha), 2)
    
    # ==================== V2 双评分系统 ====================
    
    def _calc_relative_score(
        self,
        current: float,
        avg: Optional[float],
        max_score: float,
        inverse: bool = False,
    ) -> float:
        """
        计算相对强度得分
        
        公式: 相对强度 = 当日值 / MA均值
        得分 = 相对强度 * max_score (上限为 max_score)
        
        Args:
            current: 当日值
            avg: MA均值
            max_score: 该因子满分
            inverse: 是否反向（如跌停，越少得分越高）
        """
        if avg is None or avg <= 0:
            return max_score * 0.5  # 无基准时给 50%
        
        if inverse:
            # 反向: avg / current
            ratio = avg / current if current > 0 else 2.0
        else:
            ratio = current / avg
        
        score = ratio * max_score
        return min(max_score, max(0, score))
    
    def calculate_sentiment_core_v2(
        self,
        stats: Dict[str, Any],
        baseline: Dict[str, Any],
    ) -> Tuple[float, Dict[str, float]]:
        """
        计算情绪评分核心动态分 (70分) - V2.2 超短核心版
        
        核心改动:
        1. 绝对阈值约束: 连板高度≤2板 → 高度因子0分
        2. 权重向超短倾斜: 连板高度+晋级率 = 50分
        3. 双重计分: min(相对分, 绝对分)
        4. 高标跌停重罚
        
        因子权重:
        - 连板高度 (绝对+相对) → 25分
        - 昨日连板晋级率 (绝对+相对) → 25分
        - 连板家数(2板+) → 10分
        - 封板率 → 5分
        - 跌停惩罚 → 15分 (反向)
        
        Returns:
            (core_score, detail_dict)
        """
        # 提取当日数据
        max_height = self._safe_float(stats.get("max_limit_height"))
        limit_up = self._safe_float(stats.get("limit_up_count"))
        seal_rate = self._safe_float(stats.get("seal_rate"))
        cont_board = self._safe_float(stats.get("cont_board_count"))
        promo_rate = self._safe_float(stats.get("promotion_rate"))
        limit_down = self._safe_float(stats.get("limit_down_count"))
        
        # 提取MA基准
        avg_height = baseline.get("avg_max_height")
        avg_cont_board = baseline.get("avg_cont_board")
        avg_promo_rate = baseline.get("avg_promo_rate")
        avg_seal_rate = baseline.get("avg_seal_rate")
        avg_limit_down = baseline.get("avg_limit_down")
        
        detail = {}
        
        # === 1. 连板高度 (25分) - 超短核心锚 ===
        # 绝对阈值: ≤2板=0分, ≥5板=满分
        height_abs = self._calc_absolute_score(
            max_height, {"low": 2, "high": 5}, 25
        )
        # 相对强度
        height_rel = self._calc_relative_score(max_height, avg_height, 25)
        # 取较小值
        detail["height_score"] = min(height_abs, height_rel)
        
        # === 2. 昨日连板晋级率 (25分) - 接力质量 ===
        # 绝对阈值: ≤30%=0分, ≥60%=满分 (promo_rate 是百分比 0-100)
        if promo_rate is not None:
            promo_abs = self._calc_absolute_score(
                promo_rate, {"low": 30, "high": 60}, 25
            )
            promo_rel = self._calc_relative_score(promo_rate, avg_promo_rate, 25)
            detail["promo_rate_score"] = min(promo_abs, promo_rel)
        else:
            detail["promo_rate_score"] = 12.5  # 无数据给50%
        
        # === 3. 连板家数 2板+ (10分) ===
        # 绝对阈值: ≤3家=0分, ≥10家=满分
        cont_abs = self._calc_absolute_score(
            cont_board, {"low": 3, "high": 10}, 10
        )
        cont_rel = self._calc_relative_score(cont_board, avg_cont_board, 10)
        detail["cont_board_score"] = min(cont_abs, cont_rel)
        
        # === 4. 封板率 (5分) ===
        detail["seal_rate_score"] = self._calc_relative_score(seal_rate, avg_seal_rate, 5)
        
        # === 5. 跌停惩罚 (15分反向) ===
        # 跌停越多，得分越低
        detail["limit_down_score"] = self._calc_relative_score(
            limit_down, avg_limit_down, 15, inverse=True
        )
        
        # 汇总核心分
        core_score = sum(detail.values())
        
        # === 绝对底仓约束 ===
        # 连板高度≤2板 → 核心分封顶40
        if max_height <= 2:
            core_score = min(core_score, 40)
            detail["cap_reason"] = "height<=2"
        # 晋级率≤30% → 额外扣10分
        elif promo_rate is not None and promo_rate <= 30:
            core_score = max(0, core_score - 10)
            detail["penalty"] = "promo<=30%"
        
        core_score = min(70, max(0, core_score))
        
        return round(core_score, 2), detail
    
    def _calc_absolute_score(
        self,
        value: float,
        thresholds: Dict[str, float],
        max_score: float,
    ) -> float:
        """
        计算绝对阈值得分 (线性插值)
        
        thresholds: {"low": 0.3, "high": 0.6} 表示 <30%=0分, >60%=满分, 中间线性
        """
        low = thresholds.get("low", 0)
        high = thresholds.get("high", 1)
        
        if value <= low:
            return 0
        elif value >= high:
            return max_score
        else:
            return max_score * (value - low) / (high - low)
    
    def calculate_strength_core_v2(
        self,
        stats: Dict[str, Any],
        baseline: Dict[str, Any],
    ) -> Tuple[float, Dict[str, float]]:
        """
        计算市场强度评分核心动态分 (70分) - V2.2 亏钱效应优先版
        
        核心改动:
        1. 绝对阈值约束: 上涨家数≤30% → 核心分封顶40分
        2. 权重重构: 亏钱效应因子 > 量能因子
        3. 双重计分: min(相对分, 绝对分)，避免熊市误判
        
        因子权重:
        - 上涨家数占比 (绝对+相对) → 20分
        - 涨幅中位数 (绝对+相对) → 20分
        - 成交额相对强度 → 15分
        - 涨5%/跌5%家数比 → 15分 (反向计分)
        
        Returns:
            (core_score, detail_dict)
        """
        # 提取当日数据
        total_amount = self._safe_float(stats.get("total_amount"))
        up_ratio = self._safe_float(stats.get("up_ratio"))  # 0-1
        pct_median = self._safe_float(stats.get("pct_chg_median"))  # 百分比
        up_5pct = self._safe_float(stats.get("up_5pct_count"))
        down_5pct = self._safe_float(stats.get("down_5pct_count"))
        index_chg = self._safe_float(stats.get("index_pct_chg"))
        
        # 提取MA基准
        avg_amount = baseline.get("avg_amount")
        avg_up_ratio = baseline.get("avg_up_ratio")
        avg_pct_median = baseline.get("avg_pct_median")
        avg_up5_down5_ratio = baseline.get("avg_up5_down5_ratio")
        
        detail = {}
        
        # === 1. 上涨家数占比 (20分) - 绝对+相对双重约束 ===
        # 绝对阈值: <30%=0分, >60%=满分
        up_ratio_abs = self._calc_absolute_score(
            up_ratio, {"low": 0.30, "high": 0.60}, 20
        )
        # 相对强度
        up_ratio_rel = self._calc_relative_score(up_ratio, avg_up_ratio, 20)
        # 取较小值，避免熊市误判
        detail["up_ratio_score"] = min(up_ratio_abs, up_ratio_rel)
        
        # === 2. 涨幅中位数 (20分) - 绝对+相对双重约束 ===
        # 绝对阈值: <=-0.5%=0分, >=1%=满分 (pct_median 单位是百分比)
        median_abs = self._calc_absolute_score(
            pct_median, {"low": -0.5, "high": 1.0}, 20
        )
        # 相对强度 (处理正负)
        if avg_pct_median is not None and avg_pct_median != 0:
            if avg_pct_median > 0:
                ratio = pct_median / avg_pct_median if pct_median >= 0 else 0
            else:
                ratio = avg_pct_median / pct_median if pct_median < 0 else 2.0
            median_rel = min(20, max(0, ratio * 20))
        else:
            median_rel = 10.0
        # 取较小值
        detail["median_score"] = min(median_abs, median_rel)
        
        # === 3. 成交额相对强度 (15分) - 降权 ===
        detail["amount_score"] = self._calc_relative_score(total_amount, avg_amount, 15)
        
        # === 4. 涨5%/跌5%家数比 (15分) - 亏钱效应核心 ===
        if down_5pct > 0:
            current_ratio = up_5pct / down_5pct
        elif up_5pct > 0:
            current_ratio = up_5pct
        else:
            current_ratio = 1.0
        # 绝对阈值: <0.5=0分, >2=满分
        up5_abs = self._calc_absolute_score(
            current_ratio, {"low": 0.5, "high": 2.0}, 15
        )
        up5_rel = self._calc_relative_score(current_ratio, avg_up5_down5_ratio, 15)
        detail["up5_down5_score"] = min(up5_abs, up5_rel)
        
        # 汇总核心分
        core_score = sum(detail.values())
        
        # === 绝对底仓约束 ===
        # 上涨家数≤30% (4000+下跌) → 核心分封顶40
        if up_ratio <= 0.30:
            core_score = min(core_score, 40)
            detail["cap_reason"] = "up_ratio<=30%"
        # 中位数跌幅严重 → 额外扣分
        elif pct_median <= -0.5:
            core_score = max(0, core_score - 10)
            detail["penalty"] = "median<=-0.5%"
        
        core_score = min(70, max(0, core_score))
        
        return round(core_score, 2), detail
    
    def calculate_trend_score(
        self,
        today_core: float,
        prev_core: Optional[float],
    ) -> Tuple[float, str]:
        """
        计算趋势分 (30分) - V2.1 宽松版
        
        公式:
        趋势比例 = (今日平滑核心分 - 前日平滑核心分) / 前日平滑核心分
        
        分档 (宽松阈值 ±10%):
        - >= +10% (明显走强) → 30分, trend="up"
        - >= 0%   (温和走强) → 20分, trend="up"
        - >= -10% (横盘区间) → 15分, trend="flat"
        - < -10%  (明显走弱) → 0分,  trend="down"
        
        Returns:
            (trend_score, trend_direction)
        """
        if prev_core is None or prev_core <= 0:
            return 15, "flat"
        
        trend_ratio = (today_core - prev_core) / prev_core
        
        if trend_ratio >= TREND_THRESHOLDS["strong_up"]:
            return TREND_SCORES["strong_up"], "up"
        elif trend_ratio >= TREND_THRESHOLDS["mild_up"]:
            return TREND_SCORES["mild_up"], "up"
        elif trend_ratio >= TREND_THRESHOLDS["flat"]:
            return TREND_SCORES["flat"], "flat"
        else:
            return TREND_SCORES["strong_down"], "down"
    
    def apply_3day_ema(
        self,
        today: float,
        day1: Optional[float],
        day2: Optional[float],
    ) -> float:
        """
        应用 3 日 EMA 平滑 (用于核心分)
        
        公式: 平滑值 = 0.6 * 今日 + 0.3 * 昨日 + 0.1 * 前日
        """
        w0 = EMA_WEIGHTS_3D["day0"]
        w1 = EMA_WEIGHTS_3D["day1"]
        w2 = EMA_WEIGHTS_3D["day2"]
        
        total_weight = w0
        smoothed = today * w0
        
        if day1 is not None:
            smoothed += day1 * w1
            total_weight += w1
        
        if day2 is not None:
            smoothed += day2 * w2
            total_weight += w2
        
        return round(smoothed / total_weight * (w0 + w1 + w2), 2)
    
    def apply_5day_ema(
        self,
        scores: List[Optional[float]],
    ) -> float:
        """
        应用 5 日 EMA 强平滑 (用于最终评分)
        
        公式: 0.30*今日 + 0.25*昨日 + 0.20*前日 + 0.15*大前日 + 0.10*大大前日
        
        Args:
            scores: [今日, 昨日, 前日, 大前日, 大大前日] 按时间从新到旧
        """
        weights = [
            EMA_WEIGHTS_5D["day0"],
            EMA_WEIGHTS_5D["day1"],
            EMA_WEIGHTS_5D["day2"],
            EMA_WEIGHTS_5D["day3"],
            EMA_WEIGHTS_5D["day4"],
        ]
        
        total_weight = 0
        smoothed = 0
        
        for i, score in enumerate(scores):
            if score is not None and i < len(weights):
                smoothed += score * weights[i]
                total_weight += weights[i]
        
        if total_weight == 0:
            return scores[0] if scores and scores[0] is not None else 0
        
        return round(smoothed / total_weight * sum(weights), 2)
    
    def identify_3day_trend(
        self,
        today: float,
        day1: Optional[float],
        day2: Optional[float],
    ) -> str:
        """
        判定 3 日趋势方向
        
        - 连续3天递增 → "up"
        - 连续3天递减 → "down"
        - 其他 → "flat"
        """
        if day1 is None or day2 is None:
            return "flat"
        
        if today > day1 > day2:
            return "up"
        elif today < day1 < day2:
            return "down"
        else:
            return "flat"
    
    def identify_cycle_by_trends(
        self,
        sentiment_trend: str,
        strength_trend: str,
        sentiment_score: float,
        strength_score: float,
    ) -> Tuple[MarketCycle, str]:
        """
        基于双趋势组合判定周期 (V2.3 区间化版本)
        
        | 情绪趋势 | 强度趋势 | 周期 |
        |---------|---------|------|
        | up      | up      | 主升期 |
        | up      | down    | 分歧期 |
        | down    | up      | 分歧期 |
        | down    | down    | 退潮期 |
        | flat    | flat    | 混沌期 |
        | (双低+止跌) | -    | 修复期 |
        
        Returns:
            (MarketCycle, reason)
        """
        # 冰点期: 双分都极低
        if sentiment_score < 20 and strength_score < 20:
            return MarketCycle.ICE_POINT, "双分极低(<20)"
        
        # 修复期: 双低但有止跌迹象
        if sentiment_score < 40 and strength_score < 40:
            if sentiment_trend == "up" or strength_trend == "up":
                return MarketCycle.RECOVERY, "双低(<40)但有止跌"
        
        # 主升期: 双趋势向上
        if sentiment_trend == "up" and strength_trend == "up":
            return MarketCycle.MAIN_UPWARD, "双趋势向上"
        
        # 退潮期: 双趋势向下
        if sentiment_trend == "down" and strength_trend == "down":
            return MarketCycle.DECLINE, "双趋势向下"
        
        # 分歧期: 趋势方向相反
        if sentiment_trend != strength_trend and sentiment_trend != "flat" and strength_trend != "flat":
            return MarketCycle.DIVERGENCE, f"趋势背离(情绪{sentiment_trend}/强度{strength_trend})"
        
        # 混沌期: 其他情况
        return MarketCycle.CHAOS, "趋势不明确"
    
    async def load_prev_core_scores(
        self,
        trade_date: str,
        mongo_manager,
    ) -> Tuple[Optional[float], Optional[float]]:
        """
        加载前一天的核心动态分 (兼容旧接口)
        
        Returns:
            (prev_sentiment_core, prev_strength_core)
        """
        history = await self.load_recent_core_scores(trade_date, mongo_manager, days=1)
        if history:
            return history[0]
        return None, None
    
    async def load_recent_core_scores(
        self,
        trade_date: str,
        mongo_manager,
        days: int = 3,
    ) -> List[Tuple[Optional[float], Optional[float]]]:
        """
        加载近 N 天的核心动态分 (用于 EMA 平滑)
        
        Returns:
            [(sent_core, stren_core), ...] 按日期从新到旧排序
        """
        history = await mongo_manager.find_many(
            "market_analysis",
            {"trade_date": {"$lt": trade_date}},
            projection={
                "trade_date": 1,
                "sentiment_core_score": 1,
                "strength_core_score": 1,
                # V2.1 新增: 平滑后的核心分
                "sentiment_core_ema": 1,
                "strength_core_ema": 1,
                "_id": 0,
            },
            sort=[("trade_date", -1)],
            limit=days,
        )
        
        result = []
        for item in history:
            # 优先使用已平滑的值
            sent = self._safe_float(
                item.get("sentiment_core_ema") or item.get("sentiment_core_score"),
                default=None
            )
            stren = self._safe_float(
                item.get("strength_core_ema") or item.get("strength_core_score"),
                default=None
            )
            result.append((sent, stren))
        
        return result
    
    def identify_cycle_v2(
        self,
        sentiment_score: float,
        strength_score: float,
        sentiment_trend: str,
        strength_trend: str,
    ) -> Tuple[MarketCycle, str]:
        """
        新周期判定逻辑 (V2)
        
        基于双评分高低 + 趋势方向判断周期
        
        周期定义:
        - 冰点: 情绪<20 且 强度<20 且 双走弱/横盘
        - 修复: 20≤情绪<40 且 20≤强度<40 且 双走强
        - 主升: 情绪≥60 且 强度≥60 且 双走强/横盘
        - 分歧: 一者≥60 另一者<60 或 双强但趋势背离
        - 退潮: 情绪<40 且 强度<40 且 双走弱
        - 混沌: 其他情况
        """
        sent = sentiment_score
        stren = strength_score
        s_trend = sentiment_trend
        st_trend = strength_trend
        
        # 1. 冰点期: 双低 + 非走强
        if sent < 20 and stren < 20:
            if s_trend != "up" and st_trend != "up":
                return MarketCycle.ICE_POINT, f"双评分极低(情绪{sent:.0f},强度{stren:.0f})，市场冰点"
        
        # 2. 修复期: 双低~中 + 双走强
        if 20 <= sent < 40 and 20 <= stren < 40:
            if s_trend == "up" and st_trend == "up":
                return MarketCycle.RECOVERY, f"双评分回暖(情绪{sent:.0f},强度{stren:.0f})，双趋势走强，修复萌芽"
        
        # 3. 主升期: 双高 + 非走弱
        if sent >= 60 and stren >= 60:
            if s_trend != "down" and st_trend != "down":
                return MarketCycle.MAIN_UPWARD, f"双评分强势(情绪{sent:.0f},强度{stren:.0f})，主升行情"
        
        # 4. 分歧期: 评分背离 或 趋势背离
        # 4a. 评分背离: 一高一低
        if (sent >= 60 and stren < 60) or (stren >= 60 and sent < 60):
            return MarketCycle.DIVERGENCE, f"评分背离(情绪{sent:.0f},强度{stren:.0f})，高低分化"
        
        # 4b. 趋势背离: 双高但趋势不一致
        if sent >= 50 and stren >= 50:
            if (s_trend == "up" and st_trend == "down") or (s_trend == "down" and st_trend == "up"):
                return MarketCycle.DIVERGENCE, f"趋势背离(情绪{s_trend},强度{st_trend})，警惕分化"
        
        # 5. 退潮期: 双低 + 双走弱
        if sent < 40 and stren < 40:
            if s_trend == "down" and st_trend == "down":
                return MarketCycle.DECLINE, f"双评分走弱(情绪{sent:.0f},强度{stren:.0f})，退潮中"
        
        # 6. 混沌期: 其他情况
        return MarketCycle.CHAOS, f"无明确周期(情绪{sent:.0f},强度{stren:.0f})，轮动观望"
    
    def get_position_advice(self, cycle: MarketCycle) -> Dict[str, str]:
        """获取仓位建议"""
        return POSITION_ADVICE.get(cycle, POSITION_ADVICE[MarketCycle.UNKNOWN])
    
    def calculate_scores_with_baseline(
        self, 
        stats: Dict[str, Any],
        baseline: Dict[str, float],
    ) -> Tuple[float, float, float]:
        """
        基于 MA30 动态基准计算情绪评分和市场强度评分
        
        Args:
            stats: 每日统计数据字典
            baseline: MA30 基准值字典
        
        Returns:
            (sentiment_score, strength_score, v_ratio) 元组
        """
        # 提取数据
        up_ratio = self._safe_float(stats.get("up_ratio"))
        max_height = self._safe_float(stats.get("max_limit_height"))
        limit_up = self._safe_float(stats.get("limit_up_count"))
        broken = self._safe_float(stats.get("broken_limit_count"))
        limit_down = self._safe_float(stats.get("limit_down_count"))
        total_limit_up = self._safe_float(stats.get("total_limit_up"))
        limit_1 = self._safe_float(stats.get("limit_1"))
        total_amount = self._safe_float(stats.get("total_amount"))  # 千元
        north_money = self._safe_float(stats.get("north_money"))    # 百万元
        
        # 提取 MA30 基准 (None 表示无历史数据，使用当日数据作为基准)
        avg_amount = baseline.get("avg_amount_30d")
        avg_limit_up = baseline.get("avg_limit_up_30d")
        avg_limit_down = baseline.get("avg_limit_down_30d")
        
        # 如果没有历史基准，使用当日数据作为基准 (ratio = 1.0)
        if avg_amount is None or avg_amount <= 0:
            avg_amount = total_amount if total_amount > 0 else 1.0
        if avg_limit_up is None or avg_limit_up <= 0:
            avg_limit_up = limit_up if limit_up > 0 else 1.0
        if avg_limit_down is None or avg_limit_down <= 0:
            avg_limit_down = limit_down if limit_down > 0 else 1.0
        
        # ==================== 市场强度评分 (Strength Score) ====================
        # 引入"量能效率"概念: Strength = Volume_Score * DirectionFactor
        # 放量杀跌时强度分应回落至 50-60 分区间
        
        v_ratio = total_amount / avg_amount if avg_amount > 0 else 1.0
        
        # 1. 量能得分 (Volume_Score): 基于 v_ratio 的对数映射，防止极端值
        # v_ratio=0.5 -> 35分, v_ratio=1.0 -> 65分, v_ratio=1.5 -> 80分, v_ratio=2.0 -> 95分
        if v_ratio > 0:
            volume_score = 65 + 30 * math.log2(v_ratio)  # 对数映射
        else:
            volume_score = 30
        volume_score = max(20, min(95, volume_score))  # 限制在 20-95 范围
        
        # 2. 方向因子 (DirectionFactor): 当 up_ratio < 45% 时线性减小
        # up_ratio=45% -> factor=1.0 (无惩罚)
        # up_ratio=30% -> factor=0.8 (打8折)
        # up_ratio=15% -> factor=0.6 (打6折)
        # up_ratio=0%  -> factor=0.5 (打5折，最低)
        if up_ratio < 45:
            # 线性减小: factor = 0.5 + (up_ratio / 45) * 0.5
            direction_factor = 0.5 + (up_ratio / 45) * 0.5
        elif up_ratio > 60:
            # 上涨行情轻微加成: 最高 1.15
            direction_factor = min(1.15, 1 + (up_ratio - 60) * 0.004)
        else:
            direction_factor = 1.0
        
        # 3. 计算最终强度分 = Volume_Score * DirectionFactor
        strength_score = volume_score * direction_factor
        
        # 4. 北向资金加成/惩罚 (±8分)
        north_in_yi = north_money / 100  # 百万元 -> 亿元
        if north_in_yi > 50:
            strength_score += min(8, north_in_yi / 50 * 4)
        elif north_in_yi < -50:
            strength_score -= min(8, abs(north_in_yi) / 50 * 4)
        
        # 限制范围
        strength_score = max(0, min(100, strength_score))
        
        self.logger.debug(
            f"Strength calc: v_ratio={v_ratio:.2f}, vol_score={volume_score:.1f}, "
            f"up_ratio={up_ratio:.1f}%, dir_factor={direction_factor:.2f}, final={strength_score:.1f}"
        )
        
        # ==================== 情绪评分 (Sentiment Score) ====================
        # 基于 MA30 动态对比
        
        # 1. 普涨率因子 (0-20分)
        r_up_score = min(20, up_ratio * 0.4)  # 50% 普涨率 = 20分
        
        # 2. 高度分 (0-25分，8板满分)
        h_score = min(25, max_height * 3.125)
        
        # 3. 封板率 (0-20分)
        if limit_up + broken > 0:
            success_rate = limit_up / (limit_up + broken)
        else:
            success_rate = 0
        success_score = success_rate * 20
        
        # 4. 涨停家数对比 MA30 (0-25分)
        # limit_up_ratio = current_limit_up / avg_limit_up_30d
        if avg_limit_up > 0:
            limit_up_ratio = limit_up / avg_limit_up
        else:
            limit_up_ratio = 1.0
        # 1.0 倍 = 12.5分，2.0 倍 = 25分，0.5 倍 = 6.25分
        limit_up_score = min(25, limit_up_ratio * 12.5)
        
        # 5. 跌停惩罚 (动态基准)
        # 跌停数超过平均涨停数的 20% 时开始重罚
        down_threshold = avg_limit_up * 0.2
        if down_threshold > 0 and limit_down > down_threshold:
            down_penalty = (limit_down - down_threshold) / down_threshold * 15
            down_penalty = min(30, down_penalty)  # 最多扣 30 分
        else:
            down_penalty = 0
        
        # 6. 接力率加分 (0-10分)
        if total_limit_up > 0:
            promo_rate = (total_limit_up - limit_1) / total_limit_up
        else:
            promo_rate = 0
        promo_score = promo_rate * 10
        
        # 计算情绪分
        sentiment_score = r_up_score + h_score + success_score + limit_up_score + promo_score - down_penalty
        sentiment_score = max(0, min(100, sentiment_score))
        
        self.logger.debug(
            f"Scores (MA30): sentiment={sentiment_score:.1f}, strength={strength_score:.1f}, v_ratio={v_ratio:.2f} | "
            f"r_up={r_up_score:.1f}, h={h_score:.1f}, success={success_score:.1f}, "
            f"limit_up_score={limit_up_score:.1f}, promo={promo_score:.1f}, down_penalty={down_penalty:.1f}"
        )
        
        return round(sentiment_score, 2), round(strength_score, 2), round(v_ratio, 3)
    
    async def identify_cycle_with_baseline(
        self,
        stats: Dict[str, Any],
        prev_stats: Optional[Dict[str, Any]],
        baseline: Dict[str, float],
        recent_v_ratios: List[float],
        v_ratio: float,
    ) -> Tuple[MarketCycle, str]:
        """
        基于 MA30 动态基准判定市场周期
        
        Args:
            stats: 当日统计数据
            prev_stats: 昨日统计数据
            baseline: MA30 基准值
            recent_v_ratios: 最近几天的 v_ratio 列表
            v_ratio: 当日量能偏离比
        
        Returns:
            (cycle_enum, reason) 元组
        """
        # 提取当日数据
        max_height = self._safe_float(stats.get("max_limit_height"))
        limit_down = self._safe_float(stats.get("limit_down_count"))
        broken = self._safe_float(stats.get("broken_limit_count"))
        limit_up = self._safe_float(stats.get("limit_up_count"))
        total_amount = self._safe_float(stats.get("total_amount"))
        
        # 提取 MA 基准 (None 表示无历史数据，使用当日数据作为基准)
        avg_limit_up = baseline.get("avg_limit_up_30d")
        avg_limit_down = baseline.get("avg_limit_down_30d")
        
        # 如果没有历史基准，使用当日数据作为基准
        if avg_limit_up is None or avg_limit_up <= 0:
            avg_limit_up = limit_up if limit_up > 0 else 1.0
        if avg_limit_down is None or avg_limit_down <= 0:
            avg_limit_down = limit_down if limit_down > 0 else 1.0
        
        # 计算评分
        sentiment, strength, _ = self.calculate_scores_with_baseline(stats, baseline)
        
        # 封板率
        if limit_up + broken > 0:
            success_rate = limit_up / (limit_up + broken) * 100
        else:
            success_rate = 0
        
        # 炸板率
        if limit_up > 0:
            broken_rate = broken / limit_up * 100
        else:
            broken_rate = 0
        
        # 成交额 (亿元)
        amount_yi = total_amount / 1e8
        
        # 昨日数据
        prev_height = 0.0
        prev_amount = 0.0
        if prev_stats:
            prev_height = self._safe_float(prev_stats.get("max_limit_height"))
            prev_amount = self._safe_float(prev_stats.get("total_amount"))
        
        # 判断 v_ratio 趋势
        v_ratio_declining = False
        if len(recent_v_ratios) >= 2:
            # 检查是否连续 2 日下降
            if recent_v_ratios[0] < recent_v_ratios[1] and v_ratio < recent_v_ratios[0]:
                v_ratio_declining = True
        
        # v_ratio 低位回升判断
        v_ratio_rebounding = False
        if len(recent_v_ratios) >= 1:
            prev_v = recent_v_ratios[0]
            if prev_v < 0.8 and v_ratio > prev_v:
                v_ratio_rebounding = True
        
        # ==================== 周期判定逻辑 (按优先级) ====================
        
        # 1. 冰点期: 高度 <= 2 且 情绪分 < 30 且 跌停超过均值 2 倍
        if max_height <= 2 and sentiment < 30 and limit_down > avg_limit_down * 2:
            return MarketCycle.ICE_POINT, f"高度仅{max_height}板，情绪{sentiment:.0f}分，跌停{limit_down}家(>{avg_limit_down*2:.0f})"
        
        # 2. 退潮期: v_ratio 连续 2 日下降且跌停超过均值 2 倍
        if v_ratio_declining and limit_down > avg_limit_down * 2:
            return MarketCycle.DECLINE, f"量能连续萎缩(v_ratio={v_ratio:.2f})，跌停{limit_down}家激增"
        
        # 2b. 退潮期: 高度大幅回落
        if prev_height >= 4 and max_height < prev_height - 2:
            return MarketCycle.DECLINE, f"高度从{prev_height}板回落至{max_height}板，高标补跌"
        
        # 2c. 退潮期: 跌停激增
        if limit_down > avg_limit_down * 3:
            return MarketCycle.DECLINE, f"跌停{limit_down}家(均值{avg_limit_down:.0f}的3倍)，市场情绪快速降温"
        
        # 3. 主升期: 高度 >= 5 且 v_ratio > 1.2 且 封板率 > 80%
        if max_height >= 5 and v_ratio > 1.2 and success_rate > 80:
            return MarketCycle.MAIN_UPWARD, f"高度{max_height}板，量能{v_ratio:.2f}倍均值，封板率{success_rate:.0f}%"
        
        # 4. 分歧/轮动期: 高度高但炸板率 > 25% 或 封板率 < 60%
        if max_height >= 4 and (broken_rate > 25 or success_rate < 60):
            return MarketCycle.ROTATION, f"高度{max_height}板但炸板率{broken_rate:.0f}%，封板率{success_rate:.0f}%"
        
        # 5. 萌芽期: 量能从低位回升 且 高度突破
        if v_ratio_rebounding and prev_amount > 0 and total_amount > prev_amount:
            if max_height >= 3:
                return MarketCycle.INCUBATION, f"量能回升(v_ratio={v_ratio:.2f})，高度{max_height}板，新周期萌芽"
        
        # 5b. 萌芽期: 高度突破且量能放大
        if prev_height > 0 and max_height > prev_height and max_height >= 4:
            if v_ratio > 1.0:
                return MarketCycle.INCUBATION, f"高度从{prev_height}突破至{max_height}板，量能{v_ratio:.2f}倍均值"
        
        # 6. 混沌期: 量能低于均值 且 高度 <= 3
        if v_ratio < 0.9 and max_height <= 3:
            return MarketCycle.CHAOS, f"量能{v_ratio:.2f}倍均值偏低，高度{max_height}板，无明确主线"
        
        # 6b. 混沌期: 情绪震荡
        if max_height <= 3 and 30 <= sentiment <= 50:
            return MarketCycle.CHAOS, f"高度{max_height}板，情绪{sentiment:.0f}分震荡，轮动行情"
        
        # 7. 冰点期 (兜底)
        if max_height <= 2 and sentiment < 30:
            return MarketCycle.ICE_POINT, f"高度仅{max_height}板，情绪{sentiment:.0f}分"
        
        # 默认情况
        return MarketCycle.UNKNOWN, f"数据不足或处于过渡状态(v_ratio={v_ratio:.2f})"
    
    # ==================== 兼容旧接口 ====================
    
    def calculate_scores(self, stats: Dict[str, Any]) -> Tuple[float, float]:
        """
        计算情绪评分和市场强度评分 (旧接口，使用默认基准)
        
        注意: 此方法使用固定默认基准，建议使用 calculate_scores_with_baseline
        """
        baseline = {
            "avg_amount_30d": self.DEFAULT_AVG_AMOUNT,
            "avg_limit_up_30d": self.DEFAULT_AVG_LIMIT_UP,
            "avg_limit_down_30d": 5,
        }
        sentiment, strength, _ = self.calculate_scores_with_baseline(stats, baseline)
        return sentiment, strength
    
    def identify_cycle(
        self, 
        stats: Dict[str, Any], 
        prev_stats: Optional[Dict[str, Any]] = None
    ) -> Tuple[MarketCycle, str]:
        """
        判定市场周期 (旧接口，使用默认基准)
        
        注意: 此方法使用固定默认基准，建议使用 identify_cycle_with_baseline
        """
        # 使用默认基准进行同步判定
        max_height = self._safe_float(stats.get("max_limit_height"))
        limit_down = self._safe_float(stats.get("limit_down_count"))
        broken = self._safe_float(stats.get("broken_limit_count"))
        limit_up = self._safe_float(stats.get("limit_up_count"))
        total_amount = self._safe_float(stats.get("total_amount"))
        
        sentiment, strength = self.calculate_scores(stats)
        
        if limit_up + broken > 0:
            success_rate = limit_up / (limit_up + broken) * 100
        else:
            success_rate = 0
        
        if limit_up > 0:
            broken_rate = broken / limit_up * 100
        else:
            broken_rate = 0
        
        amount_yi = total_amount / 1e8
        
        prev_height = 0.0
        if prev_stats:
            prev_height = self._safe_float(prev_stats.get("max_limit_height"))
        
        # 简化的周期判定
        if max_height <= 2 and sentiment < 30 and limit_down > 15:
            return MarketCycle.ICE_POINT, f"高度仅{max_height}板，情绪{sentiment:.0f}分，跌停{limit_down}家"
        
        if limit_down > 15:
            return MarketCycle.DECLINE, f"跌停{limit_down}家，市场情绪快速降温"
        
        if max_height >= 5 and amount_yi > 8000 and success_rate > 80:
            return MarketCycle.MAIN_UPWARD, f"高度{max_height}板，成交{amount_yi:.0f}亿，封板率{success_rate:.0f}%"
        
        if max_height >= 4 and (broken_rate > 25 or success_rate < 60):
            return MarketCycle.ROTATION, f"高度{max_height}板但炸板率{broken_rate:.0f}%"
        
        if max_height <= 3 and 30 <= sentiment <= 50:
            return MarketCycle.CHAOS, f"高度{max_height}板，情绪{sentiment:.0f}分震荡"
        
        return MarketCycle.UNKNOWN, "数据不足或处于过渡状态"
    
    async def load_recent_final_scores(
        self,
        trade_date: str,
        mongo_manager,
        days: int = 5,
    ) -> List[Tuple[Optional[float], Optional[float]]]:
        """
        加载近 N 天的最终评分 (用于 5 日 EMA 平滑)
        
        Returns:
            [(sentiment_ema5, strength_ema5), ...] 按日期从新到旧
        """
        history = await mongo_manager.find_many(
            "market_analysis",
            {"trade_date": {"$lt": trade_date}},
            projection={
                "trade_date": 1,
                "sentiment_ema5": 1,
                "strength_ema5": 1,
                "sentiment_score": 1,
                "strength_score": 1,
                "_id": 0,
            },
            sort=[("trade_date", -1)],
            limit=days,
        )
        
        result = []
        for item in history:
            sent = self._safe_float(
                item.get("sentiment_ema5") or item.get("sentiment_score"),
                default=None
            )
            stren = self._safe_float(
                item.get("strength_ema5") or item.get("strength_score"),
                default=None
            )
            result.append((sent, stren))
        
        return result
    
    async def analyze_and_store(
        self,
        stats: Dict[str, Any],
        prev_stats: Optional[Dict[str, Any]] = None,
        mongo_manager = None,
    ) -> Dict[str, Any]:
        """
        完整分析流程 (V2.3 区间化版)
        
        V2.3 优化:
        1. 核心分经过 3 日 EMA 平滑
        2. 最终评分经过 5 日 EMA 强平滑，消除锯齿
        3. 3 日趋势判定 (up/down/flat)
        4. 双趋势组合判定周期
        5. 强弱差 ≥15 分且趋势方向相反才显示
        
        流程:
        1. 加载 MA10 基准 + 近 5 日评分
        2. 计算核心分 → 3 日 EMA → 趋势分 → 原始评分
        3. 原始评分 → 5 日 EMA → 平滑评分
        4. 计算 3 日趋势方向
        5. 双趋势组合判定周期
        """
        trade_date = stats.get("trade_date", "")
        
        # 1. 加载数据
        if mongo_manager:
            baseline = await self.load_ma10_baseline(trade_date, mongo_manager)
            recent_core = await self.load_recent_core_scores(trade_date, mongo_manager, days=3)
            recent_final = await self.load_recent_final_scores(trade_date, mongo_manager, days=5)
        else:
            baseline = {"data_count": 0}
            recent_core = []
            recent_final = []
        
        # 解析历史数据
        prev_sent_cores = [s[0] for s in recent_core if s[0] is not None]
        prev_stren_cores = [s[1] for s in recent_core if s[1] is not None]
        prev_sent_finals = [s[0] for s in recent_final if s[0] is not None]
        prev_stren_finals = [s[1] for s in recent_final if s[1] is not None]
        
        # 2. 计算当日核心分
        sentiment_core_raw, sent_detail = self.calculate_sentiment_core_v2(stats, baseline)
        strength_core_raw, stren_detail = self.calculate_strength_core_v2(stats, baseline)
        
        # 3. 核心分 3 日 EMA 平滑
        sentiment_core_ema = self.apply_3day_ema(
            sentiment_core_raw,
            prev_sent_cores[0] if len(prev_sent_cores) > 0 else None,
            prev_sent_cores[1] if len(prev_sent_cores) > 1 else None,
        )
        strength_core_ema = self.apply_3day_ema(
            strength_core_raw,
            prev_stren_cores[0] if len(prev_stren_cores) > 0 else None,
            prev_stren_cores[1] if len(prev_stren_cores) > 1 else None,
        )
        
        # 4. 计算趋势分
        prev_sent_ema = prev_sent_cores[0] if prev_sent_cores else None
        prev_stren_ema = prev_stren_cores[0] if prev_stren_cores else None
        
        sentiment_trend_score, _ = self.calculate_trend_score(sentiment_core_ema, prev_sent_ema)
        strength_trend_score, _ = self.calculate_trend_score(strength_core_ema, prev_stren_ema)
        
        # 5. 原始评分 = 平滑核心分 + 趋势分
        sentiment_raw = min(100, max(0, sentiment_core_ema + sentiment_trend_score))
        strength_raw = min(100, max(0, strength_core_ema + strength_trend_score))
        
        # 6. 最终评分: 5 日 EMA 强平滑
        sentiment_ema5 = self.apply_5day_ema(
            [sentiment_raw] + prev_sent_finals[:4]
        )
        strength_ema5 = self.apply_5day_ema(
            [strength_raw] + prev_stren_finals[:4]
        )
        
        # 7. 计算 3 日趋势方向
        sentiment_trend_3d = self.identify_3day_trend(
            sentiment_ema5,
            prev_sent_finals[0] if len(prev_sent_finals) > 0 else None,
            prev_sent_finals[1] if len(prev_sent_finals) > 1 else None,
        )
        strength_trend_3d = self.identify_3day_trend(
            strength_ema5,
            prev_stren_finals[0] if len(prev_stren_finals) > 0 else None,
            prev_stren_finals[1] if len(prev_stren_finals) > 1 else None,
        )
        
        # 8. 双趋势组合判定周期
        cycle, reason = self.identify_cycle_by_trends(
            sentiment_trend_3d, strength_trend_3d,
            sentiment_ema5, strength_ema5
        )
        
        # 9. 强弱差 (≥15分且趋势方向相反才显示)
        raw_diff = strength_ema5 - sentiment_ema5
        show_divergence = (
            abs(raw_diff) >= DIVERGENCE_THRESHOLD and
            sentiment_trend_3d != strength_trend_3d and
            sentiment_trend_3d != "flat" and
            strength_trend_3d != "flat"
        )
        strength_diff = round(raw_diff, 2) if show_divergence else 0
        
        # 10. 获取仓位建议
        position = self.get_position_advice(cycle)
        
        # 11. 构建分析结果
        analysis = {
            "trade_date": trade_date,
            "created_at": datetime.utcnow(),
            
            # === V2.3 双评分 (5日EMA平滑后) ===
            "sentiment_score": round(sentiment_ema5, 2),
            "strength_score": round(strength_ema5, 2),
            
            # 5日EMA平滑后的评分 (用于下次计算)
            "sentiment_ema5": sentiment_ema5,
            "strength_ema5": strength_ema5,
            
            # 原始评分 (未5日平滑)
            "sentiment_raw": round(sentiment_raw, 2),
            "strength_raw": round(strength_raw, 2),
            
            # 核心分 (原始 + 3日平滑)
            "sentiment_core_score": sentiment_core_raw,
            "strength_core_score": strength_core_raw,
            "sentiment_core_ema": sentiment_core_ema,
            "strength_core_ema": strength_core_ema,
            
            # 趋势分
            "sentiment_trend_score": sentiment_trend_score,
            "strength_trend_score": strength_trend_score,
            
            # 3日趋势方向 (区间化关键)
            "sentiment_trend_3d": sentiment_trend_3d,
            "strength_trend_3d": strength_trend_3d,
            
            # 强弱差 (≥15分且趋势相反才有效)
            "strength_diff": strength_diff,
            "strength_diff_raw": round(raw_diff, 2),
            
            # === 周期 (基于双趋势组合) ===
            "cycle": cycle.value,
            "cycle_name": CYCLE_DESCRIPTIONS.get(cycle, ""),
            "cycle_reason": reason,
            
            # === 仓位建议 ===
            "position_advice": position,
            
            # === MA基准 ===
            "baseline_data_count": baseline.get("data_count", 0),
            
            # === 关键指标快照 ===
            "max_limit_height": stats.get("max_limit_height", 0),
            "limit_up_count": stats.get("limit_up_count", 0),
            "limit_down_count": stats.get("limit_down_count", 0),
            "seal_rate": stats.get("seal_rate", 0),
            "cont_board_count": stats.get("cont_board_count", 0),
            "promotion_rate": stats.get("promotion_rate"),
            "up_ratio": stats.get("up_ratio", 0),
            "pct_chg_median": stats.get("pct_chg_median"),
            "index_pct_chg": stats.get("index_pct_chg"),
            "total_amount": stats.get("total_amount", 0),
            "north_money": stats.get("north_money", 0),
            
            # === 兼容旧字段 ===
            "sentiment_score_ema": round(sentiment_ema5, 2),
            "v_ratio": (stats.get("total_amount", 0) / baseline.get("avg_amount", 1)) if baseline.get("avg_amount") else 1.0,
        }
        
        # 趋势符号
        trend_sym = {"up": "↑", "flat": "→", "down": "↓"}
        sent_sym = trend_sym.get(sentiment_trend_3d, "?")
        stren_sym = trend_sym.get(strength_trend_3d, "?")
        
        self.logger.info(
            f"[{trade_date}] 情绪={sentiment_ema5:.0f}{sent_sym} "
            f"强度={strength_ema5:.0f}{stren_sym} | "
            f"{cycle.value} | {position['range']}"
        )
        
        # 存储到 MongoDB
        if mongo_manager:
            await mongo_manager.update_one(
                "market_analysis",
                {"trade_date": trade_date},
                {"$set": analysis},
                upsert=True,
            )
        
        return analysis


# 全局单例
analysis_manager = AnalysisManager()
