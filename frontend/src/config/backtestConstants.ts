/**
 * 回测模块共享常量
 * 避免在多个组件中重复定义
 */

/** 策略中文名映射 */
export const STRATEGY_NAMES: Record<string, string> = {
  halfway_chase: '🏃‍♂️ 半路追涨',
  first_limit_up: '🥇 首板打板',
  limit_up_open: '📈 涨停开板',
  dragon_head: '🐲 龙头低吸',
  limit_down_qiao: '💥 跌停翘板',
  leader_buy_dip: '🐲 龙头低吸',
}

/** 参数扫描参数配置 */
export const SWEEP_PARAMS = [
  // 全局风控参数
  { value: 'stop_loss_pct', label: '止损比例', unit: '%', factor: 100, min: 1, max: 20, step: 1 },
  { value: 'take_profit_pct', label: '止盈比例', unit: '%', factor: 100, min: 1, max: 50, step: 1 },
  { value: 'max_hold_days', label: '最大持仓天数', unit: '天', factor: 1, min: 1, max: 10, step: 1 },
  { value: 'max_position_per_stock', label: '单票最大仓位', unit: '%', factor: 100, min: 5, max: 50, step: 5 },
  { value: 'max_position', label: '总仓位上限', unit: '%', factor: 100, min: 10, max: 100, step: 10 },
  // 半路追涨策略参数
  { value: 'min_rise_pct', label: '半路追涨·最小涨幅', unit: '%', factor: 100, min: 1, max: 10, step: 1 },
  { value: 'min_volume_ratio', label: '最小量比', unit: '倍', factor: 1, min: 0.5, max: 5, step: 0.5 },
  // 次日高开即卖(所有策略共享)
  { value: 'next_day_open_sell_pct', label: '次日高开即卖', unit: '%', factor: 100, min: 1, max: 10, step: 1 },
  // 首板打板策略参数
  { value: 'hit_probability_normal', label: '首板打板·快板成交率', unit: '%', factor: 100, min: 10, max: 90, step: 10 },
  // 跌停翘板策略参数
  { value: 'pullback_mid_fallback_pct', label: '跌停翘板·冲高回落阈值', unit: '%', factor: 100, min: 0.5, max: 5, step: 0.5 },
  // V48: 利润锁定参数
  { value: 'intraday_lock_min_high_rise', label: '利润锁定·盘中冲高', unit: '%', factor: 100, min: 3, max: 10, step: 1 },
  { value: 'intraday_lock_pullback_pct', label: '利润锁定·回撤阈值', unit: '%', factor: 100, min: 1, max: 5, step: 0.5 },
  { value: 'intraday_lock_min_profit', label: '利润锁定·最小利润', unit: '%', factor: 100, min: 1, max: 5, step: 0.5 },
  { value: 'hold_protection_threshold', label: '持仓保护阈值', unit: '%', factor: 100, min: 3, max: 10, step: 1 },
]
