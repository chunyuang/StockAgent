# V17回测模块审查报告

**审查日期**: 2026-05-21
**审查人**: 第二轮审查（发现P0-1/P0-2已修复后，补充发现新问题）
**审查范围**: portfolio_backtest.py (4034行) + ultra_short.py (675行) + strategy_defaults.py
**基线版本**: commit 94fd153 (V16)
**V16基线结果**: 2策略(半路追涨+跌停翘板) 收益69.92% 夏普8.79 回撤3.01% 胜率69.23% 104笔

---

## 审查发现 (按优先级)

### P0级 (数据正确性/逻辑错误)

**P0-1: `_rebalance`未对目标池内的持仓检查冲高回落/高开即卖/利润保护**
- 位置: `_rebalance` 方法, 约 L3590-3610
- 问题: 对仍在目标池中的持仓(`_sl_tp_codes`)，只检查了止损和止盈，**完全跳过了冲高回落/高开即卖/利润保护检查**
- 影响代码:
  ```python
  _sl_tp_codes = set(holdings.keys()) - set(sell_codes)  # 还在目标池中的持仓
  for code in list(_sl_tp_codes):
      ...
      if enable_stop_loss and low_p <= stop_price:
          sell_codes.append(code)
      elif enable_take_profit and high_p >= tp_price:
          sell_codes.append(code)
      # ❌ 缺少: early_sell_signals(冲高回落/高开即卖/利润保护)检查!
  ```
- 影响场景: 持仓股次日高开冲高回落(如半路追涨高开5%+且高开低收)，本应以open价卖出保利润，但因为仍在目标池中而继续持有，可能回吐利润甚至止损
- 修复: 对`_sl_tp_codes`也调用`_check_early_sell_signals`，触发时加入sell_codes

**P0-2: `_rebalance`减仓逻辑未检查冲高回落/高开即卖**
- 位置: `_rebalance` 方法, 约L3900 减仓逻辑
- 问题: 减仓分支(`reduce_codes`)只检查了止损止盈是否应升级为全卖，**未检查冲高回落/高开即卖/利润保护**
- 修复: 对`reduce_codes`中的股票也调用`_check_early_sell_signals`，触发时升级为全卖

**P0-3: 非调仓日超时强卖reason不包含交易日信息**
- 位置: `_process_non_rebalance_day` 超时判断
- 问题: 超时reason格式为 `超时(3交易日>3交易日)` 而非 `超时(3天>3天)`，当恰好等于max_hold_days时不触发(>号)，导致超时+1交易日才卖出
- 影响: 3天max_hold实际持有4个交易日(第4天trade_days_held=3>3才触发)
- 修复: 改为 `>=` 或调整阈值为 `max_hold_days - 1`(视语义而定)。当前语义"持有超过N天卖出"用`>`是正确的，但需要确认这是否符合预期

### P1级 (逻辑/模拟精度)

**P1-1: 半路追涨收盘确认close_rise_pct默认5%过于严格，与V9基线3%对比收益差距大**
- 位置: `strategy_defaults.py` halfway_chase params
- 问题: V14将min_close_rise_pct从3%提升至5%，虽然提高了单笔胜率(40.5%→66.2%)，但大幅减少了信号数量
- 数据: 当前104笔交易(含跌停翘板27笔)，半路追涨77笔。如果恢复3%收盘确认，信号量可能增加50%+
- 建议: 测试3%收盘确认的收益对比，如果收益提升则回退

**P1-2: 跌停翘板默认min_circulation_market_cap=20亿偏小**
- 位置: `strategy_defaults.py` limit_down_qiao params
- 问题: V16审查中P1-2建议提升至30亿，但测试后回退(收益-5%)。20亿仍可能包含小盘操纵风险股
- 现状: 保持20亿，可接受

