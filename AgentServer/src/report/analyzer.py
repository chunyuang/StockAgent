"""
事件分析器

使用 LLM 对聚合后的事件进行：
1. 4步硬规则筛选（降噪→打分→聚类→截断）
2. 重要性评估（3维度量化打分）
3. 摘要生成
4. 分类汇总
5. 核心影响反复述检测
"""

import logging
import json
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from .types import (
    ReportItem,
    ReportSection,
    ReportCategory,
    EventImportance,
    SECTION_TITLES,
)
from .news_filter import NewsFilter, FilteredEvent, news_filter


logger = logging.getLogger(__name__)


def calculate_similarity(text1: str, text2: str) -> float:
    """计算两个文本的相似度 (0-1)"""
    if not text1 or not text2:
        return 0.0
    return SequenceMatcher(None, text1.lower(), text2.lower()).ratio()


# ==================== 标题-板块映射配置访问器 ====================
# 映射数据存储在 config/news_filter.yaml 中，支持热更新
# 修改配置后调用 config_manager.reload() 即可生效

from src.config import config_manager


def get_title_sector_map() -> Dict[str, List[str]]:
    """
    获取标题-板块映射（从配置读取，支持热更新）
    
    配置路径：config/news_filter.yaml -> title_sector_map
    """
    return config_manager.get("news_filter.title_sector_map", {})


def get_sector_synonyms() -> Dict[str, str]:
    """
    获取板块同义词映射（从配置读取，支持热更新）
    
    配置路径：config/news_filter.yaml -> sector_synonyms
    """
    return config_manager.get("news_filter.sector_synonyms", {})


def _normalize_sector(sector: str) -> str:
    """标准化板块名称（统一命名）"""
    sector_lower = sector.lower().strip()
    # 检查同义词映射（从配置读取）
    synonyms = get_sector_synonyms()
    for syn, std in synonyms.items():
        if syn.lower() in sector_lower or sector_lower in syn.lower():
            return std
    return sector


def _fuzzy_match_sector(sector: str, expected_sectors: set) -> bool:
    """
    模糊匹配板块（语义相似度≥70%判定为匹配）
    
    例如："电力设备" 匹配 "电力"，"节水" 匹配 "节水设备"
    """
    sector_lower = sector.lower()
    for expected in expected_sectors:
        expected_lower = expected.lower()
        # 完全包含
        if expected_lower in sector_lower or sector_lower in expected_lower:
            return True
        # 计算相似度
        similarity = calculate_similarity(sector_lower, expected_lower)
        if similarity >= 0.7:
            return True
    return False


