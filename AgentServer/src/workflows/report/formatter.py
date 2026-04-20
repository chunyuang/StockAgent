"""
复盘报告格式化器

将复盘分析结果转换为各种输出格式。
"""

import logging
from typing import Any, Dict, Union
from datetime import datetime

from src.config import config_manager
from src.workflows.graph.state import ReviewState


logger = logging.getLogger(__name__)


# 类型别名：支持 ReviewState（LangGraph）或普通 dict
WorkflowResult = Union[ReviewState, Dict[str, Any]]


class ReviewReportFormatter:
    """
    复盘报告格式化器
    
    支持格式：
    - Markdown（标准）
    - WeChat（企业微信兼容）
    - HTML（Web展示）
    
    Example:
        formatter = ReviewReportFormatter()
        markdown = formatter.to_markdown(workflow_result)
        wechat = formatter.to_wechat(workflow_result)
    """
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        # 从配置读取限制
        report_config = config_manager.get("review.report", {})
        self.limits = report_config.get("limits", {
            "overview": 200,
            "market": 300,
            "sector": 400,
            "limit": 500,
            "sentiment": 200,
        })
    
    def to_markdown(self, result: WorkflowResult) -> str:
        """
        转换为标准 Markdown 格式
        
        Args:
            result: 工作流执行结果（ReviewState 或 dict）
        
        Returns:
            Markdown 格式的报告
        """
        # ReviewState 就是一个 dict
        state = result if isinstance(result, dict) else dict(result)
        trade_date = state.get("trade_date", "")
        
        lines = []
        
        # 标题
        lines.append(f"# {trade_date} 每日复盘")
        lines.append("")
        lines.append(f"*生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
        lines.append("")
        
        # 各部分内容
        sections = [
            ("market_result", "大盘复盘", "📈"),
            ("sector_result", "板块复盘", "🎯"),
            ("limit_result", "涨停复盘", "🚀"),
            ("linkage_result", "龙头梯队", "👑"),
            ("sentiment_result", "情绪周期", "💡"),
        ]
        
        for key, title, emoji in sections:
            agent_result = state.get(key)
            if agent_result:
                content = self._extract_content(agent_result)
                if content:
                    lines.append(f"## {emoji} {title}")
                    lines.append("")
                    lines.append(content)
                    lines.append("")
        
        # 最终报告（如果有）
        report = state.get("report")
        if report:
            lines.append("---")
            lines.append("")
            lines.append(report)
        
        # 免责声明
        lines.append("")
        lines.append("---")
        lines.append("*本报告由 AI 自动生成，仅供参考，不构成投资建议。*")
        
        return "\n".join(lines)
    
    def to_wechat(self, result: WorkflowResult) -> str:
        """
        转换为企业微信 Markdown 格式
        
        企业微信 Markdown 限制：
        - 支持基础语法
        - 部分高级语法不支持
        - 内容长度限制
        
        Args:
            result: 工作流执行结果
        
        Returns:
            企业微信兼容的 Markdown
        """
        state = result if isinstance(result, dict) else dict(result)
        trade_date = state.get("trade_date", "")
        
        lines = []
        
        # 标题
        lines.append(f"### 📊 {trade_date} 每日复盘")
        lines.append("")
        
        # 概览（从最终报告提取）
        report = state.get("report")
        if report:
            overview = self._extract_overview(report)
            if overview:
                lines.append(f"> {overview}")
                lines.append("")
        
        lines.append("---")
        lines.append("")
        
        # 核心数据
        market_result = state.get("market_result")
        if market_result:
            content = self._extract_content(market_result)
            if content:
                summary = self._truncate(content, self.limits.get("market", 300))
                lines.append("**📈 大盘**")
                lines.append(summary)
                lines.append("")
        
        # 板块
        sector_result = state.get("sector_result")
        if sector_result:
            content = self._extract_content(sector_result)
            if content:
                summary = self._truncate(content, self.limits.get("sector", 400))
                lines.append("**🎯 板块**")
                lines.append(summary)
                lines.append("")
        
        # 涨停
        limit_result = state.get("limit_result")
        if limit_result:
            content = self._extract_content(limit_result)
            if content:
                summary = self._truncate(content, self.limits.get("limit", 500))
                lines.append("**🚀 涨停**")
                lines.append(summary)
                lines.append("")
        
        # 情绪
        sentiment_result = state.get("sentiment_result")
        if sentiment_result:
            content = self._extract_content(sentiment_result)
            if content:
                summary = self._truncate(content, self.limits.get("sentiment", 200))
                lines.append("**💡 情绪**")
                lines.append(summary)
                lines.append("")
        
        lines.append("---")
        lines.append("> 本报告由AI自动生成，仅供参考")
        
        return "\n".join(lines)
    
    def to_html(self, result: WorkflowResult) -> str:
        """
        转换为 HTML 格式（用于 Web 展示）
        
        Args:
            result: 工作流执行结果
        
        Returns:
            HTML 格式的报告
        """
        import markdown
        
        md_content = self.to_markdown(result)
        
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>每日复盘</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            line-height: 1.6;
        }}
        h1 {{ color: #333; border-bottom: 2px solid #4CAF50; padding-bottom: 10px; }}
        h2 {{ color: #4CAF50; margin-top: 30px; }}
        blockquote {{
            border-left: 4px solid #4CAF50;
            margin: 0;
            padding-left: 16px;
            color: #666;
        }}
        code {{ background: #f5f5f5; padding: 2px 6px; border-radius: 4px; }}
        hr {{ border: none; border-top: 1px solid #eee; margin: 20px 0; }}
    </style>
</head>
<body>
{markdown.markdown(md_content)}
</body>
</html>"""
        
        return html
    
    def _extract_content(self, agent_result: Any) -> str:
        """从 Agent 结果中提取内容"""
        if isinstance(agent_result, dict):
            return agent_result.get("content", "")
        elif hasattr(agent_result, "content"):
            return agent_result.content
        elif isinstance(agent_result, str):
            return agent_result
        return ""
    
    def _extract_overview(self, content: str, max_length: int = 150) -> str:
        """从报告中提取概览"""
        lines = content.split("\n")
        
        for line in lines:
            line = line.strip()
            # 跳过标题行
            if line.startswith("#"):
                continue
            # 跳过空行
            if not line:
                continue
            # 返回第一段有效内容
            if len(line) > 20:
                return self._truncate(line, max_length)
        
        return ""
    
    def _truncate(self, text: str, max_length: int) -> str:
        """截断文本"""
        if len(text) <= max_length:
            return text
        return text[:max_length - 3] + "..."
    
    def format_dragons_summary(self, summary: Dict[str, Any]) -> str:
        """
        格式化龙头汇总
        
        Args:
            summary: StockLinkageAnalyzer.get_dragons_summary() 的结果
        
        Returns:
            格式化的文本
        """
        lines = []
        
        trade_date = summary.get("trade_date", "")
        lines.append(f"## 👑 {trade_date} 龙头梯队")
        lines.append("")
        
        # 龙一汇总
        dragon_ones = summary.get("dragon_one_list", [])
        if dragon_ones:
            lines.append("### 🔴 龙一")
            for d in dragon_ones[:5]:
                lines.append(f"- **{d['name']}**（{d['sector']}）")
            lines.append("")
        
        # 龙二汇总
        dragon_twos = summary.get("dragon_two_list", [])
        if dragon_twos:
            lines.append("### 🟠 龙二")
            for d in dragon_twos[:5]:
                lines.append(f"- **{d['name']}**（{d['sector']}）")
            lines.append("")
        
        # 中军汇总
        central_army = summary.get("central_army_list", [])
        if central_army:
            lines.append("### 🟢 中军")
            for d in central_army[:5]:
                lines.append(f"- **{d['name']}**（{d['sector']}）")
            lines.append("")
        
        return "\n".join(lines)
