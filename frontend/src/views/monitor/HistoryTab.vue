<script setup lang="ts">
/**
 * HistoryTab — 交易历史Tab
 * 从 MarketMonitorView provide/inject 获取composable数据
 * 【v2.9.74: 从MarketMonitorView提取(73行)】
 */
import { useScannerMonitorInject } from './scannerMonitorInject'
import { ElButton, ElDatePicker, ElTag } from 'element-plus'

const m = useScannerMonitorInject()

const {
  auditLog, auditLogLoading, closedPositions, cumulativePnl,
  exportTradeLog, fetchAuditLog, historyData, historyDate, historyLoading,
  loadHistory,
  openTradeAudit, openTradeDetail, orders,
  saveSnapshot, strategyCN, strategyMeta, timeline,
} = m
</script>

<template>
  <div class="mm-tab-content">
    <div class="mm-tab-scroll">
      <!-- 交易时间线 -->
      <div class="st">⏱️ 交易时间线 <span class="text-tertiary" style="font-size:11px">({{ timeline.length }}笔)</span>
        <span v-if="cumulativePnl !== 0" :class="cumulativePnl >= 0 ? 'up' : 'down'" style="font-size:12px;margin-left:6px">累计{{ cumulativePnl >= 0 ? '+' : '' }}¥{{ cumulativePnl.toFixed(0) }}</span>
        <ElButton v-if="timeline.length" size="small" type="warning" @click="openTradeAudit" style="margin-left:8px">🔍 审查</ElButton>
        <div style="display:inline-flex;align-items:center;gap:4px;margin-left:8px"><ElDatePicker v-model="historyDate" type="date" placeholder="历史日期" size="small" value-format="YYYY-MM-DD" style="width:130px" :disabled-date="(d: Date) => d > new Date()" /><ElButton size="small" @click="loadHistory" :loading="historyLoading">回放</ElButton><ElButton v-if="historyData.length" size="small" type="info" @click="historyData=[];historyDate=''">返回</ElButton></div>
      </div>
      <div v-if="historyData.length" class="history-tag" style="margin-bottom:6px">📜 {{ historyDate }} 历史回放 ({{ historyData.length }}条)</div>
      <div v-if="!historyData.length && !timeline.length" class="empty">暂无交易记录</div>
      <div class="ht-timeline">
        <div v-for="(item, i) in historyData.length ? historyData : timeline" :key="i" class="tl-row cp" @click="item.action !== 'blocked' && openTradeDetail(item.ts_code)">
          <span class="tl-time">{{ item.time }}</span>
          <span class="tl-action" :class="item.action === 'buy' ? 'buy' : item.action === 'sell' ? 'sell' : 'blocked'">{{ item.action === 'buy' ? '买' : item.action === 'sell' ? '卖' : '⛔' }}</span>
          <span class="code">{{ item.ts_code }}</span><span class="name">{{ item.stock_name }}</span>
          <span v-if="item.action === 'blocked'" class="tl-blocked-reason">{{ item.reason }}</span>
          <template v-else>
            <span v-if="item.strategy" class="tl-strat">{{ strategyCN(item.strategy) }}</span>
            <span class="tl-detail">{{ item.shares }}股@{{ item.price?.toFixed(2) || '-' }}</span>
            <span v-if="item.profit_pct !== undefined" :class="item.profit_pct >= 0 ? 'up' : 'down'">{{ item.profit_pct >= 0 ? '+' : '' }}{{ item.profit_pct.toFixed(1) }}%</span>
            <span v-if="item.profit_amount != null" :class="item.profit_amount >= 0 ? 'up' : 'down'" class="tl-amt">{{ item.profit_amount >= 0 ? '+' : '' }}¥{{ item.profit_amount.toFixed(0) }}</span>
          </template>
        </div>
      </div>

      <!-- 历史订单 -->
      <div class="st" style="margin-top:16px">📋 历史订单 <span class="text-tertiary" style="font-size:11px">({{ orders.length }}笔)</span></div>
      <div v-if="!orders.length" class="empty">暂无订单</div>
      <div v-else class="ht-orders">
        <div class="ho-header"><span>时间</span><span>方向</span><span>代码</span><span>名称</span><span>数量</span><span>价格</span><span>策略</span></div>
        <div v-for="o in orders" :key="o.order_id" class="ho-row cp" @click="openTradeDetail(o.ts_code)">
          <span class="tl-time">{{ o.trade_date?.slice(-4) || '' }} {{ o.create_time }}</span>
          <span class="tl-action" :class="o.side === 'buy' ? 'buy' : 'sell'">{{ o.side === 'buy' ? '买' : '卖' }}</span>
          <span class="code">{{ o.ts_code }}</span><span class="name">{{ o.stock_name }}</span>
          <span>{{ o.filled_qty }}股</span><span>¥{{ o.filled_price?.toFixed(2) || '0.00' }}</span>
          <span class="text-tertiary-sm">{{ strategyCN(o.strategy) }}</span>
        </div>
      </div>

      <!-- 已平仓汇总 -->
      <div class="st" style="margin-top:16px">💰 已平仓汇总</div>
      <div v-if="!closedPositions.length" class="empty">暂无已平仓记录</div>
      <div v-else class="ht-closed">
        <div class="hc-header"><span>代码</span><span>名称</span><span>策略</span><span>买入价</span><span>卖出价</span><span>盈亏</span><span>盈亏%</span></div>
        <div v-for="cp in closedPositions" :key="cp.ts_code + cp.strategy" class="hc-row" @click="openTradeDetail(cp.ts_code)" :class="cp.profit_pct >= 0 ? 'hc-win' : 'hc-loss'">
          <span class="code">{{ cp.ts_code }}</span><span class="name">{{ cp.stock_name }}</span>
          <span><ElTag size="small" :color="strategyMeta[cp.strategy]?.color || 'var(--text-tertiary)'" class="tag-solid" style="font-size:10px">{{ strategyCN(cp.strategy) }}</ElTag></span>
          <span>¥{{ cp.buy_price?.toFixed(2) }}</span><span>¥{{ cp.sell_price?.toFixed(2) }}</span>
          <span :class="(cp.profit_amount || 0) >= 0 ? 'up' : 'down'">{{ (cp.profit_amount || 0) >= 0 ? '+' : '' }}¥{{ Math.abs(cp.profit_amount || 0).toFixed(0) }}</span>
          <span :class="cp.profit_pct >= 0 ? 'up' : 'down'" style="font-weight:600">{{ cp.profit_pct >= 0 ? '+' : '' }}{{ cp.profit_pct.toFixed(1) }}%</span>
        </div>
      </div>

      <!-- 审计日志 -->
      <div class="st" style="margin-top:16px">📝 审计日志 <ElButton size="small" @click="fetchAuditLog" :loading="auditLogLoading">🔄</ElButton></div>
      <div v-if="!auditLog.length" class="empty">暂无审计记录</div>
      <div v-else class="ht-audit">
        <div v-for="(log, i) in auditLog" :key="i" class="ha-row cp" @click="log.ts_code && openTradeDetail(log.ts_code)">
          <span class="tl-time">{{ log.timestamp?.substring(11, 19) || log.time || '' }}</span>
          <span class="ha-action">{{ log.action }}</span>
          <span class="ha-detail">{{ log.reason || log.detail || '' }}</span>
        </div>
      </div>

      <!-- 导出 -->
      <div class="st" style="margin-top:16px">📥 数据导出</div>
      <div class="ht-export">
        <ElButton size="small" @click="exportTradeLog">📥 导出交易日志(CSV)</ElButton>
        <ElButton size="small" @click="saveSnapshot">📸 保存快照</ElButton>
        <ElButton size="small" @click="openTradeAudit" :disabled="!timeline.length">🔍 交易审查</ElButton>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.ht-timeline { display: flex; flex-direction: column; gap: 2px; }

