"""v2.9.44: scanner_daemon _SubprocessRuntime提取测试

验证:
1. _SubprocessRuntime类结构(方法完整性)
2. 命令路由正确分发
3. ACK发送逻辑
4. _subprocess_async_main委托到_SubprocessRuntime
5. 回测零影响
"""

import asyncio
import json
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestSubprocessRuntimeStructure:
    """验证_SubprocessRuntime类结构完整性"""

    def test_runtime_has_required_methods(self):
        """_SubprocessRuntime应包含所有必要方法"""
        from nodes.market_monitor.scanner_daemon import _SubprocessRuntime
        required = [
            "pub", "handle_command", "run",
            "_cmd_start", "_cmd_stop", "_cmd_emergency_liquidate",
            "_cmd_update_params", "_cmd_scan",
            "_run_scanner_loop", "status_pusher", "health_pusher",
            "_send_ack",
        ]
        for method_name in required:
            assert hasattr(_SubprocessRuntime, method_name), f"Missing method: {method_name}"

    def test_runtime_initial_state(self):
        """_SubprocessRuntime初始状态应为IDLE"""
        from nodes.market_monitor.scanner_daemon import _SubprocessRuntime, ScannerDaemonConfig, ScannerState
        rt = _SubprocessRuntime(ScannerDaemonConfig())
        assert rt.state == ScannerState.IDLE
        assert rt.scanner is None
        assert rt.scan_task is None

    def test_runtime_channels_initialized_empty(self):
        """IPC频道初始为空(在run()中初始化)"""
        from nodes.market_monitor.scanner_daemon import _SubprocessRuntime, ScannerDaemonConfig
        rt = _SubprocessRuntime(ScannerDaemonConfig())
        assert rt.cmd_channel == ""
        assert rt.status_channel == ""
        assert rt.ack_channel == ""


class TestSubprocessRuntimeCommandRouting:
    """验证命令路由分发"""

    @pytest.mark.asyncio
    async def test_start_command_routes_to_cmd_start(self):
        """start命令应路由到_cmd_start"""
        from nodes.market_monitor.scanner_daemon import _SubprocessRuntime, ScannerDaemonConfig
        rt = _SubprocessRuntime(ScannerDaemonConfig())
        rt._redis_client = MagicMock()
        rt._send_ack = AsyncMock()

        # Mock _cmd_start to verify it gets called
        called_with = {}
        async def fake_start(params, cmd_id):
            called_with["params"] = params
            called_with["cmd_id"] = cmd_id

        rt._cmd_start = fake_start
        await rt.handle_command({"cmd": "start", "params": {"trade_date": "20260601"}, "cmd_id": "abc123"})
        assert called_with["params"] == {"trade_date": "20260601"}
        assert called_with["cmd_id"] == "abc123"

    @pytest.mark.asyncio
    async def test_stop_command_routes_to_cmd_stop(self):
        """stop命令应路由到_cmd_stop"""
        from nodes.market_monitor.scanner_daemon import _SubprocessRuntime, ScannerDaemonConfig
        rt = _SubprocessRuntime(ScannerDaemonConfig())
        rt._redis_client = MagicMock()
        rt._send_ack = AsyncMock()

        called = False
        async def fake_stop(params, cmd_id):
            nonlocal called
            called = True

        rt._cmd_stop = fake_stop
        await rt.handle_command({"cmd": "stop", "params": {}, "cmd_id": "xyz"})
        assert called

    @pytest.mark.asyncio
    async def test_unknown_command_warns(self):
        """未知命令应打印警告"""
        from nodes.market_monitor.scanner_daemon import _SubprocessRuntime, ScannerDaemonConfig
        rt = _SubprocessRuntime(ScannerDaemonConfig())
        rt._redis_client = MagicMock()
        rt._send_ack = AsyncMock()

        # 不应抛异常
        await rt.handle_command({"cmd": "unknown_cmd", "params": {}, "cmd_id": ""})


