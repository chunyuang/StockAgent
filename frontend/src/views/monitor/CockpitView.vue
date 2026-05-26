<script setup lang="ts">
/**
 * CockpitView — 驾驶舱视图 (交易员视角)
 * 
 * 布局: 
 * 顶: 状态栏(模式+资产+紧急平仓)
 * 左: 风控仪表盘
 * 中: 核心实时区(信号+9层管道)
 * 右: 持仓盈亏波动
 * 底: 时间线
 */
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import {
  ElCard, ElButton, ElTag, ElProgress, ElBadge, ElTooltip,
  ElEmpty, ElTable, ElTableColumn, ElTabs, ElTabPane,
  ElMessage, ElMessageBox, ElDialog,
} from 'element-plus'
import { api } from '@/api/client'

// ============ 类型 ============
interface HealthCheck { name: string; status: string; value: string; threshold: string; message: string }
interface HealthInfo { overall_status: string; checks: Record<string, HealthCheck>; alert_count: number }
interface ScanSignal { ts_code: string; stock_name: string; strategy: string; strategy_name: string; price: number; pct_chg: number; reason: string; signal_status?: string; created_at?: number }
interface PositionInfo { ts_code: string; stock_name: string; strategy: string; shares: number; available_qty: number; cost_price: number; current_price: number; profit_pct: number; profit_amount?: number; market_value?: number; stop_loss_pct?: number; take_profit_pct?: number; stop_loss_price?: number; take_profit_price?: number; distance_to_stop?: number }
interface AccountInfo { total_assets: number; available_cash: number; market_value: number; total_profit: number }
interface TimelineItem { time: string; action: string; ts_code: string; stock_name: string; strategy: string; shares: number; price: number; reason: string; profit_pct?: number }

// ============ 状态 ============
const scannerApi = '/scanner'
const status = ref<any>(null)
const health = ref<HealthInfo | null>(null)
const signals = ref<ScanSignal[]>([])
const positions = ref<PositionInfo[]>([])
const timeline = ref<TimelineItem[]>([])
const pnlHistory = ref<{time: string, value: number}[]>([])
const loading = ref(false)
const autoRefresh = ref(true)
let refreshTimer: any = null
let ws: WebSocket | null = null
let wsReconnectTimer: any = null
const nowMs = ref(Date.now())
let nowTimer: any = null

// ============ 策略元数据 ============
const strategyMeta: Record<string, { color: string; icon: string; cn: string }> = {
  halfway_chase: { color: '#e6a23c', icon: '🚀', cn: '半路追涨' },
  first_limit_up: { color: '#f56c6c', icon: '🔥', cn: '首板打板' },
  dragon_head: { color: '#409eff', icon: '🐉', cn: '龙头低吸' },
  limit_down_qiao: { color: '#67c23a', icon: '💪', cn: '跌停翘板' },
  anomaly_surge: { color: '#e6a23c', icon: '⚡', cn: '急速拉升' },
  anomaly_broken: { color: '#f56c6c', icon: '💔', cn: '涨停炸板' },
  anomaly_strong: { color: '#409eff', icon: '💪', cn: '强势涨停' },
}
const strategyCN = (s: string) => strategyMeta[s]?.cn || s
const strategyColor = (s: string) => strategyMeta[s]?.color || '#909399'
const strategyIcon = (s: string) => strategyMeta[s]?.icon || '📊'

// ============ 计算 ============
const account = computed<AccountInfo>(() => status.value?.account ?? { total_assets: 0, available_cash: 0, market_value: 0, total_profit: 0 })
const positionRatio = computed(() => account.value.market_value > 0 ? (account.value.market_value / account.value.total_assets * 100).toFixed(1) : '0')
const isRunning = computed(() => status.value?.is_running ?? false)
const tradeMode = computed(() => status.value?.trade_mode ?? 'simulated')
const tradeModeLabel = computed(() => {
  const m: Record<string, { text: string; color: string }> = {
    simulated: { text: '模拟', color: '#67c23a' },
    gm: { text: '掘金', color: '#409eff' },
    dry_run: { text: '调试', color: '#e6a23c' },
  }
  return m[tradeMode.value] || { text: tradeMode.value, color: '#909399' }
})

