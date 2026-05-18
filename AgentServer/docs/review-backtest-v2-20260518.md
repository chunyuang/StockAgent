# 回测模块全面审查报告 V2

**审查时间**: 2026-05-18 23:30  
**审查范围**: 后端数据格式、API链路、前端解析渲染、UI显示  
**分支**: feature/live-trading  
**验证回测**: us_51d2a46761e3 (4策略组合 20260105-20260320 ¥1M)  
**结果**: 收益38.91% 胜率60.14% 回撤7.52% 夏普4.42 交易143笔

---

## 📋 审查发现汇总

| 级别 | 数量 | 修复状态 |
|------|------|----------|
| P0   | 1    | ✅ 已修复验证 |
| P1   | 5    | ✅ 已修复验证 |
| P2   | 5    | ✅ 已修复验证 |
| 信息性 | 2   | ✅ 已文档化 |

---

## 🔴 P0级修复(1项)

### P0-1: `daily_profit`顶层字段与`net_value_series[].daily_profit`单位不一致
- **问题**: 后端`_build_run_result`中`result["daily_profit"]`存的是绝对值(元),如13989.20, 但`net_value_series[].daily_profit`存的是归一化小数(÷initial_cash),如0.01399。前端如果从顶层读取会得到完全不同的数值。
- **影响**: 虽然当前前端只从`net_value_series`读取,但如果有新代码或第三方使用顶层`daily_profit`就会出错。
- **修复**: `portfolio_backtest.py`第2514行,`result["daily_profit"]`改为归一化小数列表
- **验证**: `daily_profit[1]=0.015741` vs `nvs.daily_profit=0.015741` **匹配=True** ✅

---

## 🟡 P1级修复(5项)

### P1-1: History API参数读取路径错误
- **问题**: `start_date`/`end_date`/`strategies`/`initial_cash`在`params`顶层,但代码从`params.params`内层读取,永远返回null
- **影响**: 前端历史列表中"日期范围"和"策略"列永远显示"?"和"-"
- **修复**: `ultra_short.py`第361-364行,改为`params.get("start_date") or inner_params.get("start_date")`
- **验证**: history API返回`start_date=20260105, strategies=['halfway_chase',...]` ✅

### P1-2: History API `trades_count`永远为0
- **问题**: 从`result.trades`读取,但实际交易记录存在`result.merged_trades`中,`result.trades`不存在
- **修复**: 改为`result.get("total_trades") or len(result.get("merged_trades", []))`
- **验证**: `trades_count=143` ✅

### P1-3: 策略对比表"总盈亏"列引用不存在的`total_pnl_pct`字段
- **问题**: 后端`strategy_results`中没有`total_pnl_pct`字段,该列永远显示空值
- **修复**: 替换为"最大回撤"列,显示`strategy_results.max_drawdown`
- **验证**: 龙头低吸回撤15.15%, 半路追涨回撤20.37% ✅

### P1-4: 策略柱状图Y轴标签误导
- **问题**: Y轴标签"收益率(%)"但实际数据是`total_return`(profit_pct之和,如125%),不是策略真实收益率
- **修复**: Y轴标签改为"累计盈利(%)",与策略对比表一致
- **验证**: 龙头低吸125%, 跌停翘板70%, 半路追涨34.5% ✅

### P1-5: 盈亏额计算不准确
- **问题**: 用`sell_price * shares * profit_pct / 100`计算,但profit_pct已扣佣金,且sell_price可能为空
- **修复**: 改为`buy_price * shares * profit_pct / 100`,基于买入成本估算
- **验证**: 交易记录中盈亏额正常显示 ✅

---

## 🟢 P2级修复(5项)

### P2-1: 卖出原因英文→中文翻译
- **问题**: 交易记录"卖出原因"列显示原始英文(rebalance/stop_loss等)
- **修复**: 新增`translateSellReason()`函数,支持精确匹配+包含匹配
- **验证**: "止损"/"止盈"/"调仓"/"强制空仓"/"到期"等中文显示 ✅

### P2-2: 日收益/净值曲线增加dataZoom
- **问题**: 时间跨度较长时,无法查看特定时间段细节
- **修复**: 两个图表都增加`dataZoom: [{ type: 'inside' }, { type: 'slider' }]`
- **验证**: 图表底部出现滑块 ✅

