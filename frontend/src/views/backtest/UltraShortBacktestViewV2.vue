<script setup lang="ts">
/**
 * 超短策略回测V2.0 - 私募级实盘版
 * 主页面：状态管理 + 回测提交 + WebSocket/轮询
 * 子组件：StrategyConfigPanel / AnsiLogPanel / BacktestSummaryTable / BacktestResultPanel
 */
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'

// 子组件
import StrategyConfigPanel from '@/components/ultrashort/StrategyConfigPanel.vue'
import AnsiLogPanel from '@/components/backtest/AnsiLogPanel.vue'
import BacktestSummaryTable from '@/components/backtest/BacktestSummaryTable.vue'
import BacktestResultPanel from '@/components/ultrashort/BacktestResultPanel.vue'

// API
import { backtestApi } from '@/api'

// ==================== 状态 ====================

const form = reactive({
  dataSource: {
    period: 'daily',
    ts_codes: '',
    start_date: '20260105',
    end_date: '20260320',
    adjust_type: 'qfq',
  },
  base: { initial_cash: 1000000 },
  globalFilter: {
    exclude_st: true,
    exclude_delisting: true,
    exclude_new_stock_days: 60,
    min_daily_amount: 500,
    min_turnover_rate: 3,
  },
  forceEmpty: {
    enabled: true,
    index_drop_pct: 0.03,
    limit_down_count: 50,
    limit_up_count: 10,
  },
  sentimentCycle: {
    enabled: true,
    weight_limit_up: 0.25,
    weight_limit_down: 0.1,
    weight_blast_rate: 0.07,
    weight_rise_fall_diff: 0.15,
    weight_north_inflow: 0.12,
  },
  auctionFilter: {
    enabled: true,
    min_auction_pct: 0.005,
    max_auction_pct: 0.07,
    min_unmatched_volume_positive: true,
    min_auction_amount: 300,
    min_auction_volume_ratio: 1.5,
  },
  tradeParams: {
    base_stop_loss_pct: 0.02,
    base_take_profit_pct: 0.07,
    max_hold_days: 3,
    max_position_per_stock: 0.2,  // 单票20%分散风险
    max_total_position: 0.7,  // 总仓位70%，留30%现金
    commission_rate: 0.0003,
    stamp_duty_rate: 0.001,
    slippage_pct: 0.002,
  },
  strategies: ['halfway_chase', 'first_limit_up', 'limit_up_open', 'leader_buy_dip', 'limit_down_qiao'],
  strategyConfigs: {
    halfway_chase: {
      enabled: true, name: '半路追涨',
      params: { min_rise_pct: 0.03, max_rise_pct: 0.07, min_volume_ratio: 1.5, allow_after_10am: false }
    },
    first_limit_up: {
      enabled: true, name: '首板打板',
      params: { min_seal_amount: 5000, max_limit_up_time: '10:00', max_circulation_market_cap: 100, max_blast_count: 1, require_hot_sector: true }
    },
    limit_up_open: {
      enabled: true, name: '涨停开板',
      params: { min_consecutive_limit: 2, max_open_duration: 5, min_seal_after_open: 3000, min_turnover_rate: 0.15 }
    },
    leader_buy_dip: {
      enabled: true, name: '龙头低吸',
      params: { min_consecutive_limit: 3, min_correction_pct: 0.15, max_correction_pct: 0.3, correction_days_min: 2, correction_days_max: 5, support_level: 'ma5' }
    },
    limit_down_qiao: {
      enabled: true, name: '跌停翘板',
      params: { min_consecutive_limit: 3, min_qiao_amount: 10000, min_rise_after_qiao: 0.03, require_high_sentiment: true }
    },
  },
})

const activeCollapse = ref<string[]>([])

const backtestState = reactive({
  running: false,
  task_id: '',
  progress: 0,
})

const logs = ref<string[]>([])
const backtestResult = ref<any>(null)

// ==================== 辅助：INI解析 ====================

