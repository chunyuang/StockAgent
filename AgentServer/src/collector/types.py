"""
新闻采集类型定义
"""

import hashlib
from enum import Enum, IntEnum
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field


# ==================== 源优先级体系 ====================

class SourcePriority(IntEnum):
    """
    来源优先级 (数字越大优先级越高)
    
    用于:
    - 跨源去重时保留高优先级源
    - 事件聚类选主新闻
    - 报告排序
    """
    P5_COMMUNITY = 1       # 社区讨论: 雪球
    P4_GENERAL_MEDIA = 2   # 综合媒体: 澎湃、东方财富
    P3_PRO_MEDIA = 3       # 专业财经: 财联社、金十、华尔街见闻
    P2_REGULATOR = 4       # 监管机构: 工信部、交易所
    P1_OFFICIAL = 5        # 官方源: 国务院、央行、证监会


class Sentiment(str, Enum):
    """情绪判断"""
    POSITIVE = "positive"   # 利好
    NEGATIVE = "negative"   # 利空
    NEUTRAL = "neutral"     # 中性


class ImpactScope(str, Enum):
    """影响范围"""
    MARKET = "market"       # 全市场
    SECTOR = "sector"       # 板块级
    STOCK = "stock"         # 个股级


class PolicyLevel(str, Enum):
    """政策级别"""
    CENTRAL = "central"     # 中央/国务院
    MINISTRY = "ministry"   # 部委级
    LOCAL = "local"         # 地方级
    COMPANY = "company"     # 企业级


class NewsCategory(str, Enum):
    """新闻分类"""
    # 财经
    FINANCE_FLASH = "finance_flash"         # 财经快讯
    FINANCE_ARTICLE = "finance_article"     # 财经文章
    FINANCE_REPORT = "finance_report"       # 研究报告
    
    # 政策（国内）
    POLICY_RELEASE = "policy_release"       # 政策发布
    POLICY_INTERPRET = "policy_interpret"   # 政策解读
    POLICY_NOTICE = "policy_notice"         # 通知公告
    POLICY_STANDARD = "policy_standard"     # 行业标准
    
    # 国际
    INTERNATIONAL = "international"         # 国际大事件（地缘政治、外交等）
    INTL_ECONOMY = "intl_economy"           # 国际经济（美联储、汇率等）
    INTL_COMMODITY = "intl_commodity"       # 国际大宗商品（油价、金价等）
    
    # 公司
    COMPANY_ANNOUNCE = "company_announce"   # 公司公告
    COMPANY_NEWS = "company_news"           # 公司新闻
    
    # 行业
    INDUSTRY_NEWS = "industry_news"         # 行业新闻
    INDUSTRY_ANALYSIS = "industry_analysis" # 行业分析
    
    # 其他
    GENERAL = "general"                     # 一般新闻


class NewsSource(str, Enum):
    """新闻来源"""
    # 财经媒体
    CLS = "cls"                     # 财联社
    EASTMONEY = "eastmoney"         # 东方财富
    XUEQIU = "xueqiu"               # 雪球
    WALLSTREETCN = "wallstreetcn"   # 华尔街见闻
    JIN10 = "jin10"                 # 金十数据
    GELONGHUI = "gelonghui"         # 格隆汇
    CAIXIN = "caixin"               # 财新
    
    # 政府机构
    MIIT = "miit"                   # 工信部
    CSRC = "csrc"                   # 证监会
    PBC = "pbc"                     # 央行
    MOF = "mof"                     # 财政部
    GOV = "gov"                     # 国务院
    
    # 交易所
    SSE = "sse"                     # 上交所
    SZSE = "szse"                   # 深交所
    
    # 科技/综合
    JUEJIN = "juejin"               # 稀土掘金
    THEPAPER = "thepaper"           # 澎湃新闻
    
    # 其他
    SINA = "sina"                   # 新浪财经
    TOUTIAO = "toutiao"             # 今日头条
    OTHER = "other"                 # 其他


