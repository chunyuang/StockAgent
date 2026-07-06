<script setup lang="ts">
/**
 * 数据获取页面 - 展示所有数据源配置、获取逻辑和注意事项
 * 纯展示页面，不修改任何运行时逻辑
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import {
  ElCard,
  ElTable,
  ElTableColumn,
  ElTag,
  ElDescriptions,
  ElDescriptionsItem,
  ElCollapse,
  ElCollapseItem,
  ElAlert,
  ElBadge,
  ElTooltip,
  ElProgress,
  ElDivider,
} from 'element-plus'
import { api } from '@/api'
import type { ApiResponse } from '@/api/client'

// ==================== 静态数据定义 ====================

/** 数据源配置 */
const dataSources = [
  {
    id: 'eastmoney_push2',
    name: '东方财富 Push2',
    icon: '📊',
    status: 'active' as const,
    priority: 1,
    collections: ['stock_daily_ak_full', 'daily_basic'],
    scripts: ['eastmoney_daily_bar.py', 'eastmoney_daily_basic.py'],
    schedule: '盘后自动 + 盘中实时(scanner)',
    rateLimit: '无限, ~3秒/次',
    fields: '全量38字段(OHLCV+PE/PB/流通市值/量比/换手率等)',
    notes: '主力数据源。盘中scanner实时从push2拉行情，盘后15:35 cron自动补采。周末/非交易日push2不可用(RemoteDisconnected)，可fallback到datacenter API。',
    unitWarnings: ['circ_mv: API返回元→需÷10000→万元(ak_full)或÷1e8→亿元(daily_basic)', 'amount: API返回元→需÷100→百元(ak_full)', 'vol: API返回手→直接存', 'turnover_rate: API返回百分数→直接存'],
  },
  {
    id: 'eastmoney_datacenter',
    name: '东方财富 DataCenter',
    icon: '📈',
    status: 'fallback' as const,
    priority: 2,
    collections: ['daily_basic'],
    scripts: ['eastmoney_datacenter_daily_basic.py'],
    schedule: '周末/非交易日push2不可用时',
    rateLimit: '无限',
    fields: 'PE_TTM / PB_MRQ / 流通市值(计算) / 收盘价',
    notes: '通过free_shares×close计算流通市值，结果为亿元(直接存daily_basic)。周末可用，push2的fallback。',
    unitWarnings: ['circ_mv: 计算结果÷1e8→亿元(daily_basic标准)', 'total_mv: 计算结果÷1e8→亿元'],
  },
  {
    id: 'sohu',
    name: '搜狐 hisHq',
    icon: '🔍',
    status: 'fallback' as const,
    priority: 3,
    collections: ['stock_daily_ak_full'],
    scripts: ['sohu_fill_daily.py'],
    schedule: '盘后东方财富失败时自动fallback',
    rateLimit: '无限',
    fields: '12字段(OHLCV+换手率)，缺26个字段',
    notes: '日期必须YYYYMMDD格式(无横杠)。盘中盘后均可用。缺失的is_limit_up/intraday_max_rise_pct等由_merge_factors实时补算。',
    unitWarnings: ['vol: 搜狐返回手→直接存(与MongoDB一致)', 'amount: 搜狐返回万元→需×100→百元', 'turnover_rate: 搜狐返回小数(0.25%)→需×100→百分数(25.0)', '日期格式: 必须YYYYMMDD无横杠'],
  },
  {
    id: 'akshare',
    name: 'AKShare',
    icon: '🐍',
    status: 'fallback' as const,
    priority: 4,
    collections: ['stock_daily_ak_full'],
    scripts: ['fill_missing_daily_ak.py', 'akshare_daily_manager.py'],
    schedule: '按需补采缺失数据',
    rateLimit: '无限',
    fields: '基础OHLCV',
    notes: 'AKShare是Python库，不是API。vol返回股(需÷100→手)，amount返回元(需÷100→百元)。circ_mv返回亿元(需×10000→万元)。',
    unitWarnings: ['vol: 返回股→需÷100→手', 'amount: 返回元→需÷100→百元', 'circ_mv: 返回亿元→需×10000→万元(ak_full标准)', 'turnover_rate: 返回百分数→直接存'],
  },
  {
    id: 'tushare',
    name: 'Tushare',
    icon: '📡',
    status: 'limited' as const,
    priority: 5,
    collections: ['stock_daily_ak_full', 'daily_basic'],
    scripts: ['tushare_fill_v2.py', 'tushare_fill_daily.py', 'tushare_fill_basic.py', 'tushare_fill_2years_v2.py'],
    schedule: '按需补采',
    rateLimit: '5000积分(~4758剩余)',
    fields: 'daily_basic全字段 + daily日线',
    notes: 'Token 5000积分(用户2026-05-11提供)。daily_basic的circ_mv单位=万元，写入daily_basic(标准=亿元)时需÷10000。daily的vol=手(写入ak_full时不应×100)，amount=千元(不应×1000→元)。',
    unitWarnings: ['daily_basic.circ_mv: Tushare返回万元→写入daily_basic需÷10000→亿元', 'daily_basic.total_mv: 同上÷10000', 'daily_basic.turnover_rate: Tushare返回小数(0.0531)→需×100→百分数(5.31)', 'daily.vol: Tushare返回手→直接存(不要×100!)', 'daily.amount: Tushare返回千元→需×10→百元(不要×1000→元!)'],
  },
  {
    id: 'biying',
    name: '必盈 API',
    icon: '🎯',
    status: 'limited' as const,
    priority: 6,
    collections: ['limit_list'],
    scripts: ['fill_limit_list.py'],
    schedule: '盘后补涨停池',
    rateLimit: '200次/天',
    fields: '涨停池(封板时间/开板次数/连板数等)',
    notes: '每日额度有限(200次)。超限后涨停池=0。Licence当日额度耗尽后次日恢复。',
    unitWarnings: [],
  },
  {
    id: 'liangmai',
    name: '量脉 LiangMai',
    icon: '⚡',
    status: 'deprecated' as const,
    priority: 7,
    collections: ['(实时行情)'],
    scripts: ['(scanner内置)'],
    schedule: '盘中实时(1min K线)',
    rateLimit: '120次/分钟, 2个IP',
    fields: '实时盘中行情/1min K线',
    notes: 'DNS不解析(api.liangmai8.com)已不可用。Token绑定2个IP，服务器动态IP导致429不可避免。429错误=IP超限，不要反复重试。daily_basic不要再用量脉，用东方财富替代。',
    unitWarnings: ['已废弃: DNS不解析，429频繁', 'daily_basic已用东方财富替代'],
  },
  {
    id: 'tencent',
    name: '腾讯 QQ行情',
    icon: '💬',
    status: 'legacy' as const,
    priority: 8,
    collections: ['stock_daily_ak_full'],
    scripts: ['tencent_daily_bar.py', 'tencent_kline_bar.py'],
    schedule: '历史遗留，不常用',
    rateLimit: '无限',
    fields: '基础OHLCV+换手率',
    notes: '历史数据源。vol返回手但代码×100→股(错误!), amount返回万元但代码×10000→元(错误!)。这些单位与MongoDB标准不一致，使用时需注意。',
    unitWarnings: ['⚠️ vol: 代码×100→股(MongoDB标准=手! 单位错!)', '⚠️ amount: 代码×10000→元(MongoDB标准=百元! 单位错!)'],
  },
]

/** 全量集合分类与审查规则 */
const allCollectionCategories = [
  {
    category: '行情数据',
    icon: '📈',
    color: '#3b82f6',
    description: '数据源采补的原始行情与因子数据',
    collections: [
      { name: 'stock_daily_ak_full', desc: 'A股日线行情+46+因子', keyField: 'trade_date', freshness: '1天' },
      { name: 'daily_basic', desc: 'PE/PB/换手率/市值等基础指标', keyField: 'trade_date', freshness: '1天' },
      { name: 'limit_list', desc: '涨跌停池(涨停/跌停/炸板)', keyField: 'trade_date', freshness: '1天' },
      { name: 'sentiment_scores', desc: '市场情绪评分(涨停数/炸板率等)', keyField: 'trade_date', freshness: '1天' },
    ],
  },
  {
    category: '交易数据',
    icon: '💰',
    color: '#10b981',
    description: '实盘交易产生的订单/持仓/账户数据',
    collections: [
      { name: 'broker_orders', desc: '买卖订单(filled/pending/cancelled)', keyField: 'created_at', freshness: '实时' },
      { name: 'broker_positions', desc: '当前持仓(市值/成本/盈亏)', keyField: 'ts_code', freshness: '实时' },
      { name: 'broker_accounts', desc: '账户资产(现金/市值/总资产)', keyField: '-', freshness: '实时' },
      { name: 'equity_curve', desc: '资金曲线(每日资产快照)', keyField: 'date', freshness: '1天' },
    ],
  },
  {
    category: '持久化/状态',
    icon: '⚙️',
    color: '#8b5cf6',
    description: 'scanner运行时状态持久化',
    collections: [
      { name: 'scanner_runtime_snapshot', desc: 'scanner运行时快照(持仓/现金)', keyField: 'trade_date', freshness: '实时' },
      { name: 'risk_decisions', desc: '风控决策记录(止损/止盈)', keyField: 'timestamp', freshness: '实时' },
      { name: 'scan_traces', desc: '扫描记录(信号漏斗)', keyField: 'created_at', freshness: '实时' },
      { name: 'performance_snapshots', desc: '绩效快照(胜率/夏普等)', keyField: 'timestamp', freshness: '1天' },
      { name: 'premarket_snapshots', desc: '盘前快照(竞价/持仓盈亏)', keyField: 'trade_date', freshness: '1天' },
    ],
  },
  {
    category: '计算/展示',
    icon: '🖥️',
    color: '#f59e0b',
    description: '衍生计算与展示层数据',
    collections: [
      { name: 'scanner_timeline', desc: '信号时间线(signal/skip/circuit)', keyField: 'trade_date', freshness: '实时' },
      { name: 'scanner_signals', desc: '交易信号池', keyField: 'trade_date', freshness: '实时' },
      { name: 'sentiment_live_log', desc: '盘中情绪日志', keyField: 'timestamp', freshness: '实时' },
      { name: 'limit_pool_down', desc: '跌停池', keyField: 'trade_date', freshness: '1天' },
      { name: 'index_daily', desc: '指数日线(上证/深证/创业板)', keyField: 'trade_date', freshness: '1天' },
      { name: 'audit_log', desc: '审计日志', keyField: 'timestamp', freshness: '实时' },
    ],
  },
]

/** 审查规则说明 */
const auditRules = [
  { dimension: '因子影响审查', schedule: '工作日16:00', script: 'factor_impact_audit.py', checks: '因子计算/值域/策略一致性/派生因子/空壳防护/跨集合/漏斗/炸板率' },
  { dimension: '交易数据审查', schedule: '工作日16:10', script: 'trading_data_audit.py', checks: 'positions.mv/账户等式/equity单调/risk_decisions/sell avg_cost/cash偏差' },
  { dimension: '使用侧一致性审查', schedule: '周一20:00', script: '内嵌6维度', checks: 'circ_mv单位/PE-PB/策略参数vs代码/broken/first_limit_up/回测引擎' },
  { dimension: '数据单位验证', schedule: '工作日16:40', script: 'validate_data_units.py', checks: '字段单位/参照票市值/跨集合一致性' },
]

/** MongoDB集合字段单位标准 */
const collectionStandards = [
  {
    collection: 'stock_daily_ak_full',
    description: 'A股日线行情+因子',
    fields: [
      { field: 'close/open/high/low/pre_close', unit: '元', example: '25.38', range: '0.01-99999' },
      { field: 'pct_chg', unit: '百分数', example: '10.0 (表示10%)', range: '-30~+30' },
      { field: 'vol', unit: '手', example: '891848', range: '1-1e8', warning: '手！不是股！' },
      { field: 'amount', unit: '百元', example: '891848', range: '1-1e10', warning: '百元！不是元！' },
      { field: 'turnover_rate', unit: '百分数', example: '5.31 (表示5.31%)', range: '0.01-100', warning: '不是0.0531！不是531！' },
      { field: 'volume_ratio', unit: '倍数', example: '1.52', range: '0-50' },
      { field: 'circ_mv', unit: '万元', example: '148800', range: '100-1e8', warning: '万元！不是元！不是亿！' },
      { field: 'total_mv', unit: '万元', example: '200000', range: '100-1e8', warning: '万元！' },
      { field: 'is_limit_up', unit: '0/1', example: '1', range: '0-1' },
      { field: 'first_limit_up', unit: '0/1', example: '1', range: '0-1' },
    ],
  },
  {
    collection: 'daily_basic',
    description: '每日基础面数据',
    fields: [
      { field: 'turnover_rate', unit: '百分数', example: '5.31', range: '0.01-100' },
      { field: 'volume_ratio', unit: '倍数', example: '1.52', range: '0-50' },
      { field: 'circ_mv', unit: '亿元', example: '14.88', range: '0.01-1e4', warning: '亿元！与ak_full差10000倍！' },
      { field: 'total_mv', unit: '亿元', example: '20.0', range: '0.01-1e4', warning: '亿元！与ak_full差10000倍！' },
      { field: 'pe_ttm', unit: '倍数', example: '25.3', range: '-1000~1000' },
      { field: 'pb', unit: '倍数', example: '3.2', range: '0-100' },
      { field: 'close', unit: '元', example: '25.38', range: '0.01-99999' },
    ],
  },
]

