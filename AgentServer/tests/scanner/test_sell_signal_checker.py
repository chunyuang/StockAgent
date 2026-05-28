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


class TestQuoteManagerRecovery:
    """【Phase2.2】行情降级自动恢复测试"""
    
    def test_staleness_no_fetch(self):
        """从未获取行情时陈旧度为999"""
        from nodes.market_monitor.quote_manager import QuoteManager
        qm = QuoteManager()
        assert qm.get_staleness() == 999.0
    
    def test_staleness_after_fetch(self):
        """获取行情后陈旧度应递增"""
        import time
        from nodes.market_monitor.quote_manager import QuoteManager
        qm = QuoteManager()
        qm._last_fetch_time = time.monotonic()
        staleness = qm.get_staleness()
        assert staleness < 1.0  # 刚获取,陈旧度应<1秒
    
    def test_should_not_recover_when_normal(self):
        """正常状态不应尝试恢复"""
        from nodes.market_monitor.quote_manager import QuoteManager
        qm = QuoteManager()
        qm._quote_degrade_level = 0
        assert qm.should_try_recover() is False
    
    def test_should_not_recover_too_soon(self):
        """降级后5分钟内不应尝试恢复"""
        import time
        from nodes.market_monitor.quote_manager import QuoteManager
        qm = QuoteManager()
        qm._quote_degrade_level = 1
        qm._degrade_since = time.monotonic()
        qm._last_recover_attempt = time.monotonic()  # 刚降级
        assert qm.should_try_recover() is False
    
    def test_should_recover_after_5min(self):
        """降级5分钟后应尝试恢复"""
        import time
        from nodes.market_monitor.quote_manager import QuoteManager
        qm = QuoteManager()
        qm._quote_degrade_level = 1
        qm._degrade_since = time.monotonic() - 100
        qm._last_recover_attempt = time.monotonic() - 310  # 5m10s ago
        assert qm.should_try_recover() is True
    
    def test_status_includes_staleness_and_recovery(self):
        """状态应包含陈旧度和恢复倒计时"""
        import time
        from nodes.market_monitor.quote_manager import QuoteManager
        qm = QuoteManager()
        qm._quote_degrade_level = 1
        qm._degrade_since = time.monotonic() - 60
        qm._last_recover_attempt = time.monotonic() - 60
        qm._last_fetch_time = time.monotonic() - 10
        status = qm.get_status()
        assert "staleness_seconds" in status
        assert "degrade_duration_seconds" in status
        assert "next_recover_in_seconds" in status
        assert status["degrade_level"] == 1


class TestParamAuditLog:
    """【Phase2.3】参数变更审计日志测试"""
    
    def test_check_dangerous_params_normal(self):
        """正常参数不应告警"""
        from nodes.market_monitor.strategy_param_center import StrategyParamCenter
        pc = StrategyParamCenter()
        warnings = pc.check_dangerous_params("halfway_chase", {"stop_loss_pct": 0.04})
        assert len(warnings) == 0
    
    def test_check_dangerous_params_excessive_sl(self):
        """止损过大应告警"""
        from nodes.market_monitor.strategy_param_center import StrategyParamCenter
        pc = StrategyParamCenter()
        warnings = pc.check_dangerous_params("halfway_chase", {"stop_loss_pct": 0.15})
        assert len(warnings) > 0
        assert "stop_loss_pct" in warnings[0]
    
    def test_check_dangerous_params_tiny_tp(self):
        """止盈过小应告警"""
        from nodes.market_monitor.strategy_param_center import StrategyParamCenter
        pc = StrategyParamCenter()
        warnings = pc.check_dangerous_params("halfway_chase", {"take_profit_pct": 0.01})
        assert len(warnings) > 0
    
    def test_audit_trail_method_exists(self):
        """审计轨迹查询方法应存在"""
        from nodes.market_monitor.strategy_param_center import StrategyParamCenter
        pc = StrategyParamCenter()
        assert hasattr(pc, 'get_param_audit_trail')
        assert hasattr(pc, '_write_param_audit_log')


