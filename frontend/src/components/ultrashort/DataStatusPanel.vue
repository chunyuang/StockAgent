<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElCard, ElEmpty, ElProgress, ElTable, ElTableColumn, ElTag, ElButton, ElTooltip } from 'element-plus'
import VChart from 'vue-echarts'

interface DailyCoverage {
  date: string
  total: number
  factor_rate: number
  groups: Record<string, number>
}

interface DataStatus {
  collections: Record<string, number>
  daily_coverage: DailyCoverage[]
  latest: { stock_daily: string | null; daily_basic: string | null }
  factor_groups: Record<string, number>
}

const loading = ref(false)
const status = ref<DataStatus | null>(null)
const error = ref('')

async function fetchData() {
  loading.value = true
  error.value = ''
  try {
    const res = await fetch('/api/v1/system/data-status')
    const json = await res.json()
    if (json.success) {
      status.value = json.data
    } else {
      error.value = json.message || '查询失败'
    }
  } catch (e: any) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

// 覆盖率热力图
const heatmapOption = computed(() => {
  if (!status.value?.daily_coverage?.length) return null
  const cov = status.value.daily_coverage
  const groups = ['basic', 'technical', 'volume', 'limit', 'sentiment']
  const groupLabels: Record<string, string> = {
    basic: '基础', technical: '技术指标', volume: '量价', limit: '涨跌停', sentiment: '情绪'
  }

  // 构建数据 [x(group), y(date), value]
  const data: number[][] = []
  const yLabels = cov.map(c => {
    const d = c.date
    return `${d.slice(4, 6)}/${d.slice(6, 8)}`
  })

  cov.forEach((c, yi) => {
    groups.forEach((g, xi) => {
      data.push([xi, yi, c.groups[g] || 0])
    })
  })

  return {
    tooltip: {
      formatter: (p: any) => {
        const c = cov[p.data[1]]
        const g = groups[p.data[0]]
        return `${c.date} ${groupLabels[g]}<br/>覆盖率: ${p.data[2]}%<br/>股票数: ${c.total}`
      }
    },
    grid: { left: 60, right: 30, top: 10, bottom: 30 },
    xAxis: {
      type: 'category',
      data: groups.map(g => groupLabels[g]),
      splitArea: { show: true },
      axisLabel: { fontSize: 11 }
    },
    yAxis: {
      type: 'category',
      data: yLabels,
      axisLabel: { fontSize: 10 }
    },
    visualMap: {
      min: 0, max: 100,
      inRange: {
        color: ['#f56c6c', '#e6a23c', '#f5da55', '#95d475', '#67c23a']
      },
      orient: 'horizontal',
      left: 'center',
      bottom: 0,
      itemWidth: 12,
      itemHeight: 100,
      text: ['100%', '0%'],
      textStyle: { fontSize: 10 }
    },
    series: [{
      type: 'heatmap',
      data,
      label: {
        show: true,
        formatter: (p: any) => p.data[2] > 0 ? `${p.data[2]}` : '',
        fontSize: 9,
        color: '#333'
      },
      itemStyle: { borderWidth: 1, borderColor: '#fff' }
    }]
  }
})

// 每日股票数趋势
const stockCountOption = computed(() => {
  if (!status.value?.daily_coverage?.length) return null
  const cov = status.value.daily_coverage
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 50, right: 20, top: 20, bottom: 30 },
    xAxis: {
      type: 'category',
      data: cov.map(c => `${c.date.slice(4, 6)}/${c.date.slice(6, 8)}`),
      axisLabel: { fontSize: 10, rotate: 30 }
    },
    yAxis: [
      { type: 'value', name: '股票数', min: 0, axisLabel: { fontSize: 10 } },
      { type: 'value', name: '覆盖率%', min: 0, max: 100, axisLabel: { fontSize: 10 } }
    ],
    series: [
      {
        name: '股票数', type: 'bar', data: cov.map(c => c.total),
        itemStyle: { color: '#409eff' }, barMaxWidth: 20
      },
      {
        name: '因子覆盖率', type: 'line', yAxisIndex: 1,
        data: cov.map(c => c.factor_rate),
        itemStyle: { color: '#67c23a' }, lineStyle: { width: 2 },
        areaStyle: { color: 'rgba(103,194,58,0.1)' }
      }
    ]
  }
})

