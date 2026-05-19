<script setup lang="ts">
/**
 * 因子参考面板 V2 — 按分类卡片展示，带搜索/筛选/展开折叠
 */
import { ref, computed } from 'vue'
import { ElInput, ElTag, ElSelect, ElOption, ElCollapse, ElCollapseItem, ElTooltip, ElEmpty } from 'element-plus'
import { Search, Warning, CircleCheck, DataLine, TrendCharts, Cpu } from '@element-plus/icons-vue'

interface FactorDef {
  name: string
  desc: string
  cat: string
  source: string
  strategies: string[]
  unit: string
  example: string
  note?: string
  quality?: 'good' | 'warn' | 'bad'  // 数据质量
}

const allFactors: FactorDef[] = [
  // ===== 行情原始 (9) =====
  { name: 'open', desc: '开盘价', cat: '行情原始', source: 'AKShare/东方财富', strategies: [], unit: '元', example: '9.41', quality: 'good' },
  { name: 'high', desc: '最高价', cat: '行情原始', source: 'AKShare/东方财富', strategies: ['半路追涨'], unit: '元', example: '9.45', quality: 'good' },
  { name: 'low', desc: '最低价', cat: '行情原始', source: 'AKShare/东方财富', strategies: [], unit: '元', example: '8.96', quality: 'good' },
  { name: 'close', desc: '收盘价', cat: '行情原始', source: 'AKShare/东方财富', strategies: [], unit: '元', example: '8.96', quality: 'good' },
  { name: 'pre_close', desc: '前收盘价', cat: '行情原始', source: 'AKShare/东方财富', strategies: [], unit: '元', example: '9.37', quality: 'good' },
  { name: 'pct_chg', desc: '涨跌幅', cat: '行情原始', source: 'AKShare/东方财富', strategies: ['半路追涨'], unit: '%', example: '-4.38', quality: 'good' },
  { name: 'change', desc: '涨跌额', cat: '行情原始', source: 'AKShare/东方财富', strategies: [], unit: '元', example: '-0.41', quality: 'good' },
  { name: 'vol', desc: '成交量', cat: '行情原始', source: 'AKShare/东方财富', strategies: [], unit: '股', example: '20294181', quality: 'good' },
  { name: 'amount', desc: '成交额', cat: '行情原始', source: 'AKShare/东方财富', strategies: [], unit: '元', example: '1.86亿', quality: 'good' },

  // ===== 基础面 (5) =====
  { name: 'turnover_rate', desc: '换手率', cat: '基础面', source: '东方财富 daily_basic', strategies: ['首板打板', '跌停翘板'], unit: '%', example: '2.92', quality: 'good' },
  { name: 'volume_ratio', desc: '量比(当日成交/5日均量)', cat: '基础面', source: '自动计算', strategies: ['半路追涨', '龙头低吸'], unit: '倍', example: '1.5', quality: 'good' },
  { name: 'circ_mv', desc: '流通市值', cat: '基础面', source: '东方财富 daily_basic', strategies: ['首板打板', '龙头低吸', '跌停翘板'], unit: '万元', example: '620000', quality: 'good' },
  { name: 'pe_ttm', desc: '滚动市盈率(TTM)', cat: '基础面', source: '东方财富 daily_basic', strategies: [], unit: '倍', example: '154.6', quality: 'good' },
  { name: 'pb', desc: '市净率', cat: '基础面', source: '东方财富 daily_basic', strategies: [], unit: '倍', example: '5.27', quality: 'good' },

  // ===== 涨跌停 (17) =====
  { name: 'is_limit_up', desc: '是否涨停(当日)', cat: '涨跌停', source: '自动计算', strategies: ['涨停开板'], unit: '0/1', example: '0', note: 'pct_chg≥阈值(主板9.8%/科创19.8%/北交29.8%)', quality: 'good' },
  { name: 'is_limit_down', desc: '是否跌停(当日)', cat: '涨跌停', source: '自动计算', strategies: [], unit: '0/1', example: '0', quality: 'good' },
  { name: 'first_limit_up', desc: '是否首板(首次涨停且非连板)', cat: '涨跌停', source: '自动计算', strategies: ['首板打板'], unit: '0/1', example: '0', note: 'is_limit_up=1 且 limit_up_yesterday=0', quality: 'good' },
  { name: 'first_limit_down', desc: '是否首跌(首次跌停且非连跌)', cat: '涨跌停', source: '自动计算', strategies: [], unit: '0/1', example: '0', quality: 'good' },
  { name: 'limit_up_count', desc: '近5日涨停次数', cat: '涨跌停', source: '自动计算', strategies: ['龙头低吸'], unit: '次', example: '0', note: '龙头低吸要求≥2', quality: 'good' },
  { name: 'limit_down_count', desc: '近5日跌停次数', cat: '涨跌停', source: '自动计算', strategies: [], unit: '次', example: '0', quality: 'good' },
  { name: 'limit_up_yesterday', desc: '昨日是否涨停', cat: '涨跌停', source: '自动计算', strategies: ['首板打板', '涨停开板'], unit: '0/1', example: '0', quality: 'good' },
  { name: 'limit_down_yesterday', desc: '昨日是否跌停', cat: '涨跌停', source: '自动计算', strategies: ['跌停翘板'], unit: '0/1', example: '0', quality: 'good' },
  { name: 'open_above_limit_down', desc: '开盘高于跌停价', cat: '涨跌停', source: '自动计算', strategies: ['跌停翘板'], unit: '0/1', example: '0', note: '翘板信号：低开但高于跌停价=有资金抄底', quality: 'good' },
  { name: 'open_below_limit', desc: '开盘低于涨停价', cat: '涨跌停', source: '自动计算', strategies: [], unit: '0/1', example: '0', quality: 'good' },
  { name: 'limit_up_open_count', desc: '涨停开板次数', cat: '涨跌停', source: '日线估算', strategies: ['涨停开板'], unit: '次', example: '0', note: '日线数据大部分为0，盘中数据更准', quality: 'warn' },
  { name: 'limit_up_open_duration', desc: '涨停开板持续时间', cat: '涨跌停', source: '日线估算', strategies: ['涨停开板'], unit: '分钟', example: '0', note: '日线数据大部分为0', quality: 'warn' },
  { name: 'limit_up_time', desc: '封板时间', cat: '涨跌停', source: '日线估算', strategies: [], unit: '分钟', example: '0', note: '日线数据大部分为0', quality: 'warn' },
  { name: 'limit_up_open_amount', desc: '涨停封单金额', cat: '涨跌停', source: '日线估算', strategies: ['首板打板'], unit: '元', example: '0', note: '日线数据大部分为0', quality: 'warn' },
  { name: 'limit_down_open_amount', desc: '跌停封单金额', cat: '涨跌停', source: '日线估算', strategies: ['跌停翘板'], unit: '元', example: '0', note: '日线数据大部分为0', quality: 'warn' },
  { name: 'hot_sector', desc: '是否热门板块', cat: '涨跌停', source: '日线估算', strategies: ['首板打板'], unit: '0/1', example: '0', note: '日线数据大部分为0', quality: 'warn' },
  { name: 'market_leader', desc: '是否市场龙头', cat: '涨跌停', source: '不可用', strategies: [], unit: '0/1', example: '0', note: '全部为0，因子不可用', quality: 'bad' },

  // ===== 开盘/盘中 (4) =====
  { name: 'opening_pct_chg', desc: '竞价涨幅=(open-pre_close)/pre_close', cat: '开盘/盘中', source: '自动计算', strategies: ['首板打板'], unit: '%', example: '0.43', note: '首板打板需竞价≥2%', quality: 'good' },
  { name: 'intraday_max_rise_pct', desc: '盘中最高涨幅=(high-pre_close)/pre_close', cat: '开盘/盘中', source: '自动计算', strategies: ['半路追涨'], unit: '%', example: '0.85', note: '半路追涨核心因子：3%~7%', quality: 'good' },
  { name: 'intraday_open_rise_pct', desc: '开盘涨幅(同opening_pct_chg)', cat: '开盘/盘中', source: '自动计算', strategies: ['半路追涨'], unit: '%', example: '0.43', quality: 'good' },
  { name: 'amplitude', desc: '振幅=(high-low)/pre_close', cat: '开盘/盘中', source: '自动计算', strategies: [], unit: '%', example: '5.23', quality: 'good' },

  // ===== 回调因子 (3) =====
  { name: 'pullback_pct', desc: '回调幅度=(close-20日high)/high', cat: '回调因子', source: '自动计算', strategies: ['龙头低吸'], unit: '小数', example: '-0.093', note: '⚠️ 负数=回调，龙头低吸需≤-0.05(回调≥5%)', quality: 'good' },
  { name: 'pullback_days', desc: '回调天数(距20日内最高价)', cat: '回调因子', source: '自动计算', strategies: ['龙头低吸'], unit: '天', example: '43', quality: 'good' },
  { name: 'pullback_ma5', desc: '回调至MA5支撑', cat: '回调因子', source: '自动计算', strategies: ['龙头低吸'], unit: '0/1', example: '0', note: '数据质量差，大部分为0', quality: 'warn' },

  // ===== 均线 (4) =====
  { name: 'ma5', desc: '5日均线', cat: '均线', source: '自动计算', strategies: [], unit: '元', example: '9.396', quality: 'good' },
  { name: 'ma10', desc: '10日均线', cat: '均线', source: '自动计算', strategies: [], unit: '元', example: '9.549', quality: 'good' },
  { name: 'ma20', desc: '20日均线', cat: '均线', source: '自动计算', strategies: [], unit: '元', example: '9.775', quality: 'good' },
  { name: 'ma60', desc: '60日均线(趋势过滤)', cat: '均线', source: '自动计算', strategies: ['半路追涨'], unit: '元', example: '10.29', note: 'close>ma60表示中期趋势向上', quality: 'good' },

  // ===== Talib技术 (15) =====
  { name: 'macd', desc: 'MACD线(12,26,9)', cat: 'Talib技术', source: 'talib', strategies: [], unit: '', example: '-0.284', quality: 'good' },
  { name: 'macd_signal', desc: 'MACD信号线', cat: 'Talib技术', source: 'talib', strategies: [], unit: '', example: '-0.241', quality: 'good' },
  { name: 'macd_hist', desc: 'MACD柱状图(DIF-DEA)', cat: 'Talib技术', source: 'talib', strategies: [], unit: '', example: '-0.043', quality: 'good' },
  { name: 'ema12', desc: '12日指数移动平均', cat: 'Talib技术', source: 'talib', strategies: [], unit: '元', example: '9.545', quality: 'good' },
  { name: 'ema26', desc: '26日指数移动平均', cat: 'Talib技术', source: 'talib', strategies: [], unit: '元', example: '9.829', quality: 'good' },
  { name: 'rsi_6', desc: '6日RSI', cat: 'Talib技术', source: 'talib', strategies: [], unit: '', example: '21.83', quality: 'good' },
  { name: 'rsi_12', desc: '12日RSI', cat: 'Talib技术', source: 'talib', strategies: [], unit: '', example: '28.82', quality: 'good' },
  { name: 'rsi_24', desc: '24日RSI', cat: 'Talib技术', source: 'talib', strategies: [], unit: '', example: '35.62', quality: 'good' },
  { name: 'boll_upper', desc: '布林带上轨(20日,2σ)', cat: 'Talib技术', source: 'talib', strategies: [], unit: '元', example: '10.64', quality: 'good' },
  { name: 'boll_mid', desc: '布林带中轨(=MA20)', cat: 'Talib技术', source: 'talib', strategies: [], unit: '元', example: '9.78', quality: 'good' },
  { name: 'boll_lower', desc: '布林带下轨', cat: 'Talib技术', source: 'talib', strategies: [], unit: '元', example: '8.91', quality: 'good' },
  { name: 'atr', desc: '14日平均真实波幅', cat: 'Talib技术', source: 'talib', strategies: [], unit: '元', example: '0.28', quality: 'good' },
  { name: 'natr', desc: '归一化ATR(%)', cat: 'Talib技术', source: 'talib', strategies: [], unit: '%', example: '3.13', quality: 'good' },
  { name: 'trange', desc: '真实波幅(True Range)', cat: 'Talib技术', source: 'talib', strategies: [], unit: '元', example: '0.49', quality: 'good' },
  { name: 'rise_after_limit_down', desc: '跌停后反弹幅度', cat: 'Talib技术', source: '日线估算', strategies: ['跌停翘板'], unit: '%', example: '0', note: '日线数据大部分为0', quality: 'warn' },

  // ===== 动量/波动 (7) =====
  { name: 'momentum_1d', desc: '1日动量(=pct_chg)', cat: '动量/波动', source: '自动计算', strategies: [], unit: '%', example: '-4.38', quality: 'good' },
  { name: 'momentum_5d', desc: '5日动量(5日涨跌幅)', cat: '动量/波动', source: '自动计算', strategies: [], unit: '%', example: '-5.68', quality: 'good' },
  { name: 'momentum_10d', desc: '10日动量', cat: '动量/波动', source: '自动计算', strategies: [], unit: '%', example: '-7.05', quality: 'good' },
  { name: 'momentum_20d', desc: '20日动量', cat: '动量/波动', source: '自动计算', strategies: [], unit: '%', example: '-13.76', quality: 'good' },
  { name: 'volatility_5d', desc: '5日波动率', cat: '动量/波动', source: '自动计算', strategies: [], unit: '%', example: '2.45', quality: 'good' },
  { name: 'volatility_10d', desc: '10日波动率', cat: '动量/波动', source: '自动计算', strategies: [], unit: '%', example: '2.07', quality: 'good' },
  { name: 'volatility_20d', desc: '20日波动率', cat: '动量/波动', source: '自动计算', strategies: [], unit: '%', example: '2.25', quality: 'good' },

  // ===== 复合因子 (2) =====
  { name: 'fear_greed_index', desc: '恐贪指数(0=极度恐惧~100=极度贪婪)', cat: '复合因子', source: 'RSI+量比+动量+波动综合', strategies: [], unit: '', example: '2.26', quality: 'good' },
  { name: 'sentiment_score', desc: '情绪评分(个股级)', cat: '复合因子', source: '自动计算', strategies: [], unit: '', example: '0.40', note: '个股级大部分为0.5(std=0)，回测用市场级sentiment替代', quality: 'warn' },

  // ===== 辅助 (4) =====
  { name: 'turnover_5d_avg', desc: '5日平均换手率', cat: '辅助', source: '自动计算', strategies: [], unit: '%', example: '2.05', quality: 'good' },
  { name: 'turnover_20d_avg', desc: '20日平均换手率', cat: '辅助', source: '自动计算', strategies: [], unit: '%', example: '2.66', quality: 'good' },
  { name: 'volume_increase', desc: '放量标记', cat: '辅助', source: '自动计算', strategies: [], unit: '0/1', example: '0', quality: 'good' },
  { name: 'amount_20d', desc: '20日平均成交额', cat: '辅助', source: '自动计算', strategies: [], unit: '元', example: '1.82亿', quality: 'good' },
]

