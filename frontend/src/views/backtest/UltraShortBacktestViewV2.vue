<script setup lang="ts">
/**
 * 超短策略回测V2.0 - 私募级实盘版
 * 【全新版本特性】：
 * ✅ 无Tushare依赖，全程使用AKShare+MongoDB
 * ✅ 专业级可审计日志系统
 * ✅ 实盘级风控规则默认开启
 * ✅ 所有bug修复集成
 * ✅ 无未来函数/信号漂移
 * ✅ 界面全新设计，专业金融系统风格
 */
import { ref, reactive, onMounted, computed, watch, nextTick, onUnmounted } from 'vue'
import { Search, Play, Stop, Download, Document } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
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

// 注册ECharts
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

// 导入组件
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
  ElSwitch,
  ElSelect,
  ElOption,
  ElStatistic
} from 'element-plus'

// API
import { backtestApi } from '@/api'
import { useWebSocket } from '@vueuse/core'

// ==================== 状态 ====================

// 表单数据
const form = reactive({
  // 数据源配置
  dataSource: {
    data_source: 'mongodb',
    period: 'daily',
    ts_codes: '',
    start_date: '20260105',
    end_date: '20260320',
    adjust_type: 'qfq',
  },
  // 基础配置
  base: {
    initial_cash: 1000000,
  },
  // 全局筛选参数
  globalFilter: {
    exclude_st: true,
    exclude_delisting: true,
    exclude_new_stock_days: 60,
    min_daily_amount: 500,
    min_turnover_rate: 3,
  },
  // 强制空仓配置（默认开启）
  forceEmpty: {
    enabled: true,
    index_drop_pct: 0.03,
    limit_down_count: 50,
    limit_up_count: 10,
    max_consecutive_limit: 3,
  },
  // 情绪周期配置（默认开启）
  sentimentCycle: {
    enabled: true,
    weight_limit_up: 0.25,
    weight_limit_down: 0.1,
    weight_blast_rate: 0.07,
    weight_rise_fall_diff: 0.15,
    weight_north_inflow: 0.12,
  },
  // 竞价过滤配置（默认开启）
  auctionFilter: {
    enabled: true,
    min_auction_pct: 0.005,
    max_auction_pct: 0.07,
    min_unmatched_volume_positive: true,
    min_auction_amount: 300,
    min_auction_volume_ratio: 1.5,
  },
  // 通用交易参数
  tradeParams: {
    base_stop_loss_pct: 0.02, // 2%止损
    base_take_profit_pct: 0.07, // 7%止盈
    max_hold_days: 3,
    max_position_per_stock: 0.3, // 单票30%
    max_total_position: 0.6, // 总仓60%
    commission_rate: 0.0003, // 0.03%佣金
    stamp_duty_rate: 0.001, // 0.1%印花税
    slippage_pct: 0.002, // 0.2%滑点
  },
  // 策略选择
  strategies: ['halfway_chase'],
  strategyConfigs: {
    halfway_chase: {
      enabled: true,
      name: '半路追涨',
      params: {
        min_rise_pct: 0.03,
        max_rise_pct: 0.07,
        min_volume_ratio: 1.5,
        allow_after_10am: false,
      }
    },
    first_limit_up: {
      enabled: true,
      name: '首板打板',
      params: {
        min_seal_amount: 5000,
        max_limit_up_time: '10:00',
        max_circulation_market_cap: 100,
        max_blast_count: 1,
        require_hot_sector: true,
      }
    },
    limit_up_open: {
      enabled: true,
      name: '涨停开板',
      params: {
        min_consecutive_limit: 2,
        max_open_duration: 5,
        min_seal_after_open: 3000,
        min_turnover_rate: 0.15,
      }
    },
    leader_buy_dip: {
      enabled: true,
      name: '龙头低吸',
      params: {
        min_consecutive_limit: 3,
        min_correction_pct: 0.15,
        max_correction_pct: 0.3,
        correction_days_min: 2,
        correction_days_max: 5,
        support_level: 'ma5',
      }
    },
    limit_down_qiao: {
      enabled: false,
      name: '跌停翘板',
      params: {
        min_consecutive_limit: 3,
        min_qiao_amount: 10000,
        min_rise_after_qiao: 0.03,
        require_high_sentiment: true,
      }
    }
  },
})