// 风控仪表盘
const healthStatus = computed(() => health.value?.overall_status ?? 'unknown')
const healthColor = computed(() => {
  const c: Record<string, string> = { healthy: '#67c23a', degraded: '#e6a23c', critical: '#f56c6c', dead: '#303133' }
  return c[healthStatus.value] || '#909399'
})
const dailyDrawdown = computed(() => {
  const dd = health.value?.checks?.drawdown
  if (!dd) return { value: 0, threshold: 5, status: 'healthy' }
  const match = dd.value?.match(/日([\d.]+)%/)
  return { value: parseFloat(match?.[1] || '0'), threshold: 5, status: dd.status }
})
const consecutiveLosses = computed(() => {
  const cb = status.value?.circuit_breaker
  return cb?.consecutive_losses ?? 0
})

// 信号过期倒计时
const SIGNAL_EXPIRE_MS = 300000
function signalRemaining(sig: ScanSignal): number {
  if (!sig.created_at || sig.created_at <= 0) return -1
  return Math.max(0, SIGNAL_EXPIRE_MS - (nowMs.value / 1000 - sig.created_at) * 1000)
}
function formatRemaining(ms: number): string {
  if (ms < 0) return ''
  const s = Math.floor(ms / 1000)
  if (s < 60) return `${s}s`
  return `${Math.floor(s / 60)}m${s % 60}s`
}

// 信号详情弹窗
const signalDetail = ref<ScanSignal | null>(null)
const signalDetailVisible = ref(false)
function showSignalDetail(sig: ScanSignal) {
  signalDetail.value = sig
  signalDetailVisible.value = true
}
const pipelineLayers = ['L1_force_empty', 'L2_special_period', 'L3_sentiment', 'L4_premarket', 'L5_auction', 'L6_strategy', 'L7_ranking', 'L8_position']
const pipelineLabels: Record<string, string> = { L1_force_empty: '强制空仓', L2_special_period: '特殊时期', L3_sentiment: '情绪周期', L4_premarket: '盘前预选', L5_auction: '竞价过滤', L6_strategy: '策略量能', L7_ranking: '综合排序', L8_position: '仓位控制' }

// 盈亏曲线
const pnlOption = computed(() => ({
  grid: { top: 10, right: 10, bottom: 20, left: 50 },
  xAxis: { type: 'category', data: pnlHistory.value.map(p => p.time), axisLabel: { color: 'var(--text-tertiary)', fontSize: 10 } },
  yAxis: { type: 'value', axisLabel: { color: 'var(--text-tertiary)', fontSize: 10 }, splitLine: { lineStyle: { color: 'var(--border-light)' } } },
  series: [{
    type: 'line', data: pnlHistory.value.map(p => p.value), smooth: true,
    lineStyle: { color: 'var(--stock-down)', width: 2 },
    areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'var(--stock-down-bg)' }, { offset: 1, color: 'rgba(0,0,0,0)' }] } },
  }],
  backgroundColor: 'transparent',
}))

// ============ API ============
async function fetchAll() {
  try {
    const r = await api.get(`${scannerApi}/all`)
    if (r?.success) {
      status.value = r.status
      signals.value = r.signals || []
      positions.value = r.positions || []
      timeline.value = r.timeline || []
      // 更新盈亏曲线
      const pnl = account.value.total_profit
      pnlHistory.value.push({ time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }), value: pnl })
      if (pnlHistory.value.length > 60) pnlHistory.value = pnlHistory.value.slice(-60)
    }
  } catch (e) { /* ignore */ }
}
async function fetchHealth() {
  try {
    const r = await api.get(`${scannerApi}/health`)
    if (r?.success) health.value = r.health
  } catch (e) { /* ignore */ }
}

// ============ 操作 ============
async function toggleScanner() {
  loading.value = true
  try {
    if (isRunning.value) {
      await ElMessageBox.confirm('确认停止扫描器？持仓将保留。', '停止扫描', { confirmButtonText: '确认停止', cancelButtonText: '取消', type: 'warning' })
      await api.post(`${scannerApi}/stop`)
      ElMessage.success('扫描器已停止')
    } else {
      // 二次确认并显示当前账户摘要
      const acc = account.value
      await ElMessageBox.confirm(
        `确认启动扫描器？\n模式: ${tradeModeLabel.text}\n可用资金: ¥${(acc.available_cash / 10000).toFixed(1)}万\n当前持仓: ${positions.value.length}只`,
        '启动扫描',
        { confirmButtonText: '确认启动', cancelButtonText: '取消', type: 'info' }
      )
      await api.post(`${scannerApi}/start`, { trade_mode: tradeMode.value })
      ElMessage.success('扫描器已启动')
    }
    await fetchAll()
  } catch { /* cancelled or error */ }
  loading.value = false
}

