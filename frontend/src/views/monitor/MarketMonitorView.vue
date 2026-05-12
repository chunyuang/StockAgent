<script setup lang="ts">
/**
 * MarketMonitorView — 超短量化统一页面
 * 
 * 3个Tab:
 * 1. 📡 实时扫描 — 信号 + 持仓 + 时间线 + 统计
 * 2. 🎛️ 策略配置 — 4策略参数 + 全局风控
 * 3. 📊 盘后复盘 — 调度器状态 + 报告
 */
import { ref, computed, onMounted, onUnmounted, reactive } from 'vue'
import {
  ElCard, ElButton, ElTag, ElEmpty, ElTable, ElTableColumn,
  ElSwitch, ElInputNumber, ElSlider, ElDescriptions, ElDescriptionsItem,
  ElTabs, ElTabPane, ElDialog, ElMessage, ElTooltip, ElBadge,
} from 'element-plus'

// ==================== Types ====================

interface ScanStats {
  scans: number; signals_found: number; trades_executed: number
  stop_losses: number; take_profits: number; stocks_scanned: number
}
interface ScannerStatus {
  is_running: boolean; scan_count: number; last_scan_time: string
  active_signals: number; positions: number; stocks_scanned: number
  stats: ScanStats; account_id: string; trade_mode: string
  account: { total_assets: number; available_cash: number; market_value: number; total_profit: number }
}
interface ScanSignal {
  ts_code: string; stock_name: string; strategy: string; strategy_name: string
  signal_type: string; price: number; pct_chg: number; volume_ratio: number
  turnover_rate: number; is_limit_up: boolean; limit_up_count: number
  confidence: number; reason: string; scan_time: string
  factors: Record<string, number>
}
interface PositionInfo {
  ts_code: string; stock_name: string; strategy: string; shares: number
  available_qty: number; cost_price: number; current_price: number; profit_pct: number
  today_buy: number
}
interface TimelineItem {
  time: string; action: string; ts_code: string; stock_name: string
  strategy: string; shares: number; price: number; reason: string; profit_pct?: number
}
interface StrategyConfig {
  id: string; name: string; enabled: boolean
  params: Record<string, any>; riskParams: Record<string, any>
  paramDescriptions: ParamDesc[]; riskDescriptions: ParamDesc[]
}
interface ParamDesc {
  key: string; label: string; value: any; displayValue: any; unit: string; type: string
}
interface GlobalRisk {
  stop_loss_pct: number; take_profit_pct: number; max_hold_days: number
  slippage_pct: number; commission_rate: number; stamp_duty_rate: number
  max_position_per_stock: number; max_total_position: number
  liquidity_threshold: number; volume_threshold: number
}

// ==================== State ====================

const activeTab = ref('scanner')
const loading = ref(false)
const autoRefresh = ref(true)
let refreshTimer: any = null

// 扫描器
const status = ref<ScannerStatus | null>(null)
const signals = ref<ScanSignal[]>([])
const positions = ref<PositionInfo[]>([])
const timeline = ref<TimelineItem[]>([])

// 策略配置
const strategies = ref<StrategyConfig[]>([])
const globalRisk = ref<GlobalRisk | null>(null)
const editingStrategy = ref<StrategyConfig | null>(null)
const editDialogVisible = ref(false)
const editTab = ref('params')
const editParams = ref<Record<string, any>>({})
const editRiskParams = ref<Record<string, any>>({})
const saving = ref(false)

const scannerApi = '/api/v1/scanner'
const configApi = '/api/v1/strategy-config'

// ==================== 策略颜色 ====================

const strategyColor: Record<string, string> = {
  halfway_chase: '#409eff', first_limit_up: '#e6a23c',
  limit_up_open: '#909399', leader_buy_dip: '#67c23a', limit_down_qiao: '#f56c6c',
}
const strategyIcon: Record<string, string> = {
  halfway_chase: '📈', first_limit_up: '🎯', limit_up_open: '🔓',
  leader_buy_dip: '👑', limit_down_qiao: '🔨',
}

// ==================== Computed ====================

const tradeMode = ref('simulated')  // 'simulated' | 'gm'

