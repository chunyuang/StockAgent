# V59 回测引擎审计报告

**审计时间**: 2026-05-27  
**审计范围**: portfolio_backtest.py (4522行) + sell_signal_checker.py (871行) + strategy_filter.py (223行) + strategy_defaults.py + 实盘对齐  
**基线**: V57 (total_return=102.11%, max_drawdown=3.09%, sharpe=10.17) → V58 (total_return=148.15%, max_drawdown=5.06%, sharpe=9.76)  

---

## 一、Bug 清单

### P1 (重要)

#### P1-1: `_pending_force_sell` 是类级变量，跨实例共享且未重置

**文件**: portfolio_backtest.py:95  
**代码**: `_pending_force_sell: set = set()`  
**问题**: 这是类级注解（class-level annotation），不是实例属性。Python中 `self._pending_force_sell.add(code)` 会修改类级 set（因为实例字典中不存在该键时，Python 回退到类字典并原地修改）。  
**影响**: 
- 两次回测在同一进程中运行时，第二次回测会继承第一次遗留的 `_pending_force_sell`
- 导致本应在第二次回测中正常持有的股票被错误强制卖出
**修复**: 在 `__init__` 中添加 `self._pending_force_sell = set()`

#### P1-2: sell_signal_checker 利润锁定默认值不一致

**文件**: sell_signal_checker.py:285  
**代码**: `min_high_rise = params.get('intraday_lock_min_high_rise', GLOBAL_RISK.get('intraday_lock_min_high_rise', 0.05))`  
**问题**: 硬编码 fallback 是 0.05，但 strategy_defaults.py 中 `intraday_lock_min_high_rise = 0.04`。portfolio_backtest.py 的 `_check_intraday_profit_lock` fallback 是 0.04。  
**影响**: 当前因为 GLOBAL_RISK 有值(0.04)，两者实际运行时一致。但如果 GLOBAL_RISK 缺少该键，sell_signal_checker 会用 0.05 而 portfolio_backtest 用 0.04，导致利润锁定行为不一致。  
**修复**: 将 sell_signal_checker.py 的 fallback 从 0.05 改为 0.04

#### P1-3: position_manager.py 注释过时（0.08 vs 0.06）

**文件**: position_manager.py:444  
**代码**: `# 回测: STRATEGY_PULLBACK_PARAMS['龙头低吸']['pullback_profit_lock_threshold']=0.08`  
**问题**: V53 已将该值从 0.08→0.06，但实盘代码注释仍写 0.08。实际代码从 `_strategy_params.get('pullback_profit_lock_threshold', None)` 读取，运行时值为 0.06，结果正确但注释误导。  
**修复**: 更新注释为 0.06

#### P1-4: V58 策略级利润锁定代码是死代码

**文件**: portfolio_backtest.py:213-229  
**代码**: V58 新增的从 `STRATEGY_PULLBACK_PARAMS` + `_strategy_risk_params` 读取 `intraday_lock_min_high_rise/pullback_pct/min_profit` 的代码路径  
**问题**: `STRATEGY_PULLBACK_PARAMS` 不包含 `intraday_lock_*` 键（只有 `pullback_*` 键），`STRATEGY_CONFIGS.riskParams` 也不包含 `intraday_lock_*` 键。因此 `_merged_params` 中永远不会出现 `intraday_lock_*`，策略级 override 代码永远不会执行。  
**影响**: 功能正确性不受影响（始终 fallback 到 GLOBAL_RISK 值），但代码增加了不必要的复杂度和维护负担。  
**修复**: 要么在 STRATEGY_CONFIGS 中添加策略级利润锁定参数使其生效，要么删除死代码简化逻辑

#### P1-5: 利润锁定逻辑重复实现

**文件**: portfolio_backtest.py `_check_intraday_profit_lock` vs sell_signal_checker.py `check_intraday_profit_lock`  
**问题**: 利润锁定在两处独立实现：
1. portfolio_backtest.py L196-232: 在 `_check_and_execute_forced_sells` 中直接调用
2. sell_signal_checker.py L282-307: 在 `check_full_sell` (DEPRECATED) 和 `INTRADAY_PROFIT_LOCK_SIGNALS` 中使用  
两处代码逻辑相同但参数读取路径不同（portfolio_backtest 从 `_risk_config` + `GLOBAL_RISK` + 策略级合并；sell_signal_checker 从 `params` + `GLOBAL_RISK`）。  
**风险**: 如果未来在一处修改逻辑而忘记另一处，会导致行为不一致。  
**修复**: 统一到 sell_signal_checker.py，portfolio_backtest.py 通过 `_sell_checker` 调用

