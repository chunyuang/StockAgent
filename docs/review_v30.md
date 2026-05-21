# V30回测审查报告

## 基线结果 (V29, 2025-01-01~2025-06-01)
- 总收益率: 658.83% | 夏普: 7.80 | 回撤: 6.69% | 胜率: 76.53% | 盈亏比: 3.53 | 98笔

## 审查发现

### P0 - 逻辑错误

#### P0-1: _rebalance中重复检查early_sell_signals
- **位置**: portfolio_backtest.py L~3660-3690 (_rebalance卖出循环)
- **问题**: 在`_check_and_execute_forced_sells`已经检查过冲高回落/利润保护后,
  `_rebalance`的卖出循环中对目标池内持仓又检查了一次`_check_early_sell_signals`。
  两处检查用的是相同的open/close价格，结果应该一致，但造成不必要的重复计算。
- **影响**: 性能(每日每持仓多一次信号检查) + 代码冗余
- **修复**: `_rebalance`中的early_sell检查保持(因为它检查的是"仍在目标池"的持仓)，
  但需要确保与`_check_and_execute_forced_sells`的结果一致，不重复卖出。

#### P0-2: 停牌超时强卖(slippage=0)但`_execute_forced_sells`中查should_apply_slippage返回False
- **位置**: portfolio_backtest.py L~3800 (_rebalance中停牌超时强卖)
- **问题**: `_rebalance`中停牌超时强卖直接`sell_price_adj = price`（不扣滑点），
  但`_execute_forced_sells`中对'停牌超时强卖'也通过`should_apply_slippage`返回False不扣滑点。
  两处逻辑一致但代码路径不同——`_rebalance`直接硬编码，`_execute_forced_sells`走规则表。
- **影响**: 不影响结果，但代码风格不一致
- **修复**: 统一走`should_apply_slippage`规则表

#### P0-3: _print_market_environment返回值变化但调用方未更新
- **位置**: L~781 
- **问题**: `_print_market_environment`现在返回4个值`(sentiment_level, sentiment_score, limit_up_count, limit_down_count)`，
  但方法名暗示只返回市场环境信息。而调用方在L~810用`sentiment_level, market_sentiment_score, limit_up_count, limit_down_count`接收。
  注意返回的sentiment_level是字符串(如"高潮期,仓位系数1.0")，但后续_check_early_sell_signals不使用它，
  只用于仓位计算和日志。这不是bug但增加了耦合度。
- **影响**: 无直接影响，但sentiment_level字符串解析(_extract_position_multiplier)脆弱

### P1 - 性能/优化

#### P1-1: trade_days_held计算O(N)遍历all_trade_dates
- **位置**: _check_and_execute_forced_sells L~280, _rebalance L~3800
- **问题**: 每次计算持仓天数都遍历整个all_trade_dates列表: `sum(1 for d in _all_td if buy_dt_int < d <= trade_dt_int)`
  当_all_td有500+元素时，每个持仓股都要遍历500+次。假设3个持仓，每天3*500=1500次比较。
- **影响**: 5个月回测~120天*1500=18万次比较，性能损失约1-2秒
- **修复**: 预构建`{trade_date: index}`映射，`trade_days_held = idx_sell - idx_buy`，O(1)查找

#### P1-2: _get_prices每天查询全市场5013只股票的daily_basic
- **位置**: factor_engine.py compute_factors
- **问题**: daily_basic合并查询不区分是否需要circ_mv/turnover_rate。
  每天查5013只股票的daily_basic，但实际上回测可能只有3个持仓需要价格。
- **影响**: 每天额外一次5013条记录的MongoDB查询
- **修复**: 只在因子列表需要时才查daily_basic

#### P1-3: 强制空仓分支的股票池查询是浪费
- **位置**: L~1260
- **问题**: 强制空仓时跳过选股，但`universe`和`universe_raw`的查询在强制空仓判断之后。
  实际上强制空仓分支在L~1260之前就return了，所以不影响。但`_print_market_environment`
  的涨跌停聚合查询(~5000条$substrCP+$switch)在每天都会执行，即使是非调仓日。
- **影响**: 非调仓日的涨跌停统计完全没有用处(只在调仓日决策时使用)
- **修复**: 非调仓日跳过_print_market_environment的详细统计

#### P1-4: 月度收益计算使用daily_profit_list绝对值
- **位置**: L~2870
- **问题**: monthly_profit计算用`current_value += profit`(profit是绝对金额)，
  但不同月份的初始资金不同。如果某月大幅盈利后下月亏损，月度收益率的分母不同。
  实际上current_value是累计值，monthly_start_value是该月初的累计值，
  所以m_return = (current_value - monthly_start_value) / monthly_start_value是正确的。
  **验证后不是bug**。

