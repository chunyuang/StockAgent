<template>
  <div class="factor-selection-view">
    <!-- 顶部标题栏 -->
    <div class="header-strip">
      <div class="title-section">
        <span class="title-icon">📊</span>
        <h1 class="title">因子选股回测</h1>
        <!-- <span class="subtitle">Factor Selection Backtest</span> -->
      </div>
      <div class="header-actions">
        <button class="action-btn" @click="showHistory = !showHistory">
          <span class="icon">📋</span>
          历史记录
        </button>
      </div>
    </div>

    <div class="main-content">
      <!-- 左侧: 参数配置 -->
      <div class="config-panel">
        <div class="panel-header">
          <span class="panel-icon">⚙️</span>
          <span>回测参数</span>
        </div>

        <div class="config-form">
          <!-- 日期范围 -->
          <div class="form-section">
            <div class="section-label">
              <span class="section-icon">📅</span>
              回测区间
            </div>
            <div class="form-row">
              <div class="form-group">
                <label class="form-label">开始日期</label>
                <input 
                  v-model="form.start_date"
                  type="date"
                  class="form-input"
                />
              </div>
              <div class="form-group">
                <label class="form-label">结束日期</label>
                <input 
                  v-model="form.end_date"
                  type="date"
                  class="form-input"
                />
              </div>
            </div>
          </div>

          <!-- 资金配置 -->
          <div class="form-section">
            <div class="section-label">
              <span class="section-icon">💰</span>
              资金与仓位
            </div>
            <div class="form-row">
              <div class="form-group">
                <label class="form-label">初始资金</label>
                <div class="input-with-suffix">
                  <input 
                    v-model.number="form.initial_cash"
                    type="number"
                    class="form-input"
                    min="100000"
                    max="100000000"
                  />
                  <span class="input-suffix">元</span>
                </div>
              </div>
              <div class="form-group">
                <label class="form-label">选股数量</label>
                <div class="input-with-suffix">
                  <input 
                    v-model.number="form.top_n"
                    type="number"
                    class="form-input"
                    min="1"
                    max="100"
                  />
                  <span class="input-suffix">只</span>
                </div>
              </div>
            </div>
          </div>

          <!-- 调仓设置 -->
          <div class="form-section">
            <div class="section-label">
              <span class="section-icon">🔄</span>
              调仓设置
            </div>
            <div class="form-row">
              <div class="form-group">
                <label class="form-label">调仓频率</label>
                <select v-model="form.rebalance_freq" class="form-select">
                  <option value="daily">每日</option>
                  <option value="weekly">每周</option>
                  <option value="monthly">每月</option>
                  <option value="quarterly">每季度</option>
                </select>
              </div>
              <div class="form-group">
                <label class="form-label">权重方法</label>
                <select v-model="form.weight_method" class="form-select">
                  <option value="equal">等权重</option>
                  <option value="factor_weighted">因子加权</option>
                </select>
              </div>
            </div>
          </div>

          <!-- 排除规则 -->
          <div class="form-section">
            <div class="section-label">
              <span class="section-icon">🚫</span>
              排除规则
            </div>
            <div class="exclude-chips">
              <label 
                v-for="rule in excludeRules" 
                :key="rule.value"
                class="exclude-chip"
                :class="{ active: form.exclude.includes(rule.value) }"
              >
                <input 
                  type="checkbox"
                  :value="rule.value"
                  v-model="form.exclude"
                />
                <span class="chip-label">{{ rule.label }}</span>
              </label>
            </div>
          </div>

          <!-- 因子选择 -->
          <div class="form-section factors-section">
            <div class="section-label">
              <span class="section-icon">⚖️</span>
              选股因子
              <span class="section-hint">选择并调整因子权重</span>
            </div>
            
            <!-- 因子分类 -->
            <div class="factor-categories">
              <div 
                v-for="(factors, category) in groupedFactors" 
                :key="category"
                class="factor-category"
              >
                <div class="category-header" @click="toggleCategory(category)">
                  <span class="category-icon">{{ getCategoryIcon(category) }}</span>
                  <span class="category-name">{{ getCategoryName(category) }}</span>
                  <span class="category-toggle">{{ expandedCategories[category] ? '▼' : '▶' }}</span>
                </div>
                
                <div v-if="expandedCategories[category]" class="category-factors">
                  <div 
                    v-for="factor in factors" 
                    :key="factor.name"
                    class="factor-item"
                    :class="{ selected: isFactorSelected(factor.name) }"
                  >
                    <div class="factor-header" @click="toggleFactor(factor)">
                      <input 
                        type="checkbox"
                        :checked="isFactorSelected(factor.name)"
                        @click.stop
                        @change="toggleFactor(factor)"
                      />
                      <span class="factor-name">{{ factor.display_name }}</span>
                      <span class="factor-direction" :class="factor.direction">
                        {{ factor.direction === 'asc' ? '↑' : '↓' }}
                      </span>
                    </div>
                    <div class="factor-desc">{{ factor.description }}</div>
                    
                    <!-- 权重滑块 (仅选中时显示) -->
                    <div v-if="isFactorSelected(factor.name)" class="factor-weight-control">
                      <input 
                        type="range"
                        :value="getFactorWeight(factor.name)"
                        @input="handleWeightChange(factor.name, $event)"
                        min="0"
                        max="1"
                        step="0.05"
                        class="weight-slider"
                      />
                      <span class="weight-value">{{ (getFactorWeight(factor.name) * 100).toFixed(0) }}%</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            
            <!-- 已选因子摘要 -->
            <div v-if="form.factors.length > 0" class="selected-factors-summary">
              <div class="summary-header">已选择 {{ form.factors.length }} 个因子</div>
              <div class="selected-factor-chips">
                <span 
                  v-for="f in form.factors" 
                  :key="f.name"
                  class="selected-chip"
                >
                  {{ getFactorDisplayName(f.name) }}
                  <span class="chip-weight">{{ (f.weight * 100).toFixed(0) }}%</span>
                  <button class="chip-remove" @click="removeFactor(f.name)">×</button>
                </span>
              </div>
            </div>
          </div>

          <!-- 验证提示 -->
          <div v-if="!isFormValid" class="validation-hint">
            <span class="hint-icon">⚠️</span>
            <span v-if="form.factors.length === 0">请至少选择一个因子</span>
            <span v-else-if="!form.start_date || !form.end_date">请选择回测日期范围</span>
            <span v-else-if="form.initial_cash < 100000">初始资金不能少于 10 万元</span>
          </div>

          <!-- 提交按钮 -->
          <button 
            class="submit-btn"
            :disabled="isSubmitting || !isFormValid"
            @click="submitBacktest"
          >
            <span v-if="isSubmitting" class="btn-spinner"></span>
            <span v-else class="btn-icon">▶</span>
            {{ isSubmitting ? '提交中...' : '开始回测' }}
          </button>
        </div>
      </div>

      <!-- 右侧: 结果展示 -->
      <div class="result-panel">
        <!-- 任务状态 -->
        <div v-if="currentTask" class="task-status-card">
          <div class="status-header">
            <span class="status-icon" :class="currentTask.status">
              {{ getStatusIcon(currentTask.status) }}
            </span>
            <span class="status-text">{{ getStatusText(currentTask.status) }}</span>
            <span class="task-id">{{ currentTask.task_id }}</span>
          </div>
          <div v-if="currentTask.status === 'running' || currentTask.status === 'queued'" class="progress-bar">
            <div class="progress-fill"></div>
          </div>
        </div>

        <!-- 空状态 -->
        <div v-if="!result" class="empty-state">
          <div class="empty-icon">📊</div>
          <div class="empty-title">选择因子开始回测</div>
          <div class="empty-desc">
            配置因子权重后，系统将自动选出评分最高的股票构建组合，
            并按设定的频率进行调仓
          </div>
        </div>

        <!-- 结果展示 -->
        <template v-if="result && result.result && result.result.performance">
          <!-- 核心指标卡片 -->
          <div class="metrics-grid">
            <div class="metric-card" :class="(result.result.performance.total_return || 0) >= 0 ? 'up' : 'down'">
              <span class="metric-label">总收益率</span>
              <span class="metric-value">{{ (result.result.performance.total_return || 0).toFixed(2) }}%</span>
            </div>
            <div class="metric-card" :class="(result.result.performance.excess_return || 0) >= 0 ? 'up' : 'down'">
              <span class="metric-label">超额收益</span>
              <span class="metric-value">{{ (result.result.performance.excess_return || 0).toFixed(2) }}%</span>
            </div>
            <div class="metric-card">
              <span class="metric-label">年化收益</span>
              <span class="metric-value">{{ (result.result.performance.annual_return || 0).toFixed(2) }}%</span>
            </div>
            <div class="metric-card">
              <span class="metric-label">夏普比率</span>
              <span class="metric-value">{{ (result.result.performance.sharpe_ratio || 0).toFixed(2) }}</span>
            </div>
            <div class="metric-card warning">
              <span class="metric-label">最大回撤</span>
              <span class="metric-value">{{ (result.result.performance.max_drawdown || 0).toFixed(2) }}%</span>
            </div>
            <div class="metric-card">
              <span class="metric-label">胜率</span>
              <span class="metric-value">{{ (result.result.performance.win_rate || 0).toFixed(1) }}%</span>
            </div>
          </div>

          <!-- 基准对比 -->
          <div class="benchmark-compare">
            <div class="compare-item">
              <span class="compare-label">策略收益</span>
              <span class="compare-value strategy">{{ (result.result.performance.total_return || 0).toFixed(2) }}%</span>
            </div>
            <span class="compare-vs">VS</span>
            <div class="compare-item">
              <span class="compare-label">基准收益 (沪深300)</span>
              <span class="compare-value benchmark">{{ (result.result.performance.benchmark_return || 0).toFixed(2) }}%</span>
            </div>
          </div>

          <!-- 收益曲线图表 -->
          <div class="chart-section">
            <div class="section-header">
              <span class="section-title">📈 净值曲线</span>
              <div class="chart-legend">
                <span class="legend-item strategy">策略</span>
                <span class="legend-item benchmark">基准</span>
              </div>
            </div>
            <div class="chart-container" ref="navChartRef"></div>
          </div>

          <!-- 调仓明细 -->
          <div class="rebalance-section" v-if="result.result.selection_history">
            <div class="section-header">
              <span class="section-title">📋 选股历史</span>
              <span class="section-count">{{ result.result.selection_history.length }} 次调仓</span>
            </div>
            <div class="rebalance-list">
              <div 
                v-for="(item, idx) in result.result.selection_history.slice(0, showAllRebalance ? undefined : 5)" 
                :key="idx"
                class="rebalance-item"
              >
                <div class="rebalance-date">{{ formatDate(item.date) }}</div>
                <div class="rebalance-stocks">
                  <span 
                    class="stock-chip" 
                    v-for="stock in (item.stock_details || item.stocks).slice(0, 10)" 
                    :key="stock.code || stock"
                    :title="stock.code || stock"
                  >
                    {{ stock.name || stock.replace?.(/\.(SH|SZ|BJ)$/, '') || stock }}
                  </span>
                  <span v-if="(item.stock_details || item.stocks).length > 10" class="more-stocks">
                    +{{ (item.stock_details || item.stocks).length - 10 }} 只
                  </span>
                </div>
              </div>
              <button 
                v-if="result.result.selection_history.length > 5"
                class="show-more-btn"
                @click="showAllRebalance = !showAllRebalance"
              >
                {{ showAllRebalance ? '收起' : `展开全部 ${result.result.selection_history.length} 条` }}
              </button>
            </div>
          </div>
        </template>
      </div>
    </div>

    <!-- 历史记录抽屉 -->
    <div class="history-drawer" :class="{ open: showHistory }">
      <div class="drawer-header">
        <h3>回测历史</h3>
        <button class="close-btn" @click="showHistory = false">✕</button>
      </div>
      <div class="history-list">
        <div 
          v-for="item in history" 
          :key="item.task_id" 
          class="history-item"
          @click="loadHistoryResult(item.task_id)"
        >
          <div class="history-main">
            <span class="history-label">因子选股</span>
            <span class="history-meta">Top {{ item.top_n }} · {{ formatFreq(item.rebalance_freq) }}</span>
          </div>
          <div class="history-date">{{ item.start_date }} ~ {{ item.end_date }}</div>
          <div class="history-metrics">
            <span :class="(item.total_return_pct || 0) >= 0 ? 'up' : 'down'">
              {{ (item.total_return_pct || 0).toFixed(2) }}%
            </span>
            <span class="history-sharpe">夏普: {{ (item.sharpe_ratio || 0).toFixed(2) }}</span>
            <span v-if="item.excess_return_pct" class="history-excess">
              超额: {{ item.excess_return_pct.toFixed(2) }}%
            </span>
          </div>
          <div class="history-time">{{ formatTime(item.created_at) }}</div>
        </div>
        <div v-if="history.length === 0" class="no-history">
          暂无因子选股回测记录
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, nextTick } from 'vue'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import { backtestApi } from '@/api'

