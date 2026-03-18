"""
新闻数据生命周期管理

分层存储策略:
- Hot:  完整数据，用于实时查询和处理
- Warm: 压缩数据，只保留关键字段
- Cold: 删除或归档

不同类型新闻有不同的保留周期。
"""

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

from .types import NewsCategory, NewsSource


class DataTier(str, Enum):
    """数据层级"""
    HOT = "hot"    # 完整数据
    WARM = "warm"  # 压缩数据
    COLD = "cold"  # 归档/删除


@dataclass
class RetentionConfig:
    """保留配置"""
    hot_days: int      # 热数据保留天数
    warm_days: int     # 温数据保留天数
    cold_days: int     # 冷数据保留天数 (0=删除)
    
    def get_tier(self, age_days: int) -> DataTier:
        """根据数据年龄获取层级"""
        if age_days <= self.hot_days:
            return DataTier.HOT
        elif age_days <= self.hot_days + self.warm_days:
            return DataTier.WARM
        else:
            return DataTier.COLD


# 按新闻分类的保留策略
RETENTION_POLICIES: Dict[str, RetentionConfig] = {
    # 财经快讯 - 时效性强
    NewsCategory.FINANCE_FLASH.value: RetentionConfig(
        hot_days=1,
        warm_days=6,
        cold_days=0,  # 7天后删除
    ),
    
    # 财经文章 - 有分析价值
    NewsCategory.FINANCE_ARTICLE.value: RetentionConfig(
        hot_days=7,
        warm_days=23,
        cold_days=60,  # 90天后删除
    ),
    
    # 研究报告 - 长期参考
    NewsCategory.FINANCE_REPORT.value: RetentionConfig(
        hot_days=30,
        warm_days=60,
        cold_days=275,  # 365天后删除
    ),
    
    # 政策发布 - 长期保存
    NewsCategory.POLICY_RELEASE.value: RetentionConfig(
        hot_days=30,
        warm_days=150,
        cold_days=185,  # 365天后删除
    ),
    
    # 政策解读
    NewsCategory.POLICY_INTERPRET.value: RetentionConfig(
        hot_days=14,
        warm_days=46,
        cold_days=30,  # 90天后删除
    ),
    
    # 通知公告
    NewsCategory.POLICY_NOTICE.value: RetentionConfig(
        hot_days=7,
        warm_days=23,
        cold_days=60,
    ),
    
    # 行业标准 - 长期保存
    NewsCategory.POLICY_STANDARD.value: RetentionConfig(
        hot_days=30,
        warm_days=150,
        cold_days=185,
    ),
    
    # 国际大事件 - 中期保存（地缘政治等）
    NewsCategory.INTERNATIONAL.value: RetentionConfig(
        hot_days=7,
        warm_days=23,
        cold_days=30,  # 60天后删除
    ),
    
    # 国际经济 - 较长保存（美联储、汇率等对A股有影响）
    NewsCategory.INTL_ECONOMY.value: RetentionConfig(
        hot_days=14,
        warm_days=46,
        cold_days=30,  # 90天后删除
    ),
    
    # 国际大宗商品 - 中期保存（油价、金价等）
    NewsCategory.INTL_COMMODITY.value: RetentionConfig(
        hot_days=7,
        warm_days=23,
        cold_days=30,  # 60天后删除
    ),
    
    # 公司公告 - 较长保存
    NewsCategory.COMPANY_ANNOUNCE.value: RetentionConfig(
        hot_days=14,
        warm_days=76,
        cold_days=90,  # 180天后删除
    ),
    
    # 公司新闻
    NewsCategory.COMPANY_NEWS.value: RetentionConfig(
        hot_days=7,
        warm_days=23,
        cold_days=30,
    ),
    
    # 行业新闻
    NewsCategory.INDUSTRY_NEWS.value: RetentionConfig(
        hot_days=3,
        warm_days=11,
        cold_days=16,  # 30天后删除
    ),
    
    # 行业分析
    NewsCategory.INDUSTRY_ANALYSIS.value: RetentionConfig(
        hot_days=7,
        warm_days=23,
        cold_days=60,
    ),
    
    # 一般新闻 - 默认策略
    NewsCategory.GENERAL.value: RetentionConfig(
        hot_days=3,
        warm_days=11,
        cold_days=16,
    ),
}

