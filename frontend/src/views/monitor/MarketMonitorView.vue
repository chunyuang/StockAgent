<script setup lang="ts">
/**
 * MarketMonitorView — 超短量化实盘监控 (3列布局)
 * 左: 策略控制+快捷操作 / 中: 信号+行情 / 右: 持仓+统计
 * 底: 时间线 / 顶: 状态栏
 */
import { ref, computed, onMounted, onUnmounted, reactive, watch } from 'vue'
import {
  ElCard, ElButton, ElTag, ElEmpty, ElTable, ElTableColumn,
  ElSwitch, ElInputNumber, ElSlider, ElDescriptions, ElDescriptionsItem,
  ElTabs, ElTabPane, ElDialog, ElMessage, ElTooltip, ElBadge,
  ElInput, ElSelect, ElOption, ElDatePicker,
} from 'element-plus'
import { api } from '@/api/client'

interface ScanStats { scans: number; signals_found: number; trades_executed: number; stop_losses: number; take_profits: number; stocks_scanned: number }
interface ScannerStatus { is_running: boolean; scan_count: number; last_scan_time: string; active_signals: number; positions: number; stocks_scanned: number; stats: ScanStats; account_id: string; trade_mode: string; dry_run?: boolean; circuit_breaker_paused?: boolean; circuit_breaker?: { trading_paused: boolean; pause_reason: string }; account: { total_assets: number; available_cash: number; market_value: number; total_profit: number }; data_sources?: Array<{ name: string; available: boolean; stocks: number; calls: number; limit: number; note: string }> }
interface ScanSignal { ts_code: string; stock_name: string; strategy: string; strategy_name: string; signal_type: string; price: number; pct_chg: number; volume_ratio: number; turnover_rate: number; is_limit_up: boolean; limit_up_count: number; confidence: number; reason: string; scan_time: string; factors: Record<string, number>; key_factors?: Record<string, string>; decision_detail?: Record<string, any>; signal_status?: string; layer_trace?: Record<string, any>; created_at?: number }
interface PositionInfo { ts_code: string; stock_name: string; strategy: string; strategy_name?: string; shares: number; available_qty: number; cost_price: number; current_price: number; profit_pct: number; profit_amount?: number; market_value?: number; today_buy: number; stop_loss_pct?: number; take_profit_pct?: number; stop_loss_price?: number; take_profit_price?: number; distance_to_stop?: number }
interface TimelineItem { time: string; action: string; ts_code: string; stock_name: string; strategy: string; shares: number; price: number; reason: string; profit_pct?: number; profit_amount?: number; decision_detail?: Record<string, any> }
interface StrategyConfig { id: string; name: string; enabled: boolean; params: Record<string, any>; riskParams: Record<string, any>; paramDescriptions: ParamDesc[]; riskDescriptions: ParamDesc[] }
interface ParamDesc { key: string; label: string; value: any; displayValue: string; unit: string; min: number; max: number; step: number }
interface GlobalRisk { stop_loss_pct: number; take_profit_pct: number; max_position_pct: number; max_positions: number }

const loading = ref(false), autoRefresh = ref(true), darkMode = ref(document.documentElement.classList.contains('dark')), soundEnabled = ref(false)
watch(darkMode, (v) => { document.documentElement.classList.toggle('dark', v) })
let refreshTimer: any = null
let ws: WebSocket | null = null
let wsReconnectTimer: any = null
const status = ref<ScannerStatus | null>(null)
const signals = ref<ScanSignal[]>([])
const positions = ref<PositionInfo[]>([])
const timeline = ref<TimelineItem[]>([])
const orders = ref<any[]>([])
const limitPools = ref<{limit_up: any[], limit_down: any[], broken: any[]}>({limit_up: [], limit_down: [], broken: []})
const limitPoolTab = ref('limit_up')
const dailyReport = ref<any>(null)
const strategies = ref<StrategyConfig[]>([])
const globalRisk = ref<GlobalRisk | null>(null)
const editingStrategy = ref<StrategyConfig | null>(null)
const editDialogVisible = ref(false)
const editTab = ref('params')
const editParams = ref<Record<string, any>>({})
const editRiskParams = ref<Record<string, any>>({})
const saving = ref(false)
const scannerApi = '/scanner', configApi = '/strategy-config'
const strategyMeta: Record<string, { color: string; icon: string; desc: string; cn: string }> = {
  halfway_chase: { color: '#e6a23c', icon: '🚀', desc: '盘中冲高2-7%+量能放大', cn: '半路追涨' },
  first_limit_up: { color: '#f56c6c', icon: '🔥', desc: '首板涨停封板强', cn: '首板打板' },
  dragon_head: { color: '#409eff', icon: '🐉', desc: '连板龙头回调低吸', cn: '龙头低吸' },
  limit_down_qiao: { color: '#67c23a', icon: '💪', desc: '跌停撬板反弹', cn: '跌停翘板' },
  limit_up_open: { color: '#909399', icon: '🔓', desc: '涨停炸板回封', cn: '涨停开板' },
  anomaly_surge: { color: '#e6a23c', icon: '⚡', desc: '5分钟急速拉升', cn: '急速拉升' },
  anomaly_broken: { color: '#f56c6c', icon: '💔', desc: '涨停炸板', cn: '涨停炸板' },
  anomaly_strong: { color: '#409eff', icon: '💪', desc: '强势涨停确认', cn: '强势涨停' },
}
const strategyCN = (s: string) => strategyMeta[s]?.cn || s
const factorCN: Record<string, string> = {
  pct_chg: '涨跌幅', volume_ratio: '量比', turnover_rate: '换手率',
  circ_mv: '流通市值', total_mv: '总市值', float_mv: '流通市值',
  ma5: 'MA5', ma10: 'MA10', ma20: 'MA20', ma60: 'MA60',
  rsi_6: 'RSI6', rsi_12: 'RSI12', rsi_24: 'RSI24',
  macd: 'MACD', macd_signal: 'MACD信号', macd_hist: 'MACD柱',
  boll_upper: '布林上轨', boll_lower: '布林下轨', boll_mid: '布林中轨',
  atr: 'ATR', momentum_1d: '1日动量',
  is_limit_up: '涨停', is_limit_down: '跌停',
  limit_up_count: '涨停次数', limit_up_yesterday: '昨日涨停',
  limit_down_yesterday: '昨日跌停', first_limit_up: '首板',
  opening_pct_chg: '竞价涨跌幅', open: '开盘价', high: '最高价',
  low: '最低价', close: '收盘价', pre_close: '前收盘',
  pe: 'PE', pb: 'PB', amplitude: '振幅',
  fear_greed_index: '恐慌贪婪指数',
  limit_up_open_amount: '涨停开板金额', limit_down_open_amount: '跌停开板金额',
  pullback_pct: '回调幅度', pullback_days: '回调天数',
  rise_after_limit_down: '跌停后涨幅',
  open_times: '开板次数', fd_amount: '封板资金', limit_times: '连板数',
}
const factorLabel = (k: string) => factorCN[k] || k
const layerCN: Record<string, string> = {
  L1_force_empty: 'L1 强制空仓', L2_special_period: 'L2 特殊时期',
  L3_sentiment: 'L3 情绪周期', L4_premarket: 'L4 盘前预选',
  L5_auction: 'L5 竞价过滤', L6_strategy: 'L6 策略量能',
  L7_ranking: 'L7 综合排序', L8_position: 'L8 仓位控制',
}
const layerLabel = (k: string) => layerCN[k] || k
const tradeMode = ref('simulated')
const dataSources = ref<any[]>([])
const brokers = ref<any[]>([])
const signalFilter = ref('all')
const filteredSignals = computed(() => { if (signalFilter.value === 'all') return signals.value; if (signalFilter.value === 'anomaly') return signals.value.filter(s => s.strategy.startsWith('anomaly_')); return signals.value.filter(s => s.strategy === signalFilter.value) })
const tradeDetailVisible = ref(false), tradeDetailData = ref<any>(null), tradeAuditData = ref<any[]>([]), tradeAuditVisible = ref(false)
const manualTrade = reactive({ ts_code: '', stock_name: '', side: 'buy', quantity: 0, price: 0 })
const manualQuote = ref<any>(null)
const isRunning = computed(() => status.value?.is_running ?? false)
const accountInfo = computed(() => status.value?.account ?? { total_assets: 0, available_cash: 0, market_value: 0, total_profit: 0 })
const positionRatio = computed(() => accountInfo.value.market_value > 0 ? (accountInfo.value.market_value / accountInfo.value.total_assets * 100).toFixed(1) : '0')
const totalPnl = computed(() => accountInfo.value.total_profit)
const circuitBreakerPaused = computed(() => status.value?.circuit_breaker?.trading_paused ?? false)
const posSort = ref('profit')
const sortedPositions = computed(() => {
  const arr = [...positions.value]
  switch(posSort.value) {
    case 'profit': return arr.sort((a, b) => a.profit_pct - b.profit_pct)
    case 'cost': return arr.sort((a, b) => b.market_value - a.market_value)
    case 'strategy': return arr.sort((a, b) => (a.strategy || '').localeCompare(b.strategy || ''))
    case 'time': return arr.sort((a, b) => (b.buy_time || '').localeCompare(a.buy_time || ''))
    default: return arr
  }
})
function playSignalSound() {
  if (!soundEnabled.value) return
  try {
    const ctx = new AudioContext()
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.connect(gain)
    gain.connect(ctx.destination)
    osc.frequency.value = 880
    osc.type = 'sine'
    gain.gain.value = 0.3
    osc.start()
    gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.3)
    osc.stop(ctx.currentTime + 0.3)
  } catch {}
}
function distanceToStopLoss(pos: PositionInfo): string { if (pos.stop_loss_price && pos.stop_loss_price > 0 && pos.current_price > 0) { const dist = ((pos.current_price - pos.stop_loss_price) / pos.current_price * 100); return dist.toFixed(1) + '%'; } const slPct = pos.stop_loss_pct ?? 3; return (pos.profit_pct + slPct).toFixed(1) + '%' }

// 【P1-7】交易确认弹窗(含loading防重复)
const confirmVisible = ref(false)
const confirmLoading = ref(false)
const confirmData = reactive({ title: '', message: '', onConfirm: () => {} })
function showConfirm(title: string, message: string, onConfirm: () => void) { confirmData.title = title; confirmData.message = message; confirmData.onConfirm = onConfirm; confirmVisible.value = true; confirmLoading.value = false }
async function handleConfirm() { if (confirmLoading.value) return; confirmLoading.value = true; try { await confirmData.onConfirm() } finally { confirmLoading.value = false; confirmVisible.value = false } }

// 【P1-6】复盘报告
const dailyReportVisible = ref(false)

// 【P1-4】信号过期倒计时
const nowMs = ref(Date.now())
let nowTimer: any = null
const SIGNAL_EXPIRE_MS = 300000 // 5分钟
function signalRemaining(sig: ScanSignal): number { if (!sig.created_at || sig.created_at <= 0) return -1; const remain = SIGNAL_EXPIRE_MS - (nowMs.value / 1000 - sig.created_at) * 1000; return Math.max(0, remain) }
function formatRemaining(ms: number): string { if (ms < 0) return ''; const s = Math.floor(ms / 1000); if (s < 60) return `${s}s`; return `${Math.floor(s / 60)}m${s % 60}s` }

