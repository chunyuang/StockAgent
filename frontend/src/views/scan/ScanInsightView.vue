<script setup lang="ts">
/**
 * 数据扫描洞察页面 — Scanner 架构 / 管道 / 策略 / 情绪 / 信号 / 行情 / 风控 / 时序
 * 纯展示页面，不修改任何运行时逻辑
 */
import { ref, computed, onMounted } from 'vue'
import {
  ElCard,
  ElTabs,
  ElTabPane,
  ElTable,
  ElTableColumn,
  ElTag,
  ElDescriptions,
  ElDescriptionsItem,
  ElProgress,
  ElCollapse,
  ElCollapseItem,
  ElBadge,
  ElTooltip,
  ElDivider,
  ElEmpty,
  ElAlert,
  ElIcon,
} from 'element-plus'
import { api } from '@/api'

// ==================== 状态 ====================

const loading = ref(false)
const activeTab = ref('architecture')

const architecture = ref<any>(null)
const pipeline = ref<any>(null)
const strategies = ref<any>(null)
const emotionCycle = ref<any>(null)
const signalLifecycle = ref<any>(null)
const quoteManager = ref<any>(null)
const riskSystem = ref<any>(null)
const timing = ref<any>(null)

// ==================== 工具函数 ====================

function fmtPct(val: number | undefined | null): string {
  if (val == null) return '-'
  return val.toFixed(2) + '%'
}

function fmtMoney(val: number | undefined | null, unit: '万' | '亿' = '万', digits = 1): string {
  if (val == null) return '-'
  const v = unit === '亿' ? val / 100000000 : val / 10000
  return v.toFixed(digits) + unit
}

function fmtBool(val: boolean | undefined | null): string {
  if (val == null) return '-'
  return val ? '✅ 是' : '❌ 否'
}

function fmtNum(val: number | undefined | null, digits = 0): string {
  if (val == null) return '-'
  return digits > 0 ? val.toFixed(digits) : String(val)
}

// ==================== 数据加载 ====================

async function loadAll() {
  loading.value = true
  const endpoints = [
    { key: 'architecture', ref: architecture, path: '/scan-insight/architecture' },
    { key: 'pipeline', ref: pipeline, path: '/scan-insight/pipeline' },
    { key: 'strategies', ref: strategies, path: '/scan-insight/strategies' },
    { key: 'emotionCycle', ref: emotionCycle, path: '/scan-insight/emotion-cycle' },
    { key: 'signalLifecycle', ref: signalLifecycle, path: '/scan-insight/signal-lifecycle' },
    { key: 'quoteManager', ref: quoteManager, path: '/scan-insight/quote-manager' },
    { key: 'riskSystem', ref: riskSystem, path: '/scan-insight/risk-system' },
    { key: 'timing', ref: timing, path: '/scan-insight/timing' },
  ]
  await Promise.all(
    endpoints.map(e =>
      api.get(e.path)
        .then((res: any) => { e.ref.value = res })
        .catch((err: any) => { console.warn(`[${e.key}] 加载失败`, err) })
    )
  )
  loading.value = false
}

onMounted(loadAll)

// ==================== 计算属性 ====================

const archStatus = computed(() => architecture.value?.status || {})
const archModules = computed(() => architecture.value?.modules || [])
const archDataFlow = computed(() => architecture.value?.data_flow || [])
const archCollections = computed(() => architecture.value?.collections || [])

const pipelineLayers = computed(() => pipeline.value?.layers || [])
const pipelineSummary = computed(() => pipeline.value?.summary || null)

const strategyList = computed(() => strategies.value?.strategies || [])
const globalRisk = computed(() => strategies.value?.global_risk || {})

const emotionDimensions = computed(() => emotionCycle.value?.dimensions || [])
const emotionPhases = computed(() => emotionCycle.value?.phases || [])
const emotionLatest = computed(() => emotionCycle.value?.latest || null)

const signalStates = computed(() => signalLifecycle.value?.states || [])
const signalTransitions = computed(() => signalLifecycle.value?.transitions || [])
const signalExpiry = computed(() => signalLifecycle.value?.expiry_policies || [])
const signalStats = computed(() => signalLifecycle.value?.status_stats || [])
const signalDelay = computed(() => signalLifecycle.value?.delay_mechanism || null)

