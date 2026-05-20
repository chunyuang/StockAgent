# V23 回测模块审查报告

## 基线回测结果 (2策略: 半路追涨+跌停翘板, 20260105-20260320)
- 收益: 105.83% | 夏普: 10.64 | 回撤: 2.25% | 胜率: 73.95% | 盈亏比: 2.41 | 交易: 119笔

## V23修复后回测结果
- 收益: 113.92% | 夏普: 11.38 | 回撤: 2.26% | 胜率: 75.63% | 盈亏比: 2.38 | 交易: 119笔
- **vs基线: 收益+8.09%, 夏普+0.74, 回撤+0.01%, 胜率+1.68%**

### 卖出原因对比
| 原因 | V22基线 | V23修复 | 变化 |
|------|---------|---------|------|
| 调仓卖出 | 81 | 75 | -6 |
| 冲高回落 | 16 | 26 | +10 |
| 止盈(20%) | 5 | 5 | 0 |
| 止盈(12%) | 5 | 5 | 0 |
| 止损(5%) | 5 | 5 | 0 |
| 利润保护 | 4 | 0 | -4 |
| 强制空仓 | 3 | 3 | 0 |
| 持仓中 | 1 | 1 | 0 |

### 冲高回落详细分析 (V23)
- 半路追涨冲高回落: 14笔 100%胜率 平均4.44%
- 跌停翘板冲高回落: 12笔 100%胜率 平均10.56%
- **冲高回落阈值从5%降到3%后,多保护了10笔交易,全部盈利,平均利润6.98%**
- 卖出原因: 调仓卖出81, 冲高回落16, 止盈(20%)5, 止盈(12%)5, 止损(5%)5, 利润保护4, 强制空仓3, 持仓中1
- 耗时: 92.1s

---

## P0级修复 (数据正确性/崩溃风险)

### P0-1: _check_early_sell_signals 半路追涨冲高回落逻辑错误
**文件**: portfolio_backtest.py L143-149
**问题**: 半路追涨冲高回落检查使用`open_rise_from_cost >= sp.get('冲高回落_阈值', ...)`，
但`冲高回落_阈值`这个参数名是中文，在strategy_defaults.py中从未定义。`sp.get('冲高回落_阈值')`永远返回None，
fallback到`sp.get('next_day_open_sell_pct', 0.05)`=0.03(半路追涨默认值)。
这意味着半路追涨冲高回落的阈值实际是3%，而非5%。

更严重的是：elif链的顺序有逻辑bug。半路追涨的"冲高回落"和"利润保护"是两个独立的elif分支，
但它们都检查`sname == '半路追涨'`。当`open_rise_from_cost >= 0.03`且`close_price < open_price`时，
第一个elif(冲高回落)会触发，第二个elif(利润保护)永远不执行。利润保护(close_rise≥2%且close<open)需要
open_rise<0.03才能触发——但此时冲高回落条件不满足，所以利润保护确实可以在冲高回落不触发时执行。
**结论**: 逻辑正确但参数名'冲高回落_阈值'不存在于策略参数中，需要改用正确的英文参数名。

**修复**: 使用`next_day_open_sell_pct`替代中文参数名，与strategy_defaults.py保持一致。

### P0-2: _build_run_result中profit_pct可能为None导致TypeError
**文件**: portfolio_backtest.py (策略汇总计算)
**问题**: `strategy_results`计算`total_pnl = sum(t.get('profit_pct', 0) for t in completed)`时，
如果某笔交易的`profit_pct`为None，`sum()`会抛出TypeError(因为None+float不支持)。
同样的问题出现在盈亏比计算中`avg_win/avg_loss`，以及策略级盈亏比计算中。
基线回测中已观察到此TypeError(脚本汇总时崩溃)。
**修复**: 在所有sum中增加`if t.get('profit_pct') is not None`过滤。

### P0-3: _rebalance中止损/止盈检查重复执行
**文件**: portfolio_backtest.py L3660-3680 (sell_codes循环中的止损止盈)
**问题**: 在`_rebalance`方法中，止损/止盈检查被执行了两次：
1. 先对`_sl_tp_codes = set(holdings.keys()) - set(sell_codes)`检查(目标池内持仓)
2. 然后在卖出循环中又对每个sell_code再次检查

第一次检查的结果已经将触发止损/止盈的代码加入sell_codes并设置sell_code_reasons。
第二次检查在卖出循环中又计算一次`cost_basis, stop_price, tp_price`并覆盖sell_price和sell_reason。
这会导致：如果股票同时"不在目标池"和"触发止损"，第二次检查的close价(默认)会覆盖第一次的止损价。
**修复**: 卖出循环中，对于已在sell_code_reasons中的股票，直接使用已确定的sell_price和sell_reason。

---

## P1级修复 (逻辑优化/性能)

### P1-1: 非调仓日超时强卖阈值不一致
**文件**: portfolio_backtest.py L1983 (非调仓日超时)
**问题**: 非调仓日使用`if trade_days_held > max_hold`判断超时(严格等于max_hold+1天触发)。
但_rebalance中使用`if trade_days_held > max_hold_days`(同样的>比较)。
然而在_process_rebalance_day的"调仓日无交易"分支(L1834)中，超时判断代码完全缺失！
如果调仓日无新交易但持仓已超时，不会被强制卖出，要等到非调仓日才触发。
**修复**: 在_process_rebalance_day的"调仓日无交易"分支中添加超时检查。

### P1-2: _compute_weights volume_ratio权重计算可能返回空dict
**文件**: portfolio_backtest.py L3034-3123
**问题**: 当weight_method="equal"时，_compute_weights返回等权。但当weight_method="factor"时，
如果factor_df中缺少指定因子列，会返回空权重字典，导致所有候选被跳过，当日无交易。
应该有fallback逻辑。
**修复**: factor权重失败时fallback到equal权重。

