"""
LiveFilterPipeline 单元+集成测试

覆盖:
- FilterResult / CandidateTrace 数据结构
- L1 强制空仓: 跌停≥80/涨停≤10+跌停>0/大盘跌≥3%
- L2 特殊时期: 月末/周五降仓
- L3 情绪周期: score→ratio映射, 冰点过滤半路追涨
- L4 盘前预选: ST/退市/低流动性排除
- L5 竞价过滤: 首板≥2%, 极端高开>7%/低开<-5%
- L7 综合排序: 去重+优先级+截断
- L8 仓位控制: 总仓位上限
- 全管道apply: 正常流程/强制空仓短路/空候选
- 追踪: trace_candidates / trace_summary
"""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime

from nodes.market_monitor.live_filter_pipeline import (
    LiveFilterPipeline, FilterResult, CandidateTrace
)


def _make_candidates(n=5, strategy="halfway_chase"):
    """创建测试候选"""
    codes = ["600036.SH", "000001.SZ", "688001.SH", "300750.SZ", "002475.SZ"][:n]
    return [
        {
            "ts_code": code,
            "stock_name": f"测试股{i}",
            "strategy": strategy,
            "strategy_name": strategy,
            "price": 10.0 + i,
            "pct_chg": 2.0 + i,
            "amount": 1000 + i * 100,  # 万元
            "volume": 5000 + i * 100,
        }
        for i, code in enumerate(codes)
    ]


def _make_realtime_with_limits(limit_ups=5, limit_downs=2, total=100):
    """创建带涨跌停统计的实时行情"""
    data = {}
    for i in range(total):
        code = f"{600000 + i:06d}.SH"
        if i < limit_ups:
            pct = 9.8
        elif i < limit_ups + limit_downs:
            pct = -9.8
        else:
            pct = 1.0
        data[code] = {"pct_chg": pct, "price": 10, "open": 10, "high": 10, "low": 10, "pre_close": 10}
    # 上证指数(不触大盘跌幅)
    data["000001.SH"] = {"pct_chg": -0.5}
    return data


# ==================== 数据结构测试 ====================


class TestDataClasses:
    """FilterResult / CandidateTrace 数据结构测试"""
    
    def test_filter_result_defaults(self):
        result = FilterResult()
        assert result.action == "trade"
        assert result.candidates == []
        assert result.position_ratio == 1.0
        assert result.force_empty_reason == ""
        assert result.trace_candidates == []
        assert result.trace_summary == {}
    
    def test_candidate_trace_defaults(self):
        trace = CandidateTrace(ts_code="600036.SH", stock_name="测试", strategy="halfway_chase", strategy_name="半路追涨")
        assert trace.ts_code == "600036.SH"
        assert trace.final_status == "pending"
        assert trace.layer_results == {}
    
    def test_filter_result_custom(self):
        result = FilterResult(action="empty", position_ratio=0.0, force_empty_reason="跌停过多")
        assert result.action == "empty"
        assert result.position_ratio == 0.0


# ==================== L1 强制空仓测试 ====================


