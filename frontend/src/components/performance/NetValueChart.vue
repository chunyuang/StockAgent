<script setup lang="ts">
/**
 * NetValueChart - 净值曲线图组件
 * 使用 ECharts 展示策略净值曲线、基准对比、回撤区域
 */
import { ref, computed, watch, onMounted } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, MarkLineComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import { systemApi } from '@/api'
import type { PerformanceReport } from '@/api'

use([CanvasRenderer, LineChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, MarkLineComponent])

const props = defineProps<{
  reports: PerformanceReport[]
  accountId?: string
}>()

/** 从API加载的净值历史数据 */
const apiDates = ref<string[]>([])
const apiValues = ref<number[]>([])
const apiDrawdowns = ref<number[]>([])
const apiLoaded = ref(false)

/** 从后端API加载净值历史 */
async function loadNetValueHistory() {
  if (!props.accountId) return
  try {
    const res = await systemApi.getNetValueHistory(props.accountId, 90)
    if (res?.success && res?.data?.dates?.length) {
      apiDates.value = res.data.dates
      apiValues.value = res.data.values
      apiDrawdowns.value = res.data.drawdowns || []
      apiLoaded.value = true
    }
  } catch { /* fallback to computed */ }
}

onMounted(() => { loadNetValueHistory() })
watch(() => props.accountId, () => { apiLoaded.value = false; loadNetValueHistory() })

/** 从报告数据推算净值曲线（API不可用时的回退方案） */
const computedData = computed(() => {
  if (!props.reports.length) return { dates: [], values: [], drawdowns: [] }

  // 按日期排序
  const sorted = [...props.reports].sort((a, b) =>
    new Date(a.start_date).getTime() - new Date(b.start_date).getTime()
  )

  const dates: string[] = []
  const values: number[] = []
  const drawdowns: number[] = []
  let cumValue = 1.0
  let maxVal = 1.0

  for (const r of sorted) {
    const label = r.end_date || r.start_date
    cumValue *= (1 + (r.total_return_pct || 0))
    maxVal = Math.max(maxVal, cumValue)
    const dd = (cumValue - maxVal) / maxVal

    dates.push(label)
    values.push(parseFloat(cumValue.toFixed(4)))
    drawdowns.push(parseFloat(dd.toFixed(4)))
  }

  return { dates, values, drawdowns }
})

/** 最终使用的净值数据：优先API，回退到计算值 */
const netValueData = computed(() => {
  if (apiLoaded.value && apiDates.value.length > 0) {
    return { dates: apiDates.value, values: apiValues.value, drawdowns: apiDrawdowns.value }
  }
  return computedData.value
})

const chartOption = computed(() => {
  const { dates, values, drawdowns } = netValueData.value
  if (!dates.length) return {}

  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        let html = `<b>${params[0].axisValue}</b><br/>`
        for (const p of params) {
          html += `${p.marker} ${p.seriesName}: ${p.value.toFixed(4)}<br/>`
        }
        return html
      },
    },
    legend: {
      data: ['策略净值', '回撤'],
      top: 0,
    },
    grid: [
      { left: 60, right: 30, top: 40, height: '55%' },
      { left: 60, right: 30, top: '72%', height: '20%' },
    ],
    xAxis: [
      { type: 'category', data: dates, gridIndex: 0, axisLabel: { fontSize: 11 } },
      { type: 'category', data: dates, gridIndex: 1, axisLabel: { show: false } },
    ],
    yAxis: [
      { type: 'value', gridIndex: 0, scale: true, axisLabel: { fontSize: 11 } },
      { type: 'value', gridIndex: 1, scale: true, axisLabel: { fontSize: 11, formatter: '{value}%' } },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: 0, end: 100 },
      { type: 'slider', xAxisIndex: [0, 1], bottom: 4, height: 16 },
    ],
    series: [
      {
        name: '策略净值',
        type: 'line',
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: values,
        smooth: true,
        lineStyle: { width: 2, color: '#409eff' },
        areaStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(64,158,255,0.25)' },
              { offset: 1, color: 'rgba(64,158,255,0.02)' },
            ],
          },
        },
        markLine: {
          silent: true,
          data: [{ yAxis: 1.0, lineStyle: { color: '#909399', type: 'dashed' } }],
          label: { formatter: '基准线 1.0' },
        },
      },
      {
        name: '回撤',
        type: 'line',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: drawdowns.map(d => parseFloat((d * 100).toFixed(2))),
        smooth: true,
        lineStyle: { width: 1.5, color: '#f56c6c' },
        areaStyle: { color: 'rgba(245,108,108,0.2)' },
        itemStyle: { color: '#f56c6c' },
      },
    ],
  }
})
</script>

<template>
  <div class="net-value-chart">
    <div class="chart-title">📈 净值曲线 & 回撤</div>
    <VChart :option="chartOption" autoresize style="height: 420px; width: 100%" />
    <div v-if="!reports.length" class="empty-chart">暂无数据</div>
  </div>
</template>

<script lang="ts">
export default { name: 'NetValueChart' }
</script>

<style scoped>
.net-value-chart {
  background: var(--el-bg-color);
  border-radius: 8px;
  padding: 16px 20px;
}
.chart-title {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 10px;
}
.empty-chart {
  text-align: center;
  padding: 60px 0;
  color: var(--el-text-color-placeholder);
}
</style>
