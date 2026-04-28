"""
Redis Pub/Sub → WebSocket 日志推送桥接服务

解决三个核心问题：
1. 实现Redis Pub/Sub通道，替代前端MongoDB轮询：回测节点→Redis Pub/Sub→Web节点订阅→WebSocket推送→前端
2. MongoDB异步写入不影响推送性能：日志先发布到Redis（即时推送），再异步写入MongoDB（持久化）
3. WebSocket断开重连时支持日志补发：客户端重连订阅task时，从MongoDB读取历史日志补发

架构：
  BacktestNode._push_log()
    ├── redis_manager.publish("backtest:logs", ...)   ← 即时推送（毫秒级）
    └── async mongo write (background task)            ← 异步持久化（不阻塞推送）

  WebNode.RedisWSBridge
    ├── subscribe("backtest:logs")                     ← 订阅Redis频道
    ├── on_message → manager.broadcast_task_update()   ← 推送到WebSocket客户端
    └── on_subscribe(task_id, ws) → catchup from MongoDB  ← 重连补发
"""

import json
import asyncio
import logging
from typing import Dict, Set, Optional, Any, List
from datetime import datetime

from redis.asyncio.client import PubSub

from core.managers import redis_manager, mongo_manager


logger = logging.getLogger("ws_bridge")


# ==================== 频道常量 ====================

CHANNEL_BACKTEST_LOGS = "backtest:logs"
CHANNEL_BACKTEST_STATUS = "backtest:status"
CHANNEL_BACKTEST_PROGRESS = "backtest:progress"

# Scheduler 频道
CHANNEL_SCHEDULER_STATUS = "scheduler:status"
CHANNEL_SCHEDULER_PHASE = "scheduler:phase"


# ==================== Redis Pub/Sub → WebSocket 桥接 ====================


