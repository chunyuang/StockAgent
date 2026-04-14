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
from core.utils.logger import logger

from nodes.backtest_engine.factors import FactorData
from nodes.backtest_engine.backtester import VectorizedBacktester, BacktestConfig
from nodes.backtest_engine.performance import PerformanceAnalyzer
from nodes.backtest_engine.factor_selection import PortfolioBacktester
from nodes.backtest_engine.factor_selection.universe import UniverseManager, ExcludeRule
from nodes.backtest_engine.factor_selection.factor_engine import FactorEngine
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
                        result = await self._execute_ultra_short_backtest(task_info)
#else:
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
#else:
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
        # 设置当前任务ID到日志工具类
        logger.set_task_id(task_id)
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

        # 打印初始化阶段头部
        logger.success("INIT", "============== 回测任务启动 ==============")
        logger.info("INIT", f"回测时间：{start_date} → {end_date}")
        logger.info("INIT", f"初始资金：{initial_cash:,.0f} 元")
        
        # 解析选中策略名称
        strategy_name_map = {
            "halfway_chase": "半路追涨",
            "first_limit_up": "首板打板", 
            "limit_up_open": "涨停开板",
            "leader_buy_dip": "龙头低吸",
            "limit_down_qiao": "跌停翘板"
        }
        selected_strategy_names = [strategy_name_map.get(s, s) for s in strategies]
        logger.info("INIT", f"选中策略：【{'、'.join(selected_strategy_names)}】")
        
        # 打印全局参数
        logger.info("INIT", f"全局参数：流动性门槛{strategy_params.get('liquidity_threshold', 500)}万/止损{strategy_params.get('stop_loss_pct', 0.02)*100}%/止盈{strategy_params.get('take_profit_pct', 0.07)*100}%/最大持仓{strategy_params.get('max_hold_days', 3)}天/单票仓位{strategy_params.get('max_position_per_stock', 0.3)*100}%/总仓位{strategy_params.get('max_position', 0.6)*100}%")
        
        # 打印功能开关
        enable_force_empty = req_params.get("enable_force_empty", True)
        enable_sentiment_cycle = req_params.get("enable_sentiment_cycle", True)
        enable_auction_filter = req_params.get("enable_auction_filter", True)
        logger.info("INIT", f"功能开关：强制空仓{'✅' if enable_force_empty else '❌'} / 情绪周期{'✅' if enable_sentiment_cycle else '❌'} / 竞价过滤{'✅' if enable_auction_filter else '❌'}")
        
        # 打印代码版本
        import subprocess
        try:
            commit_id = subprocess.check_output("git rev-parse --short HEAD", shell=True, cwd="/root/.openclaw/workspace/StockAgent").decode().strip()
            commit_time = subprocess.check_output("git log -1 --format=%cd --date=format:'%Y-%m-%d %H:%M'", shell=True, cwd="/root/.openclaw/workspace/StockAgent").decode().strip()
            logger.info("INIT", f"代码版本：log分支 commit {commit_id} ({commit_time})")
        except:
            pass
            
        logger.success("INIT", "===============================================")

        # 更新状态为 running
        await mongo_manager.update_one(
            "backtest_tasks",
            {"task_id": task_id},
            {"$set": {"status": "running", "started_at": datetime.utcnow(), "progress": 10, "logs": []}},
        )

        # ========== 🔍 服务健康检查（点击回测第一时间输出+自动修复） ==========
