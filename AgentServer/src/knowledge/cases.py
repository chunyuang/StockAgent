"""
历史案例知识库

存储历史复盘案例，用于 RAG 检索和相似案例匹配。

内容:
- 市场环境特征
- 板块表现
- 情绪周期
- 后续走势
"""

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

from core.database import get_database


logger = logging.getLogger(__name__)


class CasesKnowledgeBase:
    """
    历史案例知识库
    
    存储历史复盘案例，用于：
    1. 相似案例检索（RAG）
    2. 历史规律总结
    3. 后市预测参考
    
    Example:
        kb = CasesKnowledgeBase()
        
        # 保存案例
        await kb.save_case(
            trade_date="20260305",
            features={
                "index_change": 1.5,
                "limit_up_count": 80,
                "sentiment_phase": "high_tide",
            },
            analysis="今日市场强势上涨...",
            outcome="次日延续上涨",
        )
        
        # 查找相似案例
        cases = await kb.find_similar_cases(
            features={"limit_up_count": 85, "sentiment_phase": "high_tide"}
        )
    """
    
    COLLECTION = "kb_cases"
    
    def __init__(self, db: Optional[AsyncIOMotorDatabase] = None):
        self.db = db
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    async def _get_db(self) -> AsyncIOMotorDatabase:
        """获取数据库连接"""
        if self.db is None:
            self.db = await get_database()
        return self.db
    
    async def save_case(
        self,
        trade_date: str,
        features: Dict[str, Any],
        analysis: str,
        outcome: Optional[str] = None,
        tags: List[str] = None,
        embedding: List[float] = None,
    ) -> str:
        """
        保存历史案例
        
        Args:
            trade_date: 交易日期
            features: 特征数据
                {
                    "index_change": float,      # 指数涨跌幅
                    "limit_up_count": int,      # 涨停家数
                    "limit_down_count": int,    # 跌停家数
                    "first_board": int,         # 首板数量
                    "max_step": int,            # 最高连板
                    "broken_rate": float,       # 炸板率
                    "northbound_flow": float,   # 北向资金
                    "sentiment_phase": str,     # 情绪阶段
                    "main_sector": str,         # 主线板块
                }
            analysis: 复盘分析内容
            outcome: 后续走势（用于回溯验证）
            tags: 标签
            embedding: 向量嵌入（用于相似度检索）
        
        Returns:
            案例ID
        """
        db = await self._get_db()
        
        doc = {
            "trade_date": trade_date,
            "features": features,
            "analysis": analysis,
            "outcome": outcome,
            "tags": tags or [],
            "embedding": embedding,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        
        # 使用 upsert 避免重复
        await db[self.COLLECTION].update_one(
            {"trade_date": trade_date},
            {"$set": doc},
            upsert=True,
        )
        
        self.logger.info(f"Saved case for {trade_date}")
        
        return trade_date
    
    async def update_outcome(
        self,
        trade_date: str,
        outcome: str,
    ) -> bool:
        """
        更新案例的后续走势
        
        Args:
            trade_date: 交易日期
            outcome: 后续走势描述
        
        Returns:
            是否更新成功
        """
        db = await self._get_db()
        
        result = await db[self.COLLECTION].update_one(
            {"trade_date": trade_date},
            {
                "$set": {
                    "outcome": outcome,
                    "updated_at": datetime.now(timezone.utc),
                },
            },
        )
        
        return result.modified_count > 0
    
    async def get_case(self, trade_date: str) -> Optional[Dict[str, Any]]:
        """获取指定日期的案例"""
        db = await self._get_db()
        
        case = await db[self.COLLECTION].find_one({"trade_date": trade_date})
        
        if case:
            case["_id"] = str(case["_id"])
        
        return case
    
    async def find_similar_cases(
        self,
        features: Dict[str, Any],
        limit: int = 5,
        use_vector: bool = False,
        embedding: List[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        查找相似案例
        
        Args:
            features: 特征数据
            limit: 返回数量
            use_vector: 是否使用向量检索
            embedding: 查询向量
        
        Returns:
            相似案例列表
        """
        db = await self._get_db()
        
        if use_vector and embedding:
            # 向量检索（需要 MongoDB Atlas 或向量数据库）
            # 这里简化处理，使用特征匹配
            pass
        
        # 基于特征的相似度匹配
        query = {"features": {"$exists": True}}
        
        cursor = db[self.COLLECTION].find(query).sort("trade_date", -1).limit(100)
        all_cases = await cursor.to_list(100)
        
        # 计算相似度
        scored_cases = []
        for case in all_cases:
            score = self._calculate_similarity(features, case.get("features", {}))
            case["similarity_score"] = score
            case["_id"] = str(case["_id"])
            scored_cases.append(case)
        
        # 按相似度排序
        scored_cases.sort(key=lambda x: x["similarity_score"], reverse=True)
        
        return scored_cases[:limit]
    
    def _calculate_similarity(
        self,
        features1: Dict[str, Any],
        features2: Dict[str, Any],
    ) -> float:
        """
        计算特征相似度
        
        简单的加权相似度计算
        """
        score = 0.0
        weights = {
            "sentiment_phase": 0.3,
            "limit_up_count": 0.2,
            "first_board": 0.15,
            "max_step": 0.15,
            "broken_rate": 0.1,
            "index_change": 0.1,
        }
        
        for key, weight in weights.items():
            v1 = features1.get(key)
            v2 = features2.get(key)
            
            if v1 is None or v2 is None:
                continue
            
            if isinstance(v1, str):
                # 字符串相等性
                if v1 == v2:
                    score += weight
            else:
                # 数值相似度（归一化差异）
                try:
                    diff = abs(float(v1) - float(v2))
                    max_val = max(abs(float(v1)), abs(float(v2)), 1)
                    similarity = 1 - min(diff / max_val, 1)
                    score += weight * similarity
                except (ValueError, TypeError):
                    pass
        
        return round(score, 3)
    
    async def find_by_sentiment_phase(
        self,
        phase: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        按情绪阶段查找案例
        
        Args:
            phase: 情绪阶段（ice_point, recovery, high_tide, ebb）
            limit: 返回数量
        
        Returns:
            案例列表
        """
        db = await self._get_db()
        
        cursor = db[self.COLLECTION].find({
            "features.sentiment_phase": phase,
        }).sort("trade_date", -1).limit(limit)
        
        cases = await cursor.to_list(limit)
        
        for case in cases:
            case["_id"] = str(case["_id"])
        
        return cases
    
    async def find_by_sector(
        self,
        sector: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        按主线板块查找案例
        
        Args:
            sector: 板块名称
            limit: 返回数量
        
        Returns:
            案例列表
        """
        db = await self._get_db()
        
        cursor = db[self.COLLECTION].find({
            "features.main_sector": {"$regex": sector, "$options": "i"},
        }).sort("trade_date", -1).limit(limit)
        
        cases = await cursor.to_list(limit)
        
        for case in cases:
            case["_id"] = str(case["_id"])
        
        return cases
    
    async def get_recent_cases(
        self,
        days: int = 30,
    ) -> List[Dict[str, Any]]:
        """
        获取近期案例
        
        Args:
            days: 回溯天数
        
        Returns:
            案例列表
        """
        db = await self._get_db()
        
        cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
        
        cursor = db[self.COLLECTION].find({
            "trade_date": {"$gte": cutoff_date},
        }).sort("trade_date", -1)
        
        cases = await cursor.to_list(None)
        
        for case in cases:
            case["_id"] = str(case["_id"])
        
        return cases
    
    async def ensure_indexes(self):
        """创建索引"""
        db = await self._get_db()
        
        await db[self.COLLECTION].create_index("trade_date", unique=True)
        await db[self.COLLECTION].create_index("features.sentiment_phase")
        await db[self.COLLECTION].create_index("features.main_sector")
        await db[self.COLLECTION].create_index("tags")
