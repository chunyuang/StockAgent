<script setup lang="ts">
/**
 * MonthlyReturnChart - 月度收益柱状图组件
 * 使用 ECharts 展示每月收益率的正负柱状图
 */
import { computed } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import type { PerformanceReport } from '@/api'

use([CanvasRenderer, BarChart, GridComponent, TooltipComponent, LegendComponent])

const props = defineProps<{
  reports: PerformanceReport[]
}>()

const chartOption = computed(() => {
  if (!props.reports.length) return {}

  const sorted = [...props.reports].sort((a, b) =>
    new Date(a.start_date).getTime() - new Date(b.start_date).getTime()
  )

  const months = sorted.map(r => {
    const d = r.end_date || r.start_date
    return d.substring(0, 7) // YYYY-MM
  })
  const returns = sorted.map(r => parseFloat(((r.total_return_pct || 0) * 100).toFixed(2)))

  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        const p = params[0]
        return `<b>${p.axisValue}</b><br/>${p.marker} 收益率: ${p.value > 0 ? '+' : ''}${p.value}%`
      },
    },
    grid: { left: 60, right: 30, top: 20, bottom: 40 },
    xAxis: {
      type: 'category',
      data: months,
      axisLabel: { fontSize: 11, rotate: 30 },
    },
    yAxis: {
      type: 'value',
      axisLabel: { fontSize: 11, formatter: '{value}%' },
    },
    series: [
      {
        name: '月度收益',
        type: 'bar',
        data: returns.map(v => ({
          value: v,
          itemStyle: { color: v >= 0 ? '#67c23a' : '#f56c6c', borderRadius: v >= 0 ? [3, 3, 0, 0] : [0, 0, 3, 3] },
        })),
        barMaxWidth: 40,
        label: {
          show: true,
          position: 'outside',
          fontSize: 10,
          formatter: (p: any) => (p.value > 0 ? '+' : '') + p.value + '%',
        },
      },
    ],
  }
})
</script>

<template>
  <div class="monthly-return-chart">
    <div class="chart-title">📊 月度收益率</div>
    <VChart :option="chartOption" autoresize style="height: 320px; width: 100%" />
    <div v-if="!reports.length" class="empty-chart">暂无数据</div>
  </div>
</template>

<script lang="ts">
export default { name: 'MonthlyReturnChart' }
</script>

<style scoped>
.monthly-return-chart {
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
