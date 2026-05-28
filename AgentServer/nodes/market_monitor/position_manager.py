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
    
    # ==================== 属性代理(从scanner读取) ====================
    
    @property
    def broker(self):
        return self._scanner._broker
    
    @property
    def trailing_stops(self) -> Dict:
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
        """获取实际止损价(考虑追踪止损/移动止损)"""
        # 追踪止损
        trailing = self.trailing_stops.get(pos.ts_code)
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
            # 单票风控覆盖
            pos_overrides = self.position_risk_overrides.get(pos.ts_code, {})
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

            # 追踪止损检查
            trailing = self.trailing_stops.get(pos.ts_code)
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
                # 挂起(不丢追踪止损)
                if ts_code not in self.pending_sells:
                    risk = self._scanner._get_strategy_risk(pos.strategy)
                    reason = f"跌停挂起(当前{current_price:.2f})"
                    self.pending_sells[ts_code] = (reason, current_price)
                    logger.warning(f"[RISK] {ts_code} {reason}")
                continue
            
            # 跌停恢复: 之前挂起,现在不跌停了
            if ts_code in self.pending_sells:
                reason, price = self.pending_sells.pop(ts_code)
                logger.info(f"[RISK] {ts_code} 跌停恢复,执行挂起卖出: {reason}")
                risk = self._scanner._get_strategy_risk(pos.strategy)
                to_sell.append((pos, reason, price, risk))
                continue
            
            risk = self._scanner._get_strategy_risk(pos.strategy)
            # 单票覆盖
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
            trailing = self.trailing_stops.get(ts_code)
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
            
            state = self.trailing_stops.get(ts_code, {
                "high_price": pos.avg_cost,
                "trailing_stop_pct": trailing_stop_pct,
                "activated": False,
                "activated_at": None,
                "stop_price": 0.0,
            })
            
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
                buy_dt = int(pos.buy_date)
                cur_dt = int(trade_date)
                from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
                bt = PortfolioBacktester()
                days_held = bt._calc_trade_days_held(buy_dt, cur_dt)
                if days_held >= max_hold:
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
            pos_overrides = self.position_risk_overrides.get(pos.ts_code, {})
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