// ===== 分类元信息 =====
const catMeta: Record<string, { icon: string; color: string; desc: string }> = {
  '行情原始':  { icon: '📊', color: '#409eff', desc: 'OHLCV等基础行情数据，来自AKShare/东方财富' },
  '基础面':    { icon: '💰', color: '#67c23a', desc: '换手率/量比/市值等基本面指标' },
  '涨跌停':    { icon: '🚦', color: '#f56c6c', desc: '涨停/跌停/开板/封单等涨跌停相关因子' },
  '开盘/盘中': { icon: '⏰', color: '#e6a23c', desc: '竞价涨幅/盘中最高涨幅/振幅等开盘盘中因子' },
  '回调因子':  { icon: '📉', color: '#909399', desc: '回调幅度/天数/均线支撑等回调相关因子' },
  '均线':      { icon: '📈', color: '#b37feb', desc: 'MA5/10/20/60均线，用于趋势判断' },
  'Talib技术': { icon: '🔬', color: '#fbbf24', desc: 'MACD/RSI/布林带/ATR等技术指标' },
  '动量/波动': { icon: '⚡', color: '#ff7a45', desc: 'N日动量/N日波动率等动量波动因子' },
  '复合因子':  { icon: '🧠', color: '#597ef7', desc: '恐贪指数/情绪评分等综合因子' },
  '辅助':      { icon: '🔧', color: '#8c8c8c', desc: '平均换手率/放量标记/平均成交额等辅助字段' },
}

