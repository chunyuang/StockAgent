"""Web API 公共工具函数"""
import math


def sanitize_nan(obj):
    """递归清理NaN/inf, 防止JSON序列化失败
    
    统一替代 app.py._sanitize_nan 和 scanner.py._sanitize 的重复定义。
    """
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: sanitize_nan(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_nan(v) for v in obj]
    return obj
