"""
配置验证器

提供配置模式验证和类型安全的配置访问。
"""

import logging
from typing import Dict, Type, TypeVar

from pydantic import BaseModel, Field


logger = logging.getLogger(__name__)


T = TypeVar("T", bound=BaseModel)


class NewsFilterOutputConfig(BaseModel):
    """新闻筛选输出配置模式"""
    max_events: int = Field(default=8, ge=1, le=50)
    min_events: int = Field(default=4, ge=1, le=20)
    importance_threshold: int = Field(default=7, ge=1, le=15)


class ReportPushConfig(BaseModel):
    """报告推送配置模式"""
    wecom_enabled: bool = True
    email_enabled: bool = False
    max_retries: int = Field(default=3, ge=1, le=10)
    timeout: int = Field(default=30, ge=5, le=120)


class CollectorDedupConfig(BaseModel):
    """采集器去重配置模式"""
    redis_ttl_hours: int = Field(default=72, ge=1, le=168)
    memory_cache_max: int = Field(default=10000, ge=100, le=100000)
    title_similarity_threshold: float = Field(default=0.85, ge=0.5, le=1.0)


class ConfigValidator:
    """
    配置验证器
    
    使用 Pydantic 模式验证配置数据。
    
    Example:
        from src.config import config_manager
        from src.config.validators import ConfigValidator, NewsFilterOutputConfig
        
        validator = ConfigValidator(config_manager)
        output_config = validator.validate("news_filter.output", NewsFilterOutputConfig)
    """
    
    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    def validate(
        self,
        key: str,
        schema: Type[T],
        strict: bool = False,
    ) -> T:
        """
        验证配置并返回类型安全的对象
        
        Args:
            key: 配置键
            schema: Pydantic 模式类
            strict: 是否严格模式（失败时抛出异常）
            
        Returns:
            验证后的配置对象
            
        Raises:
            ValueError: 严格模式下验证失败
        """
        raw_config = self.config_manager.get(key, {})
        
        try:
            if isinstance(raw_config, dict):
                return schema(**raw_config)
            else:
                self.logger.warning(f"Config {key} is not a dict, using defaults")
                return schema()
        except Exception as e:
            if strict:
                raise ValueError(f"Config validation failed for {key}: {e}")
            self.logger.warning(f"Config validation failed for {key}: {e}, using defaults")
            return schema()
    
    def validate_all(
        self,
        schemas: Dict[str, Type[BaseModel]],
        strict: bool = False,
    ) -> Dict[str, BaseModel]:
        """
        批量验证多个配置
        
        Args:
            schemas: 键到模式的映射
            strict: 是否严格模式
            
        Returns:
            验证后的配置对象字典
        """
        result = {}
        for key, schema in schemas.items():
            result[key] = self.validate(key, schema, strict)
        return result