// 折叠面板默认全部展开
const activeCollapse = ref(['dataSource', 'strategy', 'riskControl', 'advanced'])

// 回测状态
const backtestState = reactive({
  running: false,
  task_id: '',
  progress: 0,
  status: 'idle', // idle / running / completed / failed
  error: '',
  logs: [] as string[],
  result: null as any,
})

// 标签页激活项
const activeTab = ref('metrics')

// WebSocket连接
const { status: wsStatus, send: wsSend, data: wsData } = useWebSocket(
  () => {
    const token = localStorage.getItem('access_token')
    return `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws?token=${token || ''}`
  },
  {
    autoReconnect: true,
    heartbeat: {
      message: JSON.stringify({ type: 'ping' }),
      interval: 30000,
    },
  }
)

// 预设模板
const presetTemplates = [
  {
    name: '🔴 高收益型',
    desc: '胜率45%+，收益优先',
    config: {
      globalFilter: { min_daily_amount: 500, min_turnover_rate: 3 },
      tradeParams: { max_total_position: 0.9, base_stop_loss_pct: 0.07, base_take_profit_pct: 0.15 },
      strategies: ['halfway_chase', 'first_limit_up', 'limit_up_open'],
    }
  },
  {
    name: '🟡 平衡型',
    desc: '收益回撤平衡',
    config: {
      globalFilter: { min_daily_amount: 1000, min_turnover_rate: 3 },
      tradeParams: { max_total_position: 0.7, base_stop_loss_pct: 0.05, base_take_profit_pct: 0.1 },
      strategies: ['halfway_chase', 'first_limit_up'],
    }
  },
  {
    name: '🟢 低风险型',
    desc: '最大回撤≤20%',
    config: {
      globalFilter: { min_daily_amount: 2000, min_turnover_rate: 5 },
      tradeParams: { max_total_position: 0.5, base_stop_loss_pct: 0.03, base_take_profit_pct: 0.08 },
      strategies: ['halfway_chase'],
    }
  }
]

// 当前选中的预设模板
const selectedPreset = ref<number | null>(null)

// 应用预设模板
function applyTemplate(tpl: any) {
  Object.assign(form.globalFilter, tpl.config.globalFilter)
  Object.assign(form.tradeParams, tpl.config.tradeParams)
  form.strategies = tpl.config.strategies
  ElMessage.success(`已应用【${tpl.name}】模板`)
}

// 回测流程步骤
const flowSteps = [
  { icon: '📊', name: '数据加载' },
  { icon: '🔍', name: '全局筛选' },
  { icon: '🧠', name: '情绪计算' },
  { icon: '📋', name: '盘前预选' },
  { icon: '⏰', name: '竞价过滤' },
  { icon: '⚡', name: '盘中信号' },
  { icon: '💹', name: '交易执行' },
  { icon: '📈', name: '绩效计算' },
]

// 图表实例
let navChart: echarts.ECharts | null = null
let drawdownChart: echarts.ECharts | null = null
let positionChart: echarts.ECharts | null = null
let dailyProfitChart: echarts.ECharts | null = null
let strategyRadarChart: echarts.ECharts | null = null
let profitDistributionChart: echarts.ECharts | null = null
let factorContributionChart: echarts.ECharts | null = null
let strategyEquityChart: echarts.ECharts | null = null

// 轮询定时器
let pollingTimer: number | null = null

// ==================== 交易记录筛选相关 ====================
const tradeFilter = reactive({
  strategy: '',
  profitType: 'all',
  searchKeyword: '',
  page: 1,
  pageSize: 50,
})

