<script setup lang="ts">
/**
 * MarketMonitorView — 超短量化实盘监控 (3列布局)
 * 左: 策略控制+快捷操作 / 中: 信号+行情 / 右: 持仓+统计
 * 底: 时间线 / 顶: 状态栏
 */
import { ref, computed, onMounted, onUnmounted, reactive } from 'vue'
import {
  ElCard, ElButton, ElTag, ElEmpty, ElTable, ElTableColumn,
  ElSwitch, ElInputNumber, ElSlider, ElDescriptions, ElDescriptionsItem,
  ElTabs, ElTabPane, ElDialog, ElMessage, ElTooltip, ElBadge,
  ElInput, ElSelect, ElOption,
} from 'element-plus'
import { api } from '@/api/client'

interface ScanStats { scans: number; signals_found: number; trades_executed: number; stop_losses: number; take_profits: number; stocks_scanned: number }
interface ScannerStatus { is_running: boolean; scan_count: number; last_scan_time: string; active_signals: number; positions: number; stocks_scanned: number; stats: ScanStats; account_id: string; trade_mode: string; circuit_breaker_paused?: boolean; circuit_breaker?: { trading_paused: boolean; pause_reason: string }; account: { total_assets: number; available_cash: number; market_value: number; total_profit: number } }
interface ScanSignal { ts_code: string; stock_name: string; strategy: string; strategy_name: string; signal_type: string; price: number; pct_chg: number; volume_ratio: number; turnover_rate: number; is_limit_up: boolean; limit_up_count: number; confidence: number; reason: string; scan_time: string; factors: Record<string, number>; decision_detail?: Record<string, any>; signal_status?: string; layer_trace?: Record<string, any>; created_at?: number }
interface PositionInfo { ts_code: string; stock_name: string; strategy: string; shares: number; available_qty: number; cost_price: number; current_price: number; profit_pct: number; today_buy: number; stop_loss_pct?: number; take_profit_pct?: number }
interface TimelineItem { time: string; action: string; ts_code: string; stock_name: string; strategy: string; shares: number; price: number; reason: string; profit_pct?: number; decision_detail?: Record<string, any> }
interface StrategyConfig { id: string; name: string; enabled: boolean; params: Record<string, any>; riskParams: Record<string, any>; paramDescriptions: ParamDesc[]; riskDescriptions: ParamDesc[] }
interface ParamDesc { key: string; label: string; value: any; displayValue: string; unit: string; min: number; max: number; step: number }
interface GlobalRisk { stop_loss_pct: number; take_profit_pct: number; max_position_pct: number; max_positions: number }

const loading = ref(false), autoRefresh = ref(true)
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
const strategyMeta: Record<string, { color: string; icon: string; desc: string }> = {
  halfway_chase: { color: '#e6a23c', icon: '🚀', desc: '盘中冲高2-7%+量能放大' },
  first_limit_up: { color: '#f56c6c', icon: '🔥', desc: '首板涨停封板强' },
  dragon_head: { color: '#409eff', icon: '🐉', desc: '连板龙头回调低吸' },
  limit_down_qiao: { color: '#67c23a', icon: '💪', desc: '跌停撬板反弹' },
  limit_up_open: { color: '#909399', icon: '🔓', desc: '涨停炸板回封' },
  anomaly_surge: { color: '#e6a23c', icon: '⚡', desc: '5分钟急速拉升' },
  anomaly_broken: { color: '#f56c6c', icon: '💔', desc: '涨停炸板' },
  anomaly_strong: { color: '#409eff', icon: '💪', desc: '强势涨停确认' },
}
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

