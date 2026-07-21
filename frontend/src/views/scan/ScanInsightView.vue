<template>
  <div class="scan-page">
    <!-- 顶部状态栏 -->
    <div class="status-bar">
      <div class="sb-item" v-for="item in statusItems" :key="item.label">
        <span class="sb-label">{{ item.label }}</span>
        <component :is="item.tag || 'span'" v-bind="item.tagProps || {}">{{ item.value }}</component>
      </div>
    </div>

    <!-- 6阶段时间线 -->
    <ElCard shadow="never" class="phase-card">
      <template #header>
        <div class="card-header"><span>⏱️ 扫描时序</span><span class="header-hint">6阶段 · 点击查看详情</span></div>
      </template>
      <div class="phase-track">
        <div v-for="(p, i) in phases" :key="p.phase" class="phase-block"
             :class="{ active: p.phase === currentPhase, dim: !p.scan, selected: selectedPhase === p.phase }"
             @click="selectedPhase = p">
          <div class="pb-connector" v-if="i > 0"><div class="pb-line" :class="{ lit: p.scan || phases[i-1].scan }" /></div>
          <div class="pb-body">
            <div class="pb-icon">{{ phaseIcon(p.phase) }}</div>
            <div class="pb-name">{{ phaseLabel(p.phase) }}</div>
            <div class="pb-time">{{ p.time?.split(' ')[0] }}</div>
            <div class="pb-badge" :class="p.scan ? 'scan' : 'rest'">{{ p.scan ? '扫描' : '休止' }}</div>
          </div>
        </div>
      </div>
      <!-- 选中阶段详情 -->
      <div class="phase-detail" v-if="selectedPhase">
        <div class="pd-row"><span class="pd-label">阶段</span><span>{{ phaseLabel(selectedPhase.phase) }} · {{ selectedPhase.time }}</span></div>
        <div class="pd-row"><span class="pd-label">动作</span><span>{{ selectedPhase.action }}</span></div>
        <div class="pd-row" v-if="selectedPhase.purpose"><span class="pd-label">目的</span><span class="pd-desc">{{ selectedPhase.purpose }}</span></div>
        <div class="pd-ops" v-if="selectedPhase.key_operations?.length">
          <div v-for="op in selectedPhase.key_operations" :key="op" class="pd-op">• {{ op }}</div>
        </div>
      </div>
    </ElCard>

    <!-- 双栏: 架构+管道 -->
    <div class="two-col">
      <!-- 数据流架构 -->
      <ElCard shadow="never" class="arch-card">
        <template #header><span>🏗️ 数据流架构</span></template>
        <div class="flow-steps">
          <div v-for="(step, i) in dataFlow" :key="i" class="flow-step">
            <div class="fs-num">{{ i + 1 }}</div>
            <div class="fs-text">{{ step }}</div>
            <div class="fs-arrow" v-if="i < dataFlow.length - 1">→</div>
          </div>
        </div>
        <div class="sub-modules" v-if="subModules.length">
          <div class="sm-title">子模块</div>
          <div v-for="m in subModules" :key="m.name" class="sm-row">
            <span class="sm-name">{{ m.name }}</span>
            <span class="sm-file">{{ m.file }}</span>
            <span class="sm-purpose">{{ m.purpose }}</span>
          </div>
        </div>
      </ElCard>

      <!-- 9层管道 -->
      <ElCard shadow="never" class="pipe-card">
        <template #header><span>🔧 9层管道</span></template>
        <div class="pipe-list">
          <div v-for="(layer, i) in pipelineLayers" :key="i" class="pipe-row">
            <div class="pr-left">
              <span class="pr-icon">{{ layer.icon }}</span>
              <span class="pr-id">L{{ i + 1 }}</span>
              <span class="pr-name">{{ layer.name }}</span>
            </div>
            <div class="pr-desc">{{ layer.description }}</div>
            <div class="pr-detail" v-if="layer.condition">
              <span class="pr-detail-label">条件:</span> {{ layer.condition }}
            </div>
            <div class="pr-detail" v-if="layer.effect">
              <span class="pr-detail-label">效果:</span> {{ layer.effect }}
            </div>
          </div>
        </div>
      </ElCard>
    </div>

    <!-- 三栏: 情绪+风控+信号 -->
    <div class="three-col">
      <!-- 情绪周期 -->
      <ElCard shadow="never" class="emotion-card">
        <template #header><span>🎭 情绪周期</span></template>
        <div class="emotion-latest" v-if="emotionLatest.score != null">
          <div class="el-score" :class="emotionPeriodClass">{{ emotionLatest.score?.toFixed(0) }}</div>
          <div class="el-period">{{ emotionLatest.period || '-' }}</div>
          <div class="el-stats">
            <span>涨停{{ emotionLatest.limit_up_count || 0 }}</span>
            <span>跌停{{ emotionLatest.limit_down_count || 0 }}</span>
            <span>炸板{{ emotionLatest.broken_count || 0 }}</span>
          </div>
        </div>
        <div class="emotion-dims" v-if="emotionDims.length">
          <div v-for="d in emotionDims" :key="d.name" class="ed-row">
            <span class="ed-name">{{ d.name }}</span>
            <div class="ed-bar-wrap"><div class="ed-bar" :style="{ width: (d.weight * 100) + '%' }" /></div>
            <span class="ed-wt">{{ (d.weight * 100).toFixed(0) }}%</span>
          </div>
        </div>
        <div class="emotion-periods" v-if="emotionPeriods.length">
          <div v-for="p in emotionPeriods" :key="p.name" class="ep-row" :style="{ borderLeftColor: p.color }">
            <span class="ep-name">{{ p.name }}</span>
            <span class="ep-range">{{ p.score_min }}-{{ p.score_max }}</span>
            <span class="ep-pos">仓位{{ p.position_ratio }}%</span>
          </div>
        </div>
      </ElCard>

      <!-- 风控体系 -->
      <ElCard shadow="never" class="risk-card">
        <template #header><span>🛡️ 风控体系</span></template>
        <!-- 策略参数表 -->
        <div class="risk-table" v-if="riskData.stop_loss">
          <div class="rt-header">
            <span class="rt-strat">策略</span><span>ATR止损</span><span>止盈</span><span>追踪止损</span><span>持仓</span>
          </div>
          <div v-for="key in Object.keys(riskData.stop_loss || {})" :key="key" class="rt-row">
            <span class="rt-strat">{{ key }}</span>
            <span class="rt-val danger" :title="'ATR自适应: ' + riskData.stop_loss?.[key]">{{ riskData.stop_loss?.[key] }}</span>
            <span class="rt-val success">{{ riskData.take_profit?.[key] }}</span>
            <span class="rt-val warn" :title="riskData.trailing_stop?.[key]">{{ (riskData.trailing_stop?.[key] || '').split('|')[0] }}<span class="rt-detail" v-if="(riskData.trailing_stop?.[key] || '').split('|').length > 1">4档</span></span>
            <span class="rt-val">{{ riskData.max_hold_days?.[key] }}</span>
          </div>
        </div>
        <!-- 高级风控规则 -->
        <div class="risk-advanced" v-if="riskData.advanced_rules?.length">
          <div class="ra-title">高级规则</div>
          <div v-for="rule in riskData.advanced_rules" :key="rule.name" class="ra-rule">
            <div class="ra-head">
              <span class="ra-name">{{ rule.name }}</span>
              <span class="ra-ver">{{ rule.version }}</span>
            </div>
            <div class="ra-formula">{{ rule.formula }}</div>
            <div class="ra-desc" v-if="rule.desc">{{ rule.desc }}</div>
            <div class="ra-tiers" v-if="rule.tiers">
              <div v-for="t in rule.tiers" :key="t.range" class="ra-tier">
                <span class="at-range">{{ t.range }}</span>
                <span class="at-obs">{{ t.obs }}</span>
                <span class="at-hit">{{ t.hit }}</span>
              </div>
            </div>
            <div class="ra-note" v-if="rule.cap">封顶: {{ rule.cap }}</div>
            <div class="ra-note" v-if="rule.min">下限: {{ rule.min }}</div>
          </div>
        </div>
        <!-- 运行时状态 -->
        <div class="risk-runtime" v-if="riskRuntime.circuit_breaker">
          <div class="rr-row"><span>熔断器</span><ElTag :type="riskRuntime.circuit_breaker?.trading_paused ? 'danger' : 'success'" size="small">{{ riskRuntime.circuit_breaker?.trading_paused ? '已暂停' : '正常' }}</ElTag></div>
          <div class="rr-row" v-if="riskRuntime.circuit_breaker?.consecutive_losses"><span>连亏</span><span>{{ riskRuntime.circuit_breaker.consecutive_losses }}/{{ riskRuntime.circuit_breaker.consecutive_loss_limit }}</span></div>
          <div class="rr-row"><span>仓位</span><span>{{ fmtPct(riskRuntime.position_ratio) }}</span></div>
        </div>
      </ElCard>

      <!-- 信号生命周期 -->
      <ElCard shadow="never" class="signal-card">
        <template #header><span>📡 信号生命周期</span></template>
        <div class="signal-flow" v-if="signalStates.length">
          <div v-for="(s, i) in signalStates" :key="s.name" class="sf-step">
            <div class="sf-dot" :style="{ background: s.color }" />
            <div class="sf-label">{{ s.label }}</div>
            <div class="sf-desc">{{ s.desc }}</div>
            <div class="sf-arrow" v-if="i < signalStates.length - 1">→</div>
          </div>
        </div>
        <div class="signal-stats" v-if="signalStats.length">
          <div v-for="s in signalStats" :key="s.status" class="ss-row">
            <div class="ss-dot" :style="{ background: s.color }" />
            <span class="ss-status">{{ s.status }}</span>
            <span class="ss-count">{{ s.count }}</span>
            <div class="ss-bar-wrap"><div class="ss-bar" :style="{ width: s.pct + '%', background: s.color }" /></div>
            <span class="ss-pct">{{ s.pct }}%</span>
          </div>
        </div>
        <div class="signal-expiry" v-if="signalExpiry.length">
          <div class="se-title">过期时间</div>
          <div v-for="e in signalExpiry" :key="e.strategy" class="se-row">
            <span>{{ e.strategy }}</span><span>{{ e.desc }}</span>
          </div>
        </div>
      </ElCard>
    </div>

    <!-- 双栏: 行情+因子 -->
    <div class="two-col">
      <!-- 行情管理 -->
      <ElCard shadow="never" class="quote-card">
        <template #header><span>📊 行情管理</span></template>
        <div class="quote-sources" v-if="quoteSources.length">
          <div class="qs-header"><span>数据源</span><span>优先级</span><span>用途</span></div>
          <div v-for="s in quoteSources" :key="s.name" class="qs-row">
            <span class="qs-name">{{ s.name }}</span>
            <span class="qs-pri">{{ s.priority }}</span>
            <span class="qs-purpose">{{ s.purpose }}</span>
          </div>
        </div>
        <div class="quote-cache" v-if="quoteCache">
          <div class="qc-title">缓存策略</div>
          <div class="qc-row"><span>最大年龄</span><span>{{ quoteCache.max_age }}</span></div>
          <div class="qc-row"><span>时间源</span><span>{{ quoteCache.time_source }}</span></div>
          <div class="qc-row"><span>预取间隔</span><span>{{ quotePrefetch?.interval }}</span></div>
          <div class="qc-row"><span>缓存大小</span><span>{{ quoteRuntime?.cache_size || 0 }}</span></div>
        </div>
        <div class="quote-degrade" v-if="quoteDegradation?.steps?.length">
          <div class="qd-title">降级策略</div>
          <div v-for="s in quoteDegradation.steps" :key="s" class="qd-step">{{ s }}</div>
        </div>
      </ElCard>

      <!-- 因子详情 -->
      <ElCard shadow="never" class="factor-card">
        <template #header><span>🧬 因子体系</span></template>
        <div class="factor-merge" v-if="factorMerge.length">
          <div class="fm-title">合并流程</div>
          <div v-for="m in factorMerge" :key="m.step" class="fm-row">
            <span class="fm-step">Step{{ m.step }}</span>
            <span class="fm-source">{{ m.source }}</span>
            <span class="fm-fields">{{ m.fields }}</span>
            <span class="fm-note" v-if="m.note">⚠️ {{ m.note }}</span>
          </div>
        </div>
        <div class="factor-list" v-if="factorList.length">
          <div class="fl-header"><span>因子</span><span>单位</span><span>来源</span><span>使用者</span></div>
          <div v-for="f in factorList" :key="f.name" class="fl-row" :class="{ warn: f.warning }">
            <span class="fl-name">{{ f.name }}</span>
            <span class="fl-unit">{{ f.unit }}</span>
            <span class="fl-src">{{ f.source }}</span>
            <span class="fl-used">{{ f.used_by }}</span>
          </div>
        </div>
      </ElCard>
    </div>

    <!-- MongoDB集合 -->
    <ElCard shadow="never" class="mongo-card" v-if="mongoCollections.length">
      <template #header><span>💾 MongoDB集合</span></template>
      <div class="mongo-grid">
        <div v-for="c in mongoCollections" :key="c.name" class="mc-item">
          <span class="mc-name">{{ c.name }}</span>
          <span class="mc-count">{{ c.count?.toLocaleString() }}</span>
          <span class="mc-purpose">{{ c.purpose }}</span>
        </div>
      </div>
    </ElCard>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElCard, ElTag } from 'element-plus'
