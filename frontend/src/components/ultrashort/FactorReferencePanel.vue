<script setup lang="ts">
/**
 * 因子参考面板 — 70个因子完整定义
 * 从MongoDB stock_daily_ak_full字段整理
 */
import { ref, computed } from 'vue'
import { ElInput, ElTable, ElTableColumn, ElTag, ElSelect, ElOption, ElCard } from 'element-plus'

interface FactorDef {
  name: string
  desc: string
  cat: string
  source: string
  strategies: string[]
  unit: string
  example: string
  note?: string  // 额外说明
}

const allFactors: FactorDef[] = [
  // ===== 行情原始 (9) =====
  { name: 'open', desc: '开盘价', cat: '行情原始', source: 'AKShare/东方财富', strategies: [], unit: '元', example: '9.41' },
  { name: 'high', desc: '最高价', cat: '行情原始', source: 'AKShare/东方财富', strategies: [], unit: '元', example: '9.45' },
  { name: 'low', desc: '最低价', cat: '行情原始', source: 'AKShare/东方财富', strategies: [], unit: '元', example: '8.96' },
  { name: 'close', desc: '收盘价', cat: '行情原始', source: 'AKShare/东方财富', strategies: [], unit: '元', example: '8.96' },
  { name: 'pre_close', desc: '前收盘价', cat: '行情原始', source: 'AKShare/东方财富', strategies: [], unit: '元', example: '9.37' },
  { name: 'pct_chg', desc: '涨跌幅(%)', cat: '行情原始', source: 'AKShare/东方财富', strategies: ['半路追涨'], unit: '%', example: '-4.38' },
  { name: 'change', desc: '涨跌额', cat: '行情原始', source: 'AKShare/东方财富', strategies: [], unit: '元', example: '-0.41' },
  { name: 'vol', desc: '成交量(股)', cat: '行情原始', source: 'AKShare/东方财富', strategies: [], unit: '股', example: '20294181' },
  { name: 'amount', desc: '成交额', cat: '行情原始', source: 'AKShare/东方财富', strategies: [], unit: '元', example: '1.86亿' },

  // ===== 基础面 (5) =====
  { name: 'turnover_rate', desc: '换手率(%)', cat: '基础面', source: '东方财富daily_basic', strategies: ['首板打板', '跌停翘板'], unit: '%', example: '2.92' },
  { name: 'volume_ratio', desc: '量比(当日成交/5日均量)', cat: '基础面', source: 'factor_auto_compute', strategies: ['半路追涨', '龙头低吸'], unit: '倍', example: '1.5' },
  { name: 'circ_mv', desc: '流通市值(万元)', cat: '基础面', source: '东方财富daily_basic', strategies: ['首板打板', '龙头低吸', '跌停翘板'], unit: '万元', example: '62亿' },
  { name: 'pe_ttm', desc: '滚动市盈率(TTM)', cat: '基础面', source: '东方财富daily_basic', strategies: [], unit: '倍', example: '154.6' },
  { name: 'pb', desc: '市净率', cat: '基础面', source: '东方财富daily_basic', strategies: [], unit: '倍', example: '5.27' },

  // ===== 涨跌停 (17) =====
  { name: 'is_limit_up', desc: '是否涨停(当日)', cat: '涨跌停', source: 'factor_auto_compute', strategies: ['涨停开板'], unit: '0/1', example: '0', note: 'pct_chg≥阈值(主板9.8%/科创19.8%/北交29.8%)' },
  { name: 'is_limit_down', desc: '是否跌停(当日)', cat: '涨跌停', source: 'factor_auto_compute', strategies: [], unit: '0/1', example: '0' },
  { name: 'first_limit_up', desc: '是否首板(首次涨停且非连板)', cat: '涨跌停', source: 'factor_auto_compute', strategies: ['首板打板'], unit: '0/1', example: '0', note: 'is_limit_up=1 且 limit_up_yesterday=0' },
  { name: 'first_limit_down', desc: '是否首跌(首次跌停且非连跌)', cat: '涨跌停', source: 'factor_auto_compute', strategies: [], unit: '0/1', example: '0' },
  { name: 'limit_up_count', desc: '近5日涨停次数', cat: '涨跌停', source: 'factor_auto_compute', strategies: ['龙头低吸'], unit: '次', example: '0', note: '滚动5日计数，龙头低吸要求≥2' },
  { name: 'limit_down_count', desc: '近5日跌停次数', cat: '涨跌停', source: 'factor_auto_compute', strategies: [], unit: '次', example: '0' },
  { name: 'limit_up_yesterday', desc: '昨日是否涨停', cat: '涨跌停', source: 'factor_auto_compute', strategies: ['首板打板', '涨停开板'], unit: '0/1', example: '0' },
  { name: 'limit_down_yesterday', desc: '昨日是否跌停', cat: '涨跌停', source: 'factor_auto_compute', strategies: ['跌停翘板'], unit: '0/1', example: '0' },
  { name: 'open_above_limit_down', desc: '开盘高于跌停价', cat: '涨跌停', source: 'factor_auto_compute', strategies: ['跌停翘板'], unit: '0/1', example: '0', note: '翘板信号：低开但高于跌停价=有资金抄底' },
  { name: 'open_below_limit', desc: '开盘低于涨停价', cat: '涨跌停', source: 'factor_auto_compute', strategies: [], unit: '0/1', example: '0', note: '之前语义bug已修复' },
  { name: 'limit_up_open_count', desc: '涨停开板次数', cat: '涨跌停', source: '日线估算⚠️', strategies: ['涨停开板'], unit: '次', example: '0', note: '日线数据大部分为0，盘中数据更准' },
  { name: 'limit_up_open_duration', desc: '涨停开板持续时间(分钟)', cat: '涨跌停', source: '日线估算⚠️', strategies: ['涨停开板'], unit: '分钟', example: '0', note: '日线数据大部分为0' },
  { name: 'limit_up_time', desc: '封板时间(分钟)', cat: '涨跌停', source: '日线估算⚠️', strategies: [], unit: '分钟', example: '0', note: '日线数据大部分为0' },
  { name: 'limit_up_open_amount', desc: '涨停封单金额', cat: '涨跌停', source: '日线估算⚠️', strategies: ['首板打板'], unit: '元', example: '0', note: '日线数据大部分为0' },
  { name: 'limit_down_open_amount', desc: '跌停封单金额', cat: '涨跌停', source: '日线估算⚠️', strategies: ['跌停翘板'], unit: '元', example: '0', note: '日线数据大部分为0' },
  { name: 'hot_sector', desc: '是否热门板块', cat: '涨跌停', source: '日线估算⚠️', strategies: ['首板打板'], unit: '0/1', example: '0', note: '日线数据大部分为0' },
  { name: 'market_leader', desc: '是否市场龙头', cat: '涨跌停', source: '全0❌不可用', strategies: [], unit: '0/1', example: '0', note: '全部为0，因子不可用' },

  // ===== 开盘/盘中 (4) =====
  { name: 'opening_pct_chg', desc: '开盘涨幅(%)=(open-pre_close)/pre_close', cat: '开盘/盘中', source: 'factor_auto_compute', strategies: ['首板打板'], unit: '%', example: '0.43', note: '首板打板需竞价≥2%' },
  { name: 'intraday_max_rise_pct', desc: '盘中最高涨幅(%)=(high-pre_close)/pre_close', cat: '开盘/盘中', source: 'factor_auto_compute', strategies: ['半路追涨'], unit: '%', example: '0.85', note: '半路追涨核心因子：3%~7%' },
  { name: 'intraday_open_rise_pct', desc: '开盘涨幅(=opening_pct_chg)', cat: '开盘/盘中', source: 'factor_auto_compute', strategies: ['半路追涨'], unit: '%', example: '0.43' },
  { name: 'amplitude', desc: '振幅(%)=(high-low)/pre_close', cat: '开盘/盘中', source: 'factor_auto_compute', strategies: [], unit: '%', example: '5.23' },

  // ===== 回调因子 (3) =====
  { name: 'pullback_pct', desc: '回调幅度=(close-20日high)/high,负数=回调', cat: '回调因子', source: 'factor_auto_compute', strategies: ['龙头低吸'], unit: '比例', example: '-0.093', note: '⚠️之前符号bug: 条件写>=0.05但值是负数,已修复为<=-0.05' },
  { name: 'pullback_days', desc: '回调天数(距20日内最高价)', cat: '回调因子', source: 'factor_auto_compute', strategies: ['龙头低吸'], unit: '天', example: '43' },
  { name: 'pullback_ma5', desc: '回调至MA5支撑', cat: '回调因子', source: 'factor_auto_compute⚠️', strategies: ['龙头低吸'], unit: '0/1', example: '0', note: '数据质量差，大部分为0' },

  // ===== 均线 (4) =====
  { name: 'ma5', desc: '5日均线', cat: '均线', source: 'factor_auto_compute', strategies: [], unit: '元', example: '9.396' },
  { name: 'ma10', desc: '10日均线', cat: '均线', source: 'factor_auto_compute', strategies: [], unit: '元', example: '9.549' },
  { name: 'ma20', desc: '20日均线', cat: '均线', source: 'factor_auto_compute', strategies: [], unit: '元', example: '9.775' },
  { name: 'ma60', desc: '60日均线', cat: '均线', source: 'factor_auto_compute', strategies: ['半路追涨'], unit: '元', example: '10.29', note: '半路追涨要求close>ma60(趋势过滤)' },

  // ===== Talib技术 (15) =====
  { name: 'macd', desc: 'MACD线(12,26,9)', cat: 'Talib技术', source: 'talib.MACD', strategies: [], unit: '', example: '-0.284' },
  { name: 'macd_signal', desc: 'MACD信号线', cat: 'Talib技术', source: 'talib.MACD', strategies: [], unit: '', example: '-0.241' },
  { name: 'macd_hist', desc: 'MACD柱状图(MACD-信号线)', cat: 'Talib技术', source: 'talib.MACD', strategies: [], unit: '', example: '-0.043' },
  { name: 'ema12', desc: '12日指数移动平均', cat: 'Talib技术', source: 'talib.EMA', strategies: [], unit: '元', example: '9.545' },
  { name: 'ema26', desc: '26日指数移动平均', cat: 'Talib技术', source: 'talib.EMA', strategies: [], unit: '元', example: '9.829' },
  { name: 'rsi_6', desc: '6日RSI', cat: 'Talib技术', source: 'talib.RSI', strategies: [], unit: '', example: '21.83' },
  { name: 'rsi_12', desc: '12日RSI', cat: 'Talib技术', source: 'talib.RSI', strategies: [], unit: '', example: '28.82' },
  { name: 'rsi_24', desc: '24日RSI', cat: 'Talib技术', source: 'talib.RSI', strategies: [], unit: '', example: '35.62' },
  { name: 'boll_upper', desc: '布林带上轨(20日,2σ)', cat: 'Talib技术', source: 'talib.BBANDS', strategies: [], unit: '元', example: '10.64' },
  { name: 'boll_mid', desc: '布林带中轨(=MA20)', cat: 'Talib技术', source: 'talib.BBANDS', strategies: [], unit: '元', example: '9.78' },
  { name: 'boll_lower', desc: '布林带下轨', cat: 'Talib技术', source: 'talib.BBANDS', strategies: [], unit: '元', example: '8.91' },
  { name: 'atr', desc: '14日平均真实波幅', cat: 'Talib技术', source: 'talib.ATR', strategies: [], unit: '元', example: '0.28' },
  { name: 'natr', desc: '归一化ATR(%)', cat: 'Talib技术', source: 'talib.NATR', strategies: [], unit: '%', example: '3.13' },
  { name: 'trange', desc: '真实波幅(True Range)', cat: 'Talib技术', source: 'talib.TRANGE', strategies: [], unit: '元', example: '0.49' },
  { name: 'rise_after_limit_down', desc: '跌停后反弹幅度', cat: 'Talib技术', source: '日线估算⚠️', strategies: ['跌停翘板'], unit: '比例', example: '0', note: '日线数据大部分为0' },

  // ===== 动量/波动 (7) =====
  { name: 'momentum_1d', desc: '1日动量(=pct_chg)', cat: '动量/波动', source: 'factor_auto_compute', strategies: [], unit: '%', example: '-4.38' },
  { name: 'momentum_5d', desc: '5日动量(5日涨跌幅)', cat: '动量/波动', source: 'factor_auto_compute', strategies: [], unit: '%', example: '-5.68' },
  { name: 'momentum_10d', desc: '10日动量', cat: '动量/波动', source: 'factor_auto_compute', strategies: [], unit: '%', example: '-7.05' },
  { name: 'momentum_20d', desc: '20日动量', cat: '动量/波动', source: 'factor_auto_compute', strategies: [], unit: '%', example: '-13.76' },
  { name: 'volatility_5d', desc: '5日波动率', cat: '动量/波动', source: 'factor_auto_compute', strategies: [], unit: '%', example: '2.45' },
  { name: 'volatility_10d', desc: '10日波动率', cat: '动量/波动', source: 'factor_auto_compute', strategies: [], unit: '%', example: '2.07' },
  { name: 'volatility_20d', desc: '20日波动率', cat: '动量/波动', source: 'factor_auto_compute', strategies: [], unit: '%', example: '2.25' },

  // ===== 复合因子 (2) =====
  { name: 'fear_greed_index', desc: '恐贪指数(0=极度恐惧~100=极度贪婪)', cat: '复合因子', source: 'RSI+量比+动量+波动综合', strategies: [], unit: '', example: '2.26' },
  { name: 'sentiment_score', desc: '情绪评分(个股级,大部分0.5填充)⚠️', cat: '复合因子', source: 'factor_auto_compute⚠️', strategies: [], unit: '', example: '0.40', note: '个股级大部分为0.5(std=0)，回测用市场级sentiment替代' },

  // ===== 辅助 (4) =====
  { name: 'turnover_5d_avg', desc: '5日平均换手率', cat: '辅助', source: 'factor_auto_compute', strategies: [], unit: '%', example: '2.05' },
  { name: 'turnover_20d_avg', desc: '20日平均换手率', cat: '辅助', source: 'factor_auto_compute', strategies: [], unit: '%', example: '2.66' },
  { name: 'volume_increase', desc: '放量标记', cat: '辅助', source: 'factor_auto_compute', strategies: [], unit: '0/1', example: '0' },
  { name: 'amount_20d', desc: '20日平均成交额', cat: '辅助', source: 'factor_auto_compute', strategies: [], unit: '元', example: '1.82亿' },
]

