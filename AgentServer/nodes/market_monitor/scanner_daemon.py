#!/usr/bin/env python3
"""
ScannerDaemon — Scanner 独立进程守护

将 MarketScanner 运行为独立子进程，与 WebNode 进程隔离：
- UI 请求 / 回测 / 数据同步不再阻塞扫描主循环
- GC 停顿不影响超短交易时序
- 子进程崩溃可自动重启（看门狗）

IPC 通过 Redis 实现：
  scanner:cmd      主进程 → 子进程  (List+ACK, 不可丢)
  scanner:ack      子进程 → 主进程  (命令确认, Pub/Sub)
  scanner:status   子进程 → 主进程  (状态推送, 1秒间隔, Pub/Sub)
  scanner:signal   子进程 → 主进程  (信号推送, Redis Stream)
  scanner:position 子进程 → 主进程  (持仓变更, Redis Stream)
  scanner:health   子进程 → 主进程  (看门狗健康状态, Pub/Sub)
"""

from __future__ import annotations

import asyncio
import json
import logging
import multiprocessing
import os
import sys
import time
import traceback
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Any, Dict, Optional, Callable

from nodes.market_monitor.daemon_command_mixin import DaemonCommandMixin  # 【v2.9.68提取到mixin】
from nodes.market_monitor.daemon_subscription_mixin import DaemonSubscriptionMixin  # 【v2.9.68提取到mixin】
from nodes.market_monitor.daemon_watchdog_mixin import DaemonWatchdogMixin  # 【v2.9.68提取到mixin】

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

logger = logging.getLogger("scanner.daemon")


class ScannerState(str, Enum):
    """Scanner 子进程状态"""
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    SCANNING = "scanning"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class ScannerDaemonConfig:
    """ScannerDaemon 配置"""
    cpu_core: int = -1                     # 绑定CPU核心, -1=不绑定
    realtime_priority: bool = False         # 是否设置 SCHED_FIFO
    max_restart_count: int = 3              # 最大自动重启次数
    heartbeat_interval: float = 10.0        # 看门狗心跳间隔(秒)
    ipc_redis_prefix: str = "scanner:"      # Redis频道前缀
    status_push_interval: float = 1.0       # 状态推送间隔(秒)
    health_push_interval: float = 5.0       # 健康推送间隔(秒)
    subprocess_startup_timeout: float = 30.0 # 子进程启动超时(秒)
    restart_cooldown: float = 5.0           # 重启冷却时间(秒)
    max_memory_mb: int = 0                  # 最大内存MB, 0=不限制
    max_cpu_percent: float = 0.0            # 最大CPU%, 0=不限制
    cmd_ack_timeout: float = 10.0           # 命令ACK超时(秒)【v2.9.7】


# ---------------------------------------------------------------------------
# IPC 频道名
# ---------------------------------------------------------------------------

def _chan(cfg: ScannerDaemonConfig, suffix: str) -> str:
    """生成完整频道名"""
    return f"{cfg.ipc_redis_prefix}{suffix}"


# ---------------------------------------------------------------------------
# 子进程入口
# ---------------------------------------------------------------------------

def _scanner_subprocess_main(config_dict: dict) -> None:
    """
    Scanner 子进程入口函数

    在独立进程中运行 asyncio 事件循环 + MarketScanner。
    通过 Redis 与主进程通信(cmd用List+ACK, 其余用Pub/Sub或Stream)。
    """
    config = ScannerDaemonConfig(**config_dict)

    # 设置进程名（方便 top/htop 识别）
    try:
        import setproctitle
        setproctitle.setproctitle("scanner-daemon")
    except ImportError:
        pass

    # CPU 亲和
    if config.cpu_core >= 0:
        try:
            os.sched_setaffinity(0, {config.cpu_core})
            logger.info(f"CPU affinity set to core {config.cpu_core}")
        except (OSError, AttributeError) as e:
            logger.warning(f"Failed to set CPU affinity: {e}")

    # 实时调度优先级
    if config.realtime_priority:
        try:
            param = os.sched_param(50)  # 优先级50(1-99)
            os.sched_setscheduler(0, os.SCHED_FIFO, param)
            logger.info("Set SCHED_FIFO priority 50")
        except (OSError, PermissionError, AttributeError) as e:
            logger.warning(f"Failed to set SCHED_FIFO (need root): {e}")

    # 运行 asyncio 事件循环
    try:
        asyncio.run(_subprocess_async_main(config))
    except Exception:
        logger.critical(f"Scanner subprocess crashed:\n{traceback.format_exc()}")
        sys.exit(1)


