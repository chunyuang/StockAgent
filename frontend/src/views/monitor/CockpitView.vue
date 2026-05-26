<script setup lang="ts">
/**
 * CockpitView — 驾驶舱视图 (交易员视角)
 * 
 * 布局: 
 * 顶: 状态栏(模式切换+资产+紧急平仓)
 * 左: 风控仪表盘 + 数据源状态 + 参数热更新
 * 中: 核心实时区(信号+9层管道)
 * 右: 持仓盈亏波动 + 涨跌停池
 * 底: 时间线
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import {
  ElButton, ElTag, ElProgress, ElInputNumber,
  ElEmpty,
  ElMessage, ElMessageBox, ElDialog, ElSelect, ElOption,
} from 'element-plus'
import { api } from '@/api/client'
import {
  strategyMeta, strategyCN, strategyColor, strategyIcon,
  pipelineLayers, pipelineLabels,
  modeMeta, modeLabel,
  parseResponse, signalRemaining, formatRemaining,
  formatMoney, formatPct,
} from '@/utils/scanner'

// ============ 类型 ============
interface HealthCheck { name: string; status: string; value: string; threshold: string; message: string }
interface HealthInfo { overall_status: string; checks: Record<string, HealthCheck>; alert_count: number }
interface ScanSignal { ts_code: string; stock_name: string; strategy: string; strategy_name: string; price: number; pct_chg: number; reason: string; signal_status?: string; created_at?: number }
interface PositionInfo { ts_code: string; stock_name: string; strategy: string; shares: number; available_qty: number; cost_price: number; current_price: number; profit_pct: number; profit_amount?: number; market_value?: number; stop_loss_pct?: number; take_profit_pct?: number; stop_loss_price?: number; take_profit_price?: number; distance_to_stop?: number; trailing_stop?: { high_price: number; trailing_stop_pct: number; activated: boolean; stop_price: number; activated_at?: string }; risk_level?: string; effective_stop_price?: number }
interface AccountInfo { total_assets: number; available_cash: number; market_value: number; total_profit: number }
interface TimelineItem { time: string; action: string; ts_code: string; stock_name: string; strategy: string; shares: number; price: number; reason: string; profit_pct?: number }
interface ScanTraceCandidate { ts_code: string; stock_name: string; strategy: string; strategy_name: string; price: number; pct_chg: number; final_status: string; rejection_layer?: string; rejection_reason?: string; layer_results?: Record<string, { passed: boolean; reason?: string }> }
interface ScanTrace { trade_date: string; scan_time: string; summary: Record<string, any>; candidates: ScanTraceCandidate[] }
interface LimitPools { limit_up: any[]; limit_down: any[]; broken: any[] }
interface DataSourceInfo { name: string; available: boolean; stocks: number; calls: number; limit: number; note: string }
interface StrategyParams { [key: string]: any }

// ============ 状态 ============
const scannerApi = '/scanner'
const status = ref<any>(null)
const health = ref<HealthInfo | null>(null)
const signals = ref<ScanSignal[]>([])
const positions = ref<PositionInfo[]>([])
const timeline = ref<TimelineItem[]>([])
const pnlHistory = ref<{time: string, value: number}[]>([])
const scanTraces = ref<ScanTrace[]>([])
const limitPools = ref<LimitPools>({ limit_up: [], limit_down: [], broken: [] })
const dataSources = ref<DataSourceInfo[]>([])
const strategyParams = ref<Record<string, StrategyParams>>({})
const paramExpanded = ref(false)
const editingParam = ref<string | null>(null)
const paramEdits = ref<Record<string, any>>({})
const loading = ref(false)
const autoRefresh = ref(true)
const selectedMode = ref('simulated')
const buyingSignal = ref<string | null>(null)
let refreshTimer: any = null
let ws: WebSocket | null = null
let wsReconnectTimer: any = null
const nowMs = ref(Date.now())
let nowTimer: any = null

// ============ 计算 ============
const account = computed<AccountInfo>(() => status.value?.account ?? { total_assets: 0, available_cash: 0, market_value: 0, total_profit: 0 })
const positionRatio = computed(() => account.value.market_value > 0 ? (account.value.market_value / account.value.total_assets * 100).toFixed(1) : '0')
const isRunning = computed(() => status.value?.is_running ?? false)
const tradeMode = computed(() => status.value?.trade_mode ?? 'simulated')
const tradeModeLabel = computed(() => modeMeta[tradeMode.value] || { text: tradeMode.value, color: '#909399' })

// 今日盈亏 — 从 timeline + 持仓浮盈计算
const todayPnl = computed(() => {
  const today = new Date().toLocaleDateString('zh-CN')
  let realized = 0
  for (const item of timeline.value) {
    if (!item.time) continue
    const itemDate = item.time.includes('-')
      ? new Date(item.time).toLocaleDateString('zh-CN')
      : today
    if (itemDate !== today) continue
    if (item.action === 'sell' && item.profit_pct != null && item.price > 0) {
      realized += item.profit_pct / 100 * item.shares * item.price / (1 + item.profit_pct / 100)
    }
  }
  // 加上持仓浮盈
  let floating = 0
  for (const pos of positions.value) {
    if (pos.profit_amount != null) floating += pos.profit_amount
    else if (pos.profit_pct != null && pos.cost_price > 0) {
      floating += (pos.current_price - pos.cost_price) * pos.shares
    }
  }
  return realized + floating
})

// 风控仪表盘
const healthStatus = computed(() => health.value?.overall_status ?? 'unknown')
const healthColor = computed(() => {
  const c: Record<string, string> = { healthy: '#67c23a', degraded: '#e6a23c', critical: '#f56c6c', dead: '#303133' }
  return c[healthStatus.value] || '#909399'
})
const dailyDrawdown = computed(() => {
  const dd = health.value?.checks?.drawdown
  if (!dd) return { value: 0, threshold: 5, status: 'healthy' }
  const match = dd.value?.match(/日([\d.]+)%/)
  return { value: parseFloat(match?.[1] || '0'), threshold: 5, status: dd.status }
})
const consecutiveLosses = computed(() => {
  const cb = status.value?.circuit_breaker
  return cb?.consecutive_losses ?? 0
})

// 策略健康 - 从health checks动态获取
const strategyHealthList = computed(() => {
  const checks = health.value?.checks
  if (!checks) {
    return Object.entries(strategyMeta).map(([key, meta]) => ({
      key, name: meta.cn, icon: meta.icon, status: 'unknown', color: '#909399'
    }))
  }
  const result: { key: string; name: string; icon: string; status: string; color: string }[] = []
  for (const [key, meta] of Object.entries(strategyMeta)) {
    const checkKey = Object.keys(checks).find(k => k.includes(key) || key.includes(k))
    const check = checkKey ? checks[checkKey] : null
    result.push({
      key,
      name: meta.cn,
      icon: meta.icon,
      status: check?.status || 'unknown',
      color: check?.status === 'healthy' ? '#67c23a' : check?.status === 'degraded' ? '#e6a23c' : check?.status === 'critical' ? '#f56c6c' : '#909399'
    })
  }
  return result
})

function strategyHealthIcon(status: string): string {
  const m: Record<string, string> = { healthy: '✅', degraded: '⚠️', critical: '🔴', dead: '⚫', unknown: '❓' }
  return m[status] || '❓'
}

// 获取最近scan trace的summary作为管道状态
const pipelineSummary = computed(() => {
  if (!scanTraces.value.length) return null
  return scanTraces.value[0]?.summary || null
})

// 管道层级的通过/拒绝数量
function pipelineLayerStats(layer: string): { passed: number; rejected: number; total: number } {
  const summary = pipelineSummary.value
  if (!summary || !summary[layer]) return { passed: 0, rejected: 0, total: 0 }
  const s = summary[layer]
  return { passed: s.passed ?? s.keep ?? 0, rejected: s.rejected ?? s.filtered ?? 0, total: s.total ?? s.input ?? 0 }
}

function pipelineLayerStatus(layer: string): 'pass' | 'filter' | 'idle' {
  const stats = pipelineLayerStats(layer)
  if (stats.total === 0) return 'idle'
  if (stats.rejected > 0) return 'filter'
  return 'pass'
}

// 涨跌停池统计
const limitPoolStats = computed(() => ({
  limitUp: limitPools.value.limit_up?.length ?? 0,
  limitDown: limitPools.value.limit_down?.length ?? 0,
  broken: limitPools.value.broken?.length ?? 0,
}))

// 信号详情弹窗
const signalDetail = ref<ScanSignal | null>(null)
const signalDetailVisible = ref(false)
const signalDetailTrace = ref<ScanTraceCandidate | null>(null)

function showSignalDetail(sig: ScanSignal) {
  signalDetail.value = sig
  signalDetailVisible.value = true
  signalDetailTrace.value = null
  for (const trace of scanTraces.value) {
    const candidate = trace.candidates?.find(c => c.ts_code === sig.ts_code && c.strategy === sig.strategy)
    if (candidate) {
      signalDetailTrace.value = candidate
      break
    }
  }
}

// 获取信号在特定层的trace状态
function getSignalLayerResult(layer: string): { passed: boolean; reason?: string } | null {
  if (!signalDetailTrace.value?.layer_results) return null
  return signalDetailTrace.value.layer_results[layer] || null
}

// 盈亏曲线
const perfData = ref<Array<{time:string,net_value:number,drawdown:number}>>([]) // 历史绩效
const pnlOption = computed(() => {
  const source = perfData.value.length > 0 ? perfData.value : pnlHistory.value.map(p => ({ time: p.time, net_value: p.value / 1000000 + 1, drawdown: 0 }))
  return {
    grid: { top: 10, right: 10, bottom: 20, left: 50 },
    tooltip: { trigger: 'axis' as const, formatter: (p: any) => `${p[0].axisValue}<br/>净值: ${(p[0].value).toFixed(4)}${p[1] ? '<br/>回撤: ' + p[1].value.toFixed(2) + '%' : ''}` },
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

// ============ API ============
async function fetchAll() {
  try {
    const r = await api.get(`${scannerApi}/all`)
    const { success, data } = parseResponse(r)
    if (success) {
      status.value = data.status || {}
      signals.value = data.signals || []
      positions.value = data.positions || []
      timeline.value = data.timeline || []
      if (data.status?.data_sources) dataSources.value = data.status.data_sources
      if (data.status?.trade_mode) selectedMode.value = data.status.trade_mode
      const pnl = account.value.total_profit
      pnlHistory.value.push({ time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }), value: pnl })
      if (pnlHistory.value.length > 60) pnlHistory.value = pnlHistory.value.slice(-60)
    }
  } catch (e) { /* ignore */ }
}

