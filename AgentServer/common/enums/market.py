"""
市场相关枚举

V2 双评分系统周期定义:
- 冰点期: 双评分极低，空仓观望
- 修复期: 双评分回暖，轻仓试错
- 主升期: 双评分强势，重仓做多
- 分歧期: 评分背离或趋势背离，半仓龙头
- 退潮期: 双评分走弱，空仓等待
- 混沌期: 无明确周期，轮动观望
"""

from enum import Enum


class MarketCycle(str, Enum):
    """市场周期 (V2 双评分系统)"""
    ICE_POINT = "ice_point"        # 冰点期 - 双评分<20，双走弱/横盘
    RECOVERY = "recovery"          # 修复期 - 20≤双评分<40，双走强
    MAIN_UPWARD = "main_upward"    # 主升期 - 双评分≥60，双走强/横盘
    DIVERGENCE = "divergence"      # 分歧期 - 评分背离或趋势背离
    DECLINE = "decline"            # 退潮期 - 双评分<40，双走弱
    CHAOS = "chaos"                # 混沌期 - 其他情况，轮动行情
    UNKNOWN = "unknown"            # 未知 - 数据不足
    
    # 兼容旧枚举值
    INCUBATION = "incubation"      # 萌芽期 (已合并到 RECOVERY)
    ROTATION = "rotation"          # 分歧/轮动期 (已合并到 DIVERGENCE)


class ThemeStatus(str, Enum):
    """板块状态"""
    MAIN_THEME = "main_theme"       # 当前主线
    STRONG_FOCUS = "strong_focus"   # 强势关注
    RISING = "rising"               # 上升中
    ROTATING = "rotating"           # 轮动中
    FADING = "fading"               # 衰退中
    NORMAL = "normal"               # 普通
