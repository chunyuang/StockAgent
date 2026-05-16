#!/bin/bash
# portfolio_backtest.py 自动拆分脚本
# 按照拆分方案逐步提取代码到新文件

BASE_DIR="/root/.openclaw/workspace/StockAgent/AgentServer/nodes/backtest_engine/factor_selection"
SOURCE_FILE="$BASE_DIR/portfolio_backtest.py"

echo "开始拆分 portfolio_backtest.py..."
echo "源文件行数: $(wc -l < $SOURCE_FILE)"

# Phase 1 已完成：数据模型层
echo "✅ Phase 1: 数据模型层已完成"

# Phase 2: 日志输出层
echo "Phase 2: 创建日志输出层..."
cat > "$BASE_DIR/backtest_logger.py" << 'LOGGER_EOF'
"""
回测日志输出模块

负责所有回测过程中的日志输出，包括：
- 每日头部信息
- 市场环境分析
- 策略筛选结果
- 股票池清洗信息
- 每日汇总信息
"""

from typing import Dict, List, Set, Any
from core.managers import mongo_manager
from core.constants import C


class BacktestLogger:
    """回测日志输出器"""
    
    def __init__(self, log_func):
        """
        Args:
            log_func: 日志输出函数 (async def log(msg: str))
        """
        self.log = log_func
    
    async def print_daily_header(self, day_idx: int, total_days: int, trade_date: str):
        """打印每日头部信息"""
        await self.log(f"")
        await self.log(f"═══════════════════════════════════════════════════════════")
        await self.log(f"📅 第 {day_idx}/{total_days} 天 | 处理日期: {trade_date}")
        await self.log(f"═══════════════════════════════════════════════════════════")
    
    async def print_market_environment(self, trade_date: int) -> tuple:
        """打印市场环境分析
        
        Returns:
            (limit_up_count, limit_down_count, sentiment_score)
        """
        if trade_date is None:
            return 0, 0, 0
        
        td = int(trade_date)
        
        # 主板涨停/跌停统计
        main_pipeline = [
            {"$match": {"trade_date": td, "ts_code": {"$not": {"$regex": "^(30[01]|688|[84])"}}}},
            {"$group": {"_id": None,
                "up": {"$sum": {"$cond": [{"$gte": ["$pct_chg", 9.8]}, 1, 0]}},
                "down": {"$sum": {"$cond": [{"$lte": ["$pct_chg", -9.8]}, 1, 0]}}
            }}
        ]
        
        # 创业板+科创板涨停/跌停统计（20%板）
        gem_pipeline = [
            {"$match": {"trade_date": td, "ts_code": {"$regex": "^(30[01]|688)"}}},
            {"$group": {"_id": None,
                "up": {"$sum": {"$cond": [{"$gte": ["$pct_chg", 19.6]}, 1, 0]}},
                "down": {"$sum": {"$cond": [{"$lte": ["$pct_chg", -19.6]}, 1, 0]}}
            }}
        ]
        
        # 北交所涨停/跌停统计（30%板）
        bse_pipeline = [
            {"$match": {"trade_date": td, "ts_code": {"$regex": "^[84]"}}},
            {"$group": {"_id": None,
                "up": {"$sum": {"$cond": [{"$gte": ["$pct_chg", 29.8]}, 1, 0]}},
                "down": {"$sum": {"$cond": [{"$lte": ["$pct_chg", -29.8]}, 1, 0]}}
            }}
        ]
        
        # 平均涨跌幅统计
        avg_pipeline = [
            {"$match": {"trade_date": td}},
            {"$group": {"_id": None, "avg_pct": {"$avg": "$pct_chg"}}}
        ]
        
        # 执行查询
        main_result = await mongo_manager.aggregate(C.STOCK_DAILY, main_pipeline)
        gem_result = await mongo_manager.aggregate(C.STOCK_DAILY, gem_pipeline)
        bse_result = await mongo_manager.aggregate(C.STOCK_DAILY, bse_pipeline)
        avg_result = await mongo_manager.aggregate(C.STOCK_DAILY, avg_pipeline)
        
        # 统计涨停跌停数
        limit_up = (main_result[0].get("up", 0) if main_result else 0) + \
                   (gem_result[0].get("up", 0) if gem_result else 0) + \
                   (bse_result[0].get("up", 0) if bse_result else 0)
        
        limit_down = (main_result[0].get("down", 0) if main_result else 0) + \
                     (gem_result[0].get("down", 0) if gem_result else 0) + \
                     (bse_result[0].get("down", 0) if bse_result else 0)
        
        avg_pct = avg_result[0].get("avg_pct", 0) if avg_result else 0
        
        # 计算情绪评分
        sentiment_score = int(limit_up - limit_down + avg_pct * 10 + 50)
        sentiment_score = max(0, min(100, sentiment_score))
        
        # 情绪周期映射
        if sentiment_score >= 70:
            sentiment_level = "高潮期"
        elif sentiment_score >= 55:
            sentiment_level = "上升期"
        elif sentiment_score >= 40:
            sentiment_level = "震荡期"
        else:
            sentiment_level = "低迷期"
        
        # 输出市场环境
        await self.log(f"   📊 【市场环境】")
        await self.log(f"      • 涨停家数: {limit_up} 只")
        await self.log(f"      • 跌停家数: {limit_down} 只")
        await self.log(f"      • 平均涨幅: {avg_pct:.2f}%")
        await self.log(f"      • 情绪评分: {sentiment_score} ({sentiment_level})")
        
        return limit_up, limit_down, sentiment_score
    
    async def print_stock_pool_and_cleaning(self, trade_date: str, universe: set, 
                                             st_count: int, new_stock_count: int, 
                                             low_liquidity_count: int):
        """打印股票池清洗信息"""
        await self.log(f"   📦 【股票池清洗】")
        await self.log(f"      • 原始池: {len(universe) + st_count + new_stock_count + low_liquidity_count} 只")
        await self.log(f"      • ST股剔除: {st_count} 只")
        await self.log(f"      • 新股剔除: {new_stock_count} 只")
        await self.log(f"      • 低流动性剔除: {low_liquidity_count} 只")
        await self.log(f"      • 最终池: {len(universe)} 只")
    
    async def print_daily_summary(self, trade_date: str, holdings_count: int, cash: float):
        """打印每日汇总信息"""
        await self.log(f"")
        await self.log(f"═══════════════════════════════════════════════════════════")
        await self.log(f"📅 处理完成: {trade_date}")
        await self.log(f"   💵 当日持仓: {holdings_count} 只股票, 现金剩余: {cash:,.2f} 元")
        await self.log(f"═══════════════════════════════════════════════════════════")
LOGGER_EOF

echo "✅ Phase 2: 日志输出层创建完成"

# Phase 3: 策略筛选层
echo "Phase 3: 创建策略筛选层..."
cat > "$BASE_DIR/strategy_filter.py" << 'STRATEGY_EOF'
"""
策略筛选模块

负责构建各策略的筛选条件，包括：
- 半路追涨
- 首板打板
- 涨停开板
- 龙头低吸
- 跌停翘板
"""

from typing import Dict, List, Any
from .strategy_defaults import STRATEGY_CONFIGS, GLOBAL_RISK


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
STRATEGY_EOF

echo "✅ Phase 3: 策略筛选层创建完成"

echo "拆分脚本准备完成，等待后续Phase..."
echo "当前进度: Phase 1 ✅ | Phase 2 ✅ | Phase 3 ✅"