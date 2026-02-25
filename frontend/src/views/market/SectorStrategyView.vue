<template>
  <div class="sector-strategy">
    <!-- 页面头部 -->
    <div class="page-header">
      <h1 class="page-title">板块分析中心</h1>
      <div class="header-info">
        <span class="trade-date">{{ tradeDate }}</span>
        <button class="refresh-btn" @click="loadData" :disabled="loading">
          <svg viewBox="0 0 24 24" :class="{ spinning: loading }">
            <path fill="currentColor" d="M17.65 6.35A7.958 7.958 0 0012 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0112 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/>
          </svg>
        </button>
      </div>
    </div>

    <!-- 上部：趋势分析 -->
    <div class="top-section">
      <div class="analysis-panel">
        <div class="diagnosis-section">
          <h2 class="section-title">
            <span class="title-icon">◉</span>
            趋势诊断
          </h2>
          <div class="diagnosis-text">
            <p v-for="(line, idx) in diagnosisLines" :key="idx" :class="getDiagnosisClass(line)">
              {{ line }}
            </p>
          </div>
        </div>

        <!-- 三列网格：核心主线 | 脉冲轮动 | 退潮信号 -->
        <div class="theme-grid">
          <!-- 核心主线 -->
          <div class="theme-column core-themes">
            <h3 class="subsection-title">核心主线 [CORE]</h3>
            <div class="theme-list">
              <div 
                v-for="(theme, idx) in coreThemes" 
                :key="idx" 
                class="theme-item core"
              >
                <div class="theme-main">
                  <span class="theme-rank">#{{ idx + 1 }}</span>
                  <span class="theme-name">{{ theme.name }}</span>
                  <span class="theme-freq">{{ theme.frequency }}次</span>
                </div>
                <div class="theme-sub">
                  <span class="lead-stock" v-if="theme.lead_stock">领涨: {{ theme.lead_stock }}</span>
                </div>
              </div>
              <div v-if="coreThemes.length === 0" class="empty-hint">暂无核心主线</div>
            </div>
          </div>

          <!-- 脉冲轮动 -->
          <div class="theme-column pulse-themes">
            <h3 class="subsection-title">脉冲轮动 [PULSE]</h3>
            <div class="theme-list">
              <div 
                v-for="(theme, idx) in pulseThemes" 
                :key="idx" 
                class="theme-item pulse"
              >
                <div class="theme-main">
                  <span class="theme-name">{{ theme.name }}</span>
                  <span class="theme-pct up">+{{ theme.today_pct.toFixed(1) }}%</span>
                </div>
                <div class="theme-sub">
                  <span class="lead-stock" v-if="theme.lead_stock">领涨: {{ theme.lead_stock }}</span>
                </div>
              </div>
              <div v-if="pulseThemes.length === 0" class="empty-hint">暂无脉冲轮动</div>
            </div>
          </div>

          <!-- 退潮信号 -->
          <div class="theme-column fading-themes">
            <h3 class="subsection-title">退潮信号 [FADE]</h3>
            <div class="theme-list">
              <div 
                v-for="(theme, idx) in fadingThemes" 
                :key="idx" 
                class="theme-item fading"
              >
                <div class="theme-main">
                  <span class="theme-name">{{ theme.name }}</span>
                </div>
                <div class="theme-sub">
                  <span class="lead-stock" v-if="theme.lead_stock">领涨: {{ theme.lead_stock }}</span>
                </div>
              </div>
              <div v-if="fadingThemes.length === 0" class="empty-hint">暂无退潮信号</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 中部：散点雷达 -->
    <div class="middle-section">
      <div class="scatter-panel">
        <div class="scatter-header">
          <h2 class="section-title">共识度 × 短期强度</h2>
          <button class="help-btn" @click="showGuideDialog = true" title="查看象限说明">
            <svg viewBox="0 0 24 24" width="18" height="18">
              <path fill="currentColor" d="M11 18h2v-2h-2v2zm1-16C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm0-14c-2.21 0-4 1.79-4 4h2c0-1.1.9-2 2-2s2 .9 2 2c0 2-3 1.75-3 5h2c0-2.25 3-2.5 3-5 0-2.21-1.79-4-4-4z"/>
            </svg>
          </button>
        </div>
        <div class="scatter-chart" ref="scatterChartRef"></div>
        <div class="zone-legend">
          <span class="zone-item golden">黄金坑</span>
          <span class="zone-item pulse">脉冲区</span>
          <span class="zone-item resonance">共振区</span>
          <span class="zone-item cold">冷宫区</span>
        </div>
      </div>
    </div>

    <!-- 教练模式指导弹窗 -->
    <div class="guide-dialog-overlay" v-if="showGuideDialog" @click.self="showGuideDialog = false">
      <div class="guide-dialog">
        <div class="guide-header">
          <h3>象限策略指南</h3>
          <button class="close-btn" @click="showGuideDialog = false">×</button>
        </div>
        <div class="guide-content">
          <div class="guide-item golden">
            <div class="guide-zone">右下角</div>
            <div class="guide-label">【黄金坑】</div>
            <div class="guide-desc">大资金已深度介入，目前是缩量回调，主线低吸位。</div>
          </div>
          <div class="guide-item pulse">
            <div class="guide-zone">左上角</div>
            <div class="guide-label">【脉冲区】</div>
            <div class="guide-desc">无资金基础的突发上涨，多为一日游，<strong>严禁追高</strong>。</div>
          </div>
          <div class="guide-item resonance">
            <div class="guide-zone">右上角</div>
            <div class="guide-label">【共振区】</div>
            <div class="guide-desc">主线加速，适合持股或高抛，不宜新开仓。</div>
          </div>
          <div class="guide-item cold">
            <div class="guide-zone">左下角</div>
            <div class="guide-label">【冷宫区】</div>
            <div class="guide-desc">无资金关注，无波动，直接忽略。</div>
          </div>
        </div>
      </div>
    </div>

    <!-- PULSE 警告弹窗 -->
    <div class="pulse-warning-overlay" v-if="showPulseWarning" @click="showPulseWarning = false">
      <div class="pulse-warning-dialog">
        <div class="warning-icon">⚠️</div>
        <div class="warning-title">诱多风险警告</div>
        <div class="warning-sector">{{ selectedPulseSector }}</div>
        <div class="warning-desc">该板块共识度极低，今日突发上涨可能为一日游行情，严禁追高！</div>
        <button class="warning-close" @click="showPulseWarning = false">知道了</button>
      </div>
    </div>

    <!-- 下半部分：全屏表格 -->
    <div class="table-section">
      <h2 class="section-title">板块评分明细</h2>
      <div class="table-wrapper">
        <table class="sector-table">
          <thead>
            <tr>
              <th class="rank-th">排名</th>
              <th class="name-th">板块</th>
              <th class="lead-th">领涨个股</th>
              <th class="freq-th">20日共识</th>
              <th class="strength-th">短期强度</th>
              <th class="category-th">分类</th>
              <th class="reason-th">系统建议</th>
            </tr>
          </thead>
          <tbody>
            <tr 
              v-for="(sector, idx) in sectors" 
              :key="sector.name"
              :class="['sector-row', sector.status]"
            >
              <td class="rank-col">{{ idx + 1 }}</td>
              <td class="name-col">{{ sector.name }}</td>
              <td class="lead-col">{{ sector.lead_stock || '-' }}</td>
              <td class="freq-col">{{ sector.frequency }}次</td>
              <td class="strength-col" :class="sector.short_strength >= 0 ? 'up' : 'down'">
                {{ sector.short_strength >= 0 ? '+' : '' }}{{ sector.short_strength.toFixed(1) }}
              </td>
              <td class="category-col">
                <span class="category-tag" :class="sector.status">{{ sector.category }}</span>
              </td>
              <td class="reason-col">{{ sector.reason }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import * as echarts from 'echarts'
import { marketApi } from '@/api'
import type { SectorScore, ScatterPoint, ScatterZone } from '@/api/modules/market'

// 响应式数据
const loading = ref(false)
const tradeDate = ref('')
const sectors = ref<SectorScore[]>([])
const coreThemes = ref<SectorScore[]>([])
const pulseThemes = ref<SectorScore[]>([])
const fadingThemes = ref<SectorScore[]>([])
const diagnosis = ref('')
const scatterData = ref<ScatterPoint[]>([])
const scatterZones = ref<ScatterZone[]>([])

// 弹窗控制
const showGuideDialog = ref(false)
const showPulseWarning = ref(false)
const selectedPulseSector = ref('')

// 图表
const scatterChartRef = ref<HTMLElement | null>(null)
let scatterChart: echarts.ECharts | null = null

// 诊断文字分行
const diagnosisLines = computed(() => {
  return diagnosis.value.split('\n').filter(l => l.trim())
})

// 诊断行样式
const getDiagnosisClass = (line: string) => {
  if (line.includes('核心主线')) return 'core'
  if (line.includes('脉冲轮动')) return 'pulse'
  if (line.includes('退潮信号')) return 'fading'
  return ''
}

// 数据加载
const loadData = async () => {
  loading.value = true
  try {
    const [scoresRes, scatterRes] = await Promise.all([
      marketApi.getSectorScores(),
      marketApi.getSectorScatter(),
    ])
    
    tradeDate.value = scoresRes.trade_date
    sectors.value = scoresRes.sectors || []
    coreThemes.value = scoresRes.core_themes || []
    pulseThemes.value = scoresRes.pulse_themes || []
    fadingThemes.value = scoresRes.fading_themes || []
    diagnosis.value = scoresRes.diagnosis || ''
    scatterData.value = scatterRes.scatter || []
    scatterZones.value = scatterRes.zones || []
    
    updateScatterChart()
  } catch (error) {
    console.error('Failed to load sector data:', error)
  } finally {
    loading.value = false
  }
}

// 处理散点数据，标记 PULSE 和 CORE
const processScatterData = () => {
  // 按今日排名排序（短期强度越高排名越前）
  const sortedByStrength = [...scatterData.value].sort((a, b) => b.y - a.y)
  const top3Names = new Set(sortedByStrength.slice(0, 3).map(p => p.name))
  
  return scatterData.value.map(p => {
    // PULSE: 今日排名前3，但20日共识度 < 3
    const isPulse = top3Names.has(p.name) && p.x < 3
    // CORE: 20日共识度 >= 9
    const isCore = p.x >= 9
    
    return {
      ...p,
      isPulse,
      isCore,
    }
  })
}

// 散点图配置 - 专业暗色风格（参考东方财富/同花顺）
const updateScatterChart = () => {
  if (!scatterChart) return
  
  const processedData = processScatterData()
  
  // 计算Y轴范围
  const yValues = processedData.map(p => p.y)
  const dataYMin = Math.min(...yValues, -20)
  const dataYMax = Math.max(...yValues, 40)
  const yRange = dataYMax - dataYMin
  const yPadding = yRange * 0.15
  const yMin = Math.floor(dataYMin - yPadding)
  const yMax = Math.ceil(dataYMax + yPadding)
  const yMid = 0
  const xMid = 10
  
  // 极致暗色配色 - 近纯黑背景
  const THEME = {
    bg: '#0A0A0F',           // 近纯黑背景
    resonance: '#22D3EE',    // 共振区 - 亮青色 (发光)
    pulse: '#F59E0B',        // 脉冲区 - 琥珀橙
    golden: '#3B82F6',       // 黄金坑 - 深蓝色
    cold: '#475569',         // 冷宫区 - 深灰色
    text: '#FFFFFF',         // 纯白文字
    textMuted: '#64748B',    // 次要文字
    axis: 'rgba(100, 116, 139, 0.25)',  // 坐标轴
  }
  
  // 四象限极微弱背景 (透明度 0.02 - 若隐若现)
  const quadrantAreas = [
    // 脉冲区 - 左上
    { data: [[{ xAxis: 0, yAxis: yMid }, { xAxis: xMid, yAxis: yMax }]], itemStyle: { color: 'rgba(245, 158, 11, 0.02)' } },
    // 共振区 - 右上 (稍微明显一点)
    { data: [[{ xAxis: xMid, yAxis: yMid }, { xAxis: 20, yAxis: yMax }]], itemStyle: { color: 'rgba(34, 211, 238, 0.025)' } },
    // 冷宫区 - 左下 (几乎不可见)
    { data: [[{ xAxis: 0, yAxis: yMin }, { xAxis: xMid, yAxis: yMid }]], itemStyle: { color: 'rgba(100, 116, 139, 0.015)' } },
    // 黄金坑 - 右下
    { data: [[{ xAxis: xMid, yAxis: yMin }, { xAxis: 20, yAxis: yMid }]], itemStyle: { color: 'rgba(59, 130, 246, 0.02)' } },
  ]
  
  // 散点数据 - 活跃象限发光，冷宫区淡化
  const data = processedData.map(p => {
    const isResonance = p.x >= 9 && p.y > 0
    const isPulse = p.x < 5 && p.y >= 15
    const isGoldenPit = p.x >= 9 && p.y <= 0
    const isCold = p.x < 5 && p.y < 0
    
    let color = THEME.cold
    let opacity = 1
    let symbolSize = 12
    let shadowBlur = 0
    let shadowColor = 'transparent'
    
    if (isResonance) {
      color = THEME.resonance
      symbolSize = 16
      shadowBlur = 12  // 微弱径向发光
      shadowColor = 'rgba(34, 211, 238, 0.4)'
    } else if (isPulse) {
      color = THEME.pulse
      symbolSize = 14
      shadowBlur = 8
      shadowColor = 'rgba(245, 158, 11, 0.3)'
    } else if (isGoldenPit) {
      color = THEME.golden
      symbolSize = 14
      shadowBlur = 6
      shadowColor = 'rgba(59, 130, 246, 0.3)'
    } else if (isCold) {
      color = THEME.cold
      opacity = 0.35  // 冷宫区高度淡化
      symbolSize = 9
    } else {
      color = THEME.cold
      opacity = 0.55
      symbolSize = 10
    }
    
    return {
      value: [p.x, p.y],
      name: p.name,
      itemStyle: { 
        color,
        opacity,
        borderColor: 'rgba(255, 255, 255, 0.3)',
        borderWidth: 1,
        shadowBlur,
        shadowColor,
      },
      symbolSize,
    }
  })
  
  scatterChart.setOption({
    backgroundColor: THEME.bg,
    animation: true,
    animationDuration: 400,
    tooltip: {
      trigger: 'item',
      confine: true,
      backgroundColor: 'rgba(10, 10, 15, 0.95)',
      borderColor: 'rgba(255, 255, 255, 0.06)',
      borderWidth: 1,
      borderRadius: 8,
      padding: [14, 18],
      textStyle: { color: '#FFFFFF', fontSize: 13 },
      formatter: (params: any) => {
        const point = processedData.find(p => p.name === params.name)
        if (!point) return ''
        const strengthColor = point.y >= 0 ? '#10B981' : '#EF4444'
        return `
          <div style="font-weight:600;font-size:14px;margin-bottom:10px;color:#FFFFFF">${point.name}</div>
          <div style="font-size:12px;color:#64748B;line-height:1.8">
            <div>20日共识度: <span style="color:#FFFFFF;font-weight:500">${point.x} 次</span></div>
            <div>短期强度: <span style="color:${strengthColor};font-weight:500">${point.y >= 0 ? '+' : ''}${point.y.toFixed(1)}</span></div>
          </div>
        `
      },
    },
    grid: {
      left: '6%',
      right: '6%',
      top: '10%',
      bottom: '12%',
      containLabel: true,
    },
    xAxis: {
      type: 'value',
      name: '20日共识度',
      nameLocation: 'center',
      nameGap: 28,
      nameTextStyle: { color: THEME.textMuted, fontSize: 12 },
      min: 0,
      max: 20,
      axisLine: { lineStyle: { color: THEME.axis } },
      axisTick: { show: false },
      axisLabel: { color: THEME.textMuted, fontSize: 11 },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      name: '短期强度',
      nameLocation: 'center',
      nameGap: 36,
      nameTextStyle: { color: THEME.textMuted, fontSize: 12 },
      min: yMin,
      max: yMax,
      axisLine: { lineStyle: { color: THEME.axis } },
      axisTick: { show: false },
      axisLabel: { color: THEME.textMuted, fontSize: 11 },
      splitLine: { show: false },
    },
    graphic: [
      // 象限水印 - 极淡灰色空心文字（不使用背景色块）
      { type: 'text', left: '8%', top: '12%', style: { 
        text: '脉冲区', 
        fill: 'transparent',
        stroke: 'rgba(100, 116, 139, 0.12)',
        lineWidth: 0.5,
        fontSize: 14, 
        fontWeight: 500,
        fontFamily: 'Inter, system-ui, sans-serif',
      }},
      { type: 'text', right: '7%', top: '12%', style: { 
        text: '共振区', 
        fill: 'transparent',
        stroke: 'rgba(100, 116, 139, 0.15)',
        lineWidth: 0.5,
        fontSize: 14, 
        fontWeight: 500,
        fontFamily: 'Inter, system-ui, sans-serif',
      }},
      { type: 'text', left: '8%', bottom: '18%', style: { 
        text: '冷宫区', 
        fill: 'transparent',
        stroke: 'rgba(100, 116, 139, 0.08)',
        lineWidth: 0.5,
        fontSize: 14, 
        fontWeight: 500,
        fontFamily: 'Inter, system-ui, sans-serif',
      }},
      { type: 'text', right: '7%', bottom: '18%', style: { 
        text: '黄金坑', 
        fill: 'transparent',
        stroke: 'rgba(100, 116, 139, 0.12)',
        lineWidth: 0.5,
        fontSize: 14, 
        fontWeight: 500,
        fontFamily: 'Inter, system-ui, sans-serif',
      }},
    ],
    series: [{
      type: 'scatter',
      data: data,
      markArea: {
        silent: true,
        data: quadrantAreas.flatMap(q => q.data.map(d => [{ ...d[0], itemStyle: q.itemStyle }, d[1]])),
      },
      // 极细白色半透明虚线分割
      markLine: {
        silent: true,
        symbol: 'none',
        lineStyle: { 
          color: 'rgba(255, 255, 255, 0.08)', 
          width: 1, 
          type: 'dashed',
        },
        data: [
          { xAxis: xMid, label: { show: false } },
          { yAxis: yMid, label: { show: false } },
        ],
      },
      // 显示所有点的标签 - 纯白对比
      label: {
        show: true,
        position: 'right',
        formatter: '{b}',
        fontSize: 11,
        color: '#FFFFFF',
        distance: 6,
        textBorderColor: 'rgba(10, 10, 15, 0.8)',
        textBorderWidth: 3,
      },
      labelLayout: {
        hideOverlap: true,
        moveOverlap: 'shiftY',
      },
      emphasis: {
        scale: 1.2,
        itemStyle: {
          borderColor: '#FFFFFF',
          borderWidth: 2,
        },
        label: { 
          show: true,
          fontWeight: 600,
        },
      },
    }],
  })
  
  // 点击事件：PULSE 板块弹出警告
  scatterChart.on('click', (params: any) => {
    const point = processedData.find(p => p.name === params.name)
    if (point?.isPulse) {
      selectedPulseSector.value = point.name
      showPulseWarning.value = true
    }
  })
}

// 窗口resize
const handleResize = () => {
  scatterChart?.resize()
}

onMounted(() => {
  if (scatterChartRef.value) {
    scatterChart = echarts.init(scatterChartRef.value)
  }
  loadData()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  scatterChart?.dispose()
})
</script>

<style scoped>
.sector-strategy {
  min-height: 100vh;
  background: var(--bg-base);
  padding: 20px 24px;
  color: var(--text-secondary);
  font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', Roboto, sans-serif;
  box-sizing: border-box;
  transition: background-color var(--transition-normal), color var(--transition-normal);
}

/* 页面头部 */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border-default);
}

