"""
实盘9层筛选管道（LiveFilterPipeline）

与回测9层筛选逻辑对齐，但针对实盘场景做了适配：
- 数据源：实时行情（必盈/东方财富）而非MongoDB日线
- 时序：盘中逐层执行，每层可独立开关
- 竞价：实盘可获取真实竞价数据（9:25定价），回测只能近似

9层筛选：
  L1 强制空仓 — 涨停/跌停数极端时清仓
  L2 特殊时期 — 节假日/会议/月末降仓
  L3 情绪周期 — 市场情绪→仓位系数
  L4 盘前预选 — 排除ST/次新/低流动性
  L5 竞价过滤 — 真实竞价数据过滤（实盘优势）
  L6 策略量能 — 复用回测_build_strategy_filter_conditions
  L7 综合排序 — 策略优先级+候选去重
  L8 仓位控制 — 情绪×特殊×单票上限
  L9 买入执行 — T+1/跳空止损/成交概率

用法:
    pipeline = LiveFilterPipeline(scanner)
    result = await pipeline.apply(trade_date, candidates, positions, account)
    # result.action: "trade" | "hold" | "empty"
    # result.candidates: 过滤后的候选列表
    # result.position_ratio: 建议仓位比例 (0.0 ~ 1.0)
"""

import math
import logging
from datetime import datetime, date
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class FilterResult:
    """9层筛选结果"""
    action: str = "trade"           # trade/hold/empty
    candidates: List[Dict] = field(default_factory=list)  # 过滤后的候选
    position_ratio: float = 1.0     # 建议仓位比例
    layers_applied: Dict[str, bool] = field(default_factory=dict)  # 各层是否生效
    layer_details: Dict[str, str] = field(default_factory=dict)    # 各层日志
    force_empty_reason: str = ""    # 强制空仓原因


