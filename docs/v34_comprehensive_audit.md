# V34 全面审查报告 — 回测+实盘+UI

> 2026-05-23 | 全面审查，涵盖回测引擎、实盘模块、前端UI

## 基线指标 (2025Q4, V33)

| 指标 | 值 |
|------|-----|
| 总收益率 | 98.34% |
| 夏普比率 | 10.53 |
| Sortino | 50.16 |
| 最大回撤 | 1.78% |
| 胜率 | 77.05% |
| 盈亏比 | 2.65 |
| 信号数 | 61 |
| 回测耗时 | 19.9s |

---

## 一、回测引擎审查

### P0-1: monthly_profit计算的V32修复仍有一个隐患

**文件**: portfolio_backtest.py:2825-2855

**问题**: `_need_initial_insert`的insert(0, ...)在monthly_profit计算之后执行。这本身正确，但insert后`result["daily_profit"]`被重新归一化（第2898行），而`result["positions"]["daily_profit"]`仍是旧的归一化列表（第2645行在insert前写入）。

**影响**: 前端如果从`result.positions.daily_profit`读取，会缺少初始0值条目，导致净值曲线比net_value_series短1天。

**修复**: insert后同步更新`result["positions"]["daily_profit"]`。

### P0-2: _build_run_result方法过长(800+行)

**文件**: portfolio_backtest.py:2115-2920

**问题**: 单方法800+行，包含绩效计算、交易合并、策略统计、图表数据、月度收益5段逻辑。V32注释说"不可拆分"是因为run_state是dict，但可以拆分为独立的纯函数。

**影响**: 维护困难，每次修改容易引入regression。

**修复**: 拆分为_build_metrics(), _merge_trades(), _build_strategy_results(), _build_chart_data(), _calc_monthly_profit()5个子方法。

### P1-1: sortino_ratio计算方法非标准

**文件**: portfolio_backtest.py:2610-2616

**问题**: 当前sortino计算使用 `downside_variance = sum(r**2 for r in downside_returns) / len(daily_returns)`，这是对负收益取平方后除以总样本数。标准Sortino应该是：
```
downside_deviation = sqrt(sum(min(r-target, 0)**2) / N) 其中N是总样本数
```
当前实现中target=0是对的，但只取了负收益的平方再除以总数，等价于标准做法。然而Sortino=50.16相对于Sharpe=10.53过高（正常Sortino/Sharpe约1.2-1.5倍），说明下行波动极低。

**影响**: Sortino值失真，容易误导用户认为策略下行风险极小。

**修复**: 添加Sortino/Sharpe比率的合理性检查，如果>3则标注"不可靠"。

### P1-2: strategy_filter.py未被引用(P2-4遗留)

**文件**: factor_selection/strategy_filter.py

**问题**: 该文件已从portfolio_backtest.py拆分但从未被import。选股逻辑仍在portfolio_backtest.py的`_build_strategy_filter_conditions`中。

**影响**: 两份实现可能不同步，维护混乱。

**修复**: 在portfolio_backtest.py中import并使用strategy_filter.py，或删除strategy_filter.py。

### P1-3: check_full_sell()死代码(P2-2遗留)

**文件**: sell_signal_checker.py:489

**问题**: `SellSignalChecker.check_full_sell()`已定义但从未被调用。且该方法的逻辑（按优先级遍历信号后在第一个策略就break）与外层_check_and_execute_forced_sells的逻辑不一致。

**影响**: 代码冗余，如果有人误调用可能引入bug。

**修复**: 标记@deprecated或删除。

### P1-4: daily_cash_list insert后未同步更新formatted_drawdown_series

**文件**: portfolio_backtest.py:2882-2892

**问题**: 当`_need_initial_insert=True`时，net_value_series/daily_profit_list/drawdown_series/daily_cash_list都insert了初始值。但`formatted_drawdown_series`在insert之前已构建（第2589行），少了一个初始条目。

**影响**: formatted_drawdown_series比net_value_series短1天，前端回撤曲线与净值曲线不匹配。

**修复**: 在insert块中重建formatted_drawdown_series。

### P2-1: 日收益率序列计算方式不一致

**文件**: portfolio_backtest.py:2584-2599

**问题**: Sharpe计算中，日收益率使用`daily_profit_list[i] / current_value`逐日累加计算。但current_value从initial_cash开始逐日加上profit。这等价于用绝对利润/当前市值，与标准日收益率`(V_t/V_{t-1} - 1)`略有差异。当资金变化大时（如100%收益），两种方法会显著不同。

**当前实现**:
```python
current_value = self._initial_cash
for p in daily_profit_list:
    if current_value > 0:
        daily_returns.append(p / current_value)
    current_value += p
```

这其实是正确的：`p / current_value = (V_t - V_{t-1}) / V_{t-1} = V_t/V_{t-1} - 1`

**结论**: 逻辑正确，无需修改。

### P2-2: position_series中cash占比使用daily_cash_list但daily_cash_list含义模糊

**文件**: portfolio_backtest.py:2727-2733

**问题**: `daily_cash_list`存储的是什么？如果是绝对现金值，`1 - cash/equity`才是仓位。但代码中`pos_val = max(0.0, 1.0 - daily_cash_list[i])`假设cash_list已经是占比(0-1)。

**需要验证**: daily_cash_list存储的是绝对值还是归一化占比。

---

## 二、实盘模块审查

（待live-trading-audit子代理完成）

---

## 三、前端UI审查

（待frontend-ui-audit子代理完成）

---

## 四、回测-实盘对齐

### 关键对齐点

| 维度 | 回测 | 实盘 | 对齐状态 |
|------|------|------|---------|
| 选股条件 | _build_strategy_filter_conditions | generate_daily_signals | ⚠️ 需验证 |
| 因子数据源 | factor_engine (MongoDB) | factor_engine (MongoDB) | ✅ 共享 |
| 参数来源 | strategy_defaults.py | strategy_defaults.py | ✅ 共享 |
| 止损止盈 | _check_and_execute_forced_sells | risk_checker | ⚠️ 需验证逻辑一致 |
| 仓位管理 | 内联计算 | position_manager | ⚠️ 需验证 |
| 买入价 | _get_buy_price_for_stock | signal_pusher推送 | ⚠️ 回测模拟 vs 实盘市价 |
| T+1规则 | _cost_basis_date检查 | position_manager.t1_blocked | ✅ 逻辑一致 |

### 优化: 回测与实盘相互助力

1. **回测→实盘**: 回测的胜率/盈亏比可指导实盘信号过滤(如只推送胜率>60%的策略信号)
2. **实盘→回测**: 实盘的成交滑点数据可回注到回测的slippage模型
3. **共享因子引擎**: 两者都使用FactorEngine，因子计算逻辑天然一致
4. **参数统一**: strategy_defaults.py作为单一来源，两者共享