# 默认策略
DEFAULT_RETENTION = RetentionConfig(
    hot_days=3,
    warm_days=11,
    cold_days=16,
)

# 按源优先级的保留天数（默认值）
DEFAULT_PRIORITY_RETENTION = {
    5: 90,  # P1_OFFICIAL: 90天（政策类）
    4: 90,  # P2_REGULATOR: 90天（政策类）
    3: 60,  # P3_PRO_MEDIA: 60天
    2: 14,  # P4_GENERAL_MEDIA: 14天
    1: 7,   # P5_COMMUNITY: 7天
}

# 按新闻类别的保留天数（覆盖优先级配置）
DEFAULT_CATEGORY_RETENTION = {
    # 政策类 - 长期保存
    "policy_release": 90,
    "policy_interpret": 60,
    "policy_notice": 60,
    "policy_standard": 90,
    # 财经类
    "finance_flash": 7,
    "finance_article": 60,
    "finance_report": 90,
    # 公司类
    "company_announce": 60,
    "company_news": 30,
    # 行业类
    "industry_news": 14,
    "industry_analysis": 60,
    # 默认
    "general": 14,
}

# Warm 阶段保留的字段
WARM_FIELDS = [
    "_id", "id", "title", "summary", "url", "source", "category",
    "publish_time", "collect_time", "ts_codes", "tags",
    "content_hash", "title_hash",
    "event_id", "is_primary", "clustered_at",
]


