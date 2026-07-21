/**
 * scoreCalc - 策略感知综合评分
 * 数据驱动: 106笔半路追涨实盘验证, AUC 0.673
 */
import { ref } from 'vue'
import { api } from '@/api/client'
import { parseResponse } from '@/utils/scanner'

const BASE = '/scanner'

// 策略参数: 从后端动态获取
const strategyParams = ref<Record<string, any>>({})

export async function fetchStrategyParams() {
  try {
    const strategies = ['halfway_chase', 'first_limit_up', 'dragon_head', 'limit_down_qiao', 'limit_up_open']
    const results: Record<string, any> = {}
    await Promise.all(strategies.map(async (sid) => {
      try {
        const resp = await api.get(`${BASE}/params/${sid}`)
        const data = parseResponse(resp) as any
        if (data?.params) results[sid] = data.params
      } catch (e) { console.warn('[scoreCalc] fetchStrategyParams single failed:', sid, e) }
    }))
    strategyParams.value = results
  } catch (e) { console.error('[scoreCalc] fetchStrategyParams failed:', e) }
}

/** 综合评分路由 */
export function calcCompositeScore(factors: Record<string, any>, strategy: string, status: string): number {
  if (!factors || !Object.keys(factors).length) return 0
  switch (strategy) {
    case 'halfway_chase': return calcHalfwayChase(factors, status)
    case 'first_limit_up': return calcFirstLimitUp(factors, status)
    case 'dragon_head': return calcDragonHead(factors, status)
    case 'limit_down_qiao': return calcLimitDownQiao(factors, status)
    case 'limit_up_open': return calcLimitUpOpen(factors, status)
    default: return calcGeneric(factors, status)
  }
}

/** 半路追涨: 开盘位置(25)+量比(20)+涨幅(15)+换手(15)+MA5(15)+市值(5)+恐贪(5) */
function calcHalfwayChase(f: Record<string, any>, status: string): number {
  let s = 0
  const p = strategyParams.value.halfway_chase || {}
  const minRise = (p.min_rise_pct ?? 0.03) * 100
  const maxRise = (p.max_rise_pct ?? 0.07) * 100
  const minVr = p.min_volume_ratio ?? 1.5
  const maxVr = p.max_volume_ratio ?? 3.0

  // 1. 开盘位置(25分)
  const openRise = f.opening_pct_chg || f.open_rise_pct || f.open_pct || 0
  if (openRise >= -1 && openRise <= 1) s += 25
  else if (openRise > 1 && openRise <= 2) s += 15
  else if (openRise > 2) s -= 10
  else s += 15

  // 2. 量比(20分)
  const vr = f.volume_ratio || 0
  if (vr >= minVr && vr <= 2.5) s += 20
  else if (vr > 2.5 && vr <= maxVr) s += 12
  else if (vr > maxVr && vr <= 5) s += 5
  else if (vr > 5 && vr <= 10) s -= 5
  else if (vr > 10) s -= 10
  else s += 3

  // 3. 涨幅(15分)
  const pct = f.pct_chg || 0
  if (pct >= minRise && pct < (minRise + maxRise) / 2) s += 15
  else if (pct >= (minRise + maxRise) / 2 && pct <= maxRise) s += 8
  else if (pct > maxRise && pct <= maxRise + 2) s -= 5
  else if (pct > maxRise + 2) s -= 15
  else s += 5

  // 4. 换手率(15分)
  const tr = f.turnover_rate || 0
  if (tr >= 2 && tr <= 5) s += 15
  else if (tr >= 1 && tr < 2) s += 10
  else if (tr >= 0.5 && tr < 1) s += 5
  else if (tr > 5 && tr <= 10) s -= 10
  else if (tr > 10) s += 0
  else s += 3

  // 5. MA5偏离(15分)
  const pbPct = (f.pullback_pct || 0) * 100
  if (pbPct > 0 && pbPct <= 1) s += 15
  else if (pbPct > 1 && pbPct <= 3) s += 10
  else if (pbPct >= -1 && pbPct <= 0) s += 8
  else if (pbPct >= -3 && pbPct < -1) s += 3
  else if (pbPct >= -5 && pbPct < -3) s -= 5
  else if (pbPct < -5) s -= 10

  // 6. 流通市值(5分)
  const mv = (f.circ_mv || 0) / 10000
  if (mv >= 20 && mv <= 200) s += 5
  else if (mv >= 200 && mv <= 500) s += 3
  else s += 1

  // 7. 恐贪指数(5分)
  const fgi = f.fear_greed_index
  if (fgi != null && fgi > 0) {
    if (fgi < 3) s += 5
    else if (fgi >= 3 && fgi < 5) s += 2
    else if (fgi >= 5 && fgi < 7) s += 3
    else s += 1
  }

  if (status === 'bought') s += 20
  return Math.max(0, Math.min(100, s))
}

