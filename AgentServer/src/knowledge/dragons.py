"""
龙头档案知识库

记录历史龙头股的信息，用于辅助识别和分析。

内容:
- 股票基本信息
- 成为龙头的时间和板块
- 连板高度和周期
- 操盘特征
"""

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

from motor.motor_asyncio import AsyncIOMotorDatabase

from core.database import get_database


logger = logging.getLogger(__name__)


class DragonsKnowledgeBase:
    """
    龙头档案知识库
    
    记录历史龙头股信息，用于：
    1. 识别曾经的龙头股
    2. 分析龙头股的操盘特征
    3. 辅助判断当前龙头的走势
    
    Example:
        kb = DragonsKnowledgeBase()
        
        # 记录龙头
        await kb.record_dragon(
            ts_code="000001.SZ",
            name="平安银行",
            sector="金融",
            role="龙一",
            start_date="20260301",
            max_step=5,
        )
        
        # 查询历史龙头
        dragons = await kb.get_sector_dragons("人工智能")
    """
    
    COLLECTION = "kb_dragons"
    
    ROLES = ["龙一", "龙二", "中军", "补涨", "跟风"]
    
    def __init__(self, db: Optional[AsyncIOMotorDatabase] = None):
        self.db = db
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    async def _get_db(self) -> AsyncIOMotorDatabase:
        """获取数据库连接"""
        if self.db is None:
            self.db = await get_database()
        return self.db
    
    async def record_dragon(
        self,
        ts_code: str,
        name: str,
        sector: str,
        role: str,
        start_date: str,
        end_date: Optional[str] = None,
        max_step: int = 1,
        characteristics: Dict[str, Any] = None,
        notes: str = "",
    ) -> str:
        """
        记录龙头股
        
        Args:
            ts_code: 股票代码
            name: 股票名称
            sector: 所属板块/主题
            role: 角色（龙一、龙二、中军等）
            start_date: 成为龙头的日期
            end_date: 结束日期
            max_step: 最高连板数
            characteristics: 操盘特征
            notes: 备注
        
        Returns:
            记录ID
        """
        db = await self._get_db()
        
        doc = {
            "ts_code": ts_code,
            "name": name,
            "sector": sector,
            "role": role,
            "start_date": start_date,
            "end_date": end_date,
            "max_step": max_step,
            "characteristics": characteristics or {},
            "notes": notes,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        
        result = await db[self.COLLECTION].insert_one(doc)
        
        self.logger.info(f"Recorded dragon: {name} ({role}) in {sector}")
        
        return str(result.inserted_id)
    
    async def update_dragon(
        self,
        ts_code: str,
        start_date: str,
        updates: Dict[str, Any],
    ) -> bool:
        """更新龙头记录"""
        db = await self._get_db()
        
        updates["updated_at"] = datetime.utcnow()
        
        result = await db[self.COLLECTION].update_one(
            {"ts_code": ts_code, "start_date": start_date},
            {"$set": updates},
        )
        
        return result.modified_count > 0
    
    async def get_stock_history(
        self,
        ts_code: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        获取股票的龙头历史
        
        Args:
            ts_code: 股票代码
            limit: 返回数量
        
        Returns:
            龙头记录列表
        """
        db = await self._get_db()
        
        cursor = db[self.COLLECTION].find(
            {"ts_code": ts_code}
        ).sort("start_date", -1).limit(limit)
        
        records = await cursor.to_list(limit)
        
        for r in records:
            r["_id"] = str(r["_id"])
        
        return records
    
    async def get_sector_dragons(
        self,
        sector: str,
        days: int = 90,
        role: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        获取板块的历史龙头
        
        Args:
            sector: 板块名称
            days: 回溯天数
            role: 角色过滤
        
        Returns:
            龙头记录列表
        """
        db = await self._get_db()
        
        cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
        
        query = {
            "sector": {"$regex": sector, "$options": "i"},
            "start_date": {"$gte": cutoff_date},
        }
        
        if role:
            query["role"] = role
        
        cursor = db[self.COLLECTION].find(query).sort("start_date", -1)
        records = await cursor.to_list(None)
        
        for r in records:
            r["_id"] = str(r["_id"])
        
        return records
    
    async def get_recent_dragons(
        self,
        days: int = 30,
        min_step: int = 2,
    ) -> List[Dict[str, Any]]:
        """
        获取近期龙头股
        
        Args:
            days: 回溯天数
            min_step: 最小连板数
        
        Returns:
            龙头记录列表
        """
        db = await self._get_db()
        
        cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
        
        cursor = db[self.COLLECTION].find({
            "start_date": {"$gte": cutoff_date},
            "max_step": {"$gte": min_step},
        }).sort([("max_step", -1), ("start_date", -1)])
        
        records = await cursor.to_list(None)
        
        for r in records:
            r["_id"] = str(r["_id"])
        
        return records
    
    async def find_similar_dragons(
        self,
        ts_code: str,
        sector: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        查找相似的历史龙头
        
        Args:
            ts_code: 当前股票代码
            sector: 板块名称
        
        Returns:
            相似龙头列表
        """
        db = await self._get_db()
        
        # 获取当前股票的板块
        if not sector:
            from core.managers import mongo_manager
            stock_map = await mongo_manager.find_one(
                "stock_sector_map",
                {"code": ts_code[:6]},
            )
            if stock_map:
                sectors = [s["name"] for s in stock_map.get("sectors", [])]
            else:
                sectors = []
        else:
            sectors = [sector]
        
        if not sectors:
            return []
        
        # 查找同板块历史龙头
        query = {
            "ts_code": {"$ne": ts_code},
            "$or": [
                {"sector": {"$regex": s, "$options": "i"}}
                for s in sectors[:3]
            ],
        }
        
        cursor = db[self.COLLECTION].find(query).sort("max_step", -1).limit(10)
        records = await cursor.to_list(10)
        
        for r in records:
            r["_id"] = str(r["_id"])
        
        return records
    
    async def auto_record_from_limit(
        self,
        trade_date: str,
    ) -> int:
        """
        从涨停数据自动记录龙头
        
        Args:
            trade_date: 交易日期
        
        Returns:
            记录数量
        """
        db = await self._get_db()
        
        # 获取连板数据
        step_data = await db["review_limit_step"].find({
            "trade_date": trade_date,
            "step": {"$gte": 3},
        }).to_list(None)
        
        if not step_data:
            return 0
        
        count = 0
        
        for item in step_data:
            ts_code = item.get("ts_code")
            name = item.get("name")
            step = item.get("step", 1)
            
            # 获取股票所属板块
            stock_map = await db["stock_sector_map"].find_one(
                {"code": ts_code[:6]}
            )
            
            sector = ""
            if stock_map:
                sectors = stock_map.get("sectors", [])
                if sectors:
                    sector = sectors[0].get("name", "")
            
            # 检查是否已记录
            existing = await db[self.COLLECTION].find_one({
                "ts_code": ts_code,
                "start_date": trade_date,
            })
            
            if not existing:
                await self.record_dragon(
                    ts_code=ts_code,
                    name=name,
                    sector=sector,
                    role="龙一" if step >= 5 else "龙二",
                    start_date=trade_date,
                    max_step=step,
                )
                count += 1
        
        self.logger.info(f"Auto recorded {count} dragons for {trade_date}")
        
        return count
    
    async def ensure_indexes(self):
        """创建索引"""
        db = await self._get_db()
        
        await db[self.COLLECTION].create_index([("ts_code", 1), ("start_date", -1)])
        await db[self.COLLECTION].create_index("sector")
        await db[self.COLLECTION].create_index("role")
        await db[self.COLLECTION].create_index([("start_date", -1), ("max_step", -1)])