const quoteSources = computed(() => quoteManager.value?.sources || [])
const quoteCache = computed(() => quoteManager.value?.cache || {})
const quotePrefetch = computed(() => quoteManager.value?.prefetch || {})
const quoteDegradation = computed(() => quoteManager.value?.degradation || [])
const quoteRuntime = computed(() => quoteManager.value?.runtime || {})

const riskCategories = computed(() => riskSystem.value?.categories || [])
const riskRuntime = computed(() => riskSystem.value?.runtime || {})

const timingSessions = computed(() => timing.value?.sessions || [])
const timingIntervals = computed(() => timing.value?.intervals || [])
const timingPremarket = computed(() => timing.value?.premarket_flow || [])
const timingRecovery = computed(() => timing.value?.error_recovery || null)
</script>

<template>
  <div class="scan-insight-page">
    <div class="page-header">
      <div class="header-left">
        <h2>🔍 数据扫描洞察</h2>
        <span class="header-sub">Scanner 架构全景 / 管道 / 策略 / 情绪 / 信号 / 行情 / 风控 / 时序</span>
      </div>
      <div class="header-right">
        <ElTag :type="loading ? 'warning' : 'success'" size="large" effect="dark">
          {{ loading ? '⏳ 加载中...' : '✅ 已加载' }}
        </ElTag>
      </div>
    </div>

    <div class="overview-bar" v-if="architecture">
      <div class="summary-card"><div class="sc-label">运行状态</div><div class="sc-value"><ElTag :type="archStatus.is_running ? 'success' : 'danger'" effect="dark">{{ archStatus.is_running ? '🟢 运行中' : '🔴 已停止' }}</ElTag></div></div>
      <div class="summary-card"><div class="sc-label">交易日</div><div class="sc-value">{{ archStatus.trade_date || '-' }}</div></div>
      <div class="summary-card"><div class="sc-label">熔断器</div><div class="sc-value"><ElTag :type="archStatus.circuit_breaker ? 'danger' : 'success'" size="small">{{ archStatus.circuit_breaker ? '已熔断' : '正常' }}</ElTag></div></div>
      <div class="summary-card"><div class="sc-label">情绪周期</div><div class="sc-value"><ElTag type="warning" size="small">{{ archStatus.sentiment || '-' }}</ElTag></div></div>
      <div class="summary-card"><div class="sc-label">仓位比例</div><div class="sc-value">{{ fmtPct(archStatus.position_ratio) }}</div></div>
      <div class="summary-card"><div class="sc-label">扫描错误</div><div class="sc-value"><ElBadge :value="archStatus.scan_errors || 0" :type="(archStatus.scan_errors || 0) > 0 ? 'danger' : 'info'"><span style="font-size:14px">{{ archStatus.scan_errors || 0 }}</span></ElBadge></div></div>
    </div>

    <ElTabs v-model="activeTab" type="border-card" class="main-tabs">

      <!-- Tab1: 架构总览 -->
      <ElTabPane label="🏗️ 架构总览" name="architecture">
        <ElEmpty v-if="!architecture" description="暂无架构数据" />
        <template v-else>
          <ElCard shadow="hover" class="section-card">
            <template #header><span class="card-title">📡 运行状态</span></template>
            <ElDescriptions :column="3" border size="small">
              <ElDescriptionsItem label="是否运行">{{ fmtBool(archStatus.is_running) }}</ElDescriptionsItem>
              <ElDescriptionsItem label="交易日">{{ archStatus.trade_date || '-' }}</ElDescriptionsItem>
              <ElDescriptionsItem label="扫描线程">{{ fmtBool(archStatus.scan_thread) }}</ElDescriptionsItem>
              <ElDescriptionsItem label="风控线程">{{ fmtBool(archStatus.risk_thread) }}</ElDescriptionsItem>
              <ElDescriptionsItem label="预取线程">{{ fmtBool(archStatus.prefetch) }}</ElDescriptionsItem>
              <ElDescriptionsItem label="熔断器"><ElTag :type="archStatus.circuit_breaker ? 'danger' : 'success'" size="small">{{ archStatus.circuit_breaker ? '已熔断' : '正常' }}</ElTag></ElDescriptionsItem>
              <ElDescriptionsItem label="情绪周期">{{ archStatus.sentiment || '-' }}</ElDescriptionsItem>
              <ElDescriptionsItem label="仓位比例">{{ fmtPct(archStatus.position_ratio) }}</ElDescriptionsItem>
              <ElDescriptionsItem label="扫描错误">{{ archStatus.scan_errors || 0 }}</ElDescriptionsItem>
            </ElDescriptions>
          </ElCard>

          <ElCard shadow="hover" class="section-card">
            <template #header><span class="card-title">🧩 子模块</span></template>
            <div class="module-grid">
              <div v-for="mod in archModules" :key="mod.name" class="module-card">
                <div class="mod-name">{{ mod.name }}</div>
                <div class="mod-file" v-if="mod.file">📄 {{ mod.file }}</div>
                <div class="mod-purpose" v-if="mod.purpose">{{ mod.purpose }}</div>
                <div class="mod-methods" v-if="mod.key_methods?.length">
                  <ElTag v-for="m in mod.key_methods" :key="m" size="small" type="info" class="method-tag">{{ m }}</ElTag>
                </div>
              </div>
            </div>
          </ElCard>

          <ElCard shadow="hover" class="section-card">
            <template #header><span class="card-title">🔄 数据流 (7步)</span></template>
            <div class="data-flow">
              <template v-for="(step, idx) in archDataFlow" :key="idx">
                <div class="flow-step"><div class="flow-num">{{ idx + 1 }}</div><div class="flow-label">{{ step }}</div></div>
                <div v-if="idx < archDataFlow.length - 1" class="flow-arrow">→</div>
              </template>
            </div>
          </ElCard>

          <ElCard shadow="hover" class="section-card">
            <template #header><span class="card-title">🗄️ MongoDB 集合</span></template>
            <ElTable :data="archCollections" size="small" stripe border max-height="400">
              <ElTableColumn prop="name" label="集合名" min-width="200" />
              <ElTableColumn prop="purpose" label="用途" min-width="240" />
              <ElTableColumn prop="count" label="记录数" width="100" align="right"><template #default="{ row }">{{ fmtNum(row.count) }}</template></ElTableColumn>
            </ElTable>
          </ElCard>
        </template>
      </ElTabPane>

      <!-- Tab2: 9层管道 -->
      <ElTabPane label="🔧 9层管道" name="pipeline">
        <ElEmpty v-if="!pipeline" description="暂无管道数据" />
        <template v-else>
          <ElCard shadow="hover" class="section-card" v-if="pipelineSummary">
            <template #header><span class="card-title">📊 最新漏斗总览</span></template>
            <div class="funnel-bar">
              <div class="funnel-step" v-for="(s, i) in pipelineSummary.steps || []" :key="i">
                <div class="funnel-label">{{ s.name }}</div>
                <ElProgress :percentage="s.pct || 0" :stroke-width="18" :color="s.color || '#409eff'" :text-inside="true" :format="() => String(s.output ?? '-')" />
              </div>
            </div>
          </ElCard>
          <div class="pipeline-layers">
            <ElCard v-for="(layer, idx) in pipelineLayers" :key="idx" shadow="hover" class="section-card layer-card">
              <template #header>
                <div class="layer-header">
                  <span class="layer-icon">{{ layer.icon || '⚙️' }}</span>
                  <span class="layer-name">L{{ idx + 1 }}: {{ layer.name }}</span>
                  <ElTag size="small" :type="layer.enabled !== false ? 'success' : 'info'">{{ layer.enabled !== false ? '启用' : '禁用' }}</ElTag>
                </div>
              </template>
              <div class="layer-body">
                <p class="layer-desc">{{ layer.description }}</p>
                <div class="layer-stats" v-if="layer.input != null || layer.output != null">
                  <span class="stat-item">📥 输入: <b>{{ fmtNum(layer.input) }}</b></span>
                  <span class="stat-item">📤 输出: <b>{{ fmtNum(layer.output) }}</b></span>
                  <span class="stat-item" v-if="layer.rejected != null">🚫 拒绝: <b>{{ fmtNum(layer.rejected) }}</b></span>
                </div>
                <ElCollapse v-if="layer.details">
                  <ElCollapseItem title="展开条件 & 效果">
                    <div v-if="layer.condition" class="layer-detail"><b>条件:</b> {{ layer.condition }}</div>
                    <div v-if="layer.effect" class="layer-detail"><b>效果:</b> {{ layer.effect }}</div>
                    <pre v-if="layer.raw" class="layer-raw">{{ layer.raw }}</pre>
                  </ElCollapseItem>
                </ElCollapse>
              </div>
            </ElCard>
          </div>
        </template>
      </ElTabPane>

      <!-- Tab3: 策略配置 -->
      <ElTabPane label="🎯 策略配置" name="strategies">
        <ElEmpty v-if="!strategies" description="暂无策略数据" />
        <template v-else>
          <div class="strategy-cards">
            <ElCard v-for="s in strategyList" :key="s.name" shadow="hover" class="section-card strategy-card">
              <template #header>
                <div class="strat-header">
                  <span class="strat-name">{{ s.name }}</span>
                  <ElTag :type="s.enabled ? 'success' : 'info'" effect="dark">{{ s.enabled ? '启用' : '禁用' }}</ElTag>
                </div>
              </template>
              <div v-if="s.params?.length">
                <div class="sub-title">筛选参数</div>
                <ElTable :data="s.params" size="small" stripe border>
                  <ElTableColumn prop="name" label="参数名" min-width="160" />
                  <ElTableColumn prop="value" label="值" min-width="120"><template #default="{ row }"><code>{{ row.value }}</code></template></ElTableColumn>
                  <ElTableColumn prop="desc" label="说明" min-width="200" />
                </ElTable>
              </div>
              <div v-if="s.risk_params?.length" style="margin-top:12px">
                <div class="sub-title">风控参数</div>
                <ElTable :data="s.risk_params" size="small" stripe border>
                  <ElTableColumn prop="name" label="参数名" min-width="160" />
                  <ElTableColumn prop="value" label="值" min-width="120"><template #default="{ row }"><code>{{ row.value }}</code></template></ElTableColumn>
                </ElTable>
              </div>
            </ElCard>
          </div>
          <ElCard shadow="hover" class="section-card" v-if="Object.keys(globalRisk).length">
            <template #header><span class="card-title">🛡️ 全局风控参数</span></template>
            <ElCollapse>
              <ElCollapseItem title="展开查看全局风控参数">
                <ElTable :data="globalRisk.params || []" size="small" stripe border>
                  <ElTableColumn prop="name" label="参数名" min-width="180" />
                  <ElTableColumn prop="value" label="值" min-width="140"><template #default="{ row }"><code>{{ row.value }}</code></template></ElTableColumn>
                  <ElTableColumn prop="desc" label="说明" min-width="200" />
                </ElTable>
              </ElCollapseItem>
            </ElCollapse>
          </ElCard>
        </template>
      </ElTabPane>

      <!-- Tab4: 情绪周期 -->
      <ElTabPane label="🌡️ 情绪周期" name="emotion-cycle">
        <ElEmpty v-if="!emotionCycle" description="暂无情绪数据" />
        <template v-else>
          <ElCard shadow="hover" class="section-card">
            <template #header><span class="card-title">📊 7维评分体系</span></template>
            <ElTable :data="emotionDimensions" size="small" stripe border>
              <ElTableColumn prop="name" label="维度" min-width="140" />
              <ElTableColumn prop="weight" label="权重" width="100" align="center"><template #default="{ row }">{{ fmtPct(row.weight) }}</template></ElTableColumn>
              <ElTableColumn prop="desc" label="说明" min-width="280" />
            </ElTable>
          </ElCard>
          <ElCard shadow="hover" class="section-card">
            <template #header><span class="card-title">🎨 4阶段映射</span></template>
            <div class="phase-bar">
              <div v-for="p in emotionPhases" :key="p.name" class="phase-segment" :style="{ flex: p.span || 1, background: p.color || '#ccc' }">
                <div class="phase-label">{{ p.name }}</div>
                <div class="phase-range">[{{ p.score_min }}, {{ p.score_max }}]</div>
                <div class="phase-position">仓位: {{ fmtPct(p.position_ratio) }}</div>
              </div>
            </div>
          </ElCard>
          <ElCard shadow="hover" class="section-card" v-if="emotionLatest">
            <template #header><span class="card-title">🕐 最新评分</span></template>
            <ElDescriptions :column="3" border size="small">
              <ElDescriptionsItem label="综合评分"><span class="emotion-score">{{ fmtNum(emotionLatest.score, 1) }}</span></ElDescriptionsItem>
              <ElDescriptionsItem label="所处阶段"><ElTag type="warning">{{ emotionLatest.period || '-' }}</ElTag></ElDescriptionsItem>
              <ElDescriptionsItem label="涨停数">{{ emotionLatest.limit_up_count ?? '-' }}</ElDescriptionsItem>
              <ElDescriptionsItem label="跌停数">{{ emotionLatest.limit_down_count ?? '-' }}</ElDescriptionsItem>
              <ElDescriptionsItem label="炸板数">{{ emotionLatest.broken_count ?? '-' }}</ElDescriptionsItem>
              <ElDescriptionsItem label="炸板率">{{ fmtPct(emotionLatest.broken_rate) }}</ElDescriptionsItem>
            </ElDescriptions>
          </ElCard>
        </template>
      </ElTabPane>

      <!-- Tab5: 信号生命周期 -->
      <ElTabPane label="🔔 信号生命周期" name="signal-lifecycle">
        <ElEmpty v-if="!signalLifecycle" description="暂无信号数据" />
        <template v-else>
          <ElCard shadow="hover" class="section-card">
            <template #header><span class="card-title">🔄 状态机</span></template>
            <div class="state-machine">
              <div v-for="st in signalStates" :key="st.name" class="state-node" :style="{ borderColor: st.color || '#409eff' }">
                <div class="state-dot" :style="{ background: st.color || '#409eff' }"></div>
                <div class="state-name">{{ st.name }}</div>
                <div class="state-desc" v-if="st.desc">{{ st.desc }}</div>
              </div>
            </div>
            <ElDivider>状态转换</ElDivider>
            <ElTable :data="signalTransitions" size="small" stripe border>
              <ElTableColumn prop="from" label="起始状态" min-width="120" />
              <ElTableColumn prop="to" label="目标状态" min-width="120" />
              <ElTableColumn prop="trigger" label="触发条件" min-width="200" />
            </ElTable>
          </ElCard>
          <ElCard shadow="hover" class="section-card">
            <template #header><span class="card-title">⏱️ 过期策略</span></template>
            <ElTable :data="signalExpiry" size="small" stripe border>
              <ElTableColumn prop="strategy" label="策略" min-width="140" />
              <ElTableColumn prop="ttl_seconds" label="过期秒数" width="120" align="right"><template #default="{ row }">{{ fmtNum(row.ttl_seconds) }}s</template></ElTableColumn>
              <ElTableColumn prop="desc" label="说明" min-width="280" />
            </ElTable>
          </ElCard>
          <ElCard shadow="hover" class="section-card" v-if="signalDelay">
            <template #header><span class="card-title">🐢 延退机制</span></template>
            <ElAlert :title="signalDelay.title || '信号延退说明'" :description="signalDelay.desc || ''" type="info" show-icon :closable="false" />
          </ElCard>
          <ElCard shadow="hover" class="section-card" v-if="signalStats.length">
            <template #header><span class="card-title">📊 信号状态分布</span></template>
            <div class="signal-stats-grid">
              <div v-for="s in signalStats" :key="s.status" class="stat-box">
                <ElProgress type="circle" :percentage="s.pct || 0" :width="80" :color="s.color || '#409eff'" />
                <div class="stat-label">{{ s.status }}</div>
                <div class="stat-count">{{ fmtNum(s.count) }} 条</div>
              </div>
            </div>
          </ElCard>
        </template>
      </ElTabPane>

      <!-- Tab6: 行情管理 -->
      <ElTabPane label="📈 行情管理" name="quote-manager">
        <ElEmpty v-if="!quoteManager" description="暂无行情数据" />
        <template v-else>
          <ElCard shadow="hover" class="section-card">
            <template #header><span class="card-title">📡 数据源</span></template>
            <ElTable :data="quoteSources" size="small" stripe border>
              <ElTableColumn prop="name" label="名称" min-width="140" />
              <ElTableColumn prop="priority" label="优先级" width="90" align="center" />
              <ElTableColumn prop="purpose" label="用途" min-width="160" />
              <ElTableColumn prop="fields" label="字段" min-width="200" />
              <ElTableColumn prop="available" label="可用时间" min-width="160" />
            </ElTable>
          </ElCard>
          <ElCard shadow="hover" class="section-card">
            <template #header><span class="card-title">💾 缓存机制</span></template>
            <ElDescriptions :column="2" border size="small">
              <ElDescriptionsItem label="最大缓存时间">{{ quoteCache.max_age ?? '-' }}</ElDescriptionsItem>
              <ElDescriptionsItem label="时间源">{{ quoteCache.time_source ?? '-' }}</ElDescriptionsItem>
            </ElDescriptions>
          </ElCard>
          <ElCard shadow="hover" class="section-card">
            <template #header><span class="card-title">⚡ 预取线程</span></template>
            <ElDescriptions :column="3" border size="small">
              <ElDescriptionsItem label="间隔">{{ quotePrefetch.interval ?? '-' }}</ElDescriptionsItem>
              <ElDescriptionsItem label="强制刷新">{{ fmtBool(quotePrefetch.force) }}</ElDescriptionsItem>
              <ElDescriptionsItem label="防重入">{{ fmtBool(quotePrefetch.anti_reentry) }}</ElDescriptionsItem>
            </ElDescriptions>
          </ElCard>
          <ElCard shadow="hover" class="section-card" v-if="quoteDegradation.length">
            <template #header><span class="card-title">🔄 降级策略</span></template>
            <div class="degradation-steps">
              <div v-for="(step, i) in quoteDegradation" :key="i" class="degrade-step">
                <div class="degrade-num">{{ i + 1 }}</div>
                <div class="degrade-text">{{ step }}</div>
              </div>
            </div>
          </ElCard>
          <ElCard shadow="hover" class="section-card">
            <template #header><span class="card-title">🖥️ 运行时状态</span></template>
            <ElDescriptions :column="2" border size="small">
              <ElDescriptionsItem label="缓存大小">{{ fmtNum(quoteRuntime.cache_size) }}</ElDescriptionsItem>
              <ElDescriptionsItem label="当前数据源">{{ quoteRuntime.source ?? '-' }}</ElDescriptionsItem>
            </ElDescriptions>
          </ElCard>
        </template>
      </ElTabPane>

      <!-- Tab7: 风控体系 -->
      <ElTabPane label="🛡️ 风控体系" name="risk-system">
        <ElEmpty v-if="!riskSystem" description="暂无风控数据" />
        <template v-else>
          <div class="risk-grid">
            <ElCard v-for="cat in riskCategories" :key="cat.name" shadow="hover" class="section-card risk-card">
              <template #header>
                <div class="risk-header"><span>{{ cat.icon || '🛡️' }} {{ cat.name }}</span></div>
              </template>
              <p class="risk-desc" v-if="cat.desc">{{ cat.desc }}</p>
              <ElTable v-if="cat.strategies?.length" :data="cat.strategies" size="small" stripe border>
                <ElTableColumn prop="strategy" label="策略" min-width="120" />
                <ElTableColumn v-for="col in cat.columns" :key="col.key" :prop="col.key" :label="col.label" min-width="100">
                  <template #default="{ row }"><code>{{ row[col.key] ?? '-' }}</code></template>
                </ElTableColumn>
              </ElTable>
            </ElCard>
          </div>
          <ElCard shadow="hover" class="section-card">
            <template #header><span class="card-title">🖥️ 风控运行时</span></template>
            <ElDescriptions :column="2" border size="small">
              <ElDescriptionsItem label="熔断器"><ElTag :type="riskRuntime.circuit_breaker ? 'danger' : 'success'" size="small">{{ riskRuntime.circuit_breaker ? '已熔断' : '正常' }}</ElTag></ElDescriptionsItem>
              <ElDescriptionsItem label="仓位比例">{{ fmtPct(riskRuntime.position_ratio) }}</ElDescriptionsItem>
              <ElDescriptionsItem label="冷却期">{{ riskRuntime.cooldown ?? '-' }}</ElDescriptionsItem>
              <ElDescriptionsItem label="强制空仓">{{ fmtBool(riskRuntime.force_empty) }}</ElDescriptionsItem>
            </ElDescriptions>
          </ElCard>
        </template>
      </ElTabPane>

      <!-- Tab8: 扫描时序 -->
      <ElTabPane label="⏱️ 扫描时序" name="timing">
        <ElEmpty v-if="!timing" description="暂无时序数据" />
        <template v-else>
          <ElCard shadow="hover" class="section-card">
            <template #header><span class="card-title">🕐 交易时段</span></template>
            <ElTable :data="timingSessions" size="small" stripe border>
              <ElTableColumn prop="phase" label="阶段" min-width="140" />
              <ElTableColumn prop="time" label="时间" min-width="160" />
              <ElTableColumn prop="action" label="动作" min-width="200" />
              <ElTableColumn prop="scanning" label="是否扫描" width="110" align="center">
                <template #default="{ row }"><ElTag :type="row.scanning ? 'success' : 'info'" size="small">{{ row.scanning ? '是' : '否' }}</ElTag></template>
              </ElTableColumn>
            </ElTable>
          </ElCard>
          <ElCard shadow="hover" class="section-card" v-if="timingIntervals.length">
            <template #header><span class="card-title">⚡ 动态扫描间隔</span></template>
            <div class="interval-bars">
              <div v-for="iv in timingIntervals" :key="iv.phase" class="interval-row">
                <div class="iv-label">{{ iv.phase }}</div>
                <ElProgress :percentage="iv.pct || 0" :stroke-width="22" :text-inside="true" :format="() => iv.seconds + 's'" :color="iv.color || '#409eff'" />
              </div>
            </div>
          </ElCard>
          <ElCard shadow="hover" class="section-card" v-if="timingPremarket.length">
            <template #header><span class="card-title">🌅 盘前流程</span></template>
            <div class="timeline">
              <div v-for="(step, i) in timingPremarket" :key="i" class="timeline-item">
                <div class="tl-num">{{ i + 1 }}</div>
                <div class="tl-content">
                  <div class="tl-time" v-if="step.time">⏰ {{ step.time }}</div>
                  <div class="tl-action">{{ step.action }}</div>
                </div>
              </div>
            </div>
          </ElCard>
          <ElCard shadow="hover" class="section-card" v-if="timingRecovery">
            <template #header><span class="card-title">🔧 错误恢复</span></template>
            <ElAlert :title="timingRecovery.title || '错误恢复策略'" :description="timingRecovery.desc || ''" type="warning" show-icon :closable="false" />
          </ElCard>
        </template>
      </ElTabPane>
    </ElTabs>
  </div>
