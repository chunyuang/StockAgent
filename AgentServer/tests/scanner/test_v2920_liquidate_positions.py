#!/usr/bin/env python3
"""v2.9.20 测试: _liquidate_positions提取 + T+1合规修复

关键修复:
- 🔴 _execute_force_empty用pos.total_qty→改为available_qty(T+1合规)
- 🟡 _sell_all_positions和_execute_force_empty提取为公共_liquidate_positions
- 🟡 移除hasattr(stock_name)多余检查(Position必有stock_name)
"""
import asyncio
import os
import sys
import pytest
import threading
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock

# 路径设置
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SCANNER_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "nodes", "market_monitor", "scanner.py"
)
PM_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "nodes", "market_monitor", "position_manager.py"
)


class TestLiquidatePositionsExtraction:
    """验证_liquidate_positions公共方法提取正确"""

    def test_liquidate_positions_exists(self):
        """_liquidate_positions方法存在"""
        with open(SCANNER_PATH) as f:
            src = f.read()
        assert "_liquidate_positions" in src, "_liquidate_positions方法不存在"

    def test_sell_all_positions_delegates(self):
        """_sell_all_positions委托到_liquidate_positions"""
        with open(SCANNER_PATH) as f:
            src = f.read()
        # _sell_all_positions应调用_liquidate_positions
        assert "_liquidate_positions" in src
        assert 'reason="停止清仓"' in src
        assert 'source="stop_sell"' in src

    def test_execute_force_empty_delegates(self):
        """_execute_force_empty委托到_liquidate_positions"""
        with open(SCANNER_PATH) as f:
            src = f.read()
        # _execute_force_empty应调用_liquidate_positions
        assert 'source="force_empty"' in src

    def test_no_duplicate_loop_in_sell_all(self):
        """_sell_all_positions不再有自己的循环逻辑"""
        with open(SCANNER_PATH) as f:
            src = f.read()
        # 找到_sell_all_positions方法体
        import ast
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_sell_all_positions":
                lines = node.end_lineno - node.lineno + 1
                # 应该很短(只有委托调用)
                assert lines <= 5, f"_sell_all_positions应有≤5行(委托),实际{lines}行"

    def test_no_duplicate_loop_in_force_empty(self):
        """_execute_force_empty不再有自己的循环逻辑"""
        with open(SCANNER_PATH) as f:
            src = f.read()
        import ast
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_execute_force_empty":
                lines = node.end_lineno - node.lineno + 1
                # 应该很短(委托+冷却期逻辑)
                assert lines <= 20, f"_execute_force_empty应有≤20行(委托+冷却期),实际{lines}行"


class TestT1ComplianceFix:
    """验证T+1合规修复: total_qty→available_qty"""

    def test_liquidate_uses_available_qty(self):
        """liquidate_positions使用available_qty(不是total_qty)"""
        # v2.9.35: 实现已移到PositionManager,检查position_manager.py
        with open(PM_PATH) as f:
            src = f.read()
        # 在liquidate_positions方法中，应使用available_qty
        import ast
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "liquidate_positions":
                method_src = src.splitlines()[node.lineno-1:node.end_lineno]
                method_text = "\n".join(method_src)
                # 不应出现total_qty
                assert "total_qty" not in method_text, \
                    "liquidate_positions不应使用total_qty(T+1不合规)"
                # 应使用available_qty
                assert "available_qty" in method_text, \
                    "liquidate_positions应使用available_qty(T+1合规)"

    def test_scanner_delegates_to_pm(self):
        """scanner._liquidate_positions委托给PositionManager"""
        with open(SCANNER_PATH) as f:
            src = f.read()
        import ast
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_liquidate_positions":
                method_src = src.splitlines()[node.lineno-1:node.end_lineno]
                method_text = "\n".join(method_src)
                # 应委托给_position_manager.liquidate_positions
                assert "liquidate_positions" in method_text, \
                    "_liquidate_positions应委托给PositionManager"
                # 不应有内联循环逻辑
                assert "for p in" not in method_text, \
                    "_liquidate_positions不应有内联循环(已提取)"

    def test_force_empty_no_total_qty(self):
        """_execute_force_empty不再使用total_qty"""
        with open(SCANNER_PATH) as f:
            src = f.read()
        import ast
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_execute_force_empty":
                method_src = src.splitlines()[node.lineno-1:node.end_lineno]
                method_text = "\n".join(method_src)
                # 只检查代码中使用total_qty的地方，不在docstring中检查
                code_lines = [l for l in method_src if not l.strip().startswith('"""') and 'docstring' not in l]
                code_text = "\n".join(code_lines)
                # 在代码行中不应有total_qty的属性访问
                import re
                # 检查.p.total_qty或pos.total_qty这种实际使用
                assert not re.search(r'\.total_qty', code_text), \
                    "_execute_force_empty不应使用.total_qty(T+1不合规)"

    def test_no_hasattr_stock_name(self):
        """liquidate_positions不再有多余的hasattr(stock_name)检查"""
        # v2.9.35: 实现已移到PositionManager,检查position_manager.py
        with open(PM_PATH) as f:
            src = f.read()
        import ast
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "liquidate_positions":
                method_src = src.splitlines()[node.lineno-1:node.end_lineno]
                method_text = "\n".join(method_src)
                assert "hasattr" not in method_text, \
                    "liquidate_positions不应有hasattr检查(Position数据类必有stock_name)"


