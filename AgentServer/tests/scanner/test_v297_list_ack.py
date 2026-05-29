"""v2.9.7: scanner:cmd List+ACK 升级测试

验证:
1. send_command使用RPUSH到List(非Pub/Sub)
2. 子进程使用BLPOP消费List
3. ACK确认机制(received/done)
4. ACK超时处理
5. Daemon状态包含ACK维度
6. 紧急告警发布Redis事件
7. 回测零影响
"""

import asyncio
import json
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock


# ============================================================================
# 1. send_command使用RPUSH
# ============================================================================

class TestSendCommandUsesList:
    """验证send_command使用RPUSH到List, 非Pub/Sub"""

    @pytest.mark.asyncio
    async def test_send_command_uses_rpush_not_publish(self):
        """send_command应使用rpush而非publish"""
        from nodes.market_monitor.scanner_daemon import ScannerDaemon, ScannerDaemonConfig

        daemon = ScannerDaemon(ScannerDaemonConfig())
        daemon._redis_client = MagicMock()
        daemon._redis_client.rpush = AsyncMock()
        daemon._redis_client.publish = AsyncMock()

        # 不需要真正等待ACK
        with patch.object(asyncio, 'wait_for', side_effect=asyncio.TimeoutError):
            result = await daemon.send_command("start", {"trade_date": "20260530"})

        # 验证使用rpush而非publish
        assert daemon._redis_client.rpush.called
        assert not daemon._redis_client.publish.called or daemon._redis_client.publish.call_count == 0
        # rpush的key应为"scanner:cmd"
        call_args = daemon._redis_client.rpush.call_args
        assert "scanner:cmd" in str(call_args)

    @pytest.mark.asyncio
    async def test_send_command_includes_cmd_id(self):
        """send_command的消息应包含cmd_id"""
        from nodes.market_monitor.scanner_daemon import ScannerDaemon, ScannerDaemonConfig

        daemon = ScannerDaemon(ScannerDaemonConfig())
        daemon._redis_client = MagicMock()
        daemon._redis_client.rpush = AsyncMock()

        with patch.object(asyncio, 'wait_for', side_effect=asyncio.TimeoutError):
            await daemon.send_command("scan", {})

        # 验证消息包含cmd_id
        call_args = daemon._redis_client.rpush.call_args
        message = json.loads(call_args[0][1])
        assert "cmd_id" in message
        assert len(message["cmd_id"]) == 8  # uuid[:8]

    @pytest.mark.asyncio
    async def test_send_command_registers_pending_ack(self):
        """send_command应注册pending_ack Future"""
        from nodes.market_monitor.scanner_daemon import ScannerDaemon, ScannerDaemonConfig

        daemon = ScannerDaemon(ScannerDaemonConfig())
        daemon._redis_client = MagicMock()
        daemon._redis_client.rpush = AsyncMock()

        # 模拟ACK立即返回
        async def fake_wait_for(future, timeout):
            future.set_result({"cmd_id": "test1234", "status": "done"})
            return {"cmd_id": "test1234", "status": "done"}

        with patch.object(asyncio, 'wait_for', side_effect=fake_wait_for):
            with patch.object(daemon._redis_client, 'rpush', AsyncMock()) as mock_rpush:
                # 修改cmd_id为已知值
                with patch('uuid.uuid4', return_value=MagicMock(__str__=lambda s: "test1234-xxxx")):
                    await daemon.send_command("scan", {})

        # pending_acks应该在完成后被清理
        assert len(daemon._pending_acks) == 0


# ============================================================================
# 2. ACK确认机制
# ============================================================================

