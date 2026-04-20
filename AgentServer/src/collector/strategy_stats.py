"""
策略迭代统计

核心指标：
1. 事件命中率 = 报告使用事件数 / 聚类事件数
2. 去重效率 = 各层去重命中比例
3. 聚类准确率 = 正确聚类数 / 总聚类数

统计周期：每周
用途：指导规则迭代优化
"""

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, field



logger = logging.getLogger(__name__)


@dataclass
class WeeklyStats:
    """周统计数据"""
    week_start: datetime
    week_end: datetime
    
    # 采集
    total_fetched: int = 0
    total_new: int = 0
    by_source: Dict[str, int] = field(default_factory=dict)
    by_priority: Dict[int, int] = field(default_factory=dict)
    
    # 去重
    dedup_redis_hit: int = 0
    dedup_memory_hit: int = 0
    dedup_fingerprint_hit: int = 0
    dedup_mongo_hit: int = 0
    
    # 聚类
    events_created: int = 0
    events_merged: int = 0
    
    # 过滤
    events_kept: int = 0
    events_filtered: int = 0
    filter_reasons: Dict[str, int] = field(default_factory=dict)
    
    # 报告
    events_in_report: int = 0
    reports_generated: int = 0
    
    @property
    def event_hit_rate(self) -> float:
        """事件命中率（进入报告的比例）"""
        if self.events_kept == 0:
            return 0.0
        return self.events_in_report / self.events_kept
    
    @property
    def event_valid_rate(self) -> float:
        """事件有效率（非低价值比例）"""
        total = self.events_kept + self.events_filtered
        if total == 0:
            return 1.0
        return self.events_kept / total
    
    @property
    def dedup_efficiency(self) -> Dict[str, float]:
        """去重效率（各层命中比例）"""
        total_hits = (
            self.dedup_redis_hit + 
            self.dedup_memory_hit + 
            self.dedup_fingerprint_hit + 
            self.dedup_mongo_hit
        )
        if total_hits == 0:
            return {"redis": 0, "memory": 0, "fingerprint": 0, "mongo": 0}
        
        return {
            "redis": self.dedup_redis_hit / total_hits,
            "memory": self.dedup_memory_hit / total_hits,
            "fingerprint": self.dedup_fingerprint_hit / total_hits,
            "mongo": self.dedup_mongo_hit / total_hits,
        }
    
    @property
    def cluster_merge_rate(self) -> float:
        """聚类合并率"""
        total = self.events_created + self.events_merged
        if total == 0:
            return 0.0
        return self.events_merged / total


@dataclass
class StrategyRecommendation:
    """策略优化建议"""
    category: str  # dedup / cluster / filter / llm
    priority: str  # high / medium / low
    current_value: float
    target_value: float
    recommendation: str
    action: str