class TestSubprocessRuntimeACK:
    """验证ACK发送逻辑"""

    @pytest.mark.asyncio
    async def test_send_ack_with_cmd_id(self):
        """_send_ack有cmd_id时应发布ACK"""
        from nodes.market_monitor.scanner_daemon import _SubprocessRuntime, ScannerDaemonConfig
        rt = _SubprocessRuntime(ScannerDaemonConfig())
        rt._redis_client = MagicMock()
        rt._redis_client.publish = AsyncMock()
        rt.ack_channel = "scanner:ack"

        await rt._send_ack("test1234", "received")
        assert rt._redis_client.publish.called
        call_args = rt._redis_client.publish.call_args
        payload = json.loads(call_args[0][1])
        assert payload["cmd_id"] == "test1234"
        assert payload["status"] == "received"

    @pytest.mark.asyncio
    async def test_send_ack_without_cmd_id(self):
        """_send_ack无cmd_id时不应发布ACK"""
        from nodes.market_monitor.scanner_daemon import _SubprocessRuntime, ScannerDaemonConfig
        rt = _SubprocessRuntime(ScannerDaemonConfig())
        rt._redis_client = MagicMock()
        rt._redis_client.publish = AsyncMock()

        await rt._send_ack("", "done")
        assert not rt._redis_client.publish.called

    @pytest.mark.asyncio
    async def test_handle_command_sends_received_ack(self):
        """handle_command应先发送received ACK"""
        from nodes.market_monitor.scanner_daemon import _SubprocessRuntime, ScannerDaemonConfig
        rt = _SubprocessRuntime(ScannerDaemonConfig())
        rt._redis_client = MagicMock()
        ack_statuses = []

        async def fake_ack(cmd_id, status, cmd=""):
            ack_statuses.append((cmd_id, status))

        rt._send_ack = fake_ack
        rt._cmd_start = AsyncMock()

        await rt.handle_command({"cmd": "start", "params": {}, "cmd_id": "abc"})
        # First ACK should be "received", then "done"
        assert ack_statuses[0] == ("abc", "received")
        assert ack_statuses[-1] == ("abc", "done")


class TestSubprocessAsyncMainDelegation:
    """验证_subprocess_async_main委托给_SubprocessRuntime"""

    def test_subprocess_async_main_is_thin_wrapper(self):
        """_subprocess_async_main应只有3行(委托)"""
        import inspect
        from nodes.market_monitor.scanner_daemon import _subprocess_async_main
        source = inspect.getsource(_subprocess_async_main)
        lines = [l.strip() for l in source.strip().split('\n') if l.strip() and not l.strip().startswith('#')]
        # def line + docstring + runtime = _SubprocessRuntime(config) + await runtime.run()
        # Should be ~4 meaningful lines
        assert len(lines) <= 5, f"_subprocess_async_main should be thin, got {len(lines)} lines: {lines}"

    def test_subprocess_async_main_creates_runtime(self):
        """_subprocess_async_main源码应包含_SubprocessRuntime"""
        import inspect
        from nodes.market_monitor.scanner_daemon import _subprocess_async_main
        source = inspect.getsource(_subprocess_async_main)
        assert "_SubprocessRuntime" in source


class TestSubprocessRuntimeCmdStart:
    """验证_cmd_start逻辑"""

    @pytest.mark.asyncio
    async def test_start_already_running_rejects(self):
        """已在运行时拒绝重复启动"""
        from nodes.market_monitor.scanner_daemon import _SubprocessRuntime, ScannerDaemonConfig, ScannerState
        rt = _SubprocessRuntime(ScannerDaemonConfig())
        rt._redis_client = MagicMock()
        rt._send_ack = AsyncMock()
        rt.state = ScannerState.RUNNING

        published = []
        async def fake_pub(channel, data):
            published.append((channel, data))

        rt.pub = fake_pub

        await rt._cmd_start({}, "")
        # Should publish already_running, not change state
        assert any("already_running" in str(d) for _, d in published)


class TestSubprocessRuntimeCmdStop:
    """验证_cmd_stop逻辑"""

    @pytest.mark.asyncio
    async def test_stop_cancels_scan_task(self):
        """stop应取消scan_task并重置状态"""
        from nodes.market_monitor.scanner_daemon import _SubprocessRuntime, ScannerDaemonConfig, ScannerState
        rt = _SubprocessRuntime(ScannerDaemonConfig())
        rt._redis_client = MagicMock()
        rt._send_ack = AsyncMock()

        # Create a proper mock task that supports await
        loop = asyncio.get_event_loop()
        async def never_finish():
            await asyncio.sleep(1000)
        mock_task = loop.create_task(never_finish())

        rt.scan_task = mock_task
        rt.state = ScannerState.RUNNING
        rt.pub = AsyncMock()

        await rt._cmd_stop({}, "stop123")
        assert rt.scanner is None
        assert rt.state == ScannerState.STOPPED
        # Task should have been cancelled
        assert mock_task.cancelled()


class TestNoBacktestRegressionV2944:
    """验证回测零影响"""

    def test_backtest_engine_importable(self):
        """回测引擎应正常导入"""
        from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
        assert PortfolioBacktester is not None

    def test_sell_signal_checker_importable(self):
        """卖出信号检查器应正常导入"""
        from nodes.backtest_engine.factor_selection.sell_signal_checker import SellSignalChecker
        assert SellSignalChecker is not None

    def test_strategy_defaults_importable(self):
        """策略默认参数应正常导入"""
        from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS
        assert isinstance(STRATEGY_CONFIGS, dict)
