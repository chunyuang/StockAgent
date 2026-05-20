# V20回测模块审查报告

## 基线回测结果 (2策略: 半路追涨+跌停翘板, 20260105-20260320)
- 收益: 69.51%
- 夏普: 9.03
- 回撤: 3.04%
- 胜率: 68.27%
- 盈亏比: 2.16
- 交易: 104笔
- 信号: 105个
- 耗时: 13.9s

## 审查发现 (按优先级)

### P0级 (逻辑错误/数据问题)

**P0-1: INDEX_DAILY无ma60字段，MA60过滤形同虚设**
- `_process_rebalance_day`中`enable_ma60_filter`查询`index_daily`的`ma60`字段
- 但INDEX_DAILY只有`ts_code, trade_date, close, pct_chg`4个字段
- `index_data.get("ma60")`始终返回None → `close < ma60`始终False → MA60过滤从不触发
- 影响：大盘跌破MA60时应降低仓位50%，但从未生效
- 修复：用前60个交易日close计算MA60

**P0-2: 非调仓日净值记录中last_prices更新不完整**
- `_process_non_rebalance_day`中，`if _prices_for_display: last_prices = _prices_for_display`
- 但`_prices_for_display`只包含holdings的股票，不包含已卖出股票
- 后续`_record_daily_net_value`用`last_prices`计算持仓市值，如果某股停牌close=0则用`_last_valid_price`
- 潜在问题：last_prices被覆盖为只含holdings的字典，之前卖出的股票价格丢失

**P0-3: 跌停翘板circ_mv参数默认20亿，但V16记忆显示30亿会过滤过多候选**
- strategy_defaults.py中`min_circulation_market_cap: 20`
- V16审查笔记说"30亿过滤过多跌停翘板候选"，所以保持20亿
- 但portfolio_backtest.py中`_build_strategy_filter_conditions`的跌停翘板默认也是20亿
- 一致性OK，但可能需要验证20亿vs30亿的影响

### P1级 (性能/优化)

**P1-1: 策略筛选中factor_df.copy()每次都深拷贝整个DataFrame**
- `_print_single_strategy_filtering`中`current_df = factor_df.copy()`
- 5个策略=5次完整深拷贝，每次~5000行×40列
- 优化：改为浅拷贝+独立筛选掩码，避免5次内存分配

**P1-2: _compute_weights中factor_df逐行查找composite_score/pct_chg**
- `row = factor_df[factor_df['ts_code'] == code]` → O(N)每行全表扫描
- 候选股可能10-50只，每次扫描5000行
- 优化：预构建ts_code→row的索引dict

**P1-3: 每日打印大量日志(push_log)到MongoDB，消耗IO**
- 回测2.5个月≈50天，每天打印5-10KB日志 → ~500KB per run
- push_log每条都写MongoDB，高频IO
- 优化：日志批量写入或降低频率

**P1-4: _get_stock_names每次rebalance后都重新查询**
- 即使大部分股票已在缓存中，仍重新查询所有records中的代码
- 优化：先过滤缓存未命中的，只查询缺失的

**P1-5: 竞价过滤中无真实数据时遍历factor_df逐行查找**
- `code_rows = factor_df[factor_df['ts_code'] == code]` → O(N*M)
- 优化：预构建ts_code→opening_pct_chg的dict

### P2级 (代码质量/防御性)

**P2-1: strategy_filter.py未被portfolio_backtest.py引用，代码冗余**
- strategy_filter.py与_build_strategy_filter_conditions功能重复
- 应统一为单一来源

**P2-2: ultra_short.py中变量_defaults在for循环外定义但只在特定分支内使用**
- L154: `_defaults = STRATEGY_CONFIGS.get(strategy_id, {}).get("params", {})`
- 但strategy_id来自循环内，在外层定义_defaults会在第二次循环时使用上一次的值
- 实际检查：_defaults在每次for迭代开头重新赋值，但strategy_id是循环变量 → 实际每次迭代是正确的
- 但如果selected_strategies中有重复strategy_id，_defaults可能不一致

**P2-3: _build_run_result方法过长(~700行)，可拆分为绩效计算/交易记录/图表数据3个子方法**

**P2-4: daily_profit归一化时初始值可能导致第一天daily_profit异常**
- 首日daily_profit = (current - initial_cash) / initial_cash = 0 (正确)
- 但net_value_series.insert(0, {net_value: 1.0, daily_profit: 0.0})可能导致长度不匹配

### 回测结果优化方向

**R1: MA60过滤修复后，大盘弱势期自动降低仓位 → 可能降低回撤**
**R2: 半路追涨收盘确认5%可能偏严，3%-5%区间的低开冲高股被过滤，可测试4%**
**R3: 跌停翘板止损7%偏松，测试5%止损是否减少大亏损交易**