</template>

<style lang="scss" scoped>
.scan-insight-page {
  padding: 16px 20px;
  min-height: 100vh;
  background: var(--el-bg-color-page);
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  .header-left h2 { margin: 0 0 4px; font-size: 22px; font-weight: 700; }
  .header-sub { font-size: 13px; color: var(--el-text-color-secondary); }
}
.overview-bar {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 12px;
  margin-bottom: 18px;
  .summary-card {
    background: var(--el-bg-color-overlay);
    border-radius: 10px;
    padding: 14px 16px;
    border: 1px solid var(--el-border-color-lighter);
    text-align: center;
    .sc-label { font-size: 12px; color: var(--el-text-color-secondary); margin-bottom: 6px; }
    .sc-value { font-size: 16px; font-weight: 600; }
  }
}
.main-tabs {
  border-radius: 10px;
  :deep(.el-tabs__content) { padding: 12px 4px; }
}
.section-card {
  margin-bottom: 16px;
  border-radius: 10px;
  :deep(.el-card__header) { padding: 12px 18px; }
}
.card-title { font-size: 15px; font-weight: 600; }
.sub-title { font-size: 13px; font-weight: 600; color: var(--el-text-color-regular); margin-bottom: 8px; }

// Tab1: Architecture
.module-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
  .module-card {
    background: var(--el-fill-color-light);
    border-radius: 8px;
    padding: 12px 14px;
    border: 1px solid var(--el-border-color-lighter);
    .mod-name { font-weight: 600; font-size: 14px; margin-bottom: 4px; }
    .mod-file { font-size: 12px; color: var(--el-text-color-secondary); margin-bottom: 4px; }
    .mod-purpose { font-size: 12px; color: var(--el-text-color-regular); margin-bottom: 6px; }
    .method-tag { margin: 2px 4px 2px 0; }
  }
}
.data-flow {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  .flow-step {
    display: flex;
    align-items: center;
    gap: 6px;
    background: var(--el-fill-color-light);
    border-radius: 8px;
    padding: 8px 12px;
    border: 1px solid var(--el-border-color-lighter);
    .flow-num {
      width: 26px; height: 26px;
      background: var(--el-color-primary);
      color: #fff;
      border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
      font-size: 13px; font-weight: 700;
    }
    .flow-label { font-size: 13px; }
  }
  .flow-arrow { font-size: 20px; color: var(--el-text-color-secondary); font-weight: 700; }
}

