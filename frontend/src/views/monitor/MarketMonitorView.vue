<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ElCard, ElButton, ElTag, ElEmpty, ElProgress, ElTable, ElTableColumn, ElDescriptions, ElDescriptionsItem } from 'element-plus'

interface ScanStats {
  scans: number; signals_found: number; trades_executed: number
  stop_losses: number; take_profits: number; stocks_scanned: number
}
interface ScannerStatus {
  is_running: boolean; scan_count: number; last_scan_time: string
  active_signals: number; positions: number; stocks_scanned: number
  stats: ScanStats; account_id: string
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
  cost_price: number; current_price: number; profit_pct: number
  stop_loss_pct: number; take_profit_pct: number; should_sell: boolean; sell_reason: string
}
interface TimelineItem {
  time: string; action: string; ts_code: string; stock_name: string
  strategy: string; shares: number; price: number; reason: string; profit_pct?: number
}

const status = ref<ScannerStatus | null>(null)
const signals = ref<ScanSignal[]>([])
const positions = ref<PositionInfo[]>([])
const timeline = ref<TimelineItem[]>([])
const loading = ref(false)
const autoRefresh = ref(true)
let refreshTimer: any = null

const apiBase = '/api/v1/scanner'

async function fetchAll() {
  loading.value = true
  try {
    const [statusRes, sigRes, posRes, tlRes] = await Promise.all([
      fetch(`${apiBase}/status`).then(r => r.json()),
      fetch(`${apiBase}/signals`).then(r => r.json()),
      fetch(`${apiBase}/positions`).then(r => r.json()),
      fetch(`${apiBase}/timeline`).then(r => r.json()),
    ])
    if (statusRes.success) status.value = statusRes.data
    if (sigRes.success) signals.value = sigRes.data
    if (posRes.success) positions.value = posRes.data
    if (tlRes.success) timeline.value = tlRes.data
  } catch (e) { console.error(e) }
  finally { loading.value = false }
}

async function startScanner() {
  await fetch(`${apiBase}/start`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ account_id: 'default' }) })
  await fetchAll()
}

async function stopScanner() {
  await fetch(`${apiBase}/stop`, { method: 'POST' })
  await fetchAll()
}

async function manualScan() {
  await fetch(`${apiBase}/scan-once`, { method: 'POST' })
  await fetchAll()
}

const isRunning = computed(() => status.value?.is_running ?? false)

const totalProfit = computed(() => {
  if (!positions.value.length) return 0
  return positions.value.reduce((sum, p) => sum + p.profit_pct, 0)
})

const strategyColor: Record<string, string> = {
  half_chase: '#409eff', first_limit_up: '#e6a23c',
  leader_buy_dip: '#67c23a', limit_down_qiao: '#f56c6c',
}

onMounted(() => {
  fetchAll()
  refreshTimer = setInterval(() => { if (autoRefresh.value) fetchAll() }, 5000)
})
onUnmounted(() => { if (refreshTimer) clearInterval(refreshTimer) })
</script>

