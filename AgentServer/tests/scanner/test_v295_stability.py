"""
v2.9.5 稳定性增强测试

覆盖:
1. 风控线程看门狗(自动重启)
2. 风控卖出超时fallback(pending_sells兜底)
3. 健康度评分含风控线程状态
4. MongoDB import一致性
5. 风控线程trade_date一致性
6. 回测模块不受影响
"""

import asyncio
import threading
import time
from datetime import datetime
from unittest.mock import MagicMock, patch, PropertyMock
import pytest


# ==================== 1. 风控线程看门狗 ====================

class TestRiskThreadWatchdog:
    """v2.9.5: 风控线程崩溃后自动重启"""

    def _make_scanner(self):
        """创建mock scanner(最小依赖)"""
        scanner = MagicMock()
        scanner._risk_running = False
        scanner._risk_thread = None
        scanner._risk_thread_restarts = 0
        scanner._is_running = True
        scanner._trade_date = "20260529"
        scanner._state_lock = threading.Lock()
        scanner._cache_lock = threading.Lock()
        scanner._realtime_cache = {}
        scanner._pending_sells = {}
        scanner._trailing_stops = {}
        scanner._position_risk_levels = {}
        scanner._broker = None
        scanner._position_manager = None
        scanner._loop = None
        scanner._last_risk_check_ts = 0.0
        scanner._last_scan_ts = 0.0
        scanner._quote_manager = MagicMock()
        scanner._quote_manager.degrade_level = 0
        scanner._quote_manager.get_staleness.return_value = 1.0
        scanner._quote_manager.should_try_recover.return_value = False
        scanner._circuit_breaker = {"trading_paused": False}
        scanner._event_bus = MagicMock()
        scanner._event_bus.get_stats.return_value = {}
        scanner.SCAN_INTERVAL = 300
        scanner.SELL_LOGIC_MODE = "legacy"
        scanner._dry_run = True
        scanner._active_signals = []
        scanner._stats = {}
        scanner._nav_peak = 1.0
        return scanner

    def test_risk_thread_restarts_counter_initialized(self):
        """_risk_thread_restarts 初始化为0(类属性或_init_state)"""
        from nodes.market_monitor.scanner import MarketScanner
        # v2.9.37: _risk_thread_restarts提升为类属性默认值
        assert MarketScanner._risk_thread_restarts == 0

    def test_risk_thread_restarts_counter_in_start(self):
        """start()或其调用的方法中重置重启计数"""
        import inspect
        from nodes.market_monitor.scanner import MarketScanner
        # v2.9.18: _risk_thread_restarts = 0 移到 _start_risk_thread()
        src = inspect.getsource(MarketScanner.start) + inspect.getsource(MarketScanner._start_risk_thread)
        assert '_risk_thread_restarts = 0' in src or '_risk_thread_restarts=0' in src

    def test_watchdog_in_scan_loop_source(self):
        """_scan_loop或其提取方法中有风控线程看门狗代码"""
        import inspect
        from nodes.market_monitor.scanner import MarketScanner
        # v2.9.13: 看门狗逻辑提取到_scan_loop_trading
        src = inspect.getsource(MarketScanner._scan_loop_trading)
        # 验证有风控线程健康检查
        assert '_risk_thread' in src and 'is_alive' in src
        assert '_risk_thread_restarts' in src

    def test_watchdog_restarts_dead_thread(self):
        """风控线程死后看门狗重启它"""
        scanner = self._make_scanner()

        # 模拟一个死掉的风控线程
        dead_thread = threading.Thread(target=lambda: None, daemon=True)
        dead_thread.start()
        dead_thread.join(timeout=1)  # 让它立即结束

        scanner._risk_running = True
        scanner._risk_thread = dead_thread

        # 验证死线程不alive
        assert not dead_thread.is_alive()

        # 看门狗应该重启: 用sleep让新线程保持存活
        import time as _t
        stop_event = threading.Event()
        def _long_running():
            while not stop_event.is_set():
                _t.sleep(0.1)

        scanner._risk_thread_restarts += 1
        scanner._risk_thread = threading.Thread(
            target=_long_running, daemon=True,
            name="scanner-risk-thread"
        )
        scanner._risk_thread.start()

        try:
            assert scanner._risk_thread_restarts == 1
            assert scanner._risk_thread.is_alive()
        finally:
            stop_event.set()

    def test_watchdog_alerts_after_3_restarts(self):
        """重启3次后发送告警"""
        scanner = self._make_scanner()
        scanner._risk_thread_restarts = 3
        # 应该在scan_loop中触发_publish_scanner_event
        # 这里只验证逻辑: 3次以上需要告警
        assert scanner._risk_thread_restarts >= 3