def validate_and_fix_sectors(
    title: str, 
    llm_sectors: List[str], 
    impact: str = ""
) -> Tuple[List[str], bool, str]:
    """
    三步校验并修复 LLM 返回的板块
    
    步骤1：模糊匹配判定（语义相似度≥70%即匹配）
    步骤2：分层修正（完全错配/部分匹配/完全匹配）
    步骤3：二次校验（结合impact补充核心板块）
    
    Args:
        title: 事件标题
        llm_sectors: LLM 返回的板块列表
        impact: LLM 返回的核心影响（用于二次校验）
        
    Returns:
        (修正后的板块列表, 是否进行了修正, 修正原因)
    """
    if not title:
        return llm_sectors, False, ""
    
    title_lower = title.lower()
    
    # 从配置获取映射（支持热更新）
    title_sector_map = get_title_sector_map()
    
    # 检测标题中的核心关键词（多关键词叠加）
    detected_keywords = []
    for keyword in title_sector_map:
        if keyword in title_lower:
            detected_keywords.append(keyword)
    
    if not detected_keywords:
        return llm_sectors, False, ""
    
    # 获取标题对应的核心板块（多关键词取并集，按热度排序）
    expected_sectors_list = []
    for kw in detected_keywords:
        for sector in title_sector_map[kw]:
            if sector not in expected_sectors_list:
                expected_sectors_list.append(sector)
    expected_sectors = set(expected_sectors_list[:5])  # 保留前5个高热度板块
    
    if not llm_sectors:
        # LLM 未返回板块，直接使用预期板块
        return list(expected_sectors)[:3], True, "LLM未返回板块，使用标题预期板块"
    
    # ========== 步骤1：模糊匹配判定 ==========
    matched_sectors = []  # 匹配的板块
    unmatched_sectors = []  # 不匹配的板块
    
    for sector in llm_sectors:
        normalized = _normalize_sector(sector)
        if _fuzzy_match_sector(normalized, expected_sectors):
            matched_sectors.append(normalized)
        else:
            unmatched_sectors.append(sector)
    
    match_rate = len(matched_sectors) / len(llm_sectors)
    
    # ========== 步骤2：分层修正 ==========
    final_sectors = []
    was_fixed = False
    fix_reason = ""
    
    if match_rate == 0:
        # 完全错配：直接替换为预期板块
        final_sectors = list(expected_sectors)[:3]
        was_fixed = True
        fix_reason = f"完全错配(0%)，替换为预期板块"
    
    elif match_rate < 1.0:
        # 部分匹配：保留匹配的，移除错误的，补充预期板块
        final_sectors = matched_sectors.copy()
        # 补充预期板块至3个
        for sector in expected_sectors_list:
            if sector not in final_sectors and len(final_sectors) < 3:
                final_sectors.append(sector)
        was_fixed = True
        fix_reason = f"部分匹配({match_rate:.0%})，移除{unmatched_sectors}，补充预期板块"
    
    else:
        # 完全匹配：不修正
        final_sectors = [_normalize_sector(s) for s in llm_sectors]
        was_fixed = False
    
    # ========== 步骤3：二次校验（结合impact） ==========
    if impact:
        impact_lower = impact.lower()
        # 检测 impact 中是否提及额外的核心概念
        impact_keywords = []
        for keyword in title_sector_map:
            if keyword in impact_lower and keyword not in title_lower:
                impact_keywords.append(keyword)
        
        # 如果 impact 中有新的核心概念，补充对应板块
        if impact_keywords:
            for kw in impact_keywords[:2]:  # 最多补充2个
                for sector in title_sector_map[kw][:1]:  # 每个关键词取1个核心板块
                    if sector not in final_sectors:
                        final_sectors.append(sector)
                        if not was_fixed:
                            was_fixed = True
                            fix_reason = f"二次校验：impact中检测到{kw}，补充{sector}"
    
    # 去重并限制数量
    seen = set()
    deduplicated = []
    for s in final_sectors:
        if s not in seen:
            seen.add(s)
            deduplicated.append(s)
    final_sectors = deduplicated[:4]  # 最多保留4个板块
    
    return final_sectors, was_fixed, fix_reason


# ==================== 政策级别与Impact质量配置访问器 ====================
# 所有关键词配置存储在 config/news_filter.yaml 中，支持热更新
# 修改配置后调用 config_manager.reload() 即可生效


def get_policy_level_keywords() -> Dict[str, List[str]]:
    """
    获取政策级别关键词（从配置读取）
    
    配置路径：config/news_filter.yaml -> policy_level_keywords
    返回：{"national": [...], "ministry": [...], "regulatory": [...], ...}
    """
    return config_manager.get("news_filter.policy_level_keywords", {
        "national": ["国务院", "中央", "全国人大"],
        "ministry": ["工信部", "发改委"],
        "regulatory": ["证监会"],
        "local": ["省政府", "市政府"],
        "company": ["公司", "业绩"],
        "international": ["美国", "欧洲"],
    })


def get_impact_quality_keywords() -> Dict[str, List[str]]:
    """
    获取Impact质量检测关键词（从配置读取）
    
    配置路径：config/news_filter.yaml -> impact_quality
    返回：{"action_only_patterns": [...], "analysis_keywords": [...]}
    """
    return config_manager.get("news_filter.impact_quality", {
        "action_only_patterns": ["印发", "发布", "出台"],
        "analysis_keywords": ["利好", "利空", "受益"],
    })


class PolicyLevel:
    """政策级别枚举"""
    NATIONAL = "national"      # 国家级（强制触发）
    MINISTRY = "ministry"      # 部委级（低质量时触发）
    REGULATORY = "regulatory"  # 监管/交易所级（低质量时触发）
    LOCAL = "local"           # 地方级（仅核心政策触发）
    COMPANY = "company"       # 公司级（低质量时触发）
    INTERNATIONAL = "international"  # 国际级（低质量时触发）
    OTHER = "other"           # 其他