async function fetchHealth() {
  try {
    const r = await api.get(`${scannerApi}/health`)
    if (r?.success) health.value = r.health || null
  } catch (e) { /* ignore */ }
}

async function fetchPerformanceHistory() {
  try {
    // 先尝试MongoDB快照
    const r = await api.get(`${scannerApi}/performance-history?days=30`)
    const p = parseResponse(r)
    if (p.success && p.data?.length > 0) {
      perfData.value = p.data.map((s: any) => ({
        time: (s.timestamp || s.date || '').substring(5, 16),
        net_value: s.net_value || s.total_assets / 1000000,
        drawdown: s.drawdown_pct || 0,
      }))
      return
    }
    // fallback: 从timeline构建
    const tl = await api.get(`${scannerApi}/timeline/history?days=30`)
    const tp = parseResponse(tl)
    if (tp.success && tp.data?.length > 0) {
      let nav = 1.0
      let peak = 1.0
      const events: typeof perfData.value = []
      for (const item of tp.data) {
        const profitAmount = item.profit_amount || 0
        nav *= (1 + profitAmount / (1000000 * nav))
        peak = Math.max(peak, nav)
        const dd = nav < peak ? (nav / peak - 1) * 100 : 0
        events.push({
          time: (item.date || item.time || '').substring(0, 16),
          net_value: nav,
          drawdown: dd,
        })
      }
      perfData.value = events
    }
  } catch (e) { /* ignore */ }
}

async function fetchScanTraces() {
  try {
    const r = await api.get(`${scannerApi}/scan-traces?limit=3`)
    if (r?.success) scanTraces.value = r.data || []
  } catch (e) { /* ignore */ }
}

async function fetchLimitPools() {
  try {
    const r = await api.get(`${scannerApi}/limit-pools`)
    if (r?.success) limitPools.value = r.data || { limit_up: [], limit_down: [], broken: [] }
  } catch (e) { /* ignore */ }
}

async function fetchStrategyParams() {
  try {
    const r = await api.get(`${scannerApi}/params`)
    if (r?.success) strategyParams.value = r.data || {}
  } catch (e) { /* ignore */ }
}

// ============ 操作 ============
async function toggleScanner() {
  loading.value = true
  try {
    if (isRunning.value) {
      await ElMessageBox.confirm('确认停止扫描器？持仓将保留。', '停止扫描', { confirmButtonText: '确认停止', cancelButtonText: '取消', type: 'warning' })
      await api.post(`${scannerApi}/stop`)
      ElMessage.success('扫描器已停止')
    } else {
      const acc = account.value
      let replayDate = ''
      if (selectedMode.value === 'replay') {
        const today = new Date()
        const defaultDate = new Date(today)
        defaultDate.setDate(today.getDate() - 1)
        const dateStr = defaultDate.toISOString().slice(0, 10).replace(/-/g, '')
        try {
          const { value } = await ElMessageBox.prompt(
            '输入回放日期(YYYYMMDD格式)，将使用该日历史数据模拟实时行情',
            '🔄 回放模式',
            { confirmButtonText: '确认', cancelButtonText: '取消', inputValue: dateStr, inputPattern: /^\d{8}$/, inputErrorMessage: '请输入8位日期' }
          )
          replayDate = value
        } catch { return }
      }
      await ElMessageBox.confirm(
        `确认启动扫描器？\n模式: ${modeLabel(selectedMode.value)}${replayDate ? ' (日期: ' + replayDate + ')' : ''}\n可用资金: ${formatMoney(acc.available_cash)}\n当前持仓: ${positions.value.length}只`,
        '启动扫描',
        { confirmButtonText: '确认启动', cancelButtonText: '取消', type: 'info' }
      )
      const payload: Record<string, string> = { trade_mode: selectedMode.value }
      if (replayDate) payload.replay_date = replayDate
      await api.post(`${scannerApi}/start`, payload)
      ElMessage.success('扫描器已启动')
    }
    await fetchAll()
  } catch { /* cancelled or error */ }
  loading.value = false
}

// 持仓详情弹窗
const posDetailVisible = ref(false)
const posDetailData = ref<any>(null)
const posDetailLoading = ref(false)
const posRiskSL = ref(3.0)
const posRiskTP = ref(7.0)
const posRiskSaving = ref(false)
async function openPositionDetail(pos: PositionInfo) {
  posDetailLoading.value = true
  posDetailVisible.value = true
  try {
    const r = await api.get(`${scannerApi}/trade-detail/${pos.ts_code}`)
    if (r?.success) {
      posDetailData.value = r.data
      posRiskSL.value = r.data.position?.stop_loss_pct || 3.0
      posRiskTP.value = r.data.position?.take_profit_pct || 7.0
    }
    else posDetailData.value = { ts_code: pos.ts_code, position: { shares: pos.available_qty, cost_price: pos.avg_cost, current_price: pos.current_price, profit_pct: pos.profit_pct, strategy: pos.strategy, stop_loss_pct: pos.stop_loss_pct, take_profit_pct: pos.take_profit_pct } }
    posRiskSL.value = posDetailData.value?.position?.stop_loss_pct || 3.0
    posRiskTP.value = posDetailData.value?.position?.take_profit_pct || 7.0
  } catch { posDetailData.value = null } finally { posDetailLoading.value = false }
}

// 熔断操作
async function toggleCircuitBreaker(action: 'pause' | 'reset') {
  try {
    const label = action === 'pause' ? '暂停交易' : '恢复交易'
    await ElMessageBox.confirm(
      `确认${label}？${action === 'pause' ? '\n暂停后不会自动买入新信号，但持仓止损止盈仍正常执行。' : '\n恢复后信号将正常执行买入。'}`,
      label,
      { confirmButtonText: '确认', cancelButtonText: '取消', type: action === 'pause' ? 'warning' : 'info' }
    )
    const r = await api.post(`${scannerApi}/circuit-breaker/${action}`)
    if (r?.success) ElMessage.success(`${label}成功`)
    else ElMessage.error(r?.message || '操作失败')
    await fetchAll()
    await fetchHealth()
  } catch { /* cancelled */ }
}