.ht-orders { border: 1px solid var(--border-default); border-radius: 6px; overflow: hidden; }

.ho-header { display: grid; grid-template-columns: 100px 40px 80px 1fr 60px 70px 60px; gap: 4px; padding: 6px 10px; background: var(--bg-muted); font-size: 11px; color: var(--text-tertiary); font-weight: 600; }

.ho-row { display: grid; grid-template-columns: 100px 40px 80px 1fr 60px 70px 60px; gap: 4px; padding: 4px 10px; font-size: 12px; border-bottom: 1px solid var(--border-default); align-items: center; }

.ho-row:hover { background: var(--bg-muted); }

.ht-closed { border: 1px solid var(--border-default); border-radius: 6px; overflow: hidden; }

.hc-header { display: grid; grid-template-columns: 80px 1fr 60px 70px 70px 70px 60px; gap: 4px; padding: 6px 10px; background: var(--bg-muted); font-size: 11px; color: var(--text-tertiary); font-weight: 600; }

.hc-row { display: grid; grid-template-columns: 80px 1fr 60px 70px 70px 70px 60px; gap: 4px; padding: 4px 10px; font-size: 12px; border-bottom: 1px solid var(--border-default); align-items: center; cursor: pointer; }

.hc-row:hover { background: var(--bg-muted); }

.hc-win { border-left: 3px solid var(--stock-up); }

.hc-loss { border-left: 3px solid var(--stock-down); }

.ht-audit { display: flex; flex-direction: column; gap: 2px; }

.ha-row { display: flex; align-items: center; gap: 8px; padding: 3px 0; font-size: 12px; }

.ha-action { color: var(--el-color-primary); font-weight: 600; min-width: 60px; }

.ha-detail { color: var(--text-secondary); }

.ht-export { display: flex; gap: 8px; flex-wrap: wrap; }
</style>
