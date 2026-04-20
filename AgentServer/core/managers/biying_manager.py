"""
比盈 (Biying) 数据管理器

专用于 A股数据获取，比盈提供免费的日线、基本面、资金流等数据。

比盈官方网站: https://www.biyingapi.com/
文档: https://www.biyingapi.com/docs
"""

import aiohttp
from typing import Dict, Any, Optional
import pandas as pd

from .base import BaseManager
from ..settings import settings


class BiyingManager(BaseManager):
    """
    比盈数据管理器
    
    支持获取:
    - 日线行情数据
    - 每日指标 (PE/PB/市值等)
    - 涨跌停列表
    - 股票列表
    
    使用方法:
        daily = await biying_manager.get_daily("20251201")
    """
    
    BASE_URL = "https://api.biyingapi.com"
    
    def __init__(self):
        super().__init__()
        self._token = settings.biying.token.get_secret_value() if settings.biying.is_configured else None
        self._session = None
        self._initialized = False
    
    async def initialize(self) -> None:
        """初始化比盈管理器"""
        self._session = aiohttp.ClientSession()
        if not self._token:
            self.logger.warning("Biying token not configured. Set settings.biying.TOKEN to use it.")
        self._initialized = True
        self.logger.info("BiyingManager initialized ✓")
    
    async def shutdown(self) -> None:
        """关闭连接"""
        if self._session:
            await self._session.close()
        self._initialized = False
        self.logger.info("BiyingManager shutdown")
    
    async def health_check(self) -> bool:
        """健康检查"""
        return self._initialized and self._session is not None
    
    def has_token(self) -> bool:
        """检查是否配置了 token"""
        return self._token is not None and len(self._token) > 0
    
    async def _request(self, endpoint: str, params: Dict[str, Any]) -> Optional[Any]:
        """发送请求到比盈 API"""
        if not self.has_token():
            self.logger.error("Biying token not configured")
            return None
        
        url = f"{self.BASE_URL}/{endpoint}"
        params['token'] = self._token
        
        try:
            async with self._session.get(url, params=params, timeout=30) as resp:
                if resp.status != 200:
                    self.logger.error(f"Biying API error: status={resp.status}")
                    return None
                data = await resp.json()
                if data.get('code') != 200:
                    self.logger.error(f"Biying API error: {data.get('msg')}")
            return data
        except Exception as e:
            self.logger.error(f"Biying request failed: {e}")
            return None
    
    async def get_daily(self, trade_date: int) -> Optional[pd.DataFrame]:
        """
        获取指定交易日的日线行情数据
        
        Args:
            trade_date: 交易日期 (int, YYYYMMDD)
            
        Returns:
            日线行情 DataFrame，失败返回 None
            包含字段:
            - ts_code: 股票代码
            - trade_date: 交易日期
            - open: 开盘价
            - high: 最高价
            - low: 最低价
            - close: 收盘价
            - pre_close: 昨收价
            - vol: 成交量
            - amount: 成交额
            - pct_chg: 涨跌幅
        """
        self._ensure_initialized()
        
        data = await self._request("his/day", {"date": str(trade_date)})
        if data is None or data.get('data') is None:
            self.logger.debug(f"No daily data for {trade_date}")
            return None
        
        df = pd.DataFrame(data['data'])
        if df.empty:
            return None
        
        # 标准化列名匹配 Tushare/AkShare 格式
        df = df.rename(columns={
            'code': 'ts_code',
            'vol': 'vol',
            'amount': 'amount',
            'percent': 'pct_chg',
        })
        
        # 添加 ts_code 后缀 (.SH/.SZ)
        def add_suffix(code: str) -> str:
            if code.startswith(('6', '5', '9')):
                return f"{code}.SH"
            else:
                return f"{code}.SZ"
        
        df['ts_code'] = df['ts_code'].apply(add_suffix)
        df['trade_date'] = trade_date
        
        # pre_close 比盈不提供，计算一下
        if 'pre_close' not in df.columns:
            df['pre_close'] = df['close'] / (1 + df['pct_chg'] / 100)
        
        return df
    
    async def get_daily_basic(self, trade_date: int) -> Optional[pd.DataFrame]:
        """
        获取每日指标数据 (PE/PB/市值等)
        
        Args:
            trade_date: 交易日期
            
        Returns:
            每日指标 DataFrame
        """
        self._ensure_initialized()
        
        data = await self._request("fin/dailybasic", {"date": str(trade_date)})
        if data is None or data.get('data') is None:
            self.logger.debug(f"No daily basic data for {trade_date}")
            return None
        
        df = pd.DataFrame(data['data'])
        if df.empty:
            return None
        
        # 标准化列名
        df = df.rename(columns={
            'code': 'ts_code',
            'tr': 'turnover_rate',
            'trf': 'turnover_rate_f',
            'pe': 'pe',
            'pe_ttm': 'pe_ttm',
            'pb': 'pb',
            'ps': 'ps',
            'ps_ttm': 'ps_ttm',
            'dv_ratio': 'dv_ratio',
            'dv_ttm': 'dv_ttm',
            'total_mv': 'total_mv',
            'circ_mv': 'circ_mv',
        })
        
        # 添加后缀
        def add_suffix(code: str) -> str:
            if code.startswith(('6', '5', '9')):
                return f"{code}.SH"
            else:
                return f"{code}.SZ"
        
        df['ts_code'] = df['ts_code'].apply(add_suffix)
        df['trade_date'] = trade_date
        
        # 单位转换：比盈 总单位是 万元 → 转换为 亿元，匹配 Tushare 格式
        df['total_mv'] = df['total_mv'] / 10000
        df['circ_mv'] = df['circ_mv'] / 10000
        
        return df
    
    async def get_limit_list(self, trade_date: int) -> Optional[pd.DataFrame]:
        """
        获取涨跌停股票列表
        
        Args:
            trade_date: 交易日期
            
        Returns:
            涨跌停列表 DataFrame，包含 ts_code, trade_date, limit_type (1=涨停, -1=跌停)
        """
        self._ensure_initialized()
        
        data = await self._request("tools/limit", {"date": str(trade_date)})
        if data is None or data.get('data') is None:
            self.logger.debug(f"No limit list for {trade_date}")
            return None
        
        df = pd.DataFrame(data['data'])
        if df.empty:
            return None
        
        # 标准化
        def add_suffix(code: str) -> str:
            if code.startswith(('6', '5', '9')):
                return f"{code}.SH"
            else:
                return f"{code}.SZ"
        
        df['ts_code'] = df['code'].apply(add_suffix)
        df['trade_date'] = trade_date
        # limit: 1=涨停, -1=跌停
        df['limit_type'] = df['limit'].astype(int)
        
        return df
    
    async def get_stock_list(self) -> Optional[pd.DataFrame]:
        """
        获取当前股票列表
        
        Returns:
            股票列表 DataFrame
        """
        self._ensure_initialized()
        
        data = await self._request("company/list", {})
        if data is None or data.get('data') is None:
            self.logger.error("Failed to get stock list")
            return None
        
        df = pd.DataFrame(data['data'])
        if df.empty:
            return None
        
        # 标准化
        def add_suffix(code: str) -> str:
            if code.startswith(('6', '5', '9')):
                return f"{code}.SH"
            else:
                return f"{code}.SZ"
        
        df['ts_code'] = df['code'].apply(add_suffix)
        
        return df


# 全局单例
biying_manager = BiyingManager()
