<script setup lang="ts">
import { ref, computed, onMounted, watch, inject } from 'vue'
import VChart from 'vue-echarts'
import { useChartColors } from './useChartColors'
import { SCANNER_MONITOR_KEY, type ScannerMonitorData } from './scannerMonitorInject'

const c = useChartColors()
const loading = ref(false)
const accountData = ref<any>(null)
const activeSection = ref('overview')

// 获取父组件的activeTab和stockCode切换能力
const monitorData = inject(SCANNER_MONITOR_KEY, null)
const setActiveTab = (tab: string) => {
  if (monitorData?.activeTab) {
    monitorData.activeTab.value = tab
  }
}

const fetchAccount = async () => {
  loading.value = true
  try {
    const [analysisRes, statusRes, accountRes] = await Promise.all([
      fetch('/api/v1/scanner/analysis?period=30d').then(r => r.json()),
      fetch('/api/v1/scanner/status').then(r => r.json()),
      fetch('/api/v1/scanner/account').then(r => r.json()),
    ])
    accountData.value = {
      analysis: analysisRes.data || {},
      status: statusRes.data || {},
      account: accountRes.data || {},
    }
  } catch (e) { console.error(e) }
  loading.value = false
}

onMounted(fetchAccount)

// Account summary - prefer MongoDB account data (available even when scanner stopped)
const acc = computed(() => accountData.value?.analysis?.account || accountData.value?.account || {})
const status = computed(() => accountData.value?.status || {})
const riskMonitor = computed(() => accountData.value?.analysis?.risk_monitor || {})
const positions = computed(() => (accountData.value?.analysis?.positions || []).slice().sort((a: any, b: any) => (a.profit_pct || 0) - (b.profit_pct || 0)))
const totalAssets = computed(() => acc.value.total_assets || 0)
const availableCash = computed(() => acc.value.available_cash || 0)
const marketValue = computed(() => acc.value.market_value || positions.value.reduce((s: number, p: any) => s + (p.market_value || 0), 0))
const totalProfit = computed(() => totalAssets.value - 1000000)
const positionRatio = computed(() => totalAssets.value > 0 ? marketValue.value / totalAssets.value * 100 : 0)
const brokenSL = computed(() => positions.value.filter((p: any) => p.stop_loss_status === 'broken'))
const nearSL = computed(() => positions.value.filter((p: any) => p.stop_loss_status === 'near'))

// Format helpers
const fmt = (v: number) => v >= 0 ? `¥${(v/10000).toFixed(2)}万` : `¥${(v/10000).toFixed(2)}万`
const fmtPct = (v: number) => v >= 0 ? `+${v.toFixed(2)}%` : `${v.toFixed(2)}%`
const cls = (v: number) => v >= 0 ? 'up' : 'down'

// Position pie chart
const posPie = computed(() => {
  const pos = positions.value
  if (!pos.length) return null
  const up = pos.filter((p: any) => p.profit_pct >= 0)
  const down = pos.filter((p: any) => p.profit_pct < 0)
  return {
    tooltip: { trigger: 'item', formatter: '{b}: ¥{c} ({d}%)' },
    legend: { bottom: 0, textStyle: { fontSize: 11 } },
    series: [{
      type: 'pie', radius: ['40%', '70%'], center: ['50%', '45%'],
      label: { formatter: '{b}\n{d}%', fontSize: 10 },
      data: [
        ...(up.length ? [{ value: Math.round(up.reduce((s: number, p: any) => s + p.market_value, 0)), name: '盈利持仓', itemStyle: { color: c.stockDown } }] : []),
        ...(down.length ? [{ value: Math.round(down.reduce((s: number, p: any) => s + p.market_value, 0)), name: '亏损持仓', itemStyle: { color: c.stockUp } }] : []),
        { value: Math.round(availableCash.value), name: '可用现金', itemStyle: { color: '#909399' } },
      ]
    }]
  }
})

// Equity breakdown
const equityBreakdown = computed(() => {
  const items: any[] = [
    { label: '初始资金', value: 1000000, color: '#909399' },
    { label: '已实现盈亏', value: 0, color: '#909399' },
  ]
  positions.value.forEach((p: any) => {
    items.push({ label: p.stock_name || p.ts_code, value: p.profit_amount || 0, color: (p.profit_amount || 0) >= 0 ? c.stockDown : c.stockUp })
  })
  return items
})

