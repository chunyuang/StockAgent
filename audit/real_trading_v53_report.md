# 实盘模块 V53 审计报告

> 审计日期：2026-05-26  
> 审计范围：real_trading/ 全部核心模块 + 回测引擎 strategy_defaults.py / sell_signal_checker.py  
> 审计原则：只做审计报告，不修改任何代码

---

## 一、实盘-回测参数一致性检查

### 1.1 止损/止盈/持仓天数（核心风控参数）

| 参数 | 策略 | strategy_defaults.py | 实盘读取方式 | 一致性 |
|------|------|---------------------|-------------|--------|
| stop_loss_pct | 半路追涨 | 4% | ✅ paper_trading.py / position_manager.py 从STRATEGY_CONFIGS读取 | ✅ 一致 |
| stop_loss_pct | 首板打板 | 3% | ✅ 同上 | ✅ 一致 |
| stop_loss_pct | 龙头低吸 | 3% | ✅ 同上 | ✅ 一致 |
| stop_loss_pct | 跌停翘板 | 5% | ✅ 同上 | ✅ 一致 |
| take_profit_pct | 半路追涨 | 12% | ✅ 同上 | ✅ 一致 |
| take_profit_pct | 首板打板 | 8% | ✅ 同上 | ✅ 一致 |
| take_profit_pct | 龙头低吸 | 30% | ✅ 同上 | ✅ 一致 |
| take_profit_pct | 跌停翘板 | 20% | ✅ 同上 | ✅ 一致 |
| max_hold_days | 半路追涨 | 3 | ✅ 同上 | ✅ 一致 |
| max_hold_days | 首板打板 | 2 | ✅ 同上 | ✅ 一致 |
| max_hold_days | 龙头低吸 | 7 | ✅ 同上 | ✅ 一致 |
| max_hold_days | 跌停翘板 | 3 | ✅ 同上 | ✅ 一致 |
| slippage_pct | 半路追涨 | 0.2% | ✅ 从riskParams读取 | ✅ 一致 |
| slippage_pct | 首板打板 | 0.5% | ✅ 同上 | ✅ 一致 |
| slippage_pct | 龙头低吸 | 0.2% | ✅ 同上 | ✅ 一致 |
| slippage_pct | 跌停翘板 | 0.3% | ✅ 同上 | ✅ 一致 |

**结论：V40修复后，实盘核心风控参数已全部从strategy_defaults.py动态读取，不再硬编码，与回测完全一致。**

### 1.2 全局风控参数

| 参数 | strategy_defaults GLOBAL_RISK | daily_scheduler | 一致性 |
|------|------------------------------|-----------------|--------|
| max_total_position | 0.7 | ✅ 从GLOBAL_RISK读取 | ✅ 一致 |
| max_position_per_stock | 0.35 | ✅ 从GLOBAL_RISK读取 | ✅ 一致 |
| force_empty_limit_down | 80 | ✅ 通过backtester._check_force_empty | ✅ 一致 |
| force_empty_limit_up | 10 | ✅ 同上 | ✅ 一致 |
| force_empty_index_drop_pct | 3% | ✅ 同上 | ✅ 一致 |
| hold_protection_threshold | 5% | ✅ _step_compute_rebalance中读取 | ✅ 一致 |
| intraday_lock_* | 5%/2%/2% | ✅ position_manager.daily_check读取 | ✅ 一致 |

---

## 二、实盘-回测逻辑差异清单

### 2.1 🔴 P0级差异（影响实盘收益的核心逻辑差异）

#### P0-1: 卖出信号检查路径完全不同

**回测**：统一通过 `SellSignalChecker.check_early_sell()` → 优先级队列驱动 → 冲高回落/利润保护/高开即卖/利润锁定  
**实盘**：`position_manager.daily_check()` 自行实现了一套独立的告警逻辑，**不调用SellSignalChecker**

