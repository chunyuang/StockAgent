"""
策略参数单一来源（Single Source of Truth）

所有策略的选股参数、风控参数只在这里定义一次。
其他文件（defaults.py / models.py / ultra_short.py / portfolio_backtest.py / 前端Vue）
都必须从这里读取，不允许硬编码默认值。

修改策略参数只需要改这个文件。
"""

# ============================================================
# 全局风控参数
# ============================================================
GLOBAL_RISK = {
    "stop_loss_pct": 0.03,          # 全局默认止损3%
    "take_profit_pct": 0.07,        # 全局默认止盈7%
    "max_hold_days": 3,             # 全局默认最大持仓3天
    "slippage_pct": 0.002,          # 全局默认滑点0.2%
    "commission_rate": 0.0003,      # 综合佣金率万3
    "stamp_duty_rate": 0.001,       # 印花税率千1
    "max_position_per_stock": 0.2,  # 单票最大仓位20%
    "max_total_position": 0.7,      # 总仓位上限70%
    "liquidity_threshold": 500,     # 流动性门槛(万元)
    "volume_threshold": 1.5,        # 量能放大倍数(首板打板等用)
}

# ============================================================
# 策略级默认止损映射（当策略没有传riskParams时的兜底）
# ============================================================
STRATEGY_DEFAULT_STOP_LOSS = {
    "半路追涨": 0.03,
    "首板打板": 0.04,
    "涨停开板": 0.05,
    "龙头低吸": 0.05,
    "跌停翘板": 0.07,
}

# ============================================================
# 各策略完整配置
# ============================================================
STRATEGY_CONFIGS = {
    "halfway_chase": {
        "id": "halfway_chase",
        "name": "半路追涨",
        "enabled": True,
        "params": {
            "min_rise_pct": 0.02,           # 最小涨幅2%
            "max_rise_pct": 0.07,           # 最大涨幅7%
            "min_volume_ratio": 2.0,        # 量比≥2.0
            "allow_after_10am": False,      # 不允许10点后买入
        },
        "riskParams": {
            "stop_loss_pct": 0.03,          # 止损3%
            "take_profit_pct": 0.07,        # 止盈7%
            "max_hold_days": 2,             # 最大持仓2天
            "slippage_pct": 0.002,          # 滑点0.2%
        }
    },
    "first_limit_up": {
        "id": "first_limit_up",
        "name": "首板打板",
        "enabled": True,
        "params": {
            "min_seal_amount": 5000,                    # 最小封单金额(万元)
            "max_limit_up_time": "10:00",               # 最晚涨停时间
            "min_circulation_market_cap": 50,            # 最小流通市值(亿)
            "max_circulation_market_cap": 500,           # 最大流通市值(亿)
            "max_blast_count": 1,                        # 最大开板次数
            "require_hot_sector": False,                 # 不要求热门板块
            "opening_pct_min": 2.0,                      # 竞价涨幅下限%
            "opening_pct_max": 5.0,                      # 竞价涨幅上限%
            "min_volume_ratio": 1.5,                     # 量比≥1.5
            "min_turnover_rate": 3,                      # 换手率≥3%
            "max_turnover_rate": 15,                     # 换手率≤15%
        },
        "riskParams": {
            "stop_loss_pct": 0.04,          # 止损4%
            "take_profit_pct": 0.12,        # 止盈12%(提高:首板成功往往涨幅大)
            "max_hold_days": 3,             # 最大持仓3天(延长:让利润奔跑)
            "slippage_pct": 0.005,          # 滑点0.5%(打板场景)
        }
    },
    "limit_up_open": {
        "id": "limit_up_open",
        "name": "涨停开板",
        "enabled": False,  # 默认关闭：胜率<30%
        "params": {
            "min_consecutive_limit": 2,                 # 最小连板数
            "max_open_duration": 5,                     # 最大开板时长(分钟)
            "min_seal_after_open": 3000,                # 开板后最小封单(万元)
            "min_turnover_rate": 0.15,                  # 换手率
            "opening_pct_min": -3.0,                    # 竞价涨幅下限%
            "opening_pct_max": 3.0,                     # 竞价涨幅上限%
            "min_volume_ratio": 2.0,                    # 量比≥2.0
        },
        "riskParams": {
            "stop_loss_pct": 0.05,          # 止损5%
            "take_profit_pct": 0.06,        # 止盈6%
            "max_hold_days": 2,             # 最大持仓2天
            "slippage_pct": 0.003,          # 滑点0.3%(开板后波动大)
        }
    },
    "leader_buy_dip": {
        "id": "leader_buy_dip",
        "name": "龙头低吸",
        "enabled": True,
        "params": {
            "min_consecutive_limit": 2,                 # 最小连板数
            "min_circulation_market_cap": 50,           # 最小流通市值(亿)
            "min_correction_pct": 0.08,                 # 最小回调8%
            "max_correction_pct": 0.35,                 # 最大回调35%
            "correction_days_min": 1,                   # 回调天数下限
            "correction_days_max": 7,                   # 回调天数上限
            "support_level": "ma5",                     # 支撑位参考
        },
        "riskParams": {
            "stop_loss_pct": 0.05,          # 止损5%
            "take_profit_pct": 0.06,        # 止盈6%
            "max_hold_days": 4,             # 最大持仓4天
            "slippage_pct": 0.002,          # 滑点0.2%
        }
    },
    "limit_down_qiao": {
        "id": "limit_down_qiao",
        "name": "跌停翘板",
        "enabled": True,
        "params": {
            "min_consecutive_limit": 2,                 # 最小连跌数
            "min_qiao_amount": 1000,                    # 翘板金额(万元)
            "min_rise_after_qiao": 0.03,                # 翘板后最小涨幅3%
            "require_high_sentiment": False,             # 不要求高情绪
        },
        "riskParams": {
            "stop_loss_pct": 0.07,          # 止损7%
            "take_profit_pct": 0.07,        # 止盈7%
            "max_hold_days": 3,             # 最大持仓3天
            "slippage_pct": 0.003,          # 滑点0.3%(跌停后波动大)
        }
    },
}

# 策略ID列表（按优先级排序）
STRATEGY_IDS = list(STRATEGY_CONFIGS.keys())

# 兜底策略列表（用于ultra_short.py，格式与前端提交的selected_strategies一致）
ALL_STRATEGIES = [
    {
        "id": cfg["id"],
        "name": cfg["name"],
        "params": dict(cfg["params"]),
        "riskParams": dict(cfg["riskParams"]),
    }
    for cfg in STRATEGY_CONFIGS.values()
]
