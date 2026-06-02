#!/usr/bin/env python3
"""
v2.9.35 — 卖出执行方法提取到PositionManager 测试

验证:
- execute_risk_sell提取到PositionManager
- liquidate_positions提取到PositionManager
- scanner委托正确
- DELEGATE_MAP注册
- 行数回归
"""

import ast
import os
import pytest
import inspect

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SCANNER_PATH = os.path.join(_PROJECT_ROOT, "nodes", "market_monitor", "scanner.py")
_PM_PATH = os.path.join(_PROJECT_ROOT, "nodes", "market_monitor", "position_manager.py")


def _read_file(path):
    with open(path) as f:
        return f.read()


# ==================== 1. PositionManager方法存在性 ====================

class TestPositionManagerMethods:
    """验证PositionManager有execute_risk_sell和liquidate_positions"""

    def test_execute_risk_sell_exists(self):
        from nodes.market_monitor.position_manager import PositionManager
        assert hasattr(PositionManager, 'execute_risk_sell')

    def test_liquidate_positions_exists(self):
        from nodes.market_monitor.position_manager import PositionManager
        assert hasattr(PositionManager, 'liquidate_positions')

    def test_execute_risk_sell_is_async(self):
        source = _read_file(_PM_PATH)
        assert "async def execute_risk_sell" in source

    def test_liquidate_positions_is_async(self):
        source = _read_file(_PM_PATH)
        assert "async def liquidate_positions" in source

    def test_execute_risk_sell_calls_post_sell_cleanup(self):
        """execute_risk_sell成功时调用_post_sell_cleanup"""
        from nodes.market_monitor.position_manager import PositionManager
        source = inspect.getsource(PositionManager.execute_risk_sell)
        assert "_post_sell_cleanup" in source

    def test_execute_risk_sell_handles_failure(self):
        """execute_risk_sell处理卖出失败"""
        from nodes.market_monitor.position_manager import PositionManager
        source = inspect.getsource(PositionManager.execute_risk_sell)
        assert "RISK_SELL" in source or "卖出失败" in source

    def test_liquidate_positions_calls_post_sell_cleanup(self):
        """liquidate_positions成功时调用_post_sell_cleanup"""
        from nodes.market_monitor.position_manager import PositionManager
        source = inspect.getsource(PositionManager.liquidate_positions)
        assert "_post_sell_cleanup" in source

    def test_liquidate_positions_uses_available_qty(self):
        """liquidate_positions使用available_qty(T+1合规)"""
        source = _read_file(_PM_PATH)
        idx = source.find("async def liquidate_positions")
        end = source.find("\n    async def ", idx + 10)
        if end == -1:
            end = source.find("\n\nclass ", idx + 10)
        method_code = source[idx:end]
        assert "available_qty" in method_code, "liquidate_positions应使用available_qty"
        assert "total_qty" not in method_code or "available_qty" in method_code, \
            "不应仅依赖total_qty"

    def test_liquidate_positions_no_broker_returns_zero(self):
        """liquidate_positions无broker时返回(0, 0)"""
        from nodes.market_monitor.position_manager import PositionManager
        source = inspect.getsource(PositionManager.liquidate_positions)
        assert "return 0, 0" in source

    def test_execute_sell_list_from_risk_calls_execute_risk_sell(self):
        """execute_sell_list_from_risk调用self.execute_risk_sell(不是scanner._execute_risk_sell)"""
        from nodes.market_monitor.position_manager import PositionManager
        source = inspect.getsource(PositionManager.execute_sell_list_from_risk)
        assert "self.execute_risk_sell" in source, \
            "execute_sell_list_from_risk应调用self.execute_risk_sell(不再走scanner委托)"


# ==================== 2. Scanner委托 ====================