const searchQuery = ref('')
const catFilter = ref('')
const activeCollapse = ref<string[]>(Object.keys(catMeta))

const categories = [...new Set(allFactors.map(f => f.cat))]

// 按分类分组
const groupedFactors = computed(() => {
  const groups: Record<string, FactorDef[]> = {}
  for (const f of filteredFactors.value) {
    if (!groups[f.cat]) groups[f.cat] = []
    groups[f.cat].push(f)
  }
  return groups
})

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

const strategyUsedCount = computed(() => allFactors.filter(f => f.strategies.length > 0).length)
const warnCount = computed(() => allFactors.filter(f => f.quality === 'warn').length)
const badCount = computed(() => allFactors.filter(f => f.quality === 'bad').length)

function qualityIcon(q?: string) {
  if (q === 'bad') return '❌'
  if (q === 'warn') return '⚠️'
  return '✅'
}
function qualityClass(q?: string) {
  if (q === 'bad') return 'quality-bad'
  if (q === 'warn') return 'quality-warn'
  return 'quality-good'
}
</script>

<template>
  <div class="factor-ref-v2">
    <!-- 顶部统计卡片 -->
    <div class="stat-row">
      <div class="stat-card">
        <div class="stat-num">{{ allFactors.length }}</div>
        <div class="stat-label">因子总数</div>
      </div>
      <div class="stat-card accent">
        <div class="stat-num">{{ strategyUsedCount }}</div>
        <div class="stat-label">策略使用</div>
      </div>
      <div class="stat-card warn">
        <div class="stat-num">{{ warnCount }}</div>
        <div class="stat-label">⚠️ 数据质量差</div>
      </div>
      <div class="stat-card bad" v-if="badCount > 0">
        <div class="stat-num">{{ badCount }}</div>
        <div class="stat-label">❌ 不可用</div>
      </div>
    </div>

    <!-- 搜索栏 -->
    <div class="search-bar">
      <ElInput v-model="searchQuery" placeholder="搜索因子名/描述/策略..." clearable prefix-icon="Search" style="max-width:320px" size="default" />
      <ElSelect v-model="catFilter" placeholder="全部分类" clearable style="width:150px" size="default">
        <ElOption v-for="c in categories" :key="c" :label="c" :value="c" />
      </ElSelect>
      <span class="result-count">匹配 {{ filteredFactors.length }} / {{ allFactors.length }}</span>
    </div>

    <!-- 无结果 -->
    <ElEmpty v-if="filteredFactors.length === 0" description="无匹配因子" :image-size="80" />

    <!-- 按分类折叠展示 -->
    <ElCollapse v-model="activeCollapse" class="factor-collapse">
      <ElCollapseItem v-for="(factors, cat) in groupedFactors" :key="cat" :name="cat">
        <template #title>
          <div class="cat-title">
            <span class="cat-icon">{{ catMeta[cat]?.icon || '📋' }}</span>
            <span class="cat-name">{{ cat }}</span>
            <span class="cat-count">{{ factors.length }}个</span>
            <span class="cat-desc">{{ catMeta[cat]?.desc }}</span>
            <span v-if="factors.some(f => f.quality === 'warn')" class="cat-warn-badge">⚠️</span>
          </div>
        </template>
        <div class="factor-grid">
          <div v-for="f in factors" :key="f.name" class="factor-card" :class="qualityClass(f.quality)">
            <div class="factor-header">
              <code class="factor-name">{{ f.name }}</code>
              <span class="quality-badge">{{ qualityIcon(f.quality) }}</span>
            </div>
            <div class="factor-desc">{{ f.desc }}</div>
            <div class="factor-meta">
              <span class="meta-item">
                <span class="meta-label">来源</span>
                <span class="meta-value" :class="{ 'src-warn': f.quality === 'warn', 'src-bad': f.quality === 'bad' }">{{ f.source }}</span>
              </span>
              <span class="meta-item">
                <span class="meta-label">单位</span>
                <span class="meta-value">{{ f.unit }}</span>
              </span>
              <span class="meta-item">
                <span class="meta-label">示例</span>
                <code class="meta-value example">{{ f.example }}</code>
              </span>
            </div>
            <div v-if="f.strategies.length > 0" class="factor-strategies">
              <ElTag v-for="s in f.strategies" :key="s" size="small" type="warning" effect="plain">{{ s }}</ElTag>
            </div>
            <div v-if="f.note" class="factor-note">{{ f.note }}</div>
          </div>
        </div>
      </ElCollapseItem>
    </ElCollapse>
  </div>
