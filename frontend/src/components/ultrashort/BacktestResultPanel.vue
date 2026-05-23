<script setup lang="ts">
/**
 * BacktestResultPanel - 超短回测结果展示面板
 * 包含净值曲线、回撤、日收益、仓位、策略对比、雷达图、因子贡献、月度收益、风险指标、交易记录
 * 
 * 后端数据规范(必须遵守):
 * - total_return/win_rate/max_drawdown/annualized_return: 已是百分比(-1.11表示-1.11%)
 * - net_value_series[].net_value: 已归一化(1.0起始), 直接使用
 * - net_value_series[].daily_profit: 已归一化(÷initial_cash), 需×100转百分比
 * - drawdown_series[].drawdown: 小数(0.0368=3.68%), 需×100转百分比
 * - position_series[].value: 小数(0.188=18.8%), 需×100转百分比
 * - monthly_profit值: 小数(-0.011=-1.11%), 需×100转百分比
 * - factor_contribution值: 小数(0.5=50%), 需×100转百分比
 * - merged_trades[].profit_pct: 已是百分比(-2.55=-2.55%), 不需×100
 * - daily_profit(顶层): 已归一化(÷initial_cash), 与net_value_series一致
 * - metrics.risk.*_pct: 已是百分比, 直接用
 * - strategy_results: 只有win_rate/total_return/trades_count/avg_profit_pct, 无净值曲线
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
  ElTooltip,
} from 'element-plus'
import { Download } from '@element-plus/icons-vue'
import { STRATEGY_NAMES } from '@/config/backtestConstants'

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

// 策略中文名（去emoji版本，用于表格/选项等空间有限的场景）
function strategyDisplayName(id: string): string {
  const raw = STRATEGY_NAMES[id] || id
  // 去掉开头的emoji+空格, 如 "🏃‍♂️ 半路追涨" → "半路追涨"
  return raw.replace(/^[\u{1F000}-\u{1FFFF}\u{2600}-\u{27BF}\u{FE00}-\u{FE0F}\u{1F900}-\u{1F9FF}\u{200D}\u{20E3}]+\s*/u, '').trim() || raw
}

// 卖出原因中文翻译
function translateSellReason(reason: string): string {
  // 未平仓交易(空字符串或undefined)
  if (!reason) return '持仓中'
  const map: Record<string, string> = {
    'stop_loss': '止损', '止损': '止损',
    'take_profit': '止盈', '止盈': '止盈',
    'rebalance': '调仓', '调仓卖出': '调仓', '调仓调出': '调仓', '减仓': '调仓',
    'force_empty_position': '强制空仓', 'force_empty': '强制空仓', '空仓': '强制空仓', '强制': '强制空仓',
    'max_hold': '到期', '到期': '到期', '超时': '到期',
    '跳空止损': '跳空止损',
    '冲高回落': '冲高回落',
    '高开即卖': '高开即卖',
    '利润保护': '利润保护',
    '利润锁定': '利润锁定',
    'gap_down_stop': '跳空止损',
    '持仓中': '持仓中',
    '停牌超时强卖': '停牌强卖',
  }
  // 尝试精确匹配
  if (map[reason]) return map[reason]
  // 尝试包含匹配(从长到短排序,避免短key误匹配)
  const sortedKeys = Object.keys(map).sort((a, b) => b.length - a.length)
  for (const key of sortedKeys) {
    if (reason.includes(key)) return map[key]
  }
  // 未匹配, 返回原始值(可能是后端新增的卖出原因)
  return reason
}

// 任务3: 卖出原因百分比
function sellReasonPct(key: string): string {
  const stats = props.result?.sell_reason_stats
  if (!stats) return '0'
  const total = (Object.values(stats) as number[]).reduce((a, b) => a + b, 0)
  if (total === 0) return '0'
  return ((stats[key] / total) * 100).toFixed(0)
}

// 任务2: 月度收益数据(按月聚合,月度收益=该月内收益)
const monthlyData = computed(() => {
  const nvs = props.result?.net_value_series
  if (!nvs || nvs.length === 0) return []
  const monthMap = new Map<string, { start_value: number; end_value: number; start_date: string; end_date: string }>()
  for (const d of nvs) {
    const date = String(d.trade_date)
    const monthKey = date.substring(0, 6) // "202601"
    if (!monthMap.has(monthKey)) {
      monthMap.set(monthKey, { start_value: d.net_value, end_value: d.net_value, start_date: date, end_date: date })
    }
    const m = monthMap.get(monthKey)!
    m.end_value = d.net_value
    m.end_date = date
  }
  return Array.from(monthMap.entries()).map(([month, data]) => ({
    month: month.substring(0, 4) + '-' + month.substring(4),
    return_pct: +((data.end_value - data.start_value) / data.start_value * 100).toFixed(2),
    start_date: data.start_date,
    end_date: data.end_date,
  }))
})

// 任务2: 月度交易统计
const monthlyTrades = computed(() => {
  const trades = allTrades.value
  if (!trades.length) return []
  const monthMap = new Map<string, { total: number; wins: number }>()
  for (const t of trades) {
    const date = t.buy_date || t.date || ''
    const monthKey = date.substring(0, 7) // "2026-01"
    if (!monthKey || monthKey.length < 7) continue
    if (!monthMap.has(monthKey)) monthMap.set(monthKey, { total: 0, wins: 0 })
    const m = monthMap.get(monthKey)!
    m.total++
    if (t.profit_pct > 0) m.wins++
  }
  return Array.from(monthMap.entries()).map(([month, data]) => ({
    month, trades: data.total, win_rate: data.total > 0 ? +(data.wins / data.total * 100).toFixed(1) : 0
  }))
})