import { api } from '@/api'

// ===== Data =====
const architecture = ref<any>({})
const timing = ref<any>({})
const strategies = ref<any>({})
const pipeline = ref<any>({})
const emotion = ref<any>({})
const signal = ref<any>({})
const quote = ref<any>({})
const risk = ref<any>({})
const factors = ref<any>({})

const selectedPhase = ref<any>(null)

// ===== Computed =====
const archStatus = computed(() => architecture.value?.runtime || {})
const phases = computed(() => timing.value?.phases || [])
const dataFlow = computed(() => architecture.value?.data_flow || [])
const subModules = computed(() => architecture.value?.sub_modules || [])
const mongoCollections = computed(() => architecture.value?.mongo_collections || [])
const pipelineLayers = computed(() => pipeline.value?.layers || [])
const emotionDims = computed(() => emotion.value?.dimensions || [])
const emotionPeriods = computed(() => emotion.value?.periods || [])
const emotionLatest = computed(() => emotion.value?.latest || {})
const signalStates = computed(() => signal.value?.states || [])
const signalStats = computed(() => signal.value?.status_stats || [])
const signalExpiry = computed(() => signal.value?.expiry || [])
const quoteSources = computed(() => quote.value?.sources || [])
const quoteCache = computed(() => quote.value?.cache)
const quotePrefetch = computed(() => quote.value?.prefetch)
const quoteDegradation = computed(() => quote.value?.degradation)
const quoteRuntime = computed(() => quote.value?.runtime)
const riskData = computed(() => risk.value || {})
const riskRuntime = computed(() => risk.value?.runtime || {})
const factorList = computed(() => factors.value?.factors || [])
const factorMerge = computed(() => factors.value?.merge_flow || [])

