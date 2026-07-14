/**
 * useReviewMonitor - 复盘数据域
 * 
 * 从useScannerMonitor拆出的复盘相关逻辑
 * 管理: reviewTab/reviewData/日报/周报/月报/偏差归因/参数漂移
 */

import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '@/api/client'
import { parseResponse } from '@/utils/scanner'

const scannerApi = '/scanner'

/** 获取中国时区的日期字符串 YYYY-MM-DD */
function getChinaDate(): string {
  const now = new Date()
  const china = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Shanghai' }))
  const y = china.getFullYear()
  const m = String(china.getMonth() + 1).padStart(2, '0')
  const d = String(china.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

export function useReviewMonitor() {
  // ==================== 复盘状态 ====================
  const reviewTab = ref<'daily' | 'weekly' | 'monthly'>('daily')
  const reviewLoading = ref(false)
  const reviewDate = ref(getChinaDate())
  const reviewHero = ref<any>(null)
  const reviewForward = ref<any>(null)
  const dailyReportData = ref<any>(null)
  const weeklyReviewData = ref<any>({})
  const weeklyReportRaw = ref<any>(null)
  const weeklyReportData = computed(() => weeklyReportRaw.value)
  const monthlyReviewData = ref<any>({})
  const deviationData = ref<any>(null)
  const closedLoopData = ref<any>(null)
  const tradeAttributions = ref<any[]>([])
  const paramDriftData = ref<any>(null)
  const factorEffectData = ref<any>(null)
  const disciplineCheck = ref<any>(null)
  const liveBacktestDiff = ref<any[]>([])
  const executionQuality = ref<any>(null)
  const backtestRunning = ref(false)

  function buildTradeAttributions(trades: any[]) {
    const sells = (trades || []).filter((t: any) => t.side === 'sell')
    const buys = (trades || []).filter((t: any) => t.side === 'buy')
    if (sells.length) {
      return sells.map((s: any) => {
        const buy = buys.find((b: any) => b.ts_code === s.ts_code && b.strategy === s.strategy)
        return { status: 'closed', ts_code: s.ts_code, stock_name: s.stock_name, strategy: s.strategy, buy_price: buy?.price || 0, sell_price: s.price, profit_pct: s.profit_pct, profit_amount: s.profit_amount, sell_reason: s.reason, sell_time: s.time, buy_time: buy?.time || '', why_profit: s.why, why_loss: s.why }
      })
    }
    // 当天只有买入没有卖出时，也要展示“建仓中”明细，否则日复盘看起来像空数据
    return buys.map((b: any) => ({
      status: 'open', ts_code: b.ts_code, stock_name: b.stock_name, strategy: b.strategy,
      buy_price: b.price, buy_time: b.time, quantity: b.quantity, amount: b.amount,
      sell_price: null, sell_time: '', profit_pct: null, profit_amount: null,
      sell_reason: b.reason || '今日买入，持仓未闭环', why_profit: '', why_loss: '',
    }))
  }

  // ==================== 复盘API ====================
  async function fetchReviewData() {
    reviewLoading.value = true
    try {
      const promises: Promise<any>[] = []
      const opts = { timeout: 60000 }
      const today = getChinaDate()
      const dateParam = reviewDate.value.replace(/-/g, '')
      const isToday = reviewDate.value === today

      // ===== 共享数据(所有Tab共用,不重复请求) =====
      promises.push(
        api.get(`${scannerApi}/backtest-compare?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) liveBacktestDiff.value = p.data || [] }),
        api.get(`${scannerApi}/review-hero?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) reviewHero.value = p.data }),
        api.get(`${scannerApi}/discipline-check?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) disciplineCheck.value = p.data }),
        api.get(`${scannerApi}/deviation-attribution?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) deviationData.value = p.data }),
        api.get(`${scannerApi}/review-forward?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) reviewForward.value = p.data }),
      )

      // ===== 按周期差异化(仅周期特有数据) =====
      if (reviewTab.value === 'daily') {
        if (isToday) {
          promises.push(
            api.get(`${scannerApi}/daily-report?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) dailyReportData.value = p.data }),
            // 【v2.9.97】切换到统一数据源 — 包含 buy+sell
            api.get(`/unified/trades?date=${dateParam}`, opts).then(r => {
              const p = parseResponse(r); if (p.success) {
                tradeAttributions.value = buildTradeAttributions(p.data?.trades || [])
              }
            }),
          )
        } else {
          promises.push(
            api.get(`${scannerApi}/historical-review?date=${dateParam}`, opts).then(r => {
              const p = parseResponse(r)
              if (p.success && p.data) {
                const d = p.data
                dailyReportData.value = {
                  date: reviewDate.value,
                  account: { today_profit: 0, position_ratio: 0, available_cash: 0 },
                  positions: { count: 0, strategy_summary: d.strategy_summary, top_profit: [], top_loss: [] },
                  trades: { buy: d.scan_stats?.buy_count || 0, sell: d.scan_stats?.sell_count || 0, total_amount: 0 },
                  win_rate: Object.values(d.strategy_summary || {}).reduce((s: number, v: any) => s + v.win_count, 0) / Math.max(Object.values(d.strategy_summary || {}).reduce((s: number, v: any) => s + (v.win_count || 0) + (v.loss_count || 0), 0), 1) * 100,
                  stop_loss_count: Object.values(d.strategy_summary || {}).reduce((s: number, v: any) => s + (v.stop_loss_count || 0), 0),
                  take_profit_count: Object.values(d.strategy_summary || {}).reduce((s: number, v: any) => s + (v.take_profit_count || 0), 0),
                  scanner_stats: d.scan_stats, funnel_summary: d.funnel_summary, sentiment_snapshot: d.sentiment_snapshot,
                }
              }
            }),
            // 【v2.9.97】历史日复盘也走统一数据源
            api.get(`/unified/trades?date=${dateParam}`, opts).then(r => {
              const p = parseResponse(r); if (p.success) {
                tradeAttributions.value = buildTradeAttributions(p.data?.trades || [])
              }
            }),
          )
        }
        promises.push(
          api.get(`${scannerApi}/execution-quality?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) executionQuality.value = p.data }),
        )
      } else if (reviewTab.value === 'weekly') {
        promises.push(
          api.get(`${scannerApi}/review-weekly?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) weeklyReviewData.value = p.data }),
          api.get(`${scannerApi}/weekly-report?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) weeklyReportRaw.value = p.data }),
        )
      } else if (reviewTab.value === 'monthly') {
        promises.push(
          api.get(`${scannerApi}/review-monthly?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) monthlyReviewData.value = p.data }),
          api.get(`${scannerApi}/param-drift`, opts).then(r => { const p = parseResponse(r); if (p.success) paramDriftData.value = p.data }),
          api.get(`${scannerApi}/factor-effectiveness?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) factorEffectData.value = p.data }),
          api.get(`${scannerApi}/review-closed-loop?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) closedLoopData.value = p.data }),
        )
      }

      await Promise.allSettled(promises)
      // 后端review-hero按“卖出闭环”统计，盘中只有买入时会显示0笔；前端用统一交易数据兜底修正展示
      if (reviewTab.value === 'daily' && reviewHero.value && tradeAttributions.value.length) {
        const openBuys = tradeAttributions.value.filter((t: any) => t.status === 'open').length
        if (openBuys && !(reviewHero.value.metrics?.closed_trades || 0)) {
          reviewHero.value = {
            ...reviewHero.value,
            conclusion: `📋 今日买入${openBuys}笔，暂无卖出闭环`,
            metrics: { ...(reviewHero.value.metrics || {}), trades: tradeAttributions.value.length, buys: openBuys },
          }
        }
      }
    } catch (e) { console.error('[useReviewMonitor]', e) }
    finally { reviewLoading.value = false }
  }

  async function runBacktest() {
    backtestRunning.value = true
    try {
      const r = await api.post(`${scannerApi}/run-backtest`, {})
      const p = parseResponse(r)
      if (p.success) ElMessage.success('回测已启动')
      else ElMessage.error(String(p.data?.message || '启动失败'))
    } catch (e: any) { console.error('[useReviewMonitor] runBacktest failed:', e); ElMessage.error('回测启动失败') }
    finally { backtestRunning.value = false }
  }

  async function runSamePeriodBacktest() {
    try {
      const r = await api.post(`${scannerApi}/backtest-same-period`, {})
      const p = parseResponse(r)
      if (p.success) ElMessage.success('同区间回测已启动')
    } catch (e: any) { console.error('[useReviewMonitor] runSamePeriodBacktest failed:', e); ElMessage.error('回测启动失败') }
  }

  async function saveParamSnapshot() {
    try {
      const r = await api.get(`${scannerApi}/param-snapshot`)
      const p = parseResponse(r)
      if (p.success) ElMessage.success('参数快照已保存')
    } catch (e) { console.error('[review] saveParamsSnapshot failed:', e); ElMessage.error('保存失败') }
  }

  async function saveSnapshot() {
    try {
      await api.post(`${scannerApi}/snapshot`)
      ElMessage.success('快照已保存')
    } catch (e) { console.error('[useReviewMonitor]', e) }
  }

  // openWeeklyReport 和 exportTradeLog 由 useScannerMonitor 统一实现
  const openWeeklyReport = () => { /* 由useScannerMonitor实现 */ }
  const exportTradeLog = () => { /* 由useScannerMonitor实现 */ }

  return {
    // 状态
    reviewTab, reviewLoading, reviewDate, reviewHero, reviewForward,
    dailyReportData, weeklyReviewData, weeklyReportData, monthlyReviewData,
    deviationData, closedLoopData, tradeAttributions,
    paramDriftData, factorEffectData, disciplineCheck,
    liveBacktestDiff, executionQuality, backtestRunning,
    // 方法
    fetchReviewData, runBacktest, runSamePeriodBacktest,
    saveParamSnapshot, saveSnapshot, openWeeklyReport, exportTradeLog,
  }
}
