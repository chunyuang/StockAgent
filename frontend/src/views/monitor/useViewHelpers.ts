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
  // 【v2.9.110】信号按时段分组(盘前/早盘/午休/下午盘/盘后) + 30分钟子分组
  const SIGNAL_SLOT_DEFS = [
    { key: 'premarket',  label: '🔍 盘前竞价', timeRange: '09:00-09:30', order: 0 },
    { key: 'morning',   label: '📈 早盘',     timeRange: '09:30-11:30', order: 1 },
    { key: 'lunch',     label: '🍱 午休',     timeRange: '11:30-13:00', order: 2 },
    { key: 'afternoon', label: '📉 下午盘',   timeRange: '13:00-15:00', order: 3 },
    { key: 'postmarket',label: '🌙 盘后',     timeRange: '15:00+',     order: 4 },
    { key: 'no_time',   label: '⚠️ 无时间',   timeRange: '',            order: 5 },
  ]
  function getSignalSlotKey(timeStr: string, createdAt?: number): string {
    // 优先用 scan_time
    if (timeStr && timeStr.length >= 5) {
      const parts = timeStr.split(':')
      const hh = parseInt(parts[0]), mm = parseInt(parts[1] || '0')
      if (!isNaN(hh) && !isNaN(mm)) {
        const m = hh * 60 + mm
        if (m < 9 * 60 + 30) return 'premarket'
        if (m < 11 * 60 + 30) return 'morning'
        if (m < 13 * 60) return 'lunch'
        if (m < 15 * 60) return 'afternoon'
        return 'postmarket'
      }
    }
    // fallback: 用 created_at 时间戳推算
    if (createdAt && createdAt > 0) {
      const d = new Date(createdAt * 1000)
      // 用北京时间(UTC+8)判断时段
      const utcMs = d.getTime() + d.getTimezoneOffset() * 60000
      const cn = new Date(utcMs + 8 * 3600000)
      const hh = cn.getHours(), mm = cn.getMinutes()
      const m = hh * 60 + mm
      if (m < 9 * 60 + 30) return 'premarket'
      if (m < 11 * 60 + 30) return 'morning'
      if (m < 13 * 60) return 'lunch'
      if (m < 15 * 60) return 'afternoon'
      return 'postmarket'
    }
    return 'no_time'
  }
  function getHalfHourKey(timeStr: string, createdAt?: number): string {
    let hh: number | null = null, mm: number | null = null
    if (timeStr && timeStr.length >= 5) {
      const parts = timeStr.split(':')
      hh = parseInt(parts[0]); mm = parseInt(parts[1] || '0')
    } else if (createdAt && createdAt > 0) {
      const d = new Date(createdAt * 1000)
      const utcMs2 = d.getTime() + d.getTimezoneOffset() * 60000
      const cn2 = new Date(utcMs2 + 8 * 3600000)
      hh = cn2.getHours(); mm = cn2.getMinutes()
    }
    if (hh === null || mm === null || isNaN(hh) || isNaN(mm)) return 'other'
    return `${String(hh).padStart(2,'0')}:${(mm as number) < 30 ? '00' : '30'}`
  }
  const signalsByHour = computed(() => {
    const rawSigs = visibleSignals.value as any[]
    // 去重: 同一 (ts_code, strategy) 只保留一条(最新)
    const seen = new Set<string>()
    const sigs = rawSigs.filter(s => {
      const k = `${s.ts_code}|${s.strategy}`
      if (seen.has(k)) return false
      seen.add(k)
      return true
    })
    if (!sigs.length) return []
    const slotMap = new Map<string, any[]>()
    for (const sig of sigs) {
      const sk = getSignalSlotKey(String(sig.scan_time || ''), sig.created_at)
      if (!slotMap.has(sk)) slotMap.set(sk, [])
      slotMap.get(sk)!.push(sig)
    }
    return SIGNAL_SLOT_DEFS.map(def => {
      const items = slotMap.get(def.key) || []
      // 30分钟子分组
      const hhMap = new Map<string, any[]>()
      for (const s of items) {
        const hk = getHalfHourKey(String(s.scan_time || ''), s.created_at)
        if (!hhMap.has(hk)) hhMap.set(hk, [])
        hhMap.get(hk)!.push(s)
      }
      const subGroups = [...hhMap.keys()].sort().map(hk => ({
        halfHour: hk,
        signals: (hhMap.get(hk) || []).slice().sort((a:any,b:any) => String(a.scan_time||'').localeCompare(String(b.scan_time||''))),
        count: (hhMap.get(hk) || []).length,
      }))
      return { hour: def.key, label: def.label, timeRange: def.timeRange, signals: items, count: items.length, subGroups }
    }).filter(g => g.count > 0)
  })
  const signalHourCollapse = ref<Record<string, boolean>>({})
  const signalSubCollapse = ref<Record<string, boolean>>({})
  const signalSubFilter = ref<Record<string, string>>({})  // '' | 'executed' | 'skipped' | 'blocked'
  const toggleSignalHour = (h: string) => { signalHourCollapse.value[h] = !signalHourCollapse.value[h] }
  const toggleSignalSubGroup = (k: string) => { signalSubCollapse.value[k] = !signalSubCollapse.value[k] }
  const cycleSubFilter = (k: string) => {
    const cur = signalSubFilter.value[k] || ''
    const next: Record<string,string> = { '': 'executed', 'executed': 'skipped', 'skipped': 'blocked', 'blocked': '' }
    signalSubFilter.value[k] = next[cur]
  }
  const signalHourInitialized = ref(false)
  watch(signalsByHour, (groups) => {
    if (!signalHourInitialized.value && groups.length) {
      // 默认全部折叠
      for (const g of groups) signalHourCollapse.value[g.hour] = true
      signalHourInitialized.value = true
    }
  }, { immediate: true })
  const signalFilterOptions = computed(() => [
    { k: 'all', l: '全部', title: '显示所有当前活跃信号', color: '' },
    { k: 'halfway_chase', l: '半路追涨', title: '盘中冲高2-7%+量能放大的追涨信号', color: '#e6a23c' },
    { k: 'first_limit_up', l: '首板打板', title: '首板涨停封板强的打板信号', color: '#f56c6c' },
    { k: 'limit_up_open', l: '涨停开板', title: '涨停炸板/开板后的回封观察信号', color: '#909399' },
    { k: 'dragon_head', l: '龙头低吸', title: '连板龙头回调低吸信号', color: '#409eff' },
    { k: 'limit_down_qiao', l: '跌停翘板', title: '跌停撬板反弹信号', color: '#67c23a' },
    { k: 'anomaly_surge', l: '急速拉升', title: '5分钟急速拉升异动信号', color: '#e6a23c' },
    { k: 'anomaly_broken', l: '涨停炸板', title: '涨停炸板异动信号', color: '#f56c6c' },
    { k: 'anomaly_strong', l: '强势涨停', title: '强势涨停确认信号', color: '#9c27b0' },
  ])
  const signalFilterHelp = computed(() => {
    const base = '活跃信号：当前仍有效、可关注/可操作的实时信号；历史扫描结果请看「扫描追踪」，这里的数量不等于今日全部扫描通过数。'
    const anomaly = '异动拆分为急速拉升/涨停炸板/强势涨停。'
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
    signalsByHour, signalHourCollapse, signalSubCollapse, signalSubFilter, toggleSignalHour, toggleSignalSubGroup, cycleSubFilter,
    signalFilterOptions, signalFilterHelp,
    toggleDateSection, togglePositionCard, toggleActiveSignalTrace,
    displayStrategyName, formatBuyDateDisplay, positionActionLabel,
    formatPositionTime, toggleStrategySection, formatTradeDateTime,
  }
}