const currentPhase = computed(() => {
  const now = new Date()
  const hm = now.getHours() * 100 + now.getMinutes()
  if (hm < 900) return 'PREMARKET'
  if (hm < 925) return 'AUCTION'
  if (hm < 1130) return 'MORNING'
  if (hm < 1300) return 'LUNCH'
  if (hm < 1500) return 'AFTERNOON'
  return 'AFTER_CLOSE'
})

const emotionPeriodClass = computed(() => {
  const s = emotionLatest.value.score
  if (s == null) return ''
  if (s >= 70) return 'rising'
  if (s >= 55) return 'diff'
  if (s >= 40) return 'chaos'
  return 'freeze'
})

const statusItems = computed(() => {
  const rt = archStatus.value
  const items: any[] = [
    { label: '状态', value: rt.is_running ? '🟢 运行中' : '🔴 已停止', tag: 'span' },
    { label: '阶段', value: phaseLabel(currentPhase.value) },
    { label: '仓位', value: fmtPct(rt.position_ratio) },
  ]
  const cb = rt.circuit_breaker
  if (cb && typeof cb === 'object') {
    items.push({ label: '熔断', value: cb.trading_paused ? '已暂停' : '正常', tag: ElTag, tagProps: { type: cb.trading_paused ? 'danger' : 'success', size: 'small' } })
  }
  const se = rt.sentiment
  if (se && typeof se === 'object') {
    items.push({ label: '情绪', value: `${se.period || '-'} ${se.score?.toFixed(0) || ''}`, tag: ElTag, tagProps: { type: 'warning', size: 'small' } })
  }
  if (cb?.consecutive_losses) {
    items.push({ label: '连亏', value: `${cb.consecutive_losses}/${cb.consecutive_loss_limit}` })
  }
  return items
})

