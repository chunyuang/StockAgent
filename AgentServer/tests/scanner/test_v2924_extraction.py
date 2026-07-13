#!/usr/bin/env python3
"""v2.9.24 diagnose+情绪调仓提取测试

变更点:
1. diagnose()从scanner提取到ScannerUtils.diagnose(scanner), 通过DELEGATE_MAP委托
2. _handle_emotion_phase_change从scanner提取到EmotionCycleManager.handle_emotion_phase_change, 通过DELEGATE_MAP委托
3. DelegateRouter新增_emotion_cycle_class策略+EmotionCycleManager绑定
4. scanner.py 2103→1966行(-6.5%)
"""
import os
import sys
import time
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


class TestDiagnoseDelegation:
    """diagnose()委托到ScannerUtils测试"""

    def _make_minimal_scanner(self):
        """创建最小可诊断的scanner实例"""
        from nodes.market_monitor.scanner import MarketScanner
        scanner = MarketScanner.__new__(MarketScanner)
        scanner._is_running = True
        scanner._risk_running = False
        scanner._risk_thread = None
        scanner._risk_thread_restarts = 0
        scanner._last_realtime_update_ts = time.time()
        scanner._active_signals = []
        scanner._pending_sells = {}
        scanner._circuit_breaker = {"trading_paused": False, "pause_reason": ""}
        scanner._last_risk_check_ts = time.time()
        scanner._scan_loop_error_count = 0
        scanner._broker = MagicMock()
        scanner._broker.get_positions.return_value = [MagicMock()]
        return scanner

    def test_diagnose_via_delegation(self):
        """scanner.diagnose()通过DELEGATE_MAP委托到ScannerUtils"""
        scanner = self._make_minimal_scanner()
        # 通过__getattr__委托调用
        result = scanner.diagnose()
        assert result["healthy"] is True
        assert result["issues"] == []

    def test_diagnose_direct_utils_call(self):
        """ScannerUtils.diagnose(scanner)直接调用结果一致"""
        scanner = self._make_minimal_scanner()
        from nodes.market_monitor.scanner_utils import ScannerUtils
        direct_result = ScannerUtils.diagnose(scanner)
        delegate_result = scanner.diagnose()
        assert direct_result["healthy"] == delegate_result["healthy"]
        assert len(direct_result["issues"]) == len(delegate_result["issues"])

    def test_diagnose_delegation_stale_cache(self):
        """委托调用diagnose检测行情缓存过期"""
        scanner = self._make_minimal_scanner()
        scanner._last_realtime_update_ts = time.time() - 180
        result = scanner.diagnose()
        assert any(i["area"] == "quote_cache" for i in result["issues"])

    def test_diagnose_in_delegate_map(self):
        """diagnose在DELEGATE_MAP中正确注册"""
        from nodes.market_monitor.scanner import MarketScanner
        assert "diagnose" in MarketScanner._DELEGATE_MAP
        assert MarketScanner._DELEGATE_MAP["diagnose"] == ("_scanner_utils", "diagnose")


