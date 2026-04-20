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
const activeCollapse = ref<string[]>([])

// 每个策略的动态标题
const halfwayChaseTitle = computed(() => `🏃‍♂️ 半路追涨策略 ${form.strategyConfigs.halfway_chase.enabled ? '✅' : '❌'} (涨幅${(form.strategyConfigs.halfway_chase.params.min_rise_pct*100).toFixed(1)}%~${(form.strategyConfigs.halfway_chase.params.max_rise_pct*100).toFixed(1)}%, 量比≥${form.strategyConfigs.halfway_chase.params.min_volume_ratio}倍, 10点后买入: ${form.strategyConfigs.halfway_chase.params.allow_after_10am ? '✅' : '❌'})`)
const firstLimitUpTitle = computed(() => `🥇 首板打板策略 ${form.strategyConfigs.first_limit_up.enabled ? '✅' : '❌'} (封单≥${form.strategyConfigs.first_limit_up.params.min_seal_amount}万, ≤${form.strategyConfigs.first_limit_up.params.max_limit_up_time}涨停, 流通市值≤${form.strategyConfigs.first_limit_up.params.max_circulation_market_cap}亿, 热点板块: ${form.strategyConfigs.first_limit_up.params.require_hot_sector ? '✅' : '❌'})`)
const limitUpOpenTitle = computed(() => `📈 涨停开板策略 ${form.strategyConfigs.limit_up_open.enabled ? '✅' : '❌'} (连板≥${form.strategyConfigs.limit_up_open.params.min_consecutive_limit}板, 开板≤${form.strategyConfigs.limit_up_open.params.max_open_duration}分钟)`)
const leaderBuyDipTitle = computed(() => `🐲 龙头低吸策略 ${form.strategyConfigs.leader_buy_dip.enabled ? '✅' : '❌'} (连板≥${form.strategyConfigs.leader_buy_dip.params.min_consecutive_limit}板, 回调${(form.strategyConfigs.leader_buy_dip.params.min_correction_pct*100).toFixed(0)}%~${(form.strategyConfigs.leader_buy_dip.params.max_correction_pct*100).toFixed(0)}%, 回调${form.strategyConfigs.leader_buy_dip.params.correction_days_min}~${form.strategyConfigs.leader_buy_dip.params.correction_days_max}天, 支撑位: ${form.strategyConfigs.leader_buy_dip.params.support_level.toUpperCase()})`)
const limitDownQiaoTitle = computed(() => `💥 跌停翘板策略 ${form.strategyConfigs.limit_down_qiao.enabled ? '✅' : '❌'} (连板≥${form.strategyConfigs.limit_down_qiao.params.min_consecutive_limit}板, 翘板金额≥${form.strategyConfigs.limit_down_qiao.params.min_qiao_amount}万, 翘板后涨幅≥${(form.strategyConfigs.limit_down_qiao.params.min_rise_after_qiao*100).toFixed(0)}%, 仅高潮期: ${form.strategyConfigs.limit_down_qiao.params.require_high_sentiment ? '✅' : '❌'})`)

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
const auctionFilterTitle = computed(() => `⏰ 竞价过滤 ${form.auctionFilter.enabled ? '✅' : '❌'} (涨幅${(form.auctionFilter.min_auction_pct*100).toFixed(1)}%~${(form.auctionFilter.max_auction_pct*100).toFixed(1)}%, 成交额≥${form.auctionFilter.min_auction_amount}万, 量比≥${form.auctionFilter.min_auction_volume_ratio}倍, 未匹配量正: ${form.auctionFilter.min_unmatched_volume_positive ? '✅' : '❌'})`)
const strategyConfigTitle = computed(() => `🎯 策略配置 (已选: ${form.strategies.map(id => form.strategyConfigs[id as keyof typeof form.strategyConfigs]?.name).join(', ') || '无'})`)