#### P1-6: 实盘 position_manager 利润锁定读取 riskParams 但 STRATEGY_CONFIGS 无该键

**文件**: position_manager.py:447-453  
**代码**: 
```python
_strategy_risk_params = _strategy_cfg.get('riskParams', {})
if 'intraday_lock_min_high_rise' in _strategy_risk_params:
    _lock_min_high = _strategy_risk_params['intraday_lock_min_high_rise']
```
**问题**: `STRATEGY_CONFIGS` 的 `riskParams` 中没有 `intraday_lock_*` 键，所以这段策略级 override 代码永远不会执行。如果未来需要策略级差异化，需要先在 `STRATEGY_CONFIGS` 中定义参数。  
**影响**: 当前无影响（fallback 到 GLOBAL_RISK 正确值），但代码意图与实际不符。  
**修复**: 如果不需要策略级差异，删除此段代码；如果需要，在 STRATEGY_CONFIGS 中添加参数

---

### P2 (优化建议)

#### P2-1: strategy_filter.py 已废弃但仍存在

**文件**: strategy_filter.py (223行)  
**问题**: 文件头已标注 "⚠️ 注意：本模块已过时，不再维护"，但文件仍存在于代码库中。其 `StrategyFilter` 类使用旧式 `or` 模式（而非 `is not None`）和 T 日因子（而非 `_prev`），与主引擎不一致。  
**风险**: 新开发者可能误用此模块。  
**修复**: 移除文件或移至 `_deprecated/` 目录

#### P2-2: sell_signal_checker.check_full_sell 已废弃但仍保留

**文件**: sell_signal_checker.py:510-567  
**问题**: `check_full_sell` 方法文档标注 "DEPRECATED (V33 review: never called in portfolio_backtest.py)"，但方法仍在类中。所有卖出检查通过 `check_early_sell` + 内联 SL/TP 在 `_rebalance/_check_and_execute_forced_sells` 中处理。  
**修复**: 删除 `check_full_sell` 方法

#### P2-3: `_get_sl_tp_for_code` TP 取 `strategies[0]` vs `get_sl_tp_for_strategies` TP 取 `min`

**文件**: portfolio_backtest.py `_get_sl_tp_for_code` vs sell_signal_checker.py `get_sl_tp_for_strategies`  
**问题**: 
- `_get_sl_tp_for_code`（实际使用）: TP 取第一个策略的止盈（`strategies[0]`）
- `get_sl_tp_for_strategies`（DEPRECATED）: TP 取最严格的止盈（`min`）  
**影响**: 当前 `get_sl_tp_for_strategies` 未被调用，无实际影响。但代码注释说明 V31 曾讨论此问题并选择 `strategies[0]`（买入策略），这与其他参数取 min（最严格）的逻辑不一致。  
**建议**: 统一为 `strategies[0]`（买入策略决定卖出条件更合理），并删除 DEPRECATED 方法

#### P2-4: 持仓保护阈值参数名不一致

**文件**: strategy_defaults.py `hold_protection_threshold` vs portfolio_backtest.py `hold_protection_threshold`  
**问题**: `hold_protection_threshold` 在 GLOBAL_RISK 中定义为 0.04，但 `_rebalance` 方法中通过 `self._risk_config.get('hold_protection_threshold', GLOBAL_RISK.get('hold_protection_threshold', 0.04))` 读取。如果前端传入不同的 `hold_protection_threshold`，可能覆盖 GLOBAL_RISK 的值，但文档注释中 V57 说的是 "从5%→4%"，实际 GLOBAL_RISK 的值已经是 0.04。  
**影响**: 参数已正确对齐，但注释中引用的旧值(0.05)可能造成混淆。

#### P2-5: 首板打板 STRATEGY_PULLBACK_PARAMS 缺失