async function openTradeDetail(ts_code: string) { try { const r = await api.get(`${scannerApi}/trade-detail/${ts_code}`); if (r?.success) { tradeDetailData.value = r.data; tradeDetailVisible.value = true } } catch (e: any) { ElMessage.error('获取详情失败') } }
async function openTradeAudit() { try { const r = await api.get(`${scannerApi}/trade-audit`); if (r?.success) { tradeAuditData.value = r.data; tradeAuditVisible.value = true } } catch (e: any) { ElMessage.error('获取审查失败') } }
function formatDecisionDetail(detail: any): string[] {
  if (!detail) return ['无决策详情']; const lines: string[] = []
  if (detail.filter_pipeline) { const fp = detail.filter_pipeline; lines.push('【9层筛选管道】'); for (const [l, a] of Object.entries(fp.layers_applied || {})) { lines.push(`  ${a ? '✅' : '⏭️'} ${l}: ${fp.layer_details?.[l] || (a ? '生效' : '跳过')}`) }; lines.push(`  仓位系数: ${fp.position_ratio || 'N/A'}`) }
  if (detail.factors) { lines.push('【关键因子】'); for (const [k, v] of Object.entries(detail.factors)) { if (v !== 0 && v !== null) lines.push(`  ${k}: ${typeof v === 'number' ? v.toFixed(2) : v}`) } }
  if (detail.sell_reason) { lines.push('【卖出决策】'); lines.push(`  原因: ${detail.sell_reason}`); if (detail.profit_pct) lines.push(`  盈亏: ${detail.profit_pct.toFixed(2)}%`); if (detail.stop_loss_pct) lines.push(`  止损线: ${detail.stop_loss_pct}%`); if (detail.take_profit_pct) lines.push(`  止盈线: ${detail.take_profit_pct}%`) }
  return lines
}
async function quickBuy(sig: ScanSignal) { const a = status.value?.account; if (!a) { ElMessage.warning('请先启动'); return } const q = Math.floor(a.available_cash * 0.25 / sig.price / 100) * 100; if (q <= 0) { ElMessage.warning('资金不足'); return } try { const r = await api.post(`${scannerApi}/trade`, { ts_code: sig.ts_code, stock_name: sig.stock_name, side: 'buy', quantity: q, price: sig.price, order_type: 'market', strategy: sig.strategy, reason: sig.reason }); if (r?.success) { ElMessage.success(`买入${sig.stock_name} ${q}股@${r.data.filled_price?.toFixed(2)}`); fetchScanner() } else ElMessage.error(r?.data?.message || '失败') } catch (e: any) { ElMessage.error('买入失败') } }
async function quickSell(pos: PositionInfo) { if (pos.available_qty <= 0) { ElMessage.warning('T+1限制'); return } try { const r = await api.post(`${scannerApi}/trade`, { ts_code: pos.ts_code, stock_name: pos.stock_name, side: 'sell', quantity: pos.available_qty, price: pos.current_price, order_type: 'market', strategy: pos.strategy, reason: `手动卖出 ${pos.profit_pct >= 0 ? '+' : ''}${pos.profit_pct.toFixed(1)}%` }); if (r?.success) { ElMessage.success(`卖出${pos.stock_name} ${pos.available_qty}股@${r.data.filled_price?.toFixed(2)}`); fetchScanner() } else ElMessage.error(r?.data?.message || '失败') } catch (e: any) { ElMessage.error('卖出失败') } }
async function onManualCodeChange(code: string) { if (!code || code.length < 9) { manualQuote.value = null; return } try { const r = await api.get(`${scannerApi}/positions`); const p = (r?.data || []).find((x: any) => x.ts_code === code); if (p) { manualQuote.value = { price: p.current_price, cost: p.cost_price, name: p.stock_name }; if (!manualTrade.stock_name) manualTrade.stock_name = p.stock_name } else { const s = signals.value.find(x => x.ts_code === code); if (s) { manualQuote.value = { price: s.price, name: s.stock_name }; if (!manualTrade.stock_name) manualTrade.stock_name = s.stock_name } else manualQuote.value = null } } catch { manualQuote.value = null } }
const executeManualTrade = async () => { if (!manualTrade.ts_code) return; try { const r = await api.post(`${scannerApi}/trade`, { ts_code: manualTrade.ts_code, stock_name: manualTrade.stock_name, side: manualTrade.side, quantity: manualTrade.quantity || 0, price: manualTrade.price || 0, order_type: 'market', strategy: 'manual', reason: '手动操作' }); if (r?.success) { ElMessage.success(`${r.data.side === 'buy' ? '买入' : '卖出'} ${r.data.ts_code} ${r.data.filled_qty}股@${r.data.filled_price}`); manualTrade.ts_code = ''; manualTrade.stock_name = ''; manualTrade.quantity = 0; manualTrade.price = 0; fetchAll(true) } else ElMessage.error('下单失败') } catch (e: any) { ElMessage.error('下单失败') } }
async function fetchScanner() { try { const [sR, sigR, posR, tlR, ordR] = await Promise.all([api.get(`${scannerApi}/status`), api.get(`${scannerApi}/signals`), api.get(`${scannerApi}/positions`), api.get(`${scannerApi}/timeline`), api.get(`${scannerApi}/orders`)]); if (sR?.success) status.value = sR.data; if (sigR?.success) signals.value = sigR.data; if (posR?.success) positions.value = posR.data; if (tlR?.success) timeline.value = tlR.data; if (ordR?.success) orders.value = ordR.data || [] } catch (e) { console.error(e) } }
async function startScanner() { await api.post(`${scannerApi}/start`, { account_id: 'default', trade_mode: dryRun.value ? 'dry_run' : tradeMode.value }); await fetchScanner() }
async function stopScanner() { await api.post(`${scannerApi}/stop`); await fetchScanner() }
async function manualScan() { loading.value = true; try { const r = await api.post(`${scannerApi}/scan-once`); if (r?.success) { const m = r.data?.message; if (m) ElMessage.warning(m); else ElMessage.success(`扫描完成: ${r.data?.signals || 0}信号, ${r.data?.positions || 0}持仓`) } else ElMessage.error('扫描失败') } catch (e: any) { ElMessage.error('扫描失败') } finally { loading.value = false; await fetchScanner() } }
async function forceScan() { loading.value = true; try { const r = await api.post(`${scannerApi}/scan-once`, { force: true }); if (r?.success) { ElMessage.success(`强制扫描完成: ${r.data?.signals || 0}信号, ${r.data?.positions || 0}持仓`) } else ElMessage.error('强制扫描失败') } catch (e: any) { ElMessage.error('强制扫描失败') } finally { loading.value = false; await fetchScanner() } }
const stratCollapsed = ref<Record<string, boolean>>({})
function toggleStrat(id: string) { stratCollapsed.value[id] = !stratCollapsed.value[id] }
async function dailySettlement() { try { const r = await api.post(`${scannerApi}/daily-settlement`); if (r?.success) { ElMessage.success(r.data?.message || '日结算完成'); await fetchScanner() } } catch (e: any) { ElMessage.error('日结算失败') } }
async function resetAccount() { try { const r = await api.post(`${scannerApi}/reset`); if (r?.success) { ElMessage.success('账户已重置'); await fetchAll(true) } } catch (e: any) { ElMessage.error('重置失败') } }
async function resetCircuitBreaker() { try { const r = await api.post(`${scannerApi}/circuit-breaker/reset`); if (r?.success) { ElMessage.success('熔断已重置'); fetchAll(true) } } catch { ElMessage.error('重置失败') } }
async function fetchLimitPools() { try { const r = await api.get(`${scannerApi}/limit-pools`); if (r?.success) limitPools.value = r.data } catch { } }
async function fetchDailyReport() { try { const r = await api.get(`${scannerApi}/daily-report`); if (r?.success) dailyReport.value = r.data } catch { } }
async function fetchDataSources() { try { const [sR, bR] = await Promise.all([api.get('/datasource/sources'), api.get('/datasource/brokers')]); if (sR?.success) dataSources.value = sR.data || []; if (bR?.success) brokers.value = bR.data || [] } catch { } }
async function fetchAll(force = false) { await Promise.all([fetchScanner(), fetchStrategies(), fetchDataSources(), fetchLimitPools(), fetchDailyReport()]) }
async function fetchStrategies() { try { const [sR, rR] = await Promise.all([api.get(`${configApi}/strategies`), api.get(`${configApi}/global-risk`)]); if (sR?.success) strategies.value = sR.data; if (rR?.success) globalRisk.value = rR.data } catch (e) { console.error(e) } }
async function toggleStrategy(sid: string, enabled: boolean) { try { await api.put(`${configApi}/strategies/${sid}`, { enabled }); await fetchStrategies(); ElMessage.success(enabled ? '已启用' : '已停用') } catch { ElMessage.error('操作失败') } }
function openEditDialog(strategy: StrategyConfig) { editingStrategy.value = strategy; editParams.value = { ...strategy.params }; editRiskParams.value = { ...strategy.riskParams }; editTab.value = 'params'; editDialogVisible.value = true }
async function saveStrategy() { if (!editingStrategy.value) return; saving.value = true; try { await api.put(`${configApi}/strategies/${editingStrategy.value.id}`, { params: editParams.value, riskParams: editRiskParams.value }); await fetchStrategies(); editDialogVisible.value = false; ElMessage.success('已保存') } catch { ElMessage.error('保存失败') } finally { saving.value = false } }
async function resetStrategy(sid: string) { try { await api.post(`${configApi}/reset/${sid}`); await fetchStrategies(); ElMessage.success('已重置') } catch { ElMessage.error('重置失败') } }
onMounted(async () => { await Promise.all([fetchScanner(), fetchStrategies(), fetchDataSources()]); connectWS(); const getRefreshInterval = () => { const n = new Date(), h = n.getHours(), m = n.getMinutes(); const isTrading = (h === 9 && m >= 30) || (h >= 10 && h < 15) || (h === 15 && m === 0); return isTrading ? 5000 : 60000 }; refreshTimer = setInterval(() => { if (!autoRefresh.value || ws?.readyState === WebSocket.OPEN) return; fetchScanner() }, getRefreshInterval()) })
onUnmounted(() => { if (refreshTimer) clearInterval(refreshTimer); disconnectWS() })
function connectWS() { try { const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'; ws = new WebSocket(`${proto}//${location.host}/ws`); ws.onopen = () => { ws?.send(JSON.stringify({ type: 'subscribe_scanner' })); }; ws.onmessage = (e) => { try { const d = JSON.parse(e.data); if (d.type === 'scanner_signal') { signals.value = d.signals?.length ? d.signals : signals.value; fetchScanner(); } else if (d.type === 'scanner_position') { positions.value = d.positions?.length ? d.positions : positions.value; } else if (d.type === 'scanner_timeline') { if (d.item) timeline.value = [...timeline.value, d.item]; fetchScanner(); } else if (d.type === 'scanner_status') { if (d.status) status.value = { ...status.value, ...d.status }; fetchScanner(); } } catch {} }; ws.onclose = () => { wsReconnectTimer = setTimeout(connectWS, 3000); }; ws.onerror = () => { ws?.close(); }; } catch {} }
function disconnectWS() { if (wsReconnectTimer) clearTimeout(wsReconnectTimer); if (ws) { ws.close(); ws = null; } }
const historyDate = ref('')
const historyData = ref<any[]>([])
const historyLoading = ref(false)
async function loadHistory() { if (!historyDate.value) { ElMessage.warning('请选择日期'); return } historyLoading.value = true; try { const d = historyDate.value.replace(/-/g, ''); const r = await api.get(`${scannerApi}/timeline/history?date=${d}`); if (r?.success) { historyData.value = r.data || []; if (!historyData.value.length) ElMessage.info('该日无交易记录') } } catch { ElMessage.error('加载失败') } finally { historyLoading.value = false } }
const compareData = ref<any[]>([])
const compareVisible = ref(false)
const compareLoading = ref(false)
async function loadCompare() { compareLoading.value = true; try { const r = await api.get(`${scannerApi}/backtest-compare`); if (r?.success) { compareData.value = r.data || []; compareVisible.value = true } } catch { ElMessage.error('加载失败') } finally { compareLoading.value = false } }
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
function formatLayerTrace(trace: Record<string, any>): string[] { if (!trace) return ['无trace']; const lines: string[] = []; for (const [layer, info] of Object.entries(trace)) { if (typeof info === 'object' && info !== null) { const applied = info.applied !== undefined ? (info.applied ? '✅' : '⏭️') : ''; const detail = info.detail || info.reason || ''; lines.push(`${applied} ${layer}: ${detail}`) } else { lines.push(`${layer}: ${info}`) } } return lines }
function signalStatusTag(status?: string) { if (!status || status === 'new') return { text: '新', type: 'primary' }; if (status === 'executed') return { text: '已买', type: 'success' }; if (status === 'skipped') return { text: '跳过', type: 'warning' }; if (status === 'expired') return { text: '过期', type: 'info' }; if (status === 'filtered') return { text: '过滤', type: 'danger' }; return { text: status, type: 'info' } }
</script>
<template>
  <div class="mm">
    <!-- 顶部状态栏 -->
    <div class="mm-header">
      <div class="hh-left">
        <div class="hh-status" :class="{ running: isRunning, stopped: !isRunning }"><span class="dot"></span><span>{{ isRunning ? '扫描中' : '已停止' }}</span></div>
        <ElTag size="small" :type="tradeMode === 'gm' ? 'warning' : 'info'">🔵仿真</ElTag>
        <ElTag v-if="dryRun" type="warning" size="small">🔍调试</ElTag>
        <ElTag v-if="circuitBreakerPaused" type="danger" size="small">⚠️熔断</ElTag>
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
        <ElSwitch v-model="autoRefresh" size="small" active-text="自动" inactive-text="" />
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
        <div class="st">🎛️ 策略控制</div>
        <div v-for="s in strategies" :key="s.id" class="sc" :class="{ disabled: !s.enabled }">
          <div class="sc-top" @click="toggleStrat(s.id)" style="cursor:pointer"><span class="sc-icon">{{ strategyMeta[s.id]?.icon || '📋' }}</span><span class="sc-name">{{ s.name }}</span><ElSwitch :model-value="s.enabled" @change="(v: boolean) => toggleStrategy(s.id, v)" size="small" @click.stop /><span class="sc-arrow">{{ stratCollapsed[s.id] ? '▶' : '▼' }}</span></div>
          <div v-if="!stratCollapsed[s.id]">
            <div class="sc-desc">{{ strategyMeta[s.id]?.desc || '' }}</div>
            <div class="sc-params"><div v-for="p in s.paramDescriptions.slice(0, 3)" :key="p.key" class="pm"><span class="pk">{{ p.label }}</span><span class="pv">{{ p.displayValue }}{{ p.unit }}</span></div></div>
            <ElButton size="small" text type="primary" @click="openEditDialog(s)">⚙️ 编辑</ElButton>
          </div>
        </div>
        <div class="st" style="margin-top:10px">⚡ 快捷操作</div>
        <div class="qa">
          <ElButton size="small" @click="manualScan" :loading="loading" :disabled="!isRunning" style="width:100%">📡 手动扫描</ElButton>
        <ElButton size="small" type="warning" @click="forceScan" :loading="loading" :disabled="!isRunning" style="width:100%" title="忽略交易时间检查，消耗必盈额度">⚡ 强制扫描</ElButton>
          <ElButton size="small" @click="dailySettlement" :disabled="!isRunning" style="width:100%">📅 日结算(T+1)</ElButton>
          <ElButton size="small" @click="openTradeAudit" :disabled="!timeline.length" style="width:100%">🔍 审查全部交易</ElButton>
          <ElButton size="small" @click="openLayerDebug" :loading="layerDebugLoading" style="width:100%">🧪 9层调试</ElButton>
          <ElButton size="small" @click="toggleDryRun" style="width:100%">{{ dryRun ? '🔴 关闭调试' : '🔍 开启调试' }}</ElButton>
          <ElButton size="small" @click="loadCompare" :loading="compareLoading" style="width:100%">📊 回测对比</ElButton>
          <ElButton v-if="circuitBreakerPaused" size="small" type="danger" @click="resetCircuitBreaker" style="width:100%">🔓 重置熔断</ElButton>
          <ElButton size="small" type="warning" @click="resetAccount" style="width:100%">🗑️ 清仓重置</ElButton>
        </div>
        <div class="st" style="margin-top:10px">🔧 手动下单</div>
        <div class="mf">
          <ElInput v-model="manualTrade.ts_code" placeholder="代码 000001.SZ" size="small" @change="onManualCodeChange(manualTrade.ts_code)" />
          <div class="mf-row"><ElSelect v-model="manualTrade.side" size="small" style="width:70px"><ElOption label="买入" value="buy" /><ElOption label="卖出" value="sell" /></ElSelect><ElInputNumber v-model="manualTrade.quantity" :min="0" :step="100" placeholder="数量" size="small" style="flex:1" controls-position="right" /></div>
          <ElButton type="primary" size="small" :disabled="!manualTrade.ts_code" @click="executeManualTrade" style="width:100%">下单</ElButton>
          <div v-if="manualQuote" class="mf-q">💡 现价: ¥{{ manualQuote.price?.toFixed(2) }}</div>
        </div>
      </div>

      <!-- 中列: 信号+行情 -->
      <div class="mm-center">
        <div class="st">🎯 活跃信号 <div style="display:inline-flex;gap:2px;margin-left:6px"><ElTag v-for="f in [{k:'all',l:'全部'},{k:'halfway_chase',l:'半路'},{k:'first_limit_up',l:'首板'},{k:'limit_down_qiao',l:'跌停'},{k:'anomaly',l:'异动'}]" :key="f.k" size="small" :type="signalFilter===f.k?'primary':'info'" style="cursor:pointer" @click="signalFilter=f.k">{{ f.l }}</ElTag></div> <ElBadge :value="filteredSignals.length" :max="99" style="margin-left:4px" /></div>
        <div class="sl">
          <div v-if="!signals.length" class="empty">启动后扫描获取信号</div>
          <div v-for="sig in filteredSignals" :key="sig.ts_code + sig.strategy" class="sig-row">
            <div class="sig-top"><span class="code">{{ sig.ts_code }}</span><span class="name">{{ sig.stock_name }}</span><ElTag size="small" :color="strategyMeta[sig.strategy]?.color || '#909399'" style="color:#fff;border:none">{{ sig.strategy_name }}</ElTag><ElTag v-if="sig.signal_status === 'executed'" size="small" type="success">已买入</ElTag><ElTag v-if="sig.signal_status === 'skipped'" size="small" type="warning">跳过</ElTag><ElTag v-if="sig.signal_status === 'expired'" size="small" type="info">过期</ElTag><span :class="sig.pct_chg >= 0 ? 'up' : 'down'" style="margin-left:auto;font-weight:600">{{ sig.pct_chg >= 0 ? '+' : '' }}{{ sig.pct_chg.toFixed(1) }}%</span></div>
            <div class="sig-bot"><span v-if="sig.volume_ratio" class="factor">量比{{ sig.volume_ratio.toFixed(1) }}</span><span v-if="sig.turnover_rate" class="factor">换手{{ sig.turnover_rate.toFixed(1) }}%</span><span class="reason">{{ sig.reason }}</span></div>
            <div class="sig-act"><ElButton v-if="!dryRun && sig.signal_status === 'new'" size="small" type="danger" plain @click="quickBuy(sig)">🟢 买入{{ Math.floor((status?.account?.available_cash || 0) * 0.25 / sig.price / 100) * 100 > 0 ? ' ' + Math.floor((status?.account?.available_cash || 0) * 0.25 / sig.price / 100) * 100 + '股' : '' }}</ElButton><ElButton v-if="sig.decision_detail" size="small" type="info" plain @click="openTradeDetail(sig.ts_code)">🔍 决策</ElButton><ElButton v-if="sig.layer_trace" size="small" type="warning" plain @click="openScanTrace(sig.ts_code)">🧪 Trace</ElButton></div>
          </div>
        </div>
        <div class="st" style="margin-top:6px">🔥 涨跌停池 <div style="display:inline-flex;gap:2px;margin-left:6px"><ElTag size="small" :type="limitPoolTab==='limit_up'?'danger':'info'" style="cursor:pointer" @click="limitPoolTab='limit_up'">涨停{{ limitPools.limit_up.length }}</ElTag><ElTag size="small" :type="limitPoolTab==='limit_down'?'warning':'info'" style="cursor:pointer" @click="limitPoolTab='limit_down'">跌停{{ limitPools.limit_down.length }}</ElTag><ElTag size="small" :type="limitPoolTab==='broken'?'':'info'" style="cursor:pointer" @click="limitPoolTab='broken'">炸板{{ limitPools.broken.length }}</ElTag></div></div>
        <div class="sl sl-sm">
          <div v-if="!limitPools[limitPoolTab as keyof typeof limitPools]?.length" class="empty">暂无数据</div>
          <div v-for="item in (limitPools[limitPoolTab as keyof typeof limitPools] || []).slice(0, 20)" :key="item.ts_code" class="limit-row"><span class="code">{{ item.ts_code }}</span><span class="name">{{ item.name }}</span><span :class="item.pct_chg >= 0 ? 'up' : 'down'">{{ item.pct_chg >= 0 ? '+' : '' }}{{ item.pct_chg.toFixed(1) }}%</span><span v-if="item.limit_times" class="lb-tag">{{ item.limit_times }}连板</span><span v-if="item.fd_amount" class="fd-tag">封{{ item.fd_amount }}万</span></div>
        </div>
      </div>

      <!-- 右列: 持仓 -->
      <div class="mm-right">
        <div class="st">📊 持仓监控 <ElBadge :value="positions.length" :max="99" style="margin-left:4px" /></div>
        <div class="sl">
          <div v-if="!positions.length" class="empty">暂无持仓</div>
          <div v-for="pos in [...positions].sort((a, b) => a.profit_pct - b.profit_pct)" :key="pos.ts_code" class="pos-card">
            <div class="pos-top"><span class="code">{{ pos.ts_code }}</span><span class="name">{{ pos.stock_name }}</span><ElTag size="small" :color="strategyMeta[pos.strategy]?.color || '#909399'" style="color:#fff;border:none;font-size:10px">{{ pos.strategy }}</ElTag><span :class="pos.profit_pct >= 0 ? 'up' : 'down'" class="pct">{{ pos.profit_pct >= 0 ? '+' : '' }}{{ pos.profit_pct.toFixed(1) }}%</span></div>
            <div class="pos-bar-w"><div class="pos-bar" :style="{ width: Math.min(Math.abs(pos.profit_pct) / 10 * 100, 100) + '%', background: pos.profit_pct >= 0 ? '#67c23a' : '#f56c6c' }"></div></div>
            <div class="pos-info"><span>{{ pos.shares }}股</span><span>成本{{ pos.cost_price.toFixed(2) }}</span><span>现价{{ pos.current_price.toFixed(2) }}</span><span v-if="pos.today_buy > 0" class="t1-tag">T+1</span></div>
            <div class="pos-risk" v-if="pos.stop_loss_pct != null"><span class="rl stop">止损{{ pos.stop_loss_pct.toFixed(1) }}%</span><span class="rl stop-price">止损价{{ (pos.cost_price * (1 - pos.stop_loss_pct / 100)).toFixed(2) }}</span><span class="rl profit">止盈{{ pos.take_profit_pct?.toFixed(1) || 7.0 }}%</span><span class="rl profit-price">止盈价{{ (pos.cost_price * (1 + (pos.take_profit_pct || 7.0) / 100)).toFixed(2) }}</span><span class="rd" :class="{ danger: pos.profit_pct - pos.stop_loss_pct < 2 }">距止损{{ (pos.profit_pct - pos.stop_loss_pct).toFixed(1) }}%</span></div>
            <div class="pos-act"><ElButton size="small" type="danger" plain @click="quickSell(pos)" :disabled="pos.available_qty <= 0">🔴 卖出</ElButton><ElButton size="small" type="info" plain @click="openTradeDetail(pos.ts_code)">🔍 详情</ElButton></div>
          </div>
        </div>
        <div class="st" style="margin-top:6px">📈 今日统计</div>
        <div class="stats" v-if="status"><div class="si"><div class="sv">{{ status.stats.signals_found }}</div><div class="sl2">信号</div></div><div class="si"><div class="sv">{{ status.stats.trades_executed }}</div><div class="sl2">交易</div></div><div class="si"><div class="sv" style="color:#f56c6c">{{ status.stats.stop_losses }}</div><div class="sl2">止损</div></div><div class="si"><div class="sv" style="color:#67c23a">{{ status.stats.take_profits }}</div><div class="sl2">止盈</div></div></div>
      </div>
    </div>

    <!-- 底部时间线 -->
    <div v-if="isRunning || timeline.length" class="mm-footer">
      <div class="st">⏱️ 交易时间线 ({{ timeline.length }}) <ElButton v-if="timeline.length" size="small" type="warning" @click="openTradeAudit" style="margin-left:6px">🔍 审查全部</ElButton> <div style="display:inline-flex;align-items:center;gap:4px;margin-left:8px"><input type="date" v-model="historyDate" style="font-size:11px;padding:2px 4px;border:1px solid #dcdfe6;border-radius:4px" /><ElButton size="small" @click="loadHistory" :loading="historyLoading" style="padding:2px 8px;font-size:11px">回放</ElButton><ElButton v-if="historyData.length" size="small" type="info" @click="historyData=[];historyDate=''" style="padding:2px 8px;font-size:11px">返回今日</ElButton></div></div>
      <div class="tl-scroll">
        <div v-if="historyData.length" class="history-tag">📜 {{ historyDate }} 历史回放 ({{ historyData.length }}条)</div>
        <div v-if="!historyData.length && !timeline.length" class="empty">暂无交易</div>
        <div v-for="(item, i) in historyData.length ? historyData : timeline" :key="i" class="tl-row" @click="openTradeDetail(item.ts_code)" style="cursor:pointer"><span class="tl-time">{{ item.time }}</span><span class="tl-action" :class="item.action === 'buy' ? 'buy' : 'sell'">{{ item.action === 'buy' ? '买' : '卖' }}</span><span class="code">{{ item.ts_code }}</span><span class="name">{{ item.stock_name }}</span><span class="tl-detail">{{ item.shares }}股@{{ item.price.toFixed(2) }}</span><span v-if="item.profit_pct !== undefined" :class="item.profit_pct >= 0 ? 'up' : 'down'">{{ item.profit_pct >= 0 ? '+' : '' }}{{ item.profit_pct.toFixed(1) }}%</span><span class="tl-reason">{{ item.reason }}</span></div>
        <div v-if="orders.length" style="margin-top:6px;padding-top:6px;border-top:1px dashed #dcdfe6"><div style="font-size:12px;font-weight:600;color:#606266;margin-bottom:4px">📋 历史订单 ({{ orders.length }})</div><div v-for="o in orders.slice(0, 15)" :key="o.order_id" class="tl-row" @click="openTradeDetail(o.ts_code)" style="cursor:pointer"><span class="tl-time">{{ o.trade_date?.slice(-4) || '' }} {{ o.create_time }}</span><span class="tl-action" :class="o.side === 'buy' ? 'buy' : 'sell'">{{ o.side === 'buy' ? '买' : '卖' }}</span><span class="code">{{ o.ts_code }}</span><span class="name">{{ o.stock_name }}</span><span class="tl-detail">{{ o.filled_qty }}股@{{ o.filled_price?.toFixed(2) || '0.00' }}</span><span style="font-size:11px;color:#909399">{{ o.strategy }}</span></div></div>
      </div>
    </div>

    <!-- 策略编辑弹窗 -->
    <ElDialog v-model="editDialogVisible" :title="`编辑 ${editingStrategy?.name}`" width="560px" :close-on-click-modal="false">
      <ElTabs v-model="editTab">
        <ElTabPane label="选股参数" name="params"><div v-for="p in editingStrategy?.paramDescriptions || []" :key="p.key" style="margin-bottom:12px"><div style="font-size:13px;margin-bottom:4px">{{ p.label }} <span style="color:#909399">({{ p.min }}~{{ p.max }}{{ p.unit }})</span></div><ElSlider v-model="editParams[p.key]" :min="p.min" :max="p.max" :step="p.step" show-input size="small" /></div></ElTabPane>
        <ElTabPane label="风控参数" name="risk"><div v-for="p in editingStrategy?.riskDescriptions || []" :key="p.key" style="margin-bottom:12px"><div style="font-size:13px;margin-bottom:4px">{{ p.label }} <span style="color:#909399">({{ p.min }}~{{ p.max }}{{ p.unit }})</span></div><ElSlider v-model="editRiskParams[p.key]" :min="p.min" :max="p.max" :step="p.step" show-input size="small" /></div></ElTabPane>
      </ElTabs>
      <template #footer><ElButton @click="editDialogVisible = false">取消</ElButton><ElButton type="primary" :loading="saving" @click="saveStrategy">保存</ElButton></template>
    </ElDialog>

    <!-- 交易详情弹窗 -->
    <ElDialog v-model="tradeDetailVisible" :title="`🔍 交易审查 — ${tradeDetailData?.ts_code || ''}`" width="680px">
      <div v-if="tradeDetailData" class="td">
        <div class="td-sec"><div class="td-t">📥 买入决策</div><template v-if="tradeDetailData.buy"><div class="td-g"><div class="td-i"><span class="td-l">时间</span><span class="td-v">{{ tradeDetailData.buy.time }}</span></div><div class="td-i"><span class="td-l">价格</span><span class="td-v">{{ tradeDetailData.buy.price?.toFixed(2) }}</span></div><div class="td-i"><span class="td-l">数量</span><span class="td-v">{{ tradeDetailData.buy.shares }}股</span></div><div class="td-i"><span class="td-l">策略</span><span class="td-v">{{ tradeDetailData.buy.strategy }}</span></div></div><div class="td-r">原因: {{ tradeDetailData.buy.reason }}</div><template v-if="tradeDetailData.buy.decision_detail"><div class="td-c">决策链路:</div><div v-for="(line, i) in formatDecisionDetail(tradeDetailData.buy.decision_detail)" :key="i" class="cl">{{ line }}</div></template></template><div v-else class="td-e">无买入记录</div></div>
        <div class="td-sec"><div class="td-t">📤 卖出决策</div><template v-if="tradeDetailData.sell"><div class="td-g"><div class="td-i"><span class="td-l">时间</span><span class="td-v">{{ tradeDetailData.sell.time }}</span></div><div class="td-i"><span class="td-l">价格</span><span class="td-v">{{ tradeDetailData.sell.price?.toFixed(2) }}</span></div><div class="td-i"><span class="td-l">盈亏</span><span class="td-v" :class="tradeDetailData.sell.profit_pct >= 0 ? 'up' : 'down'">{{ tradeDetailData.sell.profit_pct >= 0 ? '+' : '' }}{{ tradeDetailData.sell.profit_pct?.toFixed(2) }}%</span></div></div><div class="td-r">原因: {{ tradeDetailData.sell.reason }}</div><template v-if="tradeDetailData.sell.decision_detail"><div class="td-c">决策链路:</div><div v-for="(line, i) in formatDecisionDetail(tradeDetailData.sell.decision_detail)" :key="i" class="cl">{{ line }}</div></template></template><div v-else class="td-e">无卖出记录</div></div>
        <div class="td-sec" v-if="tradeDetailData.position"><div class="td-t">📊 当前持仓</div><div class="td-g"><div class="td-i"><span class="td-l">持仓</span><span class="td-v">{{ tradeDetailData.position.shares }}股</span></div><div class="td-i"><span class="td-l">成本</span><span class="td-v">{{ tradeDetailData.position.cost_price?.toFixed(2) }}</span></div><div class="td-i"><span class="td-l">现价</span><span class="td-v">{{ tradeDetailData.position.current_price?.toFixed(2) }}</span></div><div class="td-i"><span class="td-l">盈亏</span><span class="td-v" :class="tradeDetailData.position.profit_pct >= 0 ? 'up' : 'down'">{{ tradeDetailData.position.profit_pct >= 0 ? '+' : '' }}{{ tradeDetailData.position.profit_pct?.toFixed(2) }}%</span></div></div></div>
      </div>
      <div v-else class="empty">无数据</div>
    </ElDialog>

    <!-- 审查弹窗 -->
    <ElDialog v-model="tradeAuditVisible" title="🔍 全部交易审查" width="800px">
      <div v-if="tradeAuditData.length" class="al"><div class="ah"><span>股票</span><span>策略</span><span>买入</span><span>卖出</span><span>盈亏</span><span>状态</span></div><div v-for="t in tradeAuditData" :key="t.ts_code" class="ar" @click="openTradeDetail(t.ts_code); tradeAuditVisible = false"><span class="code">{{ t.ts_code }}</span><span><ElTag size="small" type="info">{{ t.strategy }}</ElTag></span><span>{{ t.buy_time }} {{ t.buy_price?.toFixed(2) }}</span><span>{{ t.sell_time || '-' }} {{ t.sell_price?.toFixed(2) || '-' }}</span><span :class="t.profit_pct !== null && t.profit_pct >= 0 ? 'up' : 'down'">{{ t.profit_pct !== null ? (t.profit_pct >= 0 ? '+' : '') + t.profit_pct.toFixed(2) + '%' : '-' }}</span><span style="font-size:11px;color:#909399">{{ t.status }}</span></div></div>
      <div v-else class="empty">暂无交易记录</div>
    </ElDialog>
    <!-- 回测对比弹窗 -->
    <ElDialog v-model="compareVisible" title="📊 实盘 vs 回测对比" width="700px">
      <div v-if="compareData.length" class="cl-table">
        <div class="cl-h"><span>策略</span><span>实盘交易</span><span>实盘胜率</span><span>实盘盈亏</span><span>回测收益</span><span>回测胜率</span><span>回测回撤</span><span>回测夏普</span></div>
        <div v-for="c in compareData" :key="c.strategy" class="cl-r">
          <span class="code">{{ c.strategy }}</span>
          <span>{{ c.live_trades }}笔</span>
          <span :class="c.live_win_rate >= 50 ? 'up' : 'down'">{{ c.live_win_rate }}%</span>
          <span :class="c.live_pnl >= 0 ? 'up' : 'down'">{{ c.live_pnl >= 0 ? '+' : '' }}{{ c.live_pnl.toFixed(0) }}</span>
          <span :class="c.bt_return >= 0 ? 'up' : 'down'">{{ c.bt_return }}%</span>
          <span>{{ c.bt_win_rate }}%</span>
          <span style="color:#f56c6c">{{ c.bt_drawdown }}%</span>
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
              <span class="ld-name">{{ layer }}</span>
            </div>
          </div>
          <div class="ld-sentiment" v-if="layerDebugData.pipeline_config.sentiment">
            情绪: {{ layerDebugData.pipeline_config.sentiment.score }} → {{ layerDebugData.pipeline_config.sentiment.period }} | 仓位系数: {{ (layerDebugData.pipeline_config.position_ratio * 100).toFixed(0) }}%
          </div>
        </div>
        <div v-if="layerDebugData.signal_traces?.length" class="ld-traces">
          <div class="ld-title">信号逐层Trace</div>
          <div v-for="trace in layerDebugData.signal_traces" :key="trace.ts_code + trace.strategy" class="ld-trace-card">
            <div class="ld-trace-top"><span class="code">{{ trace.ts_code }}</span><span class="name">{{ trace.stock_name }}</span><ElTag size="small" type="info">{{ trace.strategy }}</ElTag><ElTag size="small" :type="trace.signal_status === 'skipped' ? 'warning' : trace.signal_status === 'executed' ? 'success' : 'primary'">{{ trace.signal_status }}</ElTag></div>
            <div class="ld-trace-layers">
              <div v-for="(line, i) in formatLayerTrace(trace.layer_trace)" :key="i" class="ld-trace-line">{{ line }}</div>
            </div>
          </div>
        </div>
        <div v-else class="empty">暂无信号trace数据</div>
      </div>
      <div v-else class="empty">加载中...</div>
    </ElDialog>

    <!-- 【调试增强】单只股票扫描Trace弹窗 -->
    <ElDialog v-model="scanTraceVisible" title="🧪 扫描Trace — {{ scanTraceCode }}" width="700px">
      <div v-if="scanTraceData" class="scan-trace">
        <div v-if="scanTraceData.status === 'not_found'" class="empty">{{ scanTraceData.message }}</div>
        <div v-else>
          <div class="st-header">
            <span class="code">{{ scanTraceData.ts_code }}</span>
            <span class="name">{{ scanTraceData.stock_name }}</span>
            <ElTag size="small" :type="scanTraceData.signal_status === 'skipped' ? 'warning' : scanTraceData.signal_status === 'executed' ? 'success' : 'primary'">{{ scanTraceData.signal_status }}</ElTag>
            <span :class="scanTraceData.pct_chg >= 0 ? 'up' : 'down'" style="font-weight:600">{{ scanTraceData.pct_chg >= 0 ? '+' : '' }}{{ scanTraceData.pct_chg?.toFixed(1) }}%</span>
          </div>
          <div class="st-reason">{{ scanTraceData.reason }}</div>
          <div v-if="scanTraceData.age_seconds" class="st-age">信号年龄: {{ scanTraceData.age_seconds }}秒</div>
          <div v-if="scanTraceData.layer_trace" class="st-trace">
            <div class="st-title">逐层筛选Trace</div>
            <div v-for="(line, i) in formatLayerTrace(scanTraceData.layer_trace)" :key="i" class="st-line">{{ line }}</div>
          </div>
          <div v-if="scanTraceData.decision_detail" class="st-detail">
            <div class="st-title">决策详情</div>
            <div v-for="(line, i) in formatDecisionDetail(scanTraceData.decision_detail)" :key="i" class="st-line">{{ line }}</div>
          </div>
          <div v-if="scanTraceData.factors" class="st-factors">
            <div class="st-title">关键因子</div>
            <div class="st-fg">
              <div v-for="(v, k) in scanTraceData.factors" :key="k" class="st-fi"><span class="st-fl">{{ k }}</span><span class="st-fv">{{ typeof v === 'number' ? v.toFixed(2) : v }}</span></div>
            </div>
          </div>
        </div>
      </div>
      <div v-else class="empty">加载中...</div>
    </ElDialog>
  </div>
</template>
<style scoped lang="scss">
.mm { height: 100%; display: flex; flex-direction: column; background: #f5f7fa; overflow: hidden; }
/* 顶部状态栏 */
.mm-header { display: flex; align-items: center; gap: 12px; padding: 8px 16px; background: #fff; border-bottom: 1px solid #ebeef5; flex-shrink: 0; }
.hh-left { display: flex; align-items: center; gap: 6px; }
.hh-status { display: flex; align-items: center; gap: 5px; font-weight: 600; font-size: 13px; }
.hh-status .dot { width: 8px; height: 8px; border-radius: 50%; }
.hh-status.running .dot { background: #67c23a; animation: pulse 1.5s infinite; }
.hh-status.stopped .dot { background: #909399; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
.hh-account { display: flex; gap: 14px; flex: 1; }
.ha { display: flex; flex-direction: column; }
.hl { font-size: 10px; color: #909399; }
.hv { font-size: 13px; font-weight: 600; }
.hh-actions { display: flex; align-items: center; gap: 6px; }
.up { color: #f56c6c; }
.down { color: #67c23a; }

/* 引导页 */
.mm-guide { flex: 1; display: flex; align-items: center; justify-content: center; }
.guide-card { text-align: center; padding: 40px; background: #fff; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.08); }
.guide-icon { font-size: 48px; margin-bottom: 12px; }
.guide-title { font-size: 20px; font-weight: 600; margin-bottom: 20px; }
.guide-steps { text-align: left; display: inline-block; }
.guide-step { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; font-size: 14px; }
.sn { display: inline-flex; align-items: center; justify-content: center; width: 24px; height: 24px; border-radius: 50%; background: #409eff; color: #fff; font-size: 12px; font-weight: 600; flex-shrink: 0; }

/* 3列主布局 */
.mm-body { flex: 1; display: grid; grid-template-columns: 240px 1fr 280px; gap: 0; overflow: hidden; }
.mm-left, .mm-center, .mm-right { overflow-y: auto; padding: 10px; }
.mm-left { background: #fafbfc; border-right: 1px solid #ebeef5; }
.mm-right { background: #fafbfc; border-left: 1px solid #ebeef5; }

/* 区域标题 */
.st { font-size: 13px; font-weight: 600; color: #303133; margin-bottom: 8px; display: flex; align-items: center; }

/* 策略卡片 */
.sc { padding: 8px 10px; margin-bottom: 6px; background: #fff; border-radius: 6px; border: 1px solid #ebeef5; transition: border-color 0.2s; }
.sc:hover { border-color: #c0c4cc; }
.sc.disabled { opacity: 0.5; }
.sc-top { display: flex; align-items: center; gap: 6px; }
.sc-icon { font-size: 16px; }
.sc-name { font-size: 13px; font-weight: 600; flex: 1; }
.sc-arrow { font-size: 10px; color: #909399; margin-left: 4px; }
.sc-desc { font-size: 11px; color: #909399; margin: 2px 0 4px 24px; }
.sc-params { margin-left: 24px; }
.pm { display: flex; justify-content: space-between; font-size: 11px; }
.pk { color: #909399; }
.pv { color: #606266; font-weight: 500; }

/* 快捷操作 */
.qa { display: flex; flex-direction: column; gap: 4px; }

/* 手动下单 */
.mf { display: flex; flex-direction: column; gap: 4px; }
.mf-row { display: flex; gap: 4px; }
.mf-q { font-size: 11px; color: #67c23a; padding: 2px 0; }

/* 信号列表 */
.sl { overflow-y: auto; }
.sl-sm { max-height: 200px; }
.sig-row { padding: 6px 8px; margin-bottom: 4px; background: #fff; border-radius: 6px; border: 1px solid #ebeef5; }
.sig-row:hover { border-color: #409eff; }
.sig-top { display: flex; align-items: center; gap: 6px; }
.sig-bot { display: flex; align-items: center; gap: 6px; margin-top: 2px; font-size: 12px; }
.factor { font-size: 11px; color: #909399; background: #f4f4f5; padding: 1px 4px; border-radius: 3px; }
.reason { font-size: 11px; color: #909399; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 200px; }
.sig-act { display: flex; gap: 4px; margin-top: 4px; }
.sig-act .el-button { padding: 3px 8px; font-size: 11px; }

/* 涨停池 */
.limit-row { display: flex; align-items: center; gap: 6px; padding: 3px 8px; font-size: 12px; border-bottom: 1px solid #f2f3f5; }
.lb-tag { font-size: 10px; color: #f56c6c; background: #fef0f0; padding: 1px 4px; border-radius: 3px; }
.fd-tag { font-size: 10px; color: #e6a23c; background: #fdf6ec; padding: 1px 4px; border-radius: 3px; }

/* 持仓卡片 */
.pos-card { padding: 8px 10px; margin-bottom: 6px; background: #fff; border-radius: 6px; border: 1px solid #ebeef5; }
.pos-card:hover { border-color: #409eff; }
.pos-top { display: flex; align-items: center; gap: 6px; }
.pct { margin-left: auto; font-weight: 700; font-size: 14px; }
.pos-bar-w { height: 3px; background: #ebeef5; border-radius: 2px; margin: 4px 0; }
.pos-bar { height: 100%; border-radius: 2px; transition: width 0.3s; background: linear-gradient(90deg, rgba(103,194,58,0.3), rgba(103,194,58,1)); }
.pos-info { display: flex; gap: 8px; font-size: 11px; color: #606266; }
.t1-tag { font-size: 10px; color: #e6a23c; background: #fdf6ec; padding: 1px 4px; border-radius: 3px; font-weight: 600; }
.pos-risk { display: flex; gap: 6px; margin-top: 4px; font-size: 11px; align-items: center; }
.rl { padding: 1px 5px; border-radius: 3px; font-weight: 500; }
.rl.stop { color: #f56c6c; background: #fef0f0; }
.rl.stop-price { color: #f56c6c; background: #fef0f0; font-weight: 700; }
.rl.profit { color: #67c23a; background: #f0f9eb; }
.rl.profit-price { color: #67c23a; background: #f0f9eb; font-weight: 700; }
.rd { color: #909399; }
.rd.danger { color: #f56c6c; font-weight: 600; animation: blink 1s infinite; }
@keyframes blink { 50% { opacity: 0.5; } }
.pos-act { display: flex; gap: 4px; margin-top: 6px; }
.pos-act .el-button { padding: 3px 8px; font-size: 11px; }

/* 统计 */
.stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }
.si { text-align: center; padding: 6px; background: #fff; border-radius: 6px; }
.sv { font-size: 18px; font-weight: 700; }
.sl2 { font-size: 11px; color: #909399; }

/* 底部时间线 */
.mm-footer { flex-shrink: 0; max-height: 180px; border-top: 1px solid #ebeef5; padding: 6px 16px; background: #fff; }
.tl-scroll { overflow-y: auto; max-height: 140px; }
.tl-row { display: flex; align-items: center; gap: 6px; padding: 3px 0; font-size: 12px; border-bottom: 1px solid #f9f9f9; cursor: pointer; }
.tl-row:hover { background: #f5f7fa; }
.tl-time { font-size: 11px; color: #909399; min-width: 50px; }
.tl-action { font-size: 11px; font-weight: 600; min-width: 20px; }
.tl-action.buy { color: #f56c6c; }
.tl-action.sell { color: #67c23a; }
.tl-detail { font-size: 11px; color: #606266; }
.tl-reason { font-size: 11px; color: #909399; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.history-tag { font-size: 12px; color: #409eff; background: #ecf5ff; padding: 4px 8px; border-radius: 4px; margin-bottom: 4px; font-weight: 600; }

/* 通用 */
.code { font-size: 12px; font-weight: 600; color: #303133; font-family: monospace; }
.name { font-size: 12px; color: #606266; }
.empty { text-align: center; color: #c0c4cc; font-size: 12px; padding: 20px 0; }

/* 交易详情弹窗 */
.td { font-size: 13px; }
.td-sec { margin-bottom: 14px; padding: 10px; background: #fafafa; border-radius: 8px; border: 1px solid #ebeef5; }
.td-t { font-size: 14px; font-weight: 600; margin-bottom: 6px; color: #303133; }
.td-g { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin-bottom: 4px; }
.td-i { display: flex; flex-direction: column; gap: 1px; }
.td-l { font-size: 10px; color: #909399; }
.td-v { font-size: 13px; font-weight: 500; }
.td-r { font-size: 12px; color: #606266; margin: 4px 0; padding: 4px 6px; background: #fff; border-radius: 4px; border-left: 3px solid #409eff; }
.td-c { font-size: 12px; font-weight: 600; color: #606266; margin-top: 4px; }
.cl { font-size: 11px; color: #606266; padding: 1px 0 1px 10px; font-family: monospace; }
.td-e { color: #c0c4cc; font-size: 12px; }

/* 审查弹窗 */
.al { max-height: 500px; overflow-y: auto; }
.ah { display: grid; grid-template-columns: 100px 80px 120px 120px 70px 80px; gap: 4px; padding: 6px 0; font-size: 12px; font-weight: 600; color: #909399; border-bottom: 1px solid #ebeef5; }
.ar { display: grid; grid-template-columns: 100px 80px 120px 120px 70px 80px; gap: 4px; padding: 6px 0; font-size: 12px; align-items: center; border-bottom: 1px solid #f2f3f5; cursor: pointer; }
.ar:hover { background: rgba(64,158,255,0.06); }

/* 回测对比 */
.cl-table { max-height: 400px; overflow-y: auto; }
.cl-h { display: grid; grid-template-columns: 120px 70px 70px 80px 70px 70px 70px 60px; gap: 4px; padding: 6px 0; font-size: 12px; font-weight: 600; color: #909399; border-bottom: 1px solid #ebeef5; }
.cl-r { display: grid; grid-template-columns: 120px 70px 70px 80px 70px 70px 70px 60px; gap: 4px; padding: 6px 0; font-size: 12px; align-items: center; border-bottom: 1px solid #f2f3f5; }

/* 响应式 */
@media (max-width: 1024px) { .mm-body { grid-template-columns: 1fr; } .mm-left, .mm-right { border: none; border-bottom: 1px solid #ebeef5; } }

/* 【调试增强】9层调试弹窗 */
.layer-debug { font-size: 13px; }
.ld-header { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; font-size: 12px; color: #606266; }
.ld-title { font-size: 13px; font-weight: 600; color: #303133; margin-bottom: 6px; }
.ld-pipeline { padding: 10px; background: #fafafa; border-radius: 8px; border: 1px solid #ebeef5; margin-bottom: 10px; }
.ld-layers { display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; margin-bottom: 6px; }
.ld-layer { display: flex; align-items: center; gap: 4px; font-size: 11px; padding: 3px 6px; background: #fff; border-radius: 4px; border: 1px solid #ebeef5; }
.ld-on { color: #67c23a; }
.ld-off { color: #909399; }
.ld-name { color: #606266; }
.ld-sentiment { font-size: 12px; color: #409eff; padding: 4px 0; }
.ld-traces { max-height: 400px; overflow-y: auto; }
.ld-trace-card { padding: 8px 10px; margin-bottom: 6px; background: #fff; border-radius: 6px; border: 1px solid #ebeef5; }
.ld-trace-top { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
.ld-trace-layers { padding-left: 10px; }
.ld-trace-line { font-size: 11px; color: #606266; padding: 1px 0; font-family: monospace; }

/* 【调试增强】扫描Trace弹窗 */
.scan-trace { font-size: 13px; }
.st-header { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
.st-reason { font-size: 12px; color: #606266; padding: 4px 6px; background: #fff; border-radius: 4px; border-left: 3px solid #409eff; margin-bottom: 6px; }
.st-age { font-size: 11px; color: #909399; margin-bottom: 6px; }
.st-trace, .st-detail, .st-factors { padding: 10px; background: #fafafa; border-radius: 8px; border: 1px solid #ebeef5; margin-bottom: 8px; }
.st-title { font-size: 13px; font-weight: 600; color: #303133; margin-bottom: 4px; }
.st-line { font-size: 11px; color: #606266; padding: 1px 0; font-family: monospace; }
.st-fg { display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; }
.st-fi { display: flex; flex-direction: column; padding: 3px 6px; background: #fff; border-radius: 4px; }
.st-fl { font-size: 10px; color: #909399; }
.st-fv { font-size: 13px; font-weight: 500; }
</style>
