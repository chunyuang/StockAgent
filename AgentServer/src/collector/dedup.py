"""
新闻去重引擎

实现多层去重策略:
1. 精确去重 - 内容哈希匹配 (同源同内容)
2. 跨源去重 - 标题相似度 (不同源同一事件)
3. 向量去重 - 语义相似度 (改写稿件)
4. 事件核心指纹去重 - 基于 policy_level + core_subject + impact_scope

TTL 差异化策略:
- P1/P2 (官方/监管): 24h
- P3 (专业财经): 12h
- P4/P5 (综合/社区): 1-6h
"""

import logging
import hashlib
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from src.config import config_manager


@dataclass
class DeduplicationResult:
    """去重结果"""
    total: int = 0
    new_items: List[Any] = field(default_factory=list)
    duplicate_items: List[Any] = field(default_factory=list)
    similar_items: List[Tuple[Any, Any, float]] = field(default_factory=list)  # (新项, 已存在项, 相似度)
    
    @property
    def new_count(self) -> int:
        return len(self.new_items)
    
    @property
    def duplicate_count(self) -> int:
        return len(self.duplicate_items)
    
    @property
    def similar_count(self) -> int:
        return len(self.similar_items)


class DeduplicationEngine:
    """
    去重引擎
    
    三层去重策略:
    
    1. **精确去重 (Hash)** - O(1)
       - 基于 content_hash 或 title_hash
       - 完全相同的内容
       
    2. **标题相似度去重** - O(n)
       - 基于标题文本相似度
       - 阈值: 0.85 (85%相似视为重复)
       - 用于跨源同一事件检测
       
    3. **向量语义去重** - O(log n)
       - 基于向量余弦相似度
       - 阈值: 0.92 (92%相似视为重复)
       - 用于改写稿件检测
    
    Example:
        engine = DeduplicationEngine()
        
        # 检查单条
        is_dup, reason = await engine.is_duplicate(news_item)
        
        # 批量去重
        result = await engine.deduplicate_batch(news_items)
    """
    
    def __init__(
        self,
        title_similarity_threshold: float = 0.85,
        vector_similarity_threshold: float = 0.92,
        time_window_hours: int = 72,
    ):
        """
        Args:
            title_similarity_threshold: 标题相似度阈值
            vector_similarity_threshold: 向量相似度阈值
            time_window_hours: 去重时间窗口 (小时)
        """
        self.title_threshold = title_similarity_threshold
        self.vector_threshold = vector_similarity_threshold
        self.time_window = timedelta(hours=time_window_hours)
        
        self.logger = logging.getLogger("src.collector.DeduplicationEngine")
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
    
    # ==================== 精确去重 ====================
    
    async def check_hash_exists(
        self,
        content_hash: str,
        collection: str = "news",
        trace_id: Optional[str] = None,
    ) -> bool:
        """检查内容哈希是否已存在"""
        mongo = await self._get_mongo()
        
        try:
            doc = await mongo.find_one(collection, {"content_hash": content_hash})
            return doc is not None
        except Exception as e:
            self.logger.error(f"[{trace_id}] Check hash error: {e}")
            return False
    
    async def check_hash_batch(
        self,
        content_hashes: List[str],
        collection: str = "news",
        trace_id: Optional[str] = None,
    ) -> Dict[str, bool]:
        """批量检查内容哈希"""
        mongo = await self._get_mongo()
        
        try:
            docs = await mongo.find_many(
                collection,
                {"content_hash": {"$in": content_hashes}},
                projection={"content_hash": 1},
            )
            existing = {doc["content_hash"] for doc in docs}
            return {h: h in existing for h in content_hashes}
        except Exception as e:
            self.logger.error(f"[{trace_id}] Check hash batch error: {e}")
            return {h: False for h in content_hashes}
    
    # ==================== 标题相似度去重 ====================
    
    def compute_title_similarity(self, title1: str, title2: str) -> float:
        """
        计算标题相似度
        
        使用改进的算法:
        1. 预处理: 去除标点、空格、数字
        2. SequenceMatcher 计算相似度
        """
        # 预处理
        t1 = self._normalize_title(title1)
        t2 = self._normalize_title(title2)
        
        if not t1 or not t2:
            return 0.0
        
        # 计算相似度
        return SequenceMatcher(None, t1, t2).ratio()
    
    def _normalize_title(self, title: str) -> str:
        """标题标准化"""
        # 去除标点符号
        title = re.sub(r'[^\w\s]', '', title)
        # 去除数字
        title = re.sub(r'\d+', '', title)
        # 去除空格
        title = re.sub(r'\s+', '', title)
        return title.lower()
    
    async def find_similar_by_title(
        self,
        title: str,
        collection: str = "news",
        time_window: Optional[timedelta] = None,
        trace_id: Optional[str] = None,
    ) -> List[Tuple[str, str, float]]:
        """
        查找标题相似的新闻
        
        Returns:
            [(id, title, similarity), ...]
        """
        mongo = await self._get_mongo()
        time_window = time_window or self.time_window
        
        try:
            # 查询时间窗口内的新闻
            cutoff = datetime.utcnow() - time_window
            docs = await mongo.find_many(
                collection,
                {"collect_time": {"$gte": cutoff}},
                projection={"_id": 1, "title": 1},
                limit=1000,
            )
            
            similar = []
            for doc in docs:
                sim = self.compute_title_similarity(title, doc.get("title", ""))
                if sim >= self.title_threshold:
                    similar.append((doc["_id"], doc["title"], sim))
            
            # 按相似度排序
            similar.sort(key=lambda x: x[2], reverse=True)
            return similar[:5]  # 返回最相似的5个
            
        except Exception as e:
            self.logger.error(f"[{trace_id}] Find similar error: {e}")
            return []
    
    # ==================== 向量语义去重 ====================
    
    async def find_similar_by_vector(
        self,
        vector: List[float],
        collection: str = "semantic_memory",
        threshold: Optional[float] = None,
        trace_id: Optional[str] = None,
    ) -> List[Tuple[str, float]]:
        """
        基于向量查找相似新闻
        
        Returns:
            [(id, similarity), ...]
        """
        milvus = await self._get_milvus()
        threshold = threshold or self.vector_threshold
        
        try:
            results = await milvus.search(
                collection=collection,
                query_vector=vector,
                top_k=5,
                output_fields=["id"],
            )
            
            similar = []
            for hit in results:
                # Milvus 返回的是距离，需要转换为相似度
                distance = hit.get("distance", 0)
                # 假设使用 L2 距离，转换为相似度
                # 或者如果使用 IP (内积)，distance 就是相似度
                similarity = 1 - distance if distance < 1 else 1 / (1 + distance)
                
                if similarity >= threshold:
                    similar.append((hit.get("entity", {}).get("id", ""), similarity))
            
            return similar
            
        except Exception as e:
            self.logger.error(f"[{trace_id}] Find similar by vector error: {e}")
            return []
    
    # ==================== 综合去重 ====================
    
    async def is_duplicate(
        self,
        news_item: "NewsItem",
        collection: str = "news",
        trace_id: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[str]]:
        """
        检查新闻是否重复
        
        Args:
            news_item: 新闻项
            collection: MongoDB 集合名
            trace_id: 追踪ID
            
        Returns:
            (是否重复, 原因, 重复项ID)
        """
        # 1. 精确哈希匹配
        if await self.check_hash_exists(news_item.content_hash, collection, trace_id):
            return True, "exact_hash_match", None
        
        # 2. 标题相似度匹配
        similar = await self.find_similar_by_title(
            news_item.title, collection, trace_id=trace_id
        )
        if similar:
            best_match = similar[0]
            return True, f"title_similar({best_match[2]:.2f})", best_match[0]
        
        # 3. 向量语义匹配 (如果有向量)
        if news_item.vector:
            vector_similar = await self.find_similar_by_vector(
                news_item.vector, trace_id=trace_id
            )
            if vector_similar:
                best_match = vector_similar[0]
                return True, f"vector_similar({best_match[1]:.2f})", best_match[0]
        
        return False, "new", None
    
    async def deduplicate_batch(
        self,
        items: List["NewsItem"],
        collection: str = "news",
        check_vector: bool = False,
        trace_id: Optional[str] = None,
    ) -> DeduplicationResult:
        """
        批量去重
        
        Args:
            items: 新闻项列表
            collection: MongoDB 集合名
            check_vector: 是否检查向量相似度
            trace_id: 追踪ID
            
        Returns:
            去重结果
        """
        result = DeduplicationResult(total=len(items))
        
        if not items:
            return result
        
        # 1. 批量哈希检查
        content_hashes = [item.content_hash for item in items]
        hash_exists = await self.check_hash_batch(content_hashes, collection, trace_id)
        
        # 分离精确重复和需要进一步检查的
        to_check = []
        for item in items:
            if hash_exists.get(item.content_hash, False):
                result.duplicate_items.append(item)
            else:
                to_check.append(item)
        
        # 2. 标题相似度检查
        for item in to_check:
            similar = await self.find_similar_by_title(
                item.title, collection, trace_id=trace_id
            )
            if similar:
                best_match = similar[0]
                result.similar_items.append((item, best_match[0], best_match[2]))
            else:
                result.new_items.append(item)
        
        self.logger.info(
            f"[{trace_id}] Deduplication: {result.total} total, "
            f"{result.new_count} new, {result.duplicate_count} dup, "
            f"{result.similar_count} similar"
        )
        
        return result
    
    # ==================== 内存缓存去重 ====================
    
    def deduplicate_in_memory(
        self,
        items: List["NewsItem"],
    ) -> Tuple[List["NewsItem"], List["NewsItem"]]:
        """
        内存中去重 (用于批量采集时的预处理)
        
        Returns:
            (唯一项列表, 重复项列表)
        """
        seen_hashes: Set[str] = set()
        unique = []
        duplicates = []
        
        for item in items:
            if item.content_hash in seen_hashes:
                duplicates.append(item)
            else:
                seen_hashes.add(item.content_hash)
                unique.append(item)
        
        return unique, duplicates


