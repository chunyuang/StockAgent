<script setup lang="ts">
/**
 * IntradayRiskPanel - 盘中持仓风控状态
 * 实时展示：大盘环境、持仓盈亏、风控熔断状态、异动提醒
 */
import { ref, reactive, onMounted, onUnmounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import {
  ElCard,
  ElTag,
  ElTable,
  ElTableColumn,
  ElBadge,
  ElDivider,
} from 'element-plus'
import { systemApi } from '@/api'
import { tradingApi, type Position } from '@/api'

// ==================== 类型 ====================

interface MarketStatus {
  index_code: string
  index_name: string
  change_pct: number
  limit_up_count: number
  limit_down_count: number
}

interface PositionAlert {
  ts_code: string
  stock_name: string
  alert_type: string
  message: string
  severity: 'info' | 'warning' | 'danger'
  time: string
}

// ==================== 数据 ====================

const riskLevel = ref<'normal' | 'warning' | 'circuit_breaker'>('normal')
const marketStatus = reactive<MarketStatus>({
  index_code: 'sh000001',
  index_name: '上证指数',
  change_pct: 0,
  limit_up_count: 0,
  limit_down_count: 0,
})
const positions = ref<Position[]>([])
const positionAlerts = ref<PositionAlert[]>([])
const loading = ref(false)
const lastRefresh = ref('')
const autoRefreshTimer = ref<ReturnType<typeof setInterval>>()

const riskLevelMap = {
  normal: { label: '正常', color: '#67c23a', tagType: 'success' },
  warning: { label: '预警', color: '#e6a23c', tagType: 'warning' },
  circuit_breaker: { label: '熔断', color: '#f56c6c', tagType: 'danger' },
}

const currentRiskDisplay = computed(() => riskLevelMap[riskLevel.value])

// ==================== 方法 ====================

async function fetchRiskStatus() {
  try {
    const res = await systemApi.getRiskStatus()
    if (res?.success && res?.data) {
      riskLevel.value = res.data.risk_level || 'normal'
    }
  } catch { /* fallback */ }
}

async function fetchPositions() {
  try {
    const accounts = await tradingApi.getSimAccounts()
    if (accounts.length > 0) {
      const posRes = await tradingApi.getPositions(accounts[0].account_id)
      positions.value = posRes || []
    }
  } catch { /* ignore */ }
}

async function refresh() {
  loading.value = true
  try {
    await Promise.all([fetchRiskStatus(), fetchPositions()])
    lastRefresh.value = new Date().toLocaleTimeString('zh-CN')
  } finally {
    loading.value = false
  }
}

/** WebSocket推送风险事件时调用 */
function onRiskEvent(event: { risk_level: string; message: string }) {
  riskLevel.value = (event.risk_level as any) || 'warning'
  if (event.risk_level === 'circuit_breaker') {
    ElMessage.error(`⚠️ 风控熔断：${event.message}`)
  } else if (event.risk_level === 'warning') {
    ElMessage.warning(`⚠️ 风险预警：${event.message}`)
  }
}

/** WebSocket推送持仓异动时调用 */
function onPositionAlert(alert: PositionAlert) {
  positionAlerts.value.unshift(alert)
  if (positionAlerts.value.length > 20) positionAlerts.value.pop()
}

defineExpose({ onRiskEvent, onPositionAlert })

onMounted(() => {
  refresh()
  autoRefreshTimer.value = setInterval(refresh, 30000)
})

onUnmounted(() => {
  if (autoRefreshTimer.value) clearInterval(autoRefreshTimer.value)
})
</script>

<template>
  <div class="intraday-risk-panel">
    <!-- 风控等级横幅 -->
    <div class="risk-banner" :class="riskLevel">
      <div class="risk-level-badge">
        <ElBadge :type="(currentRiskDisplay.tagType as any)" is-dot />
        <span class="risk-label" :style="{ color: currentRiskDisplay.color }">
          风控等级：{{ currentRiskDisplay.label }}
        </span>
      </div>
      <span class="refresh-time">{{ lastRefresh ? `刷新于 ${lastRefresh}` : '' }}</span>
    </div>

    <div class="monitor-grid">
      <!-- 大盘环境卡片 -->
      <ElCard shadow="never" class="market-card">
        <template #header><span>📊 大盘环境</span></template>
        <div class="market-row">
          <span class="market-name">{{ marketStatus.index_name }}</span>
          <span class="market-change" :style="{ color: marketStatus.change_pct >= 0 ? '#f56c6c' : '#67c23a' }">
            {{ marketStatus.change_pct >= 0 ? '+' : '' }}{{ marketStatus.change_pct.toFixed(2) }}%
          </span>
        </div>
        <div class="limit-row">
          <ElTag type="danger" size="small">涨停 {{ marketStatus.limit_up_count }}</ElTag>
          <ElTag type="success" size="small" style="margin-left: 8px">跌停 {{ marketStatus.limit_down_count }}</ElTag>
        </div>
      </ElCard>

      <!-- 持仓概况卡片 -->
      <ElCard shadow="never" class="position-card">
        <template #header><span>💼 持仓概况</span></template>
        <div v-if="positions.length === 0" class="empty-pos">当前无持仓</div>
        <div v-else>
          <div class="pos-stat">
            <span>持仓数</span>
            <strong>{{ positions.length }}</strong>
          </div>
          <ElTable :data="positions" size="small" max-height="200" stripe>
            <ElTableColumn prop="ts_code" label="代码" width="100" />
            <ElTableColumn prop="stock_name" label="名称" width="80" />
            <ElTableColumn label="盈亏" width="90" align="right">
              <template #default="{ row }">
                <span :style="{ color: (row.profit_pct || 0) >= 0 ? '#f56c6c' : '#67c23a', fontWeight: 600 }">
                  {{ row.profit_pct != null ? ((row.profit_pct >= 0 ? '+' : '') + (row.profit_pct * 100).toFixed(2) + '%') : '-' }}
                </span>
              </template>
            </ElTableColumn>
            <ElTableColumn label="天数" width="60" align="center" prop="hold_days" />
          </ElTable>
        </div>
      </ElCard>
    </div>

    <!-- 异动提醒列表 -->
    <div v-if="positionAlerts.length > 0" class="alert-section">
      <ElDivider content-position="left">🚨 异动提醒</ElDivider>
      <div class="alert-list">
        <div
          v-for="(alert, idx) in positionAlerts"
          :key="idx"
          class="alert-item"
          :class="alert.severity"
        >
          <span class="alert-time">{{ alert.time }}</span>
          <ElTag :type="(alert.severity === 'danger' ? 'danger' : alert.severity === 'warning' ? 'warning' : 'info') as any" size="small">
            {{ alert.stock_name }}
          </ElTag>
          <span class="alert-msg">{{ alert.message }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script lang="ts">
export default { name: 'IntradayRiskPanel' }
</script>

<style scoped>
.intraday-risk-panel { padding: 4px 0; }
.risk-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
  border-radius: 6px;
  margin-bottom: 12px;
  transition: all 0.3s;
}
.risk-banner.normal { background: rgba(103,194,58,0.08); border-left: 3px solid #67c23a; }
.risk-banner.warning { background: rgba(230,162,60,0.08); border-left: 3px solid #e6a23c; }
.risk-banner.circuit_breaker { background: rgba(245,108,108,0.08); border-left: 3px solid #f56c6c; }
.risk-level-badge { display: flex; align-items: center; gap: 8px; }
.risk-label { font-size: 15px; font-weight: 700; }
.refresh-time { font-size: 12px; color: var(--el-text-color-secondary); }
.monitor-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.market-card, .position-card { font-size: 13px; }
.market-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.market-name { font-weight: 600; }
.market-change { font-size: 20px; font-weight: 700; }
.limit-row { margin-top: 4px; }
.pos-stat { display: flex; justify-content: space-between; margin-bottom: 8px; font-size: 13px; }
.empty-pos { text-align: center; color: var(--el-text-color-placeholder); padding: 20px 0; }
.alert-section { margin-top: 8px; }
.alert-list { max-height: 160px; overflow-y: auto; }
.alert-item {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 10px; border-radius: 4px; margin-bottom: 4px;
  font-size: 12px;
}
.alert-item.danger { background: rgba(245,108,108,0.06); }
.alert-item.warning { background: rgba(230,162,60,0.06); }
.alert-item.info { background: var(--el-fill-color-light); }
.alert-time { color: var(--el-text-color-secondary); white-space: nowrap; }
.alert-msg { flex: 1; }
</style>