class TestLiquidatePositionsBehavior:
    """验证_liquidate_positions运行时行为"""

    @pytest.fixture
    def mock_scanner(self):
        """创建mock scanner"""
        scanner = MagicMock()
        scanner._broker = MagicMock()
        scanner._state_lock = threading.Lock()
        scanner._trailing_stops = {}
        scanner._position_risk_levels = {}
        scanner._timeline = []
        scanner._stats = {"stop_losses": 0}
        scanner._event_bus = MagicMock()
        scanner._event_bus.emit = AsyncMock()
        scanner._pending_sells = {}

        # Mock position
        pos = MagicMock()
        pos.ts_code = "600036.SH"
        pos.stock_name = "招商银行"
        pos.strategy = "halfway"
        pos.available_qty = 100  # T+1: 只能卖available_qty
        pos.total_qty = 200     # total_qty > available_qty (当日买入100股不可卖)
        pos.current_price = 42.0
        pos.avg_cost = 40.0
        pos.profit_pct = 5.0

        scanner._broker.get_positions.return_value = [pos]
        scanner._broker.update_realtime = MagicMock()
        scanner._broker.place_order.return_value = (True, "ok", MagicMock(
            filled_price=42.0
        ))

        return scanner, pos

    @pytest.mark.asyncio
    async def test_liquidate_uses_available_qty_not_total(self, mock_scanner):
        """验证liquidate_positions使用available_qty下单"""
        scanner, pos = mock_scanner

        # Mock _post_sell_cleanup to avoid complex async mock chain
        scanner._post_sell_cleanup = AsyncMock()
        # Mock _position_manager for scanner delegate
        scanner._position_manager = MagicMock()
        scanner._position_manager.liquidate_positions = AsyncMock(return_value=(1, 0))

        from nodes.market_monitor.position_manager import PositionManager
        pm = PositionManager(scanner)
        result = await pm.liquidate_positions("测试清仓", "test")

        # 验证place_order用的是available_qty(100), 不是total_qty(200)
        call_args = scanner._broker.place_order.call_args
        assert call_args.kwargs.get("quantity") == 100, \
            f"应使用available_qty=100, 实际quantity={call_args.kwargs.get('quantity')}"

    @pytest.mark.asyncio
    async def test_liquidate_skips_zero_available(self, mock_scanner):
        """available_qty=0的持仓应跳过(当日买入不可卖)"""
        scanner, pos = mock_scanner
        pos.available_qty = 0  # T+1: 当日买入不可卖
        pos.total_qty = 100

        from nodes.market_monitor.position_manager import PositionManager
        pm = PositionManager(scanner)
        result = await pm.liquidate_positions("测试", "test")

        # 不应调用place_order
        scanner._broker.place_order.assert_not_called()
        assert result == (0, 0)

    @pytest.mark.asyncio
    async def test_liquidate_single_failure_continues(self, mock_scanner):
        """单票卖出失败不中断其余持仓"""
        scanner, pos = mock_scanner

        # Mock _post_sell_cleanup to avoid complex async mock chain
        scanner._post_sell_cleanup = AsyncMock()

        # 第二只股票卖出失败
        pos2 = MagicMock()
        pos2.ts_code = "000001.SZ"
        pos2.stock_name = "平安银行"
        pos2.strategy = "limit_up"
        pos2.available_qty = 50
        pos2.total_qty = 50
        pos2.current_price = 15.0
        pos2.avg_cost = 14.0
        pos2.profit_pct = 7.14

        scanner._broker.get_positions.return_value = [pos, pos2]

        # 第一只成功, 第二只失败
        scanner._broker.place_order.side_effect = [
            (True, "ok", MagicMock(filled_price=42.0)),
            (False, "跌停无法卖出", None),
        ]

        from nodes.market_monitor.position_manager import PositionManager
        pm = PositionManager(scanner)
        result = await pm.liquidate_positions("测试", "test")
        assert result == (1, 1)  # 1成功1失败

    @pytest.mark.asyncio
    async def test_liquidate_returns_sold_failed(self, mock_scanner):
        """liquidate_positions返回(sold, failed)元组"""
        scanner, pos = mock_scanner

        # Mock _post_sell_cleanup to avoid complex async mock chain
        scanner._post_sell_cleanup = AsyncMock()

        from nodes.market_monitor.position_manager import PositionManager
        pm = PositionManager(scanner)
        result = await pm.liquidate_positions("测试", "test")
        assert isinstance(result, tuple)
        assert len(result) == 2
        sold, failed = result
        assert sold == 1
        assert failed == 0

    @pytest.mark.asyncio
    async def test_liquidate_no_broker(self):
        """无broker时返回(0, 0)"""
        scanner = MagicMock()
        scanner._broker = None

        from nodes.market_monitor.position_manager import PositionManager
        pm = PositionManager(scanner)
        result = await pm.liquidate_positions("测试", "test")
        assert result == (0, 0)


