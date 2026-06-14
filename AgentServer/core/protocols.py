"""
消息协议定义

定义节点间通信的强类型消息模型。
所有消息必须包含 trace_id 用于分布式追踪。
"""

from enum import Enum
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from pydantic import BaseModel, Field
import uuid


# ==================== 枚举定义 ====================


class NodeType(str, Enum):
    """节点类型"""
    WEB = "web"
    DATA_SYNC = "data_sync"
    BACKTEST = "backtest"


class TaskType(str, Enum):
    """任务类型"""
    STOCK_ANALYSIS = "stock_analysis" # 股票分析
    MARKET_OVERVIEW = "market_overview" # 市场概览
    NEWS_SENTIMENT = "news_sentiment" # 新闻情感
    STRATEGY_BACKTEST = "strategy_backtest" # 策略回测
    CUSTOM_QUERY = "custom_query" # 自定义查询


class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending" # 待处理
    QUEUED = "queued" # 已排队
    RUNNING = "running" # 运行中
    COMPLETED = "completed" # 已完成
    FAILED = "failed" # 失败
    CANCELLED = "cancelled" # 已取消


class SignalType(str, Enum):
    """交易信号"""
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


# ==================== 节点信息 ====================


class NodeInfo(BaseModel):
    """节点注册信息"""
    node_id: str
    node_type: NodeType
    host: str
    port: int
    status: str = "online"  # online, busy, offline
    last_heartbeat: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    current_tasks: int = 0
    max_tasks: int = 5
    
    # RPC 地址 (gRPC)
    rpc_address: Optional[str] = Field(default=None, description="gRPC RPC 地址 (host:port)")
    
    @property
    def load_ratio(self) -> float:
        """负载比例"""
        return self.current_tasks / self.max_tasks if self.max_tasks > 0 else 0


class NodeHeartbeat(BaseModel):
    """节点心跳"""
    node_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "alive"
    load: float = 0.0


# ==================== 任务消息 (核心) ====================


class AgentTask(BaseModel):
    """
    Agent 任务消息
    
    从 Web 节点派发的任务。
    所有任务必须包含 trace_id。
    """
    # 任务标识
    task_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    trace_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    
    # 任务内容
    task_type: TaskType
    ts_codes: List[str] = Field(default_factory=list)
    query: Optional[str] = None
    params: Dict[str, Any] = Field(default_factory=dict)
    
    # 元信息
    user_id: str
    priority: int = 0  # 优先级，数字越大越优先
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    # 目标节点 (用于定向分发)
    target_node_id: Optional[str] = None


class AgentResponse(BaseModel):
    """
    Agent 响应消息
    
    任务执行结果。
    """
    # 关联信息
    task_id: str
    trace_id: str
    
    # 状态
    status: TaskStatus
    
    # 结果
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    
    # 执行信息
    source_node: Optional[str] = None
    execution_time_ms: float = 0
    llm_tokens_used: int = 0
    
    # 时间戳
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ==================== 进度消息 ====================


class TaskProgress(BaseModel):
    """任务进度消息 (WebSocket 推送)"""
    task_id: str
    trace_id: str
    status: TaskStatus
    progress: float = 0  # 0-100
    current_step: Optional[str] = None
    message: Optional[str] = None
    source_node: Optional[str] = None


class AgentThought(BaseModel):
    """Agent 思考过程 (用于前端展示)"""
    task_id: str
    trace_id: str
    node_name: str
    content: str
    is_final: bool = False
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ==================== 分析结果 ====================


class AnalysisScore(BaseModel):
    """分析评分"""
    fundamental: Optional[float] = None  # 基本面 0-100
    technical: Optional[float] = None    # 技术面 0-100
    sentiment: Optional[float] = None    # 舆情 0-100
    valuation: Optional[float] = None    # 估值 0-100


class AnalysisResult(BaseModel):
    """分析结果"""
    signal: SignalType
    confidence: float  # 0-1
    scores: AnalysisScore
    summary: str
    
    # 详细分析
    fundamental_analysis: Optional[str] = None
    technical_analysis: Optional[str] = None
    sentiment_analysis: Optional[str] = None
    
    # 目标价
    target_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    
    # 风险提示
    risks: List[str] = Field(default_factory=list)