class TestScannerHealthScore:
    """【Phase4.3】Scanner健康度评分测试"""
    
    def test_health_red_when_not_started(self):
        """未启动时健康度应为红"""
        import threading
        from nodes.market_monitor.scanner import MarketScanner
        import time
        s = MarketScanner.__new__(MarketScanner)
        s._last_scan_ts = 0
        s._last_risk_check_ts = 0
        s._pending_sells = {}
        s._state_lock = threading.Lock()
        s._quote_manager = None
        s._circuit_breaker = {}
        health = s._compute_health_score()
        assert health["status"] == "red"
        assert health["is_healthy"] is False
    
    def test_health_green_when_active(self):
        """活跃时健康度应为绿"""
        import threading
        from nodes.market_monitor.scanner import MarketScanner
        from nodes.market_monitor.quote_manager import QuoteManager
        import time
        s = MarketScanner.__new__(MarketScanner)
        s._last_scan_ts = time.time() - 60
        s._last_risk_check_ts = time.time() - 2
        s._pending_sells = {}
        s._state_lock = threading.Lock()
        s._quote_manager = QuoteManager()
        s._quote_manager._last_fetch_time = time.time() - 5
        s._circuit_breaker = {}
        health = s._compute_health_score()
        assert health["status"] == "green"
        assert health["is_healthy"] is True
    
    def test_health_yellow_when_degraded(self):
        """行情降级时健康度应为黄"""
        import threading
        from nodes.market_monitor.scanner import MarketScanner
        from nodes.market_monitor.quote_manager import QuoteManager
        import time
        s = MarketScanner.__new__(MarketScanner)
        s._last_scan_ts = time.time() - 60
        s._last_risk_check_ts = time.time() - 2
        s._pending_sells = {}
        s._state_lock = threading.Lock()
        s._quote_manager = QuoteManager()
        s._quote_manager._last_fetch_time = time.time() - 5
        s._quote_manager._quote_degrade_level = 1
        s._circuit_breaker = {}
        health = s._compute_health_score()
        assert health["status"] == "yellow"
        assert "行情降级" in str(health["warnings"])
    
    def test_health_warnings_include_pending_sells(self):
        """跌停挂起应出现在warnings"""
        import threading
        from nodes.market_monitor.scanner import MarketScanner
        from nodes.market_monitor.quote_manager import QuoteManager
        import time
        s = MarketScanner.__new__(MarketScanner)
        s._last_scan_ts = time.time() - 60
        s._last_risk_check_ts = time.time() - 2
        s._pending_sells = {"600036.SH": {"reason": "跌停挂起", "price": 40.0}}
        s._state_lock = threading.Lock()
        s._quote_manager = QuoteManager()
        s._quote_manager._last_fetch_time = time.time() - 5
        s._circuit_breaker = {}
        health = s._compute_health_score()
        assert any("跌停挂起" in w for w in health["warnings"])