def get_policy_level(title: str) -> PolicyLevel:
    """
    判断事件的政策级别（从配置读取关键词，支持热更新）
    
    Returns:
        PolicyLevel: 政策级别
    """
    if not title:
        return PolicyLevel.OTHER
    
    # 从配置获取关键词（支持热更新）
    policy_keywords = get_policy_level_keywords()
    
    # 国家级
    for kw in policy_keywords.get("national", []):
        if kw in title:
            return PolicyLevel.NATIONAL
    
    # 部委级
    for kw in policy_keywords.get("ministry", []):
        if kw in title:
            return PolicyLevel.MINISTRY
    
    # 监管/交易所级
    for kw in policy_keywords.get("regulatory", []):
        if kw in title:
            return PolicyLevel.REGULATORY
    
    # 地方级
    for kw in policy_keywords.get("local", []):
        if kw in title:
            return PolicyLevel.LOCAL
    
    # 公司级
    for kw in policy_keywords.get("company", []):
        if kw in title:
            return PolicyLevel.COMPANY
    
    # 国际级
    for kw in policy_keywords.get("international", []):
        if kw in title:
            return PolicyLevel.INTERNATIONAL
    
    return PolicyLevel.OTHER


def is_ministry_level_policy(title: str) -> bool:
    """检测是否为部委级以上政策（兼容旧接口）"""
    level = get_policy_level(title)
    return level in [PolicyLevel.NATIONAL, PolicyLevel.MINISTRY, PolicyLevel.REGULATORY]


def is_low_quality_impact(
    impact: str, 
    title: str, 
    policy_level: PolicyLevel = None
) -> Tuple[bool, str]:
    """
    检测 impact 是否为低质量（三标准判定）
    
    低质量三标准（需同时满足）：
    1. 仅含动作类词汇（印发、发布等），无影响/逻辑/结果
    2. 与标题文本相似度≥70%（复述标题）
    3. 未提及对A股板块/公司的具体影响
    
    Args:
        impact: 核心影响文本
        title: 事件标题
        policy_level: 政策级别（可选）
        
    Returns:
        (是否低质量, 低质量原因)
    """
    if not impact:
        return True, "impact为空"
    
    reasons = []
    
    # 从配置获取关键词（支持热更新）
    quality_keywords = get_impact_quality_keywords()
    action_patterns = quality_keywords.get("action_only_patterns", [])
    analysis_keywords = quality_keywords.get("analysis_keywords", [])
    
    # 标准1：仅含动作类词汇
    action_count = sum(1 for p in action_patterns if p in impact)
    has_analysis = any(kw in impact for kw in analysis_keywords)
    
    if action_count >= 2 and not has_analysis:
        reasons.append(f"仅含动作词({action_count}个)无分析")
    
    # 标准2：与标题相似度≥70%（复述标题）
    similarity = calculate_similarity(impact, title)
    if similarity >= 0.7:
        reasons.append(f"与标题相似度{similarity:.0%}")
    elif similarity >= 0.5:
        # 50-70%也记录，但不单独判定为低质量
        pass
    
    # 标准3：未提及对A股板块的具体影响
    sector_mentioned = False
    # 检查是否提及任何板块关键词（从配置读取）
    title_sector_map = get_title_sector_map()
    for keyword in title_sector_map:
        if keyword in impact.lower():
            sector_mentioned = True
            break
    # 也检查是否有"XX板块"的表述
    if "板块" in impact:
        sector_mentioned = True
    
    if not sector_mentioned and not has_analysis:
        reasons.append("未提及板块影响")
    
    # 判定：满足2个及以上标准 = 低质量
    is_low = len(reasons) >= 2
    
    # 特殊规则：国家级政策更严格（满足1个标准即低质量）
    if policy_level == PolicyLevel.NATIONAL and len(reasons) >= 1:
        is_low = True
    
    return is_low, "；".join(reasons) if reasons else ""


