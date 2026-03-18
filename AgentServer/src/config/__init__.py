"""
YAML 配置管理模块

提供基于 YAML 文件的配置管理，支持：
- 全局单例访问
- 服务启动时加载到内存
- 热重载（可选）
- 配置继承与覆盖
- Pydantic 模式验证

使用方式:
    from src.config import config_manager
    
    # 获取配置
    keywords = config_manager.get("news_filter.noise_keywords", [])
    
    # 获取整个配置模块
    news_filter_config = config_manager.get_module("news_filter")
    
    # 使用验证器获取类型安全的配置
    from src.config import ConfigValidator, NewsFilterOutputConfig
    validator = ConfigValidator(config_manager)
    output_config = validator.validate("news_filter.output", NewsFilterOutputConfig)
"""

from .manager import ConfigManager, config_manager
from .validators import (
    ConfigValidator,
    NewsFilterOutputConfig,
    ReportPushConfig,
    CollectorDedupConfig,
)

__all__ = [
    "ConfigManager",
    "config_manager",
    "ConfigValidator",
    "NewsFilterOutputConfig",
    "ReportPushConfig",
    "CollectorDedupConfig",
]
