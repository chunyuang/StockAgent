"""
本地 MongoDB 数据服务
基于已存储在 MongoDB 的选股信号和价格历史数据，提供和 akshare 完全对齐的接口
用于回测可以重复运行，不需要每次重新从网络获取数据
"""
from typing import List, Dict, Optional
import pandas as pd
import pymongo
from datetime import datetime

import sys
sys.path.insert(0, '/root/.openclaw/workspace')  # FIXME: 硬编码绝对路径 + sys.path.insert反模式，应通过pyproject.toml/pip install -e . 解决模块查找
from data_fetcher.fetchers.base import BaseFetcher


class LocalMongoService(BaseFetcher):
    """本地 MongoDB 数据服务
    
    基于已存储在 MongoDB 的选股信号和价格历史数据，
    提供和 akshare 完全对齐的接口，用于回测可重复运行，
    不需要每次重新从网络获取数据。
    
    数据集合：
    - price_history: 完整历史价格K线
    - strategy_signals: 选股信号（trade_date/strategy/ts_code/is_signal/score/reason）
    - stock_basic: 股票基础信息
    - financial_metrics/financial_income/financial_balance/financial_cashflow: 财务数据
    """
    
    def __init__(self, mongo_uri: str = "mongodb://localhost:27017/", db_name: str = "stock_agent"):  # FIXME: MongoDB连接URI硬编码默认值，应从环境变量或配置文件读取
        """初始化本地数据服务
        
        Args:
            mongo_uri: MongoDB连接URI，默认本地27017端口
            db_name: 数据库名称，默认 stock_agent
        """
        self.client = pymongo.MongoClient(mongo_uri)
        self.db = self.client[db_name]
        self.price_coll = self.db['price_history']
        self.signal_coll = self.db['strategy_signals']
        self.basic_coll = self.db['stock_basic']
        
        # 缓存
        self._price_cache: Dict[str, pd.DataFrame] = {}
    
    def _convert_date(self, date_val) -> int:
        """转换日期为 int 格式 YYYYMMDD
        
        支持多种输入格式：int/str(含/不含横杠)/datetime/NaN。
        NaN返回0，其他无效输入也返回0。
        
        Args:
            date_val: 日期值，支持 int/str/datetime 类型
        
        Returns:
            int: YYYYMMDD格式的整数，如 20240101
        """
        if pd.isna(date_val):
            return 0
        if isinstance(date_val, int):
            return date_val
        if isinstance(date_val, str):
            return int(date_val.replace('-', ''))
        if isinstance(date_val, datetime):
            return int(date_val.strftime("%Y%m%d"))
        return 0
    
    def get_price_history(
        self,
        ts_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """获取股票历史价格数据
        
        优先从内存缓存读取，缓存未命中则查MongoDB。
        支持日期范围过滤，结果按日期升序排列。
        
        Args:
            ts_code: 股票代码（如 000001.SZ）
            start_date: 开始日期 YYYYMMDD，None表示从最早开始
            end_date: 结束日期 YYYYMMDD，None表示到最新结束
        
        Returns:
            DataFrame: 包含 date/open/high/low/close/volume/turnover/turnover_rate 列，
                       无数据时返回空DataFrame
        """
        # 先看缓存
        if ts_code in self._price_cache:
            df = self._price_cache[ts_code]
        else:
            # 从 MongoDB 查询
            query = {"ts_code": ts_code}
            cursor = self.price_coll.find(query)
            data = list(cursor)
            if not data:
                return pd.DataFrame()
            
            df = pd.DataFrame(data)
            # 缓存
            self._price_cache[ts_code] = df
        
        # 筛选日期范围
        if start_date:
            start_int = int(start_date)
            df = df[df['date'] >= start_int]
        if end_date:
            end_int = int(end_date)
            df = df[df['date'] <= end_int]
        
        # 按日期排序
        df = df.sort_values('date').reset_index(drop=True)
        
        return df

    def get_financial_metrics(
        self,
        ts_code: str,
    ) -> List[Dict]:
        """
        获取财务指标数据
        
        Returns:
            按时间倒序排列的财务指标列表
        """
        query = {"ts_code": ts_code}
        cursor = self.db['financial_metrics'].find(query).sort([("end_date", -1)])
        return list(cursor)

    def get_financial_statements(
        self,
        ts_code: str,
    ) -> Dict[str, List[Dict]]:
        """
        获取财务报表
        
        Returns:
        {
            "income": [...],  # 利润表
            "balance": [...],  # 资产负债表
            "cashflow": [...],  # 现金流量表
        }
        """
        result = {
            "income": [],
            "balance": [],
            "cashflow": [],
        }
        
        result["income"] = list(self.db['financial_income'].find(
            {"ts_code": ts_code}
        ).sort([("end_date", -1)]))
        
        result["balance"] = list(self.db['financial_balance'].find(
            {"ts_code": ts_code}
        ).sort([("end_date", -1)]))
        
        result["cashflow"] = list(self.db['financial_cashflow'].find(
            {"ts_code": ts_code}
        ).sort([("end_date", -1)]))
        
        return result

    def get_market_data(
        self,
        ts_code: str,
        trade_date: str,
    ) -> Dict:
        """
        获取当日市场数据
        
        Returns:
        {
            "market_cap": float,  # 总市值
            "turnover": float,  # 换手率
            "high_52week": float,  # 52周高点
            "low_52week": float,  # 52周低点
            "market_emotion_score": float,  # 市场情绪分数
        }
        """
        trade_date_int = int(trade_date)
        
        # 从 price_history 获取这一天的数据
        try:
            record = self.price_coll.find_one({
                "ts_code": ts_code,
                "date": trade_date_int,
            })
        except Exception as e:
            print(f"⚠️  查询市场数据失败: {e}")
            record = None
        
        if not record:
            return {
                "market_cap": 0,
                "turnover": 0,
                "high_52week": 0,
                "low_52week": 0,
                "market_emotion_score": 0,
            }
        
        # 计算 52 周高低点
        try:
            one_year_ago = (datetime.strptime(trade_date, "%Y%m%d").replace(year=int(trade_date[:4]) - 1)).strftime("%Y%m%d")
        except (ValueError, IndexError) as e:
            print(f"⚠️  日期解析失败: {e}")
            one_year_ago = str(int(trade_date) - 10000)  # 粗略回退1年
        one_year_ago_int = int(one_year_ago)
        
        recent = list(self.price_coll.find({
            "ts_code": ts_code,
            "date": {"$gte": one_year_ago_int},
            "date": {"$lte": trade_date_int},
        }))
        
        high_52week = 0
        low_52week = 0
        if recent:
            closes = [r['close'] for r in recent if r['close'] > 0]
            if closes:
                high_52week = max(closes)
                low_52week = min(closes)
        
        return {
            "market_cap": record.get('market_cap', 0),
            "turnover": record.get('turnover_rate', 0),
            "high_52week": high_52week,
            "low_52week": low_52week,
            "market_emotion_score": record.get('market_emotion_score', 0),
        }
    
    def get_strategy_signals(
        self,
        strategy: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict]:
        """获取选股信号
        
        支持按策略名称和日期范围过滤，结果按 trade_date 升序排列。
        
        Args:
            strategy: 策略名称，None表示查询所有策略
            start_date: 开始日期（YYYYMMDD），支持含横杠格式
            end_date: 结束日期（YYYYMMDD），支持含横杠格式
        
        Returns:
            List[Dict]: 信号列表，每个信号包含 trade_date/strategy/ts_code/is_signal/score/reason
        """
        query = {}
        if strategy:
            query["strategy"] = strategy
        if start_date:
            # start_date 格式是 YYYYMMDD，去掉横杠
            start_date_clean = start_date.replace('-', '')
            query["trade_date"] = {"$gte": int(start_date_clean)}
        if end_date:
            end_date_clean = end_date.replace('-', '')
            if "trade_date" not in query:
                query["trade_date"] = {}
            query["trade_date"]["$lte"] = int(end_date_clean)
        
        cursor = self.signal_coll.find(query).sort([("trade_date", 1)])
        return list(cursor)
    
    def clear_cache(self):
        """清空价格数据内存缓存
        
        当MongoDB数据更新后需调用此方法，
        否则get_price_history仍会返回旧缓存数据。
        """
        self._price_cache.clear()