差异细节：
1. **高开即卖（首板打板专用）**：
   - 回测：`SellSignalChecker` 中首板打板优先级1（最高），高开≥`next_day_open_sell_pct`(2%)即以open卖出
   - 实盘：`daily_check()` 中只检查 `_strategy == '首板打板' and open_rise >= _pullback_threshold`，使用`next_day_open_sell_pct`参数名但取值来源不同——实盘从`_strategy_params.get('next_day_open_sell_pct')`，回测从`SellSignalChecker._get_sell_params()`合并后的params读取

2. **冲高回落参数来源不一致**：
   - 回测：`STRATEGY_PULLBACK_PARAMS` 在 `sell_signal_checker.py` 中硬编码（半路追涨mid_fallback=0.01, 龙头/跌停=0.015, 龙头profit_lock=0.06）
   - 实盘：从 `STRATEGY_CONFIGS[id].params` 读取 `pullback_mid_fallback_pct`，但 **strategy_defaults.py 的 params 中只有跌停翘板定义了 `pullback_mid_fallback_pct: 0.015`，半路追涨和龙头低吸没有定义此参数**
   - **实盘fallback**：半路追涨 `_pullback_mid_fallback = _strategy_params.get('pullback_mid_fallback_pct', 0.01)` 硬编码0.01作为fallback，与回测STRATEGY_PULLBACK_PARAMS中的0.01一致，但这是**巧合而非设计**
   - 龙头低吸实盘fallback也是0.01，而回测是0.015 → **⚠️ 实盘龙头低吸冲高回落mid_fallback为0.01，回测为0.015，实盘更敏感**

3. **利润锁定参数**：
   - 回测：`INTRADAY_PROFIT_LOCK_SIGNALS` 统一注册，`check_intraday_profit_lock()` 函数，参数从 GLOBAL_RISK 读取
   - 实盘：`daily_check()` 中内联实现了相同逻辑，参数也从 GLOBAL_RISK 读取 → **一致**

4. **冲高回落利润保护阈值**：
   - 回测：龙头低吸 `pullback_profit_lock_threshold=0.06`（V53从8%→6%）
   - 实盘：`_pullback_profit_lock = _strategy_params.get('pullback_profit_lock_threshold', None)`，但 **strategy_defaults.py 龙头低吸 params 中没有定义此参数**，所以实盘 `None`，条件 `_pullback_profit_lock is not None and open_rise >= _pullback_profit_lock` 永远不成立
   - **🔴 龙头低吸实盘缺少 pullback_profit_lock_threshold 参数，冲高回落利润保护失效！** 回测中利润≥6%时不触发冲高回落让利润锁定/超时自然退出，实盘中无此保护

#### P0-2: 卖出价格确定逻辑差异

| 卖出原因 | 回测卖出价 | 实盘卖出价 | 一致性 |
|----------|-----------|-----------|--------|
| 正常止损 | stop_loss_price | ✅ stop_loss_price | ✅ 一致 |
| 跳空止损 | open_price | ⚠️ stop_loss_price（代码写的是`pos.stop_loss_price`，注释说"跳空止损用open"但实际代码取的是stop_loss_price） | ❌ 不一致 |
| 止盈 | take_profit_price | ✅ take_profit_price | ✅ 一致 |
| 冲高回落 | open_price | ✅ open_price（有fallback到close） | ✅ 基本一致 |
| 利润保护 | close_price | ✅ close_price（默认） | ✅ 一致 |
| 利润锁定 | close_price | ✅ close_price（默认） | ✅ 一致 |
| 超时 | close_price | ⚠️ alert.get("current_price", 0) = close | ✅ 一致 |
| 调仓卖出 | close_price | ⚠️ current_price或buy_price或从MongoDB查close | ✅ 基本一致 |

**🔴 P0-2 关键问题：跳空止损实盘用stop_loss_price而非open_price**

