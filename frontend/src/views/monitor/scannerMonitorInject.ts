/**
 * ScannerMonitor provide/inject key
 * 用于MarketMonitorView子组件间共享composable数据
 * 【v2.9.74: 新增provide/inject模式, 替代大量props传递】
 * 【v2.9.75: 完整类型接口, 消除子组件as any类型断言】
 */
import { inject, type InjectionKey, type Ref, type ComputedRef } from 'vue'

// ==================== 子组件类型 ====================

/** 信号数据 */
export interface ScanSignal {
  ts_code: string
  stock_name: string
  strategy: string
  strategy_name: string
  signal_type: string
  price: number
  pct_chg: number
  volume_ratio: number
  turnover_rate: number
  is_limit_up: boolean
  limit_up_count: number
  confidence: number
  reason: string
  scan_time: string
  factors: Record<string, number>
  key_factors?: Record<string, string>
  decision_detail?: Record<string, any>
  signal_status?: string
  layer_trace?: Record<string, any>
  created_at?: number
}

/** 持仓数据 */
export interface PositionInfo {
  ts_code: string
  stock_name: string
  strategy: string
  strategy_name?: string
  shares: number
  available_qty: number
  cost_price: number
  current_price: number
  profit_pct: number
  profit_amount?: number
  market_value?: number
  today_buy: number
  stop_loss_pct?: number
  take_profit_pct?: number
  stop_loss_price?: number
  take_profit_price?: number
  distance_to_stop?: number
  risk_level?: string
  trailing_stop?: {
    high_price: number
    trailing_stop_pct: number
    activated: boolean
    stop_price: number
    activated_at?: string
  }
  effective_stop_price?: number
  buy_price?: number
  sell_price?: number
}

/** 时间线条目 */
export interface TimelineItem {
  time: string
  action: string
  ts_code: string
  stock_name: string
  strategy: string
  shares: number
  price: number
  reason: string
  profit_pct?: number
  profit_amount?: number
  decision_detail?: Record<string, any>
}

/** 健康状态 */
export type HealthStatus = 'healthy' | 'warning' | 'critical'

/** 策略元数据 */
export interface StrategyMetaEntry {
  color?: string
  label?: string
  [key: string]: any
}

// ==================== 完整provide/inject接口 ====================
// 注: 使用工具类型保持类型安全的同时兼容composable动态返回值
// 关键属性显式类型化, 其余通过索引签名兼容

export interface ScannerMonitorData {
  // --- 核心状态 (显式类型) ---
  loading: Ref<boolean>
  autoRefresh: Ref<boolean>
  soundEnabled: Ref<boolean>
  status: Ref<any>
  signals: Ref<ScanSignal[]>
  positions: Ref<PositionInfo[]>
  timeline: Ref<TimelineItem[]>
  orders: Ref<any[]>
  signalFilter: Ref<string>
  filteredSignals: ComputedRef<ScanSignal[]>
  closedPositions: ComputedRef<PositionInfo[]>
  isRunning: ComputedRef<boolean>
  accountInfo: ComputedRef<any>
  totalPnl: ComputedRef<number>
  positionRatio: ComputedRef<number>
  circuitBreakerPaused: ComputedRef<boolean>
  focusIndex: Ref<number>
  nowMs: Ref<number>
  tradeMode: Ref<string>
  replayDate: Ref<string>
  activeTab: Ref<string>
  tradeDetailVisible: Ref<boolean>
  tradeDetailData: Ref<any>
  scanTraceVisible: Ref<boolean>
  scanTraceData: Ref<any>
  scanTraceCode: Ref<string>
  layerDebugVisible: Ref<boolean>
  layerDebugData: Ref<any>
  signalTraceVisible: Ref<boolean>
  compareVisible: Ref<boolean>
  compareData: Ref<any[]>
  dailyReportVisible: Ref<boolean>
  weeklyReportVisible: Ref<boolean>
  dailyReport: Ref<any>
  dryRun: Ref<boolean>

  // --- 核心方法 (显式类型) ---
  fetchScanner: () => void
  startScanner: () => void
  stopScanner: () => void
  quickBuy: (signal: ScanSignal) => void
  quickSell: (position: PositionInfo) => void
  manualScan: () => void
  forceScan: () => void
  dailySettlement: () => void
  resetCircuitBreaker: () => void
  resetAccount: () => void
  sellAllPositions: () => void

  // --- 工具方法 (显式类型) ---
  strategyCN: (s: string | number) => string | number
  strategyMeta: Record<string, StrategyMetaEntry>
  factorLabel: (k: string) => string
  layerLabel: (k: any) => string
  layerDesc: (k: any, v?: any) => string
  rejectionLayerCN: (k: string) => string
  signalStatusTag: (status: string) => { type: 'success' | 'warning' | 'info' | 'primary' | 'danger'; text: string }
  formatLayerTrace: (trace: any) => string[]
  formatDecisionDetail: (detail: any) => string[]

  // --- WS状态 ---
  wsStatus: ComputedRef<string>
  wsIsConnected: ComputedRef<boolean>
  wsRetryCount: ComputedRef<number>

  // --- 兼容索引签名 (其余composable属性) ---
  [key: string]: any
}

export const SCANNER_MONITOR_KEY: InjectionKey<ScannerMonitorData> = Symbol('scannerMonitor')

/** 子组件中使用: const m = useScannerMonitorInject() */
export function useScannerMonitorInject(): ScannerMonitorData {
  const data = inject(SCANNER_MONITOR_KEY)
  if (!data) throw new Error('useScannerMonitorInject must be used inside MarketMonitorView')
  return data
}