// 排除规则选项
const excludeRules = [
  { value: 'st', label: 'ST股票' },
  { value: 'new_stock', label: '次新股' },
  { value: 'limit_up', label: '涨停股' },
  { value: 'limit_down', label: '跌停股' },
]

// 因子分类名称映射
const categoryNames: Record<string, string> = {
  momentum: '动量因子',
  value: '价值因子',
  quality: '质量因子',
  growth: '成长因子',
  volatility: '波动因子',
  liquidity: '流动性因子',
  technical: '技术因子',
}

// 因子分类图标
const categoryIcons: Record<string, string> = {
  momentum: '🚀',
  value: '💎',
  quality: '⭐',
  growth: '📈',
  volatility: '📊',
  liquidity: '💧',
  technical: '🔧',
}

// 表单数据
const form = reactive({
  universe: 'all_a',
  start_date: getDefaultStartDate(),
  end_date: getDefaultEndDate(),
  initial_cash: 1000000,
  rebalance_freq: 'monthly',
  top_n: 20,
  weight_method: 'equal',
  factors: [] as Array<{ name: string; weight: number }>,
  exclude: ['st', 'new_stock'],
  benchmark: '000300.SH',
})

// 状态
const isSubmitting = ref(false)
const currentTask = ref<any>(null)
const result = ref<any>(null)
const showAllRebalance = ref(false)
const showHistory = ref(false)
const history = ref<any[]>([])