/** 首板打板: 涨幅(30)+换手(20)+市值(20)+量比(15)+开盘位置(15) */
function calcFirstLimitUp(f: Record<string, any>, status: string): number {
  let s = 0
  const p = strategyParams.value.first_limit_up || {}
  const minVr = p.min_volume_ratio ?? 1.5
  const minTr = p.min_turnover_rate ?? 3
  const minMv = p.min_circulation_market_cap ?? 10
  const maxMv = p.max_circulation_market_cap ?? 500
  const openMin = p.opening_pct_min ?? -1
  const openMax = p.opening_pct_max ?? 5

  const pct = f.pct_chg || 0
  if (pct >= 9.5) s += 30; else if (pct >= 7) s += 20; else if (pct >= 5) s += 12; else s += 5

  const tr = f.turnover_rate || 0
  if (tr >= minTr && tr <= minTr + 15) s += 20
  else if (tr >= minTr) s += 12
  else s += 3

  const mv = (f.circ_mv || 0) / 10000
  if (mv >= Math.max(minMv, 50) && mv <= Math.min(maxMv, 300)) s += 20
  else if (mv >= minMv) s += 12
  else s += 5

  const vr = f.volume_ratio || 0
  if (vr >= minVr && vr <= 5) s += 15; else if (vr >= 1) s += 8; else s += 3

  const openPct = f.opening_pct_chg || f.open_rise_pct || f.open_pct || 0
  if (openPct >= openMin && openPct <= openMax * 0.6) s += 15
  else if (openPct <= openMax) s += 10
  else s += 3

  if (status === 'bought') s += 20
  return Math.max(0, Math.min(100, s))
}

/** 龙头低吸: 回调(25)+缩量(25)+连板(20)+市值(15)+支撑(15) */
function calcDragonHead(f: Record<string, any>, status: string): number {
  let s = 0
  const p = strategyParams.value.dragon_head || {}
  const minCorrection = (p.min_correction_pct ?? 0.05) * 100
  const maxCorrection = (p.max_correction_pct ?? 0.22) * 100
  const minVr = p.min_volume_ratio ?? 0.5
  const maxVr = p.max_volume_ratio ?? 2.0
  const minMv = p.min_circulation_market_cap ?? 30

  const correction = Math.abs(f.pct_chg || 0)
  if (correction >= minCorrection && correction <= minCorrection + 5) s += 25
  else if (correction > minCorrection + 5 && correction <= maxCorrection * 0.7) s += 20
  else if (correction > maxCorrection * 0.7 && correction <= maxCorrection) s += 10
  else s += 5

  const vr = f.volume_ratio || 0
  if (vr >= minVr && vr <= (minVr + maxVr) / 2) s += 25
  else if (vr >= minVr && vr <= maxVr) s += 15
  else if (vr > maxVr) s += 3
  else s += 5

  const limitDays = f.limit_up_days || f.consecutive_limit || 1
  if (limitDays >= 3) s += 20; else if (limitDays >= 2) s += 15; else s += 8

  const mv = (f.circ_mv || 0) / 10000
  if (mv >= minMv && mv <= 300) s += 15; else if (mv >= minMv) s += 10; else s += 5

  const pb = f.pullback_pct || 0
  if (pb >= -0.03 && pb <= 0) s += 15; else if (pb > 0 && pb <= 0.02) s += 10; else s += 3

  if (status === 'bought') s += 20
  return Math.max(0, Math.min(100, s))
}

