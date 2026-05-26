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
    "max_position_per_stock": 0.35,  # 单票最大仓位35%(3只均分=33%,留2%buffer,避免资金闲置)
    "max_total_position": 0.7,      # 总仓位上限70%
    "liquidity_threshold": 500,     # 流动性门槛(万元)
    "volume_threshold": 1.5,        # 量能放大倍数(首板打板等用)
    "force_empty_limit_down": 80,   # 跌停≥80只触发强制空仓
    "force_empty_limit_up": 10,     # 涨停≤10只触发强制空仓
    "force_empty_index_drop_pct": 0.03,  # 大盘跌幅≥3%触发强制空仓
    "intraday_lock_min_high_rise": 0.05,  # 盘中利润锁定:冲高≥5%(V59:从4%→5%,减少过早锁定;V58回撤5.06% vs V57回撤3.09%,根因是4%+1.5%组合过早触发利润锁定,导致盈利股过早退出+现金闲置→回撤增大)
    "intraday_lock_pullback_pct": 0.02,    # 盘中利润锁定:从高点回撤≥2%(V59:从1.5%→2%,减少误触发;1.5%在超短线正常波动内,大量盈利股被过早锁定退出)
    "intraday_lock_min_profit": 0.02,     # 盘中利润锁定:收盘仍≥2%利润(保持不变)
    "hold_protection_threshold": 0.05,     # 【V59:从4%→5%】V58回撤5.06%根因之一:4%保护阈值过窄,盈利4-5%的股票失去保护被调仓卖出,但它们可能正在上涨中,卖出后反弹→回撤增大
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
            "next_day_open_sell_pct": 0.02, # 次日高开≥2%冲高回落保护(V53:从3%→2%,半路追涨次日冲高2%+即有回落风险,更早锁定利润)
            "pullback_mid_fallback_pct": 0.01,          # 冲高回落mid_fallback=1%(V55-LIVE-009:补充缺失参数,与回测STRATEGY_PULLBACK_PARAMS对齐)
            "pullback_high_threshold": 0.05,             # 冲高回落直接触发阈值=5%(V55-LIVE-009:补充缺失参数,与回测STRATEGY_PULLBACK_PARAMS对齐)
        },
        "riskParams": {
            "stop_loss_pct": 0.03,          # 止损3%(V57:从4%→3%,V55基线4笔止损平均-3.65%偏大;3%更早截断,降低单笔最大亏损,目标回撤<5%)
            "take_profit_pct": 0.12,        # 止盈12%(V20:从10%→12%,12%比15%多捕获1-2笔快止盈)
            "max_hold_days": 3,             # 最大持仓3天
            "slippage_pct": 0.002,          # 滑点0.2%
            "trailing_stop_pct": 0.02,       # 追踪止损2%(盈利>=2%后激活,从最高价回撤2%触发,锁住大部分利润)
        }
    },
    "first_limit_up": {
        "id": "first_limit_up",
        "name": "首板打板",
        "enabled": True,  # 首板打板策略，配合成交概率模拟
        "params": {
            "opening_pct_min": -1.0,                      # 竞价涨幅下限%(放宽:低开也能涨停)
            "opening_pct_max": 5.0,                      # 竞价涨幅上限%(优化C:从7%→5%,排除高开>5%的追高风险)
            "min_volume_ratio": 1.5,                     # 量比≥1.5(保持1.5,2.0过严导致信号暴降)
            "min_turnover_rate": 8,                      # 换手率≥8%(优化A:从5→8,过滤低质量涨停,首板胜率47.4%是最大拖累)
            "max_turnover_rate": 15,                     # 换手率≤15%
            "min_circulation_market_cap": 50,            # 最小流通市值50亿(保持50,80过严)
            "max_circulation_market_cap": 500,           # 最大流通市值(亿)
            "hit_probability_yizi": 0.0,                # 一字板成交概率0%(不可能买入)
            "hit_probability_fast": 0.20,                 # 秒板(开盘>8%)成交概率20%(V37:恢复20%,V36上调25%未带来显著改善且可能导致过多低质量成交)
            "hit_probability_normal": 0.40,              # 快速板(开盘2-8%)40%(V57:从45%→40%,收紧成交概率降低低质量信号;跳空止损-8.95%是最大回撤来源)
            "hit_probability_slow": 0.45,                # 盘中板(开盘<2%)45%(V57:从60%→45%,首板跳空止损极端亏损-8.95%,需更严格筛选;配合2.5%止损双保险)
            "next_day_open_sell_pct": 0.02, # 次日高开≥2%冲高回落保护(V53:从3%→2%,首板高开2%+即有回落风险,更早保护减少利润回吐)
        },
        "riskParams": {
            "stop_loss_pct": 0.025,         # 止损2.5%(V57:从3%→2.5%,跳空止损-8.95%是最大回撤来源;2.5%更早截断,跳空时亏损从-6%降至-3%左右)
            "take_profit_pct": 0.08,          # 止盈8%(V53:从10%→8%,首板avg_win仅4.3%,8%止盈更实际,10%几乎不触发)
            "max_hold_days": 2,             # 最大持仓2天(V33:3→2,首板次日未兑现即退出)
            "slippage_pct": 0.005,          # 滑点0.5%(打板场景)
            "trailing_stop_pct": 0.02,       # 追踪止损2%(首板高开多,盈利2%后激活,快速锁利)
        }
    },
    "limit_up_open": {
        "id": "limit_up_open",
        "name": "涨停开板",
        "enabled": False,  # 默认关闭：胜率<30%
        "params": {
            "min_consecutive_limit": 2,                 # 最小连板数
            "max_consecutive_limit": 4,                 # 最大连板数(4板以上风险大)
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
            "max_correction_pct": 0.22,                 # 最大回调22%(优化D:从20%→22%,稍微放宽回调上限,龙头低吸V52胜率90.6%→当前87.5%微降)
            "correction_days_min": 1,                   # 回调天数下限
            "correction_days_max": 7,                   # 回调天数上限
            "support_level": "ma5",                     # 支撑位参考
            "min_volume_ratio": 0.5,                    # 量比≥0.5(排除极度冷门,<0.5几乎无成交)
            "max_volume_ratio": 2.0,                    # 量比≤2.0(缩量回调,放量回调危险)
            "next_day_open_sell_pct": 0.02,           # 次日高开≥2%冲高回落保护(V53:从3%→2%,龙头低吸买在低位,高开2%+已有回落风险,更早锁定利润)
            "pullback_mid_fallback_pct": 0.015,         # 冲高回落mid_fallback=1.5%(V55-LIVE-009:补充缺失参数,与回测STRATEGY_PULLBACK_PARAMS对齐,龙头波动大)
            "pullback_profit_lock_threshold": 0.06,       # 冲高回落利润保护≥6%(V55-LIVE-009:补充缺失参数,利润≥6%时不触发冲高回落,让利润锁定/超时自然退出;与回测STRATEGY_PULLBACK_PARAMS对齐)
            "pullback_high_threshold": 0.05,             # 冲高回落直接触发阈值=5%(V55-LIVE-009:补充缺失参数,与回测STRATEGY_PULLBACK_PARAMS对齐)
        },
        "riskParams": {
            "stop_loss_pct": 0.03,          # 止损3%(V45:从4%→3%,龙头低吸是缩量回调买入,止损应最紧,3月验证+4.11%收益/夏普+0.28/回撤-0.20%/盈亏比+0.39)
            "take_profit_pct": 0.30,          # 止盈30%(V38:从15%→30%,回测验证+15.68%收益/夏普+0.05,仅1笔触发30%止盈,其余由冲高回落/利润保护在更高价位退出,30%作为极端行情安全网)
            "max_hold_days": 7,             # 最大持仓7天(V47:从5→7,龙头低吸捕捉大趋势,51.69%和33.55%的超时退出说明5天太短截断大牛)
            "slippage_pct": 0.002,          # 滑点0.2%
            "trailing_stop_pct": 0.03,       # 追踪止损3%(龙头低吸波动较大,给3%空间避免被震出)
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
            "next_day_open_sell_pct": 0.02,          # 次日高开≥2%冲高回落保护(V53:从3%→2%,跌停翘板波动大,高开2%+即有回落风险)
            "pullback_mid_fallback_pct": 0.015,     # 回落≥1.5%触发(跌停翘板波动大)
            "pullback_high_threshold": 0.05,             # 冲高回落直接触发阈值=5%(V55-LIVE-009:补充缺失参数,与回测STRATEGY_PULLBACK_PARAMS对齐)
        },
        "riskParams": {
            "stop_loss_pct": 0.05,          # 止损5%(V39:从4%→5%,跌停翘板是极端波动股,止损应更宽,组合优化+1.80%收益)
            "take_profit_pct": 0.20,        # 止盈20%(V42:从25%→20%,回测验证止盈25%仅2笔avg+24.43%,20%多捕获1-2笔更快止盈减少利润回吐)
            "max_hold_days": 3,             # 最大持仓3天
            "slippage_pct": 0.003,          # 滑点0.3%(跌停后波动大)
            "trailing_stop_pct": 0.04,       # 追踪止损4%(跌停翘板波动极大,4%空间避免被震出)
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

# 【V55-LIVE-003:统一策略ID↔名称映射,避免散落多处】
# 旧问题: paper_trading/position_manager/generate_daily_signals各自独立维护映射,易遗漏
STRATEGY_ID_TO_NAME = {sid: cfg["name"] for sid, cfg in STRATEGY_CONFIGS.items()}
STRATEGY_NAME_TO_ID = {cfg["name"]: sid for sid, cfg in STRATEGY_CONFIGS.items()}


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
