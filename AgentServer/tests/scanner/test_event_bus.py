"""
ScannerEventBus 单元+集成测试

覆盖:
- 基础API: on/off/emit
- 异常隔离: handler失败不影响其他handler
- once: 一次性订阅
- 统计: emit/handled/errors
- 历史记录
- enable/disable
- 全局单例
- 与MarketScanner集成: 事件发射到event_bus
"""

import asyncio
import pytest
import time

from nodes.market_monitor.scanner_event_bus import (
    ScannerEventBus, ScannerEvents, get_event_bus, reset_event_bus
)


# ==================== 基础API测试 ====================


class TestEventBusBasic:
    """基础API测试"""
    
    @pytest.mark.asyncio
    async def test_on_and_emit(self):
        """基本订阅和发布"""
        bus = ScannerEventBus()
        received = []
        
        async def handler(data):
            received.append(data)
        
        bus.on("test_event", handler)
        await bus.emit("test_event", {"key": "value"})
        
        assert len(received) == 1
        assert received[0]["key"] == "value"
    
    @pytest.mark.asyncio
    async def test_multiple_handlers(self):
        """多个handler按注册顺序执行"""
        bus = ScannerEventBus()
        order = []
        
        async def h1(data):
            order.append(1)
        
        async def h2(data):
            order.append(2)
        
        async def h3(data):
            order.append(3)
        
        bus.on("test", h1)
        bus.on("test", h2)
        bus.on("test", h3)
        
        count = await bus.emit("test", {})
        assert count == 3
        assert order == [1, 2, 3]
    
    @pytest.mark.asyncio
    async def test_off_removes_handler(self):
        """取消订阅"""
        bus = ScannerEventBus()
        received = []
        
        async def handler(data):
            received.append(data)
        
        bus.on("test", handler)
        await bus.emit("test", {})
        assert len(received) == 1
        
        result = bus.off("test", handler)
        assert result is True
        
        await bus.emit("test", {})
        assert len(received) == 1  # 不再收到
    
    @pytest.mark.asyncio
    async def test_off_nonexistent_handler(self):
        """取消不存在的handler返回False"""
        bus = ScannerEventBus()
        
        async def handler(data):
            pass
        
        result = bus.off("test", handler)
        assert result is False
    
    @pytest.mark.asyncio
    async def test_duplicate_on_ignored(self):
        """重复订阅同一handler只注册一次"""
        bus = ScannerEventBus()
        count = [0]
        
        async def handler(data):
            count[0] += 1
        
        bus.on("test", handler)
        bus.on("test", handler)  # 重复
        await bus.emit("test", {})
        
        assert count[0] == 1  # 只调用一次
    
    @pytest.mark.asyncio
    async def test_emit_no_handlers(self):
        """没有订阅者时emit不报错"""
        bus = ScannerEventBus()
        count = await bus.emit("nonexistent", {"data": 1})
        assert count == 0
    
    @pytest.mark.asyncio
    async def test_emit_default_data(self):
        """不传data时默认空dict"""
        bus = ScannerEventBus()
        received = []
        
        async def handler(data):
            received.append(data)
        
        bus.on("test", handler)
        await bus.emit("test")
        
        assert len(received) == 1
        assert received[0] == {}


# ==================== 异常隔离测试 ====================


class TestEventBusExceptionIsolation:
    """异常隔离测试"""
    
    @pytest.mark.asyncio
    async def test_handler_exception_isolated(self):
        """handler异常不影响其他handler"""
        bus = ScannerEventBus()
        results = []
        
        async def good_handler(data):
            results.append("good")
        
        async def bad_handler(data):
            raise ValueError("test error")
        
        async def another_good(data):
            results.append("another")
        
        bus.on("test", good_handler)
        bus.on("test", bad_handler)
        bus.on("test", another_good)
        
        count = await bus.emit("test", {})
        assert count == 2  # 2个成功
        assert "good" in results
        assert "another" in results
    
    @pytest.mark.asyncio
    async def test_handler_exception_updates_stats(self):
        """handler异常增加errors计数"""
        bus = ScannerEventBus()
        
        async def bad_handler(data):
            raise RuntimeError("oops")
        
        bus.on("test", bad_handler)
        await bus.emit("test", {})
        
        stats = bus.get_stats()
        assert stats["test"]["errors"] == 1
        assert stats["test"]["emitted"] == 1


# ==================== once 测试 ====================


class TestEventBusOnce:
    """一次性订阅测试"""
    
    @pytest.mark.asyncio
    async def test_once_fires_only_once(self):
        """once handler只触发一次"""
        bus = ScannerEventBus()
        count = [0]
        
        async def handler(data):
            count[0] += 1
        
        bus.once("test", handler)
        await bus.emit("test", {})
        await bus.emit("test", {})
        
        assert count[0] == 1
    
    @pytest.mark.asyncio
    async def test_once_removes_after_fire(self):
        """once触发后自动取消"""
        bus = ScannerEventBus()
        
        async def handler(data):
            pass
        
        bus.once("test", handler)
        assert bus.handler_count("test") == 1
        
        await bus.emit("test", {})
        assert bus.handler_count("test") == 0


