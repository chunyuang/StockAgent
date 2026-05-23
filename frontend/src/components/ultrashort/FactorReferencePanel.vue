<script setup lang="ts">
/**
 * 因子参考面板 V3 — 紧凑表格+策略关联
 * 重点优化: 
 * 1. 补齐_prev因子(volume_ratio_prev/circ_mv_prev/pct_chg_prev/turnover_rate_prev)
 * 2. 策略筛选条件标记(哪些因子真正参与选股决策)
 * 3. 紧凑表格布局替代卡片网格(信息密度翻倍)
 * 4. 日线模式可用性标注
 */
import { ref, computed } from 'vue'
import { ElInput, ElTag, ElSelect, ElOption, ElEmpty, ElSwitch } from 'element-plus'

type Quality = 'good' | 'warn' | 'bad' | 'prev'

interface FactorDef {
  name: string
  desc: string
  cat: string
  source: string
  usedBy: string[]   // 哪些策略用这个因子做筛选
  unit: string
  example: string
  note?: string
  quality: Quality
  dailyOk: boolean   // 日线回测是否可用
}

const allFactors: FactorDef[] = [
  // ===== 行情原始 =====
  { name: 'open', desc: '开盘价', cat: '行情', source: '东方财富', usedBy: [], unit: '元', example: '9.41', quality: 'good', dailyOk: true },
  { name: 'high', desc: '最高价', cat: '行情', source: '东方财富', usedBy: ['半路追涨'], unit: '元', example: '9.45', quality: 'good', dailyOk: true },
  { name: 'low', desc: '最低价', cat: '行情', source: '东方财富', usedBy: [], unit: '元', example: '8.96', quality: 'good', dailyOk: true },
  { name: 'close', desc: '收盘价', cat: '行情', source: '东方财富', usedBy: [], unit: '元', example: '8.96', quality: 'good', dailyOk: true },
  { name: 'pre_close', desc: '前收盘价', cat: '行情', source: '东方财富', usedBy: [], unit: '元', example: '9.37', quality: 'good', dailyOk: true },
  { name: 'pct_chg', desc: '涨跌幅', cat: '行情', source: '东方财富', usedBy: ['半路追涨'], unit: '%', example: '-4.38', quality: 'good', dailyOk: true, note: '⚠半路追涨用于收盘确认,盘中不可知(未来函数)' },
  { name: 'vol', desc: '成交量', cat: '行情', source: '东方财富', usedBy: [], unit: '股', example: '20294181', quality: 'good', dailyOk: true },
  { name: 'amount', desc: '成交额', cat: '行情', source: '东方财富', usedBy: [], unit: '元', example: '1.86亿', quality: 'good', dailyOk: true },

  // ===== T-1因子(消除未来函数) =====
  { name: 'pct_chg_prev', desc: 'T-1日涨跌幅', cat: 'T-1因子', source: 'T-1日数据', usedBy: [], unit: '%', example: '-2.15', quality: 'prev', dailyOk: true, note: '替代T日pct_chg,消除未来函数。当前仅内部参考' },
  { name: 'volume_ratio_prev', desc: 'T-1日量比', cat: 'T-1因子', source: 'T-1日数据', usedBy: ['半路追涨', '首板打板', '涨停开板'], unit: '倍', example: '1.8', quality: 'prev', dailyOk: true, note: '替代T日volume_ratio,消除未来函数。半路/首板/涨停开板均用此因子' },
  { name: 'turnover_rate_prev', desc: 'T-1日换手率', cat: 'T-1因子', source: 'T-1日数据', usedBy: [], unit: '%', example: '3.5', quality: 'prev', dailyOk: true, note: '替代T日turnover_rate,当前仅内部参考' },
  { name: 'circ_mv_prev', desc: 'T-1日流通市值', cat: 'T-1因子', source: 'T-1日数据', usedBy: ['跌停翘板'], unit: '万元', example: '620000', quality: 'prev', dailyOk: true, note: '替代T日circ_mv,跌停翘板用此因子做市值筛选' },

  // ===== 基础面 =====
  { name: 'turnover_rate', desc: '换手率', cat: '基础面', source: '东方财富', usedBy: ['首板打板', '涨停开板', '跌停翘板'], unit: '%', example: '2.92', quality: 'good', dailyOk: true },
  { name: 'volume_ratio', desc: '量比(当日成交/5日均量)', cat: '基础面', source: '自动计算', usedBy: ['龙头低吸'], unit: '倍', example: '1.5', quality: 'good', dailyOk: true, note: '龙头低吸保留T日数据(T日放量启动信号)' },
  { name: 'circ_mv', desc: '流通市值', cat: '基础面', source: '东方财富', usedBy: ['首板打板', '龙头低吸'], unit: '万元', example: '620000', quality: 'good', dailyOk: true },
  { name: 'pe_ttm', desc: '滚动市盈率', cat: '基础面', source: '东方财富', usedBy: [], unit: '倍', example: '154.6', quality: 'good', dailyOk: true },
  { name: 'pb', desc: '市净率', cat: '基础面', source: '东方财富', usedBy: [], unit: '倍', example: '5.27', quality: 'good', dailyOk: true },

  // ===== 涨跌停 =====
  { name: 'is_limit_up', desc: '是否涨停(当日)', cat: '涨跌停', source: '自动计算', usedBy: ['涨停开板'], unit: '0/1', example: '0', quality: 'good', dailyOk: true, note: '涨停开板: is_limit_up=0(今日未封住)' },
  { name: 'is_limit_down', desc: '是否跌停(当日)', cat: '涨跌停', source: '自动计算', usedBy: [], unit: '0/1', example: '0', quality: 'good', dailyOk: true },
  { name: 'first_limit_up', desc: '是否首板(首次涨停且非连板)', cat: '涨跌停', source: '自动计算', usedBy: ['首板打板'], unit: '0/1', example: '1', quality: 'good', dailyOk: true, note: 'is_limit_up=1 且 limit_up_yesterday=0' },
  { name: 'limit_up_count', desc: '近5日涨停次数', cat: '涨跌停', source: '自动计算', usedBy: ['龙头低吸'], unit: '次', example: '2', quality: 'good', dailyOk: true, note: '龙头低吸要求≥1' },
  { name: 'limit_up_yesterday', desc: '昨日是否涨停', cat: '涨跌停', source: '自动计算', usedBy: ['首板打板', '涨停开板'], unit: '0/1', example: '0', quality: 'good', dailyOk: true },
  { name: 'limit_down_yesterday', desc: '昨日是否跌停', cat: '涨跌停', source: '自动计算', usedBy: ['跌停翘板'], unit: '0/1', example: '1', quality: 'good', dailyOk: true },
  { name: 'open_above_limit_down', desc: '开盘高于跌停价', cat: '涨跌停', source: '自动计算', usedBy: ['跌停翘板'], unit: '0/1', example: '1', quality: 'good', dailyOk: true, note: '翘板信号：低开但高于跌停价=有资金抄底' },
  { name: 'open_below_limit', desc: '开盘低于涨停价', cat: '涨跌停', source: '自动计算', usedBy: [], unit: '0/1', example: '0', quality: 'good', dailyOk: true },
  // 日线不可用(盘中因子)
  { name: 'limit_up_open_count', desc: '涨停开板次数', cat: '涨跌停', source: '盘中数据', usedBy: [], unit: '次', example: '0', quality: 'warn', dailyOk: false, note: '日线数据全为0,默认值填充' },
  { name: 'limit_up_open_duration', desc: '涨停开板持续时间', cat: '涨跌停', source: '盘中数据', usedBy: [], unit: '分钟', example: '0', quality: 'warn', dailyOk: false, note: '日线数据全为0,默认值填充' },
  { name: 'limit_up_time', desc: '封板时间', cat: '涨跌停', source: '盘中数据', usedBy: [], unit: '分钟', example: '0', quality: 'warn', dailyOk: false, note: '日线数据全为0,默认值填充' },
  { name: 'limit_up_open_amount', desc: '涨停封单金额', cat: '涨跌停', source: '盘中数据', usedBy: [], unit: '元', example: '0', quality: 'warn', dailyOk: false, note: '日线数据全为0,默认值填充' },
  { name: 'limit_down_open_amount', desc: '跌停封单金额', cat: '涨跌停', source: '盘中数据', usedBy: [], unit: '元', example: '0', quality: 'warn', dailyOk: false, note: '日线数据全为0,默认值填充' },
  { name: 'hot_sector', desc: '是否热门板块', cat: '涨跌停', source: '盘中数据', usedBy: [], unit: '0/1', example: '0', quality: 'warn', dailyOk: false, note: '日线数据全为0,默认值填充' },
  { name: 'market_leader', desc: '是否市场龙头', cat: '涨跌停', source: '不可用', usedBy: [], unit: '0/1', example: '0', quality: 'bad', dailyOk: false, note: '全为0,已改用circ_mv识别龙头' },
  { name: 'rise_after_limit_down', desc: '跌停后反弹幅度', cat: '涨跌停', source: '盘中数据', usedBy: [], unit: '%', example: '0', quality: 'warn', dailyOk: false, note: '日线数据全为0,默认值填充' },

  // ===== 开盘/盘中 =====
  { name: 'opening_pct_chg', desc: '竞价涨幅=(open-pre_close)/pre_close', cat: '开盘/盘中', source: 'OHLCV计算', usedBy: ['首板打板'], unit: '%', example: '0.43', quality: 'good', dailyOk: true, note: '9:25竞价可知,首板打板需竞价在-1%~7%' },
  { name: 'intraday_max_rise_pct', desc: '盘中最高涨幅=(high-pre_close)/pre_close', cat: '开盘/盘中', source: 'OHLCV计算', usedBy: ['半路追涨', '涨停开板'], unit: '%', example: '5.85', quality: 'good', dailyOk: true, note: '半路追涨核心因子：3%~7%' },
  { name: 'intraday_open_rise_pct', desc: '开盘涨幅(同opening_pct_chg)', cat: '开盘/盘中', source: 'OHLCV计算', usedBy: ['半路追涨'], unit: '%', example: '0.43', quality: 'good', dailyOk: true, note: '排除高开>3%追高' },
  { name: 'amplitude', desc: '振幅=(high-low)/pre_close', cat: '开盘/盘中', source: '自动计算', usedBy: [], unit: '%', example: '5.23', quality: 'good', dailyOk: true },

  // ===== 回调因子 =====
  { name: 'pullback_pct', desc: '回调幅度=(close-20日high)/high', cat: '回调', source: '自动计算', usedBy: ['龙头低吸'], unit: '小数', example: '-0.093', quality: 'good', dailyOk: true, note: '负数=回调,龙头低吸需-0.35~-0.05(回调5%~35%)' },
  { name: 'pullback_days', desc: '回调天数(距20日内最高价)', cat: '回调', source: '自动计算', usedBy: ['龙头低吸'], unit: '天', example: '3', quality: 'good', dailyOk: true },
  { name: 'pullback_ma5', desc: '回调至MA5支撑', cat: '回调', source: '自动计算', usedBy: [], unit: '0/1', example: '0', quality: 'warn', dailyOk: true, note: '数据质量差,已不强制要求' },

  // ===== 均线 =====
  { name: 'ma5', desc: '5日均线', cat: '均线', source: '自动计算', usedBy: [], unit: '元', example: '9.396', quality: 'good', dailyOk: true },
  { name: 'ma10', desc: '10日均线', cat: '均线', source: '自动计算', usedBy: [], unit: '元', example: '9.549', quality: 'good', dailyOk: true },
  { name: 'ma20', desc: '20日均线', cat: '均线', source: '自动计算', usedBy: [], unit: '元', example: '9.775', quality: 'good', dailyOk: true },
  { name: 'ma60', desc: '60日均线(趋势过滤)', cat: '均线', source: '自动计算', usedBy: [], unit: '元', example: '10.29', quality: 'good', dailyOk: true },

  // ===== 技术指标 =====
  { name: 'macd', desc: 'MACD线(12,26,9)', cat: '技术', source: 'talib', usedBy: [], unit: '', example: '-0.284', quality: 'good', dailyOk: true },
  { name: 'macd_signal', desc: 'MACD信号线', cat: '技术', source: 'talib', usedBy: [], unit: '', example: '-0.241', quality: 'good', dailyOk: true },
  { name: 'macd_hist', desc: 'MACD柱状图', cat: '技术', source: 'talib', usedBy: [], unit: '', example: '-0.043', quality: 'good', dailyOk: true },
  { name: 'rsi_6', desc: '6日RSI', cat: '技术', source: 'talib', usedBy: [], unit: '', example: '21.83', quality: 'good', dailyOk: true },
  { name: 'rsi_12', desc: '12日RSI', cat: '技术', source: 'talib', usedBy: [], unit: '', example: '28.82', quality: 'good', dailyOk: true },
  { name: 'rsi_24', desc: '24日RSI', cat: '技术', source: 'talib', usedBy: [], unit: '', example: '35.62', quality: 'good', dailyOk: true },
  { name: 'boll_upper', desc: '布林上轨(20日,2σ)', cat: '技术', source: 'talib', usedBy: [], unit: '元', example: '10.64', quality: 'good', dailyOk: true },
  { name: 'boll_mid', desc: '布林中轨(=MA20)', cat: '技术', source: 'talib', usedBy: [], unit: '元', example: '9.78', quality: 'good', dailyOk: true },
  { name: 'boll_lower', desc: '布林下轨', cat: '技术', source: 'talib', usedBy: [], unit: '元', example: '8.91', quality: 'good', dailyOk: true },
  { name: 'atr', desc: '14日ATR', cat: '技术', source: 'talib', usedBy: [], unit: '元', example: '0.28', quality: 'good', dailyOk: true },
  { name: 'natr', desc: '归一化ATR(%)', cat: '技术', source: 'talib', usedBy: [], unit: '%', example: '3.13', quality: 'good', dailyOk: true },

  // ===== 动量/波动 =====
  { name: 'momentum_1d', desc: '1日动量(=pct_chg)', cat: '动量', source: '自动计算', usedBy: [], unit: '%', example: '-4.38', quality: 'good', dailyOk: true },
  { name: 'momentum_5d', desc: '5日动量', cat: '动量', source: '自动计算', usedBy: [], unit: '%', example: '-5.68', quality: 'good', dailyOk: true },
  { name: 'momentum_10d', desc: '10日动量', cat: '动量', source: '自动计算', usedBy: [], unit: '%', example: '-7.05', quality: 'good', dailyOk: true },
  { name: 'momentum_20d', desc: '20日动量', cat: '动量', source: '自动计算', usedBy: [], unit: '%', example: '-13.76', quality: 'good', dailyOk: true },
  { name: 'volatility_5d', desc: '5日波动率', cat: '动量', source: '自动计算', usedBy: [], unit: '%', example: '2.45', quality: 'good', dailyOk: true },
  { name: 'volatility_10d', desc: '10日波动率', cat: '动量', source: '自动计算', usedBy: [], unit: '%', example: '2.07', quality: 'good', dailyOk: true },
  { name: 'volatility_20d', desc: '20日波动率', cat: '动量', source: '自动计算', usedBy: [], unit: '%', example: '2.25', quality: 'good', dailyOk: true },

  // ===== 复合 =====
  { name: 'fear_greed_index', desc: '恐贪指数(0恐惧~100贪婪)', cat: '复合', source: 'RSI+量比+动量综合', usedBy: [], unit: '', example: '2.26', quality: 'good', dailyOk: true },
  { name: 'sentiment_score', desc: '情绪评分(个股级)', cat: '复合', source: '自动计算', usedBy: [], unit: '', example: '0.50', quality: 'warn', dailyOk: true, note: '个股级大部分为0.5,回测用市场级sentiment替代' },

  // ===== 辅助 =====
  { name: 'turnover_5d_avg', desc: '5日平均换手率', cat: '辅助', source: '自动计算', usedBy: [], unit: '%', example: '2.05', quality: 'good', dailyOk: true },
  { name: 'turnover_20d_avg', desc: '20日平均换手率', cat: '辅助', source: '自动计算', usedBy: [], unit: '%', example: '2.66', quality: 'good', dailyOk: true },
  { name: 'volume_increase', desc: '放量标记', cat: '辅助', source: '自动计算', usedBy: [], unit: '0/1', example: '0', quality: 'good', dailyOk: true },
  { name: 'amount_20d', desc: '20日平均成交额', cat: '辅助', source: '自动计算', usedBy: [], unit: '元', example: '1.82亿', quality: 'good', dailyOk: true },
]