class RedisWSBridge:
    """
    Redis Pub/Sub → WebSocket 桥接服务

    运行在 Web 节点内，职责：
    1. 订阅 Redis backtest:* 频道
    2. 将消息转发到对应 task 的 WebSocket 订阅者
    3. 新客户端订阅 task 时，从 MongoDB 补发历史日志

    使用方式：
        # 在 Web 节点启动时初始化
        bridge = RedisWSBridge(ws_manager)
        await bridge.start()

        # 在 Web 节点关闭时停止
        await bridge.stop()
    """

    def __init__(self, ws_manager: Any):
        """
        Args:
            ws_manager: WebSocket ConnectionManager 实例
        """
        self._ws_manager = ws_manager
        self._pubsub: Optional[PubSub] = None
        self._listener_task: Optional[asyncio.Task] = None
        self._running = False

        # 日志缓存：task_id -> [log_string, ...]
        # 用于快速补发最近日志（不查MongoDB）
        self._log_cache: Dict[str, List[str]] = {}
        self._log_cache_max = 500  # 每个task最多缓存500条

    async def start(self) -> None:
        """启动桥接服务"""
        if self._running:
            return

        logger.info("Starting Redis→WebSocket bridge...")


        # 2. 订阅 Redis 频道
        try:
            self._pubsub = redis_manager.client.pubsub()
            await self._pubsub.subscribe(
                CHANNEL_BACKTEST_LOGS,
                CHANNEL_BACKTEST_STATUS,
                CHANNEL_BACKTEST_PROGRESS,
                CHANNEL_SCHEDULER_STATUS,
                CHANNEL_SCHEDULER_PHASE,
            )
            logger.info(f"Subscribed to Redis channels: {CHANNEL_BACKTEST_LOGS}, {CHANNEL_BACKTEST_STATUS}, {CHANNEL_BACKTEST_PROGRESS}, {CHANNEL_SCHEDULER_STATUS}, {CHANNEL_SCHEDULER_PHASE}")
        except Exception as e:
            logger.error(f"Failed to subscribe to Redis: {e}")
            # Redis订阅失败不阻塞启动，降级为仅MongoDB模式
            self._pubsub = None

        # 3. 启动 Redis 监听协程
        if self._pubsub:
            self._listener_task = asyncio.create_task(self._redis_listener())
            logger.info("Redis listener started")

        self._running = True
        logger.info("Redis→WebSocket bridge started ✓")

    async def stop(self) -> None:
        """停止桥接服务"""
        if not self._running:
            return

        self._running = False
        logger.info("Stopping Redis→WebSocket bridge...")

        # 停止 Redis 监听
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
            self._listener_task = None

        # 关闭 PubSub
        if self._pubsub:
            try:
                await self._pubsub.unsubscribe()
                await self._pubsub.close()
            except Exception:
                pass
            self._pubsub = None

        # 【修复风险4：不再停止MongoDB writer】
        logger.info("Redis→WebSocket bridge stopped")

    # ==================== Redis 监听 ====================

    async def _redis_listener(self) -> None:
        """监听 Redis Pub/Sub 消息，转发到 WebSocket 客户端"""
        try:
            async for message in self._pubsub.listen():
                if not self._running:
                    break

                if message["type"] != "message":
                    continue

                channel = message.get("channel", "")
                if isinstance(channel, bytes):
                    channel = channel.decode("utf-8")

                data_str = message.get("data", "")
                if isinstance(data_str, bytes):
                    data_str = data_str.decode("utf-8")

                try:
                    data = json.loads(data_str)
                except (json.JSONDecodeError, TypeError):
                    continue

                task_id = data.get("task_id")

                if channel == CHANNEL_BACKTEST_LOGS:
                    await self._handle_log_message(task_id, data)
                elif channel == CHANNEL_BACKTEST_STATUS:
                    await self._handle_status_message(task_id, data)
                elif channel == CHANNEL_BACKTEST_PROGRESS:
                    await self._handle_progress_message(task_id, data)
                elif channel == CHANNEL_SCHEDULER_STATUS:
                    await self._handle_scheduler_status_message(data)
                elif channel == CHANNEL_SCHEDULER_PHASE:
                    await self._handle_scheduler_phase_message(data)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Redis listener error: {e}")

    async def _handle_log_message(self, task_id: str, data: dict) -> None:
        """处理日志消息：缓存 + 推送到WebSocket + 异步写MongoDB"""
        log_text = data.get("log", "")
        if not log_text:
            return

        # 1. 缓存日志（用于重连补发）
        if task_id not in self._log_cache:
            self._log_cache[task_id] = []
        self._log_cache[task_id].append(log_text)
        # 控制缓存大小
        if len(self._log_cache[task_id]) > self._log_cache_max:
            self._log_cache[task_id] = self._log_cache[task_id][-self._log_cache_max:]

        # 2. 即时推送到 WebSocket 客户端（毫秒级延迟）
        await self._ws_manager.broadcast_task_update(task_id, {
            "type": "log",
            "task_id": task_id,
            "log": log_text,
        })

        # 【修复风险4：不再往mongo_write_queue塞数据，Bridge不写MongoDB】
        # try:

    async def _handle_status_message(self, task_id: str, data: dict) -> None:
        """处理状态变更消息"""
        await self._ws_manager.broadcast_task_update(task_id, {
            "type": "status",
            "task_id": task_id,
            "status": data.get("status"),
            "error": data.get("error"),
        })

    async def _handle_progress_message(self, task_id: str, data: dict) -> None:
        """处理进度更新消息"""
        await self._ws_manager.broadcast_task_update(task_id, {
            "type": "progress",
            "task_id": task_id,
            "progress": data.get("progress", 0),
        })

    # ==================== Scheduler 频道处理 ====================

    async def _handle_scheduler_status_message(self, data: dict) -> None:
        """处理调度器状态变更消息（started/stopped）
        
        推送到所有订阅了 scheduler 频道的 WebSocket 客户端。
        """
        await self._ws_manager.broadcast_scheduler_event({
            "type": "scheduler_status",
            "action": data.get("action"),  # started / stopped
            "timestamp": data.get("timestamp"),
            "details": data.get("details", {}),
        })

    async def _handle_scheduler_phase_message(self, data: dict) -> None:
        """处理调度器阶段执行消息（started/step_completed/completed/failed）
        
        推送到所有订阅了 scheduler 频道的 WebSocket 客户端。
        """
        await self._ws_manager.broadcast_scheduler_event({
            "type": "scheduler_phase",
            "phase": data.get("phase"),      # premarket / intraday / postmarket / full
            "event": data.get("event"),      # started / completed / failed
            "trade_date": data.get("trade_date"),
            "timestamp": data.get("timestamp"),
            "data": data.get("data", {}),
        })

    # ==================== MongoDB 异步批量写入 ====================

    # 【修复风险4：_mongo_batch_writer已废弃，不再调用，Bridge不写MongoDB】
    # MongoDB写入统一由BacktestNode._push_log()负责
    # async def _mongo_batch_writer(self) -> None: ... 已删除
    # async def _flush_batch(self, batch) -> None: ... 已删除

    # ==================== WebSocket 重连日志补发 ====================

    async def catchup_logs(self, task_id: str, websocket: Any) -> None:
        """
        为重连的 WebSocket 客户端补发历史日志

        策略：
        1. 优先从内存缓存中读取（最快）
        2. 如果缓存不足或不存在，从 MongoDB 读取
        3. 补发后发送一个 "catchup_end" 标记，让前端知道补发完毕

        Args:
            task_id: 任务ID
            websocket: WebSocket 连接
        """
        logs_to_send = []

        # 1. 尝试从内存缓存获取
        cached_logs = self._log_cache.get(task_id, [])
        if cached_logs:
            logs_to_send = cached_logs
            logger.info(f"[catchup] Sending {len(cached_logs)} cached logs for {task_id}")
        else:
            # 2. 从 MongoDB 获取
            try:
                record = await mongo_manager.find_one(
                    "backtest_tasks",
                    {"task_id": task_id},
                )
                if record and record.get("logs"):
                    logs_to_send = record["logs"]
                    logger.info(f"[catchup] Sending {len(logs_to_send)} MongoDB logs for {task_id}")
                    # 同步到内存缓存
                    self._log_cache[task_id] = logs_to_send[-self._log_cache_max:]
            except Exception as e:
                logger.error(f"[catchup] Failed to fetch logs from MongoDB for {task_id}: {e}")

        # 3. 逐条补发（避免一次性发送大量数据导致WebSocket阻塞）
        for log_text in logs_to_send:
            try:
                await websocket.send_json({
                    "type": "log",
                    "task_id": task_id,
                    "log": log_text,
                })
            except Exception:
                break  # WebSocket已断开，停止补发

        # 4. 发送补发完成标记
        try:
            await websocket.send_json({
                "type": "catchup_end",
                "task_id": task_id,
                "count": len(logs_to_send),
            })
        except Exception:
            pass

    # ==================== 状态查询 ====================

    @property
    def is_running(self) -> bool:
        return self._running

    def get_stats(self) -> Dict[str, Any]:
        """获取桥接服务状态"""
        return {
            "running": self._running,
            "subscribed": self._pubsub is not None,
            "cached_tasks": len(self._log_cache),
        }


# ==================== 全局单例（需要在Web节点启动时初始化） ====================

_bridge: Optional[RedisWSBridge] = None


def get_bridge() -> Optional[RedisWSBridge]:
    """获取全局桥接实例"""
    return _bridge


def init_bridge(ws_manager: Any) -> RedisWSBridge:
    """初始化全局桥接实例"""
    global _bridge
    _bridge = RedisWSBridge(ws_manager)
    return _bridge
