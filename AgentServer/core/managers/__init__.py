"""
资源管理器 (单例模式)

所有外部服务必须通过全局 Manager 单例访问。
禁止在业务代码中直接 import 外部库。

Example:
    from core.managers import tushare_manager
    
    # 确保已初始化 (在 main.py lifespan 中完成)
    data = await tushare_manager.get_daily("000001.SZ")
    
使用规范:
    1. 导入: from core.managers import redis_manager, mongo_manager, ...
    2. 初始化: 在 main.py 的 lifespan 中按依赖顺序调用 await xxx_manager.initialize()
    3. 调用: 直接使用全局单例的方法
"""

from .base import BaseManager
from .redis_manager import RedisManager, redis_manager
from .mongo_manager import MongoManager, mongo_manager
from .tushare_manager import TushareManager, tushare_manager
from .llm_manager import LLMManager, llm_manager
from .milvus_manager import MilvusManager, milvus_manager
from .analysis_manager import AnalysisManager, analysis_manager, MarketCycle
from .theme_manager import ThemeManager, theme_manager, ThemeStatus
from .prompt_manager import PromptManager, prompt_manager
from .notification_manager import NotificationManager, notification_manager
from .feishu_bitable_manager import FeishuBitableManager, feishu_bitable_manager
from .baostock_manager import BaostockManager, baostock_manager
from .akshare_manager import AKShareManager, akshare_manager
from .akshare_daily_manager import AKShareDailyManager, akshare_daily_manager
from .local_mongo_manager import LocalMongoManager, local_mongo_manager

__all__ = [
    # 基类
    "BaseManager",
    # Manager 类 (用于类型标注)
    "RedisManager",
    "MongoManager",
    "TushareManager",
    "BaostockManager",
    "LLMManager",
    "MilvusManager",
    "AnalysisManager",
    "MarketCycle",
    "ThemeManager",
    "ThemeStatus",
    "PromptManager",
    "NotificationManager",
    "FeishuBitableManager",
    "AKShareManager",
    "AKShareDailyManager",
    "LocalMongoManager",
    # 全局单例 (推荐使用)
    "redis_manager",
    "mongo_manager",
    "tushare_manager",
    "baostock_manager",
    "llm_manager",
    "milvus_manager",
    "analysis_manager",
    "theme_manager",
    "prompt_manager",
    "notification_manager",
    "feishu_bitable_manager",
    "akshare_manager",
    "akshare_daily_manager",
    "local_mongo_manager",
]


async def initialize_all_managers() -> None:
    """
    按依赖顺序初始化所有管理器
    
    初始化顺序:
    1. Redis (基础设施)
    2. MongoDB (基础设施)
    3. LocalMongo (本地数据源 - 依赖 MongoDB)
    4. Tushare (网络数据源)
    5. Baostock (免费历史数据源)
    6. LLM (AI 服务)
    7. Milvus (向量数据库)
    8. Prompt (提示词管理)
    9. Notification (通知服务)
    10. Feishu (多维表格)
    """
    await redis_manager.initialize()
    await mongo_manager.initialize()
    await local_mongo_manager.initialize()
    await tushare_manager.initialize()
    await baostock_manager.initialize()
    await akshare_manager.initialize()
    await akshare_daily_manager.initialize()
    await llm_manager.initialize()
    await milvus_manager.initialize()
    await prompt_manager.initialize()
    await notification_manager.initialize()
    await feishu_bitable_manager.initialize()


async def shutdown_all_managers() -> None:
    """关闭所有管理器"""
    await akshare_daily_manager.shutdown()
    await akshare_manager.shutdown()
    await baostock_manager.shutdown()
    await local_mongo_manager.shutdown()
    await feishu_bitable_manager.shutdown()
    await notification_manager.shutdown()
    await prompt_manager.shutdown()
    await milvus_manager.shutdown()
    await llm_manager.shutdown()
    await tushare_manager.shutdown()
    await mongo_manager.shutdown()
    await redis_manager.shutdown()


async def health_check_all() -> dict[str, bool]:
    """检查所有管理器健康状态"""
    return {
        "redis": await redis_manager.health_check(),
        "mongo": await mongo_manager.health_check(),
        "local_mongo": await local_mongo_manager.health_check(),
        "tushare": await tushare_manager.health_check(),
        "akshare_daily": await akshare_daily_manager.health_check(),
        "llm": await llm_manager.health_check(),
        "milvus": await milvus_manager.health_check(),
        "notification": await notification_manager.health_check(),
    }
