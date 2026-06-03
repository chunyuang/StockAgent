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

  // 扫描追踪辅助(后续逐步实现)
  const scanTraceDate = ref('')
  const scanTraceFilter = ref('all')
  const scanTraceLoadingMore = ref(false)
  const selectedScanIdx = ref(-1)
  const scanHistory = ref<any[]>([])
  const scanHistoryByHour = ref<any[]>([])
  const scanHistoryLoading = ref(false)

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
    } catch { /* ignore */ }
  }

  async function fetchScanHistory() {
    try {
      const r = await api.get(`${scannerApi}/scan-traces`)
      const p = parseResponse(r)
      if (p.success) scanTraceList.value = p.data || []
    } catch { /* ignore */ }
  }

  async function fetchScanTrace(scanId: string) {
    try {
      const r = await api.get(`${scannerApi}/scan-traces/${scanId}`)
      const p = parseResponse(r)
      if (p.success) scanTraceDetail.value = p.data
    } catch { /* ignore */ }
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
      'sentiment_blocked': '情绪周期不允许',
      'strategy_score_low': '策略评分不足',
      'position_full': '仓位已满',
      'insufficient_cash': '资金不足',
      'already_held': '已持有',
      'limit_up_unbuyable': '涨停不可买',
      'duplicate_signal': '重复信号',
    }
    return map[reason] || reason
  }

  const layerLabel = (k: string) => {
    const label = pipelineLabels[k]
    if (!label) return k
    const prefix = k.split('_')[0]
    return prefix + ' ' + label
  }

  const layerDesc = (_layer: string, _data: any): string => ''

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
    for (const [k, v] of Object.entries(detail)) {
      lines.push(`${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`)
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

  const scanTraceHasData = ref<any[]>([])  // 有扫描数据的日期列表

  function switchScanTraceFilter(f: string) { scanTraceFilter.value = f }
  function scanDateCellClass(date: Date) {
    const y = date.getFullYear()
    const m = String(date.getMonth() + 1).padStart(2, '0')
    const d = String(date.getDate()).padStart(2, '0')
    const key = `${y}${m}${d}`
    const item = scanTraceHasData.value.find((x: any) => x.date === key)
    if (!item) return ''
    return item.is_debug ? 'has-scan-debug' : 'has-scan-data'
  }
  function rejectionLayerCN(layer: string) { return layer }

  return {
    // 状态
    scanTraceDates, scanTraceList, scanTraceDetail, signalTraceVisible,
    scanTraceDate, scanTraceFilter, scanTraceLoadingMore,
    selectedScanIdx, scanHistory, scanHistoryByHour, scanHistoryLoading,
    layerDebugVisible, layerDebugData, layerDebugLoading,
    scanTraceHasData,
    // 兼容
    scanTraceVisible, scanTraceData, scanTraceCode,
    // 方法
    fetchScanTraceDates, fetchScanHistory, fetchScanTrace,
    openScanTrace, openLayerDebug,
    rejectionReasonCN, layerLabel, layerDesc,
    formatLayerTrace, formatDecisionDetail, signalStatusTag,
    switchScanTraceFilter, scanDateCellClass, rejectionLayerCN,
  }
}