// 数据源管理
const dataSources = ref<any[]>([])
const brokers = ref<any[]>([])
const dsComparison = ref<any[]>([])
const dataSourceLabels: Record<string, string> = {
  biying: '必盈(主力)',
  gm: '掘金(需终端)',
}

// 手动交易
const manualTrade = reactive({
  ts_code: '',
  stock_name: '',
  side: 'buy',
  quantity: 0,
  price: 0,
})

const executeManualTrade = async () => {
  if (!manualTrade.ts_code) return
  try {
    const res = await api.post(`${scannerApi}/trade`, {
      ts_code: manualTrade.ts_code,
      stock_name: manualTrade.stock_name,
      side: manualTrade.side,
      quantity: manualTrade.quantity || 0,
      price: manualTrade.price || 0,
      order_type: 'market',
      strategy: 'manual',
      reason: '手动操作',
    })
    if (res.data?.success) {
      const d = res.data.data
      ElMessage.success(`${d.side === 'buy' ? '买入' : '卖出'} ${d.ts_code} ${d.filled_qty}股@${d.filled_price}`)
      manualTrade.ts_code = ''
      manualTrade.stock_name = ''
      manualTrade.quantity = 0
      manualTrade.price = 0
      fetchAll(true)
    } else {
      ElMessage.error(`下单失败: ${res.data?.data?.message || '未知错误'}`)
    }
  } catch (e: any) {
    ElMessage.error(`下单失败: ${e.message}`)
  }
}

const resetCircuitBreaker = async () => {
  try {
    const res = await api.post(`${scannerApi}/circuit-breaker/reset`)
    if (res.data?.success) {
      ElMessage.success('熔断已重置')
      fetchAll(true)
    }
  } catch (e: any) {
    ElMessage.error(`重置失败: ${e.message}`)
  }
}

const fetchDataSources = async () => {
  try {
    const [srcRes, bkRes, cmpRes] = await Promise.all([
      api.get('/datasource/sources'),
      api.get('/datasource/brokers'),
      api.get('/datasource/comparison'),
    ])
    if (srcRes.data?.success) dataSources.value = srcRes.data.data || []
    if (bkRes.data?.success) brokers.value = bkRes.data.data || []
    if (cmpRes.data?.success) dsComparison.value = cmpRes.data.data || []
  } catch (e: any) {
    console.warn('数据源信息获取失败:', e.message)
  }
}

const switchDataSource = async (source: string) => {
  try {
    const res = await api.post('/datasource/switch', { source })
    if (res.data?.success) {
      ElMessage.success(`已切换到 ${dataSourceLabels[source] || source}`)
      fetchDataSources()
    }
  } catch (e: any) {
    ElMessage.error(`切换失败: ${e.message}`)
  }
}

// 初始加载数据源(fetchDataSources会在主onMounted中调用)

const isRunning = computed(() => status.value?.is_running ?? false)
const accountInfo = computed(() => status.value?.account ?? { total_assets: 0, available_cash: 0, market_value: 0, total_profit: 0 })

// ==================== Scanner Methods ====================

async function fetchScanner() {
  try {
    const [sR, sigR, posR, tlR] = await Promise.all([
      fetch(`${scannerApi}/status`).then(r => r.json()),
      fetch(`${scannerApi}/signals`).then(r => r.json()),
      fetch(`${scannerApi}/positions`).then(r => r.json()),
      fetch(`${scannerApi}/timeline`).then(r => r.json()),
    ])
    if (sR.success) status.value = sR.data
    if (sigR.success) signals.value = sigR.data
    if (posR.success) positions.value = posR.data
    if (tlR.success) timeline.value = tlR.data
  } catch (e) { console.error(e) }
}

async function startScanner() {
  await fetch(`${scannerApi}/start`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ account_id: 'default', trade_mode: tradeMode.value })
  })
  await fetchScanner()
}

async function stopScanner() {
  await fetch(`${scannerApi}/stop`, { method: 'POST' })
  await fetchScanner()
}

async function manualScan() {
  await fetch(`${scannerApi}/scan-once`, { method: 'POST' })
  await fetchScanner()
}

function toggleTradeMode() {
  if (isRunning.value) {
    ElMessage.warning('请先停止扫描器再切换模式')
    return
  }
  tradeMode.value = tradeMode.value === 'simulated' ? 'gm' : 'simulated'
}