.page-title {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
}

.header-info {
  display: flex;
  align-items: center;
  gap: 16px;
}

.trade-date {
  color: var(--text-tertiary);
  font-size: 13px;
}

.refresh-btn {
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 50%;
  background: var(--bg-muted);
  color: var(--text-tertiary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.refresh-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.refresh-btn svg {
  width: 18px;
  height: 18px;
}

.refresh-btn .spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* 上部区块 */
.top-section {
  margin-bottom: 20px;
}

/* 中部区块 */
.middle-section {
  margin-bottom: 20px;
}

/* 区块标题 */
.section-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-tertiary);
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  text-transform: uppercase;
  letter-spacing: 1px;
}

.title-icon {
  color: var(--primary-500);
  font-size: 12px;
}

.subsection-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-tertiary);
  margin: 0 0 10px 0;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

/* 分析面板 */
.analysis-panel {
  background: var(--bg-elevated);
  border: 1px solid var(--border-default);
  border-radius: 12px;
  padding: 20px;
}

/* 主题分类网格布局 */
.theme-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
  margin-top: 16px;
}

/* 诊断文字 */
.diagnosis-section {
  margin-bottom: 20px;
}

.diagnosis-text {
  background: var(--bg-muted);
  border-radius: 8px;
  padding: 16px;
}

