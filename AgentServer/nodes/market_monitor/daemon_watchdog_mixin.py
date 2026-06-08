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
        """紧急减仓: 卖出利润最低的50%持仓【v2.9.45提取,v2.9.50接口优化,v2.9.84:daemon模式委托子进程】

        优先通过Redis命令委托子进程执行(daemon模式下scanner在子进程中)。
        如果非daemon模式(无Redis命令通道), 回退到直接操作broker。
        """
        # 【v2.9.84修复】daemon模式下应通过Redis命令委托子进程执行
        # 子进程拥有最新的broker状态, 主进程直接操作可能导致状态不一致
        if await self._try_delegate_emergency_reduce():
            return

        # 回退: 非daemon模式, 直接操作broker
        try:
            from nodes.web.api.scanner_shared import _get_scanner_instance
            scanner = _get_scanner_instance()
            if not scanner:
                return
            # 【v2.9.81修复】get_positions()返回List[Dict]而非Dict,
            # 之前代码把列表当dict调.items()会AttributeError。
            # 同时sell_codes计算后未传给liquidate_positions导致清仓所有持仓。
            positions_list = scanner.get_positions()
            if not positions_list:
                return
            # 按profit_pct排序, 保留利润最高的50%
            sorted_positions = sorted(
                positions_list,
                key=lambda p: p.get("profit_pct", 0),
                reverse=True,
            )
            keep_count = max(1, len(sorted_positions) // 2)
            sell_positions = sorted_positions[keep_count:]
            if sell_positions:
                sold, failed = 0, 0
                for pos_info in sell_positions:
                    ts_code = pos_info.get("ts_code", "")
                    stock_name = pos_info.get("stock_name", ts_code)
                    strategy = pos_info.get("strategy", "")
                    available_qty = pos_info.get("available_qty", 0)
                    current_price = pos_info.get("current_price", 0)
                    if available_qty <= 0 or current_price <= 0:
                        continue
                    try:
                        scanner._broker.update_realtime(ts_code, current_price)
                        ok, msg, order = scanner._broker.place_order(
                            ts_code=ts_code,
                            stock_name=stock_name,
                            side="sell",
                            quantity=available_qty,
                            price=current_price,
                            order_type="market",
                            strategy=strategy,
                            reason="daemon_emergency_reduce",
                        )
                        if ok:
                            sold += 1
                            # 委托RuntimePersistence做卖出后清理
                            rp = scanner._runtime_persistence
                            if rp and order:
                                avg_cost = pos_info.get('avg_cost', 0) or 1
                                sell_profit_pct = (current_price - avg_cost) / avg_cost * 100
                                sell_profit_amount = (current_price - avg_cost) * available_qty
                                await rp.post_sell_cleanup(
                                    type('Pos', (), {
                                        'ts_code': ts_code, 'stock_name': stock_name,
                                        'strategy': strategy, 'available_qty': available_qty,
                                        'avg_cost': pos_info.get('avg_cost', 0),
                                        'current_price': current_price,
                                        'profit_pct': pos_info.get('profit_pct', 0),
                                    })(),
                                    "daemon_emergency_reduce", order, available_qty,
                                    sell_profit_pct, sell_profit_amount,
                                    source="daemon_alert",
                                )
                        else:
                            failed += 1
                    except Exception as e:
                        failed += 1
                        logger.warning(f"[DAEMON_ALERT] 减仓{ts_code}异常: {e}")
                logger.warning(f"[DAEMON_ALERT] 紧急减仓完成: 卖出{sold}只, 失败{failed}只")
        except Exception as e:
            logger.warning(f"[DAEMON_ALERT] 紧急减仓失败: {e}")

    async def _try_delegate_emergency_reduce(self) -> bool:
        """尝试通过Redis命令委托子进程执行紧急减仓【v2.9.84新增】

        daemon模式下scanner运行在子进程中, 主进程直接操作broker会导致状态不一致。
        通过send_command发送emergency_liquidate命令到子进程, 由子进程执行减仓。

        Returns:
            True=成功委托到子进程, False=非daemon模式或委托失败(回退到本地执行)
        """
        try:
            # 检查是否在daemon模式(有Redis命令通道)
            if not hasattr(self, '_redis_client') or not self._redis_client:
                return False
            if not self.is_alive():
                logger.warning("[DAEMON_ALERT] 子进程已停止, 无法委托减仓")
                return False

            # 通过Redis发送emergency_liquidate命令到子进程
            await self.send_command("emergency_liquidate", {
                "reason": f"daemon重启{self._restart_count}次失败,紧急减仓",
            })
            logger.info("[DAEMON_ALERT] 紧急减仓已委托到子进程执行")
            return True
        except Exception as e:
            logger.debug(f"[DAEMON_ALERT] 委托子进程减仓失败,回退到本地: {e}")
            return False