回测逻辑（sell_signal_checker.py + portfolio_backtest.py）：
- 跳空止损：open ≤ stop_price → 以 open 价格卖出
- 正常止损：low ≤ stop_price 且 open > stop_price → 以 stop_price 卖出

实盘逻辑（paper_trading.py daily_settlement）：
```python
if "跳空止损" in str(alert.get("alerts", [])):
    sell_price = pos.stop_loss_price  # ← BUG：应该是open价格！
    reason = "跳空止损"
else:
    sell_price = pos.stop_loss_price  # 正常止损
    reason = "止损平仓"
```

**两分支取的sell_price完全相同（都是stop_loss_price），跳空止损分支的open价逻辑被吞掉了。** position_manager.daily_check() 的alert中包含了open_p信息，但paper_trading.py的daily_settlement没有使用alert中的open价格。

#### P0-3: 实盘信号生成策略判断与回测筛选条件不同

**generate_daily_signals.py 的 `_get_strategy_for_stock()`**：
```python
if abs(pct_chg - 10) < 0.5 and abs(close - limit_up) < 0.01:
    return "首板打板"
elif pct_chg >= 5:
    return "半路追涨"
else:
    return "龙头低吸"
```

这个简化的规则与回测的 `_build_strategy_filter_conditions()` 完全不同：
- 回测首板打板：需要满足竞价条件（opening_pct_min/max）、换手率、流通市值、成交概率模拟等多维条件
- 回测半路追涨：需要 min_rise_pct/max_rise_pct/min_volume_ratio/max_volume_ratio/min_close_rise_pct/max_open_rise_pct
- 回测龙头低吸：需要 min_consecutive_limit/min_correction_pct/max_correction_pct/min_circulation_market_cap 等
- 回测跌停翘板：**完全没有对应判断**，实盘信号生成器不会产出"跌停翘板"策略的信号

**问题**：实盘策略分配过于粗糙，所有不满足首板/半路的都归为"龙头低吸"，且完全缺失"跌停翘板"策略信号。后续的策略级止损止盈虽然从STRATEGY_CONFIGS读取了正确的参数，但如果策略标签本身就是错的，参数对齐毫无意义。

### 2.2 🟡 P1级差异（影响实盘精度但不直接导致亏损）

#### P1-1: 滑点规则不完整

**回测**：`SLIPPAGE_RULES` 定义了12种卖出原因的滑点规则，止盈/止损/跳空止损/超时/强制空仓/停牌超时强卖不扣滑点  
**实盘**：`paper_trading.py` 通过 `should_apply_slippage(reason)` 前缀匹配，与回测一致 → ✅ **已对齐**

但有一个细微差异：
- 回测中"调仓卖出"扣滑点(True)
- 实盘daily_scheduler的`_step_execute_trades`中卖出时，reason="调仓卖出"，调用`close_position`时默认slippage=0.002
- 但close_position会根据should_apply_slippage("调仓卖出")=True来决定是否扣滑点
- ✅ 一致

#### P1-2: 买入价计算差异

**回测**：`STRATEGY_BUY_PRICE` 注册表，每个策略有独立的买入价计算函数：
- 半路追涨：max(open, close * (1 - min_rise_pct))
- 龙头低吸：open（次日买入用open价）
- 跌停翘板：open
- 首板打板：涨停价（需_get_limit_up_price）

**实盘**：`generate_daily_signals.py` 中 `_generate_trading_plan()` 尝试调用 `get_buy_price_for_strategy`，但调用方式有问题：
```python
_calc = STRATEGY_BUY_PRICE.get(strategy_name)
if _calc and _calc.__name__ != 'calc_buy_price_first_limit_up':
    buy_price = _calc(stock['ts_code'], open_p, stock['close'], high_p, low_p, pre_close, {})
```

