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
import signal
import sys
import time
import traceback
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Callable

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
    except Exception as _e:
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
            logger.warning(f"Cannot update params: no scanner instance")

    async def _cmd_scan(self, params: dict, cmd_id: str) -> None:
        """手动触发一次扫描"""
        if self.scanner is not None:
            try:
                self.state = ScannerState.SCANNING
                await self.pub(self.status_channel, {"state": self.state.value, "ts": time.time()})
                # 【v2.9.50:修复方法名run_once→scan_once, 移除hasattr防御】
                from datetime import datetime
                trade_date = datetime.now().strftime("%Y%m%d")
                result = await self.scanner.scan_once(trade_date=trade_date, force=True)
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
        import redis.asyncio as aioredis

        from core.managers import redis_manager
        from core.settings import settings as app_settings

        # 初始化 Redis（子进程需要自己的连接）
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
        self.cmd_list_key = _chan(self.config, "cmd")    # List+ACK
        self.ack_channel = _chan(self.config, "ack")      # ACK确认通道

        logger.info(f"Listening for commands on {self.cmd_list_key} (List+ACK mode)")

        # 启动定时推送
        self._status_task = asyncio.create_task(self.status_pusher())
        self._health_task = asyncio.create_task(self.health_pusher())

        # 主循环: BLPOP消费命令
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

class ScannerDaemon:
    """
    Scanner 独立进程守护

    将 MarketScanner 运行为独立子进程，通过 Redis Pub/Sub IPC。
    作为单例挂在 WebNode 上。

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
    # 命令发送 (v2.9.7: List+ACK)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # 回调注册
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # 内部: 进程启动
    # ------------------------------------------------------------------

    def _start_process(self) -> None:
        """启动子进程"""
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

    # ------------------------------------------------------------------
    # 内部: Redis 订阅 (主进程侧)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # 内部: 看门狗
    # ------------------------------------------------------------------

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
    
    # ==================== Phase4.4: 紧急告警 ====================
    
    async def _send_emergency_alert(self, message: str):
        """重启3次失败→飞书紧急告警+可选紧急减仓"""
        logger.critical(f"[DAEMON_ALERT] {message}")
        
        # 0. Redis告警事件(前端可见)
        try:
            if self._redis_client:
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
    
    async def _emergency_reduce_positions(self):
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