// 集合大小表
const collectionRows = computed(() => {
  if (!status.value?.collections) return []
  const names: Record<string, string> = {
    stock_daily_ak_full: '日线行情', daily_basic: '基础指标(PE/PB)',
    index_daily: '指数日线', limit_list: '涨停池',
    limit_pool_down: '跌停池', backtest_tasks: '回测任务'
  }
  return Object.entries(status.value.collections).map(([k, v]) => ({
    key: k, name: names[k] || k, count: v as number
  }))
})

// 健康度评分
const healthScore = computed(() => {
  if (!status.value) return 0
  const cov = status.value.daily_coverage
  if (!cov.length) return 0
  // 最近3天的平均因子覆盖率
  const recent = cov.slice(-3)
  const avgFactor = recent.reduce((s, c) => s + c.factor_rate, 0) / recent.length
  // 数据新鲜度
  const latest = status.value.latest.stock_daily
  const today = new Date()
  const latestDate = latest ? new Date(
    parseInt(latest.slice(0, 4)),
    parseInt(latest.slice(4, 6)) - 1,
    parseInt(latest.slice(6, 8))
  ) : new Date(0)
  const daysSinceUpdate = Math.floor((today.getTime() - latestDate.getTime()) / 86400000)
  const freshnessScore = Math.max(0, 100 - daysSinceUpdate * 20)

  return Math.round(avgFactor * 0.6 + freshnessScore * 0.4)
})

const healthStatus = computed(() => {
  const s = healthScore.value
  if (s >= 80) return { text: '健康', color: '#67c23a' }
  if (s >= 50) return { text: '部分可用', color: '#e6a23c' }
  return { text: '需补数据', color: '#f56c6c' }
})

// 5月问题诊断
const mayDiagnosis = computed(() => {
  if (!status.value?.daily_coverage) return []
  const issues: string[] = []
  const cov = status.value.daily_coverage
  const mayDays = cov.filter(c => c.date.startsWith('202605'))
  if (mayDays.length > 0 && mayDays[0].factor_rate === 0) {
    issues.push('5月因子完全缺失 — 需运行 factor_auto_compute 或等东方财富API解封后重跑')
  }
  const recentDays = cov.filter(c => c.groups.volume < 80 && c.groups.volume > 0)
  if (recentDays.length > 0) {
    issues.push(`量价因子覆盖率仅${recentDays[recentDays.length - 1].groups.volume}% — daily_basic的turnover_rate未合并到stock_daily_ak_full`)
  }
  if (cov.some(c => c.groups.limit === 0 && c.factor_rate > 0)) {
    issues.push('涨跌停因子始终0% — 需limit_list/limit_pool_down数据合并')
  }
  const downCount = status.value.collections?.limit_pool_down || 0
  if (downCount < 10) {
    issues.push(`跌停池仅${downCount}条 — 缺乏跌停数据影响跌停翘板策略`)
  }
  return issues
})

onMounted(fetchData)
</script>

