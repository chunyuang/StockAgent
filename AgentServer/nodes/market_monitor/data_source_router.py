"""
数据源与券商路由器

统一管理数据源(必盈/掘金)和券商(仿真/实盘)，
支持运行时切换、降级、状态监控。

数据源:
  - biying:   必盈(免费/付费, 涨停池+五档+行情, 无IP限制) ← 主力
  - gm:       掘金(需终端, 数据+交易, 当前不可用)

券商:
  - simulated: SimulatedBroker(内存撮合, 开发/测试)
  - gm_paper:  掘金仿真(需要gm3_node终端)
  - qmt:       QMT实盘(需要券商开户)
"""

import asyncio
import logging
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class DataSourceType(str, Enum):
    """数据源类型"""
    BIYING = "biying"
    GM = "gm"


class BrokerType(str, Enum):
    """券商类型"""
    SIMULATED = "simulated"
    GM_PAPER = "gm_paper"    # 掘金仿真
    QMT = "qmt"              # QMT实盘


@dataclass
class DataSourceStatus:
    """数据源状态"""
    name: str
    available: bool = False
    initialized: bool = False
    priority: int = 99
    daily_calls: int = 0
    daily_limit: int = 0
    daily_remaining: int = 0
    last_error: str = ""
    last_success: str = ""
    capabilities: Dict[str, bool] = field(default_factory=dict)


@dataclass
class BrokerStatus:
    """券商状态"""
    name: str
    available: bool = False
    connected: bool = False
    account_id: str = ""
    total_assets: float = 0
    available_cash: float = 0
    market_value: float = 0
    positions_count: int = 0
    trade_mode: str = "simulated"  # simulated/paper/live