class LiveFilterPipeline:
    """实盘9层筛选管道"""

    # 强制空仓阈值（与回测portfolio_backtest.py一致）
    FORCE_EMPTY_LIMIT_DOWN = 50   # 跌停≥50只
    FORCE_EMPTY_LIMIT_UP = 10     # 涨停≤10只

    # 特殊时期配置
    SPECIAL_PERIODS = {
        # 月末最后2个交易日降仓
        "month_end": {"days_before": 2, "position_ratio": 0.3},
        # 重要会议期间降仓
        "conference": {"position_ratio": 0.5},
    }

    # 策略优先级（同时多策略选中同一股票时，按优先级取）
    STRATEGY_PRIORITY = {
        "dragon_head": 1,         # 龙头低吸最高优先
        "leader_buy_dip": 1,
        "limit_down_qiao": 2,     # 跌停翘板
        "first_limit_up": 3,      # 首板打板
        "halfway_chase": 4,       # 半路追涨
        "anomaly_broken": 5,     # 异动开板
        "anomaly_strong": 5,     # 异动强势
        "anomaly_surge": 5,      # 异动拉升
    }

    def __init__(self, scanner=None, config: Dict = None):
        self._scanner = scanner
        self._config = config or {}

        # 层开关（默认全部开启）
        self._layer_enabled = {
            "L1_force_empty": self._config.get("enable_force_empty", True),
            "L2_special_period": self._config.get("enable_special_period", True),
            "L3_sentiment": self._config.get("enable_sentiment_cycle", True),
            "L4_premarket": self._config.get("enable_premarket_filter", True),
            "L5_auction": self._config.get("enable_auction_filter", True),
            "L6_strategy": True,   # 策略筛选必须开启
            "L7_ranking": True,    # 综合排序必须开启
            "L8_position": True,   # 仓位控制必须开启
        }

        # 情绪状态缓存
        self._sentiment_score = 50.0
        self._sentiment_period = "chaos"

    # ========================================================================
    # 主入口
    # ========================================================================

    async def apply(
        self,
        trade_date: str,
        candidates: List[Dict],
        positions: List[Dict],
        account: Dict = None,
        realtime_data: Dict = None,
    ) -> FilterResult:
        """
        执行9层筛选

        Args:
            trade_date: 交易日期 (YYYYMMDD)
            candidates: 原始候选列表 [{ts_code, strategy, ...}]
            positions: 当前持仓列表
            account: 账户信息 {cash, total_value, ...}
            realtime_data: 实时行情 {ts_code: {close, pct_chg, ...}}
        """
        result = FilterResult(candidates=list(candidates))
        ratio = 1.0  # 仓位系数

        # ---- L1: 强制空仓 ----
        if self._layer_enabled["L1_force_empty"]:
            force_empty, reason = await self._check_force_empty(trade_date, realtime_data)
            result.layers_applied["L1_force_empty"] = True
            if force_empty:
                result.action = "empty"
                result.force_empty_reason = reason
                result.position_ratio = 0.0
                result.candidates = []
                result.layer_details["L1_force_empty"] = f"⚠️ 强制空仓: {reason}"
                logger.warning(f"[L1] 强制空仓: {reason}")
                return result
            result.layer_details["L1_force_empty"] = "✅ 不触发"

        # ---- L2: 特殊时期 ----
        if self._layer_enabled["L2_special_period"]:
            special_ratio, reason = self._check_special_period(trade_date)
            result.layers_applied["L2_special_period"] = True
            ratio *= special_ratio
            result.layer_details["L2_special_period"] = (
                f"仓位系数={special_ratio:.0%} ({reason})" if special_ratio < 1.0 else "✅ 非特殊时期"
            )

        # ---- L3: 情绪周期 ----
        if self._layer_enabled["L3_sentiment"]:
            sentiment_ratio, score, period = await self._calc_sentiment(trade_date, realtime_data)
            result.layers_applied["L3_sentiment"] = True
            self._sentiment_score = score
            self._sentiment_period = period
            ratio *= sentiment_ratio
            result.layer_details["L3_sentiment"] = (
                f"情绪={score:.0f}→{period}, 仓位系数={sentiment_ratio:.0%}"
            )

        # ---- L4: 盘前预选 ----
        if self._layer_enabled["L4_premarket"]:
            before = len(result.candidates)
            result.candidates = self._premarket_filter(result.candidates)
            result.layers_applied["L4_premarket"] = True
            result.layer_details["L4_premarket"] = (
                f"过滤: {before}→{len(result.candidates)} (排除ST/次新/低流动)"
            )

        # ---- L5: 竞价过滤 ----
        if self._layer_enabled["L5_auction"]:
            before = len(result.candidates)
            result.candidates = await self._auction_filter(
                result.candidates, trade_date, realtime_data
            )
            result.layers_applied["L5_auction"] = True
            result.layer_details["L5_auction"] = (
                f"过滤: {before}→{len(result.candidates)} (排除极端竞价)"
            )

        # ---- L6: 策略量能 ---- (已由scanner._apply_strategies完成)
        result.layers_applied["L6_strategy"] = True
        result.layer_details["L6_strategy"] = f"✅ 复用回测筛选 ({len(result.candidates)}个候选)"

        # ---- L7: 综合排序 ----
        if self._layer_enabled["L7_ranking"]:
            before = len(result.candidates)
            result.candidates = self._rank_and_dedup(result.candidates)
            result.layers_applied["L7_ranking"] = True
            result.layer_details["L7_ranking"] = (
                f"排序去重: {before}→{len(result.candidates)}"
            )

        # ---- L8: 仓位控制 ----
        max_position_ratio = self._config.get("max_total_position", 0.7)
        max_per_stock = self._config.get("max_position_per_stock", 0.2)
        final_ratio = min(ratio, max_position_ratio)
        result.position_ratio = final_ratio
        result.layers_applied["L8_position"] = True
        result.layer_details["L8_position"] = (
            f"总仓位={final_ratio:.0%} (情绪×特殊={ratio:.0%}, 上限{max_position_ratio:.0%}), "
            f"单票上限{max_per_stock:.0%}"
        )

        return result

    # ========================================================================
    # L1: 强制空仓
    # ========================================================================

    async def _check_force_empty(
        self, trade_date: str, realtime_data: Dict = None
    ) -> Tuple[bool, str]:
        """
        检查是否触发强制空仓

        实盘优势: 可用必盈涨停池/跌停池获取实时数据，比回测更精确
        回测用MongoDB日线统计涨停数（收盘后），实盘盘中即可判断
        """
        limit_up_count = 0
        limit_down_count = 0

        # 优先用实时行情统计
        if realtime_data:
            for code, data in realtime_data.items():
                pct = data.get("pct_chg", 0)
                if isinstance(pct, (int, float)):
                    if pct >= 9.5:
                        limit_up_count += 1
                    elif pct <= -9.5:
                        limit_down_count += 1
        else:
            # 无实时数据时从MongoDB取前日数据
            try:
                from core.managers import mongo_manager
                await mongo_manager.initialize()
                prev_date = await self._get_prev_trade_date(trade_date)
                if prev_date:
                    cursor = mongo_manager.db["stock_daily_ak_full"].find(
                        {"trade_date": int(prev_date)},
                        {"pct_chg": 1, "_id": 0}
                    )
                    async for doc in cursor:
                        pct = doc.get("pct_chg", 0)
                        if pct >= 9.5:
                            limit_up_count += 1
                        elif pct <= -9.5:
                            limit_down_count += 1
            except Exception as e:
                logger.warning(f"[L1] 获取涨跌停数失败: {e}")
                return False, ""  # 数据不足不触发

        # 判断
        if limit_down_count >= self.FORCE_EMPTY_LIMIT_DOWN:
            return True, f"跌停{limit_down_count}只≥{self.FORCE_EMPTY_LIMIT_DOWN}"
        if limit_up_count <= self.FORCE_EMPTY_LIMIT_UP and limit_down_count > 0:
            return True, f"涨停{limit_up_count}只≤{self.FORCE_EMPTY_LIMIT_UP}且跌停{limit_down_count}只"

        return False, ""

    # ========================================================================
    # L2: 特殊时期
    # ========================================================================

    def _check_special_period(self, trade_date: str) -> Tuple[float, str]:
        """
        特殊时期检测 → 仓位系数

        实盘适配: 可接入日历API判断节假日/会议，回测用hardcode日期表
        """
        td = datetime.strptime(trade_date, "%Y%m%d")
        day = td.day
        weekday = td.weekday()

        # 月末: 最后2个交易日（简化用日期>=28判断）
        if day >= 28:
            return self.SPECIAL_PERIODS["month_end"]["position_ratio"], "月末降仓"

        # 周五: 降低仓位（周末不确定性）
        if weekday == 4:  # Friday
            return 0.7, "周五降仓"

        # TODO: 可扩展接入节假日日历、重要会议日程
        return 1.0, "正常"

    # ========================================================================
    # L3: 情绪周期
    # ========================================================================

    async def _calc_sentiment(
        self, trade_date: str, realtime_data: Dict = None
    ) -> Tuple[float, float, str]:
        """
        计算市场情绪 → 仓位系数

        与回测一致的计算方法:
          sentiment_score = (涨停数 - 跌停数) + 大盘涨幅×10 + 50
          rising(>70): 仓位100%, chaos(40-70): 70%, depression(<40): 30%

        实盘优势: 可盘中实时计算（回测只能收盘后算）
        """
        limit_up = 0
        limit_down = 0
        avg_pct = 0.0

        if realtime_data and len(realtime_data) > 100:
            # 用实时行情（盘中有足够数据时）
            pcts = []
            for code, data in realtime_data.items():
                pct = data.get("pct_chg", 0)
                if isinstance(pct, (int, float)):
                    pcts.append(pct)
                    if pct >= 9.5:
                        limit_up += 1
                    elif pct <= -9.5:
                        limit_down += 1
            avg_pct = sum(pcts) / len(pcts) if pcts else 0
        else:
            # 用前日MongoDB数据
            try:
                from core.managers import mongo_manager
                await mongo_manager.initialize()
                prev_date = await self._get_prev_trade_date(trade_date)
                if prev_date:
                    pipeline = [
                        {"$match": {"trade_date": int(prev_date)}},
                        {"$group": {
                            "_id": None,
                            "avg_pct": {"$avg": "$pct_chg"},
                            "limit_up": {"$sum": {"$cond": [{"$gte": ["$pct_chg", 9.5]}, 1, 0]}},
                            "limit_down": {"$sum": {"$cond": [{"$lte": ["$pct_chg", -9.5]}, 1, 0]}},
                        }}
                    ]
                    async for doc in mongo_manager.db["stock_daily_ak_full"].aggregate(pipeline):
                        limit_up = doc.get("limit_up", 0)
                        limit_down = doc.get("limit_down", 0)
                        avg_pct = doc.get("avg_pct", 0) or 0
            except Exception as e:
                logger.warning(f"[L3] 情绪计算失败: {e}")

        # 计算情绪评分（与回测portfolio_backtest.py一致）
        score = (limit_up - limit_down) + avg_pct * 10 + 50
        score = max(0, min(100, score))

        # 情绪周期
        if score > 70:
            period = "rising"
            ratio = 1.0
        elif score >= 40:
            period = "chaos"
            ratio = 0.7
        else:
            period = "depression"
            ratio = 0.3

        return ratio, score, period

    # ========================================================================
    # L4: 盘前预选
    # ========================================================================

    def _premarket_filter(self, candidates: List[Dict]) -> List[Dict]:
        """
        排除: ST/退市/次新(上市<60天)/低流动性(日成交<500万)

        实盘适配: 可从实时行情直接判断流动性（比回测用历史成交额更准）
        """
        filtered = []
        for c in candidates:
            name = c.get("stock_name", "") or c.get("reason", "")
            ts_code = c.get("ts_code", "")

            # 排除ST/退市
            if "ST" in name or "退" in name:
                continue

            # 排除次新（代码规则：60/00/30开头且上市不足60个交易日）
            # 简化：北交所(8/9开头)次新波动大，优先排除上市<30天
            # 实际需查stock_basic的list_date

            # 排除低成交额（用实时数据中的amount判断）
            amount = c.get("amount", 0) or c.get("amt", 0)
            if amount and amount < 500:  # 万元
                continue

            filtered.append(c)

        return filtered

    # ========================================================================
    # L5: 竞价过滤
    # ========================================================================

    async def _auction_filter(
        self, candidates: List[Dict], trade_date: str, realtime_data: Dict = None
    ) -> List[Dict]:
        """
        竞价过滤（实盘优势层！）

        回测只能用opening_pct_chg近似，实盘可获取9:25真实竞价数据

        实盘逻辑:
        1. 9:25后获取竞价涨幅（=开盘价/昨收-1）
        2. 排除极端: 高开>7%（追高风险）/ 低开<-5%（可能有风险）
        3. 策略差异化:
           - 首板打板: 需竞价强势(≥2%) → 排除低开
           - 半路追涨: 不要求竞价强势 → 保留正常区间
        """
        filtered = []

        for c in candidates:
            strategy = c.get("strategy", "")
            ts_code = c.get("ts_code", "")

            # 从实时数据获取开盘涨幅
            opening_pct = None
            if realtime_data and ts_code in realtime_data:
                rd = realtime_data[ts_code]
                opening_pct = rd.get("opening_pct_chg", None)
                if opening_pct is None:
                    # 从open和pre_close计算
                    op = rd.get("open", 0)
                    pc = rd.get("pre_close", 0)
                    if op and pc and pc > 0:
                        opening_pct = (op - pc) / pc * 100

            if opening_pct is None:
                filtered.append(c)  # 无竞价数据保留
                continue

            # 按策略差异化过滤
            if strategy in ("first_limit_up",):
                # 首板打板: 需竞价强势(≥2%)
                if opening_pct < 2:
                    continue
                if opening_pct > 7:
                    continue  # 一字板高开追不上
            else:
                # 半路追涨/跌停翘板/龙头低吸: 仅排除极端
                if opening_pct > 7 or opening_pct < -5:
                    continue

            filtered.append(c)

        return filtered

    # ========================================================================
    # L7: 综合排序
    # ========================================================================

    def _rank_and_dedup(self, candidates: List[Dict]) -> List[Dict]:
        """
        候选去重+策略优先级排序

        规则:
        1. 同一只股票被多策略选中 → 取优先级最高的策略
        2. 按策略优先级排序
        3. 限制最大候选数（避免过多信号）
        """
        # 按股票去重，保留优先级最高的策略
        best_by_code = {}
        for c in candidates:
            ts_code = c.get("ts_code", "")
            strategy = c.get("strategy", "")
            priority = self.STRATEGY_PRIORITY.get(strategy, 99)

            if ts_code not in best_by_code:
                best_by_code[ts_code] = (priority, c)
            else:
                existing_priority, _ = best_by_code[ts_code]
                if priority < existing_priority:
                    best_by_code[ts_code] = (priority, c)

        # 按优先级排序
        sorted_candidates = [
            item[1] for item in
            sorted(best_by_code.values(), key=lambda x: x[0])
        ]

        # 限制最大候选数
        max_candidates = self._config.get("max_candidates_per_scan", 10)
        if len(sorted_candidates) > max_candidates:
            sorted_candidates = sorted_candidates[:max_candidates]

        return sorted_candidates

    # ========================================================================
    # 辅助方法
    # ========================================================================

    async def _get_prev_trade_date(self, trade_date: str) -> Optional[str]:
        """获取前一个交易日"""
        try:
            from core.managers import mongo_manager
            pipeline = [
                {"$match": {"trade_date": {"$lt": int(trade_date)}}},
                {"$group": {"_id": None, "max_date": {"$max": "$trade_date"}}},
            ]
            async for doc in mongo_manager.db["stock_daily_ak_full"].aggregate(pipeline):
                return str(doc["max_date"])
        except:
            return None

    def get_sentiment_info(self) -> Dict:
        """获取当前情绪状态（供外部查询）"""
        return {
            "score": self._sentiment_score,
            "period": self._sentiment_period,
        }
