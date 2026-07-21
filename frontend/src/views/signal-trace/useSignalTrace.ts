/**
 * useSignalTrace - 信号追踪域
 * 全链路候选追踪: 竞价→9层管道→执行层→成交/拦截
 */
import { ref, computed } from 'vue'
import { api } from '@/api/client'
import { parseResponse } from '@/utils/scanner'
import { calcCompositeScore, fetchStrategyParams } from './scoreCalc'

const BASE = '/scanner'

export const PIPELINE_LAYERS = [
  { key: 'L1_force_empty', label: 'L1 强制空仓', short: 'L1', icon: '🚫', color: '#f56c6c' },
  { key: 'L2_special_period', label: 'L2 特殊时期', short: 'L2', icon: '⚠️', color: '#e6a23c' },
  { key: 'L3_sentiment', label: 'L3 情绪周期', short: 'L3', icon: '📊', color: '#409eff' },
  { key: 'L4_premarket', label: 'L4 盘前预选', short: 'L4', icon: '🔍', color: '#909399' },
  { key: 'L5_auction', label: 'L5 竞价过滤', short: 'L5', icon: '📋', color: '#e6a23c' },
  { key: 'L6_strategy', label: 'L6 策略量能', short: 'L6', icon: '📈', color: '#67c23a' },
  { key: 'L7_ranking', label: 'L7 综合排序', short: 'L7', icon: '🏅', color: '#409eff' },
  { key: 'L8_position', label: 'L8 仓位控制', short: 'L8', icon: '💰', color: '#e6a23c' },
  { key: 'L9_execute', label: 'L9 执行', short: 'L9', icon: '🎯', color: '#67c23a' },
]

export const FLOW_LAYERS = [
  { key: 'L1_force_empty', short: 'L1', label: '强制空仓', desc: '极端行情下禁止开仓' },
  { key: 'L2_special_period', short: 'L2', label: '特殊时期', desc: '特殊时段限制' },
  { key: 'L3_sentiment', short: 'L3', label: '情绪周期', desc: '市场情绪阶段' },
  { key: 'L4_premarket', short: 'L4', label: '盘前预选', desc: '基本面/技术面初筛' },
  { key: 'L5_auction', short: 'L5', label: '竞价过滤', desc: '竞价异常排除' },
  { key: 'L6_strategy', short: 'L6', label: '策略量能', desc: '策略专属过滤' },
  { key: 'L7_ranking', short: 'L7', label: '综合排序', desc: '因子加权打分排序' },
  { key: 'L8_position', short: 'L8', label: '仓位控制', desc: '风控拦截' },
  { key: 'L9_execute', short: 'L9', label: '执行队列', desc: '进入执行队列' },
  { key: 'execution', short: '下单', label: '执行结果', desc: '成交/拦截/观察' },
]

