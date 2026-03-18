"""
报告格式化器

将结构化报告转换为不同格式:
1. Markdown - 用于前端展示（完整版，包含核心影响、板块、情绪）
2. WeChat - 企业微信适配格式（精简版，突出关键信息）

每条事件展示：
1. 重要性标签（🔴重磅/🟡重要/⚪关注）
2. 事件标题
3. 核心影响（利好/利空谁）
4. 关联板块
5. 情绪标签（可选）
"""

from datetime import datetime
from typing import List, Dict
from collections import Counter

from .types import (
    Report,
    ReportSection,
    ReportItem,
    ReportType,
    ReportCategory,
    EventImportance,
    SECTION_TITLES,
    SECTION_ORDER,
    SENTIMENT_LABELS,
)


# 重要性标记（4档位）
IMPORTANCE_MARKS = {
    EventImportance.HIGH: "🔴",        # 重磅
    EventImportance.MEDIUM_HIGH: "🟠",  # 重要（新增中高档位）
    EventImportance.MEDIUM: "🟡",       # 关注
    EventImportance.LOW: "⚪",          # 一般
}

# 重要性标签（中文，4档位）
IMPORTANCE_TAGS = {
    EventImportance.HIGH: "重磅",
    EventImportance.MEDIUM_HIGH: "重要",  # 新增
    EventImportance.MEDIUM: "关注",
    EventImportance.LOW: "一般",
}

# 情绪 emoji
SENTIMENT_EMOJI = {
    "positive": "📈",
    "negative": "📉",
    "neutral": "➖",
}