// 表格列
const tradeColumns = [
  { prop: 'date', label: '交易日期', width: 100 },
  { prop: 'ts_code', label: '股票代码', width: 100 },
  { prop: 'stock_name', label: '股票名称', width: 100 },
  { prop: 'strategy', label: '策略', width: 100 },
  { prop: 'buy_price', label: '买入价', width: 80, formatter: (row: any) => row.buy_price?.toFixed(2) },
  { prop: 'sell_price', label: '卖出价', width: 80, formatter: (row: any) => row.sell_price?.toFixed(2) },
  { prop: 'profit_pct', label: '收益率', width: 90, formatter: (row: any) => row.profit_pct ? `${(row.profit_pct * 100).toFixed(2)}%` : '' },
  { prop: 'hold_days', label: '持仓天数', width: 80 },
  { prop: 'auction_pct', label: '竞价涨幅', width: 90, formatter: (row: any) => row.auction_pct ? `${(row.auction_pct * 100).toFixed(2)}%` : '-' },
  { prop: 'volume_ratio', label: '量能比', width: 80, formatter: (row: any) => row.volume_ratio ? row.volume_ratio.toFixed(2) : '-' },
  { prop: 'signal_reason', label: '信号原因', minWidth: 180 },
  { prop: 'exit_reason', label: '离场原因', width: 120 },
]

// 筛选后的交易记录
const filteredTrades = computed(() => {
  let trades = [...(backtestState.result?.trades || [])]
  
  // 按策略筛选
  if (tradeFilter.strategy) {
    trades = trades.filter(t => t.strategy === tradeFilter.strategy)
  }
  
  // 按盈亏筛选
  if (tradeFilter.profitType === 'profit') {
    trades = trades.filter(t => t.profit_pct > 0)
  } else if (tradeFilter.profitType === 'loss') {
    trades = trades.filter(t => t.profit_pct <= 0)
  }
  
  // 按关键字搜索
  if (tradeFilter.searchKeyword.trim()) {
    const keyword = tradeFilter.searchKeyword.trim().toLowerCase()
    trades = trades.filter(t => 
      t.ts_code.toLowerCase().includes(keyword) || 
      t.stock_name.toLowerCase().includes(keyword)
    )
  }
  
  return trades
})

// 分页后的交易记录
const paginatedTrades = computed(() => {
  const start = (tradeFilter.page - 1) * tradeFilter.pageSize
  const end = start + tradeFilter.pageSize
  return filteredTrades.value.slice(start, end)
})

// ==================== 交易分析计算属性 ====================
const trades = computed(() => backtestState.result?.trades || [])
const strategyResults = computed(() => Object.values(backtestState.result?.strategy_results || {}) as any[])

// 盈利笔数
const profitCount = computed(() => trades.value.filter((t: any) => t.profit_pct > 0).length)
// 亏损笔数
const lossCount = computed(() => trades.value.filter((t: any) => t.profit_pct <= 0).length)
// 胜率
const winRate = computed(() => trades.value.length > 0 ? ((profitCount.value / trades.value.length) * 100).toFixed(2) as any : 0)
// 平均持仓天数
const avgHoldDays = computed(() => {
  if (trades.value.length === 0) return 0
  const total = trades.value.reduce((sum: number, t: any) => sum + t.hold_days, 0)
  return (total / trades.value.length).toFixed(1) as any
})
// 盈亏比
const profitLossRatio = computed(() => {
  if (lossCount.value === 0) return 999
  const avgProfit = trades.value.filter((t: any) => t.profit_pct > 0).reduce((sum: number, t: any) => sum + t.profit_pct, 0) / Math.max(profitCount.value, 1)
  const avgLoss = Math.abs(trades.value.filter((t: any) => t.profit_pct <= 0).reduce((sum: number, t: any) => sum + t.profit_pct, 0) / Math.max(lossCount.value, 1))
  return avgLoss === 0 ? 0 : avgProfit / avgLoss
})

// 最大盈利Top5
const topProfitTrades = computed(() => {
  return [...trades.value].sort((a: any, b: any) => b.profit_pct - a.profit_pct).slice(0, 5)
})
// 最大亏损Top5
const topLossTrades = computed(() => {
  return [...trades.value].sort((a: any, b: any) => a.profit_pct - b.profit_pct).slice(0, 5)
})
// 平均盈利
const avgProfitPerTrade = computed(() => {
  if (profitCount.value === 0) return 0
  const totalProfit = trades.value.filter((t: any) => t.profit_pct > 0).reduce((sum: number, t: any) => sum + t.profit_pct, 0)
  return ((totalProfit / profitCount.value) * 100).toFixed(2)
})
// 平均亏损
const avgLossPerTrade = computed(() => {
  if (lossCount.value === 0) return 0
  const totalLoss = Math.abs(trades.value.filter((t: any) => t.profit_pct <= 0).reduce((sum: number, t: any) => sum + t.profit_pct, 0))
  return ((totalLoss / lossCount.value) * 100).toFixed(2)
})
// 最大单笔盈利
const maxProfitTrade = computed(() => {
  if (trades.value.length === 0) return 0
  return (Math.max(...trades.value.map((t: any) => t.profit_pct)) * 100).toFixed(2)
})
// 最大单笔亏损
const maxLossTrade = computed(() => {
  if (trades.value.length === 0) return 0
  return (Math.abs(Math.min(...trades.value.map((t: any) => t.profit_pct))) * 100).toFixed(2)
})

