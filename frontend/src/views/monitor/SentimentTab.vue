<script setup lang="ts">
/**
 * SentimentTab — 情绪分析Tab (ReviewTab风格重构 v2.9.98zf)
 * 布局: hero-banner + metric-strip + review-section折叠 + dev-card双栏
 */
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useScannerMonitorInject } from './scannerMonitorInject'
import { ElButton } from 'element-plus'
import UnifiedDateBar from './components/UnifiedDateBar.vue'
import { api } from '@/api/client'
import { parseResponse } from '@/utils/scanner'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, LegendComponent, GridComponent, MarkLineComponent } from 'echarts/components'
import VChart from 'vue-echarts'
use([CanvasRenderer, BarChart, LineChart, TitleComponent, TooltipComponent, LegendComponent, GridComponent, MarkLineComponent])

const m = useScannerMonitorInject()
const {
  sentimentMode, sentimentDate, hoveredPoint, sentimentTimeline,
  displayTimeline, isIntradayFallback,
  xAxisLabels, sentimentMatrix, sentimentLoading,
  sentimentLive, phaseGuide, downgradeRules, phaseColors, sentimentAdvice,
  fetchSentimentData, strategyCN,
} = m

// 折叠状态
const chartExpanded = ref(true)
const statusExpanded = ref(false)
const dimExpanded = ref(false)
const logExpanded = ref(false)
const guideExpanded = ref(false)
const downgradeExpanded = ref(false)
const matrixExpanded = ref(false)
const algoDimExpanded = ref(false)
const algoSourceExpanded = ref(false)

// ===== 最新日内点 =====
const intradayLatest = computed(() => {
  const tl = displayTimeline.value as Array<Record<string, any>>
  for (let i = tl.length - 1; i >= 0; i--) { if (tl[i].score != null) return tl[i] }
  return tl.length ? tl[tl.length - 1] : null
})

// ===== ECharts 日内图 =====
const intradayChartOption = computed(() => {
  const tl = displayTimeline.value as Array<Record<string, any>>
  if (!tl.length) return {}
  const times = tl.map((p: any) => p.time_label || '')
  const limitUps = tl.map((p: any) => p.limit_up || 0)
  const limitDowns = tl.map((p: any) => -(p.limit_down || 0))
  const scores = tl.map((p: any) => p.score != null ? p.score : null)
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, backgroundColor: 'rgba(30,30,30,0.92)', borderColor: '#444', textStyle: { color: '#eee', fontSize: 11 },
      formatter: (params: any[]) => { const idx = params[0]?.dataIndex ?? 0; const p = tl[idx]; if (!p) return ''; return `<div style="font-weight:600;margin-bottom:4px">${p.time_label||''}</div>涨停<b style="color:#f56c6c">${p.limit_up||0}</b> 跌停<b style="color:#409eff">${p.limit_down||0}</b> 炸板<b style="color:#e6a23c">${p.broken||0}</b><br/>Score: <b style="color:${scoreColor(p.score||0)}">${(p.score||0).toFixed(1)}</b> ${periodCN(p.period||'')}<br/>动量${(p.momentum||0)>=0?'+':''}${(p.momentum||0).toFixed(1)} 溢价${(p.today_premium||0).toFixed(1)}% 炸板率${((p.broken_rate||0)*100).toFixed(0)}%` }
    },
    legend: { data: ['涨停','跌停','Score'], top: 4, right: 8, textStyle: { fontSize: 10 }, itemWidth: 12, itemHeight: 8 },
    grid: { left: 42, right: 42, top: 32, bottom: 28 },
    xAxis: { type: 'category', data: times, axisLabel: { fontSize: 9, interval: Math.max(0, Math.floor(times.length/8)-1), color: '#999' }, axisLine: { lineStyle: { color: '#444' } }, axisTick: { show: false } },
    yAxis: [
      { type: 'value', name: '数量', nameTextStyle: { fontSize: 9, color: '#999' }, axisLabel: { fontSize: 9, color: '#999', formatter: (v: number) => Math.abs(v) }, splitLine: { lineStyle: { color: '#333', type: 'dashed' } }, axisLine: { show: false } },
      { type: 'value', name: 'Score', min: 0, max: 100, nameTextStyle: { fontSize: 9, color: '#999' }, axisLabel: { fontSize: 9, color: '#999' }, splitLine: { show: false }, axisLine: { show: false } },
    ],
    series: [
      { name: '涨停', type: 'bar', data: limitUps, itemStyle: { color: 'rgba(245,108,108,0.7)', borderRadius: [2,2,0,0] }, barMaxWidth: 16 },
      { name: '跌停', type: 'bar', data: limitDowns, itemStyle: { color: 'rgba(64,158,255,0.6)', borderRadius: [0,0,2,2] }, barMaxWidth: 16 },
      { name: 'Score', type: 'line', data: scores, yAxisIndex: 1, smooth: 0.3, lineStyle: { width: 2, color: '#a855f7' }, itemStyle: { color: '#a855f7' }, symbol: 'circle', symbolSize: 3, connectNulls: true,
        markLine: { silent: true, lineStyle: { color: '#666', type: 'dashed', width: 1 }, label: { fontSize: 9, color: '#888' }, data: [{ yAxis: 50, label: { formatter: '50 中性' } }] } },
    ],
    animation: true, animationDuration: 400,
  }
})

