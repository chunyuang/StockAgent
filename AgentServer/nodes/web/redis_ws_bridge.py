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

# Scanner 频道
CHANNEL_SCANNER_SIGNAL = "scanner:signal"
CHANNEL_SCANNER_POSITION = "scanner:position"
CHANNEL_SCANNER_TIMELINE = "scanner:timeline"
CHANNEL_SCANNER_STATUS = "scanner:status"


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
        self._stream_task: Optional[asyncio.Task] = None  # 【Phase2.1】
        self._running = False

        # 【方案C】日志不再缓存，前端完成后通过API从.jsonl文件读取

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
                # 【v2.9.14】scanner:signal和scanner:position已升级为Redis Stream,
                # 由_redis_stream_consumer(XREADGROUP)处理,不再通过Pub/Sub
                CHANNEL_SCANNER_TIMELINE,
                CHANNEL_SCANNER_STATUS,
            )
            logger.info(f"Subscribed to Redis channels: backtest+scheduler+scanner")
        except Exception as e:
            logger.error(f"Failed to subscribe to Redis: {e}")
            # Redis订阅失败不阻塞启动，降级为仅MongoDB模式
            self._pubsub = None

        # 3. 启动 Redis 监听协程(Pub/Sub)
        if self._pubsub:
            self._listener_task = asyncio.create_task(self._redis_listener())
            logger.info("Redis Pub/Sub listener started")
        
        # 【Phase2.1:启动Redis Stream消费协程(signal/position不可丢)】
        self._stream_task = asyncio.create_task(self._redis_stream_consumer())
        logger.info("Redis Stream consumer started")

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
            except Exception as e:
                logger.warning(f"WebSocket error: {e}")
                pass
            self._pubsub = None

        # 【修复风险4：不再停止MongoDB writer】
        
        # 【Phase2.1:停止Stream消费者】
        if self._stream_task:
            self._stream_task.cancel()
            try:
                await self._stream_task
            except asyncio.CancelledError:
                pass
            self._stream_task = None
        
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
                # 【v2.9.14】scanner:signal和scanner:position由Stream消费者处理
                # 不再在Pub/Sub监听器中处理
                elif channel == CHANNEL_SCANNER_TIMELINE:
                    await self._handle_scanner_timeline_message(data)
                elif channel == CHANNEL_SCANNER_STATUS:
                    await self._handle_scanner_status_message(data)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Redis listener error: {e}")

    # ==================== Phase2.1: Redis Stream消费者 ====================

    async def _redis_stream_consumer(self) -> None:
        """消费Redis Stream中的signal/position消息(不可丢,有ACK机制)
        
        Scanner写入signal/position到Stream, 这里用消费组读取并ACK。
        断线重连后可从上次ACK位置继续消费,不丢消息。
        """
        # 创建消费组(如果不存在)
        group_name = "ws_bridge_group"
        consumer_name = "web-node-1"
        
        for stream_key in [CHANNEL_SCANNER_SIGNAL, CHANNEL_SCANNER_POSITION]:
            try:
                await redis_manager.client.xgroup_create(
                    stream_key, group_name, id="0", mkstream=True
                )
            except Exception:
                pass  # 消费组已存在
        
        logger.info(f"Stream consumer groups created for signal/position")
        
        while self._running:
            try:
                # 从Stream读取(阻塞1秒)
                entries = await redis_manager.client.xreadgroup(
                    group_name, consumer_name,
                    {CHANNEL_SCANNER_SIGNAL: ">", CHANNEL_SCANNER_POSITION: ">"},
                    count=10, block=1000
                )
                
                if entries:
                    for stream_name, messages in entries:
                        if isinstance(stream_name, bytes):
                            stream_name = stream_name.decode("utf-8")
                        
                        for msg_id, fields in messages:
                            # 【v2.9.14】支持两种Stream格式:
                            # 1. 嵌套JSON: fields={"data": "{...}"} (旧格式)
                            # 2. 扁平字段: fields={"ts_code": "...", "action": "..."} (新格式)
                            data_str = fields.get("data", "")
                            if isinstance(data_str, bytes):
                                data_str = data_str.decode("utf-8")
                            
                            if data_str:
                                # 旧格式: data字段包含JSON字符串
                                try:
                                    data = json.loads(data_str)
                                except (json.JSONDecodeError, TypeError):
                                    continue
                            else:
                                # 新格式: 扁平字段(signal_dispatcher + _push_to_redis)
                                data = {}
                                for k, v in fields.items():
                                    if isinstance(k, bytes):
                                        k = k.decode("utf-8")
                                    if isinstance(v, bytes):
                                        v = v.decode("utf-8")
                                    data[k] = v
                            
                            # 转发到WebSocket(含_stream_id, 供前端断线补发)
                            if stream_name == CHANNEL_SCANNER_SIGNAL:
                                await self._handle_scanner_signal_message(data, stream_id=str(msg_id))
                            elif stream_name == CHANNEL_SCANNER_POSITION:
                                await self._handle_scanner_position_message(data, stream_id=str(msg_id))
                            
                            # ACK确认
                            await redis_manager.client.xack(
                                stream_name, group_name, msg_id
                            )
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Stream consumer error: {e}")
                await asyncio.sleep(1)  # 出错后等待1秒重试
    
    async def _handle_log_message(self, task_id: str, data: dict) -> None:
        """处理日志消息：透传到WebSocket（不再缓存，前端完成后从API拉取）"""
        log_text = data.get("log", "")
        if not log_text:
            return

        # 即时推送到 WebSocket 客户端（运行中可见）
        await self._ws_manager.broadcast_task_update(task_id, {
            "type": "log",
            "task_id": task_id,
            "log": log_text,
        })

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

    # ==================== Scanner 频道处理 ====================

    async def _handle_scanner_signal_message(self, data: dict, stream_id: str = "") -> None:
        """处理scanner信号消息"""
        msg = {
            "type": "scanner_signal",
            "signals": data.get("signals", []),
            "timestamp": data.get("timestamp"),
        }
        if stream_id:
            msg["_stream_id"] = stream_id
        await self._ws_manager.broadcast_scanner_event(msg)

    async def _handle_scanner_position_message(self, data: dict, stream_id: str = "") -> None:
        """处理scanner持仓变更消息"""
        msg = {
            "type": "scanner_position",
            "positions": data.get("positions", []),
            "timestamp": data.get("timestamp"),
        }
        if stream_id:
            msg["_stream_id"] = stream_id
        await self._ws_manager.broadcast_scanner_event(msg)

    async def _handle_scanner_timeline_message(self, data: dict) -> None:
        """处理scanner时间线消息"""
        await self._ws_manager.broadcast_scanner_event({
            "type": "scanner_timeline",
            "item": data.get("item", {}),
            "timestamp": data.get("timestamp"),
        })

    async def _handle_scanner_status_message(self, data: dict) -> None:
        """处理scanner状态变更消息"""
        await self._ws_manager.broadcast_scanner_event({
            "type": "scanner_status",
            "status": data.get("status", {}),
            "timestamp": data.get("timestamp"),
        })

    # ==================== WebSocket 重连日志补发 ====================

    async def catchup_logs(self, task_id: str, websocket: Any) -> None:
        """
        为重连的 WebSocket 客户端补发历史日志

        方案C：日志从本地.jsonl/.log文件读取（通过API）
        不再依赖内存缓存，重启后仍可补发
        """
        # 不再做内存补发，前端完成后通过API /backtest/logs/{task_id} 获取
        # 运行中的实时日志仍通过Redis推送
        try:
            await websocket.send_json({
                "type": "catchup_end",
                "task_id": task_id,
                "count": 0,
                "message": "历史日志请通过API获取: GET /backtest/logs/{task_id}",
            })
        except Exception:
            pass

    async def catchup_scanner_stream(self, stream: str, last_id: str, websocket: Any) -> int:
        """【v2.9.14】为重连的WS客户端补发Scanner Stream消息
        
        WS断线重连后，前端可传last_id(上次收到的Stream entry ID)，
       从此ID之后读取未消费的消息并推送，实现断线不丢。
        
        Args:
            stream: Stream名称(scanner:signal / scanner:position)
            last_id: 上次收到的entry ID(如"1717000000000-0")
            websocket: WebSocket连接
        Returns:
            补发消息数量
        """
        if not last_id or not redis_manager._initialized:
            return 0
        
        try:
            # 从last_id之后读取(XRANGE, 不含last_id)
            messages = await redis_manager.client.xrange(
                stream, min=f"({last_id}", max="+", count=100
            )
            
            count = 0
            for msg_id, fields in messages:
                # 构造消息(与实时推送格式一致)
                data = {}
                for k, v in fields.items():
                    if isinstance(k, bytes):
                        k = k.decode("utf-8")
                    if isinstance(v, bytes):
                        v = v.decode("utf-8")
                    data[k] = v
                
                if stream == CHANNEL_SCANNER_SIGNAL:
                    await websocket.send_json({
                        "type": "scanner_signal",
                        "signals": data.get("signals", []),
                        "timestamp": data.get("timestamp"),
                        "_stream_id": msg_id,
                    })
                elif stream == CHANNEL_SCANNER_POSITION:
                    await websocket.send_json({
                        "type": "scanner_position",
                        "positions": data.get("positions", []),
                        "timestamp": data.get("timestamp"),
                        "_stream_id": msg_id,
                    })
                count += 1
            
            return count
        except Exception as e:
            logger.debug(f"Scanner Stream catchup失败: {e}")
            return 0

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
