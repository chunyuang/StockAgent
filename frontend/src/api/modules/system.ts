/**
 * 系统配置 API 模块
 * 对接后端 /system/* 和新增的推送/日志/风控状态接口
 */
import { api } from '@/api'

// ==================== 类型定义 ====================

export interface RiskConfigData {
  market_filter: {
    enabled: boolean
    reference_index: string
    max_index_drop: number
    limit_up_count_threshold: number
    limit_down_count_threshold: number
  }
  drawdown: {
    daily_max_drawdown: number
    weekly_max_drawdown: number
    monthly_max_drawdown: number
  }
  loss_circuit: {
    consecutive_loss_limit: number
    consecutive_loss_pause_days: number
    max_daily_loss_count: number
  }
  stock_risk: {
    exclude_st_stocks: boolean
    min_market_cap: number
    max_volatility: number
    limit_board_caution: boolean
    max_limit_up_days: number
    max_limit_down_days: number
  }
}

export interface RiskCheckItem {
  name: string
  key: string
  status: 'pass' | 'warn' | 'block'
  message: string
  value?: string
}

export interface RejectionRecord {
  time: string
  ts_code: string
  stock_name: string
  reason: string
  risk_level: string
  strategy?: string
}

export interface RiskStatusData {
  risk_level: 'normal' | 'warning' | 'circuit_breaker'
  check_items: RiskCheckItem[]
  rejection_records: RejectionRecord[]
  last_check_time: string
}

export interface PushConfigData {
  notify_enabled: boolean
  wecom_webhook: string
  wecom_enabled?: boolean
  feishu_enabled: boolean
  feishu_webhook: string
  feishu_app_id: string
  feishu_app_secret: string
  feishu_bitable_app_token: string
  min_interval: number
  min_confidence: number
  push_empty_signal?: boolean
}

export interface LogLevelConfig {
  global_level: string
  modules: {
    backtest_engine: string
    trading_signal: string
    risk_check: string
    data_fetcher: string
  }
  critical_event_notify: boolean
}

export interface StrategyRiskOverride {
  enabled: boolean
  max_position_pct: number
  max_daily_trades: number
  stop_loss_pct: number
  take_profit_pct: number
  min_confidence: number
  max_slippage_pct: number
  time_restrict_enabled: boolean
  earliest_entry: string
  latest_entry: string
  no_entry_before_close: number
}

// UserPreferences 从 types.ts 统一导入，避免重复导出冲突
import type { UserPreferences } from '../types'

// ==================== API 函数 ====================

/** 获取风控配置 */
export async function getRiskConfig(): Promise<{ success: boolean; data: any }> {
  return api.get('/system/risk-config')
}

/** 保存风控配置 */
export async function saveRiskConfig(config: RiskConfigData): Promise<{ success: boolean; message: string }> {
  return api.post('/system/save-risk-config', { config })
}

/** 获取实时风控状态 */
export async function getRiskStatus(): Promise<{ success: boolean; data: RiskStatusData }> {
  return api.get('/system/risk-status')
}

/** 获取推送配置 */
export async function getPushConfig(): Promise<{ success: boolean; config: PushConfigData }> {
  return api.get('/system/push-config')
}

/** 保存推送配置 */
export async function savePushConfig(config: PushConfigData): Promise<{ success: boolean; message: string }> {
  return api.post('/system/save-push-config', { config })
}

/** 发送测试推送消息 */
export async function sendTestPush(type: 'wecom' | 'feishu'): Promise<{ success: boolean; message: string }> {
  return api.post('/system/test-push', { type })
}

/** 获取日志级别配置 */
export async function getLogLevelConfig(): Promise<{ success: boolean; data: LogLevelConfig }> {
  return api.get('/system/log-config')
}

/** 保存日志级别配置 */
export async function saveLogLevelConfig(config: LogLevelConfig): Promise<{ success: boolean; message: string }> {
  return api.post('/system/save-log-config', config)
}

/** 保存策略风控覆盖 */
export async function saveStrategyRiskConfig(config: Record<string, StrategyRiskOverride & { name: string }>): Promise<{ success: boolean; message: string }> {
  return api.post('/system/save-strategy-risk-config', { config })
}

/** 更新用户偏好设置 */
export async function updateUserPreferences(prefs: UserPreferences): Promise<{ message: string }> {
  return api.put('/user/me/preferences', prefs)
}

/** 获取净值历史（业绩曲线用） */
export async function getNetValueHistory(accountId: string, days: number = 90): Promise<{ success: boolean; data: any }> {
  return api.get(`/trading/performance/net-value`, { params: { account_id: accountId, days } })
}
export default {
  getRiskConfig,
  saveRiskConfig,
  getRiskStatus,
  getPushConfig,
  savePushConfig,
  sendTestPush,
  getLogLevelConfig,
  saveLogLevelConfig,
  saveStrategyRiskConfig,
  updateUserPreferences,
  getNetValueHistory,
}
