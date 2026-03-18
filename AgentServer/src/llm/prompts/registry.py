"""
Prompt 注册表

集中管理所有 Prompt 模板:
- 自动加载模板文件
- 按名称/任务类型检索
- 版本管理
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional

from .template import PromptTemplate, OutputFormat


logger = logging.getLogger(__name__)


# 模板目录
# 优先从 config/prompts/ 加载，与其他配置统一管理
CONFIG_PROMPTS_DIR = Path(__file__).parents[3] / "config" / "prompts"
# 备选目录（保留原有支持）
TEMPLATES_DIR = Path(__file__).parent / "templates"


class PromptRegistry:
    """
    Prompt 注册表
    
    Example:
        registry = PromptRegistry()
        registry.load_templates()
        
        template = registry.get("event_extract")
        rendered = template.render(title="xxx", content="yyy")
    """
    
    _instance: Optional["PromptRegistry"] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._templates = {}
            cls._instance._loaded = False
        return cls._instance
    
    def __init__(self):
        self._templates: Dict[str, PromptTemplate] = {}
        self._loaded: bool = False
    
    def load_templates(self, templates_dir: Optional[Path] = None) -> int:
        """
        加载模板目录下的所有 YAML 文件
        
        加载顺序：
        1. config/prompts/ (优先，与其他配置统一管理)
        2. src/llm/prompts/templates/ (备选)
        3. 指定的 templates_dir (如果提供)
        
        Returns:
            加载的模板数量
        """
        count = 0
        
        # 如果指定了目录，只加载该目录
        if templates_dir is not None:
            count += self._load_from_dir(templates_dir)
        else:
            # 优先加载 config/prompts/
            if CONFIG_PROMPTS_DIR.exists():
                count += self._load_from_dir(CONFIG_PROMPTS_DIR)
            
            # 再加载 src/llm/prompts/templates/ (如果存在)
            if TEMPLATES_DIR.exists():
                count += self._load_from_dir(TEMPLATES_DIR)
        
        self._loaded = True
        logger.info(f"Loaded {count} prompt templates from YAML files")
        return count
    
    def _load_from_dir(self, directory: Path) -> int:
        """从指定目录加载模板"""
        if not directory.exists():
            logger.warning(f"Templates directory not found: {directory}")
            return 0
        
        count = 0
        for yaml_file in directory.glob("*.yaml"):
            try:
                template = PromptTemplate.from_file(yaml_file)
                self.register(template)
                count += 1
                logger.debug(f"Loaded template: {template.name} v{template.version} from {yaml_file}")
            except Exception as e:
                logger.error(f"Failed to load template {yaml_file}: {e}")
        
        if count > 0:
            logger.info(f"Loaded {count} templates from {directory}")
        return count
    
    def register(self, template: PromptTemplate) -> None:
        """注册模板"""
        self._templates[template.name] = template
    
    def get(self, name: str) -> Optional[PromptTemplate]:
        """获取模板"""
        if not self._loaded:
            self.load_templates()
        return self._templates.get(name)
    
    def get_or_raise(self, name: str) -> PromptTemplate:
        """获取模板，不存在则抛出异常"""
        template = self.get(name)
        if template is None:
            raise KeyError(f"Template not found: {name}")
        return template
    
    def list_templates(self) -> List[str]:
        """列出所有模板名称"""
        if not self._loaded:
            self.load_templates()
        return list(self._templates.keys())
    
    def list_by_task(self, task_prefix: str) -> List[PromptTemplate]:
        """按任务前缀列出模板"""
        if not self._loaded:
            self.load_templates()
        return [
            t for name, t in self._templates.items()
            if name.startswith(task_prefix)
        ]


# 全局单例
prompt_registry = PromptRegistry()


# ==================== 内置模板 (代码定义) ====================

# 事件提取模板
EVENT_EXTRACT_TEMPLATE = PromptTemplate(
    name="event_extract",
    version="1.1",
    description="从新闻中提取事件指纹",
    system_prompt="你是一位专业的财经分析师，擅长从新闻中提取关键事件信息。",
    user_prompt="""分析以下新闻，提取事件指纹信息。

新闻标题: {title}
新闻内容: {content}