// ===== Helpers =====
function fmtPct(v: any) { return v != null ? (v * 100).toFixed(0) + '%' : '-' }
function phaseLabel(p?: string) {
  const m: Record<string, string> = { PREMARKET: '盘前准备', AUCTION: '集合竞价', MORNING: '早盘', LUNCH: '午休', AFTERNOON: '下午盘', AFTER_CLOSE: '盘后' }
  return m[p || ''] || p || '-'
}
function phaseIcon(p: string) {
  const m: Record<string, string> = { PREMARKET: '🌅', AUCTION: '📢', MORNING: '📈', LUNCH: '🍽️', AFTERNOON: '📉', AFTER_CLOSE: '📦' }
  return m[p] || '⚪'
}

// ===== Load =====
async function loadAll() {
  const endpoints = [
    { ref: architecture, path: '/scan-insight/architecture' },
    { ref: timing, path: '/scan-insight/timing' },
    { ref: strategies, path: '/scan-insight/strategies' },
    { ref: pipeline, path: '/scan-insight/pipeline' },
    { ref: emotion, path: '/scan-insight/emotion-cycle' },
    { ref: signal, path: '/scan-insight/signal-lifecycle' },
    { ref: quote, path: '/scan-insight/quote-manager' },
    { ref: risk, path: '/scan-insight/risk-system' },
    { ref: factors, path: '/scan-insight/factors' },
  ]
  await Promise.all(
    endpoints.map(e =>
      api.get(e.path)
        .then((res: any) => { e.ref.value = res?.data || res })
        .catch(() => {})
    )
  )
  selectedPhase.value = phases.value.find((p: any) => p.phase === currentPhase.value) || phases.value[0]
}

