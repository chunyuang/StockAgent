<script setup lang="ts">
/**
 * BacktestResultPanel - 超短回测结果展示面板
 * 包含净值曲线、回撤、日收益、仓位、策略对比、雷达图、因子贡献、月度收益、风险指标、交易记录
 * 
 * 后端数据规范(必须遵守):
 * - total_return/win_rate/max_drawdown/annualized_return: 已是百分比(-1.11表示-1.11%)
 * - net_value_series[].net_value: 绝对金额(988861), 需÷initial_cash归一化
 * - net_value_series[].daily_profit: 绝对金额(-3386), 需÷initial_cash×100转百分比
 * - drawdown_series[].drawdown: 小数(0.003=0.3%), 需×100转百分比
 * - position_series[].value: 小数(0.188=18.8%), 需×100转百分比
 * - monthly_profit值: 小数(-0.011=-1.11%), 需×100转百分比
 * - factor_contribution值: 小数(0.5=50%), 需×100转百分比
 * - merged_trades[].profit_pct: 已是百分比(-2.55=-2.55%), 不需×100
 * - metrics.risk.*_pct: 已是百分比, 直接用
 * - strategy_results: 只有win_rate/total_return/trades_count/total_pnl_pct, 无净值曲线
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

// 格式化百分比(后端已是百分比形式,直接加%)
function fmtPct(val: number | undefined | null): string {
  if (val == null || isNaN(val)) return '--'
  return val.toFixed(2) + '%'
}

// 格式化金额(备用)

// 筛选变量
const searchTradeKeyword = ref('')
const filterStrategy = ref('')
const filterProfit = ref('')

// 统一的交易数据源(merged_trades优先)
const allTrades = computed(() => {
  return props.result?.merged_trades || props.result?.all_trades || []
})

// 筛选后的交易记录
const filteredTrades = computed(() => {
  let trades = allTrades.value
  if (searchTradeKeyword.value) {
    const keyword = searchTradeKeyword.value.toLowerCase()
    trades = trades.filter((t: any) =>
      (t.ts_code || '').toLowerCase().includes(keyword) ||
      (t.name || t.stock_name || '').toLowerCase().includes(keyword)
    )
  }
  if (filterStrategy.value) {
    trades = trades.filter((t: any) => t.strategy === filterStrategy.value)
  }
  if (filterProfit.value) {
    trades = trades.filter((t: any) => filterProfit.value === 'profit' ? t.profit_pct > 0 : t.profit_pct < 0)
  }
  return trades
})

// 可用策略列表(从交易中提取)
const availableStrategies = computed(() => {
  const strategies = new Set<string>()
  allTrades.value.forEach((t: any) => {
    if (t.strategy) strategies.add(t.strategy)
  })
  return Array.from(strategies)
})

// 盈亏TOP5
const profitTop5 = computed(() => {
  const trades = [...allTrades.value].filter((t: any) => t.profit_pct > 0)
  return trades.sort((a: any, b: any) => b.profit_pct - a.profit_pct).slice(0, 5)
})

const lossTop5 = computed(() => {
  const trades = [...allTrades.value].filter((t: any) => t.profit_pct < 0)
  return trades.sort((a: any, b: any) => a.profit_pct - b.profit_pct).slice(0, 5)
})

// ==================== 图表配置 ====================

const netValueChartOption = computed(() => {
  const result = props.result
  if (!result?.net_value_series || result.net_value_series.length === 0) return null
  const initialCash = result.initial_cash || 1000000
  // net_value是绝对金额, 归一化为净值(初始=1.0)
  const netValues = result.net_value_series.map((d: any) => +(d.net_value / initialCash).toFixed(4))
  // drawdown是小数(0.003=0.3%), ×100转百分比
  const drawdowns = result.drawdown_series.map((d: any) => +(d.drawdown * 100).toFixed(4))
  const dates = result.net_value_series.map((d: any) => d.trade_date)
  // 自动计算Y轴范围
  const minNV = Math.min(...netValues)
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['净值曲线', '回撤(%)'] },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', boundaryGap: false, data: dates },
    yAxis: [
      { type: 'value', name: '净值', min: Math.floor(minNV * 100) / 100 - 0.01 },
      { type: 'value', name: '回撤(%)', position: 'right' }
    ],
    series: [
      {
        name: '净值曲线', type: 'line', data: netValues, smooth: true,
        lineStyle: { width: 2 },
        areaStyle: { color: 'rgba(64,158,255,0.1)' }
      },
      {
        name: '回撤(%)', type: 'line', yAxisIndex: 1, data: drawdowns,
        color: '#f56c6c', lineStyle: { width: 1.5, type: 'dashed' },
        areaStyle: { color: 'rgba(245,108,108,0.1)' }
      }
    ]
  }
})

const dailyProfitChartOption = computed(() => {
  const result = props.result
  const nvs = result?.net_value_series
  if (!nvs || nvs.length === 0) return null
  // daily_profit是绝对金额, ÷initial_cash×100转百分比
  const initial = result.initial_cash || 1000000
  const dp = nvs.map((d: any) => d.daily_profit)
  const dates = nvs.map((d: any) => d.trade_date)
  const values = dp.map((v: any) => +((v / initial) * 100).toFixed(4))
  return {
    tooltip: { trigger: 'axis', formatter: (p: any) => `${p[0].axisValue}<br/>当日盈亏：${p[0].value}%` },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', data: dates },
    yAxis: { type: 'value', axisLabel: { formatter: '{value}%' } },
    series: [
      {
        type: 'bar', data: values,
        itemStyle: {
          color: (params: any) => params.value >= 0 ? '#67c23a' : '#f56c6c'
        }
      }
    ]
  }
})

const positionChartOption = computed(() => {
  const result = props.result
  if (!result?.position_series || result.position_series.length === 0) return null
  // value是小数(0.188=18.8%), ×100转百分比
  const values = result.position_series.map((d: any) => +(d.value * 100).toFixed(2))
  const dates = result.position_series.map((d: any) => d.date)
  return {
    tooltip: { trigger: 'axis', formatter: (p: any) => `${p[0].axisValue}<br/>仓位：${p[0].value}%` },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', boundaryGap: false, data: dates },
    yAxis: { type: 'value', max: 100, axisLabel: { formatter: '{value}%' } },
    series: [
      {
        name: '仓位', type: 'line', data: values, smooth: true,
        areaStyle: { color: 'rgba(103,194,58,0.15)' },
        lineStyle: { color: '#67c23a' }
      }
    ]
  }
})

// 策略对比: strategy_results只有KPI, 无净值曲线, 改为KPI对比表
const strategyCompareChartOption = computed(() => {
  const result = props.result
  if (!result?.strategy_results) return null
  const sr = result.strategy_results
  const names = Object.keys(sr)
  if (names.length < 2) return null  // 只有一个策略时不需要对比
  const strategies = Object.values(sr) as any[]
  // total_return已是百分比, 直接用
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: names },
    radar: {
      indicator: [
        { name: '收益率(%)', max: 100 },
        { name: '胜率(%)', max: 100 },
        { name: '交易次数' }
      ]
    },
    series: [{
      type: 'radar',
      data: strategies.map(s => ({
        name: s.strategy_name || s.name || '未知',
        value: [
          s.total_return ?? 0,
          s.win_rate ?? 0,
          s.trades_count ?? 0
        ]
      }))
    }]
  }
})

// 雷达图: 组合级别的多维度指标
const radarChartOption = computed(() => {
  const result = props.result
  if (!result) return null
  // 从顶层result取(已是百分比)
  const risk = result.metrics?.risk || {}
  const values = [
    result.total_return ?? 0,       // 收益率(%) 
    result.win_rate ?? 0,           // 胜率(%)
    risk.profit_loss_ratio ?? result.profit_loss_ratio ?? 0,  // 盈亏比
    result.sharpe_ratio ?? 0,       // 夏普
    -(result.max_drawdown ?? 0)     // 回撤(取反,越大越好)
  ]
  return {
    tooltip: { trigger: 'item' },
    radar: {
      indicator: [
        { name: '收益率(%)', max: 50 },
        { name: '胜率(%)', max: 100 },
        { name: '盈亏比', max: 5 },
        { name: '夏普比率', max: 5 },
        { name: '回撤控制', max: 20 }
      ]
    },
    series: [{
      type: 'radar',
      data: [{
        name: '组合绩效',
        value: values.map(v => Math.abs(v).toFixed(2))
      }]
    }]
  }
})

const factorContributionChartOption = computed(() => {
  const result = props.result
  if (!result?.factor_contribution) return null
  const entries = Object.entries(result.factor_contribution)
  if (entries.length === 0) return null
  // factor_contribution值是小数(0.5=50%), ×100转百分比
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c}%' },
    series: [{
      type: 'pie', radius: ['40%', '70%'],
      label: { formatter: '{b}: {c}%' },
      data: entries.map(([name, value]) => ({
        name,
        value: +((value as number) * 100).toFixed(1)
      }))
    }]
  }
})

const monthlyProfitChartOption = computed(() => {
  const result = props.result
  if (!result?.monthly_profit) return null
  const entries = Object.entries(result.monthly_profit)
  if (entries.length === 0) return null
  // monthly_profit值是小数(-0.011=-1.11%), ×100转百分比
  return {
    tooltip: { trigger: 'axis', formatter: '{b}<br/>收益：{c}%' },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', data: entries.map(([k]) => k) },
    yAxis: { type: 'value', axisLabel: { formatter: '{value}%' } },
    series: [{
      type: 'bar',
      data: entries.map(([_, v]) => +((v as number) * 100).toFixed(2)),
      itemStyle: {
        color: (params: any) => parseFloat(params.value) >= 0 ? '#67c23a' : '#f56c6c'
      }
    }]
  }
})

// 风险指标: 优先从metrics.risk取, 兜底从result顶层取
const riskMetrics = computed(() => {
  const result = props.result
  if (!result) return []
  const risk = result.metrics?.risk || {}
  const ret = result.metrics?.returns || {}
  return [
    { name: '波动率', value: fmtPct(risk.volatility_pct), desc: '收益率的标准差，衡量风险水平' },
    { name: '信息比率', value: (risk.information_ratio ?? 0).toFixed(2), desc: '超额收益与跟踪误差的比值' },
    { name: '胜率', value: fmtPct(risk.win_rate_pct ?? result.win_rate), desc: '盈利交易占总交易的比例' },
    { name: '盈亏比', value: (risk.profit_loss_ratio ?? result.profit_loss_ratio ?? 0).toFixed(2), desc: '平均盈利/平均亏损的比值' },
    { name: '最大回撤', value: fmtPct(risk.max_drawdown_pct ?? result.max_drawdown), desc: '净值从最高点到最低点的最大跌幅' },
    { name: '夏普比率', value: (risk.sharpe_ratio ?? result.sharpe_ratio ?? 0).toFixed(2), desc: '单位风险获得的超额收益' },
    { name: '卡玛比率', value: (risk.calmar_ratio ?? result.calmar_ratio ?? 0).toFixed(2), desc: '年化收益/最大回撤' },
    { name: '索提诺比率', value: (risk.sortino_ratio ?? result.sortino_ratio ?? 0).toFixed(2), desc: '只考虑下行风险的夏普比率' },
    { name: '基准收益', value: fmtPct(ret.benchmark_return_pct), desc: '沪深300同期收益' },
    { name: 'Alpha', value: fmtPct(ret.alpha_pct), desc: '超额收益(组合-基准)' },
  ]
})

// 导出CSV
function exportTrades() {
  const trades = allTrades.value
  if (!trades || trades.length === 0) {
    ElMessage.warning('暂无交易记录可导出')
    return
  }
  const headers = ['买入日期', '股票代码', '股票名称', '策略', '买入价', '卖出价', '收益率(%)', '持仓天数']
  const rows = trades.map((t: any) => [
    t.buy_date || t.date || '', t.ts_code || '', t.name || t.stock_name || '',
    t.strategy || '', t.buy_price ?? '', t.sell_price ?? '',
    t.profit_pct != null ? t.profit_pct.toFixed(2) : '-', t.hold_days ?? 1
  ])
  const csvContent = [headers.join(','), ...rows.map((r: string[]) => r.join(','))].join('\n')
  const blob = new Blob(['\uFEFF' + csvContent], { type: 'text/csv;charset=utf-8;' })
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
          {{ fmtPct(result.total_return) }}
        </span>
      </div>
      <div class="kpi-chip">
        <span class="kpi-label">年化收益</span>
        <span class="kpi-value" :style="{ color: (result.annualized_return || 0) >= 0 ? '#67c23a' : '#f56c6c' }">
          {{ fmtPct(result.annualized_return) }}
        </span>
      </div>
      <div class="kpi-chip">
        <span class="kpi-label">最大回撤</span>
        <span class="kpi-value" style="color: #f56c6c">{{ fmtPct(result.max_drawdown) }}</span>
      </div>
      <div class="kpi-chip">
        <span class="kpi-label">夏普比率</span>
        <span class="kpi-value" style="color: #409eff">{{ (result.sharpe_ratio || 0).toFixed(2) }}</span>
      </div>
      <div class="kpi-chip">
        <span class="kpi-label">胜率</span>
        <span class="kpi-value" :style="{ color: (result.win_rate || 0) >= 50 ? '#67c23a' : '#f56c6c' }">
          {{ fmtPct(result.win_rate) }}
        </span>
      </div>
      <div class="kpi-chip">
        <span class="kpi-label">交易笔数</span>
        <span class="kpi-value" style="color: #409eff">{{ result.total_trades || 0 }}</span>
      </div>
      <div class="kpi-chip">
        <span class="kpi-label">信号数</span>
        <span class="kpi-value" style="color: #e6a23c">{{ result.total_signals || 0 }}</span>
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

    <!-- 策略对比(多策略时显示) -->
    <ElCard v-if="result?.strategy_results && Object.keys(result.strategy_results).length >= 2" style="margin-top: 16px">
      <template #header><span>🔄 策略对比</span></template>
      <VChart v-if="strategyCompareChartOption" :option="strategyCompareChartOption" autoresize style="height: 350px; width: 100%" />
      <!-- 策略KPI对比表 -->
      <ElTable :data="Object.entries(result.strategy_results).map(([name, d]: any) => ({ name, ...d }))" size="small" border stripe style="margin-top: 12px">
        <ElTableColumn prop="name" label="策略" width="120" />
        <ElTableColumn label="收益率" width="100">
          <template #default="{ row }">
            <span :style="{ color: row.total_return >= 0 ? '#67c23a' : '#f56c6c' }">{{ fmtPct(row.total_return) }}</span>
          </template>
        </ElTableColumn>
        <ElTableColumn label="胜率" width="80">
          <template #default="{ row }">{{ fmtPct(row.win_rate) }}</template>
        </ElTableColumn>
        <ElTableColumn prop="trades_count" label="交易次数" width="80" />
        <ElTableColumn label="盈亏比" width="80">
          <template #default="{ row }">{{ (row.total_pnl_pct ?? 0).toFixed(2) }}%</template>
        </ElTableColumn>
      </ElTable>
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
        <ElTable v-if="profitTop5.length > 0" :data="profitTop5" size="small" border>
          <ElTableColumn prop="ts_code" label="代码" width="100" />
          <ElTableColumn label="名称" width="80">
            <template #default="{ row }">{{ row.name || row.stock_name || row.ts_code }}</template>
          </ElTableColumn>
          <ElTableColumn prop="strategy" label="策略" width="100" />
          <ElTableColumn label="收益率" width="90">
            <template #default="{ row }">
              <span style="color: #67c23a">{{ fmtPct(row.profit_pct) }}</span>
            </template>
          </ElTableColumn>
        </ElTable>
        <ElEmpty v-else description="无盈利交易" :image-size="40" />
      </ElCard>
      <ElCard class="top5-card">
        <template #header><span style="color: #f56c6c">💀 亏损TOP5</span></template>
        <ElTable v-if="lossTop5.length > 0" :data="lossTop5" size="small" border>
          <ElTableColumn prop="ts_code" label="代码" width="100" />
          <ElTableColumn label="名称" width="80">
            <template #default="{ row }">{{ row.name || row.stock_name || row.ts_code }}</template>
          </ElTableColumn>
          <ElTableColumn prop="strategy" label="策略" width="100" />
          <ElTableColumn label="收益率" width="90">
            <template #default="{ row }">
              <span style="color: #f56c6c">{{ fmtPct(row.profit_pct) }}</span>
            </template>
          </ElTableColumn>
        </ElTable>
        <ElEmpty v-else description="无亏损交易" :image-size="40" />
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
          <ElOption v-for="s in availableStrategies" :key="s" :label="s" :value="s" />
        </ElSelect>
        <ElSelect v-model="filterProfit" placeholder="盈亏筛选" size="small" style="width: 120px" clearable>
          <ElOption label="盈利" value="profit" />
          <ElOption label="亏损" value="loss" />
        </ElSelect>
      </div>
      <ElTable :data="filteredTrades" size="small" border stripe max-height="500">
        <ElTableColumn label="买入日" width="100">
          <template #default="{ row }">{{ row.buy_date || row.date }}</template>
        </ElTableColumn>
        <ElTableColumn label="卖出日" width="100">
          <template #default="{ row }">{{ row.sell_date || '-' }}</template>
        </ElTableColumn>
        <ElTableColumn prop="ts_code" label="代码" width="100" />
        <ElTableColumn label="名称" width="80">
          <template #default="{ row }">{{ row.name || row.stock_name || '-' }}</template>
        </ElTableColumn>
        <ElTableColumn prop="strategy" label="策略" width="100" />
        <ElTableColumn label="买入价" width="80">
          <template #default="{ row }">{{ row.buy_price?.toFixed(2) ?? '-' }}</template>
        </ElTableColumn>
        <ElTableColumn label="卖出价" width="80">
          <template #default="{ row }">{{ row.sell_price?.toFixed(2) ?? '-' }}</template>
        </ElTableColumn>
        <ElTableColumn label="收益率" width="90">
          <template #default="{ row }">
            <span :style="{ color: row.profit_pct > 0 ? '#67c23a' : '#f56c6c' }">
              {{ fmtPct(row.profit_pct) }}
            </span>
          </template>
        </ElTableColumn>
        <ElTableColumn label="数量" width="70">
          <template #default="{ row }">{{ row.shares ?? '-' }}</template>
        </ElTableColumn>
        <ElTableColumn prop="sentiment" label="情绪" min-width="120" show-overflow-tooltip />
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