class TestEmotionPhaseChangeDelegation:
    """_handle_emotion_phase_change委托到EmotionCycleManager测试"""

    def _make_emotion_scanner(self):
        """创建带情绪调仓能力的scanner"""
        from nodes.market_monitor.scanner import MarketScanner
        scanner = MarketScanner.__new__(MarketScanner)
        scanner._broker = MagicMock()
        scanner._broker.get_positions.return_value = []
        scanner._position_checker = MagicMock()
        scanner._position_checker.execute_sell_list = AsyncMock()
        scanner._trade_date = "20260531"
        scanner._pending_sells = {}
        scanner._state_lock = None
        scanner._publish_scanner_event = AsyncMock()
        scanner._build_emotion_sell_list = MagicMock(return_value=[])
        scanner._is_limit_down = MagicMock(return_value=False)
        return scanner

    @pytest.mark.asyncio
    async def test_emotion_via_delegation_no_rule(self):
        """无降级规则时不调仓(上升→上升)"""
        scanner = self._make_emotion_scanner()
        await scanner._handle_emotion_phase_change('rising', 'rising')
        # 无降级规则,不应调仓
        scanner._build_emotion_sell_list.assert_not_called()

    @pytest.mark.asyncio
    async def test_emotion_via_delegation_with_positions(self):
        """有降级规则且有持仓时触发调仓"""
        scanner = self._make_emotion_scanner()
        # 模拟有持仓
        mock_pos = MagicMock()
        mock_pos.ts_code = "600036.SH"
        mock_pos.profit_pct = 1.0
        mock_pos.available_qty = 100
        mock_pos.current_price = 10.1
        scanner._broker.get_positions.return_value = [mock_pos]
        # 返回卖出列表
        scanner._build_emotion_sell_list = MagicMock(return_value=[(mock_pos, "降级", 10.1, {})])
        # Mock is_continuous_auction to return True (非交易时间会跳过卖出)
        with patch('nodes.market_monitor.market_phase.MarketPhase.is_continuous_auction', return_value=True):
            await scanner._handle_emotion_phase_change('rising', 'bearish')
            scanner._build_emotion_sell_list.assert_called_once()
            scanner._position_checker.execute_sell_list.assert_called_once()

    def test_emotion_in_delegate_map(self):
        """_handle_emotion_phase_change在DELEGATE_MAP中正确注册"""
        from nodes.market_monitor.scanner import MarketScanner
        assert "_handle_emotion_phase_change" in MarketScanner._DELEGATE_MAP
        assert MarketScanner._DELEGATE_MAP["_handle_emotion_phase_change"] == ("_emotion_cycle_class", "handle_emotion_phase_change")


class TestDelegateRouterEmotionStrategy:
    """DelegateRouter的EmotionCycleManager路由策略测试"""

    def test_emotion_binder_exists(self):
        """_EMOTION_BINDINGS中注册了handle_emotion_phase_change"""
        from nodes.market_monitor.scanner_delegate_router import _EMOTION_BINDINGS
        assert "handle_emotion_phase_change" in _EMOTION_BINDINGS

    def test_emotion_in_async_delegates(self):
        """_handle_emotion_phase_change在ASYNC_DELEGATE_METHODS中"""
        from nodes.market_monitor.scanner_delegate_router import _ASYNC_DELEGATE_METHODS
        assert "_handle_emotion_phase_change" in _ASYNC_DELEGATE_METHODS

    def test_resolve_emotion_returns_callable(self):
        """resolve_delegate为_emotion_cycle_class返回可调用对象"""
        from nodes.market_monitor.scanner_delegate_router import resolve_delegate
        from nodes.market_monitor.scanner import MarketScanner
        scanner = MarketScanner.__new__(MarketScanner)
        result = resolve_delegate(scanner, "_handle_emotion_phase_change", ("_emotion_cycle_class", "handle_emotion_phase_change"))
        assert callable(result)


class TestScannerLineCount:
    """scanner.py行数回归测试"""

    def test_scanner_under_2000(self):
        """scanner.py行数应低于2000行(v2.9.24: 1966行)"""
        import os
        path = os.path.join(os.path.dirname(__file__), '..', '..', 'nodes', 'market_monitor', 'scanner.py')
        with open(path) as f:
            lines = len(f.readlines())
        assert lines < 2000, f"scanner.py {lines}行, 应<2000行"


class TestEmotionCycleManagerHandleMethod:
    """EmotionCycleManager.handle_emotion_phase_change单元测试"""

    def test_method_is_static(self):
        """handle_emotion_phase_change是静态方法"""
        from nodes.market_monitor.emotion_cycle import EmotionCycleManager
        # 静态方法可以直接从类调用,不需要实例
        assert callable(EmotionCycleManager.handle_emotion_phase_change)

    def test_invalid_phase_no_crash(self):
        """无效的phase名称不会崩溃"""
        from nodes.market_monitor.emotion_cycle import EmotionCycleManager
        scanner = MagicMock()
        scanner._broker = None
        # 不做任何操作,因为broker=None应该早返回
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            loop.run_until_complete(
                EmotionCycleManager.handle_emotion_phase_change(scanner, 'invalid', 'also_invalid')
            )
        except RuntimeError:
            # 无event loop时创建新的
            asyncio.run(
                EmotionCycleManager.handle_emotion_phase_change(scanner, 'invalid', 'also_invalid')
            )
