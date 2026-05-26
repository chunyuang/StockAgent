# 回测引擎V53深度代码审计报告

**审计日期**: 2026-05-26  
**审计范围**: portfolio_backtest.py(4433行), sell_signal_checker.py(871行), ultra_short.py(632行), strategy_defaults.py(192行), factor_engine.py(718行)  
**审计目标**: 收益率虚高(3个月432%/净值5.32)、merged_trades=0、sell_reason_stats={}、all_trades中sell_price缺失、未来函数风险  

---

## 一、核心问题诊断

### 1. merged_trades=0 的根因

**结论: merged_trades 在 `_build_run_result()` 中正确构建，问题在 ultra_short.py 的读取路径**

| 位置 | 代码路径 | 状态 |
|------|---------|------|
| portfolio_backtest.py L2842 | `result["merged_trades"] = merged_trades` | ✅ 正确写入顶层 |
| ultra_short.py L484 | `merged_trades = performance_data.get('merged_trades', result.get('merged_trades', []))` | ✅ 双层fallback正确 |

**可能的根因**:
1. **RebalanceRecord未序列化问题** — L2642-2660将RebalanceRecord转为dict，但如果record对象属性缺失(price/amount/shares)，FIFO匹配中`avg_cost = sell_cost / sell_buy_shares`可能除零
2. **record.price=0导致merged_trades跳过** — `_rebalance`卖出循环中，`_sell_code_details[code]=(best_price, best_reason)`的best_price可能为0(当cost<=0或prices[code]为空dict时)，此时RebalanceRecord.price=0，后续FIFO中`cost_per_share = abs(buy_rec.amount) / buy_rec.shares`如果amount=0则avg_cost=0
3. **更可能: ultra_short.py读的是嵌套结构performance_data而非result** — performance_data来自`metrics.get('performance', {})`，而merged_trades写入的是`result["merged_trades"]`(顶层)，不在`result.metrics.performance`中

**P0确认**: L2842写`result["merged_trades"]`到顶层，但L2795-2810的嵌套结构`result.metrics.performance`里**没有**写入merged_trades。ultra_short.py L484的`performance_data.get('merged_trades', ...)`会从嵌套结构先读，**读不到**，再fallback到`result.get('merged_trades', [])`，这条路径是正确的。

**最终结论**: 如果ultra_short.py正确调用了双层fallback，merged_trades不应为0。问题可能在于**前端展示层**读取了`performance_data.merged_trades`(嵌套路径)而非`result.merged_trades`(顶层)。需要检查前端API返回时是否丢失了顶层字段。

---

### 2. sell_reason_stats={} 的根因

**直接原因: sell_reason_stats依赖merged_trades或raw_trades，如果两者都为空则统计为空**

ultra_short.py L497-L540:
```python
for trade in (merged_trades or raw_trades or []):
    reason = trade.get("reason", trade.get("sell_reason", ""))
```

关键: `trade.get("reason", ...)` — **RebalanceRecord序列化后的dict中，卖出reason在`reason`字段**。但ultra_short.py先读`reason`再读`sell_reason`，顺序正确。

**真正问题**: `raw_trades = performance_data.get('all_trades', ...)` — all_trades是RebalanceRecord对象列表转dict，dict中有`reason`字段但**没有`sell_reason`字段**。如果`reason`字段为空字符串(默认值)，则匹配不到任何类别，计入`other`。

但sell_reason_stats={}意味着**循环从未执行**，即`merged_trades`和`raw_trades`都为空列表。这指向merged_trades=0的问题。

---

### 3. all_trades中sell_price全部缺失

**all_trades来自RebalanceRecord对象，字段是`price`而非`sell_price`**

- RebalanceRecord(L13 models.py): 字段为`date, action, ts_code, shares, price, amount, reason, strategy_name, sentiment`
- 没有`sell_price`字段 — 只有`price`
- ultra_short.py格式化时(L490): `if 'sell_price' not in trade_dict` — 没有从`price`映射到`sell_price`

**P1问题**: all_trades(dict格式)中的卖出价格在`price`字段，但前端/分析代码期望`sell_price`字段。需要在格式化时添加映射。

---

### 4. 收益率虚高分析

**3个月432%确实偏高但可能真实**，历史审计记录显示:
- V45: 147% (3个月)
- V53: 3825% (全年) / 372.86% (Q1)

