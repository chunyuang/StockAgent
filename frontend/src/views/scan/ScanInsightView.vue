<template>
  <div class="scan-page">
    <!-- 顶部状态栏 -->
    <div class="status-bar">
      <div class="status-item">
        <span class="label">状态</span>
        <ElTag :type="archStatus.is_running ? 'success' : 'danger'" effect="dark" size="small">
          {{ archStatus.is_running ? '🟢 运行中' : '🔴 已停止' }}
        </ElTag>
      </div>
      <div class="status-item">
        <span class="label">当前阶段</span>
        <span class="value">{{ currentPhase?.phase || '-' }}</span>
      </div>
      <div class="status-item">
        <span class="label">仓位</span>
        <span class="value">{{ fmtPct(archStatus.position_ratio) }}</span>
      </div>
      <div class="status-item">
        <span class="label">熔断器</span>
        <ElTag :type="cbPaused ? 'danger' : 'success'" size="small">
          {{ cbPaused ? '已暂停' : '正常' }}
        </ElTag>
      </div>
      <div class="status-item">
        <span class="label">情绪</span>
        <ElTag type="warning" size="small">{{ sentimentLabel }}</ElTag>
      </div>
      <div class="status-item" v-if="cbInfo">
        <span class="label">连亏</span>
        <span class="value">{{ cbInfo.consecutive_losses }}/{{ cbInfo.consecutive_loss_limit }}</span>
      </div>
    </div>

    <!-- 核心时间线 -->
    <ElCard shadow="never" class="timeline-card">
      <template #header>
        <div class="card-header">
          <span>📋 扫描时间线</span>
          <span class="header-hint">一天6个阶段 · 点击查看详情</span>
        </div>
      </template>
      <div class="phase-timeline">
        <div
          v-for="(p, i) in timingPhases"
          :key="p.phase"
          class="phase-block"
          :class="{ active: p.phase === currentPhaseName, dim: !p.scan }"
          @click="selectPhase(p)"
        >
          <div class="phase-connector" v-if="i > 0"></div>
          <div class="phase-content">
            <div class="phase-icon">{{ phaseIcon(p.phase) }}</div>
            <div class="phase-name">{{ phaseLabel(p.phase) }}</div>
            <div class="phase-time">{{ p.time }}</div>
            <div class="phase-scan" v-if="p.scan">
              <ElTag size="small" type="success">扫描中</ElTag>
            </div>
            <div class="phase-scan" v-else>
              <span class="dim-text">休止</span>
            </div>
          </div>
        </div>
      </div>
    </ElCard>

    <!-- 选中阶段详情 -->
    <div class="detail-grid">
      <!-- 阶段说明 -->
      <ElCard shadow="never" class="detail-card">
        <template #header><span class="card-title">{{ phaseLabel(selectedPhase?.phase) }} · 做什么</span></template>
        <div class="detail-body" v-if="selectedPhase">
          <p class="purpose">{{ selectedPhase.purpose }}</p>
          <div class="op-list" v-if="selectedPhase.key_operations?.length">
            <div v-for="(op, i) in selectedPhase.key_operations" :key="i" class="op-item">
              <span class="op-dot">•</span> {{ op }}
            </div>
          </div>
        </div>
        <ElEmpty v-else description="选择一个阶段" :image-size="60" />
      </ElCard>

      <!-- 扫描间隔 -->
      <ElCard shadow="never" class="detail-card">
        <template #header><span class="card-title">⏱️ 扫描间隔</span></template>
        <div class="detail-body" v-if="selectedPhase?.scan">
          <div class="interval-list">
            <div v-for="iv in phaseIntervals" :key="iv.time_range" class="interval-row">
              <span class="iv-time">{{ iv.time_range }}</span>
              <span class="iv-secs">{{ iv.seconds }}秒</span>
              <span class="iv-reason">{{ iv.reason }}</span>
            </div>
          </div>
          <div class="interval-extra">
            <div class="extra-row"><span>🌬️ 行情预取</span><span>30秒/轮</span></div>
            <div class="extra-row"><span>🛡️ 风控循环</span><span>1秒/次</span></div>
            <div class="extra-row"><span>🔧 错误恢复</span><span>{{ timingRecovery || '5秒/30秒' }}</span></div>
          </div>
        </div>
        <ElEmpty v-else description="该阶段不扫描" :image-size="60" />
      </ElCard>

      <!-- 策略概览 -->
      <ElCard shadow="never" class="detail-card">
        <template #header><span class="card-title">🎯 策略概览</span></template>
        <div class="detail-body">
          <div v-for="s in strategyList" :key="s.id" class="strategy-row">
            <div class="strat-header">
              <span class="strat-name">{{ s.name || s.id }}</span>
              <ElTag size="small" :type="s.enabled ? 'success' : 'info'">{{ s.enabled ? '启用' : '停用' }}</ElTag>
            </div>
            <div class="strat-params">
              <span v-for="rp in (s.risk_params || [])" :key="rp.name" v-show="isCoreRisk(rp.name)">
                {{ riskLabel(rp.name) }} {{ fmtRiskVal(rp.name, rp.value) }}
              </span>
            </div>
          </div>
        </div>
      </ElCard>

      <!-- 9层管道 -->
      <ElCard shadow="never" class="detail-card">
        <template #header><span class="card-title">🔧 9层管道</span></template>
        <div class="detail-body">
          <div class="pipeline-flow">
            <div v-for="(layer, i) in pipelineLayers" :key="i" class="pipe-step">
              <span class="pipe-num">L{{ i + 1 }}</span>
              <span class="pipe-name">{{ layer.name }}</span>
              <span class="pipe-desc" v-if="layer.description">{{ layer.description }}</span>
            </div>
          </div>
        </div>
      </ElCard>
    </div>

    <!-- 盘前流程 -->
    <ElCard shadow="never" class="premarket-card" v-if="timingPremarket.length">
      <template #header><span class="card-title">🌅 盘前流程</span></template>
      <div class="premarket-flow">
        <div v-for="step in timingPremarket" :key="step.step" class="pm-step">
          <div class="pm-time">{{ step.time }}</div>
          <div class="pm-action">{{ step.action }}</div>
          <div class="pm-detail" v-if="step.detail">{{ step.detail }}</div>
        </div>
      </div>
    </ElCard>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElCard, ElTag, ElEmpty } from 'element-plus'
