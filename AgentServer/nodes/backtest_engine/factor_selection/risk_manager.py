"""
风控管理模块（拆分Phase 5产物）

⚠️ 注意：本模块已从portfolio_backtest.py拆分出来，但尚未被主引擎引用。
   portfolio_backtest.py仍使用内联的_get_sl_tp_for_code/check_force_empty等方法。
   待Phase 6-8完成拆分后，本模块将被正式集成。
   当前状态：独立可用，但未被调用。
"""

from typing import Dict, List, Tuple
from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK, STRATEGY_CONFIGS


class RiskManager:
    """风控管理器"""
    
    def __init__(self, risk_config: dict, strategy_risk_params: dict, strategy_params: dict):
        """
        Args:
            risk_config: 全局风控配置
            strategy_risk_params: 策略级风控参数
            strategy_params: 策略参数
        """
        self.risk_config = risk_config
        self.strategy_risk_params = strategy_risk_params
        self.strategy_params = strategy_params
    
    def get_sl_tp_for_code(self, code: str, stock_to_strategy: dict) -> Tuple[float, float]:
        """获取某只股票对应的策略级止损止盈参数
        
        Args:
            code: 股票代码
            stock_to_strategy: 股票到策略的映射
            
        Returns:
            Tuple[float, float]: (止损比例, 止盈比例)
        """
        strategies = stock_to_strategy.get(code, [])
        global_sl = self.risk_config.get('stop_loss_pct', GLOBAL_RISK['stop_loss_pct'])
        global_tp = self.risk_config.get('take_profit_pct', 0.07)
        
        if isinstance(strategies, list) and strategies:
            sl = min(self.strategy_risk_params.get(s, {}).get('stop_loss_pct', global_sl) 
                     for s in strategies)
            tp = max(self.strategy_risk_params.get(s, {}).get('take_profit_pct', global_tp) 
                     for s in strategies)
            return sl, tp
        
        return global_sl, global_tp
    
    def get_slippage_for_code(self, code: str, stock_to_strategy: dict) -> float:
        """获取某只股票对应的策略级滑点
        
        Args:
            code: 股票代码
            stock_to_strategy: 股票到策略的映射
            
        Returns:
            float: 滑点比例
        """
        strategies = stock_to_strategy.get(code, [])
        global_slippage = self.risk_config.get('slippage_pct', GLOBAL_RISK['slippage_pct'])
        
        if isinstance(strategies, list) and strategies:
            slippages = []
            for s in strategies:
                sp = self.strategy_risk_params.get(s, {}).get('slippage_pct', global_slippage)
                slippages.append(sp)
            return max(slippages) if slippages else global_slippage
        
        return global_slippage
    
    def check_force_empty(self, limit_up_count: int, limit_down_count: int, 
                          index_pct_chg: float, force_empty_config: dict) -> Tuple[bool, str]:
        """检查是否触发强制空仓
        
        Args:
            limit_up_count: 涨停家数
            limit_down_count: 跌停家数
            index_pct_chg: 大盘涨跌幅
            force_empty_config: 强制空仓配置
            
        Returns:
            Tuple[bool, str]: (是否触发, 原因)
        """
        if not self.risk_config.get('enable_force_empty', True):
            return False, ""
        
        limit_down_threshold = force_empty_config.get('limit_down_count', 50)
        limit_up_threshold = force_empty_config.get('limit_up_count', 10)
        index_drop_threshold = force_empty_config.get('index_drop_pct', 0.02)
        
        # 跌停数极端
        if limit_down_count >= limit_down_threshold:
            return True, f"跌停数{limit_down_count}≥{limit_down_threshold}"
        
        # 涨停数极少（极端低迷）
        if limit_up_count <= limit_up_threshold and limit_down_count > limit_up_count * 3:
            return True, f"涨停数{limit_up_count}≤{limit_up_threshold}且跌停数{limit_down_count}远大于涨停"
        
        # 大盘暴跌
        if index_pct_chg <= -index_drop_threshold * 100:
            return True, f"大盘跌幅{index_pct_chg:.2f}%≤-{index_drop_threshold*100:.0f}%"
        
        return False, ""
    
    def check_stop_loss_take_profit(self, code: str, cost: float, low_price: float, 
                                     high_price: float, open_price: float, 
                                     stock_to_strategy: dict,
                                     enable_sl: bool = True, enable_tp: bool = True
                                    ) -> Tuple[bool, str, float]:
        """检查止损止盈触发
        
        Args:
            code: 股票代码
            cost: 成本价
            low_price: 最低价
            high_price: 最高价
            open_price: 开盘价
            stock_to_strategy: 股票到策略的映射
            enable_sl: 是否启用止损
            enable_tp: 是否启用止盈
            
        Returns:
            Tuple[bool, str, float]: (是否触发, 原因, 卖出价)
        """
        if cost <= 0:
            return False, "", 0
        
        sl_pct, tp_pct = self.get_sl_tp_for_code(code, stock_to_strategy)
        stop_price = cost * (1 - sl_pct)
        profit_price = cost * (1 + tp_pct)
        
        # 检查止损
        if enable_sl and low_price <= stop_price:
            # 跳空止损
            if open_price <= stop_price:
                return True, f"跳空止损(开{open_price:.2f}<止损{stop_price:.2f})", open_price
            else:
                return True, f"止损({sl_pct*100:.0f}%)", stop_price
        
        # 检查止盈
        if enable_tp and high_price >= profit_price:
            return True, f"止盈({tp_pct*100:.0f}%)", profit_price
        
        return False, "", 0
    
    def get_max_hold_days(self, code: str, stock_to_strategy: dict) -> int:
        """获取最大持仓天数
        
        Args:
            code: 股票代码
            stock_to_strategy: 股票到策略的映射
            
        Returns:
            int: 最大持仓天数
        """
        strategies = stock_to_strategy.get(code, [])
        global_max_hold = self.risk_config.get('max_hold_days', 999)
        
        if isinstance(strategies, list) and strategies:
            max_hold_days = None
            for s in strategies:
                smh = self.strategy_risk_params.get(s, {}).get('max_hold_days')
                if smh is not None:
                    if max_hold_days is None or smh < max_hold_days:
                        max_hold_days = smh
            return max_hold_days if max_hold_days is not None else global_max_hold
        
        return global_max_hold
