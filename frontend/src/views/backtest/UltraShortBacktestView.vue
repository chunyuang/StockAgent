<script setup lang="ts">
/**
 * 超短策略回测页面
 * 专门针对5大超短策略：半路追涨、首板打板、涨停开板、龙头低吸、跌停翘板
 */
import { ref, reactive, onMounted, computed, watch, nextTick } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart, BarChart, RadarChart, PieChart } from 'echarts/charts'
import {
  TitleComponent,
  TooltipComponent,
  GridComponent,
  LegendComponent,
  DataZoomComponent,
  RadarComponent
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

// 注册ECharts组件
echarts.use([
  TitleComponent,
  TooltipComponent,
  GridComponent,
  LegendComponent,
  DataZoomComponent,
  RadarComponent,
  LineChart,
  BarChart,
  RadarChart,
  PieChart,
  CanvasRenderer
])
import {
  ElCard,
  ElForm,
  ElFormItem,
  ElInput,
  ElInputNumber,
  ElButton,
  ElCheckboxGroup,
  ElCheckbox,
  ElCollapse,
  ElCollapseItem,
  ElTabs,
  ElTabPane,
  ElTable,
  ElTableColumn,
  ElProgress,
  ElAlert,
  ElEmpty,
} from 'element-plus'
import {
  VideoPlay as Play,
  CircleClose as Stop,
  Download,
  Document,
} from '@element-plus/icons-vue'
import { backtestApi } from '@/api'
import { useWebSocket } from '@vueuse/core'

// 移除未使用的导入

// ==================== 状态 ====================

// 表单数据
const form = reactive({
  // 策略选择
  strategies: ['halfway_chase'], // 默认选中半路追涨
  // 时间范围
  start_date: '20260105',
  end_date: '20260320',
  // 初始资金
  initial_cash: 1000000,
  // 参数配置
  params: {
    liquidity_threshold: 500, // 流动性门槛：万元
    volume_threshold: 1.5, // 量能放大倍数
    stop_loss_pct: 0.05, // 止损比例
    take_profit_pct: 0.1, // 止盈比例
    max_hold_days: 3, // 最大持仓天数
    max_position_per_stock: 0.2, // 单票最大仓位
    max_position: 0.7, // 总仓位上限
  },
  // 高级设置
  enable_force_empty: true, // 启用强制空仓
  enable_sentiment_cycle: true, // 启用情绪周期
  enable_auction_filter: true, // 启用竞价过滤
})

// 策略列表
const strategyOptions = [
  { label: '🚀 半路追涨', value: 'halfway_chase' },
  { label: '🚀 首板打板', value: 'first_limit_up' },
  { label: '🚀 涨停开板', value: 'limit_up_open' },
  { label: '🚀 龙头低吸', value: 'leader_buy_dip' },
  { label: '🚀 跌停翘板', value: 'limit_down_翘板' },
]

// 回测状态
const backtestState = reactive({
  running: false,
  task_id: '',
  progress: 0,
  status: 'idle', // idle / running / completed / failed
  logs: [] as string[],
  result: null as any,
})

// WebSocket连接
const { status: wsStatus, send: wsSend, data: wsData } = useWebSocket(
  () => {
    const token = localStorage.getItem('access_token')
    return `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws?token=${token}`
  },
  {
    autoReconnect: true,
    heartbeat: {
      message: JSON.stringify({ type: 'ping' }),
      interval: 30000,
    },
  }
)

// 表单验证规则
const rules = {
  strategies: [
    { required: true, message: '请选择至少一个策略', trigger: 'change' },
  ],
  start_date: [
    { required: true, message: '请选择开始日期', trigger: 'change' },
  ],
  end_date: [
    { required: true, message: '请选择结束日期', trigger: 'change' },
  ],
  initial_cash: [
    { required: true, message: '请输入初始资金', trigger: 'blur' },
    { type: 'number' as const, min: 10000, max: 100000000, message: '初始资金范围1万-1亿', trigger: 'blur' },
  ],
}

// 折叠面板激活项
const activeCollapse = ref('params')
// 标签页激活项
const activeTab = ref('metrics')
// 策略结果列表（转成any避免类型错误）
const strategyResults = computed(() => {
  return Object.values(backtestState.result?.strategy_results || {}) as any[]
})

// 图表实例
let equityChart: echarts.ECharts | null = null
let positionChart: echarts.ECharts | null = null
let dailyProfitChart: echarts.ECharts | null = null
let strategyRadarChart: echarts.ECharts | null = null
let profitDistributionChart: echarts.ECharts | null = null
let factorContributionChart: echarts.ECharts | null = null

// 表格列
const tradeColumns = [
  { prop: 'ts_code', label: '股票代码', width: 120 },
  { prop: 'stock_name', label: '股票名称', width: 120 },
  { prop: 'strategy', label: '策略', width: 120 },
  { prop: 'buy_date', label: '买入日期', width: 120 },
  { prop: 'sell_date', label: '卖出日期', width: 120 },
  { prop: 'buy_price', label: '买入价格', width: 100 },
  { prop: 'sell_price', label: '卖出价格', width: 100 },
  { prop: 'profit_pct', label: '收益率', width: 100, formatter: (row: any) => `${(row.profit_pct * 100).toFixed(2)}%` },
  { prop: 'hold_days', label: '持仓天数', width: 100 },
  { prop: 'signal_reason', label: '信号触发原因', minWidth: 200 },
  { prop: 'entry_time', label: '入场时点', width: 120 },
  { prop: 'exit_reason', label: '离场原因', width: 150 },
]

// ==================== 计算属性 ====================

const canRun = computed(() => {
  return !backtestState.running && form.strategies.length > 0 && form.start_date && form.end_date
})

// ==================== 生命周期 ====================

onMounted(() => {
  // 监听WebSocket消息
  watch(wsData, (newData) => {
    if (!newData) return
    try {
      const msg = JSON.parse(newData)
      handleWsMessage(msg)
    } catch (e) {
      console.error('WebSocket消息解析失败', e)
    }
  })
})

// ==================== 方法 ====================

/**
 * 处理WebSocket消息
 */
function handleWsMessage(msg: any) {
  if (msg.type === 'task_update' && msg.task_id === backtestState.task_id) {
    // 任务进度更新
    if (msg.progress !== undefined) {
      backtestState.progress = msg.progress
    }
    // 日志消息
    if (msg.log) {
      const timestamp = new Date().toLocaleTimeString()
      backtestState.logs.push(`[${timestamp}] ${msg.log}`)
      // 自动滚动到底部
      nextTick(() => {
        const logEl = document.querySelector('.log-panel')
        if (logEl) {
          logEl.scrollTop = logEl.scrollHeight
        }
      })
    }
    // 状态更新
    if (msg.status) {
      backtestState.status = msg.status
      if (msg.status === 'completed') {
        backtestState.running = false
        backtestState.progress = 100
        addLog('✅ 回测完成！正在加载结果...')
        // 获取回测结果
        loadBacktestResult()
      } else if (msg.status === 'failed') {
        backtestState.running = false
        addLog(`❌ 回测失败：${msg.error || '未知错误'}`)
      }
    }
  }
}

/**
 * 添加日志
 */
function addLog(text: string) {
  const timestamp = new Date().toLocaleTimeString()
  backtestState.logs.push(`[${timestamp}] ${text}`)
}

/**
 * 运行回测
 */
async function runBacktest() {
  if (!canRun.value) return
  
  try {
    backtestState.running = true
    backtestState.status = 'running'
    backtestState.progress = 0
    backtestState.logs = []
    backtestState.result = null
    
    addLog('🚀 开始提交回测任务...')
    
    // 提交超短回测任务
    const res = await backtestApi.submitUltraShort({
      strategies: form.strategies,
      start_date: form.start_date,
      end_date: form.end_date,
      initial_cash: form.initial_cash,
      params: form.params,
      enable_force_empty: form.enable_force_empty,
      enable_sentiment_cycle: form.enable_sentiment_cycle,
      enable_auction_filter: form.enable_auction_filter,
    })
    
    backtestState.task_id = res.task_id
    addLog(`✅ 任务提交成功，任务ID：${res.task_id}`)
    
    // 订阅任务进度
    if (wsStatus.value === 'OPEN') {
      wsSend(JSON.stringify({
        type: 'subscribe',
        task_id: res.task_id,
      }))
      addLog('📡 已订阅任务实时进度')
    } else {
      addLog('⚠️ WebSocket未连接，将使用轮询获取进度')
      // 启动轮询
      startPolling()
    }
    
  } catch (e: any) {
    backtestState.running = false
    addLog(`❌ 任务提交失败：${e.message || '未知错误'}`)
  }
}

/**
 * 轮询获取进度（WebSocket不可用时备用）
 */
function startPolling() {
  const timer = setInterval(async () => {
    if (!backtestState.running) {
      clearInterval(timer)
      return
    }
    
    try {
      const res = await backtestApi.getBacktestStatus(backtestState.task_id) as any
      backtestState.progress = res.progress || 0
      
      // 如果有新日志
      if (res.logs && res.logs.length > backtestState.logs.length) {
        res.logs.slice(backtestState.logs.length).forEach((log: string) => {
          addLog(log)
        })
      }
      
      // 状态更新
      if (res.status === 'completed') {
        clearInterval(timer)
        backtestState.running = false
        backtestState.progress = 100
        addLog('✅ 回测完成！')
        loadBacktestResult()
      } else if (res.status === 'failed') {
        clearInterval(timer)
        backtestState.running = false
        addLog(`❌ 回测失败：${res.error || '未知错误'}`)
      }
      
    } catch (e) {
      console.error('轮询失败', e)
    }
  }, 2000)
}

/**
 * 加载回测结果
 */
async function loadBacktestResult() {
  try {
    addLog('📊 正在加载回测结果...')
    const res = await backtestApi.getBacktestResult(backtestState.task_id)
    backtestState.result = res
    addLog('✅ 结果加载完成！')
    
    // 渲染图表
    nextTick(() => {
      renderCharts()
    })
  } catch (e: any) {
    addLog(`❌ 结果加载失败：${e.message || '未知错误'}`)
  }
}

/**
 * 停止回测
 */
async function stopBacktest() {
  if (!backtestState.running || !backtestState.task_id) return
  
  try {
    await backtestApi.cancelBacktest(backtestState.task_id)
    backtestState.running = false
    backtestState.status = 'cancelled'
    addLog('⏹️ 回测已取消')
  } catch (e: any) {
    addLog(`❌ 取消失败：${e.message || '未知错误'}`)
  }
}

/**
 * 导出报告
 */
function exportReport() {
  // 待实现
  alert('导出功能开发中...')
}

/**
 * 渲染所有图表
 */
function renderCharts() {
  if (!backtestState.result) return
  
  // 渲染收益+回撤组合图
  renderEquityChart()
  // 渲染仓位变化图
  renderPositionChart()
  // 渲染每日盈亏图
  renderDailyProfitChart()
  
  // 高级分析图表
  nextTick(() => {
    // 策略对比雷达图（多个策略时渲染）
    if (form.strategies.length > 1) {
      renderStrategyRadarChart()
    }
    // 收益分布直方图
    renderProfitDistributionChart()
    // 因子贡献分析图
    renderFactorContributionChart()
  })
}

/**
 * 渲染收益+回撤组合图
 */
function renderEquityChart() {
  const dom = document.getElementById('equity-chart')
  if (!dom) return
  
  equityChart = echarts.init(dom)
  
  const data = backtestState.result.daily_data || []
  const dates = data.map((item: any) => item.trade_date)
  const equity = data.map((item: any) => (item.equity / form.initial_cash - 1) * 100)
  const drawdown = data.map((item: any) => -item.drawdown * 100)
  
  const option = {
    title: { text: '收益曲线 & 回撤曲线', left: 'center' },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' }
    },
    legend: { data: ['累计收益率', '最大回撤'], top: 30 },
    grid: { left: '3%', right: '4%', bottom: '15%', containLabel: true },
    dataZoom: [{ type: 'inside', start: 0, end: 100 }, { start: 0, end: 100, bottom: 10 }],
    xAxis: { type: 'category', boundaryGap: false, data: dates },
    yAxis: [
      { type: 'value', name: '收益率(%)', axisLabel: { formatter: '{value}%' } },
      { type: 'value', name: '回撤(%)', axisLabel: { formatter: '{value}%' }, min: -100, max: 0 }
    ],
    series: [
      {
        name: '累计收益率',
        type: 'line',
        yAxisIndex: 0,
        data: equity,
        smooth: true,
        lineStyle: { color: '#f56c6c', width: 2 },
        itemStyle: { color: '#f56c6c' },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(245, 108, 108, 0.3)' },
            { offset: 1, color: 'rgba(245, 108, 108, 0.05)' }
          ])
        }
      },
      {
        name: '最大回撤',
        type: 'line',
        yAxisIndex: 1,
        data: drawdown,
        smooth: true,
        lineStyle: { color: '#e6a23c', width: 2 },
        itemStyle: { color: '#e6a23c' },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(230, 162, 60, 0.3)' },
            { offset: 1, color: 'rgba(230, 162, 60, 0.05)' }
          ])
        }
      }
    ]
  }
  
  equityChart.setOption(option)
  // 自适应
  window.addEventListener('resize', () => equityChart?.resize())
}

