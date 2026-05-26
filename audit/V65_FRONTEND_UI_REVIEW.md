# V65 前端UI审查报告

**审查日期**: 2026-05-27  
**审查范围**: 16个前端文件 + 3个后端API文件  
**审查人**: subagent (frontend-ui-review)

---

## P0 - 必须修复(数据显示错误)

| ID | 文件 | 行号 | 问题 | 影响 | 修复方案 |
|----|------|------|------|------|----------|
| P0-1 | strategyDefaults.ts | - | 首板打板 `hit_probability_normal: 0.45` vs 后端 `0.40`; `hit_probability_slow: 0.6` vs 后端 `0.50` | 前端默认参数与后端不一致，用户未改参数时回测使用前端传的0.45/0.6而非后端0.40/0.50，导致回测结果偏差 | 同步脚本重新运行，将hit_probability_normal改为0.40, hit_probability_slow改为0.50 |
| P0-2 | strategyDefaults.ts | - | 首板打板 `take_profit_pct: 0.08` vs 后端 `0.10`; `stop_loss_pct: 0.03` vs 后端 `0.03`(一致); 但首板打板后端新增了`trailing_stop_pct: 0.02`前端缺失 | 止盈参数不一致(8% vs 10%)，首板实际止盈更宽；缺少追踪止损参数 | 同步脚本重新运行，take_profit_pct改为0.10，增加trailing_stop_pct |
| P0-3 | strategyDefaults.ts | - | 半路追涨 `stop_loss_pct: 0.04` vs 后端 `0.03` | 半路追涨止损4% vs 后端3%，前端默认值比后端宽松1%，可能误导用户 | 同步脚本重新运行，stop_loss_pct改为0.03，增加trailing_stop_pct: 0.02 |
| P0-4 | strategyDefaults.ts | - | 跌停翘板 `take_profit_pct: 0.2` vs 后端 `0.20`(一致)但后端新增`trailing_stop_pct: 0.04`前端缺失; 龙头低吸后端新增`trailing_stop_pct: 0.03`前端缺失 | 4个策略的追踪止损参数全部缺失，前端无法配置追踪止损 | 同步脚本重新运行，增加所有策略的trailing_stop_pct |
| P0-5 | strategyDefaults.ts | - | `max_total_position: 0.7` vs 后端 `0.75` | 前端总仓位上限70% vs 后端75%，V62已从70%提升到75%但前端未同步 | 同步脚本重新运行，改为0.75 |

## P1 - 建议修复(参数不一致/体验问题)

| ID | 文件 | 行号 | 问题 | 影响 | 修复方案 |
|----|------|------|------|------|----------|
| P1-1 | UltraShortBacktestViewV2.vue | form.forceEmpty | `limit_down_count: 50` 硬编码默认值 vs 后端GLOBAL_RISK `force_empty_limit_down: 80` | 前端默认跌停50只触发强制空仓，后端默认80只。用户首次使用时参数不一致 | form.forceEmpty.limit_down_count应从GLOBAL_RISK.force_empty_limit_down读取 |
| P1-2 | UltraShortBacktestViewV2.vue | submitBacktest() | forceEmpty对象fallback值 `index_drop_pct: 0.02` vs 实际默认0.03 | 提交回测时，若forceEmpty.index_drop_pct为空，fallback到0.02而非0.03，与全局默认值不一致 | 改为 `form.forceEmpty.index_drop_pct ?? GLOBAL_RISK.force_empty_index_drop_pct` |
| P1-3 | BacktestResultPanel.vue | factorContributionChartOption | tooltip显示 `{b}: {c}%` 但数据已×100，实际显示如"半路追涨: 50%"正确 | 无错误，但factor_contribution是交易笔数占比而非盈亏贡献，label可能误导用户 | 改tooltip为 `{b}: {c}%(笔数占比)` 澄清含义 |
| P1-4 | BacktestHistoryPanel.vue | formatReturn() | 收益率格式 `+340.23%` 加了+号，但BacktestResultPanel的fmtPct()不加+号 | 两个面板收益率格式不一致：历史面板有+号前缀，结果面板没有 | 统一收益率格式，建议都加+号 |
| P1-5 | StrategyConfigPanel.vue | 涨停开板 | `min_seal_after_open: 3000`的单位标注为"万元" | 后端strategy_defaults.py定义为3000万元，但StrategyConfigPanel里label写"万元"且min=1000 max=100000，数值3000对万元单位合理但范围暗示可能是手(1000手=10万) | 确认单位是否为万元，若为万元则范围max应改小(如10000) |
| P1-6 | BacktestResultPanel.vue | netValueChartOption | drawdown_series数据用`d.drawdown * 100`转百分比，但若后端返回的drawdown已是百分比格式则会出现×100错误 | 需确认后端drawdown_series.drawdown是小数还是百分比格式。注释说"小数(0.003=0.3%)"但实际需要验证 | 增加数据格式防御：若drawdown>1则认为已是百分比不再×100 |
| P1-7 | UltraShortBacktestViewV2.vue | form初始化 | form.globalFilter有`enable_ma60_filter`和`enable_sector_concentration`，但config.ini解析和后端defaults未包含这两个字段 | 这两个字段只在前端硬编码默认true，config.ini加载和后端defaults API不返回它们 | defaults.py增加这两个字段，或前端init从GLOBAL_RISK读取 |
| P1-8 | StrategyConfigPanel.vue | 首板打板opening_pct_min/max | 输入范围是`-10~10`和`0~15`，但数据模型存储的是百分比值(如-1.0表示-1%)，而其他策略的百分比参数存储的是小数(0.03=3%) | 首板打板的opening_pct是直接百分比数字(如5.0=5%)，其他策略的rise_pct是小数(0.05=5%)，两种格式不统一，用户容易混淆 | 在UI上明确标注"百分比形式(如5=5%)"或统一格式 |
| P1-9 | BacktestResultPanel.vue | strategyCompareChartOption | 雷达图3个维度(收益率/胜率/盈亏比)量级差异大(收益率可能500%/胜率80%/盈亏比3)，雷达图形状严重变形 | 雷达图无法直观反映策略优劣，收益率维度几乎撑满整个图 | 改用归一化雷达图(各维度除以最大值)或改用柱状图对比 |
| P1-10 | BacktestResultPanel.vue | dailyProfitChartOption | `daily_profit` ×100转百分比，注释说"已归一化(÷initial_cash)"。但若后端返回的daily_profit已经是百分比格式，则会出现双重×100 | 日收益率可能显示为放大100倍的错误值 | 增加数据格式防御：若daily_profit绝对值普遍>1则认为已是百分比 |