// 持仓风控辅助
function riskBarWidth(pos: PositionInfo): number {
  const slPct = Math.abs(pos.stop_loss_pct || 3)
  const tpPct = pos.take_profit_pct || 7
  const range = slPct + tpPct
  const current = pos.profit_pct + slPct // 从止损线算起
  return Math.max(0, Math.min(100, current / range * 100))
}
function riskBarClass(pos: PositionInfo): string {
  const distToStop = pos.profit_pct + (pos.stop_loss_pct || 3)
  if (distToStop < 1) return 'danger'
  if (distToStop < 2) return 'warning'
  return 'safe'
}
// 【V59:追踪止损在进度条上的位置】
function trailBarPos(pos: PositionInfo): number {
  if (!pos.trailing_stop?.activated || !pos.stop_loss_pct || !pos.take_profit_pct) return 0
  const slPct = Math.abs(pos.stop_loss_pct)
  const tpPct = pos.take_profit_pct
  const trailPct = pos.trailing_stop.trailing_stop_pct * 100
  // 追踪止损距止损线的比例
  const distFromSL = slPct - trailPct  // 如: SL=3%, trail=2%, 距离=1%
  const range = slPct + tpPct
  const posOnBar = (slPct - trailPct + slPct) / range * 100  // 归一化到0-100
  // 简化: 从成本价看, 追踪止损价=(1-trailPct/100)*high_price, 在bar上的相对位置
  // 用profit_pct反推: 如果high使profit=X%, trail触发在X%-trailPct%
  return Math.max(5, Math.min(95, 50)) // 简化: 追踪止损在中间偏上
}

// 持仓快捷卖出
async function quickSell(pos: PositionInfo) {
  try {
    await ElMessageBox.confirm(
      `确认卖出？\n${pos.stock_name} ${pos.ts_code}\n盈亏: ${formatPct(pos.profit_pct)} | 数量: ${pos.available_qty}股\n现价: ¥${pos.current_price.toFixed(2)}`,
      '卖出确认',
      { confirmButtonText: '确认卖出', cancelButtonText: '取消', type: pos.profit_pct < 0 ? 'warning' : 'info' }
    )
    const r = await api.post(`${scannerApi}/trade`, {
      ts_code: pos.ts_code, stock_name: pos.stock_name,
      side: 'sell', quantity: pos.available_qty, price: pos.current_price,
      order_type: 'market', strategy: pos.strategy,
      reason: `手动卖出 ${formatPct(pos.profit_pct)}`
    })
    if (r?.success) ElMessage.success(`已卖出 ${pos.stock_name} ${pos.available_qty}股@${r.data?.filled_price?.toFixed(2)}`)
    else ElMessage.error(r?.data?.message || '卖出失败')
    await fetchAll()
  } catch { /* cancelled */ }
}

async function emergencyLiquidate() {
  try {
    await ElMessageBox.confirm('⚠️ 确认紧急平仓？所有持仓将以市价卖出！', '🚨 紧急平仓', { confirmButtonText: '确认平仓', cancelButtonText: '取消', type: 'error' })
    loading.value = true
    const r = await api.post(`${scannerApi}/emergency-liquidate`, { reason: 'GUI手动触发' })
    if (r?.success) ElMessage.success(`紧急平仓完成: ${r.data?.positions_cleared}只持仓已清空`)
    else ElMessage.error(r?.message || '平仓失败')
    await fetchAll()
  } catch { /* cancelled */ }
  loading.value = false
}

// 模式切换
async function onModeChange(mode: string) {
  if (mode === tradeMode.value) return
  try {
    let replayDate = ''
    if (mode === 'replay') {
      const today = new Date()
      const defaultDate = new Date(today)
      defaultDate.setDate(today.getDate() - 1)
      const dateStr = defaultDate.toISOString().slice(0, 10).replace(/-/g, '')
      try {
        const { value } = await ElMessageBox.prompt(
          '输入回放日期(YYYYMMDD)',
          '🔄 回放模式',
          { confirmButtonText: '确认', cancelButtonText: '取消', inputValue: dateStr, inputPattern: /^\d{8}$/, inputErrorMessage: '请输入8位日期' }
        )
        replayDate = value
      } catch { selectedMode.value = tradeMode.value; return }
    }
    await ElMessageBox.confirm(
      `确认切换到 ${modeLabel(mode)} 模式？${mode === 'gm' ? '\n⚠️ 掘金模式将进行实盘交易！' : ''}${replayDate ? '\n📅 回放日期: ' + replayDate : ''}`,
      '模式切换',
      { confirmButtonText: '确认切换', cancelButtonText: '取消', type: mode === 'gm' ? 'warning' : 'info' }
    )
    selectedMode.value = mode
    if (isRunning.value) {
      await api.post(`${scannerApi}/stop`)
      const payload: Record<string, string> = { trade_mode: mode }
      if (replayDate) payload.replay_date = replayDate
      await api.post(`${scannerApi}/start`, payload)
      ElMessage.success(`已切换到${modeLabel(mode)}模式并重启`)
      await fetchAll()
    } else {
      ElMessage.success(`模式已切换到${modeLabel(mode)}，启动时生效`)
    }
  } catch { /* cancelled */ }
}

// 快捷买入信号(增强确认)
async function quickBuySignal(sig: ScanSignal) {
  const key = sig.ts_code + sig.strategy
  buyingSignal.value = key
  try {
    // 获取策略参数
    const paramR = await api.get(`${scannerApi}/params/${sig.strategy}`)
    const sp = paramR?.success ? paramR.data : null
    const slPct = sp?.stop_loss_pct ? (sp.stop_loss_pct * 100).toFixed(1) : '3.0'
    const tpPct = sp?.take_profit_pct ? (sp.take_profit_pct * 100).toFixed(1) : '7.0'
    const holdDays = sp?.max_hold_days || '?'
    // 预估仓位
    const availCash = account.value.available_cash
    const posRatio = { halfway_chase: 0.25, first_limit_up: 0.25, dragon_head: 0.15, limit_down_qiao: 0.15 }[sig.strategy] || 0.20
    const estAmount = availCash * posRatio
    const estShares = sig.price > 0 ? Math.floor(estAmount / sig.price / 100) * 100 : 0

    await ElMessageBox.confirm(
      `确认买入 ${sig.ts_code} ${sig.stock_name}？\n\n`
      + `📊 策略: ${strategyIcon(sig.strategy)} ${strategyCN(sig.strategy)}\n`
      + `💰 价格: ¥${sig.price?.toFixed(2)} | 涨幅: ${formatPct(sig.pct_chg)}\n\n`
      + `📐 预估仓位: ${estShares}股 ≈ ¥${(estShares * sig.price).toFixed(0)} (${(posRatio*100).toFixed(0)}%可用)\n`
      + `🛡️ 风控: 止损${slPct}% / 止盈${tpPct}% / 持有${holdDays}天`,
      '快捷买入',
      { confirmButtonText: '确认买入', cancelButtonText: '取消', type: 'info' }
    )
    const r = await api.post(`${scannerApi}/trade`, {
      ts_code: sig.ts_code,
      stock_name: sig.stock_name,
      strategy: sig.strategy,
      price: sig.price,
      action: 'buy',
    })
    if (r?.success) {
      ElMessage.success(`买入成功: ${sig.ts_code} ${r.data?.filled_qty}股@¥${r.data?.filled_price?.toFixed(2)}`)
      await fetchAll()
    } else {
      ElMessage.error(r?.data?.message || r?.message || '买入失败')
    }
  } catch { /* cancelled */ }
  buyingSignal.value = null
}

// 单票风控保存
async function savePosRisk() {
  if (!posDetailData.value?.ts_code) return
  posRiskSaving.value = true
  try {
    const r = await api.put(`${scannerApi}/position-risk/${posDetailData.value.ts_code}`, {
      stop_loss_pct: posRiskSL.value / 100, // UI用百分比，API用小数
      take_profit_pct: posRiskTP.value / 100,
    })
    if (r?.success) {
      ElMessage.success(`${posDetailData.value.ts_code} 风控已更新: 止损${posRiskSL.value}%/止盈${posRiskTP.value}%`)
      posDetailData.value.position.stop_loss_pct = posRiskSL.value
      posDetailData.value.position.take_profit_pct = posRiskTP.value
      await fetchAll()
    } else {
      ElMessage.error(r?.message || '更新失败')
    }
  } catch (e) { ElMessage.error('保存失败') }
  finally { posRiskSaving.value = false }
}