<template>
  <div class="data-status-panel">
    <!-- 顶部概览 -->
    <div class="status-header">
      <div class="health-gauge">
        <ElProgress type="circle" :percentage="healthScore" :width="80" :stroke-width="8"
          :color="healthStatus.color">
          <template #default>
            <span :style="{ color: healthStatus.color, fontWeight: 700, fontSize: '16px' }">
              {{ healthScore }}
            </span>
          </template>
        </ElProgress>
        <div class="health-label" :style="{ color: healthStatus.color }">{{ healthStatus.text }}</div>
      </div>

      <div class="summary-cards">
        <div class="s-card">
          <div class="s-label">日线最新</div>
          <div class="s-value">{{ status?.latest?.stock_daily || '--' }}</div>
        </div>
        <div class="s-card">
          <div class="s-label">基础指标最新</div>
          <div class="s-value">{{ status?.latest?.daily_basic || '--' }}</div>
        </div>
        <div class="s-card">
          <div class="s-label">日线总记录</div>
          <div class="s-value">{{ (status?.collections?.stock_daily_ak_full || 0).toLocaleString() }}</div>
        </div>
        <div class="s-card">
          <div class="s-label">交易日天数</div>
          <div class="s-value">{{ status?.daily_coverage?.length || 0 }}</div>
        </div>
      </div>
    </div>

    <!-- 问题诊断 -->
    <div v-if="mayDiagnosis.length" class="diagnosis-box">
      <div class="diag-title">⚠️ 数据问题</div>
      <div v-for="(issue, i) in mayDiagnosis" :key="i" class="diag-item">{{ issue }}</div>
    </div>

    <!-- 因子覆盖率热力图 -->
    <ElCard style="margin-top: 12px">
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>🌡️ 因子覆盖率热力图</span>
          <ElButton size="small" @click="fetchData" :loading="loading">🔄 刷新</ElButton>
        </div>
      </template>
      <VChart v-if="heatmapOption" :option="heatmapOption" autoresize style="height: 500px; width: 100%" />
      <ElEmpty v-else description="暂无数据" />
    </ElCard>

    <!-- 每日股票数+覆盖率趋势 -->
    <ElCard style="margin-top: 12px">
      <template #header><span>📊 数据量趋势</span></template>
      <VChart v-if="stockCountOption" :option="stockCountOption" autoresize style="height: 280px; width: 100%" />
      <ElEmpty v-else description="暂无数据" />
    </ElCard>

    <!-- 集合大小 -->
    <ElCard style="margin-top: 12px">
      <template #header><span>🗄️ 数据集概览</span></template>
      <ElTable :data="collectionRows" size="small" border stripe>
        <ElTableColumn prop="name" label="名称" width="180" />
        <ElTableColumn prop="key" label="集合" width="200" />
        <ElTableColumn label="记录数" width="120">
          <template #default="{ row }">{{ row.count.toLocaleString() }}</template>
        </ElTableColumn>
        <ElTableColumn label="状态" min-width="100">
          <template #default="{ row }">
            <ElTag v-if="row.key === 'stock_daily_ak_full' && row.count > 400000" type="success" size="small">完整</ElTag>
            <ElTag v-else-if="row.key === 'limit_pool_down' && row.count < 10" type="danger" size="small">缺失</ElTag>
            <ElTag v-else-if="row.count > 0" type="success" size="small">有数据</ElTag>
            <ElTag v-else type="info" size="small">空</ElTag>
          </template>
        </ElTableColumn>
      </ElTable>
    </ElCard>
  </div>
</template>

<style scoped lang="scss">
.data-status-panel { padding: 0; }
.status-header {
  display: flex;
  gap: 20px;
  align-items: center;
  padding: 16px;
  background: var(--el-fill-color-lighter);
  border-radius: 8px;
}
.health-gauge {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}
.health-label { font-size: 13px; font-weight: 600; }
.summary-cards {
  display: flex;
  gap: 16px;
  flex: 1;
  flex-wrap: wrap;
}
.s-card {
  display: flex;
  flex-direction: column;
  min-width: 100px;
  padding: 8px 16px;
  border-radius: 6px;
  background: #fff;
}
.s-label { font-size: 11px; color: var(--el-text-color-secondary); }
.s-value { font-size: 18px; font-weight: 700; color: var(--el-text-color-primary); margin-top: 2px; }
.diagnosis-box {
  margin-top: 12px;
  padding: 12px 16px;
  background: #fef0f0;
  border-radius: 6px;
  border-left: 4px solid #f56c6c;
}
.diag-title { font-weight: 600; font-size: 14px; margin-bottom: 6px; }
.diag-item { font-size: 13px; color: #606266; margin-bottom: 4px; padding-left: 8px; }
</style>