**文件**: sell_signal_checker.py:452  
**问题**: `STRATEGY_PULLBACK_PARAMS` 只定义了半路追涨、跌停翘板、龙头低吸三个策略的冲高回落参数，首板打板没有。但首板打板也不使用冲高回落信号（STRATEGY_SELL_SIGNALS 中首板打板只有 `高开即卖`），所以这不是 bug，但代码结构上不够清晰。  
**建议**: 在 `STRATEGY_PULLBACK_PARAMS` 中添加注释说明首板打板不需要冲高回落参数

---

## 二、结果优化分析

### 2.1 回撤增加的根因分析

V57→V58 的关键变化：return +46%, drawdown +64%, sharpe -0.41

| 参数 | V57 | V58 | 对回撤的影响 |
|------|-----|-----|------------|
| intraday_lock_min_high_rise | 5% | 4% | ⚠️ 更早触发利润锁定→可能过早退出反弹股 |
| intraday_lock_pullback_pct | 2% | 1.5% | ⚠️ 更敏感→更多利润锁定→错过后续涨幅 |
| hold_protection_threshold | 5% | 4% | ⚠️ 更少股票受保护→更多调仓卖出→可能卖在低点 |
| 首板打板 SL | 3% | 2.5% | ✅ 更早截断亏损→应该降低回撤 |
| 半路追涨 SL | 4% | 3% | ✅ 更早截断亏损→应该降低回撤 |
| 首板打板 hit_probability | 45%/60% | 40%/45% | ✅ 更少低质量成交→应该降低回撤 |

**核心矛盾**: 更紧的止损(SL)应该降低回撤，但更激进的利润锁定和更窄的持仓保护反而可能增加回撤。

**根因假设**:

1. **利润锁定过早退出**: min_high_rise=4% + pullback=1.5% 意味着只要盘中涨4%且从高点回落1.5%就锁定利润。但很多超短线股正常波动就有1.5%的盘中回落，过早锁定导致：
   - 错过后续继续上涨的股票
   - 卖出后现金闲置→错过反弹机会→净值下降→回撤增大

2. **持仓保护缩窄(5%→4%)**: 更多盈利4%-5%的股票失去保护被调仓卖出。这些股票可能正在上涨中，调仓卖出后次日继续涨。同时4%保护阈值让一些微利股也受保护，增加了调仓难度（持仓无法及时调整）。

3. **超时退出的恶化**: 利润锁定过早退出→现金占比更高→仓位不足→选到的新股质量可能不如被锁定的旧股→超时卖出时亏损更大。

### 2.2 首板打板策略(33.3%胜率，12笔)的影响

首板打板在当前参数下（SL=2.5%, TP=8%, hit_probability 40%/45%）贡献有限：
- 12笔交易，33.3%胜率 → 4笔盈利8笔亏损
- 假设平均盈利+5%，平均亏损-3% → 净贡献 = 4×5% - 8×3% = -4%
- 但首板打板的跳空止损（open直接低于SL）亏损更大（-6%到-8%）

**建议**: 考虑将首板打板 hit_probability 进一步降低到 30%/35%，或干脆禁用该策略（如 V40 测试所示，去掉首板打板后夏普从13.34降到12.67但回撤改善）。当前12笔交易样本太小，统计不显著。

### 2.3 跳空止损(7笔，avg -6.26%)优化

跳空止损是最大单笔亏损来源。2.5% SL 对首板打板来说太紧：
- 首板次日经常跳空低开-3%~-8%
- 2.5% SL 在跳空场景下无效（open < stop_price → 以 open 卖出）
- 实际亏损取决于 open 跌幅，而非 SL 百分比

**优化方案**:
1. **跳空止损价格下限**: 设置最低卖出价为 stop_price × 0.97（给3%缓冲），避免在极端跳空时以过低价格成交
2. **首板打板专用跳空保护**: 首板次日如果 open 跌幅 > 5%，等待盘中反弹再卖（而非立即以 open 卖出）。但回测中只有日线数据，无法模拟盘中反弹
3. **更现实的方案**: 首板打板 SL 回调到 3%（与半路追涨一致），减少跳空止损触发频率

### 2.4 max_position_per_stock=0.35 是否过于激进

