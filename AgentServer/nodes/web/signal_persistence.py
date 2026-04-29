#!/usr/bin/env python3
"""
信号 MongoDB 持久化服务

解决的核心问题：
1. 信号集合缺少索引 → 查询慢、可能重复写入
2. 同一天重复运行会插入重复信号 → 需要幂等写入（upsert）
3. 信号缺少生命周期管理 → active/executed/expired 状态流转
4. 缺少查询辅助方法 → 各处分散写 MongoDB 查询代码
5. 缺少数据清理策略 → 历史数据无限膨胀

Collections & Indexes:
  daily_premarket_signals: 盘前信号主文档
    - (date, signal_id) unique
    - (status, generated_at)
    - (date) for daily lookup
  
  trading_signals: 每只股票一条信号记录（兼容已有API）
    - (signal_id) unique
    - (ts_code, trade_date)
    - (status, generated_at)
    - (strategy, generated_at)
  
  daily_postmarket_review: 盘后复盘报告
    - (date) unique
  
  signal_execution_log: 信号执行日志（新增）
    - (signal_id)
    - (account_id, executed_at)

使用方式：
  from nodes.web.signal_persistence import signal_persistence

  # 初始化（在 app lifespan 中调用一次）
  await signal_persistence.initialize()

  # 幂等写入盘前信号
  await signal_persistence.save_premarket_signal(signal_doc)

  # 查询
  signals = await signal_persistence.get_signals_by_date("20260423")
  pending = await signal_persistence.get_pending_signals()

  # 状态流转
  await signal_persistence.mark_signal_executed("sig_xxx", account_id, trade_id)
  await signal_persistence.expire_day_signals("20260423")

  # 清理
  await signal_persistence.cleanup_old_signals(retention_days=90)
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any

from core.managers import mongo_manager

logger = logging.getLogger("signal_persistence")


# ==================== 集合名 ====================

COLLECTION_PREMARKET = "daily_premarket_signals"
COLLECTION_TRADING = "trading_signals"
COLLECTION_REVIEW = "daily_postmarket_review"
COLLECTION_EXECUTION_LOG = "signal_execution_log"
COLLECTION_POOL = "premarket_pool"


# ==================== 信号状态 ====================

class SignalStatus:
    """信号生命周期状态"""
    ACTIVE = "active"          # 盘前生成，待执行
    PENDING = "pending"        # 兼容已有 trading_signals 状态
    EXECUTED = "executed"      # 已执行交易
    EXPIRED = "expired"        # 已过期（收盘未执行）
    CANCELLED = "cancelled"    # 手动取消


# 有效的状态流转
VALID_TRANSITIONS = {
    SignalStatus.ACTIVE: {SignalStatus.EXECUTED, SignalStatus.EXPIRED, SignalStatus.CANCELLED},
    SignalStatus.PENDING: {SignalStatus.EXECUTED, SignalStatus.EXPIRED, SignalStatus.CANCELLED},
    SignalStatus.EXECUTED: set(),    # 终态
    SignalStatus.EXPIRED: set(),     # 终态
    SignalStatus.CANCELLED: set(),   # 终态
}


class SignalPersistence:
    """
    信号 MongoDB 持久化服务

    核心能力：
    1. 幂等写入：同一天重复运行不会产生重复信号
    2. 索引管理：启动时自动创建必要索引
    3. 生命周期：active → executed / expired 状态流转
    4. 查询辅助：按日期/状态/策略等多维度查询
    5. 数据清理：自动清理过期历史数据
    """

    def __init__(self):
        self._initialized = False

    # ==================== 初始化 & 索引 ====================

    async def initialize(self) -> None:
        """创建信号相关集合的索引（幂等操作）"""
        if self._initialized:
            return

        logger.info("Initializing signal persistence indexes...")

        try:
            db = mongo_manager.db

            # daily_premarket_signals 索引
            await db[COLLECTION_PREMARKET].create_indexes([
                {"key": [("date", 1)], "unique": False, "name": "idx_date"},
                {"key": [("signal_id", 1)], "unique": True, "name": "idx_signal_id"},
                {"key": [("status", 1), ("generated_at", -1)], "name": "idx_status_date"},
                {"key": [("date", 1), ("signal_id", 1)], "unique": True, "name": "idx_date_signal"},
            ])

            # trading_signals 索引
            await db[COLLECTION_TRADING].create_indexes([
                {"key": [("signal_id", 1)], "unique": True, "name": "idx_signal_id"},
                {"key": [("ts_code", 1), ("generated_at", -1)], "name": "idx_tscode_date"},
                {"key": [("status", 1), ("generated_at", -1)], "name": "idx_status_date"},
                {"key": [("strategy", 1), ("generated_at", -1)], "name": "idx_strategy_date"},
                {"key": [("premarket_signal_id", 1)], "name": "idx_premarket_ref"},
            ])

            # daily_postmarket_review 索引
            await db[COLLECTION_REVIEW].create_indexes([
                {"key": [("date", 1)], "unique": True, "name": "idx_date"},
                {"key": [("review_id", 1)], "unique": True, "name": "idx_review_id"},
            ])

            # signal_execution_log 索引
            await db[COLLECTION_EXECUTION_LOG].create_indexes([
                {"key": [("signal_id", 1)], "name": "idx_signal_id"},
                {"key": [("account_id", 1), ("executed_at", -1)], "name": "idx_account_date"},
            ])

            # premarket_pool 索引
            await db[COLLECTION_POOL].create_indexes([
                {"key": [("date", 1)], "unique": False, "name": "idx_date"},
                {"key": [("date", 1), ("ts_code", 1)], "unique": True, "name": "idx_date_tscode"},
            ])

            self._initialized = True
            logger.info("Signal persistence indexes created ✓")

        except Exception as e:
            logger.error(f"Failed to create signal indexes: {e}")
            # 不阻塞启动，索引缺失只影响性能
            self._initialized = True

    # ==================== 幂等写入：盘前信号 ====================

    async def save_premarket_signal(self, signal_doc: Dict) -> Dict:
        """
        幂等写入盘前信号

        逻辑：
        - 同一天重复运行 → 更新已有记录（upsert），不产生重复
        - 首次写入 → 插入新记录
        - 同时兼容写入 trading_signals 集合

        Args:
            signal_doc: 盘前信号文档（来自 PremarketSignalScheduler._build_signal_doc）

        Returns:
            Dict: {"upserted": bool, "signal_id": str, "trading_count": int}
        """
        trade_date = signal_doc["date"]
        signal_id = signal_doc["signal_id"]

        # 1. 幂等写入 daily_premarket_signals
        #    使用 (date) 作为 upsert 键：同一天只保留最新信号
        existing = await mongo_manager.find_one(
            COLLECTION_PREMARKET,
            {"date": trade_date},
        )

        if existing:
            # 更新已有记录（保留原 _id）
            await mongo_manager.update_one(
                COLLECTION_PREMARKET,
                {"date": trade_date},
                {
                    "$set": {
                        "signal_id": signal_id,
                        "force_empty": signal_doc["force_empty"],
                        "sentiment": signal_doc["sentiment"],
                        "pool_size": signal_doc["pool_size"],
                        "auction_filtered_size": signal_doc["auction_filtered_size"],
                        "signals": signal_doc["signals"],
                        "signal_count": signal_doc["signal_count"],
                        "trading_plan": signal_doc["trading_plan"],
                        "status": signal_doc["status"],
                        "config_snapshot": signal_doc.get("config_snapshot", {}),
                        "generated_at": signal_doc["generated_at"],
                        "regenerated_at": datetime.now(timezone.utc),
                        "regeneration_count": (existing.get("regeneration_count", 0) or 0) + 1,
                    },
                },
            )
            logger.info(f"Updated existing premarket signal for {trade_date} (regeneration #{(existing.get('regeneration_count', 0) or 0) + 1})")
            upserted = False
        else:
            signal_doc["regeneration_count"] = 1
            await mongo_manager.insert_one(COLLECTION_PREMARKET, signal_doc)
            logger.info(f"Inserted new premarket signal for {trade_date}: {signal_id}")
            upserted = True

        # 2. 幂等写入 trading_signals 集合
        #    先删除同一天的旧信号，再插入新的
        trading_count = 0
        signals = signal_doc.get("signals", [])
        if signals:
            # 删除同一天的旧 pending 信号
            day_start = datetime.strptime(f"{trade_date} 00:00:00", "%Y%m%d %H:%M:%S")
            day_end = datetime.strptime(f"{trade_date} 23:59:59", "%Y%m%d %H:%M:%S")
            deleted = await mongo_manager.delete_many(
                COLLECTION_TRADING,
                {
                    "status": {"$in": [SignalStatus.PENDING, SignalStatus.ACTIVE]},
                    "generated_at": {"$gte": day_start, "$lte": day_end},
                },
            )
            if deleted:
                logger.info(f"Deleted {deleted} old pending trading signals for {trade_date}")

            # 插入新的交易信号
            trading_docs = self._build_trading_signal_docs(signals, signal_doc)
            if trading_docs:
                await mongo_manager.insert_many(COLLECTION_TRADING, trading_docs)
                trading_count = len(trading_docs)
                logger.info(f"Inserted {trading_count} trading signals for {trade_date}")

        return {
            "upserted": upserted,
            "signal_id": signal_id,
            "trading_count": trading_count,
        }

    def _build_trading_signal_docs(self, signals: List[Dict], parent_doc: Dict) -> List[Dict]:
        """构建 trading_signals 集合的文档列表"""
        trade_date = parent_doc["date"]
        sentiment = parent_doc.get("sentiment", {})
        now = datetime.now(timezone.utc)
        expired_at = datetime.strptime(f"{trade_date} 15:00:00", "%Y%m%d %H:%M:%S")

        docs = []
        for stock in signals:
            buy_price = stock.get("close", 0) * 1.01
            per_stock = 1_000_000 * 0.7 / 5  # 默认值
            qty = int(per_stock / max(buy_price, 0.01) / 100) * 100 if buy_price > 0 else 100

            docs.append({
                "signal_id": f"sig_{uuid.uuid4().hex[:12]}",
                "ts_code": stock.get("ts_code", ""),
                "stock_name": stock.get("name", ""),
                "strategy": stock.get("strategy", ""),
                "strategy_name": stock.get("strategy", ""),
                "signal_type": "buy",
                "price": buy_price,
                "suggest_quantity": qty,
                "confidence": stock.get("confidence", 0.7),
                "reason": f"策略:{stock.get('strategy', '?')} | 情绪:{sentiment.get('level', '?')}",
                "generated_at": now,
                "expired_at": expired_at,
                "status": SignalStatus.PENDING,
                "premarket_signal_id": parent_doc["signal_id"],
                "trade_date": trade_date,
            })
        return docs

    # ==================== 幂等写入：盘后回顾 ====================

    async def save_postmarket_review(self, review_doc: Dict) -> Dict:
        """
        幂等写入盘后回顾

        同一天重复运行 → 更新已有记录
        """
        trade_date = review_doc["date"]
        existing = await mongo_manager.find_one(COLLECTION_REVIEW, {"date": trade_date})

        if existing:
            await mongo_manager.update_one(
                COLLECTION_REVIEW,
                {"date": trade_date},
                {"$set": review_doc},
            )
            logger.info(f"Updated postmarket review for {trade_date}")
            return {"upserted": False, "review_id": review_doc["review_id"]}
        else:
            await mongo_manager.insert_one(COLLECTION_REVIEW, review_doc)
            logger.info(f"Inserted postmarket review for {trade_date}")
            return {"upserted": True, "review_id": review_doc["review_id"]}

    # ==================== 幂等写入：预选池 ====================

    async def save_premarket_pool(self, trade_date: str, pool: List[str], metadata: Dict = None) -> int:
        """
        保存预选池记录（幂等）

        Args:
            trade_date: 交易日期
            pool: 股票代码列表
            metadata: 附加信息（如排除规则、过滤条件）

        Returns:
            int: 写入记录数
        """
        if not pool:
            return 0

        # 删除同一天的旧记录
        await mongo_manager.delete_many(COLLECTION_POOL, {"date": trade_date})

        now = datetime.now(timezone.utc)
        docs = [
            {
                "date": trade_date,
                "ts_code": ts_code,
                "created_at": now,
                **(metadata or {}),
            }
            for ts_code in pool
        ]

        await mongo_manager.insert_many(COLLECTION_POOL, docs)
        logger.info(f"Saved premarket pool for {trade_date}: {len(docs)} stocks")
        return len(docs)

    # ==================== 查询方法 ====================

    async def get_signals_by_date(self, trade_date: str) -> Optional[Dict]:
        """查询指定日期的盘前信号"""
        return await mongo_manager.find_one(COLLECTION_PREMARKET, {"date": trade_date})

    async def get_signals_range(
        self, start_date: str, end_date: str, limit: int = 30,
    ) -> List[Dict]:
        """查询日期范围内的盘前信号"""
        return await mongo_manager.find_many(
            COLLECTION_PREMARKET,
            {"date": {"$gte": start_date, "$lte": end_date}},
            sort=[("generated_at", -1)],
            limit=limit,
        )

    async def get_latest_signals(self, limit: int = 10) -> List[Dict]:
        """获取最近的盘前信号"""
        return await mongo_manager.find_many(
            COLLECTION_PREMARKET,
            {},
            sort=[("generated_at", -1)],
            limit=limit,
        )

    async def get_pending_signals(self, trade_date: str = None) -> List[Dict]:
        """获取待执行的交易信号"""
        query = {"status": SignalStatus.PENDING}
        if trade_date:
            day_start = datetime.strptime(f"{trade_date} 00:00:00", "%Y%m%d %H:%M:%S")
            day_end = datetime.strptime(f"{trade_date} 23:59:59", "%Y%m%d %H:%M:%S")
            query["generated_at"] = {"$gte": day_start, "$lte": day_end}
        return await mongo_manager.find_many(
            COLLECTION_TRADING, query,
            sort=[("confidence", -1)],
        )

    async def get_signals_by_strategy(
        self, strategy: str, limit: int = 50,
    ) -> List[Dict]:
        """按策略查询交易信号"""
        return await mongo_manager.find_many(
            COLLECTION_TRADING,
            {"strategy": strategy},
            sort=[("generated_at", -1)],
            limit=limit,
        )

    async def get_signals_by_stock(
        self, ts_code: str, limit: int = 20,
    ) -> List[Dict]:
        """按股票查询交易信号"""
        return await mongo_manager.find_many(
            COLLECTION_TRADING,
            {"ts_code": ts_code},
            sort=[("generated_at", -1)],
            limit=limit,
        )

    async def get_signal_stats(self, trade_date: str = None) -> Dict:
        """获取信号统计"""
        query = {}
        if trade_date:
            day_start = datetime.strptime(f"{trade_date} 00:00:00", "%Y%m%d %H:%M:%S")
            day_end = datetime.strptime(f"{trade_date} 23:59:59", "%Y%m%d %H:%M:%S")
            query["generated_at"] = {"$gte": day_start, "$lte": day_end}

        pipeline = [
            {"$match": query},
            {"$group": {
                "_id": "$status",
                "count": {"$sum": 1},
            }},
        ]
        results = await mongo_manager.aggregate(COLLECTION_TRADING, pipeline)

        stats = {s: 0 for s in [SignalStatus.PENDING, SignalStatus.EXECUTED, SignalStatus.EXPIRED, SignalStatus.CANCELLED]}
        for r in results:
            status = r["_id"]
            if status in stats:
                stats[status] = r["count"]

        stats["total"] = sum(stats.values())
        return stats

    async def get_pool_by_date(self, trade_date: str) -> List[str]:
        """获取指定日期的预选池"""
        records = await mongo_manager.find_many(
            COLLECTION_POOL,
            {"date": trade_date},
            projection={"ts_code": 1},
        )
        return [r["ts_code"] for r in records if r.get("ts_code")]

    # ==================== 生命周期管理 ====================

    async def mark_signal_executed(
        self,
        signal_id: str,
        account_id: str,
        trade_id: str,
        execution_price: float = None,
        execution_quantity: int = None,
    ) -> bool:
        """
        标记交易信号为已执行

        Args:
            signal_id: 信号ID
            account_id: 执行账户ID
            trade_id: 交易记录ID
            execution_price: 实际执行价格
            execution_quantity: 实际执行数量

        Returns:
            bool: 是否成功
        """
        # 1. 验证信号存在且状态允许转换
        signal = await mongo_manager.find_one(
            COLLECTION_TRADING,
            {"signal_id": signal_id},
        )

        if not signal:
            logger.warning(f"Signal {signal_id} not found")
            return False

        current_status = signal.get("status")
        if current_status not in VALID_TRANSITIONS or SignalStatus.EXECUTED not in VALID_TRANSITIONS.get(current_status, set()):
            logger.warning(f"Signal {signal_id} status {current_status} cannot transition to executed")
            return False

        # 2. 更新信号状态
        now = datetime.now(timezone.utc)
        update_fields = {
            "status": SignalStatus.EXECUTED,
            "executed_time": now,
            "executed_account_id": account_id,
            "executed_trade_id": trade_id,
        }
        if execution_price is not None:
            update_fields["execution_price"] = execution_price
        if execution_quantity is not None:
            update_fields["execution_quantity"] = execution_quantity

        await mongo_manager.update_one(
            COLLECTION_TRADING,
            {"signal_id": signal_id},
            {"$set": update_fields},
        )

        # 3. 写入执行日志
        await mongo_manager.insert_one(COLLECTION_EXECUTION_LOG, {
            "signal_id": signal_id,
            "ts_code": signal.get("ts_code"),
            "account_id": account_id,
            "trade_id": trade_id,
            "strategy": signal.get("strategy"),
            "signal_type": signal.get("signal_type"),
            "expected_price": signal.get("price"),
            "execution_price": execution_price,
            "execution_quantity": execution_quantity,
            "executed_at": now,
        })

        # 4. 检查盘前信号是否所有子信号都已执行
        premarket_id = signal.get("premarket_signal_id")
        if premarket_id:
            await self._check_premarket_all_executed(premarket_id)

        logger.info(f"Signal {signal_id} marked as executed by account {account_id}")
        return True

    async def mark_signal_cancelled(self, signal_id: str, reason: str = "") -> bool:
        """标记信号为已取消"""
        signal = await mongo_manager.find_one(
            COLLECTION_TRADING,
            {"signal_id": signal_id},
        )
        if not signal:
            return False

        current_status = signal.get("status")
        if SignalStatus.CANCELLED not in VALID_TRANSITIONS.get(current_status, set()):
            return False

        await mongo_manager.update_one(
            COLLECTION_TRADING,
            {"signal_id": signal_id},
            {"$set": {
                "status": SignalStatus.CANCELLED,
                "cancelled_at": datetime.now(timezone.utc),
                "cancel_reason": reason,
            }},
        )
        return True

    async def expire_day_signals(self, trade_date: str) -> int:
        """
        将指定日期所有未执行的信号标记为过期

        Args:
            trade_date: 交易日期

        Returns:
            int: 过期的信号数
        """
        day_start = datetime.strptime(f"{trade_date} 00:00:00", "%Y%m%d %H:%M:%S")
        day_end = datetime.strptime(f"{trade_date} 23:59:59", "%Y%m%d %H:%M:%S")
        now = datetime.now(timezone.utc)

        # 过期 trading_signals
        result = await mongo_manager.update_many(
            COLLECTION_TRADING,
            {
                "status": {"$in": [SignalStatus.PENDING, SignalStatus.ACTIVE]},
                "generated_at": {"$gte": day_start, "$lte": day_end},
            },
            {"$set": {
                "status": SignalStatus.EXPIRED,
                "expired_at": now,
            }},
        )
        count = result if isinstance(result, int) else result.get("modified_count", 0)

        # 更新盘前信号状态
        await mongo_manager.update_one(
            COLLECTION_PREMARKET,
            {"date": trade_date, "status": SignalStatus.ACTIVE},
            {"$set": {"status": SignalStatus.EXPIRED, "expired_at": now}},
        )

        logger.info(f"Expired {count} trading signals for {trade_date}")
        return count

    async def _check_premarket_all_executed(self, premarket_signal_id: str) -> None:
        """检查盘前信号的所有子信号是否都已执行"""
        # 查找该盘前信号下所有未执行的子信号
        pending_count = await mongo_manager.count(COLLECTION_TRADING, {
            "premarket_signal_id": premarket_signal_id,
            "status": {"$in": [SignalStatus.PENDING, SignalStatus.ACTIVE]},
        })

        if pending_count == 0:
            # 所有子信号都已处理，更新盘前信号状态
            await mongo_manager.update_one(
                COLLECTION_PREMARKET,
                {"signal_id": premarket_signal_id},
                {"$set": {"status": SignalStatus.EXECUTED, "executed_at": datetime.now(timezone.utc)}},
            )
            logger.info(f"All sub-signals of {premarket_signal_id} executed, marking as executed")

    # ==================== 数据清理 ====================

    async def cleanup_old_signals(self, retention_days: int = 90) -> Dict:
        """
        清理过期历史数据

        Args:
            retention_days: 保留天数，默认90天

        Returns:
            Dict: 各集合删除数量
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        cutoff_date = cutoff.strftime("%Y%m%d")

        results = {}

        # 1. 清理 trading_signals
        deleted = await mongo_manager.delete_many(
            COLLECTION_TRADING,
            {"generated_at": {"$lt": cutoff}},
        )
        results["trading_signals_deleted"] = deleted
        logger.info(f"Cleaned up {deleted} old trading_signals (before {cutoff_date})")

        # 2. 清理 daily_premarket_signals
        deleted = await mongo_manager.delete_many(
            COLLECTION_PREMARKET,
            {"date": {"$lt": cutoff_date}},
        )
        results["premarket_signals_deleted"] = deleted

        # 3. 清理 daily_postmarket_review
        deleted = await mongo_manager.delete_many(
            COLLECTION_REVIEW,
            {"date": {"$lt": cutoff_date}},
        )
        results["reviews_deleted"] = deleted

        # 4. 清理 signal_execution_log
        deleted = await mongo_manager.delete_many(
            COLLECTION_EXECUTION_LOG,
            {"executed_at": {"$lt": cutoff}},
        )
        results["execution_logs_deleted"] = deleted

        # 5. 清理 premarket_pool
        deleted = await mongo_manager.delete_many(
            COLLECTION_POOL,
            {"date": {"$lt": cutoff_date}},
        )
        results["pool_deleted"] = deleted

        logger.info(f"Signal cleanup completed: {results}")
        return results

    # ==================== 辅助 ====================

    @property
    def is_initialized(self) -> bool:
        return self._initialized


# ==================== 全局单例 ====================

signal_persistence = SignalPersistence()