class DataSourceRouter:
    """数据源路由器

    根据请求类型和当前状态, 自动选择最优数据源。
    支持降级: 主数据源不可用时自动切到备用。

    用法:
        router = DataSourceRouter()
        router.register("liangmai", liangmai_adapter, priority=5)
        router.register("biying", biying_adapter, priority=10)
        await router.initialize_all()

        # 获取涨停池(自动选最优数据源)
        pool = await router.get_limit_up_pool("2026-05-12")

        # 指定数据源
        pool = await router.get_limit_up_pool("2026-05-12", source="biying")
    """

    def __init__(self):
        self._sources: Dict[str, Any] = {}
        self._priorities: Dict[str, int] = {}
        self._statuses: Dict[str, DataSourceStatus] = {}
        self._active_source: Optional[str] = None

    def register(self, name: str, adapter: Any, priority: int = 99) -> None:
        """注册数据源"""
        self._sources[name] = adapter
        self._priorities[name] = priority
        self._statuses[name] = DataSourceStatus(
            name=name,
            priority=priority,
            available=False,
            initialized=False,
        )

    async def initialize_all(self) -> Dict[str, bool]:
        """初始化所有数据源, 返回 {name: success}"""
        results = {}
        for name, adapter in self._sources.items():
            try:
                ok = await adapter.initialize()
                self._statuses[name].initialized = ok
                self._statuses[name].available = ok
                results[name] = ok
                if ok:
                    logger.info(f"[ROUTER] 数据源 {name} 初始化成功")
                    if self._active_source is None:
                        self._active_source = name
                else:
                    logger.warning(f"[ROUTER] 数据源 {name} 初始化失败")
            except Exception as e:
                results[name] = False
                self._statuses[name].last_error = str(e)
                logger.error(f"[ROUTER] 数据源 {name} 初始化异常: {e}")

        # 选优先级最高的可用源
        if self._active_source is None or not self._statuses.get(self._active_source, {}).available:
            self._select_best_source()

        return results

    def _select_best_source(self) -> None:
        """选择最优数据源(优先级数字越小越优先)"""
        best = None
        best_priority = 999
        for name, status in self._statuses.items():
            if status.available and self._priorities.get(name, 99) < best_priority:
                best = name
                best_priority = self._priorities[name]

        if best:
            old = self._active_source
            self._active_source = best
            logger.info(f"[ROUTER] 切换到数据源: {best}")
            # 【v2.9.107】持久化切换事件
            if old != best:
                try:
                    import asyncio as _asyncio
                    from .market_event_log import log_data_source_switch
                    _asyncio.get_event_loop().create_task(log_data_source_switch(
                        from_source=old or '', to_source=best, reason='auto_select_best_available',
                    ))
                except Exception:
                    pass
        else:
            logger.error("[ROUTER] 无可用数据源!")

    def set_active_source(self, name: str) -> bool:
        """手动切换数据源"""
        if name in self._sources and self._statuses[name].available:
            old = self._active_source
            self._active_source = name
            logger.info(f"[ROUTER] 手动切换到数据源: {name}")
            # 【v2.9.107】持久化手动切换事件
            if old != name:
                try:
                    import asyncio as _asyncio
                    from .market_event_log import log_data_source_switch
                    _asyncio.get_event_loop().create_task(log_data_source_switch(
                        from_source=old or '', to_source=name, reason='manual_switch',
                    ))
                except Exception:
                    pass
            return True
        else:
            logger.warning(f"[ROUTER] 数据源 {name} 不可用")
            return False

    def get_active_source(self) -> str:
        """获取当前活跃数据源"""
        return self._active_source or "none"

    # ==================== 数据接口(自动路由) ====================

    async def get_limit_up_pool(self, trade_date: str = None, source: str = None) -> List:
        """获取涨停股池"""
        adapter = self._get_adapter(source)
        if adapter is None:
            return []

        try:
            if hasattr(adapter, 'get_limit_up_pool'):
                result = await adapter.get_limit_up_pool(trade_date)
                self._mark_success(adapter)
                return result
        except Exception as e:
            self._mark_error(adapter, str(e))

        # 降级: 尝试其他数据源
        return await self._fallback("get_limit_up_pool", trade_date=trade_date, exclude=source)

    async def get_limit_down_pool(self, trade_date: str = None, source: str = None) -> List:
        """获取跌停股池"""
        adapter = self._get_adapter(source)
        if adapter is None:
            return []

        try:
            if hasattr(adapter, 'get_limit_down_pool'):
                result = await adapter.get_limit_down_pool(trade_date)
                self._mark_success(adapter)
                return result
        except Exception as e:
            self._mark_error(adapter, str(e))

        return await self._fallback("get_limit_down_pool", trade_date=trade_date, exclude=source)

    async def get_broken_board_pool(self, trade_date: str = None, source: str = None) -> List:
        """获取炸板股池"""
        adapter = self._get_adapter(source)
        if adapter is None:
            return []

        try:
            if hasattr(adapter, 'get_broken_board_pool'):
                result = await adapter.get_broken_board_pool(trade_date)
                self._mark_success(adapter)
                return result
        except Exception as e:
            self._mark_error(adapter, str(e))

        return await self._fallback("get_broken_board_pool", trade_date=trade_date, exclude=source)

    async def get_realtime_quote(self, ts_code: str, source: str = None) -> Optional[Dict]:
        """获取单只股票实时行情"""
        adapter = self._get_adapter(source)
        if adapter is None:
            return None

        try:
            if hasattr(adapter, 'get_realtime_quote'):
                result = await adapter.get_realtime_quote(ts_code)
                self._mark_success(adapter)
                return result
        except Exception as e:
            self._mark_error(adapter, str(e))

        result = await self._fallback("get_realtime_quote", ts_code=ts_code, exclude=source)
        return result[0] if result else None

    async def get_order_book(self, ts_code: str, source: str = None) -> Optional[Dict]:
        """获取买卖五档"""
        adapter = self._get_adapter(source)
        if adapter is None:
            return None

        try:
            if hasattr(adapter, 'get_order_book'):
                result = await adapter.get_order_book(ts_code)
                self._mark_success(adapter)
                return result
        except Exception as e:
            self._mark_error(adapter, str(e))

        # 降级: 只有必盈有五档, 不降级
        return None

    # ==================== 内部方法 ====================

    def _get_adapter(self, source: str = None) -> Optional[Any]:
        """获取数据源适配器"""
        name = source or self._active_source
        if name and name in self._sources and self._statuses[name].available:
            return self._sources[name]
        # 降级: 用活跃源
        if self._active_source and self._statuses.get(self._active_source, DataSourceStatus(name="")).available:
            return self._sources.get(self._active_source)
        return None

    async def _fallback(self, method_name: str, exclude: str = None, **kwargs) -> Any:
        """降级: 尝试其他数据源"""
        for name, priority in sorted(self._priorities.items(), key=lambda x: x[1]):
            if name == exclude or not self._statuses[name].available:
                continue
            adapter = self._sources[name]
            method = getattr(adapter, method_name, None)
            if method:
                try:
                    result = await method(**kwargs)
                    self._mark_success(adapter)
                    return result
                except Exception as e:
                    self._mark_error(adapter, str(e))
        return [] if "pool" in method_name else None

    def _mark_success(self, adapter) -> None:
        name = getattr(adapter, 'name', 'unknown')
        if name in self._statuses:
            self._statuses[name].last_success = datetime.now().strftime("%H:%M:%S")

    def _mark_error(self, adapter, error: str) -> None:
        name = getattr(adapter, 'name', 'unknown')
        if name in self._statuses:
            self._statuses[name].last_error = error[:100]

    # ==================== 状态 ====================

    def get_all_statuses(self) -> Dict[str, DataSourceStatus]:
        """获取所有数据源状态"""
        # 更新状态
        for name, adapter in self._sources.items():
            if hasattr(adapter, 'get_status'):
                status = adapter.get_status()
                self._statuses[name].daily_calls = status.get("daily_calls", 0)
                self._statuses[name].daily_limit = status.get("daily_limit", 0)
                self._statuses[name].daily_remaining = status.get("daily_remaining", 0)
        return self._statuses

    async def close_all(self) -> None:
        """关闭所有数据源"""
        for name, adapter in self._sources.items():
            try:
                if hasattr(adapter, 'close'):
                    await adapter.close()
            except Exception as e:
                logger.warning(f"[ROUTER] 关闭 {name} 失败: {e}")
