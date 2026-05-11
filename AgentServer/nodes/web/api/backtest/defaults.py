"""
超短策略回测默认配置

从环境变量/配置文件读取默认初始值，供前端页面初始化使用。
所有策略参数从 strategy_defaults.py 读取（单一来源）。
"""

from typing import Dict, Any
from nodes.backtest_engine.strategy_defaults import (
    GLOBAL_RISK,
    STRATEGY_CONFIGS,
    STRATEGY_IDS,
)


def get_ultra_short_defaults() -> Dict[str, Any]:
    """
    获取超短回测页面的默认初始配置

    所有策略参数从 strategy_defaults.py 读取，不在此处硬编码。
    """
    defaults = {
        # 数据源
        "dataSource": {
            "period": "daily",
            "ts_codes": "",
            "start_date": "20260105",
            "end_date": "20260320",
            "adjust_type": "qfq",
        },
        # 基础配置
        "base": {
            "initial_cash": 1000000,
        },
        # 全局筛选
        "globalFilter": {
            "exclude_st": True,
            "exclude_delisting": True,
            "exclude_new_stock_days": 60,
            "min_daily_amount": 500,
            "min_turnover_rate": 3,
        },
        # 强制空仓
        "forceEmpty": {
            "enabled": True,
            "index_drop_pct": 0.03,
            "limit_down_count": 50,
            "limit_up_count": 10,
        },
        # 情绪周期
        "sentimentCycle": {
            "enabled": True,
            "weight_limit_up": 0.25,
            "weight_limit_down": 0.10,
            "weight_blast_rate": 0.07,
            "weight_rise_fall_diff": 0.15,
            "weight_north_inflow": 0.12,
        },
        # 竞价过滤
        "auctionFilter": {
            "enabled": True,
            "min_auction_pct": 0.005,
            "max_auction_pct": 0.07,
            "min_unmatched_volume_positive": True,
            "min_auction_amount": 300,
            "min_auction_volume_ratio": 1.5,
        },
        # 交易参数 — 从单一来源读取
        "tradeParams": {
            "base_stop_loss_pct": GLOBAL_RISK["stop_loss_pct"],
            "base_take_profit_pct": GLOBAL_RISK["take_profit_pct"],
            "max_hold_days": GLOBAL_RISK["max_hold_days"],
            "max_position_per_stock": GLOBAL_RISK["max_position_per_stock"],
            "max_total_position": GLOBAL_RISK["max_total_position"],
            "commission_rate": GLOBAL_RISK["commission_rate"],
            "stamp_duty_rate": GLOBAL_RISK["stamp_duty_rate"],
            "slippage_pct": GLOBAL_RISK["slippage_pct"],
        },
        # 策略启用列表
        "strategies": STRATEGY_IDS,
        # 各策略独立配置 — 从单一来源读取
        "strategyConfigs": {
            sid: {
                "enabled": cfg["enabled"],
                "name": cfg["name"],
                "params": dict(cfg["params"]),
                "riskParams": dict(cfg["riskParams"]),
            }
            for sid, cfg in STRATEGY_CONFIGS.items()
        },
    }
    return defaults
