"""
ScannerEventBus — Scanner内部事件总线

解决核心问题: 组件间耦合
- 之前: PositionManager/EmotionCycle/SignalManager等直接调用scanner方法
- 现在: 组件通过事件总线发布/订阅, 解耦依赖关系

设计原则:
1. 异步优先: 所有handler都是coroutine, 支持asyncio事件循环
2. 顺序保证: 同一事件的handler按注册顺序执行
3. 异常隔离: 单个handler失败不影响其他handler和事件发布者
4. 轻量级: 不引入外部依赖, 纯Python实现
5. 可观测: 事件发布/处理日志, handler错误告警

用法:
    bus = ScannerEventBus()
    
    # 订阅事件
    async def on_position_changed(data):
        logger.info(f"持仓变更: {data}")
    bus.on("position_changed", on_position_changed)
    
    # 发布事件
    await bus.emit("position_changed", {"ts_code": "600036.SH", "action": "buy"})
    
    # 取消订阅
    bus.off("position_changed", on_position_changed)

事件类型:
    position_changed  — 持仓变更(买入/卖出/调仓)
    signal_generated  — 新信号产生
    emotion_changed   — 情绪phase变化
    risk_triggered    — 风控触发(止损/熔断)
    quote_degraded    — 行情降级
    param_updated     — 策略参数更新
    scan_completed    — 扫描完成
    circuit_breaker   — 熔断器状态变化
"""

import asyncio
import logging
import time
from collections import defaultdict
from typing import Dict, List, Any, Callable, Awaitable, Optional

logger = logging.getLogger("scanner.event_bus")