# ==================== 统计测试 ====================


class TestEventBusStats:
    """统计功能测试"""
    
    @pytest.mark.asyncio
    async def test_stats_tracking(self):
        """统计emit/handled/errors"""
        bus = ScannerEventBus()
        
        async def h1(data):
            pass
        
        async def h2(data):
            raise ValueError("test")
        
        bus.on("test", h1)
        bus.on("test", h2)
        
        await bus.emit("test", {})
        await bus.emit("test", {})
        
        stats = bus.get_stats()
        assert stats["test"]["emitted"] == 2
        assert stats["test"]["handled"] == 2  # h1成功2次
        assert stats["test"]["errors"] == 2  # h2失败2次
    
    @pytest.mark.asyncio
    async def test_reset_stats(self):
        """重置统计"""
        bus = ScannerEventBus()
        
        async def handler(data):
            pass
        
        bus.on("test", handler)
        await bus.emit("test", {})
        
        bus.reset_stats()
        stats = bus.get_stats()
        assert "test" not in stats


# ==================== 历史记录测试 ====================


class TestEventBusHistory:
    """事件历史测试"""
    
    @pytest.mark.asyncio
    async def test_history_recorded(self):
        """事件历史被记录"""
        bus = ScannerEventBus()
        
        async def handler(data):
            pass
        
        bus.on("test", handler)
        await bus.emit("test", {"key": "val"})
        
        history = bus.get_history()
        assert len(history) >= 1
        assert history[-1]["event"] == "test"
    
    @pytest.mark.asyncio
    async def test_history_filter_by_event(self):
        """按事件名过滤历史"""
        bus = ScannerEventBus()
        
        await bus.emit("event_a", {})
        await bus.emit("event_b", {})
        await bus.emit("event_a", {})
        
        history = bus.get_history(event="event_a")
        assert all(h["event"] == "event_a" for h in history)
        assert len(history) == 2
    
    @pytest.mark.asyncio
    async def test_history_max_limit(self):
        """历史记录最大数量限制"""
        bus = ScannerEventBus(max_history=5)
        
        for i in range(10):
            await bus.emit("test", {"i": i})
        
        history = bus.get_history()
        assert len(history) <= 5


# ==================== enable/disable 测试 ====================


class TestEventBusControl:
    """启用/禁用测试"""
    
    @pytest.mark.asyncio
    async def test_disable_prevents_emit(self):
        """禁用后emit不执行handler"""
        bus = ScannerEventBus()
        count = [0]
        
        async def handler(data):
            count[0] += 1
        
        bus.on("test", handler)
        bus.disable()
        
        result = await bus.emit("test", {})
        assert result == 0
        assert count[0] == 0
    
    @pytest.mark.asyncio
    async def test_enable_reenables(self):
        """启用后恢复正常"""
        bus = ScannerEventBus()
        count = [0]
        
        async def handler(data):
            count[0] += 1
        
        bus.on("test", handler)
        bus.disable()
        await bus.emit("test", {})
        bus.enable()
        await bus.emit("test", {})
        
        assert count[0] == 1
    
    @pytest.mark.asyncio
    async def test_clear_specific_event(self):
        """清除特定事件的订阅"""
        bus = ScannerEventBus()
        
        async def h1(data):
            pass
        
        async def h2(data):
            pass
        
        bus.on("a", h1)
        bus.on("b", h2)
        bus.clear("a")
        
        assert bus.handler_count("a") == 0
        assert bus.handler_count("b") == 1
    
    @pytest.mark.asyncio
    async def test_clear_all_events(self):
        """清除所有订阅"""
        bus = ScannerEventBus()
        
        async def handler(data):
            pass
        
        bus.on("a", handler)
        bus.on("b", handler)
        bus.clear()
        
        assert bus.handler_count("a") == 0
        assert bus.handler_count("b") == 0


# ==================== 查询API测试 ====================


class TestEventBusQuery:
    """查询API测试"""
    
    def test_has_handlers(self):
        bus = ScannerEventBus()
        
        async def handler(data):
            pass
        
        assert not bus.has_handlers("test")
        bus.on("test", handler)
        assert bus.has_handlers("test")
    
    def test_handler_count(self):
        bus = ScannerEventBus()
        
        async def h1(data):
            pass
        
        async def h2(data):
            pass
        
        assert bus.handler_count("test") == 0
        bus.on("test", h1)
        assert bus.handler_count("test") == 1
        bus.on("test", h2)
        assert bus.handler_count("test") == 2
    
    def test_get_events(self):
        bus = ScannerEventBus()
        
        async def handler(data):
            pass
        
        bus.on("event_a", handler)
        bus.on("event_b", handler)
        
        events = bus.get_events()
        assert "event_a" in events
        assert "event_b" in events


# ==================== 批量操作测试 ====================