async function emergencyLiquidate() {
  try {
    await ElMessageBox.confirm('⚠️ 确认紧急平仓？所有持仓将以市价卖出！', '🚨 紧急平仓', { confirmButtonText: '确认平仓', cancelButtonText: '取消', type: 'error' })
    loading.value = true
    const r = await api.post(`${scannerApi}/emergency-liquidate`, { reason: 'GUI手动触发' })
    if (r?.success) ElMessage.success(`紧急平仓完成: ${r.data?.positions_cleared}只持仓已清空`)
    else ElMessage.error(r?.message || '平仓失败')
    await fetchAll()
  } catch { /* cancelled */ }
  loading.value = false
}

// ============ WebSocket ============
function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  ws = new WebSocket(`${proto}://${location.host}/ws`)
  ws.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data)
      if (data.type === 'scanner_signal' && data.data) signals.value.unshift(data.data)
      if (data.type === 'scanner_position' && data.data) positions.value = data.data
      if (data.type === 'scanner_status' && data.data) status.value = data.data
      if (data.type === 'scanner_timeline' && data.data) timeline.value.unshift(data.data)
    } catch { /* ignore */ }
  }
  ws.onclose = () => { wsReconnectTimer = setTimeout(connectWS, 5000) }
  ws.onerror = () => { ws?.close() }
}

// ============ 生命周期 ============
onMounted(() => {
  fetchAll(); fetchHealth()
  refreshTimer = setInterval(() => { if (autoRefresh.value) { fetchAll(); fetchHealth() } }, 5000)
  nowTimer = setInterval(() => { nowMs.value = Date.now() }, 1000)
  connectWS()
})
onUnmounted(() => {
  clearInterval(refreshTimer); clearInterval(nowTimer); clearTimeout(wsReconnectTimer)
  ws?.close()
})
</script>

