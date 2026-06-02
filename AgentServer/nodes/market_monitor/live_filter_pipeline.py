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
     ⚠️ L9 实际由 MarketScanner 实现，不在本文件中:
     - 买入: scanner._execute_signals() → SimulatedBroker.place_order()
     - 止损: scanner._check_positions() → 策略级SL/TP(复用STRATEGY_CONFIGS)
     - T+1: SimulatedBroker 内置 today_buy_qty 追踪
     - 跳空止损: _check_positions_quick() 当日open<止损价→open卖出

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
class CandidateTrace:
    """单个候选在各层的追踪记录"""
    ts_code: str
    stock_name: str
    strategy: str
    strategy_name: str
    price: float = 0.0
    pct_chg: float = 0.0
    layer_results: Dict[str, Any] = field(default_factory=dict)  # {layer: {passed, reason, score}}
    final_status: str = "pending"  # pending/passed/rejected
    final_rejection_layer: str = ""
    final_rejection_reason: str = ""


@dataclass
class FilterResult:
    """9层筛选结果"""
    action: str = "trade"           # trade/hold/empty
    candidates: List[Dict] = field(default_factory=list)  # 过滤后的候选
    position_ratio: float = 1.0     # 建议仓位比例
    layers_applied: Dict[str, bool] = field(default_factory=dict)  # 各层是否生效
    layer_details: Dict[str, str] = field(default_factory=dict)    # 各层日志
    force_empty_reason: str = ""    # 强制空仓原因
    # 【V50.1】信号链路追踪: 记录每层每个候选的通过/拒绝状态
    trace_candidates: List[CandidateTrace] = field(default_factory=list)
    trace_summary: Dict[str, Dict] = field(default_factory=dict)  # {layer: {passed: N, rejected: N}}


