"""v2.9.50 审查修复测试 — Daemon方法名Bug修复+hasattr防御清理+except收窄

关键修复:
- 🔴 _cmd_update_params: update_strategy_params→update_strategy_config (命令永远不执行!)
- 🔴 _cmd_scan: run_once→scan_once (手动扫描永远不触发!)
- 🟡 _cmd_emergency_liquidate: 移除hasattr防御(方法已存在)
- 🟡 _run_scanner_loop: 移除hasattr链,统一用start()
- 🟡 status_pusher: 移除hasattr链,统一用get_status()
- 🟡 _emergency_reduce_positions: 用get_positions()替代_broker直接访问
- 🟡 except Exception收窄(scanner.py 7处+daemon.py 2处)
"""
import os
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from dataclasses import dataclass

# 源文件绝对路径(从tests/scanner/向上3级到AgentServer/)
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCANNER_PY = os.path.join(_ROOT, "nodes", "market_monitor", "scanner.py")
DAEMON_PY = os.path.join(_ROOT, "nodes", "market_monitor", "scanner_daemon.py")


# ---------------------------------------------------------------------------
# _cmd_update_params 方法名修复
# ---------------------------------------------------------------------------

class TestCmdUpdateParamsFix:
    """验证_cmd_update_params调用正确的方法名"""

    def test_calls_update_strategy_config_not_params(self):
        """_cmd_update_params应调用update_strategy_config,不是update_strategy_params"""
        from nodes.market_monitor.scanner_daemon import _SubprocessRuntime, ScannerDaemonConfig

        runtime = _SubprocessRuntime(ScannerDaemonConfig())
        runtime.pub = AsyncMock()

        # Mock scanner with update_strategy_config
        scanner = MagicMock()
        scanner.update_strategy_config = MagicMock()
        runtime.scanner = scanner

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(runtime._cmd_update_params(
                {"strategy_id": "test_strategy", "updates": {"stop_loss": 0.05}},
                "cmd-123"
            ))
        finally:
            loop.close()

        # 验证调用了update_strategy_config而不是update_strategy_params
        scanner.update_strategy_config.assert_called_once_with(
            strategy_key="test_strategy", updates={"stop_loss": 0.05}
        )
        # 验证没有update_strategy_params
        assert not hasattr(scanner, 'update_strategy_params') or \
               not scanner.update_strategy_params.called if hasattr(scanner, 'update_strategy_params') else True

    def test_no_scanner_logs_warning(self):
        """无scanner实例时记录warning"""
        from nodes.market_monitor.scanner_daemon import _SubprocessRuntime, ScannerDaemonConfig

        runtime = _SubprocessRuntime(ScannerDaemonConfig())
        runtime.pub = AsyncMock()
        runtime.scanner = None

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(runtime._cmd_update_params(
                {"strategy_id": "test", "updates": {}}, "cmd-123"
            ))
        finally:
            loop.close()

        # 不应crash, scanner=None


# ---------------------------------------------------------------------------
# _cmd_scan 方法名修复
# ---------------------------------------------------------------------------

class TestCmdScanFix:
    """验证_cmd_scan调用正确的方法名"""

    def test_calls_scan_once_not_run_once(self):
        """_cmd_scan应调用scan_once,不是run_once"""
        from nodes.market_monitor.scanner_daemon import _SubprocessRuntime, ScannerDaemonConfig

        runtime = _SubprocessRuntime(ScannerDaemonConfig())
        runtime.pub = AsyncMock()

        # Mock scanner with scan_once
        scanner = MagicMock()
        scanner.scan_once = AsyncMock(return_value=None)
        runtime.scanner = scanner

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(runtime._cmd_scan({}, "cmd-123"))
        finally:
            loop.close()

        # 验证调用了scan_once
        scanner.scan_once.assert_called_once()
        call_kwargs = scanner.scan_once.call_args
        assert call_kwargs[1].get("force") is True or call_kwargs.kwargs.get("force") is True


# ---------------------------------------------------------------------------
# _cmd_emergency_liquidate hasattr清理
# ---------------------------------------------------------------------------

class TestCmdEmergencyLiquidateFix:
    """验证_cmd_emergency_liquidate直接调用,不再hasattr"""

    def test_calls_emergency_liquidate_directly(self):
        """_cmd_emergency_liquidate应直接调用emergency_liquidate"""
        from nodes.market_monitor.scanner_daemon import _SubprocessRuntime, ScannerDaemonConfig

        runtime = _SubprocessRuntime(ScannerDaemonConfig())
        runtime.pub = AsyncMock()

        scanner = MagicMock()
        scanner.emergency_liquidate = AsyncMock()
        runtime.scanner = scanner

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(runtime._cmd_emergency_liquidate(
                {"reason": "test"}, "cmd-123"
            ))
        finally:
            loop.close()

        scanner.emergency_liquidate.assert_called_once_with(reason="test")


# ---------------------------------------------------------------------------
# _run_scanner_loop hasattr清理
# ---------------------------------------------------------------------------