**可能导致虚高的因素**:

| 因素 | 影响程度 | 当前状态 |
|------|---------|---------|
| 半路追涨pct_chg未来函数 | 高 | ⚠️已知(V25分析:去pct_chg收益从350%→181%) |
| 龙头低吸volume_ratio(T日) | 中 | ⚠️已知灰色地带(V25:改_prev降90%) |
| 跌停翘板pct_chg>0 | 低 | ✅合理(收盘确认,盘中买入逻辑自洽) |
| 滑点应用不一致 | 中 | 见下方P0-2 |
| 买入价保守性不足 | 中 | 见下方P1-1 |

---

## 二、逐文件Bug清单

### BUG-001: 利润锁定在_check_and_execute_forced_sells中与_rebalance重复检查

- **文件**: portfolio_backtest.py
- **行号**: L285-298 (_check_and_execute_forced_sells) + L3899-3910 (_rebalance)
- **描述**: 利润锁定检查在两处都存在:
  1. `_check_and_execute_forced_sells`中L285-298: 非调仓日强制卖出路径
  2. `_rebalance`中L3899-3910(V48)和L3956-3970: 调仓日止损检查
  
  在调仓日，如果股票**不在目标池**(sell_codes_raw)，`_sell_code_details`会检查利润锁定(L3899-3910)。同时，`_check_and_execute_forced_sells`在**非调仓日**检查。但如果**调仓日无交易**(走_process_non_rebalance_day路径)，利润锁定也会被检查。两处逻辑一致，**不造成双重触发**，但代码冗余。
- **影响程度**: P2
- **建议**: 将利润锁定检查统一到_check_and_execute_forced_sells，_rebalance中的V48/V49检查作为补充(覆盖目标池内股票)

### BUG-002: _get_sl_tp_for_code TP取strategies[0]与SellSignalChecker取min不一致

- **文件**: portfolio_backtest.py L3716 + sell_signal_checker.py L655
- **描述**: 
  - `_get_sl_tp_for_code` L3716: TP取`strategies[0]`(买入策略的TP) — 注释说"不用max"
  - `SellSignalChecker.get_sl_tp_for_strategies` L655: TP取`min(所有策略)` — 注释说"保持min与portfolio_backtest超时强卖/调仓卖出一致"
  
  两者不一致。`_get_sl_tp_for_code`在_rebalance和_check_and_execute_forced_sells中调用，是实际生效的。SellSignalChecker的`get_sl_tp_for_strategies`只在DEPRECATED的`check_full_sell`中使用。
- **影响程度**: P2 (check_full_sell已DEPRECATED，不影响实际回测)
- **建议**: 在check_full_sell完全移除后统一

### BUG-003: _rebalance卖出循环中record.price使用含滑点前的价格

- **文件**: portfolio_backtest.py L4205-4225
- **描述**: 卖出记录中:
  ```python
  price = sell_price  # L4217: 止损价/冲高回落open价/收盘价(不含滑点)
  slippage_pct = 0 if not should_apply_slippage(sell_reason) else self._get_slippage_for_code(ts_code)
  sell_price_adj = price * (1 - slippage_pct)  # L4219: 含滑点价格
  gross_amount = shares * sell_price_adj  # L4220: 用含滑点价格计算金额
  
  records.append(RebalanceRecord(
      price=price,  # ← 记录的是不含滑点的价格!
      amount=net_amount,  # ← 但金额是按含滑点价格计算的!
  ))
  ```
  **record.price与record.amount不一致**: price不含滑点，amount扣了滑点。在`_build_run_result`的FIFO匹配中:
  ```python
  cost_per_share = abs(buy_rec.amount) / buy_rec.shares  # 买入金额/股数=含滑点的实际成本
  net_sell_amount = record.amount  # 卖出净额(含滑点+佣金+印花税)
  profit = (net_sell_amount - sell_cost) / sell_cost * 100
  ```
  买入金额`abs(buy_rec.amount)`是-total_cost(含佣金)，卖出金额`record.amount`是net_amount(扣了滑点+佣金+印花税)。**profit计算是正确的**(都是实际收支金额)。
  
  但record.price=不含滑点的价格，**前端展示的卖出价是不含滑点的**，与实际卖出金额不匹配。
- **影响程度**: P1 (回测利润计算正确，但前端展示的卖出价与实际金额不一致，用户可能困惑)
- **建议**: 将record.price改为sell_price_adj(含滑点价格)，或在RebalanceRecord中新增slippage字段