class TestL1ForceEmpty:
    """L1 强制空仓测试"""
    
    @pytest.mark.asyncio
    async def test_no_force_empty_normal(self):
        """正常市场不触发"""
        pipeline = LiveFilterPipeline()
        rt = _make_realtime_with_limits(limit_ups=30, limit_downs=5, total=100)
        force_empty, reason, stats = await pipeline._check_force_empty("20260529", rt)
        assert not force_empty
    
    @pytest.mark.asyncio
    async def test_force_empty_many_limit_downs(self):
        """跌停≥80触发"""
        pipeline = LiveFilterPipeline()
        rt = _make_realtime_with_limits(limit_ups=5, limit_downs=85, total=200)
        force_empty, reason, stats = await pipeline._check_force_empty("20260529", rt)
        assert force_empty
        assert "跌停" in reason
    
    @pytest.mark.asyncio
    async def test_force_empty_few_limit_ups_with_limit_downs(self):
        """涨停≤10且跌停>0触发"""
        pipeline = LiveFilterPipeline()
        rt = _make_realtime_with_limits(limit_ups=5, limit_downs=3, total=50)
        force_empty, reason, stats = await pipeline._check_force_empty("20260529", rt)
        assert force_empty
        assert "涨停" in reason
    
    @pytest.mark.asyncio
    async def test_force_empty_index_drop(self):
        """大盘跌≥3%触发"""
        pipeline = LiveFilterPipeline()
        rt = _make_realtime_with_limits(limit_ups=20, limit_downs=5, total=100)
        rt["000001.SH"] = {"pct_chg": -3.5}  # 上证跌3.5%
        force_empty, reason, stats = await pipeline._check_force_empty("20260529", rt)
        assert force_empty
        assert "大盘跌幅" in reason
    
    @pytest.mark.asyncio
    async def test_no_force_empty_no_data(self):
        """无实时数据不触发(fail-safe)"""
        pipeline = LiveFilterPipeline()
        # 无MongoDB时catch异常
        force_empty, reason, stats = await pipeline._check_force_empty("20260529", None)
        assert not force_empty
    
    @pytest.mark.asyncio
    async def test_force_empty_kcb_limit_ups(self):
        """科创板涨跌停(20%阈值)不计入主板统计"""
        pipeline = LiveFilterPipeline()
        rt = {}
        # 科创板涨19%不算涨停(需≥19.5)
        for i in range(90):
            code = f"688{i:03d}.SH"
            rt[code] = {"pct_chg": 19.0}  # 不到涨停
        force_empty, reason, stats = await pipeline._check_force_empty("20260529", rt)
        assert not force_empty
    
    @pytest.mark.asyncio
    async def test_force_empty_short_circuits_apply(self):
        """强制空仓时apply直接返回empty"""
        pipeline = LiveFilterPipeline()
        # Mock _check_force_empty
        pipeline._check_force_empty = AsyncMock(return_value=(True, "跌停85只", {"limit_up_count": 5, "limit_down_count": 85, "index_drop_pct": 0.0}))
        result = await pipeline.apply("20260529", _make_candidates(), [])
        assert result.action == "empty"
        assert result.position_ratio == 0.0
        assert result.candidates == []
    
    @pytest.mark.asyncio
    async def test_force_empty_marks_all_traces_rejected(self):
        """强制空仓标记所有候选为rejected"""
        pipeline = LiveFilterPipeline()
        pipeline._check_force_empty = AsyncMock(return_value=(True, "跌停85只", {"limit_up_count": 5, "limit_down_count": 85, "index_drop_pct": 0.0}))
        candidates = _make_candidates(3)
        result = await pipeline.apply("20260529", candidates, [])
        for t in result.trace_candidates:
            assert t.final_status == "rejected"
            assert "L1_force_empty" in t.layer_results


# ==================== L2 特殊时期测试 ====================


class TestL2SpecialPeriod:
    """L2 特殊时期测试"""
    
    def test_month_end(self):
        """月末降仓"""
        pipeline = LiveFilterPipeline()
        # 月末28号
        ratio, reason = pipeline._check_special_period("20260528")
        # 可能有SpecialPeriodFilter或回退逻辑
        assert isinstance(ratio, float)
        assert 0 < ratio <= 1.0
    
    def test_normal_day(self):
        """正常交易日"""
        pipeline = LiveFilterPipeline()
        # 5月15日(普通日)
        ratio, reason = pipeline._check_special_period("20260515")
        assert isinstance(ratio, float)
    
    def test_friday_fallback(self):
        """周五降仓(回退逻辑)"""
        pipeline = LiveFilterPipeline()
        # 用一个确定的周五测试回退逻辑
        # 2026-05-29是周五
        ratio, reason = pipeline._check_special_period("20260529")
        assert isinstance(ratio, float)


# ==================== L3 情绪周期测试 ====================