const searchQuery = ref('')
const catFilter = ref('')

const categories = [...new Set(allFactors.map(f => f.cat))]

const filteredFactors = computed(() => {
  const q = searchQuery.value.toLowerCase()
  const cat = catFilter.value
  return allFactors.filter(f => {
    if (cat && f.cat !== cat) return false
    if (!q) return true
    return f.name.toLowerCase().includes(q) ||
           f.desc.toLowerCase().includes(q) ||
           f.strategies.some(s => s.includes(q)) ||
           f.source.toLowerCase().includes(q)
  })
})

// 被策略使用的因子数量
const strategyUsedCount = computed(() => allFactors.filter(f => f.strategies.length > 0).length)
const warningCount = computed(() => allFactors.filter(f => f.source.includes('⚠️') || f.source.includes('❌')).length)

function catTagType(cat: string) {
  const map: Record<string, string> = {
    '行情原始': '', '基础面': 'success', '涨跌停': 'danger',
    '开盘/盘中': 'warning', '回调因子': 'info', '均线': 'info',
    'Talib技术': 'warning', '动量/波动': 'danger', '复合因子': 'info', '辅助': 'info'
  }
  return map[cat] || 'info'
}

function sourceColor(source: string) {
  if (source.includes('❌')) return '#f56c6c'
  if (source.includes('⚠️')) return '#e6a23c'
  if (source.includes('talib')) return '#fbbf24'
  if (source.includes('东方财富') || source.includes('AKShare')) return '#67c23a'
  return '#409eff'
}