// 因子数据
const availableFactors = ref<any[]>([])
const groupedFactors = ref<Record<string, any[]>>({})
const expandedCategories = reactive<Record<string, boolean>>({
  momentum: true,
  value: true,
  quality: false,
  growth: false,
  volatility: false,
  liquidity: false,
  technical: false,
})

// 图表
const navChartRef = ref<HTMLElement | null>(null)
let navChart: echarts.ECharts | null = null

// 计算属性
const isFormValid = computed(() => {
  return (
    form.factors.length > 0 &&
    form.start_date &&
    form.end_date &&
    form.initial_cash >= 100000
  )
})

// 默认日期
function getDefaultStartDate(): string {
  const d = new Date()
  d.setFullYear(d.getFullYear() - 1)
  return d.toISOString().split('T')[0]
}

function getDefaultEndDate(): string {
  return new Date().toISOString().split('T')[0]
}

// 加载因子列表
async function loadFactors() {
  try {
    const res = await backtestApi.getFactors()
    availableFactors.value = res.factors || []
    groupedFactors.value = res.grouped || {}
    
    // 默认选择几个常用因子
    if (form.factors.length === 0) {
      const defaults = ['momentum_20d', 'pb', 'roe']
      defaults.forEach(name => {
        const factor = availableFactors.value.find((f: any) => f.name === name)
        if (factor) {
          form.factors.push({ name, weight: 0.33 })
        }
      })
    }
  } catch (e) {
    console.error('Failed to load factors:', e)
  }
}

