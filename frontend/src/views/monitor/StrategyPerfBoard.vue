<script setup lang="ts">
/**
 * 策略实时绩效看板
 * P0-2: 按策略维度展示今日收益、累计收益、胜率、盈亏比、sparkline
 */
import { ref, onMounted, onUnmounted } from 'vue'
import { api } from '@/api/client'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { PieChart, GaugeChart, BarChart, LineChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, LegendComponent, GridComponent } from 'echarts/components'
import VChart from 'vue-echarts'

use([CanvasRenderer, PieChart, GaugeChart, BarChart, LineChart, TitleComponent, TooltipComponent, LegendComponent, GridComponent])

interface StrategyPerf {
  key: string
  name: string
  today_profit: number
  total_profit: number
  win_count: number
  loss_count: number
  win_rate: number
  profit_loss_ratio: number
  position_count: number
  closed_count: number
  max_win_pct: number
  max_loss_pct: number
  avg_profit_pct: number
  sparkline: number[]
}

const data = ref<StrategyPerf[]>([])
const loading = ref(false)
const strategyColors: Record<string, string> = {
  halfway_chase: '#409eff',
  first_limit_up: '#e6a23c',
  dragon_head: '#f56c6c',
  limit_down_qiao: '#67c23a',
  limit_up_open: '#909399',
  manual: '#b37feb',
  total: '#303133',
}

async function fetchData() {
  loading.value = true
  try {
    const r: any = await api.get('/scanner/strategy-performance')
    if (r?.success) data.value = r.data || []
  } catch { } finally { loading.value = false }
}

function sparklineOption(vals: number[], color: string) {
  if (!vals?.length) return {}
  return {
    grid: { left: 0, right: 0, top: 2, bottom: 2 },
    xAxis: { type: 'category', show: false, data: vals.map((_, i) => i) },
    yAxis: { type: 'value', show: false, min: (v: { min: number; max: number }) => v.min - (v.max - v.min) * 0.1 },
    series: [{
      type: 'line', data: vals, smooth: true, symbol: 'none', lineStyle: { width: 1.5, color },
      areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: color + '40' }, { offset: 1, color: color + '05' }] } },
    }],
    animation: false,
  }
}

let timer: number
onMounted(() => { fetchData(); timer = window.setInterval(fetchData, 15000) })
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div class="strategy-perf">
    <div class="sp-header">
      <span class="sp-title">📊 策略绩效</span>
      <span class="sp-refresh cp" @click="fetchData">🔄</span>
    </div>
    <div v-if="loading" class="sp-loading">加载中...</div>
    <div v-else-if="!data.length" class="sp-empty">暂无数据</div>
    <table v-else class="sp-table">
      <thead>
        <tr>
          <th>策略</th>
          <th>今日</th>
          <th>累计</th>
          <th>胜率</th>
          <th>盈亏比</th>
          <th>持仓</th>
          <th>平仓</th>
          <th style="width:80px">趋势</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="s in data" :key="s.key" :class="{ 'sp-total': s.key === 'total' }">
          <td>
            <span class="sp-dot" :style="{ background: strategyColors[s.key] || '#909399' }"></span>
            {{ s.name }}
          </td>
          <td :class="s.today_profit >= 0 ? 'up' : 'down'">
            {{ s.today_profit >= 0 ? '+' : '' }}{{ ((s.today_profit || 0) / 10000).toFixed(2) }}万
          </td>
          <td :class="s.total_profit >= 0 ? 'up' : 'down'">
            {{ s.total_profit >= 0 ? '+' : '' }}{{ ((s.total_profit || 0) / 10000).toFixed(1) }}万
          </td>
          <td>
            <span class="sp-wr" :class="s.win_rate >= 70 ? 'good' : s.win_rate >= 50 ? 'mid' : 'bad'">
              {{ s.win_rate }}%
            </span>
          </td>
          <td>{{ s.profit_loss_ratio }}</td>
          <td>{{ s.position_count }}</td>
          <td>{{ s.closed_count }}</td>
          <td>
            <VChart v-if="s.sparkline?.length" :option="sparklineOption(s.sparkline, strategyColors[s.key] || '#409eff')" autoresize style="height:28px;width:80px" />
            <span v-else class="sp-nochart">-</span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.strategy-perf { background: var(--el-bg-color); border-radius: 8px; padding: 12px; }
.sp-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.sp-title { font-weight: 600; font-size: 13px; }
.sp-refresh { font-size: 12px; }
.sp-loading, .sp-empty { text-align: center; padding: 16px; color: var(--el-text-color-secondary); font-size: 12px; }
.sp-table { width: 100%; border-collapse: collapse; font-size: 11px; }
.sp-table th { text-align: left; padding: 4px 6px; color: var(--el-text-color-secondary); font-weight: 500; border-bottom: 1px solid var(--el-border-color-lighter); white-space: nowrap; }
.sp-table td { padding: 5px 6px; border-bottom: 1px solid var(--el-border-color-extra-light); white-space: nowrap; }
.sp-total { font-weight: 600; background: var(--el-fill-color-lighter); }
.sp-total td { border-top: 2px solid var(--el-border-color); }
.sp-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; vertical-align: middle; }
.up { color: var(--el-color-danger); }
.down { color: var(--el-color-success); }
.sp-wr { padding: 1px 4px; border-radius: 3px; font-size: 10px; }
.sp-wr.good { background: #f56c6c20; color: #f56c6c; }
.sp-wr.mid { background: #e6a23c20; color: #e6a23c; }
.sp-wr.bad { background: #90939920; color: #909399; }
.sp-nochart { color: var(--el-text-color-placeholder); }
</style>
