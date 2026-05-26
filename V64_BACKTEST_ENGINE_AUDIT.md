# V64 回测引擎审计报告

**日期**: 2026-05-27  
**审计范围**: portfolio_backtest.py, sell_signal_checker.py, strategy_defaults.py, ultra_short.py, factor_engine.py  
**基线**: V63 (total_return: 331.11%, max_drawdown: 5.45%, sharpe: 11.39, win_rate: 80.85%, trades: 94)

---

## 修复清单

### P0 级（影响正确性/结果）✅ 全部已修复

| 编号 | 问题 | 修复 | 提交 |
|------|------|------|------|
| P0-1 | hit_probability_normal fallback 0.45 vs strategy_defaults 0.40 (ultra_short.py) | 0.45→0.40 | 8ae34c8 |
| P0-2 | hit_probability_slow fallback 0.45 vs strategy_defaults 0.50 (portfolio_backtest.py) | 0.45→0.50 | 8ae34c8 |
| P0-3 | ultra_short.py hit_probability_normal fallback 0.45 | 0.45→0.40 | 8ae34c8 |
| P0-4 | global_tp 硬编码 0.07 → GLOBAL_RISK (portfolio_backtest.py L3836, L4311) | 改用GLOBAL_RISK读取 | 8ae34c8 |
| P0-5 | sell_signal_checker.py global_sl/global_tp 硬编码 0.03/0.07 | 改用GLOBAL_RISK读取 | 2eb425c |

### P1 级（参数提升 + 优化）✅ 全部已修复

| 编号 | 问题 | 修复 | 提交 |
|------|------|------|------|
| P1-1 | 龙头低吸5天低利润退出硬编码5和0.03 | 提升为GLOBAL_RISK参数 | 8ae34c8 |
| P1-2 | 强制空仓冷却期仓位上限0.5硬编码 | 提升为GLOBAL_RISK参数 | 8ae34c8 |
| P1-3 | 首板打板止盈8%→10% | 参数优化 | d9d134d |
| P1-4 | 冷却期仓位上限0.5→0.6 | 参数优化 | d9d134d |

### P2 级（代码质量）✅ 全部已修复

| 编号 | 问题 | 修复 | 提交 |
|------|------|------|------|
| P2-1 | daily_rf = 0.03/252 硬编码无风险利率 | 提升为GLOBAL_RISK.risk_free_rate | 8ae34c8 |
| P2-2 | MarketMonitorView ElTag type空字符串 | 空字符串→'danger' | 2eb425c |

---

## 回测结果对比

| 指标 | V63 | V64 | 变化 | 说明 |
|------|-----|-----|------|------|
| 总收益 | 331.11% | **335.82%** | **+4.71%** | 首板TP提升+冷却期cap放宽 |
| 最大回撤 | 5.45% | 5.46% | +0.01% | 几乎不变 |
| 夏普 | 11.39 | **11.46** | +0.07 | |
| 索提诺 | 14.08 | **16.23** | +2.15 | 显著提升 |
| 胜率 | 80.85% | **81.05%** | +0.20% | |
| 盈亏比 | 3.00 | 3.01 | +0.01 | |
| 交易笔数 | 94 | 95 | +1 | 首板+1笔 |

### 策略级对比

| 策略 | V63收益 | V64收益 | 变化 | 说明 |
|------|---------|---------|------|------|
| 跌停翘板 | 312.90% | 312.90% | 0 | 不受影响 |
| 龙头低吸 | 299.93% | 299.93% | 0 | 不受影响 |
| 半路追涨 | 94.83% | 94.83% | 0 | 止损保持3% |
| 首板打板 | 72.61% | **86.73%** | **+14.12%** | TP 8→10% + 冷却期cap |

### 首板打板交易明细变化
- 300253.SZ: V63 止盈(8.0%)=7.83% → V64 止盈(10.0%)=9.82% (+2%)
- 605018.SH: V63 止盈(8.0%)=7.83% → V64 利润锁定=3.58% (止盈未触发,被更早卖出信号替代)
- 300569.SZ: V63 止盈(8.0%)=7.83% → V64 高开即卖=4.79%
- 002276.SZ: V64新增,超时=19.40% (冷却期0.6让更多资金可以进场)

---

## 废弃参数测试

| 测试 | 结果 | 结论 |
|------|------|------|
| 半路追涨止损3%→3.5% | 收益94.83→94.08, 盈亏比2.70→2.58 | ❌ 得不偿失,保持3% |

---

## 实盘-回测互助力

### 已有的互助力机制
1. **参数单一来源**: strategy_defaults.py 是唯一参数来源,回测和实盘都从此读取
2. **卖出信号共享**: 实盘使用sell_signal_checker.py(回测引擎模块),逻辑100%对齐
3. **偏差监控**: live_backtest_bridge.py 自动对比实盘vs回测胜率/收益/滑点
4. **参数同步检查**: strategy_defaults.py修改后自动提醒重启实盘服务
5. **校准报告**: 生成可手动应用的参数调整建议

### V64新增互助力
- P0-5修复: sell_signal_checker的global_sl/global_tp fallback现在与portfolio_backtest.py完全一致
- 冷却期仓位上限可配置: 实盘可以与回测使用不同的冷却期cap(更保守)
- 龙头5天低利润退出可配置: 实盘可以根据实际表现调整退出阈值

---

## 前端UI审计

### V63已修复项 (全部已提交)
- P0-1: todayPnl fallback数学错误
- P0-2: StrategyEditView全局注册组件
- P0-4: 卖出确认弹窗缺成本价
- P0-5: 实盘模式切换无二次确认
- P1-1~P1-15: 11项体验优化
- P2-1~P2-14: UI细节优化

### V64新增修复
- MarketMonitorView ElTag type空字符串→'danger'

### 待优化项
- 月度收益热力图 (需ECharts heatmap)
- 大chunk拆分 (element-plus 921KB / echarts 585KB)
- TypeScript类型错误 (MarketMonitorView 7处, SettingsView 2处, StockDetailView 1处, StrategyEditView 2处)
- 深色模式部分硬编码颜色→CSS变量

---

## 结论

V64在V63基础上实现**全面参数正确性修复+收益优化**:

1. **正确性**: 5个P0级参数fallback不一致bug全部修复,消除未来参数漂移风险
2. **收益**: 总收益331.11%→335.82%(+4.71%),回撤仅增0.01%
3. **可配置性**: 3个硬编码参数提升为GLOBAL_RISK可配置
4. **互助力**: 回测-实盘参数一致性保障,偏差监控,参数同步提醒

**V64最终指标**: total_return=335.82%, max_drawdown=5.46%, sharpe=11.46, win_rate=81.05%, trades=95