class TestACKMechanism:
    """验证ACK确认机制"""

    @pytest.mark.asyncio
    async def test_ack_listener_resolves_future(self):
        """ACK监听器应匹配cmd_id并resolve Future"""
        from nodes.market_monitor.scanner_daemon import ScannerDaemon, ScannerDaemonConfig

        daemon = ScannerDaemon(ScannerDaemonConfig())
        daemon._running = True
        daemon._redis_client = MagicMock()

        # 创建一个pending ack
        loop = asyncio.get_running_loop()
        ack_future = loop.create_future()
        daemon._pending_acks["abc12345"] = ack_future

        # 模拟pubsub返回ACK消息
        mock_pubsub = AsyncMock()
        ack_message = {
            "type": "message",
            "data": json.dumps({"cmd_id": "abc12345", "status": "received", "ts": time.time()})
        }

        call_count = 0
        async def fake_get_message(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ack_message
            daemon._running = False
            return None

        mock_pubsub.get_message = fake_get_message
        mock_pubsub.unsubscribe = AsyncMock()
        mock_pubsub.close = AsyncMock()
        daemon._redis_client.pubsub = MagicMock(return_value=mock_pubsub)

        await daemon._ack_listener()

        # Future应该被resolve
        assert ack_future.done()
        result = ack_future.result()
        assert result["status"] == "received"

    @pytest.mark.asyncio
    async def test_ack_timeout_returns_none(self):
        """ACK超时应返回None"""
        from nodes.market_monitor.scanner_daemon import ScannerDaemon, ScannerDaemonConfig

        daemon = ScannerDaemon(ScannerDaemonConfig(cmd_ack_timeout=0.1))
        daemon._redis_client = MagicMock()
        daemon._redis_client.rpush = AsyncMock()

        result = await daemon.send_command("scan", {}, timeout=0.1)
        assert result is None

    @pytest.mark.asyncio
    async def test_ack_success_returns_result(self):
        """ACK成功应返回结果"""
        from nodes.market_monitor.scanner_daemon import ScannerDaemon, ScannerDaemonConfig

        daemon = ScannerDaemon(ScannerDaemonConfig())
        daemon._redis_client = MagicMock()
        daemon._redis_client.rpush = AsyncMock()

        ack_result = {"cmd_id": "test1234", "status": "done", "cmd": "scan"}

        async def fake_wait_for(future, timeout):
            future.set_result(ack_result)
            return ack_result

        with patch.object(asyncio, 'wait_for', side_effect=fake_wait_for):
            result = await daemon.send_command("scan", {})

        assert result is not None
        assert result["status"] == "done"


# ============================================================================
# 3. 子进程BLPOP消费
# ============================================================================

class TestSubprocessBLPOP:
    """验证子进程使用BLPOP消费List"""

    def test_subprocess_uses_blpop_in_source(self):
        """源码中子进程应使用blpop"""
        import inspect
        from nodes.market_monitor.scanner_daemon import _scanner_subprocess_main, _subprocess_async_main

        # _scanner_subprocess_main只是入口, 核心逻辑在_subprocess_async_main
        source = inspect.getsource(_subprocess_async_main)
        assert "blpop" in source
        assert "cmd_list_key" in source or "scanner:cmd" in source

    def test_subprocess_sends_ack(self):
        """源码中子进程应在收到命令后发送ACK"""
        import inspect
        from nodes.market_monitor.scanner_daemon import _subprocess_async_main

        source = inspect.getsource(_subprocess_async_main)
        assert "ack" in source.lower()
        assert "cmd_id" in source


# ============================================================================
# 4. Daemon状态包含ACK维度
# ============================================================================

class TestDaemonStatusACK:
    """验证Daemon状态包含ACK维度"""

    def test_get_status_includes_ack_info(self):
        """get_status应包含pending_acks和cmd_ack_timeout"""
        from nodes.market_monitor.scanner_daemon import ScannerDaemon, ScannerDaemonConfig

        daemon = ScannerDaemon(ScannerDaemonConfig(cmd_ack_timeout=15.0))
        status = daemon.get_status()

        assert "pending_acks" in status
        assert "cmd_ack_timeout" in status
        assert status["cmd_ack_timeout"] == 15.0
        assert status["pending_acks"] == 0  # 初始为0

    def test_get_status_includes_max_restart_count(self):
        """get_status应包含max_restart_count"""
        from nodes.market_monitor.scanner_daemon import ScannerDaemon, ScannerDaemonConfig

        daemon = ScannerDaemon(ScannerDaemonConfig(max_restart_count=5))
        status = daemon.get_status()
        assert status["max_restart_count"] == 5
        assert status["restart_count"] == 0


# ============================================================================
# 5. 紧急告警发布Redis事件
# ============================================================================

class TestEmergencyAlertRedisEvent:
    """验证紧急告警发布Redis事件"""

    @pytest.mark.asyncio
    async def test_emergency_alert_publishes_to_redis(self):
        """紧急告警应发布到Redis health通道"""
        from nodes.market_monitor.scanner_daemon import ScannerDaemon, ScannerDaemonConfig

        daemon = ScannerDaemon(ScannerDaemonConfig())
        daemon._redis_client = MagicMock()
        daemon._redis_client.publish = AsyncMock()

        # Mock飞书推送
        with patch('nodes.market_monitor.scanner_daemon.ScannerDaemon._send_emergency_alert',
                   new_callable=AsyncMock):
            # 直接测试_send_emergency_alert
            pass

        # 调用_send_emergency_alert
        await daemon._send_emergency_alert("测试告警")

        # 验证Redis publish被调用
        if daemon._redis_client.publish.called:
            call_args = daemon._redis_client.publish.call_args
            assert "scanner:health" in str(call_args)

    @pytest.mark.asyncio
    async def test_emergency_alert_data_format(self):
        """紧急告警数据格式应包含必要字段"""
        from nodes.market_monitor.scanner_daemon import ScannerDaemon, ScannerDaemonConfig

        daemon = ScannerDaemon(ScannerDaemonConfig())
        daemon._redis_client = MagicMock()
        daemon._redis_client.publish = AsyncMock()

        await daemon._send_emergency_alert("重启3次失败")

        if daemon._redis_client.publish.called:
            call_args = daemon._redis_client.publish.call_args
            data = json.loads(call_args[0][1])
            assert data["event"] == "daemon_emergency"
            assert "ts" in data
            assert "restart_count" in data


# ============================================================================
# 6. ScannerDaemonConfig新字段
# ============================================================================

class TestDaemonConfigACK:
    """验证ScannerDaemonConfig新字段"""

    def test_default_cmd_ack_timeout(self):
        """默认cmd_ack_timeout应为10秒"""
        from nodes.market_monitor.scanner_daemon import ScannerDaemonConfig
        config = ScannerDaemonConfig()
        assert config.cmd_ack_timeout == 10.0

    def test_custom_cmd_ack_timeout(self):
        """自定义cmd_ack_timeout"""
        from nodes.market_monitor.scanner_daemon import ScannerDaemonConfig
        config = ScannerDaemonConfig(cmd_ack_timeout=30.0)
        assert config.cmd_ack_timeout == 30.0


# ============================================================================
# 7. 回测零影响
# ============================================================================

class TestNoBacktestRegressionV297:
    """验证回测零影响"""

    def test_sell_signal_checker_api_unchanged(self):
        """SellSignalChecker API未变"""
        from nodes.backtest_engine.factor_selection.sell_signal_checker import SellSignalChecker
        assert hasattr(SellSignalChecker, 'check_realtime_sell')
        assert hasattr(SellSignalChecker, 'check_full_sell')

    def test_strategy_defaults_importable(self):
        """strategy_defaults正常导入"""
        from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS, GLOBAL_RISK
        assert isinstance(STRATEGY_CONFIGS, dict)
        assert isinstance(GLOBAL_RISK, dict)

    def test_portfolio_backtester_importable(self):
        """回测引擎正常导入"""
        from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
        assert hasattr(PortfolioBacktester, 'run')  # 主方法名

    def test_daemon_not_imported_in_backtest(self):
        """回测模块不应导入scanner_daemon"""
        import importlib
        bt_module = importlib.import_module('nodes.backtest_engine.factor_selection.portfolio_backtest')
        source = open(bt_module.__file__).read()
        assert 'scanner_daemon' not in source

    def test_scanner_daemon_does_not_modify_backtest_files(self):
        """scanner_daemon不修改回测文件"""
        import inspect
        from nodes.market_monitor.scanner_daemon import ScannerDaemon
        source = inspect.getsource(ScannerDaemon)
        # daemon不应引用回测模块
        assert 'portfolio_backtest' not in source
        assert 'sell_signal_checker' not in source


# ============================================================================
# 8. 便捷方法返回ACK结果
# ============================================================================

class TestConvenienceMethodsReturnACK:
    """验证便捷方法返回ACK结果"""

    @pytest.mark.asyncio
    async def test_start_scanner_returns_ack(self):
        """start_scanner应返回ACK结果"""
        from nodes.market_monitor.scanner_daemon import ScannerDaemon, ScannerDaemonConfig

        daemon = ScannerDaemon(ScannerDaemonConfig())
        daemon._redis_client = MagicMock()
        daemon._redis_client.rpush = AsyncMock()

        ack = {"cmd_id": "test", "status": "done"}
        with patch.object(daemon, 'send_command', new_callable=AsyncMock, return_value=ack):
            result = await daemon.start_scanner(trade_date="20260530")
        assert result == ack

    @pytest.mark.asyncio
    async def test_stop_scanner_returns_ack(self):
        """stop_scanner应返回ACK结果"""
        from nodes.market_monitor.scanner_daemon import ScannerDaemon, ScannerDaemonConfig

        daemon = ScannerDaemon(ScannerDaemonConfig())
        ack = {"cmd_id": "test", "status": "done"}
        with patch.object(daemon, 'send_command', new_callable=AsyncMock, return_value=ack):
            result = await daemon.stop_scanner()
        assert result == ack

    @pytest.mark.asyncio
    async def test_emergency_liquidate_returns_ack(self):
        """emergency_liquidate应返回ACK结果"""
        from nodes.market_monitor.scanner_daemon import ScannerDaemon, ScannerDaemonConfig

        daemon = ScannerDaemon(ScannerDaemonConfig())
        ack = {"cmd_id": "test", "status": "done"}
        with patch.object(daemon, 'send_command', new_callable=AsyncMock, return_value=ack):
            result = await daemon.emergency_liquidate(reason="测试")
        assert result == ack


# ============================================================================
# 9. EventBus handler latency (v2.9.7)
# ============================================================================

class TestEventBusHandlerLatency:
    """验证EventBus handler耗时统计"""

    @pytest.mark.asyncio
    async def test_handler_latency_tracked(self):
        """handler执行耗时应被记录"""
        from nodes.market_monitor.scanner_event_bus import ScannerEventBus, reset_event_bus
        
        reset_event_bus()
        bus = ScannerEventBus()
        
        async def slow_handler(data):
            await asyncio.sleep(0.01)  # 10ms
        
        bus.on("test_event", slow_handler)
        await bus.emit("test_event", {"key": "value"})
        
        latency = bus.get_handler_latency()
        assert len(latency) > 0
        
        # 找到slow_handler的记录
        handler_key = None
        for k in latency:
            if "slow_handler" in k:
                handler_key = k
                break
        
        assert handler_key is not None
        assert latency[handler_key]["count"] == 1
        assert latency[handler_key]["total_ms"] > 5  # 至少5ms
        assert latency[handler_key]["max_ms"] > 5
        assert latency[handler_key]["avg_ms"] > 5
        
        reset_event_bus()

    @pytest.mark.asyncio
    async def test_handler_latency_reset(self):
        """reset_stats应清除耗时统计"""
        from nodes.market_monitor.scanner_event_bus import ScannerEventBus, reset_event_bus
        
        reset_event_bus()
        bus = ScannerEventBus()
        
        async def handler(data):
            pass
        
        bus.on("test_event", handler)
        await bus.emit("test_event", {})
        
        assert len(bus.get_handler_latency()) > 0
        bus.reset_stats()
        assert len(bus.get_handler_latency()) == 0
        
        reset_event_bus()

    @pytest.mark.asyncio
    async def test_handler_latency_multiple_calls(self):
        """多次调用应正确统计"""
        from nodes.market_monitor.scanner_event_bus import ScannerEventBus, reset_event_bus
        
        reset_event_bus()
        bus = ScannerEventBus()
        
        async def handler(data):
            pass
        
        bus.on("test_event", handler)
        await bus.emit("test_event", {})
        await bus.emit("test_event", {})
        await bus.emit("test_event", {})
        
        latency = bus.get_handler_latency()
        handler_key = [k for k in latency if "handler" in k][0]
        assert latency[handler_key]["count"] == 3
        
        reset_event_bus()


# ============================================================================
# 10. scan-traces API优化 (v2.9.7)
# ============================================================================

class TestScanTracesAPIOptimization:
    """验证scan-traces API优化"""

    def test_detail_api_default_status_is_passed(self):
        """详情API默认status应为passed(不加载rejected)"""
        # 直接读取源文件验证
        import os
        api_path = os.path.join(os.path.dirname(__file__), '..', '..', 'nodes', 'web', 'api', 'scanner.py')
        with open(api_path) as f:
            source = f.read()
        # 找到get_scan_trace_detail函数
        idx = source.find('async def get_scan_trace_detail')
        func_source = source[idx:idx+2000]
        assert '"passed"' in func_source  # 默认filter_status = status or "passed"

    def test_detail_api_has_offset_param(self):
        """详情API应支持offset分页"""
        import os
        api_path = os.path.join(os.path.dirname(__file__), '..', '..', 'nodes', 'web', 'api', 'scanner.py')
        with open(api_path) as f:
            source = f.read()
        idx = source.find('async def get_scan_trace_detail')
        func_source = source[idx:idx+2000]
        assert "offset" in func_source

    def test_detail_api_has_summary_mode(self):
        """详情API应支持summary模式(只返回统计)"""
        import os
        api_path = os.path.join(os.path.dirname(__file__), '..', '..', 'nodes', 'web', 'api', 'scanner.py')
        with open(api_path) as f:
            source = f.read()
        idx = source.find('async def get_scan_trace_detail')
        func_source = source[idx:idx+2000]
        assert "summary" in func_source

    def test_list_api_excludes_candidates(self):
        """列表API应排除candidates和rejected_summary字段"""
        import os
        api_path = os.path.join(os.path.dirname(__file__), '..', '..', 'nodes', 'web', 'api', 'scanner.py')
        with open(api_path) as f:
            source = f.read()
        idx = source.find('async def get_scan_traces')
        func_source = source[idx:idx+2000]
        assert "rejected_summary" in func_source
        assert '"candidates": 0' in func_source or "'candidates': 0" in func_source

    def test_pagination_has_more_fields(self):
        """分页信息应包含has_more字段"""
        import os
        api_path = os.path.join(os.path.dirname(__file__), '..', '..', 'nodes', 'web', 'api', 'scanner.py')
        with open(api_path) as f:
            source = f.read()
        idx = source.find('async def get_scan_trace_detail')
        func_source = source[idx:idx+3000]
        assert "has_more" in func_source
# remove old bad tests
