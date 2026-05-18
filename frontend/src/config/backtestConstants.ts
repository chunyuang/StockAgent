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
}

/** 参数扫描参数配置 */
export const SWEEP_PARAMS = [
  { value: 'stop_loss_pct', label: '止损比例', unit: '%', factor: 100, min: 1, max: 20, step: 1 },
  { value: 'take_profit_pct', label: '止盈比例', unit: '%', factor: 100, min: 1, max: 50, step: 1 },
  { value: 'max_hold_days', label: '最大持仓天数', unit: '天', factor: 1, min: 1, max: 10, step: 1 },
  { value: 'max_position_per_stock', label: '单票最大仓位', unit: '%', factor: 100, min: 5, max: 50, step: 5 },
  { value: 'max_position', label: '总仓位上限', unit: '%', factor: 100, min: 10, max: 100, step: 10 },
  { value: 'min_rise_pct', label: '半路追涨最小涨幅', unit: '%', factor: 100, min: 1, max: 10, step: 1 },
  { value: 'min_volume_ratio', label: '最小量比', unit: '倍', factor: 1, min: 0.5, max: 5, step: 0.5 },
]