/**
 * 渲染仓位变化图
 */
function renderPositionChart() {
  const dom = document.getElementById('position-chart')
  if (!dom) return
  
  positionChart = echarts.init(dom)
  
  const data = backtestState.result.daily_data || []
  const dates = data.map((item: any) => item.trade_date)
  const position = data.map((item: any) => item.position_ratio * 100)
  
  const option = {
    title: { text: '仓位变化趋势', left: 'center' },
    tooltip: { trigger: 'axis' },
    grid: { left: '3%', right: '4%', bottom: '15%', containLabel: true },
    dataZoom: [{ type: 'inside', start: 0, end: 100 }, { start: 0, end: 100, bottom: 10 }],
    xAxis: { type: 'category', boundaryGap: false, data: dates },
    yAxis: { 
      type: 'value', 
      name: '仓位比例(%)', 
      axisLabel: { formatter: '{value}%' },
      min: 0,
      max: 100
    },
    series: [
      {
        name: '仓位比例',
        type: 'line',
        data: position,
        smooth: true,
        step: 'end',
        lineStyle: { color: '#409eff', width: 2 },
        itemStyle: { color: '#409eff' },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(64, 158, 255, 0.3)' },
            { offset: 1, color: 'rgba(64, 158, 255, 0.05)' }
          ])
        }
      }
    ]
  }
  
  positionChart.setOption(option)
  window.addEventListener('resize', () => positionChart?.resize())
}