<template>
  <div class="cockpit">
    <!-- ===== 顶部状态栏 ===== -->
    <div class="top-bar">
      <div class="top-left">
        <span class="mode-badge" :style="{ background: tradeModeLabel.color }">{{ tradeModeLabel.text }}</span>
        <span class="asset-info">
          资产 <b>¥{{ (account.total_assets / 10000).toFixed(1) }}万</b>
          <span class="divider">|</span>
          可用 <b>¥{{ (account.available_cash / 10000).toFixed(1) }}万</b>
          <span class="divider">|</span>
          仓位 <b>{{ positionRatio }}%</b>
          <span class="divider">|</span>
          盈亏 <b :class="account.total_profit >= 0 ? 'profit' : 'loss'">{{ account.total_profit >= 0 ? '+' : '' }}¥{{ account.total_profit.toFixed(0) }}</b>
        </span>
      </div>
      <div class="top-right">
        <ElButton :type="isRunning ? 'danger' : 'success'" size="small" @click="toggleScanner" :loading="loading">
          {{ isRunning ? '停止' : '启动' }}
        </ElButton>
        <ElButton type="danger" size="small" class="emergency-btn" @click="emergencyLiquidate" :disabled="!isRunning">
          🚨 紧急平仓
        </ElButton>
      </div>
    </div>

    <!-- ===== 三列主体 ===== -->
    <div class="main-grid">

      <!-- ===== 左: 风控仪表盘 ===== -->
      <div class="panel risk-panel">
        <div class="panel-title">🛡️ 风控仪表盘</div>
        
        <!-- 日回撤 -->
        <div class="risk-item">
          <div class="risk-label">日回撤</div>
          <ElProgress 
            :percentage="Math.min(100, dailyDrawdown.value / dailyDrawdown.threshold * 100)" 
            :color="dailyDrawdown.value < 2 ? '#67c23a' : dailyDrawdown.value < 4 ? '#e6a23c' : '#f56c6c'"
            :stroke-width="12"
            :format="() => `${dailyDrawdown.value.toFixed(1)}%`"
          />
          <div class="risk-threshold">阈值 {{ dailyDrawdown.threshold }}%</div>
        </div>

        <!-- 连续亏损 -->
        <div class="risk-item">
          <div class="risk-label">连续亏损</div>
          <div class="loss-boxes">
            <span v-for="i in 3" :key="i" class="loss-box" :class="{ filled: i <= consecutiveLosses }">▲</span>
            <span class="loss-count">{{ consecutiveLosses }}/3次</span>
          </div>
        </div>

        <!-- 熔断状态 -->
        <div class="risk-item">
          <div class="risk-label">熔断状态</div>
          <div class="circuit-status" :class="healthStatus">
            <span class="circuit-dot" :style="{ background: healthColor }"></span>
            {{ { healthy: '🟢 正常', degraded: '🟡 预警', critical: '🔴 熔断', dead: '⚫ 失联', unknown: '⚪ 未知' }[healthStatus] || '⚪ 未知' }}
          </div>
        </div>

        <!-- 策略健康 -->
        <div class="risk-item">
          <div class="risk-label">策略健康</div>
          <div class="strategy-health-list">
            <div v-for="meta in strategyMeta" :key="meta.cn" class="strategy-health-item">
              <span>{{ meta.icon }} {{ meta.cn }}</span>
              <ElTag size="small" type="info">✅</ElTag>
            </div>
          </div>
        </div>

        <!-- 看门狗详情 -->
        <div v-if="health?.checks" class="watchdog-details">
          <div v-for="(check, name) in health.checks" :key="name" class="watchdog-item">
            <span class="wd-name">{{ name }}</span>
            <span class="wd-status" :class="check.status">{{ { healthy: '✅', degraded: '⚠️', critical: '🔴', dead: '⚫' }[check.status] || '❓' }}</span>
          </div>
        </div>
      </div>

      <!-- ===== 中: 核心实时区 ===== -->
      <div class="panel center-panel">
        <div class="panel-title">📡 实时信号</div>
        
        <!-- 信号列表 -->
        <div class="signal-list">
          <div v-if="signals.length === 0" class="no-signals">
            <ElEmpty description="暂无信号" :image-size="60" />
          </div>
          <div v-for="sig in signals.slice(0, 10)" :key="sig.ts_code + sig.strategy" class="signal-card" :style="{ borderLeftColor: strategyColor(sig.strategy) }" @click="showSignalDetail(sig)">
            <div class="sig-header">
              <span class="sig-icon">{{ strategyIcon(sig.strategy) }}</span>
              <span class="sig-strategy" :style="{ color: strategyColor(sig.strategy) }">{{ sig.strategy_name }}</span>
              <span class="sig-code">{{ sig.ts_code }} {{ sig.stock_name }}</span>
              <span class="sig-pct" :class="sig.pct_chg >= 0 ? 'profit' : 'loss'">
                {{ sig.pct_chg >= 0 ? '+' : '' }}{{ sig.pct_chg.toFixed(1) }}%
              </span>
              <span v-if="signalRemaining(sig) >= 0" class="sig-countdown">⏱{{ formatRemaining(signalRemaining(sig)) }}</span>
            </div>
            <div class="sig-reason">{{ sig.reason }}</div>
          </div>
        </div>

        <!-- 9层管道可视化 -->
        <div class="pipeline-viz">
          <div class="pipeline-title">9层筛选管道</div>
          <div class="pipeline-flow">
            <template v-for="(layer, i) in pipelineLayers" :key="layer">
              <div class="pipe-node">
                <span class="pipe-label">{{ pipelineLabels[layer] || layer }}</span>
                <span class="pipe-status">✅</span>
              </div>
              <span v-if="i < pipelineLayers.length - 1" class="pipe-arrow">→</span>
            </template>
          </div>
        </div>
      </div>

      <!-- ===== 右: 持仓盈亏 ===== -->
      <div class="panel right-panel">
        <div class="panel-title">📊 持仓盈亏</div>
        
        <!-- 盈亏曲线 -->
        <div class="pnl-chart">
          <v-chart :option="pnlOption" autoresize style="height: 160px" />
        </div>

        <!-- 总盈亏 -->
        <div class="total-pnl" :class="account.total_profit >= 0 ? 'profit' : 'loss'">
          {{ account.total_profit >= 0 ? '+' : '' }}¥{{ account.total_profit.toFixed(0) }}
        </div>

        <!-- 资金信息 -->
        <div class="fund-info">
          <div class="fund-row">
            <span>可用资金</span>
            <span>¥{{ (account.available_cash / 10000).toFixed(1) }}万</span>
          </div>
          <div class="fund-row">
            <span>占用保证金</span>
            <span>¥{{ (account.market_value / 10000).toFixed(1) }}万</span>
          </div>
        </div>

        <!-- 持仓列表(紧凑) -->
        <div class="pos-list">
          <div v-for="pos in positions.slice(0, 5)" :key="pos.ts_code" class="pos-item">
            <span class="pos-code">{{ pos.ts_code }} {{ pos.stock_name }}</span>
            <span class="pos-pnl" :class="pos.profit_pct >= 0 ? 'profit' : 'loss'">
              {{ pos.profit_pct >= 0 ? '+' : '' }}{{ pos.profit_pct.toFixed(1) }}%
            </span>
          </div>
          <div v-if="positions.length > 5" class="pos-more">... 共{{ positions.length }}只</div>
        </div>
      </div>
    </div>

    <!-- ===== 信号详情弹窗 ===== -->
    <ElDialog v-model="signalDetailVisible" :title="signalDetail ? `${signalDetail.ts_code} ${signalDetail.stock_name}` : ''" width="480px" destroy-on-close>
      <div v-if="signalDetail" class="sig-detail">
        <div class="sig-detail-row"><span class="sig-detail-label">策略</span><span :style="{ color: strategyColor(signalDetail.strategy) }">{{ strategyIcon(signalDetail.strategy) }} {{ signalDetail.strategy_name }}</span></div>
        <div class="sig-detail-row"><span class="sig-detail-label">价格</span><span>¥{{ signalDetail.price?.toFixed(2) }}</span></div>
        <div class="sig-detail-row"><span class="sig-detail-label">涨幅</span><span :class="signalDetail.pct_chg >= 0 ? 'profit' : 'loss'">{{ signalDetail.pct_chg >= 0 ? '+' : '' }}{{ signalDetail.pct_chg?.toFixed(2) }}%</span></div>
        <div class="sig-detail-row"><span class="sig-detail-label">原因</span><span>{{ signalDetail.reason }}</span></div>
        <div class="sig-detail-pipeline">
          <div class="sig-detail-pipeline-title">9层筛选管道通过详情</div>
          <div class="pipeline-flow">
            <template v-for="(layer, i) in pipelineLayers" :key="layer">
              <div class="pipe-node"><span class="pipe-label">{{ pipelineLabels[layer] }}</span><span class="pipe-status">✅</span></div>
              <span v-if="i < pipelineLayers.length - 1" class="pipe-arrow">→</span>
            </template>
          </div>
        </div>
      </div>
    </ElDialog>

    <!-- ===== 底部时间线 ===== -->
    <div class="timeline-bar">
      <span class="timeline-label">📋 时间线</span>
      <div class="timeline-scroll">
        <span v-for="item in timeline.slice(0, 20)" :key="item.time + item.ts_code" class="tl-item" :class="item.action">
          {{ item.time }} 
          <ElTag size="small" :type="item.action === 'buy' ? 'danger' : item.action === 'sell' ? 'success' : 'info'" effect="dark">
            {{ item.action === 'buy' ? '买' : item.action === 'sell' ? '卖' : item.action }}
          </ElTag>
          {{ item.ts_code }} {{ item.stock_name }}
          <span v-if="item.profit_pct != null" :class="item.profit_pct >= 0 ? 'profit' : 'loss'">
            {{ item.profit_pct >= 0 ? '+' : '' }}{{ item.profit_pct.toFixed(1) }}%
          </span>
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.cockpit { display: flex; flex-direction: column; height: 100vh; background: var(--bg-base); color: var(--text-secondary); font-size: 13px; }