// 因子操作
function isFactorSelected(name: string): boolean {
  return form.factors.some(f => f.name === name)
}

function getFactorWeight(name: string): number {
  const f = form.factors.find(f => f.name === name)
  return f?.weight || 0
}

function setFactorWeight(name: string, weight: number) {
  const f = form.factors.find(f => f.name === name)
  if (f) {
    f.weight = weight
  }
}

function handleWeightChange(name: string, event: Event) {
  const target = event.target as HTMLInputElement
  setFactorWeight(name, Number(target.value))
}

function toggleFactor(factor: any) {
  const idx = form.factors.findIndex(f => f.name === factor.name)
  if (idx >= 0) {
    form.factors.splice(idx, 1)
  } else {
    form.factors.push({ name: factor.name, weight: 0.5 })
  }
}

function removeFactor(name: string) {
  const idx = form.factors.findIndex(f => f.name === name)
  if (idx >= 0) {
    form.factors.splice(idx, 1)
  }
}

function toggleCategory(category: string) {
  expandedCategories[category] = !expandedCategories[category]
}

function getFactorDisplayName(name: string): string {
  const factor = availableFactors.value.find((f: any) => f.name === name)
  return factor?.display_name || name
}

function getCategoryIcon(category: string): string {
  return categoryIcons[category] || '📌'
}

function getCategoryName(category: string): string {
  return categoryNames[category] || category
}

// 提交回测
async function submitBacktest() {
  if (!isFormValid.value) return
  
  isSubmitting.value = true
  result.value = null
  
  try {
    // 转换日期格式
    const startDate = form.start_date.replace(/-/g, '')
    const endDate = form.end_date.replace(/-/g, '')
    
    const requestBody = {
      universe: form.universe,
      start_date: startDate,
      end_date: endDate,
      initial_cash: form.initial_cash,
      rebalance_freq: form.rebalance_freq,
      top_n: form.top_n,
      weight_method: form.weight_method,
      factors: form.factors,
      exclude: form.exclude,
      benchmark: form.benchmark,
    }
    console.log('Factor selection request:', JSON.stringify(requestBody, null, 2))
    
    const res = await backtestApi.submitFactorSelection(requestBody)
    
    currentTask.value = {
      task_id: res.task_id,
      status: res.status,
    }
    
    ElMessage.success('回测任务已提交')
    
    // 轮询结果
    pollResult(res.task_id)
    
  } catch (e: any) {
    console.error('Submit error:', e)
    const errorMsg = e.response?.data?.detail || e.message || '提交失败'
    ElMessage.error(typeof errorMsg === 'string' ? errorMsg : JSON.stringify(errorMsg))
  } finally {
    isSubmitting.value = false
  }
}