class LiveFilterPipeline:
    """实盘9层筛选管道"""

    # 强制空仓阈值（与回测portfolio_backtest.py一致）
    FORCE_EMPTY_LIMIT_DOWN = 80   # 【V50:跌停≥80只,与回测GLOBAL_RISK.force_empty_limit_down对齐(原50)】
    FORCE_EMPTY_LIMIT_UP = 10     # 涨停≤10只

    # 特殊时期配置
    SPECIAL_PERIODS = {
        # 月末最后2个交易日降仓（回退用，正式逻辑走SpecialPeriodFilter）
        "month_end": {"days_before": 2, "position_ratio": 0.3},
    }

    # 策略优先级（同时多策略选中同一股票时，按优先级取）
    STRATEGY_PRIORITY = {
        "dragon_head": 1,         # 龙头低吸最高优先
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

    def _resolve_positions_account(
        self,
        positions: Optional[List[Dict]],
        account: Optional[Dict],
    ) -> Tuple[List[Dict], Dict]:
        """自动从scanner获取持仓和账户信息【v2.9.48:从apply提取,v2.9.51:getattr清理】"""
        if positions is None and self._scanner:
            broker = self._scanner._broker
            if broker:
                positions = [{"ts_code": p.ts_code, "strategy": p.strategy} for p in broker.get_positions()]
            else:
                positions = []
        elif positions is None:
            positions = []

        if account is None and self._scanner:
            broker = self._scanner._broker
            if broker:
                account = {"cash": broker.account.available_cash}
            else:
                account = {"cash": 0}
        return positions, account

    async def _apply_L1_force_empty(
        self,
        result: FilterResult,
        trade_date: str,
        realtime_data: Optional[Dict],
    ) -> bool:
        """L1强制空仓检查, 返回True=触发强制空仓(apply应提前返回)【v2.9.48:从apply提取】"""
        if not self._layer_enabled["L1_force_empty"]:
            return False

        force_empty, reason, l1_stats = await self._check_force_empty(trade_date, realtime_data)
        result.layers_applied["L1_force_empty"] = True
        if force_empty:
            result.action = "empty"
            result.force_empty_reason = reason
            result.position_ratio = 0.0
            result.candidates = []
            result.layer_details["L1_force_empty"] = f"⚠️ 强制空仓: {reason}"
            for t in result.trace_candidates:
                t.layer_results["L1_force_empty"] = {"passed": False, "reason": f"强制空仓: {reason}"}
                t.final_status = "rejected"
                t.final_rejection_layer = "L1_force_empty"
                t.final_rejection_reason = f"强制空仓: {reason}"
            self._build_trace_summary(result)
            logger.warning(f"[L1] 强制空仓: {reason}")
            return True

        # L1未触发
        _lu = l1_stats.get("limit_up_count", 0)
        _ld = l1_stats.get("limit_down_count", 0)
        _idx = l1_stats.get("index_drop_pct", 0.0)
        result.layer_details["L1_force_empty"] = (
            f"✅ 未触发 (涨停{_lu}只, 跌停{_ld}只, "
            f"大盘{'' if _idx < 0.03 else '跌' + f'{_idx*100:.1f}%'} | "
            f"触发条件: 跌停≥80 / 涨停≤10且跌停>0 / 大盘跌≥3%)"
        )
        for t in result.trace_candidates:
            t.layer_results["L1_force_empty"] = {"passed": True}
        return False

    async def _apply_L3_sentiment(
        self,
        result: FilterResult,
        trade_date: str,
        realtime_data: Optional[Dict],
        ratio: float,
    ) -> float:
        """L3情绪周期筛选, 返回更新后的仓位系数【v2.9.48:从apply提取】"""
        if not self._layer_enabled["L3_sentiment"]:
            return ratio

        sentiment_ratio, score, period = await self._calc_sentiment(trade_date, realtime_data)
        result.layers_applied["L3_sentiment"] = True
        self._sentiment_score = score
        self._sentiment_period = period
        ratio *= sentiment_ratio

        # L3默认全部通过
        for t in result.trace_candidates:
            if t.final_status != "rejected":
                t.layer_results["L3_sentiment"] = {"passed": True}

        # 冰点期(<40)暂停半路追涨
        l3_drop_count = 0
        if score < 40:
            before_ids = {c["ts_code"] for c in result.candidates}
            result.candidates = [c for c in result.candidates
                                 if c.get("strategy") != "halfway_chase"]
            after_ids = {c["ts_code"] for c in result.candidates}
            dropped = before_ids - after_ids
            if dropped:
                self._record_layer_drop(result, "L3_sentiment", dropped,
                                        lambda c: f"冰点期(情绪{score:.0f}<40), 暂停半路追涨")
                logger.info(f"[L3] 冰点期(情绪={score:.0f}), 过滤半路追涨{len(dropped)}只")
                l3_drop_count = len(dropped)

        result.layer_details["L3_sentiment"] = (
            f"情绪={score:.0f}分→{period}, 仓位系数={sentiment_ratio:.0%}"
            + (f", 过滤半路追涨{l3_drop_count}只(冰点<40分暂停)" if l3_drop_count else "")
            + f" | 公式: 涨停-跌停+大盘×10+50 | 高潮≥70→100% / 分化55-70→70% / 震荡40-55→50% / 冰点<40→25%"
        )
        result.layer_details["L3_sentiment_data"] = {
            "score": round(score, 1), "period": period,
            "position_ratio": round(sentiment_ratio, 3),
            "l3_drop_count": l3_drop_count,
        }
        return ratio

    def _apply_filter_layer(
        self,
        result: FilterResult,
        layer_name: str,
        filtered: List[Dict],
        reject_reason_fn,
        detail_template: str,
    ) -> None:
        """通用过滤层: 记录before/after/dropped+淘汰明细+详情【v2.9.48:从apply提取(L4/L5/L7共享)】"""
        before_ids = {c["ts_code"] for c in result.candidates}
        result.candidates = filtered
        after_ids = {c["ts_code"] for c in result.candidates}
        dropped = before_ids - after_ids
        result.layers_applied[layer_name] = True
        self._record_layer_drop(result, layer_name, dropped, reject_reason_fn)
        result.layer_details[layer_name] = detail_template.format(
            before=len(before_ids), after=len(after_ids), dropped=len(dropped)
        )

    async def apply(
        self,
        trade_date: str,
        candidates: List[Dict],
        positions: List[Dict] = None,
        account: Dict = None,
        realtime_data: Dict = None,
    ) -> FilterResult:
        """
        执行9层筛选

        Args:
            trade_date: 交易日期 (YYYYMMDD)
            candidates: 原始候选列表 [{ts_code, strategy, ...}]
            positions: 当前持仓列表(不传则从scanner自动获取)【v2.9.40】
            account: 账户信息(不传则从scanner自动获取)【v2.9.40】
            realtime_data: 实时行情 {ts_code: {close, pct_chg, ...}}
        """
        # 【v2.9.40+2.9.48:自动获取持仓/账户信息提取为_resolve_positions_account】
        positions, account = self._resolve_positions_account(positions, account)

        result = FilterResult(candidates=list(candidates))
        ratio = 1.0  # 仓位系数

        # 【V50.1】初始化全量候选追踪
        self._init_traces(result, candidates)

        # ---- L1: 强制空仓 ----
        if await self._apply_L1_force_empty(result, trade_date, realtime_data):
            return result

        # ---- L2~L8: 筛选层应用 ----
        ratio = await self._apply_filter_layers(result, trade_date, realtime_data, ratio)

        # ---- L8: 仓位控制 ----
        max_position_ratio = self._config.get("max_total_position", 0.7)
        max_per_stock = self._config.get("max_position_per_stock", 0.2)
        final_ratio = min(ratio, max_position_ratio)
        result.position_ratio = final_ratio
        result.layers_applied["L8_position"] = True
        result.layer_details["L8_position"] = (
            f"总仓位上限={final_ratio:.0%} (情绪×特殊={ratio:.0%}, 硬上限{max_position_ratio:.0%}), "
            f"单票上限={max_per_stock:.0%} | 仓位系数=min(情绪仓位, 特殊时期, 硬上限)"
        )

        # 【V50.1】最终标记通过 + 构建汇总
        self._finalize_traces(result)

        return result

    async def _apply_filter_layers(
        self, result: FilterResult, trade_date: str,
        realtime_data: Dict, ratio: float
    ) -> float:
        """应用L2~L7筛选层, 返回仓位系数【v2.9.61:从apply提取】"""
        # ---- L2: 特殊时期 ----
        if self._layer_enabled["L2_special_period"]:
            special_ratio, reason = self._check_special_period(trade_date)
            result.layers_applied["L2_special_period"] = True
            ratio *= special_ratio
            result.layer_details["L2_special_period"] = (
                f"⚠️ {reason} → 仓位系数={special_ratio:.0%} (正常100%, 月末30%, 周五70%)" if special_ratio < 1.0 else f"✅ 非特殊时期 → 仓位系数=100% (无月末/季末/年末/节前效应)"
            )
            for t in result.trace_candidates:
                if t.final_status != "rejected":
                    t.layer_results["L2_special_period"] = {"passed": True}

        # ---- L3: 情绪周期 ----
        ratio = await self._apply_L3_sentiment(result, trade_date, realtime_data, ratio)

        # ---- L4: 盘前预选 ----
        if self._layer_enabled["L4_premarket"]:
            self._apply_filter_layer(
                result, "L4_premarket",
                self._premarket_filter(result.candidates),
                lambda c: self._premarket_reject_reason(c),
                "过滤: {before}→{after} (排除ST/退市/次新(<60天)/低流动(<500万/日): {dropped}只)",
            )

        # ---- L5: 竞价过滤 ----
        if self._layer_enabled["L5_auction"]:
            auction_filtered = await self._auction_filter(result.candidates, trade_date, realtime_data)
            self._apply_filter_layer(
                result, "L5_auction", auction_filtered,
                lambda c: "极端竞价(高开>7%或低开<-5%)",
                "过滤: {before}→{after} (排除极端竞价: {dropped}只 | 高开>7%追不上/低开<-5%有风险 | 首板打板额外要求竞价≥2%)",
            )

        # ---- L6: 策略量能 ---- (已由scanner._apply_strategies完成)
        result.layers_applied["L6_strategy"] = True
        result.layer_details["L6_strategy"] = f"✅ 复用回测策略筛选 → {len(result.candidates)}个候选通过量能/涨幅条件 (半路追涨:涨2-7%+量比>1.5 | 首板:涨停封板 | 龙头:连板回调 | 跌停翘板:撬板反弹)"
        for t in result.trace_candidates:
            if t.final_status != "rejected":
                t.layer_results["L6_strategy"] = {"passed": True}

        # ---- L7: 综合排序 ----
        if self._layer_enabled["L7_ranking"]:
            self._apply_filter_layer(
                result, "L7_ranking",
                self._rank_and_dedup(result.candidates),
                lambda c: "去重/排序靠后被截断",
                "排序去重: {before}→{after} (截断{dropped}只 | 优先级: 龙头>跌停翘板>首板>半路 | 同股多策略取最高 | 最多保留10候选)",
            )

        return ratio

    def _finalize_traces(self, result: FilterResult) -> None:
        """最终标记候选通过/拒绝状态+构建汇总【v2.9.61:从apply提取】"""
        passed_ids = {c["ts_code"] for c in result.candidates}
        for t in result.trace_candidates:
            if t.final_status == "pending":
                if t.ts_code in passed_ids:
                    t.final_status = "passed"
                else:
                    t.final_status = "rejected"
                    t.final_rejection_layer = t.final_rejection_layer or "unknown"
        self._build_trace_summary(result)

    # ========================================================================
    # 【V50.1】候选追踪辅助方法
    # ========================================================================

    def _init_traces(self, result, candidates) -> None:
        """初始化全量候选追踪"""
        result.trace_candidates = []
        for c in candidates:
            result.trace_candidates.append(CandidateTrace(
                ts_code=c.get("ts_code", ""),
                stock_name=c.get("stock_name", ""),
                strategy=c.get("strategy", ""),
                strategy_name=c.get("strategy_name", ""),
                price=c.get("price", 0),
                pct_chg=c.get("pct_chg", 0),
            ))

    def _record_layer_drop(self, result, layer, dropped_ids, reason_fn) -> None:
        """记录某层被淘汰的候选"""
        if not dropped_ids:
            for t in result.trace_candidates:
                if t.final_status != "rejected":
                    t.layer_results[layer] = {"passed": True}
            return
        all_candidates = {c["ts_code"]: c for c in result.candidates}
        for t in result.trace_candidates:
            if t.ts_code in dropped_ids and t.final_status != "rejected":
                original = all_candidates.get(t.ts_code, {})
                reason = reason_fn(original)
                t.layer_results[layer] = {"passed": False, "reason": reason}
                t.final_status = "rejected"
                t.final_rejection_layer = layer
                t.final_rejection_reason = reason
            elif t.final_status != "rejected":
                t.layer_results[layer] = {"passed": True}

    def _premarket_reject_reason(self, c) -> None:
        """分析盘前预选淘汰原因"""
        name = c.get("stock_name", "")
        if "ST" in name.upper():
            return f"ST股: {name}"
        ts_code = c.get("ts_code", "")
        vol = c.get("volume", 0)
        if vol == 0:
            return f"次新/退市(无行情): {ts_code}"
        if isinstance(vol, (int, float)) and vol < 500:
            return f"流动性不足(日成交{vol:.0f}万<500万)"
        return f"未知原因"

    def _build_trace_summary(self, result) -> Dict:
        """构建追踪汇总 — 正确追踪每层的输入/输出/淘汰
        
        每层都通过layer_results正确标记了passed/rejected:
        - 淘汰层(L1/L3冰点/L4/L5/L7): 部分passed, 部分rejected
        - 仓位调整层(L2/L3非冰点/L6/L8): 全部passed, 0 rejected
        """
        layers = ["L1_force_empty", "L2_special_period", "L3_sentiment",
                   "L4_premarket", "L5_auction", "L6_strategy",
                   "L7_ranking", "L8_position"]
        
        prev_output = len(result.trace_candidates)
        for layer in layers:
            passed = sum(1 for t in result.trace_candidates
                        if t.layer_results.get(layer, {}).get("passed") is True)
            rejected = sum(1 for t in result.trace_candidates
                          if t.layer_results.get(layer, {}).get("passed") is False)
            output = prev_output - rejected  # 本层输出 = 上层输出 - 本层淘汰
            result.trace_summary[layer] = {
                "total": passed + rejected,
                "passed": passed,
                "rejected": rejected,
                "input": prev_output,
                "output": output,
            }
            prev_output = output

    # ========================================================================
    # L1: 强制空仓
    # ========================================================================

    async def _check_force_empty(
        self, trade_date: str, realtime_data: Dict = None
    ) -> Tuple[bool, str, Dict]:
        """
        检查是否触发强制空仓【v2.9.56:提取数据收集】

        与回测portfolio_backtest.py完全对齐的3个条件:
        1. 跌停≥80只 → 强制空仓
        2. 涨停≤10只且跌停>0 → 强制空仓
        3. 大盘跌幅≥3% → 强制空仓 (V44回测修复, V52实盘补齐)

        Returns:
            (force_empty, reason, stats) stats={limit_up_count, limit_down_count, index_drop_pct}
        """
        if realtime_data:
            limit_up_count, limit_down_count, index_drop_pct = \
                self._count_limits_from_realtime(realtime_data)
        else:
            limit_up_count, limit_down_count, index_drop_pct = \
                await self._count_limits_from_mongo(trade_date)
            if limit_up_count is None:  # MongoDB查询失败
                return False, "", {"limit_up_count": 0, "limit_down_count": 0, "index_drop_pct": 0.0}

        # 【V52:从strategy_defaults读取阈值,与回测对齐】
        try:
            from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK
            index_drop_threshold = GLOBAL_RISK.get("force_empty_index_drop_pct", 0.03)
        except ImportError:
            index_drop_threshold = 0.03

        stats = {"limit_up_count": limit_up_count, "limit_down_count": limit_down_count, "index_drop_pct": index_drop_pct}

        # 判断(3个条件,与回测完全对齐)
        if limit_down_count >= self.FORCE_EMPTY_LIMIT_DOWN:
            return True, f"跌停{limit_down_count}只≥{self.FORCE_EMPTY_LIMIT_DOWN}", stats
        if limit_up_count <= self.FORCE_EMPTY_LIMIT_UP and limit_down_count > 0:
            return True, f"涨停{limit_up_count}只≤{self.FORCE_EMPTY_LIMIT_UP}且跌停{limit_down_count}只", stats
        if index_drop_pct >= index_drop_threshold:
            return True, f"大盘跌幅{index_drop_pct*100:.1f}%≥{index_drop_threshold*100:.0f}%", stats

        return False, "", stats

    def _count_limits_from_realtime(self, realtime_data: Dict) -> Tuple[int, int, float]:
        """从实时行情统计涨跌停数量【v2.9.56从_check_force_empty提取】
        
        Returns: (limit_up_count, limit_down_count, index_drop_pct)
        """
        limit_up_count = 0
        limit_down_count = 0
        for code, data in realtime_data.items():
            pct = data.get("pct_chg", 0)
            if isinstance(pct, (int, float)):
                if pct >= 9.5:
                    limit_up_count += 1
                elif pct <= -9.5:
                    limit_down_count += 1
        # 上证指数跌幅
        sh_index = realtime_data.get("000001.SH", {})
        index_drop_pct = 0.0
        if sh_index and isinstance(sh_index.get("pct_chg"), (int, float)):
            index_drop_pct = -sh_index["pct_chg"] / 100
        return limit_up_count, limit_down_count, index_drop_pct

    async def _count_limits_from_mongo(self, trade_date: str) -> Tuple[Optional[int], Optional[int], Optional[float]]:
        """从MongoDB统计涨跌停数量【v2.9.56从_check_force_empty提取】
        
        Returns: (limit_up_count, limit_down_count, index_drop_pct) 或 (None,None,None)表示查询失败
        """
        try:
            from core.managers import mongo_manager
            await mongo_manager.initialize()
            prev_date = await self._get_prev_trade_date(trade_date)
            limit_up_count = 0
            limit_down_count = 0
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
            # 上证指数跌幅
            idx_doc = await mongo_manager.db["stock_daily_ak_full"].find_one(
                {"ts_code": "000001.SH", "trade_date": int(prev_date or trade_date)},
                {"pct_chg": 1, "_id": 0}
            )
            index_drop_pct = 0.0
            if idx_doc and isinstance(idx_doc.get("pct_chg"), (int, float)):
                index_drop_pct = -idx_doc["pct_chg"] / 100
            return limit_up_count, limit_down_count, index_drop_pct
        except Exception as e:
            logger.warning(f"[L1] 获取涨跌停数失败: {e}")
            return None, None, None

    # ========================================================================
    # L2: 特殊时期
    # ========================================================================

    def _check_special_period(self, trade_date: str) -> Tuple[float, str]:
        """
        特殊时期检测 → 仓位系数

        复用回测引擎的SpecialPeriodFilter，与回测逻辑完全对齐。
        优先级：年末 > 季末 > 月末 > 重大会议 > 节假日前夕
        """
        try:
            from nodes.backtest_engine.factor_selection.special_period_filter import get_special_period_filter
            sp_filter = get_special_period_filter()
            ratio = sp_filter.get_position_multiplier(trade_date)
            if ratio < 1.0:
                # 找出生效的特殊时期名称
                active = sp_filter.get_active_periods(trade_date)
                if active:
                    names = ", ".join(p.name for p in active)
                    return ratio, names
                return ratio, "特殊时期降仓"
            return 1.0, "正常"
        except Exception as e:
            logger.warning(f"[L2] SpecialPeriodFilter异常: {e}, 回退简单判断")
            td = datetime.strptime(trade_date, "%Y%m%d")
            day = td.day
            weekday = td.weekday()
            # 简单回退逻辑
            if day >= 28:
                return 0.3, "月末降仓"
            if weekday == 4:
                return 0.7, "周五降仓"
            return 1.0, "正常"

    # ========================================================================
    # L3: 情绪周期
    # ========================================================================

    async def _calc_sentiment(
        self, trade_date: str, realtime_data: Dict = None
    ) -> Tuple[float, float, str]:
        """
        计算市场情绪 → 仓位系数
        
        【V50:统一使用emotion_cycle_manager,不再自己计算】
        原问题：live_filter_pipeline与emotion_cycle.py各自计算情绪,
        公式不同(简化vs五维评分)、阈值不同、仓位乘数不同,
        导致实盘行为不一致。
        """
        # 兼容: 优先从market_monitor导入, fallback到listener(旧路径)
        try:
            from .emotion_cycle import emotion_cycle_manager
        except ImportError:
            from ..listener.strategies.emotion_cycle import emotion_cycle_manager
        
        # 构建limit_stocks dict供emotion_cycle使用
        limit_stocks = {}
        if realtime_data and len(realtime_data) > 100:
            for code, data in realtime_data.items():
                pct = data.get("pct_chg", 0)
                if isinstance(pct, (int, float)):
                    if pct >= 9.5:
                        limit_stocks[code] = {"limit_type": "U"}
                    elif pct <= -9.5:
                        limit_stocks[code] = {"limit_type": "D"}
        
        try:
            emotion = await emotion_cycle_manager.calculate_daily_emotion(
                trade_date, limit_stocks
            )
            score = emotion.score
            phase = emotion.phase.value
            ratio = emotion.position_multiplier
        except Exception as e:
            logger.warning(f"[L3] emotion_cycle调用失败, fallback简化计算: {e}")
            # Fallback: 简化计算
            limit_up = sum(1 for v in limit_stocks.values() if v.get("limit_type") == "U")
            limit_down = sum(1 for v in limit_stocks.values() if v.get("limit_type") == "D")
            score = (limit_up - limit_down) + 50
            score = max(0, min(100, score))
            phase = "rising" if score > 70 else ("chaos" if score >= 40 else "bearish")
            ratio = 1.0 if score > 70 else (0.5 if score >= 40 else 0.25)

        return ratio, score, phase
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

    @staticmethod
    def _calc_opening_pct(ts_code: str, realtime_data: Dict) -> Optional[float]:
        """从实时数据获取开盘涨幅【v2.9.62提取】"""
        if not realtime_data or ts_code not in realtime_data:
            return None
        rd = realtime_data[ts_code]
        opening_pct = rd.get("opening_pct_chg", None)
        if opening_pct is None:
            # 从open和pre_close计算
            op = rd.get("open", 0)
            pc = rd.get("pre_close", 0)
            if op and pc and pc > 0:
                opening_pct = (op - pc) / pc * 100
        return opening_pct

    @staticmethod
    def _check_auction_pass(strategy: str, opening_pct: float) -> bool:
        """按策略差异化判断竞价过滤【v2.9.62提取】

        首板打板: 需竞价强势(2%~7%)
        其他策略: 仅排除极端(>-7%或<-5%)
        """
        if strategy in ("first_limit_up",):
            # 首板打板: 需竞价强势(≥2%)且非一字板(<7%)
            if opening_pct < 2 or opening_pct > 7:
                return False
        else:
            # 半路追涨/跌停翘板/龙头低吸: 仅排除极端
            if opening_pct > 7 or opening_pct < -5:
                return False
        return True

    async def _auction_filter(
        self, candidates: List[Dict], trade_date: str, realtime_data: Dict = None
    ) -> List[Dict]:
        """竞价过滤（实盘优势层！）

        回测只能用opening_pct_chg近似，实盘可获取9:25真实竞价数据

        实盘逻辑:
        1. 9:25后获取竞价涨幅（=开盘价/昨收-1）
        2. 排除极端: 高开>7%（追高风险）/ 低开<-5%（可能有风险）
        3. 策略差异化:
           - 首板打板: 需竞价强势(≥2%) → 排除低开
           - 半路追涨: 不要求竞价强势 → 保留正常区间
        【v2.9.62重构: 提取_calc_opening_pct+_check_auction_pass】
        """
        filtered = []

        for c in candidates:
            strategy = c.get("strategy", "")
            ts_code = c.get("ts_code", "")

            opening_pct = self._calc_opening_pct(ts_code, realtime_data)
            if opening_pct is None:
                filtered.append(c)  # 无竞价数据保留
                continue

            if not self._check_auction_pass(strategy, opening_pct):
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
        except Exception as _e:
            return None

    def get_sentiment_info(self) -> Dict:
        """获取当前情绪状态（供外部查询）"""
        return {
            "score": self._sentiment_score,
            "period": self._sentiment_period,
        }

    @staticmethod
    def merge_filter_result(signals, result) -> list:
        """将filter_pipeline结果合并回ScanSignal【v2.9.28:从scanner提取】"""
        candidate_map = {c["ts_code"]: c for c in result.candidates}
        filtered_signals = []
        for s in signals:
            if s.ts_code in candidate_map:
                # 注入9层筛选决策详情
                s.decision_detail = {
                    "filter_pipeline": {
                        "layers_applied": result.layers_applied,
                        "layer_details": result.layer_details,
                        "position_ratio": result.position_ratio,
                        "action": result.action,
                    },
                    "signal_reason": s.reason,
                    "strategy": s.strategy,
                    "strategy_name": s.strategy_name,
                    "price": s.price,
                    "pct_chg": s.pct_chg,
                    "volume_ratio": s.volume_ratio,
                    "turnover_rate": s.turnover_rate,
                    "factors": s.factors,
                    "scan_time": s.scan_time,
                }
                # 逐层trace
                for layer_name, detail in result.layer_details.items():
                    s.layer_trace[layer_name] = {
                        "detail": detail,
                        "applied": result.layers_applied.get(layer_name, False),
                    }
                s.layer_trace["L8_position"] = {
                    "position_ratio": result.position_ratio,
                    "action": result.action,
                }
                filtered_signals.append(s)
            else:
                # 被过滤掉的信号
                s.signal_status = "filtered"
                s.layer_trace["filter_result"] = {
                    "filtered_out": True,
                    "reason": "9层筛选管道过滤",
                    "layer_details": result.layer_details,
                }
        return filtered_signals
