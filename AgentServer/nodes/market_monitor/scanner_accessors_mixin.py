"""ScannerAccessorsMixin — 只读属性访问器 + 线程安全状态读取

从scanner.py提取的属性访问方法群，减少scanner.py行数。
这些方法都是只读或线程安全读取，不修改任何状态。
"""

from typing import Dict, Optional
import threading


class ScannerAccessorsMixin:
    """只读属性访问器 + 线程安全状态读取【v2.9.99从scanner.py提取】"""

    def get_current_sentiment(self) -> Dict:
        """当前情绪得分(只读)"""
        return self._current_sentiment or {}

    def get_current_position_ratio(self) -> Optional[float]:
        """当前仓位比例(只读)"""
        return self._current_position_ratio

    def get_scan_error_count(self) -> int:
        """扫描循环连续异常次数(只读)"""
        return self._scan_loop_error_count

    def get_event_bus(self):
        """事件总线实例(只读,可能为None)"""
        return self._event_bus

    def get_risk_thread(self) -> Optional[threading.Thread]:
        """风控线程对象(只读,可能为None)"""
        return self._risk_thread

    def get_circuit_breaker(self) -> Dict:
        """熔断器状态(只读)"""
        return self._circuit_breaker or {}

    def get_risk_thread_restarts(self) -> int:
        """风控线程重启次数(只读)"""
        return self._risk_thread_restarts

    def is_risk_running(self) -> bool:
        """风控线程是否在运行(只读)"""
        return self._risk_running

    def get_trade_date(self) -> str:
        """当前交易日期(只读,可能为空串)"""
        return self._trade_date

    def _safe_read_state(self, attr_name: str) -> Dict:
        """线程安全深拷贝共享状态(统一辅助)【v2.9.31提取】

        替代4个_safe_copy_*方法, 统一state_lock保护读取模式:
        - _state_lock未初始化 → 直接浅拷贝(启动前无并发风险)
        - _state_lock已初始化 → 加锁后浅拷贝再释放

        Args:
            attr_name: 共享状态属性名(trailing_stops/position_risk_levels/pending_sells等)
        Returns:
            dict浅拷贝(调用方可安全修改不影响原始状态)
        """
        source = getattr(self, attr_name, {})
        if self._state_lock is None:
            return dict(source)
        with self._state_lock:
            return dict(source)

    def _get_activated_trailing_stops_safe(self) -> Dict:
        """线程安全读取已激活的追踪止损(深拷贝+过滤)"""
        all_stops = self._safe_read_state("_trailing_stops")
        return {k: v for k, v in all_stops.items() if v.get("activated")}

    def _safe_copy_position_risk_levels(self) -> Dict:
        """线程安全深拷贝position_risk_levels"""
        return self._safe_read_state("_position_risk_levels")

    def _safe_copy_trailing_stops(self) -> Dict:
        """线程安全深拷贝trailing_stops"""
        return self._safe_read_state("_trailing_stops")

    def _safe_copy_pending_sells(self) -> Dict:
        """线程安全深拷贝pending_sells"""
        return self._safe_read_state("_pending_sells")