const showStockDetail = (code: string) => {
  // 切换到analysis Tab并设置stockCode
  setActiveTab('analysis')
}
</script>

<template>
  <div class="account-tab" v-loading="loading">
    <!-- Risk Alert Banner -->
    <div v-if="riskMonitor.status && riskMonitor.status !== 'healthy'" class="risk-alert-banner">
      <span class="risk-alert-icon">⚠️</span>
      <span>风控告警：{{ riskMonitor.desc }}</span>
      <span v-if="brokenSL.length" style="margin-left:12px;color:var(--stock-up)">🔴 {{ brokenSL.length }}只持仓已跌破止损价</span>
    </div>

    <!-- KPI Cards -->
    <div class="acc-kpi-row">
      <div class="acc-kpi-card">
        <div class="kpi-label">总资产</div>
        <div class="kpi-value">{{ fmt(totalAssets) }}</div>
      </div>
      <div class="acc-kpi-card">
        <div class="kpi-label">可用现金</div>
        <div class="kpi-value">{{ fmt(availableCash) }}</div>
      </div>
      <div class="acc-kpi-card">
        <div class="kpi-label">持仓市值</div>
        <div class="kpi-value">{{ fmt(marketValue) }}</div>
      </div>
      <div class="acc-kpi-card">
        <div class="kpi-label">总盈亏</div>
        <div :class="['kpi-value', cls(totalProfit)]">{{ fmt(totalProfit) }}</div>
      </div>
      <div class="acc-kpi-card">
        <div class="kpi-label">仓位</div>
        <div class="kpi-value">{{ positionRatio.toFixed(1) }}%</div>
      </div>
      <div class="acc-kpi-card">
        <div class="kpi-label">持仓数</div>
        <div class="kpi-value">{{ positions.length }}只</div>
      </div>
    </div>

    <!-- Section Nav -->
    <div class="acc-section-nav">
      <button :class="['sec-btn', activeSection === 'overview' ? 'active' : '']" @click="activeSection = 'overview'">📊 资产分布</button>
      <button :class="['sec-btn', activeSection === 'positions' ? 'active' : '']" @click="activeSection = 'positions'">💼 持仓明细</button>
      <button :class="['sec-btn', activeSection === 'risk' ? 'active' : '']" @click="activeSection = 'risk'">🛡️ 风控状态</button>
    </div>

    <!-- Overview: Asset Distribution -->
    <div :class="['section-content', { 'section-hidden': activeSection !== 'overview' }]">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
        <div class="chart-section">
          <div class="chart-title">📊 资产分布</div>
          <VChart v-if="posPie" :option="posPie" autoresize style="height:300px;width:100%" />
          <div v-else class="ana-empty-sm">空仓</div>
        </div>
        <div class="chart-section">
          <div class="chart-title">📋 盈亏构成</div>
          <div style="padding:8px 0">
            <div v-for="item in equityBreakdown" :key="item.label" style="display:flex;justify-content:space-between;padding:4px 8px;border-bottom:1px solid var(--border-light)">
              <span style="font-size:12px">{{ item.label }}</span>
              <span :style="{ color: item.color, fontSize: '12px', fontWeight: item.value !== 0 ? 600 : 400 }">¥{{ (item.value / 10000).toFixed(2) }}万</span>
            </div>
            <div style="display:flex;justify-content:space-between;padding:8px 8px 4px;font-weight:700;border-top:2px solid var(--border)">
              <span>当前总资产</span>
              <span>¥{{ (totalAssets / 10000).toFixed(2) }}万</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Positions Detail -->
    <div :class="['section-content', { 'section-hidden': activeSection !== 'positions' }]">
      <div v-if="!positions.length" class="ana-empty-sm">空仓</div>
      <div v-else class="chart-section">
        <div class="chart-title">📋 持仓明细 <span class="ana-stat">{{ positions.length }}只</span>
          <span v-if="brokenSL.length" class="ana-stat" style="color:var(--stock-up);background:rgba(8,153,129,0.1)">🔴 {{ brokenSL.length }}只破止损</span>
          <span v-if="nearSL.length" class="ana-stat" style="color:#e6a23c;background:rgba(230,162,60,0.1)">⚠ {{ nearSL.length }}只近止损</span>
        </div>
        <table class="ana-tbl"><thead><tr><th>代码</th><th>名称</th><th>策略</th><th>数量</th><th>成本</th><th>现价</th><th>止损价</th><th>盈亏%</th><th>盈亏额</th><th>市值</th><th>仓位</th><th>状态</th><th></th></tr></thead><tbody>
          <tr v-for="p in positions" :key="p.ts_code" :class="p.profit_pct >= 0 ? 'row-up' : 'row-down'">
            <td>{{ p.ts_code?.slice(0,6) }}</td>
            <td>{{ p.stock_name }}</td>
            <td>{{ p.strategy }}</td>
            <td>{{ p.shares }}</td>
            <td>¥{{ p.cost_price }}</td>
            <td>¥{{ p.current_price }}</td>
            <td :style="{color: p.stop_loss_status === 'broken' ? 'var(--stock-up)' : p.stop_loss_status === 'near' ? '#e6a23c' : 'var(--text-tertiary)'}">¥{{ p.stop_loss_price || '-' }}</td>
            <td :class="cls(p.profit_pct)" style="font-weight:600">{{ p.profit_pct >= 0 ? '+' : '' }}{{ p.profit_pct.toFixed(1) }}%</td>
            <td :class="cls(p.profit_amount)">¥{{ (p.profit_amount || 0).toLocaleString() }}</td>
            <td>¥{{ (p.market_value || 0).toLocaleString() }}</td>
            <td style="font-size:11px">{{ totalAssets > 0 ? ((p.market_value || 0) / totalAssets * 100).toFixed(1) : 0 }}%</td>
            <td><span v-if="p.stop_loss_status === 'broken'" style="color:var(--stock-up);font-weight:600;font-size:11px">🔴破止损</span><span v-else-if="p.stop_loss_status === 'near'" style="color:#e6a23c;font-size:11px">⚠近止损</span><span v-else style="color:var(--text-tertiary);font-size:11px">安全</span></td>
            <td><ElButton size="small" text type="primary" @click="showStockDetail(p.ts_code)">详情</ElButton></td>
          </tr>
        </tbody></table>
      </div>
    </div>

    <!-- Risk Monitor -->
    <div :class="['section-content', { 'section-hidden': activeSection !== 'risk' }]">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
        <div class="chart-section">
          <div class="chart-title">🛡️ 系统风控状态</div>
          <div style="padding:12px 0">
            <div style="display:flex;justify-content:space-between;padding:6px 8px;border-bottom:1px solid var(--border-light)">
              <span>扫描器实例</span>
              <span :style="{color: riskMonitor.scanner_alive ? 'var(--stock-down)' : 'var(--stock-up)'}">{{ riskMonitor.scanner_alive ? '✅ 已创建' : '❌ 未创建' }}</span>
            </div>
            <div style="display:flex;justify-content:space-between;padding:6px 8px;border-bottom:1px solid var(--border-light)">
              <span>扫描循环</span>
              <span :style="{color: riskMonitor.scan_loop_active ? 'var(--stock-down)' : 'var(--stock-up)'}">{{ riskMonitor.scan_loop_active ? '✅ 运行中' : '❌ 未启动' }}</span>
            </div>
            <div style="display:flex;justify-content:space-between;padding:6px 8px;border-bottom:1px solid var(--border-light)">
              <span>风控线程</span>
              <span :style="{color: riskMonitor.risk_thread_alive ? 'var(--stock-down)' : 'var(--stock-up)'}">{{ riskMonitor.risk_thread_alive ? '✅ 运行中' : '❌ 未运行' }}</span>
            </div>
            <div style="display:flex;justify-content:space-between;padding:6px 8px;border-bottom:1px solid var(--border-light)">
              <span>综合状态</span>
              <span :style="{color: riskMonitor.status === 'healthy' ? 'var(--stock-down)' : 'var(--stock-up)', fontWeight: 600}">{{ riskMonitor.desc || '未知' }}</span>
            </div>
          </div>
        </div>
        <div class="chart-section">
          <div class="chart-title">🔴 止损风险汇总</div>
          <div style="padding:12px 0">
            <div style="display:flex;justify-content:space-between;padding:6px 8px;border-bottom:1px solid var(--border-light)">
              <span>🔴 破止损</span>
              <span style="color:var(--stock-up);font-weight:600">{{ brokenSL.length }}只 / ¥{{ Math.round(brokenSL.reduce((s: number, p: any) => s + Math.abs(p.profit_amount || 0), 0)).toLocaleString() }}</span>
            </div>
            <div style="display:flex;justify-content:space-between;padding:6px 8px;border-bottom:1px solid var(--border-light)">
              <span>⚠️ 接近止损</span>
              <span style="color:#e6a23c;font-weight:600">{{ nearSL.length }}只</span>
            </div>
            <div style="display:flex;justify-content:space-between;padding:6px 8px;border-bottom:1px solid var(--border-light)">
              <span>✅ 安全</span>
              <span style="color:var(--stock-down)">{{ positions.length - brokenSL.length - nearSL.length }}只</span>
            </div>
            <div v-if="brokenSL.length" style="padding:8px;margin-top:8px;background:rgba(8,153,129,0.08);border-radius:6px;font-size:12px;color:var(--stock-up)">
              <div v-for="p in brokenSL" :key="p.ts_code" style="padding:2px 0">• {{ p.ts_code?.slice(0,6) }} {{ p.stock_name }} {{ p.profit_pct.toFixed(1) }}% (止损价¥{{ p.stop_loss_price }})</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.account-tab { padding: 12px; }