<template>
  <div class="market-monitor">
    <!-- 顶部控制栏 -->
    <div class="monitor-header">
      <div class="status-indicator" :class="{ running: isRunning, stopped: !isRunning }">
        <span class="dot"></span>
        <span class="status-text">{{ isRunning ? '扫描中' : '已停止' }}</span>
      </div>
      <div class="header-stats" v-if="status">
        <div class="hs-item"><span class="hs-label">已扫描</span><span class="hs-val">{{ status.stocks_scanned }}</span></div>
        <div class="hs-item"><span class="hs-label">信号</span><span class="hs-val">{{ status.active_signals }}</span></div>
        <div class="hs-item"><span class="hs-label">持仓</span><span class="hs-val">{{ status.positions }}</span></div>
        <div class="hs-item"><span class="hs-label">扫描次数</span><span class="hs-val">{{ status.scan_count }}</span></div>
      </div>
      <div class="header-actions">
        <ElButton v-if="!isRunning" type="success" @click="startScanner" :loading="loading">▶ 启动</ElButton>
        <ElButton v-else type="danger" @click="stopScanner">■ 停止</ElButton>
        <ElButton @click="manualScan" :loading="loading" :disabled="isRunning">手动扫描</ElButton>
        <ElButton @click="fetchAll" :loading="loading" size="small">🔄</ElButton>
      </div>
    </div>

    <!-- 4列面板 -->
    <div class="monitor-grid">
      <!-- 活跃信号 -->
      <ElCard class="panel">
        <template #header><span>🎯 活跃信号 ({{ signals.length }})</span></template>
        <div v-if="!signals.length" class="empty-hint">暂无信号 — 启动扫描器或手动扫描</div>
        <div v-else class="signal-list">
          <div v-for="sig in signals" :key="sig.ts_code + sig.strategy" class="signal-item">
            <div class="sig-header">
              <span class="sig-code">{{ sig.ts_code }}</span>
              <span class="sig-name">{{ sig.stock_name }}</span>
              <ElTag size="small" :color="strategyColor[sig.strategy] || '#909399'" style="color:#fff;border:none">{{ sig.strategy_name }}</ElTag>
            </div>
            <div class="sig-detail">
              <span :class="sig.pct_chg >= 0 ? 'pct-up' : 'pct-down'">{{ sig.pct_chg >= 0 ? '+' : '' }}{{ sig.pct_chg.toFixed(1) }}%</span>
              <span v-if="sig.volume_ratio" class="sig-factor">量比{{ sig.volume_ratio.toFixed(1) }}</span>
              <span v-if="sig.is_limit_up" class="sig-limit">涨停</span>
            </div>
          </div>
        </div>
      </ElCard>

      <!-- 持仓监控 -->
      <ElCard class="panel">
        <template #header><span>📊 持仓监控 ({{ positions.length }})</span></template>
        <div v-if="!positions.length" class="empty-hint">暂无持仓</div>
        <div v-else class="position-list">
          <div v-for="pos in positions" :key="pos.ts_code" class="pos-item" :class="{ 'pos-danger': pos.profit_pct <= pos.stop_loss_pct + 1 }">
            <div class="pos-header">
              <span class="pos-code">{{ pos.ts_code }}</span>
              <span class="pos-name">{{ pos.stock_name }}</span>
              <span :class="pos.profit_pct >= 0 ? 'pct-up' : 'pct-down'" class="pos-pct">
                {{ pos.profit_pct >= 0 ? '+' : '' }}{{ pos.profit_pct.toFixed(1) }}%
              </span>
            </div>
            <div class="pos-bar-wrap">
              <div class="pos-bar" :style="{
                width: Math.min(Math.abs(pos.profit_pct) / Math.abs(pos.stop_loss_pct) * 100, 100) + '%',
                background: pos.profit_pct >= 0 ? '#67c23a' : '#f56c6c'
              }"></div>
              <div class="pos-bar-stop" :style="{ left: '100%' }"></div>
            </div>
            <div class="pos-detail">
              <span>{{ pos.shares }}股 @{{ pos.cost_price.toFixed(2) }}</span>
              <span>止损{{ pos.stop_loss_pct }}% 止盈+{{ pos.take_profit_pct }}%</span>
            </div>
          </div>
        </div>
      </ElCard>

      <!-- 今日时间线 -->
      <ElCard class="panel">
        <template #header><span>⏱️ 今日时间线 ({{ timeline.length }})</span></template>
        <div v-if="!timeline.length" class="empty-hint">暂无交易</div>
        <div v-else class="timeline-list">
          <div v-for="(item, i) in timeline" :key="i" class="tl-item">
            <span class="tl-time">{{ item.time }}</span>
            <span class="tl-action" :class="item.action === 'buy' ? 'tl-buy' : 'tl-sell'">
              {{ item.action === 'buy' ? '买入' : '卖出' }}
            </span>
            <span class="tl-code">{{ item.ts_code }}</span>
            <span class="tl-name">{{ item.stock_name }}</span>
            <span class="tl-detail">{{ item.shares }}股@{{ item.price.toFixed(2) }}</span>
            <span v-if="item.profit_pct !== undefined" :class="item.profit_pct >= 0 ? 'pct-up' : 'pct-down'">
              {{ item.profit_pct >= 0 ? '+' : '' }}{{ item.profit_pct.toFixed(1) }}%
            </span>
            <span class="tl-reason">{{ item.reason }}</span>
          </div>
        </div>
      </ElCard>

      <!-- 统计 -->
      <ElCard class="panel">
        <template #header><span>📈 今日统计</span></template>
        <div class="stats-grid" v-if="status">
          <div class="stat-item">
            <div class="stat-val">{{ status.stats.signals_found }}</div>
            <div class="stat-label">信号发现</div>
          </div>
          <div class="stat-item">
            <div class="stat-val">{{ status.stats.trades_executed }}</div>
            <div class="stat-label">执行交易</div>
          </div>
          <div class="stat-item">
            <div class="stat-val" style="color: #f56c6c">{{ status.stats.stop_losses }}</div>
            <div class="stat-label">止损</div>
          </div>
          <div class="stat-item">
            <div class="stat-val" style="color: #67c23a">{{ status.stats.take_profits }}</div>
            <div class="stat-label">止盈</div>
          </div>
          <div class="stat-item">
            <div class="stat-val">{{ status.stocks_scanned }}</div>
            <div class="stat-label">扫描股票数</div>
          </div>
          <div class="stat-item">
            <div class="stat-val">{{ status.scan_count }}</div>
            <div class="stat-label">扫描次数</div>
          </div>
        </div>
      </ElCard>
    </div>
  </div>
