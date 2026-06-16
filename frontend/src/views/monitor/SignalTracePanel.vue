import { formatTradeDate } from '@/utils/scanner'
<template>
  <div class="signal-trace-panel">
    <div class="panel-header">
      <h3>信号链路追踪</h3>
      <div class="header-actions">
        <el-select v-model="selectedTraceId" placeholder="选择扫描记录" size="small" @change="loadTraceDetail">
          <el-option
            v-for="t in traceList"
            :key="t._id"
            :label="`${formatTradeDate(t.trade_date)} ${t.scan_time?.substring(11,19) || ''}`"
            :value="t._id"
          />
        </el-select>
        <el-button size="small" @click="loadTraces" :loading="loading">刷新</el-button>
      </div>
    </div>

    <!-- 管道流图 -->
    <div v-if="currentTrace" class="pipeline-flow">
      <div class="flow-header">
        候选总数: <strong>{{ currentTrace.summary?.total_candidates || 0 }}</strong>
        → 通过: <strong style="color:var(--success)">{{ currentTrace.summary?.passed || 0 }}</strong>
        → 拒绝: <strong style="color:var(--stock-up)">{{ (currentTrace.summary?.total_candidates || 0) - (currentTrace.summary?.passed || 0) }}</strong>
        <el-tag size="small" style="margin-left:8px">仓位系数: {{ ((Number(currentTrace.summary?.L8_position?.ratio ?? 0) || 0) * 100).toFixed(0) }}%</el-tag>
      </div>

      <div class="pipeline-bars">
        <div v-for="layer in pipelineLayers" :key="layer.key" class="pipeline-bar-item">
          <div class="bar-label">{{ layer.label }}</div>
          <div class="bar-track">
            <div
              v-if="layer.passed > 0"
              class="bar-passed"
              :style="{ width: (layer.passed / maxPassed * 100) + '%' }"
            >
              {{ layer.passed }}
            </div>
            <div
              v-if="layer.rejected > 0"
              class="bar-rejected"
              :style="{ width: (layer.rejected / maxPassed * 100) + '%' }"
            >
              {{ layer.rejected }}
            </div>
          </div>
          <div class="bar-detail">
            <span style="color:var(--success)">{{ layer.passed }}</span>
            <span v-if="layer.rejected > 0" style="color:var(--stock-up);margin-left:4px">→{{ layer.rejected }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 候选列表 -->
    <div v-if="currentTrace" class="candidate-list">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="淘汰原因" name="rejected">
          <div v-if="rejectedCandidates.length === 0" class="empty-hint">无被淘汰候选</div>
          <div v-for="c in rejectedCandidates" :key="c.ts_code" class="candidate-card rejected">
            <div class="candidate-header">
              <span class="candidate-name">{{ c.stock_name || c.ts_code }}</span>
              <span class="candidate-code">{{ c.ts_code }}</span>
              <el-tag :type="getStrategyColor(c.strategy)" size="small">{{ c.strategy_name }}</el-tag>
              <span v-if="c.pct_chg" :class="c.pct_chg >= 0 ? 'up' : 'down'">{{ formatPct(c.pct_chg) }}</span>
            </div>
            <div class="candidate-rejection">
              <span class="rejection-layer">🔴 {{ formatLayer(c.rejection_layer) }}</span>
              <span class="rejection-reason">{{ c.rejection_reason }}</span>
            </div>
            <div class="candidate-layers">
              <span v-for="(lr, key) in c.layer_results" :key="key"
                    :class="['layer-badge', lr.passed ? 'passed' : 'failed']"
                    :title="lr.reason || ''">
                {{ formatLayer(key) }}
              </span>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="通过候选" name="passed">
          <div v-if="passedCandidates.length === 0" class="empty-hint">无通过候选</div>
          <div v-for="c in passedCandidates" :key="c.ts_code" class="candidate-card passed">
            <div class="candidate-header">
              <span class="candidate-name">{{ c.stock_name || c.ts_code }}</span>
              <span class="candidate-code">{{ c.ts_code }}</span>
              <el-tag :type="getStrategyColor(c.strategy)" size="small">{{ c.strategy_name }}</el-tag>
              <span v-if="c.pct_chg" :class="c.pct_chg >= 0 ? 'up' : 'down'">{{ formatPct(c.pct_chg) }}</span>
              <span class="price">¥{{ c.price?.toFixed(2) }}</span>
            </div>
            <div class="candidate-layers">
              <span v-for="(lr, key) in c.layer_results" :key="key"
                    :class="['layer-badge', lr.passed ? 'passed' : 'failed']">
                {{ formatLayer(key) }}
              </span>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="全部候选" name="all">
          <div v-for="c in allCandidates" :key="c.ts_code"
               :class="['candidate-card', c.final_status === 'rejected' ? 'rejected' : 'passed']">
            <div class="candidate-header">
              <span class="candidate-name">{{ c.stock_name || c.ts_code }}</span>
              <span class="candidate-code">{{ c.ts_code }}</span>
              <el-tag :type="getStrategyColor(c.strategy)" size="small">{{ c.strategy_name }}</el-tag>
              <el-tag v-if="c.final_status === 'rejected'" type="danger" size="small" effect="plain">
                {{ formatLayer(c.rejection_layer) }}
              </el-tag>
              <el-tag v-else type="success" size="small" effect="plain">通过</el-tag>
            </div>
            <div v-if="c.final_status === 'rejected'" class="candidate-rejection">
              {{ c.rejection_reason }}
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- 空状态 -->
    <div v-if="!currentTrace && !loading" class="empty-state">
      <p>暂无扫描追踪记录</p>
      <p class="hint">启动扫描器后，每次扫描会自动记录选股全流程</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { api } from '@/api/client'

const loading = ref(false)
const traceList = ref([])
const currentTrace = ref(null)
const selectedTraceId = ref('')
const activeTab = ref('rejected')

const pipelineLayerDefs = [
  { key: 'L1_force_empty', label: 'L1 强制空仓' },
  { key: 'L2_special_period', label: 'L2 特殊时期' },
  { key: 'L3_sentiment', label: 'L3 情绪周期' },
  { key: 'L4_premarket', label: 'L4 盘前预选' },
  { key: 'L5_auction', label: 'L5 竞价过滤' },
  { key: 'L6_strategy', label: 'L6 策略量能' },
  { key: 'L7_ranking', label: 'L7 综合排序' },
  { key: 'L8_position', label: 'L8 仓位控制' },
]

const pipelineLayers = computed(() =>
  pipelineLayerDefs.map(def => {
    const s = currentTrace.value?.summary?.[def.key]
    return { ...def, passed: s?.passed || 0, rejected: s?.rejected || 0, input: s?.input || 0, output: s?.output || 0 }
  })
)

const allCandidates = computed(() => currentTrace.value?.candidates || [])
const rejectedCandidates = computed(() => allCandidates.value.filter(c => c.final_status === 'rejected'))
const passedCandidates = computed(() => allCandidates.value.filter(c => c.final_status === 'passed'))
const maxPassed = computed(() => {
  let max = 0
  for (const layer of pipelineLayers.value) {
    max = Math.max(max, layer.passed || 0, layer.rejected || 0)
  }
  return max || 1
})

function formatLayer(key) {
  const found = pipelineLayers.find(l => l.key === key)
  return found ? found.label : key
}

function formatPct(v) {
  if (v === null || v === undefined) return '-'
  if (typeof v !== 'number' || isNaN(v)) return '-'
  return (v >= 0 ? '+' : '') + v.toFixed(1) + '%'
}

function getStrategyColor(strategy) {
  const colors = {
    dragon_head: 'danger',
    limit_down_qiao: 'warning',
    halfway_chase: 'success',
    first_limit_up: '',
  }
  return colors[strategy] || 'info'
}

async function loadTraces() {
  loading.value = true
  try {
    const { data } = await api.get('/scanner/scan-traces', { params: { limit: 20 } })
    if (data?.success) {
      traceList.value = data.data || []
      if (traceList.value.length > 0 && !selectedTraceId.value) {
        selectedTraceId.value = traceList.value[0]._id
        await loadTraceDetail()
      }
    }
  } catch (e) {
    console.warn('加载追踪记录失败:', e)
  } finally {
    loading.value = false
  }
}

async function loadTraceDetail() {
  if (!selectedTraceId.value) return
  loading.value = true
  try {
    // 先加载passed候选(用于管道流图)
    const { data } = await api.get(`/scanner/scan-traces/${selectedTraceId.value}?status=passed&limit=50`)
    if (data?.success) {
      currentTrace.value = data.data
      // 异步加载rejected候选(用于“淘汰原因”tab)
      try {
        const r = await api.get(`/scanner/scan-traces/${selectedTraceId.value}?status=rejected&limit=200`)
        if (r.data?.success && r.data.data?.candidates) {
          // 合并rejected候选到candidates列表(前端通过final_status区分)
          const existing = currentTrace.value?.candidates || []
          currentTrace.value = {
            ...currentTrace.value,
            candidates: [...existing, ...r.data.data.candidates],
            rejected_layer_stats: r.data.data.rejected_layer_stats,
          }
        }
      } catch (e2) {
        console.warn('加载淘汰候选失败(非关键):', e2)
      }
    }
  } catch (e) {
    console.warn('加载追踪详情失败:', e)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadTraces()
})
</script>

<style scoped>
.signal-trace-panel {
  background: var(--bg-elevated);
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 16px;
  border: 1px solid var(--border-default, var(--border-default));
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.panel-header h3 {
  margin: 0;
  font-size: 16px;
  color: var(--text-primary, var(--text-primary));
}
.header-actions {
  display: flex;
  gap: 8px;
}

.pipeline-flow {
  margin-bottom: 16px;
}

.flow-header {
  margin-bottom: 12px;
  font-size: 14px;
  color: var(--text-regular, var(--text-secondary));
}

.pipeline-bars {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.pipeline-bar-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.bar-label {
  width: 100px;
  font-size: 12px;
  color: var(--text-secondary, var(--text-tertiary));
  text-align: right;
  flex-shrink: 0;
}

.bar-track {
  flex: 1;
  height: 20px;
  background: var(--bg-muted, var(--bg-secondary));
  border-radius: 3px;
  display: flex;
  overflow: hidden;
}

.bar-passed {
  background: var(--success);
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  color: var(--text-inverse);
  min-width: 24px;
  transition: width 0.3s;
}

.bar-rejected {
  background: var(--stock-up);
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  color: var(--text-inverse);
  min-width: 24px;
  transition: width 0.3s;
}

.bar-detail {
  width: 60px;
  font-size: 12px;
  flex-shrink: 0;
}

.candidate-list {
  margin-top: 8px;
}

.candidate-card {
  padding: 10px 12px;
  margin: 4px 0;
  border-radius: 6px;
  border-left: 3px solid transparent;
  background: var(--bg-muted);
}

.candidate-card.rejected {
  border-left-color: var(--stock-up);
}

.candidate-card.passed {
  border-left-color: var(--success);
}

.candidate-header {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.candidate-name {
  font-weight: 600;
  font-size: 14px;
  color: var(--text-primary, var(--text-primary));
}

.candidate-code {
  font-size: 12px;
  color: var(--text-secondary, var(--text-tertiary));
}

.up { color: var(--stock-up, var(--stock-up)); font-size: 12px; }
.down { color: var(--stock-down, var(--success)); font-size: 12px; }
.price { font-size: 12px; color: var(--text-regular, var(--text-secondary)); }

.candidate-rejection {
  margin-top: 6px;
  font-size: 13px;
  color: var(--text-regular, var(--text-secondary));
}

.rejection-layer {
  font-weight: 600;
  margin-right: 8px;
}

.rejection-reason {
  color: var(--text-secondary, var(--text-tertiary));
}

.candidate-layers {
  display: flex;
  gap: 4px;
  margin-top: 6px;
  flex-wrap: wrap;
}

.layer-badge {
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 10px;
  cursor: default;
}

.layer-badge.passed {
  background: var(--stock-down-bg);
  color: var(--stock-down, var(--success));
}

.layer-badge.failed {
  background: var(--stock-up-bg);
  color: var(--stock-up, var(--stock-up));
}

.empty-hint {
  text-align: center;
  padding: 24px;
  color: var(--text-secondary, var(--text-tertiary));
}

.empty-state {
  text-align: center;
  padding: 40px;
  color: var(--text-secondary, var(--text-tertiary));
}

.empty-state .hint {
  font-size: 13px;
  color: var(--text-placeholder, var(--text-placeholder));
}
</style>
