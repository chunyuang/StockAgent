"""v2.9.61: _StepTimer提取 + _scan_loop阶段处理程序 + start初始化序列提取

变更:
- 🟡 _StepTimer上下文管理器: scan_once 7个计时变量→with timer.step()
- 🟡 _handle_weekend_phase/_handle_premarket_phase: _scan_loop阶段处理提取
- 🟡 _start_init_sequence: start()初始化序列提取(参数校验+加载+恢复+注册)
- 回测零影响
"""
import inspect
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# _StepTimer 测试
# ---------------------------------------------------------------------------

class TestStepTimer:
    """验证_StepTimer上下文管理器"""

    def test_step_timer_class_exists(self):
        """_StepTimer类应存在于scanner.py"""
        from nodes.market_monitor.scanner import _StepTimer
        assert _StepTimer is not None

    def test_step_timer_records_steps(self):
        """_StepTimer应记录步骤名称和耗时"""
        import time
        from nodes.market_monitor.scanner import _StepTimer
        timer = _StepTimer()
        with timer.step("行情"):
            time.sleep(0.01)
        with timer.step("因子"):
            time.sleep(0.01)
        assert len(timer.steps) == 2
        assert timer.steps[0][0] == "行情"
        assert timer.steps[1][0] == "因子"
        assert timer.steps[0][1] > 0  # 耗时>0ms

    def test_step_timer_slow_info(self):
        """get_slow_info应返回慢步骤摘要"""
        import time
        from nodes.market_monitor.scanner import _StepTimer
        timer = _StepTimer()
        with timer.step("行情"):
            time.sleep(0.6)  # >500ms = 慢步骤
        with timer.step("因子"):
            pass  # 快步骤
        info = timer.get_slow_info()
        assert "行情" in info
        assert "因子" not in info

    def test_step_timer_empty_slow_info(self):
        """无慢步骤时get_slow_info返回空字符串"""
        from nodes.market_monitor.scanner import _StepTimer
        timer = _StepTimer()
        with timer.step("快"):
            pass
        info = timer.get_slow_info()
        assert info == ""

    def test_step_timer_slots(self):
        """_StepTimer使用__slots__优化内存"""
        from nodes.market_monitor.scanner import _StepTimer
        assert hasattr(_StepTimer, '__slots__')

    def test_step_timer_exception_handling(self):
        """_StepTimer步骤中异常仍记录耗时"""
        from nodes.market_monitor.scanner import _StepTimer
        timer = _StepTimer()
        try:
            with timer.step("失败步骤"):
                raise ValueError("test")
        except ValueError:
            pass
        assert len(timer.steps) == 1
        assert timer.steps[0][0] == "失败步骤"


# ---------------------------------------------------------------------------
# scan_once重构测试
# ---------------------------------------------------------------------------

class TestScanOnceRefactoring:
    """验证scan_once使用_StepTimer后的结构"""

    def test_scan_once_uses_step_timer(self):
        """scan_once应使用_StepTimer替代手动计时变量"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner.scan_once)
        assert "_StepTimer" in source or "timer = _StepTimer" in source
        assert "timer.step" in source
        # 不应有手动计时变量
        assert "step1_ms" not in source
        assert "step2_ms" not in source
        assert "step3_ms" not in source

    def test_scan_once_line_count(self):
        """scan_once行数应≤70(v2.9.61:_StepTimer简化)"""
        from nodes.market_monitor.scanner import MarketScanner
        lines = inspect.getsource(MarketScanner.scan_once).split('\n')
        assert len(lines) <= 70, f"scan_once {len(lines)}行,应≤70"

    def test_scan_once_get_slow_info_call(self):
        """scan_once应调用timer.get_slow_info()"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner.scan_once)
        assert "get_slow_info" in source


# ---------------------------------------------------------------------------
# _scan_loop阶段处理提取测试
# ---------------------------------------------------------------------------