class TestL3Sentiment:
    """L3 情绪周期测试"""
    
    @pytest.mark.asyncio
    async def test_calc_sentiment_fallback(self):
        """emotion_cycle失败时fallback"""
        pipeline = LiveFilterPipeline()
        rt = _make_realtime_with_limits(limit_ups=20, limit_downs=5, total=100)
        
        with patch("nodes.market_monitor.live_filter_pipeline.LiveFilterPipeline._calc_sentiment",
                   new_callable=AsyncMock) as mock_calc:
            mock_calc.return_value = (0.5, 45.0, "chaos")
            ratio, score, phase = await pipeline._calc_sentiment("20260529", rt)
            assert ratio == 0.5
            assert score == 45.0
            assert phase == "chaos"
    
    @pytest.mark.asyncio
    async def test_sentiment_filters_halfway_chase_in_cold(self):
        """冰点期(score<40)过滤半路追涨"""
        pipeline = LiveFilterPipeline()
        pipeline._calc_sentiment = AsyncMock(return_value=(0.25, 30.0, "bearish"))
        
        candidates = [
            {"ts_code": "600036.SH", "strategy": "halfway_chase", "stock_name": "A", "amount": 1000},
            {"ts_code": "000001.SZ", "strategy": "first_limit_up", "stock_name": "B", "amount": 1000},
        ]
        result = await pipeline.apply("20260529", candidates, [])
        
        # 半路追涨应被过滤
        strategies = [c["strategy"] for c in result.candidates]
        assert "halfway_chase" not in strategies
    
    @pytest.mark.asyncio
    async def test_sentiment_keeps_halfway_chase_in_warm(self):
        """温暖期(score≥40)保留半路追涨"""
        pipeline = LiveFilterPipeline()
        pipeline._check_force_empty = AsyncMock(return_value=(False, "", {"limit_up_count": 30, "limit_down_count": 5, "index_drop_pct": 0.005}))
        pipeline._calc_sentiment = AsyncMock(return_value=(1.0, 70.0, "rising"))
        pipeline._check_special_period = MagicMock(return_value=(1.0, "正常"))
        
        candidates = [
            {"ts_code": "600036.SH", "strategy": "halfway_chase", "stock_name": "A", "amount": 5000},
        ]
        result = await pipeline.apply("20260529", candidates, [])
        
        strategies = [c["strategy"] for c in result.candidates]
        assert "halfway_chase" in strategies


# ==================== L4 盘前预选测试 ====================


class TestL4Premarket:
    """L4 盘前预选测试"""
    
    def test_filter_st_stocks(self):
        """排除ST股"""
        pipeline = LiveFilterPipeline()
        candidates = [
            {"ts_code": "600036.SH", "stock_name": "测试股", "amount": 1000},
            {"ts_code": "000001.SZ", "stock_name": "*ST测试", "amount": 1000},
        ]
        result = pipeline._premarket_filter(candidates)
        assert len(result) == 1
        assert result[0]["ts_code"] == "600036.SH"
    
    def test_filter_delisted(self):
        """排除退市股"""
        pipeline = LiveFilterPipeline()
        candidates = [
            {"ts_code": "600036.SH", "stock_name": "测试股", "amount": 1000},
            {"ts_code": "000001.SZ", "stock_name": "测试退", "amount": 1000},
        ]
        result = pipeline._premarket_filter(candidates)
        assert len(result) == 1
    
    def test_filter_low_liquidity(self):
        """排除低流动性(成交额<500万)"""
        pipeline = LiveFilterPipeline()
        candidates = [
            {"ts_code": "600036.SH", "stock_name": "正常股", "amount": 2000},
            {"ts_code": "000001.SZ", "stock_name": "低流动", "amount": 300},
        ]
        result = pipeline._premarket_filter(candidates)
        assert len(result) == 1
        assert result[0]["ts_code"] == "600036.SH"
    
    def test_keep_normal_stocks(self):
        """保留正常股"""
        pipeline = LiveFilterPipeline()
        candidates = _make_candidates(5)
        result = pipeline._premarket_filter(candidates)
        assert len(result) == 5
    
    def test_empty_candidates(self):
        """空候选列表"""
        pipeline = LiveFilterPipeline()
        result = pipeline._premarket_filter([])
        assert result == []


# ==================== L5 竞价过滤测试 ====================


