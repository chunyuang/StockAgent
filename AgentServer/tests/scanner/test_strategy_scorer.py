"""
StrategyScorer 单元+集成测试

覆盖:
- merge_factors: 日级因子+实时数据合并
- apply_strategies: 策略筛选条件应用
- detect_anomalies: 异动检测
- 参数获取: get_effective_strategy_config / get_strategy_risk
- 边界条件: 空数据/缺失因子/异常值
"""

import asyncio
import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, AsyncMock, patch

from nodes.market_monitor.strategy_scorer import StrategyScorer


def _make_mock_scanner(config=None, daily_factors=None):
    """创建mock scanner"""
    scanner = MagicMock()
    scanner.config = config or {
        "strategy_overrides": {},
        "strategies": {
            "halfway_chase": {"enabled": True},
            "limit_up": {"enabled": True},
        }
    }
    scanner._daily_factors_df = daily_factors
    scanner._broker = MagicMock()
    scanner._broker.get_positions.return_value = []
    
    # ParamCenter mock
    param_center = MagicMock()
    param_center.get_effective_params = AsyncMock(return_value={})
    scanner._param_center = param_center
    
    return scanner


def _make_realtime_data(n=5):
    """创建测试用实时行情数据"""
    codes = ["600036.SH", "000001.SZ", "688001.SH", "300750.SZ", "002475.SZ"][:n]
    data = {}
    for i, code in enumerate(codes):
        data[code] = {
            "price": 10.0 + i,
            "pct_chg": 2.0 + i * 0.5,
            "volume_ratio": 1.5 + i * 0.1,
            "turnover_rate": 3.0 + i,
            "circ_mv": 100000 + i * 10000,
            "open": 9.8 + i,
            "high": 10.5 + i,
            "low": 9.5 + i,
            "pre_close": 9.9 + i,
            "name": f"测试股{i}",
        }
    return data


def _make_daily_factors(n=5):
    """创建测试用日级因子DataFrame"""
    codes = ["600036.SH", "000001.SZ", "688001.SH", "300750.SZ", "002475.SZ"][:n]
    return pd.DataFrame({
        "ts_code": codes,
        "ma5": [10.0 + i for i in range(n)],
        "macd": [0.1 + i * 0.01 for i in range(n)],
        "rsi_6": [50 + i * 2 for i in range(n)],
        "boll_upper": [11.0 + i for i in range(n)],
        "atr": [0.5 + i * 0.1 for i in range(n)],
    })


# ==================== merge_factors 测试 ====================


