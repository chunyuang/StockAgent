# V60 实盘交易模块审查报告

**审查日期**: 2026-05-27
**审查范围**: real_trading/ 全部模块 + strategy_defaults.py + sell_signal_checker.py
**审查行数**: ~4800行 (position_manager 686 + auto_trade_executor 146 + daily_scheduler 972 + generate_daily_signals 568 + paper_trading 631 + smart_reviewer + pre_buy_risk_check + trade_gateway + realtime_monitor)
**审查重点**: 回测-实盘对齐、实盘特有逻辑、代码质量

---

## 一、审查总览

### 好消息
1. **V40-V59已修复大量对齐问题**: 止损止盈已从strategy_defaults读取(V40)、滑点规则已与SLIPPAGE_RULES对齐(V52)、冲高回落/利润锁定参数已对齐(V49/V55/V59)
2. **strategy_defaults.py单一来源已基本建立**: 实盘模块全部import STRATEGY_CONFIGS/GLOBAL_RISK，不再硬编码风控参数
3. **T+1约束已实现(V50)**: paper_trading.py有_t1_blocked集合，daily_settlement清除T+1锁
4. **持仓保护已对齐(V50)**: daily_scheduler._step_compute_rebalance读取hold_protection_threshold
5. **auto_trade_executor.py已标注废弃(V52)**: 明确指出调用不存在的buy()/sell()方法

### 仍需关注
1. _NAME_TO_ID映射在4个文件中重复定义(strategy_defaults已有STRATEGY_NAME_TO_ID)
2. pre_buy_risk_check.py中max_index_drop/daily_max_drawdown与strategy_defaults/GLOBAL_RISK的force_empty_index_drop_pct未对齐
3. generate_daily_signals.py未使用live_trading_mode开关(回测有，实盘缺失)
4. 实盘daily_check的卖出信号检查是内联实现，未复用sell_signal_checker.py
5. realtime_monitor.py使用akshare，但TOOLS.md记录的行情源是东方财富/量脉

---

## 二、问题清单

### P0 — 关键对齐缺失/逻辑错误

#### P0-1: pre_buy_risk_check.py 市场环境检查未接入真实数据源
**文件**: `real_trading/pre_buy_risk_check.py` L152-L168
**问题**: `_check_market_environment()`使用模拟数据`self.market_data.get(f"{index_code}_today_drop", 0.01)`，不是从MongoDB/东方财富获取真实指数跌幅。这意味着市场环境过滤形同虚设——永远返回"跌幅1%，安全"。
**对齐**: 回测`_check_force_empty()`从MongoDB读取上证指数/全市场涨跌停数据，实盘的风控检查应该用同样的数据源。
**修复建议**: 改为从MongoDB获取sh000001当日pct_chg，或复用回测的`_check_force_empty()`逻辑。
**影响**: 高——大盘暴跌时风控失效，可能在高风险环境下继续开仓。

#### P0-2: generate_daily_signals.py 未使用live_trading_mode因子降级
**文件**: `real_trading/generate_daily_signals.py`
**问题**: 回测引擎有`live_trading_mode`开关(GLOBAL_RISK["live_trading_mode"]=False)，当设为True时，pct_chg等T_close因子降级为_prev版本。但实盘信号生成器完全没有使用这个开关——它直接调用`self.backtester._build_strategy_filter_conditions()`，而该方法内部的pct_chk等因子使用不受live_trading_mode影响。
**对齐**: sell_signal_checker.py定义了FACTOR_AVAILABILITY和LIVE_DOWNGRADE_MAP，但实盘信号生成不经过这些降级。
**修复建议**: 在generate_signals()中设置`self.backtester._risk_config["live_trading_mode"] = True`，并在策略筛选阶段使用pct_chg_prev替代pct_chg。
**影响**: 高——半路追涨策略依赖pct_chg≥5%过滤，盘中信号生成时收盘价尚未确认，使用pct_chg是未来函数。

