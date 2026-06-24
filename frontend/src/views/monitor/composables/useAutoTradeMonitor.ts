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

function todayStr(): string {
  const d = new Date()
  return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}`
}

// 接收核心状态的接口
interface CoreState {
  totalPnl: { value: number }
  pnlHistory: { value: { time: string; value: number }[] }
  perfData: { value: Array<{ time: string; net_value: number; drawdown: number }> }
}

export function useAutoTradeMonitor(core: CoreState) {
  const autoTrades = ref<any[]>([])
  const opsDate = ref(getChinaDate())
  const paramCompare = ref<any>(null)
  const paramCompareLoading = ref(false)
  const scanConfig = ref<any>(null)
  const scanConfigLoading = ref(false)

  /** 获取最近交易日的日期字符串 YYYY-MM-DD */
  function getChinaDate(): string {
    const now = new Date()
    const china = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Shanghai' }))
    const y = china.getFullYear(), m = String(china.getMonth() + 1).padStart(2, '0'), d = String(china.getDate()).padStart(2, '0')
    // 周六→回退到周五, 周日→回退到周五
    const dow = china.getDay()
    if (dow === 6) return `${y}-${m}-${String(china.getDate() - 1).padStart(2, '0')}`
    if (dow === 0) return `${y}-${m}-${String(china.getDate() - 2).padStart(2, '0')}`
    return `${y}-${m}-${d}`
  }

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
      // fallback: from unified trades (v2.9.97)
      const ut = await api.get(`/unified/trades?date=${todayStr()}`)
      const up = parseResponse(ut)
      if (up.success && up.data?.trades?.length > 0) {
        let nav = 1.0, peak = 1.0
        core.perfData.value = up.data.trades.filter((t: any) => t.side === 'sell').map((item: any) => {
          const profitAmount = item.profit_amount || 0
          nav *= (1 + profitAmount / (1000000 * nav))
          peak = Math.max(peak, nav)
          const dd = nav < peak ? (nav / peak - 1) * 100 : 0
          return { time: (item.time || '').substring(0, 16), net_value: nav, drawdown: dd }
        })
      }
    } catch (e) { console.error('[useAutoTradeMonitor]', e) }
  }

  // 【v2.9.97】切换到统一数据源 — broker_orders 为唯一真相
  async function fetchAutoTrades() {
    try {
      let url = '/unified/trades?limit=50'
      if (opsDate.value) url += `&date=${opsDate.value.replace(/-/g, '')}`
      if (__DEV__) console.log('[OpsTab] fetchAutoTrades url:', url, 'opsDate:', opsDate.value)
      const r = await api.get(url)
      const p = parseResponse(r)
      if (__DEV__) console.log('[OpsTab] fetchAutoTrades result:', p.success, 'trades count:', p.data?.trades?.length)
      if (p.success) {
        // unified/trades 返回 { trades: [...], summary: {...} }
        autoTrades.value = (p.data?.trades || []).map((t: any) => ({
          time: t.time || t.fill_time,
          ts_code: t.ts_code,
          stock_name: t.stock_name,
          side: t.side,
          quantity: t.quantity,
          price: t.price,
          amount: t.amount,
          strategy: t.strategy,
          reason: t.reason,
          source: t.source || 'auto',
          trade_date: t.trade_date,
          order_id: t.order_id,
          profit_pct: t.profit_pct,
          profit_amount: t.profit_amount,
          decision_trace: t.decision_trace || {},
        }))
      }
    } catch (e) { console.error('[OpsTab] fetchAutoTrades error:', e) }
  }

  async function fetchParamCompare() {
    paramCompareLoading.value = true
    try {
      const r = await api.get(`${scannerApi}/strategy-params-compare`)
      const p = parseResponse(r)
      if (p.success) paramCompare.value = p.data
    } catch (e) { console.error('[useAutoTradeMonitor]', e) }
    finally { paramCompareLoading.value = false }
  }

  async function fetchScanConfig() {
    scanConfigLoading.value = true
    try {
      const r = await api.get(`${scannerApi}/scan-config`)
      const p = parseResponse(r)
      if (__DEV__) console.log('[OpsTab] fetchScanConfig result:', p.success, 'data:', !!p.data)
      if (p.success) scanConfig.value = p.data
    } catch (e) { console.error('[OpsTab] fetchScanConfig error:', e) }
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
