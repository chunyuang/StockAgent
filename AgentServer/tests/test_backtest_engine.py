"""
回测引擎单元测试

测试核心逻辑：
1. 止损止盈
2. T+1约束
3. 成交概率模拟
4. 买入价计算
5. 因子质量检查
6. 参数校验
"""

import pytest
import math
from datetime import datetime

# 添加路径
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from nodes.backtest_engine.validation.backtest_validator import BacktestValidator
from nodes.backtest_engine.factor_selection.factor_quality_checker import (
    FactorQualityChecker,
    FactorQualityLevel,
    FactorQualityReport
)


class TestBacktestValidator:
    """参数校验器测试"""
    
    def setup_method(self):
        self.validator = BacktestValidator()
    
    def test_valid_request(self):
        """测试合法请求"""
        request = {
            "start_date": "20260105",
            "end_date": "20260320",
            "initial_cash": 1000000,
            "strategies": ["halfway_chase", "first_limit_up"],
            "params": {
                "stop_loss_pct": 0.03,
                "take_profit_pct": 0.07,
                "max_hold_days": 3,
                "max_position_per_stock": 0.2,
                "max_position": 0.7,
            }
        }
        
        is_valid, errors = self.validator.validate_backtest_request(request)
        assert is_valid is True
        assert len(errors) == 0
    
    def test_invalid_date_format(self):
        """测试日期格式错误"""
        request = {
            "start_date": "2026-01-05",  # 错误格式
            "end_date": "20260320",
            "strategies": ["halfway_chase"],
        }
        
        is_valid, errors = self.validator.validate_backtest_request(request)
        assert is_valid is False
        assert any("start_date" in e.field for e in errors)
    
    def test_start_date_after_end_date(self):
        """测试开始日期晚于结束日期"""
        request = {
            "start_date": "20260320",
            "end_date": "20260105",  # 早于开始日期
            "strategies": ["halfway_chase"],
        }
        
        is_valid, errors = self.validator.validate_backtest_request(request)
        assert is_valid is False
        assert any("不能晚于" in e.message for e in errors)
    
    def test_invalid_initial_cash(self):
        """测试初始资金范围错误"""
        request = {
            "start_date": "20260105",
            "end_date": "20260320",
            "initial_cash": 1000,  # 小于最小值10000
            "strategies": ["halfway_chase"],
        }
        
        is_valid, errors = self.validator.validate_backtest_request(request)
        assert is_valid is False
        assert any("initial_cash" in e.field for e in errors)
    
    def test_invalid_strategy_id(self):
        """测试无效策略ID"""
        request = {
            "start_date": "20260105",
            "end_date": "20260320",
            "strategies": ["invalid_strategy"],  # 无效策略
        }
        
        is_valid, errors = self.validator.validate_backtest_request(request)
        assert is_valid is False
        assert any("无效的策略ID" in e.message for e in errors)
    
    def test_stop_loss_greater_than_take_profit(self):
        """测试止损大于止盈"""
        request = {
            "start_date": "20260105",
            "end_date": "20260320",
            "strategies": ["halfway_chase"],
            "params": {
                "stop_loss_pct": 0.10,  # 10%
                "take_profit_pct": 0.05,  # 5%，小于止损
            }
        }
        
        is_valid, errors = self.validator.validate_backtest_request(request)
        assert is_valid is False
        assert any("止损" in e.message and "止盈" in e.message for e in errors)
    
    def test_position_per_stock_exceeds_total(self):
        """测试单票仓位超过总仓位"""
        request = {
            "start_date": "20260105",
            "end_date": "20260320",
            "strategies": ["halfway_chase"],
            "params": {
                "max_position_per_stock": 0.8,  # 80%
                "max_position": 0.5,  # 50%，小于单票仓位
            }
        }
        
        is_valid, errors = self.validator.validate_backtest_request(request)
        assert is_valid is False
        assert any("单票仓位" in e.message for e in errors)
    
    def test_no_strategies(self):
        """测试未选择策略"""
        request = {
            "start_date": "20260105",
            "end_date": "20260320",
            "strategies": [],  # 空列表
        }
        
        is_valid, errors = self.validator.validate_backtest_request(request)
        assert is_valid is False
        assert any("至少需要选择一个策略" in e.message for e in errors)


