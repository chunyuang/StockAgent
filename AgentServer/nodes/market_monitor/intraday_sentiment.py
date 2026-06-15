#!/usr/bin/env python3
"""盘中实时情绪计算器 — 7维公式

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
    """盘中实时情绪计算器 — 7维公式, 每次scan调用"""
    
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
    ) -> IntradayEmotionScore:
        """
        计算盘中实时情绪 — 每次scan_loop调用一次
        
        Args:
            trade_date: 交易日期 YYYYMMDD
            realtime_data: 实时行情 dict, key=ts_code, value={pct_chg, ...}
        
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
                # 曾涨停但开板: 通过盘中最高价判断
                # 如果没有最高价, 用涨幅>5%作为曾涨停的代理(粗糙但可用)
                high_pct = data.get("high_pct", pct)  # 部分数据源有high_pct
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
        7维加权情绪得分 — 满分100
        
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
            except Exception:
                pass
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
            except Exception:
                pass
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
            
            pipeline = [
                {"$match": {"trade_date": int(trade_date), "is_limit_up": True}},
                {"$group": {"_id": None, "max_limit": {"$max": "$limit_times"}}}
            ]
            result = await mongo_manager.aggregate(C.LIMIT_LIST, pipeline)
            if result and result[0].get("max_limit"):
                return result[0]["max_limit"]
        except Exception as e:
            logger.debug(f"[INTRA-EMO] max_continue查询失败, fallback估算: {e}")
        
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
        except Exception:
            pass
        
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
        except Exception:
            pass
        
        return 0.0


# 全局单例 — 在scanner进程内复用, 保持_prev_up_down_ratio状态
intraday_calculator = IntradaySentimentCalculator()