import { api } from '@/api'

const loading = ref(true)
const architecture = ref<any>(null)
const timing = ref<any>(null)
const strategies = ref<any>(null)
const pipeline = ref<any>(null)
const selectedPhase = ref<any>(null)

const archStatus = computed(() => architecture.value?.runtime || {})
const cbInfo = computed(() => archStatus.value?.circuit_breaker && typeof archStatus.value.circuit_breaker === 'object' ? archStatus.value.circuit_breaker : null)
const cbPaused = computed(() => cbInfo.value?.trading_paused || false)
const sentimentLabel = computed(() => {
  const s = archStatus.value?.sentiment
  if (!s || typeof s !== 'object') return '-'
  return `${s.period || '-'} ${s.score?.toFixed(0) || ''}`
})
const timingPhases = computed(() => timing.value?.phases || [])
const timingIntervals = computed(() => timing.value?.intervals || [])
const timingPremarket = computed(() => timing.value?.premarket || [])
const timingRecovery = computed(() => timing.value?.error_recovery || '')
const strategyList = computed(() => strategies.value?.strategies || [])
const pipelineLayers = computed(() => pipeline.value?.layers || [])

const currentPhaseName = computed(() => {
  const now = new Date()
  const h = now.getHours()
  const m = now.getMinutes()
  const hm = h * 100 + m
  if (hm < 900) return 'PREMARKET'
  if (hm < 925) return 'AUCTION'
  if (hm < 1130) return 'MORNING'
  if (hm < 1300) return 'LUNCH'
  if (hm < 1500) return 'AFTERNOON'
  return 'AFTER_CLOSE'
})

const currentPhase = computed(() => timingPhases.value.find(p => p.phase === currentPhaseName.value))