// ===== 日线 =====
const dailyScorePoints = computed(() => { const tl = (displayTimeline.value as any[]).filter((p: any) => p.score != null); return tl.map((p: any, i: number) => `${i*20},${100-(p.score||0)}`).join(' ') })
const scoredTimeline = computed(() => (displayTimeline.value as any[]).filter((p: any) => p.score != null))
function matrixTotal(periods: Record<string,any>): number { return Object.values(periods).reduce((s: number, v: any) => s + ((v as any).count||0), 0) }
function dailyDotBottom(p: any): number { return p.score||0 }
function dailyHoverLeft(): number { const tl = displayTimeline.value as any[]; const hp = hoveredPoint.value as any; if (!hp) return 0; return Math.min(tl.findIndex(p => p === hp) / Math.max(tl.length-1,1) * 100, 75) }
function dailyHoverBottom(): number { const hp = hoveredPoint.value as any; return Math.min((hp?.score||30)+8, 85) }

// ===== 盘中日志 =====
const liveLogs = ref<any[]>([])
const liveLogsLoading = ref(false)
async function fetchLiveLogs() { liveLogsLoading.value = true; try { const r = await api.get('/scanner/sentiment-live-log?limit=50', { timeout: 5000 }); const p = parseResponse(r); if (p.success) liveLogs.value = p.data?.logs || [] } catch(e) { console.error('[SentimentTab]', e) } finally { liveLogsLoading.value = false } }

// ===== 工具函数 =====
function scoreColor(s: number): string { return s >= 70 ? '#f56c6c' : s >= 55 ? '#409eff' : s >= 40 ? '#e6a23c' : '#67c23a' }
function periodCN(p: string): string { return { rising:'🔥高潮', differentiation:'⚡分化', chaos:'🌀震荡', bearish:'🥶冰点', '高潮':'🔥高潮', '分化':'⚡分化', '震荡':'🌀震荡', '冰点':'🥶冰点' }[p] || p }
function periodColor(p: string): string { return { rising:'#f56c6c', differentiation:'#e6a23c', chaos:'#409eff', bearish:'#67c23a', '高潮':'#f56c6c', '分化':'#e6a23c', '震荡':'#409eff', '冰点':'#67c23a' }[p] || '#909399' }
function heroClass(s: number): string { return s >= 70 ? 'hot' : s >= 55 ? 'warm' : s >= 40 ? 'neutral' : 'cold' }

let liveLogTimer: number | undefined
onMounted(() => { fetchSentimentData(); fetchLiveLogs(); liveLogTimer = window.setInterval(fetchLiveLogs, 15000) })
onUnmounted(() => { if (liveLogTimer) clearInterval(liveLogTimer) })
</script>

