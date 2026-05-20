# V22回测模块审查报告

## 基线回测结果 (2策略: 半路追涨+跌停翘板, 20260105-20260320)
- 收益: 92.11%
- 夏普: 9.41
- 回撤: 3.48%
- 胜率: 73.11%
- 盈亏比: 2.17
- 交易: 119笔
- 信号: 120个
- 执行时间: 92.5s
- 卖出统计: 止损10/止盈38/强制空仓3/调仓68

## V22修复后结果 (全局SL5%/TP10%)
- 收益: 92.20% (+0.09%)
- 夏普: 9.42 (+0.01)
- 回撤: 3.48% (不变)
- 胜率: 73.11% (不变)
- 盈亏比: 2.17 (不变)
- 交易: 119笔 (不变)

## V22策略默认值模式 (SL5%/TP12% + SL7%/TP20%)
- 收益: 105.83% (+13.72% vs 基线)
- 夏普: 10.64 (+1.23)
- 回撤: 2.25% (-1.23%)
- 胜率: 73.95% (+0.84%)
- 盈亏比: 2.41 (+0.24)
- 交易: 119笔
- 卖出统计: 止损5/止盈30/强制空仓3/调仓81

## 审查发现

### P0级 (逻辑错误)

**P0-1: 强制空仓卖出扣了滑点(不应扣)**
- 位置: portfolio_backtest.py L1191
- 问题: 强制空仓卖出使用 `slippage_pct = self._slippage_pct` (0.2%)
- 分析: 强制空仓是在极端行情下清仓，市场冲击已经通过开盘价反映(用open卖出)，再扣滑点等于双重惩罚
- 与止损对比: 止损不扣滑点(止损价已保守)，强制空仓同样用open卖出(已是最差情况)
- 影响: 3笔强制空仓交易各多扣0.2%滑点

**P0-2: MA60缓存只缓存了ma60值，没缓存current_close**
- 位置: portfolio_backtest.py L1650-1668
- 问题: 缓存命中时ma60已知但current_close=None，需要额外查一次MongoDB
- 影响: 49个交易日中19天跌破MA60+其余30天也查一次 = 每次缓存命中多1次find_one查询
- 修复: 缓存{trade_date: (ma60, current_close)}元组

**P0-3: 非调仓日超时强卖未从target_shares移除(但非调仓日无调仓，不影响)**
- 分析: 非调仓日不执行_rebalance，超时强卖后不会重新买入
- 结论: 非问题，逻辑正确

### P1级 (性能/优化)

**P1-1: _print_market_environment的聚合查询用$regexMatch性能差**
- 位置: portfolio_backtest.py L270-292
- 问题: $regexMatch对5万条记录做正则匹配，CPU密集且无法利用索引
- 优化: 改用$substrCP提取代码前缀 + $switch分类，性能提升3-5x

**P1-2: 因子完整性检测的采样查询可能返回过少样本**
- 位置: portfolio_backtest.py L1012
- 问题: $limit 100可能在特定trade_date返回0条(如果先匹配到的日期不包含因子)
- 优化: 增加$sort确保按trade_date降序取最新数据

**P1-3: 强制空仓时仍然调用_get_prices查所有持仓价格**
- 位置: portfolio_backtest.py L1178
- 问题: 即使只有1只持仓，也查所有holdings的价格
- 实际: 这是必要的(需要价格才能卖出)，不影响性能

**P1-4: _rebalance中减仓检查止损止盈后升级为全卖，但未从target_shares删除**
- 位置: portfolio_backtest.py L3794-3800
- 问题: codes_to_promote将减仓股升级为全卖，但只从reduce_codes删除
- 分析: 全卖后holdings[code]=0，target_shares[code]存在但delta=target-current=0-0=0，不会重新买入
- 结论: 不影响结果(delta<=0时continue)，但代码语义不清晰

### P2级 (代码质量/体验优化)

**P2-1: _rebalance卖出循环中sell_code_reasons未用于sell记录的reason字段**
- 位置: portfolio_backtest.py L3903
- 问题: 在_rebalance的卖出循环中，对于目标池内止损/止盈卖出的股票，sell_reason逻辑重复计算
- 分析: 前面已将reason存入sell_code_reasons[code]，但卖出循环又重新计算cost_basis和止损/止盈判断
- 影响: 不影响结果(两次判断结果一致)，但代码冗余

**P2-2: 停牌超时强卖阈值硬编码为10天**
- 位置: portfolio_backtest.py L3812-3824
- 问题: 10天停牌超时硬编码，不同策略的max_hold_days不同(3/4天)
- 修复: 使用策略级max_hold_days * 3(留出足够缓冲)作为停牌超时阈值

**P2-3: _get_prices的matched_key匹配逻辑过于复杂**
- 位置: portfolio_backtest.py L2972-3010
- 问题: 三层嵌套的匹配逻辑(精确→去后缀→反向匹配)
- 修复: 统一用_standardize_ts_code预标准化，只做一次精确匹配

**P2-4: 每日日志输出过多，92s回测产生上千条日志**
- 问题: _print_market_environment + _print_single_strategy_filtering + 调仓记录 + 每日汇总 = 每天30+条
- 优化: 将策略筛选过程日志降为debug级别(保留汇总)

**P2-5: _check_early_sell_signals中跌停翘板开盘卖出阈值硬编码**
- 位置: portfolio_backtest.py L157-160
- 问题: 半路追涨的open_sell_pct从params读取，但>=5%的硬编码阈值不在params中
- 修复: 从strategy_defaults或params读取

### P3级 (策略结果优化)

**P3-1: 半路追涨pct_chg>=5%未来函数修复方案**
- V18已标注但未修复: pct_chg是收盘数据(盘中不可知)
- 当前状态: 已知未来函数，去掉后策略完全失效(92%→-13%)
- 待架构支持: T日收盘确认+T+1买入 或 收盘价买入

**P3-2: 跌停翘板止盈20%是否仍有优化空间**
- V21从15%→20%已验证有效(收益+6.4%)
- 可测试25%止盈(翘板股极端行情下利润可达28%+)

## 修复优先级
1. P0-1: 强制空仓不扣滑点 (1行改动)
2. P0-2: MA60缓存优化 (5行改动)
3. P1-1: 聚合查询优化 (20行改动)
4. P2-2: 停牌超时阈值 (3行改动)
5. P2-5: 硬编码阈值提取 (3行改动)
