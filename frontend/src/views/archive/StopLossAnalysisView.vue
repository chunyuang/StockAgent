<script setup lang="ts">
/**
 * 止损止盈分析页面 — 交易归档子页面
 * 展示: 策略配置对比(优化前/后) + 实盘执行记录 + 统计
 */
import { ref, computed, onMounted } from 'vue'
import { Loading } from '@element-plus/icons-vue'
import {
  ElCard, ElSelect, ElOption, ElButton, ElIcon, ElTabs, ElTabPane,
  ElTable, ElTableColumn, ElTag, ElEmpty, ElTooltip, ElSwitch,
  ElDescriptions, ElDescriptionsItem, ElDivider, ElAlert,
} from 'element-plus'
import { api } from '@/api'

// ==================== 状态 ====================
const loading = ref(false)
const mode = ref<'post' | 'pre'>('post') // 优化后/优化前切换
const activeTab = ref('config')
const executions = ref<any[]>([])
const stats = ref<any>(null)
const configData = ref<any[]>([])
const selectedDate = ref<number>(0)
const dates = ref<number[]>([])

// ==================== 计算 ====================
const modeLabel = computed(() => mode.value === 'post' ? 'v2.9.119 (优化后)' : 'v2.9.115 (优化前)')

const statsByType = computed(() => stats.value?.by_type || [])

const filteredExecutions = computed(() => {
  if (!selectedDate.value) return executions.value
  return executions.value.filter(e => e.trade_date === selectedDate.value)
})

// ==================== 方法 ====================
async function fetchAll() {
  loading.value = true
  try {
    const [cfg, exec, st] = await Promise.all([
      api.get('/stop-loss-analysis/config'),
      api.get('/stop-loss-analysis/executions?limit=200'),
      api.get('/stop-loss-analysis/stats'),
    ])
    configData.value = cfg || []
    executions.value = exec || []
    stats.value = st || null
    // 提取日期列表
    const dateSet = new Set<number>()
    executions.value.forEach(e => { if (e.trade_date) dateSet.add(e.trade_date) })
    dates.value = Array.from(dateSet).sort((a, b) => b - a)
    if (dates.value.length > 0 && !selectedDate.value) {
      selectedDate.value = 0 // 默认全部
    }
  } catch (e) {
    console.warn('加载止损止盈数据失败', e)
  } finally {
    loading.value = false
  }
}

function fmtMoney(val: number | undefined, unit: '万' | '元' = '元'): string {
  if (val == null) return '-'
  if (unit === '万') return (val / 10000).toFixed(2) + '万'
  return val.toFixed(0) + '元'
}

function fmtPct(val: number | undefined): string {
  if (val == null) return '-'
  return val.toFixed(1) + '%'
}

function fmtPrice(val: number | undefined): string {
  if (val == null) return '-'
  return val.toFixed(2)
}

function sellTypeTag(type: string): string {
  const map: Record<string, string> = {
    '跳空止损': 'danger',
    '固定止损': 'danger',
    '追踪止损': 'warning',
    '止盈': 'success',
    '分批止盈': 'success',
    '冲高回落': 'warning',
    '强制空仓': 'info',
    '超时强卖': 'info',
    '其他': 'info',
  }
  return map[type] || 'info'
}

function pnlClass(val: number): string {
  if (val > 0) return 'pnl-win'
  if (val < 0) return 'pnl-lose'
  return ''
}

// ==================== 生命周期 ====================
onMounted(() => {
  fetchAll()
})
</script>

