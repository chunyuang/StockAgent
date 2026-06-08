<script setup lang="ts">
/**
 * OpsTab — 运维操作Tab
 * 从 MarketMonitorView provide/inject 获取composable数据
 * 【v2.9.74: 从MarketMonitorView提取】
 */
import { useScannerMonitorInject } from './scannerMonitorInject'
import SystemHealth from './SystemHealth.vue'
import { ElButton, ElTag, ElInput, ElSelect, ElOption, ElInputNumber, ElDatePicker } from 'element-plus'

const m = useScannerMonitorInject()

// 解构需要的变量(从inject对象)
const {
  loading, isRunning, dryRun, circuitBreakerPaused,
  autoTrades, scanConfig, scanConfigLoading,
  timeline, orders, historyData, historyDate, historyLoading,
  manualTrade, manualQuote,
  cumulativePnl,
  strategyCN,
  // 方法
  manualScan, forceScan, dailySettlement, openTradeAudit,
  fetchAutoTrades, fetchScanConfig, fetchDailyReport,
  openWeeklyReport, toggleDryRun, resetCircuitBreaker,
  exportTradeLog, saveSnapshot, resetAccount, sellAllPositions,
  loadCompare, compareLoading, layerDebugVisible, layerDebugLoading,
  onManualCodeChange, executeManualTrade,
  loadHistory, openTradeDetail,
  dailyReportVisible,
} = m
</script>

