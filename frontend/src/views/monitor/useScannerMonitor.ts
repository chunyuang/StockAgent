import { ref, computed, reactive, watch, nextTick } from 'vue'
import {
  ElButton, ElTag, ElEmpty,
  ElSwitch, ElInputNumber, ElSlider,
  ElTabs, ElTabPane, ElDialog, ElMessage, ElBadge,
  ElInput, ElSelect, ElOption, ElDatePicker,
  ElMessageBox,
} from 'element-plus'
import { api } from '@/api/client'
import { useThemeStore } from '@/stores/theme'
import { useScannerStore } from '@/stores/scanner'
import { useWebSocket } from '@/hooks/useWebSocket'
import {
  strategyMeta, strategyCN,
  pipelineLabels, modeMeta, factorLabel,
  parseResponse, signalRemaining as _signalRemaining, formatRemaining,
  normalizePct, formatSlTp,
} from '@/utils/scanner'

export function useScannerMonitor() {

/**
 * MarketMonitorView — 超短量化实盘监控 (3列布局)
 * 左: 策略控制+快捷操作 / 中: 信号+行情 / 右: 持仓+统计
 * 底: 时间线 / 顶: 状态栏
 */

const loading = ref(false), autoRefresh = ref(true), soundEnabled = ref(false)
// 【v2.9.49】P2修复: fetchScanner并发控制,防止请求叠加
let fetchScannerAbort: AbortController | null = null
let fetchScannerRunning = false
const themeStore = useThemeStore()
const scannerStore = useScannerStore() // 【Phase4.1:Scanner Store】
const wsHook = useWebSocket() // 【P0-3】统一WS连接管理, 替代原始WebSocket
watch(() => themeStore.isDark, () => { /* theme changes auto-propagate via CSS vars */ })
let refreshTimer: any = null
// 【P0-3】WS连接已由useWebSocket hook统一管理, 不再自行创建
// scanner事件通过Scanner Store分发, 不再直接处理ws.onmessage
let _wsSubscribed = false
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
const layerDesc = (layer: string, data: any): string => {
  const inp = data?.input || 0, out = data?.output || 0, rej = data?.rejected || 0
  const descs: Record<string, () => string> = {
    'L1_force_empty': () => {
      if (rej > 0 && inp > 0 && out === 0) return `⚠️ 触发强制空仓! ${inp}只全部禁止买入`
      if (inp > 0) return `${inp}只通过 (未触发: 跌停<80且涨停>10且大盘跌<3%)`
      return '未执行'
    },
    'L2_special_period': () => {
      if (inp > 0 && out < inp) return `仓位系数下调至${out}%(月末/季末/周五/节前)`
      if (inp > 0) return '仓位系数=100% (无特殊时期)'
      return '未执行'
    },
    'L3_sentiment': () => {
      if (rej > 0) return `冰点期 → 暂停半路追涨${rej}只, 仓位≈25%`
      if (inp > 0 && out < inp) return `情绪偏低 → 仓位系数下调`
      if (inp > 0) return '情绪正常(≥70分) → 仓位100%'
      return '未执行'
    },
    'L4_premarket': () => {
      if (rej > 0) return `${inp}→${out}: 排除${rej}只(ST/退市/次新<60天/低流动性<500万)`
      if (inp > 0) return `${inp}只全部通过(ST/退市/次新/低流动性检查)`
      return '未执行'
    },
    'L5_auction': () => {
      if (rej > 0) return `${inp}→${out}: 排除${rej}只(高开>7%/低开<-5%/首板竞价<2%)`
      if (inp > 0) return `${inp}只竞价正常(无极端高开低开)`
      return '未执行'
    },
    'L6_strategy': () => {
      if (out > 0) return `${inp}→${out}: ${out}个候选通过策略量能筛选`
      if (inp > 0) return `${inp}个候选, 无一通过策略条件`
      return '未执行(策略筛选由上游完成)'
    },
    'L7_ranking': () => {
      if (rej > 0) return `${inp}→${out}: 排序+去重截断${rej}只(最多保留10候选)`
      if (inp > 0) return `${inp}只排序通过(未超上限)`
      return '未执行'
    },
    'L8_position': () => {
      if (inp > 0) return '仓位充足 → 总仓位≤70%, 单票≤20%'
      return '仓位控制(总≤70%/单票≤20%)'
    },
  }
  const fn = descs[layer]
  return fn ? fn() : ''
}
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
const premarketMarketSnapshot = ref<any>({})
const premarketSentiment = ref<any>({})
const premarketStrategyGroups = ref<any[]>([])
const premarketHitRate = ref<Record<string, any>>({})
const premarketGroupMode = ref<'strategy' | 'list'>('strategy')
const premarketDebugMode = ref(false)
const premarketGroupExpanded = ref<Record<string, boolean>>({})
const premarketFunnel = ref<any>({})
const premarketBlockedReasons = ref<Record<string, number>>({})
const premarketCacheSource = ref('')
const premarketLimitPools = ref<any>({})
const premarketPositionGaps = ref<any[]>([])
const premarketAnalysis = ref<any>(null)

// ==================== 扫描追踪Tab ====================
const scanHistory = ref<any[]>([])
const selectedScanIdx = ref(-1)
const scanTraceDetail = ref<any>(null)
const scanHistoryLoading = ref(false)
const scanTraceDate = ref('')  // 日期过滤器
const scanTraceHasData = ref<string[]>([])  // 有数据的日期列表
const scanTraceFilter = ref<'passed' | 'rejected' | 'summary'>('passed')
const scanTraceLoadingMore = ref(false)

const scanHourCollapse = ref<Record<string, boolean>>({})  // 小时折叠状态

// 按小时分组扫描记录，最新小时展开，其他折叠
const scanHistoryByHour = computed(() => {
  if (!scanHistory.value.length) return []
  const hourMap = new Map<string, any[]>()
  for (const s of scanHistory.value) {
    const t = s.scan_time || s.time || ''
    const hour = t.length > 11 ? t.substring(11, 13) : '??'
    if (!hourMap.has(hour)) hourMap.set(hour, [])
    hourMap.get(hour)!.push(s)
  }
  const hours = [...hourMap.keys()].sort((a, b) => b.localeCompare(a))  // 最新的小时在前
  const latestHour = hours[0]
  return hours.map(h => ({
    hour: h,
    items: hourMap.get(h) || [],
    collapsed: scanHourCollapse.value[h] ?? (h !== latestHour)  // 默认：最新展开，其他折叠
  }))
})

function toggleScanHour(hour: string) {
  scanHourCollapse.value[hour] = !(scanHourCollapse.value[hour] ?? true)
}


// ==================== 复盘Tab ====================
const reviewTab = ref<'daily' | 'weekly' | 'monthly'>('daily')
const reviewDate = ref(new Date().toISOString().slice(0, 10))
const dailyReportData = ref<any>(null)
const weeklyReportData = ref<any>(null)
const tradeAttributions = ref<any[]>([])
const reviewLoading = ref(false)
const executionQuality = ref<any>(null)
const liveBacktestDiff = ref<any[]>([])
const reviewHero = ref<any>(null)  // Hero Banner数据
const disciplineCheck = ref<any>(null)  // 纪律检查数据
const reviewForward = ref<any>(null)  // 前瞻建议数据
const backtestRunning = ref(false)  // 回测运行中
const deviationData = ref<any>(null)  // P1偏差归因
const weeklyReviewData = ref<any>(null)  // P2周复盘
const monthlyReviewData = ref<any>(null)  // P2月复盘
const paramDriftData = ref<any>(null)  // P2参数漂移
const factorEffectData = ref<any>(null)  // P2因子效果
const closedLoopData = ref<any>(null)  // P2闭环建议

async function runBacktest() {
  backtestRunning.value = true
  try {
    const r = await api.post(`${scannerApi}/run-backtest`, { period: '2025Q1' })
    const p = parseResponse(r)
    if (p.success) {
      ElMessage.success(p.message || '回测已启动')
      setTimeout(() => { fetchReviewData() }, 30000)
    } else { ElMessage.error(p.message || '回测启动失败') }
  } catch { ElMessage.error('回测启动失败') }
  finally { backtestRunning.value = false }
}

async function runSamePeriodBacktest() {
  backtestRunning.value = true
  try {
    const r = await api.post(`${scannerApi}/backtest-same-period`, {})
    const p = parseResponse(r)
    if (p.success) {
      ElMessage.success(p.message || '同区间回测已启动')
      setTimeout(() => { fetchReviewData() }, 60000)
    } else { ElMessage.error(p.message || '回测启动失败') }
  } catch { ElMessage.error('回测启动失败') }
  finally { backtestRunning.value = false }
}

async function saveParamSnapshot() {
  try {
    const r = await api.get(`${scannerApi}/param-snapshot`)
    const p = parseResponse(r)
    if (p.success) ElMessage.success('参数快照已保存')
    else ElMessage.error(p.message || '保存失败')
  } catch { ElMessage.error('保存失败') }
}

// ==================== 情绪Tab ====================
const sentimentMode = ref<'intraday' | 'daily' | 'weekly' | 'monthly'>('daily')
const sentimentDate = ref(new Date().toISOString().slice(0, 10))
const hoveredPoint = ref<any>(null)
// 每个模式独立缓存, 切换时不会清空
const sentimentCache = reactive<Record<string, any[]>>({})
const sentimentTradesCache = reactive<Record<string, any[]>>({})
const sentimentTimeline = computed(() => sentimentCache[sentimentMode.value] || [])
const sentimentTrades = computed(() => sentimentTradesCache[sentimentMode.value] || [])
// displayTimeline: 直接用当前模式数据
// 日内无数据时回退显示日线
const displayTimeline = computed(() => {
  const data = sentimentTimeline.value
  // 日内模式: 有数据(即使score=null)直接用, 无数据才fallback日线
  if (sentimentMode.value === 'intraday' && !data.length) {
    const dailyData = sentimentCache['daily'] || []
    return dailyData.slice(-60)
  }
  return data
})
const isIntradayFallback = computed(() => sentimentMode.value === 'intraday' && !sentimentTimeline.value.length && (sentimentCache['daily'] || []).length > 0)
// 日内模式candidates最大值(用于归一化Y轴)
const intradayMaxCand = computed(() => {
  if (sentimentMode.value !== 'intraday') return 0
  const data = displayTimeline.value
  if (!data.length) return 0
  return Math.max(...data.map(p => p.candidates || 0), 1)
})
// X轴标签: 采样+可读格式
const xAxisLabels = computed(() => {
  const data = displayTimeline.value
  if (!data.length) return []
  const maxLabels = sentimentMode.value === 'intraday' ? 6 : 8
  const step = Math.max(Math.ceil(data.length / maxLabels), 1)
  const sampled = data.filter((_, idx) => idx % step === 0)
  return sampled.map(p => {
    const d = p.date || ''
    if (sentimentMode.value === 'intraday') {
      return p.time?.substring(11, 16) || ''
    } else if (sentimentMode.value === 'weekly') {
      // "2024-W19" → 从date推算月/日显示
      const wi = d.indexOf('-W')
      if (wi >= 0) {
        const yr = d.substring(2, 4)
        const wk = parseInt(d.substring(wi + 2)) || 1
        // ISO周→大概月份: week*7/30 粗估
        const mon = Math.min(Math.ceil(wk * 7 / 30), 12)
        return yr + '/' + String(mon).padStart(2, '0')
      }
      return d
    } else if (sentimentMode.value === 'monthly') {
      // "202601" → "26/01"
      return d.length >= 6 ? d.substring(2, 4) + '/' + d.substring(4, 6) : d
    } else {
      // "20260211" → "02/11"
      return d.length >= 8 ? d.substring(4, 6) + '/' + d.substring(6, 8) : d
    }
  })
})
const sentimentMatrix = ref<any>(null)
const sentimentRecommendations = ref<any[]>([])
const sentimentLoading = ref(false)
const sentimentLive = ref<any>(null)  // 实时情绪快照

// 情绪阶段指南(固定数据)
const phaseGuide = computed(() => {
  const cur = sentimentLive.value?.period_label || ''
  return [
    { name: '高潮', icon: '🔥', range: '≥70分', color: '#f56c6c', position: '100%', canOpen: '✅ 全部', strategy: '所有策略开放', advice: '满仓操作，可追涨打板、龙头低吸、跌停翘板', active: cur.includes('高潮') },
    { name: '分化', icon: '⚖️', range: '55-70分', color: '#409eff', position: '50-70%', canOpen: '✅ 精选', strategy: '仅龙头低吸+半路追涨', advice: '降低仓位，只做最强龙头，避免跟风股', active: cur.includes('分化') },
    { name: '震荡', icon: '🌊', range: '40-55分', color: '#e6a23c', position: '25-40%', canOpen: '⚠️ 轻仓', strategy: '仅龙头低吸(小仓)', advice: '轻仓试错，严格止损3%，快进快出', active: cur.includes('震荡') },
    { name: '冰点', icon: '❄️', range: '<40分', color: '#67c23a', position: '0%', canOpen: '❌ 禁止', strategy: '空仓观望', advice: '禁止新开仓，持仓止损优先，等待情绪回暖', active: cur.includes('冰点') },
  ]
})

// 情绪降级调仓规则
const downgradeRules = [
  { from: '分化', to: '冰点', action: '清低利润', desc: '利润<3%的全部卖出' },
  { from: '高潮', to: '分化', action: '减仓50%', desc: '保留核心仓位' },
  { from: '高潮', to: '冰点', action: '清低利润', desc: '急转直下，保命优先' },
  { from: '震荡', to: '冰点', action: '清低利润', desc: '利润<5%的全部卖出' },
  { from: '分化', to: '震荡', action: '减仓60%', desc: '仅保留最强持仓' },
  { from: '高潮', to: '震荡', action: '减仓50%', desc: '市场转弱，保留核心' },
]

const phaseColors: Record<string, string> = { '高潮': '#f56c6c', '分化': '#409eff', '震荡': '#e6a23c', '冰点': '#67c23a' }

// 基于当前情绪的智能建议
const sentimentAdvice = computed(() => {
  const s = sentimentLive.value
  if (!s) return '选择日期后查看建议'
  const score = s.score || 0
  const lu = s.limit_up_count || 0
  const ld = s.limit_down_count || 0
  if (score >= 70) return `市场高潮，涨停${lu}只，赚钱效应强。可满仓操作，所有策略开放。注意高潮末端可能突然分化，设好止盈。`
  if (score >= 55) return `市场分化，涨停${lu}只跌停${ld}只。建议降仓位至50-70%，只做最强龙头，避免追高跟风股。`
  if (score >= 40) return `市场震荡，涨停${lu}只跌停${ld}只。建议轻仓25-40%试错，严格止损3%，快进快出，不恋战。`
  return `市场冰点，跌停${ld}只，极度弱势。建议空仓观望，禁止新开仓。持仓执行止损，等待情绪回暖信号。`
})

// ==================== 自动交易 + 参数对比 ====================
const autoTrades = ref<any[]>([])
const paramCompare = ref<any>(null)

// ==================== 情绪Tab fetch ====================
async function fetchSentimentData() {
  sentimentLoading.value = true
  try {
    const opts = { timeout: 15000 }
    const dateParam = sentimentDate.value.replace(/-/g, '')
    const [tlRes, matRes, liveRes] = await Promise.allSettled([
      api.get(`${scannerApi}/sentiment-timeline?date=${dateParam}&mode=${sentimentMode.value}`, opts),
      api.get(`${scannerApi}/sentiment-strategy-matrix?date=${dateParam}`, opts),
      api.get(`${scannerApi}/market-sentiment?date=${dateParam}`, opts),
    ])
    if (tlRes.status === 'fulfilled') { const p = parseResponse(tlRes.value); if (p.success) { sentimentCache[sentimentMode.value] = p.data?.points || []; sentimentTradesCache[sentimentMode.value] = p.data?.trades || [] } }
    if (matRes.status === 'fulfilled') { const p = parseResponse(matRes.value); if (p.success) { sentimentMatrix.value = p.data?.matrix || {}; sentimentRecommendations.value = p.data?.recommendations || [] } }
    if (liveRes.status === 'fulfilled') { const p = parseResponse(liveRes.value); if (p.success) sentimentLive.value = p.data }
  } catch { /* ignore */ }
  finally { sentimentLoading.value = false }
}
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
    const url = premarketDebugMode.value ? `${scannerApi}/debug/premarket-sim` : `${scannerApi}/premarket-status`
    const r = await api.get(url)
    const p = parseResponse(r)
    if (p.success && p.data) {
      premarketSignals.value = p.data.auction_signals || []
      premarketStatus.value = premarketDebugMode.value ? 'debug' : (p.data.status || 'off')
      premarketCandidates.value = p.data.candidates || []
      auctionTopGainers.value = p.data.top_gainers || []
      premarketMarketSnapshot.value = p.data.market_snapshot || {}
      premarketSentiment.value = p.data.sentiment || {}
      premarketStrategyGroups.value = p.data.strategy_groups || []
      premarketHitRate.value = p.data.historical_hit_rate || {}
      premarketFunnel.value = p.data.funnel || {}
      premarketBlockedReasons.value = p.data.blocked_reasons || {}
      premarketCacheSource.value = p.data.cache_source || ''
      premarketLimitPools.value = p.data.limit_pools || {}
      premarketPositionGaps.value = p.data.position_gaps || []
      premarketAnalysis.value = p.data.analysis || null
    }
  } catch { /* ignore */ }
}