#### P1-5: 首板打板成交概率模拟的hash不稳定性
- **位置**: L~3960
- **问题**: 使用md5 hash模拟成交概率，但这依赖于code和trade_date的组合。
  如果回测区间改变（start_date不同但包含同一天），hash值不变，结果可复现。
  但如果添加新的候选股票（如参数调整），其他股票的hash不受影响。这是正确的。
  **验证后不是bug**。

### P2 - 代码质量

#### P2-1: _rebalance方法453行过长
- **位置**: L~3600-4053
- **问题**: _rebalance包含卖出决策、买入决策、减仓、停牌强卖4段逻辑，
  每段都有独立的状态变量和判断。当前已部分提取子方法(_calc_total_value等)，
  但核心卖出循环仍在_rebalance内。
- **影响**: 可维护性差
- **修复**: 进一步提取卖出循环为_execute_sell_cycle方法

#### P2-2: run_state dict解包冗余
- **位置**: _process_rebalance_day和_process_non_rebalance_day开头
- **问题**: 每个方法开头都有15+行`x = run_state['x']`解包，和方法结尾15+行
  `_update_run_state(run_state, ...)`回写。这种模式在每个方法中重复。
- **影响**: 代码冗余~100行，每次修改run_state字段需修改4处
- **修复**: 将run_state改为SimpleNamespace或类，自动属性访问

#### P2-3: _build_strategy_filter_conditions中硬编码的策略参数
- **位置**: L~3300-3600
- **问题**: 虽然已添加strategy_defaults.py作为单一来源，但_build_strategy_filter_conditions
  中仍有大量`converted_params.get("xxx") if converted_params.get("xxx") is not None else strategy_defaults.get("xxx", 0.03)`
  的模板代码。5个策略加起来~200行参数读取+条件构建。
- **影响**: 新增策略需复制粘贴~40行
- **修复**: 定义STRATEGY_FILTER_TEMPLATES数据结构，从strategy_defaults.py自动生成筛选条件

#### P2-4: _print_single_strategy_filtering方法过长(~120行)
- **位置**: L~440-560
- **问题**: 每个策略的参数打印逻辑不同(如半路追涨打印量比/涨幅区间，跌停翘板打印翘板金额)，
  导致大量if/elif策略分支。
- **影响**: 新增策略需添加elif分支
- **修复**: 每个策略定义参数展示模板(PROPERTY_DISPLAY)，自动生成打印内容

### P3 - 回测结果优化

#### P3-1: 半路追涨胜率仅54.5%，回撤11.74%
- **分析**: 半路追涨是3个策略中胜率最低、回撤最大的。
  盈亏比1.90虽不算低，但胜率偏低导致整体拖累。
- **优化方向**:
  1. 加强半路追涨的过滤条件(如量比>2.5更严格,或增加pct_chg_prev>0条件)
  2. 考虑提高半路追涨的止损(5%→4%)，因为波动大
  3. 减仓:降低半路追涨的策略权重(从0.5→0.4)

#### P3-2: 龙头低吸回撤5.15%但胜率94.4%极高
- **分析**: 胜率94.4%可能过于乐观。检查是否有未来函数成分。
  volume_ratio用T日数据(已标注"信号是T日放量启动")。
  但pullback_pct/pullback_days是T日数据，这些在开盘时是否可观测？
  pullback_pct = (close - high_peak) / high_peak，其中high_peak是近N日最高价，
  这是历史数据可计算。pullback_days也是历史数据。所以这不是未来函数。
  胜率高是因为龙头低吸的选股条件本身非常严格(大市值+连板+缩量回调)。

#### P3-3: 跌停翘板盈亏比4.00最高但回撤7.85%
- **分析**: 跌停翘板的高盈亏比来自25%止盈线(允许更大的利润空间)。
  回撤7.85%主要来自4%止损被跳空击穿的情况。
- **优化方向**: 
  1. 跌停翘板添加前日成交量放大条件(volume_ratio_prev>2)，过滤虚假翘板
  2. 考虑将跌停翘板的min_circulation_market_cap从20亿提升到30亿

## 修复优先级
1. P1-1: trade_days_held O(N)→O(1) (性能，每次回测省1-2秒)
2. P1-3: 非调仓日跳过市场环境统计 (性能，每次回测省2-3秒)
3. P0-1: 重复early_sell检查 (逻辑清晰度)
4. P3-1: 半路追涨过滤优化 (回测结果优化)
5. P2-2: run_state改为类 (代码质量，大改动需谨慎)