const phaseIntervals = computed(() => {
  if (!selectedPhase.value) return []
  const phase = selectedPhase.value.phase
  if (phase === 'MORNING') return timingIntervals.value.filter(iv => iv.time_range.startsWith('09:') || iv.time_range.startsWith('10:') || iv.time_range.startsWith('11:'))
  if (phase === 'AFTERNOON') return timingIntervals.value.filter(iv => iv.time_range.startsWith('13:') || iv.time_range.startsWith('14:'))
  return timingIntervals.value
})

function selectPhase(p: any) { selectedPhase.value = p }

function fmtPct(v: any) {
  if (v == null) return '-'
  return (v * 100).toFixed(0) + '%'
}

const CORE_RISK = ['stop_loss_pct', 'take_profit_pct', 'trailing_stop_pct', 'max_hold_days']
function isCoreRisk(name: string) { return CORE_RISK.includes(name) }
function riskLabel(name: string) {
  const map: Record<string, string> = { stop_loss_pct: '止损', take_profit_pct: '止盈', trailing_stop_pct: '追踪', max_hold_days: '持仓' }
  return map[name] || name
}
function fmtRiskVal(name: string, val: string) {
  if (name === 'max_hold_days') return val + '天'
  return (parseFloat(val) * 100).toFixed(1) + '%'
}

function phaseLabel(phase?: string) {
  const map: Record<string, string> = {
    PREMARKET: '盘前准备', AUCTION: '集合竞价', MORNING: '早盘',
    LUNCH: '午休', AFTERNOON: '下午盘', AFTER_CLOSE: '盘后'
  }
  return map[phase || ''] || phase || ''
}

function phaseIcon(phase: string) {
  const map: Record<string, string> = {
    PREMARKET: '🌅', AUCTION: '📢', MORNING: '📈',
    LUNCH: '🍽️', AFTERNOON: '📉', AFTER_CLOSE: '📦'
  }
  return map[phase] || '⚪'
}

async function loadAll() {
  const endpoints = [
    { ref: architecture, path: '/scan-insight/architecture' },
    { ref: timing, path: '/scan-insight/timing' },
    { ref: strategies, path: '/scan-insight/strategies' },
    { ref: pipeline, path: '/scan-insight/pipeline' },
  ]
  await Promise.all(
    endpoints.map(e =>
      api.get(e.path)
        .then((res: any) => { e.ref.value = res?.data || res })
        .catch((err) => { if (__DEV__) console.warn('[ScanInsight] Failed to load', e.path, err?.message) })
    )
  )
  loading.value = false
  selectedPhase.value = currentPhase.value || timingPhases.value[0]
}

onMounted(loadAll)
</script>

<style lang="scss" scoped>
.scan-page {
  padding: 16px 20px;
  min-height: 100vh;
  background: var(--el-bg-color-page);
}

/* 状态栏 */
.status-bar {
  display: flex;
  gap: 24px;
  align-items: center;
  padding: 12px 20px;
  background: var(--el-bg-color-overlay);
  border-radius: 10px;
  margin-bottom: 16px;
  border: 1px solid var(--el-border-color-lighter);
  flex-wrap: wrap;
  .status-item {
    display: flex;
    align-items: center;
    gap: 6px;
    .label { font-size: 12px; color: var(--el-text-color-secondary); }
    .value { font-size: 15px; font-weight: 600; }
  }
}

/* 时间线 */
.timeline-card {
  margin-bottom: 16px;
  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    .header-hint { font-size: 12px; color: var(--el-text-color-secondary); font-weight: normal; }
  }
}

.phase-timeline {
  display: flex;
  align-items: stretch;
  gap: 0;
  overflow-x: auto;
  padding-bottom: 4px;
}

.phase-block {
  display: flex;
  align-items: center;
  cursor: pointer;
  flex-shrink: 0;
  &.dim { opacity: 0.5; }
  &.active {
    .phase-content {
      background: var(--el-color-primary-light-9);
      border-color: var(--el-color-primary);
      transform: translateY(-2px);
    }
  }
}