/** 关键跨集合差异 */
const crossCollectionDiffs = [
  { field: 'circ_mv', ak_full: '万元', daily_basic: '亿元', ratio: '×10000', impact: '同步时必须×10000(ak_full)或÷10000(daily_basic)，否则差1万倍' },
  { field: 'total_mv', ak_full: '万元', daily_basic: '亿元', ratio: '×10000', impact: '同circ_mv' },
]

/** 历史bug记录 */
const historicalBugs = [
  { date: '2026-06-23~29', bug: 'turnover_rate被×100存入', impact: '23954条数据, 回测换手率筛选失效', rootCause: '搜狐写入时多×100', fix: '÷100恢复' },
  { date: '2026-06-24~29', bug: 'first_limit_up字段全0', impact: '回测0笔first_limit_up交易', rootCause: 'daily_factor_precompute逻辑缺陷', fix: 'is_limit_up=1→first_limit_up=1' },
  { date: '2026-07-02', bug: 'circ_mv单位混乱(亿元/百万元/万元混存)', impact: '流通市值筛选全部失效, 回测0笔', rootCause: '不同数据源写入时未做单位转换', fix: '用6/30正确数据覆盖+×100/×10000修复' },
  { date: '2026-07-02', bug: '回测策略名中英文不匹配', impact: 'first_limit_up回测0笔', rootCause: 'API传英文ID但筛选用中文名', fix: '3处统一转中文名' },
  { date: '2026-07-02', bug: 'tushare_fill_v2写入daily_basic时circ_mv未÷10000', impact: '每次Tushare补采都写入错误单位', rootCause: 'Tushare返回万元但daily_basic标准亿元', fix: '÷10000转换' },
  { date: '2026-07-02', bug: 'lightweight_factor_fill同步circ_mv未×10000', impact: 'daily_basic→ak_full同步时单位错误', rootCause: 'daily_basic=亿元, ak_full=万元', fix: '×10000转换' },
]

/** 因子分类 */
const factorCategories = [
  {
    category: '技术因子',
    icon: '📈',
    color: '#3b82f6',
    factors: [
      { name: 'MA5/MA10/MA20/MA60', source: '计算', compute: '收盘价滚动均值', script: 'lightweight_factor_fill.py → compute_ma()', collection: 'stock_daily_ak_full', schedule: '盘后因子补算' },
      { name: 'MACD/DIF/DEA', source: '计算', compute: 'EMA12/EMA26差值+9日信号线', script: 'lightweight_factor_fill.py → compute_technical_indicators()', collection: 'stock_daily_ak_full', schedule: '盘后因子补算' },
      { name: 'RSI_6/12/24', source: '计算', compute: '相对强弱指数(6/12/24日)', script: 'lightweight_factor_fill.py → compute_technical_indicators()', collection: 'stock_daily_ak_full', schedule: '盘后因子补算' },
      { name: 'BOLL(upper/mid/lower)', source: '计算', compute: '20日均线±2倍标准差', script: 'lightweight_factor_fill.py → compute_technical_indicators()', collection: 'stock_daily_ak_full', schedule: '盘后因子补算' },
      { name: 'ATR/NATR', source: '计算', compute: '14日真实波幅均值', script: 'lightweight_factor_fill.py → compute_technical_indicators()', collection: 'stock_daily_ak_full', schedule: '盘后因子补算' },
      { name: '恐贪指数(fear_greed_index)', source: '计算', compute: 'RSI_12归一化: (RSI-50)/50×2.5+5', script: 'lightweight_factor_fill.py → compute_technical_indicators()', collection: 'stock_daily_ak_full', schedule: '盘后因子补算' },
      { name: '振幅(amplitude)', source: '计算', compute: '(最高-最低)/昨收×100', script: 'daily_factor_precompute.py', collection: 'stock_daily_ak_full', schedule: '盘后因子预计算' },
    ],
  },
  {
    category: '动量因子',
    icon: '🚀',
    color: '#10b981',
    factors: [
      { name: 'momentum_1d/5d/10d/20d', source: '计算', compute: 'N日收益率: close[T]/close[T-N]-1', script: 'lightweight_factor_fill.py → compute_technical_indicators()', collection: 'stock_daily_ak_full', schedule: '盘后因子补算' },
      { name: '波动率_5d/10d/20d', source: '计算', compute: 'N日收益率标准差', script: 'lightweight_factor_fill.py → compute_technical_indicators()', collection: 'stock_daily_ak_full', schedule: '盘后因子补算' },
      { name: '波动率_60d(volatility_60d)', source: '计算', compute: '60日收益率标准差(回测时factor_engine动态计算)', script: 'factor_engine.py (回测时计算)', collection: '(不持久化, 回测实时算)', schedule: '回测时实时计算' },
      { name: '领涨股(leading_stock)', source: '计算', compute: '近期涨幅排序, 涨幅越大分数越高', script: '回测时factor_engine动态计算', collection: '(不持久化, 回测实时算)', schedule: '回测时实时计算' },
      { name: '龙虎榜净买入(lhb_buy_in)', source: '外部获取', compute: '龙虎榜净买入金额(千万), Tushare获取', script: '回测时从外部获取', collection: '(不持久化, 回测实时获取)', schedule: '回测时实时获取' },
      { name: '一月反转(one_month_reversal)', source: '计算', compute: '一个月收益反转, 上月跌越多本月得分越高', script: '回测时factor_engine动态计算', collection: '(不持久化, 回测实时算)', schedule: '回测时实时计算' },
      { name: '情绪评分(sentiment_score)', source: '计算', compute: '基于涨跌停/炸板率/连板数等7维情绪模型', script: 'daily_factor_precompute.py → _compute_factors_for_stock()', collection: 'stock_daily_ak_full', schedule: '盘后因子预计算' },
      { name: '龙头股(market_leader)', source: '计算', compute: '板块内涨幅排序Top1', script: 'daily_factor_precompute.py → _compute_factors_for_stock()', collection: 'stock_daily_ak_full', schedule: '盘后因子预计算' },
      { name: '热门板块(hot_sector)', source: '计算', compute: '当日板块涨幅Top3内个股', script: 'daily_factor_precompute.py → _compute_factors_for_stock()', collection: 'stock_daily_ak_full', schedule: '盘后因子预计算' },
    ],
  },
  {
    category: '流动性因子',
    icon: '💧',
    color: '#6366f1',
    factors: [
      { name: '换手率(turnover_rate)', source: '外部获取', compute: '东方财富/搜狐/Tushare/AKShare直接获取', script: 'eastmoney_daily_basic.py / sohu_fill_daily.py / tushare_fill_v2.py', collection: 'stock_daily_ak_full + daily_basic', schedule: '盘后数据采补', unitNote: '百分数(5.31=5.31%), 搜狐需×100' },
      { name: '量比(volume_ratio)', source: '外部获取', compute: '东方财富/Tushare直接获取', script: 'eastmoney_daily_basic.py / tushare_fill_v2.py', collection: 'stock_daily_ak_full + daily_basic', schedule: '盘后数据采补' },
      { name: '放量标记(volume_increase)', source: '计算', compute: '当日成交量 > 5日均值×1.5', script: 'daily_factor_precompute.py → _compute_factors_for_stock()', collection: 'stock_daily_ak_full', schedule: '盘后因子预计算' },
      { name: '成交额(amount_20d)', source: '计算', compute: '20日平均成交额(亿元)', script: 'daily_factor_precompute.py', collection: 'stock_daily_ak_full', schedule: '盘后因子预计算' },
      { name: '流通市值(circ_mv)', source: '外部获取+同步', compute: '东方财富API(元)→÷1e4→万元(ak_full) / ÷1e8→亿元(daily_basic)', script: 'eastmoney_daily_bar.py + eastmoney_daily_basic.py + lightweight_factor_fill.py', collection: 'stock_daily_ak_full + daily_basic', schedule: '盘后采补+因子同步', unitNote: '⚠️ ak_full=万元, daily_basic=亿元, 差10000倍!' },
      { name: '总市值(total_mv)', source: '外部获取+同步', compute: '同circ_mv', script: 'eastmoney_daily_basic.py + lightweight_factor_fill.py', collection: 'stock_daily_ak_full + daily_basic', schedule: '盘后采补+因子同步', unitNote: '⚠️ 同circ_mv, 跨集合差10000倍' },
    ],
  },
  {
    category: '涨跌停因子',
    icon: '🔴',
    color: '#ef4444',
    factors: [
      { name: 'is_limit_up / is_limit_down', source: '计算', compute: 'pct_chg≥阈值(ST5%/主板10%/创业板20%/北交30%)', script: 'lightweight_factor_fill.py → compute_limit_flags()', collection: 'stock_daily_ak_full', schedule: '盘后因子补算' },
      { name: 'first_limit_up', source: '计算', compute: '当日涨停 且 昨日未涨停', script: 'lightweight_factor_fill.py → compute_limit_flags()', collection: 'stock_daily_ak_full', schedule: '盘后因子补算' },
      { name: 'limit_up_count / limit_down_count', source: '计算', compute: '连续涨/跌停天数(向前遍历)', script: 'lightweight_factor_fill.py → compute_limit_up_count()', collection: 'stock_daily_ak_full', schedule: '盘后因子补算' },
      { name: 'limit_up_yesterday / limit_down_yesterday', source: '计算', compute: 'T-1日是否涨/跌停', script: 'lightweight_factor_fill.py → compute_limit_flags()', collection: 'stock_daily_ak_full', schedule: '盘后因子补算' },
      { name: 'open_above_limit / open_below_limit', source: '计算', compute: '开盘价与昨日涨/跌停价比较', script: 'lightweight_factor_fill.py → compute_opening_and_intraday()', collection: 'stock_daily_ak_full', schedule: '盘后因子补算' },
      { name: 'limit_up_open_amount/count/time/duration', source: '外部获取', compute: '涨停开板金额/次数/时间/时长(必盈API)', script: 'fill_limit_list.py → limit_list集合', collection: 'limit_list → 合入stock_daily_ak_full', schedule: '盘后涨停池补采' },
      { name: 'limit_up_amount', source: '外部获取', compute: '涨停封单金额(万元), 必盈API', script: 'fill_limit_list.py → limit_list集合', collection: 'limit_list → 合入stock_daily_ak_full', schedule: '盘后涨停池补采' },
      { name: 'open_above_limit_down', source: '计算', compute: '开盘价 > 昨日跌停价(1=是)', script: 'lightweight_factor_fill.py → compute_opening_and_intraday()', collection: 'stock_daily_ak_full', schedule: '盘后因子补算' },
      { name: 'limit_down_open_amount', source: '外部获取', compute: '跌停被打开时的成交金额(万元)', script: 'fill_limit_list.py', collection: 'limit_list → 合入stock_daily_ak_full', schedule: '盘后涨停池补采' },
      { name: 'rise_after_limit_down', source: '计算', compute: '跌停被打开后到收盘的涨幅(%)', script: 'lightweight_factor_fill.py → compute_opening_and_intraday()', collection: 'stock_daily_ak_full', schedule: '盘后因子补算' },
    ],
  },
  {
    category: '回调因子',
    icon: '📉',
    color: '#f59e0b',
    factors: [
      { name: 'pullback_pct', source: '计算', compute: '从近期高点回调幅度(%)', script: 'lightweight_factor_fill.py → compute_pullback()', collection: 'stock_daily_ak_full', schedule: '盘后因子补算' },
      { name: 'pullback_days', source: '计算', compute: '从近期高点回调天数', script: 'lightweight_factor_fill.py → compute_pullback()', collection: 'stock_daily_ak_full', schedule: '盘后因子补算' },
      { name: 'pullback_ma5', source: '计算', compute: '价格回踩MA5附近得分', script: 'lightweight_factor_fill.py → compute_pullback()', collection: 'stock_daily_ak_full', schedule: '盘后因子补算' },
      { name: '价格靠近MA5(price_near_ma5)', source: '计算', compute: '|close-ma5|/ma5偏离度', script: '回测时factor_engine动态计算', collection: '(不持久化)', schedule: '回测时实时计算' },
    ],
  },
  {
    category: '价值因子',
    icon: '💰',
    color: '#8b5cf6',
    factors: [
      { name: 'PE_TTM', source: '外部获取', compute: '东方财富/Tushare直接获取', script: 'eastmoney_daily_basic.py / tushare_fill_v2.py', collection: 'daily_basic', schedule: '盘后数据采补' },
      { name: 'PB', source: '外部获取', compute: '东方财富/Tushare直接获取', script: 'eastmoney_daily_basic.py / tushare_fill_v2.py', collection: 'daily_basic', schedule: '盘后数据采补' },
      { name: 'PS_TTM / DV_TTM', source: '外部获取', compute: 'Tushare fina_indicator', script: 'fina_indicator collector', collection: 'fina_indicator', schedule: '每月1号' },
    ],
  },
  {
    category: '质量/成长因子',
    icon: '📊',
    color: '#06b6d4',
    factors: [
      { name: 'ROE / ROA', source: '外部获取', compute: 'Tushare fina_indicator', script: 'fina_indicator collector (tushare_adapter.py)', collection: 'fina_indicator', schedule: '每月1号(季报披露后更新)' },
      { name: '毛利率(gross_margin)', source: '外部获取', compute: 'Tushare fina_indicator', script: 'fina_indicator collector', collection: 'fina_indicator', schedule: '每月1号' },
      { name: '营收增长率(revenue_growth)', source: '外部获取', compute: 'Tushare fina_indicator: 营业收入同比增长率', script: 'fina_indicator collector', collection: 'fina_indicator', schedule: '每月1号' },
      { name: '利润增长率(profit_growth)', source: '外部获取', compute: 'Tushare fina_indicator: 净利润同比增长率', script: 'fina_indicator collector', collection: 'fina_indicator', schedule: '每月1号' },
    ],
  },
  {
    category: '盘中实时因子',
    icon: '⚡',
    color: '#ec4899',
    factors: [
      { name: 'pct_chg / price / open / high / low', source: '实时获取', compute: '东方财富Push2实时行情', script: 'scanner → eastmoney_adapter.py', collection: '(内存, 不持久化)', schedule: '盘中每轮扫描' },
      { name: 'is_limit_up(实时)', source: '实时计算', compute: 'pct_chg≥阈值(区分ST/主板/创业板/北交)', script: 'strategy_scorer.py → _classify_limit()', collection: '(内存)', schedule: '盘中每轮扫描' },
      { name: 'circ_mv(实时)', source: '实时获取', compute: '东方财富f21(元)→÷10000→万元', script: 'strategy_scorer.py → _realtime_to_dataframe()', collection: '(内存)', schedule: '盘中每轮扫描', unitNote: '实时数据float_mv可能是元(>1e7时÷10000)或万元' },
      { name: '*_prev (T-1日因子)', source: 'DB读取', compute: '从daily_factors_df合入, 重命名为pct_chg_prev等', script: 'strategy_scorer.py → _merge_with_daily_factors()', collection: 'stock_daily_ak_full(T-1)', schedule: '盘中每轮扫描', unitNote: '约定: T-1日因子加_prev后缀, 避免与实时混淆' },
    ],
  },
]

