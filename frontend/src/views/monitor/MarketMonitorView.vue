<script setup lang="ts">
/**
 * MarketMonitorView — 超短量化实盘监控 (3列布局)
 * 左: 策略控制+快捷操作 / 中: 信号+行情 / 右: 持仓+统计
 * 底: 时间线 / 顶: 状态栏
 */
import { ref, computed, onMounted, onUnmounted, onErrorCaptured, reactive, watch, nextTick } from 'vue'
import {
  ElButton, ElTag, ElEmpty,
  ElSwitch, ElInputNumber, ElSlider,
  ElTabs, ElTabPane, ElDialog, ElMessage, ElBadge,
  ElInput, ElSelect, ElOption, ElDatePicker,
  ElMessageBox,
} from 'element-plus'
import { api } from '@/api/client'
import SignalTracePanel from './SignalTracePanel.vue'
import StrategyPerfBoard from './StrategyPerfBoard.vue'
import PositionRiskMatrix from './PositionRiskMatrix.vue'
import MiniKline from './MiniKline.vue'
import MarketSentiment from './MarketSentiment.vue'
import SystemHealth from './SystemHealth.vue'
import KeyboardShortcuts from './KeyboardShortcuts.vue'
import { useThemeStore } from '@/stores/theme'
import { useScannerStore } from '@/stores/scanner'
import {
  strategyMeta, strategyCN,
  pipelineLabels,
  modeMeta,
  factorLabel,
  parseResponse, signalRemaining as _signalRemaining, formatRemaining,
  normalizePct, formatSlTp,
} from '@/utils/scanner'
import VChart from 'vue-echarts'

interface ScanStats { scans: number; signals_found: number; trades_executed: number; stop_losses: number; take_profits: number; stocks_scanned: number }
interface ScannerStatus { is_running: boolean; scan_count: number; last_scan_time: string; active_signals: number; positions: number; stocks_scanned: number; stats: ScanStats; account_id: string; trade_mode: string; dry_run?: boolean; circuit_breaker_paused?: boolean; circuit_breaker?: { trading_paused: boolean; pause_reason: string }; account: { total_assets: number; available_cash: number; market_value: number; total_profit: number }; data_sources?: Array<{ name: string; available: boolean; stocks: number; calls: number; limit: number; note: string }> }
interface ScanSignal { ts_code: string; stock_name: string; strategy: string; strategy_name: string; signal_type: string; price: number; pct_chg: number; volume_ratio: number; turnover_rate: number; is_limit_up: boolean; limit_up_count: number; confidence: number; reason: string; scan_time: string; factors: Record<string, number>; key_factors?: Record<string, string>; decision_detail?: Record<string, any>; signal_status?: string; layer_trace?: Record<string, any>; created_at?: number }
interface PositionInfo { ts_code: string; stock_name: string; strategy: string; strategy_name?: string; shares: number; available_qty: number; cost_price: number; current_price: number; profit_pct: number; profit_amount?: number; market_value?: number; today_buy: number; stop_loss_pct?: number; take_profit_pct?: number; stop_loss_price?: number; take_profit_price?: number; distance_to_stop?: number; risk_level?: string; trailing_stop?: { high_price: number; trailing_stop_pct: number; activated: boolean; stop_price: number; activated_at?: string }; effective_stop_price?: number }
interface TimelineItem { time: string; action: string; ts_code: string; stock_name: string; strategy: string; shares: number; price: number; reason: string; profit_pct?: number; profit_amount?: number; decision_detail?: Record<string, any> }
interface StrategyConfig { id: string; name: string; enabled: boolean; params: Record<string, any>; riskParams: Record<string, any>; paramDescriptions: ParamDesc[]; riskDescriptions: ParamDesc[] }
interface ParamDesc { key: string; label: string; value: any; displayValue: string; unit: string; min: number; max: number; step: number }
interface GlobalRisk { stop_loss_pct: number; take_profit_pct: number; max_position_pct: number; max_positions: number }
interface HealthData { overall_status: 'healthy' | 'warning' | 'critical'; circuit_breaker: { trading_paused: boolean; pause_reason: string; consecutive_losses: number; max_consecutive_losses: number }; risk_metrics: { daily_drawdown_pct: number; max_drawdown_pct: number; position_ratio: number }; data_sources: Array<{ name: string; available: boolean; last_check: string }> }

const loading = ref(false), autoRefresh = ref(true), soundEnabled = ref(false)
const themeStore = useThemeStore()
const scannerStore = useScannerStore() // 【Phase4.1:Scanner Store】
watch(() => themeStore.isDark, () => { /* theme changes auto-propagate via CSS vars */ })
let refreshTimer: any = null
let ws: WebSocket | null = null
let wsReconnectTimer: any = null
const status = ref<ScannerStatus | null>(null)
const signals = ref<ScanSignal[]>([])
const positions = ref<PositionInfo[]>([])
const signalTraceVisible = ref(false)
const timeline = ref<TimelineItem[]>([])
const orders = ref<any[]>([])
const closedPositions = computed(() => {
  // 优先从timeline匹配买卖(有完整决策链路),fallback到orders
  const tlBuys = timeline.value.filter(t => t.action === 'buy')
  const tlSells = timeline.value.filter(t => t.action === 'sell')
  const result: any[] = []
  for (const sell of tlSells) {
    const buy = tlBuys.find(b => b.ts_code === sell.ts_code && b.strategy === sell.strategy && !result.some(r => r.buy_time === b.time))
    const buyPrice = buy?.price || sell.decision_detail?.cost_price || 0
    result.push({
      ts_code: sell.ts_code,
      stock_name: sell.stock_name || buy?.stock_name || '',
      strategy: sell.strategy,
      buy_price: buyPrice,
      sell_price: sell.price,
      profit_amount: sell.profit_amount || (sell.price - buyPrice) * (sell.shares || 0),
      profit_pct: sell.profit_pct || (buyPrice > 0 ? (sell.price - buyPrice) / buyPrice * 100 : 0),
      buy_time: buy?.time || '',
      sell_time: sell.time || '',
    })
  }
  // 补充orders中的卖出(timeline可能不全)
  const covered = new Set(result.map(r => r.ts_code + r.strategy))
  for (const o of orders.value.filter(o => o.side === 'sell' && o.filled_price > 0)) {
    const key = o.ts_code + o.strategy
    if (covered.has(key)) continue
    const buy = orders.value.find(b => b.side === 'buy' && b.ts_code === o.ts_code && b.strategy === o.strategy)
    const buyPrice = buy?.filled_price || 0
    result.push({
      ts_code: o.ts_code,
      stock_name: o.stock_name || '',
      strategy: o.strategy,
      buy_price: buyPrice,
      sell_price: o.filled_price,
      profit_amount: (o.filled_price - buyPrice) * o.filled_qty,
      profit_pct: buyPrice > 0 ? (o.filled_price - buyPrice) / buyPrice * 100 : 0,
      buy_time: buy?.create_time || '',
      sell_time: o.create_time || '',
    })
  }
  return result.sort((a, b) => Math.abs(b.profit_amount) - Math.abs(a.profit_amount))
})
const limitPools = ref<{limit_up: any[], limit_down: any[], broken: any[]}>({limit_up: [], limit_down: [], broken: []})
const limitPoolTab = ref('limit_up')
const dailyReport = ref<any>(null)
const strategies = ref<StrategyConfig[]>([])
const globalRisk = ref<GlobalRisk | null>(null)
const editingStrategy = ref<StrategyConfig | null>(null)
const editDialogVisible = ref(false)
const editTab = ref('params')
const editParams = ref<Record<string, any>>({})
const editRiskParams = ref<Record<string, any>>({})
const saving = ref(false)
const scannerApi = '/scanner', configApi = '/strategy-config'
// Wrappers for shared constants (adapted for template usage)
const layerLabel = (k: string) => { const label = pipelineLabels[k]; if (!label) return k; const prefix = k.split('_')[0]; return prefix + ' ' + label }
const nowMs = ref(Date.now())
const sigRemaining = (sig: ScanSignal) => _signalRemaining(sig.created_at || 0, nowMs.value)
// factorCN, factorLabel imported from @/utils/scanner
// layerLabel uses pipelineLabels from @/utils/scanner (see wrapper above)
const dataSources = ref<any[]>([])
const brokers = ref<any[]>([])
const healthData = ref<HealthData | null>(null)
const healthStatus = computed(() => healthData.value?.overall_status || 'unknown')
const healthEmoji = computed(() => ({ healthy: '🟢', warning: '🟡', critical: '🔴' }[healthStatus.value] || '⚪'))
const healthCN = computed(() => ({ healthy: '正常', warning: '预警', critical: '熔断' }[healthStatus.value] || '未知'))
const healthClass = computed(() => ({ healthy: 'ok', warning: 'warn', critical: 'crit' }[healthStatus.value] || 'unknown'))
const riskBarCollapsed = ref(true)
const focusIndex = ref(-1)
const emergencyLiquidating = ref(false)
const signalFilter = ref('all')
const filteredSignals = computed(() => { if (signalFilter.value === 'all') return signals.value; if (signalFilter.value === 'anomaly') return signals.value.filter(s => s.strategy.startsWith('anomaly_')); return signals.value.filter(s => s.strategy === signalFilter.value) })
const tradeDetailVisible = ref(false), tradeDetailData = ref<any>(null), tradeAuditData = ref<any[]>([]), tradeAuditVisible = ref(false)
// 追踪止损编辑
const trailEditPct = ref(3)
const trailSaving = ref(false)
async function setTrailingStop(ts_code: string, activated: boolean) {
  trailSaving.value = true
  try {
    const r = await api.put(`${scannerApi}/trailing-stop/${ts_code}`, { trailing_stop_pct: trailEditPct.value / 100, activated })
    const p = parseResponse(r)
    if (p.success) {
      ElMessage.success(activated ? '追踪止损已激活' : '追踪止损已停用')
      // 刷新持仓和详情
      await fetchScanner()
      if (tradeDetailData.value?.ts_code === ts_code) {
        const dr = await api.get(`${scannerApi}/trade-detail/${ts_code}`)
        if (dr?.success) tradeDetailData.value = dr.data
      }
    } else ElMessage.warning(p.data?.message || '操作失败')
  } catch { ElMessage.error('操作失败') } finally { trailSaving.value = false }
}
const manualTrade = reactive({ ts_code: '', stock_name: '', side: 'buy', quantity: 0, price: 0 })
const manualQuote = ref<any>(null)
const isRunning = computed(() => status.value?.is_running ?? false)
const accountInfo = computed(() => status.value?.account ?? { total_assets: 0, available_cash: 0, market_value: 0, total_profit: 0 })
const positionRatio = computed(() => accountInfo.value.market_value > 0 ? (accountInfo.value.market_value / accountInfo.value.total_assets * 100).toFixed(1) : '0')
const totalPnl = computed(() => accountInfo.value.total_profit)
const circuitBreakerPaused = computed(() => status.value?.circuit_breaker?.trading_paused ?? false)
const posSort = ref('profit')
const sortedPositions = computed(() => {
  const arr = [...positions.value]
  switch(posSort.value) {
    case 'profit': return arr.sort((a, b) => a.profit_pct - b.profit_pct)
    case 'cost': return arr.sort((a, b) => b.market_value - a.market_value)
    case 'strategy': return arr.sort((a, b) => (a.strategy || '').localeCompare(b.strategy || ''))
    case 'time': return arr.sort((a, b) => (b.buy_time || '').localeCompare(a.buy_time || ''))
    default: return arr
  }
})
function playSignalSound() {
  if (!soundEnabled.value) return
  try {
    const ctx = new AudioContext()
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.connect(gain)
    gain.connect(ctx.destination)
    osc.frequency.value = 880
    osc.type = 'sine'
    gain.gain.value = 0.3
    osc.start()
    gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.3)
    osc.stop(ctx.currentTime + 0.3)
  } catch {}
}
function distanceToStopLoss(pos: PositionInfo): string { if (pos.stop_loss_price && pos.stop_loss_price > 0 && pos.current_price > 0) { const dist = ((pos.current_price - pos.stop_loss_price) / pos.current_price * 100); return dist.toFixed(1) + '%'; } const slPct = normalizePct(pos.stop_loss_pct, 3); return (pos.profit_pct + slPct).toFixed(1) + '%' }

// 【P1-7】交易确认弹窗(含loading防重复)
const confirmVisible = ref(false)
const confirmLoading = ref(false)
const confirmData = reactive({ title: '', message: '', onConfirm: () => {} })
function showConfirm(title: string, message: string, onConfirm: () => void) { confirmData.title = title; confirmData.message = message; confirmData.onConfirm = onConfirm; confirmVisible.value = true; confirmLoading.value = false }
async function handleConfirm() { if (confirmLoading.value) return; confirmLoading.value = true; try { await confirmData.onConfirm() } finally { confirmLoading.value = false; confirmVisible.value = false } }

// 【P1-6】复盘报告
const dailyReportVisible = ref(false)
// 盈亏曲线
const pnlHistory = ref<{time: string, value: number}[]>([])
const perfData = ref<Array<{time:string,net_value:number,drawdown:number}>>([])

// ==================== 盘前竞价Tab ====================
const premarketSignals = ref<any[]>([])
const premarketStatus = ref<'waiting' | 'active' | 'ended' | 'off'>('off')
const premarketCandidates = ref<any[]>([])
const auctionTopGainers = ref<any[]>([])

// ==================== 扫描追踪Tab ====================
const scanHistory = ref<any[]>([])
const selectedScanIdx = ref(-1)
const scanTraceDetail = ref<any>(null)
const scanHistoryLoading = ref(false)
const scanTraceDate = ref('')  // 日期过滤器
const scanTraceFilter = ref<'passed' | 'rejected' | 'summary'>('passed')  // 【v2.9.7: 候选过滤模式】
const scanTraceLoadingMore = ref(false)  // 【v2.9.7: 加载更多loading】

// ==================== 复盘Tab ====================
const reviewTab = ref<'daily' | 'weekly' | 'monthly'>('daily')
const reviewDate = ref(new Date().toISOString().slice(0, 10))
const dailyReportData = ref<any>(null)
const weeklyReportData = ref<any>(null)
const tradeAttributions = ref<any[]>([])
const reviewLoading = ref(false)
const executionQuality = ref<any>(null)
const liveBacktestDiff = ref<any[]>([])

// ==================== 自动交易 + 参数对比 ====================
const autoTrades = ref<any[]>([])
const paramCompare = ref<any>(null)
const paramCompareLoading = ref(false)
const scanConfig = ref<any>(null)
const scanConfigLoading = ref(false)
function updatePnlHistory() {
  const pnl = totalPnl.value
  if (pnl === 0 && pnlHistory.value.length === 0) return
  pnlHistory.value.push({ time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }), value: pnl })
  if (pnlHistory.value.length > 60) pnlHistory.value = pnlHistory.value.slice(-60)
}
async function fetchPerformanceHistory() {
  try {
    const r = await api.get(`${scannerApi}/performance-history?days=30`)
    const p = parseResponse(r)
    if (p.success && p.data?.length > 0) {
      perfData.value = p.data.map((s: any) => ({ time: (s.timestamp || s.date || '').substring(5, 16), net_value: s.net_value || s.total_assets / 1000000, drawdown: s.drawdown_pct || 0 }))
      return
    }
    // fallback: from timeline
    const tl = await api.get(`${scannerApi}/timeline/history?days=30`)
    const tp = parseResponse(tl)
    if (tp.success && tp.data?.length > 0) {
      let nav = 1.0, peak = 1.0
      perfData.value = tp.data.map((item: any) => {
        const profitAmount = item.profit_amount || 0
        nav *= (1 + profitAmount / (1000000 * nav))
        peak = Math.max(peak, nav)
        const dd = nav < peak ? (nav / peak - 1) * 100 : 0
        return { time: (item.date || item.time || '').substring(0, 16), net_value: nav, drawdown: dd }
      })
    }
  } catch { /* ignore */ }
}

// ==================== 盘前竞价Tab 数据 ====================
async function fetchPremarketData() {
  try {
    const r = await api.get(`${scannerApi}/premarket-status`)
    const p = parseResponse(r)
    if (p.success && p.data) {
      premarketSignals.value = p.data.auction_signals || []
      premarketStatus.value = p.data.status || 'off'
      premarketCandidates.value = p.data.candidates || []
      auctionTopGainers.value = p.data.top_gainers || []
    }
  } catch { /* ignore */ }
}

// ==================== 扫描追踪Tab 数据 ====================
async function fetchScanHistory() {
  scanHistoryLoading.value = true
  try {
    const dateParam = scanTraceDate.value ? `&date=${scanTraceDate.value.replace(/-/g, '')}` : ''
    const r = await api.get(`${scannerApi}/scan-traces?limit=30${dateParam}`, { timeout: 15000 })
    const p = parseResponse(r)
    if (p.success && p.data?.length) {
      scanHistory.value = p.data
      if (selectedScanIdx.value < 0 && p.data.length) selectedScanIdx.value = 0
    }
  } catch { /* ignore */ }
  finally { scanHistoryLoading.value = false }
}
async function fetchScanTrace(scanId: string) {
  scanTraceDetail.value = null  // 清空旧数据防止渲染旧内容
  scanTraceFilter.value = 'passed'  // 重置过滤
  try {
    // 【v2.9.7: 默认只加载passed候选, 避免卡顿】
    const r = await api.get(`${scannerApi}/scan-traces/${scanId}?status=passed&limit=50`, { timeout: 10000 })
    const p = parseResponse(r)
    if (p.success) scanTraceDetail.value = p.data
  } catch { /* ignore */ }
}
// 【v2.9.7】切换候选过滤模式
async function switchScanTraceFilter(filter: 'passed' | 'rejected' | 'summary') {
  if (!scanTraceDetail.value) return
  const scanId = scanTraceDetail.value.scan_id
  if (!scanId) return
  scanTraceFilter.value = filter
  scanTraceLoadingMore.value = true
  try {
    const r = await api.get(`${scannerApi}/scan-traces/${scanId}?status=${filter}&limit=50`, { timeout: 10000 })
    const p = parseResponse(r)
    if (p.success) {
      scanTraceDetail.value = { ...scanTraceDetail.value, candidates: p.data.candidates || [], _pagination: p.data._pagination, rejected_layer_stats: p.data.rejected_layer_stats }
    }
  } catch { /* ignore */ }
  finally { scanTraceLoadingMore.value = false }
}
// 【v2.9.7】中文化rejection_layer
const rejectionLayerCN: Record<string, string> = {
  L1_force_empty: '强制空仓', L2_special_period: '特殊时期', L3_sentiment: '情绪周期',
  L4_premarket: '盘前预选', L5_auction: '竞价过滤', L6_strategy: '策略量能',
  L7_ranking: '综合排序', L8_position: '仓位控制', L9_execute: '执行确认',
}
const rejectionReasonCN = (reason: string) => {
  if (!reason) return reason
  const map: Record<string, string> = {
    'force_empty': '强制空仓期', 'special_period': '特殊时期限制',
    'sentiment_blocked': '情绪周期不允许', 'not_in_premarket': '未在盘前预选',
    'auction_filter': '竞价过滤', 'strategy_score_low': '策略评分不足',
    'ranking_too_low': '综合排名太低', 'position_full': '仓位已满',
    'insufficient_cash': '资金不足', 'already_held': '已持有',
    'limit_up_unbuyable': '涨停不可买', 'duplicate_signal': '重复信号',
  }
  return map[reason] || reason
}

// ==================== 复盘Tab 数据 ====================
async function fetchReviewData() {
  reviewLoading.value = true
  try {
    // 用 Promise.allSettled 防止单个API失败阻塞其他，并加15秒超时
    const promises: Promise<any>[] = []
    const opts = { timeout: 15000 }
    
    if (reviewTab.value === 'daily') {
      promises.push(
        api.get(`${scannerApi}/daily-report`, opts).then(r => { const p = parseResponse(r); if (p.success) dailyReportData.value = p.data }),
        api.get(`${scannerApi}/trade-attribution?date=${reviewDate.value}`, opts).then(r => { const p = parseResponse(r); if (p.success) tradeAttributions.value = p.data || [] }),
      )
    } else if (reviewTab.value === 'weekly') {
      promises.push(
        api.get(`${scannerApi}/weekly-report`, opts).then(r => { const p = parseResponse(r); if (p.success) weeklyReportData.value = p.data }),
      )
    }
    
    // 执行质量和实盘vs回测(所有tab共用)
    promises.push(
      api.get(`${scannerApi}/execution-quality`, opts).then(r => { const p = parseResponse(r); if (p.success) executionQuality.value = p.data }),
      api.get(`${scannerApi}/backtest-compare`, opts).then(r => { const p = parseResponse(r); if (p.success) liveBacktestDiff.value = p.data || [] }),
    )
    
    await Promise.allSettled(promises)
  } catch { /* ignore */ }
  finally { reviewLoading.value = false }
}

// ==================== 自动交易 + 参数对比 数据 ====================
async function fetchAutoTrades() {
  try {
    const r = await api.get(`${scannerApi}/auto-trades?limit=50`)
    const p = parseResponse(r)
    if (p.success) autoTrades.value = p.data || []
  } catch { /* ignore */ }
}
async function fetchParamCompare() {
  paramCompareLoading.value = true
  try {
    const r = await api.get(`${scannerApi}/strategy-params-compare`)
    const p = parseResponse(r)
    if (p.success) paramCompare.value = p.data
  } catch { /* ignore */ }
  finally { paramCompareLoading.value = false }
}
async function fetchScanConfig() {
  scanConfigLoading.value = true
  try {
    const r = await api.get(`${scannerApi}/scan-config`)
    const p = parseResponse(r)
    if (p.success) scanConfig.value = p.data
  } catch { /* ignore */ }
  finally { scanConfigLoading.value = false }
}
const pnlOption = computed(() => {
  const source = perfData.value.length > 0 ? perfData.value : pnlHistory.value.map(p => ({ time: p.time, net_value: p.value / 1000000 + 1, drawdown: 0 }))
  return {
    grid: { top: 10, right: 10, bottom: 20, left: 50 },
    tooltip: { trigger: 'axis' as const, formatter: (p: any) => `${p[0].axisValue}<br/>净值: ${p[0].value.toFixed(4)}${p[1] ? '<br/>回撤: ' + p[1].value.toFixed(2) + '%' : ''}` },
    xAxis: { type: 'category', data: source.map(p => p.time), axisLabel: { color: 'var(--text-tertiary)', fontSize: 10 } },
    yAxis: [
      { type: 'value', axisLabel: { color: 'var(--text-tertiary)', fontSize: 10 }, splitLine: { lineStyle: { color: 'var(--border-light)' } } },
      { type: 'value', position: 'right', axisLabel: { color: 'var(--stock-up)', fontSize: 9, formatter: '{value}%' }, splitLine: { show: false } },
    ],
    series: [
      { type: 'line', data: source.map(p => p.net_value), smooth: true, lineStyle: { color: 'var(--stock-down)', width: 2 }, areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'var(--stock-down-bg)' }, { offset: 1, color: 'rgba(0,0,0,0)' }] } } },
      ...(perfData.value.length > 0 ? [{ type: 'bar' as const, yAxisIndex: 1, data: source.map(p => p.drawdown), itemStyle: { color: 'rgba(103,194,58,0.3)' }, barWidth: 3 }] : []),
    ],
    backgroundColor: 'transparent',
  }
})

// 【P1-4】信号过期倒计时
// nowMs defined at top
let nowTimer: any = null
// signalRemaining/formatRemaining/SIGNAL_EXPIRE_MS imported from @/utils/scanner
// ==================== Tab 导航 ====================
const activeTab = ref<'guide' | 'trading' | 'premarket' | 'scan-trace' | 'review' | 'risk' | 'history' | 'ops'>('guide')
watch(activeTab, (tab) => {
  try {
    if (tab === 'premarket') fetchPremarketData()
    if (tab === 'scan-trace') fetchScanHistory()
    if (tab === 'review') { fetchReviewData(); fetchParamCompare() }
    if (tab === 'history') { fetchTimeline(); fetchOrders(); fetchAuditLog() }
    if (tab === 'ops') { fetchAutoTrades(); fetchScanConfig() }
  } catch (e) { console.error('[Tab] error:', e) }
})

const tradeMode = ref('simulated')
const replayDate = ref('')
const replayDateVisible = ref(false)
const replayDateInput = ref('')