.phase-connector {
  width: 24px;
  height: 2px;
  background: var(--el-border-color);
  flex-shrink: 0;
}

.phase-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 12px 16px;
  border: 2px solid var(--el-border-color-lighter);
  border-radius: 10px;
  min-width: 100px;
  transition: all 0.2s;
  &:hover { border-color: var(--el-color-primary-light-5); }
  .phase-icon { font-size: 24px; margin-bottom: 4px; }
  .phase-name { font-size: 14px; font-weight: 600; margin-bottom: 2px; }
  .phase-time { font-size: 12px; color: var(--el-text-color-secondary); margin-bottom: 4px; }
  .phase-scan .dim-text { font-size: 12px; color: var(--el-text-color-placeholder); }
}

/* 详情网格 */
.detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 16px;
}

.detail-card {
  .card-title { font-size: 15px; font-weight: 600; }
}

.detail-body {
  font-size: 13px;
  line-height: 1.7;
  .purpose { margin: 0 0 10px; color: var(--el-text-color-primary); }
}

.op-list {
  .op-item {
    padding: 3px 0;
    .op-dot { color: var(--el-color-primary); margin-right: 4px; }
  }
}

/* 间隔列表 */
.interval-list {
  margin-bottom: 12px;
  .interval-row {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 6px 0;
    border-bottom: 1px solid var(--el-border-color-extra-light);
    &:last-child { border: none; }
    .iv-time { width: 100px; font-weight: 600; }
    .iv-secs {
      width: 60px;
      text-align: center;
      background: var(--el-color-primary-light-9);
      color: var(--el-color-primary);
      border-radius: 4px;
      padding: 2px 6px;
      font-size: 12px;
      font-weight: 600;
    }
    .iv-reason { color: var(--el-text-color-secondary); font-size: 12px; }
  }
}

.interval-extra {
  padding-top: 8px;
  border-top: 1px dashed var(--el-border-color);
  .extra-row {
    display: flex;
    justify-content: space-between;
    padding: 4px 0;
    font-size: 12px;
    color: var(--el-text-color-secondary);
  }
}

/* 策略 */
.strategy-row {
  padding: 8px 0;
  border-bottom: 1px solid var(--el-border-color-extra-light);
  &:last-child { border: none; }
  .strat-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 4px;
    .strat-name { font-weight: 600; font-size: 13px; }
  }
  .strat-params {
    display: flex;
    gap: 12px;
    font-size: 12px;
    color: var(--el-text-color-secondary);
  }
}

/* 管道 */
.pipeline-flow {
  display: flex;
  flex-direction: column;
  gap: 6px;
  .pipe-step {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 0;
    .pipe-num {
      width: 32px;
      height: 24px;
      line-height: 24px;
      text-align: center;
      background: var(--el-color-primary-light-9);
      color: var(--el-color-primary);
      border-radius: 4px;
      font-size: 12px;
      font-weight: 700;
      flex-shrink: 0;
    }
    .pipe-name { font-weight: 600; font-size: 13px; white-space: nowrap; }
    .pipe-desc { color: var(--el-text-color-secondary); font-size: 12px; }
  }
}

/* 盘前流程 */
.premarket-card {
  .card-title { font-size: 15px; font-weight: 600; }
}

.premarket-flow {
  display: flex;
  gap: 16px;
  overflow-x: auto;
  padding-bottom: 4px;
  .pm-step {
    flex-shrink: 0;
    min-width: 160px;
    padding: 10px 14px;
    background: var(--el-fill-color-light);
    border-radius: 8px;
    border-left: 3px solid var(--el-color-primary);
    .pm-time { font-size: 12px; color: var(--el-color-primary); font-weight: 600; margin-bottom: 4px; }
    .pm-action { font-size: 13px; font-weight: 600; margin-bottom: 2px; }
    .pm-detail { font-size: 12px; color: var(--el-text-color-secondary); }
  }
}

@media (max-width: 768px) {
  .detail-grid { grid-template-columns: 1fr; }
}
</style>