// Tab2: Pipeline
.funnel-bar {
  display: flex;
  flex-direction: column;
  gap: 10px;
  .funnel-step { .funnel-label { font-size: 12px; color: var(--el-text-color-secondary); margin-bottom: 4px; } }
}
.layer-card {
  border-left: 4px solid var(--el-color-primary);
  .layer-header {
    display: flex;
    align-items: center;
    gap: 8px;
    .layer-icon { font-size: 18px; }
    .layer-name { font-weight: 600; font-size: 15px; }
  }
  .layer-body {
    .layer-desc { font-size: 13px; color: var(--el-text-color-regular); margin: 0 0 8px; }
    .layer-stats {
      display: flex;
      gap: 16px;
      margin-bottom: 8px;
      .stat-item { font-size: 13px; }
    }
    .layer-detail { font-size: 13px; margin-bottom: 6px; }
    .layer-raw {
      font-size: 11px;
      background: var(--el-fill-color);
      padding: 8px;
      border-radius: 6px;
      overflow-x: auto;
      max-height: 200px;
    }
  }
}

// Tab3: Strategy
.strategy-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
  gap: 16px;
}
.strat-header {
  display: flex;
  align-items: center;
  gap: 10px;
  .strat-name { font-weight: 700; font-size: 16px; }
}