#### P0-3: position_manager.py daily_check卖出逻辑与sell_signal_checker不完全对齐
**文件**: `real_trading/position_manager.py` L370-L460
**问题**: daily_check中的卖出信号检查(冲高回落/利润保护/利润锁定/高开即卖)是内联if/elif链实现，与sell_signal_checker.py的SellSignal优先级队列不同:
1. **缺少首板打板的高开即卖检查**: daily_check中高开即卖只在`_strategy == '首板打板'`时触发(L431)，但回测sell_signal_checker的check_high_open_sell对所有策略都检查(V53已改为首板专用，但回测中只有首板打板策略注册了这个信号)——这里已对齐。
2. **冲高回落/利润保护/利润锁定的elif顺序不同**: 实盘用elif链(高开即卖→冲高回落→利润保护→利润锁定)，回测用优先级队列(冲高回落>利润保护>高开即卖)。虽然结果大体相同，但边界情况可能不一致。
3. **缺少跌停翘板/半路追涨的冲高回落差异参数**: 实盘从`_strategy_params`读取pullback_mid_fallback_pct，但如果策略未定义此参数则fallback到0.01，与回测STRATEGY_PULLBACK_PARAMS的跌停翘板0.015不同。
**修复建议**: 让daily_check复用sell_signal_checker.py的check_early_sell/check_full_sell方法，确保完全对齐。传入holding/market_data格式的参数即可。
**影响**: 中高——卖出信号优先级差异可能导致特定场景下卖出行为不一致。

### P1 — 重要但不紧急

#### P1-1: _NAME_TO_ID映射在4个文件中重复定义
**文件**: position_manager.py L240, paper_trading.py L206/L228/L310, generate_daily_signals.py L496, pre_buy_risk_check.py L518
**问题**: 每个文件各自构建`_NAME_TO_ID = {cfg["name"]: sid for sid, cfg in STRATEGY_CONFIGS.items()}`。strategy_defaults.py已提供STRATEGY_NAME_TO_ID，但实盘模块全部自己重建。
**风险**: 新增策略时如果忘记更新STRATEGY_CONFIGS但某个文件的映射逻辑有细微差异，可能导致策略名查找失败。
**修复建议**: 统一使用`from nodes.backtest_engine.strategy_defaults import STRATEGY_NAME_TO_ID`。

#### P1-2: pre_buy_risk_check.py max_index_drop与strategy_defaults force_empty_index_drop_pct未对齐
**文件**: pre_buy_risk_check.py L79 `"max_index_drop": 0.03`
**问题**: pre_buy_risk_check的max_index_drop=0.03与GLOBAL_RISK["force_empty_index_drop_pct"]=0.03值恰好相同，但参数来源不同——前者是硬编码默认值，后者从strategy_defaults读取。如果strategy_defaults修改了阈值，pre_buy_risk_check不会自动跟随。
**修复建议**: `from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK; self.config["max_index_drop"] = GLOBAL_RISK.get("force_empty_index_drop_pct", 0.03)`

#### P1-3: daily_scheduler.py 止损卖出价逻辑与回测不完全一致
**文件**: `real_trading/paper_trading.py` L378-L397
**问题**: daily_settlement中止损时卖出价取pos.stop_loss_price，跳空止损也取stop_loss_price(而非open)。回测中跳空止损以open价卖出。
```python
if "跳空止损" in str(alert.get("alerts", [])):
    sell_price = pos.stop_loss_price  # ❌ 应该用open
    reason = "跳空止损"
```
V47注释说"跳空止损用open"，但代码实际用stop_loss_price。
**修复建议**: 跳空止损时，sell_price应取alert中的open价(需要daily_check在alert中传递open_price)。
**影响**: 中——跳空低开时stop_loss_price>open_price，实际亏损比回测大。

#### P1-4: generate_daily_signals.py 买入价计算未覆盖首板打板
**文件**: `real_trading/generate_daily_signals.py` L486-L494
**问题**: _generate_trading_plan中，首板打板策略使用`stock['close'] * 1.01`作为买入价估算。但回测的首板打板买入价依赖_get_limit_up_price(委托价=涨停价)，两者差异显著。
**修复建议**: 首板打板买入价应使用up_limit价(已在stock_details中获取)，而非close*1.01。

#### P1-5: realtime_monitor.py 使用akshare但TOOLS.md标注东方财富为主力数据源
**文件**: `real_trading/realtime_monitor.py` L18 `import akshare as ak`
**问题**: TOOLS.md明确记录东方财富API为主力数据源(无限流、3秒/次)，akshare已不再是推荐数据源。realtime_monitor仍然依赖akshare。
**修复建议**: 盘中实时监控应改用东方财富实时行情接口或量脉1min K线(仅盘中使用)。