// 轮询结果
async function pollResult(taskId: string) {
  let attempts = 0
  const maxAttempts = 300  // 最多等待 5 分钟
  
  const poll = async () => {
    try {
      const res = await backtestApi.getBacktestResult(taskId)
      
      currentTask.value = {
        task_id: taskId,
        status: res.status,
      }
      
      if (res.status === 'completed') {
        result.value = res
        ElMessage.success('回测完成')
        renderChart()
        return
      }
      
      if (res.status === 'failed') {
        ElMessage.error(`回测失败: ${res.error || '未知错误'}`)
        return
      }
      
      if (attempts++ < maxAttempts) {
        setTimeout(poll, 1000)
      }
    } catch (e) {
      console.error('Poll error:', e)
      if (attempts++ < maxAttempts) {
        setTimeout(poll, 2000)
      }
    }
  }
  
  poll()
}

// 渲染图表
function renderChart() {
  if (!result.value?.result?.daily_values || !navChartRef.value) return
  
  nextTick(() => {
    if (!navChartRef.value) return
    
    if (navChart) {
      navChart.dispose()
    }
    
    navChart = echarts.init(navChartRef.value)
    
    const dailyValues = result.value.result.daily_values
    const dates = dailyValues.map((d: any) => d.date)
    const strategyValues = dailyValues.map((d: any) => d.total_value)
    const benchmarkValues = dailyValues.map((d: any) => d.benchmark_value)
    
    const option = {
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(20, 20, 30, 0.9)',
        borderColor: '#4f46e5',
        textStyle: { color: '#fff' },
      },
      legend: {
        data: ['策略净值', '基准净值'],
        textStyle: { color: '#888' },
        top: 10,
      },
      grid: {
        left: 60,
        right: 20,
        top: 50,
        bottom: 30,
      },
      xAxis: {
        type: 'category',
        data: dates,
        axisLine: { lineStyle: { color: '#333' } },
        axisLabel: { color: '#888' },
      },
      yAxis: {
        type: 'value',
        axisLine: { lineStyle: { color: '#333' } },
        axisLabel: { color: '#888' },
        splitLine: { lineStyle: { color: '#222' } },
      },
      series: [
        {
          name: '策略净值',
          type: 'line',
          data: strategyValues,
          lineStyle: { color: '#ef4444', width: 2 },
          itemStyle: { color: '#ef4444' },
          showSymbol: false,
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(239, 68, 68, 0.3)' },
              { offset: 1, color: 'rgba(239, 68, 68, 0.05)' },
            ]),
          },
        },
        {
          name: '基准净值',
          type: 'line',
          data: benchmarkValues,
          lineStyle: { color: '#6366f1', width: 2, type: 'dashed' },
          itemStyle: { color: '#6366f1' },
          showSymbol: false,
        },
      ],
    }
    
    navChart.setOption(option)
  })
}

// 格式化日期
function formatDate(dateStr: string): string {
  if (!dateStr) return ''
  return `${dateStr.slice(0, 4)}-${dateStr.slice(4, 6)}-${dateStr.slice(6, 8)}`
}

// 状态图标
function getStatusIcon(status: string): string {
  const icons: Record<string, string> = {
    queued: '⏳',
    running: '🔄',
    completed: '✅',
    failed: '❌',
    cancelled: '🚫',
  }
  return icons[status] || '❓'
}

function getStatusText(status: string): string {
  const texts: Record<string, string> = {
    queued: '排队中',
    running: '运行中',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
  }
  return texts[status] || status
}

// 加载历史记录
async function loadHistory() {
  try {
    const res = await backtestApi.getBacktestHistory(20, 0, 'factor_selection')
    history.value = res.items
  } catch (e) {
    console.error('Failed to load history:', e)
  }
}

// 加载历史结果
async function loadHistoryResult(taskId: string) {
  try {
    const res = await backtestApi.getBacktestResult(taskId) as any
    console.log('History result:', res)
    console.log('Result has daily_values:', !!res?.result?.daily_values)
    
    if (res && res.status === 'completed') {
      result.value = res
      currentTask.value = { task_id: taskId, status: 'completed' }
      showHistory.value = false
      
      // 等待 DOM 更新
      await nextTick()
      
      // 延迟渲染图表，确保结果面板已显示
      setTimeout(() => {
        console.log('Rendering chart for loaded result')
        renderChart()
      }, 100)
      
      ElMessage.success('已加载历史结果')
    } else if (res && res.status === 'failed') {
      ElMessage.error(`回测失败: ${res.error || '未知错误'}`)
    } else {
      ElMessage.warning(`状态: ${res?.status || 'unknown'}`)
    }
  } catch (e) {
    console.error('Failed to load history result:', e)
    ElMessage.error('加载历史结果失败')
  }
}

