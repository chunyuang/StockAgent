#!/usr/bin/env python3
"""
v2.9.43 测试: _scan_loop_settlement提取 + _emit_risk_thread_error委托RiskWatchdog + MarketPhase.is_trading_active + position_checker except修复

1. _scan_loop_settlement委托RuntimePersistence.daily_settlement
2. _emit_risk_thread_error委托RiskWatchdog.emit_risk_thread_error
3. MarketPhase.is_trading_active便捷方法
4. position_checker except Exception → except Exception as _e
"""
import os
import pytest
import inspect

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SCANNER = os.path.join(_PROJECT_ROOT, "nodes", "market_monitor", "scanner.py")
_RW = os.path.join(_PROJECT_ROOT, "nodes", "market_monitor", "risk_watchdog.py")
_RP = os.path.join(_PROJECT_ROOT, "nodes", "market_monitor", "runtime_persistence.py")
_PC = os.path.join(_PROJECT_ROOT, "nodes", "market_monitor", "position_checker.py")
_API = os.path.join(_PROJECT_ROOT, "nodes", "web", "api", "scanner.py")


def _read(path):
    return open(path).read()


class TestScanLoopSettlementDelegation:
    """验证_scan_loop_settlement委托RuntimePersistence.daily_settlement"""

    def test_method_exists(self):
        """_scan_loop_settlement方法存在"""
        source = _read(_SCANNER)
        assert "def _scan_loop_settlement" in source

    def test_delegates_to_runtime_persistence(self):
        """委托给RuntimePersistence.daily_settlement"""
        source = _read(_SCANNER)
        idx = source.find("def _scan_loop_settlement")
        assert idx > 0
        method_code = source[idx:idx+400]
        assert "daily_settlement" in method_code
        assert "_runtime_persistence" in method_code

    def test_no_inline_broker_settlement(self):
        """scanner中不再内联broker.daily_settlement"""
        source = _read(_SCANNER)
        idx = source.find("def _scan_loop_settlement")
        assert idx > 0
        method_code = source[idx:idx+400]
        assert "self._broker.daily_settlement" not in method_code
        assert "self._event_bus.emit" not in method_code

    def test_runtime_persistence_has_daily_settlement(self):
        """RuntimePersistence有daily_settlement方法"""
        source = _read(_RP)
        assert "async def daily_settlement" in source

    def test_daily_settlement_has_broker_settlement(self):
        """RuntimePersistence.daily_settlement包含broker日终结算"""
        source = _read(_RP)
        idx = source.find("async def daily_settlement")
        assert idx > 0
        method_code = source[idx:idx+2000]
        assert "broker.daily_settlement" in method_code
        assert "broker.save_state" in method_code

    def test_daily_settlement_has_event_bus(self):
        """RuntimePersistence.daily_settlement发射DAILY_SETTLED事件"""
        source = _read(_RP)
        idx = source.find("async def daily_settlement")
        assert idx > 0
        method_code = source[idx:idx+2000]
        assert "ScannerEvents.DAILY_SETTLED" in method_code

    def test_daily_settlement_has_timeline(self):
        """RuntimePersistence.daily_settlement保存Timeline"""
        source = _read(_RP)
        idx = source.find("async def daily_settlement")
        assert idx > 0
        method_code = source[idx:idx+2000]
        assert "_save_timeline" in method_code

    def test_daily_settlement_has_sentiment(self):
        """RuntimePersistence.daily_settlement更新情绪预计算"""
        source = _read(_RP)
        idx = source.find("async def daily_settlement")
        assert idx > 0
        method_code = source[idx:idx+2000]
        assert "_update_sentiment_score" in method_code

    def test_daily_settlement_has_close_sync(self):
        """RuntimePersistence.daily_settlement同步收盘数据"""
        source = _read(_RP)
        idx = source.find("async def daily_settlement")
        assert idx > 0
        method_code = source[idx:idx+2000]
        assert "_sync_close_data_to_mongo" in method_code


class TestEmitRiskThreadErrorDelegation:
    """验证_emit_risk_thread_error委托RiskWatchdog"""

    def test_method_exists(self):
        """_emit_risk_thread_error方法存在"""
        source = _read(_SCANNER)
        assert "def _emit_risk_thread_error" in source

    def test_delegates_to_risk_watchdog(self):
        """委托给RiskWatchdog.emit_risk_thread_error"""
        source = _read(_SCANNER)
        idx = source.find("def _emit_risk_thread_error")
        assert idx > 0
        method_code = source[idx:idx+400]
        assert "RiskWatchdog" in method_code
        assert "emit_risk_thread_error" in method_code

    def test_no_inline_call_soon(self):
        """scanner中不再内联call_soon_threadsafe"""
        source = _read(_SCANNER)
        idx = source.find("def _emit_risk_thread_error")
        assert idx > 0
        method_code = source[idx:idx+400]
        assert "call_soon_threadsafe" not in method_code

    def test_risk_watchdog_has_emit_method(self):
        """RiskWatchdog有emit_risk_thread_error静态方法"""
        source = _read(_RW)
        assert "def emit_risk_thread_error" in source

    def test_risk_watchdog_uses_scanner_error(self):
        """RiskWatchdog.emit_risk_thread_error发射SCANNER_ERROR"""
        source = _read(_RW)
        idx = source.find("def emit_risk_thread_error")
        assert idx > 0
        method_code = source[idx:idx+1500]
        assert "ScannerEvents.SCANNER_ERROR" in method_code

    def test_risk_watchdog_uses_threadsafe(self):
        """RiskWatchdog.emit_risk_thread_error使用call_soon_threadsafe"""
        source = _read(_RW)
        idx = source.find("def emit_risk_thread_error")
        assert idx > 0
        method_code = source[idx:idx+1500]
        assert "call_soon_threadsafe" in method_code
        assert "create_task" in method_code

    def test_risk_loop_still_calls_method(self):
        """_risk_loop_sync仍调用_emit_risk_thread_error"""
        source = _read(_SCANNER)
        idx = source.find("def _risk_loop_sync")
        assert idx > 0
        method_code = source[idx:idx+2000]
        assert "_emit_risk_thread_error" in method_code