// ==================== Strategy Config Methods ====================

async function fetchStrategies() {
  try {
    const [sRes, rRes] = await Promise.all([
      fetch(`${configApi}/strategies`).then(r => r.json()),
      fetch(`${configApi}/global-risk`).then(r => r.json()),
    ])
    if (sRes.success) strategies.value = sRes.data
    if (rRes.success) globalRisk.value = rRes.data
  } catch (e) { console.error(e) }
}

async function toggleStrategy(sid: string, enabled: boolean) {
  try {
    await fetch(`${configApi}/strategies/${sid}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled })
    })
    await fetchStrategies()
    ElMessage.success(enabled ? '已启用' : '已停用')
  } catch (e) { ElMessage.error('操作失败') }
}

function openEditDialog(strategy: StrategyConfig) {
  editingStrategy.value = strategy
  editParams.value = { ...strategy.params }
  editRiskParams.value = { ...strategy.riskParams }
  editTab.value = 'params'
  editDialogVisible.value = true
}

async function saveStrategy() {
  if (!editingStrategy.value) return
  saving.value = true
  try {
    await fetch(`${configApi}/strategies/${editingStrategy.value.id}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ params: editParams.value, riskParams: editRiskParams.value })
    })
    await fetchStrategies()
    editDialogVisible.value = false
    ElMessage.success('参数已保存')
  } catch (e) { ElMessage.error('保存失败') }
  finally { saving.value = false }
}

async function resetStrategy(sid: string) {
  try {
    await fetch(`${configApi}/reset/${sid}`, { method: 'POST' })
    await fetchStrategies()
    ElMessage.success('已重置为默认')
  } catch (e) { ElMessage.error('重置失败') }
}

// ==================== Lifecycle ====================

onMounted(async () => {
  await Promise.all([fetchScanner(), fetchStrategies(), fetchDataSources()])
  refreshTimer = setInterval(() => {
    if (!autoRefresh.value || activeTab.value !== 'scanner') return
    // 非交易时间降频(15秒), 交易时间5秒
    fetchScanner()
  }, 5000)
})
onUnmounted(() => { if (refreshTimer) clearInterval(refreshTimer) })
</script>