// 格式化调仓频率
function formatFreq(freq: string | undefined): string {
  const map: Record<string, string> = {
    daily: '每日',
    weekly: '每周',
    monthly: '每月',
    quarterly: '每季',
  }
  return map[freq || 'monthly'] || freq || ''
}

// 格式化时间
function formatTime(timeStr: string | undefined): string {
  if (!timeStr) return ''
  const d = new Date(timeStr)
  return d.toLocaleString('zh-CN', { 
    month: '2-digit', 
    day: '2-digit', 
    hour: '2-digit', 
    minute: '2-digit' 
  })
}

// 生命周期
onMounted(() => {
  loadFactors()
  loadHistory()
})

// 监听窗口大小变化
window.addEventListener('resize', () => {
  navChart?.resize()
})
</script>

<style scoped lang="scss">
.factor-selection-view {
  min-height: 100vh;
  background: var(--bg-base);
  color: var(--text-primary);
  padding: 20px;
}

.header-strip {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  background: var(--bg-elevated);
  border-radius: 12px;
  margin-bottom: 20px;
  border: 1px solid var(--border-color);
}

.title-section {
  display: flex;
  align-items: center;
  gap: 12px;
}

.title-icon {
  font-size: 24px;
}

.title {
  font-size: 20px;
  font-weight: 600;
  margin: 0;
}

.subtitle {
  color: var(--text-secondary);
  font-size: 12px;
  font-family: 'JetBrains Mono', monospace;
}

.action-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  background: rgba(99, 102, 241, 0.2);
  border: 1px solid rgba(99, 102, 241, 0.3);
  border-radius: 8px;
  color: #a5b4fc;
  text-decoration: none;
  cursor: pointer;
  transition: all 0.2s;
  
  &:hover {
    background: rgba(99, 102, 241, 0.3);
    border-color: rgba(99, 102, 241, 0.5);
  }
}

.main-content {
  display: grid;
  grid-template-columns: 400px 1fr;
  gap: 20px;
}

.config-panel {
  background: var(--bg-primary);
  border-radius: 12px;
  border: 1px solid var(--border-color);
  overflow: hidden;
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px 20px;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-color);
  font-weight: 600;
}

.config-form {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 20px;
  max-height: calc(100vh - 180px);
  overflow-y: auto;
}

.form-section {
  .section-label {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;
    font-weight: 500;
    color: #a5b4fc;
    
    .section-icon {
      font-size: 16px;
    }
    
    .section-hint {
      font-size: 12px;
      color: var(--text-muted);
      margin-left: auto;
    }
  }
}

.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-label {
  display: block;
  margin-bottom: 8px;
  font-size: 13px;
  color: var(--text-secondary);
}

.form-input, .form-select {
  width: 100%;
  padding: 10px 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 14px;
  transition: all 0.2s;
  
  &:focus {
    outline: none;
    border-color: var(--accent-color);
    box-shadow: 0 0 0 3px rgba(var(--accent-rgb), 0.1);
  }
}

.input-with-suffix {
  position: relative;
  
  .form-input {
    width: 100%;
    padding-right: 40px;
  }
  
  .input-suffix {
    position: absolute;
    right: 12px;
    top: 50%;
    transform: translateY(-50%);
    color: var(--text-muted);
    font-size: 12px;
  }
}

.exclude-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.exclude-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 20px;
  cursor: pointer;
  transition: all 0.2s;
  color: var(--text-secondary);
  
  input {
    display: none;
  }
  
  &.active {
    background: rgba(16, 185, 129, 0.1);
    border-color: #10b981;
    color: #10b981;
  }
  
  &:hover {
    border-color: var(--accent-color);
  }
  
  .chip-label {
    font-size: 13px;
  }
}

.factor-categories {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.factor-category {
  background: var(--bg-secondary);
  border-radius: 8px;
  overflow: hidden;
}

.category-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  cursor: pointer;
  transition: background 0.2s;
  
  &:hover {
    background: var(--bg-hover);
  }
  
  .category-icon {
    font-size: 16px;
  }
  
  .category-name {
    flex: 1;
    font-weight: 500;
  }
  
  .category-toggle {
    color: var(--text-muted);
    font-size: 12px;
  }
}

