<script setup lang="ts">
/**
 * 迷你K线图组件
 * P0-1: 嵌入持仓/信号卡片的5日K线缩略图 + 大图弹窗
 */
import { ref, computed, watch, onMounted } from 'vue'
import { api } from '@/api/client'
import VChart from 'vue-echarts'

const props = defineProps<{
  tsCode: string
  days?: number
  compact?: boolean  // true = 迷你模式(无坐标轴)
}>()

interface KlineBar { date: string; open: number; high: number; low: number; close: number; volume: number; pct_chg: number; ma5?: number; ma10?: number; ma20?: number }
interface Annotation { date: string; action: string; price: number; strategy: string }

const kline = ref<KlineBar[]>([])
const annotations = ref<Annotation[]>([])
const showDetail = ref(false)
const loading = ref(false)

async function fetchKline() {
  if (!props.tsCode) return
  loading.value = true
  try {
    const r = await api.get(`/scanner/kline/${props.tsCode}?days=${props.days || 30}`)
    if (r?.success) {
      kline.value = r.data?.kline || []
      annotations.value = r.data?.annotations || []
    }
  } catch { } finally { loading.value = false }
}

const miniOption = computed(() => {
  if (!kline.value.length) return {}
  const data = kline.value.slice(-5)
  return {
    grid: { left: 2, right: 2, top: 4, bottom: 2 },
    xAxis: { type: 'category', show: false, data: data.map(d => d.date) },
    yAxis: { type: 'value', show: false },
    series: [{
      type: 'candlestick',
      data: data.map(d => [d.open, d.close, d.low, d.high]),
      itemStyle: { color: '#f56c6c', color0: '#67c23a', borderColor: '#f56c6c', borderColor0: '#67c23a' },
    }],
    animation: false,
  }
})

const fullOption = computed(() => {
  if (!kline.value.length) return {}
  const dates = kline.value.map(d => d.date.slice(-4))  // MM-DD
  const ohlc = kline.value.map(d => [d.open, d.close, d.low, d.high])
  const volumes = kline.value.map(d => d.volume)
  const ma5 = kline.value.map(d => d.ma5 ?? null)
  const ma10 = kline.value.map(d => d.ma10 ?? null)
  const ma20 = kline.value.map(d => d.ma20 ?? null)

  // 买卖标注
  const buyMarks: any[] = []
  const sellMarks: any[] = []
  annotations.value.forEach(a => {
    const idx = kline.value.findIndex(k => k.date === a.date)
    if (idx >= 0) {
      if (a.action === 'buy') buyMarks.push({ coord: [idx, kline.value[idx].low], value: '买', itemStyle: { color: '#f56c6c' } })
      if (a.action === 'sell') sellMarks.push({ coord: [idx, kline.value[idx].high], value: '卖', symbol: 'triangle', symbolRotate: 180, itemStyle: { color: '#67c23a' } })
    }
  })

  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    legend: { data: ['K线', 'MA5', 'MA10', 'MA20'], top: 0, textStyle: { fontSize: 10 } },
    grid: [
      { left: 50, right: 20, top: 30, height: '55%' },
      { left: 50, right: 20, top: '72%', height: '20%' },
    ],
    xAxis: [
      { type: 'category', data: dates, gridIndex: 0, axisLabel: { fontSize: 9 } },
      { type: 'category', data: dates, gridIndex: 1, axisLabel: { show: false } },
    ],
    yAxis: [
      { type: 'value', gridIndex: 0, scale: true, splitLine: { lineStyle: { type: 'dashed' } } },
      { type: 'value', gridIndex: 1, scale: true, splitNumber: 2 },
    ],
    series: [
      {
        name: 'K线', type: 'candlestick', data: ohlc, xAxisIndex: 0, yAxisIndex: 0,
        itemStyle: { color: '#f56c6c', color0: '#67c23a', borderColor: '#f56c6c', borderColor0: '#67c23a' },
        markPoint: { data: [...buyMarks, ...sellMarks], symbolSize: 20, label: { fontSize: 9 } },
      },
      { name: 'MA5', type: 'line', data: ma5, smooth: true, symbol: 'none', lineStyle: { width: 1 }, xAxisIndex: 0, yAxisIndex: 0 },
      { name: 'MA10', type: 'line', data: ma10, smooth: true, symbol: 'none', lineStyle: { width: 1 }, xAxisIndex: 0, yAxisIndex: 0 },
      { name: 'MA20', type: 'line', data: ma20, smooth: true, symbol: 'none', lineStyle: { width: 1 }, xAxisIndex: 0, yAxisIndex: 0 },
      {
        name: '成交量', type: 'bar', data: volumes, xAxisIndex: 1, yAxisIndex: 1,
        itemStyle: { color: (p: any) => { const idx = p.dataIndex; return kline.value[idx]?.close >= kline.value[idx]?.open ? '#f56c6c80' : '#67c23a80' } },
      },
    ],
  }
})

onMounted(fetchKline)
watch(() => props.tsCode, fetchKline)
</script>

<template>
  <div class="mini-kline" @click="showDetail = true">
    <VChart v-if="compact && kline.length" :option="miniOption" autoresize style="height:28px;width:48px" />
    <span v-else-if="loading" class="mk-loading">⏳</span>
    <span v-else class="mk-placeholder">📊</span>
  </div>

  <!-- 大图弹窗 -->
  <el-dialog v-model="showDetail" :title="`📈 K线 — ${tsCode}`" width="700px" :close-on-click-modal="true">
    <VChart v-if="kline.length" :option="fullOption" autoresize style="height:400px;width:100%" />
    <div v-else class="mk-nodata">暂无K线数据</div>
  </el-dialog>
</template>

<style scoped>
.mini-kline { display: inline-block; vertical-align: middle; cursor: pointer; }
.mk-loading, .mk-placeholder { font-size: 12px; }
.mk-nodata { text-align: center; padding: 40px; color: var(--el-text-color-secondary); }
</style>