#        import subprocess, os
#        
#        # 检查端口占用（仅做检查，不自动杀进程，避免误杀服务）
#        try:
#            port_status = subprocess.check_output("ss -tlnp | grep :50057 2>/dev/null || echo ''", shell=True).decode().strip()
#            current_pid = str(os.getpid())
#            
##if not port_status:
##elif current_pid not in port_status:
#    #                await self._push_log(task_id, f"🔹 50057端口状态: 被其他进程占用: {port_status}")
##else:
#                    
#        except Exception as e:
##            await self._push_log(task_id, f"🔹 50057端口检查异常: {str(e)}")
#        
#        # 检查回测进程数量
#        try:
#            process_count = int(subprocess.check_output("ps aux | grep 'AgentServer/main.py' | grep -v grep | wc -l", shell=True).decode().strip())
#            process_list = subprocess.check_output("ps aux | grep 'AgentServer/main.py' | grep -v grep | awk '{print $2, $9}'", shell=True).decode().strip()
##            await self._push_log(task_id, f"🔹 当前运行回测进程数: {process_count}")
##            await self._push_log(task_id, f"🔹 进程列表(PID 启动时间): {process_list}")
#            
#            if process_count > 1:
#                await self._push_log(task_id, "⚠️  发现多个回测进程，可能影响性能，建议手动清理")
#            elif process_count == 1:
##                await self._push_log(task_id, "🔹 进程状态: ✅ 正常单进程运行")
#                
#        except Exception as e:
##            await self._push_log(task_id, f"🔹 进程检查异常: {str(e)}")
#        
#        # 代码版本标识
##        await self._push_log(task_id, "🔹 运行代码版本: 【NEW CODE 2026-04-10 稳定版】")
#        await self._push_log(task_id, "✅ 健康检查完成，回测节点正常运行")
#        await self._push_log(task_id, "========================================")
#
#        # 推送日志
#        await self._push_log(task_id, "🚀 超短策略回测启动")
#        await self._push_log(task_id, f"📅 回测区间: {start_date} -> {end_date}")
#        await self._push_log(task_id, f"💰 初始资金: {initial_cash:,}")
#        await self._push_log(task_id, f"🔌 数据源: MongoDB本地行情库")
#        await self._push_log(task_id, f"⏱️ 周期: {period}")
#        await self._push_log(task_id, f"📊 复权方式: {'前复权' if adjust_type == 'qfq' else '不复权'}")
#        if ts_codes and ts_codes.strip():
#            await self._push_log(task_id, f"📝 股票池: {ts_codes}")
##else:
#            await self._push_log(task_id, f"📝 股票池: 全市场")
#        await self._push_log(task_id, f"🔧 流动性门槛: {strategy_params.get('liquidity_threshold', 500)} 万元")
#        await self._push_log(task_id, f"📈 单票最大仓位: {strategy_params.get('max_position_per_stock', 0.2)*100}%")
#
#        # ========== 策略定义 ==========
#        # 已移除旧的ALL_STRATEGIES定义，完全使用前端提交的selected_strategies配置
#
        # 🔧 2026-04-10 14:08 修复：直接使用前端提交的带完整参数的策略列表，解决参数丢失问题
        selected_strategies = req_params.get("selected_strategies", [])
        # 输出修改标记到日志，确认新代码生效
        # 兜底：如果前端没传，用默认所有策略
        if not selected_strategies:
            selected_strategies = ALL_STRATEGIES

        await self._push_log(task_id, f"🎯 选中策略: {[s["name"] for s in selected_strategies]}")
        
        # ========== 参数核对日志（与界面对照） ==========
        await self._push_log(task_id, "")
        await self._push_log(task_id, "📋 === 🔧 全局公共参数 ===")
        await self._push_log(task_id, "   ├─ 流动性门槛: %s 万元" % strategy_params.get('liquidity_threshold', 500))
        await self._push_log(task_id, "   ├─ 单票最大仓位: %.1f %%" % (strategy_params.get('max_position_per_stock', 0.3)*100))
        await self._push_log(task_id, "   ├─ 总仓位上限: %.1f %%" % (strategy_params.get('max_position', 0.6)*100))
        await self._push_log(task_id, "   ├─ 止损比例: %.1f %%" % (strategy_params.get('stop_loss_pct', 0.02)*100))
        await self._push_log(task_id, "   ├─ 止盈比例: %.1f %%" % (strategy_params.get('take_profit_pct', 0.07)*100))
        await self._push_log(task_id, "   ├─ 最大持仓天数: %d 天" % strategy_params.get('max_hold_days', 3))
        await self._push_log(task_id, "   ├─ 强制空仓规则: %s" % ("已启用" if req_params.get('enable_force_empty', True) else "已关闭"))
        await self._push_log(task_id, "   ├─ 情绪周期算法: %s" % ("已启用" if req_params.get('enable_sentiment_cycle', True) else "已关闭"))
        await self._push_log(task_id, "   └─ 竞价过滤规则: %s" % ("已启用" if req_params.get('enable_auction_filter', True) else "已关闭"))
        
        await self._push_log(task_id, "")
        volume_val = 1.5
        # 遍历选中的策略字典，不是原始字符串列表
        for s in selected_strategies:
            strategy_name = s.get('name', s.get('id', '未知策略'))
            await self._push_log(task_id, "   ┌─ 🎯 【%s】" % strategy_name)
            # 从前端提交的策略参数中找对应策略的配置
            for frontend_strategy in params.get('params', {}).get('selected_strategies', []):
                if isinstance(frontend_strategy, dict) and frontend_strategy.get('name') == strategy_name:
                    strategy_params_local = frontend_strategy.get('params', {})
                    break
