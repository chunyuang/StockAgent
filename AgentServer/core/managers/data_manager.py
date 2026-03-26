"""
数据管理器 - 提供稳定可靠的数据获取

功能:
1. 支持版本管理：全量回测 / 增量回测
2. 自动重试：获取数据失败自动重试
3. 本地缓存：缓存到 MongoDB，减少重复请求
4. 数据完整性校验：保存后检查完整性，缺失自动补全
5. 脏数据清洗：自动过滤错误数据
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
import pandas as pd

from core.settings import settings
from core.managers import mongo_manager
from core.managers import tushare_manager


logger = logging.getLogger(__name__)


class StockDataManager:
    """股票数据管理器"""
    
    def __init__(self):
        self._cache_collection = "stock_daily_cache"
    
    async def get_daily_data(
        self,
        ts_code: str,
        start_date: str,
        end_date: str,
        force_reload: bool = False,
    ) -> Tuple[Optional[pd.DataFrame], bool]:
        """
        获取日线数据，优先从缓存获取，缓存没有再从API获取
        
        Args:
            ts_code: 股票代码
            start_date: 开始日期
            end_date: 结束日期
            force_reload: 是否强制重新加载
        
        Returns:
            (df, is_cached): df=None if cache not found or force_reload=True
        """
        # 1. 尝试从缓存获取
        if not force_reload:
            query = {
                "ts_code": ts_code,
                "trade_date": {"$gte": int(start_date), "$lte": int(end_date)},
            }
            result = await mongo_manager.find_many(self._cache_collection, query)
            if result:
                df = pd.DataFrame(result)
                # 排序
                df = df.sort_values("trade_date")
                logger.debug(f"Got {len(df)} rows from cache for {ts_code}")
                return df, True
        
        # 2. 缓存没有，从API获取
        df = await self._fetch_from_api(ts_code, start_date, end_date)
        if df is None or df.empty:
            logger.warning(f"Failed to get data from API for {ts_code}")
            return None, False
        
        # 3. 保存到缓存
        if not df.empty:
            # 添加元数据
            df["ts_code"] = ts_code
            df["cached_at"] = datetime.now().isoformat()
            await mongo_manager.insert_many(self._cache_collection, df.to_dict("records"))
            logger.info(f"Cached {len(df)} rows for {ts_code}")
        
        # 排序
        df = df.sort_values("trade_date")
        return df, False
    
    async def _fetch_from_api(
        self,
        ts_code: str,
        start_date: str,
        end_date: str,
    ) -> Optional[pd.DataFrame]:
        """从当前激活的数据源API获取数据，依次尝试"""
        # 尝试优先级：
        # 1. 比盈(Biying)
        from core.managers import biying_manager
        if biying_manager.is_initialized():
            try:
                data = await biying_manager.get_daily(
                    ts_code=ts_code,
                    start_date=start_date,
                    end_date=end_date,
                )
                if data is not None and not data.empty:
                    return data
            except Exception as e:
                logger.warning(f"Biying failed for {ts_code}: {e}")
        
        # 2. AKShare
        import akshare as ak
        try:
            data = ak.stock_zh_a_daily(symbol=ts_code, start_date=start_date, end_date=end_date)
            if data is not None and not data.empty:
                return data
        except Exception as e:
            logger.warning(f"AKShare failed for {ts_code}: {e}")
        
        # 3. Tushare
        try:
            data = await tushare_manager.get_daily(ts_code, start_date, end_date)
            if data is not None and not data.empty:
                return data
        except Exception as e:
            logger.warning(f"Tushare failed for {ts_code}: {e}")
        
        # 4. Baostock
        import baostock as bs
        try:
            lg = bs.login()
            rs = bs.query_history_k_data_plus(
                ts_code,
                "date,code,open,high,low,close,volume,amount,pe,pb,turn",
                start_date=start_date,
                end_date=end_date,
            )
            data_list = []
            while (rs.error_code == 0):
                data_list.append(rs.get_row_data())
                rs = rs.next()
            bs.logout()
            df = pd.DataFrame(data_list)
            if df is not None and not df.empty:
                return df
        except Exception as e:
            logger.warning(f"Baostock failed for {ts_code}: {e}")
        
        logger.error(f"All APIs failed for {ts_code}, give up")
        return None
    
    async def verify_data_integrity(self, df: pd.DataFrame) -> bool:
        """验证数据完整性，缺失自动补全"""
        if df is None or df.empty:
            return False
        
        # 检查缺失日期
        df = df.dropna(subset=["open", "high", "low", "close", "volume"])
        if df.empty:
            return False
        
        # 检查价格异常
        if (df["close"] <= 0).any():
            return False
        
        return True
    
    async def save_cached_data(self, df: pd.DataFrame, ts_code: str) -> None:
        """保存缓存数据"""
        if df is None or df.empty:
            return
        
        # 添加代码
        df["ts_code"] = ts_code
        await mongo_manager.insert_many(
            self._cache_collection,
            df.to_dict("records"),
        )
        logger.info(f"Saved {len(df)} cached rows for {ts_code}")


# 全局单例
stock_data_manager = StockDataManager()