/**
 * 渲染每日盈亏柱状图
 */
function renderDailyProfitChart() {
  const dom = document.getElementById('daily-profit-chart')
  if (!dom) return
  
  dailyProfitChart = echarts.init(dom)
  
  const data = backtestState.result.daily_data || []
  const dates = data.map((item: any) => item.trade_date)
  const profit = data.map((item: any) => item.daily_profit_pct * 100)
  
  const option = {
    title: { text: '每日盈亏', left: 'center' },
    tooltip: { trigger: 'axis' },
    grid: { left: '3%', right: '4%', bottom: '15%', containLabel: true },
    dataZoom: [{ type: 'inside', start: 0, end: 100 }, { start: 0, end: 100, bottom: 10 }],
    xAxis: { type: 'category', data: dates, axisLabel: { rotate: 45 } },
    yAxis: { 
      type: 'value', 
      name: '日收益率(%)', 
      axisLabel: { formatter: '{value}%' }
    },
    series: [
      {
        name: '日收益率',
        type: 'bar',
        data: profit,
        itemStyle: {
          color: (params: any) => {
            return params.value >= 0 ? '#f56c6c' : '#67c23a'
          }
        }
      }
    ]
  }
  
  dailyProfitChart.setOption(option)
  window.addEventListener('resize', () => dailyProfitChart?.resize())
}