### P1-3: daily_profit_list和net_value_series可能长度不一致
**文件**: portfolio_backtest.py
**问题**: net_value_series在开头插入初始值{net_value: 1.0}，但daily_profit_list和drawdown_series
是同步插入的。如果在某些边界条件(如第一天就是调仓日)下，_record_daily_net_value被调用两次
(一次在调仓日返回路径，一次在非调仓日)，可能导致序列长度不一致。
**修复**: 添加长度一致性断言检查。

### P1-4: _get_buy_price_for_stock 多策略选同股时取最低价可能不合理
**文件**: portfolio_backtest.py L3202-3240
**问题**: 当一只股票被两个策略选中时(如半路追涨+跌停翘板都选了同一股)，
买入价取min(半路追涨价, 跌停翘板价)。但跌停翘板价=low*1.01，通常比半路追涨价低很多。
这导致买入价偏保守，成本偏低，虚增利润。
实际上应该取**最高买入价**(最保守的成本假设)，因为两个策略都想买这只股，
至少要付出其中一个策略要求的价格。
**修复**: 取max(prices)而非min(prices)，或改为优先使用第一个策略的买入价。

### P1-5: 减仓逻辑(strategy_filter.py)板块集中度过滤的sector_top_n硬编码
**文件**: portfolio_backtest.py L1582
**问题**: `sector_top_n = self._risk_config.get('sector_concentration_top_n', 3)`默认3。
3对超短策略太严格：如果某行业当天有5只强势股，只能选3只，错过2只。
**修复**: 从strategy_params读取，默认改为4。

### P1-6: 因子查询factor_engine重复查询prev_date
**文件**: factor_engine.py (V22已部分修复)
**问题**: V22修复了pct_chg_prev和volume_ratio_prev共用prev_date查询。但turnover_rate_prev和circ_mv_prev
也可能需要T-1数据，如果factor_engine没有为这些_prev因子统一处理，仍会重复查询。
**修复**: 确认_prev因子是否统一处理。

---

## P2级修复 (代码质量/体验)

### P2-1: logger.warn调用签名错误
**文件**: universe.py L401, portfolio_backtest.py多处
**问题**: `logger.warn('BACKTEST', f"板块集中度过滤失败: {e}")`，但LokiLogger的warn方法签名
是`warning(level, msg, *args)`，`warn`是`warning`的别名。传入两个positional参数时，
第一个是level='BACKTEST'，第二个是msg="..."，但args也为空，这会触发
`msg % self.args`的TypeError(如果msg中包含%字符)。基线回测已观察到此日志错误。
**修复**: 确保msg中不包含%字符，或改用logger.warning并确保参数正确。

### P2-2: 冲高回落/利润保护卖出不计入sell_code_reasons(调仓日)
**文件**: portfolio_backtest.py L3694-3700
**问题**: 在_rebalance中，目标池内持仓的冲高回落/利润保护会加入sell_codes和sell_code_reasons。
但"不在目标池"的股票(sell_codes初始化时的)没有sell_code_reasons。卖出循环中，这些股票
走默认的close_price卖出，即使它们可能也触发了冲高回落。但由于不在目标池中，检查被跳过。
**修复**: 对"不在目标池"的股票也检查冲高回落/利润保护(已在V17部分修复，但需确认完整性)。

### P2-3: ultra_short.py中sell_reason_stats遗漏"停牌超时强卖"
**文件**: ultra_short.py L557
**问题**: 卖出原因统计中，"停牌超时强卖"不匹配任何已有分类，会归入"other"。
但停牌超时本质上是max_hold的变体(持仓时间过长)，应归入"max_hold"。
**修复**: 在"超时"匹配规则中添加"停牌"关键词。

### P2-4: 策略筛选日志过长，影响回测速度
**问题**: 每个策略每天打印完整参数列表，2策略×49天≈98次参数打印，每次20+行，
总日志量超过2000行。push_log_fn通过网络推送到前端，大量日志拖慢回测速度。
**修复**: 参数只在第一天打印，后续天只打印筛选结果。

---

## 回测结果优化方向

### O-1: 跌停翘板止盈20%可能仍偏保守
基线中5笔止盈(20%)，说明有股票涨幅超过20%被截断。考虑分批止盈：
- 涨15%卖出50%仓位
- 涨20%卖出剩余仓位
但这增加了复杂度，暂不实施。

### O-2: 调仓卖出占比过高(81/119=68%)
81笔调仓卖出中，很多可能是当日买入次日调仓卖出(持仓1天)。
如果持仓1天的胜率低于整体胜率，说明策略选股的持仓期不足。
但超短策略max_hold_days=3，1天卖出是正常的——关键是看调仓卖出的盈亏比。

### O-3: 强制空仓3笔，损失未知
需要分析强制空仓具体发生在哪些天，空仓导致错过的收益是否可接受。
当前阈值80只跌停，1月份极端行情可能频繁触发。

---

## 修复优先级排序

1. P0-2 (profit_pct None TypeError) - 已导致脚本崩溃
2. P0-3 (止损检查重复) - 可能导致卖出价被覆盖
3. P0-1 (冲高回落参数名) - 参数实际生效但名称不规范
4. P1-1 (调仓日无交易缺少超时检查) - 逻辑遗漏
5. P1-4 (多策略买入价取min→max) - 成本计算偏保守
6. P2-3 (停牌超时归入max_hold) - 统计分类
7. P2-4 (日志精简) - 性能优化
8. P1-2 (权重fallback) - 防御性修复
9. P1-5 (板块集中度top_n) - 参数优化