function rowClassName({ row }: { row: FactorDef }) {
  if (row.source.includes('❌')) return 'danger-row'
  if (row.source.includes('⚠️')) return 'warning-row'
  return ''
}
</script>

<template>
  <div class="factor-reference-panel">
    <!-- 顶部概览 -->
    <div class="overview-bar">
      <div class="ov-card"><div class="ov-label">因子总数</div><div class="ov-value">{{ allFactors.length }}</div></div>
      <div class="ov-card"><div class="ov-label">策略使用</div><div class="ov-value" style="color:#409eff">{{ strategyUsedCount }}</div></div>
      <div class="ov-card"><div class="ov-label">⚠️ 数据质量差</div><div class="ov-value" style="color:#e6a23c">{{ warningCount }}</div></div>
      <div class="ov-card"><div class="ov-label">分类数</div><div class="ov-value">{{ categories.length }}</div></div>
    </div>

    <!-- 搜索和过滤 -->
    <div class="filter-bar">
      <ElInput v-model="searchQuery" placeholder="搜索因子名/描述/策略名/来源..." clearable style="max-width:360px" />
      <ElSelect v-model="catFilter" placeholder="分类筛选" clearable style="width:160px">
        <ElOption v-for="c in categories" :key="c" :label="c" :value="c" />
      </ElSelect>
      <span class="filter-count">{{ filteredFactors.length }} / {{ allFactors.length }}</span>
    </div>

    <!-- 因子表格 -->
    <ElTable :data="filteredFactors" border size="small" max-height="600" :row-class-name="rowClassName" stripe>
      <ElTableColumn prop="name" label="字段名" width="200">
        <template #default="{ row }">
          <code class="field-name">{{ row.name }}</code>
        </template>
      </ElTableColumn>
      <ElTableColumn prop="desc" label="描述" min-width="220">
        <template #default="{ row }">
          <span>{{ row.desc }}</span>
          <div v-if="row.note" class="field-note">{{ row.note }}</div>
        </template>
      </ElTableColumn>
      <ElTableColumn prop="cat" label="分类" width="110">
        <template #default="{ row }">
          <ElTag size="small" :type="catTagType(row.cat)">{{ row.cat }}</ElTag>
        </template>
      </ElTableColumn>
      <ElTableColumn prop="source" label="来源" width="150">
        <template #default="{ row }">
          <span :style="{ color: sourceColor(row.source), fontSize: '12px' }">{{ row.source }}</span>
        </template>
      </ElTableColumn>
      <ElTableColumn prop="strategies" label="策略用途" width="140">
        <template #default="{ row }">
          <ElTag v-for="s in row.strategies" :key="s" size="small" type="warning" style="margin:1px">{{ s }}</ElTag>
          <span v-if="row.strategies.length===0" style="color:#c0c4cc;font-size:11px">-</span>
        </template>
      </ElTableColumn>
      <ElTableColumn prop="example" label="示例值" width="100">
        <template #default="{ row }">
          <code class="field-example">{{ row.example }}</code>
        </template>
      </ElTableColumn>
    </ElTable>
  </div>
</template>

<style scoped lang="scss">
.factor-reference-panel { padding: 0; }

.overview-bar {
  display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap;
}
.ov-card {
  padding: 12px 20px; border-radius: 8px; background: #f5f7fa;
  min-width: 100px; text-align: center;
}
.ov-label { font-size: 11px; color: #909399; }
.ov-value { font-size: 22px; font-weight: 700; color: #303133; margin-top: 2px; }

.filter-bar {
  display: flex; gap: 12px; align-items: center; margin-bottom: 12px;
}
.filter-count { font-size: 12px; color: #909399; }

.field-name { font-size: 12px; color: #409eff; font-family: 'SF Mono', 'Fira Code', monospace; }
.field-example { font-size: 11px; color: #909399; font-family: monospace; }
.field-note { font-size: 11px; color: #e6a23c; margin-top: 2px; line-height: 1.4; }

:deep(.warning-row) { background-color: #fdf6ec !important; }
:deep(.danger-row) { background-color: #fef0f0 !important; }
</style>