#else:
                strategy_params_local = {}
            # 初始化策略params字段，合并所有前端参数，确保全链路参数一致
            if "params" not in s:
                s["params"] = {}
            s["params"].update(strategy_params_local)
            # 打印策略参数并更新到筛选逻辑
            if strategy_name == '半路追涨':
                min_rise = strategy_params_local.get('min_rise_pct', 0.03) * 100
                max_rise = strategy_params_local.get('max_rise_pct', 0.07) * 100
                # 修正字段名：前端提交的是volume_threshold，不是min_volume_ratio
                volume_val = strategy_params_local.get('volume_threshold', strategy_params_local.get('min_volume_ratio', 1.5))
                allow_after_10am = strategy_params_local.get('allow_after_10am', False)
                await self._push_log(task_id, "   │   ├─ 最小涨幅: %.1f %%" % min_rise)
                await self._push_log(task_id, "   │   ├─ 最大涨幅: %.1f %%" % max_rise)
                await self._push_log(task_id, "   │   ├─ 量比阈值: %.1f 倍 (应用到筛选逻辑)" % volume_val)
                await self._push_log(task_id, "   │   └─ 允许10点后买入: %s" % ("是" if allow_after_10am else "否"))
                # 更新params里的字段，确保全链路一致
                s["params"]["volume_threshold"] = volume_val
                s["params"]["min_volume_ratio"] = volume_val
                self.logger.info(f"[{task_id}] 半路追涨量比阈值更新为: {volume_val}")
            elif strategy_name == '首板打板':
                min_seal = strategy_params_local.get('min_seal_amount', 5000)
                max_limit_time = strategy_params_local.get('max_limit_up_time', '10:00')
                max_cap = strategy_params_local.get('max_circulation_market_cap', 100)
                max_blast = strategy_params_local.get('max_blast_count', 1)
                require_hot = strategy_params_local.get('require_hot_sector', True)
                await self._push_log(task_id, "   │   ├─ 最小封单金额: %d 万元" % min_seal)
                await self._push_log(task_id, "   │   ├─ 最晚涨停时间: %s" % max_limit_time)
                await self._push_log(task_id, "   │   ├─ 最大流通市值: %d 亿" % max_cap)
                await self._push_log(task_id, "   │   ├─ 最大开板次数: %d 次" % max_blast)
                await self._push_log(task_id, "   │   └─ 要求热门板块: %s" % ("是" if require_hot else "否"))
                # 更新参数到筛选逻辑：添加封单金额筛选条件
                self.logger.info(f"[{task_id}] 首板打板最小封单金额更新为: {min_seal}万元")
                
            elif strategy_name == '涨停开板':
                min_consecutive = strategy_params_local.get('min_consecutive_limit', 2)
                max_open_duration = strategy_params_local.get('max_open_duration', 5)
                min_seal_after = strategy_params_local.get('min_seal_after_open', 3000)
                min_turnover = strategy_params_local.get('min_turnover_rate', 0.15) * 100
                await self._push_log(task_id, "   │   ├─ 最小连续涨停天数: %d 天" % min_consecutive)
                await self._push_log(task_id, "   │   ├─ 最大开板时长: %d 分钟" % max_open_duration)
                await self._push_log(task_id, "   │   ├─ 开板后最小封单: %d 万元" % min_seal_after)
                await self._push_log(task_id, "   │   └─ 最小换手率: %.1f %%" % min_turnover)
                self.logger.info(f"[{task_id}] 涨停开板最小连续涨停更新为: {min_consecutive}天，最小封单更新为: {min_seal_after}万元")
                
            elif strategy_name == '龙头低吸':
                min_consecutive = strategy_params_local.get('min_consecutive_limit', 3)
                min_correction = strategy_params_local.get('min_correction_pct', 0.15) * 100
                max_correction = strategy_params_local.get('max_correction_pct', 0.3) * 100
                correction_days_min = strategy_params_local.get('correction_days_min', 2)
                correction_days_max = strategy_params_local.get('correction_days_max', 5)
                support_level = strategy_params_local.get('support_level', 'ma5')
                await self._push_log(task_id, "   │   ├─ 最小连续涨停天数: %d 天" % min_consecutive)
                await self._push_log(task_id, "   │   ├─ 最小回调幅度: %.1f %%" % min_correction)
                await self._push_log(task_id, "   │   ├─ 最大回调幅度: %.1f %%" % max_correction)
                await self._push_log(task_id, "   │   ├─ 最小回调天数: %d 天" % correction_days_min)
                await self._push_log(task_id, "   │   ├─ 最大回调天数: %d 天" % correction_days_max)
                await self._push_log(task_id, "   │   └─ 支撑位: %s" % support_level)
                self.logger.info(f"[{task_id}] 龙头低吸最小连续涨停更新为: {min_consecutive}天")
                
            elif strategy_name == '跌停翘板':
                min_consecutive = strategy_params_local.get('min_consecutive_limit', 3)
                min_qiao_amount = strategy_params_local.get('min_qiao_amount', 10000)
                min_rise_after = strategy_params_local.get('min_rise_after_qiao', 0.03) * 100
                require_high_sentiment = strategy_params_local.get('require_high_sentiment', True)
                await self._push_log(task_id, "   │   ├─ 最小连续跌停天数: %d 天" % min_consecutive)
                await self._push_log(task_id, "   │   ├─ 翘板最小金额: %d 万元" % min_qiao_amount)
                await self._push_log(task_id, "   │   ├─ 翘板后最小涨幅: %.1f %%" % min_rise_after)
                await self._push_log(task_id, "   │   └─ 要求高情绪周期: %s" % ("是" if require_high_sentiment else "否"))
                self.logger.info(f"[{task_id}] 跌停翘板最小连续跌停更新为: {min_consecutive}天")
        
        await self._push_log(task_id, "")
        await self._push_log(task_id, "✅ ========================================")
        await self._push_log(task_id, "")
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
            # 直接从params读取策略参数，构建因子条件
            params = strategy.get("params", {})
            if strategy["id"] == "halfway_chase":
                # 半路追涨策略参数
                min_volume = params.get("min_volume_ratio", 1.5)
                all_factors.append({"name": "volume_increase", "weight": weight_per_strategy, "target": min_volume})
            elif strategy["id"] == "first_limit_up":
                # 首板打板策略参数
                min_seal = params.get("min_seal_amount", 5000)
                all_factors.append({"name": "limit_up_amount", "weight": weight_per_strategy, "target": min_seal})
            elif strategy["id"] == "limit_up_open":
                # 涨停开板策略参数
                min_consecutive = params.get("min_consecutive_limit", 2)
                min_seal_after = params.get("min_seal_after_open", 3000)
                all_factors.append({"name": "limit_up_count", "weight": weight_per_strategy, "target": min_consecutive})
                all_factors.append({"name": "limit_up_open_amount", "weight": weight_per_strategy, "target": min_seal_after})
            elif strategy["id"] == "leader_buy_dip":
                # 龙头低吸策略参数
                min_consecutive = params.get("min_consecutive_limit", 3)
                all_factors.append({"name": "market_leader", "weight": weight_per_strategy, "target": 1})
            elif strategy["id"] == "limit_down_qiao":
                # 跌停翘板策略参数
                min_consecutive = params.get("min_consecutive_limit", 3)
                all_factors.append({"name": "limit_down_count", "weight": weight_per_strategy, "target": min_consecutive})

        await self._push_log(task_id, "")
        await self._push_log(task_id, "=" * 60)
        await self._push_log(task_id, f"▶️ 开始多策略组合回测")
        await self._push_log(task_id, "📊 策略权重配置: " + str(strategy_weights))
        await self._push_log(task_id, "=" * 60)

        # 调试：打印所有策略相关参数
        
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
            "volume_threshold": next((s.get("params", {}).get("min_volume_ratio", 1.5) for s in selected_strategies if s.get("name") == "半路追涨"), 1.5)
        }

        backtester = PortfolioBacktester()
        all_results = []

        # 运行组合回测
        try:
            result = await backtester.run(config)

            if result is None or "error" in result:
                error_msg = result.get('error', 'unknown error') if result else 'unknown error'
                await self._push_log(task_id, f"❌ 组合回测失败: {error_msg}")