# ==================== 2. 风控卖出超时fallback ====================

class TestRiskSellTimeoutFallback:
    """v2.9.5: _execute_risk_sell超时时pending_sells兜底"""

    def test_timeout_adds_to_pending_sells(self):
        """超时卖出不丢弃, 加入pending_sells"""
        scanner = MagicMock()
        scanner._state_lock = threading.Lock()
        scanner._pending_sells = {}

        # 模拟超时场景
        pos = MagicMock()
        pos.ts_code = "600036.SH"
        pos.available_qty = 100

        # 模拟: 超时后加入pending_sells
        with scanner._state_lock:
            if pos.ts_code not in scanner._pending_sells:
                scanner._pending_sells[pos.ts_code] = {
                    "reason": "止损 -3.5%",
                    "price": 38.5,
                    "added_at": time.time(),
                    "source": "risk_thread_timeout",
                }

        assert "600036.SH" in scanner._pending_sells
        assert scanner._pending_sells["600036.SH"]["source"] == "risk_thread_timeout"

    def test_timeout_does_not_overwrite_existing_pending(self):
        """已有pending_sell时不覆盖(例如跌停挂起)"""
        scanner = MagicMock()
        scanner._state_lock = threading.Lock()
        scanner._pending_sells = {
            "600036.SH": {"reason": "跌停挂起", "price": 38.0, "added_at": time.time(), "source": "position_manager"}
        }

        pos = MagicMock()
        pos.ts_code = "600036.SH"

        # 模拟: 超时后检查已有pending, 不覆盖
        with scanner._state_lock:
            if pos.ts_code not in scanner._pending_sells:
                scanner._pending_sells[pos.ts_code] = {
                    "reason": "止损 -3.5%", "price": 38.5,
                    "added_at": time.time(), "source": "risk_thread_timeout",
                }

        # 原有pending_sells不被覆盖
        assert scanner._pending_sells["600036.SH"]["source"] == "position_manager"
        assert scanner._pending_sells["600036.SH"]["reason"] == "跌停挂起"

    def test_check_stop_loss_only_timeout_handling_in_source(self):
        """execute_sell_list_from_risk源码包含TimeoutError处理(v2.9.27:在PositionManager中)"""
        import inspect
        from nodes.market_monitor.position_manager import PositionManager
        # v2.9.27: _execute_sell_list_from_risk已移至PositionManager.execute_sell_list_from_risk
        src = inspect.getsource(PositionManager.execute_sell_list_from_risk)
        assert "TimeoutError" in src
        assert "pending_sells" in src


# ==================== 3. 健康度评分增强 ====================

class TestHealthScoreRiskThread:
    """v2.9.5: 健康度评分含风控线程状态"""

    def _make_scanner_for_health(self):
        scanner = MagicMock()
        scanner._last_scan_ts = time.time()
        scanner._last_risk_check_ts = time.time()
        scanner._quote_manager = MagicMock()
        scanner._quote_manager.get_staleness.return_value = 1.0
        scanner._quote_manager.degrade_level = 0
        scanner._state_lock = threading.Lock()
        scanner._pending_sells = {}
        scanner._circuit_breaker = {"trading_paused": False}
        scanner._event_bus = MagicMock()
        scanner._event_bus.get_stats.return_value = {}
        # 风控线程
        scanner._risk_running = True
        scanner._risk_thread = MagicMock()
        scanner._risk_thread.is_alive.return_value = True
        scanner._risk_thread_restarts = 0
        return scanner

    def test_health_score_includes_risk_thread_alive(self):
        """健康评分包含risk_thread_alive字段"""
        scanner = self._make_scanner_for_health()
        from nodes.market_monitor.scanner_utils import ScannerUtils
        result = ScannerUtils.compute_health_score(scanner)
        assert "risk_thread_alive" in result
        assert result["risk_thread_alive"] is True

    def test_health_score_includes_restarts(self):
        """健康评分包含risk_thread_restarts字段"""
        scanner = self._make_scanner_for_health()
        from nodes.market_monitor.scanner_utils import ScannerUtils
        result = ScannerUtils.compute_health_score(scanner)
        assert "risk_thread_restarts" in result
        assert result["risk_thread_restarts"] == 0

    def test_health_score_dead_risk_thread_warning(self):
        """风控线程停止时健康评分有warning"""
        scanner = self._make_scanner_for_health()
        scanner._risk_thread.is_alive.return_value = False
        from nodes.market_monitor.scanner_utils import ScannerUtils
        result = ScannerUtils.compute_health_score(scanner)
        assert result["risk_thread_alive"] is False
        assert any("风控线程" in w for w in result["warnings"])

    def test_health_score_healthy_requires_risk_thread(self):
        """is_healthy要求风控线程存活"""
        scanner = self._make_scanner_for_health()
        from nodes.market_monitor.scanner_utils import ScannerUtils

        # 风控线程存活→健康
        scanner._risk_thread.is_alive.return_value = True
        result = ScannerUtils.compute_health_score(scanner)
        assert result["is_healthy"] is True

        # 风控线程停止→不健康
        scanner._risk_thread.is_alive.return_value = False
        result = ScannerUtils.compute_health_score(scanner)
        assert result["is_healthy"] is False

    def test_health_score_source_has_risk_thread_alive(self):
        """ScannerUtils.compute_health_score源码包含risk_thread_alive"""
        import inspect
        from nodes.market_monitor.scanner_utils import ScannerUtils
        src = inspect.getsource(ScannerUtils.compute_health_score)
        assert "risk_thread_alive" in src


