"""
回测引擎节点

作为独立的计算节点运行,通过 RPC 接收回测任务请求。
支持水平扩展,多节点并行执行回测任务。

模块拆分：
- node.py: 节点骨架（启动/停止/RPC注册/任务调度/日志推送）
- ultra_short.py: 超短策略回测执行
- single_stock.py: 单股回测执行 + 行情数据获取
"""

import asyncio
from typing import Optional, Dict
from datetime import datetime
import traceback
# 【修复#33：logger并发安全】Python logging模块本身就是线程安全的
# 因为logging模块内部使用了锁机制（threading.RLock），保证多线程环境下的安全写入
# 本项目使用的logger基于标准logging，天然支持并发安全，不需要额外加锁

from nodes.base import BaseNode
from common.utils import convert_numpy_types
from core.protocols import NodeType
from core.managers import redis_manager, mongo_manager, tushare_manager
from core.utils.logger import logger
from core.managers import baostock_manager, akshare_manager

# 导入拆分后的执行器
from .ultra_short import execute_ultra_short_backtest
from .single_stock import execute_backtest, fetch_price_data


class BacktestNode(BaseNode):
    """
    回测引擎节点

    职责:
    - 接收回测任务请求 (通过 RPC)
    - 执行向量化回测计算
    - 返回绩效分析结果

    特性:
    - 独立计算节点,可水平扩展
    - 支持异步任务执行
    - 任务结果持久化到 MongoDB
    """

    node_type = NodeType.BACKTEST
    DEFAULT_RPC_PORT = 50056  # BacktestNode 默认 RPC 端口

    def __init__(self, node_id: Optional[str] = None, rpc_port: int = 0):
        from core.settings import settings
        # 从 settings 获取端口,如果没有则使用默认值
        port = rpc_port or getattr(settings.rpc, 'backtest_port', self.DEFAULT_RPC_PORT)
        super().__init__(node_id, port)

        # 任务队列
        self._task_queue: asyncio.Queue = asyncio.Queue()
        self._running_tasks: Dict[str, asyncio.Task] = {}

        # 工作协程数(修改为1,避免重复执行同一个任务)
        self._worker_count = 1

        # 日志序号计数器，每个任务独立计数，解决日志乱序问题
        self._log_counters: Dict[str, int] = {}

    async def start(self) -> None:
        """启动回测节点"""
        self.logger.info("Starting Backtest Node...")

        # 初始化管理器
        self.logger.info("Initializing managers...")
        await redis_manager.initialize()
        await mongo_manager.initialize()
        # Tushare初始化加异常保护,失败不影响运行
        try:
            await tushare_manager.initialize()
            self.logger.info("Tushare manager initialized successfully")
        except Exception as e:
            self.logger.warning(f"Tushare manager initialize failed (ignored): {e}, will use AKShare only")

        # 启动 RPC 服务器
        await self._start_rpc_server()

        # 启动工作协程
        self._start_workers()

        self.logger.info(f"Backtest Node started: {self.node_id}")
        self.logger.info(f"RPC listening on port {self._rpc_port}")

    async def stop(self) -> None:
        """停止回测节点"""
        self.logger.info("Stopping Backtest Node...")

        # 取消所有运行中的任务
        for task_id, task in self._running_tasks.items():
            if not task.done():
                task.cancel()
                self.logger.info(f"Cancelled task: {task_id}")

        await super().stop()

    async def run(self) -> None:
        """节点主循环 - 保持节点运行"""
        self.logger.info("Backtest Node is running, waiting for tasks...")

        # 回测节点主要通过 RPC 接收任务,这里只需保持运行
        while self._running:
            await asyncio.sleep(1)

    def _register_rpc_methods(self) -> None:
        """注册 RPC 方法"""
        super()._register_rpc_methods()

        # 注册回测方法
        self.register_rpc_method("run_backtest", self._handle_run_backtest)
        self.register_rpc_method("run_factor_selection", self._handle_run_factor_selection)
        self.register_rpc_method("run_ultra_short_backtest", self._handle_run_ultra_short_backtest)
        self.register_rpc_method("get_task_status", self._handle_get_task_status)
        self.register_rpc_method("cancel_task", self._handle_cancel_task)

    def _start_workers(self) -> None:
        """启动工作协程"""
        for i in range(self._worker_count):
            asyncio.create_task(self._worker_loop(i))
            self.logger.info(f"Started worker {i}")

    async def _worker_loop(self, worker_id: int) -> None:
        """工作协程循环"""
        while True:
            try:
                # 从队列获取任务
                task_info = await self._task_queue.get()
                task_id = task_info["task_id"]
                task_type = task_info.get("task_type", "single_stock")

                self.logger.info(f"[Worker-{worker_id}] Processing {task_type} task: {task_id}")

                try:
                    # 根据任务类型执行不同的回测
                    if task_type == "factor_selection":
                        result = await self._execute_factor_selection(task_info)
                    elif task_type == "ultra_short":
                        result = await execute_ultra_short_backtest(
                            task_info, self._push_log, self.logger, task_id
                        )
                    else:
                        result = await execute_backtest(task_info, self.logger)

                    # 更新任务状态
                    await self._update_task_result(task_id, "completed", result)

                except Exception as e:
                    self.logger.error(f"[Worker-{worker_id}] Task {task_id} failed: {e}")
                    traceback.print_exc()
                    await self._update_task_result(task_id, "failed", error=str(e))
                    continue  # 【修复风险6：任务失败后continue而非return，避免worker永久退出】

                finally:
                    self._task_queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.exception(f"[Worker-{worker_id}] Unexpected error: {e}")

    # ==================== RPC 处理器 ====================

    async def _handle_run_backtest(self, params: dict) -> dict:
        """处理回测 RPC 请求"""
        task_id = params.get("task_id", f"bt_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}")

        self.logger.info(f"Received backtest request: {task_id}")

        # 记录任务
        await mongo_manager.update_one(
            "backtest_tasks",
            {"task_id": task_id},
            {
                "$set": {
                    "task_id": task_id,
                    "status": "queued",
                    "params": params,
                    "node_id": self.node_id,
                    "created_at": datetime.utcnow(),
                }
            },
            upsert=True,
        )

        # 异步执行,加入队列后立即返回
        await self._task_queue.put({"task_id": task_id, **params})

        return {
            "success": True,
            "task_id": task_id,
            "status": "queued",
            "queue_size": self._task_queue.qsize(),
        }

    async def _handle_get_task_status(self, params: dict) -> dict:
        """查询任务状态"""
        task_id = params.get("task_id")
        if not task_id:
            return {"success": False, "error": "task_id is required"}

        record = await mongo_manager.find_one(
            "backtest_tasks",
            {"task_id": task_id},
        )

        if not record:
            return {"success": False, "error": "Task not found"}

        return {
            "success": True,
            "task_id": task_id,
            "status": record.get("status"),
            "created_at": record.get("created_at", "").isoformat() if record.get("created_at") else None,
            "completed_at": record.get("completed_at", "").isoformat() if record.get("completed_at") else None,
            "error": record.get("error"),
        }

    async def _handle_cancel_task(self, params: dict) -> dict:
        """取消任务"""
        task_id = params.get("task_id")
        if not task_id:
            return {"success": False, "error": "task_id is required"}

        # 更新数据库状态
        result = await mongo_manager.update_one(
            "backtest_tasks",
            {"task_id": task_id, "status": {"$in": ["pending", "queued"]}},
            {"$set": {"status": "cancelled", "cancelled_at": datetime.utcnow()}},
        )

        if result.modified_count > 0:
            return {"success": True, "task_id": task_id, "status": "cancelled"}
        else:
            return {"success": False, "error": "Task cannot be cancelled (already running or completed)"}

    async def _handle_run_factor_selection(self, params: dict) -> dict:
        """处理因子选股回测 RPC 请求"""
        task_id = params.get("task_id", f"fs_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}")

        self.logger.info(f"Received factor selection backtest request: {task_id}")

        # 记录任务
        await mongo_manager.update_one(
            "backtest_tasks",
            {"task_id": task_id},
            {
                "$set": {
                    "task_id": task_id,
                    "task_type": "factor_selection",
                    "status": "queued",
                    "params": params,
                    "node_id": self.node_id,
                    "created_at": datetime.utcnow(),
                }
            },
            upsert=True,
        )

        # 加入任务队列
        task_info = {"task_id": task_id, "task_type": "factor_selection", **params}
        await self._task_queue.put(task_info)

        return {
            "success": True,
            "task_id": task_id,
            "status": "queued",
            "queue_size": self._task_queue.qsize(),
        }

    async def _handle_run_ultra_short_backtest(self, params: dict) -> dict:
        """处理超短策略回测 RPC 请求"""
        task_id = params.get("task_id", f"us_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}")

        self.logger.info(f"Received ultra short backtest request: {task_id}")

        # 记录任务
        await mongo_manager.update_one(
            "backtest_tasks",
            {"task_id": task_id},
            {
                "$set": {
                    "task_id": task_id,
                    "status": "queued",
                    "task_type": "ultra_short",
                    "params": params,
                    "node_id": self.node_id,
                    "created_at": datetime.utcnow(),
                    "progress": 0,
                    "logs": [],
                }
            },
            upsert=True,
        )

        # 加入任务队列
        task_info = {"task_id": task_id, "task_type": "ultra_short", **params}
        await self._task_queue.put(task_info)

        return {
            "success": True,
            "task_id": task_id,
            "status": "queued",
            "queue_size": self._task_queue.qsize(),
        }

    # ==================== 执行器 ====================

    async def _execute_factor_selection(self, params: dict) -> dict:
        """执行因子选股回测"""
        task_id = params.get("task_id", "unknown")

        self.logger.info(
            f"[{task_id}] Executing factor selection: "
            f"{params.get('start_date')} ~ {params.get('end_date')}"
        )

        # 更新状态为 running
        await mongo_manager.update_one(
            "backtest_tasks",
            {"task_id": task_id},
            {"$set": {"status": "running", "started_at": datetime.utcnow()}},
        )

        # 构建回测配置
        config = {
            "universe": params.get("universe", "all_a"),
            "start_date": params["start_date"],
            "end_date": params["end_date"],
            "initial_cash": params.get("initial_cash", 1000000),
            "rebalance_freq": params.get("rebalance_freq", "monthly"),
            "top_n": params.get("top_n", 20),
            "weight_method": params.get("weight_method", "equal"),
            "factors": params.get("factors", []),
            "exclude": params.get("exclude", ["st", "new_stock"]),
            "benchmark": params.get("benchmark", "000300.SH"),
        }

        # 执行组合回测
        # 【修复#30：添加超时检测，超时 10 分钟自动标记失败，避免悬挂任务
        import asyncio
        from .factor_selection import PortfolioBacktester
        backtester = PortfolioBacktester()
        try:
            # 超时 600 秒 = 10 分钟
            result = await asyncio.wait_for(backtester.run(config), timeout=600)
        except asyncio.TimeoutError:
            # 超时，标记任务失败
            error_msg = "回测执行超时（超过 10 分钟），任务自动终止"
            self.logger.error(f"[{task_id}] {error_msg}")
            await self._update_task_result(task_id, "failed", error=error_msg)
            return {"success": False, "error": error_msg}

        self.logger.info(
            f"[{task_id}] Factor selection completed: "
            f"return={result.get('performance', {}).get('total_return', 0):.2f}%"
        )

        return result

    # ==================== 日志与持久化 ====================

    async def _push_log(self, task_id: str, log_text: str) -> None:
        """推送日志 - 只走一条路
        
        【修复：日志只走一条路 + MongoDB和Redis内容统一为原始文本】
        
        原则：
        1. logger只写本地文件（带时间戳格式用于排查）
        2. push_log推原始文本到Redis（前端显示）和MongoDB（持久化）
        3. MongoDB和Redis内容完全一致，都是原始文本
        4. WebSocket推送统一带 type 字段
        """
        # 1. 本地文件日志 - 带格式（仅用于本地排查，不对外推送）
        timestamp = datetime.utcnow().strftime('%H:%M:%S')
        self.logger.info(f"[{task_id}] {log_text}")

        # 2. MongoDB保存原始文本
        await mongo_manager.update_one(
            "backtest_tasks",
            {"task_id": task_id},
            {"$push": {"logs": f"[{timestamp}] {log_text}"}},
        )

        # 3. Redis发布原始文本 + 统一带 type 字段
        try:
            await redis_manager.publish(
                "backtest:logs",
                {
                    "task_id": task_id,
                    "type": "log",  # WebSocket推送统一带type字段
                    "log": f"[{timestamp}] {log_text}",  # MongoDB和Redis内容统一
                }
            )
        except Exception as e:
            self.logger.warning(f"Failed to publish log to Redis: {e}")

        # 让出事件循环
        await asyncio.sleep(0)

    async def _update_task_result(
        self,
        task_id: str,
        status: str,
        result: dict = None,
        error: str = None,
    ) -> None:
        """更新任务结果"""
        update_data = {
            "status": status,
            "completed_at": datetime.utcnow(),
        }

        if result:
            # 转换 numpy 类型为 Python 原生类型,避免 MongoDB 序列化错误
            update_data["result"] = convert_numpy_types(result)

        if error:
            update_data["error"] = error

        await mongo_manager.update_one(
            "backtest_tasks",
            {"task_id": task_id},
            {"$set": update_data},
            upsert=True,
        )


# ==================== 启动入口 ====================


async def main():
    """回测节点启动入口"""
    import logging
    from core.logging import setup_logging

    setup_logging()
    _logger = logging.getLogger("backtest_node")

    node = BacktestNode()

    try:
        await node.start()

        # 保持运行
        _logger.info("Backtest Node is running. Press Ctrl+C to stop.")
        while True:
            await asyncio.sleep(3600)

    except KeyboardInterrupt:
        _logger.info("Received shutdown signal")
    finally:
        await node.stop()


if __name__ == "__main__":
    asyncio.run(main())