请提取以下信息 (JSON格式):
{{
    "subject": "事件主体 (公司名/行业/政策名称/国家)",
    "action": "核心动作 (如: 发布, 上涨, 下跌, 收购, 推出, 暂停, 冲突, 制裁)",
    "time_ref": "时间参照 (如: 今日, 本周, 2024Q1, 近期)",
    "keywords": ["关键词1", "关键词2", "关键词3"],
    "importance": "high/medium/low",
    "summary": "一句话事件摘要 (20字以内)",
    "category": "事件分类，必须从以下选项中选择:
        - policy: 中国国内政策（国务院、部委、地方政府发布的政策）
        - international: 国际大事件（地缘政治、外交、国际冲突、外国政策）
        - intl_economy: 国际经济（美联储、欧央行、汇率、外贸）
        - intl_commodity: 国际大宗商品（油价、金价、期货）
        - company: 公司相关（财报、人事、并购）
        - industry: 行业动态
        - market: 市场行情
        - tech: 科技创新"
}}

分类判断要点：
- 涉及外国政府、外国领导人、国际组织的外交/军事行动 → international
- 涉及中国政府机构发布的政策/法规/通知 → policy
- 美联储/欧央行利率决议、汇率变动 → intl_economy
- 国际油价、大宗商品价格波动 → intl_commodity

只返回JSON，不要其他内容。""",
    variables=["title", "content"],
    output_format=OutputFormat.JSON,
    output_schema={
        "type": "object",
        "properties": {
            "subject": {"type": "string"},
            "action": {"type": "string"},
            "time_ref": {"type": "string"},
            "keywords": {"type": "array", "items": {"type": "string"}},
            "importance": {"type": "string", "enum": ["high", "medium", "low"]},
            "summary": {"type": "string"},
            "category": {"type": "string", "enum": [
                "policy", "international", "intl_economy", "intl_commodity",
                "company", "industry", "market", "tech"
            ]},
        },
        "required": ["subject", "action", "summary", "category"],
    },
    model_preference="fast",
    temperature=0.1,
    max_tokens=512,
)

# 重要性评估模板 (3维度量化打分 + 核心影响深度解读)
IMPORTANCE_ASSESS_TEMPLATE = PromptTemplate(
    name="importance_assess",
    version="3.0",
    description="批量评估事件重要性 - 3维度量化打分 + 基于正文的核心影响解读",
    system_prompt="""你是一位资深A股投研分析师，专注于短线交易机会挖掘。
你需要用严格的量化标准评估财经事件对股市的影响。

评分规则（每个维度1-5分）：

【来源级别分】
5分 = 国务院/中央/全国性会议/总书记/总理
4分 = 部委（工信部、发改委、财政部、央行、证监会）
3分 = 交易所/行业协会/中证
1分 = 地方政府/普通公司/一般媒体

【影响范围分】
5分 = 影响全市场/全板块（降准降息、印花税、北向资金政策）
3分 = 影响1个大板块（行业政策、产业规划）
1分 = 只影响几只个股（单一公司公告）

【资金敏感分】（最关键！）
5分 = 直接影响成本/利润/供需/监管（涨价、关税、制裁、补贴、涨跌停）
3分 = 中期影响行业逻辑（政策规划、标准规范）
1分 = 长期概念，短期不涨（远期规划、研究报告）

【总分判定】
≥10分 = 重磅（必须收录）- 中央级政策/影响大板块/资金敏感度高
8-9分 = 重要（应该收录）
6-7分 = 关注（可选收录）
≤5分 = 噪音（直接过滤）

【特别规则 - 自动升级为重磅】
- 国务院/中央/全国人大发布的政策 → 直接定为重磅
- 影响1个及以上大板块 + 资金敏感度≥3分 → 定为重磅

【核心影响生成规则 - 极其重要！】
- 禁止复述标题，必须基于正文内容提炼
- 必须体现因果逻辑：XX措施/条款 → 导致XX结果 → 利好/利空XX板块
- 挖掘正文中的关键信息：具体指标、限制条件、覆盖范围、执行时间等""",
    user_prompt="""评估以下财经事件，给出3维度评分。

事件列表（包含标题和正文）:
{events_json}