// ==================== 扫描追踪Tab 数据 ====================
async function fetchScanTraceDates() {
  try {
    const r = await api.get(`${scannerApi}/scan-dates`, { timeout: 10000 })
    const p = parseResponse(r)
    if (p.success && p.data?.length) {
      scanTraceHasData.value = p.data  // [{date, count, is_debug}]
    }
  } catch {}
}
function scanDateCellClass(date: Date) {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  const key = `${y}${m}${d}`
  const item = scanTraceHasData.value.find((x: any) => x.date === key)
  if (!item) return ''
  return item.is_debug ? 'has-scan-debug' : 'has-scan-data'
}

async function fetchScanHistory() {
  if (!scanTraceDate.value) { scanHistory.value = []; scanTraceDetail.value = null; return }
  scanHistoryLoading.value = true
  scanTraceDetail.value = null
  selectedScanIdx.value = -1
  try {
    const r = await api.get(`${scannerApi}/scan-traces?limit=200&date=${scanTraceDate.value.replace(/-/g, '')}`, { timeout: 15000 })
    const p = parseResponse(r)
    if (p.success && p.data?.length) {
      scanHistory.value = p.data
    } else {
      scanHistory.value = []
    }
  } catch { scanHistory.value = [] }
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
    const promises: Promise<any>[] = []
    const opts = { timeout: 15000 }
    const today = new Date().toISOString().slice(0, 10)
    const dateParam = reviewDate.value.replace(/-/g, '')
    const isToday = reviewDate.value === today
    
    // ===== 通用数据 =====
    promises.push(
      api.get(`${scannerApi}/review-hero?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) reviewHero.value = p.data }),
      api.get(`${scannerApi}/backtest-compare?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) liveBacktestDiff.value = p.data || [] }),
    )
    
    // ===== 按周期差异化 =====
    if (reviewTab.value === 'daily') {
      // 日复盘: 执行质量 + 纪律检查 + 偏差归因(纪律+滑点) + 前瞻
      if (isToday) {
        promises.push(
          api.get(`${scannerApi}/daily-report`, opts).then(r => { const p = parseResponse(r); if (p.success) dailyReportData.value = p.data }),
          api.get(`${scannerApi}/trade-attribution?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) tradeAttributions.value = p.data || [] }),
        )
      } else {
        promises.push(
          api.get(`${scannerApi}/historical-review?date=${dateParam}`, opts).then(r => {
            const p = parseResponse(r)
            if (p.success && p.data) {
              const d = p.data
              dailyReportData.value = {
                date: reviewDate.value,
                account: { today_profit: 0, position_ratio: 0, available_cash: 0 },
                positions: { count: 0, strategy_summary: d.strategy_summary, top_profit: [], top_loss: [] },
                trades: { buy: d.scan_stats?.buy_count || 0, sell: d.scan_stats?.sell_count || 0, total_amount: 0 },
                win_rate: Object.values(d.strategy_summary || {}).reduce((s: number, v: any) => s + v.win_count, 0) / Math.max(Object.values(d.strategy_summary || {}).reduce((s: number, v: any) => s + (v.win_count || 0) + (v.loss_count || 0), 0), 1) * 100,
                stop_loss_count: Object.values(d.strategy_summary || {}).reduce((s: number, v: any) => s + (v.stop_loss_count || 0), 0),
                take_profit_count: Object.values(d.strategy_summary || {}).reduce((s: number, v: any) => s + (v.take_profit_count || 0), 0),
                scanner_stats: d.scan_stats, funnel_summary: d.funnel_summary, sentiment_snapshot: d.sentiment_snapshot,
              }
            }
          }),
          api.get(`${scannerApi}/trade-attribution?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) tradeAttributions.value = p.data || [] }),
        )
      }
      // 日复盘专有: 纪律检查 + 偏差归因(执行偏差)
      promises.push(
        api.get(`${scannerApi}/discipline-check?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) disciplineCheck.value = p.data }),
        api.get(`${scannerApi}/deviation-attribution?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) deviationData.value = p.data }),
        api.get(`${scannerApi}/review-forward?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) reviewForward.value = p.data }),
      )
    } else if (reviewTab.value === 'weekly') {
      // 周复盘: 策略效能 + 偏差归因(策略偏差) + 偏差趋势
      promises.push(
        api.get(`${scannerApi}/review-weekly?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) weeklyReviewData.value = p.data }),
        api.get(`${scannerApi}/deviation-attribution?start_date=&end_date=`, opts).then(r => { const p = parseResponse(r); if (p.success) deviationData.value = p.data }),
      )
      // 周复盘也需要纪律和前瞻
      promises.push(
        api.get(`${scannerApi}/discipline-check?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) disciplineCheck.value = p.data }),
        api.get(`${scannerApi}/review-forward?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) reviewForward.value = p.data }),
      )
    } else if (reviewTab.value === 'monthly') {
      // 月复盘: 系统偏差 + 参数漂移 + 行为漂移 + 因子效果 + 闭环建议
      promises.push(
        api.get(`${scannerApi}/review-monthly?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) monthlyReviewData.value = p.data }),
        api.get(`${scannerApi}/param-drift`, opts).then(r => { const p = parseResponse(r); if (p.success) paramDriftData.value = p.data }),
        api.get(`${scannerApi}/factor-effectiveness?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) factorEffectData.value = p.data }),
        api.get(`${scannerApi}/review-closed-loop?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) closedLoopData.value = p.data }),
      )
      promises.push(
        api.get(`${scannerApi}/review-forward?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) reviewForward.value = p.data }),
        api.get(`${scannerApi}/discipline-check?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) disciplineCheck.value = p.data }),
      )
    }
    
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
const activeTab = ref<'guide' | 'trading' | 'premarket' | 'scan-trace' | 'review' | 'risk' | 'sentiment' | 'history' | 'ops'>('guide')
watch(activeTab, (tab) => {
  try {
    if (tab === 'premarket') fetchPremarketData()
    if (tab === 'scan-trace') { fetchScanTraceDates(); fetchScanHistory() }
    if (tab === 'review') { fetchReviewData(); fetchParamCompare() }
    if (tab === 'sentiment') { fetchSentimentData() }
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
async function fetchScanner() { if (fetchScannerRunning) return; fetchScannerRunning = true; try { if (fetchScannerAbort) fetchScannerAbort.abort(); fetchScannerAbort = new AbortController(); const r = await api.get(`${scannerApi}/all`, { signal: fetchScannerAbort.signal }); const p = parseResponse(r); if (p.success) { const d = p.data; if (d.signals && signals.value.length > 0 && d.signals.length > signals.value.length) { playSignalSound() } if (d.status) status.value = d.status; if (d.signals) signals.value = d.signals; if (d.positions) positions.value = d.positions; if (d.timeline) timeline.value = d.timeline; if (d.orders) orders.value = d.orders } fetchLimitPools(); updatePnlHistory() } catch (e: any) { if (e.name !== 'CanceledError' && e.name !== 'AbortError') console.error(e) } finally { fetchScannerRunning = false } }
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

onMounted(async () => { try { await Promise.all([fetchScanner(), fetchStrategies(), fetchHealth()]) } catch(e) { console.error('[Mount] fetch error:', e); ElMessage.warning('数据加载失败，请检查连接后刷新') } try { fetchLimitPools(); fetchDataSources(); fetchPerformanceHistory(); /* P0-3: WS由useWebSocket hook管理 */ wsHook.connect(); if (!_wsSubscribed) { wsHook.send({ type: 'subscribe_scanner' }); _wsSubscribed = true } } catch(e) { console.error('[Mount] setup error:', e); ElMessage.error('实时连接建立失败') } nowTimer = setInterval(() => { nowMs.value = Date.now() }, 1000); const getRefreshInterval = () => { const n = new Date(), h = n.getHours(), m = n.getMinutes(); const isTrading = (h === 9 && m >= 30) || (h >= 10 && h < 15) || (h === 15 && m === 0); return isTrading ? 5000 : 60000 }; refreshTimer = setInterval(() => { if (!autoRefresh.value || wsHook.isConnected.value) return; fetchScanner(); fetchHealth() }, getRefreshInterval()) })
onUnmounted(() => { if (refreshTimer) clearInterval(refreshTimer); if (nowTimer) clearInterval(nowTimer); /* P0-3: WS由hook管理引用计数, 不需手动disconnect */ _wsSubscribed = false })
// 【P0-3+4】WS统一: connectWS/disconnectWS已删除
// WS连接由useWebSocket hook管理, scanner事件由hook分发到Scanner Store
// 断线重连+补发由hook+store统一处理, 不再有两套WS连接
// Store数据变化由watch监听, 本地ref自动同步
watch(() => scannerStore.signals, (v) => { if (v?.length) signals.value = v }, { deep: true })
watch(() => scannerStore.positions, (v) => { if (v?.length) positions.value = v }, { deep: true })
watch(() => scannerStore.timeline, (v) => { if (v?.length) timeline.value = v }, { deep: true })
watch(() => scannerStore.status, (v) => { if (v) status.value = { ...status.value, ...v } }, { deep: true })
// Scanner异常事件弹窗
watch(() => scannerStore.lastError, (v) => { if (v) ElMessage({ type: 'error', message: `Scanner异常: ${v}`, duration: 8000 }) })
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

  return {
    accountInfo,
    activeTab,
    auctionTopGainers,
    auditLog,
    auditLogLoading,
    autoTrades,
    backtestRunning,
    brokers,
    cancelReplay,
    circuitBreakerPaused,
    closedLoopData,
    closedPositions,
    compareData,
    compareLoading,
    compareVisible,
    configApi,
    confirmData,
    confirmLoading,
    confirmReplay,
    confirmVisible,
    cumulativePnl,
    dailyReport,
    dailyReportData,
    dailyReportVisible,
    dailySettlement,
    dataSources,
    deviationData,
    disciplineCheck,
    displayTimeline,
    distanceToStopLoss,
    dryRun,
    editDialogVisible,
    editParams,
    editRiskParams,
    editTab,
    editingStrategy,
    emergencyLiquidate,
    emergencyLiquidating,
    executeManualTrade,
    executionQuality,
    exportTradeLog,
    factorEffectData,
    fetchAll,
    fetchAuditLog,
    fetchAutoTrades,
    fetchDailyReport,
    fetchDataSources,
    fetchHealth,
    fetchLimitPools,
    fetchParamCompare,
    fetchPerformanceHistory,
    fetchPremarketData,
    fetchReviewData,
    fetchScanConfig,
    fetchScanHistory,
    fetchScanTrace,
    fetchScanTraceDates,
    fetchScanner,
    fetchScannerFull,
    fetchSentimentData,
    fetchStrategies,
    fetchWeeklyReport,
    filteredSignals,
    focusIndex,
    forceScan,
    formatDecisionDetail,
    formatLayerTrace,
    getRefreshInterval,
    globalRisk,
    handleConfirm,
    healthCN,
    healthClass,
    healthData,
    healthEmoji,
    healthStatus,
    historyData,
    historyDate,
    historyLoading,
    hoveredPoint,
    intradayMaxCand,
    isIntradayFallback,
    isRunning,
    layerDebugData,
    layerDebugLoading,
    layerDebugVisible,
    layerLabel,
    limitPoolTab,
    limitPools,
    liveBacktestDiff,
    loadCompare,
    loadHistory,
    loading,
    manualQuote,
    manualScan,
    manualTrade,
    monthlyReviewData,
    nowMs,
    onManualCodeChange,
    onModeChange,
    openEditDialog,
    openLayerDebug,
    openScanTrace,
    openTradeAudit,
    openTradeDetail,
    openWeeklyReport,
    orders,
    paramCompare,
    paramCompareLoading,
    paramDriftData,
    pauseCircuitBreaker,
    perfData,
    phaseGuide,
    playSignalSound,
    pnlHistory,
    pnlOption,
    posSort,
    positionRatio,
    positions,
    premarketAnalysis,
    premarketBlockedReasons,
    premarketCacheSource,
    premarketCandidates,
    premarketDebugMode,
    premarketFunnel,
    premarketGroupExpanded,
    premarketGroupMode,
    premarketHitRate,
    premarketLimitPools,
    premarketMarketSnapshot,
    premarketPositionGaps,
    premarketSentiment,
    premarketSignals,
    premarketStatus,
    premarketStrategyGroups,
    qaSectionCollapsed,
    quickBuy,
    quickSell,
    rejectionReasonCN,
    replayDate,
    replayDateInput,
    replayDateVisible,
    resetAccount,
    resetCircuitBreaker,
    resetStrategy,
    reviewDate,
    reviewForward,
    reviewHero,
    reviewLoading,
    reviewTab,
    riskBarCollapsed,
    runBacktest,
    runSamePeriodBacktest,
    saveParamSnapshot,
    saveSnapshot,
    saveStrategy,
    saving,
    scanConfig,
    scanConfigLoading,
    scanDateCellClass,
    scanHistory,
    scanHistoryByHour,
    scanHistoryLoading,
    scanHourCollapse,
    scanTraceCode,
    scanTraceData,
    scanTraceDate,
    scanTraceDetail,
    scanTraceFilter,
    scanTraceHasData,
    scanTraceLoadingMore,
    scanTraceVisible,
    scannerApi,
    selectedScanIdx,
    sellAllPositions,
    sentimentAdvice,
    sentimentCache,
    sentimentDate,
    sentimentLive,
    sentimentLoading,
    sentimentMatrix,
    sentimentMode,
    sentimentRecommendations,
    sentimentTimeline,
    sentimentTrades,
    sentimentTradesCache,
    setTrailingStop,
    showConfirm,
    sigRemaining,
    signalFilter,
    signalStatusTag,
    signalTraceVisible,
    signals,
    sortedPositions,
    startScanner,
    status,
    stopScanner,
    stratCollapsed,
    stratSectionCollapsed,
    strategies,
    switchScanTraceFilter,
    timeline,
    timelineCollapsed,
    toggleDryRun,
    toggleScanHour,
    toggleStrat,
    toggleStrategy,
    totalPnl,
    tradeAttributions,
    tradeDetailVisible,
    tradeMode,
    trailEditPct,
    trailSaving,
    updatePnlHistory,
    weeklyReportData,
    weeklyReportVisible,
    weeklyReviewData,
    xAxisLabels,
  }
}