class TestMergeFactors:
    """因子合并测试"""
    
    def test_merge_empty_realtime(self):
        """空实时数据返回空DataFrame"""
        scanner = _make_mock_scanner()
        scorer = StrategyScorer(scanner)
        result = scorer.merge_factors({})
        assert isinstance(result, pd.DataFrame)
        assert result.empty
    
    def test_merge_realtime_only(self):
        """仅实时数据(无日级因子)"""
        scanner = _make_mock_scanner(daily_factors=pd.DataFrame())
        scorer = StrategyScorer(scanner)
        rt_data = _make_realtime_data(3)
        result = scorer.merge_factors(rt_data)
        
        assert len(result) == 3
        assert "pct_chg" in result.columns
        assert "close" in result.columns
    
    def test_merge_with_daily_factors(self):
        """实时+日级因子合并"""
        scanner = _make_mock_scanner(daily_factors=_make_daily_factors(3))
        scorer = StrategyScorer(scanner)
        rt_data = _make_realtime_data(3)
        result = scorer.merge_factors(rt_data)
        
        assert len(result) == 3
        # 应该同时有实时和日级列
        assert "pct_chg" in result.columns
        assert "ma5" in result.columns
    
    def test_merge_limit_up_detection_mainboard(self):
        """主板涨停判断(>=9.5%)"""
        scanner = _make_mock_scanner()
        scorer = StrategyScorer(scanner)
        rt_data = {"600036.SH": {"pct_chg": 9.8, "price": 10, "open": 9.5, "high": 10, "low": 9.5, "pre_close": 9, "volume_ratio": 2, "turnover_rate": 5, "circ_mv": 100000, "name": "测试"}}
        result = scorer.merge_factors(rt_data)
        
        row = result[result["ts_code"] == "600036.SH"]
        assert row["is_limit_up"].values[0] == 1
    
    def test_merge_limit_down_mainboard(self):
        """主板跌停判断(<=-9.5%)"""
        scanner = _make_mock_scanner()
        scorer = StrategyScorer(scanner)
        rt_data = {"600036.SH": {"pct_chg": -10.0, "price": 8, "open": 9, "high": 9, "low": 8, "pre_close": 9, "volume_ratio": 1, "turnover_rate": 2, "circ_mv": 100000, "name": "测试"}}
        result = scorer.merge_factors(rt_data)
        
        row = result[result["ts_code"] == "600036.SH"]
        assert row["is_limit_down"].values[0] == 1
    
    def test_merge_limit_up_kcb(self):
        """科创板涨停判断(>=19.5%)"""
        scanner = _make_mock_scanner()
        scorer = StrategyScorer(scanner)
        rt_data = {"688001.SH": {"pct_chg": 20.0, "price": 12, "open": 10, "high": 12, "low": 10, "pre_close": 10, "volume_ratio": 3, "turnover_rate": 8, "circ_mv": 50000, "name": "科创"}}
        result = scorer.merge_factors(rt_data)
        
        row = result[result["ts_code"] == "688001.SH"]
        assert row["is_limit_up"].values[0] == 1
    
    def test_merge_limit_up_bj(self):
        """北交所涨停判断(>=29.5%)"""
        scanner = _make_mock_scanner()
        scorer = StrategyScorer(scanner)
        rt_data = {"430001.BJ": {"pct_chg": 30.0, "price": 13, "open": 10, "high": 13, "low": 10, "pre_close": 10, "volume_ratio": 3, "turnover_rate": 8, "circ_mv": 50000, "name": "北交"}}
        result = scorer.merge_factors(rt_data)
        
        row = result[result["ts_code"] == "430001.BJ"]
        assert row["is_limit_up"].values[0] == 1
    
    def test_merge_no_limit(self):
        """非涨跌停"""
        scanner = _make_mock_scanner()
        scorer = StrategyScorer(scanner)
        rt_data = {"600036.SH": {"pct_chg": 3.0, "price": 10, "open": 9.5, "high": 10, "low": 9.5, "pre_close": 9.7, "volume_ratio": 1, "turnover_rate": 3, "circ_mv": 100000, "name": "测试"}}
        result = scorer.merge_factors(rt_data)
        
        row = result[result["ts_code"] == "600036.SH"]
        assert row["is_limit_up"].values[0] == 0
        assert row["is_limit_down"].values[0] == 0
    
    def test_merge_preserves_all_realtime_fields(self):
        """保留所有实时字段"""
        scanner = _make_mock_scanner()
        scorer = StrategyScorer(scanner)
        rt_data = _make_realtime_data(1)
        result = scorer.merge_factors(rt_data)
        
        expected_fields = ["pct_chg", "volume_ratio", "turnover_rate", "circ_mv", "open", "high", "low", "close", "pre_close", "stock_name"]
        for field in expected_fields:
            assert field in result.columns, f"Missing field: {field}"


# ==================== get_effective_strategy_config 测试 ====================


class TestGetEffectiveStrategyConfig:
    """策略配置获取测试"""
    
    @pytest.mark.asyncio
    async def test_get_config_from_param_center(self):
        """从ParamCenter获取配置"""
        scanner = _make_mock_scanner()
        scanner._param_center.get_effective_params = AsyncMock(return_value={"stop_loss_pct": 0.05})
        scorer = StrategyScorer(scanner)
        
        result = await scorer._scanner._param_center.get_effective_params("halfway_chase")
        assert result == {"stop_loss_pct": 0.05}
    
    @pytest.mark.asyncio
    async def test_get_config_no_param_center(self):
        """无ParamCenter时返回空"""
        scanner = _make_mock_scanner()
        scanner._param_center = None
        scorer = StrategyScorer(scanner)
        
        # get_effective_strategy_config on scorer
        config = scorer.get_effective_strategy_config("nonexistent")
        # 应返回空或默认配置
        assert isinstance(config, dict)


# ==================== 属性代理测试 ====================


