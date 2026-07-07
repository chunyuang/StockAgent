"""
ScanLoopRunner — MarketScanner扫描循环逻辑

从scanner.py提取的扫描循环方法集，职责:
1. 主扫描循环(_scan_loop)
2. 阶段处理(周末/盘前/盘后/交易)
3. 交易时间逻辑(看门狗+行情恢复+全量扫描)
4. 异常恢复

设计原则:
- 所有方法通过self访问scanner属性(混入模式)
- 不持有独立状态
"""

import asyncio
import logging
import threading
import time
from datetime import datetime
from typing import Dict

from nodes.market_monitor.scanner_event_bus import ScannerEvents
from nodes.market_monitor.market_phase import MarketPhase

logger = logging.getLogger("scanner.scan_loop")


class ScanLoopRunner:
    """扫描循环方法集(混入类)

    用法: MarketScanner继承此类+ScannerInitializer，自动获得_scan_loop系列方法。
    """

    async def _scan_loop(self, trade_date: str) -> None:
        """主扫描循环(双层节奏 + 智能刷新)

        全量扫描(5分钟): 涨停池+策略筛选 → 发现新信号
        持仓检查(30秒): 只查持仓股行情 → 止损止盈

        【v2.9.55】阶段处理提取为_handle_*_phase方法
        【v2.9.67】提取到ScanLoopRunner混入类
        """
        settled = False
        last_full_scan = 0

        if self._replay_mode:
            await self._scan_loop_replay()
            return

        try:
            while self._is_running:
                phase = MarketPhase.classify()

                if phase == MarketPhase.WEEKEND:
                    await self._handle_weekend_phase(trade_date)

                elif MarketPhase.is_in_trading(phase):
                    settled = False
                    did_full_scan = await self._scan_loop_trading(trade_date, last_full_scan)
                    if did_full_scan:
                        last_full_scan = time.time()
                    else:
                        continue

                elif phase in (MarketPhase.PREMARKET, MarketPhase.AUCTION):
                    settled = False
                    await self._handle_premarket_phase(trade_date)

                elif phase == MarketPhase.AFTER_CLOSE:
                    if not settled and self._broker:
                        await self._scan_loop_settlement(trade_date)
                        settled = True
                    await asyncio.sleep(60)

                else:
                    await asyncio.sleep(self._scan_loop_phase_sleep(phase))

        except asyncio.CancelledError:
            pass
        except Exception as e:
            await self._scan_loop_error_recovery(e)

    async def _handle_weekend_phase(self, trade_date: str) -> None:
        """周末阶段: 持仓检查+低频休眠【v2.9.55从_scan_loop提取】"""
        pos_count = len(self.get_positions())
        if pos_count > 0:
            try:
                await self._check_positions_quick(trade_date)
            except (RuntimeError, KeyError, ValueError) as e:
                logger.debug(f"[SCANNER] 周末持仓检查异常: {e}")
        await asyncio.sleep(60)

    async def _handle_premarket_phase(self, trade_date: str) -> None:
        """盘前竞价阶段【v2.9.55从_scan_loop提取】
        
        9:00-9:15: 仅检查持仓跳空 (premarket_auction)
        9:15-9:25: 运行全市场竞价扫描 (premarket_scan) 生成今日候选
        """
        from datetime import datetime
        ct = datetime.now().strftime("%H:%M")
        # 持仓跳空检查(轻量)
        await self._premarket_auction(trade_date)
        # 竞价窗口全市场扫描(重要!)
        if "09:15" <= ct < "09:30":
            try:
                await self.premarket_scan(trade_date)
            except Exception as e:
                logger.error(f"[SCAN-LOOP] 竞价扫描异常: {e}")
        await asyncio.sleep(60 if "09:15" <= ct < "09:30" else 120)

    @staticmethod
    def _scan_loop_phase_sleep(phase) -> int:
        """非交易时间scan_loop的sleep秒数【v2.9.28提取】"""
        if phase == MarketPhase.DEEP_NIGHT:
            return 1800
        return 300

    async def _scan_loop_error_recovery(self, error: Exception) -> None:
        """_scan_loop异常恢复【v2.9.28从_scan_loop提取】"""
        logger.error(f"[SCANNER] _scan_loop异常: {error}", exc_info=True)
        self._scan_loop_error_count += 1
        if self._scan_loop_error_count >= 3:
            logger.error(f"[SCANNER] 连续{self._scan_loop_error_count}次异常, scanner退出")
            self._is_running = False
        else:
            logger.warning(f"[SCANNER] 第{self._scan_loop_error_count}次异常, 30秒后尝试恢复")
            await asyncio.sleep(30)
        try:
            if self._loop and not self._loop.is_closed():
                self._loop.call_soon_threadsafe(
                    lambda: self._loop.create_task(self._event_bus.emit(ScannerEvents.SCANNER_ERROR, {
                        "error": str(error),
                        "error_type": type(error).__name__,
                        "timestamp": time.time(),
                        "consecutive_errors": self._scan_loop_error_count,
                    }))
                )
        except Exception as _e:
            logger.debug(f"[SCAN_LOOP] 错误恢复事件发射失败: {_e}")

    async def _scan_loop_trading(self, trade_date: str, last_full_scan: float) -> bool:
        """交易时间(9:30-15:00)处理逻辑

        职责: 风控线程看门狗 + 行情恢复 + 全量扫描/等待
        Returns: True=全量扫描完成(更新last_full_scan), False=等待中

        【v2.9.54:scan_once异常不向上传播,返回False让主循环继续】
        【v2.9.70:尾盘(14:30+)禁止新开仓,只做持仓检查】
        """
        self._restart_risk_thread_if_dead()
        await self._try_recover_quote_source()

        # 尾盘只做持仓检查,不做全量扫描(避免新开仓)
        phase = MarketPhase.classify()
        if phase == MarketPhase.LATE_TRADING:
            try:
                realtime_data = await self._fetch_realtime_batch()
                await self._check_positions(realtime_data, trade_date)
                self._sync_broker_prices(realtime_data)
                await asyncio.sleep(3)
                return False
            except Exception as e:
                logger.error(f"[SCAN_LATE] 尾盘持仓检查异常: {e}")
                await asyncio.sleep(5)
                return False

        elapsed = time.time() - last_full_scan
        if elapsed >= self.SCAN_INTERVAL:
            try:
                await self.scan_once(trade_date)
                return True
            except Exception as e:
                import traceback
                logger.error(f"[SCAN_TRADING] scan_once异常: {e}\n{traceback.format_exc()}")
                self._scan_loop_error_count += 1
                return False
        else:
            # 【v2.9.117】非全量扫描轮: 定期刷新行情+持仓检查, 避免两次全量扫描之间行情缓存陈旧
            # 之前: 只sleep(check_interval) → 风控线程用5分钟前价格做止损
            check_interval = self._get_smart_check_interval(self._broker.get_positions() if self._broker else [])
            # 30秒刷新一次行情(不全量, 用东财TTL缓存: <5s返回缓存, >5s才拉API)
            quote_age = time.monotonic() - getattr(self._quote_manager, '_last_fetch_time', 0)
            if quote_age > 30:
                try:
                    realtime_data = await self._fetch_realtime_batch(force=False)
                    if realtime_data:
                        await self._check_positions(realtime_data, trade_date)
                        self._sync_broker_prices(realtime_data)
                except Exception as e:
                    logger.debug(f"[SCAN_LOOP] 行情刷新异常(非致命): {e}")
            await asyncio.sleep(check_interval)
            return False

    def _restart_risk_thread_if_dead(self) -> None:
        """风控线程看门狗: 检测线程退出并自动重启【v2.9.54从_scan_loop_trading提取】"""
        if not (self._risk_running and self._risk_thread and not self._risk_thread.is_alive()):
            return
        self._risk_thread_restarts += 1
        logger.warning(
            f"[RISK_WATCHDOG] 风控线程已退出(第{self._risk_thread_restarts}次重启)"
        )
        self._risk_running = True
        self._risk_thread = threading.Thread(
            target=self._risk_loop_sync, daemon=True,
            name="scanner-risk-thread",
        )
        self._risk_thread.start()
        if self._risk_thread_restarts >= 3:
            try:
                asyncio.create_task(self._publish_scanner_event("status", {
                    "event": "risk_thread_unstable",
                    "restarts": self._risk_thread_restarts,
                }))
            except RuntimeError:
                pass

    async def _try_recover_quote_source(self) -> None:
        """行情降级自动恢复尝试【v2.9.54从_scan_loop_trading提取】"""
        if not self._quote_manager.should_try_recover():
            return
        try:
            recovered = await self._quote_manager.try_recover()
            if recovered:
                self._quote_degrade_level = self._quote_manager.degrade_level
                await self._publish_scanner_event("status", {
                    "event": "quote_recovered",
                    "degrade_level": 0,
                })
        except (ConnectionError, OSError, TimeoutError) as e:
            logger.debug(f"[SCAN] 行情恢复尝试异常: {e}")

    async def _scan_loop_settlement(self, trade_date: str) -> None:
        """盘后结算(15:05+) — 委托给RuntimePersistence【v2.9.39提取】"""
        await self._runtime_persistence.daily_settlement(trade_date)

    async def _scan_loop_replay(self) -> None:
        """回放模式循环: 不受交易时间限制, 持续扫描【v2.9.19提取】"""
        logger.info(f"[REPLAY] 回放循环启动, 日期={self._replay_date}")
        while self._is_running:
            trade_date = self._replay_date or datetime.now().strftime("%Y%m%d")
            await self.scan_once(trade_date, force=True)
            await asyncio.sleep(self.SCAN_INTERVAL)