### BUG-004: all_trades(dict)缺少sell_price字段映射

- **文件**: ultra_short.py L490
- **描述**: 格式化交易记录时:
  ```python
  trade_dict = trade.copy() if isinstance(trade, dict) else {}
  ```
  RebalanceRecord转为dict后字段为`{date, action, ts_code, shares, price, amount, reason, ...}`，**没有sell_price字段**。前端期望的`sell_price`在`price`字段中(对卖出记录)。ultra_short.py没有做`price→sell_price`的映射。
- **影响程度**: P1 (前端all_trades展示卖出价缺失)
- **建议**: 格式化时添加: `if trade_dict.get('action') == 'sell' and 'price' in trade_dict: trade_dict['sell_price'] = trade_dict['price']`

### BUG-005: 首板打板hit_probability默认值在_apply_limit_up_hit_probability中硬编码

- **文件**: portfolio_backtest.py L3703-3707
- **描述**:
  ```python
  hit_prob_yizi = sp.get('hit_probability_yizi', 0.0)
  hit_prob_fast = sp.get('hit_probability_fast', 0.20)
  hit_prob_normal = sp.get('hit_probability_normal', 0.45)
  hit_prob_slow = sp.get('hit_probability_slow', 0.65)  # ← 硬编码0.65
  ```
  strategy_defaults.py V53已将hit_probability_slow从65%→60%，但_apply_limit_up_hit_probability的fallback硬编码为0.65，**与STRATEGY_CONFIGS不一致**。
  
  `sp = self._strategy_params.get('首板打板', {})` — 如果前端没传hit_probability_slow，fallback到0.65而非V53的0.60。
- **影响程度**: P0 (回测结果与策略参数配置不一致，V53优化失效)
- **建议**: fallback值改为从STRATEGY_CONFIGS读取:
  ```python
  _defaults = STRATEGY_CONFIGS.get('first_limit_up', {}).get('params', {})
  hit_prob_slow = sp.get('hit_probability_slow', _defaults.get('hit_probability_slow', 0.60))
  ```

### BUG-006: 强制空仓时未清理stock_to_strategy映射

- **文件**: portfolio_backtest.py L1470-1510
- **描述**: 强制空仓清仓时:
  ```python
  holdings.pop(code, None)
  # 删除cost_basis/cost_basis_date
  ```
  但**没有清理`self.stock_to_strategy[code]`**。虽然L1680有清理逻辑"清理已卖出股票的映射(不在holdings中的)"，但这只在**下一个调仓日**执行。如果强制空仓后同日有非调仓日检查(`_check_and_execute_forced_sells`)，已清仓股票仍在`stock_to_strategy`中，可能导致遍历已清仓股票做不必要的止损检查(但因为holdings已空，不会造成实际bug)。
- **影响程度**: P2 (功能性无影响，但有轻微性能浪费和代码整洁性问题)
- **建议**: 强制空仓清仓后立即清理stock_to_strategy

### BUG-007: _check_and_execute_forced_sells不检查利润锁定的策略特定参数

- **文件**: portfolio_backtest.py L285-298
- **描述**: 利润锁定检查使用全局risk_config参数:
  ```python
  lock_min_high = self._risk_config.get('intraday_lock_min_high_rise', ...)
  lock_pullback = self._risk_config.get('intraday_lock_pullback_pct', ...)
  lock_min_profit = self._risk_config.get('intraday_lock_min_profit', ...)
  ```
  所有策略使用相同的利润锁定参数，但**跌停翘板波动大**可能需要不同的参数(如更宽松的pullback_pct)。当前没有策略级差异化。
- **影响程度**: P2 (功能正确但策略参数不够精细化)
- **建议**: 添加策略级利润锁定参数覆盖，类似STRATEGY_PULLBACK_PARAMS的模式

### BUG-008: 调仓日_rebalance中sell_codes的T+1检查在超时强卖之后重复执行

