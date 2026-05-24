# V38 深度审查报告

## 审查时间
2026-05-24 08:30~09:05

## 版本演进

| 版本 | 总收益 | 回撤 | 胜率 | 夏普 | 盈亏比 | 笔数 | 关键改动 |
|------|--------|------|------|------|--------|------|----------|
| V35基线 | 241.14% | 2.47% | 76.77% | 12.64 | 3.29 | 99 | 原始版本 |
| V36 | 143.57% | 3.63% | 69.31% | 10.45 | 2.59 | 101 | 竞价过滤收窄+持仓8%+止损统一 |
| V37 | 229.53% | 3.63% | 73.79% | 11.71 | 2.93 | 103 | 恢复V35竞价+持仓6%+首板概率 |
| **V38** | **234%** | **2.9%** | **74.8%** | **11.86** | **2.83** | **104** | **持仓保护恢复5%** |

## V38核心发现

### 1. 多策略调仓竞争（关键发现）
单跑半路追涨 hold_protection 5% vs 6% → 结果完全一致！
- 单策略时无跨策略调仓竞争，5%=6%
- 多策略时5-6%盈利+阳线的股票在6%下不被保护
- 半路追涨胜率68.2%(V35)→62.5%(V37)→65.2%(V38)

### 2. 半路追涨调仓卖出占比43%（23笔中10笔）
- 调仓卖出平均收益仅+0.93%，多数0-3%微利
- 持仓保护5%已是最优，4%会保护太多微利股锁死资金

### 3. 首板打板跳空止损是最大杀手
- 5笔跳空止损平均-7.2%（-5.75%~-10.96%）
- 正常止损3笔-4.15%，跳空远比正常止损严重
- 选股条件改善空间有限，但策略贡献仅9.31%

## 全文件审查清单

### 回测引擎 ✅
- [x] portfolio_backtest.py (4283行) — 持仓保护/调仓竞争/止损止盈
- [x] sell_signal_checker.py (853行) — 卖出信号优先级/滑点规则/买入价
  - 冲高回落→利润保护→高开即卖优先级正确
  - 首板打板利润锁定信号冗余但不影响（check_full_sell未被调用）
- [x] factor_engine.py (718行) — 因子计算/标准化/打分
- [x] strategy_defaults.py (192行) — 参数单一来源
- [x] universe.py (416行) — 股票池/交易日历/缓存TTL

### 实盘模块 ✅
- [x] generate_daily_signals.py (536行)
  - ✅ 竞价过滤与回测对齐(-5%~7%)
  - ✅ 参数从strategy_defaults读取
  - 🔧 V38修复: 买入价与STRATEGY_BUY_PRICE对齐
  - 🔧 V38修复: 止损止盈从策略级riskParams读取
- [x] paper_trading.py (540行)
  - 🔧 V38修复: 滑点从策略级参数读取(首板0.5% vs 其他0.2%)
- [x] position_manager.py (616行) — 止损/止盈/持仓天数从STRATEGY_CONFIGS读取
- [x] daily_scheduler.py (952行) — 参数从GLOBAL_RISK读取
- [x] AgentServer/core/managers/live/position_manager.py — 从strategy_defaults读取

### 前端 ✅
- [x] BacktestResultPanel.vue (1197行)
  - 🔧 V38: 持仓保护标签动态化(Math.round(holdProtPct*100)%)
  - 🔧 V38: 卖出原因颜色标签(绿=止盈/保护, 红=止损, 橙=强制, 灰=调仓)
- [x] BacktestHistoryPanel.vue (550行) — 历史对比
- [x] BacktestSummaryTable.vue (173行) — 概要卡片
- [x] AnsiLogPanel.vue (648行) — 日志面板
- [x] UltraShortBacktestViewV2.vue (1021行) — 主视图
- [x] StrategyConfigPanel.vue (1537行) — 策略配置
- [x] DataStatusPanel.vue (484行) — 数据状态
- [x] FactorReferencePanel.vue (304行) — 因子参考
- [x] strategyDefaults.ts — 自动同步✅
- [x] backtestConstants.ts — 共享常量✅

## 回测-实盘互助力

### 参数同步链 ✅
```
strategy_defaults.py → sync_strategy_defaults.py → strategyDefaults.ts
                    → portfolio_backtest.py (回测读取)
                    → generate_daily_signals.py (实盘读取)
                    → paper_trading.py (模拟读取)
                    → position_manager.py (实盘/模拟读取)
                    → daily_scheduler.py (调度读取)
```

### 关键对齐项
| 维度 | 回测 | 实盘 | 对齐状态 |
|------|------|------|----------|
| 竞价过滤 | >7%/<-5%排除 | >7%/<-5%排除 | ✅ |
| 买入价 | STRATEGY_BUY_PRICE | close*1.01→V38修复 | ✅ |
| 止损止盈 | 策略级riskParams | 策略级riskParams(V38) | ✅ |
| 滑点 | 策略级0.2%/0.5% | 策略级(V38修复) | ✅ |
| 持仓保护 | hold_protection=5% | hold_protection=5% | ✅ |

## Git提交记录
1. `e6de654` - V38: 持仓保护恢复5% + 多策略调仓竞争分析
2. `1b7325b` - V38-fix1: 前端持仓保护标签动态化
3. `0702a6c` - V38: 完整审查报告
4. `985edc2` - V38-fix2: 实盘模块3项优化(滑点/买入价/止损止盈)
5. `5972f78` - V38-fix3: 前端卖出原因颜色标签