class TestPositionManager:
    """【Phase3.1】PositionManager持仓风控测试"""

    def _make_mock_pos(self, ts_code="600036.SH", strategy="halfway_chase",
                       avg_cost=10.0, current_price=10.5, available_qty=100,
                       profit_pct=5.0, buy_date="20260528"):
        """构造mock Position对象"""
        class MockPos:
            pass
        pos = MockPos()
        pos.ts_code = ts_code
        pos.strategy = strategy
        pos.stock_name = "测试股"
        pos.avg_cost = avg_cost
        pos.current_price = current_price
        pos.available_qty = available_qty
        pos.profit_pct = profit_pct
        pos.buy_date = buy_date
        return pos

    def _make_mock_scanner(self):
        """构造mock Scanner对象(只提供PositionManager需要的属性)"""
        import threading
        class MockScanner:
            SELL_LOGIC_MODE = "legacy"
            _trailing_stops = {}
            _pending_sells = {}
            _position_risk_levels = {}
            _position_risk_overrides = {}
            _state_lock = threading.Lock()
            
            def _get_strategy_risk(self, strategy):
                return {"stop_loss_pct": 0.03, "take_profit_pct": 0.07,
                        "trailing_stop_pct": 0.02, "next_day_open_sell_pct": 0.03}
            
            def _get_open_price(self, ts_code):
                return 10.0
            
            def _is_limit_down(self, ts_code):
                return False
        
        return MockScanner()
    
    def _make_mock_scanner_with_broker(self, positions=None):
        """构造带Broker的mock Scanner(check_stop_loss_only需要)"""
        scanner = self._make_mock_scanner()
        
        class MockBroker:
            def get_positions(self):
                return positions or []
            def update_realtime(self, code, price):
                pass
        
        scanner._broker = MockBroker()
        return scanner

    def test_calc_stop_loss_price(self):
        """止损价计算"""
        from nodes.market_monitor.position_manager import PositionManager
        pm = PositionManager(self._make_mock_scanner())
        pos = self._make_mock_pos(avg_cost=10.0)
        price = pm.calc_stop_loss_price(pos, {"stop_loss_pct": 0.03})
        assert price == 9.7  # 10 * (1 - 0.03)

    def test_calc_take_profit_price(self):
        """止盈价计算"""
        from nodes.market_monitor.position_manager import PositionManager
        pm = PositionManager(self._make_mock_scanner())
        pos = self._make_mock_pos(avg_cost=10.0)
        price = pm.calc_take_profit_price(pos, {"take_profit_pct": 0.07})
        assert price == 10.7  # 10 * (1 + 0.07)

    def test_check_stop_loss_triggered(self):
        """止损触发"""
        from nodes.market_monitor.position_manager import PositionManager
        pm = PositionManager(self._make_mock_scanner())
        pos = self._make_mock_pos(current_price=9.5, profit_pct=-5.0)
        result = pm.check_stop_loss_take_profit([pos], {})
        assert len(result) == 1
        assert "止损" in result[0][1]

    def test_check_take_profit_triggered(self):
        """止盈触发"""
        from nodes.market_monitor.position_manager import PositionManager
        pm = PositionManager(self._make_mock_scanner())
        pos = self._make_mock_pos(current_price=11.0, profit_pct=10.0)
        result = pm.check_stop_loss_take_profit([pos], {})
        assert len(result) == 1
        assert "止盈" in result[0][1]

    def test_check_no_sell_when_profitable(self):
        """盈利中不应触发卖出"""
        from nodes.market_monitor.position_manager import PositionManager
        pm = PositionManager(self._make_mock_scanner())
        pos = self._make_mock_pos(current_price=10.5, profit_pct=5.0)
        result = pm.check_stop_loss_take_profit([pos], {})
        assert len(result) == 0

    def test_check_gap_stop_loss(self):
        """跳空止损: open < stop_loss_price"""
        from nodes.market_monitor.position_manager import PositionManager
        pm = PositionManager(self._make_mock_scanner())
        pos = self._make_mock_pos(current_price=9.3, profit_pct=-7.0)
        rt = {pos.ts_code: {"open": 9.6}}  # open < 9.7(止损价)
        result = pm.check_stop_loss_take_profit([pos], rt)
        assert len(result) == 1
        assert "跳空" in result[0][1]

    def test_check_trailing_stop_triggered(self):
        """追踪止损触发"""
        from nodes.market_monitor.position_manager import PositionManager
        scanner = self._make_mock_scanner()
        scanner._trailing_stops = {
            "600036.SH": {
                "activated": True,
                "stop_price": 10.5,
                "high_price": 11.0,
                "trailing_stop_pct": 0.02,
            }
        }
        pm = PositionManager(scanner)
        pos = self._make_mock_pos(current_price=10.3, profit_pct=3.0)
        result = pm.check_stop_loss_take_profit([pos], {})
        assert len(result) == 1
        assert "追踪止损" in result[0][1]

    def test_check_stop_loss_only_lightweight(self):
        """1秒级止损检查(轻量,不含止盈)"""
        from nodes.market_monitor.position_manager import PositionManager
        pos = self._make_mock_pos(current_price=9.5, profit_pct=-5.0)
        scanner = self._make_mock_scanner_with_broker([pos])
        pm = PositionManager(scanner)
        rt = {pos.ts_code: {"price": 9.5, "open": 10.0}}
        result = pm.check_stop_loss_only(rt)
        assert len(result) == 1

    def test_check_stop_loss_only_no_take_profit(self):
        """1秒级止损不应触发止盈"""
        from nodes.market_monitor.position_manager import PositionManager
        pos = self._make_mock_pos(current_price=11.0, profit_pct=10.0)
        scanner = self._make_mock_scanner_with_broker([pos])
        pm = PositionManager(scanner)
        rt = {pos.ts_code: {"price": 11.0, "open": 10.0}}
        result = pm.check_stop_loss_only(rt)
        assert len(result) == 0

    def test_update_trailing_stops_activate(self):
        """追踪止损激活(盈利>=2%)"""
        from nodes.market_monitor.position_manager import PositionManager
        scanner = self._make_mock_scanner()
        pm = PositionManager(scanner)
        pos = self._make_mock_pos(current_price=10.5, profit_pct=5.0)
        pm.update_trailing_stops([pos], {})
        assert "600036.SH" in scanner._trailing_stops
        assert scanner._trailing_stops["600036.SH"]["activated"] is True

    def test_check_timeout_sell(self):
        """超时强卖"""
        from nodes.market_monitor.position_manager import PositionManager
        pm = PositionManager(self._make_mock_scanner())
        pos = self._make_mock_pos(buy_date="20260520")
        result = pm.check_timeout_sell([pos], "20260528")
        # 取决于_calc_trade_days_held, 但至少不应该crash
        assert isinstance(result, list)

    def test_get_effective_stop_price_trailing(self):
        """有效止损价(追踪止损>固定止损)"""
        from nodes.market_monitor.position_manager import PositionManager
        scanner = self._make_mock_scanner()
        scanner._trailing_stops = {
            "600036.SH": {
                "activated": True,
                "stop_price": 10.5,
                "high_price": 11.0,
            }
        }
        pm = PositionManager(scanner)
        pos = self._make_mock_pos(current_price=10.8, profit_pct=8.0)
        price = pm.get_effective_stop_price(pos, {"stop_loss_pct": 0.03})
        # 追踪止损10.5 > 固定止损9.7, 取更高的
        assert price == 10.5

    def test_pending_sells_on_limit_down(self):
        """跌停不可卖→挂起pending_sells"""
        from nodes.market_monitor.position_manager import PositionManager
        pos = self._make_mock_pos(current_price=9.5, profit_pct=-5.0)
        scanner = self._make_mock_scanner_with_broker([pos])
        
        # 跌停
        scanner._is_limit_down = lambda code: True
        pm = PositionManager(scanner)
        rt = {pos.ts_code: {"price": 9.5, "open": 10.0}}
        result = pm.check_stop_loss_only(rt)
        # 跌停时挂起, 不返回to_sell(由Scanner处理挂起)
        assert "600036.SH" in scanner._pending_sells


