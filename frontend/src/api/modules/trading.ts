/**
 * 实盘交易 API
 */

import { api } from '../client'

// ==================== 类型定义 ====================

/** 模拟账户信息 */
export interface SimAccount {
  account_id: string
  name: string
  initial_cash: number
  available_cash: number
  total_assets: number
  total_profit_pct: number
  total_profit: number
  position_value: number
  position_ratio: number
  created_at: string
  updated_at: string
}

/** 持仓信息 */
export interface Position {
  position_id: string
  account_id: string
  ts_code: string
  stock_name: string
  quantity: number
  available_quantity: number
  avg_cost: number
  current_price: number
  profit_pct: number
  profit: number
  first_buy_date: string
  hold_days: number
  strategy: string
}

/** 交易记录 */
export interface TradeRecord {
  trade_id: string
  account_id: string
  ts_code: string
  stock_name: string
  direction: 'buy' | 'sell'
  quantity: number
  price: number
  amount: number
  commission: number
  stamp_duty: number
  trade_time: string
  strategy: string
  reason: string
}

/** 交易信号 */
export interface TradingSignal {
  signal_id: string
  ts_code: string
  stock_name: string
  strategy: string
  signal_type: 'buy' | 'sell' | 'hold'
  price: number
  suggest_quantity: number
  confidence: number
  reason: string
  generated_at: string
  expired_at: string
  executed: boolean
  executed_time?: string
}

/** 绩效报告 */
export interface PerformanceReport {
  report_id: string
  account_id: string
  period: string
  start_date: string
  end_date: string
  total_return_pct: number
  annual_return_pct: number
  max_drawdown_pct: number
  sharpe_ratio: number
  sortino_ratio: number
  win_rate_pct: number
  profit_factor: number
  total_trades: number
  created_at: string
}

// ==================== API 方法 ====================

/**
 * 获取模拟账户列表
 */
export async function getSimAccounts(): Promise<SimAccount[]> {
  return api.get<SimAccount[]>('/trading/accounts')
}

/**
 * 获取指定账户的持仓
 */
export async function getPositions(account_id: string): Promise<Position[]> {
  return api.get<Position[]>(`/trading/accounts/${account_id}/positions`)
}

/**
 * 获取指定账户的交易记录
 */
export async function getTradeRecords(
  account_id: string,
  limit: number = 20,
  offset: number = 0
): Promise<{ total: number; items: TradeRecord[] }> {
  return api.get<{ total: number; items: TradeRecord[] }>(
    `/trading/accounts/${account_id}/trades`,
    { params: { limit, offset } }
  )
}

/**
 * 获取交易信号列表
 */
export async function getTradingSignals(
  limit: number = 20,
  offset: number = 0,
  only_unexecuted: boolean = false
): Promise<{ total: number; items: TradingSignal[] }> {
  return api.get<{ total: number; items: TradingSignal[] }>(
    '/trading/signals',
    { params: { limit, offset, only_unexecuted } }
  )
}

/**
 * 执行交易信号
 */
export async function executeSignal(signal_id: string, account_id: string, quantity?: number): Promise<{ success: boolean; trade_id: string }> {
  return api.post<{ success: boolean; trade_id: string }>(`/trading/signals/${signal_id}/execute`, {
    account_id,
    quantity
  })
}

/**
 * 获取绩效报告列表
 */
export async function getPerformanceReports(
  account_id?: string,
  limit: number = 20,
  offset: number = 0
): Promise<{ total: number; items: PerformanceReport[] }> {
  const params: Record<string, unknown> = { limit, offset }
  if (account_id) params.account_id = account_id
  return api.get<{ total: number; items: PerformanceReport[] }>(
    '/trading/performance/reports',
    { params }
  )
}

/**
 * 手动触发信号生成
 */
export async function triggerSignalGeneration(): Promise<{ success: boolean; message: string; signal_count: number }> {
  return api.post<{ success: boolean; message: string; signal_count: number }>('/trading/signals/generate')
}

/** 今日预选池 - 按策略分组的信号统计 */
export interface PoolStrategyGroup {
  strategy_id: string
  strategy_name: string
  count: number
  avg_confidence: number
  signals: TradingSignal[]
}

/** 今日预选池概览 */
export interface TodayPoolOverview {
  trade_date: string
  total_count: number
  buy_count: number
  sell_count: number
  pending_count: number
  executed_count: number
  strategy_groups: PoolStrategyGroup[]
}

/**
 * 获取今日预选池数据
 */
export async function getTodayPool(limit: number = 200): Promise<{ total: number; items: TradingSignal[] }> {
  return api.get<{ total: number; items: TradingSignal[] }>('/trading/signals', {
    params: { limit, offset: 0, only_unexecuted: false }
  })
}

export default {
  getSimAccounts,
  getPositions,
  getTradeRecords,
  getTradingSignals,
  executeSignal,
  getPerformanceReports,
  triggerSignalGeneration,
}