@dataclass
class LifecycleResult:
    """生命周期处理结果"""
    total_processed: int = 0
    compressed: int = 0       # Hot → Warm
    deleted: int = 0          # Cold 删除
    archived: int = 0         # Cold 归档
    errors: List[str] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class NewsLifecycleManager:
    """
    新闻生命周期管理器
    
    定期执行:
    1. Hot → Warm: 压缩旧数据 (删除 content 等大字段)
    2. Warm → Cold: 删除或归档过期数据
    3. 同步清理 Milvus 中的过期向量
    
    Example:
        manager = NewsLifecycleManager()
        result = await manager.process_lifecycle(trace_id="xxx")
    """
    
    def __init__(self):
        self.logger = logging.getLogger("src.collector.NewsLifecycleManager")
        self._mongo_manager = None
        self._milvus_manager = None
    
    async def _get_mongo(self):
        if self._mongo_manager is None:
            from core.managers import mongo_manager
            if not mongo_manager.is_initialized:
                await mongo_manager.initialize()
            self._mongo_manager = mongo_manager
        return self._mongo_manager
    
    async def _get_milvus(self):
        if self._milvus_manager is None:
            from core.managers import milvus_manager
            if not milvus_manager.is_initialized:
                await milvus_manager.initialize()
            self._milvus_manager = milvus_manager
        return self._milvus_manager
    
    def _get_retention(self, category: str) -> RetentionConfig:
        """获取保留策略"""
        return RETENTION_POLICIES.get(category, DEFAULT_RETENTION)
    
    async def process_lifecycle(
        self,
        batch_size: int = 500,
        trace_id: Optional[str] = None,
    ) -> LifecycleResult:
        """
        处理数据生命周期
        
        分层存储策略：
        1. 按分类压缩（Hot → Warm）
        2. 按新闻类别删除（政策类90d，财经类60d，快讯7d等）
        3. 按源优先级删除（P1/P2:90d, P3:60d, P4:14d, P5:7d）
        4. 清理低价值事件（7天）
        5. 清理过期事件（90天）
        """
        result = LifecycleResult()
        
        self.logger.info(f"[{trace_id}] Starting lifecycle processing...")
        
        # 1. 处理 Hot → Warm (压缩)
        compress_result = await self._process_compress(batch_size, trace_id)
        result.compressed = compress_result
        result.total_processed += compress_result
        
        # 2. 按新闻类别删除（优先级最高）
        delete_by_cat = await self._delete_by_category(batch_size, trace_id)
        result.deleted = delete_by_cat
        result.total_processed += delete_by_cat
        
        # 3. 按源优先级删除（处理未被类别规则覆盖的新闻）
        delete_by_priority = await self._delete_by_priority(batch_size, trace_id)
        result.deleted += delete_by_priority
        result.total_processed += delete_by_priority
        
        # 4. 清理过期事件
        events_deleted = await self._delete_old_events(trace_id)
        if events_deleted > 0:
            self.logger.debug(f"[{trace_id}] Deleted {events_deleted} old events")
        
        # 5. 清理 Milvus 中的孤儿向量
        await self._cleanup_milvus_orphans(trace_id)
        
        self.logger.info(
            f"[{trace_id}] Lifecycle done: "
            f"compressed={result.compressed}, deleted={result.deleted} "
            f"(by_category={delete_by_cat}, by_priority={delete_by_priority})"
        )
        
        return result
    
    async def _process_compress(
        self,
        batch_size: int,
        trace_id: Optional[str] = None,
    ) -> int:
        """
        压缩 Hot → Warm 数据
        
        删除大字段 (content, vector, extra)，只保留关键字段。
        """
        mongo = await self._get_mongo()
        compressed_count = 0
        
        for category, config in RETENTION_POLICIES.items():
            hot_cutoff = datetime.utcnow() - timedelta(days=config.hot_days)
            warm_cutoff = datetime.utcnow() - timedelta(
                days=config.hot_days + config.warm_days
            )
            
            # 查找需要压缩的数据 (超过 hot 但未超过 warm+cold)
            query = {
                "category": category,
                "collect_time": {
                    "$lt": hot_cutoff,
                    "$gte": warm_cutoff,
                },
                "data_tier": {"$ne": DataTier.WARM.value},  # 未压缩的
            }
            
            try:
                # 批量更新：删除大字段，标记为 WARM
                modified_count = await mongo.update_many(
                    "news",
                    query,
                    {
                        "$unset": {
                            "content": "",
                            "vector": "",
                            "extra": "",
                        },
                        "$set": {
                            "data_tier": DataTier.WARM.value,
                            "compressed_at": datetime.utcnow(),
                        }
                    }
                )
                
                if modified_count > 0:
                    compressed_count += modified_count
                    self.logger.debug(
                        f"[{trace_id}] Compressed {modified_count} "
                        f"news in category '{category}'"
                    )
                    
            except Exception as e:
                self.logger.error(f"[{trace_id}] Compress error for {category}: {e}")
        
        return compressed_count
    
    async def _process_delete(
        self,
        batch_size: int,
        trace_id: Optional[str] = None,
    ) -> int:
        """
        删除 Cold 数据
        """
        mongo = await self._get_mongo()
        deleted_count = 0
        
        for category, config in RETENTION_POLICIES.items():
            if config.cold_days == 0:
                # cold_days=0 表示 warm 之后直接删除
                total_days = config.hot_days + config.warm_days
            else:
                total_days = config.hot_days + config.warm_days + config.cold_days
            
            cutoff = datetime.utcnow() - timedelta(days=total_days)
            
            query = {
                "category": category,
                "collect_time": {"$lt": cutoff},
            }
            
            try:
                # 先获取要删除的 ID (用于清理 Milvus)
                to_delete = await mongo.find_many(
                    "news",
                    query,
                    projection={"_id": 1},
                    limit=batch_size,
                )
                
                ids_to_delete = [doc["_id"] for doc in to_delete]
                
                if ids_to_delete:
                    # 删除 MongoDB
                    count = await mongo.delete_many(
                        "news",
                        {"_id": {"$in": ids_to_delete}}
                    )
                    
                    deleted_count += count
                    
                    # 删除 Milvus 中对应的向量
                    await self._delete_milvus_vectors(ids_to_delete, trace_id)
                    
                    self.logger.debug(
                        f"[{trace_id}] Deleted {count} "
                        f"news in category '{category}'"
                    )
                    
            except Exception as e:
                self.logger.error(f"[{trace_id}] Delete error for {category}: {e}")
        
        # 同步删除过期的 news_events
        events_deleted = await self._delete_old_events(trace_id)
        if events_deleted > 0:
            self.logger.debug(f"[{trace_id}] Deleted {events_deleted} old events")
        
        return deleted_count
    
    async def _delete_milvus_vectors(
        self,
        ids: List[str],
        trace_id: Optional[str] = None,
    ):
        """删除 Milvus 中的向量"""
        if not ids:
            return
        
        milvus = await self._get_milvus()
        
        try:
            await milvus.delete(
                collection="semantic_memory",
                ids=ids,
            )
        except Exception as e:
            self.logger.error(f"[{trace_id}] Delete Milvus vectors error: {e}")
    
    async def _delete_old_events(
        self,
        trace_id: Optional[str] = None,
    ) -> int:
        """删除过期的事件"""
        from src.config import config_manager
        
        mongo = await self._get_mongo()
        deleted_count = 0
        
        # 从配置读取保留天数
        events_retention = config_manager.get("collector.lifecycle.events_retention_days", 90)
        low_value_retention = config_manager.get("collector.lifecycle.low_value_events_retention_days", 7)
        
        try:
            # 删除过期的正常事件
            cutoff = datetime.utcnow() - timedelta(days=events_retention)
            count = await mongo.delete_many(
                "news_events",
                {
                    "last_update_time": {"$lt": cutoff},
                    "$or": [
                        {"is_low_value": {"$exists": False}},
                        {"is_low_value": False},
                    ],
                }
            )
            deleted_count += count
            
            # 低价值事件更快删除
            low_value_cutoff = datetime.utcnow() - timedelta(days=low_value_retention)
            low_count = await mongo.delete_many(
                "news_events",
                {
                    "filtered_at": {"$lt": low_value_cutoff},
                    "is_low_value": True,
                }
            )
            deleted_count += low_count
            
            if low_count > 0:
                self.logger.debug(f"[{trace_id}] Deleted {low_count} low-value events")
            
            return deleted_count
        except Exception as e:
            self.logger.error(f"[{trace_id}] Delete old events error: {e}")
            return 0
    
    async def _delete_by_priority(
        self,
        batch_size: int,
        trace_id: Optional[str] = None,
    ) -> int:
        """
        按源优先级删除过期新闻
        
        P1/P2: 90天（政策类）
        P3: 60天
        P4: 14天
        P5: 7天
        """
        from src.config import config_manager
        
        mongo = await self._get_mongo()
        deleted_count = 0
        
        # 从配置读取按优先级的保留天数
        retention_config = config_manager.get("collector.lifecycle.news_retention_by_priority", {})
        
        priority_map = {
            "P1_OFFICIAL": 5,
            "P2_REGULATOR": 4,
            "P3_PRO_MEDIA": 3,
            "P4_GENERAL_MEDIA": 2,
            "P5_COMMUNITY": 1,
        }
        
        # 构建按优先级的保留天数映射
        retention_by_priority = {}
        for name, days in retention_config.items():
            priority = priority_map.get(name)
            if priority:
                retention_by_priority[priority] = days
        
        # 使用默认值补充
        for p, default_days in DEFAULT_PRIORITY_RETENTION.items():
            if p not in retention_by_priority:
                retention_by_priority[p] = default_days
        
        # 按优先级删除（排除按类别管理的新闻）
        for priority, days in retention_by_priority.items():
            cutoff = datetime.utcnow() - timedelta(days=days)
            
            try:
                # 先获取要删除的 ID（排除有特定类别的新闻，它们由 _delete_by_category 处理）
                to_delete = await mongo.find_many(
                    "news",
                    {
                        "source_priority": priority,
                        "collect_time": {"$lt": cutoff},
                        "category": {"$nin": list(DEFAULT_CATEGORY_RETENTION.keys())},
                    },
                    projection={"_id": 1},
                    limit=batch_size,
                )
                
                ids_to_delete = [doc["_id"] for doc in to_delete]
                
                if ids_to_delete:
                    count = await mongo.delete_many(
                        "news",
                        {"_id": {"$in": ids_to_delete}}
                    )
                    deleted_count += count
                    
                    # 同步删除 Milvus 向量
                    await self._delete_milvus_vectors(ids_to_delete, trace_id)
                    
                    self.logger.debug(
                        f"[{trace_id}] Deleted {count} P{6-priority} news (>{days}d)"
                    )
                    
            except Exception as e:
                self.logger.error(f"[{trace_id}] Delete P{6-priority} news error: {e}")
        
        return deleted_count
    
    async def _delete_by_category(
        self,
        batch_size: int,
        trace_id: Optional[str] = None,
    ) -> int:
        """
        按新闻类别删除过期新闻
        
        政策类: 60-90天
        财经类: 7-90天
        公司类: 30-60天
        行业类: 14-60天
        """
        from src.config import config_manager
        
        mongo = await self._get_mongo()
        deleted_count = 0
        
        # 从配置读取按类别的保留天数
        retention_config = config_manager.get(
            "collector.lifecycle.news_retention_by_category", {}
        )
        
        # 使用默认值补充
        retention_by_category = {**DEFAULT_CATEGORY_RETENTION}
        retention_by_category.update(retention_config)
        
        # 按类别删除
        for category, days in retention_by_category.items():
            cutoff = datetime.utcnow() - timedelta(days=days)
            
            try:
                to_delete = await mongo.find_many(
                    "news",
                    {
                        "category": category,
                        "collect_time": {"$lt": cutoff},
                    },
                    projection={"_id": 1},
                    limit=batch_size,
                )
                
                ids_to_delete = [doc["_id"] for doc in to_delete]
                
                if ids_to_delete:
                    count = await mongo.delete_many(
                        "news",
                        {"_id": {"$in": ids_to_delete}}
                    )
                    deleted_count += count
                    
                    await self._delete_milvus_vectors(ids_to_delete, trace_id)
                    
                    self.logger.debug(
                        f"[{trace_id}] Deleted {count} '{category}' news (>{days}d)"
                    )
                    
            except Exception as e:
                self.logger.error(f"[{trace_id}] Delete '{category}' news error: {e}")
        
        return deleted_count
    
    async def _cleanup_milvus_orphans(
        self,
        trace_id: Optional[str] = None,
    ):
        """
        清理 Milvus 中的孤儿向量
        
        检查 Milvus 中的向量是否在 MongoDB 中存在，
        删除不存在的向量。
        """
        # 这个操作比较耗时，可以考虑低频执行或单独任务
        pass
    
    async def get_stats(
        self,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """获取数据统计"""
        mongo = await self._get_mongo()
        
        stats = {
            "by_category": {},
            "by_tier": {
                DataTier.HOT.value: 0,
                DataTier.WARM.value: 0,
            },
            "total": 0,
        }
        
        try:
            # 按分类统计
            pipeline = [
                {"$group": {
                    "_id": "$category",
                    "count": {"$sum": 1},
                }}
            ]
            
            async for doc in mongo.db["news"].aggregate(pipeline):
                category = doc["_id"]
                count = doc["count"]
                stats["by_category"][category] = count
                stats["total"] += count
            
            # 按层级统计
            tier_pipeline = [
                {"$group": {
                    "_id": "$data_tier",
                    "count": {"$sum": 1},
                }}
            ]
            
            async for doc in mongo.db["news"].aggregate(tier_pipeline):
                tier = doc["_id"] or DataTier.HOT.value
                stats["by_tier"][tier] = doc["count"]
                
        except Exception as e:
            self.logger.error(f"[{trace_id}] Get stats error: {e}")
        
        return stats
    
    @staticmethod
    def get_retention_policies() -> Dict[str, Dict[str, int]]:
        """获取所有保留策略"""
        return {
            category: {
                "hot_days": config.hot_days,
                "warm_days": config.warm_days,
                "cold_days": config.cold_days,
                "total_days": config.hot_days + config.warm_days + config.cold_days,
            }
            for category, config in RETENTION_POLICIES.items()
        }
