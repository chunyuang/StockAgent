<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElCard, ElEmpty, ElProgress, ElTable, ElTableColumn, ElTag, ElButton, ElTooltip, ElDescriptions, ElDescriptionsItem } from 'element-plus'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, BarChart, HeatmapChart } from 'echarts/charts'
import {
  TitleComponent, TooltipComponent, LegendComponent, GridComponent,
  VisualMapComponent, DataZoomComponent
} from 'echarts/components'

use([CanvasRenderer, LineChart, BarChart, HeatmapChart, TitleComponent, TooltipComponent, LegendComponent, GridComponent, VisualMapComponent, DataZoomComponent])

interface DailyCoverage {
  date: string
  total: number
  factor_rate: number
  groups: Record<string, number>
}

interface CollectionInfo {
  count: number
  date_range: { start: string; end: string } | null
  error?: string
}

interface DataSource {
  name: string
  type: string
  status: string
  status_text: string
  rate_limit: string
  coverage: string
  gotchas: string[]
  scripts: string[]
}

interface RecommendedRange {
  start: string
  end: string
  factor_rate: string
}

interface DataStatus {
  health_score: number
  diagnostics: { level: string; message: string }[]
  collections: Record<string, CollectionInfo>
  daily_coverage: DailyCoverage[]
  latest: { stock_daily: string | null; daily_basic: string | null }
  factor_groups: Record<string, number>
  recommended_ranges: RecommendedRange[]
  data_sources: DataSource[]
}

const loading = ref(false)
const status = ref<DataStatus | null>(null)
const error = ref('')

const collectionNames: Record<string, string> = {
  stock_daily_ak_full: '日线行情(OHLCV)', daily_basic: '基础指标(PE/PB/市值)',
  index_daily: '指数日线', limit_list: '涨停池',
  limit_pool_down: '跌停池', backtest_tasks: '回测任务'
}

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

// 格式化日期 20260106 → 2026-01-06
function fmtDate(d: string) {
  if (!d || d.length !== 8) return d
  return `${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6,8)}`
}

// 覆盖率热力图
const heatmapOption = computed(() => {
  if (!status.value?.daily_coverage?.length) return null
  const cov = status.value.daily_coverage
  const groups = ['basic', 'technical', 'volume', 'limit']
  const groupLabels: Record<string, string> = {
    basic: '基础', technical: '技术指标', volume: '量价', limit: '涨跌停'
  }
  const data: number[][] = []
  const yLabels = cov.map(c => `${c.date.slice(4,6)}/${c.date.slice(6,8)}`)

  cov.forEach((c, yi) => {
    groups.forEach((g, xi) => {
      data.push([xi, yi, c.groups[g] || 0])
    })
  })

  // 当日期较多时启用Y轴滚动
  const needZoom = yLabels.length > 15
  const dataZoomY = needZoom ? [{
    type: 'slider', yAxisIndex: 0,
    startValue: Math.max(0, yLabels.length - 30),
    endValue: yLabels.length - 1,
    right: 0, width: 16, top: 10, bottom: 30,
    borderColor: '#ddd', fillerColor: 'rgba(64,158,255,0.15)',
    handleStyle: { color: '#409eff' },
    labelFormatter: (v: number) => yLabels[v] || ''
  }] : []

  return {
    tooltip: {
      formatter: (p: any) => {
        const c = cov[p.data[1]]
        const g = groups[p.data[0]]
        return `${c.date} ${groupLabels[g]}<br/>覆盖率: ${p.data[2]}%<br/>股票数: ${c.total}`
      }
    },
    grid: { left: 60, right: needZoom ? 36 : 30, top: 10, bottom: 30 },
    dataZoom: dataZoomY,
    xAxis: { type: 'category', data: groups.map(g => groupLabels[g]), splitArea: { show: true }, axisLabel: { fontSize: 11 } },
    yAxis: { type: 'category', data: yLabels, axisLabel: { fontSize: 10 } },
    visualMap: {
      min: 0, max: 100,
      inRange: { color: ['#f56c6c', '#e6a23c', '#f5da55', '#95d475', '#67c23a'] },
      orient: 'horizontal', left: 'center', bottom: 0,
      itemWidth: 12, itemHeight: 100, text: ['100%', '0%'], textStyle: { fontSize: 10 }
    },
    series: [{
      type: 'heatmap', data,
      label: { show: true, formatter: (p: any) => p.data[2] > 0 ? `${p.data[2]}` : '', fontSize: 9, color: '#333' },
      itemStyle: { borderWidth: 1, borderColor: '#fff' }
    }]
  }
})