/**
 * 渲染策略对比雷达图
 */
function renderStrategyRadarChart() {
  const dom = document.getElementById('strategy-radar-chart')
  if (!dom || strategyResults.value.length === 0) return
  
  strategyRadarChart = echarts.init(dom)
  
  // 雷达图维度
  const indicators = [
    { name: '收益率', max: 2 },
    { name: '胜率', max: 1 },
    { name: '盈亏比', max: 5 },
    { name: '夏普比率', max: 5 },
    { name: '最大回撤', max: 0.5, inverse: true }
  ]
  
  // 构造数据
  const seriesData = strategyResults.value.map(item => ({
    name: item.strategy_name,
    value: [
      item.total_return || 0,
      item.win_rate || 0,
      item.profit_loss_ratio || 0,
      item.sharpe_ratio || 1,
      item.max_drawdown || 0
    ]
  }))
  
  const option = {
    title: { text: '多策略绩效对比', left: 'center' },
    tooltip: { trigger: 'item' },
    legend: { data: seriesData.map(s => s.name), bottom: 10 },
    radar: {
      indicator: indicators,
      center: ['50%', '50%'],
      radius: '60%'
    },
    series: [
      {
        type: 'radar',
        data: seriesData
      }
    ]
  }
  
  strategyRadarChart.setOption(option)
  window.addEventListener('resize', () => strategyRadarChart?.resize())
}

