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
    def broker(self) -> Any:
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
        return self._scanner._position_risk_levels
    
    @property
    def position_risk_overrides(self) -> Dict:
        return self._scanner._position_risk_overrides
    
    @property
    def sell_logic_mode(self) -> str:
        return self._scanner.SELL_LOGIC_MODE
    
    @property
    def state_lock(self) -> threading.Lock:
        """共享状态锁(保护trailing_stops/pending_sells/position_risk_levels)"""
        lock = self._scanner._state_lock
        # 【v2.9.79:defensive】未start时state_lock可能为None, 返回dummy锁避免崩溃
        if lock is None:
            lock = threading.Lock()
            self._scanner._state_lock = lock
        return lock
    
    def _get_trailing_stop_safe(self, ts_code: str) -> Optional[Dict]:
        """线程安全读取追踪止损状态(深拷贝后释放锁)"""
        with self.state_lock:
            if ts_code in self.trailing_stops:
                return dict(self.trailing_stops[ts_code])
        return None

    def _get_backtester(self) -> Optional[Any]:
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
    
    @staticmethod
    def _extract_cost(pos_or_cost) -> float:
        """从Position对象或float值提取成本价【v2.9.52:替代hasattr防御】"""
        if isinstance(pos_or_cost, (int, float)):
            return pos_or_cost
        return pos_or_cost.avg_cost

    def calc_stop_loss_price(self, pos_or_cost, risk: Dict) -> float:
        """统一止损价计算"""
        cost = self._extract_cost(pos_or_cost)
        sl_pct = risk.get("stop_loss_pct", 0.03)
        return round(cost * (1 - sl_pct), 2)
    
    def calc_take_profit_price(self, pos_or_cost, risk: Dict) -> float:
        """统一止盈价计算"""
        cost = self._extract_cost(pos_or_cost)
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

            risk = self._get_risk_with_overrides(pos)
            stop_loss_pct = -risk.get("stop_loss_pct", 0.03) * 100
            take_profit_pct = risk.get("take_profit_pct", 0.07) * 100
            stop_loss_price = self.calc_stop_loss_price(pos, risk)

            sell_reason = None
            sell_price = pos.current_price

            # 追踪止损检查
            sell_reason, sell_price, trailing_triggered = self._check_trailing_stop(pos, risk)

            # 常规止损止盈+冲高回落等策略(追踪止损未触发时)
            if not trailing_triggered:
                sell_reason, sell_price = self._check_regular_stop_profit(
                    pos, risk, realtime_data, stop_loss_pct, take_profit_pct, stop_loss_price,
                )

            if sell_reason:
                to_sell.append((pos, sell_reason, sell_price, risk))

        return to_sell
    
    def _get_risk_with_overrides(self, pos) -> Dict:
        """获取策略级风控参数+单票覆盖【v2.9.45提取】"""
        risk = self._scanner._get_strategy_risk(pos.strategy)
        with self.state_lock:
            pos_overrides = dict(self.position_risk_overrides.get(pos.ts_code, {}))
        if 'stop_loss_pct' in pos_overrides:
            risk['stop_loss_pct'] = pos_overrides['stop_loss_pct']
        if 'take_profit_pct' in pos_overrides:
            risk['take_profit_pct'] = pos_overrides['take_profit_pct']
        return risk
    
    def _check_trailing_stop(self, pos, risk: Dict) -> Tuple:
        """追踪止损检查【v2.9.45提取】
        
        Returns: (sell_reason, sell_price, triggered)
        """
        trailing = self._get_trailing_stop_safe(pos.ts_code)
        if not trailing or not trailing.get("activated") or trailing.get("stop_price", 0) <= 0:
            return None, pos.current_price, False
        
        trailing_stop_price = trailing["stop_price"]
        if pos.current_price <= trailing_stop_price:
            high_price = trailing.get("high_price", pos.avg_cost)
            trailing_pct = trailing.get("trailing_stop_pct", 0)
            profit_at_high = (high_price / pos.avg_cost - 1) * 100 if pos.avg_cost > 0 else 0
            reason = f"追踪止损(最高{high_price:.2f}→{trailing_pct*100:.0f}%回撤, 曾盈{profit_at_high:.1f}%)"
            return reason, trailing_stop_price, True
        
        return None, pos.current_price, False
    
    def _check_regular_stop_profit(self, pos, risk: Dict, realtime_data: Dict,
                                    stop_loss_pct: float, take_profit_pct: float,
                                    stop_loss_price: float) -> Tuple:
        """常规止损止盈+冲高回落/利润保护/高开即卖【v2.9.45提取】
        
        Returns: (sell_reason, sell_price)
        """
        rt = realtime_data.get(pos.ts_code, {})
        today_open = rt.get("open", 0) if rt else self._get_open_price(pos.ts_code)
        
        sell_reason = None
        sell_price = pos.current_price
        
        # 固定止损/止盈
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
            sell_reason, sell_price = self._check_intraday_rules(
                pos, risk, today_open,
            )
        
        return sell_reason, sell_price
    
    def _check_intraday_rules(self, pos, risk: Dict, today_open: float) -> Tuple:
        """盘中冲高回落/利润保护/利润锁定/高开即卖/龙头低利润规则【v2.9.45提取, v2.9.64补齐利润锁定+龙头5天低利润】
        
        v2.9.64变更: 补齐两个P0缺失卖出条件
        - 利润锁定: 盘中冲高>=min_high_rise但从高点回撤>=pullback_pct→以close价卖出
        - 龙头5天低利润: 龙头低吸持仓>=5天且利润<3%→提前退出
        
        Returns: (sell_reason, sell_price) or (None, price)
        """
        if today_open <= 0:
            return None, pos.current_price
        
        open_rise = (today_open / pos.avg_cost - 1) if pos.avg_cost > 0 else 0
        close_rise = pos.profit_pct / 100
        next_day_sell_pct = risk.get("next_day_open_sell_pct", 0.03)
        
        # 冲高回落
        if open_rise >= next_day_sell_pct and pos.current_price < today_open:
            if open_rise >= 0.05:
                return f"冲高回落(开涨{open_rise*100:.1f}%)", today_open
            elif (today_open - pos.current_price) / today_open >= 0.01:
                return f"冲高回落(开涨{open_rise*100:.1f}%回落)", today_open
        
        # 利润保护
        if open_rise >= 0.02 and close_rise >= 0.02 and pos.current_price < today_open:
            return f"利润保护(收涨{close_rise*100:.1f}%)", pos.current_price
        
        # 【v2.9.64新增】利润锁定: 盘中冲高>=6%但从高点回撤>=2.5%→以close价卖出
        # 与sell_signal_checker.check_intraday_profit_lock对齐
        profit_lock_reason = self._check_intraday_profit_lock(pos, risk)
        if profit_lock_reason:
            return profit_lock_reason, pos.current_price
        
        # 高开即卖(首板策略专属)
        if open_rise >= next_day_sell_pct:
            strategy_name = pos.strategy
            if strategy_name in ('first_limit_up', '首板打板'):
                return f"高开即卖(开涨{open_rise*100:.1f}%)", today_open
        
        # 【v2.9.64新增】龙头5天低利润: 龙头低吸持仓5天+利润<3%→提前退出
        dragon_reason = self._check_dragon_head_early_exit(pos, risk)
        if dragon_reason:
            return dragon_reason, pos.current_price
        
        return None, pos.current_price
    
    def _check_intraday_profit_lock(self, pos, risk: Dict) -> Optional[str]:
        """盘中利润锁定: 冲高>=6%回撤>=2.5%仍盈>=2%→close价卖出【v2.9.64】
        
        对齐sell_signal_checker.check_intraday_profit_lock。
        此信号在利润保护之上、止盈之下,保护"冲高后大幅回落但仍有利润"的场景。
        """
        if pos.avg_cost <= 0 or pos.current_price <= 0:
            return None
        
        from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK
        min_high_rise = risk.get("intraday_lock_min_high_rise", GLOBAL_RISK.get("intraday_lock_min_high_rise", 0.06))
        pullback_pct = risk.get("intraday_lock_pullback_pct", GLOBAL_RISK.get("intraday_lock_pullback_pct", 0.025))
        min_profit = risk.get("intraday_lock_min_profit", GLOBAL_RISK.get("intraday_lock_min_profit", 0.02))
        
        # 从追踪止损获取盘中最高价(更精确), 回退到current_price
        trailing = self._get_trailing_stop_safe(pos.ts_code)
        high_price = trailing.get("high_price", pos.current_price) if trailing else pos.current_price
        
        high_rise = (high_price / pos.avg_cost - 1)
        close_rise = pos.profit_pct / 100
        
        # 必须冲高足够 + 从高点回撤 + 收盘仍有利润
        if high_rise >= min_high_rise and pos.current_price < high_price:
            intraday_pullback = (high_price - pos.current_price) / high_price
            if intraday_pullback >= pullback_pct and close_rise >= min_profit:
                return f"利润锁定(冲高{high_rise*100:.1f}%回撤{intraday_pullback*100:.1f}%仍盈{close_rise*100:.1f}%)"
        
        return None
    
    def _check_dragon_head_early_exit(self, pos, risk: Dict) -> Optional[str]:
        """龙头5天低利润: 龙头低吸持仓>=5天且利润<3%→提前退出【v2.9.64】
        
        对齐sell_signal_checker龙头5天低利润。仅dragon_head/龙头低吸策略生效。
        """
        strategy_name = pos.strategy or ""
        if strategy_name not in ('dragon_head', '龙头低吸'):
            return None
        if not pos.buy_date:
            return None
        
        from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK
        exit_days = risk.get("dragon_head_early_exit_days", GLOBAL_RISK.get("dragon_head_early_exit_days", 5))
        min_profit = risk.get("dragon_head_early_exit_min_profit", GLOBAL_RISK.get("dragon_head_early_exit_min_profit", 0.03))
        
        # 从scanner获取trade_date(运行时始终有值)
        scanner = self._scanner
        trade_date = scanner.get_trade_date() if scanner else None
        if not trade_date:
            return None
        
        days_held = self._calc_trade_days_held(pos.buy_date, trade_date)
        if days_held is None or days_held < exit_days:
            return None
        
        close_rise = pos.profit_pct / 100
        if close_rise < min_profit:
            return f"龙头5天低利润(持仓{days_held}天盈{close_rise*100:.1f}%<{min_profit*100:.0f}%)"
        
        return None
    
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
            
            # 【v2.9.82修复】用实时价格重算profit_pct, 避免pos.profit_pct基于过期current_price
            # 风控线程1秒检查时broker可能未update_realtime, pos.profit_pct可能不准
            if pos.avg_cost > 0 and current_price != pos.current_price:
                realtime_profit_pct = (current_price - pos.avg_cost) / pos.avg_cost * 100
            else:
                realtime_profit_pct = pos.profit_pct
            
            # 跌停不可卖处理
            handled, sell_item = self._handle_limit_down(pos, current_price)
            if sell_item:
                to_sell.append(sell_item)
            if handled:
                continue
            
            # 固定止损+追踪止损
            sell_item = self._check_quick_stop_loss(pos, rt, current_price, realtime_profit_pct)
            if sell_item:
                to_sell.append(sell_item)
        
        return to_sell
    
    def _handle_limit_down(self, pos, current_price: float) -> Tuple[bool, Optional[Tuple]]:
        """跌停不可卖处理: 挂起/恢复【v2.9.45提取】
        
        Returns: (handled, sell_item) — handled=True表示该持仓已处理(跳过后续检查)
        """
        ts_code = pos.ts_code
        
        if self._is_limit_down(ts_code):
            with self.state_lock:
                if ts_code not in self.pending_sells:
                    risk = self._scanner._get_strategy_risk(pos.strategy)
                    reason = f"跌停挂起(当前{current_price:.2f})"
                    self.pending_sells[ts_code] = {"reason": reason, "price": current_price, "added_at": time.time(), "source": "position_manager"}
                    logger.warning(f"[RISK] {ts_code} {reason}")
                else:
                    info = self.pending_sells[ts_code]
                    if isinstance(info, dict):
                        info["price"] = current_price
            return True, None
        
        # 跌停恢复: 之前挂起,现在不跌停了
        with self.state_lock:
            if ts_code in self.pending_sells:
                info = self.pending_sells.pop(ts_code)
                reason = info.get("reason", "跌停恢复") if isinstance(info, dict) else info[0]
                price = info.get("price", current_price) if isinstance(info, dict) else info[1]
                logger.info(f"[RISK] {ts_code} 跌停恢复,执行挂起卖出: {reason}")
                risk = self._scanner._get_strategy_risk(pos.strategy)
                return True, (pos, reason, price, risk)
        
        return False, None
    
    def _check_quick_stop_loss(self, pos, rt: Dict, current_price: float, realtime_profit_pct: float = None) -> Optional[Tuple]:
        """快速止损检查: 固定止损+追踪止损【v2.9.45提取, v2.9.82:realtime_profit_pct参数】
        
        Note: 使用_get_risk_with_overrides获取完整风控参数(含take_profit覆盖),
        虽然止损检查不使用take_profit, 但统一获取减少分支。
        
        Args:
            pos: 持仓对象
            rt: 实时行情dict
            current_price: 实时价格
            realtime_profit_pct: 用实时价格计算的profit_pct(v2.9.82新增)
        
        Returns: (pos, reason, price, risk) or None
        """
        ts_code = pos.ts_code
        risk = self._get_risk_with_overrides(pos)
        sl_pct = -risk.get("stop_loss_pct", 0.03) * 100
        
        # 【v2.9.82修复】优先用实时profit_pct, 避免pos.profit_pct基于过期current_price
        check_profit_pct = realtime_profit_pct if realtime_profit_pct is not None else pos.profit_pct
        
        # 固定止损
        if check_profit_pct <= sl_pct:
            stop_loss_price = self.calc_stop_loss_price(pos, risk)
            today_open = rt.get("open", 0)
            if today_open > 0 and today_open < stop_loss_price:
                return (pos, f"跳空止损(开{today_open:.2f}<止损{stop_loss_price:.2f})", today_open, risk)
            else:
                return (pos, f"止损 {check_profit_pct:.1f}%", current_price, risk)
        
        # 追踪止损
        with self.state_lock:
            trailing = dict(self.trailing_stops.get(ts_code, {})) if ts_code in self.trailing_stops else None
        if trailing and trailing.get("activated") and trailing.get("stop_price", 0) > 0:
            if current_price <= trailing["stop_price"]:
                return (pos, f"追踪止损(回撤至{current_price:.2f})", trailing["stop_price"], risk)
        
        return None
    
    def _update_single_trailing_stop(
        self, ts_code: str, current_price: float, avg_cost: float,
        profit_pct: float, trailing_stop_pct: float
    ) -> Dict:
        """更新单个持仓的追踪止损状态, 返回更新后的state【v2.9.62提取】"""
        with self.state_lock:
            state = dict(self.trailing_stops.get(ts_code, {
                "high_price": avg_cost,
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
            return state

    def update_trailing_stops(self, positions, realtime_data: Dict) -> None:
        """更新追踪止损状态(每轮扫描后调用)

        规则(与真实超短量化对齐):
        1. 买入后, 初始止损=固定止损(如-3%)
        2. 当盈利>=2%时, 激活追踪止损, 止损线=最高价×(1-trailing_pct)
        3. 价格创新高时, 止损线上移
        4. 价格回落触发追踪止损时卖出, 锁住大部分利润

        线程安全: 通过state_lock保护trailing_stops读写
        【v2.9.62重构: 提取_update_single_trailing_stop】
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

            self._update_single_trailing_stop(
                ts_code, current_price, pos.avg_cost, profit_pct, trailing_stop_pct
            )
    
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
            # 连板股重仓(limit_up_count字段)
            limit_count = signal.limit_up_count
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
        pipeline_ratio = self._scanner._current_position_ratio
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

    def _retry_single_pending_sell(self, ts_code: str, info: Dict, positions) -> bool:
        """重试单个挂起卖出, 返回是否成功【v2.9.62提取】"""
        scanner = self._scanner

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
            return False

        # 检查是否不再跌停
        if self._is_limit_down(ts_code):
            return False  # 仍在跌停, 无法卖出

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
                return True
            except Exception as e:
                logger.debug(f"[RISK_THREAD] 跌停恢复重试失败: {ts_code} {e}")
        return False

    def retry_pending_sells(self, realtime_data: Dict) -> None:
        """跌停恢复后重试挂起的卖出指令【v2.9.22提取, v2.9.27:从scanner移入PositionManager, v2.9.62重构】

        当股票从跌停恢复(非跌停状态)且有挂起的卖出指令时,
        重新尝试执行该卖出。避免跌停恢复后卖出指令被遗忘。
        """
        with self.state_lock:
            pending = dict(self.pending_sells)
        if not pending:
            return

        retried = []
        for ts_code, info in pending.items():
            if self._retry_single_pending_sell(ts_code, info, None):
                retried.append(ts_code)

        # 清除成功重试的条目
        if retried:
            with self.state_lock:
                for code in retried:
                    self.pending_sells.pop(code, None)

    def execute_sell_list_from_risk(self, to_sell: list) -> None:
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

    async def execute_risk_sell(self, pos, reason: str, price: float, quantity: int) -> None:
        """风控线程触发的卖出执行(在asyncio主循环中运行)

        【v2.9.35: 从scanner._execute_risk_sell提取】
        v2.9.12: try/except保护
        v2.9.19: 提取_post_sell_cleanup
        v2.9.71: trace_id贯穿
        """
        import uuid
        scanner = self._scanner
        if pos.available_qty <= 0:
            return

        trace_id = f"risk-{pos.ts_code}-{uuid.uuid4().hex[:8]}"
        # 【v2.9.82修复】不再用pos.profit_pct预估值,卖出后从order取实际盈亏
        # 旧代码: sell_profit_pct = pos.profit_pct / sell_profit_amount = (pos.current_price - pos.avg_cost) * quantity
        # 问题: pos.current_price可能与实际成交价(fill_price)不同, 导致timeline/EventBus记录的盈亏不准
        sell_profit_pct = None  # 占位, 卖出成功后从order填充
        sell_profit_amount = None

        try:
            scanner._broker.update_realtime(pos.ts_code, pos.current_price)
            ok, msg, order = scanner._broker.place_order(
                ts_code=pos.ts_code, stock_name=pos.stock_name,
                side="sell", quantity=quantity, price=price,
                order_type="market", strategy=pos.strategy, reason=reason,
            )
        except Exception as e:
            logger.error(f"[RISK_SELL] place_order异常 {pos.ts_code}: {e} trace={trace_id}")
            return

        if ok:
            # 【v2.9.82修复】使用broker实际成交的盈亏, 而非卖出前的预估值
            actual_profit_pct = order.profit_pct if order.profit_pct != 0 else pos.profit_pct
            actual_profit_amount = order.profit_amount if order.profit_amount != 0 else sell_profit_amount
            await scanner._post_sell_cleanup(
                pos, reason, order, quantity,
                actual_profit_pct, actual_profit_amount, source="risk_sell",
                trace_id=trace_id,
            )
        else:
            logger.warning(f"[RISK_SELL] 卖出失败 {pos.ts_code}: {msg} trace={trace_id}")

    async def liquidate_positions(self, reason: str, source: str) -> Tuple[int, int]:
        """批量清仓: 卖出所有可用持仓

        【v2.9.35: 从scanner._liquidate_positions提取】
        _sell_all_positions(停止清仓)和_execute_force_empty(强制空仓)的公共实现。
        使用available_qty(T+1合规), 单票异常不中断。
        v2.9.71: 每笔卖出带trace_id。

        Returns:
            (sold, failed) 成功/失败数
        """
        import uuid
        scanner = self._scanner
        if not scanner._broker:
            return 0, 0
        positions = scanner._broker.get_positions()
        sold, failed = 0, 0
        for p in positions:
            if p.available_qty <= 0:
                continue  # T+1: 不可卖跳过
            trace_id = f"liq-{p.ts_code}-{uuid.uuid4().hex[:8]}"
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
                # 【v2.9.82修复】使用broker实际成交的盈亏, 而非预估值
                if ok:
                    sold += 1
                    actual_profit_pct = order.profit_pct if order.profit_pct != 0 else p.profit_pct
                    actual_profit_amount = order.profit_amount if order.profit_amount != 0 else profit_amount
                    await scanner._post_sell_cleanup(
                        p, reason, order, p.available_qty,
                        actual_profit_pct, actual_profit_amount, source=source,
                        trace_id=trace_id,
                    )
                else:
                    failed += 1
                    logger.warning(f"[{source.upper()}] {p.ts_code} 卖出失败: {msg} trace={trace_id}")
            except Exception as e:
                failed += 1
                logger.error(f"[{source.upper()}] {p.ts_code} 异常: {e} trace={trace_id}")
        logger.info(f"[{source.upper()}] 完成: 卖出{sold}只, 失败{failed}只")
        return sold, failed