## P2 - UI优化建议

### 数据展示优化

1. **KPI strip响应式**: 当前`grid-template-columns: repeat(auto-fill, minmax(90px, 1fr))`在窄屏(手机)下8个KPI过于拥挤，建议在768px以下改为4列
2. **回撤颜色反转**: A股习惯红色=涨、绿色=跌，当前用`var(--stock-down)`(绿)表示盈利、`var(--stock-up)`(红)表示亏损，但这与ResultPanel中的实际CSS变量含义相反——应确认stock-down/stock-up的CSS变量定义是否正确
3. **年化收益警告**: 当前年化收益KPI在不足1年时只显示`*`号，建议直接在数值后追加`⚠️`图标更显眼
4. **月度收益表**: monthlyMergedData表格列宽可优化，"月份"列不需要100px宽

### 交互体验优化

5. **回测提交按钮位置**: 当前按钮在StrategyConfigPanel卡片头部，需滚动很长才能找到。建议在页面底部增加固定悬浮的"开始回测"按钮
6. **参数重置**: 没有一键恢复默认参数的功能，用户改错参数后只能刷新页面
7. **配置持久化**: 用户每次刷新页面配置丢失(除非后端API返回)，建议localStorage保存最近一次配置
8. **回测结果对比**: 历史面板的对比功能只选3条，建议增加到5条

### 图表优化

9. **净值曲线tooltip**: 当前tooltip显示"策略净值：1.2345"不带百分号，建议同时显示相对初始净值的涨跌幅
10. **仓位图Y轴**: 固定max=100，但当max_total_position=75%时，25%的空间是永远不用的空白，建议Y轴max跟随实际仓位上限
11. **月度收益柱状图**: 柱子颜色用var(--stock-down)/var(--stock-up)但var可能被暗色模式覆盖，建议直接用固定色值或确保CSS变量正确
12. **雷达图替代**: 组合级雷达图意义不大(5个维度量级差异大)，建议替换为水平条形图更直观

### 暗色模式

13. **ECharts图表暗色**: 多处图表使用CSS变量(如`var(--stock-down)`)作为颜色，但ECharts不一定能正确解析CSS变量，取决于渲染时机。需在暗色模式下实际测试图表颜色是否正确
14. **日志面板暗色**: AnsiLogPanel已有完整的暗色样式，但`--bg-code`/`--text-code`等变量需确保在浅色模式下也有合理值
15. **表格条纹暗色**: `el-table`的stripe行在暗色模式下可能过于突兀，建议调整`--el-fill-color-lighter`的暗色模式值

## 新功能建议

