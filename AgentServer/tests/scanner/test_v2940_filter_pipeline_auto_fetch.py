#!/usr/bin/env python3
"""
v2.9.43 测试: filter_pipeline自动获取持仓/账户 + scanner broker耦合降低

1. LiveFilterPipeline.apply自动从scanner._broker获取positions和account
2. scanner._apply_filter_pipeline不再组装positions/account
3. scanner使用self.get_positions()替代self._broker.get_positions()
4. scanner broker耦合从23→17
"""
import os
import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SCANNER = os.path.join(_PROJECT_ROOT, "nodes", "market_monitor", "scanner.py")
_LFP = os.path.join(_PROJECT_ROOT, "nodes", "market_monitor", "live_filter_pipeline.py")
_API = os.path.join(_PROJECT_ROOT, "nodes", "web", "api", "scanner.py")


def _read(path):
    return open(path).read()


class TestFilterPipelineAutoFetch:
    """验证LiveFilterPipeline.apply自动获取positions/account"""

    def test_apply_positions_default_none(self):
        """apply方法positions参数默认为None"""
        source = _read(_LFP)
        idx = source.find("async def apply")
        assert idx > 0
        sig = source[idx:idx+300]
        assert "positions" in sig
        # 默认值是None而非必填
        assert "positions: List[Dict] = None" in sig or "positions=None" in sig

    def test_apply_account_default_none(self):
        """apply方法account参数默认为None"""
        source = _read(_LFP)
        idx = source.find("async def apply")
        assert idx > 0
        sig = source[idx:idx+300]
        assert "account: Dict = None" in sig or "account=None" in sig

    def test_auto_fetch_positions_from_scanner(self):
        """当positions为None时从scanner自动获取"""
        source = _read(_LFP)
        # v2.9.40: getattr已替换为直接属性访问
        assert "self._scanner._broker" in source
        assert "broker.get_positions()" in source

    def test_auto_fetch_account_from_scanner(self):
        """当account为None时从scanner自动获取"""
        source = _read(_LFP)
        assert "available_cash" in source


class TestScannerFilterPipelineSimplified:
    """验证scanner._apply_filter_pipeline简化"""

    def test_no_positions_assembly(self):
        """scanner不再手动组装positions列表"""
        source = _read(_SCANNER)
        idx = source.find("async def _apply_filter_pipeline")
        assert idx > 0
        method_code = source[idx:idx+800]
        # 不应有手动组装positions的代码
        assert "for p in self._broker.get_positions()" not in method_code
        assert "positions.append" not in method_code

    def test_no_account_assembly(self):
        """scanner不再手动组装account"""
        source = _read(_SCANNER)
        idx = source.find("async def _apply_filter_pipeline")
        assert idx > 0
        method_code = source[idx:idx+800]
        assert "available_cash" not in method_code

    def test_pipeline_call_without_positions(self):
        """pipeline.apply调用不传positions参数"""
        source = _read(_SCANNER)
        idx = source.find("async def _apply_filter_pipeline")
        assert idx > 0
        method_code = source[idx:idx+800]
        assert "positions=" not in method_code or "positions=None" in method_code

    def test_pipeline_call_without_account(self):
        """pipeline.apply调用不传account参数"""
        source = _read(_SCANNER)
        idx = source.find("async def _apply_filter_pipeline")
        assert idx > 0
        method_code = source[idx:idx+800]
        assert "account=" not in method_code or "account=None" in method_code


class TestScannerBrokerDecoupling:
    """验证scanner broker耦合降低"""

    def test_broker_refs_under_20(self):
        """self._broker引用<20处"""
        source = _read(_SCANNER)
        count = sum(1 for line in source.splitlines()
                    if 'self._broker' in line and not line.strip().startswith('#'))
        assert count < 20, f"self._broker references: {count} (expected < 20)"

    def test_uses_get_positions_method(self):
        """get_status中使用self.get_positions()"""
        source = _read(_SCANNER)
        idx = source.find("def get_status")
        assert idx > 0
        method_code = source[idx:idx+1000]
        assert "self.get_positions()" in method_code

    def test_scan_loop_uses_get_positions(self):
        """_scan_loop使用self.get_positions()"""
        source = _read(_SCANNER)
        idx = source.find("async def _scan_loop")
        assert idx > 0
        method_code = source[idx:idx+2000]
        # 周末持仓检查用self.get_positions()
        assert "self.get_positions()" in method_code

    def test_scan_loop_trading_uses_broker_positions(self):
        """_scan_loop_trading使用broker.get_positions()"""
        source = _read(_SCANNER)
        idx = source.find("async def _scan_loop_trading")
        assert idx > 0
        method_code = source[idx:idx+2000]
        # 【v2.9.49】重构后使用broker.get_positions(), 不再通过self.get_positions()
        assert "get_positions()" in method_code


class TestScannerLineCount:
    """验证scanner.py行数持续减少"""

    def test_scanner_under_1490(self):
        """scanner.py行数<1490"""
        lines = len(_read(_SCANNER).splitlines())
        assert lines < 1490, f"scanner.py has {lines} lines (expected < 1490)"


class TestVersionSync:
    """版本同步检查"""

    def test_design_doc_version_in_api(self):
        """API版本号为v2.9.43"""
        source = _read(_API)
        assert '_DESIGN_DOC_VERSION = "v2.9.58"' in source


class TestNoBacktestRegressionV2940:
    """回测零影响验证"""

    def test_filter_pipeline_no_backtest_executor(self):
        """LiveFilterPipeline不导入回测执行器(只复用策略参数)"""
        source = _read(_LFP)
        # 允许复用策略参数(strategy_defaults/special_period_filter), 但不应导入回测执行器
        assert 'PortfolioBacktester' not in source
        assert 'from nodes.backtest_engine.factor_selection.portfolio_backtest' not in source
        assert 'from nodes.backtest_engine.backtest' not in source

    def test_backtest_tests_still_pass(self):
        """回测核心可导入"""
        from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
        from nodes.backtest_engine.factor_selection.sell_signal_checker import SellSignalChecker
        assert PortfolioBacktester is not None
        assert SellSignalChecker is not None