<template>
  <div class="mm-tab-content">
    <div class="mm-tab-scroll">
      <!-- ========== 顶栏 ========== -->
      <div class="review-header">
        <div class="review-tabs">
          <button :class="['review-tab', sentimentMode==='intraday'?'active':'']" @click="sentimentMode='intraday';fetchSentimentData()">📈 日内</button>
          <button :class="['review-tab', sentimentMode==='daily'?'active':'']" @click="sentimentMode='daily';fetchSentimentData()">📊 日线</button>
          <button :class="['review-tab', sentimentMode==='weekly'?'active':'']" @click="sentimentMode='weekly';fetchSentimentData()">📅 周线</button>
          <button :class="['review-tab', sentimentMode==='monthly'?'active':'']" @click="sentimentMode='monthly';fetchSentimentData()">📆 月线</button>
        </div>
        <UnifiedDateBar @change="(_d:string)=>{sentimentDate=_d;fetchSentimentData()}" />
        <ElButton size="small" @click="fetchSentimentData" :loading="sentimentLoading">🔄</ElButton>
      </div>

      <!-- ========== 日内专属区 ========== -->
      <template v-if="sentimentMode==='intraday'">
        <div v-if="intradayLatest&&!isIntradayFallback" class="hero-banner" :class="heroClass(intradayLatest.score||0)">
          <div class="hero-conclusion">{{ (intradayLatest.score||0)>=70?'市场高潮，积极做多':(intradayLatest.score||0)>=55?'市场分化，精选龙头':(intradayLatest.score||0)>=40?'市场震荡，轻仓操作':'市场冰点，空仓观望' }}</div>
          <div class="hero-big-score" :style="{color:scoreColor(intradayLatest.score||0)}">{{ (intradayLatest.score||0).toFixed(0) }}<span class="hero-unit">分</span></div>
          <div class="hero-meta">
            <span :style="{color:periodColor(intradayLatest.period||'')}">{{ periodCN(intradayLatest.period||'') }}</span>
            <span>涨停<b class="up">{{ intradayLatest.limit_up||0 }}</b></span>
            <span>跌停<b class="down">{{ intradayLatest.limit_down||0 }}</b></span>
            <span>炸板<b>{{ intradayLatest.broken||0 }}</b>(<b>{{ ((intradayLatest.broken_rate||0)*100).toFixed(0) }}%</b>)</span>
            <span>动量<b :class="(intradayLatest.momentum||0)>0?'up':'down'">{{ (intradayLatest.momentum||0)>=0?'+':'' }}{{ (intradayLatest.momentum||0).toFixed(1) }}</b></span>
            <span>溢价<b>{{ (intradayLatest.today_premium||0).toFixed(1) }}%</b></span>
          </div>
        </div>
        <div v-if="intradayLatest&&!isIntradayFallback" class="metric-strip">
          <span class="ms">D1涨停 <b>{{ intradayLatest.limit_up||0 }}/20</b></span>
          <span class="ms">D2跌停 <b :class="(intradayLatest.limit_down||0)>10?'down':''">{{ intradayLatest.limit_down||0 }}/15</b></span>
          <span class="ms">D3涨跌比 <b>{{ ((intradayLatest.up_down_ratio||0)*100).toFixed(0) }}%</b></span>
          <span class="ms">D4动量 <b :class="(intradayLatest.momentum||0)>0?'up':(intradayLatest.momentum||0)<-0.05?'down':''">{{ (intradayLatest.momentum||0).toFixed(2) }}</b></span>
          <span class="ms">D5炸板率 <b :class="(intradayLatest.broken_rate||0)>0.3?'down':''">{{ ((intradayLatest.broken_rate||0)*100).toFixed(0) }}%</b></span>
          <span class="ms">D6连板 <b>{{ sentimentLive?.max_continue||0 }}/10</b></span>
          <span class="ms">D7昨溢价 <b>{{ (sentimentLive?.zt_premium||0).toFixed(1) }}/5</b></span>
          <span class="ms">D8今溢价 <b>{{ (intradayLatest.today_premium||0).toFixed(1) }}/5</b></span>
          <span class="ms">仓位 <b :style="{color:(sentimentLive?.position_ratio||0)>=0.7?'#f56c6c':(sentimentLive?.position_ratio||0)>=0.5?'#409eff':'#67c23a'}">{{ ((sentimentLive?.position_ratio||0)*100).toFixed(0) }}%</b></span>
          <span class="ms">开仓 <b :class="sentimentLive?.can_open!==false?'up':'down'">{{ sentimentLive?.can_open!==false?'✅':'❌' }}</b></span>
        </div>
        <div v-if="isIntradayFallback||!intradayLatest" class="review-section">
          <span class="section-detail" style="color:var(--text-tertiary);font-style:italic">📡 无日内扫描数据（非交易日或Scanner未运行），下方显示日线参考</span>
        </div>
        <div v-if="!isIntradayFallback" class="review-section">
          <span class="section-title title-blue" style="cursor:pointer" @click="chartExpanded=!chartExpanded">📈 情绪走势 <span style="font-weight:400;font-size:11px;color:var(--text-tertiary)">{{ chartExpanded?'▼':'▶' }} {{ displayTimeline.length }}点</span></span>
        </div>
        <div v-if="chartExpanded&&!isIntradayFallback&&displayTimeline.length" class="chart-wrap">
          <VChart :option="intradayChartOption" autoresize style="height:240px;width:100%" />
        </div>
      </template>

      <!-- ========== 日线/周线/月线 SVG 图表 ========== -->
      <div v-if="sentimentMode!=='intraday'||isIntradayFallback" class="sentiment-chart">
        <div class="sc-chart-row">
          <div class="sc-y-axis"><span>100</span><span>70</span><span>55</span><span>40</span><span>0</span></div>
          <div class="sc-chart-body">
            <div class="sc-band" style="height:30%;background:rgba(245,108,108,0.08)"></div>
            <div class="sc-band" style="height:15%;background:rgba(64,158,255,0.08)"></div>
            <div class="sc-band" style="height:15%;background:rgba(230,162,60,0.08)"></div>
            <div class="sc-band" style="height:40%;background:rgba(103,194,58,0.08)"></div>
            <svg class="sc-svg" :viewBox="`0 0 ${Math.max(scoredTimeline.length-1,1)*20} 100`" preserveAspectRatio="none"><polyline :points="dailyScorePoints" fill="none" stroke="var(--el-color-primary)" stroke-width="1.5" /></svg>
            <template v-for="(p,i) in (displayTimeline as any[])" :key="i">
              <div v-if="p.score!=null" class="sc-dot" :style="{left:`${i/Math.max((displayTimeline as any[]).length-1,1)*100}%`,bottom:`${dailyDotBottom(p)}%`}" :class="p.period==='高潮'?'hot':p.period==='冰点'?'cold':p.missing_data?'missing':''" @mouseenter="hoveredPoint=p" @mouseleave="hoveredPoint=null"></div>
            </template>
            <div v-if="hoveredPoint" class="sc-hover-card" :style="{left:`${dailyHoverLeft()}%`,bottom:`${dailyHoverBottom()}%`}">
              <div class="sc-hover-date">{{ hoveredPoint.date }}</div>
              <div class="sc-hover-score" :class="hoveredPoint.period==='高潮'?'hot':hoveredPoint.period==='冰点'?'cold':''">{{ (hoveredPoint.score??0).toFixed(1) }} {{ hoveredPoint.period }}</div>
              <div class="sc-hover-detail">涨停{{ hoveredPoint.limit_up||0 }} 跌停{{ hoveredPoint.limit_down||0 }}</div>
            </div>
          </div>
        </div>
        <div class="sc-x-labels"><span v-for="(lbl,i) in xAxisLabels" :key="i">{{ lbl }}</span></div>
      </div>

      <!-- ========== 所有模式共享的折叠section ========== -->
      <div class="review-section">
        <span class="section-title title-blue" style="cursor:pointer" @click="statusExpanded=!statusExpanded">🌡 当前状态 <span style="font-weight:400;font-size:11px;color:var(--text-tertiary)">{{ statusExpanded?'▼':'▶' }}</span></span>
        <span v-if="!statusExpanded&&sentimentLive" class="section-detail">情绪分<b :style="{color:scoreColor(sentimentLive.score||0)}">{{ (sentimentLive.score||0).toFixed(0) }}</b> {{ sentimentLive.period_label||sentimentLive.period }} 仓位<b>{{ ((sentimentLive.position_ratio||0)*100).toFixed(0) }}%</b> 涨停<b class="up">{{ sentimentLive.limit_up_count||0 }}</b> 跌停<b class="down">{{ sentimentLive.limit_down_count||0 }}</b> 炸板<b>{{ sentimentLive.broken_count||0 }}</b> 开仓<b>{{ sentimentLive.can_open!==false?'✅':'❌' }}</b></span>
      </div>
      <div v-if="statusExpanded&&sentimentLive" class="dev-card" style="margin-top:2px">
        <div class="dev-title">🌡 当前状态</div>
        <div class="dev-row"><span>情绪分</span><span :style="{color:scoreColor(sentimentLive.score||0),fontWeight:700}">{{ (sentimentLive.score||0).toFixed(0) }}</span></div>
        <div class="dev-row"><span>周期</span><span>{{ sentimentLive.period_label||sentimentLive.period }}</span></div>
        <div class="dev-row"><span>仓位系数</span><span>{{ ((sentimentLive.position_ratio||0)*100).toFixed(0) }}%</span></div>
        <div class="dev-row"><span>允许开仓</span><span :style="{color:sentimentLive.can_open!==false?'#67c23a':'#f56c6c'}">{{ sentimentLive.can_open!==false?'✅ 是':'❌ 否' }}</span></div>
        <div class="dev-row"><span>涨停</span><span class="up">{{ sentimentLive.limit_up_count||0 }}</span></div>
        <div class="dev-row"><span>跌停</span><span class="down">{{ sentimentLive.limit_down_count||0 }}</span></div>
        <div class="dev-row"><span>炸板</span><span>{{ sentimentLive.broken_count||0 }}(<b>{{ (sentimentLive.broken_rate||0).toFixed(1) }}%</b>)</span></div>
      </div>

      <div class="review-section">
        <span class="section-title title-purple" style="cursor:pointer" @click="dimExpanded=!dimExpanded">🧮 8维拆解 <span style="font-weight:400;font-size:11px;color:var(--text-tertiary)">{{ dimExpanded?'▼':'▶' }}</span></span>
        <span v-if="!dimExpanded&&sentimentLive" class="section-detail"><template v-if="sentimentLive.dimensions&&sentimentLive.dimensions.d1_limit_up!=null">D1涨停<b>{{ sentimentLive.dimensions.d1_limit_up }}/20</b> D2跌停<b>{{ sentimentLive.dimensions.d2_limit_down }}/15</b> D3涨跌比<b>{{ sentimentLive.dimensions.d3_up_down }}/15</b> D4动量<b>{{ sentimentLive.dimensions.d4_momentum }}/10</b> D5炸板<b>{{ sentimentLive.dimensions.d5_broken_rate }}/10</b> D6连板<b>{{ sentimentLive.dimensions.d6_max_continue }}/10</b> D7昨溢价<b>{{ sentimentLive.dimensions.d7_zt_premium }}/5</b> D8今溢价<b>{{ sentimentLive.dimensions.d8_today_premium }}/5</b></template><template v-else>涨停<b>{{ Math.min(30,sentimentLive.limit_up_count||0) }}/30</b> 跌停<b>{{ Math.max(0,20-(sentimentLive.limit_down_count||0)*2) }}/20</b> 连板<b>{{ Math.min(20,(sentimentLive.max_continue||0)*2) }}/20</b> 涨跌比<b>{{ Math.min(15,Math.round((sentimentLive.up_down_ratio||0)*15)) }}/15</b> 溢价<b>{{ Math.min(15,Math.max(0,Math.round(sentimentLive.zt_premium||0))) }}/15</b></template></span>
      </div>
      <div v-if="dimExpanded&&sentimentLive" class="dev-card" style="margin-top:2px">
        <template v-if="sentimentLive.dimensions&&sentimentLive.dimensions.d1_limit_up!=null">
          <div class="dev-row"><span>D1 涨停</span><span>{{ sentimentLive.dimensions.d1_limit_up }}/20</span></div>
          <div class="dev-row"><span>D2 跌停</span><span>{{ sentimentLive.dimensions.d2_limit_down }}/15</span></div>
          <div class="dev-row"><span>D3 涨跌比</span><span>{{ sentimentLive.dimensions.d3_up_down }}/15</span></div>
          <div class="dev-row"><span>D4 动量</span><span>{{ sentimentLive.dimensions.d4_momentum }}/10</span></div>
          <div class="dev-row"><span>D5 炸板率</span><span>{{ sentimentLive.dimensions.d5_broken_rate }}/10</span></div>
          <div class="dev-row"><span>D6 连板</span><span>{{ sentimentLive.dimensions.d6_max_continue }}/10</span></div>
          <div class="dev-row"><span>D7 昨溢价</span><span>{{ sentimentLive.dimensions.d7_zt_premium }}/5</span></div>
          <div class="dev-row"><span>D8 今溢价</span><span>{{ sentimentLive.dimensions.d8_today_premium }}/5</span></div>
        </template>
        <template v-else>
          <div class="dev-row"><span>涨停贡献</span><span>{{ Math.min(30,sentimentLive.limit_up_count||0) }}/30</span></div>
          <div class="dev-row"><span>跌停扣分</span><span>{{ Math.max(0,20-(sentimentLive.limit_down_count||0)*2) }}/20</span></div>
          <div class="dev-row"><span>连板高度</span><span>{{ Math.min(20,(sentimentLive.max_continue||0)*2) }}/20</span></div>
          <div class="dev-row"><span>涨跌比</span><span>{{ Math.min(15,Math.round((sentimentLive.up_down_ratio||0)*15)) }}/15</span></div>
          <div class="dev-row"><span>涨停溢价</span><span>{{ Math.min(15,Math.max(0,Math.round(sentimentLive.zt_premium||0))) }}/15</span></div>
          <div style="font-size:10px;color:var(--text-quaternary);margin-top:4px">5维盘后(无8维实时)</div>
        </template>
      </div>

      <div class="review-section">
        <span class="section-title title-purple" style="cursor:pointer" @click="logExpanded=!logExpanded">📜 计算日志 <span style="font-weight:400;font-size:11px;color:var(--text-tertiary)">{{ logExpanded?'▼':'▶' }} {{ liveLogs.length }}条</span></span>
        <ElButton size="small" @click="fetchLiveLogs" :loading="liveLogsLoading" style="font-size:10px;padding:0 6px;height:18px;margin-left:auto">🔄</ElButton>
      </div>
      <div v-if="logExpanded&&liveLogs.length" class="live-log-wrap">
        <table class="live-log-tbl">
          <thead><tr><th>时间</th><th>得分</th><th>周期</th><th>仓位</th><th>涨停</th><th>跌停</th><th>连板</th><th>涨跌比</th><th>溢价</th><th>动量</th><th>炸板</th></tr></thead>
          <tbody>
            <tr v-for="(l,i) in liveLogs" :key="l.time+i" :class="i===0?'live-log-latest':''">
              <td class="ll-time">{{ l.time }}</td>
              <td class="ll-score" :style="{color:scoreColor(l.score),fontWeight:'bold'}">{{ Number(l.score||0).toFixed(1) }}</td>
              <td><span class="ll-phase" :style="{color:phaseColors[l.phase_label]||'#888'}">{{ l.phase_label }}</span></td>
              <td>{{ ((l.position_ratio||0)*100).toFixed(0) }}%</td>
              <td class="up">{{ l.limit_up }}</td><td class="down">{{ l.limit_down }}</td>
              <td>{{ l.max_continue }}</td><td>{{ ((l.up_down_ratio||0)*100).toFixed(1) }}%</td>
              <td>{{ Number(l.zt_premium||0).toFixed(2) }}</td>
              <td :style="{color:(l.momentum||0)>=0?'#67c23a':'#f56c6c'}">{{ ((l.momentum||0)*100).toFixed(2) }}%</td>
              <td>{{ l.broken }} ({{ (l.broken_rate||0).toFixed(1) }}%)</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="review-section">
        <span class="section-title title-cyan" style="cursor:pointer" @click="guideExpanded=!guideExpanded">📖 阶段说明 <span style="font-weight:400;font-size:11px;color:var(--text-tertiary)">{{ guideExpanded?'▼':'▶' }}</span></span>
        <span v-if="!guideExpanded&&sentimentLive" class="section-detail"><b :style="{color:(sentimentLive.score||0)>=70?'#f56c6c':(sentimentLive.score||0)>=55?'#e6a23c':(sentimentLive.score||0)>=40?'#409eff':'#67c23a'}">{{ (sentimentLive.score||0)>=70?'🔥高潮':(sentimentLive.score||0)>=55?'⚡分化':(sentimentLive.score||0)>=40?'🌀震荡':'🥶冰点' }}</b> 仓位<b>{{ (sentimentLive.score||0)>=70?'100%':(sentimentLive.score||0)>=55?'70%':(sentimentLive.score||0)>=40?'50%':'30%' }}</b> {{ (sentimentLive.score||0)>=70?'积极做多':(sentimentLive.score||0)>=55?'精选龙头':(sentimentLive.score||0)>=40?'轻仓操作':'空仓观望' }}</span>
      </div>
      <div v-if="guideExpanded" class="phase-guide">
        <div v-for="p in phaseGuide" :key="p.name" class="phase-card" :class="p.active?'active':''" :style="{borderColor:p.color}">
          <div class="phase-header" :style="{background:p.color+'18'}"><span class="phase-icon">{{ p.icon }}</span><span class="phase-name" :style="{color:p.color}">{{ p.name }}</span><span class="phase-range">{{ p.range }}</span></div>
          <div class="phase-body"><div class="phase-row"><span class="phase-label">仓位</span><span class="phase-val">{{ p.position }}</span></div><div class="phase-row"><span class="phase-label">开仓</span><span class="phase-val">{{ p.canOpen }}</span></div><div class="phase-row"><span class="phase-label">策略</span><span class="phase-val">{{ p.strategy }}</span></div></div>
        </div>
      </div>

      <div v-if="downgradeRules?.length" class="review-section">
        <span class="section-title title-orange" style="cursor:pointer" @click="downgradeExpanded=!downgradeExpanded">⚠️ 降级规则 <span style="font-weight:400;font-size:11px;color:var(--text-tertiary)">{{ downgradeExpanded?'▼':'▶' }} {{ downgradeRules.length }}条</span></span>
      </div>
      <div v-if="downgradeExpanded&&downgradeRules?.length" class="dg-list">
        <div v-for="r in downgradeRules" :key="r.from+r.to" class="dg-row"><span class="dg-from" :style="{color:phaseColors[r.from]}">{{ r.from }}</span><span class="dg-arrow">→</span><span class="dg-to" :style="{color:phaseColors[r.to]}">{{ r.to }}</span><span class="dg-action">{{ r.action }}</span><span class="dg-desc">{{ r.desc }}</span></div>
      </div>

      <div v-if="sentimentMatrix&&Object.keys(sentimentMatrix).length" class="review-section">
        <span class="section-title title-red" style="cursor:pointer" @click="matrixExpanded=!matrixExpanded">📋 策略×情绪 <span style="font-weight:400;font-size:11px;color:var(--text-tertiary)">{{ matrixExpanded?'▼':'▶' }} {{ Object.keys(sentimentMatrix).length }}策略</span></span>
      </div>
      <div v-if="matrixExpanded&&sentimentMatrix" class="matrix-table-wrap">
        <table class="matrix-table"><thead><tr><th>策略</th><th>冰点</th><th>震荡</th><th>分化</th><th>高潮</th><th>合计</th></tr></thead>
        <tbody><tr v-for="(periods,strat) in sentimentMatrix" :key="strat"><td class="mt-strat">{{ strategyCN(strat) }}</td><td v-for="col in ['冰点','震荡','分化','高潮']" :key="col" class="mt-cell"><template v-if="periods[col]"><div class="mt-count" :class="periods[col].total_pnl>=0?'up':'down'">{{ periods[col].count }}笔</div><div class="mt-wr" :class="periods[col].win_rate>=50?'up':'down'">WR{{ periods[col].win_rate }}%</div><div class="mt-pnl" :class="periods[col].total_pnl>=0?'up':'down'">¥{{ periods[col].total_pnl }}</div></template><span v-else class="mt-empty">-</span></td><td class="mt-total">{{ matrixTotal(periods) }}笔</td></tr></tbody></table>
      </div>

      <div v-if="sentimentLive" class="review-section">
        <span class="section-title title-blue">💡 建议</span>
        <span class="section-detail">{{ sentimentAdvice }}</span>
      </div>
      <div v-if="sentimentLive&&(sentimentLive.score||0)<40" class="review-section">
        <span class="section-title title-orange">⚠️ 风险</span>
        <span class="section-detail down">冰点期，建议空仓观望，禁止新开仓。</span>
      </div>
      <div v-else-if="sentimentLive&&(sentimentLive.score||0)<55" class="review-section">
        <span class="section-title title-orange">⚡ 提醒</span>
        <span class="section-detail">震荡期，轻仓操作，仅做龙头低吸，严格止损3%。</span>
      </div>

      <!-- ========== 算法说明 ========== -->
      <div class="review-section">
        <span class="section-title title-purple" style="cursor:pointer" @click="algoDimExpanded=!algoDimExpanded">📐 算法日内8维 <span style="font-weight:400;font-size:11px;color:var(--text-tertiary)">{{ algoDimExpanded?'▼':'▶' }}</span></span>
        <span v-if="!algoDimExpanded" class="section-detail">D1涨停(0-20) D2跌停(0-15) D3涨跌比(0-15) D4动量(-5~10) D5炸板率(0-10) D6连板(0-10) D7昨溢价(0-5) D8今溢价(0-5)</span>
      </div>
      <div v-if="algoDimExpanded" class="dev-card" style="margin-top:2px">
        <div style="font-size:10px;color:var(--text-secondary);line-height:1.6"><b>D1涨停</b>(0-20) <b>D2跌停</b>(0-15) <b>D3涨跌比</b>(0-15) <b>D4动量</b>(-5~10) <b>D5炸板率</b>(0-10) <b>D6连板</b>(0-10) <b>D7昨溢价</b>(0-5) <b>D8今溢价</b>(0-5)<br>≥70🔥 | ≥55⚡ | ≥40🌀 | &lt;40🥶</div>
      </div>
      <div class="review-section">
        <span class="section-title title-cyan" style="cursor:pointer" @click="algoSourceExpanded=!algoSourceExpanded">📊 数据源 <span style="font-weight:400;font-size:11px;color:var(--text-tertiary)">{{ algoSourceExpanded?'▼':'▶' }}</span></span>
        <span v-if="!algoSourceExpanded" class="section-detail">盘中 Scanner 8维 | 炸板 limit_list | 历史 5维+8维</span>
      </div>
      <div v-if="algoSourceExpanded" class="dev-card" style="margin-top:2px">
        <div style="font-size:10px;color:var(--text-secondary);line-height:1.6"><b>盘中</b> Scanner 8维公式 5min采样 | <b>炸板</b> limit_list.open_times<br><b>历史</b> sentiment_scores(5维) + sentiment_live_log(8维)</div>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.review-header { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; flex-wrap: nowrap; }