# 源优先级映射表
SOURCE_PRIORITY_MAP: Dict["NewsSource", SourcePriority] = {
    # P1 - 官方 (国务院/央行/证监会)
    NewsSource.GOV: SourcePriority.P1_OFFICIAL,
    NewsSource.PBC: SourcePriority.P1_OFFICIAL,
    NewsSource.CSRC: SourcePriority.P1_OFFICIAL,
    NewsSource.MOF: SourcePriority.P1_OFFICIAL,
    
    # P2 - 监管/部委
    NewsSource.MIIT: SourcePriority.P2_REGULATOR,
    NewsSource.SSE: SourcePriority.P2_REGULATOR,
    NewsSource.SZSE: SourcePriority.P2_REGULATOR,
    
    # P3 - 专业财经
    NewsSource.CLS: SourcePriority.P3_PRO_MEDIA,
    NewsSource.JIN10: SourcePriority.P3_PRO_MEDIA,
    NewsSource.WALLSTREETCN: SourcePriority.P3_PRO_MEDIA,
    NewsSource.CAIXIN: SourcePriority.P3_PRO_MEDIA,
    NewsSource.GELONGHUI: SourcePriority.P3_PRO_MEDIA,
    
    # P4 - 综合媒体
    NewsSource.THEPAPER: SourcePriority.P4_GENERAL_MEDIA,
    NewsSource.EASTMONEY: SourcePriority.P4_GENERAL_MEDIA,
    NewsSource.SINA: SourcePriority.P4_GENERAL_MEDIA,
    NewsSource.TOUTIAO: SourcePriority.P4_GENERAL_MEDIA,
    NewsSource.JUEJIN: SourcePriority.P4_GENERAL_MEDIA,
    
    # P5 - 社区
    NewsSource.XUEQIU: SourcePriority.P5_COMMUNITY,
    
    # 默认
    NewsSource.OTHER: SourcePriority.P4_GENERAL_MEDIA,
}


def get_source_priority(source: "NewsSource") -> int:
    """获取来源优先级值"""
    return SOURCE_PRIORITY_MAP.get(source, SourcePriority.P4_GENERAL_MEDIA).value


