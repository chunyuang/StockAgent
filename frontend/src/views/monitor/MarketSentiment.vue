<script setup lang="ts">
/**
 * 市场情绪全景
 * P1-7: 情绪指数条+涨跌停+炸板率+连板分布+仓位系数
 */
import { ref, onMounted, onUnmounted } from 'vue'
import { api } from '@/api/client'
import VChart from 'vue-echarts'

interface SentimentData {
  score: number; period: string; period_label: string; position_ratio: number
  limit_up_count: number; limit_down_count: number; broken_count: number
  broken_rate: number; board_distribution: Record<string, number>
  ranges: { label: string; min: number; max: number; color: string }[]
}

const data = ref<SentimentData | null>(null)

async function fetchData() {
  try {
    const r: any = await api.get('/scanner/market-sentiment')
    if (r?.success) data.value = r.data
  } catch { }
}

// 连板分布柱状图
const boardOption = () => {
  if (!data.value?.board_distribution) return {}
  const entries = Object.entries(data.value.board_distribution).sort((a, b) => +a[0] - +b[0])
  return {
    grid: { left: 30, right: 10, top: 10, bottom: 20 },
    xAxis: { type: 'category', data: entries.map(e => e[0] + '板'), axisLabel: { fontSize: 9 } },
    yAxis: { type: 'value', axisLabel: { fontSize: 9 }, splitNumber: 3 },
    series: [{ type: 'bar', data: entries.map(e => e[1]), itemStyle: { color: '#f56c6c', borderRadius: [2, 2, 0, 0] }, barWidth: '60%' }],
    animation: false,
  }
}

let timer: number
onMounted(() => { fetchData(); timer = window.setInterval(fetchData, 15000) })
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div class="sentiment-pano">
    <div class="sp-header">
      <span class="sp-title">🧠 市场情绪</span>
      <span class="sp-refresh cp" @click="fetchData">🔄</span>
    </div>

    <div v-if="data" class="sp-content">
      <!-- 情绪条 -->
      <div class="sent-bar">
        <div v-for="r in data.ranges" :key="r.label" class="sent-seg" :style="{ flex: r.max - r.min, background: r.color + '30' }">
          <span class="sent-label">{{ r.label }}</span>
        </div>
        <div class="sent-pointer" :style="{ left: data.score + '%' }">
          <span class="sent-score">{{ data.score }}</span>
        </div>
      </div>

      <!-- 指标行 -->
      <div class="sent-metrics">
        <div class="sent-m">
          <span class="sent-ml">涨停</span>
          <span class="sent-mv up">{{ data.limit_up_count }}</span>
        </div>
        <div class="sent-m">
          <span class="sent-ml">跌停</span>
          <span class="sent-mv down">{{ data.limit_down_count }}</span>
        </div>
        <div class="sent-m">
          <span class="sent-ml">炸板率</span>
          <span class="sent-mv" :class="data.broken_rate > 30 ? 'warn' : ''">{{ data.broken_rate }}%</span>
        </div>
        <div class="sent-m">
          <span class="sent-ml">周期</span>
          <span class="sent-mv">{{ data.period_label }}</span>
        </div>
        <div class="sent-m">
          <span class="sent-ml">仓位系数</span>
          <span class="sent-mv">{{ (data.position_ratio * 100).toFixed(0) }}%</span>
        </div>
      </div>

      <!-- 连板分布 -->
      <div v-if="Object.keys(data.board_distribution || {}).length" class="sent-boards">
        <VChart :option="boardOption()" autoresize style="height:60px;width:100%" />
      </div>
    </div>
    <div v-else class="sp-empty">加载中...</div>
  </div>
</template>

<style scoped>
.sentiment-pano { background: var(--el-bg-color); border-radius: 8px; padding: 12px; }
.sp-header { display: flex; justify-content: space-between; margin-bottom: 8px; }
.sp-title { font-weight: 600; font-size: 13px; }
.sp-refresh { font-size: 12px; }
.sp-content { }
.sp-empty { text-align: center; padding: 16px; color: var(--el-text-color-secondary); font-size: 12px; }

.sent-bar { display: flex; height: 20px; border-radius: 10px; overflow: hidden; position: relative; margin-bottom: 8px; }
.sent-seg { display: flex; align-items: center; justify-content: center; }
.sent-label { font-size: 9px; color: #fff; text-shadow: 0 0 2px rgba(0,0,0,0.3); }
.sent-pointer { position: absolute; top: -4px; transform: translateX(-50%); transition: left 0.5s; }
.sent-score { background: var(--el-color-primary); color: #fff; padding: 1px 6px; border-radius: 6px; font-size: 10px; font-weight: 600; }
.sent-pointer::after { content: ''; display: block; width: 0; height: 0; border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 4px solid var(--el-color-primary); }

.sent-metrics { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 6px; }
.sent-m { display: flex; flex-direction: column; }
.sent-ml { font-size: 10px; color: var(--el-text-color-secondary); }
.sent-mv { font-size: 13px; font-weight: 600; }
.up { color: var(--el-color-danger); }
.down { color: var(--el-color-success); }
.warn { color: #e6a23c; }
.sent-boards { margin-top: 4px; }
</style>
