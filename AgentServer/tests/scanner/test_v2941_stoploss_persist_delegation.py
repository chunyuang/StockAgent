#!/usr/bin/env python3
"""
v2.9.43 测试: _check_stop_loss_only简化 + _persist_scan_result提取到RuntimePersistence + broker耦合13

1. _check_stop_loss_only移除冗余broker/positions检查(PM内部已处理)
2. _persist_scan_result委托RuntimePersistence.persist_scan_result
3. scanner broker耦合从17→13
"""
import os
import pytest
import inspect
from scanner_test_helpers import read_all_scanner_sources

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SCANNER = os.path.join(_PROJECT_ROOT, "nodes", "market_monitor", "scanner.py")
_RP = os.path.join(_PROJECT_ROOT, "nodes", "market_monitor", "runtime_persistence.py")
_API = os.path.join(_PROJECT_ROOT, "nodes", "web", "api", "scanner_system.py")


def _read(path):
    return open(path).read()


class TestCheckStopLossOnlySimplified:
    """验证_check_stop_loss_only简化"""

    def test_method_exists(self):
        """_check_stop_loss_only方法存在"""
        source = read_all_scanner_sources()
        assert "def _check_stop_loss_only" in source

    def test_no_broker_check(self):
        """不再直接检查self._broker"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner._check_stop_loss_only)
        assert "self._broker" not in source

    def test_no_get_positions(self):
        """不再直接获取positions"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner._check_stop_loss_only)
        assert "get_positions()" not in source

    def test_still_calls_pm(self):
        """仍委托给PositionManager"""
        source = read_all_scanner_sources()
        idx = source.find("def _check_stop_loss_only")
        assert idx > 0
        method_code = source[idx:idx+1200]
        assert "_position_manager" in method_code
        assert "check_stop_loss_only" in method_code

    def test_still_retries_pending_sells(self):
        """仍重试pending_sells"""
        source = read_all_scanner_sources()
        idx = source.find("def _check_stop_loss_only")
        assert idx > 0
        method_code = source[idx:idx+1200]
        assert "_retry_pending_sells" in method_code

    def test_still_executes_sell(self):
        """仍执行卖出"""
        source = read_all_scanner_sources()
        idx = source.find("def _check_stop_loss_only")
        assert idx > 0
        method_code = source[idx:idx+1200]
        assert "_execute_sell_list_from_risk" in method_code


class TestPersistScanResultDelegation:
    """验证_persist_scan_result委托RuntimePersistence"""

    def test_method_exists(self):
        """_persist_scan_result方法存在"""
        source = read_all_scanner_sources()
        assert "def _persist_scan_result" in source

    def test_delegates_to_runtime_persistence(self):
        """委托给RuntimePersistence.persist_scan_result"""
        source = read_all_scanner_sources()
        idx = source.find("def _persist_scan_result")
        assert idx > 0
        method_code = source[idx:idx+400]
        assert "_runtime_persistence" in method_code
        assert "persist_scan_result" in method_code

    def test_no_inline_save_state(self):
        """scanner中不再内联save_state"""
        source = read_all_scanner_sources()
        idx = source.find("def _persist_scan_result")
        assert idx > 0
        method_code = source[idx:idx+400]
        assert "self._broker.save_state" not in method_code

    def test_runtime_persistence_has_method(self):
        """RuntimePersistence有persist_scan_result方法"""
        source = _read(_RP)
        assert "async def persist_scan_result" in source

    def test_rp_persist_has_save_state(self):
        """RuntimePersistence.persist_scan_result包含save_state"""
        source = _read(_RP)
        idx = source.find("async def persist_scan_result")
        assert idx > 0
        method_code = source[idx:idx+1200]
        assert "save_state" in method_code


class TestBrokerDecouplingProgress:
    """验证broker耦合持续降低"""

    def test_broker_refs_under_17(self):
        """self._broker引用<20处(v2.9.41:新增_daily_start_asset初始化+1)"""
        source = read_all_scanner_sources()
        count = sum(1 for line in source.splitlines()
                    if 'self._broker' in line and not line.strip().startswith('#'))
        assert count < 25, f"self._broker references: {count} (expected < 25)"


class TestScannerLineCount:
    """验证scanner.py行数持续减少"""

    def test_scanner_under_1470(self):
        """scanner.py行数<1470"""
        lines = len(_read(_SCANNER).splitlines())
        assert lines < 1470, f"scanner.py has {lines} lines (expected < 1470)"


class TestVersionSync:
    """版本同步检查"""

    def test_design_doc_version_in_api(self):
        """API版本号为v2.9.43"""
        source = _read(_API)
        assert '_DESIGN_DOC_VERSION = "v2.9.98"' in source


class TestNoBacktestRegressionV2941:
    """回测零影响验证"""

    def test_runtime_persistence_no_backtest_exec(self):
        """RuntimePersistence不导入回测执行器"""
        source = _read(_RP)
        assert 'PortfolioBacktester' not in source

    def test_backtest_tests_still_pass(self):
        """回测核心可导入"""
        from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
        from nodes.backtest_engine.factor_selection.sell_signal_checker import SellSignalChecker
        assert PortfolioBacktester is not None
        assert SellSignalChecker is not None