// ==================== 核心指标页辅助方法 ====================
/**
 * 获取回测结论文本
 */
function getBacktestConclusion() {
  if (!backtestState.result) return '请先运行回测查看结论'
  const totalReturn = (backtestState.result.total_return || 0) * 100
  const maxDrawdown = (backtestState.result.max_drawdown || 0) * 100
  const sharpe = backtestState.result.sharpe_ratio || 0
  
  if (totalReturn >= 30 && maxDrawdown <= 30 && sharpe >= 1.5) {
    return '✅ 策略表现优秀，建议实盘使用'
  } else if (totalReturn >= 10 && maxDrawdown <= 40 && sharpe >= 1) {
    return '⚠️ 策略表现一般，建议优化参数后使用'
  } else {
    return '❌ 策略表现较差，不建议实盘使用'
  }
}

/**
 * 获取回测结论提示类型
 */
function getBacktestConclusionType() {
  if (!backtestState.result) return 'info'
  const totalReturn = (backtestState.result.total_return || 0) * 100
  if (totalReturn >= 30) return 'success'
  if (totalReturn >= 10) return 'warning'
  return 'error'
}

/**
 * 计算年化收益率
 */
function calculateAnnualizedReturn() {
  if (!backtestState.result) return 0
  const startDate = new Date(backtestState.result.start_date.replace(/(\d{4})(\d{2})(\d{2})/, '$1-$2-$3'))
  const endDate = new Date(backtestState.result.end_date.replace(/(\d{4})(\d{2})(\d{2})/, '$1-$2-$3'))
  const days = (endDate.getTime() - startDate.getTime()) / (1000 * 60 * 60 * 24)
  if (days <= 0) return 0
  const totalReturn = backtestState.result.total_return || 0
  const annualized = (Math.pow(1 + totalReturn, 365 / days) - 1) * 100
  return annualized
}

// ==================== 计算属性 ====================
const selectedStrategyNames = computed(() => {
  return form.strategies.map(id => form.strategyConfigs[id as keyof typeof form.strategyConfigs]?.name || id)
})

const canRun = computed(() => {
  return !backtestState.running && form.dataSource.start_date && form.dataSource.end_date && form.strategies.length > 0
})

