/**
 * 策略参数单一来源（前端版本）
 * 
 * 此文件由后端 strategy_defaults.py 生成，请勿手动修改！
 * 修改策略参数请改后端 nodes/backtest_engine/strategy_defaults.py，然后重新同步。
 * 
 * 同步命令: cd AgentServer && python3 scripts/sync_strategy_defaults.py
 */

// 全局风控参数
export const GLOBAL_RISK = {
  stop_loss_pct: 0.03,
  take_profit_pct: 0.07,
  max_hold_days: 3,
  max_position_per_stock: 0.2,
  max_total_position: 0.7,
  commission_rate: 0.0003,
  stamp_duty_rate: 0.001,
  slippage_pct: 0.002,
  liquidity_threshold: 500,
  volume_threshold: 1.5,
}

// 策略配置
export const STRATEGY_CONFIGS = {
  halfway_chase: {
    name: '半路追涨',
    enabled: true,
    params: {
      min_rise_pct: 0.02,
      max_rise_pct: 0.07,
      min_volume_ratio: 2.0,
      allow_after_10am: false,
    },
    riskParams: {
      stop_loss_pct: 0.03,
      take_profit_pct: 0.07,
      max_hold_days: 2,
      slippage_pct: 0.002,
    }
  },
  first_limit_up: {
    name: '首板打板',
    enabled: true,
    params: {
      min_seal_amount: 5000,
      max_limit_up_time: '10:00',
      min_circulation_market_cap: 50,
      max_circulation_market_cap: 500,
      max_blast_count: 1,
      require_hot_sector: false,
    },
    riskParams: {
      stop_loss_pct: 0.04,
      take_profit_pct: 0.07,
      max_hold_days: 2,
      slippage_pct: 0.005,
    }
  },
  limit_up_open: {
    name: '涨停开板',
    enabled: false,
    params: {
      min_consecutive_limit: 2,
      max_open_duration: 5,
      min_seal_after_open: 3000,
      min_turnover_rate: 0.15,
      opening_pct_min: -3.0,
      opening_pct_max: 3.0,
      min_volume_ratio: 2.0,
    },
    riskParams: {
      stop_loss_pct: 0.05,
      take_profit_pct: 0.06,
      max_hold_days: 2,
      slippage_pct: 0.003,
    }
  },
  leader_buy_dip: {
    name: '龙头低吸',
    enabled: true,
    params: {
      min_consecutive_limit: 2,
      min_circulation_market_cap: 50,
      min_correction_pct: 0.08,
      max_correction_pct: 0.35,
      correction_days_min: 1,
      correction_days_max: 7,
      support_level: 'ma5',
    },
    riskParams: {
      stop_loss_pct: 0.05,
      take_profit_pct: 0.06,
      max_hold_days: 4,
      slippage_pct: 0.002,
    }
  },
  limit_down_qiao: {
    name: '跌停翘板',
    enabled: true,
    params: {
      min_consecutive_limit: 2,
      min_qiao_amount: 1000,
      min_rise_after_qiao: 0.03,
      require_high_sentiment: false,
    },
    riskParams: {
      stop_loss_pct: 0.07,
      take_profit_pct: 0.07,
      max_hold_days: 3,
      slippage_pct: 0.003,
    }
  },
}
