#!/usr/bin/env python3
"""v2.9.21 测试: MarketPhase时间分类提取 + 循环门控统一

关键变更:
- 🟡 提取MarketPhase类(7个阶段+classify()静态方法)
- 🟡 _scan_loop时间门控→MarketPhase.classify()
- 🟡 _risk_loop_sync时间门控→MarketPhase.classify()
- 消除散布在两个方法中的魔术字符串比较
"""
import os
import sys
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SCANNER_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "nodes", "market_monitor", "scanner.py"
)


class TestMarketPhaseClassify:
    """验证MarketPhase.classify()时间分类"""

    def test_market_phase_class_exists(self):
        """MarketPhase类存在"""
        from nodes.market_monitor.scanner import MarketPhase
        assert hasattr(MarketPhase, 'classify')

    def test_weekend_detected(self):
        """周末返回WEEKEND"""
        from nodes.market_monitor.scanner import MarketPhase
        # 模拟周六10:00
        with patch('nodes.market_monitor.scanner.datetime') as mock_dt:
            mock_now = MagicMock()
            mock_now.weekday.return_value = 5  # 周六
            mock_now.hour = 10
            mock_now.strftime.return_value = "10:00"
            mock_dt.now.return_value = mock_now
            assert MarketPhase.classify() == MarketPhase.WEEKEND

    def test_deep_night_late(self):
        """深夜(23:00+)返回DEEP_NIGHT"""
        from nodes.market_monitor.scanner import MarketPhase
        with patch('nodes.market_monitor.scanner.datetime') as mock_dt:
            mock_now = MagicMock()
            mock_now.weekday.return_value = 2  # 周三
            mock_now.hour = 23
            mock_now.strftime.return_value = "23:30"
            mock_dt.now.return_value = mock_now
            assert MarketPhase.classify() == MarketPhase.DEEP_NIGHT

    def test_deep_night_early(self):
        """凌晨(0-7点)返回DEEP_NIGHT"""
        from nodes.market_monitor.scanner import MarketPhase
        with patch('nodes.market_monitor.scanner.datetime') as mock_dt:
            mock_now = MagicMock()
            mock_now.weekday.return_value = 3  # 周四
            mock_now.hour = 3
            mock_now.strftime.return_value = "03:00"
            mock_dt.now.return_value = mock_now
            assert MarketPhase.classify() == MarketPhase.DEEP_NIGHT

    def test_premarket_detected(self):
        """盘前(9:00-9:25)返回PREMARKET"""
        from nodes.market_monitor.scanner import MarketPhase
        with patch('nodes.market_monitor.scanner.datetime') as mock_dt:
            mock_now = MagicMock()
            mock_now.weekday.return_value = 0  # 周一
            mock_now.hour = 9
            mock_now.strftime.return_value = "09:15"
            mock_dt.now.return_value = mock_now
            assert MarketPhase.classify() == MarketPhase.PREMARKET

    def test_auction_detected(self):
        """竞价(9:25-9:30)返回AUCTION"""
        from nodes.market_monitor.scanner import MarketPhase
        with patch('nodes.market_monitor.scanner.datetime') as mock_dt:
            mock_now = MagicMock()
            mock_now.weekday.return_value = 1  # 周二
            mock_now.hour = 9
            mock_now.strftime.return_value = "09:27"
            mock_dt.now.return_value = mock_now
            assert MarketPhase.classify() == MarketPhase.AUCTION

    def test_trading_detected(self):
        """交易时间(9:30-15:00)返回TRADING"""
        from nodes.market_monitor.scanner import MarketPhase
        with patch('nodes.market_monitor.scanner.datetime') as mock_dt:
            mock_now = MagicMock()
            mock_now.weekday.return_value = 2  # 周三
            mock_now.hour = 10
            mock_now.strftime.return_value = "10:30"
            mock_dt.now.return_value = mock_now
            assert MarketPhase.classify() == MarketPhase.TRADING

    def test_after_close_detected(self):
        """收盘后(15:05+)返回AFTER_CLOSE"""
        from nodes.market_monitor.scanner import MarketPhase
        with patch('nodes.market_monitor.scanner.datetime') as mock_dt:
            mock_now = MagicMock()
            mock_now.weekday.return_value = 3  # 周四
            mock_now.hour = 15
            mock_now.strftime.return_value = "15:10"
            mock_dt.now.return_value = mock_now
            assert MarketPhase.classify() == MarketPhase.AFTER_CLOSE

    def test_off_hours_lunch(self):
        """午间(8:00-9:00)返回OFF_HOURS"""
        from nodes.market_monitor.scanner import MarketPhase
        with patch('nodes.market_monitor.scanner.datetime') as mock_dt:
            mock_now = MagicMock()
            mock_now.weekday.return_value = 0  # 周一
            mock_now.hour = 8
            mock_now.strftime.return_value = "08:30"
            mock_dt.now.return_value = mock_now
            assert MarketPhase.classify() == MarketPhase.OFF_HOURS

    def test_classify_no_side_effects(self):
        """classify()零副作用, 可随时调用"""
        from nodes.market_monitor.scanner import MarketPhase
        # 连续调用不应修改任何状态
        phase1 = MarketPhase.classify()
        phase2 = MarketPhase.classify()
        assert phase1 == phase2

    def test_seven_phases_defined(self):
        """MarketPhase定义了7个阶段"""
        from nodes.market_monitor.scanner import MarketPhase
        phases = [
            MarketPhase.WEEKEND, MarketPhase.DEEP_NIGHT,
            MarketPhase.PREMARKET, MarketPhase.AUCTION,
            MarketPhase.TRADING, MarketPhase.AFTER_CLOSE,
            MarketPhase.OFF_HOURS,
        ]
        assert len(phases) == 7
        assert len(set(phases)) == 7  # 所有阶段值唯一