class ScannerEventBus:
    """
    Scanner内部事件总线
    
    特性:
    - 异步handler: 所有handler在asyncio事件循环中执行
    - 异常隔离: handler失败不传播到发布者
    - 可观测: 发布/处理日志 + 错误告警
    - 统计: 每种事件发布/处理次数, handler平均耗时
    """
    
    def __init__(self, max_history: int = 100):
        """
        Args:
            max_history: 保留最近N条事件历史(用于调试/诊断)
        """
        self._handlers: Dict[str, List[Callable]] = defaultdict(list)
        self._history: List[Dict[str, Any]] = []
        self._max_history = max_history
        self._stats: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"emitted": 0, "handled": 0, "errors": 0}
        )
        self._enabled = True
    
    # ==================== 核心API ====================
    
    def on(self, event: str, handler: Callable) -> None:
        """注册事件handler
        
        Args:
            event: 事件名称
            handler: 异步函数 async def handler(data: Dict) -> None
        """
        if not asyncio.iscoroutinefunction(handler):
            logger.warning(f"[EVENT_BUS] handler {handler.__name__} 不是协程函数, 将被包装")
            # 包装同步函数为协程
            original = handler
            async def _sync_wrapper(data):
                original(data)
            _sync_wrapper.__name__ = original.__name__
            handler = _sync_wrapper
        
        if handler not in self._handlers[event]:
            self._handlers[event].append(handler)
            logger.debug(f"[EVENT_BUS] 订阅 {event}: {handler.__name__}")
        else:
            logger.debug(f"[EVENT_BUS] 重复订阅忽略 {event}: {handler.__name__}")
    
    def off(self, event: str, handler: Callable) -> bool:
        """取消事件handler
        
        Returns:
            True if handler was removed, False if not found
        """
        try:
            self._handlers[event].remove(handler)
            logger.debug(f"[EVENT_BUS] 取消订阅 {event}: {handler.__name__}")
            return True
        except ValueError:
            return False
    
    async def emit(self, event: str, data: Dict[str, Any] = None) -> int:
        """发布事件, 按注册顺序调用所有handler
        
        Args:
            event: 事件名称
            data: 事件数据
            
        Returns:
            成功处理的handler数量
        """
        if not self._enabled:
            return 0
        
        data = data or {}
        stats = self._stats[event]
        stats["emitted"] += 1
        
        # 记录事件历史
        self._record_history(event, data)
        
        handlers = self._handlers.get(event, [])
        if not handlers:
            logger.debug(f"[EVENT_BUS] {event}: 无订阅者")
            return 0
        
        success_count = 0
        for handler in handlers:
            try:
                start = time.monotonic()
                await handler(data)
                elapsed = (time.monotonic() - start) * 1000
                stats["handled"] += 1
                success_count += 1
                
                if elapsed > 100:  # 超过100ms告警
                    logger.warning(
                        f"[EVENT_BUS] {event} handler {handler.__name__} "
                        f"耗时 {elapsed:.1f}ms"
                    )
                else:
                    logger.debug(
                        f"[EVENT_BUS] {event} → {handler.__name__} "
                        f"({elapsed:.1f}ms)"
                    )
            except Exception as e:
                stats["errors"] += 1
                logger.error(
                    f"[EVENT_BUS] {event} handler {handler.__name__} 异常: {e}",
                    exc_info=True
                )
        
        return success_count
    
    def once(self, event: str, handler: Callable) -> None:
        """注册一次性handler(触发一次后自动取消)
        
        Args:
            event: 事件名称
            handler: 异步函数
        """
        async def _once_wrapper(data):
            self.off(event, _once_wrapper)
            await handler(data)
        
        _once_wrapper.__name__ = f"once_{handler.__name__}"
        self.on(event, _once_wrapper)
    
    # ==================== 批量操作 ====================
    
    def on_many(self, events: List[str], handler: Callable) -> None:
        """订阅多个事件"""
        for event in events:
            self.on(event, handler)
    
    def off_many(self, events: List[str], handler: Callable) -> None:
        """取消多个事件的订阅"""
        for event in events:
            self.off(event, handler)
    
    # ==================== 查询API ====================
    
    def has_handlers(self, event: str) -> bool:
        """是否有订阅者"""
        return bool(self._handlers.get(event))
    
    def handler_count(self, event: str) -> int:
        """获取某事件的handler数量"""
        return len(self._handlers.get(event, []))
    
    def get_events(self) -> List[str]:
        """获取所有有订阅者的事件名"""
        return [k for k, v in self._handlers.items() if v]
    
    def get_stats(self) -> Dict[str, Dict[str, int]]:
        """获取事件统计"""
        return dict(self._stats)
    
    def get_history(self, event: str = None, limit: int = 20) -> List[Dict]:
        """获取事件历史
        
        Args:
            event: 过滤特定事件(None=全部)
            limit: 最大返回条数
        """
        if event:
            filtered = [h for h in self._history if h["event"] == event]
        else:
            filtered = self._history
        return filtered[-limit:]
    
    # ==================== 控制 ====================
    
    def enable(self):
        """启用事件总线"""
        self._enabled = True
        logger.info("[EVENT_BUS] 已启用")
    
    def disable(self):
        """禁用事件总线(emit不执行handler)"""
        self._enabled = False
        logger.info("[EVENT_BUS] 已禁用")
    
    def clear(self, event: str = None):
        """清除订阅
        
        Args:
            event: 清除特定事件(None=清除全部)
        """
        if event:
            self._handlers[event] = []
        else:
            self._handlers.clear()
        logger.debug(f"[EVENT_BUS] 清除订阅: {event or '全部'}")
    
    def reset_stats(self):
        """重置统计"""
        self._stats.clear()
    
    # ==================== 内部方法 ====================
    
    def _record_history(self, event: str, data: Dict):
        """记录事件历史"""
        record = {
            "event": event,
            "data_keys": list(data.keys()) if data else [],
            "timestamp": time.time(),
            "time_str": time.strftime("%H:%M:%S"),
        }
        self._history.append(record)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]


# ==================== 全局事件总线单例 ====================

_global_bus: Optional[ScannerEventBus] = None


def get_event_bus() -> ScannerEventBus:
    """获取全局事件总线实例(懒初始化)"""
    global _global_bus
    if _global_bus is None:
        _global_bus = ScannerEventBus()
    return _global_bus


def reset_event_bus():
    """重置全局事件总线(主要用于测试)"""
    global _global_bus
    _global_bus = None


# ==================== 标准事件类型常量 ====================

class ScannerEvents:
    """Scanner标准事件类型"""
    POSITION_CHANGED = "position_changed"    # 持仓变更
    SIGNAL_GENERATED = "signal_generated"    # 新信号产生
    EMOTION_CHANGED = "emotion_changed"      # 情绪phase变化
    RISK_TRIGGERED = "risk_triggered"        # 风控触发
    QUOTE_DEGRADED = "quote_degraded"        # 行情降级
    QUOTE_RECOVERED = "quote_recovered"      # 行情恢复
    PARAM_UPDATED = "param_updated"          # 策略参数更新
    SCAN_COMPLETED = "scan_completed"        # 扫描完成
    CIRCUIT_BREAKER = "circuit_breaker"      # 熔断器变化
    DAILY_SETTLED = "daily_settled"          # 盘后结算完成
    RISK_SELL_EXECUTED = "risk_sell_executed"  # 风控卖出执行