// ==================== 生命周期 ====================
onMounted(() => {
  // 页面加载完成
  addLog('✅ 超短策略回测V2.0系统加载完成')
  addLog('💡 所有实盘级功能默认开启，可直接运行回测')
  
  // 自动加载默认演示回测数据（无需运行回测即可看到所有图表）
  const mockResult = {
    total_return: 2.8834,
    annualized_return: 12.56,
    win_rate: 0.494,
    profit_loss_ratio: 1.78,
    max_drawdown: 0.3536,
    sharpe_ratio: 2.45,
    sortino_ratio: 3.21,
    calmar_ratio: 1.87,
    total_trades: 166,
    win_count: 82,
    loss_count: 84,
    avg_win: 0.072,
    avg_loss: -0.040,
    max_win: 0.213,
    max_loss: -0.095,
    avg_hold_days: 2.3,
    volatility: 0.2345,
    information_ratio: 1.23,
    
    // 净值与回撤数据
    net_value_series: Array.from({length: 75}, (_, i) => ({
      date: `2026${String(Math.floor(i/22)+1).padStart(2, '0')}${String((i%22)+1).padStart(2, '0')}`,
      value: 1 + Math.random() * 3 + i * 0.03
    })),
    drawdown_series: Array.from({length: 75}, (_, i) => ({
      date: `2026${String(Math.floor(i/22)+1).padStart(2, '0')}${String((i%22)+1).padStart(2, '0')}`,
      value: Math.random() * 0.35
    })),
    
    // 每日盈亏
    daily_profit: Object.fromEntries(Array.from({length: 75}, (_, i) => [
      `2026${String(Math.floor(i/22)+1).padStart(2, '0')}${String((i%22)+1).padStart(2, '0')}`,
      (Math.random() - 0.4) * 0.1
    ])),
    
    // 仓位数据
    position_series: Array.from({length: 75}, (_, i) => ({
      date: `2026${String(Math.floor(i/22)+1).padStart(2, '0')}${String((i%22)+1).padStart(2, '0')}`,
      value: Math.random() * 0.8
    })),
    
    // 收益分布
    profit_distribution: {
      '-5%~0%': 34,
      '0%~5%': 42,
      '5%~10%': 58,
      '10%~15%': 21,
      '15%+': 11
    },
    
    // 策略结果
    strategy_results: {
      halfway_chase: {
        strategy_name: '半路追涨',
        total_return: 2.8834,
        win_rate: 0.494,
        profit_loss_ratio: 1.78,
        sharpe_ratio: 2.45,
        max_drawdown: 0.3536,
        net_value_series: Array.from({length: 75}, (_, i) => ({
          date: `2026${String(Math.floor(i/22)+1).padStart(2, '0')}${String((i%22)+1).padStart(2, '0')}`,
          value: 1 + Math.random() * 3 + i * 0.03
        }))
      },
      first_limit_up: {
        strategy_name: '首板打板',
        total_return: 1.9245,
        win_rate: 0.452,
        profit_loss_ratio: 1.65,
        sharpe_ratio: 2.12,
        max_drawdown: 0.2876,
        net_value_series: Array.from({length: 75}, (_, i) => ({
          date: `2026${String(Math.floor(i/22)+1).padStart(2, '0')}${String((i%22)+1).padStart(2, '0')}`,
          value: 1 + Math.random() * 2 + i * 0.02
        }))
      }
    },
    
    // 因子贡献
    factor_contribution: {
      '一月反转': 0.35,
      '量能因子': 0.22,
      '波动率因子': 0.18,
      '流动性因子': 0.15,
      '其他因子': 0.10
    },
    
    // 月度收益
    monthly_profit: {
      '2026-01': 0.423,
      '2026-02': 0.785,
      '2026-03': 0.892
    },
    
    // 交易记录
    trades: Array.from({length: 50}, (_, i) => ({
      date: `20260${Math.floor(Math.random()*3)+1}${String(Math.floor(Math.random()*28)+1).padStart(2, '0')}`,
      ts_code: `${String(Math.floor(Math.random()*1000)).padStart(6, '0')}.SZ`,
      stock_name: `股票${i+1}`,
      strategy: ['半路追涨', '首板打板', '涨停开板'][Math.floor(Math.random()*3)],
      buy_price: Math.random() * 50 + 10,
      sell_price: Math.random() * 60 + 10,
      profit_pct: (Math.random() - 0.4) * 0.2,
      hold_days: Math.floor(Math.random() * 3) + 1
    }))
  }
  
  backtestResult.value = mockResult
  addLog('✅ 已自动加载演示回测数据，所有图表可正常查看')
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
          name: (form.strategyConfigs[id as keyof typeof form.strategyConfigs] as any).name,
          params: (form.strategyConfigs[id as keyof typeof form.strategyConfigs] as any).params,
        })),
      },
      enable_force_empty: form.forceEmpty.enabled,
      enable_sentiment_cycle: form.sentimentCycle.enabled,
      enable_auction_filter: form.auctionFilter.enabled,
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
        // 字段映射：后端返回结构适配前端期望结构
        const res = data.result
        // 日期转换函数：YYYYMMDD -> YYYY-MM-DD
        const formatDate = (dateStr: string) => {
          if (!dateStr || typeof dateStr !== 'string') return dateStr
          if (dateStr.length === 8) {
            return `${dateStr.slice(0,4)}-${dateStr.slice(4,6)}-${dateStr.slice(6,8)}`
          }
          return dateStr
        }
        backtestResult.value = {
          ...res,
          // 适配净值和回撤曲线，转换日期格式
          net_value_series: (res.net_value_series || res.net_value || []).map((item: any) => ({
            ...item,
            date: formatDate(item.date),
          })),
          drawdown_series: (res.drawdown_series || res.drawdown || []).map((item: any) => ({
            ...item,
            date: formatDate(item.date),
          })),
          // 适配交易记录
          trades: res.trades || res.trade_records || [],
          // 适配每日收益，转换日期格式
          daily_profit: Object.fromEntries(
            Object.entries(res.daily_profit || res.daily_return || {}).map(([date, value]) => [formatDate(date), value])
          ),
          // 适配仓位曲线，转换日期格式
          position_series: (res.position_series || res.position || []).map((item: any) => ({
            ...item,
            date: formatDate(item.date),
          })),
          // 适配收益分布
          profit_distribution: res.profit_distribution || res.return_distribution || {},
          // 适配策略结果
          strategy_results: res.strategy_results || res.strategies || {},
          // 适配因子贡献
          factor_contribution: res.factor_contribution || res.factor || {},
          // 适配月度收益，转换日期格式
          monthly_profit: Object.fromEntries(
            Object.entries(res.monthly_profit || res.monthly_return || {}).map(([date, value]) => [formatDate(date), value])
          ),
        }
        backtestState.running = false
        addLog('✅ 回测全部完成！')
        ElMessage.success('回测完成！')
        // 自动滚动到结果区域，让用户看到结果
        setTimeout(() => {
          const resultCard = document.querySelector('.result-card')
          if (resultCard) {
            resultCard.scrollIntoView({ behavior: 'smooth', block: 'start' })
          }
        }, 200)
        ws.close()
      } else if (data.type === 'status' && data.status === 'completed') {
        // 字段映射：后端返回结构适配前端期望结构
        const res = data.result
        // 日期转换函数：YYYYMMDD -> YYYY-MM-DD
        const formatDate = (dateStr: string) => {
          if (!dateStr || typeof dateStr !== 'string') return dateStr
          if (dateStr.length === 8) {
            return `${dateStr.slice(0,4)}-${dateStr.slice(4,6)}-${dateStr.slice(6,8)}`
          }
          return dateStr
        }
        backtestResult.value = {
          ...res,
          // 适配净值和回撤曲线，转换日期格式
          net_value_series: (res.net_value_series || res.net_value || []).map((item: any) => ({
            ...item,
            date: formatDate(item.date),
          })),
          drawdown_series: (res.drawdown_series || res.drawdown || []).map((item: any) => ({
            ...item,
            date: formatDate(item.date),
          })),
          // 适配交易记录
          trades: res.trades || res.trade_records || [],
          // 适配每日收益，转换日期格式
          daily_profit: Object.fromEntries(
            Object.entries(res.daily_profit || res.daily_return || {}).map(([date, value]) => [formatDate(date), value])
          ),
          // 适配仓位曲线，转换日期格式
          position_series: (res.position_series || res.position || []).map((item: any) => ({
            ...item,
            date: formatDate(item.date),
          })),
          // 适配收益分布
          profit_distribution: res.profit_distribution || res.return_distribution || {},
          // 适配策略结果
          strategy_results: res.strategy_results || res.strategies || {},
          // 适配因子贡献
          factor_contribution: res.factor_contribution || res.factor || {},
          // 适配月度收益，转换日期格式
          monthly_profit: Object.fromEntries(
            Object.entries(res.monthly_profit || res.monthly_return || {}).map(([date, value]) => [formatDate(date), value])
          ),
        }
        backtestState.running = false
        addLog('✅ 回测全部完成！')
        ElMessage.success('回测完成！')
        // 自动滚动到结果区域，让用户看到结果
        setTimeout(() => {
          const resultCard = document.querySelector('.result-card')
          if (resultCard) {
            resultCard.scrollIntoView({ behavior: 'smooth', block: 'start' })
          }
        }, 200)
        ws.close()
      } else if (data.type === 'error') {
        addLog(`❌ 回测失败：${data.message || '未知错误'}`)
        backtestState.running = false
        ElMessage.error(`回测失败：${data.message || '未知错误'}`)
        ws.close()
      }
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

// 筛选变量
const searchTradeKeyword = ref('')
const filterStrategy = ref('')
const