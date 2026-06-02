/**
 * Scanner 共享常量与工具函数
 * 驾驶舱 & 市场监听共用，避免重复定义
 */

// ============ 策略元数据 ============
export const strategyMeta: Record<string, { color: string; icon: string; cn: string; desc?: string }> = {
  halfway_chase: { color: '#e6a23c', icon: '🚀', cn: '半路追涨', desc: '盘中冲高2-7%+量能放大' },
  first_limit_up: { color: '#f56c6c', icon: '🔥', cn: '首板打板', desc: '首板涨停封板强' },
  dragon_head: { color: '#409eff', icon: '🐉', cn: '龙头低吸', desc: '连板龙头回调低吸' },
  limit_down_qiao: { color: '#67c23a', icon: '💪', cn: '跌停翘板', desc: '跌停撬板反弹' },
  limit_up_open: { color: '#909399', icon: '🔓', cn: '涨停开板', desc: '涨停炸板回封' },
  anomaly_surge: { color: '#e6a23c', icon: '⚡', cn: '急速拉升', desc: '5分钟急速拉升' },
  anomaly_broken: { color: '#f56c6c', icon: '💔', cn: '涨停炸板', desc: '涨停炸板' },
  anomaly_strong: { color: '#409eff', icon: '💪', cn: '强势涨停', desc: '强势涨停确认' },
}

export const strategyCN = (s: string | number) => strategyMeta[String(s)]?.cn || s
export const strategyColor = (s: string) => strategyMeta[s]?.color || '#909399'
export const strategyIcon = (s: string) => strategyMeta[s]?.icon || '📊'

// ============ 9层管道 ============
export const pipelineLayers = [
  'L1_force_empty', 'L2_special_period', 'L3_sentiment', 'L4_premarket',
  'L5_auction', 'L6_strategy', 'L7_ranking', 'L8_position', 'L9_execute',
]

export const pipelineLabels: Record<string, string> = {
  L1_force_empty: '强制空仓', L2_special_period: '特殊时期', L3_sentiment: '情绪周期',
  L4_premarket: '盘前预选', L5_auction: '竞价过滤', L6_strategy: '策略量能',
  L7_ranking: '综合排序', L8_position: '仓位控制', L9_execute: '执行确认',
}

// ============ 交易模式 ============
export const modeMeta: Record<string, { text: string; color: string; emoji: string }> = {
  simulated: { text: '模拟', color: '#67c23a', emoji: '🟢' },
  gm: { text: '掘金', color: '#409eff', emoji: '🔵' },
  dry_run: { text: '调试', color: '#e6a23c', emoji: '🟡' },
  replay: { text: '回放', color: '#9b59b6', emoji: '🔄' },
}

export const modeLabel = (mode: string) => modeMeta[mode]?.text || mode
export const modeEmoji = (mode: string) => modeMeta[mode]?.emoji || '⚪'

// ============ 因子中文名 ============
export const factorCN: Record<string, string> = {
  pct_chg: '涨跌幅', volume_ratio: '量比', turnover_rate: '换手率',
  circ_mv: '流通市值', total_mv: '总市值', float_mv: '流通市值',
  ma5: 'MA5', ma10: 'MA10', ma20: 'MA20', ma60: 'MA60',
  rsi_6: 'RSI6', rsi_12: 'RSI12', rsi_24: 'RSI24',
  macd: 'MACD', macd_signal: 'MACD信号', macd_hist: 'MACD柱',
  boll_upper: '布林上轨', boll_lower: '布林下轨', boll_mid: '布林中轨',
  atr: 'ATR', momentum_1d: '1日动量',
  is_limit_up: '涨停', is_limit_down: '跌停',
  limit_up_count: '涨停次数', limit_up_yesterday: '昨日涨停',
  limit_down_yesterday: '昨日跌停', first_limit_up: '首板',
  opening_pct_chg: '竞价涨跌幅', open: '开盘价', high: '最高价',
  low: '最低价', close: '收盘价', pre_close: '前收盘',
  pe: 'PE', pb: 'PB', amplitude: '振幅',
  fear_greed_index: '恐慌贪婪指数',
  limit_up_open_amount: '涨停开板金额', limit_down_open_amount: '跌停开板金额',
  pullback_pct: '回调幅度', pullback_days: '回调天数',
  rise_after_limit_down: '跌停后涨幅',
  open_times: '开板次数', fd_amount: '封板资金', limit_times: '连板数',
}

export const factorLabel = (k: string | number) => factorCN[String(k)] || k

// ============ Scanner API 封装 ============
const scannerApi = '/scanner'

/** 统一解析scanner API响应 — axios拦截器已剥response.data */
export function parseResponse(r: any): { success: boolean; data: any } {
  if (!r) return { success: false, data: null }
  if (r.success) {
    // /scanner/all 返回 {success, data:{status, signals, ...}}
    // /scanner/health 返回 {success, health:{...}}
    // /scanner/limit-pools 返回 {success, data:{limit_up,...}}
    if (r.data !== undefined) return { success: true, data: r.data }
    // health等直接在顶层
    const filtered: Record<string, any> = {}
    for (const [k, v] of Object.entries(r)) {
      if (k !== 'success') filtered[k] = v
    }
    return { success: true, data: Object.keys(filtered).length === 1 ? filtered[Object.keys(filtered)[0]] : filtered }
  }
  return { success: false, data: null }
}

// ============ 信号过期 ============
export const SIGNAL_EXPIRE_MS = 300000 // 5分钟

export function signalRemaining(created_at: number, nowMs: number): number {
  if (!created_at || created_at <= 0) return -1
  return Math.max(0, SIGNAL_EXPIRE_MS - (nowMs / 1000 - created_at) * 1000)
}

export function formatRemaining(ms: number): string {
  if (ms < 0) return ''
  const s = Math.floor(ms / 1000)
  if (s < 60) return `${s}s`
  return `${Math.floor(s / 60)}m${s % 60}s`
}

// ============ 金额格式化 ============
export function formatMoney(v: number): string {
  if (Math.abs(v) >= 10000) return `¥${(v / 10000).toFixed(1)}万`
  return `¥${v.toFixed(0)}`
}

export function formatPct(v: number): string {
  if (v == null || isNaN(v)) return '--'
  return `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`
}

// ============ 止损止盈格式化 ============
// 后端 /scanner/positions 返回百分比格式 (3.0 = 3%)
// 后端 /strategy-config 和 /scanner/params 内部存储小数 (0.03 = 3%)
// 此函数统一将任意格式转为百分比数值
export function normalizePct(v: number | undefined, fallback: number = 3): number {
  if (v == null || isNaN(v)) return fallback
  // 小于1认为是小数格式(0.03)，大于1认为是百分比格式(3.0)
  return v < 1 ? v * 100 : v
}

// 格式化止损止盈百分比显示 (始终输出如 "3.0%")
export function formatSlTp(v: number | undefined, fallback: number = 3): string {
  return normalizePct(v, fallback).toFixed(1) + '%'
}