当前配置：3只股票 × 35% = 105% 理论仓位
- 实际受现金限制，通常只有2-3只满仓
- 35%单票上限提供了足够的分散度
- 但如果一只股票止损-3%，对组合的影响 = 35% × 3% = 1.05%
- 三只同时止损 = 3.15%，这接近 V58 的 5.06% 回撤的60%

**优化方案**: 降低到 0.30（30%单票上限），三只同时止损 = 2.7%，给回撤留更多缓冲。但会减少单票收益贡献。

### 2.5 综合优化建议

| 优化项 | 当前值 | 建议值 | 预期效果 |
|--------|--------|--------|----------|
| intraday_lock_min_high_rise | 0.04 | 0.05 | 减少过早利润锁定，让更多盈利股继续运行 |
| intraday_lock_pullback_pct | 0.015 | 0.02 | 减少误触发，只锁定真正大幅回撤 |
| hold_protection_threshold | 0.04 | 0.05 | 更多盈利股受保护，避免调仓卖出后反弹 |
| 首板打板 SL | 0.025 | 0.03 | 减少跳空止损触发频率 |
| max_position_per_stock | 0.35 | 0.30 | 降低单票风险敞口 |

**预期**: 回撤从5.06%降至3-4%，收益可能从148%降至130-140%，但夏普比率应回升至10+。

---

## 三、回测-实盘对齐分析

### 3.1 止损止盈参数

| 策略 | 回测 SL/TP | 实盘 SL/TP | 对齐状态 |
|------|-----------|-----------|---------|
| 半路追涨 | 3%/12% | ✅ 从STRATEGY_CONFIGS读取 | ✅ 对齐 |
| 首板打板 | 2.5%/8% | ✅ 从STRATEGY_CONFIGS读取 | ✅ 对齐 |
| 龙头低吸 | 3%/30% | ✅ 从STRATEGY_CONFIGS读取 | ✅ 对齐 |
| 跌停翘板 | 5%/20% | ✅ 从STRATEGY_CONFIGS读取 | ✅ 对齐 |

**V40修复确认**: 之前实盘硬编码5%/10%已修复，现从strategy_defaults动态读取。

### 3.2 冲高回落/利润保护逻辑

| 卖出信号 | 回测实现 | 实盘实现 | 对齐状态 |
|----------|---------|---------|---------|
| 冲高回落 | SellSignalChecker.check_pullback | position_manager.daily_check | ✅ 参数来源一致(GLOBAL_RISK+STRATEGY_CONFIGS) |
| 利润保护 | SellSignalChecker.check_profit_protect | position_manager.daily_check | ✅ 逻辑一致(open_rise≥2%+close_rise≥2%+close<open) |
| 利润锁定 | portfolio_backtest._check_intraday_profit_lock | position_manager.daily_check | ⚠️ 参数路径不同但结果一致 |
| 高开即卖 | SellSignalChecker.check_high_open_sell | position_manager.daily_check | ✅ 首板打板专用，逻辑一致 |
| 跳空止损 | _check_and_execute_forced_sells + _rebalance | position_manager.daily_check | ✅ open≤stop_price→以open卖出 |

### 3.3 关键分歧点

#### 分歧1: 实盘只做告警，不做自动卖出

**回测**: 冲高回落/止损/止盈/利润锁定 → 自动执行卖出  
**实盘**: position_manager.daily_check → 生成告警列表 → 需人工或 RiskChecker 执行  
**影响**: 实盘可能错过最佳卖出时机（告警→决策→执行有延迟）  
**建议**: RiskChecker 应自动执行 danger 级别告警（止损/跳空止损/超时），仅 warning/success 级别需人工确认

#### 分歧2: 实盘持仓超期检查使用自然日/1.5近似

**回测**: `_calc_trade_days_held` 精确计算交易日  
**实盘**: `Position.hold_days()` 优先查交易日历，fallback 用自然日/1.5  
**影响**: 实盘的 hold_days 可能与回测有1天偏差（如周五买入→周一：回测=1天，实盘=1天(3/1.5=2→但上限为2)）  
**风险等级**: 低（偏差≤1天，且超时强卖有缓冲）

#### 分歧3: 实盘利润锁定参数路径

