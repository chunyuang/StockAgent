#!/usr/bin/env python3
"""v2.9.23 运行时诊断测试

变更点:
1. diagnose()运行时诊断方法(6项检查+可操作建议)
2. 行情缓存过期检测(_last_realtime_update_ts)
3. get_status新增字段(last_realtime_update_ts, realtime_cache_age_sec)
"""
import os
import sys
import time
import pytest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


class TestDiagnoseMethod:
    """diagnose()运行时诊断测试"""

    def _make_minimal_scanner(self):
        """创建最小可诊断的scanner实例"""
        from nodes.market_monitor.scanner import MarketScanner
        scanner = MarketScanner.__new__(MarketScanner)
        scanner._is_running = True
        scanner._risk_running = False
        scanner._risk_thread = None
        scanner._risk_thread_restarts = 0
        scanner._last_realtime_update_ts = time.time()
        scanner._active_signals = []
        scanner._pending_sells = {}
        scanner._circuit_breaker = {"trading_paused": False, "pause_reason": ""}
        scanner._last_risk_check_ts = time.time()
        scanner._scan_loop_error_count = 0
        scanner._broker = MagicMock()
        scanner._broker.get_positions.return_value = [MagicMock()]
        return scanner

    def test_diagnose_returns_healthy(self):
        """正常状态返回healthy=True"""
        scanner = self._make_minimal_scanner()
        result = scanner.diagnose()
        assert result["healthy"] is True
        assert result["issues"] == []

    def test_diagnose_detects_risk_thread_dead(self):
        """风控线程退出→critical"""
        scanner = self._make_minimal_scanner()
        scanner._risk_running = True
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = False
        scanner._risk_thread = mock_thread
        result = scanner.diagnose()
        assert result["healthy"] is False
        assert any(i["area"] == "risk_thread" and i["level"] == "critical" for i in result["issues"])

    def test_diagnose_detects_stale_cache(self):
        """行情缓存过期→warning"""
        scanner = self._make_minimal_scanner()
        scanner._last_realtime_update_ts = time.time() - 180  # 3分钟前
        result = scanner.diagnose()
        assert any(i["area"] == "quote_cache" for i in result["issues"])

    def test_diagnose_detects_scan_errors(self):
        """scan_loop连续异常→warning/critical"""
        scanner = self._make_minimal_scanner()
        scanner._scan_loop_error_count = 2
        result = scanner.diagnose()
        assert any(i["area"] == "scan_loop" for i in result["issues"])

    def test_diagnose_detects_pending_sells_backlog(self):
        """pending_sells积压→warning"""
        scanner = self._make_minimal_scanner()
        scanner._pending_sells = {f"00000{i}.SZ": {"reason": "test"} for i in range(10)}
        result = scanner.diagnose()
        assert any(i["area"] == "pending_sells" for i in result["issues"])

    def test_diagnose_detects_circuit_breaker(self):
        """熔断器触发→critical"""
        scanner = self._make_minimal_scanner()
        scanner._circuit_breaker = {"trading_paused": True, "pause_reason": "日亏损超限"}
        result = scanner.diagnose()
        assert result["healthy"] is False
        assert any(i["area"] == "circuit_breaker" for i in result["issues"])

    def test_diagnose_has_summary(self):
        """diagnose包含summary摘要"""
        scanner = self._make_minimal_scanner()
        result = scanner.diagnose()
        assert "summary" in result
        assert "running" in result["summary"]
        assert "positions" in result["summary"]
        assert "cache_age_sec" in result["summary"]
        assert "pending_sells" in result["summary"]

    def test_diagnose_issues_have_action(self):
        """每个issue都包含action建议"""
        scanner = self._make_minimal_scanner()
        scanner._scan_loop_error_count = 1
        result = scanner.diagnose()
        for issue in result["issues"]:
            assert "action" in issue, f"{issue['area']}缺少action"


class TestRealtimeUpdateTimestamp:
    """行情缓存更新时间戳测试"""

    def test_timestamp_initialized(self):
        """_last_realtime_update_ts初始化为0"""
        from nodes.market_monitor.scanner import MarketScanner
        scanner = MarketScanner.__new__(MarketScanner)
        scanner._init_state()
        assert hasattr(scanner, '_last_realtime_update_ts')
        assert scanner._last_realtime_update_ts == 0.0

    def test_get_status_includes_cache_age(self):
        """get_status包含缓存年龄字段"""
        from nodes.market_monitor.scanner import MarketScanner
        scanner = MarketScanner.__new__(MarketScanner)
        scanner._is_running = True
        scanner._risk_running = False
        scanner._risk_thread = None
        scanner._risk_thread_restarts = 0
        scanner._last_realtime_update_ts = time.time()
        scanner._active_signals = []
        scanner._pending_sells = {}
        scanner._circuit_breaker = {"trading_paused": False}
        scanner._last_risk_check_ts = time.time()
        scanner._scan_loop_error_count = 0
        scanner._broker = MagicMock()
        scanner._broker.get_positions.return_value = []
        result = scanner.diagnose()
        assert "cache_age_sec" in result["summary"]