/**
 * 渲染收益分布直方图
 */
function renderProfitDistributionChart() {
  const dom = document.getElementById('profit-distribution-chart')
  if (!dom) return
  
  profitDistributionChart = echarts.init(dom)
  
  // 模拟交易收益数据，按收益率区间分组
  const trades = backtestState.result?.trades || []
  const profitPcts = trades.map((t: any) => t.profit_pct * 100)
  
  // 统计区间分布
  const bins = [-10, -8, -6, -4, -2, 0, 2, 4, 6, 8, 10]
  const counts = new Array(bins.length - 1).fill(0)
  
  profitPcts.forEach((pct: number) => {
    for (let i = 0; i < bins.length - 1; i++) {
      if (pct >= bins[i] && pct < bins[i + 1]) {
        counts[i]++
        break
      }
    }
  })
  
  const option = {
    title: { text: '交易收益率分布', left: 'center' },
    tooltip: { trigger: 'axis' },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: {
      type: 'category',
      data: bins.slice(0, -1).map((b, i) => `${b}%~${bins[i+1]}%`),
      axisLabel: { rotate: 45 }
    },
    yAxis: { type: 'value', name: '交易次数' },
    series: [
      {
        type: 'bar',
        data: counts,
        itemStyle: {
          color: (params: any) => {
            const rangeStart = bins[params.dataIndex]
            return rangeStart >= 0 ? '#f56c6c' : '#67c23a'
          }
        }
      }
    ]
  }
  
  profitDistributionChart.setOption(option)
  window.addEventListener('resize', () => profitDistributionChart?.resize())
}

/**
 * 渲染因子贡献分析图
 */
function renderFactorContributionChart() {
  const dom = document.getElementById('factor-contribution-chart')
  if (!dom) return
  
  factorContributionChart = echarts.init(dom)
  
  // 模拟因子贡献数据（实际应从接口返回）
  const factorData = [
    { name: '一月反转', value: 35 },
    { name: '量能因子', value: 22 },
    { name: '波动率', value: 18 },
    { name: '流动性', value: 12 },
    { name: '技术指标', value: 8 },
    { name: '其他', value: 5 }
  ]
  
  const option = {
    title: { text: '因子贡献占比', left: 'center' },
    tooltip: { trigger: 'item', formatter: '{b}: {c}% ({d}%)' },
    legend: { orient: 'vertical', left: 'left' },
    series: [
      {
        type: 'pie',
        radius: ['40%', '70%'],
        avoidLabelOverlap: false,
        itemStyle: { borderRadius: 10, borderColor: '#fff', borderWidth: 2 },
        label: { show: false, position: 'center' },
        emphasis: {
          label: { show: true, fontSize: '16', fontWeight: 'bold' }
        },
        labelLine: { show: false },
        data: factorData
      }
    ]
  }
  
  factorContributionChart.setOption(option)
  window.addEventListener('resize', () => factorContributionChart?.resize())
}

// 页面销毁时释放图表实例
onUnmounted(() => {
  equityChart?.dispose()
  positionChart?.dispose()
  dailyProfitChart?.dispose()
  strategyRadarChart?.dispose()
  profitDistributionChart?.dispose()
  factorContributionChart?.dispose()
})
</script>