// 数据量趋势
const stockCountOption = computed(() => {
  if (!status.value?.daily_coverage?.length) return null
  const cov = status.value.daily_coverage
  // 计算合理的初始显示范围（最近60个交易日）
  const totalDays = cov.length
  const showDays = Math.min(totalDays, 60)
  const startPercent = ((totalDays - showDays) / totalDays) * 100

  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 50, right: 20, top: 20, bottom: 60 },
    dataZoom: [
      {
        type: 'slider', xAxisIndex: 0,
        start: startPercent, end: 100,
        height: 20, bottom: 8,
        borderColor: '#ddd', fillerColor: 'rgba(64,158,255,0.15)',
        handleStyle: { color: '#409eff' },
        labelFormatter: (v: number) => {
          const idx = Math.round(v / 100 * (cov.length - 1))
          return cov[idx] ? `${cov[idx].date.slice(4,6)}/${cov[idx].date.slice(6,8)}` : ''
        }
      },
      { type: 'inside', xAxisIndex: 0 }
    ],
    xAxis: { type: 'category', data: cov.map(c => `${c.date.slice(4,6)}/${c.date.slice(6,8)}`), axisLabel: { fontSize: 10, rotate: 30 } },
    yAxis: [
      { type: 'value', name: '股票数', min: 0, axisLabel: { fontSize: 10 } },
      { type: 'value', name: '覆盖率%', min: 0, max: 100, axisLabel: { fontSize: 10 } }
    ],
    series: [
      { name: '股票数', type: 'bar', data: cov.map(c => c.total), itemStyle: { color: '#409eff' }, barMaxWidth: 20 },
      { name: '因子覆盖率', type: 'line', yAxisIndex: 1, data: cov.map(c => c.factor_rate), itemStyle: { color: '#67c23a' }, lineStyle: { width: 2 }, areaStyle: { color: 'rgba(103,194,58,0.1)' } }
    ]
  }
})

// 集合信息行
const collectionRows = computed(() => {
  if (!status.value?.collections) return []
  return Object.entries(status.value.collections).map(([k, v]) => ({
    key: k,
    name: collectionNames[k] || k,
    count: v.count,
    dateStart: v.date_range?.start,
    dateEnd: v.date_range?.end,
    hasDate: v.date_range?.start && v.date_range.start.length === 8,
  }))
})

// 健康评分(用后端返回的值)
const healthScore = computed(() => {
  return status.value?.health_score || 0
})

const healthStatus = computed(() => {
  const s = healthScore.value
  if (s >= 80) return { text: '健康', color: '#67c23a' }
  if (s >= 50) return { text: '部分可用', color: '#e6a23c' }
  return { text: '需补数据', color: '#f56c6c' }
})

// 问题诊断(用后端返回的)
const diagnosis = computed(() => {
  if (!status.value?.diagnostics) return []
  return status.value.diagnostics.map(d => ({
    level: d.level,
    text: d.message
  }))
})

// 数据源状态样式
function srcStatusColor(s: string) {
  return { ok: '#67c23a', limited: '#e6a23c', degraded: '#e6a23c', blocked: '#f56c6c', disabled: '#909399' }[s] || '#909399'
}
function srcStatusText(s: string) {
  return { ok: '✅可用', limited: '⚠️受限', degraded: '⚠️降级', blocked: '❌被封', disabled: '🚫停用' }[s] || s
}

onMounted(fetchData)
</script>