.category-factors {
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.factor-item {
  padding: 10px 12px;
  background: var(--bg-primary);
  border-radius: 6px;
  transition: all 0.2s;
  
  &.selected {
    background: rgba(16, 185, 129, 0.1);
  }
  
  &:hover {
    background: var(--bg-hover);
  }
}

.factor-header {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  
  input[type="checkbox"] {
    width: 16px;
    height: 16px;
    accent-color: #10b981;
  }
  
  .factor-name {
    flex: 1;
    font-weight: 500;
  }
  
  .factor-direction {
    font-size: 14px;
    
    &.asc { color: #10b981; }
    &.desc { color: #f59e0b; }
  }
}

.factor-desc {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 4px;
  padding-left: 24px;
}

.factor-weight-control {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 8px;
  padding-left: 24px;
  
  .weight-slider {
    flex: 1;
    height: 4px;
    appearance: none;
    background: var(--bg-hover);
    border-radius: 2px;
    
    &::-webkit-slider-thumb {
      appearance: none;
      width: 14px;
      height: 14px;
      background: #10b981;
      border-radius: 50%;
      cursor: pointer;
    }
  }
  
  .weight-value {
    font-size: 13px;
    font-weight: 600;
    color: #10b981;
    min-width: 40px;
  }
}

.selected-factors-summary {
  margin-top: 12px;
  padding: 12px;
  background: rgba(16, 185, 129, 0.1);
  border-radius: 8px;
  
  .summary-header {
    font-size: 13px;
    color: #10b981;
    margin-bottom: 8px;
  }
}

.selected-factor-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.selected-chip {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  background: rgba(16, 185, 129, 0.2);
  border-radius: 4px;
  font-size: 12px;
  
  .chip-weight {
    color: #10b981;
    font-weight: 600;
  }
  
  .chip-remove {
    background: none;
    border: none;
    color: var(--text-muted);
    cursor: pointer;
    padding: 0 2px;
    
    &:hover {
      color: #ef4444;
    }
  }
}

.validation-hint {
  padding: 10px 12px;
  background: rgba(245, 158, 11, 0.1);
  border: 1px solid rgba(245, 158, 11, 0.3);
  border-radius: 8px;
  color: #fbbf24;
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.submit-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 14px;
  background: linear-gradient(135deg, #10b981, #059669);
  border: none;
  border-radius: 8px;
  color: white;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  
  &:hover:not(:disabled) {
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
  }
  
  &:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  
  .btn-spinner {
    width: 16px;
    height: 16px;
    border: 2px solid rgba(255,255,255,0.3);
    border-top-color: white;
    border-radius: 50%;
    animation: spin 1s linear infinite;
  }
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.result-panel {
  background: var(--bg-primary);
  border-radius: 12px;
  border: 1px solid var(--border-color);
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.task-status-card {
  background: var(--bg-elevated);
  border-radius: 12px;
  border: 1px solid var(--border-color);
  padding: 16px 20px;
}

.status-header {
  display: flex;
  align-items: center;
  gap: 10px;
}

.status-icon {
  font-size: 20px;
  
  &.running {
    animation: pulse 1.5s infinite;
  }
  
  &.completed {
    color: #10b981;
  }
  
  &.failed {
    color: #ef4444;
  }
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.status-text {
  font-weight: 600;
}

.task-id {
  margin-left: auto;
  font-size: 11px;
  color: var(--text-muted);
  font-family: 'JetBrains Mono', monospace;
}

.progress-bar {
  margin-top: 12px;
  height: 4px;
  background: var(--bg-secondary);
  border-radius: 2px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  width: 30%;
  background: linear-gradient(90deg, #ef4444, #f87171);
  animation: progress-move 1.5s ease-in-out infinite;
}

@keyframes progress-move {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 40px;
  background: var(--bg-elevated);
  border-radius: 12px;
  border: 1px solid var(--border-color);
  text-align: center;
  
  .empty-icon {
    font-size: 64px;
    margin-bottom: 20px;
    opacity: 0.6;
  }
  
  .empty-title {
    font-size: 20px;
    font-weight: 600;
    color: #a5b4fc;
    margin-bottom: 12px;
  }
  
  .empty-desc {
    color: var(--text-muted);
    max-width: 400px;
    line-height: 1.6;
  }
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.metric-card {
  background: var(--bg-elevated);
  border-radius: 12px;
  border: 1px solid var(--border-color);
  padding: 20px;
  text-align: center;
  
  &.up {
    border-color: rgba(239, 68, 68, 0.3);
    background: linear-gradient(135deg, rgba(239, 68, 68, 0.05), transparent);
    
    .metric-value { color: #ef4444; }
  }
  
  &.down {
    border-color: rgba(16, 185, 129, 0.3);
    background: linear-gradient(135deg, rgba(16, 185, 129, 0.05), transparent);
    
    .metric-value { color: #10b981; }
  }
  
  &.warning {
    .metric-value { color: #f59e0b; }
  }
}

.metric-label {
  display: block;
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.metric-value {
  font-size: 24px;
  font-weight: 700;
  font-family: 'JetBrains Mono', monospace;
}

.benchmark-compare {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 30px;
  padding: 20px;
  background: var(--bg-secondary);
  border-radius: 8px;
  
  .compare-item {
    text-align: center;
    
    .compare-label {
      display: block;
      font-size: 12px;
      color: var(--text-secondary);
      margin-bottom: 4px;
    }
    
    .compare-value {
      font-size: 28px;
      font-weight: 700;
      
      &.strategy { color: #ef4444; }
      &.benchmark { color: #6366f1; }
    }
  }
  
  .compare-vs {
    font-size: 14px;
    color: var(--text-muted);
    font-weight: 600;
  }
}

.chart-section {
  background: var(--bg-elevated);
  border-radius: 12px;
  border: 1px solid var(--border-color);
  padding: 20px;
  
  .section-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 16px;
    
    .section-title {
      font-weight: 600;
    }
    
    .chart-legend {
      display: flex;
      gap: 16px;
      
      .legend-item {
        font-size: 12px;
        color: var(--text-secondary);
        display: flex;
        align-items: center;
        gap: 6px;
        
        &::before {
          content: '';
          width: 12px;
          height: 3px;
          border-radius: 2px;
        }
        
        &.strategy::before { background: #ef4444; }
        &.benchmark::before { background: #6366f1; }
      }
    }
  }
  
  .chart-container {
    height: 300px;
  }
}

.rebalance-section {
  background: var(--bg-elevated);
  border-radius: 12px;
  border: 1px solid var(--border-color);
  padding: 20px;
  
  .section-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 16px;
    
    .section-title {
      font-weight: 600;
    }
    
    .section-count {
      font-size: 12px;
      color: var(--text-secondary);
    }
  }
}

.rebalance-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 400px;
  overflow-y: auto;
}

.rebalance-item {
  padding: 12px;
  background: var(--bg-secondary);
  border-radius: 8px;
  
  .rebalance-date {
    font-size: 13px;
    color: #a5b4fc;
    margin-bottom: 8px;
  }
  
  .rebalance-stocks {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  
  .stock-chip {
    padding: 2px 8px;
    background: rgba(99, 102, 241, 0.2);
    border-radius: 4px;
    font-size: 12px;
    font-family: monospace;
  }
  
  .more-stocks {
    font-size: 12px;
    color: var(--text-muted);
  }
}

.show-more-btn {
  padding: 8px;
  background: none;
  border: 1px solid rgba(99, 102, 241, 0.3);
  border-radius: 6px;
  color: #a5b4fc;
  cursor: pointer;
  transition: all 0.2s;
  
  &:hover {
    background: rgba(99, 102, 241, 0.1);
  }
}

@media (max-width: 1200px) {
  .main-content {
    grid-template-columns: 1fr;
  }
  
  .metrics-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

/* 历史抽屉 */
.history-drawer {
  position: fixed;
  top: 0;
  right: -400px;
  width: 400px;
  height: 100vh;
  background: var(--bg-elevated);
  border-left: 1px solid var(--border-color);
  transition: right 0.3s ease;
  z-index: 1000;
  display: flex;
  flex-direction: column;
  
  &.open {
    right: 0;
  }
}

.drawer-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px;
  border-bottom: 1px solid var(--border-color);
  
  h3 {
    margin: 0;
    font-size: 16px;
  }
}

.close-btn {
  width: 32px;
  height: 32px;
  background: var(--bg-secondary);
  border: none;
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 20px;
  cursor: pointer;
  
  &:hover {
    background: var(--bg-hover);
  }
}

.history-list {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}

.history-item {
  padding: 16px;
  background: var(--bg-secondary);
  border-radius: 10px;
  margin-bottom: 10px;
  cursor: pointer;
  transition: all 0.2s;
  
  &:hover {
    background: var(--bg-hover);
    transform: translateX(-4px);
  }
}

.history-main {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
}

.history-label {
  font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
}

.history-meta {
  font-size: 12px;
  color: var(--text-muted);
}

.history-date {
  font-size: 11px;
  color: var(--text-muted);
}

.history-metrics {
  display: flex;
  gap: 16px;
  font-size: 14px;
  font-family: 'JetBrains Mono', monospace;
  
  .up { color: #ef4444; }
  .down { color: #10b981; }
}

.history-sharpe {
  color: var(--text-secondary);
  font-size: 12px;
}

.history-excess {
  color: var(--text-secondary);
  font-size: 12px;
}

.history-time {
  margin-top: 8px;
  font-size: 11px;
  color: var(--text-muted);
}

.no-history {
  text-align: center;
  padding: 40px;
  color: var(--text-muted);
}
</style>
