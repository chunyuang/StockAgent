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
"""

import logging
import os
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
        return self._scanner._realtime_cache or {}
    
    @property
    def trailing_stops(self) -> Dict:
        return self._scanner._trailing_stops
    
    @property
    def position_risk_levels(self) -> Dict:
        return getattr(self._scanner, '_position_risk_levels', {})
    
    @property
    def data_router(self):
        return getattr(self._scanner, '_data_router', None)
    
    @property
    def execution_stats(self) -> Dict:
        return getattr(self._scanner, '_execution_stats', {})
    
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
                buy_dt = int(pos.buy_date)
                cur_dt = int(trade_date)
                from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
                bt = PortfolioBacktester()
                days_held = bt._calc_trade_days_held(buy_dt, cur_dt)
                if days_held >= max_hold:
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
        
        # 卖出后清理
        for pos, reason, _, _ in to_sell:
            self.trailing_stops.pop(pos.ts_code, None)
            self.position_risk_levels.pop(pos.ts_code, None)
        
        # 强制持久化
        if to_sell and self.broker:
            try:
                await self.broker.save_state(force=True)
            except Exception:
                pass
            await scanner._save_runtime_snapshot(force=True)
    
    # ==================== Checker模式 ====================
    
    async def _check_positions_checker(self, realtime_data: Dict[str, Dict], trade_date: str):
        """checker卖出逻辑(复用回测SellSignalChecker)"""
        scanner = self._scanner
        
        try:
            from nodes.backtest_engine.factor_selection.sell_signal_checker import SellSignalChecker
        except ImportError:
            logger.warning("[CHECKER] SellSignalChecker不可用, 回退legacy")
            return await self._check_positions_legacy(realtime_data, trade_date)

        positions = self.broker.get_positions()
        if not positions:
            return

        to_sell = []
        checker = SellSignalChecker()

        for pos in positions:
            if pos.available_qty <= 0:
                continue
            rt = realtime_data.get(pos.ts_code, {})
            if not rt or rt.get("price", 0) <= 0:
                continue

            risk = scanner._get_strategy_risk(pos.strategy)
            result = checker.check_realtime_sell(
                ts_code=pos.ts_code,
                buy_price=pos.avg_cost,
                current_price=rt.get("price", 0),
                buy_date=pos.buy_date,
                trade_date=trade_date,
                strategy=pos.strategy,
                risk_params=risk,
                high_today=rt.get("high", 0),
                low_today=rt.get("low", 0),
                open_today=rt.get("open", 0),
                pre_close=rt.get("pre_close", 0),
            )

            if result.should_sell:
                to_sell.append((pos, result.reason, rt.get("price", 0), risk))

        await self._execute_sell_list(to_sell, trade_date, source="checker")
        
        for pos, reason, _, _ in to_sell:
            self.trailing_stops.pop(pos.ts_code, None)
            self.position_risk_levels.pop(pos.ts_code, None)
        
        if to_sell and self.broker:
            try:
                await self.broker.save_state(force=True)
            except Exception:
                pass
    
    # ==================== Compare模式 ====================
    
    async def _check_positions_compare(self, realtime_data: Dict[str, Dict], trade_date: str):
        """compare模式: 两种逻辑都跑, 只执行旧逻辑, 记录差异"""
        scanner = self._scanner
        
        # Legacy
        legacy_sell = scanner._check_stop_loss_take_profit(
            self.broker.get_positions(), realtime_data
        )
        legacy_codes = {p.ts_code for p, _, _, _ in legacy_sell}

        # Checker
        try:
            from nodes.backtest_engine.factor_selection.sell_signal_checker import SellSignalChecker
            checker = SellSignalChecker()
            checker_codes = set()
            for pos in self.broker.get_positions():
                if pos.available_qty <= 0:
                    continue
                rt = realtime_data.get(pos.ts_code, {})
                if not rt or rt.get("price", 0) <= 0:
                    continue
                risk = scanner._get_strategy_risk(pos.strategy)
                result = checker.check_realtime_sell(
                    ts_code=pos.ts_code, buy_price=pos.avg_cost,
                    current_price=rt.get("price", 0), buy_date=pos.buy_date,
                    trade_date=trade_date, strategy=pos.strategy,
                    risk_params=risk, high_today=rt.get("high", 0),
                    low_today=rt.get("low", 0), open_today=rt.get("open", 0),
                    pre_close=rt.get("pre_close", 0),
                )
                if result.should_sell:
                    checker_codes.add(pos.ts_code)
        except ImportError:
            checker_codes = set()

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
            except Exception:
                pass

        # 只执行legacy逻辑
        await self._check_positions_legacy(realtime_data, trade_date)
    
    # ==================== 卖出执行 ====================
    
    async def _execute_sell_list(self, to_sell: List[Tuple], trade_date: str, source: str = "legacy"):
        """执行卖出列表(含跌停挂起、dry_run、P1-7修复)"""
        scanner = self._scanner
        
        for pos, reason, force_price, risk in to_sell:
            if pos.available_qty <= 0:
                continue
            
            # 跌停不可卖
            if self._is_limit_down(pos.ts_code):
                scanner._add_timeline_log("blocked", pos.ts_code, pos.stock_name,
                    pos.strategy, f"跌停不可卖(触发{reason}但跌停挂单无法成交)", None)
                # 加入pending_sells(等跌停打开后执行)
                if not hasattr(scanner, '_pending_sells'):
                    scanner._pending_sells = {}
                scanner._pending_sells[pos.ts_code] = {
                    "reason": reason, "risk": risk,
                    "added_at": time.time(), "source": source,
                }
                logger.warning(f"[{source.upper()}] 跌停不可卖: {pos.ts_code} {pos.stock_name}")
                continue
            
            # dry_run模式
            if self.dry_run:
                scanner._add_timeline_log("blocked", pos.ts_code, pos.stock_name,
                    pos.strategy, f"调试模式跳过卖出({reason})", None)
                logger.info(f"[DRY-RUN] 跳过卖出 {pos.ts_code} {reason}")
                continue
            
            # P1-7修复: 卖出前保存关键值
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
            
            if ok:
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
                    try:
                        self.execution_stats.setdefault("stop_loss_response_times", []).append(time.time())
                        if len(self.execution_stats["stop_loss_response_times"]) > 50:
                            self.execution_stats["stop_loss_response_times"] = self.execution_stats["stop_loss_response_times"][-50:]
                    except Exception:
                        pass
                else:
                    scanner._stats["take_profits"] += 1
                await scanner._publish_scanner_event("timeline", {"item": scanner._timeline[-1]})
                logger.info(f"[{source.upper()}] {reason}: {pos.ts_code} {sell_qty}股@{order.filled_price:.2f}")
            else:
                scanner._add_timeline_log("blocked", pos.ts_code, pos.stock_name,
                    pos.strategy, f"卖出失败: {msg}", None)
                logger.warning(f"[{source.upper()}] 卖出被拒 {pos.ts_code}: {msg}")
    
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
        trailing = self.trailing_stops.get(pos.ts_code)
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
    
    def _get_open_price(self, ts_code: str) -> float:
        """获取当日开盘价(用于跳空止损)"""
        rt = self.realtime_cache.get(ts_code, {})
        return rt.get("open", 0) or rt.get("pre_close", 0)
