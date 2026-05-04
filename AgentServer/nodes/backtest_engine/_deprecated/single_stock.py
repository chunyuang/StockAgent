"""
单股回测执行器 — 已废弃

execute_backtest 已废弃，超短策略回测统一使用 execute_ultra_short_backtest。
单股回测功能如需恢复，请从 git history 恢复本文件的旧版本。
"""

from typing import Optional, Dict


async def execute_backtest(params: dict, node_logger) -> dict:
    """已废弃：单股回测不再使用"""
    return {
        "success": False,
        "error": "单股回测已废弃，请使用超短策略回测（task_type=ultra_short）"
    }


async def fetch_price_data(ts_code: str, start_date: str, end_date: str) -> Optional[Dict]:
    """已废弃：单股行情获取不再使用"""
    return None