# ==================== 策略监听 ====================


class StrategyType(str, Enum):
    """策略类型（核心4个活跃策略）
    
    活跃策略:
    - LIMIT_OPEN = "limit_open"           # 涨停开板
    - PRICE_CHANGE = "price_change"       # 半路追涨（涨跌幅阈值）
    - LEADING_DRAGON = "leading_dragon"   # 龙头战法（龙头低吸）
    - FIRST_BOARD = "first_board"         # 首板打板
    
    已停用（保留枚举定义，数据库中旧配置兼容）:
    - MA5_BUY = "ma5_buy"                 # 5日线低吸（回测表现差，已移除）
    - VOLUME_SURGE = "volume_surge"       # 放量突破（预留）
    - MA_CROSS = "ma_cross"               # 均线交叉（预留）
    - CUSTOM = "custom"                   # 自定义策略
    """
    LIMIT_OPEN = "limit_open"           # 涨跌停打开
    PRICE_CHANGE = "price_change"       # 涨跌幅阈值
    VOLUME_SURGE = "volume_surge"       # 放量突破
    MA_CROSS = "ma_cross"               # 均线交叉
    MA5_BUY = "ma5_buy"                 # 5日线低吸（已停用）
    LEADING_DRAGON = "leading_dragon"   # 龙头战法
    FIRST_BOARD = "first_board"         # 首板打板
    CUSTOM = "custom"                   # 自定义策略


class StrategySubscription(BaseModel):
    """
    策略订阅配置
    """
    # 基础信息
    subscription_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    strategy_id: str = Field(default_factory=lambda: uuid.uuid4().hex, description="策略唯一标识")
    strategy_name: str = Field(default="", description="策略名称")
    strategy_type: StrategyType = Field(default=StrategyType.CUSTOM, description="策略类型")
    
    # 监听范围
    watch_list: List[str] = Field(
        default_factory=list, 
        description="监听股票列表，必须包含 'ALL' 才表示全市场监听，空列表表示不监听任何股票"
    )
    
    # 策略参数
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="策略参数，如 {'threshold': 3.0} 表示涨幅超过3%触发"
    )
    
    # 状态
    is_active: bool = Field(default=True, description="是否激活")
    user_id: Optional[str] = Field(default=None, description="所属用户")
    
    # 时间戳
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    def is_all_market(self) -> bool:
        """是否监听全市场 (必须明确包含 'ALL' 标识)"""
        return "ALL" in self.watch_list


class StrategyAlert(BaseModel):
    """
    策略触发预警
    
    当策略条件满足时生成的预警消息。
    """
    alert_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    trace_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    
    # 关联信息
    subscription_id: str = Field(description="订阅配置ID")
    strategy_id: str = Field(description="策略ID")
    strategy_name: str = Field(default="", description="策略名称")
    
    # 触发信息
    ts_code: str = Field(description="股票代码")
    stock_name: str = Field(default="", description="股票名称")
    trigger_price: float = Field(description="触发时价格")
    trigger_reason: str = Field(description="触发原因")
    
    # 附加数据
    extra_data: Dict[str, Any] = Field(default_factory=dict, description="额外数据")
    
    # 时间戳
    triggered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MarketSnapshot(BaseModel):
    """
    市场快照 (内存缓存用)
    
    每次轮询获取的全市场实时数据快照。
    """
    snapshot_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    snapshot_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    # 数据
    quotes: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict,
        description="实时行情数据，key 为 ts_code"
    )
    limit_stocks: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict,
        description="今日涨跌停股票，key 为 ts_code"
    )
    
    # 统计
    total_stocks: int = Field(default=0, description="股票总数")
    up_count: int = Field(default=0, description="上涨家数")
    down_count: int = Field(default=0, description="下跌家数")
    limit_up_count: int = Field(default=0, description="涨停家数")
    limit_down_count: int = Field(default=0, description="跌停家数")


# ==================== 兼容性别名 ====================

TaskMessage = AgentTask
ResultMessage = AgentResponse
TaskProgressMessage = TaskProgress