#### P1-6: position_manager.py hold_days()在async上下文中的近似计算不够精确
**文件**: `real_trading/position_manager.py` L88-L95
**问题**: 当在async上下文中调用hold_days()时，使用`int(natural_days / 1.5)`近似。但回测引擎使用精确的交易日历(MongoDB trade_date去重)。
**影响**: 周五买入→周一，实际1个交易日，但natural_days/1.5=1.33→int=1。而如果周四买入→周一，natural_days=4/1.5=2.67→int=2，实际2个交易日。看起来近似尚可，但遇到长假(如国庆7天/1.5=4.67→int=4，实际仅1个交易日)误差很大。
**修复建议**: 在daily_check中传入current_date参数，并预先批量查询交易日历，避免逐只查询MongoDB。

### P2 — 代码质量/优化建议

#### P2-1: auto_trade_executor.py 已废弃但仍保留
**文件**: `real_trading/auto_trade_executor.py`
**问题**: V52已标注废弃("调用PaperTradingEngine已不存在的buy()/sell()方法")，但仍保留在代码库中。
**修复建议**: 移入backups/目录或添加deprecation warning。

#### P2-2: sys.path.insert反模式
**文件**: 所有real_trading/*.py
**问题**: 每个文件都有`sys.path.insert(0, ...)`做模块查找，注释也标注了FIXME。
**修复建议**: 使用pyproject.toml安装项目到venv，消除所有sys.path.insert。

#### P2-3: paper_trading.py _t1_blocked实现不够健壮
**文件**: `real_trading/paper_trading.py` L262-L268
**问题**: _t1_blocked用`set()`存储"{account_id}:{ts_code}"格式字符串，而非按account_id分组。如果有多个账户，clear()会清除所有账户的T+1锁定。
**修复建议**: 改为`Dict[str, Set[str]]`格式，按account_id分组管理。

#### P2-4: smart_reviewer.py 使用numpy但未在依赖中声明
**文件**: `real_trading/smart_reviewer.py` L13 `import numpy as np`
**问题**: numpy仅用于np.mean()一个调用，可以用sum()/len()替代。
**修复建议**: 移除numpy依赖，改用Python内置计算。

#### P2-5: generate_daily_signals.py _get_strategy_for_stock逻辑过于简化
**文件**: `real_trading/generate_daily_signals.py` L411-L432
**问题**: 策略判断仅基于pct_chg+涨停板关系，与回测引擎的多因子筛选条件(量比/换手率/回调幅度等)完全不同。这意味着同一只股票在回测中可能被分类为"龙头低吸"，但实盘中可能被分类为"半路追涨"或"首板打板"。
**修复建议**: 使用factor_df中已计算的策略分类结果(来自filter_stocks_by_strategies)，而非重新用简单规则判断。

#### P2-6: trade_gateway.py SimulatedGateway滑点未扣
**文件**: `real_trading/trade_gateway.py` L155-L170
**问题**: SimulatedGateway.place_order不扣滑点(注释"100%模拟成交，无滑点")，但PaperTradingEngine.place_order扣滑点。两个模块对同一交易的模拟结果不同。
**修复建议**: SimulatedGateway应与PaperTradingEngine保持一致，扣取策略级滑点。

#### P2-7: daily_scheduler.py 缺少intraday_phase的自动止盈止损执行
**文件**: `real_trading/daily_scheduler.py` L317-L385
**问题**: run_intraday中只处理danger级别告警(止损/超期/冲高回落)，不处理success级别(止盈/利润保护/利润锁定)。这意味着盘中止盈不会自动执行，要等到盘后daily_settlement。
**修复建议**: 将success级别的止盈/利润保护也纳入盘中自动平仓逻辑。

#### P2-8: pre_buy_risk_check.py _check_stock_risk使用模拟数据
**文件**: `real_trading/pre_buy_risk_check.py` L324-L332
**问题**: 个股风控检查(市值/波动率)使用模拟数据`self.stock_risk_cache.get(ts_code, {"market_cap": 50, "volatility_20d": 0.15})`，不查询MongoDB真实数据。
**修复建议**: 从stock_daily_ak_full/daily_basic获取真实市值和波动率。

---

## 三、回测-实盘对齐检查清单

| # | 检查项 | 回测来源 | 实盘来源 | 是否对齐 | 备注 |
|---|--------|---------|---------|---------|------|
| 1 | 止损止盈参数 | STRATEGY_CONFIGS.riskParams | STRATEGY_CONFIGS.riskParams (V40修复) | ✅ | 单一来源 |
| 2 | 最大持仓天数 | STRATEGY_CONFIGS.riskParams | STRATEGY_CONFIGS.riskParams | ✅ | 单一来源 |
| 3 | 买入价计算 | STRATEGY_BUY_PRICE注册表 | generate_daily_signals部分使用 | ⚠️ | 首板打板未对齐(P1-4) |
| 4 | 卖出信号优先级 | SellSignal优先级队列 | daily_check elif链 | ⚠️ | 边界情况可能不一致(P0-3) |
| 5 | 滑点规则 | SLIPPAGE_RULES表 | should_apply_slippage() (V52修复) | ✅ | 单一来源 |
| 6 | 冲高回落参数 | STRATEGY_PULLBACK_PARAMS | _strategy_params读取 | ⚠️ | 缺失参数时fallback可能不一致(P0-3) |
| 7 | T+1约束 | PositionManager.t1_blocked | paper_trading._t1_blocked | ✅ | V50已实现 |
| 8 | 持仓保护阈值 | hold_protection_threshold | GLOBAL_RISK读取 | ✅ | V50已实现 |
| 9 | 强制空仓 | _check_force_empty(MongoDB) | pre_buy_risk_check(模拟数据) | ❌ | P0-1:实盘未接入真实数据 |
| 10 | 情绪周期 | _get_sentiment_cycle | generate_daily_signals复用backtester | ✅ | 同一代码路径 |
| 11 | 因子降级(live_trading_mode) | FACTOR_AVAILABILITY+LIVE_DOWNGRADE_MAP | 未使用 | ❌ | P0-2:实盘未启用因子降级 |
| 12 | 策略筛选条件 | _build_strategy_filter_conditions | 复用backtester方法 | ✅ | 同一代码路径 |
| 13 | 跳空止损卖出价 | open价 | stop_loss_price | ❌ | P1-3:代码与注释不一致 |
| 14 | 盘中利润锁定参数 | GLOBAL_RISK读取 | GLOBAL_RISK+策略级覆盖 | ✅ | V58/V59已对齐 |
| 15 | 单票最大仓位 | max_position_per_stock=0.35 | GLOBAL_RISK读取 | ✅ | |
| 16 | 总仓位上限 | max_total_position=0.7 | GLOBAL_RISK读取 | ✅ | |
| 17 | 策略名称映射 | STRATEGY_NAME_TO_ID | 各文件自建_NAME_TO_ID | ⚠️ | P1-1:重复定义 |
| 18 | 竞价过滤阈值 | 排除>7%/<-5% | -5%~7%与回测一致 | ✅ | V37已修复 |
| 19 | 追踪止损(trailing_stop_pct) | STRATEGY_CONFIGS.riskParams | 未实现 | ❌ | 实盘无追踪止损逻辑 |
| 20 | 涨跌停板买入限制 | hit_probability模拟 | 未实现 | ⚠️ | 实盘无法模拟打板成交概率 |

---

## 四、实盘-回测相互助力建议

### A. 回测→实盘(参数同步)
1. **自动参数同步**: 当前回测发现最优参数后需手动更新strategy_defaults.py，实盘自动读取。这个链路已打通，但建议增加参数变更审计日志——每次strategy_defaults.py的参数修改记录commit hash和验证结果。
2. **回测结果驱动实盘开关**: 回测验证某策略参数显著改善后，应自动启用实盘的对应策略。当前需要手动操作。

### B. 实盘→回测(反馈优化)
1. **实盘止损止盈结果反馈到回测**: 当前实盘的止损止盈记录(trade_history.json)未自动反馈到回测验证。建议定期将实盘交易记录导入回测引擎，对比回测vs实盘的盈亏差异，识别参数过拟合。
2. **实盘滑点实测值反馈**: 实盘的成交价vs委托价偏差应记录，反馈到回测的slippage_pct参数校准。当前滑点参数(0.2%/0.5%)是经验值，未用实盘数据验证。
3. **盘中执行偏差记录**: 实盘中信号触发到实际成交的时间延迟、价格偏差应记录，用于校准回测的买入价计算函数。

### C. 建议新增的反馈闭环
1. **周度实盘vs回测对账**: 每周自动运行，对比同一信号在回测和实盘中的交易结果差异，识别对齐偏差。
2. **参数漂移检测**: 监控strategy_defaults.py参数修改频率，过于频繁则告警(可能过度优化)。

---

## 五、可直接执行的代码修改

### 修改1: 统一使用STRATEGY_NAME_TO_ID (P1-1)
**影响范围**: position_manager.py, paper_trading.py, generate_daily_signals.py, pre_buy_risk_check.py
**对回测的影响**: 无

#### position_manager.py L240
```python
# 旧: _NAME_TO_ID = {cfg["name"]: sid for sid, cfg in STRATEGY_CONFIGS.items()}
# 新:
from nodes.backtest_engine.strategy_defaults import STRATEGY_NAME_TO_ID as _NAME_TO_ID
```

#### paper_trading.py L206/L228/L310
```python
# 同上: 统一使用STRATEGY_NAME_TO_ID
from nodes.backtest_engine.strategy_defaults import STRATEGY_NAME_TO_ID as _NAME_TO_ID
```

#### generate_daily_signals.py L496
```python
# 同上
from nodes.backtest_engine.strategy_defaults import STRATEGY_NAME_TO_ID as _NAME_TO_ID
```

#### pre_buy_risk_check.py L518
```python
# 同上
from nodes.backtest_engine.strategy_defaults import STRATEGY_NAME_TO_ID as _NAME_TO_ID
```

### 修改2: pre_buy_risk_check.py 从strategy_defaults读取市场风控参数 (P1-2)
**影响范围**: pre_buy_risk_check.py
**对回测的影响**: 无

```python
# pre_buy_risk_check.py __init__中
# 旧:
self.default_config = {
    "max_index_drop": 0.03,
    ...
}

# 新:
from nodes.backtest_engine.strategy_defaults import GLOBAL_RISK as _GR
self.default_config = {
    "max_index_drop": _GR.get("force_empty_index_drop_pct", 0.03),
    "daily_max_drawdown": _GR.get("stop_loss_pct", 0.03),  # 与最大止损对齐
    ...
}
```

### 修改3: paper_trading.py 跳空止损卖出价修复 (P1-3)
**影响范围**: paper_trading.py daily_settlement
**对回测的影响**: 无(修复对齐)

```python
# paper_trading.py daily_settlement L390-395
# 旧:
if "跳空止损" in str(alert.get("alerts", [])):
    sell_price = pos.stop_loss_price  # ❌ 应该用open
    reason = "跳空止损"

# 新:
if "跳空止损" in str(alert.get("alerts", [])):
    open_p = alert.get("open", 0)
    sell_price = open_p if open_p > 0 else pos.stop_loss_price  # ✅ 跳空用open
    reason = "跳空止损"
```

**前置条件**: position_manager.py daily_check需要在alert中传递open_price:
```python
# position_manager.py daily_check alert构建中添加:
alert["open"] = open_p  # 传递开盘价给上层使用
```

### 修改4: generate_daily_signals.py 首板打板买入价修复 (P1-4)
**影响范围**: generate_daily_signals.py _generate_trading_plan
**对回测的影响**: 无

```python
# generate_daily_signals.py _generate_trading_plan L486-494
# 旧:
_calc = STRATEGY_BUY_PRICE.get(strategy_name)
if _calc and _calc.__name__ != 'calc_buy_price_first_limit_up':
    buy_price = _calc(...)
else:
    buy_price = stock['close'] * 1.01  # 打板策略fallback

# 新:
_calc = STRATEGY_BUY_PRICE.get(strategy_name)
if _calc and _calc.__name__ != 'calc_buy_price_first_limit_up':
    buy_price = _calc(...)
elif strategy_name == '首板打板':
    up_limit = stock.get('up_limit', 0)
    buy_price = up_limit if up_limit > 0 else stock['close'] * 1.01  # 打板用涨停价
else:
    buy_price = stock['close'] * 1.01  # 其他fallback
```

### 修改5: generate_daily_signals.py 启用live_trading_mode (P0-2)
**影响范围**: generate_daily_signals.py RealTradingSignalGenerator.__init__
**对回测的影响**: 无(只影响实盘信号生成)

```python
# generate_daily_signals.py RealTradingSignalGenerator.__init__中
# 在self.backtester._risk_config赋值块之后添加:
self.backtester._risk_config["live_trading_mode"] = True  # 实盘模式:pct_chg降级为_prev
```

**注意**: 这只是第一步——完整的因子降级还需要在_build_strategy_filter_conditions中检查live_trading_mode开关，对pct_chg等T_close因子使用_prev替代。这个改动涉及回测引擎代码，需要更谨慎地评估。

### 修改6: position_manager.py daily_check alert中传递open_price (修改3的前置)
**影响范围**: position_manager.py daily_check
**对回测的影响**: 无

```python
# position_manager.py daily_check alert构建中(已有open_p变量):
# 在alert字典中添加:
alert["open"] = open_p  # 传递开盘价给上层使用(paper_trading跳空止损需要)
```

---

## 六、审查统计

| 级别 | 数量 | 关键项 |
|------|------|--------|
| P0 | 3 | 强制空仓未接入真实数据、live_trading_mode未启用、卖出信号elif链vs优先级队列 |
| P1 | 6 | _NAME_TO_ID重复、max_index_drop未对齐、跳空止损卖出价、首板打板买入价、akshare数据源、hold_days近似 |
| P2 | 8 | 废弃代码、sys.path反模式、_t1_blocked健壮性、numpy依赖、策略分类简化、SimulatedGateway滑点、盘中止盈未执行、个股风控模拟数据 |

**对齐检查**: 20项中 ✅12项 / ⚠️4项 / ❌4项

**最紧急修复**: P0-1(强制空仓) > P0-2(因子降级) > P0-3(卖出信号对齐) > P1-3(跳空止损价)

---

*报告生成时间: 2026-05-27 02:46*
*代码修改已应用: 2026-05-27 02:53*

---

## 七、已应用的代码修改

### 已应用: P1-1 统一使用STRATEGY_NAME_TO_ID
- **position_manager.py L240**: `_NAME_TO_ID` → `STRATEGY_NAME_TO_ID`
- **paper_trading.py L206/L228/L310**: 3处 `_NAME_TO_ID` → `STRATEGY_NAME_TO_ID`
- **generate_daily_signals.py L496**: `_NAME_TO_ID` → `STRATEGY_NAME_TO_ID`
- **pre_buy_risk_check.py L518**: `_NAME_TO_ID` 移除,import更新

### 已应用: P1-2 pre_buy_risk_check.py 从strategy_defaults读取市场风控参数
- `max_index_drop` 从 `GLOBAL_RISK["force_empty_index_drop_pct"]` 读取
- `daily_max_drawdown` 从 `GLOBAL_RISK["stop_loss_pct"]` 读取

### 已应用: P1-3 paper_trading.py 跳空止损卖出价修复
- 跳空止损时: `sell_price = open_p if open_p > 0 else pos.stop_loss_price` (原先错误使用stop_loss_price)
- 前置修改: position_manager.py daily_check alert中传递`open`字段

### 已应用: P1-4 generate_daily_signals.py 首板打板买入价修复
- 首板打板买入价: `up_limit if up_limit > 0 else stock['close'] * 1.01` (原先使用close*1.01)

### 未应用(需更谨慎评估):
- **P0-1**: pre_buy_risk_check市场环境检查接入真实数据源 — 需要修改_check_market_environment实现,影响较大
- **P0-2**: live_trading_mode因子降级 — 需要回测引擎配合修改,跨模块影响
- **P0-3**: daily_check复用sell_signal_checker — 重构较大,需要充分测试
- **P1-5**: realtime_monitor改用东方财富API — 涉及数据源切换
- **P2-7**: 盘中止盈自动平仓 — 逻辑变更需充分验证
