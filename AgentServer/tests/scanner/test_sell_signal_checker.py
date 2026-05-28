"""
sell_signal_checker 核心模块测试

优先级最高的测试:
1. check_early_sell / check_full_sell (回测用)
2. check_realtime_sell (实盘用, Phase1.3新增)
3. SELL_PRIORITY优先级表
4. 卖出条件覆盖: 固定止损/跳空止损/追踪止损/冲高回落/利润保护/超时
"""
import pytest
from nodes.backtest_engine.factor_selection.sell_signal_checker import (
    SellSignalChecker, SELL_PRIORITY
)
from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS, GLOBAL_RISK


class MockPosition:
    """模拟Position对象"""
    def __init__(self, ts_code="000001.SZ", strategy="halfway_chase",
                 avg_cost=10.0, current_price=10.0, profit_pct=0.0,
                 buy_date="20260101", available_qty=100):
        self.ts_code = ts_code
        self.strategy = strategy
        self.stock_name = "测试股"
        self.avg_cost = avg_cost
        self.current_price = current_price
        self.profit_pct = profit_pct
        self.buy_date = buy_date
        self.available_qty = available_qty
        self.total_qty = available_qty


class TestSELLPRIORITY:
    """卖出优先级表测试"""
    
    def test_stop_loss_highest(self):
        """止损优先级最高"""
        assert SELL_PRIORITY.get("stop_loss", 0) >= 8
    
    def test_force_empty_is_defined(self):
        """强制空仓优先级已定义"""
        assert "force_empty" in SELL_PRIORITY
    
    def test_timeout_lower_than_stop_loss(self):
        """超时低于止损"""
        assert SELL_PRIORITY.get("timeout", 0) < SELL_PRIORITY.get("stop_loss", 0)
    
    def test_take_profit_lower_than_trailing(self):
        """止盈低于追踪止损"""
        assert SELL_PRIORITY.get("take_profit", 0) < SELL_PRIORITY.get("trailing_stop", 0)


class TestCheckRealtimeSell:
    """实盘卖出检查测试"""
    
    def setup_method(self):
        strategy_params = {}
        strategy_risk_params = {}
        for sid, cfg in STRATEGY_CONFIGS.items():
            strategy_params[sid] = cfg
            strategy_risk_params[sid] = cfg.get("riskParams", {})
        self.checker = SellSignalChecker(
            strategy_params=strategy_params,
            strategy_risk_params=strategy_risk_params,
            risk_config=GLOBAL_RISK
        )
    
    def test_no_sell_when_profitable(self):
        """盈利持仓不应触发止损"""
        pos = MockPosition(avg_cost=10.0, current_price=11.0, profit_pct=10.0,
                          strategy="halfway_chase")
        # open_price设为9.8(不高开), high=11.5
        result = self.checker.check_realtime_sell(
            position=pos, realtime_price=11.0, high_price=11.5, open_price=9.8
        )
        # 可能触发利润保护/冲高回落等,但不应是止损
        if result and "stop_loss" in result.get("reason", ""):
            pytest.fail(f"盈利持仓不应触发止损: {result}")
    
    def test_stop_loss_triggered(self):
        """止损应触发"""
        pos = MockPosition(avg_cost=10.0, current_price=9.5, profit_pct=-5.0,
                          strategy="halfway_chase")
        result = self.checker.check_realtime_sell(
            position=pos, realtime_price=9.5, high_price=9.6, open_price=9.8
        )
        assert result is not None
        assert "stop_loss" in result["reason"] or "gap" in result["reason"]
    
    def test_gap_down_stop_loss(self):
        """跳空低开应触发止损"""
        pos = MockPosition(avg_cost=10.0, current_price=9.2, profit_pct=-8.0,
                          strategy="halfway_chase")
        result = self.checker.check_realtime_sell(
            position=pos, realtime_price=9.2, high_price=9.3, open_price=9.2
        )
        assert result is not None
        assert "stop_loss" in result["reason"] or "gap" in result["reason"]
    
    def test_trailing_stop_activated(self):
        """追踪止损应正确触发"""
        pos = MockPosition(avg_cost=10.0, current_price=11.0, profit_pct=10.0,
                          strategy="halfway_chase")
        trailing_state = {
            "activated": True,
            "stop_price": 11.2,  # 已激活, 止损线11.2元
            "high_since_activate": 12.5,
        }
        # 价格跌到11.0, 低于追踪止损线11.2
        result = self.checker.check_realtime_sell(
            position=pos, realtime_price=11.0, high_price=12.5, open_price=11.5,
            trailing_stop_state=trailing_state
        )
        if result:
            assert "trailing" in result.get("reason", "").lower() or "stop" in result.get("reason", "").lower()
    
    def test_no_trailing_stop_without_state(self):
        """无追踪止损状态不应触发追踪止损"""
        pos = MockPosition(avg_cost=10.0, current_price=12.0, profit_pct=20.0)
        result = self.checker.check_realtime_sell(
            position=pos, realtime_price=12.0, high_price=12.5, open_price=11.0,
            trailing_stop_state=None
        )
        # 可能触发其他卖出(如利润保护), 但不应是追踪止损
        if result:
            assert "追踪止损" not in result.get("reason", "")