.diagnosis-text p {
  margin: 0 0 8px 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-secondary);
}

.diagnosis-text p:last-child {
  margin-bottom: 0;
}

.diagnosis-text p.core {
  color: #00BFA5;
}

.diagnosis-text p.pulse {
  color: #FFAB00;
}

.diagnosis-text p.fading {
  color: #78909C;
}

/* 主题列 */
.theme-column {
  background: var(--bg-muted);
  border-radius: 8px;
  padding: 12px;
}

/* 主题列表 */
.theme-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.theme-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px 14px;
  background: var(--bg-elevated);
  border-radius: 8px;
  border-left: 3px solid transparent;
  transition: all 0.2s;
}

.theme-item:hover {
  background: var(--bg-hover);
}

.theme-item.core {
  border-left-color: #00BFA5;
  animation: breathe-core 3s ease-in-out infinite;
}

@keyframes breathe-core {
  0%, 100% { box-shadow: 0 0 0 0 rgba(0, 191, 165, 0); }
  50% { box-shadow: 0 0 12px 3px rgba(0, 191, 165, 0.2); }
}

.theme-item.pulse {
  border-left-color: #FFAB00;
}

.theme-item.fading {
  border-left-color: #78909C;
}

.theme-main {
  display: flex;
  align-items: center;
  gap: 10px;
}

