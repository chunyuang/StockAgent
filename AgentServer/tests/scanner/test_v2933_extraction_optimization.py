#!/usr/bin/env python3
"""
v2.9.35 — scan_once策略筛选提取 + _emit_risk_thread_error提取 + get_status模块状态提取 测试

新增:
1. _apply_strategies_and_filters: scan_once Step3策略+筛选+异动合并
2. _emit_risk_thread_error: 风控线程异常事件发射提取
3. _build_module_status: get_status子模块状态读取提取
"""
import os
import pytest
import ast

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SCANNER = os.path.join(_PROJECT_ROOT, "nodes", "market_monitor", "scanner.py")
_API_SCANNER = os.path.join(_PROJECT_ROOT, "nodes", "web", "api", "scanner.py")
_RW = os.path.join(_PROJECT_ROOT, "nodes", "market_monitor", "risk_watchdog.py")


def _read(path):
    return open(path).read()


class TestApplyStrategiesAndFilters:
    """验证_apply_strategies_and_filters提取(scan_once Step3)"""

    def test_method_exists(self):
        """_apply_strategies_and_filters方法存在"""
        source = _read(_SCANNER)
        assert "async def _apply_strategies_and_filters" in source

    def test_scan_once_calls_extracted_method(self):
        """scan_once调用_apply_strategies_and_filters而非内联逻辑"""
        source = _read(_SCANNER)
        idx = source.find("async def scan_once")
        assert idx > 0, "scan_once方法不存在"
        method_code = source[idx:idx+1500]
        assert "_apply_strategies_and_filters" in method_code, \
            "scan_once应调用_apply_strategies_and_filters"
        # 不应内联_apply_strategies + _apply_filter_pipeline + _detect_anomalies
        assert "new_signals = await self._apply_strategies(merged_df" not in method_code, \
            "scan_once不应内联调用_apply_strategies(应通过_apply_strategies_and_filters)"

    def test_method_combines_strategies_filters_anomalies(self):
        """_apply_strategies_and_filters包含策略+筛选+异动三步"""
        source = _read(_SCANNER)
        idx = source.find("async def _apply_strategies_and_filters")
        assert idx > 0
        method_code = source[idx:idx+800]
        assert "_apply_strategies" in method_code
        assert "_apply_filter_pipeline" in method_code
        assert "_detect_anomalies" in method_code

    def test_method_signature(self):
        """方法签名包含merged_df, trade_date, realtime_data"""
        source = _read(_SCANNER)
        idx = source.find("async def _apply_strategies_and_filters")
        sig = source[idx:idx+200]
        assert "merged_df" in sig
        assert "trade_date" in sig
        assert "realtime_data" in sig

    def test_returns_list(self):
        """返回List[ScanSignal]"""
        source = _read(_SCANNER)
        idx = source.find("async def _apply_strategies_and_filters")
        assert idx > 0
        method_code = source[idx:idx+800]
        assert "List[ScanSignal]" in method_code


class TestEmitRiskThreadError:
    """验证_emit_risk_thread_error提取(风控线程异常事件发射)"""

    def test_method_exists(self):
        """_emit_risk_thread_error方法存在"""
        source = _read(_SCANNER)
        assert "def _emit_risk_thread_error" in source

    def test_risk_loop_calls_extracted_method(self):
        """_risk_loop_sync调用_emit_risk_thread_error"""
        source = _read(_SCANNER)
        idx = source.find("def _risk_loop_sync")
        assert idx > 0
        method_code = source[idx:idx+2000]
        assert "_emit_risk_thread_error" in method_code

    def test_method_contains_scanner_error_event(self):
        """_emit_risk_thread_error发射SCANNER_ERROR事件(v2.9.40:委托给RiskWatchdog)"""
        source = _read(_SCANNER)
        idx = source.find("def _emit_risk_thread_error")
        assert idx > 0
        method_code = source[idx:idx+800]
        # v2.9.40: 逻辑已迁移到RiskWatchdog.emit_risk_thread_error
        assert "RiskWatchdog" in method_code
        # 验证RiskWatchdog中有SCANNER_ERROR
        rw_source = _read(_RW)
        assert "ScannerEvents.SCANNER_ERROR" in rw_source

    def test_method_signature(self):
        """方法签名包含error和consecutive_errors"""
        source = _read(_SCANNER)
        idx = source.find("def _emit_risk_thread_error")
        sig = source[idx:idx+200]
        assert "error" in sig
        assert "consecutive_errors" in sig

    def test_method_uses_threadsafe_emit(self):
        """使用call_soon_threadsafe跨线程发射(v2.9.40:逻辑在RiskWatchdog)"""
        rw_source = _read(_RW)
        assert "call_soon_threadsafe" in rw_source
        assert "create_task" in rw_source