.risk-alert-banner { padding: 10px 16px; background: rgba(230,162,60,0.1); border: 1px solid rgba(230,162,60,0.3); border-radius: 8px; margin-bottom: 12px; font-size: 13px; color: #e6a23c; display: flex; align-items: center; gap: 8px; }
.risk-alert-icon { font-size: 18px; }
.acc-kpi-row { display: grid; grid-template-columns: repeat(6, 1fr); gap: 8px; margin-bottom: 12px; }
.acc-kpi-card { background: var(--bg-card); border: 1px solid var(--border-light); border-radius: 8px; padding: 10px 12px; text-align: center; }
.kpi-label { font-size: 11px; color: var(--text-tertiary); margin-bottom: 4px; }
.kpi-value { font-size: 16px; font-weight: 700; }
.kpi-value.up { color: var(--stock-down); }
.kpi-value.down { color: var(--stock-up); }
.acc-section-nav { display: flex; gap: 4px; margin-bottom: 12px; flex-wrap: wrap; }
.sec-btn { padding: 5px 12px; border: 1px solid var(--border); border-radius: 6px; background: transparent; color: var(--text-secondary); font-size: 12px; cursor: pointer; transition: all .2s; }
.sec-btn:hover { background: var(--bg-hover); }
.sec-btn.active { background: var(--el-color-primary); color: #fff; border-color: var(--el-color-primary); }
.section-content { display: block; }
.section-hidden { display: none; }
.chart-section { background: var(--bg-card); border: 1px solid var(--border-light); border-radius: 8px; padding: 12px; margin-bottom: 8px; }
.chart-title { font-size: 13px; font-weight: 600; margin-bottom: 8px; display: flex; align-items: center; gap: 8px; }
.ana-stat { font-size: 11px; padding: 1px 6px; border-radius: 4px; background: var(--bg-muted); color: var(--text-tertiary); font-weight: 400; }
.ana-empty-sm { text-align: center; padding: 20px; color: var(--text-tertiary); font-size: 12px; }
.ana-tbl { width: 100%; border-collapse: collapse; font-size: 12px; }
.ana-tbl th { padding: 6px 8px; text-align: left; border-bottom: 2px solid var(--border); color: var(--text-tertiary); font-size: 11px; font-weight: 600; white-space: nowrap; }
.ana-tbl td { padding: 5px 8px; border-bottom: 1px solid var(--border-light); white-space: nowrap; }
.row-up td { background: rgba(239,68,68,0.03); }
.row-down td { background: rgba(8,153,129,0.03); }
.up { color: var(--stock-down); }
.down { color: var(--stock-up); }
.cp { cursor: pointer; }
</style>
