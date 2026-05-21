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

**状态**: ✅已确认已处理

**分析**: 非调仓日路径_check_and_execute_forced_sells中, T+1过滤在循环顶部(第206行)对
所有holdings生效,包括超时强卖代码。调仓日_rebalance路径中, sell_codes(含over_hold_codes)
在第3771行统一T+1过滤。两条路径均已正确处理,无需额外修复。

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

### P2-5: factor_auto_compute.py涨跌停阈值硬编码0.9/1.1 (✅已修复)

**问题**: factor_auto_compute.py中`open_above_limit_down`、`limit_down_open_amount`、
`rise_after_limit_down`、`limit_up_open_amount`、`open_above_limit`、`open_below_limit`
等字段的计算使用硬编码的0.9/1.1(主板10%涨跌停价),不区分板块。

创业板/科创板(300/301/688)涨跌停幅度20%,应使用0.8/1.2。
北交所(8/4)涨跌停幅度30%,应使用0.7/1.3。

**影响**: 
- 对当前回测:无影响(factor_engine从MongoDB读取实时数据,回测期内没有创业板翘板信号因阈值错误被漏算)
- 对factor_auto_compute预计算数据:创业板/科创板/北交所股票的涨跌停相关因子值可能不正确
- 重新运行auto_compute后修复会生效

**修复**: 根据股票代码前缀确定板块,使用对应的涨跌停价格阈值:

---

### 优化建议

1. ~~monthly_profit + sharpe计算统一修复~~: ✅已完成(P1-1)
2. ~~over_hold_codes纳入T+1过滤~~: ✅已确认已处理
3. **check_full_sell标记deprecated**: 减少维护混淆
4. **factor_auto_compute涨跌停阈值按板块区分**: ✅已完成(P2-5)
5. **universe.py _get_limit_up_stocks性能优化**: 当前逐文档遍历,可用$match+聚合优化(低优先级)
6. **special_period_filter.py: 月末/季末/年末用自然日近似交易日**: 可接受(注释已说明)
7. **factor_quality_checker.py: STRATEGY_REQUIRED_FACTORS与实际筛选条件需同步维护**: 文档级问题

### 交易分析

| 卖出原因 | 笔数 | 胜率 | 平均利润 | 总利润 |
|---------|------|------|---------|--------|
| 冲高回落 | 24 | 100% | +7.67% | +184.1% |
| 利润保护 | 3 | 100% | +2.97% | +8.9% |
| 高开即卖 | 4 | 100% | +3.11% | +12.4% |
| 止盈 | 10 | 100% | +16.51% | +165.1% |
| 止损 | 13 | 0% | -4.84% | -63.0% |
| 跳空止损 | 3 | 0% | -9.94% | -29.8% |
| 强制空仓 | 2 | 100% | +10.74% | +21.5% |
| 调仓 | 48 | 70.8% | +2.84% | +136.4% |

**关键发现**: 止损(含跳空)共16笔,总亏损-92.8%,是最大亏损来源。其中跳空止损(-29.8%)无法避免(日线数据限制)。龙头低吸占9/16止损笔,但贡献222%总收益(最高),不建议缩减。

### 文件审查状态
- portfolio_backtest.py: ✅逐行审查
- sell_signal_checker.py: ✅审查(slippage规则/信号优先级/T+1)
- factor_engine.py: ✅审查(_prev因子/pre_close修复/缓存)
- factor_library.py: ✅审查(因子定义/方向)
- strategy_defaults.py: ✅审查(参数一致性/单一来源)
- ultra_short.py: ✅审查(V31_defaults修复/因子构建循环)
- factor_auto_compute.py: ✅审查+修复(P2-5涨跌停阈值)
- universe.py: ✅审查(缓存/涨跌停区分)
- factor_quality_checker.py: ✅审查(因子质量检查逻辑)
- models.py: ✅审查(数据模型定义)
- special_period_filter.py: ✅审查(假期/会议/月末配置)