// ==================== 生命周期 ====================
onMounted(() => {
  // 从localStorage加载保存的参数
  const savedConfig = localStorage.getItem('ultra-short-v2-config')
  if (savedConfig) {
    try {
      const parsed = JSON.parse(savedConfig)
      Object.assign(form, parsed)
    } catch (e) {
      console.warn('Failed to load saved config:', e)
    }
  }

  // 初始化净值图表
  const chartDom = document.getElementById('nav-chart')
  if (chartDom) {
    navChart = echarts.init(chartDom)
    updateNavChart([])
  }

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

// 页面销毁时释放图表实例
onUnmounted(() => {
  navChart?.dispose()
  drawdownChart?.dispose()
  positionChart?.dispose()
  dailyProfitChart?.dispose()
  strategyRadarChart?.dispose()
  profitDistributionChart?.dispose()
  factorContributionChart?.dispose()
  strategyEquityChart?.dispose()
})

// ==================== 方法 ====================

// 保存配置到localStorage
const saveConfig = () => {
  localStorage.setItem('ultra-short-v2-config', JSON.stringify(form))
  ElMessage.success('配置已保存')
}

// 清空配置
const clearConfig = () => {
  localStorage.removeItem('ultra-short-v2-config')
  ElMessage.success('配置已重置')
}

// 提交回测
const submitBacktest = async () => {
  if (backtestState.running) {
    ElMessage.warning('回测正在运行中，请先停止')
    return
  }

  // 校验参数
  if (!form.strategies.length) {
    ElMessage.error('请至少选择一个策略')
    return
  }
  if (!form.dataSource.start_date || !form.dataSource.end_date) {
    ElMessage.error('请选择回测日期范围')
    return
  }

  // 保存配置
  saveConfig()

  // 重置状态
  backtestState.running = true
  backtestState.status = 'running'
  backtestState.progress = 0
  backtestState.error = ''
  backtestState.logs = []
  backtestState.result = null

  // 清除旧的轮询定时器
  if (pollingTimer) {
    clearInterval(pollingTimer)
    pollingTimer = null
  }

  addLog('🚀 【V2.0】开始提交超短策略回测任务...')
  addLog(`📅 回测区间: ${form.dataSource.start_date} -> ${form.dataSource.end_date}`)
  addLog(`💰 初始资金: ${form.base.initial_cash.toLocaleString()} 元`)
  addLog(`🎯 选中策略: [${selectedStrategyNames.value.join(', ')}]`)
  addLog(`🔧 流动性门槛: ${form.globalFilter.min_daily_amount} 万元`)
  addLog(`📈 单票最大仓位: ${form.tradeParams.max_position_per_stock * 100}%`)
  addLog(`✅ 强制空仓规则: ${form.forceEmpty.enabled ? '已启用' : '已禁用'}`)
  addLog(`✅ 情绪周期算法: ${form.sentimentCycle.enabled ? '已启用' : '已禁用'}`)
  addLog(`✅ 竞价过滤规则: ${form.auctionFilter.enabled ? '已启用' : '已禁用'}`)

  try {
    // 提交回测
    const response = await backtestApi.submitUltraShort({
      strategies: form.strategies,
      start_date: form.dataSource.start_date,
      end_date: form.dataSource.end_date,
      initial_cash: form.base.initial_cash,
      params: {
        liquidity_threshold: form.globalFilter.min_daily_amount,
        volume_threshold: form.globalFilter.min_turnover_rate,
        stop_loss_pct: form.tradeParams.base_stop_loss_pct,
        take_profit_pct: form.tradeParams.base_take_profit_pct,
        max_hold_days: form.tradeParams.max_hold_days,
        max_position_per_stock: form.tradeParams.max_position_per_stock,
        max_position: form.tradeParams.max_total_position,
      },
      enable_force_empty: form.forceEmpty.enabled,
      enable_sentiment_cycle: form.sentimentCycle.enabled,
      enable_auction_filter: form.auctionFilter.enabled,
    })

    backtestState.task_id = response.task_id
    addLog(`✅ 任务提交成功，任务ID：${backtestState.task_id}`)
    addLog('🔄 已启动进度轮询保障')

    // 订阅任务进度
    if (wsStatus.value === 'OPEN') {
      wsSend(JSON.stringify({
        type: 'subscribe',
        task_id: backtestState.task_id,
      }))
      addLog('📡 已订阅任务实时进度')
    }

    // 启动轮询
    startPolling()

  } catch (e: any) {
    backtestState.running = false
    backtestState.status = 'failed'
    const errorMsg = e?.response?.data?.detail || e?.message || '未知错误'
    backtestState.error = errorMsg
    addLog(`❌ 回测提交失败: ${errorMsg}`)
    ElMessage.error(`回测提交失败: ${errorMsg}`)
  }
}

/**
 * 处理WebSocket消息
 */
function handleWsMessage(msg: any) {
  if (msg.type === 'task_update' && msg.task_id === backtestState.task_id) {
    // 任务进度更新
    if (msg.progress !== undefined) {
      backtestState.progress = msg.progress
      // 兜底逻辑：进度到100%后3秒如果还是运行中，主动查询状态
      if (msg.progress === 100 && backtestState.status === 'running') {
        setTimeout(async () => {
          if (backtestState.status === 'running' && backtestState.running && backtestState.task_id) {
            try {
              addLog('🔍 检查回测状态...')
              const status = await backtestApi.getBacktestStatus(backtestState.task_id)
              backtestState.status = status.status
              if (status.status === 'completed') {
                backtestState.running = false
                addLog('✅ 回测完成！正在加载结果...')
                // 获取回测结果
                loadBacktestResult()
              } else if (status.status === 'failed') {
                backtestState.running = false
                addLog(`❌ 回测失败：${status.error || '未知错误'}`)
              }
            } catch (e: any) {
              console.error('状态查询失败', e)
              addLog(`⚠️ 状态查询失败：${e.message || '未知错误'}`)
            }
          }
        }, 3000)
      }
    }
    // 日志消息
    if (msg.log) {
      addLog(msg.log)
    }
    // 状态更新
    if (msg.status) {
      backtestState.status = msg.status
      if (msg.status === 'completed') {
        backtestState.running = false
        backtestState.progress = 100
        // 收到完成消息，清除轮询定时器
        if (pollingTimer) {
          clearInterval(pollingTimer)
          pollingTimer = null
        }
        addLog('✅ 回测完成！正在加载结果...')
        // 获取回测结果
        loadBacktestResult()
      } else if (msg.status === 'failed') {
        backtestState.running = false
        // 收到失败消息，清除轮询定时器
        if (pollingTimer) {
          clearInterval(pollingTimer)
          pollingTimer = null
        }
        addLog(`❌ 回测失败：${msg.error || '未知错误'}`)
      }
    }
  }
}

/**
 * 轮询获取进度
 */
function startPolling() {
  // 先清除之前的定时器
  if (pollingTimer) {
    clearInterval(pollingTimer)
  }
  pollingTimer = window.setInterval(async () => {
    if (!backtestState.running) {
      if (pollingTimer) {
        clearInterval(pollingTimer)
        pollingTimer = null
      }
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
        if (pollingTimer) {
          clearInterval(pollingTimer)
          pollingTimer = null
        }
        backtestState.running = false
        backtestState.progress = 100
        backtestState.status = 'completed'
        addLog('✅ 回测完成！')
        loadBacktestResult()
      } else if (res.status === 'failed') {
        if (pollingTimer) {
          clearInterval(pollingTimer)
          pollingTimer = null
        }
        backtestState.running = false
        backtestState.status = 'failed'
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
    backtestState.result = res.result
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

// 添加日志
const addLog = (text: string) => {
  const timestamp = new Date().toLocaleTimeString('zh-CN')
  backtestState.logs.push(`[${timestamp}] ${text}`)
  // 自动滚动到底部
  nextTick(() => {
    const logPanel = document.getElementById('log-panel')
    if (logPanel) {
      logPanel.scrollTop = logPanel.scrollHeight
    }
  })
}

// 更新净值图表
const updateNavChart = (navData: any) => {
  if (!navChart || !navData?.dates?.length) {
    navChart?.setOption({
      title: { text: '净值曲线' },
      tooltip: { trigger: 'axis' },
      grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
      xAxis: { type: 'category', boundaryGap: false, data: [] },
      yAxis: { type: 'value', scale: true },
      series: [
        { name: '策略净值', type: 'line', data: [], smooth: true, lineStyle: { width: 2 } },
        { name: '基准收益', type: 'line', data: [], smooth: true, lineStyle: { width: 2, type: 'dashed' } }
      ]
    })
    return
  }

  navChart.setOption({
    xAxis: { data: navData.dates },
    series: [
      { name: '策略净值', data: navData.strategy },
      { name: '基准收益', data: navData.benchmark }
    ]
  })
}

/**
 * 渲染所有图表
 */
function renderCharts() {
  if (!backtestState.result) return
  
  // 渲染净值和回撤曲线
  renderEquityAndDrawdownChart()
  // 渲染仓位变化图
  renderPositionChart()
  // 渲染每日盈亏图
  renderDailyProfitChart()
  
  // 高级分析图表
  nextTick(() => {
    // 策略对比相关图表（多个策略时渲染）
    if (form.strategies.length > 1) {
      renderStrategyRadarChart()
      renderStrategyEquityChart()
    }
    // 交易分析图表
    renderTradeAnalysisCharts()
    // 收益分布直方图
    renderProfitDistributionChart()
    // 因子贡献分析图
    renderFactorContributionChart()
  })
}

/**
 * 渲染收益+回撤组合图
 */
function renderEquityAndDrawdownChart() {
  const dom = document.getElementById('nav-chart')
  if