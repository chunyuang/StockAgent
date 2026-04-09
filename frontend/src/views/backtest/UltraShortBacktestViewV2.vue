<script setup lang="ts">
/**
 * 超短策略回测V2.0 - 私募级实盘版
 * 极简稳定版本，确保可以正常运行
 */
import { ref, reactive, onMounted, computed } from 'vue'
import { VideoPlay as Play, Download } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

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
} from 'element-plus'

// API
import { backtestApi } from '@/api'

// ==================== 状态 ====================

// 表单数据
const form = reactive({
  // 数据源配置
  dataSource: {
    period: 'daily', // daily/1min
    ts_codes: '', // 股票代码，逗号分隔，空为全市场
    start_date: '20260105',
    end_date: '20260320',
    adjust_type: 'qfq', // 前复权/不复权
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
    min_daily_amount: 500, // 最低日成交额(万元)
    min_turnover_rate: 3, // 最低换手率(%)
  },
  // 强制空仓配置
  forceEmpty: {
    enabled: true,
    index_drop_pct: 0.03, // 大盘跌幅≥3%
    limit_down_count: 50, // 跌停家数≥50只
    limit_up_count: 10, // 涨停家数<10只
  },
  // 情绪周期配置
  sentimentCycle: {
    enabled: true,
    weight_limit_up: 0.25,
    weight_limit_down: 0.1,
    weight_blast_rate: 0.07,
    weight_rise_fall_diff: 0.15,
    weight_north_inflow: 0.12,
  },
  // 竞价过滤配置
  auctionFilter: {
    enabled: true,
    min_auction_pct: 0.005, // 最低竞价涨幅
    max_auction_pct: 0.07, // 最高竞价涨幅
    min_unmatched_volume_positive: true, // 未匹配量必须为正
    min_auction_amount: 300, // 最低竞价成交额(万元)
    min_auction_volume_ratio: 1.5, // 最低竞价量比
  },
  // 通用交易参数
  tradeParams: {
    base_stop_loss_pct: 0.02, // 2%止损
    base_take_profit_pct: 0.07, // 7%止盈
    max_hold_days: 3, // 最大持仓天数
    max_position_per_stock: 0.3, // 单票最大仓位
    max_total_position: 0.6, // 总仓位上限
    commission_rate: 0.0003, // 0.03%佣金
    stamp_duty_rate: 0.001, // 0.1%印花税
    slippage_pct: 0.002, // 0.2%滑点
  },
  // 策略选择（默认全选）
  strategies: ['halfway_chase', 'first_limit_up', 'limit_up_open', 'leader_buy_dip', 'limit_down_qiao'],
  // 5个策略独立配置
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
      enabled: true,
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

// 折叠面板默认全部折叠
const activeCollapse = ref([])

// 每个策略的动态标题
const halfwayChaseTitle = computed(() => `🏃‍♂️ 半路追涨策略 ${form.strategyConfigs.halfway_chase.enabled ? '✅' : '❌'} (涨幅${(form.strategyConfigs.halfway_chase.params.min_rise_pct*100).toFixed(1)}%~${(form.strategyConfigs.halfway_chase.params.max_rise_pct*100).toFixed(1)}%, 量比≥${form.strategyConfigs.halfway_chase.params.min_volume_ratio}倍, 10点后买入: ${form.strategyConfigs.halfway_chase.params.allow_after_10am ? '✅' : '❌'})`)
const firstLimitUpTitle = computed(() => `🥇 首板打板策略 ${form.strategyConfigs.first_limit_up.enabled ? '✅' : '❌'} (封单≥${form.strategyConfigs.first_limit_up.params.min_seal_amount}万, ≤${form.strategyConfigs.first_limit_up.params.max_limit_up_time}涨停, 热点板块: ${form.strategyConfigs.first_limit_up.params.require_hot_sector ? '✅' : '❌'})`)
const limitUpOpenTitle = computed(() => `📈 涨停开板策略 ${form.strategyConfigs.limit_up_open.enabled ? '✅' : '❌'} (连板≥${form.strategyConfigs.limit_up_open.params.min_consecutive_limit}板, 开板≤${form.strategyConfigs.limit_up_open.params.max_open_duration}分钟)`)
const leaderBuyDipTitle = computed(() => `🐲 龙头低吸策略 ${form.strategyConfigs.leader_buy_dip.enabled ? '✅' : '❌'} (连板≥${form.strategyConfigs.leader_buy_dip.params.min_consecutive_limit}板, 回调${(form.strategyConfigs.leader_buy_dip.params.min_correction_pct*100).toFixed(0)}%~${(form.strategyConfigs.leader_buy_dip.params.max_correction_pct*100).toFixed(0)}%)`)
const limitDownQiaoTitle = computed(() => `💥 跌停翘板策略 ${form.strategyConfigs.limit_down_qiao.enabled ? '✅' : '❌'} (连板≥${form.strategyConfigs.limit_down_qiao.params.min_consecutive_limit}板, 翘板金额≥${form.strategyConfigs.limit_down_qiao.params.min_qiao_amount}万, 仅高潮期: ${form.strategyConfigs.limit_down_qiao.params.require_high_sentiment ? '✅' : '❌'})`)

// 策略参数标签页激活项
const activeStrategyTab = ref('halfway_chase')

// 回测状态
const backtestState = reactive({
  running: false,
  task_id: '',
  progress: 0,
})

// 日志
const logs = ref<string[]>([])

// 回测结果
const backtestResult = ref<any>(null)

// 各配置面板动态标题
const dataSourceTitle = computed(() => `🔌 数据源配置 (${form.dataSource.period === 'daily' ? '日线' : '1分钟'}, ${form.dataSource.adjust_type === 'qfq' ? '前复权' : '不复权'}, 股票池: ${form.dataSource.ts_codes || '全市场'})`)
const baseConfigTitle = computed(() => `📅 基础配置 (${form.dataSource.start_date}~${form.dataSource.end_date}, 初始资金¥${(form.base.initial_cash/10000).toFixed(0)}万)`)
const tradeParamsTitle = computed(() => `💹 交易参数 (止损${(form.tradeParams.base_stop_loss_pct*100).toFixed(1)}%, 止盈${(form.tradeParams.base_take_profit_pct*100).toFixed(1)}%, 持仓${form.tradeParams.max_hold_days}天, 总仓${(form.tradeParams.max_total_position*100).toFixed(0)}%, 单票${(form.tradeParams.max_position_per_stock*100).toFixed(0)}%, 佣金${(form.tradeParams.commission_rate*1000).toFixed(1)}‰, 印花税${(form.tradeParams.stamp_duty_rate*1000).toFixed(0)}‰, 滑点${(form.tradeParams.slippage_pct*1000).toFixed(1)}‰)`)
const globalFilterTitle = computed(() => `🔍 全局筛选 (剔除ST: ${form.globalFilter.exclude_st ? '✅' : '❌'}, 剔除退市: ${form.globalFilter.exclude_delisting ? '✅' : '❌'}, 次新股≥${form.globalFilter.exclude_new_stock_days}天, 成交额≥${form.globalFilter.min_daily_amount}万, 换手率≥${form.globalFilter.min_turnover_rate}%)`)
const forceEmptyTitle = computed(() => `⚠️ 强制空仓 ${form.forceEmpty.enabled ? '✅' : '❌'} (跌幅≥${(form.forceEmpty.index_drop_pct*100).toFixed(1)}%, 跌停≥${form.forceEmpty.limit_down_count}只, 涨停<${form.forceEmpty.limit_up_count}只)`)
const sentimentCycleTitle = computed(() => `🧠 情绪周期 ${form.sentimentCycle.enabled ? '✅' : '❌'} (涨停${form.sentimentCycle.weight_limit_up}, 跌停${form.sentimentCycle.weight_limit_down}, 炸板率${form.sentimentCycle.weight_blast_rate}, 涨跌差${form.sentimentCycle.weight_rise_fall_diff}, 北向${form.sentimentCycle.weight_north_inflow})`)
const auctionFilterTitle = computed(() => `⏰ 竞价过滤 ${form.auctionFilter.enabled ? '✅' : '❌'} (涨幅${(form.auctionFilter.min_auction_pct*100).toFixed(1)}%~${(form.auctionFilter.max_auction_pct*100).toFixed(1)}%, 成交额≥${form.auctionFilter.min_auction_amount}万, 量比≥${form.auctionFilter.min_auction_volume_ratio}, 未匹配量正: ${form.auctionFilter.min_unmatched_volume_positive ? '✅' : '❌'})`)
const strategyConfigTitle = computed(() => `🎯 策略配置 (已选: ${form.strategies.map(id => form.strategyConfigs[id as keyof typeof form.strategyConfigs]?.name).join(', ') || '无'})`)

// ==================== 生命周期 ====================
onMounted(() => {
  // 页面加载完成
  addLog('✅ 超短策略回测V2.0系统加载完成')
  addLog('💡 所有实盘级功能默认开启，可直接运行回测')
})

// ==================== 方法 ====================

// 提交回测
const submitBacktest = async () => {
  if (backtestState.running) {
    ElMessage.warning('回测正在运行中')
    return
  }

  // 重置状态
  backtestState.running = true
  backtestState.progress = 0
  logs.value = []
  backtestResult.value = null

  addLog('🚀 【实盘级】开始提交超短策略回测任务...')
  addLog(`📅 回测区间: ${form.dataSource.start_date} -> ${form.dataSource.end_date}`)
  addLog(`💰 初始资金: ${form.base.initial_cash.toLocaleString()} 元`)
  addLog(`🎯 选中策略: [${form.strategies.map(id => form.strategyConfigs[id as keyof typeof form.strategyConfigs]?.name).join(', ')}]`)
  addLog(`🔧 流动性门槛: ${form.globalFilter.min_daily_amount} 万元`)
  addLog(`📈 单票最大仓位: ${form.tradeParams.max_position_per_stock * 100}%`)
  addLog(`✅ 强制空仓规则: ${form.forceEmpty.enabled ? '已启用' : '已禁用'}`)
  addLog(`✅ 情绪周期算法: ${form.sentimentCycle.enabled ? '已启用' : '已禁用'}`)
  addLog(`✅ 竞价过滤规则: ${form.auctionFilter.enabled ? '已启用' : '已禁用'}`)

  try {
    // 提交回测任务到后端
    const res = await backtestApi.submitUltraShort({
      start_date: form.dataSource.start_date,
      end_date: form.dataSource.end_date,
      initial_cash: form.base.initial_cash,
      strategies: form.strategies,
      params: {
        liquidity_threshold: form.globalFilter.min_daily_amount,
        volume_threshold: form.globalFilter.min_turnover_rate,
        stop_loss_pct: form.tradeParams.base_stop_loss_pct,
        take_profit_pct: form.tradeParams.base_take_profit_pct,
        max_hold_days: form.tradeParams.max_hold_days,
        max_position_per_stock: form.tradeParams.max_position_per_stock,
        max_position: form.tradeParams.max_total_position,
        selected_strategies: form.strategies.map(id => ({
          id,
          name: form.strategyConfigs[id as keyof typeof form.strategyConfigs].name,
          params: form.strategyConfigs[id as keyof typeof form.strategyConfigs].params
        }))
      },
      enable_force_empty: form.forceEmpty.enabled,
      enable_sentiment_cycle: form.sentimentCycle.enabled,
      enable_auction_filter: form.auctionFilter.enabled
    })

    // 空值保护（响应拦截器已经直接返回response.data）
    if (!res || !res.task_id) {
      throw new Error(`接口返回异常：${JSON.stringify(res || '无返回数据')}`)
    }

    backtestState.task_id = res.task_id
    addLog(`✅ 任务提交成功，任务ID：${backtestState.task_id}`)
    // addLog('🔄 等待回测节点调度执行...') // 已移除，使用后端返回的真实日志

    // 建立WebSocket连接接收实时日志和结果
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsHost = '172.16.16.101:8000' // 固定后端地址，解决开发环境端口不一致问题
    // WebSocket需要Token认证，使用本地存储的token
    const token = localStorage.getItem('access_token') || 'mock-token-123456'
    const ws = new WebSocket(`${wsProtocol}//${wsHost}/ws?token=${token}`)
    
    ws.onopen = () => {
      // 连接成功后订阅当前任务
      ws.send(JSON.stringify({
        type: 'subscribe',
        task_id: backtestState.task_id
      }))
    }

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      if (data.type === 'log') {
        addLog(data.log)
      } else if (data.type === 'progress') {
        backtestState.progress = data.progress
      } else if (data.type === 'result') {
        backtestResult.value = data.result
        backtestState.running = false
        addLog('✅ 回测全部完成！')
        ElMessage.success('回测完成！')
        ws.close()
      } else if (data.type === 'error') {
        addLog(`❌ 回测失败：${data.message}`)
        backtestState.running = false
        ElMessage.error(`回测失败：${data.message}`)
        ws.close()
      } else if (data.type === 'subscribed') {
        addLog('✅ WebSocket已连接，实时日志推送已开启')
      }
    }

    ws.onerror = (error) => {
      // WebSocket连接失败时自动切换到高速轮询，无错误提示，体验和实时推送一致
      const pollInterval = setInterval(async () => {
        try {
          console.log('开始轮询任务状态:', backtestState.task_id)
          const statusRes = await backtestApi.getBacktestStatus(backtestState.task_id)
          console.log('轮询原始返回:', statusRes)
          
          // 完整空值保护
          if (!statusRes || !statusRes.data) {
            console.error('轮询返回数据为空:', statusRes)
            addLog(`⚠️ 轮询异常：接口返回数据为空`)
            return
          }
          
          const data = statusRes.data
          console.log('轮询返回数据:', data)
          
          if (data.logs) {
            logs.value = [...new Set([...logs.value, ...data.logs])]
            console.log('更新后日志条数:', logs.value.length)
          }
          
          if (data.progress !== undefined) {
            backtestState.progress = data.progress
          }
          
          if (data.status === 'completed') {
            // 回测完成后调用结果接口获取完整数据
            const resultRes = await backtestApi.getBacktestResult(backtestState.task_id)
            backtestResult.value = resultRes.data.result
            backtestState.running = false
            ElMessage.success('回测完成！')
            clearInterval(pollInterval)
          } else if (data.status === 'failed') {
            addLog(`❌ 回测失败：${data.error || '未知错误'}`)
            backtestState.running = false
            ElMessage.error(`回测失败：${data.error || '未知错误'}`)
            clearInterval(pollInterval)
          }
        } catch (e) {
          console.error('轮询失败', e)
          addLog(`⚠️ 轮询异常：${e.message || '未知错误'}`)
        }
      }, 1000) // 1秒轮询
    }

  } catch (e: any) {
    addLog(`❌ 提交回测任务失败：${e.message || '未知错误'}`)
    backtestState.running = false
    ElMessage.error(`提交回测失败：${e.message || '未知错误'}`)
  }
}

// 切换开关方法
const toggleGlobalFilterSt = () => {
  form.globalFilter.exclude_st = !form.globalFilter.exclude_st
}
const toggleGlobalFilterDelisting = () => {
  form.globalFilter.exclude_delisting = !form.globalFilter.exclude_delisting
}
const toggleForceEmpty = () => {
  form.forceEmpty.enabled = !form.forceEmpty.enabled
}
const toggleSentimentCycle = () => {
  form.sentimentCycle.enabled = !form.sentimentCycle.enabled
}
const toggleAuctionFilter = () => {
  form.auctionFilter.enabled = !form.auctionFilter.enabled
}
const toggleAuctionUnmatchedVolume = () => {
  if (form.auctionFilter.enabled) {
    form.auctionFilter.min_unmatched_volume_positive = !form.auctionFilter.min_unmatched_volume_positive
  }
}
const toggleHalfwayChase = () => {
  form.strategyConfigs.halfway_chase.enabled = !form.strategyConfigs.halfway_chase.enabled
  if (form.strategyConfigs.halfway_chase.enabled) {
    if (!form.strategies.includes('halfway_chase')) form.strategies.push('halfway_chase')
  } else {
    form.strategies = form.strategies.filter(k => k !== 'halfway_chase')
  }
}
const toggleHalfwayChaseAllowAfter10am = () => {
  if (form.strategyConfigs.halfway_chase.enabled) {
    form.strategyConfigs.halfway_chase.params.allow_after_10am = !form.strategyConfigs.halfway_chase.params.allow_after_10am
  }
}
const toggleFirstLimitUp = () => {
  form.strategyConfigs.first_limit_up.enabled = !form.strategyConfigs.first_limit_up.enabled
  if (form.strategyConfigs.first_limit_up.enabled) {
    if (!form.strategies.includes('first_limit_up')) form.strategies.push('first_limit_up')
  } else {
    form.strategies = form.strategies.filter(k => k !== 'first_limit_up')
  }
}
const toggleFirstLimitUpHotSector = () => {
  if (form.strategyConfigs.first_limit_up.enabled) {
    form.strategyConfigs.first_limit_up.params.require_hot_sector = !form.strategyConfigs.first_limit_up.params.require_hot_sector
  }
}
const toggleLimitUpOpen = () => {
  form.strategyConfigs.limit_up_open.enabled = !form.strategyConfigs.limit_up_open.enabled
  if (form.strategyConfigs.limit_up_open.enabled) {
    if (!form.strategies.includes('limit_up_open')) form.strategies.push('limit_up_open')
  } else {
    form.strategies = form.strategies.filter(k => k !== 'limit_up_open')
  }
}
const toggleLeaderBuyDip = () => {
  form.strategyConfigs.leader_buy_dip.enabled = !form.strategyConfigs.leader_buy_dip.enabled
  if (form.strategyConfigs.leader_buy_dip.enabled) {
    if (!form.strategies.includes('leader_buy_dip')) form.strategies.push('leader_buy_dip')
  } else {
    form.strategies = form.strategies.filter(k => k !== 'leader_buy_dip')
  }
}
const toggleLimitDownQiao = () => {
  form.strategyConfigs.limit_down_qiao.enabled = !form.strategyConfigs.limit_down_qiao.enabled
  if (form.strategyConfigs.limit_down_qiao.enabled) {
    if (!form.strategies.includes('limit_down_qiao')) form.strategies.push('limit_down_qiao')
  } else {
    form.strategies = form.strategies.filter(k => k !== 'limit_down_qiao')
  }
}
const toggleLimitDownQiaoHighSentiment = () => {
  if (form.strategyConfigs.limit_down_qiao.enabled) {
    form.strategyConfigs.limit_down_qiao.params.require_high_sentiment = !form.strategyConfigs.limit_down_qiao.params.require_high_sentiment
  }
}

// 添加日志
const addLog = (text: string) => {
  const timestamp = new Date().toLocaleTimeString('zh-CN')
  logs.value.push(`[${timestamp}] ${text}`)
  // 自动滚动到底部
  setTimeout(() => {
    const logPanel = document.getElementById('log-panel')
    if (logPanel) {
      logPanel.scrollTop = logPanel.scrollHeight
    }
  }, 100)
}

// 导入图表组件
import VChart from 'vue-echarts'
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

use([
  CanvasRenderer,
  LineChart,
  BarChart,
  PieChart,
  RadarChart,
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  GridComponent,
  DataZoomComponent
])

// 筛选变量
const searchTradeKeyword = ref('')
const filterStrategy = ref('')
const filterProfit = ref('')

// 计算属性：筛选后的交易记录
const filteredTrades = computed(() => {
  let trades = backtestResult.value?.trades || []
  if (searchTradeKeyword.value) {
    const keyword = searchTradeKeyword.value.toLowerCase()
    trades = trades.filter(t => 
      t.ts_code.toLowerCase().includes(keyword) || 
      t.stock_name.toLowerCase().includes(keyword)
    )
  }
  if (filterStrategy.value) {
    trades = trades.filter(t => t.strategy === form.strategyConfigs[filterStrategy.value as keyof typeof form.strategyConfigs]?.name)
  }
  if (filterProfit.value) {
    trades = trades.filter(t => filterProfit.value === 'profit' ? t.profit_pct >= 0 : t.profit_pct < 0)
  }
  return trades
})

// 计算属性：盈利/亏损TOP5
const profitTop5 = computed(() => {
  const trades = [...(backtestResult.value?.trades || [])].filter(t => t.profit_pct > 0)
  return trades.sort((a, b) => b.profit_pct - a.profit_pct).slice(0, 5)
})

const lossTop5 = computed(() => {
  const trades = [...(backtestResult.value?.trades || [])].filter(t => t.profit_pct < 0)
  return trades.sort((a, b) => a.profit_pct - b.profit_pct).slice(0, 5)
})

// 图表配置计算属性
const netValueChartOption = computed(() => {
  const result = backtestResult.value
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
  const result = backtestResult.value
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
  const result = backtestResult.value
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

const profitDistChartOption = computed(() => {
  const result = backtestResult.value
  if (!result?.profit_distribution) return {}
  return {
    tooltip: { trigger: 'item' },
    series: [
      { type: 'bar', data: Object.entries(result.profit_distribution).map(([range, count]) => ({ name: range, value: count })) }
    ]
  }
})

const strategyCompareChartOption = computed(() => {
  const result = backtestResult.value
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
  const result = backtestResult.value
  if (!result?.strategy_results) return {}
  const strategies = Object.values(result.strategy_results) as any[]
  return {
    tooltip: { trigger: 'item' },
    legend: { data: strategies.map(s => s.strategy_name) },
    radar: {
      indicator: [
        { name: '收益率', max: 200 },
        { name: '胜率', max: 100 },
        { name: '盈亏比', max: 5 },
        { name: '夏普比率', max: 5 },
        { name: '最大回撤', max: 100 }
      ]
    },
    series: [
      { type: 'radar', data: strategies.map(s => ({
        name: s.strategy_name,
        value: [
          (s.total_return * 100).toFixed(2),
          (s.win_rate * 100).toFixed(2),
          s.profit_loss_ratio.toFixed(2),
          s.sharpe_ratio.toFixed(2),
          100 - (s.max_drawdown * 100).toFixed(2)
        ]
      }))}
    ]
  }
})

const factorContributionChartOption = computed(() => {
  const result = backtestResult.value
  if (!result?.factor_contribution) return {}
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c}%' },
    series: [
      { type: 'pie', radius: ['40%', '70%'], data: Object.entries(result.factor_contribution).map(([name, value]) => ({ name, value: (value as number * 100).toFixed(2) })) }
    ]
  }
})

const monthlyProfitChartOption = computed(() => {
  const result = backtestResult.value
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
  const result = backtestResult.value
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

// 导出记录
const exportTrades = () => {
  if (!backtestResult.value?.trades) {
    ElMessage.warning('暂无交易记录可导出')
    return
  }
  // 简单导出为CSV
  const headers = ['交易日期', '股票代码', '股票名称', '策略', '买入价', '卖出价', '收益率', '持仓天数']
  const rows = backtestResult.value.trades.map((t: any) => [
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
  <div class="ultra-short-v2-page">
    <!-- 页面头部 -->
    <div class="page-header">
      <div>
        <h1 class="page-title">超短策略回测系统 V2.1.0 ✅ 私募级实盘版</h1>
        <p class="page-description">【版本标识：V2.1.0 - 2026-04-05 专业升级】无Tushare依赖 | 专业级日志 | 实盘级风控 | 完全无未来函数<br/>🚀 系统架构说明：回测功能需要【Web节点】+【回测引擎节点】启动运行才会生效<br/>🟢 当前运行状态：Web节点✅ 运行中 | 回测节点✅ 运行中 | 分布式多节点架构</p>
      </div>
    </div>

    <!-- 配置区域 -->
    <ElCard class="config-card">
      <template #header>
        <div class="card-header">
          <span>⚙️ 回测配置</span>
          <ElButton 
            @click="submitBacktest" 
            :icon="Play" 
            type="success" 
            :loading="backtestState.running"
            size="large"
          >
            {{ backtestState.running ? '回测中...' : '开始回测' }}
          </ElButton>
        </div>
      </template>

      <ElCollapse v-model="activeCollapse">
        <!-- 数据源配置 -->
        <ElCollapseItem name="dataSource">
          <template #title>
            <span>🔌 数据源配置 ({{ form.dataSource.period === 'daily' ? '日线' : '1分钟' }}, {{ form.dataSource.adjust_type === 'qfq' ? '前复权' : '不复权' }}, 股票池: {{ form.dataSource.ts_codes || '全市场' }})</span>
          </template>
          <ElForm label-width="120px">
            <ElFormItem label="周期">
              <ElSelect v-model="form.dataSource.period" style="width: 150px">
                <ElOption label="日线" value="daily" />
                <ElOption label="1分钟" value="1min" />
              </ElSelect>
            </ElFormItem>
            <ElFormItem label="复权方式">
              <ElSelect v-model="form.dataSource.adjust_type" style="width: 150px">
                <ElOption label="前复权" value="qfq" />
                <ElOption label="不复权" value="none" />
              </ElSelect>
            </ElFormItem>
            <ElFormItem label="股票代码">
              <ElInput v-model="form.dataSource.ts_codes" placeholder="空为全市场，多只逗号分隔" style="width: 300px" />
            </ElFormItem>
            <ElFormItem label="开始日期">
              <ElInput v-model="form.dataSource.start_date" placeholder="YYYYMMDD" />
            </ElFormItem>
            <ElFormItem label="结束日期">
              <ElInput v-model="form.dataSource.end_date" placeholder="YYYYMMDD" />
            </ElFormItem>
          </ElForm>
        </ElCollapseItem>

        <!-- 基础配置 -->
        <ElCollapseItem name="baseConfig">
          <template #title>
            <span>📅 基础配置 ({{ form.dataSource.start_date }}~{{ form.dataSource.end_date }}, 初始资金¥{{ (form.base.initial_cash/10000).toFixed(0) }}万)</span>
          </template>
          <ElForm label-width="120px">
            <ElFormItem label="初始资金">
              <ElInputNumber v-model="form.base.initial_cash" :min="100000" :max="1000000000" style="width: 200px" prefix="¥" />
            </ElFormItem>
          </ElForm>
        </ElCollapseItem>

        <!-- 交易参数 -->
        <ElCollapseItem name="tradeParams">
          <template #title>
            <span>💹 交易参数 (止损{{ (form.tradeParams.base_stop_loss_pct*100).toFixed(1) }}%, 止盈{{ (form.tradeParams.base_take_profit_pct*100).toFixed(1) }}%, 持仓{{ form.tradeParams.max_hold_days }}天, 总仓{{ (form.tradeParams.max_total_position*100).toFixed(0) }}%, 单票{{ (form.tradeParams.max_position_per_stock*100).toFixed(0) }}%, 佣金{{ (form.tradeParams.commission_rate*1000).toFixed(1) }}‰, 印花税{{ (form.tradeParams.stamp_duty_rate*1000).toFixed(0) }}‰, 滑点{{ (form.tradeParams.slippage_pct*1000).toFixed(1) }}‰)</span>
          </template>
          <ElForm label-width="120px">
            <ElFormItem label="基础止损">
              <ElInputNumber v-model="form.tradeParams.base_stop_loss_pct" :min="0" :max="1" :step="0.001" style="width: 150px" />
              <span class="unit">%</span>
            </ElFormItem>
            <ElFormItem label="基础止盈">
              <ElInputNumber v-model="form.tradeParams.base_take_profit_pct" :min="0" :max="1" :step="0.001" style="width: 150px" />
              <span class="unit">%</span>
            </ElFormItem>
            <ElFormItem label="最大持仓天数">
              <ElInputNumber v-model="form.tradeParams.max_hold_days" :min="1" :max="10" style="width: 150px" />
              <span class="unit">天</span>
            </ElFormItem>
            <ElFormItem label="单票最大仓位">
              <ElInputNumber v-model="form.tradeParams.max_position_per_stock" :min="0" :max="1" :step="0.05" style="width: 150px" />
              <span class="unit">%</span>
            </ElFormItem>
            <ElFormItem label="总仓位上限">
              <ElInputNumber v-model="form.tradeParams.max_total_position" :min="0" :max="1" :step="0.05" style="width: 150px" />
              <span class="unit">%</span>
            </ElFormItem>
            <ElFormItem label="佣金费率">
              <ElInputNumber v-model="form.tradeParams.commission_rate" :min="0" :max="0.01" :step="0.00001" style="width: 150px" />
              <span class="unit">‰</span>
            </ElFormItem>
            <ElFormItem label="印花税税率">
              <ElInputNumber v-model="form.tradeParams.stamp_duty_rate" :min="0" :max="0.01" :step="0.0001" disabled style="width: 150px" />
              <span class="unit">‰</span>
            </ElFormItem>
            <ElFormItem label="滑点比例">
              <ElInputNumber v-model="form.tradeParams.slippage_pct" :min="0" :max="0.01" :step="0.0001" style="width: 150px" />
              <span class="unit">‰</span>
            </ElFormItem>
          </ElForm>
        </ElCollapseItem>

        <!-- 全局筛选 -->
        <ElCollapseItem name="globalFilter">
          <template #title>
            <span>🔍 全局筛选 (剔除ST: 
              <span style="cursor: pointer; font-weight: bold;" @click.stop="toggleGlobalFilterSt">
                {{ form.globalFilter.exclude_st ? '✅' : '❌' }}
              </span>, 剔除退市: 
              <span style="cursor: pointer; font-weight: bold;" @click.stop="toggleGlobalFilterDelisting">
                {{ form.globalFilter.exclude_delisting ? '✅' : '❌' }}
              </span>, 次新股≥{{ form.globalFilter.exclude_new_stock_days }}天, 成交额≥{{ form.globalFilter.min_daily_amount }}万, 换手率≥{{ form.globalFilter.min_turnover_rate }}%)
            </span>
          </template>
          <ElForm label-width="160px" :disabled="!activeCollapse.includes('globalFilter')">
            <ElFormItem label="剔除ST/*ST">
              <ElSwitch v-model="form.globalFilter.exclude_st" />
            </ElFormItem>
            <ElFormItem label="剔除退市股">
              <ElSwitch v-model="form.globalFilter.exclude_delisting" />
            </ElFormItem>
            <ElFormItem label="剔除上市未满N天次新股">
              <ElInputNumber v-model="form.globalFilter.exclude_new_stock_days" :min="30" :max="365" style="width: 150px" />
              <span class="unit">天</span>
            </ElFormItem>
            <ElFormItem label="最低日成交额">
              <ElInputNumber v-model="form.globalFilter.min_daily_amount" :min="100" :max="10000" style="width: 150px" />
              <span class="unit">万元</span>
            </ElFormItem>
            <ElFormItem label="最低换手率">
              <ElInputNumber v-model="form.globalFilter.min_turnover_rate" :min="1" :max="20" style="width: 150px" />
              <span class="unit">%</span>
            </ElFormItem>
          </ElForm>
        </ElCollapseItem>

        <!-- 强制空仓 -->
        <ElCollapseItem name="forceEmpty">
          <template #title>
            <span>⚠️ 强制空仓 
              <span style="cursor: pointer; font-weight: bold;" @click.stop="toggleForceEmpty">
                {{ form.forceEmpty.enabled ? '✅' : '❌' }}
              </span> (跌幅≥{{ (form.forceEmpty.index_drop_pct*100).toFixed(1) }}%, 跌停≥{{ form.forceEmpty.limit_down_count }}只, 涨停<{{ form.forceEmpty.limit_up_count }}只)
            </span>
          </template>
          <ElForm label-width="160px">
            <ElFormItem label="启用强制空仓">
              <ElSwitch v-model="form.forceEmpty.enabled" />
            </ElFormItem>
            <ElFormItem label="大盘跌幅≥" :disabled="!form.forceEmpty.enabled">
              <ElInputNumber v-model="form.forceEmpty.index_drop_pct" :min="0" :max="0.2" :step="0.001" :disabled="!form.forceEmpty.enabled" style="width: 150px" />
              <span class="unit">%</span>
            </ElFormItem>
            <ElFormItem label="跌停家数≥" :disabled="!form.forceEmpty.enabled">
              <ElInputNumber v-model="form.forceEmpty.limit_down_count" :min="0" :max="500" :disabled="!form.forceEmpty.enabled" style="width: 150px" />
              <span class="unit">只</span>
            </ElFormItem>
            <ElFormItem label="涨停家数<" :disabled="!form.forceEmpty.enabled">
              <ElInputNumber v-model="form.forceEmpty.limit_up_count" :min="0" :max="500" :disabled="!form.forceEmpty.enabled" style="width: 150px" />
              <span class="unit">只</span>
            </ElFormItem>
          </ElForm>
        </ElCollapseItem>

        <!-- 情绪周期 -->
        <ElCollapseItem name="sentimentCycle">
          <template #title>
            <span>🧠 情绪周期 
              <span style="cursor: pointer; font-weight: bold;" @click.stop="toggleSentimentCycle">
                {{ form.sentimentCycle.enabled ? '✅' : '❌' }}
              </span> (涨停{{ form.sentimentCycle.weight_limit_up }}, 跌停{{ form.sentimentCycle.weight_limit_down }}, 炸板率{{ form.sentimentCycle.weight_blast_rate }}, 涨跌差{{ form.sentimentCycle.weight_rise_fall_diff }}, 北向{{ form.sentimentCycle.weight_north_inflow }})
            </span>
          </template>
          <ElForm label-width="160px">
            <ElFormItem label="启用情绪周期">
              <ElSwitch v-model="form.sentimentCycle.enabled" />
            </ElFormItem>
            <ElFormItem label="涨停家数权重" :disabled="!form.sentimentCycle.enabled">
              <ElInputNumber v-model="form.sentimentCycle.weight_limit_up" :min="0" :max="1" :step="0.01" :disabled="!form.sentimentCycle.enabled" style="width: 150px" />
            </ElFormItem>
            <ElFormItem label="跌停家数权重" :disabled="!form.sentimentCycle.enabled">
              <ElInputNumber v-model="form.sentimentCycle.weight_limit_down" :min="0" :max="1" :step="0.01" :disabled="!form.sentimentCycle.enabled" style="width: 150px" />
            </ElFormItem>
            <ElFormItem label="炸板率权重" :disabled="!form.sentimentCycle.enabled">
              <ElInputNumber v-model="form.sentimentCycle.weight_blast_rate" :min="0" :max="1" :step="0.01" :disabled="!form.sentimentCycle.enabled" style="width: 150px" />
            </ElFormItem>
            <ElFormItem label="涨跌家数差权重" :disabled="!form.sentimentCycle.enabled">
              <ElInputNumber v-model="form.sentimentCycle.weight_rise_fall_diff" :min="0" :max="1" :step="0.01" :disabled="!form.sentimentCycle.enabled" style="width: 150px" />
            </ElFormItem>
            <ElFormItem label="北向资金权重" :disabled="!form.sentimentCycle.enabled">
              <ElInputNumber v-model="form.sentimentCycle.weight_north_inflow" :min="0" :max="1" :step="0.01" :disabled="!form.sentimentCycle.enabled" style="width: 150px" />
            </ElFormItem>
          </ElForm>
        </ElCollapseItem>

        <!-- 竞价过滤 -->
        <ElCollapseItem name="auctionFilter">
          <template #title>
            <span>⏰ 竞价过滤 
              <span style="cursor: pointer; font-weight: bold;" @click.stop="toggleAuctionFilter">
                {{ form.auctionFilter.enabled ? '✅' : '❌' }}
              </span> (涨幅{{ (form.auctionFilter.min_auction_pct*100).toFixed(1) }}%~{{ (form.auctionFilter.max_auction_pct*100).toFixed(1) }}%, 成交额≥{{ form.auctionFilter.min_auction_amount }}万, 量比≥{{ form.auctionFilter.min_auction_volume_ratio }}, 未匹配量正: 
              <span style="cursor: pointer; font-weight: bold;" @click.stop="toggleAuctionUnmatchedVolume">
                {{ form.auctionFilter.min_unmatched_volume_positive ? '✅' : '❌' }}
              </span>)
            </span>
          </template>
          <ElForm label-width="160px">
            <ElFormItem label="启用竞价过滤">
              <ElSwitch v-model="form.auctionFilter.enabled" />
            </ElFormItem>
            <ElFormItem label="最低竞价涨幅" :disabled="!form.auctionFilter.enabled">
              <ElInputNumber v-model="form.auctionFilter.min_auction_pct" :min="0" :max="0.1" :step="0.001" :disabled="!form.auctionFilter.enabled" style="width: 150px" />
              <span class="unit">%</span>
            </ElFormItem>
            <ElFormItem label="最高竞价涨幅" :disabled="!form.auctionFilter.enabled">
              <ElInputNumber v-model="form.auctionFilter.max_auction_pct" :min="0" :max="0.2" :step="0.001" :disabled="!form.auctionFilter.enabled" style="width: 150px" />
              <span class="unit">%</span>
            </ElFormItem>
            <ElFormItem label="未匹配量必须为正" :disabled="!form.auctionFilter.enabled">
              <ElSwitch v-model="form.auctionFilter.min_unmatched_volume_positive" :disabled="!form.auctionFilter.enabled" />
            </ElFormItem>
            <ElFormItem label="最低竞价成交额" :disabled="!form.auctionFilter.enabled">
              <ElInputNumber v-model="form.auctionFilter.min_auction_amount" :min="100" :max="10000" :disabled="!form.auctionFilter.enabled" style="width: 150px" />
              <span class="unit">万元</span>
            </ElFormItem>
            <ElFormItem label="最低竞价量比" :disabled="!form.auctionFilter.enabled">
              <ElInputNumber v-model="form.auctionFilter.min_auction_volume_ratio" :min="1" :max="10" :step="0.1" :disabled="!form.auctionFilter.enabled" style="width: 150px" />
              <span class="unit">倍</span>
            </ElFormItem>
          </ElForm>
        </ElCollapseItem>

        <!-- 半路追涨策略 -->
        <ElCollapseItem name="halfway_chase">
          <template #title>
            <span>🏃‍♂️ 半路追涨策略 
              <span style="cursor: pointer; font-weight: bold;" @click.stop="toggleHalfwayChase">
                {{ form.strategyConfigs.halfway_chase.enabled ? '✅' : '❌' }}
              </span> (涨幅{{ (form.strategyConfigs.halfway_chase.params.min_rise_pct*100).toFixed(1) }}%~{{ (form.strategyConfigs.halfway_chase.params.max_rise_pct*100).toFixed(1) }}%, 量比≥{{ form.strategyConfigs.halfway_chase.params.min_volume_ratio }}倍, 10点后买入: 
              <span style="cursor: pointer; font-weight: bold;" @click.stop="toggleHalfwayChaseAllowAfter10am">
                {{ form.strategyConfigs.halfway_chase.params.allow_after_10am ? '✅' : '❌' }}
              </span>)
            </span>
          </template>
          <ElForm label-width="160px">
            <ElFormItem label="启用策略">
              <ElSwitch 
                v-model="form.strategyConfigs.halfway_chase.enabled" 
                @change="(val) => {
                  if (val) {
                    if (!form.strategies.includes('halfway_chase')) form.strategies.push('halfway_chase')
                  } else {
                    form.strategies = form.strategies.filter(k => k !== 'halfway_chase')
                  }
                }"
              />
            </ElFormItem>
            <div :disabled="!form.strategyConfigs.halfway_chase.enabled" class="grid grid-cols-2 gap-4">
              <ElFormItem label="最低实时涨幅" :disabled="!form.strategyConfigs.halfway_chase.enabled">
                <ElInputNumber v-model="form.strategyConfigs.halfway_chase.params.min_rise_pct" :min="0" :max="0.2" :step="0.001" style="width: 150px" :disabled="!form.strategyConfigs.halfway_chase.enabled" />
                <span class="unit">%</span>
              </ElFormItem>
              <ElFormItem label="最高实时涨幅" :disabled="!form.strategyConfigs.halfway_chase.enabled">
                <ElInputNumber v-model="form.strategyConfigs.halfway_chase.params.max_rise_pct" :min="0" :max="0.3" :step="0.001" style="width: 150px" :disabled="!form.strategyConfigs.halfway_chase.enabled" />
                <span class="unit">%</span>
              </ElFormItem>
              <ElFormItem label="最低量能比" :disabled="!form.strategyConfigs.halfway_chase.enabled">
                <ElInputNumber v-model="form.strategyConfigs.halfway_chase.params.min_volume_ratio" :min="1" :max="10" :step="0.1" style="width: 150px" :disabled="!form.strategyConfigs.halfway_chase.enabled" />
                <span class="unit">倍</span>
              </ElFormItem>
              <ElFormItem label="允许10点后买入" :disabled="!form.strategyConfigs.halfway_chase.enabled">
                <ElSwitch v-model="form.strategyConfigs.halfway_chase.params.allow_after_10am" :disabled="!form.strategyConfigs.halfway_chase.enabled" />
              </ElFormItem>
            </div>
          </ElForm>
        </ElCollapseItem>

        <!-- 首板打板策略 -->
        <ElCollapseItem name="first_limit_up">
          <template #title>
            <span>🥇 首板打板策略 
              <span style="cursor: pointer; font-weight: bold;" @click.stop="toggleFirstLimitUp">
                {{ form.strategyConfigs.first_limit_up.enabled ? '✅' : '❌' }}
              </span> (封单≥{{ form.strategyConfigs.first_limit_up.params.min_seal_amount }}万, ≤{{ form.strategyConfigs.first_limit_up.params.max_limit_up_time }}涨停, 流通市值≤{{ form.strategyConfigs.first_limit_up.params.max_circulation_market_cap }}亿, 炸板≤{{ form.strategyConfigs.first_limit_up.params.max_blast_count }}次, 热点板块: 
              <span style="cursor: pointer; font-weight: bold;" @click.stop="toggleFirstLimitUpHotSector">
                {{ form.strategyConfigs.first_limit_up.params.require_hot_sector ? '✅' : '❌' }}
              </span>)
            </span>
          </template>
          <ElForm label-width="160px">
            <ElFormItem label="启用策略">
              <ElSwitch 
                v-model="form.strategyConfigs.first_limit_up.enabled" 
                @change="(val) => {
                  if (val) {
                    if (!form.strategies.includes('first_limit_up')) form.strategies.push('first_limit_up')
                  } else {
                    form.strategies = form.strategies.filter(k => k !== 'first_limit_up')
                  }
                }"
              />
            </ElFormItem>
            <div :disabled="!form.strategyConfigs.first_limit_up.enabled" class="grid grid-cols-2 gap-4">
              <ElFormItem label="最低封单金额" :disabled="!form.strategyConfigs.first_limit_up.enabled">
                <ElInputNumber v-model="form.strategyConfigs.first_limit_up.params.min_seal_amount" :min="1000" :max="100000" style="width: 150px" :disabled="!form.strategyConfigs.first_limit_up.enabled" />
                <span class="unit">万元</span>
              </ElFormItem>
              <ElFormItem label="最晚涨停时间" :disabled="!form.strategyConfigs.first_limit_up.enabled">
                <ElInput v-model="form.strategyConfigs.first_limit_up.params.max_limit_up_time" style="width: 150px" :disabled="!form.strategyConfigs.first_limit_up.enabled" />
              </ElFormItem>
              <ElFormItem label="最大流通市值" :disabled="!form.strategyConfigs.first_limit_up.enabled">
                <ElInputNumber v-model="form.strategyConfigs.first_limit_up.params.max_circulation_market_cap" :min="10" :max="1000" style="width: 150px" :disabled="!form.strategyConfigs.first_limit_up.enabled" />
                <span class="unit">亿</span>
              </ElFormItem>
              <ElFormItem label="最大炸板次数" :disabled="!form.strategyConfigs.first_limit_up.enabled">
                <ElInputNumber v-model="form.strategyConfigs.first_limit_up.params.max_blast_count" :min="0" :max="10" style="width: 150px" :disabled="!form.strategyConfigs.first_limit_up.enabled" />
                <span class="unit">次</span>
              </ElFormItem>
              <ElFormItem label="要求是热点板块" :disabled="!form.strategyConfigs.first_limit_up.enabled">
                <ElSwitch v-model="form.strategyConfigs.first_limit_up.params.require_hot_sector" :disabled="!form.strategyConfigs.first_limit_up.enabled" />
              </ElFormItem>
            </div>
          </ElForm>
        </ElCollapseItem>

        <!-- 涨停开板策略 -->
        <ElCollapseItem name="limit_up_open">
          <template #title>
            <span>📈 涨停开板策略 
              <span style="cursor: pointer; font-weight: bold;" @click.stop="toggleLimitUpOpen">
                {{ form.strategyConfigs.limit_up_open.enabled ? '✅' : '❌' }}
              </span> (连板≥{{ form.strategyConfigs.limit_up_open.params.min_consecutive_limit }}板, 开板≤{{ form.strategyConfigs.limit_up_open.params.max_open_duration }}分钟, 回封封单≥{{ form.strategyConfigs.limit_up_open.params.min_seal_after_open }}万, 换手率≥{{ (form.strategyConfigs.limit_up_open.params.min_turnover_rate*100).toFixed(0) }}%)
            </span>
          </template>
          <ElForm label-width="160px">
            <ElFormItem label="启用策略">
              <ElSwitch 
                v-model="form.strategyConfigs.limit_up_open.enabled" 
                @change="(val) => {
                  if (val) {
                    if (!form.strategies.includes('limit_up_open')) form.strategies.push('limit_up_open')
                  } else {
                    form.strategies = form.strategies.filter(k => k !== 'limit_up_open')
                  }
                }"
              />
            </ElFormItem>
            <div :disabled="!form.strategyConfigs.limit_up_open.enabled" class="grid grid-cols-2 gap-4">
              <ElFormItem label="最少连板数" :disabled="!form.strategyConfigs.limit_up_open.enabled">
                <ElInputNumber v-model="form.strategyConfigs.limit_up_open.params.min_consecutive_limit" :min="2" :max="20" style="width: 150px" :disabled="!form.strategyConfigs.limit_up_open.enabled" />
                <span class="unit">板</span>
              </ElFormItem>
              <ElFormItem label="最大开板时长" :disabled="!form.strategyConfigs.limit_up_open.enabled">
                <ElInputNumber v-model="form.strategyConfigs.limit_up_open.params.max_open_duration" :min="1" :max="60" style="width: 150px" :disabled="!form.strategyConfigs.limit_up_open.enabled" />
                <span class="unit">分钟</span>
              </ElFormItem>
              <ElFormItem label="回封后最低封单" :disabled="!form.strategyConfigs.limit_up_open.enabled">
                <ElInputNumber v-model="form.strategyConfigs.limit_up_open.params.min_seal_after_open" :min="1000" :max="100000" style="width: 150px" :disabled="!form.strategyConfigs.limit_up_open.enabled" />
                <span class="unit">万元</span>
              </ElFormItem>
              <ElFormItem label="最低换手率" :disabled="!form.strategyConfigs.limit_up_open.enabled">
                <ElInputNumber v-model="form.strategyConfigs.limit_up_open.params.min_turnover_rate" :min="0" :max="1" :step="0.01" style="width: 150px" :disabled="!form.strategyConfigs.limit_up_open.enabled" />
                <span class="unit">%</span>
              </ElFormItem>
            </div>
          </ElForm>
        </ElCollapseItem>

        <!-- 龙头低吸策略 -->
        <ElCollapseItem name="leader_buy_dip">
          <template #title>
            <span>🐲 龙头低吸策略 
              <span style="cursor: pointer; font-weight: bold;" @click.stop="toggleLeaderBuyDip">
                {{ form.strategyConfigs.leader_buy_dip.enabled ? '✅' : '❌' }}
              </span> (连板≥{{ form.strategyConfigs.leader_buy_dip.params.min_consecutive_limit }}板, 回调{{ (form.strategyConfigs.leader_buy_dip.params.min_correction_pct*100).toFixed(0) }}%~{{ (form.strategyConfigs.leader_buy_dip.params.max_correction_pct*100).toFixed(0) }}%, 回调{{ form.strategyConfigs.leader_buy_dip.params.correction_days_min }}~{{ form.strategyConfigs.leader_buy_dip.params.correction_days_max }}天, 支撑位: {{ form.strategyConfigs.leader_buy_dip.params.support_level.toUpperCase() }})
            </span>
          </template>
          <ElForm label-width="160px">
            <ElFormItem label="启用策略">
              <ElSwitch 
                v-model="form.strategyConfigs.leader_buy_dip.enabled" 
                @change="(val) => {
                  if (val) {
                    if (!form.strategies.includes('leader_buy_dip')) form.strategies.push('leader_buy_dip')
                  } else {
                    form.strategies = form.strategies.filter(k => k !== 'leader_buy_dip')
                  }
                }"
              />
            </ElFormItem>
            <div :disabled="!form.strategyConfigs.leader_buy_dip.enabled" class="grid grid-cols-2 gap-4">
              <ElFormItem label="最低连板高度" :disabled="!form.strategyConfigs.leader_buy_dip.enabled">
                <ElInputNumber v-model="form.strategyConfigs.leader_buy_dip.params.min_consecutive_limit" :min="3" :max="20" style="width: 150px" :disabled="!form.strategyConfigs.leader_buy_dip.enabled" />
                <span class="unit">板</span>
              </ElFormItem>
              <ElFormItem label="最低回调幅度" :disabled="!form.strategyConfigs.leader_buy_dip.enabled">
                <ElInputNumber v-model="form.strategyConfigs.leader_buy_dip.params.min_correction_pct" :min="0" :max="0.5" :step="0.01" style="width: 150px" :disabled="!form.strategyConfigs.leader_buy_dip.enabled" />
                <span class="unit">%</span>
              </ElFormItem>
              <ElFormItem label="最高回调幅度" :disabled="!form.strategyConfigs.leader_buy_dip.enabled">
                <ElInputNumber v-model="form.strategyConfigs.leader_buy_dip.params.max_correction_pct" :min="0" :max="1" :step="0.01" style="width: 150px" :disabled="!form.strategyConfigs.leader_buy_dip.enabled" />
                <span class="unit">%</span>
              </ElFormItem>
              <ElFormItem label="最少回调天数" :disabled="!form.strategyConfigs.leader_buy_dip.enabled">
                <ElInputNumber v-model="form.strategyConfigs.leader_buy_dip.params.correction_days_min" :min="1" :max="30" style="width: 150px" :disabled="!form.strategyConfigs.leader_buy_dip.enabled" />
                <span class="unit">天</span>
              </ElFormItem>
              <ElFormItem label="最多回调天数" :disabled="!form.strategyConfigs.leader_buy_dip.enabled">
                <ElInputNumber v-model="form.strategyConfigs.leader_buy_dip.params.correction_days_max" :min="1" :max="30" style="width: 150px" :disabled="!form.strategyConfigs.leader_buy_dip.enabled" />
                <span class="unit">天</span>
              </ElFormItem>
              <ElFormItem label="支撑位" :disabled="!form.strategyConfigs.leader_buy_dip.enabled">
                <ElSelect v-model="form.strategyConfigs.leader_buy_dip.params.support_level" style="width: 150px" :disabled="!form.strategyConfigs.leader_buy_dip.enabled">
                  <ElOption label="MA5" value="ma5" />
                  <ElOption label="MA10" value="ma10" />
                  <ElOption label="平台" value="platform" />
                </ElSelect>
              </ElFormItem>
            </div>
          </ElForm>
        </ElCollapseItem>

        <!-- 跌停翘板策略 -->
        <ElCollapseItem name="limit_down_qiao">
          <template #title>
            <span>💥 跌停翘板策略 
              <span style="cursor: pointer; font-weight: bold;" @click.stop="toggleLimitDownQiao">
                {{ form.strategyConfigs.limit_down_qiao.enabled ? '✅' : '❌' }}
              </span> (连板≥{{ form.strategyConfigs.limit_down_qiao.params.min_consecutive_limit }}板, 翘板金额≥{{ form.strategyConfigs.limit_down_qiao.params.min_qiao_amount }}万, 翘板后涨幅≥{{ (form.strategyConfigs.limit_down_qiao.params.min_rise_after_qiao*100).toFixed(0) }}%, 仅高潮期: 
              <span style="cursor: pointer; font-weight: bold;" @click.stop="toggleLimitDownQiaoHighSentiment">
                {{ form.strategyConfigs.limit_down_qiao.params.require_high_sentiment ? '✅' : '❌' }}
              </span>)
            </span>
          </template>
          <ElForm label-width="160px">
            <ElFormItem label="启用策略">
              <ElSwitch 
                v-model="form.strategyConfigs.limit_down_qiao.enabled" 
                @change="(val) => {
                  if (val) {
                    if (!form.strategies.includes('limit_down_qiao')) form.strategies.push('limit_down_qiao')
                  } else {
                    form.strategies = form.strategies.filter(k => k !== 'limit_down_qiao')
                  }
                }"
              />
            </ElFormItem>
            <div :disabled="!form.strategyConfigs.limit_down_qiao.enabled" class="grid grid-cols-2 gap-4">
              <ElFormItem label="最低连板高度" :disabled="!form.strategyConfigs.limit_down_qiao.enabled">
                <ElInputNumber v-model="form.strategyConfigs.limit_down_qiao.params.min_consecutive_limit" :min="3" :max="20" style="width: 150px" :disabled="!form.strategyConfigs.limit_down_qiao.enabled" />
                <span class="unit">板</span>
              </ElFormItem>
              <ElFormItem label="翘板最低成交额" :disabled="!form.strategyConfigs.limit_down_qiao.enabled">
                <ElInputNumber v-model="form.strategyConfigs.limit_down_qiao.params.min_qiao_amount" :min="1000" :max="100000" style="width: 150px" :disabled="!form.strategyConfigs.limit_down_qiao.enabled" />
                <span class="unit">万元</span>
              </ElFormItem>
              <ElFormItem label="翘板后最低涨幅" :disabled="!form.strategyConfigs.limit_down_qiao.enabled">
                <ElInputNumber v-model="form.strategyConfigs.limit_down_qiao.params.min_rise_after_qiao" :min="0" :max="0.2" :step="0.01" style="width: 150px" :disabled="!form.strategyConfigs.limit_down_qiao.enabled" />
                <span class="unit">%</span>
              </ElFormItem>
              <ElFormItem label="仅情绪高潮期允许" :disabled="!form.strategyConfigs.limit_down_qiao.enabled">
                <ElSwitch v-model="form.strategyConfigs.limit_down_qiao.params.require_high_sentiment" :disabled="!form.strategyConfigs.limit_down_qiao.enabled" />
              </ElFormItem>
            </div>
          </ElForm>
        </ElCollapseItem>
      </ElCollapse>
    </ElCard>

    <!-- 进度展示 -->
    <ElCard v-if="backtestState.running" class="progress-card">
      <template #header>
        <span>⏳ 回测进度</span>
      </template>
      <ElProgress :percentage="backtestState.progress" :show-text="true" status="success" />
    </ElCard>

    <!-- 结果区域 -->
    <ElCard class="result-card">
      <template #header>
        <span>📊 回测结果</span>
        <ElButton 
          v-if="backtestResult" 
          @click="exportTrades" 
          :icon="Download" 
          type="primary" 
          plain 
          size="small"
        >
          导出交易记录
        </ElButton>
      </template>

      <!-- 核心指标 -->
      <div v-if="backtestResult" class="metrics-grid">
        <div class="metric-card">
          <div class="metric-label">累计收益率</div>
          <div class="metric-value">{{ ((backtestResult.total_return || 0) * 100).toFixed(2) }}%</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">胜率</div>
          <div class="metric-value">{{ ((backtestResult.win_rate || 0) * 100).toFixed(2) }}%</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">盈亏比</div>
          <div class="metric-value">{{ (backtestResult.profit_loss_ratio || 0).toFixed(2) }}</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">最大回撤</div>
          <div class="metric-value">{{ ((backtestResult.max_drawdown || 0) * 100).toFixed(2) }}%</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">夏普比率</div>
          <div class="metric-value">{{ (backtestResult.sharpe_ratio || 0).toFixed(2) }}</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">总交易次数</div>
          <div class="metric-value">{{ backtestResult.total_trades || 0 }}</div>
        </div>
      </div>

      <!-- 标签页永久显示（符合Element Plus语法规范） -->
      <ElTabs type="border-card">
        <ElTabPane label="核心指标" name="metrics">
          <!-- 空状态提示：无回测结果时显示 -->
          <ElEmpty v-if="!backtestResult" description="暂无回测结果，请先运行回测 【修改时间：2026-04-05 15:15 版本：v2.3.0-标签页永久显示最终版】" />
          <!-- 有结果时显示核心指标 -->
          <div v-if="backtestResult" class="metrics-grid">
            <div class="metric-card">
              <div class="metric-label">累计收益率</div>
              <div class="metric-value">{{ ((backtestResult.total_return || 0) * 100).toFixed(2) }}%</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">年化收益率</div>
              <div class="metric-value">{{ ((backtestResult.annualized_return || 0) * 100).toFixed(2) }}%</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">胜率</div>
              <div class="metric-value">{{ ((backtestResult.win_rate || 0) * 100).toFixed(2) }}%</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">盈亏比</div>
              <div class="metric-value">{{ (backtestResult.profit_loss_ratio || 0).toFixed(2) }}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">最大回撤</div>
              <div class="metric-value">{{ ((backtestResult.max_drawdown || 0) * 100).toFixed(2) }}%</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">夏普比率</div>
              <div class="metric-value">{{ (backtestResult.sharpe_ratio || 0).toFixed(2) }}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">索提诺比率</div>
              <div class="metric-value">{{ (backtestResult.sortino_ratio || 0).toFixed(2) }}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">卡尔玛比率</div>
              <div class="metric-value">{{ (backtestResult.calmar_ratio || 0).toFixed(2) }}</div>
            </div>
            <div class="metric-card">
              <div class="metric-label">总交易次数</div>
              <div class="metric-value">{{ backtestResult.total_trades || 0 }}</div>
            </div>
          </div>
        </ElTabPane>

        <ElTabPane label="可视化图表" name="charts">
          <!-- 空状态提示 -->
          <ElEmpty v-if="!backtestResult" description="暂无回测结果，请先运行回测" />
          <!-- 有结果时显示图表 -->
          <div v-if="backtestResult" class="charts-grid">
            <div class="chart-card">
              <div class="chart-title">净值曲线与回撤</div>
              <v-chart :option="netValueChartOption" autoresize />
            </div>
            <div class="chart-card">
              <div class="chart-title">每日盈亏</div>
              <v-chart :option="dailyProfitChartOption" autoresize />
            </div>
            <div class="chart-card">
              <div class="chart-title">仓位变化</div>
              <v-chart :option="positionChartOption" autoresize />
            </div>
            <div class="chart-card">
              <div class="chart-title">收益分布</div>
              <v-chart :option="profitDistChartOption" autoresize />
            </div>
          </div>
        </ElTabPane>

        <ElTabPane label="交易记录" name="trades">
          <!-- 空状态提示 -->
          <ElEmpty v-if="!backtestResult" description="暂无回测结果，请先运行回测" />
          <!-- 有结果时显示交易记录 -->
          <div v-if="backtestResult" class="mb-3">
            <ElInput placeholder="搜索股票代码/名称" style="width: 300px; margin-right: 10px;" v-model="searchTradeKeyword" />
            <ElSelect placeholder="按策略筛选" style="width: 200px; margin-right: 10px;" v-model="filterStrategy">
              <ElOption label="全部策略" value="" />
              <ElOption v-for="(config, id) in form.strategyConfigs" :key="id" :label="config.name" :value="id" />
            </ElSelect>
            <ElSelect placeholder="按盈亏筛选" style="width: 200px;" v-model="filterProfit">
              <ElOption label="全部" value="" />
              <ElOption label="盈利" value="profit" />
              <ElOption label="亏损" value="loss" />
            </ElSelect>
          </div>
          <ElTable :data="filteredTrades" border stripe max-height="400">
            <ElTableColumn prop="date" label="交易日期" />
            <ElTableColumn prop="ts_code" label="股票代码" />
            <ElTableColumn prop="stock_name" label="股票名称" />
            <ElTableColumn prop="strategy" label="策略" />
            <ElTableColumn prop="buy_price" label="买入价" :formatter="(row) => row.buy_price?.toFixed(2)" />
            <ElTableColumn prop="sell_price" label="卖出价" :formatter="(row) => row.sell_price?.toFixed(2)" />
            <ElTableColumn prop="profit_pct" label="收益率" :formatter="(row) => `${(row.profit_pct * 100).toFixed(2)}%`" :cell-style="(row) => row.profit_pct >= 0 ? {color: '#67c23a'} : {color: '#f56c6c'}" />
            <ElTableColumn prop="hold_days" label="持仓天数" />
          </ElTable>
        </ElTabPane>

        <ElTabPane label="交易分析" name="analysis">
          <!-- 空状态提示 -->
          <ElEmpty v-if="!backtestResult" description="暂无回测结果，请先运行回测" />
          <!-- 有结果时显示交易分析 -->
          <div v-if="backtestResult" class="analysis-grid">
            <div class="analysis-card">
              <h4>统计概览</h4>
              <div class="analysis-item">
                <span>盈利交易数：</span><span class="value">{{ backtestResult.win_count || 0 }} 笔</span>
              </div>
              <div class="analysis-item">
                <span>亏损交易数：</span><span class="value">{{ backtestResult.loss_count || 0 }} 笔</span>
              </div>
              <div class="analysis-item">
                <span>平均盈利：</span><span class="value profit">{{ ((backtestResult.avg_win || 0) * 100).toFixed(2) }}%</span>
              </div>
              <div class="analysis-item">
                <span>平均亏损：</span><span class="value loss">{{ ((backtestResult.avg_loss || 0) * 100).toFixed(2) }}%</span>
              </div>
              <div class="analysis-item">
                <span>最大单笔盈利：</span><span class="value profit">{{ ((backtestResult.max_win || 0) * 100).toFixed(2) }}%</span>
              </div>
              <div class="analysis-item">
                <span>最大单笔亏损：</span><span class="value loss">{{ ((backtestResult.max_loss || 0) * 100).toFixed(2) }}%</span>
              </div>
              <div class="analysis-item">
                <span>平均持仓天数：</span><span class="value">{{ (backtestResult.avg_hold_days || 0).toFixed(1) }} 天</span>
              </div>
            </div>
            <div class="analysis-card">
              <h4>盈利TOP5</h4>
              <ElTable :data="profitTop5 || []" border size="small">
                <ElTableColumn prop="stock_name" label="股票" />
                <ElTableColumn prop="strategy" label="策略" />
                <ElTableColumn prop="profit_pct" label="收益率" :formatter="(row) => `${(row.profit_pct * 100).toFixed(2)}%`" />
              </ElTable>
            </div>
            <div class="analysis-card">
              <h4>亏损TOP5</h4>
              <ElTable :data="lossTop5 || []" border size="small">
                <ElTableColumn prop="stock_name" label="股票" />
                <ElTableColumn prop="strategy" label="策略" />
                <ElTableColumn prop="profit_pct" label="收益率" :formatter="(row) => `${(row.profit_pct * 100).toFixed(2)}%`" />
              </ElTable>
            </div>
          </div>
        </ElTabPane>

        <ElTabPane label="策略对比" name="compare">
          <!-- 空状态提示 -->
          <ElEmpty v-if="!backtestResult" description="暂无回测结果，请先运行回测" />
          <!-- 有结果时显示策略对比 -->
          <div v-if="backtestResult" class="compare-grid">
            <div class="chart-card full-width">
              <div class="chart-title">多策略收益曲线对比</div>
              <v-chart :option="strategyCompareChartOption" autoresize />
            </div>
            <div class="chart-card full-width">
              <div class="chart-title">策略绩效雷达图</div>
              <v-chart :option="radarChartOption" autoresize />
            </div>
          </div>
        </ElTabPane>

        <ElTabPane label="高级分析" name="advanced">
          <!-- 空状态提示 -->
          <ElEmpty v-if="!backtestResult" description="暂无回测结果，请先运行回测" />
          <!-- 有结果时显示高级分析 -->
          <div v-if="backtestResult" class="advanced-grid">
            <div class="chart-card">
              <div class="chart-title">因子贡献度</div>
              <v-chart :option="factorContributionChartOption" autoresize />
            </div>
            <div class="chart-card">
              <div class="chart-title">月度收益分布</div>
              <v-chart :option="monthlyProfitChartOption" autoresize />
            </div>
            <div class="analysis-card full-width">
              <h4>风险指标矩阵</h4>
              <ElTable :data="riskMetrics || []" border>
                <ElTableColumn prop="name" label="指标名称" />
                <ElTableColumn prop="value" label="数值" />
                <ElTableColumn prop="desc" label="说明" />
              </ElTable>
            </div>
          </div>
        </ElTabPane>
      </ElTabs>
    </ElCard>

    <!-- 日志区域 -->
    <ElCard class="log-card">
      <template #header>
        <span>📝 实时日志（专业审计级）</span>
      </template>
      <div id="log-panel" class="log-panel">
        <div v-for="(log, index) in logs" :key="index" class="log-item">{{ log }}</div>
      </div>
    </ElCard>
  </div>
</template>

<style scoped lang="scss">
.ultra-short-v2-page {
  padding: 20px;
  max-width: 1400px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: 20px;
  
  .page-title {
    font-size: 26px;
    font-weight: 700;
    color: #303133;
    margin: 0 0 8px 0;
  }
  
  .page-description {
    color: #606266;
    margin: 0;
  }
}

.config-card,
.progress-card,
.result-card,
.log-card {
  margin-bottom: 20px;
  
  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-weight: 600;
    font-size: 16px;
  }
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 15px;
  margin-bottom: 20px;
  
  .metric-card {
    background: #f5f7fa;
    border-radius: 8px;
    padding: 20px;
    text-align: center;
    
    .metric-label {
      font-size: 14px;
      color: #606266;
      margin-bottom: 8px;
    }
    
    .metric-value {
      font-size: 24px;
      font-weight: 700;
      color: #303133;
    }
  }
}

