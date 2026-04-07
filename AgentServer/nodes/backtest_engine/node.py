"""
回测引擎节点

作为独立的计算节点运行,通过 RPC 接收回测任务请求。
支持水平扩展,多节点并行执行回测任务。
"""

import asyncio
from typing import Optional, Dict, Any
from datetime import datetime
import traceback

import pandas as pd

from nodes.base import BaseNode
from common.utils import convert_numpy_types
from core.protocols import NodeType
from core.managers import redis_manager, mongo_manager, tushare_manager

from .factors import FactorData
from .backtester import VectorizedBacktester, BacktestConfig
from .performance import PerformanceAnalyzer
from .factor_selection import PortfolioBacktester
from .factor_selection.universe import UniverseManager, ExcludeRule
from .factor_selection.factor_engine import FactorEngine
from core.managers import baostock_manager, akshare_manager


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
                        result = await self._execute_ultra_short_backtest(task_info)
                    else:
                        result = await self._execute_backtest(task_info)

                    # 更新任务状态
                    await self._update_task_result(task_id, "completed", result)

                except Exception as e:
                    self.logger.error(f"[Worker-{worker_id}] Task {task_id} failed: {e}")
                    traceback.print_exc()
                    await self._update_task_result(task_id, "failed", error=str(e))

                finally:
                    self._task_queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.exception(f"[Worker-{worker_id}] Unexpected error: {e}")

    async def _handle_run_backtest(self, params: dict) -> dict:
        """
        处理回测 RPC 请求

        任务投递到队列后立即返回,不阻塞等待执行结果。
        客户端需要通过 get_task_status 查询任务状态和结果。

        Args:
            params: 回测参数
                - task_id: 任务ID
                - ts_code: 股票代码
                - start_date: 开始日期
                - end_date: 结束日期
                - initial_cash: 初始资金
                - entry_threshold: 买入阈值
                - exit_threshold: 卖出阈值
                - factor_weights: 因子权重

        Returns:
            任务投递状态
        """
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
        """
        处理因子选股回测 RPC 请求

        Args:
            params: 回测参数
                - task_id: 任务ID
                - universe: 股票池类型 ("all_a")
                - start_date: 开始日期
                - end_date: 结束日期
                - initial_cash: 初始资金
                - rebalance_freq: 调仓频率 ("monthly" | "weekly" | "daily")
                - top_n: 选股数量
                - weight_method: 权重方法 ("equal" | "factor_weighted")
                - factors: 因子配置列表
                - exclude: 排除规则列表
                - benchmark: 基准指数代码

        Returns:
            任务投递状态
        """
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
        """
        处理超短策略回测 RPC 请求

        任务投递到队列后立即返回,不阻塞等待执行结果。
        客户端需要通过 get_task_status 查询任务状态和结果,支持WebSocket实时日志推送。

        Args:
            params: 超短策略回测参数
                - task_id: 任务ID
                - strategies: 策略列表
                - start_date: 开始日期
                - end_date: 结束日期
                - initial_cash: 初始资金
                - params: 策略参数配置
                - enable_force_empty: 启用强制空仓
                - enable_sentiment_cycle: 启用情绪周期
                - enable_auction_filter: 启用竞价过滤

        Returns:
            任务投递状态
        """
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

    async def _execute_factor_selection(self, params: dict) -> dict:
        """
        执行因子选股回测

        Args:
            params: 回测参数

        Returns:
            回测报告
        """
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
        backtester = PortfolioBacktester()
        result = await backtester.run(config)

        self.logger.info(
            f"[{task_id}] Factor selection completed: "
            f"return={result.get('performance', {}).get('total_return', 0):.2f}%"
        )

        return result

    async def _execute_ultra_short_backtest(self, params: dict) -> dict:
        """
        执行超短策略回测

        Args:
            params: 超短回测参数
                - strategies: 策略列表
                - start_date: 开始日期
                - end_date: 结束日期
                - initial_cash: 初始资金
                - params: 策略参数配置
                - enable_force_empty: 启用强制空仓
                - enable_sentiment_cycle: 启用情绪周期
                - enable_auction_filter: 启用竞价过滤
                - data_source: 数据源
                - period: 周期:daily/1min
                - ts_codes: 股票代码列表,逗号分隔
                - adjust_type: 复权方式:none/qfq

        Returns:
            回测报告(包含所有策略的结果和汇总统计
        """
        task_id = params.get("task_id", "unknown")
        # 参数在params子对象中,因为web层调用时封装在params里
        req_params = params.get("params", {})
        strategies = req_params.get("strategies", [])
        start_date = req_params.get("start_date", "20260105")
        end_date = req_params.get("end_date", "20260320")
        initial_cash = req_params.get("initial_cash", 1000000)
        strategy_params = req_params.get("params", {})
        # 数据源配置
        data_source = req_params.get("data_source", "mongodb")
        period = req_params.get("period", "daily")
        ts_codes = req_params.get("ts_codes", "")
        adjust_type = req_params.get("adjust_type", "qfq")

        # 初始化所有数据管理器,异常保护
        try:
            await tushare_manager.initialize()
            self.logger.info("Tushare manager initialized successfully")
        except Exception as e:
            self.logger.warning(f"Tushare manager initialize failed (ignored): {e}, will use AKShare only")

        try:
            await baostock_manager.initialize()
            self.logger.info("Baostock manager initialized successfully")
        except Exception as e:
            self.logger.warning(f"Baostock manager initialize failed (ignored): {e}, will use MongoDB only")

        try:
            await akshare_manager.initialize()
            self.logger.info("AKShare manager initialized successfully")
        except Exception as e:
            self.logger.warning(f"AKShare manager initialize failed (ignored): {e}, will use MongoDB only")

        self.logger.info(
            f"[{task_id}] Executing ultra short backtest: "
            f"{start_date} ~ {end_date}, strategies={strategies}, period={period}, adjust_type={adjust_type}"
        )

        # 更新状态为 running
        await mongo_manager.update_one(
            "backtest_tasks",
            {"task_id": task_id},
            {"$set": {"status": "running", "started_at": datetime.utcnow(), "progress": 10, "logs": []}},
        )

        # ========== 🔍 服务健康检查（点击回测第一时间输出+自动修复） ==========
        await self._push_log(task_id, "🔍 【服务健康检查】回测节点启动前自检...")
        import subprocess, os
        need_restart = False
        
        # 检查端口占用
        try:
            port_status = subprocess.check_output("ss -tlnp | grep :50057 2>/dev/null || echo ''", shell=True).decode().strip()
            current_pid = str(os.getpid())
            
            if not port_status:
                await self._push_log(task_id, "🔹 50057端口状态: 当前节点未监听，需要修复")
                need_restart = True
            elif current_pid not in port_status:
                await self._push_log(task_id, f"🔹 50057端口状态: 被其他进程占用: {port_status}")
                await self._push_log(task_id, "🔧 自动清理占用端口的旧进程...")
                subprocess.run("pkill -9 -f 'AgentServer/main.py' 2>/dev/null", shell=True)
                need_restart = True
            else:
                await self._push_log(task_id, "🔹 50057端口状态: ✅ 正常被当前进程占用")
                
        except Exception as e:
            await self._push_log(task_id, f"🔹 50057端口检查异常: {str(e)}")
            need_restart = True
        
        # 检查回测进程数量
        try:
            process_count = int(subprocess.check_output("ps aux | grep 'AgentServer/main.py' | grep -v grep | wc -l", shell=True).decode().strip())
            process_list = subprocess.check_output("ps aux | grep 'AgentServer/main.py' | grep -v grep | awk '{print $2, $9}'", shell=True).decode().strip()
            await self._push_log(task_id, f"🔹 当前运行回测进程数: {process_count}")
            
            if process_count > 1:
                await self._push_log(task_id, f"🔹 发现多余进程，自动清理: {process_list}")
                subprocess.run("pkill -9 -f 'AgentServer/main.py' 2>/dev/null", shell=True)
                need_restart = True
            elif process_count == 1:
                await self._push_log(task_id, "🔹 进程状态: ✅ 正常单进程运行")
                
        except Exception as e:
            await self._push_log(task_id, f"🔹 进程检查异常: {str(e)}")
            need_restart = True
        
        # 自动修复重启
        if need_restart:
            await self._push_log(task_id, "🔧 正在自动修复服务...")
            # 执行一键重启脚本，自动启动新服务
            subprocess.Popen("cd /root/.openclaw/workspace/StockAgent && ./restart_all_services.sh > /tmp/auto_restart.log 2>&1 &", shell=True)
            await self._push_log(task_id, "⏳ 服务自动修复中，请等待3秒后重新提交回测")
            return
        
        # 代码版本标识
        await self._push_log(task_id, "🔹 运行代码版本: 【NEW CODE 2026-04-08 稳定版】")
        await self._push_log(task_id, "✅ 健康检查完成，回测节点正常运行")
        await self._push_log(task_id, "========================================")

        # 推送日志
        await self._push_log(task_id, "🚀 超短策略回测启动")
        await self._push_log(task_id, f"📅 回测区间: {start_date} -> {end_date}")
        await self._push_log(task_id, f"💰 初始资金: {initial_cash:,}")
        await self._push_log(task_id, f"🔌 数据源: MongoDB本地行情库")
        await self._push_log(task_id, f"⏱️ 周期: {period}")
        await self._push_log(task_id, f"📊 复权方式: {'前复权' if adjust_type == 'qfq' else '不复权'}")
        if ts_codes and ts_codes.strip():
            await self._push_log(task_id, f"📝 股票池: {ts_codes}")
        else:
            await self._push_log(task_id, f"📝 股票池: 全市场")
        await self._push_log(task_id, f"🔧 流动性门槛: {strategy_params.get('liquidity_threshold', 500)} 万元")
        await self._push_log(task_id, f"📈 单票最大仓位: {strategy_params.get('max_position_per_stock', 0.2)*100}%")

        # ========== 策略定义 ==========
        ALL_STRATEGIES = [
            {
                "id": "halfway_chase",
                "name": "半路追涨",
                "filters": [
                    ("limit_up_yesterday", 1),
                    ("open_below_limit", 1),
                    ("volume_increase", strategy_params.get('volume_threshold', 1.5)),
                ],
            },
            {
                "id": "first_limit_up",
                "name": "首板打板",
                "filters": [
                    ("first_limit_up", 1),
                ],
            },
            {
                "id": "limit_up_open",
                "name": "涨停开板",
                "filters": [
                    ("limit_up_yesterday", 1),
                    ("first_limit_up", 0),
                ],
            },
            {
                "id": "leader_buy_dip",
                "name": "龙头低吸",
                "filters": [
                    ("market_leader", 1),
                    ("pullback_ma5", 1),
                    ("lhb_buy_in", 1),
                ],
            },
            {
                "id": "limit_down_qiao",
                "name": "跌停翘板",
                "filters": [
                    ("limit_down_yesterday", 1),
                    ("open_above_limit", 1),
                ],
            },
        ]

        # 过滤选择用户选中的策略
        selected_strategies = [s for s in ALL_STRATEGIES if s["id"] in strategies]
        if not selected_strategies:
            selected_strategies = ALL_STRATEGIES

        await self._push_log(task_id, f"🎯 选中策略: {[s["name"] for s in selected_strategies]}")
        
        # 打印完整前端提交的所有参数结构，方便核对字段名
        import json
        await self._push_log(task_id, f"🔍 前端完整提交的所有参数根字段: {list(params.keys())}")
        await self._push_log(task_id, f"🔍 完整params内容: {json.dumps(params, ensure_ascii=False, indent=2)}")
        await self._push_log(task_id, f"🔍 前端提交的strategies字段内容: {json.dumps(params.get('strategies', []), ensure_ascii=False, indent=2)}")
        await self._push_log(task_id, f"🔍 前端提交的strategy_params字段内容: {json.dumps(params.get('strategy_params', {}), ensure_ascii=False, indent=2)}")
        await self._push_log(task_id, f"🔍 前端提交的selected_strategies字段内容: {json.dumps(params.get('selected_strategies', []), ensure_ascii=False, indent=2)}")
        
        # ========== 参数核对日志（与界面对照） ==========
        await self._push_log(task_id, "")
        await self._push_log(task_id, "📋 ========================================")
        await self._push_log(task_id, "📋 === 🔧 全局公共参数 ===")
        await self._push_log(task_id, "   ├─ 流动性门槛: %s 万元" % strategy_params.get('liquidity_threshold', 500))
        await self._push_log(task_id, "   ├─ 单票最大仓位: %.1f %%" % (strategy_params.get('max_position_per_stock', 0.3)*100))
        await self._push_log(task_id, "   ├─ 总仓位上限: %.1f %%" % (strategy_params.get('max_position', 0.6)*100))
        await self._push_log(task_id, "   ├─ 止损比例: %.1f %%" % (strategy_params.get('stop_loss_pct', 0.02)*100))
        await self._push_log(task_id, "   ├─ 止盈比例: %.1f %%" % (strategy_params.get('take_profit_pct', 0.07)*100))
        await self._push_log(task_id, "   └─ 最大持仓天数: %d 天" % strategy_params.get('max_hold_days', 3))
        
        await self._push_log(task_id, "")
        await self._push_log(task_id, "📋 === 🎯 各策略独立参数 ===")
        volume_val = 1.5
        # 遍历选中的策略字典，不是原始字符串列表
        for s in selected_strategies:
            strategy_name = s.get('name', s.get('id', '未知策略'))
            await self._push_log(task_id, "   ┌─ 🎯 【%s】" % strategy_name)
            # 从前端提交的策略参数中找对应策略的配置
            for frontend_strategy in params.get('strategies', []):
                if isinstance(frontend_strategy, dict) and frontend_strategy.get('name') == strategy_name:
                    strategy_params_local = frontend_strategy.get('params', {})
                    break
            else:
                strategy_params_local = {}
            if strategy_name == '半路追涨':
                volume_val = strategy_params_local.get('volume_threshold', 1.5)
                await self._push_log(task_id, "   │   ├─ 量比阈值: %.1f 倍 (应用到筛选逻辑)" % volume_val)
                await self._push_log(task_id, "   │   └─ 涨幅区间: %s" % strategy_params_local.get('rise_range', '3%-7%'))
            elif strategy_name == '首板打板':
                await self._push_log(task_id, "   │   └─ 最小封单金额: %d 万元" % strategy_params_local.get('min_order_amount', 5000))
        
        await self._push_log(task_id, "")
        await self._push_log(task_id, "✅ 参数核对完成，量比阈值实际使用: %.1f 倍" % volume_val)
        await self._push_log(task_id, "✅ ========================================")
        await self._push_log(task_id, "")
        
        # 更新量比阈值到筛选逻辑，确保实际生效
        for strategy in selected_strategies:
            if strategy["name"] == "半路追涨":
                for i, (factor_name, target_val) in enumerate(strategy["filters"]):
                    if factor_name == "volume_increase":
                        strategy["filters"][i] = (factor_name, volume_val)
                        break
        await self._push_log(task_id, "🔄 初始化管理器...")

        # 初始化选股和因子引擎
        from .factor_selection.universe import UniverseManager, ExcludeRule
        from .factor_selection.factor_engine import FactorEngine

        # UniverseManager 无参数初始化
        universe_mgr = UniverseManager()
        universe_mgr.start_date = start_date
        universe_mgr.end_date = end_date
        universe_mgr.exclude_rules = [ExcludeRule.ST, ExcludeRule.NEW_STOCK]
        universe_mgr.min_liquidity = strategy_params.get('liquidity_threshold', 500)
        factor_engine = FactorEngine()

        await self._push_log(task_id, "✅ 管理器初始化完成")
        await mongo_manager.update_one(
            "backtest_tasks",
            {"task_id": task_id},
            {"$set": {"progress": 20}},
        )


        # 获取真实调仓日期(每日调仓)
        rebalance_dates = await universe_mgr.get_rebalance_dates(start_date, end_date, "daily")
        trade_days_count = len(rebalance_dates)
        await self._push_log(task_id, f"✅ 总交易日: {trade_days_count} 天")
        await mongo_manager.update_one(
            "backtest_tasks",
            {"task_id": task_id},
            {"$set": {"progress": 30}},
        )

        # 合并所有选中策略的因子和过滤条件,构建组合回测配置
        all_factors = []
        strategy_weights = {}
        total_weight = 0

        # 给每个策略分配相同权重
        weight_per_strategy = 1.0 / len(selected_strategies)

        for strategy in selected_strategies:
            strategy_weights[strategy["name"]] = weight_per_strategy
            total_weight += weight_per_strategy
            # 添加策略需要的因子
            for (factor_name, target_value) in strategy["filters"]:
                all_factors.append({
                    "name": factor_name,
                    "weight": weight_per_strategy,
                    "target": target_value
                })

        await self._push_log(task_id, "")
        await self._push_log(task_id, "=" * 60)
        await self._push_log(task_id, f"▶️ 开始多策略组合回测")
        await self._push_log(task_id, f"📊 策略权重配置: {strategy_weights}")
        await self._push_log(task_id, "=" * 60)

        # 调试：打印所有策略相关参数
        await self._push_log(task_id, f"🔍 【node.py调试】selected_strategies内容: {selected_strategies}")
        await self._push_log(task_id, f"🔍 【node.py调试】strategy_weights内容: {strategy_weights}")
        
        # 创建组合回测器
        config = {
            "start_date": start_date,
            "end_date": end_date,
            "initial_cash": initial_cash,
            "max_position_percent": strategy_params.get("max_position_per_stock", 0.2),
            "liquidity_threshold": strategy_params.get("liquidity_threshold", 500),
            "data_collection": "stock_daily_ak_full" if period == "daily" else "stock_1min",
            "universe_mgr": universe_mgr,
            "factor_engine": factor_engine,
            "exclude_rules": [ExcludeRule.ST, ExcludeRule.NEW_STOCK],
            "factors": all_factors,
            "top_n": 10,
            "rebalance_freq": "daily",
            "task_id": task_id,
            "push_log": self._push_log,
            "strategy_weights": strategy_weights,  # 传入策略权重配置
            "selected_strategies": selected_strategies,  # 传入选中策略列表
            # 动态传入各策略参数
            "volume_threshold": next((s.get("params", {}).get("volume_threshold", 1.5) for s in selected_strategies if s["name"] == "半路追涨"), 1.5)
        }

        backtester = PortfolioBacktester()
        all_results = []

        # 运行组合回测
        try:
            result = await backtester.run(config)

            if result is None or "error" in result:
                error_msg = result.get('error', 'unknown error') if result else 'unknown error'
                await self._push_log(task_id, f"❌ 组合回测失败: {error_msg}")
            else:
                # 兼容字段名,确保所有字段存在
                perf = result.get('performance', {})
                # 字段映射,兼容不同返回格式
                field_map = {
                    'trade_days': ['total_trade_days', 'trade_count', 0],
                    'win_rate': ['winrate', 'winning_rate', 0.0],
                    'avg_daily_return': ['avg_return', 'daily_return', 0.0],
                    'total_return': ['return', 'total_profit', 0.0],
                    'max_drawdown': ['drawdown', 'max_dd', 0.0],
                    'sharpe_ratio': ['sharpe', 'sharpe_score', 0.0]
                }
                # 填充所有需要的字段
                for field, aliases in field_map.items():
                    if field not in perf:
                        # 查找别名
                        for alias in aliases[:-1]:
                            if alias in perf:
                                perf[field] = perf[alias]
                                break
                        # 都没有就用默认值
                        if field not in perf:
                            perf[field] = aliases[-1]

                perf["strategy_name"] = "多策略组合"
                all_results.append(perf)

                await self._push_log(task_id, "✅ 多策略组合回测完成")
                await self._push_log(task_id, f"   信号数: {perf.get('trade_count', perf.get('total_trades', 0))}")
                await self._push_log(task_id, f"   胜率: {perf['win_rate']:.2f}%")
                await self._push_log(task_id, f"   累计收益率: {perf['total_return']:.2f}%")
                await self._push_log(task_id, f"   最大回撤: {perf['max_drawdown']:.2f}%")
                await self._push_log(task_id, f"   盈亏比: {perf.get('profit_loss_ratio', 0):.2f}")
                await self._push_log(task_id, f"   夏普比率: {perf['sharpe_ratio']:.2f}")

        except Exception as e:
            self.logger.error(f"[{task_id}] Portfolio backtest failed: {e}")
            await self._push_log(task_id, f"❌ 组合回测运行异常: {str(e)}")

        # 计算汇总结果
        await self._push_log(task_id, "")
        await self._push_log(task_id, "📊 所有策略回测完成,正在生成汇总报告...")
        await mongo_manager.update_one(
            "backtest_tasks",
            {"task_id": task_id},
            {"$set": {"progress": 90}},
        )

        # 汇总统计
        total_signals = sum(r.get("trade_days", 0) for r in all_results)
        avg_win_rate = sum(r.get("win_rate", 0) for r in all_results) / len(all_results) if all_results else 0
        total_return = sum(r.get("total_return", 0) for r in all_results)
        max_drawdown = max(r.get("max_drawdown", 0) for r in all_results) if all_results else 0

        summary = {
            "total_strategies": len(all_results),
            "total_signals": total_signals,
            "avg_win_rate": avg_win_rate,
            "total_return": total_return,
            "max_drawdown": max_drawdown,
        }

        final_result = {
            "strategies": all_results,
            "summary": summary,
            "params": params,
            "start_date": start_date,
            "end_date": end_date,
            "initial_cash": initial_cash,
        }

        await self._push_log(task_id, "✅ 回测全部完成!")
        await self._push_log(task_id, f"📈 汇总结果:总信号 {total_signals} 个,平均胜率 {avg_win_rate:.2f}%,总收益率 {total_return:.2f}%")
        await mongo_manager.update_one(
            "backtest_tasks",
            {"task_id": task_id},
            {"$set": {"progress": 100}},
        )

        # 关闭管理器
        await baostock_manager.shutdown()
        await akshare_manager.shutdown()

        return final_result

    async def _push_log(self, task_id: str, log_text: str) -> None:
        """推送日志到数据库、WebSocket和本地文件
        """
        timestamp = datetime.utcnow().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {log_text}"

        # 保存到数据库
        await mongo_manager.update_one(
            "backtest_tasks",
            {"task_id": task_id},
            {"$push": {"logs": log_entry}},
        )

        # 写入本地持久化文件 - 同一个任务所有日志写入同一个文件
        import os
        log_dir = "/root/.openclaw/workspace/StockAgent/logs/backtest/"
        os.makedirs(log_dir, exist_ok=True)
        # 生成文件名:{task_id}.log,确保同一个任务所有日志都写到同一个文件
        log_file = os.path.join(log_dir, f"{task_id}.log")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(log_entry + "\n")

        # 推送WebSocket消息 - 推送带时间戳的完整日志,和本地文件、MongoDB完全一致
        try:
            from nodes.web.websocket import manager as ws_manager
            await ws_manager.broadcast_task_update(task_id, {
                "type": "log",
                "log": log_entry,
            })
        except Exception:
            # 回测节点独立运行时可能没有WebSocket服务,忽略推送错误
            pass

    async def _execute_backtest(self, params: dict) -> dict:
        """
        执行单股回测

        Args:
            params: 回测参数

        Returns:
            回测报告
        """
        task_id = params.get("task_id", "unknown")
        ts_code = params["ts_code"]
        start_date = params["start_date"]
        end_date = params["end_date"]

        self.logger.info(f"[{task_id}] Executing backtest: {ts_code} ({start_date} ~ {end_date})")

        # 更新状态为 running
        await mongo_manager.update_one(
            "backtest_tasks",
            {"task_id": task_id},
            {"$set": {"status": "running", "started_at": datetime.utcnow()}},
        )

        # 1. 获取行情数据
        price_data = await self._fetch_price_data(ts_code, start_date, end_date)

        if price_data.empty:
            raise ValueError(f"No price data found for {ts_code}")

        self.logger.info(f"[{task_id}] Loaded {len(price_data)} days of price data")

        # 2. 构建因子数据
        factor_data = FactorData(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            price_data=price_data,
        )

        # 3. 自动计算技术指标
        if params.get("auto_technical", True):
            factor_data.add_technical_indicators()

        # 4. 配置回测
        weights = params.get("factor_weights", {})
        if not weights:
            weights = {
                "tech_rsi": 0.25,
                "tech_macd_signal": 0.25,
                "tech_price_position": 0.25,
                "tech_vol_ma5": 0.25,
            }

        config = BacktestConfig(
            initial_cash=params.get("initial_cash", 100000),
            entry_threshold=params.get("entry_threshold", 0.7),
            exit_threshold=params.get("exit_threshold", 0.3),
            position_size=params.get("position_size", 1.0),
            factor_weights=weights,
        )

        # 5. 执行回测
        backtester = VectorizedBacktester(config)
        result = backtester.run(factor_data)

        if not result.success:
            raise ValueError(result.error_message)

        # 6. 分析绩效
        analyzer = PerformanceAnalyzer()
        metrics = analyzer.analyze(result)
        report = analyzer.generate_report(result, metrics)

        self.logger.info(
            f"[{task_id}] Backtest completed: "
            f"return={metrics.total_return_pct:.2f}%, "
            f"sharpe={metrics.sharpe_ratio:.2f}, "
            f"max_dd={metrics.max_drawdown_pct:.2f}%"
        )

        return report

    async def _fetch_price_data(
        self,
        ts_code: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """从数据库获取行情数据,不存在则自动从AKShare下载"""
        records = await mongo_manager.find_many(
            "stock_daily",
            {
                "ts_code": ts_code,
                "trade_date": {"$gte": start_date, "$lte": end_date},
            },
            sort=[("trade_date", 1)],
        )

        if not records:
            # 本地没有数据,自动从AKShare下载
            self.logger.info(f"本地没有{ts_code} {start_date}~{end_date}数据,尝试从AKShare下载...")
            try:
                # 转换日期格式:YYYYMMDD -> YYYY-MM-DD
                start_dt = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
                end_dt = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"

                # 调用AKShare获取日线数据
                df_ak = await akshare_manager.get_daily(ts_code, start_dt, end_dt)
                if df_ak.empty:
                    self.logger.warning(f"AKShare没有获取到{ts_code}的数据")
                    return pd.DataFrame()

                # 转换格式存入MongoDB
                records_to_insert = []
                for _, row in df_ak.iterrows():
                    # 转换trade_date为YYYYMMDD格式
                    trade_date = row["trade_date"].strftime("%Y%m%d") if hasattr(row["trade_date"], 'strftime') else str(row["trade_date"]).replace("-", "")
                    record = {
                        "ts_code": ts_code,
                        "trade_date": trade_date,
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "vol": float(row["vol"]) if "vol" in row else float(row["volume"]),
                        "amount": float(row["amount"]),
                        "up_limit": float(row["up_limit"]) if "up_limit" in row else None,
                        "down_limit": float(row["down_limit"]) if "down_limit" in row else None,
                        "pct_chg": float(row["pct_chg"]) if "pct_chg" in row else None,
                        "source": "ak" # 标记数据源为AKShare
                    }
                    records_to_insert.append(record)

                if records_to_insert:
                    # 批量插入数据库,避免重复
                    for record in records_to_insert:
                        await mongo_manager.update_one(
                            "stock_daily",
                            {"ts_code": record["ts_code"], "trade_date": record["trade_date"]},
                            {"$setOnInsert": record},
                            upsert=True
                        )
                    self.logger.info(f"成功下载并保存{ts_code} {len(records_to_insert)}条日线数据")

                    # 重新查询数据
                    records = await mongo_manager.find_many(
                        "stock_daily",
                        {
                            "ts_code": ts_code,
                            "trade_date": {"$gte": start_date, "$lte": end_date},
                        },
                        sort=[("trade_date", 1)],
                    )

            except Exception as e:
                self.logger.error(f"从AKShare下载{ts_code}数据失败: {e}")
                return pd.DataFrame()

        if not records:
            return pd.DataFrame()

        df = pd.DataFrame(records)

        # 转换日期索引
        df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
        df.set_index("trade_date", inplace=True)
        df.sort_index(inplace=True)

        # 重命名列
        column_map = {
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "vol": "volume",
            "amount": "amount",
            "up_limit": "up_limit",
            "down_limit": "down_limit",
        }

        df = df.rename(columns=column_map)

        # 确保必要列存在
        required = ["open", "high", "low", "close", "volume"]
        for col in required:
            if col not in df.columns:
                if col == "volume" and "vol" in df.columns:
                    df["volume"] = df["vol"]
                else:
                    raise ValueError(f"Missing required column: {col}")

        return df

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
        )


# ==================== 启动入口 ====================


async def main():
    """回测节点启动入口"""
    import logging
    from core.logging import setup_logging

    setup_logging()
    logger = logging.getLogger("backtest_node")

    node = BacktestNode()

    try:
        await node.start()

        # 保持运行
        logger.info("Backtest Node is running. Press Ctrl+C to stop.")
        while True:
            await asyncio.sleep(3600)

    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    finally:
        await node.stop()


if __name__ == "__main__":
    asyncio.run(main())