问题：
1. **open_p/high_p/low_p/pre_close从stock dict取，但stock dict中可能没有这些字段**（`_get_stock_details` 的MongoDB projection只取了close/pct_chg/amount/volume/up_limit/down_limit，没有open/high/low/pre_close）
2. **首板打板被跳过**（`_calc.__name__ != 'calc_buy_price_first_limit_up'` 条件），fallback到close*1.01
3. **跌停翘板策略信号不存在**（P0-3），所以跌停翘板的买入价函数也永远不会被调用

#### P1-3: 持仓天数计算差异

**回测**：`_calc_trade_days_held()` 使用MongoDB交易日历精确计算交易日天数  
**实盘**：`Position.hold_days()` 尝试用MongoDB交易日历，但在async上下文中fallback到 `natural_days / 1.5` 近似

问题：
- 在async上下文（daily_check是async函数）中，`run_until_complete`会抛异常，所以永远走fallback
- 近似公式`natural_days / 1.5`对短持仓（1-3天）误差较大：
  - 周五买入→周一：自然日3天/1.5=2天，实际1个交易日
  - 周一买入→周三：自然日2天/1.5=1.33→1天，实际2个交易日
  - 周四买入→周一：自然日4天/1.5=2.67→2天，实际2个交易日（部分正确）

**影响**：max_hold_days=2的首板打板，周五买入→周一可能被误判超期（2天≥2天）

#### P1-4: T+1约束实现差异

**回测**：`PositionManager.block_t1(code)` 标记当日买入股不可卖出，`should_sell()`检查  
**实盘**：`paper_trading.py._t1_blocked` 集合存储 `account_id:ts_code`，在`daily_settlement`中检查

问题：
1. `_t1_blocked` 是实例属性而非账户属性，多账户场景下不同账户的T+1可能互相干扰
2. `daily_settlement` 在盘后调用时 `_t1_blocked.clear()` 清除所有锁定——这是正确的（次日可卖）
3. 但如果同一天调用两次`daily_settlement`（比如手动触发），第二次调用时`_t1_blocked`已被清空，如果当日有新买入会被跳过
4. **盘中自动平仓（run_intraday）不检查T+1约束**：`_step_execute_trades`中的卖出和`run_intraday`中的自动平仓都不检查`_t1_blocked`

#### P1-5: 佣金计算差异

**回测**：`commission_rate = 0.0003`（从GLOBAL_RISK读取），最低5元  
**实盘**：`commission = max(total_cost * 0.0003, 5)` → ✅ 一致

印花税：回测`stamp_duty_rate = 0.001`，实盘`stamp_tax = total_income * 0.001` → ✅ 一致

#### P1-6: 强制空仓逻辑差异

**回测**：`_check_force_empty()` 检查三个条件（跌停数≥80 且 涨停数≤10 且 大盘跌幅≥3%）  
**实盘**：`generate_daily_signals.py` 调用 `self.backtester._check_force_empty(trade_date)` → ✅ 复用回测逻辑

但 `daily_scheduler.py` 的盘中/盘后调度**不检查强制空仓**。如果盘中触发强制空仓条件（突发暴跌），实盘不会自动清仓。

### 2.3 🟢 P2级差异（影响有限或属设计选择）

#### P2-1: 持仓市值估算

**回测**：使用当日close精确计算  
**实盘**：`_update_account_performance` 使用 `pos.get("current_price") or pos.get("last_price") or pos["buy_price"]`，但Position对象没有`current_price`和`last_price`字段（dataclass中未定义），所以**永远fallback到buy_price**，导致持仓期间PnL永远不变

**实际上V41注释说"P1修复：用current_price计算市值"，但Position dataclass没有动态添加这些字段的逻辑，所以修复无效。**

#### P2-2: 绩效统计不包含未实现盈亏

**实盘**：`PerformanceAnalyzer._get_balance_series()` 从已平仓交易累计profit，不包含当前持仓的浮动盈亏  
**回测**：使用净值序列（包含持仓市值），更准确

#### P2-3: 策略ID映射散落多处