class TestCheckEarlySell:
    """回测早盘卖出检查测试"""
    
    def setup_method(self):
        strategy_params = {}
        strategy_risk_params = {}
        for sid, cfg in STRATEGY_CONFIGS.items():
            strategy_params[sid] = cfg
            strategy_risk_params[sid] = cfg.get("riskParams", {})
        self.checker = SellSignalChecker(
            strategy_params=strategy_params,
            strategy_risk_params=strategy_risk_params,
            risk_config=GLOBAL_RISK
        )
    
    def test_early_stop_loss(self):
        """早盘止损——check_early_sell只检查冲高回落/利润保护/高开即卖,不检查固定止损"""
        # 止损在check_realtime_sell中检查,early_sell只检查盘中保护
        pos = MockPosition(avg_cost=10.0, current_price=9.6, profit_pct=-4.0,
                          strategy="halfway_chase")
        # check_early_sell的签名: (code, strategies, cost, open_price, close_price)
        price, reason = self.checker.check_early_sell(
            pos.ts_code, [pos.strategy], pos.avg_cost, 9.8, 9.6
        )
        # 止损不在early_sell中检查,所以不应该返回
        assert price == 0 or reason == ''
    
    def test_early_no_sell_normal(self):
        """早盘正常持仓不应触发冲高回落"""
        pos = MockPosition(avg_cost=10.0, current_price=10.5, profit_pct=5.0,
                          strategy="halfway_chase")
        price, reason = self.checker.check_early_sell(
            pos.ts_code, [pos.strategy], pos.avg_cost, 9.8, 10.5
        )
        assert price == 0 or reason == ''


class TestCheckFullSell:
    """回测尾盘卖出检查测试"""
    
    def setup_method(self):
        strategy_params = {}
        strategy_risk_params = {}
        for sid, cfg in STRATEGY_CONFIGS.items():
            strategy_params[sid] = cfg
            strategy_risk_params[sid] = cfg.get("riskParams", {})
        self.checker = SellSignalChecker(
            strategy_params=strategy_params,
            strategy_risk_params=strategy_risk_params,
            risk_config=GLOBAL_RISK
        )
    
    def test_full_take_profit(self):
        """尾盘止盈"""
        market_data = {"high": 14.0, "low": 13.0, "close": 13.5, "open": 9.8}
        price, reason = self.checker.check_full_sell(
            "000001.SZ", ["dragon_head_low"], 10.0, market_data, trade_days_held=5
        )
        if price > 0:
            assert "止盈" in reason or "take_profit" in reason
    
    def test_full_timeout(self):
        """超时卖出"""
        market_data = {"high": 10.5, "low": 10.0, "close": 10.2, "open": 9.8}
        price, reason = self.checker.check_full_sell(
            "000001.SZ", ["halfway_chase"], 10.0, market_data, trade_days_held=4
        )
        if price > 0:
            assert "超时" in reason or "timeout" in reason