onMounted(loadAll)
</script>

<style lang="scss" scoped>
.scan-page { padding: 16px 20px; min-height: 100vh; background: var(--el-bg-color-page); display: flex; flex-direction: column; gap: 14px; }

// 状态栏
.status-bar {
  display: flex; gap: 20px; align-items: center; padding: 10px 18px;
  background: var(--el-bg-color-overlay); border-radius: 10px; border: 1px solid var(--el-border-color-lighter); flex-wrap: wrap;
  .sb-item { display: flex; align-items: center; gap: 5px; .sb-label { font-size: 12px; color: var(--el-text-color-secondary); } }
}

// 阶段时间线
.phase-card { .card-header { display: flex; justify-content: space-between; align-items: center; .header-hint { font-size: 11px; color: var(--el-text-color-secondary); } } }
.phase-track { display: flex; align-items: center; overflow-x: auto; padding-bottom: 8px; }
.phase-block {
  display: flex; align-items: center; cursor: pointer; flex-shrink: 0;
  &.dim { opacity: 0.45; }
  &.active .pb-body { border-color: var(--el-color-primary); box-shadow: 0 0 0 2px var(--el-color-primary-light-9); }
  &.selected .pb-body { background: var(--el-color-primary-light-9); }
}
.pb-connector { width: 20px; display: flex; align-items: center; .pb-line { width: 100%; height: 2px; background: var(--el-border-color); &.lit { background: var(--el-color-primary-light-5); } } }
.pb-body {
  display: flex; flex-direction: column; align-items: center; padding: 10px 14px;
  border: 2px solid var(--el-border-color-lighter); border-radius: 10px; min-width: 90px; transition: all 0.15s;
  &:hover { border-color: var(--el-color-primary-light-5); }
  .pb-icon { font-size: 22px; margin-bottom: 3px; }
  .pb-name { font-size: 13px; font-weight: 600; }
  .pb-time { font-size: 11px; color: var(--el-text-color-secondary); }
  .pb-badge { font-size: 10px; margin-top: 4px; padding: 1px 6px; border-radius: 3px;
    &.scan { background: rgba(103,194,58,0.12); color: var(--el-color-success); }
    &.rest { background: var(--fill-color-light); color: var(--el-text-color-placeholder); }
  }
}
.phase-detail {
  margin-top: 12px; padding: 12px 16px; background: var(--fill-color-lighter); border-radius: 8px;
  .pd-row { display: flex; gap: 8px; margin-bottom: 4px; .pd-label { font-size: 12px; color: var(--el-text-color-secondary); min-width: 36px; } .pd-desc { color: var(--el-text-color-regular); } }
  .pd-op { font-size: 12px; color: var(--el-text-color-regular); padding: 2px 0 2px 12px; }
}

