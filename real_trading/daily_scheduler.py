#!/usr/bin/env python3
"""
每日主调度器 — 串联盘前/盘中/盘后全流程

调度流程：
╔══════════════════════════════════════════════════════════╗
║  盘前 08:50  premarket_phase()                          ║
║  ├── 1. 生成当日信号（PremarketSignalScheduler）         ║
║  ├── 2. 买入前风控检查（PreBuyRiskChecker）              ║
║  ├── 3. 执行建仓（PortfolioTracker / PaperTradingEngine）║
║  └── 4. 推送交易计划通知                                ║
╠══════════════════════════════════════════════════════════╣
║  盘中 09:30-15:00  intraday_phase()                     ║
║  ├── 1. 实时行情监控（RealTimeMonitor）                  ║
║  ├── 2. 止损/止盈/超期自动平仓                          ║
║  └── 3. 风险告警推送                                    ║
╠══════════════════════════════════════════════════════════╣
║  盘后 15:30  postmarket_phase()                         ║
║  ├── 1. 每日结算（PaperTradingEngine.daily_settlement）  ║
║  ├── 2. 更新净值（NavTracker.update_daily_nav）          ║
║  ├── 3. 风控检查（PortfolioTracker.daily_risk_check）    ║
║  ├── 4. 生成调仓报告（DailyRebalanceReportGenerator）    ║
║  ├── 5. 绩效指标计算（PerformanceCalculator）            ║
║  ├── 6. 盘后回顾（PremarketSignalScheduler.review）      ║
║  └── 7. 推送日报                                        ║
╚══════════════════════════════════════════════════════════╝

支持两种运行模式：
1. 定时调度模式（APScheduler）：自动按时间点执行
2. 手动触发模式：指定 phase + date 手动执行

使用方式：
    from daily_scheduler import DailyScheduler

    scheduler = DailyScheduler(account_id="xxx")
    # 手动执行
    await scheduler.run_premarket("20260410")
    await scheduler.run_intraday("20260410")
    await scheduler.run_postmarket("20260410")

    # 或启动定时调度
    await scheduler.start()
    # ...
    await scheduler.stop()
"""
import sys
import os
import json
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

# 项目路径配置
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', '..', 'workspace', 'StockAgent'))
REAL_TRADING_DIR = os.path.join(PROJECT_ROOT, 'real_trading')
AGENT_SERVER_DIR = os.path.join(PROJECT_ROOT, 'AgentServer')

sys.path.insert(0, AGENT_SERVER_DIR)
sys.path.insert(0, REAL_TRADING_DIR)
sys.path.insert(0, os.path.dirname(__file__))

from paper_trading import PaperTradingEngine
from performance_analyzer import PerformanceAnalyzer
from pre_buy_risk_check import PreBuyRiskChecker

# 可选导入（MongoDB依赖模块，不存在时降级）
try:
    from nodes.web.portfolio_tracker import portfolio_tracker, PortfolioTracker
    _HAS_PORTFOLIO_TRACKER = True
except ImportError:
    _HAS_PORTFOLIO_TRACKER = False

try:
    from nodes.web.premarket_signal_scheduler import PremarketSignalScheduler
    _HAS_PREMARKET_SCHEDULER = True
except ImportError:
    try:
        sys.path.insert(0, '/root/.openclaw/.arkclaw-team/projects/p-mob3egqdqoen1q/output/p-mob3egqdqoen1q-worker5')
        from premarket_signal_scheduler import PremarketSignalScheduler
        _HAS_PREMARKET_SCHEDULER = True
    except ImportError:
        _HAS_PREMARKET_SCHEDULER = False

# 本模块产出
from nav_tracker import NavTracker
from performance_calculator import PerformanceCalculator
from daily_rebalance_report import DailyRebalanceReportGenerator
from data_maintainer import DataMaintainer, DownloadResult, ValidationResult

logger = logging.getLogger("daily_scheduler")


class SchedulePhase:
    PREMARKET = "premarket"
    INTRADAY = "intraday"
    POSTMARKET = "postmarket"


@dataclass
class DataAlert:
    """数据缺失/异常告警"""
    alert_type: str           # download_fail / validate_fail / data_missing / incremental_gap
    severity: str             # critical / warning / info
    trade_date: str
    message: str
    details: Dict             # 详细信息
    created_at: str


