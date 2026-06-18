"""
PositionChecker — 持仓检查与卖出执行引擎

从MarketScanner拆分出来(Phase3.1)。
负责:
- 持仓止损止盈检查(legacy/quick/checker/compare四种模式)
- 卖出执行(含跌停挂起、dry_run、P1-7修复)
- 超时强卖
- 移动止损(盈利保护)
- 追踪止损更新
- 智能检查频率
- 危出后清理+持久化

设计原则:
1. 卖出逻辑灰度开关: SELL_LOGIC_MODE环境变量
2. 跌停不可卖→pending_sells挂起机制
3. 追踪止损状态留在Scanner, checker只做判断(与回测一致)
4. 不影响策略回测模块

v2.9.38: _run_checker_on_positions提取(消除checker/compare重复遍历)
         _post_sell_state_cleanup提取(3处卖出后清理统一)
         compare差异MongoDB持久化(sell_compare_diff集合)
"""

import logging
import os
import threading
import time
from datetime import datetime
from typing import Dict, List, Any, Tuple, Optional
from dataclasses import dataclass, field

logger = logging.getLogger("position_checker")


# ==================== 灰度对齐追踪器【v2.9.69】 ====================

@dataclass
class CompareAlignmentStats:
    """compare模式对齐度统计【v2.9.69新增, v2.9.70持久化+通知】
    
    累积compare模式运行结果, 量化legacy与checker的对齐程度。
    当对齐度>=95%时, 可安全切换到checker模式。
    
    v2.9.70增强:
    - 持久化到MongoDB(scanner_alignment_stats集合)
    - switch_ready变更时发射事件通知
    - from_dict类方法支持重启恢复
    """
    total_checks: int = 0          # 总检查次数
    total_positions: int = 0       # 总持仓检查次数(含多持仓单次check)
    agreement_count: int = 0       # 完全一致次数(legacy==checker)
    only_legacy_count: int = 0     # 仅legacy触发卖出次数
    only_checker_count: int = 0    # 仅checker触发卖出次数
    both_count: int = 0            # 两边都触发卖出次数
    last_check_time: str = ""      # 最近一次check时间
    first_check_time: str = ""     # 首次check时间
    consecutive_agree: int = 0     # 连续一致次数
    max_consecutive_agree: int = 0 # 最大连续一致次数
    _notified_switch_ready: bool = False  # 是否已通知可切换【v2.9.70】

    @property
    def alignment_rate(self) -> float:
        """对齐率: 完全一致占比(0.0~1.0)"""
        return self.agreement_count / self.total_checks if self.total_checks > 0 else 0.0

    @property
    def coverage_rate(self) -> float:
        """覆盖率: checker触发卖出中与legacy重合的比例(0.0~1.0)"""
        checker_sells = self.both_count + self.only_checker_count
        return self.both_count / checker_sells if checker_sells > 0 else 0.0

    @property
    def switch_ready(self) -> bool:
        """是否可以安全切换到checker模式(需满足3个条件)"""
        return (
            self.total_checks >= 50           # 至少50次compare
            and self.alignment_rate >= 0.95   # 对齐率>=95%
            and self.consecutive_agree >= 20  # 最近20次连续一致
        )

    def record(self, only_legacy: set, only_checker: set, both: set) -> bool:
        """记录一次compare结果
        
        Returns:
            True if switch_ready状态发生变更(从未就绪→就绪)
        """
        was_ready = self.switch_ready
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.total_checks += 1
        self.total_positions += len(only_legacy) + len(only_checker) + len(both)
        self.only_legacy_count += len(only_legacy)
        self.only_checker_count += len(only_checker)
        self.both_count += len(both)
        self.last_check_time = now
        if not self.first_check_time:
            self.first_check_time = now

        if not only_legacy and not only_checker:
            self.agreement_count += 1
            self.consecutive_agree += 1
            self.max_consecutive_agree = max(self.max_consecutive_agree, self.consecutive_agree)
        else:
            self.consecutive_agree = 0
        
        # 检查switch_ready状态变更【v2.9.70】
        became_ready = not was_ready and self.switch_ready
        if became_ready:
            self._notified_switch_ready = True
        return became_ready

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "total_checks": self.total_checks,
            "total_positions": self.total_positions,
            "agreement_count": self.agreement_count,
            "only_legacy_count": self.only_legacy_count,
            "only_checker_count": self.only_checker_count,
            "both_count": self.both_count,
            "alignment_rate": round(self.alignment_rate, 4),
            "coverage_rate": round(self.coverage_rate, 4),
            "switch_ready": self.switch_ready,
            "consecutive_agree": self.consecutive_agree,
            "max_consecutive_agree": self.max_consecutive_agree,
            "last_check_time": self.last_check_time,
            "first_check_time": self.first_check_time,
            "notified_switch_ready": self._notified_switch_ready,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CompareAlignmentStats':
        """从字典恢复统计【v2.9.70:重启恢复】
        
        Args:
            data: to_dict()序列化的字典
            
        Returns:
            恢复后的CompareAlignmentStats实例
        """
        if not isinstance(data, dict):
            return cls()
        stats = cls()
        stats.total_checks = int(data.get("total_checks", 0))
        stats.total_positions = int(data.get("total_positions", 0))
        stats.agreement_count = int(data.get("agreement_count", 0))
        stats.only_legacy_count = int(data.get("only_legacy_count", 0))
        stats.only_checker_count = int(data.get("only_checker_count", 0))
        stats.both_count = int(data.get("both_count", 0))
        stats.consecutive_agree = int(data.get("consecutive_agree", 0))
        stats.max_consecutive_agree = int(data.get("max_consecutive_agree", 0))
        stats.last_check_time = str(data.get("last_check_time", ""))
        stats.first_check_time = str(data.get("first_check_time", ""))
        stats._notified_switch_ready = bool(data.get("notified_switch_ready", False))
        return stats


