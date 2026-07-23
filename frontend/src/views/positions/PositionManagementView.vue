<script setup lang="ts">
/**
 * PositionManagementView - 持仓管理
 *
 * 全局持仓视图: 日期切换 + 汇总卡片 + 仓位趋势组合图 + 持仓表格
 * 当天: 5秒自动刷新实时数据
 * 历史日: 从交易归档获取快照
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { usePositionManagement } from './usePositionManagement'
import PositionSystemPanel from './PositionSystemPanel.vue'
import { ElTable, ElTableColumn, ElTag, ElButton, ElSelect, ElOption, ElSwitch, ElDatePicker } from 'element-plus'
import { getChinaDate } from '@/utils/chinaDate'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, BarChart } from 'echarts/charts'
import { TooltipComponent, GridComponent, LegendComponent, MarkLineComponent } from 'echarts/components'
use([CanvasRenderer, LineChart, BarChart, TooltipComponent, GridComponent, LegendComponent, MarkLineComponent])

const {
  date, today, isToday, loading, error,
  account, sentiment, tradeStats, circuitBreaker,
  sortKey, sortAsc,
  totalMarketValue, totalCost, totalProfit, totalProfitPct,
  positionRatio, positionCount,
  profitCount, lossCount,
  riskDistribution, strategyDistribution,
  sortedPositions,
  equityHistory, currentEquity,
  autoRefresh,
  fetchAll, onDateChange, startAutoRefresh, stopAutoRefresh,
} = usePositionManagement()

function onAutoRefreshChange(val: boolean) {
  if (val && isToday.value) startAutoRefresh()
  else stopAutoRefresh()
}

// ===== 工具函数 =====
function fmtMoney(v: number | undefined): string {
  if (v == null || isNaN(v)) return '-'
  const abs = Math.abs(v)
  if (abs >= 1e8) return (v / 1e8).toFixed(2) + '亿'
  if (abs >= 1e4) return (v / 1e4).toFixed(1) + '万'
  return v.toFixed(0)
}
function fmtPrice(v: number | undefined): string {
  if (v == null || isNaN(v)) return '-'
  return v.toFixed(2)
}
function fmtSignedPct(v: number | undefined): string {
  if (v == null || isNaN(v)) return '-'
  return (v >= 0 ? '+' : '') + v.toFixed(2) + '%'
}
function fmtSignedMoney(v: number | undefined): string {
  if (v == null || isNaN(v)) return '-'
  return (v >= 0 ? '+' : '') + fmtMoney(v)
}
function strategyCN(s: string): string {
  const map: Record<string, string> = {
    halfway_chase: '半路追涨', first_limit_up: '首板打板', broken_board: '炸板反包',
    dragon_head: '龙头追涨', pry_board: '翘板反抽',
  }
  return map[s] || s
}
function riskLabel(lvl: string): string {
  return { high: '🔴高风险', elevated: '🟡较高', normal: '🟢正常', low: '🟢低风险' }[lvl] || lvl
}
function periodCN(period: string): string {
  const map: Record<string, string> = { rising: '高潮', differentiation: '分化', chaos: '震荡', bearish: '冰点' }
  return map[period] || period
}
function periodColor(period: string): string {
  return { rising: '#f23645', differentiation: '#e6a23c', chaos: '#409eff', bearish: '#089981' }[period] || '#888'
}

// 风控回撤cap
const drawdownPct = computed(() => {
  const dd = circuitBreaker?.value?.cumulative_drawdown ?? 0
  return (dd * 100).toFixed(1)
})
const drawdownCapValue = computed(() => {
  const cap = circuitBreaker?.value?.position_cap ?? 1.0
  return cap >= 1.0 ? '100%' : `${(cap * 100).toFixed(0)}%`
})
const drawdownCapLabel = computed(() => {
  const cap = circuitBreaker?.value?.position_cap ?? 1.0
  if (cap <= 0) return '禁止买入'
  if (cap <= 0.25) return '1/4仓'
  if (cap <= 0.5) return '半仓'
  if (cap < 1.0) return '限仓'
  return '正常'
})
const drawdownCapClass = computed(() => {
  const cap = circuitBreaker?.value?.position_cap ?? 1.0
  if (cap <= 0) return 'down'
  if (cap <= 0.25) return 'down'
  if (cap <= 0.5) return 'warn'
  return 'up'
})
function holdDays(buyDate: string): number {
  if (!buyDate) return 0
  const d = new Date(buyDate.slice(0, 4) + '-' + buyDate.slice(4, 6) + '-' + buyDate.slice(6, 8))
  return Math.floor((Date.now() - d.getTime()) / 86400000)
}
function posRowClass({ row }: { row: any }): string {
  if ((row.profit_pct || 0) >= 0) return 'row-profit'
  return 'row-loss'
}
function handleRefresh() { fetchAll() }

const dateShortcuts = [{ text: '今天', value: new Date() }]

// ===== 仓位趋势: 每日节点, 默认显示2周 =====
const trendWindow = ref(10) // 默认显示10个交易日(约2周)
const trendOffset = ref(0) // 从末尾偏移, 0=最新

const trendChartOption = computed(() => {
  const raw = equityHistory.value
  if (!raw.length) return {}

  // 截取窗口
  const endIdx = raw.length - trendOffset.value
  const startIdx = Math.max(0, endIdx - trendWindow.value)
  const data = raw.slice(startIdx, endIdx)

  const labels = data.map(d => {
    const s = String(d.date)
    return `${s.slice(4,6)}/${s.slice(6,8)}`
  })
  const months = data.map(d => String(d.date).slice(0,6))
  const selectedDateStr = date.value.replace(/-/g, '')
  const selectedIdx = data.findIndex(d => String(d.date) === selectedDateStr)

  // 月份分隔
  const monthBoundaries: number[] = []
  for (let i = 1; i < months.length; i++) {
    if (months[i] !== months[i-1]) monthBoundaries.push(i)
  }

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross', crossStyle: { color: '#555' } },
      formatter: (params: any) => {
        const idx = params[0]?.dataIndex ?? 0
        const d = data[idx]
        if (!d) return ''
        const pnl = d.daily_pnl || 0
        const pnlColor = pnl >= 0 ? '#f23645' : '#089981'
        return `<div style="font-size:12px;line-height:1.6">
          <b>${labels[idx]}</b><br/>
          <span style="color:#a855f7">资产 ¥${fmtMoney(d.total_assets)}</span><br/>
          <span style="color:#409eff">仓位 ${(d.position_ratio * 100).toFixed(1)}% · ${d.position_count}只</span><br/>
          <span style="color:${pnlColor}">当日盈亏 ${fmtSignedMoney(pnl)}</span><br/>
          <span style="color:#888">净值 ${d.net_value.toFixed(3)} · 回撤 ${(d.drawdown_pct * 100).toFixed(1)}%</span><br/>
          <span style="color:#666">买${d.buys || 0}笔 卖${d.sells || 0}笔</span>
        </div>`
      },
    },
    legend: {
      data: ['仓位%', '持仓数', '日盈亏', '资产'],
      top: 0, right: 10, textStyle: { fontSize: 10, color: '#888' }, itemWidth: 12, itemHeight: 8,
    },
    grid: { left: 40, right: 45, top: 28, bottom: 30 },
    xAxis: {
      type: 'category', data: labels,
      axisLabel: {
        fontSize: 10, color: '#888',
        formatter: (val: string, i: number) => {
          if (i === 0 || months[i] !== months[i-1]) return months[i].slice(2) + '\n' + val
          return val
        },
      },
      axisLine: { lineStyle: { color: '#333' } },
      splitLine: {
        show: true,
        interval: (index: number) => monthBoundaries.includes(index),
        lineStyle: { color: '#333', type: 'solid', width: 1 },
      },
    },
    yAxis: [
      { type: 'value', name: '仓位%', position: 'left', min: 0, max: 100,
        axisLabel: { fontSize: 9, color: '#409eff', formatter: '{value}%' },
        splitLine: { lineStyle: { color: '#1a1a2e', type: 'dashed' } },
        nameTextStyle: { fontSize: 9, color: '#409eff' },
      },
      { type: 'value', name: '盈亏', position: 'right',
        axisLabel: { fontSize: 9, color: '#888', formatter: (v: number) => fmtMoney(v) },
        splitLine: { show: false },
        nameTextStyle: { fontSize: 9, color: '#888' },
      },
    ],
    series: [
      // 1. 仓位比例 - 渐变面积
      {
        name: '仓位%', type: 'line', data: data.map(d => +(d.position_ratio * 100).toFixed(1)),
        yAxisIndex: 0, smooth: 0.2, symbol: 'circle', symbolSize: 6,
        lineStyle: { width: 2, color: '#409eff' },
        itemStyle: { color: '#409eff' },
        areaStyle: {
          color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(64,158,255,0.3)' },
              { offset: 1, color: 'rgba(64,158,255,0.02)' },
            ],
          },
        },
        markLine: selectedIdx >= 0 ? {
          silent: true, symbol: 'none',
          data: [{ xAxis: selectedIdx }],
          lineStyle: { color: '#f56c6c', type: 'solid', width: 1.5 },
          label: { show: false },
        } : undefined,
      },
      // 2. 持仓数 - 柱状
      {
        name: '持仓数', type: 'bar', data: data.map(d => d.position_count || 0),
        yAxisIndex: 0, barWidth: '30%',
        itemStyle: {
          color: (params: any) => {
            const d = data[params.dataIndex]
            return d && (d.position_count || 0) >= 8 ? '#f56c6c' : d && (d.position_count || 0) >= 6 ? '#e6a23c' : '#67c23a'
          },
          borderRadius: [2, 2, 0, 0],
        },
      },
      // 3. 日盈亏 - 红绿柱
      {
        name: '日盈亏', type: 'bar', data: data.map(d => d.daily_pnl || 0),
        yAxisIndex: 1, barWidth: '30%',
        itemStyle: {
          color: (params: any) => params.value >= 0 ? 'rgba(242,54,69,0.8)' : 'rgba(8,153,129,0.8)',
          borderRadius: [2, 2, 0, 0],
        },
      },
      // 4. 总资产 - 紫线带菱形点
      {
        name: '资产', type: 'line', data: data.map(d => d.total_assets),
        yAxisIndex: 1, smooth: 0.3, symbol: 'diamond', symbolSize: 6,
        lineStyle: { width: 1.5, color: '#a855f7' },
        itemStyle: { color: '#a855f7' },
      },
    ],
  }
})

// 翻页
function trendPrev() {
  const maxOffset = equityHistory.value.length - trendWindow.value
  if (trendOffset.value < maxOffset) trendOffset.value += trendWindow.value
}
function trendNext() {
  if (trendOffset.value > 0) trendOffset.value = Math.max(0, trendOffset.value - trendWindow.value)
}
function trendLatest() {
  trendOffset.value = 0
}
const trendRangeLabel = computed(() => {
  const raw = equityHistory.value
  if (!raw.length) return ''
  const endIdx = raw.length - trendOffset.value
  const startIdx = Math.max(0, endIdx - trendWindow.value)
  const s = String(raw[startIdx]?.date || '')
  const e = String(raw[endIdx - 1]?.date || '')
  return `${s} ~ ${e}`
})
const canPrev = computed(() => trendOffset.value < equityHistory.value.length - trendWindow.value)
const canNext = computed(() => trendOffset.value > 0)

// ===== 汇总指标条 =====
const recentStats = computed(() => {
  const data = equityHistory.value
  if (data.length < 2) return null
  const latest = data[data.length - 1]
  const prev = data[data.length - 2]
  const assetChange = latest.total_assets - prev.total_assets
  const assetChangePct = prev.total_assets > 0 ? (assetChange / prev.total_assets * 100) : 0
  return {
    assetChange,
    assetChangePct,
    latestPnl: latest.daily_pnl || 0,
    maxAssets: Math.max(...data.map(d => d.total_assets)),
    minAssets: Math.min(...data.map(d => d.total_assets)),
    avgPosition: data.reduce((s, d) => s + d.position_ratio, 0) / data.length,
    totalDays: data.length,
    profitDays: data.filter(d => (d.daily_pnl || 0) > 0).length,
    lossDays: data.filter(d => (d.daily_pnl || 0) < 0).length,
    maxDrawdown: Math.min(...data.map(d => d.drawdown_pct)),
  }
})
</script>

<template>
  <div class="pm-page">
    <!-- 顶部工具栏 -->
    <div class="pm-toolbar">
      <div class="pm-toolbar-left">
        <h2>📊 持仓管理</h2>
        <ElDatePicker
          v-model="date" type="date" size="small"
          format="YYYY-MM-DD" value-format="YYYY-MM-DD"
          :clearable="false" :shortcuts="dateShortcuts"
          @change="onDateChange" style="width: 130px"
        />
        <ElTag v-if="isToday" size="small" type="success">实时</ElTag>
        <ElTag v-else size="small" type="info">历史快照</ElTag>
        <ElTag v-if="loading" size="small" type="warning">加载中...</ElTag>
      </div>
      <div class="pm-toolbar-right">
        <template v-if="isToday">
          <span class="pm-auto-label">自动刷新</span>
          <ElSwitch v-model="autoRefresh" size="small" @change="onAutoRefreshChange" />
        </template>
        <ElButton size="small" @click="handleRefresh" :loading="loading">刷新</ElButton>
      </div>
    </div>

    <!-- 汇总卡片 -->
    <div class="pm-summary-grid">
      <div class="pm-card pm-card-assets">
        <div class="pm-card-label">总资产</div>
        <div class="pm-card-value">¥{{ fmtMoney(account?.total_assets) }}</div>
        <div class="pm-card-sub">
          <span>现金 ¥{{ fmtMoney(account?.available_cash) }}</span>
          <span>市值 ¥{{ fmtMoney(totalMarketValue) }}</span>
        </div>
      </div>
      <div class="pm-card pm-card-ratio">
        <div class="pm-card-label">仓位比例</div>
        <div class="pm-card-value">{{ positionRatio }}%</div>
        <div class="pm-card-sub">
          <span>{{ positionCount }}/{{ tradeStats?.max_positions || 8 }}只</span>
          <span v-if="sentiment" :style="{color: periodColor(sentiment.period)}">
            {{ periodCN(sentiment.period) }}{{ sentiment.score.toFixed(0) }}
          </span>
        </div>
      </div>
      <div class="pm-card pm-card-pnl">
        <div class="pm-card-label">持仓盈亏</div>
        <div class="pm-card-value" :class="totalProfit >= 0 ? 'up' : 'down'">
          {{ fmtSignedMoney(totalProfit) }}
        </div>
        <div class="pm-card-sub" :class="totalProfitPct >= 0 ? 'up' : 'down'">
          {{ fmtSignedPct(totalProfitPct) }}
        </div>
      </div>
      <div class="pm-card pm-card-dist">
        <div class="pm-card-label">盈亏分布</div>
        <div class="pm-card-value">
          <span class="up">{{ profitCount }}盈</span>
          <span class="pm-sep">/</span>
          <span class="down">{{ lossCount }}亏</span>
        </div>
        <div class="pm-card-sub">
          <span v-if="riskDistribution.high" class="risk-high">🔴{{ riskDistribution.high }}</span>
          <span v-if="riskDistribution.elevated" class="risk-elevated">🟡{{ riskDistribution.elevated }}</span>
          <span class="risk-normal">🟢{{ riskDistribution.normal }}</span>
        </div>
      </div>
    </div>

    <!-- 仓位决策上下文 -->
    <div v-if="isToday && sentiment" class="pm-context-bar">
      <div class="pm-ctx-item">
        <span class="pm-ctx-label">情绪周期</span>
        <span class="pm-ctx-val" :style="{color: periodColor(sentiment.period)}">
          {{ periodCN(sentiment.period) }} · {{ sentiment.score.toFixed(0) }}分
        </span>
      </div>
      <div class="pm-ctx-sep"></div>
      <div class="pm-ctx-item">
        <span class="pm-ctx-label">持仓上限</span>
        <span class="pm-ctx-val">{{ tradeStats?.max_positions || 8 }}只</span>
        <span class="pm-ctx-hint">{{ positionCount }}/{{ tradeStats?.max_positions || 8 }}已用</span>
      </div>
      <div class="pm-ctx-sep"></div>
      <div class="pm-ctx-item">
        <span class="pm-ctx-label">总资产</span>
        <span class="pm-ctx-val">¥{{ fmtMoney(account?.total_assets) }}</span>
        <span class="pm-ctx-hint">现金¥{{ fmtMoney(account?.available_cash) }}</span>
      </div>
      <div class="pm-ctx-sep"></div>
      <div class="pm-ctx-item">
        <span class="pm-ctx-label">单票仓位</span>
        <span class="pm-ctx-val">≤35%</span>
        <span class="pm-ctx-hint">半路追涨35% / 龙头15%</span>
      </div>
      <div class="pm-ctx-sep"></div>
      <div class="pm-ctx-item">
        <span class="pm-ctx-label">回撤cap</span>
        <span class="pm-ctx-val" :class="drawdownCapClass">{{ drawdownCapLabel }}</span>
        <span class="pm-ctx-hint">回撤{{ drawdownPct }}% -> cap{{ drawdownCapValue }}</span>
      </div>
      <div class="pm-ctx-sep"></div>
      <div class="pm-ctx-item">
        <span class="pm-ctx-label">总仓位上限</span>
        <span class="pm-ctx-val">70%</span>
        <span class="pm-ctx-hint">当前{{ positionRatio }}%</span>
      </div>
    </div>

    <!-- 仓位趋势组合图 + 统计指标 -->
    <div v-if="equityHistory.length" class="pm-trend-section">
      <div class="pm-trend-header">
        <span class="pm-trend-title">仓位趋势</span>
        <div class="pm-trend-nav">
          <ElButton size="small" text :disabled="!canPrev" @click="trendPrev">← 更早</ElButton>
          <span class="pm-trend-range">{{ trendRangeLabel }}</span>
          <ElButton size="small" text :disabled="!canNext" @click="trendNext">更新 →</ElButton>
          <ElButton size="small" text :disabled="trendOffset === 0" @click="trendLatest">最新</ElButton>
        </div>
        <div v-if="recentStats" class="pm-trend-stats">
          <span class="pm-stat-item">
            <span class="pm-stat-label">日胜率</span>
            <span class="pm-stat-val" :class="recentStats.profitDays >= recentStats.lossDays ? 'up' : 'down'">
              {{ recentStats.profitDays }}/{{ recentStats.profitDays + recentStats.lossDays }}
            </span>
          </span>
          <span class="pm-stat-item">
            <span class="pm-stat-label">最大回撤</span>
            <span class="pm-stat-val down">{{ (recentStats.maxDrawdown * 100).toFixed(1) }}%</span>
          </span>
          <span class="pm-stat-item">
            <span class="pm-stat-label">平均仓位</span>
            <span class="pm-stat-val">{{ (recentStats.avgPosition * 100).toFixed(1) }}%</span>
          </span>
        </div>
      </div>
      <VChart :option="trendChartOption" autoresize style="height: 220px; width: 100%" />
    </div>

    <!-- 策略分布 -->
    <div v-if="strategyDistribution.length" class="pm-strategy-bar">
      <span class="pm-sb-label">策略分布:</span>
      <div class="pm-sb-items">
        <div v-for="s in strategyDistribution" :key="s.name" class="pm-sb-item">
          <span class="pm-sb-name">{{ strategyCN(s.name) }}</span>
          <span class="pm-sb-count">{{ s.count }}只</span>
          <span class="pm-sb-mv">¥{{ fmtMoney(s.mv) }}</span>
          <span class="pm-sb-profit" :class="s.profit >= 0 ? 'up' : 'down'">{{ fmtSignedMoney(s.profit) }}</span>
        </div>
      </div>
    </div>

    <!-- 持仓表格 -->
    <div class="pm-table-wrap">
      <div class="pm-table-header">
        <span class="pm-th-title">
          持仓明细
          <span v-if="!isToday" class="pm-historical-note">（{{ date }} 历史快照，无实时价格）</span>
        </span>
        <div class="pm-th-sort">
          <ElSelect v-model="sortKey" size="small" style="width:100px">
            <ElOption label="按盈亏" value="profit" />
            <ElOption label="按市值" value="market_value" />
            <ElOption label="按成本" value="cost" />
            <ElOption label="按风险" value="risk" />
          </ElSelect>
          <ElButton size="small" @click="sortAsc = !sortAsc">{{ sortAsc ? '↑升序' : '↓降序' }}</ElButton>
        </div>
      </div>
      <ElTable :data="sortedPositions" size="small" stripe :row-class-name="posRowClass" class="pm-table" :max-height="500">
        <ElTableColumn prop="ts_code" label="代码" width="110" fixed />
        <ElTableColumn prop="stock_name" label="名称" width="90" fixed />
        <ElTableColumn label="策略" width="90">
          <template #default="{ row }">
            <ElTag size="small" effect="plain">{{ strategyCN(row.strategy) }}</ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn prop="shares" label="数量" width="70" align="right" />
        <ElTableColumn label="成本价" width="80" align="right">
          <template #default="{ row }">{{ fmtPrice(row.cost_price) }}</template>
        </ElTableColumn>
        <ElTableColumn label="现价" width="80" align="right">
          <template #default="{ row }">{{ row.current_price ? fmtPrice(row.current_price) : '-' }}</template>
        </ElTableColumn>
        <ElTableColumn label="市值" width="100" align="right">
          <template #default="{ row }">{{ row.market_value ? '¥' + fmtMoney(row.market_value) : '-' }}</template>
        </ElTableColumn>
        <ElTableColumn label="盈亏%" width="90" align="right">
          <template #default="{ row }">
            <span v-if="row.profit_pct != null" :class="(row.profit_pct || 0) >= 0 ? 'up' : 'down'" class="pm-pct">
              {{ fmtSignedPct(row.profit_pct) }}
            </span>
            <span v-else class="pm-na">-</span>
          </template>
        </ElTableColumn>
        <ElTableColumn label="盈亏额" width="100" align="right">
          <template #default="{ row }">
            <span v-if="row.profit_amount != null" :class="(row.profit_amount || 0) >= 0 ? 'up' : 'down'">
              {{ fmtSignedMoney(row.profit_amount) }}
            </span>
            <span v-else class="pm-na">-</span>
          </template>
        </ElTableColumn>
        <ElTableColumn label="止损价" width="85" align="right">
          <template #default="{ row }">
            <span v-if="row.stop_loss_price" class="pm-sl">{{ fmtPrice(row.stop_loss_price) }}</span>
            <span v-else class="pm-na">-</span>
          </template>
        </ElTableColumn>
        <ElTableColumn label="止盈价" width="85" align="right">
          <template #default="{ row }">
            <span v-if="row.take_profit_price" class="pm-tp">{{ fmtPrice(row.take_profit_price) }}</span>
            <span v-else class="pm-na">-</span>
          </template>
        </ElTableColumn>
        <ElTableColumn label="追踪止损" width="120">
          <template #default="{ row }">
            <ElTag v-if="row.trailing_stop?.activated" size="small" type="warning">
              📍{{ (row.trailing_stop.trailing_stop_pct * 100).toFixed(0) }}%
            </ElTag>
            <span v-else class="pm-na">-</span>
          </template>
        </ElTableColumn>
        <ElTableColumn label="风险" width="80" align="center">
          <template #default="{ row }">
            <span :class="'risk-' + (row.risk_level || 'normal')">{{ riskLabel(row.risk_level) }}</span>
          </template>
        </ElTableColumn>
        <ElTableColumn label="持有天数" width="80" align="right">
          <template #default="{ row }">{{ holdDays(row.buy_date) }}天</template>
        </ElTableColumn>
        <ElTableColumn label="买入日期" width="110">
          <template #default="{ row }">
            <span class="pm-buy-date">{{ row.buy_date }}</span>
            <span v-if="row.buy_time" class="pm-buy-time">{{ row.buy_time }}</span>
          </template>
        </ElTableColumn>
        <ElTableColumn v-if="isToday" label="T+1" width="55" align="center">
          <template #default="{ row }">
            <ElTag v-if="row.today_buy > 0" size="small" type="warning">T+1</ElTag>
            <span v-else class="pm-na">-</span>
          </template>
        </ElTableColumn>
      </ElTable>
      <div v-if="!sortedPositions.length && !loading" class="pm-empty">
        {{ isToday ? '暂无持仓' : '该日无持仓' }}
      </div>
    </div>

    <!-- 仓位系统设计面板 -->
    <PositionSystemPanel
      :sentiment="sentiment"
      :circuit-breaker="circuitBreaker"
      :account="account"
      :position-count="positionCount"
      :position-ratio="positionRatio"
    />
  </div>
</template>

<style scoped>
.pm-page { padding: 16px; }

.pm-toolbar {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 16px; flex-wrap: wrap; gap: 8px;
}
.pm-toolbar-left { display: flex; align-items: center; gap: 12px; }
.pm-toolbar-left h2 { margin: 0; font-size: 18px; font-weight: 700; }
.pm-toolbar-right { display: flex; align-items: center; gap: 8px; }
.pm-auto-label { font-size: 12px; color: var(--text-secondary); }

/* 汇总卡片 */
.pm-summary-grid {
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px;
  margin-bottom: 12px;
}
@media (max-width: 768px) { .pm-summary-grid { grid-template-columns: repeat(2, 1fr); } }

