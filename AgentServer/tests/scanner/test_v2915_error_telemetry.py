#!/usr/bin/env python3
"""
v2.9.15 — 错误遥测 + 参数预检 + 事件扩展 测试

新增:
1. SCANNER_ERROR事件(扫描循环异常/风控线程异常→EventBus→Redis→前端)
2. HEALTH_CHANGED事件(ScannerEvents枚举)
3. 参数预检验证API(/params/validate)
4. WS前端异常弹窗(scanner_error事件)
"""
import os
import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_EVENT_BUS = os.path.join(_PROJECT_ROOT, "nodes", "market_monitor", "scanner_event_bus.py")
_SUBSCRIBERS = os.path.join(_PROJECT_ROOT, "nodes", "market_monitor", "scanner_event_subscribers.py")
_SCANNER = os.path.join(_PROJECT_ROOT, "nodes", "market_monitor", "scanner.py")
_API_SCANNER = os.path.join(_PROJECT_ROOT, "nodes", "web", "api", "scanner_shared.py")
_RW = os.path.join(_PROJECT_ROOT, "nodes", "market_monitor", "risk_watchdog.py")
_WS_BRIDGE = os.path.join(_PROJECT_ROOT, "nodes", "web", "redis_ws_bridge.py")
_FRONTEND = os.path.join(_PROJECT_ROOT, "..", "frontend", "src", "views", "monitor", "MarketMonitorView.vue")


def _read(path):
    return open(path).read()


# ==================== 1. SCANNER_ERROR事件 ====================

class TestScannerErrorEvent:
    """验证SCANNER_ERROR事件(异常→EventBus→Redis→前端)"""

    def test_scanner_error_in_events_enum(self):
        """ScannerEvents枚举包含SCANNER_ERROR"""
        source = _read(_EVENT_BUS)
        assert 'SCANNER_ERROR = "scanner_error"' in source

    def test_health_changed_in_events_enum(self):
        """ScannerEvents枚举包含HEALTH_CHANGED"""
        source = _read(_EVENT_BUS)
        assert 'HEALTH_CHANGED = "health_changed"' in source

    def test_scan_loop_emits_error_on_exception(self):
        """scan_loop主循环异常时发射SCANNER_ERROR"""
        source = _read(_SCANNER)
        # 主循环except块应有emit(SCANNER_ERROR)
        assert "ScannerEvents.SCANNER_ERROR" in source

    def test_risk_thread_emits_error(self):
        """风控线程异常时发射SCANNER_ERROR(v2.9.39:委托给RiskWatchdog)"""
        source = _read(_SCANNER)
        # 查找风控线程except块
        idx = source.find("[RISK_THREAD] 风控线程异常")
        assert idx > 0, "缺少风控线程异常日志"
        block = source[idx:idx+500]
        # v2.9.33+39: 原内联emit提取为_emit_risk_thread_error方法,再委托RiskWatchdog
        assert "_emit_risk_thread_error" in block, \
            "风控线程异常未调用_emit_risk_thread_error"
        # 确认_emit_risk_thread_error方法存在且委托RiskWatchdog
        method_idx = source.find("def _emit_risk_thread_error")
        assert method_idx > 0, "缺少_emit_risk_thread_error方法定义"
        method_code = source[method_idx:method_idx+400]
        assert "RiskWatchdog" in method_code, \
            "_emit_risk_thread_error应委托RiskWatchdog.emit_risk_thread_error"
        # 验证RiskWatchdog中有SCANNER_ERROR
        rw_source = _read(_RW)
        assert "ScannerEvents.SCANNER_ERROR" in rw_source, \
            "RiskWatchdog.emit_risk_thread_error应发射SCANNER_ERROR"

    def test_error_subscriber_registered(self):
        """scanner_error事件订阅器已注册"""
        source = _read(_SUBSCRIBERS)
        assert 'bus.on("scanner_error"' in source

    def test_error_handler_pushes_to_redis(self):
        """error handler推送scanner:status到Redis"""
        source = _read(_SUBSCRIBERS)
        # 找到函数定义(而非调用)
        func_start = source.find("def _make_scanner_error_handler")
        assert func_start > 0, "缺少_make_scanner_error_handler定义"
        func_code = source[func_start:func_start+800]
        assert "scanner:status" in func_code, \
            "error handler应推送scanner:status"
        assert '"scanner_error"' in func_code, \
            "应包含scanner_error事件标记"

    def test_error_handler_writes_audit_log(self):
        """error handler写入审计日志"""
        source = _read(_SUBSCRIBERS)
        func_start = source.find("_make_scanner_error_handler")
        func_code = source[func_start:func_start+1000]
        assert "_write_audit_log" in func_code, \
            "error handler应写入审计日志"

    def test_subscriber_count_updated(self):
        """订阅器数量从9→10"""
        source = _read(_SUBSCRIBERS)
        assert "10组事件订阅器" in source or "10 组" in source


# ==================== 2. 参数预检验证 ====================

class TestParamValidation:
    """验证参数预检API(/params/validate)"""

    def test_validate_endpoint_exists(self):
        """/params/validate端点存在"""
        source = _read(_API_SCANNER)
        assert '"/params/validate"' in source

    def test_validate_checks_stop_loss(self):
        """验证止损参数(过宽/过紧)"""
        source = _read(_API_SCANNER)
        idx = source.find("/params/validate")
        block = source[idx:idx+2000]
        assert "stop_loss_pct" in block

    def test_validate_checks_take_profit(self):
        """验证止盈参数(过低)"""
        source = _read(_API_SCANNER)
        idx = source.find("/params/validate")
        block = source[idx:idx+2000]
        assert "take_profit_pct" in block

    def test_validate_checks_position_ratio(self):
        """验证单票仓位(过高)"""
        source = _read(_API_SCANNER)
        idx = source.find("/params/validate")
        block = source[idx:idx+2000]
        assert "max_position_ratio" in block

    def test_validate_returns_is_safe(self):
        """验证返回is_safe字段"""
        source = _read(_API_SCANNER)
        idx = source.find("/params/validate")
        block = source[idx:idx+2000]
        assert '"is_safe"' in block

    def test_validate_does_not_update(self):
        """验证不实际更新参数(只检查)"""
        source = _read(_API_SCANNER)
        idx = source.find("/params/validate")
        block = source[idx:idx+2000]
        assert "update_strategy_params" not in block, \
            "validate端点不应调用update_strategy_params"


# ==================== 3. 回测零影响 ====================

class TestNoBacktestRegressionV2915:
    """验证v2.9.15改动对回测零影响"""

    def test_scanner_events_not_imported_by_backtest(self):
        """回测引擎不导入scanner_event_bus"""
        backtest_path = os.path.join(
            _PROJECT_ROOT, "nodes", "backtest_engine",
            "factor_selection", "portfolio_backtest.py"
        )
        if os.path.exists(backtest_path):
            source = open(backtest_path).read()
            assert "scanner_event_bus" not in source
            assert "scanner_event_subscribers" not in source

    def test_scanner_error_not_in_backtest_sell_checker(self):
        """回测SellSignalChecker不含SCANNER_ERROR"""
        checker_path = os.path.join(
            _PROJECT_ROOT, "nodes", "backtest_engine",
            "factor_selection", "sell_signal_checker.py"
        )
        if os.path.exists(checker_path):
            source = open(checker_path).read()
            assert "SCANNER_ERROR" not in source
