<script setup lang="ts">
/**
 * BacktestResultPanel - 超短回测结果展示面板
 * 包含净值曲线、回撤、日收益、仓位、策略对比、雷达图、因子贡献、月度收益、风险指标、交易记录
 */
import { ref, computed } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, BarChart, PieChart, RadarChart } from 'echarts/charts'
import {
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  GridComponent,
  DataZoomComponent
} from 'echarts/components'
import VChart from 'vue-echarts'
import {
  ElCard,
  ElTable,
  ElTableColumn,
  ElTabs,
  ElTabPane,
  ElButton,
  ElInput,
  ElSelect,
  ElOption,
  ElEmpty,
  ElMessage,
} from 'element-plus'
import { Download } from '@element-plus/icons-vue'

use([CanvasRenderer, LineChart, BarChart, PieChart, RadarChart, TitleComponent, TooltipComponent, LegendComponent, GridComponent, DataZoomComponent])

const props = defineProps<{
  result: any
  form: any
}>()

// 筛选变量
const searchTradeKeyword = ref('')
const filterStrategy = ref('')
const filterProfit = ref('')

// 筛选后的交易记录
const filteredTrades = computed(() => {
  let trades = props.result?.trades || []
  if (searchTradeKeyword.value) {
    const keyword = searchTradeKeyword.value.toLowerCase()
    trades = trades.filter((t: any) =>
      t.ts_code.toLowerCase().includes(keyword) ||
      t.stock_name.toLowerCase().includes(keyword)
    )
  }
  if (filterStrategy.value) {
    trades = trades.filter((t: any) => t.strategy === props.form.strategyConfigs[filterStrategy.value as keyof typeof props.form.strategyConfigs]?.name)
  }
  if (filterProfit.value) {
    trades = trades.filter((t: any) => filterProfit.value === 'profit' ? t.profit_pct >= 0 : t.profit_pct < 0)
  }
  return trades
})

// 盈亏TOP5
const profitTop5 = computed(() => {
  const trades = [...(props.result?.trades || [])].filter((t: any) => t.profit_pct > 0)
  return trades.sort((a: any, b: any) => b.profit_pct - a.profit_pct).slice(0, 5)
})

const lossTop5 = computed(() => {
  const trades = [...(props.result?.trades || [])].filter((t: any) => t.profit_pct < 0)
  return trades.sort((a: any, b: any) => a.profit_pct - b.profit_pct).slice(0, 5)
})

// 图表配置
const netValueChartOption = computed(() => {
  const result = props.result
  if (!result?.net_value_series) return {}
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['净值曲线', '回撤'] },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', boundaryGap: false, data: result.net_value_series.map((d: any) => d.date) },
    yAxis: [
      { type: 'value', name: '净值', position: 'left' },
      { type: 'value', name: '回撤', position: 'right', axisLabel: { formatter: '{value}%' } }
    ],
    series: [
      { name: '净值曲线', type: 'line', data: result.net_value_series.map((d: any) => d.value), smooth: true },
      { name: '回撤', type: 'line', yAxisIndex: 1, data: result.drawdown_series.map((d: any) => (d.value * 100).toFixed(2)), color: '#f56c6c' }
    ]
  }
})

const dailyProfitChartOption = computed(() => {
  const result = props.result
  if (!result?.daily_profit) return {}
  return {
    tooltip: { trigger: 'axis', formatter: '{b}<br/>当日盈亏：{c}%' },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', data: Object.keys(result.daily_profit) },
    yAxis: { type: 'value', axisLabel: { formatter: '{value}%' } },
    series: [
      { type: 'bar', data: Object.values(result.daily_profit).map((v: any) => (v * 100).toFixed(2)),
        itemStyle: { color: (params: any) => params.value >= 0 ? '#67c23a' : '#f56c6c' }
      }
    ]
  }
})

const positionChartOption = computed(() => {
  const result = props.result
  if (!result?.position_series) return {}
  return {
    tooltip: { trigger: 'axis', formatter: '{b}<br/>仓位：{c}%' },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', boundaryGap: false, data: result.position_series.map((d: any) => d.date) },
    yAxis: { type: 'value', axisLabel: { formatter: '{value}%' } },
    series: [
      { name: '仓位', type: 'line', data: result.position_series.map((d: any) => (d.value * 100).toFixed(2)), areaStyle: {} }
    ]
  }
})