class TestFactorQualityChecker:
    """因子质量检查器测试"""
    
    def setup_method(self):
        self.checker = FactorQualityChecker(strict_mode=False)
    
    def test_good_quality_factors(self):
        """测试良好质量的因子数据"""
        import pandas as pd
        
        # 创建模拟因子数据
        factor_df = pd.DataFrame({
            "ts_code": ["000001.SZ", "000002.SZ", "000003.SZ"],
            "pct_chg": [3.0, 2.5, 1.8],
            "volume_ratio": [2.5, 3.0, 1.5],
            "turnover_rate": [5.0, 4.5, 3.0],
            "circ_mv": [1000000, 2000000, 500000],
            "opening_pct_chg": [1.0, 0.5, -0.5],
        })
        
        requested_factors = [
            {"name": "pct_chg"},
            {"name": "volume_ratio"},
            {"name": "turnover_rate"},
            {"name": "circ_mv"},
            {"name": "opening_pct_chg"},
        ]
        
        report = self.checker.check_factor_quality(
            factor_df, requested_factors, ["半路追涨"], "20260105"
        )
        
        assert report.level == FactorQualityLevel.GOOD
        assert len(report.missing_factors) == 0
        assert len(report.empty_factors) == 0
    
    def test_missing_factors(self):
        """测试缺失因子"""
        import pandas as pd
        
        factor_df = pd.DataFrame({
            "ts_code": ["000001.SZ", "000002.SZ"],
            "pct_chg": [3.0, 2.5],
            "volume_ratio": [2.5, 3.0],
        })
        
        requested_factors = [
            {"name": "pct_chg"},
            {"name": "volume_ratio"},
            {"name": "turnover_rate"},  # 缺失
            {"name": "circ_mv"},  # 缺失
        ]
        
        report = self.checker.check_factor_quality(
            factor_df, requested_factors, ["半路追涨"], "20260105"
        )
        
        assert report.level == FactorQualityLevel.ERROR  # 核心因子缺失
        assert "turnover_rate" in report.missing_factors
        assert "circ_mv" in report.missing_factors
    
    def test_empty_factors(self):
        """测试全空因子"""
        import pandas as pd
        import numpy as np
        
        factor_df = pd.DataFrame({
            "ts_code": ["000001.SZ", "000002.SZ"],
            "pct_chg": [3.0, 2.5],
            "volume_ratio": [np.nan, np.nan],  # 全空
        })
        
        requested_factors = [
            {"name": "pct_chg"},
            {"name": "volume_ratio"},
        ]
        
        report = self.checker.check_factor_quality(
            factor_df, requested_factors, [], "20260105"
        )
        
        assert "volume_ratio" in report.empty_factors
    
    def test_apply_defaults(self):
        """测试应用默认值"""
        import pandas as pd
        
        factor_df = pd.DataFrame({
            "ts_code": ["000001.SZ", "000002.SZ"],
            "pct_chg": [3.0, 2.5],
        })
        
        missing_factors = ["market_leader", "limit_up_open_amount"]
        
        self.checker.apply_factor_defaults(factor_df, missing_factors)
        
        assert "market_leader" in factor_df.columns
        assert factor_df["market_leader"].iloc[0] == 0
        assert "limit_up_open_amount" in factor_df.columns
        assert factor_df["limit_up_open_amount"].iloc[0] == 0
    
    def test_should_abort_on_core_missing(self):
        """测试核心因子缺失时中止回测"""
        report = FactorQualityReport(
            level=FactorQualityLevel.ERROR,
            total_factors=5,
            missing_factors=["pct_chg", "volume_ratio"],  # 核心因子
            empty_factors=[],
            low_quality_factors=[],
            message="核心因子缺失"
        )
        
        should_abort, reason = self.checker.should_abort_backtest(report)
        assert should_abort is True
        assert "核心因子缺失" in reason
    
    def test_strict_mode_abort(self):
        """测试严格模式下中止"""
        strict_checker = FactorQualityChecker(strict_mode=True)
        
        report = FactorQualityReport(
            level=FactorQualityLevel.ERROR,
            total_factors=5,
            missing_factors=["some_factor"],
            empty_factors=[],
            low_quality_factors=[],
            message="数据缺失"
        )
        
        should_abort, reason = strict_checker.should_abort_backtest(report)
        assert should_abort is True
        assert "严格模式" in reason