</template>

<style scoped lang="scss">
.market-monitor { padding: 0; }
.monitor-header {
  display: flex; align-items: center; gap: 16px; padding: 12px 16px;
  background: var(--el-fill-color-lighter); border-radius: 8px; flex-wrap: wrap;
}
.status-indicator { display: flex; align-items: center; gap: 6px; font-weight: 600; font-size: 14px; }
.dot { width: 10px; height: 10px; border-radius: 50%; }
.running .dot { background: #67c23a; animation: pulse 1.5s infinite; }
.stopped .dot { background: #909399; }
.running .status-text { color: #67c23a; }
.stopped .status-text { color: #909399; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
.header-stats { display: flex; gap: 16px; flex: 1; }
.hs-item { display: flex; flex-direction: column; }
.hs-label { font-size: 10px; color: #909399; }
.hs-val { font-size: 16px; font-weight: 700; }
.header-actions { display: flex; gap: 8px; }

.monitor-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 12px; }
.panel { min-height: 200px; }

.empty-hint { color: #909399; text-align: center; padding: 30px 0; font-size: 13px; }

.signal-list, .position-list, .timeline-list { max-height: 360px; overflow-y: auto; }
.signal-item { padding: 8px 0; border-bottom: 1px solid #f0f0f0; }
.sig-header { display: flex; align-items: center; gap: 6px; }
.sig-code { font-weight: 700; font-family: monospace; font-size: 13px; }
.sig-name { font-size: 12px; color: #606266; flex: 1; }
.sig-detail { display: flex; align-items: center; gap: 8px; margin-top: 4px; font-size: 12px; }
.sig-factor { color: #909399; }
.sig-limit { color: #f56c6c; font-weight: 600; }

.pos-item { padding: 8px 0; border-bottom: 1px solid #f0f0f0; }
.pos-header { display: flex; align-items: center; gap: 6px; }
.pos-code { font-weight: 700; font-family: monospace; font-size: 13px; }
.pos-name { font-size: 12px; color: #606266; flex: 1; }
.pos-pct { font-weight: 700; font-size: 14px; }
.pos-bar-wrap { height: 4px; background: #ebeef5; border-radius: 2px; margin: 4px 0; position: relative; overflow: hidden; }
.pos-bar { height: 100%; border-radius: 2px; transition: width 0.3s; }
.pos-detail { display: flex; justify-content: space-between; font-size: 11px; color: #909399; }

.tl-item { display: flex; align-items: center; gap: 6px; padding: 4px 0; font-size: 12px; border-bottom: 1px solid #f5f5f5; }
.tl-time { color: #909399; font-family: monospace; min-width: 55px; }
.tl-buy { color: #f56c6c; font-weight: 600; min-width: 30px; }
.tl-sell { color: #67c23a; font-weight: 600; min-width: 30px; }
.tl-code { font-family: monospace; font-weight: 600; }
.tl-name { color: #606266; flex: 1; }
.tl-detail { color: #909399; }
.tl-reason { color: #909399; font-size: 11px; }

.pct-up { color: #f56c6c; }
.pct-down { color: #67c23a; }

.stats-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; text-align: center; }
.stat-item { padding: 10px; }
.stat-val { font-size: 24px; font-weight: 700; }
.stat-label { font-size: 11px; color: #909399; margin-top: 2px; }

@media (max-width: 900px) {
  .monitor-grid { grid-template-columns: 1fr; }
}
</style>