class _SubprocessRuntime:
    """子进程运行时 — 封装异步主循环的所有逻辑【v2.9.44提取】
    
    从_subprocess_async_main的303行闭包提取为类,
    每个子功能成为独立的类方法:
    - pub(): Redis发布辅助
    - handle_command(): 命令路由+处理
    - _cmd_start/stop/emergency_liquidate/update_params/scan(): 各命令子handler
    - _run_scanner_loop(): 扫描循环
    - status_pusher/health_pusher(): 定时推送
    - run(): 主循环(BLPOP消费命令)
    """

    def __init__(self, config: ScannerDaemonConfig):
        self.config = config
        self.scanner = None
        self.state = ScannerState.IDLE
        self.scan_task: Optional[asyncio.Task] = None
        self._redis_client = None
        self._status_task: Optional[asyncio.Task] = None
        self._health_task: Optional[asyncio.Task] = None

        # IPC 频道(延迟初始化, 在run()中设置)
        self.cmd_channel: str = ""
        self.status_channel: str = ""
        self.signal_channel: str = ""
        self.position_channel: str = ""
        self.health_channel: str = ""
        self.cmd_list_key: str = ""
        self.ack_channel: str = ""

    # ==================== Redis 发布辅助 ====================

    async def pub(self, channel: str, data: dict) -> None:
        """Redis发布(异常安全)"""
        try:
            await self._redis_client.publish(channel, json.dumps(data, default=str))
        except Exception as e:
            logger.warning(f"Redis publish to {channel} failed: {e}")

    async def _send_ack(self, cmd_id: str, status: str, cmd: str = "") -> None:
        """发送ACK确认【v2.9.44从handle_command提取】"""
        if not cmd_id:
            return
        try:
            payload = {"cmd_id": cmd_id, "status": status, "ts": time.time()}
            if cmd:
                payload["cmd"] = cmd
            await self._redis_client.publish(
                self.ack_channel, json.dumps(payload, default=str)
            )
        except Exception as _e:
            logger.debug(f"ACK publish failed: {_e}")

    # ==================== 命令路由+处理 ====================

    async def handle_command(self, data: dict) -> None:
        """命令路由 — 分发到各子handler【v2.9.44提取, 原闭包handle_command 134行】"""
        cmd = data.get("cmd", "")
        params = data.get("params", {})
        cmd_id = data.get("cmd_id", "")  # 【v2.9.7: 命令唯一ID, 用于ACK】

        logger.info(f"Received command: {cmd} (id={cmd_id}) params={params}")

        # ACK确认 — 收到命令立即回复
        await self._send_ack(cmd_id, "received")

        # 命令路由
        handler = {
            "start": self._cmd_start,
            "stop": self._cmd_stop,
            "emergency_liquidate": self._cmd_emergency_liquidate,
            "update_params": self._cmd_update_params,
            "scan": self._cmd_scan,
        }.get(cmd)

        if handler:
            await handler(params, cmd_id)
        else:
            logger.warning(f"Unknown command: {cmd}")

        # 通用完成ACK(stop已单独发ACK)
        if cmd_id and cmd != "stop":
            await self._send_ack(cmd_id, "done", cmd)

    async def _cmd_start(self, params: dict, cmd_id: str) -> None:
        """启动Scanner"""
        if self.state in (ScannerState.RUNNING, ScannerState.SCANNING):
            await self.pub(self.cmd_channel, {"response": "already_running"})
            return
        self.state = ScannerState.STARTING
        await self.pub(self.status_channel, {"state": self.state.value, "ts": time.time()})

        try:
            from nodes.market_monitor.scanner import MarketScanner
            self.scanner = MarketScanner()
            self.scan_task = asyncio.create_task(
                self._run_scanner_loop(self.scanner, self.config, params)
            )
            self.state = ScannerState.RUNNING
            await self.pub(self.status_channel, {"state": self.state.value, "ts": time.time()})
            logger.info("Scanner started successfully")
        except Exception as e:
            self.state = ScannerState.ERROR
            await self.pub(self.status_channel, {
                "state": self.state.value, "error": str(e), "ts": time.time(),
            })
            logger.error(f"Scanner start failed: {e}\n{traceback.format_exc()}")

    async def _cmd_stop(self, params: dict, cmd_id: str) -> None:
        """停止Scanner"""
        if self.scan_task and not self.scan_task.done():
            self.scan_task.cancel()
            try:
                await self.scan_task
            except asyncio.CancelledError:
                pass
        self.scanner = None
        self.scan_task = None
        self.state = ScannerState.STOPPED
        await self.pub(self.status_channel, {"state": self.state.value, "ts": time.time()})
        # 完成ACK
        await self._send_ack(cmd_id, "done")
        logger.info("Scanner stopped")

    async def _cmd_emergency_liquidate(self, params: dict, cmd_id: str) -> None:
        """紧急清仓"""
        reason = params.get("reason", "未知")
        logger.warning(f"EMERGENCY LIQUIDATE: {reason}")
        if self.scanner is not None:
            try:
                # 【v2.9.50:emergency_liquidate已在v2.9.45添加,移除hasattr防御】
                await self.scanner.emergency_liquidate(reason=reason)
                await self.pub(self.position_channel, {
                    "event": "emergency_liquidate",
                    "reason": reason,
                    "ts": time.time(),
                })
            except Exception as e:
                logger.error(f"Emergency liquidate failed: {e}")
        else:
            logger.warning("No scanner instance for emergency liquidate")

    async def _cmd_update_params(self, params: dict, cmd_id: str) -> None:
        """更新策略参数"""
        strategy_id = params.get("strategy_id", "default")
        updates = params.get("updates", {})
        if self.scanner is not None:
            try:
                # 【v2.9.50:修复方法名update_strategy_params→update_strategy_config, 对齐参数签名】
                self.scanner.update_strategy_config(strategy_key=strategy_id, updates=updates)
                await self.pub(self.status_channel, {
                    "state": self.state.value,
                    "params_updated": strategy_id,
                    "ts": time.time(),
                })
            except Exception as e:
                logger.error(f"Update params failed: {e}")
        else:
            logger.warning("Cannot update params: no scanner instance")

    async def _cmd_scan(self, params: dict, cmd_id: str) -> None:
        """手动触发一次扫描"""
        if self.scanner is not None:
            try:
                self.state = ScannerState.SCANNING
                await self.pub(self.status_channel, {"state": self.state.value, "ts": time.time()})
                # 【v2.9.50:修复方法名run_once→scan_once, 移除hasattr防御】
                from datetime import datetime
                trade_date = datetime.now().strftime("%Y%m%d")
                await self.scanner.scan_once(trade_date=trade_date, force=True)
                await self.pub(self.signal_channel, {
                    "event": "manual_scan",
                    "ts": time.time(),
                })
                self.state = ScannerState.RUNNING
                await self.pub(self.status_channel, {"state": self.state.value, "ts": time.time()})
            except Exception as e:
                logger.error(f"Manual scan failed: {e}")
                self.state = ScannerState.RUNNING
        else:
            logger.warning("Cannot scan: no scanner instance")

    # ==================== Scanner 扫描循环 ====================

    async def _run_scanner_loop(
        self, scanner_instance, cfg: ScannerDaemonConfig, start_params: dict
    ) -> None:
        """运行 Scanner 主循环"""
        try:
            # 【v2.9.50:scanner统一用start()接口,移除hasattr防御】
            await scanner_instance.start(**start_params)
        except asyncio.CancelledError:
            logger.info("Scanner loop cancelled")
            raise
        except Exception as e:
            logger.error(f"Scanner loop error: {e}\n{traceback.format_exc()}")

    # ==================== 定时推送 ====================

    async def status_pusher(self) -> None:
        """定期推送状态"""
        while True:
            await asyncio.sleep(self.config.status_push_interval)
            status_data: Dict[str, Any] = {
                "state": self.state.value,
                "ts": time.time(),
            }
            if self.scanner is not None:
                try:
                    # 【v2.9.50:用get_status()统一接口,移除hasattr链】
                    scanner_status = self.scanner.get_status()
                    if isinstance(scanner_status, dict):
                        status_data.update(scanner_status)
                except Exception as e:
                    status_data["status_error"] = str(e)
            await self.pub(self.status_channel, status_data)

    async def health_pusher(self) -> None:
        """定期推送健康状态"""
        while True:
            await asyncio.sleep(self.config.health_push_interval)
            try:
                import psutil
                proc = psutil.Process(os.getpid())
                health_data = {
                    "pid": os.getpid(),
                    "memory_mb": proc.memory_info().rss / 1024 / 1024,
                    "cpu_pct": proc.cpu_percent(),
                    "threads": proc.num_threads(),
                    "state": self.state.value,
                    "ts": time.time(),
                }
            except ImportError:
                health_data = {
                    "pid": os.getpid(),
                    "state": self.state.value,
                    "ts": time.time(),
                }
            except Exception as e:
                health_data = {"pid": os.getpid(), "error": str(e), "ts": time.time()}
            await self.pub(self.health_channel, health_data)

    # ==================== 主循环 ====================

    async def run(self) -> None:
        """子进程主循环: 初始化Redis + BLPOP消费命令 + 定时推送"""
        await self._init_ipc_channels()

        # 启动定时推送
        self._status_task = asyncio.create_task(self.status_pusher())
        self._health_task = asyncio.create_task(self.health_pusher())

        # 主循环: BLPOP消费命令
        await self._run_command_loop()

    async def _init_ipc_channels(self) -> None:
        """【v2.9.57提取】初始化Redis IPC频道"""
        import redis.asyncio as aioredis
        from core.settings import settings as app_settings

        self._redis_client = aioredis.from_url(
            app_settings.redis.url,
            decode_responses=True,
            max_connections=20,
        )

        # IPC 频道
        self.cmd_channel = _chan(self.config, "cmd")
        self.status_channel = _chan(self.config, "status")
        self.signal_channel = _chan(self.config, "signal")
        self.position_channel = _chan(self.config, "position")
        self.health_channel = _chan(self.config, "health")
        self.cmd_list_key = _chan(self.config, "cmd")
        self.ack_channel = _chan(self.config, "ack")

        logger.info(f"Listening for commands on {self.cmd_list_key} (List+ACK mode)")

    async def _run_command_loop(self) -> None:
        """【v2.9.57提取】BLPOP命令消费主循环"""
        logger.info("Scanner subprocess main loop started (List+ACK mode)")
        try:
            while True:
                try:
                    result = await self._redis_client.blpop(self.cmd_list_key, timeout=1.0)
                    if result is not None:
                        _, raw = result
                        try:
                            data = json.loads(raw)
                            await self.handle_command(data)
                        except json.JSONDecodeError as e:
                            logger.warning(f"Invalid JSON in command: {e}")
                        except Exception as e:
                            logger.error(f"Command handling error: {e}\n{traceback.format_exc()}")
                except (ConnectionError, OSError, TimeoutError) as e:
                    logger.warning(f"BLPOP connection error: {e}")
                    await asyncio.sleep(0.1)
                except Exception as e:
                    if "Timeout" not in str(e):
                        logger.warning(f"BLPOP error: {e}")
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass
        finally:
            self._status_task.cancel()
            self._health_task.cancel()
            if self.scan_task and not self.scan_task.done():
                self.scan_task.cancel()
            await self._redis_client.close()
            logger.info("Scanner subprocess shutdown complete")


