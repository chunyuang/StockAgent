/**
 * useUnifiedData - 市场监听统一数据源 (v2.9.97)
 *
 * 所有 8 个 Tab 共享此 composable, 单一数据源:
 *   - /unified/trades?date=...    交易记录
 *   - /unified/positions?date=... 持仓快照
 *   - /unified/date-availability  日期染色
 *
 * 设计原则:
 *   1. 不再各自查 broker_orders / scanner_timeline
 *   2. 同一份数据, 8 个 UI 共用
 *   3. 自动按当前选中日期刷新
 *   4. 提供 reactive 状态供 Tab 直接展示
 */
import { ref, computed, watch, type Ref } from 'vue'
import { api } from '@/api/client'

// ----- Types -----
export interface UnifiedTrade {
  trade_date: string
  time: string
  fill_time: string
  side: 'buy' | 'sell'
  ts_code: string
  stock_name: string
  quantity: number
  price: number
  amount: number
  strategy: string
  reason: string
  source: string
  order_id: string
  profit_pct: number | null
  profit_amount: number | null
  why: string | null
}

export interface UnifiedPosition {
  ts_code: string
  stock_name: string
  strategy: string
  strategy_en: string
  shares: number
  available_qty: number
  today_buy_qty: number
  cost_price: number
  current_price: number
  profit_pct: number
  profit_amount: number
  market_value: number
  stop_loss_price: number
  stop_loss_pct: number
  take_profit_price: number
  take_profit_pct: number
  stop_loss_status: 'safe' | 'near' | 'broken'
  stop_loss_desc: string
  risk_monitor_desc?: string
  buy_date: string
}

export interface PositionSummary {
  count: number
  total_market_value: number
  total_cost: number
  total_profit: number
  total_profit_pct: number
  loss_count: number
  gain_count: number
  broken_stop_count: number
}

export interface TradeSummary {
  total: number
  buy_count: number
  sell_count: number
  buy_amount: number
  sell_amount: number
  realized_profit: number
}

// ----- 工具 -----
function todayStr(): string {
  const d = new Date()
  return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}`
}

function parseResponse(r: any): { success: boolean; data: any } {
  // api/client 的响应拦截器已返回 response.data；
  // 兼容两种形态：
  // 1) { success: true, data: {...} }            ← 当前 api.get 实际返回
  // 2) { data: { success: true, data: {...} } } ← 原始 axios response 形态
  const p = typeof r?.success === 'boolean' ? r : (r?.data || r)
  return { success: !!p?.success, data: p?.data ?? p }
}

// ----- Composable -----
export function useUnifiedData(initialDate?: Ref<string> | string) {
  // 当前日期 (YYYYMMDD)
  const currentDate = ref<string>(
    typeof initialDate === 'string'
      ? initialDate
      : initialDate?.value || todayStr()
  )

  // 数据状态
  const trades = ref<UnifiedTrade[]>([])
  const tradesSummary = ref<TradeSummary>({
    total: 0, buy_count: 0, sell_count: 0,
    buy_amount: 0, sell_amount: 0, realized_profit: 0,
  })

  const positions = ref<UnifiedPosition[]>([])
  const positionsSummary = ref<PositionSummary>({
    count: 0, total_market_value: 0, total_cost: 0,
    total_profit: 0, total_profit_pct: 0,
    loss_count: 0, gain_count: 0, broken_stop_count: 0,
  })
  const positionsAsOf = ref<string>('')
  const isRealtime = ref<boolean>(true)

  // 加载状态
  const loadingTrades = ref(false)
  const loadingPositions = ref(false)
  const lastError = ref<string | null>(null)

  // 派生: 是否今天
  const isToday = computed(() => currentDate.value === todayStr())

  // ----- API 调用 -----
  async function fetchTrades(date?: string): Promise<void> {
    const d = date || currentDate.value
    loadingTrades.value = true
    lastError.value = null
    try {
      const r = await api.get(`/unified/trades?date=${d}`)
      const p = parseResponse(r)
      if (p.success) {
        trades.value = p.data?.trades || []
        tradesSummary.value = p.data?.summary || tradesSummary.value
      } else {
        trades.value = []
      }
    } catch (e: any) {
      lastError.value = e?.message || 'fetch trades failed'
      trades.value = []
    } finally {
      loadingTrades.value = false
    }
  }

  async function fetchPositions(date?: string): Promise<void> {
    const d = date ?? currentDate.value
    loadingPositions.value = true
    lastError.value = null
    try {
      // 实时(today) 不传 date 参数, 历史传 date=YYYYMMDD
      const url = d === todayStr()
        ? '/unified/positions'
        : `/unified/positions?date=${d}`
      const r = await api.get(url)
      const p = parseResponse(r)
      if (p.success) {
        positions.value = p.data?.positions || []
        positionsSummary.value = p.data?.summary || positionsSummary.value
        positionsAsOf.value = p.data?.as_of || ''
        isRealtime.value = !!p.data?.is_realtime
      } else {
        positions.value = []
      }
    } catch (e: any) {
      lastError.value = e?.message || 'fetch positions failed'
      positions.value = []
    } finally {
      loadingPositions.value = false
    }
  }

  async function refresh(): Promise<void> {
    await Promise.all([fetchTrades(), fetchPositions()])
  }

  // 监听日期变化, 自动刷新 (immediate: 确保首次mount即加载数据)
  watch(currentDate, () => {
    refresh()
  }, { immediate: true })

  // 派生数据 (供不同 Tab 用)
  const buys = computed(() => trades.value.filter(t => t.side === 'buy'))
  const sells = computed(() => trades.value.filter(t => t.side === 'sell'))

  const profitablePositions = computed(() =>
    positions.value.filter(p => p.profit_pct > 0)
  )
  const losingPositions = computed(() =>
    positions.value.filter(p => p.profit_pct < 0)
  )
  const brokenStopPositions = computed(() =>
    positions.value.filter(p => p.stop_loss_status === 'broken')
  )

  function setDate(date: string) {
    currentDate.value = date
  }

  return {
    // 状态
    currentDate,
    trades,
    tradesSummary,
    positions,
    positionsSummary,
    positionsAsOf,
    isRealtime,
    loadingTrades,
    loadingPositions,
    lastError,

    // 派生
    isToday,
    buys,
    sells,
    profitablePositions,
    losingPositions,
    brokenStopPositions,

    // 方法
    fetchTrades,
    fetchPositions,
    refresh,
    setDate,
  }
}