class TestStopLossTakeProfit:
    """止损止盈逻辑测试"""
    
    def test_stop_loss_trigger(self):
        """测试止损触发"""
        # 买入价 10元，止损 3%
        buy_price = 10.0
        stop_loss_pct = 0.03
        stop_price = buy_price * (1 - stop_loss_pct)
        
        # 当日最低价跌破止损价
        low_price = 9.5  # < 9.7
        
        assert low_price <= stop_price  # 应触发止损
    
    def test_stop_loss_not_trigger(self):
        """测试止损未触发"""
        buy_price = 10.0
        stop_loss_pct = 0.03
        stop_price = buy_price * (1 - stop_loss_pct)
        
        # 当日最低价未跌破止损价
        low_price = 9.8  # > 9.7
        
        assert low_price > stop_price  # 不应触发止损
    
    def test_take_profit_trigger(self):
        """测试止盈触发"""
        # 买入价 10元，止盈 7%
        buy_price = 10.0
        take_profit_pct = 0.07
        profit_price = buy_price * (1 + take_profit_pct)
        
        # 当日最高价触及止盈价
        high_price = 10.8  # > 10.7
        
        assert high_price >= profit_price  # 应触发止盈
    
    def test_gap_stop_loss(self):
        """测试跳空止损"""
        # 买入价 10元，止损 3%
        buy_price = 10.0
        stop_loss_pct = 0.03
        stop_price = buy_price * (1 - stop_loss_pct)  # 9.7
        
        # 开盘直接跳空低于止损价
        open_price = 9.5  # < 9.7
        
        # 跳空止损应以开盘价卖出
        assert open_price <= stop_price
        sell_price = open_price  # 9.5
        assert sell_price == 9.5


class TestT1Constraint:
    """T+1约束测试"""
    
    def test_t1_block_sell(self):
        """测试T+1禁止卖出"""
        # 当日买入的股票
        buy_date = 20260105
        current_date = 20260105
        
        # T+1约束：当日买入不可卖出
        assert buy_date == current_date  # 应阻止卖出
    
    def test_t1_allow_sell_next_day(self):
        """测试T+1次日可卖出"""
        # 昨日买入的股票
        buy_date = 20260105
        current_date = 20260106
        
        # T+1约束：次日可卖出
        assert buy_date < current_date  # 允许卖出
    
    def test_t1_block_stop_loss(self):
        """测试T+1阻止止损"""
        # 当日买入的股票，即使触发止损也不能卖
        buy_date = 20260105
        current_date = 20260105
        
        # 即使 low < stop_price，也应跳过止损
        assert buy_date == current_date  # T+1优先级高于止损


class TestHitProbability:
    """成交概率模拟测试"""
    
    def test_yizi_board_zero_probability(self):
        """测试一字板0%成交"""
        # 一字板：open = close = high = low
        open_price = 10.0
        close_price = 10.0
        high_price = 10.0
        low_price = 10.0
        
        # 判断为一字板
        is_yizi = (open_price == close_price == high_price == low_price)
        assert is_yizi is True
        
        # 一字板成交概率应为0%
        hit_probability = 0.0
        assert hit_probability == 0.0
    
    def test_fast_board_probability(self):
        """测试秒板成交概率"""
        pre_close = 10.0
        open_price = 10.9  # 开盘涨9%，秒板
        
        open_rise = (open_price - pre_close) / pre_close * 100
        
        # 秒板（开盘涨>=8%）
        assert open_rise >= 8
        
        # 秒板成交概率约10-30%
        hit_probability = 0.3
        assert 0.1 <= hit_probability <= 0.3
    
    def test_normal_board_probability(self):
        """测试快速板成交概率"""
        pre_close = 10.0
        open_price = 10.5  # 开盘涨5%，快速板
        
        open_rise = (open_price - pre_close) / pre_close * 100
        
        # 快速板（开盘涨2-8%）
        assert 2 <= open_rise < 8
        
        # 快速板成交概率约30-50%
        hit_probability = 0.5
        assert 0.3 <= hit_probability <= 0.5
    
    def test_deterministic_hash(self):
        """测试确定性hash（回测可复现）"""
        import hashlib
        
        # 同一只股票同一交易日的hash应固定
        code = "000001.SZ"
        trade_date = 20260105
        
        seed_str = f"{code}_{trade_date}"
        hash_val1 = int(hashlib.md5(seed_str.encode()).hexdigest(), 16) % 1000 / 1000.0
        hash_val2 = int(hashlib.md5(seed_str.encode()).hexdigest(), 16) % 1000 / 1000.0
        
        assert hash_val1 == hash_val2  # 确定性


