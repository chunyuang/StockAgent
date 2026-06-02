"""
SignalDispatcher — 统一信号分发器

解决核心问题: 信号出口统一化
- 之前: Listener走飞书webhook, Scanner走Redis pub/sub + _push_signals, 两条路径互不感知
- 现在: 所有信号经SignalDispatcher统一分发, 支持多通道(飞书/交易网关/GUI/Redis)

设计原则:
1. 单一出口: 无论信号来源(Scanner/DailyScheduler/手动), 都经此分发
2. 通道解耦: 新增通道只需注册handler, 不修改信号生产逻辑
3. 可靠投递: handler异常不影响其他通道
4. 信号去重: 同一ts_code+strategy在信号有效期内不重复推送

用法:
    dispatcher = SignalDispatcher(scanner)
    dispatcher.register_channel("feishu", feishu_handler)
    dispatcher.register_channel("trade", trade_handler)
    dispatcher.register_channel("redis", redis_handler)
    await dispatcher.dispatch(signal)
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable, Awaitable
from dataclasses import dataclass, field
from enum import Enum


logger = logging.getLogger("signal.dispatcher")


class SignalPriority(Enum):
    """信号优先级"""
    CRITICAL = "critical"  # 熔断/强平/系统异常 → 全通道+弹窗+声音
    HIGH = "high"          # 买入/卖出信号 → 全通道
    NORMAL = "normal"      # 异动观察 → Redis+列表更新
    LOW = "low"            # 扫描统计 → 仅Redis


@dataclass
class DispatchSignal:
    """统一信号格式"""
    signal_id: str                          # 唯一ID (ts_code|strategy|timestamp)
    ts_code: str                            # 股票代码
    stock_name: str                         # 股票名称
    strategy: str                           # 策略ID
    strategy_name: str                      # 策略中文名
    signal_type: str                        # buy/sell/alert/risk/system
    priority: SignalPriority = SignalPriority.NORMAL
    price: float = 0.0
    pct_chg: float = 0.0
    reason: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0                 # time.time()
    expires_at: float = 0.0                 # 过期时间 (0=不过期)
    source: str = "scanner"                 # 来源: scanner/scheduler/manual

    @property
    def is_expired(self) -> bool:
        if self.expires_at <= 0:
            return False
        return time.time() > self.expires_at


# 通道handler类型: 接收信号, 返回是否成功
SignalHandler = Callable[[DispatchSignal], Awaitable[bool]]


class SignalDispatcher:
    """
    统一信号分发器
    
    职责:
    1. 接收所有交易信号(买入/卖出/风控/系统)
    2. 信号去重(同一ts_code+strategy在有效期内不重复)
    3. 按优先级分发到注册的通道
    4. 记录分发日志(可追溯)
    """

    # 信号去重窗口(秒): 同一ts_code+strategy在此窗口内不重复推送
    DEDUP_WINDOW = 300  # 5分钟

    def __init__(self, scanner=None):
        self._scanner = scanner
        self._channels: Dict[str, SignalHandler] = {}
        self._dispatch_log: List[Dict] = []
        self._dedup_cache: Dict[str, float] = {}  # key → last_dispatch_time
        self._stats = {
            "total_received": 0,
            "total_dispatched": 0,
            "total_deduped": 0,
            "total_failed": 0,
            "by_channel": {},
            "by_priority": {},
        }

    def register_channel(self, name: str, handler: SignalHandler) -> None:
        """注册信号通道"""
        self._channels[name] = handler
        self._stats["by_channel"][name] = {"success": 0, "failed": 0}
        logger.info(f"[DISPATCHER] 注册通道: {name}")

    def unregister_channel(self, name: str) -> None:
        """移除信号通道"""
        self._channels.pop(name, None)
        self._stats["by_channel"].pop(name, None)
        logger.info(f"[DISPATCHER] 移除通道: {name}")

    async def dispatch(self, signal: DispatchSignal) -> Dict[str, bool]:
        """分发信号到所有注册通道(编排方法)"""
        self._stats["total_received"] += 1
        priority_key = signal.priority.value
        self._stats["by_priority"][priority_key] = self._stats["by_priority"].get(priority_key, 0) + 1

        if self._should_dedup(signal):
            return {}
        if signal.is_expired:
            logger.debug(f"[DISPATCHER] 过期信号丢弃: {signal.ts_code}")
            return {}

        results = await self._dispatch_to_channels(signal)
        self._record_dispatch(signal, results)
        return results

    def _should_dedup(self, signal: DispatchSignal) -> bool:
        """信号去重检查(CRITICAL级不去重)"""
        if signal.priority == SignalPriority.CRITICAL:
            return False
        dedup_key = f"{signal.ts_code}|{signal.strategy}|{signal.signal_type}"
        last_time = self._dedup_cache.get(dedup_key, 0)
        if time.time() - last_time < self.DEDUP_WINDOW:
            self._stats["total_deduped"] += 1
            logger.debug(f"[DISPATCHER] 去重: {signal.ts_code} {signal.strategy} "
                         f"(距上次{time.time()-last_time:.0f}s<{self.DEDUP_WINDOW}s)")
            return True
        self._dedup_cache[dedup_key] = time.time()
        return False

    async def _dispatch_to_channels(self, signal: DispatchSignal) -> Dict[str, bool]:
        """分发到所有通道"""
        results = {}
        for name, handler in self._channels.items():
            try:
                ok = await handler(signal)
                results[name] = ok
                key = "success" if ok else "failed"
                self._stats["by_channel"][name][key] += 1
            except Exception as e:
                logger.warning(f"[DISPATCHER] 通道{name}异常: {e}")
                results[name] = False
                self._stats["by_channel"][name]["failed"] += 1
                self._stats["total_failed"] += 1
        return results

    def _record_dispatch(self, signal: DispatchSignal, results: Dict[str, bool]) -> None:
        """记录分发日志"""
        self._dispatch_log.append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "signal_id": signal.signal_id, "ts_code": signal.ts_code,
            "strategy": signal.strategy, "type": signal.signal_type,
            "priority": signal.priority.value, "channels": results,
            "source": signal.source,
        })
        if len(self._dispatch_log) > 500:
            self._dispatch_log = self._dispatch_log[-500:]
        self._stats["total_dispatched"] += 1

    async def dispatch_batch(self, signals: List[DispatchSignal]) -> List[Dict[str, bool]]:
        """批量分发"""
        return [await self.dispatch(s) for s in signals]

    def get_stats(self) -> Dict:
        """获取分发统计"""
        return {
            **self._stats,
            "channels": list(self._channels.keys()),
            "dedup_cache_size": len(self._dedup_cache),
            "recent_dispatches": self._dispatch_log[-10:],
        }

    def clear_dedup_cache(self) -> None:
        """清除去重缓存(新交易日开始时调用)"""
        self._dedup_cache.clear()
        logger.info("[DISPATCHER] 去重缓存已清除")

    # ==================== 便捷方法: 从ScanSignal转换 ====================

    @staticmethod
    def from_scan_signal(scan_signal, source: str = "scanner") -> DispatchSignal:
        """从MarketScanner的ScanSignal转换为DispatchSignal"""
        from nodes.market_monitor.scanner import ScanSignal

        sig = scan_signal  # type: ScanSignal
        signal_type = "buy" if sig.signal_type == "buy" else "alert"
        priority = SignalPriority.HIGH if signal_type == "buy" else SignalPriority.NORMAL

        return DispatchSignal(
            signal_id=f"{sig.ts_code}|{sig.strategy}|{int(time.time())}",
            ts_code=sig.ts_code,
            stock_name=sig.stock_name,
            strategy=sig.strategy,
            strategy_name=sig.strategy_name,
            signal_type=signal_type,
            priority=priority,
            price=sig.price,
            pct_chg=sig.pct_chg,
            reason=sig.reason,
            extra={
                "volume_ratio": sig.volume_ratio,
                "turnover_rate": sig.turnover_rate,
                "is_limit_up": sig.is_limit_up,
                "limit_up_count": sig.limit_up_count,
                "confidence": sig.confidence,
                "factors": sig.factors,
                "decision_detail": sig.decision_detail,
                "layer_trace": sig.layer_trace,
            },
            created_at=time.time(),
            expires_at=time.time() + 300,  # 5分钟有效
            source=source,
        )

    @staticmethod
    def from_risk_event(event_type: str, reason: str, extra: Dict = None) -> DispatchSignal:
        """创建风控事件信号"""
        return DispatchSignal(
            signal_id=f"risk|{event_type}|{int(time.time())}",
            ts_code="SYSTEM",
            stock_name="系统风控",
            strategy="risk_control",
            strategy_name="风控系统",
            signal_type="risk",
            priority=SignalPriority.CRITICAL,
            reason=reason,
            extra=extra or {},
            created_at=time.time(),
            source="risk_watchdog",
        )


# ==================== 内置通道handler ====================

async def redis_channel_handler(signal: DispatchSignal) -> bool:
    """Redis Stream通道(不可丢, →WebSocket实时推送到GUI)
    
    v2.1: Pub/Sub → Stream升级
    - scanner:signal → Redis Stream (maxlen=1000, 不可丢)
    - scanner:status/health → Pub/Sub (不变, 允许丢)
    """
    try:
        from core.managers import redis_manager
        if not redis_manager._client:
            return False

        import json
        channel = f"scanner:signal"
        data = {
            "signal_id": signal.signal_id,
            "ts_code": signal.ts_code,
            "stock_name": signal.stock_name,
            "strategy": signal.strategy_name,
            "type": signal.signal_type,
            "priority": signal.priority.value,
            "price": str(signal.price),  # Stream要求string值
            "pct_chg": str(signal.pct_chg),
            "reason": signal.reason,
            "timestamp": datetime.now().strftime("%H:%M:%S"),
        }
        # Redis Stream: XADD (不可丢, maxlen防内存溢出)
        await redis_manager._client.xadd(channel, data, maxlen=1000, approximate=True)
        return True
    except Exception as e:
        logger.debug(f"[DISPATCHER] Redis Stream通道失败: {e}")
        return False


async def feishu_channel_handler(signal: DispatchSignal) -> bool:
    """飞书推送通道"""
    try:
        from core.managers.notification_manager import notification_manager

        # 只推送CRITICAL和HIGH优先级
        if signal.priority not in (SignalPriority.CRITICAL, SignalPriority.HIGH):
            return True

        if signal.priority == SignalPriority.CRITICAL:
            emoji = "🚨"
        elif signal.signal_type == "buy":
            emoji = "🎯"
        elif signal.signal_type == "sell":
            emoji = "💰"
        else:
            emoji = "📊"

        pct = f"+{signal.pct_chg:.1f}%" if signal.pct_chg > 0 else f"{signal.pct_chg:.1f}%"
        text = f"{emoji} **{signal.strategy_name}** | {signal.ts_code} {signal.stock_name} | {pct} | {signal.reason}"

        # notification_manager.send_alert需要StrategyAlert对象
        # 简化: 直接用webhook发送文本
        if hasattr(notification_manager, '_webhook_url') and notification_manager._webhook_url:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                payload = {
                    "msg_type": "interactive",
                    "card": {
                        "header": {"title": {"tag": "plain_text", "content": f"{emoji} {signal.signal_type.upper()}"}},
                        "elements": [{"tag": "markdown", "content": text}],
                    },
                }
                async with session.post(notification_manager._webhook_url, json=payload) as resp:
                    return resp.status == 200
        return False
    except Exception as e:
        logger.debug(f"[DISPATCHER] 飞书通道失败: {e}")
        return False


async def log_channel_handler(signal: DispatchSignal) -> bool:
    """日志通道(始终成功, 用于审计)"""
    priority_emoji = {
        SignalPriority.CRITICAL: "🚨",
        SignalPriority.HIGH: "⚡",
        SignalPriority.NORMAL: "📊",
        SignalPriority.LOW: "📝",
    }
    emoji = priority_emoji.get(signal.priority, "❓")
    logger.info(
        f"[SIGNAL] {emoji} {signal.signal_type}|{signal.priority.value}|"
        f"{signal.ts_code} {signal.stock_name}|{signal.strategy_name}|"
        f"{signal.price:.2f}|{signal.reason}"
    )
    return True
