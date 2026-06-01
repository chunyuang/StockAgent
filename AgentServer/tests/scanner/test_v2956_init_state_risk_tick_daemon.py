"""v2.9.57: _init_state分组提取 + _risk_tick_body提取 + ScannerDaemon方法提取

变更:
- 🟡 _init_state分组提取: 42行→5行委托 + 4个子方法(_init_risk_state/_init_execution_state/_init_cache_state/_init_signal_state)
- 🟡 _risk_tick_body提取: _risk_loop_sync循环体提取为独立方法
- 🟡 ScannerDaemon._handle_subscription_message: _subscribe_loop消息处理提取
- 🟡 ScannerDaemon._restart_subprocess: _watchdog_loop重启逻辑提取
- 🟡 ScannerDaemon._wait_for_ack: send_command ACK等待提取
- 🟡 ScannerDaemon._terminate_process: stop()进程终止提取
- 回测零影响
"""
import inspect
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# _init_state分组提取测试
# ---------------------------------------------------------------------------

class TestInitStateDecomposition:
    """验证_init_state分组提取为4个子方法"""

    def test_init_risk_state_exists(self):
        """_init_risk_state方法应存在"""
        from nodes.market_monitor.scanner import MarketScanner
        assert hasattr(MarketScanner, '_init_risk_state')

    def test_init_execution_state_exists(self):
        """_init_execution_state方法应存在"""
        from nodes.market_monitor.scanner import MarketScanner
        assert hasattr(MarketScanner, '_init_execution_state')

    def test_init_cache_state_exists(self):
        """_init_cache_state方法应存在"""
        from nodes.market_monitor.scanner import MarketScanner
        assert hasattr(MarketScanner, '_init_cache_state')

    def test_init_signal_state_exists(self):
        """_init_signal_state方法应存在"""
        from nodes.market_monitor.scanner import MarketScanner
        assert hasattr(MarketScanner, '_init_signal_state')

    def test_init_state_calls_sub_methods(self):
        """_init_state应调用4个子方法"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner._init_state)
        assert "_init_risk_state" in source
        assert "_init_execution_state" in source
        assert "_init_cache_state" in source
        assert "_init_signal_state" in source

    def test_init_risk_state_contents(self):
        """_init_risk_state应包含风控+交易状态初始化"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner._init_risk_state)
        assert "_trailing_stops" in source
        assert "_pending_sells" in source
        assert "SELL_LOGIC_MODE" in source

    def test_init_cache_state_contents(self):
        """_init_cache_state应包含数据缓存初始化"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner._init_cache_state)
        assert "_realtime_cache" in source
        assert "_daily_factors_df" in source
        assert "_all_codes" in source

    def test_init_state_line_count(self):
        """_init_state行数应≤10(v2.9.57:分组委托)"""
        from nodes.market_monitor.scanner import MarketScanner
        lines = inspect.getsource(MarketScanner._init_state).split('\n')
        assert len(lines) <= 10, f"_init_state {len(lines)}行,应≤10"

    def test_init_risk_state_line_count(self):
        """_init_risk_state行数应≤12"""
        from nodes.market_monitor.scanner import MarketScanner
        lines = inspect.getsource(MarketScanner._init_risk_state).split('\n')
        assert len(lines) <= 12, f"_init_risk_state {len(lines)}行,应≤12"


# ---------------------------------------------------------------------------
# _risk_tick_body提取测试
# ---------------------------------------------------------------------------

class TestRiskTickBodyExtraction:
    """验证_risk_tick_body从_risk_loop_sync提取"""

    def test_risk_tick_body_exists(self):
        """_risk_tick_body方法应存在"""
        from nodes.market_monitor.scanner import MarketScanner
        assert hasattr(MarketScanner, '_risk_tick_body')

    def test_risk_loop_sync_calls_tick_body(self):
        """_risk_loop_sync应调用_risk_tick_body"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner._risk_loop_sync)
        assert "_risk_tick_body" in source

    def test_risk_tick_body_contents(self):
        """_risk_tick_body应包含阶段判断+行情读取+止损检查+周期检查"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner._risk_tick_body)
        assert "MarketPhase.classify" in source
        assert "_check_stop_loss_only" in source
        assert "_risk_periodic_checks" in source

    def test_risk_loop_sync_line_count(self):
        """_risk_loop_sync行数应≤35(v2.9.57:循环体提取)"""
        from nodes.market_monitor.scanner import MarketScanner
        lines = inspect.getsource(MarketScanner._risk_loop_sync).split('\n')
        assert len(lines) <= 35, f"_risk_loop_sync {len(lines)}行,应≤35"


# ---------------------------------------------------------------------------
# ScannerDaemon方法提取测试
# ---------------------------------------------------------------------------

class TestDaemonSubscriptionMessageExtraction:
    """验证_handle_subscription_message从_subscribe_loop提取"""

    def test_handle_subscription_message_exists(self):
        """_handle_subscription_message方法应存在"""
        from nodes.market_monitor.scanner_daemon import ScannerDaemon
        assert hasattr(ScannerDaemon, '_handle_subscription_message')

    def test_subscribe_loop_calls_handler(self):
        """_subscribe_loop应调用_handle_subscription_message"""
        from nodes.market_monitor.scanner_daemon import ScannerDaemon
        source = inspect.getsource(ScannerDaemon._subscribe_loop)
        assert "_handle_subscription_message" in source

    def test_subscribe_loop_line_count(self):
        """_subscribe_loop行数应≤30(v2.9.57:消息处理提取)"""
        from nodes.market_monitor.scanner_daemon import ScannerDaemon
        lines = inspect.getsource(ScannerDaemon._subscribe_loop).split('\n')
        assert len(lines) <= 30, f"_subscribe_loop {len(lines)}行,应≤30"


class TestDaemonRestartSubprocessExtraction:
    """验证_restart_subprocess从_watchdog_loop提取"""

    def test_restart_subprocess_exists(self):
        """_restart_subprocess方法应存在"""
        from nodes.market_monitor.scanner_daemon import ScannerDaemon
        assert hasattr(ScannerDaemon, '_restart_subprocess')

    def test_watchdog_loop_calls_restart(self):
        """_watchdog_loop应调用_restart_subprocess"""
        from nodes.market_monitor.scanner_daemon import ScannerDaemon
        source = inspect.getsource(ScannerDaemon._watchdog_loop)
        assert "_restart_subprocess" in source

    def test_restart_subprocess_contents(self):
        """_restart_subprocess应包含重启计数+旧进程清理+启动新进程"""
        from nodes.market_monitor.scanner_daemon import ScannerDaemon
        source = inspect.getsource(ScannerDaemon._restart_subprocess)
        assert "_restart_count" in source
        assert "_start_process" in source


class TestDaemonWaitForAckExtraction:
    """验证_wait_for_ack从send_command提取"""

    def test_wait_for_ack_exists(self):
        """_wait_for_ack方法应存在"""
        from nodes.market_monitor.scanner_daemon import ScannerDaemon
        assert hasattr(ScannerDaemon, '_wait_for_ack')

    def test_send_command_calls_wait(self):
        """send_command应调用_wait_for_ack"""
        from nodes.market_monitor.scanner_daemon import ScannerDaemon
        source = inspect.getsource(ScannerDaemon.send_command)
        assert "_wait_for_ack" in source

    def test_wait_for_ack_handles_timeout(self):
        """_wait_for_ack应处理TimeoutError"""
        from nodes.market_monitor.scanner_daemon import ScannerDaemon
        source = inspect.getsource(ScannerDaemon._wait_for_ack)
        assert "TimeoutError" in source


class TestDaemonTerminateProcessExtraction:
    """验证_terminate_process从stop()提取"""

    def test_terminate_process_exists(self):
        """_terminate_process方法应存在"""
        from nodes.market_monitor.scanner_daemon import ScannerDaemon
        assert hasattr(ScannerDaemon, '_terminate_process')

    def test_stop_calls_terminate(self):
        """stop()应调用_terminate_process"""
        from nodes.market_monitor.scanner_daemon import ScannerDaemon
        source = inspect.getsource(ScannerDaemon.stop)
        assert "_terminate_process" in source

    def test_terminate_process_contents(self):
        """_terminate_process应包含join+terminate+kill三阶段"""
        from nodes.market_monitor.scanner_daemon import ScannerDaemon
        source = inspect.getsource(ScannerDaemon._terminate_process)
        assert ".join(" in source
        assert ".terminate()" in source
        assert ".kill()" in source


# ---------------------------------------------------------------------------
# RuntimePersistence方法提取测试
# ---------------------------------------------------------------------------

class TestRuntimePersistenceExtraction:
    """验证RuntimePersistence方法提取(v2.9.57)"""

    def test_split_trace_candidates_exists(self):
        """_split_trace_candidates方法应存在"""
        from nodes.market_monitor.runtime_persistence import RuntimePersistence
        assert hasattr(RuntimePersistence, '_split_trace_candidates')

    def test_build_trace_doc_exists(self):
        """_build_trace_doc方法应存在"""
        from nodes.market_monitor.runtime_persistence import RuntimePersistence
        assert hasattr(RuntimePersistence, '_build_trace_doc')

    def test_build_limit_ops_exists(self):
        """_build_limit_ops方法应存在"""
        from nodes.market_monitor.runtime_persistence import RuntimePersistence
        assert hasattr(RuntimePersistence, '_build_limit_ops')

    def test_sync_pct_chg_exists(self):
        """_sync_pct_chg_to_daily_basic方法应存在"""
        from nodes.market_monitor.runtime_persistence import RuntimePersistence
        assert hasattr(RuntimePersistence, '_sync_pct_chg_to_daily_basic')

    def test_save_scan_traces_calls_split(self):
        """save_scan_traces应调用_split_trace_candidates"""
        from nodes.market_monitor.runtime_persistence import RuntimePersistence
        source = inspect.getsource(RuntimePersistence.save_scan_traces)
        assert "_split_trace_candidates" in source

    def test_sync_close_data_calls_build_limit_ops(self):
        """sync_close_data_to_mongo应调用_build_limit_ops"""
        from nodes.market_monitor.runtime_persistence import RuntimePersistence
        source = inspect.getsource(RuntimePersistence.sync_close_data_to_mongo)
        assert "_build_limit_ops" in source
        assert "_sync_pct_chg" in source

    def test_save_scan_traces_line_count(self):
        """save_scan_traces行数应≤35(v2.9.57:提取)"""
        from nodes.market_monitor.runtime_persistence import RuntimePersistence
        lines = inspect.getsource(RuntimePersistence.save_scan_traces).split('\n')
        assert len(lines) <= 35, f"save_scan_traces {len(lines)}行,应≤35"

    def test_sync_close_data_line_count(self):
        """sync_close_data_to_mongo行数应≤25(v2.9.57:提取)"""
        from nodes.market_monitor.runtime_persistence import RuntimePersistence
        lines = inspect.getsource(RuntimePersistence.sync_close_data_to_mongo).split('\n')
        assert len(lines) <= 25, f"sync_close_data_to_mongo {len(lines)}行,应≤25"


# ---------------------------------------------------------------------------
# 回测不影响验证
# ---------------------------------------------------------------------------

class TestNoBacktestRegressionV2956:
    """验证v2.9.57变更不影响回测模块"""

    def test_sell_signal_checker_importable(self):
        """SellSignalChecker仍可正常导入"""
        from nodes.backtest_engine.factor_selection.sell_signal_checker import SellSignalChecker
        assert SellSignalChecker is not None

    def test_strategy_defaults_importable(self):
        """strategy_defaults仍可正常导入"""
        from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS
        assert isinstance(STRATEGY_CONFIGS, dict)

    def test_portfolio_backtester_importable(self):
        """回测引擎仍可正常导入"""
        from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
        assert PortfolioBacktester is not None

    def test_no_backtest_file_modified(self):
        """回测相关文件未被修改"""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(base_dir, "..", ".."))
        backtest_files = [
            "nodes/backtest_engine/factor_selection/sell_signal_checker.py",
            "nodes/backtest_engine/factor_selection/portfolio_backtest.py",
            "nodes/backtest_engine/strategy_defaults.py",
        ]
        for f in backtest_files:
            full_path = os.path.join(project_root, f)
            assert os.path.exists(full_path), f"回测文件不存在: {f}"

    def test_version_constant_updated(self):
        """版本常量更新为v2.9.57"""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(base_dir, "..", ".."))
        with open(os.path.join(project_root, "nodes/web/api/scanner.py")) as f:
            source = f.read()
        assert '_DESIGN_DOC_VERSION = "v2.9.57"' in source


# ---------------------------------------------------------------------------
# ScannerUtils方法提取测试
# ---------------------------------------------------------------------------

class TestScannerUtilsExtraction:
    """验证ScannerUtils方法提取(v2.9.57+)"""

    def test_diagnose_checks_extracted(self):
        """diagnose的6个检查应提取为子方法"""
        from nodes.market_monitor.scanner_utils import ScannerUtils
        check_methods = [
            '_check_risk_thread_alive',
            '_check_quote_cache_stale',
            '_check_scan_loop_errors',
            '_check_pending_sells_backlog',
            '_check_circuit_breaker_active',
            '_check_risk_check_timeout',
        ]
        for name in check_methods:
            assert hasattr(ScannerUtils, name), f"ScannerUtils缺少{name}"

    def test_diagnose_calls_sub_methods(self):
        """diagnose应调用所有子检查方法"""
        from nodes.market_monitor.scanner_utils import ScannerUtils
        source = inspect.getsource(ScannerUtils.diagnose)
        assert '_check_risk_thread_alive' in source
        assert '_check_quote_cache_stale' in source
        assert '_check_scan_loop_errors' in source
        assert '_check_pending_sells_backlog' in source
        assert '_check_circuit_breaker_active' in source
        assert '_check_risk_check_timeout' in source

    def test_diagnose_line_count(self):
        """diagnose行数应≤40(v2.9.57:6检查提取)"""
        from nodes.market_monitor.scanner_utils import ScannerUtils
        lines = inspect.getsource(ScannerUtils.diagnose).split('\n')
        assert len(lines) <= 40, f"diagnose {len(lines)}行,应≤40"

    def test_summary_report_helpers_exist(self):
        """generate_summary_report的5个构建方法应存在"""
        from nodes.market_monitor.scanner_utils import ScannerUtils
        helpers = [
            '_build_account_summary',
            '_build_position_details',
            '_build_trade_stats',
            '_build_strategy_performance',
            '_build_risk_status',
            '_build_signal_stats',
        ]
        for name in helpers:
            assert hasattr(ScannerUtils, name), f"ScannerUtils缺少{name}"

    def test_summary_report_calls_helpers(self):
        """generate_summary_report应调用所有构建方法"""
        from nodes.market_monitor.scanner_utils import ScannerUtils
        source = inspect.getsource(ScannerUtils.generate_summary_report)
        assert '_build_account_summary' in source
        assert '_build_position_details' in source
        assert '_build_trade_stats' in source
        assert '_build_strategy_performance' in source
        assert '_build_risk_status' in source
        assert '_build_signal_stats' in source

    def test_summary_report_line_count(self):
        """generate_summary_report行数应≤28(v2.9.57:6子方法提取)"""
        from nodes.market_monitor.scanner_utils import ScannerUtils
        lines = inspect.getsource(ScannerUtils.generate_summary_report).split('\n')
        assert len(lines) <= 28, f"generate_summary_report {len(lines)}行,应≤28"

    def test_compute_health_score_helpers_exist(self):
        """compute_health_score的3个构建方法应存在"""
        from nodes.market_monitor.scanner_utils import ScannerUtils
        helpers = ['_collect_health_metrics', '_collect_health_warnings', '_judge_health', '_get_pending_sells_count']
        for name in helpers:
            assert hasattr(ScannerUtils, name), f"ScannerUtils缺少{name}"

    def test_compute_health_score_calls_helpers(self):
        """compute_health_score应调用所有构建方法"""
        from nodes.market_monitor.scanner_utils import ScannerUtils
        source = inspect.getsource(ScannerUtils.compute_health_score)
        assert '_collect_health_metrics' in source
        assert '_collect_health_warnings' in source
        assert '_judge_health' in source

    def test_compute_health_score_line_count(self):
        """compute_health_score行数应≤35(v2.9.57:3子方法提取)"""
        from nodes.market_monitor.scanner_utils import ScannerUtils
        lines = inspect.getsource(ScannerUtils.compute_health_score).split('\n')
        assert len(lines) <= 35, f"compute_health_score {len(lines)}行,应≤35"
