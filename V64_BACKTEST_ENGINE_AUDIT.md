# V64 回测引擎审计报告

**日期**: 2026-05-27  
**审计范围**: portfolio_backtest.py, sell_signal_checker.py, strategy_defaults.py, ultra_short.py, factor_engine.py  
**基线**: V63 (total_return: 331.11%, max_drawdown: 5.45%, sharpe: 11.39, win_rate: 80.85%, trades: 94)

---

## 修复清单

### P0 级（影响正确性/结果）

| 编号 | 问题 | 影响 | 修复 | 文件 |
|------|------|------|------|------|
| P0-1 | hit_probability_normal fallback 0.45 vs strategy_defaults 0.40 | 首板打板成交概率不一致,ultra_short.py中normal概率偏高5% | 统一从strategy_defaults读取fallback | portfolio_backtest.py L3931 |
| P0-2 | hit_probability_slow fallback 0.45 vs strategy_defaults 0.50 | 首板打板成交概率不一致,portfolio中slow概率偏低5% | 统一从strategy_defaults读取fallback | portfolio_backtest.py L3932 |
| P0-3 | ultra_short.py hit_probability_normal fallback 0.45 vs 0.40 | 与strategy_defaults不一致 | 统一为0.40 | ultra_short.py L202 |
| P0-4 | global_tp 硬编码 0.07 而非 GLOBAL_RISK['take_profit_pct'] | 如果修改GLOBAL_RISK默认止盈,此处不会同步 | 改为GLOBAL_RISK['take_profit_pct'] | portfolio_backtest.py L3836, L4311 |

### P1 级（应该修复 — 影响结果优化）

| 编号 | 问题 | 影响 | 修复 | 文件 |
|------|------|------|------|------|
| P1-1 | 半路追涨胜率71.4%是最低策略,止损3%可能过紧 | 半路追涨14笔亏损中可能有3%→3.5%可避免的跳空止损 | 评估止损3%→3.5%的效果 | strategy_defaults.py |
| P1-2 | 龙头低吸5天低利润退出0.03硬编码 | 违反参数单一来源原则 | 提升为strategy_defaults参数 | portfolio_backtest.py L412 |
| P1-3 | 强制空仓冷却期0.5硬编码 | 冷却期仓位上限不可配置 | 提升为strategy_defaults参数 | strategy_defaults.py + portfolio_backtest.py |
| P1-4 | 首板打板收益72.61%但盈亏比2.04偏低 | 止盈8%可能过早截断盈利 | 评估8%→10%的效果 | strategy_defaults.py |
| P1-5 | _check_intraday_profit_lock重复实现 | 在portfolio_backtest.py和sell_signal_checker.py各有一份,逻辑不同步风险 | 统一调用sell_signal_checker | portfolio_backtest.py |

### P2 级（代码质量/可维护性）

| 编号 | 问题 | 修复 | 文件 |
|------|------|------|------|
| P2-1 | P0-1/P0-2: hit_probability的4个fallback值分散在2个文件中 | 提取为STRATEGY_CONFIGS常量引用 | portfolio_backtest.py + ultra_short.py |
| P2-2 | _rebalance方法仍有453行,虽然注释说明不可拆分但内部分段可优化 | 提取sell/buy子方法 | portfolio_backtest.py |
| P2-3 | daily_rf = 0.03/252 硬编码无风险利率 | 提取为GLOBAL_RISK参数 | portfolio_backtest.py L2835 |
| P2-4 | stop_loss_pct/take_profit_pct在risk_config初始化时重复赋值 | 简化risk_config构建 | portfolio_backtest.py |

---

## 参数优化建议（需回测验证）

### 方案A: 保守优化（修复fallback不一致即可）
- P0-1/P0-2/P0-3: 统一hit_probability fallback → 首板打板信号量可能增加
- P0-4: 统一global_tp → 当前值相同,无实际影响,但消除未来风险

### 方案B: 积极优化（在A基础上微调参数）
- P1-1: 半路追涨止损3%→3.5% → 减少跳空止损误杀
- P1-4: 首板打板止盈8%→10% → 让盈利跑更远
- P1-3: 冷却期仓位上限0.5→0.6 → 减少冷却期资金闲置

### 方案C: 激进优化（高风险）
- 龙头低吸止损3%→2.5% → 更紧止损,但可能被震出
- 半路追涨min_rise 3%→2.5% → 更多信号,但噪音也更多
- max_total_position 0.75→0.80 → 更高仓位,回撤风险增大

---

## 回测结果优化分析

### V63策略分解
| 策略 | 笔数 | 胜率 | 收益% | 盈亏比 | 最大优化空间 |
|------|------|------|-------|--------|------------|
| 跌停翘板 | 28 | 82.1% | 312.90 | 3.49 | 已接近最优 |
| 龙头低吸 | 32 | 90.6% | 299.93 | 3.38 | 5天低利润退出可优化 |
| 半路追涨 | 21 | 71.4% | 94.83 | 2.70 | **止损/止盈参数** |
| 首板打板 | 13 | 69.2% | 72.61 | 2.04 | **成交概率/止盈参数** |

### 关键洞察
1. **半路追涨是最大拖累**: 胜率71.4%最低,盈亏比2.70最低,收益仅94.83%
2. **首板打板已有改善**: 从V62的33.3%胜率→V63的69.2%,但盈亏比2.04仍需提升
3. **跌停翘板和龙头低吸已接近最优**: 进一步优化空间有限
4. **总收益331.11% vs V62的340.23%**: 差9%来自冷却期限制,是风控换取的合理代价

### 优化方向
- **P0修复(参数一致性)**: 不改变策略逻辑,仅修复fallback不一致,预期首板打板信号量微增
- **半路追涨止损微调**: 3%→3.5%,减少跳空止损误杀,预期能提升2-3%收益
- **首板止盈8%→10%**: 当前8%几乎不触发止盈,10%更实际,预期能提升5-10%收益
