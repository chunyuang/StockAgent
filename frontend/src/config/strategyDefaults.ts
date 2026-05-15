/**
 * 策略参数单一来源（前端版本）
 * 
 * ⚠️ 此文件必须与后端 strategy_defaults.py 保持同步！
 * 修改策略参数请改后端 nodes/backtest_engine/strategy_defaults.py，然后重新同步。
 * 
 * 同步命令: cd AgentServer && python3 scripts/sync_strategy_defaults.py
 */

// 全局风控参数
export const GLOBAL_RISK = {
  stop_loss_pct: 0.05,
  take_profit_pct: 0.10,
  max_hold_days: 3,
  max_position_per_stock: 0.2,
  max_total_position: 0.7,
  commission_rate: 0.0003,
  stamp_duty_rate: 0.001,
  slippage_pct: 0.002,
  liquidity_threshold: 500,
  volume_threshold: 1.5,
}

// 策略配置 — 与后端 strategy_defaults.py 完全对齐
export const STRATEGY_CONFIGS = {
  halfway_chase: {
    name: '半路追涨',
    enabled: true,
    params: {
      min_rise_pct: 0.03,           // 最小涨幅3%
      max_rise_pct: 0.07,           // 最大涨幅7%
      min_volume_ratio: 2.0,        // 量比≥2
      max_volume_ratio: 3.0,        // 量比≤3
      min_close_rise_pct: 0.03,     // 收盘确认≥3%(盘中冲高但收盘不站=次日差)
      max_open_rise_pct: 0.03,      // 开盘涨幅上限3%(排除高开低走)
      allow_after_10am: false,      // 10点后是否允许买入
    },
    riskParams: {
      stop_loss_pct: 0.05,
      take_profit_pct: 0.10,
      max_hold_days: 3,
      slippage_pct: 0.002,
    }
  },
  first_limit_up: {
    name: '首板打板',
    enabled: true,
    params: {
      opening_pct_min: -1.0,        // 竞价涨幅下限-1%
      opening_pct_max: 7.0,         // 竞价涨幅上限7%
      min_volume_ratio: 1.5,        // 量比≥1.5
      min_turnover_rate: 3,         // 换手率≥3%
      max_turnover_rate: 15,        // 换手率≤15%
      min_circulation_market_cap: 50,  // 流通市值≥50亿
      max_circulation_market_cap: 500, // 流通市值≤500亿
      hit_probability_yizi: 0.0,    // 一字板成交概率0%
      hit_probability_fast: 0.3,    // 秒板成交概率30%
      hit_probability_normal: 0.5,  // 快板成交概率50%
      hit_probability_slow: 0.7,    // 慢板成交概率70%
      next_day_open_sell_pct: 0.03, // 次日高开≥3%即卖
    },
    riskParams: {
      stop_loss_pct: 0.04,
      take_profit_pct: 0.12,
      max_hold_days: 3,
      slippage_pct: 0.005,
    }
  },
  limit_up_open: {
    name: '涨停开板',
    enabled: false,  // 负期望，默认关闭
    params: {
      min_consecutive_limit: 2,     // 最小连板数
      max_open_duration: 5,         // 开板最长时间(分钟)
      min_seal_after_open: 3000,    // 开板后封单额(万元)
      min_turnover_rate: 0.15,      // 换手率≥15%
      opening_pct_min: -3.0,        // 开盘涨幅下限
      opening_pct_max: 3.0,         // 开盘涨幅上限
      min_volume_ratio: 2.0,        // 量比≥2
    },
    riskParams: {
      stop_loss_pct: 0.05,
      take_profit_pct: 0.06,
      max_hold_days: 2,
      slippage_pct: 0.003,
    }
  },
  dragon_head: {
    name: '龙头低吸',
    enabled: true,
    params: {
      min_consecutive_limit: 1,     // 最小连板数(1板即可:50.5%wr>2板42.2%)
      min_circulation_market_cap: 30, // 流通市值≥30亿
      min_correction_pct: 0.05,     // 最小回调5%
      max_correction_pct: 0.35,     // 最大回调35%
      correction_days_min: 1,       // 回调天数下限
      correction_days_max: 7,       // 回调天数上限
      support_level: 'ma5',         // 支撑位参考
      min_volume_ratio: 0.5,        // 量比≥0.5(排除极度冷门)
      max_volume_ratio: 2.0,        // 量比≤2.0(缩量回调更安全)
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
      min_consecutive_limit: 2,     // 最小连跌数
      min_qiao_amount: 1000,        // 翘板金额(万元)
      min_rise_after_qiao: 0.03,    // 翘板后最小涨幅3%
      min_circulation_market_cap: 20, // 流通市值≥20亿(排除小盘操纵)
      require_high_sentiment: false, // 是否要求高情绪(默认不要求)
    },
    riskParams: {
      stop_loss_pct: 0.07,
      take_profit_pct: 0.07,
      max_hold_days: 3,
      slippage_pct: 0.003,
    }
  },
}
