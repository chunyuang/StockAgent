#!/usr/bin/env python3
"""ScannerDaemon Redis订阅混入

v2.9.68从scanner_daemon.py提取, 包含:
- Redis连接管理
- 订阅循环 (status/signal/position/health)
- 订阅消息处理
- 回调注册
- Redis清理
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional, Callable

logger = logging.getLogger("scanner.daemon")


class DaemonSubscriptionMixin:
    """ScannerDaemon Redis订阅混入"""

    def on_status(self, callback: Callable[[dict], None]) -> None:
        """注册状态回调"""
        self._status_callback = callback

    def on_signal(self, callback: Callable[[dict], None]) -> None:
        """注册信号回调"""
        self._signal_callback = callback

    def on_position(self, callback: Callable[[dict], None]) -> None:
        """注册持仓变更回调"""
        self._position_callback = callback

    def on_health(self, callback: Callable[[dict], None]) -> None:
        """注册健康回调"""
        self._health_callback = callback

    async def _ensure_redis(self) -> None:
        """确保 Redis 连接"""
        if self._redis_client is not None:
            return
        try:
            import redis.asyncio as aioredis
            from core.settings import settings as app_settings
            self._redis_client = aioredis.from_url(
                app_settings.redis.url,
                decode_responses=True,
                max_connections=10,
            )
            await self._redis_client.ping()
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            self._redis_client = None

    async def _init_redis_subscriptions(self) -> None:
        """初始化 Redis 订阅"""
        await self._ensure_redis()
        if self._redis_client is None:
            logger.error("Cannot subscribe: Redis not available")
            return

        self._status_sub_task = asyncio.create_task(
            self._subscribe_loop("status", self._status_callback)
        )
        self._signal_sub_task = asyncio.create_task(
            self._subscribe_loop("signal", self._signal_callback)
        )
        self._position_sub_task = asyncio.create_task(
            self._subscribe_loop("position", self._position_callback)
        )
        self._health_sub_task = asyncio.create_task(
            self._subscribe_loop("health", self._health_callback)
        )
        # 【v2.9.7: ACK监听器】
        self._ack_sub_task = asyncio.create_task(
            self._ack_listener()
        )

    async def _subscribe_loop(self, channel_suffix: str, callback: Optional[Callable]) -> None:
        """订阅 Redis 频道的循环"""
        from nodes.market_monitor.scanner_daemon import _chan
        channel = _chan(self.config, channel_suffix)
        try:
            pubsub = self._redis_client.pubsub()
            await pubsub.subscribe(channel)
            logger.info(f"Subscribed to {channel}")

            while self._running:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                if message and message["type"] == "message":
                    await self._handle_subscription_message(channel_suffix, message["data"], callback)
                else:
                    await asyncio.sleep(0.05)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Subscription loop error on {channel}: {e}")
        finally:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.close()
            except Exception as _e:
                logger.debug(f"pubsub cleanup failed: {_e}")

    async def _handle_subscription_message(
        self, channel_suffix: str, raw_data: bytes, callback: Optional[Callable]
    ) -> None:
        """处理订阅消息: 解析+状态更新+回调【v2.9.56从_subscribe_loop提取】"""
        try:
            data = json.loads(raw_data)

            # 特殊处理: 更新状态
            if channel_suffix == "status" and "state" in data:
                try:
                    from nodes.market_monitor.scanner_daemon import ScannerState
                    self._state = ScannerState(data["state"])
                except ValueError:
                    pass

            # 特殊处理: 更新健康时间戳
            if channel_suffix == "health" and "ts" in data:
                self._last_health_ts = data["ts"]

            # 调用回调
            if callback:
                callback(data)

        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON on {channel_suffix}: {e}")
        except Exception as e:
            logger.error(f"Callback error on {channel_suffix}: {e}")

    async def _cleanup_redis_subscriptions(self) -> None:
        """清理 Redis"""
        if self._redis_client:
            try:
                await self._redis_client.close()
            except Exception as _e:
                logger.debug(f"redis client close failed: {_e}")
            self._redis_client = None
