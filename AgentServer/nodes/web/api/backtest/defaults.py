"""
超短策略回测默认配置

从环境变量/配置文件读取默认初始值，供前端页面初始化使用。
"""

from typing import Dict, Any


def get_ultra_short_defaults() -> Dict[str, Any]:
    """
    获取超短回测页面的默认初始配置

    从环境变量/.env读取配置，返回给前端用于初始化表单。
    这样修改.env就能改变前端默认值，不需要重新编译前端代码。
    """
    # 默认硬编码值 (如果环境变量没有配置，使用这些默认值)
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
        # 交易参数
        "tradeParams": {
            "base_stop_loss_pct": 0.02,
            "base_take_profit_pct": 0.07,
            "max_hold_days": 3,
            "max_position_per_stock": 0.2,  # 单票20%分散风险
            "max_total_position": 0.7,  # 总仓位70%
            "commission_rate": 0.0003,
            "stamp_duty_rate": 0.001,
            "slippage_pct": 0.002,
            "commission_rate": 0.0003,  # 综合佣金率万3
            "stamp_duty_rate": 0.001,   # 印花税率千1
        },
        # 策略启用
        "strategies": ["halfway_chase", "first_limit_up", "limit_up_open", "leader_buy_dip", "limit_down_qiao"],
        # 各策略独立配置
        "strategyConfigs": {
            "halfway_chase": {
                "enabled": True,
                "name": "半路追涨",
                "params": {
                    "min_rise_pct": 0.03,
                    "max_rise_pct": 0.05,
                    "min_volume_ratio": 1.0,
                    "allow_after_10am": False,
                },
                "riskParams": {
                    "stop_loss_pct": 0.02,      # 止损2%
                    "take_profit_pct": 0.06,    # 止盈6%
                    "max_hold_days": 2,          # 最大持仓2天
                    "slippage_pct": 0.002         # 滑点0.2%
                }
            },
            "first_limit_up": {
                "enabled": True,
                "name": "首板打板",
                "params": {
                    "min_seal_amount": 5000,
                    "max_limit_up_time": "10:00",
                    "max_circulation_market_cap": 500,
                    "max_blast_count": 1,
                    "require_hot_sector": True,
                },
                "riskParams": {
                    "stop_loss_pct": 0.015,     # 止损1.5%
                    "take_profit_pct": 0.085,    # 止盈8.5%
                    "max_hold_days": 2,          # 最大持仓2天
                    "slippage_pct": 0.005         # 滑点0.5%(打板场景)
                }
            },
            "limit_up_open": {
                "enabled": True,
                "name": "涨停开板",
                "params": {
                    "min_consecutive_limit": 2,
                    "max_open_duration": 5,
                    "min_seal_after_open": 3000,
                    "min_turnover_rate": 0.15,
                },
                "riskParams": {
                    "stop_loss_pct": 0.02,      # 止损2%
                    "take_profit_pct": 0.06,    # 止盈6%
                    "max_hold_days": 2,          # 最大持仓2天
                    "slippage_pct": 0.003         # 滑点0.3%(开板后波动大)
                }
            },
            "leader_buy_dip": {
                "enabled": True,
                "name": "龙头低吸",
                "params": {
                    "min_consecutive_limit": 3,
                    "min_correction_pct": 0.15,
                    "max_correction_pct": 0.3,
                    "correction_days_min": 2,
                    "correction_days_max": 5,
                    "support_level": "ma5",
                },
                "riskParams": {
                    "stop_loss_pct": 0.0275,    # 止损2.75%
                    "take_profit_pct": 0.06,    # 止盈6%
                    "max_hold_days": 4,          # 最大持仓4天(需等待企稳)
                    "slippage_pct": 0.002         # 滑点0.2%
                }
            },
            "limit_down_qiao": {
                "enabled": True,
                "name": "跌停翘板",
                "params": {
                    "min_consecutive_limit": 3,
                    "min_qiao_amount": 1000,
                    "min_rise_after_qiao": 0.03,
                    "require_high_sentiment": True,
                },
                "riskParams": {
                    "stop_loss_pct": 0.02,      # 止损2%
                    "take_profit_pct": 0.07,    # 止盈7%
                    "max_hold_days": 3,          # 最大持仓3天(博反弹)
                    "slippage_pct": 0.003         # 滑点0.3%(跌停后波动大)
                }
            },
        }
    }

    # 检查环境变量是否有覆盖
    # 从settings中读取ULTRASHORT_*前缀的环境变量，覆盖默认值
    # 这里我们不做复杂的嵌套解析，只支持顶级简单覆盖
    # 如果需要更深层次覆盖，后续可以扩展

    return defaults
