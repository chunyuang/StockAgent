"""
复盘规则知识库

存储和管理复盘分析的规则和标准。

规则分类:
- 涨停规则：首板判断、连板规则、炸板规则
- 板块规则：主线判断、轮动规则、强弱判断
- 情绪规则：周期判断、仓位建议
- 风险规则：止损规则、回避条件
"""

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

from core.database import get_database


logger = logging.getLogger(__name__)


class RulesKnowledgeBase:
    """
    规则知识库
    
    存储复盘分析使用的各类规则和标准。
    
    Example:
        kb = RulesKnowledgeBase()
        
        # 添加规则
        await kb.add_rule(
            category="涨停规则",
            name="首板强度判断",
            content="首板数量>60为强势，40-60为正常，<30为弱势",
            conditions={"first_board_strong": ">60"},
        )
        
        # 查询规则
        rules = await kb.get_rules(category="涨停规则")
    """
    
    COLLECTION = "kb_rules"
    
    CATEGORIES = [
        "涨停规则",
        "板块规则",
        "情绪规则",
        "风险规则",
        "联动规则",
    ]
    
    def __init__(self, db: Optional[AsyncIOMotorDatabase] = None):
        self.db = db
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    async def _get_db(self) -> AsyncIOMotorDatabase:
        """获取数据库连接"""
        if self.db is None:
            self.db = await get_database()
        return self.db
    
    async def add_rule(
        self,
        category: str,
        name: str,
        content: str,
        conditions: Dict[str, Any] = None,
        priority: int = 0,
        tags: List[str] = None,
    ) -> str:
        """
        添加规则
        
        Args:
            category: 规则分类
            name: 规则名称
            content: 规则内容
            conditions: 触发条件
            priority: 优先级
            tags: 标签
        
        Returns:
            规则ID
        """
        db = await self._get_db()
        
        doc = {
            "category": category,
            "name": name,
            "content": content,
            "conditions": conditions or {},
            "priority": priority,
            "tags": tags or [],
            "enabled": True,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        
        result = await db[self.COLLECTION].insert_one(doc)
        
        self.logger.info(f"Added rule: {name} ({category})")
        
        return str(result.inserted_id)
    
    async def update_rule(
        self,
        rule_id: str,
        updates: Dict[str, Any],
    ) -> bool:
        """更新规则"""
        from bson import ObjectId
        
        db = await self._get_db()
        
        updates["updated_at"] = datetime.now(timezone.utc)
        
        result = await db[self.COLLECTION].update_one(
            {"_id": ObjectId(rule_id)},
            {"$set": updates},
        )
        
        return result.modified_count > 0
    
    async def delete_rule(self, rule_id: str) -> bool:
        """删除规则"""
        from bson import ObjectId
        
        db = await self._get_db()
        
        result = await db[self.COLLECTION].delete_one({"_id": ObjectId(rule_id)})
        
        return result.deleted_count > 0
    
    async def get_rules(
        self,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        enabled_only: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        获取规则列表
        
        Args:
            category: 规则分类
            tags: 标签过滤
            enabled_only: 只返回启用的规则
        
        Returns:
            规则列表
        """
        db = await self._get_db()
        
        query = {}
        if category:
            query["category"] = category
        if tags:
            query["tags"] = {"$all": tags}
        if enabled_only:
            query["enabled"] = True
        
        cursor = db[self.COLLECTION].find(query).sort("priority", -1)
        rules = await cursor.to_list(None)
        
        # 转换 ObjectId
        for rule in rules:
            rule["_id"] = str(rule["_id"])
        
        return rules
    
    async def search_rules(
        self,
        keyword: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        搜索规则
        
        Args:
            keyword: 关键词
            limit: 返回数量
        
        Returns:
            匹配的规则列表
        """
        db = await self._get_db()
        
        query = {
            "$or": [
                {"name": {"$regex": keyword, "$options": "i"}},
                {"content": {"$regex": keyword, "$options": "i"}},
                {"tags": {"$regex": keyword, "$options": "i"}},
            ],
            "enabled": True,
        }
        
        cursor = db[self.COLLECTION].find(query).limit(limit)
        rules = await cursor.to_list(limit)
        
        for rule in rules:
            rule["_id"] = str(rule["_id"])
        
        return rules
    
    async def init_default_rules(self) -> int:
        """
        初始化默认规则
        
        Returns:
            添加的规则数量
        """
        default_rules = [
            # 涨停规则
            {
                "category": "涨停规则",
                "name": "首板数量判断",
                "content": "首板>60为热点，40-60为正常，<30为冷淡",
                "conditions": {
                    "hot": {"first_board": {"$gt": 60}},
                    "normal": {"first_board": {"$gte": 40, "$lte": 60}},
                    "cold": {"first_board": {"$lt": 30}},
                },
                "priority": 10,
                "tags": ["首板", "赚钱效应"],
            },
            {
                "category": "涨停规则",
                "name": "炸板率判断",
                "content": "炸板率<20%为良好，20-35%为正常，>35%为较差",
                "conditions": {
                    "good": {"broken_rate": {"$lt": 20}},
                    "normal": {"broken_rate": {"$gte": 20, "$lte": 35}},
                    "bad": {"broken_rate": {"$gt": 35}},
                },
                "priority": 9,
                "tags": ["炸板", "赚钱效应"],
            },
            {
                "category": "涨停规则",
                "name": "连板高度预警",
                "content": "5板以下安全，7板预警，10板以上危险",
                "conditions": {
                    "safe": {"max_step": {"$lte": 5}},
                    "warning": {"max_step": {"$gt": 5, "$lte": 7}},
                    "danger": {"max_step": {"$gt": 10}},
                },
                "priority": 8,
                "tags": ["连板", "空间"],
            },
            # 板块规则
            {
                "category": "板块规则",
                "name": "主线板块判断",
                "content": "涨幅>3%且涨停家数>5为强势主线",
                "conditions": {
                    "main_line": {
                        "pct_change": {"$gt": 3},
                        "limit_up_count": {"$gt": 5},
                    },
                },
                "priority": 10,
                "tags": ["主线", "板块强度"],
            },
            {
                "category": "板块规则",
                "name": "板块轮动信号",
                "content": "前日弱势板块涨幅突然进入前3，可能是新主线",
                "priority": 8,
                "tags": ["轮动", "切换"],
            },
            # 情绪规则
            {
                "category": "情绪规则",
                "name": "冰点特征",
                "content": "首板<20，炸板率>50%，连板高度断层",
                "conditions": {
                    "first_board": {"$lt": 20},
                    "broken_rate": {"$gt": 50},
                },
                "priority": 10,
                "tags": ["冰点", "抄底"],
            },
            {
                "category": "情绪规则",
                "name": "高潮特征",
                "content": "首板>60，连板高度5板以上，赚钱效应好",
                "conditions": {
                    "first_board": {"$gt": 60},
                    "max_step": {"$gte": 5},
                },
                "priority": 10,
                "tags": ["高潮", "注意风险"],
            },
            # 风险规则
            {
                "category": "风险规则",
                "name": "高位股回避",
                "content": "情绪退潮期，回避5板以上高位股",
                "priority": 10,
                "tags": ["风险", "高位"],
            },
            {
                "category": "风险规则",
                "name": "跟风股回避",
                "content": "非主线板块的跟风涨停，风险大于机会",
                "priority": 9,
                "tags": ["风险", "跟风"],
            },
            # 联动规则
            {
                "category": "联动规则",
                "name": "龙一识别",
                "content": "板块内最先涨停，辨识度最高",
                "priority": 10,
                "tags": ["龙头", "龙一"],
            },
            {
                "category": "联动规则",
                "name": "中军识别",
                "content": "板块内市值>200亿的大票，走势稳健",
                "conditions": {
                    "market_cap": {"$gt": 200},
                },
                "priority": 9,
                "tags": ["中军", "大票"],
            },
        ]
        
        db = await self._get_db()
        
        # 清空现有规则
        await db[self.COLLECTION].delete_many({})
        
        # 添加默认规则
        for rule in default_rules:
            rule["enabled"] = True
            rule["created_at"] = datetime.now(timezone.utc)
            rule["updated_at"] = datetime.now(timezone.utc)
        
        result = await db[self.COLLECTION].insert_many(default_rules)
        
        # 创建索引
        await db[self.COLLECTION].create_index("category")
        await db[self.COLLECTION].create_index("tags")
        await db[self.COLLECTION].create_index([("category", 1), ("priority", -1)])
        
        self.logger.info(f"Initialized {len(result.inserted_ids)} default rules")
        
        return len(result.inserted_ids)