class TestScanLoopUsesMarketPhase:
    """验证_scan_loop使用MarketPhase"""

    def test_scan_loop_no_magic_string_compare(self):
        """_scan_loop不再有硬编码时间字符串比较"""
        with open(SCANNER_PATH) as f:
            src = f.read()
        import ast
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_scan_loop":
                method_src = src.splitlines()[node.lineno-1:node.end_lineno]
                method_text = "\n".join(method_src)
                # 不应有直接的时间字符串比较(如 "09:30" <= ct)
                import re
                # 找到 "XX:XX" 格式的比较
                time_compares = re.findall(r'["\']\d{2}:\d{2}["\']', method_text)
                # 只允许sleep参数中的时间字符串
                # 如果有直接比较的时间字符串, 说明没有完全重构
                for tc in time_compares:
                    line_with_tc = [l for l in method_src if tc in l]
                    for l in line_with_tc:
                        # sleep中的时间字符串是OK的
                        if "sleep" in l:
                            continue
                        # 日志中的时间字符串是OK的
                        if "logger" in l or "log" in l:
                            continue
                        # 如果行中有<=或>=比较操作, 那就是问题
                        if "<=" in l or ">=" in l or "<" in l or ">" in l:
                            pytest.fail(
                                f"_scan_loop仍有硬编码时间比较: {l.strip()}")

    def test_scan_loop_uses_market_phase(self):
        """_scan_loop使用MarketPhase.classify()"""
        with open(SCANNER_PATH) as f:
            src = f.read()
        import ast
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_scan_loop":
                method_src = src.splitlines()[node.lineno-1:node.end_lineno]
                method_text = "\n".join(method_src)
                assert "MarketPhase" in method_text, \
                    "_scan_loop应使用MarketPhase"


