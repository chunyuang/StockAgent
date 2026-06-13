<script setup lang="ts">
import { ref, computed, onMounted, inject } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { PieChart } from 'echarts/charts'
import { TooltipComponent, LegendComponent } from 'echarts/components'
import { useChartColors } from './useChartColors'

use([CanvasRenderer, PieChart, TooltipComponent, LegendComponent])
import { SCANNER_MONITOR_KEY, type ScannerMonitorData } from './scannerMonitorInject'

const c = useChartColors().value
const loading = ref(false)
const accountData = ref<any>(null)
const activeSection = ref('overview')

const monitorData = inject(SCANNER_MONITOR_KEY, null)
const setActiveTab = (tab: string) => {
  if (monitorData?.activeTab) {
    monitorData.activeTab.value = tab
  }
}

const fetchAccount = async () => {
  loading.value = true
  try {
    const [analysisRes] = await Promise.all([
      fetch('/api/v1/scanner/analysis?period=30d').then(r => r.json()),
    ])
    accountData.value = { analysis: analysisRes.data || {} }
  } catch (e) { console.error(e) }
  loading.value = false
}

onMounted(fetchAccount)

const acc = computed(() => accountData.value?.analysis?.account || {})
const riskMonitor = computed(() => accountData.value?.analysis?.risk_monitor || {})
const positions = computed(() => (accountData.value?.analysis?.positions || []).slice().sort((a: any, b: any) => (a.profit_pct || 0) - (b.profit_pct || 0)))
const totalAssets = computed(() => acc.value.total_assets || 0)
const availableCash = computed(() => acc.value.available_cash || 0)
const marketValue = computed(() => acc.value.market_value || positions.value.reduce((s: number, p: any) => s + (p.market_value || 0), 0))
const totalProfit = computed(() => totalAssets.value - 1000000)
const positionRatio = computed(() => totalAssets.value > 0 ? marketValue.value / totalAssets.value * 100 : 0)
const brokenSL = computed(() => positions.value.filter((p: any) => p.stop_loss_status === 'broken'))
const nearSL = computed(() => positions.value.filter((p: any) => p.stop_loss_status === 'near'))

const fmt = (v: number) => `¥${(v/10000).toFixed(2)}万`
const cls = (v: number) => v >= 0 ? 'up' : 'down'

const realizedPnl = computed(() => {
  const positions_pnl = positions.value.reduce((s: number, p: any) => s + (p.profit_amount || 0), 0)
  return totalProfit.value - positions_pnl
})

// Pie chart
const posPie = computed(() => {
  const pos = positions.value
  if (!pos.length) return null
  const up = pos.filter((p: any) => p.profit_pct >= 0)
  const down = pos.filter((p: any) => p.profit_pct < 0)
  return {
    tooltip: { trigger: 'item', formatter: '{b}: ¥{c} ({d}%)' },
    legend: { bottom: 0, textStyle: { fontSize: 11, color: '#999' } },
    series: [{
      type: 'pie', radius: ['35%', '65%'], center: ['50%', '45%'],
      label: { formatter: '{b}\n{d}%', fontSize: 10, color: '#999' },
      data: [
        ...(up.length ? [{ value: Math.round(up.reduce((s: number, p: any) => s + p.market_value, 0)), name: '盈利持仓', itemStyle: { color: c.stockDown } }] : []),
        ...(down.length ? [{ value: Math.round(down.reduce((s: number, p: any) => s + p.market_value, 0)), name: '亏损持仓', itemStyle: { color: c.stockUp } }] : []),
        { value: Math.round(availableCash.value), name: '可用现金', itemStyle: { color: '#909399' } },
      ]
    }]
  }
})
</script>

