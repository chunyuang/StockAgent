/**
 * useScanTraceMonitor - 扫描追踪域
 * 
 * 从useScannerMonitor拆出的扫描追踪相关逻辑
 * 管理: scanTraceDates/scanTraceList/scanTraceDetail/层级调试
 */

import { ref, computed } from 'vue'
import { api } from '@/api/client'
import { parseResponse, pipelineLabels } from '@/utils/scanner'

const scannerApi = '/scanner'

export function useScanTraceMonitor() {
  // ==================== 扫描追踪状态 ====================
  const scanTraceDates = ref<string[]>([])
  const scanTraceList = ref<any[]>([])
  const scanTraceDetail = ref<any>(null)
  const signalTraceVisible = ref(false)

  const scanTraceDate = ref('')
  const scanTraceFilter = ref('all')
  const scanTraceLoadingMore = ref(false)
  const selectedScanIdx = ref(-1)
  const scanHistory = ref<any[]>([])
  const scanHistoryLoading = ref(false)
  // 默认生产模式；只有显式打开调试审计，才请求debug/off-session数据
  const scanTraceDebugMode = ref(false)

  // 按小时分组+折叠
  const scanHourCollapse = ref<Record<string, boolean>>({})
  // 【v2.9.95】全天执行摘要(buys/blocked/block_reasons)
  const executionSummary = ref<any>(null)

  const scanHistoryByHour = computed(() => {
    if (!scanHistory.value.length) return []
    const hourMap = new Map<string, any[]>()
    for (const s of scanHistory.value) {
      const t = s.scan_time || s.time || ''
      const hour = t.length > 11 ? t.substring(11, 13) : '??'
      if (!hourMap.has(hour)) hourMap.set(hour, [])
      hourMap.get(hour)!.push(s)
    }
    // 降序排列: 最新时段在最上面；默认全部折叠，点击小时行后再展开
    const hours = [...hourMap.keys()].sort((a, b) => b.localeCompare(a))
    return hours.map(h => ({
      hour: h,
      items: hourMap.get(h) || [],
      collapsed: scanHourCollapse.value[h] ?? true
    }))
  })

  function toggleScanHour(hour: string) {
    // 从computed获取实际折叠状态(而非从scanHourCollapse直接取, 因为latestHour默认展开)
    const group = scanHistoryByHour.value.find(g => g.hour === hour)
    const current = group?.collapsed ?? true
    scanHourCollapse.value = { ...scanHourCollapse.value, [hour]: !current }
  }

  // 日期高亮
  const scanTraceHasData = ref<any[]>([])

  // ==================== 层级调试 ====================
  const layerDebugVisible = ref(false)
  const layerDebugData = ref<any>(null)
  const layerDebugLoading = ref(false)

  // ==================== API ====================
  async function fetchScanTraceDates() {
    try {
      const r = await api.get(`${scannerApi}/scan-dates`, { timeout: 10000 })
      const p = parseResponse(r)
      if (p.success && p.data?.length) {
        scanTraceDates.value = p.data || []
        scanTraceHasData.value = p.data  // [{date, count, is_debug}]
      }
      return scanTraceDates.value  // 返回日期列表供onMounted使用
    } catch { /* ignore */ }
    return []
  }

  async function fetchScanHistory() {
    if (!scanTraceDate.value) { scanHistory.value = []; scanTraceDetail.value = null; return }
    scanHistoryLoading.value = true
    scanTraceDetail.value = null
    selectedScanIdx.value = -1
    // 切换日期时重置折叠状态, 避免旧状态残留
    scanHourCollapse.value = {}
    try {
      const dataMode = scanTraceDebugMode.value ? 'debug' : 'production'
      const r = await api.get(`${scannerApi}/scan-traces?limit=200&date=${scanTraceDate.value.replace(/-/g, '')}&mode=${dataMode}`, { timeout: 15000 })
      const p = parseResponse(r)
      if (p.success && p.data?.length) {
        scanHistory.value = p.data
        // 【v2.9.95】保存全天执行摘要
        executionSummary.value = (r as any)?.execution_summary || null
      } else {
        scanHistory.value = []
        executionSummary.value = null
      }
    } catch { scanHistory.value = [] }
    finally { scanHistoryLoading.value = false }
  }

  async function fetchScanTrace(scanId: string) {
    scanTraceDetail.value = null
    scanTraceFilter.value = 'passed'
    try {
      const dataMode = scanTraceDebugMode.value ? 'debug' : 'production'
      const r = await api.get(`${scannerApi}/scan-traces/${scanId}?status=passed&limit=50&mode=${dataMode}`, { timeout: 10000 })
      const p = parseResponse(r)
      if (p.success) scanTraceDetail.value = p.data
    } catch { /* ignore */ }
  }

  // 切换候选过滤模式
  async function switchScanTraceFilter(filter: 'passed' | 'bought' | 'rejected' | 'summary') {
    if (!scanTraceDetail.value) return
    const scanId = scanTraceDetail.value.scan_id
    if (!scanId) return
    scanTraceFilter.value = filter
    scanTraceLoadingMore.value = true
    try {
      const dataMode = scanTraceDebugMode.value ? 'debug' : 'production'
      const r = await api.get(`${scannerApi}/scan-traces/${scanId}?status=${filter}&limit=50&mode=${dataMode}`, { timeout: 10000 })
      const p = parseResponse(r)
      if (p.success) {
        scanTraceDetail.value = { ...scanTraceDetail.value, candidates: p.data.candidates || [], _pagination: p.data._pagination, rejected_layer_stats: p.data.rejected_layer_stats }
      }
    } catch { /* ignore */ }
    finally { scanTraceLoadingMore.value = false }
  }

  function openScanTrace(scanId: string | number) {
    fetchScanTrace(String(scanId))
    signalTraceVisible.value = true
  }

  function openLayerDebug(sig: any) {
    layerDebugData.value = sig
    layerDebugVisible.value = true
  }

  // ==================== 工具方法 ====================
  function rejectionReasonCN(reason: string) {
    const map: Record<string, string> = {
      'force_empty': '强制空仓期',
      'special_period': '特殊时期限制',
      'sentiment_blocked': '情绪周期不允许',
      'not_in_premarket': '未在盘前预选',
      'auction_filter': '竞价过滤',
      'strategy_score_low': '策略评分不足',
      'ranking_too_low': '综合排名太低',
      'position_full': '仓位已满',
      'insufficient_cash': '资金不足',
      'already_held': '已持有',
      'limit_up_unbuyable': '涨停不可买',
      'duplicate_signal': '重复信号',
    }
    return map[reason] || reason
  }

  const rejectionLayerCNMap: Record<string, string> = {
    L1_force_empty: '强制空仓', L2_special_period: '特殊时期', L3_sentiment: '情绪周期',
    L4_premarket: '盘前预选', L5_auction: '竞价过滤', L6_strategy: '策略量能',
    L7_ranking: '综合排序', L8_position: '仓位控制', L9_execute: '执行确认',
  }
  // 兼容模板函数调用: rejectionLayerCN('L1_force_empty')
  function rejectionLayerCN(key: string): string {
    return rejectionLayerCNMap[key] || key
  }

  const layerLabel = (k: string) => {
    const label = pipelineLabels[k]
    if (!label) return k
    const prefix = k.split('_')[0]
    return prefix + ' ' + label
  }

  const layerDesc = (layer: string, data: any): string => {
    const descs: Record<string, (d: any) => string> = {
      // 【v2.9.95c】优先看 passed/rejected 数字而不是 applied，因为很多层根本没 applied 字段
      L1_force_empty: (d) => d === true || d?.applied ? '✅ 未触发空仓(涨停多/跌停少)' : '⛔ 触发强制空仓',
      L2_special_period: (d) => d === true || d?.applied ? '✅ 非特殊时期,仓位系数100%' : '⚠️ 特殊时期,降低仓位',
      L3_sentiment: (d) => typeof d === 'string' ? d : d?.applied ? `✅ 情绪筛选通过` : '⛔ 情绪不达标',
      L4_premarket: (d) => typeof d === 'string' ? d : (Number(d?.rejected||0) === 0 && Number(d?.output||0) > 0) ? `✅ 盘前预选通过 入${d.input}出${d.output}` : (Number(d?.rejected||0) > 0 ? `🔍 盘前过滤 入${d.input}出${d.output}(剔除${d.rejected}只)` : '⛔ 盘前预选未通过'),
      L5_auction: (d) => typeof d === 'string' ? d : (Number(d?.rejected||0) === 0 && Number(d?.output||0) > 0) ? `✅ 竞价过滤通过 入${d.input}出${d.output}` : (Number(d?.rejected||0) > 0 ? `🔍 竞价过滤 入${d.input}出${d.output}(剔除${d.rejected}只)` : '⛔ 竞价异常排除'),
      L6_strategy: (d) => typeof d === 'string' ? d : (Number(d?.rejected||0) === 0 && Number(d?.output||0) > 0) ? `✅ 策略量能达标 入${d.input}出${d.output}` : (Number(d?.rejected||0) > 0 ? `🔍 策略筛选 入${d.input}出${d.output}(剔除${d.rejected}只)` : '⛔ 不满足策略条件'),
      L7_ranking: (d) => typeof d === 'string' ? d : (Number(d?.rejected||0) === 0 && Number(d?.output||0) > 0) ? `✅ 排名靠前入选 入${d.input}出${d.output}` : (Number(d?.rejected||0) > 0 ? `🔍 综合排序 入${d.input}出${d.output}(剔除${d.rejected}只)` : '⛔ 排名靠后淘汰'),
      L8_position: (d) => typeof d === 'string' ? d : (Number(d?.rejected||0) === 0 && Number(d?.output||0) > 0) ? `✅ 仓位允许开仓 入${d.input}出${d.output}` : (Number(d?.rejected||0) > 0 ? `⚠️ 仓位限制 入${d.input}出${d.output}(剔除${d.rejected}只)` : '⛔ 仓位已满/超限'),
      // 【v2.9.95c修复】L9 是"输出层"——通过的就是本轮可执行信号数, 不是"被拒"
      L9_execute: (d) => {
        if (typeof d === 'string') return d
        if (!d || typeof d !== 'object') return ''
        const i = Number(d.input || 0)
        const o = Number(d.output || d.passed || 0)
        const r = Number(d.rejected || 0)
        if (i === 0) return '⏭️ 本轮无候选进入执行层'
        if (r > 0) return `⚠️ 有${r}个信号被拒绝(可能因已满仓/风控熔断/额度不足) 入${i}出${o}`
        return `✅ 本轮生成${o}个可买信号进入执行(实际成交还要看候选追踪栏的执行状态)`
      },
    }
    const fn = descs[layer]
    if (fn) try { return fn(data) } catch { /* fallback */ }
    if (typeof data === 'string') return data
    if (data?.detail) return data.detail
    if (data?.reason) return data.reason
    if (data?.applied !== undefined) return data.applied ? '✅ 通过' : '⛔ 未通过'
    return ''
  }

  function formatLayerTrace(trace: Record<string, any>): string[] {
    if (!trace) return ['无链路数据']
    const lines: string[] = []
    for (const [layer, info] of Object.entries(trace)) {
      if (typeof info === 'object' && info !== null) {
        const applied = info.applied !== undefined ? (info.applied ? '✅' : '⏭️') : ''
        const detail = info.detail || info.reason || ''
        lines.push(`${applied} ${layerLabel(layer)}: ${detail}`)
      } else {
        lines.push(`${layerLabel(layer)}: ${info}`)
      }
    }
    return lines
  }

  function formatDecisionDetail(detail: Record<string, any>): string[] {
    if (!detail) return []
    const lines: string[] = []
    if (detail.signal_reason) lines.push(`📋 选股原因: ${detail.signal_reason}`)
    if (detail.filter_pipeline) {
      const fp = detail.filter_pipeline
      lines.push('【9层筛选管道】')
      for (const [l, a] of Object.entries(fp.layers_applied || {})) {
        lines.push(`  ${a ? '✅' : '⏭️'} ${layerLabel(l)}: ${fp.layer_details?.[l] || (a ? '生效' : '跳过')}`)
      }
      lines.push(`  最终仓位系数: ${fp.position_ratio ? ((Number(fp.position_ratio) || 0) * 100).toFixed(0) + '%' : '未知'}`)
    }
    if (detail.execution) {
      const ex = detail.execution
      lines.push('【执行决策】')
      if (ex.position_ratio) lines.push(`  仓位比例: ${((Number(ex.position_ratio) || 0) * 100).toFixed(0)}%`)
      if (ex.available_cash) lines.push(`  可用资金: ¥${Number(ex.available_cash || 0).toFixed(0)}`)
      if (ex.max_amount) lines.push(`  最大买入: ¥${Number(ex.max_amount || 0).toFixed(0)}`)
      if (ex.shares) lines.push(`  买入股数: ${ex.shares}股`)
      if (ex.total_cost) lines.push(`  成本: ¥${Number(ex.total_cost || 0).toFixed(0)}`)
      if (ex.filled_price) lines.push(`  成交价: ¥${Number(ex.filled_price || 0).toFixed(2)}`)
    }
    if (detail.factors) {
      lines.push('【关键因子】')
      for (const [k, v] of Object.entries(detail.factors)) {
        if (v !== 0 && v !== null) lines.push(`  ${k}: ${typeof v === 'number' && isFinite(v) ? v.toFixed(2) : v}`)
      }
    }
    if (detail.sell_reason) {
      lines.push('【卖出决策】')
      lines.push(`  原因: ${detail.sell_reason}`)
      if (detail.profit_pct) lines.push(`  盈亏: ${Number(detail.profit_pct ?? 0).toFixed(2)}%`)
    }
    return lines
  }

  // 信号状态标签
  function signalStatusTag(status?: string): { type: string; text: string } {
    const map: Record<string, { type: string; text: string }> = {
      pending: { type: 'warning', text: '待执行' },
      executed: { type: 'success', text: '已执行' },
      expired: { type: 'info', text: '已过期' },
      rejected: { type: 'danger', text: '已拒绝' },
    }
    return map[status || ''] || { type: 'info', text: status || '未知' }
  }

  // 兼容模板旧名
  const scanTraceVisible = computed({
    get: () => signalTraceVisible.value,
    set: (v: boolean) => { signalTraceVisible.value = v },
  })
  const scanTraceData = computed(() => scanTraceDetail.value)
  const scanTraceCode = computed(() => scanTraceDetail.value?.ts_code || '')

  function scanDateCellClass(date: Date) {
    const y = date.getFullYear()
    const m = String(date.getMonth() + 1).padStart(2, '0')
    const d = String(date.getDate()).padStart(2, '0')
    const key = `${y}${m}${d}`
    // scan-dates API returns date as string(YYYYMMDD), but guard against int
    const item = scanTraceHasData.value.find((x: any) => String(x.date) === key)
    if (!item) return ''
    return item.is_debug ? 'has-scan-debug' : 'has-scan-data'
  }

  return {
    // 状态
    scanTraceDates, scanTraceList, scanTraceDetail, signalTraceVisible,
    scanTraceDate, scanTraceFilter, scanTraceLoadingMore,
    selectedScanIdx, scanHistory, scanHistoryByHour, scanHistoryLoading,
    scanHourCollapse, scanTraceDebugMode, scanTraceHasData,
    executionSummary,
    layerDebugVisible, layerDebugData, layerDebugLoading,
    // 兼容
    scanTraceVisible, scanTraceData, scanTraceCode,
    // 方法
    fetchScanTraceDates, fetchScanHistory, fetchScanTrace,
    openScanTrace, openLayerDebug, toggleScanHour,
    rejectionReasonCN, rejectionLayerCN, layerLabel, layerDesc,
    formatLayerTrace, formatDecisionDetail, signalStatusTag,
    switchScanTraceFilter, scanDateCellClass,
  }
}