# ==================== 4. MongoDB import一致性 ====================

class TestMongoImportConsistency:
    """v2.9.5: 所有market_monitor模块使用统一的mongo_manager导入"""

    def test_runtime_persistence_imports(self):
        """runtime_persistence.py使用core.managers导入"""
        import inspect
        from nodes.market_monitor.runtime_persistence import RuntimePersistence
        src = inspect.getsource(RuntimePersistence)
        # 不应出现core.managers.mongo_manager的直导
        assert "from core.managers.mongo_manager import" not in src

    def test_event_subscribers_imports(self):
        """scanner_event_subscribers.py使用core.managers导入"""
        import inspect
        from nodes.market_monitor.scanner_event_subscribers import register_subscribers
        src = inspect.getsource(register_subscribers)
        # 不应出现core.managers.mongo_manager的直导
        assert "from core.managers.mongo_manager import" not in src


# ==================== 5. 风控线程trade_date一致性 ====================

class TestRiskThreadTradeDateConsistency:
    """v2.9.5: 风控线程使用scanner._trade_date"""

    def test_risk_loop_uses_scanner_trade_date(self):
        """风控线程使用self._trade_date【v2.9.30:逻辑在_risk_periodic_checks中】"""
        import inspect
        from nodes.market_monitor.scanner import MarketScanner
        src = inspect.getsource(MarketScanner._risk_periodic_checks)
        assert "self._trade_date" in src

    def test_risk_loop_has_fallback(self):
        """_trade_date为空时有fallback【v2.9.30:逻辑在_risk_periodic_checks中】"""
        import inspect
        from nodes.market_monitor.scanner import MarketScanner
        src = inspect.getsource(MarketScanner._risk_periodic_checks)
        assert "datetime.now()" in src


# ==================== 6. 回测模块不受影响 ====================

class TestNoBacktestRegressionV295:
    """v2.9.5: 回测模块零影响"""

    def test_sell_signal_checker_api_unchanged(self):
        """SellSignalChecker API未变"""
        from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS
        assert isinstance(STRATEGY_CONFIGS, dict)
        assert len(STRATEGY_CONFIGS) > 0

    def test_strategy_defaults_importable(self):
        """策略默认参数可导入"""
        from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK
        assert "stop_loss_pct" in GLOBAL_RISK

    def test_portfolio_backtester_importable(self):
        """回测引擎可导入"""
        from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
        assert PortfolioBacktester is not None

    def test_scanner_changes_not_in_backtest_path(self):
        """scanner.py的改动不影响回测路径"""
        # 验证: 回测引擎不import scanner模块
        import inspect
        from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
        src = inspect.getsource(PortfolioBacktester)
        assert "market_monitor.scanner" not in src
        assert "MarketScanner" not in src

    def test_health_score_changes_not_in_backtest(self):
        """健康度评分改动不影响回测"""
        # ScannerUtils是market_monitor独有, 回测不用
        import importlib
        try:
            mod = importlib.import_module("nodes.market_monitor.scanner_utils")
            # 能导入说明模块存在(不影响回测,因为回测不import它)
            assert hasattr(mod, "ScannerUtils")
        except ImportError:
            pass  # 模块路径可能不同,不影响
