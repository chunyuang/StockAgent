/**
 * usePositionManagement - 持仓管理页面数据
 *
 * 独立composable, 从后端API获取持仓+账户数据
 * 支持日期切换: 当天实时刷新, 历史日从交易归档API获取快照
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { api } from '@/api/client'
import { parseResponse } from '@/utils/scanner'
import { getChinaDate } from '@/utils/chinaDate'

export interface PositionItem {
  ts_code: string
  stock_name: string
  strategy: string
  strategy_name: string
  shares: number
  available_qty: number
  today_buy: number
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
  stop_loss_status: string
  risk_level: string
  buy_date: string
  buy_time: string
  trailing_stop?: {
    high_price: number
    trailing_stop_pct: number
    activated: boolean
    activated_at: string
    stop_price: number
  }
}

interface AccountInfo {
  total_assets: number
  available_cash: number
  market_value: number
  total_profit: number
}

interface SentimentInfo {
  score: number
  period: string  // 英文: rising/differentiation/chaos/bearish
  phase: string   // 中文: 高潮/分化/震荡/冰点
}

interface TradeStats {
  signal_count: number
  buy_count: number
  sell_count: number
  max_positions: number
}

interface EquityPoint {
  date: number
  total_assets: number
  net_value: number
  drawdown_pct: number
  position_ratio: number
  position_count: number
  realized_profit: number
  unrealized_profit: number
  buys: number
  sells: number
  buy_amount: number
  sell_amount: number
  daily_pnl: number
}

export function usePositionManagement() {
  const today = getChinaDate().replace(/-/g, '')
  const date = ref(getChinaDate())
  const isToday = computed(() => date.value.replace(/-/g, '') === today)
  const loading = ref(false)
  const positions = ref<PositionItem[]>([])
  const account = ref<AccountInfo | null>(null)
  const sentiment = ref<SentimentInfo | null>(null)
  const tradeStats = ref<TradeStats | null>(null)
  const circuitBreaker = ref<{ position_cap: number; cumulative_drawdown: number; buy_paused: boolean } | null>(null)
  const error = ref<string | null>(null)

  // 历史净值数据
  const equityHistory = ref<EquityPoint[]>([])
  const availableDates = ref<number[]>([])

  // 排序
  const sortKey = ref<'profit' | 'market_value' | 'cost' | 'hold_days' | 'risk'>('profit')
  const sortAsc = ref(false)

  // 汇总
  const totalMarketValue = computed(() =>
    positions.value.reduce((s, p) => s + (p.market_value || 0), 0)
  )
  const totalCost = computed(() =>
    positions.value.reduce((s, p) => s + (p.cost_price || 0) * (p.shares || 0), 0)
  )
  const totalProfit = computed(() =>
    positions.value.reduce((s, p) => s + (p.profit_amount || 0), 0)
  )
  const totalProfitPct = computed(() =>
    totalCost.value > 0 ? (totalProfit.value / totalCost.value * 100) : 0
  )
  const positionRatio = computed(() => {
    const acc = account.value
    if (acc && acc.total_assets > 0) {
      return (acc.market_value / acc.total_assets * 100).toFixed(1)
    }
    return '0.0'
  })
  const positionCount = computed(() => positions.value.length)

  // 盈亏分布
  const profitCount = computed(() => positions.value.filter(p => (p.profit_pct || 0) >= 0).length)
  const lossCount = computed(() => positions.value.filter(p => (p.profit_pct || 0) < 0).length)

  // 风险分布
  const riskDistribution = computed(() => {
    const dist = { normal: 0, elevated: 0, high: 0 }
    for (const p of positions.value) {
      const lvl = p.risk_level || 'normal'
      if (lvl in dist) dist[lvl as keyof typeof dist]++
    }
    return dist
  })

  // 策略分布
  const strategyDistribution = computed(() => {
    const map: Record<string, { count: number; profit: number; mv: number }> = {}
    for (const p of positions.value) {
      const key = p.strategy_name || p.strategy || 'unknown'
      if (!map[key]) map[key] = { count: 0, profit: 0, mv: 0 }
      map[key].count++
      map[key].profit += p.profit_amount || 0
      map[key].mv += p.market_value || 0
    }
    return Object.entries(map).map(([name, v]) => ({ name, ...v }))
  })

  // 排序后的持仓
  const sortedPositions = computed(() => {
    const arr = [...positions.value]
    const key = sortKey.value
    const asc = sortAsc.value
    arr.sort((a, b) => {
      let va: number, vb: number
      switch (key) {
        case 'profit':
          va = a.profit_pct || 0; vb = b.profit_pct || 0; break
        case 'market_value':
          va = a.market_value || 0; vb = b.market_value || 0; break
        case 'cost':
          va = (a.cost_price || 0) * (a.shares || 0); vb = (b.cost_price || 0) * (b.shares || 0); break
        case 'risk':
          va = a.risk_level === 'high' ? 2 : a.risk_level === 'elevated' ? 1 : 0
          vb = b.risk_level === 'high' ? 2 : b.risk_level === 'elevated' ? 1 : 0; break
        default:
          va = 0; vb = 0
      }
      return asc ? va - vb : vb - va
    })
    return arr
  })

  // 当前选中的净值点(用于历史日汇总卡片)
  const currentEquity = computed(() => {
    const d = parseInt(date.value.replace(/-/g, ''))
    return equityHistory.value.find(p => p.date === d) || null
  })

  async function fetchAll() {
    loading.value = true
    error.value = null
    try {
      if (isToday.value) {
        await Promise.allSettled([fetchPositions(), fetchAccount(), fetchSentiment()])
      } else {
        await fetchArchiveDay(date.value.replace(/-/g, ''))
      }
    } finally {
      loading.value = false
    }
  }

  // 当天: 实时持仓
  async function fetchPositions() {
    try {
      const r = await api.get('/scanner/positions', { timeout: 10000 })
      const p = parseResponse(r)
      if (p.success) {
        positions.value = (p.data || []).map((item: any) => ({
          ...item,
          strategy_name: item.strategy_name || item.strategy || '',
        }))
      }
    } catch (e) {
      console.error('[usePositionManagement] fetchPositions', e)
      error.value = '获取持仓失败'
    }
  }

  // 当天: 账户状态+情绪+交易统计
  async function fetchAccount() {
    try {
      const r = await api.get('/scanner/status', { timeout: 10000 })
      const d = r as any
      if (d) {
        account.value = d?.data?.account || d?.account || null
        const s = d?.data?.sentiment || d?.sentiment || null
        if (s) {
          sentiment.value = {
            score: s.score || 0,
            period: s.period || '',
            phase: s.phase || '',
          }
        }
        // 从positions数推算max_positions
        const periodMap: Record<string, number> = { rising: 10, differentiation: 8, chaos: 6, bearish: 4 }
        const maxPos = periodMap[s?.period || ''] || 8
        tradeStats.value = {
          signal_count: d?.data?.signal_count || d?.signal_count || 0,
          buy_count: d?.data?.buy_count || d?.buy_count || 0,
          sell_count: d?.data?.sell_count || d?.sell_count || 0,
          max_positions: maxPos,
        }
        // 风控熔断状态
        const cb = d?.data?.circuit_breaker || d?.circuit_breaker || null
        if (cb) {
          circuitBreaker.value = {
            position_cap: cb.position_cap ?? 1.0,
            cumulative_drawdown: cb.cumulative_drawdown ?? 0,
            buy_paused: cb.buy_paused ?? false,
          }
        }
      }
    } catch (e) {
      console.error('[usePositionManagement] fetchAccount', e)
    }
  }

  // 当天: 情绪周期 (fetchAccount已包含, 此函数保留兼容)
  async function fetchSentiment() {
    // 情绪数据已在fetchAccount中获取
  }

  // 历史日: 从交易归档API获取
  // 注意: trading-archive API返回flat结构, 无success字段
  async function fetchArchiveDay(dateStr: string) {
    try {
      const r = await api.get(`/trading-archive/day/${dateStr}`, { timeout: 15000 })
      const d = r as any
      if (d && d.positions) {
        positions.value = (d.positions || []).map((item: any) => ({
          ts_code: item.ts_code || '',
          stock_name: item.stock_name || '',
          strategy: item.strategy || '',
          strategy_name: item.strategy || '',
          shares: item.quantity || 0,
          available_qty: item.available_qty || 0,
          today_buy: 0,
          today_buy_qty: 0,
          cost_price: item.avg_cost || 0,
          current_price: item.current_price || 0,
          profit_pct: item.profit_pct || 0,
          profit_amount: item.profit_amount || 0,
          market_value: item.market_value || 0,
          stop_loss_price: item.stop_loss_price || 0,
          stop_loss_pct: 0,
          take_profit_price: 0,
          take_profit_pct: 0,
          stop_loss_status: '',
          risk_level: 'normal',
          buy_date: item.buy_time || '',
          buy_time: '',
        }))
        const cap = d.capital || {}
        account.value = {
          total_assets: cap.total_assets || 0,
          available_cash: cap.available_cash || 0,
          market_value: cap.market_value || 0,
          total_profit: cap.total_profit || 0,
        }
      } else {
        positions.value = []
        account.value = null
      }
    } catch (e) {
      console.error('[usePositionManagement] fetchArchiveDay', e)
      error.value = '获取历史持仓失败'
      positions.value = []
      account.value = null
    }
  }

  // 获取可用日期列表 + 净值历史
  // 注意: trading-archive API返回flat结构
  async function fetchDateList() {
    try {
      const [datesRes, eqRes] = await Promise.allSettled([
        api.get('/trading-archive/dates', { timeout: 10000 }),
        api.get('/trading-archive/equity-curve', { timeout: 10000 }),
      ])
      if (datesRes.status === 'fulfilled') {
        const d = datesRes.value as any
        availableDates.value = d?.dates || []
      }
      if (eqRes.status === 'fulfilled') {
        const d = eqRes.value as any
        equityHistory.value = d?.data?.performance || d?.performance || []
      }
    } catch (e) {
      console.error('[usePositionManagement] fetchDateList', e)
    }
  }

  // 日期切换
  async function onDateChange() {
    stopAutoRefresh()
    await fetchAll()
    if (isToday.value && autoRefresh.value) {
      startAutoRefresh(REFRESH_MS)
    }
  }

  // 自动刷新
  const autoRefresh = ref(true)
  const REFRESH_MS = 5000
  let refreshTimer: ReturnType<typeof setInterval> | null = null
  function startAutoRefresh(intervalMs = REFRESH_MS) {
    stopAutoRefresh()
    refreshTimer = setInterval(fetchAll, intervalMs)
  }
  function stopAutoRefresh() {
    if (refreshTimer) { clearInterval(refreshTimer); refreshTimer = null }
  }

  onMounted(() => {
    fetchDateList()
    fetchAll()
    if (autoRefresh.value && isToday.value) startAutoRefresh()
  })
  onUnmounted(() => { stopAutoRefresh() })

  return {
    date, today, isToday, loading, error,
    positions, account, sentiment, tradeStats, circuitBreaker,
    sortKey, sortAsc,
    totalMarketValue, totalCost, totalProfit, totalProfitPct,
    positionRatio, positionCount,
    profitCount, lossCount,
    riskDistribution, strategyDistribution,
    sortedPositions,
    equityHistory, availableDates, currentEquity,
    autoRefresh,
    fetchAll, onDateChange, startAutoRefresh, stopAutoRefresh,
  }
}