### P2-3: 日收益图Y轴标签不明确
- **问题**: Y轴无单位标签,用户不清楚数值含义
- **修复**: 添加`name: '日收益率(%)'`,tooltip改为"日收益率：X%"
- **验证**: Y轴显示"日收益率(%)" ✅

### P2-4: 历史列表缺少"交易笔数"列
- **修复**: 新增"交易"列,显示`trades_count`
- **验证**: 显示143 ✅

### P2-5: History API缺少`profit_loss_ratio`字段
- **修复**: projection和返回item中添加`profit_loss_ratio`
- **验证**: `profit_loss_ratio=2.09` ✅

---

## 📝 信息性(2项)

### INFO-1: `strategy_results.total_return`含义文档化
- **说明**: `total_return`是profit_pct之和(累加收益率),不是策略组合的净收益率。已在注释和前端标签中明确。
- **例如**: 龙头低吸49笔,累加125%,但实际贡献组合收益远低于125%(因为仓位限制)

### INFO-2: `strategy_results.max_drawdown`计算基于累加曲线
- **说明**: 基于profit_pct累加曲线而非真实净值曲线,回撤值偏大(20-22%)
- **建议**: 未来可基于策略级净值曲线重新计算,但当前不影响组合级指标

---

## ✅ 数据格式规范(验证通过)

| 字段 | 格式 | 示例 | 前端处理 |
|------|------|------|----------|
| total_return | 百分比 | 38.91 | 直接+%(fmtPct) |
| win_rate | 百分比 | 60.14 | 直接+%(fmtPct) |
| max_drawdown | 百分比 | 7.52 | 直接+%(fmtPct) |
| sharpe_ratio | 比率 | 4.42 | toFixed(2) |
| profit_loss_ratio | 比率 | 2.09 | toFixed(2) |
| net_value_series[].net_value | 归一化(1.0起始) | 1.3891 | 直接使用 |
| net_value_series[].daily_profit | 归一化小数 | 0.015741 | ×100转% |
| daily_profit(顶层) | 归一化小数 | 0.015741 | ×100转% |
| drawdown_series[].drawdown | 小数 | 0.0752 | ×100转% |
| position_series[].value | 小数 | 0.188 | ×100转% |
| monthly_profit值 | 小数 | 0.1999 | ×100转% |
| factor_contribution值 | 小数 | 0.5 | ×100转% |
| merged_trades[].profit_pct | 百分比 | 2.07 | 直接+%(fmtPct) |
| sell_reason_stats | 整数计数 | {stop_loss: 19, ...} | 直接显示 |

---

## 📊 验证回测结果(4策略组合)

| 策略 | 累计盈利% | 胜率% | 笔数 | 单笔均利% | 最大回撤% |
|------|-----------|-------|------|-----------|-----------|
| 半路追涨 | 34.5 | 51.2 | 41 | 0.84 | 20.37 |
| 龙头低吸 | 125.0 | 69.4 | 49 | 2.55 | 15.15 |
| 首板打板 | 5.0 | 46.2 | 26 | 0.19 | 22.75 |
| 跌停翘板 | 70.0 | 70.4 | 27 | 2.59 | 10.40 |
| **组合** | **38.91** | **60.14** | **143** | - | **7.52** |

**卖出原因分布**: 止盈46笔(32%) > 调仓65笔(45%) > 止损19笔(13%) > 强制空仓13笔(9%) > 到期0笔 > 其他0笔

---

## 🔧 Git提交记录

| Commit | 描述 |
|--------|------|
| a5855fb | fix(backtest): 数据格式统一+API修复+UI优化 |
| 30d0e4a | fix(backtest): P1策略对比修复+前端TS类型补全 |

---

## 🚫 未影响实盘模块

所有修改仅在以下文件中,未触及scanner/broker等实盘模块:
- `AgentServer/nodes/backtest_engine/factor_selection/portfolio_backtest.py` — 仅daily_profit归一化+注释
- `AgentServer/nodes/web/api/backtest/ultra_short.py` — history API参数读取修复
- `frontend/src/components/ultrashort/BacktestResultPanel.vue` — UI显示优化
- `frontend/src/components/backtest/BacktestHistoryPanel.vue` — 新增交易列
- `frontend/src/api/modules/backtest.ts` — TS类型补全