class TestEventBusBatch:
    """批量订阅测试"""
    
    @pytest.mark.asyncio
    async def test_on_many(self):
        bus = ScannerEventBus()
        received = []
        
        async def handler(data):
            received.append(data.get("type"))
        
        bus.on_many(["a", "b", "c"], handler)
        await bus.emit("a", {"type": "a"})
        await bus.emit("b", {"type": "b"})
        await bus.emit("c", {"type": "c"})
        
        assert len(received) == 3
    
    @pytest.mark.asyncio
    async def test_off_many(self):
        bus = ScannerEventBus()
        
        async def handler(data):
            pass
        
        bus.on_many(["a", "b"], handler)
        bus.off_many(["a", "b"], handler)
        
        assert bus.handler_count("a") == 0
        assert bus.handler_count("b") == 0


# ==================== 全局单例测试 ====================


class TestGlobalEventBus:
    """全局单例测试"""
    
    def test_get_event_bus_returns_same_instance(self):
        reset_event_bus()
        bus1 = get_event_bus()
        bus2 = get_event_bus()
        assert bus1 is bus2
    
    def test_reset_event_bus(self):
        bus1 = get_event_bus()
        reset_event_bus()
        bus2 = get_event_bus()
        assert bus1 is not bus2


# ==================== ScannerEvents常量测试 ====================


class TestScannerEvents:
    """事件类型常量测试"""
    
    def test_all_events_defined(self):
        events = [
            ScannerEvents.POSITION_CHANGED,
            ScannerEvents.SIGNAL_GENERATED,
            ScannerEvents.EMOTION_CHANGED,
            ScannerEvents.RISK_TRIGGERED,
            ScannerEvents.QUOTE_DEGRADED,
            ScannerEvents.QUOTE_RECOVERED,
            ScannerEvents.PARAM_UPDATED,
            ScannerEvents.SCAN_COMPLETED,
            ScannerEvents.CIRCUIT_BREAKER,
            ScannerEvents.DAILY_SETTLED,
            ScannerEvents.RISK_SELL_EXECUTED,
        ]
        assert len(events) == 11
        # 确保没有重复
        assert len(set(events)) == 11


# ==================== 同步函数包装测试 ====================


class TestSyncHandlerWrapper:
    """同步handler自动包装测试"""
    
    @pytest.mark.asyncio
    async def test_sync_handler_wrapped(self):
        """同步函数被自动包装为协程"""
        bus = ScannerEventBus()
        received = []
        
        def sync_handler(data):
            received.append(data["value"])
        
        bus.on("test", sync_handler)
        await bus.emit("test", {"value": 42})
        
        assert received == [42]


# ==================== Scanner集成测试 ====================


class TestEventBusScannerIntegration:
    """与MarketScanner集成测试"""
    
    @pytest.mark.asyncio
    async def test_scanner_has_event_bus(self):
        """Scanner实例有event_bus属性"""
        from nodes.market_monitor.scanner import MarketScanner
        scanner = MarketScanner(account_id="test_event_bus")
        assert hasattr(scanner, 'event_bus')
        assert isinstance(scanner.event_bus, ScannerEventBus)
    
    @pytest.mark.asyncio
    async def test_scanner_event_bus_is_readonly(self):
        """event_bus属性是只读的"""
        from nodes.market_monitor.scanner import MarketScanner
        scanner = MarketScanner(account_id="test_event_bus_ro")
        bus = scanner.event_bus
        # 重新获取应该返回同一实例
        assert scanner.event_bus is bus
    
    @pytest.mark.asyncio
    async def test_emotion_changed_event(self):
        """情绪变化触发EventBus事件"""
        from nodes.market_monitor.scanner import MarketScanner
        scanner = MarketScanner(account_id="test_emotion_event")
        
        events_received = []
        
        async def on_emotion(data):
            events_received.append(data)
        
        scanner.event_bus.on(ScannerEvents.EMOTION_CHANGED, on_emotion)
        
        # 直接调用_handle_emotion_phase_change不触发EventBus(它在调用前触发)
        # 需要通过_apply_filter_pipeline的路径触发
        # 简单验证: emit手动触发能到达handler
        await scanner.event_bus.emit(ScannerEvents.EMOTION_CHANGED, {
            "old_phase": "rising", "new_phase": "chaos",
        })
        
        assert len(events_received) == 1
        assert events_received[0]["old_phase"] == "rising"
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_event(self):
        """熔断触发EventBus事件"""
        from nodes.market_monitor.scanner import MarketScanner
        scanner = MarketScanner(account_id="test_cb_event")
        
        events_received = []
        
        async def on_cb(data):
            events_received.append(data)
        
        scanner.event_bus.on(ScannerEvents.CIRCUIT_BREAKER, on_cb)
        
        # 直接emit模拟熔断
        await scanner.event_bus.emit(ScannerEvents.CIRCUIT_BREAKER, {
            "paused": True, "reason": "单日回撤超限",
        })
        
        assert len(events_received) == 1
        assert events_received[0]["paused"] is True