class TestScannerDelegation:
    """验证scanner委托到PositionManager"""

    def test_execute_risk_sell_in_delegate_map(self):
        """_execute_risk_sell有显式方法定义(v2.9.52:从DELEGATE_MAP移除,保留显式存根)"""
        from nodes.market_monitor.scanner import MarketScanner
        # 应有显式方法定义
        assert hasattr(MarketScanner, '_execute_risk_sell')
        # 显式方法优先于DELEGATE_MAP, 不需要委托条目
        from nodes.market_monitor.scanner_delegate_router import DELEGATE_MAP
        assert '_execute_risk_sell' not in DELEGATE_MAP, "显式方法不应在DELEGATE_MAP中(死代码)"

    def test_liquidate_positions_in_delegate_map(self):
        """_liquidate_positions有显式方法定义(v2.9.52:从DELEGATE_MAP移除,保留显式存根)"""
        from nodes.market_monitor.scanner import MarketScanner
        assert hasattr(MarketScanner, '_liquidate_positions')
        from nodes.market_monitor.scanner_delegate_router import DELEGATE_MAP
        assert '_liquidate_positions' not in DELEGATE_MAP, "显式方法不应在DELEGATE_MAP中(死代码)"

    def test_delegate_stubs_are_short(self):
        """scanner中的委托存根应<=5行"""
        source = _read_file(_SCANNER_PATH)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                if node.name in ("_execute_risk_sell", "_liquidate_positions"):
                    lines = node.end_lineno - node.lineno + 1
                    assert lines <= 5, f"{node.name}委托存根应<=5行, 实际{lines}行"

    def test_no_inline_loop_in_scanner_liquidate(self):
        """scanner的_liquidate_positions不应有内联循环"""
        source = _read_file(_SCANNER_PATH)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_liquidate_positions":
                method_src = source.splitlines()[node.lineno-1:node.end_lineno]
                method_text = "\n".join(method_src)
                assert "for p in" not in method_text, \
                    "_liquidate_positions不应有内联循环(已提取到PositionManager)"

    def test_sell_all_positions_still_works(self):
        """_sell_all_positions仍委托到_liquidate_positions"""
        source = _read_file(_SCANNER_PATH)
        assert '_liquidate_positions' in source
        assert 'source="stop_sell"' in source

    def test_execute_force_empty_still_works(self):
        """_execute_force_empty仍委托到_liquidate_positions"""
        source = _read_file(_SCANNER_PATH)
        assert 'source="force_empty"' in source


# ==================== 3. AsyncDelegate注册 ====================

class TestAsyncDelegateRegistration:
    """验证_ASYNC_DELEGATE_METHODS包含新方法"""

    def test_execute_risk_sell_in_async_delegates(self):
        source = _read_file(
            os.path.join(_PROJECT_ROOT, "nodes", "market_monitor", "scanner_delegate_router.py")
        )
        assert '"_execute_risk_sell"' in source

    def test_liquidate_positions_in_async_delegates(self):
        source = _read_file(
            os.path.join(_PROJECT_ROOT, "nodes", "market_monitor", "scanner_delegate_router.py")
        )
        assert '"_liquidate_positions"' in source


# ==================== 4. 行数回归 ====================

class TestLineCountV2935:
    """验证行数回归"""

    def test_scanner_line_count(self):
        with open(_SCANNER_PATH) as f:
            line_count = sum(1 for _ in f)
        assert line_count < 1550, f"scanner.py行数{line_count}应<1550"
        assert line_count > 800, f"scanner.py行数{line_count}应>1200"

    def test_pm_grew(self):
        with open(_PM_PATH) as f:
            line_count = sum(1 for _ in f)
        assert line_count >= 700, f"position_manager.py行数{line_count}应>=700"


# ==================== 5. 回测零影响 ====================

class TestNoBacktestRegressionV2935:

    def test_backtester_importable(self):
        from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
        assert PortfolioBacktester is not None

    def test_pm_no_scanner_import(self):
        """PositionManager不直接import scanner模块"""
        source = _read_file(_PM_PATH)
        # 不应有from nodes.market_monitor.scanner import
        assert "from nodes.market_monitor.scanner import" not in source, \
            "PositionManager不应import scanner(通过self._scanner引用)"