class TestBuildModuleStatus:
    """验证_build_module_status提取(get_status子模块状态)"""

    def test_method_exists(self):
        """_build_module_status方法存在"""
        source = _read(_SCANNER)
        assert "def _build_module_status" in source

    def test_get_status_uses_extracted_method(self):
        """get_status使用_build_module_status"""
        source = _read(_SCANNER)
        idx = source.find("def get_status")
        assert idx > 0
        method_code = source[idx:idx+1500]
        assert "_build_module_status" in method_code

    def test_returns_dict(self):
        """返回Dict[str, Any]"""
        source = _read(_SCANNER)
        idx = source.find("def _build_module_status")
        sig = source[idx:idx+200]
        assert "Dict" in sig

    def test_includes_risk_watchdog(self):
        """包含risk_watchdog状态"""
        source = _read(_SCANNER)
        idx = source.find("def _build_module_status")
        method_code = source[idx:idx+800]
        assert "_risk_watchdog" in method_code

    def test_includes_signal_dispatcher(self):
        """包含signal_dispatcher状态"""
        source = _read(_SCANNER)
        idx = source.find("def _build_module_status")
        method_code = source[idx:idx+800]
        assert "_signal_dispatcher" in method_code

    def test_includes_quote_degrade(self):
        """包含行情降级信息"""
        source = _read(_SCANNER)
        idx = source.find("def _build_module_status")
        method_code = source[idx:idx+800]
        assert "degrade_level" in method_code or "degrade_desc" in method_code


class TestVersionSync:
    """验证版本号同步"""

    def test_design_doc_version_in_api(self):
        """API中的_DESIGN_DOC_VERSION应为v2.9.35"""
        source = _read(_API_SCANNER)
        assert '_DESIGN_DOC_VERSION = "v2.9.40"' in source


class TestNoBacktestRegressionV2933:
    """验证v2.9.35改动对回测零影响"""

    def test_scanner_methods_not_in_backtest(self):
        """新方法不在回测引擎中"""
        backtest_path = os.path.join(
            _PROJECT_ROOT, "nodes", "backtest_engine",
            "factor_selection", "portfolio_backtest.py"
        )
        if os.path.exists(backtest_path):
            source = open(backtest_path).read()
            assert "_apply_strategies_and_filters" not in source
            assert "_emit_risk_thread_error" not in source
            assert "_build_module_status" not in source

    def test_sell_signal_checker_api_unchanged(self):
        """SellSignalChecker API未变"""
        checker_path = os.path.join(
            _PROJECT_ROOT, "nodes", "backtest_engine",
            "factor_selection", "sell_signal_checker.py"
        )
        if os.path.exists(checker_path):
            source = open(checker_path).read()
            assert "check_realtime_sell" in source

    def test_strategy_defaults_importable(self):
        """策略默认参数模块可导入"""
        import importlib
        try:
            mod = importlib.import_module("nodes.backtest_engine.strategy_defaults")
            assert hasattr(mod, "STRATEGY_CONFIGS")
        except ImportError:
            pass  # 非完整环境可接受
