import { ref, computed, reactive, watch, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '@/api/client'
import { useThemeStore } from '@/stores/theme'
import {
  strategyMeta, strategyCN, pipelineLabels, modeMeta, factorLabel,
  parseResponse, signalRemaining as _signalRemaining, formatRemaining,
  normalizePct, formatSlTp,
} from '@/utils/scanner'
import { getChinaDate } from '@/utils/chinaDate'

// 子composable
import { useSentimentMonitor } from './composables/useSentimentMonitor'
import { useAutoTradeMonitor } from './composables/useAutoTradeMonitor'
import { useCoreMethods } from './composables/useCoreMethods'
import { useReviewMonitor } from './composables/useReviewMonitor'
import { useScanTraceMonitor } from './composables/useScanTraceMonitor'
import { usePremarketMonitor } from './composables/usePremarketMonitor'
import { useUnifiedData } from './composables/useUnifiedData'

// 类型定义
interface ScanStats { scans: number; signals_found: number; trades_executed: number; stop_losses: number; take_profits: number; stocks_scanned: number }
interface ScannerStatus { is_running: boolean; scan_count: number; last_scan_time: string; active_signals: number; positions: number; stocks_scanned: number; stats: ScanStats; account_id: string; trade_mode: string; dry_run?: boolean; circuit_breaker_paused?: boolean; circuit_breaker?: { trading_paused: boolean; pause_reason: string }; account: { total_assets: number; available_cash: number; market_value: number; total_profit: number }; data_sources?: Array<{ name: string; available: boolean; stocks: number; calls: number; limit: string; note: string }> }
interface ScanSignal { ts_code: string; stock_name: string; strategy: string; strategy_name: string; signal_type: string; price: number; pct_chg: number; volume_ratio: number; turnover_rate: number; is_limit_up: boolean; limit_up_count: number; confidence: number; reason: string; scan_time: string; factors: Record<string, number>; key_factors?: Record<string, string>; decision_detail?: Record<string, any>; signal_status?: string; _historical_signal?: boolean; layer_trace?: Record<string, any>; created_at?: number }
interface PositionInfo { ts_code: string; stock_name: string; strategy: string; strategy_name?: string; shares: number; available_qty: number; cost_price: number; current_price: number; profit_pct: number; profit_amount?: number; market_value?: number; today_buy: number; stop_loss_pct?: number; take_profit_pct?: number; stop_loss_price?: number; take_profit_price?: number; distance_to_stop?: number; risk_level?: string; trailing_stop?: { high_price: number; trailing_stop_pct: number; activated: boolean; stop_price: number; activated_at?: string }; effective_stop_price?: number; buy_date?: string; total_qty?: number }
interface TimelineItem { time: string; action: string; ts_code: string; stock_name: string; strategy: string; shares: number; price: number; reason: string; profit_pct?: number; profit_amount?: number; decision_detail?: Record<string, any> }
interface StrategyConfig { id: string; name: string; enabled: boolean; params: Record<string, any>; riskParams: Record<string, any>; paramDescriptions: ParamDesc[]; riskDescriptions: ParamDesc[] }
interface ParamDesc { key: string; label: string; value: any; displayValue: string; unit: string; min: number; max: number; step: number }
interface GlobalRisk { stop_loss_pct: number; take_profit_pct: number; max_position_per_stock: number; max_total_position: number }
interface HealthData { overall_status: 'healthy' | 'warning' | 'critical'; circuit_breaker: { trading_paused: boolean; pause_reason: string; consecutive_losses: number; max_consecutive_losses: number }; risk_metrics: { daily_drawdown_pct: number; max_drawdown_pct: number; position_ratio: number }; data_sources: Array<{ name: string; available: boolean; last_check: string }> }

type HealthStatusKey = 'healthy' | 'warning' | 'critical'
const healthEmojiMap: Record<HealthStatusKey, string> = { healthy: '🟢', warning: '🟡', critical: '🔴' }
const healthCNMap: Record<HealthStatusKey, string> = { healthy: '正常', warning: '预警', critical: '熔断' }
const healthClassMap: Record<HealthStatusKey, string> = { healthy: 'ok', warning: 'warn', critical: 'crit' }

const scannerApi = '/scanner'
const configApi = '/strategy-config'

export function useScannerMonitor() {
  // 【v2.9.97】统一数据源 - 8个Tab共用
  const unified = useUnifiedData()

  // ==================== 🔴 核心状态 ====================
  const loading = ref(false), autoRefresh = ref(true), soundEnabled = ref(false)
  const themeStore = useThemeStore()
  watch(() => themeStore.isDark, () => { /* theme changes auto-propagate via CSS vars */ })
  const status = ref<ScannerStatus | null>(null)
  const signals = ref<ScanSignal[]>([])
  const positions = ref<PositionInfo[]>([])
  const timeline = ref<TimelineItem[]>([])
  const orders = ref<any[]>([])
  // 【v2.9.99-r4】今日已平仓 (后端 v19 字段)
  const todayClosedTrades = ref<any[]>([])
  const closedPositions = computed(() => {
    const tlBuys = timeline.value.filter(t => t.action === 'buy')
    const tlSells = timeline.value.filter(t => t.action === 'sell')
    const result: any[] = []
    // 【v2.9.83修复】FIFO配对: 同一股票+策略可能多次买卖，需要按时间顺序配对
    // 用Map跟踪每个(ts_code+strategy)的未配对买入队列
    const buyQueues = new Map<string, any[]>()
    for (const buy of tlBuys) {
      const key = buy.ts_code + '|' + (buy.strategy || '')
      if (!buyQueues.has(key)) buyQueues.set(key, [])
      buyQueues.get(key)!.push(buy)
    }
    for (const sell of tlSells) {
      const key = sell.ts_code + '|' + (sell.strategy || '')
      const queue = buyQueues.get(key)
      const buy = queue?.length ? queue.shift() : undefined
      // 买入价反推: buy.price > sell.decision_detail?.cost_price > 当前持仓cost_price > 0
      const buyPrice = buy?.price ?? sell.decision_detail?.cost_price ?? positions.value.find(p => p.ts_code === sell.ts_code)?.cost_price ?? 0
      // 盈亏: 优先用sell自带的profit_pct/profit_amount(后端已算好), 否则用买卖价差
      // 【v2.9.111】买入订单不显示0%盈亏: 无买入价时profitPct=null
      const profitAmount = sell.profit_amount ?? (buyPrice > 0 ? (sell.price - buyPrice) * (sell.shares || 0) : null)
      const profitPct = sell.profit_pct ?? (buyPrice > 0 ? (sell.price - buyPrice) / buyPrice * 100 : null)
      result.push({ ts_code: sell.ts_code, stock_name: sell.stock_name || buy?.stock_name || '', strategy: sell.strategy, buy_price: buyPrice, sell_price: sell.price, profit_amount: profitAmount, profit_pct: profitPct, buy_time: buy?.time || '', sell_time: sell.time || '' })
    }
    const covered = new Set(result.map(r => r.ts_code + r.strategy))
    for (const o of orders.value.filter(o => o.side === 'sell' && o.filled_price > 0)) {
      const key = o.ts_code + o.strategy
      if (covered.has(key)) continue
      const buy = orders.value.find(b => b.side === 'buy' && b.ts_code === o.ts_code && b.strategy === o.strategy)
      const buyPrice = buy?.filled_price ?? 0
      result.push({ ts_code: o.ts_code, stock_name: o.stock_name || '', strategy: o.strategy, buy_price: buyPrice, sell_price: o.filled_price, profit_amount: buyPrice > 0 ? (o.filled_price - buyPrice) * o.filled_qty : null, profit_pct: buyPrice > 0 ? (o.filled_price - buyPrice) / buyPrice * 100 : null, buy_time: buy?.create_time || '', sell_time: o.create_time || '' })
    }
    return result.sort((a, b) => Math.abs(b.profit_amount) - Math.abs(a.profit_amount))
  })
  const limitPools = ref<{limit_up: any[], limit_down: any[], broken: any[]}>({limit_up: [], limit_down: [], broken: []})
  const limitPoolTab = ref('limit_up')
  const nowMs = ref(Date.now())
  const signalFilter = ref('all')
  const filteredSignals = computed(() => {
    const base = signalFilter.value === 'all' ? signals.value : signalFilter.value === 'anomaly' ? signals.value.filter(s => s.strategy.startsWith('anomaly_') || s.strategy_name?.startsWith('anomaly_')) : signals.value.filter(s => s.strategy === signalFilter.value || s.strategy_name === signalFilter.value)
    // 【v2.9.110】去重: 同一 (ts_code, strategy) 只保留最后一条(最新扫描)
    const seen = new Map<string, any>()
    for (const s of base) {
      const k = `${s.ts_code}|${s.strategy}`
      seen.set(k, s)
    }
    return [...seen.values()]
  })
  const focusIndex = ref(-1)
  const manualTrade = reactive({ ts_code: '', stock_name: '', side: 'buy', quantity: 0, price: 0 })
  const manualQuote = ref<any>(null)
  const posSort = ref('profit')
  const sortedPositions = computed(() => {
    const p = [...positions.value]
    switch (posSort.value) {
      case 'profit':   return p.sort((a, b) => (b.profit_pct || 0) - (a.profit_pct || 0))
      case 'cost':     return p.sort((a, b) => (b.market_value || 0) - (a.market_value || 0))
      case 'strategy': return p.sort((a, b) => (a.strategy || '').localeCompare(b.strategy || '') || (b.profit_pct || 0) - (a.profit_pct || 0))
      case 'time':     return p.sort((a, b) => (b.buy_time || b.created_at || '').localeCompare(a.buy_time || a.created_at || ''))
      default:         return p
    }
  })
  const sigRemaining = (sig: ScanSignal) => _signalRemaining(sig.created_at || 0, nowMs.value)
  const confirmVisible = ref(false)
  const confirmLoading = ref(false)
  const confirmData = reactive({ title: '', message: '', onConfirm: () => {} })
  const tradeMode = ref('simulated')
  const replayDate = ref('')
  const replayDateInput = ref('')
  const riskBarCollapsed = ref(true)
  const emergencyLiquidating = ref(false)
  const trailEditPct = ref(3)
  const trailSaving = ref(false)
  const dailyReport = ref<any>(null)
  const stratCollapsed = ref<Record<string, boolean>>({})
  const stratSectionCollapsed = ref(true)
  const qaSectionCollapsed = ref(false)
  const timelineCollapsed = ref(true)
  const replayDateVisible = ref(false)

  // 策略开关/UI辅助
  function toggleStrat(id: string) { stratCollapsed.value[id] = !stratCollapsed.value[id] }
  function toggleStrategy(id: string, _val?: boolean | string | number) { const s = strategies.value.find(s => s.id === id); if (s) { s.enabled = !s.enabled } }
  function openEditDialog(strategy: StrategyConfig) { editingStrategy.value = strategy; editParams.value = { ...strategy.params }; editRiskParams.value = { ...strategy.riskParams }; editDialogVisible.value = true }

  // 仓位比(资产中市值占比)
  const positionRatio = computed(() => {
    const acc = status.value?.account
    if (!acc || !acc.total_assets || acc.total_assets <= 0) return '0'
    const ratio = acc.market_value / acc.total_assets * 100
    if (!isFinite(ratio)) return '0'
    return ratio.toFixed(1)
  })

  // 距止损距离
  function distanceToStopLoss(pos: PositionInfo): string {
    if (pos.stop_loss_price && pos.stop_loss_price > 0 && pos.current_price > 0) {
      const dist = ((pos.current_price - pos.stop_loss_price) / pos.current_price * 100)
      return (isFinite(dist) ? dist : 0).toFixed(1) + '%'
    }
    const slPct = normalizePct(pos.stop_loss_pct, 3)
    const result = pos.profit_pct + slPct
    return (isFinite(result) ? result : 0).toFixed(1) + '%'
  }

  // ==================== ⚙️ 策略配置 ====================
  const strategies = ref<StrategyConfig[]>([])
  const globalRisk = ref<GlobalRisk | null>(null)
  const editingStrategy = ref<StrategyConfig | null>(null)
  const editDialogVisible = ref(false)
  const editTab = ref('params')
  const editParams = ref<Record<string, any>>({})
  const editRiskParams = ref<Record<string, any>>({})
  const saving = ref(false)
  const dataSources = ref<any[]>([])
  const brokers = ref<any[]>([])

  // ==================== 🏥 健康状态 ====================
  const healthData = ref<HealthData | null>(null)
  const healthStatus = computed(() => healthData.value?.overall_status || 'unknown')
  const healthEmoji = computed(() => healthEmojiMap[healthStatus.value as HealthStatusKey] || '⚪')
  const healthCN = computed(() => healthCNMap[healthStatus.value as HealthStatusKey] || '未知')
  const healthClass = computed(() => healthClassMap[healthStatus.value as HealthStatusKey] || 'unknown')

  // ==================== 💫 情绪数据 (子composable) ====================
  const sentiment = useSentimentMonitor()

  // ==================== 🤖 自动交易+参数对比 (子composable) ====================
  const pnlHistory = ref<{time: string; value: number}[]>([])
  const perfData = ref<Array<{time:string;net_value:number;drawdown:number}>>([])
  const autoTrade = useAutoTradeMonitor({ totalPnl: computed(() => status.value?.account?.total_profit || 0), pnlHistory, perfData })
  const perfChartOption = computed(() => autoTrade.pnlOption.value)
  const dailyReportVisible = ref(false)
  const weeklyReportVisible = ref(false)

  // ==================== 🎛️ UI状态 ====================
  type MonitorTab = 'guide' | 'trading' | 'premarket' | 'scan-trace' | 'review' | 'risk' | 'sentiment' | 'history' | 'analysis' | 'account' | 'ops'
  const monitorTabs: MonitorTab[] = ['guide', 'trading', 'premarket', 'scan-trace', 'review', 'risk', 'sentiment', 'history', 'analysis', 'account', 'ops']
  const savedTab = (() => {
    try {
      const v = localStorage.getItem('market-monitor-active-tab') as MonitorTab | null
      return v && monitorTabs.includes(v) ? v : 'guide'
    } catch (e) { console.error('[monitor] localStorage读取失败:', e); return 'guide' }
  })()
  const activeTab = ref<MonitorTab>(savedTab)
  watch(activeTab, (tab) => {
    try { localStorage.setItem('market-monitor-active-tab', tab) } catch (e) { console.error('[useScannerMonitor]', e) }
    try {
      if (tab === 'premarket') premarket.fetchPremarketData()
      if (tab === 'scan-trace') { scanTrace.fetchScanTraceDates(); scanTrace.fetchScanHistory() }
      if (tab === 'review') { review.fetchReviewData(); autoTrade.fetchParamCompare() }
      if (tab === 'sentiment') { sentiment.fetchSentimentData() }
      if (tab === 'ops') { autoTrade.fetchAutoTrades(); autoTrade.fetchScanConfig() }
    } catch (e) { console.error('[Tab] error:', e) }
  })

  // 页面初始化时预加载运维数据(避免切tab时出现加载中)
  autoTrade.fetchScanConfig()
  autoTrade.fetchAutoTrades()

  // ==================== 🌅 盘前竞价 (子composable) ====================
  const premarket = usePremarketMonitor()

  // ==================== 🔍 扫描追踪 (子composable) ====================
  const scanTrace = useScanTraceMonitor()

  // ==================== 📋 复盘数据 (子composable) ====================
  const review = useReviewMonitor()

  // ==================== 📊 运维+审计 ====================
  const auditLog = ref<any[]>([])
  const auditLogLoading = ref(false)
  async function fetchAuditLog() { try { const r = await api.get(`${scannerApi}/audit-log?limit=100`); const p = parseResponse(r); if (p.success) auditLog.value = p.data || [] } catch (e) { console.error('[useScannerMonitor]', e) } }

  // ==================== 📜 历史 ====================
  // 【v2.9.99-r3】历史默认今天 (每日交易快照默认看今天)
  const _getTodayStr = () => {
    const now = new Date()
    const china = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Shanghai' }))
    const y = china.getFullYear(), m = String(china.getMonth() + 1).padStart(2, '0'), d = String(china.getDate()).padStart(2, '0')
    return `${y}-${m}-${d}`
  }
  const historyDate = ref(_getTodayStr())
  const historyData = ref<any[]>([])
  const historyOrders = ref<any[]>([])
  const historyLoading = ref(false)
  // 【v2.9.97】历史回放走统一数据源
  async function loadHistory() {
    if (!historyDate.value) return
    historyLoading.value = true
    try {
      const d = historyDate.value.replace(/-/g, '')
      const [tlR, ordR] = await Promise.all([
        api.get(`/unified/trades?date=${d}`),
        api.get(`${scannerApi}/orders?limit=200&date=${d}`),
      ])
      const tlP = parseResponse(tlR)
      const ordP = parseResponse(ordR)
      // unified trades → timeline 格式适配
      if (tlP.success) historyData.value = (tlP.data?.trades || []).map((t: any) => ({
        time: t.time || t.fill_time, action: t.side, ts_code: t.ts_code, stock_name: t.stock_name,
        strategy: t.strategy, shares: t.quantity, price: t.price, reason: t.reason,
        profit_pct: t.profit_pct, profit_amount: t.profit_amount,
      }))
      if (ordP.success) historyOrders.value = ordP.data || []
    } catch (e) { console.error('[useScannerMonitor]', e) }
    finally { historyLoading.value = false }
  }

  // ==================== 🔧 核心方法 (子composable) ====================
  const core = useCoreMethods({
    loading, autoRefresh, soundEnabled, status, signals, positions, timeline, orders, todayClosedTrades,
    nowMs, signalFilter, focusIndex, tradeMode, replayDate, activeTab, limitPools,
    strategies, globalRisk, healthData, confirmVisible, confirmLoading, confirmData,
    manualTrade, manualQuote, riskBarCollapsed, trailEditPct, trailSaving,
    emergencyLiquidating, dataSources, brokers, dailyReport,
    stratCollapsed: ref<Record<string, boolean>>({}),
    stratSectionCollapsed: ref(true),
    qaSectionCollapsed: ref(false),
    timelineCollapsed: ref(true),
    editDialogVisible, editTab, editParams, editRiskParams,
    editingStrategy, saving,
  })

  // ==================== 📌 交易详情/审计弹窗 ====================
  const tradeDetailVisible = ref(false)
  const tradeDetailData = ref<any>(null)
  const tradeAuditVisible = ref(false)
  const tradeAuditData = ref<any[]>([])
  async function openTradeDetail(ts_code: string) { try { const r = await api.get(`${scannerApi}/trade-detail/${ts_code}`); const p = parseResponse(r); if (p.success) { tradeDetailData.value = p.data; tradeDetailVisible.value = true } } catch (e: any) { ElMessage.error('获取详情失败') } }
  async function openTradeAudit() { try { const r = await api.get(`${scannerApi}/trade-audit`); const p = parseResponse(r); if (p.success) { tradeAuditData.value = p.data; tradeAuditVisible.value = true } } catch (e: any) { ElMessage.error('获取审查失败') } }

  // ==================== 📌 追踪止损 ====================
  async function setTrailingStop(ts_code: string, activated: boolean) {
    trailSaving.value = true
    try {
      const r = await api.put(`${scannerApi}/trailing-stop/${ts_code}`, { activated, trailing_stop_pct: trailEditPct.value / 100 })
      const p = parseResponse(r)
      if (p.success) { ElMessage.success(`${activated ? '激活' : '取消'}追踪止损`); core.fetchScanner() }
      else ElMessage.error('设置失败')
    } catch (e: any) { ElMessage.error('设置失败') }
    finally { trailSaving.value = false }
  }

  // ==================== 📌 手动交易 ====================
  async function onManualCodeChange(code: string) {
    if (!code) { manualQuote.value = null; return }
    try {
      const tsCode = code.includes('.') ? code : (code.startsWith('6') || code.startsWith('9') ? code + '.SH' : code + '.SZ')
      const r = await api.get(`${scannerApi}/quote/${tsCode}`)
      const p = parseResponse(r)
      if (p.success && p.data) { manualQuote.value = p.data; manualTrade.ts_code = tsCode; manualTrade.stock_name = p.data.name || ''; manualTrade.price = p.data.price || 0 }
    } catch (e) { console.error('[useScannerMonitor]', e) }
  }

  const executeManualTrade = async () => {
    if (!manualTrade.ts_code) return
    const sideText = manualTrade.side === 'buy' ? '买入' : '卖出'
    const amount = (manualTrade.quantity || 0) * (manualTrade.price || 0)
    core.showConfirm(`确认${sideText}`, `${manualTrade.stock_name || manualTrade.ts_code}\n${sideText} ${manualTrade.quantity || 0}股 × ¥${(manualTrade.price || 0).toFixed(2)} ≈ ¥${amount.toFixed(0)}`, async () => {
      try {
        const r = await api.post(`${scannerApi}/trade`, { ts_code: manualTrade.ts_code, stock_name: manualTrade.stock_name, side: manualTrade.side, quantity: manualTrade.quantity || 0, price: manualTrade.price || 0, order_type: 'market', strategy: 'manual', reason: '手动操作' })
        const p = parseResponse(r); if (p.success) { ElMessage.success(`${p.data.side === 'buy' ? '买入' : '卖出'} ${p.data.ts_code} ${p.data.filled_qty ?? '?'}股@${p.data.filled_price ?? '市价'}`); manualTrade.ts_code = ''; manualTrade.stock_name = ''; manualTrade.quantity = 0; manualTrade.price = 0; core.fetchAll(true) } else ElMessage.error('下单失败')
      } catch (e: any) { ElMessage.error('下单失败') }
    })
  }

  // ==================== 📌 策略保存 ====================
  async function saveStrategy() {
    if (!editingStrategy.value) return
    saving.value = true
    try {
      const r = await api.put(`${configApi}/strategies/${editingStrategy.value.id}`, { params: editParams.value, risk_params: editRiskParams.value })
      const p = parseResponse(r)
      if (p.success) { ElMessage.success('策略已保存'); editDialogVisible.value = false; core.fetchStrategies() }
      else ElMessage.error('保存失败')
    } catch (e) { console.error('[monitor] saveStrategy failed:', e); ElMessage.error('保存失败') }
    finally { saving.value = false }
  }

  // ==================== 📌 模式切换/回放 ====================
  function onModeChange(mode: string) { if (mode === 'replay') { replayDateVisible.value = true } }
  async function confirmReplay() {
    if (!replayDateInput.value) { ElMessage.warning('请选择回放日期'); return }
    replayDate.value = replayDateInput.value.replace(/-/g, '')
    ElMessage.success(`回放模式: ${replayDateInput.value}`)
  }
  function cancelReplay() { replayDate.value = ''; replayDateInput.value = ''; tradeMode.value = 'simulated' }

  // ==================== 📌 日报 ====================
  async function fetchDailyReport() { try { const r = await api.get(`${scannerApi}/daily-report`); const p = parseResponse(r); if (p.success) dailyReport.value = p.data } catch (e) { console.error('[useScannerMonitor]', e) } }

  // ==================== 📌 对比模式 ====================
  const compareVisible = ref(false)
  const compareData = ref<any[]>([])
  const compareLoading = ref(false)
  async function loadCompare() { compareLoading.value = true; try { const r = await api.get(`${scannerApi}/strategy-params-compare`); const p = parseResponse(r); if (p.success) { compareData.value = p.data; compareVisible.value = true } } catch (e) { console.error('[useScannerMonitor]', e) } finally { compareLoading.value = false } }

  const toggleDryRun = () => { tradeMode.value = tradeMode.value === 'dry_run' ? 'simulated' : 'dry_run' }
  // 【v2.9.87修复】cumulativePnl: 优先从timeline sell事件累加profit_amount(更准确),
  // fallback到account.total_profit(回测/全量场景)
  const cumulativePnl = computed(() => {
    // 尝试从timeline的sell事件累加
    let sellPnl = 0
    let hasSellPnl = false
    for (const item of timeline.value) {
      if (item.action === 'sell' && item.profit_amount != null) {
        sellPnl += item.profit_amount
        hasSellPnl = true
      }
    }
    // 如果timeline有profit_amount数据,用累加值(更精确); 否则fallback到account
    if (hasSellPnl) return sellPnl
    return core.totalPnl.value
  })

  // ==================== 📌 模板兼容/stub 属性 ====================
  const signalTraceVisible = ref(false)
  // layerDebugVisible, layerDebugData, layerDebugLoading come from ...scanTrace spread — do NOT override with local refs
  // (otherwise openLayerDebug writes to scanTrace's refs but template reads ours)
  function signalStatusTag(status?: string): { type: 'success' | 'warning' | 'info' | 'danger'; text: string } { const map: Record<string, { type: 'success' | 'warning' | 'info' | 'danger'; text: string }> = { pending: { type: 'warning', text: '待执行' }, executed: { type: 'success', text: '已执行' }, expired: { type: 'info', text: '已过期' }, rejected: { type: 'danger', text: '已拒绝' } }; return map[status || ''] || { type: 'info', text: status || '未知' } }
  const scanTraceVisible = computed({ get: () => signalTraceVisible.value, set: (v: boolean) => { signalTraceVisible.value = v } })
  const scanTraceData = computed(() => scanTrace.scanTraceDetail?.value || null)
  const scanTraceCode = computed(() => (scanTraceData.value as any)?.ts_code || '')
  function openScanTrace(scanId: string | number) { scanTrace.fetchScanTrace(String(scanId)); signalTraceVisible.value = true }
  // formatLayerTrace and formatDecisionDetail come from ...scanTrace spread — do NOT override with simpler versions
  const layerLabel = (k: string | number) => { const key = String(k); const label = pipelineLabels[key]; if (!label) return key; const prefix = key.split('_')[0]; return prefix + ' ' + label }
  // layerDesc comes from ...scanTrace spread — do NOT override with a stub
  const openWeeklyReport = () => { weeklyReportVisible.value = true }
  const saveSnapshot = async () => { try { await api.post(`${scannerApi}/snapshot`); ElMessage.success('快照已保存') } catch (e) { console.error('[useScannerMonitor]', e) } }
  // backtestRunning 来自 ...review spread, 不再本地覆盖(避免 spread 陷阱)
  const exportTradeLog = async () => {
    try {
      const r = await api.get(`${scannerApi}/export-trade-log`)
      const p = parseResponse(r)
      if (p.success && p.data?.csv) {
        // 生成CSV下载
        const blob = new Blob(['\uFEFF' + p.data.csv], { type: 'text/csv;charset=utf-8' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `trade_log_${getChinaDate()}.csv`
        a.click()
        URL.revokeObjectURL(url)
      } else if (p.success) {
        // 无数据
      }
    } catch (e) { console.error('[useScannerMonitor]', e) }
  }
  const exportJSON = async () => {
    try {
      // 导出时间线+订单为JSON
      const data = {
        export_time: getChinaDate() + 'T' + new Date().toLocaleTimeString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }),
        timeline: timeline.value,
        orders: orders.value,
        closedPositions: closedPositions.value,
        auditLog: auditLog.value,
        cumulativePnl: cumulativePnl.value,
      }
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `trade_data_${getChinaDate()}.json`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) { console.error('[useScannerMonitor]', e) }
  }
  const weeklyReportData = computed<Record<string, any>>(() => review.weeklyReportData?.value as Record<string, any> || {})

  // 生命周期
  onMounted(async () => {
    try { await Promise.all([core.fetchScanner(), core.fetchStrategies(), core.fetchHealth()]) } catch(e) { console.error('[Mount] fetch error:', e); ElMessage.warning('数据加载失败，请检查连接后刷新') }
    try { core.fetchLimitPools(); core.fetchDataSources(); autoTrade.fetchPerformanceHistory(); core.mount() } catch(e) { console.error('[Mount] setup error:', e); ElMessage.error('实时连接建立失败') }
    core.setupStoreWatchers(watch)
  })
  onUnmounted(() => { core.unmount() })

  return {
    // 【v2.9.97】统一数据层 - 8个Tab共用
    unified,
    // 核心状态
    loading, autoRefresh, soundEnabled, status, signals, positions, timeline, orders, todayClosedTrades,
    signalFilter, filteredSignals, closedPositions, isRunning: core.isRunning,
    accountInfo: core.accountInfo, totalPnl: core.totalPnl, positionRatio,
    circuitBreakerPaused: core.circuitBreakerPaused, focusIndex, nowMs,
    tradeMode, replayDate, replayDateInput, manualTrade, manualQuote, posSort, sortedPositions,
    confirmVisible, confirmLoading, confirmData,
    sigRemaining, scannerApi, configApi,
    // 策略配置
    strategies, globalRisk, editingStrategy, editDialogVisible, editTab,
    editParams, editRiskParams, saving, dataSources, brokers,
    // 健康状态
    healthData, healthStatus, healthEmoji, healthCN, healthClass,
    riskBarCollapsed, trailEditPct, trailSaving, emergencyLiquidating,
    // 情绪 (子composable)
    ...sentiment,
    // 自动交易 (子composable)
    autoTrades: autoTrade.autoTrades, opsDate: autoTrade.opsDate, paramCompare: autoTrade.paramCompare,
    paramCompareLoading: autoTrade.paramCompareLoading,
    scanConfig: autoTrade.scanConfig, scanConfigLoading: autoTrade.scanConfigLoading,
    pnlOption: autoTrade.pnlOption,
    updatePnlHistory: autoTrade.updatePnlHistory,
    fetchPerformanceHistory: autoTrade.fetchPerformanceHistory,
    fetchAutoTrades: autoTrade.fetchAutoTrades,
    fetchParamCompare: autoTrade.fetchParamCompare,
    fetchScanConfig: autoTrade.fetchScanConfig,
    fetchSentimentData: sentiment.fetchSentimentData,
    perfChartOption, dailyReportVisible, weeklyReportVisible,
    // 盘前 (子composable)
    ...premarket,
    // 扫描追踪 (子composable)
    ...scanTrace,
    // 复盘 (子composable)
    ...review,
    pnlHistory, perfData,
    // 历史
    historyDate, historyData, historyOrders, historyLoading, loadHistory,
    // 审计
    auditLog, auditLogLoading, fetchAuditLog,
    // 交易详情/审计
    tradeDetailVisible, tradeDetailData,
    tradeAuditVisible, tradeAuditData,
    openTradeDetail, openTradeAudit,
    // 追踪止损
    setTrailingStop, distanceToStopLoss,
    // 手动交易
    onManualCodeChange, executeManualTrade,
    // 策略保存
    saveStrategy,
    // 模式切换/回放
    onModeChange, confirmReplay, cancelReplay,
    // 日报
    fetchDailyReport, dailyReport,
    // 工具
    strategyCN, normalizePct, formatSlTp, modeMeta,
    // UI
    activeTab, limitPools, limitPoolTab,
    stratCollapsed, stratSectionCollapsed, qaSectionCollapsed, timelineCollapsed,
    toggleStrat, toggleStrategy, openEditDialog,
    replayDateVisible,
    themeStore,
    // 对比
    compareVisible, compareData, compareLoading, loadCompare,
    toggleDryRun, cumulativePnl,
    // 格式化方法 — formatLayerTrace/formatDecisionDetail come from ...scanTrace
    // 层级调试 — layerDebugVisible/Data/Loading/openLayerDebug come from ...scanTrace
    // 追踪弹窗别名
    scanTraceVisible, scanTraceData, scanTraceCode, signalTraceVisible,
    openScanTrace, signalStatusTag,
    // 复盘(来自...review)
    openWeeklyReport, weeklyReportData, saveSnapshot,
    // backtestRunning 来自 ...review spread
    exportTradeLog,
    exportJSON,
    // 工具
    strategyMeta, formatRemaining, factorLabel, layerLabel,
    // 核心方法
    fetchScanner: core.fetchScanner, startScanner: core.startScanner,
    stopScanner: core.stopScanner, manualScan: core.manualScan,
    forceScan: core.forceScan, quickBuy: core.quickBuy, quickSell: core.quickSell,
    dailySettlement: core.dailySettlement, resetAccount: core.resetAccount,
    sellAllPositions: core.sellAllPositions, resetCircuitBreaker: core.resetCircuitBreaker,
    pauseCircuitBreaker: core.pauseCircuitBreaker, emergencyLiquidate: core.emergencyLiquidate,
    fetchLimitPools: core.fetchLimitPools, fetchDataSources: core.fetchDataSources,
    fetchHealth: core.fetchHealth, fetchStrategies: core.fetchStrategies,
    fetchAll: core.fetchAll, showConfirm: core.showConfirm, handleConfirm: core.handleConfirm,
    playSignalSound: core.playSignalSound,
    dryRun: core.dryRun,
    // 【v2.9.71/75: WS连接状态+数据新鲜度】
    wsStatus: core.wsStatus,
    wsIsConnected: core.wsIsConnected,
    wsRetryCount: core.wsRetryCount,
    wsDataStale: core.wsDataStale,
  }
}
