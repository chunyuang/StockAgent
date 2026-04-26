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
mock_tasks: dict = {}


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
