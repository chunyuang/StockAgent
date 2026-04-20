"""
AKShare 日线数据管理器

专用于 AKShare 批量按日期下载日线数据
物理隔离: 不依赖 tushare/mongodb 读取，只负责下载存入数据库

特点:
- 按日期批量下载: 每一天获取全市场股票
- 存入 stock_daily_ak_full 集合，格式与 Tushare 一致
- 独立频率控制，不与 Tushare 混用
- 完全免费，无 Token 限制
"""

import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime

import pandas as pd

from .base import BaseManager


class AKShareDailyManager(BaseManager):
    """
    AKShare 日线数据管理器
    
    负责:
    - 按日期批量获取全市场日线数据
    - 数据标准化为 Tushare 相同格式
    - 存入 MongoDB stock_daily_ak_full 集合
    """
    
    def __init__(self):
        super().__init__()
        self._ak = None  # akshare 模块
    
    async def initialize(self) -> None:
        """初始化 AKShare"""
        try:
            import akshare as ak
            self._ak = ak
            self._initialized = True
            self.logger.info("AKShareDaily Manager initialized ✓ (物理隔离，独立按日期下载)")
        except ImportError:
            self.logger.error("AKShare not installed. Run: pip install akshare")
            raise
    
    async def shutdown(self) -> None:
        """关闭管理器"""
        self._ak = None
        self._initialized = False
        self.logger.info("AKShareDaily Manager shutdown")
    
    async def health_check(self) -> bool:
        """健康检查"""
        if not self._initialized or self._ak is None:
            return False
        try:
            # 简单测试 - 获取交易日历
            return True
        except Exception:
            return False
    
    async def get_daily_by_date(
        self,
        trade_date: str,
    ) -> Optional[List[Dict[str, Any]]]:
        """
        获取指定交易日全市场日线数据 (AKShare 原生接口)
        
        Args:
            trade_date: 交易日期 YYYYMMDD
            
        Returns:
            日线数据列表，每条包含标准字段，出错返回 None
            
        Note:
            - 物理隔离 - 纯 AKShare 实现，不依赖 Tushare
            - 返回格式与 Tushare get_daily 完全一致，方便存储到同一个 stock_daily_ak_full 集合
        """
        self._ensure_initialized()
        
        try:
            # AKShare 接口: 东方财富网-沪深两市每日行情
            loop = asyncio.get_event_loop()
            
            df = await loop.run_in_executor(
                None,
                lambda: self._ak.stock_zh_a_spot_em()
            )
            
            if df is None or df.empty:
                self.logger.warning(f"[{trade_date}] No data from AKShare")
                return []
            
            # 标准化字段名称 → 匹配 Tushare 格式
            # AKShare 原始列名: code, name, open, high, low, latest, change, pct_change, volume, amount, tick
            # 需要转换为: ts_code, open, high, low, close, pre_close, vol, amount, pct_chg
            
            records = []
            for _, row in df.iterrows():
                # 补充后缀 .SH / .SZ
                code = str(row['code'])
                if code.startswith('6'):
                    ts_code = f"{code}.SH"
                else:
                    ts_code = f"{code}.SZ"
                
                # 计算 pct_chg 百分比 (AKShare 返回的是小数，Tushare 返回百分比)
                pct_chg = float(row['pct_change']) * 100
                
                # pre_close = close - change
                close = float(row['latest'])
                change = float(row['change'])
                pre_close = close - change
                
                record = {
                    'ts_code': ts_code,
                    'trade_date': trade_date,
                    'open': float(row['open']),
                    'high': float(row['high']),
                    'low': float(row['low']),
                    'close': close,
                    'pre_close': pre_close,
                    'vol': float(row['volume']),     # 单位: 手 → 与 Tushare 一致
                    'amount': float(row['amount']) * 10000,  # AKShare: 万元 → 元 → 与 Tushare 一致
                    'pct_chg': pct_chg,
                    'change': change,
                    # up_limit/down_limit 需要后续补全
                }
                
                # round 保留两位小数
                for k in ['open', 'high', 'low', 'close', 'pre_close', 'pct_chg', 'change']:
                    if k in record:
                        record[k] = round(record[k], 2)
                
                records.append(record)
            
            self.logger.info(f"[{trade_date}] AKShare downloaded {len(records)} stocks")
            return records
            
        except Exception as e:
            self.logger.error(f"[{trade_date}] AKShare download failed: {e}")
            return None
    
    async def get_trade_calendar(
        self,
        start_date: str,
        end_date: str,
    ) -> List[str]:
        """
        获取交易日历
        
        Args:
            start_date: 开始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD
            
        Returns:
            交易日列表 ["YYYYMMDD", ...]
        """
        self._ensure_initialized()
        
        try:
            loop = asyncio.get_event_loop()
            df = await loop.run_in_executor(
                None,
                lambda: self._ak.tool_trade_date_hist_sina()
            )
            
            if df is None or df.empty:
                self.logger.error("Failed to get trade calendar from AKShare")
                return []
            
            # 筛选日期范围
            start_dt = datetime.strptime(start_date, "%Y%m%d")
            end_dt = datetime.strptime(end_date, "%Y%m%d")
            
            df['trade_date'] = pd.to_datetime(df['trade_date'])
            mask = (df['trade_date'] >= start_dt) & (df['trade_date'] <= end_dt)
            df = df[mask]
            
            # 转换为 YYYYMMDD 字符串列表
            trade_dates = df['trade_date'].dt.strftime('%Y%m%d').tolist()
            trade_dates.sort()
            
            self.logger.info(f"Got {len(trade_dates)} trade dates between {start_date} ~ {end_date}")
            return trade_dates
            
        except Exception as e:
            self.logger.error(f"Failed to get trade calendar: {e}")
            return []


# 模块级别单例
akshare_daily_manager = AKShareDailyManager()