def should_regenerate_impact(
    title: str,
    impact: str,
    policy_level: PolicyLevel = None
) -> Tuple[bool, str]:
    """
    判断是否需要重生成 impact（分级触发规则）
    
    触发规则：
    - 国家级政策：强制触发（无论impact质量）
    - 部委级/监管级政策：低质量时触发
    - 公司/国际事件：低质量时触发
    - 地方级/其他：仅严重低质量时触发
    
    Returns:
        (是否需要重生成, 原因)
    """
    if policy_level is None:
        policy_level = get_policy_level(title)
    
    is_low, low_reason = is_low_quality_impact(impact, title, policy_level)
    
    # 国家级政策：强制触发
    if policy_level == PolicyLevel.NATIONAL:
        if is_low:
            return True, f"国家级政策+低质量({low_reason})"
        # 即使不低质量，也检查是否有实质性分析
        has_substantial = any(kw in impact for kw in ["利好", "利空", "受益", "影响"])
        if not has_substantial:
            return True, "国家级政策需强化影响分析"
        return False, ""
    
    # 部委级/监管级：低质量时触发
    if policy_level in [PolicyLevel.MINISTRY, PolicyLevel.REGULATORY]:
        if is_low:
            return True, f"部委级政策+低质量({low_reason})"
        return False, ""
    
    # 公司/国际事件：低质量时触发
    if policy_level in [PolicyLevel.COMPANY, PolicyLevel.INTERNATIONAL]:
        if is_low:
            return True, f"事件级别+低质量({low_reason})"
        return False, ""
    
    # 地方级/其他：仅严重低质量时触发（相似度≥80%）
    similarity = calculate_similarity(impact, title)
    if similarity >= 0.8:
        return True, f"严重复述标题({similarity:.0%})"
    
    return False, ""