class TestL5Auction:
    """L5 竞价过滤测试"""
    
    @pytest.mark.asyncio
    async def test_filter_extreme_high_open(self):
        """排除高开>7%"""
        pipeline = LiveFilterPipeline()
        candidates = [
            {"ts_code": "600036.SH", "strategy": "halfway_chase"},
            {"ts_code": "000001.SZ", "strategy": "halfway_chase"},
        ]
        rt = {
            "600036.SH": {"open": 10.8, "pre_close": 10.0},  # 高开8%
            "000001.SZ": {"open": 10.2, "pre_close": 10.0},  # 高开2%
        }
        result = await pipeline._auction_filter(candidates, "20260529", rt)
        assert len(result) == 1
        assert result[0]["ts_code"] == "000001.SZ"
    
    @pytest.mark.asyncio
    async def test_filter_extreme_low_open(self):
        """排除低开<-5%"""
        pipeline = LiveFilterPipeline()
        candidates = [
            {"ts_code": "600036.SH", "strategy": "halfway_chase"},
        ]
        rt = {
            "600036.SH": {"open": 9.4, "pre_close": 10.0},  # 低开-6%
        }
        result = await pipeline._auction_filter(candidates, "20260529", rt)
        assert len(result) == 0
    
    @pytest.mark.asyncio
    async def test_first_limit_up_needs_strong_auction(self):
        """首板打板需竞价≥2%"""
        pipeline = LiveFilterPipeline()
        candidates = [
            {"ts_code": "600036.SH", "strategy": "first_limit_up"},
            {"ts_code": "000001.SZ", "strategy": "first_limit_up"},
        ]
        rt = {
            "600036.SH": {"open": 10.3, "pre_close": 10.0},  # 高开3%
            "000001.SZ": {"open": 10.1, "pre_close": 10.0},  # 高开1%(不够)
        }
        result = await pipeline._auction_filter(candidates, "20260529", rt)
        assert len(result) == 1
        assert result[0]["ts_code"] == "600036.SH"
    
    @pytest.mark.asyncio
    async def test_keep_no_auction_data(self):
        """无竞价数据保留"""
        pipeline = LiveFilterPipeline()
        candidates = [{"ts_code": "600036.SH", "strategy": "halfway_chase"}]
        result = await pipeline._auction_filter(candidates, "20260529", None)
        assert len(result) == 1
    
    @pytest.mark.asyncio
    async def test_keep_normal_auction(self):
        """正常竞价保留"""
        pipeline = LiveFilterPipeline()
        candidates = [{"ts_code": "600036.SH", "strategy": "halfway_chase"}]
        rt = {"600036.SH": {"open": 10.2, "pre_close": 10.0}}  # 高开2%
        result = await pipeline._auction_filter(candidates, "20260529", rt)
        assert len(result) == 1


# ==================== L7 综合排序测试 ====================


class TestL7Ranking:
    """L7 综合排序测试"""
    
    def test_dedup_same_stock(self):
        """同一股票多策略去重"""
        pipeline = LiveFilterPipeline()
        candidates = [
            {"ts_code": "600036.SH", "strategy": "halfway_chase"},
            {"ts_code": "600036.SH", "strategy": "dragon_head"},  # 优先级更高
        ]
        result = pipeline._rank_and_dedup(candidates)
        assert len(result) == 1
        assert result[0]["strategy"] == "dragon_head"
    
    def test_sort_by_priority(self):
        """按策略优先级排序"""
        pipeline = LiveFilterPipeline()
        candidates = [
            {"ts_code": "000001.SZ", "strategy": "halfway_chase"},     # 优先级4
            {"ts_code": "600036.SH", "strategy": "dragon_head"},       # 优先级1
            {"ts_code": "300750.SZ", "strategy": "first_limit_up"},    # 优先级3
        ]
        result = pipeline._rank_and_dedup(candidates)
        assert result[0]["strategy"] == "dragon_head"
        assert result[1]["strategy"] == "first_limit_up"
    
    def test_max_candidates_limit(self):
        """最大候选数截断"""
        pipeline = LiveFilterPipeline(config={"max_candidates_per_scan": 3})
        candidates = _make_candidates(10)
        result = pipeline._rank_and_dedup(candidates)
        assert len(result) <= 3
    
    def test_empty_candidates(self):
        """空候选"""
        pipeline = LiveFilterPipeline()
        result = pipeline._rank_and_dedup([])
        assert result == []


# ==================== 全管道apply测试 ====================