/** 因子计算脚本详情 */
const factorScripts = [
  {
    name: 'lightweight_factor_fill.py',
    lineCount: 659,
    description: '轻量因子补算(主力)',
    functions: [
      { fn: 'fill_simple_factors()', desc: '从daily_basic同步turnover_rate/volume_ratio/circ_mv/total_mv到ak_full', note: 'circ_mv/total_mv需×10000(亿元→万元)' },
      { fn: 'compute_ma()', desc: '计算MA5/10/20/60均线', note: '需要60天lookback数据' },
      { fn: 'compute_limit_flags()', desc: '计算is_limit_up/is_limit_down/first_limit_up/limit_up_yesterday', note: '基于pct_chg阈值(ST/主板/创业板/北交不同)' },
      { fn: 'compute_opening_and_intraday()', desc: '计算开盘涨幅/open_above_limit/intraday_max_rise_pct等', note: '' },
      { fn: 'compute_limit_up_count()', desc: '计算连续涨跌停天数', note: '向前遍历直到pct_chg<阈值' },
      { fn: 'compute_pullback()', desc: '计算pullback_pct/pullback_days/pullback_ma5', note: '' },
      { fn: 'compute_technical_indicators()', desc: '纯Python计算MACD/RSI/BOLL/ATR/恐贪/动量/波动率', note: '不需要talib, 用pandas ewm/rolling实现' },
    ],
  },
  {
    name: 'daily_factor_precompute.py',
    lineCount: 237,
    description: '每日因子预计算(回测高频使用)',
    functions: [
      { fn: 'precompute_factors()', desc: '读取60天数据→合并daily_basic→计算KEY_FACTORS→写回ak_full', note: '⚠️ L72-75: 从daily_basic合并circ_mv时用亿元值覆盖ak_full万元值! 但只写new_factors不影响circ_mv' },
      { fn: '_compute_factors_for_stock()', desc: '计算volume_increase/market_leader/hot_sector/sentiment_score', note: '这4个因子是策略专用, 不在lightweight_factor_fill中' },
    ],
  },
  {
    name: 'factor_auto_compute.py',
    lineCount: 574,
    description: '回测时自动检测因子缺失并计算',
    functions: [
      { fn: 'auto_compute_factors()', desc: 'portfolio_backtest检测缺失→触发计算→写MongoDB→回测继续', note: '增量计算, 只算缺失日期' },
    ],
  },
  {
    name: 'strategy_scorer.py (盘中)',
    lineCount: 613,
    description: '盘中实时因子合并',
    functions: [
      { fn: 'merge_factors()', desc: '实时数据→DataFrame', note: '' },
      { fn: '_realtime_to_dataframe()', desc: '实时行情→DataFrame, circ_mv单位统一转万元', note: 'float_mv>1e7时÷10000(元→万元)' },
      { fn: '_merge_with_daily_factors()', desc: '合入T-1日因子, 加_prev后缀', note: '约定: pct_chg_prev/volume_ratio_prev/turnover_rate_prev/circ_mv_prev' },
      { fn: '_classify_limit()', desc: '涨跌停判断(ST5%/主板10%/创业板20%/北交30%)', note: '' },
    ],
  },
]

/** 采补链路 */
const pipelineSteps = [
  { time: '15:35 盘后', step: '东方财富(主力)', script: 'eastmoney_daily_bar.py + eastmoney_daily_basic.py', detail: '全市场OHLCV+PE/PB/流通市值/量比, ~3秒完成' },
  { time: '15:35 盘后', step: '搜狐(fallback)', script: 'sohu_fill_daily.py', detail: '东方财富失败时自动切换, 只有12字段' },
  { time: '15:35 盘后', step: '涨停池补采', script: 'fill_limit_list.py', detail: '从必盈API获取涨停池(封板时间/连板数等)' },
  { time: '15:40 盘后', step: '因子同步+补算', script: 'lightweight_factor_fill.py', detail: 'daily_basic→ak_full同步 + MA/MACD/RSI/BOLL/ATR/涨跌停/回调/恐贪等计算' },
  { time: '15:40 盘后', step: '策略因子预计算', script: 'daily_factor_precompute.py', detail: 'volume_increase/market_leader/hot_sector/sentiment_score等策略专用因子' },
  { time: '15:40 盘后', step: '完整性验证', script: 'validate_data_units.py', detail: '校验字段单位、参照票市值、跨集合一致性' },
  { time: '07:00 盘前', step: '盘前数据补采自愈', script: 'sohu_fill_daily.py + fill_limit_list_from_daily.py', detail: '检查昨日数据缺失→搜狐补采→涨停池推算→验证就绪' },
  { time: '09:30-15:00', step: '实时因子', script: 'strategy_scorer.py → merge_factors()', detail: '盘中每轮: 实时行情+T-1日因子(_prev)→合并为策略筛选输入' },
  { time: '每月1号', step: '财务因子更新', script: 'fina_indicator collector (Tushare)', detail: 'ROE/ROA/毛利率/营收增长率/利润增长率等5因子, 季报后更新' },
]

/** 已知问题(已全部修复) */
const knownIssues = [
  { level: '✅', script: 'tushare_fill_daily.py', issue: 'vol: 手×100→股(应为手), amount: 千元×1000→元(应为百元)', impact: '已修: vol直接存, amount×10→百元' },
  { level: '✅', script: 'tushare_fill_2years_v2.py', issue: '同上, vol/amount单位错误 + daily_basic circ_mv未÷10000', impact: '已修: vol直接存, amount×10→百元, circ_mv÷10000' },
  { level: '✅', script: 'tencent_daily_bar.py', issue: 'vol: 手×100→股(应为手), amount: 万元×10000→元(应为百元)', impact: '已修: vol直接存, amount×100→百元' },
  { level: '✅', script: 'fill_old_segment_em.py', issue: 'vol: 手×100→股(应为手), amount: 元(应为百元)', impact: '已修: vol直接存, amount÷100→百元' },
  { level: '✅', script: 'fill_missing_daily_ak.py', issue: 'vol: 股(未÷100→手), amount: 元(未÷100→百元)', impact: '已修: vol÷100→手, amount÷100→百元' },
  { level: '✅', script: 'tushare_fill_basic.py', issue: 'circ_mv未÷10000(写入daily_basic)', impact: '已修: circ_mv÷10000→亿元' },
]

// ==================== 动态数据 ====================

const loading = ref(false)
const dbStats = ref<any>({})
const dataStatus = ref<any>({})

/** 折叠状态 */
const expandedSections = ref<Record<string, boolean>>({
  pipeline: false,
  status: false,
})
const mainCollapse = ref<string[]>([])  // 默认全部折叠

/** 数据采补状态子区块折叠 */
const statusSubCollapse = ref<string[]>([])

const toggleSection = (key: string) => {
  expandedSections.value[key] = !expandedSections.value[key]
}

const sentimentPoints = ref<any[]>([])
const recentSignals = ref<any[]>([])
const scannerRuntimeStatus = ref<any>({})

/** 因子覆盖率详情(最新日) */
const factorDetailLatest = computed(() => dataStatus.value?.factor_detail_latest || {})

/** 盘中状态汇总 */
const intradaySummary = computed(() => {
  const snap = scannerRuntimeStatus.value || {}
  const stats = snap.stats || {}
  return [
    { label: '扫描轮次', value: stats.scans ?? '-', icon: '🔄' },
    { label: '扫描股票', value: stats.stocks_scanned?.toLocaleString() ?? '-', icon: '📊' },
    { label: '发现信号', value: stats.signals_found ?? '-', icon: '📡' },
    { label: '执行交易', value: stats.trades_executed ?? '-', icon: '✅' },
    { label: '止损', value: stats.stop_losses ?? '-', icon: '🛑' },
    { label: '止盈', value: stats.take_profits ?? '-', icon: '🎯' },
    { label: '情绪分数', value: snap.sentiment_score ? snap.sentiment_score.toFixed(1) : '-', icon: '🌡️' },
    { label: '持仓比例', value: snap.current_position_ratio != null ? (snap.current_position_ratio * 100).toFixed(0) + '%' : '-', icon: '💼' },
    { label: '活跃信号', value: snap.active_signals_count ?? '-', icon: '⚡' },
    { label: '熔断暂停', value: snap.circuit_breaker?.trading_paused ? '是' : '否', icon: '🚨' },
  ]
})

/** 今日信号按策略分组 */
const signalsByStrategy = computed(() => {
  const sigs = recentSignals.value || []
  const groups: Record<string, number> = {}
  for (const s of sigs) {
    const name = s.strategy_name || s.strategy || '未知'
    groups[name] = (groups[name] || 0) + 1
  }
  return Object.entries(groups).map(([name, count]) => ({ name, count }))
})