**回测**: `_risk_config` → `GLOBAL_RISK` → `STRATEGY_PULLBACK_PARAMS` + `_strategy_risk_params` (死代码) → 硬编码 fallback  
**实盘**: `GLOBAL_RISK` → `_strategy_risk_params` (死代码) → 无 fallback  
**当前**: 两边都 fallback 到 GLOBAL_RISK(0.04/0.015/0.02)，结果一致  
**风险**: 如果未来在 STRATEGY_CONFIGS 中添加策略级利润锁定参数，需要同时更新两个文件

#### 分歧4: 实盘冲高回落 profit_lock_threshold

**回测**: `STRATEGY_PULLBACK_PARAMS['龙头低吸']['pullback_profit_lock_threshold'] = 0.06`  
**实盘**: `_strategy_params.get('pullback_profit_lock_threshold', None)` → 从 STRATEGY_CONFIGS.params 读取 → 0.06  
**对齐状态**: ✅ 一致

---

## 四、具体代码审查

### 4.1 `_check_intraday_profit_lock` 参数读取路径

```python
# portfolio_backtest.py L196-232
# 参数读取链:
# 1. self._risk_config.get('intraday_lock_min_high_rise', ...) → V48修复后从GLOBAL_RISK写入
# 2. GLOBAL_RISK.get('intraday_lock_min_high_rise', 0.04) → 当前值0.04
# 3. V58新增: code→stock_to_strategy→STRATEGY_PULLBACK_PARAMS+_strategy_risk_params → 死代码
# 实际运行: 始终走路径1+2，值为0.04/0.015/0.02
```

**问题**: V58新增的第三层(策略级参数)是死代码，增加了理解成本但不影响结果。

### 4.2 `_apply_limit_up_hit_probability` 概率一致性

```python
# portfolio_backtest.py L3861-3890
# 读取路径: self._strategy_params.get('首板打板', {})
# self._strategy_params 由 _init_run_config 从 selected_strategies[].params 填充
# selected_strategies 来自前端或 ALL_STRATEGIES(兜底)
# ALL_STRATEGIES 从 STRATEGY_CONFIGS 读取 → 包含 hit_probability_* 参数
# 因此: 实际运行时概率与 STRATEGY_CONFIGS 一致
```

**V58-BUG-001 修复确认**: 注释说从0.45/0.65→0.40/0.45，与 strategy_defaults.py V57 修改一致。已修复。

### 4.3 `_pending_force_sell` T+1 实现

```python
# 强制空仓时T+1跳过: L1532
# self._pending_force_sell.add(code)  # 记录次日优先清仓

# 次日处理: L261-272
# if hasattr(self, '_pending_force_sell') and self._pending_force_sell:
#   for _pf_code in list(self._pending_force_sell):
#     if _pf_code in holdings → 以open价强制卖出(延后)
#   self._pending_force_sell -= _to_sell_now  # 清理已处理的
```

**逻辑正确性**: ✅ 正确实现  
**P1-1 问题**: 类级变量共享问题（见上文）

### 4.4 净值/回撤计算

```python
# _record_daily_net_value:
# current_net_value = cash + holdings_market_value
# daily_profit = current_net_value - last_net_value
# drawdown = (peak_value - current_net_value) / peak_value  # 正数=回撤
# normalized_nv = current_net_value / _initial_cash
```

**正确性**: ✅ 回撤计算正确（从峰值计算，非从初始值）  
**停牌折价**: ✅ V36实现的停牌>3天每日-1%折价正确  
**注意**: `net_value_series[].daily_profit` 是归一化值(÷initial_cash)，`daily_profit_list` 是绝对值(元)，两者在 `_build_run_result` 中都有使用

### 4.5 佣金/滑点计算

**买入**:
- `buy_price_adj = price * (1 + slippage_pct)` — 含滑点的买入价
- `commission = max(gross_amount * BUY_COMMISSION, MIN_COMMISSION)` — 佣金
- `total_cost = gross_amount + commission` — 总成本
- `cost_basis[ts_code] = buy_price_adj` — 成本记录含滑点但不含佣金