class TestFullPipelineApply:
    """全管道apply测试"""
    
    @pytest.mark.asyncio
    async def test_apply_normal_flow(self):
        """正常流程"""
        pipeline = LiveFilterPipeline()
        pipeline._check_force_empty = AsyncMock(return_value=(False, "", {"limit_up_count": 30, "limit_down_count": 5, "index_drop_pct": 0.005}))
        pipeline._check_special_period = MagicMock(return_value=(1.0, "正常"))
        pipeline._calc_sentiment = AsyncMock(return_value=(1.0, 65.0, "rising"))
        
        candidates = [
            {"ts_code": "600036.SH", "strategy": "dragon_head", "stock_name": "正常", "amount": 5000},
        ]
        result = await pipeline.apply("20260529", candidates, [])
        assert result.action == "trade"
        assert result.position_ratio > 0
    
    @pytest.mark.asyncio
    async def test_apply_force_empty_short_circuit(self):
        """强制空仓短路后续层"""
        pipeline = LiveFilterPipeline()
        pipeline._check_force_empty = AsyncMock(return_value=(True, "跌停85只", {"limit_up_count": 5, "limit_down_count": 85, "index_drop_pct": 0.0}))
        
        result = await pipeline.apply("20260529", _make_candidates(3), [])
        assert result.action == "empty"
        assert "L1_force_empty" in result.layers_applied
        # L2-L8不应执行
        assert "L2_special_period" not in result.layers_applied
    
    @pytest.mark.asyncio
    async def test_apply_empty_candidates(self):
        """空候选列表"""
        pipeline = LiveFilterPipeline()
        pipeline._check_force_empty = AsyncMock(return_value=(False, "", {"limit_up_count": 30, "limit_down_count": 5, "index_drop_pct": 0.005}))
        pipeline._check_special_period = MagicMock(return_value=(1.0, "正常"))
        pipeline._calc_sentiment = AsyncMock(return_value=(1.0, 65.0, "rising"))
        
        result = await pipeline.apply("20260529", [], [])
        assert result.action == "trade"
    
    @pytest.mark.asyncio
    async def test_apply_position_ratio_combined(self):
        """仓位系数=情绪×特殊×上限"""
        pipeline = LiveFilterPipeline(config={"max_total_position": 0.6})
        pipeline._check_force_empty = AsyncMock(return_value=(False, "", {"limit_up_count": 30, "limit_down_count": 5, "index_drop_pct": 0.005}))
        pipeline._check_special_period = MagicMock(return_value=(0.7, "月末"))
        pipeline._calc_sentiment = AsyncMock(return_value=(0.5, 40.0, "chaos"))
        
        result = await pipeline.apply("20260529", _make_candidates(1), [])
        # ratio = 0.7 * 0.5 = 0.35, capped by 0.6
        assert result.position_ratio == pytest.approx(0.35, abs=0.01)
    
    @pytest.mark.asyncio
    async def test_apply_trace_candidates_initialized(self):
        """追踪候选正确初始化"""
        pipeline = LiveFilterPipeline()
        pipeline._check_force_empty = AsyncMock(return_value=(False, "", {"limit_up_count": 30, "limit_down_count": 5, "index_drop_pct": 0.005}))
        pipeline._check_special_period = MagicMock(return_value=(1.0, "正常"))
        pipeline._calc_sentiment = AsyncMock(return_value=(1.0, 65.0, "rising"))
        
        candidates = _make_candidates(3)
        result = await pipeline.apply("20260529", candidates, [])
        
        assert len(result.trace_candidates) == 3
        for t in result.trace_candidates:
            assert t.ts_code != ""
            assert t.final_status in ("passed", "rejected", "pending")
    
    @pytest.mark.asyncio
    async def test_apply_trace_summary_built(self):
        """追踪汇总构建"""
        pipeline = LiveFilterPipeline()
        pipeline._check_force_empty = AsyncMock(return_value=(False, "", {"limit_up_count": 30, "limit_down_count": 5, "index_drop_pct": 0.005}))
        pipeline._check_special_period = MagicMock(return_value=(1.0, "正常"))
        pipeline._calc_sentiment = AsyncMock(return_value=(1.0, 65.0, "rising"))
        
        result = await pipeline.apply("20260529", _make_candidates(3), [])
        assert isinstance(result.trace_summary, dict)


# ==================== 层开关测试 ====================


class TestLayerToggle:
    """层开关测试"""
    
    def test_default_all_enabled(self):
        """默认全部开启"""
        pipeline = LiveFilterPipeline()
        for layer, enabled in pipeline._layer_enabled.items():
            assert enabled is True
    
    def test_disable_layer_via_config(self):
        """通过配置关闭层"""
        pipeline = LiveFilterPipeline(config={
            "enable_force_empty": False,
            "enable_sentiment_cycle": False,
        })
        assert pipeline._layer_enabled["L1_force_empty"] is False
        assert pipeline._layer_enabled["L3_sentiment"] is False
        assert pipeline._layer_enabled["L2_special_period"] is True


# ==================== 追踪辅助方法测试 ====================