class TestRiskLoopUsesMarketPhase:
    """验证_risk_loop_sync使用MarketPhase"""

    def test_risk_loop_no_magic_string_compare(self):
        """_risk_loop_sync不再有硬编码时间字符串比较"""
        with open(SCANNER_PATH) as f:
            src = f.read()
        import ast
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_risk_loop_sync":
                method_src = src.splitlines()[node.lineno-1:node.end_lineno]
                method_text = "\n".join(method_src)
                # 不应有ct < "09:25"这种比较
                import re
                time_compares = re.findall(r'["\']\d{2}:\d{2}["\']', method_text)
                for tc in time_compares:
                    line_with_tc = [l for l in method_src if tc in l]
                    for l in line_with_tc:
                        if "sleep" in l or "logger" in l or "MarketPhase" in l:
                            continue
                        if "<=" in l or ">=" in l or "<" in l or ">" in l:
                            pytest.fail(
                                f"_risk_loop_sync仍有硬编码时间比较: {l.strip()}")

    def test_risk_loop_uses_market_phase(self):
        """_risk_loop_sync使用MarketPhase.classify()"""
        with open(SCANNER_PATH) as f:
            src = f.read()
        import ast
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_risk_loop_sync":
                method_src = src.splitlines()[node.lineno-1:node.end_lineno]
                method_text = "\n".join(method_src)
                assert "MarketPhase" in method_text, \
                    "_risk_loop_sync应使用MarketPhase"


class TestMarketPhaseEdgeCases:
    """MarketPhase边界时间测试"""

    def test_trading_start_boundary(self):
        """9:30是交易时间"""
        from nodes.market_monitor.scanner import MarketPhase
        with patch('nodes.market_monitor.scanner.datetime') as mock_dt:
            mock_now = MagicMock()
            mock_now.weekday.return_value = 0
            mock_now.hour = 9
            mock_now.strftime.return_value = "09:30"
            mock_dt.now.return_value = mock_now
            assert MarketPhase.classify() == MarketPhase.TRADING

    def test_trading_end_boundary(self):
        """15:00仍是交易时间"""
        from nodes.market_monitor.scanner import MarketPhase
        with patch('nodes.market_monitor.scanner.datetime') as mock_dt:
            mock_now = MagicMock()
            mock_now.weekday.return_value = 0
            mock_now.hour = 15
            mock_now.strftime.return_value = "15:00"
            mock_dt.now.return_value = mock_now
            assert MarketPhase.classify() == MarketPhase.TRADING

    def test_auction_start_boundary(self):
        """9:25是竞价时间"""
        from nodes.market_monitor.scanner import MarketPhase
        with patch('nodes.market_monitor.scanner.datetime') as mock_dt:
            mock_now = MagicMock()
            mock_now.weekday.return_value = 0
            mock_now.hour = 9
            mock_now.strftime.return_value = "09:25"
            mock_dt.now.return_value = mock_now
            assert MarketPhase.classify() == MarketPhase.AUCTION

    def test_gap_between_trading_and_close(self):
        """15:01-15:04是OFF_HOURS(交易和收盘之间)"""
        from nodes.market_monitor.scanner import MarketPhase
        with patch('nodes.market_monitor.scanner.datetime') as mock_dt:
            mock_now = MagicMock()
            mock_now.weekday.return_value = 0
            mock_now.hour = 15
            mock_now.strftime.return_value = "15:02"
            mock_dt.now.return_value = mock_now
            assert MarketPhase.classify() == MarketPhase.OFF_HOURS


class TestNoBacktestRegressionV2921:
    """验证回测零影响"""

    def test_market_phase_not_in_backtest(self):
        """MarketPhase不影响回测"""
        backtest_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "..",
            "nodes", "backtest_engine"
        )
        if not os.path.exists(backtest_dir):
            return
        for root, dirs, files in os.walk(backtest_dir):
            for f in files:
                if f.endswith('.py'):
                    fpath = os.path.join(root, f)
                    with open(fpath) as fh:
                        content = fh.read()
                    assert "MarketPhase" not in content, \
                        f"MarketPhase不应出现在回测引擎 {f} 中"

    def test_scanner_importable(self):
        """scanner模块可正常导入"""
        from nodes.market_monitor.scanner import MarketScanner, MarketPhase
        assert hasattr(MarketScanner, '_scan_loop')
        assert hasattr(MarketScanner, '_risk_loop_sync')
        assert hasattr(MarketPhase, 'classify')