<template>
  <div class="stop-loss-page">
    <!-- 页面标题 -->
    <div class="page-header">
      <div class="header-left">
        <h2>止损止盈分析</h2>
        <p class="subtitle">策略配置对比 · 实盘执行记录 · 优化前后切换</p>
      </div>
      <div class="header-right">
        <span class="mode-label">优化后</span>
        <ElSwitch
          v-model="mode"
          active-value="post"
          inactive-value="pre"
          active-text="优化后"
          inactive-text="优化前"
          inline-prompt
          style="margin: 0 12px"
        />
        <span class="mode-label">优化前</span>
        <ElButton type="primary" :loading="loading" @click="fetchAll" style="margin-left: 12px">
          刷新
        </ElButton>
      </div>
    </div>

    <!-- 优化前后提示 -->
    <ElAlert
      v-if="mode === 'post'"
      type="success"
      :closable="false"
      show-icon
      style="margin-bottom: 16px"
    >
      <template #title>
        <span>当前展示: <b>v2.9.119 (优化后)</b> — ATR自适应止损 + 分批止盈 + 高盈利紧缩 + 分级追踪止损 + 跳空分级观察期</span>
      </template>
    </ElAlert>
    <ElAlert
      v-else
      type="warning"
      :closable="false"
      show-icon
      style="margin-bottom: 16px"
    >
      <template #title>
        <span>当前展示: <b>v2.9.115 (优化前)</b> — 固定3%止损 + 固定止盈 + 统一5%追踪止损 + 跳空立即止损</span>
      </template>
    </ElAlert>

    <!-- 加载中 -->
    <div v-if="loading" class="center-hint">
      <ElIcon class="is-loading" :size="24"><Loading /></ElIcon>
      <span>加载中...</span>
    </div>

    <div v-else>
      <ElTabs v-model="activeTab" type="border-card" class="sl-tabs">

        <!-- ========== 策略配置对比 ========== -->
        <ElTabPane name="config">
          <template #label><span>📋 策略配置</span></template>

          <div v-for="item in configData" :key="item.category" class="config-section">
            <h3 class="config-title">
              <span v-if="item.category === 'stop_loss'">🛡️ 止损</span>
              <span v-else-if="item.category === 'take_profit'">🎯 止盈</span>
              <span v-else-if="item.category === 'trailing_stop'">📈 追踪止损</span>
              <span v-else-if="item.category === 'gap_stop'">⚠️ 跳空止损</span>
            </h3>

            <div class="config-compare">
              <!-- 优化前 -->
              <div class="config-card config-pre">
                <div class="cc-header">
                  <ElTag type="warning" size="small">优化前</ElTag>
                  <span class="cc-version">{{ item.pre_optimization.version || 'v2.9.115' }}</span>
                </div>
                <div class="cc-body">
                  <ElDescriptions :column="1" size="small" border>
                    <ElDescriptionsItem label="类型">{{ item.pre_optimization.type || '-' }}</ElDescriptionsItem>
                    <ElDescriptionsItem v-if="item.pre_optimization.default_pct !== undefined" label="默认止损">{{ item.pre_optimization.default_pct }}%</ElDescriptionsItem>
                    <ElDescriptionsItem v-if="item.pre_optimization.atr_multiplier" label="ATR乘数">{{ item.pre_optimization.atr_multiplier }}</ElDescriptionsItem>
                    <ElDescriptionsItem v-if="item.pre_optimization.atr_adaptive !== undefined" label="ATR自适应">
                      <ElTag :type="item.pre_optimization.atr_adaptive ? 'success' : 'info'" size="small">{{ item.pre_optimization.atr_adaptive ? '是' : '否' }}</ElTag>
                    </ElDescriptionsItem>
                    <ElDescriptionsItem v-if="item.pre_optimization.partial_take_profit !== undefined" label="分批止盈">
                      <ElTag :type="item.pre_optimization.partial_take_profit ? 'success' : 'info'" size="small">{{ item.pre_optimization.partial_take_profit ? '是' : '否' }}</ElTag>
                    </ElDescriptionsItem>
                    <ElDescriptionsItem v-if="item.pre_optimization.high_profit_tighten !== undefined" label="高盈利紧缩">
                      <ElTag :type="item.pre_optimization.high_profit_tighten ? 'success' : 'info'" size="small">{{ item.pre_optimization.high_profit_tighten ? '是' : '否' }}</ElTag>
                    </ElDescriptionsItem>
                    <ElDescriptionsItem v-if="item.pre_optimization.market_filter !== undefined" label="大盘过滤">
                      <ElTag :type="item.pre_optimization.market_filter ? 'success' : 'info'" size="small">{{ item.pre_optimization.market_filter ? '是' : '否' }}</ElTag>
                    </ElDescriptionsItem>
                  </ElDescriptions>

                  <!-- 策略级参数表 -->
                  <template v-if="item.pre_optimization.strategy_pct">
                    <div class="sub-title">策略级参数</div>
                    <ElTable :data="Object.entries(item.pre_optimization.strategy_pct).map(([k, v]) => ({ strategy: k, pct: v }))" size="small" border>
                      <ElTableColumn prop="strategy" label="策略" min-width="120" />
                      <ElTableColumn label="百分比" width="100" align="right">
                        <template #default="{ row }">{{ row.pct }}%</template>
                      </ElTableColumn>
                    </ElTable>
                  </template>

                  <template v-if="item.pre_optimization.activate_threshold">
                    <div class="sub-title">激活阈值</div>
                    <ElTable :data="Object.entries(item.pre_optimization.activate_threshold).map(([k, v]) => ({ strategy: k, pct: v }))" size="small" border>
                      <ElTableColumn prop="strategy" label="策略" min-width="120" />
                      <ElTableColumn label="阈值" width="100" align="right">
                        <template #default="{ row }">{{ row.pct }}%</template>
                      </ElTableColumn>
                    </ElTable>
                  </template>

                  <div class="cc-desc">{{ item.pre_optimization.description || '' }}</div>
                </div>
              </div>

              <!-- 优化后 -->
              <div class="config-card config-post">
                <div class="cc-header">
                  <ElTag type="success" size="small">优化后</ElTag>
                  <span class="cc-version">{{ item.post_optimization.version || 'v2.9.119' }}</span>
                </div>
                <div class="cc-body">
                  <ElDescriptions :column="1" size="small" border>
                    <ElDescriptionsItem label="类型">{{ item.post_optimization.type || '-' }}</ElDescriptionsItem>
                    <ElDescriptionsItem v-if="item.post_optimization.default_pct !== undefined" label="默认止损">{{ item.post_optimization.default_pct }}%</ElDescriptionsItem>
                    <ElDescriptionsItem v-if="item.post_optimization.atr_multiplier" label="ATR乘数">{{ item.post_optimization.atr_multiplier }}</ElDescriptionsItem>
                    <ElDescriptionsItem v-if="item.post_optimization.atr_period" label="ATR周期">{{ item.post_optimization.atr_period }}天</ElDescriptionsItem>
                    <ElDescriptionsItem v-if="item.post_optimization.atr_adaptive !== undefined" label="ATR自适应">
                      <ElTag :type="item.post_optimization.atr_adaptive ? 'success' : 'info'" size="small">{{ item.post_optimization.atr_adaptive ? '是' : '否' }}</ElTag>
                    </ElDescriptionsItem>
                    <ElDescriptionsItem v-if="item.post_optimization.partial_take_profit !== undefined" label="分批止盈">
                      <ElTag :type="item.post_optimization.partial_take_profit ? 'success' : 'info'" size="small">{{ item.post_optimization.partial_take_profit ? '是' : '否' }}</ElTag>
                    </ElDescriptionsItem>
                    <ElDescriptionsItem v-if="item.post_optimization.partial_threshold !== undefined" label="分批阈值">{{ item.post_optimization.partial_threshold }}% (卖{{ (item.post_optimization.partial_ratio * 100) }}%)</ElDescriptionsItem>
                    <ElDescriptionsItem v-if="item.post_optimization.high_profit_tighten !== undefined" label="高盈利紧缩">
                      <ElTag :type="item.post_optimization.high_profit_tighten ? 'success' : 'info'" size="small">{{ item.post_optimization.high_profit_tighten ? '是' : '否' }}</ElTag>
                    </ElDescriptionsItem>
                    <ElDescriptionsItem v-if="item.post_optimization.high_profit_threshold !== undefined" label="紧缩阈值">≥{{ item.post_optimization.high_profit_threshold }}% → 回撤{{ item.post_optimization.high_profit_tighten_pct }}%</ElDescriptionsItem>
                    <ElDescriptionsItem v-if="item.post_optimization.min_activate_pct !== undefined" label="最低激活">{{ item.post_optimization.min_activate_pct }}%</ElDescriptionsItem>
                    <ElDescriptionsItem v-if="item.post_optimization.market_filter !== undefined" label="大盘过滤">
                      <ElTag :type="item.post_optimization.market_filter ? 'success' : 'info'" size="small">{{ item.post_optimization.market_filter ? '是' : '否' }}</ElTag>
                    </ElDescriptionsItem>
                  </ElDescriptions>

                  <!-- ATR范围表 -->
                  <template v-if="item.post_optimization.strategy_atr_ranges">
                    <div class="sub-title">策略ATR止损范围</div>
                    <ElTable :data="Object.entries(item.post_optimization.strategy_atr_ranges).map(([k, v]) => ({ strategy: k, min: v.min, max: v.max }))" size="small" border>
                      <ElTableColumn prop="strategy" label="策略" min-width="120" />
                      <ElTableColumn label="下限" width="80" align="right">
                        <template #default="{ row }">{{ row.min }}%</template>
                      </ElTableColumn>
                      <ElTableColumn label="上限" width="80" align="right">
                        <template #default="{ row }">{{ row.max }}%</template>
                      </ElTableColumn>
                    </ElTable>
                  </template>

                  <!-- 策略级参数表 -->
                  <template v-if="item.post_optimization.strategy_pct">
                    <div class="sub-title">策略级止盈参数</div>
                    <ElTable :data="Object.entries(item.post_optimization.strategy_pct).map(([k, v]) => ({ strategy: k, pct: v }))" size="small" border>
                      <ElTableColumn prop="strategy" label="策略" min-width="120" />
                      <ElTableColumn label="百分比" width="100" align="right">
                        <template #default="{ row }">{{ row.pct }}%</template>
                      </ElTableColumn>
                    </ElTable>
                  </template>

                  <!-- 策略偏移表 -->
                  <template v-if="item.post_optimization.strategy_offsets">
                    <div class="sub-title">策略追踪止损偏移</div>
                    <ElTable :data="Object.entries(item.post_optimization.strategy_offsets).map(([k, v]) => ({ strategy: k, offsets: (v as number[]).map(o => (o*100).toFixed(0)+'%').join(' / ') }))" size="small" border>
                      <ElTableColumn prop="strategy" label="策略" min-width="120" />
                      <ElTableColumn label="偏移(5%/10%/20%/20%+)" min-width="200" />
                    </ElTable>
                  </template>

                  <!-- 跳空分级 -->
                  <template v-if="item.post_optimization.observation_period">
                    <div class="sub-title">跳空分级观察期</div>
                    <ElTable :data="Object.entries(item.post_optimization.observation_period).map(([k, v]) => ({ level: k, desc: v }))" size="small" border>
                      <ElTableColumn prop="level" label="级别" width="120" />
                      <ElTableColumn prop="desc" label="规则" min-width="280" />
                    </ElTable>
                  </template>

                  <div class="cc-desc">{{ item.post_optimization.description || '' }}</div>
                </div>
              </div>
            </div>
            <ElDivider />
          </div>
        </ElTabPane>

        <!-- ========== 实盘执行记录 ========== -->
        <ElTabPane name="executions">
          <template #label><span>✅ 执行记录 <ElTag v-if="filteredExecutions.length" size="small" round type="info">{{ filteredExecutions.length }}</ElTag></span></template>

          <div class="exec-header">
            <ElSelect v-model="selectedDate" placeholder="全部日期" size="small" style="width:140px" clearable>
              <ElOption :value="0" label="全部日期" />
              <ElOption v-for="d in dates" :key="d" :label="String(d)" :value="d" />
            </ElSelect>
            <span class="exec-note">按日期筛选卖出记录, 显示卖出类型和盈亏</span>
          </div>

          <ElTable :data="filteredExecutions" size="small" stripe class="exec-table" max-height="600">
            <ElTableColumn prop="trade_date" label="日期" width="90" sortable />
            <ElTableColumn prop="fill_time" label="时间" width="140" />
            <ElTableColumn prop="ts_code" label="代码" width="100" />
            <ElTableColumn prop="stock_name" label="名称" width="70" />
            <ElTableColumn label="卖出类型" width="100" align="center">
              <template #default="{ row }">
                <ElTag :type="sellTypeTag(row.sell_type)" size="small" effect="plain">{{ row.sell_type }}</ElTag>
              </template>
            </ElTableColumn>
            <ElTableColumn prop="strategy" label="策略" width="110" />
            <ElTableColumn label="价格" width="70" align="right">
              <template #default="{ row }">{{ fmtPrice(row.filled_price) }}</template>
            </ElTableColumn>
            <ElTableColumn prop="filled_qty" label="数量" width="70" align="right" />
            <ElTableColumn label="盈亏%" width="80" align="right" sortable>
              <template #default="{ row }">
                <span :class="pnlClass(row.profit_pct)">{{ row.profit_pct > 0 ? '+' : '' }}{{ fmtPct(row.profit_pct) }}</span>
              </template>
            </ElTableColumn>
            <ElTableColumn label="盈亏额" width="90" align="right" sortable>
              <template #default="{ row }">
                <span :class="pnlClass(row.profit_amount)">{{ row.profit_amount > 0 ? '+' : '' }}{{ fmtMoney(row.profit_amount) }}</span>
              </template>
            </ElTableColumn>
            <ElTableColumn prop="reason" label="原因" min-width="200" show-overflow-tooltip />
          </ElTable>
          <div v-if="filteredExecutions.length === 0" class="center-hint">暂无执行记录</div>
        </ElTabPane>

        <!-- ========== 统计 ========== -->
        <ElTabPane name="stats">
          <template #label><span>📊 统计</span></template>

          <div v-if="stats" class="stats-grid">
            <!-- 总览 -->
            <div class="stats-overview">
              <div class="so-item">
                <span class="so-label">总卖出笔数</span>
                <span class="so-value">{{ stats.total_sells }}</span>
              </div>
              <div class="so-item">
                <span class="so-label">总盈亏</span>
                <span class="so-value" :class="pnlClass(stats.total_pnl)">
                  {{ stats.total_pnl > 0 ? '+' : '' }}{{ fmtMoney(stats.total_pnl) }}
                </span>
              </div>
              <div class="so-item">
                <span class="so-label">胜率</span>
                <span class="so-value">{{ stats.win_rate }}%</span>
              </div>
            </div>

            <!-- 按类型分组 -->
            <div class="stats-by-type">
              <h3>按卖出类型分组</h3>
              <ElTable :data="statsByType" size="small" stripe border>
                <ElTableColumn prop="sell_type" label="卖出类型" width="120">
                  <template #default="{ row }">
                    <ElTag :type="sellTypeTag(row.sell_type)" size="small" effect="plain">{{ row.sell_type }}</ElTag>
                  </template>
                </ElTableColumn>
                <ElTableColumn prop="count" label="笔数" width="80" align="right" sortable />
                <ElTableColumn label="总盈亏" width="120" align="right" sortable>
                  <template #default="{ row }">
                    <span :class="pnlClass(row.total_pnl)">{{ row.total_pnl > 0 ? '+' : '' }}{{ fmtMoney(row.total_pnl) }}</span>
                  </template>
                </ElTableColumn>
                <ElTableColumn prop="win_rate" label="胜率" width="80" align="right" sortable>
                  <template #default="{ row }">{{ row.win_rate }}%</template>
                </ElTableColumn>
                <ElTableColumn prop="avg_pct" label="平均盈亏%" width="100" align="right" sortable>
                  <template #default="{ row }">
                    <span :class="pnlClass(row.avg_pct)">{{ row.avg_pct > 0 ? '+' : '' }}{{ row.avg_pct }}%</span>
                  </template>
                </ElTableColumn>
              </ElTable>
            </div>
          </div>
          <div v-else class="center-hint">暂无统计数据</div>
        </ElTabPane>

      </ElTabs>
    </div>
  </div>
