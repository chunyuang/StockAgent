"""
新闻筛选器

实现4步硬规则筛选：
1. 极速降噪 - 删除6类无价值新闻
2. 重要性打分 - 3维度量化评分
3. 同类聚类 - 同主线合并
4. 精简输出 - 只保留核心信息

配置来源：config/news_filter.yaml
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from src.config import config_manager


logger = logging.getLogger(__name__)


# ==================== 配置加载器 ====================


class NewsFilterConfig:
    """
    新闻筛选配置加载器
    
    从 config/news_filter.yaml 读取配置，提供类型安全的访问。
    支持热重载和默认值回退。
    """
    
    # 默认配置（当 YAML 未配置时使用）
    _DEFAULT_NOISE_KEYWORDS: Set[str] = {
        "县委", "乡镇", "街道办", "社区", "居委会", "村委",
        "民政局", "交通局", "城管", "环卫", "物业",
        "停水", "停电", "停气", "道路施工", "交通管制",
        "娱乐", "八卦", "明星", "网红", "综艺", "电视剧", "电影上映",
        "体育赛事", "球赛", "比分", "联赛",
        "天气预报", "气象", "暴雨预警", "高温预警",
        "斯里兰卡", "孟加拉", "尼泊尔", "老挝", "柬埔寨", "缅甸",
        "非洲联盟", "拉美", "南美", "加勒比",
        "统计局例行", "月度例会", "常规会议", "工作汇报",
        "股东减持", "高管减持", "小额增持", "人事变动", "监事辞职",
        "会计师变更", "独立董事",
        "车祸", "火灾", "失踪", "寻人", "婚礼", "葬礼",
    }
    
    _DEFAULT_NOISE_SOURCE_PATTERNS: List[str] = [
        r"地方.*日报",
        r".*晚报",
        r".*都市报",
        r".*晨报",
    ]
    
    _DEFAULT_DUPLICATE_PATTERNS: List[str] = [
        r"^(续|追踪|跟进|更新)[:：]",
        r"(第\d+次|再次|继续)",
        r"(最新|持续|进一步)报道",
    ]
    
    @property
    def noise_keywords(self) -> Set[str]:
        """获取无价值关键词集合"""
        keywords = config_manager.get("news_filter.noise_keywords", [])
        if keywords:
            return set(keywords)
        return self._DEFAULT_NOISE_KEYWORDS
    
    @property
    def noise_source_patterns(self) -> List[str]:
        """获取无价值来源正则模式"""
        patterns = config_manager.get("news_filter.noise_source_patterns", [])
        return patterns if patterns else self._DEFAULT_NOISE_SOURCE_PATTERNS
    
    @property
    def duplicate_patterns(self) -> List[str]:
        """获取重复/跟进新闻正则模式"""
        patterns = config_manager.get("news_filter.duplicate_patterns", [])
        return patterns if patterns else self._DEFAULT_DUPLICATE_PATTERNS
    
    @property
    def source_level_keywords(self) -> Dict[str, List[str]]:
        """获取来源级别关键词"""
        return config_manager.get("news_filter.source_level_keywords", {})
    
    @property
    def impact_scope_keywords(self) -> Dict[str, List[str]]:
        """获取影响范围关键词"""
        return config_manager.get("news_filter.impact_scope_keywords", {})
    
    @property
    def fund_sensitivity_keywords(self) -> Dict[str, List[str]]:
        """获取资金敏感关键词"""
        return config_manager.get("news_filter.fund_sensitivity_keywords", {})
    
    @property
    def cluster_pools(self) -> Dict[str, Dict[str, Any]]:
        """获取聚类池配置"""
        return config_manager.get("news_filter.cluster_pools", {})
    
    @property
    def output_config(self) -> Dict[str, Any]:
        """
        获取输出配置
        
        调整（2026-03-12）：
        - max_events: 8→12，保留更多优质部委级政策
        - importance_threshold: 7→6，覆盖更多关注级事件
        """
        return config_manager.get("news_filter.output", {
            "max_events": 12,
            "min_events": 4,
            "importance_threshold": 6,
        })
    
    @property
    def importance_tags(self) -> Dict[str, str]:
        """获取重要性标签映射"""
        return config_manager.get("news_filter.importance_tags", {
            "critical": "重磅",
            "important": "重要",
            "notable": "关注",
            "noise": "噪音",
        })


# 全局配置实例
filter_config = NewsFilterConfig()


def is_noise_news(event: Dict[str, Any]) -> Tuple[bool, str]:
    """
    判断是否为噪音新闻
    
    配置来源：config/news_filter.yaml
    
    Returns:
        (is_noise, reason)
    """
    title = event.get("title", "").lower()
    summary = event.get("summary", "").lower()
    content = title + " " + summary
    sources = event.get("sources", [])
    
    # 检查无价值关键词（从配置读取）
    for keyword in filter_config.noise_keywords:
        if keyword in content:
            return True, f"含无价值关键词: {keyword}"
    
    # 检查来源（从配置读取）
    for source in sources:
        for pattern in filter_config.noise_source_patterns:
            if re.search(pattern, source):
                return True, f"来源为地方媒体: {source}"
    
    # 检查重复/跟进（从配置读取）
    for pattern in filter_config.duplicate_patterns:
        if re.search(pattern, title):
            return True, "重复/跟进新闻"
    
    return False, ""


# ==================== 第2步：重要性打分 ====================

class SourceLevel(Enum):
    """来源级别"""
    CENTRAL = 5      # 国务院/中央/全国性会议
    MINISTRY = 4     # 部委（工信部、发改委、财政部）
    EXCHANGE = 3     # 交易所/行业协会
    LOCAL = 1        # 地方/普通公司


class ImpactScope(Enum):
    """影响范围"""
    MARKET_WIDE = 5  # 影响全市场/全板块
    SECTOR = 3       # 影响1个大板块
    INDIVIDUAL = 1   # 只影响几只个股


class FundSensitivity(Enum):
    """资金敏感度"""
    DIRECT = 5       # 直接影响成本/利润/供需/监管
    INDIRECT = 3     # 中期影响行业逻辑
    LONG_TERM = 1    # 长期概念，短期不涨


# 关键词配置映射到枚举值
_SOURCE_LEVEL_MAP = {
    "central": SourceLevel.CENTRAL,
    "ministry": SourceLevel.MINISTRY,
    "exchange": SourceLevel.EXCHANGE,
}

_IMPACT_SCOPE_MAP = {
    "market_wide": ImpactScope.MARKET_WIDE,
    "sector": ImpactScope.SECTOR,
}

_FUND_SENSITIVITY_MAP = {
    "direct": FundSensitivity.DIRECT,
    "indirect": FundSensitivity.INDIRECT,
}


def _get_source_level_keywords() -> Dict[SourceLevel, List[str]]:
    """从配置获取来源级别关键词映射"""
    config_keywords = filter_config.source_level_keywords
    result = {}
    
    for key, enum_val in _SOURCE_LEVEL_MAP.items():
        keywords = config_keywords.get(key, [])
        if keywords:
            result[enum_val] = keywords
    
    # 如果配置为空，使用默认值
    if not result:
        result = {
            SourceLevel.CENTRAL: [
                "国务院", "中央", "全国人大", "全国政协", "中共中央",
                "总书记", "总理", "国家主席", "全国性会议",
                "中央经济工作会议", "政府工作报告", "两会",
            ],
            SourceLevel.MINISTRY: [
                "工信部", "发改委", "财政部", "商务部", "科技部",
                "央行", "银保监", "证监会", "外汇局",
                "国资委", "自然资源部", "生态环境部", "住建部",
                "交通运输部", "农业农村部", "海关总署", "税务总局",
                "市场监管总局", "统计局", "能源局",
            ],
            SourceLevel.EXCHANGE: [
                "上交所", "深交所", "北交所", "上期所", "大商所", "郑商所",
                "中金所", "行业协会", "中证", "沪深",
            ],
        }
    return result


def _get_impact_scope_keywords() -> Dict[ImpactScope, List[str]]:
    """从配置获取影响范围关键词映射"""
    config_keywords = filter_config.impact_scope_keywords
    result = {}
    
    for key, enum_val in _IMPACT_SCOPE_MAP.items():
        keywords = config_keywords.get(key, [])
        if keywords:
            result[enum_val] = keywords
    
    if not result:
        result = {
            ImpactScope.MARKET_WIDE: [
                "全市场", "A股", "大盘", "指数", "流动性", "降准", "降息",
                "利率", "汇率", "外资", "北向资金", "印花税", "交易规则",
                "两会", "政府工作报告", "中央经济工作会议", "全国",
            ],
            ImpactScope.SECTOR: [
                "行业", "板块", "产业链", "赛道", "概念股",
                "龙头", "领涨", "集体", "全线",
            ],
        }
    return result


def _get_fund_sensitivity_keywords() -> Dict[FundSensitivity, List[str]]:
    """从配置获取资金敏感关键词映射"""
    config_keywords = filter_config.fund_sensitivity_keywords
    result = {}
    
    for key, enum_val in _FUND_SENSITIVITY_MAP.items():
        keywords = config_keywords.get(key, [])
        if keywords:
            result[enum_val] = keywords
    
    if not result:
        result = {
            FundSensitivity.DIRECT: [
                "涨价", "降价", "成本", "利润", "毛利率", "净利润",
                "供需", "产能", "订单", "出货", "销量",
                "关税", "反倾销", "制裁", "禁令", "限制",
                "补贴", "退税", "减税", "免税",
                "涨停", "跌停", "暴涨", "暴跌", "大涨", "大跌",
                "刚性约束", "强制", "必须", "立即",
                "空袭", "战争", "冲突", "制裁", "封锁",
                "油价", "金价", "铜价", "粮价",
            ],
            FundSensitivity.INDIRECT: [
                "政策", "规划", "方案", "指导意见", "发展纲要",
                "标准", "规范", "认证", "考核", "办法",
                "支持", "鼓励", "推进", "加快", "深化",
                "新形态", "新模式", "新业态",
            ],
        }
    return result


@dataclass
class ImportanceScore:
    """重要性评分"""
    source_level: int = 1
    impact_scope: int = 1
    fund_sensitivity: int = 1
    
    @property
    def total(self) -> int:
        return self.source_level + self.impact_scope + self.fund_sensitivity
    
    @property
    def importance_tag(self) -> str:
        """
        根据总分返回重要性标签（4档位）
        
        阈值标准（2026-03-12优化）：
        - ≥10分 = 重磅（国家级政策/龙头业绩超预期/全市场影响）
        - 8-9分 = 重要（部委级产业政策/细分赛道龙头）
        - 6-7分 = 关注（监管政策/一般公司/板块级影响）
        - ≤5分 = 一般（地方政策/小公司）
        """
        tags = filter_config.importance_tags
        if self.total >= 10:
            return tags.get("critical", "重磅")
        elif self.total >= 8:
            return tags.get("important", "重要")  # 新增"中高"档位
        elif self.total >= 6:
            return tags.get("notable", "关注")
        else:
            return "一般"
    
    @property
    def importance_level(self) -> str:
        """返回对应的 EventImportance 枚举值（用于 ReportItem）"""
        if self.total >= 10:
            return "high"
        elif self.total >= 8:
            return "medium_high"  # 新增档位
        elif self.total >= 6:
            return "medium"
        else:
            return "low"
    
    def is_keep(self) -> bool:
        """是否保留（从配置读取阈值）"""
        threshold = filter_config.output_config.get("importance_threshold", 6)
        return self.total >= threshold


def score_importance(event: Dict[str, Any]) -> ImportanceScore:
    """
    计算事件重要性评分
    
    配置来源：config/news_filter.yaml
    
    Args:
        event: 事件数据
        
    Returns:
        ImportanceScore
    """
    title = event.get("title", "")
    summary = event.get("summary", "")
    content = title + " " + summary
    
    score = ImportanceScore()
    
    # 1. 来源级别打分（从配置读取）
    source_level_keywords = _get_source_level_keywords()
    for level, keywords in source_level_keywords.items():
        for kw in keywords:
            if kw in content:
                score.source_level = max(score.source_level, level.value)
                break
    
    # 2. 影响范围打分（从配置读取）
    impact_scope_keywords = _get_impact_scope_keywords()
    for scope, keywords in impact_scope_keywords.items():
        for kw in keywords:
            if kw in content:
                score.impact_scope = max(score.impact_scope, scope.value)
                break
    
    # 3. 资金敏感度打分（从配置读取）
    fund_sensitivity_keywords = _get_fund_sensitivity_keywords()
    for sensitivity, keywords in fund_sensitivity_keywords.items():
        for kw in keywords:
            if kw in content:
                score.fund_sensitivity = max(score.fund_sensitivity, sensitivity.value)
                break
    
    # 新闻数量加成
    news_count = event.get("news_count", 1)
    if news_count >= 5:
        score.impact_scope = max(score.impact_scope, 3)
    
    return score


# ==================== 第3步：同类聚类 ====================

# 默认聚类池（当配置为空时使用）
_DEFAULT_CLUSTER_POOLS = {
    "两会政策": {
        "keywords": ["两会", "全国人大", "全国政协", "政府工作报告", "人大代表", "政协委员", "委员通道", "代表通道"],
        "sectors": ["政策主线", "科技", "消费", "制造"],
    },
    "能源地缘": {
        "keywords": ["石油", "油价", "原油", "中东", "伊朗", "俄罗斯", "OPEC", "天然气", "煤炭", "能源", "空袭", "战争"],
        "sectors": ["油气", "煤炭", "能源", "军工", "航空", "油运"],
    },
    "电力能源": {
        "keywords": ["电力", "电网", "电价", "光伏", "风电", "储能", "新能源", "电力市场"],
        "sectors": ["电力", "光伏", "风电", "储能", "电网"],
    },
    "水务环保": {
        "keywords": ["水利", "节水", "水资源", "水务", "污水", "环保", "碳中和", "碳排放", "绿色"],
        "sectors": ["智慧水务", "水利", "水处理", "环保"],
    },
    "科技制造": {
        "keywords": ["工业互联网", "智能制造", "工业软件", "自动化", "机器人", "数控", "智能经济"],
        "sectors": ["工业软件", "工业互联网", "自动化", "机器人"],
    },
    "汽车产业链": {
        "keywords": ["汽车", "新能源汽车", "智能驾驶", "自动驾驶", "车联网", "充电桩", "特斯拉"],
        "sectors": ["汽车", "智能驾驶", "充电桩", "动力电池"],
    },
    "半导体芯片": {
        "keywords": ["芯片", "半导体", "晶圆", "光刻", "封装", "存储", "GPU", "AI芯片"],
        "sectors": ["芯片", "半导体", "存储", "封装测试"],
    },
    "AI人工智能": {
        "keywords": ["人工智能", "AI", "大模型", "ChatGPT", "机器学习", "深度学习", "算力", "智能经济"],
        "sectors": ["AI", "算力", "数据中心", "云计算"],
    },
    "消费电子": {
        "keywords": ["手机", "消费电子", "苹果", "华为", "OPPO", "小米", "vivo", "折叠屏"],
        "sectors": ["消费电子", "手机产业链", "面板"],
    },
    "市场监管": {
        "keywords": ["交易规则", "期货", "期权", "保证金", "涨跌停", "限额", "监管"],
        "sectors": ["期货", "券商"],
    },
    "农业粮食": {
        "keywords": ["粮食", "农业", "种业", "化肥", "农药", "生猪", "养殖"],
        "sectors": ["农业", "种业", "化肥", "养殖"],
    },
    "医药医疗": {
        "keywords": ["医药", "医疗", "创新药", "仿制药", "医保", "集采", "医疗器械"],
        "sectors": ["医药", "创新药", "医疗器械", "CXO"],
    },
    "消费零售": {
        "keywords": ["消费", "零售", "电商", "白酒", "食品", "家电", "旅游", "增收"],
        "sectors": ["消费", "白酒", "食品", "家电", "旅游"],
    },
    "金融地产": {
        "keywords": ["银行", "保险", "券商", "地产", "房地产", "楼市", "信贷"],
        "sectors": ["银行", "保险", "券商", "地产"],
    },
    "央企改革": {
        "keywords": ["央企", "国企", "国资", "混改", "重组", "整合"],
        "sectors": ["央企改革", "国企改革"],
    },
}


def _get_cluster_pools() -> Dict[str, Dict[str, Any]]:
    """从配置获取聚类池"""
    pools = filter_config.cluster_pools
    return pools if pools else _DEFAULT_CLUSTER_POOLS


def get_cluster_key(event: Dict[str, Any]) -> Optional[str]:
    """
    获取事件所属的聚类池
    
    配置来源：config/news_filter.yaml
    
    Returns:
        聚类池名称，或 None
    """
    title = event.get("title", "")
    summary = event.get("summary", "")
    content = title + " " + summary
    
    cluster_pools = _get_cluster_pools()
    for cluster_name, cluster_info in cluster_pools.items():
        for keyword in cluster_info.get("keywords", []):
            if keyword in content:
                return cluster_name
    
    return None


def get_cluster_sectors(cluster_key: str) -> List[str]:
    """获取聚类池对应的板块（从配置读取）"""
    cluster_pools = _get_cluster_pools()
    if cluster_key in cluster_pools:
        return cluster_pools[cluster_key].get("sectors", [])
    return []


@dataclass
class FilteredEvent:
    """筛选后的事件"""
    event_id: str
    title: str
    summary: str
    importance_tag: str  # 重磅/重要/关注
    score: ImportanceScore
    cluster_key: Optional[str] = None
    sectors: List[str] = field(default_factory=list)
    news_count: int = 1
    raw_event: Dict[str, Any] = field(default_factory=dict)
    merged_events: List[Dict[str, Any]] = field(default_factory=list)


class NewsFilter:
    """
    新闻筛选器
    
    实现4步硬规则筛选，将大量新闻精简为6-8条核心大事。
    
    配置来源：config/news_filter.yaml
    
    Example:
        filter = NewsFilter()
        filtered = filter.filter_events(events)
        # filtered 包含6-8条核心事件
    """
    
    def __init__(
        self,
        max_output: Optional[int] = None,
        min_score: Optional[int] = None,
    ):
        # 从配置读取默认值
        output_config = filter_config.output_config
        self.max_output = max_output or output_config.get("max_events", 8)
        self.min_score = min_score or output_config.get("importance_threshold", 7)
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    def filter_events(
        self,
        events: List[Dict[str, Any]],
        trace_id: Optional[str] = None,
    ) -> List[FilteredEvent]:
        """
        执行4步筛选
        
        Args:
            events: 原始事件列表
            trace_id: 追踪ID
            
        Returns:
            筛选后的事件列表 (6-8条)
        """
        self.logger.info(f"[{trace_id}] 开始筛选 {len(events)} 条事件")
        
        # 第1步：降噪
        step1_events = self._step1_denoise(events, trace_id)
        self.logger.info(f"[{trace_id}] 第1步降噪: {len(events)} → {len(step1_events)}")
        
        # 第2步：打分
        step2_events = self._step2_score(step1_events, trace_id)
        self.logger.info(f"[{trace_id}] 第2步打分: {len(step1_events)} → {len(step2_events)}")
        
        # 第3步：聚类
        step3_events = self._step3_cluster(step2_events, trace_id)
        self.logger.info(f"[{trace_id}] 第3步聚类: {len(step2_events)} → {len(step3_events)}")
        
        # 第4步：截断
        step4_events = self._step4_truncate(step3_events, trace_id)
        self.logger.info(f"[{trace_id}] 第4步截断: {len(step3_events)} → {len(step4_events)}")
        
        return step4_events
    
    def _step1_denoise(
        self,
        events: List[Dict[str, Any]],
        trace_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """第1步：极速降噪"""
        result = []
        
        for event in events:
            is_noise, reason = is_noise_news(event)
            if is_noise:
                self.logger.debug(f"[{trace_id}] 过滤噪音: {event.get('title', '')[:30]} - {reason}")
                continue
            result.append(event)
        
        return result
    
    def _step2_score(
        self,
        events: List[Dict[str, Any]],
        trace_id: Optional[str] = None,
    ) -> List[FilteredEvent]:
        """第2步：重要性打分"""
        result = []
        
        for event in events:
            score = score_importance(event)
            
            # 评分≥9分才保留
            if not score.is_keep():
                self.logger.debug(
                    f"[{trace_id}] 低分过滤({score.total}): {event.get('title', '')[:30]}"
                )
                continue
            
            # 获取聚类键和板块
            cluster_key = get_cluster_key(event)
            sectors = get_cluster_sectors(cluster_key) if cluster_key else []
            
            filtered = FilteredEvent(
                event_id=event.get("id", ""),
                title=event.get("title", ""),
                summary=event.get("summary", ""),
                importance_tag=score.importance_tag,
                score=score,
                cluster_key=cluster_key,
                sectors=sectors,
                news_count=event.get("news_count", 1),
                raw_event=event,
            )
            result.append(filtered)
        
        # 按分数排序
        result.sort(key=lambda x: x.score.total, reverse=True)
        
        return result
    
    def _step3_cluster(
        self,
        events: List[FilteredEvent],
        trace_id: Optional[str] = None,
    ) -> List[FilteredEvent]:
        """第3步：同类聚类合并"""
        # 按聚类键分组
        clusters: Dict[str, List[FilteredEvent]] = {}
        no_cluster: List[FilteredEvent] = []
        
        for event in events:
            if event.cluster_key:
                if event.cluster_key not in clusters:
                    clusters[event.cluster_key] = []
                clusters[event.cluster_key].append(event)
            else:
                no_cluster.append(event)
        
        result = []
        
        # 每个聚类只保留分数最高的那条，其他作为补充
        for cluster_key, cluster_events in clusters.items():
            if not cluster_events:
                continue
            
            # 按分数排序，取最高分
            cluster_events.sort(key=lambda x: x.score.total, reverse=True)
            main_event = cluster_events[0]
            
            # 合并其他事件作为补充
            if len(cluster_events) > 1:
                main_event.merged_events = [e.raw_event for e in cluster_events[1:]]
                # 累加新闻数
                main_event.news_count += sum(e.news_count for e in cluster_events[1:])
            
            result.append(main_event)
            self.logger.debug(
                f"[{trace_id}] 聚类[{cluster_key}]: {len(cluster_events)} → 1 (主: {main_event.title[:30]})"
            )
        
        # 加上无聚类的事件
        result.extend(no_cluster)
        
        # 按分数重新排序
        result.sort(key=lambda x: x.score.total, reverse=True)
        
        return result
    
    def _step4_truncate(
        self,
        events: List[FilteredEvent],
        trace_id: Optional[str] = None,
    ) -> List[FilteredEvent]:
        """第4步：截断到最大数量"""
        return events[:self.max_output]
    
    def format_output(
        self,
        events: List[FilteredEvent],
    ) -> str:
        """
        格式化输出（4个核心信息）
        
        格式:
        【重磅】事件主体
        影响：核心影响
        板块：对应板块
        """
        lines = []
        
        for event in events:
            # 重要性标签
            tag = event.importance_tag
            
            # 事件标题
            title = event.title
            
            # 影响（从摘要中提取或使用默认）
            impact = event.summary[:50] if event.summary else "待分析"
            
            # 板块
            sectors = "、".join(event.sectors[:4]) if event.sectors else "综合"
            
            lines.append(f"【{tag}】{title}")
            lines.append(f"影响：{impact}")
            lines.append(f"板块：{sectors}")
            lines.append("")
        
        return "\n".join(lines)


# 全局实例
news_filter = NewsFilter()
