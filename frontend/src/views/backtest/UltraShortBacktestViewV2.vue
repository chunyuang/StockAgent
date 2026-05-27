<script setup lang="ts">
/**
 * 超短策略回测V2.0 - 私募级实盘版
 * 主页面：状态管理 + 回测提交 + WebSocket/轮询
 * 子组件：StrategyConfigPanel / AnsiLogPanel / BacktestSummaryTable / BacktestResultPanel
 */
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import StrategyConfigPanel from '@/components/ultrashort/StrategyConfigPanel.vue'
import AnsiLogPanel from '@/components/backtest/AnsiLogPanel.vue'
import BacktestSummaryTable from '@/components/backtest/BacktestSummaryTable.vue'
import BacktestResultPanel from '@/components/ultrashort/BacktestResultPanel.vue'
import BacktestHistoryPanel from '@/components/backtest/BacktestHistoryPanel.vue'
import DataStatusPanel from '@/components/ultrashort/DataStatusPanel.vue'
import FactorReferencePanel from '@/components/ultrashort/FactorReferencePanel.vue'

import { GLOBAL_RISK, STRATEGY_CONFIGS } from '@/config/strategyDefaults'
import { systemHealthCheck } from '@/api/modules/backtest'
import { SWEEP_PARAMS } from '@/config/backtestConstants'

// API
import { backtestApi } from '@/api'
import type { BacktestHistoryItem } from '@/api/modules/backtest'

// ECharts for sweep chart
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, LegendComponent, GridComponent } from 'echarts/components'
import VChart from 'vue-echarts'

use([CanvasRenderer, LineChart, TitleComponent, TooltipComponent, LegendComponent, GridComponent])

// ==================== 参数扫描配置 ====================

// SWEEP_PARAMS - imported from shared config
// STRATEGY_NAMES - imported from shared config

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
    enable_ma60_filter: true,
    enable_sector_concentration: true,
  },
  forceEmpty: {
    enabled: true,
    index_drop_pct: 0.03,
    limit_down_count: 80,  // 【V65修复】与GLOBAL_RISK.force_empty_limit_down=80对齐(旧值50)
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
    base_stop_loss_pct: GLOBAL_RISK.stop_loss_pct,
    base_take_profit_pct: GLOBAL_RISK.take_profit_pct,
    max_hold_days: GLOBAL_RISK.max_hold_days,
    max_position_per_stock: GLOBAL_RISK.max_position_per_stock,
    max_total_position: GLOBAL_RISK.max_total_position,
    commission_rate: GLOBAL_RISK.commission_rate,
    stamp_duty_rate: GLOBAL_RISK.stamp_duty_rate,
    slippage_pct: GLOBAL_RISK.slippage_pct,
    enable_stop_loss: true,
    enable_take_profit: true,
  },
  strategies: ['halfway_chase', 'first_limit_up', 'dragon_head', 'limit_down_qiao'],
  sweep: {
    enabled: false,
    param: 'stop_loss_pct',
    start: 0.02,
    end: 0.07,
    step: 0.01,
  },
  strategyConfigs: {
    halfway_chase: {
      enabled: STRATEGY_CONFIGS.halfway_chase.enabled, name: STRATEGY_CONFIGS.halfway_chase.name,
      params: { ...STRATEGY_CONFIGS.halfway_chase.params },
      riskParams: { ...STRATEGY_CONFIGS.halfway_chase.riskParams }
    },
    first_limit_up: {
      enabled: STRATEGY_CONFIGS.first_limit_up.enabled, name: STRATEGY_CONFIGS.first_limit_up.name,
      params: { ...STRATEGY_CONFIGS.first_limit_up.params },
      riskParams: { ...STRATEGY_CONFIGS.first_limit_up.riskParams }
    },
    limit_up_open: {
      enabled: STRATEGY_CONFIGS.limit_up_open.enabled, name: STRATEGY_CONFIGS.limit_up_open.name,
      params: { ...STRATEGY_CONFIGS.limit_up_open.params },
      riskParams: { ...STRATEGY_CONFIGS.limit_up_open.riskParams }
    },
    dragon_head: {
      enabled: STRATEGY_CONFIGS.dragon_head.enabled, name: STRATEGY_CONFIGS.dragon_head.name,
      params: { ...STRATEGY_CONFIGS.dragon_head.params },
      riskParams: { ...STRATEGY_CONFIGS.dragon_head.riskParams }
    },
    limit_down_qiao: {
      enabled: STRATEGY_CONFIGS.limit_down_qiao.enabled, name: STRATEGY_CONFIGS.limit_down_qiao.name,
      params: { ...STRATEGY_CONFIGS.limit_down_qiao.params },
      riskParams: { ...STRATEGY_CONFIGS.limit_down_qiao.riskParams }
    },
  },
})

