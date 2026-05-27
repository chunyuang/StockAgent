# V76 回测模块深度审查报告

## 审查范围
- portfolio_backtest.py (4840行) - 逐行审查完成
- sell_signal_checker.py (875行) - 逐行审查完成
- factor_engine.py (745行) - 逐行审查完成
- factor_library.py (797行) - 审查完成
- strategy_defaults.py (216行) - 审查完成
- factor_quality_checker.py (247行) - 审查完成
- ultra_short.py (648行) - 审查完成
- node.py (587行) - 审查完成
- models.py (127行) - 审查完成

## 基线（V76=V74, 2年 20240506-20260511）
| 指标 | 值 |
|------|-----|
| 总收益 | 1005576.37% |
| 最大回撤 | 9.65% |
| 夏普比率 | 11.29 |
| 索提诺 | 17.47 |
| 胜率 | 72.7% |
| 交易笔数 | 871 |
| 最大连续亏损笔数 | 8 |
| 最大单日亏损% | 8.25% |
| 单笔最大亏损% | -13.33% |

策略分解:
- 半路追涨: 加权收益368.98% 胜率73.6% 笔386 回撤19.23%
- 首板打板: 加权收益7.33% 胜率44.9% 笔98 回撤46.74%
- 跌停翘板: 加权收益762.05% 胜率77.7% 笔264 回撤18.32%
- 龙头低吸: 加权收益848.83% 胜率81.3% 笔123 回撤17.77%

卖出原因(共871笔):
- profit_lock: 203(23.3%)
- pullback: 194(22.3%)
- rebalance: 176(20.2%)
- stop_loss: 110(12.6%)
- take_profit: 95(10.9%)
- force_empty: 32(3.7%)
- gap_stop_loss: 26(3.0%)
- profit_protect: 19(2.2%)
- max_hold: 16(1.8%)

---

## 发现的问题

### P0级（影响回测正确性）

#### P0-1: daily_profit归一化重复计算
- **文件**: portfolio_backtest.py L3008 + L3087
- **问题**: `_build_run_result`中对`daily_profit`做了两次归一化(`÷_initial_cash`)
  - L3008: result["positions"]["daily_profit"] 归一化一次
  - L3087: result["daily_profit"] 顶层字段又归一化一次
  - 两次使用相同的列表推导，浪费计算且代码冗余
- **影响**: 无数据错误，但浪费O(N)计算，且维护时需同步两处
- **修复**: 提取为局部变量`_dp_normalized`，两处引用同一结果

#### P0-2: 首板打板hit_probability_normal fallback=0.40与strategy_defaults的0.45不一致
- **文件**: portfolio_backtest.py L4098
- **问题**: `_apply_limit_up_hit_probability`中`hit_probability_normal`的fallback链:
  `sp.get(...) → _first_limit_defaults.get(..., 0.40)`
  但STRATEGY_CONFIGS中`hit_probability_normal=0.45`
- **原因**: fallback值0.40是V72之前的旧值，V72将strategy_defaults提升到0.45，
  但fallback值未同步更新
- **影响**: 当_strategy_params和STRATEGY_CONFIGS均无此参数时(极罕见)，fallback为0.40而非0.45
- **修复**: 将fallback改为0.45，与strategy_defaults一致

#### P0-3: sell_signal_checker.check_full_sell在止损止盈检查中存在逻辑bug
- **文件**: sell_signal_checker.py L641-660
- **问题**: `check_full_sell`方法中止损止盈只检查第一个策略就break:
  ```python
  for strategy_name in strategies:
      ...
      break  # 止损止盈参数已用min/max取最严格,只需检查一次
  ```
  但注释说"已用min/max取最严格"，实际上**并没有取min/max**！
  每个策略的params是独立的，check_stop_loss用的是当前strategy的stop_loss_pct，
  不同策略的stop_loss_pct不同(半路3%，跌停5%)，只检查第一个策略可能漏掉更严格的止损
- **影响**: 此方法标记为DEPRECATED（V33 review: never called），不影响当前回测
- **修复**: 标注为DEPRECATED，未来如启用需修复

### P1级（影响代码质量/可维护性/体验）

#### P1-1: _print_single_strategy_filtering中参数fallback逻辑冗长重复
- **文件**: portfolio_backtest.py L623-820（~200行）
- **问题**: 5个策略各有独立的参数读取+fallback代码，每个策略~40行重复模式:
  ```python
  min_xxx = params.get("xxx") if params.get("xxx") is not None else STRATEGY_CONFIGS.get("yyy", {}).get("params", {}).get("xxx", default)
  ```
- **影响**: 维护成本高，新增策略需复制~40行模板；已存在_param_or_default方法但未使用
- **修复**: 使用_param_or_default统一参数读取，每个策略减少到~10行

#### P1-2: _rebalance方法仍然过长（~450行）
- **文件**: portfolio_backtest.py L3990-4640
- **问题**: 虽然V75提取了_check_sell_signal_for_holdings，但_rebalance仍然包含:
  - 持仓保护逻辑(50行)
  - 超时强卖逻辑(30行)
  - 停牌超时逻辑(20行)
  - 卖出执行循环(100行)
  - 买入执行循环(100行)
  - 减仓循环(40行)
