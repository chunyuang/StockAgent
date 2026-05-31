"""
PositionManager — 持仓风控管理器

从MarketScanner God Class拆分出来(Phase3.1)。
负责所有持仓卖出决策和执行:
- 止损止盈检查(固定/跳空/追踪/移动)
- 超时强卖
- 跌停不可卖挂起
- 灰度模式(legacy/checker/compare)
- 卖出执行与状态清理

设计原则:
1. 卖出决策与执行分离: check方法返回to_sell列表, execute方法执行
2. 状态由Scanner持有: trailing_stops/pending_sells等状态留在Scanner
3. Broker为唯一持仓权威: PositionManager不存持仓,只读Broker
"""

import logging
import threading
import time
from datetime import datetime
from typing import Dict, List, Tuple, Any, Optional

logger = logging.getLogger("position_manager")


class PositionManager:
    """
    持仓风控管理器
    
    用法:
        pm = PositionManager(scanner)  # scanner引用(读取状态)
        to_sell = pm.check_stop_loss_take_profit(positions, realtime_data)
        await pm.execute_sell_list(to_sell, trade_date)
    """
    
    def __init__(self, scanner):
        """
        Args:
            scanner: MarketScanner实例(读取状态,不修改)
        """
        self._scanner = scanner
        self._backtester = None  # 缓存PortfolioBacktester实例
    
    # ==================== 属性代理(从scanner读取,线程安全) ====================
    
    @property
    def broker(self):
        return self._scanner._broker
    
    @property
    def trailing_stops(self) -> Dict:
        """读取追踪止损状态(直接引用,调用方需自行加锁或仅在单线程读)"""
        return self._scanner._trailing_stops
    
    @property
    def pending_sells(self) -> Dict:
        return self._scanner._pending_sells
    
    @property
    def position_risk_levels(self) -> Dict:
        return getattr(self._scanner, '_position_risk_levels', {})
    
    @property
    def position_risk_overrides(self) -> Dict:
        return getattr(self._scanner, '_position_risk_overrides', {})
    
    @property
    def sell_logic_mode(self) -> str:
        return self._scanner.SELL_LOGIC_MODE
    
    @property
    def state_lock(self) -> threading.Lock:
        """共享状态锁(保护trailing_stops/pending_sells/position_risk_levels)"""
        return self._scanner._state_lock
    
    def _get_trailing_stop_safe(self, ts_code: str) -> Optional[Dict]:
        """线程安全读取追踪止损状态(深拷贝后释放锁)"""
        with self.state_lock:
            if ts_code in self.trailing_stops:
                return dict(self.trailing_stops[ts_code])
        return None

    def _get_backtester(self):
        """获取缓存的PortfolioBacktester实例(懒初始化)"""
        if self._backtester is not None:
            return self._backtester
        try:
            from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
            self._backtester = PortfolioBacktester()
            return self._backtester
        except ImportError:
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

    # ==================== 止损止盈计算 ====================
    
    def calc_stop_loss_price(self, pos_or_cost, risk: Dict) -> float:
        """统一止损价计算"""
        cost = pos_or_cost.avg_cost if hasattr(pos_or_cost, 'avg_cost') else pos_or_cost
        sl_pct = risk.get("stop_loss_pct", 0.03)
        return round(cost * (1 - sl_pct), 2)
    
    def calc_take_profit_price(self, pos_or_cost, risk: Dict) -> float:
        """统一止盈价计算"""
        cost = pos_or_cost.avg_cost if hasattr(pos_or_cost, 'avg_cost') else pos_or_cost
        tp_pct = risk.get("take_profit_pct", 0.07)
        return round(cost * (1 + tp_pct), 2)
    
    def get_effective_stop_price(self, pos, risk: Dict) -> Optional[float]:
        """获取实际止损价(考虑追踪止损/移动止损)
        
        【v2.9.13:线程安全修复】trailing_stops通过state_lock深拷贝读取，
        避免风控线程并发写入导致读取半更新状态。
        """
        # 追踪止损(线程安全读取)
        trailing = self._get_trailing_stop_safe(pos.ts_code)
        if trailing and trailing.get("activated") and trailing.get("stop_price", 0) > 0:
            return trailing["stop_price"]
        
        # 移动止损(盈利>2倍止损→保本价)
        sl_pct = risk.get("stop_loss_pct", 0.03)
        if pos.profit_pct / 100 > sl_pct * 2:
            return pos.avg_cost  # 保本出局
        
        # 固定止损
        return self.calc_stop_loss_price(pos, risk)
    
    # ==================== 卖出检查 ====================
    
    def check_stop_loss_take_profit(self, positions, realtime_data: Dict) -> List[Tuple]:
        """
        止损止盈检查(Scanner内嵌逻辑)
        
        Returns: [(pos, reason, price, risk), ...]
        """
        to_sell = []
        
        for pos in positions:
            if pos.available_qty <= 0:
                continue  # T+1: 今日买入不可卖

            # 获取策略级风控参数
            risk = self._scanner._get_strategy_risk(pos.strategy)
            # 单票风控覆盖(线程安全读取)
            with self.state_lock:
                pos_overrides = dict(self.position_risk_overrides.get(pos.ts_code, {}))
            if 'stop_loss_pct' in pos_overrides:
                risk['stop_loss_pct'] = pos_overrides['stop_loss_pct']
            if 'take_profit_pct' in pos_overrides:
                risk['take_profit_pct'] = pos_overrides['take_profit_pct']
            stop_loss_pct = -risk.get("stop_loss_pct", 0.03) * 100
            take_profit_pct = risk.get("take_profit_pct", 0.07) * 100

            stop_loss_price = self.calc_stop_loss_price(pos, risk)
            take_profit_price = self.calc_take_profit_price(pos, risk)

            sell_reason = None
            sell_price = pos.current_price

            # 追踪止损检查(线程安全: 深拷贝读取)
            trailing = self._get_trailing_stop_safe(pos.ts_code)
            trailing_triggered = False
            if trailing and trailing.get("activated") and trailing.get("stop_price", 0) > 0:
                trailing_stop_price = trailing["stop_price"]
                if pos.current_price <= trailing_stop_price:
                    high_price = trailing.get("high_price", pos.avg_cost)
                    trailing_pct = trailing.get("trailing_stop_pct", 0)
                    profit_at_high = (high_price / pos.avg_cost - 1) * 100 if pos.avg_cost > 0 else 0
                    sell_reason = f"追踪止损(最高{high_price:.2f}→{trailing_pct*100:.0f}%回撤, 曾盈{profit_at_high:.1f}%)"
                    sell_price = trailing_stop_price
                    trailing_triggered = True

            # 常规止损止盈(追踪止损未触发时)
            if not trailing_triggered:
                rt = realtime_data.get(pos.ts_code, {})
                today_open = rt.get("open", 0) if rt else self._get_open_price(pos.ts_code)

                if pos.profit_pct <= stop_loss_pct:
                    if today_open and today_open > 0 and today_open < stop_loss_price:
                        sell_reason = f"跳空止损(开{today_open:.2f}<止损{stop_loss_price:.2f})"
                        sell_price = today_open
                    else:
                        sell_reason = f"止损 {pos.profit_pct:.1f}%"
                elif pos.profit_pct >= take_profit_pct:
                    sell_reason = f"止盈 {pos.profit_pct:.1f}%"

                # 冲高回落/利润保护/高开即卖
                if not sell_reason and pos.avg_cost > 0:
                    open_rise = (today_open / pos.avg_cost - 1) if today_open > 0 else 0
                    close_rise = pos.profit_pct / 100
                    next_day_sell_pct = risk.get("next_day_open_sell_pct", 0.03)

                    if open_rise >= next_day_sell_pct and pos.current_price < today_open:
                        if open_rise >= 0.05:
                            sell_reason = f"冲高回落(开涨{open_rise*100:.1f}%)"
                            sell_price = today_open
                        elif (today_open - pos.current_price) / today_open >= 0.01:
                            sell_reason = f"冲高回落(开涨{open_rise*100:.1f}%回落)"
                            sell_price = today_open

                    if not sell_reason and open_rise >= 0.02 and close_rise >= 0.02 and pos.current_price < today_open:
                        sell_reason = f"利润保护(收涨{close_rise*100:.1f}%)"
                        sell_price = pos.current_price

                    if not sell_reason and open_rise >= next_day_sell_pct:
                        strategy_name = getattr(pos, 'strategy', '')
                        if strategy_name in ('first_limit_up', '首板打板'):
                            sell_reason = f"高开即卖(开涨{open_rise*100:.1f}%)"
                            sell_price = today_open

            if sell_reason:
                to_sell.append((pos, sell_reason, sell_price, risk))

        return to_sell
    
    def check_stop_loss_only(self, realtime_data: Dict) -> List[Tuple]:
        """
        1秒级止损检查(风控线程用,轻量)
        
        只检查固定止损+追踪止损,不检查止盈/超时
        跌停不可卖→挂起pending_sells
        
        线程安全: 通过state_lock保护trailing_stops/pending_sells读写
        
        Returns: [(pos, reason, price, risk), ...]
        """
        to_sell = []
        positions = list(self.broker.get_positions()) if self.broker else []
        
        for pos in positions:
            if pos.available_qty <= 0:
                continue
            
            ts_code = pos.ts_code
            rt = realtime_data.get(ts_code, {})
            current_price = rt.get("price", pos.current_price)
            
            if current_price <= 0:
                continue
            
            # 跌停不可卖
            if self._is_limit_down(ts_code):
                with self.state_lock:
                    if ts_code not in self.pending_sells:
                        risk = self._scanner._get_strategy_risk(pos.strategy)
                        reason = f"跌停挂起(当前{current_price:.2f})"
                        self.pending_sells[ts_code] = {"reason": reason, "price": current_price, "added_at": time.time(), "source": "position_manager"}
                        logger.warning(f"[RISK] {ts_code} {reason}")
                    else:
                        # 【v3.0:更新挂起价格(可能连续跌停,价格在变)】
                        info = self.pending_sells[ts_code]
                        if isinstance(info, dict):
                            info["price"] = current_price
                continue
            
            # 跌停恢复: 之前挂起,现在不跌停了
            with self.state_lock:
                if ts_code in self.pending_sells:
                    info = self.pending_sells.pop(ts_code)
                    reason = info.get("reason", "跌停恢复") if isinstance(info, dict) else info[0]
                    price = info.get("price", current_price) if isinstance(info, dict) else info[1]
                    logger.info(f"[RISK] {ts_code} 跌停恢复,执行挂起卖出: {reason}")
                    risk = self._scanner._get_strategy_risk(pos.strategy)
                    to_sell.append((pos, reason, price, risk))
                    continue
            
            risk = self._scanner._get_strategy_risk(pos.strategy)
            # 单票覆盖
            with self.state_lock:
                pos_overrides = self.position_risk_overrides.get(ts_code, {})
            if 'stop_loss_pct' in pos_overrides:
                risk['stop_loss_pct'] = pos_overrides['stop_loss_pct']
            
            sl_pct = -risk.get("stop_loss_pct", 0.03) * 100
            
            # 固定止损
            if pos.profit_pct <= sl_pct:
                stop_loss_price = self.calc_stop_loss_price(pos, risk)
                today_open = rt.get("open", 0)
                if today_open > 0 and today_open < stop_loss_price:
                    to_sell.append((pos, f"跳空止损(开{today_open:.2f}<止损{stop_loss_price:.2f})", today_open, risk))
                else:
                    to_sell.append((pos, f"止损 {pos.profit_pct:.1f}%", current_price, risk))
                continue
            
            # 追踪止损
            with self.state_lock:
                trailing = dict(self.trailing_stops.get(ts_code, {})) if ts_code in self.trailing_stops else None
            if trailing and trailing.get("activated") and trailing.get("stop_price", 0) > 0:
                if current_price <= trailing["stop_price"]:
                    to_sell.append((pos, f"追踪止损(回撤至{current_price:.2f})", trailing["stop_price"], risk))
        
        return to_sell
    
    def update_trailing_stops(self, positions, realtime_data: Dict):
        """更新追踪止损状态(每轮扫描后调用)
        
        规则(与真实超短量化对齐):
        1. 买入后, 初始止损=固定止损(如-3%)
        2. 当盈利>=2%时, 激活追踪止损, 止损线=最高价×(1-trailing_pct)
        3. 价格创新高时, 止损线上移
        4. 价格回落触发追踪止损时卖出, 锁住大部分利润
        
        线程安全: 通过state_lock保护trailing_stops读写
        """
        for pos in positions:
            ts_code = pos.ts_code
            current_price = pos.current_price
            
            if current_price <= 0 or pos.avg_cost <= 0:
                continue
            
            profit_pct = pos.profit_pct  # 如: 5.0 = +5%
            
            # 获取策略追踪止损比例
            risk = self._scanner._get_strategy_risk(pos.strategy)
            trailing_stop_pct = risk.get("trailing_stop_pct", 0.0)  # 0=不启用
            
            if trailing_stop_pct <= 0:
                continue
            
            with self.state_lock:
                state = dict(self.trailing_stops.get(ts_code, {
                    "high_price": pos.avg_cost,
                    "trailing_stop_pct": trailing_stop_pct,
                    "activated": False,
                    "activated_at": None,
                    "stop_price": 0.0,
                }))
                
                # 更新最高价
                if current_price > state["high_price"]:
                    state["high_price"] = current_price
                    logger.debug(f"[TRAILING] {ts_code} 新高: {current_price:.2f}")
                
                # 盈利>=2%时激活追踪止损
                if not state["activated"] and profit_pct >= 2.0:
                    state["activated"] = True
                    state["activated_at"] = datetime.now().strftime("%H:%M:%S")
                    logger.info(f"[TRAILING] {ts_code} 追踪止损激活: 盈利{profit_pct:.1f}%>=2%")
                
                # 计算追踪止损价
                if state["activated"]:
                    state["stop_price"] = state["high_price"] * (1 - trailing_stop_pct)
                
                self.trailing_stops[ts_code] = state
    
    # ==================== 超时强卖检查 ====================
    
    def check_timeout_sell(self, positions, trade_date: str) -> List[Tuple]:
        """超时强卖检查"""
        to_sell = []
        from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK
        
        for pos in positions:
            if pos.available_qty <= 0 or not pos.buy_date:
                continue
            risk = self._scanner._get_strategy_risk(pos.strategy)
            max_hold = risk.get("max_hold_days", GLOBAL_RISK.get("max_hold_days", 999))
            if max_hold >= 999:
                continue
            try:
                days_held = self._calc_trade_days_held(pos.buy_date, trade_date)
                if days_held is not None and days_held >= max_hold:
                    risk = self._scanner._get_strategy_risk(pos.strategy)
                    to_sell.append((pos, f"超时({days_held}日≥{max_hold}日)", pos.current_price, risk))
                    logger.info(f"[TIMEOUT] {pos.ts_code} 持仓{days_held}日≥{max_hold}日, 强制卖出")
            except (ValueError, TypeError):
                pass
        
        return to_sell
    
    def check_moving_stop(self, positions) -> List[Tuple]:
        """移动止损(保本)检查: 盈利>2倍止损→保本出局"""
        to_sell = []
        
        for pos in positions:
            if pos.available_qty <= 0:
                continue
            risk = self._scanner._get_strategy_risk(pos.strategy)
            # 线程安全读取覆盖参数
            with self.state_lock:
                pos_overrides = dict(self.position_risk_overrides.get(pos.ts_code, {}))
            sl_pct = pos_overrides.get('stop_loss_pct', risk.get('stop_loss_pct', 0.03))
            
            if pos.profit_pct / 100 > sl_pct * 2 and pos.profit_pct <= 0:
                to_sell.append((pos, f"移动止损(盈利回撤至{pos.profit_pct:.1f}%)", pos.current_price, risk))
                logger.info(f"[TRAILING] {pos.ts_code} 盈利回撤至{pos.profit_pct:.1f}%, 移动止损触发")
        
        return to_sell
    
    # ==================== 辅助方法 ====================
    
    def _get_open_price(self, ts_code: str) -> Optional[float]:
        """获取当日开盘价(委托给scanner)"""
        return self._scanner._get_open_price(ts_code)
    
    def _is_limit_down(self, ts_code: str) -> bool:
        """跌停判断(委托给scanner)"""
        return self._scanner._is_limit_down(ts_code)

    # ==================== 仓位计算 ====================

    def calc_position_ratio(self, signal) -> float:
        """根据信号特征计算仓位比例
        
        逻辑:
        - 涨停+连板≥2 → 重仓40% (确定性高)
        - 涨停+首板 → 中仓25% (有确定性)
        - 半路追涨 → 中仓25% (主力策略)
        - 跌停翘板 → 轻仓15% (高风险)
        - 龙头低吸 → 轻仓15% (高风险)
        
        总仓位限制: 单票≤总资产15%, 总仓位≤70%
        """
        strategy = signal.strategy or ""
        
        # 策略级仓位
        if "涨停" in strategy or "limit_up" in strategy:
            # 连板股重仓(limit_up_count字段, 兼容旧limit_times字段名)
            limit_count = getattr(signal, 'limit_up_count', None) or getattr(signal, 'limit_times', 0)
            if signal.is_limit_up and limit_count >= 2:
                ratio = 0.40
            else:
                ratio = 0.25
        elif "半路" in strategy or "mid_chase" in strategy:
            ratio = 0.25
        elif "跌停" in strategy or "limit_down" in strategy:
            ratio = 0.15
        elif "龙头" in strategy or "leader" in strategy:
            ratio = 0.15
        elif "anomaly" in strategy:
            ratio = 0.10
        else:
            ratio = 0.20
        
        # 动态调整: 持仓多时减仓
        if self.broker:
            acct = self.broker.get_account()
            if acct.total_assets > 0:
                current_ratio = acct.market_value / acct.total_assets
                if current_ratio > 0.5:
                    ratio *= 0.7
                if current_ratio > 0.65:
                    ratio *= 0.5
        
        # 情绪仓位系数
        pipeline_ratio = getattr(self._scanner, '_current_position_ratio', None)
        if pipeline_ratio is not None and pipeline_ratio < 1.0:
            ratio *= pipeline_ratio
        
        return ratio

    def calc_would_buy_shares(self, signal) -> int:
        """计算dry_run模式下会买入多少股(不实际下单)"""
        if not self.broker or signal.price <= 0:
            return 0
        acct = self.broker.get_account()
        position_ratio = self.calc_position_ratio(signal)
        max_amount = acct.available_cash * position_ratio
        lot = 200 if signal.ts_code.startswith('688') else 100
        shares = int(max_amount / signal.price / lot) * lot
        return shares

    # ==================== pending_sells超时检查 ====================

    def check_pending_sells_timeout(self, max_wait_seconds: int = 7200) -> List[Tuple]:
        """检查跌停挂起卖出是否超时(默认2小时)
        
        场景: 跌停后一直未恢复, 挂起的卖出永远无法执行。
        超时后取消挂起, 保留持仓(避免亏损扩大时不必要的急杀)。
        
        注意: 此方法在风控线程中调用, 需要线程安全
        
        Args:
            max_wait_seconds: 最大等待时间(默认7200秒=2小时, 即一个交易日的最长时间)
        Returns:
            超时清除的ts_code列表(不执行卖出, 仅清除挂起)
        """
        now = time.time()
        expired_codes = []
        
        with self.state_lock:
            to_remove = []
            for ts_code, info in list(self.pending_sells.items()):
                if not isinstance(info, dict):
                    # 旧格式兼容, 直接清除
                    to_remove.append(ts_code)
                    continue
                added_at = info.get("added_at", 0)
                if added_at > 0 and (now - added_at) > max_wait_seconds:
                    to_remove.append(ts_code)
                    expired_codes.append(ts_code)
                    logger.warning(
                        f"[PENDING_SELLS] {ts_code} 跌停挂起超时({(now-added_at)/60:.0f}分钟>"
                        f"{max_wait_seconds/60:.0f}分钟), 清除挂起: {info.get('reason', '')}"
                    )
            for code in to_remove:
                self.pending_sells.pop(code, None)
        
        # 【v2.9.17:超时清除也记录到timeline】
        for ts_code in expired_codes:
            try:
                self._scanner._add_timeline_log("blocked", ts_code, "",
                    "", f"跌停挂起超时清除(保留持仓)", None)
            except Exception as _e:
                logger.debug(f"operation failed: {_e}")
        
        return expired_codes

    def get_pending_sells_summary(self) -> List[Dict]:
        """获取跌停挂起卖出摘要(供API/前端使用)

        Returns:
            [{ts_code, reason, price, wait_seconds, source}, ...]
        """
        now = time.time()
        result = []
        with self.state_lock:
            for ts_code, info in dict(self.pending_sells).items():
                if isinstance(info, dict):
                    result.append({
                        "ts_code": ts_code,
                        "reason": info.get("reason", ""),
                        "price": info.get("price", 0),
                        "wait_seconds": round(now - info.get("added_at", now), 0),
                        "source": info.get("source", "unknown"),
                    })
        return result

    # ==================== v2.9.27: 风控卖出执行逻辑提取 ====================

    def retry_pending_sells(self, realtime_data: Dict):
        """跌停恢复后重试挂起的卖出指令【v2.9.22提取, v2.9.27:从scanner移入PositionManager】

        当股票从跌停恢复(非跌停状态)且有挂起的卖出指令时,
        重新尝试执行该卖出。避免跌停恢复后卖出指令被遗忘。
        """
        scanner = self._scanner
        with self.state_lock:
            pending = dict(self.pending_sells)
        if not pending:
            return

        retried = []
        for ts_code, info in pending.items():
            # 检查是否仍持有该票
            pos = None
            for p in scanner._broker.get_positions():
                if p.ts_code == ts_code and p.available_qty > 0:
                    pos = p
                    break
            if not pos:
                # 已无持仓或无可用数量, 清除挂起
                with self.state_lock:
                    self.pending_sells.pop(ts_code, None)
                continue

            # 检查是否不再跌停
            if self._is_limit_down(ts_code):
                continue  # 仍在跌停, 无法卖出

            # 跌停恢复! 尝试执行挂起的卖出
            reason = info.get("reason", "pending_retry")
            price = info.get("price", pos.current_price)
            logger.info(f"[RISK_THREAD] 跌停恢复重试: {ts_code} {reason}")

            if scanner._loop and not scanner._loop.is_closed():
                import asyncio
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        scanner._execute_risk_sell(pos, reason, price, pos.available_qty),
                        scanner._loop
                    )
                    future.result(timeout=5)
                    retried.append(ts_code)
                except Exception as e:
                    logger.debug(f"[RISK_THREAD] 跌停恢复重试失败: {ts_code} {e}")

        # 清除成功重试的条目
        if retried:
            with self.state_lock:
                for code in retried:
                    self.pending_sells.pop(code, None)

    def execute_sell_list_from_risk(self, to_sell: list):
        """风控线程执行卖出列表【v2.9.22提取, v2.9.27:从scanner移入PositionManager】

        逐个执行PositionManager返回的to_sell列表, 超时/失败时记录到pending_sells。
        """
        import asyncio
        scanner = self._scanner
        for pos, reason, price, risk in to_sell:
            if scanner._loop and not scanner._loop.is_closed():
                try:
                    sell_qty = pos.available_qty
                    future = asyncio.run_coroutine_threadsafe(
                        self.execute_risk_sell(pos, reason, price, sell_qty),
                        scanner._loop
                    )
                    future.result(timeout=5)
                except asyncio.TimeoutError:
                    # 超时不丢弃,记录到pending_sells待下次执行
                    logger.warning(
                        f"[RISK_THREAD] 卖出执行超时(5秒): {pos.ts_code} {reason}, "
                        f"加入pending_sells待下次执行"
                    )
                    with self.state_lock:
                        if pos.ts_code not in self.pending_sells:
                            self.pending_sells[pos.ts_code] = {
                                "reason": reason, "price": price,
                                "added_at": time.time(),
                                "source": "risk_thread_timeout",
                            }
                except Exception as e:
                    logger.error(f"[RISK_THREAD] 卖出执行失败: {pos.ts_code} {e}")

    # ==================== v2.9.35: 从scanner提取的卖出执行方法 ====================

    async def execute_risk_sell(self, pos, reason: str, price: float, quantity: int):
        """风控线程触发的卖出执行(在asyncio主循环中运行)

        【v2.9.35: 从scanner._execute_risk_sell提取】
        v2.9.12: try/except保护
        v2.9.19: 提取_post_sell_cleanup
        """
        scanner = self._scanner
        if pos.available_qty <= 0:
            return

        sell_profit_pct = pos.profit_pct
        sell_profit_amount = (pos.current_price - pos.avg_cost) * quantity

        try:
            scanner._broker.update_realtime(pos.ts_code, pos.current_price)
            ok, msg, order = scanner._broker.place_order(
                ts_code=pos.ts_code, stock_name=pos.stock_name,
                side="sell", quantity=quantity, price=price,
                order_type="market", strategy=pos.strategy, reason=reason,
            )
        except Exception as e:
            logger.error(f"[RISK_SELL] place_order异常 {pos.ts_code}: {e}")
            return

        if ok:
            await scanner._post_sell_cleanup(
                pos, reason, order, quantity,
                sell_profit_pct, sell_profit_amount, source="risk_sell",
            )
        else:
            logger.warning(f"[RISK_SELL] 卖出失败 {pos.ts_code}: {msg}")

    async def liquidate_positions(self, reason: str, source: str) -> Tuple[int, int]:
        """批量清仓: 卖出所有可用持仓

        【v2.9.35: 从scanner._liquidate_positions提取】
        _sell_all_positions(停止清仓)和_execute_force_empty(强制空仓)的公共实现。
        使用available_qty(T+1合规), 单票异常不中断。

        Returns:
            (sold, failed) 成功/失败数
        """
        scanner = self._scanner
        if not scanner._broker:
            return 0, 0
        positions = scanner._broker.get_positions()
        sold, failed = 0, 0
        for p in positions:
            if p.available_qty <= 0:
                continue  # T+1: 不可卖跳过
            try:
                scanner._broker.update_realtime(p.ts_code, p.current_price)
                profit_pct = p.profit_pct
                profit_amount = (p.current_price - p.avg_cost) * p.available_qty
                ok, msg, order = scanner._broker.place_order(
                    ts_code=p.ts_code,
                    stock_name=p.stock_name,
                    side="sell",
                    quantity=p.available_qty,
                    price=p.current_price,
                    order_type="market",
                    strategy=p.strategy,
                    reason=reason,
                )
                if ok:
                    sold += 1
                    await scanner._post_sell_cleanup(
                        p, reason, order, p.available_qty,
                        profit_pct, profit_amount, source=source,
                    )
                else:
                    failed += 1
                    logger.warning(f"[{source.upper()}] {p.ts_code} 卖出失败: {msg}")
            except Exception as e:
                failed += 1
                logger.error(f"[{source.upper()}] {p.ts_code} 异常: {e}")
        logger.info(f"[{source.upper()}] 完成: 卖出{sold}只, 失败{failed}只")
        return sold, failed