const strategyCompareChartOption = computed(() => {
  const result = props.result
  if (!result?.strategy_results) return {}
  const strategies = Object.values(result.strategy_results) as any[]
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: strategies.map(s => s.strategy_name) },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', boundaryGap: false, data: result.net_value_series?.map((d: any) => d.date) || [] },
    yAxis: { type: 'value' },
    series: strategies.map(s => ({
      name: s.strategy_name,
      type: 'line',
      data: s.net_value_series?.map((d: any) => d.value) || [],
      smooth: true
    }))
  }
})

const radarChartOption = computed(() => {
  const result = props.result
  if (!result?.strategy_results) return {}
  const strategies = Object.values(result.strategy_results) as any[]
  return {
    tooltip: { trigger: 'item' },
    legend: { data: strategies.map(s => s.strategy_name) },
    radar: {
      indicator: [
        { name: '收益率', max: 200 }, { name: '胜率', max: 100 },
        { name: '盈亏比', max: 5 }, { name: '夏普比率', max: 5 }, { name: '最大回撤', max: 100 }
      ]
    },
    series: [
      { type: 'radar', data: strategies.map(s => ({
        name: s.strategy_name,
        value: [(s.total_return * 100).toFixed(2), (s.win_rate * 100).toFixed(2), s.profit_loss_ratio.toFixed(2), s.sharpe_ratio.toFixed(2), (100 - s.max_drawdown * 100).toFixed(2)]
      }))}
    ]
  }
})

const factorContributionChartOption = computed(() => {
  const result = props.result
  if (!result?.factor_contribution) return {}
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c}%' },
    series: [
      { type: 'pie', radius: ['40%', '70%'], data: Object.entries(result.factor_contribution).map(([name, value]) => ({ name, value: ((value as number) * 100).toFixed(2) })) }
    ]
  }
})

const monthlyProfitChartOption = computed(() => {
  const result = props.result
  if (!result?.monthly_profit) return {}
  return {
    tooltip: { trigger: 'axis', formatter: '{b}<br/>收益：{c}%' },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', data: Object.keys(result.monthly_profit) },
    yAxis: { type: 'value', axisLabel: { formatter: '{value}%' } },
    series: [
      { type: 'bar', data: Object.values(result.monthly_profit).map((v: any) => (v * 100).toFixed(2)),
        itemStyle: { color: (params: any) => params.value >= 0 ? '#67c23a' : '#f56c6c' }
      }
    ]
  }
})

const riskMetrics = computed(() => {
  const result = props.result
  if (!result) return []
  return [
    { name: '波动率', value: (result.volatility || 0).toFixed(4), desc: '收益率的标准差，衡量风险水平' },
    { name: '信息比率', value: (result.information_ratio || 0).toFixed(2), desc: '超额收益与跟踪误差的比值' },
    { name: '胜率', value: ((result.win_rate || 0) * 100).toFixed(2) + '%', desc: '盈利交易占总交易的比例' },
    { name: '盈亏比', value: (result.profit_loss_ratio || 0).toFixed(2), desc: '平均盈利/平均亏损的比值' },
    { name: '最大回撤', value: ((result.max_drawdown || 0) * 100).toFixed(2) + '%', desc: '净值从最高点到最低点的最大跌幅' },
    { name: '夏普比率', value: (result.sharpe_ratio || 0).toFixed(2), desc: '单位风险获得的超额收益' },
    { name: '卡玛比率', value: (result.calmar_ratio || 0).toFixed(2), desc: '年化收益/最大回撤' },
    { name: '索提诺比率', value: (result.sortino_ratio || 0).toFixed(2), desc: '只考虑下行风险的夏普比率' }
  ]
})