**卖出**:
- `slippage_pct = 0 if not should_apply_slippage(reason) else self._get_slippage_for_code(ts_code)`
- `sell_price_adj = price * (1 - slippage_pct)` — 扣滑点
- `commission = max(gross_amount * SELL_COMMISSION, MIN_COMMISSION)`
- `stamp_tax = gross_amount * STAMP_TAX`
- `net_amount = gross_amount - commission - stamp_tax`

**结论**: ✅ 无双重计费。买入滑点加在价格上，卖出滑点从价格扣，佣金和印花税独立计算。

**注意**: `cost_basis` 不含买入佣金，这意味着止损/止盈基于滑点后价格而非全成本价。这是有意设计（SL/TP基于成交价更直观），但理论上应基于全成本价更保守。

---

## 五、修复优先级建议

| 优先级 | 编号 | 修复内容 | 预计影响 |
|--------|------|----------|---------|
| **P1** | P1-1 | `_pending_force_sell` 移至 `__init__` 实例化 | 防止跨回测数据污染 |
| **P1** | P1-2 | sell_signal_checker fallback 0.05→0.04 | 消除潜在不一致 |
| **P1** | P1-5 | 统一利润锁定到 sell_signal_checker | 消除重复代码风险 |
| P2 | P1-3 | 更新 position_manager 注释 0.08→0.06 | 消除误导 |
| P2 | P1-4 | 清理 V58 死代码或添加策略级参数 | 代码简化 |
| P2 | P1-6 | 清理 position_manager 死代码或添加参数 | 代码简化 |
| P2 | P2-1 | 移除 strategy_filter.py | 减少混淆 |
| P2 | P2-2 | 删除 check_full_sell | 代码简化 |

---

## 六、回撤优化方案

### 方案A: 回调 V57 利润锁定参数（推荐）

```python
# strategy_defaults.py
"intraday_lock_min_high_rise": 0.05,   # 4%→5%，减少过早锁定
"intraday_lock_pullback_pct": 0.02,    # 1.5%→2%，减少误触发
"hold_protection_threshold": 0.05,     # 4%→5%，更多盈利股受保护
```

**预期**: 回撤从5.06%降至3-3.5%，收益从148%降至120-130%，夏普回升至10+

### 方案B: 仅回调利润锁定，保留其他V58参数

```python
"intraday_lock_min_high_rise": 0.05,   # 只回调此项
"intraday_lock_pullback_pct": 0.02,    # 只回调此项
# hold_protection_threshold 保持0.04
# 首板打板SL保持0.025
```

**预期**: 回撤从5.06%降至3.5-4%，收益保持130-140%

### 方案C: 首板打板专属优化

```python
# 首板打板SL回调到3%（与半路追涨一致）
"first_limit_up.riskParams.stop_loss_pct": 0.03,
# 进一步降低首板打板成交概率
"first_limit_up.params.hit_probability_slow": 0.35,
"first_limit_up.params.hit_probability_normal": 0.30,
```

**预期**: 减少首板打板跳空止损亏损，但对整体回撤影响有限（仅12笔）

### 推荐方案: A+B混合

先只回调利润锁定参数(intraday_lock_min_high_rise=0.05, intraday_lock_pullback_pct=0.02)，保留 hold_protection=0.04 和首板打板SL=0.025。观察回撤是否改善到可接受范围(4%以下)，再决定是否进一步调整。

---

## 七、总结

1. **代码质量**: 无P0级bug。P1级问题主要是 `_pending_force_sell` 类级变量共享和参数 fallback 不一致，均不影响当前单次回测结果的正确性。

2. **回撤根因**: V58回撤增加64%的主要原因是利润锁定参数过于敏感（min_high_rise 5%→4%，pullback 2%→1.5%），导致过早退出盈利头寸。虽然更紧的止损(SL)理论上应该降低回撤，但利润锁定和持仓保护的变更方向相反，净效果是回撤增加。

3. **回测-实盘对齐**: 止损止盈参数已对齐(V40修复确认)。卖出信号逻辑一致，但实盘只生成告警不自动执行，存在延迟风险。利润锁定参数路径虽不同但当前值一致。

4. **优化方向**: 回调利润锁定参数到V57水平是最直接的回撤优化手段，预计可将回撤从5.06%降至3-4%区间，同时保持V58大部分收益提升。