**P1-3: 调仓日冲高回落卖出时strategy_name缺失**
- 位置: `_process_rebalance_day` 调仓日无交易分支(L1755)
- 问题: 止损止盈卖出记录的`strategy_name`使用`_get_strategy_for_stock(code)`，但冲高回落/高开即卖/利润保护触发的卖出也走同样逻辑。然而该分支没有像_rebalance中那样处理冲高回落strategy_name
- 影响: 前端策略统计可能将这些卖出归入错误策略

**P1-4: `_get_buy_price_for_stock`跌停翘板买入价low*1.01可能偏低**
- 位置: `_get_buy_price_for_stock` 跌停翘板分支
- 问题: V15将系数从1.005调整为1.01(1%溢价)，但跌停翘板实际买入价通常在跌停价上方2-5%
- 影响: 买入价偏低导致回测利润偏高
- 建议: 测试1.02(2%溢价)的效果

**P1-5: 首板打板成交概率模拟过于简化**
- 位置: `_apply_limit_up_hit_probability`
- 问题: 仅基于开盘涨幅分4档(hit_probability_yizi/fast/normal/slow)，未考虑封单金额、板块热度等
- 影响: 回测与实盘偏差大，但首板打板当前2策略组合中未使用

**P1-6: 龙头低吸策略的买入价low+(high-low)*0.25可能偏高**
- 位置: `_get_buy_price_for_stock` 龙头低吸分支
- 问题: 低吸策略应尽量在低位买入，0.25的位置可能在日线上半段而非低位
- 影响: 买入价偏高导致回测利润偏低(保守)，但龙头低吸当前未在2策略组合中使用

**P1-7: 减仓reason字段始终为"减仓"，未区分是否因止损止盈升级**
- 位置: `_rebalance` 减仓分支
- 问题: 减仓时reason硬编码为'减仓'，但减仓前有止损止盈检查(升级为全卖的已移除)。保留减仓的reason缺少具体原因
- 影响: 前端无法区分正常调仓减仓和因止损止盈触发的减仓

### P2级 (代码质量/性能)

**P2-1: _rebalance方法453行过长，建议提取子方法**
- 已有P1-7修复提取了4个子方法(_calc_total_value/_calc_position_multiplier/_apply_limit_up_hit_probability/_get_sl_tp_for_code)
- 建议: 进一步提取卖出决策和买入决策为独立方法

**P2-2: 卖出决策代码在3处重复(调仓日无交易/非调仓日/_rebalance内)**
- 止损止盈卖出逻辑在3个地方分别实现，虽然V14提取了`_check_early_sell_signals`，但止损止盈判断+执行卖出的完整逻辑仍重复3次
- 建议: 提取为统一方法`_execute_forced_sell(codes_with_reasons, ...)` 

**P2-3: ultra_short.py中首板打板参数显示逻辑与portfolio_backtest.py不同步**
- 位置: `ultra_short.py` 策略参数打印段(约L120-150)
- 问题: 首板打板参数在ultra_short.py和_print_single_strategy_filtering中分别显示，默认值来源不同
- 影响: 日志中显示的参数可能与实际筛选使用的参数不一致

**P2-4: strategy_filter.py与portfolio_backtest.py._build_strategy_filter_conditions不同步**
- 已在V16中标注(P1-5)，strategy_filter.py是拆分产物但未被调用
- 建议: 后续Phase删除或统一，当前不修改

**P2-5: _get_prices中代码标准化逻辑在3处重复**
- `_get_prices`、`_get_stock_names`、缓存查找中各有代码标准化逻辑
- 建议: 提取为`_standardize_ts_code(code)`类方法

**P2-6: factor_engine.py compute_factors每次调用都重新从MongoDB读取因子数据**
- 位置: `factor_engine.py`
- 问题: 每个调仓日都完整读取一次factor数据(5000+行)，无跨日缓存
- 影响: 回测14秒中约8秒在MongoDB IO
- 建议: 考虑批量预读整个回测区间的因子数据(内存换时间)

---

## 修复计划

