/**
 * useAutoTradeMonitor - 自动交易+参数对比管理
 * 
 * 从useScannerMonitor拆出的自动交易功能域
 * 管理: autoTrades/paramCompare/scanConfig/perfData/pnlChart
 */

import { ref, computed } from 'vue'
import { api } from '@/api/client'
import { parseResponse } from '@/utils/scanner'

const scannerApi = '/scanner'

// 接收核心状态的接口
interface CoreState {
  totalPnl: { value: number }
  pnlHistory: { value: { time: string; value: number }[] }
  perfData: { value: Array<{ time: string; net_value: number; drawdown: number }> }
}

export function useAutoTradeMonitor(core: CoreState) {
  const autoTrades = ref<any[]>([])
  const opsDate = ref('')
  const paramCompare = ref<any>(null)
  const paramCompareLoading = ref(false)
  const scanConfig = ref<any>(null)
  const scanConfigLoading = ref(false)

  function updatePnlHistory() {
    const pnl = core.totalPnl.value
    if (pnl === 0 && core.pnlHistory.value.length === 0) return
    core.pnlHistory.value.push({ time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }), value: pnl })
    if (core.pnlHistory.value.length > 60) core.pnlHistory.value = core.pnlHistory.value.slice(-60)
  }

  async function fetchPerformanceHistory() {
    try {
      const r = await api.get(`${scannerApi}/performance-history?days=30`)
      const p = parseResponse(r)
      if (p.success && p.data?.length > 0) {
        core.perfData.value = p.data.map((s: any) => ({ time: (s.timestamp || s.date || '').substring(5, 16), net_value: s.net_value || s.total_assets / 1000000, drawdown: s.drawdown_pct || 0 }))
        return
      }
      // fallback: from timeline
      const tl = await api.get(`${scannerApi}/timeline/history?days=30`)
      const tp = parseResponse(tl)
      if (tp.success && tp.data?.length > 0) {
        let nav = 1.0, peak = 1.0
        core.perfData.value = tp.data.map((item: any) => {
          const profitAmount = item.profit_amount || 0
          nav *= (1 + profitAmount / (1000000 * nav))
          peak = Math.max(peak, nav)
          const dd = nav < peak ? (nav / peak - 1) * 100 : 0
          return { time: (item.date || item.time || '').substring(0, 16), net_value: nav, drawdown: dd }
        })
      }
    } catch { /* ignore */ }
  }

  async function fetchAutoTrades() {
    try {
      let url = `${scannerApi}/auto-trades?limit=50`
      if (opsDate.value) url += `&date=${opsDate.value.replace(/-/g, '')}`
      const r = await api.get(url)
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
    const source = core.perfData.value.length > 0 ? core.perfData.value : core.pnlHistory.value.map(p => ({ time: p.time, net_value: p.value / 1000000 + 1, drawdown: 0 }))
    return {
      grid: { top: 10, right: 10, bottom: 20, left: 50 },
      tooltip: { trigger: 'axis' as const, formatter: (p: any) => { if (!p?.length) return ''; const v0 = Number(p[0].value ?? 0); let s = `${p[0].axisValue}<br/>净值: ${isFinite(v0) ? v0.toFixed(4) : '-'}`; if (p[1]) { const v1 = Number(p[1].value ?? 0); s += `<br/>回撤: ${isFinite(v1) ? v1.toFixed(2) : '-'}%`; } return s; } },
      xAxis: { type: 'category', data: source.map(p => p.time), axisLabel: { color: 'var(--text-tertiary)', fontSize: 10 } },
      yAxis: [
        { type: 'value', axisLabel: { color: 'var(--text-tertiary)', fontSize: 10 }, splitLine: { lineStyle: { color: 'var(--border-light)' } } },
        { type: 'value', position: 'right', axisLabel: { color: 'var(--stock-up)', fontSize: 9, formatter: '{value}%' }, splitLine: { show: false } },
      ],
      series: [
        { type: 'line', data: source.map(p => p.net_value), smooth: true, lineStyle: { color: 'var(--stock-down)', width: 2 }, areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'var(--stock-down-bg)' }, { offset: 1, color: 'rgba(0,0,0,0)' }] } } },
        ...(core.perfData.value.length > 0 ? [{ type: 'bar' as const, yAxisIndex: 1, data: source.map(p => p.drawdown), itemStyle: { color: 'rgba(103,194,58,0.3)' }, barWidth: 3 }] : []),
      ],
      backgroundColor: 'transparent',
    }
  })

  return {
    autoTrades, opsDate, paramCompare, paramCompareLoading,
    scanConfig, scanConfigLoading,
    pnlOption,
    updatePnlHistory, fetchPerformanceHistory,
    fetchAutoTrades, fetchParamCompare, fetchScanConfig,
  }
}