# ==================== 事件核心指纹 ====================

@dataclass
class EventCoreFingerprint:
    """
    事件核心指纹
    
    基于三要素生成唯一指纹：
    - policy_level: 政策级别 (central/ministry/local/company)
    - core_subject: 核心主体 (水资源/工业互联网/新能源汽车等)
    - impact_scope: 影响范围 (market/sector/stock)
    
    用于炒股场景的精准去重，识别同一政策/事件的不同报道。
    """
    policy_level: str = ""
    core_subject: str = ""
    impact_scope: str = ""
    
    @property
    def fingerprint(self) -> str:
        """生成指纹字符串"""
        return f"{self.policy_level}:{self.core_subject}:{self.impact_scope}"
    
    @property
    def fingerprint_hash(self) -> str:
        """生成指纹哈希"""
        return hashlib.md5(self.fingerprint.encode('utf-8')).hexdigest()[:16]
    
    def is_valid(self) -> bool:
        """是否有效指纹（至少有核心主体）"""
        return bool(self.core_subject)


class EventFingerprintExtractor:
    """
    事件核心指纹提取器
    
    从新闻标题/内容中提取核心指纹要素。
    """
    
    # 默认核心主体关键词
    _DEFAULT_CORE_SUBJECTS = [
        "水资源", "节水", "水利", "污水", "环保",
        "工业互联网", "智能制造", "人工智能", "AI", "大模型", "芯片", "半导体",
        "新能源", "光伏", "储能", "风电", "油气", "石油", "天然气",
        "利率", "降息", "降准", "汇率", "外汇", "信贷",
        "新能源汽车", "智能驾驶", "充电桩", "汽车",
        "医药", "医疗", "创新药", "集采",
        "消费", "白酒", "食品", "家电",
        "房地产", "地产", "银行", "保险",
        "央企", "国企", "混改", "重组",
    ]
    
    _DEFAULT_IMPACT_KEYWORDS = {
        "market": ["A股", "全市场", "大盘", "指数", "两会", "政府工作报告", "中央经济工作会议", "降准", "降息", "印花税"],
        "sector": ["行业", "板块", "产业链", "赛道", "龙头"],
        "stock": ["公司", "股份", "集团"],
    }
    
    def __init__(self):
        self.logger = logging.getLogger("src.collector.EventFingerprintExtractor")
        self._core_subjects: Optional[List[str]] = None
        self._impact_keywords: Optional[Dict[str, List[str]]] = None
    
    @property
    def core_subjects(self) -> List[str]:
        """获取核心主体关键词（从配置或默认）"""
        if self._core_subjects is None:
            config_keywords = config_manager.get(
                "collector.dedup.event_fingerprint.core_subject_keywords", []
            )
            self._core_subjects = config_keywords if config_keywords else self._DEFAULT_CORE_SUBJECTS
        return self._core_subjects
    
    @property
    def impact_keywords(self) -> Dict[str, List[str]]:
        """获取影响范围关键词（从配置或默认）"""
        if self._impact_keywords is None:
            config_keywords = config_manager.get(
                "collector.dedup.event_fingerprint.impact_scope_keywords", {}
            )
            self._impact_keywords = config_keywords if config_keywords else self._DEFAULT_IMPACT_KEYWORDS
        return self._impact_keywords
    
    def extract(
        self,
        title: str,
        content: str = "",
        policy_level: Optional[str] = None,
    ) -> EventCoreFingerprint:
        """
        从文本中提取事件核心指纹
        
        Args:
            title: 新闻标题
            content: 新闻内容（可选，用于补充提取）
            policy_level: 已知的政策级别（如果有）
            
        Returns:
            EventCoreFingerprint
        """
        text = f"{title} {content[:500]}" if content else title
        
        # 1. 提取核心主体（取第一个匹配的关键词）
        core_subject = ""
        for keyword in self.core_subjects:
            if keyword in text:
                core_subject = keyword
                break
        
        # 2. 确定影响范围
        impact_scope = "stock"  # 默认个股级
        for scope, keywords in self.impact_keywords.items():
            for kw in keywords:
                if kw in text:
                    impact_scope = scope
                    break
            if impact_scope != "stock":
                break
        
        # 3. 政策级别（如果未提供，尝试从文本推断）
        if not policy_level:
            policy_level = self._infer_policy_level(text)
        
        return EventCoreFingerprint(
            policy_level=policy_level or "",
            core_subject=core_subject,
            impact_scope=impact_scope,
        )
    
    def _infer_policy_level(self, text: str) -> str:
        """从文本推断政策级别"""
        central_keywords = ["国务院", "中央", "总书记", "总理", "两会", "全国人大", "全国政协"]
        ministry_keywords = ["工信部", "发改委", "财政部", "央行", "证监会", "银保监", "商务部"]
        local_keywords = ["省", "市", "地方", "区域"]
        
        for kw in central_keywords:
            if kw in text:
                return "central"
        for kw in ministry_keywords:
            if kw in text:
                return "ministry"
        for kw in local_keywords:
            if kw in text:
                return "local"
        return ""


