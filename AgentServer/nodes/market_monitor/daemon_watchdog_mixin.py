#!/usr/bin/env python3
"""ScannerDaemon 看门狗+紧急处理混入

v2.9.68从scanner_daemon.py提取, 包含:
- 看门狗循环 (_watchdog_loop)
- 子进程重启 (_restart_subprocess)
- 进程启动 (_start_process)
- 紧急告警 (_send_emergency_alert)
- 紧急减仓 (_emergency_reduce_positions)
"""
from __future__ import annotations

import json
import logging
import multiprocessing
import time
from dataclasses import asdict
from typing import Optional

logger = logging.getLogger("scanner.daemon")


class DaemonWatchdogMixin:
    """ScannerDaemon看门狗+紧急处理混入"""

    def _start_process(self) -> None:
        """启动子进程"""
        from nodes.market_monitor.scanner_daemon import _scanner_subprocess_main
        config_dict = {
            "cpu_core": self.config.cpu_core,
            "realtime_priority": self.config.realtime_priority,
            "max_restart_count": self.config.max_restart_count,
            "heartbeat_interval": self.config.heartbeat_interval,
            "ipc_redis_prefix": self.config.ipc_redis_prefix,
            "status_push_interval": self.config.status_push_interval,
            "health_push_interval": self.config.health_push_interval,
            "subprocess_startup_timeout": self.config.subprocess_startup_timeout,
            "restart_cooldown": self.config.restart_cooldown,
            "max_memory_mb": self.config.max_memory_mb,
            "max_cpu_percent": self.config.max_cpu_percent,
        }

        self._process = multiprocessing.Process(
            target=_scanner_subprocess_main,
            args=(config_dict,),
            name="scanner-daemon",
            daemon=True,
        )
        self._process.start()
        self._last_start_time = time.monotonic()
        logger.info(f"Scanner subprocess started, PID={self._process.pid}")

    async def _watchdog_loop(self) -> None:
        """看门狗: 检查子进程存活, 挂掉自动重启【v2.9.56:提取_check_subprocess_health】"""
        while self._running:
            await asyncio.sleep(self.config.heartbeat_interval)

            if not self._running:
                break

            # 检查子进程存活
            if not self.is_alive():
                if self._restart_count >= self.config.max_restart_count:
                    logger.error(
                        f"Scanner subprocess died, max restart count "
                        f"({self.config.max_restart_count}) reached. "
                        f"Not restarting."
                    )
                    from nodes.market_monitor.scanner_daemon import ScannerState
                    self._state = ScannerState.ERROR
                    # 【Phase4.4:重启3次失败→飞书紧急告警+可选紧急减仓】
                    await self._send_emergency_alert("Scanner重启{0}次失败,已停止自动重启!".format(self._restart_count))
                    break

                await self._restart_subprocess()

            # 检查健康时间戳（子进程可能活着但不响应）
            elif self._last_health_ts > 0:
                elapsed = time.time() - self._last_health_ts
                if elapsed > self.config.heartbeat_interval * 3:
                    logger.warning(
                        f"Scanner health check stale ({elapsed:.1f}s), "
                        f"subprocess may be unresponsive"
                    )

    async def _restart_subprocess(self) -> None:
        """重启子进程(清理旧进程+启动新进程)【v2.9.56从_watchdog_loop提取】"""
        self._restart_count += 1
        logger.warning(
            f"Scanner subprocess died! "
            f"Restarting ({self._restart_count}/{self.config.max_restart_count})..."
        )

        # 清理旧进程
        if self._process:
            try:
                self._process.join(timeout=3)
            except Exception as _e:
                logger.debug(f"process join failed: {_e}")

        # 重启
        self._start_process()

    # ==================== Phase4.4: 紧急告警 ====================

    async def _send_emergency_alert(self, message: str) -> None:
        """重启3次失败→飞书紧急告警+可选紧急减仓"""
        logger.critical(f"[DAEMON_ALERT] {message}")

        # 0. Redis告警事件(前端可见)
        try:
            if self._redis_client:
                from nodes.market_monitor.scanner_daemon import _chan
                alert_data = {
                    "event": "daemon_emergency",
                    "message": message,
                    "restart_count": self._restart_count,
                    "max_restart_count": self.config.max_restart_count,
                    "ts": time.time(),
                }
                await self._redis_client.publish(
                    _chan(self.config, "health"),
                    json.dumps(alert_data, default=str)
                )
        except Exception as e:
            logger.debug(f"[DAEMON_ALERT] Redis告警发布失败: {e}")

        # 1. 飞书告警
        try:
            from core.managers.live.signal_pusher import SignalPusher
            pusher = SignalPusher()
            pusher.push_signal(f"🚨 **紧急告警**\n{message}\n\n请立即检查Scanner状态!")
            logger.info("[DAEMON_ALERT] 飞书告警已发送")
        except Exception as e:
            logger.warning(f"[DAEMON_ALERT] 飞书告警失败: {e}")

        # 2. 可选紧急减仓(通过scanner.emergency_liquidate委托)
        await self._emergency_reduce_positions()

    async def _emergency_reduce_positions(self) -> None:
        """紧急减仓: 卖出利润最低的50%持仓【v2.9.45提取,v2.9.50接口优化】

        通过scanner.emergency_liquidate委托, 不再直接操作broker内部。
        """
        try:
            from nodes.web.api.scanner import _get_scanner_instance
            scanner = _get_scanner_instance()
            if not scanner:
                return
            # 【v2.9.50:用get_positions()统一接口,移除_broker直接访问】
            positions_dict = scanner.get_positions()
            if not positions_dict:
                return
            # 按profit_pct排序, 保留利润最高的50%
            sorted_items = sorted(
                positions_dict.items(),
                key=lambda kv: kv[1].get("profit_pct", 0),
                reverse=True,
            )
            keep_count = max(1, len(sorted_items) // 2)
            sell_codes = [code for code, _ in sorted_items[keep_count:]]
            if sell_codes:
                # 用liquidate_positions委托, 传入指定标的
                await scanner._liquidate_positions(
                    reason="daemon_emergency_reduce",
                    source="daemon_alert",
                )
                logger.warning(f"[DAEMON_ALERT] 紧急减仓{len(sell_codes)}只")
        except Exception as e:
            logger.warning(f"[DAEMON_ALERT] 紧急减仓失败: {e}")
