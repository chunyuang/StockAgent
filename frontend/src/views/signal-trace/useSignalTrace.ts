/**
 * useSignalTrace - 信号追踪域
 * 全链路候选追踪: 竞价→9层管道→执行层→成交/拦截
 */
import { ref, computed } from 'vue'
import { api } from '@/api/client'
import { parseResponse } from '@/utils/scanner'

const BASE = '/scanner'

// 管道层完整定义
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

export function useSignalTrace() {
  const loading = ref(false)
  const tradeDate = ref('')
  const scanTraces = ref<any[]>([])
  const premarketSnapshots = ref<any[]>([])
  const funnelData = ref<any>(null)
  const stockTraces = ref<any[]>([])

  // 策略参数: 从后端动态获取, 评分函数引用这些值而非硬编码
  const strategyParams = ref<Record<string, any>>({})

  async function fetchStrategyParams() {
    try {
      const strategies = ['halfway_chase', 'first_limit_up', 'dragon_head', 'limit_down_qiao', 'limit_up_open']
      const results: Record<string, any> = {}
      await Promise.all(strategies.map(async (sid) => {
        try {
          const resp = await api.get(`${BASE}/params/${sid}`)
          const data = parseResponse(resp) as any
          if (data?.params) results[sid] = data.params
        } catch (e) { console.warn('[useSignalTrace] 策略参数获取失败 sid=%s:', sid, e) }
      }))
      strategyParams.value = results
    } catch (e) { console.warn('[useSignalTrace] 整体策略参数获取失败:', e) }
  }

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
    if (filterStrategy.value && filterStrategy.value !== 'all') {
      list = list.filter(s => s.strategy === filterStrategy.value)
    }
    if (filterResult.value && filterResult.value !== 'all') {
      list = list.filter(s => {
        if (filterResult.value === 'bought') return s.finalStatus === 'bought'
        if (filterResult.value === 'passed') return s.finalStatus === 'passed'
        if (filterResult.value === 'rejected') return s.finalStatus !== 'passed' && s.finalStatus !== 'bought'
        return true
      })
    }
    if (filterLayer.value && filterLayer.value !== 'all') {
      list = list.filter(s => {
        if (filterLayer.value === 'execution') return s.rejectionType === 'execution'
        return s.rejectionLayer === filterLayer.value
      })
    }
    // 评分区间筛选
    if (filterScore.value && filterScore.value !== 'all') {
      list = list.filter(s => {
        const sc = s.score || 0
        if (filterScore.value === 'high') return sc >= 70
        if (filterScore.value === 'mid') return sc >= 50 && sc < 70
        if (filterScore.value === 'low') return sc < 50
        return true
      })
    }
    // 市值筛选
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
    const rejected = pipelineRejected + execBlocked
    const layerCounts: Record<string, number> = {}
    stockTraces.value.forEach(s => {
      if (s.rejectionType === 'pipeline' && s.rejectionLayer) {
        layerCounts[s.rejectionLayer] = (layerCounts[s.rejectionLayer] || 0) + 1
      }
    })
    const maxEntry = Object.entries(layerCounts).sort((a, b) => b[1] - a[1])[0]
    const maxLayerKey = maxEntry ? maxEntry[0] : ''
    return {
      total, bought, passedNotBought, pipelineRejected, execBlocked, rejected,
      layerCounts,
      maxLayer: maxEntry ? `${layerLabel(maxEntry[0])}(${maxEntry[1]}只)` : '-',
      maxLayerKey,
    }
  })

  const timelineNodes = computed(() => {
    const nodes: any[] = []
    premarketSnapshots.value.forEach((ps: any) => {
      const t = ps.scan_time || ps.time || ''
      const hhmm = t.length >= 16 ? t.substring(11, 16) : t.substring(0, 5)
      const funnel = ps.funnel || ps.summary || ps.display_funnel || {}
      nodes.push({
        time: hhmm, phase: '竞价',
        total: funnel.total_scanned || 0,
        candidates: funnel.strategy_candidates || funnel.total_candidates || ps.total_candidates || 0,
        passed: funnel.after_pipeline || funnel.passed || ps.passed || 0,
        buys: 0, type: 'premarket',
      })
    })
    const buckets: Record<string, any> = {}
    scanTraces.value.forEach(st => {
      const t = st.scan_time || ''
      const hhmm = t.length >= 16 ? t.substring(11, 16) : t.substring(0, 5)
      if (!hhmm || hhmm.length < 4) return
      const mm = parseInt(hhmm.substring(3, 5) || '0')
      const bucketMin = Math.floor(mm / 5) * 5
      const bucketKey = hhmm.substring(0, 3) + String(bucketMin).padStart(2, '0')
      if (!buckets[bucketKey]) {
        buckets[bucketKey] = {
          time: bucketKey, phase: '盘中',
          total: 0, candidates: 0, passed: 0, buys: 0, blocked: 0, type: 'scan', count: 0,
        }
      }
      const b = buckets[bucketKey]
      const summ = st.summary || {}
      b.total = Math.max(b.total, summ.total_stocks || 0)
      b.candidates += (summ.total_candidates || 0)
      b.passed += (summ.passed || 0)
      const exec = st.exec || {}
      b.buys += (exec.bought || 0)
      b.blocked += (exec.blocked || 0)
      b.count++
    })
    Object.values(buckets).forEach(b => nodes.push(b))
    nodes.sort((a, b) => (a.time || '').localeCompare(b.time || ''))
    return nodes
  })

  function layerLabel(key: string): string {
    const map: Record<string, string> = {
      L1_force_empty: 'L1强制空仓', L2_special_period: 'L2特殊时期',
      L3_sentiment: 'L3情绪', L4_premarket: 'L4盘前', L5_auction: 'L5竞价',
      L7_ranking: 'L7排序', L8_position: 'L8仓位', L8_cooldown: 'L8冷却',
      L8_ma60: 'L8 MA60', L8_market_risk: 'L8大盘风险', execution: '执行层',
    }
    return map[key] || key
  }

  async function fetchSignalTrace(date?: string) {
    if (date) tradeDate.value = date
    if (!tradeDate.value) {
      const now = new Date()
      tradeDate.value = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}`
    }
    loading.value = true
    // 首次加载时获取策略参数(评分函数动态引用)
    if (!Object.keys(strategyParams.value).length) {
      fetchStrategyParams() // 不await, 异步加载不阻塞页面
    }
    try {
      const [tracesRes, premarketRes] = await Promise.all([
        api.get(`${BASE}/scan-traces`, { params: { date: tradeDate.value, limit: 200 } })
          .then(r => parseResponse(r)).catch(() => ({ data: [], execution_summary: {} })),
        api.get(`${BASE}/premarket-timeline`, { params: { date: tradeDate.value, limit: 30 } })
          .then(r => parseResponse(r)).catch(() => ({ data: { items: [] } })),
      ])
      scanTraces.value = (tracesRes as any).data || []
      const pmData = (premarketRes as any).data || {}
      premarketSnapshots.value = pmData.items || (Array.isArray(pmData) ? pmData : [])
      funnelData.value = (tracesRes as any).execution_summary || null
      await buildStockTraces()
    } finally {
      loading.value = false
    }
  }

  async function buildStockTraces() {
    const map = new Map<string, any>()
    const allScans = scanTraces.value.filter(t => {
      const summ = t.summary || {}
      return (summ.total_candidates || 0) > 0 && t.scan_id
    })
    const priorityScans = [...allScans].sort((a, b) => {
      const aExec = a.exec || {}
      const bExec = b.exec || {}
      const aScore = (aExec.bought || 0) * 100 + (aExec.blocked || 0) * 10 + (a.summary?.rejected || 0)
      const bScore = (bExec.bought || 0) * 100 + (bExec.blocked || 0) * 10 + (b.summary?.rejected || 0)
      return bScore - aScore
    }).slice(0, 30)

    const batchSize = 5
    for (let i = 0; i < priorityScans.length; i += batchSize) {
      const batch = priorityScans.slice(i, i + batchSize)
      const results = await Promise.allSettled(
        batch.map(t =>
          api.get(`${BASE}/scan-traces/${t.scan_id}`, { params: { status: 'all', limit: 100 } })
            .then(r => parseResponse(r)).catch(() => null)
        )
      )
      for (const result of results) {
        if (result.status !== 'fulfilled' || !result.value) continue
        const data = result.value.data || {}
        const scanTime = data.scan_time || ''
        for (const c of (data.candidates || [])) {
          mergeCandidate(map, c, scanTime)
        }
      }
    }

    stockTraces.value = Array.from(map.values()).sort((a, b) => {
      if (a.finalStatus === 'bought' && b.finalStatus !== 'bought') return -1
      if (a.finalStatus !== 'bought' && b.finalStatus === 'bought') return 1
      // 同状态按评分降序
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

      if (!Object.keys(layerResults).length && rejectionLayer) {
        Object.assign(layerResults, buildLayerResultsFromRejection(rejectionLayer, rejectionReason))
      }

      let rejectionType = ''
      if (status === 'passed' && execStatus === 'blocked') {
        rejectionType = 'execution'
      } else if (status !== 'passed') {
        rejectionType = rejectionLayer.startsWith('L') ? 'pipeline' : 'execution'
      }

      let displayRejectionLayer = rejectionLayer
      let displayRejectionReason = rejectionReason || c.execution_desc || ''

      if (status === 'passed' && execStatus === 'blocked') {
        displayRejectionLayer = 'execution'
        displayRejectionReason = c.execution_desc || '执行层拦截'
        if (!layerResults.execution) {
          layerResults.execution = { passed: false, reason: displayRejectionReason }
        }
      }

      const isBought = status === 'passed' && execStatus === 'bought'
      const execDetail = c.execution_detail || {}
      const factors = c.factors || {}
      const reason = c.reason || ''

      // 综合评分: 多因子加权
      const score = calcCompositeScore(factors, c.strategy || c.strategy_name || '', status)

      map.set(key, {
        tsCode: c.ts_code,
        stockName: c.stock_name || '',
        strategy: c.strategy || c.strategy_name || '',
        strategyName: c.strategy_name || c.strategy || '',
        price: c.price,
        pctChg: c.pct_chg,
        firstSeen: scanTime,
        lastSeen: scanTime,
        layerResults,
        finalStatus: isBought ? 'bought' : (status === 'passed' && execStatus !== 'blocked' ? 'passed' : 'rejected'),
        rejectionLayer: displayRejectionLayer,
        rejectionReason: displayRejectionReason,
        rejectionType,
        executionStatus: execStatus,
        executionDesc: c.execution_desc || '',
        executionTime: execDetail.time || '',
        boughtPrice: execDetail.price || 0,
        boughtShares: execDetail.shares || 0,
        boughtAmount: execDetail.amount || 0,
        factors,
        reason,
        score,
        scanCount: 1,
      })
    } else {
      existing.lastSeen = scanTime
      existing.scanCount++
      // 更新factors/score(取最新的)
      if (c.factors && !existing.factors) existing.factors = c.factors
      if (c.reason && !existing.reason) existing.reason = c.reason
      if (!existing.factors) existing.factors = {}
      if (c.factors) {
        existing.factors = { ...existing.factors, ...c.factors }
        existing.score = calcCompositeScore(existing.factors, existing.strategy, existing.finalStatus)
      }
      if (status === 'passed' && execStatus !== 'blocked' && existing.finalStatus !== 'bought') {
        existing.finalStatus = 'passed'
        existing.rejectionLayer = ''
        existing.rejectionReason = ''
        existing.rejectionType = ''
      }
      if (c.layer_results) {
        Object.assign(existing.layerResults, c.layer_results)
      }
      if (execStatus && !existing.executionStatus) {
        existing.executionStatus = execStatus
        existing.executionDesc = c.execution_desc || ''
        const ed = c.execution_detail || {}
        if (ed.time) existing.executionTime = ed.time
        if (ed.price) existing.boughtPrice = ed.price
        if (ed.shares) existing.boughtShares = ed.shares
        if (ed.amount) existing.boughtAmount = ed.amount
        if (execStatus === 'blocked') {
          existing.rejectionLayer = 'execution'
          existing.rejectionReason = c.execution_desc || '执行层拦截'
          existing.rejectionType = 'execution'
          existing.layerResults.execution = { passed: false, reason: c.execution_desc || '' }
          if (existing.finalStatus === 'passed') existing.finalStatus = 'rejected'
        }
        if (execStatus === 'bought') {
          existing.finalStatus = 'bought'
        }
      }
    }
  }

  /** 综合评分: 策略感知的多因子加权打分, 动态引用后端策略参数 */
  function calcCompositeScore(factors: Record<string, any>, strategy: string, status: string): number {
    if (!factors || !Object.keys(factors).length) return 0
    switch (strategy) {
      case 'halfway_chase': return calcHalfwayChase(factors, status)
      case 'first_limit_up': return calcFirstLimitUp(factors, status)
      case 'dragon_head': return calcDragonHead(factors, status)
      case 'limit_down_qiao': return calcLimitDownQiao(factors, status)
      case 'limit_up_open': return calcLimitUpOpen(factors, status)
      default: return calcGeneric(factors, status)
    }
  }

  /** 半路追涨(数据驱动): 开盘位置(25)+量比(20)+涨幅(15)+换手(15)+MA5(15)+市值(5)+恐贪(5)
   *  实盘106笔验证:
   *  - 开盘+2~3%: 7笔0%胜率均亏-7.0% → 大扣分
   *  - 量比1.5-2.5x: 胜率80% → 最佳; >5x仅35% → 扣分
   *  - 涨幅5-6%: 胜率40%; 6-7%仅34% → 6%以上逐步扣分
   *  - 换手2-5%: 胜率46%; >5%仅12% → 高换手危险
   *  - MA5偏离+0~1%: 64笔最多,胜率44% → 正偏离加分
   */
  function calcHalfwayChase(f: Record<string, any>, status: string): number {
    let s = 0
    const p = strategyParams.value.halfway_chase || {}
    const minRise = (p.min_rise_pct ?? 0.03) * 100
    const maxRise = (p.max_rise_pct ?? 0.07) * 100
    const minVr = p.min_volume_ratio ?? 1.5
    const maxVr = p.max_volume_ratio ?? 3.0

    // 1. 开盘位置(25分) — 实盘最强区分力因子(区分力134%)
    //    低开-1~+1%: 胜率44%; +2~3%: 0%胜率均亏-7%
    const openRise = f.opening_pct_chg || f.open_rise_pct || f.open_pct || 0
    if (openRise >= -1 && openRise <= 1) s += 25         // 低开冲高最佳(胜率44%)
    else if (openRise > 1 && openRise <= 2) s += 15      // 略高开(胜率43%)
    else if (openRise > 2) s -= 10                        // 高开追涨=自杀(0%胜率)
    else s += 15                                           // 大幅低开

    // 2. 量比(20分) — 实盘第二强区分力因子(区分力29%)
    //    1.5-2.5x胜率80%; >5x仅35%; 10x以上33%
    const vr = f.volume_ratio || 0
    if (vr >= minVr && vr <= 2.5) s += 20                 // 适度量能最佳(80%胜率)
    else if (vr > 2.5 && vr <= maxVr) s += 12             // 量能充足但有回调风险
    else if (vr > maxVr && vr <= 5) s += 5                // 过热(35%胜率)
    else if (vr > 5 && vr <= 10) s -= 5                   // 严重过热(37%胜率均亏-2.7%)
    else if (vr > 10) s -= 10                             // 极度过热(33%胜率)
    else s += 3                                            // 量能不足

    // 3. 涨幅(15分) — 区分力仅0.7%,但分箱有方向性
    //    5-6%胜率40%; 6-7%仅34%
    const pct = f.pct_chg || 0
    if (pct >= minRise && pct < (minRise + maxRise) / 2) s += 15  // 理想区间(5-5.5%)
    else if (pct >= (minRise + maxRise) / 2 && pct <= maxRise) s += 8  // 偏高(5.5-7%)
    else if (pct > maxRise && pct <= maxRise + 2) s -= 5           // 超出上限
    else if (pct > maxRise + 2) s -= 15                            // 追顶
    else s += 5

    // 4. 换手率(15分) — 换手5-10%仅12%胜率, 强区分力
    const tr = f.turnover_rate || 0
    if (tr >= 2 && tr <= 5) s += 15                        // 理想换手(胜率46%)
    else if (tr >= 1 && tr < 2) s += 10                    // 偏低(胜率36%)
    else if (tr >= 0.5 && tr < 1) s += 5                   // 低换手(胜率34%)
    else if (tr > 5 && tr <= 10) s -= 10                   // 高换手危险(12%胜率!)
    else if (tr > 10) s += 0                               // 极端换手(样本少)
    else s += 3

    // 5. MA5偏离(15分) — 正偏离+0~1%胜率44%, 负偏离-5%以下胜率40%
    const pb = f.pullback_pct || 0
    const pbPct = pb * 100
    if (pbPct > 0 && pbPct <= 1) s += 15                   // 略高于MA5(胜率44%)
    else if (pbPct > 1 && pbPct <= 3) s += 10              // 明显高于MA5
    else if (pbPct >= -1 && pbPct <= 0) s += 8             // 贴近MA5
    else if (pbPct >= -3 && pbPct < -1) s += 3             // 略低于MA5
    else if (pbPct >= -5 && pbPct < -3) s -= 5             // 低于MA5(胜率25%)
    else if (pbPct < -5) s -= 10                           // 远低于MA5

    // 6. 流通市值(5分) — 区分力弱
    const mv = (f.circ_mv || 0) / 10000
    if (mv >= 20 && mv <= 200) s += 5
    else if (mv >= 200 && mv <= 500) s += 3
    else s += 1

    // 7. 恐贪指数(5分) — fear_greed_index < 3冰点反弹胜率100%, 5-7正常40%
    const fgi = f.fear_greed_index
    if (fgi != null && fgi > 0) {
      if (fgi < 3) s += 5                                    // 冰点反弹(胜率100%)
      else if (fgi >= 3 && fgi < 5) s += 2                  // 恐惧区间
      else if (fgi >= 5 && fgi < 7) s += 3                  // 正常区间(胜率40%)
      else s += 1                                            // 贪婪区间
    }

    if (status === 'bought') s += 20
    return Math.max(0, Math.min(100, s))
  }
  function calcFirstLimitUp(f: Record<string, any>, status: string): number {
    let s = 0
    const p = strategyParams.value.first_limit_up || {}
    const minVr = p.min_volume_ratio ?? 1.5
    const minTr = p.min_turnover_rate ?? 3
    const minMv = p.min_circulation_market_cap ?? 10
    const maxMv = p.max_circulation_market_cap ?? 500
    const openMin = p.opening_pct_min ?? -1
    const openMax = p.opening_pct_max ?? 5

    const pct = f.pct_chg || 0
    if (pct >= 9.5) s += 30; else if (pct >= 7) s += 20; else if (pct >= 5) s += 12; else s += 5

    const tr = f.turnover_rate || 0
    if (tr >= minTr && tr <= minTr + 15) s += 20
    else if (tr >= minTr) s += 12
    else s += 3

    const mv = (f.circ_mv || 0) / 10000
    if (mv >= Math.max(minMv, 50) && mv <= Math.min(maxMv, 300)) s += 20
    else if (mv >= minMv) s += 12
    else s += 5

    const vr = f.volume_ratio || 0
    if (vr >= minVr && vr <= 5) s += 15; else if (vr >= 1) s += 8; else s += 3

    const openPct = f.opening_pct_chg || f.open_rise_pct || f.open_pct || 0
    if (openPct >= openMin && openPct <= openMax * 0.6) s += 15
    else if (openPct <= openMax) s += 10
    else s += 3

    if (status === 'bought') s += 20
    return Math.max(0, Math.min(100, s))
  }

  /** 龙头低吸: 回调幅度(25)+缩量程度(25)+连板数(20)+市值(15)+支撑强度(15) */
  function calcDragonHead(f: Record<string, any>, status: string): number {
    let s = 0
    const p = strategyParams.value.dragon_head || {}
    const minCorrection = (p.min_correction_pct ?? 0.05) * 100
    const maxCorrection = (p.max_correction_pct ?? 0.22) * 100
    const minVr = p.min_volume_ratio ?? 0.5
    const maxVr = p.max_volume_ratio ?? 2.0
    const minMv = p.min_circulation_market_cap ?? 30

    const pct = f.pct_chg || 0
    const correction = Math.abs(pct)
    if (correction >= minCorrection && correction <= minCorrection + 5) s += 25  // 理想回调
    else if (correction > minCorrection + 5 && correction <= maxCorrection * 0.7) s += 20
    else if (correction > maxCorrection * 0.7 && correction <= maxCorrection) s += 10
    else s += 5

    const vr = f.volume_ratio || 0
    // 龙头低吸: 缩量=好信号, 放量=危险(与追涨逻辑相反!)
    if (vr >= minVr && vr <= (minVr + maxVr) / 2) s += 25   // 缩量回调最佳
    else if (vr >= minVr && vr <= maxVr) s += 15
    else if (vr > maxVr) s += 3                              // 放量回调危险
    else s += 5

    const limitDays = f.limit_up_days || f.consecutive_limit || 1
    if (limitDays >= 3) s += 20; else if (limitDays >= 2) s += 15; else s += 8

    const mv = (f.circ_mv || 0) / 10000
    if (mv >= minMv && mv <= 300) s += 15; else if (mv >= minMv) s += 10; else s += 5

    const pb = f.pullback_pct || 0
    if (pb >= -0.03 && pb <= 0) s += 15; else if (pb > 0 && pb <= 0.02) s += 10; else s += 3

    if (status === 'bought') s += 20
    return Math.max(0, Math.min(100, s))
  }

  /** 跌停翘板: 翘板强度(30)+换手(25)+市值(20)+连跌(15)+量比(10) */
  function calcLimitDownQiao(f: Record<string, any>, status: string): number {
    let s = 0
    const p = strategyParams.value.limit_down_qiao || {}
    const minTr = p.min_turnover_rate ?? 10
    const minMv = p.min_circulation_market_cap ?? 20
    const minQiaoRise = (p.min_rise_after_qiao ?? 0.03) * 100
    const minLimitDown = p.min_consecutive_limit ?? 2

    const pct = f.pct_chg || 0
    if (pct >= minQiaoRise && pct <= minQiaoRise + 2) s += 30    // 翘板后理想涨幅
    else if (pct > minQiaoRise + 2) s += 20
    else if (pct >= 0) s += 10
    else s += 0

    const tr = f.turnover_rate || 0
    if (tr >= minTr && tr <= minTr + 10) s += 25
    else if (tr > minTr + 10) s += 15
    else s += 3

    const mv = (f.circ_mv || 0) / 10000
    if (mv >= minMv && mv <= 200) s += 20; else if (mv >= minMv) s += 12; else s += 5

    const limitDownDays = f.limit_down_days || f.consecutive_limit_down || 1
    if (limitDownDays === minLimitDown) s += 15
    else if (limitDownDays >= minLimitDown + 1) s += 5
    else s += 8

    const vr = f.volume_ratio || 0
    if (vr >= 3) s += 15; else if (vr >= 2) s += 10; else s += 3

    if (status === 'bought') s += 20
    return Math.max(0, Math.min(100, s))
  }

  /** 涨停开板: 连板数(25)+量比(25)+换手(20)+市值(15)+涨幅(15) */
  function calcLimitUpOpen(f: Record<string, any>, status: string): number {
    let s = 0
    const p = strategyParams.value.limit_up_open || {}
    const minVr = p.min_volume_ratio ?? 2.0
    const minTr = p.min_turnover_rate ?? 15

    const pct = f.pct_chg || 0
    if (pct >= 8) s += 25; else if (pct >= 5) s += 15; else s += 5
    const vr = f.volume_ratio || 0
    if (vr >= minVr && vr <= 5) s += 25; else if (vr >= minVr * 0.75) s += 15; else s += 5
    const tr = f.turnover_rate || 0
    if (tr >= minTr && tr <= minTr + 15) s += 20; else if (tr >= minTr * 0.7) s += 12; else s += 5
    const mv = (f.circ_mv || 0) / 10000
    if (mv >= 50 && mv <= 300) s += 15; else if (mv >= 20) s += 10; else s += 5
    if (status === 'bought') s += 20
    return Math.max(0, Math.min(100, s))
  }

  /** 通用评分: anomaly等观察信号(不依赖策略参数) */
  function calcGeneric(f: Record<string, any>, status: string): number {
    let s = 0
    const pct = f.pct_chg || 0
    if (pct >= 4 && pct <= 7) s += 30; else if (pct >= 2) s += 15; else if (pct > 7) s += 10; else s += 5
    const vr = f.volume_ratio || 0
    if (vr >= 1.5 && vr <= 5) s += 25; else if (vr >= 1) s += 10; else s += 3
    const tr = f.turnover_rate || 0
    if (tr >= 1 && tr <= 5) s += 15; else if (tr > 5 && tr <= 10) s += 8; else s += 3
    const mv = (f.circ_mv || 0) / 10000
    if (mv >= 30 && mv <= 200) s += 15; else s += 5
    if (status === 'bought') s += 20
    return Math.max(0, Math.min(100, s))
  }
  function buildLayerResultsFromRejection(layer: string, reason: string): Record<string, any> {
    const result: Record<string, any> = {}
    const layerOrder = [
      'L1_force_empty', 'L2_special_period', 'L3_sentiment',
      'L4_premarket', 'L5_auction', 'L6_strategy', 'L7_ranking', 'L8_position',
    ]
    let found = false
    for (const l of layerOrder) {
      if (l === layer) { result[l] = { passed: false, reason }; found = true }
      else if (!found) { result[l] = { passed: true, reason: '' } }
    }
    return result
  }

  function toggleRow(key: string) {
    if (expandedRows.value.has(key)) expandedRows.value.delete(key)
    else expandedRows.value.add(key)
  }

  function fmtTime(iso: string): string {
    if (!iso) return ''
    if (iso.length >= 16) return iso.substring(11, 16)
    return iso
  }

  function fmtTimeSec(iso: string): string {
    if (!iso) return ''
    if (iso.length >= 19) return iso.substring(11, 19)
    if (iso.length >= 16) return iso.substring(11, 16)
    return iso
  }

  return {
    loading, tradeDate,
    scanTraces, premarketSnapshots,
    funnelData, stockTraces,
    filterLayer, filterResult, filterStrategy, filterScore, filterCap,
    expandedRows,
    strategyList, layerList,
    filteredStockTraces, summary, timelineNodes,
    fetchSignalTrace, toggleRow, fmtTime, fmtTimeSec, layerLabel,
  }
}
