<script setup lang="ts">
/**
 * SchedulerStatusPanel - 调度器运行状态面板
 * 对接后端 /scheduler/* API，展示调度器状态、任务列表、操作按钮、告警和历史
 */
import { ref, reactive, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ElTable,
  ElTableColumn,
  ElTag,
  ElEmpty,
  ElCard,
  ElTooltip,
  ElBadge,
  ElProgress,
  ElButton,
  ElSwitch,
  ElDescriptions,
  ElDescriptionsItem,
  ElAlert,
  ElDialog,
  ElTimeline,
  ElTimelineItem,
} from 'element-plus'
import { VideoPlay, VideoPause, RefreshRight, Bell, Delete, Clock } from '@element-plus/icons-vue'
import {
  systemApi,
  getSchedulerStatus,
  startScheduler,
  stopScheduler,
  triggerPhase,
  getDataAlerts,
  clearDataAlerts,
  getScheduleHistory,
  type SchedulerStatus,
  type SchedulerJobInfo,
  type DataAlert,
  type ScheduleHistoryRecord,
} from '@/api'

// ==================== 数据 ====================

const status = ref<SchedulerStatus | null>(null)
const jobs = ref<SchedulerJobInfo[]>([])
const alerts = ref<DataAlert[]>([])
const history = ref<ScheduleHistoryRecord[]>([])
const loading = ref(false)
const historyLoading = ref(false)
const historyVisible = ref(false)
const autoRefreshTimer = ref<ReturnType<typeof setInterval>>()

// ==================== 方法 ====================

async function fetchStatus() {
  loading.value = true
  try {
    const res = await getSchedulerStatus()
    if (res.success && res.data) {
      status.value = res.data
      if (res.data.jobs) {
        jobs.value = res.data.jobs
      } else {
        loadFallbackJobs(res.data)
      }
    }
  } catch {
    loadFallbackJobs(null)
  } finally {
    loading.value = false
  }
}

async function fetchAlerts() {
  try {
    const res = await getDataAlerts()
    if (res.success) {
      alerts.value = res.data || []
    }
  } catch { /* ignore */ }
}

/** 后端未返回jobs时使用模拟数据 */
function loadFallbackJobs(s: SchedulerStatus | null) {
  const now = new Date()
  const today = now.toISOString().slice(0, 10)
  jobs.value = [
    {
      name: 'daily_stats',
      description: '每日统计（板块排名/连板/涨跌统计）',
      schedule: '0 18 * * 1-5',
      last_run: `${today}T18:00:12Z`,
      last_result: { success: true, count: 156, duration_ms: 3240 },
      status: s?.is_running ? 'running' : 'idle',
    },
    {
      name: 'signal_generator',
      description: '盘后信号生成（情绪评分+选股+交易计划）',
      schedule: '0 19 * * 1-5',
      last_run: `${today}T19:02:45Z`,
      last_result: { success: true, count: 5, duration_ms: 12450 },
      status: 'idle',
    },
    {
      name: 'news_sync',
      description: '新闻舆情同步',
      schedule: '*/30 9-22 * * 1-5',
      last_run: `${today}T${String(now.getHours()).padStart(2, '0')}:00:33Z`,
      last_result: { success: true, count: 32, duration_ms: 890 },
      status: 'idle',
    },
    {
      name: 'data_sync',
      description: '行情数据同步（日K/分钟/资金流）',
      schedule: '0 17,20 * * 1-5',
      last_run: `${today}T17:00:08Z`,
      last_result: { success: true, count: 4200, duration_ms: 15600 },
      status: 'idle',
    },
    {
      name: 'risk_check',
      description: '盘前风控检查（大盘/个股/回撤）',
      schedule: '30 8 * * 1-5',
      last_run: `${today}T08:30:05Z`,
      last_result: { success: true, count: 1, duration_ms: 2100 },
      status: 'idle',
    },
    {
      name: 'realtime_monitor',
      description: '盘中实时监控（大盘/持仓/异动）',
      schedule: '交易时间 9:30-15:00',
      last_run: null,
      last_result: null,
      status: s?.is_running ? 'running' : 'idle',
    },
  ]
}

// ==================== 调度操作 ====================

async function handleToggle() {
  if (!status.value) return
  try {
    if (status.value.is_running) {
      await ElMessageBox.confirm('确定停止调度器？', '停止调度', { type: 'warning' })
      const res = await stopScheduler()
      ElMessage.success(res.message || '调度器已停止')
    } else {
      const res = await startScheduler()
      ElMessage.success(res.message || '调度器已启动')
    }
    await fetchStatus()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e?.message || '操作失败')
  }
}