export function useSignalTrace() {
  const loading = ref(false)
  const tradeDate = ref('')
  const scanTraces = ref<any[]>([])
  const premarketSnapshots = ref<any[]>([])
  const stockTraces = ref<any[]>([])

  const filterLayer = ref('all')
  const filterResult = ref('all')
  const filterStrategy = ref('all')
  const filterScore = ref('all')
  const filterCap = ref('all')
  const expandedRows = ref<Set<string>>(new Set())

  const strategyList = computed(() => {
    const set = new Set<string>()
    stockTraces.value.forEach(s => { if (s.strategy) set.add(s.strategyName || s.strategy) })
    return Array.from(set).sort()
  })

  const layerList = [
    { key: 'all', label: '全部' },
    ...PIPELINE_LAYERS.map(l => ({ key: l.key, label: l.label })),
    { key: 'execution', label: '执行层' },
  ]

  const filteredStockTraces = computed(() => {
    let list = stockTraces.value
    if (filterStrategy.value && filterStrategy.value !== 'all') list = list.filter(s => s.strategy === filterStrategy.value)
    if (filterResult.value && filterResult.value !== 'all') {
      list = list.filter(s => {
        if (filterResult.value === 'bought') return s.finalStatus === 'bought'
        if (filterResult.value === 'passed') return s.finalStatus === 'passed'
        if (filterResult.value === 'rejected') return s.finalStatus !== 'passed' && s.finalStatus !== 'bought'
        return true
      })
    }
    if (filterLayer.value && filterLayer.value !== 'all') {
      list = list.filter(s => filterLayer.value === 'execution' ? s.rejectionType === 'execution' : s.rejectionLayer === filterLayer.value)
    }
    if (filterScore.value && filterScore.value !== 'all') {
      list = list.filter(s => {
        const sc = s.score || 0
        if (filterScore.value === 'high') return sc >= 70
        if (filterScore.value === 'mid') return sc >= 50 && sc < 70
        if (filterScore.value === 'low') return sc < 50
        return true
      })
    }
    if (filterCap.value && filterCap.value !== 'all') {
      list = list.filter(s => {
        const mv = (s.factors?.circ_mv || 0) / 10000
        if (filterCap.value === 'small') return mv < 30
        if (filterCap.value === 'mid') return mv >= 30 && mv < 100
        if (filterCap.value === 'large') return mv >= 100 && mv < 300
        if (filterCap.value === 'mega') return mv >= 300
        return true
      })
    }
    return list
  })

  const summary = computed(() => {
    const total = stockTraces.value.length
    const bought = stockTraces.value.filter(s => s.finalStatus === 'bought').length
    const passedNotBought = stockTraces.value.filter(s => s.finalStatus === 'passed').length
    const pipelineRejected = stockTraces.value.filter(s => s.rejectionType === 'pipeline').length
    const execBlocked = stockTraces.value.filter(s => s.rejectionType === 'execution').length
    const layerCounts: Record<string, number> = {}
    stockTraces.value.forEach(s => {
      if (s.rejectionType === 'pipeline' && s.rejectionLayer) layerCounts[s.rejectionLayer] = (layerCounts[s.rejectionLayer] || 0) + 1
    })
    const maxEntry = Object.entries(layerCounts).sort((a, b) => b[1] - a[1])[0]
    return { total, bought, passedNotBought, pipelineRejected, execBlocked, rejected: pipelineRejected + execBlocked, layerCounts, maxLayer: maxEntry ? `${layerLabel(maxEntry[0])}(${maxEntry[1]}只)` : '-', maxLayerKey: maxEntry?.[0] || '' }
  })

  const kpi = computed(() => {
    const list = filteredStockTraces.value
    const bought = list.filter(s => s.finalStatus === 'bought')
    const bc = bought.length
    const avgPct = bc ? bought.reduce((s, x) => s + (x.pctChg || 0), 0) / bc : 0
    const avgVR = bc ? bought.reduce((s, x) => s + (x.factors?.volume_ratio || 0), 0) / bc : 0
    const avgScore = list.length ? list.reduce((s, x) => s + (x.score || 0), 0) / list.length : 0
    const rejected = list.filter(s => s.finalStatus === 'rejected').length
    const winRate = (bc + rejected) > 0 ? bc / (bc + rejected) * 100 : 0
    return { boughtCount: bc, avgPct, avgVR, avgScore, winRate, total: list.length, rejected }
  })

  const timelineSlots = computed(() => {
    const nodes: any[] = []
    premarketSnapshots.value.forEach((ps: any) => {
      const t = ps.scan_time || ps.time || ''
      const hhmm = t.length >= 16 ? t.substring(11, 16) : t.substring(0, 5)
      const funnel = ps.funnel || ps.summary || ps.display_funnel || {}
      nodes.push({ time: hhmm, phase: '竞价', total: funnel.total_scanned || 0, candidates: funnel.strategy_candidates || funnel.total_candidates || ps.total_candidates || 0, passed: funnel.after_pipeline || funnel.passed || ps.passed || 0, buys: 0, type: 'premarket' })
    })
    const buckets: Record<string, any> = {}
    scanTraces.value.forEach(st => {
      const t = st.scan_time || ''
      const hhmm = t.length >= 16 ? t.substring(11, 16) : t.substring(0, 5)
      if (!hhmm || hhmm.length < 4) return
      const mm = parseInt(hhmm.substring(3, 5) || '0')
      const bucketKey = hhmm.substring(0, 3) + String(Math.floor(mm / 5) * 5).padStart(2, '0')
      if (!buckets[bucketKey]) buckets[bucketKey] = { time: bucketKey, phase: '盘中', total: 0, candidates: 0, passed: 0, buys: 0, blocked: 0, type: 'scan', count: 0 }
      const b = buckets[bucketKey], summ = st.summary || {}
      b.total = Math.max(b.total, summ.total_stocks || 0)
      b.candidates += summ.total_candidates || 0
      b.passed += summ.passed || 0
      const exec = st.exec || {}
      b.buys += exec.bought || 0
      b.blocked += exec.blocked || 0
      b.count++
    })
    Object.values(buckets).forEach(b => nodes.push(b))
    nodes.sort((a, b) => (a.time || '').localeCompare(b.time || ''))
    const slotDefs = [
      { key: 'premarket', label: '盘前竞价', type: 'premarket', start: '09:00', end: '09:30' },
      { key: 'early', label: '早盘', type: 'early', start: '09:30', end: '11:30' },
      { key: 'lunch', label: '午休', type: 'lunch', start: '11:30', end: '13:00' },
      { key: 'afternoon', label: '下午盘', type: 'afternoon', start: '13:00', end: '15:00' },
    ]
    return slotDefs.map(sd => {
      const sn = nodes.filter(n => (n.time || '') >= sd.start && (n.time || '') < sd.end)
      return { ...sd, nodes: sn, range: sn.length ? `${sn[0].time}-${sn[sn.length - 1].time}` : '', totalCand: sn.reduce((s, n) => s + (n.candidates || 0), 0), totalPassed: sn.reduce((s, n) => s + (n.passed || 0), 0), totalBuys: sn.reduce((s, n) => s + (n.buys || 0), 0), maxCand: Math.max(...sn.map(n => n.candidates || 0), 1) }
    }).filter(s => s.nodes.length > 0)
  })

  function layerLabel(key: string): string {
    const m: Record<string, string> = { L1_force_empty: 'L1强制空仓', L2_special_period: 'L2特殊时期', L3_sentiment: 'L3情绪', L4_premarket: 'L4盘前', L5_auction: 'L5竞价', L7_ranking: 'L7排序', L8_position: 'L8仓位', L8_cooldown: 'L8冷却', L8_ma60: 'L8 MA60', L8_market_risk: 'L8大盘风险', execution: '执行层' }
    return m[key] || key
  }

  async function fetchSignalTrace(date?: string) {
    if (date) tradeDate.value = date
    if (!tradeDate.value) { const now = new Date(); tradeDate.value = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}` }
    loading.value = true
    fetchStrategyParams().catch(() => {})
    try {
      const [tracesRes, premarketRes] = await Promise.all([
        api.get(`${BASE}/scan-traces`, { params: { date: tradeDate.value, limit: 200 } }).then(r => parseResponse(r)).catch(() => ({ data: [], execution_summary: {} })),
        api.get(`${BASE}/premarket-timeline`, { params: { date: tradeDate.value, limit: 30 } }).then(r => parseResponse(r)).catch(() => ({ data: { items: [] } })),
      ])
      scanTraces.value = (tracesRes as any).data || []
      const pmData = (premarketRes as any).data || {}
      premarketSnapshots.value = pmData.items || (Array.isArray(pmData) ? pmData : [])
      await buildStockTraces()
    } finally { loading.value = false }
  }

  async function buildStockTraces() {
    const map = new Map<string, any>()
    const allScans = scanTraces.value.filter(t => (t.summary?.total_candidates || 0) > 0 && t.scan_id)
    const priorityScans = [...allScans].sort((a, b) => {
      const aS = (a.exec?.bought || 0) * 100 + (a.exec?.blocked || 0) * 10 + (a.summary?.rejected || 0)
      const bS = (b.exec?.bought || 0) * 100 + (b.exec?.blocked || 0) * 10 + (b.summary?.rejected || 0)
      return bS - aS
    }).slice(0, 30)
    const batchSize = 5
    for (let i = 0; i < priorityScans.length; i += batchSize) {
      const batch = priorityScans.slice(i, i + batchSize)
      const results = await Promise.allSettled(batch.map(t => api.get(`${BASE}/scan-traces/${t.scan_id}`, { params: { status: 'all', limit: 100 } }).then(r => parseResponse(r)).catch(() => null)))
      for (const result of results) {
        if (result.status !== 'fulfilled' || !result.value) continue
        const data = result.value.data || {}
        const scanTime = data.scan_time || ''
        for (const c of (data.candidates || [])) mergeCandidate(map, c, scanTime)
      }
    }
    stockTraces.value = Array.from(map.values()).sort((a, b) => {
      if (a.finalStatus === 'bought' && b.finalStatus !== 'bought') return -1
      if (a.finalStatus !== 'bought' && b.finalStatus === 'bought') return 1
      if (a.finalStatus === b.finalStatus) return (b.score || 0) - (a.score || 0)
      if (a.finalStatus === 'passed' && b.finalStatus !== 'passed') return -1
      return (a.firstSeen || '').localeCompare(b.firstSeen || '')
    })
  }

  function mergeCandidate(map: Map<string, any>, c: any, scanTime: string) {
    const key = `${c.ts_code}|${c.strategy || c.strategy_name}`
    const existing = map.get(key)
    const status = c.final_status || 'unknown'
    const execStatus = c.execution_status || ''
    if (!existing) {
      const layerResults = c.layer_results || {}
      const rejectionLayer = c.final_rejection_layer || c.rejection_layer || ''
      const rejectionReason = c.final_rejection_reason || c.rejection_reason || ''
      if (!Object.keys(layerResults).length && rejectionLayer) Object.assign(layerResults, buildLayerResultsFromRejection(rejectionLayer, rejectionReason))
      let rejectionType = ''
      if (status === 'passed' && execStatus === 'blocked') rejectionType = 'execution'
      else if (status !== 'passed') rejectionType = rejectionLayer.startsWith('L') ? 'pipeline' : 'execution'
      let displayRejectionLayer = rejectionLayer, displayRejectionReason = rejectionReason || c.execution_desc || ''
      if (status === 'passed' && execStatus === 'blocked') {
        displayRejectionLayer = 'execution'; displayRejectionReason = c.execution_desc || '执行层拦截'
        if (!layerResults.execution) layerResults.execution = { passed: false, reason: displayRejectionReason }
      }
      const isBought = status === 'passed' && execStatus === 'bought'
      const execDetail = c.execution_detail || {}
      const factors = c.factors || {}
      map.set(key, {
        tsCode: c.ts_code, stockName: c.stock_name || '', strategy: c.strategy || c.strategy_name || '', strategyName: c.strategy_name || c.strategy || '',
        price: c.price, pctChg: c.pct_chg, firstSeen: scanTime, lastSeen: scanTime,
        layerResults, finalStatus: isBought ? 'bought' : (status === 'passed' && execStatus !== 'blocked' ? 'passed' : 'rejected'),
        rejectionLayer: displayRejectionLayer, rejectionReason: displayRejectionReason, rejectionType,
        executionStatus: execStatus, executionDesc: c.execution_desc || '', executionTime: execDetail.time || '',
        boughtPrice: execDetail.price || 0, boughtShares: execDetail.shares || 0, boughtAmount: execDetail.amount || 0,
        factors, reason: c.reason || '', score: calcCompositeScore(factors, c.strategy || c.strategy_name || '', status), scanCount: 1,
      })
    } else {
      existing.lastSeen = scanTime; existing.scanCount++
      if (c.factors) { existing.factors = { ...existing.factors, ...c.factors }; existing.score = calcCompositeScore(existing.factors, existing.strategy, existing.finalStatus) }
      if (c.reason && !existing.reason) existing.reason = c.reason
      if (status === 'passed' && execStatus !== 'blocked' && existing.finalStatus !== 'bought') { existing.finalStatus = 'passed'; existing.rejectionLayer = ''; existing.rejectionReason = ''; existing.rejectionType = '' }
      if (c.layer_results) Object.assign(existing.layerResults, c.layer_results)
      if (execStatus && !existing.executionStatus) {
        existing.executionStatus = execStatus; existing.executionDesc = c.execution_desc || ''
        const ed = c.execution_detail || {}
        if (ed.time) existing.executionTime = ed.time; if (ed.price) existing.boughtPrice = ed.price; if (ed.shares) existing.boughtShares = ed.shares; if (ed.amount) existing.boughtAmount = ed.amount
        if (execStatus === 'blocked') { existing.rejectionLayer = 'execution'; existing.rejectionReason = c.execution_desc || '执行层拦截'; existing.rejectionType = 'execution'; existing.layerResults.execution = { passed: false, reason: c.execution_desc || '' }; if (existing.finalStatus === 'passed') existing.finalStatus = 'rejected' }
        if (execStatus === 'bought') existing.finalStatus = 'bought'
      }
    }
  }

  function buildLayerResultsFromRejection(layer: string, reason: string): Record<string, any> {
    const result: Record<string, any> = {}
    const order = ['L1_force_empty', 'L2_special_period', 'L3_sentiment', 'L4_premarket', 'L5_auction', 'L6_strategy', 'L7_ranking', 'L8_position']
    let found = false
    for (const l of order) { if (l === layer) { result[l] = { passed: false, reason }; found = true } else if (!found) { result[l] = { passed: true, reason: '' } } }
    return result
  }

  function toggleRow(key: string) { if (expandedRows.value.has(key)) expandedRows.value.delete(key); else expandedRows.value.add(key) }
  function fmtTime(iso: string): string { if (!iso) return ''; return iso.length >= 16 ? iso.substring(11, 16) : iso }
  function fmtTimeSec(iso: string): string { if (!iso) return ''; return iso.length >= 19 ? iso.substring(11, 19) : iso.length >= 16 ? iso.substring(11, 16) : iso }

  return {
    loading, tradeDate, scanTraces, premarketSnapshots, stockTraces,
    filterLayer, filterResult, filterStrategy, filterScore, filterCap, expandedRows,
    strategyList, layerList,
    filteredStockTraces, summary, kpi, timelineNodes: timelineSlots,
    fetchSignalTrace, toggleRow, fmtTime, fmtTimeSec, layerLabel,
  }
}