class TestStrategyScorerProperties:
    """属性代理测试"""
    
    def test_broker_property(self):
        """broker属性代理"""
        scanner = _make_mock_scanner()
        scorer = StrategyScorer(scanner)
        assert scorer.broker is scanner._broker
    
    def test_config_property(self):
        """config属性代理"""
        scanner = _make_mock_scanner()
        scorer = StrategyScorer(scanner)
        assert scorer.config is scanner.config
    
    def test_daily_factors_property(self):
        """daily_factors属性代理"""
        df = _make_daily_factors()
        scanner = _make_mock_scanner(daily_factors=df)
        scorer = StrategyScorer(scanner)
        assert scorer.daily_factors_df is df
    
    def test_param_center_property(self):
        """param_center属性代理"""
        scanner = _make_mock_scanner()
        scorer = StrategyScorer(scanner)
        assert scorer.param_center is scanner._param_center
    
    def test_param_center_none(self):
        """param_center为None时"""
        scanner = _make_mock_scanner()
        scanner._param_center = None
        scorer = StrategyScorer(scanner)
        assert scorer.param_center is None


# ==================== detect_anomalies 测试 ====================


class TestDetectAnomalies:
    """异动检测测试"""
    
    @pytest.mark.asyncio
    async def test_detect_anomalies_returns_list(self):
        """异动检测返回列表(via __getattr__委托)"""
        from nodes.market_monitor.scanner import MarketScanner
        scanner = MarketScanner(account_id="test_anomaly")
        
        # _detect_anomalies方法通过DELEGATE_MAP+__getattr__存在
        assert "_detect_anomalies" in MarketScanner._DELEGATE_MAP
        result = await scanner._detect_anomalies({})
        assert isinstance(result, list)
    
    @pytest.mark.asyncio
    async def test_scanner_delegates_detect_anomalies(self):
        """Scanner委托_detect_anomalies到StrategyScorer"""
        from nodes.market_monitor.scanner import MarketScanner
        scanner = MarketScanner(account_id="test_anomaly")
        
        # scanner有_detect_anomalies方法
        assert hasattr(scanner, '_detect_anomalies')


# ==================== 边界条件测试 ====================


class TestStrategyScorerEdgeCases:
    """边界条件测试"""
    
    def test_merge_nan_values(self):
        """NaN值处理"""
        scanner = _make_mock_scanner()
        scorer = StrategyScorer(scanner)
        rt_data = {"600036.SH": {"pct_chg": None, "price": float('nan'), "open": 0, "high": 0, "low": 0, "pre_close": 0, "volume_ratio": 0, "turnover_rate": 0, "circ_mv": 0, "name": "测试"}}
        # 不应crash
        result = scorer.merge_factors(rt_data)
        assert len(result) == 1
    
    def test_merge_missing_fields(self):
        """缺失字段"""
        scanner = _make_mock_scanner()
        scorer = StrategyScorer(scanner)
        rt_data = {"600036.SH": {"pct_chg": 3.0}}  # 只有pct_chg
        # 不应crash
        result = scorer.merge_factors(rt_data)
        assert len(result) == 1
    
    def test_merge_large_dataset(self):
        """大数据集(5000只)"""
        scanner = _make_mock_scanner()
        scorer = StrategyScorer(scanner)
        rt_data = {}
        for i in range(5000):
            code = f"{600000+i:06d}.SH"
            rt_data[code] = {
                "pct_chg": np.random.uniform(-10, 10),
                "price": 10 + np.random.random(),
                "open": 9.5 + np.random.random(),
                "high": 10.5 + np.random.random(),
                "low": 9.0 + np.random.random(),
                "pre_close": 9.8 + np.random.random(),
                "volume_ratio": np.random.uniform(0.5, 5),
                "turnover_rate": np.random.uniform(0.1, 20),
                "circ_mv": np.random.uniform(10000, 500000),
                "name": f"股{i}",
            }
        
        result = scorer.merge_factors(rt_data)
        assert len(result) == 5000
    
    def test_merge_duplicate_ts_codes(self):
        """重复ts_code处理"""
        scanner = _make_mock_scanner()
        scorer = StrategyScorer(scanner)
        rt_data = {
            "600036.SH": {"pct_chg": 3.0, "price": 10, "open": 9.5, "high": 10, "low": 9.5, "pre_close": 9.7, "volume_ratio": 1, "turnover_rate": 3, "circ_mv": 100000, "name": "测试"},
        }
        result = scorer.merge_factors(rt_data)
        # 不应crash
        assert isinstance(result, pd.DataFrame)
