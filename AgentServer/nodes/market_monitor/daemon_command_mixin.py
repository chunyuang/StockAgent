#!/usr/bin/env python3
"""ScannerDaemon 命令发送混入

v2.9.68从scanner_daemon.py提取, 包含:
- 命令发送 (RPUSH到Redis List)
- ACK监听 (Pub/Sub + Future匹配)
- 便捷方法 (start_scanner/stop_scanner/emergency_liquidate/update_params/trigger_scan)
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Dict, Optional, Callable

logger = logging.getLogger("scanner.daemon")


class DaemonCommandMixin:
    """ScannerDaemon命令发送+ACK混入"""

    async def send_command(self, cmd: str, params: dict, timeout: float = None) -> Optional[dict]:
        """向子进程发送命令 (v2.9.7: RPUSH到List, 等待ACK)

        Args:
            cmd: 命令名
            params: 命令参数
            timeout: ACK超时(秒), None=使用config默认值

        Returns:
            ACK结果dict, 超时返回None
        """
        if self._redis_client is None:
            await self._ensure_redis()
        if self._redis_client is None:
            logger.error("Redis not available, cannot send command")
            return None

        cmd_id = str(uuid.uuid4())[:8]
        ack_timeout = timeout or self.config.cmd_ack_timeout

        # 注册ACK Future
        loop = asyncio.get_running_loop()
        ack_future = loop.create_future()
        self._pending_acks[cmd_id] = ack_future

        # RPUSH到List (子进程用BLPOP消费)
        from nodes.market_monitor.scanner_daemon import _chan
        cmd_list_key = _chan(self.config, "cmd")
        message = json.dumps({"cmd": cmd, "params": params, "cmd_id": cmd_id}, default=str)
        try:
            await self._redis_client.rpush(cmd_list_key, message)
            logger.info(f"Sent command: {cmd} (id={cmd_id})")
        except Exception as e:
            logger.error(f"Failed to send command {cmd}: {e}")
            self._pending_acks.pop(cmd_id, None)
            return None

        # 等待ACK
        return await self._wait_for_ack(cmd, cmd_id, ack_future, ack_timeout)

    async def _wait_for_ack(
        self, cmd: str, cmd_id: str, ack_future: asyncio.Future, ack_timeout: float
    ) -> Optional[dict]:
        """等待命令ACK确认【v2.9.56从send_command提取】"""
        try:
            result = await asyncio.wait_for(ack_future, timeout=ack_timeout)
            logger.info(f"Command {cmd} (id={cmd_id}) ACK: {result.get('status', 'unknown')}")
            return result
        except asyncio.TimeoutError:
            logger.warning(f"Command {cmd} (id={cmd_id}) ACK timeout ({ack_timeout}s)")
            return None
        finally:
            self._pending_acks.pop(cmd_id, None)

    async def _ack_listener(self) -> None:
        """【v2.9.7】订阅ACK通道, 匹配pending_acks并resolve Future"""
        from nodes.market_monitor.scanner_daemon import _chan
        ack_channel = _chan(self.config, "ack")
        try:
            pubsub = self._redis_client.pubsub()
            await pubsub.subscribe(ack_channel)
            logger.info(f"ACK listener subscribed to {ack_channel}")

            while self._running:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                if message and message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        cmd_id = data.get("cmd_id", "")
                        if cmd_id in self._pending_acks:
                            future = self._pending_acks[cmd_id]
                            if not future.done():
                                future.set_result(data)
                    except json.JSONDecodeError as e:
                        logger.debug(f"ACK parse error: {e}")
                    except (KeyError, TypeError, AttributeError) as e:
                        logger.debug(f"ACK resolve error: {e}")
                else:
                    await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"ACK listener error: {e}")
        finally:
            try:
                await pubsub.unsubscribe(ack_channel)
                await pubsub.close()
            except Exception as _e:
                logger.debug(f"ACK publish failed: {_e}")

    # ------------------------------------------------------------------
    # 便捷方法
    # ------------------------------------------------------------------

    async def start_scanner(self, trade_date: str = "", trade_mode: str = "simulated") -> Optional[dict]:
        """启动扫描 (v2.9.7: 返回ACK结果)"""
        return await self.send_command("start", {
            "trade_date": trade_date,
            "trade_mode": trade_mode,
        })

    async def stop_scanner(self) -> Optional[dict]:
        """停止扫描 (v2.9.7: 返回ACK结果)"""
        return await self.send_command("stop", {})

    async def emergency_liquidate(self, reason: str = "手动") -> Optional[dict]:
        """紧急清仓 (v2.9.7: 返回ACK结果)"""
        return await self.send_command("emergency_liquidate", {"reason": reason})

    async def update_params(self, strategy_id: str, updates: dict) -> Optional[dict]:
        """更新策略参数 (v2.9.7: 返回ACK结果)"""
        return await self.send_command("update_params", {
            "strategy_id": strategy_id,
            "updates": updates,
        })

    async def trigger_scan(self) -> Optional[dict]:
        """手动触发一次扫描 (v2.9.7: 返回ACK结果)"""
        return await self.send_command("scan", {})
