#!/usr/bin/env python3
"""盘中实时情绪计算器 - 7维公式

v2.9.95: 替代盘中fallback公式, 新增2个动态维度:
  - 涨跌加速度(momentum): 当前vs上一次采样的涨跌比变化率
  - 涨停开板率(broken_rate): 炸板数/曾涨停数

维度对照(7维 vs 原盘后5维):
  维度              权重   盘中变化   来源
  ────────────────────────────────────────────────
  1. 涨停数量        20分   ✅动态    realtime_data ≥9.5%
  2. 跌停数量        15分   ✅动态    realtime_data ≤-9.5%
  3. 涨跌家数比      15分   ✅动态    realtime_data pct_chg
  4. 涨跌加速度      10分   ✅动态    当前vs上次涨跌比差 ← NEW
  5. 涨停开板率      10分   ✅动态    炸板/曾涨停         ← NEW
  6. 最高连板高度    10分   ⏸首次固定 limit_list缓存
  7. 昨日涨停溢价    10分   ⏸首次固定 zt_premium缓存
  8. 今日涨停溢价    10分   ✅动态    今日涨停股当前涨幅均值
  ────────────────────────────────────────────────
  合计              100分   动态占60分

与盘后5维公式(_compute_score)的映射:
  盘后5维: zu(30) + zd(20) + lb(20) + ud(15) + premium(15) = 100
  盘中7维: zu(20) + zd(15) + ud(15) + momentum(10) + broken(10) + lb(10) + premium(10+10) = 100

  权重重新分配原因:
  - 盘中涨停数波动大(开盘涨停少→盘中增加), 降低权重避免跳变
  - 新增momentum/broken_rate更能反映盘中情绪转向
  - 连板高度和溢价率在盘中基本不变, 降低权重
"""

import logging
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class IntradayEmotionScore:
    """盘中情绪得分结果"""
    score: float
    period: str          # 中文: 高潮/分化/震荡/冰点
    period_en: str       # 英文: rising/differentiation/chaos/bearish
    position_ratio: float
    # 7维明细
    dimensions: Dict[str, Any] = field(default_factory=dict)