// 参数热更新
async function saveParam(strategyId: string) {
  const updates = paramEdits.value[strategyId]
  if (!updates || Object.keys(updates).length === 0) return
  try {
    const r = await api.put(`${scannerApi}/params/${strategyId}`, { params: updates, updated_by: 'cockpit' })
    if (r?.success) {
      ElMessage.success(`${strategyCN(strategyId)}参数已更新`)
      paramEdits.value[strategyId] = {}
      editingParam.value = null
      await fetchStrategyParams()
    } else {
      ElMessage.error(r?.message || '更新失败')
    }
  } catch (e: any) {
    ElMessage.error('参数更新失败: ' + (e.message || e))
  }
}

function startEditParam(strategyId: string) {
  editingParam.value = strategyId
  if (!paramEdits.value[strategyId]) paramEdits.value[strategyId] = {}
  const params = strategyParams.value[strategyId]
  if (params) {
    paramEdits.value[strategyId] = { ...params }
  }
}

function cancelEditParam() {
  editingParam.value = null
}

// ============ WebSocket ============
function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  ws = new WebSocket(`${proto}://${location.host}/ws`)
  ws.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data)
      if (data.type === 'scanner_signal' && data.data) signals.value.unshift(data.data)
      if (data.type === 'scanner_position' && data.data) positions.value = data.data
      if (data.type === 'scanner_status' && data.data) status.value = data.data
      if (data.type === 'scanner_timeline' && data.data) timeline.value.unshift(data.data)
    } catch { /* ignore */ }
  }
  ws.onclose = () => { wsReconnectTimer = setTimeout(connectWS, 5000) }
  ws.onerror = () => { ws?.close() }
}

// ============ 生命周期 ============
onMounted(() => {
  fetchAll(); fetchHealth(); fetchScanTraces(); fetchLimitPools(); fetchStrategyParams(); fetchPerformanceHistory()
  refreshTimer = setInterval(() => {
    if (autoRefresh.value) {
      fetchAll(); fetchHealth(); fetchScanTraces(); fetchLimitPools()
      if (paramExpanded.value) fetchStrategyParams()
    }
  }, 5000)
  nowTimer = setInterval(() => { nowMs.value = Date.now() }, 1000)
  connectWS()
})
onUnmounted(() => {
  clearInterval(refreshTimer); clearInterval(nowTimer); clearTimeout(wsReconnectTimer)
  ws?.close()
})
</script>

