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
    "max_position_per_stock": 0.35,  # 单票最大仓位35%(V62:保持35%,但增加持仓分散度,单日新买入≤4只,防止单日6只同暴跌)
    "max_total_position": 0.75,      # 总仓位上限75%(V62:从70%→75%,70%过严导致2月收益下降113%;75%在3/28回撤场景下仍能降低集中度)
    "liquidity_threshold": 500,     # 流动性门槛(万元)
    "volume_threshold": 1.5,        # 量能放大倍数(首板打板等用)
    "force_empty_limit_down": 80,   # 跌停≥80只触发强制空仓
    "force_empty_limit_up": 10,     # 涨停≤10只触发强制空仓
    "force_empty_index_drop_pct": 0.03,  # 大盘跌幅≥3%触发强制空仓
    "force_empty_cooldown_days": 2,       # 【V63-P0-4:强制空仓冷却期(交易日)】强制空仓后N天内position_multiplier上限0.5,防止次日立即满仓
    "force_empty_cooldown_position_cap": 0.6,  # 【V64-P1-3:冷却期仓位上限(从0.5提升为0.6),V63收益下降9%主因是冷却期0.5过严,0.6在回撤控制与收益间更好平衡】
    "dragon_head_early_exit_days": 5,      # 【V64-P1-2:龙头低吸低利润提前退出天数(从5硬编码提升为可配置参数)】
    "dragon_head_early_exit_min_profit": 0.03,      # 【V72:从0.04→0.03,龙头低吸5天利润<3%提前退出;V67从0.03→0.04后多笔3-4%盈利股被过早退出;3%是最低有意义的利润阈值,4%过严截断了3-4%的稳健盈利交易;V69验证5%过宽,3%比4%多捕获2-3笔盈利交易,龙头胜率93.5%说明3%+的持仓基本安全】
    "intraday_lock_min_high_rise": 0.06,  # 盘中利润锁定:冲高≥6%(V67:从5%→6%,5%对超短线来说偏低,3-5%的日内冲高很常见,过早锁定导致大量盈利股被退出;6%只在真正大冲高时触发,配合2.5%回撤阈值更精确;V72验证5%→325.41%回退-1.37%,5%过敏感;V73验证5.5%导致龙头低吸收益-16%因为超时交易(28%avg)被过早锁定)
    "intraday_lock_pullback_pct": 0.025,    # 盘中利润锁定:从高点回撤≥2.5%(V68:从2%→2.5%,2%回撤在超短线中偏敏感,日内2%回撤很常见;2.5%减少误触发,只在真正大幅回撤时触发;V69验证3%过宽导致-21%收益下降,2.5%仍是最优)
    "intraday_lock_min_profit": 0.02,     # 盘中利润锁定:收盘仍≥2%利润(保持不变)
    "hold_protection_threshold": 0.06,     # 【V67:从5%→6%】持仓保护阈值提升:盈利≥6%的股不让调仓卖出;5%保护了龙头低吸低利润股,但6%以上的盈利股更有可能继续上涨,5%→6%减少被调仓卖出的潜在大牛
    "enable_ma60_filter": True,       # 【v2.9.92x】大盘MA60过滤:大盘跌破MA60时仓位×0.5(与回测对齐)
    "sector_concentration_top_n": 3,  # 【v2.9.92x】板块集中度:同行业最多N只(与回测对齐)
    "live_trading_mode": False,     # 【V29:实盘模式开关】True时pct_chg等T日因子降级为_prev
    "risk_free_rate": 0.03,        # 【V64-P2-3:无风险利率,用于夏普/索提诺计算(从0.03/252硬编码提升为可配置参数)】
    # 【V67:情绪仓位单一来源(Single Source of Truth)】
    # 所有消费方(EmotionCycleManager/live_filter_pipeline/portfolio_backtest/emotion_cycle.py)
    # 必须从此读取,不允许各自硬编码。修改仓位系数只改这里。
    "sentiment_position_map": {
        "rising": 1.0,              # 高潮期(≥70): 满仓
        "differentiation": 0.7,    # 分化期(55-70): 七仓
        "chaos": 0.5,              # 震荡期(40-55): 半仓
        "bearish": 0.3,            # 冰点期(<40): 三仓
    },
    # 情绪阶段阈值(也统一在这里)
    "sentiment_thresholds": {
        "rising": 70,               # ≥70 高潮
        "differentiation": 55,      # 55-70 分化
        "chaos": 40,                # 40-55 震荡
        # <40 冰点
    },
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
            "min_volume_ratio": 1.5,        # 量比≥1.5(V72:保持1.5,V67从2.0→1.5已验证信号量增加且胜率>70%)
            "max_volume_ratio": 3.0,        # 量比≤3.0(>3过热回调,胜率反而下降)
            "min_close_rise_pct": 0.05,     # 收盘涨幅≥5%(⚠近似:盘中趋势判断+收盘确认,见V25未来函数分析)
            "max_open_rise_pct": 0.03,      # 开盘涨幅≤3%(高开>3%追高胜率仅44%,低开冲高81.5%胜率)
            "allow_after_10am": False,      # 不允许10点后买入
            "next_day_open_sell_pct": 0.02, # 次日高开≥2%冲高回落保护(V53:从3%→2%,半路追涨次日冲高2%+即有回落风险,更早锁定利润)
            "pullback_mid_fallback_pct": 0.015,          # 冲高回落mid_fallback=1.5%(V65:1%→1.5%,日内1%波动即触发过敏感,正常回落不应误判;与回测STRATEGY_PULLBACK_PARAMS对齐)
            "pullback_high_threshold": 0.05,             # 冲高回落直接触发阈值=5%(V55-LIVE-009:补充缺失参数,与回测STRATEGY_PULLBACK_PARAMS对齐)
            "pullback_profit_lock_threshold": 0.08,     # V65:半路追涨利润≥8%时不触发冲高回落,让利润锁定/超时处理;与回测STRATEGY_PULLBACK_PARAMS对齐;V72验证6%→323.42%回退-3.36%,6%过敏感导致本应冲高回落退出的6-8%股被保护到利润锁定退出(close价<open价)
        },
        "riskParams": {
            "stop_loss_pct": 0.03,          # 止损3%(V64:保持3%,3.5%虽减少跳空误杀但盈亏比从2.70→2.58,总体收益微降;3%仍是半路追涨最优止损)
            "take_profit_pct": 0.12,        # 止盈12%(V20:从10%→12%,12%比15%多捕获1-2笔快止盈;V72验证15%减少止盈触发21→15笔收益-6%,12%是最优)
            "max_hold_days": 3,             # 最大持仓3天
            "hold_protection_threshold": 0.04,     # 【V71-P0-1:半路追涨持仓保护4%】V72验证5%过严导致利润锁定/冲高回落过多代替止盈,4%保护2-5%盈利股免于调仓卖出同时止盈12%能正常触发;5%→4%收益326.78%→320.46%回退-6%,4%仍是最优;V73验证3%回退-62%因为3-4%区间股被保护后持有到止损而非微利调仓
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
            "hit_probability_normal": 0.45,              # 快速板(开盘2-8%)45%(V72:从40%→45%,首板信号量瓶颈;V57收紧40%后首板交易仅13笔,信号过少;快速板封板质量好,45%合理)
            "hit_probability_slow": 0.55,                # 盘中板(开盘<2%)55%(V72:从45%→55%,首板信号量瓶颈;慢板多是大盘股封板稳定,55%更接近实际;首板仅13笔信号过少是收益损失主因;V70之前55%运行稳定)
            "next_day_open_sell_pct": 0.02, # 次日高开≥2%冲高回落保护(V53:从3%→2%,首板高开2%+即有回落风险,更早保护减少利润回吐)
        },
        "riskParams": {
            "stop_loss_pct": 0.035,         # 止损3.5%(V70:从3%→3.5%,首板波动大,3%止损5笔+跳空4笔=9笔/21笔=42.9%止损率过高;3.5%给首板更多空间避免被日内波动误杀;首板avg_loss=-3.16%说明3%止损基本全部触发,3.5%可减少跳空误杀)
            "take_profit_pct": 0.10,          # 止盈10%(V64:从8%→10%,首板盈亏比2.04最低,8%止盈过早截断盈利,10%让盈利跑更远;首板avg_win仅4.3%,8%几乎不触发止盈,10%同样但预留更多上涨空间)
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
            "stop_loss_pct": 0.03,          # 止损3%(V68:从3.5%→3%,V65扩至3.5%后2笔3.5%止损后续反弹,但反弹不具普遍性;3%配合hold_protection(盈利+阳线不卖)和利润锁定机制可有效避免误杀;V67基线龙头低吸胜率93.5%说明大部分持仓不需要3.5%的宽止损空间;V68验证回撤从3.65%降至3.16%)
            "take_profit_pct": 0.30,          # 止盈30%(V38:从15%→30%,回测验证+15.68%收益/夏普+0.05,仅1笔触发30%止盈,其余由冲高回落/利润保护在更高价位退出,30%作为极端行情安全网)
            "max_hold_days": 7,             # 最大持仓7天(V47:从5→7,龙头低吸捕捉大趋势,51.69%和33.55%的超时退出说明5天太短截断大牛)
            "hold_protection_threshold": 0.04,     # 【V71-P0-1:龙头低吸持仓保护4%】低于全局6%,龙头低吸max_hold=7天,4%盈利+阳线说明趋势仍在,不应被调仓卖出;9笔调仓卖出中2笔盈利4-5%被6%阅值漏过,4%可保护这些股继续持有到利润锁定/止盈退出
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
            "pullback_profit_lock_threshold": 0.10,     # V65:跌停翘板利润≥10%时不触发冲高回落;与回测STRATEGY_PULLBACK_PARAMS对齐
        },
        "riskParams": {
            "stop_loss_pct": 0.05,          # 止损5%(V72:4.5%回退→5%;4.5%止损被跳空触发2笔增加亏损,5%给跌停翘板足够空间;跌停翘板波动极大是固有特征,4.5%过严反而增加跳空止损概率)
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

# 【V75:策略别名映射 — scanner内部使用的anomaly_*等ID映射到正式策略】
# 问题: strategy_scorer.py发出的anomaly_surge/strong/broken不在STRATEGY_CONFIGS中,
# 导致策略配置API/参数中心/归因分析无法正确关联这些策略
# 所有消费方通过此映射将别名归一化到正式策略ID
STRATEGY_ALIASES = {
    "anomaly_surge": "halfway_chase",    # 急速拉升 → 半路追涨
    "anomaly_strong": "halfway_chase",   # 强势涨停 → 半路追涨(已封板,逻辑接近)
    "anomaly_broken": "limit_down_qiao", # 涨停炸板 → 跌停翘板(开板逻辑)
    # ⚠️ 注意: limit_up_open是STRATEGY_CONFIGS中的正式策略(涨停开板),不能放入ALIASES
    # 否则normalize_strategy_id会把合法策略ID错误映射到另一个策略
    # 历史兼容映射由scanner_review.py的strategy_name_aliases单独处理
}


def normalize_strategy_id(strategy_id: str) -> str:
    """将策略别名归一化为正式策略ID
    
    消费方(position_manager/scanner_review/strategy_config等)
    应在查找STRATEGY_CONFIGS之前调用此函数。
    
    >>> normalize_strategy_id('anomaly_surge')
    'halfway_chase'
    >>> normalize_strategy_id('halfway_chase')
    'halfway_chase'
    """
    return STRATEGY_ALIASES.get(strategy_id, strategy_id)


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