请严格按照评分规则，为每个事件打分，并给出：
1. 来源级别分 (source_score: 1-5)
2. 影响范围分 (scope_score: 1-5)
3. 资金敏感分 (fund_score: 1-5)
4. 总分 (total: 三项相加)
5. 重要性标签 (tag: 重磅/重要/关注/噪音)
6. 情绪 (sentiment: positive=利好/negative=利空/neutral=中性)
7. 核心影响 (impact): 
   【强制要求】
   - 禁止复述事件标题！与标题相似度不得超过50%
   - 必须基于正文内容，提炼对A股相关板块的具体影响
   - 格式：事件的XX措施/条款，导致XX结果，利好/利空XX板块
   【正确示例】
   - 标题：国务院印发水资源刚性约束考核办法
   - 正确impact：设严格用水指标考核，高耗水企业受限，利好节水设备板块
   【错误示例】
   - 错误impact：国务院印发水资源刚性约束考核办法（这是复述标题！）
8. 关联板块 (sectors: 最多3个具体板块名称，必须与核心影响逻辑一致)

返回 JSON 格式:
```json
{{
  "results": [
    {{
      "event_id": "xxx",
      "source_score": 4,
      "scope_score": 3,
      "fund_score": 5,
      "total": 12,
      "tag": "重磅",
      "sentiment": "positive",
      "impact": "设严格用水指标考核，高耗水企业产能受限，利好节水设备和水务板块",
      "sectors": ["节水设备", "水务", "环保"]
    }}
  ]
}}
```

只返回 JSON，不要其他内容。""",
    variables=["events_json"],
    output_format=OutputFormat.JSON,
    model_preference="fast",
    temperature=0.2,
    max_tokens=4096,
)

# 报告摘要模板
REPORT_SUMMARY_TEMPLATE = PromptTemplate(
    name="report_summary",
    version="1.0",
    description="生成报告段落摘要",
    system_prompt="你是一位财经编辑，擅长撰写简洁专业的财经摘要。",
    user_prompt="""为以下{category}类事件撰写一段简洁的汇总（50-100字）。

事件列表:
{events_text}

要求:
1. 突出最重要的1-2个事件
2. 语言简洁专业
3. 不要使用"首先"、"其次"等词
4. 直接输出汇总内容，不要有前缀""",
    variables=["category", "events_text"],
    output_format=OutputFormat.TEXT,
    model_preference="balanced",
    temperature=0.5,
    max_tokens=256,
)

# 报告概述模板
REPORT_OVERVIEW_TEMPLATE = PromptTemplate(
    name="report_overview",
    version="1.1",
    description="生成报告总体概述",
    system_prompt="你是一位资深财经编辑，擅长撰写简洁有洞察力的市场概述。",
    user_prompt="""为今日{report_type}撰写一段总体概述（80-120字）。

今日要点:
- 宏观政策: {macro_summary}
- 国际事件: {international_summary}
- 行业动态: {industry_summary}
- 个股异动: {stock_summary}
- 热点事件: {hot_summary}

核心板块: {top_sectors}

要求:
1. 用一句话概括今日市场整体情况和情绪
2. 点明今日最值得关注的1-2个板块机会
3. 如有重大政策或国际事件，简要说明对A股的影响
4. 语言简洁专业，不要空话套话
5. 直接输出概述内容""",
    variables=["report_type", "macro_summary", "international_summary", "industry_summary", "stock_summary", "hot_summary", "top_sectors"],
    output_format=OutputFormat.TEXT,
    model_preference="balanced",
    temperature=0.5,
    max_tokens=256,
)

# 股票分析模板
STOCK_ANALYSIS_TEMPLATE = PromptTemplate(
    name="stock_analysis",
    version="1.0",
    description="个股综合分析",
    system_prompt="""你是一位专业的股票分析师，擅长从多维度分析股票:
- 基本面分析 (财务指标、估值)
- 技术面分析 (K线形态、趋势)
- 资金面分析 (主力资金、北向资金)
- 消息面分析 (新闻、公告)""",
    user_prompt="""分析股票 {ts_code} ({name})

基本面数据:
{fundamental_data}

技术面数据:
{technical_data}

资金流向:
{money_flow}

近期新闻:
{recent_news}