// 任务2: 月度收益柱状图 + 累计收益折线(双Y轴)
const monthlyReturnChartOption = computed(() => {
  if (!monthlyData.value.length) return null
  const months = monthlyData.value.map(d => d.month)
  const returns = monthlyData.value.map(d => d.return_pct)
  // 计算累计收益线
  const cumReturns: number[] = []
  let cumVal = 0
  for (const r of returns) {
    cumVal += r
    cumReturns.push(+cumVal.toFixed(2))
  }
  return {
    tooltip: { trigger: 'axis', formatter: (p: any) => {
      let html = `${p[0].axisValue}<br/>`
      for (const s of p) {
        html += `${s.marker} ${s.seriesName}：${s.value}%<br/>`
      }
      return html
    }},
    legend: { data: ['月度收益', '累计收益'] },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', data: months },
    yAxis: [
      { type: 'value', name: '月度收益(%)', axisLabel: { formatter: '{value}%' } },
      { type: 'value', name: '累计收益(%)', position: 'right', axisLabel: { formatter: '{value}%' } },
    ],
    series: [
      {
        name: '月度收益', type: 'bar', data: returns,
        itemStyle: {
          color: (params: any) => parseFloat(params.value) >= 0 ? '#67c23a' : '#f56c6c'
        },
        label: { show: true, position: 'top', formatter: '{c}%', fontSize: 11 },
      },
      {
        name: '累计收益', type: 'line', yAxisIndex: 1, data: cumReturns,
        lineStyle: { color: '#409eff', width: 2 },
        itemStyle: { color: '#409eff' },
        smooth: true,
      },
    ]
  }
})

// 任务2: 合并月度数据(收益+交易统计)
const monthlyMergedData = computed(() => {
  const returns = monthlyData.value
  const trades = monthlyTrades.value
  const tradeMap = new Map(trades.map(t => [t.month, t]))
  return returns.map(r => {
    const t = tradeMap.get(r.month)
    return {
      ...r,
      trades: t?.trades ?? 0,
      win_rate: t?.win_rate ?? 0,
    }
  })
})

// 筛选变量
const searchTradeKeyword = ref('')
const filterStrategy = ref('')
const filterProfit = ref('')
const activeMainTab = ref('charts')

// 统一的交易数据源(merged_trades优先)
const allTrades = computed(() => {
  const trades = props.result?.merged_trades || props.result?.all_trades || []
  // 🔧 用stock_names兜底: 如果交易记录里没name, 从result.stock_names补上
  const stockNames = props.result?.stock_names || {}
  if (stockNames && Object.keys(stockNames).length > 0) {
    return trades.map((t: any) => {
      if (!t.name || t.name === t.ts_code?.split('.')[0]) {
        const fallbackName = stockNames[t.ts_code]
        if (fallbackName) return { ...t, name: fallbackName }
      }
      return t
    })
  }
  return trades
})

// 筛选后的交易记录
const filteredTrades = computed(() => {
  let trades = [...allTrades.value]  // 浅拷贝，避免排序影响原数组
  // 默认按buy_date降序(最新在前)
  trades.sort((a: any, b: any) => {
    const da = a.buy_date || a.date || ''
    const db = b.buy_date || b.date || ''
    return db.toString().localeCompare(da.toString())
  })
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

// 可用策略列表(从交易中提取,显示中文名)
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
  // net_value已归一化(1.0起始), 直接使用
  const netValues = result.net_value_series.map((d: any) => +(d.net_value).toFixed(4))
  // drawdown是小数(0.003=0.3%), ×100转百分比
  const drawdowns = result.drawdown_series?.map((d: any) => +(d.drawdown * 100).toFixed(4)) || []
  const dates = result.net_value_series.map((d: any) => d.trade_date)

  // 🔧 Bug1修复: 计算基准净值线(从benchmark_data累乘pct_chg)
  const benchmarkData = result.benchmark_data || []
  let benchmarkValues: number[] = []
  if (benchmarkData.length > 0) {
    // 按日期对齐: benchmark_data可能有不同的日期范围
    const bdMap = new Map(benchmarkData.map((b: any) => [String(b.trade_date), b.pct_chg]))
    let cumBench = 1.0
    benchmarkValues = dates.map((d: string) => {
      const pct = bdMap.get(String(d))
      if (pct != null && !isNaN(pct)) {
        cumBench *= (1 + pct / 100)
      }
      return +cumBench.toFixed(4)
    })
  }

  // 自动计算Y轴范围
  const minNV = Math.min(...netValues, ...(benchmarkValues.length > 0 ? benchmarkValues : [1]))
  const series: any[] = [
    {
      name: '策略净值', type: 'line', data: netValues, smooth: true,
      lineStyle: { width: 2 },
      areaStyle: { color: 'rgba(64,158,255,0.1)' }
    },
  ]
  if (benchmarkValues.length > 0) {
    series.push({
      name: '基准(沪深300)', type: 'line', data: benchmarkValues, smooth: true,
      lineStyle: { width: 1.5, type: 'dashed', color: '#e6a23c' },
      itemStyle: { color: '#e6a23c' },
    })
  }
  series.push({
    name: '回撤(%)', type: 'line', yAxisIndex: 1, data: drawdowns,
    color: '#f56c6c', lineStyle: { width: 1.5, type: 'dashed' },
    areaStyle: { color: 'rgba(245,108,108,0.1)' }
  })

  const isDark = document.documentElement.classList.contains('dark')
  const axisLabelColor = isDark ? '#94A3B8' : '#64748b'
  const gridLineColor = isDark ? 'rgba(255,255,255,0.03)' : '#f1f5f9'
  const tooltipBg = isDark ? 'rgba(18,18,26,0.98)' : 'rgba(255,255,255,0.96)'
  const tooltipBorder = isDark ? 'rgba(255,255,255,0.08)' : '#e2e8f0'
  const tooltipText = isDark ? '#fff' : '#1e293b'

  return {
    tooltip: {
      trigger: 'axis',
      backgroundColor: tooltipBg,
      borderColor: tooltipBorder,
      textStyle: { color: tooltipText },
      formatter: (params: any) => {
        let html = `<b>${params[0].axisValue}</b><br/>`
        for (const p of params) {
          const unit = p.seriesName.includes('回撤') ? '%' : ''
          html += `${p.marker} ${p.seriesName}：${p.value}${unit}<br/>`
        }
        return html
      }
    },
    legend: { data: ['策略净值', ...(benchmarkValues.length > 0 ? ['基准(沪深300)'] : []), '回撤(%)'], textStyle: { color: axisLabelColor } },
    grid: { left: '3%', right: '4%', bottom: '12%', containLabel: true },
    xAxis: { type: 'category', boundaryGap: false, data: dates, axisLine: { lineStyle: { color: gridLineColor } }, axisLabel: { color: axisLabelColor }, splitLine: { lineStyle: { color: gridLineColor } } },
    yAxis: [
      { type: 'value', name: '净值', min: Math.floor(minNV * 100) / 100 - 0.01, axisLabel: { color: axisLabelColor }, splitLine: { lineStyle: { color: gridLineColor } } },
      { type: 'value', name: '回撤(%)', position: 'right', axisLabel: { color: axisLabelColor }, splitLine: { show: false } }
    ],
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 20, bottom: 4 }],
    series,
  }
})