@dataclass
class ScheduleResult:
    """调度执行结果"""
    phase: str
    trade_date: str
    success: bool
    steps: List[Dict]
    errors: List[str]
    started_at: str
    finished_at: str


class DailyScheduler:
    """每日主调度器

    串联盘前→盘中→盘后全流程，整合以下模块：
    - PremarketSignalScheduler: 盘前信号生成
    - PreBuyRiskChecker: 买入前风控检查
    - PortfolioTracker / PaperTradingEngine: 建仓/平仓
    - NavTracker: 净值跟踪
    - PerformanceCalculator: 绩效指标
    - DailyRebalanceReportGenerator: 调仓报告
    """

    SCHEDULE_TIMES = {
        SchedulePhase.PREMARKET: {"hour": 8, "minute": 50},
        SchedulePhase.INTRADAY: {"hour": 9, "minute": 30},
        SchedulePhase.POSTMARKET: {"hour": 15, "minute": 30},
    }

    def __init__(self, account_id: str = None, config: Dict = None):
        self.config = {
            "initial_cash": 1_000_000,
            "max_position": 0.7,
            "max_position_per_stock": 0.2,
            "slippage": 0.002,
            "stop_loss_pct": 0.02,
            "take_profit_pct": 0.07,
            "max_hold_days": 3,
            "top_n": 5,
            "report_output_dir": os.path.join(os.path.dirname(__file__), "daily_reports"),
            "push_notifications": True,
            "use_mongodb": _HAS_PORTFOLIO_TRACKER,
        }
        self.config.update(config or {})

        self.engine = PaperTradingEngine()

        if account_id:
            self.account_id = account_id
        else:
            self.account_id = next(
                (acc_id for acc_id, acc in self.engine.accounts.items() if acc.status == "active"),
                None
            )
        if not self.account_id:
            raise ValueError("无可用活跃模拟账户")

        # 初始化子模块
        self.nav_tracker = NavTracker(self.account_id)
        self.perf_calculator = PerformanceCalculator(self.account_id)
        self.risk_checker = PreBuyRiskChecker()
        self.report_generator = DailyRebalanceReportGenerator(self.account_id)

        # 数据维护模块
        self.data_maintainer = DataMaintainer()
        self._data_alerts: List[DataAlert] = []  # 数据告警队列
        self._data_initialized = False

        # 可选模块
        self.premarket_scheduler = None
        if _HAS_PREMARKET_SCHEDULER:
            try:
                self.premarket_scheduler = PremarketSignalScheduler()
            except Exception as e:
                logger.warning(f"PremarketSignalScheduler初始化失败: {e}")

        self._apscheduler = None
        self._running = False

    # ============ 数据维护初始化 ============

    async def _ensure_data_maintainer(self):
        """确保DataMaintainer已初始化"""
        if not self._data_initialized:
            await self.data_maintainer.initialize()
            self._data_initialized = True

    def _add_data_alert(self, alert_type: str, severity: str, trade_date: str,
                        message: str, details: Dict = None):
        """添加数据告警"""
        alert = DataAlert(
            alert_type=alert_type,
            severity=severity,
            trade_date=trade_date,
            message=message,
            details=details or {},
            created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        self._data_alerts.append(alert)
        icon = {"critical": "🔴", "warning": "🟡", "info": "🟢"}.get(severity, "⚪")
        logger.info(f"{icon} 数据告警 [{severity}] {alert_type}: {message}")

    def get_data_alerts(self, severity: str = None) -> List[Dict]:
        """获取数据告警列表

        Args:
            severity: 过滤级别 critical/warning/info，None返回全部

        Returns:
            List[Dict]: 告警列表
        """
        alerts = self._data_alerts
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        return [asdict(a) for a in alerts]

    def clear_data_alerts(self, before_date: str = None):
        """清除数据告警"""
        if before_date:
            self._data_alerts = [a for a in self._data_alerts if a.trade_date >= before_date]
        else:
            self._data_alerts = []

    # ============ 盘前调度 ============

    async def run_premarket(self, trade_date: str = None) -> ScheduleResult:
        """盘前调度：信号生成 + 风控检查 + 建仓"""
        if not trade_date:
            trade_date = datetime.now().strftime("%Y%m%d")

        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        steps = []
        errors = []

        logger.info(f"========== 🌅 盘前调度 {trade_date} ==========")

        # Step 0: 下载竞价数据
        try:
            await self._ensure_data_maintainer()
            auction_result = await self.data_maintainer.download_auction_data(trade_date)
            if auction_result.success:
                steps.append({
                    "step": "竞价数据下载", "status": "success",
                    "records": auction_result.records_downloaded,
                    "source": auction_result.source,
                })
            else:
                self._add_data_alert(
                    "download_fail", "warning", trade_date,
                    f"竞价数据下载失败: {'; '.join(auction_result.errors)}",
                    {"source": auction_result.source, "errors": auction_result.errors},
                )
                steps.append({
                    "step": "竞价数据下载", "status": "failed",
                    "error": "; ".join(auction_result.errors),
                })
        except Exception as e:
            self._add_data_alert("download_fail", "warning", trade_date, f"竞价数据下载异常: {e}", {"error": str(e)})
            steps.append({"step": "竞价数据下载", "status": "failed", "error": str(e)})

        # Step 1: 生成信号
        try:
            signal_data = await self._step_generate_signals(trade_date)
            steps.append({
                "step": "信号生成", "status": "success",
                "signal_count": len(signal_data.get("signals", [])),
                "trading_plan": signal_data.get("trading_plan", ""),
                "force_empty": signal_data.get("force_empty", False),
            })
        except Exception as e:
            errors.append(f"信号生成失败: {e}")
            steps.append({"step": "信号生成", "status": "failed", "error": str(e)})
            signal_data = {"signals": [], "force_empty": False, "trading_plan": "信号生成失败"}

        # Step 2: 计算调仓
        try:
            rebalance_ops = self._step_compute_rebalance(signal_data)
            steps.append({
                "step": "调仓计算", "status": "success",
                "to_sell": len(rebalance_ops.get("to_sell", [])),
                "to_buy": len(rebalance_ops.get("to_buy", [])),
                "to_hold": len(rebalance_ops.get("to_hold", [])),
            })
        except Exception as e:
            errors.append(f"调仓计算失败: {e}")
            steps.append({"step": "调仓计算", "status": "failed", "error": str(e)})
            rebalance_ops = {"to_sell": [], "to_buy": [], "to_hold": []}

        # Step 3: 买入前风控检查
        risk_check_results = []
        for sig in rebalance_ops.get("to_buy", []):
            try:
                result = self.risk_checker.check_before_buy(
                    account_id=self.account_id,
                    ts_code=sig.get("ts_code", ""),
                    buy_price=sig.get("price", 0),
                    buy_amount=sig.get("amount", 0),
                )
                risk_check_results.append({
                    "ts_code": sig.get("ts_code", ""),
                    "allowed": result.allowed,
                    "reason": result.reason,
                    "risk_level": result.risk_level,
                })
                if not result.allowed:
                    logger.info(f"❌ 风控拒绝 {sig.get('ts_code', '')}: {result.reason}")
            except Exception as e:
                risk_check_results.append({
                    "ts_code": sig.get("ts_code", ""),
                    "allowed": True,
                    "reason": f"风控检查异常，默认允许: {e}",
                    "risk_level": "unknown",
                })

        passed_buys = [r for r in risk_check_results if r["allowed"]]
        steps.append({
            "step": "买入前风控", "status": "success",
            "passed": len(passed_buys),
            "blocked": len(risk_check_results) - len(passed_buys),
        })

        # Step 4: 执行交易
        try:
            trade_results = await self._step_execute_trades(rebalance_ops, passed_buys, trade_date)
            steps.append({
                "step": "执行交易", "status": "success",
                "sells": len(trade_results.get("sells", [])),
                "buys": len(trade_results.get("buys", [])),
            })
        except Exception as e:
            errors.append(f"执行交易失败: {e}")
            steps.append({"step": "执行交易", "status": "failed", "error": str(e)})

        # Step 5: 推送交易计划
        try:
            plan_text = signal_data.get("trading_plan", "无交易计划")
            steps.append({"step": "推送通知", "status": "success", "plan_length": len(plan_text)})
        except Exception as e:
            errors.append(f"推送失败: {e}")
            steps.append({"step": "推送通知", "status": "failed", "error": str(e)})

        finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"========== 盘前调度完成: {len(errors)}个错误 ==========")

        return ScheduleResult(
            phase=SchedulePhase.PREMARKET, trade_date=trade_date,
            success=len(errors) == 0, steps=steps, errors=errors,
            started_at=started_at, finished_at=finished_at,
        )

    # ============ 盘中调度 ============

    async def run_intraday(self, trade_date: str = None) -> ScheduleResult:
        """盘中调度：实时监控 + 自动平仓"""
        if not trade_date:
            trade_date = datetime.now().strftime("%Y%m%d")

        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        steps = []
        errors = []

        logger.info(f"========== 📊 盘中调度 {trade_date} ==========")

        # Step 1: 持仓风控检查
        try:
            if _HAS_PORTFOLIO_TRACKER:
                await portfolio_tracker.initialize()
                alerts = await portfolio_tracker.daily_risk_check(self.account_id, trade_date)
            else:
                pos_manager = self.engine.position_managers[self.account_id]
                alerts = await pos_manager.daily_check(trade_date)

            danger_alerts = [a for a in alerts if a.get("level") == "danger"]
            steps.append({
                "step": "持仓风控检查", "status": "success",
                "total_alerts": len(alerts), "danger_count": len(danger_alerts),
            })
        except Exception as e:
            errors.append(f"风控检查失败: {e}")
            alerts = []
            danger_alerts = []
            steps.append({"step": "持仓风控检查", "status": "failed", "error": str(e)})

        # Step 2: 自动平仓
        auto_close_results = []
        for alert in danger_alerts:
            ts_code = alert.get("ts_code", "")
            sell_price = alert.get("current_price", 0)
            if not ts_code or sell_price <= 0:
                continue
            try:
                if _HAS_PORTFOLIO_TRACKER:
                    result = await portfolio_tracker.close_position(
                        self.account_id, ts_code, sell_price, reason="盘中自动平仓"
                    )
                else:
                    result = await self.engine.close_position(
                        self.account_id, ts_code, sell_price, reason="盘中自动平仓"
                    )
                auto_close_results.append({"ts_code": ts_code, "success": result.get("success", True)})
            except Exception as e:
                auto_close_results.append({"ts_code": ts_code, "success": False, "error": str(e)})

        steps.append({
            "step": "自动平仓", "status": "success",
            "closed": len([r for r in auto_close_results if r.get("success")]),
            "failed": len([r for r in auto_close_results if not r.get("success")]),
        })

        # Step 3: 推送告警
        try:
            if alerts:
                alert_summary = "\n".join([
                    f"- {a.get('name', '?')}({a.get('ts_code', '?')}): {', '.join(a.get('alerts', []))}"
                    for a in alerts
                ])
                logger.info(f"盘中告警:\n{alert_summary}")
            steps.append({"step": "推送告警", "status": "success", "alert_count": len(alerts)})
        except Exception as e:
            errors.append(f"告警推送失败: {e}")
            steps.append({"step": "推送告警", "status": "failed", "error": str(e)})

        finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"========== 盘中调度完成: {len(errors)}个错误 ==========")

        return ScheduleResult(
            phase=SchedulePhase.INTRADAY, trade_date=trade_date,
            success=len(errors) == 0, steps=steps, errors=errors,
            started_at=started_at, finished_at=finished_at,
        )

    # ============ 盘后调度 ============

    async def run_postmarket(self, trade_date: str = None) -> ScheduleResult:
        """盘后调度：结算 + 净值 + 报告 + 绩效"""
        if not trade_date:
            trade_date = datetime.now().strftime("%Y%m%d")

        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        steps = []
        errors = []
        output_dir = self.config["report_output_dir"]

        logger.info(f"========== 🌙 盘后调度 {trade_date} ==========")

        # Step 0: 下载日线数据
        try:
            await self._ensure_data_maintainer()
            daily_result = await self.data_maintainer.download_daily_data(trade_date)
            if daily_result.success:
                steps.append({
                    "step": "日线数据下载", "status": "success",
                    "records": daily_result.records_downloaded,
                    "upserted": daily_result.records_upserted,
                    "source": daily_result.source,
                    "elapsed": round(daily_result.elapsed_seconds, 1),
                })
            else:
                self._add_data_alert(
                    "download_fail", "critical", trade_date,
                    f"日线数据下载失败: {'; '.join(daily_result.errors)}",
                    {"source": daily_result.source, "errors": daily_result.errors},
                )
                errors.append(f"日线数据下载失败: {'; '.join(daily_result.errors)}")
                steps.append({
                    "step": "日线数据下载", "status": "failed",
                    "error": "; ".join(daily_result.errors),
                })
        except Exception as e:
            self._add_data_alert("download_fail", "critical", trade_date, f"日线数据下载异常: {e}", {"error": str(e)})
            errors.append(f"日线数据下载异常: {e}")
            steps.append({"step": "日线数据下载", "status": "failed", "error": str(e)})

        # Step 0.5: 增量补齐+校验
        try:
            await self._ensure_data_maintainer()
            # 增量补齐最近5天
            inc_results = await self.data_maintainer.incremental_update(days=5)
            missing_count = sum(1 for r in inc_results if not r.success)
            if inc_results:
                steps.append({
                    "step": "增量补齐", "status": "success" if missing_count == 0 else "warning",
                    "checked_days": len(inc_results),
                    "missing_days": missing_count,
                })
                if missing_count > 0:
                    failed_dates = [r.trade_date for r in inc_results if not r.success]
                    self._add_data_alert(
                        "incremental_gap", "warning", trade_date,
                        f"增量补齐缺失{missing_count}天数据: {','.join(failed_dates)}",
                        {"failed_dates": failed_dates},
                    )

            # 校验当日数据
            validation = await self.data_maintainer.validate_daily_data(trade_date)
            if validation.is_valid:
                steps.append({
                    "step": "数据校验", "status": "success",
                    "records": validation.total_records,
                    "outliers": validation.outlier_count,
                    "null_fields": len(validation.null_fields),
                })
            else:
                self._add_data_alert(
                    "validate_fail", "warning" if validation.total_records > 0 else "critical",
                    trade_date,
                    f"数据校验异常: {'; '.join(validation.errors)}",
                    {
                        "total_records": validation.total_records,
                        "outlier_count": validation.outlier_count,
                        "null_fields": validation.null_fields,
                        "errors": validation.errors,
                    },
                )
                steps.append({
                    "step": "数据校验", "status": "failed",
                    "errors": validation.errors,
                    "records": validation.total_records,
                    "outliers": validation.outlier_count,
                })
        except Exception as e:
            logger.warning(f"增量补齐/校验异常: {e}")
            steps.append({"step": "增量补齐+校验", "status": "failed", "error": str(e)})

        # Step 1: 每日结算
        try:
            await self.engine.daily_settlement(self.account_id)
            steps.append({"step": "每日结算", "status": "success"})
        except Exception as e:
            errors.append(f"每日结算失败: {e}")
            steps.append({"step": "每日结算", "status": "failed", "error": str(e)})

        # Step 2: 更新净值
        try:
            nav_record = self.nav_tracker.update_daily_nav(trade_date)
            steps.append({
                "step": "更新净值", "status": "success",
                "nav": nav_record.nav, "daily_return": nav_record.daily_return,
            })
        except Exception as e:
            errors.append(f"净值更新失败: {e}")
            steps.append({"step": "更新净值", "status": "failed", "error": str(e)})

        # Step 3: 绩效指标
        try:
            nav_records = self.nav_tracker.get_nav_history()
            strategy_analysis = None
            try:
                analyzer = PerformanceAnalyzer(f"paper_trade_history_{self.account_id}.json")
                strategy_analysis = analyzer.get_strategy_analysis()
            except Exception:
                pass

            metrics = self.perf_calculator.calculate(nav_records)
            self.perf_calculator.generate_report(
                metrics, output_dir=output_dir, strategy_analysis=strategy_analysis
            )
            steps.append({
                "step": "绩效指标", "status": "success",
                "sharpe": metrics.sharpe_ratio, "max_drawdown": metrics.max_drawdown,
                "win_rate": metrics.win_rate, "annualized_return": metrics.annualized_return,
            })
        except Exception as e:
            errors.append(f"绩效计算失败: {e}")
            steps.append({"step": "绩效指标", "status": "failed", "error": str(e)})

        # Step 4: 调仓报告
        try:
            self.report_generator.generate(trade_date, output_dir=output_dir)
            steps.append({"step": "调仓报告", "status": "success"})
        except Exception as e:
            errors.append(f"调仓报告生成失败: {e}")
            steps.append({"step": "调仓报告", "status": "failed", "error": str(e)})

        # Step 5: 净值报告
        try:
            self.nav_tracker.generate_report(trade_date, output_dir=output_dir)
            steps.append({"step": "净值报告", "status": "success"})
        except Exception as e:
            errors.append(f"净值报告生成失败: {e}")
            steps.append({"step": "净值报告", "status": "failed", "error": str(e)})

        # Step 6: 盘后回顾
        if self.premarket_scheduler:
            try:
                review = await self.premarket_scheduler.generate_postmarket_review(trade_date)
                steps.append({
                    "step": "盘后回顾", "status": "success",
                    "signal_count": review.get("signal_count", 0),
                    "executed_count": review.get("executed_count", 0),
                })
            except Exception as e:
                errors.append(f"盘后回顾失败: {e}")
                steps.append({"step": "盘后回顾", "status": "failed", "error": str(e)})

        # Step 7: 检查数据告警并推送
        critical_alerts = [a for a in self._data_alerts if a.severity == "critical" and a.trade_date == trade_date]
        warning_alerts = [a for a in self._data_alerts if a.severity == "warning" and a.trade_date == trade_date]
        if critical_alerts:
            errors.append(f"🔴 {len(critical_alerts)}个严重数据告警")
        if warning_alerts:
            logger.warning(f"🟡 {len(warning_alerts)}个数据警告")

        # Step 8: 推送日报
        try:
            summary = self._build_daily_summary(trade_date, steps, errors)
            # 附加数据告警摘要
            if critical_alerts or warning_alerts:
                summary += "\n\n⚠️ 数据告警："
                for a in critical_alerts:
                    summary += f"\n  🔴 [{a.alert_type}] {a.message}"
                for a in warning_alerts:
                    summary += f"\n  🟡 [{a.alert_type}] {a.message}"
            logger.info(f"日报摘要:\n{summary}")
            steps.append({"step": "推送日报", "status": "success"})
        except Exception as e:
            errors.append(f"日报推送失败: {e}")
            steps.append({"step": "推送日报", "status": "failed", "error": str(e)})

        finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"========== 盘后调度完成: {len(errors)}个错误 ==========")

        return ScheduleResult(
            phase=SchedulePhase.POSTMARKET, trade_date=trade_date,
            success=len(errors) == 0, steps=steps, errors=errors,
            started_at=started_at, finished_at=finished_at,
        )

    # ============ 全流程 ============

    async def run_full_day(self, trade_date: str = None) -> Dict:
        """执行完整一天的全流程（盘前+盘后）"""
        if not trade_date:
            trade_date = datetime.now().strftime("%Y%m%d")

        logger.info(f"🚀 执行完整日流程: {trade_date}")

        premarket_result = await self.run_premarket(trade_date)
        postmarket_result = await self.run_postmarket(trade_date)

        return {
            "trade_date": trade_date,
            "premarket": asdict(premarket_result),
            "postmarket": asdict(postmarket_result),
            "overall_success": premarket_result.success and postmarket_result.success,
        }

    # ============ 定时调度 ============

    async def start(self) -> None:
        """启动APScheduler定时调度"""
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.triggers.cron import CronTrigger
        except ImportError:
            logger.error("APScheduler未安装，请执行: pip install apscheduler")
            raise

        if self._running:
            logger.warning("调度器已在运行")
            return

        self._apscheduler = AsyncIOScheduler(timezone="Asia/Shanghai")

        for phase, time_cfg in self.SCHEDULE_TIMES.items():
            handler = {
                SchedulePhase.PREMARKET: self._scheduled_premarket,
                SchedulePhase.INTRADAY: self._scheduled_intraday,
                SchedulePhase.POSTMARKET: self._scheduled_postmarket,
            }[phase]
            self._apscheduler.add_job(
                handler,
                CronTrigger(day_of_week="mon-fri", hour=time_cfg["hour"], minute=time_cfg["minute"]),
                id=phase, name=f"{phase}调度", replace_existing=True,
            )

        self._apscheduler.start()
        self._running = True
        logger.info(
            f"✅ 定时调度已启动 | "
            f"盘前{self.SCHEDULE_TIMES[SchedulePhase.PREMARKET]['hour']:02d}:{self.SCHEDULE_TIMES[SchedulePhase.PREMARKET]['minute']:02d} | "
            f"盘中{self.SCHEDULE_TIMES[SchedulePhase.INTRADAY]['hour']:02d}:{self.SCHEDULE_TIMES[SchedulePhase.INTRADAY]['minute']:02d} | "
            f"盘后{self.SCHEDULE_TIMES[SchedulePhase.POSTMARKET]['hour']:02d}:{self.SCHEDULE_TIMES[SchedulePhase.POSTMARKET]['minute']:02d}"
        )

    async def stop(self) -> None:
        """停止定时调度"""
        if self._apscheduler:
            self._apscheduler.shutdown(wait=False)
            self._apscheduler = None
        self._running = False
        logger.info("⏹️ 定时调度已停止")

    async def _scheduled_premarket(self):
        try:
            await self.run_premarket()
        except Exception as e:
            logger.exception(f"定时盘前调度异常: {e}")

    async def _scheduled_intraday(self):
        try:
            await self.run_intraday()
        except Exception as e:
            logger.exception(f"定时盘中调度异常: {e}")

    async def _scheduled_postmarket(self):
        try:
            await self.run_postmarket()
        except Exception as e:
            logger.exception(f"定时盘后调度异常: {e}")

    @property
    def is_running(self) -> bool:
        return self._running

    def get_status(self) -> Dict:
        """获取调度器状态"""
        status = {
            "running": self._running,
            "account_id": self.account_id,
            "modules": {
                "paper_trading_engine": True,
                "nav_tracker": True,
                "performance_calculator": True,
                "risk_checker": True,
                "report_generator": True,
                "premarket_scheduler": self.premarket_scheduler is not None,
                "portfolio_tracker_mongo": _HAS_PORTFOLIO_TRACKER,
                "data_maintainer": self._data_initialized,
            },
            "data_alerts": {
                "total": len(self._data_alerts),
                "critical": len([a for a in self._data_alerts if a.severity == "critical"]),
                "warning": len([a for a in self._data_alerts if a.severity == "warning"]),
                "info": len([a for a in self._data_alerts if a.severity == "info"]),
            },
            "schedule_times": self.SCHEDULE_TIMES,
        }
        if self._apscheduler:
            jobs = []
            for job in self._apscheduler.get_jobs():
                jobs.append({
                    "id": job.id, "name": job.name,
                    "next_run": str(job.next_run_time) if job.next_run_time else None,
                })
            status["jobs"] = jobs
        return status

    # ============ 内部步骤方法 ============

    async def _step_generate_signals(self, trade_date: str) -> Dict:
        """Step: 生成当日信号"""
        if self.premarket_scheduler:
            return await self.premarket_scheduler.generate_premarket_signals(trade_date)

        # 降级：从信号文件读取
        signal_file = os.path.join(REAL_TRADING_DIR, "signals", f"{trade_date}.json")
        if os.path.exists(signal_file):
            with open(signal_file, "r", encoding="utf-8") as f:
                return json.load(f)

        # 找最近的信号文件
        signals_dir = os.path.join(REAL_TRADING_DIR, "signals")
        if os.path.isdir(signals_dir):
            files = sorted([f for f in os.listdir(signals_dir) if f.endswith(".json")], reverse=True)
            if files:
                with open(os.path.join(signals_dir, files[0]), "r", encoding="utf-8") as f:
                    return json.load(f)

        logger.warning("未找到信号文件，返回空信号")
        return {"date": trade_date, "force_empty": False, "signals": [], "trading_plan": "未找到信号文件，保持空仓"}

    def _step_compute_rebalance(self, signal_data: Dict) -> Dict:
        """Step: 计算调仓操作"""
        signals = signal_data.get("signals", [])
        signal_codes = {s.get("ts_code") for s in signals} if signals else set()

        pos_manager = self.engine.position_managers[self.account_id]
        current_positions = pos_manager.get_positions()
        position_codes = {p["ts_code"] for p in current_positions}

        to_sell = [p for p in current_positions if p["ts_code"] not in signal_codes]
        to_buy = [s for s in signals if s.get("ts_code") not in position_codes]
        to_hold = [p for p in current_positions if p["ts_code"] in signal_codes]

        # 计算买入金额分配
        account = self.engine.accounts[self.account_id]
        sell_proceeds = sum(p["total_cost"] for p in to_sell)
        investable = account.current_balance + sell_proceeds
        position_limit = signal_data.get("sentiment", {}).get("position_limit", 0.7)

        for sig in to_buy:
            buy_price = sig.get("price", sig.get("close", 0))
            per_stock = investable * position_limit / max(len(signals), 1)
            shares = int(per_stock / buy_price / 100) * 100 if buy_price > 0 else 0
            sig["amount"] = shares * buy_price
            sig["shares"] = shares

        return {"to_sell": to_sell, "to_buy": to_buy, "to_hold": to_hold}

    async def _step_execute_trades(self, rebalance_ops: Dict, passed_buys: List[Dict],
                                    trade_date: str) -> Dict:
        """Step: 执行交易"""
        results = {"sells": [], "buys": [], "buy_errors": []}

        # 卖出
        for pos in rebalance_ops.get("to_sell", []):
            try:
                sell_price = pos.get("buy_price", 0)
                if _HAS_PORTFOLIO_TRACKER:
                    result = await portfolio_tracker.close_position(
                        self.account_id, pos["ts_code"], sell_price, reason="调仓卖出"
                    )
                else:
                    result = await self.engine.close_position(
                        self.account_id, pos["ts_code"], sell_price, reason="调仓卖出"
                    )
                results["sells"].append({"ts_code": pos["ts_code"], "success": result.get("success", True)})
            except Exception as e:
                results["sells"].append({"ts_code": pos["ts_code"], "success": False, "error": str(e)})

        # 买入（仅风控通过的）
        passed_codes = {r["ts_code"] for r in passed_buys}
        for sig in rebalance_ops.get("to_buy", []):
            if sig.get("ts_code") not in passed_codes:
                continue
            try:
                if _HAS_PORTFOLIO_TRACKER:
                    await portfolio_tracker.initialize()
                    result = await portfolio_tracker.open_position(
                        account_id=self.account_id,
                        ts_code=sig.get("ts_code", ""),
                        stock_name=sig.get("name", ""),
                        buy_price=sig.get("price", sig.get("close", 0)),
                        shares=sig.get("shares", 100),
                        strategy=sig.get("strategy", ""),
                    )
                else:
                    result = await self.engine.place_order(
                        account_id=self.account_id,
                        ts_code=sig.get("ts_code", ""),
                        name=sig.get("name", ""),
                        buy_price=sig.get("price", sig.get("close", 0)),
                        shares=sig.get("shares", 100),
                        strategy=sig.get("strategy", ""),
                    )
                results["buys"].append({"ts_code": sig.get("ts_code", ""), "success": result.get("success", True)})
            except Exception as e:
                results["buy_errors"].append({"ts_code": sig.get("ts_code", ""), "error": str(e)})

        return results

    def _build_daily_summary(self, trade_date: str, steps: List[Dict], errors: List[str]) -> str:
        """构建每日摘要"""
        lines = [
            f"📋 StockAgent 每日调度摘要 - {trade_date}",
            f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"账户：{self.account_id}",
            "",
            "执行步骤：",
        ]
        for step in steps:
            icon = "✅" if step["status"] == "success" else "❌"
            lines.append(f"  {icon} {step['step']}")
        if errors:
            lines.append("")
            lines.append("错误信息：")
            for err in errors:
                lines.append(f"  ❌ {err}")
        lines.append("")
        lines.append(f"整体状态：{'✅ 成功' if not errors else '⚠️ 部分失败'}")
        return "\n".join(lines)