.theme-sub {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.theme-rank {
  font-size: 12px;
  font-weight: 700;
  color: #00BFA5;
  width: 24px;
}

.theme-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  min-width: 80px;
}

.theme-freq {
  font-size: 12px;
  color: var(--text-tertiary);
  background: var(--bg-subtle);
  padding: 2px 8px;
  border-radius: 10px;
}

.theme-pct {
  font-size: 13px;
  font-weight: 600;
}

.theme-pct.up { color: var(--stock-up); }
.theme-pct.down { color: var(--stock-down); }

.lead-stock {
  font-size: 12px;
  color: #FF8F00;
  background: rgba(255, 143, 0, 0.1);
  padding: 2px 8px;
  border-radius: 4px;
  white-space: nowrap;
}

.empty-hint {
  font-size: 12px;
  color: var(--text-muted);
  padding: 10px;
  text-align: center;
}

/* 散点面板 */
.scatter-panel {
  background: var(--bg-elevated);
  border: 1px solid var(--border-default);
  border-radius: 12px;
  padding: 20px;
}

/* 暗色模式下散点面板采用极深背景 */
:root.dark .scatter-panel {
  background: #0A0A0F;
  border-color: rgba(255, 255, 255, 0.04);
}

.scatter-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.help-btn {
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 50%;
  background: var(--bg-muted);
  color: var(--text-tertiary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.help-btn:hover {
  background: var(--bg-subtle);
  color: var(--primary-500);
}

.scatter-chart {
  width: 100%;
  height: 480px;
  background: var(--bg-secondary);
  border-radius: 12px;
  border: 1px solid var(--border-light);
}

:root.dark .scatter-chart {
  background: linear-gradient(135deg, rgba(15, 23, 42, 0.6), rgba(30, 41, 59, 0.4));
  border-color: rgba(51, 65, 85, 0.3);
}

.zone-legend {
  display: flex;
  justify-content: center;
  gap: 20px;
  margin-top: 16px;
  padding: 10px 16px;
  background: var(--bg-secondary);
  border-radius: 8px;
}

/* 暗色模式 zone-legend 样式 */
:root.dark .zone-legend {
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(255, 255, 255, 0.04);
}

.zone-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 500;
  font-family: 'Inter', system-ui, sans-serif;
  color: var(--text-secondary);
  padding: 4px 10px;
  border-radius: 6px;
  transition: all 0.2s ease;
}

.zone-item:hover {
  background: var(--bg-hover);
}

.zone-item::before {
  content: '';
  width: 10px;
  height: 10px;
  border-radius: 50%;
  box-shadow: 0 0 6px currentColor;
}

/* 与散点图配色保持一致 */
.zone-item.golden { color: #3B82F6; }
.zone-item.golden::before { background: #3B82F6; }

.zone-item.pulse { color: #F59E0B; }
.zone-item.pulse::before { background: #F59E0B; }

.zone-item.resonance { color: #22D3EE; }
.zone-item.resonance::before { background: #22D3EE; }

.zone-item.cold { color: #475569; }
.zone-item.cold::before { background: #475569; }

:root.dark .zone-item.golden { color: #3B82F6; }
:root.dark .zone-item.pulse { color: #F59E0B; }
:root.dark .zone-item.resonance { color: #22D3EE; }
:root.dark .zone-item.cold { color: #64748B; }

/* 教练模式弹窗 */
.guide-dialog-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0,0,0,0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.guide-dialog {
  background: var(--bg-elevated);
  border: 1px solid var(--border-default);
  border-radius: 16px;
  width: 90%;
  max-width: 500px;
  overflow: hidden;
}

.guide-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 24px;
  border-bottom: 1px solid var(--border-light);
}

.guide-header h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
}

.close-btn {
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 50%;
  background: var(--bg-muted);
  color: var(--text-primary);
  font-size: 20px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.close-btn:hover {
  background: var(--bg-subtle);
}

.guide-content {
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.guide-item {
  padding: 16px;
  border-radius: 10px;
  background: var(--bg-muted);
  border-left: 4px solid;
}

.guide-item.golden {
  border-left-color: #FFC107;
}

.guide-item.pulse {
  border-left-color: #FFAB00;
}

.guide-item.resonance {
  border-left-color: #00BFA5;
}

.guide-item.cold {
  border-left-color: #78909C;
}

.guide-zone {
  font-size: 11px;
  color: var(--text-tertiary);
  margin-bottom: 4px;
}

.guide-label {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 6px;
}

.guide-desc {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.5;
}

.guide-desc strong {
  color: var(--stock-up);
}

/* PULSE 警告弹窗 */
.pulse-warning-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0,0,0,0.8);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1001;
}

.pulse-warning-dialog {
  background: var(--bg-elevated);
  border: 2px solid #FFAB00;
  border-radius: 16px;
  padding: 32px;
  text-align: center;
  max-width: 360px;
  animation: shake 0.5s ease-in-out;
}

@keyframes shake {
  0%, 100% { transform: translateX(0); }
  10%, 30%, 50%, 70%, 90% { transform: translateX(-5px); }
  20%, 40%, 60%, 80% { transform: translateX(5px); }
}

.warning-icon {
  font-size: 48px;
  margin-bottom: 16px;
}

.warning-title {
  font-size: 20px;
  font-weight: 700;
  color: #FFAB00;
  margin-bottom: 12px;
}

.warning-sector {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 16px;
}

.warning-desc {
  font-size: 14px;
  color: var(--text-secondary);
  line-height: 1.6;
  margin-bottom: 24px;
}

.warning-close {
  padding: 12px 32px;
  border: none;
  border-radius: 8px;
  background: #FFAB00;
  color: #000;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.warning-close:hover {
  background: #FFC107;
}

/* 表格区域 */
.table-section {
  background: var(--bg-elevated);
  border: 1px solid var(--border-default);
  border-radius: 12px;
  padding: 20px;
}

.table-wrapper {
  width: 100%;
  overflow-x: auto;
}

.sector-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.sector-table th {
  padding: 12px 16px;
  background: var(--bg-muted);
  color: var(--text-tertiary);
  font-weight: 600;
  text-align: left;
  border-bottom: 1px solid var(--border-light);
  white-space: nowrap;
  text-transform: uppercase;
  font-size: 11px;
  letter-spacing: 0.5px;
}

.sector-table td {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-light);
  color: var(--text-secondary);
}

.sector-row:hover {
  background: var(--bg-hover);
}

.sector-row.core {
  background: rgba(0, 191, 165, 0.04);
}

.sector-row.pulse {
  background: rgba(255, 171, 0, 0.04);
}

.sector-row.fading {
  background: rgba(120, 144, 156, 0.04);
}

.rank-col {
  font-weight: 700;
  color: var(--primary-500);
  width: 60px;
}

.name-col {
  font-weight: 600;
  color: var(--text-primary);
}

.lead-col {
  color: #FF8F00;
  font-size: 12px;
  max-width: 120px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.freq-col {
  color: var(--text-muted);
}

.strength-col {
  font-weight: 600;
}

.strength-col.up { color: var(--stock-up); }
.strength-col.down { color: var(--stock-down); }

.category-tag {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.5px;
}

.category-tag.core {
  background: rgba(0, 191, 165, 0.15);
  color: #00BFA5;
}

.category-tag.pulse {
  background: rgba(255, 171, 0, 0.15);
  color: #FFAB00;
}

.category-tag.fading {
  background: rgba(120, 144, 156, 0.15);
  color: #78909C;
}

.category-tag.active {
  background: rgba(66, 165, 245, 0.15);
  color: #42A5F5;
}

.category-tag.normal {
  background: var(--bg-muted);
  color: var(--text-tertiary);
}

.reason-col {
  font-size: 11px;
  color: var(--text-tertiary);
}

/* 响应式 - 全屏适配 */
@media (max-width: 1400px) {
  .theme-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 1024px) {
  .theme-grid {
    grid-template-columns: 1fr;
  }
  
  .scatter-chart {
    height: 320px;
  }
}

@media (max-width: 768px) {
  .sector-strategy {
    padding: 16px;
  }
  
  .page-title {
    font-size: 18px;
  }
  
  .scatter-chart {
    height: 280px;
  }
  
  .zone-legend {
    flex-wrap: wrap;
    gap: 12px;
  }
}
</style>