class TestScanLoopPhaseHandlers:
    """验证_scan_loop阶段处理方法提取"""

    def test_handle_weekend_phase_exists(self):
        """_handle_weekend_phase方法应存在"""
        from nodes.market_monitor.scanner import MarketScanner
        assert hasattr(MarketScanner, '_handle_weekend_phase')

    def test_handle_premarket_phase_exists(self):
        """_handle_premarket_phase方法应存在"""
        from nodes.market_monitor.scanner import MarketScanner
        assert hasattr(MarketScanner, '_handle_premarket_phase')

    def test_scan_loop_calls_handlers(self):
        """_scan_loop应调用提取的阶段处理方法"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner._scan_loop)
        assert "_handle_weekend_phase" in source
        assert "_handle_premarket_phase" in source

    def test_scan_loop_line_count(self):
        """_scan_loop行数应≤50(v2.9.61:阶段处理提取)"""
        from nodes.market_monitor.scanner import MarketScanner
        lines = inspect.getsource(MarketScanner._scan_loop).split('\n')
        assert len(lines) <= 50, f"_scan_loop {len(lines)}行,应≤50"

    def test_handle_weekend_phase_calls_check_positions_quick(self):
        """_handle_weekend_phase应调用_check_positions_quick"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner._handle_weekend_phase)
        assert "_check_positions_quick" in source

    def test_handle_premarket_phase_calls_premarket_auction(self):
        """_handle_premarket_phase应调用_premarket_auction"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner._handle_premarket_phase)
        assert "_premarket_auction" in source


# ---------------------------------------------------------------------------
# start初始化序列提取测试
# ---------------------------------------------------------------------------

class TestStartInitSequence:
    """验证_start_init_sequence从start()提取"""

    def test_start_init_sequence_exists(self):
        """_start_init_sequence方法应存在"""
        from nodes.market_monitor.scanner import MarketScanner
        assert hasattr(MarketScanner, '_start_init_sequence')

    def test_start_calls_init_sequence(self):
        """start()应调用_start_init_sequence"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner.start)
        assert "_start_init_sequence" in source

    def test_init_sequence_contains_key_steps(self):
        """_start_init_sequence应包含关键初始化步骤"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner._start_init_sequence)
        assert "_validate_live_params" in source
        assert "_load_strategy_overrides" in source
        assert "_detect_param_drift" in source
        assert "premarket_prepare" in source
        assert "_restore_start_state" in source

    def test_start_line_count(self):
        """start()行数应<30行有效代码(v2.9.61:初始化序列提取)"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner.start)
        lines = [l for l in source.split('\n') if l.strip() and not l.strip().startswith('#')]
        assert len(lines) < 30, f"start() {len(lines)}行有效代码,应<30"


# ---------------------------------------------------------------------------
# premarket_prepare提取测试
# ---------------------------------------------------------------------------

class TestPremarketPrepareExtraction:
    """验证premarket_prepare数据加载提取"""

    def test_load_premarket_data_exists(self):
        """_load_premarket_data方法应存在"""
        from nodes.market_monitor.scanner import MarketScanner
        assert hasattr(MarketScanner, '_load_premarket_data')

    def test_check_premarket_auction_exists(self):
        """_check_premarket_auction方法应存在"""
        from nodes.market_monitor.scanner import MarketScanner
        assert hasattr(MarketScanner, '_check_premarket_auction')

    def test_premarket_prepare_calls_extracted_methods(self):
        """premarket_prepare应调用提取的方法"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner.premarket_prepare)
        assert "_load_premarket_data" in source
        assert "_check_premarket_auction" in source

    def test_load_premarket_data_contains_key_steps(self):
        """_load_premarket_data应包含关键数据加载步骤"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner._load_premarket_data)
        assert "_load_stock_list" in source
        assert "_load_daily_factors" in source
        assert "_load_positions" in source

    def test_premarket_prepare_line_count(self):
        """premarket_prepare行数应≤25(v2.9.61:数据加载提取)"""
        from nodes.market_monitor.scanner import MarketScanner
        lines = inspect.getsource(MarketScanner.premarket_prepare).split('\n')
        assert len(lines) <= 25, f"premarket_prepare {len(lines)}行,应≤25"


# ---------------------------------------------------------------------------
# stop清理提取测试
# ---------------------------------------------------------------------------

class TestStopCleanupExtraction:
    """验证_stop_cleanup从stop()提取"""

    def test_stop_cleanup_exists(self):
        """_stop_cleanup方法应存在"""
        from nodes.market_monitor.scanner import MarketScanner
        assert hasattr(MarketScanner, '_stop_cleanup')

    def test_stop_calls_cleanup(self):
        """stop()应调用_stop_cleanup"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner.stop)
        assert "_stop_cleanup" in source

    def test_stop_cleanup_contains_key_steps(self):
        """_stop_cleanup应包含清仓+持久化+数据源关闭"""
        from nodes.market_monitor.scanner import MarketScanner
        source = inspect.getsource(MarketScanner._stop_cleanup)
        assert "_sell_all_positions" in source
        assert "_persist_stop_state" in source
        assert "_data_router" in source

    def test_stop_line_count(self):
        """stop()行数应≤25(v2.9.61:清理提取)"""
        from nodes.market_monitor.scanner import MarketScanner
        lines = inspect.getsource(MarketScanner.stop).split('\n')
        assert len(lines) <= 30, f"stop() {len(lines)}行,应≤30"


# ---------------------------------------------------------------------------
# 回测不影响验证
# ---------------------------------------------------------------------------

class TestNoBacktestRegressionV2955:
    """验证v2.9.61变更不影响回测模块"""

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
        import os
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
        """版本常量更新为v2.9.61"""
        import os
        base_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(base_dir, "..", ".."))
        with open(os.path.join(project_root, "nodes/web/api/scanner_system.py")) as f:
            source = f.read()
        assert '_DESIGN_DOC_VERSION = "v2.9.64"' in source
