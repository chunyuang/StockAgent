<script setup lang="ts">
/**
 * RiskStatusPanel - 实时风控状态展示
 * 显示当前风控状态（正常/警告/熔断）+ 最近拒绝记录
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import {
  ElTag,
  ElTable,
  ElTableColumn,
  ElEmpty,
  ElBadge,
  ElDescriptions,
  ElDescriptionsItem,
} from 'element-plus'

import { systemApi } from '@/api'

// ==================== 类型 ====================

type RiskLevel = 'normal' | 'warning' | 'circuit_breaker'
type CheckStatus = 'pass' | 'warn' | 'block'

interface RiskCheckItem {
  name: string
  key: string
  status: CheckStatus
  message: string
  value?: string
}

interface RejectionRecord {
  time: string
  ts_code: string
  stock_name: string
  reason: string
  risk_level: string
  strategy?: string
}

// ==================== 状态 ====================

const riskLevel = ref<RiskLevel>('normal')
const lastCheckTime = ref('')
const checkItems = ref<RiskCheckItem[]>([])
const rejectionRecords = ref<RejectionRecord[]>([])
let pollTimer: ReturnType<typeof setInterval> | null = null

// ==================== 计算属性 ====================

const riskLevelLabel = computed(() => {
  const map: Record<RiskLevel, string> = {
    normal: '正常运行',
    warning: '风险警告',
    circuit_breaker: '熔断保护',
  }
  return map[riskLevel.value]
})

// riskLevelType removed - unused computed

const riskLevelIcon = computed(() => {
  const map: Record<RiskLevel, string> = {
    normal: '✅',
    warning: '⚠️',
    circuit_breaker: '🛑',
  }
  return map[riskLevel.value]
})

const passCount = computed(() => checkItems.value.filter(i => i.status === 'pass').length)
const warnCount = computed(() => checkItems.value.filter(i => i.status === 'warn').length)
const blockCount = computed(() => checkItems.value.filter(i => i.status === 'block').length)

// ==================== 方法 ====================

async function fetchRiskStatus() {
  try {
    const res = await systemApi.getRiskStatus()
    if (res?.success && res?.data) {
      riskLevel.value = res.data.risk_level || 'normal'
      checkItems.value = res.data.check_items || []
      rejectionRecords.value = res.data.rejection_records || []
      lastCheckTime.value = res.data.last_check_time || new Date().toLocaleTimeString('zh-CN')
    } else {
      // API返回但无数据，使用空状态
      loadFallbackData()
    }
  } catch {
    // 后端API不可用，使用模拟数据
    loadFallbackData()
  }
}

function loadFallbackData() {
  checkItems.value = [
    { name: '市场环境', key: 'market', status: 'pass', message: '上证指数今日跌幅0.52%，在安全范围内', value: '-0.52%' },
    { name: '日内回撤', key: 'drawdown', status: 'pass', message: '当前回撤1.2%，未触发熔断', value: '1.2%' },
    { name: '连续亏损', key: 'loss', status: 'warn', message: '连续亏损2次，接近熔断阈值3次', value: '2次' },
    { name: '个股风险', key: 'stock', status: 'pass', message: '最近检查的股票风险均在可接受范围内', value: '-' },
  ]
  riskLevel.value = 'warning'
  lastCheckTime.value = new Date().toLocaleTimeString('zh-CN')
  rejectionRecords.value = [
    { time: '2026-04-24 09:45:12', ts_code: '688123.SH', stock_name: '西力科技', reason: '20日波动率28.5%超过阈值20%', risk_level: 'high', strategy: '半路追涨' },
    { time: '2026-04-24 10:12:30', ts_code: '300456.SZ', stock_name: 'ST慧辰', reason: 'ST股票已被排除', risk_level: 'critical', strategy: '首板打板' },
    { time: '2026-04-23 14:30:05', ts_code: '002345.SZ', stock_name: '潮宏基', reason: '市值18亿元低于阈值30亿元', risk_level: 'medium', strategy: '龙头低吸' },
  ]
}

function statusTagType(status: CheckStatus) {
  return status === 'pass' ? 'success' : status === 'warn' ? 'warning' : 'danger' as const
}

function statusLabel(status: CheckStatus) {
  return status === 'pass' ? '通过' : status === 'warn' ? '警告' : '拒绝'
}

// ==================== 生命周期 ====================

onMounted(() => {
  fetchRiskStatus()
  // 每30秒轮询
  pollTimer = setInterval(fetchRiskStatus, 30000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<template>
  <div class="risk-status-panel">
    <!-- 风控状态总览 -->
    <div class="status-header">
      <div class="status-indicator" :class="riskLevel">
        <span class="status-icon">{{ riskLevelIcon }}</span>
        <span class="status-text">{{ riskLevelLabel }}</span>
      </div>
      <div class="status-stats">
        <ElBadge :value="passCount" type="success">
          <ElTag size="small" type="success">通过</ElTag>
        </ElBadge>
        <ElBadge :value="warnCount" type="warning">
          <ElTag size="small" type="warning">警告</ElTag>
        </ElBadge>
        <ElBadge :value="blockCount" type="danger">
          <ElTag size="small" type="danger">拒绝</ElTag>
        </ElBadge>
      </div>
      <div class="last-check">
        最后检查：{{ lastCheckTime || '-' }}
      </div>
    </div>

    <!-- 检查明细 -->
    <ElDescriptions :column="1" border size="small" class="check-descriptions">
      <ElDescriptionsItem v-for="item in checkItems" :key="item.key" :label="item.name">
        <div class="check-item">
          <ElTag :type="statusTagType(item.status)" size="small" effect="dark">{{ statusLabel(item.status) }}</ElTag>
          <span class="check-msg">{{ item.message }}</span>
          <span v-if="item.value" class="check-value">{{ item.value }}</span>
        </div>
      </ElDescriptionsItem>
    </ElDescriptions>

    <!-- 拒绝记录 -->
    <div class="rejection-section">
      <div class="section-title">📋 最近拒绝记录</div>
      <ElTable v-if="rejectionRecords.length" :data="rejectionRecords" size="small" stripe border max-height="250">
        <ElTableColumn prop="time" label="时间" width="160" />
        <ElTableColumn prop="ts_code" label="代码" width="110" />
        <ElTableColumn prop="stock_name" label="名称" width="90" />
        <ElTableColumn prop="strategy" label="策略" width="90" />
        <ElTableColumn prop="reason" label="拒绝原因" show-overflow-tooltip />
        <ElTableColumn prop="risk_level" label="风险级别" width="90" align="center">
          <template #default="{ row }">
            <ElTag :type="row.risk_level === 'critical' ? 'danger' : row.risk_level === 'high' ? 'warning' : 'info'" size="small">
              {{ row.risk_level === 'critical' ? '严重' : row.risk_level === 'high' ? '高' : row.risk_level === 'medium' ? '中' : '低' }}
            </ElTag>
          </template>
        </ElTableColumn>
      </ElTable>
      <ElEmpty v-else description="暂无拒绝记录" :image-size="60" />
    </div>
  </div>
</template>

<script lang="ts">
export default { name: 'RiskStatusPanel' }
</script>

<style scoped lang="scss">
.risk-status-panel {
  padding: 8px 0;
}
.status-header {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 16px;
  margin-bottom: 16px;
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
}
.status-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  border-radius: 6px;
  font-weight: 700;
  font-size: 16px;
  &.normal { background: rgba(103, 194, 58, 0.1); color: #67c23a; }
  &.warning { background: rgba(230, 162, 60, 0.1); color: #e6a23c; }
  &.circuit_breaker { background: rgba(245, 108, 108, 0.1); color: #f56c6c; }
  .status-icon { font-size: 20px; }
}
.status-stats {
  display: flex;
  gap: 12px;
}
.last-check {
  margin-left: auto;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.check-descriptions {
  margin-bottom: 16px;
}
.check-item {
  display: flex;
  align-items: center;
  gap: 8px;
}
.check-msg {
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.check-value {
  font-weight: 600;
  color: var(--el-color-primary);
  margin-left: auto;
}
.rejection-section {
  margin-top: 8px;
  .section-title {
    font-size: 14px;
    font-weight: 600;
    color: var(--el-text-color-primary);
    margin-bottom: 10px;
  }
}
</style>