<template>
  <div class="cockpit">
    <!-- ===== 顶部状态栏 ===== -->
    <div class="top-bar">
      <div class="top-left">
        <!-- 模式切换下拉 -->
        <ElSelect v-model="selectedMode" size="small" class="mode-select" @change="onModeChange">
          <ElOption v-for="(m, key) in modeMeta" :key="key" :label="`${m.emoji} ${m.text}`" :value="key" />
        </ElSelect>
        <span class="mode-badge" :style="{ background: tradeModeLabel.color }">{{ tradeModeLabel.text }}</span>
        <span class="asset-info">
          资产 <b>{{ formatMoney(account.total_assets) }}</b>
          <span class="divider">|</span>
          可用 <b>{{ formatMoney(account.available_cash) }}</b>
          <span class="divider">|</span>
          仓位 <b>{{ positionRatio }}%</b>
          <span class="divider">|</span>
          盈亏 <b :class="account.total_profit >= 0 ? 'profit' : 'loss'">{{ account.total_profit >= 0 ? '+' : '' }}¥{{ account.total_profit.toFixed(0) }}</b>
          <span class="divider">|</span>
          今日 <b :class="todayPnl >= 0 ? 'profit' : 'loss'">{{ todayPnl >= 0 ? '+' : '' }}¥{{ todayPnl.toFixed(0) }}</b>
        </span>
      </div>
      <div class="top-right">
        <ElButton :type="isRunning ? 'danger' : 'success'" size="small" @click="toggleScanner" :loading="loading">
          {{ isRunning ? '停止' : '启动' }}
        </ElButton>
        <ElButton type="danger" size="small" class="emergency-btn" @click="emergencyLiquidate" :disabled="!isRunning">
          🚨 紧急平仓
        </ElButton>
      </div>
    </div>

    <!-- ===== 三列主体 ===== -->
    <div class="main-grid">

      <!-- ===== 左: 风控仪表盘 ===== -->
      <div class="panel risk-panel">
        <div class="panel-title">🛡️ 风控仪表盘</div>
        
        <!-- 日回撤 -->
        <div class="risk-item">
          <div class="risk-label">日回撤</div>
          <ElProgress 
            :percentage="Math.min(100, dailyDrawdown.value / dailyDrawdown.threshold * 100)" 
            :color="dailyDrawdown.value < 2 ? '#67c23a' : dailyDrawdown.value < 4 ? '#e6a23c' : '#f56c6c'"
            :stroke-width="12"
            :format="() => `${dailyDrawdown.value.toFixed(1)}%`"
          />
          <div class="risk-threshold">阈值 {{ dailyDrawdown.threshold }}%</div>
        </div>

        <!-- 连续亏损 -->
        <div class="risk-item">
          <div class="risk-label">连续亏损</div>
          <div class="loss-boxes">
            <span v-for="i in 3" :key="i" class="loss-box" :class="{ filled: i <= consecutiveLosses }">▲</span>
            <span class="loss-count">{{ consecutiveLosses }}/3次</span>
          </div>
        </div>

        <!-- 熔断状态 -->
        <div class="risk-item">
          <div class="risk-label">熔断状态</div>
          <div class="circuit-status" :class="healthStatus">
            <span class="circuit-dot" :style="{ background: healthColor }"></span>
            {{ { healthy: '🟢 正常', degraded: '🟡 预警', critical: '🔴 熔断', dead: '⚫ 失联', unknown: '⚪ 未知' }[healthStatus] || '⚪ 未知' }}
          </div>
          <div v-if="isRunning" class="circuit-actions">
            <button v-if="healthStatus !== 'critical'" class="circuit-btn pause" @click="toggleCircuitBreaker('pause')" title="暂停交易">⏸ 暂停</button>
            <button v-else class="circuit-btn resume" @click="toggleCircuitBreaker('reset')" title="恢复交易">▶ 恢复</button>
          </div>
        </div>

        <!-- 策略健康 — 从API获取 -->
        <div class="risk-item">
          <div class="risk-label">策略健康</div>
          <div class="strategy-health-list">
            <div v-for="item in strategyHealthList" :key="item.key" class="strategy-health-item">
              <span>{{ item.icon }} {{ item.name }}</span>
              <ElTag size="small" :type="item.status === 'healthy' ? 'success' : item.status === 'degraded' ? 'warning' : item.status === 'critical' ? 'danger' : 'info'">
                {{ strategyHealthIcon(item.status) }}
              </ElTag>
            </div>
          </div>
        </div>

        <!-- 数据源状态 -->
        <div class="risk-item" v-if="dataSources.length > 0">
          <div class="risk-label">数据源</div>
          <div class="ds-list">
            <div v-for="ds in dataSources" :key="ds.name" class="ds-item">
              <span class="ds-dot" :class="{ online: ds.available, offline: !ds.available }"></span>
              <span class="ds-name">{{ ds.name }}</span>
              <span class="ds-info">{{ ds.available ? `${ds.stocks}只` : '离线' }}</span>
              <span v-if="ds.limit > 0" class="ds-calls">{{ ds.calls }}/{{ ds.limit }}</span>
            </div>
          </div>
        </div>

        <!-- 看门狗详情 -->
        <div v-if="health?.checks" class="watchdog-details">
          <div v-for="(check, name) in health.checks" :key="name" class="watchdog-item">
            <span class="wd-name">{{ name }}</span>
            <span class="wd-status" :class="check.status">{{ { healthy: '✅', degraded: '⚠️', critical: '🔴', dead: '⚫' }[check.status] || '❓' }}</span>
          </div>
        </div>

        <!-- ⚙️ 参数热更新面板 -->
        <div class="param-section">
          <div class="param-toggle" @click="paramExpanded = !paramExpanded">
            <span>⚙️ 参数中心</span>
            <span class="param-arrow" :class="{ expanded: paramExpanded }">▼</span>
          </div>
          <div v-if="paramExpanded" class="param-panel">
            <div v-if="Object.keys(strategyParams).length === 0" class="param-empty">
              暂无参数数据
            </div>
            <div v-for="(params, sid) in strategyParams" :key="sid" class="param-strategy">
              <div class="param-strategy-header">
                <span :style="{ color: strategyColor(sid) }">{{ strategyIcon(sid) }} {{ strategyCN(sid) }}</span>
                <span v-if="editingParam !== sid" class="param-edit-btn" @click="startEditParam(sid)">✏️</span>
                <span v-else class="param-action-btns">
                  <span class="param-save-btn" @click="saveParam(sid)">💾</span>
                  <span class="param-cancel-btn" @click="cancelEditParam">✖</span>
                </span>
              </div>
              <div class="param-fields">
                <div v-for="(val, key) in params" :key="key" class="param-field">
                  <span class="param-key">{{ key }}</span>
                  <span v-if="editingParam === sid" class="param-value-edit">
                    <input
                      type="number"
                      step="any"
                      :value="paramEdits[sid]?.[key] ?? val"
                      @input="(e: any) => { if (!paramEdits[sid]) paramEdits[sid] = {}; paramEdits[sid][key] = parseFloat(e.target.value) || 0 }"
                      class="param-input"
                    />
                  </span>
                  <span v-else class="param-value">{{ typeof val === 'number' ? (Number.isInteger(val) ? val : val.toFixed(4)) : val }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- ===== 中: 核心实时区 ===== -->
      <div class="panel center-panel">
        <div class="panel-title">📡 实时信号</div>
        
        <!-- 信号列表 -->
        <div class="signal-list">
          <div v-if="signals.length === 0" class="no-signals">
            <ElEmpty description="暂无信号" :image-size="60" />
          </div>
          <div v-for="sig in signals.slice(0, 10)" :key="sig.ts_code + sig.strategy" class="signal-card" :style="{ borderLeftColor: strategyColor(sig.strategy) }" @click="showSignalDetail(sig)">
            <div class="sig-header">
              <span class="sig-icon">{{ strategyIcon(sig.strategy) }}</span>
              <span class="sig-strategy" :style="{ color: strategyColor(sig.strategy) }">{{ sig.strategy_name }}</span>
              <span class="sig-code">{{ sig.ts_code }} {{ sig.stock_name }}</span>
              <span class="sig-pct" :class="sig.pct_chg >= 0 ? 'profit' : 'loss'">
                {{ formatPct(sig.pct_chg) }}
              </span>
              <span v-if="signalRemaining(sig.created_at || 0, nowMs) >= 0" class="sig-countdown">⏱{{ formatRemaining(signalRemaining(sig.created_at || 0, nowMs)) }}</span>
              <ElButton 
                class="sig-buy-btn" 
                size="small" 
                type="success" 
                plain
                :loading="buyingSignal === sig.ts_code + sig.strategy"
                @click.stop="quickBuySignal(sig)"
              >买入</ElButton>
            </div>
            <div class="sig-reason">{{ sig.reason }}</div>
          </div>
        </div>

        <!-- 9层管道可视化 — 接入ScanTrace -->
        <div class="pipeline-viz">
          <div class="pipeline-title">
            9层筛选管道
            <span v-if="pipelineSummary" class="pipeline-summary-badge">
              最近: {{ scanTraces[0]?.trade_date }} {{ scanTraces[0]?.scan_time?.substring(11, 19) || '' }}
            </span>
          </div>
          <div class="pipeline-flow">
            <template v-for="(layer, i) in pipelineLayers" :key="layer">
              <div class="pipe-node" :class="pipelineLayerStatus(layer)">
                <span class="pipe-label">{{ pipelineLabels[layer] || layer }}</span>
                <span class="pipe-status">
                  <template v-if="pipelineSummary">
                    <template v-if="pipelineLayerStatus(layer) === 'idle'">—</template>
                    <template v-else>
                      ✅<span class="pipe-stat">{{ pipelineLayerStats(layer).passed }}/{{ pipelineLayerStats(layer).total }}</span>
                    </template>
                  </template>
                  <template v-else>✅</template>
                </span>
              </div>
              <span v-if="i < pipelineLayers.length - 1" class="pipe-arrow">→</span>
            </template>
          </div>
        </div>
      </div>

      <!-- ===== 右: 持仓盈亏 ===== -->
      <div class="panel right-panel">
        <div class="panel-title">📊 持仓盈亏</div>
        
        <!-- 盈亏曲线 -->
        <div class="pnl-chart">
          <v-chart :option="pnlOption" autoresize style="height: 160px" />
        </div>

        <!-- 总盈亏 -->
        <div class="total-pnl" :class="account.total_profit >= 0 ? 'profit' : 'loss'">
          {{ account.total_profit >= 0 ? '+' : '' }}¥{{ account.total_profit.toFixed(0) }}
        </div>

        <!-- 今日盈亏 -->
        <div class="today-pnl" :class="todayPnl >= 0 ? 'profit' : 'loss'">
          今日 {{ todayPnl >= 0 ? '+' : '' }}¥{{ todayPnl.toFixed(0) }}
        </div>

        <!-- 资金信息 -->
        <div class="fund-info">
          <div class="fund-row">
            <span>可用资金</span>
            <span>{{ formatMoney(account.available_cash) }}</span>
          </div>
          <div class="fund-row">
            <span>占用保证金</span>
            <span>{{ formatMoney(account.market_value) }}</span>
          </div>
        </div>

        <!-- 持仓列表(紧凑+风险线+操作) -->
        <div class="pos-list">
          <div v-for="pos in positions.slice(0, 8)" :key="pos.ts_code" class="pos-item">
            <div class="pos-main">
              <div class="pos-left">
                <span class="pos-code" @click="openPositionDetail(pos)">{{ pos.ts_code }}</span>
                <span v-if="pos.risk_level && pos.risk_level !== 'normal'" class="pos-risk-dot" :class="pos.risk_level" :title="pos.risk_level === 'critical' ? '触及止损区(5秒检查)' : '接近止损(10秒检查)'"></span>
                <span class="pos-name">{{ pos.stock_name }}</span>
                <ElTag size="small" :color="strategyColor(pos.strategy)" effect="dark" style="font-size:10px;border:none;color:#fff">{{ strategyIcon(pos.strategy) }}</ElTag>
              </div>
              <div class="pos-right">
                <span class="pos-pnl" :class="pos.profit_pct >= 0 ? 'profit' : 'loss'">
                  {{ formatPct(pos.profit_pct) }}
                </span>
                <button class="pos-sell-btn" @click="quickSell(pos)" title="卖出">卖</button>
              </div>
            </div>
            <!-- 风险进度条 -->
            <div v-if="pos.stop_loss_pct" class="pos-risk-bar">
              <div class="risk-track">
                <div class="risk-fill" :style="{ width: riskBarWidth(pos) + '%' }" :class="riskBarClass(pos)"></div>
                <div class="risk-marker" :style="{ left: '0%' }" title="止损">SL</div>
                <div class="risk-marker-tp" :style="{ left: '100%' }" title="止盈">TP</div>
                <!-- 追踪止损标记 -->
                <div v-if="pos.trailing_stop?.activated" class="risk-marker-trail" 
                  :style="{ left: trailBarPos(pos) + '%' }" 
                  :title="`追踪止损${(pos.trailing_stop.trailing_stop_pct*100).toFixed(0)}%`">
                  📍
                </div>
              </div>
              <div class="risk-labels">
                <span class="rl-sl">止损{{ pos.stop_loss_pct }}%</span>
                <span v-if="pos.trailing_stop?.activated" class="rl-trail">
                  📍{{ (pos.trailing_stop.trailing_stop_pct*100).toFixed(0) }}%
                </span>
                <span class="rl-dist" :class="pos.profit_pct + (pos.stop_loss_pct||3) < 1 ? 'danger' : ''">
                  距止损{{ (pos.profit_pct + (pos.stop_loss_pct||3)).toFixed(1) }}%
                </span>
                <span class="rl-tp">止盈{{ pos.take_profit_pct }}%</span>
              </div>
              <!-- 风险等级标记 -->
              <div v-if="pos.risk_level && pos.risk_level !== 'normal'" class="risk-level-tag" :class="pos.risk_level">
                {{ pos.risk_level === 'critical' ? '🔴紧急' : '🟡预警' }}
              </div>
            </div>
          </div>
          <div v-if="positions.length > 8" class="pos-more">... 共{{ positions.length }}只</div>
        </div>

        <!-- 涨跌停池快览 -->
        <div class="limit-pool-section">
          <div class="limit-pool-title">🔥 涨跌停池</div>
          <div class="limit-pool-cards">
            <div class="lp-card lp-up">
              <div class="lp-num">{{ limitPoolStats.limitUp }}</div>
              <div class="lp-label">涨停</div>
            </div>
            <div class="lp-card lp-down">
              <div class="lp-num">{{ limitPoolStats.limitDown }}</div>
              <div class="lp-label">跌停</div>
            </div>
            <div class="lp-card lp-broken">
              <div class="lp-num">{{ limitPoolStats.broken }}</div>
              <div class="lp-label">炸板</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ===== 信号详情弹窗 ===== -->
    <ElDialog v-model="signalDetailVisible" :title="signalDetail ? `${signalDetail.ts_code} ${signalDetail.stock_name}` : ''" width="520px" destroy-on-close>
      <div v-if="signalDetail" class="sig-detail">
        <div class="sig-detail-row"><span class="sig-detail-label">策略</span><span :style="{ color: strategyColor(signalDetail.strategy) }">{{ strategyIcon(signalDetail.strategy) }} {{ signalDetail.strategy_name }}</span></div>
        <div class="sig-detail-row"><span class="sig-detail-label">价格</span><span>¥{{ signalDetail.price?.toFixed(2) }}</span></div>
        <div class="sig-detail-row"><span class="sig-detail-label">涨幅</span><span :class="signalDetail.pct_chg >= 0 ? 'profit' : 'loss'">{{ formatPct(signalDetail.pct_chg) }}</span></div>
        <div class="sig-detail-row"><span class="sig-detail-label">原因</span><span>{{ signalDetail.reason }}</span></div>
        <div v-if="signalDetailTrace" class="sig-detail-row">
          <span class="sig-detail-label">最终状态</span>
          <span :class="signalDetailTrace.final_status === 'passed' ? 'profit' : 'loss'">
            {{ signalDetailTrace.final_status === 'passed' ? '✅ 通过' : '❌ ' + (signalDetailTrace.rejection_layer || '拒绝') }}
          </span>
        </div>
        <div v-if="signalDetailTrace?.rejection_reason" class="sig-detail-row">
          <span class="sig-detail-label">拒绝原因</span>
          <span class="loss">{{ signalDetailTrace.rejection_reason }}</span>
        </div>
        <div class="sig-detail-pipeline">
          <div class="sig-detail-pipeline-title">9层筛选管道通过详情</div>
          <div class="pipeline-flow">
            <template v-for="(layer, i) in pipelineLayers" :key="layer">
              <div class="pipe-node" :class="getSignalLayerResult(layer)?.passed ? 'pass' : getSignalLayerResult(layer) === null ? 'idle' : 'filter'">
                <span class="pipe-label">{{ pipelineLabels[layer] }}</span>
                <span class="pipe-status">
                  <template v-if="getSignalLayerResult(layer) === null">✅</template>
                  <template v-else-if="getSignalLayerResult(layer)!.passed">✅</template>
                  <template v-else>❌</template>
                </span>
              </div>
              <span v-if="i < pipelineLayers.length - 1" class="pipe-arrow">→</span>
            </template>
          </div>
          <!-- Layer detail table -->
          <div v-if="signalDetailTrace?.layer_results" class="layer-detail-list">
            <div v-for="(lr, layerKey) in signalDetailTrace.layer_results" :key="layerKey" class="layer-detail-item">
              <span class="ld-layer">{{ pipelineLabels[layerKey] || layerKey }}</span>
              <span :class="lr.passed ? 'profit' : 'loss'">{{ lr.passed ? '✅ 通过' : '❌ 拦截' }}</span>
              <span v-if="lr.reason" class="ld-reason">{{ lr.reason }}</span>
            </div>
          </div>
        </div>
      </div>
    </ElDialog>

    <!-- ===== 底部时间线 ===== -->
    <div class="timeline-bar">
      <span class="timeline-label">📋 时间线</span>
      <div class="timeline-scroll">
        <span v-for="item in timeline.slice(0, 20)" :key="item.time + item.ts_code" class="tl-item" :class="item.action">
          {{ item.time }} 
          <ElTag size="small" :type="item.action === 'buy' ? 'danger' : item.action === 'sell' ? 'success' : 'info'" effect="dark">
            {{ item.action === 'buy' ? '买' : item.action === 'sell' ? '卖' : item.action }}
          </ElTag>
          {{ item.ts_code }} {{ item.stock_name }}
          <span v-if="item.profit_pct != null" :class="item.profit_pct >= 0 ? 'profit' : 'loss'">
            {{ formatPct(item.profit_pct) }}
          </span>
        </span>
      </div>
    </div>

    <!-- 持仓详情弹窗 -->
    <ElDialog v-model="posDetailVisible" title="📊 持仓详情" width="560px" :append-to-body="true">
      <div v-if="posDetailLoading" style="text-align:center;padding:40px">加载中...</div>
      <div v-else-if="posDetailData" class="pos-detail">
        <!-- 基础信息 -->
        <div class="pd-header">
          <div class="pd-title">{{ posDetailData.ts_code }}</div>
          <ElTag v-if="posDetailData.position?.strategy" :color="strategyColor(posDetailData.position.strategy)" effect="dark" style="color:#fff;border:none">{{ strategyIcon(posDetailData.position.strategy) }} {{ strategyCN(posDetailData.position.strategy) }}</ElTag>
        </div>
        <!-- 当前状态 -->
        <div v-if="posDetailData.position" class="pd-section">
          <div class="pd-stitle">📈 当前持仓</div>
          <div class="pd-grid">
            <div class="pd-cell"><span class="pd-cl">持仓</span><span class="pd-cv">{{ posDetailData.position.shares }}股</span></div>
            <div class="pd-cell"><span class="pd-cl">成本</span><span class="pd-cv">¥{{ posDetailData.position.cost_price?.toFixed(2) }}</span></div>
            <div class="pd-cell"><span class="pd-cl">现价</span><span class="pd-cv">¥{{ posDetailData.position.current_price?.toFixed(2) }}</span></div>
            <div class="pd-cell"><span class="pd-cl">盈亏</span><span class="pd-cv" :class="posDetailData.position.profit_pct >= 0 ? 'profit' : 'loss'">{{ formatPct(posDetailData.position.profit_pct) }}</span></div>
          </div>
          <!-- 风控调整 -->
          <div class="pd-risk-adj">
            <div class="pd-risk-row">
              <span class="pd-cl" style="color:var(--stock-up)">止损</span>
              <ElInputNumber v-model="posRiskSL" size="small" :min="0.5" :max="20" :step="0.5" :precision="1" style="width:90px" />
              <span class="pd-unit">%</span>
              <span class="pd-cl" style="color:var(--stock-down)">止盈</span>
              <ElInputNumber v-model="posRiskTP" size="small" :min="1" :max="50" :step="1" :precision="1" style="width:90px" />
              <span class="pd-unit">%</span>
              <ElButton size="small" type="primary" @click="savePosRisk" :loading="posRiskSaving">保存</ElButton>
            </div>
            <div class="pd-risk-hint">修改后仅对该持仓生效，不影响策略全局参数</div>
          </div>
        </div>
        <!-- 买入详情 -->
        <div v-if="posDetailData.buy" class="pd-section">
          <div class="pd-stitle">🟢 买入</div>
          <div class="pd-grid">
            <div class="pd-cell"><span class="pd-cl">时间</span><span class="pd-cv">{{ posDetailData.buy.time }}</span></div>
            <div class="pd-cell"><span class="pd-cl">价格</span><span class="pd-cv">¥{{ posDetailData.buy.price?.toFixed(2) }}</span></div>
            <div class="pd-cell"><span class="pd-cl">数量</span><span class="pd-cv">{{ posDetailData.buy.shares }}股</span></div>
            <div class="pd-cell"><span class="pd-cl">原因</span><span class="pd-cv">{{ posDetailData.buy.reason }}</span></div>
          </div>
          <!-- 9层决策链路 -->
          <div v-if="posDetailData.buy.decision_detail" class="pd-layers">
            <div v-for="(val, key) in posDetailData.buy.decision_detail" :key="key" class="pd-layer-row">
              <span class="pd-lk">{{ key }}</span>
              <span class="pd-lv">{{ typeof val === 'object' ? JSON.stringify(val) : val }}</span>
            </div>
          </div>
        </div>
        <!-- 卖出详情 -->
        <div v-if="posDetailData.sell" class="pd-section">
          <div class="pd-stitle">🔴 卖出</div>
          <div class="pd-grid">
            <div class="pd-cell"><span class="pd-cl">时间</span><span class="pd-cv">{{ posDetailData.sell.time }}</span></div>
            <div class="pd-cell"><span class="pd-cl">价格</span><span class="pd-cv">¥{{ posDetailData.sell.price?.toFixed(2) }}</span></div>
            <div class="pd-cell"><span class="pd-cl">原因</span><span class="pd-cv">{{ posDetailData.sell.reason }}</span></div>
            <div class="pd-cell"><span class="pd-cl">盈亏</span><span class="pd-cv" :class="posDetailData.sell.profit_pct >= 0 ? 'profit' : 'loss'">{{ formatPct(posDetailData.sell.profit_pct) }}</span></div>
          </div>
        </div>
        <!-- 订单历史 -->
        <div v-if="posDetailData.orders?.length" class="pd-section">
          <div class="pd-stitle">📋 订单历史</div>
          <div v-for="o in posDetailData.orders" :key="o.order_id" class="pd-order-row">
            <ElTag size="small" :type="o.side === 'buy' ? 'danger' : 'success'">{{ o.side === 'buy' ? '买' : '卖' }}</ElTag>
            <span>{{ o.quantity }}股@¥{{ o.filled_price?.toFixed(2) }}</span>
            <span class="pd-order-reason">{{ o.reason }}</span>
          </div>
        </div>
      </div>
      <div v-else style="text-align:center;padding:20px;color:var(--text-muted)">无数据</div>
    </ElDialog>
  </div>
</template>

<style scoped>
.cockpit { display: flex; flex-direction: column; height: 100vh; background: var(--bg-base); color: var(--text-secondary); font-size: 13px; }

/* 顶部状态栏 */
.top-bar { display: flex; justify-content: space-between; align-items: center; padding: 8px 16px; background: var(--bg-elevated); border-bottom: 1px solid var(--border-default); }
.top-left { display: flex; align-items: center; gap: 12px; }
.top-right { display: flex; gap: 8px; }
.mode-select { width: 110px; }
.mode-badge { padding: 2px 10px; border-radius: 4px; font-weight: bold; color: var(--text-primary); font-size: 12px; }
.asset-info { font-size: 13px; color: var(--text-tertiary); }
.asset-info b { color: var(--text-primary); }
.divider { color: var(--text-quaternary, var(--text-tertiary)); margin: 0 4px; }
.profit { color: var(--stock-down); }
.loss { color: var(--stock-up); }
.emergency-btn { animation: pulse 2s infinite; }
@keyframes pulse { 0%, 100% { box-shadow: 0 0 0 0 rgba(245,108,108,0.4); } 50% { box-shadow: 0 0 0 6px rgba(245,108,108,0); } }

/* 三列主体 */
.main-grid { display: grid; grid-template-columns: 240px 1fr 280px; gap: 12px; padding: 12px; flex: 1; overflow: hidden; }
.panel { background: var(--bg-elevated); border-radius: 8px; padding: 12px; border: 1px solid var(--border-default); overflow-y: auto; }
.panel-title { font-size: 14px; font-weight: bold; margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px solid var(--border-default); }

/* 风控仪表盘 */
.risk-item { margin-bottom: 16px; }
.risk-label { font-size: 12px; color: var(--text-tertiary); margin-bottom: 4px; }
.risk-threshold { font-size: 11px; color: var(--text-muted); margin-top: 2px; }
.loss-boxes { display: flex; gap: 6px; align-items: center; }
.loss-box { font-size: 18px; color: var(--border-default); transition: color 0.3s; }
.loss-box.filled { color: #f56c6c; }
.loss-count { font-size: 12px; color: var(--text-tertiary); margin-left: 8px; }
.circuit-status { font-size: 14px; font-weight: bold; }
.circuit-dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; animation: blink 1.5s infinite; }
.circuit-status.critical .circuit-dot { animation: blink 0.5s infinite; }
.circuit-actions { margin-top: 6px; display: flex; gap: 6px; }
.circuit-btn { font-size: 11px; padding: 2px 10px; border-radius: 4px; cursor: pointer; border: 1px solid; }
.circuit-btn.pause { border-color: #e6a23c; color: #e6a23c; background: transparent; }
.circuit-btn.pause:hover { background: #e6a23c; color: #fff; }
.circuit-btn.resume { border-color: #67c23a; color: #67c23a; background: transparent; }
.circuit-btn.resume:hover { background: #67c23a; color: #fff; }
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
.strategy-health-item { display: flex; justify-content: space-between; padding: 3px 0; font-size: 12px; }
.watchdog-details { margin-top: 12px; padding-top: 8px; border-top: 1px solid var(--border-default); }
.watchdog-item { display: flex; justify-content: space-between; font-size: 11px; padding: 2px 0; }
.wd-name { color: #888; }

/* 数据源状态 */
.ds-list { display: flex; flex-direction: column; gap: 4px; }
.ds-item { display: flex; align-items: center; gap: 6px; font-size: 12px; }
.ds-dot { width: 8px; height: 8px; border-radius: 50%; }
.ds-dot.online { background: #67c23a; }
.ds-dot.offline { background: #f56c6c; }
.ds-name { color: var(--text-secondary); min-width: 40px; }
.ds-info { color: var(--text-tertiary); }
.ds-calls { color: var(--text-muted); font-size: 11px; margin-left: auto; }

/* 参数热更新面板 */
.param-section { margin-top: 12px; padding-top: 8px; border-top: 1px solid var(--border-default); }
.param-toggle { display: flex; justify-content: space-between; align-items: center; cursor: pointer; font-size: 13px; font-weight: bold; padding: 4px 0; }
.param-toggle:hover { color: var(--text-primary); }
.param-arrow { font-size: 10px; transition: transform 0.2s; }
.param-arrow.expanded { transform: rotate(180deg); }
.param-panel { margin-top: 8px; max-height: 300px; overflow-y: auto; }
.param-empty { color: var(--text-muted); font-size: 12px; text-align: center; padding: 12px; }
.param-strategy { margin-bottom: 10px; padding: 6px; background: var(--bg-muted); border-radius: 4px; }
.param-strategy-header { display: flex; justify-content: space-between; align-items: center; font-size: 12px; font-weight: bold; margin-bottom: 4px; }
.param-edit-btn, .param-save-btn, .param-cancel-btn { cursor: pointer; font-size: 14px; padding: 0 4px; }
.param-save-btn { color: #67c23a; }
.param-cancel-btn { color: #f56c6c; }
.param-action-btns { display: flex; gap: 4px; }
.param-fields { display: flex; flex-direction: column; gap: 2px; }
.param-field { display: flex; justify-content: space-between; font-size: 11px; padding: 1px 0; }
.param-key { color: var(--text-tertiary); }
.param-value { color: var(--text-secondary); font-family: monospace; }
.param-value-edit { flex: 1; max-width: 80px; }
.param-input { width: 100%; font-size: 11px; padding: 2px 4px; border: 1px solid var(--border-default); border-radius: 3px; background: var(--bg-base); color: var(--text-primary); font-family: monospace; }

/* 核心实时区 */
.signal-list { flex: 1; }
.signal-card { background: var(--bg-muted); border-radius: 6px; padding: 8px 10px; margin-bottom: 6px; border-left: 3px solid var(--primary-500); cursor: pointer; }
.signal-card:hover { background: var(--bg-hover, rgba(255,255,255,0.05)); }
.sig-header { display: flex; align-items: center; gap: 6px; }
.sig-icon { font-size: 16px; }
.sig-strategy { font-weight: bold; font-size: 13px; }
.sig-code { color: var(--text-tertiary); font-size: 12px; }
.sig-pct { font-weight: bold; margin-left: auto; }
.sig-countdown { font-size: 11px; color: #e6a23c; }
.sig-buy-btn { margin-left: 4px; padding: 2px 8px; font-size: 11px; }
.sig-reason { font-size: 11px; color: var(--text-tertiary); margin-top: 4px; }
.no-signals { padding: 20px 0; }

/* 9层管道 */
.pipeline-viz { margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border-default); }
.pipeline-title { font-size: 13px; font-weight: bold; margin-bottom: 8px; display: flex; align-items: center; gap: 8px; }
.pipeline-summary-badge { font-size: 11px; font-weight: normal; color: var(--text-muted); background: var(--bg-muted); padding: 2px 6px; border-radius: 3px; }
.pipeline-flow { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
.pipe-node { background: var(--bg-muted); padding: 3px 8px; border-radius: 4px; font-size: 11px; }
.pipe-node.filter { background: rgba(245,108,108,0.1); border: 1px solid rgba(245,108,108,0.3); }
.pipe-node.pass { background: rgba(103,194,58,0.1); border: 1px solid rgba(103,194,58,0.3); }
.pipe-node.idle { opacity: 0.5; }
.pipe-label { color: var(--text-tertiary); margin-right: 4px; }
.pipe-status { font-size: 10px; }
.pipe-stat { color: var(--text-muted); font-size: 10px; margin-left: 2px; }
.pipe-arrow { color: var(--text-muted); font-size: 12px; }

/* 持仓盈亏 */
.pnl-chart { margin-bottom: 8px; }
.total-pnl { text-align: center; font-size: 28px; font-weight: bold; margin: 8px 0; }
.total-pnl.profit { color: var(--stock-down, #f56c6c); }
.total-pnl.loss { color: var(--stock-up, #67c23a); }
.today-pnl { text-align: center; font-size: 14px; font-weight: bold; margin-bottom: 8px; }
.today-pnl.profit { color: var(--stock-down, #f56c6c); }
.today-pnl.loss { color: var(--stock-up, #67c23a); }
.fund-info { margin: 8px 0; }
.fund-row { display: flex; justify-content: space-between; padding: 4px 0; font-size: 12px; color: var(--text-tertiary); }
.pos-list { margin-top: 12px; padding-top: 8px; border-top: 1px solid var(--border-default); }
.pos-item { padding: 6px 0; border-bottom: 1px solid var(--border-light, var(--border-default)); }
.pos-main { display: flex; justify-content: space-between; align-items: center; font-size: 12px; }
.pos-left { display: flex; align-items: center; gap: 4px; }
.pos-right { display: flex; align-items: center; gap: 6px; }
.pos-code { color: var(--text-primary); font-size: 12px; font-weight: 500; cursor: pointer; }
.pos-code:hover { text-decoration: underline; }
.pos-risk-dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; margin-left: 3px; vertical-align: middle; }
.pos-risk-dot.warning { background: #e6a23c; }
.pos-risk-dot.critical { background: #f56c6c; animation: risk-pulse 1s infinite; }
.pos-name { color: var(--text-tertiary); font-size: 11px; }
.pos-pnl { font-weight: bold; font-size: 13px; }
.pos-pnl.profit { color: var(--stock-down, #f56c6c); }
.pos-pnl.loss { color: var(--stock-up, #67c23a); }
.pos-sell-btn { font-size: 10px; padding: 1px 6px; border-radius: 3px; border: 1px solid var(--stock-up, #67c23a); color: var(--stock-up, #67c23a); background: transparent; cursor: pointer; line-height: 1.4; }
.pos-sell-btn:hover { background: var(--stock-up, #67c23a); color: #fff; }
.pos-risk-bar { margin-top: 3px; }
.risk-track { height: 4px; background: var(--bg-muted); border-radius: 2px; position: relative; overflow: hidden; }
.risk-fill { height: 100%; border-radius: 2px; transition: width 0.3s; }
.risk-fill.safe { background: linear-gradient(90deg, #e6a23c, #67c23a); }
.risk-fill.warning { background: linear-gradient(90deg, #e6a23c, #f56c6c); }
.risk-fill.danger { background: #f56c6c; animation: risk-pulse 1s infinite; }
.risk-labels { display: flex; justify-content: space-between; font-size: 10px; margin-top: 1px; }
.rl-sl { color: var(--stock-up, #67c23a); }
.rl-tp { color: var(--stock-down, #f56c6c); }
.rl-dist { color: var(--text-muted); }
.rl-dist.danger { color: #f56c6c; font-weight: bold; }
.risk-marker-trail { position: absolute; top: -3px; transform: translateX(-50%); font-size: 9px; z-index: 2; filter: drop-shadow(0 0 2px rgba(255,200,0,0.6)); }
.rl-trail { color: #e6a23c; font-weight: bold; }
.risk-level-tag { display: inline-block; font-size: 10px; padding: 0 4px; border-radius: 3px; margin-top: 2px; font-weight: bold; }
.risk-level-tag.critical { background: rgba(245,108,108,0.2); color: #f56c6c; animation: risk-pulse 1s infinite; }
.risk-level-tag.warning { background: rgba(230,162,60,0.2); color: #e6a23c; }
@keyframes risk-pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }
.pos-risk-line { display: flex; gap: 8px; font-size: 10px; margin-top: 2px; }
.pos-sl { color: var(--stock-up); }
.pos-tp { color: var(--stock-down); }
.pos-more { text-align: center; color: var(--text-muted); font-size: 11px; padding: 4px; }

/* 涨跌停池 */
.limit-pool-section { margin-top: 12px; padding-top: 8px; border-top: 1px solid var(--border-default); }
.limit-pool-title { font-size: 13px; font-weight: bold; margin-bottom: 8px; }
.limit-pool-cards { display: flex; gap: 8px; }
.lp-card { flex: 1; text-align: center; padding: 8px 4px; border-radius: 6px; }
.lp-card.lp-up { background: rgba(245,108,108,0.1); border: 1px solid rgba(245,108,108,0.2); }
.lp-card.lp-down { background: rgba(103,194,58,0.1); border: 1px solid rgba(103,194,58,0.2); }
.lp-card.lp-broken { background: rgba(230,162,60,0.1); border: 1px solid rgba(230,162,60,0.2); }
.lp-num { font-size: 22px; font-weight: bold; }
.lp-up .lp-num { color: #f56c6c; }
.lp-down .lp-num { color: #67c23a; }
.lp-broken .lp-num { color: #e6a23c; }
.lp-label { font-size: 11px; color: var(--text-tertiary); margin-top: 2px; }

/* 信号详情弹窗 */
.sig-detail { font-size: 13px; }
.sig-detail-row { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid var(--border-default); }
.sig-detail-label { color: var(--text-tertiary); min-width: 60px; }
.sig-detail-pipeline { margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--border-default); }
.sig-detail-pipeline-title { font-weight: bold; margin-bottom: 8px; font-size: 13px; }
.layer-detail-list { margin-top: 8px; }
.layer-detail-item { display: flex; align-items: center; gap: 8px; padding: 4px 0; font-size: 12px; border-bottom: 1px dashed var(--border-light, var(--border-default)); }
.ld-layer { min-width: 70px; color: var(--text-tertiary); }
.ld-reason { color: var(--text-muted); font-size: 11px; }

/* 底部时间线 */
.timeline-bar { display: flex; align-items: center; gap: 12px; padding: 8px 16px; background: var(--bg-elevated); border-top: 1px solid var(--border-default); }
.timeline-label { font-weight: bold; font-size: 12px; white-space: nowrap; }
.timeline-scroll { display: flex; gap: 12px; overflow-x: auto; flex: 1; }
.tl-item { white-space: nowrap; font-size: 12px; color: var(--text-tertiary); }

/* 响应式 */
@media (max-width: 900px) {
  .main-grid { grid-template-columns: 1fr; }
  .cockpit { padding: 8px; }
  .top-bar { flex-wrap: wrap; gap: 8px; }
  .asset-info { font-size: 12px; }
  .mode-select { width: 90px; }
}

@media (max-width: 640px) {
  .main-grid { grid-template-columns: 1fr; gap: 8px; padding: 8px; }
  .panel { padding: 8px; }
  .total-pnl { font-size: 22px; }
  .signal-card { padding: 6px 8px; }
  .limit-pool-cards { flex-wrap: wrap; }
}

/* 持仓详情弹窗 */
.pos-detail { font-size: 13px; }
.pd-header { display: flex; align-items: center; gap: 8px; margin-bottom: 16px; }
.pd-title { font-size: 18px; font-weight: bold; }
.pd-section { margin-bottom: 16px; padding: 12px; background: var(--bg-muted); border-radius: 8px; }
.pd-stitle { font-size: 14px; font-weight: bold; margin-bottom: 8px; }
.pd-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; }
.pd-cell { display: flex; flex-direction: column; gap: 2px; }
.pd-cl { font-size: 11px; color: var(--text-muted); }
.pd-cv { font-size: 13px; font-weight: 500; }
.pd-cv.profit { color: var(--stock-down, #f56c6c); }
.pd-cv.loss { color: var(--stock-up, #67c23a); }
.pd-layers { margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--border-default); }
.pd-layer-row { display: flex; gap: 8px; padding: 2px 0; font-size: 11px; }
.pd-lk { color: var(--text-muted); min-width: 80px; }
.pd-lv { color: var(--text-primary); word-break: break-all; }
.pd-order-row { display: flex; align-items: center; gap: 8px; padding: 4px 0; font-size: 12px; }
.pd-order-reason { color: var(--text-muted); font-size: 11px; }
.pd-risk-adj { margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--border-default); }
.pd-risk-row { display: flex; align-items: center; gap: 8px; }
.pd-unit { font-size: 12px; color: var(--text-muted); }
.pd-risk-hint { font-size: 11px; color: var(--text-muted); margin-top: 6px; }
</style>