// 分类元信息
const catMeta: Record<string, { icon: string; color: string }> = {
  '行情':     { icon: '📊', color: '#409eff' },
  'T-1因子':  { icon: '⏪', color: '#9b59b6' },
  '基础面':   { icon: '💰', color: '#67c23a' },
  '涨跌停':   { icon: '🚦', color: '#f56c6c' },
  '开盘/盘中': { icon: '⏰', color: '#e6a23c' },
  '回调':     { icon: '📉', color: '#909399' },
  '均线':     { icon: '📈', color: '#b37feb' },
  '技术':     { icon: '🔬', color: '#fbbf24' },
  '动量':     { icon: '⚡', color: '#ff7a45' },
  '复合':     { icon: '🧠', color: '#597ef7' },
  '辅助':     { icon: '🔧', color: '#8c8c8c' },
}

const searchQuery = ref('')
const catFilter = ref('')
const showUsedOnly = ref(false)

const categories = [...new Set(allFactors.map(f => f.cat))]

const filteredFactors = computed(() => {
  const q = searchQuery.value.toLowerCase()
  const cat = catFilter.value
  return allFactors.filter(f => {
    if (showUsedOnly.value && f.usedBy.length === 0) return false
    if (cat && f.cat !== cat) return false
    if (!q) return true
    return f.name.toLowerCase().includes(q) ||
           f.desc.toLowerCase().includes(q) ||
           f.usedBy.some(s => s.includes(q))
  })
})

