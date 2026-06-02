"""
RiskLoopRunner — MarketScanner风控循环逻辑

从scanner.py提取的风控循环方法集，职责:
1. 风控独立线程主循环(_risk_loop_sync)
2. 风控tick处理(_risk_tick_body)
3. 周期性检查(跌停超时+quick check)
4. 行情缓存过期检测
5. 错误退避+异常事件

设计原则:
- threading.Thread运行，不受asyncio事件循环影响
- 1秒止损检查(缓存数据, 零API成本)
- 30秒完整quick check
- 职责: 只负责卖出, 不负责买入
"""

import asyncio
import logging
import time
from datetime import datetime

from nodes.market_monitor.scanner_event_bus import ScannerEvents
from nodes.market_monitor.market_phase import MarketPhase

logger = logging.getLogger("scanner.risk_loop")


class RiskLoopRunner:
    """风控循环方法集(混入类)

    用法: MarketScanner继承此类，自动获得_risk_loop_sync系列方法。
    """

    def _risk_loop_sync(self) -> None:
        """风控独立线程(分级节奏，不受asyncio事件循环影响)

        设计原则:
        - threading.Thread(真并行, 不受asyncio协作式调度影响)
        - 1秒止损检查(用缓存数据, 零API成本)
        - 30秒完整quick check(东财缓存, 零额度)
        - 职责: 只负责卖出, 不负责买入
        - 跌停不可卖: 挂起pending_sells, 不丢追踪止损
        - 【v2.9.28】提取_risk_non_trading_sleep/_check_stale_quote_cache/_risk_periodic_checks
        - 【v2.9.56】循环体提取为_risk_tick_body
        - 【v2.9.67】提取到RiskLoopRunner混入类
        """
        tick = 0
        consecutive_errors = 0
        logger.info("[RISK_THREAD] 风控线程启动")

        while self._risk_running:
            try:
                tick += 1
                consecutive_errors = 0
                self._risk_tick_body(tick)
            except Exception as e:
                consecutive_errors += 1
                logger.error(f"[RISK_THREAD] 风控线程异常({consecutive_errors}次): {e}")
                self._emit_risk_thread_error(e, consecutive_errors)
                sleep_s = self._risk_error_backoff(consecutive_errors, e)
                time.sleep(sleep_s)
                continue
            time.sleep(1)

        logger.info("[RISK_THREAD] 风控线程已退出")

    def _risk_tick_body(self, tick: int) -> None:
        """风控线程单次循环体【v2.9.56从_risk_loop_sync提取】

        包含: 阶段判断→行情读取→过期检测→止损检查→周期性检查
        """
        phase = MarketPhase.classify()
        sleep_s = self._risk_non_trading_sleep(phase)
        if sleep_s > 0:
            time.sleep(sleep_s)
            return

        with self._cache_lock:
            realtime_data = dict(self._realtime_cache) if self._realtime_cache else {}

        if not realtime_data or not self._broker:
            time.sleep(1)
            return

        self._check_stale_quote_cache(tick, phase)

        # 每1秒: 止损检查
        self._check_stop_loss_only(realtime_data)
        self._last_risk_check_ts = time.time()

        # 周期性检查(60秒/30秒)
        self._risk_periodic_checks(tick)

    def _risk_periodic_checks(self, tick: int) -> None:
        """风控线程周期性检查(60秒跌停超时+30秒quick check)【v2.9.30提取】"""
        # 60秒: 跌停挂起超时检查
        if tick % 60 == 0 and self._position_manager:
            try:
                self._position_manager.check_pending_sells_timeout()
            except (RuntimeError, KeyError, AttributeError) as e:
                logger.debug(f"[RISK_THREAD] pending_sells超时检查异常: {e}")

        # 30秒: 完整quick check(东财缓存, 零额度)
        if tick % 30 == 0 and self._loop and not self._loop.is_closed():
            try:
                risk_trade_date = self._trade_date or datetime.now().strftime("%Y%m%d")
                future = asyncio.run_coroutine_threadsafe(
                    self._check_positions_quick(risk_trade_date),
                    self._loop
                )
                future.result(timeout=10)
            except (RuntimeError, KeyError, TimeoutError, asyncio.TimeoutError) as e:
                logger.debug(f"[RISK_THREAD] quick check异常: {e}")

    @staticmethod
    def _risk_non_trading_sleep(phase: str) -> int:
        """非交易时间返回sleep秒数, 交易时间返回0【v2.9.28提取】"""
        if phase == MarketPhase.WEEKEND:
            return 60
        elif phase == MarketPhase.DEEP_NIGHT:
            return 300
        elif phase not in (MarketPhase.TRADING, MarketPhase.AUCTION):
            return 30
        return 0

    def _check_stale_quote_cache(self, tick: int, phase: str) -> None:
        """交易时间内行情缓存过期检测+告警【v2.9.28从_risk_loop_sync提取】"""
        if phase != MarketPhase.TRADING:
            return
        if not self._last_realtime_update_ts:
            return
        cache_age = time.time() - (self._last_realtime_update_ts or 0)
        if cache_age <= 120:
            return
        logger.warning(f"[RISK_THREAD] 行情缓存过期({cache_age:.0f}秒), 风控精度下降")
        if tick % 300 == 0:
            try:
                if self._loop and not self._loop.is_closed():
                    self._loop.call_soon_threadsafe(
                        lambda: self._loop.create_task(self._event_bus.emit(ScannerEvents.SCANNER_ERROR, {
                            "error": f"行情缓存过期{cache_age:.0f}秒",
                            "error_type": "StaleQuoteCache",
                            "timestamp": time.time(),
                        }))
                    )
            except Exception as _e:
                logger.debug(f"[RISK] 行情缓存过期事件发射失败: {_e}")

    @staticmethod
    def _risk_error_backoff(consecutive_errors: int, error: Exception) -> int:
        """风控线程错误退避sleep秒数【v2.9.28从_risk_loop_sync提取】"""
        if consecutive_errors >= 10:
            return 30
        elif consecutive_errors >= 3:
            return 5
        return 1

    def _emit_risk_thread_error(self, error: Exception, consecutive_errors: int) -> None:
        """风控线程异常事件发射 — 委托给RiskWatchdog【v2.9.39提取】"""
        from nodes.market_monitor.risk_watchdog import RiskWatchdog
        RiskWatchdog.emit_risk_thread_error(self, error, consecutive_errors)