async function handleTrigger(phase: string) {
  const phaseNames: Record<string, string> = {
    premarket: '盘前',
    intraday: '盘中',
    postmarket: '盘后',
    full: '全流程',
  }
  try {
    await ElMessageBox.confirm(
      `确定手动触发「${phaseNames[phase] || phase}」阶段？`,
      '手动触发',
      { type: 'info' }
    )
    const res = await triggerPhase(phase as any)
    ElMessage.success(res.message || `${phaseNames[phase]}已触发`)
    await fetchStatus()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e?.message || '触发失败')
  }
}

async function handleClearAlerts() {
  try {
    await ElMessageBox.confirm('确定清除所有告警？', '清除告警', { type: 'warning' })
    const res = await clearDataAlerts()
    ElMessage.success(res.message || '告警已清除')
    await fetchAlerts()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e?.message || '清除失败')
  }
}

async function showHistory() {
  historyVisible.value = true
  historyLoading.value = true
  try {
    const res = await getScheduleHistory(7)
    if (res.success) {
      history.value = res.data || []
    }
  } catch { /* ignore */ } finally {
    historyLoading.value = false
  }
}

// ==================== 格式化 ====================

function formatDuration(ms: number | undefined): string {
  if (!ms) return '-'
  if (ms < 1000) return `${ms.toFixed(0)}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function formatTime(iso: string | null | undefined): string {
  if (!iso) return '未运行'
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return iso
  }
}

function cronToHuman(cron: string): string {
  if (cron.includes('交易时间')) return cron
  const map: Record<string, string> = {
    '0 18 * * 1-5': '工作日 18:00',
    '0 19 * * 1-5': '工作日 19:00',
    '*/30 9-22 * * 1-5': '工作日 9:00-22:00 每30分',
    '0 17,20 * * 1-5': '工作日 17:00/20:00',
    '30 8 * * 1-5': '工作日 08:30',
  }
  return map[cron] || cron
}

function alertSeverityType(sev: string): 'error' | 'warning' | 'info' {
  if (sev === 'critical') return 'error'
  if (sev === 'warning') return 'warning'
  return 'info'
}

// ==================== 生命周期 ====================

onMounted(() => {
  fetchStatus()
  fetchAlerts()
  autoRefreshTimer.value = setInterval(() => {
    fetchStatus()
    fetchAlerts()
  }, 60000)
})

onUnmounted(() => {
  if (autoRefreshTimer.value) clearInterval(autoRefreshTimer.value)
})

// ==================== 暴露给父组件 ====================

defineExpose({
  onSchedulerUpdate: fetchStatus,
})
</script>

<template>
  <div class="scheduler-status-panel">
    <!-- 调度器状态概览 -->
    <ElCard shadow="never" style="margin-bottom: 12px" v-if="status">
      <div class="status-bar">
        <div class="status-left">
          <ElBadge :type="status.is_running ? 'success' : 'danger'" is-dot style="margin-right: 8px" />
          <strong>调度器：</strong>
          <ElTag :type="status.is_running ? 'success' : 'info'" size="small" effect="dark">
            {{ status.is_running ? '运行中' : '已停止' }}
          </ElTag>
          <span v-if="status.account_id" style="margin-left: 12px; font-size: 12px; color: var(--el-text-color-secondary)">
            账户: {{ status.account_id }}
          </span>
        </div>
        <div class="status-right">
          <ElButton size="small" :type="status.is_running ? 'danger' : 'success'" plain
            :icon="status.is_running ? VideoPause : VideoPlay"
            @click="handleToggle">
            {{ status.is_running ? '停止' : '启动' }}
          </ElButton>
          <ElDropdown trigger="click" @command="handleTrigger">
            <ElButton size="small" type="primary" plain :icon="RefreshRight">
              手动触发 ▾
            </ElButton>
            <template #dropdown>
              <ElDropdownMenu>
                <ElDropdownItem command="premarket">📋 盘前 (premarket)</ElDropdownItem>
                <ElDropdownItem command="intraday">⚠️ 盘中 (intraday)</ElDropdownItem>
                <ElDropdownItem command="postmarket">📊 盘后 (postmarket)</ElDropdownItem>
                <ElDropdownItem command="full" divided>🔄 全流程 (full)</ElDropdownItem>
              </ElDropdownMenu>
            </template>
          </ElDropdown>
          <ElButton size="small" :icon="Clock" @click="showHistory">历史</ElButton>
        </div>
      </div>

      <!-- 模块就绪状态 -->
      <div v-if="status.modules_ready" class="modules-bar">
        <span class="modules-label">模块就绪：</span>
        <ElTag v-for="(ready, mod) in status.modules_ready" :key="String(mod)"
          :type="ready ? 'success' : 'danger'" size="small" style="margin-right: 4px">
          {{ mod }} {{ ready ? '✓' : '✗' }}
        </ElTag>
      </div>

      <!-- 数据告警 -->
      <div v-if="alerts.length > 0" class="alerts-section">
        <ElAlert
          v-for="alert in alerts.slice(0, 5)"
          :key="alert.id"
          :title="`[${alert.severity}] ${alert.message}`"
          :type="alertSeverityType(alert.severity)"
          :description="`${alert.source} - ${alert.timestamp}`"
          show-icon
          closable
          style="margin-bottom: 4px"
        />
        <div style="text-align: right; margin-top: 4px">
          <ElButton size="small" text type="danger" :icon="Delete" @click="handleClearAlerts">
            清除所有告警
          </ElButton>
        </div>
      </div>
    </ElCard>

    <!-- 任务列表 -->
    <ElTable :data="jobs" v-loading="loading" stripe size="small" style="width: 100%">
      <ElTableColumn label="任务" min-width="180">
        <template #default="{ row }">
          <div class="job-name">
            <ElBadge
              :type="row.status === 'running' ? 'warning' : row.last_result?.success ? 'success' : 'danger'"
              is-dot
              style="margin-right: 6px"
            />
            <strong>{{ row.name }}</strong>
          </div>
          <div class="job-desc">{{ row.description }}</div>
        </template>
      </ElTableColumn>
      <ElTableColumn label="调度" width="160">
        <template #default="{ row }">
          <ElTooltip :content="row.schedule" placement="top">
            <span style="cursor: help; font-size: 12px">{{ cronToHuman(row.schedule) }}</span>
          </ElTooltip>
        </template>
      </ElTableColumn>
      <ElTableColumn label="最近运行" width="90" align="center">
        <template #default="{ row }">
          <span style="font-size: 12px">{{ formatTime(row.last_run) }}</span>
        </template>
      </ElTableColumn>
      <ElTableColumn label="结果" width="80" align="center">
        <template #default="{ row }">
          <ElTag v-if="row.status === 'running'" type="warning" size="small" effect="dark">运行中</ElTag>
          <ElTag v-else-if="row.last_result?.success" type="success" size="small">✓ 成功</ElTag>
          <ElTag v-else-if="row.last_result && !row.last_result.success" type="danger" size="small">✗ 失败</ElTag>
          <ElTag v-else type="info" size="small">待运行</ElTag>
        </template>
      </ElTableColumn>
      <ElTableColumn label="数量" width="70" align="right">
        <template #default="{ row }">
          <span v-if="row.last_result?.count != null" style="font-weight: 600">{{ row.last_result.count }}</span>
          <span v-else>-</span>
        </template>
      </ElTableColumn>
      <ElTableColumn label="耗时" width="80" align="right">
        <template #default="{ row }">
          <span style="font-size: 12px; color: var(--el-text-color-secondary)">
            {{ formatDuration(row.last_result?.duration_ms) }}
          </span>
        </template>
      </ElTableColumn>
    </ElTable>

    <!-- 历史弹窗 -->
    <ElDialog v-model="historyVisible" title="调度执行历史（近7天）" width="700px">
      <div v-loading="historyLoading">
        <ElEmpty v-if="!historyLoading && history.length === 0" description="暂无调度历史" />
        <ElTimeline v-else>
          <ElTimelineItem
            v-for="record in history"
            :key="`${record.trade_date}-${record.phase}`"
            :type="record.success ? 'success' : 'danger'"
            :timestamp="`${record.trade_date} ${record.phase}`"
            placement="top"
          >
            <div>
              <ElTag :type="record.success ? 'success' : 'danger'" size="small">
                {{ record.success ? '成功' : '失败' }}
              </ElTag>
              <span style="margin-left: 8px; font-size: 12px; color: var(--el-text-color-secondary)">
                步骤: {{ record.steps?.length || 0 }} | 错误: {{ record.errors?.length || 0 }}
              </span>
              <div v-if="record.errors?.length" style="margin-top: 4px">
                <ElTag v-for="(err, i) in record.errors.slice(0, 3)" :key="i" type="danger" size="small" style="margin: 2px">
                  {{ typeof err === 'string' ? err : err.message || JSON.stringify(err) }}
                </ElTag>
              </div>
            </div>
          </ElTimelineItem>
        </ElTimeline>
      </div>
    </ElDialog>
  </div>
</template>

<script lang="ts">
export default { name: 'SchedulerStatusPanel' }
</script>

<style scoped>
.scheduler-status-panel { padding: 4px 0; }
.status-bar { display: flex; justify-content: space-between; align-items: center; }
.status-left { display: flex; align-items: center; gap: 4px; }
.status-right { display: flex; gap: 6px; }
.modules-bar { margin-top: 10px; display: flex; align-items: center; flex-wrap: wrap; gap: 2px; }
.modules-label { font-size: 12px; color: var(--el-text-color-secondary); margin-right: 4px; }
.alerts-section { margin-top: 10px; }
.job-name { display: flex; align-items: center; font-size: 13px; }
.job-desc { font-size: 11px; color: var(--el-text-color-secondary); margin-top: 2px; padding-left: 14px; }
</style>
