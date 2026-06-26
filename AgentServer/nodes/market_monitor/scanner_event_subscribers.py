"""
ScannerEventSubscribers — EventBus事件订阅处理器

将EventBus的emit点与实际副作用连接起来:
- 审计日志: 风控卖出/熔断/参数变更写入MongoDB audit_log
- 运行时快照: 持仓变更触发自动保存
- Redis推送: 关键事件转发到Redis供Web节点WebSocket广播
- 健康度更新: 扫描完成/行情降级更新health指标

所有handler通过ScannerEventBus.on()注册, 不侵入scanner核心逻辑。
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, Any, Optional, Callable

logger = logging.getLogger("scanner.event_subscribers")


# ==================== 订阅器工厂 ====================

def register_subscribers(scanner) -> None:
    """注册所有EventBus订阅器
    
    Args:
        scanner: MarketScanner实例(通过弱引用或直接引用访问内部组件)
    
    设计原则:
    - 每个handler是独立的async函数, 异常不互相影响(EventBus保证)
    - handler内不raise, 只记录错误(EventBus保证但防御性编程)
    - handler内不阻塞, 耗时操作用ensure_future异步化
    """
    bus = scanner.event_bus
    
    # 1. 风控卖出 → 审计日志 + Redis状态推送
    bus.on("risk_sell_executed", _make_risk_sell_handler(scanner))
    
    # 2. 持仓变更 → 自动快照 + Redis状态推送
    bus.on("position_changed", _make_position_changed_handler(scanner))
    
    # 3. 熔断器 → 审计日志 + Redis紧急推送
    bus.on("circuit_breaker", _make_circuit_breaker_handler(scanner))
    
    # 4. 扫描完成 → 健康指标更新
    bus.on("scan_completed", _make_scan_completed_handler(scanner))
    
    # 5. 行情降级/恢复/告警 → 健康指标更新 + Redis推送 + 飞书通知
    bus.on("quote_degraded", _make_quote_degraded_handler(scanner))
    bus.on("quote_recovered", _make_quote_recovered_handler(scanner))
    bus.on("quote_warning", _make_quote_warning_handler(scanner))
    bus.on("quote_warning", _make_quote_warning_handler(scanner))
    
    # 6. 参数更新 → 审计日志(已有StrategyParamCenter._write_param_audit_log,
    #    这里补充EventBus侧的冗余记录,防止直接调用scanner方法时遗漏)
    bus.on("param_updated", _make_param_updated_handler(scanner))
    
    # 7. 情绪变化 → Redis状态推送
    bus.on("emotion_changed", _make_emotion_changed_handler(scanner))
    
    # 8. 盘后结算 → 审计日志 + 绩效快照 + 飞书日报
    bus.on("daily_settled", _make_daily_settled_handler(scanner))
    
    # 9. 信号生成 → Redis推送(前端实时信号面板)
    bus.on("signal_generated", _make_signal_generated_handler(scanner))
    
    # 10. 【v2.9.15】扫描器异常 → Redis推送(前端错误提示)
    bus.on("scanner_error", _make_scanner_error_handler(scanner))
    
    logger.info(
        f"[SUBSCRIBERS] 已注册10组事件订阅器, "
        f"总计{sum(bus.handler_count(e) for e in bus.get_events())}个handler"
    )


# ==================== 审计日志写入器 ====================

async def _write_audit_log(scanner, event_type: str, data: Dict[str, Any]) -> None:
    """写入审计日志到MongoDB audit_log集合
    
    设计文档Phase3.4: TTL 90天自动清理, 防止无限增长。
    
    字段规范(v2.9.80统一):
    - timestamp: datetime对象(MongoDB TTL索引要求Date类型)
    - time_str: 人类可读字符串
    - action: 事件类型(与signal_manager对齐)
    - reason: 事件描述(从data中提取)
    """
    try:
        from core.managers import mongo_manager
        if not mongo_manager._initialized:
            return
        
        # 【Phase3.4】确保TTL索引存在(90天自动清理, 幂等操作)
        try:
            await mongo_manager.db["audit_log"].create_index(
                "timestamp", name="ttl_90d",
                expireAfterSeconds=90 * 86400
            )
        except Exception as _e:
            pass  # 索引已存在或其他错误, 不影响写入
        
        now = datetime.now()
        # 提取reason: 优先用data中的reason/message, 否则用event_type
        reason = data.get("reason", "") or data.get("message", "") or event_type
        # 【v2.9.82】推断level: 关键事件自动标记, 其他默认info
        critical_events = {"circuit_breaker", "scanner_error", "risk_sell_executed"}
        level = "critical" if event_type in critical_events else "info"
        doc = {
            "timestamp": now,  # datetime对象, TTL索引需要Date类型
            "time_str": now.strftime("%Y-%m-%d %H:%M:%S"),
            "event_type": event_type,  # 保留event_type向后兼容
            "action": event_type,      # 统一action字段(与signal_manager对齐)
            "reason": reason,          # 统一reason字段(与signal_manager对齐)
            "level": level,             # 日志级别(critical/warning/info)
            "trade_date": scanner._trade_date,
            "account_id": scanner._account_id,
            "data": _safe_serialize(data),
        }
        # 保留data中的ts_code/strategy到顶层(方便前端查询)
        for key in ("ts_code", "stock_name", "strategy"):
            if key in data and data[key]:
                doc[key] = data[key]
        await mongo_manager.db["audit_log"].insert_one(doc)
    except Exception as e:
        # 审计日志写入失败不应影响主流程
        logger.debug(f"[AUDIT] 写入失败(非关键): {e}")


def _safe_serialize(data: Any, max_depth: int = 3) -> Any:
    """递归序列化数据, 处理不可JSON化的类型"""
    if max_depth <= 0:
        return str(data)
    if isinstance(data, dict):
        return {str(k): _safe_serialize(v, max_depth - 1) for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        return [_safe_serialize(i, max_depth - 1) for i in data]
    if isinstance(data, (int, float, str, bool, type(None))):
        return data
    return str(data)


# ==================== Redis状态推送 ====================

async def _push_to_redis(scanner, channel: str, data: Dict[str, Any], use_stream: bool = False, maxlen: int = 1000) -> None:
    """推送事件到Redis
    
    Args:
        scanner: MarketScanner实例
        channel: Redis频道名
        data: 推送数据
        use_stream: True时用Redis Stream(xadd,不可丢), False时用Pub/Sub(允许丢)
        maxlen: Stream最大长度(仅use_stream=True时生效)
    
    设计文档Phase2.1:
    - scanner:signal   → Redis Stream(maxlen=1000, 不可丢)
    - scanner:position → Redis Stream(maxlen=5000, 不可丢)
    - scanner:status   → Pub/Sub(允许丢)
    - scanner:health   → Pub/Sub(允许丢)
    """
    try:
        from core.managers.redis_manager import redis_manager
        if not redis_manager.is_initialized:
            return
        
        import json
        payload = {
            **_safe_serialize(data),
            "timestamp": time.time(),
            "account_id": scanner._account_id,
        }
        
        client = redis_manager.client
        if use_stream:
            # Redis Stream: 消息持久化, 消费者可用XREAD消费, 不丢失
            await client.xadd(
                channel, payload, maxlen=maxlen, approximate=True
            )
        else:
            # Pub/Sub: 实时广播, 不持久化, 离线消费者丢失
            await client.publish(channel, json.dumps(payload, default=str))
    except Exception as e:
        logger.debug(f"[REDIS_PUSH] 推送失败(非关键): {e}")


# ==================== Handler工厂 ====================

def _make_risk_sell_handler(scanner) -> Callable:
    """风控卖出事件handler"""
    async def on_risk_sell(data: Dict[str, Any]) -> None:
        """风控卖出事件: 写审计日志+推送Redis状态"""
        await _write_audit_log(scanner, "risk_sell_executed", data)
        # Redis状态推送
        await _push_to_redis(scanner, "scanner:status", {
            "event": "risk_sell",
            "ts_code": data.get("ts_code", ""),
            "reason": data.get("reason", ""),
            "price": data.get("price", 0),
        })
        logger.info(
            f"[AUDIT] 风控卖出: {data.get('ts_code')} "
            f"原因={data.get('reason')} 价格={data.get('price')}"
        )
    on_risk_sell.__name__ = "on_risk_sell"
    return on_risk_sell


def _make_position_changed_handler(scanner) -> Callable:
    """持仓变更事件handler"""
    async def on_position_changed(data: Dict[str, Any]) -> None:
        """持仓变更事件: 触发快照保存+推送Redis状态"""
        # 触发运行时快照自动保存(节流由save_runtime_snapshot内部控制)
        try:
            rp = scanner._runtime_persistence
            if rp:
                await rp.save_runtime_snapshot(force=True)
        except Exception as e:
            logger.debug(f"[SNAPSHOT] 持仓变更后快照保存失败: {e}")
        
        # Redis持仓推送(Phase2.1: Redis Stream, 不可丢)
        await _push_to_redis(scanner, "scanner:position", {
            "action": data.get("action", ""),
            "ts_code": data.get("ts_code", ""),
            "strategy": data.get("strategy", ""),
        }, use_stream=True, maxlen=5000)
    on_position_changed.__name__ = "on_position_changed"
    return on_position_changed


def _make_circuit_breaker_handler(scanner) -> Callable:
    """熔断器事件handler"""
    async def on_circuit_breaker(data: Dict[str, Any]) -> None:
        """熔断器事件: 写审计日志+紧急Redis推送"""
        # 审计日志(熔断是关键事件,必须记录)
        await _write_audit_log(scanner, "circuit_breaker", data)
        # Redis紧急推送
        await _push_to_redis(scanner, "scanner:status", {
            "event": "circuit_breaker",
            "trading_paused": data.get("trading_paused", False),
            "consecutive_losses": data.get("consecutive_losses", 0),
        })
        logger.warning(
            f"[AUDIT] 熔断器: 交易暂停={data.get('trading_paused')} "
            f"连续亏损={data.get('consecutive_losses')}"
        )
    on_circuit_breaker.__name__ = "on_circuit_breaker"
    return on_circuit_breaker


def _make_scan_completed_handler(scanner) -> Callable:
    """扫描完成事件handler"""
    async def on_scan_completed(data: Dict[str, Any]) -> None:
        """扫描完成事件: 更新健康指标时间戳"""
        # 更新健康指标时间戳
        scanner._last_scan_ts = time.time()
        # Redis状态推送(轻量,不含信号详情)
        await _push_to_redis(scanner, "scanner:status", {
            "event": "scan_completed",
            "signal_count": data.get("signal_count", 0),
            "scan_duration_ms": data.get("scan_duration_ms", 0),
        })
    on_scan_completed.__name__ = "on_scan_completed"
    return on_scan_completed


def _make_quote_degraded_handler(scanner) -> Callable:
    """行情降级事件handler"""
    async def on_quote_degraded(data: Dict[str, Any]) -> None:
        """行情降级事件: 推送Redis降级警告 + 飞书通知"""
        level = data.get('level', 1)
        source = data.get('source', '')
        error = data.get('error', '')
        # Redis推送(前端应显示降级警告)
        await _push_to_redis(scanner, "scanner:status", {
            "event": "quote_degraded",
            "level": level,
            "source": source,
            "message": data.get("message", ""),
        })
        logger.warning(f"[QUOTE] 行情降级: level={level} source={source} error={error}")
        # 飞书通知
        try:
            from core.managers.push_service import PushService
            push = PushService()
            level_desc = ["正常", "东财降级(用缓存)", "日线缓存"][min(level, 2)]
            await push.push_risk_alert(
                "行情数据降级",
                f"**降级等级**: L{level} ({level_desc})\n**数据源**: {source}\n**错误**: {error}\n**影响**: 策略筛选可能产出0候选，实盘无法产生交易信号",
                level="danger" if level >= 2 else "warning"
            )
        except Exception as e:
            logger.debug(f"[QUOTE] 飞书通知失败: {e}")
    on_quote_degraded.__name__ = "on_quote_degraded"
    return on_quote_degraded


def _make_quote_recovered_handler(scanner) -> Callable:
    """行情恢复事件handler"""
    async def on_quote_recovered(data: Dict[str, Any]) -> None:
        """行情恢复事件: 推送Redis恢复通知"""
        # Redis推送
        await _push_to_redis(scanner, "scanner:status", {
            "event": "quote_recovered",
            "degrade_duration_s": data.get("degrade_duration_s", 0),
        })
        logger.info(
            f"[QUOTE] 行情恢复: 降级持续{data.get('degrade_duration_s', 0):.0f}秒"
        )
    on_quote_recovered.__name__ = "on_quote_recovered"
    return on_quote_recovered


def _make_quote_warning_handler(scanner) -> Callable:
    """【v2.9.105】行情告警事件handler — 行情陈旧/源切换等警告"""
    async def on_quote_warning(data: Dict[str, Any]) -> None:
        """行情告警事件: 推送Redis + 飞书通知"""
        message = data.get("message", "行情异常")
        source = data.get("source", "")
        # Redis推送(前端显示告警)
        await _push_to_redis(scanner, "scanner:status", {
            "event": "quote_warning",
            "message": message,
            "source": source,
            "level": data.get("level", "warning"),
        })
        logger.warning(f"[QUOTE] 行情告警: {message} (source={source})")
        # 飞书通知(告警级别的行情警告)
        try:
            from core.managers.push_service import PushService
            push = PushService()
            extra_info = ""
            if "staleness_s" in data:
                extra_info = f"\n**陈旧度**: {data['staleness_s']:.0f}秒"
            elif "stocks" in data:
                extra_info = f"\n**股票数**: {data['stocks']}只"
            await push.push_risk_alert(
                "行情数据告警",
                f"**告警内容**: {message}\n**当前数据源**: {source}{extra_info}\n**影响**: 策略筛选可能受影响，实盘可能无法产生交易信号",
                level="warning"
            )
        except Exception as e:
            logger.debug(f"[QUOTE] 飞书通知失败: {e}")
    on_quote_warning.__name__ = "on_quote_warning"
    return on_quote_warning


def _make_param_updated_handler(scanner) -> Callable:
    """参数更新事件handler"""
    async def on_param_updated(data: Dict[str, Any]) -> None:
        """参数更新事件: 写审计日志(合规要求)"""
        # 审计日志(参数变更是合规要求)
        await _write_audit_log(scanner, "param_updated", data)
    on_param_updated.__name__ = "on_param_updated"
    return on_param_updated


def _make_emotion_changed_handler(scanner) -> Callable:
    """情绪变化事件handler"""
    async def on_emotion_changed(data: Dict[str, Any]) -> None:
        """情绪变化事件: 推送Redis状态(前端情绪面板)"""
        # Redis状态推送(前端情绪面板实时更新)
        await _push_to_redis(scanner, "scanner:status", {
            "event": "emotion_changed",
            "phase": data.get("phase", ""),
            "score": data.get("score", 0),
            "position_ratio": data.get("position_ratio", 0),
        })
    on_emotion_changed.__name__ = "on_emotion_changed"
    return on_emotion_changed


def _make_daily_settled_handler(scanner) -> Callable:
    """盘后结算事件handler(v2.9:扩展为审计日志+绩效快照+飞书日报)"""
    async def on_daily_settled(data: Dict[str, Any]) -> None:
        """盘后结算事件: 审计日志+绩效快照+飞书日报"""
        # 审计日志
        await _write_audit_log(scanner, "daily_settled", data)
        # Redis推送
        await _push_to_redis(scanner, "scanner:status", {
            "event": "daily_settled",
            "trade_date": data.get("trade_date", ""),
            "total_profit": data.get("total_profit", 0),
        })
        # 【v2.9:绩效快照保存(从scanner._scan_loop解耦到EventBus)】
        trade_date = data.get("trade_date", "")
        if trade_date:
            try:
                await scanner._save_performance_snapshot(trade_date)
            except Exception as e:
                logger.warning(f"[DAILY] 保存绩效快照失败: {e}")
            # 【v2.9:推送飞书日报(从scanner._scan_loop解耦到EventBus)】
            try:
                await scanner._push_daily_summary(trade_date)
            except Exception as e:
                logger.warning(f"[DAILY] 推送日报失败: {e}")
    on_daily_settled.__name__ = "on_daily_settled"
    return on_daily_settled


def _make_signal_generated_handler(scanner) -> Callable:
    """信号生成事件handler"""
    async def on_signal_generated(data: Dict[str, Any]) -> None:
        """信号生成事件: 推送Redis Pub/Sub状态通知
        
        【v2.9.82修复】不再向scanner:signal Stream重复写入！
        signal_manager._publish_scanner_event("signal")已写入scanner:signal Stream,
        此处如果再写会导致前端WS收到重复信号。
        只推scanner:status通知(轻量, 前端用于信号计数/声音提示)。
        """
        await _push_to_redis(scanner, "scanner:status", {
            "event": "signal_generated",
            "signal_count": data.get("signal_count", 0),
        })
    on_signal_generated.__name__ = "on_signal_generated"
    return on_signal_generated


def _make_scanner_error_handler(scanner) -> Callable:
    """【v2.9.15】扫描器异常事件handler"""
    async def on_scanner_error(data: Dict[str, Any]) -> None:
        """扫描器异常事件: 推送Redis告警+日志"""
        # 异常推送(Pub/Sub, 允许丢但前端可感知)
        await _push_to_redis(scanner, "scanner:status", {
            "event": "scanner_error",
            "error": data.get("error", "unknown"),
            "error_type": data.get("error_type", "UnknownError"),
            "timestamp": data.get("timestamp", time.time()),
        })
        # 审计日志
        await _write_audit_log(scanner, "scanner_error", {
            "error": data.get("error", ""),
            "error_type": data.get("error_type", ""),
        })
    on_scanner_error.__name__ = "on_scanner_error"
    return on_scanner_error