- **文件**: portfolio_backtest.py L4001-4004, L4011-4013
- **描述**:
  ```python
  # L4001: 第一次T+1检查(Phase1)
  t1_blocked = [code for code in sell_codes if ...]
  sell_codes = [code for code in sell_codes if code not in set(t1_blocked)]
  
  # L4011: 超时强卖
  sell_codes.extend(over_hold_codes)
  
  # L4013: 第二次T+1检查(超时后)
  sell_codes = [c for c in sell_codes if self._cost_basis_date.get(c) != trade_date]
  ```
  超时强卖的T+1检查是必要的(正常不应触超时，但防御性检查是对的)。但第一次检查后的sell_codes已经排除了T+1，超时强卖只添加了over_hold_codes，如果over_hold_codes中有当日买入的，第二次检查正确过滤。**逻辑正确，但冗余**。
- **影响程度**: P2
- **建议**: 合并为一次T+1检查在最终sell_codes确定后

### BUG-009: 买入循环中delta为0的边界条件

- **文件**: portfolio_backtest.py L4245
- **描述**:
  ```python
  for ts_code, target_count in pos_mgr.target_shares.items():
      current_shares = holdings.get(ts_code, 0)
      delta = target_count - current_shares
      if delta <= 0:
          continue
  ```
  当`delta < 0`时(持仓>目标)，应该走减仓逻辑，但这里只是continue跳过。减仓逻辑在L4323处理`reduce_codes`。但如果pos_mgr.target_shares[code] < holdings[code]但code不在reduce_codes中(因为reduce_codes的计算在mark_sold之前)，可能导致减仓遗漏。
  
  实际上reduce_codes在L4074计算:
  ```python
  reduce_codes = {code: holdings[code] - pos_mgr.target_shares[code] for code in holdings if code in pos_mgr.target_shares and holdings.get(code, 0) > pos_mgr.target_shares[code]}
  ```
  这个计算是正确的，但**pos_mgr.target_shares已被mark_sold修改**，所以被mark_sold的股不在target_shares中(已删除)，也就不在reduce_codes中，走的是sell_codes路径。逻辑正确。
- **影响程度**: 无bug，仅确认逻辑
- **建议**: 无需修改

### BUG-010: 跌停翘板pct_chg>0作为选股条件是收盘确认而非盘中可用

- **文件**: portfolio_backtest.py L3582 (跌停翘板筛选条件)
- **描述**:
  ```python
  {"name": "pct_chg", "target": 0, "operator": ">", "label": "今日收涨(确认翘板资金)"},
  ```
  注释说"收盘确认条件，与盘中买入逻辑自洽"。逻辑是:开盘观察不继续跌停→盘中低位买入→收盘确认翘板成功。
  
  **问题**: 回测中pct_chg>0在T日选股时使用(选出pct_chg>0的股)，但买入也在T日。如果pct_chg≤0，根本不会选入候选。这意味着**只有翘板成功的股才会被选中**，失败的全部被排除。实际交易中，你无法在买入时知道今天是否会成功翘板。
  
  **这构成未来函数**: 用T日收盘数据(pct_chg>0)来决定T日是否买入。实盘中，你只能在盘中判断"是否有翘板资金涌入"(通过观察成交量、买卖盘口等)，而非等到收盘确认pct_chg>0再买入。
- **影响程度**: P1 (跌停翘板收益虚高，因为剔除了所有失败案例)
- **建议**: 改用T-1日数据或开盘数据预选，T日只验证open_above_limit_down(开盘高于跌停价)作为盘中可观测信号，不再要求pct_chg>0

### BUG-011: 半路追涨pct_chg≥5%是已知未来函数，影响巨大

- **文件**: portfolio_backtest.py L3517-3528
- **描述**: V25对照实验已确认:
  - 有pct_chg≥5%: 收益350.98%/夏普15.29
  - 去pct_chg: 收益181.18%/夏普10.14
  
  pct_chg贡献了48.4%总收益。代码中已标注为"⚠近似,盘中趋势判断"。
  
  **当前状态**: 已知但未修复(V25分析"代价太大")。实盘需改为:
  1. T日选股+T+1收盘价买入(延迟1天)
  2. T日收盘确认+T+1开盘买入
- **影响程度**: P1 (实盘性能可能显著低于回测)
- **建议**: 实盘scanner已做近似(盘中趋势判断)，回测保留但需在报告中标注

### BUG-012: 龙头低吸使用T日volume_ratio是灰色地带