/** 情绪曲线简化数据 */
const sentimentChartPoints = computed(() => {
  return (sentimentPoints.value || []).slice(-30).map((p: any) => ({
    time: p.time_label || p.time?.slice(11, 16) || '?',
    score: p.score?.toFixed(1) ?? 0,
    limit_up: p.limit_up ?? 0,
    broken: p.broken ?? 0,
    broken_rate: p.broken_rate ? (p.broken_rate * 100).toFixed(0) + '%' : '-',
    period: p.period || '-',
  }))
})

/** 因子覆盖率详情表格 */
const factorDetailRows = computed(() => {
  const fdl = factorDetailLatest.value
  if (!fdl || Object.keys(fdl).length === 0) return []
  const groups: Record<string, { factor: string; rate: number }[]> = {
    '基础': [],
    '技术MA': [],
    '技术TALib': [],
    '量价': [],
    '涨跌停': [],
  }
  const groupMap: Record<string, string[]> = {
    '基础': ['pct_chg', 'pre_close', 'open', 'high', 'low', 'close'],
    '技术MA': ['ma5', 'ma10', 'ma20', 'ma60'],
    '技术TALib': ['macd', 'rsi_6', 'boll_upper', 'atr', 'fear_greed_index'],
    '量价': ['turnover_rate', 'volume_ratio', 'circ_mv'],
    '涨跌停': ['is_limit_up', 'is_limit_down', 'first_limit_up', 'limit_up_count'],
  }
  for (const [gname, factors] of Object.entries(groupMap)) {
    for (const f of factors) {
      if (fdl[f] != null) {
        groups[gname].push({ factor: f, rate: fdl[f] })
      }
    }
  }
  const rows: { group: string; factor: string; rate: number; status: string }[] = []
  for (const [gname, items] of Object.entries(groups)) {
    for (const item of items) {
      const status = item.rate >= 90 ? 'ok' : item.rate >= 50 ? 'warn' : 'error'
      rows.push({ group: gname, factor: item.factor, rate: item.rate, status })
    }
  }
  return rows
})

/** 今日MongoDB实时数据计数 */
const intradayMongoCounts = ref<any[]>([])

const fetchDbStats = async () => {
  loading.value = true
  try {
    const [statsResult, statusResult] = await Promise.allSettled([
      api.get<ApiResponse>('/admin/db/stats'),
      api.get<ApiResponse>('/system/data-status'),
    ])
    if (statsResult.status === 'fulfilled' && statsResult.value.success && statsResult.value.data) {
      dbStats.value = statsResult.value.data
    }
    if (statusResult.status === 'fulfilled' && statusResult.value.success && statusResult.value.data) {
      dataStatus.value = statusResult.value.data
    }
  } catch (e) {
    // 静默失败，页面仍可用
  } finally {
    loading.value = false
  }
}

/** 拉取盘中实时数据 */
const fetchIntradayData = async () => {
  try {
    // 1. 情绪时间线
    const sentRes = await api.get<ApiResponse>('/scanner/sentiment-timeline?mode=intraday')
    if (sentRes.success && sentRes.data) {
      sentimentPoints.value = sentRes.data.points || []
    }
    // 2. 最新信号
    const sigRes = await api.get<ApiResponse>('/scanner/stream/signals?limit=50')
    if (sigRes.success && sigRes.data) {
      const sigData = sigRes.data
      if (Array.isArray(sigData)) {
        // 展开嵌套的signals
        const flat: any[] = []
        for (const item of sigData) {
          const inner = item.data?.data
          if (typeof inner === 'string') {
            try {
              const parsed = JSON.parse(inner)
              if (parsed.signals) flat.push(...parsed.signals)
            } catch {}
          }
        }
        recentSignals.value = flat
      }
    }
  } catch (e) {
    // 静默失败
  }
}

/** 拉取MongoDB实时计数(通过admin/db/stats或直接用data-status的collections) */
const fetchIntradayMongoCounts = async () => {
  try {
    // 从data-status的collections中提取盘中实时集合
    const cols = dataStatus.value?.collections || {}
    const realtimeCollections = [
      'scanner_signals', 'scanner_timeline', 'sentiment_live_log',
      'scan_traces', 'premarket_snapshots', 'limit_list',
      'broker_orders', 'risk_decisions', 'scanner_runtime_snapshot',
    ]
    const today = new Date().toISOString().slice(0, 10).replace(/-/g, '')
    intradayMongoCounts.value = realtimeCollections.map(name => {
      const info = cols[name] as any || {}
      return {
        name,
        count: info.count || 0,
        dateEnd: info.date_range?.end || '-',
        freshness: info.date_range?.end === today || info.date_range?.end === today.slice(0, 4) + '-' + today.slice(4, 6) + '-' + today.slice(6) ? '今日' : (info.date_range?.end || '-'),
      }
    })
  } catch (e) {
    // 静默
  }
}

/** 拉取scanner运行时快照 */
const fetchScannerRuntime = async () => {
  try {
    const res = await api.get<ApiResponse>('/scanner/health')
    if (res.success && res.data) {
      const h = res.data.health || res.data
      scannerRuntimeStatus.value = {
        overall_status: h.overall_status,
        message: h.message,
        health_score: h.health_score,
        scan_lag_seconds: h.scan_lag_seconds,
        data_freshness: h.data_freshness,
        warnings: h.warnings || [],
        circuit_breaker: h.circuit_breaker || {},
        risk_metrics: h.risk_metrics || {},
        data_sources: h.data_sources || [],
        version: h.version || {},
      }
    }
  } catch (e) {
    // 静默
  }
}

/** 自动刷新(盘中每30秒) */
let refreshTimer: ReturnType<typeof setInterval> | null = null

const startAutoRefresh = () => {
  const now = new Date()
  const hour = now.getHours()
  const day = now.getDay()
  // 交易日 9:25-15:05
  if (day >= 1 && day <= 5 && hour >= 9 && hour < 16) {
    refreshTimer = setInterval(() => {
      fetchIntradayData()
      fetchScannerRuntime()
    }, 30000)
  }
}

onMounted(() => {
  fetchDbStats().then(() => {
    fetchIntradayMongoCounts()
  })
  fetchIntradayData()
  fetchScannerRuntime()
  startAutoRefresh()
})


/** 采补状态汇总计算 */
const collectionHealth = computed(() => {
  const cols = dataStatus.value?.collections || {}
  const results: { name: string; count: number; dateEnd: string; status: 'ok' | 'warn' | 'error'; statusText: string }[] = []
  const today = new Date()
  const yesterday = new Date(today.getTime() - 86400000)
  const todayStr = today.toISOString().slice(0, 10).replace(/-/g, '')
  const yesterdayStr = yesterday.toISOString().slice(0, 10).replace(/-/g, '')
  const fridayStr = new Date(today.getTime() - (today.getDay() + 2) % 7 * 86400000).toISOString().slice(0, 10).replace(/-/g, '')
  const expectedLatest = today.getDay() === 0 || today.getDay() === 6 ? fridayStr : yesterdayStr

  for (const [name, info] of Object.entries(cols)) {
    const col = info as any
    const count = col.count || 0
    const dateEnd = col.date_range?.end || 'N/A'
    let status: 'ok' | 'warn' | 'error' = 'ok'
    let statusText = '✅ 正常'

    if (count === 0) {
      status = 'error'
      statusText = '❌ 无数据'
    } else {
      const expected: Record<string, number> = {
        stock_daily_ak_full: 4000, daily_basic: 4000, limit_list: 50, index_daily: 1,
      }
      const minCount = expected[name]
      if (minCount && count > 0) {
        // 看最新日期是否是最近交易日
        const endNum = parseInt(dateEnd)
        const expectedNum = parseInt(expectedLatest)
        if (endNum < expectedNum - 3) {
          status = 'warn'
          statusText = `⚠️ 数据滞后(${dateEnd})`
        }
      }
    }

    results.push({ name, count, dateEnd, status, statusText })
  }
  return results
})

/** 因子覆盖率(最近5天) */
const recentCoverage = computed(() => {
  const coverage = dataStatus.value?.daily_coverage || []
  if (!coverage.length) return []
  return coverage.slice(-5).map((c: any) => ({
    date: c.date,
    total: c.total,
    rate: c.factor_rate,
    groups: c.groups || {},
  }))
})

/** 全量集合状态(按4大类分组) */
const allCollectionsStatus = computed(() => {
  const cols = dataStatus.value?.collections || {}
  return allCollectionCategories.map(cat => ({
    ...cat,
    collections: cat.collections.map(c => {
      const info = cols[c.name] as any || {}
      return {
        ...c,
        count: info.count || 0,
        dateRange: info.date_range || null,
        error: info.error || null,
        category: cat.category,
      }
    })
  }))
})

/** 全量集合总览统计 */
const allCollectionsSummary = computed(() => {
  const cols = dataStatus.value?.collections || {}
  let totalCollections = 0
  let okCollections = 0
  for (const cat of allCollectionCategories) {
    for (const c of cat.collections) {
      totalCollections++
      const info = cols[c.name] as any || {}
      if (info.count > 0) okCollections++
    }
  }
  return { total: totalCollections, ok: okCollections }
})
/** 健康评分 */
const healthScore = computed(() => dataStatus.value?.health_score ?? '-')
const healthBreakdown = computed(() => dataStatus.value?.health_breakdown || {})

/** 诊断信息 */
const diagnostics = computed(() => dataStatus.value?.diagnostics || [])
const actionItems = computed(() => dataStatus.value?.action_items || [])

/** 数据对齐状态 */
const dataAlignment = computed(() => dataStatus.value?.data_alignment || null)

/** 策略可用性 */
const strategyAvailability = computed(() => dataStatus.value?.strategy_availability || [])

/** 推荐回测区间 */
const recommendedRanges = computed(() => dataStatus.value?.recommended_ranges || [])

// ==================== 样式辅助 ====================

const statusMap: Record<string, { type: '' | 'success' | 'warning' | 'danger' | 'info', label: string }> = {
  active: { type: 'success', label: '主力' },
  fallback: { type: 'warning', label: '备用' },
  limited: { type: 'info', label: '有限' },
  deprecated: { type: 'danger', label: '已废弃' },
  legacy: { type: 'info', label: '历史' },
}

const getStatusTag = (status: string) => statusMap[status] || { type: 'info' as const, label: status }

const factorSourceTag = (source: string) => {
  const map: Record<string, { type: '' | 'success' | 'warning' | 'danger' | 'info', label: string }> = {
    '外部获取': { type: 'success', label: '获取' },
    '计算': { type: 'warning', label: '计算' },
    '外部获取+同步': { type: '', label: '获取+同步' },
    '实时获取': { type: 'danger', label: '实时' },
    '实时计算': { type: 'danger', label: '实时' },
    'DB读取': { type: 'info', label: 'DB' },
  }
  return map[source] || { type: 'info' as const, label: source }
}

const factorRowClass = ({ row }: { row: any }) => {
  if (row.unitNote) return 'row-with-note'
  if (row.source === '实时获取' || row.source === '实时计算') return 'row-realtime'
  if (row.source === '外部获取' || row.source === '外部获取+同步') return 'row-external'
  if (row.source === '计算') return 'row-compute'
  return ''
}

const levelColorMap: Record<string, string> = {
  P1: '#ef4444',
  P2: '#f59e0b',
  P3: '#6b7280',
  '✅': '#22c55e',
}

onMounted(() => {
  fetchDbStats().then(() => {
    fetchIntradayMongoCounts()
  })
  fetchIntradayData()
  fetchScannerRuntime()
  startAutoRefresh()
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
})
</script>