1. **策略参数快照**: 回测提交时保存参数快照到后端，历史记录查看时可以完整还原当时的参数配置，而非只保存策略名称列表
2. **回测结果对比图**: 选择2-3条历史回测，在同一张净值曲线图上叠加展示(双Y轴或归一化)
3. **交易热力图**: 以日历热力图展示每日盈亏(绿=赚/红=亏)，快速识别亏损集中期
4. **参数敏感度雷达**: 参数扫描结果不仅展示折线图，还展示各参数的敏感度评分(斜率)，帮助用户判断哪些参数最关键
5. **一键A/B对比**: 修改一个参数后自动与上次回测结果对比，高亮差异指标(如"收益+5.2%, 回撤+0.3%")
6. **移动端适配**: 当前在手机上基本不可用(回测配置面板过宽、表格无法滚动)，建议增加移动端专用布局
7. **交易记录标注**: 交易记录表格增加"查看K线"按钮，点击后弹窗展示该股买入卖出时的日K图
8. **实时净值追踪**: 回测运行时实时绘制已计算部分的净值曲线(而非等全部完成才展示)

---

## 参数不一致详细对照

以下为前端`strategyDefaults.ts`与后端`strategy_defaults.py`的逐项对照，标注差异：

### GLOBAL_RISK

| 参数 | 前端(strategyDefaults.ts) | 后端(strategy_defaults.py) | 一致? |
|------|---------------------------|---------------------------|-------|
| stop_loss_pct | 0.03 | 0.03 | ✅ |
| take_profit_pct | 0.07 | 0.07 | ✅ |
| max_hold_days | 3 | 3 | ✅ |
| slippage_pct | 0.002 | 0.002 | ✅ |
| commission_rate | 0.0003 | 0.0003 | ✅ |
| stamp_duty_rate | 0.001 | 0.001 | ✅ |
| max_position_per_stock | 0.35 | 0.35 | ✅ |
| max_total_position | 0.7 | **0.75** | ❌ P0-5 |
| liquidity_threshold | 500 | 500 | ✅ |
| volume_threshold | 1.5 | 1.5 | ✅ |
| force_empty_limit_down | 80 | 80 | ✅ |
| force_empty_limit_up | 10 | 10 | ✅ |
| force_empty_index_drop_pct | 0.03 | 0.03 | ✅ |
| intraday_lock_min_high_rise | 0.05 | 0.05 | ✅ |
| intraday_lock_pullback_pct | 0.02 | 0.02 | ✅ |
| intraday_lock_min_profit | 0.02 | 0.02 | ✅ |
| hold_protection_threshold | 0.05 | 0.05 | ✅ |
| live_trading_mode | false | false | ✅ |
| force_empty_cooldown_days | ❌缺失 | 2 | ❌ |
| force_empty_cooldown_position_cap | ❌缺失 | 0.6 | ❌ |
| dragon_head_early_exit_days | ❌缺失 | 5 | ❌ |
| dragon_head_early_exit_min_profit | ❌缺失 | 0.03 | ❌ |
| risk_free_rate | ❌缺失 | 0.03 | ❌ |

### halfway_chase (半路追涨)

| 参数 | 前端 | 后端 | 一致? |
|------|------|------|-------|
| min_rise_pct | 0.03 | 0.03 | ✅ |
| max_rise_pct | 0.07 | 0.07 | ✅ |
| min_volume_ratio | 2.0 | 2.0 | ✅ |
| max_volume_ratio | 3.0 | 3.0 | ✅ |
| min_close_rise_pct | 0.05 | 0.05 | ✅ |
| max_open_rise_pct | 0.03 | 0.03 | ✅ |
| allow_after_10am | false | false | ✅ |
| next_day_open_sell_pct | 0.02 | 0.02 | ✅ |
| pullback_mid_fallback_pct | ❌缺失 | 0.01 | ❌ |
| pullback_high_threshold | ❌缺失 | 0.05 | ❌ |
| stop_loss_pct (riskParams) | **0.04** | **0.03** | ❌ P0-3 |
| take_profit_pct (riskParams) | 0.12 | 0.12 | ✅ |
| max_hold_days (riskParams) | 3 | 3 | ✅ |
| slippage_pct (riskParams) | 0.002 | 0.002 | ✅ |
| trailing_stop_pct (riskParams) | ❌缺失 | 0.02 | ❌ P0-4 |

### first_limit_up (首板打板)

| 参数 | 前端 | 后端 | 一致? |
|------|------|------|-------|
| opening_pct_min | -1.0 | -1.0 | ✅ |
| opening_pct_max | 5.0 | 5.0 | ✅ |
| min_volume_ratio | 1.5 | 1.5 | ✅ |
| min_turnover_rate | 8 | 8 | ✅ |
| max_turnover_rate | 15 | 15 | ✅ |
| min_circulation_market_cap | 50 | 50 | ✅ |
| max_circulation_market_cap | 500 | 500 | ✅ |
| hit_probability_yizi | 0.0 | 0.0 | ✅ |
| hit_probability_fast | 0.2 | 0.20 | ✅ |
| hit_probability_normal | **0.45** | **0.40** | ❌ P0-1 |
| hit_probability_slow | **0.6** | **0.50** | ❌ P0-1 |
| next_day_open_sell_pct | 0.02 | 0.02 | ✅ |
| stop_loss_pct (riskParams) | 0.03 | 0.03 | ✅ |
| take_profit_pct (riskParams) | **0.08** | **0.10** | ❌ P0-2 |
| max_hold_days (riskParams) | 2 | 2 | ✅ |
| slippage_pct (riskParams) | 0.005 | 0.005 | ✅ |
| trailing_stop_pct (riskParams) | ❌缺失 | 0.02 | ❌ P0-4 |