class TestMarketPhaseIsTradingActive:
    """验证MarketPhase.is_trading_active便捷方法"""

    def test_method_exists(self):
        """is_trading_active方法存在"""
        from nodes.market_monitor.scanner import MarketPhase
        assert hasattr(MarketPhase, 'is_trading_active')

    def test_trading_is_active(self):
        """交易时段返回True"""
        from nodes.market_monitor.scanner import MarketPhase
        assert MarketPhase.is_trading_active(MarketPhase.TRADING) is True

    def test_auction_is_active(self):
        """竞价时段返回True"""
        from nodes.market_monitor.scanner import MarketPhase
        assert MarketPhase.is_trading_active(MarketPhase.AUCTION) is True

    def test_premarket_not_active(self):
        """盘前非活跃"""
        from nodes.market_monitor.scanner import MarketPhase
        assert MarketPhase.is_trading_active(MarketPhase.PREMARKET) is False

    def test_deep_night_not_active(self):
        """深夜非活跃"""
        from nodes.market_monitor.scanner import MarketPhase
        assert MarketPhase.is_trading_active(MarketPhase.DEEP_NIGHT) is False

    def test_weekend_not_active(self):
        """周末非活跃"""
        from nodes.market_monitor.scanner import MarketPhase
        assert MarketPhase.is_trading_active(MarketPhase.WEEKEND) is False

    def test_after_close_not_active(self):
        """盘后非活跃"""
        from nodes.market_monitor.scanner import MarketPhase
        assert MarketPhase.is_trading_active(MarketPhase.AFTER_CLOSE) is False

    def test_off_hours_not_active(self):
        """非交易时间非活跃"""
        from nodes.market_monitor.scanner import MarketPhase
        assert MarketPhase.is_trading_active(MarketPhase.OFF_HOURS) is False

    def test_is_static_method(self):
        """是静态方法"""
        from nodes.market_monitor.scanner import MarketPhase
        assert isinstance(inspect.getattr_static(MarketPhase, 'is_trading_active'), staticmethod)

    def test_accepts_phase_arg(self):
        """接受phase参数(避免重复classify)"""
        source = _read(_SCANNER)
        idx = source.find("def is_trading_active")
        assert idx > 0
        sig = source[idx:idx+200]
        assert "phase" in sig


class TestPositionCheckerExceptFix:
    """验证position_checker.py中except Exception修复"""

    def test_no_bare_except_exception(self):
        """position_checker中无bare except Exception"""
        source = _read(_PC)
        import re
        # 检查except Exception: 不跟as的情况
        for i, line in enumerate(source.splitlines(), 1):
            stripped = line.strip()
            if 'except Exception:' in stripped and 'as ' not in stripped:
                pytest.fail(f'Found bare except Exception: at line {i}: {stripped}')

    def test_compare_diff_index_uses_as(self):
        """compare差异索引创建使用except Exception as _e【v2.9.45:实现已迁移到runtime_persistence】"""
        source = _read(_RP)
        idx = source.find("ttl_30d_compare")
        assert idx > 0
        block = source[max(0, idx-300):idx+100]
        assert "except Exception as _e:" in block or "except Exception as " in block


class TestScannerLineCount:
    """验证scanner.py行数持续减少"""

    def test_scanner_under_1500(self):
        """scanner.py行数<1500"""
        lines = len(_read(_SCANNER).splitlines())
        assert lines < 1500, f"scanner.py has {lines} lines (expected < 1500)"


class TestVersionSync:
    """版本同步检查"""

    def test_design_doc_version_in_api(self):
        """API版本号为v2.9.43"""
        source = _read(_API)
        assert '_DESIGN_DOC_VERSION = "v2.9.51"' in source


class TestNoBacktestRegressionV2939:
    """回测零影响验证"""

    def test_sell_signal_checker_importable(self):
        """SellSignalChecker可导入"""
        from nodes.backtest_engine.factor_selection.sell_signal_checker import SellSignalChecker
        assert SellSignalChecker is not None

    def test_strategy_defaults_importable(self):
        """策略默认参数可导入"""
        from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS
        assert len(STRATEGY_CONFIGS) > 0

    def test_portfolio_backtester_importable(self):
        """回测引擎可导入"""
        from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
        assert PortfolioBacktester is not None

    def test_runtime_persistence_no_backtest_ref(self):
        """RuntimePersistence不引用回测模块"""
        source = _read(_RP)
        assert "backtest_engine" not in source
        assert "PortfolioBacktester" not in source

    def test_risk_watchdog_no_backtest_ref(self):
        """RiskWatchdog不引用回测模块"""
        source = _read(_RW)
        assert "backtest_engine" not in source
        assert "PortfolioBacktester" not in source