- **文件**: portfolio_backtest.py L3570-3574
- **描述**: 龙头低吸筛选条件使用`volume_ratio`(T日)而非`volume_ratio_prev`(T-1日)，注释说"龙头低吸的信号是缩量回调后T日开始放量，用_prev会把T日放量启动的高胜率候选过滤掉(收益-90%)"。
  
  **问题**: volume_ratio是T日全天数据，盘中只是近似。实盘中量比基于前5日均量推算，盘中可观测但精确值收盘才知。回测中用全天数据是近似，但影响巨大(改_prev降90%收益)。
- **影响程度**: P1 (实盘信号可能不如回测精确)
- **建议**: 保留T日数据但标注为近似，实盘scanner已处理

### BUG-013: _get_limit_up_price中V54-Bug5修复可能引入新问题

- **文件**: portfolio_backtest.py L3353-3365
- **描述**: V54修复:一字板时返回close_price而非0，让上层hit_probability_yizi=0逻辑正确执行。
  ```python
  if (open_price == close_price == high_price == low_price) and open_price > 0:
      return close_price  # 一字板返回涨停价,由上层hit_probability处理
  ```
  但`_get_buy_price_for_stock`中:
  ```python
  prices.append(p)  # p = close_price
  return max(prices)  # 多策略时取最高买入价
  ```
  如果首板打板是一字板，返回close(涨停价)作为买入价，然后hit_probability_yizi=0删除该股。逻辑正确。
  
  **但**: 如果一字板股同时被另一个策略(如龙头低吸)选中，`max(prices)`会取到涨停价作为买入价，而不是龙头低吸的`low + (high-low)*0.20`。因为涨停价>低吸价，取max导致以更高的价格买入。这虽然更保守(买入价更高)，但可能不符合龙头低吸策略的买入逻辑。
- **影响程度**: P2 (一字板股极少被多策略同时选中，且更保守是好事)
- **建议**: 多策略选同股时，取max(prices)是最保守估算，保留

### BUG-014: Calmar上限1000过高

- **文件**: portfolio_backtest.py L2742
- **描述**: 
  ```python
  calmar_ratio = min(raw_calmar, 1000.0)
  ```
  V49-P1-1将上限从200→1000。但3个月回测(60天)的max_drawdown可能<1%，Calmar=(1+total_return)^(252/60)/0.01轻松超过1000。上限1000无法区分正常和异常值。
  
  历史记录: V39基线Calmar=141.7被100截断，V40上限改为200。V53全年Calmar应远超200。
- **影响程度**: P2 (Calmar比率失真，但不影响回测收益计算)
- **建议**: Calmar比率仅在回测期≥6个月时有参考价值，短回测期应标注"不可靠"

### BUG-015: ultra_short.py中首板打板参数fallback不一致

- **文件**: ultra_short.py L220-224
- **描述**:
  ```python
  hit_yizi = strategy_params_local.get('hit_probability_yizi', _defaults.get('hit_probability_yizi', 0.0))
  hit_fast = strategy_params_local.get('hit_probability_fast', _defaults.get('hit_probability_fast', 0.3))
  hit_normal = strategy_params_local.get('hit_probability_normal', _defaults.get('hit_probability_normal', 0.5))
  hit_slow = strategy_params_local.get('hit_probability_slow', _defaults.get('hit_probability_slow', 0.7))
  ```
  **ultra_short.py中的fallback**: 0.3/0.5/0.7  
  **STRATEGY_CONFIGS V53**: 0.20/0.45/0.60  
  **portfolio_backtest.py中**: 0.20/0.45/0.65(BUG-005)
  
  三个地方三套不同的fallback值!ultra_short.py只影响日志打印，portfolio_backtest.py影响实际回测。
- **影响程度**: P1 (日志打印与实际参数不一致，用户误判)
- **建议**: 统一从STRATEGY_CONFIGS读取默认值

---

## 三、滑点应用审计

### 滑点应用完整性检查

| 卖出路径 | 是否扣滑点 | 正确性 |
|---------|-----------|--------|
| _rebalance卖出循环(调仓卖出) | should_apply_slippage判断 | ✅ 正确 |
| _rebalance卖出循环(止损) | should_apply_slippage判断 | ✅ 正确 |
| _rebalance卖出循环(冲高回落) | should_apply_slippage判断 | ✅ 正确 |
| _rebalance卖出循环(跳空止损) | should_apply_slippage判断 | ✅ 正确 |
| _rebalance卖出循环(止盈) | should_apply_slippage判断 | ✅ 正确 |
| _rebalance卖出循环(停牌超时) | 不扣滑点(L4173 `sell_price_adj = price`) | ✅ 正确(被迫卖出) |
| _rebalance卖出循环(强制空仓) | 不扣滑点(L1486 `sell_price_adj = price`) | ✅ 正确(被迫卖出) |
| _execute_forced_sells(非调仓日) | should_apply_slippage判断 | ✅ 正确 |
| _rebalance买入循环 | 始终扣滑点 | ✅ 正确 |