</template>

<style scoped lang="scss">
.factor-ref-v2 { padding: 0; }

/* 统计卡片 */
.stat-row { display: flex; gap: 10px; margin-bottom: 16px; }
.stat-card {
  padding: 10px 20px; border-radius: 8px; background: #f5f7fa; min-width: 80px; text-align: center;
  &.accent { background: #ecf5ff; .stat-num { color: #409eff; } }
  &.warn { background: #fdf6ec; .stat-num { color: #e6a23c; } }
  &.bad { background: #fef0f0; .stat-num { color: #f56c6c; } }
}
.stat-num { font-size: 20px; font-weight: 700; color: #303133; }
.stat-label { font-size: 11px; color: #909399; margin-top: 2px; }

/* 搜索栏 */
.search-bar { display: flex; gap: 10px; align-items: center; margin-bottom: 16px; }
.result-count { font-size: 12px; color: #909399; }

/* 折叠面板 */
.factor-collapse {
  border: none;
  :deep(.el-collapse-item__header) { background: #fafafa; border-radius: 6px; padding: 0 12px; margin-bottom: 6px; border: 1px solid #ebeef5; }
  :deep(.el-collapse-item__wrap) { border: none; background: transparent; }
  :deep(.el-collapse-item__content) { padding: 8px 0 16px; }
}

/* 分类标题 */
.cat-title { display: flex; align-items: center; gap: 8px; }
.cat-icon { font-size: 16px; }
.cat-name { font-weight: 600; font-size: 14px; }
.cat-count { font-size: 11px; color: #909399; background: #f0f2f5; padding: 1px 8px; border-radius: 10px; }
.cat-desc { font-size: 12px; color: #909399; }
.cat-warn-badge { font-size: 12px; }

/* 因子网格 */
.factor-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 10px;
}

/* 因子卡片 */
.factor-card {
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid #ebeef5;
  background: #fff;
  transition: box-shadow 0.2s;
  &:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.08); }

  &.quality-warn { border-color: #faeccd; background: #fffbf0; }
  &.quality-bad { border-color: #fbc4c4; background: #fff5f5; }
}

.factor-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.factor-name { font-size: 13px; color: #409eff; font-family: 'SF Mono', 'Fira Code', Consolas, monospace; font-weight: 600; }
.quality-badge { font-size: 11px; }

.factor-desc { font-size: 12px; color: #606266; line-height: 1.5; margin-bottom: 6px; }

.factor-meta { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 6px; }
.meta-item { font-size: 11px; }
.meta-label { color: #c0c4cc; margin-right: 2px; }
.meta-value { color: #606266; font-size: 11px;
  &.example { font-family: monospace; color: #909399; }
  &.src-warn { color: #e6a23c; }
  &.src-bad { color: #f56c6c; }
}

.factor-strategies { display: flex; gap: 4px; flex-wrap: wrap; margin-bottom: 4px; }

.factor-note { font-size: 11px; color: #e6a23c; background: #fdf6ec; padding: 4px 8px; border-radius: 4px; line-height: 1.5; margin-top: 4px; }
</style>