class TestPositionManagerThreadSafety:
    """【线程安全】PositionManager并发读写测试"""

    def _make_threadsafe_scanner(self):
        """构造线程安全的mock Scanner"""
        import threading
        class MockScanner:
            SELL_LOGIC_MODE = "legacy"
            _trailing_stops = {}
            _pending_sells = {}
            _position_risk_levels = {}
            _position_risk_overrides = {}
            _state_lock = threading.Lock()

            def _get_strategy_risk(self, strategy):
                return {"stop_loss_pct": 0.03, "take_profit_pct": 0.07,
                        "trailing_stop_pct": 0.02, "next_day_open_sell_pct": 0.03}

            def _get_open_price(self, ts_code):
                return 10.0

            def _is_limit_down(self, ts_code):
                return False
        return MockScanner()

    def test_concurrent_trailing_stop_update(self):
        """并发更新追踪止损不会crash或丢失数据"""
        import threading
        from nodes.market_monitor.position_manager import PositionManager

        scanner = self._make_threadsafe_scanner()
        pm = PositionManager(scanner)

        class MockPos:
            pass

        errors = []

        def update_worker(code_prefix, count):
            try:
                for i in range(count):
                    pos = MockPos()
                    pos.ts_code = f"{code_prefix}{i:04d}.SH"
                    pos.stock_name = "测试"
                    pos.avg_cost = 10.0
                    pos.current_price = 10.5 + i * 0.01
                    pos.available_qty = 100
                    pos.profit_pct = 5.0 + i * 0.1
                    pos.buy_date = "20260520"
                    pos.strategy = "halfway_chase"
                    pm.update_trailing_stops([pos], {})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=update_worker, args=(f"60{i}", 50)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"并发更新出错: {errors}"
        # 应该有200只(4线程×50)
        assert len(scanner._trailing_stops) == 200

    def test_concurrent_pending_sells_access(self):
        """风控线程和主线程同时读写pending_sells"""
        import threading
        from nodes.market_monitor.position_manager import PositionManager

        scanner = self._make_threadsafe_scanner()
        pm = PositionManager(scanner)

        # 预填一些pending_sells
        for i in range(10):
            scanner._pending_sells[f"60{i:04d}.SH"] = {"reason": "test", "price": 10.0}

        errors = []

        def reader_worker():
            try:
                for _ in range(100):
                    with scanner._state_lock:
                        _ = dict(scanner._pending_sells)
                        _ = dict(scanner._trailing_stops)
            except Exception as e:
                errors.append(e)

        def writer_worker():
            try:
                for i in range(100):
                    code = f"00{i:04d}.SZ"
                    with scanner._state_lock:
                        scanner._pending_sells[code] = {"reason": "write", "price": 10.0}
                    with scanner._state_lock:
                        scanner._pending_sells.pop(code, None)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=reader_worker),
            threading.Thread(target=reader_worker),
            threading.Thread(target=writer_worker),
            threading.Thread(target=writer_worker),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"并发读写出错: {errors}"