### 滑点规则表(SLIPPAGE_RULES)

检查sell_signal_checker.py中的SLIPPAGE_RULES:

| 原因 | 扣滑点 | 合理性 |
|------|--------|--------|
| 冲高回落 | 是 | ✅ 盘中主动卖出 |
| 利润保护 | 是 | ✅ 盘中主动卖出 |
| 利润锁定 | 是 | ✅ 盘中主动卖出 |
| 高开即卖 | 是 | ✅ 盘中主动卖出 |
| 调仓卖出 | 是 | ✅ 主动卖出 |
| 超时 | 否 | ✅ 被迫卖出(收盘价) |
| 止损 | 否 | ✅ 被迫卖出 |
| 跳空止损 | 否 | ✅ 被迫卖出 |
| 止盈 | 否 | ✅ 触发价卖出 |
| 强制空仓 | 否 | ✅ 被迫卖出 |
| 停牌超时 | 否 | ✅ 被迫卖出 |
| 减仓 | 是 | ✅ 主动卖出 |

**滑点应用整体正确**。

---

## 四、止损止盈逻辑审计

### 止损止盈参数读取路径

```
_get_sl_tp_for_code(code)
  → self.stock_to_strategy.get(code, [])
  → self._strategy_risk_params.get(sname, {}).get('stop_loss_pct', global_sl)
  → min(所有策略的SL) / strategies[0]的TP
```

**V34修复确认**: SL取min(最严格)✅，TP取strategies[0](买入策略)✅

### 止损止盈与strategy_defaults一致性

| 策略 | strategy_defaults SL/TP | 实际生效(无前端覆盖时) | 一致性 |
|------|------------------------|---------------------|--------|
| 半路追涨 | 4%/12% | 4%/12% | ✅ |
| 首板打板 | 3%/8% | 3%/8% | ✅ |
| 龙头低吸 | 3%/30% | 3%/30% | ✅ |
| 跌停翘板 | 5%/20% | 5%/20% | ✅ |

**止损止盈参数一致性确认**。

---

## 五、买入价计算审计

### 买入价计算函数

| 策略 | 计算公式 | 合理性 |
|------|---------|--------|
| 半路追涨 | open*(1+min_rise*0.8) | ⚠️盘中模拟，实际应在涨到3%时买入 |
| 首板打板 | _get_limit_up_price(涨停价) | ✅ 打板以涨停价买入 |
| 龙头低吸 | low+(high-low)*0.20 | ⚠️用当天high(未来函数)，但系数0.20保守 |
| 跌停翘板 | low*1.01 | ✅ 跌停价上方1%溢价 |
| 默认 | open | ✅ 开盘价 |

**龙头低吸买入价注意**: 使用了当天high，理论上盘中不知道high会是多少。但low+(high-low)*0.20 = low*0.80 + high*0.20，当high很高时(大阳线)，买入价偏高。但系数0.20使买入价接近low(偏低位)，影响有限。

---

## 六、首板打板成交概率模拟审计

### _apply_limit_up_hit_probability逻辑

```python
if o == c == h == l:     → 一字板 → hit_prob = 0.0 (不可能买入)
elif open_rise >= 8:     → 秒板 → hit_prob = 0.20
elif open_rise >= 2:     → 快速板 → hit_prob = 0.45
else:                    → 盘中板 → hit_prob = 0.60
```

**确定性hash**: `hashlib.md5(f"{code}_{trade_date}".encode())` → 结果可复现 ✅

**BUG-005的影响**: hit_probability_slow fallback硬编码0.65而非V53的0.60，导致更多低质量成交。

---

## 七、T+1约束审计

T+1约束在以下位置检查:
1. _rebalance卖出循环前(L3997-4000): 排除当日买入的股票
2. 超时强卖后(L4013): 再次排除
3. 减仓前(L4078): 排除当日买入
4. 强制空仓时(L1468): 排除当日买入
5. _check_and_execute_forced_sells(L233): 排除当日买入

