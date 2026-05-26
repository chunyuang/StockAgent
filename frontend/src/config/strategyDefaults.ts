/**
 * 策略参数单一来源（前端版本）
 * 
 * ⚠️ 此文件由 scripts/sync_strategy_defaults.py 自动生成！
 * 请勿手动修改！修改策略参数请改后端 strategy_defaults.py，然后重新运行同步脚本。
 * 
 * 同步命令: cd AgentServer && python3 scripts/sync_strategy_defaults.py
 */

// 全局风控参数 — 与后端 strategy_defaults.py GLOBAL_RISK 完全一致
export const GLOBAL_RISK = {
  stop_loss_pct: 0.03,
  take_profit_pct: 0.07,
  max_hold_days: 3,
  slippage_pct: 0.002,
  commission_rate: 0.0003,
  stamp_duty_rate: 0.001,
  max_position_per_stock: 0.35,
  max_total_position: 0.7,
  liquidity_threshold: 500,
  volume_threshold: 1.5,
  force_empty_limit_down: 80,
  force_empty_limit_up: 10,
  force_empty_index_drop_pct: 0.03,
  intraday_lock_min_high_rise: 0.05,
  intraday_lock_pullback_pct: 0.02,
  intraday_lock_min_profit: 0.02,
  hold_protection_threshold: 0.05,
  live_trading_mode: false,
}

// 策略配置 — 与后端 strategy_defaults.py STRATEGY_CONFIGS 完全对齐
export const STRATEGY_CONFIGS = {
  halfway_chase: {
    id: 'halfway_chase',
    name: '半路追涨',
    enabled: true,
    params: {
      min_rise_pct: 0.03,
      max_rise_pct: 0.07,
      min_volume_ratio: 2.0,
      max_volume_ratio: 3.0,
      min_close_rise_pct: 0.05,
      max_open_rise_pct: 0.03,
      allow_after_10am: false,
      next_day_open_sell_pct: 0.02,
    },
    riskParams: {
      stop_loss_pct: 0.04,
      take_profit_pct: 0.12,
      max_hold_days: 3,
      slippage_pct: 0.002,
    },
  },
  first_limit_up: {
    id: 'first_limit_up',
    name: '首板打板',
    enabled: true,
    params: {
      opening_pct_min: -1.0,
      opening_pct_max: 5.0,
      min_volume_ratio: 1.5,
      min_turnover_rate: 8,
      max_turnover_rate: 15,
      min_circulation_market_cap: 50,
      max_circulation_market_cap: 500,
      hit_probability_yizi: 0.0,
      hit_probability_fast: 0.2,
      hit_probability_normal: 0.45,
      hit_probability_slow: 0.6,
      next_day_open_sell_pct: 0.02,
    },
    riskParams: {
      stop_loss_pct: 0.03,
      take_profit_pct: 0.08,
      max_hold_days: 2,
      slippage_pct: 0.005,
    },
  },
  limit_up_open: {
    id: 'limit_up_open',
    name: '涨停开板',
    enabled: false,
    params: {
      min_consecutive_limit: 2,
      max_consecutive_limit: 4,
      max_open_duration: 5,
      min_seal_after_open: 3000,
      min_turnover_rate: 15.0,
      opening_pct_min: -3.0,
      opening_pct_max: 3.0,
      min_volume_ratio: 2.0,
    },
    riskParams: {
      stop_loss_pct: 0.05,
      take_profit_pct: 0.06,
      max_hold_days: 2,
      slippage_pct: 0.003,
    },
  },
  dragon_head: {
    id: 'dragon_head',
    name: '龙头低吸',
    enabled: true,
    params: {
      min_consecutive_limit: 1,
      min_circulation_market_cap: 30,
      min_correction_pct: 0.05,
      max_correction_pct: 0.22,
      correction_days_min: 1,
      correction_days_max: 7,
      support_level: 'ma5',
      min_volume_ratio: 0.5,
      max_volume_ratio: 2.0,
      next_day_open_sell_pct: 0.02,
    },
    riskParams: {
      stop_loss_pct: 0.03,
      take_profit_pct: 0.3,
      max_hold_days: 7,
      slippage_pct: 0.002,
    },
  },
  limit_down_qiao: {
    id: 'limit_down_qiao',
    name: '跌停翘板',
    enabled: true,
    params: {
      min_consecutive_limit: 2,
      min_turnover_rate: 10,
      min_qiao_amount: 1000,
      min_rise_after_qiao: 0.03,
      min_circulation_market_cap: 20,
      require_high_sentiment: false,
      next_day_open_sell_pct: 0.02,
      pullback_mid_fallback_pct: 0.015,
    },
    riskParams: {
      stop_loss_pct: 0.05,
      take_profit_pct: 0.2,
      max_hold_days: 3,
      slippage_pct: 0.003,
    },
  },
}