<template>
  <div class="data-status-panel">
    <!-- 顶部概览 -->
    <div class="status-header">
      <div class="health-gauge">
        <ElProgress type="circle" :percentage="healthScore" :width="80" :stroke-width="8" :color="healthStatus.color">
          <template #default>
            <span :style="{ color: healthStatus.color, fontWeight: 700, fontSize: '16px' }">{{ healthScore }}</span>
          </template>
        </ElProgress>
        <div class="health-label" :style="{ color: healthStatus.color }">{{ healthStatus.text }}</div>
      </div>
      <div class="summary-cards">
        <div class="s-card">
          <div class="s-label">日线最新</div>
          <div class="s-value">{{ fmtDate(status?.latest?.stock_daily || '') }}</div>
        </div>
        <div class="s-card">
          <div class="s-label">基础指标最新</div>
          <div class="s-value">{{ fmtDate(status?.latest?.daily_basic || '') }}</div>
        </div>
        <div class="s-card">
          <div class="s-label">日线总记录</div>
          <div class="s-value">{{ (status?.collections?.stock_daily_ak_full?.count || 0).toLocaleString() }}</div>
        </div>
        <div class="s-card">
          <div class="s-label">交易日天数</div>
          <div class="s-value">{{ status?.daily_coverage?.length || 0 }}</div>
        </div>
      </div>
    </div>

    <!-- 问题诊断 -->
    <div v-if="diagnosis.length" class="diagnosis-box">
      <div class="diag-title">⚠️ 数据问题</div>
      <div v-for="(issue, i) in diagnosis" :key="i" class="diag-item" :class="'diag-' + issue.level">
        {{ issue.level === 'red' ? '🔴' : issue.level === 'yellow' ? '🟡' : '🔴' }} {{ issue.text }}
      </div>
    </div>

    <!-- 推荐回测区间 -->
    <ElCard v-if="status?.recommended_ranges?.length" style="margin-top: 12px">
      <template #header><span>🎯 推荐回测区间</span></template>
      <div class="recommended-ranges">
        <div v-for="(r, i) in status.recommended_ranges" :key="i" class="range-card">
          <div class="range-dates">{{ fmtDate(r.start) }} ~ {{ fmtDate(r.end) }}</div>
          <ElTag type="success" size="small">因子{{ r.factor_rate }}</ElTag>
        </div>
      </div>
    </ElCard>
    <ElCard v-else style="margin-top: 12px">
      <template #header><span>🎯 推荐回测区间</span></template>
      <div style="color: #e6a23c; font-size: 13px">
        当前无因子覆盖率≥70%的连续区间，请检查数据补全情况。
      </div>
    </ElCard>

    <!-- 数据集概览(含日期区间) -->
    <ElCard style="margin-top: 12px">
      <template #header><span>🗄️ 数据集概览</span></template>
      <ElTable :data="collectionRows" size="small" border stripe>
        <ElTableColumn prop="name" label="名称" width="180" />
        <ElTableColumn prop="key" label="集合" width="200" />
        <ElTableColumn label="记录数" width="100">
          <template #default="{ row }">{{ row.count.toLocaleString() }}</template>
        </ElTableColumn>
        <ElTableColumn label="日期区间" min-width="220">
          <template #default="{ row }">
            <span v-if="row.hasDate" style="font-family: monospace; font-size: 13px">
              {{ fmtDate(row.dateStart) }} ~ {{ fmtDate(row.dateEnd) }}
            </span>
            <span v-else style="color: #909399">-</span>
          </template>
        </ElTableColumn>
        <ElTableColumn label="状态" width="80">
          <template #default="{ row }">
            <ElTag v-if="row.key === 'stock_daily_ak_full' && row.count > 400000" type="success" size="small">完整</ElTag>
            <ElTag v-else-if="row.key === 'daily_basic' && row.count > 2000000" type="success" size="small">完整</ElTag>
            <ElTag v-else-if="row.key === 'index_daily' && row.count > 1000" type="success" size="small">完整</ElTag>
            <ElTag v-else-if="row.key === 'limit_list' && row.count > 0" type="success" size="small">有数据</ElTag>
            <ElTag v-else-if="row.key === 'limit_pool_down' && row.count < 10" type="danger" size="small">缺失</ElTag>
            <ElTag v-else-if="row.count > 0" type="success" size="small">有数据</ElTag>
            <ElTag v-else type="info" size="small">空</ElTag>
          </template>
        </ElTableColumn>
      </ElTable>
    </ElCard>

    <!-- 数据源卡片 -->
    <ElCard style="margin-top: 12px">
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>📡 数据源状态</span>
          <ElButton size="small" @click="fetchData" :loading="loading">🔄 刷新</ElButton>
        </div>
      </template>
      <div class="source-grid">
        <div v-for="src in status?.data_sources || []" :key="src.name" class="source-card" :class="'src-' + src.status">
          <div class="src-header">
            <span class="src-name">{{ src.name }}</span>
            <span class="src-status" :style="{ color: srcStatusColor(src.status) }">{{ srcStatusText(src.status) }}</span>
          </div>
          <div class="src-type">{{ src.type }}</div>
          <div class="src-detail" v-if="src.status_text">{{ src.status_text }}</div>
          <div class="src-detail"><b>限制:</b> {{ src.rate_limit }}</div>
          <div class="src-detail"><b>覆盖:</b> {{ src.coverage }}</div>
          <div class="src-gotchas" v-if="src.gotchas?.length">
            <div class="src-gotchas-title">⚠️ 注意:</div>
            <div v-for="(g, i) in src.gotchas" :key="i" class="src-gotcha">• {{ g }}</div>
          </div>
          <div class="src-scripts" v-if="src.scripts?.length">
            <span class="src-scripts-label">脚本:</span>
            <code v-for="s in src.scripts" :key="s" class="src-script">{{ s }}</code>
          </div>
        </div>
      </div>
    </ElCard>

    <!-- 因子覆盖率热力图 -->
    <ElCard style="margin-top: 12px">
      <template #header><span>🌡️ 因子覆盖率热力图</span></template>
      <VChart v-if="heatmapOption" :option="heatmapOption" autoresize style="height: 500px; width: 100%" />
      <ElEmpty v-else description="暂无数据" />
    </ElCard>

    <!-- 数据量趋势 -->
    <ElCard style="margin-top: 12px">
      <template #header><span>📊 数据量趋势</span></template>
      <VChart v-if="stockCountOption" :option="stockCountOption" autoresize style="height: 280px; width: 100%" />
      <ElEmpty v-else description="暂无数据" />
    </ElCard>
  </div>