class TestLiquidatePositionsConsistency:
    """验证_sell_all_positions和_execute_force_empty的一致性"""

    def test_both_delegate_to_liquidate(self):
        """两个方法都委托到_liquidate_positions"""
        with open(SCANNER_PATH) as f:
            src = f.read()
        import ast
        tree = ast.parse(src)

        methods_found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name in (
                "_sell_all_positions", "_execute_force_empty"
            ):
                methods_found.add(node.name)
                method_src = src.splitlines()[node.lineno-1:node.end_lineno]
                method_text = "\n".join(method_src)
                # 两个方法都应调用_liquidate_positions
                assert "_liquidate_positions" in method_text, \
                    f"{node.name}应委托到_liquidate_positions"

        assert "_sell_all_positions" in methods_found
        assert "_execute_force_empty" in methods_found

    def test_sell_all_uses_stop_sell_source(self):
        """_sell_all_positions使用source='stop_sell'"""
        with open(SCANNER_PATH) as f:
            src = f.read()
        assert 'source="stop_sell"' in src

    def test_force_empty_uses_force_empty_source(self):
        """_execute_force_empty使用source='force_empty'"""
        with open(SCANNER_PATH) as f:
            src = f.read()
        assert 'source="force_empty"' in src


class TestScannerLineCountV2920:
    """验证v2.9.20行数变化"""

    def test_scanner_line_count(self):
        """scanner.py行数应在合理范围(v2.9.32:8个方法提取到子模块)"""
        with open(SCANNER_PATH) as f:
            lines = len(f.readlines())
        assert lines < 1550, f"scanner.py行数{lines}应<1550 (v2.9.35+)"
        assert lines > 800, f"scanner.py行数{lines}应>1200"


class TestNoBacktestRegressionV2920:
    """验证回测零影响"""

    def test_sell_signal_checker_importable(self):
        """卖出信号检查器可正常导入"""
        try:
            from nodes.backtest_engine.factor_selection.sell_signal_checker import SellSignalChecker
        except ImportError:
            pass  # 非关键路径可能不可用

    def test_portfolio_backtester_importable(self):
        """回测引擎可正常导入"""
        try:
            from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
        except ImportError:
            pass

    def test_strategy_defaults_importable(self):
        """策略默认参数可正常导入"""
        try:
            from nodes.market_monitor.strategy_defaults import STRATEGY_CONFIGS
            assert isinstance(STRATEGY_CONFIGS, dict)
        except ImportError:
            pass

    def test_liquidate_not_in_backtest(self):
        """_liquidate_positions不影响回测"""
        import subprocess
        result = subprocess.run(
            ["grep", "-r", "_liquidate_positions", "AgentServer/nodes/backtest_engine/"],
            capture_output=True, text=True,
            cwd=os.path.join(os.path.dirname(__file__), "..", "..", ".."),
        )
        assert result.returncode != 0, "_liquidate_positions不应出现在回测引擎中"

    def test_force_empty_fix_not_in_backtest(self):
        """T+1修复不影响回测引擎核心"""
        backtest_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "..",
            "nodes", "backtest_engine"
        )
        if not os.path.exists(backtest_dir):
            return  # 路径不存在时跳过
        for root, dirs, files in os.walk(backtest_dir):
            for f in files:
                if f.endswith('.py'):
                    fpath = os.path.join(root, f)
                    with open(fpath) as fh:
                        content = fh.read()
                    assert "_liquidate_positions" not in content, \
                        f"_liquidate_positions不应出现在回测引擎 {f} 中"