### limit_up_open (涨停开板)

| 参数 | 前端 | 后端 | 一致? |
|------|------|------|-------|
| min_consecutive_limit | 2 | 2 | ✅ |
| max_consecutive_limit | 4 | 4 | ✅ |
| max_open_duration | 5 | 5 | ✅ |
| min_seal_after_open | 3000 | 3000 | ✅ |
| min_turnover_rate | 15.0 | 15.0 | ✅ |
| opening_pct_min | -3.0 | -3.0 | ✅ |
| opening_pct_max | 3.0 | 3.0 | ✅ |
| min_volume_ratio | 2.0 | 2.0 | ✅ |
| stop_loss_pct (riskParams) | 0.05 | 0.05 | ✅ |
| take_profit_pct (riskParams) | 0.06 | 0.06 | ✅ |
| max_hold_days (riskParams) | 2 | 2 | ✅ |
| slippage_pct (riskParams) | 0.003 | 0.003 | ✅ |

### dragon_head (龙头低吸)

| 参数 | 前端 | 后端 | 一致? |
|------|------|------|-------|
| min_consecutive_limit | 1 | 1 | ✅ |
| min_circulation_market_cap | 30 | 30 | ✅ |
| min_correction_pct | 0.05 | 0.05 | ✅ |
| max_correction_pct | 0.22 | 0.22 | ✅ |
| correction_days_min | 1 | 1 | ✅ |
| correction_days_max | 7 | 7 | ✅ |
| support_level | ma5 | ma5 | ✅ |
| min_volume_ratio | 0.5 | 0.5 | ✅ |
| max_volume_ratio | 2.0 | 2.0 | ✅ |
| next_day_open_sell_pct | 0.02 | 0.02 | ✅ |
| pullback_mid_fallback_pct | ❌缺失 | 0.015 | ❌ |
| pullback_profit_lock_threshold | ❌缺失 | 0.06 | ❌ |
| pullback_high_threshold | ❌缺失 | 0.05 | ❌ |
| stop_loss_pct (riskParams) | 0.03 | 0.03 | ✅ |
| take_profit_pct (riskParams) | **0.3** | 0.30 | ✅ |
| max_hold_days (riskParams) | 7 | 7 | ✅ |
| slippage_pct (riskParams) | 0.002 | 0.002 | ✅ |
| trailing_stop_pct (riskParams) | ❌缺失 | 0.03 | ❌ P0-4 |

### limit_down_qiao (跌停翘板)

| 参数 | 前端 | 后端 | 一致? |
|------|------|------|-------|
| min_consecutive_limit | 2 | 2 | ✅ |
| min_turnover_rate | 10 | 10 | ✅ |
| min_qiao_amount | 1000 | 1000 | ✅ |
| min_rise_after_qiao | 0.03 | 0.03 | ✅ |
| min_circulation_market_cap | 20 | 20 | ✅ |
| require_high_sentiment | false | false | ✅ |
| next_day_open_sell_pct | 0.02 | 0.02 | ✅ |
| pullback_mid_fallback_pct | 0.015 | 0.015 | ✅ |
| pullback_high_threshold | ❌缺失 | 0.05 | ❌ |
| stop_loss_pct (riskParams) | 0.05 | 0.05 | ✅ |
| take_profit_pct (riskParams) | 0.2 | 0.20 | ✅ |
| max_hold_days (riskParams) | 3 | 3 | ✅ |
| slippage_pct (riskParams) | 0.003 | 0.003 | ✅ |
| trailing_stop_pct (riskParams) | ❌缺失 | 0.04 | ❌ P0-4 |

---

## 统计

- **P0 (必须修复)**: 5项 — 均为前后端参数不一致，其中3项直接影响回测结果(止损/止盈/成交概率参数偏差)
- **P1 (建议修复)**: 10项 — 包括数据格式防御、UI一致性、交互改进
- **P2 (优化建议)**: 15项 — 响应式、暗色模式、图表优化
- **新功能建议**: 8项

**最紧急修复**: P0-1至P0-5均为`strategyDefaults.ts`与`strategy_defaults.py`参数不同步。建议运行同步脚本`cd AgentServer && python3 scripts/sync_strategy_defaults.py`一次性修复所有P0问题。
