"""
事件聚类引擎

深度去重阶段：使用 LLM 识别相同事件，聚类新闻。

工作流程:
1. 定期扫描未聚类的新闻
2. 使用 LLM 提取事件指纹 (主体 + 动作 + 时间)
3. 基于事件指纹进行聚类
4. 标记重复新闻，保留主新闻
"""

import logging
import hashlib
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum

from pydantic import BaseModel, Field


class EventImportance(str, Enum):
    """事件重要性"""
    HIGH = "high"        # 重大事件
    MEDIUM = "medium"    # 一般事件
    LOW = "low"          # 次要事件


@dataclass
class EventFingerprint:
    """事件指纹"""
    subject: str          # 主体 (公司/行业/政策)
    action: str           # 动作 (发布/涨跌/收购)
    time_ref: str         # 时间参照 (今日/本周/Q1)
    keywords: List[str]   # 关键词
    
    @property
    def fingerprint_hash(self) -> str:
        """生成指纹哈希"""
        text = f"{self.subject}:{self.action}:{self.time_ref}"
        return hashlib.md5(text.encode('utf-8')).hexdigest()
    
    def similarity(self, other: "EventFingerprint") -> float:
        """计算与另一个指纹的相似度"""
        score = 0.0
        
        # 主体相似度 (权重 0.4)
        if self.subject == other.subject:
            score += 0.4
        elif self._fuzzy_match(self.subject, other.subject):
            score += 0.2
        
        # 动作相似度 (权重 0.3)
        if self.action == other.action:
            score += 0.3
        elif self._fuzzy_match(self.action, other.action):
            score += 0.15
        
        # 关键词重叠 (权重 0.3)
        if self.keywords and other.keywords:
            overlap = len(set(self.keywords) & set(other.keywords))
            total = len(set(self.keywords) | set(other.keywords))
            if total > 0:
                score += 0.3 * (overlap / total)
        
        return score
    
    def _fuzzy_match(self, s1: str, s2: str) -> bool:
        """模糊匹配"""
        return s1 in s2 or s2 in s1


class NewsEvent(BaseModel):
    """新闻事件 (聚类后的事件)"""
    id: str = Field(default="")
    
    # 事件信息
    title: str = Field(description="事件标题")
    summary: str = Field(default="", description="事件摘要")
    importance: EventImportance = Field(default=EventImportance.MEDIUM)
    
    # 关联
    category: str = Field(default="general", description="事件分类")
    ts_codes: List[str] = Field(default_factory=list, description="关联股票")
    tags: List[str] = Field(default_factory=list, description="标签")
    
    # 事件指纹
    fingerprint: Optional[Dict[str, Any]] = Field(default=None)
    fingerprint_hash: str = Field(default="")
    
    # 关联新闻
    primary_news_id: str = Field(default="", description="主新闻ID")
    primary_news_priority: int = Field(default=2, description="主新闻源优先级")
    related_news_ids: List[str] = Field(default_factory=list, description="相关新闻ID")
    news_count: int = Field(default=1, description="新闻数量")
    
    # 时间
    event_time: Optional[datetime] = Field(default=None, description="事件发生时间")
    first_report_time: Optional[datetime] = Field(default=None, description="首次报道时间")
    last_update_time: Optional[datetime] = Field(default=None, description="最后更新时间")
    
    # 元数据
    sources: List[str] = Field(default_factory=list, description="来源列表")
    
    # ========== 炒股关键信息 (LLM 批量增强) ==========
    sentiment: Optional[str] = Field(default=None, description="情绪: positive/negative/neutral")
    sentiment_score: float = Field(default=0.0, description="情绪分数 -1.0 ~ 1.0")
    impact_scope: Optional[str] = Field(default=None, description="影响范围: market/sector/stock")
    related_sectors: List[str] = Field(default_factory=list, description="关联板块")
    policy_level: Optional[str] = Field(default=None, description="政策级别: central/ministry/local/company")
    enriched_at: Optional[datetime] = Field(default=None, description="LLM增强时间")
    

@dataclass
class ClusterResult:
    """聚类结果"""
    total_processed: int = 0
    new_events: int = 0
    merged_news: int = 0
    failed: int = 0
    filtered_low_value: int = 0  # 过滤的低价值事件数
    events: List[NewsEvent] = field(default_factory=list)