中文名→英文ID的映射在以下位置独立实现：
1. `paper_trading.py` place_order: `_NAME_TO_ID = {cfg["name"]: sid ...}`
2. `position_manager.py` add_position_by_signal: `_NAME_TO_ID = {cfg["name"]: sid ...}`
3. `position_manager.py` daily_check: 硬编码 `{'半路追涨': 'halfway_chase', ...}`
4. `generate_daily_signals.py`: `_strategy_id_name_map = {"halfway_chase": "半路追涨", ...}`

**风险**：新增策略时如果只改了strategy_defaults.py，4处映射可能遗漏

#### P2-4: 数据持久化使用JSON文件

**实盘**：accounts/positions/trade_history 全部使用JSON文件持久化  
**回测**：结果写入MongoDB

**风险**：JSON文件无事务保护，并发写入可能丢失数据；无索引，查询效率低

---

## 三、一致性风险点总结

### 🔴 高风险

| # | 风险点 | 影响 | 根因 |
|---|--------|------|------|
| R1 | 龙头低吸冲高回落利润保护失效 | 龙头低吸盈利≥6%时仍被冲高回落触发卖出，截断大牛 | strategy_defaults.py龙头低吸params缺少`pullback_profit_lock_threshold` |
| R2 | 跳空止损用错卖出价 | 跳空止损应以open卖出，实盘用stop_loss_price（可能高于open导致"卖出价>实际可卖价"） | paper_trading.py daily_settlement 两分支取相同sell_price |
| R3 | 实盘策略标签分配粗糙 | 跌停翘板信号缺失；非首板/半路的都归为"龙头低吸"导致策略级止损止盈参数错配 | generate_daily_signals._get_strategy_for_stock过于简化 |
| R4 | 龙头低吸冲高回落mid_fallback实盘0.01 vs 回测0.015 | 实盘更敏感，0.01的回落即触发冲高回落，可能过早卖出龙头 | strategy_defaults.py龙头低吸params缺少pullback_mid_fallback_pct |

### 🟡 中风险

| # | 风险点 | 影响 | 根因 |
|---|--------|------|------|
| R5 | 持仓天数计算近似误差 | 首板打板(2天)可能被误判超期 | hold_days()在async上下文只能用natural_days/1.5 |
| R6 | 盘中自动平仓不检查T+1 | 当日买入的股票可能被盘中风控卖出 | run_intraday不检查_t1_blocked |
| R7 | 持仓市值用buy_price | 账户绩效PnL在持仓期间不更新 | Position没有current_price字段 |
| R8 | 买入价计算缺open/high/low/pre_close | 交易计划中的建议买入价可能不准 | _get_stock_details的MongoDB projection缺字段 |
| R9 | 策略ID映射4处独立维护 | 新增策略时可能遗漏映射 | 无统一映射函数 |

---

## 四、实盘↔回测互相助力建议

### 4.1 实盘→回测反馈（滑点校准、成交概率调整）

#### 建议 E2B-1: 实盘滑点校准回测参数

**现状**：回测使用固定滑点（半路追涨0.2%，首板打板0.5%，跌停翘板0.3%），实盘也是同样的参数。  
**问题**：实际滑点可能因市场波动率、流动性、时段不同而变化。

**方案**：
1. 实盘记录每笔交易的实际滑点（申报价vs成交价偏差）
2. 按策略+市场情绪分组统计实际滑点分布
3. 定期（月度）将统计结果回传回测参数
4. 例如：如果首板打板实际平均滑点0.8% > 回测0.5%，则回测应调高滑点参数

#### 建议 E2B-2: 实盘成交率校准打板成交概率

**现状**：回测首板打板使用成交概率模拟（秒板20%/快速板45%/盘中板60%）  
**问题**：这些概率来自历史统计，实盘可能因市场结构变化而不同