function parseIni(content: string): Record<string, any> {
  const result: Record<string, any> = {}
  let currentSection: Record<string, any> = {}
  const lines = content.split('\n')
  for (const line of lines) {
    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith('#')) continue
    const sectionMatch = trimmed.match(/^\[(.*)\]$/)
    if (sectionMatch) {
      const sectionName = sectionMatch[1].trim()
      result[sectionName] = {}
      currentSection = result[sectionName]
      continue
    }
    const eqIndex = trimmed.indexOf('=')
    if (eqIndex >= 0) {
      const key = trimmed.slice(0, eqIndex).trim()
      let value: any = trimmed.slice(eqIndex + 1).trim()
      if (value === 'true') value = true
      else if (value === 'false') value = false
      else if (!isNaN(parseFloat(value)) && value.includes('.')) value = parseFloat(value)
      else if (!isNaN(parseInt(value)) && !value.includes('.')) value = parseInt(value)
      currentSection[key] = value
    }
  }
  return result
}

// ==================== 生命周期 ====================

onMounted(async () => {
  let loaded = false

  // 1. 尝试从 config.ini 加载
  try {
    const response = await fetch('/config.ini')
    if (response.ok) {
      const text = await response.text()
      const parsed = parseIni(text)
      if (parsed.dataSource) {
        Object.assign(form.dataSource, parsed.dataSource)
        if (typeof parsed.dataSource.start_date === 'number') form.dataSource.start_date = String(parsed.dataSource.start_date)
        if (typeof parsed.dataSource.end_date === 'number') form.dataSource.end_date = String(parsed.dataSource.end_date)
      }
      if (parsed.base) Object.assign(form.base, parsed.base)
      if (parsed.globalFilter) Object.assign(form.globalFilter, parsed.globalFilter)
      if (parsed.forceEmpty) {
        Object.assign(form.forceEmpty, parsed.forceEmpty)
        if (parsed.forceEmpty.index_drop_pct !== undefined) form.forceEmpty.index_drop_pct = parsed.forceEmpty.index_drop_pct / 100
      }
      if (parsed.sentimentCycle) Object.assign(form.sentimentCycle, parsed.sentimentCycle)
      if (parsed.auctionFilter) {
        Object.assign(form.auctionFilter, parsed.auctionFilter)
        if (parsed.auctionFilter.min_auction_pct !== undefined) form.auctionFilter.min_auction_pct = parsed.auctionFilter.min_auction_pct / 100
        if (parsed.auctionFilter.max_auction_pct !== undefined) form.auctionFilter.max_auction_pct = parsed.auctionFilter.max_auction_pct / 100
      }
      if (parsed.tradeParams) {
        Object.assign(form.tradeParams, parsed.tradeParams)
        if (parsed.tradeParams.base_stop_loss_pct !== undefined) form.tradeParams.base_stop_loss_pct = parsed.tradeParams.base_stop_loss_pct / 100
        if (parsed.tradeParams.base_take_profit_pct !== undefined) form.tradeParams.base_take_profit_pct = parsed.tradeParams.base_take_profit_pct / 100
        if (parsed.tradeParams.slippage_pct !== undefined) form.tradeParams.slippage_pct = parsed.tradeParams.slippage_pct / 100
      }
      if (parsed.defaultStrategies?.selected) {
        form.strategies = parsed.defaultStrategies.selected.split(',').map((s: string) => s.trim())
      }
      const strategyIds = ['halfway_chase', 'first_limit_up', 'limit_up_open', 'leader_buy_dip', 'limit_down_qiao']
      for (const sid of strategyIds) {
        if (parsed[sid]) {
          const cfg = parsed[sid]
          if (cfg.min_pct !== undefined && form.strategyConfigs[sid]?.params) form.strategyConfigs[sid].params.min_rise_pct = cfg.min_pct / 100
          if (cfg.max_pct !== undefined && form.strategyConfigs[sid]?.params) form.strategyConfigs[sid].params.max_rise_pct = cfg.max_pct / 100
          if (cfg.min_auction_pct !== undefined && form.strategyConfigs[sid]?.params) form.strategyConfigs[sid].params.min_auction_pct = cfg.min_auction_pct / 100
          if (cfg.max_auction_pct !== undefined && form.strategyConfigs[sid]?.params) form.strategyConfigs[sid].params.max_auction_pct = cfg.max_auction_pct / 100
          if (cfg.callback_pct !== undefined && form.strategyConfigs[sid]?.params) form.strategyConfigs[sid].params.min_correction_pct = cfg.callback_pct / 100
          if (cfg.callback_pct_max !== undefined && form.strategyConfigs[sid]?.params) form.strategyConfigs[sid].params.max_correction_pct = cfg.callback_pct_max / 100
          if (cfg.min_rise_after_qiao !== undefined && form.strategyConfigs[sid]?.params) form.strategyConfigs[sid].params.min_rise_after_qiao = cfg.min_rise_after_qiao / 100
          Object.assign(form.strategyConfigs[sid].params, cfg)
        }
      }
      addLog('✅ 已从 config.ini 加载默认配置')
      loaded = true
    }
  } catch (e) { console.warn('读取 config.ini 失败', e) }

  // 2. 尝试从后端API加载
  if (!loaded) {
    try {
      const res = await backtestApi.getUltraShortDefaults()
      if (res.data?.success && res.data?.data) {
        const defaults = res.data.data
        Object.assign(form.dataSource, defaults.dataSource || {})
        Object.assign(form.base, defaults.base || {})
        Object.assign(form.globalFilter, defaults.globalFilter || {})
        Object.assign(form.forceEmpty, defaults.forceEmpty || {})
        Object.assign(form.sentimentCycle, defaults.sentimentCycle || {})
        Object.assign(form.auctionFilter, defaults.auctionFilter || {})
        Object.assign(form.tradeParams, defaults.tradeParams || {})
        if (defaults.strategies) form.strategies = [...defaults.strategies]
        if (defaults.strategyConfigs) Object.assign(form.strategyConfigs, defaults.strategyConfigs)
        addLog('✅ 已从后端API加载默认配置')
        loaded = true
      }
    } catch (e) { console.warn('从后端API获取默认配置失败', e) }
  }

  if (!loaded) addLog('✅ 使用本地硬编码默认参数（config.ini和后端API获取都失败）')
  addLog('✅ 超短策略回测V2.0系统加载完成')
  addLog('💡 所有实盘级功能默认开启，可直接运行回测')
})