class ReportFormatter:
    """
    报告格式化器
    
    Example:
        formatter = ReportFormatter()
        report.content_markdown = formatter.to_markdown(report)
        report.content_wechat = formatter.to_wechat(report)
    """
    
    def to_markdown(self, report: Report) -> str:
        """
        转换为 Markdown 格式（完整版）
        
        - 按分类整合事件
        - 展示核心影响、板块、情绪
        - 重要事件详细展开
        """
        lines = []
        
        # 标题
        lines.append(f"# {report.title}")
        lines.append("")
        
        # 发布时间（早报用盘前时间）
        if report.type == ReportType.MORNING:
            time_str = report.created_at.strftime("%Y-%m-%d") + " 08:30"
        else:
            time_str = report.created_at.strftime("%Y-%m-%d %H:%M")
        lines.append(f"> 发布时间: {time_str}")
        lines.append("")
        
        # 概述
        if report.overview:
            lines.append("## 📋 今日要点")
            lines.append("")
            lines.append(report.overview)
            lines.append("")
        
        # 核心机会提示
        if report.stats.top_sectors:
            sectors_str = "、".join(report.stats.top_sectors[:5])
            lines.append(f"**🎯 今日核心板块**: {sectors_str}")
            lines.append("")
        
        # 统计
        stats = report.stats
        lines.append(f"---")
        lines.append(f"*本期共收录 {stats.event_count} 条事件，其中重磅 {stats.high_importance_count} 条*")
        lines.append("")
        
        # 各分节（按优先级排序）
        sorted_sections = sorted(
            report.sections,
            key=lambda s: SECTION_ORDER.get(s.category, 99)
        )
        
        for section in sorted_sections:
            if not section.items:
                continue
            
            # 分类标题
            section_title = SECTION_TITLES.get(section.category, str(section.category))
            
            # 国际事件标记为低影响
            if section.category == ReportCategory.INTERNATIONAL:
                section_title += "（关注）"
            elif section.category == ReportCategory.MACRO:
                # 宏观政策如果有重磅事件，标记为重磅
                has_high = any(i.importance == EventImportance.HIGH for i in section.items)
                if has_high:
                    section_title += "（重磅）"
            
            lines.append(f"## {section_title}")
            lines.append("")
            
            # 分类摘要
            if section.summary:
                lines.append(f"*{section.summary}*")
                lines.append("")
            
            # 事件列表
            for item in section.items:
                self._format_item_markdown(item, lines, detailed=True)
            
            lines.append("")
        
        # 页脚
        lines.append("---")
        lines.append("*本报告由 AI 自动生成，仅供参考，不构成投资建议*")
        
        return "\n".join(lines)
    
    def _format_item_markdown(
        self, 
        item: ReportItem, 
        lines: List[str],
        detailed: bool = True
    ) -> None:
        """格式化单个事件条目（Markdown）"""
        mark = IMPORTANCE_MARKS.get(item.importance, "")
        
        # 时间戳
        time_str = ""
        if item.event_time:
            time_str = f"[{item.event_time.strftime('%H:%M')}] "
        
        # 标题行
        line = f"- {mark} {time_str}**{item.title}**"
        
        # 新闻数量（如果大于1）
        if item.news_count > 1:
            line += f" `{item.news_count}条`"
        
        lines.append(line)
        
        # 详细信息（核心影响、板块、情绪）
        if detailed and (item.impact or item.sectors):
            # 核心影响
            if item.impact:
                impact_text = item.impact[:80]
                if len(item.impact) > 80:
                    impact_text += "..."
                lines.append(f"  > **核心影响**: {impact_text}")
            
            # 关联板块
            if item.sectors:
                sectors_str = "、".join(item.sectors[:4])
                lines.append(f"  > **关联板块**: {sectors_str}")
            
            # 情绪（仅重要事件显示）
            if item.importance == EventImportance.HIGH:
                sentiment_label = SENTIMENT_LABELS.get(item.sentiment, "中性")
                emoji = SENTIMENT_EMOJI.get(item.sentiment, "")
                if item.policy_level:
                    lines.append(f"  > **情绪**: {emoji} {sentiment_label} | **级别**: {item.policy_level}")
                else:
                    lines.append(f"  > **情绪**: {emoji} {sentiment_label}")
            
            lines.append("")  # 空行分隔
    
    def to_wechat(self, report: Report) -> str:
        """
        转换为企业微信 Markdown 格式
        """
        lines = []
        
        # 标题
        report_type_name = "早报" if report.type == ReportType.MORNING else "午报"
        lines.append(f"### 📰 {report.date} 财经{report_type_name}")
        lines.append("")
        
        # 概述
        if report.overview:
            overview_text = report.overview[:150]
            if len(report.overview) > 150:
                overview_text += "..."
            lines.append(f"> {overview_text}")
            lines.append("")
        
        # 核心机会
        if report.stats.top_sectors:
            sectors_str = "、".join(report.stats.top_sectors[:3])
            lines.append(f"🎯 **今日核心机会**: {sectors_str}")
            lines.append("")
        
        lines.append("---")
        
        # 统计
        stats = report.stats
        lines.append(f"今日核心财经大事（共{stats.event_count}条，重磅{stats.high_importance_count}条）")
        lines.append("")
        
        # 收集所有事件，按重要性排序
        all_items = []
        for section in report.sections:
            for item in section.items:
                item.raw_event["_report_category"] = section.category
                all_items.append(item)
        
        def sort_key(item: ReportItem):
            importance_order = {
                EventImportance.HIGH: 0,
                EventImportance.MEDIUM_HIGH: 1,
                EventImportance.MEDIUM: 2, 
                EventImportance.LOW: 3
            }
            category = item.raw_event.get("_report_category", ReportCategory.HOT)
            category_order = SECTION_ORDER.get(category, 99)
            return (importance_order.get(item.importance, 3), category_order)
        
        all_items.sort(key=sort_key)
        
        # 分组
        high_items = [i for i in all_items if i.importance == EventImportance.HIGH]
        other_items = [i for i in all_items if i.importance != EventImportance.HIGH]
        
        # 重磅事件
        if high_items:
            lines.append("**📍 重磅事件**")
            lines.append("")
            for item in high_items[:5]:
                tag = IMPORTANCE_TAGS.get(item.importance, "关注")
                lines.append(f"**【{tag}】{item.title}**")
                if item.impact:
                    impact_text = item.impact[:80] + ("..." if len(item.impact) > 80 else "")
                    lines.append(f"> 影响: {impact_text}")
                if item.sectors:
                    lines.append(f"> 板块: {'、'.join(item.sectors[:3])}")
                lines.append("")
        
        # 其他要闻
        if other_items:
            lines.append("**📌 其他要闻**")
            lines.append("")
            for item in other_items[:6]:
                tag = IMPORTANCE_TAGS.get(item.importance, "关注")
                lines.append(f"**【{tag}】{item.title}**")
                if item.sectors:
                    lines.append(f"> 板块: {'、'.join(item.sectors[:2])}")
                lines.append("")
        
        lines.append("---")
        lines.append("> 本报告由AI自动生成，仅供参考")
        
        return "\n".join(lines)
    
    def format_report(self, report: Report) -> Report:
        """
        一次性生成所有格式
        
        Args:
            report: 报告对象
            
        Returns:
            填充了格式化内容的报告对象
        """
        report.content_markdown = self.to_markdown(report)
        report.content_wechat = self.to_wechat(report)
        return report


def create_report_title(report_type: ReportType, date: str) -> str:
    """生成报告标题"""
    type_name = "早报" if report_type == ReportType.MORNING else "午报"
    return f"📰 {date} 财经{type_name}"


def create_report_id(report_type: ReportType, date: str) -> str:
    """生成报告ID"""
    return f"{report_type.value}_{date.replace('-', '')}"