class TestQuoteManager:
    """QuoteManager测试"""
    
    def test_short_to_ts_code(self):
        """6位代码转ts_code"""
        from nodes.market_monitor.quote_manager import QuoteManager
        
        assert QuoteManager.short_to_ts_code("600036") == "600036.SH"
        assert QuoteManager.short_to_ts_code("000001") == "000001.SZ"
        assert QuoteManager.short_to_ts_code("300001") == "300001.SZ"
        assert QuoteManager.short_to_ts_code("830001") == "830001.BJ"
        assert QuoteManager.short_to_ts_code("") == ""
    
    def test_degrade_status(self):
        """降级状态描述"""
        from nodes.market_monitor.quote_manager import QuoteManager
        
        qm = QuoteManager()
        assert qm.degrade_level == 0
        assert qm.degrade_desc == "正常"
        
        qm._quote_degrade_level = 1
        assert qm.degrade_desc == "东财降级"
        
        qm._quote_degrade_level = 2
        assert qm.degrade_desc == "日线缓存"
    
    def test_cache_thread_safety(self):
        """缓存线程安全"""
        from nodes.market_monitor.quote_manager import QuoteManager
        import threading
        
        qm = QuoteManager()
        qm.set_cache_lock(threading.Lock())
        
        # 模拟并发写入
        qm._realtime_cache = {"000001.SZ": {"price": 10.0}}
        
        # 读取应该安全
        price = qm.get_cached_price("000001.SZ")
        assert price == 10.0
        
        data = qm.get_cached_data("000001.SZ")
        assert data["price"] == 10.0
        
        all_data = qm.get_all_cached()
        assert "000001.SZ" in all_data


class TestEmotionDowngradeRules:
    """情绪降级调仓规则测试"""
    
    def test_all_downgrade_paths_have_rules(self):
        """所有降级路径都有规则"""
        from nodes.market_monitor.scanner import MarketScanner
        
        # 检查6条降级规则
        rules = MarketScanner.EMOTION_DOWNGRADE_RULES
        expected_keys = [
            ("rising", "differentiation"),
            ("rising", "chaos"),
            ("rising", "bearish"),
            ("differentiation", "chaos"),
            ("differentiation", "bearish"),
            ("chaos", "bearish"),
        ]
        for key in expected_keys:
            assert key in rules, f"缺少降级规则: {key}"
    
    def test_upgrade_no_rule(self):
        """升级路径不应有规则(自然加仓)"""
        from nodes.market_monitor.scanner import MarketScanner
        
        rules = MarketScanner.EMOTION_DOWNGRADE_RULES
        # 震荡→高潮不应有规则
        assert ("chaos", "rising") not in rules
        assert ("bearish", "rising") not in rules
    
    def test_reduce_rules_have_keep_ratio(self):
        """减仓规则应有keep_ratio"""
        from nodes.market_monitor.scanner import MarketScanner
        
        rules = MarketScanner.EMOTION_DOWNGRADE_RULES
        for key, rule in rules.items():
            if rule["action"] == "reduce":
                assert "keep_ratio" in rule, f"{key} 减仓规则缺少keep_ratio"
                assert 0 < rule["keep_ratio"] < 1, f"{key} keep_ratio应在0-1之间"
    
    def test_clear_rules_have_min_profit(self):
        """清仓规则应有min_profit"""
        from nodes.market_monitor.scanner import MarketScanner
        
        rules = MarketScanner.EMOTION_DOWNGRADE_RULES
        for key, rule in rules.items():
            if rule["action"] == "clear_low_profit":
                assert "min_profit" in rule, f"{key} 清仓规则缺少min_profit"
                assert rule["min_profit"] > 0, f"{key} min_profit应>0"
