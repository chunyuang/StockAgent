"""
RiskWatchdog — 独立风控看门狗

解决核心问题: 风控不能依赖策略进程
- 之前: 风控只在Scanner内部, Scanner假死则风控也失效
- 现在: RiskWatchdog是独立健康检查循环, 与Scanner主循环解耦
  - 监控: 扫描心跳/信号产出/行情延迟/账户回撤
  - 告警: 通过SignalDispatcher发送CRITICAL级告警
  - 自愈: 检测异常后可触发自动恢复(重启扫描/降低仓位)
  - 紧急通道: 提供独立于Scanner的紧急平仓接口

设计原则:
1. 独立循环: 不在Scanner主循环内, 即使Scanner卡死也能运行
2. 轻量: 只做监控和告警, 不做复杂计算
3. 可观测: 所有检查结果对外可见(GUI/API)

用法:
    watchdog = RiskWatchdog(scanner)
    watchdog.register_alert_channel(dispatcher.dispatch)
    asyncio.create_task(watchdog.run())
    
    # 紧急平仓(独立于Scanner)
    await watchdog.emergency_liquidate("手动触发")
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, Optional, Callable, Awaitable, List, Any
from dataclasses import dataclass, field
from enum import Enum


logger = logging.getLogger("risk.watchdog")


class HealthStatus(Enum):
    """健康状态"""
    HEALTHY = "healthy"        # 绿灯
    DEGRADED = "degraded"      # 黄灯: 部分指标异常
    CRITICAL = "critical"      # 红灯: 需要人工干预
    DEAD = "dead"              # 黑灯: Scanner无心跳


@dataclass
class HealthCheck:
    """单项健康检查"""
    name: str
    status: HealthStatus
    value: Any = None
    threshold: Any = None
    message: str = ""
    last_check_time: float = 0.0


@dataclass 
class WatchdogState:
    """看门狗状态"""
    overall_status: HealthStatus = HealthStatus.HEALTHY
    checks: Dict[str, HealthCheck] = field(default_factory=dict)
    last_alert_time: float = 0.0
    alert_count: int = 0
    scanner_heartbeat: float = 0.0   # Scanner最后心跳时间
    start_time: float = 0.0


class RiskWatchdog:
    """
    独立风控看门狗
    
    检查项:
    1. Scanner心跳: 最近一次成功扫描时间
    2. 信号产出: 最近5分钟是否有信号(不应该一直0)
    3. 行情延迟: 东财接口响应时间
    4. 账户回撤: 单日/总回撤是否超限
    5. 持仓健康: 是否有持仓超过最大持有天数
    6. 必盈额度: 剩余API调用次数
    """
    
    # 检查间隔
    CHECK_INTERVAL = 30  # 30秒检查一次
    HEARTBEAT_TIMEOUT = 300  # 5分钟无心跳视为异常
    SIGNAL_SILENCE_WARNING = 1800  # 30分钟无信号发警告
    
    # 告警冷却(秒): 同一告警不重复发送
    ALERT_COOLDOWN = 300
    
    def __init__(self, scanner=None):
        self._scanner = scanner
        self._state = WatchdogState(start_time=time.time())
        self._alert_channels: List[Callable] = []
        self._running = False
        self._task: Optional[asyncio.Task] = None
        
        # 告警冷却
        self._last_alerts: Dict[str, float] = {}  # check_name → last_alert_time
    
    def register_alert_channel(self, handler: Callable) -> None:
        """注册告警通道(如SignalDispatcher.dispatch)"""
        self._alert_channels.append(handler)
        logger.info(f"[WATCHDOG] 注册告警通道: {handler.__name__ if hasattr(handler, '__name__') else 'lambda'}")
    
    def update_heartbeat(self) -> None:
        """Scanner调用: 每次扫描成功后更新心跳"""
        self._state.scanner_heartbeat = time.time()
    
    async def start(self) -> None:
        """启动看门狗"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("[WATCHDOG] 看门狗已启动")
    
    async def stop(self) -> None:
        """停止看门狗"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[WATCHDOG] 看门狗已停止")
    
    async def _run_loop(self) -> None:
        """看门狗主循环"""
        while self._running:
            try:
                await self._run_checks()
            except Exception as e:
                logger.error(f"[WATCHDOG] 检查异常: {e}", exc_info=True)
            await asyncio.sleep(self.CHECK_INTERVAL)
    
    async def _run_checks(self) -> None:
        """执行所有健康检查"""
        checks = {}
        
        # 1. Scanner心跳检查
        checks["heartbeat"] = self._check_heartbeat()
        
        # 2. 信号产出检查
        checks["signal_output"] = self._check_signal_output()
        
        # 3. 账户回撤检查
        checks["drawdown"] = await self._check_drawdown()
        
        # 4. 持仓健康检查
        checks["position_health"] = await self._check_position_health()
        
        # 5. 行情延迟检查(如果Scanner有数据)
        checks["market_latency"] = self._check_market_latency()
        
        # 【V54:数据源可用性检查】
        checks["data_source"] = self._check_data_source()
        
        # 更新状态
        self._state.checks = checks
        
        # 综合判断
        statuses = [c.status for c in checks.values()]
        if any(s == HealthStatus.CRITICAL for s in statuses):
            self._state.overall_status = HealthStatus.CRITICAL
        elif any(s == HealthStatus.DEGRADED for s in statuses):
            self._state.overall_status = HealthStatus.DEGRADED
        elif any(s == HealthStatus.DEAD for s in statuses):
            self._state.overall_status = HealthStatus.DEAD
        else:
            self._state.overall_status = HealthStatus.HEALTHY
        
        # 发送告警(只对DEGRADED/CRITICAL/DEAD)
        for name, check in checks.items():
            if check.status in (HealthStatus.DEGRADED, HealthStatus.CRITICAL, HealthStatus.DEAD):
                await self._send_alert_if_needed(name, check)
    
    # ==================== 具体检查 ====================
    
    def _check_heartbeat(self) -> HealthCheck:
        """检查Scanner心跳"""
        now = time.time()
        last_hb = self._state.scanner_heartbeat
        
        if last_hb <= 0:
            # 尚未收到心跳(刚启动)
            elapsed = now - self._state.start_time
            if elapsed < 120:
                return HealthCheck(
                    name="heartbeat", status=HealthStatus.HEALTHY,
                    value=f"启动中({elapsed:.0f}s)",
                    threshold="<300s",
                    message="Scanner尚未完成首次扫描",
                    last_check_time=now,
                )
            else:
                return HealthCheck(
                    name="heartbeat", status=HealthStatus.DEAD,
                    value=f"从未心跳({elapsed:.0f}s)",
                    threshold="<300s",
                    message="🚨 Scanner从未成功扫描, 可能启动失败",
                    last_check_time=now,
                )
        
        elapsed = now - last_hb
        
        if elapsed > self.HEARTBEAT_TIMEOUT:
            return HealthCheck(
                name="heartbeat", status=HealthStatus.DEAD,
                value=f"{elapsed:.0f}s",
                threshold=f"<{self.HEARTBEAT_TIMEOUT}s",
                message=f"🚨 Scanner心跳超时{elapsed:.0f}s, 可能假死",
                last_check_time=now,
            )
        elif elapsed > self.HEARTBEAT_TIMEOUT * 0.6:
            return HealthCheck(
                name="heartbeat", status=HealthStatus.DEGRADED,
                value=f"{elapsed:.0f}s",
                threshold=f"<{self.HEARTBEAT_TIMEOUT}s",
                message=f"⚠️ Scanner心跳延迟{elapsed:.0f}s",
                last_check_time=now,
            )
        else:
            return HealthCheck(
                name="heartbeat", status=HealthStatus.HEALTHY,
                value=f"{elapsed:.0f}s",
                threshold=f"<{self.HEARTBEAT_TIMEOUT}s",
                message="正常",
                last_check_time=now,
            )
    
    def _check_signal_output(self) -> HealthCheck:
        """检查信号产出"""
        now = time.time()
        
        if not self._scanner:
            return HealthCheck(
                name="signal_output", status=HealthStatus.HEALTHY,
                value="N/A", threshold="N/A",
                message="Scanner未关联",
                last_check_time=now,
            )
        
        stats = self._scanner._stats
        total_signals = stats.get("signals_found", 0)
        scan_count = stats.get("scans", 0)
        
        # 检查最近时间线(信号产出)
        recent_trades = [t for t in self._scanner._timeline 
                        if now - t.get("_timestamp", now) < 1800]  # 最近30分钟
        
        if scan_count > 10 and total_signals == 0:
            return HealthCheck(
                name="signal_output", status=HealthStatus.DEGRADED,
                value=f"0信号/{scan_count}次扫描",
                threshold=">0",
                message="⚠️ 多次扫描无信号, 可能行情源异常或策略条件过严",
                last_check_time=now,
            )
        
        return HealthCheck(
            name="signal_output", status=HealthStatus.HEALTHY,
            value=f"{total_signals}信号/{scan_count}次扫描",
            threshold=">0",
            message="正常",
            last_check_time=now,
        )
    
    async def _check_drawdown(self) -> HealthCheck:
        """检查账户回撤"""
        now = time.time()
        
        if not self._scanner or not self._scanner._broker:
            return HealthCheck(
                name="drawdown", status=HealthStatus.HEALTHY,
                value="N/A", threshold="<5%日/<20%总",
                message="Broker未初始化",
                last_check_time=now,
            )
        
        try:
            acct = self._scanner._broker.get_account()
            if not acct:
                return HealthCheck(
                    name="drawdown", status=HealthStatus.HEALTHY,
                    value="N/A", threshold="<5%日/<20%总",
                    message="账户信息不可用",
                    last_check_time=now,
                )
            
            # 计算总回撤(从峰值)
            total_assets = acct.total_assets
            initial = self._scanner._broker._initial_cash
            peak = max(initial, total_assets)  # 简化: 实际应从历史获取峰值
            
            total_drawdown = 0
            if peak > 0:
                total_drawdown = (1 - total_assets / peak) * 100
            
            # 检查DailyScheduler的daily_start_asset
            daily_start = getattr(self._scanner, '_daily_start_asset', 0)
            daily_drawdown = 0
            if daily_start > 0:
                daily_drawdown = (1 - total_assets / daily_start) * 100
            
            if total_drawdown > 20 or daily_drawdown > 5:
                return HealthCheck(
                    name="drawdown", status=HealthStatus.CRITICAL,
                    value=f"日{daily_drawdown:.1f}%/总{total_drawdown:.1f}%",
                    threshold="<5%日/<20%总",
                    message=f"🚨 回撤超限! 日{daily_drawdown:.1f}%/总{total_drawdown:.1f}%",
                    last_check_time=now,
                )
            elif daily_drawdown > 3 or total_drawdown > 10:
                return HealthCheck(
                    name="drawdown", status=HealthStatus.DEGRADED,
                    value=f"日{daily_drawdown:.1f}%/总{total_drawdown:.1f}%",
                    threshold="<5%日/<20%总",
                    message=f"⚠️ 回撤偏高: 日{daily_drawdown:.1f}%/总{total_drawdown:.1f}%",
                    last_check_time=now,
                )
            
            return HealthCheck(
                name="drawdown", status=HealthStatus.HEALTHY,
                value=f"日{daily_drawdown:.1f}%/总{total_drawdown:.1f}%",
                threshold="<5%日/<20%总",
                message="正常",
                last_check_time=now,
            )
        except Exception as e:
            return HealthCheck(
                name="drawdown", status=HealthStatus.DEGRADED,
                value=f"检查失败: {e}",
                threshold="<5%日/<20%总",
                message=f"⚠️ 回撤检查异常: {e}",
                last_check_time=now,
            )
    
    async def _check_position_health(self) -> HealthCheck:
        """检查持仓健康"""
        now = time.time()
        
        if not self._scanner or not self._scanner._broker:
            return HealthCheck(
                name="position_health", status=HealthStatus.HEALTHY,
                value="N/A", threshold="无超时持仓",
                message="Broker未初始化",
                last_check_time=now,
            )
        
        try:
            positions = self._scanner._broker.get_positions()
            max_hold_days = 5  # 与回测对齐
            
            overdue = []
            for p in positions:
                # 计算持仓天数
                buy_date = getattr(p, 'buy_date', None)
                if buy_date:
                    if isinstance(buy_date, str):
                        from datetime import datetime as dt
                        buy_dt = dt.strptime(buy_date, "%Y%m%d")
                    elif hasattr(buy_date, 'date'):
                        buy_dt = buy_date
                    else:
                        buy_dt = datetime.now()
                    
                    days = (datetime.now() - buy_dt).days
                    if days > max_hold_days:
                        overdue.append(f"{p.ts_code}({days}天)")
            
            if overdue:
                return HealthCheck(
                    name="position_health", status=HealthStatus.DEGRADED,
                    value=f"{len(overdue)}只超时",
                    threshold=f"<={max_hold_days}天",
                    message=f"⚠️ 超时持仓: {', '.join(overdue[:5])}",
                    last_check_time=now,
                )
            
            return HealthCheck(
                name="position_health", status=HealthStatus.HEALTHY,
                value=f"{len(positions)}只持仓",
                threshold=f"<={max_hold_days}天",
                message="正常",
                last_check_time=now,
            )
        except Exception as e:
            return HealthCheck(
                name="position_health", status=HealthStatus.HEALTHY,
                value=f"检查失败: {e}",
                threshold=f"<={max_hold_days}天",
                message=f"持仓检查异常(非关键): {e}",
                last_check_time=now,
            )
    
    def _check_market_latency(self) -> HealthCheck:
        """检查行情延迟"""
        now = time.time()
        
        if not self._scanner:
            return HealthCheck(
                name="market_latency", status=HealthStatus.HEALTHY,
                value="N/A", threshold="<10s",
                message="Scanner未关联",
                last_check_time=now,
            )
        
        # 从Scanner获取最近一次扫描耗时
        scan_time = getattr(self._scanner, '_last_scan_duration_ms', 0)
        
        if scan_time <= 0:
            return HealthCheck(
                name="market_latency", status=HealthStatus.HEALTHY,
                value="N/A", threshold="<10s",
                message="暂无扫描耗时数据",
                last_check_time=now,
            )
        
        if scan_time > 30000:  # >30秒
            return HealthCheck(
                name="market_latency", status=HealthStatus.DEGRADED,
                value=f"{scan_time/1000:.1f}s",
                threshold="<10s",
                message=f"⚠️ 行情获取耗时{scan_time/1000:.1f}s, 可能被限流",
                last_check_time=now,
            )
        elif scan_time > 10000:  # >10秒
            return HealthCheck(
                name="market_latency", status=HealthStatus.DEGRADED,
                value=f"{scan_time/1000:.1f}s",
                threshold="<10s",
                message=f"⚠️ 行情获取偏慢{scan_time/1000:.1f}s",
                last_check_time=now,
            )
        
        return HealthCheck(
            name="market_latency", status=HealthStatus.HEALTHY,
            value=f"{scan_time/1000:.1f}s",
            threshold="<10s",
            message="正常",
            last_check_time=now,
        )
    
    def _check_data_source(self) -> HealthCheck:
        """【V54:检查数据源可用性(东财/必盈连接状态)"""
        now = time.time()
        
        if not self._scanner:
            return HealthCheck(
                name="data_source", status=HealthStatus.HEALTHY,
                value="N/A", threshold="东财可用",
                message="Scanner未关联",
                last_check_time=now,
            )
        
        issues = []
        # 检查东财连接: 最后一次scan是否成功获取行情
        cache_size = len(getattr(self._scanner, '_realtime_cache', {}))
        if cache_size == 0 and self._scanner._is_running:
            # 正在运行但行情缓存为空 = 东财可能断流
            elapsed = time.time() - self._state.scanner_heartbeat
            if elapsed > 60:  # 超过60秒没有行情
                issues.append("东财行情缓存为空")
        
        # 检查必盈额度(如果有)
        data_router = getattr(self._scanner, '_data_router', None)
        if data_router and hasattr(data_router, 'bingying_remaining'):
            remaining = data_router.bingying_remaining
            if remaining is not None and remaining < 20:
                issues.append(f"必盈额度不足({remaining}次)")
        
        if issues:
            return HealthCheck(
                name="data_source", status=HealthStatus.DEGRADED,
                value=", ".join(issues),
                threshold="东财可用+必盈>20次",
                message=f"⚠️ 数据源异常: {', '.join(issues)}",
                last_check_time=now,
            )
        
        return HealthCheck(
            name="data_source", status=HealthStatus.HEALTHY,
            value=f"东财缓存{cache_size}只",
            threshold="东财可用",
            message="正常",
            last_check_time=now,
        )

    # ==================== 告警与紧急操作 ====================
    
    async def _send_alert_if_needed(self, check_name: str, check: HealthCheck) -> None:
        """发送告警(带冷却)"""
        now = time.time()
        last_alert = self._last_alerts.get(check_name, 0)
        
        if now - last_alert < self.ALERT_COOLDOWN:
            return  # 冷却中
        
        self._last_alerts[check_name] = now
        self._state.alert_count += 1
        
        # 构建告警信号
        from nodes.market_monitor.signal_dispatcher import (
            SignalDispatcher, DispatchSignal, SignalPriority
        )
        
        priority = SignalPriority.CRITICAL if check.status in (HealthStatus.CRITICAL, HealthStatus.DEAD) else SignalPriority.HIGH
        
        alert_signal = DispatchSignal(
            signal_id=f"watchdog|{check_name}|{int(now)}",
            ts_code="SYSTEM",
            stock_name="风控看门狗",
            strategy="risk_watchdog",
            strategy_name="风控看门狗",
            signal_type="risk",
            priority=priority,
            reason=check.message,
            extra={
                "check_name": check.name,
                "status": check.status.value,
                "value": str(check.value),
                "threshold": str(check.threshold),
            },
            created_at=now,
            source="risk_watchdog",
        )
        
        for handler in self._alert_channels:
            try:
                await handler(alert_signal)
            except Exception as e:
                logger.warning(f"[WATCHDOG] 告警通道异常: {e}")
    
    async def emergency_liquidate(self, reason: str = "手动触发") -> Dict:
        """
        紧急平仓(独立于Scanner)
        
        直接通过broker清仓, 不经过Scanner主循环。
        用于: GUI红色按钮 / 风控自动触发 / API紧急调用
        """
        result = {"success": False, "positions_cleared": 0, "reason": reason, "details": []}
        
        if not self._scanner or not self._scanner._broker:
            result["error"] = "Scanner或Broker不可用"
            return result
        
        try:
            positions = self._scanner._broker.get_positions()
            for pos in positions:
                if pos.available_qty <= 0:
                    continue  # T+1: 今日买入不可卖
                
                self._scanner._broker.update_realtime(pos.ts_code, pos.current_price)
                ok, msg, order = self._scanner._broker.place_order(
                    ts_code=pos.ts_code,
                    stock_name=pos.stock_name,
                    side="sell",
                    quantity=pos.available_qty,
                    price=pos.current_price,
                    order_type="market",
                    strategy=pos.strategy,
                    reason=f"⚠️紧急平仓: {reason}",
                )
                result["details"].append({
                    "ts_code": pos.ts_code,
                    "success": ok,
                    "message": msg if not ok else f"卖出{pos.available_qty}股@{order.filled_price:.2f}",
                })
                if ok:
                    result["positions_cleared"] += 1
            
            # 持久化
            await self._scanner._broker.save_state(force=True)
            result["success"] = True
            
            logger.critical(
                f"[WATCHDOG] 🚨 紧急平仓: reason={reason}, "
                f"cleared={result['positions_cleared']}/{len(positions)}"
            )
            
        except Exception as e:
            result["error"] = str(e)
            logger.critical(f"[WATCHDOG] 🚨 紧急平仓失败: {e}")
        
        return result
    
    # ==================== 对外接口 ====================
    
    def get_status(self) -> Dict:
        """获取看门狗状态(供GUI/API使用)"""
        checks = {}
        for name, check in self._state.checks.items():
            checks[name] = {
                "status": check.status.value,
                "value": str(check.value),
                "threshold": str(check.threshold),
                "message": check.message,
            }
        
        return {
            "overall_status": self._state.overall_status.value,
            "uptime_seconds": time.time() - self._state.start_time,
            "scanner_heartbeat_age": time.time() - self._state.scanner_heartbeat if self._state.scanner_heartbeat > 0 else -1,
            "alert_count": self._state.alert_count,
            "checks": checks,
        }
