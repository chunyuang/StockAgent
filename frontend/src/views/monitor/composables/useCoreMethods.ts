/**
 * useCoreMethods - 核心方法 (fetch/start/stop/trade/控制)
 *
 * 从useScannerMonitor拆出的核心方法域
 * 管理: fetchScanner/startScanner/stopScanner/quickBuy/quickSell/...
 * 依赖: 核心状态ref + api + scannerStore
 */

import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '@/api/client'
import { useScannerStore } from '@/stores/scanner'
import { useWebSocket } from '@/hooks/useWebSocket'
import { getChinaHour, getChinaMinute } from '@/utils/chinaDate'
import { parseResponse, signalRemaining as _signalRemaining } from '@/utils/scanner'

const scannerApi = '/scanner'
const configApi = '/strategy-config'

interface CoreRefs {
  loading: Ref<boolean>
  autoRefresh: Ref<boolean>
  soundEnabled: Ref<boolean>
  status: Ref<any>
  signals: Ref<any[]>
  positions: Ref<any[]>
  timeline: Ref<any[]>
  orders: Ref<any[]>
  todayClosedTrades: Ref<any[]>
  nowMs: Ref<number>
  signalFilter: Ref<string>
  focusIndex: Ref<number>
  tradeMode: Ref<string>
  replayDate: Ref<string>
  activeTab: Ref<string>
  limitPools: Ref<any>
  strategies: Ref<any[]>
  globalRisk: Ref<any>
  healthData: Ref<any>
  confirmVisible: Ref<boolean>
  confirmLoading: Ref<boolean>
  confirmData: any
  manualTrade: any
  manualQuote: Ref<any>
  riskBarCollapsed: Ref<boolean>
  trailEditPct: Ref<number>
  trailSaving: Ref<boolean>
  emergencyLiquidating: Ref<boolean>
  dataSources: Ref<any[]>
  brokers: Ref<any[]>
  dailyReport: Ref<any>
  stratCollapsed: Ref<Record<string, boolean>>
  stratSectionCollapsed: Ref<boolean>
  qaSectionCollapsed: Ref<boolean>
  timelineCollapsed: Ref<boolean>
  editDialogVisible: Ref<boolean>
  editTab: Ref<string>
  editParams: Ref<any>
  editRiskParams: Ref<any>
  editingStrategy: Ref<any>
  saving: Ref<boolean>
}

import type { Ref } from 'vue'