<template>
  <div class="at" v-loading="loading">
    <!-- Risk Alert -->
    <div v-if="riskMonitor.status && riskMonitor.status !== 'healthy'" class="at-alert">
      ⚠️ {{ riskMonitor.desc }}
      <span v-if="brokenSL.length"> | 🔴 {{ brokenSL.length }}只破止损</span>
    </div>

    <!-- KPI -->
    <div class="at-kpi">
      <div class="at-kpi-c"><div class="at-kpi-l">总资产</div><div class="at-kpi-v">{{ fmt(totalAssets) }}</div></div>
      <div class="at-kpi-c"><div class="at-kpi-l">可用现金</div><div class="at-kpi-v">{{ fmt(availableCash) }}</div></div>
      <div class="at-kpi-c"><div class="at-kpi-l">持仓市值</div><div class="at-kpi-v">{{ fmt(marketValue) }}</div></div>
      <div class="at-kpi-c"><div class="at-kpi-l">总盈亏</div><div :class="['at-kpi-v', cls(totalProfit)]">{{ totalProfit >= 0 ? '+' : '' }}{{ fmt(totalProfit) }}</div></div>
      <div class="at-kpi-c"><div class="at-kpi-l">仓位</div><div class="at-kpi-v">{{ positionRatio.toFixed(1) }}%</div></div>
      <div class="at-kpi-c"><div class="at-kpi-l">持仓</div><div class="at-kpi-v">{{ positions.length }}只<el-badge v-if="brokenSL.length" :value="brokenSL.length" type="danger" style="margin-left:4px" /></div></div>
    </div>

    <!-- Section Nav -->
    <div class="at-nav">
      <button :class="['at-nav-b', activeSection === 'overview' && 'on']" @click="activeSection = 'overview'">📊 资产分布</button>
      <button :class="['at-nav-b', activeSection === 'positions' && 'on']" @click="activeSection = 'positions'">💼 持仓明细</button>
      <button :class="['at-nav-b', activeSection === 'risk' && 'on']" @click="activeSection = 'risk'">🛡️ 风控状态</button>
    </div>

    <!-- ===== Overview ===== -->
    <div v-show="activeSection === 'overview'" class="at-sec">
      <!-- Row 1: Pie + Summary -->
      <div class="at-row2">
        <div class="at-card">
          <div class="at-card-t">📊 资产分布</div>
          <VChart v-if="posPie" :option="posPie" autoresize style="height:260px;width:100%" />
          <div v-else class="at-empty">空仓</div>
        </div>
        <div class="at-card">
          <div class="at-card-t">📋 盈亏构成</div>
          <div class="at-scroll">
            <div class="at-eq-row at-eq-head"><span>项目</span><span>金额</span></div>
            <div class="at-eq-row"><span>初始资金</span><span>¥100.00万</span></div>
            <div class="at-eq-row"><span>已实现盈亏</span><span :class="cls(realizedPnl)">{{ realizedPnl >= 0 ? '+' : '' }}¥{{ (realizedPnl / 10000).toFixed(2) }}万</span></div>
            <div class="at-eq-row at-eq-sep"><span style="font-size:11px;color:var(--text-tertiary)">── 未实现盈亏 ──</span><span></span></div>
            <div v-for="p in positions" :key="p.ts_code" class="at-eq-row">
              <span class="at-eq-name">{{ p.stock_name || p.ts_code?.slice(0,6) }}</span>
              <span :class="cls(p.profit_amount || 0)">{{ (p.profit_amount || 0) >= 0 ? '+' : '' }}¥{{ ((p.profit_amount || 0) / 10000).toFixed(2) }}万</span>
            </div>
            <div class="at-eq-row at-eq-total"><span>当前总资产</span><span>¥{{ (totalAssets / 10000).toFixed(2) }}万</span></div>
          </div>
        </div>
      </div>
    </div>

    <!-- ===== Positions ===== -->
    <div v-show="activeSection === 'positions'" class="at-sec">
      <div v-if="!positions.length" class="at-empty">空仓</div>
      <div v-else class="at-card">
        <div class="at-card-t">💼 持仓明细 <span class="at-tag">{{ positions.length }}只</span>
          <span v-if="brokenSL.length" class="at-tag at-tag-danger">🔴 {{ brokenSL.length }}只破止损</span>
          <span v-if="nearSL.length" class="at-tag at-tag-warn">⚠ {{ nearSL.length }}只近止损</span>
        </div>
        <div class="at-tbl-wrap">
          <table class="at-tbl">
            <thead><tr>
              <th>代码</th><th>名称</th><th>策略</th><th>数量</th>
              <th>成本</th><th>现价</th><th>止损价</th>
              <th>盈亏%</th><th>盈亏额</th><th>市值</th><th>仓位%</th><th>状态</th>
            </tr></thead>
            <tbody>
              <tr v-for="p in positions" :key="p.ts_code" :class="p.profit_pct >= 0 ? 'r-up' : 'r-dn'">
                <td>{{ p.ts_code?.slice(0,6) }}</td>
                <td>{{ p.stock_name }}</td>
                <td>{{ p.strategy }}</td>
                <td>{{ p.shares }}</td>
                <td>{{ p.cost_price?.toFixed(2) }}</td>
                <td>{{ p.current_price?.toFixed(2) }}</td>
                <td :class="p.stop_loss_status === 'broken' ? 'down' : p.stop_loss_status === 'near' ? 'warn' : 'muted'">{{ p.stop_loss_price?.toFixed(2) || '-' }}</td>
                <td :class="cls(p.profit_pct)" class="b">{{ p.profit_pct >= 0 ? '+' : '' }}{{ p.profit_pct?.toFixed(1) }}%</td>
                <td :class="cls(p.profit_amount || 0)">{{ (p.profit_amount || 0) >= 0 ? '+' : '' }}¥{{ Math.abs(p.profit_amount || 0).toLocaleString() }}</td>
                <td>¥{{ (p.market_value || 0).toLocaleString() }}</td>
                <td class="muted">{{ totalAssets > 0 ? ((p.market_value || 0) / totalAssets * 100).toFixed(1) : 0 }}%</td>
                <td>
                  <span v-if="p.stop_loss_status === 'broken'" class="sl-broken">🔴破止损</span>
                  <span v-else-if="p.stop_loss_status === 'near'" class="sl-near">⚠近止损</span>
                  <span v-else class="sl-ok">安全</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ===== Risk ===== -->
    <div v-show="activeSection === 'risk'" class="at-sec">
      <div class="at-row2">
        <div class="at-card">
          <div class="at-card-t">🛡️ 系统风控</div>
          <div class="at-risk-row"><span>扫描器实例</span><span :class="riskMonitor.scanner_alive ? 'ok' : 'err'">{{ riskMonitor.scanner_alive ? '✅ 已创建' : '❌ 未创建' }}</span></div>
          <div class="at-risk-row"><span>扫描循环</span><span :class="riskMonitor.scan_loop_active ? 'ok' : 'err'">{{ riskMonitor.scan_loop_active ? '✅ 运行中' : '❌ 未启动' }}</span></div>
          <div class="at-risk-row"><span>风控线程</span><span :class="riskMonitor.risk_thread_alive ? 'ok' : 'err'">{{ riskMonitor.risk_thread_alive ? '✅ 运行中' : '❌ 未运行' }}</span></div>
          <div class="at-risk-row"><span>综合状态</span><span :class="riskMonitor.status === 'healthy' ? 'ok' : 'err'">{{ riskMonitor.desc || '未知' }}</span></div>
        </div>
        <div class="at-card">
          <div class="at-card-t">🔴 止损风险</div>
          <div class="at-risk-row"><span>🔴 破止损</span><span class="err">{{ brokenSL.length }}只 / ¥{{ Math.round(brokenSL.reduce((s: number, p: any) => s + Math.abs(p.profit_amount || 0), 0)).toLocaleString() }}</span></div>
          <div class="at-risk-row"><span>⚠️ 接近止损</span><span class="warn">{{ nearSL.length }}只</span></div>
          <div class="at-risk-row"><span>✅ 安全</span><span class="ok">{{ positions.length - brokenSL.length - nearSL.length }}只</span></div>
          <div v-if="brokenSL.length" class="at-broken-list">
            <div v-for="p in brokenSL" :key="p.ts_code" class="at-broken-item">{{ p.ts_code?.slice(0,6) }} {{ p.stock_name }} {{ p.profit_pct?.toFixed(1) }}% (止损¥{{ p.stop_loss_price }})</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.at { padding: 12px; }