class NewsItem(BaseModel):
    """
    新闻项
    
    统一的新闻数据结构，所有来源的新闻都转换为此格式。
    """
    # 唯一标识 (基于内容哈希生成)
    id: str = Field(default="")
    
    # 基本信息
    title: str = Field(description="标题")
    content: str = Field(default="", description="正文内容")
    summary: str = Field(default="", description="摘要")
    url: str = Field(default="", description="原文链接")
    
    # 分类
    source: NewsSource = Field(description="来源")
    category: NewsCategory = Field(default=NewsCategory.GENERAL, description="分类")
    
    # 时间
    publish_time: Optional[datetime] = Field(default=None, description="发布时间")
    collect_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="采集时间")
    
    # 关联
    ts_codes: List[str] = Field(default_factory=list, description="关联股票代码")
    tags: List[str] = Field(default_factory=list, description="标签")
    keywords: List[str] = Field(default_factory=list, description="关键词")
    
    # 元数据
    author: str = Field(default="", description="作者")
    source_id: str = Field(default="", description="来源系统中的原始ID")
    extra: Dict[str, Any] = Field(default_factory=dict, description="额外信息")
    
    # ========== 炒股关键信息 (优化新增) ==========
    
    # 来源评级
    source_priority: int = Field(default=2, description="来源优先级 1-5, 越高越权威")
    source_unique_key: str = Field(default="", description="来源+原始ID 快速去重键")
    
    # 情绪分析
    sentiment: Optional[Sentiment] = Field(default=None, description="情绪: 利好/利空/中性")
    sentiment_score: float = Field(default=0.0, description="情绪分数 -1.0 ~ 1.0")
    
    # 影响范围
    impact_scope: Optional[ImpactScope] = Field(default=None, description="影响范围: 全市场/板块/个股")
    related_sectors: List[str] = Field(default_factory=list, description="关联板块")
    
    # 政策属性 (仅政策类新闻)
    policy_level: Optional[PolicyLevel] = Field(default=None, description="政策级别: 中央/部委/地方/企业")
    
    # 紧急程度
    urgency: str = Field(default="normal", description="紧急程度: urgent/important/normal")
    
    # 实体识别
    mentioned_companies: List[str] = Field(default_factory=list, description="提及公司名")
    mentioned_persons: List[str] = Field(default_factory=list, description="提及人物")
    mentioned_amounts: List[str] = Field(default_factory=list, description="提及金额")
    
    # ========== 原有字段 ==========
    
    # 向量 (入库时生成)
    vector: List[float] = Field(default_factory=list)
    
    # 去重相关
    content_hash: str = Field(default="", description="内容哈希")
    title_hash: str = Field(default="", description="标题哈希")
    
    # 事件聚类相关 (深度去重后填充)
    event_id: Optional[str] = Field(default=None, description="关联事件ID")
    is_primary: bool = Field(default=False, description="是否为主新闻")
    clustered_at: Optional[datetime] = Field(default=None, description="聚类时间")
    
    def __init__(self, **data):
        super().__init__(**data)
        # 自动生成哈希
        if not self.content_hash:
            self.content_hash = self._compute_content_hash()
        if not self.title_hash:
            self.title_hash = self._compute_title_hash()
        # 自动生成 ID
        if not self.id:
            self.id = self._generate_id()
        # 自动填充源优先级
        if self.source_priority == 2:  # 默认值，说明未设置
            self.source_priority = get_source_priority(self.source)
        # 自动生成快速去重键
        if not self.source_unique_key and self.source_id:
            self.source_unique_key = f"{self.source.value}:{self.source_id}"
    
    def _compute_content_hash(self) -> str:
        """计算内容哈希"""
        text = f"{self.title}:{self.content[:500]}" if self.content else self.title
        return hashlib.md5(text.encode('utf-8')).hexdigest()
    
    def _compute_title_hash(self) -> str:
        """计算标题哈希"""
        return hashlib.md5(self.title.encode('utf-8')).hexdigest()
    
    def _generate_id(self) -> str:
        """
        生成唯一 ID
        
        规则: source + 日期 + 内容哈希前8位
        这样同一篇文章无论哪个源抓到，ID 都相同
        """
        date_str = ""
        if self.publish_time:
            date_str = self.publish_time.strftime("%Y%m%d")
        else:
            date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        
        return f"{self.source.value}_{date_str}_{self.content_hash[:12]}"
    
    def get_text_for_embedding(self) -> str:
        """获取用于生成向量的文本"""
        parts = [self.title]
        if self.summary:
            parts.append(self.summary)
        if self.content:
            parts.append(self.content[:1000])
        if self.keywords:
            parts.append(" ".join(self.keywords))
        return "\n".join(parts)
    
    class Config:
        extra = "allow"


class CollectResult(BaseModel):
    """采集结果"""
    source: str = ""
    success: bool = True
    
    # 统计
    total_fetched: int = 0          # 抓取总数
    new_count: int = 0              # 新增数
    duplicate_count: int = 0        # 重复数 (完全重复)
    similar_count: int = 0          # 相似数 (跨源重复)
    failed_count: int = 0           # 失败数
    
    # 详情
    new_ids: List[str] = Field(default_factory=list)
    duplicate_ids: List[str] = Field(default_factory=list)
    similar_ids: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    
    # 耗时
    elapsed_ms: float = 0
    
    def merge(self, other: "CollectResult") -> "CollectResult":
        """合并两个结果"""
        return CollectResult(
            source=f"{self.source},{other.source}" if self.source else other.source,
            success=self.success and other.success,
            total_fetched=self.total_fetched + other.total_fetched,
            new_count=self.new_count + other.new_count,
            duplicate_count=self.duplicate_count + other.duplicate_count,
            similar_count=self.similar_count + other.similar_count,
            failed_count=self.failed_count + other.failed_count,
            new_ids=self.new_ids + other.new_ids,
            errors=self.errors + other.errors,
            elapsed_ms=max(self.elapsed_ms, other.elapsed_ms),
        )