const groupedFactors = computed(() => {
  const groups: Record<string, FactorDef[]> = {}
  for (const f of filteredFactors.value) {
    if (!groups[f.cat]) groups[f.cat] = []
    groups[f.cat].push(f)
  }
  return groups
})

const usedCount = computed(() => allFactors.filter(f => f.usedBy.length > 0).length)
const warnCount = computed(() => allFactors.filter(f => f.quality === 'warn').length)
const badCount = computed(() => allFactors.filter(f => f.quality === 'bad').length)
const prevCount = computed(() => allFactors.filter(f => f.quality === 'prev').length)
const dailyNotOkCount = computed(() => allFactors.filter(f => !f.dailyOk).length)

function qIcon(q: Quality) {
  if (q === 'bad') return '❌'
  if (q === 'warn') return '⚠️'
  if (q === 'prev') return '⏪'
  return ''
}
</script>

<template>
  <div class="factor-ref-v3">
    <!-- 统计条 -->
    <div class="stat-bar">
      <span class="stat-item">📊 总数 <b>{{ allFactors.length }}</b></span>
      <span class="stat-item accent">🎯 策略使用 <b>{{ usedCount }}</b></span>
      <span class="stat-item prev">⏪ T-1因子 <b>{{ prevCount }}</b></span>
      <span class="stat-item warn" v-if="warnCount">⚠️ 质量差 <b>{{ warnCount }}</b></span>
      <span class="stat-item bad" v-if="badCount">❌ 不可用 <b>{{ badCount }}</b></span>
      <span class="stat-item" v-if="dailyNotOkCount">📉 日线不可用 <b>{{ dailyNotOkCount }}</b></span>
    </div>

    <!-- 筛选栏 -->
    <div class="filter-bar">
      <ElInput v-model="searchQuery" placeholder="搜索因子名/描述/策略..." clearable size="small" style="width:220px" />
      <ElSelect v-model="catFilter" placeholder="全部分类" clearable size="small" style="width:130px">
        <ElOption v-for="c in categories" :key="c" :label="c" :value="c" />
      </ElSelect>
      <label class="toggle-label">
        <ElSwitch v-model="showUsedOnly" size="small" />
        <span>仅策略使用</span>
      </label>
      <span class="result-hint">匹配 {{ filteredFactors.length }} / {{ allFactors.length }}</span>
    </div>

    <ElEmpty v-if="filteredFactors.length === 0" description="无匹配因子" :image-size="60" />

    <!-- 按分类紧凑表格 -->
    <div v-for="(factors, cat) in groupedFactors" :key="cat" class="cat-section">
      <div class="cat-header">
        <span class="cat-icon">{{ catMeta[cat]?.icon || '📋' }}</span>
        <span class="cat-name">{{ cat }}</span>
        <span class="cat-count">{{ factors.length }}</span>
      </div>
      <table class="f-table">
        <thead>
          <tr>
            <th class="col-name">因子字段</th>
            <th class="col-desc">含义</th>
            <th class="col-cond">策略筛选条件</th>
            <th class="col-src">来源</th>
            <th class="col-q">质量</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="f in factors" :key="f.name" :class="{ 'row-warn': f.quality === 'warn', 'row-bad': f.quality === 'bad', 'row-prev': f.quality === 'prev', 'row-nodaily': !f.dailyOk }">
            <td class="col-name"><code>{{ f.name }}</code></td>
            <td class="col-desc">
              {{ f.desc }}
              <span v-if="!f.dailyOk" class="badge-nodaily">日线不可用</span>
            </td>
            <td class="col-cond">
              <template v-if="f.usedBy.length > 0">
                <ElTag v-for="s in f.usedBy" :key="s" size="small" effect="plain">{{ s }}</ElTag>
              </template>
              <span v-else class="no-use">—</span>
            </td>
            <td class="col-src" :class="{ 'src-warn': f.quality === 'warn', 'src-bad': f.quality === 'bad' }">{{ f.source }}</td>
            <td class="col-q">{{ qIcon(f.quality) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped lang="scss">
.factor-ref-v3 { padding: 0; }

.stat-bar {
  display: flex; gap: 14px; padding: 8px 12px; background: #f5f7fa; border-radius: 6px; margin-bottom: 12px;
  flex-wrap: wrap; align-items: center;
}
.stat-item { font-size: 13px; color: #606266;
  b { margin-left: 2px; }
  &.accent b { color: #409eff; }
  &.prev b { color: #9b59b6; }
  &.warn b { color: #e6a23c; }
  &.bad b { color: #f56c6c; }
}

.filter-bar {
  display: flex; gap: 10px; align-items: center; margin-bottom: 12px; flex-wrap: wrap;
}
.toggle-label { display: flex; align-items: center; gap: 4px; font-size: 13px; color: #606266; cursor: pointer; }
.result-hint { font-size: 12px; color: #909399; }

/* 分类块 */
.cat-section { margin-bottom: 16px; }
.cat-header {
  display: flex; align-items: center; gap: 6px; margin-bottom: 6px;
  padding: 4px 8px; background: #fafafa; border-radius: 4px; border-left: 3px solid #409eff;
}
.cat-icon { font-size: 14px; }
.cat-name { font-weight: 600; font-size: 13px; color: #303133; }
.cat-count { font-size: 11px; color: #909399; background: #f0f2f5; padding: 0 6px; border-radius: 8px; }

/* 紧凑表格 */
.f-table {
  width: 100%; border-collapse: collapse; font-size: 12px;
  th { text-align: left; color: #909399; font-weight: 500; padding: 4px 8px; border-bottom: 1px solid #ebeef5; background: #fafafa; }
  td { padding: 5px 8px; border-bottom: 1px solid #f5f5f5; vertical-align: top; }
  tr:hover td { background: #f8fbff; }
  tr.row-prev td { background: #f9f5ff; }
  tr.row-prev:hover td { background: #f0e8ff; }
  tr.row-warn td { background: #fffbf0; }
  tr.row-bad td { background: #fff5f5; }
  tr.row-nodaily td { opacity: 0.6; }
}

.col-name { width: 170px; }
.col-name code { font-family: 'SF Mono', 'Fira Code', Consolas, monospace; color: #409eff; font-size: 12px; font-weight: 500; }
.col-desc { color: #606266; line-height: 1.5; }
.col-cond { width: 180px; }
.col-src { width: 100px; color: #909399; font-size: 11px;
  &.src-warn { color: #e6a23c; }
  &.src-bad { color: #f56c6c; }
}
.col-q { width: 30px; text-align: center; }

.no-use { color: #dcdfe6; }
.badge-nodaily {
  display: inline-block; font-size: 10px; color: #f56c6c; background: #fef0f0;
  padding: 0 4px; border-radius: 3px; margin-left: 4px; vertical-align: middle;
}
</style>
