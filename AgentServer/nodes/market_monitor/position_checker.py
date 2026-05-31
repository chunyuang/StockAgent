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

logger = logging.getLogger("position_checker")


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
    
    # ==================== 属性代理 ====================
    
    @property
    def broker(self):
        return self._scanner._broker
    
    @property
    def config(self) -> Dict:
        return self._scanner.config
    
    @property
    def sell_logic_mode(self) -> str:
        return getattr(self._scanner, 'SELL_LOGIC_MODE', 'legacy')
    
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
        return getattr(self._scanner, '_position_risk_levels', {})
    
    @property
    def state_lock(self) -> threading.Lock:
        """共享状态锁(保护trailing_stops/pending_sells/position_risk_levels)"""
        return self._scanner._state_lock
    
    @property
    def data_router(self):
        return getattr(self._scanner, '_data_router', None)
    
    @property
    def execution_stats(self) -> Dict:
        return getattr(self._scanner, '_execution_stats', {})
    
    def _get_sell_checker(self):
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
    
    def _get_backtester(self):
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
    
    async def check_positions(self, realtime_data: Dict[str, Dict], trade_date: str):
        """止损止盈+超时强卖检查(灰度开关路由)"""
        mode = self.sell_logic_mode
        if mode == "checker":
            return await self._check_positions_checker(realtime_data, trade_date)
        elif mode == "compare":
            return await self._check_positions_compare(realtime_data, trade_date)
        else:
            return await self._check_positions_legacy(realtime_data, trade_date)
    
    async def check_positions_quick(self, trade_date: str):
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
    
    async def _check_positions_legacy(self, realtime_data: Dict[str, Dict], trade_date: str):
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
        for pos in self.broker.get_positions():
            if pos.available_qty <= 0:
                continue
            risk = scanner._get_strategy_risk(pos.strategy)
            pos_overrides = getattr(scanner, '_position_risk_overrides', {}).get(pos.ts_code, {})
            sl_pct = pos_overrides.get('stop_loss_pct', risk.get('stop_loss_pct', 0.03))
            if pos.profit_pct / 100 > sl_pct * 2:
                already = any(p.ts_code == pos.ts_code for p, _, _, _ in to_sell)
                if not already and pos.profit_pct <= 0:
                    to_sell.append((pos, f"移动止损(盈利回撤至{pos.profit_pct:.1f}%)", pos.current_price, risk))
                    logger.info(f"[TRAILING] {pos.ts_code} 盈利回撤至{pos.profit_pct:.1f}%, 移动止损触发")

        # 执行卖出
        await self._execute_sell_list(to_sell, trade_date, source="legacy")
        await self._post_sell_state_cleanup(to_sell)
    
    # ==================== Checker模式 ====================
    
    async def _check_positions_checker(self, realtime_data: Dict[str, Dict], trade_date: str):
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
    
    async def _check_positions_compare(self, realtime_data: Dict[str, Dict], trade_date: str):
        """compare模式: 两种逻辑都跑, 只执行旧逻辑, 记录差异【v2.9.38:用_run_checker_on_positions+差异持久化】"""
        scanner = self._scanner
        
        # Legacy
        legacy_sell = scanner._check_stop_loss_take_profit(
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

        # 记录差异
        only_legacy = legacy_codes - checker_codes
        only_checker = checker_codes - legacy_codes
        both = legacy_codes & checker_codes

        if only_legacy or only_checker:
            logger.info(f"[COMPARE] 卖出差异: "
                         f"仅legacy={only_legacy or '{}'} "
                         f"仅checker={only_checker or '{}'} "
                         f"一致={both or '{}'}")
            try:
                await scanner._publish_scanner_event("sell_compare", {
                    "only_legacy": list(only_legacy),
                    "only_checker": list(only_checker),
                    "both": list(both),
                    "time": datetime.now().strftime("%H:%M:%S"),
                })
            except Exception as _e:
                pass

            # 【v2.9.38】差异持久化到MongoDB(审计用)
            await self._persist_compare_diff(
                trade_date, only_legacy, only_checker, both,
                legacy_sell, checker_results, realtime_data,
            )

        # 只执行legacy逻辑
        await self._check_positions_legacy(realtime_data, trade_date)
    
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
    
    async def _post_sell_state_cleanup(self, to_sell: List[Tuple]):
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
        if self.broker:
            try:
                await self.broker.save_state(force=True)
            except Exception as _e:
                logger.debug(f"[CLEANUP] broker保存失败: {_e}")
            try:
                await scanner._save_runtime_snapshot(force=True)
            except Exception as _e:
                logger.debug(f"[CLEANUP] 运行时快照保存失败: {_e}")
    
    async def _persist_compare_diff(self, trade_date: str, only_legacy: set, only_checker: set,
                                     both: set, legacy_sell: list, checker_results: list,
                                     realtime_data: Dict[str, Dict]):
        """compare差异持久化到MongoDB【v2.9.38新增】
        
        将legacy/checker卖出差异记录到sell_compare_diff集合,
        用于事后审计和分析, 评估checker模式何时可以替代legacy。
        
        TTL: 30天自动过期
        """
        scanner = self._scanner
        try:
            from core.managers import mongo_manager
            if not mongo_manager or not mongo_manager._client:
                return
            
            db = mongo_manager.db
            
            # 构建差异详情
            diff_details = {}
            for code in only_legacy | only_checker:
                detail = {"code": code}
                # legacy侧卖出原因
                for pos, reason, _, _ in legacy_sell:
                    if pos.ts_code == code:
                        detail["legacy_reason"] = reason
                        detail["legacy_profit_pct"] = round(pos.profit_pct, 2)
                        detail["strategy"] = pos.strategy
                        break
                # checker侧卖出原因
                for pos, reason, _, _, _ in checker_results:
                    if pos.ts_code == code:
                        detail["checker_reason"] = reason
                        detail["checker_profit_pct"] = round(pos.profit_pct, 2)
                        break
                # 行情上下文
                rt = realtime_data.get(code, {})
                detail["price"] = rt.get("price", 0)
                detail["pct_chg"] = rt.get("pct_chg", 0)
                diff_details[code] = detail
            
            doc = {
                "trade_date": trade_date,
                "time": datetime.now().strftime("%H:%M:%S"),
                "only_legacy": list(only_legacy),
                "only_checker": list(only_checker),
                "both": list(both),
                "diff_details": diff_details,
                "summary": {
                    "total_legacy": len(only_legacy) + len(both),
                    "total_checker": len(only_checker) + len(both),
                    "agreement_rate": round(len(both) / max(len(only_legacy | only_checker | both), 1) * 100, 1),
                },
            }
            
            await db["sell_compare_diff"].insert_one(doc)
            
            # 创建TTL索引(30天, 幂等)
            try:
                await db["sell_compare_diff"].create_index(
                    "time", name="ttl_30d_compare", expireAfterSeconds=30 * 86400
                )
            except Exception:
                pass  # 索引已存在
            
            logger.info(f"[COMPARE] 差异已持久化: "
                        f"一致率={doc['summary']['agreement_rate']}% "
                        f"仅legacy={len(only_legacy)} 仅checker={len(only_checker)}")
            
        except Exception as e:
            logger.debug(f"[COMPARE] 差异持久化失败: {e}")
    
    # ==================== 卖出执行 ====================
    
    async def _execute_sell_list(self, to_sell: List[Tuple], trade_date: str, source: str = "legacy"):
        """执行卖出列表(含跌停挂起、dry_run、P1-7修复)【v2.9.26:提取子方法】"""
        for pos, reason, force_price, risk in to_sell:
            if pos.available_qty <= 0:
                continue
            # 跌停不可卖 → 挂起pending_sells
            if self._is_limit_down(pos.ts_code):
                self._handle_limit_down_pending(pos, reason, risk, source)
                continue
            # dry_run模式
            if self.dry_run:
                self._scanner._add_timeline_log("blocked", pos.ts_code, pos.stock_name,
                    pos.strategy, f"调试模式跳过卖出({reason})", None)
                logger.info(f"[DRY-RUN] 跳过卖出 {pos.ts_code} {reason}")
                continue
            # 执行卖出
            ok, msg, order, sell_info = self._place_sell_order(pos, reason, force_price, risk)
            if ok:
                await self._post_sell_processing(pos, order, sell_info, reason, risk, source)
            else:
                self._scanner._add_timeline_log("blocked", pos.ts_code, pos.stock_name,
                    pos.strategy, f"卖出失败: {msg}", None)
                logger.warning(f"[{source.upper()}] 卖出被拒 {pos.ts_code}: {msg}")

    def _handle_limit_down_pending(self, pos, reason: str, risk: Dict, source: str):
        """跌停不可卖时挂起pending_sells【v2.9.26提取】"""
        scanner = self._scanner
        scanner._add_timeline_log("blocked", pos.ts_code, pos.stock_name,
            pos.strategy, f"跌停不可卖(触发{reason}但跌停挂单无法成交)", None)
        with self.state_lock:
            if not hasattr(scanner, '_pending_sells'):
                scanner._pending_sells = {}
            scanner._pending_sells[pos.ts_code] = {
                "reason": reason, "risk": risk,
                "added_at": time.time(), "source": source,
            }
        logger.warning(f"[{source.upper()}] 跌停不可卖: {pos.ts_code} {pos.stock_name}")

    def _place_sell_order(self, pos, reason: str, force_price, risk: Dict):
        """下单卖出并返回(ok, msg, order, sell_info)【v2.9.26提取】"""
        sell_qty = pos.available_qty
        sell_profit_pct = pos.profit_pct
        sell_profit_amount = (pos.current_price - pos.avg_cost) * sell_qty
        sell_avg_cost = pos.avg_cost
        sell_current_price = pos.current_price
        sell_price = force_price if force_price else sell_current_price
        self.broker.update_realtime(pos.ts_code, sell_price)
        ok, msg, order = self.broker.place_order(
            ts_code=pos.ts_code, stock_name=pos.stock_name,
            side="sell", quantity=sell_qty, price=sell_price,
            order_type="market", strategy=pos.strategy, reason=reason,
        )
        sell_info = {
            "sell_qty": sell_qty, "sell_profit_pct": sell_profit_pct,
            "sell_profit_amount": sell_profit_amount, "sell_avg_cost": sell_avg_cost,
            "sell_current_price": sell_current_price, "risk": risk,
        }
        return ok, msg, order, sell_info

    async def _post_sell_processing(self, pos, order, sell_info: Dict, reason: str, risk: Dict, source: str):
        """卖出后处理: timeline+统计+EventBus【v2.9.26提取】"""
        scanner = self._scanner
        sell_qty = sell_info["sell_qty"]
        sell_profit_pct = sell_info["sell_profit_pct"]
        sell_profit_amount = sell_info["sell_profit_amount"]
        sell_avg_cost = sell_info["sell_avg_cost"]
        sell_current_price = sell_info["sell_current_price"]

        scanner._timeline.append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "action": "sell",
            "ts_code": pos.ts_code,
            "stock_name": pos.stock_name,
            "strategy": pos.strategy,
            "shares": sell_qty,
            "price": order.filled_price,
            "reason": reason,
            "profit_pct": round(sell_profit_pct, 2),
            "profit_amount": round(sell_profit_amount, 2),
            "decision_detail": {
                "sell_reason": reason,
                "profit_pct": round(sell_profit_pct, 2),
                "profit_amount": round(sell_profit_amount, 2),
                "cost_price": sell_avg_cost,
                "sell_price": order.filled_price,
                "current_price": sell_current_price,
                "stop_loss_pct": round(-risk.get("stop_loss_pct", 0.03) * 100, 1),
                "take_profit_pct": round(risk.get("take_profit_pct", 0.07) * 100, 1),
                "stop_loss_price": scanner._calc_stop_loss_price(pos, risk),
                "take_profit_price": scanner._calc_take_profit_price(pos, risk),
                "hold_minutes": 0,
            },
        })
        if "止损" in reason:
            scanner._stats["stop_losses"] += 1
            scanner._record_trade_result(sell_profit_pct / 100.0)
            try:
                self.execution_stats.setdefault("stop_loss_response_times", []).append(time.time())
                if len(self.execution_stats["stop_loss_response_times"]) > 50:
                    self.execution_stats["stop_loss_response_times"] = self.execution_stats["stop_loss_response_times"][-50:]
            except Exception as _e:
                pass
        else:
            scanner._stats["take_profits"] += 1
            scanner._record_trade_result(sell_profit_pct / 100.0)
        await scanner._publish_scanner_event("timeline", {"item": scanner._timeline[-1]})
        # EventBus事件(与_execute_risk_sell对齐)
        try:
            from nodes.market_monitor.scanner_event_bus import ScannerEvents
            if hasattr(scanner, '_event_bus') and scanner._event_bus:
                await scanner._event_bus.emit(ScannerEvents.RISK_SELL_EXECUTED, {
                    "ts_code": pos.ts_code, "reason": reason,
                    "price": order.filled_price, "profit_pct": sell_profit_pct,
                    "source": "position_checker",
                })
                await scanner._event_bus.emit(ScannerEvents.POSITION_CHANGED, {
                    "ts_code": pos.ts_code, "action": "sell",
                    "reason": reason, "source": "position_checker",
                })
        except Exception as _e:
            pass
        logger.info(f"[{source.upper()}] {reason}: {pos.ts_code} {sell_qty}股@{order.filled_price:.2f}")
    
    # ==================== 追踪止损 ====================
    
    def update_trailing_stops(self, positions, realtime_data: Dict[str, Dict]):
        """更新追踪止损(盈利保护)"""
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
            if price <= 0:
                continue
            
            profit_pct = (price - pos.avg_cost) / pos.avg_cost
            if profit_pct > trailing_pct * 2:
                with self.state_lock:
                    current_stop = self.trailing_stops.get(pos.ts_code, {}).get("stop_price", 0)
                    new_stop = price * (1 - trailing_pct)
                    if new_stop > current_stop:
                        self.trailing_stops[pos.ts_code] = {
                            "stop_price": round(new_stop, 2),
                            "activated_at": datetime.now().isoformat(),
                            "high_water_mark": price,
                        }
                        logger.debug(f"[TRAILING] {pos.ts_code} 止损线上移至{new_stop:.2f}(HWM={price:.2f})")
    
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
        """判断是否跌停(不可卖)"""
        rt = self.realtime_cache.get(ts_code, {})
        pct = rt.get("pct_chg", 0)
        if ts_code.startswith('688'):
            return pct <= -19.5
        elif ts_code.startswith(('4', '8')):
            return pct <= -29.5
        else:
            return pct <= -9.5

    def is_limit_down(self, ts_code: str) -> bool:
        """判断是否跌停(公开接口,替代_is_limit_down)【v2.9.18】"""
        return self._is_limit_down(ts_code)

    async def execute_sell_list(self, to_sell: List[Tuple], trade_date: str, source: str = "legacy"):
        """执行卖出列表(公开接口,替代_execute_sell_list)【v2.9.18】"""
        return await self._execute_sell_list(to_sell, trade_date, source=source)

    def _get_open_price(self, ts_code: str) -> float:
        """获取当日开盘价(用于跳空止损)"""
        rt = self.realtime_cache.get(ts_code, {})
        return rt.get("open", 0) or rt.get("pre_close", 0)
