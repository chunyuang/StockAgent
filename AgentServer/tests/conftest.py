"""
MongoDB Mock 工具

为集成测试提供模拟的MongoDB访问，无需真实数据库。
使用 mongomock 替代 motor，提供同步API封装。
"""
import pytest
import mongomock
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, List, Any, Optional


class MockMongoManager:
    """模拟 MongoManager，提供核心CRUD方法的同步实现"""

    def __init__(self):
        self.client = mongomock.MongoClient()
        self.db = self.client["stock_test"]
        self._initialized = True

    async def find_many(self, collection: str, query: dict,
                        projection: dict = None, sort: list = None,
                        limit: int = 0) -> List[Dict]:
        cursor = self.db[collection].find(query, projection or {})
        if sort:
            cursor = cursor.sort(sort)
        if limit:
            cursor = cursor.limit(limit)
        return list(cursor)

    async def find_one(self, collection: str, query: dict,
                        projection: dict = None, sort: list = None) -> Optional[Dict]:
        cursor = self.db[collection].find(query, projection or {})
        if sort:
            cursor = cursor.sort(sort)
        result = cursor.limit(1)
        docs = list(result)
        return docs[0] if docs else None

    async def insert_one(self, collection: str, doc: dict) -> str:
        result = self.db[collection].insert_one(doc)
        return str(result.inserted_id)

    async def insert_many(self, collection: str, docs: list) -> int:
        if not docs:
            return 0
        result = self.db[collection].insert_many(docs)
        return len(result.inserted_ids)

    async def update_one(self, collection: str, query: dict, update: dict) -> bool:
        result = self.db[collection].update_one(query, update)
        return result.modified_count > 0

    async def delete_one(self, collection: str, query: dict) -> bool:
        result = self.db[collection].delete_one(query)
        return result.deleted_count > 0

    async def count(self, collection: str, query: dict) -> int:
        return self.db[collection].count_documents(query)

    async def aggregate(self, collection: str, pipeline: list) -> List[Dict]:
        return list(self.db[collection].aggregate(pipeline))

    async def bulk_upsert(self, collection: str, documents: list,
                          key_fields: list = None, batch_size: int = 1000) -> dict:
        upserted = 0
        modified = 0
        for doc in documents:
            if key_fields:
                query = {k: doc.get(k) for k in key_fields}
            else:
                query = {"_id": doc.get("_id")}
            result = self.db[collection].replace_one(query, doc, upsert=True)
            if result.upserted_id:
                upserted += 1
            else:
                modified += result.modified_count
        return {"upserted": upserted, "modified": modified}

    async def replace_one(self, collection: str, query: dict, doc: dict) -> bool:
        result = self.db[collection].replace_one(query, doc)
        return result.modified_count > 0

    # 插入测试数据的便捷方法
    def seed_data(self, collection: str, data: list):
        """批量插入测试数据"""
        if data:
            self.db[collection].insert_many(data)


@pytest.fixture
def mock_mongo():
    """创建 MockMongoManager 实例"""
    return MockMongoManager()


@pytest.fixture
def mock_mongo_with_stock_data(mock_mongo):
    """预填充股票日线数据的 MockMongoManager"""
    # 插入stock_daily_ak_full测试数据
    daily_data = [
        {"ts_code": "000001.SZ", "trade_date": 20250101, "open": 10.0, "high": 10.5,
         "low": 9.8, "close": 10.2, "pct_chg": 2.0, "vol": 100000, "amount": 1020000,
         "turnover_rate": 5.0, "circ_mv": 5000000, "pre_close": 10.0},
        {"ts_code": "000001.SZ", "trade_date": 20250102, "open": 10.2, "high": 10.8,
         "low": 10.0, "close": 10.5, "pct_chg": 2.94, "vol": 120000, "amount": 1260000,
         "turnover_rate": 6.0, "circ_mv": 5150000, "pre_close": 10.2},
        {"ts_code": "000001.SZ", "trade_date": 20250103, "open": 10.5, "high": 10.6,
         "low": 10.1, "close": 10.3, "pct_chg": -1.90, "vol": 90000, "amount": 927000,
         "turnover_rate": 4.5, "circ_mv": 5050000, "pre_close": 10.5},
        # 第二只股票
        {"ts_code": "600000.SH", "trade_date": 20250101, "open": 20.0, "high": 20.5,
         "low": 19.8, "close": 20.3, "pct_chg": 1.5, "vol": 200000, "amount": 4060000,
         "turnover_rate": 3.0, "circ_mv": 20000000, "pre_close": 20.0},
        {"ts_code": "600000.SH", "trade_date": 20250102, "open": 20.3, "high": 21.0,
         "low": 20.0, "close": 20.8, "pct_chg": 2.46, "vol": 220000, "amount": 4576000,
         "turnover_rate": 3.3, "circ_mv": 20500000, "pre_close": 20.3},
    ]
    mock_mongo.seed_data("stock_daily_ak_full", daily_data)

    # 插入stock_basic测试数据
    basic_data = [
        {"ts_code": "000001.SZ", "name": "平安银行", "industry": "银行", "market": "主板", "list_status": "L"},
        {"ts_code": "600000.SH", "name": "浦发银行", "industry": "银行", "market": "主板", "list_status": "L"},
        {"ts_code": "300001.SZ", "name": "特锐德", "industry": "电气设备", "market": "创业板", "list_status": "L"},
    ]
    mock_mongo.seed_data("stock_basic", basic_data)

    # 插入index_daily测试数据
    index_data = [
        {"ts_code": "000001.SH", "trade_date": 20250101, "close": 3000.0, "pct_chg": 0.5},
        {"ts_code": "000001.SH", "trade_date": 20250102, "close": 3020.0, "pct_chg": 0.67},
        {"ts_code": "000001.SH", "trade_date": 20250103, "close": 3010.0, "pct_chg": -0.33},
    ]
    mock_mongo.seed_data("index_daily", index_data)

    return mock_mongo
