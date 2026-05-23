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
    "force_empty_limit_down": 80,   # 跌停≥80只触发强制空仓
    "force_empty_limit_up": 10,     # 涨停≤10只触发强制空仓
    "force_empty_index_drop_pct": 0.03,  # 大盘跌幅≥3%触发强制空仓
    "live_trading_mode": False,     # 【V29:实盘模式开关】True时pct_chg等T日因子降级为_prev
}

# ============================================================
# 策略级默认止损映射 — 已废弃
# ⚠️ 【P2-9修复：此映射已删除，统一使用STRATEGY_CONFIGS.riskParams】
# 之前的问题：止损比例在STRATEGY_DEFAULT_STOP_LOSS和riskParams两处定义，可能不一致
# 现在统一从STRATEGY_CONFIGS.riskParams读取，单一来源
# ============================================================

# ============================================================
# 各策略完整配置
# ============================================================
STRATEGY_CONFIGS = {
    "halfway_chase": {
        "id": "halfway_chase",
        "name": "半路追涨",
        "enabled": True,
        "params": {
            "min_rise_pct": 0.03,           # 最小涨幅3%(2%太多噪音,次日胜率仅33%)
            "max_rise_pct": 0.07,           # 最大涨幅7%
            "min_volume_ratio": 2.0,        # 量比≥2.0(V30:保持2.0,2.5太严格导致信号暴降33→3)
            "max_volume_ratio": 3.0,        # 量比≤3.0(>3过热回调,胜率反而下降)
            "min_close_rise_pct": 0.05,     # 收盘涨幅≥5%(⚠近似:盘中趋势判断+收盘确认,见V25未来函数分析)
            "max_open_rise_pct": 0.03,      # 开盘涨幅≤3%(高开>3%追高胜率仅44%,低开冲高81.5%胜率)
            "allow_after_10am": False,      # 不允许10点后买入
            "next_day_open_sell_pct": 0.03, # 次日高开≥3%冲高回落保护(与首板打板高开即卖阈值一致)
        },
        "riskParams": {
            "stop_loss_pct": 0.05,          # 止损5%(保持5%,4%实测收益略降,5%是半路追涨最优止损)
            "take_profit_pct": 0.15,        # 止盈15%(V42:从12%→15%,半路追涨5%止损/15%止盈→盈亏比3.0,更合理)
            "max_hold_days": 3,             # 最大持仓3天
            "slippage_pct": 0.002,          # 滑点0.2%
        }
    },
    "first_limit_up": {
        "id": "first_limit_up",
        "name": "首板打板",
        "enabled": False,  # 【V26:禁用】回测验证胜率仅44.8%,拖累组合(3策略vs4策略:收益+8.78%/胜率+6.54%/回撤-0.50%)
        "params": {
            "opening_pct_min": -1.0,                      # 竞价涨幅下限%(放宽:低开也能涨停)
            "opening_pct_max": 7.0,                      # 竞价涨幅上限%(放宽:高开7%内都考虑)
            "min_volume_ratio": 1.5,                     # 量比≥1.5
            "min_turnover_rate": 3,                      # 换手率≥3%
            "max_turnover_rate": 15,                     # 换手率≤15%
            "min_circulation_market_cap": 50,            # 最小流通市值(亿)
            "max_circulation_market_cap": 500,           # 最大流通市值(亿)
            "hit_probability_yizi": 0.0,                # 一字板成交概率0%
            "hit_probability_fast": 0.3,                 # 秒板(开盘>8%)成交概率30%
            "hit_probability_normal": 0.5,               # 快速板(开盘2-8%)50%
            "hit_probability_slow": 0.7,                 # 盘中板(开盘<2%)70%
            "next_day_open_sell_pct": 0.03, # 次日高开≥3%即卖出(首板高开即卖)
        },
        "riskParams": {
            "stop_loss_pct": 0.04,          # 止损4%
            "take_profit_pct": 0.12,        # 止盈12%
            "max_hold_days": 3,             # 最大持仓3天
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
            "min_turnover_rate": 15.0,                  # 换手率≥15%(统一为百分比形式)
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
    "dragon_head": {
        "id": "dragon_head",
        "name": "龙头低吸",
        "enabled": True,
        "params": {
            "min_consecutive_limit": 1,                 # 最小连板数(1板即可:数据50.5%wr>2板42.2%>3板39.4%)
            "min_circulation_market_cap": 30,           # 最小流通市值30亿
            "min_correction_pct": 0.05,                 # 最小回调5%
            "max_correction_pct": 0.35,                 # 最大回调35%
            "correction_days_min": 1,                   # 回调天数下限
            "correction_days_max": 7,                   # 回调天数上限
            "support_level": "ma5",                     # 支撑位参考
            "min_volume_ratio": 0.5,                    # 量比≥0.5(排除极度冷门,<0.5几乎无成交)
            "max_volume_ratio": 2.0,                    # 量比≤2.0(缩量回调,放量回调危险)
            "next_day_open_sell_pct": 0.03,           # 次日高开≥3%冲高回落保护(V27:与半路追涨/跌停撬板一致)
        },
        "riskParams": {
            "stop_loss_pct": 0.05,          # 止损5%
            "take_profit_pct": 0.15,        # 止盈15%(V27:从10%→15%,回测验证:收益+9.49%/夏普+0.84/盈亏比+0.07,龙头低吸回调利润空间大,10%截断过多利润)
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
            "min_turnover_rate": 10,              # 换手率≥10%(V24:提升为单一来源,消除_build_strategy_filter_conditions中的硬编码)
            "min_qiao_amount": 1000,                    # 翘板金额(万元)
            "min_rise_after_qiao": 0.03,                # 翘板后最小涨幅3%
            "min_circulation_market_cap": 20,            # 最小流通市值20亿(排除小盘操纵,V16:保持20亿,30亿过滤过多跌停翘板候选)
            "require_high_sentiment": False,             # 不要求高情绪
            "next_day_open_sell_pct": 0.03,          # 次日高开≥3%冲高回落保护(与半路追涨/龙头低吸一致)
            "pullback_mid_fallback_pct": 0.015,     # 回落≥1.5%触发(跌停翘板波动大)
        },
        "riskParams": {
            "stop_loss_pct": 0.04,          # 止损4%(V27:从5%→4%,回测验证:收益+1.8%/夏普+0.15/盈亏比+0.04,跌停撬板波动大但4%足够止损)
            "take_profit_pct": 0.20,        # 止盈20%(V42:从25%→20%,回测验证止盈25%仅2笔avg+24.43%,20%多捕获1-2笔更快止盈减少利润回吐)
            "max_hold_days": 3,             # 最大持仓3天
            "slippage_pct": 0.003,          # 滑点0.3%(跌停后波动大)
        }
    },
}

# 策略ID列表（按优先级排序）
STRATEGY_IDS = list(STRATEGY_CONFIGS.keys())

# 兜底策略列表（用于ultra_short.py，格式与前端提交的selected_strategies一致）
# 【P1-5修复(V13)】：只包含enabled=True的策略，避免未启用策略(如涨停开板)被兜底选中
ALL_STRATEGIES = [
    {
        "id": cfg["id"],
        "name": cfg["name"],
        "params": dict(cfg["params"]),
        "riskParams": dict(cfg["riskParams"]),
    }
    for cfg in STRATEGY_CONFIGS.values() if cfg.get("enabled", True)
]


def merge_strategy_params(strategy_id: str, user_params: dict) -> dict:
    """合并用户传入的策略参数与默认值
    
    用户参数优先, 缺失的从STRATEGY_CONFIGS取默认值
    返回完整的参数字典
    """
    defaults = STRATEGY_CONFIGS.get(strategy_id, {}).get("params", {})
    merged = dict(defaults)  # 先复制默认值
    merged.update(user_params)  # 用户参数覆盖
    return merged


def merge_strategy_risk_params(strategy_id: str, user_risk: dict) -> dict:
    """合并用户传入的风控参数与默认值"""
    defaults = STRATEGY_CONFIGS.get(strategy_id, {}).get("riskParams", {})
    merged = dict(defaults)
    merged.update(user_risk or {})
    return merged