/* 顶部状态栏 */
.top-bar { display: flex; justify-content: space-between; align-items: center; padding: 8px 16px; background: var(--bg-elevated); border-bottom: 1px solid var(--border-default); }
.top-left { display: flex; align-items: center; gap: 12px; }
.top-right { display: flex; gap: 8px; }
.mode-badge { padding: 2px 10px; border-radius: 4px; font-weight: bold; color: var(--text-primary); font-size: 12px; }
.asset-info { font-size: 13px; color: var(--text-tertiary); }
.asset-info b { color: var(--text-primary); }
.divider { color: var(--text-quaternary, var(--text-tertiary)); margin: 0 4px; }
.profit { color: var(--stock-down); }
.loss { color: var(--stock-up); }
.emergency-btn { animation: pulse 2s infinite; }
@keyframes pulse { 0%, 100% { box-shadow: 0 0 0 0 rgba(245,108,108,0.4); } 50% { box-shadow: 0 0 0 6px rgba(245,108,108,0); } }

/* 三列主体 */
.main-grid { display: grid; grid-template-columns: 240px 1fr 280px; gap: 12px; padding: 12px; flex: 1; overflow: hidden; }
.panel { background: var(--bg-elevated); border-radius: 8px; padding: 12px; border: 1px solid var(--border-default); overflow-y: auto; }
.panel-title { font-size: 14px; font-weight: bold; margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px solid var(--border-default); }