const dailyProfitChartOption = computed(() => {
  const result = props.result
  const nvs = result?.net_value_series
  if (!nvs || nvs.length === 0) return null
  // daily_profit已归一化(÷initial_cash), 直接×100转百分比
  const dp = nvs.map((d: any) => d.daily_profit)
  const dates = nvs.map((d: any) => d.trade_date)
  const values = dp.map((v: any) => +((v) * 100).toFixed(4))
  const isDark = document.documentElement.classList.contains('dark')
  const axisLabelColor = isDark ? '#94A3B8' : '#64748b'
  const gridLineColor = isDark ? 'rgba(255,255,255,0.03)' : '#f1f5f9'
  const tooltipBg = isDark ? 'rgba(18,18,26,0.98)' : 'rgba(255,255,255,0.96)'
  const tooltipBorder = isDark ? 'rgba(255,255,255,0.08)' : '#e2e8f0'
  const tooltipText = isDark ? '#fff' : '#1e293b'
  return {
    tooltip: { trigger: 'axis', backgroundColor: tooltipBg, borderColor: tooltipBorder, textStyle: { color: tooltipText }, formatter: (p: any) => `${p[0].axisValue}<br/>日收益率：${p[0].value}%` },
    grid: { left: '3%', right: '4%', bottom: '12%', containLabel: true },
    xAxis: { type: 'category', data: dates, axisLabel: { color: axisLabelColor }, axisLine: { lineStyle: { color: gridLineColor } }, splitLine: { lineStyle: { color: gridLineColor } } },
    yAxis: { type: 'value', name: '日收益率(%)', axisLabel: { formatter: '{value}%', color: axisLabelColor }, splitLine: { lineStyle: { color: gridLineColor } } },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 20, bottom: 4 }],
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
  const isDark = document.documentElement.classList.contains('dark')
  const axisLabelColor = isDark ? '#94A3B8' : '#64748b'
  const gridLineColor = isDark ? 'rgba(255,255,255,0.03)' : '#f1f5f9'
  const tooltipBg = isDark ? 'rgba(18,18,26,0.98)' : 'rgba(255,255,255,0.96)'
  const tooltipBorder = isDark ? 'rgba(255,255,255,0.08)' : '#e2e8f0'
  const tooltipText = isDark ? '#fff' : '#1e293b'
  return {
    tooltip: { trigger: 'axis', backgroundColor: tooltipBg, borderColor: tooltipBorder, textStyle: { color: tooltipText }, formatter: (p: any) => `${p[0].axisValue}<br/>仓位：${p[0].value}%` },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', boundaryGap: false, data: dates, axisLabel: { color: axisLabelColor }, axisLine: { lineStyle: { color: gridLineColor } } },
    yAxis: { type: 'value', max: 100, axisLabel: { formatter: '{value}%', color: axisLabelColor }, splitLine: { lineStyle: { color: gridLineColor } } },
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
  const displayNames = names.map(n => strategyDisplayName(n))
  // total_return已是百分比, 直接用
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: displayNames },
    radar: {
      indicator: [
        { name: '收益率(%)', max: Math.max(50, ...strategies.map(s => Math.abs(s.total_return ?? 0))) + 10 },
        { name: '胜率(%)', max: 100 },
        { name: '盈亏比', max: Math.max(3, ...strategies.map(s => Math.abs(s.profit_loss_ratio ?? 0))) + 1 }
      ]
    },
    series: [{
      type: 'radar',
      data: strategies.map((s, i) => ({
        name: displayNames[i],
        value: [
          s.total_return ?? 0,
          s.win_rate ?? 0,
          s.profit_loss_ratio ?? 0
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
  // 回撤控制: 用100-回撤值,越大越好(100=无回撤)
  const ddControl = Math.max(0, 100 - Math.abs(result.max_drawdown ?? 0))
  const values = [
    result.total_return ?? 0,       // 收益率(%) 
    result.win_rate ?? 0,           // 胜率(%)
    risk.profit_loss_ratio ?? result.profit_loss_ratio ?? 0,  // 盈亏比
    result.sharpe_ratio ?? 0,       // 夏普
    ddControl                        // 回撤控制(0-100,越大越好)
  ]
  // 动态计算雷达图最大值, 避免硬编码截断
  const maxReturn = Math.max(50, Math.ceil(Math.abs(result.total_return ?? 0) / 10) * 10 + 10)
  const maxWR = 100
  const maxPLR = Math.max(5, Math.ceil(Math.abs(risk.profit_loss_ratio ?? result.profit_loss_ratio ?? 0)) + 1)
  const maxSharpe = Math.max(5, Math.ceil(Math.abs(result.sharpe_ratio ?? 0)) + 1)
  const maxDDCtrl = 100  // 回撤控制范围固定0-100

  return {
    tooltip: { trigger: 'item' },
    radar: {
      indicator: [
        { name: '收益率(%)', max: maxReturn },
        { name: '胜率(%)', max: maxWR },
        { name: '盈亏比', max: maxPLR },
        { name: '夏普比率', max: maxSharpe },
        { name: '回撤控制', max: maxDDCtrl }
      ]
    },
    series: [{
      type: 'radar',
      data: [{
        name: '组合绩效',
        value: values.map(v => +Math.abs(v).toFixed(2))
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
  // 注意: 这是交易笔数占比，非盈亏贡献
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

// ==================== F2: 策略对比柱状图 ====================
const strategyBarChartOption = computed(() => {
  const result = props.result
  if (!result?.strategy_results) return null
  const sr = result.strategy_results
  const names = Object.keys(sr)
  if (names.length === 0) return null
  const strategies = Object.values(sr) as any[]
  // X轴用策略中文名
  const displayNames = names.map(n => strategyDisplayName(n))

  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: ['累计盈利(%)', '胜率(%)'] },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', data: displayNames },
    yAxis: [
      { type: 'value', name: '累计盈利(%)', axisLabel: { formatter: '{value}%' } },
      { type: 'value', name: '胜率(%)', max: 100, axisLabel: { formatter: '{value}%' } }
    ],
    series: [
      {
        name: '累计盈利(%)', type: 'bar',
        data: strategies.map(s => +(s.total_return ?? 0).toFixed(2)),
        itemStyle: {
          color: (params: any) => params.value >= 0 ? '#67c23a' : '#f56c6c'
        },
        label: { show: true, position: 'top', formatter: '{c}%', fontSize: 11 }
      },
      {
        name: '胜率(%)', type: 'bar', yAxisIndex: 1,
        data: strategies.map(s => +(s.win_rate ?? 0).toFixed(1)),
        itemStyle: { color: '#409eff' },
        label: { show: true, position: 'top', formatter: '{c}%', fontSize: 11 }
      }
    ]
  }
})

// F2: 策略交易笔数柱状图
const strategyTradesChartOption = computed(() => {
  const result = props.result
  if (!result?.strategy_results) return null
  const sr = result.strategy_results
  const names = Object.keys(sr)
  if (names.length === 0) return null
  const strategies = Object.values(sr) as any[]
  const displayNames = names.map(n => strategyDisplayName(n))

  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', data: displayNames },
    yAxis: { type: 'value', name: '笔数' },
    series: [
      {
        name: '交易笔数', type: 'bar',
        data: strategies.map(s => s.trades_count ?? 0),
        itemStyle: { color: '#e6a23c' },
        label: { show: true, position: 'top', fontSize: 12 }
      }
    ]
  }
})

// ==================== F1: 盈亏分布图 ====================
const profitDistChartOption = computed(() => {
  const trades = allTrades.value.filter((t: any) => t.profit_pct != null && t.sell_date)
  if (trades.length === 0) return null

  // 分桶: <-5%, -5~-2%, -2~0%, 0~2%, 2~5%, 5~10%, >10%
  const buckets = ['<-5%', '-5~-2%', '-2~0%', '0~2%', '2~5%', '5~10%', '>10%']
  const counts = [0, 0, 0, 0, 0, 0, 0]
  trades.forEach((t: any) => {
    const p = t.profit_pct
    if (p < -5) counts[0]++
    else if (p < -2) counts[1]++
    else if (p < 0) counts[2]++
    else if (p < 2) counts[3]++
    else if (p < 5) counts[4]++
    else if (p < 10) counts[5]++
    else counts[6]++
  })

  return {
    tooltip: { trigger: 'axis' },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', data: buckets },
    yAxis: { type: 'value', name: '笔数' },
    series: [{
      type: 'bar', data: counts,
      itemStyle: {
        color: (params: any) => {
          const idx = params.dataIndex
          return idx < 3 ? '#f56c6c' : idx === 3 ? '#e6a23c' : '#67c23a'
        }
      },
      label: { show: true, position: 'top', fontSize: 12 }
    }]
  }
})

// F1: 持仓时长分布图
const holdDaysChartOption = computed(() => {
  const trades = allTrades.value.filter((t: any) => t.hold_days != null && t.sell_date)
  if (trades.length === 0) return null

  // 按持仓天数统计
  const dayMap: Record<number, number> = {}
  trades.forEach((t: any) => {
    const d = t.hold_days
    dayMap[d] = (dayMap[d] || 0) + 1
  })
  const sortedDays = Object.keys(dayMap).map(Number).sort((a, b) => a - b)
  const labels = sortedDays.map(d => d + '天')
  const values = sortedDays.map(d => dayMap[d])

  // 平均胜率按天数
  const winRateByDay: number[] = []
  sortedDays.forEach(d => {
    const dayTrades = trades.filter((t: any) => t.hold_days === d)
    const wins = dayTrades.filter((t: any) => t.profit_pct > 0).length
    winRateByDay.push(dayTrades.length > 0 ? +(wins / dayTrades.length * 100).toFixed(1) : 0)
  })

  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['交易笔数', '胜率(%)'] },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', data: labels },
    yAxis: [
      { type: 'value', name: '笔数' },
      { type: 'value', name: '胜率(%)', max: 100, axisLabel: { formatter: '{value}%' } }
    ],
    series: [
      {
        name: '交易笔数', type: 'bar', data: values,
        itemStyle: { color: '#409eff' },
        label: { show: true, position: 'top', fontSize: 12 }
      },
      {
        name: '胜率(%)', type: 'line', yAxisIndex: 1, data: winRateByDay,
        lineStyle: { color: '#67c23a', width: 2 },
        itemStyle: { color: '#67c23a' }
      }
    ]
  }
})

// 月度收益: 统一使用 monthlyReturnChartOption (基于net_value_series计算)
// 保留monthlyProfitChartOption仅作为调试参考
const _monthlyProfitChartOption = computed(() => {
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
    { name: '信息比率', value: risk.information_ratio != null ? risk.information_ratio.toFixed(2) : '暂未计算', desc: '超额收益与跟踪误差的比值' },
    { name: '胜率', value: fmtPct(risk.win_rate_pct ?? result.win_rate), desc: '盈利交易占总交易的比例' },
    { name: '盈亏比', value: (risk.profit_loss_ratio ?? result.profit_loss_ratio ?? 0).toFixed(2), desc: '平均盈利/平均亏损的比值' },
    { name: '最大回撤', value: fmtPct(risk.max_drawdown_pct ?? result.max_drawdown), desc: '净值从最高点到最低点的最大跌幅' },
    { name: '夏普比率', value: (risk.sharpe_ratio ?? result.sharpe_ratio ?? 0).toFixed(2), desc: '单位风险获得的超额收益' },
    { name: '卡玛比率', value: (risk.calmar_ratio ?? result.calmar_ratio ?? 0).toFixed(2), desc: '年化收益/最大回撤' + ((result?.net_value_series?.length || 0) < 250 ? '（短期回测该值虚高）' : '') },
    { name: '索提诺比率', value: (risk.sortino_ratio ?? result.sortino_ratio ?? 0).toFixed(2), desc: '只考虑下行风险的夏普比率' },
    { name: '基准收益', value: fmtPct(ret.benchmark_return_pct), desc: '沪深300同期收益' },
    { name: '超额收益', value: fmtPct(ret.alpha_pct), desc: '组合收益减去基准(沪深300)收益' },
  ]
})

// 导出CSV
function exportTrades() {
  const trades = allTrades.value
  if (!trades || trades.length === 0) {
    ElMessage.warning('暂无交易记录可导出')
    return
  }
  const headers = ['买入日期', '卖出日期', '股票代码', '股票名称', '策略', '买入价', '卖出价', '收益率(%)', '盈亏额', '持仓天数', '卖出原因']
  const rows = trades.map((t: any) => [
    t.buy_date || t.date || '', t.sell_date || '', t.ts_code || '', t.name || t.stock_name || '',
    STRATEGY_NAMES[t.strategy] || t.strategy || '', t.buy_price ?? '', t.sell_price ?? '',
    t.profit_pct != null ? t.profit_pct.toFixed(2) : '-',
    (t.profit_pct != null && t.shares && t.buy_price) ? (t.buy_price * t.shares * t.profit_pct / 100).toFixed(0) : '-',
    t.hold_days ?? 1, translateSellReason(t.sell_reason || t.reason)
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
    <!-- 核心指标卡片(永远显示在顶部) -->
    <div class="kpi-strip">
      <div class="kpi-chip">
        <span class="kpi-label">累计收益</span>
        <span class="kpi-value" :style="{ color: (result.total_return || 0) >= 0 ? '#67c23a' : '#f56c6c' }">
          {{ fmtPct(result.total_return) }}
        </span>
      </div>
      <div class="kpi-chip">
        <span class="kpi-label">年化收益<template v-if="(result?.net_value_series?.length || 0) < 250"><ElTooltip content="回测期不足1年，年化收益存在放大效应，仅供参考" placement="top"><span class="annual-warn"> *</span></ElTooltip></template></span>
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
      <div class="kpi-chip">
        <span class="kpi-label">盈亏比</span>
        <span class="kpi-value" :style="{ color: (result.profit_loss_ratio || 0) >= 2 ? '#67c23a' : '#e6a23c' }">
          {{ (result.profit_loss_ratio || 0).toFixed(2) }}
        </span>
      </div>
    </div>

    <!-- 任务3: 卖出原因统计 -->
    <div v-if="result?.sell_reason_stats" class="sell-reason-bar">
      <span class="sell-reason-label">卖出分布</span>
      <div class="sell-reason-items">
        <span v-if="result.sell_reason_stats.take_profit > 0" class="sell-reason-item take-profit">
          <span class="reason-dot"></span>止盈{{ result.sell_reason_stats.take_profit }}笔({{ sellReasonPct('take_profit') }}%)
        </span>
        <span v-if="result.sell_reason_stats.profit_lock > 0" class="sell-reason-item rebalance">
          <span class="reason-dot"></span>利润锁{{ result.sell_reason_stats.profit_lock }}笔({{ sellReasonPct('profit_lock') }}%)
        </span>
        <span v-if="result.sell_reason_stats.rebalance > 0" class="sell-reason-item rebalance">
          <span class="reason-dot"></span>调仓{{ result.sell_reason_stats.rebalance }}笔({{ sellReasonPct('rebalance') }}%)
        </span>
        <span v-if="result.sell_reason_stats.stop_loss > 0" class="sell-reason-item stop-loss">
          <span class="reason-dot"></span>止损{{ result.sell_reason_stats.stop_loss }}笔({{ sellReasonPct('stop_loss') }}%)
        </span>
        <span v-if="result.sell_reason_stats.force_empty > 0" class="sell-reason-item force-empty">
          <span class="reason-dot"></span>空仓{{ result.sell_reason_stats.force_empty }}笔({{ sellReasonPct('force_empty') }}%)
        </span>
        <span v-if="result.sell_reason_stats.max_hold > 0" class="sell-reason-item max-hold">
          <span class="reason-dot"></span>到期{{ result.sell_reason_stats.max_hold }}笔({{ sellReasonPct('max_hold') }}%)
        </span>
        <span v-if="result.sell_reason_stats.other > 0" class="sell-reason-item other">
          <span class="reason-dot"></span>其他{{ result.sell_reason_stats.other }}笔({{ sellReasonPct('other') }}%)
        </span>
      </div>
    </div>

    <!-- ========== 顶层大Tab：5个核心视图 ========== -->
    <ElCard style="margin-top: 12px">
      <ElTabs v-model="activeMainTab" type="border-card">

        <!-- Tab 1: 图表总览 -->
        <ElTabPane label="📈 图表总览" name="charts">
          <ElTabs>
            <ElTabPane label="净值曲线">
              <VChart v-if="netValueChartOption" :option="netValueChartOption" autoresize style="height: 400px; width: 100%" />
              <ElEmpty v-else description="暂无净值数据" />
            </ElTabPane>
            <ElTabPane label="日收益">
              <VChart v-if="dailyProfitChartOption" :option="dailyProfitChartOption" autoresize style="height: 400px; width: 100%" />
              <ElEmpty v-else description="暂无日收益数据" />
            </ElTabPane>
            <ElTabPane label="仓位">
              <VChart v-if="positionChartOption" :option="positionChartOption" autoresize style="height: 400px; width: 100%" />
              <ElEmpty v-else description="暂无仓位数据" />
            </ElTabPane>
            <ElTabPane label="雷达图">
              <VChart v-if="radarChartOption" :option="radarChartOption" autoresize style="height: 400px; width: 100%" />
              <ElEmpty v-else description="暂无雷达数据" />
            </ElTabPane>
            <ElTabPane label="交易占比" name="factor_contribution">
              <VChart v-if="factorContributionChartOption" :option="factorContributionChartOption" autoresize style="height: 400px; width: 100%" />
              <ElEmpty v-else description="暂无交易占比数据" />
            </ElTabPane>
            <ElTabPane label="月度收益" name="monthly_profit">
              <VChart v-if="monthlyReturnChartOption" :option="monthlyReturnChartOption" autoresize style="height: 350px; width: 100%" />
              <ElEmpty v-else description="暂无月度数据" />
            </ElTabPane>
          </ElTabs>
        </ElTabPane>

        <!-- Tab 2: 策略对比 -->
        <ElTabPane label="🔄 策略对比" name="strategy">
          <div v-if="result?.strategy_results && Object.keys(result.strategy_results).length >= 2">
            <!-- 收益/胜率对比柱状图 -->
            <VChart v-if="strategyBarChartOption" :option="strategyBarChartOption" autoresize style="height: 350px; width: 100%" />
            <!-- 交易笔数 -->
            <VChart v-if="strategyTradesChartOption" :option="strategyTradesChartOption" autoresize style="height: 250px; width: 100%; margin-top: 16px" />
            <!-- 雷达图 -->
            <VChart v-if="strategyCompareChartOption" :option="strategyCompareChartOption" autoresize style="height: 350px; width: 100%; margin-top: 16px" />
            <!-- 策略KPI对比表 -->
            <ElTable :data="Object.entries(result.strategy_results).map(([name, d]: any) => ({ name, ...d }))" size="small" border stripe style="margin-top: 12px">
              <ElTableColumn label="策略名称" width="120">
                <template #default="{ row }">{{ strategyDisplayName(row.name) }}</template>
              </ElTableColumn>
              <ElTableColumn label="累计盈利" width="100">
                <template #default="{ row }">
                  <span :style="{ color: row.total_return >= 0 ? '#67c23a' : '#f56c6c' }">{{ fmtPct(row.total_return) }}</span>
                </template>
              </ElTableColumn>
              <ElTableColumn label="胜率" width="80">
                <template #default="{ row }">{{ fmtPct(row.win_rate) }}</template>
              </ElTableColumn>
              <ElTableColumn prop="trades_count" label="交易次数" width="80" />
              <ElTableColumn label="最大回撤" width="100">
                <template #default="{ row }">
                  <span style="color: #f56c6c">{{ fmtPct(row.max_drawdown) }}</span>
                </template>
              </ElTableColumn>
              <ElTableColumn label="单笔均利" width="100">
                <template #default="{ row }">
                  <span v-if="row.trades_count > 0" :style="{ color: row.avg_profit_pct >= 0 ? '#67c23a' : '#f56c6c' }">{{ fmtPct(row.avg_profit_pct) }}</span>
                  <span v-else>-</span>
                </template>
              </ElTableColumn>
              <ElTableColumn label="盈亏比" width="80">
                <template #default="{ row }">
                  <span v-if="row.profit_loss_ratio">{{ row.profit_loss_ratio.toFixed(2) }}</span>
                  <span v-else>-</span>
                </template>
              </ElTableColumn>
            </ElTable>
          </div>
          <ElEmpty v-else description="至少启用2个策略才显示对比" />
        </ElTabPane>

        <!-- Tab 3: 交易记录 -->
        <ElTabPane label="📋 交易记录" name="trades">
          <div class="filter-bar">
            <ElInput v-model="searchTradeKeyword" placeholder="搜索代码/名称" size="small" style="width: 200px" clearable />
            <ElSelect v-model="filterStrategy" placeholder="策略筛选" size="small" style="width: 140px" clearable>
              <ElOption v-for="s in availableStrategies" :key="s" :label="strategyDisplayName(s)" :value="s" />
            </ElSelect>
            <ElSelect v-model="filterProfit" placeholder="盈亏筛选" size="small" style="width: 120px" clearable>
              <ElOption label="盈利" value="profit" />
              <ElOption label="亏损" value="loss" />
            </ElSelect>
            <ElButton size="small" :icon="Download" @click="exportTrades">导出表格</ElButton>
          </div>
          <!-- 盈亏分布+持仓时长小图 -->
          <div style="display: flex; gap: 16px; margin-bottom: 12px">
            <div v-if="profitDistChartOption" style="flex: 1">
              <div style="font-size: 13px; font-weight: 600; margin-bottom: 4px">📊 盈亏分布</div>
              <VChart :option="profitDistChartOption" autoresize style="height: 220px; width: 100%" />
            </div>
            <div v-if="holdDaysChartOption" style="flex: 1">
              <div style="font-size: 13px; font-weight: 600; margin-bottom: 4px">⏱️ 持仓时长</div>
              <VChart :option="holdDaysChartOption" autoresize style="height: 220px; width: 100%" />
            </div>
          </div>
          <!-- 盈亏TOP5 -->
          <div class="top5-row" style="margin-bottom: 12px">
            <div class="top5-card">
              <div style="font-size: 13px; font-weight: 600; color: #67c23a; margin-bottom: 4px">🏆 盈利TOP5</div>
              <ElTable v-if="profitTop5.length > 0" :data="profitTop5" size="small" border>
                <ElTableColumn prop="ts_code" label="代码" width="100" />
                <ElTableColumn label="名称" width="80">
                  <template #default="{ row }">{{ row.name || row.stock_name || row.ts_code }}</template>
                </ElTableColumn>
                <ElTableColumn label="策略" width="100">
              <template #default="{ row }">{{ strategyDisplayName(row.strategy) }}</template>
            </ElTableColumn>
                <ElTableColumn label="收益率" width="90">
                  <template #default="{ row }">
                    <span style="color: #67c23a">{{ fmtPct(row.profit_pct) }}</span>
                  </template>
                </ElTableColumn>
              </ElTable>
              <ElEmpty v-else description="无盈利交易" :image-size="40" />
            </div>
            <div class="top5-card">
              <div style="font-size: 13px; font-weight: 600; color: #f56c6c; margin-bottom: 4px">💥 亏损TOP5</div>
              <ElTable v-if="lossTop5.length > 0" :data="lossTop5" size="small" border>
                <ElTableColumn prop="ts_code" label="代码" width="100" />
                <ElTableColumn label="名称" width="80">
                  <template #default="{ row }">{{ row.name || row.stock_name || row.ts_code }}</template>
                </ElTableColumn>
                <ElTableColumn label="策略" width="100">
              <template #default="{ row }">{{ strategyDisplayName(row.strategy) }}</template>
            </ElTableColumn>
                <ElTableColumn label="收益率" width="90">
                  <template #default="{ row }">
                    <span style="color: #f56c6c">{{ fmtPct(row.profit_pct) }}</span>
                  </template>
                </ElTableColumn>
              </ElTable>
              <ElEmpty v-else description="无亏损交易" :image-size="40" />
            </div>
          </div>
          <!-- 交易记录表格 -->
          <ElTable :data="filteredTrades" size="small" border stripe max-height="500">
            <ElTableColumn label="买入日" width="100" sortable>
              <template #default="{ row }">{{ row.buy_date || row.date }}</template>
            </ElTableColumn>
            <ElTableColumn label="卖出日" width="100">
              <template #default="{ row }">{{ row.sell_date || '-' }}</template>
            </ElTableColumn>
            <ElTableColumn prop="ts_code" label="代码" width="100" />
            <ElTableColumn label="名称" width="80">
              <template #default="{ row }">{{ row.name || row.stock_name || '-' }}</template>
            </ElTableColumn>
            <ElTableColumn label="策略" width="100">
              <template #default="{ row }">{{ strategyDisplayName(row.strategy) }}</template>
            </ElTableColumn>
            <ElTableColumn label="买入价" width="80">
              <template #default="{ row }">{{ row.buy_price?.toFixed(2) ?? '-' }}</template>
            </ElTableColumn>
            <ElTableColumn label="卖出价" width="80">
              <template #default="{ row }">{{ row.sell_price?.toFixed(2) ?? '-' }}</template>
            </ElTableColumn>
            <ElTableColumn label="盈亏额" width="110" sortable>
              <template #default="{ row }">
                <template v-if="row.profit_pct != null && row.shares && row.buy_price">
                  <span :style="{ color: row.profit_pct > 0 ? '#67c23a' : '#f56c6c' }">
                    ¥{{ (row.buy_price * row.shares * row.profit_pct / 100).toFixed(0) }}
                  </span>
                </template>
                <span v-else>-</span>
              </template>
            </ElTableColumn>
            <ElTableColumn label="收益率" width="90" sortable>
              <template #default="{ row }">
                <span :style="{ color: row.profit_pct > 0 ? '#67c23a' : '#f56c6c' }">
                  {{ fmtPct(row.profit_pct) }}
                </span>
              </template>
            </ElTableColumn>
            <ElTableColumn label="持仓天数" width="80" sortable>
              <template #default="{ row }">{{ row.hold_days ?? '-' }}</template>
            </ElTableColumn>
            <ElTableColumn label="股数" width="70">
              <template #default="{ row }">{{ row.shares ?? '-' }}</template>
            </ElTableColumn>
            <!-- 任务3: 卖出原因列(中文翻译) -->
            <ElTableColumn label="卖出原因" width="100">
              <template #default="{ row }">
                <span v-if="translateSellReason(row.sell_reason || row.reason) === '持仓中'" style="color: #e6a23c; font-weight: 600">持仓中</span>
                <span v-else>{{ translateSellReason(row.sell_reason || row.reason) }}</span>
              </template>
            </ElTableColumn>
          </ElTable>
        </ElTabPane>

        <!-- Tab 4: 月度归因 -->
        <ElTabPane label="📅 月度归因" name="monthly">
          <div v-if="monthlyData.length > 0">
            <div style="font-size: 13px; font-weight: 600; margin-bottom: 4px">📊 月度收益分布</div>
            <VChart v-if="monthlyReturnChartOption" :option="monthlyReturnChartOption" autoresize style="height: 350px; width: 100%" />
            <ElTable :data="monthlyMergedData" size="small" border stripe style="margin-top: 16px">
              <ElTableColumn prop="month" label="月份" width="100" />
              <ElTableColumn label="月度收益" width="100" sortable>
                <template #default="{ row }">
                  <span :style="{ color: row.return_pct >= 0 ? '#67c23a' : '#f56c6c' }">{{ row.return_pct.toFixed(2) }}%</span>
                </template>
              </ElTableColumn>
              <ElTableColumn prop="trades" label="交易笔数" width="100" sortable />
              <ElTableColumn label="胜率" width="80">
                <template #default="{ row }">{{ row.win_rate.toFixed(1) }}%</template>
              </ElTableColumn>
            </ElTable>
          </div>
          <ElEmpty v-else description="暂无月度数据" />
        </ElTabPane>

        <!-- Tab 5: 风险指标 -->
        <ElTabPane label="🛡️ 风险指标" name="risk">
          <div class="risk-grid">
            <div v-for="m in riskMetrics" :key="m.name" class="risk-item">
              <span class="risk-name">{{ m.name }}</span>
              <span class="risk-value">{{ m.value }}</span>
              <span class="risk-desc">{{ m.desc }}</span>
            </div>
          </div>
        </ElTabPane>

      </ElTabs>
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
  gap: 8px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.kpi-chip {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 10px 16px;
  border-radius: 8px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-default);
  min-width: 90px;
  transition: box-shadow 0.2s, border-color 0.2s;
  &:hover {
    box-shadow: var(--shadow-sm);
    border-color: var(--border-hover);
  }
}
.kpi-label { font-size: 11px; color: var(--text-tertiary); font-weight: 500; }
.kpi-value { font-size: 17px; font-weight: 700; margin-top: 2px; font-variant-numeric: tabular-nums; }
.annual-warn { color: #e6a23c; cursor: help; font-weight: 700; }
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
.risk-name { font-weight: 600; font-size: 13px; color: var(--text-primary); }
.risk-value { margin-left: 8px; font-size: 14px; color: var(--primary-500); }
.risk-desc { display: block; font-size: 11px; color: var(--text-muted); margin-top: 2px; }
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
.sell-reason-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 10px 16px;
  margin-bottom: 16px;
  background: var(--bg-muted);
  border-radius: 8px;
  border: 1px solid var(--border-default);
  font-size: 13px;
  .sell-reason-label {
    font-weight: 700;
    color: var(--text-primary);
    font-size: 14px;
    flex-shrink: 0;
  }
  .sell-reason-items {
    display: flex;
    gap: 14px;
    flex-wrap: wrap;
  }
  .sell-reason-item {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 3px 10px;
    border-radius: 12px;
    background: var(--bg-elevated);
    border: 1px solid var(--border-default);
    font-weight: 500;
    .reason-dot {
      display: inline-block;
      width: 8px;
      height: 8px;
      border-radius: 50%;
    }
    &.take-profit { color: #67c23a; .reason-dot { background: #67c23a; } }
    &.rebalance { color: #409eff; .reason-dot { background: #409eff; } }
    &.stop-loss { color: #f56c6c; .reason-dot { background: #f56c6c; } }
    &.max-hold { color: #e6a23c; .reason-dot { background: #e6a23c; } }
    &.force-empty { color: #909399; .reason-dot { background: #909399; } }
    &.other { color: #c0c4cc; .reason-dot { background: #c0c4cc; } }
  }
}
</style>
