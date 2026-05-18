# 回测模块全面审查报告 V3

**审查时间**: 2026-05-19 01:30  
**审查范围**: 前后端数据一致性、UI专业性、代码质量、组件重复  
**分支**: feature/live-trading  
**验证回测**: 3次实际回测验证  

---

## 📋 审查发现汇总

| 级别 | 数量 | 修复状态 |
|------|------|----------|
| P0   | 2    | ✅ 已修复验证 |
| P1   | 4    | ✅ 已修复验证 |
| P2   | 4    | ✅ 已修复验证 |

---

## 🔴 P0级修复(2项)

### P0-1: BacktestResultPanel `backtestResult`未定义引用
- **问题**: KPI strip中年化收益的`*`提示用了`backtestResult?.net_value_series?.length`，但组件props是`result`不是`backtestResult`
- **影响**: 年化收益旁永远不显示`*`提示，短期回测用户无法意识到年化虚高
- **修复**: `backtestResult` → `result`
- **验证**: ✅

### P0-2: 策略级`profit_loss_ratio`变量未定义
- **问题**: `portfolio_backtest.py`第2566行用`wins_pnl/losses_pnl`，但这两个变量在strategy循环内未定义
- **影响**: strategy_results中profit_loss_ratio永远为None(后端报NameError但被except吞掉)
- **修复**: 新增`strategy_wins_pnl`/`strategy_losses_pnl`从completed trades计算
- **验证**: 半路追涨plr=0.57, 跌停翘板plr=1.73 ✅

---

## 🟡 P1级修复(4项)

### P1-1: BacktestSummaryTable与BacktestResultPanel大量功能重复
- **问题**: 两个组件都有KPI卡片、TOP5、交易记录表、策略对比、风险指标，用户看到两份几乎相同的界面很困惑
- **修复**: BacktestSummaryTable精简为紧凑概要卡片：
  - 核心KPI(Descriptions组件，4列)
  - 策略对比速览表(5列)
  - 运行元信息(耗时/交易日/资金)
  - 短期回测警告
  - 去掉：TOP5、交易记录、风险指标明细、CSV导出（全部在ResultPanel中更完整）
- **效果**: 代码527行→160行，页面信息层次清晰

### P1-2: 策略对比表"收益率"标签误导
- **问题**: 列名"收益率"但实际数据是`total_return`(profit_pct之和，如34.89%)，不是策略真实收益率
- **修复**: 列名"收益率"→"累计盈利"，与V2审查报告的P1-4保持一致
- **验证**: ✅

### P1-3: 卡玛比率短期回测虚高无提示
- **问题**: 2.5个月回测的calmar_ratio=53.63(年化402%/回撤7.5%)，远超实际长期水平，用户容易误判
- **修复**: 风险指标desc中添加"（短期回测该值虚高）"提示；SummaryTable底部增加⚠️短期回测disclaimer
- **验证**: ✅

### P1-4: 策略对比表增加盈亏比列
- **问题**: 后端strategy_results没有profit_loss_ratio字段，前端也没有对应列
- **修复**: 
  1. 后端portfolio_backtest.py添加`profit_loss_ratio`字段计算
  2. 前端策略对比表新增"盈亏比"列
- **验证**: ✅

---

## 🟢 P2级修复(4项)

### P2-1: 策略名去emoji方法脆弱
- **问题**: `v.replace(/^[\S]+\s*/, '')`用`\S`匹配emoji，对多字节emoji(🏃‍♂️)匹配不完整
- **修复**: 改为`v.replace(/[\u{1F000}-\u{1FFFF}\u{2600}-\u{27BF}\u{FE00}-\u{FE0F}\u{1F900}-\u{1F9FF}\u{200D}\u{20E3}]+\s*/u, '')`
- **验证**: 半路追涨/首板打板/龙头低吸/跌停翘板均正确去除emoji ✅

### P2-2: 未平仓交易reason=''显示为'--'
- **问题**: 3笔未平仓交易的sell_reason为空字符串，translateSellReason返回'--'，用户不知道这些是持仓中的
- **修复**: 添加`if (!reason) return '持仓中'`
- **验证**: ✅

### P2-3: 策略对比表冗余"状态"列
- **问题**: "状态"列显示"✅ 正常"或"⚠️ warning"，但warning信息只有0交易策略有，且0交易策略本来就不应该出现在对比表
- **修复**: 去掉"状态"列，替换为更有价值的"盈亏比"列
- **验证**: ✅

### P2-4: gap_down_stop卖出原因缺少翻译
- **问题**: `跳空止损(开38.90<止损39.43)`这类详细reason包含"跳空止损"，但由于匹配顺序问题可能被归为"其他"
- **修复**: 新增`'gap_down_stop': '跳空止损'`映射，确保精确匹配和包含匹配都覆盖
- **验证**: ✅

---

## ✅ 回测验证结果

### 验证1: 单策略(半路追涨) 20260105-20260320
- 收益1.81% 胜率38.9% 回撤5.98% 夏普0.42 交易126笔
- daily_profit一致性: ✅ 顶层与nvs完全匹配
- 卖出原因: 调仓75% > 空仓10% > 止盈8% > 止损7% ✅

### 验证2: 4策略组合 20260105-20260320 ¥1M
- 收益36.85% 胜率61.3% 回撤7.50% 夏普4.51 交易142笔
- 净值归一化: 首日1.0，末日1.3685，final_value匹配 ✅
- 基准数据: 49条 ✅
- 策略级指标: profit_loss_ratio正确返回 ✅

### 验证3: 2策略短周期(3月) 验证profit_loss_ratio
- 半路追涨: plr=0.57, return=-18.05%, wr=23.1%
- 跌停翘板: plr=1.73, return=12.83%, wr=54.5%
- 数据合理，盈亏比计算正确 ✅

---

## 🚫 未影响实盘模块

所有修改仅涉及：
- `AgentServer/nodes/backtest_engine/factor_selection/portfolio_backtest.py` — strategy_results添加profit_loss_ratio
- `frontend/src/components/ultrashort/BacktestResultPanel.vue` — P0引用修复+UI优化
- `frontend/src/components/backtest/BacktestSummaryTable.vue` — 精简重构
- `frontend/src/components/backtest/BacktestHistoryPanel.vue` — emoji正则修复

未触及scanner/broker等实盘模块 ✅

---

## 🔧 Git提交记录

| Commit | 描述 |
|--------|------|
| 08444a8 | fix: 回测审查V3 - P0修复+UI专业化优化 |
| 9006ce7 | fix: 策略级profit_loss_ratio变量未定义bug修复 |