# ============ CLI入口 ============

async def main():
    import argparse
    parser = argparse.ArgumentParser(description="StockAgent 每日主调度器")
    parser.add_argument("--phase", choices=["premarket", "intraday", "postmarket", "full", "status", "start"],
                        default="full", help="执行阶段")
    parser.add_argument("--date", help="交易日期(YYYYMMDD)")
    parser.add_argument("--account", help="账户ID")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    scheduler = DailyScheduler(args.account)

    if args.phase == "status":
        status = scheduler.get_status()
        logger.info(json.dumps(status, ensure_ascii=False, indent=2))
        return

    if args.phase == "start":
        await scheduler.start()
        logger.info("✅ 定时调度已启动，按 Ctrl+C 退出...")
        try:
            while True:
                await asyncio.sleep(3600)
        except (KeyboardInterrupt, asyncio.CancelledError):
            await scheduler.stop()
        return

    if args.phase == "premarket":
        result = await scheduler.run_premarket(args.date)
    elif args.phase == "intraday":
        result = await scheduler.run_intraday(args.date)
    elif args.phase == "postmarket":
        result = await scheduler.run_postmarket(args.date)
    elif args.phase == "full":
        result = await scheduler.run_full_day(args.date)
    else:
        result = None

    if result:
        output = asdict(result) if isinstance(result, ScheduleResult) else result
        logger.info(json.dumps(output, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
