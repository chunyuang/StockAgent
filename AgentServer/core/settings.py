"""
全局配置管理

所有 Manager 在初始化时必须从此处读取配置。
使用 Pydantic Settings 实现环境变量自动绑定。

环境变量命名规则:
  - Redis: REDIS_HOST, REDIS_PORT, REDIS_PASSWORD, ...
  - MongoDB: MONGO_HOST, MONGO_PORT, MONGO_USERNAME, ...
  - Milvus: MILVUS_HOST, MILVUS_PORT, ...
  - Tushare: TUSHARE_TOKEN, TUSHARE_RATE_LIMIT, ...
  - LLM: LLM_PROVIDER, LLM_API_KEY, LLM_MODEL_NAME, ...
  - Node: NODE_TYPE, NODE_ID, ...
  - 通用: DEBUG, JWT_SECRET, ...

使用方式:
  from core.settings import settings
  
  redis_url = settings.redis.url
  mongo_db = settings.mongo.database
"""

from functools import lru_cache
from typing import Optional, Literal
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


# ==================== 子配置类 ====================
# 每个子配置类独立读取对应前缀的环境变量


class RedisSettings(BaseSettings):
    """Redis 配置
    
    环境变量: REDIS_HOST, REDIS_PORT, REDIS_PASSWORD, REDIS_DB, ...
    """
    model_config = SettingsConfigDict(
        env_prefix="REDIS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    
    host: str = "localhost"
    port: int = 6379
    password: Optional[SecretStr] = None
    db: int = 0
    max_connections: int = 100  # 连接池大小
    
    # 队列名称
    task_queue: str = "agent:tasks"
    result_channel_prefix: str = "agent:results"
    node_registry_prefix: str = "agent:nodes"
    
    @property
    def url(self) -> str:
        pwd = self.password.get_secret_value() if self.password else None
        auth = f":{pwd}@" if pwd else ""
        return f"redis://{auth}{self.host}:{self.port}/{self.db}"


class MongoSettings(BaseSettings):
    """MongoDB 配置
    
    环境变量: MONGO_HOST, MONGO_PORT, MONGO_USERNAME, MONGO_PASSWORD, ...
    """
    model_config = SettingsConfigDict(
        env_prefix="MONGO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    
    host: str = "localhost"
    port: int = 27017
    username: Optional[str] = None
    password: Optional[SecretStr] = None
    database: str = "stock_agent"
    auth_source: str = "admin"
    max_pool_size: int = 50
    
    @property
    def url(self) -> str:
        if self.username and self.password:
            pwd = self.password.get_secret_value()
            return f"mongodb://{self.username}:{pwd}@{self.host}:{self.port}/{self.database}?authSource={self.auth_source}"
        return f"mongodb://{self.host}:{self.port}/{self.database}"


class MilvusSettings(BaseSettings):
    """Milvus 向量数据库配置
    
    环境变量: MILVUS_HOST, MILVUS_PORT, MILVUS_USER, MILVUS_PASSWORD, ...
    """
    model_config = SettingsConfigDict(
        env_prefix="MILVUS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    
    host: str = "localhost"
    port: int = 19530
    user: Optional[str] = None
    password: Optional[SecretStr] = None
    
    # Collections
    research_reports_collection: str = "research_reports"
    market_snippets_collection: str = "market_snippets"
    
    # 向量维度 (与 embedding model 对应)
    embedding_dim: int = 1024


class TushareSettings(BaseSettings):
    """Tushare 数据源配置
    
    环境变量: TUSHARE_TOKEN, TUSHARE_HTTP_URL, TUSHARE_RATE_LIMIT, TUSHARE_BATCH_SIZE
    
    支持两种 Token 模式:
    1. 官方 Token: 配置 TUSHARE_TOKEN，使用官方 API
    2. 代理 Token: 配置 TUSHARE_TOKEN + TUSHARE_HTTP_URL，使用共享代理
    """
    model_config = SettingsConfigDict(
        env_prefix="TUSHARE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    
    # Token (必须配置)
    token: SecretStr = Field(
        default=SecretStr(""),
        description="Tushare Pro API Token"
    )
    
    # 自定义 API 地址 (代理模式使用，例如 http://119.45.170.23)
    http_url: Optional[str] = Field(
        default=None,
        description="自定义 API 地址，代理模式使用"
    )
    
    # 频率限制 (每分钟请求数)
    rate_limit: int = 200
    # 批量请求大小
    batch_size: int = 100
    
    @property
    def is_configured(self) -> bool:
        """检查是否已配置 Token"""
        return bool(self.token.get_secret_value())
    
    @property
    def has_custom_url(self) -> bool:
        """是否使用自定义代理地址"""
        return self.http_url is not None and bool(self.http_url)


class LLMSettings(BaseSettings):
    """LLM 模型配置
    
    环境变量: LLM_PROVIDER, LLM_API_KEY, LLM_API_BASE, LLM_MODEL_NAME, ...
    """
    model_config = SettingsConfigDict(
        env_prefix="LLM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    
    # 模型提供商: openai, dashscope (阿里), zhipu, ollama, deepseek
    provider: Literal["openai", "dashscope", "zhipu", "ollama", "deepseek"] = "dashscope"
    
    # API 配置
    api_key: Optional[SecretStr] = None
    api_base: Optional[str] = None
    
    # 模型名称
    model_name: str = "qwen-plus"
    embedding_model: str = "text-embedding-v3"
    
    # Embedding 单独配置 (可选，如果 provider 不支持 embedding)
    # 例如 DeepSeek 不支持 embedding，需要用 DashScope
    embedding_provider: Optional[Literal["openai", "dashscope", "zhipu", "ollama"]] = None
    embedding_api_key: Optional[SecretStr] = None
    embedding_api_base: Optional[str] = None
    
    # 模型参数
    temperature: float = 0.7
    max_tokens: int = 4096
    
    # 并发限制
    max_concurrent_requests: int = 10
    
    @property
    def is_configured(self) -> bool:
        """检查是否已配置 API Key"""
        return self.api_key is not None and bool(self.api_key.get_secret_value())


class ObservabilitySettings(BaseSettings):
    """可观测性配置
    
    环境变量: OBS_LOKI_URL, OBS_LOKI_ENABLED, OBS_PHOENIX_ENABLED, ...
    """
    model_config = SettingsConfigDict(
        env_prefix="OBS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    
    # Loki 日志
    loki_url: Optional[str] = None
    loki_enabled: bool = False
    
    # Arize Phoenix 追踪
    phoenix_enabled: bool = False
    phoenix_project: str = "stock-agent"
    
    # 日志级别
    log_level: str = "INFO"
    
    # 日志文件配置
    log_to_file: bool = True  # 是否输出到文件
    log_dir: str = "logs"  # 日志目录
    log_max_size_mb: int = 50  # 单个日志文件最大大小 (MB)
    log_backup_count: int = 10  # 保留的日志文件数量


class NodeSettings(BaseSettings):
    """节点配置
    
    环境变量: NODE_TYPE, NODE_ID, NODE_HEARTBEAT_INTERVAL, NODE_TTL
    """
    model_config = SettingsConfigDict(
        env_prefix="NODE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    
    # 节点类型: web, data_sync, mcp, inference, listener
    node_type: Literal["web", "data_sync", "mcp", "inference", "listener"] = "web"
    
    # 节点 ID (自动生成或指定)
    node_id: Optional[str] = None
    
    # 心跳间隔 (秒)
    heartbeat_interval: int = 10
    
    # 节点过期时间 (秒)
    node_ttl: int = 30


class RPCSettings(BaseSettings):
    """RPC 配置
    
    环境变量: RPC_WEB_PORT, RPC_INFERENCE_PORT, RPC_LISTENER_PORT, RPC_DATA_SYNC_PORT
    """
    model_config = SettingsConfigDict(
        env_prefix="RPC_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    
    # 各节点 RPC 端口
    web_port: int = 50051
    inference_port: int = 50052
    listener_port: int = 50053
    data_sync_port: int = 50054
    mcp_port: int = 50055
    backtest_port: int = 50057
    
    # RPC 超时 (秒)
    timeout: float = 10.0
    
    # 重试次数
    max_retries: int = 3


class DataSyncSettings(BaseSettings):
    """数据同步配置
    
    环境变量: SYNC_STOCK_BASIC_SCHEDULE, SYNC_STOCK_DAILY_SCHEDULE, 
             SYNC_INDEX_BASIC_SCHEDULE, SYNC_INDEX_DAILY_SCHEDULE, SYNC_NEWS_SCHEDULE
    
    使用 cron 表达式格式: 分 时 日 月 周
    示例:
      - "0 9 * * 1-5"   每个工作日 9:00
      - "30 15 * * 1-5" 每个工作日 15:30
      - "0 */2 * * *"   每 2 小时
    """
    model_config = SettingsConfigDict(
        env_prefix="SYNC_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    
    # 股票基础信息采集时间 (默认: 每个交易日 9:00)
    stock_basic_schedule: Optional[str] = None
    
    # 股票日线数据采集时间 (默认: 每个交易日 15:30)
    stock_daily_ak_full_schedule: Optional[str] = None
    
    # 指数基础信息采集时间 (默认: 每个交易日 9:00)
    index_basic_schedule: Optional[str] = None
    
    # 指数日线数据采集时间 (默认: 每个交易日 15:35)
    index_daily_schedule: Optional[str] = None
    
    # 行业资金流向采集时间 (默认: 每个交易日 16:00)
    moneyflow_industry_schedule: Optional[str] = None
    
    # 概念板块资金流向采集时间 (默认: 每个交易日 16:05)
    moneyflow_concept_schedule: Optional[str] = None
    
    # 涨跌停数据采集时间 (默认: 每个交易日 16:10)
    limit_list_schedule: Optional[str] = None
    
    # 每日统计数据计算时间 (默认: 每个交易日 16:30)
    daily_stats_schedule: Optional[str] = None
    
    # 新闻采集时间 (默认: 每 2 小时)
    news_schedule: Optional[str] = None


class WebSettings(BaseSettings):
    """Web 服务配置
    
    环境变量: WEB_HOST, WEB_PORT, WEB_WORKERS, WEBSOCKET_HOST, WEBSOCKET_PORT, CORS_ORIGINS
    """
    model_config = SettingsConfigDict(
        env_prefix="WEB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1
    reload: bool = False
    
    # WebSocket 配置（前端连接地址）
    websocket_host: str = "localhost"
    websocket_port: int = 8000
    
    # CORS 配置
    # CORS_ORIGINS: 逗号分隔的允许来源，如 "https://example.com,https://app.example.com"
    # 为空则仅允许同域名前端
    cors_origins: str = ""


class ListenerSettings(BaseSettings):
    """Listener 节点配置
    
    环境变量: LISTENER_POLL_INTERVAL, LISTENER_LIMIT_FETCH_TIME, ...
    """
    model_config = SettingsConfigDict(
        env_prefix="LISTENER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    
    # 轮询间隔 (秒)
    poll_interval: int = 60
    
    # 每日涨跌停数据获取时间 (格式: HH:MM)
    limit_fetch_time: str = "09:15"
    
    # 交易时间配置 (格式: HH:MM-HH:MM)
    morning_session: str = "09:30-11:30"
    afternoon_session: str = "13:00-15:00"
    
    # 是否在非交易时间静默
    silent_outside_trading: bool = False


class NotificationSettings(BaseSettings):
    """通知配置
    
    环境变量: NOTIFY_WECOM_WEBHOOK, NOTIFY_ENABLED, ...
    """
    model_config = SettingsConfigDict(
        env_prefix="NOTIFY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    
    # 企业微信 Webhook URL (飞书机器人也兼容此格式)
    wecom_webhook: Optional[str] = None
    
    # 是否启用通知
    enabled: bool = True
    
    # 消息发送间隔 (秒，防止刷屏)
    min_interval: int = 10
    
    @property
    def is_configured(self) -> bool:
        """检查是否已配置 Webhook"""
        return bool(self.wecom_webhook)


class FeishuSettings(BaseSettings):
    """飞书多维表格配置
    
    环境变量: FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_BITABLE_APP_TOKEN, ...
    """
    model_config = SettingsConfigDict(
        env_prefix="FEISHU_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    
    # 飞书应用凭证
    app_id: str = ""
    app_secret: str = ""
    
    # 多维表格
    bitable_app_token: str = ""  # 多维表格 App Token
    bitable_table_id: str = ""   # 实时监控表 ID
    
    # 是否启用自动写入
    enabled: bool = False
    
    @property
    def is_configured(self) -> bool:
        """检查是否完整配置"""
        return (
            self.enabled
            and bool(self.app_id)
            and bool(self.app_secret)
            and bool(self.bitable_app_token)
            and bool(self.bitable_table_id)
        )


# ==================== 主配置类 ====================


class Settings(BaseSettings):
    """
    主配置类
    
    从 .env 文件或环境变量读取配置。
    
    使用示例:
        from core.settings import settings
        
        # 访问配置
        debug = settings.debug
        redis_host = settings.redis.host
        tushare_token = settings.tushare.token.get_secret_value()
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    
    # 应用基础配置
    app_name: str = "StockAgent"
    debug: bool = Field(default=False, alias="DEBUG")
    
    # ==================== 运行模式配置 ====================
    # 
    # 【双模式架构设计】
    # 
    # MODE = 'backtest' → 回测模式（默认，当前项目阶段）
    #   - 直接从 MongoDB stock_daily_ak_full 集合读取预计算因子
    #   - 跳过实时因子计算 (_compute_single_factor)
    #   - 性能提升 10-100 倍，适合大规模历史回测
    #   - 依赖 DATA_SYNC 节点预先完成因子批量计算
    # 
    # MODE = 'live' → 实盘模式
    #   - 实时调用 factor_engine.compute_factors() 计算因子
    #   - 支持 Redis 缓存加速（24小时过期）
    #   - 支持滚动窗口、动态指标等实时计算需求
    #   - 兼容盘中选股、实时监控等场景
    # 
    # 环境变量: MODE=backtest 或 MODE=live
    # 
    # =====================================================
    mode: Literal["backtest", "live"] = Field(default="backtest", alias="MODE")
    
    # JWT 配置
    jwt_secret: SecretStr = Field(
        default=SecretStr("change-me-in-production"),
        alias="JWT_SECRET"
    )
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_expire_minutes: int = Field(default=60 * 24, alias="JWT_EXPIRE_MINUTES")  # 24 小时
    
    # 子配置 - 每个子配置独立从环境变量读取
    @property
    def redis(self) -> RedisSettings:
        return _get_redis_settings()
    
    @property
    def mongo(self) -> MongoSettings:
        return _get_mongo_settings()
    
    @property
    def milvus(self) -> MilvusSettings:
        return _get_milvus_settings()
    
    @property
    def tushare(self) -> TushareSettings:
        return _get_tushare_settings()
    
    @property
    def llm(self) -> LLMSettings:
        return _get_llm_settings()
    
    @property
    def observability(self) -> ObservabilitySettings:
        return _get_obs_settings()
    
    @property
    def node(self) -> NodeSettings:
        return _get_node_settings()
    
    @property
    def web(self) -> WebSettings:
        return _get_web_settings()
    
    @property
    def data_sync(self) -> DataSyncSettings:
        return _get_data_sync_settings()
    
    @property
    def listener(self) -> ListenerSettings:
        return _get_listener_settings()
    
    @property
    def notification(self) -> NotificationSettings:
        return _get_notification_settings()
    
    @property
    def feishu(self) -> FeishuSettings:
        return _get_feishu_settings()
    
    @property
    def rpc(self) -> RPCSettings:
        return _get_rpc_settings()


# ==================== 缓存的子配置获取函数 ====================


@lru_cache()
def _get_redis_settings() -> RedisSettings:
    return RedisSettings()


@lru_cache()
def _get_mongo_settings() -> MongoSettings:
    return MongoSettings()


@lru_cache()
def _get_milvus_settings() -> MilvusSettings:
    return MilvusSettings()


@lru_cache()
def _get_tushare_settings() -> TushareSettings:
    return TushareSettings()


@lru_cache()
def _get_llm_settings() -> LLMSettings:
    return LLMSettings()


@lru_cache()
def _get_obs_settings() -> ObservabilitySettings:
    return ObservabilitySettings()


@lru_cache()
def _get_node_settings() -> NodeSettings:
    return NodeSettings()


@lru_cache()
def _get_web_settings() -> WebSettings:
    return WebSettings()


@lru_cache()
def _get_data_sync_settings() -> DataSyncSettings:
    return DataSyncSettings()


@lru_cache()
def _get_listener_settings() -> ListenerSettings:
    return ListenerSettings()


@lru_cache()
def _get_notification_settings() -> NotificationSettings:
    return NotificationSettings()


@lru_cache()
def _get_feishu_settings() -> FeishuSettings:
    return FeishuSettings()


@lru_cache()
def _get_rpc_settings() -> RPCSettings:
    return RPCSettings()


@lru_cache()
def get_settings() -> Settings:
    """获取全局配置单例"""
    return Settings()


# ==================== 全局配置实例 ====================

settings = get_settings()
