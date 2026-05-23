# V35 Deep Audit Report

## 基线回测结果 (2025Q1)
- 总收益: 241.14%, 年化: 22604.63%, 最大回撤: 2.47%
- 胜率: 76.77%, 夏普: 12.64, 索提诺: 61.63, 卡玛: 200.00
- 盈亏比: 3.29, 交易笔数: 99
- 龙头低吸: 31笔,96.8%,359.01% | 跌停翘板: 27笔,81.5%,336.31%
- 半路追涨: 23笔,65.2%,75.54% | 首板打板: 18笔,50.0%,7.45%

## 发现问题 (按优先级)

### P0 - 严重问题

#### P0-1: 首板打板换手率仍用T日turnover_rate(未来函数)
- 文件: portfolio_backtest.py:3470-3476
- 问题: 首板打板筛选用`turnover_rate`是T日全天换手率,实盘竞价/盘中时T日换手未知
- 其他策略(半路追涨/涨停开板/跌停翘板)已改用_prev,首板遗漏
- 修复: `turnover_rate` → `turnover_rate_prev`

#### P0-2: 首板打板circ_mv仍用T日数据(未来函数)
- 文件: portfolio_backtest.py:3477-3478
- 问题: 首板打板circ_mv用T日,实盘开盘时T日流通市值未知
- 跌停翘板已改用`circ_mv_prev`,首板遗漏
- 修复: `circ_mv` → `circ_mv_prev`

### P1 - 逻辑问题/优化

#### P1-1: 龙头低吸volume_ratio用T日但注释说保留(不一致性风险)
- 文件: portfolio_backtest.py:3531-3537
- 问题: 注释说"T日开始放量",但选股发生在开盘时,T日VR实际未知
- 回测收益因这个未来函数被虚增,实盘效果会打折
- 建议: 改用`volume_ratio_prev`,但需验证回测结果

#### P1-2: _rebalance中持仓保护可能阻止必要止损
- 文件: portfolio_backtest.py:3846-3858
- 问题: hold_protection_threshold=5%+阳线时阻止调仓卖出,但已触发止损的股票
  如果同时不在目标池,可能被保护而不止损
- 分析: 止损检查在sell_codes构建之前,止损股已被append到sell_codes
  然后hold_protection遍历sell_codes移除——但止损/冲高回落的股已在sell_codes中
  逻辑: hold_protection只移除"调仓调出"(reason=rebalance),止损/止盈/冲高回落不受影响
  **结论: 不是bug**, 因为pos_mgr.mark_sold的股不会被保护移除, 只有不在target_shares
  但没有被mark_sold的纯调仓调出股才会被保护
- 实际上: sell_codes包含3类: 1)不在target的 2)止损/冲高回落的 3)超时的
  hold_protection只影响第1类,但第2类已经通过pos_mgr处理
  **问题**: 第1类中如果有股止损价被破但不在目标池,会被hold_protection阻止吗?
  不会: 因为P0-4修复中,止损检查也发生在还在target中的股,如果止损触发会mark_sold
  但如果不在target,止损不会检查(止损只检查_sl_tp_codes = holdings - sell_codes)
  **修复**: hold_protection应排除触发止损条件的股

#### P1-3: 利润保护与盘中利润锁定可能重复触发
- 文件: portfolio_backtest.py:_check_and_execute_forced_sells
- 问题: 利润保护(close_rise>=2%, open_rise>=2%, close<open)和利润锁定(high_rise>=6%, pullback>=2.5%, close_rise>=2%)
  条件有重叠: 当high_rise>=6%且close_rise>=2%且close<open时,两者都触发
  但利润保护优先级1(pullback之后),利润锁定优先级2.5(止损止盈之后)
  实际: 利润保护先触发,利润锁定不会执行 → 无重复问题
  **结论: 不是bug**, 优先级正确

#### P1-4: 冲高回落3%-5%区间阈值可策略差异化
- 文件: sell_signal_checker.py:STRATEGY_PULLBACK_PARAMS
- 问题: 跌停翘板pullback_mid_fallback_pct=0.015,半路追涨/龙头低吸=0.01
- 建议: 龙头低吸回调幅度可能更大,0.015可能更合适(与跌停翘板一致)

#### P1-5: 超时强卖日志缺少策略信息
- 文件: portfolio_backtest.py:超时强卖
- 问题: 超时强卖reason只有"超时(N日≥M日)",不含策略名,前端统计不完整

### P2 - 改进建议

#### P2-1: _get_buy_price_for_stock每次重新创建SellSignalChecker
- 文件: sell_signal_checker.py中get_buy_price_for_strategy是全局函数
- 实际: _check_early_sell_signals中延迟初始化_sell_checker(只创建一次)
- **结论: 不是bug**, checker只创建一次

#### P2-2: _daily_price_cache未在每日循环入口清理
- 文件: portfolio_backtest.py:_run_impl循环中
- 实际: self._daily_price_cache = {} 在循环内设置,每日清理
- **结论: 正确**

#### P2-3: strategy_filter.py已标注过时但仍在项目树中
- 文件: strategy_filter.py头部注释"本模块已过时,不再维护"
- 建议: 添加DeprecationWarning或移除import

#### P2-4: 强制空仓open价卖出不扣佣金
- 文件: portfolio_backtest.py:~1486行
- 问题: 强制空仓用open价卖出,代码中slippage_pct=0,但仍扣了commission和stamp_tax
- 分析: 正确,佣金和印花税是交易所收取,必须扣;滑点是模拟成交偏差,强制空仓不扣
- **结论: 正确**

#### P2-5: 跌停翘板sentiment_period_in条件空列表时不跳过
- 文件: portfolio_backtest.py:3575
- 问题: require_high_sentiment=False时,sentiment_period_in的target=[]
  空列表operator="in"会被_print_single_strategy_filtering跳过(有特殊处理)
- **结论: 正确**, 空列表=不限制情绪周期

## 回测结果优化方向

### 方向1: 修复未来函数(P0-1/P0-2)
- 首板打板turnover_rate/circ_mv改用_prev
- 预期: 首板打板候选可能减少,但实盘一致性提升

### 方向2: 持仓保护修复(P1-2)
- 保护条件排除已触发止损的股
- 预期: 减少因保护而错过止损的情况

### 方向3: 首板打板参数微调
- 首板打板胜率50%,盈亏比1.19,收益仅7.45%
- 可能的优化: 进一步收紧成交概率或换手率