# ==================== 快速去重器 ====================

@dataclass
class QuickDedupResult:
    """快速去重结果"""
    to_check: List[Any] = field(default_factory=list)  # 需进一步检查的
    skipped_by_redis: int = 0                           # Redis 跳过数
    skipped_by_memory: int = 0                          # 内存跳过数
    skipped_by_fingerprint: int = 0                     # 指纹跳过数


class QuickDeduplicator:
    """
    快速去重器 (四层策略)
    
    针对高频采集场景优化，减少 MongoDB 查询次数:
    
    Layer 1: Redis source_unique_key (O(1))
        - 同源同ID直接跳过，不计算 MD5
        - TTL 按优先级差异化：P1/P2=24h, P3=12h, P4/P5=1-6h
        
    Layer 2: 内存 title_hash Set (O(1))
        - 跨源标题重复检测
        - 进程内缓存
        
    Layer 3: 事件核心指纹去重 (O(1))
        - 基于 policy_level + core_subject + impact_scope
        - 用于识别同一政策/事件的不同报道
        
    Layer 4: 返回待 MongoDB 检查的列表
        - 最终由 DeduplicationEngine.deduplicate_batch 处理
    
    Example:
        quick_dedup = QuickDeduplicator()
        
        # 快速预过滤
        result = await quick_dedup.quick_dedup(items)
        
        # 只对 result.to_check 做完整去重
        final = await dedup_engine.deduplicate_batch(result.to_check)
    """
    
    # Redis 键前缀
    REDIS_KEY_PREFIX = "news:seen:"
    REDIS_FINGERPRINT_PREFIX = "news:fp:"  # 事件指纹前缀
    
    # 默认 TTL 配置（秒）- 按优先级差异化
    DEFAULT_TTL_BY_PRIORITY = {
        5: 86400,   # P1_OFFICIAL: 24小时
        4: 86400,   # P2_REGULATOR: 24小时
        3: 43200,   # P3_PRO_MEDIA: 12小时
        2: 21600,   # P4_GENERAL_MEDIA: 6小时
        1: 3600,    # P5_COMMUNITY: 1小时
    }
    
    # 内存缓存最大容量
    MEMORY_CACHE_MAX = 10000
    
    def __init__(self):
        self.logger = logging.getLogger("src.collector.QuickDeduplicator")
        self._title_hash_cache: Set[str] = set()
        self._fingerprint_cache: Set[str] = set()  # 指纹缓存
        self._redis = None
        self._fingerprint_extractor = EventFingerprintExtractor()
        self._ttl_config: Optional[Dict[int, int]] = None
    
    @property
    def ttl_by_priority(self) -> Dict[int, int]:
        """获取按优先级的 TTL 配置（秒）"""
        if self._ttl_config is None:
            config = config_manager.get("collector.dedup.ttl_by_priority", {})
            if config:
                # 将配置的小时转换为秒，并映射到优先级数值
                priority_map = {
                    "P1_OFFICIAL": 5,
                    "P2_REGULATOR": 4,
                    "P3_PRO_MEDIA": 3,
                    "P4_GENERAL_MEDIA": 2,
                    "P5_COMMUNITY": 1,
                }
                self._ttl_config = {}
                for name, hours in config.items():
                    priority = priority_map.get(name)
                    if priority:
                        self._ttl_config[priority] = hours * 3600  # 转换为秒
            else:
                self._ttl_config = self.DEFAULT_TTL_BY_PRIORITY
        return self._ttl_config
    
    def get_ttl_for_priority(self, priority: int) -> int:
        """根据优先级获取 TTL（秒）"""
        return self.ttl_by_priority.get(priority, 21600)  # 默认 6 小时
    
    async def _get_redis(self):
        """延迟获取 Redis 连接"""
        if self._redis is None:
            from core.managers import redis_manager
            if not redis_manager.is_initialized:
                await redis_manager.initialize()
            self._redis = redis_manager
        return self._redis
    
    async def quick_dedup(
        self,
        items: List["NewsItem"],
        use_fingerprint: bool = True,
        trace_id: Optional[str] = None,
    ) -> QuickDedupResult:
        """
        快速去重 (不查 MongoDB)
        
        四层策略：
        1. Redis source_unique_key
        2. 内存 title_hash
        3. 事件核心指纹（可选）
        4. 返回待 MongoDB 检查的列表
        
        Args:
            items: 新闻项列表
            use_fingerprint: 是否启用指纹去重
            trace_id: 追踪ID
            
        Returns:
            QuickDedupResult: 需进一步检查的列表和统计
        """
        result = QuickDedupResult()
        
        if not items:
            return result
        
        redis = await self._get_redis()
        fingerprint_enabled = use_fingerprint and config_manager.get(
            "collector.dedup.event_fingerprint.enabled", True
        )
        
        for item in items:
            # Layer 1: Redis source_unique_key 去重
            if item.source_unique_key:
                redis_key = f"{self.REDIS_KEY_PREFIX}{item.source_unique_key}"
                try:
                    exists = await redis.exists(redis_key)
                    if exists:
                        result.skipped_by_redis += 1
                        continue
                except Exception as e:
                    self.logger.debug(f"[{trace_id}] Redis check error: {e}")
            
            # Layer 2: 内存 title_hash 去重
            if item.title_hash in self._title_hash_cache:
                result.skipped_by_memory += 1
                continue
            
            # Layer 3: 事件核心指纹去重（仅对高优先级源启用）
            if fingerprint_enabled and item.source_priority >= 3:
                fingerprint = self._fingerprint_extractor.extract(
                    title=item.title,
                    content=item.content,
                    policy_level=item.policy_level.value if item.policy_level else None,
                )
                
                if fingerprint.is_valid():
                    fp_hash = fingerprint.fingerprint_hash
                    
                    # 检查 Redis 指纹
                    fp_redis_key = f"{self.REDIS_FINGERPRINT_PREFIX}{fp_hash}"
                    try:
                        fp_exists = await redis.exists(fp_redis_key)
                        if fp_exists:
                            result.skipped_by_fingerprint += 1
                            self.logger.debug(
                                f"[{trace_id}] Fingerprint dup: {item.title[:30]} -> {fingerprint.fingerprint}"
                            )
                            continue
                    except Exception as e:
                        self.logger.debug(f"[{trace_id}] Redis fingerprint check error: {e}")
                    
                    # 检查内存指纹缓存
                    if fp_hash in self._fingerprint_cache:
                        result.skipped_by_fingerprint += 1
                        continue
                    
                    # 添加到指纹缓存
                    self._fingerprint_cache.add(fp_hash)
            
            # 通过所有层，加入待检查列表
            result.to_check.append(item)
            
            # 更新内存缓存
            self._title_hash_cache.add(item.title_hash)
            
            # 缓存容量控制
            if len(self._title_hash_cache) > self.MEMORY_CACHE_MAX:
                self._trim_cache()
        
        self.logger.debug(
            f"[{trace_id}] QuickDedup: {len(items)} items -> "
            f"redis_skip={result.skipped_by_redis}, "
            f"memory_skip={result.skipped_by_memory}, "
            f"fingerprint_skip={result.skipped_by_fingerprint}, "
            f"to_check={len(result.to_check)}"
        )
        
        return result
    
    async def mark_seen(
        self,
        items: List["NewsItem"],
        trace_id: Optional[str] = None,
    ) -> int:
        """
        标记新闻为已见 (入库后调用)
        
        TTL 按优先级差异化：
        - P1/P2: 24小时
        - P3: 12小时
        - P4/P5: 1-6小时
        
        Args:
            items: 已入库的新闻项
            trace_id: 追踪ID
            
        Returns:
            成功标记数
        """
        if not items:
            return 0
        
        redis = await self._get_redis()
        marked = 0
        fingerprint_enabled = config_manager.get(
            "collector.dedup.event_fingerprint.enabled", True
        )
        
        for item in items:
            # 获取该项的 TTL
            ttl = self.get_ttl_for_priority(item.source_priority)
            
            # 标记 source_unique_key
            if item.source_unique_key:
                redis_key = f"{self.REDIS_KEY_PREFIX}{item.source_unique_key}"
                try:
                    await redis.setex(redis_key, ttl, "1")
                    marked += 1
                except Exception as e:
                    self.logger.debug(f"[{trace_id}] Redis set error: {e}")
            
            # 标记事件指纹（仅高优先级）
            if fingerprint_enabled and item.source_priority >= 3:
                fingerprint = self._fingerprint_extractor.extract(
                    title=item.title,
                    content=item.content,
                    policy_level=item.policy_level.value if item.policy_level else None,
                )
                if fingerprint.is_valid():
                    fp_redis_key = f"{self.REDIS_FINGERPRINT_PREFIX}{fingerprint.fingerprint_hash}"
                    try:
                        await redis.setex(fp_redis_key, ttl, fingerprint.fingerprint)
                    except Exception as e:
                        self.logger.debug(f"[{trace_id}] Redis fingerprint set error: {e}")
            
            # 同步更新内存缓存
            self._title_hash_cache.add(item.title_hash)
        
        return marked
    
    async def batch_mark_seen(
        self,
        items: List["NewsItem"],
        trace_id: Optional[str] = None,
    ) -> int:
        """
        批量标记新闻为已见 (使用 Redis Pipeline)
        
        TTL 按优先级差异化
        
        Args:
            items: 已入库的新闻项
            trace_id: 追踪ID
            
        Returns:
            成功标记数
        """
        if not items:
            return 0
        
        redis = await self._get_redis()
        fingerprint_enabled = config_manager.get(
            "collector.dedup.event_fingerprint.enabled", True
        )
        
        try:
            # 使用 pipeline 批量设置
            pipe = redis.client.pipeline()
            count = 0
            
            for item in items:
                # 获取该项的 TTL
                ttl = self.get_ttl_for_priority(item.source_priority)
                
                # 标记 source_unique_key
                if item.source_unique_key:
                    redis_key = f"{self.REDIS_KEY_PREFIX}{item.source_unique_key}"
                    pipe.setex(redis_key, ttl, "1")
                    count += 1
                
                # 标记事件指纹（仅高优先级）
                if fingerprint_enabled and item.source_priority >= 3:
                    fingerprint = self._fingerprint_extractor.extract(
                        title=item.title,
                        content=item.content,
                        policy_level=item.policy_level.value if item.policy_level else None,
                    )
                    if fingerprint.is_valid():
                        fp_redis_key = f"{self.REDIS_FINGERPRINT_PREFIX}{fingerprint.fingerprint_hash}"
                        pipe.setex(fp_redis_key, ttl, fingerprint.fingerprint)
                
                # 同步更新内存缓存
                self._title_hash_cache.add(item.title_hash)
            
            await pipe.execute()
            
            self.logger.debug(f"[{trace_id}] Batch marked {count} items as seen (TTL by priority)")
            return count
            
        except Exception as e:
            self.logger.error(f"[{trace_id}] Batch mark seen error: {e}")
            # 降级为单条标记
            return await self.mark_seen(items, trace_id)
    
    def _trim_cache(self):
        """清理内存缓存 (保留最近一半)"""
        if len(self._title_hash_cache) > self.MEMORY_CACHE_MAX:
            cache_list = list(self._title_hash_cache)
            self._title_hash_cache = set(cache_list[len(cache_list) // 2:])
            self.logger.debug(f"Trimmed title cache to {len(self._title_hash_cache)} items")
        
        if len(self._fingerprint_cache) > self.MEMORY_CACHE_MAX:
            fp_list = list(self._fingerprint_cache)
            self._fingerprint_cache = set(fp_list[len(fp_list) // 2:])
            self.logger.debug(f"Trimmed fingerprint cache to {len(self._fingerprint_cache)} items")
    
    def clear_cache(self):
        """清空内存缓存"""
        self._title_hash_cache.clear()
        self._fingerprint_cache.clear()
        self.logger.info("Memory caches cleared")
    
    async def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "title_cache_size": len(self._title_hash_cache),
            "fingerprint_cache_size": len(self._fingerprint_cache),
            "memory_cache_max": self.MEMORY_CACHE_MAX,
            "ttl_config": self.ttl_by_priority,
        }