// Tab4: Emotion
.phase-bar {
  display: flex;
  border-radius: 10px;
  overflow: hidden;
  height: 80px;
  .phase-segment {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    color: #fff;
    font-size: 12px;
    text-shadow: 0 1px 3px rgba(0,0,0,0.4);
    .phase-label { font-weight: 700; font-size: 14px; }
    .phase-range { font-size: 11px; }
    .phase-position { font-size: 11px; }
  }
}
.emotion-score { font-size: 22px; font-weight: 700; color: var(--el-color-warning); }

// Tab5: Signal
.state-machine {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 16px;
  .state-node {
    display: flex;
    flex-direction: column;
    align-items: center;
    border: 2px solid;
    border-radius: 10px;
    padding: 10px 16px;
    min-width: 100px;
    .state-dot {
      width: 14px; height: 14px;
      border-radius: 50%;
      margin-bottom: 6px;
    }
    .state-name { font-weight: 600; font-size: 13px; }
    .state-desc { font-size: 11px; color: var(--el-text-color-secondary); }
  }
}
.signal-stats-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 20px;
  justify-content: center;
  .stat-box {
    text-align: center;
    .stat-label { font-size: 12px; margin-top: 6px; }
    .stat-count { font-size: 11px; color: var(--el-text-color-secondary); }
  }
}