**方案**：
1. 实盘记录每只首板打板标的的实际成交结果（是否成交、成交时间、封板时长）
2. 统计实际成交概率，按类型分组
3. 差异>5%时告警，建议更新strategy_defaults.py中的hit_probability参数
4. 可做成ParamCenter动态参数，无需改代码

#### 建议 E2B-3: 实盘亏损样本回灌回测

**现状**：回测和实盘独立运行，实盘亏损无法反馈给回测  
**问题**：回测可能持续高估某些策略的收益

**方案**：
1. 实盘亏损交易按策略分组，提取特征（买入时机/市场环境/个股特征）
2. 在回测中增加"实盘亏损模式过滤器"：对符合实盘亏损特征的信号降权
3. 例如：如果实盘半路追涨在情绪冰点期（<40分）全部亏损，回测应同步过滤

### 4.2 回测→实盘反馈（参数回传、信号验证）

#### 建议 B2E-1: 回测参数变更自动同步实盘

**现状**：strategy_defaults.py 已是单一参数来源，实盘动态读取  
**问题**：仍有一处硬编码（position_manager.daily_check中的策略ID映射）和回测独有参数（STRATEGY_PULLBACK_PARAMS）不在strategy_defaults.py中

**方案**：
1. 将 `STRATEGY_PULLBACK_PARAMS` 合并到 `STRATEGY_CONFIGS.params` 中（消除sell_signal_checker.py中的独立定义）
2. 在strategy_defaults.py中统一导出 `STRATEGY_NAME_ID_MAP`，所有模块使用同一映射
3. 这样回测参数变更时实盘自动跟随

#### 建议 B2E-2: 回测信号预验证实盘信号

**现状**：实盘信号由 `RealTradingSignalGenerator` 独立生成，与回测选股逻辑不同  
**问题**：实盘可能选到回测中表现差的标的

**方案**：
1. 实盘信号生成后，查询该标的在最近回测中的表现（如果有）
2. 如果某标的在回测中胜率<30%或平均亏损，在交易计划中标注"回测验证弱"
3. 反向：如果回测选中但实盘未选中的标的，标注"实盘遗漏"供复盘

#### 建议 B2E-3: 回测最优参数周期性回归实盘

**现状**：参数优化通过手动回测验证后修改strategy_defaults.py  
**问题**：修改频率低，可能错过市场风格切换

**方案**：
1. 每月自动运行参数扫描（关键参数如止损/止盈/持仓天数）
2. 如果新参数组合在近3个月回测中显著优于当前参数（夏普+0.5以上），生成参数变更建议
3. 审批后更新strategy_defaults.py → 实盘自动生效

### 4.3 闭环反馈体系

```
┌─────────────┐    信号+参数     ┌─────────────┐
│   回测引擎   │ ──────────────→ │  实盘引擎    │
│             │                  │             │
│ • 策略参数   │                  │ • 信号执行   │
│ • 选股条件   │                  │ • 滑点记录   │
│ • 卖出规则   │                  │ • 成交概率   │
│             │ ←────────────── │ • 亏损模式   │
└─────────────┘   实盘反馈校准    └─────────────┘
      ↑                                │
      │         参数变更建议            │
      └────────────────────────────────┘
```

**建议实施优先级**：
1. **P0**：B2E-1（统一参数来源，消除STRATEGY_PULLBACK_PARAMS独立定义）
2. **P0**：修复R1-R4（冲高回落利润保护、跳空止损价格、策略标签、mid_fallback）
3. **P1**：E2B-1（滑点校准）+ B2E-2（信号预验证）
4. **P2**：E2B-2（成交概率校准）+ B2E-3（参数自动回归）

---

## 五、具体代码优化建议

### 5.1 P0级修复（必须修复，直接影响实盘收益）

#### 修复 R1: 龙头低吸冲高回落利润保护