<template>
  <div class="data-source-page">
    <!-- 页面标题 -->
    <div class="page-header">
      <h2>数据获取</h2>
      <p class="subtitle">所有数据源配置、因子体系、单位标准和采补链路</p>
      <div v-if="dbStats.collections" class="db-stats-bar">
        <span>📦 MongoDB: {{ dbStats.total_documents?.toLocaleString() }} 文档 / {{ dbStats.collections?.length }} 集合</span>
        <span v-if="dbStats.mongodb_version"> | v{{ dbStats.mongodb_version }}</span>
      </div>
    </div>

    <!-- 采补链路 -->
    <ElCard class="section-card" shadow="never">
      <template #header>
        <div class="section-title" @click="toggleSection('pipeline')" style="cursor: pointer">
          <span class="section-icon">🔄</span>
          <span>每日采补链路</span>
          <span class="collapse-summary">
            <span class="summary-detail">15:35盘后(东方财富→搜狐→涨停池→因子补算→验证) · 07:00盘前(补采自愈) · 盘中(实时行情) · 每月1号(财务因子)</span>
          </span>
          <span class="toggle-hint">{{ expandedSections.pipeline ? '▼' : '▶' }}</span>
        </div>
      </template>
      <div v-show="expandedSections.pipeline" class="section-body">
      <div class="pipeline-flow">
        <div v-for="(step, idx) in pipelineSteps" :key="idx" class="pipeline-step" :class="{ 'step-even': idx % 2 === 0 }">
          <div class="step-time">{{ step.time }}</div>
          <div class="step-content">
            <div class="step-name">{{ step.step }}</div>
            <div class="step-script">{{ step.script }}</div>
            <div class="step-detail">{{ step.detail }}</div>
          </div>
          <div v-if="idx < pipelineSteps.length - 1" class="step-arrow">→</div>
        </div>
      </div>
      </div><!-- /section-body -->
    </ElCard>

    <!-- 数据采补状态 (默认展开) -->
    <ElCard class="section-card" shadow="never">
      <template #header>
        <div class="section-title" @click="toggleSection('status')" style="cursor: pointer">
          <span class="section-icon">📊</span>
          <span>数据采补状态</span>
          <span class="collapse-summary">
            <ElTag v-if="healthScore !== '-'" :type="(healthScore as number) >= 80 ? 'success' : (healthScore as number) >= 50 ? 'warning' : 'danger'" size="small">健康分: {{ healthScore }}</ElTag>
            <span v-if="collectionHealth.length" class="summary-detail">
              {{ collectionHealth.filter(c => c.status === 'ok').length }}/{{ collectionHealth.length }}集合正常
              <template v-if="dataAlignment">· 对齐{{ dataAlignment.common?.toLocaleString() }}条</template>
              <template v-if="strategyAvailability.length">· {{ strategyAvailability.filter((s: any) => s.available).length }}/{{ strategyAvailability.length }}策略可用</template>
            </span>
          </span>
          <span v-if="loading" style="margin-left: 8px; font-size: 12px; color: var(--text-tertiary)">加载中...</span>
          <span class="toggle-hint">{{ expandedSections.status ? '▼' : '▶' }}</span>
        </div>
      </template>

      <div v-show="expandedSections.status" class="section-body">

      <!-- 诊断信息 -->
      <div v-if="diagnostics.length > 0" class="diagnostics-bar">
        <div v-for="(d, i) in diagnostics" :key="i" class="diag-item" :class="d.level">
          <span class="diag-level">{{ d.level === 'red' ? '🔴' : d.level === 'yellow' ? '🟡' : '🟢' }}</span>
          <span>{{ d.message }}</span>
        </div>
      </div>

      <!-- 健康分拆解(始终可见) -->
      <div v-if="healthBreakdown.freshness_max" class="health-bar">
        <div class="health-item">
          <span class="health-label">数据新鲜度</span>
          <ElProgress :percentage="Math.round((healthBreakdown.freshness_score / healthBreakdown.freshness_max) * 100)" :stroke-width="10" :color="'#3b82f6'" style="flex: 1" />
          <span class="health-val">{{ healthBreakdown.freshness_score }}/{{ healthBreakdown.freshness_max }}</span>
        </div>
        <div class="health-item">
          <span class="health-label">因子覆盖率</span>
          <ElProgress :percentage="healthBreakdown.factor_max > 0 ? Math.round((healthBreakdown.factor_score / healthBreakdown.factor_max) * 100) : 0" :stroke-width="10" :color="'#f59e0b'" style="flex: 1" />
          <span class="health-val">{{ healthBreakdown.factor_score }}/{{ healthBreakdown.factor_max }}</span>
        </div>
        <div class="health-item">
          <span class="health-label">数据源可用</span>
          <ElProgress :percentage="healthBreakdown.source_max > 0 ? Math.round((healthBreakdown.source_score / healthBreakdown.source_max) * 100) : 0" :stroke-width="10" :color="'#10b981'" style="flex: 1" />
          <span class="health-val">{{ healthBreakdown.source_score }}/{{ healthBreakdown.source_max }}</span>
        </div>
      </div>

      <!-- 集合+覆盖+对齐+策略 二级折叠 -->
      <ElCollapse v-model="statusSubCollapse" class="status-sub-collapse">

      <!-- 集合状态(默认展开) -->
      <ElCollapseItem name="collections" class="sub-collapse-item">
        <template #title>
          <span class="sub-title" style="margin:0">关键集合状态</span>
          <span class="sub-summary">
            <span v-for="c in collectionHealth" :key="c.name" class="sub-summary-chip" :class="c.status">{{ c.name.replace('stock_daily_ak_full','ak_full').replace('daily_basic','basic') }} {{ c.count?.toLocaleString() }}</span>
          </span>
        </template>
        <div class="tab-note">按状态着色：✅绿色正常 · ⚠️黄色滞后 · ❌红色无数据</div>
        <ElTable :data="collectionHealth" size="small" stripe :row-class-name="({row}: any) => 'row-status-' + row.status">
          <ElTableColumn prop="name" label="集合" min-width="180">
            <template #default="{ row }">
              <span class="mono-text">{{ row.name }}</span>
            </template>
          </ElTableColumn>
          <ElTableColumn prop="count" label="记录数" width="120">
            <template #default="{ row }">
              {{ row.count?.toLocaleString() }}
            </template>
          </ElTableColumn>
          <ElTableColumn prop="dateEnd" label="最新日期" width="120" />
          <ElTableColumn label="状态" width="180">
            <template #default="{ row }">
              <ElTag :type="row.status === 'ok' ? 'success' : row.status === 'warn' ? 'warning' : 'danger'" size="small">{{ row.statusText }}</ElTag>
            </template>
          </ElTableColumn>
        </ElTable>
      </ElCollapseItem>

      <!-- 因子覆盖率 -->
      <ElCollapseItem name="coverage" class="sub-collapse-item">
        <template #title>
          <span class="sub-title" style="margin:0">最近因子覆盖率</span>
          <span class="sub-summary">
            <span v-for="c in recentCoverage" :key="c.date" class="sub-summary-chip" :class="c.rate >= 80 ? 'ok' : c.rate >= 50 ? 'warn' : 'error'">{{ String(c.date).slice(4) }} {{ c.rate }}%</span>
          </span>
        </template>
        <div class="tab-note">覆盖率≥80%为绿色，50-80%黄色，&lt;50%红色</div>
        <ElTable :data="recentCoverage" size="small" stripe :row-class-name="({row}: any) => row.rate >= 80 ? 'row-status-ok' : row.rate >= 50 ? 'row-status-warn' : 'row-status-error'">
          <ElTableColumn prop="date" label="日期" width="120" />
          <ElTableColumn prop="total" label="记录数" width="100" />
          <ElTableColumn label="核心覆盖率" width="140">
            <template #default="{ row }">
              <ElProgress :percentage="row.rate" :stroke-width="8" :color="row.rate >= 80 ? '#10b981' : row.rate >= 50 ? '#f59e0b' : '#ef4444'" />
            </template>
          </ElTableColumn>
          <ElTableColumn label="基础" width="80">
            <template #default="{ row }">
              <span :class="row.groups?.basic >= 80 ? 'cov-ok' : 'cov-bad'">{{ row.groups?.basic ?? '-' }}%</span>
            </template>
          </ElTableColumn>
          <ElTableColumn label="均线" width="80">
            <template #default="{ row }">
              <span :class="row.groups?.technical_ma >= 80 ? 'cov-ok' : 'cov-bad'">{{ row.groups?.technical_ma ?? '-' }}%</span>
            </template>
          </ElTableColumn>
          <ElTableColumn label="量价" width="80">
            <template #default="{ row }">
              <span :class="row.groups?.volume >= 80 ? 'cov-ok' : 'cov-bad'">{{ row.groups?.volume ?? '-' }}%</span>
            </template>
          </ElTableColumn>
          <ElTableColumn label="技术" width="80">
            <template #default="{ row }">
              <span :class="row.groups?.technical_talib >= 80 ? 'cov-ok' : 'cov-bad'">{{ row.groups?.technical_talib ?? '-' }}%</span>
            </template>
          </ElTableColumn>
          <ElTableColumn label="涨跌停" width="80">
            <template #default="{ row }">
              <span :class="row.groups?.limit >= 80 ? 'cov-ok' : 'cov-bad'">{{ row.groups?.limit ?? '-' }}%</span>
            </template>
          </ElTableColumn>
        </ElTable>
      </ElCollapseItem>

      <!-- 建议操作 -->
      <ElCollapseItem v-if="actionItems.length > 0" name="actions" class="sub-collapse-item">
        <template #title>
          <span class="sub-title" style="margin:0">建议操作</span>
          <span class="sub-summary">
            <span v-for="item in actionItems" :key="item.action" class="sub-summary-chip" :class="item.priority === 'high' ? 'error' : item.priority === 'medium' ? 'warn' : 'ok'">{{ item.action }}</span>
          </span>
        </template>
        <div v-for="(item, i) in actionItems" :key="i" class="action-item">
          <span class="action-level">{{ item.priority === 'high' ? '🔴' : item.priority === 'medium' ? '🟡' : '🟢' }}</span>
          <span>{{ item.action }}: {{ item.desc }}</span>
          <span v-if="item.command" class="mono-text action-cmd">{{ item.command }}</span>
        </div>
      </ElCollapseItem>

      <!-- 数据对齐 -->
      <ElCollapseItem v-if="dataAlignment" name="alignment" class="sub-collapse-item">
        <template #title>
          <span class="sub-title" style="margin:0">数据对齐</span>
          <span class="sub-summary">
            <span class="sub-summary-chip ok">{{ dataAlignment.common?.toLocaleString() }}交集</span>
            <ElTag v-if="dataAlignment.only_in_basic > 0 || dataAlignment.only_in_daily > 0" size="small" type="warning">差异</ElTag>
            <ElTag v-else size="small" type="success">一致</ElTag>
          </span>
        </template>
        <div class="alignment-grid">
          <div class="align-item">
            <span class="align-label">ak_full</span>
            <span class="align-val">{{ dataAlignment.stock_daily_count?.toLocaleString() }}</span>
          </div>
          <div class="align-item">
            <span class="align-label">daily_basic</span>
            <span class="align-val">{{ dataAlignment.daily_basic_count?.toLocaleString() }}</span>
          </div>
          <div class="align-item">
            <span class="align-label">交集</span>
            <span class="align-val">{{ dataAlignment.common?.toLocaleString() }}</span>
            <ElTag v-if="dataAlignment.only_in_basic > 0 || dataAlignment.only_in_daily > 0" type="warning" size="small">差异: basic独有{{ dataAlignment.only_in_basic }} daily独有{{ dataAlignment.only_in_daily }}</ElTag>
            <ElTag v-else type="success" size="small">完全一致</ElTag>
          </div>
        </div>
      </ElCollapseItem>

      <!-- 策略可用性 -->
      <ElCollapseItem v-if="strategyAvailability.length > 0" name="strategy" class="sub-collapse-item">
        <template #title>
          <span class="sub-title" style="margin:0">策略因子可用性</span>
          <span class="sub-summary">
            <span v-for="s in strategyAvailability" :key="s.name" class="sub-summary-chip" :class="s.available ? 'ok' : 'error'">{{ s.name }} {{ s.coverage }}%</span>
          </span>
        </template>
        <ElTable :data="strategyAvailability" size="small" stripe>
          <ElTableColumn prop="name" label="策略" width="120" />
          <ElTableColumn label="因子就绪" min-width="200">
            <template #default="{ row }">
              <span v-for="f in row.factors" :key="f" class="factor-chip">{{ f }}</span>
            </template>
          </ElTableColumn>
          <ElTableColumn label="覆盖率" width="120">
            <template #default="{ row }">
              <ElProgress :percentage="row.coverage" :stroke-width="8" :color="row.coverage >= 90 ? '#10b981' : row.coverage >= 70 ? '#f59e0b' : '#ef4444'" />
            </template>
          </ElTableColumn>
          <ElTableColumn label="状态" width="80">
            <template #default="{ row }">
              <ElTag :type="row.available ? 'success' : 'danger'" size="small">{{ row.available ? '可用' : '不可用' }}</ElTag>
            </template>
          </ElTableColumn>
        </ElTable>
      </ElCollapseItem>

      <!-- 推荐回测区间 -->
      <ElCollapseItem v-if="recommendedRanges.length > 0" name="ranges" class="sub-collapse-item">
        <template #title>
          <span class="sub-title" style="margin:0">推荐回测区间</span>
          <span class="sub-summary">
            <span v-for="r in recommendedRanges.slice(0, 3)" :key="r.start" class="sub-summary-chip ok">{{ r.start }}~{{ r.end }} ({{ r.factor_rate }}%)</span>
          </span>
        </template>
        <div v-for="(r, i) in recommendedRanges" :key="i" class="range-item">
          <span class="mono-text">{{ r.start }} ~ {{ r.end }}</span>
          <ElTag size="small" type="info">{{ r.factor_rate }}</ElTag>
        </div>
      </ElCollapseItem>

      </ElCollapse><!-- /statusSubCollapse -->
      </div><!-- /section-body -->
    </ElCard>

    <!-- 盘中实时采集状态 -->
    <ElCard class="section-card" shadow="never">
      <template #header>
        <div class="section-title">
          <span class="section-icon">⚡</span>
          <span>盘中实时采集状态</span>
          <ElTag v-if="scannerRuntimeStatus.overall_status === 'running'" type="success" size="small">运行中</ElTag>
          <ElTag v-else-if="scannerRuntimeStatus.overall_status === 'dead'" type="danger" size="small">未运行</ElTag>
          <ElTag v-else type="info" size="small">{{ scannerRuntimeStatus.overall_status || '未知' }}</ElTag>
          <span v-if="scannerRuntimeStatus.scan_lag_seconds != null && scannerRuntimeStatus.scan_lag_seconds >= 0" class="summary-detail">扫描延迟 {{ scannerRuntimeStatus.scan_lag_seconds }}s</span>
        </div>
      </template>

      <!-- Scanner状态概览 -->
      <div class="intraday-stats-grid">
        <div v-for="item in intradaySummary" :key="item.label" class="stat-card" :class="{ 'stat-warning': item.label === '熔断暂停' && item.value === '是' }">
          <span class="stat-icon">{{ item.icon }}</span>
          <div class="stat-info">
            <span class="stat-label">{{ item.label }}</span>
            <span class="stat-value">{{ item.value }}</span>
          </div>
        </div>
      </div>

      <!-- 警告信息 -->
      <div v-if="scannerRuntimeStatus.warnings?.length" class="diag-bar">
        <div v-for="(w, i) in scannerRuntimeStatus.warnings" :key="i" class="diag-item yellow">
          <span class="diag-level">🟡</span>
          <span>{{ w }}</span>
        </div>
      </div>

      <!-- 情绪曲线 + 信号分组 -->
      <ElCollapse class="status-sub-collapse">
        <ElCollapseItem name="sentiment" class="sub-collapse-item">
          <template #title>
            <span class="sub-title" style="margin:0">盘中情绪曲线</span>
            <span class="sub-summary">
              <span v-if="sentimentChartPoints.length" class="sub-summary-chip ok">{{ sentimentChartPoints.length }}点</span>
              <span v-if="sentimentChartPoints.length" class="sub-summary-chip" :class="sentimentChartPoints[sentimentChartPoints.length-1]?.score >= 50 ? 'ok' : 'warn'">最新 {{ sentimentChartPoints[sentimentChartPoints.length-1]?.score }}</span>
            </span>
          </template>
          <div v-if="sentimentChartPoints.length" class="sentiment-table-wrap">
            <ElTable :data="sentimentChartPoints" size="small" stripe max-height="300">
              <ElTableColumn prop="time" label="时间" width="70" />
              <ElTableColumn label="情绪分" width="80">
                <template #default="{ row }">
                  <span :class="row.score >= 50 ? 'cov-ok' : 'cov-bad'">{{ row.score }}</span>
                </template>
              </ElTableColumn>
              <ElTableColumn prop="period" label="阶段" width="80" />
              <ElTableColumn prop="limit_up" label="涨停" width="60" align="center" />
              <ElTableColumn prop="broken" label="炸板" width="60" align="center" />
              <ElTableColumn prop="broken_rate" label="炸板率" width="70" align="center" />
            </ElTable>
          </div>
          <div v-else class="text-muted" style="padding: 12px; font-size: 13px;">暂无盘中情绪数据</div>
        </ElCollapseItem>

        <ElCollapseItem name="signals" class="sub-collapse-item">
          <template #title>
            <span class="sub-title" style="margin:0">今日信号分组</span>
            <span class="sub-summary">
              <span v-for="s in signalsByStrategy" :key="s.name" class="sub-summary-chip ok">{{ s.name }} {{ s.count }}</span>
            </span>
          </template>
          <ElTable v-if="signalsByStrategy.length" :data="signalsByStrategy" size="small" stripe>
            <ElTableColumn prop="name" label="策略" min-width="120" />
            <ElTableColumn prop="count" label="信号数" width="100" align="right" />
          </ElTable>
          <div v-else class="text-muted" style="padding: 12px; font-size: 13px;">暂无信号数据</div>
        </ElCollapseItem>

        <ElCollapseItem name="realtime-collections" class="sub-collapse-item">
          <template #title>
            <span class="sub-title" style="margin:0">实时集合状态</span>
            <span class="sub-summary">
              <span v-for="c in intradayMongoCounts.filter(c => c.count > 0)" :key="c.name" class="sub-summary-chip ok">{{ c.name.replace('scanner_','').replace('sentiment_','') }} {{ c.count?.toLocaleString() }}</span>
            </span>
          </template>
          <div class="tab-note">盘中实时写入的MongoDB集合（今日是否更新）</div>
          <ElTable :data="intradayMongoCounts" size="small" stripe>
            <ElTableColumn prop="name" label="集合" min-width="200">
              <template #default="{ row }">
                <span class="mono-text">{{ row.name }}</span>
              </template>
            </ElTableColumn>
            <ElTableColumn prop="count" label="总记录数" width="120" align="right">
              <template #default="{ row }">
                {{ row.count?.toLocaleString() }}
              </template>
            </ElTableColumn>
            <ElTableColumn prop="dateEnd" label="最新日期" width="140" align="center" />
            <ElTableColumn label="状态" width="80" align="center">
              <template #default="{ row }">
                <span v-if="row.dateEnd === new Date().toISOString().slice(0,10) || row.dateEnd === new Date().toISOString().slice(0,10).replace(/-/g,'')">✅</span>
                <span v-else>⏳</span>
              </template>
            </ElTableColumn>
          </ElTable>
        </ElCollapseItem>
      </ElCollapse>
    </ElCard>

    <!-- 今日因子覆盖率详情 -->
    <ElCard class="section-card" shadow="never">
      <template #header>
        <div class="section-title">
          <span class="section-icon">🧪</span>
          <span>今日因子覆盖率详情</span>
          <span class="summary-detail">最新交易日每个因子的覆盖率(%)</span>
        </div>
      </template>
      <div v-if="factorDetailRows.length" class="factor-detail-grid">
        <div v-for="gname in ['基础', '技术MA', '技术TALib', '量价', '涨跌停']" :key="gname" class="factor-detail-group">
          <div class="fdg-header">
            <span class="fdg-name">{{ gname }}</span>
            <ElTag size="small" :type="factorDetailRows.filter(r => r.group === gname).every(r => r.rate >= 90) ? 'success' : 'warning'">
              {{ factorDetailRows.filter(r => r.group === gname).filter(r => r.rate >= 90).length }}/{{ factorDetailRows.filter(r => r.group === gname).length }}
            </ElTag>
          </div>
          <div v-for="row in factorDetailRows.filter(r => r.group === gname)" :key="row.factor" class="fdg-item">
            <span class="fdg-factor">{{ row.factor }}</span>
            <ElProgress :percentage="row.rate" :stroke-width="6" :color="row.rate >= 90 ? '#10b981' : row.rate >= 50 ? '#f59e0b' : '#ef4444'" :show-text="false" style="flex: 1; min-width: 60px" />
            <span class="fdg-rate" :class="row.status === 'ok' ? 'cov-ok' : 'cov-bad'">{{ row.rate.toFixed(1) }}%</span>
          </div>
        </div>
      </div>
      <div v-else class="text-muted" style="padding: 16px; font-size: 13px;">暂无因子覆盖率数据</div>
    </ElCard>

    <!-- 其余区块用折叠包裹 -->
    <ElCollapse v-model="mainCollapse" class="main-collapse">

    <!-- 全量数据状态 -->
    <ElCollapseItem name="all-collections">
      <template #title>
        <div class="section-title collapsible-title">
          <span class="section-icon">🗄️</span>
          <span>全量数据状态</span>
          <span class="collapse-summary">
            <ElTag size="small" type="info">{{ allCollectionsSummary.total }}集合</ElTag>
            <ElTag size="small" :type="allCollectionsSummary.ok === allCollectionsSummary.total ? 'success' : 'warning'">{{ allCollectionsSummary.ok }}/{{ allCollectionsSummary.total }}有数据</ElTag>
            <span class="summary-detail">4大类: 行情4 + 交易4 + 状态5 + 展示6</span>
          </span>
        </div>
      </template>

      <p class="factor-intro">
        系统共 <strong>{{ allCollectionsSummary.total }}个集合</strong>，按4大类分组。
        审查定时任务4个：因子影响(日16:00) + 交易数据(日16:10) + 使用侧一致性(周一20:00) + 数据单位验证(日16:40)。
      </p>

      <!-- 按类别展示 -->
      <div v-for="cat in allCollectionsStatus" :key="cat.category" class="collection-category">
        <div class="cat-header-row" :style="{ borderLeftColor: cat.color }">
          <span class="cat-icon-lg">{{ cat.icon }}</span>
          <span class="cat-name-lg" :style="{ color: cat.color }">{{ cat.category }}</span>
          <ElTag size="small" type="info">{{ cat.collections.length }}集合</ElTag>
          <span class="cat-desc">{{ cat.description }}</span>
        </div>
        <ElTable :data="cat.collections" size="small" stripe class="cat-table">
          <ElTableColumn label="集合" min-width="200">
            <template #default="{ row }">
              <span class="col-name">{{ row.name }}</span>
            </template>
          </ElTableColumn>
          <ElTableColumn label="说明" min-width="180">
            <template #default="{ row }">
              <span>{{ row.desc }}</span>
            </template>
          </ElTableColumn>
          <ElTableColumn label="条数" width="100" align="right">
            <template #default="{ row }">
              <span :class="{ 'text-muted': row.count === 0 }">{{ row.count > 0 ? row.count.toLocaleString() : '0' }}</span>
            </template>
          </ElTableColumn>
          <ElTableColumn label="最新日期" width="120" align="center">
            <template #default="{ row }">
              <span v-if="row.dateRange" class="date-range-end">{{ row.dateRange.end }}</span>
              <span v-else class="text-muted">-</span>
            </template>
          </ElTableColumn>
          <ElTableColumn label="日期字段" width="100" align="center">
            <template #default="{ row }">
              <span class="text-muted">{{ row.keyField }}</span>
            </template>
          </ElTableColumn>
          <ElTableColumn label="预期更新" width="80" align="center">
            <template #default="{ row }">
              <ElTag size="small" :type="row.freshness === '实时' ? 'success' : 'info'" effect="plain">{{ row.freshness }}</ElTag>
            </template>
          </ElTableColumn>
          <ElTableColumn label="状态" width="80" align="center">
            <template #default="{ row }">
              <span v-if="row.error">❌</span>
              <span v-else-if="row.count === 0">🟡</span>
              <span v-else>✅</span>
            </template>
          </ElTableColumn>
        </ElTable>
      </div>

      <!-- 审查定时任务 -->
      <div class="audit-rules-section">
        <h4 class="sub-section-title">🔍 审查定时任务</h4>
        <ElTable :data="auditRules" size="small" stripe>
          <ElTableColumn prop="dimension" label="审查维度" min-width="160" />
          <ElTableColumn prop="schedule" label="调度" width="140" align="center" />
          <ElTableColumn prop="script" label="脚本" min-width="180" />
          <ElTableColumn prop="checks" label="检查项" min-width="300" />
        </ElTable>
      </div>
    </ElCollapseItem>

    <!-- 因子体系 -->
    <ElCollapseItem name="factors">
      <template #title>
        <div class="section-title collapsible-title">
          <span class="section-icon">🧮</span>
          <span>因子体系</span>
          <span class="collapse-summary">
            <ElTag size="small" type="success">46+因子</ElTag>
            <ElTag size="small" type="info">8大类</ElTag>
            <span class="summary-detail">技术7 / 动量9 / 流动性6 / 涨跌停9 / 回调4 / 价值3 / 质量4 / 实时4</span>
          </span>
        </div>
      </template>
      <p class="factor-intro">
        因子来源分3种：<strong>外部获取</strong>(数据源直接提供) → <strong>计算</strong>(从原始数据推导) → <strong>实时计算</strong>(盘中每轮扫描)。<br/>
        因子计算脚本3个：lightweight_factor_fill.py(主力) / daily_factor_precompute.py(策略专用) / factor_auto_compute.py(回测自动补算)。<br/>
        盘中还有 strategy_scorer.py 实时合并T-1日因子(加_prev后缀)和实时行情。
      </p>

      <ElCollapse>
        <ElCollapseItem v-for="cat in factorCategories" :key="cat.category" :name="cat.category">
          <template #title>
            <div class="factor-cat-header">
              <span class="cat-icon">{{ cat.icon }}</span>
              <span class="cat-name">{{ cat.category }}</span>
              <ElTag size="small" :color="cat.color" effect="dark" style="border: none; color: white; margin-left: 8px">{{ cat.factors.length }}个</ElTag>
            </div>
          </template>
          <ElTable :data="cat.factors" size="small" stripe :row-class-name="factorRowClass" class="factor-table">
            <ElTableColumn label="因子" min-width="220">
              <template #default="{ row }">
                <span class="factor-name">{{ row.name }}</span>
                <ElTooltip v-if="row.unitNote" :content="row.unitNote" placement="top">
                  <span class="unit-badge">⚠️</span>
                </ElTooltip>
              </template>
            </ElTableColumn>
            <ElTableColumn label="来源" width="100">
              <template #default="{ row }">
                <ElTag :type="factorSourceTag(row.source).type" size="small" effect="plain">{{ factorSourceTag(row.source).label }}</ElTag>
              </template>
            </ElTableColumn>
            <ElTableColumn prop="compute" label="计算逻辑" min-width="240" />
            <ElTableColumn prop="script" label="计算脚本" min-width="200">
              <template #default="{ row }">
                <span class="mono-text">{{ row.script }}</span>
              </template>
            </ElTableColumn>
            <ElTableColumn prop="collection" label="写入集合" width="160">
              <template #default="{ row }">
                <span class="mono-text">{{ row.collection }}</span>
              </template>
            </ElTableColumn>
            <ElTableColumn label="调度/单位" min-width="160">
              <template #default="{ row }">
                <div>{{ row.schedule }}</div>
              </template>
            </ElTableColumn>
          </ElTable>
        </ElCollapseItem>
      </ElCollapse>
    </ElCollapseItem>

    <!-- 因子计算脚本 -->
    <ElCollapseItem name="scripts">
      <template #title>
        <div class="section-title collapsible-title">
          <span class="section-icon">🔧</span>
          <span>因子计算脚本</span>
          <span class="collapse-summary">
            <span class="summary-detail">lightweight_factor_fill(主力659行) · daily_factor_precompute(237行) · factor_auto_compute(574行) · strategy_scorer(盘中613行)</span>
          </span>
        </div>
      </template>
      <ElCollapse>
        <ElCollapseItem v-for="scr in factorScripts" :key="scr.name" :name="scr.name">
          <template #title>
            <div class="script-header">
              <span class="script-name">{{ scr.name }}</span>
              <span class="script-desc">{{ scr.description }}</span>
              <span class="script-lines">{{ scr.lineCount }}行</span>
            </div>
          </template>
          <div class="script-functions">
            <div v-for="fn in scr.functions" :key="fn.fn" class="fn-item">
              <div class="fn-header">
                <span class="fn-name">{{ fn.fn }}</span>
                <span class="fn-desc">{{ fn.desc }}</span>
              </div>
              <div v-if="fn.note" class="fn-note">📌 {{ fn.note }}</div>
            </div>
          </div>
        </ElCollapseItem>
      </ElCollapse>
    </ElCollapseItem>

    <!-- 数据源列表 -->
    <ElCollapseItem name="sources">
      <template #title>
        <div class="section-title collapsible-title">
          <span class="section-icon">📡</span>
          <span>数据源配置</span>
          <span class="collapse-summary">
            <ElTag size="small" type="success">东方财富(主力)</ElTag>
            <ElTag size="small" type="warning">搜狐/AKShare/Tushare(备用)</ElTag>
            <ElTag size="small" type="info">必盈(有限)</ElTag>
            <ElTag size="small" type="danger">量脉(废弃)</ElTag>
          </span>
        </div>
      </template>
      <ElCollapse>
        <ElCollapseItem v-for="src in dataSources" :key="src.id" :name="src.id">
          <template #title>
            <div class="source-header" :class="'src-status-' + src.status">
              <span class="source-icon">{{ src.icon }}</span>
              <span class="source-name">{{ src.name }}</span>
              <ElTag :type="getStatusTag(src.status).type" size="small" effect="dark">{{ getStatusTag(src.status).label }}</ElTag>
              <span class="source-priority">优先级 #{{ src.priority }}</span>
            </div>
          </template>
          <div class="source-detail">
            <ElDescriptions :column="2" border size="small">
              <ElDescriptionsItem label="写入集合">{{ src.collections.join(', ') }}</ElDescriptionsItem>
              <ElDescriptionsItem label="使用脚本">{{ src.scripts.join(', ') }}</ElDescriptionsItem>
              <ElDescriptionsItem label="调度时间">{{ src.schedule }}</ElDescriptionsItem>
              <ElDescriptionsItem label="频率限制">{{ src.rateLimit }}</ElDescriptionsItem>
              <ElDescriptionsItem label="可用字段" :span="2">{{ src.fields }}</ElDescriptionsItem>
              <ElDescriptionsItem label="备注" :span="2">{{ src.notes }}</ElDescriptionsItem>
            </ElDescriptions>

            <!-- 单位警告 -->
            <div v-if="src.unitWarnings.length > 0" class="unit-warnings" :class="{ 'unit-critical': src.unitWarnings.some((w: string) => w.startsWith('⚠️')) }">
              <div class="warning-title">⚠️ 单位转换注意事项</div>
              <div v-for="(w, i) in src.unitWarnings" :key="i" class="warning-item" :class="{ critical: w.startsWith('⚠️') }">
                <span class="warning-dot">{{ w.startsWith('⚠️') ? '🚨' : '•' }}</span>
                {{ w.replace('⚠️ ', '') }}
              </div>
            </div>
          </div>
        </ElCollapseItem>
      </ElCollapse>
    </ElCollapseItem>

    <!-- MongoDB字段单位标准 -->
    <ElCollapseItem name="standards">
      <template #title>
        <div class="section-title collapsible-title">
          <span class="section-icon">📏</span>
          <span>MongoDB字段单位标准</span>
          <span class="collapse-summary">
            <ElTag size="small" type="danger">⚠️ circ_mv/total_mv 跨集合差10000倍</ElTag>
            <span class="summary-detail">ak_full=万元 vs daily_basic=亿元</span>
          </span>
        </div>
      </template>

      <!-- 跨集合关键差异 -->
      <ElAlert
        title="跨集合关键差异"
        type="error"
        :closable="false"
        show-icon
        style="margin-bottom: 16px"
      >
        <div v-for="diff in crossCollectionDiffs" :key="diff.field" class="diff-item">
          <strong>{{ diff.field }}</strong>: stock_daily_ak_full={{ diff.ak_full }} vs daily_basic={{ diff.daily_basic }}
          (差{{ diff.ratio }}倍) — {{ diff.impact }}
        </div>
      </ElAlert>

      <ElCollapse>
        <ElCollapseItem v-for="col in collectionStandards" :key="col.collection" :name="col.collection">
          <template #title>
            <div class="collection-header">
              <span class="collection-name">{{ col.collection }}</span>
              <span class="collection-desc">{{ col.description }}</span>
            </div>
          </template>
          <ElTable :data="col.fields" size="small" stripe>
            <ElTableColumn prop="field" label="字段" min-width="200" />
            <ElTableColumn prop="unit" label="标准单位" width="100" />
            <ElTableColumn prop="example" label="示例" min-width="150" />
            <ElTableColumn prop="range" label="合理范围" width="120" />
            <ElTableColumn label="警告" min-width="180">
              <template #default="{ row }">
                <ElTag v-if="row.warning" type="danger" size="small">{{ row.warning }}</ElTag>
                <span v-else>—</span>
              </template>
            </ElTableColumn>
          </ElTable>
        </ElCollapseItem>
      </ElCollapse>
    </ElCollapseItem>

    <!-- 历史bug记录 -->
    <ElCollapseItem name="bugs">
      <template #title>
        <div class="section-title collapsible-title">
          <span class="section-icon">🐛</span>
          <span>历史单位bug记录</span>
          <span class="collapse-summary">
            <ElTag size="small" type="success">全部已修 ✅</ElTag>
            <span class="summary-detail">{{ historicalBugs.length }}个历史bug(换手率×100/首板为0/circ_mv单位混乱/策略名不匹配/tushare未转换/6个脚本修复)</span>
          </span>
        </div>
      </template>
      <ElTable :data="historicalBugs" size="small" stripe :row-class-name="({row}: any) => row.date.includes('07-02') ? 'row-critical' : 'row-warning'" class="bug-table">
        <ElTableColumn prop="date" label="日期" width="140" />
        <ElTableColumn prop="bug" label="Bug" min-width="220" />
        <ElTableColumn prop="impact" label="影响" min-width="180" />
        <ElTableColumn prop="rootCause" label="根因" min-width="200" />
        <ElTableColumn prop="fix" label="修复" min-width="160" />
      </ElTable>
    </ElCollapseItem>

    <!-- 已知未修问题 -->
    <ElCollapseItem name="issues">
      <template #title>
        <div class="section-title collapsible-title">
          <span class="section-icon">⚠️</span>
          <span>已知未修问题</span>
          <span class="collapse-summary">
            <ElTag size="small" type="success">全部已修 ✅</ElTag>
            <span class="summary-detail">6个已知单位bug均已修复</span>
          </span>
        </div>
      </template>
      <ElTable :data="knownIssues" size="small" stripe class="fixed-issue-table">
        <ElTableColumn label="级别" width="70">
          <template #default="{ row }">
            <ElTag :color="levelColorMap[row.level]" effect="dark" size="small" style="border: none; color: white">{{ row.level }}</ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn prop="script" label="脚本" width="220" />
        <ElTableColumn prop="issue" label="问题" min-width="300" />
        <ElTableColumn prop="impact" label="影响" min-width="250" />
      </ElTable>
    </ElCollapseItem>

    </ElCollapse><!-- /main-collapse -->
  </div>