// Tab6: Quote
.degradation-steps {
  display: flex;
  flex-direction: column;
  gap: 8px;
  .degrade-step {
    display: flex;
    align-items: center;
    gap: 10px;
    .degrade-num {
      width: 28px; height: 28px;
      background: var(--el-color-warning);
      color: #fff;
      border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
      font-size: 13px; font-weight: 700;
      flex-shrink: 0;
    }
    .degrade-text { font-size: 13px; }
  }
}

// Tab7: Risk
.risk-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
  gap: 16px;
}
.risk-header { font-weight: 600; font-size: 15px; }
.risk-desc { font-size: 13px; color: var(--el-text-color-regular); margin: 0 0 10px; }

// Tab8: Timing
.interval-bars {
  display: flex;
  flex-direction: column;
  gap: 12px;
  .interval-row {
    display: flex;
    align-items: center;
    gap: 12px;
    .iv-label { min-width: 100px; font-size: 13px; font-weight: 500; }
    flex: 1;
  }
}
.timeline {
  display: flex;
  flex-direction: column;
  gap: 12px;
  .timeline-item {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    .tl-num {
      width: 28px; height: 28px;
      background: var(--el-color-primary);
      color: #fff;
      border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
      font-size: 13px; font-weight: 700;
      flex-shrink: 0;
    }
    .tl-content {
      .tl-time { font-size: 12px; color: var(--el-text-color-secondary); }
      .tl-action { font-size: 13px; }
    }
  }
}

// Responsive
@media (max-width: 900px) {
  .module-grid,
  .strategy-cards,
  .risk-grid {
    grid-template-columns: 1fr;
  }
  .overview-bar {
    grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  }
}
</style>