</template>

<style scoped lang="scss">
.stop-loss-page {
  padding: 24px;
  max-width: 1400px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;

  .header-left {
    h2 { margin: 0; font-size: 20px; }
    .subtitle { margin: 4px 0 0; color: var(--el-text-color-secondary); font-size: 13px; }
  }
  .header-right {
    display: flex;
    align-items: center;
    .mode-label { font-size: 13px; color: var(--el-text-color-secondary); }
  }
}

.center-hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  color: var(--el-text-color-secondary);
  gap: 8px;
}

.sl-tabs {
  margin-top: 8px;
}

// 配置对比
.config-section {
  margin-bottom: 8px;
}

.config-title {
  font-size: 16px;
  margin: 0 0 12px;
  padding: 8px 12px;
  background: var(--el-fill-color-light);
  border-radius: 6px;
}

.config-compare {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.config-card {
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  overflow: hidden;

  &.config-pre {
    border-top: 3px solid var(--el-color-warning);
  }
  &.config-post {
    border-top: 3px solid var(--el-color-success);
  }
}

.cc-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--el-fill-color-lighter);
  .cc-version { font-size: 12px; color: var(--el-text-color-secondary); }
}

.cc-body {
  padding: 12px;
}

.sub-title {
  font-size: 13px;
  font-weight: 600;
  margin: 12px 0 6px;
  color: var(--el-text-color-regular);
}

.cc-desc {
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}

// 执行记录
.exec-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  .exec-note { font-size: 12px; color: var(--el-text-color-secondary); }
}

// 统计
.stats-grid {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.stats-overview {
  display: flex;
  gap: 24px;
  padding: 16px;
  background: var(--el-fill-color-light);
  border-radius: 8px;
}

.so-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  .so-label { font-size: 12px; color: var(--el-text-color-secondary); }
  .so-value { font-size: 22px; font-weight: 600; }
}

.stats-by-type {
  h3 { font-size: 15px; margin: 0 0 12px; }
}

// 盈亏颜色
.pnl-win { color: var(--el-color-success); }
.pnl-lose { color: var(--el-color-danger); }

// 响应式
@media (max-width: 900px) {
  .config-compare {
    grid-template-columns: 1fr;
  }
}
</style>