/* Alert */
.at-alert { padding: 8px 14px; background: rgba(230,162,60,0.1); border: 1px solid rgba(230,162,60,0.3); border-radius: 6px; margin-bottom: 10px; font-size: 12px; color: #e6a23c; }

/* KPI */
.at-kpi { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 10px; }
.at-kpi-c { background: var(--bg-card); border: 1px solid var(--border-light); border-radius: 6px; padding: 8px 10px; }
.at-kpi-l { font-size: 11px; color: var(--text-tertiary); }
.at-kpi-v { font-size: 15px; font-weight: 700; margin-top: 2px; }

/* Nav */
.at-nav { display: flex; gap: 4px; margin-bottom: 10px; }
.at-nav-b { padding: 4px 10px; border: 1px solid var(--border); border-radius: 4px; background: transparent; color: var(--text-secondary); font-size: 12px; cursor: pointer; }
.at-nav-b:hover { background: var(--bg-hover); }
.at-nav-b.on { background: var(--el-color-primary); color: #fff; border-color: var(--el-color-primary); }

/* Card */
.at-card { background: var(--bg-card); border: 1px solid var(--border-light); border-radius: 6px; padding: 10px; }
.at-card-t { font-size: 13px; font-weight: 600; margin-bottom: 6px; display: flex; align-items: center; gap: 6px; }
.at-tag { font-size: 10px; padding: 1px 5px; border-radius: 3px; background: var(--bg-muted); color: var(--text-tertiary); }
.at-tag-danger { color: var(--stock-up); background: rgba(8,153,129,0.1); }
.at-tag-warn { color: #e6a23c; background: rgba(230,162,60,0.1); }
.at-empty { text-align: center; padding: 20px; color: var(--text-tertiary); font-size: 12px; }

/* 2-col grid */
.at-row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }

/* Scrollable equity breakdown */
.at-scroll { max-height: 320px; overflow-y: auto; }
.at-eq-row { display: flex; justify-content: space-between; padding: 3px 6px; border-bottom: 1px solid var(--border-light); font-size: 12px; }
.at-eq-head { font-weight: 600; color: var(--text-tertiary); font-size: 11px; border-bottom: 2px solid var(--border); }
.at-eq-name { max-width: 80px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.at-eq-sep { text-align: center; color: var(--text-tertiary); border-bottom: none; }
.at-eq-total { font-weight: 700; border-top: 2px solid var(--border); border-bottom: none; margin-top: 2px; }

/* Table wrapper - horizontal scroll for narrow screens */
.at-tbl-wrap { overflow-x: auto; }
.at-tbl { width: 100%; border-collapse: collapse; font-size: 12px; min-width: 800px; }
.at-tbl th { padding: 5px 6px; text-align: left; border-bottom: 2px solid var(--border); color: var(--text-tertiary); font-size: 11px; font-weight: 600; white-space: nowrap; position: sticky; top: 0; background: var(--bg-card); }
.at-tbl td { padding: 4px 6px; border-bottom: 1px solid var(--border-light); white-space: nowrap; }
.r-up td { background: rgba(239,68,68,0.03); }
.r-dn td { background: rgba(8,153,129,0.03); }

/* Color classes */
.up { color: var(--stock-down); }
.down { color: var(--stock-up); }
.warn { color: #e6a23c; }
.muted { color: var(--text-tertiary); }
.b { font-weight: 600; }
.ok { color: var(--stock-down); font-weight: 500; }
.err { color: var(--stock-up); font-weight: 500; }

/* Stop-loss badges */
.sl-broken { color: var(--stock-up); font-weight: 600; font-size: 11px; }
.sl-near { color: #e6a23c; font-size: 11px; }
.sl-ok { color: var(--text-tertiary); font-size: 11px; }

/* Risk rows */
.at-risk-row { display: flex; justify-content: space-between; padding: 5px 6px; border-bottom: 1px solid var(--border-light); font-size: 12px; }

/* Broken list */
.at-broken-list { margin-top: 6px; padding: 6px 8px; background: rgba(8,153,129,0.08); border-radius: 4px; }
.at-broken-item { font-size: 11px; color: var(--stock-up); padding: 1px 0; }
</style>