.review-tabs { display: flex; gap: 2px; }
.review-tab { padding: 3px 8px; border: 1px solid var(--border-default); border-radius: 4px; background: var(--bg-elevated); color: var(--text-secondary); font-size: 11px; cursor: pointer; transition: all 0.2s; }
.review-tab:hover { background: var(--bg-hover); }
.review-tab.active { background: var(--el-color-primary); color: var(--text-inverse); border-color: var(--el-color-primary); }

.review-section { padding: 3px 8px; background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 4px; margin-bottom: 2px; display: flex; align-items: baseline; flex-wrap: wrap; gap: 4px; overflow: visible; }
.section-title { font-size: 13px; font-weight: 800; line-height: 1.4; padding: 1px 6px; border-left: 3px solid var(--el-color-primary); white-space: nowrap; flex-shrink: 0; }
.title-red { border-left-color: #e6363a; color: #e6363a; }
.title-orange { border-left-color: #e6a23c; color: #e6a23c; }
.title-blue { border-left-color: #409eff; color: #409eff; }
.title-purple { border-left-color: #9b59b6; color: #9b59b6; }
.title-cyan { border-left-color: #36cfc9; color: #36cfc9; }
.section-detail { font-size: 11px; color: var(--text-secondary); line-height: 1.6; flex-basis: calc(100% - 110px); flex-shrink: 1; overflow: visible; }
.section-detail b { font-weight: 600; color: var(--text-primary); font-size: 12px; margin: 0 1px; }

.hero-banner { padding: 4px 8px; border-radius: 4px; margin-bottom: 2px; display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.hero-conclusion { font-size: 12px; font-weight: 700; }
.hero-big-score { font-size: 20px; font-weight: 800; letter-spacing: -0.5px; }
.hero-unit { font-size: 11px; font-weight: 400; margin-left: 1px; }
.hero-meta { display: flex; gap: 8px; font-size: 10px; color: var(--text-secondary); margin-left: auto; }
.hero-banner.hot { background: linear-gradient(135deg, rgba(245,108,108,0.12), rgba(245,108,108,0.03)); border: 1px solid rgba(245,108,108,0.25); }
.hero-banner.warm { background: linear-gradient(135deg, rgba(64,158,255,0.10), rgba(230,162,60,0.03)); border: 1px solid rgba(64,158,255,0.18); }
.hero-banner.neutral { background: linear-gradient(135deg, rgba(230,162,60,0.08), rgba(230,162,60,0.02)); border: 1px solid rgba(230,162,60,0.18); }
.hero-banner.cold { background: linear-gradient(135deg, rgba(103,194,58,0.10), rgba(103,194,58,0.03)); border: 1px solid rgba(103,194,58,0.18); }

.metric-strip { display: flex; flex-wrap: wrap; gap: 2px 6px; margin-top: 2px; padding: 3px 8px; background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 3px; font-size: 10px; color: var(--text-tertiary); }
.metric-strip .ms b { font-weight: 600; color: var(--text-primary); font-size: 11px; margin-left: 2px; }
.metric-strip .ms b.down { color: #f56c6c; }
.metric-strip .ms b.up { color: #67c23a; }

.review-2col { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; margin-top: 4px; }
.dev-card { padding: 8px 10px; border-radius: 6px; background: var(--bg-elevated); border: 1px solid var(--border-default); }
.dev-title { font-weight: 700; font-size: 12px; margin-bottom: 4px; }
.dev-row { display: flex; justify-content: space-between; font-size: 11px; padding: 2px 0; }
.dev-row span:first-child { color: var(--text-tertiary); }

.chart-wrap { border: 1px solid var(--border-default); border-radius: 6px; overflow: hidden; background: var(--bg-elevated); padding: 2px; margin-bottom: 2px; }

.sentiment-chart { display: flex; flex-direction: column; height: 260px; border: 1px solid var(--border-default); border-radius: 6px; overflow: hidden; background: var(--bg-elevated); margin-top: 4px; }
.sc-chart-row { display: flex; flex: 1; min-height: 0; }
.sc-y-axis { display: flex; flex-direction: column-reverse; justify-content: space-between; padding: 4px 6px; font-size: 10px; color: var(--text-tertiary); min-width: 36px; text-align: right; }
.sc-chart-body { flex: 1; position: relative; display: flex; flex-direction: column-reverse; }
.sc-band { width: 100%; position: relative; z-index: 1; }
.sc-svg { position: absolute; inset: 0; width: 100%; height: 100%; z-index: 3; }
.sc-dot { position: absolute; width: 6px; height: 6px; border-radius: 50%; background: var(--el-color-primary); transform: translate(-50%, 50%); z-index: 4; cursor: pointer; transition: transform 0.15s; }
.sc-dot:hover { transform: translate(-50%, 50%) scale(2); }
.sc-dot.hot { background: #f56c6c; }
.sc-dot.cold { background: #67c23a; }
.sc-dot.missing { background: var(--el-color-warning); opacity: 0.6; border: 1px dashed var(--el-color-warning); }
.sc-hover-card { position: absolute; z-index: 10; background: var(--el-bg-color-overlay); border: 1px solid var(--el-border-color); border-radius: 6px; padding: 6px 10px; font-size: 12px; pointer-events: none; box-shadow: 0 2px 8px rgba(0,0,0,0.15); white-space: nowrap; }
.sc-hover-date { color: var(--text-secondary); margin-bottom: 2px; }
.sc-hover-score { font-weight: 600; font-size: 14px; }
.sc-hover-score.hot { color: #f56c6c; }
.sc-hover-score.cold { color: #67c23a; }
.sc-hover-detail { color: var(--text-tertiary); margin-top: 2px; }
.sc-x-labels { display: flex; justify-content: space-between; padding: 4px 8px 4px 40px; font-size: 11px; color: var(--text-tertiary); border-top: 1px solid var(--border-default); min-height: 22px; }

.phase-guide { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin-top: 2px; }
.phase-card { border: 1px solid var(--border-default); border-radius: 6px; overflow: hidden; opacity: 0.6; }
.phase-card.active { opacity: 1; box-shadow: 0 0 0 2px var(--el-color-primary); }
.phase-header { display: flex; align-items: center; gap: 4px; padding: 5px 8px; font-size: 12px; }
.phase-icon { font-size: 14px; }
.phase-name { font-weight: 700; font-size: 12px; }
.phase-range { margin-left: auto; color: var(--text-tertiary); font-size: 10px; }
.phase-body { padding: 4px 8px; }
.phase-row { display: flex; justify-content: space-between; font-size: 11px; padding: 1px 0; }
.phase-label { color: var(--text-tertiary); }
.phase-val { font-weight: 500; }

.live-log-wrap { overflow-x: auto; max-height: 320px; overflow-y: auto; border: 1px solid var(--border-default); border-radius: 4px; margin-top: 2px; }
.live-log-tbl { width: 100%; border-collapse: collapse; font-size: 11px; }
.live-log-tbl th { position: sticky; top: 0; z-index: 1; padding: 5px 8px; background: var(--bg-secondary); font-weight: 600; color: var(--text-tertiary); text-align: center; border-bottom: 1px solid var(--border-default); white-space: nowrap; }
.live-log-tbl td { padding: 4px 8px; text-align: center; border-bottom: 1px solid var(--border-subtle); white-space: nowrap; }
.live-log-latest { background: rgba(64, 158, 255, 0.08); }
.live-log-latest td { font-weight: 500; }
.ll-time { font-family: 'Menlo','Monaco',monospace; color: var(--text-tertiary); }
.ll-score { font-family: 'Menlo','Monaco',monospace; min-width: 38px; }
.ll-phase { padding: 1px 6px; border-radius: 3px; font-size: 10px; background: rgba(128,128,128,0.08); }

.matrix-table-wrap { overflow-x: auto; margin-top: 2px; }
.matrix-table { width: 100%; border-collapse: collapse; font-size: 11px; }
.matrix-table th { padding: 5px 8px; background: var(--bg-secondary); font-weight: 600; color: var(--text-tertiary); text-align: center; border-bottom: 1px solid var(--border-default); }
.matrix-table td { padding: 5px 8px; text-align: center; border-bottom: 1px solid var(--border-default); }
.mt-strat { font-weight: 600; text-align: left !important; }
.mt-cell { min-width: 80px; }
.mt-count { font-weight: 600; }
.mt-wr { font-size: 10px; }
.mt-pnl { font-size: 10px; font-weight: 600; }
.mt-empty { color: var(--text-quaternary); }
.mt-total { font-weight: 600; color: var(--text-secondary); }

.up { color: var(--stock-up); }
.down { color: var(--stock-down); }

.dg-list { display: flex; flex-direction: column; gap: 2px; margin-bottom: 2px; }
.dg-row { display: flex; align-items: center; gap: 6px; padding: 3px 8px; font-size: 11px; background: var(--bg-elevated); border: 1px solid var(--border-default); border-radius: 3px; }
.dg-from, .dg-to { font-weight: 700; min-width: 28px; }
.dg-arrow { color: var(--text-quaternary); }
.dg-action { color: var(--el-color-warning); font-weight: 600; min-width: 60px; }
.dg-desc { color: var(--text-tertiary); }

</style>

