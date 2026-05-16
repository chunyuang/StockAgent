"""
回测API公共工具

包含认证辅助、常量、mock任务存储等共享组件。
"""

import logging
from typing import Optional

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from core.settings import settings


oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

logger = logging.getLogger("api.backtest")

# 回测任务计数器，简单过载保护
_running_backtest_count = 0
_MAX_CONCURRENT_BACKTESTS = 3

# Mock回测任务存储，临时使用（超短策略回测）
# 【P2-3修复：添加TTL自动清理机制】
mock_tasks: dict = {}

# mock_tasks TTL配置：任务缓存最多保留5分钟
MOCK_TASKS_TTL_SECONDS = 300

import time

def cleanup_expired_mock_tasks():
    """清理超过TTL的mock_tasks条目，防止内存泄漏"""
    now = time.time()
    expired_keys = [k for k, v in mock_tasks.items() 
                    if isinstance(v, dict) and v.get('_created_at', 0) < now - MOCK_TASKS_TTL_SECONDS]
    for k in expired_keys:
        del mock_tasks[k]
    if expired_keys:
        logger.info(f"[mock_tasks] 清理{len(expired_keys)}条过期缓存")


async def get_optional_user_id(token: Optional[str] = Depends(oauth2_scheme_optional)) -> str:
    """可选登录，没有token返回默认测试用户"""
    if not token:
        return "test_user_001"
    try:
        payload = jwt.decode(token, settings.jwt_secret.get_secret_value(), algorithms=[settings.jwt_algorithm])
        user_id: str = payload.get("sub")
        if user_id is None:
            return "test_user_001"
        return user_id
    except JWTError:
        return "test_user_001"