export function useCoreMethods(refs: CoreRefs) {
  const scannerStore = useScannerStore()
  const wsHook = useWebSocket()

  // 【v2.9.72】WS数据新鲜度追踪:WS连接成功但Redis断开时,scanner数据不会流过WS
  // 此时ws.isConnected=true但实际无数据,需要降级到轮询
  const lastWsDataTime = ref(0) // 上次从WS收到scanner数据的时间
  const WS_DATA_STALE_MS = 15000 // 15秒无WS数据则视为陈旧
  let _wsUnsubFn: (() => void) | null = null // WS订阅取消函数
  const wsDataStale = computed(() => {
    if (!wsHook.isConnected.value) return false // WS断开时不叫“陈旧”，正常走轮询
    if (lastWsDataTime.value === 0) return true // WS连接但从未收到scanner数据
    // 【v2.9.82修复】用nowMs(每秒更新)而非Date.now()(非响应式)
    // 之前Date.now()不触发computed重算, 导致WS断流15秒后wsDataStale仍为false
    return (refs.nowMs.value - lastWsDataTime.value) > WS_DATA_STALE_MS
  })

  let fetchScannerAbort: AbortController | null = null
  let fetchScannerRunning = false
  let _wsSubscribed = false
  let refreshTimer: any = null
  let nowTimer: any = null
  let _unwatchWs: (() => void) | null = null

  // computed
  const isRunning = computed(() => refs.status.value?.is_running ?? false)
  const accountInfo = computed(() => refs.status.value?.account ?? { total_assets: 0, available_cash: 0, market_value: 0, total_profit: 0 })
  const totalPnl = computed(() => accountInfo.value.total_profit ?? 0)
  const circuitBreakerPaused = computed(() => refs.status.value?.circuit_breaker?.trading_paused ?? false)
  const dryRun = computed(() => refs.tradeMode.value === 'dry_run' || (refs.status.value?.dry_run ?? false))

  function playSignalSound() {
    if (!refs.soundEnabled.value) return
    try {
      const ctx = new AudioContext()
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.connect(gain)
      gain.connect(ctx.destination)
      osc.frequency.value = 880
      osc.type = 'sine'
      gain.gain.setValueAtTime(0.3, ctx.currentTime)
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.3)
      osc.start(ctx.currentTime)
      osc.stop(ctx.currentTime + 0.3)
    } catch (e) { console.error('[useCoreMethods]', e) }
  }

  function showConfirm(title: string, message: string, onConfirm: () => void) {
    refs.confirmData.title = title; refs.confirmData.message = message; refs.confirmData.onConfirm = onConfirm; refs.confirmVisible.value = true
  }

  async function handleConfirm() {
    if (refs.confirmLoading.value) return
    refs.confirmLoading.value = true
    try { await refs.confirmData.onConfirm() } finally { refs.confirmLoading.value = false; refs.confirmVisible.value = false }
  }

  async function fetchScanner(date?: string) {
    if (fetchScannerRunning) return; fetchScannerRunning = true
    try {
      if (fetchScannerAbort) fetchScannerAbort.abort(); fetchScannerAbort = new AbortController()
      const url = date ? `${scannerApi}/all?date=${date.replace(/-/g, '')}` : `${scannerApi}/all`
      const r = await api.get(url, { signal: fetchScannerAbort.signal })
      const p = parseResponse(r)
      if (p.success) {
        const d = p.data
        if (d.signals && refs.signals.value.length > 0 && d.signals.length > refs.signals.value.length) { playSignalSound() }
        if (d.status) refs.status.value = d.status
        if (d.signals) refs.signals.value = d.signals
        // 【v2.9.87修复】positions可能是数字(持仓数量)或数组(持仓详情)，只有数组才更新
        if (d.positions && Array.isArray(d.positions)) refs.positions.value = d.positions
        if (d.timeline) refs.timeline.value = d.timeline
        if (d.orders) refs.orders.value = d.orders
        // 【v2.9.99-r4】同步今日已平仓 (后端 v19 恢复字段)
        if (d.today_closed_trades && Array.isArray(d.today_closed_trades)) {
          refs.todayClosedTrades.value = d.today_closed_trades
        }
      }
      fetchLimitPools()
    } catch (e: any) { if (e.name !== 'CanceledError' && e.name !== 'AbortError') console.error(e) }
    finally { fetchScannerRunning = false }
  }

  async function startScanner() {
    const payload: Record<string, any> = { account_id: 'default', trade_mode: refs.tradeMode.value }
    if (refs.tradeMode.value === 'replay') {
      if (!refs.replayDate.value) { ElMessage.warning('请先选择回放日期'); return }
      payload.replay_date = refs.replayDate.value
    }
    refs.loading.value = true
    try {
      const res: any = await api.post(`${scannerApi}/start`, payload)
      if (res?.success === false) {
        ElMessage.warning(res?.data?.message || res?.message || '启动被拒绝')
      } else {
        ElMessage.success('扫描器已启动')
        refs.activeTab.value = 'trading'
        await new Promise(r => setTimeout(r, 1500))
        await fetchScanner()
      }
    } catch (e: any) {
      ElMessage.error('启动失败: ' + (e?.response?.data?.detail || e?.message || '超时'))
    } finally {
      refs.loading.value = false
    }
  }

  async function stopScanner() { showConfirm('停止扫描', '确认停止扫描器?\n持仓将保留,可手动卖出。', async () => { const res: any = await api.post(`${scannerApi}/stop`, { sell_all: false }); if (res?.success === false) { ElMessage.warning(res?.data?.message || '停止失败') } else { await fetchScanner() } }) }

  async function manualScan() {
    refs.loading.value = true
    try {
      const payload: Record<string, any> = {}
      if (refs.tradeMode.value === 'replay' && refs.replayDate.value) payload.replay_date = refs.replayDate.value
      const r = await api.post(`${scannerApi}/scan-once`, payload)
      const p = parseResponse(r)
      if (p.success) { const m = p.data?.message; if (m) ElMessage.warning(m); else ElMessage.success(`扫描完成: ${p.data?.signals || 0}信号, ${p.data?.positions || 0}持仓`) }
      else ElMessage.error('扫描失败')
    } catch (e: any) { ElMessage.error('扫描失败') }
    finally { refs.loading.value = false; await fetchScanner() }
  }

  async function forceScan() {
    refs.loading.value = true
    try {
      const payload: Record<string, any> = { force: true }
      if (refs.tradeMode.value === 'replay' && refs.replayDate.value) payload.replay_date = refs.replayDate.value
      const r = await api.post(`${scannerApi}/scan-once`, payload)
      const p = parseResponse(r)
      if (p.success) { ElMessage.success(`强制扫描完成: ${p.data?.signals || 0}信号, ${p.data?.positions || 0}持仓`) }
      else ElMessage.error('强制扫描失败')
    } catch (e: any) { ElMessage.error('强制扫描失败') }
    finally { refs.loading.value = false; await fetchScanner() }
  }

  async function quickBuy(sig: any) {
    const a = refs.status.value?.account; if (!a) { ElMessage.warning('请先启动'); return }
    const price = sig.price || 0
    if (price <= 0) { ElMessage.warning('价格无效'); return }
    const q = Math.floor(a.available_cash * 0.25 / price / 100) * 100
    if (q <= 0) { ElMessage.warning('资金不足'); return }
    showConfirm('确认买入', `${sig.stock_name} ${sig.ts_code}\n${sig.strategy_name} | 涨${(sig.pct_chg || 0) >= 0 ? '+' : ''}${(sig.pct_chg || 0).toFixed(1)}%\n买入 ${q}股 × ¥${price.toFixed(2)} ≈ ¥${(q * price).toFixed(0)}`, async () => {
      try {
        const r = await api.post(`${scannerApi}/trade`, { ts_code: sig.ts_code, stock_name: sig.stock_name, side: 'buy', quantity: q, price: sig.price, order_type: 'market', strategy: sig.strategy, reason: sig.reason })
        const p = parseResponse(r); if (p.success) { ElMessage.success(`买入${sig.stock_name} ${q}股@${p.data.filled_price?.toFixed(2) ?? '市价'}`); fetchScanner() } else ElMessage.error('失败')
      } catch (e: any) { ElMessage.error('买入失败') }
    })
  }

  async function quickSell(pos: any) {
    const sellQty = pos.available_qty || pos.total_qty || pos.shares || 0
    if (sellQty <= 0) { ElMessage.warning('T+1限制或无可用持仓'); return }
    showConfirm('确认卖出', `${pos.stock_name} ${pos.ts_code}\n${(pos.profit_pct || 0) >= 0 ? '+' : ''}${(pos.profit_pct || 0).toFixed(1)}% | 卖出 ${sellQty}股\n成本 ¥${(pos.cost_price || 0).toFixed(2)} → 现价 ¥${(pos.current_price || 0).toFixed(2)} ≈ ¥${(sellQty * (pos.current_price || 0)).toFixed(0)}`, async () => {
      try {
        const r = await api.post(`${scannerApi}/trade`, { ts_code: pos.ts_code, stock_name: pos.stock_name, side: 'sell', quantity: sellQty, price: pos.current_price, order_type: 'market', strategy: pos.strategy, reason: `手动卖出 ${(pos.profit_pct || 0) >= 0 ? '+' : ''}${(pos.profit_pct || 0).toFixed(1)}%` })
        const p = parseResponse(r); if (p.success) { ElMessage.success(`卖出${pos.stock_name} ${sellQty}股@${p.data.filled_price?.toFixed(2) ?? '市价'}`); fetchScanner() } else ElMessage.error('失败')
      } catch (e: any) { ElMessage.error('卖出失败') }
    })
  }

  async function dailySettlement() { try { const r = await api.post(`${scannerApi}/daily-settlement`); const p = parseResponse(r); if (p.success) { ElMessage.success(p.data?.message || '日结算完成'); await fetchScanner() } } catch (e: any) { ElMessage.error('日结算失败') } }

  async function resetAccount() { showConfirm('⚠️ 重置账户', '将清空所有持仓和交易记录,不可恢复!\n确认重置?', async () => { try { const r = await api.post(`${scannerApi}/reset`); const p = parseResponse(r); if (p.success) { ElMessage.success('账户已重置'); await fetchAll(true) } } catch (e: any) { ElMessage.error('重置失败') } }) }

  async function sellAllPositions() { showConfirm('⚠️ 一键清仓', `确认清仓所有持仓?\n当前持仓 ${refs.positions.value.length} 只,总市值 ¥${refs.positions.value.reduce((s: number, p: any) => s + (Number(p.market_value) || (Number(p.current_price) || 0) * (Number(p.shares) || 0)), 0).toFixed(0)}`, async () => { try { const r = await api.post(`${scannerApi}/sell-all`); const p = parseResponse(r); if (p.success) { ElMessage.success(p.data?.message || '清仓完成'); await fetchAll(true) } } catch (e: any) { ElMessage.error('清仓失败') } }) }

  async function resetCircuitBreaker() { try { const r = await api.post(`${scannerApi}/circuit-breaker/reset`); const p = parseResponse(r); if (p.success) { ElMessage.success('熔断已重置'); fetchAll(true) } } catch (e) { console.error('[core] resetCircuitBreaker failed:', e); ElMessage.error('重置失败') } }

  async function pauseCircuitBreaker() {
    try {
      await ElMessageBox.confirm('确认暂停交易?\n暂停后不会自动买入新信号,但持仓止损止盈仍正常执行。', '暂停交易', { confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning' })
      const r = await api.post(`${scannerApi}/circuit-breaker/pause`)
      const p = parseResponse(r); if (p.success) { ElMessage.success('已暂停'); fetchAll(true) } else ElMessage.error('操作失败')
    } catch (e) { console.error('[useCoreMethods]', e) }
  }

  async function emergencyLiquidate() { showConfirm('🚨 紧急平仓', '将立即以市价卖出所有持仓!\n此操作不可撤销!\n\n确认紧急平仓?', async () => { refs.emergencyLiquidating.value = true; try { const r = await api.post(`${scannerApi}/emergency-liquidate`); const p = parseResponse(r); if (p.success) { ElMessage.success(p.data?.message || '紧急平仓完成'); await fetchAll(true) } else ElMessage.error('平仓失败') } catch (e) { console.error('[emergencyLiquidate] failed:', e); ElMessage.error('紧急平仓失败') } finally { refs.emergencyLiquidating.value = false } }) }

  async function fetchLimitPools() { try { const r = await api.get(`${scannerApi}/limit-pools`); const p = parseResponse(r); if (p.success) refs.limitPools.value = p.data } catch (e) { console.error('[useCoreMethods]', e) } }
  async function fetchDataSources() { try { const [sR, bR] = await Promise.all([api.get('/datasource/sources'), api.get('/datasource/brokers')]); const sP = parseResponse(sR), bP = parseResponse(bR); if (sP.success) refs.dataSources.value = sP.data || []; if (bP.success) refs.brokers.value = bP.data || [] } catch (e) { console.error('[useCoreMethods]', e) } }
  async function fetchHealth() { try { const r = await api.get(`${scannerApi}/health`); const p = parseResponse(r); if (p.success) { refs.healthData.value = p.data; scannerStore.health = p.data; } } catch (e) { console.error('[useCoreMethods]', e) } }
  async function fetchStrategies() { try { const [sR, rR] = await Promise.all([api.get(`${configApi}/strategies`), api.get(`${configApi}/global-risk`)]); const sP = parseResponse(sR), rP = parseResponse(rR); if (sP.success) refs.strategies.value = sP.data; if (rP.success) refs.globalRisk.value = rP.data } catch (e) { console.error(e) } }

  async function fetchAll(_force = false) { await Promise.all([fetchScanner(), fetchStrategies(), fetchHealth()]); fetchLimitPools(); fetchDataSources() }

  // 生命周期方法 (由父组件在onMounted/onUnmounted中调用)
  function mount() {
    wsHook.connect()
    if (!_wsSubscribed) {
      wsHook.subscribeScanner()
      _wsSubscribed = true
    }
    // 【v2.9.72】监听WS scanner数据到达,更新新鲜度时间戳
    _wsUnsubFn = wsHook.subscribe((msg: any) => {
      if (msg.type?.startsWith('scanner_')) {
        lastWsDataTime.value = Date.now()
      }
    })
    // 【v2.9.75】WS重连后主动fetch恢复数据
    _unwatchWs = watch(() => wsHook.isConnected.value, (connected: boolean, prev: boolean) => {
      if (connected && !prev) {
        // WS从断开恢复到连接 → 主动fetch一次全量数据恢复
        if (__DEV__) console.log('[WS] 重连成功, 主动fetch恢复数据')
        fetchScanner()
        fetchHealth()
        // 重新订阅scanner频道(携带last_stream_id断线补发)
        if (_wsSubscribed) {
          wsHook.subscribeScanner()
        }
      }
    })
    nowTimer = setInterval(() => { refs.nowMs.value = Date.now() }, 1000)
    const getRefreshInterval = () => { const h = getChinaHour(), m = getChinaMinute(); const isTrading = (h === 9 && m >= 30) || (h >= 10 && h < 15) || (h === 15 && m === 0); return isTrading ? 5000 : 60000 }
    // 【v2.9.72】修复:WS连接但Redis断开时数据不更新的bug
    // 当wsDataStale=true(WS连接但无scanner数据)时,仍执行轮询作为降级
    refreshTimer = setInterval(() => { if (!refs.autoRefresh.value) return; if (wsHook.isConnected.value && !wsDataStale.value) return; fetchScanner(); fetchHealth() }, getRefreshInterval())
  }

  function unmount() {
    if (refreshTimer) clearInterval(refreshTimer)
    if (nowTimer) clearInterval(nowTimer)
    // 【v2.9.98修复】unmount时退订scanner WS频道,避免离屏后仍收到WS推送
    if (_wsSubscribed) {
      wsHook.unsubscribeScanner()
      _wsSubscribed = false
    }
    if (_wsUnsubFn) { _wsUnsubFn(); _wsUnsubFn = null }
    if (_unwatchWs) { _unwatchWs(); _unwatchWs = null }
    // 重置WS数据新鲜度时间戳, 避免下次mount时wsDataStale判断错误
    lastWsDataTime.value = 0
  }

  // 【v2.9.72】Store同步 - 修复:空数组也必须同步(如0个signal时不更新导致UI不一致)
  function setupStoreWatchers(watch: any) {
    watch(() => scannerStore.signals, (v: any) => { if (v != null) refs.signals.value = v }, { deep: true })
    watch(() => scannerStore.positions, (v: any) => { if (v != null) refs.positions.value = v }, { deep: true })
    watch(() => scannerStore.timeline, (v: any) => { if (v != null) refs.timeline.value = v }, { deep: true })
    watch(() => scannerStore.status, (v: any) => { if (v) refs.status.value = { ...(refs.status.value || {}), ...v } }, { deep: true })
    watch(() => scannerStore.lastError, (v: string) => { if (v) ElMessage({ type: 'error', message: `Scanner异常: ${v}`, duration: 8000 }) })
  }

  return {
    isRunning, accountInfo, totalPnl, circuitBreakerPaused, dryRun,
    // 【v2.9.71: 暴露WS连接状态给UI】
    wsStatus: wsHook.status,
    wsIsConnected: wsHook.isConnected,
    wsRetryCount: wsHook.retryCount,
    // 【v2.9.75: 暴露WS数据新鲜度给UI】
    wsDataStale,
    playSignalSound, showConfirm, handleConfirm,
    fetchScanner, startScanner, stopScanner, manualScan, forceScan,
    quickBuy, quickSell, dailySettlement, resetAccount, sellAllPositions,
    resetCircuitBreaker, pauseCircuitBreaker, emergencyLiquidate,
    fetchLimitPools, fetchDataSources, fetchHealth, fetchStrategies, fetchAll,
    mount, unmount, setupStoreWatchers,
  }
}
