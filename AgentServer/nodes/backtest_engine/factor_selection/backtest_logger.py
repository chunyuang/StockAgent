"""
回测日志输出模块（拆分Phase 2产物）

⚠️ 注意：本模块已从portfolio_backtest.py拆分出来，但尚未被主引擎引用。
   portfolio_backtest.py仍使用内联的日志方法。
   待Phase 6-8完成拆分后，本模块将被正式集成。
   当前状态：独立可用，但未被调用。
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
