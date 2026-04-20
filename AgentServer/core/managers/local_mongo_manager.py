"""
本地 MongoDB 数据管理器 (第三级数据源)

物理隔离: 纯本地读取，不依赖任何网络数据源 (Tushare/AKShare)
职责:
- 从 MongoDB 读取已经下载好的日线数据、基础信息、财务指标等
- 提供与 TushareManager/AKShareManager 完全一致的接口
- 回测时直接使用本地数据，避免重复网络请求，保证结果稳定

三级降级架构:
1. 一级: Tushare (按股票下载 → 存入 MongoDB) - 需要 Token，频率限制 500次/分钟
2. 二级: AKShare (按日期下载 → 存入 MongoDB) - 免费无限制，适合批量下载
3. 三级: LocalMongo (从 MongoDB 读取) - 纯本地，一次下载永久复用，结果完全稳定

特点:
- 物理隔离: 代码独立，不依赖任何网络 API
- 接口对齐: 与 TushareManager 提供相同接口，回测逻辑可无缝切换
- 统一格式: 所有网络数据源下载后统一格式存入 MongoDB，读取时无差异
- 完整覆盖: 策略和因子用到的所有数据都支持读取
"""

from typing import Optional, List, Dict, Any

import pymongo

from .base import BaseManager
from ..settings import settings