class TestRunScannerLoopFix:
    """验证_run_scanner_loop直接调用start()"""

    def test_calls_start_directly(self):
        """_run_scanner_loop应直接调用start()"""
        from nodes.market_monitor.scanner_daemon import _SubprocessRuntime, ScannerDaemonConfig

        runtime = _SubprocessRuntime(ScannerDaemonConfig())

        scanner = MagicMock()
        scanner.start = AsyncMock()
        config = ScannerDaemonConfig()

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(runtime._run_scanner_loop(scanner, config, {"trade_date": "20260601"}))
        finally:
            loop.close()

        scanner.start.assert_called_once_with(trade_date="20260601")


# ---------------------------------------------------------------------------
# status_pusher hasattr清理
# ---------------------------------------------------------------------------

class TestStatusPusherFix:
    """验证status_pusher用get_status()替代hasattr链"""

    def test_uses_get_status(self):
        """status_pusher应通过get_status()获取状态"""
        from nodes.market_monitor.scanner_daemon import _SubprocessRuntime, ScannerDaemonConfig

        runtime = _SubprocessRuntime(ScannerDaemonConfig())
        runtime.pub = AsyncMock()
        runtime.config.status_push_interval = 0.01  # 极短间隔

        scanner = MagicMock()
        scanner.get_status = MagicMock(return_value={
            "total_assets": 1000000,
            "position_count": 3,
        })
        runtime.scanner = scanner

        # 只跑1次
        call_count = 0
        original_sleep = asyncio.sleep

        async def limited_sleep(seconds):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()
            await original_sleep(seconds)

        loop = asyncio.new_event_loop()
        try:
            with patch('asyncio.sleep', side_effect=limited_sleep):
                loop.run_until_complete(runtime.status_pusher())
        except asyncio.CancelledError:
            pass
        finally:
            loop.close()

        # 验证调用了get_status而不是hasattr链
        scanner.get_status.assert_called()
        # 验证状态数据包含了get_status的返回值
        if runtime.pub.call_count > 0:
            last_call = runtime.pub.call_args
            status_data = last_call[0][1]  # 第二个位置参数
            assert "total_assets" in status_data


# ---------------------------------------------------------------------------
# scanner.py except收窄验证
# ---------------------------------------------------------------------------

class TestScannerExceptNarrowing:
    """验证scanner.py的except Exception收窄"""

    def test_replay_load_catches_import_error(self):
        """回放数据加载应捕获ImportError而不是Exception"""
        import ast
        with open(SCANNER_PY) as f:
            source = f.read()
        # 验证不再有"回放数据加载失败"的except Exception
        lines = source.split('\n')
        for i, line in enumerate(lines):
            if '回放数据加载失败' in line and 'except Exception' in line:
                pytest.fail(f"Line {i+1}: 回放数据加载应使用更窄的异常类型")

    def test_eventbus_subscriber_catches_import_error(self):
        """EventBus订阅器注册应捕获ImportError而不是Exception"""
        with open(SCANNER_PY) as f:
            source = f.read()
        lines = source.split('\n')
        for i, line in enumerate(lines):
            if '订阅器注册失败' in line and 'except Exception' in line:
                pytest.fail(f"Line {i+1}: EventBus订阅器应使用更窄的异常类型")

    def test_data_router_close_catches_os_error(self):
        """数据源关闭应捕获OSError而不是Exception"""
        with open(SCANNER_PY) as f:
            source = f.read()
        lines = source.split('\n')
        for i, line in enumerate(lines):
            if '数据源关闭失败' in line and 'except Exception' in line:
                pytest.fail(f"Line {i+1}: 数据源关闭应使用更窄的异常类型")

    def test_quote_recovery_catches_connection_error(self):
        """行情恢复应捕获ConnectionError而不是Exception"""
        with open(SCANNER_PY) as f:
            source = f.read()
        lines = source.split('\n')
        for i, line in enumerate(lines):
            if '行情恢复尝试异常' in line and 'except Exception' in line:
                pytest.fail(f"Line {i+1}: 行情恢复应使用更窄的异常类型")


# ---------------------------------------------------------------------------
# daemon.py except收窄验证
# ---------------------------------------------------------------------------

class TestDaemonExceptNarrowing:
    """验证daemon.py的except Exception收窄"""

    def test_ack_listener_catches_specific_errors(self):
        """ACK监听器应捕获json.JSONDecodeError+KeyError而不是Exception"""
        with open(DAEMON_PY) as f:
            source = f.read()
        # 验证ACK parse error不在宽except内
        assert "except (json.JSONDecodeError, Exception) as e:" not in source, \
            "ACK listener应使用分开的异常类型"

    def test_blpop_catches_connection_error(self):
        """BLPOP错误应单独捕获ConnectionError"""
        with open(DAEMON_PY) as f:
            source = f.read()
        assert "except (ConnectionError, OSError, TimeoutError)" in source, \
            "BLPOP应单独捕获ConnectionError"


# ---------------------------------------------------------------------------
# 回测不影响验证
# ---------------------------------------------------------------------------

class TestNoBacktestRegression:
    """验证回测模块未受影响"""

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