请给出:
1. 综合评分 (1-10)
2. 核心观点 (3句话以内)
3. 风险提示
4. 操作建议 (买入/观望/卖出)""",
    variables=["ts_code", "name", "fundamental_data", "technical_data", "money_flow", "recent_news"],
    output_format=OutputFormat.MARKDOWN,
    model_preference="quality",
    temperature=0.3,
    max_tokens=1024,
)

# 事件增强模板 (批量提取炒股关键信息)
EVENT_ENRICH_TEMPLATE = PromptTemplate(
    name="event_enrich",
    version="1.0",
    description="批量增强事件的炒股关键字段",
    system_prompt="""你是一位A股资深投研分析师，专注于挖掘财经事件的交易价值。

你需要分析事件并提取以下关键信息：
1. 情绪判断 (sentiment): 对股市的整体影响
   - positive: 利好（提振股价、增加盈利预期）
   - negative: 利空（打压股价、降低盈利预期）
   - neutral: 中性（无明显方向性影响）

2. 情绪强度 (sentiment_score): -1.0 到 1.0
   - 1.0 = 重大利好
   - 0.5 = 中度利好
   - 0 = 中性
   - -0.5 = 中度利空
   - -1.0 = 重大利空

3. 影响范围 (impact_scope):
   - market: 全市场（货币政策、印花税、北向资金等）
   - sector: 板块级（行业政策、产业规划）
   - stock: 个股级（单一公司公告、人事变动）

4. 关联板块 (related_sectors): 最多5个最相关的A股板块
   - 使用标准板块名称，如：光伏、锂电、汽车、银行、地产等

5. 政策级别 (policy_level): 仅对政策类事件填写
   - central: 中央/国务院级
   - ministry: 部委级（工信部、发改委等）
   - local: 地方级
   - company: 企业级
   - null: 非政策类事件""",
    user_prompt="""分析以下财经事件，提取炒股关键信息：

事件标题: {title}
事件摘要: {summary}
事件分类: {category}
信息来源: {sources}

请返回JSON格式：
```json
{{
  "sentiment": "positive/negative/neutral",
  "sentiment_score": 0.5,
  "impact_scope": "market/sector/stock",
  "related_sectors": ["板块1", "板块2"],
  "policy_level": "central/ministry/local/company/null"
}}
```

只返回JSON，不要其他内容。""",
    variables=["title", "summary", "category", "sources"],
    output_format=OutputFormat.JSON,
    output_schema={
        "type": "object",
        "properties": {
            "sentiment": {"type": "string", "enum": ["positive", "negative", "neutral"]},
            "sentiment_score": {"type": "number", "minimum": -1.0, "maximum": 1.0},
            "impact_scope": {"type": "string", "enum": ["market", "sector", "stock"]},
            "related_sectors": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
            "policy_level": {"type": ["string", "null"]},
        },
        "required": ["sentiment", "sentiment_score", "impact_scope", "related_sectors"],
    },
    model_preference="fast",
    temperature=0.2,
    max_tokens=512,
)


# P3 简化版模板：仅提取板块（降低 Token 消耗）
EVENT_SECTOR_ONLY_TEMPLATE = PromptTemplate(
    name="event_sector_only",
    description="P3 简化版增强模板，仅提取关联板块，用于降低 LLM 成本",
    system_prompt="你是股票板块分析专家。根据新闻标题快速识别关联的A股板块。",
    user_prompt="""新闻标题: {title}

请返回JSON：
```json
{{"sectors": ["板块1", "板块2"]}}
```

要求：
1. 最多返回3个最相关板块
2. 使用A股常见板块名称
3. 只返回JSON""",
    variables=["title"],
    output_format=OutputFormat.JSON,
    output_schema={
        "type": "object",
        "properties": {
            "sectors": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        },
        "required": ["sectors"],
    },
    model_preference="fast",
    temperature=0.1,
    max_tokens=128,
)


# 注册内置模板
def register_builtin_templates():
    """注册所有内置模板"""
    builtin = [
        EVENT_EXTRACT_TEMPLATE,
        EVENT_ENRICH_TEMPLATE,
        EVENT_SECTOR_ONLY_TEMPLATE,
        IMPORTANCE_ASSESS_TEMPLATE,
        REPORT_SUMMARY_TEMPLATE,
        REPORT_OVERVIEW_TEMPLATE,
        STOCK_ANALYSIS_TEMPLATE,
    ]
    for template in builtin:
        prompt_registry.register(template)
    logger.info(f"Registered {len(builtin)} builtin templates")


# 自动注册
register_builtin_templates()