</template>

<style scoped lang="scss">
.data-status-panel { padding: 0; }
.status-header {
  display: flex; gap: 20px; align-items: center;
  padding: 16px; background: var(--el-fill-color-lighter); border-radius: 8px;
}
.health-gauge { display: flex; flex-direction: column; align-items: center; gap: 4px; }
.health-label { font-size: 13px; font-weight: 600; }
.summary-cards { display: flex; gap: 16px; flex: 1; flex-wrap: wrap; }
.s-card { display: flex; flex-direction: column; min-width: 100px; padding: 8px 16px; border-radius: 6px; background: #fff; }
.s-label { font-size: 11px; color: var(--el-text-color-secondary); }
.s-value { font-size: 18px; font-weight: 700; color: var(--el-text-color-primary); margin-top: 2px; }

.diagnosis-box {
  margin-top: 12px; padding: 12px 16px; background: #fef0f0;
  border-radius: 6px; border-left: 4px solid #f56c6c;
}
.diag-title { font-weight: 600; font-size: 14px; margin-bottom: 6px; }
.diag-item { font-size: 13px; color: #606266; margin-bottom: 4px; padding-left: 8px; }
.diag-warn { color: #8a6d3b; }

.recommended-ranges { display: flex; gap: 12px; flex-wrap: wrap; }
.range-card {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 18px; border-radius: 6px; background: #f0f9eb; border: 1px solid #e1f3d8;
}
.range-dates { font-size: 15px; font-weight: 600; font-family: monospace; }

.source-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 12px; }
.source-card {
  padding: 12px 14px; border-radius: 8px; border: 1px solid #ebeef5;
  background: #fafafa; transition: border-color 0.2s;
  &.src-blocked { border-color: #f56c6c; background: #fff5f5; }
  &.src-disabled { border-color: #dcdfe6; opacity: 0.6; }
  &.src-ok { border-color: #b3e19d; }
  &.src-limited, &.src-degraded { border-color: #e6a23c; background: #fdf6ec; }
}
.src-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.src-name { font-weight: 700; font-size: 14px; }
.src-status { font-size: 12px; font-weight: 600; }
.src-type { font-size: 12px; color: #909399; margin-bottom: 6px; }
.src-detail { font-size: 12px; color: #606266; margin-bottom: 3px; line-height: 1.5; }
.src-gotchas { margin-top: 6px; padding-top: 6px; border-top: 1px dashed #e4e7ed; }
.src-gotchas-title { font-size: 12px; font-weight: 600; color: #e6a23c; margin-bottom: 2px; }
.src-gotcha { font-size: 11px; color: #8a6d3b; line-height: 1.6; }
.src-scripts { margin-top: 6px; }
.src-scripts-label { font-size: 11px; color: #909399; }
.src-script { font-size: 11px; background: #f4f4f5; padding: 1px 5px; border-radius: 3px; margin-right: 4px; }
</style>