const auditLog = ref<any[]>([])
const auditLogLoading = ref(false)
async function fetchAuditLog() {
  auditLogLoading.value = true
  try {
    const r = await api.get(`${scannerApi}/audit-log`)
    const p = parseResponse(r)
    if (p.success && p.data) {
      auditLog.value = (p.data || []).map((log: any) => {
        // 格式化时间
        const ts = log.timestamp
        const time = ts ? new Date(typeof ts === 'number' ? ts * 1000 : ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : ''
        // 格式化动作
        const actionMap: Record<string, string> = {
          buy: '🟢 买入', sell: '🔴 卖出', blocked: '⛔ 拦截',
          force_sell: '🚨 强卖', signal: '📡 信号', position_check: '🔍 检查',
        }
        const action = actionMap[log.action] || log.action || '-'
        // 格式化详情: 股票+策略+原因
        const name = log.stock_name || ''
        const code = log.ts_code || ''
        const strategy = log.strategy ? `[${log.strategy}]` : ''
        const reason = log.reason || ''
        const sentiment = log.sentiment ? `情绪=${log.sentiment}` : ''
        const posRatio = log.position_ratio ? `仓位=${(log.position_ratio * 100).toFixed(0)}%` : ''
        const detail = [name || code, strategy, reason, sentiment, posRatio].filter(Boolean).join(' ')
        return { time, action, detail, ts_code: code }
      })
    }
  } catch { auditLog.value = [] }
  finally { auditLogLoading.value = false }
}

async function openTradeDetail(ts_code: string) { try { const r = await api.get(`${scannerApi}/trade-detail/${ts_code}`); const p = parseResponse(r); if (p.success) { tradeDetailData.value = p.data; tradeDetailVisible.value = true } } catch (e: any) { ElMessage.error('获取详情失败') } }
async function openTradeAudit() { try { const r = await api.get(`${scannerApi}/trade-audit`); const p = parseResponse(r); if (p.success) { tradeAuditData.value = p.data; tradeAuditVisible.value = true } } catch (e: any) { ElMessage.error('获取审查失败') } }
function formatDecisionDetail(detail: any): string[] {
  if (!detail) return ['无决策详情']; const lines: string[] = []
  if (detail.signal_reason) lines.push(`📋 选股原因: ${detail.signal_reason}`)
  if (detail.filter_pipeline) { const fp = detail.filter_pipeline; lines.push('【9层筛选管道】'); for (const [l, a] of Object.entries(fp.layers_applied || {})) { lines.push(`  ${a ? '✅' : '⏭️'} ${layerLabel(l)}: ${fp.layer_details?.[l] || (a ? '生效' : '跳过')}`) }; lines.push(`  最终仓位系数: ${fp.position_ratio ? (fp.position_ratio * 100).toFixed(0) + '%' : '未知'}`) }
  if (detail.execution) { const ex = detail.execution; lines.push('【执行决策】'); if (ex.position_ratio) lines.push(`  仓位比例: ${(ex.position_ratio * 100).toFixed(0)}%`); if (ex.available_cash) lines.push(`  可用资金: ¥${ex.available_cash?.toFixed(0)}`); if (ex.max_amount) lines.push(`  最大买入: ¥${ex.max_amount?.toFixed(0)}`); if (ex.shares) lines.push(`  买入股数: ${ex.shares}股`); if (ex.total_cost) lines.push(`  成本: ¥${ex.total_cost?.toFixed(0)}`); if (ex.filled_price) lines.push(`  成交价: ¥${ex.filled_price?.toFixed(2)}`); if (ex.sentiment) { const s = ex.sentiment; lines.push(`  情绪: ${s.score?.toFixed(0) || '?'}→${s.period || '?'} (${s.phase_name || ''})`) }; if (ex.circuit_breaker) lines.push(`  熔断: ${ex.circuit_breaker.paused ? '⛔暂停' : '✅正常'}(连续亏损${ex.circuit_breaker.consecutive_losses})`); if (ex.position_count_before !== undefined) lines.push(`  执行前持仓: ${ex.position_count_before}只`) }
  if (detail.factors) { lines.push('【关键因子】'); for (const [k, v] of Object.entries(detail.factors)) { if (v !== 0 && v !== null) lines.push(`  ${factorLabel(k)}: ${typeof v === 'number' ? v.toFixed(2) : v}`) } }
  if (detail.sell_reason) { lines.push('【卖出决策】'); lines.push(`  原因: ${detail.sell_reason}`); if (detail.profit_pct) lines.push(`  盈亏: ${detail.profit_pct.toFixed(2)}%`); if (detail.profit_amount) lines.push(`  盈亏额: ¥${detail.profit_amount.toFixed(0)}`); if (detail.cost_price) lines.push(`  成本: ¥${detail.cost_price?.toFixed(2)}`); if (detail.current_price) lines.push(`  现价: ¥${detail.current_price?.toFixed(2)}`); if (detail.stop_loss_pct) lines.push(`  止损线: ${detail.stop_loss_pct}%`); if (detail.take_profit_pct) lines.push(`  止盈线: ${detail.take_profit_pct}%`); if (detail.stop_loss_price) lines.push(`  止损价: ¥${detail.stop_loss_price?.toFixed(2)}`); if (detail.take_profit_price) lines.push(`  止盈价: ¥${detail.take_profit_price?.toFixed(2)}`) }
  return lines
}
async function quickBuy(sig: ScanSignal) { const a = status.value?.account; if (!a) { ElMessage.warning('请先启动'); return } const q = Math.floor(a.available_cash * 0.25 / sig.price / 100) * 100; if (q <= 0) { ElMessage.warning('资金不足'); return } showConfirm('确认买入', `${sig.stock_name} ${sig.ts_code}\n${sig.strategy_name} | 涨${sig.pct_chg >= 0 ? '+' : ''}${sig.pct_chg.toFixed(1)}%\n买入 ${q}股 × ¥${sig.price.toFixed(2)} ≈ ¥${(q * sig.price).toFixed(0)}`, async () => { try { const r = await api.post(`${scannerApi}/trade`, { ts_code: sig.ts_code, stock_name: sig.stock_name, side: 'buy', quantity: q, price: sig.price, order_type: 'market', strategy: sig.strategy, reason: sig.reason }); const p = parseResponse(r); if (p.success) { ElMessage.success(`买入${sig.stock_name} ${q}股@${p.data.filled_price?.toFixed(2)}`); fetchScanner() } else ElMessage.error('失败') } catch (e: any) { ElMessage.error('买入失败') } }) }
async function quickSell(pos: PositionInfo) { if (pos.available_qty <= 0) { ElMessage.warning('T+1限制'); return } showConfirm('确认卖出', `${pos.stock_name} ${pos.ts_code}\n${pos.profit_pct >= 0 ? '+' : ''}${pos.profit_pct.toFixed(1)}% | 卖出 ${pos.available_qty}股\n成本 ¥${pos.cost_price.toFixed(2)} → 现价 ¥${pos.current_price.toFixed(2)} ≈ ¥${(pos.available_qty * pos.current_price).toFixed(0)}`, async () => { try { const r = await api.post(`${scannerApi}/trade`, { ts_code: pos.ts_code, stock_name: pos.stock_name, side: 'sell', quantity: pos.available_qty, price: pos.current_price, order_type: 'market', strategy: pos.strategy, reason: `手动卖出 ${pos.profit_pct >= 0 ? '+' : ''}${pos.profit_pct.toFixed(1)}%` }); const p = parseResponse(r); if (p.success) { ElMessage.success(`卖出${pos.stock_name} ${pos.available_qty}股@${p.data.filled_price?.toFixed(2)}`); fetchScanner() } else ElMessage.error('失败') } catch (e: any) { ElMessage.error('卖出失败') } }) }
async function onManualCodeChange(code: string) {
  if (!code || code.length < 9) { manualQuote.value = null; return }
  // 优先从持仓/信号缓存获取
  const p = positions.value.find(x => x.ts_code === code)
  if (p) { manualQuote.value = { price: p.current_price, cost: p.cost_price, name: p.stock_name }; manualTrade.price = p.current_price; if (!manualTrade.stock_name) manualTrade.stock_name = p.stock_name; return }
  const s = signals.value.find(x => x.ts_code === code)
  if (s) { manualQuote.value = { price: s.price, name: s.stock_name }; manualTrade.price = s.price; if (!manualTrade.stock_name) manualTrade.stock_name = s.stock_name; return }
  // 缓存未命中则从quote API获取
  try { const r = await api.get(`${scannerApi}/quote/${code}`); const p = parseResponse(r); if (p.success) { manualQuote.value = { price: p.data.price, name: p.data.name, pct_chg: p.data.pct_chg }; manualTrade.price = p.data.price; if (!manualTrade.stock_name) manualTrade.stock_name = p.data.name } else manualQuote.value = null } catch { manualQuote.value = null }
}
const executeManualTrade = async () => { if (!manualTrade.ts_code) return; const sideText = manualTrade.side === 'buy' ? '买入' : '卖出'; const amount = (manualTrade.quantity || 0) * (manualTrade.price || 0); showConfirm(`确认${sideText}`, `${manualTrade.stock_name || manualTrade.ts_code}\n${sideText} ${manualTrade.quantity || 0}股 × ¥${(manualTrade.price || 0).toFixed(2)} ≈ ¥${amount.toFixed(0)}`, async () => { try { const r = await api.post(`${scannerApi}/trade`, { ts_code: manualTrade.ts_code, stock_name: manualTrade.stock_name, side: manualTrade.side, quantity: manualTrade.quantity || 0, price: manualTrade.price || 0, order_type: 'market', strategy: 'manual', reason: '手动操作' }); const p = parseResponse(r); if (p.success) { ElMessage.success(`${p.data.side === 'buy' ? '买入' : '卖出'} ${p.data.ts_code} ${p.data.filled_qty}股@${p.data.filled_price}`); manualTrade.ts_code = ''; manualTrade.stock_name = ''; manualTrade.quantity = 0; manualTrade.price = 0; fetchAll(true) } else ElMessage.error('下单失败') } catch (e: any) { ElMessage.error('下单失败') } }) }
const cumulativePnl = computed(() => { let total = 0; return timeline.value.filter(t => t.action === 'sell' && t.profit_amount != null).reduce((sum, t) => sum + (t.profit_amount || 0), 0) })
async function fetchScanner() { try { const r = await api.get(`${scannerApi}/all`); const p = parseResponse(r); if (p.success) { const d = p.data; if (d.signals && signals.value.length > 0 && d.signals.length > signals.value.length) { playSignalSound() } if (d.status) status.value = d.status; if (d.signals) signals.value = d.signals; if (d.positions) positions.value = d.positions; if (d.timeline) timeline.value = d.timeline; if (d.orders) orders.value = d.orders } fetchLimitPools(); updatePnlHistory() } catch (e) { console.error(e) } }
async function fetchScannerFull() { try { const [sR, sigR, posR, tlR, ordR] = await Promise.all([api.get(`${scannerApi}/status`), api.get(`${scannerApi}/signals`), api.get(`${scannerApi}/positions`), api.get(`${scannerApi}/timeline`), api.get(`${scannerApi}/orders`)]); const sP = parseResponse(sR), sigP = parseResponse(sigR), posP = parseResponse(posR), tlP = parseResponse(tlR), ordP = parseResponse(ordR); if (sP.success) status.value = sP.data; if (sigP.success) signals.value = sigP.data; if (posP.success) positions.value = posP.data; if (tlP.success) timeline.value = tlP.data; if (ordP.success) orders.value = ordP.data || [] } catch (e) { console.error(e) } }
async function startScanner() {
  const payload: Record<string, any> = { account_id: 'default', trade_mode: tradeMode.value }
  if (tradeMode.value === 'replay') {
    if (!replayDate.value) { ElMessage.warning('请先选择回放日期'); return }
    payload.replay_date = replayDate.value
  }
  loading.value = true
  try {
    await api.post(`${scannerApi}/start`, payload)
    ElMessage.success('扫描器已启动')
    activeTab.value = 'trading'
    await fetchScanner()
  } catch (e: any) {
    ElMessage.error('启动失败: ' + (e?.response?.data?.detail || e?.message || '超时'))
  } finally {
    loading.value = false
  }
}
async function stopScanner() { showConfirm('停止扫描', '确认停止扫描器？\n持仓将保留，可手动卖出。', async () => { await api.post(`${scannerApi}/stop`, { sell_all: false }); await fetchScanner() }) }
async function manualScan() { loading.value = true; try { const payload: Record<string, any> = {}; if (tradeMode.value === 'replay' && replayDate.value) payload.replay_date = replayDate.value; const r = await api.post(`${scannerApi}/scan-once`, payload); const p = parseResponse(r); if (p.success) { const m = p.data?.message; if (m) ElMessage.warning(m); else ElMessage.success(`扫描完成: ${p.data?.signals || 0}信号, ${p.data?.positions || 0}持仓`) } else ElMessage.error('扫描失败') } catch (e: any) { ElMessage.error('扫描失败') } finally { loading.value = false; await fetchScanner() } }
async function forceScan() { loading.value = true; try { const payload: Record<string, any> = { force: true }; if (tradeMode.value === 'replay' && replayDate.value) payload.replay_date = replayDate.value; const r = await api.post(`${scannerApi}/scan-once`, payload); const p = parseResponse(r); if (p.success) { ElMessage.success(`强制扫描完成: ${p.data?.signals || 0}信号, ${p.data?.positions || 0}持仓`) } else ElMessage.error('强制扫描失败') } catch (e: any) { ElMessage.error('强制扫描失败') } finally { loading.value = false; await fetchScanner() } }
const stratCollapsed = ref<Record<string, boolean>>({ halfway_chase: false, first_limit_up: false, dragon_head: false, limit_down_qiao: false, limit_up_open: false })
const stratSectionCollapsed = ref(false)
const qaSectionCollapsed = ref(false)
const timelineCollapsed = ref(true)
function toggleStrat(id: string) { stratCollapsed.value[id] = !stratCollapsed.value[id] }
async function dailySettlement() { try { const r = await api.post(`${scannerApi}/daily-settlement`); const p = parseResponse(r); if (p.success) { ElMessage.success(p.data?.message || '日结算完成'); await fetchScanner() } } catch (e: any) { ElMessage.error('日结算失败') } }
async function resetAccount() { showConfirm('⚠️ 重置账户', '将清空所有持仓和交易记录，不可恢复！\n确认重置？', async () => { try { const r = await api.post(`${scannerApi}/reset`); const p = parseResponse(r); if (p.success) { ElMessage.success('账户已重置'); await fetchAll(true) } } catch (e: any) { ElMessage.error('重置失败') } }) }
async function sellAllPositions() { showConfirm('⚠️ 一键清仓', `确认清仓所有持仓？\n当前持仓 ${positions.value.length} 只，总市值 ¥${positions.value.reduce((s, p) => s + (p.market_value || p.current_price * p.shares), 0).toFixed(0)}`, async () => { try { const r = await api.post(`${scannerApi}/sell-all`); const p = parseResponse(r); if (p.success) { ElMessage.success(p.data?.message || '清仓完成'); await fetchAll(true) } } catch (e: any) { ElMessage.error('清仓失败') } }) }
async function fetchWeeklyReport() { try { const r = await api.get(`${scannerApi}/weekly-report`); const p = parseResponse(r); if (p.success) return p.data } catch { return null } }
async function exportTradeLog() { try { const r = await api.get(`${scannerApi}/trade-log?format=csv&days=30`); if (r?.success && r.data) { const blob = new Blob([r.data], { type: 'text/csv;charset=utf-8' }); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = r.filename || 'trade_log.csv'; a.click(); URL.revokeObjectURL(url); ElMessage.success('导出成功') } } catch { ElMessage.error('导出失败') } }
async function saveSnapshot() { try { const r = await api.post(`${scannerApi}/snapshot`); const p = parseResponse(r); if (p.success) ElMessage.success('快照已保存') } catch { ElMessage.error('保存失败') } }
async function resetCircuitBreaker() { try { const r = await api.post(`${scannerApi}/circuit-breaker/reset`); const p = parseResponse(r); if (p.success) { ElMessage.success('熔断已重置'); fetchAll(true) } } catch { ElMessage.error('重置失败') } }
async function pauseCircuitBreaker() {
  try {
    await ElMessageBox.confirm('确认暂停交易？\n暂停后不会自动买入新信号，但持仓止损止盈仍正常执行。', '暂停交易', { confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning' })
    const r = await api.post(`${scannerApi}/circuit-breaker/pause`)
    const p = parseResponse(r); if (p.success) { ElMessage.success('已暂停'); fetchAll(true) } else ElMessage.error('操作失败')
  } catch { /* cancelled */ }
}
async function fetchLimitPools() { try { const r = await api.get(`${scannerApi}/limit-pools`); const p = parseResponse(r); if (p.success) limitPools.value = p.data } catch { } }
async function fetchDailyReport() { try { const r = await api.get(`${scannerApi}/daily-report`); const p = parseResponse(r); if (p.success) dailyReport.value = p.data } catch { } }
async function fetchDataSources() { try { const [sR, bR] = await Promise.all([api.get('/datasource/sources'), api.get('/datasource/brokers')]); const sP = parseResponse(sR), bP = parseResponse(bR); if (sP.success) dataSources.value = sP.data || []; if (bP.success) brokers.value = bP.data || [] } catch { } }
async function fetchHealth() { try { const r = await api.get(`${scannerApi}/health`); const p = parseResponse(r); if (p.success) { healthData.value = p.data; scannerStore.health = p.data; /* Phase4.1 */ } } catch { } }
async function emergencyLiquidate() { showConfirm('🚨 紧急平仓', '将立即以市价卖出所有持仓！\n此操作不可撤销！\n\n确认紧急平仓？', async () => { emergencyLiquidating.value = true; try { const r = await api.post(`${scannerApi}/emergency-liquidate`); const p = parseResponse(r); if (p.success) { ElMessage.success(p.data?.message || '紧急平仓完成'); await fetchAll(true) } else ElMessage.error('平仓失败') } catch { ElMessage.error('紧急平仓失败') } finally { emergencyLiquidating.value = false } }) }
async function fetchAll(force = false) { await Promise.all([fetchScanner(), fetchStrategies(), fetchHealth()]); fetchLimitPools(); fetchDataSources(); }
async function fetchStrategies() { try { const [sR, rR] = await Promise.all([api.get(`${configApi}/strategies`), api.get(`${configApi}/global-risk`)]); if (sR?.success) strategies.value = sR.data; if (rR?.success) globalRisk.value = rR.data } catch (e) { console.error(e) } }
async function toggleStrategy(sid: string, enabled: boolean) { try { await api.put(`${configApi}/strategies/${sid}`, { enabled }); await fetchStrategies(); ElMessage.success(enabled ? '已启用' : '已停用') } catch { ElMessage.error('操作失败') } }
function openEditDialog(strategy: StrategyConfig) { editingStrategy.value = strategy; editParams.value = { ...strategy.params }; editRiskParams.value = { ...strategy.riskParams }; editTab.value = 'params'; editDialogVisible.value = true }
async function saveStrategy() {
  if (!editingStrategy.value) return
  // 【P1-9】参数校验
  const strategy = editingStrategy.value
  const allDescs = [...(strategy.paramDescriptions || []), ...(strategy.riskDescriptions || [])]
  const allValues = { ...editParams.value, ...editRiskParams.value }
  for (const desc of allDescs) {
    const v = allValues[desc.key]
    if (v !== undefined && (v < desc.min || v > desc.max)) {
      ElMessage.warning(`${desc.label} 超出范围(${desc.min}~${desc.max}${desc.unit})，当前值: ${v}`)
      return
    }
  }
  saving.value = true
  try { await api.put(`${configApi}/strategies/${strategy.id}`, { params: editParams.value, riskParams: editRiskParams.value }); await fetchStrategies(); editDialogVisible.value = false; ElMessage.success('已保存') }
  catch { ElMessage.error('保存失败') }
  finally { saving.value = false }
}
async function resetStrategy(sid: string) { try { await api.post(`${configApi}/reset/${sid}`); await fetchStrategies(); ElMessage.success('已重置') } catch { ElMessage.error('重置失败') } }
// 全局错误边界：防止单个子组件崩溃导致整个页面白屏
onErrorCaptured((err, instance, info) => {
  console.error('[MonitorView] render error captured:', err, info)
  return false // 阻止错误继续向上传播，组件不会卸载
})

onMounted(async () => { try { await Promise.all([fetchScanner(), fetchStrategies(), fetchHealth()]) } catch(e) { console.error('[Mount] fetch error:', e) } try { fetchLimitPools(); fetchDataSources(); fetchPerformanceHistory(); connectWS() } catch(e) { console.error('[Mount] setup error:', e) } nowTimer = setInterval(() => { nowMs.value = Date.now() }, 1000); const getRefreshInterval = () => { const n = new Date(), h = n.getHours(), m = n.getMinutes(); const isTrading = (h === 9 && m >= 30) || (h >= 10 && h < 15) || (h === 15 && m === 0); return isTrading ? 5000 : 60000 }; refreshTimer = setInterval(() => { if (!autoRefresh.value || ws?.readyState === WebSocket.OPEN) return; fetchScanner(); fetchHealth() }, getRefreshInterval()) })
onUnmounted(() => { if (refreshTimer) clearInterval(refreshTimer); if (nowTimer) clearInterval(nowTimer); disconnectWS() })
function connectWS() {
  try {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
    ws = new WebSocket(`${proto}//${location.host}/ws`)
    let wsDebounceTimer: any = null
    const wsDebouncedFetch = () => { if (wsDebounceTimer) clearTimeout(wsDebounceTimer); wsDebounceTimer = setTimeout(fetchScanner, 500) }
    let lastSignalStreamId = ''
    let lastPositionStreamId = ''
    ws.onopen = () => { ws?.send(JSON.stringify({ type: 'subscribe_scanner' })); scannerStore.isWsConnected = true }
    ws.onmessage = (e) => {
      try {
        const d = JSON.parse(e.data)
        // 【v2.9.14】记录Stream ID(断线重连后补发用)
        if (d._stream_id) {
          if (d.type === 'scanner_signal') lastSignalStreamId = d._stream_id
          else if (d.type === 'scanner_position') lastPositionStreamId = d._stream_id
        }
        // 【Phase4.1:通过Scanner Store分发WS数据】
        if (d.type === 'scanner_signal') {
          scannerStore.updateFromWs('signal', { item: d.signals?.[0] || d.item })
          signals.value = d.signals?.length ? d.signals : signals.value
          wsDebouncedFetch()
        } else if (d.type === 'scanner_position') {
          scannerStore.updateFromWs('position', { positions: d.positions, account: d.account })
          positions.value = d.positions?.length ? d.positions : positions.value
        } else if (d.type === 'scanner_timeline') {
          scannerStore.updateFromWs('timeline', { item: d.item })
          if (d.item) timeline.value = [...timeline.value, d.item]
          wsDebouncedFetch()
        } else if (d.type === 'scanner_status') {
          scannerStore.updateFromWs('status', d.status || d)
          if (d.status) status.value = { ...status.value, ...d.status }
          // 【v2.9.15】异常事件弹窗提示
          if (d.event === 'scanner_error') {
            ElMessage({ type: 'error', message: `Scanner异常: ${d.error || '未知错误'}`, duration: 8000 })
          }
          wsDebouncedFetch()
        }
      } catch {}
    }
    ws.onclose = () => { scannerStore.isWsConnected = false; wsReconnectTimer = setTimeout(connectWS, 3000) } // Phase4.1: 3秒重连(设计文档规范)
    ws.onerror = () => { ws?.close() }
  } catch {}
}
function disconnectWS() { if (wsReconnectTimer) clearTimeout(wsReconnectTimer); if (ws) { ws.close(); ws = null; } }
const historyDate = ref('')
const historyData = ref<any[]>([])
const historyLoading = ref(false)
async function loadHistory() { if (!historyDate.value) { ElMessage.warning('请选择日期'); return } historyLoading.value = true; try { const d = historyDate.value.replace(/-/g, ''); const r = await api.get(`${scannerApi}/timeline/history?date=${d}`); const p = parseResponse(r); if (p.success) { historyData.value = p.data || []; if (!historyData.value.length) ElMessage.info('该日无交易记录') } } catch { ElMessage.error('加载失败') } finally { historyLoading.value = false } }
const compareData = ref<any[]>([])
const compareVisible = ref(false)
const compareLoading = ref(false)
const weeklyReportVisible = ref(false)
async function loadCompare() { compareLoading.value = true; try { const r = await api.get(`${scannerApi}/backtest-compare`); const p = parseResponse(r); if (p.success) { compareData.value = p.data || []; compareVisible.value = true } } catch { ElMessage.error('加载失败') } finally { compareLoading.value = false } }
async function openWeeklyReport() { try { const data = await fetchWeeklyReport(); if (data) { weeklyReportData.value = data; weeklyReportVisible.value = true } else ElMessage.warning('暂无周报数据') } catch { ElMessage.error('加载失败') } }
// 【调试增强】
const dryRun = computed(() => tradeMode.value === 'dry_run' || (status.value?.dry_run ?? false))
function onModeChange(mode: string) {
  if (mode === 'replay') {
    replayDateInput.value = ''
    replayDateVisible.value = true
    return
  }
  // 实盘模式切换需要输入确认码
  if (mode === 'gm') {
    ElMessageBox.prompt(
      '⚠️ 即将切换到实盘交易模式，真实资金将参与交易！\n\n请输入 LIVE 确认切换',
      '实盘模式确认',
      {
        confirmButtonText: '确认切换',
        cancelButtonText: '取消',
        inputPattern: /^LIVE$/,
        inputErrorMessage: '请输入 LIVE 确认',
        type: 'warning',
      }
    ).then(() => {
      ElMessage.success('已切换到实盘模式')
    }).catch(() => {
      // 用户取消，恢复原模式
      nextTick(() => { tradeMode.value = status.value?.trade_mode || 'simulated' })
    })
  }
}
async function confirmReplay() {
  if (!replayDateInput.value) { ElMessage.warning('请选择回放日期'); return }
  replayDate.value = replayDateInput.value.replace(/-/g, '')
  replayDateVisible.value = false
  ElMessage.success(`回放模式: ${replayDateInput.value}`)
}
function cancelReplay() {
  replayDateVisible.value = false
  tradeMode.value = 'simulated'
}
const layerDebugVisible = ref(false)
const layerDebugData = ref<any>(null)
const layerDebugLoading = ref(false)
const scanTraceVisible = ref(false)
const scanTraceData = ref<any>(null)
const scanTraceCode = ref('')
async function toggleDryRun() { try { const r = await api.post(`${scannerApi}/debug/dry-run`); const p = parseResponse(r); if (p.success) { ElMessage.success(p.data.mode); fetchScanner() } } catch { ElMessage.error('切换失败') } }
async function openLayerDebug() { layerDebugLoading.value = true; layerDebugVisible.value = true; try { const r = await api.get(`${scannerApi}/debug/layers`); const p = parseResponse(r); if (p.success) layerDebugData.value = p.data } catch { ElMessage.error('加载失败') } finally { layerDebugLoading.value = false } }
async function openScanTrace(ts_code: string) { scanTraceCode.value = ts_code; scanTraceVisible.value = true; try { const r = await api.get(`${scannerApi}/debug/scan-trace/${ts_code}`); const p = parseResponse(r); if (p.success) scanTraceData.value = p.data } catch { ElMessage.error('加载失败') } }
function formatLayerTrace(trace: Record<string, any>): string[] { if (!trace) return ['无链路数据']; const lines: string[] = []; for (const [layer, info] of Object.entries(trace)) { if (typeof info === 'object' && info !== null) { const applied = info.applied !== undefined ? (info.applied ? '✅' : '⏭️') : ''; const detail = info.detail || info.reason || ''; lines.push(`${applied} ${layerLabel(layer)}: ${detail}`) } else { lines.push(`${layerLabel(layer)}: ${info}`) } } return lines }
function signalStatusTag(status?: string) { if (!status || status === 'new') return { text: '新', type: 'primary' }; if (status === 'executed') return { text: '已买', type: 'success' }; if (status === 'skipped') return { text: '跳过', type: 'warning' }; if (status === 'expired') return { text: '过期', type: 'info' }; if (status === 'filtered') return { text: '过滤', type: 'danger' }; return { text: status, type: 'info' } }
</script>
<template>
  <div class="mm" :class="{ dark: themeStore.isDark }">
    <!-- 顶部状态栏(一行: 风控+状态+资产+操作) -->
    <div class="mm-header">
      <div class="hh-left">
        <div class="hh-status" :class="{ running: isRunning, stopped: !isRunning }"><span class="dot"></span><span>{{ isRunning ? '扫描中' : '已停止' }}</span></div>
        <ElSelect v-model="tradeMode" size="small" style="width:96px" @change="onModeChange">
          <ElOption v-for="(m, key) in modeMeta" :key="key" :value="key" :label="m.emoji + ' ' + m.text" />
        </ElSelect>
        <ElTag v-if="tradeMode === 'replay' && replayDate" type="warning" size="small">🔄 {{ replayDateInput }}</ElTag>
        <ElTag v-if="circuitBreakerPaused" type="danger" size="small">⚠️熔断</ElTag>
        <div v-if="status?.data_sources?.length" class="ds-indicator">
          <span v-for="ds in (status?.data_sources || [])" :key="ds.name" class="ds-dot" :class="{ ok: ds.available, err: !ds.available }">{{ ds.name === 'eastmoney' ? '东财' : ds.name === 'biying' ? '必盈' : ds.name }}</span>
        </div>
      </div>
      <div class="hh-account" v-if="status">
        <span class="ha">资产<span class="hv">{{ (accountInfo.total_assets / 10000).toFixed(1) }}万</span></span>
        <span class="ha">可用<span class="hv">{{ (accountInfo.available_cash / 10000).toFixed(1) }}万</span></span>
        <span class="ha">仓位<span class="hv">{{ positionRatio }}%</span></span>
        <span class="ha">盈亏<span class="hv" :class="totalPnl >= 0 ? 'up' : 'down'">{{ totalPnl >= 0 ? '+' : '' }}{{ totalPnl.toFixed(0) }}</span></span>
      </div>
      <div class="hh-actions">
        <ElButton v-if="!isRunning" type="success" size="small" @click="startScanner">▶ 启动</ElButton>
        <ElButton v-else type="danger" size="small" @click="stopScanner">⏹ 停止</ElButton>
        <ElButton size="small" :loading="loading" @click="manualScan" :disabled="!isRunning">📡 扫描</ElButton>
        <button class="emergency-btn-inline" :class="{ disabled: !isRunning || emergencyLiquidating }" @click="isRunning && !emergencyLiquidating && emergencyLiquidate()" :disabled="!isRunning || emergencyLiquidating" title="紧急平仓">🚨</button>
        <ElSwitch v-model="autoRefresh" size="small" active-text="自动" inactive-text="" />
        <span class="dark-toggle" @click="themeStore.toggleTheme()">{{ themeStore.isDark ? '☀️' : '🌙' }}</span>
      </div>
    </div>

    <!-- Tab 导航栏 -->
    <div class="mm-tab-bar">
      <button :class="['tab-btn', activeTab === 'guide' ? 'active' : '']" @click="activeTab = 'guide'">
        <span class="tab-icon">📖</span>
        <span class="tab-text"><span class="tab-label">指南</span><span class="tab-desc">架构·策略·操作</span></span>
      </button>
      <button :class="['tab-btn', activeTab === 'trading' ? 'active' : '']" @click="activeTab = 'trading'">
        <span class="tab-icon">🎯</span>
        <span class="tab-text"><span class="tab-label">实盘</span><span class="tab-desc">信号·持仓·交易</span></span>
        <span v-if="filteredSignals.length" class="tab-badge">{{ filteredSignals.length }}</span>
      </button>
      <button :class="['tab-btn', activeTab === 'premarket' ? 'active' : '']" @click="activeTab = 'premarket'">
        <span class="tab-icon">🌅</span>
        <span class="tab-text"><span class="tab-label">盘前竞价</span><span class="tab-desc">9:00-9:25</span></span>
        <span v-if="premarketSignals.length" class="tab-badge">{{ premarketSignals.length }}</span>
      </button>
      <button :class="['tab-btn', activeTab === 'scan-trace' ? 'active' : '']" @click="activeTab = 'scan-trace'">
        <span class="tab-icon">🔍</span>
        <span class="tab-text"><span class="tab-label">扫描追踪</span><span class="tab-desc">9层漏斗·执行链</span></span>
      </button>
      <button :class="['tab-btn', activeTab === 'review' ? 'active' : '']" @click="activeTab = 'review'">
        <span class="tab-icon">📋</span>
        <span class="tab-text"><span class="tab-label">复盘</span><span class="tab-desc">日/周·归因·对比</span></span>
      </button>
      <button :class="['tab-btn', activeTab === 'risk' ? 'active' : '']" @click="activeTab = 'risk'">
        <span class="tab-icon">🛡️</span>
        <span class="tab-text"><span class="tab-label">风控</span><span class="tab-desc">止损·矩阵</span></span>
        <span v-if="positions.some(p => p.risk_level === 'high')" class="tab-badge-danger">!</span>
      </button>
      <button :class="['tab-btn', activeTab === 'history' ? 'active' : '']" @click="activeTab = 'history'">
        <span class="tab-icon">📜</span>
        <span class="tab-text"><span class="tab-label">历史</span><span class="tab-desc">时间线·订单</span></span>
      </button>
      <button :class="['tab-btn', activeTab === 'ops' ? 'active' : '']" @click="activeTab = 'ops'">
        <span class="tab-icon">⚙️</span>
        <span class="tab-text"><span class="tab-label">运维</span><span class="tab-desc">系统·操作</span></span>
      </button>
    </div>

    <!-- 📖 指南Tab -->
    <div v-if="activeTab === 'guide'" class="mm-guide">
      <!-- 顶部横幅 -->
      <div class="guide-banner">
        <div class="gb-left">
          <div class="gb-logo">📡</div>
          <div>
            <div class="gb-title">超短量化实盘监控系统</div>
            <div class="gb-sub">9层漏斗筛选 · 4策略联合选股 · 实时风控守护</div>
          </div>
        </div>
        <ElButton type="success" size="large" @click="startScanner" style="padding:10px 32px;font-size:15px">▶ 启动扫描器</ElButton>
      </div>

      <!-- 4列卡片网格 -->
      <div class="guide-grid">
        <!-- 系统架构 -->
        <div class="gg-card gg-span2">
          <div class="gg-head"><span class="gg-icon">🏗️</span>系统架构</div>
          <div class="gg-body">
            <div class="gf-flow">
              <span class="gf-tag gf-input">5000+股票</span>
              <span class="gf-arrow">→</span>
              <span class="gf-tag">L1~L3 基础过滤</span>
              <span class="gf-arrow">→</span>
              <span class="gf-tag">L4~L6 策略筛选</span>
              <span class="gf-arrow">→</span>
              <span class="gf-tag">L7~L9 排序仓位</span>
              <span class="gf-arrow">→</span>
              <span class="gf-tag gf-output">买入信号</span>
            </div>
          </div>
        </div>

        <!-- 操作指南 -->
        <div class="gg-card gg-span2">
          <div class="gg-head"><span class="gg-icon">📖</span>操作指南</div>
          <div class="gg-body">
            <div class="go-list">
              <div class="go-row"><span class="sn">1</span>▶ 启动 → 每5分钟自动扫描，30秒检查持仓</div>
              <div class="go-row"><span class="sn">2</span>📡 扫描 → 立即触发选股，⚡ 强扫跳缓存</div>
              <div class="go-row"><span class="sn">3</span>🎛️ 策略 → 左侧面板开关策略、调参数</div>
              <div class="go-row"><span class="sn">4</span>🟢 买入 → 信号区候选一键下单</div>
              <div class="go-row"><span class="sn">5</span>🔴 卖出 → 持仓卡片快捷平仓或自动止盈止损</div>
              <div class="go-row"><span class="sn">6</span>📋 复盘 / ⚙️ 运维 → 归因分析+系统健康</div>
            </div>
          </div>
        </div>

        <!-- 半路追涨 -->
        <div class="gg-card">
          <div class="gg-head"><span class="gg-icon">🏃</span>半路追涨</div>
          <div class="gg-body gg-compact">
            <div class="gg-line">盘中涨幅3-5% + 量能放大</div>
            <div class="gg-params">
              <span class="gg-p"><span class="gg-pl">SL</span>3%</span>
              <span class="gg-p"><span class="gg-pl">TP</span>12%</span>
              <span class="gg-p"><span class="gg-pl">持仓</span>3天</span>
            </div>
          </div>
        </div>

        <!-- 首板打板 -->
        <div class="gg-card">
          <div class="gg-head"><span class="gg-icon">🥇</span>首板打板</div>
          <div class="gg-body gg-compact">
            <div class="gg-line">首次涨停封板 + 成交概率</div>
            <div class="gg-params">
              <span class="gg-p"><span class="gg-pl">SL</span>3%</span>
              <span class="gg-p"><span class="gg-pl">TP</span>10%</span>
              <span class="gg-p"><span class="gg-pl">持仓</span>2天</span>
            </div>
          </div>
        </div>

        <!-- 龙头低吸 -->
        <div class="gg-card">
          <div class="gg-head"><span class="gg-icon">🐲</span>龙头低吸</div>
          <div class="gg-body gg-compact">
            <div class="gg-line">连板龙头回调 + MA支撑</div>
            <div class="gg-params">
              <span class="gg-p"><span class="gg-pl">SL</span>3.5%</span>
              <span class="gg-p"><span class="gg-pl">TP</span>30%</span>
              <span class="gg-p"><span class="gg-pl">持仓</span>7天</span>
            </div>
          </div>
        </div>

        <!-- 跌停翘板 -->
        <div class="gg-card">
          <div class="gg-head"><span class="gg-icon">💥</span>跌停翘板</div>
          <div class="gg-body gg-compact">
            <div class="gg-line">连续跌停翘板反转</div>
            <div class="gg-params">
              <span class="gg-p"><span class="gg-pl">SL</span>5%</span>
              <span class="gg-p"><span class="gg-pl">TP</span>20%</span>
              <span class="gg-p"><span class="gg-pl">持仓</span>3天</span>
            </div>
          </div>
        </div>

        <!-- 风控体系 -->
        <div class="gg-card gg-span2">
          <div class="gg-head"><span class="gg-icon">🛡️</span>风控体系</div>
          <div class="gg-body">
            <div class="gr-grid">
              <div class="gr-row"><span class="gr-k">强制空仓</span><span class="gr-v">跌停≥80只 / 大盘跌≥3%</span></div>
              <div class="gr-row"><span class="gr-k">情绪仓位</span><span class="gr-v">高潮100% / 分化70% / 震荡50% / 冰点30%</span></div>
              <div class="gr-row"><span class="gr-k">单票上限</span><span class="gr-v">35% · 总仓位上限75%</span></div>
              <div class="gr-row"><span class="gr-k">盘中锁定</span><span class="gr-v">冲高≥6% 回撤≥2.5% → 利润保护</span></div>
              <div class="gr-row"><span class="gr-k">智能检查</span><span class="gr-v">盈利5s / 亏损3s / 接近止损1s</span></div>
              <div class="gr-row"><span class="gr-k">信号过期</span><span class="gr-v">5分钟未执行自动取消</span></div>
            </div>
          </div>
        </div>

        <!-- 快捷键 -->
        <div class="gg-card gg-span2">
          <div class="gg-head"><span class="gg-icon">⌨️</span>快捷键</div>
          <div class="gg-body">
            <div class="gk-row">
              <span class="gk-g"><kbd>F5</kbd>强扫</span>
              <span class="gk-g"><kbd>F9</kbd>买入</span>
              <span class="gk-g"><kbd>Ctrl+S</kbd>卖出</span>
              <span class="gk-g"><kbd>Ctrl+E</kbd>紧急平仓</span>
              <span class="gk-g"><kbd>↑↓</kbd>切换持仓</span>
              <span class="gk-g"><kbd>Enter</kbd>详情</span>
              <span class="gk-g"><kbd>1-4</kbd>策略开关</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 3列主布局 -->
    <div v-if="activeTab === 'trading'" class="mm-body">
      <!-- 左列: 策略控制 -->
      <div class="mm-left">
        <div class="st cp" @click="stratSectionCollapsed = !stratSectionCollapsed">🎛️ 策略控制 <span class="sc-arrow">{{ stratSectionCollapsed ? '▶' : '▼' }}</span></div>
        <template v-if="!stratSectionCollapsed">
        <div v-for="s in strategies" :key="s.id" class="sc" :class="{ disabled: !s.enabled }">
          <div class="sc-top cp" @click="toggleStrat(s.id)"><span class="sc-icon">{{ strategyMeta[s.id]?.icon || '📋' }}</span><span class="sc-name">{{ s.name }}</span><ElSwitch :model-value="s.enabled" @change="(v: boolean) => toggleStrategy(s.id, v)" size="small" @click.stop /><span class="sc-arrow">{{ stratCollapsed[s.id] ? '▶' : '▼' }}</span></div>
          <div v-if="!stratCollapsed[s.id]">
            <div class="sc-desc">{{ strategyMeta[s.id]?.desc || '' }}</div>
            <div class="sc-params"><div v-for="p in (s.paramDescriptions || []).slice(0, 3)" :key="p.key" class="pm"><span class="pk">{{ p.label }}</span><span class="pv">{{ p.displayValue }}{{ p.unit }}</span></div></div>
            <ElButton size="small" text type="primary" @click="openEditDialog(s)">⚙️ 编辑</ElButton>
          </div>
        </div>
        </template>
        <div class="st mt-10" style="font-size:11px;color:var(--text-tertiary)">更多操作见 <span class="cp" style="color:var(--el-color-primary)" @click="activeTab='ops'">⚙️ 运维Tab</span></div>

      </div>

      <!-- 中列: 信号+行情 -->
      <div class="mm-center">
        <div class="st">🎯 活跃信号 <div style="display:inline-flex;gap:2px;margin-left:6px"><ElTag v-for="f in [{k:'all',l:'全部'},{k:'halfway_chase',l:'半路'},{k:'first_limit_up',l:'首板'},{k:'limit_down_qiao',l:'跌停'},{k:'anomaly',l:'异动'}]" :key="f.k" size="small" :type="signalFilter===f.k?'primary':'info'" class="cp" @click="signalFilter=f.k">{{ f.l }}</ElTag></div> <ElBadge :value="filteredSignals.length" :max="99" style="margin-left:4px" /></div>
        <div class="sl">
          <div v-if="!signals.length" class="empty">启动后扫描获取信号</div>
          <div v-for="sig in filteredSignals" :key="sig.ts_code + sig.strategy" class="sig-row" :title="`${sig.ts_code} ${sig.stock_name}\n策略: ${sig.strategy_name}\n量比: ${sig.volume_ratio?.toFixed(1) || '-'}\n换手: ${sig.turnover_rate?.toFixed(1) || '-'}%\n${sig.reason}`">
            <ElTag size="small" :color="strategyMeta[sig.strategy]?.color || 'var(--text-tertiary)'" class="tag-solid" style="min-width:52px;text-align:center">{{ sig.strategy_name }}</ElTag><ElTag v-if="sig.signal_status === 'executed'" size="small" type="success">已买</ElTag><ElTag v-if="sig.signal_status === 'skipped'" size="small" type="warning">跳过</ElTag><ElTag v-if="sig.signal_status === 'expired'" size="small" type="info">过期</ElTag><span class="code">{{ sig.ts_code }}</span><span class="name">{{ sig.stock_name }}</span><span v-if="sig.signal_status === 'new' && sigRemaining(sig) >= 0" class="expire-tag" :class="{ urgent: sigRemaining(sig) < 60000 }">⏱{{ formatRemaining(sigRemaining(sig)) }}</span><span :class="sig.pct_chg >= 0 ? 'up' : 'down'" class="pct ml-auto" style="font-weight:600">{{ sig.pct_chg >= 0 ? '+' : '' }}{{ sig.pct_chg.toFixed(1) }}%</span><ElButton v-if="!dryRun && sig.signal_status === 'new'" size="small" type="danger" plain @click="quickBuy(sig)" class="btn-xs">买</ElButton><ElButton v-if="sig.decision_detail" size="small" type="info" plain @click="openTradeDetail(sig.ts_code)" class="btn-xs">🔍</ElButton><ElButton v-if="sig.layer_trace" size="small" type="warning" plain @click="openScanTrace(sig.ts_code)" class="btn-xs">🧪</ElButton>
          </div>
        </div>

      </div>

      <!-- 右列: 持仓 -->
      <div class="mm-right">
        <div class="st">📊 持仓监控 <ElBadge :value="positions.length" :max="99" style="margin-left:4px" /><ElSelect v-model="posSort" size="small" style="width:80px;margin-left:auto"><ElOption label="盈亏" value="profit" /><ElOption label="市值" value="cost" /><ElOption label="策略" value="strategy" /><ElOption label="时间" value="time" /></ElSelect></div>
        <div class="sl">
          <div v-if="!positions.length" class="empty">暂无持仓</div>
          <div v-for="(pos, idx) in sortedPositions" :key="pos.ts_code" class="pos-card" :class="{ 'pos-focused': idx === focusIndex }">
            <div class="pos-top"><ElTag size="small" :color="strategyMeta[pos.strategy]?.color || 'var(--text-tertiary)'" class="tag-solid" style="font-size:10px;min-width:48px;text-align:center">{{ pos.strategy_name || strategyCN(pos.strategy) }}</ElTag><span class="code">{{ pos.ts_code }}</span><span class="name">{{ pos.stock_name }}</span><MiniKline :tsCode="pos.ts_code" :compact="true" :days="5" /><span :class="pos.profit_pct >= 0 ? 'up' : 'down'" class="pct">{{ pos.profit_pct >= 0 ? '+' : '' }}{{ pos.profit_pct.toFixed(1) }}%</span><span class="mini-bar"><span class="mini-bar-fill" :style="{ width: Math.min(Math.abs(pos.profit_pct) / 10 * 100, 100) + '%' }" :class="pos.profit_pct >= 0 ? 'bar-up' : 'bar-down'"></span></span><span v-if="pos.today_buy > 0" class="t1-tag">T+1</span><ElButton size="small" type="danger" plain @click="quickSell(pos)" :disabled="pos.available_qty <= 0" class="btn-xs ml-auto">卖出</ElButton><ElButton size="small" type="info" plain @click="openTradeDetail(pos.ts_code)" class="btn-xs">详情</ElButton></div>
            <div class="pos-info"><span>{{ pos.shares }}股</span><span>成本¥{{ pos.cost_price.toFixed(2) }}</span><span>现价¥{{ pos.current_price.toFixed(2) }}</span><span v-if="pos.market_value" class="mv">市值{{ (pos.market_value / 10000).toFixed(1) }}万</span><span v-if="pos.profit_amount != null" :class="pos.profit_amount >= 0 ? 'up' : 'down'" class="pamt">{{ pos.profit_amount >= 0 ? '+' : '' }}¥{{ Math.abs(pos.profit_amount).toFixed(0) }}</span></div>
            <div class="pos-prices-row">
              <span v-if="pos.stop_loss_price" class="pp-sl">止损¥{{ pos.stop_loss_price.toFixed(2) }}</span>
              <span v-if="pos.take_profit_price" class="pp-tp">止盈¥{{ pos.take_profit_price.toFixed(2) }}</span>
              <span v-if="pos.trailing_stop?.activated" class="pp-trail">📍追踪¥{{ pos.trailing_stop.stop_price?.toFixed(2) }}({{ (pos.trailing_stop.trailing_stop_pct * 100).toFixed(0) }}%)</span>
              <span v-if="pos.risk_level && pos.risk_level !== 'normal'" class="pp-risk" :class="pos.risk_level">{{ {high:'🔴高风险',elevated:'🟡较高',low:'🟢低风险'}[pos.risk_level] || pos.risk_level }}</span>
            </div>
            <div v-if="pos.stop_loss_pct != null" class="pos-risk-row">
              <div class="risk-track"><div class="risk-fill" :style="{ width: Math.max(0, Math.min(100, (pos.profit_pct + normalizePct(pos.stop_loss_pct, 3)) / (normalizePct(pos.stop_loss_pct, 3) + normalizePct(pos.take_profit_pct, 7)) * 100)) + '%' }" :class="pos.profit_pct + normalizePct(pos.stop_loss_pct, 3) < 1 ? 'danger' : pos.profit_pct + normalizePct(pos.stop_loss_pct, 3) < 2 ? 'warning' : 'safe'"></div></div>
              <div class="risk-labels-row"><span class="rl stop">止损{{ formatSlTp(pos.stop_loss_pct, 3) }}</span><span v-if="pos.trailing_stop?.activated" class="rl trail">📍{{ (pos.trailing_stop.trailing_stop_pct * 100).toFixed(0) }}%</span><span class="rd" :class="{ danger: pos.profit_pct + normalizePct(pos.stop_loss_pct, 3) < 2 }">距止损{{ (pos.profit_pct + normalizePct(pos.stop_loss_pct, 3)).toFixed(1) }}%</span><span class="rl profit">止盈{{ formatSlTp(pos.take_profit_pct, 7) }}</span></div>
            </div>
          </div>
        </div>

        <!-- 盈亏曲线 → 已移至绩效Tab -->

      </div>
    </div>


    <!-- 策略编辑弹窗 -->
    <ElDialog v-model="editDialogVisible" :title="`编辑 ${editingStrategy?.name}`" width="560px" :close-on-click-modal="false">
      <ElTabs v-model="editTab">
        <ElTabPane label="选股参数" name="params"><div v-for="p in editingStrategy?.paramDescriptions || []" :key="p.key" style="margin-bottom:12px"><div style="font-size:13px;margin-bottom:4px">{{ p.label }} <span class="text-tertiary">({{ p.min }}~{{ p.max }}{{ p.unit }})</span></div><ElInputNumber v-model="editParams[p.key]" :min="p.min" :max="p.max" :step="p.step" :precision="p.step < 1 ? 2 : 1" size="small" controls-position="right" style="width:160px" /></div></ElTabPane>
        <ElTabPane label="风控参数" name="risk"><div v-for="p in editingStrategy?.riskDescriptions || []" :key="p.key" style="margin-bottom:12px"><div style="font-size:13px;margin-bottom:4px">{{ p.label }} <span class="text-tertiary">({{ p.min }}~{{ p.max }}{{ p.unit }})</span></div><ElInputNumber v-model="editRiskParams[p.key]" :min="p.min" :max="p.max" :step="p.step" :precision="p.step < 1 ? 2 : 1" size="small" controls-position="right" style="width:160px" /></div></ElTabPane>
      </ElTabs>
      <template #footer><ElButton @click="editDialogVisible = false">取消</ElButton><ElButton type="primary" :loading="saving" @click="saveStrategy">保存</ElButton></template>
    </ElDialog>

    <!-- 交易详情弹窗 — 结构化卡片 -->
    <ElDialog v-model="tradeDetailVisible" :title="`🔍 交易审查 — ${tradeDetailData?.ts_code || ''} ${tradeDetailData?.stock_name || tradeDetailData?.buy?.stock_name || tradeDetailData?.sell?.stock_name || ''}`" width="780px">
      <div v-if="tradeDetailData" class="td2">
        <!-- 买入决策 -->
        <div class="td2-sec"><div class="td2-title">📥 买入决策</div>
          <template v-if="tradeDetailData.buy">
            <div class="td2-grid">
              <div class="td2-card"><div class="td2-label">⏰ 时间</div><div class="td2-val">{{ tradeDetailData.buy.time }}</div></div>
              <div class="td2-card"><div class="td2-label">💰 价格</div><div class="td2-val">¥{{ tradeDetailData.buy.price?.toFixed(2) }}</div></div>
              <div class="td2-card"><div class="td2-label">📊 数量</div><div class="td2-val">{{ tradeDetailData.buy.shares }}股</div></div>
              <div class="td2-card"><div class="td2-label">🎯 策略</div><div class="td2-val"><ElTag size="small" :color="strategyMeta[tradeDetailData.buy.strategy]?.color || 'var(--text-tertiary)'" class="tag-solid">{{ strategyCN(tradeDetailData.buy.strategy) }}</ElTag></div></div>
            </div>
            <div class="td2-reason">📋 选股原因: {{ tradeDetailData.buy.reason }}</div>
            <template v-if="tradeDetailData.buy.decision_detail">
              <div class="td2-chain">
                <template v-if="tradeDetailData.buy.decision_detail.filter_pipeline">
                  <div class="td2-chain-title">🔍 9层筛选管道</div>
                  <div class="td2-pipeline">
                    <div v-for="(applied, layer) in tradeDetailData.buy.decision_detail.filter_pipeline.layers_applied || {}" :key="layer" class="td2-pipe-step" :class="{ passed: applied }">
                      <span class="td2-pipe-icon">{{ applied ? '✅' : '⏭️' }}</span>
                      <span class="td2-pipe-name">{{ layerLabel(layer) }}</span>
                      <span class="td2-pipe-detail">{{ tradeDetailData.buy.decision_detail.filter_pipeline.layer_details?.[layer] || (applied ? '通过' : '跳过') }}</span>
                    </div>
                  </div>
                </template>
                <template v-if="tradeDetailData.buy.decision_detail.execution">
                  <div class="td2-chain-title">⚡ 执行决策</div>
                  <div class="td2-grid">
                    <div class="td2-card sm"><div class="td2-label">仓位比例</div><div class="td2-val">{{ ((tradeDetailData.buy.decision_detail.execution.position_ratio || 0) * 100).toFixed(0) }}%</div></div>
                    <div class="td2-card sm"><div class="td2-label">可用资金</div><div class="td2-val">¥{{ (tradeDetailData.buy.decision_detail.execution.available_cash || 0).toFixed(0) }}</div></div>
                    <div class="td2-card sm"><div class="td2-label">买入金额</div><div class="td2-val">¥{{ (tradeDetailData.buy.decision_detail.execution.total_cost || 0).toFixed(0) }}</div></div>
                    <div class="td2-card sm"><div class="td2-label">成交价</div><div class="td2-val">¥{{ (tradeDetailData.buy.decision_detail.execution.filled_price || 0).toFixed(2) }}</div></div>
                    <div class="td2-card sm" v-if="tradeDetailData.buy.decision_detail.execution.sentiment"><div class="td2-label">情绪</div><div class="td2-val">{{ tradeDetailData.buy.decision_detail.execution.sentiment.score?.toFixed(0) }}→{{ tradeDetailData.buy.decision_detail.execution.sentiment.period }}</div></div>
                    <div class="td2-card sm" v-if="tradeDetailData.buy.decision_detail.execution.circuit_breaker"><div class="td2-label">熔断</div><div class="td2-val" :class="tradeDetailData.buy.decision_detail.execution.circuit_breaker.paused ? 'down' : ''">{{ tradeDetailData.buy.decision_detail.execution.circuit_breaker.paused ? '⛔暂停' : '✅正常' }}</div></div>
                  </div>
                </template>
                <template v-if="tradeDetailData.buy.decision_detail.factors && Object.values(tradeDetailData.buy.decision_detail.factors).some(v => v !== 0 && v !== null)">
                  <div class="td2-chain-title">📈 关键因子</div>
                  <div class="td2-factors">
                    <div v-for="(v, k) in tradeDetailData.buy.decision_detail.factors" :key="k" v-show="v !== 0 && v !== null" class="td2-factor"><span class="td2-fk">{{ factorLabel(k) }}</span><span class="td2-fv">{{ typeof v === 'number' ? v.toFixed(2) : v }}</span></div>
                  </div>
                </template>
              </div>
            </template>
          </template>
          <div v-else class="td2-empty">暂无买入记录</div>
        </div>
        <!-- 卖出决策 -->
        <div class="td2-sec"><div class="td2-title">📤 卖出决策</div>
          <template v-if="tradeDetailData.sell">
            <div class="td2-grid">
              <div class="td2-card"><div class="td2-label">⏰ 时间</div><div class="td2-val">{{ tradeDetailData.sell.time }}</div></div>
              <div class="td2-card"><div class="td2-label">💰 价格</div><div class="td2-val">¥{{ tradeDetailData.sell.price?.toFixed(2) }}</div></div>
              <div class="td2-card"><div class="td2-label">📊 盈亏</div><div class="td2-val" :class="tradeDetailData.sell.profit_pct >= 0 ? 'up' : 'down'">{{ tradeDetailData.sell.profit_pct >= 0 ? '+' : '' }}{{ tradeDetailData.sell.profit_pct?.toFixed(2) }}%</div></div>
              <div class="td2-card"><div class="td2-label">💵 盈亏额</div><div class="td2-val" :class="(tradeDetailData.sell.profit_amount || 0) >= 0 ? 'up' : 'down'">¥{{ (tradeDetailData.sell.profit_amount || 0).toFixed(0) }}</div></div>
            </div>
            <div class="td2-reason">📋 卖出原因: {{ tradeDetailData.sell.reason }}</div>
            <template v-if="tradeDetailData.sell.decision_detail">
              <div class="td2-chain">
                <div class="td2-grid">
                  <div class="td2-card sm" v-if="tradeDetailData.sell.decision_detail.cost_price"><div class="td2-label">成本价</div><div class="td2-val">¥{{ tradeDetailData.sell.decision_detail.cost_price?.toFixed(2) }}</div></div>
                  <div class="td2-card sm" v-if="tradeDetailData.sell.decision_detail.current_price"><div class="td2-label">卖出价</div><div class="td2-val">¥{{ tradeDetailData.sell.decision_detail.current_price?.toFixed(2) }}</div></div>
                  <div class="td2-card sm" v-if="tradeDetailData.sell.decision_detail.stop_loss_pct"><div class="td2-label">止损线</div><div class="td2-val text-stock-up">{{ tradeDetailData.sell.decision_detail.stop_loss_pct }}%</div></div>
                  <div class="td2-card sm" v-if="tradeDetailData.sell.decision_detail.take_profit_pct"><div class="td2-label">止盈线</div><div class="td2-val text-stock-down">{{ tradeDetailData.sell.decision_detail.take_profit_pct }}%</div></div>
                  <div class="td2-card sm" v-if="tradeDetailData.sell.decision_detail.stop_loss_price"><div class="td2-label">止损价</div><div class="td2-val text-stock-up">¥{{ tradeDetailData.sell.decision_detail.stop_loss_price?.toFixed(2) }}</div></div>
                  <div class="td2-card sm" v-if="tradeDetailData.sell.decision_detail.take_profit_price"><div class="td2-label">止盈价</div><div class="td2-val text-stock-down">¥{{ tradeDetailData.sell.decision_detail.take_profit_price?.toFixed(2) }}</div></div>
                </div>
              </div>
            </template>
          </template>
          <div v-else class="td2-empty">暂无卖出记录</div>
        </div>
        <!-- 当前持仓 -->
        <div class="td2-sec" v-if="tradeDetailData.position"><div class="td2-title">📊 当前持仓</div>
          <div class="td2-grid">
            <div class="td2-card"><div class="td2-label">持仓</div><div class="td2-val">{{ tradeDetailData.position.shares }}股</div></div>
            <div class="td2-card"><div class="td2-label">成本</div><div class="td2-val">¥{{ tradeDetailData.position.cost_price?.toFixed(2) }}</div></div>
            <div class="td2-card"><div class="td2-label">现价</div><div class="td2-val">¥{{ tradeDetailData.position.current_price?.toFixed(2) }}</div></div>
            <div class="td2-card"><div class="td2-label">盈亏</div><div class="td2-val" :class="tradeDetailData.position.profit_pct >= 0 ? 'up' : 'down'">{{ tradeDetailData.position.profit_pct >= 0 ? '+' : '' }}{{ tradeDetailData.position.profit_pct?.toFixed(2) }}%</div></div>
            <div class="td2-card" v-if="tradeDetailData.position.stop_loss_pct"><div class="td2-label">止损</div><div class="td2-val text-stock-up">{{ formatSlTp(tradeDetailData.position.stop_loss_pct, 3) }}</div></div>
            <div class="td2-card" v-if="tradeDetailData.position.take_profit_pct"><div class="td2-label">止盈</div><div class="td2-val text-stock-down">{{ formatSlTp(tradeDetailData.position.take_profit_pct, 7) }}</div></div>
            <div class="td2-card" v-if="tradeDetailData.position.stop_loss_price"><div class="td2-label">止损价</div><div class="td2-val text-stock-up">¥{{ tradeDetailData.position.stop_loss_price?.toFixed(2) }}</div></div>
            <div class="td2-card" v-if="tradeDetailData.position.take_profit_price"><div class="td2-label">止盈价</div><div class="td2-val text-stock-down">¥{{ tradeDetailData.position.take_profit_price?.toFixed(2) }}</div></div>
          </div>
          <!-- 追踪止损 -->
          <div v-if="tradeDetailData.position.trailing_stop" class="td2-trail-section">
            <div class="td2-chain-title">📍 追踪止损</div>
            <div class="td2-grid">
              <div class="td2-card sm"><div class="td2-label">状态</div><div class="td2-val" :class="tradeDetailData.position.trailing_stop.activated ? 'up' : ''">{{ tradeDetailData.position.trailing_stop.activated ? '✅已激活' : '⏸未激活' }}</div></div>
              <div class="td2-card sm"><div class="td2-label">比例</div><div class="td2-val">{{ (tradeDetailData.position.trailing_stop.trailing_stop_pct * 100).toFixed(1) }}%</div></div>
              <div class="td2-card sm"><div class="td2-label">最高价</div><div class="td2-val">¥{{ tradeDetailData.position.trailing_stop.high_price?.toFixed(2) }}</div></div>
              <div class="td2-card sm"><div class="td2-label">止损价</div><div class="td2-val text-stock-up">¥{{ tradeDetailData.position.trailing_stop.stop_price?.toFixed(2) }}</div></div>
            </div>
            <div class="td2-trail-ctrl">
              <ElInputNumber v-model="trailEditPct" :min="1" :max="20" :step="0.5" :precision="1" size="small" style="width:110px" />
              <span style="font-size:12px;color:var(--text-tertiary)">%回撤</span>
              <ElButton size="small" type="primary" @click="setTrailingStop(tradeDetailData.ts_code, true)" :loading="trailSaving">激活</ElButton>
              <ElButton v-if="tradeDetailData.position.trailing_stop.activated" size="small" @click="setTrailingStop(tradeDetailData.ts_code, false)" :loading="trailSaving">停用</ElButton>
            </div>
          </div>
          <div v-else class="td2-trail-section">
            <div class="td2-chain-title">📍 追踪止损</div>
            <div class="td2-trail-ctrl">
              <ElInputNumber v-model="trailEditPct" :min="1" :max="20" :step="0.5" :precision="1" size="small" style="width:110px" />
              <span style="font-size:12px;color:var(--text-tertiary)">%回撤</span>
              <ElButton size="small" type="primary" @click="setTrailingStop(tradeDetailData.ts_code, true)" :loading="trailSaving">激活追踪止损</ElButton>
            </div>
          </div>
        </div>
      </div>
      <div v-else class="empty">无数据</div>
    </ElDialog>

    <!-- 审查弹窗 -->
    <ElDialog v-model="tradeAuditVisible" title="🔍 全部交易审查" width="800px">
      <div v-if="tradeAuditData.length" class="al"><div class="ah"><span>股票</span><span>策略</span><span>买入</span><span>卖出</span><span>盈亏</span><span>状态</span></div><div v-for="t in tradeAuditData" :key="t.ts_code" class="ar" @click="openTradeDetail(t.ts_code); tradeAuditVisible = false"><span class="code">{{ t.ts_code }}</span><span><ElTag size="small" type="info">{{ strategyCN(t.strategy) }}</ElTag></span><span>{{ t.buy_time }} {{ t.buy_price?.toFixed(2) }}</span><span>{{ t.sell_time || '-' }} {{ t.sell_price?.toFixed(2) || '-' }}</span><span :class="t.profit_pct !== null && t.profit_pct >= 0 ? 'up' : 'down'">{{ t.profit_pct !== null ? (t.profit_pct >= 0 ? '+' : '') + t.profit_pct.toFixed(2) + '%' : '-' }}</span><span class="text-tertiary-sm">{{ t.status }}</span></div></div>
      <div v-else class="empty">暂无交易记录</div>
    </ElDialog>
    <!-- 回测对比弹窗 -->
    <ElDialog v-model="compareVisible" title="📊 实盘 vs 回测对比" width="700px">
      <div v-if="compareData.length" class="cl-table">
        <div class="cl-h"><span>策略</span><span>实盘交易</span><span>实盘胜率</span><span>实盘盈亏</span><span>回测收益</span><span>回测胜率</span><span>回测回撤</span><span>回测夏普</span></div>
        <div v-for="c in compareData" :key="c.strategy" class="cl-r">
          <span class="code">{{ strategyCN(c.strategy) }}</span>
          <span>{{ c.live_trades }}笔</span>
          <span :class="c.live_win_rate >= 50 ? 'up' : 'down'">{{ c.live_win_rate }}%</span>
          <span :class="c.live_pnl >= 0 ? 'up' : 'down'">{{ c.live_pnl >= 0 ? '+' : '' }}{{ c.live_pnl.toFixed(0) }}</span>
          <span :class="c.bt_return >= 0 ? 'up' : 'down'">{{ c.bt_return }}%</span>
          <span>{{ c.bt_win_rate }}%</span>
          <span class="text-stock-up">{{ c.bt_drawdown }}%</span>
          <span>{{ c.bt_sharpe }}</span>
        </div>
      </div>
      <div v-else class="empty">暂无对比数据（需先运行回测）</div>
    </ElDialog>

    <!-- 【调试增强】9层筛选调试弹窗 -->
    <ElDialog v-model="layerDebugVisible" title="🧪 9层筛选管道调试" width="750px">
      <div v-if="layerDebugData" class="layer-debug">
        <div class="ld-header">
          <ElTag :type="layerDebugData.dry_run ? 'warning' : 'success'" size="small">{{ layerDebugData.dry_run ? '🔍调试模式' : '正常交易' }}</ElTag>
          <span>信号: {{ layerDebugData.total_signals }} | 已执行: {{ layerDebugData.executed_signals }} | 跳过: {{ layerDebugData.skipped_signals }} | 过期: {{ layerDebugData.expired_signals }}</span>
        </div>
        <div v-if="layerDebugData.pipeline_config" class="ld-pipeline">
          <div class="ld-title">管道配置</div>
          <div class="ld-layers">
            <div v-for="(enabled, layer) in layerDebugData.pipeline_config.layer_enabled" :key="layer" class="ld-layer">
              <span :class="enabled ? 'ld-on' : 'ld-off'">{{ enabled ? '✅' : '⏭️' }}</span>
              <span class="ld-name">{{ layerLabel(layer) }}</span>
            </div>
          </div>
          <div class="ld-sentiment" v-if="layerDebugData.pipeline_config.sentiment">
            情绪: {{ layerDebugData.pipeline_config.sentiment.score }} → {{ layerDebugData.pipeline_config.sentiment.period }} | 仓位系数: {{ (layerDebugData.pipeline_config.position_ratio * 100).toFixed(0) }}%
          </div>
        </div>
        <div v-if="layerDebugData.signal_traces?.length" class="ld-traces">
          <div class="ld-title">信号逐层链路</div>
          <div v-for="trace in layerDebugData.signal_traces" :key="trace.ts_code + trace.strategy" class="ld-trace-card">
            <div class="ld-trace-top"><span class="code">{{ trace.ts_code }}</span><span class="name">{{ trace.stock_name }}</span><ElTag size="small" type="info">{{ strategyCN(trace.strategy) }}</ElTag><ElTag size="small" :type="signalStatusTag(trace.signal_status).type">{{ signalStatusTag(trace.signal_status).text }}</ElTag></div>
            <div class="ld-trace-layers">
              <div v-for="(line, i) in formatLayerTrace(trace.layer_trace)" :key="i" class="ld-trace-line">{{ line }}</div>
            </div>
          </div>
        </div>
        <div v-else class="empty">暂无信号链路数据</div>
      </div>
      <div v-else class="empty">加载中...</div>
    </ElDialog>

    <!-- 单只股票扫描链路弹窗 -->
    <ElDialog v-model="scanTraceVisible" title="🧪 扫描链路 — {{ scanTraceCode }}" width="700px">
      <div v-if="scanTraceData" class="scan-trace">
        <div v-if="scanTraceData.status === 'not_found'" class="empty">{{ scanTraceData.message }}</div>
        <div v-else>
          <div class="st-header">
            <span class="code">{{ scanTraceData.ts_code }}</span>
            <span class="name">{{ scanTraceData.stock_name }}</span>
            <ElTag size="small" :type="signalStatusTag(scanTraceData.signal_status).type">{{ signalStatusTag(scanTraceData.signal_status).text }}</ElTag>
            <span :class="scanTraceData.pct_chg >= 0 ? 'up' : 'down'" style="font-weight:600">{{ scanTraceData.pct_chg >= 0 ? '+' : '' }}{{ scanTraceData.pct_chg?.toFixed(1) }}%</span>
          </div>
          <div class="st-reason">{{ scanTraceData.reason }}</div>
          <div v-if="scanTraceData.age_seconds" class="st-age">信号年龄: {{ scanTraceData.age_seconds }}秒</div>
          <div v-if="scanTraceData.layer_trace" class="st-trace">
            <div class="st-title">逐层筛选链路</div>
            <div v-for="(line, i) in formatLayerTrace(scanTraceData.layer_trace)" :key="i" class="st-line">{{ line }}</div>
          </div>
          <div v-if="scanTraceData.decision_detail" class="st-detail">
            <div class="st-title">决策详情</div>
            <div v-for="(line, i) in formatDecisionDetail(scanTraceData.decision_detail)" :key="i" class="st-line">{{ line }}</div>
          </div>
          <div v-if="scanTraceData.factors" class="st-factors">
            <div class="st-title">关键因子</div>
            <div class="st-fg">
              <div v-for="(v, k) in scanTraceData.factors" :key="k" class="st-fi"><span class="st-fl">{{ factorLabel(k) }}</span><span class="st-fv">{{ typeof v === 'number' ? v.toFixed(2) : v }}</span></div>
            </div>
          </div>
        </div>
      </div>
      <div v-else class="empty">加载中...</div>
    </ElDialog>
    <!-- 回放日期弹窗 -->
    <ElDialog v-model="replayDateVisible" title="🔄 回放模式" width="380px" :close-on-click-modal="false">
      <div style="margin-bottom:12px;font-size:14px">选择要回放的交易日期，将使用历史数据重放扫描：</div>
      <ElDatePicker v-model="replayDateInput" type="date" placeholder="选择回放日期" value-format="YYYY-MM-DD" style="width:100%" :disabled-date="(d: Date) => d > new Date()" />
      <template #footer><ElButton @click="cancelReplay">取消</ElButton><ElButton type="primary" @click="confirmReplay" :disabled="!replayDateInput">确认回放</ElButton></template>
    </ElDialog>

    <!-- 【P1-7】交易确认弹窗 -->
    <ElDialog v-model="confirmVisible" :title="confirmData.title" width="420px" :close-on-click-modal="false">
      <div style="font-size:14px;line-height:1.8;white-space:pre-line">{{ confirmData.message }}</div>
      <template #footer><ElButton @click="confirmVisible = false" :disabled="confirmLoading">取消</ElButton><ElButton type="danger" :loading="confirmLoading" @click="handleConfirm">确认执行</ElButton></template>
    </ElDialog>

    <!-- 【P1-6】复盘报告弹窗 -->
    <ElDialog v-model="dailyReportVisible" title="📈 每日复盘报告" width="750px">
      <div v-if="dailyReport" class="dr">
        <div class="dr-sec"><div class="dr-t">💰 账户概览</div><div class="dr-g"><div class="dr-i"><span class="dr-l">总资产</span><span class="dr-v">{{ (dailyReport.account.total_assets / 10000).toFixed(1) }}万</span></div><div class="dr-i"><span class="dr-l">可用</span><span class="dr-v">{{ (dailyReport.account.available_cash / 10000).toFixed(1) }}万</span></div><div class="dr-i"><span class="dr-l">仓位</span><span class="dr-v">{{ dailyReport.account.position_ratio }}%</span></div><div class="dr-i"><span class="dr-l">今日盈亏</span><span class="dr-v" :class="dailyReport.account.today_profit >= 0 ? 'up' : 'down'">{{ dailyReport.account.today_profit >= 0 ? '+' : '' }}{{ dailyReport.account.today_profit.toFixed(0) }}</span></div></div></div>
        <div class="dr-sec"><div class="dr-t">📊 持仓概况</div><div class="dr-g"><div class="dr-i"><span class="dr-l">持仓数</span><span class="dr-v">{{ dailyReport.positions.count }}</span></div><div class="dr-i"><span class="dr-l">止损</span><span class="dr-v text-stock-up">{{ dailyReport.stop_loss_count }}</span></div><div class="dr-i"><span class="dr-l">止盈</span><span class="dr-v text-stock-down">{{ dailyReport.take_profit_count }}</span></div><div class="dr-i"><span class="dr-l">胜率</span><span class="dr-v">{{ dailyReport.win_rate }}%</span></div></div></div>
        <div class="dr-sec" v-if="dailyReport.positions.top_profit?.length"><div class="dr-t">🏆 最赚</div><div v-for="p in dailyReport.positions.top_profit" class="dr-p"><span class="code">{{ p.ts_code }}</span><span>{{ p.name }}</span><span class="up">+{{ p.pct }}%</span></div></div>
        <div class="dr-sec" v-if="dailyReport.positions.top_loss?.length"><div class="dr-t">💀 最亏</div><div v-for="p in dailyReport.positions.top_loss" class="dr-p"><span class="code">{{ p.ts_code }}</span><span>{{ p.name }}</span><span class="down">{{ p.pct }}%</span></div></div>
        <div class="dr-sec" v-if="dailyReport.positions.strategy_summary"><div class="dr-t">📋 策略汇总</div><div v-for="(s, k) in dailyReport.positions.strategy_summary" class="dr-p"><span>{{ strategyCN(k) }}</span><span>{{ s.count }}只</span><span :class="(s.total_profit || s.total_pnl || 0) >= 0 ? 'up' : 'down'">¥{{ (s.total_profit || s.total_pnl || 0) >= 0 ? '+' : '' }}{{ (s.total_profit || s.total_pnl || 0).toFixed(0) }}</span></div></div>
      </div>
      <div v-else class="empty">暂无复盘数据</div>
    </ElDialog>

    <!-- 周报弹窗 -->
    <ElDialog v-model="weeklyReportVisible" title="📊 周报 — 最近5个交易日" width="800px">
      <div v-if="weeklyReportData" class="wr">
        <div class="wr-sec"><div class="wr-t">💰 账户状态</div><div class="wr-g"><div class="wr-i"><span class="wr-l">总资产</span><span class="wr-v">{{ (weeklyReportData.account?.total_assets / 10000 || 0).toFixed(1) }}万</span></div><div class="wr-i"><span class="wr-l">累计盈亏</span><span class="wr-v" :class="weeklyReportData.account?.total_profit >= 0 ? 'up' : 'down'">{{ weeklyReportData.account?.total_profit >= 0 ? '+' : '' }}{{ (weeklyReportData.account?.total_profit || 0).toFixed(0) }}</span></div><div class="wr-i"><span class="wr-l">可用现金</span><span class="wr-v">{{ (weeklyReportData.account?.available_cash / 10000 || 0).toFixed(1) }}万</span></div></div></div>
        <div class="wr-sec"><div class="wr-t">📈 交易统计</div><div class="wr-g"><div class="wr-i"><span class="wr-l">交易日</span><span class="wr-v">{{ weeklyReportData.totals?.trading_days || 0 }}天</span></div><div class="wr-i"><span class="wr-l">买入</span><span class="wr-v">{{ weeklyReportData.totals?.total_buys || 0 }}笔</span></div><div class="wr-i"><span class="wr-l">卖出</span><span class="wr-v">{{ weeklyReportData.totals?.total_sells || 0 }}笔</span></div><div class="wr-i"><span class="wr-l">净流入</span><span class="wr-v" :class="weeklyReportData.totals?.net_flow >= 0 ? 'up' : 'down'">{{ (weeklyReportData.totals?.net_flow || 0).toFixed(0) }}</span></div></div></div>
        <div class="wr-sec" v-if="weeklyReportData.strategy_summary"><div class="wr-t">📋 策略汇总</div><div v-for="(s, k) in weeklyReportData.strategy_summary" class="dr-p"><span>{{ strategyCN(k) }}</span><span>{{ s.trades }}笔</span><span :class="s.amount >= 0 ? 'up' : 'down'">¥{{ s.amount >= 0 ? '+' : '' }}{{ s.amount.toFixed(0) }}</span></div></div>
        <div class="wr-sec" v-if="weeklyReportData.daily_stats"><div class="wr-t">📅 每日明细</div><div v-for="(stats, date) in weeklyReportData.daily_stats" class="wr-day"><span class="wr-date">{{ date }}</span><span>买{{ stats.buys }}卖{{ stats.sells }}</span><span :class="stats.sell_amount - stats.buy_amount >= 0 ? 'up' : 'down'">¥{{ (stats.sell_amount - stats.buy_amount).toFixed(0) }}</span></div></div>
      </div>
      <div v-else class="empty">暂无周报数据</div>
    </ElDialog>
    <!-- ==================== 🌅 盘前竞价Tab ==================== -->
    <div v-if="activeTab === 'premarket'" class="mm-tab-content">
      <div class="mm-tab-scroll">
        <!-- 竞价状态 -->
        <div class="pm-status-bar">
          <div class="pm-status-icon">{{ premarketStatus === 'active' ? '🔴' : premarketStatus === 'ended' ? '✅' : premarketStatus === 'waiting' ? '⏳' : '💤' }}</div>
          <div class="pm-status-text">
            <div class="pm-status-title">{{ {active: '竞价进行中', ended: '竞价已结束', waiting: '等待竞价(9:15)', off: '非交易时间'}[premarketStatus] }}</div>
            <div class="pm-status-sub">盘前预选 · 竞价异动 · 量比排名</div>
          </div>
          <ElButton size="small" @click="fetchPremarketData" :loading="false">🔄 刷新</ElButton>
        </div>

        <div class="pm-grid">
          <!-- 左: 预选候选 -->
          <div class="pm-section">
            <div class="st">📋 盘前预选 ({{ premarketCandidates.length }})</div>
            <div v-if="!premarketCandidates.length" class="empty">9:00后自动生成</div>
            <div v-for="c in premarketCandidates" :key="c.ts_code" class="pm-candidate">
              <ElTag size="small" :color="strategyMeta[c.strategy]?.color || 'var(--text-tertiary)'" class="tag-solid">{{ strategyCN(c.strategy) }}</ElTag>
              <span class="code">{{ c.ts_code }}</span>
              <span class="name">{{ c.stock_name }}</span>
              <span v-if="c.auction_pct" :class="c.auction_pct >= 0 ? 'up' : 'down'" class="pct">{{ c.auction_pct >= 0 ? '+' : '' }}{{ (c.auction_pct * 100).toFixed(1) }}%</span>
              <span v-if="c.reason" class="text-tertiary" style="font-size:11px">{{ c.reason }}</span>
            </div>
          </div>

          <!-- 右: 竞价异动 -->
          <div class="pm-section">
            <div class="st">⚡ 竞价异动 ({{ auctionTopGainers.length }})</div>
            <div v-if="!auctionTopGainers.length" class="empty">9:15后自动更新</div>
            <div v-for="g in auctionTopGainers" :key="g.ts_code" class="pm-candidate">
              <span class="code">{{ g.ts_code }}</span>
              <span class="name">{{ g.name }}</span>
              <span :class="g.pct_chg >= 0 ? 'up' : 'down'" class="pct">{{ g.pct_chg >= 0 ? '+' : '' }}{{ g.pct_chg.toFixed(1) }}%</span>
              <span v-if="g.volume_ratio" class="text-tertiary" style="font-size:11px">量比{{ g.volume_ratio.toFixed(1) }}</span>
            </div>

            <div class="st" style="margin-top:12px">🎯 竞价信号 ({{ premarketSignals.length }})</div>
            <div v-if="!premarketSignals.length" class="empty">竞价过滤后生成</div>
            <div v-for="s in premarketSignals" :key="s.ts_code" class="pm-signal">
              <ElTag size="small" :color="strategyMeta[s.strategy]?.color || 'var(--text-tertiary)'" class="tag-solid">{{ strategyCN(s.strategy) }}</ElTag>
              <span class="code">{{ s.ts_code }}</span>
              <span class="name">{{ s.stock_name }}</span>
              <span :class="s.pct_chg >= 0 ? 'up' : 'down'" class="pct">{{ s.pct_chg >= 0 ? '+' : '' }}{{ s.pct_chg.toFixed(1) }}%</span>
              <ElTag v-if="!dryRun" size="small" type="success" plain class="btn-xs" @click="quickBuy(s)">买</ElTag>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ==================== 🔍 扫描追踪Tab ==================== -->
    <div v-if="activeTab === 'scan-trace'" class="mm-tab-content">
      <div class="mm-tab-scroll">
        <!-- 顶部: 扫描历史列表(单行紧凑) -->
        <div class="st">📡 扫描历史
          <ElDatePicker v-model="scanTraceDate" type="date" placeholder="全部日期" size="small" value-format="YYYY-MM-DD" style="width:130px;margin-left:8px" :disabled-date="(d: Date) => d > new Date()" @change="fetchScanHistory" />
          <ElButton size="small" @click="scanTraceDate='';fetchScanHistory()" :loading="scanHistoryLoading">🔄</ElButton>
          <span class="text-tertiary" style="font-size:11px;margin-left:auto">全量5分钟 · 持仓30秒 · 信号5分钟过期</span>
        </div>
        <div v-if="scanHistoryLoading" class="empty" style="padding:8px 0">加载中...</div>
        <div v-else-if="!scanHistory.length" class="empty" style="padding:8px 0">启动后扫描记录会显示在这里</div>
        <div v-else class="scan-strip">
          <div v-for="(s, i) in scanHistory" :key="i" class="scan-chip" :class="{ active: selectedScanIdx === i }" @click="selectedScanIdx = i; fetchScanTrace(s.scan_id || '')">
            <span class="sc-time">{{ (s.scan_time || s.time || '').substring(11, 19) }}</span>
            <span class="sc-type" :class="s.scan_type === 'full' ? 'full' : 'quick'">{{ s.scan_type === 'full' ? '全量' : '快速' }}</span>
            <span class="sc-stats">{{ s.summary?.total_candidates || 0 }}→{{ s.summary?.passed || 0 }}→{{ s.buys || 0 }}</span>
          </div>
        </div>

        <!-- 中部: 9层漏斗(横向紧凑) -->
        <div v-if="scanTraceDetail" class="scan-funnel-bar">
          <template v-for="(layerData, layerName, idx) in scanTraceDetail.summary || {}">
            <div v-if="layerName !== 'total_candidates' && layerName !== 'passed' && layerName !== 'rejected' && typeof layerData === 'object'" :key="layerName" class="fb-step" :class="{ passed: layerData.output > 0 }">
              <span class="fb-name">{{ layerLabel(layerName) }}</span>
              <span class="fb-nums">{{ layerData.output || 0 }}<span v-if="layerData.rejected" class="fb-rej">-{{ layerData.rejected }}</span></span>
            </div>
            <span v-if="layerName !== 'total_candidates' && layerName !== 'passed' && layerName !== 'rejected' && typeof layerData === 'object' && idx < 8" :key="'arrow'+layerName" class="fb-arrow">→</span>
          </template>
          <span v-if="scanTraceDetail._pagination" class="fb-summary">通过{{ scanTraceDetail._pagination.passed_count }} / 淘汰{{ scanTraceDetail._pagination.rejected_count }}</span>
        </div>

        <!-- 底部: 候选追踪(主区域) -->
        <div v-if="scanTraceDetail" style="margin-top:8px">
          <div class="st" style="display:flex;align-items:center;gap:8px">
            <span>🎯 候选追踪</span>
            <div style="display:flex;gap:4px;margin-left:auto">
              <button :class="['tab-btn-sm', scanTraceFilter === 'passed' ? 'active' : '']" @click="switchScanTraceFilter('passed')" :disabled="scanTraceLoadingMore">✅ 通过({{ scanTraceDetail._pagination?.passed_count || 0 }})</button>
              <button :class="['tab-btn-sm', scanTraceFilter === 'rejected' ? 'active' : '']" @click="switchScanTraceFilter('rejected')" :disabled="scanTraceLoadingMore">❌ 淘汰({{ scanTraceDetail._pagination?.rejected_count || 0 }})</button>
              <button :class="['tab-btn-sm', scanTraceFilter === 'summary' ? 'active' : '']" @click="switchScanTraceFilter('summary')">📊 统计</button>
            </div>
          </div>

          <!-- 淘汰统计视图 -->
          <div v-if="scanTraceFilter === 'summary' && scanTraceDetail.rejected_layer_stats" class="rejected-stats">
            <div v-for="(count, layer) in scanTraceDetail.rejected_layer_stats" :key="layer" class="rs-row">
              <span class="rs-label">{{ rejectionLayerCN[layer] || layer }}</span>
              <div class="rs-bar-track"><div class="rs-bar-fill" :style="{ width: Math.min(count / (scanTraceDetail._pagination?.rejected_count || 1) * 100, 100) + '%' }"></div></div>
              <span class="rs-count">{{ count }}只</span>
            </div>
          </div>

          <!-- 候选列表 -->
          <div v-if="scanTraceFilter !== 'summary'">
            <div v-if="scanTraceLoadingMore" class="empty">加载中...</div>
            <div v-else-if="!scanTraceDetail.candidates?.length" class="empty">{{ scanTraceFilter === 'passed' ? '本轮无通过候选' : '无淘汰候选' }}</div>
            <div class="et-table">
              <div class="et-th"><span>策略</span><span>代码</span><span>名称</span><span>涨跌</span><span>结果</span></div>
              <div v-for="sig in scanTraceDetail.candidates || []" :key="sig.ts_code + sig.strategy" class="et-tr" :class="sig.final_status === 'passed' ? 'et-pass' : 'et-fail'">
                <span class="et-c et-strat"><ElTag size="small" :color="strategyMeta[sig.strategy]?.color || 'var(--text-tertiary)'" class="tag-solid" style="font-size:10px">{{ strategyCN(sig.strategy) }}</ElTag></span>
                <span class="et-c code">{{ sig.ts_code }}</span>
                <span class="et-c name">{{ sig.stock_name }}</span>
                <span class="et-c" :class="sig.pct_chg >= 0 ? 'up' : 'down'" style="font-weight:600">{{ sig.pct_chg >= 0 ? '+' : '' }}{{ (sig.pct_chg || 0).toFixed(1) }}%</span>
                <span class="et-c et-res" v-if="sig.final_status === 'passed'">✅ 通过</span>
                <span class="et-c et-res" v-else>❌ {{ rejectionLayerCN[sig.rejection_layer] || sig.rejection_layer }}: {{ rejectionReasonCN(sig.rejection_reason) || sig.rejection_reason }}</span>
              </div>
            </div>
            <div v-if="scanTraceDetail._pagination && (scanTraceDetail._pagination.has_more_passed || scanTraceDetail._pagination.has_more_rejected)" class="load-more-hint">
              <span class="text-tertiary" style="font-size:11px">已显示{{ scanTraceDetail._pagination.returned_count }}条 / 共{{ scanTraceFilter === 'passed' ? scanTraceDetail._pagination.passed_count : scanTraceDetail._pagination.rejected_count }}条</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ==================== 📋 复盘Tab (专业版) ==================== -->
    <div v-if="activeTab === 'review'" class="mm-tab-content">
      <div class="mm-tab-scroll">
        <!-- 日期/周期选择 -->
        <div class="review-header">
          <div class="review-tabs">
            <button :class="['review-tab', reviewTab === 'daily' ? 'active' : '']" @click="reviewTab = 'daily'; fetchReviewData()">📊 日复盘</button>
            <button :class="['review-tab', reviewTab === 'weekly' ? 'active' : '']" @click="reviewTab = 'weekly'; fetchReviewData()">📅 周复盘</button>
            <button :class="['review-tab', reviewTab === 'monthly' ? 'active' : '']" @click="reviewTab = 'monthly'; fetchReviewData()">📆 月复盘</button>
          </div>
          <ElDatePicker v-model="reviewDate" type="date" size="small" value-format="YYYY-MM-DD" @change="fetchReviewData" />
          <ElButton size="small" @click="fetchReviewData" :loading="reviewLoading">🔄</ElButton>
        </div>

        <!-- 日复盘内容 -->
        <template v-if="reviewTab === 'daily' && dailyReportData">
          <!-- 概览卡片 -->
          <div class="review-summary-cards">
            <div class="rsc"><div class="rsc-label">收益</div><div class="rsc-value" :class="dailyReportData.account?.today_profit >= 0 ? 'up' : 'down'">{{ dailyReportData.account?.today_profit >= 0 ? '+' : '' }}¥{{ dailyReportData.account?.today_profit?.toFixed(0) }}</div></div>
            <div class="rsc"><div class="rsc-label">胜率</div><div class="rsc-value">{{ dailyReportData.win_rate }}%</div></div>
            <div class="rsc"><div class="rsc-label">交易</div><div class="rsc-value">{{ dailyReportData.trades?.buy + dailyReportData.trades?.sell || 0 }}笔</div></div>
            <div class="rsc"><div class="rsc-label">仓位</div><div class="rsc-value">{{ dailyReportData.account?.position_ratio }}%</div></div>
            <div class="rsc"><div class="rsc-label">止损</div><div class="rsc-value down">{{ dailyReportData.stop_loss_count }}</div></div>
            <div class="rsc"><div class="rsc-label">止盈</div><div class="rsc-value up">{{ dailyReportData.take_profit_count }}</div></div>
          </div>

          <!-- 策略贡献 -->
          <div class="st" style="margin-top:12px">🎯 策略贡献</div>
          <div class="strategy-contrib">
            <div v-for="(data, key) in dailyReportData.positions?.strategy_summary || {}" :key="key" class="sc-bar-row">
              <span class="sc-bar-label">{{ strategyCN(key) }}</span>
              <div class="sc-bar-track"><div class="sc-bar-fill" :class="(data.closed_profit || data.total_profit) >= 0 ? 'up' : 'down'" :style="{ width: Math.min(Math.abs(data.closed_profit || data.total_profit || 0) / Math.max(Math.abs(dailyReportData.account?.today_profit || 1), 1) * 100, 100) + '%' }"></div></div>
              <span class="sc-bar-value" :class="(data.closed_profit || data.total_profit) >= 0 ? 'up' : 'down'">¥{{ (data.closed_profit || data.total_profit || 0).toFixed(0) }}</span>
              <span class="text-tertiary" style="font-size:11px">胜{{ data.win_rate }}% {{ data.closed_count || data.count }}笔</span>
            </div>
          </div>

          <!-- 净值曲线 -->
          <div class="st" style="margin-top:12px">📈 净值曲线</div>
          <div v-if="perfData.length || pnlHistory.length" class="pnl-chart-wrap-lg">
            <VChart :option="pnlOption" autoresize style="height:260px;width:100%" />
          </div>
          <div v-else class="empty" style="padding:12px 0">暂无净值数据</div>

          <!-- 逐笔归因 -->
          <div class="st" style="margin-top:12px">📝 逐笔归因</div>
          <div v-if="!tradeAttributions.length" class="empty">暂无交易数据</div>
          <div v-for="t in tradeAttributions" :key="t.ts_code" class="attribution-card">
            <div class="attr-top">
              <ElTag size="small" :color="strategyMeta[t.strategy]?.color || 'var(--text-tertiary)'" class="tag-solid">{{ strategyCN(t.strategy) }}</ElTag>
              <span class="code">{{ t.ts_code }}</span>
              <span class="name">{{ t.stock_name }}</span>
              <span :class="t.profit_pct >= 0 ? 'up' : 'down'" class="pct ml-auto">{{ t.profit_pct >= 0 ? '+' : '' }}{{ t.profit_pct.toFixed(1) }}%</span>
            </div>
            <div class="attr-detail">
              <div class="attr-row"><span>买入</span><span>¥{{ t.buy_price?.toFixed(2) }} {{ t.buy_time }}</span></div>
              <div class="attr-row"><span>卖出</span><span>¥{{ t.sell_price?.toFixed(2) }} {{ t.sell_time }}</span></div>
              <div class="attr-row"><span>原因</span><span>{{ t.sell_reason }}</span></div>
              <div class="attr-row" v-if="t.why_profit"><span class="up">赚在哪</span><span>{{ t.why_profit }}</span></div>
              <div class="attr-row" v-if="t.why_loss"><span class="down">亏在哪</span><span>{{ t.why_loss }}</span></div>
            </div>
          </div>

          <!-- 情绪周期 -->
          <div class="st" style="margin-top:12px">🌡️ 情绪周期</div>
          <MarketSentiment />
        </template>

        <!-- 周复盘内容 -->
        <template v-if="reviewTab === 'weekly' && weeklyReportData">
          <div class="review-summary-cards">
            <div class="rsc"><div class="rsc-label">周收益</div><div class="rsc-value" :class="weeklyReportData.weekly_profit >= 0 ? 'up' : 'down'">¥{{ weeklyReportData.weekly_profit?.toFixed(0) }}</div></div>
            <div class="rsc"><div class="rsc-label">周胜率</div><div class="rsc-value">{{ weeklyReportData.win_rate }}%</div></div>
            <div class="rsc"><div class="rsc-label">交易</div><div class="rsc-value">{{ weeklyReportData.total_trades }}笔</div></div>
          </div>
          <div v-if="weeklyReportData.daily_breakdown" class="st" style="margin-top:12px">📅 逐日明细</div>
          <div v-if="weeklyReportData.daily_breakdown" class="weekly-daily-table">
            <div class="wdt-header"><span>日期</span><span>盈亏</span><span>交易</span><span>胜率</span><span>情绪</span></div>
            <div v-for="d in weeklyReportData.daily_breakdown" :key="d.date" class="wdt-row">
              <span>{{ d.date }}</span>
              <span :class="d.profit >= 0 ? 'up' : 'down'">{{ d.profit >= 0 ? '+' : '' }}¥{{ d.profit?.toFixed(0) }}</span>
              <span>{{ d.trades }}笔</span>
              <span>{{ d.win_rate }}%</span>
              <span>{{ d.sentiment || '-' }}</span>
            </div>
          </div>
        </template>

        <!-- 执行质量 & 实盘vs回测 -->
        <div class="st" style="margin-top:16px">🎯 执行质量</div>
        <div v-if="executionQuality" class="eq-grid">
          <div class="eq-card"><div class="eq-label">平均滑点</div><div class="eq-value">{{ executionQuality.avg_slippage_pct?.toFixed(2) }}%</div></div>
          <div class="eq-card"><div class="eq-label">成交延迟</div><div class="eq-value">{{ executionQuality.avg_fill_delay_ms?.toFixed(0) }}ms</div></div>
          <div class="eq-card"><div class="eq-label">成交率</div><div class="eq-value">{{ executionQuality.fill_rate_pct?.toFixed(1) }}%</div></div>
          <div class="eq-card"><div class="eq-label">拒绝数</div><div class="eq-value">{{ executionQuality.rejected_orders || 0 }}</div></div>
        </div>
        <div v-else class="empty">暂无执行数据</div>

        <div class="st" style="margin-top:12px">📊 实盘 vs 回测偏差</div>
        <div v-if="liveBacktestDiff.length" class="lb-table">
          <div class="lb-header"><span>策略</span><span>实盘交易</span><span>实盘胜率</span><span>回测胜率</span><span>偏差</span><span>实盘收益</span><span>回测收益</span><span>偏差</span></div>
          <div v-for="c in liveBacktestDiff" :key="c.strategy" class="lb-row">
            <span class="code">{{ strategyCN(c.strategy) }}</span>
            <span>{{ c.live_trades }}笔</span>
            <span>{{ c.live_win_rate }}%</span>
            <span>{{ c.bt_win_rate }}%</span>
            <span :class="Math.abs(c.live_win_rate - c.bt_win_rate) > 15 ? 'down' : 'up'">{{ (c.live_win_rate - c.bt_win_rate).toFixed(1) }}%</span>
            <span :class="c.live_pnl >= 0 ? 'up' : 'down'">¥{{ c.live_pnl?.toFixed(0) }}</span>
            <span :class="c.bt_return >= 0 ? 'up' : 'down'">{{ c.bt_return }}%</span>
            <span :class="c.live_pnl >= 0 ? 'up' : 'down'">{{ c.live_pnl >= 0 ? '+' : '' }}{{ ((c.live_pnl / (c.bt_return || 1)) - 1).toFixed(1) }}%</span>
          </div>
        </div>
        <div v-else class="empty">暂无对比数据</div>

        <!-- 改进建议 -->
        <div class="st" style="margin-top:12px">💡 改进建议</div>
        <div class="suggestions">
          <div v-if="dailyReportData?.stop_loss_count > 3" class="suggestion warn">止损{{ dailyReportData.stop_loss_count }}次过多，建议检查入场条件或收紧情绪阈值</div>
          <div v-if="executionQuality?.avg_slippage_pct > 0.5" class="suggestion warn">平均滑点{{ executionQuality.avg_slippage_pct.toFixed(2) }}%偏高，考虑限价单或避开开盘5分钟</div>
          <div v-if="liveBacktestDiff.some(c => Math.abs(c.live_win_rate - c.bt_win_rate) > 20)" class="suggestion warn">实盘胜率偏离回测>20%，参数可能过拟合，建议降仓位</div>
          <div v-if="dailyReportData?.positions?.strategy_summary" class="suggestion info">
            策略集中度: {{ Object.keys(dailyReportData.positions.strategy_summary).filter(k => dailyReportData.positions.strategy_summary[k].count > 0).length }}个策略活跃
          </div>
        </div>

        <!-- 策略参数对比(实盘vs回测) -->
        <div class="st" style="margin-top:16px">🔧 策略参数对比 <span class="text-tertiary" style="font-size:11px">实盘(MongoDB) vs 回测(strategy_defaults.py)</span> <ElButton size="small" @click="fetchParamCompare" :loading="paramCompareLoading">🔄</ElButton></div>
        <div v-if="paramCompare" class="param-compare">
          <div v-if="paramCompare.drift_count > 0" class="suggestion warn" style="margin-bottom:8px">⚠️ 检测到{{ paramCompare.drift_count }}个参数漂移(实盘≠回测)，可能影响实盘-回测一致性</div>
          <div v-for="sc in paramCompare.strategy_comparisons || []" :key="sc.strategy_id" class="pc-strategy">
            <div class="pc-header">
              <span class="pc-name">{{ sc.strategy_name }}</span>
              <ElTag v-if="sc.drift_count > 0" size="small" type="danger">{{ sc.drift_count }}项漂移</ElTag>
              <ElTag v-else size="small" type="success">一致</ElTag>
            </div>
            <div v-if="sc.param_diffs?.length" class="pc-params">
              <div v-for="p in sc.param_diffs.filter(d => d.diff)" :key="p.key" class="pc-diff-row">
                <span class="pc-key">{{ p.label || p.key }}</span>
                <span class="pc-live">实盘: {{ typeof p.live_value === 'number' ? (p.live_value < 0.1 ? p.live_value.toFixed(4) : p.live_value.toFixed(2)) : p.live_value }}</span>
                <span class="pc-bt">回测: {{ typeof p.backtest_value === 'number' ? (p.backtest_value < 0.1 ? p.backtest_value.toFixed(4) : p.backtest_value.toFixed(2)) : p.backtest_value }}</span>
              </div>
              <details v-if="sc.param_diffs.filter(d => !d.diff).length > 0"><summary class="cp" style="font-size:11px;color:var(--text-tertiary)">一致参数({{ sc.param_diffs.filter(d => !d.diff).length }}项) ▾</summary>
                <div v-for="p in sc.param_diffs.filter(d => !d.diff)" :key="p.key" class="pc-same-row">
                  <span class="pc-key">{{ p.label || p.key }}</span>
                  <span>{{ typeof p.live_value === 'number' ? (p.live_value < 0.1 ? p.live_value.toFixed(4) : p.live_value.toFixed(2)) : p.live_value }}</span>
                </div>
              </details>
            </div>
          </div>
          <!-- 全局风控参数 -->
          <div v-if="paramCompare.global_risk" class="pc-strategy" style="margin-top:8px">
            <div class="pc-header">
              <span class="pc-name">全局风控</span>
              <ElTag v-if="paramCompare.global_risk.diffs?.length" size="small" type="danger">{{ paramCompare.global_risk.diffs.length }}项漂移</ElTag>
              <ElTag v-else size="small" type="success">一致</ElTag>
            </div>
            <div class="pc-params">
              <div v-for="d in paramCompare.global_risk.diffs || []" :key="d.key" class="pc-diff-row">
                <span class="pc-key">{{ d.label || d.key }}</span>
                <span class="pc-live">实盘: {{ typeof d.live_value === 'number' ? (d.live_value < 0.1 ? d.live_value.toFixed(4) : d.live_value.toFixed(2)) : d.live_value }}</span>
                <span class="pc-bt">回测: {{ typeof d.backtest_value === 'number' ? (d.backtest_value < 0.1 ? d.backtest_value.toFixed(4) : d.backtest_value.toFixed(2)) : d.backtest_value }}</span>
              </div>
              <details v-if="(paramCompare.global_risk.sames || []).length > 0"><summary class="cp" style="font-size:11px;color:var(--text-tertiary)">一致参数({{ paramCompare.global_risk.sames.length }}项) ▾</summary>
                <div v-for="d in paramCompare.global_risk.sames" :key="d.key" class="pc-same-row">
                  <span class="pc-key">{{ d.label || d.key }}</span>
                  <span v-if="d.missing_in_live" style="color:var(--el-color-warning)">{{ typeof d.backtest_value === 'number' ? (d.backtest_value < 0.1 ? d.backtest_value.toFixed(4) : d.backtest_value.toFixed(2)) : d.backtest_value }} <small>(默认)</small></span>
                  <span v-else>{{ typeof d.live_value === 'number' ? (d.live_value < 0.1 ? d.live_value.toFixed(4) : d.live_value.toFixed(2)) : d.live_value }}</span>
                </div>
              </details>
            </div>
          </div>
        </div>
        <div v-else class="empty">点击刷新加载参数对比</div>
      </div>
    </div>

    <!-- ==================== 风控Tab ==================== -->
    <div v-if="activeTab === 'risk'" class="mm-tab-content">
      <div class="mm-tab-scroll">
        <!-- 系统风控概览 -->
        <div class="st">🛡️ 系统风控概览 <span :class="healthClass" style="font-size:14px">{{ healthEmoji }}</span> <span :class="healthClass" style="font-size:12px;font-weight:600">{{ healthCN }}</span></div>
        <div class="risk-overview">
          <div class="ro-card">
            <span class="ro-label">日回撤</span>
            <span class="rb-progress" style="width:80px"><span class="rb-progress-fill" :style="{ width: Math.min(Math.abs(healthData?.risk_metrics?.daily_drawdown_pct || 0) / (healthData?.risk_metrics?.max_drawdown_pct || 5) * 100, 100) + '%' }" :class="Math.abs(healthData?.risk_metrics?.daily_drawdown_pct || 0) > (healthData?.risk_metrics?.max_drawdown_pct || 5) * 0.7 ? 'danger' : ''"></span></span>
            <span class="ro-value" :class="Math.abs(healthData?.risk_metrics?.daily_drawdown_pct || 0) > (healthData?.risk_metrics?.max_drawdown_pct || 5) * 0.5 ? 'down' : ''">{{ Math.abs(healthData?.risk_metrics?.daily_drawdown_pct || 0).toFixed(2) }}%</span>
          </div>
          <div class="ro-card">
            <span class="ro-label">回撤限制</span>
            <span class="ro-value">{{ (healthData?.risk_metrics?.max_drawdown_pct || 5).toFixed(1) }}%</span>
          </div>
          <div class="ro-card">
            <span class="ro-label">连续亏损</span>
            <span class="ro-value" :class="(healthData?.circuit_breaker?.consecutive_losses || 0) >= ((healthData?.circuit_breaker?.max_consecutive_losses || 3) - 1) ? 'down' : ''">{{ healthData?.circuit_breaker?.consecutive_losses ?? 0 }} / {{ healthData?.circuit_breaker?.max_consecutive_losses ?? 3 }}</span>
          </div>
          <div class="ro-card">
            <span class="ro-label">仓位比例</span>
            <span class="ro-value">{{ ((healthData?.risk_metrics?.position_ratio || 0) * 100).toFixed(0) }}%</span>
          </div>
          <div class="ro-card">
            <span class="ro-label">健康分数</span>
            <span class="ro-value" :class="healthData?.health_score != null && healthData.health_score < 60 ? 'down' : ''">{{ healthData?.health_score ?? '-' }}</span>
          </div>
          <div class="ro-card">
            <span class="ro-label">扫描延迟</span>
            <span class="ro-value" :class="healthData?.scan_lag_seconds > 60 ? 'down' : ''">{{ healthData?.scan_lag_seconds == null ? '-' : healthData.scan_lag_seconds < 0 ? '未运行' : healthData.scan_lag_seconds.toFixed(1) + 's' }}</span>
          </div>
          <div class="ro-card" v-if="healthData?.circuit_breaker?.trading_paused">
            <span class="ro-label">熔断原因</span>
            <span class="ro-value down">{{ healthData?.circuit_breaker?.pause_reason || '-' }}</span>
          </div>
          <div class="ro-card" v-if="healthData?.warnings?.length">
            <span class="ro-label">告警</span>
            <span class="ro-value down">{{ healthData.warnings.join('; ') }}</span>
          </div>
        </div>

        <!-- 持仓风控矩阵 -->
        <PositionRiskMatrix />

        <!-- 持仓止损止盈详情 -->
        <div class="st" style="margin-top:16px">🎯 持仓止损止盈</div>
        <div v-if="!positions.length" class="empty">暂无持仓</div>
        <div v-else class="risk-cards">
          <div v-for="pos in sortedPositions" :key="pos.ts_code" class="risk-card">
            <div class="rc-top">
              <ElTag size="small" :color="strategyMeta[pos.strategy]?.color || 'var(--text-tertiary)'" class="tag-solid">{{ pos.strategy_name || strategyCN(pos.strategy) }}</ElTag>
              <span class="code">{{ pos.ts_code }}</span>
              <span class="name">{{ pos.stock_name }}</span>
              <span :class="pos.profit_pct >= 0 ? 'up' : 'down'" class="pct ml-auto">{{ pos.profit_pct >= 0 ? '+' : '' }}{{ pos.profit_pct.toFixed(1) }}%</span>
            </div>
            <div class="rc-detail">
              <div class="rc-row"><span>成本</span><span>¥{{ pos.cost_price.toFixed(2) }}</span></div>
              <div class="rc-row"><span>现价</span><span>¥{{ pos.current_price.toFixed(2) }}</span></div>
              <div class="rc-row" v-if="pos.stop_loss_price"><span>止损价</span><span class="text-stock-up">¥{{ pos.stop_loss_price.toFixed(2) }}</span></div>
              <div class="rc-row" v-if="pos.take_profit_price"><span>止盈价</span><span class="text-stock-down">¥{{ pos.take_profit_price.toFixed(2) }}</span></div>
              <div class="rc-row"><span>距止损</span><span :class="parseFloat(distanceToStopLoss(pos)) < 2 ? 'down' : ''">{{ distanceToStopLoss(pos) }}</span></div>
              <div class="rc-row" v-if="pos.trailing_stop?.activated"><span>追踪止损</span><span>📍¥{{ pos.trailing_stop.stop_price?.toFixed(2) }} ({{ (pos.trailing_stop.trailing_stop_pct * 100).toFixed(0) }}%)</span></div>
            </div>
            <div v-if="pos.stop_loss_pct != null" class="pos-risk-row" style="margin-top:6px">
              <div class="risk-track"><div class="risk-fill" :style="{ width: Math.max(0, Math.min(100, (pos.profit_pct + normalizePct(pos.stop_loss_pct, 3)) / (normalizePct(pos.stop_loss_pct, 3) + normalizePct(pos.take_profit_pct, 7)) * 100)) + '%' }" :class="pos.profit_pct + normalizePct(pos.stop_loss_pct, 3) < 1 ? 'danger' : pos.profit_pct + normalizePct(pos.stop_loss_pct, 3) < 2 ? 'warning' : 'safe'"></div></div>
              <div class="risk-labels-row"><span class="rl stop">止损{{ formatSlTp(pos.stop_loss_pct, 3) }}</span><span class="rd" :class="{ danger: pos.profit_pct + normalizePct(pos.stop_loss_pct, 3) < 2 }">距止损{{ (pos.profit_pct + normalizePct(pos.stop_loss_pct, 3)).toFixed(1) }}%</span><span class="rl profit">止盈{{ formatSlTp(pos.take_profit_pct, 7) }}</span></div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ==================== 📜 历史Tab ==================== -->
    <div v-if="activeTab === 'history'" class="mm-tab-content">
      <div class="mm-tab-scroll">
        <!-- 交易时间线 -->
        <div class="st">⏱️ 交易时间线 <span class="text-tertiary" style="font-size:11px">({{ timeline.length }}笔)</span>
          <span v-if="cumulativePnl !== 0" :class="cumulativePnl >= 0 ? 'up' : 'down'" style="font-size:12px;margin-left:6px">累计{{ cumulativePnl >= 0 ? '+' : '' }}¥{{ cumulativePnl.toFixed(0) }}</span>
          <ElButton v-if="timeline.length" size="small" type="warning" @click="openTradeAudit" style="margin-left:8px">🔍 审查</ElButton>
          <div style="display:inline-flex;align-items:center;gap:4px;margin-left:8px"><ElDatePicker v-model="historyDate" type="date" placeholder="历史日期" size="small" value-format="YYYY-MM-DD" style="width:130px" :disabled-date="(d: Date) => d > new Date()" /><ElButton size="small" @click="loadHistory" :loading="historyLoading">回放</ElButton><ElButton v-if="historyData.length" size="small" type="info" @click="historyData=[];historyDate=''">返回</ElButton></div>
        </div>
        <div v-if="historyData.length" class="history-tag" style="margin-bottom:6px">📜 {{ historyDate }} 历史回放 ({{ historyData.length }}条)</div>
        <div v-if="!historyData.length && !timeline.length" class="empty">暂无交易记录</div>
        <div class="ht-timeline">
          <div v-for="(item, i) in historyData.length ? historyData : timeline" :key="i" class="tl-row cp" @click="item.action !== 'blocked' && openTradeDetail(item.ts_code)">
            <span class="tl-time">{{ item.time }}</span>
            <span class="tl-action" :class="item.action === 'buy' ? 'buy' : item.action === 'sell' ? 'sell' : 'blocked'">{{ item.action === 'buy' ? '买' : item.action === 'sell' ? '卖' : '⛔' }}</span>
            <span class="code">{{ item.ts_code }}</span><span class="name">{{ item.stock_name }}</span>
            <span v-if="item.action === 'blocked'" class="tl-blocked-reason">{{ item.reason }}</span>
            <template v-else>
              <span v-if="item.strategy" class="tl-strat">{{ strategyCN(item.strategy) }}</span>
              <span class="tl-detail">{{ item.shares }}股@{{ item.price.toFixed(2) }}</span>
              <span v-if="item.profit_pct !== undefined" :class="item.profit_pct >= 0 ? 'up' : 'down'">{{ item.profit_pct >= 0 ? '+' : '' }}{{ item.profit_pct.toFixed(1) }}%</span>
              <span v-if="item.profit_amount != null" :class="item.profit_amount >= 0 ? 'up' : 'down'" class="tl-amt">{{ item.profit_amount >= 0 ? '+' : '' }}¥{{ item.profit_amount.toFixed(0) }}</span>
            </template>
          </div>
        </div>

        <!-- 历史订单 -->
        <div class="st" style="margin-top:16px">📋 历史订单 <span class="text-tertiary" style="font-size:11px">({{ orders.length }}笔)</span></div>
        <div v-if="!orders.length" class="empty">暂无订单</div>
        <div v-else class="ht-orders">
          <div class="ho-header"><span>时间</span><span>方向</span><span>代码</span><span>名称</span><span>数量</span><span>价格</span><span>策略</span></div>
          <div v-for="o in orders" :key="o.order_id" class="ho-row cp" @click="openTradeDetail(o.ts_code)">
            <span class="tl-time">{{ o.trade_date?.slice(-4) || '' }} {{ o.create_time }}</span>
            <span class="tl-action" :class="o.side === 'buy' ? 'buy' : 'sell'">{{ o.side === 'buy' ? '买' : '卖' }}</span>
            <span class="code">{{ o.ts_code }}</span><span class="name">{{ o.stock_name }}</span>
            <span>{{ o.filled_qty }}股</span><span>¥{{ o.filled_price?.toFixed(2) || '0.00' }}</span>
            <span class="text-tertiary-sm">{{ strategyCN(o.strategy) }}</span>
          </div>
        </div>

        <!-- 已平仓汇总 -->
        <div class="st" style="margin-top:16px">💰 已平仓汇总</div>
        <div v-if="!closedPositions.length" class="empty">暂无已平仓记录</div>
        <div v-else class="ht-closed">
          <div class="hc-header"><span>代码</span><span>名称</span><span>策略</span><span>买入价</span><span>卖出价</span><span>盈亏</span><span>盈亏%</span></div>
          <div v-for="cp in closedPositions" :key="cp.ts_code + cp.strategy" class="hc-row" @click="openTradeDetail(cp.ts_code)" :class="cp.profit_pct >= 0 ? 'hc-win' : 'hc-loss'">
            <span class="code">{{ cp.ts_code }}</span><span class="name">{{ cp.stock_name }}</span>
            <span><ElTag size="small" :color="strategyMeta[cp.strategy]?.color || 'var(--text-tertiary)'" class="tag-solid" style="font-size:10px">{{ strategyCN(cp.strategy) }}</ElTag></span>
            <span>¥{{ cp.buy_price?.toFixed(2) }}</span><span>¥{{ cp.sell_price?.toFixed(2) }}</span>
            <span :class="cp.profit_amount >= 0 ? 'up' : 'down'">{{ cp.profit_amount >= 0 ? '+' : '' }}¥{{ Math.abs(cp.profit_amount).toFixed(0) }}</span>
            <span :class="cp.profit_pct >= 0 ? 'up' : 'down'" style="font-weight:600">{{ cp.profit_pct >= 0 ? '+' : '' }}{{ cp.profit_pct.toFixed(1) }}%</span>
          </div>
        </div>

        <!-- 审计日志 -->
        <div class="st" style="margin-top:16px">📝 审计日志 <ElButton size="small" @click="fetchAuditLog" :loading="auditLogLoading">🔄</ElButton></div>
        <div v-if="!auditLog.length" class="empty">暂无审计记录</div>
        <div v-else class="ht-audit">
          <div v-for="(log, i) in auditLog" :key="i" class="ha-row cp" @click="log.ts_code && openTradeDetail(log.ts_code)">
            <span class="tl-time">{{ log.time }}</span>
            <span class="ha-action">{{ log.action }}</span>
            <span class="ha-detail">{{ log.detail }}</span>
          </div>
        </div>

        <!-- 导出 -->
        <div class="st" style="margin-top:16px">📥 数据导出</div>
        <div class="ht-export">
          <ElButton size="small" @click="exportTradeLog">📥 导出交易日志(CSV)</ElButton>
          <ElButton size="small" @click="saveSnapshot">📸 保存快照</ElButton>
          <ElButton size="small" @click="openTradeAudit" :disabled="!timeline.length">🔍 交易审查</ElButton>
        </div>
      </div>
    </div>

    <!-- ==================== 运维Tab ==================== -->
    <div v-if="activeTab === 'ops'" class="mm-tab-content">
      <div class="mm-tab-scroll">
        <!-- 自动交易操作流 -->
        <div class="st">🤖 自动交易操作流 <ElButton size="small" @click="fetchAutoTrades">🔄</ElButton></div>
        <div v-if="!autoTrades.length" class="empty">暂无自动交易记录</div>
        <div v-else class="auto-trades-list">
          <div class="at-header"><span>时间</span><span>来源</span><span>操作</span><span>代码</span><span>名称</span><span>数量</span><span>价格</span><span>策略</span><span>原因</span></div>
          <div v-for="t in autoTrades" :key="t.order_id" class="at-row" :class="{ 'auto-trade': t.source === 'auto', 'manual-trade': t.source === 'manual' }">
            <span class="tl-time">{{ t.time }}</span>
            <span><ElTag size="small" :type="t.source === 'auto' ? 'primary' : 'warning'" style="font-size:10px">{{ t.source === 'auto' ? '🤖自动' : '✋手动' }}</ElTag></span>
            <span class="tl-action" :class="t.side === 'buy' ? 'buy' : 'sell'">{{ t.side === 'buy' ? '买' : '卖' }}</span>
            <span class="code">{{ t.ts_code }}</span>
            <span class="name">{{ t.stock_name }}</span>
            <span>{{ t.quantity }}股</span>
            <span>¥{{ t.price?.toFixed(2) }}</span>
            <span v-if="t.strategy" class="tl-strat">{{ strategyCN(t.strategy) }}</span><span v-else>-</span>
            <span class="text-tertiary" style="font-size:11px">{{ t.reason }}</span>
          </div>
        </div>

        <!-- 扫描器配置 -->
        <div class="st" style="margin-top:16px">⏱️ 扫描器配置 <ElButton size="small" @click="fetchScanConfig" :loading="scanConfigLoading">🔄</ElButton></div>
        <div v-if="scanConfig" class="scan-config-grid">
          <div class="sc-item"><span class="sc-label">自动扫描间隔</span><span class="sc-value">{{ scanConfig.scan_interval_desc || scanConfig.scan_interval_sec + '秒' }}</span></div>
          <div class="sc-item"><span class="sc-label">持仓检查间隔</span><span class="sc-value">{{ scanConfig.position_check_interval_sec }}秒</span></div>
          <div class="sc-item"><span class="sc-label">持仓快速检查</span><span class="sc-value">{{ scanConfig.position_check_fast_sec }}秒(接近止损)</span></div>
          <div class="sc-item"><span class="sc-label">持仓紧急检查</span><span class="sc-value">{{ scanConfig.position_check_critical_sec }}秒(触及止损)</span></div>
          <div class="sc-item"><span class="sc-label">信号过期时间</span><span class="sc-value">{{ scanConfig.signal_expire_desc || scanConfig.signal_expire_sec + '秒' }}</span></div>
          <div class="sc-item"><span class="sc-label">最大持仓数</span><span class="sc-value">{{ scanConfig.max_positions }}只</span></div>
          <div class="sc-item"><span class="sc-label">最大仓位比例</span><span class="sc-value">{{ (scanConfig.max_position_ratio * 100).toFixed(0) }}%</span></div>
          <div class="sc-item" v-if="scanConfig.current_smart_interval"><span class="sc-label">当前智能检查间隔</span><span class="sc-value">{{ scanConfig.current_smart_interval }}秒</span></div>
          <div class="sc-item"><span class="sc-label">交易模式</span><span class="sc-value">{{ scanConfig.trade_mode === 'simulated' ? '模拟' : scanConfig.trade_mode === 'gm' ? '掘金' : scanConfig.trade_mode }}</span></div>
          <div class="sc-item"><span class="sc-label">运行状态</span><span class="sc-value" :style="{ color: scanConfig.is_running ? 'var(--el-color-success)' : 'var(--el-color-danger)' }">{{ scanConfig.is_running ? '🟢 运行中' : '🔴 未启动' }}</span></div>
        </div>
        <div v-else class="empty" style="padding:8px">点击刷新加载扫描配置</div>

        <!-- 系统健康 -->
        <div class="st" style="margin-top:16px">💻 系统健康</div>
        <SystemHealth />

        <!-- 快捷操作 -->
        <div class="st" style="margin-top:16px">⚡ 快捷操作</div>
        <div class="ops-grid">
          <ElButton size="small" @click="manualScan" :loading="loading" :disabled="!isRunning">📡 扫描</ElButton>
          <ElButton size="small" type="warning" @click="forceScan" :loading="loading" :disabled="!isRunning">⚡ 强扫</ElButton>
          <ElButton size="small" @click="dailySettlement" :disabled="!isRunning">📅 日结</ElButton>
          <ElButton size="small" @click="openTradeAudit" :disabled="!timeline.length">🔍 审查</ElButton>
          <ElButton size="small" @click="fetchDailyReport(); dailyReportVisible = true">📈 复盘</ElButton>
          <ElButton size="small" @click="openWeeklyReport">📊 周报</ElButton>
          <ElButton size="small" @click="openLayerDebug" :loading="layerDebugLoading">🧪 9层调试</ElButton>
          <ElButton size="small" @click="loadCompare" :loading="compareLoading">📊 回测对比</ElButton>
          <ElButton size="small" @click="toggleDryRun">{{ dryRun ? '🔴 关闭调试' : '🔍 开启调试' }}</ElButton>
          <ElButton v-if="circuitBreakerPaused" size="small" type="danger" @click="resetCircuitBreaker">🔓 解熔断</ElButton>
          <ElButton size="small" @click="exportTradeLog">📥 导出日志</ElButton>
          <ElButton size="small" @click="saveSnapshot">📸 保存快照</ElButton>
          <ElButton size="small" type="warning" @click="resetAccount">🗑️ 清仓重置</ElButton>
          <ElButton size="small" @click="sellAllPositions">💰 一键清仓</ElButton>
        </div>

        <!-- 手动下单 -->
        <div class="st" style="margin-top:16px">🔧 手动下单</div>
        <div class="mf ops-mf">
          <ElInput v-model="manualTrade.ts_code" placeholder="代码 000001.SZ" size="small" @change="onManualCodeChange(manualTrade.ts_code)" />
          <div class="mf-row"><ElSelect v-model="manualTrade.side" size="small" style="width:70px"><ElOption label="买入" value="buy" /><ElOption label="卖出" value="sell" /></ElSelect><ElInputNumber v-model="manualTrade.quantity" :min="0" :step="100" placeholder="数量" size="small" style="flex:1" controls-position="right" /></div>
          <div class="mf-row"><ElInputNumber v-model="manualTrade.price" :min="0" :precision="2" :step="0.01" placeholder="价格(0=市价)" size="small" style="flex:1" controls-position="right" /><span v-if="manualQuote" class="mf-hint" @click="manualTrade.price = manualQuote.price">💰 填入现价</span></div>
          <ElButton type="primary" size="small" :disabled="!manualTrade.ts_code" @click="executeManualTrade" class="w-full">下单</ElButton>
          <div v-if="manualQuote" class="mf-q">💡 现价: ¥{{ manualQuote.price?.toFixed(2) }} <span v-if="manualQuote.pct_chg" :class="manualQuote.pct_chg >= 0 ? 'up' : 'down'">{{ manualQuote.pct_chg >= 0 ? '+' : '' }}{{ manualQuote.pct_chg.toFixed(2) }}%</span></div>
        </div>

        <!-- 交易时间线 -->
        <div class="st" style="margin-top:16px">⏱️ 交易时间线 ({{ timeline.length }}) <span v-if="cumulativePnl !== 0" :class="cumulativePnl >= 0 ? 'up' : 'down'" style="font-size:12px;margin-left:6px">累计{{ cumulativePnl >= 0 ? '+' : '' }}¥{{ cumulativePnl.toFixed(0) }}</span>
          <div style="display:inline-flex;align-items:center;gap:4px;margin-left:8px"><ElDatePicker v-model="historyDate" type="date" placeholder="日期" size="small" value-format="YYYY-MM-DD" style="width:130px" :disabled-date="(d: Date) => d > new Date()" /><ElButton size="small" @click="loadHistory" :loading="historyLoading" style="padding:2px 8px;font-size:11px">回放</ElButton></div>
        </div>
        <div v-if="!timeline.length && !historyData.length" class="empty">暂无交易</div>
        <div v-else class="ops-timeline">
          <div v-if="historyData.length" class="history-tag">📜 {{ historyDate }} 历史回放 ({{ historyData.length }}条)</div>
          <div v-for="(item, i) in historyData.length ? historyData : timeline" :key="i" class="tl-row cp" @click="item.action !== 'blocked' && openTradeDetail(item.ts_code)"><span class="tl-time">{{ item.time }}</span><span class="tl-action" :class="item.action === 'buy' ? 'buy' : item.action === 'sell' ? 'sell' : 'blocked'">{{ item.action === 'buy' ? '买' : item.action === 'sell' ? '卖' : '⛔' }}</span><span class="code">{{ item.ts_code }}</span><span class="name">{{ item.stock_name }}</span><template v-if="item.action !== 'blocked'"><span v-if="item.strategy" class="tl-strat">{{ strategyCN(item.strategy) }}</span><span class="tl-detail">{{ item.shares }}股@{{ item.price.toFixed(2) }}</span><span v-if="item.profit_pct !== undefined" :class="item.profit_pct >= 0 ? 'up' : 'down'">{{ item.profit_pct >= 0 ? '+' : '' }}{{ item.profit_pct.toFixed(1) }}%</span><span v-if="item.profit_amount != null" :class="item.profit_amount >= 0 ? 'up' : 'down'" class="tl-amt">{{ item.profit_amount >= 0 ? '+' : '' }}¥{{ item.profit_amount.toFixed(0) }}</span></template><span v-else class="tl-blocked-reason">{{ item.reason }}</span></div>
        </div>

        <!-- 历史订单 -->
        <div v-if="orders.length" class="st" style="margin-top:16px">📋 历史订单 ({{ orders.length }})</div>
        <div v-if="orders.length" class="ops-timeline">
          <div v-for="o in orders.slice(0, 50)" :key="o.order_id" class="tl-row cp" @click="openTradeDetail(o.ts_code)"><span class="tl-time">{{ o.trade_date?.slice(-4) || '' }} {{ o.create_time }}</span><span class="tl-action" :class="o.side === 'buy' ? 'buy' : 'sell'">{{ o.side === 'buy' ? '买' : '卖' }}</span><span class="code">{{ o.ts_code }}</span><span class="name">{{ o.stock_name }}</span><span class="tl-detail">{{ o.filled_qty }}股@{{ o.filled_price?.toFixed(2) || '0.00' }}</span><span class="text-tertiary-sm">{{ strategyCN(o.strategy) }}</span></div>
        </div>
      </div>
    </div>

    <!-- 【V50.1】信号链路追踪面板(可收起, 跨Tab) -->
    <div v-if="signalTraceVisible" class="mm-trace">
      <SignalTracePanel />
    </div>

    <!-- P2-10: 键盘快捷键 -->
    <KeyboardShortcuts
      @force-scan="forceScan"
      @manual-buy="() => { manualTrade.ts_code = ''; const input = $refs.codeInput as any; input?.focus() }"
      @sell-selected="() => { if (focusIndex >= 0 && focusIndex < sortedPositions.length) quickSell(sortedPositions[focusIndex]) }"
      @emergency-liquidate="emergencyLiquidate"
      @toggle-strategy="(i) => { const keys = ['halfway_chase','first_limit_up','dragon_head','limit_down_qiao']; if (strategies[keys[i]]) toggleStrat(strategies[keys[i]].id) }"
      @focus-prev="() => { if (focusIndex > 0) focusIndex-- }"
      @focus-next="() => { if (focusIndex < sortedPositions.length - 1) focusIndex++ }"
      @show-detail="() => { if (focusIndex >= 0 && focusIndex < sortedPositions.length) openTradeDetail(sortedPositions[focusIndex].ts_code) }"
    />

  </div>
</template>
<style scoped lang="scss">
.mm { height: 100%; display: flex; flex-direction: column; background: var(--bg-base); overflow: hidden; min-width: 0; }
/* 顶部状态栏 */
.mm-header { display: flex; align-items: center; gap: 8px; padding: 5px 12px; background: var(--bg-elevated); border-bottom: 1px solid var(--border-default); flex-shrink: 0; min-width: 0; overflow-x: auto; }
.cb-pause-btn { font-size: 12px; padding: 2px 8px; border-radius: 4px; border: 1px solid var(--warning); color: var(--warning); background: transparent; cursor: pointer; }
.cb-pause-btn:hover { background: var(--warning); color: var(--text-inverse); }
.hh-left { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
.hh-status { display: flex; align-items: center; gap: 5px; font-weight: 600; font-size: 13px; }
.hh-status .dot { width: 8px; height: 8px; border-radius: 50%; }
.hh-status.running .dot { background: var(--stock-down); animation: pulse 1.5s infinite; }
.hh-status.stopped .dot { background: var(--text-tertiary); }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
.hh-account { display: flex; align-items: center; gap: 8px; flex: 1; justify-content: center; }
.ha { display: inline-flex; align-items: baseline; gap: 2px; font-size: 12px; }
.hl { color: var(--text-tertiary); font-size: 10px; }
.hv { font-weight: 600; }
.hl { font-size: 10px; color: var(--text-tertiary); }
.hv { font-size: 13px; font-weight: 600; }
.hh-actions { display: flex; align-items: center; gap: 4px; flex-shrink: 0; }
.up { color: var(--stock-up); }
.down { color: var(--stock-down); }

/* 引导页 */
.mm-guide { flex: 1; overflow-y: auto; padding: 12px 16px; }
/* 横幅 */
.guide-banner { display: flex; align-items: center; justify-content: space-between; padding: 16px 20px; background: var(--bg-elevated); border-radius: 10px; margin-bottom: 12px; }
.gb-left { display: flex; align-items: center; gap: 14px; }
.gb-logo { font-size: 36px; }
.gb-title { font-size: 18px; font-weight: 700; }
.gb-sub { font-size: 12px; color: var(--text-secondary); margin-top: 2px; }
/* 卡片网格 */
.guide-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.gg-card { background: var(--bg-elevated); border-radius: 10px; overflow: hidden; }
.gg-span2 { grid-column: span 2; }
.gg-head { padding: 8px 14px; font-size: 13px; font-weight: 600; background: var(--bg-normal); border-bottom: 1px solid var(--border-light); }
.gg-icon { margin-right: 6px; }
.gg-body { padding: 10px 14px; }
.gg-compact { display: flex; flex-direction: column; gap: 6px; }
.gg-line { font-size: 12px; color: var(--text-secondary); }
.gg-params { display: flex; gap: 10px; }
.gg-p { font-size: 12px; font-weight: 500; }
.gg-pl { color: var(--text-tertiary); font-weight: 400; margin-right: 3px; }
/* 架构流程 */
.gf-flow { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.gf-tag { padding: 4px 10px; border-radius: 5px; font-size: 12px; font-weight: 500; background: var(--bg-normal); border: 1px solid var(--border-default); }
.gf-tag.gf-input { background: var(--el-color-primary-light-5); border-color: var(--el-color-primary-light-3); color: var(--el-color-primary-dark-2); }
.gf-tag.gf-output { background: rgba(0,180,42,0.1); border-color: rgba(0,180,42,0.3); color: #00b42a; }
.gf-arrow { color: var(--text-tertiary); font-size: 11px; }
/* 操作指南 */
.go-list { display: flex; flex-direction: column; gap: 6px; }
.go-row { display: flex; align-items: center; gap: 8px; font-size: 12px; line-height: 1.5; }
.sn { display: inline-flex; align-items: center; justify-content: center; width: 20px; height: 20px; border-radius: 50%; background: var(--el-color-primary); color: var(--text-inverse); font-size: 10px; font-weight: 600; flex-shrink: 0; }
/* 风控 */
.gr-grid { display: flex; flex-direction: column; gap: 5px; }
.gr-row { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.gr-k { color: var(--text-tertiary); min-width: 56px; flex-shrink: 0; }
.gr-v { font-weight: 500; font-family: 'JetBrains Mono', monospace; font-size: 11px; }
/* 快捷键 */
.gk-row { display: flex; flex-wrap: wrap; gap: 12px; }
.gk-g { font-size: 12px; display: flex; align-items: center; gap: 4px; }
.gk-g kbd { background: var(--bg-normal); border: 1px solid var(--border-default); border-radius: 4px; padding: 1px 6px; font-size: 11px; font-family: 'JetBrains Mono', monospace; }
/* 紧急平仓行内按钮 */
.emergency-btn-inline { font-size: 14px; padding: 2px 8px; border-radius: 4px; border: 1px solid var(--stock-up); color: var(--stock-up); background: transparent; cursor: pointer; }
.emergency-btn-inline:hover { background: var(--stock-up); color: var(--text-inverse); }
.emergency-btn-inline.disabled { opacity: 0.4; cursor: not-allowed; }

/* 3列主布局 */
.mm-trace { flex-shrink: 0; max-height: 45vh; overflow-y: auto; border-top: 1px solid var(--border-default); background: var(--bg-elevated); }
.mm-body { flex: 1; display: grid; grid-template-columns: minmax(180px, 2fr) minmax(200px, 3fr) minmax(300px, 5fr); gap: 0; overflow: hidden; min-width: 0; }
.mm-left, .mm-center, .mm-right { overflow-y: auto; padding: 10px; min-width: 0; min-height: 0; }
.mm-left { background: var(--bg-secondary); border-right: 1px solid var(--border-default); }
.mm-right { background: var(--bg-secondary); border-left: 1px solid var(--border-default); }

/* 区域标题 */
.st { font-size: 13px; font-weight: 600; color: var(--text-primary); margin-bottom: 8px; display: flex; align-items: center; }

/* 策略卡片 */
.sc { padding: 8px 10px; margin-bottom: 6px; background: var(--bg-elevated); border-radius: 6px; border: 1px solid var(--border-default); transition: border-color 0.2s; min-width: 0; }
.sc:hover { border-color: var(--text-muted); }
.sc.disabled { opacity: 0.5; }
.sc-top { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; min-width: 0; }
.sc-icon { font-size: 16px; }
.sc-name { font-size: 13px; font-weight: 600; flex: 1 1 auto; min-width: 0; }
.sc-arrow { font-size: 10px; color: var(--text-tertiary); margin-left: 4px; }
.sc-desc { font-size: 11px; color: var(--text-tertiary); margin: 2px 0 4px 24px; overflow-wrap: break-word; }
.sc-params { margin-left: 24px; min-width: 0; }
.pm { display: flex; justify-content: space-between; font-size: 11px; gap: 4px; min-width: 0; }
.pk { color: var(--text-tertiary); white-space: nowrap; }
.pv { color: var(--text-secondary); font-weight: 500; overflow-wrap: break-word; }

/* 快捷操作 */
.qa { display: flex; flex-direction: column; gap: 4px; min-width: 0; }

/* 手动下单 */
.mf { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.mf-row { display: flex; gap: 4px; min-width: 0; flex-wrap: wrap; }
.mf-q { font-size: 11px; color: var(--stock-down); padding: 2px 0; }
.mf-hint { font-size: 11px; color: var(--el-color-primary); cursor: pointer; padding: 0 4px; white-space: nowrap; }

/* 信号列表 */
.sl { overflow-y: auto; min-width: 0; }
.sl-sm { max-height: 200px; }
.sig-row { display: flex; align-items: center; gap: 5px; padding: 4px 8px; margin-bottom: 2px; background: var(--bg-elevated); border-radius: 4px; border: 1px solid var(--border-default); font-size: 12px; flex-wrap: wrap; min-width: 0; }
.sig-row:hover { border-color: var(--el-color-primary); }
.factor { font-size: 11px; color: var(--text-tertiary); background: var(--bg-tertiary); padding: 1px 4px; border-radius: 3px; white-space: nowrap; }
.reason { font-size: 11px; color: var(--text-tertiary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 200px; min-width: 0; }
.sig-row .el-button { padding: 1px 6px; font-size: 11px; }

/* 涨停池 */
.limit-row { display: flex; align-items: center; gap: 6px; padding: 3px 8px; font-size: 12px; border-bottom: 1px solid var(--border-light); flex-wrap: wrap; min-width: 0; }
.lb-tag { font-size: 10px; color: var(--stock-up); background: var(--stock-up-bg); padding: 1px 4px; border-radius: 3px; }
.fd-tag { font-size: 10px; color: var(--el-color-warning); background: var(--warning-bg); padding: 1px 4px; border-radius: 3px; }

/* 持仓卡片 */
.pos-card { padding: 8px 10px; margin-bottom: 6px; background: var(--bg-elevated); border-radius: 6px; border: 1px solid var(--border-default); min-width: 0; }
.pos-card:hover { border-color: var(--el-color-primary); }
.pos-top { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; min-width: 0; }
.pct { margin-left: auto; font-weight: 700; font-size: 14px; transition: transform 0.3s; }
.pos-card:hover .pct { transform: scale(1.05); }
.pos-info { display: flex; gap: 8px; font-size: 11px; color: var(--text-secondary); flex-wrap: wrap; min-width: 0; }
.pos-risk-row { margin-top: 4px; }
.risk-track { height: 4px; background: var(--bg-muted); border-radius: 2px; overflow: hidden; }
.risk-fill { height: 100%; border-radius: 2px; transition: width 0.3s; }
.risk-fill.safe { background: linear-gradient(90deg, var(--warning), var(--success)); }
.risk-fill.warning { background: linear-gradient(90deg, var(--warning), var(--stock-up)); }
.risk-fill.danger { background: var(--stock-up); animation: risk-pulse 1s infinite; }
.risk-labels-row { display: flex; justify-content: space-between; font-size: 10px; margin-top: 2px; }
@keyframes risk-pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }
.t1-tag { font-size: 10px; color: var(--el-color-warning); background: var(--warning-bg); padding: 1px 4px; border-radius: 3px; font-weight: 600; }
.rl { padding: 1px 5px; border-radius: 3px; font-weight: 500; }
.rl.stop { color: var(--stock-up); background: var(--stock-up-bg); }
.rl.stop-price { color: var(--stock-up); background: var(--stock-up-bg); font-weight: 700; }
.rl.profit { color: var(--stock-down); background: var(--stock-down-bg); }
.rl.profit-price { color: var(--stock-down); background: var(--stock-down-bg); font-weight: 700; }
.rd { color: var(--text-tertiary); }
.rd.danger { color: var(--stock-up); font-weight: 600; animation: blink 1s infinite; }
@keyframes blink { 50% { opacity: 0.5; } }

/* 统计 */
.stats { display: grid; grid-template-columns: repeat(auto-fill, minmax(60px, 1fr)); gap: 6px; }
.si { text-align: center; padding: 6px; background: var(--bg-elevated); border-radius: 6px; min-width: 0; }
.sv { font-size: 18px; font-weight: 700; }
.sl2 { font-size: 11px; color: var(--text-tertiary); }

/* 底部时间线 */
.mm-footer { flex-shrink: 0; border-top: 1px solid var(--border-default); padding: 6px 16px; background: var(--bg-elevated); min-width: 0; }
.tl-body { display: flex; gap: 16px; flex-wrap: wrap; min-width: 0; }
.tl-col { flex: 1 1 200px; overflow-y: auto; max-height: 260px; min-width: 0; }
.tl-col + .tl-col { border-left: 1px solid var(--border-default); padding-left: 16px; }
.tl-row { display: flex; align-items: center; gap: 6px; padding: 3px 0; font-size: 12px; border-bottom: 1px solid var(--border-light); cursor: pointer; flex-wrap: wrap; min-width: 0; }
.tl-row:hover { background: var(--bg-base); }
.tl-time { font-size: 11px; color: var(--text-tertiary); min-width: 40px; }
.tl-action { font-size: 11px; font-weight: 600; min-width: 20px; }
.tl-action.buy { color: var(--stock-up); }
.tl-action.sell { color: var(--stock-down); }
.tl-action.blocked { color: var(--text-tertiary, var(--text-tertiary)); font-size: 11px; }
.tl-strat { font-size: 10px; color: var(--el-color-primary); background: var(--bg-tertiary); padding: 1px 5px; border-radius: 3px; white-space: nowrap; }
.tl-blocked-reason { font-size: 12px; color: var(--text-tertiary, var(--text-tertiary)); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 300px; }
.tl-detail { font-size: 11px; color: var(--text-secondary); }
.tl-reason { font-size: 11px; color: var(--text-tertiary); max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.history-tag { font-size: 12px; color: var(--el-color-primary); background: var(--info-bg); padding: 4px 8px; border-radius: 4px; margin-bottom: 4px; font-weight: 600; }

/* 通用 */
.code { font-size: 12px; font-weight: 600; color: var(--text-primary); font-family: monospace; }
.name { font-size: 12px; color: var(--text-secondary); }
.empty { text-align: center; color: var(--text-muted); font-size: 12px; padding: 20px 0; }

/* 【P1-1】关键因子标签 */
.kf { color: var(--el-color-warning); background: var(--warning-bg); font-weight: 600; }

/* 【P1-2】持仓市值和盈亏金额 */
.mv { color: var(--text-tertiary); font-size: 11px; }
.pamt { font-weight: 700; font-size: 12px; }

/* 【P1-5】数据源健康指示器 */
.ds-indicator { display: inline-flex; gap: 4px; margin-left: 4px; }
.ds-dot { font-size: 10px; padding: 1px 4px; border-radius: 3px; font-weight: 600; cursor: help; }
.ds-dot.ok { color: var(--stock-down); background: var(--stock-down-bg); }
.ds-dot.err { color: var(--stock-up); background: var(--stock-up-bg); }

/* 【P1-3】时间线盈亏金额 */
.tl-amt { font-size: 11px; font-weight: 700; min-width: 50px; text-align: right; }

/* 交易详情弹窗 */
.td { font-size: 13px; }
.td-sec { margin-bottom: 14px; padding: 10px; background: var(--bg-muted); border-radius: 8px; border: 1px solid var(--border-default); min-width: 0; }
.td-t { font-size: 14px; font-weight: 600; margin-bottom: 6px; color: var(--text-primary); }
.td-g { display: grid; grid-template-columns: repeat(auto-fill, minmax(100px, 1fr)); gap: 6px; margin-bottom: 4px; }
.td-i { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.td-l { font-size: 10px; color: var(--text-tertiary); }
.td-v { font-size: 13px; font-weight: 500; }
.td-r { font-size: 12px; color: var(--text-secondary); margin: 4px 0; padding: 4px 6px; background: var(--bg-elevated); border-radius: 4px; border-left: 3px solid var(--el-color-primary); }
.td-c { font-size: 12px; font-weight: 600; color: var(--text-secondary); margin-top: 4px; }
.cl { font-size: 11px; color: var(--text-secondary); padding: 1px 0 1px 10px; font-family: monospace; }
.td-e { color: var(--text-muted); font-size: 12px; }

/* 审查弹窗 */
.al { max-height: 500px; overflow-y: auto; }
.ah { display: grid; grid-template-columns: minmax(60px, 1fr) minmax(50px, 1fr) minmax(80px, 1.2fr) minmax(80px, 1.2fr) minmax(50px, 1fr) minmax(50px, 1fr); gap: 4px; padding: 6px 0; font-size: 12px; font-weight: 600; color: var(--text-tertiary); border-bottom: 1px solid var(--border-default); }
.ar { display: grid; grid-template-columns: minmax(60px, 1fr) minmax(50px, 1fr) minmax(80px, 1.2fr) minmax(80px, 1.2fr) minmax(50px, 1fr) minmax(50px, 1fr); gap: 4px; padding: 6px 0; font-size: 12px; align-items: center; border-bottom: 1px solid var(--border-light); cursor: pointer; overflow: hidden; }
.ar:hover { background: var(--bg-hover); }

/* 回测对比 */
.cl-table { max-height: 400px; overflow-y: auto; }
.cl-h { display: grid; grid-template-columns: repeat(8, minmax(50px, 1fr)); gap: 4px; padding: 6px 0; font-size: 12px; font-weight: 600; color: var(--text-tertiary); border-bottom: 1px solid var(--border-default); }
.cl-r { display: grid; grid-template-columns: repeat(8, minmax(50px, 1fr)); gap: 4px; padding: 6px 0; font-size: 12px; align-items: center; border-bottom: 1px solid var(--border-light); overflow: hidden; }

/* 响应式 */
@media (max-width: 1400px) {
  .mm-body { grid-template-columns: minmax(160px, 2fr) minmax(180px, 3fr) minmax(280px, 4fr); }
  .pos-info { flex-wrap: wrap; gap: 4px; }
  .tl-body { flex-wrap: wrap; }
  .tl-col { min-width: 180px; }
}
@media (max-width: 1024px) {
  .mm-body { grid-template-columns: 1fr; }
  .mm-left, .mm-right { border: none; border-bottom: 1px solid var(--border-default); }
  .tl-body { flex-direction: column; }
  .tl-col { max-height: 180px; }
  .tl-col + .tl-col { border-left: none; padding-left: 0; border-top: 1px solid var(--border-default); padding-top: 8px; }
}
@media (max-width: 1024px) {
  }

/* 【调试增强】9层调试弹窗 */
.layer-debug { font-size: 13px; }
.ld-header { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; font-size: 12px; color: var(--text-secondary); }
.ld-title { font-size: 13px; font-weight: 600; color: var(--text-primary); margin-bottom: 6px; }
.ld-pipeline { padding: 10px; background: var(--bg-muted); border-radius: 8px; border: 1px solid var(--border-default); margin-bottom: 10px; }
.ld-layers { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 4px; margin-bottom: 6px; }
.ld-layer { display: flex; align-items: center; gap: 4px; font-size: 11px; padding: 3px 6px; background: var(--bg-elevated); border-radius: 4px; border: 1px solid var(--border-default); }
.ld-on { color: var(--stock-down); }
.ld-off { color: var(--text-tertiary); }
.ld-name { color: var(--text-secondary); }
.ld-sentiment { font-size: 12px; color: var(--el-color-primary); padding: 4px 0; }
.ld-traces { max-height: 400px; overflow-y: auto; }
.ld-trace-card { padding: 8px 10px; margin-bottom: 6px; background: var(--bg-elevated); border-radius: 6px; border: 1px solid var(--border-default); }
.ld-trace-top { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
.ld-trace-layers { padding-left: 10px; }
.ld-trace-line { font-size: 11px; color: var(--text-secondary); padding: 1px 0; font-family: monospace; }

/* 【调试增强】扫描Trace弹窗 */
.scan-trace { font-size: 13px; }
.st-header { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
.st-reason { font-size: 12px; color: var(--text-secondary); padding: 4px 6px; background: var(--bg-elevated); border-radius: 4px; border-left: 3px solid var(--el-color-primary); margin-bottom: 6px; }
.st-age { font-size: 11px; color: var(--text-tertiary); margin-bottom: 6px; }
.st-trace, .st-detail, .st-factors { padding: 10px; background: var(--bg-muted); border-radius: 8px; border: 1px solid var(--border-default); margin-bottom: 8px; }
.st-title { font-size: 13px; font-weight: 600; color: var(--text-primary); margin-bottom: 4px; }
.st-line { font-size: 11px; color: var(--text-secondary); padding: 1px 0; font-family: monospace; }
.st-fg { display: grid; grid-template-columns: repeat(auto-fill, minmax(100px, 1fr)); gap: 4px; }
.st-fi { display: flex; flex-direction: column; padding: 3px 6px; background: var(--bg-elevated); border-radius: 4px; }
.st-fl { font-size: 10px; color: var(--text-tertiary); }
.st-fv { font-size: 13px; font-weight: 500; }

/* 【P1-4】信号过期倒计时 */
.expire-tag { font-size: 11px; color: var(--el-color-primary); background: var(--info-bg); padding: 1px 5px; border-radius: 3px; font-weight: 600; }
.expire-tag.urgent { color: var(--stock-up); background: var(--stock-up-bg); animation: blink 1s infinite; }

/* 【P1-6】复盘报告弹窗 */
.dr { font-size: 13px; }
.dr-sec { margin-bottom: 14px; padding: 10px; background: var(--bg-muted); border-radius: 8px; border: 1px solid var(--border-default); }
.dr-t { font-size: 14px; font-weight: 600; margin-bottom: 6px; color: var(--text-primary); }
.dr-g { display: grid; grid-template-columns: repeat(auto-fill, minmax(100px, 1fr)); gap: 6px; margin-bottom: 4px; }
.dr-i { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.dr-l { font-size: 10px; color: var(--text-tertiary); }
.dr-v { font-size: 13px; font-weight: 500; }
.dr-p { display: flex; align-items: center; gap: 8px; padding: 3px 0; font-size: 12px; border-bottom: 1px solid var(--border-light); }

/* 周报弹窗 */
.wr { font-size: 13px; }
.wr-sec { margin-bottom: 14px; padding: 10px; background: var(--bg-muted); border-radius: 8px; border: 1px solid var(--border-default); }
.wr-t { font-size: 14px; font-weight: 600; margin-bottom: 6px; color: var(--text-primary); }
.wr-g { display: grid; grid-template-columns: repeat(auto-fill, minmax(100px, 1fr)); gap: 6px; margin-bottom: 4px; }
.wr-i { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.wr-l { font-size: 10px; color: var(--text-tertiary); }
.wr-v { font-size: 14px; font-weight: 600; }
.wr-p { display: flex; align-items: center; gap: 8px; padding: 3px 0; font-size: 12px; border-bottom: 1px solid var(--border-light); }
.wr-day { display: flex; align-items: center; gap: 10px; padding: 4px 0; font-size: 12px; border-bottom: 1px solid var(--border-light); }
.wr-date { font-weight: 600; color: var(--text-primary); min-width: 80px; }

/* === Extracted utility classes === */
.w-full { width: 100%; }
.ml-auto { margin-left: auto; }
.mt-10 { margin-top: 10px; }
.cp { cursor: pointer; }
.btn-xs { padding: 1px 6px; font-size: 11px; }
.tag-solid { color: var(--text-inverse); border: none; }
.fs-10 { font-size: 10px; }

/* === Dark toggle button === */
.dark-toggle { font-size: 16px; cursor: pointer; padding: 0 4px; user-select: none; }

/* === Mini bar (PnL progress) === */
.mini-bar { display: inline-block; width: 40px; height: 4px; background: var(--border-default); border-radius: 2px; vertical-align: middle; margin-left: 4px; }
.mini-bar-fill { display: block; height: 100%; border-radius: 2px; transition: width 0.3s; }

/* === Quick action groups === */
.qa-group { margin-bottom: 2px; }
.qa-label { font-size: 10px; color: var(--text-tertiary); margin-top: 4px; margin-bottom: 2px; padding-left: 2px; }


/* === Utility classes for inline style replacement === */
.text-stock-up { color: var(--stock-up) !important; }
.text-stock-down { color: var(--stock-down) !important; }
.text-tertiary { color: var(--text-tertiary); }
.text-tertiary-sm { font-size: 11px; color: var(--text-tertiary); }

/* === Mini bar fill variants === */
.mini-bar-fill.bar-up { background: var(--stock-up) !important; }
.mini-bar-fill.bar-down { background: var(--stock-down) !important; }

/* ============================================ */

/* 【V50.1】交易详情弹窗-结构化卡片 */
.td2 { font-size: 13px; }
.td2-sec { margin-bottom: 16px; padding: 12px; background: var(--bg-secondary); border-radius: 8px; }
.td2-title { font-size: 14px; font-weight: 600; margin-bottom: 10px; color: var(--text-primary, var(--text-primary)); }
.td2-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 8px; }
.td2-card { padding: 8px 10px; background: var(--bg-elevated, var(--text-inverse)); border-radius: 6px; border: 1px solid var(--border-default); }
.td2-card.sm { padding: 6px 8px; }
.td2-label { font-size: 11px; color: var(--text-tertiary, var(--text-tertiary)); margin-bottom: 2px; }
.td2-val { font-size: 14px; font-weight: 600; color: var(--text-primary, var(--text-primary)); }
.td2-reason { padding: 8px 10px; margin: 8px 0; background: var(--bg-elevated, var(--text-inverse)); border-radius: 6px; border-left: 3px solid var(--el-color-primary); font-size: 13px; color: var(--text-secondary, var(--text-secondary)); }
.td2-chain { margin-top: 8px; }
.td2-chain-title { font-size: 12px; font-weight: 600; color: var(--text-secondary, var(--text-secondary)); margin: 8px 0 6px; padding-left: 4px; border-left: 2px solid var(--el-color-primary); }
.td2-pipeline { display: flex; flex-direction: column; gap: 3px; }
.td2-pipe-step { display: flex; align-items: center; gap: 6px; padding: 4px 8px; background: var(--bg-elevated, var(--text-inverse)); border-radius: 4px; font-size: 12px; }
.td2-pipe-step.passed { border-left: 2px solid var(--success); }
.td2-pipe-icon { font-size: 12px; flex-shrink: 0; }
.td2-pipe-name { font-weight: 500; min-width: 100px; color: var(--text-primary, var(--text-primary)); }
.td2-pipe-detail { color: var(--text-tertiary, var(--text-tertiary)); font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.td2-factors { display: flex; flex-wrap: wrap; gap: 6px; }
.td2-factor { padding: 4px 8px; background: var(--bg-elevated, var(--text-inverse)); border-radius: 4px; font-size: 12px; }
.td2-fk { color: var(--text-tertiary, var(--text-tertiary)); margin-right: 4px; }
.td2-fv { font-weight: 500; color: var(--text-primary, var(--text-primary)); }
.td2-empty { text-align: center; padding: 16px; color: var(--text-tertiary, var(--text-tertiary)); font-size: 13px; }

/* 风控状态栏 */
.risk-bar { background: var(--bg-elevated); border-bottom: 1px solid var(--border-default); flex-shrink: 0; transition: background 0.3s; }
.risk-bar.critical { background: rgba(245, 108, 108, 0.12); border-bottom-color: var(--stock-up); }
.risk-bar.warning { background: rgba(230, 162, 60, 0.08); border-bottom-color: var(--el-color-warning); }
.rb-main { display: flex; align-items: center; justify-content: space-between; padding: 6px 16px; gap: 12px; flex-wrap: wrap; }
.rb-left { display: flex; align-items: center; gap: 8px; }
.rb-right { display: flex; align-items: center; gap: 8px; }
.rb-light { font-size: 14px; line-height: 1; }
.rb-label { font-size: 12px; font-weight: 600; color: var(--text-primary); }
.rb-metric { display: flex; align-items: center; gap: 4px; font-size: 11px; }
.rb-ml { color: var(--text-tertiary); }
.rb-mv { font-weight: 600; color: var(--text-secondary); }
.rb-progress { display: inline-block; width: 60px; height: 6px; background: var(--border-default); border-radius: 3px; overflow: hidden; vertical-align: middle; }
.rb-progress-fill { display: block; height: 100%; background: var(--stock-down); border-radius: 3px; transition: width 0.3s; }
.rb-progress-fill.danger { background: var(--stock-up); }
.rb-arrow { font-size: 10px; color: var(--text-tertiary); margin-left: 4px; }
.rb-ds { display: flex; gap: 4px; }
.rb-ds-dot { font-size: 10px; }
.rb-ds-dot.ok { color: var(--stock-down); }
.rb-ds-dot.err { color: var(--stock-up); }

/* 紧急平仓按钮 */
.emergency-btn { position: relative; display: inline-flex; align-items: center; justify-content: center; padding: 4px 14px; border: 2px solid var(--stock-up); border-radius: 6px; background: transparent; cursor: pointer; font-size: 12px; font-weight: 700; color: var(--stock-up); transition: all 0.2s; }
.emergency-btn.active { animation: emergency-pulse 1.5s infinite; }
.emergency-btn.disabled { opacity: 0.4; cursor: not-allowed; animation: none; }
.emergency-btn:not(.disabled):hover { background: var(--stock-up); color: var(--text-inverse); }
.emergency-text { white-space: nowrap; }
@keyframes emergency-pulse { 0%, 100% { box-shadow: 0 0 0 0 rgba(245, 108, 108, 0.5); } 50% { box-shadow: 0 0 0 8px rgba(245, 108, 108, 0); } }

/* 风控详情 */
.rb-detail { padding: 8px 16px 10px; border-top: 1px solid var(--border-light); }
.rb-detail-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 6px; margin-bottom: 6px; }
.rb-di { display: flex; flex-direction: column; gap: 1px; }
.rb-dl { font-size: 10px; color: var(--text-tertiary); }
.rb-dv { font-size: 13px; font-weight: 600; color: var(--text-secondary); }
.rb-dv.ok { color: var(--stock-down); }
.rb-dv.warn { color: var(--el-color-warning); }
.rb-dv.crit { color: var(--stock-up); }
.rb-ds-detail { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 11px; }
.rb-ds-item { padding: 1px 6px; border-radius: 3px; font-weight: 500; }
.rb-ds-item.ok { color: var(--stock-down); background: var(--stock-down-bg); }
.rb-ds-item.err { color: var(--stock-up); background: var(--stock-up-bg); }

/* P1: 持仓价格行 */
.pos-prices-row { display: flex; align-items: center; gap: 8px; padding: 2px 0; font-size: 11px; flex-wrap: wrap; }
.pp-sl { color: var(--stock-up); }
.pp-tp { color: var(--stock-down); }
.pp-trail { color: var(--el-color-warning); }
.pp-risk { font-weight: 600; }
.pp-risk.high { color: var(--stock-up); }
.pp-risk.elevated { color: var(--el-color-warning); }
.pp-risk.low { color: var(--stock-down); }
.risk-labels-row .rl.trail { color: var(--el-color-warning); font-size: 10px; }

/* P1: 快捷操作常用行 */
.qa-row2 { display: flex; gap: 4px; margin-bottom: 4px; }
.qa-row2 .ElButton, .qa-row2 > button { flex: 1; }
.qa-more { margin-top: 6px; }
.qa-more-toggle { cursor: pointer; font-size: 12px; color: var(--text-tertiary); padding: 4px 0; user-select: none; }
.qa-more-toggle:hover { color: var(--text-primary); }
.qa-more[open] .qa-more-toggle { color: var(--text-primary); margin-bottom: 4px; }

/* P1: 追踪止损区域 */
.td2-trail-section { margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--border-default); }
.td2-trail-ctrl { display: flex; align-items: center; gap: 8px; margin-top: 8px; }

/* 盈亏曲线 */
.pnl-chart-wrap { background: var(--bg-elevated); border-radius: 6px; padding: 4px; margin-top: 4px; }
/* 【Phase4.1:数据新鲜度+健康分数】 */
.rb-freshness { font-size: 10px; margin: 0 4px; }
.rb-freshness.green { color: #52c41a; }
.rb-freshness.yellow { color: #faad14; }
.rb-freshness.red { color: #ff4d4f; }
.rb-score { font-size: 11px; font-weight: 600; color: var(--text-secondary); background: var(--bg-elevated); border-radius: 4px; padding: 1px 5px; margin-left: 4px; }

/* Tab导航栏 */
.mm-tab-bar {
  display: flex;
  gap: 2px;
  padding: 0 16px;
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--border-default);
  flex-shrink: 0;
}
.mm-tab-bar .tab-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: all 0.2s;
  white-space: nowrap;
}
.mm-tab-bar .tab-btn:hover {
  color: var(--text-primary);
  background: var(--bg-hover);
}
.mm-tab-bar .tab-btn.active {
  color: var(--el-color-primary);
  border-bottom-color: var(--el-color-primary);
  font-weight: 600;
}
.tab-icon { font-size: 15px; }
.tab-text { display: flex; flex-direction: column; gap: 1px; }
.tab-label { font-size: 13px; line-height: 1.2; }
.tab-desc { font-size: 10px; color: var(--text-tertiary); line-height: 1; }
.tab-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  font-size: 10px;
  font-weight: 600;
  border-radius: 9px;
  background: var(--el-color-primary);
  color: var(--text-inverse);
  padding: 0 5px;
}
.tab-badge-danger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  font-size: 10px;
  font-weight: 700;
  border-radius: 9px;
  background: var(--stock-up);
  color: var(--text-inverse);
  padding: 0 5px;
}

/* Tab内容区 */
.mm-tab-content { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.mm-tab-scroll { flex: 1; overflow-y: auto; padding: 12px 16px; }

/* 历史Tab */
.ht-timeline { display: flex; flex-direction: column; gap: 2px; }
.ht-orders { border: 1px solid var(--border-default); border-radius: 6px; overflow: hidden; }
.ho-header { display: grid; grid-template-columns: 100px 40px 80px 1fr 60px 70px 60px; gap: 4px; padding: 6px 10px; background: var(--bg-muted); font-size: 11px; color: var(--text-tertiary); font-weight: 600; }
.ho-row { display: grid; grid-template-columns: 100px 40px 80px 1fr 60px 70px 60px; gap: 4px; padding: 4px 10px; font-size: 12px; border-bottom: 1px solid var(--border-default); align-items: center; }
.ho-row:hover { background: var(--bg-muted); }
.ht-closed { border: 1px solid var(--border-default); border-radius: 6px; overflow: hidden; }
.hc-header { display: grid; grid-template-columns: 80px 1fr 60px 70px 70px 70px 60px; gap: 4px; padding: 6px 10px; background: var(--bg-muted); font-size: 11px; color: var(--text-tertiary); font-weight: 600; }
.hc-row { display: grid; grid-template-columns: 80px 1fr 60px 70px 70px 70px 60px; gap: 4px; padding: 4px 10px; font-size: 12px; border-bottom: 1px solid var(--border-default); align-items: center; cursor: pointer; }
.hc-row:hover { background: var(--bg-muted); }
.hc-win { border-left: 3px solid var(--stock-up); }
.hc-loss { border-left: 3px solid var(--stock-down); }
.ht-audit { display: flex; flex-direction: column; gap: 2px; }
.ha-row { display: flex; align-items: center; gap: 8px; padding: 3px 0; font-size: 12px; }
.ha-action { color: var(--el-color-primary); font-weight: 600; min-width: 60px; }
.ha-detail { color: var(--text-secondary); }
.ht-export { display: flex; gap: 8px; flex-wrap: wrap; }
mm-tab-content {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.mm-tab-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

/* 绩效Tab */
.pnl-chart-wrap-lg {
  background: var(--bg-elevated);
  border-radius: 8px;
  padding: 8px;
  margin-bottom: 12px;
  border: 1px solid var(--border-default);
}

/* 风控Tab */
.risk-overview { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
.ro-card { display: flex; align-items: center; gap: 6px; padding: 4px 10px; border: 1px solid var(--border-default); border-radius: 6px; font-size: 12px; background: var(--bg-normal); }
.ro-label { color: var(--text-tertiary); }
.ro-value { font-weight: 600; font-family: 'JetBrains Mono', monospace; }
.risk-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 8px;
}
.risk-card {
  background: var(--bg-elevated);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  padding: 10px 12px;
}
.rc-top {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
}
.rc-detail {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px 12px;
  font-size: 12px;
}
.rc-row {
  display: flex;
  justify-content: space-between;
}
.rc-row span:first-child { color: var(--text-tertiary); }

/* 复盘Tab */
.review-header { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
.review-tabs { display: flex; gap: 2px; }
.review-tab { padding: 6px 14px; border: 1px solid var(--border-default); border-radius: 6px; background: var(--bg-elevated); color: var(--text-secondary); font-size: 13px; cursor: pointer; transition: all 0.2s; }
.review-tab:hover { background: var(--bg-hover); }
.review-tab.active { background: var(--el-color-primary); color: var(--text-inverse); border-color: var(--el-color-primary); }
.review-summary-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 8px; }
.rsc { background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 8px; padding: 10px 12px; text-align: center; }
.rsc-label { font-size: 11px; color: var(--text-tertiary); margin-bottom: 4px; }
.rsc-value { font-size: 16px; font-weight: 600; }
.strategy-contrib { display: flex; flex-direction: column; gap: 6px; }
.sc-bar-row { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.sc-bar-label { width: 70px; text-align: right; flex-shrink: 0; }
.sc-bar-track { flex: 1; height: 16px; background: var(--bg-secondary); border-radius: 4px; overflow: hidden; }
.sc-bar-fill { height: 100%; border-radius: 4px; transition: width 0.3s; }
.sc-bar-fill.up { background: var(--stock-down); }
.sc-bar-fill.down { background: var(--stock-up); }
.sc-bar-value { width: 70px; font-weight: 600; }
.attribution-card { background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 8px; padding: 10px 12px; margin-bottom: 6px; }
.attr-top { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
.attr-detail { display: grid; grid-template-columns: 1fr 1fr; gap: 2px 16px; font-size: 12px; }
.attr-row { display: flex; justify-content: space-between; }
.attr-row span:first-child { color: var(--text-tertiary); }
.weekly-daily-table { font-size: 12px; }
.wdt-header, .wdt-row { display: grid; grid-template-columns: 90px 1fr 60px 60px 80px; gap: 8px; padding: 4px 0; }
.wdt-header { font-weight: 600; color: var(--text-tertiary); border-bottom: 1px solid var(--border-default); }
.eq-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 8px; }
.eq-card { background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 8px; padding: 10px 12px; text-align: center; }
.eq-label { font-size: 11px; color: var(--text-tertiary); margin-bottom: 4px; }
.eq-value { font-size: 15px; font-weight: 600; }
.lb-table { font-size: 12px; }
.lb-header, .lb-row { display: grid; grid-template-columns: 70px 60px 60px 60px 60px 70px 60px 60px; gap: 4px; padding: 3px 0; }
.lb-header { font-weight: 600; color: var(--text-tertiary); border-bottom: 1px solid var(--border-default); }
.suggestions { display: flex; flex-direction: column; gap: 6px; }
.suggestion { padding: 8px 12px; border-radius: 6px; font-size: 12px; }
.suggestion.warn { background: rgba(250,173,20,0.1); border: 1px solid rgba(250,173,20,0.3); }
.suggestion.info { background: rgba(22,119,255,0.1); border: 1px solid rgba(22,119,255,0.3); }

/* 盘前竞价Tab */
.pm-status-bar { display: flex; align-items: center; gap: 12px; padding: 12px 16px; background: var(--bg-elevated); border-radius: 8px; border: 1px solid var(--border-default); margin-bottom: 12px; }
.pm-status-icon { font-size: 28px; }
.pm-status-title { font-size: 15px; font-weight: 600; }
.pm-status-sub { font-size: 11px; color: var(--text-tertiary); }
.pm-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.pm-section { background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 8px; padding: 10px 12px; }
.pm-candidate, .pm-signal { display: flex; align-items: center; gap: 6px; padding: 4px 0; font-size: 12px; border-bottom: 1px solid var(--border-default); }
.pm-candidate:last-child, .pm-signal:last-child { border-bottom: none; }

/* 扫描追踪Tab */
.scan-strip { display: flex; flex-wrap: wrap; gap: 4px; }
.scan-chip { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 6px; font-size: 11px; cursor: pointer; border: 1px solid var(--border-default); background: var(--bg-elevated); transition: all 0.15s; }
.scan-chip:hover { background: var(--bg-hover); border-color: var(--el-color-primary-light-5); }
.scan-chip.active { background: var(--el-color-primary-light-9); border-color: var(--el-color-primary); }
.sc-time { color: var(--text-tertiary); font-family: 'JetBrains Mono', monospace; }
.sc-type { font-weight: 600; padding: 1px 5px; border-radius: 3px; font-size: 10px; }
.sc-type.full { background: rgba(0,180,42,0.12); color: #00b42a; }
.sc-type.quick { background: rgba(22,93,255,0.12); color: #165dff; }
.sc-stats { color: var(--text-secondary); }
.scan-funnel-bar { display: flex; align-items: center; gap: 2px; flex-wrap: wrap; padding: 8px 12px; background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 8px; margin-top: 8px; }
.fb-step { display: inline-flex; flex-direction: column; align-items: center; padding: 4px 8px; border-radius: 5px; font-size: 11px; min-width: 48px; }
.fb-step.passed { background: rgba(0,180,42,0.06); }
.fb-name { font-weight: 600; font-size: 10px; color: var(--text-secondary); white-space: nowrap; }
.fb-nums { font-weight: 700; font-family: 'JetBrains Mono', monospace; }
.fb-rej { color: var(--stock-down); font-weight: 400; font-size: 10px; }
.fb-arrow { color: var(--text-tertiary); font-size: 12px; }
.fb-summary { margin-left: auto; font-size: 11px; color: var(--text-tertiary); }
.funnel { display: flex; flex-direction: column; gap: 2px; }
.funnel-step { display: flex; align-items: center; gap: 8px; padding: 6px 10px; border-radius: 6px; font-size: 12px; border: 1px solid var(--border-default); }
.funnel-step.passed { background: rgba(0,180,42,0.06); border-color: rgba(0,180,42,0.2); }
.funnel-step.rejected { background: rgba(245,63,63,0.06); border-color: rgba(245,63,63,0.2); }
.fn-label { font-weight: 600; width: 80px; }
.fn-count { flex: 1; }
.fn-reject { color: var(--stock-up); font-size: 11px; }
.fn-arrow { text-align: center; color: var(--text-tertiary); font-size: 12px; }
.et-table { width: 100%; border-collapse: collapse; font-size: 11px; border: 1px solid var(--border-default); border-radius: 6px; overflow: hidden; }
.et-th { display: grid; grid-template-columns: 52px 80px 72px 52px 1fr; gap: 4px; padding: 3px 8px; background: var(--bg-muted); font-size: 10px; font-weight: 600; color: var(--text-tertiary); }
.et-tr { display: grid; grid-template-columns: 52px 80px 72px 52px 1fr; gap: 4px; padding: 2px 8px; border-top: 1px solid var(--border-default); align-items: center; }
.et-tr:hover { background: var(--bg-hover); }
.et-tr.et-pass { border-left: 2px solid var(--stock-up); }
.et-tr.et-fail { border-left: 2px solid var(--stock-down); }
.et-c { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.et-strat { line-height: 1; }
.et-res { font-size: 10px; }
/* 【v2.9.7: 候选过滤按钮+淘汰统计+加载更多 */
.tab-btn-sm { padding: 2px 10px; border-radius: 4px; border: 1px solid var(--border-default); background: transparent; font-size: 11px; cursor: pointer; color: var(--text-secondary); transition: all 0.15s; }
.tab-btn-sm:hover { border-color: var(--el-color-primary-light-5); color: var(--el-color-primary); }
.tab-btn-sm.active { background: var(--el-color-primary-light-9); border-color: var(--el-color-primary-light-5); color: var(--el-color-primary); font-weight: 600; }
.tab-btn-sm:disabled { opacity: 0.5; cursor: not-allowed; }
.rejected-stats { padding: 8px 0; }
.rs-row { display: flex; align-items: center; gap: 8px; padding: 4px 0; font-size: 12px; }
.rs-label { min-width: 72px; color: var(--text-secondary); }
.rs-bar-track { flex: 1; height: 16px; background: var(--bg-hover); border-radius: 3px; overflow: hidden; }
.rs-bar-fill { height: 100%; background: rgba(245,63,63,0.25); border-radius: 3px; transition: width 0.3s; }
.rs-count { min-width: 40px; text-align: right; font-weight: 600; }
.load-more-hint { text-align: center; padding: 8px 0; }
.et-strat { line-height: 1; }
.et-result { font-size: 10px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* 情绪Tab */
.limit-pool-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 6px;
}
.limit-pool-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: var(--bg-elevated);
  border-radius: 6px;
  border: 1px solid var(--border-default);
  font-size: 12px;
}

/* 运维Tab */
.auto-trades-list { font-size: 12px; }
.at-header, .at-row { display: grid; grid-template-columns: 52px 50px 28px 72px 56px 50px 60px 56px 1fr; gap: 4px; padding: 3px 0; align-items: center; }
.at-header { font-weight: 600; color: var(--text-tertiary); border-bottom: 1px solid var(--border-default); font-size: 11px; }
.at-row { border-bottom: 1px solid var(--border-default); }
.at-row:last-child { border-bottom: none; }
.at-row.auto-trade { background: rgba(22,119,255,0.03); }
.at-row.manual-trade { background: rgba(250,173,20,0.03); }

/* 参数对比 */
.param-compare { display: flex; flex-direction: column; gap: 8px; }
.pc-strategy { background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 8px; padding: 10px 12px; }
.pc-header { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.pc-name { font-weight: 600; font-size: 13px; }
.pc-params { display: flex; flex-direction: column; gap: 2px; }
.pc-diff-row { display: grid; grid-template-columns: 140px 1fr 1fr; gap: 8px; padding: 3px 6px; border-radius: 4px; font-size: 12px; background: rgba(245,63,63,0.06); }
.pc-same-row { display: grid; grid-template-columns: 140px 1fr; gap: 8px; padding: 2px 6px; font-size: 11px; color: var(--text-tertiary); }
.pc-key { font-weight: 500; }
.pc-live { color: var(--el-color-primary); }
.pc-bt { color: var(--stock-up); }

.ops-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.scan-config-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 6px;
}
.sc-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 5px 10px;
  border-radius: 6px;
  font-size: 12px;
  border: 1px solid var(--border-default);
  background: var(--bg-elevated);
}
.sc-label { color: var(--text-secondary); }
.sc-value { font-weight: 500; font-family: 'JetBrains Mono', monospace; font-size: 11px; }
.ops-mf {
  max-width: 400px;
}
.ops-timeline {
  max-height: 400px;
  overflow-y: auto;
}

.pos-focused {
  border: 2px solid var(--el-color-primary) !important;
  box-shadow: 0 0 8px var(--el-color-primary-light-5);
}
</style>