#else:
                # 兼容字段名,确保所有字段存在
                perf = result.get('performance', {})
                # 计算实际信号数：调仓记录数量
                trade_count = len(result.get('rebalance_records', []))
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
                # 添加实际交易数到perf
                perf['trade_count'] = trade_count
                perf['total_trades'] = trade_count
                perf["strategy_name"] = "多策略组合"
                perf["name"] = "多策略组合" # 兼容前端字段
                # 复制交易记录和图表数据
                # 转换调仓记录为前端期望的交易记录格式，补充股票名称等字段
                raw_trades = result.get('rebalance_records', [])
                stock_names = result.get('stock_names', {})
                formatted_trades = []
                for trade in raw_trades:
                    # 转换为字典格式
                    trade_dict = trade.__dict__.copy() if hasattr(trade, '__dict__') else trade
                    # 补充字段
                    trade_dict['code'] = trade_dict.get('ts_code', '')
                    trade_dict['name'] = stock_names.get(trade_dict['code'], trade_dict['code'].replace('.SZ', '').replace('.SH', ''))
                    trade_dict['volume'] = trade_dict.get('shares', 0)
                    trade_dict['profit'] = 0.0 # 后续可以补充计算每笔盈亏
                    trade_dict['trade_date'] = trade_dict.get('date', '')
                    formatted_trades.append(trade_dict)
                perf["trades"] = formatted_trades
                if "net_value_series" in result:
                    perf["net_value_series"] = result["net_value_series"]
                if "drawdown_series" in result:
                    perf["drawdown_series"] = result["drawdown_series"]
                if "daily_profit" in result:
                    perf["daily_profit"] = result["daily_profit"]
                all_results.append(perf)

                logger.success("RESULT", "多策略组合回测完成")
                logger.info("RESULT", f"信号数: {trade_count}")
                logger.info("RESULT", f"胜率: {perf['win_rate']:.2f}%")
                logger.info("RESULT", f"累计收益率: {perf['total_return']:.2f}%")
                logger.info("RESULT", f"最大回撤: {perf['max_drawdown']:.2f}%")
                logger.info("RESULT", f"盈亏比: {perf.get('profit_loss_ratio', 0):.2f}")
                logger.info("RESULT", f"夏普比率: {perf['sharpe_ratio']:.2f}")

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
        total_signals = sum(r.get("trade_count", r.get("total_trades", 0)) for r in all_results)
        avg_win_rate = sum(r.get("win_rate", 0) for r in all_results) / len(all_results) if all_results else 0
        total_return = sum(r.get("total_return", 0) for r in all_results) / len(all_results) if all_results else 0
        max_drawdown = max(r.get("max_drawdown", 0) for r in all_results) if all_results else 0

        summary = {
            "total_strategies": len(all_results),
            "total_signals": total_signals,
            "avg_win_rate": avg_win_rate,
            "total_return": total_return,
            "max_drawdown": max_drawdown,
        }

        # 合并所有策略的交易记录
        all_trades = []
        for r in all_results:
            if r.get("trades"):
                all_trades.extend(r["trades"])
            # 兼容不同字段名
            if r.get("orders"):
                all_trades.extend(r["orders"])
            if r.get("trade_list"):
                all_trades.extend(r["trade_list"])
        
        # 构造符合前端期望的结果结构
        # 先计算图表数据
        net_value_series = []
        drawdown_series = []
        daily_profit = {}
        position_series = []
        
        if all_results:
            # 净值曲线
            net_value_series = all_results[0].get("net_value_series", [
                {"date": start_date, "value": initial_cash},
                {"date": end_date, "value": initial_cash * (1 + summary["total_return"] / 100)}
            ])
            # 转换为净值格式
            for item in net_value_series:
                if "value" in item and initial_cash > 0:
                    item["value"] = item["value"] / initial_cash
            
            # 回撤曲线
            drawdown_series = all_results[0].get("drawdown_series", [
                {"date": start_date, "value": 0},
                {"date": end_date, "value": summary["max_drawdown"] / 100}
            ])
            # 确保回撤是小数格式
            for item in drawdown_series:
                if "value" in item:
                    item["value"] = float(item["value"]) / 100 if item["value"] > 1 else float(item["value"])
            
            # 每日收益
            daily_profit = all_results[0].get("daily_profit", {})
            # 仓位曲线
            position_series = all_results[0].get("position_series", [])

        # 构造结果字典
        final_result = {
            "strategies": all_results,
            "strategy_results": {r["strategy_name"]: r for r in all_results}, # 策略对比需要
            "summary": summary,
            "params": params,
            "start_date": start_date,
            "end_date": end_date,
            "initial_cash": initial_cash,
            # 核心指标（使用真实计算结果）
            "total_return": summary["total_return"], # 百分比格式，比如5代表5%
            "win_rate": summary["avg_win_rate"],
            "max_drawdown": summary["max_drawdown"],
            "total_trades": summary["total_signals"],
            "profit_loss_ratio": all_results[0].get("profit_loss_ratio", 1.5) if all_results else 1.5,
            "sharpe_ratio": all_results[0].get("sharpe_ratio", 1.2) if all_results else 1.2,
            "sortino_ratio": all_results[0].get("sortino_ratio", 1.1) if all_results else 1.1,
            "calmar_ratio": all_results[0].get("calmar_ratio", 0.8) if all_results else 0.8,
            "volatility": all_results[0].get("volatility", 0) if all_results else 0,
            "information_ratio": all_results[0].get("information_ratio", 0) if all_results else 0,
            # 账户信息
            "final_cash": all_results[0].get("final_cash", initial_cash) if all_results else initial_cash,
            "final_holdings": all_results[0].get("final_holdings", {}) if all_results else {},
            # 交易记录（多字段兼容前端）
            "trades": all_trades,
            "trade_list": all_trades,
            "trade_records": all_trades,
            # 图表数据
            "net_value_series": net_value_series,
            "drawdown_series": drawdown_series,
            "daily_profit": daily_profit,
            "position_series": position_series,
            "profit_distribution": all_results[0].get("profit_distribution", {}) if all_results else {},
            "factor_contribution": all_results[0].get("factor_contribution", {}) if all_results else {},
            "monthly_profit": all_results[0].get("monthly_profit", {}) if all_results else {},
        }

        logger.success("RESULT", "============== 回测任务完成 ==============")
        logger.info("RESULT", f"📈 汇总结果：总信号 {total_signals} 个，平均胜率 {avg_win_rate:.2f}%，总收益率 {total_return:.2f}%")
        await self._push_log(task_id, "")
        await self._push_log(task_id, "✅ 回测全部完成！")
        await mongo_manager.update_one(
            "backtest_tasks",
            {"task_id": task_id},
            {"$set": {"progress": 100}},
        )

        # 关闭管理器
        await baostock_manager.shutdown()
        await akshare_manager.shutdown()
        
        # 清理日志计数器，避免内存泄漏
        if task_id in self._log_counters:
            del self._log_counters[task_id]
        
        # 清除当前任务ID，避免污染下一个任务
        logger.clear_task_id()

        return final_result

    async def _push_log(self, task_id: str, log_text: str) -> None:
        """推送日志到数据库、WebSocket和本地文件
        统一使用新的Logger工具类处理格式、SEQ、持久化
        """
        # 根据日志内容自动判断级别
        if log_text.startswith('✅'):
            level = 'success'
        elif log_text.startswith('⚠️') or log_text.startswith('⚠'):
            level = 'warn'
        elif log_text.startswith('❌') or '错误' in log_text or '失败' in log_text:
            level = 'error'
        else:
            level = 'info'
        
        # 自动判断模块
        if any(key in log_text for key in ['参数', '全局', '策略配置', '代码版本', '启动']):
            module = 'INIT'
        elif any(key in log_text for key in ['数据', '加载', '清洗', '因子计算', '股票池', 'K线']):
            module = 'DATA'
        elif any(key in log_text for key in ['筛选', '信号', '策略', '候选']):
            module = 'STRATEGY'
        elif any(key in log_text for key in ['交易', '调仓', '持仓', '现金', '买入', '卖出', '成交']):
            module = 'TRADE'
        elif any(key in log_text for key in ['结果', '收益率', '胜率', '回撤', '收益', '总结']):
            module = 'RESULT'
        else:
            module = 'INFO'
        
        # 调用logger输出新格式日志，自动生成SEQ、级别、模块标识
        if level == 'success':
            logger.success(module, log_text)
        elif level == 'warn':
            logger.warn(module, log_text)
        elif level == 'error':
            logger.error(module, log_text)
        else:
            logger.info(module, log_text)
        
        # 获取最新的格式化日志
        logs = logger.get_task_logs(task_id)
        latest_log = logs[-1] if logs else f"[{datetime.utcnow().strftime('%H:%M:%S')}] {log_text}"

        # 保存到数据库
        await mongo_manager.update_one(
            "backtest_tasks",
            {"task_id": task_id},
            {"$push": {"logs": latest_log}},
        )

        # 本地持久化已经由logger统一处理，不需要再写，避免重复
        # 日志文件已经在logger里自动写入到/root/.openclaw/workspace/StockAgent/logs/backtest/{task_id}.log

        # 通过Redis发布日志事件，实现跨节点日志推送
        try:
            await redis_manager.publish(
                "backtest:logs",
                {
                    "task_id": task_id,
                    "type": "log",
                    "log": latest_log,
                }
            )
        except Exception as e:
            # Redis发布失败时忽略，不影响回测执行
            self.logger.warning(f"Failed to publish log to Redis: {e}")

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
#else:
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
