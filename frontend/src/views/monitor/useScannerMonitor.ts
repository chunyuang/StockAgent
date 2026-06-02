import { ref, computed, reactive, watch, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '@/api/client'
import { useThemeStore } from '@/stores/theme'
import {
  strategyMeta, strategyCN, pipelineLabels, modeMeta, factorLabel,
  parseResponse, signalRemaining as _signalRemaining, formatRemaining,
  normalizePct, formatSlTp,
} from '@/utils/scanner'

// 子composable
import { useSentimentMonitor } from './composables/useSentimentMonitor'
import { useAutoTradeMonitor } from './composables/useAutoTradeMonitor'
import { useCoreMethods } from './composables/useCoreMethods'
import { useReviewMonitor } from './composables/useReviewMonitor'
import { useScanTraceMonitor } from './composables/useScanTraceMonitor'
import { usePremarketMonitor } from './composables/usePremarketMonitor'

// 类型定义
interface ScanStats { scans: number; signals_found: number; trades_executed: number; stop_losses: number; take_profits: number; stocks_scanned: number }
interface ScannerStatus { is_running: boolean; scan_count: number; last_scan_time: string; active_signals: number; positions: number; stocks_scanned: number; stats: ScanStats; account_id: string; trade_mode: string; dry_run?: boolean; circuit_breaker_paused?: boolean; circuit_breaker?: { trading_paused: boolean; pause_reason: string }; account: { total_assets: number; available_cash: number; market_value: number; total_profit: number }; data_sources?: Array<{ name: string; available: boolean; stocks: number; calls: number; limit: string; note: string }> }
interface ScanSignal { ts_code: string; stock_name: string; strategy: string; strategy_name: string; signal_type: string; price: number; pct_chg: number; volume_ratio: number; turnover_rate: number; is_limit_up: boolean; limit_up_count: number; confidence: number; reason: string; scan_time: string; factors: Record<string, number>; key_factors?: Record<string, string>; decision_detail?: Record<string, any>; signal_status?: string; layer_trace?: Record<string, any>; created_at?: number }
interface PositionInfo { ts_code: string; stock_name: string; strategy: string; strategy_name?: string; shares: number; available_qty: number; cost_price: number; current_price: number; profit_pct: number; profit_amount?: number; market_value?: number; today_buy: number; stop_loss_pct?: number; take_profit_pct?: number; stop_loss_price?: number; take_profit_price?: number; distance_to_stop?: number; risk_level?: string; trailing_stop?: { high_price: number; trailing_stop_pct: number; activated: boolean; stop_price: number; activated_at?: string }; effective_stop_price?: number }
interface TimelineItem { time: string; action: string; ts_code: string; stock_name: string; strategy: string; shares: number; price: number; reason: string; profit_pct?: number; profit_amount?: number; decision_detail?: Record<string, any> }
interface StrategyConfig { id: string; name: string; enabled: boolean; params: Record<string, any>; riskParams: Record<string, any>; paramDescriptions: ParamDesc[]; riskDescriptions: ParamDesc[] }
interface ParamDesc { key: string; label: string; value: any; displayValue: string; unit: string; min: number; max: number; step: number }
interface GlobalRisk { stop_loss_pct: number; take_profit_pct: number; max_position_pct: number; max_positions: number }
interface HealthData { overall_status: 'healthy' | 'warning' | 'critical'; circuit_breaker: { trading_paused: boolean; pause_reason: string; consecutive_losses: number; max_consecutive_losses: number }; risk_metrics: { daily_drawdown_pct: number; max_drawdown_pct: number; position_ratio: number }; data_sources: Array<{ name: string; available: boolean; last_check: string }> }

type HealthStatusKey = 'healthy' | 'warning' | 'critical'
const healthEmojiMap: Record<HealthStatusKey, string> = { healthy: '🟢', warning: '🟡', critical: '🔴' }
const healthCNMap: Record<HealthStatusKey, string> = { healthy: '正常', warning: '预警', critical: '熔断' }
const healthClassMap: Record<HealthStatusKey, string> = { healthy: 'ok', warning: 'warn', critical: 'crit' }

const scannerApi = '/scanner'
const configApi = '/strategy-config'

export function useScannerMonitor() {

  // ==================== 🔴 核心状态 ====================
  const loading = ref(false), autoRefresh = ref(true), soundEnabled = ref(false)
  const themeStore = useThemeStore()
  watch(() => themeStore.isDark, () => { /* theme changes auto-propagate via CSS vars */ })
  const status = ref<ScannerStatus | null>(null)
  const signals = ref<ScanSignal[]>([])
  const positions = ref<PositionInfo[]>([])
  const timeline = ref<TimelineItem[]>([])
  const orders = ref<any[]>([])
  const closedPositions = computed(() => {
    const tlBuys = timeline.value.filter(t => t.action === 'buy')
    const tlSells = timeline.value.filter(t => t.action === 'sell')
    const result: any[] = []
    for (const sell of tlSells) {
      const buy = tlBuys.find(b => b.ts_code === sell.ts_code && b.strategy === sell.strategy && !result.some(r => r.buy_time === b.time))
      const buyPrice = buy?.price || sell.decision_detail?.cost_price || 0
      result.push({ ts_code: sell.ts_code, stock_name: sell.stock_name || buy?.stock_name || '', strategy: sell.strategy, buy_price: buyPrice, sell_price: sell.price, profit_amount: sell.profit_amount || (sell.price - buyPrice) * (sell.shares || 0), profit_pct: sell.profit_pct || (buyPrice > 0 ? (sell.price - buyPrice) / buyPrice * 100 : 0), buy_time: buy?.time || '', sell_time: sell.time || '' })
    }
    const covered = new Set(result.map(r => r.ts_code + r.strategy))
    for (const o of orders.value.filter(o => o.side === 'sell' && o.filled_price > 0)) {
      const key = o.ts_code + o.strategy
      if (covered.has(key)) continue
      const buy = orders.value.find(b => b.side === 'buy' && b.ts_code === o.ts_code && b.strategy === o.strategy)
      const buyPrice = buy?.filled_price || 0
      result.push({ ts_code: o.ts_code, stock_name: o.stock_name || '', strategy: o.strategy, buy_price: buyPrice, sell_price: o.filled_price, profit_amount: (o.filled_price - buyPrice) * o.filled_qty, profit_pct: buyPrice > 0 ? (o.filled_price - buyPrice) / buyPrice * 100 : 0, buy_time: buy?.create_time || '', sell_time: o.create_time || '' })
    }
    return result.sort((a, b) => Math.abs(b.profit_amount) - Math.abs(a.profit_amount))
  })
  const limitPools = ref<{limit_up: any[], limit_down: any[], broken: any[]}>({limit_up: [], limit_down: [], broken: []})
  const limitPoolTab = ref('limit_up')
  const nowMs = ref(Date.now())
  const signalFilter = ref('all')
  const filteredSignals = computed(() => { if (signalFilter.value === 'all') return signals.value; if (signalFilter.value === 'anomaly') return signals.value.filter(s => s.strategy.startsWith('anomaly_')); return signals.value.filter(s => s.strategy === signalFilter.value) })
  const focusIndex = ref(-1)
  const manualTrade = reactive({ ts_code: '', stock_name: '', side: 'buy', quantity: 0, price: 0 })
  const manualQuote = ref<any>(null)
  const posSort = ref('profit')
  const sortedPositions = computed(() => { const p = [...positions.value]; if (posSort.value === 'profit') return p.sort((a, b) => b.profit_pct - a.profit_pct); if (posSort.value === 'risk') return p.sort((a, b) => (a.distance_to_stop ?? 0) - (b.distance_to_stop ?? 0)); return p })
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
  const stratSectionCollapsed = ref(false)
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
    if (!acc || acc.total_assets <= 0) return '0'
    return (acc.market_value / acc.total_assets * 100).toFixed(1)
  })

  // 距止损距离
  function distanceToStopLoss(pos: PositionInfo): string {
    if (pos.stop_loss_price && pos.stop_loss_price > 0 && pos.current_price > 0) {
      const dist = ((pos.current_price - pos.stop_loss_price) / pos.current_price * 100)
      return dist.toFixed(1) + '%'
    }
    const slPct = normalizePct(pos.stop_loss_pct, 3)
    return (pos.profit_pct + slPct).toFixed(1) + '%'
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
  const activeTab = ref<'guide' | 'trading' | 'premarket' | 'scan-trace' | 'review' | 'risk' | 'sentiment' | 'history' | 'ops'>('guide')
  watch(activeTab, (tab) => {
    try {
      if (tab === 'premarket') premarket.fetchPremarketData()
      if (tab === 'scan-trace') { scanTrace.fetchScanTraceDates(); scanTrace.fetchScanHistory() }
      if (tab === 'review') { review.fetchReviewData(); autoTrade.fetchParamCompare() }
      if (tab === 'sentiment') { sentiment.fetchSentimentData() }
      if (tab === 'ops') { autoTrade.fetchAutoTrades(); autoTrade.fetchScanConfig() }
    } catch (e) { console.error('[Tab] error:', e) }
  })

  // ==================== 🌅 盘前竞价 (子composable) ====================
  const premarket = usePremarketMonitor()

  // ==================== 🔍 扫描追踪 (子composable) ====================
  const scanTrace = useScanTraceMonitor()

  // ==================== 📋 复盘数据 (子composable) ====================
  const review = useReviewMonitor()

  // ==================== 📊 运维+审计 ====================
  const auditLog = ref<any[]>([])
  const auditLogLoading = ref(false)
  async function fetchAuditLog() { try { const r = await api.get(`${scannerApi}/audit-log?limit=100`); const p = parseResponse(r); if (p.success) auditLog.value = p.data || [] } catch { /* ignore */ } }

  // ==================== 📜 历史 ====================
  const historyDate = ref('')
  const historyData = ref<any[]>([])
  const historyLoading = ref(false)
  async function loadHistory() { if (!historyDate.value) return; historyLoading.value = true; try { const d = historyDate.value.replace(/-/g, ''); const r = await api.get(`${scannerApi}/timeline/history?date=${d}`); const p = parseResponse(r); if (p.success) historyData.value = p.data || [] } catch {} finally { historyLoading.value = false } }

  // ==================== 🔧 核心方法 (子composable) ====================
  const core = useCoreMethods({
    loading, autoRefresh, soundEnabled, status, signals, positions, timeline, orders,
    nowMs, signalFilter, focusIndex, tradeMode, replayDate, activeTab, limitPools,
    strategies, globalRisk, healthData, confirmVisible, confirmLoading, confirmData,
    manualTrade, manualQuote, riskBarCollapsed, trailEditPct, trailSaving,
    emergencyLiquidating, dataSources, brokers, dailyReport,
    stratCollapsed: ref<Record<string, boolean>>({}),
    stratSectionCollapsed: ref(false),
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
      const r = await api.post(`${scannerApi}/trailing-stop`, { ts_code, activated, trailing_stop_pct: trailEditPct.value / 100 })
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
      const tsCode = code.length === 6 ? code + '.SH' : code
      const r = await api.get(`${scannerApi}/quote?ts_code=${tsCode}`)
      const p = parseResponse(r)
      if (p.success && p.data) { manualQuote.value = p.data; manualTrade.ts_code = tsCode; manualTrade.stock_name = p.data.name || ''; manualTrade.price = p.data.price || 0 }
    } catch { /* ignore */ }
  }

  const executeManualTrade = async () => {
    if (!manualTrade.ts_code) return
    const sideText = manualTrade.side === 'buy' ? '买入' : '卖出'
    const amount = (manualTrade.quantity || 0) * (manualTrade.price || 0)
    core.showConfirm(`确认${sideText}`, `${manualTrade.stock_name || manualTrade.ts_code}\n${sideText} ${manualTrade.quantity || 0}股 × ¥${(manualTrade.price || 0).toFixed(2)} ≈ ¥${amount.toFixed(0)}`, async () => {
      try {
        const r = await api.post(`${scannerApi}/trade`, { ts_code: manualTrade.ts_code, stock_name: manualTrade.stock_name, side: manualTrade.side, quantity: manualTrade.quantity || 0, price: manualTrade.price || 0, order_type: 'market', strategy: 'manual', reason: '手动操作' })
        const p = parseResponse(r); if (p.success) { ElMessage.success(`${p.data.side === 'buy' ? '买入' : '卖出'} ${p.data.ts_code} ${p.data.filled_qty}股@${p.data.filled_price}`); manualTrade.ts_code = ''; manualTrade.stock_name = ''; manualTrade.quantity = 0; manualTrade.price = 0; core.fetchAll(true) } else ElMessage.error('下单失败')
      } catch (e: any) { ElMessage.error('下单失败') }
    })
  }

  // ==================== 📌 策略保存 ====================
  async function saveStrategy() {
    if (!editingStrategy.value) return
    saving.value = true
    try {
      const r = await api.post(`${configApi}/strategies/${editingStrategy.value.id}`, { params: editParams.value, risk_params: editRiskParams.value })
      const p = parseResponse(r)
      if (p.success) { ElMessage.success('策略已保存'); editDialogVisible.value = false; core.fetchStrategies() }
      else ElMessage.error('保存失败')
    } catch { ElMessage.error('保存失败') }
    finally { saving.value = false }
  }

  // ==================== 📌 模式切换/回放 ====================
  function toggleScanHour(_hour: string) { /* 内联实现 - 扫描时段开关 */ }
  function onModeChange(mode: string) { if (mode === 'replay') { /* 触发日期选择 */ } }
  async function confirmReplay() {
    if (!replayDateInput.value) { ElMessage.warning('请选择回放日期'); return }
    replayDate.value = replayDateInput.value.replace(/-/g, '')
    ElMessage.success(`回放模式: ${replayDateInput.value}`)
  }
  function cancelReplay() { replayDate.value = ''; replayDateInput.value = ''; tradeMode.value = 'simulated' }

  // ==================== 📌 日报 ====================
  async function fetchDailyReport() { try { const r = await api.get(`${scannerApi}/daily-report`); const p = parseResponse(r); if (p.success) dailyReport.value = p.data } catch { /* ignore */ } }

  // ==================== 📌 对比模式 ====================
  const compareVisible = ref(false)
  const compareData = ref<any>(null)
  const compareLoading = ref(false)
  async function loadCompare() { compareLoading.value = true; try { const r = await api.get(`${scannerApi}/strategy-params-compare`); const p = parseResponse(r); if (p.success) { compareData.value = p.data; compareVisible.value = true } } catch { /* ignore */ } finally { compareLoading.value = false } }

  const toggleDryRun = () => { tradeMode.value = tradeMode.value === 'dry_run' ? 'simulated' : 'dry_run' }
  const cumulativePnl = computed(() => core.totalPnl.value)

  // ==================== 📌 模板兼容/stub 属性 ====================
  const signalTraceVisible = ref(false)
  const layerDebugVisible = ref(false)
  const layerDebugData = ref<any>(null)
  const layerDebugLoading = ref(false)
  function openLayerDebug(_sig: any) { layerDebugVisible.value = true }
  function signalStatusTag(status?: string): { type: 'success' | 'warning' | 'info' | 'danger'; text: string } { const map: Record<string, { type: 'success' | 'warning' | 'info' | 'danger'; text: string }> = { pending: { type: 'warning', text: '待执行' }, executed: { type: 'success', text: '已执行' }, expired: { type: 'info', text: '已过期' }, rejected: { type: 'danger', text: '已拒绝' } }; return map[status || ''] || { type: 'info', text: status || '未知' } }
  const scanTraceVisible = computed({ get: () => signalTraceVisible.value, set: (v: boolean) => { signalTraceVisible.value = v } })
  const scanTraceData = computed(() => scanTrace.scanTraceDetail?.value || null)
  const scanTraceCode = computed(() => (scanTraceData.value as any)?.ts_code || '')
  function openScanTrace(scanId: string | number) { scanTrace.fetchScanTrace(String(scanId)); signalTraceVisible.value = true }
  const formatLayerTrace = (trace: Record<string, any>): string[] => { if (!trace) return ['无链路数据']; return Object.entries(trace).map(([layer, info]) => { const applied = typeof info === 'object' && info !== null && (info as any).applied !== undefined ? ((info as any).applied ? '✅' : '⏭️') : ''; const detail = typeof info === 'object' && info !== null ? (info as any).detail || (info as any).reason || '' : String(info); return `${applied} ${layerLabel(layer)}: ${detail}` }) }
  const formatDecisionDetail = (detail: Record<string, any>): string[] => { if (!detail) return []; return Object.entries(detail).map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`) }
  const layerLabel = (k: string | number) => { const key = String(k); const label = pipelineLabels[key]; if (!label) return key; const prefix = key.split('_')[0]; return prefix + ' ' + label }
  const layerDesc = (_layer: string | number, _data: any): string => ''
  const reviewDate = ref('')
  const reviewHero = ref<any>(null)
  const reviewForward = ref<any>(null)
  const openWeeklyReport = () => { weeklyReportVisible.value = true }
  const saveSnapshot = async () => { try { await api.post(`${scannerApi}/snapshot`); ElMessage.success('快照已保存') } catch { /* ignore */ } }
  const backtestRunning = ref(false)
  const liveBacktestDiff = ref<any>(null)
  const executionQuality = ref<any>(null)
  const tradeAttributions = ref<any[]>([])
  const paramDriftData = ref<any>(null)
  const factorEffectData = ref<any>(null)
  const exportTradeLog = () => { /* stub */ }
  const disciplineCheck = ref<any>(null)
  const weeklyReportData = computed<Record<string, any>>(() => review.weeklyReviewData?.value as Record<string, any> || {})

  // 生命周期
  onMounted(async () => {
    try { await Promise.all([core.fetchScanner(), core.fetchStrategies(), core.fetchHealth()]) } catch(e) { console.error('[Mount] fetch error:', e); ElMessage.warning('数据加载失败，请检查连接后刷新') }
    try { core.fetchLimitPools(); core.fetchDataSources(); autoTrade.fetchPerformanceHistory(); core.mount() } catch(e) { console.error('[Mount] setup error:', e); ElMessage.error('实时连接建立失败') }
    core.setupStoreWatchers(watch)
  })
  onUnmounted(() => { core.unmount() })

  return {
    // 核心状态
    loading, autoRefresh, soundEnabled, status, signals, positions, timeline, orders,
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
    autoTrades: autoTrade.autoTrades, paramCompare: autoTrade.paramCompare,
    paramCompareLoading: autoTrade.paramCompareLoading,
    scanConfig: autoTrade.scanConfig, scanConfigLoading: autoTrade.scanConfigLoading,
    pnlOption: autoTrade.pnlOption,
    updatePnlHistory: autoTrade.updatePnlHistory,
    fetchPerformanceHistory: autoTrade.fetchPerformanceHistory,
    fetchAutoTrades: autoTrade.fetchAutoTrades,
    fetchParamCompare: autoTrade.fetchParamCompare,
    fetchScanConfig: autoTrade.fetchScanConfig,
    perfChartOption, dailyReportVisible, weeklyReportVisible,
    // 盘前 (子composable)
    ...premarket,
    // 扫描追踪 (子composable)
    ...scanTrace,
    // 复盘 (子composable)
    ...review,
    pnlHistory, perfData,
    // 历史
    historyDate, historyData, historyLoading, loadHistory,
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
    saveStrategy, toggleScanHour,
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
    // 格式化方法
    formatLayerTrace, formatDecisionDetail,
    // 层级调试
    layerDebugVisible, layerDebugData, openLayerDebug, layerDebugLoading,
    // 追踪弹窗别名
    scanTraceVisible, scanTraceData, scanTraceCode, signalTraceVisible,
    openScanTrace, signalStatusTag,
    // 复盘stub
    reviewDate, reviewHero, reviewForward, openWeeklyReport, saveSnapshot,
    backtestRunning, liveBacktestDiff, executionQuality,
    tradeAttributions, paramDriftData, factorEffectData, exportTradeLog,
    disciplineCheck,
    // 工具
    strategyMeta, formatRemaining, factorLabel, layerLabel, layerDesc,
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
  }
}