class PositionChecker:
    """
    持仓检查与卖出执行引擎
    
    用法:
        checker = PositionChecker(scanner)
        await checker.check_positions(realtime_data, trade_date)
        await checker.check_positions_quick(trade_date)
    """
    
    def __init__(self, scanner):
        """
        Args:
            scanner: MarketScanner实例
        """
        self._scanner = scanner
        self._sell_checker = None  # 缓存SellSignalChecker实例
        self._backtester = None   # 缓存PortfolioBacktester实例
        self._alignment_stats = CompareAlignmentStats()  # 灰度对齐统计【v2.9.69】
        self._restore_alignment_stats()  # 重启恢复【v2.9.70】
    
    # ==================== 属性代理 ====================
    
    @property
    def broker(self) -> Any:
        return self._scanner._broker
    
    @property
    def config(self) -> Dict:
        return self._scanner.config
    
    @property
    def sell_logic_mode(self) -> str:
        return self._scanner.SELL_LOGIC_MODE

    @property
    def alignment_stats(self) -> CompareAlignmentStats:
        """灰度对齐统计【v2.9.69】"""
        return self._alignment_stats
    
    @property
    def dry_run(self) -> bool:
        return self._scanner._dry_run
    
    @property
    def realtime_cache(self) -> Dict:
        """读取实时行情缓存(直接引用,仅用于内部加锁场景)"""
        return self._scanner._realtime_cache or {}
    
    @property
    def trailing_stops(self) -> Dict:
        """读取追踪止损状态(直接引用,仅用于内部加锁场景)"""
        return self._scanner._trailing_stops
    
    @property
    def position_risk_levels(self) -> Dict:
        return self._scanner._position_risk_levels
    
    @property
    def state_lock(self) -> threading.Lock:
        """共享状态锁(保护trailing_stops/pending_sells/position_risk_levels)"""
        return self._scanner._state_lock
    
    @property
    def data_router(self) -> Any:
        return self._scanner._data_router
    
    @property
    def execution_stats(self) -> Dict:
        return self._scanner._execution_stats
    
    def _get_sell_checker(self) -> Optional[Any]:
        """获取缓存的SellSignalChecker实例(懒初始化)"""
        if self._sell_checker is not None:
            return self._sell_checker
        try:
            from nodes.backtest_engine.factor_selection.sell_signal_checker import SellSignalChecker
            from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS, GLOBAL_RISK
            strategy_params = {}
            strategy_risk_params = {}
            for strategy_key, cfg in STRATEGY_CONFIGS.items():
                strategy_params[strategy_key] = cfg.get("params", {})
                strategy_risk_params[strategy_key] = cfg.get("riskParams", {})
            self._sell_checker = SellSignalChecker(strategy_params, strategy_risk_params, dict(GLOBAL_RISK))
            return self._sell_checker
        except ImportError:
            logger.warning("[CHECKER] SellSignalChecker不可用")
            return None
    
    def _get_backtester(self) -> Optional[Any]:
        """获取缓存的PortfolioBacktester实例(懒初始化,避免每个持仓重复创建)"""
        if self._backtester is not None:
            return self._backtester
        try:
            from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
            self._backtester = PortfolioBacktester()
            return self._backtester
        except ImportError:
            logger.warning("[CHECKER] PortfolioBacktester不可用")
            return None
    
    def _calc_trade_days_held(self, buy_date, trade_date) -> Optional[int]:
        """计算持仓交易日天数(缓存Backtester实例)"""
        bt = self._get_backtester()
        if bt is None:
            return None
        try:
            return bt._calc_trade_days_held(int(buy_date), int(trade_date))
        except (ValueError, TypeError):
            return None
    
    # ==================== 主入口 ====================
    
    async def check_positions(self, realtime_data: Dict[str, Dict], trade_date: str) -> List[Tuple]:
        """止损止盈+超时强卖检查(灰度开关路由)"""
        mode = self.sell_logic_mode
        if mode == "checker":
            return await self._check_positions_checker(realtime_data, trade_date)
        elif mode == "compare":
            return await self._check_positions_compare(realtime_data, trade_date)
        else:
            return await self._check_positions_legacy(realtime_data, trade_date)
    
    async def check_positions_quick(self, trade_date: str) -> List[Tuple]:
        """持仓快速检查(30秒级, 用东方财富全市场缓存)"""
        scanner = self._scanner
        
        if not self.broker:
            return
        positions = self.broker.get_positions()
        if not positions:
            return
        
        # 风控熔断检查
        if not await scanner._check_circuit_breaker():
            return
        
        # 东方财富: 从缓存获取持仓股价格
        pos_codes = [pos.ts_code for pos in positions]
        if self.data_router:
            eastmoney = self.data_router._sources.get("eastmoney")
            if eastmoney:
                prices = await eastmoney.get_position_prices(pos_codes)
                for ts_code, price in prices.items():
                    if price and price > 0:
                        self.broker.update_realtime(ts_code=ts_code, price=price)
                logger.debug(f"[QUICK] 东方财富更新: {len(prices)}/{len(pos_codes)}只持仓价")
        
        # 回退: 用全量扫描缓存
        for pos in positions:
            if pos.ts_code not in self.realtime_cache:
                continue
            cached = self.realtime_cache.get(pos.ts_code, {})
            if cached.get("price", 0) > 0 and pos.current_price <= 0:
                self.broker.update_realtime(
                    ts_code=pos.ts_code, price=cached["price"],
                    pre_close=cached.get("pre_close", 0),
                )
        
        # 止损止盈检查
        to_sell = scanner._check_stop_loss_take_profit(
            self.broker.get_positions(), self.realtime_cache
        )
        
        # 执行卖出
        await self._execute_sell_list(to_sell, trade_date, source="quick")
    
    # ==================== Legacy模式 ====================
    
    async def _check_positions_legacy(self, realtime_data: Dict[str, Dict], trade_date: str) -> List[Tuple]:
        """原Scanner内嵌卖出逻辑(不变)"""
        scanner = self._scanner
        
        to_sell = scanner._check_stop_loss_take_profit(
            self.broker.get_positions(), realtime_data
        )

        # 超时强卖
        from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK
        for pos in self.broker.get_positions():
            if pos.available_qty <= 0 or not pos.buy_date:
                continue
            risk = scanner._get_strategy_risk(pos.strategy)
            max_hold = risk.get("max_hold_days", GLOBAL_RISK.get("max_hold_days", 999))
            if max_hold >= 999:
                continue
            try:
                days_held = self._calc_trade_days_held(pos.buy_date, trade_date)
                if days_held is not None and days_held >= max_hold:
                    already = any(p.ts_code == pos.ts_code for p, _, _, _ in to_sell)
                    if not already:
                        to_sell.append((pos, f"超时({days_held}日≥{max_hold}日)", pos.current_price, risk))
                        logger.info(f"[TIMEOUT] {pos.ts_code} 持仓{days_held}日≥{max_hold}日, 强制卖出")
            except (ValueError, TypeError):
                pass

        # 移动止损(盈利保护)
        # 【v2.9.89修复+同步】与position_manager.check_moving_stop对齐
        # 旧bug: 条件 `profit_pct/100 > sl_pct*2 and profit_pct < 0` 永远为False
        # (不可能同时>2*sl_pct且<0)
        # 修复: 使用trailing_stop已激活(说明盈利曾>=2%) + 当前亏损 作为触发条件
        for pos in self.broker.get_positions():
            if pos.available_qty <= 0:
                continue
            risk = scanner._get_strategy_risk(pos.strategy)
            # 线程安全读取position_risk_overrides(与position_manager对齐)
            with self.state_lock:
                trailing = dict(self.trailing_stops.get(pos.ts_code, {}))
            if trailing.get("activated") and pos.profit_pct < 0:
                already = any(p.ts_code == pos.ts_code for p, _, _, _ in to_sell)
                if not already:
                    to_sell.append((pos, f"移动止损(盈利回撤至{pos.profit_pct:.1f}%)", pos.current_price, risk))
                    logger.info(f"[TRAILING] {pos.ts_code} 盈利回撤至{pos.profit_pct:.1f}%, 移动止损触发")

        # 执行卖出
        await self._execute_sell_list(to_sell, trade_date, source="legacy")
        await self._post_sell_state_cleanup(to_sell)
    
    # ==================== Checker模式 ====================
    
    async def _check_positions_checker(self, realtime_data: Dict[str, Dict], trade_date: str) -> List[Tuple]:
        """checker卖出逻辑(复用回测SellSignalChecker)【v2.9.38:用_run_checker_on_positions消除重复】"""
        checker = self._get_sell_checker()
        if checker is None:
            logger.warning("[CHECKER] SellSignalChecker不可用, 回退legacy")
            return await self._check_positions_legacy(realtime_data, trade_date)

        positions = self.broker.get_positions()
        if not positions:
            return

        results = self._run_checker_on_positions(checker, positions, realtime_data, trade_date)

        # 按卖出优先级排序(高优先级先执行: 止损>追踪止损>止盈)
        results.sort(key=lambda x: x[4], reverse=True)
        # 去掉priority, 恢复4元组
        to_sell = [(pos, reason, price, risk) for pos, reason, price, risk, _ in results]

        await self._execute_sell_list(to_sell, trade_date, source="checker")
        await self._post_sell_state_cleanup(to_sell)
    
    # ==================== Compare模式 ====================
    
    async def _check_positions_compare(self, realtime_data: Dict[str, Dict], trade_date: str) -> List[Tuple]:
        """compare模式: 两种逻辑都跑, 只执行旧逻辑, 记录差异【v2.9.38+v2.9.70重构】"""
        scanner = self._scanner
        
        # 并行运行legacy+checker
        legacy_sell, checker_results, legacy_codes, checker_codes = \
            self._run_compare_both(realtime_data, trade_date)

        # 记录差异 + 对齐统计
        only_legacy = legacy_codes - checker_codes
        only_checker = checker_codes - legacy_codes
        both = legacy_codes & checker_codes
        await self._handle_compare_stats(only_legacy, only_checker, both)
        
        # 差异通知+持久化
        if only_legacy or only_checker:
            await self._handle_compare_diff(
                trade_date, only_legacy, only_checker, both,
                legacy_sell, checker_results, realtime_data,
            )

        # 只执行legacy逻辑
        await self._check_positions_legacy(realtime_data, trade_date)
    
    def _run_compare_both(self, realtime_data: Dict[str, Dict], trade_date: str) -> Tuple:
        """compare模式: 并行运行legacy+checker, 返回结果集合【v2.9.70提取】
        
        Returns:
            (legacy_sell, checker_results, legacy_codes, checker_codes)
        """
        # Legacy
        legacy_sell = self._scanner._check_stop_loss_take_profit(
            self.broker.get_positions(), realtime_data
        )
        legacy_codes = {p.ts_code for p, _, _, _ in legacy_sell}

        # Checker(使用缓存的实例, 复用_run_checker_on_positions)
        checker_codes = set()
        checker_results = []
        checker = self._get_sell_checker()
        if checker:
            try:
                positions = self.broker.get_positions()
                checker_results = self._run_checker_on_positions(checker, positions, realtime_data, trade_date)
                checker_codes = {pos.ts_code for pos, _, _, _, _ in checker_results}
            except Exception as e:
                logger.debug(f"[COMPARE] checker执行异常: {e}")
        
        return legacy_sell, checker_results, legacy_codes, checker_codes
    
    async def _handle_compare_stats(self, only_legacy: set, only_checker: set, both: set) -> None:
        """对齐统计记录+持久化+switch_ready通知【v2.9.70提取】"""
        became_ready = self._alignment_stats.record(only_legacy, only_checker, both)
        
        # 每10次check或状态变更时持久化
        if self._alignment_stats.total_checks % 10 == 0 or became_ready:
            await self._persist_alignment_stats()
        
        if became_ready:
            logger.info(f"[COMPARE] 🔔 灰度切换就绪! 对齐率={self._alignment_stats.alignment_rate:.1%} "
                         f"连续一致={self._alignment_stats.consecutive_agree} "
                         f"总检查={self._alignment_stats.total_checks}")
            try:
                await self._scanner._publish_scanner_event("alignment_switch_ready", {
                    "alignment_rate": round(self._alignment_stats.alignment_rate, 4),
                    "consecutive_agree": self._alignment_stats.consecutive_agree,
                    "total_checks": self._alignment_stats.total_checks,
                    "recommendation": "可安全切换: 设置 SELL_LOGIC_MODE=checker",
                })
            except Exception as _e:
                logger.debug(f"[COMPARE] switch_ready事件发送失败: {_e}")
    
    async def _handle_compare_diff(self, trade_date: str, only_legacy: set, only_checker: set,
                                     both: set, legacy_sell: list, checker_results: list,
                                     realtime_data: Dict[str, Dict]) -> None:
        """卖出差异通知+持久化【v2.9.70从_check_positions_compare提取】"""
        logger.info(f"[COMPARE] 卖出差异: "
                     f"仅legacy={only_legacy or '{}'} "
                     f"仅checker={only_checker or '{}'} "
                     f"一致={both or '{}'}")
        try:
            await self._scanner._publish_scanner_event("sell_compare", {
                "only_legacy": list(only_legacy),
                "only_checker": list(only_checker),
                "both": list(both),
                "time": datetime.now().strftime("%H:%M:%S"),
            })
        except Exception as _e:
            logger.debug(f"operation failed: {_e}")

        await self._persist_compare_diff(
            trade_date, only_legacy, only_checker, both,
            legacy_sell, checker_results, realtime_data,
        )
    
    # ==================== Checker公共逻辑【v2.9.38提取】 ====================
    
    def _run_checker_on_positions(self, checker, positions, realtime_data: Dict[str, Dict], trade_date: str) -> List[Tuple]:
        """遍历持仓, 运行SellSignalChecker, 返回5元组列表[(pos, reason, price, risk, priority)]
        
        消除checker/compare模式的重复遍历逻辑。
        checker模式使用完整5元组(含priority排序), compare模式只取ts_code。
        
        Args:
            checker: SellSignalChecker实例
            positions: 持仓列表
            realtime_data: 实时行情字典
            trade_date: 交易日期
            
        Returns:
            List of (pos, reason, sell_price, risk, priority) tuples
        """
        scanner = self._scanner
        results = []
        
        for pos in positions:
            if pos.available_qty <= 0:
                continue
            rt = realtime_data.get(pos.ts_code, {})
            if not rt or rt.get("price", 0) <= 0:
                continue

            # 传入trailing_stop_state(状态留在Scanner, checker只做判断)
            with self.state_lock:
                trailing_state = dict(self.trailing_stops[pos.ts_code]) if pos.ts_code in self.trailing_stops else None

            # 计算持仓天数(超时检查需要)
            trade_days_held = self._calc_trade_days_held(pos.buy_date, trade_date) if pos.buy_date else None

            result = checker.check_realtime_sell(
                position=pos,
                realtime_price=rt.get("price", 0),
                high_price=rt.get("high", 0),
                open_price=rt.get("open", 0),
                trailing_stop_state=trailing_state,
                trade_days_held=trade_days_held,
            )

            if result:
                reason = result.get('reason', 'unknown')
                sell_price = result.get('price', rt.get("price", 0))
                priority = result.get('priority', 0)
                risk = scanner._get_strategy_risk(pos.strategy)
                results.append((pos, reason, sell_price, risk, priority))
        
        return results
    
    async def _post_sell_state_cleanup(self, to_sell: List[Tuple]) -> None:
        """卖出后状态清理(线程安全) + 强制持久化【v2.9.38:从3处重复逻辑提取】"""
        if not to_sell:
            return
        scanner = self._scanner
        
        # 线程安全清理trailing_stops/position_risk_levels
        with self.state_lock:
            for pos, reason, _, _ in to_sell:
                self.trailing_stops.pop(pos.ts_code, None)
                self.position_risk_levels.pop(pos.ts_code, None)
        
        # 强制持久化
        # 【v2.9.92s】replay/dry_run模式不应覆盖MongoDB实盘数据
        is_virtual = getattr(self._scanner, '_trade_mode', '') in ('replay', 'dry_run') if hasattr(self, '_scanner') else False
        if self.broker:
            try:
                await self.broker.save_state(force=True, skip_if_virtual=is_virtual)
            except Exception as _e:
                logger.debug(f"[CLEANUP] broker保存失败: {_e}")
            try:
                await scanner._save_runtime_snapshot(force=True)
            except Exception as _e:
                logger.debug(f"[CLEANUP] 运行时快照保存失败: {_e}")
    
    async def _persist_alignment_stats(self) -> None:
        """对齐统计持久化到MongoDB【v2.9.70新增】
        
        存入scanner_alignment_stats集合(单文档,按last_check_time更新)。
        重启时通过_restore_alignment_stats恢复, 避免统计数据丢失。
        """
        try:
            rp = self._scanner._runtime_persistence
            if rp and rp._mongo_db:
                stats_dict = self._alignment_stats.to_dict()
                rp._mongo_db["scanner_alignment_stats"].replace_one(
                    {"_id": "global"},
                    {"_id": "global", **stats_dict},
                    upsert=True,
                )
        except Exception as _e:
            logger.debug(f"[COMPARE] 对齐统计持久化失败: {_e}")
    
    def _restore_alignment_stats(self) -> None:
        """从MongoDB恢复对齐统计【v2.9.70新增】
        
        启动时调用, 恢复上次运行的统计数据。
        如果无历史数据或恢复失败, 使用默认空统计。
        """
        try:
            rp = self._scanner._runtime_persistence
            if rp and rp._mongo_db:
                doc = rp._mongo_db["scanner_alignment_stats"].find_one({"_id": "global"})
                if doc:
                    self._alignment_stats = CompareAlignmentStats.from_dict(doc)
                    logger.info(f"[COMPARE] 对齐统计已恢复: 总检查={self._alignment_stats.total_checks} "
                                f"对齐率={self._alignment_stats.alignment_rate:.1%} "
                                f"连续一致={self._alignment_stats.consecutive_agree}")
        except Exception as _e:
            logger.debug(f"[COMPARE] 对齐统计恢复失败(使用默认): {_e}")
    
    async def _persist_compare_diff(self, trade_date: str, only_legacy: set, only_checker: set,
                                     both: set, legacy_sell: list, checker_results: list,
                                     realtime_data: Dict[str, Dict]) -> None:
        """compare差异持久化 — 委托给RuntimePersistence【v2.9.45提取,v2.9.51:getattr清理】"""
        rp = self._scanner._runtime_persistence
        if rp:
            await rp.persist_compare_diff(
                trade_date, only_legacy, only_checker, both,
                legacy_sell, checker_results, realtime_data,
            )
    
    # ==================== 卖出执行 ====================
    
    async def _execute_sell_list(self, to_sell: List[Tuple], trade_date: str, source: str = "legacy") -> List[Tuple]:
        """执行卖出列表(含跌停挂起、dry_run、P1-7修复)【v2.9.26:提取子方法, v2.9.72:trace_id】"""
        import uuid
        from nodes.market_monitor.market_phase import MarketPhase

        # 【v2.9.98修复】非交易时间禁止卖出(盘后止损卖出是BUG)
        # 允许的时段: 交易时间(09:30-15:00) + 盘后5分钟结算(15:00-15:05)
        phase = MarketPhase.classify()
        if phase in (MarketPhase.AFTER_CLOSE, MarketPhase.OFF_HOURS, MarketPhase.DEEP_NIGHT, MarketPhase.WEEKEND, MarketPhase.PREMARKET):
            blocked = len(to_sell)
            if blocked > 0:
                logger.warning(
                    f"[{source.upper()}] 非交易时间({phase})跳过{blocked}笔卖出: "
                    f"{', '.join(p.ts_code for p, _, _, _ in to_sell[:5])}{'...' if blocked > 5 else ''}"
                )
            return to_sell  # 返回未执行的列表

        for pos, reason, force_price, risk in to_sell:
            if pos.available_qty <= 0:
                continue
            trace_id = f"chk-{pos.ts_code}-{uuid.uuid4().hex[:8]}"
            # 跌停不可卖 → 挂起pending_sells
            if self._is_limit_down(pos.ts_code):
                self._handle_limit_down_pending(pos, reason, risk, source)
                continue
            # dry_run模式
            if self.dry_run:
                self._scanner._add_timeline_log("blocked", pos.ts_code, pos.stock_name,
                    pos.strategy, f"调试模式跳过卖出({reason})", None)
                logger.info(f"[DRY-RUN] 跳过卖出 {pos.ts_code} {reason} trace={trace_id}")
                continue
            # 执行卖出
            ok, msg, order, sell_info = self._place_sell_order(pos, reason, force_price, risk)
            if ok:
                await self._post_sell_processing(pos, order, sell_info, reason, risk, source, trace_id=trace_id)
            else:
                self._scanner._add_timeline_log("blocked", pos.ts_code, pos.stock_name,
                    pos.strategy, f"卖出失败: {msg}", None)
                logger.warning(f"[{source.upper()}] 卖出被拒 {pos.ts_code}: {msg} trace={trace_id}")

    def _handle_limit_down_pending(self, pos, reason: str, risk: Dict, source: str) -> None:
        """跌停不可卖时挂起pending_sells【v2.9.26提取,v2.9.50:移除hasattr防御(_pending_sells在__init__已初始化)】"""
        scanner = self._scanner
        scanner._add_timeline_log("blocked", pos.ts_code, pos.stock_name,
            pos.strategy, f"跌停不可卖(触发{reason}但跌停挂单无法成交)", None)
        with self.state_lock:
            scanner._pending_sells[pos.ts_code] = {
                "reason": reason, "risk": risk,
                "added_at": time.time(), "source": source,
            }
        logger.warning(f"[{source.upper()}] 跌停不可卖: {pos.ts_code} {pos.stock_name}")

    def _place_sell_order(self, pos, reason: str, force_price, risk: Dict) -> Optional[Dict]:
        """下单卖出并返回(ok, msg, order, sell_info)【v2.9.26提取, v2.9.80:用实际成交价计算盈亏】"""
        sell_qty = pos.available_qty
        sell_current_price = pos.current_price
        sell_price = force_price if force_price else sell_current_price
        self.broker.update_realtime(pos.ts_code, sell_price)
        ok, msg, order = self.broker.place_order(
            ts_code=pos.ts_code, stock_name=pos.stock_name,
            side="sell", quantity=sell_qty, price=sell_price,
            order_type="market", strategy=pos.strategy, reason=reason,
        )
        # 【v2.9.80修复】用实际成交价(fill_price)计算盈亏,与broker.order对齐
        # 之前用pos.current_price(决策价)与broker.fill_price(成交价)不一致
        if ok and order and order.filled_price > 0:
            sell_profit_pct = (order.filled_price - pos.avg_cost) / pos.avg_cost * 100 if pos.avg_cost > 0 else 0
            sell_profit_amount = (order.filled_price - pos.avg_cost) * sell_qty
        else:
            sell_profit_pct = pos.profit_pct
            sell_profit_amount = (pos.current_price - pos.avg_cost) * sell_qty
        sell_info = {
            "sell_qty": sell_qty, "sell_profit_pct": sell_profit_pct,
            "sell_profit_amount": sell_profit_amount, "sell_avg_cost": pos.avg_cost,
            "sell_current_price": sell_current_price, "risk": risk,
        }
        return ok, msg, order, sell_info

    async def _post_sell_processing(self, pos, order, sell_info: Dict, reason: str, risk: Dict, source: str, *, trace_id: str = "") -> None:
        """卖出后处理: 委托RuntimePersistence.post_sell_cleanup【v2.9.45重构, v2.9.72:trace_id】
        
        之前: 内联构建timeline+统计+EventBus(63行)
        现在: 统一委托, 与emergency_liquidate/execute_sell_list对齐
        """
        rp = self._scanner._runtime_persistence
        if rp:
            await rp.post_sell_cleanup(
                pos, reason, order, sell_info["sell_qty"],
                sell_info["sell_profit_pct"], sell_info["sell_profit_amount"],
                source=source, trace_id=trace_id,
            )
            # checker专属: 记录止损响应时间
            if "止损" in reason:
                try:
                    self.execution_stats.setdefault("stop_loss_response_times", []).append(time.time())
                    if len(self.execution_stats["stop_loss_response_times"]) > 50:
                        self.execution_stats["stop_loss_response_times"] = self.execution_stats["stop_loss_response_times"][-50:]
                except Exception as _e:
                    logger.debug(f"operation failed: {_e}")
        else:
            # 降级: RuntimePersistence不可用时仍记录基本timeline
            scanner = self._scanner
            sell_profit_pct = sell_info["sell_profit_pct"]
            scanner._timeline.append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "action": "sell", "ts_code": pos.ts_code,
                "stock_name": pos.stock_name, "strategy": pos.strategy,
                "shares": sell_info["sell_qty"], "price": order.filled_price,
                "reason": reason,
                "profit_pct": round(sell_profit_pct, 2),
                "profit_amount": round(sell_info["sell_profit_amount"], 2),
            })
            if "止损" in reason:
                scanner._stats["stop_losses"] += 1
            else:
                scanner._stats["take_profits"] += 1
            scanner._record_trade_result(sell_profit_pct / 100.0)
    
    # ==================== 追踪止损 ====================
    
    def update_trailing_stops(self, positions, realtime_data: Dict[str, Dict]) -> None:
        """更新追踪止损(盈利保护)

        【v2.9.83:弃用】DELEGATE_MAP路由到position_manager.update_trailing_stops。
        内部逻辑已与position_manager对齐(字段格式: high_price/trailing_stop_pct/activated/stop_price)。
        """
        scanner = self._scanner
        for pos in positions:
            if pos.available_qty <= 0:
                continue
            risk = scanner._get_strategy_risk(pos.strategy)
            trailing_pct = risk.get("trailing_stop_pct", 0)
            if trailing_pct <= 0:
                continue
            rt = realtime_data.get(pos.ts_code, {})
            price = rt.get("price", 0) or pos.current_price
            if price <= 0 or pos.avg_cost <= 0:
                continue
            profit_pct = (price - pos.avg_cost) / pos.avg_cost * 100
            with self.state_lock:
                state = dict(self.trailing_stops.get(pos.ts_code, {
                    "high_price": pos.avg_cost, "trailing_stop_pct": trailing_pct,
                    "activated": False, "activated_at": None, "stop_price": 0.0,
                }))
                if price > state.get("high_price", pos.avg_cost):
                    state["high_price"] = price
                if not state.get("activated") and profit_pct >= 2.0:
                    state["activated"] = True
                    state["activated_at"] = datetime.now().strftime("%H:%M:%S")
                    logger.info(f"[TRAILING] {pos.ts_code} 追踪止损激活: 盈利{profit_pct:.1f}%")
                if state.get("activated"):
                    new_stop = price * (1 - trailing_pct)
                    if new_stop > state.get("stop_price", 0):
                        state["stop_price"] = round(new_stop, 2)
                        logger.debug(f"[TRAILING] {pos.ts_code} 止损线上移至{new_stop:.2f}")
                self.trailing_stops[pos.ts_code] = state
    
    def get_effective_stop_price(self, pos, risk: Dict) -> float:
        """获取有效止损价(追踪止损 > 固定止损)"""
        scanner = self._scanner
        with self.state_lock:
            trailing = dict(self.trailing_stops[pos.ts_code]) if pos.ts_code in self.trailing_stops else None
        if trailing and trailing.get("stop_price", 0) > 0:
            return trailing["stop_price"]
        return scanner._calc_stop_loss_price(pos, risk)
    
    # ==================== 智能检查频率 ====================
    
    def get_smart_check_interval(self, positions) -> float:
        """根据持仓状态动态调整检查间隔(秒)"""
        if not positions:
            return 60.0
        
        # 有持仓且接近止损→1秒
        # 有持仓且盈利→5秒
        # 有持仓且涨停→10秒
        # 空仓→30秒
        scanner = self._scanner
        min_interval = 60.0
        
        for pos in positions:
            if pos.available_qty <= 0:
                continue
            risk = scanner._get_strategy_risk(pos.strategy)
            sl_pct = risk.get("stop_loss_pct", 0.03)
            profit_pct = pos.profit_pct / 100 if pos.profit_pct else 0
            
            # 接近止损→1秒
            if profit_pct < -sl_pct * 0.5:
                min_interval = min(min_interval, 1.0)
            # 盈利中→5秒
            elif profit_pct > 0:
                min_interval = min(min_interval, 5.0)
            # 亏损但未接近止损→3秒
            else:
                min_interval = min(min_interval, 3.0)
        
        return min_interval
    
    # ==================== 辅助方法 ====================
    
    def _is_limit_down(self, ts_code: str) -> bool:
        """判断是否跌停(不可卖)【v2.9.83:新增ST股±5%跌停阈值】"""
        rt = self.realtime_cache.get(ts_code, {})
        pct = rt.get("pct_chg", 0)

        # 【v2.9.83修复】ST股跌停阈值±5%, 需从stock_name判断
        # 与broker._calc_limit_prices对齐(broker已处理ST)
        stock_name = rt.get("name", "") or ""
        # 备用: 从scanner的_stock_name_map获取
        if not stock_name:
            try:
                stock_name = self._scanner._stock_name_map.get(ts_code, "") if self._scanner else ""
            except AttributeError:
                stock_name = ""
        # 备用: 从broker持仓获取
        try:
            br = self.broker  # 可能因_scanner=None而AttributeError
            if br and not stock_name:
                for p in br.get_positions():
                    if p.ts_code == ts_code:
                        stock_name = p.stock_name
                        break
        except (AttributeError, TypeError):
            pass
        is_st = "ST" in stock_name or "*ST" in stock_name

        if is_st:
            return pct <= -4.5  # ST股±5%, 用-4.5%容差
        elif ts_code.startswith('688'):
            return pct <= -19.5
        elif ts_code.startswith(('4', '8')):
            return pct <= -29.5
        else:
            return pct <= -9.5

    def is_limit_down(self, ts_code: str) -> bool:
        """判断是否跌停(公开接口,替代_is_limit_down)【v2.9.18】"""
        return self._is_limit_down(ts_code)

    async def execute_sell_list(self, to_sell: List[Tuple], trade_date: str, source: str = "legacy") -> List[Tuple]:
        """执行卖出列表(公开接口,替代_execute_sell_list)【v2.9.18】"""
        return await self._execute_sell_list(to_sell, trade_date, source=source)

    def _get_open_price(self, ts_code: str) -> float:
        """获取当日开盘价(用于跳空止损)"""
        rt = self.realtime_cache.get(ts_code, {})
        return rt.get("open", 0) or rt.get("pre_close", 0)