/* 风控仪表盘 */
.risk-item { margin-bottom: 16px; }
.risk-label { font-size: 12px; color: var(--text-tertiary); margin-bottom: 4px; }
.risk-threshold { font-size: 11px; color: var(--text-muted); margin-top: 2px; }
.loss-boxes { display: flex; gap: 6px; align-items: center; }
.loss-box { font-size: 18px; color: var(--border-default); transition: color 0.3s; }
.loss-box.filled { color: #f56c6c; }
.loss-count { font-size: 12px; color: var(--text-tertiary); margin-left: 8px; }
.circuit-status { font-size: 14px; font-weight: bold; }
.circuit-dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; animation: blink 1.5s infinite; }
.circuit-status.critical .circuit-dot { animation: blink 0.5s infinite; }
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
.strategy-health-item { display: flex; justify-content: space-between; padding: 3px 0; font-size: 12px; }
.watchdog-details { margin-top: 12px; padding-top: 8px; border-top: 1px solid var(--border-default); }
.watchdog-item { display: flex; justify-content: space-between; font-size: 11px; padding: 2px 0; }
.wd-name { color: #888; }

/* 核心实时区 */
.signal-list { flex: 1; }
.signal-card { background: var(--bg-muted); border-radius: 6px; padding: 8px 10px; margin-bottom: 6px; border-left: 3px solid var(--primary-500); }
.sig-header { display: flex; align-items: center; gap: 6px; }
.sig-icon { font-size: 16px; }
.sig-strategy { font-weight: bold; font-size: 13px; }
.sig-code { color: var(--text-tertiary); font-size: 12px; }
.sig-pct { font-weight: bold; margin-left: auto; }
.sig-countdown { font-size: 11px; color: #e6a23c; }
.sig-reason { font-size: 11px; color: var(--text-tertiary); margin-top: 4px; }
.no-signals { padding: 20px 0; }

/* 9层管道 */
.pipeline-viz { margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border-default); }
.pipeline-title { font-size: 13px; font-weight: bold; margin-bottom: 8px; }
.pipeline-flow { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
.pipe-node { background: var(--bg-muted); padding: 3px 8px; border-radius: 4px; font-size: 11px; }
.pipe-label { color: var(--text-tertiary); margin-right: 4px; }
.pipe-status { font-size: 10px; }
.pipe-arrow { color: var(--text-muted); font-size: 12px; }

/* 持仓盈亏 */
.pnl-chart { margin-bottom: 8px; }
.total-pnl { text-align: center; font-size: 28px; font-weight: bold; margin: 8px 0; }
.fund-info { margin: 8px 0; }
.fund-row { display: flex; justify-content: space-between; padding: 4px 0; font-size: 12px; color: var(--text-tertiary); }
.pos-list { margin-top: 12px; padding-top: 8px; border-top: 1px solid var(--border-default); }
.pos-item { display: flex; justify-content: space-between; padding: 4px 0; font-size: 12px; }
.pos-code { color: var(--text-tertiary); }
.pos-pnl { font-weight: bold; }
.pos-more { text-align: center; color: var(--text-muted); font-size: 11px; padding: 4px; }

/* 响应式 */
@media (max-width: 900px) {
  .main-grid { grid-template-columns: 1fr; }
  .cockpit { padding: 8px; }
  .top-bar { flex-wrap: wrap; gap: 8px; }
  .asset-info { font-size: 12px; }
}

@media (max-width: 640px) {
  .main-grid { grid-template-columns: 1fr; gap: 8px; padding: 8px; }
  .panel { padding: 8px; }
  .total-pnl { font-size: 22px; }
  .signal-card { padding: 6px 8px; }
}
.timeline-label { font-weight: bold; font-size: 12px; white-space: nowrap; }
.timeline-scroll { display: flex; gap: 12px; overflow-x: auto; flex: 1; }
.tl-item { white-space: nowrap; font-size: 12px; color: var(--text-tertiary); }

/* 信号详情弹窗 */
.sig-detail { font-size: 13px; }
.sig-detail-row { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid var(--border-default); }
.sig-detail-label { color: var(--text-tertiary); min-width: 60px; }
.sig-detail-pipeline { margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--border-default); }
.sig-detail-pipeline-title { font-weight: bold; margin-bottom: 8px; font-size: 13px; }
</style>
