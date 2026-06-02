/**
 * useReviewMonitor - 复盘数据域
 * 
 * 从useScannerMonitor拆出的复盘相关逻辑
 * 管理: reviewTab/reviewData/日报/回测/参数快照
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
  const reviewData = ref<any>({})
  const reviewHeroData = ref<any>(null)
  const disciplineData = ref<any>(null)
  const reviewForwardData = ref<any>(null)
  const closedLoopData = ref<any>(null)
  const dailyReportData = ref<any>(null)
  const weeklyReviewData = ref<any>({})
  const weeklyReportData = computed(() => weeklyReviewData.value)
  const monthlyReviewData = ref<any>({})
  const deviationData = ref<any>(null)

  // 复盘辅助(后续逐步实现)
  const reviewDate = ref('')
  const reviewHero = ref<any>(null)
  const reviewForward = ref<any>(null)
  const backtestRunning = ref(false)
  const liveBacktestDiff = ref<any>(null)
  const executionQuality = ref<any>(null)
  const tradeAttributions = ref<any[]>([])
  const paramDriftData = ref<any>(null)
  const factorEffectData = ref<any>(null)
  const disciplineCheck = ref<any>(null)

  // ==================== 复盘API ====================
  async function fetchReviewData() {
    reviewLoading.value = true
    try {
      const dateParam = ''
      await Promise.allSettled([
        api.get(`${scannerApi}/review-hero`),
        api.get(`${scannerApi}/daily-report`),
        api.get(`${scannerApi}/review-closed-loop?date=${dateParam}`),
      ])
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
    reviewTab, reviewLoading, reviewData, reviewHeroData, disciplineData,
    reviewForwardData, closedLoopData, dailyReportData,
    weeklyReviewData, weeklyReportData, monthlyReviewData, deviationData,
    reviewDate, reviewHero, reviewForward, backtestRunning,
    liveBacktestDiff, executionQuality, tradeAttributions,
    paramDriftData, factorEffectData, disciplineCheck,
    // 方法
    fetchReviewData, runBacktest, runSamePeriodBacktest,
    saveParamSnapshot, saveSnapshot, openWeeklyReport, exportTradeLog,
  }
}