**文件**：`strategy_defaults.py`  
**改动**：在 `dragon_head.params` 中添加：
```python
"pullback_profit_lock_threshold": 0.06,  # 利润≥6%时不触发冲高回落
```
**同时**：在 `dragon_head.params` 中添加：
```python
"pullback_mid_fallback_pct": 0.015,  # 与回测STRATEGY_PULLBACK_PARAMS一致
```

#### 修复 R2: 跳空止损卖出价

**文件**：`paper_trading.py` daily_settlement方法  
**改动**：将跳空止损分支的sell_price改为从alert中取open价格：
```python
if "跳空止损" in str(alert.get("alerts", [])):
    sell_price = alert.get("open", pos.stop_loss_price)  # 用open价
    reason = "跳空止损"
```

#### 修复 R3: 策略标签分配

**文件**：`generate_daily_signals.py`  
**改动**：`_get_strategy_for_stock()` 应该基于因子筛选结果分配策略，而非简单规则。当前代码中已有 `stock_strategy_map`（策略筛选结果），但 `_get_stock_details` 没有使用它。

建议将 `stock_strategy_map` 传入 `_get_stock_details`，让每个标的的策略标签来自实际的筛选结果。

#### 修复 R4: 龙头低吸mid_fallback

同R1修复，在strategy_defaults.py中添加参数后实盘自动读取。

### 5.2 P1级优化（提升实盘精度）

#### 修复 R5: 持仓天数精确计算

**文件**：`position_manager.py` Position.hold_days()  
**方案**：在async上下文中使用 `await mongo_manager.distinct()`，而非 `run_until_complete()`。因为 `daily_check()` 已经是async方法，可以在其中直接await计算持仓天数，而非在Position同步方法中计算。

建议将hold_days计算移到daily_check方法中：
```python
# 在daily_check中计算
trade_dates = await mongo_manager.distinct("stock_daily_ak_full", "trade_date", ...)
hold_days = max(0, len(trade_dates) - 1)
```

#### 修复 R6: 盘中T+1检查

**文件**：`daily_scheduler.py` run_intraday  
**改动**：在自动平仓循环中添加T+1检查：
```python
if hasattr(self.engine, '_t1_blocked') and f"{self.account_id}:{ts_code}" in self.engine._t1_blocked:
    continue
```

#### 修复 R7: 持仓市值更新

**文件**：`position_manager.py` daily_check + `paper_trading.py` _update_account_performance  
**方案**：在daily_check获取到current_price后，更新Position对象的current_price字段（可以用动态属性或扩展dataclass），然后_update_account_performance中使用更新后的价格。

#### 修复 R8: 买入价计算数据完整性

**文件**：`generate_daily_signals.py` _get_stock_details  
**改动**：在MongoDB projection中添加open/high/low/pre_close字段：
```python
projection={"ts_code": 1, "close": 1, "pct_chg": 1, "amount": 1, "volume": 1,
            "up_limit": 1, "down_limit": 1, "open": 1, "high": 1, "low": 1, "pre_close": 1}
```

#### 修复 R9: 统一策略ID映射

**文件**：`strategy_defaults.py`  
**改动**：添加统一映射导出：
```python
STRATEGY_NAME_ID_MAP = {cfg["name"]: sid for sid, cfg in STRATEGY_CONFIGS.items()}
STRATEGY_ID_NAME_MAP = {sid: cfg["name"] for sid, cfg in STRATEGY_CONFIGS.items()}
```
然后所有模块统一导入使用。

### 5.3 P2级优化（架构改进）

#### 优化 A: 实盘卖出逻辑统一调用SellSignalChecker

**核心问题**：实盘daily_check()自行实现了一套卖出检查逻辑，与回测SellSignalChecker是两套代码。  
**方案**：实盘daily_check()复用SellSignalChecker.check_early_sell()和check_full_sell()，传入持仓信息和行情数据，获取统一的卖出信号。这样回测卖出逻辑变更时实盘自动同步。

#### 优化 B: 将STRATEGY_PULLBACK_PARAMS合并到STRATEGY_CONFIGS

