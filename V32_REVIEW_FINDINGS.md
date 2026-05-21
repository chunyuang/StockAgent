# V32 回测引擎审查发现

## V32结果 (P1-1修复后): 101.44%收益 / 12.73夏普 / 2.82%回撤 / 72.22%胜率 / 1.76盈亏比 / 108笔 / 19.4秒
## V31基线: 100.71% / 12.48 / 2.82% / 71.96% / 1.77 / 107笔
## 改善: 收益+0.73%, 夏普+0.25, 胜率+0.26%
## 长周期验证(3个月): 205.21% / 12.01 / 2.82% / 73.97% / 1.90 / 146笔

---

### P1-1: monthly_profit计算偏移1天 (portfolio_backtest.py:2143~2155)

**问题**: 当`net_value_series[0]['net_value'] != 1.0`时，代码在所有4个列表头部insert(0, x):
- `net_value_series.insert(0, {net_value: 1.0, ...})`
- `daily_profit_list.insert(0, 0.0)` ← 问题源
- `drawdown_series.insert(0, 0.0)`
- `daily_cash_list.insert(0, 1.0)`

但`all_trade_dates`没有对应的insert，导致`monthly_profit`计算中:
- `daily_profit_list[0]=0.0` 配对 `all_trade_dates[0]=day1` (错误: day1被分配了0利润)
- `daily_profit_list[1]=real_day1_profit` 配对 `all_trade_dates[1]=day2` (错误: 偏移1天)
- 最后1天的利润被丢弃 (i >= len(all_trade_dates))

**触发条件**: 首个交易日有交易(几乎总是触发,因为回测第1天即调仓买入)

**影响**: 月度收益计算偏移1天,最后1天利润丢失。不影响总收益率/夏普/回撤。

**修复**: monthly_profit计算前保存原始daily_profit_list,用原始列表计算,insert仅用于前端显示。

---

### P1-2: daily_profit_list偏移导致sharpe/sortino轻微失真

**问题**: insert(0, 0.0)在daily_profit_list头部添加一个0利润条目,
sharpe计算遍历整个daily_profit_list(包含额外0条目)。

**影响**: 轻微 - 1个额外的0.0日收益率在~50天数据中影响很小。
avg_return被拉低约2%,std被轻微拉高。

**修复**: 与P1-1一并修复,sharpe/sortino计算也使用原始列表。

---

### P2-1: _check_and_execute_forced_sells中over_hold_codes未考虑T+1

**问题**: 在_check_and_execute_forced_sells(非调仓日),超时强卖代码`over_hold_codes`
在T+1过滤之前构建。T+1过滤只处理`sell_codes`,不处理`over_hold_codes`。
如果一只股票今日买入,今日就被标记为超时,它不会被T+1过滤阻止卖出。

**实际影响**: 极低 - max_hold_days>=3,不可能买入当天就超时。但代码逻辑不一致。

**修复**: 将over_hold_codes也纳入T+1过滤,或合并到sell_codes后再统一过滤。

---

### P2-2: check_full_sell()死代码 (sell_signal_checker.py:489)

**问题**: `SellSignalChecker.check_full_sell()`方法已定义但从未在portfolio_backtest.py中调用。
当前_rebalance和_check_and_execute_forced_sells都直接使用`_check_early_sell_signals`+内联SL/TP检查。

**影响**: 代码冗余,增加维护负担。如果有人调用check_full_sell可能引入不一致行为(它内部用break只检查第一个策略)。

**修复**: 标记为deprecated或删除。

---

### P2-3: factor_engine _prev因子fillna(0)可能误杀新股

**问题**: factor_engine.py第287行,`result[f"{col}_prev"] = result["ts_code"].map(prev_map).fillna(0)`
对于T-1日无数据的新股,_prev因子被填充为0。

- `volume_ratio_prev=0` → 半路追涨/首板打板`volume_ratio_prev >= 2.0`过滤掉(正确:保守)
- `circ_mv_prev=0` → 不影响当前筛选条件
- `pct_chg_prev=0` → 不影响当前筛选条件

**影响**: 低 - 新股本身不应该被半路追涨选中(上市首日无前5日均量),0过滤是合理的。

---

### P2-4: strategy_filter.py未被引用

**问题**: strategy_filter.py已从portfolio_backtest.py拆分但未被调用。
portfolio_backtest.py仍使用内联的`_build_strategy_filter_conditions`方法。

**影响**: 代码冗余,两个实现可能不同步。

---

### 优化建议

1. **monthly_profit + sharpe计算统一修复**: 将insert移到_build_run_result的计算段之后
2. **over_hold_codes纳入T+1过滤**: 代码一致性
3. **check_full_sell标记deprecated**: 减少维护混淆
