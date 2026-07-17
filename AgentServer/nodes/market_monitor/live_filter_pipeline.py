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

import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK

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
    turnover_rate: float = 0.0   # 换手率因子(v2.9.84)
    vol_ratio: float = 0.0       # 量比因子(v2.9.84)
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
        self._last_intraday_dimensions = None  # v2.9.95: 盘中7维明细

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

        # ── v2.9.95: L3详情文本(包含公式标识) ────────
        intra_dims = getattr(self, '_last_intraday_dimensions', None)
        formula_tag = "7dim盘中" if intra_dims else "5dim盘后"
        result.layer_details["L3_sentiment"] = (
            f"情绪={score:.0f}分→{period}, 仓位系数={sentiment_ratio:.0%}"
            + (f", 过滤半路追涨{l3_drop_count}只(冰点<40分暂停)" if l3_drop_count else "")
            + f" | 公式: {formula_tag} | 高潮≥70→100% / 分化55-70→70% / 震荡40-55→50% / 冰点<40→25%"
        )
        
        # ── v2.9.95: L3_sentiment_data结构化扩展 ────────
        # 旧: 仅{score, period, position_ratio, l3_drop_count} 4字段
        # 新: 增加7个维度字段, 前端直接读取不再正则解析文本
        l3_data = {
            "score": round(score, 1),
            "period": period,
            "position_ratio": round(sentiment_ratio, 3),
            "l3_drop_count": l3_drop_count,
            "formula": "7dim" if intra_dims else "5dim",
        }
        
        if intra_dims:
            # 盘中7维: 直接从IntradaySentimentCalculator获取全部维度
            l3_data.update({
                "limit_up": intra_dims.get("limit_up", 0),
                "limit_down": intra_dims.get("limit_down", 0),
                "up_down_ratio": intra_dims.get("up_down_ratio", 0),
                "momentum": intra_dims.get("momentum", 0),
                "broken": intra_dims.get("broken", 0),
                "broken_rate": intra_dims.get("broken_rate", 0),
                "today_premium": intra_dims.get("today_premium", 0),
            })
        else:
            # 盘后5维: 从EmotionCycleManager结果中提取可用的维度
            l3_data.update({
                "limit_up": 0,    # 盘后模式无实时数据, 设为0(前端用sentiment_scores补)
                "limit_down": 0,
                "up_down_ratio": 0,
                "momentum": 0,
                "broken": 0,
                "broken_rate": 0,
                "today_premium": 0,
            })
        
        result.layer_details["L3_sentiment_data"] = l3_data
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
            # 【v2.9.123】L1强制空仓时仍计算情绪, 保证sentiment_live_log持续更新
            if realtime_data and len(realtime_data) > 0:
                try:
                    sentiment_ratio, score, period = await self._calc_sentiment(trade_date, realtime_data)
                    self._sentiment_score = score
                    self._sentiment_period = period
                except Exception as _e:
                    logger.debug(f"[L1] 强制空仓后情绪计算失败(非致命): {_e}")
            return result

        # ---- L2~L8: 筛选层应用 ----
        ratio = await self._apply_filter_layers(result, trade_date, realtime_data, ratio)

        # ---- L8: 仓位控制 ----
        # 【v2.9.92w】从strategy_defaults读取默认值(与回测对齐)
        max_position_ratio = self._config.get("max_total_position", GLOBAL_RISK.get("max_total_position", 0.75))
        max_per_stock = self._config.get("max_position_per_stock", GLOBAL_RISK.get("max_position_per_stock", 0.35))
        final_ratio = min(ratio, max_position_ratio)
        
        # 【v2.9.92w】冷却期检查(强制空仓后N天内仓位上限)
        cooldown_info = getattr(self._scanner, '_cooldown_info', {})
        if cooldown_info and cooldown_info.get('trigger_date'):
            from datetime import datetime
            try:
                trigger = datetime.strptime(cooldown_info['trigger_date'], '%Y%m%d')
                cooldown_days = cooldown_info.get('cooldown_days', 2)
                cooldown_cap = cooldown_info.get('position_cap', 0.6)
                now = datetime.now()
                days_since = (now - trigger).days
                if days_since <= cooldown_days * 2:  # 粗略：日历天≤2×交易日
                    if cooldown_info.get('block_new_buys') or cooldown_cap <= 0:
                        result.candidates = []
                        result.position_ratio = 0
                        # 【v2.9.100修复】标记所有trace_candidates为rejected
                        for t in result.trace_candidates:
                            t.final_status = "rejected"
                            t.final_rejection_layer = "L8_cooldown"
                            t.final_rejection_reason = f"竞价风险防守期禁止新开仓: {cooldown_info.get('reason', '')}"
                            t.layer_results["L8_cooldown"] = {"passed": False, "reason": t.final_rejection_reason}
                        self._build_trace_summary(result)
                        result.layer_details["L8_cooldown"] = f"🧊 {cooldown_info.get('risk_level','风险')}防守期: 禁止新开仓({cooldown_info.get('reason','')})"
                        logger.warning(f"[FILTER] 🧊 竞价风险防守期: 禁止新开仓 reason={cooldown_info.get('reason','')}")
                        return result
                    final_ratio = min(final_ratio, cooldown_cap)
                    result.layer_details["L8_cooldown"] = f"🧊 冷却期({days_since}天/{cooldown_days}交易日) 仓位上限{cooldown_cap*100:.0f}%"
                    logger.info(f"[FILTER] 🧊 冷却期生效: 仓位上限{cooldown_cap*100:.0f}%")
            except (ValueError, TypeError):
                pass
        
        # 【v2.9.92x】A8: 大盘MA60过滤(与回测对齐)
        # 大盘跌破MA60 → 仓位×0.5
        enable_ma60 = self._config.get("enable_ma60_filter", True)
        if enable_ma60:
            try:
                from core.managers import mongo_manager
                if mongo_manager.is_initialized:
                    # 查询上证指数最近60天close
                    index_docs = await mongo_manager.find_many(
                        "index_daily",
                        {"ts_code": "000001.SH"},
                        {"_id": 0, "close": 1, "trade_date": 1},
                        sort=[("trade_date", -1)],
                        limit=60
                    )
                    if index_docs and len(index_docs) >= 20:
                        index_docs.sort(key=lambda x: x.get("trade_date", 0))
                        close_list = [d["close"] for d in index_docs]
                        ma60 = sum(close_list) / len(close_list)
                        current_close = close_list[-1]
                        if current_close < ma60:
                            final_ratio = final_ratio * 0.5
                            result.layer_details["L8_ma60"] = f"📉 大盘跌破MA60(MA60={ma60:.0f}, 当前={current_close:.0f}), 仓位×0.5"
                            logger.info(f"[FILTER] 📉 大盘跌破MA60: MA60={ma60:.0f}, 当前={current_close:.0f}, 仓位×0.5")
                        else:
                            result.layer_details["L8_ma60"] = f"📈 大盘在MA60之上({current_close:.0f}>{ma60:.0f})"
            except Exception as e:
                logger.debug(f"[FILTER] MA60检查异常: {e}")
        
        result.position_ratio = final_ratio
        result.layers_applied["L8_position"] = True
        
        # 【v2.9.127】大盘环境过滤: 应用circuit_breaker的position_cap
        if self._scanner and hasattr(self._scanner, '_circuit_breaker'):
            cb = self._scanner._circuit_breaker or {}
            cap = cb.get("position_cap", 1.0)
            if cap < 1.0:
                result.position_ratio = result.position_ratio * cap
                if cap == 0.0:
                    result.candidates = []
                    for t in result.trace_candidates:
                        if t.final_status != "rejected":
                            t.final_status = "rejected"
                            t.final_rejection_layer = "L8_market_risk"
                            t.final_rejection_reason = f"大盘环境过滤: {cb.get('buy_pause_reason', '')}"
                    cap_reason = cb.get('buy_pause_reason', '大盘环境过滤')
                    result.layer_details["L8_market_risk"] = f"🛑 {cap_reason}, 禁止新开仓"
                    logger.warning(f"[L8] 大盘环境过滤: {cap_reason}, position_cap=0, 禁止买入")
                else:
                    result.layer_details["L8_market_risk"] = f"⚠️ 大盘环境过滤: 仓位上限={cap:.0%}"
                    logger.info(f"[L8] 大盘环境过滤: position_cap={cap:.0%}, ratio {final_ratio:.2f}->{result.position_ratio:.2f}")
        result.layer_details["L8_position"] = (
            f"总仓位上限={final_ratio:.0%} (情绪×特殊={ratio:.0%}, 硬上限{max_position_ratio:.0%}), "
            f"单票上限={max_per_stock:.0%} | 仓位系数=min(情绪仓位, 特殊时期, 硬上限)"
        )
        # 【v2.9.121修复】L8正常路径也需标记trace_candidates, 否则_build_trace_summary中
        # L8: passed=0, rejected=0, input=N, output=N — 前端漏斗图缺失L8通过数据
        for t in result.trace_candidates:
            if t.final_status != "rejected":
                t.layer_results["L8_position"] = {"passed": True}

        # 【V50.1】最终标记通过 + 构建汇总
        self._finalize_traces(result)

        return result

    @staticmethod
    def _describe_special_period(special_ratio: float, reason: str) -> str:
        """生成L2特殊时期层详细描述【v2.9.63提取@staticmethod】"""
        if special_ratio < 1.0:
            return f"⚠️ {reason} → 仓位系数={special_ratio:.0%} (正常100%, 月末30%, 周五70%)"
        return "✅ 非特殊时期 → 仓位系数=100% (无月末/季末/年末/节前效应)"

    def _mark_layer_passed(self, result: FilterResult, layer_name: str) -> None:
        """标记筛选层通过(所有未拒绝候选)【v2.9.63提取】"""
        for t in result.trace_candidates:
            if t.final_status != "rejected":
                t.layer_results[layer_name] = {"passed": True}

    async def _apply_filter_layers(
        self, result: FilterResult, trade_date: str,
        realtime_data: Dict, ratio: float
    ) -> float:
        """应用L2~L7筛选层, 返回仓位系数【v2.9.63: L2描述+标记通过提取子方法】"""
        # ---- L2: 特殊时期 ----
        if self._layer_enabled["L2_special_period"]:
            special_ratio, reason = self._check_special_period(trade_date)
            result.layers_applied["L2_special_period"] = True
            ratio *= special_ratio
            result.layer_details["L2_special_period"] = self._describe_special_period(special_ratio, reason)
            self._mark_layer_passed(result, "L2_special_period")

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
        self._mark_layer_passed(result, "L6_strategy")

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
        """最终标记候选通过/拒绝状态+构建汇总【v2.9.61:从apply提取, v2.9.90:L9标记通过】"""
        passed_ids = {c["ts_code"] for c in result.candidates}
        for t in result.trace_candidates:
            if t.final_status == "pending":
                if t.ts_code in passed_ids:
                    t.final_status = "passed"
                    # L9_execute: 管道外由MarketScanner执行, 此处默认标记通过
                    t.layer_results["L9_execute"] = {"passed": True, "reason": "管道筛选通过, 待执行"}
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
                turnover_rate=c.get("turnover_rate", 0) or c.get("turn", 0) or 0,
                vol_ratio=c.get("vol_ratio", 0) or 0,
            ))

    def _record_layer_drop(self, result, layer, dropped_ids, reason_fn) -> None:
        """记录某层被淘汰的候选
        
        【v2.9.80修复】用trace_candidates查找原始候选数据，
        不再从result.candidates(已过滤)中查找，避免dropped候选找不到reason。
        """
        if not dropped_ids:
            for t in result.trace_candidates:
                if t.final_status != "rejected":
                    t.layer_results[layer] = {"passed": True}
            return
        # 从trace_candidates中查找(包含所有原始候选，不会被过滤)
        for t in result.trace_candidates:
            if t.ts_code in dropped_ids and t.final_status != "rejected":
                # 构造候选数据供reason_fn使用
                original = {"ts_code": t.ts_code, "stock_name": t.stock_name,
                            "strategy": t.strategy, "strategy_name": t.strategy_name}
                reason = reason_fn(original)
                t.layer_results[layer] = {"passed": False, "reason": reason}
                t.final_status = "rejected"
                t.final_rejection_layer = layer
                t.final_rejection_reason = reason
            elif t.final_status != "rejected":
                t.layer_results[layer] = {"passed": True}

    def _premarket_reject_reason(self, c) -> str:
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
        return "未知原因"

    def _build_trace_summary(self, result) -> Dict:
        """构建追踪汇总 — 正确追踪每层的输入/输出/淘汰
        
        【v2.9.80修复】每层的input=上次仍存活的候选数(非之前层的rejected)。
        淘汰层(L1/L3冰点/L4/L5/L7): 部分passed, 部分rejected
        仓位调整层(L2/L3非冰点/L6/L8): 全部passed, 0 rejected
        【v2.9.90修复】层级列表与_fix_funnel_summary对齐, 加入L9_execute(默认output=input)
        """
        layers = ["L1_force_empty", "L2_special_period", "L3_sentiment",
                   "L4_premarket", "L5_auction", "L6_strategy",
                   "L7_ranking", "L8_position", "L9_execute"]
        
        prev_output = len(result.trace_candidates)
        for layer in layers:
            passed = sum(1 for t in result.trace_candidates
                        if t.layer_results.get(layer, {}).get("passed") is True)
            rejected = sum(1 for t in result.trace_candidates
                          if t.layer_results.get(layer, {}).get("passed") is False)
            # 本层input = 上一层output(仍在存活且未在前序层被reject的)
            # 本层只处理之前仍alive的候选
            input_count = prev_output
            output = prev_output - rejected
            result.trace_summary[layer] = {
                "total": passed + rejected,
                "passed": passed,
                "rejected": rejected,
                "input": input_count,
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
        
        【2026-07-06修复】按板块区分涨跌停阈值, 与intraday_sentiment保持一致。
        之前统一用9.5%导致创业板/科创板(-9.5%~-19.5%)被误算为跌停,
        虚高~27只, 误触强制空仓。
        
        Returns: (limit_up_count, limit_down_count, index_drop_pct)
        """
        limit_up_count = 0
        limit_down_count = 0
        from .utils.board_limit import is_limit_up, is_limit_down
        for code, data in realtime_data.items():
            pct = data.get("pct_chg", 0)
            if not isinstance(pct, (int, float)):
                continue
            if is_limit_up(code, pct):
                limit_up_count += 1
            elif is_limit_down(code, pct):
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
                    {"ts_code": 1, "pct_chg": 1, "_id": 0}
                )
                from .utils.board_limit import is_limit_up, is_limit_down
                async for doc in cursor:
                    pct = doc.get("pct_chg", 0)
                    code = doc.get("ts_code", "")
                    if is_limit_up(code, pct):
                        limit_up_count += 1
                    elif is_limit_down(code, pct):
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
        
        【v2.9.95重构】三级策略:
        1. 盘中(有realtime_data>100只): 使用IntradaySentimentCalculator 7维公式
        2. 盘后/历史: 使用EmotionCycleManager 5维公式
        3. 异常fallback: 简化公式(涨停-跌停+50)
        
        旧问题: 盘中也走EmotionCycleManager, 其3/5维度全天固定(zt_premium/
        max_continue/up_down_ratio读历史数据), 导致盘中score/period几乎不变。
        6/12全天2413个点全走fallback→score仅57-61, period永远是differentiation。
        """
        # ── 优先级1: 盘中7维实时公式 ────────────────────
        if realtime_data and len(realtime_data) > 100:
            try:
                from .intraday_sentiment import intraday_calculator
                # 获取limit_list数据用于炸板判断
                # 【v2.9.123修复】limit_list盘中不更新导致broken=0, 增加scanner._limit_pools作为补充
                limit_list_data = None
                try:
                    from core.managers import mongo_manager
                    if mongo_manager.is_initialized:
                        trade_date_int = int(trade_date.replace('-', '')) if isinstance(trade_date, str) else trade_date
                        limit_list_data = {}
                        async for doc in mongo_manager.db["limit_list"].find({"trade_date": trade_date_int}):
                            limit_list_data[doc.get("ts_code", "")] = doc
                except Exception:
                    pass
                # 【v2.9.123】补充scanner实时涨停池数据(limit_list盘中不写MongoDB)
                scanner = getattr(self, '_scanner', None)
                if scanner:
                    limit_pools = getattr(scanner, '_limit_pools', None) or {}
                    for item in limit_pools.get("limit_up", []):
                        code = item.get("ts_code", "")
                        if code and code not in limit_list_data:
                            limit_list_data[code] = item
                    for item in limit_pools.get("limit_down", []):
                        code = item.get("ts_code", "")
                        if code and code not in limit_list_data:
                            limit_list_data[code] = item
                    for item in limit_pools.get("broken", []):
                        code = item.get("ts_code", "")
                        if code and code not in limit_list_data:
                            limit_list_data[code] = {**item, "open_times": 1}
                result = await intraday_calculator.calculate(trade_date, realtime_data, limit_list_data=limit_list_data)
                # 保存维度明细供_apply_L3_sentiment写入L3_sentiment_data
                self._last_intraday_dimensions = result.dimensions
                return result.position_ratio, result.score, result.period_en
            except Exception as e:
                logger.error(f"[L3] IntradaySentimentCalculator失败: {e}", exc_info=True)
                # 不直接fallback到简化公式, 先试EmotionCycleManager
        
        # ── 优先级2: EmotionCycleManager 5维公式 ──────
        self._last_intraday_dimensions = None  # 标记非盘中模式
        
        from .emotion_cycle import emotion_cycle_manager
        from .utils.board_limit import is_limit_up, is_limit_down
        limit_stocks = {}
        if realtime_data and len(realtime_data) > 100:
            for code, data in realtime_data.items():
                pct = data.get("pct_chg", 0)
                if isinstance(pct, (int, float)):
                    if is_limit_up(code, pct):
                        limit_stocks[code] = {"limit_type": "U", "pct_chg": pct}
                    elif is_limit_down(code, pct):
                        limit_stocks[code] = {"limit_type": "D", "pct_chg": pct}
                    else:
                        limit_stocks[code] = {"limit_type": "normal", "pct_chg": pct}
        
        try:
            emotion = await emotion_cycle_manager.calculate_daily_emotion(
                trade_date, limit_stocks
            )
            score = emotion.score
            phase = emotion.phase.value
            ratio = emotion.position_multiplier
            # 【v2.9.123】fallback路径也persist到live_log
            await _persist_fallback_live_log(trade_date, score, phase, limit_stocks, realtime_data)
            return ratio, score, phase
        except Exception as e:
            logger.error(f"[L3] EmotionCycleManager失败, fallback简化: {e}", exc_info=True)
        
        # ── 优先级3: 简化fallback(最后手段) ───────────
        limit_up = sum(1 for v in limit_stocks.values() if v.get("limit_type") == "U")
        limit_down = sum(1 for v in limit_stocks.values() if v.get("limit_type") == "D")
        score = (limit_up - limit_down) + 50
        score = max(0, min(100, score))
        
        from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK
        spm = GLOBAL_RISK.get("sentiment_position_map", {})
        try:
            from nodes.web.api.strategy_config import _override_global_risk, _overrides_loaded
            if _overrides_loaded and _override_global_risk:
                override_spm = _override_global_risk.get("sentiment_position_map", {})
                if override_spm:
                    spm = {**spm, **override_spm}
        except Exception as _e:
            logger.debug(f"[GUARD] live_filter_pipeline: {_e}")
        if score >= 70:
            phase, ratio = "rising", spm.get("rising", 1.0)
        elif score >= 55:
            phase, ratio = "differentiation", spm.get("differentiation", 0.7)
        elif score >= 40:
            phase, ratio = "chaos", spm.get("chaos", 0.5)
        else:
            phase, ratio = "bearish", spm.get("bearish", 0.3)
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

            # 排除次新(上市<60天)
            # 【v2.9.89修复】从factors或realtime中获取list_date判断次新
            # 无list_date时按代码规则: 688/300开头次新波动大, 保守排除上市<30天
            factors = c.get("factors", {}) or {}
            list_date = factors.get("list_date", "")
            if list_date and isinstance(list_date, str) and len(list_date) == 8:
                try:
                    from datetime import datetime as _dt
                    list_dt = _dt.strptime(list_date, "%Y%m%d")
                    days_since_list = (_dt.now() - list_dt).days
                    if days_since_list < 60:
                        continue
                except (ValueError, TypeError):
                    pass
            # 无list_date时: 北交所(8/9开头.BJ)次新波动大, 跳过
            elif ts_code and ts_code[0] in ("8", "9") and ts_code.endswith(".BJ"):
                continue

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
        except Exception:
            return None

    def get_sentiment_info(self) -> Dict:
        """获取当前情绪状态（供外部查询）"""
        info = {
            "score": self._sentiment_score,
            "period": self._sentiment_period,
        }
        # 【v2.9.104】盘中7维明细同时暴露给scanner持久化，避免只写score/period导致复盘维度缺失
        if self._last_intraday_dimensions:
            info["dimensions"] = dict(self._last_intraday_dimensions)
            info["formula"] = "7dim"
        return info

    @staticmethod
    def merge_filter_result(signals, result) -> list:
        """将filter_pipeline结果合并回ScanSignal【v2.9.28:从scanner提取, v2.9.99:注入逐候选trace+修复L8重复】"""
        candidate_map = {c["ts_code"]: c for c in result.candidates}
        # 构建逐候选trace映射: ts_code -> CandidateTrace
        trace_map = {t.ts_code: t for t in result.trace_candidates} if result.trace_candidates else {}
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
                # 逐层trace(从layer_details构建, L8已包含在内)
                for layer_name, detail in result.layer_details.items():
                    s.layer_trace[layer_name] = {
                        "detail": detail,
                        "applied": result.layers_applied.get(layer_name, False),
                    }
                # 仓位信息补充到L8(仅当L8未被layer_details覆盖时)
                if "L8_position" not in result.layer_details:
                    s.layer_trace["L8_position"] = {
                        "position_ratio": result.position_ratio,
                        "action": result.action,
                    }
                # 注入逐候选trace: 每层通过/拒绝状态
                ct = trace_map.get(s.ts_code)
                if ct and ct.layer_results:
                    s.layer_trace["candidate_trace"] = {
                        layer: lr for layer, lr in ct.layer_results.items()
                    }
                filtered_signals.append(s)
            else:
                # 被过滤掉的信号
                s.signal_status = "filtered"
                # 注入被拒候选的trace信息(含具体拒绝层和原因)
                ct = trace_map.get(s.ts_code)
                s.layer_trace["filter_result"] = {
                    "filtered_out": True,
                    "reason": "9层筛选管道过滤",
                    "layer_details": result.layer_details,
                    "rejection_layer": ct.final_rejection_layer if ct else "",
                    "rejection_reason": ct.final_rejection_reason if ct else "",
                }
                if ct and ct.layer_results:
                    s.layer_trace["candidate_trace"] = {
                        layer: lr for layer, lr in ct.layer_results.items()
                    }
        return filtered_signals


async def _persist_fallback_live_log(trade_date, score, phase, limit_stocks, realtime_data):
    """【v2.9.123】fallback路径(EmotionCycleManager)也persist到sentiment_live_log
    
    解决: 13:00后午休结束首次scan可能realtime_data不足100条,
    走fallback而非7dim -> live_log无新记录 -> 前端看不到情绪更新。
    """
    try:
        from datetime import datetime
        from .intraday_sentiment import _persist_live_log_entry
        from .utils.board_limit import is_limit_up, is_limit_down
        
        limit_up = sum(1 for v in limit_stocks.values() if v.get("limit_type") == "U")
        limit_down = sum(1 for v in limit_stocks.values() if v.get("limit_type") == "D")
        up_count = sum(1 for v in limit_stocks.values() if v.get("pct_chg", 0) > 0) if limit_stocks else 0
        down_count = sum(1 for v in limit_stocks.values() if v.get("pct_chg", 0) < 0) if limit_stocks else 0
        total_active = up_count + down_count
        up_down_ratio = up_count / max(total_active, 1) if total_active > 0 else 0.5
        
        # phase中文映射
        phase_map = {
            "rising": ("rising", "高潮"),
            "differentiation": ("differentiation", "分化"),
            "chaos": ("chaos", "震荡"),
            "bearish": ("bearish", "冰点"),
        }
        phase_en, phase_cn = phase_map.get(phase, (phase, phase))
        
        # 仓位系数
        from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK
        spm = GLOBAL_RISK.get("sentiment_position_map", {})
        if score >= 70:
            ratio = spm.get("rising", 1.0)
        elif score >= 55:
            ratio = spm.get("differentiation", 0.7)
        elif score >= 40:
            ratio = spm.get("chaos", 0.5)
        else:
            ratio = spm.get("bearish", 0.3)
        
        entry = {
            'time': datetime.now().strftime('%H:%M:%S'),
            'trade_date': trade_date,
            'score': round(score, 1),
            'phase': phase_en,
            'phase_label': phase_cn,
            'position_ratio': ratio,
            'limit_up': limit_up,
            'limit_down': limit_down,
            'max_continue': 1,
            'up_down_ratio': round(up_down_ratio, 3),
            'zt_premium': 0.0,
            'broken': 0,
            'broken_rate': 0.0,
            'momentum': 0.0,
            'formula': '5dim_fallback',
            'breakdown': {
                'limit_up_score': min(20, limit_up),
                'limit_down_score': max(0, 15 - limit_down * 1.5),
                'up_down_score': round(up_down_ratio * 15, 1),
                'momentum_score': 0.0,
                'broken_score': 10.0,
                'max_continue_score': 1.5,
                'zt_premium_score': 0.0,
            },
        }
        await _persist_live_log_entry(entry)
    except Exception as _e:
        logger.debug(f"[GUARD] _persist_fallback_live_log: {_e}")