<template>
  <div class="mm-tab-content">
    <div class="mm-tab-scroll">
      <!-- 自动交易操作流 -->
      <div class="st">🤖 自动交易操作流 <ElButton size="small" @click="fetchAutoTrades">🔄</ElButton></div>
      <div v-if="!autoTrades.length" class="empty">暂无自动交易记录</div>
      <div v-else class="auto-trades-list">
        <div class="at-header"><span>时间</span><span>来源</span><span>操作</span><span>代码</span><span>名称</span><span>数量</span><span>价格</span><span>策略</span><span>原因</span></div>
        <div v-for="t in autoTrades" :key="t.order_id" class="at-row" :class="{ 'auto-trade': t.source === 'auto', 'manual-trade': t.source === 'manual' }">
          <span class="tl-time">{{ t.time }}</span>
          <span><ElTag size="small" :type="t.source === 'auto' ? 'primary' : 'warning'" style="font-size:10px">{{ t.source === 'auto' ? '🤖自动' : '✋手动' }}</ElTag></span>
          <span class="tl-action" :class="t.side === 'buy' ? 'buy' : 'sell'">{{ t.side === 'buy' ? '买' : '卖' }}</span>
          <span class="code">{{ t.ts_code }}</span>
          <span class="name">{{ t.stock_name }}</span>
          <span>{{ t.quantity }}股</span>
          <span>¥{{ Number(t.price || 0).toFixed(2) }}</span>
          <span v-if="t.strategy" class="tl-strat">{{ strategyCN(t.strategy) }}</span><span v-else>-</span>
          <span class="text-tertiary" style="font-size:11px">{{ t.reason }}</span>
        </div>
      </div>

      <!-- 扫描器配置 -->
      <div class="st" style="margin-top:16px">⏱️ 扫描器配置 <ElButton size="small" @click="fetchScanConfig" :loading="scanConfigLoading">🔄</ElButton></div>
      <div v-if="scanConfig" class="scan-config-grid">
        <div class="sc-item"><span class="sc-label">自动扫描间隔</span><span class="sc-value">{{ scanConfig.scan_interval_desc || scanConfig.scan_interval_sec + '秒' }}</span></div>
        <div class="sc-item"><span class="sc-label">持仓检查间隔</span><span class="sc-value">{{ scanConfig.position_check_interval_sec }}秒</span></div>
        <div class="sc-item"><span class="sc-label">持仓快速检查</span><span class="sc-value">{{ scanConfig.position_check_fast_sec }}秒(接近止损)</span></div>
        <div class="sc-item"><span class="sc-label">持仓紧急检查</span><span class="sc-value">{{ scanConfig.position_check_critical_sec }}秒(触及止损)</span></div>
        <div class="sc-item"><span class="sc-label">信号过期时间</span><span class="sc-value">{{ scanConfig.signal_expire_desc || scanConfig.signal_expire_sec + '秒' }}</span></div>
        <div class="sc-item"><span class="sc-label">最大持仓数</span><span class="sc-value">{{ scanConfig.max_positions }}只</span></div>
        <div class="sc-item"><span class="sc-label">最大仓位比例</span><span class="sc-value">{{ ((Number(scanConfig.max_position_ratio) || 0) * 100).toFixed(0) }}%</span></div>
        <div class="sc-item" v-if="scanConfig.current_smart_interval"><span class="sc-label">当前智能检查间隔</span><span class="sc-value">{{ scanConfig.current_smart_interval }}秒</span></div>
        <div class="sc-item"><span class="sc-label">交易模式</span><span class="sc-value">{{ scanConfig.trade_mode === 'simulated' ? '模拟' : scanConfig.trade_mode === 'gm' ? '掘金' : scanConfig.trade_mode }}</span></div>
        <div class="sc-item"><span class="sc-label">运行状态</span><span class="sc-value" :style="{ color: scanConfig.is_running ? 'var(--el-color-success)' : 'var(--el-color-danger)' }">{{ scanConfig.is_running ? '🟢 运行中' : '🔴 未启动' }}</span></div>
      </div>
      <div v-else class="empty" style="padding:8px">点击刷新加载扫描配置</div>

      <!-- 系统健康 -->
      <div class="st" style="margin-top:16px">💻 系统健康</div>
      <SystemHealth />

      <!-- 快捷操作 -->
      <div class="st" style="margin-top:16px">⚡ 快捷操作</div>
      <div class="ops-grid">
        <ElButton size="small" @click="manualScan" :loading="loading" :disabled="!isRunning">📡 扫描</ElButton>
        <ElButton size="small" type="warning" @click="forceScan" :loading="loading" :disabled="!isRunning">⚡ 强扫</ElButton>
        <ElButton size="small" @click="dailySettlement" :disabled="!isRunning">📅 日结</ElButton>
        <ElButton size="small" @click="openTradeAudit" :disabled="!timeline.length">🔍 审查</ElButton>
        <ElButton size="small" @click="fetchDailyReport(); dailyReportVisible = true">📈 复盘</ElButton>
        <ElButton size="small" @click="openWeeklyReport">📊 周报</ElButton>
        <ElButton size="small" @click="layerDebugVisible = true" :loading="layerDebugLoading">🧪 9层调试</ElButton>
        <ElButton size="small" @click="loadCompare" :loading="compareLoading">📊 回测对比</ElButton>
        <ElButton size="small" @click="toggleDryRun">{{ dryRun ? '🔴 关闭调试' : '🔍 开启调试' }}</ElButton>
        <ElButton v-if="circuitBreakerPaused" size="small" type="danger" @click="resetCircuitBreaker">🔓 解熔断</ElButton>
        <ElButton size="small" @click="exportTradeLog">📥 导出日志</ElButton>
        <ElButton size="small" @click="saveSnapshot">📸 保存快照</ElButton>
        <ElButton size="small" type="warning" @click="resetAccount">🗑️ 清仓重置</ElButton>
        <ElButton size="small" @click="sellAllPositions">💰 一键清仓</ElButton>
      </div>

      <!-- 手动下单 -->
      <div class="st" style="margin-top:16px">🔧 手动下单</div>
      <div class="mf ops-mf">
        <ElInput v-model="manualTrade.ts_code" placeholder="代码 000001.SZ" size="small" @change="onManualCodeChange(manualTrade.ts_code)" />
        <div class="mf-row"><ElSelect v-model="manualTrade.side" size="small" style="width:70px"><ElOption label="买入" value="buy" /><ElOption label="卖出" value="sell" /></ElSelect><ElInputNumber v-model="manualTrade.quantity" :min="0" :step="100" placeholder="数量" size="small" style="flex:1" controls-position="right" /></div>
        <div class="mf-row"><ElInputNumber v-model="manualTrade.price" :min="0" :precision="2" :step="0.01" placeholder="价格(0=市价)" size="small" style="flex:1" controls-position="right" /><span v-if="manualQuote" class="mf-hint" @click="manualTrade.price = manualQuote.price">💰 填入现价</span></div>
        <ElButton type="primary" size="small" :disabled="!manualTrade.ts_code" @click="executeManualTrade" class="w-full">下单</ElButton>
        <div v-if="manualQuote" class="mf-q">💡 现价: ¥{{ manualQuote.price?.toFixed(2) }} <span v-if="manualQuote.pct_chg" :class="manualQuote.pct_chg >= 0 ? 'up' : 'down'">{{ manualQuote.pct_chg >= 0 ? '+' : '' }}{{ Number(manualQuote.pct_chg || 0).toFixed(2) }}%</span></div>
      </div>

      <!-- 交易时间线 -->
      <div class="st" style="margin-top:16px">⏱️ 交易时间线 ({{ timeline.length }}) <span v-if="cumulativePnl" :class="cumulativePnl >= 0 ? 'up' : 'down'" style="font-size:12px;margin-left:6px">累计{{ cumulativePnl >= 0 ? '+' : '' }}¥{{ Number(cumulativePnl || 0).toFixed(0) }}</span>
        <div style="display:inline-flex;align-items:center;gap:4px;margin-left:8px"><ElDatePicker v-model="historyDate" type="date" placeholder="日期" size="small" value-format="YYYY-MM-DD" style="width:130px" :disabled-date="(d: Date) => d > new Date()" /><ElButton size="small" @click="loadHistory" :loading="historyLoading" style="padding:2px 8px;font-size:11px">回放</ElButton></div>
      </div>
      <div v-if="!timeline.length && !historyData.length" class="empty">暂无交易</div>
      <div v-else class="ops-timeline">
        <div v-if="historyData.length" class="history-tag">📜 {{ historyDate }} 历史回放 ({{ historyData.length }}条)</div>
        <div v-for="(item, i) in historyData.length ? historyData : timeline" :key="i" class="tl-row cp" @click="item.action !== 'blocked' && openTradeDetail(item.ts_code)"><span class="tl-time">{{ item.time }}</span><span class="tl-action" :class="item.action === 'buy' ? 'buy' : item.action === 'sell' ? 'sell' : 'blocked'">{{ item.action === 'buy' ? '买' : item.action === 'sell' ? '卖' : '⛔' }}</span><span class="code">{{ item.ts_code }}</span><span class="name">{{ item.stock_name }}</span><template v-if="item.action !== 'blocked'"><span v-if="item.strategy" class="tl-strat">{{ strategyCN(item.strategy) }}</span><span class="tl-detail">{{ item.shares }}股@{{ item.price?.toFixed(2) || '-' }}</span><span v-if="item.profit_pct !== undefined" :class="item.profit_pct >= 0 ? 'up' : 'down'">{{ item.profit_pct >= 0 ? '+' : '' }}{{ Number(item.profit_pct || 0).toFixed(1) }}%</span><span v-if="item.profit_amount != null" :class="item.profit_amount >= 0 ? 'up' : 'down'" class="tl-amt">{{ item.profit_amount >= 0 ? '+' : '' }}¥{{ Number(item.profit_amount || 0).toFixed(0) }}</span></template><span v-else class="tl-blocked-reason">{{ item.reason }}</span></div>
      </div>

      <!-- 历史订单 -->
      <div v-if="orders.length" class="st" style="margin-top:16px">📋 历史订单 ({{ orders.length }})</div>
      <div v-if="orders.length" class="ops-timeline">
        <div v-for="o in orders.slice(0, 50)" :key="o.order_id" class="tl-row cp" @click="openTradeDetail(o.ts_code)"><span class="tl-time">{{ String(o.trade_date || '').slice(-4) }} {{ o.create_time }}</span><span class="tl-action" :class="o.side === 'buy' ? 'buy' : 'sell'">{{ o.side === 'buy' ? '买' : '卖' }}</span><span class="code">{{ o.ts_code }}</span><span class="name">{{ o.stock_name }}</span><span class="tl-detail">{{ o.filled_qty }}股@{{ o.filled_price?.toFixed(2) || '0.00' }}</span><span class="text-tertiary-sm">{{ strategyCN(o.strategy) }}</span></div>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.mf { display: flex; flex-direction: column; gap: 4px; min-width: 0; }

