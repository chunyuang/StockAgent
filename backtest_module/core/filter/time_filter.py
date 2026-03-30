"""
时间窗口过滤

根据不同时间段调整策略参与：
- 9:30-10:00 黄金半小时 → 所有策略
- 10:00-11:20 → 所有策略
- 11:20-13:00 → 只做低吸翘板
- 13:00-14:30 → 只做低吸翘板打板
- 14:30 → 仅做龙头低吸

根据不同时间段允许不同策略参与，提高整体胜率
"""

from typing import List, Set, Dict
from enum import Enum


class StrategyType(str, Enum):
    """策略类型"""
    BANZHUANG_ZHUI = "banzhuang_zhui"        # 半路追涨
    ZHANGTING_KAIBAN = "zhangting_kaiban"  # 涨停开板
    DIESHENG_QIAOBAN = "diesheng_qiaoban"    # 跌停翘板
    MA5_DIP = "ma5_dip"                    # MA5低吸
    LONGTOU_DIP = "longtou_dip"              # 龙头低吸
    SHOUBAN_DABAN = "shouban_daban"        # 首板打板


# 时间段配置 (分钟数从开盘开始算，开盘 9:30 = 0 分钟)
TIME_WINDOW_RULES = {
    # (start_minutes, end_minutes): 允许的策略列表
    (0, 30): [  # 9:30-10:00 黄金半小时
        StrategyType.BANZHUANG_ZHUI,
        StrategyType.ZHANGTING_KAIBAN,
        StrategyType.DIESHENG_QIAOBAN,
        StrategyType.MA5_DIP,
        StrategyType.LONGTOU_DIP,
        StrategyType.SHOUBAN_DABAN,
    ],
    (30, 90): [  # 10:00-11:20
        StrategyType.BANZHUANG_ZHUI,
        StrategyType.ZHANGTING_KAIBAN,
        StrategyType.DIESHENG_QIAOBAN,
        StrategyType.MA5_DIP,
        StrategyType.LONGTOU_DIP,
        StrategyType.SHOUBAN_DABAN,
    ],
    (90, 150): [  # 11:20-13:00 (注意: 11:30-13:00 休市，实际 11:20-11:30 = 10分钟)
        StrategyType.DIESHENG_QIAOBAN,
        StrategyType.MA5_DIP,
    ],
    (150, 240): [  # 13:00-14:30 (开盘 13:00 = 150分钟)
        StrategyType.DIESHENG_QIAOBAN,
        StrategyType.MA5_DIP,
        StrategyType.ZHANGTING_KAIBAN,
        StrategyType.SHOUBAN_DABAN,
    ],
    (240, 360): [  # 14:30-15:00
        StrategyType.LONGTOU_DIP,
    ],
}


def is_strategy_allowed(current_time: str, strategy_type: str) -> bool:
    """
    检查当前时间是否允许该策略参与

    Args:
        current_time: 当前时间，格式 "HH:MM" (e.g., "09:45")
        strategy_type: 策略类型，来自 StrategyType

    Returns:
        True = 允许参与，False = 不允许过滤掉
    """
    # 解析当前时间为开盘后分钟数
    hh, mm = map(int, current_time.split(":"))
    # 开盘 9:30 = 0 分钟
    minutes_since_open = (hh - 9) * 60 + (mm - 30)

    # 遍历所有时间窗口
    for (start_min, end_min), allowed_strategies in TIME_WINDOW_RULES.items():
        if start_min <= minutes_since_open < end_min:
            # 当前时间在这个窗口内，检查策略是否允许
            return strategy_type in allowed_strategies

    # 不在任何窗口内 (超过收盘)，不允许
    return False


def filter_by_time_window(
    current_time: str,
    candidate_strategies: Dict[str, List[str]],
) -> Dict[str, List[str]]:
    """
    根据时间窗口过滤候选策略

    Args:
        current_time: 当前时间 "HH:MM"
        candidate_strategies: {strategy_type: [candidate_stocks]}

    Returns:
        过滤后的候选策略，只保留允许的策略
    """
    result: Dict[str, List[str]] = {}

    for strategy, candidates in candidate_strategies.items():
        if is_strategy_allowed(current_time, strategy):
            result[strategy] = candidates

    return result


def get_allowed_strategies(current_time: str) -> Set[str]:
    """
    获取当前时间允许的策略集合

    Args:
        current_time: 当前时间 "HH:MM"

    Returns:
        允许的策略集合
    """
    hh, mm = map(int, current_time.split(":"))
    minutes_since_open = (hh - 9) * 60 + (mm - 30)

    allowed: Set[str] = set()
    for (start_min, end_min), allowed_strategies in TIME_WINDOW_RULES.items():
        if start_min <= minutes_since_open < end_min:
            allowed.update(allowed_strategies)

    return allowed