class IntradaySentimentCalculator:
    """盘中实时情绪计算器 - 7维公式, 每次scan调用"""

    def __init__(self):
        self._prev_up_down_ratio: Optional[float] = None
        self._static_cache: Dict[str, Any] = {}  # 当日静态维度缓存
        self._cached_trade_date: Optional[str] = None
        self._sample_count: int = 0

    def reset_for_new_day(self):
        """新交易日重置状态"""
        self._prev_up_down_ratio = None
        self._static_cache = {}
        self._cached_trade_date = None
        self._sample_count = 0

    async def calculate(
        self,
        trade_date: str,
        realtime_data: Dict[str, Dict],
        limit_list_data: Optional[Dict[str, Dict]] = None,
    ) -> IntradayEmotionScore:
        """
        计算盘中实时情绪 — 每次scan_loop调用一次

        Args:
            trade_date: 交易日期 YYYYMMDD
            realtime_data: 实时行情 dict, key=ts_code, value={pct_chg, ...}
            limit_list_data: 涨跌停数据 dict, key=ts_code, value={open_times, limit, ...} (optional)

        Returns:
            IntradayEmotionScore with score/period/dimensions
        """
        # 新交易日自动重置
        if trade_date != self._cached_trade_date:
            self.reset_for_new_day()
            self._cached_trade_date = trade_date

        self._sample_count += 1

        # ── 动态维度 ──────────────────────────────────

        # 1. 涨停/跌停/炸板计数
        limit_up = 0
        limit_down = 0
        broken = 0  # 曾涨停但当前已开板(pct在0~9.5%之间)
        limit_up_codes = []  # 当前仍在涨停的股票
        for code, data in realtime_data.items():
            pct = data.get("pct_chg", 0)
            if not isinstance(pct, (int, float)):
                continue

            # 涨停判断: 创业板/科创板≥19.5%, 主板≥9.5%, 北交所≥29.5%
            code_prefix = code[:3] if '.' not in code else code.split('.')[0][:3]
            if code_prefix in ('688', '30'):
                lu_thresh, ld_thresh = 19.5, -19.5
            elif code_prefix in ('8', '4') and code[:1] in ('8', '4'):
                lu_thresh, ld_thresh = 29.5, -29.5
            else:
                lu_thresh, ld_thresh = 9.5, -9.5

            if pct >= lu_thresh:
                limit_up += 1
                limit_up_codes.append(code)
            elif pct <= ld_thresh:
                limit_down += 1
            elif 0 < pct < lu_thresh:
                # 曾涨停但开板: 优先用limit_list的open_times判断
                if limit_list_data:
                    ll = limit_list_data.get(code)
                    if ll and ll.get('open_times', 0) > 0 and ll.get('limit') == 'U':
                        broken += 1
                else:
                    # fallback: 用盘中最高价判断
                    high_pct = data.get("high_pct", pct)
                    if high_pct >= lu_thresh:
                        broken += 1

        # 2. 涨跌家数比
        up_count = sum(1 for d in realtime_data.values()
                       if isinstance(d.get("pct_chg"), (int, float)) and d["pct_chg"] > 0)
        down_count = sum(1 for d in realtime_data.values()
                         if isinstance(d.get("pct_chg"), (int, float)) and d["pct_chg"] < 0)
        flat_count = sum(1 for d in realtime_data.values()
                         if isinstance(d.get("pct_chg"), (int, float)) and d["pct_chg"] == 0)
        total_active = up_count + down_count
        up_down_ratio = up_count / max(total_active, 1)

        # 3. 涨跌加速度(momentum): 与上一次采样比较
        momentum = 0.0
        if self._prev_up_down_ratio is not None:
            momentum = up_down_ratio - self._prev_up_down_ratio
        self._prev_up_down_ratio = up_down_ratio

        # 4. 涨停开板率
        total_ever_limit = limit_up + broken
        broken_rate = broken / max(total_ever_limit, 1)

        # 5. 今日涨停溢价: 当前涨停股的平均涨幅(超涨停线的部分)
        today_premium = 0.0
        if limit_up_codes:
            premiums = []
            for code in limit_up_codes:
                d = realtime_data.get(code, {})
                pct = d.get("pct_chg", 0)
                if isinstance(pct, (int, float)):
                    # 溢价 = 涨幅 - 涨停线 (如10.02% - 10% = 0.02%)
                    code_prefix = code[:3] if '.' not in code else code.split('.')[0][:3]
                    if code_prefix in ('688', '30'):
                        base = 20.0
                    elif code_prefix in ('8', '4') and code[:1] in ('8', '4'):
                        base = 30.0
                    else:
                        base = 10.0
                    premiums.append(pct - base)
            if premiums:
                today_premium = sum(premiums) / len(premiums)

        # ── 静态维度(首采缓存) ────────────────────────

        if 'max_continue' not in self._static_cache:
            max_continue = await self._fetch_max_continue(trade_date, limit_up)
            zt_premium = await self._fetch_zt_premium(trade_date)
            self._static_cache['max_continue'] = max_continue
            self._static_cache['zt_premium'] = zt_premium

        max_continue = self._static_cache['max_continue']
        zt_premium = self._static_cache['zt_premium']

        # ── 7维加权计算 ────────────────────────────────

        score = self._compute_7dim_score(
            limit_up=limit_up,
            limit_down=limit_down,
            up_down_ratio=up_down_ratio,
            momentum=momentum,
            broken_rate=broken_rate,
            max_continue=max_continue,
            zt_premium=zt_premium,
            today_premium=today_premium,
        )

        period_en, period_cn, position_ratio = self._score_to_phase(score)

        dimensions = {
            "limit_up": limit_up,
            "limit_down": limit_down,
            "up_count": up_count,
            "down_count": down_count,
            "up_down_ratio": round(up_down_ratio, 3),
            "momentum": round(momentum, 4),
            "broken": broken,
            "broken_rate": round(broken_rate, 3),
            "max_continue": max_continue,
            "zt_premium": round(zt_premium, 1),
            "today_premium": round(today_premium, 2),
            "sample_count": self._sample_count,
            "formula": "7dim",
        }

        logger.debug(
            f"[INTRA-EMO] {trade_date} #{self._sample_count}: "
            f"score={score:.1f}→{period_cn} | "
            f"zu={limit_up} zd={limit_down} broken={broken} "
            f"udr={up_down_ratio:.2f} mom={momentum:+.3f} "
            f"lb={max_continue} ztp={zt_premium:.1f} tp={today_premium:.2f}"
        )

        # 【v2.9.96h】记录盘中实时计算到全局 _compute_log供前端读取
        # 【v2.9.106】同时持久化到 MongoDB sentiment_live_log 集合
        try:
            from datetime import datetime
            from .emotion_cycle import emotion_cycle_manager
            broken_rate_calc = (broken / max(limit_up + broken, 1)) * 100 if (limit_up + broken) > 0 else 0.0
            # 7维拆解按 _compute_7dim_score 的权重分配还原
            d1 = min(20, limit_up)              # 涨停数量 20分
            d2 = max(0, 15 - limit_down * 1.5)  # 跌停数量 15分
            d3 = round(up_down_ratio * 15, 1)    # 涨跌比 15分
            d4 = max(-5, min(10, momentum * 100))  # 动量 10分
            d5 = max(0, 10 - broken_rate_calc / 5)  # 炸板率 10分
            d6 = min(15, max_continue * 1.5)    # 连板高度 15分
            d7 = min(15, max(0, today_premium * 3))  # 当日溢价 15分
            now = datetime.now()
            entry = {
                'time': now.strftime('%H:%M:%S'),
                'trade_date': trade_date,
                'score': round(score, 1),
                'phase': period_en,
                'phase_label': period_cn,
                'position_ratio': position_ratio,
                'limit_up': limit_up, 'limit_down': limit_down,
                'max_continue': max_continue,
                'up_down_ratio': round(up_down_ratio, 3),
                'zt_premium': round(today_premium, 2),  # 今日溢价(与 UI 一致)
                'broken': broken,
                'broken_rate': round(broken_rate_calc, 1),
                'momentum': round(momentum, 4),
                'formula': '7dim',
                # 7维拆解
                'breakdown': {
                    'limit_up_score': round(d1, 1),
                    'limit_down_score': round(d2, 1),
                    'up_down_score': round(d3, 1),
                    'momentum_score': round(d4, 1),
                    'broken_score': round(d5, 1),
                    'max_continue_score': round(d6, 1),
                    'zt_premium_score': round(d7, 1),
                },
            }
            emotion_cycle_manager._compute_log.append(entry)
            # 【v2.9.106】同步持久化 (fire-and-forget, 不阻塞主流程)
            try:
                import asyncio as _asyncio
                _asyncio.create_task(_persist_live_log_entry(entry, now))
            except Exception as _pe:
                logger.debug(f"[GUARD] intraday_sentiment persist: {_pe}")
        except Exception as _e:
            logger.debug(f"[GUARD] intraday_sentiment: {_e}")

        return IntradayEmotionScore(
            score=score,
            period=period_cn,
            period_en=period_en,
            position_ratio=position_ratio,
            dimensions=dimensions,
        )

    def _compute_7dim_score(
        self,
        limit_up: int,
        limit_down: int,
        up_down_ratio: float,
        momentum: float,
        broken_rate: float,
        max_continue: int,
        zt_premium: float,
        today_premium: float,
    ) -> float:
        """
        7维加权情绪得分 - 满分100

        D1: 涨停数量     0~20分  (每1个涨停1分, 20个满分)
        D2: 跌停数量     0~15分  (0个跌停满分, 每个扣1.5分)
        D3: 涨跌家数比   0~15分  (上涨比例×15)
        D4: 涨跌加速度   -5~10分 (上涨加速给正分, 下跌加速扣分)
        D5: 涨停开板率   0~10分  (开板率越低越好)
        D6: 最高连板     0~10分  (每板1分, 10板满分)
        D7: 昨日涨停溢价 0~5分   (溢价每1%给1分, 满分5)
        D8: 今日涨停溢价 0~5分   (溢价每1%给1分, 满分5)
        """
        # D1: 涨停数量 (20分)
        d1 = min(20, limit_up)

        # D2: 跌停数量 (15分)
        d2 = max(0, 15 - limit_down * 1.5)

        # D3: 涨跌家数比 (15分)
        d3 = up_down_ratio * 15

        # D4: 涨跌加速度 (10分)
        # momentum ∈ [-0.3, +0.3] 典型范围
        # 正加速(涨跌比上升) → 加分, 负加速 → 扣分
        # 归一化: ±0.1 → ±5分, ±0.2 → ±10分
        d4 = max(-5, min(10, momentum * 50))

        # D5: 涨停开板率 (10分)
        # broken_rate=0 → 10分(封板率100%), broken_rate=1 → 0分
        d5 = (1 - broken_rate) * 10

        # D6: 最高连板高度 (10分)
        d6 = min(10, max_continue * 1.0)

        # D7: 昨日涨停溢价 (5分)
        d7 = min(5, max(0, zt_premium))

        # D8: 今日涨停溢价 (5分)
        d8 = min(5, max(0, today_premium * 5))  # today_premium通常<1%, 放大5倍

        total = d1 + d2 + d3 + d4 + d5 + d6 + d7 + d8

        return min(100, max(0, total))

    def _score_to_phase(self, score: float) -> Tuple[str, str, float]:
        """得分→情绪阶段+仓位系数

        Returns: (period_en, period_cn, position_ratio)
        """
        # 阈值从strategy_defaults读取(与EmotionCycleManager.THRESHOLD对齐)
        try:
            from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK
            th = GLOBAL_RISK.get("sentiment_thresholds",
                                  {"rising": 70, "differentiation": 55, "chaos": 40})
            # 优先运行时覆盖
            try:
                from nodes.web.api.strategy_config import _override_global_risk, _overrides_loaded
                if _overrides_loaded and _override_global_risk:
                    override_th = _override_global_risk.get("sentiment_thresholds", {})
                    if override_th:
                        th = {**th, **override_th}
            except Exception as _e:
                logger.debug(f"[GUARD] intraday_sentiment: {_e}")
        except Exception:
            th = {"rising": 70, "differentiation": 55, "chaos": 40}

        # 仓位系数从strategy_defaults读取
        try:
            from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK
            spm = GLOBAL_RISK.get("sentiment_position_map", {
                "rising": 1.0, "differentiation": 0.7, "chaos": 0.5, "bearish": 0.3
            })
            try:
                from nodes.web.api.strategy_config import _override_global_risk, _overrides_loaded
                if _overrides_loaded and _override_global_risk:
                    override_spm = _override_global_risk.get("sentiment_position_map", {})
                    if override_spm:
                        spm = {**spm, **override_spm}
            except Exception as _e:
                logger.debug(f"[GUARD] intraday_sentiment: {_e}")
        except Exception:
            spm = {"rising": 1.0, "differentiation": 0.7, "chaos": 0.5, "bearish": 0.3}

        if score >= th["rising"]:
            return "rising", "高潮", spm.get("rising", 1.0)
        elif score >= th["differentiation"]:
            return "differentiation", "分化", spm.get("differentiation", 0.7)
        elif score >= th["chaos"]:
            return "chaos", "震荡", spm.get("chaos", 0.5)
        else:
            return "bearish", "冰点", spm.get("bearish", 0.3)

    async def _fetch_max_continue(self, trade_date: str, limit_up: int) -> int:
        """获取最高连板高度(首次从MongoDB读, 后续用缓存)"""
        try:
            from core.managers import mongo_manager
            from nodes.market_monitor.constants import C
            if not mongo_manager.is_initialized:
                return max(1, min(10, limit_up // 5 + 1))

            from nodes.web.api.scanner_system import _enrich_limit_times_from_history, _trade_date_match
            docs = await mongo_manager.db[C.LIMIT_LIST].find(
                {"trade_date": _trade_date_match(trade_date), "$or": [{"is_limit_up": True}, {"limit": "U"}]},
                {"_id": 0, "ts_code": 1, "limit_times": 1, "limit": 1, "is_limit_up": 1},
            ).to_list(length=None)
            docs = await _enrich_limit_times_from_history(mongo_manager.db, trade_date, docs)
            max_limit = max((int(d.get("limit_times") or 0) for d in docs), default=0)
            if max_limit:
                return max_limit
        except Exception as e:
            logger.debug(f"[INTRA-EMO] max_continue查询/反推失败, fallback估算: {e}")

        # Fallback: 根据涨停数量估算
        return max(1, min(10, limit_up // 5 + 1))

    async def _fetch_zt_premium(self, trade_date: str) -> float:
        """获取昨日涨停溢价(首次从MongoDB读, 后续用缓存)"""
        try:
            from .emotion_cycle import EmotionCycleManager
            return await EmotionCycleManager._fetch_zt_premium_for_update(
                mongo_manager.db if mongo_manager.is_initialized else None,
                int(trade_date)
            ) if mongo_manager.is_initialized else 0.0
        except Exception as _e:
            logger.debug(f"[GUARD] intraday_sentiment: {_e}")

        # Fallback: 直接读sentiment_scores的zt_premium
        try:
            from core.managers import mongo_manager
            if mongo_manager.is_initialized:
                doc = await mongo_manager.db["sentiment_scores"].find_one(
                    {"trade_date": int(trade_date)},
                    {"zt_premium": 1}
                )
                if doc and doc.get("zt_premium"):
                    return doc["zt_premium"]
        except Exception as _e:
            logger.debug(f"[GUARD] intraday_sentiment: {_e}")

        return 0.0


# 全局单例 - 在scanner进程内复用, 保持_prev_up_down_ratio状态
intraday_calculator = IntradaySentimentCalculator()


# 【v2.9.106】sentiment_live_log 持久化状态 - 避免重复创建索引
_LIVE_LOG_INDEX_CREATED = False


async def _ensure_live_log_indexes() -> None:
    """创建 sentiment_live_log 集合的索引 - 进程内只跑一次"""
    global _LIVE_LOG_INDEX_CREATED
    if _LIVE_LOG_INDEX_CREATED:
        return
    try:
        from core.managers import mongo_manager
        if not mongo_manager.is_initialized:
            return
        col = mongo_manager.db["sentiment_live_log"]
        # 按 trade_date 倒序 / scan_time 倒序 联合索引,主查询"今日最近 N 条"
        await col.create_index([("trade_date", -1), ("ts", -1)], background=True)
        # TTL: ts 超过 7 天自动清理 (避免无限增长)
        await col.create_index("ts", expireAfterSeconds=7 * 24 * 3600, background=True)
        _LIVE_LOG_INDEX_CREATED = True
        logger.info("[INTRA-EMO] sentiment_live_log 索引已创建 (TTL=7天)")
    except Exception as _e:
        logger.warning(f"[INTRA-EMO] sentiment_live_log 索引创建失败: {_e}")


async def _persist_live_log_entry(entry: dict, now=None) -> None:
    """【v2.9.106】把盘中情绪计算条目写入 sentiment_live_log 集合。

    调用者:intraday_sentiment.calculate 与 emotion_cycle.calculate_daily_emotion。
    不阻塞主流程,出错只记录 debug 日志。
    """
    try:
        from core.managers import mongo_manager
        from datetime import datetime as _dt
        if not mongo_manager.is_initialized:
            return
        await _ensure_live_log_indexes()
        ts = now or _dt.now()
        # trade_date 统一为 int。入参可能是 '20260626' / 20260626 / '2026-06-26'
        td = entry.get('trade_date')
        try:
            td_int = int(str(td).replace('-', '')) if td is not None else None
        except Exception:
            td_int = None
        doc = dict(entry)
        if td_int is not None:
            doc['trade_date'] = td_int
        doc['scan_time'] = ts.strftime('%Y-%m-%d %H:%M:%S')
        doc['ts'] = ts
        # 默认 formula 代表来源 (7dim / 5dim)
        doc.setdefault('formula', '7dim')
        await mongo_manager.db["sentiment_live_log"].insert_one(doc)
    except Exception as _e:
        logger.debug(f"[GUARD] persist_live_log: {_e}")