// 双栏/三栏
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.three-col { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 14px; }

// 架构
.flow-steps { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px;
  .flow-step { display: flex; align-items: center; gap: 4px; .fs-num { width: 20px; height: 20px; line-height: 20px; text-align: center; background: var(--el-color-primary-light-9); color: var(--el-color-primary); border-radius: 50%; font-size: 11px; font-weight: 700; } .fs-text { font-size: 12px; } .fs-arrow { color: var(--el-text-color-placeholder); } }
}
.sub-modules { .sm-title { font-size: 12px; font-weight: 600; color: var(--el-text-color-secondary); margin-bottom: 6px; }
  .sm-row { display: flex; gap: 8px; padding: 3px 0; font-size: 11px; .sm-name { font-weight: 600; color: var(--el-color-primary); min-width: 120px; } .sm-file { color: var(--el-text-color-placeholder); min-width: 100px; } .sm-purpose { color: var(--el-text-color-regular); } }
}

// 管道
.pipe-list { display: flex; flex-direction: column; gap: 6px; }
.pipe-row { padding: 8px 10px; background: var(--fill-color-lighter); border-radius: 6px; border-left: 3px solid var(--el-color-primary-light-5);
  .pr-left { display: flex; align-items: center; gap: 6px; margin-bottom: 3px; .pr-icon { font-size: 16px; } .pr-id { font-size: 11px; font-weight: 700; color: var(--el-color-primary); } .pr-name { font-weight: 600; font-size: 13px; } }
  .pr-desc { font-size: 12px; color: var(--el-text-color-secondary); margin-bottom: 2px; }
  .pr-detail { font-size: 11px; color: var(--el-text-color-regular); .pr-detail-label { font-weight: 600; color: var(--el-text-color-secondary); } }
}

