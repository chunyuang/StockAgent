<template>
  <div class="stop-loss-analysis">
    <!-- 顶部标题 -->
    <div class="page-header">
      <h2>止损止盈分析</h2>
      <div class="header-actions">
        <el-radio-group v-model="activeMode" size="small">
          <el-radio-button value="live">实盘</el-radio-button>
          <el-radio-button value="backtest">回测</el-radio-button>
        </el-radio-group>
        <el-switch
          v-model="showOptimized"
          active-text="优化后"
          inactive-text="优化前"
          inline-prompt
        />
      </div>
    </div>

    <!-- Tab 切换 -->
    <el-tabs v-model="activeTab" class="main-tabs">
      <!-- Tab 1: 流程图 -->
      <el-tab-pane label="止损止盈流程" name="flow">
        <div class="flow-container">
          <!-- 实盘流程 -->
          <div v-if="liveFlow" class="flow-section">
            <div class="flow-header">
              <span class="flow-badge live">实盘</span>
              <h3>{{ liveFlow.title }}</h3>
            </div>
            <el-alert :title="`引擎: ${liveFlow.engine}`" :description="`检查频率: ${liveFlow.check_frequency}`" type="info" :closable="false" show-icon />
            <div class="flow-steps">
              <div v-for="step in liveFlow.steps" :key="step.step" class="flow-step">
                <div class="step-number">{{ step.step }}</div>
                <div class="step-body">
                  <div class="step-title">
                    {{ step.name }}
                    <el-tag v-if="step.frequency" size="small" type="warning">{{ step.frequency }}</el-tag>
                  </div>
                  <div class="step-desc">{{ step.desc }}</div>
                  <div class="step-code">{{ step.code }}</div>
                  <div v-if="step.note" class="step-note">💡 {{ step.note }}</div>
                  <ul v-if="step.sub_rules && step.sub_rules.length" class="sub-rules">
                    <li v-for="r in step.sub_rules" :key="r">{{ r }}</li>
                  </ul>
                </div>
              </div>
            </div>
            <div class="flow-features">
              <h4>实盘特性</h4>
              <div class="feature-tags">
                <el-tag v-for="f in liveFlow.features" :key="f" :type="f.startsWith('✅') ? 'success' : 'danger'" effect="plain">{{ f }}</el-tag>
              </div>
            </div>
          </div>

          <el-divider />

          <!-- 回测流程 -->
          <div v-if="backtestFlow" class="flow-section">
            <div class="flow-header">
              <span class="flow-badge backtest">回测</span>
              <h3>{{ backtestFlow.title }}</h3>
            </div>
            <el-alert :title="`引擎: ${backtestFlow.engine}`" :description="`检查频率: ${backtestFlow.check_frequency}`" type="info" :closable="false" show-icon />
            <div class="flow-steps">
              <div v-for="step in backtestFlow.steps" :key="step.step" class="flow-step">
                <div class="step-number">{{ step.step }}</div>
                <div class="step-body">
                  <div class="step-title">{{ step.name }}</div>
                  <div class="step-desc">{{ step.desc }}</div>
                  <div class="step-code">{{ step.code }}</div>
                  <div v-if="step.note" class="step-note">💡 {{ step.note }}</div>
                  <ul v-if="step.sub_rules && step.sub_rules.length" class="sub-rules">
                    <li v-for="r in step.sub_rules" :key="r">{{ r }}</li>
                  </ul>
                </div>
              </div>
            </div>
            <div class="flow-features">
              <h4>回测特性</h4>
              <div class="feature-tags">
                <el-tag v-for="f in backtestFlow.features" :key="f" :type="f.startsWith('✅') ? 'success' : 'danger'" effect="plain">{{ f }}</el-tag>
              </div>
            </div>
            <div v-if="backtestFlow.gaps_with_live && backtestFlow.gaps_with_live.length" class="gaps-section">
              <h4>⚠️ 回测与实盘的差异</h4>
              <div class="feature-tags">
                <el-tag v-for="g in backtestFlow.gaps_with_live" :key="g" type="warning" effect="dark">{{ g }}</el-tag>
              </div>
            </div>
          </div>
        </div>
      </el-tab-pane>

      <!-- Tab 2: 策略配置 -->
      <el-tab-pane label="策略配置对比" name="config">
        <el-alert
          :title="showOptimized ? '当前展示: 优化后配置 (v2.9.119)' : '当前展示: 优化前配置 (v2.9.115)'"
          :type="showOptimized ? 'success' : 'info'"
          :closable="false"
          show-icon
          style="margin-bottom: 16px"
        />
        <div class="config-grid">
          <el-card v-for="item in configData" :key="item.category" class="config-card" shadow="hover">
            <template #header>
              <div class="card-header">
                <span class="card-title">{{ item.name }}</span>
                <div class="card-badges">
                  <span class="flow-badge live">实盘</span>
                  <span class="flow-badge backtest">回测</span>
                </div>
              </div>
            </template>
            <div class="config-detail">
              <el-descriptions :column="1" border size="small">
                <el-descriptions-item label="类型">
                  <el-tag :type="showOptimized ? 'success' : 'info'">
                    {{ currentConfig(item).type }}
                  </el-tag>
                </el-descriptions-item>
                <el-descriptions-item v-if="currentConfig(item).default_pct" label="默认百分比">
                  {{ currentConfig(item).default_pct }}%
                </el-descriptions-item>
                <el-descriptions-item v-if="currentConfig(item).atr_multiplier" label="ATR乘数">
                  {{ currentConfig(item).atr_multiplier }}
                </el-descriptions-item>
                <el-descriptions-item v-if="currentConfig(item).atr_period" label="ATR周期">
                  {{ currentConfig(item).atr_period }}天
                </el-descriptions-item>
                <el-descriptions-item v-if="currentConfig(item).strategy_pct" label="策略百分比">
                  <div v-for="(v, k) in currentConfig(item).strategy_pct" :key="k" class="kv-row">
                    <span>{{ k }}</span><span>{{ v }}%</span>
                  </div>
                </el-descriptions-item>
                <el-descriptions-item v-if="currentConfig(item).strategy_atr_ranges" label="策略ATR范围">
                  <div v-for="(v, k) in currentConfig(item).strategy_atr_ranges" :key="k" class="kv-row">
                    <span>{{ k }}</span><span>{{ v.min }}% ~ {{ v.max }}%</span>
                  </div>
                </el-descriptions-item>
                <el-descriptions-item v-if="currentConfig(item).base_pct" label="基准回撤">
                  {{ currentConfig(item).base_pct }}%
                </el-descriptions-item>
                <el-descriptions-item v-if="currentConfig(item).min_activate_pct" label="最低激活盈利">
                  {{ currentConfig(item).min_activate_pct }}%
                </el-descriptions-item>
                <el-descriptions-item v-if="currentConfig(item).activate_threshold" label="激活阈值">
                  <div v-for="(v, k) in currentConfig(item).activate_threshold" :key="k" class="kv-row">
                    <span>{{ k }}</span><span>{{ v }}</span>
                  </div>
                </el-descriptions-item>
                <el-descriptions-item v-if="currentConfig(item).strategy_offsets" label="策略回撤偏移">
                  <div v-for="(v, k) in currentConfig(item).strategy_offsets" :key="k" class="kv-row">
                    <span>{{ k }}</span><span>{{ v }}</span>
                  </div>
                </el-descriptions-item>
                <el-descriptions-item v-if="currentConfig(item).high_profit_tighten !== undefined" label="高盈利紧缩">
                  <el-tag :type="currentConfig(item).high_profit_tighten ? 'success' : 'info'" size="small">
                    {{ currentConfig(item).high_profit_tighten ? '启用' : '未启用' }}
                  </el-tag>
                  <span v-if="currentConfig(item).high_profit_tighten" style="margin-left: 8px; font-size: 12px; color: #909399">
                    盈利≥{{ currentConfig(item).high_profit_threshold }}% → 回撤收紧到{{ currentConfig(item).high_profit_tighten_pct }}%
                  </span>
                </el-descriptions-item>
                <el-descriptions-item v-if="currentConfig(item).partial_take_profit !== undefined" label="分批止盈">
                  <el-tag :type="currentConfig(item).partial_take_profit ? 'success' : 'info'" size="small">
                    {{ currentConfig(item).partial_take_profit ? '启用' : '未启用' }}
                  </el-tag>
                  <span v-if="currentConfig(item).partial_take_profit" style="margin-left: 8px; font-size: 12px; color: #909399">
                    盈利≥{{ currentConfig(item).partial_threshold }}% → 卖{{ (currentConfig(item).partial_ratio * 100) }}%
                  </span>
                </el-descriptions-item>
                <el-descriptions-item v-if="currentConfig(item).atr_adaptive !== undefined" label="ATR自适应">
                  <el-tag :type="currentConfig(item).atr_adaptive ? 'success' : 'info'" size="small">
                    {{ currentConfig(item).atr_adaptive ? '启用' : '未启用' }}
                  </el-tag>
                </el-descriptions-item>
                <el-descriptions-item v-if="currentConfig(item).market_filter !== undefined" label="大盘过滤">
                  <el-tag :type="currentConfig(item).market_filter ? 'success' : 'info'" size="small">
                    {{ currentConfig(item).market_filter ? '启用' : '未启用' }}
                  </el-tag>
                </el-descriptions-item>
                <el-descriptions-item v-if="currentConfig(item).observation_period" label="观察期">
                  <template v-if="typeof currentConfig(item).observation_period === 'string'">
                    {{ currentConfig(item).observation_period }}
                  </template>
                  <template v-else>
                    <div v-for="(v, k) in currentConfig(item).observation_period" :key="k" class="kv-row">
                      <span>{{ k }}</span><span>{{ v }}</span>
                    </div>
                  </template>
                </el-descriptions-item>
                <el-descriptions-item label="说明" :span="2">
                  {{ currentConfig(item).description }}
                </el-descriptions-item>
              </el-descriptions>
            </div>
          </el-card>
        </div>
      </el-tab-pane>

      <!-- Tab 3: 实盘执行记录 -->
      <el-tab-pane label="实盘执行记录" name="executions">
        <div class="filter-bar">
          <el-date-picker
            v-model="filterDate"
            type="date"
            placeholder="选择交易日筛选"
            format="YYYY-MM-DD"
            value-format="YYYYMMDD"
            clearable
            style="width: 180px"
          />
          <el-button type="primary" @click="loadExecutions">查询</el-button>
        </div>
        <el-table :data="executionData" stripe border style="width: 100%" max-height="600">
          <el-table-column prop="trade_date" label="交易日" width="100" />
          <el-table-column prop="ts_code" label="股票代码" width="110" />
          <el-table-column prop="stock_name" label="名称" width="80" />
          <el-table-column prop="strategy" label="策略" width="90" />
          <el-table-column prop="sell_type" label="卖出类型" width="100">
            <template #default="{ row }">
              <el-tag :type="sellTypeTag(row.sell_type)" size="small">{{ row.sell_type }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="filled_price" label="卖出价" width="80" align="right" />
          <el-table-column prop="filled_qty" label="数量" width="70" align="right" />
          <el-table-column prop="profit_pct" label="盈亏%" width="80" align="right">
            <template #default="{ row }">
              <span :style="{ color: row.profit_pct >= 0 ? '#f56c6c' : '#67c23a', fontWeight: 'bold' }">
                {{ row.profit_pct > 0 ? '+' : '' }}{{ row.profit_pct.toFixed(1) }}%
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="profit_amount" label="盈亏额" width="90" align="right">
            <template #default="{ row }">
              <span :style="{ color: row.profit_amount >= 0 ? '#f56c6c' : '#67c23a' }">
                {{ row.profit_amount > 0 ? '+' : '' }}{{ row.profit_amount.toFixed(0) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="reason" label="卖出原因" min-width="200" show-overflow-tooltip />
        </el-table>
      </el-tab-pane>

      <!-- Tab 4: 统计 -->
      <el-tab-pane label="统计" name="stats">
        <div v-if="statsData" class="stats-container">
          <el-row :gutter="16" class="stats-overview">
            <el-col :span="6">
              <el-card shadow="hover">
                <div class="stat-card">
                  <div class="stat-value">{{ statsData.total_sells }}</div>
                  <div class="stat-label">总卖出笔数</div>
                </div>
              </el-card>
            </el-col>
            <el-col :span="6">
              <el-card shadow="hover">
                <div class="stat-card">
                  <div class="stat-value" :style="{ color: statsData.total_pnl >= 0 ? '#f56c6c' : '#67c23a' }">
                    {{ statsData.total_pnl > 0 ? '+' : '' }}{{ statsData.total_pnl.toFixed(0) }}
                  </div>
                  <div class="stat-label">总盈亏(元)</div>
                </div>
              </el-card>
            </el-col>
            <el-col :span="6">
              <el-card shadow="hover">
                <div class="stat-card">
                  <div class="stat-value">{{ statsData.win_rate }}%</div>
                  <div class="stat-label">胜率</div>
                </div>
              </el-card>
            </el-col>
            <el-col :span="6">
              <el-card shadow="hover">
                <div class="stat-card">
                  <div class="stat-value">{{ statsData.by_type.length }}</div>
                  <div class="stat-label">卖出类型数</div>
                </div>
              </el-card>
            </el-col>
          </el-row>

          <el-card shadow="hover" style="margin-top: 16px">
            <template #header><span>按卖出类型统计</span></template>
            <el-table :data="statsData.by_type" stripe border>
              <el-table-column prop="sell_type" label="卖出类型" width="120">
                <template #default="{ row }">
                  <el-tag :type="sellTypeTag(row.sell_type)" size="small">{{ row.sell_type }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="count" label="笔数" width="80" align="right" />
              <el-table-column prop="total_pnl" label="总盈亏(元)" width="120" align="right">
                <template #default="{ row }">
                  <span :style="{ color: row.total_pnl >= 0 ? '#f56c6c' : '#67c23a', fontWeight: 'bold' }">
                    {{ row.total_pnl > 0 ? '+' : '' }}{{ row.total_pnl.toFixed(0) }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column prop="win_rate" label="胜率" width="80" align="right">
                <template #default="{ row }">{{ row.win_rate }}%</template>
              </el-table-column>
              <el-table-column prop="avg_pct" label="平均盈亏%" width="100" align="right">
                <template #default="{ row }">
                  <span :style="{ color: row.avg_pct >= 0 ? '#f56c6c' : '#67c23a' }">
                    {{ row.avg_pct > 0 ? '+' : '' }}{{ row.avg_pct }}%
                  </span>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'

const API_BASE = '/api/v1/stop-loss-analysis'

const activeTab = ref('flow')
const activeMode = ref('live')
const showOptimized = ref(true)
const filterDate = ref('')

const liveFlow = ref<any>(null)
const backtestFlow = ref<any>(null)
const configData = ref<any[]>([])
const executionData = ref<any[]>([])
const statsData = ref<any>(null)

function currentConfig(item: any) {
  return showOptimized.value ? item.post_optimization : item.pre_optimization
}

function sellTypeTag(type: string) {
  const map: Record<string, string> = {
    '止盈': 'danger',
    '分批止盈': 'danger',
    '追踪止损': 'warning',
    '固定止损': 'danger',
    '跳空止损': 'danger',
    '冲高回落': 'warning',
    '强制空仓': 'info',
    '超时强卖': 'info',
    '其他': '',
  }
  return map[type] || ''
}

async function loadFlow() {
  try {
    const [liveRes, btRes] = await Promise.all([
      fetch(`${API_BASE}/flow/live`),
      fetch(`${API_BASE}/flow/backtest`),
    ])
    liveFlow.value = await liveRes.json()
    backtestFlow.value = await btRes.json()
  } catch (e: any) {
    ElMessage.error('加载流程数据失败: ' + e.message)
  }
}

async function loadConfig() {
  try {
    const res = await fetch(`${API_BASE}/config`)
    configData.value = await res.json()
  } catch (e: any) {
    ElMessage.error('加载配置数据失败: ' + e.message)
  }
}

async function loadExecutions() {
  try {
    const params = new URLSearchParams()
    if (filterDate.value) params.set('trade_date', filterDate.value)
    params.set('limit', '200')
    const res = await fetch(`${API_BASE}/executions?${params}`)
    executionData.value = await res.json()
  } catch (e: any) {
    ElMessage.error('加载执行记录失败: ' + e.message)
  }
}

async function loadStats() {
  try {
    const res = await fetch(`${API_BASE}/stats`)
    statsData.value = await res.json()
  } catch (e: any) {
    ElMessage.error('加载统计数据失败: ' + e.message)
  }
}

onMounted(() => {
  loadFlow()
  loadConfig()
  loadExecutions()
  loadStats()
})
</script>

<style scoped>
.stop-loss-analysis {
  padding: 20px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.page-header h2 {
  margin: 0;
  font-size: 20px;
}

.header-actions {
  display: flex;
  gap: 16px;
  align-items: center;
}

/* 流程图 */
.flow-container {
  max-width: 960px;
}

.flow-section {
  margin-bottom: 24px;
}

.flow-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.flow-header h3 {
  margin: 0;
  font-size: 18px;
}

.flow-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: bold;
}

.flow-badge.live {
  background: #e8f5e9;
  color: #2e7d32;
  border: 1px solid #4caf50;
}

.flow-badge.backtest {
  background: #e3f2fd;
  color: #1565c0;
  border: 1px solid #2196f3;
}

.flow-steps {
  margin-top: 16px;
}

.flow-step {
  display: flex;
  gap: 16px;
  margin-bottom: 16px;
  padding-bottom: 16px;
  border-bottom: 1px dashed #ebeef5;
}

.flow-step:last-child {
  border-bottom: none;
}

.step-number {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: #409eff;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: bold;
  font-size: 14px;
}

.step-body {
  flex: 1;
}

.step-title {
  font-size: 15px;
  font-weight: bold;
  margin-bottom: 4px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.step-desc {
  font-size: 13px;
  color: #606266;
  margin-bottom: 4px;
}

.step-code {
  font-family: 'Courier New', monospace;
  font-size: 12px;
  color: #909399;
  background: #f5f7fa;
  padding: 4px 8px;
  border-radius: 4px;
  margin-bottom: 4px;
}

.step-note {
  font-size: 12px;
  color: #e6a23c;
  margin-bottom: 4px;
}

.sub-rules {
  margin: 4px 0 0 0;
  padding-left: 20px;
  font-size: 12px;
  color: #606266;
}

.sub-rules li {
  line-height: 1.8;
}

.flow-features {
  margin-top: 16px;
}

.flow-features h4 {
  margin: 0 0 8px 0;
  font-size: 14px;
}

.feature-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.gaps-section {
  margin-top: 16px;
  padding: 12px;
  background: #fdf6ec;
  border-radius: 8px;
}

.gaps-section h4 {
  margin: 0 0 8px 0;
  font-size: 14px;
  color: #e6a23c;
}

/* 配置卡片 */
.config-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}

.config-card {
  margin-bottom: 0;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.card-title {
  font-weight: bold;
  font-size: 15px;
}

.card-badges {
  display: flex;
  gap: 4px;
}

.kv-row {
  display: flex;
  justify-content: space-between;
  padding: 2px 0;
  font-size: 13px;
}

.kv-row span:first-child {
  color: #909399;
}

/* 筛选栏 */
.filter-bar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

/* 统计 */
.stats-overview {
  margin-bottom: 16px;
}

.stat-card {
  text-align: center;
  padding: 12px 0;
}

.stat-value {
  font-size: 28px;
  font-weight: bold;
  color: #303133;
}

.stat-label {
  font-size: 13px;
  color: #909399;
  margin-top: 4px;
}
</style>