- **影响**: 代码可读性差，调试困难
- **修复建议**: 提取_execute_sell_cycle, _execute_buy_cycle, _check_hold_protection子方法

#### P1-3: _process_non_rebalance_day中强制空仓T+1遗留处理不完整
- **文件**: portfolio_backtest.py _process_non_rebalance_day
- **问题**: 非调仓日传入force_empty_triggered参数后，如果触发强制空仓，
  清仓逻辑直接遍历holdings卖出，但T+1跳过的股票只记录到_pending_force_sell
  没有在**当天非调仓日的止损检查**中优先清仓
- **影响**: 极端行情下，非调仓日T+1遗留股可能在次日才被清仓，增加1天持仓风险
- **修复**: _check_and_execute_forced_sells中已有_pending_force_sell处理，确认非调仓日也走此路径

#### P1-4: factor_engine.py中回测模式的pre_close=0修复可能影响intraday因子计算
- **文件**: factor_engine.py L187-230
- **问题**: pre_close=0修复先查prev_date的close，然后才计算intraday_max_rise_pct。
  但如果pre_close修复发生在daily_basic合并之后，而daily_basic也包含pre_close字段，
  可能覆盖修复后的值
- **影响**: 极罕见（daily_basic很少包含pre_close），但潜在数据覆盖风险
- **修复**: 在daily_basic合并时排除pre_close字段

#### P1-5: strategy_defaults.py缺少trailing_stop_pct的回测实现
- **文件**: strategy_defaults.py（所有策略都定义了trailing_stop_pct参数）
- **问题**: STRATEGY_CONFIGS中每个策略都定义了trailing_stop_pct参数，但回测引擎
  从未使用此参数进行追踪止损。参数定义存在但无效，造成误导。
  - 半路追涨: trailing_stop_pct=0.02（盈利≥2%后激活）
  - 首板打板: trailing_stop_pct=0.02
  - 龙头低吸: trailing_stop_pct=0.03
  - 跌停翘板: trailing_stop_pct=0.04
- **影响**: 追踪止损是重要的利润保护机制，缺失可能导致利润大量回吐
- **修复方案**: 在_check_and_execute_forced_sells中实现追踪止损逻辑

### P2级（体验/优化/文档）

#### P2-1: 回测日志输出量过大
- **问题**: 2年回测日志约50万行，大量INFO级别日志淹没了关键信息
- **修复**: 策略筛选日志降级为DEBUG，仅保留调仓/卖出/买入为INFO

#### P2-2: 策略分解中首板打板胜率仅44.9%，显著拖累组合
- **问题**: 首板打板98笔交易胜率44.9%（组合平均72.7%），回撤46.74%（组合9.65%）
  加权收益仅7.33%（远低于其他策略的369%/762%/849%）
- **分析**: 首板打板本质是高波动策略，但当前参数可能过于宽松:
  - hit_probability_slow=0.55导致大量低质量盘中板成交
  - 止损3.5%对于打板策略可能偏紧（开盘即可能低开3.5%+）
- **建议**: 考虑收紧成交概率或增加封板质量筛选条件

#### P2-3: 净值曲线中缺少日级策略贡献分解
- **问题**: 当前strategy_results只有汇总级统计，无法看到每日各策略的盈亏贡献
- **修复**: 在net_value_series中增加strategy_daily_pnl字段

#### P2-4: _compute_weights中strat_groups排序使用score+code双重key，但code方向不一致
- **文件**: portfolio_backtest.py L3564
- **问题**: `group.sort(key=lambda x: (x[1], x[0]), reverse=True)` 
  reverse=True使score降序但code也降序，同一score时code倒序排列
- **影响**: 微小差异，对回测结果影响<0.1%，但违反确定性排序意图
- **修复**: 改为`sorted(group, key=lambda x: (-x[1], x[0]))`确保score降序+code升序

#### P2-5: factor_quality_checker.py中check方法缺少对NaN比例的检查
- **文件**: factor_quality_checker.py
- **问题**: 当前只检查因子是否存在、全0比例，但未检查NaN比例。
  如果某因子50%的值为NaN，筛选条件会跳过这些股票，相当于50%的股票无法参与选股
- **修复**: 增加NaN比例检查，超过30%时发出warning

---

## 优化方向分析

### 1. 追踪止损实现（P1-5）— 预期收益提升最大
当前利润锁定和冲高回落已经提供一定保护，但缺少"盈利后从最高点回撤"的追踪止损。
实现追踪止损可能:
- 减少利润回吐（当前profit_lock占23.3%但可能退出过晚）
- 减少max_hold/超时退出比例（当前1.8%，如果有追踪止损可更早退出盈利股）

⚠️ 注意: 追踪止损与现有利润锁定机制有重叠，需仔细设计避免冲突

### 2. 首板打板优化（P2-2）— 降低回撤
首板打板胜率44.9%是最大拖累，但完全去掉会减少98笔交易。
建议:
- 紧缩hit_probability: slow 0.55→0.45（减少低质量成交）
- 提高首板筛选条件: 增加封板质量指标

### 3. 代码瘦身（P1-1/P1-2）— 不影响回测结果
- _print_single_strategy_filtering: 200行→80行
- _rebalance: 提取3个子方法，主方法从450行降至~150行

---

*审查时间: 2026-05-28*
*审查人: AI Agent (V76深度审查)*