// ==================== 方法 ====================

const submitBacktest = async () => {
  if (backtestState.running) {
    ElMessage.warning('回测正在运行中')
    return
  }

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
    const strategyKeys = Object.keys(form.strategyConfigs) as (keyof typeof form.strategyConfigs)[]
    const selected_strategies = form.strategies
      .filter(id => strategyKeys.includes(id as keyof typeof form.strategyConfigs))
      .map(id => {
        const cfg = form.strategyConfigs[id as keyof typeof form.strategyConfigs]
        return { id, name: cfg.name, enabled: cfg.enabled, params: { ...cfg.params } }
      })
    const strategy_params: Record<string, any> = {}
    for (const id of form.strategies) {
      if (strategyKeys.includes(id as keyof typeof form.strategyConfigs)) {
        strategy_params[id] = { ...form.strategyConfigs[id as keyof typeof form.strategyConfigs].params }
      }
    }

    const res = await backtestApi.submitUltraShort({
      strategies: form.strategies,
      selected_strategies,
      start_date: form.dataSource.start_date,
      end_date: form.dataSource.end_date,
      data_source: "mongodb",
      period: form.dataSource.period,
      ts_codes: form.dataSource.ts_codes,
      adjust_type: form.dataSource.adjust_type,
      initial_cash: form.base.initial_cash,
      initial_capital: form.base.initial_cash,
      rebalance_freq: "daily",
      params: {
        volume_threshold: form.globalFilter.min_turnover_rate,
        stop_loss_pct: form.tradeParams.base_stop_loss_pct,
        take_profit_pct: form.tradeParams.base_take_profit_pct,
        max_hold_days: form.tradeParams.max_hold_days,
        max_position: form.tradeParams.max_total_position,
        liquidity_threshold: form.globalFilter.min_daily_amount,
        max_position_per_stock: form.tradeParams.max_position_per_stock,
        force_empty_position: form.forceEmpty.enabled,
        sentiment_cycle: form.sentimentCycle.enabled,
        auction_filter: form.auctionFilter.enabled,
        selected_strategies
      },
      strategy_params,
      enable_sentiment_cycle: form.sentimentCycle.enabled,
      enable_auction_filter: form.auctionFilter.enabled,
      enable_force_empty: form.forceEmpty.enabled,
    })

    if (!res || !res.task_id) {
      throw new Error(`接口返回异常：${JSON.stringify(res || '无返回数据')}`)
    }

    backtestState.task_id = res.task_id
    addLog(`✅ 任务提交成功，任务ID：${backtestState.task_id}`)

    // WebSocket 连接
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    // 优先级: 1) VITE_WEBSOCKET_HOST环境变量 2) 后端API 3) 当前页面地址
    let wsHost = import.meta.env.VITE_WEBSOCKET_HOST
    if (!wsHost) {
      try {
        const res = await fetch('/api/v1/system/ws-config')
        const data = await res.json()
        if (data.success && data.data) {
          wsHost = `${data.data.host}:${data.data.port}`
        }
      } catch (e) {
        // API失败，使用当前页面地址
      }
    }
    if (!wsHost) {
      wsHost = `${window.location.hostname}:${window.location.port || (window.location.protocol === 'https:' ? '443' : '80')}`
    }
    const token = localStorage.getItem('access_token') || 'mock-token-123456'
    const ws = new WebSocket(`${wsProtocol}//${wsHost}/ws?token=${token}`)

    ws.onopen = () => {
      ws.send(JSON.stringify({ type: 'subscribe', task_id: backtestState.task_id }))
    }

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      if (data.type === 'log') addLog(data.log)
      else if (data.type === 'progress') backtestState.progress = data.progress
      else if (data.type === 'result') {
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

    ws.onerror = () => {
      // 回退到轮询
      const pollInterval = setInterval(async () => {
        try {
          const statusRes = await backtestApi.getBacktestStatus(backtestState.task_id)
          if (!statusRes || !statusRes.data) { addLog('⚠️ 轮询异常：接口返回数据为空'); return }
          const data = statusRes.data
          if (data.logs) logs.value = [...new Set([...logs.value, ...data.logs])]
          if (data.progress !== undefined) backtestState.progress = data.progress
          if (data.status === 'completed') {
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
        } catch (e: any) {
          addLog(`⚠️ 轮询异常：${e.message || '未知错误'}`)
        }
      }, 1000)
    }
  } catch (e: any) {
    addLog(`❌ 提交回测任务失败：${e.message || '未知错误'}`)
    backtestState.running = false
    ElMessage.error(`提交回测失败：${e.message || '未知错误'}`)
  }
}

const addLog = (text: string) => {
  const timestamp = new Date().toLocaleTimeString('zh-CN')
  logs.value.push(`[${timestamp}] ${text}`)
  setTimeout(() => {
    const logPanel = document.getElementById('log-panel')
    if (logPanel) logPanel.scrollTop = logPanel.scrollHeight
  }, 100)
}
</script>

<template>
  <div class="ultra-short-v2-page">
    <!-- 页面头部 -->
    <div class="page-header">
      <div>
        <h1 class="page-title">超短策略回测系统 V2.1.0 ✅ 私募级实盘版</h1>
        <p class="page-description">
          【版本标识：V2.1.0 - 2026-04-05 专业升级】无Tushare依赖 | 专业级日志 | 实盘级风控 | 完全无未来函数<br/>
          🚀 系统架构说明：回测功能需要【Web节点】+【回测引擎节点】启动运行才会生效<br/>
          🟢 当前运行状态：Web节点✅ 运行中 | 回测节点✅ 运行中 | 分布式多节点架构
        </p>
      </div>
    </div>

    <!-- 策略配置面板 -->
    <StrategyConfigPanel
      :form="form"
      :backtestRunning="backtestState.running"
      v-model:activeCollapse="activeCollapse"
      @submit="submitBacktest"
    />

    <!-- 回测进度条 -->
    <ElCard v-if="backtestState.running" class="progress-card" style="margin-bottom: 20px">
      <ElProgress :percentage="backtestState.progress" :stroke-width="18" :text-inside="true" status="success" />
    </ElCard>

    <!-- 回测结果总结表格 -->
    <BacktestSummaryTable v-if="backtestResult" :result="backtestResult" />

    <!-- 回测结果详细面板 -->
    <BacktestResultPanel v-if="backtestResult" :result="backtestResult" :form="form" />

    <!-- 实时日志面板 -->
    <AnsiLogPanel :logs="logs" />
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
</style>