// 导出CSV
function exportTrades() {
  if (!props.result?.trades) {
    ElMessage.warning('暂无交易记录可导出')
    return
  }
  const headers = ['交易日期', '股票代码', '股票名称', '策略', '买入价', '卖出价', '收益率', '持仓天数']
  const rows = props.result.trades.map((t: Record<string, any>) => [
    t.date, t.ts_code, t.stock_name, t.strategy, t.buy_price, t.sell_price, `${(t.profit_pct * 100).toFixed(2)}%`, t.hold_days
  ])
  const csvContent = [headers.join(','), ...rows.map(r => r.join(','))].join('\n')
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `回测交易记录_${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
  ElMessage.success('导出成功')
}
</script>

<template>
  <div class="backtest-result-panel" v-if="result">
    <!-- 核心指标卡片 -->
    <div class="kpi-strip">
      <div class="kpi-chip">
        <span class="kpi-label">累计收益</span>
        <span class="kpi-value" :style="{ color: (result.total_return || 0) >= 0 ? '#67c23a' : '#f56c6c' }">
          {{ ((result.total_return || 0) * 100).toFixed(2) }}%
        </span>
      </div>
      <div class="kpi-chip">
        <span class="kpi-label">年化收益</span>
        <span class="kpi-value" :style="{ color: (result.annual_return || 0) >= 0 ? '#67c23a' : '#f56c6c' }">
          {{ ((result.annual_return || 0) * 100).toFixed(2) }}%
        </span>
      </div>
      <div class="kpi-chip">
        <span class="kpi-label">最大回撤</span>
        <span class="kpi-value" style="color: #f56c6c">{{ ((result.max_drawdown || 0) * 100).toFixed(2) }}%</span>
      </div>
      <div class="kpi-chip">
        <span class="kpi-label">夏普比率</span>
        <span class="kpi-value" style="color: #409eff">{{ (result.sharpe_ratio || 0).toFixed(2) }}</span>
      </div>
      <div class="kpi-chip">
        <span class="kpi-label">胜率</span>
        <span class="kpi-value" :style="{ color: (result.win_rate || 0) >= 0.5 ? '#67c23a' : '#f56c6c' }">
          {{ ((result.win_rate || 0) * 100).toFixed(1) }}%
        </span>
      </div>
    </div>

    <!-- 图表区域 -->
    <ElCard class="chart-card">
      <ElTabs>
        <ElTabPane label="📈 净值曲线">
          <VChart v-if="netValueChartOption" :option="netValueChartOption" autoresize style="height: 400px; width: 100%" />
          <ElEmpty v-else description="暂无净值数据" />
        </ElTabPane>
        <ElTabPane label="📊 日收益">
          <VChart v-if="dailyProfitChartOption" :option="dailyProfitChartOption" autoresize style="height: 400px; width: 100%" />
          <ElEmpty v-else description="暂无日收益数据" />
        </ElTabPane>
        <ElTabPane label="📉 仓位">
          <VChart v-if="positionChartOption" :option="positionChartOption" autoresize style="height: 400px; width: 100%" />
          <ElEmpty v-else description="暂无仓位数据" />
        </ElTabPane>
        <ElTabPane label="🔄 策略对比">
          <VChart v-if="strategyCompareChartOption" :option="strategyCompareChartOption" autoresize style="height: 400px; width: 100%" />
          <ElEmpty v-else description="暂无策略对比数据" />
        </ElTabPane>
        <ElTabPane label="🎯 雷达图">
          <VChart v-if="radarChartOption" :option="radarChartOption" autoresize style="height: 400px; width: 100%" />
          <ElEmpty v-else description="暂无雷达数据" />
        </ElTabPane>
        <ElTabPane label="🧩 因子贡献">
          <VChart v-if="factorContributionChartOption" :option="factorContributionChartOption" autoresize style="height: 400px; width: 100%" />
          <ElEmpty v-else description="暂无因子数据" />
        </ElTabPane>
        <ElTabPane label="📅 月度收益">
          <VChart v-if="monthlyProfitChartOption" :option="monthlyProfitChartOption" autoresize style="height: 400px; width: 100%" />
          <ElEmpty v-else description="暂无月度数据" />
        </ElTabPane>
      </ElTabs>
    </ElCard>

    <!-- 风险指标 -->
    <ElCard class="risk-card" style="margin-top: 16px">
      <template #header><span>🛡️ 风险指标</span></template>
      <div class="risk-grid">
        <div v-for="m in riskMetrics" :key="m.name" class="risk-item">
          <span class="risk-name">{{ m.name }}</span>
          <span class="risk-value">{{ m.value }}</span>
          <span class="risk-desc">{{ m.desc }}</span>
        </div>
      </div>
    </ElCard>

    <!-- 盈亏TOP5 -->
    <div class="top5-row" style="margin-top: 16px">
      <ElCard class="top5-card">
        <template #header><span style="color: #67c23a">🏆 盈利TOP5</span></template>
        <ElTable :data="profitTop5" size="small" border>
          <ElTableColumn prop="ts_code" label="代码" width="100" />
          <ElTableColumn prop="stock_name" label="名称" width="80" />
          <ElTableColumn prop="strategy" label="策略" width="100" />
          <ElTableColumn label="收益率" width="90">
            <template #default="{ row }"><span style="color: #67c23a">{{ (row.profit_pct * 100).toFixed(2) }}%</span></template>
          </ElTableColumn>
        </ElTable>
      </ElCard>
      <ElCard class="top5-card">
        <template #header><span style="color: #f56c6c">💀 亏损TOP5</span></template>
        <ElTable :data="lossTop5" size="small" border>
          <ElTableColumn prop="ts_code" label="代码" width="100" />
          <ElTableColumn prop="stock_name" label="名称" width="80" />
          <ElTableColumn prop="strategy" label="策略" width="100" />
          <ElTableColumn label="收益率" width="90">
            <template #default="{ row }"><span style="color: #f56c6c">{{ (row.profit_pct * 100).toFixed(2) }}%</span></template>
          </ElTableColumn>
        </ElTable>
      </ElCard>
    </div>

    <!-- 交易记录 -->
    <ElCard style="margin-top: 16px">
      <template #header>
        <div class="card-header">
          <span>📋 交易记录 ({{ filteredTrades.length }}笔)</span>
          <ElButton size="small" :icon="Download" @click="exportTrades">导出CSV</ElButton>
        </div>
      </template>
      <div class="filter-bar">
        <ElInput v-model="searchTradeKeyword" placeholder="搜索代码/名称" size="small" style="width: 200px" clearable />
        <ElSelect v-model="filterStrategy" placeholder="策略筛选" size="small" style="width: 140px" clearable>
          <ElOption v-for="(cfg, id) in form.strategyConfigs" :key="id" :label="cfg.name" :value="id" />
        </ElSelect>
        <ElSelect v-model="filterProfit" placeholder="盈亏筛选" size="small" style="width: 120px" clearable>
          <ElOption label="盈利" value="profit" />
          <ElOption label="亏损" value="loss" />
        </ElSelect>
      </div>
      <ElTable :data="filteredTrades" size="small" border stripe max-height="500">
        <ElTableColumn prop="date" label="日期" width="100" />
        <ElTableColumn prop="ts_code" label="代码" width="100" />
        <ElTableColumn prop="stock_name" label="名称" width="80" />
        <ElTableColumn prop="strategy" label="策略" width="100" />
        <ElTableColumn prop="buy_price" label="买入" width="80" />
        <ElTableColumn prop="sell_price" label="卖出" width="80" />
        <ElTableColumn label="收益率" width="90">
          <template #default="{ row }">
            <span :style="{ color: row.profit_pct >= 0 ? '#67c23a' : '#f56c6c' }">
              {{ (row.profit_pct * 100).toFixed(2) }}%
            </span>
          </template>
        </ElTableColumn>
        <ElTableColumn prop="hold_days" label="持仓天数" width="80" />
      </ElTable>
    </ElCard>
  </div>
</template>

<script lang="ts">
export default { name: 'BacktestResultPanel' }
</script>

<style scoped lang="scss">
.backtest-result-panel {
  margin-top: 16px;
}
.kpi-strip {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.kpi-chip {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 10px 18px;
  border-radius: 6px;
  background: var(--el-fill-color-light);
  min-width: 100px;
}
.kpi-label { font-size: 12px; color: var(--el-text-color-secondary); }
.kpi-value { font-size: 18px; font-weight: 700; margin-top: 2px; }
.chart-card { margin-bottom: 0; }
.risk-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}
.risk-item {
  padding: 8px 12px;
  border-radius: 4px;
  background: var(--el-fill-color-lighter);
}
.risk-name { font-weight: 600; font-size: 13px; }
.risk-value { margin-left: 8px; font-size: 14px; color: var(--el-color-primary); }
.risk-desc { display: block; font-size: 11px; color: var(--el-text-color-placeholder); margin-top: 2px; }
.top5-row {
  display: flex;
  gap: 16px;
}
.top5-card { flex: 1; }
.filter-bar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>
