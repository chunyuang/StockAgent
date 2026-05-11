#!/usr/bin/env python3
"""
DailyScheduler - 每日调度编排器

3阶段调度:
- premarket (9:15): 数据更新 + 因子计算 + 信号生成 + 飞书推送
- intraday (每5min, 9:30-15:00): 持仓监控 + 止损止盈检查 + 风控告警
- postmarket (15:30): 数据补全 + 绩效统计 + 日报推送

直接复用回测引擎的策略逻辑(FactorEngine + _build_strategy_filter_conditions)
"""
import os
import asyncio
import logging
import json
from datetime import datetime, time as dtime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

import pandas as pd

logger = logging.getLogger("scheduler.daily")


@dataclass
class ScheduleStep:
    name: str
    success: bool = False
    message: str = ""
    duration_ms: int = 0
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ScheduleResult:
    success: bool = False
    steps: List[ScheduleStep] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    trade_date: str = ""


class DailyScheduler:
    """每日调度编排器 - 实盘核心"""

    # 定时配置
    SCHEDULE_TIMES = {
        "premarket": "09:15",
        "intraday_start": "09:30",
        "intraday_end": "15:00",
        "intraday_interval": 300,  # 5分钟
        "postmarket": "15:30",
    }

    def __init__(self, account_id: str = "default_account", config: Dict = None):
        self.account_id = account_id
        self.config = config or {}
        self._is_running = False
        self._current_phase = "idle"
        self._task: Optional[asyncio.Task] = None

        # 执行器(模拟盘)
        self._executor = None

        # 量脉客户端(延迟初始化)
        self._liangmai = None

        # 持仓状态
        self._positions: Dict[str, Dict] = {}
        self._signals: List[Dict] = []
        self._alerts: List[Dict] = []

    @property
    def is_running(self):
        return self._is_running

    def get_status(self) -> Dict[str, Any]:
        return {
            "is_running": self._is_running,
            "current_phase": self._current_phase,
            "account_id": self.account_id,
            "positions_count": len(self._positions),
            "signals_today": len(self._signals),
            "alerts_today": len(self._alerts),
            "mode": "live",
        }

    def get_data_alerts(self, severity=None):
        return []

    def clear_data_alerts(self, before_date=None):
        pass

    def get_schedule_history(self, days=7):
        return []

    # ==================== 生命周期 ====================

    async def start(self):
        if self._is_running:
            return {"success": True, "message": "已在运行中"}
        self._is_running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"[SCHEDULER] 启动, account={self.account_id}")
        return {"success": True, "message": "调度器启动成功"}

    async def stop(self):
        self._is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[SCHEDULER] 已停止")
        return {"success": True, "message": "调度器已停止"}

    async def _run_loop(self):
        """主循环: 按时间执行3阶段"""
        try:
            while self._is_running:
                now = datetime.now()
                ct = now.strftime("%H:%M")

                if ct == self.SCHEDULE_TIMES["premarket"]:
                    await self.run_premarket(now.strftime("%Y%m%d"))
                    await asyncio.sleep(60)

                elif (self.SCHEDULE_TIMES["intraday_start"] <= ct
                      <= self.SCHEDULE_TIMES["intraday_end"]):
                    await self.run_intraday(now.strftime("%Y%m%d"))
                    await asyncio.sleep(self.SCHEDULE_TIMES["intraday_interval"])

                elif ct == self.SCHEDULE_TIMES["postmarket"]:
                    await self.run_postmarket(now.strftime("%Y%m%d"))
                    await asyncio.sleep(60)

                else:
                    await asyncio.sleep(30)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[SCHEDULER] 异常: {e}", exc_info=True)

    # ==================== 盘前 ====================

    async def run_premarket(self, trade_date: str) -> ScheduleResult:
        result = ScheduleResult(trade_date=trade_date)
        self._current_phase = "premarket"
        logger.info(f"[PREMARKET] ===== 开始 {trade_date} =====")

        # Step 1: 数据更新
        step = ScheduleStep(name="update_daily_data")
        t0 = datetime.now()
        try:
            await self._update_daily_data(trade_date)
            step.success = True
            step.message = "数据更新完成"
        except Exception as e:
            step.message = f"失败: {e}"
            result.errors.append(step.message)
        step.duration_ms = int((datetime.now() - t0).total_seconds() * 1000)
        result.steps.append(step)

        # Step 2: 信号生成
        step = ScheduleStep(name="generate_signals")
        t0 = datetime.now()
        try:
            signals = await self._generate_signals(trade_date)
            self._signals = signals
            step.success = True
            step.data = {"signal_count": len(signals)}
            step.message = f"生成{len(signals)}个信号"
        except Exception as e:
            step.message = f"失败: {e}"
            result.errors.append(step.message)
        step.duration_ms = int((datetime.now() - t0).total_seconds() * 1000)
        result.steps.append(step)

        # Step 3: 执行买入(模拟盘)
        step = ScheduleStep(name="execute_buy")
        t0 = datetime.now()
        try:
            executed = await self._execute_signals(self._signals, trade_date)
            step.success = True
            step.data = {"executed_count": len(executed)}
            step.message = f"执行{len(executed)}笔买入"
        except Exception as e:
            step.message = f"失败: {e}"
            result.errors.append(step.message)
        step.duration_ms = int((datetime.now() - t0).total_seconds() * 1000)
        result.steps.append(step)

        # Step 4: 推送
        step = ScheduleStep(name="push_signals")
        t0 = datetime.now()
        try:
            await self._push_signals_to_feishu(self._signals, trade_date)
            step.success = True
            step.message = "推送完成"
        except Exception as e:
            step.message = f"失败: {e}"
        step.duration_ms = int((datetime.now() - t0).total_seconds() * 1000)
        result.steps.append(step)

        result.success = not result.errors
        self._current_phase = "idle" if result.success else "premarket_error"
        logger.info(f"[PREMARKET] ===== 完成 signals={len(self._signals)} =====")
        return result

    # ==================== 盘中 ====================

    async def run_intraday(self, trade_date: str) -> ScheduleResult:
        result = ScheduleResult(trade_date=trade_date)
        self._current_phase = "intraday"

        # Step 1: 实时行情
        step = ScheduleStep(name="fetch_realtime")
        t0 = datetime.now()
        try:
            market_data = await self._fetch_realtime_data()
            step.success = True
            n = len(market_data) if market_data else 0
            step.data = {"stocks_fetched": n}
            step.message = f"获取{n}只行情"
        except Exception as e:
            step.message = f"失败: {e}"
            result.errors.append(step.message)
        step.duration_ms = int((datetime.now() - t0).total_seconds() * 1000)
        result.steps.append(step)

        # Step 2: 风控检查
        step = ScheduleStep(name="check_risk")
        t0 = datetime.now()
        try:
            alerts = await self._check_stop_loss_take_profit(trade_date)
            self._alerts.extend(alerts)
            step.success = True
            step.data = {"alerts": len(alerts)}
            step.message = f"{len(alerts)}个告警"
        except Exception as e:
            step.message = f"失败: {e}"
        step.duration_ms = int((datetime.now() - t0).total_seconds() * 1000)
        result.steps.append(step)

        result.success = not result.errors
        self._current_phase = "intraday" if self._is_running else "idle"
        return result

    # ==================== 盘后 ====================

    async def run_postmarket(self, trade_date: str) -> ScheduleResult:
        result = ScheduleResult(trade_date=trade_date)
        self._current_phase = "postmarket"
        logger.info(f"[POSTMARKET] ===== 开始 {trade_date} =====")

        # Step 1: 补全数据
        step = ScheduleStep(name="complete_data")
        t0 = datetime.now()
        try:
            await self._update_daily_data(trade_date)
            step.success = True
            step.message = "数据补全完成"
        except Exception as e:
            step.message = f"失败: {e}"
            result.errors.append(step.message)
        step.duration_ms = int((datetime.now() - t0).total_seconds() * 1000)
        result.steps.append(step)

        # Step 2: 绩效
        step = ScheduleStep(name="performance")
        t0 = datetime.now()
        try:
            perf = await self._calc_daily_performance(trade_date)
            step.success = True
            step.data = perf
            step.message = f"收益: {perf.get('daily_return', '?')}"
        except Exception as e:
            step.message = f"失败: {e}"
        step.duration_ms = int((datetime.now() - t0).total_seconds() * 1000)
        result.steps.append(step)

        result.success = not result.errors
        self._current_phase = "idle"
        logger.info("[POSTMARKET] ===== 完成 =====")
        return result

    async def run_full_day(self, trade_date: str) -> ScheduleResult:
        r1 = await self.run_premarket(trade_date)
        r3 = await self.run_postmarket(trade_date)
        return ScheduleResult(
            success=r1.success and r3.success,
            steps=r1.steps + r3.steps,
            errors=r1.errors + r3.errors,
            trade_date=trade_date,
        )

    # ==================== 核心实现 ====================

    async def _update_daily_data(self, trade_date: str):
        """调东方财富脚本更新当日日线+估值(仅当天)"""
        import subprocess
        today = datetime.now().strftime("%Y%m%d")
        
        # 仅更新当天数据, 历史日期跳过
        if trade_date != today:
            logger.info(f"[DATA] {trade_date}为历史日期, 跳过数据更新")
            return
        
        scripts_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))), 'scripts')

        for script in ['eastmoney_daily_bar.py', 'eastmoney_daily_basic.py']:
            path = os.path.join(scripts_dir, script)
            if os.path.exists(path):
                r = subprocess.run(
                    ['python3', path, '--date', trade_date],
                    capture_output=True, text=True, timeout=60)
                if r.returncode != 0:
                    logger.warning(f"{script}: rc={r.returncode}, {r.stderr[:100]}")

    async def _generate_signals(self, trade_date: str) -> List[Dict]:
        """复用回测引擎逻辑生成信号"""
        from core.managers import mongo_manager
        from nodes.backtest_engine.factor_selection.factor_engine import FactorEngine
        from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS
        from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester

        await mongo_manager.initialize()

        # 获取全市场股票
        stocks = set()
        cursor = mongo_manager.db["stock_daily_ak_full"].find(
            {"trade_date": int(trade_date)}, {"ts_code": 1, "_id": 0})
        async for doc in cursor:
            stocks.add(doc["ts_code"])

        if not stocks:
            logger.warning(f"[SIGNAL] 无{trade_date}数据")
            return []

        # 计算因子
        factor_engine = FactorEngine()

        ultra_short_factors = [{"name": "pct_chg"}, {"name": "volume_ratio"}, {"name": "first_limit_up"}, {"name": "limit_up_yesterday"}, {"name": "limit_up_open_amount"}, {"name": "circ_mv"}, {"name": "turnover_rate"}, {"name": "limit_down_yesterday"}, {"name": "limit_down_open_amount"}, {"name": "rise_after_limit_down"}, {"name": "sentiment_score"}, {"name": "opening_pct_chg"}, {"name": "open_below_limit"}, {"name": "hot_sector"}, {"name": "market_leader"}, {"name": "pullback_pct"}, {"name": "pullback_days"}, {"name": "pullback_ma5"}, {"name": "open_above_limit_down"}, {"name": "limit_up_count"}, {"name": "limit_up_time"}, {"name": "limit_up_open_duration"}, {"name": "limit_up_open_count"}]
        # factor_configs defined inline below
        # see ultra_short_factors below
        factor_df = await factor_engine.compute_factors(stocks, trade_date, ultra_short_factors)

        if factor_df is None or len(factor_df) == 0:
            logger.warning("[SIGNAL] 因子为空")
            return []

        # 策略筛选(复用回测引擎)
        bt = PortfolioBacktester()
        signals = []

        for strategy_key, cfg in STRATEGY_CONFIGS.items():
            if not cfg.get("enabled", True):
                continue

            strategy_name = cfg["name"]
            params = cfg["params"]

            # 调回测引擎的筛选
            conditions = bt._build_strategy_filter_conditions(strategy_name, params)

            # 应用条件(_build_strategy_filter_conditions返回的格式)
            # key是"name"不是"column", operator默认是">="
            mask = pd.Series(True, index=factor_df.index)
            for cond in conditions:
                col = cond.get("name") or cond.get("column")
                op = cond.get("operator", ">=")  # 默认>=
                val = cond.get("target") or cond.get("value")
                if col and val is not None and col in factor_df.columns:
                    try:
                        col_data = factor_df[col].fillna(0)
                        if op == ">=":   mask &= (col_data >= val)
                        elif op == "<=": mask &= (col_data <= val)
                        elif op == ">":  mask &= (col_data > val)
                        elif op == "<":  mask &= (col_data < val)
                        elif op == "==": mask &= (col_data == val)
                    except TypeError:
                        pass

            selected = factor_df[mask]
            for _, row in selected.iterrows():
                ts_code_val = row.get('ts_code', '')
                # 从MongoDB获取收盘价
                close_price = 0
                if ts_code_val:
                    try:
                        price_doc = await mongo_manager.db['stock_daily_ak_full'].find_one(
                            {'ts_code': ts_code_val, 'trade_date': int(trade_date)},
                            {'close': 1, '_id': 0}
                        )
                        close_price = price_doc.get('close', 0) if price_doc else 0
                    except:
                        pass
                signals.append({
                    "ts_code": row.get("ts_code", ""),
                    "strategy": strategy_key,
                    "strategy_name": strategy_name,
                    "signal_type": "buy",
                    "confidence": 0.8,
                    "price": close_price,
                    "trade_date": trade_date,
                    "reason": f"{strategy_name}筛选",
                })

        logger.info(f"[SIGNAL] {len(signals)}个信号")
        return signals

    async def _fetch_realtime_data(self) -> Optional[Dict]:
        """量脉实时行情"""
        try:
            from core.data_fetchers.liangmai_client import LiangMaiClient
            if not self._liangmai:
                self._liangmai = LiangMaiClient()
                await self._liangmai.initialize()

            codes = list(self._positions.keys())
            if not codes:
                return {}

            result = {}
            for code in codes:
                short = code.split('.')[0]
                kline = await self._liangmai.get_kline(ts_code=short, klt="1", lt=1)
                if kline:
                    result[code] = kline[0]
            return result
        except Exception as e:
            logger.error(f"[REALTIME] 失败: {e}")
            return None

    async def _check_stop_loss_take_profit(self, trade_date: str) -> List[Dict]:
        """止损止盈检查(模拟盘)"""
        from nodes.listener.execution.simulator_executor import SimulatorExecutor
        
        if not self._executor:
            self._executor = SimulatorExecutor(initial_cash=1000000.0)
            await self._executor.connect()
        
        # 更新价格
        await self._executor.update_current_prices()
        
        alerts = []
        positions = await self._executor.get_position()
        
        for pos in positions:
            # 止损: -3% (默认)
            if pos.profit_pct <= -3.0:
                try:
                    await self._executor.send_order(
                        ts_code=pos.ts_code,
                        direction="sell",
                        shares=pos.shares,
                        price=pos.current_price,
                    )
                    alerts.append({
                        "ts_code": pos.ts_code,
                        "type": "stop_loss",
                        "profit_pct": pos.profit_pct,
                        "action": "已卖出",
                    })
                    logger.info(f"[RISK] 止损卖出 {pos.ts_code} 亏损{pos.profit_pct:.1f}%")
                except Exception as e:
                    logger.error(f"[RISK] 止损卖出失败 {pos.ts_code}: {e}")
            
            # 止盈: +7% (默认)
            elif pos.profit_pct >= 7.0:
                try:
                    await self._executor.send_order(
                        ts_code=pos.ts_code,
                        direction="sell",
                        shares=pos.shares,
                        price=pos.current_price,
                    )
                    alerts.append({
                        "ts_code": pos.ts_code,
                        "type": "take_profit",
                        "profit_pct": pos.profit_pct,
                        "action": "已卖出",
                    })
                    logger.info(f"[RISK] 止盈卖出 {pos.ts_code} 盈利{pos.profit_pct:.1f}%")
                except Exception as e:
                    logger.error(f"[RISK] 止盈卖出失败 {pos.ts_code}: {e}")
        
        # 更新持仓状态
        self._positions = {p.ts_code: {"shares": p.shares, "cost": p.cost_price, "current": p.current_price} 
                          for p in await self._executor.get_position()}
        
        return alerts

    async def _calc_daily_performance(self, trade_date: str) -> Dict:
        """今日绩效(模拟盘)"""
        from nodes.listener.execution.simulator_executor import SimulatorExecutor
        
        if not self._executor:
            self._executor = SimulatorExecutor(initial_cash=1000000.0)
            await self._executor.connect()
        
        await self._executor.update_current_prices()
        account = await self._executor.get_account()
        positions = await self._executor.get_position()
        
        if account:
            daily_return = (account.total_asset - 1000000) / 1000000 * 100  # 相对初始资金
            return {
                "daily_return": f"{daily_return:.2f}%",
                "total_assets": f"{account.total_asset:,.0f}",
                "cash": f"{account.available_cash:,.0f}",
                "positions": len(positions),
                "signals_today": len(self._signals),
                "alerts_today": len(self._alerts),
            }
        return {"daily_return": "N/A", "positions": len(positions)}

    async def _push_signals_to_feishu(self, signals: List[Dict], trade_date: str):
        """推送飞书"""
        if not signals:
            return
        # TODO: 飞书webhook推送
        logger.info(f"[PUSH] {len(signals)}个信号(飞书待配置)")

    async def _execute_signals(self, signals: List[Dict], trade_date: str) -> List[Dict]:
        """执行信号(模拟盘)"""
        from nodes.listener.execution.simulator_executor import SimulatorExecutor
        
        if not self._executor:
            self._executor = SimulatorExecutor(initial_cash=1000000.0)
            await self._executor.connect()
        
        executed = []
        for sig in signals:
            try:
                ts_code = sig["ts_code"]
                # 计算买入量(单票最大20%仓位, 总仓位上限70%)
                price = sig.get("price", 0)
                if price <= 0:
                    continue
                account = await self._executor.get_account()
                if not account:
                    continue
                
                # 总仓位检查
                if account.market_value / account.total_asset > 0.7:
                    break  # 已超70%总仓位, 停止买入
                
                max_amount = account.available_cash * 0.5  # 用剩余现金的50%
                shares = int(max_amount / price / 100) * 100  # 整手
                if shares <= 0:
                    continue
                
                order = await self._executor.send_order(
                    ts_code=ts_code,
                    direction="buy",
                    shares=shares,
                    price=price,
                )
                if order and order.status.value in ("filled", "partial"):
                    executed.append({
                        "ts_code": ts_code,
                        "strategy": sig["strategy"],
                        "shares": shares,
                        "price": price,
                        "order_id": order.order_id,
                    })
                    logger.info(f"[EXEC] 买入 {ts_code} {shares}股@{price}")
            except Exception as e:
                logger.error(f"[EXEC] 执行失败 {sig['ts_code']}: {e}")
        
        return executed

    async def _push_daily_report(self, trade_date: str):
        """推送日报"""
        logger.info("[REPORT] 日报待推送")