class EventAnalyzer:
    """
    事件分析器
    
    使用 LLM 服务分析事件重要性和生成摘要。
    
    Example:
        analyzer = EventAnalyzer()
        items = await analyzer.analyze_importance(events)
        summary = await analyzer.generate_section_summary(items, "宏观政策")
    """
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._llm_service = None
    
    async def _get_llm_service(self):
        """延迟获取 LLM 服务"""
        if self._llm_service is None:
            from src.llm import llm_service
            if not llm_service._initialized:
                await llm_service.initialize()
            self._llm_service = llm_service
        return self._llm_service
    
    async def analyze_importance(
        self,
        events: List[Dict[str, Any]],
        trace_id: Optional[str] = None,
        use_filter: bool = True,
    ) -> List[ReportItem]:
        """
        分析事件重要性（4步硬规则筛选 + LLM打分）
        
        Args:
            events: 事件列表 (从 news_events 获取)
            trace_id: 追踪ID
            use_filter: 是否使用4步筛选（默认True）
            
        Returns:
            带重要性评估的 ReportItem 列表（精简后6-8条）
        """
        if not events:
            return []
        
        self.logger.info(f"[{trace_id}] 收到 {len(events)} 条事件，开始分析...")
        
        # ==================== 4步硬规则筛选 ====================
        if use_filter:
            filtered_events = news_filter.filter_events(events, trace_id)
            self.logger.info(
                f"[{trace_id}] 4步筛选: {len(events)} → {len(filtered_events)} 条核心事件"
            )
        else:
            # 不使用筛选，直接转换
            filtered_events = self._events_to_filtered(events)
        
        if not filtered_events:
            self.logger.warning(f"[{trace_id}] 筛选后无事件")
            return []
        
        # ==================== 转换为 ReportItem ====================
        items = []
        for fe in filtered_events:
            # 映射重要性标签
            if fe.importance_tag == "重磅":
                importance = EventImportance.HIGH
            elif fe.importance_tag in ("重要", "关注"):
                importance = EventImportance.MEDIUM
            else:
                importance = EventImportance.LOW
            
            # 从原始事件中提取 LLM 增强字段
            raw = fe.raw_event
            
            # 板块：优先使用 LLM 增强的 related_sectors，否则用规则筛选的
            sectors = raw.get("related_sectors") or fe.sectors or []
            
            # 情绪：从 LLM 增强结果获取
            sentiment = raw.get("sentiment") or "neutral"
            
            # 影响范围（确保不为 None）
            impact_scope = raw.get("impact_scope") or ""
            
            # 政策级别（确保不为 None）
            policy_level = raw.get("policy_level") or ""
            
            # 核心影响说明（优先用 LLM 增强的摘要）
            impact = raw.get("enriched_summary") or fe.summary or ""
            
            item = ReportItem(
                event_id=fe.event_id,
                title=fe.title,
                summary=fe.summary,
                importance=importance,
                news_count=fe.news_count,
                ts_codes=raw.get("ts_codes", []),
                event_time=raw.get("first_report_time"),
                # LLM 增强字段
                impact=impact,
                sectors=sectors,
                sentiment=sentiment,
                policy_level=policy_level,
                impact_scope=impact_scope,
                raw_event=raw,
            )
            
            # 存储额外信息（兼容旧代码）
            item.raw_event["_importance_tag"] = fe.importance_tag
            item.raw_event["_score"] = fe.score.total
            item.raw_event["_sectors"] = sectors
            item.raw_event["_cluster_key"] = fe.cluster_key
            item.raw_event["_impact"] = impact
            
            items.append(item)
        
        # ==================== LLM 增强分析（核心影响解读）====================
        # 始终执行 LLM 增强，这是生成有价值核心影响的关键步骤
        self.logger.info(f"[{trace_id}] 开始 LLM 核心影响解读，共 {len(items)} 条事件")
        
        try:
            llm = await self._get_llm_service()
            
            # 构建事件 JSON（包含正文内容，供 LLM 深度解读）
            events_for_llm = []
            for item in items[:20]:  # 最多20条给LLM
                # 获取正文内容（从原始事件或关联新闻）
                content = ""
                if item.raw_event:
                    # 优先使用 enriched_summary，其次用 summary，最后用主新闻内容
                    content = (
                        item.raw_event.get("enriched_summary", "") or
                        item.raw_event.get("summary", "") or
                        item.raw_event.get("primary_news_content", "") or
                        ""
                    )
                
                events_for_llm.append({
                    "event_id": item.event_id,
                    "title": item.title,
                    "content": content[:500] if content else item.summary[:200],  # 正文内容
                    "news_count": item.news_count,
                })
            
            events_json = json.dumps(events_for_llm, ensure_ascii=False, indent=2)
            
            # 打印发送给 LLM 的内容（调试用）
            self.logger.info(f"[{trace_id}] 发送给 LLM 的事件内容:")
            for evt in events_for_llm[:3]:  # 只打印前3条
                self.logger.info(f"  - 标题: {evt['title'][:50]}")
                self.logger.info(f"    正文: {evt['content'][:100]}...")
            if len(events_for_llm) > 3:
                self.logger.info(f"  ... 还有 {len(events_for_llm) - 3} 条")
            
            # 使用模板调用
            result = await llm.invoke_and_parse(
                "importance_assess",
                events_json=events_json,
            )
            
            # 解析结果
            if result and "results" in result:
                importance_map, extra_info = self._parse_importance_results_v2(result["results"])
                
                # 需要重生成 impact 的事件
                items_need_regenerate = []
                
                # 更新 items
                for item in items:
                    if item.event_id in importance_map:
                        item.importance = importance_map[item.event_id]
                    if item.event_id in extra_info:
                        info = extra_info[item.event_id]
                        # 更新 ReportItem 字段
                        if info.get("impact"):
                            item.impact = info["impact"]
                        if info.get("sectors"):
                            item.sectors = info["sectors"]
                        if info.get("sentiment"):
                            item.sentiment = info["sentiment"]
                        
                        # 三步校验板块匹配（防止电力政策被错配为AI板块）
                        if item.sectors:
                            corrected_sectors, was_fixed, fix_reason = validate_and_fix_sectors(
                                item.title, item.sectors, item.impact
                            )
                            if was_fixed:
                                self.logger.warning(
                                    f"[{trace_id}] 板块修正: {item.title[:30]} | "
                                    f"原: {item.sectors} → 修正: {corrected_sectors} | {fix_reason}"
                                )
                                item.sectors = corrected_sectors
                        
                        # 检测 impact 质量并决定是否重生成（分级触发规则）
                        policy_level = get_policy_level(item.title)
                        need_regen, regen_reason = should_regenerate_impact(
                            item.title, item.impact, policy_level
                        )
                        
                        if need_regen:
                            self.logger.warning(
                                f"[{trace_id}] Impact需重生成: {item.title[:30]} | "
                                f"级别: {policy_level} | 原因: {regen_reason}"
                            )
                            items_need_regenerate.append(item)
                        
                        # 兼容旧代码
                        item.raw_event["_impact"] = item.impact
                        item.raw_event["_sectors"] = item.sectors
                        item.raw_event["_llm_score"] = info.get("total", 0)
                
                # 对需要重生成的事件重新生成 impact
                if items_need_regenerate:
                    self.logger.info(f"[{trace_id}] 重生成 {len(items_need_regenerate)} 个低质量 impact")
                    await self._regenerate_impacts(items_need_regenerate, llm, trace_id)
            
            self.logger.info(f"[{trace_id}] LLM增强分析完成: {len(items)} events")
            
        except Exception as e:
            self.logger.error(f"[{trace_id}] LLM importance analysis failed: {e}")
            # 已经有规则打分，不需要降级
        
        return items
    
    async def _regenerate_impacts(
        self,
        items: List[ReportItem],
        llm,
        trace_id: Optional[str] = None,
    ) -> None:
        """
        重新生成与标题相似度过高的核心影响
        
        使用极简指令，强制 LLM 基于正文生成不复述标题的影响说明
        """
        for item in items:
            try:
                # 获取正文内容
                content = ""
                if item.raw_event:
                    content = (
                        item.raw_event.get("enriched_summary", "") or
                        item.raw_event.get("summary", "") or
                        item.raw_event.get("primary_news_content", "") or
                        ""
                    )
                
                if not content:
                    continue
                
                # 使用极简指令重新生成
                prompt = f"""基于以下新闻正文，分析该事件对A股的具体核心影响。

【强制要求】
- 禁止复述标题！
- 必须体现因果逻辑：XX措施 → XX结果 → 利好/利空XX板块
- 一句话说明，不超过40字

标题：{item.title}
正文：{content[:800]}

核心影响："""

                messages = [{"role": "user", "content": prompt}]
                result = await llm.chat(messages, max_tokens=100, temperature=0.3)
                
                if result:
                    new_impact = result.strip()
                    # 再次检测相似度
                    new_similarity = calculate_similarity(new_impact, item.title)
                    if new_similarity < 0.6:
                        item.impact = new_impact
                        item.raw_event["_impact"] = new_impact
                        self.logger.info(f"[{trace_id}] 重生成 impact 成功: {item.title[:20]}...")
                    else:
                        self.logger.warning(f"[{trace_id}] 重生成仍相似({new_similarity:.0%}): {item.title[:20]}...")
                        
            except Exception as e:
                self.logger.error(f"[{trace_id}] 重生成 impact 失败: {e}")
    
    def _events_to_filtered(self, events: List[Dict[str, Any]]) -> List[FilteredEvent]:
        """将原始事件转换为 FilteredEvent（不进行筛选）"""
        from .news_filter import score_importance, get_cluster_key, get_cluster_sectors
        
        result = []
        for event in events:
            score = score_importance(event)
            cluster_key = get_cluster_key(event)
            sectors = get_cluster_sectors(cluster_key) if cluster_key else []
            
            fe = FilteredEvent(
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
            result.append(fe)
        
        return result
    
    def _rule_based_importance(self, items: List[ReportItem]) -> List[ReportItem]:
        """基于规则的重要性评估"""
        for item in items:
            # 规则1: 新闻数量多 = 重要
            if item.news_count >= 5:
                item.importance = EventImportance.HIGH
            elif item.news_count >= 3:
                item.importance = EventImportance.MEDIUM
            else:
                item.importance = EventImportance.LOW
            
            # 规则2: 关键词匹配
            keywords_high = ["央行", "降息", "加息", "降准", "涨停", "跌停", "重大", "紧急"]
            keywords_medium = ["政策", "利好", "利空", "发布", "公告"]
            
            title_lower = item.title.lower()
            for kw in keywords_high:
                if kw in title_lower:
                    item.importance = EventImportance.HIGH
                    break
            
            if item.importance != EventImportance.HIGH:
                for kw in keywords_medium:
                    if kw in title_lower:
                        item.importance = EventImportance.MEDIUM
                        break
        
        return items
    
    def _parse_importance_results(self, results: List[Dict]) -> Dict[str, EventImportance]:
        """解析重要性评估结果（旧版兼容）"""
        importance_map = {}
        
        for result in results:
            event_id = result.get("event_id", "")
            importance_str = result.get("importance", "medium").lower()
            
            if importance_str == "high":
                importance = EventImportance.HIGH
            elif importance_str == "low":
                importance = EventImportance.LOW
            else:
                importance = EventImportance.MEDIUM
            
            importance_map[event_id] = importance
        
        return importance_map
    
    def _parse_importance_results_v2(
        self, results: List[Dict]
    ) -> tuple[Dict[str, EventImportance], Dict[str, Dict]]:
        """
        解析重要性评估结果（V2版 - 3维度打分）
        
        Returns:
            (importance_map, extra_info_map)
        """
        importance_map = {}
        extra_info = {}
        
        for result in results:
            event_id = result.get("event_id", "")
            
            # 解析总分或标签
            total = result.get("total", 0)
            tag = result.get("tag", "").lower()
            
            # 根据总分或标签判断重要性
            if total >= 12 or tag == "重磅":
                importance = EventImportance.HIGH
            elif total >= 10 or tag in ("重要", "关注"):
                importance = EventImportance.MEDIUM
            else:
                importance = EventImportance.LOW
            
            importance_map[event_id] = importance
            
            # 提取额外信息
            extra_info[event_id] = {
                "source_score": result.get("source_score", 1),
                "scope_score": result.get("scope_score", 1),
                "fund_score": result.get("fund_score", 1),
                "total": total,
                "tag": result.get("tag", ""),
                "impact": result.get("impact", ""),
                "sectors": result.get("sectors", []),
                "sentiment": result.get("sentiment", "neutral"),
            }
        
        return importance_map, extra_info
    
    async def generate_section_summary(
        self,
        items: List[ReportItem],
        category: ReportCategory,
        trace_id: Optional[str] = None,
    ) -> str:
        """
        生成分类摘要
        
        Args:
            items: 该分类下的事件列表
            category: 分类
            trace_id: 追踪ID
            
        Returns:
            摘要文本
        """
        if not items:
            return ""
        
        # 如果只有1-2条，不需要 LLM 汇总
        if len(items) <= 2:
            return items[0].title if items else ""
        
        try:
            llm = await self._get_llm_service()
            
            # 构建事件文本
            events_text = "\n".join([
                f"- {item.title}" + (f" ({item.news_count}条相关)" if item.news_count > 1 else "")
                for item in items[:10]  # 最多10条
            ])
            
            category_name = SECTION_TITLES.get(category, str(category))
            
            # 使用模板调用
            summary = await llm.invoke_template(
                "report_summary",
                category=category_name,
                events_text=events_text,
            )
            
            # 清理结果
            summary = summary.strip()
            if summary.startswith('"') and summary.endswith('"'):
                summary = summary[1:-1]
            
            return summary[:200]  # 限制长度
            
        except Exception as e:
            self.logger.error(f"[{trace_id}] Generate section summary failed: {e}")
            # 降级：返回第一条标题
            return items[0].title if items else ""
    
    async def generate_overview(
        self,
        sections: List[ReportSection],
        report_type: str = "早报",
        trace_id: Optional[str] = None,
    ) -> str:
        """
        生成报告总体概述
        
        Args:
            sections: 所有分节
            report_type: 报告类型 (早报/午报)
            trace_id: 追踪ID
            
        Returns:
            概述文本
        """
        if not sections:
            return "今日暂无重大财经事件。"
        
        # 提取各分类摘要
        summaries = {
            ReportCategory.MACRO: "暂无",
            ReportCategory.INTERNATIONAL: "暂无",
            ReportCategory.INDUSTRY: "暂无",
            ReportCategory.STOCK: "暂无",
            ReportCategory.HOT: "暂无",
        }
        
        # 收集各分类摘要
        for section in sections:
            if section.items:
                summaries[section.category] = section.summary or section.items[0].title
        
        # 收集核心板块
        sector_counts: dict = {}
        for section in sections:
            for item in section.items:
                sectors = item.raw_event.get("_sectors", []) or []
                for s in sectors:
                    sector_counts[s] = sector_counts.get(s, 0) + 1
        top_sectors = sorted(sector_counts.items(), key=lambda x: -x[1])[:5]
        top_sectors_str = "、".join([s[0] for s in top_sectors]) if top_sectors else "暂无明确板块"
        
        try:
            llm = await self._get_llm_service()
            
            # 使用模板调用
            overview = await llm.invoke_template(
                "report_overview",
                report_type=report_type,
                macro_summary=summaries[ReportCategory.MACRO],
                international_summary=summaries[ReportCategory.INTERNATIONAL],
                industry_summary=summaries[ReportCategory.INDUSTRY],
                stock_summary=summaries[ReportCategory.STOCK],
                hot_summary=summaries[ReportCategory.HOT],
                top_sectors=top_sectors_str,
            )
            
            return overview.strip()[:300]
            
        except Exception as e:
            self.logger.error(f"[{trace_id}] Generate overview failed: {e}")
            # 降级
            top_items = []
            for section in sections:
                if section.items:
                    top_items.append(section.items[0].title)
            return "今日要点: " + "; ".join(top_items[:3]) if top_items else ""