| 编号 | 优先级 | 修复内容 | 预期影响 |
|------|--------|----------|----------|
| P0-1 | P0 | _rebalance目标池内持仓冲高回落检查 | 减少利润回吐，提升收益/回撤 |
| P0-2 | P0 | 减仓逻辑冲高回落检查 | 同上 |
| P0-3 | P0 | 超时强卖阈值确认(>vs>=) | 持仓天数精确性 |
| P1-1 | P1 | 半路追涨close_rise_pct 5%→3%测试 | 可能增加信号量+收益 |
| P1-4 | P1 | 跌停翘板买入价1.01→1.02测试 | 减少利润虚高 |
| P2-2 | P2 | 提取统一卖出执行方法 | 代码质量 |
| P2-5 | P2 | 提取代码标准化方法 | 代码质量 |

---

## 第二轮审查补充 (2026-05-20 08:30)

### 已确认修复（第一轮P0-1/P0-2已在代码中实现）

- ✅ P0-1: `_rebalance`目标池内持仓冲高回落/高开即卖/利润保护检查 — 已修复(L3608)
- ✅ P0-2: 减仓逻辑冲高回落检查 — 已修复(L3697)
- ✅ V17策略风控参数优先级修复(L790) — 前端riskParams > 用户改全局 > 策略默认

### 新发现

**P0-4: `min_close_rise_pct` fallback值不一致(已修复)**
- 位置: `ultra_short.py:321`, `portfolio_backtest.py:3284`
- 问题: fallback硬编码0.03，但strategy_defaults.py已更新为0.05
- 影响: 参数缺失时使用0.03(3%)而非0.05(5%)，与实际筛选条件不一致
- 修复: fallback改为0.05 + ultra_short.py改为从_defaults读取

**P0-5: 减仓检查`low_p/high_p/open_p` fallback值不一致(已修复)**
- 位置: `_rebalance`减仓止损止盈检查 L3691-3693
- 问题: 用`p.get('low', 0)`作fallback，其他3处用`p.get('low', p['close'])`
- 影响: 数据缺失时low_p=0，止损条件`low_p <= stop_price`永远不成立，漏触发止损
- 修复: 改为`p.get('low', p.get('close', 0))`

**P1-8: 超时强卖`>`vs`>=`语义确认**
- 位置: `_process_non_rebalance_day` L1944, `_rebalance` L3649
- 问题: `trade_days_held > max_hold`用`>`，即max_hold=3时第4个交易日才卖出
- 语义: "持有超过3天" → 第4天卖(>)是正确的，"持有3天" → 第3天卖(>=)是另一种理解
- 现状: `>`符合"超过"的语义，不修改

**P2-7: ultra_short.py L320 `min_rise_pct` fallback应从_defaults读取**
- 位置: `ultra_short.py:320`
- 问题: `sp.get("min_rise_pct", 0.03)`直接硬编码fallback，而L184用`_defaults.get('min_rise_pct', 0.03)`
- 修复: 已改为`sp.get("min_rise_pct", _defaults.get('min_rise_pct', 0.03))`

### V17验证结果(2策略 20260105-20260320)

| 指标 | V16基线 | V17修复后 | 变化 |
|------|---------|-----------|------|
| 收益 | 69.92% | 69.38% | -0.54% |
| 回撤 | 3.00% | 3.05% | +0.05% |
| 胜率 | 69.23% | 68.27% | -0.96% |
| 夏普 | 8.79 | 9.01 | +0.22 |
| 盈亏比 | 2.17 | 2.15 | -0.02 |
| 交易 | 104笔 | 104笔 | 0 |
| 卖出other | - | 0 | ✅ |

变化极小: P0-4的fallback修正仅在参数缺失时生效，正常流程从strategy_defaults读取本身就是0.05。P0-5的修正对当前2策略组合无影响(减仓场景在max_stocks=3时极少发生)。

### Git
- 待提交: P0-4(min_close_rise_pct fallback) + P0-5(减仓low_p fallback) + P2-7(min_rise_pct _defaults)