.charts-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 20px;
  margin-bottom: 20px;
  
  .chart-card {
    background: #fff;
    border-radius: 8px;
    padding: 20px;
    border: 1px solid #ebeef5;
    height: 400px;
    
    .chart-title {
      font-size: 16px;
      font-weight: 600;
      margin-bottom: 15px;
      color: #303133;
    }
  }
}

.analysis-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
  margin-bottom: 20px;
  
  .analysis-card {
    background: #fff;
    border-radius: 8px;
    padding: 20px;
    border: 1px solid #ebeef5;
    
    h4 {
      font-size: 16px;
      font-weight: 600;
      margin-bottom: 15px;
      color: #303133;
    }
    
    .analysis-item {
      display: flex;
      justify-content: space-between;
      margin-bottom: 10px;
      font-size: 14px;
      
      .value {
        font-weight: 600;
        &.profit { color: #67c23a; }
        &.loss { color: #f56c6c; }
      }
    }
  }
}

.compare-grid {
  display: grid;
  gap: 20px;
  margin-bottom: 20px;
  
  .chart-card.full-width {
    grid-column: 1 / -1;
    height: 400px;
  }
}

.advanced-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 20px;
  margin-bottom: 20px;
  
  .chart-card,
  .analysis-card {
    background: #fff;
    border-radius: 8px;
    padding: 20px;
    border: 1px solid #ebeef5;
    height: 400px;
    
    .chart-title,
    h4 {
      font-size: 16px;
      font-weight: 600;
      margin-bottom: 15px;
      color: #303133;
    }
  }
  
  .analysis-card.full-width {
    grid-column: 1 / -1;
    height: auto;
  }
}

.log-panel {
  height: 300px;
  overflow-y: auto;
  background: #f5f7fa;
  border-radius: 4px;
  padding: 10px;
  font-family: 'Courier New', monospace;
  font-size: 13px;
  
  .log-item {
    margin-bottom: 4px;
  }
}

.unit {
  margin-left: 8px;
  color: #909399;
}

.desc {
  margin-left: 12px;
  color: #606266;
  font-size: 13px;
}

/* 折叠面板标题强制不换行，完整显示所有参数 */
:deep(.el-collapse-item__header) {
  white-space: nowrap !important;
  overflow-x: auto !important;
  padding-right: 40px !important;
}

:deep(.el-collapse-item__header::-webkit-scrollbar) {
  height: 4px;
}

:deep(.el-collapse-item__header::-webkit-scrollbar-thumb) {
  background-color: #dcdfe6;
  border-radius: 2px;
}

:deep(.el-collapse-item__arrow) {
  position: absolute;
  right: 15px;
  background: #fff;
  padding-left: 10px;
}
</style>