.mf-row { display: flex; gap: 4px; min-width: 0; flex-wrap: wrap; }

.mf-q { font-size: 11px; color: var(--stock-down); padding: 2px 0; }

.mf-hint { font-size: 11px; color: var(--el-color-primary); cursor: pointer; padding: 0 4px; white-space: nowrap; }

.tl-row { display: flex; align-items: center; gap: 6px; padding: 3px 0; font-size: 12px; border-bottom: 1px solid var(--border-light); cursor: pointer; flex-wrap: wrap; min-width: 0; }

.tl-row:hover { background: var(--bg-base); }

.tl-time { font-size: 11px; color: var(--text-tertiary); min-width: 40px; }

.tl-action { font-size: 11px; font-weight: 600; min-width: 20px; }

.tl-action.buy { color: var(--stock-up); }

.tl-action.sell { color: var(--stock-down); }

.tl-action.blocked { color: var(--text-tertiary, var(--text-tertiary)); font-size: 11px; }

.tl-strat { font-size: 10px; color: var(--el-color-primary); background: var(--bg-tertiary); padding: 1px 5px; border-radius: 3px; white-space: nowrap; }

.tl-blocked-reason { font-size: 12px; color: var(--text-tertiary, var(--text-tertiary)); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 300px; }

.tl-detail { font-size: 11px; color: var(--text-secondary); }

.history-tag { font-size: 12px; color: var(--el-color-primary); background: var(--info-bg); padding: 4px 8px; border-radius: 4px; margin-bottom: 4px; font-weight: 600; }

.tl-amt { font-size: 11px; font-weight: 700; min-width: 50px; text-align: right; }

.auto-trades-list { font-size: 12px; }

.at-header, .at-row { display: grid; grid-template-columns: 52px 50px 28px 72px 56px 50px 60px 56px 1fr; gap: 4px; padding: 3px 0; align-items: center; }

.at-header { font-weight: 600; color: var(--text-tertiary); border-bottom: 1px solid var(--border-default); font-size: 11px; }

.at-row { border-bottom: 1px solid var(--border-default); }

.at-row:last-child { border-bottom: none; }

.at-row.auto-trade { background: rgba(22,119,255,0.03); }

.at-row.manual-trade { background: rgba(250,173,20,0.03); }

.ops-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.scan-config-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 6px;
}

.sc-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 5px 10px;
  border-radius: 6px;
  font-size: 12px;
  border: 1px solid var(--border-default);
  background: var(--bg-elevated);
}

.sc-label { color: var(--text-secondary); }

.sc-value { font-weight: 500; font-family: 'JetBrains Mono', monospace; font-size: 11px; }

.ops-mf {
  max-width: 400px;
}

.ops-timeline {
  max-height: 400px;
  overflow-y: auto;
}
</style>