<template>
  <div class="ultra-short-backtest-page">
    <div class="page-container">
      <div class="page-header">
        <h1 class="page-title">超短策略回测</h1>
        <p class="page-description">专门针对5大超短策略的全市场回测工具，支持实时过程日志和完整结果分析</p>
      </div>
      
      <div class="grid grid-cols-12 gap-6">
        <!-- 左侧配置面板 -->
        <div class="col-span-4">
          <ElCard class="config-card">
            <template #header>
              <div class="flex-between">
                <span>回测配置</span>
                <ElButton 
                  type="primary" 
                  :icon="Play" 
                  :disabled="!canRun"
                  @click="runBacktest"
                  size="small"
                >
                  运行回测
                </ElButton>
              </div>
            </template>
            
            <ElForm
              :model="form"
              :rules="rules"
              label-width="120px"
              size="small"
            >
              <ElFormItem label="选择策略" prop="strategies">
                <ElCheckboxGroup v-model="form.strategies">
                  <ElCheckbox 
                    v-for="item in strategyOptions" 
                    :key="item.value" 
                    :label="item.value"
                  >
                    {{ item.label }}
                  </ElCheckbox>
                </ElCheckboxGroup>
              </ElFormItem>
              
              <ElFormItem label="开始日期" prop="start_date">
                <ElInput v-model="form.start_date" placeholder="如：20260105" />
              </ElFormItem>
              
              <ElFormItem label="结束日期" prop="end_date">
                <ElInput v-model="form.end_date" placeholder="如：20260320" />
              </ElFormItem>
              
              <ElFormItem label="初始资金" prop="initial_cash">
                <ElInputNumber 
                  v-model="form.initial_cash" 
                  :min="10000" 
                  :max="100000000"
                  style="width: 100%"
                />
              </ElFormItem>
              
              <ElCollapse v-model="activeCollapse" accordion>
                <ElCollapseItem title="策略参数" name="params">
                  <ElFormItem label="流动性门槛(万元)">
                    <ElInputNumber 
                      v-model="form.params.liquidity_threshold" 
                      :min="100" 
                      :max="10000"
                      style="width: 100%"
                    />
                  </ElFormItem>
                  <ElFormItem label="量能放大倍数">
                    <ElInputNumber 
                      v-model="form.params.volume_threshold" 
                      :min="1" 
                      :max="10"
                      :step="0.1"
                      style="width: 100%"
                    />
                  </ElFormItem>
                  <ElFormItem label="止损比例">
                    <ElInputNumber 
                      v-model="form.params.stop_loss_pct" 
                      :min="0.01" 
                      :max="0.2"
                      :step="0.01"
                      style="width: 100%"
                    />
                  </ElFormItem>
                  <ElFormItem label="止盈比例">
                    <ElInputNumber 
                      v-model="form.params.take_profit_pct" 
                      :min="0.01" 
                      :max="0.5"
                      :step="0.01"
                      style="width: 100%"
                    />
                  </ElFormItem>
                  <ElFormItem label="最大持仓天数">
                    <ElInputNumber 
                      v-model="form.params.max_hold_days" 
                      :min="1" 
                      :max="10"
                      style="width: 100%"
                    />
                  </ElFormItem>
                </ElCollapseItem>
                
                <ElCollapseItem title="仓位配置" name="position">
                  <ElFormItem label="单票最大仓位">
                    <ElInputNumber 
                      v-model="form.params.max_position_per_stock" 
                      :min="0.1" 
                      :max="1"
                      :step="0.1"
                      style="width: 100%"
                    />
                  </ElFormItem>
                  <ElFormItem label="总仓位上限">
                    <ElInputNumber 
                      v-model="form.params.max_position" 
                      :min="0.1" 
                      :max="1"
                      :step="0.1"
                      style="width: 100%"
                    />
                  </ElFormItem>
                </ElCollapseItem>
                
                <ElCollapseItem title="高级设置" name="advanced">
                  <ElFormItem label="强制空仓">
                    <ElSwitch v-model="form.enable_force_empty" />
                  </ElFormItem>
                  <ElFormItem label="情绪周期">
                    <ElSwitch v-model="form.enable_sentiment_cycle" />
                  </ElFormItem>
                  <ElFormItem label="竞价过滤">
                    <ElSwitch v-model="form.enable_auction_filter" />
                  </ElFormItem>
                </ElCollapseItem>
              </ElCollapse>
              
              <div class="mt-4 flex gap-2">
                <ElButton 
                  type="danger" 
                  :icon="Stop" 
                  :disabled="!backtestState.running"
                  @click="stopBacktest"
                  size="small"
                  block
                >
                  停止回测
                </ElButton>
                <ElButton 
                  :icon="Download" 
                  :disabled="backtestState.status !== 'completed'"
                  @click="exportReport"
                  size="small"
                  block
                >
                  导出报告
                </ElButton>
              </div>
            </ElForm>
          </ElCard>
          
          <!-- 回测进度 -->
          <ElCard class="mt-4" v-if="backtestState.status !== 'idle'">
            <template #header>回测进度</template>
            
            <div class="mb-2 flex-between">
              <span>状态：{{ 
                backtestState.status === 'running' ? '运行中' :
                backtestState.status === 'completed' ? '已完成' :
                backtestState.status === 'failed' ? '失败' : '已取消'
              }}</span>
              <span>{{ backtestState.progress }}%</span>
            </div>
            <ElProgress 
              :percentage="backtestState.progress" 
              :status="
                backtestState.status === 'failed' ? 'exception' :
                backtestState.status === 'completed' ? 'success' : undefined
              "
            />
            
            <!-- 状态提示 -->
            <ElAlert 
              v-if="backtestState.status === 'failed'"
              title="回测失败"
              type="error"
              :closable="false"
              class="mt-4"
            />
            <ElAlert 
              v-if="backtestState.status === 'completed'"
              title="回测完成"
              type="success"
              :closable="false"
              class="mt-4"
            />
          </ElCard>
        </div>
        
        <!-- 右侧内容区 -->
        <div class="col-span-8">
          <!-- 日志面板 -->
          <ElCard class="log-card">
            <template #header>
              <div class="flex-between">
                <span>实时日志</span>
                <ElButton 
                  :icon="Document" 
                  size="small"
                  @click="backtestState.logs = []"
                >
                  清空
                </ElButton>
              </div>
            </template>
            
            <div class="log-panel h-80 overflow-y-auto bg-gray-50 dark:bg-gray-900 p-3 rounded text-sm font-mono">
              <div v-if="backtestState.logs.length === 0" class="h-full flex-center">
                <ElEmpty description="暂无日志" :image-size="80" />
              </div>
              <div v-for="(log, index) in backtestState.logs" :key="index" class="log-item mb-1">
                {{ log }}
              </div>
            </div>
          </ElCard>
          
          <!-- 结果展示 -->
          <div class="mt-6" v-if="backtestState.result">
            <ElTabs v-model="activeTab">
              <!-- 核心指标 -->
              <ElTabPane label="核心指标" name="metrics">
                <div class="grid grid-cols-3 gap-4">
                  <ElCard class="metric-card">
                    <div class="text-sm text-gray-500 mb-1">累计收益率</div>
                    <div class="text-2xl font-bold text-red-500">
                      {{ (backtestState.result.total_return * 100).toFixed(2) }}%
                    </div>
                  </ElCard>
                  <ElCard class="metric-card">
                    <div class="text-sm text-gray-500 mb-1">胜率</div>
                    <div class="text-2xl font-bold text-blue-500">
                      {{ (backtestState.result.win_rate * 100).toFixed(2) }}%
                    </div>
                  </ElCard>
                  <ElCard class="metric-card">
                    <div class="text-sm text-gray-500 mb-1">盈亏比</div>
                    <div class="text-2xl font-bold text-green-500">
                      {{ backtestState.result.profit_loss_ratio.toFixed(2) }}
                    </div>
                  </ElCard>
                  <ElCard class="metric-card">
                    <div class="text-sm text-gray-500 mb-1">最大回撤</div>
                    <div class="text-2xl font-bold text-orange-500">
                      {{ (backtestState.result.max_drawdown * 100).toFixed(2) }}%
                    </div>
                  </ElCard>
                  <ElCard class="metric-card">
                    <div class="text-sm text-gray-500 mb-1">夏普比率</div>
                    <div class="text-2xl font-bold text-purple-500">
                      {{ backtestState.result.sharpe_ratio.toFixed(2) }}
                    </div>
                  </ElCard>
                  <ElCard class="metric-card">
                    <div class="text-sm text-gray-500 mb-1">总交易次数</div>
                    <div class="text-2xl font-bold text-gray-700 dark:text-gray-200">
                      {{ backtestState.result.total_trades }}
                    </div>
                  </ElCard>
                </div>
              </ElTabPane>
              
              <!-- 可视化图表 -->
              <ElTabPane label="可视化图表" name="charts">
                <div class="space-y-6">
                  <ElCard>
                    <div id="equity-chart" style="width: 100%; height: 400px;"></div>
                  </ElCard>
                  <ElCard>
                    <div id="position-chart" style="width: 100%; height: 300px;"></div>
                  </ElCard>
                  <ElCard>
                    <div id="daily-profit-chart" style="width: 100%; height: 300px;"></div>
                  </ElCard>
                </div>
              </ElTabPane>
              
              <!-- 交易记录 -->
              <ElTabPane label="交易记录" name="trades">
                <ElTable 
                  :data="backtestState.result.trades || []" 
                  border
                  size="small"
                  max-height="400"
                >
                  <ElTableColumn 
                    v-for="col in tradeColumns" 
                    :key="col.prop" 
                    v-bind="col"
                  />
                </ElTable>
              </ElTabPane>
              
              <!-- 策略对比 -->
              <ElTabPane label="策略对比" name="strategy" v-if="form.strategies.length > 1">
                <div class="grid grid-cols-2 gap-4" v-for="(item, index) in strategyResults" :key="index">
                  <ElCard>
                    <template #header>{{ item.strategy_name }}</template>
                    <div class="grid grid-cols-2 gap-2 text-sm">
                      <div>
                        <div class="text-gray-500">收益率</div>
                        <div class="text-lg font-bold text-red-500">{{ (item.total_return * 100).toFixed(2) }}%</div>
                      </div>
                      <div>
                        <div class="text-gray-500">胜率</div>
                        <div class="text-lg font-bold text-blue-500">{{ (item.win_rate * 100).toFixed(2) }}%</div>
                      </div>
                      <div>
                        <div class="text-gray-500">盈亏比</div>
                        <div class="text-lg font-bold text-green-500">{{ item.profit_loss_ratio.toFixed(2) }}</div>
                      </div>
                      <div>
                        <div class="text-gray-500">信号数</div>
                        <div class="text-lg font-bold">{{ item.signal_count }}</div>
                      </div>
                    </div>
                  </ElCard>
                </div>
              </ElTabPane>
              
              <!-- 高级分析 -->
              <ElTabPane label="高级分析" name="advanced">
                <div class="space-y-6">
                  <!-- 策略对比雷达图 -->
                  <ElCard title="📈 多策略绩效对比雷达图" v-if="form.strategies.length > 1">
                    <div id="strategy-radar-chart" style="width: 100%; height: 450px;"></div>
                  </ElCard>
                  
                  <!-- 收益分布直方图 -->
                  <ElCard title="📊 交易收益分布">
                    <div id="profit-distribution-chart" style="width: 100%; height: 350px;"></div>
                  </ElCard>
                  
                  <!-- 因子贡献分析 -->
                  <ElCard title="🧮 因子贡献分析">
                    <div id="factor-contribution-chart" style="width: 100%; height: 350px;"></div>
                  </ElCard>
                </div>
              </ElTabPane>
            </ElTabs>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.ultra-short-backtest-page {
  .config-card {
    :deep(.el-card__body) {
      padding: 20px;
    }
  }
  
  .log-panel {
    .log-item {
      &.error {
        color: var(--stock-down);
      }
      
      &.success {
        color: var(--stock-up);
      }
      
      &.info {
        color: var(--primary-500);
      }
    }
  }
  
  .metric-card {
    :deep(.el-card__body) {
      padding: 16px;
    }
  }
}
</style>