.pm-card {
  background: var(--bg-elevated); border: 1px solid var(--border-default);
  border-radius: 10px; padding: 12px 16px; min-width: 0;
}
.pm-card-label { font-size: 12px; color: var(--text-secondary); margin-bottom: 4px; }
.pm-card-value { font-size: 22px; font-weight: 700; line-height: 1.2; }
.pm-card-sub { font-size: 12px; color: var(--text-tertiary); margin-top: 4px; display: flex; gap: 12px; }

.pm-card-assets .pm-card-value { color: var(--el-color-primary); }
.pm-card-ratio .pm-card-value { color: var(--el-color-warning); }
.pm-card-pnl .pm-card-value.up { color: #f23645; }
.pm-card-pnl .pm-card-value.down { color: #089981; }
.pm-card-dist .pm-card-value { font-size: 18px; display: flex; align-items: center; gap: 4px; }
.pm-sep { color: var(--text-quaternary); margin: 0 2px; }

/* 仓位趋势 */
.pm-context-bar {
  display: flex; align-items: center; gap: 0; margin-bottom: 12px;
  padding: 10px 16px; background: var(--bg-elevated); border-radius: 10px;
  border: 1px solid var(--border-default); flex-wrap: wrap;
}
.pm-ctx-item { display: flex; flex-direction: column; gap: 2px; padding: 0 14px; }
.pm-ctx-label { font-size: 11px; color: var(--text-tertiary); }
.pm-ctx-val { font-size: 14px; font-weight: 600; }
.pm-ctx-hint { font-size: 10px; color: var(--text-quaternary); }
.pm-ctx-sep { width: 1px; height: 32px; background: var(--border-default); }

.pm-trend-section {
  background: var(--bg-elevated); border: 1px solid var(--border-default);
  border-radius: 10px; padding: 10px 14px 6px; margin-bottom: 12px;
}
.pm-trend-header {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 4px; flex-wrap: wrap; gap: 8px;
}
.pm-trend-title { font-size: 13px; font-weight: 600; }
.pm-trend-nav { display: flex; align-items: center; gap: 4px; }
.pm-trend-range { font-size: 11px; color: var(--text-tertiary); min-width: 130px; text-align: center; }
.pm-trend-stats { display: flex; gap: 16px; flex-wrap: wrap; }
.pm-stat-item { display: flex; align-items: center; gap: 4px; font-size: 11px; }
.pm-stat-label { color: var(--text-tertiary); }
.pm-stat-val { font-weight: 600; }

/* 策略分布 */
.pm-strategy-bar {
  display: flex; align-items: center; gap: 10px; margin-bottom: 12px;
  padding: 8px 14px; background: var(--bg-elevated); border-radius: 8px;
  border: 1px solid var(--border-default); flex-wrap: wrap;
}
.pm-sb-label { font-size: 12px; color: var(--text-secondary); white-space: nowrap; }
.pm-sb-items { display: flex; gap: 16px; flex-wrap: wrap; }
.pm-sb-item { display: flex; align-items: center; gap: 6px; font-size: 12px; }
.pm-sb-name { font-weight: 600; }
.pm-sb-count { color: var(--text-tertiary); }
.pm-sb-mv { color: var(--text-secondary); }
.pm-sb-profit { font-weight: 600; }

/* 表格 */
.pm-table-wrap {
  background: var(--bg-elevated); border: 1px solid var(--border-default);
  border-radius: 10px; overflow: hidden;
}
.pm-table-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 14px; border-bottom: 1px solid var(--border-default);
}
.pm-th-title { font-weight: 600; font-size: 14px; }
.pm-historical-note { font-size: 12px; color: var(--text-tertiary); font-weight: 400; }
.pm-th-sort { display: flex; gap: 6px; }
.pm-table { width: 100%; }

:deep(.row-profit) { background: rgba(242, 54, 69, 0.04) !important; }
:deep(.row-loss) { background: rgba(8, 153, 129, 0.04) !important; }

.up { color: #f23645; }
.down { color: #089981; }
.pm-sl { color: #089981; }
.pm-tp { color: #f23645; }
.pm-pct { font-weight: 600; }
.pm-na { color: var(--text-quaternary); }
.pm-buy-date { font-size: 12px; }
.pm-buy-time { font-size: 11px; color: var(--text-tertiary); margin-left: 4px; }
.risk-high { color: #f23645; }
.risk-elevated { color: #e6a23c; }
.risk-normal { color: #67c23a; }
.pm-empty { text-align: center; padding: 40px; color: var(--text-tertiary); font-size: 14px; }
</style>