<template>
  <div class="market-monitor">
    <!-- 顶部状态栏 -->
    <div class="monitor-header">
      <div class="header-left">
        <div class="status-badge" :class="{ running: isRunning, stopped: !isRunning }">
          <span class="dot"></span>
          <span>{{ isRunning ? '扫描中' : '已停止' }}</span>
        </div>
      </div>

      <div class="header-stats" v-if="status">
        <div class="hs"><span class="hl">总资产</span><span class="hv">{{ (accountInfo.total_assets / 10000).toFixed(1) }}万</span></div>
        <div class="hs"><span class="hl">可用</span><span class="hv">{{ (accountInfo.available_cash / 10000).toFixed(1) }}万</span></div>
        <div class="hs"><span class="hl">市值</span><span class="hv">{{ (accountInfo.market_value / 10000).toFixed(1) }}万</span></div>
        <div class="hs"><span class="hl">盈亏</span><span class="hv" :class="accountInfo.total_profit >= 0 ? 'up' : 'down'">{{ accountInfo.total_profit >= 0 ? '+' : '' }}{{ accountInfo.total_profit.toFixed(0) }}</span></div>
        <div class="hs"><span class="hl">扫描</span><span class="hv">{{ status.stocks_scanned }}</span></div>
        <div class="hs"><span class="hl">信号</span><span class="hv">{{ status.active_signals }}</span></div>
      </div>

      <div class="header-actions">
        <ElButton v-if="!isRunning" type="success" size="small" @click="startScanner" :loading="loading">▶ 启动</ElButton>
        <ElButton v-else type="danger" size="small" @click="stopScanner">■ 停止</ElButton>
        <ElButton size="small" @click="manualScan" :disabled="isRunning">手动扫描</ElButton>
        <ElSwitch v-model="autoRefresh" size="small" active-text="自动" inactive-text="" />
        <ElTag size="small" :type="tradeMode === 'gm' ? 'warning' : 'info'" style="cursor:pointer" @click="toggleTradeMode">
          {{ tradeMode === 'gm' ? '🟢 掘金' : '🔵 仿真' }}
        </ElTag>
      </div>
    </div>

    <!-- Tab区域 -->
    <ElTabs v-model="activeTab" class="monitor-tabs">
      <!-- ==================== Tab1: 实时扫描 ==================== -->
      <ElTabPane label="📡 实时扫描" name="scanner">
        <div class="scanner-grid">
          <!-- 信号 -->
          <ElCard class="panel" shadow="never">
            <template #header>
              <div class="panel-header">
                <span>🎯 活跃信号</span>
                <ElBadge :value="signals.length" :max="99" />
              </div>
            </template>
            <div v-if="!signals.length" class="empty">启动扫描器或手动扫描</div>
            <div v-else class="signal-list">
              <div v-for="sig in signals" :key="sig.ts_code + sig.strategy" class="signal-row">
                <div class="sig-top">
                  <span class="code">{{ sig.ts_code }}</span>
                  <span class="name">{{ sig.stock_name }}</span>
                  <ElTag size="small" :color="strategyColor[sig.strategy]" style="color:#fff;border:none">{{ sig.strategy_name }}</ElTag>
                </div>
                <div class="sig-bot">
                  <span :class="sig.pct_chg >= 0 ? 'up' : 'down'">{{ sig.pct_chg >= 0 ? '+' : '' }}{{ sig.pct_chg.toFixed(1) }}%</span>
                  <span v-if="sig.volume_ratio" class="factor">量比{{ sig.volume_ratio.toFixed(1) }}</span>
                  <span v-if="sig.is_limit_up" class="limit-tag">涨停</span>
                  <span class="reason">{{ sig.reason }}</span>
                </div>
              </div>
            </div>
          </ElCard>

          <!-- 持仓 -->
          <ElCard class="panel" shadow="never">
            <template #header>
              <div class="panel-header">
                <span>📊 持仓监控</span>
                <ElBadge :value="positions.length" :max="99" />
              </div>
            </template>
            <div v-if="!positions.length" class="empty">暂无持仓</div>
            <div v-else class="pos-list">
              <div v-for="pos in positions" :key="pos.ts_code" class="pos-row">
                <div class="pos-top">
                  <span class="code">{{ pos.ts_code }}</span>
                  <span class="name">{{ pos.stock_name }}</span>
                  <ElTag size="small" :color="strategyColor[pos.strategy]" style="color:#fff;border:none; font-size:10px">{{ pos.strategy }}</ElTag>
                  <span :class="pos.profit_pct >= 0 ? 'up' : 'down'" class="pct">{{ pos.profit_pct >= 0 ? '+' : '' }}{{ pos.profit_pct.toFixed(1) }}%</span>
                </div>
                <div class="pos-bar-wrap">
                  <div class="pos-bar" :style="{
                    width: Math.min(Math.abs(pos.profit_pct) / 10 * 100, 100) + '%',
                    background: pos.profit_pct >= 0 ? '#67c23a' : '#f56c6c'
                  }"></div>
                </div>
                <div class="pos-bot">
                  <span>{{ pos.shares }}股 @{{ pos.cost_price.toFixed(2) }} → {{ pos.current_price.toFixed(2) }}</span>
                  <span v-if="pos.today_buy > 0" class="t1-tag">T+1</span>
                </div>
              </div>
            </div>
          </ElCard>

          <!-- 时间线 -->
          <ElCard class="panel" shadow="never">
            <template #header><span>⏱️ 今日时间线 ({{ timeline.length }})</span></template>
            <div v-if="!timeline.length" class="empty">暂无交易</div>
            <div v-else class="tl-list">
              <div v-for="(item, i) in timeline" :key="i" class="tl-row">
                <span class="tl-time">{{ item.time }}</span>
                <span class="tl-action" :class="item.action === 'buy' ? 'buy' : 'sell'">{{ item.action === 'buy' ? '买' : '卖' }}</span>
                <span class="code">{{ item.ts_code }}</span>
                <span class="name">{{ item.stock_name }}</span>
                <span class="tl-detail">{{ item.shares }}股@{{ item.price.toFixed(2) }}</span>
                <span v-if="item.profit_pct !== undefined" :class="item.profit_pct >= 0 ? 'up' : 'down'">
                  {{ item.profit_pct >= 0 ? '+' : '' }}{{ item.profit_pct.toFixed(1) }}%
                </span>
              </div>
            </div>
          </ElCard>

          <!-- 统计 -->
          <ElCard class="panel" shadow="never">
            <template #header><span>📈 今日统计</span></template>
            <div class="stats-grid" v-if="status">
              <div class="stat"><div class="sv">{{ status.stats.signals_found }}</div><div class="sl">信号</div></div>
              <div class="stat"><div class="sv">{{ status.stats.trades_executed }}</div><div class="sl">交易</div></div>
              <div class="stat"><div class="sv" style="color:#f56c6c">{{ status.stats.stop_losses }}</div><div class="sl">止损</div></div>
              <div class="stat"><div class="sv" style="color:#67c23a">{{ status.stats.take_profits }}</div><div class="sl">止盈</div></div>
              <div class="stat"><div class="sv">{{ status.stocks_scanned }}</div><div class="sl">扫描股票</div></div>
              <div class="stat"><div class="sv">{{ status.scan_count }}</div><div class="sl">扫描次数</div></div>
            </div>
          </ElCard>

          <!-- 手动交易 -->
          <ElCard class="panel" shadow="never">
            <template #header>
              <div style="display:flex;align-items:center;gap:8px">
                <span>🔧 手动交易</span>
                <ElTag v-if="status?.circuit_breaker?.trading_paused" type="danger" size="small">⚠️ 熔断中</ElTag>
              </div>
            </template>
            <div class="manual-trade">
              <div class="mt-row">
                <ElInput v-model="manualTrade.ts_code" placeholder="股票代码" size="small" style="width:120px" />
                <ElInput v-model="manualTrade.stock_name" placeholder="名称" size="small" style="width:80px" />
                <ElSelect v-model="manualTrade.side" size="small" style="width:80px">
                  <ElOption label="买入" value="buy" />
                  <ElOption label="卖出" value="sell" />
                </ElSelect>
                <ElInput v-model="manualTrade.quantity" type="number" placeholder="数量" size="small" style="width:80px" />
                <ElInput v-model="manualTrade.price" type="number" placeholder="价格(0=市价)" size="small" style="width:100px" />
                <ElButton type="primary" size="small" :disabled="!manualTrade.ts_code" @click="executeManualTrade">下单</ElButton>
              </div>
              <div class="mt-actions">
                <ElButton size="small" @click="fetchAll(true)" plain>🔄 刷新</ElButton>
                <ElButton v-if="status?.circuit_breaker?.trading_paused" type="warning" size="small" @click="resetCircuitBreaker">🔓 解除熔断</ElButton>
              </div>
            </div>
          </ElCard>
        </div>
      </ElTabPane>
      <ElTabPane label="🎛️ 策略配置" name="config">
        <div class="strategy-cards">
          <div v-for="s in strategies" :key="s.id" class="strat-card" :class="{ disabled: !s.enabled }">
            <div class="strat-top">
              <span class="strat-icon">{{ strategyIcon[s.id] || '📋' }}</span>
              <span class="strat-name">{{ s.name }}</span>
              <ElSwitch :model-value="s.enabled" @change="(v: boolean) => toggleStrategy(s.id, v)" size="small" />
            </div>

            <!-- 关键参数速览 -->
            <div class="strat-params">
              <div v-for="p in s.paramDescriptions.slice(0, 4)" :key="p.key" class="param-row">
                <span class="pk">{{ p.label }}</span>
                <span class="pv">{{ p.displayValue }}{{ p.unit }}</span>
              </div>
              <div v-if="s.paramDescriptions.length > 4" class="more">+{{ s.paramDescriptions.length - 4 }}项</div>
            </div>

            <!-- 风控速览 -->
            <div class="strat-risk">
              <span v-for="r in s.riskDescriptions.slice(0, 2)" :key="r.key" class="risk-tag">
                {{ r.label }} {{ r.displayValue }}{{ r.unit }}
              </span>
            </div>

            <div class="strat-actions">
              <ElButton size="small" type="primary" plain @click="openEditDialog(s)">编辑参数</ElButton>
              <ElButton size="small" plain @click="resetStrategy(s.id)">重置</ElButton>
            </div>
          </div>
        </div>

        <!-- 全局风控 -->
        <ElCard class="global-risk-card" shadow="never">
          <template #header><span>🛡️ 全局风控参数</span></template>
          <div class="global-risk-grid" v-if="globalRisk">
            <div class="gr-item"><span class="gr-label">默认止损</span><span class="gr-val">{{ (globalRisk.stop_loss_pct * 100).toFixed(1) }}%</span></div>
            <div class="gr-item"><span class="gr-label">默认止盈</span><span class="gr-val">{{ (globalRisk.take_profit_pct * 100).toFixed(1) }}%</span></div>
            <div class="gr-item"><span class="gr-label">最大持仓天数</span><span class="gr-val">{{ globalRisk.max_hold_days }}天</span></div>
            <div class="gr-item"><span class="gr-label">单票上限</span><span class="gr-val">{{ (globalRisk.max_position_per_stock * 100).toFixed(0) }}%</span></div>
            <div class="gr-item"><span class="gr-label">总仓位上限</span><span class="gr-val">{{ (globalRisk.max_total_position * 100).toFixed(0) }}%</span></div>
            <div class="gr-item"><span class="gr-label">滑点</span><span class="gr-val">{{ (globalRisk.slippage_pct * 100).toFixed(1) }}%</span></div>
          </div>
        </ElCard>
      </ElTabPane>

      <!-- ==================== Tab: 数据源管理 ==================== -->
      <ElTabPane label="🔌 数据源" name="datasource">
        <div class="datasource-panel">
          <!-- 数据源状态 -->
          <ElCard class="ds-card" shadow="never">
            <template #header><div class="card-header">数据源状态</div></template>
            <div class="ds-sources">
              <div v-for="src in dataSources" :key="src.name" class="ds-source-item" :class="{ active: src.active }">
                <div class="ds-source-header">
                  <span class="ds-name">{{ dataSourceLabels[src.name] || src.name }}</span>
                  <ElTag :type="src.available ? 'success' : 'danger'" size="small">
                    {{ src.available ? '可用' : '不可用' }}
                  </ElTag>
                  <ElTag v-if="src.active" type="warning" size="small" effect="dark">当前</ElTag>
                </div>
                <div class="ds-source-detail">
                  <span v-if="src.daily_limit">调用: {{ src.daily_calls }}/{{ src.daily_limit }}/日</span>
                  <span v-if="src.last_error" class="ds-error">{{ src.last_error }}</span>
                </div>
                <ElButton v-if="src.available && !src.active" size="small" type="primary" plain @click="switchDataSource(src.name)">切换</ElButton>
              </div>
            </div>
          </ElCard>

          <!-- 券商状态 -->
          <ElCard class="ds-card" shadow="never">
            <template #header><div class="card-header">券商/交易</div></template>
            <div class="ds-brokers">
              <div v-for="b in brokers" :key="b.name" class="ds-source-item">
                <div class="ds-source-header">
                  <span class="ds-name">{{ b.label }}</span>
                  <ElTag :type="b.available ? 'success' : 'info'" size="small">
                    {{ b.available ? '已连接' : '未配置' }}
                  </ElTag>
                </div>
                <div class="ds-source-detail">{{ b.description }}</div>
                <div class="ds-source-detail ds-requires">需要: {{ b.requires }}</div>
              </div>
            </div>
          </ElCard>

          <!-- 能力对比 -->
          <ElCard class="ds-card" shadow="never">
            <template #header><div class="card-header">数据源对比</div></template>
            <div class="ds-comparison">
              <table class="ds-table">
                <thead>
                  <tr><th>维度</th><th>必盈</th><th>掘金</th></tr>
                </thead>
                <tbody>
                  <tr v-for="row in dsComparison" :key="row.dimension">
                    <td>{{ row.dimension }}</td>
                    <td>{{ row.biying }}</td>
                    <td>{{ row.gm }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </ElCard>
        </div>
      </ElTabPane>
    </ElTabs>

    <!-- ==================== 编辑参数弹窗 ==================== -->
    <ElDialog v-model="editDialogVisible" :title="`编辑 ${editingStrategy?.name}`" width="560px" :close-on-click-modal="false">
      <ElTabs v-model="editTab">
        <ElTabPane label="选股参数" name="params">
          <div class="edit-grid">
            <div v-for="p in editingStrategy?.paramDescriptions || []" :key="p.key" class="edit-item">
              <label>{{ p.label }} <span v-if="p.unit" class="unit">({{ p.unit }})</span></label>
              <ElSwitch v-if="p.type === 'boolean'" v-model="editParams[p.key]" />
              <ElInputNumber v-else-if="p.type === 'number'" v-model="editParams[p.key]"
                :step="0.01" :precision="2" size="default" controls-position="right" style="width:140px" />
              <input v-else v-model="editParams[p.key]" class="text-input" />
            </div>
          </div>
        </ElTabPane>
        <ElTabPane label="风控参数" name="risk">
          <div class="edit-grid">
            <div v-for="r in editingStrategy?.riskDescriptions || []" :key="r.key" class="edit-item">
              <label>{{ r.label }} <span v-if="r.unit" class="unit">({{ r.unit }})</span></label>
              <ElInputNumber v-model="editRiskParams[r.key]" :step="0.001" :precision="3"
                size="default" controls-position="right" style="width:140px" />
            </div>
          </div>
        </ElTabPane>
      </ElTabs>
      <template #footer>
        <ElButton @click="editDialogVisible = false">取消</ElButton>
        <ElButton type="primary" :loading="saving" @click="saveStrategy">保存</ElButton>
      </template>
    </ElDialog>
  </div>
</template>

<style scoped lang="scss">
.market-monitor { height: 100%; display: flex; flex-direction: column; }

/* === 顶部状态栏 === */
.monitor-header {
  display: flex; align-items: center; gap: 12px; padding: 10px 16px;
  background: var(--el-fill-color-lighter); border-radius: 8px; flex-wrap: wrap; flex-shrink: 0;
}
.header-left { display: flex; align-items: center; gap: 8px; }
.status-badge { display: flex; align-items: center; gap: 5px; font-weight: 600; font-size: 13px; }
.dot { width: 8px; height: 8px; border-radius: 50%; }
.running .dot { background: #67c23a; animation: pulse 1.5s infinite; }
.stopped .dot { background: #909399; }
.running { color: #67c23a; } .stopped { color: #909399; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }

.header-stats { display: flex; gap: 14px; flex: 1; }
.hs { display: flex; flex-direction: column; }
.hl { font-size: 10px; color: #909399; }
.hv { font-size: 14px; font-weight: 700; }
.up { color: #f56c6c; } .down { color: #67c23a; }

.header-actions { display: flex; align-items: center; gap: 6px; }

/* === Tabs === */
.monitor-tabs { flex: 1; display: flex; flex-direction: column; }
.monitor-tabs :deep(.el-tabs__content) { flex: 1; overflow: auto; }

/* === 扫描器Grid === */
.scanner-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.panel { min-height: 180px; }
.panel-header { display: flex; align-items: center; gap: 8px; }

.empty { color: #909399; text-align: center; padding: 24px 0; font-size: 12px; }

/* 信号 */
.signal-list, .pos-list, .tl-list { max-height: 340px; overflow-y: auto; }
.signal-row { padding: 6px 0; border-bottom: 1px solid #f5f5f5; }
.sig-top { display: flex; align-items: center; gap: 5px; }
.sig-bot { display: flex; align-items: center; gap: 6px; margin-top: 2px; font-size: 11px; }
.factor { color: #909399; } .limit-tag { color: #f56c6c; font-weight: 600; }
.reason { color: #c0c4cc; flex: 1; text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* 持仓 */
.pos-row { padding: 6px 0; border-bottom: 1px solid #f5f5f5; }
.pos-top { display: flex; align-items: center; gap: 5px; }
.pct { font-weight: 700; font-size: 13px; }
.pos-bar-wrap { height: 3px; background: #ebeef5; border-radius: 2px; margin: 3px 0; overflow: hidden; }
.pos-bar { height: 100%; border-radius: 2px; transition: width .3s; }
.pos-bot { display: flex; justify-content: space-between; font-size: 10px; color: #909399; }
.t1-tag { background: #e6a23c; color: #fff; font-size: 9px; padding: 0 3px; border-radius: 2px; }

/* 时间线 */
.tl-row { display: flex; align-items: center; gap: 5px; padding: 3px 0; font-size: 11px; border-bottom: 1px solid #fafafa; }
.tl-time { color: #909399; font-family: monospace; min-width: 48px; }
.tl-action { font-weight: 600; min-width: 20px; }
.tl-action.buy { color: #f56c6c; } .tl-action.sell { color: #67c23a; }
.tl-detail { color: #909399; }

/* 统计 */
.stats-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; text-align: center; }
.stat { padding: 8px; }
.sv { font-size: 22px; font-weight: 700; }
.sl { font-size: 10px; color: #909399; margin-top: 2px; }

/* 公共 */
.code { font-weight: 700; font-family: monospace; font-size: 12px; }
.name { font-size: 11px; color: #606266; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* === 策略配置 === */
.strategy-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 12px; }
.strat-card {
  background: var(--el-bg-color-overlay, #fff); border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px; padding: 14px; transition: all .2s;
}
.strat-card:hover { border-color: var(--el-border-color); box-shadow: 0 2px 8px rgba(0,0,0,.06); }
.strat-card.disabled { opacity: .55; }
.strat-top { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.strat-icon { font-size: 20px; }
.strat-name { font-weight: 700; font-size: 15px; flex: 1; }
.strat-params { margin-bottom: 8px; }
.param-row { display: flex; justify-content: space-between; font-size: 12px; padding: 2px 0; }
.pk { color: #606266; } .pv { font-weight: 600; font-family: monospace; }
.more { font-size: 11px; color: #c0c4cc; text-align: center; margin-top: 2px; }
.strat-risk { display: flex; gap: 6px; margin-bottom: 10px; flex-wrap: wrap; }
.risk-tag { font-size: 11px; color: #909399; background: var(--el-fill-color-light); padding: 2px 6px; border-radius: 4px; }
.strat-actions { display: flex; gap: 6px; }

/* 全局风控 */
.global-risk-card { margin-top: 12px; }
.global-risk-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.gr-item { display: flex; flex-direction: column; align-items: center; padding: 6px; }
.gr-label { font-size: 11px; color: #909399; }
.gr-val { font-size: 15px; font-weight: 700; }

/* === 编辑弹窗 === */
.edit-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.edit-item { display: flex; flex-direction: column; gap: 4px; }
.edit-item label { font-size: 12px; color: #606266; }
.edit-item .unit { color: #c0c4cc; font-size: 11px; }
.text-input {
  border: 1px solid var(--el-border-color); border-radius: 4px; padding: 4px 8px;
  font-size: 13px; width: 140px;
}

@media (max-width: 900px) {
  .scanner-grid { grid-template-columns: 1fr; }
  .strategy-cards { grid-template-columns: 1fr; }
  .edit-grid { grid-template-columns: 1fr; }
}

/* === 数据源管理 === */
.datasource-panel { display: flex; flex-direction: column; gap: 16px; }
.ds-card { margin-bottom: 0; }
.ds-card .card-header { font-weight: 600; font-size: 14px; }
.ds-sources, .ds-brokers { display: flex; flex-direction: column; gap: 10px; }
.ds-source-item {
  display: flex; align-items: center; gap: 10px; padding: 10px 14px;
  border: 1px solid var(--el-border-color-lighter); border-radius: 8px;
  background: #fafbfc; transition: all 0.2s;
}
.ds-source-item.active { border-color: var(--el-color-primary); background: #ecf5ff; }
.ds-source-header { display: flex; align-items: center; gap: 8px; min-width: 180px; }
.ds-name { font-weight: 600; font-size: 14px; }
.ds-source-detail { font-size: 12px; color: #909399; flex: 1; display: flex; gap: 12px; }
.ds-error { color: var(--el-color-danger); }
.ds-requires { font-size: 11px; color: #b0b0b0; font-style: italic; }
.ds-comparison { overflow-x: auto; }
.ds-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.ds-table th, .ds-table td { padding: 6px 10px; border: 1px solid #ebeef5; text-align: left; }
.ds-table th { background: #f5f7fa; font-weight: 600; white-space: nowrap; }
.ds-table td { white-space: nowrap; }

/* === 手动交易 === */
.manual-trade { display: flex; flex-direction: column; gap: 10px; }
.mt-row { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.mt-actions { display: flex; gap: 8px; }
</style>