/** 跌停翘板: 翘板(30)+换手(25)+市值(20)+连跌(15)+量比(10) */
function calcLimitDownQiao(f: Record<string, any>, status: string): number {
  let s = 0
  const p = strategyParams.value.limit_down_qiao || {}
  const minTr = p.min_turnover_rate ?? 10
  const minMv = p.min_circulation_market_cap ?? 20
  const minQiaoRise = (p.min_rise_after_qiao ?? 0.03) * 100
  const minLimitDown = p.min_consecutive_limit ?? 2

  const pct = f.pct_chg || 0
  if (pct >= minQiaoRise && pct <= minQiaoRise + 2) s += 30
  else if (pct > minQiaoRise + 2) s += 20
  else if (pct >= 0) s += 10
  else s += 0

  const tr = f.turnover_rate || 0
  if (tr >= minTr && tr <= minTr + 10) s += 25
  else if (tr > minTr + 10) s += 15
  else s += 3

  const mv = (f.circ_mv || 0) / 10000
  if (mv >= minMv && mv <= 200) s += 20; else if (mv >= minMv) s += 12; else s += 5

  const limitDownDays = f.limit_down_days || f.consecutive_limit_down || 1
  if (limitDownDays === minLimitDown) s += 15
  else if (limitDownDays >= minLimitDown + 1) s += 5
  else s += 8

  const vr = f.volume_ratio || 0
  if (vr >= 3) s += 15; else if (vr >= 2) s += 10; else s += 3

  if (status === 'bought') s += 20
  return Math.max(0, Math.min(100, s))
}

/** 涨停开板: 连板(25)+量比(25)+换手(20)+市值(15)+涨幅(15) */
function calcLimitUpOpen(f: Record<string, any>, status: string): number {
  let s = 0
  const p = strategyParams.value.limit_up_open || {}
  const minVr = p.min_volume_ratio ?? 2.0
  const minTr = p.min_turnover_rate ?? 15

  const pct = f.pct_chg || 0
  if (pct >= 8) s += 25; else if (pct >= 5) s += 15; else s += 5
  const vr = f.volume_ratio || 0
  if (vr >= minVr && vr <= 5) s += 25; else if (vr >= minVr * 0.75) s += 15; else s += 5
  const tr = f.turnover_rate || 0
  if (tr >= minTr && tr <= minTr + 15) s += 20; else if (tr >= minTr * 0.7) s += 12; else s += 5
  const mv = (f.circ_mv || 0) / 10000
  if (mv >= 50 && mv <= 300) s += 15; else if (mv >= 20) s += 10; else s += 5
  if (status === 'bought') s += 20
  return Math.max(0, Math.min(100, s))
}

/** 通用评分: anomaly等观察信号 */
function calcGeneric(f: Record<string, any>, status: string): number {
  let s = 0
  const pct = f.pct_chg || 0
  if (pct >= 4 && pct <= 7) s += 30; else if (pct >= 2) s += 15; else if (pct > 7) s += 10; else s += 5
  const vr = f.volume_ratio || 0
  if (vr >= 1.5 && vr <= 5) s += 25; else if (vr >= 1) s += 10; else s += 3
  const tr = f.turnover_rate || 0
  if (tr >= 1 && tr <= 5) s += 15; else if (tr > 5 && tr <= 10) s += 8; else s += 3
  const mv = (f.circ_mv || 0) / 10000
  if (mv >= 30 && mv <= 200) s += 15; else s += 5
  if (status === 'bought') s += 20
  return Math.max(0, Math.min(100, s))
}