</template>

<style scoped lang="scss">
.data-source-page {
  padding: 24px;
  max-width: 1400px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: 24px;
  h2 {
    margin: 0 0 4px 0;
    font-size: 20px;
    font-weight: 700;
    color: var(--text-primary);
  }
  .subtitle {
    margin: 0;
    font-size: 13px;
    color: var(--text-secondary);
  }

  .db-stats-bar {
    margin-top: 6px;
    font-size: 12px;
    color: var(--text-tertiary);
    font-family: monospace;
  }
}

// 数据采补状态
.diagnostics-bar {
  margin-bottom: 16px;
  .diag-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 12px;
    margin-bottom: 4px;
    border-radius: 6px;
    font-size: 13px;
    &.red { background: rgba(239, 68, 68, 0.08); color: #dc2626; }
    &.yellow { background: rgba(245, 158, 11, 0.08); color: #d97706; }
    &.green { background: rgba(16, 185, 129, 0.08); color: #059669; }
    .diag-level { font-size: 14px; }
  }
}

.health-bar {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
  padding: 12px;
  background: var(--bg-muted);
  border-radius: 8px;
}

.health-item {
  display: flex;
  align-items: center;
  gap: 10px;
  .health-label { font-size: 13px; min-width: 80px; color: var(--text-secondary); }
  .health-val { font-size: 12px; color: var(--text-tertiary); font-family: monospace; min-width: 40px; text-align: right; }
}

.collection-status, .coverage-section, .action-items {
  margin-bottom: 16px;
}

.sub-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.cov-ok { color: #10b981; font-weight: 600; }
.cov-bad { color: #ef4444; font-weight: 600; }

.action-items {
  .action-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 0;
    font-size: 13px;
    .action-level { font-size: 14px; }
    .action-cmd { font-size: 11px; color: var(--text-tertiary); background: var(--bg-muted); padding: 2px 6px; border-radius: 3px; }
  }
}

.alignment-section, .strategy-avail-section, .ranges-section {
  margin-bottom: 16px;
}

.alignment-grid {
  display: flex;
  gap: 16px;
  padding: 8px 12px;
  background: var(--bg-muted);
  border-radius: 6px;
}

.align-item {
  display: flex;
  align-items: center;
  gap: 6px;
  .align-label { font-size: 12px; color: var(--text-secondary); }
  .align-val { font-size: 14px; font-weight: 600; font-family: monospace; }
}

.factor-chip {
  display: inline-block;
  font-size: 11px;
  padding: 1px 6px;
  margin: 1px 2px;
  border-radius: 3px;
  background: var(--bg-muted);
  font-family: monospace;
}

.range-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 3px 0;
  font-size: 13px;
}

.collapsible-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.collapse-summary {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-left: 8px;
}

.summary-detail {
  font-size: 11px;
  color: var(--text-tertiary);
  font-family: monospace;
}

.sub-summary {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
  margin-left: 8px;
}

.sub-summary-chip {
  display: inline-block;
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 3px;
  font-family: monospace;
  line-height: 1.5;

  &.ok {
    background: rgba(16, 185, 129, 0.1);
    color: #059669;
  }
  &.warn {
    background: rgba(245, 158, 11, 0.1);
    color: #d97706;
  }
  &.error {
    background: rgba(239, 68, 68, 0.1);
    color: #dc2626;
  }
}

.toggle-hint {
  margin-left: auto;
  font-size: 11px;
  color: var(--text-tertiary);
  transition: transform 0.2s;
}

.main-collapse {
  border: none;
  margin-bottom: 20px;

  :deep(.el-collapse-item__header) {
    background: var(--bg-card, #fff);
    border: 1px solid var(--border-default);
    border-radius: 12px;
    padding: 14px 20px;
    margin-bottom: 8px;
    height: auto;
    line-height: 1.5;
  }

  :deep(.el-collapse-item__wrap) {
    border: none;
    border-radius: 0 0 12px 12px;
    margin-top: -8px;
    margin-bottom: 8px;
  }

  :deep(.el-collapse-item__content) {
    padding: 12px 20px 20px;
  }
}

.status-sub-collapse {
  border: none;
  margin-bottom: 8px;

  :deep(.el-collapse-item__header) {
    background: var(--bg-muted);
    border-radius: 8px;
    padding: 8px 14px;
    margin-bottom: 4px;
    height: auto;
    line-height: 1.5;
    border: none;
    font-size: 13px;
  }

  :deep(.el-collapse-item__wrap) {
    border: none;
  }

  :deep(.el-collapse-item__content) {
    padding: 8px 0;
  }
}

.section-body {
  // 无额外样式，仅做v-show容器
}

.section-card {
  margin-bottom: 20px;
  border-radius: 12px;

  :deep(.el-card__header) {
    padding: 14px 20px;
    border-bottom: 1px solid var(--border-default);
  }

  :deep(.el-card__body) {
    padding: 16px 20px;
  }
}

.section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);

  .section-icon {
    font-size: 18px;
  }
}

// 采补链路
.pipeline-flow {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: flex-start;
}

.pipeline-step {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex: 0 0 auto;
  min-width: 140px;

  .step-time {
    font-size: 11px;
    font-weight: 600;
    color: var(--primary-500);
    background: var(--primary-50);
    padding: 2px 10px;
    border-radius: 10px;
    margin-bottom: 6px;
  }

  .step-content {
    background: var(--bg-muted);
    border: 1px solid var(--border-default);
    border-radius: 8px;
    padding: 10px 14px;
    text-align: center;

    .step-name {
      font-size: 13px;
      font-weight: 600;
      color: var(--text-primary);
      margin-bottom: 2px;
    }

    .step-script {
      font-size: 11px;
      color: var(--text-tertiary);
      font-family: monospace;
      margin-bottom: 4px;
    }

    .step-detail {
      font-size: 11px;
      color: var(--text-secondary);
      line-height: 1.4;
    }
  }

  .step-arrow {
    font-size: 18px;
    color: var(--text-tertiary);
    margin-top: 8px;
  }
}

// 数据源折叠面板
.source-header {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;

  .source-icon { font-size: 18px; }
  .source-name { font-weight: 600; font-size: 14px; }
  .source-priority { font-size: 12px; color: var(--text-tertiary); margin-left: auto; }
}

.source-detail {
  padding: 8px 0;
}

.unit-warnings {
  margin-top: 12px;
  padding: 10px 14px;
  background: #fef3c7;
  border: 1px solid #fbbf24;
  border-radius: 8px;

  .warning-title {
    font-size: 13px;
    font-weight: 600;
    color: #92400e;
    margin-bottom: 6px;
  }

  .warning-item {
    font-size: 12px;
    color: #78350f;
    line-height: 1.6;
    padding-left: 8px;

    .warning-dot {
      color: #f59e0b;
      &.critical { color: #ef4444; }
    }
  }
}

// 深色模式适配
:root.dark .unit-warnings {
  background: rgba(251, 191, 36, 0.1);
  border-color: rgba(251, 191, 36, 0.3);
  .warning-title { color: #fbbf24; }
  .warning-item { color: #d4a017; }
}

// 集合标准
.collection-header {
  display: flex;
  align-items: center;
  gap: 10px;

  .collection-name {
    font-family: monospace;
    font-weight: 600;
    font-size: 14px;
    color: var(--primary-500);
  }

  .collection-desc {
    font-size: 13px;
    color: var(--text-secondary);
  }
}

.diff-item {
  font-size: 13px;
  line-height: 1.8;
}

// 因子体系
.factor-intro {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.8;
  margin: 0 0 16px 0;
  strong { color: var(--text-primary); }
}

.factor-cat-header {
  display: flex;
  align-items: center;
  gap: 6px;
  .cat-icon { font-size: 16px; }
  .cat-name { font-weight: 600; font-size: 14px; }
}

.factor-name {
  font-family: monospace;
  font-size: 12px;
  font-weight: 500;
}

.mono-text {
  font-family: monospace;
  font-size: 11px;
  color: var(--text-secondary);
}

.unit-note {
  font-size: 11px;
  color: #ef4444;
  margin-top: 2px;
}

:deep(.row-with-note) {
  background: rgba(239, 68, 68, 0.03) !important;
}

// 因子脚本
.script-header {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;

  .script-name {
    font-family: monospace;
    font-weight: 600;
    font-size: 13px;
    color: var(--primary-500);
  }

  .script-desc {
    font-size: 13px;
    color: var(--text-secondary);
  }

  .script-lines {
    font-size: 11px;
    color: var(--text-tertiary);
    margin-left: auto;
  }
}

.script-functions {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 4px 0;
}

.fn-item {
  background: var(--bg-muted);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  padding: 8px 14px;

  .fn-header {
    display: flex;
    align-items: baseline;
    gap: 10px;
    margin-bottom: 4px;
  }

  .fn-name {
    font-family: monospace;
    font-weight: 600;
    font-size: 13px;
    color: var(--primary-500);
    flex-shrink: 0;
  }

  .fn-desc {
    font-size: 13px;
    color: var(--text-primary);
  }

  .fn-note {
    font-size: 12px;
    color: #f59e0b;
    line-height: 1.5;
  }
}

/* 全量数据状态 */
.collection-category {
  margin-bottom: 16px;
}
.cat-header-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  padding: 4px 0;
}
.cat-icon-lg {
  font-size: 20px;
}
.cat-name-lg {
  font-size: 15px;
  font-weight: 600;
}
.cat-desc {
  font-size: 12px;
  color: var(--text-tertiary);
}
.cat-table {
  margin-bottom: 4px;
}
.col-name {
  font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
  font-size: 12px;
  font-weight: 500;
}
.date-range-end {
  font-family: 'Menlo', 'Monaco', monospace;
  font-size: 12px;
}
.text-muted {
  color: var(--text-quaternary);
}
.audit-rules-section {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--border-light);
}
.sub-section-title {
  font-size: 14px;
  font-weight: 600;
  margin: 0 0 8px 0;
}

/* 交易归档 */

/* ===== 数据获取页面新增样式 ===== */

/* 表格行着色 */
.tab-note {
  font-size: 12px;
  color: var(--text-quaternary);
  margin-bottom: 8px;
  padding: 0 2px;
}

:deep(.row-status-ok) { background: rgba(34,197,94,0.05) !important; }
:deep(.row-status-warn) { background: rgba(245,158,11,0.06) !important; }
:deep(.row-status-error) { background: rgba(239,68,68,0.06) !important; }

/* 因子表行着色 */
:deep(.row-realtime) { background: rgba(236,72,153,0.05) !important; }
:deep(.row-external) { background: rgba(34,197,94,0.05) !important; }
:deep(.row-compute) { background: rgba(59,130,246,0.05) !important; }
:deep(.row-with-note) { background: rgba(245,158,11,0.06) !important; }

/* Bug表行着色 */
:deep(.row-critical) { background: rgba(239,68,68,0.08) !important; }
:deep(.row-warning) { background: rgba(245,158,11,0.06) !important; }

/* 单位badge(因子名旁) */
.unit-badge {
  cursor: help;
  font-size: 12px;
  margin-left: 4px;
  vertical-align: middle;
}

/* 集合类别头颜色条 */
.cat-header-row {
  border-left: 4px solid transparent;
  padding-left: 8px;
}

/* 管道步骤交替色 */
.pipeline-step.step-even {
  .step-content {
    background: rgba(59,130,246,0.03);
  }
}
.pipeline-step:not(.step-even) {
  .step-content {
    background: rgba(16,185,129,0.03);
  }
}

/* 数据源头部着色 */
.source-header {
  &.src-status-active {
    border-left: 3px solid #22c55e;
    padding-left: 8px;
    border-radius: 4px;
  }
  &.src-status-fallback {
    border-left: 3px solid #f59e0b;
    padding-left: 8px;
    border-radius: 4px;
  }
  &.src-status-limited {
    border-left: 3px solid #3b82f6;
    padding-left: 8px;
    border-radius: 4px;
  }
  &.src-status-deprecated {
    border-left: 3px solid #ef4444;
    padding-left: 8px;
    border-radius: 4px;
  }
  &.src-status-legacy {
    border-left: 3px solid #6b7280;
    padding-left: 8px;
    border-radius: 4px;
  }
}

/* 单位警告区-严重时红框 */
.unit-warnings.unit-critical {
  border-color: #ef4444 !important;
  background: rgba(239,68,68,0.04) !important;
}

.unit-warnings .warning-item.critical {
  color: #dc2626;
  font-weight: 600;
}

/* 已修issue表-绿色主题 */
.fixed-issue-table {
  :deep(tr) {
    opacity: 0.75;
  }
  :deep(tr:hover) {
    opacity: 1;
  }
}

/* 因子表(轻微内边距) */
.factor-table {
  margin-bottom: 8px;
}

/* 盘中实时采集状态 */
.intraday-stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 10px;
  margin-bottom: 16px;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  background: var(--bg-muted);
  border-radius: 8px;
  border: 1px solid var(--border-light);
  transition: border-color 0.2s;

  &.stat-warning {
    border-color: #ef4444;
    background: rgba(239, 68, 68, 0.05);
  }
}

.stat-icon {
  font-size: 20px;
}

.stat-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.stat-label {
  font-size: 11px;
  color: var(--text-tertiary);
}

.stat-value {
  font-size: 16px;
  font-weight: 700;
  font-family: monospace;
  color: var(--text-primary);
}

.diag-bar {
  margin-bottom: 12px;
}

.sentiment-table-wrap {
  max-height: 320px;
  overflow-y: auto;
}

/* 今日因子覆盖率详情 */
.factor-detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 16px;
}

.factor-detail-group {
  background: var(--bg-muted);
  border-radius: 10px;
  padding: 12px 14px;
  border: 1px solid var(--border-light);
}

.fdg-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border-light);
}

.fdg-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.fdg-item {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.fdg-factor {
  font-family: monospace;
  font-size: 11px;
  color: var(--text-secondary);
  min-width: 80px;
}

.fdg-rate {
  font-size: 11px;
  font-weight: 600;
  font-family: monospace;
  min-width: 45px;
  text-align: right;
}
</style>
