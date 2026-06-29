"""【v2.9.107】事件流持久化工具

统一记录市场监听过程中的关键事件到 MongoDB:
- quote_degrade_events: 行情降级/恢复
- data_source_events: 数据源切换
- risk_alerts: 风控告警

所有集合默认 TTL 30 天自动清理。
"""
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger("market_event_log")


_INDEXES_CREATED = False


async def ensure_indexes() -> None:
    """初始化事件流集合的索引和 TTL，进程内只跑一次"""
    global _INDEXES_CREATED
    if _INDEXES_CREATED:
        return
    try:
        from core.managers import mongo_manager
        if not getattr(mongo_manager, '_initialized', False):
            return
        # 行情降级事件: TTL 30 天
        await mongo_manager.db["quote_degrade_events"].create_index(
            "ts", expireAfterSeconds=30 * 24 * 3600, background=True
        )
        await mongo_manager.db["quote_degrade_events"].create_index(
            [("trade_date", -1), ("ts", -1)], background=True
        )
        # 数据源切换事件: TTL 30 天
        await mongo_manager.db["data_source_events"].create_index(
            "ts", expireAfterSeconds=30 * 24 * 3600, background=True
        )
        await mongo_manager.db["data_source_events"].create_index(
            [("trade_date", -1), ("ts", -1)], background=True
        )
        # 风控告警: TTL 90 天
        await mongo_manager.db["risk_alerts"].create_index(
            "ts", expireAfterSeconds=90 * 24 * 3600, background=True
        )
        await mongo_manager.db["risk_alerts"].create_index(
            [("check_name", 1), ("ts", -1)], background=True
        )
        _INDEXES_CREATED = True
        logger.info("[EVENT-LOG] 事件流集合索引已创建")
    except Exception as e:
        logger.warning(f"[EVENT-LOG] 索引创建失败: {e}")


def _today_int() -> int:
    return int(datetime.now().strftime("%Y%m%d"))


async def log_quote_degrade(
    from_level: int, to_level: int, reason: str = "",
    fail_count: int = 0, trade_date: Optional[int] = None
) -> None:
    """记录行情降级/恢复事件"""
    try:
        from core.managers import mongo_manager
        if not getattr(mongo_manager, '_initialized', False):
            return
        await ensure_indexes()
        now = datetime.now()
        doc = {
            "trade_date": trade_date or _today_int(),
            "ts": now,
            "from_level": from_level,
            "to_level": to_level,
            "reason": reason[:500],
            "fail_count": fail_count,
            "direction": "degrade" if to_level > from_level else "recover",
        }
        await mongo_manager.db["quote_degrade_events"].insert_one(doc)
    except Exception as e:
        logger.debug(f"[EVENT-LOG] log_quote_degrade 失败: {e}")


async def log_data_source_switch(
    from_source: str, to_source: str, reason: str = "",
    trade_date: Optional[int] = None
) -> None:
    """记录数据源切换事件"""
    try:
        from core.managers import mongo_manager
        if not getattr(mongo_manager, '_initialized', False):
            return
        await ensure_indexes()
        doc = {
            "trade_date": trade_date or _today_int(),
            "ts": datetime.now(),
            "from": from_source or "",
            "to": to_source or "",
            "reason": reason[:500],
        }
        await mongo_manager.db["data_source_events"].insert_one(doc)
    except Exception as e:
        logger.debug(f"[EVENT-LOG] log_data_source_switch 失败: {e}")


async def log_risk_alert(
    check_name: str, severity: str, message: str,
    details: Optional[dict] = None, trade_date: Optional[int] = None
) -> None:
    """记录风控告警 (替代纯 logger.warning 提供持久化)"""
    try:
        from core.managers import mongo_manager
        if not getattr(mongo_manager, '_initialized', False):
            return
        await ensure_indexes()
        doc = {
            "trade_date": trade_date or _today_int(),
            "ts": datetime.now(),
            "check_name": check_name[:100],
            "severity": severity,  # info/warn/error/critical
            "message": message[:2000],
            "details": details or {},
        }
        await mongo_manager.db["risk_alerts"].insert_one(doc)
    except Exception as e:
        logger.debug(f"[EVENT-LOG] log_risk_alert 失败: {e}")