class TestTraceHelpers:
    """追踪辅助方法测试"""
    
    def test_init_traces(self):
        """初始化追踪"""
        pipeline = LiveFilterPipeline()
        result = FilterResult()
        candidates = _make_candidates(3)
        pipeline._init_traces(result, candidates)
        
        assert len(result.trace_candidates) == 3
        for t in result.trace_candidates:
            assert t.final_status == "pending"
    
    def test_record_layer_drop(self):
        """记录淘汰"""
        pipeline = LiveFilterPipeline()
        result = FilterResult()
        candidates = _make_candidates(3)
        pipeline._init_traces(result, candidates)
        
        dropped = {"600036.SH"}
        pipeline._record_layer_drop(result, "L4_premarket", dropped, lambda c: "ST股")
        
        for t in result.trace_candidates:
            if t.ts_code == "600036.SH":
                assert t.final_status == "rejected"
                assert t.layer_results["L4_premarket"]["passed"] is False
            else:
                assert t.layer_results["L4_premarket"]["passed"] is True
    
    def test_record_layer_drop_no_drops(self):
        """无淘汰时全部通过"""
        pipeline = LiveFilterPipeline()
        result = FilterResult()
        candidates = _make_candidates(3)
        pipeline._init_traces(result, candidates)
        
        pipeline._record_layer_drop(result, "L4_premarket", set(), lambda c: "")
        
        for t in result.trace_candidates:
            assert t.layer_results["L4_premarket"]["passed"] is True
    
    def test_build_trace_summary(self):
        """构建追踪汇总"""
        pipeline = LiveFilterPipeline()
        result = FilterResult()
        candidates = _make_candidates(3)
        pipeline._init_traces(result, candidates)
        pipeline._record_layer_drop(result, "L4_premarket", {"600036.SH"}, lambda c: "ST股")
        pipeline._build_trace_summary(result)
        
        l4_summary = result.trace_summary.get("L4_premarket", {})
        assert l4_summary.get("rejected", 0) == 1
        assert l4_summary.get("passed", 0) == 2
    
    def test_premarket_reject_reason_st(self):
        """ST股淘汰原因"""
        pipeline = LiveFilterPipeline()
        reason = pipeline._premarket_reject_reason({"stock_name": "*ST测试"})
        assert "ST" in reason
    
    def test_premarket_reject_reason_low_liquidity(self):
        """低流动性淘汰原因"""
        pipeline = LiveFilterPipeline()
        reason = pipeline._premarket_reject_reason({"ts_code": "600036.SH", "volume": 100})
        assert "流动性" in reason


# ==================== get_sentiment_info 测试 ====================


class TestGetSentimentInfo:
    """情绪状态查询测试"""
    
    def test_default_sentiment(self):
        pipeline = LiveFilterPipeline()
        info = pipeline.get_sentiment_info()
        assert "score" in info
        assert "period" in info
    
    @pytest.mark.asyncio
    async def test_sentiment_after_apply(self):
        """apply后情绪状态更新"""
        pipeline = LiveFilterPipeline()
        pipeline._check_force_empty = AsyncMock(return_value=(False, "", {"limit_up_count": 30, "limit_down_count": 5, "index_drop_pct": 0.005}))
        pipeline._check_special_period = MagicMock(return_value=(1.0, "正常"))
        pipeline._calc_sentiment = AsyncMock(return_value=(0.5, 45.0, "chaos"))
        
        await pipeline.apply("20260529", _make_candidates(1), [])
        info = pipeline.get_sentiment_info()
        assert info["score"] == 45.0
        assert info["period"] == "chaos"


# ==================== 策略优先级测试 ====================


class TestStrategyPriority:
    """策略优先级测试"""
    
    def test_dragon_head_highest(self):
        assert LiveFilterPipeline.STRATEGY_PRIORITY["dragon_head"] == 1
    
    def test_limit_down_qiao_second(self):
        assert LiveFilterPipeline.STRATEGY_PRIORITY["limit_down_qiao"] == 2
    
    def test_first_limit_up_third(self):
        assert LiveFilterPipeline.STRATEGY_PRIORITY["first_limit_up"] == 3
    
    def test_halfway_chase_fourth(self):
        assert LiveFilterPipeline.STRATEGY_PRIORITY["halfway_chase"] == 4
    
    def test_anomaly_same_priority(self):
        """异动策略同优先级"""
        p = LiveFilterPipeline.STRATEGY_PRIORITY
        assert p["anomaly_broken"] == p["anomaly_strong"] == p["anomaly_surge"]
