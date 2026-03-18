"""
配置管理器

实现 YAML 配置的加载、访问和管理。
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, TypeVar, Union

import yaml


logger = logging.getLogger(__name__)


T = TypeVar("T")


class ConfigManager:
    """
    YAML 配置管理器 (全局单例)
    
    特性：
    - 从 YAML 文件加载配置
    - 支持多配置文件（按模块划分）
    - 点号路径访问：config.get("module.sub.key")
    - 服务启动时一次性加载到内存
    - 支持默认值
    
    目录结构:
        config/
        ├── news_filter.yaml      # 新闻筛选配置
        ├── report.yaml           # 报告生成配置
        ├── collector.yaml        # 采集器配置
        └── ...
    
    Example:
        # 初始化（在服务启动时调用一次）
        config_manager.load()
        
        # 获取配置
        keywords = config_manager.get("news_filter.noise_keywords", [])
        
        # 获取整个模块配置
        news_config = config_manager.get_module("news_filter")
        
        # 获取带类型提示
        limit: int = config_manager.get("report.max_events", 10)
    """
    
    _instance: Optional["ConfigManager"] = None
    
    # 默认配置目录
    DEFAULT_CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._config: Dict[str, Any] = {}
        self._config_dir: Path = self.DEFAULT_CONFIG_DIR
        self._loaded_files: List[str] = []
        self._initialized = True
    
    def load(
        self,
        config_dir: Optional[Union[str, Path]] = None,
        reload: bool = False,
    ) -> int:
        """
        加载配置文件
        
        Args:
            config_dir: 配置目录路径，None 使用默认路径
            reload: 是否重新加载（清空现有配置）
            
        Returns:
            加载的配置文件数量
        """
        if reload:
            self._config.clear()
            self._loaded_files.clear()
        
        if config_dir:
            self._config_dir = Path(config_dir)
        
        if not self._config_dir.exists():
            logger.warning(f"Config directory not found: {self._config_dir}")
            # 创建默认目录
            self._config_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created config directory: {self._config_dir}")
            return 0
        
        count = 0
        for yaml_file in self._config_dir.glob("*.yaml"):
            try:
                module_name = yaml_file.stem
                self._load_file(yaml_file, module_name)
                count += 1
            except Exception as e:
                logger.error(f"Failed to load config {yaml_file}: {e}")
        
        # 也加载 .yml 扩展名的文件
        for yaml_file in self._config_dir.glob("*.yml"):
            try:
                module_name = yaml_file.stem
                if module_name not in self._config:  # 避免重复
                    self._load_file(yaml_file, module_name)
                    count += 1
            except Exception as e:
                logger.error(f"Failed to load config {yaml_file}: {e}")
        
        logger.info(f"Loaded {count} config files from {self._config_dir}")
        return count
    
    def _load_file(self, file_path: Path, module_name: str) -> None:
        """加载单个配置文件"""
        with open(file_path, "r", encoding="utf-8") as f:
            content = yaml.safe_load(f)
        
        if content is None:
            content = {}
        
        self._config[module_name] = content
        self._loaded_files.append(str(file_path))
        logger.debug(f"Loaded config module: {module_name}")
    
    def get(
        self,
        key: str,
        default: T = None,
    ) -> Union[Any, T]:
        """
        获取配置值
        
        支持点号分隔的路径访问:
            config.get("news_filter.noise_keywords")
            config.get("report.max_events", 10)
        
        Args:
            key: 配置键，支持点号路径
            default: 默认值
            
        Returns:
            配置值或默认值
        """
        parts = key.split(".")
        value = self._config
        
        try:
            for part in parts:
                if isinstance(value, dict):
                    value = value[part]
                else:
                    return default
            return value
        except KeyError:
            return default
    
    def get_module(self, module_name: str) -> Dict[str, Any]:
        """
        获取整个模块的配置
        
        Args:
            module_name: 模块名（对应 yaml 文件名）
            
        Returns:
            模块配置字典，不存在返回空字典
        """
        return self._config.get(module_name, {})
    
    def set(self, key: str, value: Any) -> None:
        """
        动态设置配置值（运行时）
        
        注意：此方法不会持久化到文件
        
        Args:
            key: 配置键，支持点号路径
            value: 配置值
        """
        parts = key.split(".")
        config = self._config
        
        for part in parts[:-1]:
            if part not in config:
                config[part] = {}
            config = config[part]
        
        config[parts[-1]] = value
    
    def has(self, key: str) -> bool:
        """检查配置是否存在"""
        return self.get(key) is not None
    
    @property
    def is_loaded(self) -> bool:
        """是否已加载配置"""
        return len(self._loaded_files) > 0
    
    @property
    def config_dir(self) -> Path:
        """配置目录路径"""
        return self._config_dir
    
    @property
    def loaded_files(self) -> List[str]:
        """已加载的配置文件列表"""
        return self._loaded_files.copy()
    
    def list_modules(self) -> List[str]:
        """列出所有已加载的配置模块"""
        return list(self._config.keys())
    
    def reload(self) -> int:
        """重新加载所有配置"""
        return self.load(reload=True)
    
    def to_dict(self) -> Dict[str, Any]:
        """导出所有配置为字典"""
        return self._config.copy()


# 全局单例实例
config_manager = ConfigManager()