// 情绪
.emotion-latest { text-align: center; margin-bottom: 12px; padding: 10px; background: var(--fill-color-lighter); border-radius: 8px;
  .el-score { font-size: 36px; font-weight: 800; &.rising { color: #e74c3c; } &.diff { color: #e67e22; } &.chaos { color: #3498db; } &.freeze { color: #2c3e50; } }
  .el-period { font-size: 14px; color: var(--el-text-color-secondary); }
  .el-stats { display: flex; justify-content: center; gap: 12px; margin-top: 6px; font-size: 12px; color: var(--el-text-color-regular); }
}
.emotion-dims { margin-bottom: 10px; .ed-row { display: flex; align-items: center; gap: 6px; padding: 2px 0; .ed-name { font-size: 11px; min-width: 56px; } .ed-bar-wrap { flex: 1; height: 4px; background: var(--el-border-color-lighter); border-radius: 2px; } .ed-bar { height: 100%; background: var(--el-color-primary); border-radius: 2px; } .ed-wt { font-size: 10px; color: var(--el-text-color-placeholder); min-width: 28px; } } }
.emotion-periods { .ep-row { display: flex; align-items: center; gap: 8px; padding: 4px 8px; margin-bottom: 3px; border-left: 3px solid; border-radius: 0 4px 4px 0; background: var(--fill-color-lighter); font-size: 11px; .ep-name { font-weight: 600; min-width: 80px; } .ep-range { color: var(--el-text-color-secondary); } .ep-pos { margin-left: auto; color: var(--el-text-color-regular); } } }

// 风控
.risk-table { margin-bottom: 10px; .rt-header, .rt-row { display: flex; gap: 6px; padding: 4px 0; font-size: 11px; .rt-strat { min-width: 60px; font-weight: 600; } span { flex: 1; text-align: center; } } .rt-header { color: var(--el-text-color-secondary); border-bottom: 1px solid var(--el-border-color-lighter); } .rt-val { &.danger { color: var(--el-color-danger); } &.success { color: var(--el-color-success); } &.warn { color: var(--el-color-warning); cursor: help; } .rt-detail { font-size: 9px; background: var(--el-color-warning-light-9); color: var(--el-color-warning); padding: 0 3px; border-radius: 3px; margin-left: 3px; } } }
.risk-advanced { margin-bottom: 10px; .ra-title { font-size: 11px; font-weight: 600; color: var(--el-text-color-secondary); margin-bottom: 6px; padding-top: 8px; border-top: 1px dashed var(--el-border-color-lighter); } .ra-rule { padding: 6px 8px; margin-bottom: 4px; background: var(--fill-color-lighter); border-radius: 6px; .ra-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 3px; .ra-name { font-size: 11px; font-weight: 600; color: var(--el-color-primary); } .ra-ver { font-size: 9px; color: var(--el-text-color-placeholder); background: var(--fill-color); padding: 0 4px; border-radius: 3px; } } .ra-formula { font-size: 11px; font-family: monospace; color: var(--el-text-color-regular); } .ra-desc { font-size: 10px; color: var(--el-text-color-placeholder); margin-top: 2px; } .ra-tiers { display: flex; gap: 4px; margin-top: 4px; .ra-tier { flex: 1; padding: 3px 4px; background: var(--fill-color); border-radius: 4px; text-align: center; font-size: 10px; .at-range { font-weight: 600; color: var(--el-color-primary); display: block; } .at-obs { color: var(--el-color-success); } .at-hit { color: var(--el-text-color-placeholder); display: block; font-size: 9px; } } } .ra-note { font-size: 10px; color: var(--el-text-color-regular); margin-top: 2px; } } }
.risk-runtime { padding-top: 8px; border-top: 1px dashed var(--el-border-color); .rr-row { display: flex; justify-content: space-between; padding: 3px 0; font-size: 12px; } }

// 信号
.signal-flow { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 10px; .sf-step { display: flex; align-items: center; gap: 4px; .sf-dot { width: 8px; height: 8px; border-radius: 50%; } .sf-label { font-size: 11px; font-weight: 600; } .sf-desc { font-size: 10px; color: var(--el-text-color-placeholder); display: none; } .sf-arrow { color: var(--el-text-color-placeholder); font-size: 10px; } &:hover .sf-desc { display: inline; } } }
.signal-stats { margin-bottom: 10px; .ss-row { display: flex; align-items: center; gap: 6px; padding: 3px 0; .ss-dot { width: 6px; height: 6px; border-radius: 50%; } .ss-status { font-size: 11px; min-width: 60px; } .ss-count { font-size: 11px; font-weight: 600; min-width: 30px; } .ss-bar-wrap { flex: 1; height: 4px; background: var(--el-border-color-lighter); border-radius: 2px; } .ss-bar { height: 100%; border-radius: 2px; } .ss-pct { font-size: 10px; color: var(--el-text-color-placeholder); min-width: 32px; } } }
.signal-expiry { .se-title { font-size: 11px; font-weight: 600; color: var(--el-text-color-secondary); margin-bottom: 4px; } .se-row { display: flex; justify-content: space-between; font-size: 11px; padding: 2px 0; } }

// 行情
.quote-sources { margin-bottom: 10px; .qs-header, .qs-row { display: flex; gap: 8px; padding: 4px 0; font-size: 11px; span { flex: 1; } } .qs-header { color: var(--el-text-color-secondary); border-bottom: 1px solid var(--el-border-color-lighter); } .qs-name { font-weight: 600; } .qs-pri { text-align: center; } }
.quote-cache { margin-bottom: 10px; .qc-title { font-size: 11px; font-weight: 600; color: var(--el-text-color-secondary); margin-bottom: 4px; } .qc-row { display: flex; justify-content: space-between; font-size: 11px; padding: 2px 0; } }
.quote-degrade { .qd-title { font-size: 11px; font-weight: 600; color: var(--el-text-color-secondary); margin-bottom: 4px; } .qd-step { font-size: 11px; padding: 2px 0; color: var(--el-text-color-regular); } }

// 因子
.factor-merge { margin-bottom: 12px; .fm-title { font-size: 11px; font-weight: 600; color: var(--el-text-color-secondary); margin-bottom: 4px; } .fm-row { padding: 4px 0; font-size: 11px; .fm-step { font-weight: 700; color: var(--el-color-primary); margin-right: 6px; } .fm-source { font-weight: 600; margin-right: 6px; } .fm-fields { color: var(--el-text-color-regular); margin-right: 6px; } .fm-note { color: var(--el-color-warning); } } }
.factor-list { .fl-header, .fl-row { display: flex; gap: 6px; padding: 3px 0; font-size: 11px; span { flex: 1; } } .fl-header { color: var(--el-text-color-secondary); border-bottom: 1px solid var(--el-border-color-lighter); } .fl-name { font-weight: 600; } &.warn { background: rgba(230,162,60,0.05); } }

// MongoDB
.mongo-grid { display: flex; flex-wrap: wrap; gap: 8px; .mc-item { display: flex; flex-direction: column; padding: 8px 12px; background: var(--fill-color-lighter); border-radius: 6px; min-width: 140px; .mc-name { font-size: 12px; font-weight: 600; color: var(--el-color-primary); } .mc-count { font-size: 18px; font-weight: 700; } .mc-purpose { font-size: 10px; color: var(--el-text-color-placeholder); } } }

@media (max-width: 900px) { .two-col, .three-col { grid-template-columns: 1fr; } }
</style>