@dataclass
class FilterResult:
    """过滤结果"""
    kept: List[Dict[str, Any]] = field(default_factory=list)
    filtered: List[Dict[str, Any]] = field(default_factory=list)
    filter_reasons: Dict[str, int] = field(default_factory=dict)  # 各规则过滤数量




class EventClusterEngine:
    """
    事件聚类引擎
    
    两阶段工作:
    1. 提取事件指纹 (LLM)
    2. 基于指纹聚类
    
    Example:
        engine = EventClusterEngine()
        
        # 处理未聚类的新闻
        result = await engine.process_pending_news(trace_id="xxx")
        
        # 单条新闻提取指纹
        fingerprint = await engine.extract_fingerprint(news_item)
    """
    
    def __init__(
        self,
        similarity_threshold: float = 0.7,
        time_window_hours: int = 48,
    ):
        self.similarity_threshold = similarity_threshold
        self.time_window = timedelta(hours=time_window_hours)
        self.logger = logging.getLogger("src.collector.EventClusterEngine")
        
        self._llm_service = None
        self._mongo_manager = None
        self._milvus_manager = None
    
    async def _get_llm_service(self):
        """获取 LLM 服务实例"""
        if self._llm_service is None:
            from src.llm import LLMService
            self._llm_service = LLMService()
            await self._llm_service.initialize()
        return self._llm_service
    
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
    
    async def extract_fingerprint(
        self,
        title: str,
        content: str,
        trace_id: Optional[str] = None,
    ) -> Tuple[Optional[EventFingerprint], Optional[Dict[str, Any]]]:
        """
        使用 LLM 提取事件指纹
        
        使用 LLMService 的模板系统和自动解析功能
        """
        llm = await self._get_llm_service()
        
        try:
            # 打印调试信息
            content_preview = content[:100] if content else "(空)"
            self.logger.debug(
                f"[{trace_id}] extract_fingerprint 输入:\n"
                f"  title: {title[:50]}...\n"
                f"  content: {content_preview}..."
            )
            
            # 使用 event_extract 模板，自动解析 JSON
            result = await llm.invoke_and_parse(
                template_name="event_extract",
                title=title,
                content=content[:1000] if content else "",
            )
            
            if not result:
                self.logger.warning(f"[{trace_id}] LLM returned empty or invalid response")
                return None, None
            
            return EventFingerprint(
                subject=result.get("subject", ""),
                action=result.get("action", ""),
                time_ref=result.get("time_ref", ""),
                keywords=result.get("keywords", []),
            ), result
            
        except Exception as e:
            self.logger.error(f"[{trace_id}] Extract fingerprint error: {e}")
            return None, None
    
    async def find_similar_event(
        self,
        fingerprint: EventFingerprint,
        trace_id: Optional[str] = None,
    ) -> Optional[NewsEvent]:
        """
        查找相似的已有事件
        """
        mongo = await self._get_mongo()
        
        cutoff = datetime.utcnow() - self.time_window
        
        try:
            # 先按指纹哈希精确匹配
            event = await mongo.find_one(
                "news_events",
                {
                    "fingerprint_hash": fingerprint.fingerprint_hash,
                    "last_update_time": {"$gte": cutoff},
                }
            )
            if event:
                return NewsEvent(**event)
            
            # 再按关键词模糊匹配
            events = await mongo.find_many(
                "news_events",
                {
                    "last_update_time": {"$gte": cutoff},
                    "fingerprint.subject": {"$regex": fingerprint.subject, "$options": "i"},
                },
                limit=20,
            )
            
            for event_doc in events:
                existing_fp = EventFingerprint(
                    subject=event_doc.get("fingerprint", {}).get("subject", ""),
                    action=event_doc.get("fingerprint", {}).get("action", ""),
                    time_ref=event_doc.get("fingerprint", {}).get("time_ref", ""),
                    keywords=event_doc.get("fingerprint", {}).get("keywords", []),
                )
                
                if fingerprint.similarity(existing_fp) >= self.similarity_threshold:
                    return NewsEvent(**event_doc)
            
            return None
            
        except Exception as e:
            self.logger.error(f"[{trace_id}] Find similar event error: {e}")
            return None
    
    async def create_or_merge_event(
        self,
        news_id: str,
        news_title: str,
        news_source: str,
        fingerprint: EventFingerprint,
        llm_result: Dict[str, Any],
        news_priority: int = 2,
        trace_id: Optional[str] = None,
    ) -> Tuple[NewsEvent, bool]:
        """
        创建新事件或合并到已有事件
        
        Args:
            news_id: 新闻ID
            news_title: 新闻标题
            news_source: 新闻来源
            fingerprint: 事件指纹
            llm_result: LLM 提取结果
            news_priority: 新闻源优先级 (1-5, 越高越权威)
            trace_id: 追踪ID
            
        Returns:
            (event, is_new)
        """
        mongo = await self._get_mongo()
        
        existing = await self.find_similar_event(fingerprint, trace_id)
        
        if existing:
            # 检查是否需要替换主新闻 (新新闻优先级更高)
            should_replace_primary = news_priority > existing.primary_news_priority
            
            if should_replace_primary:
                # 原主新闻降级为相关新闻
                old_primary_id = existing.primary_news_id
                
                # 更新事件: 替换主新闻
                existing.related_news_ids.append(old_primary_id)
                existing.primary_news_id = news_id
                existing.primary_news_priority = news_priority
                existing.title = news_title  # 使用更权威来源的标题
                existing.news_count += 1
                existing.last_update_time = datetime.utcnow()
                if news_source not in existing.sources:
                    existing.sources.append(news_source)
                
                await mongo.update_one(
                    "news_events",
                    {"id": existing.id},
                    {
                        "$push": {"related_news_ids": old_primary_id},
                        "$inc": {"news_count": 1},
                        "$set": {
                            "primary_news_id": news_id,
                            "primary_news_priority": news_priority,
                            "title": news_title,
                            "last_update_time": datetime.utcnow(),
                        },
                        "$addToSet": {"sources": news_source},
                    }
                )
                
                # 原主新闻降级
                await mongo.update_one(
                    "news",
                    {"id": old_primary_id},
                    {"$set": {"is_primary": False}}
                )
                
                # 新新闻成为主新闻
                await mongo.update_one(
                    "news",
                    {"id": news_id},
                    {
                        "$set": {
                            "event_id": existing.id,
                            "is_primary": True,
                            "clustered_at": datetime.utcnow(),
                        }
                    }
                )
                
                self.logger.info(
                    f"[{trace_id}] Primary news replaced: {old_primary_id} -> {news_id} "
                    f"(priority {existing.primary_news_priority} -> {news_priority})"
                )
                
            else:
                # 普通合并，不替换主新闻
                existing.related_news_ids.append(news_id)
                existing.news_count += 1
                existing.last_update_time = datetime.utcnow()
                if news_source not in existing.sources:
                    existing.sources.append(news_source)
                
                await mongo.update_one(
                    "news_events",
                    {"id": existing.id},
                    {
                        "$push": {"related_news_ids": news_id},
                        "$inc": {"news_count": 1},
                        "$set": {"last_update_time": datetime.utcnow()},
                        "$addToSet": {"sources": news_source},
                    }
                )
                
                # 标记新闻为已聚类
                await mongo.update_one(
                    "news",
                    {"id": news_id},
                    {
                        "$set": {
                            "event_id": existing.id,
                            "is_primary": False,
                            "clustered_at": datetime.utcnow(),
                        }
                    }
                )
            
            return existing, False
        
        # 创建新事件
        event = NewsEvent(
            id=f"evt_{fingerprint.fingerprint_hash[:16]}",
            title=news_title,  # 使用原始新闻标题
            summary=llm_result.get("summary", ""),  # LLM 提取的摘要
            importance=EventImportance(llm_result.get("importance", "medium")),
            category=llm_result.get("category", "general"),
            fingerprint={
                "subject": fingerprint.subject,
                "action": fingerprint.action,
                "time_ref": fingerprint.time_ref,
                "keywords": fingerprint.keywords,
            },
            fingerprint_hash=fingerprint.fingerprint_hash,
            primary_news_id=news_id,
            primary_news_priority=news_priority,
            related_news_ids=[],
            news_count=1,
            first_report_time=datetime.utcnow(),
            last_update_time=datetime.utcnow(),
            sources=[news_source],
        )
        
        await mongo.insert_one("news_events", event.model_dump())
        
        # 标记新闻为主新闻
        await mongo.update_one(
            "news",
            {"id": news_id},
            {
                "$set": {
                    "event_id": event.id,
                    "is_primary": True,
                    "clustered_at": datetime.utcnow(),
                }
            }
        )
        
        # 为主新闻生成向量并入库 Milvus
        await self._generate_and_store_vector(
            news_id=news_id,
            event=event,
            trace_id=trace_id,
        )
        
        return event, True
    
    async def _generate_and_store_vector(
        self,
        news_id: str,
        event: NewsEvent,
        trace_id: Optional[str] = None,
    ):
        """
        为主新闻生成向量并存入 Milvus
        
        只有主新闻才会入向量库，避免语义重复。
        使用 milvus_manager.add_news_vector() 方法，它会自动处理向量生成和存储。
        """
        mongo = await self._get_mongo()
        milvus = await self._get_milvus()
        
        try:
            # 获取新闻详情
            news_doc = await mongo.find_one("news", {"id": news_id})
            if not news_doc:
                return
            
            # 使用 milvus_manager 的 insert_news 方法
            # 它会自动生成向量并存入正确的 collection
            ts_code = event.ts_codes[0] if event.ts_codes else ""
            trade_date = event.first_report_time.strftime("%Y%m%d") if event.first_report_time else datetime.utcnow().strftime("%Y%m%d")
            news_datetime = event.first_report_time.isoformat() if event.first_report_time else ""
            
            vector_id = await milvus.insert_news(
                ts_code=ts_code,
                title=event.title,
                content=news_doc.get("content", "")[:1000],
                trade_date=trade_date,
                news_datetime=news_datetime,
                source=event.sources[0] if event.sources else "unknown",
            )
            
            if vector_id:
                self.logger.debug(f"[{trace_id}] Vector stored for primary news: {news_id}, vector_id={vector_id}")
            else:
                self.logger.warning(f"[{trace_id}] Failed to store vector for {news_id}")
            
        except Exception as e:
            self.logger.error(f"[{trace_id}] Generate vector error: {e}")
    
    async def process_pending_news(
        self,
        batch_size: int = 50,
        trace_id: Optional[str] = None,
        max_concurrent: int = 20,
    ) -> ClusterResult:
        """
        处理待聚类的新闻
        
        扫描未聚类的新闻，提取指纹并聚类。
        使用并行处理加速指纹提取。
        """
        import asyncio
        import time
        
        mongo = await self._get_mongo()
        result = ClusterResult()
        
        # Step 1: 查找待聚类新闻
        t0 = time.time()
        pending_news = await mongo.find_many(
            "news",
            {
                "clustered_at": {"$exists": False},
                "collect_time": {"$gte": datetime.utcnow() - self.time_window},
            },
            limit=batch_size,
            sort=[("collect_time", 1)],
        )
        t1 = time.time()
        self.logger.info(f"[{trace_id}] Step 1 - Query pending news: {len(pending_news)} items, {t1-t0:.2f}s")
        
        result.total_processed = len(pending_news)
        
        if not pending_news:
            return result
        
        # Step 2: 并行提取指纹
        self.logger.info(f"[{trace_id}] Step 2 - Extracting fingerprints (concurrency={max_concurrent})...")
        semaphore = asyncio.Semaphore(max_concurrent)
        extract_count = [0]  # 用列表以便在闭包中修改
        
        async def extract_with_limit(news_doc):
            async with semaphore:
                title = news_doc.get("title", "")
                fingerprint, llm_result = await self.extract_fingerprint(title, content, trace_id)
                extract_count[0] += 1
                if extract_count[0] % 10 == 0:
                    self.logger.info(f"[{trace_id}]   Fingerprint progress: {extract_count[0]}/{len(pending_news)}")
                return news_doc, fingerprint, llm_result
        
        t2 = time.time()
        tasks = [extract_with_limit(doc) for doc in pending_news]
        fingerprint_results = await asyncio.gather(*tasks, return_exceptions=True)
        t3 = time.time()
        self.logger.info(f"[{trace_id}] Step 2 - Fingerprints extracted: {len(fingerprint_results)} items, {t3-t2:.2f}s")
        
        # Step 3: 串行处理聚类
        self.logger.info(f"[{trace_id}] Step 3 - Clustering...")
        cluster_count = 0
        
        for item in fingerprint_results:
            if isinstance(item, Exception):
                result.failed += 1
                continue
            
            news_doc, fingerprint, llm_result = item
            title = news_doc.get("title", "")
            source = news_doc.get("source", "")
            source_priority = news_doc.get("source_priority", 2)  # 获取源优先级
            
            cluster_count += 1
            if cluster_count % 10 == 0:
                self.logger.info(f"[{trace_id}]   Clustering progress: {cluster_count}/{len(fingerprint_results)}")
            
            if not fingerprint:
                self.logger.warning(f"[{trace_id}] Failed to extract fingerprint: {news_id}")
                continue
            
            # 创建或合并事件 (传递源优先级)
            event, is_new = await self.create_or_merge_event(
                news_id=news_id,
                news_title=title,
                news_source=source,
                fingerprint=fingerprint,
                llm_result=llm_result or {},
                news_priority=source_priority,
                trace_id=trace_id,
            )
            
            if is_new:
                result.new_events += 1
                result.events.append(event)
            else:
                result.merged_news += 1
        
        t4 = time.time()
        self.logger.info(f"[{trace_id}] Step 3 - Clustering done: {t4-t3:.2f}s")
        
        # Step 4: LLM 增强（自动对新事件进行增强）
        if result.new_events > 0 or result.merged_news > 0:
            self.logger.info(f"[{trace_id}] Step 4 - LLM enrichment for new/updated events...")
            try:
                # 收集新创建的事件 ID（如果有的话）
                new_event_ids = [e.id for e in result.events] if result.events else None
                self.logger.info(f"[{trace_id}] New event IDs to enrich: {new_event_ids}")
                
                enrich_result = await self.enrich_events_batch(
                    event_ids=new_event_ids if new_event_ids else None,  # None 让它自己查询
                    hours=48,  # 扩大时间范围到 48 小时
                    limit=min(result.new_events + 10, 50),
                    trace_id=trace_id,
                )
                self.logger.info(
                    f"[{trace_id}] Step 4 - Enrichment done: "
                    f"full={enrich_result.get('full', 0)}, "
                    f"partial={enrich_result.get('partial', 0)}, "
                    f"rule={enrich_result.get('rule', 0)}"
                )
            except Exception as e:
                self.logger.warning(f"[{trace_id}] Step 4 - Enrichment failed: {e}")
        
        t5 = time.time()
        total_time = t5 - t0
        self.logger.info(
            f"[{trace_id}] Event clustering complete: "
            f"processed={result.total_processed}, new={result.new_events}, merged={result.merged_news}, "
            f"failed={result.failed}, total_time={total_time:.2f}s"
        )
        
        return result
    
    async def get_event_by_id(
        self,
        event_id: str,
        trace_id: Optional[str] = None,
    ) -> Optional[NewsEvent]:
        """获取事件详情"""
        mongo = await self._get_mongo()
        doc = await mongo.find_one("news_events", {"id": event_id})
        if doc:
            return NewsEvent(**doc)
        return None
    
    async def get_recent_events(
        self,
        hours: int = 24,
        importance: Optional[EventImportance] = None,
        category: Optional[str] = None,
        limit: int = 50,
        trace_id: Optional[str] = None,
    ) -> List[NewsEvent]:
        """获取最近的事件"""
        mongo = await self._get_mongo()
        
        query = {
            "last_update_time": {"$gte": datetime.utcnow() - timedelta(hours=hours)}
        }
        
        if importance:
            query["importance"] = importance.value
        if category:
            query["category"] = category
        
        docs = await mongo.find_many(
            "news_events",
            query,
            limit=limit,
            sort=[("news_count", -1), ("last_update_time", -1)],
        )
        
        return [NewsEvent(**doc) for doc in docs]
    
    # ==================== 低价值事件过滤 ====================
    
    async def filter_low_value_events(
        self,
        hours: int = 24,
        trace_id: Optional[str] = None,
    ) -> FilterResult:
        """
        过滤低价值事件
        
        过滤时机：聚类合并后、LLM 增强前
        目标：事件有效率≥80%，减少报告生成噪音
        
        过滤规则：
        1. P4/P5 源且无关联板块的事件
        2. 低优先级 + 仅影响个股 + 无热度的冗余事件
        3. 但保留：优先级≥P3 或 有明确板块 或 热点事件
        
        Args:
            hours: 查询时间范围
            trace_id: 追踪ID
            
        Returns:
            FilterResult: 过滤结果
        """
        from src.config import config_manager
        
        mongo = await self._get_mongo()
        result = FilterResult()
        
        # 检查是否启用过滤
        if not config_manager.get("collector.event_filter.enabled", True):
            self.logger.info(f"[{trace_id}] Event filter disabled")
            return result
        
        # 获取过滤配置
        rules_config = config_manager.get("collector.event_filter.rules", {})
        log_filtered = config_manager.get("collector.event_filter.log_filtered", True)
        
        # 查询未增强的事件
        events = await mongo.find_many(
            "news_events",
            {
                "enriched_at": {"$exists": False},
                "filtered_at": {"$exists": False},  # 未被过滤处理过
                "last_update_time": {"$gte": datetime.utcnow() - timedelta(hours=hours)},
            },
            limit=500,
            sort=[("news_count", -1)],
        )
        
        if not events:
            self.logger.info(f"[{trace_id}] No events to filter")
            return result
        
        self.logger.info(f"[{trace_id}] Filtering {len(events)} events...")
        
        for event in events:
            priority = event.get("primary_news_priority", 2)
            sectors = event.get("related_sectors", [])
            impact_scope = event.get("impact_scope", "stock")
            news_count = event.get("news_count", 1)
            event_id = event.get("id", "")
            title = event.get("title", "")
            
            # 检查是否应该保留（白名单规则）
            keep_config = rules_config.get("always_keep", {})
            should_keep = False
            
            # 优先级 >= P3
            if priority >= keep_config.get("min_priority", 3):
                should_keep = True
            # 或有明确板块
            elif keep_config.get("or_has_sectors", True) and sectors:
                should_keep = True
            # 或热点事件（新闻数 >= 阈值）
            elif news_count >= keep_config.get("or_news_count", 3):
                should_keep = True
            
            if should_keep:
                result.kept.append(event)
                continue
            
            # 检查过滤规则
            filter_reason = None
            
            # 规则1: P4/P5 源且无关联板块
            rule1 = rules_config.get("low_priority_no_sector", {})
            if rule1.get("enabled", True):
                if priority <= rule1.get("max_priority", 2) and not sectors:
                    filter_reason = "low_priority_no_sector"
            
            # 规则2: 低优先级 + 仅影响个股 + 无热度
            if not filter_reason:
                rule2 = rules_config.get("low_value_individual", {})
                if rule2.get("enabled", True):
                    if (priority <= rule2.get("max_priority", 2) and
                        impact_scope == rule2.get("impact_scope", "stock") and
                        news_count < rule2.get("min_news_count", 2)):
                        filter_reason = "low_value_individual"
            
            if filter_reason:
                result.filtered.append(event)
                result.filter_reasons[filter_reason] = result.filter_reasons.get(filter_reason, 0) + 1
                
                if log_filtered:
                    self.logger.debug(
                        f"[{trace_id}] Filtered event: {title[:40]} "
                        f"(priority={priority}, sectors={len(sectors)}, "
                        f"scope={impact_scope}, news={news_count}, reason={filter_reason})"
                    )
                
                # 标记为已过滤
                await mongo.update_one(
                    "news_events",
                    {"id": event_id},
                    {"$set": {
                        "filtered_at": datetime.utcnow(),
                        "filter_reason": filter_reason,
                        "is_low_value": True,
                    }}
                )
            else:
                result.kept.append(event)
        
        self.logger.info(
            f"[{trace_id}] Event filter done: kept={len(result.kept)}, "
            f"filtered={len(result.filtered)}, reasons={result.filter_reasons}"
        )
        
        return result
    
    async def get_filtered_events(
        self,
        hours: int = 24,
        limit: int = 100,
        trace_id: Optional[str] = None,
    ) -> List[NewsEvent]:
        """获取被过滤的低价值事件列表"""
        mongo = await self._get_mongo()
        
        docs = await mongo.find_many(
            "news_events",
            {
                "is_low_value": True,
                "last_update_time": {"$gte": datetime.utcnow() - timedelta(hours=hours)},
            },
            limit=limit,
            sort=[("filtered_at", -1)],
        )
        
        return [NewsEvent(**doc) for doc in docs]
    
    async def get_valid_events_for_report(
        self,
        hours: int = 24,
        limit: int = 50,
        trace_id: Optional[str] = None,
    ) -> List[NewsEvent]:
        """
        获取用于报告生成的有效事件
        
        过滤掉低价值事件，只返回高质量事件
        """
        mongo = await self._get_mongo()
        
        docs = await mongo.find_many(
            "news_events",
            {
                "$or": [
                    {"is_low_value": {"$exists": False}},
                    {"is_low_value": False},
                ],
                "last_update_time": {"$gte": datetime.utcnow() - timedelta(hours=hours)},
            },
            limit=limit,
            sort=[("news_count", -1), ("last_update_time", -1)],
        )
        
        return [NewsEvent(**doc) for doc in docs]
    
    # ==================== LLM 分级增强 ====================
    
    async def enrich_events_batch(
        self,
        event_ids: Optional[List[str]] = None,
        hours: int = 24,
        limit: int = 50,
        trace_id: Optional[str] = None,
    ) -> Dict[str, int]:
        """
        分级批量增强事件字段
        
        分级策略（降低 LLM 成本 60%+）：
        - P1/P2（官方/监管）：全量 LLM 增强（情绪 + 板块 + 影响范围 + 政策级别）
        - P3（专业财经）：仅未识别板块时调用简化 LLM（只提取板块）
        - P4/P5（综合/社区）：纯规则填充，不调用 LLM
        
        Args:
            event_ids: 指定事件ID列表，None 则自动查询未增强的事件
            hours: 查询时间范围（小时）
            limit: 最大处理数量
            trace_id: 追踪ID
            
        Returns:
            各类型增强数量 {"full": x, "partial": y, "rule": z, "skip": w}
        """
        import asyncio
        from src.config import config_manager
        
        mongo = await self._get_mongo()
        llm = await self._get_llm_service()
        
        # 获取分级配置
        tiered_config = config_manager.get("collector.llm_enrichment.tiered_strategy", {})
        full_priorities = set(tiered_config.get("full_enrich_priorities", [5, 4]))
        partial_priorities = set(tiered_config.get("partial_enrich_priorities", [3]))
        rule_priorities = set(tiered_config.get("rule_fill_priorities", [2, 1]))
        
        # 获取关键词规则
        keyword_rules = config_manager.get("collector.llm_enrichment.keyword_sector_rules", [])
        
        # 查询未增强的事件（排除低价值事件）
        if event_ids:
            query = {"id": {"$in": event_ids}}
        else:
            query = {
                "enriched_at": {"$exists": False},
                "last_update_time": {"$gte": datetime.utcnow() - timedelta(hours=hours)},
                # 排除已标记为低价值的事件
                "$or": [
                    {"is_low_value": {"$exists": False}},
                    {"is_low_value": False},
                ],
            }
        
        events = await mongo.find_many(
            "news_events",
            query,
            limit=limit,
            sort=[("news_count", -1)],
        )
        
        if not events:
            self.logger.info(f"[{trace_id}] No events to enrich (after low-value filter)")
            return {"full": 0, "partial": 0, "rule": 0, "skip": 0}
        
        self.logger.info(f"[{trace_id}] Tiered enriching {len(events)} events...")
        
        stats = {"full": 0, "partial": 0, "rule": 0, "skip": 0}
        semaphore = asyncio.Semaphore(5)
        
        async def enrich_single(event_doc) -> str:
            """返回增强类型: full/partial/rule/skip"""
            async with semaphore:
                priority = event_doc.get("primary_news_priority", 2)
                event_id = event_doc.get("id", "")
                title = event_doc.get("title", "")
                existing_sectors = event_doc.get("related_sectors", [])
                
                try:
                    # P1/P2: 全量 LLM 增强
                    if priority in full_priorities:
                        result = await llm.invoke_and_parse(
                            template_name="event_enrich",
                            title=title,
                            summary=event_doc.get("summary", ""),
                            category=event_doc.get("category", ""),
                            sources=", ".join(event_doc.get("sources", [])),
                        )
                        
                        if result:
                            update_fields = {
                                "sentiment": result.get("sentiment"),
                                "sentiment_score": result.get("sentiment_score", 0.0),
                                "impact_scope": result.get("impact_scope"),
                                "related_sectors": result.get("related_sectors", []),
                                "policy_level": result.get("policy_level"),
                                "enriched_at": datetime.utcnow(),
                                "enrich_type": "full",
                            }
                            await mongo.update_one(
                                "news_events",
                                {"id": event_id},
                                {"$set": update_fields}
                            )
                            return "full"
                    
                    # P3: 仅未识别板块时调用简化 LLM
                    elif priority in partial_priorities:
                        if not existing_sectors:
                            result = await llm.invoke_and_parse(
                                template_name="event_sector_only",
                                title=title,
                            )
                            
                            if result and result.get("sectors"):
                                # 使用规则补充其他字段
                                rule_result = self._apply_keyword_rules(title, keyword_rules)
                                update_fields = {
                                    "related_sectors": result.get("sectors", []),
                                    "sentiment": rule_result.get("sentiment", "neutral"),
                                    "sentiment_score": 0.0,
                                    "impact_scope": "sector",
                                    "enriched_at": datetime.utcnow(),
                                    "enrich_type": "partial",
                                }
                                await mongo.update_one(
                                    "news_events",
                                    {"id": event_id},
                                    {"$set": update_fields}
                                )
                                return "partial"
                        else:
                            # 已有板块，规则填充其他字段
                            rule_result = self._apply_keyword_rules(title, keyword_rules)
                            update_fields = {
                                "sentiment": rule_result.get("sentiment", "neutral"),
                                "sentiment_score": 0.0,
                                "impact_scope": "sector",
                                "enriched_at": datetime.utcnow(),
                                "enrich_type": "rule",
                            }
                            await mongo.update_one(
                                "news_events",
                                {"id": event_id},
                                {"$set": update_fields}
                            )
                            return "rule"
                    
                    # P4/P5: 纯规则填充
                    elif priority in rule_priorities:
                        rule_result = self._apply_keyword_rules(title, keyword_rules)
                        update_fields = {
                            "sentiment": rule_result.get("sentiment", "neutral"),
                            "sentiment_score": 0.0,
                            "impact_scope": rule_result.get("impact_scope", "stock"),
                            "related_sectors": rule_result.get("sectors", []),
                            "enriched_at": datetime.utcnow(),
                            "enrich_type": "rule",
                        }
                        await mongo.update_one(
                            "news_events",
                            {"id": event_id},
                            {"$set": update_fields}
                        )
                        return "rule"
                    
                    return "skip"
                    
                except Exception as e:
                    self.logger.warning(f"[{trace_id}] Enrich event {event_id} failed: {e}")
                    return "skip"
        
        tasks = [enrich_single(doc) for doc in events]
        results = await asyncio.gather(*tasks)
        
        for r in results:
            stats[r] = stats.get(r, 0) + 1
        
        self.logger.info(
            f"[{trace_id}] Tiered enrichment done: "
            f"full={stats['full']}, partial={stats['partial']}, "
            f"rule={stats['rule']}, skip={stats['skip']}"
        )
        return stats
    
    def _apply_keyword_rules(
        self,
        text: str,
        rules: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        应用关键词规则匹配板块和情绪
        
        Args:
            text: 文本内容
            rules: 关键词规则列表
            
        Returns:
            {"sectors": [...], "sentiment": "..."}
        """
        result = {
            "sectors": [],
            "sentiment": "neutral",
            "impact_scope": "stock",
        }
        
        matched_sectors = set()
        
        for rule in rules:
            keywords = rule.get("keywords", [])
            for kw in keywords:
                if kw in text:
                    # 收集板块
                    sectors = rule.get("sectors", [])
                    matched_sectors.update(sectors)
                    
                    # 更新情绪（后匹配的覆盖前面的）
                    sentiment = rule.get("sentiment")
                    if sentiment and sentiment != "neutral":
                        result["sentiment"] = sentiment
                    
                    break
        
        result["sectors"] = list(matched_sectors)[:5]  # 最多5个板块
        
        # 根据板块数量判断影响范围
        if len(result["sectors"]) >= 3:
            result["impact_scope"] = "market"
        elif len(result["sectors"]) >= 1:
            result["impact_scope"] = "sector"
        
        return result
    
    async def get_unenriched_events(
        self,
        hours: int = 24,
        limit: int = 100,
        trace_id: Optional[str] = None,
    ) -> List[NewsEvent]:
        """获取未增强的事件列表"""
        mongo = await self._get_mongo()
        
        docs = await mongo.find_many(
            "news_events",
            {
                "enriched_at": {"$exists": False},
                "last_update_time": {"$gte": datetime.utcnow() - timedelta(hours=hours)},
            },
            limit=limit,
            sort=[("news_count", -1)],
        )
        
        return [NewsEvent(**doc) for doc in docs]
