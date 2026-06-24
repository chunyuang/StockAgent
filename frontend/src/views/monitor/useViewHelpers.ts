/**
 * MarketMonitorView 本地辅助函数
 * 从 .vue script 中提取，减少行数
 */
import { ref, computed, watch, type Ref } from 'vue'

export function useViewHelpers(deps: {
  todayClosedTrades: Ref<any[]>
  stratSectionCollapsed: Ref<boolean>
  dateSectionCollapsed: Ref<boolean>
  leftRailCollapsed: Ref<boolean>
  strategies: Ref<any[]>
  filteredSignals: Ref<any[]>
  formatLayerTrace: (trace: any) => any[]
  unified: { currentDate: Ref<string> }
  strategyCN: (s: string) => string
  stratCollapsed?: Ref<Record<string, boolean>>
}) {
  const closedTradesCollapsed = ref(false)
  const closedTradesProfitTotal = computed(() =>
    (deps.todayClosedTrades.value || []).reduce((s: number, t: any) => s + (Number(t.profit_amount) || 0), 0)
  )
  const todayInt = computed(() => {
    const d = new Date()
    const china = new Date(d.toLocaleString('en-US', { timeZone: 'Asia/Shanghai' }))
    return `${china.getFullYear()}${String(china.getMonth() + 1).padStart(2, '0')}${String(china.getDate()).padStart(2, '0')}`
  })
  function formatBuyDateShort(bd: any) {
    if (!bd) return ''
    const s = String(bd).replace(/\D/g, '')
    if (s.length >= 8) return `${s.slice(4, 6)}-${s.slice(6, 8)}买入`
    return s
  }
  const activeSignalTrace = ref<any>(null)
  const activeSignalTraceKey = computed(() =>
    activeSignalTrace.value ? `${activeSignalTrace.value.ts_code || ''}:${activeSignalTrace.value.strategy || ''}` : ''
  )
  const activeSignalTraceLines = computed(() => deps.formatLayerTrace(activeSignalTrace.value?.layer_trace || {}))
  const leftPanelExpanded = computed(() => !deps.leftRailCollapsed.value && (!deps.dateSectionCollapsed.value || !deps.stratSectionCollapsed.value))
  const expandedPositions = ref<Record<string, boolean>>({})
  const anyPositionExpanded = computed(() => Object.values(expandedPositions.value).some(Boolean))
  const fmtCompactDate = (d?: string) => {
    const s = String(d || '').replace(/-/g, '')
    return s.length === 8 ? `${s.slice(4, 6)}-${s.slice(6, 8)}` : '今日'
  }
  const currentDateCompact = computed(() => fmtCompactDate(deps.unified.currentDate.value))
  const enabledStrategyCount = computed(() => deps.strategies.value.filter((s: any) => s.enabled).length)
  const visibleSignals = computed(() => deps.filteredSignals.value)
  const signalsByHour = computed(() => {
    const groups: Record<string, any[]> = {}
    for (const sig of visibleSignals.value as any[]) {
      const t = String(sig.scan_time || '')
      const hour = t && t.includes(':') ? t.slice(0, 2) : '无时间'
      if (!groups[hour]) groups[hour] = []
      groups[hour].push(sig)
    }
    return Object.entries(groups).sort((a, b) => a[0].localeCompare(b[0])).map(([hour, sigs]) => ({ hour, signals: sigs, count: sigs.length }))
  })
  const signalHourCollapse = ref<Record<string, boolean>>({})
  const toggleSignalHour = (h: string) => { signalHourCollapse.value[h] = !signalHourCollapse.value[h] }
  const signalHourInitialized = ref(false)
  watch(signalsByHour, (groups) => {
    if (!signalHourInitialized.value && groups.length) {
      const lastHour = groups[groups.length - 1].hour
      for (const g of groups) signalHourCollapse.value[g.hour] = (g.hour !== lastHour)
      signalHourInitialized.value = true
    }
  }, { immediate: true })
  const signalFilterOptions = computed(() => [
    { k: 'all', l: '全部', title: '显示所有当前活跃信号' },
    { k: 'halfway_chase', l: '半路追涨', title: '盘中冲高2-7%+量能放大的追涨信号' },
    { k: 'first_limit_up', l: '首板打板', title: '首板涨停封板强的打板信号' },
    { k: 'limit_up_open', l: '涨停开板', title: '涨停炸板/开板后的回封观察信号' },
    { k: 'dragon_head', l: '龙头低吸', title: '连板龙头回调低吸信号' },
    { k: 'limit_down_qiao', l: '跌停翘板', title: '跌停撬板反弹信号' },
    { k: 'anomaly', l: '异动', title: '异动聚合：急速拉升、涨停炸板、强势涨停' },
  ])
  const signalFilterHelp = computed(() => {
    const base = '活跃信号：当前仍有效、可关注/可操作的实时信号；历史扫描结果请看「扫描追踪」，这里的数量不等于今日全部扫描通过数。'
    const anomaly = '异动=急速拉升/涨停炸板/强势涨停。'
    if (!deps.filteredSignals.value.length) return `${base} 当前无活跃信号，可能是信号已过期、已成交、被拦截、被后续扫描覆盖，或已进入历史记录。${anomaly}`
    return `${base} 顶部按钮按买入策略筛选当前活跃信号。${anomaly}`
  })
  function toggleDateSection() {
    if (deps.leftRailCollapsed.value) deps.leftRailCollapsed.value = false
    deps.dateSectionCollapsed.value = !deps.dateSectionCollapsed.value
  }
  function togglePositionCard(code: string) { expandedPositions.value[code] = !expandedPositions.value[code] }
  function toggleActiveSignalTrace(sig: any) {
    const key = `${sig?.ts_code || ''}:${sig?.strategy || ''}`
    if (activeSignalTraceKey.value === key) { activeSignalTrace.value = null; return }
    activeSignalTrace.value = sig
  }
  function displayStrategyName(raw: any, fallback?: any) {
    const v = raw || fallback; if (!v) return '-'
    const mapped = deps.strategyCN(v)
    return mapped === v && fallback && fallback !== v ? deps.strategyCN(fallback) : mapped
  }
  function formatBuyDateDisplay(bd: any) {
    if (!bd) return '--'
    const s = String(bd).replace(/\D/g, ''); if (s.length < 8) return s
    const ymd = `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}`
    try {
      const buyTime = new Date(`${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}T00:00:00`).getTime()
      const days = Math.floor((Date.now() - buyTime) / (1000 * 60 * 60 * 24))
      if (days === 0) return `${ymd} 今天`; if (days === 1) return `${ymd} 昨天`
      if (days > 0 && days < 30) return `${ymd} 持${days}天`; return ymd
    } catch (e) { console.error('[viewHelpers] 日期解析失败:', e); return ymd }
  }
  function positionActionLabel(pos: any) {
    const sn = pos?.strategy_name || pos?.strategy || ''
    if (sn) { const cn = deps.strategyCN(sn) || sn; return cn.length > 4 ? cn.slice(0, 4) : cn }
    return '持仓'
  }
  function formatPositionTime(pos: any) {
    const t = pos?.buy_time || pos?.buy_datetime || pos?.trade_time || pos?.open_time
    if (t) {
      const s = String(t); const hms = s.match(/(\d{1,2}):(\d{2})(?::(\d{2}))?/)
      if (hms) return hms[3] ? `${hms[1].padStart(2, '0')}:${hms[2]}:${hms[3]}` : `${hms[1].padStart(2, '0')}:${hms[2]}`
    }
    const bd = pos?.buy_date || pos?.trade_date
    if (bd) { const s = String(bd).replace(/\D/g, ''); if (s.length >= 8) return `${s.slice(4, 6)}-${s.slice(6, 8)}` }
    return ''
  }
  function toggleStrategySection() {
    if (deps.leftRailCollapsed.value) deps.leftRailCollapsed.value = false
    deps.stratSectionCollapsed.value = !deps.stratSectionCollapsed.value
    if (!deps.stratSectionCollapsed.value && deps.stratCollapsed) {
      deps.stratCollapsed.value = Object.fromEntries(deps.strategies.value.map((s: any) => [s.id, true]))
    }
  }
  function formatTradeDateTime(rec: any): string {
    if (!rec) return '-'; if (rec.time_display) return rec.time_display
    const td = String(rec.trade_date || '').trim(); const t = String(rec.time || '').trim()
    if (td && /^\d{8}$/.test(td)) { const ymd = `${td.slice(0,4)}-${td.slice(4,6)}-${td.slice(6,8)}`; return t ? `${ymd} ${t}` : ymd }
    if (td && /^\d{4}-\d{2}-\d{2}$/.test(td)) { return t ? `${td} ${t}` : td }
    return t || '-'
  }
  return {
    closedTradesCollapsed, closedTradesProfitTotal, todayInt, formatBuyDateShort,
    activeSignalTrace, activeSignalTraceKey, activeSignalTraceLines,
    leftPanelExpanded, expandedPositions, anyPositionExpanded,
    currentDateCompact, enabledStrategyCount, visibleSignals,
    signalsByHour, signalHourCollapse, toggleSignalHour,
    signalFilterOptions, signalFilterHelp,
    toggleDateSection, togglePositionCard, toggleActiveSignalTrace,
    displayStrategyName, formatBuyDateDisplay, positionActionLabel,
    formatPositionTime, toggleStrategySection, formatTradeDateTime,
  }
}
