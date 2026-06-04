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

export function useReviewMonitor() {
  // ==================== 复盘状态 ====================
  const reviewTab = ref<'daily' | 'weekly' | 'monthly'>('daily')
  const reviewLoading = ref(false)
  const reviewDate = ref(new Date().toISOString().slice(0, 10))
  const reviewHero = ref<any>(null)
  const reviewForward = ref<any>(null)
  const dailyReportData = ref<any>(null)
  const weeklyReviewData = ref<any>({})
  const weeklyReportData = computed(() => weeklyReviewData.value)
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

  // ==================== 复盘API ====================
  async function fetchReviewData() {
    reviewLoading.value = true
    try {
      const promises: Promise<any>[] = []
      const opts = { timeout: 60000 }
      const today = new Date().toISOString().slice(0, 10)
      const dateParam = reviewDate.value.replace(/-/g, '')
      const isToday = reviewDate.value === today

      // ===== 通用数据 =====
      promises.push(
        api.get(`${scannerApi}/backtest-compare?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) liveBacktestDiff.value = p.data || [] }),
        api.get(`${scannerApi}/review-hero?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) reviewHero.value = p.data }),
      )

      // ===== 按周期差异化 =====
      if (reviewTab.value === 'daily') {
        if (isToday) {
          promises.push(
            api.get(`${scannerApi}/daily-report`, opts).then(r => { const p = parseResponse(r); if (p.success) dailyReportData.value = p.data }),
            api.get(`${scannerApi}/trade-attribution?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) tradeAttributions.value = p.data || [] }),
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
            api.get(`${scannerApi}/trade-attribution?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) tradeAttributions.value = p.data || [] }),
          )
        }
        promises.push(
          api.get(`${scannerApi}/discipline-check?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) disciplineCheck.value = p.data }),
          api.get(`${scannerApi}/deviation-attribution?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) deviationData.value = p.data }),
          api.get(`${scannerApi}/review-forward?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) reviewForward.value = p.data }),
          // 执行质量: 从偏差归因数据中提取滑点信息
          api.get(`${scannerApi}/deviation-attribution?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success && p.data?.deviations?.slippage) executionQuality.value = { avg_slippage_pct: p.data.deviations.slippage.avg_pct || 0, max_slippage_pct: p.data.deviations.slippage.max_pct || 0, fill_rate_pct: p.data.deviations.slippage.fill_rate || 95, total_orders: p.data.live_stats?.trades || 0, filled_orders: p.data.live_stats?.wins || 0 } }),
        )
      } else if (reviewTab.value === 'weekly') {
        promises.push(
          api.get(`${scannerApi}/review-weekly?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) weeklyReviewData.value = p.data }),
          api.get(`${scannerApi}/deviation-attribution?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) deviationData.value = p.data }),
          api.get(`${scannerApi}/discipline-check?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) disciplineCheck.value = p.data }),
          api.get(`${scannerApi}/review-forward?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) reviewForward.value = p.data }),
        )
      } else if (reviewTab.value === 'monthly') {
        promises.push(
          api.get(`${scannerApi}/review-monthly?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) monthlyReviewData.value = p.data }),
          api.get(`${scannerApi}/param-drift`, opts).then(r => { const p = parseResponse(r); if (p.success) paramDriftData.value = p.data }),
          api.get(`${scannerApi}/factor-effectiveness?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) factorEffectData.value = p.data }),
          api.get(`${scannerApi}/review-closed-loop?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) closedLoopData.value = p.data }),
          api.get(`${scannerApi}/review-forward?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) reviewForward.value = p.data }),
          api.get(`${scannerApi}/discipline-check?date=${dateParam}`, opts).then(r => { const p = parseResponse(r); if (p.success) disciplineCheck.value = p.data }),
        )
      }

      await Promise.allSettled(promises)
    } catch { /* ignore */ }
    finally { reviewLoading.value = false }
  }

  async function runBacktest() {
    try {
      const r = await api.post(`${scannerApi}/run-backtest`, {})
      const p = parseResponse(r)
      if (p.success) ElMessage.success('回测已启动')
      else ElMessage.error(String(p.data?.message || '启动失败'))
    } catch (e: any) { ElMessage.error('回测启动失败') }
  }

  async function runSamePeriodBacktest() {
    try {
      const r = await api.post(`${scannerApi}/backtest-same-period`, {})
      const p = parseResponse(r)
      if (p.success) ElMessage.success('同区间回测已启动')
    } catch (e: any) { ElMessage.error('回测启动失败') }
  }

  async function saveParamSnapshot() {
    try {
      const r = await api.get(`${scannerApi}/param-snapshot`)
      const p = parseResponse(r)
      if (p.success) ElMessage.success('参数快照已保存')
    } catch { ElMessage.error('保存失败') }
  }

  async function saveSnapshot() {
    try {
      await api.post(`${scannerApi}/snapshot`)
      ElMessage.success('快照已保存')
    } catch { /* ignore */ }
  }

  function openWeeklyReport() { /* stub: 后续实现 */ }
  function exportTradeLog() { /* stub: 后续实现 */ }

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