**核心问题**：冲高回落参数在两处定义（strategy_defaults.py的STRATEGY_CONFIGS.params 和 sell_signal_checker.py的STRATEGY_PULLBACK_PARAMS），容易不一致。  
**方案**：将STRATEGY_PULLBACK_PARAMS中的所有参数（pullback_high_threshold, pullback_mid_fallback_pct, pullback_profit_lock_threshold）移入各策略的params中，sell_signal_checker.py从strategy_defaults.py读取。

#### 优化 C: 数据持久化升级

**核心问题**：JSON文件持久化无事务保护、无并发安全。  
**方案**：迁移到MongoDB（已有mongo_manager），使用原子操作保证数据一致性。

---

## 六、各模块代码质量评估

| 模块 | 行数 | 参数来源 | 回测对齐度 | 代码质量 | 关键问题 |
|------|------|----------|-----------|---------|---------|
| paper_trading.py | ~320 | ✅ strategy_defaults | 🟡 中 | B | 跳空止损价格bug、T+1实现粗糙 |
| daily_scheduler.py | ~530 | ✅ strategy_defaults | ✅ 高 | A- | 持仓保护已对齐、数据维护完善 |
| position_manager.py | ~380 | ✅ strategy_defaults | 🟡 中 | B+ | 冲高回落参数fallback、策略映射硬编码 |
| performance_calculator.py | ~410 | N/A | N/A | A | 专业级指标计算，独立模块 |
| performance_analyzer.py | ~250 | N/A | N/A | A- | 回撤计算有简化，但不影响决策 |
| smart_reviewer.py | ~260 | N/A | N/A | B+ | 依赖numpy但规则简单 |
| generate_daily_signals.py | ~350 | ✅ strategy_defaults | 🔴 低 | B- | 策略分配粗糙、缺少跌停翘板、数据不完整 |

---

## 七、结论

### 已对齐的部分（V40-V53修复成果）

1. ✅ 核心风控参数（止损/止盈/持仓天数/滑点）已全部从strategy_defaults.py动态读取
2. ✅ 滑点规则（should_apply_slippage）已与回测SLIPPAGE_RULES对齐
3. ✅ 佣金/印花税计算与回测一致
4. ✅ 强制空仓逻辑复用回测_check_force_empty
5. ✅ 持仓保护（hold_protection_threshold）已对齐
6. ✅ 利润锁定信号已实现
7. ✅ 买入价尝试调用STRATEGY_BUY_PRICE

### 尚未对齐的关键差异

1. 🔴 龙头低吸冲高回落利润保护失效（pullback_profit_lock_threshold缺失）
2. 🔴 跳空止损卖出价错误（用stop_loss_price而非open）
3. 🔴 实盘策略标签分配与回测筛选条件完全不同
4. 🔴 龙头低吸冲高回落mid_fallback实盘0.01 vs 回测0.015
5. 🟡 持仓天数计算近似误差
6. 🟡 盘中T+1约束缺失
7. 🟡 持仓市值用buy_price

### 建议实施路线图

**第一阶段（1-2天）**：修复4个🔴P0级问题
- R1: strategy_defaults.py添加pullback_profit_lock_threshold和pullback_mid_fallback_pct
- R2: paper_trading.py跳空止损用open价格
- R3: generate_daily_signals.py使用stock_strategy_map分配策略标签
- R4: 同R1

**第二阶段（3-5天）**：修复🟡P1级问题 + 优化B（合并STRATEGY_PULLBACK_PARAMS）
- R5-R9修复
- 将STRATEGY_PULLBACK_PARAMS合并到STRATEGY_CONFIGS
- 统一策略ID映射

**第三阶段（1-2周）**：实施闭环反馈体系
- 优化A：实盘复用SellSignalChecker
- E2B-1：滑点校准
- B2E-2：信号预验证

---

*报告由审计Agent自动生成 | 2026-05-26*
