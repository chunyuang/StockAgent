/**
 * Scanner Store - 实盘扫描器状态管理
 * 
 * Phase 4.1: WS主通道 + REST fallback + 数据新鲜度(3s绿/5s黄/>5s红)
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/api/client'

export type DataFreshness = 'green' | 'yellow' | 'red'

export interface ScannerPosition {
  ts_code: string
  stock_name: string
  strategy: string
  strategy_name: string
  avg_cost: number
  current_price: number
  profit_pct: number
  available_qty: number
  total_qty: number
  stop_loss_price?: number
  take_profit_price?: number
}

export interface ScannerSignal {
  ts_code: string
  stock_name: string
  strategy: string
  strategy_name: string
  price: number
  pct_chg: number
  reason: string
  created_at: number
  signal_status: string
}

export interface ScannerTimelineItem {
  time: string
  action: string
  ts_code?: string
  stock_name?: string
  strategy?: string
  reason?: string
  shares?: number
  price?: number
  profit_pct?: number
}

export interface ScannerHealth {
  overall_status: 'healthy' | 'degraded' | 'critical' | 'dead' | 'unknown'
  health_score: number
  data_freshness: DataFreshness
  is_healthy: boolean
  warnings: string[]
  scan_lag_seconds: number
  risk_check_lag_seconds: number
  risk_metrics: {
    daily_drawdown_pct: number
    max_drawdown_pct: number
    position_ratio: number
    consecutive_losses: number
  }
  circuit_breaker: {
    trading_paused: boolean
    pause_reason: string
  }
}

export const useScannerStore = defineStore('scanner', () => {
  // ==================== 状态 ====================

  /** 是否运行中 */
  const isRunning = ref(false)

  /** 持仓列表 */
  const positions = ref<ScannerPosition[]>([])

  /** 活跃信号 */
  const signals = ref<ScannerSignal[]>([])

  /** 时间线 */
  const timeline = ref<ScannerTimelineItem[]>([])

  /** 健康状态 */
  const health = ref<ScannerHealth | null>(null)

  /** 账户信息 */
  const account = ref<{
    total_assets: number
    available_cash: number
    market_value: number
    total_profit: number
  } | null>(null)

  /** 情绪周期 */
  const sentiment = ref<{
    score: number
    period: string
  } | null>(null)

  /** 仓位系数 */
  const positionRatio = ref(1.0)

  /** 扫描统计 */
  const stats = ref({
    scans: 0,
    stop_losses: 0,
    take_profits: 0,
    stocks_scanned: 0,
  })

  /** 【P0-3】Scanner状态(WS推送) */
  const status = ref<any>(null)

  /** 【P0-3】最近错误(用于弹窗) */
  const lastError = ref<string>('')

  // ==================== 数据新鲜度 ====================

  /** 最后WS更新时间 */
  const lastWsUpdate = ref<number>(0)

  /** 最后REST更新时间 */
  const lastRestUpdate = ref<number>(0)

  /** 数据新鲜度(基于WS更新延迟) */
  const dataFreshness = computed<DataFreshness>(() => {
    const lag = (Date.now() - lastWsUpdate.value) / 1000
    if (lag < 3) return 'green'
    if (lag < 5) return 'yellow'
    return 'red'
  })

  /** 是否使用WS(主通道) */
  const isWsConnected = ref(false)

  // ==================== 计算属性 ====================

  /** 持仓数量 */
  const positionCount = computed(() => positions.value.length)

  /** 信号数量 */
  const signalCount = computed(() => signals.value.length)

  /** 总资产 */
  const totalAssets = computed(() => account.value?.total_assets || 0)

  /** 日盈亏 */
  const dailyProfit = computed(() => account.value?.total_profit || 0)

  /** 日盈亏百分比 */
  const dailyProfitPct = computed(() => {
    if (!account.value || account.value.total_assets <= 0) return 0
    const startAssets = account.value.total_assets - account.value.total_profit
    if (startAssets <= 0) return 0
    return (account.value.total_profit / startAssets) * 100
  })

  /** 是否降级模式 */
  const isDegraded = computed(() =>
    health.value?.overall_status === 'degraded' ||
    health.value?.overall_status === 'critical'
  )

  /** 告警列表 */
  const warnings = computed(() => health.value?.warnings || [])

  // ==================== Actions ====================

  /** 从WS消息更新状态(主通道) */
  function updateFromWs(eventType: string, data: any) {
    switch (eventType) {
      case 'signal':
        if (data.item) {
          // 增量更新信号
          const idx = signals.value.findIndex(
            s => s.ts_code === data.item.ts_code && s.strategy === data.item.strategy
          )
          if (idx >= 0) {
            signals.value[idx] = data.item
          } else {
            signals.value.push(data.item)
          }
        }
        break

      case 'position':
        if (data.positions) {
          positions.value = data.positions
        }
        if (data.account) {
          account.value = data.account
        }
        break

      case 'timeline':
        if (data.item) {
          // 增量添加时间线
          const exists = timeline.value.some(
            t => t.time === data.item.time && t.ts_code === data.item.ts_code && t.action === data.item.action
          )
          if (!exists) {
            timeline.value.unshift(data.item) // 最新在前
            if (timeline.value.length > 100) {
              timeline.value = timeline.value.slice(0, 100)
            }
          }
        }
        break

      case 'status':
        if (data.is_running !== undefined) isRunning.value = data.is_running
        if (data.stats) stats.value = data.stats
        if (data.sentiment) sentiment.value = data.sentiment
        if (data.position_ratio) positionRatio.value = data.position_ratio
        // 【P0-3】记录状态和错误
        status.value = data
        if (data.event === 'scanner_error') lastError.value = data.error || '未知错误'
        break
    }

    lastWsUpdate.value = Date.now()
  }

  /** 从REST API全量刷新(fallback) */
  async function refreshFromApi() {
    try {
      const [statusRes, healthRes] = await Promise.allSettled([
        api.get<Record<string, any>>('/scanner/status'),
        api.get<Record<string, any>>('/scanner/health'),
      ])

      if (statusRes.status === 'fulfilled' && statusRes.value?.success) {
        const s = statusRes.value.data || statusRes.value
        isRunning.value = s.is_running ?? s.isRunning ?? false
        stats.value = s.stats || stats.value
        account.value = s.account || account.value
        sentiment.value = s.sentiment || sentiment.value
        positionRatio.value = s.position_ratio ?? s.positionRatio ?? positionRatio.value
        positions.value = s.positions || positions.value
        signals.value = s.signals || signals.value
      }

      if (healthRes.status === 'fulfilled' && healthRes.value?.success) {
        const h = healthRes.value.data || healthRes.value
        health.value = h.health || h
      }

      lastRestUpdate.value = Date.now()
    } catch (e) {
      console.warn('[ScannerStore] REST refresh failed:', e)
    }
  }

  /** 启动Scanner */
  async function start() {
    try {
      await api.post('/scanner/start')
      isRunning.value = true
      await refreshFromApi()
    } catch (e) {
      console.error('[ScannerStore] Start failed:', e)
    }
  }

  /** 停止Scanner */
  async function stop(sellAll = false) {
    try {
      await api.post(`/scanner/stop?sell_all=${sellAll}`)
      isRunning.value = false
      await refreshFromApi()
    } catch (e) {
      console.error('[ScannerStore] Stop failed:', e)
    }
  }

  /** 清空状态 */
  function $reset() {
    isRunning.value = false
    positions.value = []
    signals.value = []
    timeline.value = []
    health.value = null
    account.value = null
    sentiment.value = null
    positionRatio.value = 1.0
    stats.value = { scans: 0, stop_losses: 0, take_profits: 0, stocks_scanned: 0 }
    lastWsUpdate.value = 0
    lastRestUpdate.value = 0
  }

  // ==================== v2.9.14/15: Stream + 参数预检 ====================

  /** 【v2.9.14】从Redis Stream读取最近信号 */
  async function fetchStreamSignals(count = 20) {
    try {
      const res = await api.get<Record<string, any>>(`/scanner/stream/signals?count=${count}`)
      return res?.data || []
    } catch { return [] }
  }

  /** 【v2.9.14】从Redis Stream读取最近持仓变更 */
  async function fetchStreamPositions(count = 20) {
    try {
      const res = await api.get<Record<string, any>>(`/scanner/stream/positions?count=${count}`)
      return res?.data || []
    } catch { return [] }
  }

  /** 【v2.9.15】参数预检验证(不实际更新) */
  async function validateParams(strategyId: string, params: Record<string, number>) {
    try {
      const res = await api.post<Record<string, any>>('/scanner/params/validate', { strategy_id: strategyId, params })
      return { warnings: res?.warnings || [], isSafe: res?.is_safe ?? true }
    } catch { return { warnings: [], isSafe: true } }
  }

  return {
    // 状态
    isRunning,
    positions,
    signals,
    timeline,
    health,
    account,
    sentiment,
    positionRatio,
    stats,
    isWsConnected,
    status,
    lastError,

    // 数据新鲜度
    dataFreshness,
    lastWsUpdate,
    lastRestUpdate,

    // 计算属性
    positionCount,
    signalCount,
    totalAssets,
    dailyProfit,
    dailyProfitPct,
    isDegraded,
    warnings,

    // Actions
    updateFromWs,
    refreshFromApi,
    start,
    stop,
    $reset,

    // v2.9.14/15: Stream + 参数预检
    fetchStreamSignals,
    fetchStreamPositions,
    validateParams,
  }
})