const activeCollapse = ref<string[]>([])
const _configCollapsed = ref(false) // 备用

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

// ==================== 键盘快捷键 ====================
// 【V63修复:P2-14】Ctrl+Enter提交回测, Esc关闭弹窗
function onGlobalKeydown(e: KeyboardEvent) {
  if (e.ctrlKey && e.key === 'Enter') {
    e.preventDefault()
    if (form.sweep.enabled) submitSweepBacktest()
    else submitBacktest()
  }
}

// ==================== 生命周期 ====================

onMounted(async () => {
  // 【V63修复:P2-14】键盘快捷键: Ctrl+Enter提交回测, Esc关闭弹窗
  document.addEventListener('keydown', onGlobalKeydown)
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
      const strategyIds = ['halfway_chase', 'first_limit_up', 'limit_up_open', 'dragon_head', 'limit_down_qiao']
      for (const sid of strategyIds) {
        if (parsed[sid]) {
          const cfg = parsed[sid]
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const params = (form.strategyConfigs as any)[sid]?.params
          if (!params) continue
          if (cfg.min_pct !== undefined) params.min_rise_pct = cfg.min_pct / 100
          if (cfg.max_pct !== undefined) params.max_rise_pct = cfg.max_pct / 100
          if (cfg.min_auction_pct !== undefined) params.min_auction_pct = cfg.min_auction_pct / 100
          if (cfg.max_auction_pct !== undefined) params.max_auction_pct = cfg.max_auction_pct / 100
          if (cfg.callback_pct !== undefined) params.min_correction_pct = cfg.callback_pct / 100
          if (cfg.callback_pct_max !== undefined) params.max_correction_pct = cfg.callback_pct_max / 100
          if (cfg.min_rise_after_qiao !== undefined) params.min_rise_after_qiao = cfg.min_rise_after_qiao / 100
          Object.assign(params, cfg)
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

  // 获取回测历史数量
  try {
    const res = await fetch('/api/v1/backtest/ultra-short/history')
    if (res.ok) {
      const data = await res.json()
      historyCount.value = data.total || 0
    }
  } catch {}
})

// ==================== 任务5: 运行状态/耗时 ====================

const backtestStartTime = ref<number>(0)
const elapsedSeconds = ref(0)
let elapsedTimer: ReturnType<typeof setInterval> | null = null

const sweepResult = ref<any>(null)
const sweepLoading = ref(false)
const healthLoading = ref(false)
const healthStatus = ref<string>('')
const healthDetail = ref<any>(null)

// ==================== 方法 ====================

// ==================== 一键服务检查 ====================
const runHealthCheck = async () => {
  healthLoading.value = true; healthStatus.value = ''; healthDetail.value = null
  try {
    const res = await systemHealthCheck()
    healthDetail.value = res; healthStatus.value = res.status || 'ok'
    if (res.status === 'ok') ElMessage.success('✅ 所有服务运行正常')
    else if (res.status === 'warning') {
      const w = Object.entries(res.checks||{}).filter(([_,v]:any)=>v.status==='warning').map(([k,v]:any)=>v.message).join('; ')
      ElMessage.warning('⚠️ 部分服务异常: '+w)
    } else {
      const e2 = Object.entries(res.checks||{}).filter(([_,v]:any)=>v.status==='error').map(([k,v]:any)=>v.message).join('; ')
      ElMessage.error('❌ 服务异常: '+e2)
    }
  } catch(e:any) {
    healthStatus.value = 'error'
    ElMessage.error(e.message==='Network Error'?'❌ 后端服务未运行！请先启动服务 (restart_all.sh)':'❌ 健康检查失败: '+e.message)
  } finally { healthLoading.value = false }
}

const submitBacktest = async () => {
  if (backtestState.running) {
    ElMessage.warning('回测正在运行中')
    return
  }

  // 任务5: 开始计时
  backtestStartTime.value = Date.now()
  elapsedSeconds.value = 0
  elapsedTimer = setInterval(() => { elapsedSeconds.value = Math.floor((Date.now() - backtestStartTime.value) / 1000) }, 1000)

  backtestState.running = true
  backtestState.progress = 0
  logs.value = []
  backtestResult.value = null
  sweepResult.value = null

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
        return { id, name: cfg.name, enabled: cfg.enabled, params: { ...cfg.params }, riskParams: { ...cfg.riskParams } }
      })
    // 【P2-2修复：重命名为strategyParamsMap，避免与params字段混淆】
    const strategyParamsMap: Record<string, any> = {}
    for (const id of form.strategies) {
      if (strategyKeys.includes(id as keyof typeof form.strategyConfigs)) {
        strategyParamsMap[id] = { ...form.strategyConfigs[id as keyof typeof form.strategyConfigs].params }
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
      rebalance_freq: "daily",
      params: {
        volume_threshold: form.globalFilter.min_turnover_rate,
        stop_loss_pct: form.tradeParams.base_stop_loss_pct,
        take_profit_pct: form.tradeParams.base_take_profit_pct,
        max_hold_days: form.tradeParams.max_hold_days,
        max_position: form.tradeParams.max_total_position,
        liquidity_threshold: form.globalFilter.min_daily_amount,
        max_position_per_stock: form.tradeParams.max_position_per_stock,
        commission_rate: form.tradeParams.commission_rate ?? GLOBAL_RISK.commission_rate,
        stamp_duty_rate: form.tradeParams.stamp_duty_rate ?? GLOBAL_RISK.stamp_duty_rate,
        slippage_pct: form.tradeParams.slippage_pct ?? GLOBAL_RISK.slippage_pct,
        sentiment_cycle: form.sentimentCycle.enabled,
        auction_filter: form.auctionFilter.enabled,
        enable_stop_loss: form.tradeParams.enable_stop_loss ?? true,
        enable_take_profit: form.tradeParams.enable_take_profit ?? true,
        enable_ma60_filter: form.globalFilter.enable_ma60_filter ?? true,
        enable_sector_concentration: form.globalFilter.enable_sector_concentration ?? true,
      },
      strategy_params: strategyParamsMap,
      enable_sentiment_cycle: form.sentimentCycle.enabled,
      enable_auction_filter: form.auctionFilter.enabled,
      enable_force_empty: form.forceEmpty.enabled,
      enable_stop_loss: form.tradeParams.enable_stop_loss ?? true,
      enable_take_profit: form.tradeParams.enable_take_profit ?? true,
      enable_ma60_filter: form.globalFilter.enable_ma60_filter ?? true,
      enable_sector_concentration: form.globalFilter.enable_sector_concentration ?? true,
      exclude_st: form.globalFilter.exclude_st ?? true,
      // 【P1-3/P1-4修复】透传细粒度配置到后端
      forceEmpty: {
        enabled: form.forceEmpty.enabled,
        limit_down_count: form.forceEmpty.limit_down_count ?? 80,
        limit_up_count: form.forceEmpty.limit_up_count ?? 10,
        index_drop_pct: form.forceEmpty.index_drop_pct ?? 0.03,  // 【V65修复】0.02→0.03,与GLOBAL_RISK对齐
      },
      sentimentCycle: {
        enabled: form.sentimentCycle.enabled,
      },
      auctionFilter: {
        enabled: form.auctionFilter.enabled,
      },
      globalFilter: {
        exclude_st: form.globalFilter.exclude_st ?? true,
        exclude_delisting: form.globalFilter.exclude_delisting ?? true,
        exclude_new_stock_days: form.globalFilter.exclude_new_stock_days ?? 60,
        min_turnover_rate: form.globalFilter.min_turnover_rate ?? 1.5,
      },
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
      else if (data.type === 'result' || (data.type === 'status' && data.status === 'completed')) {
        backtestResult.value = data.result
        backtestState.running = false
        activeMainTab.value = 'result'  // 自动切换到结果Tab
        if (elapsedTimer) { clearInterval(elapsedTimer); elapsedTimer = null }
        addLog('✅ 回测全部完成！')
        ElMessage.success('回测完成！')
        ws.close()
      } else if (data.type === 'error' || (data.type === 'status' && data.status === 'failed')) {
        if (elapsedTimer) { clearInterval(elapsedTimer); elapsedTimer = null }
        addLog(`❌ 回测失败：${data.message}`)
        backtestState.running = false
        ElMessage.error(`回测失败：${data.message}`)
        ws.close()
      } else if (data.type === 'subscribed') {
        addLog('✅ WebSocket已连接，实时日志推送已开启')
      }
    }

    ws.onerror = () => {
      // 【P2-1修复：WebSocket指数退避重连，最多3次，失败后回退到轮询】
      let wsRetryCount = 0
      const maxWsRetry = 3
      const wsRetryBaseMs = 1000
      
      const tryReconnect = () => {
        if (wsRetryCount >= maxWsRetry || !backtestState.running) {
          addLog(`⚠️ WebSocket重连${wsRetryCount}次失败，回退到轮询模式`)
          const pollInterval = setInterval(async () => {
            try {
              const statusRes = await backtestApi.getBacktestStatus(backtestState.task_id)
              if (!statusRes || !statusRes.data) { return }
              const data = statusRes.data
              if (data.progress !== undefined) backtestState.progress = data.progress
              if (data.status === 'completed') {
                const resultRes = await backtestApi.getBacktestResult(backtestState.task_id)
                backtestResult.value = resultRes.data.result
                backtestState.running = false
                activeMainTab.value = 'result'  // 轮询完成也切到结果Tab
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
          return
        }
        const delay = wsRetryBaseMs * Math.pow(2, wsRetryCount)
        wsRetryCount++
        addLog(`⚠️ WebSocket断开，${delay}ms后第${wsRetryCount}次重连...`)
        setTimeout(() => {
          try {
            const newWs = new WebSocket(`${wsProtocol}//${wsHost}/ws?token=${token}`)
            newWs.onopen = () => {
              wsRetryCount = 0
              newWs.send(JSON.stringify({ type: 'subscribe', task_id: backtestState.task_id }))
              addLog('✅ WebSocket重连成功')
            }
            newWs.onmessage = ws.onmessage
            newWs.onerror = () => { tryReconnect() }
            newWs.onclose = () => { if (backtestState.running) tryReconnect() }
          } catch { tryReconnect() }
        }, delay)
      }
      tryReconnect()
    }
  } catch (e: any) {
    if (elapsedTimer) { clearInterval(elapsedTimer); elapsedTimer = null }
    // 提取后端实际错误消息，而非axios默认消息
    let errorMsg = e.message || '未知错误'
    if (e.response?.data?.detail?.message) {
      errorMsg = e.response.data.detail.message
      if (e.response.data.detail.errors?.length) {
        const details = e.response.data.detail.errors.map((err: any) => err.field_cn || err.field ? `${err.field_cn || err.field}: ${err.message}` : err.message).join('; ')
        errorMsg += ` - ${details}`
      }
    } else if (e.response?.data?.message) {
      errorMsg = e.response.data.message
    } else if (e.message === 'Network Error') {
      errorMsg = '网络连接失败，请检查后端服务是否运行'
    } else if (e.message?.includes('status code')) {
      errorMsg = `请求失败(${e.response?.status || '未知'})，请检查服务状态`
    }
    addLog(`❌ 提交回测任务失败：${errorMsg}`)
    backtestState.running = false
    ElMessage.error(`提交回测失败：${errorMsg}`)
  }
}

// ==================== 参数扫描提交 ====================

const submitSweepBacktest = async () => {
  if (backtestState.running || sweepLoading.value) {
    ElMessage.warning('回测正在运行中')
    return
  }

  sweepLoading.value = true
  sweepResult.value = null

  const strategyKeys = Object.keys(form.strategyConfigs) as (keyof typeof form.strategyConfigs)[]
  const selected_strategies = form.strategies
    .filter(id => strategyKeys.includes(id as keyof typeof form.strategyConfigs))
    .map(id => {
      const cfg = form.strategyConfigs[id as keyof typeof form.strategyConfigs]
      return { id, name: cfg.name, enabled: cfg.enabled, params: { ...cfg.params }, riskParams: { ...cfg.riskParams } }
    })
  const strategyParamsMap: Record<string, any> = {}
  for (const id of form.strategies) {
    if (strategyKeys.includes(id as keyof typeof form.strategyConfigs)) {
      strategyParamsMap[id] = { ...form.strategyConfigs[id as keyof typeof form.strategyConfigs].params }
    }
  }

  try {
    const res = await backtestApi.submitSweepBacktest({
      strategies: form.strategies,
      selected_strategies,
      start_date: form.dataSource.start_date,
      end_date: form.dataSource.end_date,
      data_source: 'mongodb',
      period: form.dataSource.period,
      ts_codes: form.dataSource.ts_codes,
      adjust_type: form.dataSource.adjust_type,
      initial_cash: form.base.initial_cash,
      rebalance_freq: 'daily',
      params: {
        volume_threshold: form.globalFilter.min_turnover_rate,
        stop_loss_pct: form.tradeParams.base_stop_loss_pct,
        take_profit_pct: form.tradeParams.base_take_profit_pct,
        max_hold_days: form.tradeParams.max_hold_days,
        max_position: form.tradeParams.max_total_position,
        liquidity_threshold: form.globalFilter.min_daily_amount,
        max_position_per_stock: form.tradeParams.max_position_per_stock,
        commission_rate: form.tradeParams.commission_rate ?? GLOBAL_RISK.commission_rate,
        stamp_duty_rate: form.tradeParams.stamp_duty_rate ?? GLOBAL_RISK.stamp_duty_rate,
        slippage_pct: form.tradeParams.slippage_pct ?? GLOBAL_RISK.slippage_pct,
        sentiment_cycle: form.sentimentCycle.enabled,
        auction_filter: form.auctionFilter.enabled,
        enable_stop_loss: form.tradeParams.enable_stop_loss ?? true,
        enable_take_profit: form.tradeParams.enable_take_profit ?? true,
        enable_ma60_filter: form.globalFilter.enable_ma60_filter ?? true,
        enable_sector_concentration: form.globalFilter.enable_sector_concentration ?? true,
      },
      strategy_params: strategyParamsMap,
      enable_force_empty: form.forceEmpty.enabled,
      enable_sentiment_cycle: form.sentimentCycle.enabled,
      enable_auction_filter: form.auctionFilter.enabled,
      enable_stop_loss: form.tradeParams.enable_stop_loss ?? true,
      enable_take_profit: form.tradeParams.enable_take_profit ?? true,
      enable_ma60_filter: form.globalFilter.enable_ma60_filter ?? true,
      enable_sector_concentration: form.globalFilter.enable_sector_concentration ?? true,
      exclude_st: form.globalFilter.exclude_st ?? true,
      forceEmpty: { enabled: form.forceEmpty.enabled, limit_down_count: form.forceEmpty.limit_down_count ?? 80, limit_up_count: form.forceEmpty.limit_up_count ?? 10, index_drop_pct: form.forceEmpty.index_drop_pct ?? 0.03 },  // 【V65修复】limit_down 50→80, index_drop_pct 0.02→0.03
      sentimentCycle: { enabled: form.sentimentCycle.enabled },
      auctionFilter: { enabled: form.auctionFilter.enabled },
      globalFilter: { exclude_st: form.globalFilter.exclude_st ?? true, exclude_delisting: form.globalFilter.exclude_delisting ?? true, exclude_new_stock_days: form.globalFilter.exclude_new_stock_days ?? 60, min_turnover_rate: form.globalFilter.min_turnover_rate ?? 1.5 },
      sweep_param: form.sweep.param,
      sweep_start: form.sweep.start,
      sweep_end: form.sweep.end,
      sweep_step: form.sweep.step,
    })
    sweepResult.value = res
    ElMessage.success('参数扫描完成！')
  } catch (e: any) {
    let errorMsg = e.response?.data?.detail?.message || e.response?.data?.message || e.message || '未知错误'
    if (e.message === 'Network Error') errorMsg = '网络连接失败，请检查后端服务是否运行'
    ElMessage.error(`参数扫描失败：${errorMsg}`)
  } finally {
    sweepLoading.value = false
  }
}

// 扫描参数选择变更时，重置范围
const currentSweepParam = computed(() => SWEEP_PARAMS.find(p => p.value === form.sweep.param))
// Note: onSweepParamChange is in StrategyConfigPanel which has direct form access

// 扫描结果折线图配置
const sweepChartOption = computed(() => {
  if (!sweepResult.value?.results?.length) return null
  const r = sweepResult.value
  const values = r.results.map((item: any) => {
    const param = SWEEP_PARAMS.find((p: any) => p.value === r.sweep_param)
    return param ? +(item.value * param.factor).toFixed(2) : item.value
  })
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['收益率(%)', '胜率(%)', '最大回撤(%)'] },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: {
      type: 'category',
      data: values,
      name: currentSweepParam.value?.label || r.sweep_param,
    },
    yAxis: [
      { type: 'value', name: '收益率(%)', axisLabel: { formatter: '{value}%' } },
      { type: 'value', name: '回撤(%)', axisLabel: { formatter: '{value}%' } },
    ],
    series: [
      {
        name: '收益率(%)', type: 'line',
        data: r.results.map((item: any) => +(item.total_return).toFixed(2)),
        lineStyle: { color: 'var(--stock-down)', width: 2 },
        itemStyle: { color: 'var(--stock-down)' },
      },
      {
        name: '胜率(%)', type: 'line',
        data: r.results.map((item: any) => +(item.win_rate).toFixed(1)),
        lineStyle: { color: 'var(--el-color-primary)', width: 2 },
        itemStyle: { color: 'var(--el-color-primary)' },
      },
      {
        name: '最大回撤(%)', type: 'line', yAxisIndex: 1,
        data: r.results.map((item: any) => +(item.max_drawdown).toFixed(2)),
        lineStyle: { color: 'var(--stock-up)', width: 2, type: 'dashed' },
        itemStyle: { color: 'var(--stock-up)' },
      },
    ],
  }
})

onUnmounted(() => {
  if (elapsedTimer) { clearInterval(elapsedTimer); elapsedTimer = null }
  document.removeEventListener('keydown', onGlobalKeydown)
})

const addLog = (text: string) => {
  // 【P3-1修复：使用requestAnimationFrame防抖，避免高频日志导致DOM频繁更新】
  const timestamp = new Date().toLocaleTimeString('zh-CN')
  const logLine = `[${timestamp}] ${text}`
  logs.value.push(logLine)
  requestAnimationFrame(() => {
    const logPanel = document.getElementById('log-panel')
    if (logPanel) logPanel.scrollTop = logPanel.scrollHeight
  })
}

// ==================== 历史回测操作 ====================

const activeMainTab = ref<'config' | 'result' | 'history' | 'data' | 'factors'>('config')
const historyCount = ref(0)

/** 从历史回测复用参数 */
function onReuseParams(task: BacktestHistoryItem) {
  if (task.start_date) form.dataSource.start_date = task.start_date
  if (task.end_date) form.dataSource.end_date = task.end_date
  if (task.initial_cash) form.base.initial_cash = task.initial_cash
  if (task.strategies && task.strategies.length > 0) {
    form.strategies = [...task.strategies]
  }
  activeMainTab.value = 'config'  // 切回配置Tab
  ElMessage.success('已复用参数到表单，修改后点击提交')
}

/** 查看历史回测结果 */
function onViewResult(task: BacktestHistoryItem) {
  backtestApi.getBacktestResult(task.task_id).then(res => {
    const result = res?.data?.result
    if (result) {
      backtestResult.value = result
      backtestState.task_id = task.task_id
      activeMainTab.value = 'result'  // 切到日志与结果Tab看结果
      ElMessage.success('已加载历史回测结果')
    } else {
      ElMessage.warning('该回测无结果数据')
    }
  }).catch(() => {
    ElMessage.error('加载结果失败')
  })
}

/** 查看历史回测日志 */
function onViewLogs(taskId: string) {
  // 切到日志与结果Tab
  activeMainTab.value = 'result'
}
</script>

<template>
  <div class="ultra-short-v2-page">
    <!-- Tab切换 + 操作按钮 -->
    <div class="main-tabs-bar">
      <div class="main-tabs">
        <button :class="['tab-btn', activeMainTab === 'config' ? 'active' : '']" @click="activeMainTab = 'config'">
          🎯 回测配置
        </button>
        <button :class="['tab-btn', activeMainTab === 'result' ? 'active' : '']" @click="activeMainTab = 'result'">
          📈 日志与结果
          <span v-if="backtestResult" class="tab-badge-success">✓</span>
          <span v-else-if="backtestState.running" class="tab-badge-running">运行中</span>
        </button>
        <button :class="['tab-btn', activeMainTab === 'history' ? 'active' : '']" @click="activeMainTab = 'history'">
          📋 回测历史
          <span class="tab-badge">{{ historyCount }}</span>
        </button>
        <button :class="['tab-btn', activeMainTab === 'data' ? 'active' : '']" @click="activeMainTab = 'data'">
          🗄️ 数据状态
        </button>
        <button :class="['tab-btn', activeMainTab === 'factors' ? 'active' : '']" @click="activeMainTab = 'factors'">
          📊 因子参考
        </button>
      </div>
      <ElButton :type="healthStatus==='ok'?'success':healthStatus==='error'?'danger':healthStatus==='warning'?'warning':'default'" :loading="healthLoading" @click="runHealthCheck" size="small">
        {{ healthLoading ? '检查中...' : healthStatus==='ok' ? '✅ 服务正常' : healthStatus==='error' ? '❌ 服务异常' : '🔧 服务检查' }}
      </ElButton>
    </div>

    <!-- Tab内容：回测配置（全屏独立标签页） -->
    <div v-show="activeMainTab === 'config'" class="tab-content-full">
      <!-- 运行状态/耗时 -->
      <div v-if="backtestState.running" class="running-status">
        ⏱ 已运行 {{ Math.floor(elapsedSeconds / 60) }}:{{ String(elapsedSeconds % 60).padStart(2, '0') }} · 回测运行中，完成后自动切换到「日志与结果」
      </div>
      <div v-if="backtestResult?.execution_time_ms" class="execution-time">
        ⏱ 上次回测耗时 {{ (backtestResult.execution_time_ms / 1000).toFixed(1) }}秒 · {{ backtestResult?.net_value_series?.length || 0 }} 交易日
        <ElButton size="small" type="primary" link @click="activeMainTab = 'result'">📈 查看结果 →</ElButton>
      </div>

      <!-- 策略配置面板 - 全屏展示 -->
      <StrategyConfigPanel
        :form="form"
        :backtestRunning="backtestState.running || sweepLoading"
        :sweepEnabled="form.sweep.enabled"
        v-model:activeCollapse="activeCollapse"
        @submit="form.sweep.enabled ? submitSweepBacktest() : submitBacktest()"
      />
    </div>

    <!-- Tab内容：日志与结果（全屏独立标签页） -->
    <div v-show="activeMainTab === 'result'" class="tab-content-full">
      <!-- 运行状态/耗时 -->
      <div v-if="backtestState.running" class="running-status">
        ⏱ 已运行 {{ Math.floor(elapsedSeconds / 60) }}:{{ String(elapsedSeconds % 60).padStart(2, '0') }} · 回测运行中...
      </div>
      <div v-if="backtestResult?.execution_time_ms" class="execution-time">
        ⏱ 回测耗时 {{ (backtestResult.execution_time_ms / 1000).toFixed(1) }}秒 · {{ backtestResult?.net_value_series?.length || 0 }} 交易日
        <ElButton size="small" type="primary" link @click="activeMainTab = 'config'">🎯 修改配置 →</ElButton>
      </div>

      <!-- 无结果时的空状态 -->
      <div v-if="!backtestState.running && !backtestResult && !backtestState.task_id" class="empty-result">
        <div class="empty-hint">
          <div class="empty-icon">📈</div>
          <div class="empty-title">暂无回测结果</div>
          <div class="empty-desc">请先在「回测配置」标签页中配置并提交回测</div>
          <ElButton type="primary" style="margin-top: 16px" @click="activeMainTab = 'config'">前往配置 →</ElButton>
        </div>
      </div>

      <!-- 参数扫描结果 -->
      <ElCard v-if="sweepResult" style="margin-bottom: 16px">
        <template #header><span>📊 参数扫描结果 - {{ currentSweepParam?.label || sweepResult.sweep_param }}</span></template>
        <VChart v-if="sweepChartOption" :option="sweepChartOption" autoresize style="height: 400px; width: 100%" />
        <ElTable v-if="sweepResult.results?.length" :data="sweepResult.results" size="small" border stripe style="margin-top: 12px">
          <ElTableColumn label="参数值" width="100">
            <template #default="{ row }">{{ currentSweepParam ? (row.value * currentSweepParam.factor).toFixed(2) + currentSweepParam.unit : row.value }}</template>
          </ElTableColumn>
          <ElTableColumn label="收益率" width="100">
            <template #default="{ row }"><span :style="{ color: row.total_return >= 0 ? 'var(--stock-down)' : 'var(--stock-up)' }">{{ row.total_return?.toFixed(2) }}%</span></template>
          </ElTableColumn>
          <ElTableColumn label="胜率" width="80">
            <template #default="{ row }">{{ row.win_rate?.toFixed(1) }}%</template>
          </ElTableColumn>
          <ElTableColumn label="最大回撤" width="100">
            <template #default="{ row }"><span style="color: var(--stock-up)">{{ row.max_drawdown?.toFixed(2) }}%</span></template>
          </ElTableColumn>
          <ElTableColumn label="夏普" width="80">
            <template #default="{ row }">{{ row.sharpe_ratio?.toFixed(2) }}</template>
          </ElTableColumn>
          <ElTableColumn prop="total_trades" label="交易数" width="80" />
        </ElTable>
      </ElCard>

      <!-- 回测结果总结表格 -->
      <BacktestSummaryTable v-if="backtestResult" :result="backtestResult" />

      <!-- 日志面板(放在结果前面，回测时更方便查看) -->
      <AnsiLogPanel v-if="backtestState.running || backtestState.task_id" :task-id="backtestState.task_id" :task-status="backtestState.running ? 'running' : 'completed'" :height="600" />

      <!-- 回测结果详细面板 -->
      <BacktestResultPanel v-if="backtestResult" :result="backtestResult" :form="form" :task-id="backtestState.task_id" :task-status="backtestState.running ? 'running' : 'completed'" />
    </div>

    <!-- Tab内容：回测历史 -->
    <div v-show="activeMainTab === 'history'" class="tab-content-full">
      <BacktestHistoryPanel
        :visible="activeMainTab === 'history'"
        @view-result="onViewResult"
        @view-logs="onViewLogs"
        @reuse-params="onReuseParams"
      />
    </div>

    <!-- Tab内容：数据状态 -->
    <div v-show="activeMainTab === 'data'" class="tab-content-full">
      <DataStatusPanel :visible="activeMainTab === 'data'" />
    </div>

    <!-- Tab内容：因子参考 -->
    <div v-show="activeMainTab === 'factors'" class="tab-content-full">
      <FactorReferencePanel />
    </div>
  </div>
</template>

<style scoped lang="scss">
.ultra-short-v2-page {
  padding: 16px;
  height: 100vh;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
  background: var(--bg-muted);
}
.main-tabs-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  border-bottom: 2px solid var(--border-default);
  flex-shrink: 0;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
  padding-bottom: 0;
  background: var(--bg-elevated);
  border-radius: 8px 8px 0 0;
  padding: 10px 16px 0;
}

.main-tabs {
  display: flex;
  gap: 0;
  flex-shrink: 0;
  flex-wrap: wrap;
  min-width: 0;

  .tab-btn {
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 600;
    border: none;
    background: transparent;
    color: var(--text-tertiary);
    cursor: pointer;
    border-bottom: 2px solid transparent;
    margin-bottom: -2px;
    transition: all 0.2s;
    position: relative;
    white-space: nowrap;
    border-radius: 6px 6px 0 0;

    &:hover { color: var(--primary-500); background: var(--bg-muted); }

    &.active {
      color: var(--primary-500);
      border-bottom-color: var(--primary-500);
      background: var(--bg-active);
    }

    .tab-badge {
      display: inline-block;
      background: var(--border-default);
      color: var(--text-tertiary);
      font-size: 11px;
      padding: 1px 6px;
      border-radius: 10px;
      margin-left: 6px;
      font-weight: 500;
    }

    &.active .tab-badge {
      background: var(--bg-active);
      color: var(--primary-500);
    }

    .tab-badge-success {
      display: inline-block;
      background: var(--stock-down-bg);
      color: var(--stock-down);
      font-size: 11px;
      padding: 1px 6px;
      border-radius: 10px;
      margin-left: 4px;
      font-weight: 600;
    }

    .tab-badge-running {
      display: inline-block;
      background: var(--warning-bg, rgba(245,158,11,0.1));
      color: var(--warning, #f59e0b);
      font-size: 10px;
      padding: 1px 6px;
      border-radius: 10px;
      margin-left: 4px;
      font-weight: 600;
      animation: pulse 1.5s infinite;
    }
  }
}

.tab-content-full {
  flex: 1;
  overflow-y: auto;
  min-width: 0;
  padding: 12px 16px;
}

.empty-result {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 400px;

  .empty-hint { text-align: center; }
  .empty-icon { font-size: 48px; margin-bottom: 16px; }
  .empty-title { font-size: 16px; font-weight: 600; margin-bottom: 8px; color: var(--text-primary); }
  .empty-desc { font-size: 13px; color: var(--text-tertiary); }
}
.running-status {
  padding: 10px 20px;
  background: linear-gradient(135deg, var(--info-bg) 0%, rgba(91,156,245,0.15) 100%);
  border-radius: 8px;
  margin-bottom: 12px;
  font-size: 14px;
  font-weight: 600;
  color: var(--el-color-primary);
  animation: pulse 2s infinite;
  display: flex;
  align-items: center;
  gap: 8px;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}
.execution-time {
  padding: 8px 20px;
  background: var(--stock-down-bg);
  border-radius: 8px;
  margin-bottom: 12px;
  font-size: 13px;
  color: var(--stock-down);
  display: flex;
  align-items: center;
  gap: 8px;
}
.tab-content-full {
  flex: 1;
  overflow-y: auto;
  min-width: 0;
  padding: 12px 16px;
}

/* Responsive: narrow screens */
@media (max-width: 1000px) {
  .ultra-short-v2-page { padding: 8px; }
}


</style>
