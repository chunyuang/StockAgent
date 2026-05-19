# 回测模块V10审查报告

**日期**: 2026-05-20
**审查范围**: portfolio_backtest.py (3935行) + ultra_short.py (669行)
**基线对比**: V9审查(cf6557d)

## 🔴 P0级修复 (5个)

### P0-1: trade_date类型不匹配导致涨跌停聚合始终返回0
**根因**: `universe.get_universe()`返回string类型的trade_date，L800-801将其转为`str(d)`格式化，但MongoDB中trade_date存储为int。所有聚合查询`{trade_date: '20260105'}`无法匹配int类型，`_print_market_environment`始终返回涨停0只/跌停0只。

**影响**: 触发force_empty_position导致49天全部无法交易，所有回测结果为0信号0交易。

**修复**: 
- `all_trade_dates`/`rebalance_dates`统一转为int（非str）
- 循环入口确保trade_date为int
- rebalance_dates日志join时转str

**Git**: d8530a6

### P0-2: INDEX_DAILY查询trade_date类型不匹配
**根因**: L1557用string类型trade_date查询INDEX_DAILY集合（存储int），导致MA60过滤功能完全失效。

**修复**: `{"trade_date": int(trade_date)}`

**Git**: 70411ce

### P0-3: strategies/selected_strategies从错误层级读取
**根因**: `ultra_short.py` L91 `strategies = req_params.get("strategies", [])`，其中`req_params = params.get("params", {})`。当API调用者把strategies放在顶层params时，strategies解析为空列表，fallback到ALL_STRATEGIES（5策略全选）。

**影响**: 原本只需2策略时变成了5策略全选，选股逻辑混乱。实际买入包含了涨停开板、龙头低吸等未选择策略的股票。

**修复**: 优先从顶层params读取，fallback到内层params.params

**Git**: 70411ce

### P0-4: strategy_params/period从错误层级读取
**根因**: L97 `strategy_params = req_params.get("params", {})` 读取的是`params.params.params`三层嵌套。实际风控参数在`params.params`层级。

**影响**: 风控参数(stop_loss_pct/take_profit_pct等)无法传入，使用GLOBAL_RISK默认值。但selected_strategies.riskParams可部分补偿。

**修复**: `strategy_params = params.get("params", req_params.get("params", {}))`

**Git**: a9d288d

### P0-5: enable_*功能开关从错误层级读取
**根因**: 与P0-3同理，功能开关从内层读取，顶层传入时无法识别。

**修复**: 优先从顶层params读取

**Git**: 70411ce

## 📊 回测基线验证

| 指标 | V10修复后 | V10修复前(bug) |
|------|-----------|----------------|
| 收益率 | 26.26% | 0.00% |
| 夏普比率 | 4.15 | 0.00 |
| 最大回撤 | 4.01% | 0.00% |
| 胜率 | 46.36% | 0.00% |
| 盈亏比 | 2.32 | 0.00 |
| 交易数 | 113 | 0 |

**配置**: 2策略(半路追涨+跌停翘板), SL5%/TP10%/3天, 100万初始资金, 20260105-20260320

## ⚠️ P2级待修复

1. **FactorQualityChecker误报13个"缺失因子"**: `ultra_short.py`的`all_factors`列表使用策略参数名（如`rise_pct`、`close_rise_pct`、`opening_pct_min`）当因子名，但这些不是DataFrame列名，QC检测为缺失并设默认值。不影响回测逻辑但增加计算开销。
2. **盈亏比/夏普日志时序问题**: 中间汇总日志打印0.00但最终API返回正确值。原因是profit_loss_ratio/sharpe_ratio在L2224初始化为0，日志在L2311打印，但实际计算在L2449/L2478。

## 📝 教训

1. **MongoDB trade_date类型**: 所有集合(stock_daily_ak_full/daily_basic/index_daily)的trade_date都是int，查询时必须确保int类型。universe返回的可能是string。
2. **API参数层级一致性**: `ultra_short.py`的params结构有3层(params/params.params/params.params.params)，不同调用者把参数放在不同层级。必须从顶层优先读取。
3. **系统性类型问题**: 同一变量在不同模块间传递时类型可能变化(string→int)，必须在边界处统一。