class StrategyStatsManager:
    """
    策略迭代统计管理器
    
    功能：
    1. 每周统计事件命中率
    2. 分析去重/聚类/过滤效果
    3. 生成策略优化建议
    
    使用流程：
    1. 每周末生成周统计报告
    2. 分析各环节指标
    3. 输出优化建议
    4. 人工确认后调整配置
    
    Example:
        manager = StrategyStatsManager()
        
        # 生成周报
        stats = await manager.generate_weekly_stats()
        
        # 获取优化建议
        recommendations = await manager.get_recommendations()
    """
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.StrategyStatsManager")
        self._mongo_manager = None
    
    async def _get_mongo(self):
        if self._mongo_manager is None:
            from core.managers import mongo_manager
            if not mongo_manager.is_initialized:
                await mongo_manager.initialize()
            self._mongo_manager = mongo_manager
        return self._mongo_manager
    
    async def generate_weekly_stats(
        self,
        week_offset: int = 0,
        trace_id: Optional[str] = None,
    ) -> WeeklyStats:
        """
        生成周统计
        
        Args:
            week_offset: 周偏移量，0=本周，-1=上周
            trace_id: 追踪ID
            
        Returns:
            WeeklyStats
        """
        mongo = await self._get_mongo()
        
        # 计算周时间范围
        today = datetime.utcnow().date()
        week_start = today - timedelta(days=today.weekday() + 7 * (-week_offset))
        week_end = week_start + timedelta(days=7)
        
        week_start_dt = datetime.combine(week_start, datetime.min.time())
        week_end_dt = datetime.combine(week_end, datetime.min.time())
        
        stats = WeeklyStats(
            week_start=week_start_dt,
            week_end=week_end_dt,
        )
        
        self.logger.info(f"[{trace_id}] Generating weekly stats: {week_start} ~ {week_end}")
        
        # 1. 采集统计
        await self._collect_fetch_stats(mongo, stats, week_start_dt, week_end_dt)
        
        # 2. 去重统计（从 metrics 表聚合）
        await self._collect_dedup_stats(mongo, stats, week_start_dt, week_end_dt)
        
        # 3. 聚类统计
        await self._collect_cluster_stats(mongo, stats, week_start_dt, week_end_dt)
        
        # 4. 过滤统计
        await self._collect_filter_stats(mongo, stats, week_start_dt, week_end_dt)
        
        # 5. 报告统计
        await self._collect_report_stats(mongo, stats, week_start_dt, week_end_dt)
        
        # 持久化周统计
        await self._save_weekly_stats(mongo, stats, trace_id)
        
        self.logger.info(
            f"[{trace_id}] Weekly stats: "
            f"fetched={stats.total_fetched}, new={stats.total_new}, "
            f"events_kept={stats.events_kept}, events_in_report={stats.events_in_report}, "
            f"hit_rate={stats.event_hit_rate:.1%}"
        )
        
        return stats
    
    async def _collect_fetch_stats(
        self,
        mongo,
        stats: WeeklyStats,
        start: datetime,
        end: datetime,
    ):
        """采集统计"""
        # 按来源统计
        pipeline = [
            {"$match": {"collect_time": {"$gte": start, "$lt": end}}},
            {"$group": {
                "_id": {"source": "$source", "priority": "$source_priority"},
                "count": {"$sum": 1},
            }},
        ]
        
        async for doc in mongo.db["news"].aggregate(pipeline):
            source = doc["_id"].get("source", "unknown")
            priority = doc["_id"].get("priority", 2)
            count = doc["count"]
            
            stats.total_fetched += count
            stats.by_source[source] = stats.by_source.get(source, 0) + count
            stats.by_priority[priority] = stats.by_priority.get(priority, 0) + count
        
        # 新增数量（未聚类的）
        stats.total_new = await mongo.count(
            "news",
            {"collect_time": {"$gte": start, "$lt": end}},
        )
    
    async def _collect_dedup_stats(
        self,
        mongo,
        stats: WeeklyStats,
        start: datetime,
        end: datetime,
    ):
        """去重统计"""
        # 从 metrics 表聚合
        pipeline = [
            {"$match": {"_created_at": {"$gte": start, "$lt": end}}},
            {"$group": {
                "_id": None,
                "redis_hit": {"$sum": "$collector.dedup_by_layer.redis"},
                "memory_hit": {"$sum": "$collector.dedup_by_layer.memory"},
                "fingerprint_hit": {"$sum": "$collector.dedup_by_layer.fingerprint"},
                "mongo_hit": {"$sum": "$collector.dedup_by_layer.mongo"},
            }},
        ]
        
        async for doc in mongo.db["collector_metrics"].aggregate(pipeline):
            stats.dedup_redis_hit = doc.get("redis_hit", 0) or 0
            stats.dedup_memory_hit = doc.get("memory_hit", 0) or 0
            stats.dedup_fingerprint_hit = doc.get("fingerprint_hit", 0) or 0
            stats.dedup_mongo_hit = doc.get("mongo_hit", 0) or 0
    
    async def _collect_cluster_stats(
        self,
        mongo,
        stats: WeeklyStats,
        start: datetime,
        end: datetime,
    ):
        """聚类统计"""
        # 新创建的事件
        stats.events_created = await mongo.count(
            "news_events",
            {"first_report_time": {"$gte": start, "$lt": end}},
        )
        
        # 合并的新闻数（news_count > 1 的事件）
        pipeline = [
            {"$match": {
                "last_update_time": {"$gte": start, "$lt": end},
                "news_count": {"$gt": 1},
            }},
            {"$group": {
                "_id": None,
                "total_merged": {"$sum": {"$subtract": ["$news_count", 1]}},
            }},
        ]
        
        async for doc in mongo.db["news_events"].aggregate(pipeline):
            stats.events_merged = doc.get("total_merged", 0)
    
    async def _collect_filter_stats(
        self,
        mongo,
        stats: WeeklyStats,
        start: datetime,
        end: datetime,
    ):
        """过滤统计"""
        # 保留的事件
        stats.events_kept = await mongo.count(
            "news_events",
            {
                "last_update_time": {"$gte": start, "$lt": end},
                "$or": [
                    {"is_low_value": {"$exists": False}},
                    {"is_low_value": False},
                ],
            },
        )
        
        # 过滤的事件
        stats.events_filtered = await mongo.count(
            "news_events",
            {
                "filtered_at": {"$gte": start, "$lt": end},
                "is_low_value": True,
            },
        )
        
        # 按原因统计
        pipeline = [
            {"$match": {
                "filtered_at": {"$gte": start, "$lt": end},
                "is_low_value": True,
            }},
            {"$group": {
                "_id": "$filter_reason",
                "count": {"$sum": 1},
            }},
        ]
        
        async for doc in mongo.db["news_events"].aggregate(pipeline):
            reason = doc["_id"] or "unknown"
            stats.filter_reasons[reason] = doc["count"]
    
    async def _collect_report_stats(
        self,
        mongo,
        stats: WeeklyStats,
        start: datetime,
        end: datetime,
    ):
        """报告统计"""
        # 生成的报告数
        stats.reports_generated = await mongo.count(
            "reports",
            {"created_at": {"$gte": start, "$lt": end}},
        )
        
        # 报告中使用的事件数（从报告内容中提取）
        pipeline = [
            {"$match": {"created_at": {"$gte": start, "$lt": end}}},
            {"$project": {"event_count": {"$size": {"$ifNull": ["$events", []]}}}},
            {"$group": {"_id": None, "total": {"$sum": "$event_count"}}},
        ]
        
        async for doc in mongo.db["reports"].aggregate(pipeline):
            stats.events_in_report = doc.get("total", 0)
    
    async def _save_weekly_stats(
        self,
        mongo,
        stats: WeeklyStats,
        trace_id: Optional[str] = None,
    ):
        """保存周统计"""
        doc = {
            "week_start": stats.week_start,
            "week_end": stats.week_end,
            "total_fetched": stats.total_fetched,
            "total_new": stats.total_new,
            "by_source": stats.by_source,
            "by_priority": {str(k): v for k, v in stats.by_priority.items()},
            "dedup_redis_hit": stats.dedup_redis_hit,
            "dedup_memory_hit": stats.dedup_memory_hit,
            "dedup_fingerprint_hit": stats.dedup_fingerprint_hit,
            "dedup_mongo_hit": stats.dedup_mongo_hit,
            "dedup_efficiency": stats.dedup_efficiency,
            "events_created": stats.events_created,
            "events_merged": stats.events_merged,
            "cluster_merge_rate": stats.cluster_merge_rate,
            "events_kept": stats.events_kept,
            "events_filtered": stats.events_filtered,
            "filter_reasons": stats.filter_reasons,
            "event_valid_rate": stats.event_valid_rate,
            "events_in_report": stats.events_in_report,
            "reports_generated": stats.reports_generated,
            "event_hit_rate": stats.event_hit_rate,
            "_created_at": datetime.utcnow(),
        }
        
        try:
            # 使用 upsert 避免重复
            await mongo.update_one(
                "strategy_weekly_stats",
                {"week_start": stats.week_start},
                {"$set": doc},
                upsert=True,
            )
        except Exception as e:
            self.logger.error(f"[{trace_id}] Save weekly stats error: {e}")
    
    async def get_recommendations(
        self,
        trace_id: Optional[str] = None,
    ) -> List[StrategyRecommendation]:
        """
        生成策略优化建议
        
        基于最近两周的数据对比，生成优化建议。
        """
        recommendations = []
        
        # 获取最近两周数据
        current_week = await self.generate_weekly_stats(week_offset=0, trace_id=trace_id)
        last_week = await self.get_weekly_stats(week_offset=-1, trace_id=trace_id)
        
        if not last_week:
            self.logger.info(f"[{trace_id}] No last week data for comparison")
            return recommendations
        
        # 1. 事件命中率分析
        if current_week.event_hit_rate < 0.9:
            recommendations.append(StrategyRecommendation(
                category="filter",
                priority="high" if current_week.event_hit_rate < 0.8 else "medium",
                current_value=current_week.event_hit_rate,
                target_value=0.9,
                recommendation=f"事件命中率 {current_week.event_hit_rate:.1%} < 90%",
                action="考虑收紧低价值事件过滤规则，或优化聚类阈值",
            ))
        
        # 2. 去重效率分析
        dedup_eff = current_week.dedup_efficiency
        if dedup_eff.get("mongo", 0) > 0.3:
            recommendations.append(StrategyRecommendation(
                category="dedup",
                priority="medium",
                current_value=dedup_eff["mongo"],
                target_value=0.2,
                recommendation=f"MongoDB 去重占比 {dedup_eff['mongo']:.1%} > 20%",
                action="考虑延长 Redis TTL 或优化指纹提取规则",
            ))
        
        # 3. 聚类合并率分析
        if current_week.cluster_merge_rate < 0.3:
            recommendations.append(StrategyRecommendation(
                category="cluster",
                priority="low",
                current_value=current_week.cluster_merge_rate,
                target_value=0.4,
                recommendation=f"聚类合并率 {current_week.cluster_merge_rate:.1%} < 30%",
                action="考虑降低相似度阈值，提高事件聚合效果",
            ))
        elif current_week.cluster_merge_rate > 0.7:
            recommendations.append(StrategyRecommendation(
                category="cluster",
                priority="medium",
                current_value=current_week.cluster_merge_rate,
                target_value=0.5,
                recommendation=f"聚类合并率 {current_week.cluster_merge_rate:.1%} > 70%（可能误合并）",
                action="考虑提高相似度阈值，减少误合并",
            ))
        
        # 4. 趋势分析（与上周对比）
        hit_rate_change = current_week.event_hit_rate - last_week.event_hit_rate
        if hit_rate_change < -0.1:
            recommendations.append(StrategyRecommendation(
                category="trend",
                priority="high",
                current_value=current_week.event_hit_rate,
                target_value=last_week.event_hit_rate,
                recommendation=f"事件命中率环比下降 {abs(hit_rate_change):.1%}",
                action="检查最近的规则变更，考虑回滚",
            ))
        
        self.logger.info(f"[{trace_id}] Generated {len(recommendations)} recommendations")
        return recommendations
    
    async def get_weekly_stats(
        self,
        week_offset: int = -1,
        trace_id: Optional[str] = None,
    ) -> Optional[WeeklyStats]:
        """获取历史周统计"""
        mongo = await self._get_mongo()
        
        today = datetime.utcnow().date()
        week_start = today - timedelta(days=today.weekday() + 7 * (-week_offset))
        week_start_dt = datetime.combine(week_start, datetime.min.time())
        
        doc = await mongo.find_one(
            "strategy_weekly_stats",
            {"week_start": week_start_dt},
        )
        
        if not doc:
            return None
        
        # 转换回 WeeklyStats
        stats = WeeklyStats(
            week_start=doc["week_start"],
            week_end=doc["week_end"],
            total_fetched=doc.get("total_fetched", 0),
            total_new=doc.get("total_new", 0),
            events_created=doc.get("events_created", 0),
            events_merged=doc.get("events_merged", 0),
            events_kept=doc.get("events_kept", 0),
            events_filtered=doc.get("events_filtered", 0),
            events_in_report=doc.get("events_in_report", 0),
            reports_generated=doc.get("reports_generated", 0),
        )
        
        return stats
    
    async def get_trend_data(
        self,
        weeks: int = 4,
        trace_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取趋势数据"""
        mongo = await self._get_mongo()
        
        docs = await mongo.find_many(
            "strategy_weekly_stats",
            {},
            sort=[("week_start", -1)],
            limit=weeks,
        )
        
        return [
            {
                "week": doc["week_start"].strftime("%Y-%m-%d"),
                "event_hit_rate": doc.get("event_hit_rate", 0),
                "event_valid_rate": doc.get("event_valid_rate", 0),
                "cluster_merge_rate": doc.get("cluster_merge_rate", 0),
                "total_fetched": doc.get("total_fetched", 0),
                "events_in_report": doc.get("events_in_report", 0),
            }
            for doc in reversed(docs)
        ]