async def _subprocess_async_main(config: ScannerDaemonConfig) -> None:
    """子进程内的异步主循环 — 委托给_SubprocessRuntime【v2.9.44重构】"""
    runtime = _SubprocessRuntime(config)
    await runtime.run()


def _signal_to_dict(sig: Any) -> dict:
    """将 ScanSignal 转为字典【v2.9.50:简化hasattr链】"""
    # dataclass是主要路径(ScanSignal)
    if isinstance(sig, dict):
        return sig
    try:
        from dataclasses import asdict as _asdict
        return _asdict(sig)
    except TypeError:
        pass
    if hasattr(sig, "model_dump"):
        return sig.model_dump(mode="json")
    return {k: v for k, v in sig.__dict__.items() if not k.startswith("_")} if hasattr(sig, "__dict__") else {"repr": repr(sig)}


# ---------------------------------------------------------------------------
# ScannerDaemon (主进程侧)
# ---------------------------------------------------------------------------

class ScannerDaemon(
    DaemonCommandMixin,
    DaemonSubscriptionMixin,
    DaemonWatchdogMixin,
):
    """
    Scanner 独立进程守护

    将 MarketScanner 运行为独立子进程，通过 Redis Pub/Sub IPC。
    作为单例挂在 WebNode 上。

    v2.9.68: mixin拆分
    - DaemonCommandMixin: 命令发送+ACK
    - DaemonSubscriptionMixin: Redis订阅+回调
    - DaemonWatchdogMixin: 看门狗+紧急处理

    用法:
        daemon = ScannerDaemon()
        await daemon.start()
        ...
        await daemon.stop()
    """

    _instance: Optional["ScannerDaemon"] = None

    def __init__(self, config: Optional[ScannerDaemonConfig] = None):
        self.config = config or ScannerDaemonConfig()
        self._process: Optional[multiprocessing.Process] = None
        self._state = ScannerState.STOPPED
        self._restart_count = 0
        self._last_start_time: float = 0.0
        self._last_health_ts: float = 0.0
        self._watchdog_task: Optional[asyncio.Task] = None
        self._status_sub_task: Optional[asyncio.Task] = None
        self._signal_sub_task: Optional[asyncio.Task] = None
        self._position_sub_task: Optional[asyncio.Task] = None
        self._health_sub_task: Optional[asyncio.Task] = None
        self._status_callback: Optional[Callable[[dict], None]] = None
        self._signal_callback: Optional[Callable[[dict], None]] = None
        self._position_callback: Optional[Callable[[dict], None]] = None
        self._health_callback: Optional[Callable[[dict], None]] = None
        self._redis_client = None
        self._running = False
        self._pending_acks: Dict[str, asyncio.Future] = {}   # 【v2.9.7: cmd_id → Future】
        self._ack_sub_task: Optional[asyncio.Task] = None     # 【v2.9.7: ACK订阅任务】

    # ------------------------------------------------------------------
    # 单例
    # ------------------------------------------------------------------

    @classmethod
    def get_instance(cls, config: Optional[ScannerDaemonConfig] = None) -> "ScannerDaemon":
        """获取单例"""
        if cls._instance is None:
            cls._instance = cls(config)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（仅测试用）"""
        cls._instance = None

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def start(self) -> bool:
        """启动 Scanner 子进程"""
        if self.is_alive():
            logger.warning("Scanner subprocess already running")
            return True

        logger.info("Starting Scanner subprocess...")

        # 启动 Redis 订阅
        await self._init_redis_subscriptions()

        # 启动子进程
        self._start_process()

        # 启动看门狗
        self._running = True
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())

        # 等待子进程启动
        deadline = time.monotonic() + self.config.subprocess_startup_timeout
        while time.monotonic() < deadline:
            if self._state in (ScannerState.RUNNING, ScannerState.SCANNING, ScannerState.IDLE):
                logger.info(f"Scanner subprocess started, state={self._state.value}")
                return True
            if not self.is_alive():
                logger.error("Scanner subprocess died during startup")
                return False
            await asyncio.sleep(0.5)

        logger.error("Scanner subprocess startup timed out")
        return False

    async def stop(self) -> None:
        """停止 Scanner 子进程【v2.9.56:进程终止提取到_terminate_process】"""
        logger.info("Stopping Scanner subprocess...")
        self._running = False

        # 发送 stop 命令
        await self.send_command("stop", {})

        # 等待子进程退出
        await self._terminate_process()

        # 取消看门狗
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass

        # 取消订阅任务
        for task_attr in ("_status_sub_task", "_signal_sub_task",
                          "_position_sub_task", "_health_sub_task",
                          "_ack_sub_task"):  # 【v2.9.7】
            task = getattr(self, task_attr)
            if task and not task.done():
                task.cancel()

        # 清理 Redis 订阅
        await self._cleanup_redis_subscriptions()

        self._state = ScannerState.STOPPED
        self._process = None
        logger.info("Scanner subprocess stopped")

    async def _terminate_process(self) -> None:
        """等待子进程退出, 不响应则强制终止【v2.9.56从stop()提取】"""
        if not (self._process and self._process.is_alive()):
            return
        self._process.join(timeout=10)
        if self._process.is_alive():
            logger.warning("Scanner subprocess did not exit gracefully, terminating...")
            self._process.terminate()
            self._process.join(timeout=5)
            if self._process.is_alive():
                logger.warning("Force killing Scanner subprocess")
                self._process.kill()
                self._process.join(timeout=3)

    async def restart(self) -> bool:
        """重启 Scanner 子进程"""
        await self.stop()
        await asyncio.sleep(self.config.restart_cooldown)
        self._restart_count = 0  # 手动重启重置计数
        return await self.start()

    def is_alive(self) -> bool:
        """检查子进程是否存活"""
        return self._process is not None and self._process.is_alive()

    @property
    def state(self) -> ScannerState:
        """当前状态"""
        return self._state

    @property
    def pid(self) -> Optional[int]:
        """子进程 PID"""
        if self._process and self._process.is_alive():
            return self._process.pid
        return None

    @property
    def restart_count(self) -> int:
        """已重启次数"""
        return self._restart_count

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        """获取守护进程状态"""
        return {
            "alive": self.is_alive(),
            "pid": self.pid,
            "state": self._state.value,
            "restart_count": self._restart_count,
            "max_restart_count": self.config.max_restart_count,
            "last_start_time": self._last_start_time,
            "last_health_ts": self._last_health_ts,
            "pending_acks": len(self._pending_acks),  # 【v2.9.7】
            "cmd_ack_timeout": self.config.cmd_ack_timeout,  # 【v2.9.7】
            "config": asdict(self.config),
        }


# ---------------------------------------------------------------------------
# WebNode 集成混入
# ---------------------------------------------------------------------------

class ScannerDaemonMixin:
    """
    WebNode 集成混入

    在 WebNode 中混入此混入，即可通过 REST API 和 WebSocket
    与 Scanner 子进程交互。

    用法::

        class MyWebNode(ScannerDaemonMixin, WebNode):
            async def start(self):
                await super().start()
                self.scanner_daemon = ScannerDaemon.get_instance()
                await self.scanner_daemon.start()
    """

    scanner_daemon: Optional[ScannerDaemon] = None

    async def init_scanner_daemon(
        self,
        config: Optional[ScannerDaemonConfig] = None,
    ) -> None:
        """初始化 Scanner 守护进程"""
        self.scanner_daemon = ScannerDaemon.get_instance(config)

        # 注册回调: WebSocket 推送
        self.scanner_daemon.on_status(self._on_scanner_status)
        self.scanner_daemon.on_signal(self._on_scanner_signal)
        self.scanner_daemon.on_position(self._on_scanner_position)
        self.scanner_daemon.on_health(self._on_scanner_health)

        await self.scanner_daemon.start()

    async def shutdown_scanner_daemon(self) -> None:
        """关闭 Scanner 守护进程"""
        if self.scanner_daemon:
            await self.scanner_daemon.stop()

    # ------------------------------------------------------------------
    # 回调: 默认实现（通过 WebSocket 广播）
    # ------------------------------------------------------------------

    def _on_scanner_status(self, data: dict) -> None:
        """状态推送回调"""
        self._ws_broadcast("scanner_status", data)

    def _on_scanner_signal(self, data: dict) -> None:
        """信号推送回调"""
        self._ws_broadcast("scanner_signal", data)

    def _on_scanner_position(self, data: dict) -> None:
        """持仓变更回调"""
        self._ws_broadcast("scanner_position", data)

    def _on_scanner_health(self, data: dict) -> None:
        """健康状态回调"""
        self._ws_broadcast("scanner_health", data)

    def _ws_broadcast(self, event_type: str, data: dict) -> None:
        """通过 WebSocket 广播（由 WebNode 提供 ws_manager）"""
        try:
            # 尝试获取 WebSocket manager
            if hasattr(self, "ws_manager") and self.ws_manager:
                # 非阻塞调用
                import asyncio
                asyncio.create_task(
                    self.ws_manager.broadcast({
                        "type": event_type,
                        "data": data,
                    })
                )
            elif hasattr(self, "_ws_broadcast_internal"):
                self._ws_broadcast_internal(event_type, data)
        except Exception as e:
            logger.debug(f"WebSocket broadcast failed: {e}")


# ---------------------------------------------------------------------------
# 模块级便利函数
# ---------------------------------------------------------------------------

_daemon: Optional[ScannerDaemon] = None


async def get_scanner_daemon(config: Optional[ScannerDaemonConfig] = None) -> ScannerDaemon:
    """获取全局 ScannerDaemon 实例（懒初始化）"""
    global _daemon
    if _daemon is None:
        _daemon = ScannerDaemon(config)
    return _daemon