async function openTradeDetail(ts_code: string) { try { const r = await api.get(`${scannerApi}/trade-detail/${ts_code}`); if (r?.success) { tradeDetailData.value = r.data; tradeDetailVisible.value = true } } catch (e: any) { ElMessage.error('获取详情失败') } }
async function openTradeAudit() { try { const r = await api.get(`${scannerApi}/trade-audit`); if (r?.success) { tradeAuditData.value = r.data; tradeAuditVisible.value = true } } catch (e: any) { ElMessage.error('获取审查失败') } }
function formatDecisionDetail(detail: any): string[] {
  if (!detail) return ['无决策详情']; const lines: string[] = []
  if (detail.filter_pipeline) { const fp = detail.filter_pipeline; lines.push('【9层筛选管道】'); for (const [l, a] of Object.entries(fp.layers_applied || {})) { lines.push(`  ${a ? '✅' : '⏭️'} ${layerLabel(l)}: ${fp.layer_details?.[l] || (a ? '生效' : '跳过')}`) }; lines.push(`  仓位系数: ${fp.position_ratio || '未知'}`) }
  if (detail.factors) { lines.push('【关键因子】'); for (const [k, v] of Object.entries(detail.factors)) { if (v !== 0 && v !== null) lines.push(`  ${factorLabel(k)}: ${typeof v === 'number' ? v.toFixed(2) : v}`) } }
  if (detail.sell_reason) { lines.push('【卖出决策】'); lines.push(`  原因: ${detail.sell_reason}`); if (detail.profit_pct) lines.push(`  盈亏: ${detail.profit_pct.toFixed(2)}%`); if (detail.stop_loss_pct) lines.push(`  止损线: ${detail.stop_loss_pct}%`); if (detail.take_profit_pct) lines.push(`  止盈线: ${detail.take_profit_pct}%`) }
  return lines
}
async function quickBuy(sig: ScanSignal) { const a = status.value?.account; if (!a) { ElMessage.warning('请先启动'); return } const q = Math.floor(a.available_cash * 0.25 / sig.price / 100) * 100; if (q <= 0) { ElMessage.warning('资金不足'); return } showConfirm('确认买入', `${sig.stock_name} ${sig.ts_code}\n${sig.strategy_name} | 涨${sig.pct_chg >= 0 ? '+' : ''}${sig.pct_chg.toFixed(1)}%\n买入 ${q}股 × ¥${sig.price.toFixed(2)} ≈ ¥${(q * sig.price).toFixed(0)}`, async () => { try { const r = await api.post(`${scannerApi}/trade`, { ts_code: sig.ts_code, stock_name: sig.stock_name, side: 'buy', quantity: q, price: sig.price, order_type: 'market', strategy: sig.strategy, reason: sig.reason }); if (r?.success) { ElMessage.success(`买入${sig.stock_name} ${q}股@${r.data.filled_price?.toFixed(2)}`); fetchScanner() } else ElMessage.error(r?.data?.message || '失败') } catch (e: any) { ElMessage.error('买入失败') } }) }
async function quickSell(pos: PositionInfo) { if (pos.available_qty <= 0) { ElMessage.warning('T+1限制'); return } showConfirm('确认卖出', `${pos.stock_name} ${pos.ts_code}\n${pos.profit_pct >= 0 ? '+' : ''}${pos.profit_pct.toFixed(1)}% | 卖出 ${pos.available_qty}股\n现价 ¥${pos.current_price.toFixed(2)} ≈ ¥${(pos.available_qty * pos.current_price).toFixed(0)}`, async () => { try { const r = await api.post(`${scannerApi}/trade`, { ts_code: pos.ts_code, stock_name: pos.stock_name, side: 'sell', quantity: pos.available_qty, price: pos.current_price, order_type: 'market', strategy: pos.strategy, reason: `手动卖出 ${pos.profit_pct >= 0 ? '+' : ''}${pos.profit_pct.toFixed(1)}%` }); if (r?.success) { ElMessage.success(`卖出${pos.stock_name} ${pos.available_qty}股@${r.data.filled_price?.toFixed(2)}`); fetchScanner() } else ElMessage.error(r?.data?.message || '失败') } catch (e: any) { ElMessage.error('卖出失败') } }) }
async function onManualCodeChange(code: string) {
  if (!code || code.length < 9) { manualQuote.value = null; return }
  // 优先从持仓/信号缓存获取
  const p = positions.value.find(x => x.ts_code === code)
  if (p) { manualQuote.value = { price: p.current_price, cost: p.cost_price, name: p.stock_name }; manualTrade.price = p.current_price; if (!manualTrade.stock_name) manualTrade.stock_name = p.stock_name; return }
  const s = signals.value.find(x => x.ts_code === code)
  if (s) { manualQuote.value = { price: s.price, name: s.stock_name }; manualTrade.price = s.price; if (!manualTrade.stock_name) manualTrade.stock_name = s.stock_name; return }
  // 缓存未命中则从quote API获取
  try { const r = await api.get(`${scannerApi}/quote/${code}`); if (r?.success) { manualQuote.value = { price: r.data.price, name: r.data.name, pct_chg: r.data.pct_chg }; manualTrade.price = r.data.price; if (!manualTrade.stock_name) manualTrade.stock_name = r.data.name } else manualQuote.value = null } catch { manualQuote.value = null }
}
const executeManualTrade = async () => { if (!manualTrade.ts_code) return; const sideText = manualTrade.side === 'buy' ? '买入' : '卖出'; const amount = (manualTrade.quantity || 0) * (manualTrade.price || 0); showConfirm(`确认${sideText}`, `${manualTrade.stock_name || manualTrade.ts_code}\n${sideText} ${manualTrade.quantity || 0}股 × ¥${(manualTrade.price || 0).toFixed(2)} ≈ ¥${amount.toFixed(0)}`, async () => { try { const r = await api.post(`${scannerApi}/trade`, { ts_code: manualTrade.ts_code, stock_name: manualTrade.stock_name, side: manualTrade.side, quantity: manualTrade.quantity || 0, price: manualTrade.price || 0, order_type: 'market', strategy: 'manual', reason: '手动操作' }); if (r?.success) { ElMessage.success(`${r.data.side === 'buy' ? '买入' : '卖出'} ${r.data.ts_code} ${r.data.filled_qty}股@${r.data.filled_price}`); manualTrade.ts_code = ''; manualTrade.stock_name = ''; manualTrade.quantity = 0; manualTrade.price = 0; fetchAll(true) } else ElMessage.error('下单失败') } catch (e: any) { ElMessage.error('下单失败') } }) }
const cumulativePnl = computed(() => { let total = 0; return timeline.value.filter(t => t.action === 'sell' && t.profit_amount != null).reduce((sum, t) => sum + (t.profit_amount || 0), 0) })
async function fetchScanner() { try { const r = await api.get(`${scannerApi}/all`); if (r?.success) { const d = r.data; if (d.signals && signals.value.length > 0 && d.signals.length > signals.value.length) { playSignalSound() } if (d.status) status.value = d.status; if (d.signals) signals.value = d.signals; if (d.positions) positions.value = d.positions; if (d.timeline) timeline.value = d.timeline; if (d.orders) orders.value = d.orders } fetchLimitPools() } catch (e) { console.error(e) } }
async function fetchScannerFull() { try { const [sR, sigR, posR, tlR, ordR] = await Promise.all([api.get(`${scannerApi}/status`), api.get(`${scannerApi}/signals`), api.get(`${scannerApi}/positions`), api.get(`${scannerApi}/timeline`), api.get(`${scannerApi}/orders`)]); if (sR?.success) status.value = sR.data; if (sigR?.success) signals.value = sigR.data; if (posR?.success) positions.value = posR.data; if (tlR?.success) timeline.value = tlR.data; if (ordR?.success) orders.value = ordR.data || [] } catch (e) { console.error(e) } }
async function startScanner() { await api.post(`${scannerApi}/start`, { account_id: 'default', trade_mode: dryRun.value ? 'dry_run' : tradeMode.value }); await fetchScanner() }
async function stopScanner() { showConfirm('停止扫描', '确认停止扫描器？\n持仓将保留，可手动卖出。', async () => { await api.post(`${scannerApi}/stop`, { sell_all: false }); await fetchScanner() }) }
async function manualScan() { loading.value = true; try { const r = await api.post(`${scannerApi}/scan-once`); if (r?.success) { const m = r.data?.message; if (m) ElMessage.warning(m); else ElMessage.success(`扫描完成: ${r.data?.signals || 0}信号, ${r.data?.positions || 0}持仓`) } else ElMessage.error('扫描失败') } catch (e: any) { ElMessage.error('扫描失败') } finally { loading.value = false; await fetchScanner() } }
async function forceScan() { loading.value = true; try { const r = await api.post(`${scannerApi}/scan-once`, { force: true }); if (r?.success) { ElMessage.success(`强制扫描完成: ${r.data?.signals || 0}信号, ${r.data?.positions || 0}持仓`) } else ElMessage.error('强制扫描失败') } catch (e: any) { ElMessage.error('强制扫描失败') } finally { loading.value = false; await fetchScanner() } }
const stratCollapsed = ref<Record<string, boolean>>({ halfway_chase: true, first_limit_up: true, dragon_head: true, limit_down_qiao: true, limit_up_open: true })
const stratSectionCollapsed = ref(true)
const qaSectionCollapsed = ref(false)
function toggleStrat(id: string) { stratCollapsed.value[id] = !stratCollapsed.value[id] }
async function dailySettlement() { try { const r = await api.post(`${scannerApi}/daily-settlement`); if (r?.success) { ElMessage.success(r.data?.message || '日结算完成'); await fetchScanner() } } catch (e: any) { ElMessage.error('日结算失败') } }
async function resetAccount() { showConfirm('⚠️ 重置账户', '将清空所有持仓和交易记录，不可恢复！\n确认重置？', async () => { try { const r = await api.post(`${scannerApi}/reset`); if (r?.success) { ElMessage.success('账户已重置'); await fetchAll(true) } } catch (e: any) { ElMessage.error('重置失败') } }) }
async function sellAllPositions() { showConfirm('⚠️ 一键清仓', `确认清仓所有持仓？\n当前持仓 ${positions.value.length} 只，总市值 ¥${positions.value.reduce((s, p) => s + p.current_price * p.total_qty, 0).toFixed(0)}`, async () => { try { const r = await api.post(`${scannerApi}/sell-all`); if (r?.success) { ElMessage.success(r.data?.message || '清仓完成'); await fetchAll(true) } } catch (e: any) { ElMessage.error('清仓失败') } }) }
async function fetchWeeklyReport() { try { const r = await api.get(`${scannerApi}/weekly-report`); if (r?.success) return r.data } catch { return null } }
async function exportTradeLog() { try { const r = await api.get(`${scannerApi}/trade-log?format=csv&days=30`); if (r?.success && r.data) { const blob = new Blob([r.data], { type: 'text/csv;charset=utf-8' }); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = r.filename || 'trade_log.csv'; a.click(); URL.revokeObjectURL(url); ElMessage.success('导出成功') } } catch { ElMessage.error('导出失败') } }
async function saveSnapshot() { try { const r = await api.post(`${scannerApi}/snapshot`); if (r?.success) ElMessage.success('快照已保存') } catch { ElMessage.error('保存失败') } }
async function resetCircuitBreaker() { try { const r = await api.post(`${scannerApi}/circuit-breaker/reset`); if (r?.success) { ElMessage.success('熔断已重置'); fetchAll(true) } } catch { ElMessage.error('重置失败') } }
async function fetchLimitPools() { try { const r = await api.get(`${scannerApi}/limit-pools`); if (r?.success) limitPools.value = r.data } catch { } }
async function fetchDailyReport() { try { const r = await api.get(`${scannerApi}/daily-report`); if (r?.success) dailyReport.value = r.data } catch { } }
async function fetchDataSources() { try { const [sR, bR] = await Promise.all([api.get('/datasource/sources'), api.get('/datasource/brokers')]); if (sR?.success) dataSources.value = sR.data || []; if (bR?.success) brokers.value = bR.data || [] } catch { } }
async function fetchAll(force = false) { await Promise.all([fetchScanner(), fetchStrategies(), fetchDataSources(), fetchLimitPools(), fetchDailyReport()]) }
async function fetchStrategies() { try { const [sR, rR] = await Promise.all([api.get(`${configApi}/strategies`), api.get(`${configApi}/global-risk`)]); if (sR?.success) strategies.value = sR.data; if (rR?.success) globalRisk.value = rR.data } catch (e) { console.error(e) } }
async function toggleStrategy(sid: string, enabled: boolean) { try { await api.put(`${configApi}/strategies/${sid}`, { enabled }); await fetchStrategies(); ElMessage.success(enabled ? '已启用' : '已停用') } catch { ElMessage.error('操作失败') } }
function openEditDialog(strategy: StrategyConfig) { editingStrategy.value = strategy; editParams.value = { ...strategy.params }; editRiskParams.value = { ...strategy.riskParams }; editTab.value = 'params'; editDialogVisible.value = true }
async function saveStrategy() {
  if (!editingStrategy.value) return
  // 【P1-9】参数校验
  const strategy = editingStrategy.value
  const allDescs = [...(strategy.paramDescriptions || []), ...(strategy.riskDescriptions || [])]
  const allValues = { ...editParams.value, ...editRiskParams.value }
  for (const desc of allDescs) {
    const v = allValues[desc.key]
    if (v !== undefined && (v < desc.min || v > desc.max)) {
      ElMessage.warning(`${desc.label} 超出范围(${desc.min}~${desc.max}${desc.unit})，当前值: ${v}`)
      return
    }
  }
  saving.value = true
  try { await api.put(`${configApi}/strategies/${strategy.id}`, { params: editParams.value, riskParams: editRiskParams.value }); await fetchStrategies(); editDialogVisible.value = false; ElMessage.success('已保存') }
  catch { ElMessage.error('保存失败') }
  finally { saving.value = false }
}
async function resetStrategy(sid: string) { try { await api.post(`${configApi}/reset/${sid}`); await fetchStrategies(); ElMessage.success('已重置') } catch { ElMessage.error('重置失败') } }
onMounted(async () => { await Promise.all([fetchScanner(), fetchStrategies(), fetchDataSources(), fetchLimitPools()]); connectWS(); nowTimer = setInterval(() => { nowMs.value = Date.now() }, 1000); const getRefreshInterval = () => { const n = new Date(), h = n.getHours(), m = n.getMinutes(); const isTrading = (h === 9 && m >= 30) || (h >= 10 && h < 15) || (h === 15 && m === 0); return isTrading ? 5000 : 60000 }; refreshTimer = setInterval(() => { if (!autoRefresh.value || ws?.readyState === WebSocket.OPEN) return; fetchScannerFast() }, getRefreshInterval()) })
onUnmounted(() => { if (refreshTimer) clearInterval(refreshTimer); if (nowTimer) clearInterval(nowTimer); disconnectWS() })
function connectWS() { try { const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'; ws = new WebSocket(`${proto}//${location.host}/ws`); let wsDebounceTimer: any = null; const wsDebouncedFetch = () => { if (wsDebounceTimer) clearTimeout(wsDebounceTimer); wsDebounceTimer = setTimeout(fetchScanner, 500); }; ws.onopen = () => { ws?.send(JSON.stringify({ type: 'subscribe_scanner' })); }; ws.onmessage = (e) => { try { const d = JSON.parse(e.data); if (d.type === 'scanner_signal') { signals.value = d.signals?.length ? d.signals : signals.value; wsDebouncedFetch(); } else if (d.type === 'scanner_position') { positions.value = d.positions?.length ? d.positions : positions.value; } else if (d.type === 'scanner_timeline') { if (d.item) timeline.value = [...timeline.value, d.item]; wsDebouncedFetch(); } else if (d.type === 'scanner_status') { if (d.status) status.value = { ...status.value, ...d.status }; wsDebouncedFetch(); } } catch {} }; ws.onclose = () => { wsReconnectTimer = setTimeout(connectWS, 3000); }; ws.onerror = () => { ws?.close(); }; } catch {} }
function disconnectWS() { if (wsReconnectTimer) clearTimeout(wsReconnectTimer); if (ws) { ws.close(); ws = null; } }
const historyDate = ref('')
const historyData = ref<any[]>([])
const historyLoading = ref(false)
async function loadHistory() { if (!historyDate.value) { ElMessage.warning('请选择日期'); return } historyLoading.value = true; try { const d = historyDate.value.replace(/-/g, ''); const r = await api.get(`${scannerApi}/timeline/history?date=${d}`); if (r?.success) { historyData.value = r.data || []; if (!historyData.value.length) ElMessage.info('该日无交易记录') } } catch { ElMessage.error('加载失败') } finally { historyLoading.value = false } }
const compareData = ref<any[]>([])
const compareVisible = ref(false)
const compareLoading = ref(false)
const weeklyReportData = ref<any>(null)
const weeklyReportVisible = ref(false)
async function loadCompare() { compareLoading.value = true; try { const r = await api.get(`${scannerApi}/backtest-compare`); if (r?.success) { compareData.value = r.data || []; compareVisible.value = true } } catch { ElMessage.error('加载失败') } finally { compareLoading.value = false } }
async function openWeeklyReport() { try { const data = await fetchWeeklyReport(); if (data) { weeklyReportData.value = data; weeklyReportVisible.value = true } else ElMessage.warning('暂无周报数据') } catch { ElMessage.error('加载失败') } }
// 【调试增强】
const dryRun = computed(() => status.value?.dry_run ?? false)
const layerDebugVisible = ref(false)
const layerDebugData = ref<any>(null)
const layerDebugLoading = ref(false)
const scanTraceVisible = ref(false)
const scanTraceData = ref<any>(null)
const scanTraceCode = ref('')
async function toggleDryRun() { try { const r = await api.post(`${scannerApi}/debug/dry-run`); if (r?.success) { ElMessage.success(r.data.mode); fetchScanner() } } catch { ElMessage.error('切换失败') } }
async function openLayerDebug() { layerDebugLoading.value = true; layerDebugVisible.value = true; try { const r = await api.get(`${scannerApi}/debug/layers`); if (r?.success) layerDebugData.value = r.data } catch { ElMessage.error('加载失败') } finally { layerDebugLoading.value = false } }
async function openScanTrace(ts_code: string) { scanTraceCode.value = ts_code; scanTraceVisible.value = true; try { const r = await api.get(`${scannerApi}/debug/scan-trace/${ts_code}`); if (r?.success) scanTraceData.value = r.data } catch { ElMessage.error('加载失败') } }
function formatLayerTrace(trace: Record<string, any>): string[] { if (!trace) return ['无链路数据']; const lines: string[] = []; for (const [layer, info] of Object.entries(trace)) { if (typeof info === 'object' && info !== null) { const applied = info.applied !== undefined ? (info.applied ? '✅' : '⏭️') : ''; const detail = info.detail || info.reason || ''; lines.push(`${applied} ${layerLabel(layer)}: ${detail}`) } else { lines.push(`${layerLabel(layer)}: ${info}`) } } return lines }
function signalStatusTag(status?: string) { if (!status || status === 'new') return { text: '新', type: 'primary' }; if (status === 'executed') return { text: '已买', type: 'success' }; if (status === 'skipped') return { text: '跳过', type: 'warning' }; if (status === 'expired') return { text: '过期', type: 'info' }; if (status === 'filtered') return { text: '过滤', type: 'danger' }; return { text: status, type: 'info' } }
</script>
<template>
  <div class="mm" :class="{ dark: darkMode }">
    <!-- 顶部状态栏 -->
    <div class="mm-header">
      <div class="hh-left">
        <div class="hh-status" :class="{ running: isRunning, stopped: !isRunning }"><span class="dot"></span><span>{{ isRunning ? '扫描中' : '已停止' }}</span></div>
        <ElTag size="small" :type="tradeMode === 'gm' ? 'warning' : 'info'">🔵仿真</ElTag>
        <ElTag v-if="dryRun" type="warning" size="small">🔍调试</ElTag>
        <ElTag v-if="circuitBreakerPaused" type="danger" size="small">⚠️熔断</ElTag>
        <!-- 【P1-5】数据源健康指示 -->
        <div v-if="status?.data_sources?.length" class="ds-indicator">
          <span v-for="ds in status.data_sources" :key="ds.name" class="ds-dot" :class="{ ok: ds.available, err: !ds.available }" :title="`${ds.name}: ${ds.available ? '可用' : '不可用'} ${ds.stocks || 0}只 ${ds.calls}/${ds.limit}次`">{{ ds.name === 'eastmoney' ? '东财' : ds.name === 'biying' ? '必盈' : ds.name }}</span>
        </div>
      </div>
      <div class="hh-account" v-if="status">
        <div class="ha"><span class="hl">资产</span><span class="hv">{{ (accountInfo.total_assets / 10000).toFixed(1) }}万</span></div>
        <div class="ha"><span class="hl">可用</span><span class="hv">{{ (accountInfo.available_cash / 10000).toFixed(1) }}万</span></div>
        <div class="ha"><span class="hl">仓位</span><span class="hv">{{ positionRatio }}%</span></div>
        <div class="ha"><span class="hl">盈亏</span><span class="hv" :class="totalPnl >= 0 ? 'up' : 'down'">{{ totalPnl >= 0 ? '+' : '' }}{{ totalPnl.toFixed(0) }}</span></div>
      </div>
      <div class="hh-actions">
        <ElButton v-if="!isRunning" type="success" size="small" @click="startScanner">▶ 启动</ElButton>
        <ElButton v-else type="danger" size="small" @click="stopScanner">⏹ 停止</ElButton>
        <ElButton size="small" :loading="loading" @click="manualScan" :disabled="!isRunning">📡 扫描</ElButton>
        <ElButton size="small" @click="dailySettlement" :disabled="!isRunning">📅 日结算</ElButton>
        <ElSwitch v-model="soundEnabled" size="small" active-text="🔔" inactive-text="" />
        <ElSwitch v-model="autoRefresh" size="small" active-text="自动" inactive-text="" />
        <span class="dark-toggle" @click="darkMode = !darkMode">{{ darkMode ? '☀️' : '🌙' }}</span>
      </div>
    </div>

    <!-- 未启动引导 -->
    <div v-if="!isRunning && !status" class="mm-guide">
      <div class="guide-card">
        <div class="guide-icon">📡</div>
        <div class="guide-title">欢迎使用超短量化实盘监控</div>
        <div class="guide-steps">
          <div class="guide-step"><span class="sn">1</span> 点击 <b>▶ 启动</b> 开始扫描器</div>
          <div class="guide-step"><span class="sn">2</span> 点击 <b>📡 扫描</b> 手动触发选股</div>
          <div class="guide-step"><span class="sn">3</span> 左侧调整 <b>策略开关</b> 和参数</div>
          <div class="guide-step"><span class="sn">4</span> 信号出现后点 <b>🟢买入</b> 快捷下单</div>
          <div class="guide-step"><span class="sn">5</span> 持仓卡片点 <b>🔴卖出</b> 快捷平仓</div>
        </div>
        <ElButton type="success" size="large" @click="startScanner" style="margin-top:16px">▶ 启动扫描器</ElButton>
      </div>
    </div>

    <!-- 3列主布局 -->
    <div v-else class="mm-body">
      <!-- 左列: 策略控制 -->
      <div class="mm-left">
        <div class="st cp" @click="stratSectionCollapsed = !stratSectionCollapsed">🎛️ 策略控制 <span class="sc-arrow">{{ stratSectionCollapsed ? '▶' : '▼' }}</span></div>
        <template v-if="!stratSectionCollapsed">
        <div v-for="s in strategies" :key="s.id" class="sc" :class="{ disabled: !s.enabled }">
          <div class="sc-top cp" @click="toggleStrat(s.id)"><span class="sc-icon">{{ strategyMeta[s.id]?.icon || '📋' }}</span><span class="sc-name">{{ s.name }}</span><ElSwitch :model-value="s.enabled" @change="(v: boolean) => toggleStrategy(s.id, v)" size="small" @click.stop /><span class="sc-arrow">{{ stratCollapsed[s.id] ? '▶' : '▼' }}</span></div>
          <div v-if="!stratCollapsed[s.id]">
            <div class="sc-desc">{{ strategyMeta[s.id]?.desc || '' }}</div>
            <div class="sc-params"><div v-for="p in s.paramDescriptions.slice(0, 3)" :key="p.key" class="pm"><span class="pk">{{ p.label }}</span><span class="pv">{{ p.displayValue }}{{ p.unit }}</span></div></div>
            <ElButton size="small" text type="primary" @click="openEditDialog(s)">⚙️ 编辑</ElButton>
          </div>
        </div>
        </template>
        <div class="st mt-10 cp" @click="qaSectionCollapsed = !qaSectionCollapsed">⚡ 快捷操作 <span class="sc-arrow">{{ qaSectionCollapsed ? '▶' : '▼' }}</span></div>
        <div class="qa" v-if="!qaSectionCollapsed">
          <div class="qa-group"><div class="qa-label">扫描</div>
          <ElButton size="small" @click="manualScan" :loading="loading" :disabled="!isRunning" class="w-full">📡 手动扫描</ElButton>
        <ElButton size="small" type="warning" @click="forceScan" :loading="loading" :disabled="!isRunning" class="w-full" title="忽略交易时间检查，消耗必盈额度">⚡ 强制扫描</ElButton>
          <ElButton size="small" @click="dailySettlement" :disabled="!isRunning" class="w-full">📅 日结算(T+1)</ElButton>
          </div>
          <div class="qa-group"><div class="qa-label">分析</div>
          <ElButton size="small" @click="openTradeAudit" :disabled="!timeline.length" class="w-full">🔍 审查全部交易</ElButton>
          <ElButton size="small" @click="openLayerDebug" :loading="layerDebugLoading" class="w-full">🧪 9层调试</ElButton>
          <ElButton size="small" @click="loadCompare" :loading="compareLoading" class="w-full">📊 回测对比</ElButton>
          <ElButton size="small" @click="fetchDailyReport(); dailyReportVisible = true" class="w-full">📈 复盘报告</ElButton>
          <ElButton size="small" @click="openWeeklyReport" class="w-full">📊 周报</ElButton>
          </div>
          <div class="qa-group"><div class="qa-label">风控</div>
          <ElButton size="small" @click="toggleDryRun" class="w-full">{{ dryRun ? '🔴 关闭调试' : '🔍 开启调试' }}</ElButton>
          <ElButton v-if="circuitBreakerPaused" size="small" type="danger" @click="resetCircuitBreaker" class="w-full">🔓 重置熔断</ElButton>
          <ElButton v-if="positions.length" size="small" type="danger" @click="sellAllPositions" class="w-full">⚡ 一键清仓</ElButton>
          <ElButton size="small" type="warning" @click="resetAccount" class="w-full">🗑️ 清仓重置</ElButton>
          </div>
          <div class="qa-group"><div class="qa-label">导出</div>
          <ElButton size="small" @click="exportTradeLog" class="w-full">📥 导出交易日志</ElButton>
          <ElButton size="small" @click="saveSnapshot" class="w-full">📸 保存快照</ElButton>
          </div>
        </div>
        <div class="st mt-10">🔧 手动下单</div>
        <div class="mf">
          <ElInput v-model="manualTrade.ts_code" placeholder="代码 000001.SZ" size="small" @change="onManualCodeChange(manualTrade.ts_code)" />
          <div class="mf-row"><ElSelect v-model="manualTrade.side" size="small" style="width:70px"><ElOption label="买入" value="buy" /><ElOption label="卖出" value="sell" /></ElSelect><ElInputNumber v-model="manualTrade.quantity" :min="0" :step="100" placeholder="数量" size="small" style="flex:1" controls-position="right" /></div>
          <div class="mf-row"><ElInputNumber v-model="manualTrade.price" :min="0" :precision="2" :step="0.01" placeholder="价格(0=市价)" size="small" style="flex:1" controls-position="right" /><span v-if="manualQuote" class="mf-hint" @click="manualTrade.price = manualQuote.price">💰 填入现价</span></div>
          <ElButton type="primary" size="small" :disabled="!manualTrade.ts_code" @click="executeManualTrade" class="w-full">下单</ElButton>
          <div v-if="manualQuote" class="mf-q">💡 现价: ¥{{ manualQuote.price?.toFixed(2) }} <span v-if="manualQuote.pct_chg" :class="manualQuote.pct_chg >= 0 ? 'up' : 'down'">{{ manualQuote.pct_chg >= 0 ? '+' : '' }}{{ manualQuote.pct_chg.toFixed(2) }}%</span></div>
        </div>

      </div>

      <!-- 中列: 信号+行情 -->
      <div class="mm-center">
        <div class="st">🎯 活跃信号 <div style="display:inline-flex;gap:2px;margin-left:6px"><ElTag v-for="f in [{k:'all',l:'全部'},{k:'halfway_chase',l:'半路'},{k:'first_limit_up',l:'首板'},{k:'limit_down_qiao',l:'跌停'},{k:'anomaly',l:'异动'}]" :key="f.k" size="small" :type="signalFilter===f.k?'primary':'info'" class="cp" @click="signalFilter=f.k">{{ f.l }}</ElTag></div> <ElBadge :value="filteredSignals.length" :max="99" style="margin-left:4px" /></div>
        <div class="sl">
          <div v-if="!signals.length" class="empty">启动后扫描获取信号</div>
          <div v-for="sig in filteredSignals" :key="sig.ts_code + sig.strategy" class="sig-row" :title="`${sig.ts_code} ${sig.stock_name} | ${sig.strategy_name} | 量比${sig.volume_ratio?.toFixed(1) || '-'} | 换手${sig.turnover_rate?.toFixed(1) || '-'}% | ${sig.reason}`">
            <ElTag size="small" :color="strategyMeta[sig.strategy]?.color || '#909399'" class="tag-solid" style="min-width:52px;text-align:center">{{ sig.strategy_name }}</ElTag><ElTag v-if="sig.signal_status === 'executed'" size="small" type="success">已买</ElTag><ElTag v-if="sig.signal_status === 'skipped'" size="small" type="warning">跳过</ElTag><ElTag v-if="sig.signal_status === 'expired'" size="small" type="info">过期</ElTag><span class="code">{{ sig.ts_code }}</span><span class="name">{{ sig.stock_name }}</span><span v-if="sig.signal_status === 'new' && signalRemaining(sig) >= 0" class="expire-tag" :class="{ urgent: signalRemaining(sig) < 60000 }">⏱{{ formatRemaining(signalRemaining(sig)) }}</span><span v-if="sig.volume_ratio" class="factor">量比{{ sig.volume_ratio.toFixed(1) }}</span><span v-if="sig.turnover_rate" class="factor">换手{{ sig.turnover_rate.toFixed(1) }}%</span><template v-if="sig.key_factors"><span v-for="(v, k) in sig.key_factors" :key="k" class="factor kf">{{ v }}</span></template><span :class="sig.pct_chg >= 0 ? 'up' : 'down'" class="pct ml-auto" style="font-weight:600">{{ sig.pct_chg >= 0 ? '+' : '' }}{{ sig.pct_chg.toFixed(1) }}%</span><ElButton v-if="!dryRun && sig.signal_status === 'new'" size="small" type="danger" plain @click="quickBuy(sig)" class="btn-xs">买</ElButton><ElButton v-if="sig.decision_detail" size="small" type="info" plain @click="openTradeDetail(sig.ts_code)" class="btn-xs">🔍</ElButton><ElButton v-if="sig.layer_trace" size="small" type="warning" plain @click="openScanTrace(sig.ts_code)" class="btn-xs">🧪</ElButton>
          </div>
        </div>

      </div>

      <!-- 右列: 持仓 -->
      <div class="mm-right">
        <div class="st">📊 持仓监控 <ElBadge :value="positions.length" :max="99" style="margin-left:4px" /><ElSelect v-model="posSort" size="small" style="width:80px;margin-left:auto"><ElOption label="盈亏" value="profit" /><ElOption label="市值" value="cost" /><ElOption label="策略" value="strategy" /><ElOption label="时间" value="time" /></ElSelect></div>
        <div class="sl">
          <div v-if="!positions.length" class="empty">暂无持仓</div>
          <div v-for="pos in sortedPositions" :key="pos.ts_code" class="pos-card">
            <div class="pos-top"><ElTag size="small" :color="strategyMeta[pos.strategy]?.color || '#909399'" class="tag-solid" style="font-size:10px;min-width:48px;text-align:center">{{ pos.strategy_name || strategyCN(pos.strategy) }}</ElTag><span class="code">{{ pos.ts_code }}</span><span class="name">{{ pos.stock_name }}</span><span :class="pos.profit_pct >= 0 ? 'up' : 'down'" class="pct">{{ pos.profit_pct >= 0 ? '+' : '' }}{{ pos.profit_pct.toFixed(1) }}%</span><span class="mini-bar"><span class="mini-bar-fill" :style="{ width: Math.min(Math.abs(pos.profit_pct) / 10 * 100, 100) + '%' }" :class="pos.profit_pct >= 0 ? 'bar-up' : 'bar-down'"></span></span><span v-if="pos.today_buy > 0" class="t1-tag">T+1</span><ElButton size="small" type="danger" plain @click="quickSell(pos)" :disabled="pos.available_qty <= 0" class="btn-xs ml-auto">卖出</ElButton><ElButton size="small" type="info" plain @click="openTradeDetail(pos.ts_code)" class="btn-xs">详情</ElButton></div>
            <div class="pos-info"><span>{{ pos.shares }}股</span><span>成本{{ pos.cost_price.toFixed(2) }}</span><span>现价{{ pos.current_price.toFixed(2) }}</span><span v-if="pos.market_value" class="mv">市值{{ (pos.market_value / 10000).toFixed(1) }}万</span><span v-if="pos.profit_amount != null" :class="pos.profit_amount >= 0 ? 'up' : 'down'" class="pamt">{{ pos.profit_amount >= 0 ? '+' : '' }}¥{{ Math.abs(pos.profit_amount).toFixed(0) }}</span><span v-if="pos.stop_loss_pct != null" class="rl stop">止损{{ pos.stop_loss_pct.toFixed(1) }}% ¥{{ pos.stop_loss_price?.toFixed(2) || (pos.cost_price * (1 - pos.stop_loss_pct / 100)).toFixed(2) }}</span><span v-if="pos.take_profit_pct != null" class="rl profit">止盈{{ pos.take_profit_pct.toFixed(1) }}% ¥{{ pos.take_profit_price?.toFixed(2) || (pos.cost_price * (1 + (pos.take_profit_pct || 7.0) / 100)).toFixed(2) }}</span><span v-if="pos.stop_loss_pct != null" class="rd" :class="{ danger: pos.profit_pct + (pos.stop_loss_pct || 3) < 2 }">距止损{{ (pos.profit_pct + (pos.stop_loss_pct || 3)).toFixed(1) }}%</span></div>
          </div>
        </div>

      </div>
    </div>

    <!-- 底部时间线 -->
    <div v-if="isRunning || timeline.length" class="mm-footer">
      <div class="tl-header"><div class="st">⏱️ 交易时间线 ({{ timeline.length }}) <span v-if="cumulativePnl !== 0" :class="cumulativePnl >= 0 ? 'up' : 'down'" style="font-size:12px;margin-left:6px">累计{{ cumulativePnl >= 0 ? '+' : '' }}¥{{ cumulativePnl.toFixed(0) }}</span> <ElButton v-if="timeline.length" size="small" type="warning" @click="openTradeAudit" style="margin-left:6px">🔍 审查全部</ElButton> <div style="display:inline-flex;align-items:center;gap:4px;margin-left:8px"><ElDatePicker v-model="historyDate" type="date" placeholder="选择日期" size="small" value-format="YYYY-MM-DD" style="width:140px" :disabled-date="(d: Date) => d > new Date()" /><ElButton size="small" @click="loadHistory" :loading="historyLoading" style="padding:2px 8px;font-size:11px">回放</ElButton><ElButton v-if="historyData.length" size="small" type="info" @click="historyData=[];historyDate=''" style="padding:2px 8px;font-size:11px">返回今日</ElButton></div></div></div>
      <div class="tl-body">
        <div class="tl-col" style="flex:3">
          <div v-if="historyData.length" class="history-tag">📜 {{ historyDate }} 历史回放 ({{ historyData.length }}条)</div>
          <div v-if="!historyData.length && !timeline.length" class="empty">暂无交易</div>
          <div v-for="(item, i) in historyData.length ? historyData : timeline" :key="i" class="tl-row cp" @click="openTradeDetail(item.ts_code)"><span class="tl-time">{{ item.time }}</span><span class="tl-action" :class="item.action === 'buy' ? 'buy' : 'sell'">{{ item.action === 'buy' ? '买' : '卖' }}</span><span class="code">{{ item.ts_code }}</span><span class="name">{{ item.stock_name }}</span><span class="tl-detail">{{ item.shares }}股@{{ item.price.toFixed(2) }}</span><span v-if="item.profit_pct !== undefined" :class="item.profit_pct >= 0 ? 'up' : 'down'">{{ item.profit_pct >= 0 ? '+' : '' }}{{ item.profit_pct.toFixed(1) }}%</span><span v-if="item.profit_amount != null" :class="item.profit_amount >= 0 ? 'up' : 'down'" class="tl-amt">{{ item.profit_amount >= 0 ? '+' : '' }}¥{{ item.profit_amount.toFixed(0) }}</span></div>
        </div>
        <div class="tl-col" v-if="orders.length" style="flex:2">
          <div class="st">📋 历史订单 ({{ orders.length }})</div>
          <div v-for="o in orders.slice(0, 20)" :key="o.order_id" class="tl-row cp" @click="openTradeDetail(o.ts_code)"><span class="tl-time">{{ o.trade_date?.slice(-4) || '' }} {{ o.create_time }}</span><span class="tl-action" :class="o.side === 'buy' ? 'buy' : 'sell'">{{ o.side === 'buy' ? '买' : '卖' }}</span><span class="code">{{ o.ts_code }}</span><span class="name">{{ o.stock_name }}</span><span class="tl-detail">{{ o.filled_qty }}股@{{ o.filled_price?.toFixed(2) || '0.00' }}</span><span class="text-tertiary-sm">{{ strategyCN(o.strategy) }}</span></div>
        </div>
        <div class="tl-col" style="flex:2">
          <div class="st">🔥 涨跌停池 <div style="display:inline-flex;gap:2px;margin-left:6px"><ElTag size="small" :type="limitPoolTab==='limit_up'?'danger':'info'" class="cp" @click="limitPoolTab='limit_up'">涨停{{ limitPools.limit_up.length }}</ElTag><ElTag size="small" :type="limitPoolTab==='limit_down'?'warning':'info'" class="cp" @click="limitPoolTab='limit_down'">跌停{{ limitPools.limit_down.length }}</ElTag><ElTag size="small" :type="limitPoolTab==='broken'?'':'info'" class="cp" @click="limitPoolTab='broken'">炸板{{ limitPools.broken.length }}</ElTag></div></div>
          <div v-if="!limitPools[limitPoolTab as keyof typeof limitPools]?.length" class="empty">暂无数据</div>
          <div v-for="item in (limitPools[limitPoolTab as keyof typeof limitPools] || []).slice(0, 20)" :key="item.ts_code" class="limit-row"><span class="code">{{ item.ts_code }}</span><span class="name">{{ item.name }}</span><span :class="item.pct_chg >= 0 ? 'up' : 'down'">{{ item.pct_chg >= 0 ? '+' : '' }}{{ item.pct_chg.toFixed(1) }}%</span><span v-if="item.limit_times" class="lb-tag">{{ item.limit_times }}连板</span><span v-if="item.fd_amount" class="fd-tag">封{{ item.fd_amount }}万</span></div>
        </div>
        <div class="tl-col" style="flex:1;max-height:none">
          <div class="st">📈 今日统计</div>
          <div class="stats" v-if="status"><div class="si"><div class="sv">{{ status.stats.signals_found }}</div><div class="sl2">信号</div></div><div class="si"><div class="sv">{{ status.stats.trades_executed }}</div><div class="sl2">交易</div></div><div class="si"><div class="sv text-stock-up">{{ status.stats.stop_losses }}</div><div class="sl2">止损</div></div><div class="si"><div class="sv text-stock-down">{{ status.stats.take_profits }}</div><div class="sl2">止盈</div></div></div>
        </div>
      </div>
    </div>

    <!-- 策略编辑弹窗 -->
    <ElDialog v-model="editDialogVisible" :title="`编辑 ${editingStrategy?.name}`" width="560px" :close-on-click-modal="false">
      <ElTabs v-model="editTab">
        <ElTabPane label="选股参数" name="params"><div v-for="p in editingStrategy?.paramDescriptions || []" :key="p.key" style="margin-bottom:12px"><div style="font-size:13px;margin-bottom:4px">{{ p.label }} <span class="text-tertiary">({{ p.min }}~{{ p.max }}{{ p.unit }})</span></div><ElSlider v-model="editParams[p.key]" :min="p.min" :max="p.max" :step="p.step" show-input size="small" /></div></ElTabPane>
        <ElTabPane label="风控参数" name="risk"><div v-for="p in editingStrategy?.riskDescriptions || []" :key="p.key" style="margin-bottom:12px"><div style="font-size:13px;margin-bottom:4px">{{ p.label }} <span class="text-tertiary">({{ p.min }}~{{ p.max }}{{ p.unit }})</span></div><ElSlider v-model="editRiskParams[p.key]" :min="p.min" :max="p.max" :step="p.step" show-input size="small" /></div></ElTabPane>
      </ElTabs>
      <template #footer><ElButton @click="editDialogVisible = false">取消</ElButton><ElButton type="primary" :loading="saving" @click="saveStrategy">保存</ElButton></template>
    </ElDialog>

    <!-- 交易详情弹窗 -->
    <ElDialog v-model="tradeDetailVisible" :title="`🔍 交易审查 — ${tradeDetailData?.ts_code || ''}`" width="680px">
      <div v-if="tradeDetailData" class="td">
        <div class="td-sec"><div class="td-t">📥 买入决策</div><template v-if="tradeDetailData.buy"><div class="td-g"><div class="td-i"><span class="td-l">时间</span><span class="td-v">{{ tradeDetailData.buy.time }}</span></div><div class="td-i"><span class="td-l">价格</span><span class="td-v">{{ tradeDetailData.buy.price?.toFixed(2) }}</span></div><div class="td-i"><span class="td-l">数量</span><span class="td-v">{{ tradeDetailData.buy.shares }}股</span></div><div class="td-i"><span class="td-l">策略</span><span class="td-v">{{ strategyCN(tradeDetailData.buy.strategy) }}</span></div></div><div class="td-r">原因: {{ tradeDetailData.buy.reason }}</div><template v-if="tradeDetailData.buy.decision_detail"><div class="td-c">决策链路:</div><div v-for="(line, i) in formatDecisionDetail(tradeDetailData.buy.decision_detail)" :key="i" class="cl">{{ line }}</div></template></template><div v-else class="td-e">无买入记录</div></div>
        <div class="td-sec"><div class="td-t">📤 卖出决策</div><template v-if="tradeDetailData.sell"><div class="td-g"><div class="td-i"><span class="td-l">时间</span><span class="td-v">{{ tradeDetailData.sell.time }}</span></div><div class="td-i"><span class="td-l">价格</span><span class="td-v">{{ tradeDetailData.sell.price?.toFixed(2) }}</span></div><div class="td-i"><span class="td-l">盈亏</span><span class="td-v" :class="tradeDetailData.sell.profit_pct >= 0 ? 'up' : 'down'">{{ tradeDetailData.sell.profit_pct >= 0 ? '+' : '' }}{{ tradeDetailData.sell.profit_pct?.toFixed(2) }}%</span></div></div><div class="td-r">原因: {{ tradeDetailData.sell.reason }}</div><template v-if="tradeDetailData.sell.decision_detail"><div class="td-c">决策链路:</div><div v-for="(line, i) in formatDecisionDetail(tradeDetailData.sell.decision_detail)" :key="i" class="cl">{{ line }}</div></template></template><div v-else class="td-e">无卖出记录</div></div>
        <div class="td-sec" v-if="tradeDetailData.position"><div class="td-t">📊 当前持仓</div><div class="td-g"><div class="td-i"><span class="td-l">持仓</span><span class="td-v">{{ tradeDetailData.position.shares }}股</span></div><div class="td-i"><span class="td-l">成本</span><span class="td-v">{{ tradeDetailData.position.cost_price?.toFixed(2) }}</span></div><div class="td-i"><span class="td-l">现价</span><span class="td-v">{{ tradeDetailData.position.current_price?.toFixed(2) }}</span></div><div class="td-i"><span class="td-l">盈亏</span><span class="td-v" :class="tradeDetailData.position.profit_pct >= 0 ? 'up' : 'down'">{{ tradeDetailData.position.profit_pct >= 0 ? '+' : '' }}{{ tradeDetailData.position.profit_pct?.toFixed(2) }}%</span></div></div></div>
      </div>
      <div v-else class="empty">无数据</div>
    </ElDialog>

    <!-- 审查弹窗 -->
    <ElDialog v-model="tradeAuditVisible" title="🔍 全部交易审查" width="800px">
      <div v-if="tradeAuditData.length" class="al"><div class="ah"><span>股票</span><span>策略</span><span>买入</span><span>卖出</span><span>盈亏</span><span>状态</span></div><div v-for="t in tradeAuditData" :key="t.ts_code" class="ar" @click="openTradeDetail(t.ts_code); tradeAuditVisible = false"><span class="code">{{ t.ts_code }}</span><span><ElTag size="small" type="info">{{ strategyCN(t.strategy) }}</ElTag></span><span>{{ t.buy_time }} {{ t.buy_price?.toFixed(2) }}</span><span>{{ t.sell_time || '-' }} {{ t.sell_price?.toFixed(2) || '-' }}</span><span :class="t.profit_pct !== null && t.profit_pct >= 0 ? 'up' : 'down'">{{ t.profit_pct !== null ? (t.profit_pct >= 0 ? '+' : '') + t.profit_pct.toFixed(2) + '%' : '-' }}</span><span class="text-tertiary-sm">{{ t.status }}</span></div></div>
      <div v-else class="empty">暂无交易记录</div>
    </ElDialog>
    <!-- 回测对比弹窗 -->
    <ElDialog v-model="compareVisible" title="📊 实盘 vs 回测对比" width="700px">
      <div v-if="compareData.length" class="cl-table">
        <div class="cl-h"><span>策略</span><span>实盘交易</span><span>实盘胜率</span><span>实盘盈亏</span><span>回测收益</span><span>回测胜率</span><span>回测回撤</span><span>回测夏普</span></div>
        <div v-for="c in compareData" :key="c.strategy" class="cl-r">
          <span class="code">{{ strategyCN(c.strategy) }}</span>
          <span>{{ c.live_trades }}笔</span>
          <span :class="c.live_win_rate >= 50 ? 'up' : 'down'">{{ c.live_win_rate }}%</span>
          <span :class="c.live_pnl >= 0 ? 'up' : 'down'">{{ c.live_pnl >= 0 ? '+' : '' }}{{ c.live_pnl.toFixed(0) }}</span>
          <span :class="c.bt_return >= 0 ? 'up' : 'down'">{{ c.bt_return }}%</span>
          <span>{{ c.bt_win_rate }}%</span>
          <span class="text-stock-up">{{ c.bt_drawdown }}%</span>
          <span>{{ c.bt_sharpe }}</span>
        </div>
      </div>
      <div v-else class="empty">暂无对比数据（需先运行回测）</div>
    </ElDialog>

    <!-- 【调试增强】9层筛选调试弹窗 -->
    <ElDialog v-model="layerDebugVisible" title="🧪 9层筛选管道调试" width="750px">
      <div v-if="layerDebugData" class="layer-debug">
        <div class="ld-header">
          <ElTag :type="layerDebugData.dry_run ? 'warning' : 'success'" size="small">{{ layerDebugData.dry_run ? '🔍调试模式' : '正常交易' }}</ElTag>
          <span>信号: {{ layerDebugData.total_signals }} | 已执行: {{ layerDebugData.executed_signals }} | 跳过: {{ layerDebugData.skipped_signals }} | 过期: {{ layerDebugData.expired_signals }}</span>
        </div>
        <div v-if="layerDebugData.pipeline_config" class="ld-pipeline">
          <div class="ld-title">管道配置</div>
          <div class="ld-layers">
            <div v-for="(enabled, layer) in layerDebugData.pipeline_config.layer_enabled" :key="layer" class="ld-layer">
              <span :class="enabled ? 'ld-on' : 'ld-off'">{{ enabled ? '✅' : '⏭️' }}</span>
              <span class="ld-name">{{ layerLabel(layer) }}</span>
            </div>
          </div>
          <div class="ld-sentiment" v-if="layerDebugData.pipeline_config.sentiment">
            情绪: {{ layerDebugData.pipeline_config.sentiment.score }} → {{ layerDebugData.pipeline_config.sentiment.period }} | 仓位系数: {{ (layerDebugData.pipeline_config.position_ratio * 100).toFixed(0) }}%
          </div>
        </div>
        <div v-if="layerDebugData.signal_traces?.length" class="ld-traces">
          <div class="ld-title">信号逐层链路</div>
          <div v-for="trace in layerDebugData.signal_traces" :key="trace.ts_code + trace.strategy" class="ld-trace-card">
            <div class="ld-trace-top"><span class="code">{{ trace.ts_code }}</span><span class="name">{{ trace.stock_name }}</span><ElTag size="small" type="info">{{ strategyCN(trace.strategy) }}</ElTag><ElTag size="small" :type="signalStatusTag(trace.signal_status).type">{{ signalStatusTag(trace.signal_status).text }}</ElTag></div>
            <div class="ld-trace-layers">
              <div v-for="(line, i) in formatLayerTrace(trace.layer_trace)" :key="i" class="ld-trace-line">{{ line }}</div>
            </div>
          </div>
        </div>
        <div v-else class="empty">暂无信号链路数据</div>
      </div>
      <div v-else class="empty">加载中...</div>
    </ElDialog>

    <!-- 单只股票扫描链路弹窗 -->
    <ElDialog v-model="scanTraceVisible" title="🧪 扫描链路 — {{ scanTraceCode }}" width="700px">
      <div v-if="scanTraceData" class="scan-trace">
        <div v-if="scanTraceData.status === 'not_found'" class="empty">{{ scanTraceData.message }}</div>
        <div v-else>
          <div class="st-header">
            <span class="code">{{ scanTraceData.ts_code }}</span>
            <span class="name">{{ scanTraceData.stock_name }}</span>
            <ElTag size="small" :type="signalStatusTag(scanTraceData.signal_status).type">{{ signalStatusTag(scanTraceData.signal_status).text }}</ElTag>
            <span :class="scanTraceData.pct_chg >= 0 ? 'up' : 'down'" style="font-weight:600">{{ scanTraceData.pct_chg >= 0 ? '+' : '' }}{{ scanTraceData.pct_chg?.toFixed(1) }}%</span>
          </div>
          <div class="st-reason">{{ scanTraceData.reason }}</div>
          <div v-if="scanTraceData.age_seconds" class="st-age">信号年龄: {{ scanTraceData.age_seconds }}秒</div>
          <div v-if="scanTraceData.layer_trace" class="st-trace">
            <div class="st-title">逐层筛选链路</div>
            <div v-for="(line, i) in formatLayerTrace(scanTraceData.layer_trace)" :key="i" class="st-line">{{ line }}</div>
          </div>
          <div v-if="scanTraceData.decision_detail" class="st-detail">
            <div class="st-title">决策详情</div>
            <div v-for="(line, i) in formatDecisionDetail(scanTraceData.decision_detail)" :key="i" class="st-line">{{ line }}</div>
          </div>
          <div v-if="scanTraceData.factors" class="st-factors">
            <div class="st-title">关键因子</div>
            <div class="st-fg">
              <div v-for="(v, k) in scanTraceData.factors" :key="k" class="st-fi"><span class="st-fl">{{ factorLabel(k) }}</span><span class="st-fv">{{ typeof v === 'number' ? v.toFixed(2) : v }}</span></div>
            </div>
          </div>
        </div>
      </div>
      <div v-else class="empty">加载中...</div>
    </ElDialog>
    <!-- 【P1-7】交易确认弹窗 -->
    <ElDialog v-model="confirmVisible" :title="confirmData.title" width="420px" :close-on-click-modal="false">
      <div style="font-size:14px;line-height:1.8;white-space:pre-line">{{ confirmData.message }}</div>
      <template #footer><ElButton @click="confirmVisible = false" :disabled="confirmLoading">取消</ElButton><ElButton type="danger" :loading="confirmLoading" @click="handleConfirm">确认执行</ElButton></template>
    </ElDialog>

    <!-- 【P1-6】复盘报告弹窗 -->
    <ElDialog v-model="dailyReportVisible" title="📈 每日复盘报告" width="750px">
      <div v-if="dailyReport" class="dr">
        <div class="dr-sec"><div class="dr-t">💰 账户概览</div><div class="dr-g"><div class="dr-i"><span class="dr-l">总资产</span><span class="dr-v">{{ (dailyReport.account.total_assets / 10000).toFixed(1) }}万</span></div><div class="dr-i"><span class="dr-l">可用</span><span class="dr-v">{{ (dailyReport.account.available_cash / 10000).toFixed(1) }}万</span></div><div class="dr-i"><span class="dr-l">仓位</span><span class="dr-v">{{ dailyReport.account.position_ratio }}%</span></div><div class="dr-i"><span class="dr-l">今日盈亏</span><span class="dr-v" :class="dailyReport.account.today_profit >= 0 ? 'up' : 'down'">{{ dailyReport.account.today_profit >= 0 ? '+' : '' }}{{ dailyReport.account.today_profit.toFixed(0) }}</span></div></div></div>
        <div class="dr-sec"><div class="dr-t">📊 持仓概况</div><div class="dr-g"><div class="dr-i"><span class="dr-l">持仓数</span><span class="dr-v">{{ dailyReport.positions.count }}</span></div><div class="dr-i"><span class="dr-l">止损</span><span class="dr-v text-stock-up">{{ dailyReport.stop_loss_count }}</span></div><div class="dr-i"><span class="dr-l">止盈</span><span class="dr-v text-stock-down">{{ dailyReport.take_profit_count }}</span></div><div class="dr-i"><span class="dr-l">胜率</span><span class="dr-v">{{ dailyReport.win_rate }}%</span></div></div></div>
        <div class="dr-sec" v-if="dailyReport.positions.top_profit?.length"><div class="dr-t">🏆 最赚</div><div v-for="p in dailyReport.positions.top_profit" class="dr-p"><span class="code">{{ p.ts_code }}</span><span>{{ p.name }}</span><span class="up">+{{ p.pct }}%</span></div></div>
        <div class="dr-sec" v-if="dailyReport.positions.top_loss?.length"><div class="dr-t">💀 最亏</div><div v-for="p in dailyReport.positions.top_loss" class="dr-p"><span class="code">{{ p.ts_code }}</span><span>{{ p.name }}</span><span class="down">{{ p.pct }}%</span></div></div>
        <div class="dr-sec" v-if="dailyReport.positions.strategy_summary"><div class="dr-t">📋 策略汇总</div><div v-for="(s, k) in dailyReport.positions.strategy_summary" class="dr-p"><span>{{ strategyCN(k) }}</span><span>{{ s.count }}只</span><span :class="s.total_pnl >= 0 ? 'up' : 'down'">¥{{ s.total_pnl >= 0 ? '+' : '' }}{{ s.total_pnl.toFixed(0) }}</span></div></div>
      </div>
      <div v-else class="empty">暂无复盘数据</div>
    </ElDialog>

    <!-- 周报弹窗 -->
    <ElDialog v-model="weeklyReportVisible" title="📊 周报 — 最近5个交易日" width="800px">
      <div v-if="weeklyReportData" class="wr">
        <div class="wr-sec"><div class="wr-t">💰 账户状态</div><div class="wr-g"><div class="wr-i"><span class="wr-l">总资产</span><span class="wr-v">{{ (weeklyReportData.account?.total_assets / 10000 || 0).toFixed(1) }}万</span></div><div class="wr-i"><span class="wr-l">累计盈亏</span><span class="wr-v" :class="weeklyReportData.account?.total_profit >= 0 ? 'up' : 'down'">{{ weeklyReportData.account?.total_profit >= 0 ? '+' : '' }}{{ (weeklyReportData.account?.total_profit || 0).toFixed(0) }}</span></div><div class="wr-i"><span class="wr-l">可用现金</span><span class="wr-v">{{ (weeklyReportData.account?.available_cash / 10000 || 0).toFixed(1) }}万</span></div></div></div>
        <div class="wr-sec"><div class="wr-t">📈 交易统计</div><div class="wr-g"><div class="wr-i"><span class="wr-l">交易日</span><span class="wr-v">{{ weeklyReportData.totals?.trading_days || 0 }}天</span></div><div class="wr-i"><span class="wr-l">买入</span><span class="wr-v">{{ weeklyReportData.totals?.total_buys || 0 }}笔</span></div><div class="wr-i"><span class="wr-l">卖出</span><span class="wr-v">{{ weeklyReportData.totals?.total_sells || 0 }}笔</span></div><div class="wr-i"><span class="wr-l">净流入</span><span class="wr-v" :class="weeklyReportData.totals?.net_flow >= 0 ? 'up' : 'down'">{{ (weeklyReportData.totals?.net_flow || 0).toFixed(0) }}</span></div></div></div>
        <div class="wr-sec" v-if="weeklyReportData.strategy_summary"><div class="wr-t">📋 策略汇总</div><div v-for="(s, k) in weeklyReportData.strategy_summary" class="dr-p"><span>{{ strategyCN(k) }}</span><span>{{ s.trades }}笔</span><span :class="s.amount >= 0 ? 'up' : 'down'">¥{{ s.amount >= 0 ? '+' : '' }}{{ s.amount.toFixed(0) }}</span></div></div>
        <div class="wr-sec" v-if="weeklyReportData.daily_stats"><div class="wr-t">📅 每日明细</div><div v-for="(stats, date) in weeklyReportData.daily_stats" class="wr-day"><span class="wr-date">{{ date }}</span><span>买{{ stats.buys }}卖{{ stats.sells }}</span><span :class="stats.sell_amount - stats.buy_amount >= 0 ? 'up' : 'down'">¥{{ (stats.sell_amount - stats.buy_amount).toFixed(0) }}</span></div></div>
      </div>
      <div v-else class="empty">暂无周报数据</div>
    </ElDialog>
  </div>
</template>
<style scoped lang="scss">
.mm { height: 100%; display: flex; flex-direction: column; background: var(--bg-base); overflow: hidden; min-width: 0; }
/* 顶部状态栏 */
.mm-header { display: flex; align-items: center; gap: 12px; padding: 8px 16px; background: var(--bg-elevated); border-bottom: 1px solid var(--border-default); flex-shrink: 0; flex-wrap: wrap; min-width: 0; }
.hh-left { display: flex; align-items: center; gap: 6px; flex-shrink: 0; flex-wrap: wrap; }
.hh-status { display: flex; align-items: center; gap: 5px; font-weight: 600; font-size: 13px; }
.hh-status .dot { width: 8px; height: 8px; border-radius: 50%; }
.hh-status.running .dot { background: var(--stock-down); animation: pulse 1.5s infinite; }
.hh-status.stopped .dot { background: var(--text-tertiary); }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
.hh-account { display: flex; gap: 14px; flex: 1 1 auto; min-width: 0; flex-wrap: wrap; }
.ha { display: flex; flex-direction: column; min-width: 0; }
.hl { font-size: 10px; color: var(--text-tertiary); }
.hv { font-size: 13px; font-weight: 600; }
.hh-actions { display: flex; align-items: center; gap: 6px; flex-shrink: 0; flex-wrap: wrap; }
.up { color: var(--stock-up); }
.down { color: var(--stock-down); }

/* 引导页 */
.mm-guide { flex: 1; display: flex; align-items: center; justify-content: center; }
.guide-card { text-align: center; padding: 40px; background: var(--bg-elevated); border-radius: 12px; box-shadow: var(--shadow-md); }
.guide-icon { font-size: 48px; margin-bottom: 12px; }
.guide-title { font-size: 20px; font-weight: 600; margin-bottom: 20px; }
.guide-steps { text-align: left; display: inline-block; }
.guide-step { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; font-size: 14px; }
.sn { display: inline-flex; align-items: center; justify-content: center; width: 24px; height: 24px; border-radius: 50%; background: var(--el-color-primary); color: var(--text-inverse); font-size: 12px; font-weight: 600; flex-shrink: 0; }

/* 3列主布局 */
.mm-body { flex: 1; display: grid; grid-template-columns: minmax(180px, 2fr) minmax(200px, 3fr) minmax(300px, 5fr); gap: 0; overflow: hidden; min-width: 0; }
.mm-left, .mm-center, .mm-right { overflow-y: auto; padding: 10px; min-width: 0; min-height: 0; }
.mm-left { background: var(--bg-secondary); border-right: 1px solid var(--border-default); }
.mm-right { background: var(--bg-secondary); border-left: 1px solid var(--border-default); }

/* 区域标题 */
.st { font-size: 13px; font-weight: 600; color: var(--text-primary); margin-bottom: 8px; display: flex; align-items: center; }

/* 策略卡片 */
.sc { padding: 8px 10px; margin-bottom: 6px; background: var(--bg-elevated); border-radius: 6px; border: 1px solid var(--border-default); transition: border-color 0.2s; min-width: 0; }
.sc:hover { border-color: var(--text-muted); }
.sc.disabled { opacity: 0.5; }
.sc-top { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; min-width: 0; }
.sc-icon { font-size: 16px; }
.sc-name { font-size: 13px; font-weight: 600; flex: 1 1 auto; min-width: 0; }
.sc-arrow { font-size: 10px; color: var(--text-tertiary); margin-left: 4px; }
.sc-desc { font-size: 11px; color: var(--text-tertiary); margin: 2px 0 4px 24px; overflow-wrap: break-word; }
.sc-params { margin-left: 24px; min-width: 0; }
.pm { display: flex; justify-content: space-between; font-size: 11px; gap: 4px; min-width: 0; }
.pk { color: var(--text-tertiary); white-space: nowrap; }
.pv { color: var(--text-secondary); font-weight: 500; overflow-wrap: break-word; }

/* 快捷操作 */
.qa { display: flex; flex-direction: column; gap: 4px; min-width: 0; }

/* 手动下单 */
.mf { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.mf-row { display: flex; gap: 4px; min-width: 0; flex-wrap: wrap; }
.mf-q { font-size: 11px; color: var(--stock-down); padding: 2px 0; }
.mf-hint { font-size: 11px; color: var(--el-color-primary); cursor: pointer; padding: 0 4px; white-space: nowrap; }

/* 信号列表 */
.sl { overflow-y: auto; min-width: 0; }
.sl-sm { max-height: 200px; }
.sig-row { display: flex; align-items: center; gap: 5px; padding: 4px 8px; margin-bottom: 2px; background: var(--bg-elevated); border-radius: 4px; border: 1px solid var(--border-default); font-size: 12px; flex-wrap: wrap; min-width: 0; }
.sig-row:hover { border-color: var(--el-color-primary); }
.factor { font-size: 11px; color: var(--text-tertiary); background: var(--bg-tertiary); padding: 1px 4px; border-radius: 3px; white-space: nowrap; }
.reason { font-size: 11px; color: var(--text-tertiary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 200px; min-width: 0; }
.sig-row .el-button { padding: 1px 6px; font-size: 11px; }

/* 涨停池 */
.limit-row { display: flex; align-items: center; gap: 6px; padding: 3px 8px; font-size: 12px; border-bottom: 1px solid var(--border-light); flex-wrap: wrap; min-width: 0; }
.lb-tag { font-size: 10px; color: var(--stock-up); background: var(--stock-up-bg); padding: 1px 4px; border-radius: 3px; }
.fd-tag { font-size: 10px; color: var(--el-color-warning); background: var(--warning-bg); padding: 1px 4px; border-radius: 3px; }

/* 持仓卡片 */
.pos-card { padding: 8px 10px; margin-bottom: 6px; background: var(--bg-elevated); border-radius: 6px; border: 1px solid var(--border-default); min-width: 0; }
.pos-card:hover { border-color: var(--el-color-primary); }
.pos-top { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; min-width: 0; }
.pct { margin-left: auto; font-weight: 700; font-size: 14px; transition: transform 0.3s; }
.pos-card:hover .pct { transform: scale(1.05); }
.pos-info { display: flex; gap: 8px; font-size: 11px; color: var(--text-secondary); flex-wrap: wrap; min-width: 0; }
.t1-tag { font-size: 10px; color: var(--el-color-warning); background: var(--warning-bg); padding: 1px 4px; border-radius: 3px; font-weight: 600; }
.rl { padding: 1px 5px; border-radius: 3px; font-weight: 500; }
.rl.stop { color: var(--stock-up); background: var(--stock-up-bg); }
.rl.stop-price { color: var(--stock-up); background: var(--stock-up-bg); font-weight: 700; }
.rl.profit { color: var(--stock-down); background: var(--stock-down-bg); }
.rl.profit-price { color: var(--stock-down); background: var(--stock-down-bg); font-weight: 700; }
.rd { color: var(--text-tertiary); }
.rd.danger { color: var(--stock-up); font-weight: 600; animation: blink 1s infinite; }
@keyframes blink { 50% { opacity: 0.5; } }

/* 统计 */
.stats { display: grid; grid-template-columns: repeat(auto-fill, minmax(60px, 1fr)); gap: 6px; }
.si { text-align: center; padding: 6px; background: var(--bg-elevated); border-radius: 6px; min-width: 0; }
.sv { font-size: 18px; font-weight: 700; }
.sl2 { font-size: 11px; color: var(--text-tertiary); }

/* 底部时间线 */
.mm-footer { flex-shrink: 0; border-top: 1px solid var(--border-default); padding: 6px 16px; background: var(--bg-elevated); min-width: 0; }
.tl-body { display: flex; gap: 16px; flex-wrap: wrap; min-width: 0; }
.tl-col { flex: 1 1 200px; overflow-y: auto; max-height: 260px; min-width: 0; }
.tl-col + .tl-col { border-left: 1px solid var(--border-default); padding-left: 16px; }
.tl-row { display: flex; align-items: center; gap: 6px; padding: 3px 0; font-size: 12px; border-bottom: 1px solid var(--border-light); cursor: pointer; flex-wrap: wrap; min-width: 0; }
.tl-row:hover { background: var(--bg-base); }
.tl-time { font-size: 11px; color: var(--text-tertiary); min-width: 40px; }
.tl-action { font-size: 11px; font-weight: 600; min-width: 20px; }
.tl-action.buy { color: var(--stock-up); }
.tl-action.sell { color: var(--stock-down); }
.tl-detail { font-size: 11px; color: var(--text-secondary); }
.tl-reason { font-size: 11px; color: var(--text-tertiary); max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.history-tag { font-size: 12px; color: var(--el-color-primary); background: var(--info-bg); padding: 4px 8px; border-radius: 4px; margin-bottom: 4px; font-weight: 600; }

/* 通用 */
.code { font-size: 12px; font-weight: 600; color: var(--text-primary); font-family: monospace; }
.name { font-size: 12px; color: var(--text-secondary); }
.empty { text-align: center; color: var(--text-muted); font-size: 12px; padding: 20px 0; }

/* 【P1-1】关键因子标签 */
.kf { color: var(--el-color-warning); background: var(--warning-bg); font-weight: 600; }

/* 【P1-2】持仓市值和盈亏金额 */
.mv { color: var(--text-tertiary); font-size: 11px; }
.pamt { font-weight: 700; font-size: 12px; }

/* 【P1-5】数据源健康指示器 */
.ds-indicator { display: inline-flex; gap: 4px; margin-left: 4px; }
.ds-dot { font-size: 10px; padding: 1px 4px; border-radius: 3px; font-weight: 600; cursor: help; }
.ds-dot.ok { color: var(--stock-down); background: var(--stock-down-bg); }
.ds-dot.err { color: var(--stock-up); background: var(--stock-up-bg); }

/* 【P1-3】时间线盈亏金额 */
.tl-amt { font-size: 11px; font-weight: 700; min-width: 50px; text-align: right; }

/* 交易详情弹窗 */
.td { font-size: 13px; }
.td-sec { margin-bottom: 14px; padding: 10px; background: var(--bg-muted); border-radius: 8px; border: 1px solid var(--border-default); min-width: 0; }
.td-t { font-size: 14px; font-weight: 600; margin-bottom: 6px; color: var(--text-primary); }
.td-g { display: grid; grid-template-columns: repeat(auto-fill, minmax(100px, 1fr)); gap: 6px; margin-bottom: 4px; }
.td-i { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.td-l { font-size: 10px; color: var(--text-tertiary); }
.td-v { font-size: 13px; font-weight: 500; }
.td-r { font-size: 12px; color: var(--text-secondary); margin: 4px 0; padding: 4px 6px; background: var(--bg-elevated); border-radius: 4px; border-left: 3px solid var(--el-color-primary); }
.td-c { font-size: 12px; font-weight: 600; color: var(--text-secondary); margin-top: 4px; }
.cl { font-size: 11px; color: var(--text-secondary); padding: 1px 0 1px 10px; font-family: monospace; }
.td-e { color: var(--text-muted); font-size: 12px; }

/* 审查弹窗 */
.al { max-height: 500px; overflow-y: auto; }
.ah { display: grid; grid-template-columns: minmax(60px, 1fr) minmax(50px, 1fr) minmax(80px, 1.2fr) minmax(80px, 1.2fr) minmax(50px, 1fr) minmax(50px, 1fr); gap: 4px; padding: 6px 0; font-size: 12px; font-weight: 600; color: var(--text-tertiary); border-bottom: 1px solid var(--border-default); }
.ar { display: grid; grid-template-columns: minmax(60px, 1fr) minmax(50px, 1fr) minmax(80px, 1.2fr) minmax(80px, 1.2fr) minmax(50px, 1fr) minmax(50px, 1fr); gap: 4px; padding: 6px 0; font-size: 12px; align-items: center; border-bottom: 1px solid var(--border-light); cursor: pointer; overflow: hidden; }
.ar:hover { background: var(--bg-hover); }

/* 回测对比 */
.cl-table { max-height: 400px; overflow-y: auto; }
.cl-h { display: grid; grid-template-columns: repeat(8, minmax(50px, 1fr)); gap: 4px; padding: 6px 0; font-size: 12px; font-weight: 600; color: var(--text-tertiary); border-bottom: 1px solid var(--border-default); }
.cl-r { display: grid; grid-template-columns: repeat(8, minmax(50px, 1fr)); gap: 4px; padding: 6px 0; font-size: 12px; align-items: center; border-bottom: 1px solid var(--border-light); overflow: hidden; }

/* 响应式 */
@media (max-width: 1400px) {
  .mm-body { grid-template-columns: minmax(160px, 2fr) minmax(180px, 3fr) minmax(280px, 4fr); }
  .pos-info { flex-wrap: wrap; gap: 4px; }
  .tl-body { flex-wrap: wrap; }
  .tl-col { min-width: 180px; }
}
@media (max-width: 1024px) {
  .mm-body { grid-template-columns: 1fr; }
  .mm-left, .mm-right { border: none; border-bottom: 1px solid var(--border-default); }
  .tl-body { flex-direction: column; }
  .tl-col { max-height: 180px; }
  .tl-col + .tl-col { border-left: none; padding-left: 0; border-top: 1px solid var(--border-default); padding-top: 8px; }
}
@media (max-width: 1024px) {
  }

/* 【调试增强】9层调试弹窗 */
.layer-debug { font-size: 13px; }
.ld-header { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; font-size: 12px; color: var(--text-secondary); }
.ld-title { font-size: 13px; font-weight: 600; color: var(--text-primary); margin-bottom: 6px; }
.ld-pipeline { padding: 10px; background: var(--bg-muted); border-radius: 8px; border: 1px solid var(--border-default); margin-bottom: 10px; }
.ld-layers { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 4px; margin-bottom: 6px; }
.ld-layer { display: flex; align-items: center; gap: 4px; font-size: 11px; padding: 3px 6px; background: var(--bg-elevated); border-radius: 4px; border: 1px solid var(--border-default); }
.ld-on { color: var(--stock-down); }
.ld-off { color: var(--text-tertiary); }
.ld-name { color: var(--text-secondary); }
.ld-sentiment { font-size: 12px; color: var(--el-color-primary); padding: 4px 0; }
.ld-traces { max-height: 400px; overflow-y: auto; }
.ld-trace-card { padding: 8px 10px; margin-bottom: 6px; background: var(--bg-elevated); border-radius: 6px; border: 1px solid var(--border-default); }
.ld-trace-top { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
.ld-trace-layers { padding-left: 10px; }
.ld-trace-line { font-size: 11px; color: var(--text-secondary); padding: 1px 0; font-family: monospace; }

/* 【调试增强】扫描Trace弹窗 */
.scan-trace { font-size: 13px; }
.st-header { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
.st-reason { font-size: 12px; color: var(--text-secondary); padding: 4px 6px; background: var(--bg-elevated); border-radius: 4px; border-left: 3px solid var(--el-color-primary); margin-bottom: 6px; }
.st-age { font-size: 11px; color: var(--text-tertiary); margin-bottom: 6px; }
.st-trace, .st-detail, .st-factors { padding: 10px; background: var(--bg-muted); border-radius: 8px; border: 1px solid var(--border-default); margin-bottom: 8px; }
.st-title { font-size: 13px; font-weight: 600; color: var(--text-primary); margin-bottom: 4px; }
.st-line { font-size: 11px; color: var(--text-secondary); padding: 1px 0; font-family: monospace; }
.st-fg { display: grid; grid-template-columns: repeat(auto-fill, minmax(100px, 1fr)); gap: 4px; }
.st-fi { display: flex; flex-direction: column; padding: 3px 6px; background: var(--bg-elevated); border-radius: 4px; }
.st-fl { font-size: 10px; color: var(--text-tertiary); }
.st-fv { font-size: 13px; font-weight: 500; }

/* 【P1-4】信号过期倒计时 */
.expire-tag { font-size: 11px; color: var(--el-color-primary); background: var(--info-bg); padding: 1px 5px; border-radius: 3px; font-weight: 600; }
.expire-tag.urgent { color: var(--stock-up); background: var(--stock-up-bg); animation: blink 1s infinite; }

/* 【P1-6】复盘报告弹窗 */
.dr { font-size: 13px; }
.dr-sec { margin-bottom: 14px; padding: 10px; background: var(--bg-muted); border-radius: 8px; border: 1px solid var(--border-default); }
.dr-t { font-size: 14px; font-weight: 600; margin-bottom: 6px; color: var(--text-primary); }
.dr-g { display: grid; grid-template-columns: repeat(auto-fill, minmax(100px, 1fr)); gap: 6px; margin-bottom: 4px; }
.dr-i { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.dr-l { font-size: 10px; color: var(--text-tertiary); }
.dr-v { font-size: 13px; font-weight: 500; }
.dr-p { display: flex; align-items: center; gap: 8px; padding: 3px 0; font-size: 12px; border-bottom: 1px solid var(--border-light); }

/* 周报弹窗 */
.wr { font-size: 13px; }
.wr-sec { margin-bottom: 14px; padding: 10px; background: var(--bg-muted); border-radius: 8px; border: 1px solid var(--border-default); }
.wr-t { font-size: 14px; font-weight: 600; margin-bottom: 6px; color: var(--text-primary); }
.wr-g { display: grid; grid-template-columns: repeat(auto-fill, minmax(100px, 1fr)); gap: 6px; margin-bottom: 4px; }
.wr-i { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.wr-l { font-size: 10px; color: var(--text-tertiary); }
.wr-v { font-size: 14px; font-weight: 600; }
.wr-p { display: flex; align-items: center; gap: 8px; padding: 3px 0; font-size: 12px; border-bottom: 1px solid var(--border-light); }
.wr-day { display: flex; align-items: center; gap: 10px; padding: 4px 0; font-size: 12px; border-bottom: 1px solid var(--border-light); }
.wr-date { font-weight: 600; color: var(--text-primary); min-width: 80px; }

/* === Extracted utility classes === */
.w-full { width: 100%; }
.ml-auto { margin-left: auto; }
.mt-10 { margin-top: 10px; }
.cp { cursor: pointer; }
.btn-xs { padding: 1px 6px; font-size: 11px; }
.tag-solid { color: var(--text-inverse); border: none; }
.fs-10 { font-size: 10px; }

/* === Dark toggle button === */
.dark-toggle { font-size: 16px; cursor: pointer; padding: 0 4px; user-select: none; }

/* === Mini bar (PnL progress) === */
.mini-bar { display: inline-block; width: 40px; height: 4px; background: var(--border-default); border-radius: 2px; vertical-align: middle; margin-left: 4px; }
.mini-bar-fill { display: block; height: 100%; border-radius: 2px; transition: width 0.3s; }

/* === Quick action groups === */
.qa-group { margin-bottom: 2px; }
.qa-label { font-size: 10px; color: var(--text-tertiary); margin-top: 4px; margin-bottom: 2px; padding-left: 2px; }


/* === Utility classes for inline style replacement === */
.text-stock-up { color: var(--stock-up) !important; }
.text-stock-down { color: var(--stock-down) !important; }
.text-tertiary { color: var(--text-tertiary); }
.text-tertiary-sm { font-size: 11px; color: var(--text-tertiary); }

/* === Mini bar fill variants === */
.mini-bar-fill.bar-up { background: var(--stock-up) !important; }
.mini-bar-fill.bar-down { background: var(--stock-down) !important; }

/* ============================================ */
</style>