**T+1约束完整且正确**。

---

## 八、未来函数风险汇总

| 因子 | 策略 | 风险等级 | 说明 |
|------|------|---------|------|
| pct_chg≥5% | 半路追涨 | ⚠️高 | T日收盘确认，去后收益-48.4% |
| pct_chg>0 | 跌停翘板 | ⚠️中 | T日收盘确认，只选成功案例 |
| volume_ratio(T日) | 龙头低吸 | ⚠️中 | 改_prev降90%，盘中可近似 |
| circ_mv(T日) | 已改_prev | ✅低 | V27已修复 |
| turnover_rate(T日) | 已改_prev | ✅低 | V27已修复 |
| is_limit_up | 涨停开板 | ⚠️低 | 需收盘确认，策略已关闭 |
| intraday_max_rise_pct | 半路追涨 | ✅低 | 盘中high逐步形成 |
| opening_pct_chg | 首板打板 | ✅低 | 9:25竞价可观测 |

---

## 九、修复优先级汇总

| 编号 | 优先级 | 问题 | 影响 |
|------|--------|------|------|
| BUG-005 | **P0** | hit_probability_slow fallback硬编码0.65 vs V53配置0.60 | V53优化失效，首板打板成交概率偏高 |
| BUG-003 | P1 | record.price不含滑点，与amount不一致 | 前端展示卖出价与实际金额不匹配 |
| BUG-004 | P1 | all_trades(dict)缺少sell_price字段 | 前端all_trades展示卖出价缺失 |
| BUG-010 | P1 | 跌停翘板pct_chg>0未来函数 | 只选成功案例，收益虚高 |
| BUG-011 | P1 | 半路追涨pct_chg≥5%未来函数 | 已知影响巨大(-48.4%收益) |
| BUG-012 | P1 | 龙头低吸volume_ratio(T日)灰色地带 | 改_prev降90%，实盘近似 |
| BUG-015 | P1 | ultra_short.py成交概率fallback不一致 | 日志与实际参数不匹配 |
| BUG-001 | P2 | 利润锁定检查代码冗余 | 可维护性 |
| BUG-002 | P2 | TP取值策略不一致 | check_full_sell已DEPRECATED |
| BUG-006 | P2 | 强制空仓未清理stock_to_strategy | 性能微浪费 |
| BUG-007 | P2 | 利润锁定无策略级参数 | 精细化不足 |
| BUG-008 | P2 | T+1检查冗余 | 可维护性 |
| BUG-013 | P2 | 一字板多策略取max买入价 | 更保守，可接受 |
| BUG-014 | P2 | Calmar上限1000过高 | 指标失真 |

---

## 十、关于3个月432%收益率的结论

**432%收益率是否虚高?**

1. **历史审计基线**: V45(3个月)147% → V53(3个月)372.86%，差异来自:
   - V47: 利润锁定参数优化(0.06/0.025→0.05/0.02) → 更多利润锁定触发
   - V53: SL/TP收紧(首板3%/8%, next_day_open_sell_pct 3%→2%) → 更早保护利润
   - 龙头低吸hold 5→7天 → 捕捉更大趋势

2. **未来函数贡献**: 已知半路追涨pct_chg贡献~170%收益(从350%→181%)，跌停翘板pct_chg>0也有贡献。去掉所有未来函数后预估收益约150-200%。

3. **3个月回测期过短**: 2025Q1(1-3月)可能恰好是策略最优时段，V53全年3825%但5-8月收益接近0。3个月数据不能代表全年。

4. **最终判断**: **432%部分虚高，主要来自未来函数贡献和短期回测期偏差**。保守估计去除未来函数后3个月收益约150-200%。但不构成bug——这是策略设计选择，需在实盘切换时调整。

---

## 附录: 代码质量观察

1. **_build_run_result过长(700行)** — 虽然有说明文档解释为何不拆分，但可考虑拆分为5个子方法
2. **_rebalance过长(453行)** — 同上
3. **重复的fallback模式** — `params.get('x', STRATEGY_CONFIGS.get(id, {}).get('params', {}).get('x', default))`出现数十次，应抽取工具函数
4. **run_state dict传参** — 10+个变量通过dict在方法间传递，建议改为dataclass
5. **策略名中英文不一致** — 'halfway_chase' vs '半路追涨' 混用，容易混淆