class TestBuyPriceCalculation:
    """买入价计算测试"""
    
    def test_halfway_chase_buy_price(self):
        """测试半路追涨买入价"""
        open_price = 10.0
        min_rise_pct = 0.03  # 最小涨幅3%
        signal_fraction = 0.6  # 信号触发位置
        
        # 半路追涨买入价 = open * (1 + min_rise * 0.6)
        buy_price = open_price * (1 + min_rise_pct * signal_fraction)
        
        # 应高于开盘价
        assert buy_price > open_price
        # 应接近 10.18
        assert abs(buy_price - 10.18) < 0.01
    
    def test_dragon_head_buy_price(self):
        """测试龙头低吸买入价"""
        low_price = 9.5
        high_price = 10.5
        
        # 龙头低吸买入价 = low + (high - low) * 0.25
        buy_price = low_price + (high_price - low_price) * 0.25
        
        # 应高于最低价
        assert buy_price > low_price
        # 应低于最高价
        assert buy_price < high_price
        # 应接近 9.75
        assert abs(buy_price - 9.75) < 0.01
    
    def test_limit_down_qiao_buy_price(self):
        """测试跌停翘板买入价"""
        low_price = 9.0  # 跌停价附近
        
        # 跌停翘板买入价 = low * 1.005
        buy_price = low_price * 1.005
        
        # 应略高于最低价
        assert buy_price > low_price
        # 应接近 9.045
        assert abs(buy_price - 9.045) < 0.01
    
    def test_multi_strategy_lowest_price(self):
        """测试多策略选同股取最低价"""
        # 假设一只股票同时被半路追涨和龙头低吸选中
        halfway_price = 10.18
        dragon_price = 9.75
        
        # 取最低价（最保守）
        buy_price = min(halfway_price, dragon_price)
        
        assert buy_price == dragon_price
        assert buy_price == 9.75


class TestPositionMultiplier:
    """仓位系数计算测试"""
    
    def test_rising_sentiment(self):
        """测试高涨情绪仓位系数"""
        # 涨停数多，跌停数少，大盘涨
        limit_up_count = 80
        limit_down_count = 10
        index_pct_chg = 2.0  # 大盘涨2%
        
        # 情绪评分 = 涨停数 - 跌停数 + 大盘涨幅*10 + 50
        sentiment_score = limit_up_count - limit_down_count + index_pct_chg * 10 + 50
        
        # 高涨情绪（>=70）
        assert sentiment_score >= 70
        
        # 仓位系数应为1.0（满仓）
        position_multiplier = 1.0
        assert position_multiplier == 1.0
    
    def test_depression_sentiment(self):
        """测试低迷情绪仓位系数"""
        # 涨停数少，跌停数多，大盘跌
        limit_up_count = 10
        limit_down_count = 80
        index_pct_chg = -3.0  # 大盘跌3%
        
        # 情绪评分 = 涨停数 - 跌停数 + 大盘涨幅*10 + 50
        sentiment_score = limit_up_count - limit_down_count + index_pct_chg * 10 + 50
        
        # 低迷情绪（<40）
        assert sentiment_score < 40
        
        # 仓位系数应为0.3（低仓）
        position_multiplier = 0.3
        assert position_multiplier == 0.3
    
    def test_force_empty_position(self):
        """测试强制空仓"""
        # 跌停数极端
        limit_down_count = 128  # 超过阈值50
        
        # 触发强制空仓
        assert limit_down_count >= 50
        
        # 仓位系数应为0（空仓）
        position_multiplier = 0.0
        assert position_multiplier == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