class LocalMongoManager(BaseManager):
    """
    本地 MongoDB 数据管理器 (第三级数据源)
    
    所有数据已经由 Tushare 或 AKShare 下载存入 MongoDB，
    此类只负责读取，不进行任何网络请求。
    
    物理隔离：不导入不依赖 tushare/akshare，纯本地读取。
    """
    
    def __init__(self):
        super().__init__()
        self._client: Optional[pymongo.MongoClient] = None
        self._db = None
    
    async def initialize(self) -> None:
        """初始化 MongoDB 连接"""
        if self._initialized:
            return
        
        self.logger.info("Initializing LocalMongo Manager (纯本地读取，物理隔离)...")
        
        self._client = pymongo.MongoClient(settings.mongo.url)
        self._db = self._client[settings.mongo.database]
        
        # 测试连接
        try:
            self._client.admin.command('ping')
            self._initialized = True
            count = self._db['stock_daily_ak_full'].count_documents({})
            self.logger.info(f"LocalMongo initialized ✓, stock_daily_ak_full 共 {count} 条记录")
        except Exception as e:
            self.logger.error(f"LocalMongo connection failed: {e}")
            raise
    
    async def shutdown(self) -> None:
        """关闭连接"""
        if self._client:
            self._client.close()
            self._client = None
            self._db = None
            self._initialized = False
            self.logger.info("LocalMongo shutdown")
    
    async def health_check(self) -> bool:
        """健康检查"""
        if not self._initialized or self._client is None or self._db is None:
            return False
        try:
            self._client.admin.command('ping')
            return True
        except Exception:
            return False
    
    # ==================== 股票基础信息 ====================
    
    async def get_stock_basic(
        self,
        ts_code: Optional[str] = None,
        list_status: str = "L",
    ) -> List[Dict[str, Any]]:
        """
        获取股票基础信息 (从 MongoDB stock_basic 集合读取)
        
        Args:
            ts_code: 股票代码，None 表示获取所有
            list_status: L-上市 D-退市 P-暂停上市
            
        Returns:
            股票基础信息列表，格式与 Tushare 一致
        """
        self._ensure_initialized()
        
        query = {}
        if ts_code:
            query["ts_code"] = ts_code
        if list_status:
            query["list_status"] = list_status
        
        cursor = self._db['stock_basic'].find(query)
        return list(cursor)
    
    # ==================== 日线数据 - 两种查询方式 ====================
    
    async def get_daily_by_stock(
        self,
        ts_code: str,
        start_date: str,
        end_date: str,
    ) -> Optional[List[Dict[str, Any]]]:
        """
        按股票查询日线数据 (本地 MongoDB 版本)
        
        Args:
            ts_code: 股票代码
            start_date: 开始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD
            
        Returns:
            日线数据列表，格式与 Tushare 一致
        """
        self._ensure_initialized()
        
        query = {
            "ts_code": ts_code,
            "trade_date": {"$gte": start_date, "$lte": end_date},
        }
        
        cursor = self._db['stock_daily_ak_full'].find(query).sort("trade_date", pymongo.ASCENDING)
        records = list(cursor)
        
        if not records:
            return None
        
        # 移除 MongoDB _id 字段，保持接口干净
        for r in records:
            r.pop('_id', None)
        
        return records
    
    async def get_daily_by_date(
        self,
        trade_date: str,
    ) -> Optional[List[Dict[str, Any]]]:
        """
        按日期查询全市场日线数据 (本地 MongoDB 版本)
        
        Args:
            trade_date: 交易日期 YYYYMMDD
            
        Returns:
            该交易日全市场日线数据列表，格式与 AKShare 下载的一致
        """
        self._ensure_initialized()
        
        query = {
            "trade_date": trade_date,
        }
        
        cursor = self._db['stock_daily_ak_full'].find(query)
        records = list(cursor)
        
        if not records:
            return None
        
        # 移除 MongoDB _id 字段
        for r in records:
            r.pop('_id', None)
        
        return records
    
    async def get_daily(
        self,
        ts_code: Optional[str] = None,
        trade_date: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        通用日线查询接口 (兼容 Tushare 接口)
        
        Args:
            ts_code: 股票代码 (支持逗号分隔多个)
            trade_date: 交易日期 (查询该日所有股票)
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            日线数据列表
        """
        self._ensure_initialized()
        
        query = {}
        
        if ts_code:
            # 支持逗号分隔多个
            ts_codes = ts_code.split(',')
            if len(ts_codes) == 1:
                query["ts_code"] = ts_codes[0]
            else:
                query["ts_code"] = {"$in": ts_codes}
        
        if trade_date:
            query["trade_date"] = trade_date
        
        if start_date:
            if "trade_date" not in query:
                query["trade_date"] = {}
            query["trade_date"]["$gte"] = start_date
        
        if end_date:
            if "trade_date" not in query:
                query["trade_date"] = {}
            query["trade_date"]["$lte"] = end_date
        
        cursor = self._db['stock_daily_ak_full'].find(query).sort([
            ("ts_code", pymongo.ASCENDING),
            ("trade_date", pymongo.ASCENDING),
        ])
        
        records = list(cursor)
        
        # 移除 _id
        for r in records:
            r.pop('_id', None)
        
        return records
    
    # ==================== 每日指标 (PE/PB/换手率/市值) ====================
    
    async def get_daily_basic(
        self,
        ts_code: Optional[str] = None,
        trade_date: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        获取每日指标 (从 MongoDB daily_basic 集合读取)
        
        Args:
            ts_code: 股票代码
            trade_date: 交易日期
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            每日指标列表，格式与 Tushare 一致
        """
        self._ensure_initialized()
        
        query = {}
        
        if ts_code:
            ts_codes = ts_code.split(',')
            if len(ts_codes) == 1:
                query["ts_code"] = ts_codes[0]
            else:
                query["ts_code"] = {"$in": ts_codes}
        
        if trade_date:
            query["trade_date"] = trade_date
        
        if start_date:
            if "trade_date" not in query:
                query["trade_date"] = {}
            query["trade_date"]["$gte"] = start_date
        
        if end_date:
            if "trade_date" not in query:
                query["trade_date"] = {}
            query["trade_date"]["$lte"] = end_date
        
        cursor = self._db['daily_basic'].find(query).sort([
            ("ts_code", pymongo.ASCENDING),
            ("trade_date", pymongo.ASCENDING),
        ])
        
        records = list(cursor)
        
        for r in records:
            r.pop('_id', None)
        
        return records
    
    # ==================== 涨跌停价格 ====================
    
    async def get_stk_limit(
        self,
        trade_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        获取每日涨跌停价格 (从 MongoDB limit_list 集合读取)
        
        Args:
            trade_date: 交易日期 YYYYMMDD
            
        Returns:
            涨跌停价格列表，格式与 Tushare 一致
        """
        self._ensure_initialized()
        
        query = {}
        if trade_date:
            query["trade_date"] = trade_date
        
        cursor = self._db['limit_list'].find(query)
        records = list(cursor)
        
        for r in records:
            r.pop('_id', None)
        
        return records
    
    # ==================== 财务数据 ====================
    
    async def get_financial_indicator(
        self,
        ts_code: str,
        period: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        获取财务指标 (从 MongoDB fina_indicator 集合读取)
        
        Args:
            ts_code: 股票代码
            period: 报告期 YYYYMMDD
            
        Returns:
            财务指标列表，按 end_date 降序排序
        """
        self._ensure_initialized()
        
        query = {"ts_code": ts_code}
        if period:
            query["end_date"] = period
        
        cursor = self._db['fina_indicator'].find(query).sort([
            ("end_date", pymongo.DESCENDING),
        ])
        
        records = list(cursor)
        
        for r in records:
            r.pop('_id', None)
        
        return records
    
    # ==================== 交易日历 ====================
    
    async def get_trade_cal(
        self,
        start_date: str,
        end_date: str,
    ) -> List[str]:
        """
        获取交易日历 (从 MongoDB trade_cal 集合读取)
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            交易日列表 (YYYYMMDD 格式字符串)
        """
        self._ensure_initialized()
        
        query = {
            "is_open": 1,
            "cal_date": {"$gte": start_date, "$lte": end_date},
        }
        
        cursor = self._db['trade_cal'].find(query).sort([
            ("cal_date", pymongo.ASCENDING),
        ])
        
        records = [doc['cal_date'] for doc in cursor if doc.get('cal_date')]
        
        return records
    
    # ==================== 指数数据 ====================
    
    async def get_index_daily(
        self,
        ts_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        获取指数日线数据 (从 MongoDB index_daily 集合读取)
        
        Args:
            ts_code: 指数代码
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            指数日线数据列表
        """
        self._ensure_initialized()
        
        query = {"ts_code": ts_code}
        
        if start_date:
            if "trade_date" not in query:
                query["trade_date"] = {}
            query["trade_date"]["$gte"] = start_date
        
        if end_date:
            if "trade_date" not in query:
                query["trade_date"] = {}
            query["trade_date"]["$lte"] = end_date
        
        cursor = self._db['index_daily'].find(query).sort([
            ("trade_date", pymongo.ASCENDING),
        ])
        
        records = list(cursor)
        
        for r in records:
            r.pop('_id', None)
        
        return records
    
    # ==================== 资金流向 ====================
    
    async def get_moneyflow_ind_ths(
        self,
        trade_date: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        获取同花顺行业资金流向 (从 MongoDB moneyflow_ind_ths 读取)
        """
        self._ensure_initialized()
        
        query = {}
        
        if trade_date:
            query["trade_date"] = trade_date
        if start_date:
            if "trade_date" not in query:
                query["trade_date"] = {}
            query["trade_date"]["$gte"] = start_date
        if end_date:
            if "trade_date" not in query:
                query["trade_date"] = {}
            query["trade_date"]["$lte"] = end_date
        
        cursor = self._db['moneyflow_ind_ths'].find(query).sort([("trade_date", pymongo.ASCENDING)])
        records = list(cursor)
        
        for r in records:
            r.pop('_id', None)
        
        return records
    
    async def get_moneyflow_cnt_ths(
        self,
        trade_date: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        获取同花顺概念板块资金流向 (从 MongoDB moneyflow_cnt_ths 读取)
        """
        self._ensure_initialized()
        
        query = {}
        
        if trade_date:
            query["trade_date"] = trade_date
        if start_date:
            if "trade_date" not in query:
                query["trade_date"] = {}
            query["trade_date"]["$gte"] = start_date
        if end_date:
            if "trade_date" not in query:
                query["trade_date"] = {}
            query["trade_date"]["$lte"] = end_date
        
        cursor = self._db['moneyflow_cnt_ths'].find(query).sort([("trade_date", pymongo.ASCENDING)])
        records = list(cursor)
        
        for r in records:
            r.pop('_id', None)
        
        return records
    
    # ==================== 统计工具 ====================
    
    def count_stock_daily_ak_full(self) -> int:
        """统计 stock_daily_ak_full 总记录数"""
        self._ensure_initialized()
        return self._db['stock_daily_ak_full'].count_documents({})
    
    def count_by_collection(self, collection_name: str) -> int:
        """统计指定集合记录数"""
        self._ensure_initialized()
        return self._db[collection_name].count_documents({})
    
    def check_data_exists(
        self,
        ts_code: str,
        trade_date: str,
    ) -> bool:
        """检查指定股票日期的数据是否已存在"""
        self._ensure_initialized()
        doc_id = f"{ts_code}_{trade_date}"
        return self._db['stock_daily_ak_full'].count_documents({"_id": doc_id}) > 0


# ==================== 全局单例 ====================
local_mongo_manager = LocalMongoManager()
