"""
策略筛选模块（拆分Phase 3产物）

⚠️ 注意：本模块已从portfolio_backtest.py拆分出来，但尚未被主引擎引用。
   portfolio_backtest.py仍使用内联的_build_strategy_filter_conditions方法。
   待Phase 6-8完成拆分后，本模块将被正式集成。
   当前状态：独立可用，但未被调用。
"""

from typing import Dict, List, Any
from nodes.backtest_engine.strategy_defaults import STRATEGY_CONFIGS, GLOBAL_RISK


class StrategyFilter:
    """策略筛选器"""
    
    def __init__(self):
        self.strategy_conditions = {}
    
    def build_strategy_filter_conditions(self, strategy_name: str, params: dict) -> list:
        """构建单个策略的因子筛选条件
        
        Args:
            strategy_name: 策略名称(中文)
            params: 策略参数字典
            
        Returns:
            list: 策略筛选条件列表
        """
        converted_params = {}
        for k, v in params.items():
            if isinstance(v, bool):
                converted_params[k] = 1 if v else 0
            elif isinstance(v, str) and v.replace(".", "", 1).isdigit():
                converted_params[k] = float(v)
            else:
                converted_params[k] = v
        
        if strategy_name == "半路追涨":
            return self._build_halfway_chase_conditions(converted_params)
        elif strategy_name == "首板打板":
            return self._build_first_limit_up_conditions(converted_params)
        elif strategy_name == "涨停开板":
            return self._build_limit_up_open_conditions(converted_params)
        elif strategy_name == "龙头低吸":
            return self._build_dragon_head_conditions(converted_params)
        elif strategy_name == "跌停翘板":
            return self._build_limit_down_qiao_conditions(converted_params)
        else:
            return []
    
    def _build_halfway_chase_conditions(self, params: dict) -> list:
        """半路追涨筛选条件"""
        min_rise_pct = params.get("min_rise_pct", 0.03)
        max_rise_pct = params.get("max_rise_pct", 0.07)
        min_volume_ratio = params.get("min_volume_ratio", 2.0)
        max_volume_ratio = params.get("max_volume_ratio", 3.0)
        min_close_rise = params.get("min_close_rise_pct", 0.03)
        max_open_rise = params.get("max_open_rise_pct", 0.03)
        
        conditions = [
            {"name": "intraday_max_rise_pct", "target": min_rise_pct * 100, "operator": ">=", 
             "label": f"盘中最高涨幅≥{min_rise_pct*100:.0f}%"},
            {"name": "intraday_max_rise_pct", "target": max_rise_pct * 100, "operator": "<=", 
             "label": f"盘中最高涨幅≤{max_rise_pct*100:.0f}%"},
            {"name": "intraday_open_rise_pct", "target": max_open_rise * 100, "operator": "<=", 
             "label": f"开盘涨幅≤{max_open_rise*100:.0f}%"},
            {"name": "volume_ratio", "target": min_volume_ratio, "operator": ">=", 
             "label": f"量比≥{min_volume_ratio}"},
        ]
        
        if max_volume_ratio and max_volume_ratio < 100:
            conditions.append({"name": "volume_ratio", "target": max_volume_ratio, "operator": "<=", 
                              "label": f"量比≤{max_volume_ratio}"})
        
        if min_close_rise and min_close_rise > 0:
            conditions.append({"name": "pct_chg", "target": min_close_rise * 100, "operator": ">=", 
                              "label": f"收盘涨幅≥{min_close_rise*100:.0f}%"})
        
        return conditions
    
    def _build_first_limit_up_conditions(self, params: dict) -> list:
        """首板打板筛选条件"""
        min_circ_mv = (params.get("min_circulation_market_cap", 50)) * 10000
        max_circ_mv = (params.get("max_circulation_market_cap", 500)) * 10000
        min_volume_ratio = params.get("min_volume_ratio", 1.5)
        min_turnover = params.get("min_turnover_rate", 3)
        max_turnover = params.get("max_turnover_rate", 15)
        
        _fl_defaults = STRATEGY_CONFIGS.get("first_limit_up", {}).get("params", {})
        opening_pct_min = params.get("opening_pct_min", _fl_defaults.get("opening_pct_min", -1.0))
        opening_pct_max = params.get("opening_pct_max", _fl_defaults.get("opening_pct_max", 7.0))
        
        return [
            {"name": "first_limit_up", "target": 1, "label": "首次涨停"},
            {"name": "limit_up_yesterday", "target": 0, "label": "昨日未涨停"},
            {"name": "opening_pct_chg", "target": opening_pct_min, "operator": ">=", 
             "label": f"竞价涨幅≥{opening_pct_min}%"},
            {"name": "opening_pct_chg", "target": opening_pct_max, "operator": "<=", 
             "label": f"竞价涨幅≤{opening_pct_max}%"},
            {"name": "volume_ratio", "target": min_volume_ratio, "operator": ">=", 
             "label": f"量比≥{min_volume_ratio}"},
            {"name": "turnover_rate", "target": min_turnover, "operator": ">=", 
             "label": f"换手率≥{min_turnover}%"},
            {"name": "turnover_rate", "target": max_turnover, "operator": "<=", 
             "label": f"换手率≤{max_turnover}%"},
            {"name": "circ_mv", "target": min_circ_mv, "operator": ">=", 
             "label": f"流通市值≥{min_circ_mv//10000}亿"},
            {"name": "circ_mv", "target": max_circ_mv, "operator": "<=", 
             "label": f"流通市值≤{max_circ_mv//10000}亿"},
        ]
    
    def _build_limit_up_open_conditions(self, params: dict) -> list:
        """涨停开板筛选条件"""
        min_volume_ratio = params.get("min_volume_ratio", 2.0)
        min_turnover = params.get("min_turnover_rate", 15.0)
        
        return [
            {"name": "limit_up_yesterday", "target": 1, "operator": "==", "label": "昨日涨停"},
            {"name": "is_limit_up", "target": 0, "operator": "==", "label": "今日未封住"},
            {"name": "intraday_max_rise_pct", "target": 0, "operator": ">=", "label": "盘中最高涨幅≥0%"},
            {"name": "volume_ratio", "target": min_volume_ratio, "operator": ">=", 
             "label": f"量比≥{min_volume_ratio}"},
            {"name": "turnover_rate", "target": min_turnover, "operator": ">=", 
             "label": f"换手率≥{min_turnover}%"},
        ]
    
    def _build_dragon_head_conditions(self, params: dict) -> list:
        """龙头低吸筛选条件"""
        min_consecutive = params.get("min_consecutive_limit", 1)
        min_correction = params.get("min_correction_pct", 0.05)
        max_correction = params.get("max_correction_pct", 0.35)
        correction_days_min = params.get("correction_days_min", 1)
        correction_days_max = params.get("correction_days_max", 7)
        _min_circ = (params.get("min_circulation_market_cap", 30)) * 10000
        _min_vr = params.get("min_volume_ratio", 0.5)
        _max_vr = params.get("max_volume_ratio", 2.0)
        
        return [
            {"name": "circ_mv", "target": _min_circ, "operator": ">=", 
             "label": f"流通市值≥{_min_circ//10000}亿"},
            {"name": "limit_up_count", "target": min_consecutive, "operator": ">=", 
             "label": f"近5日至少{min_consecutive}板"},
            {"name": "pullback_pct", "target": -max_correction, "operator": ">=", 
             "label": f"回调≤{max_correction*100:.0f}%"},
            {"name": "pullback_pct", "target": -min_correction, "operator": "<=", 
             "label": f"回调≥{min_correction*100:.0f}%"},
            {"name": "pullback_days", "target": correction_days_min, "operator": ">=", 
             "label": "最小回调天数"},
            {"name": "pullback_days", "target": correction_days_max, "operator": "<=", 
             "label": "最大回调天数"},
            {"name": "volume_ratio", "target": _min_vr, "operator": ">=", 
             "label": f"量比≥{_min_vr}"},
            {"name": "volume_ratio", "target": _max_vr, "operator": "<=", 
             "label": f"量比≤{_max_vr}"},
        ]
    
    def _build_limit_down_qiao_conditions(self, params: dict) -> list:
        """跌停翘板筛选条件"""
        min_turnover_qiao = params.get("min_turnover_rate", 10.0)
        
        return [
            {"name": "limit_down_yesterday", "target": 1, "label": "昨日跌停"},
            {"name": "open_above_limit_down", "target": 1, "label": "开盘高于跌停价"},
            {"name": "circ_mv", "target": 200000, "operator": ">=", 
             "label": "流通市值≥20亿"},
            {"name": "turnover_rate", "target": min_turnover_qiao, "operator": ">=", 
             "label": f"换手率≥{min_turnover_qiao:.0f}%"},
        ]
    
    def get_strategy_for_stock(self, code: str, stock_to_strategy: dict) -> str:
        """获取股票对应的策略名称"""
        strategies = stock_to_strategy.get(code, [])
        if isinstance(strategies, list) and strategies:
            return strategies[0] if len(strategies) == 1 else strategies[0]
        return ""
