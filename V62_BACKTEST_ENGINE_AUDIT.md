# V62 回测引擎深度审计报告

**审计日期**: 2026-05-27  
**审计范围**: portfolio_backtest.py (4569行) / sell_signal_checker.py (873行) / strategy_defaults.py (207行)  
**基线结果**: total_return=417.01%, max_drawdown=6.40%, sharpe=11.53, win_rate=81.25%, trades=96

---

## P0: 影响回测结果正确性的Bug

### P0-1: `max_total_position` (总仓位上限70%) 定义但从未执行

**文件**: strategy_defaults.py L22 / portfolio_backtest.py  
**问题**: `GLOBAL_RISK` 定义了 `"max_total_position": 0.7` (总仓位上限70%),但整个 `portfolio_backtest.py` 中没有任何代码读取或执行此限制。`_rebalance` 方法中只检查了 `max_position_per_stock` (单票仓位35%),但买入循环没有检查所有买入后总仓位是否超过70%。  
**影响**: 实际运行中,3月28日6只重仓股同日暴跌的根因就是仓位过度集中。如果总仓位上限70%被正确执行,单日最多持仓70%而非可能接近100%,最大回撤会被显著降低。  
**建议修复**: 在 `_rebalance` 买入循环中,每次买入前计算当前总持仓占比,如果 `cash / (cash + holdings_value) < 1 - max_total_position` 则跳过或缩减买入:
```python
# 在买入循环中,买入前检查:
max_total_pos = self._risk_config.get('max_total_position', 0.7)
current_total = cash + sum(shares * prices[code]['close'] for code, shares in holdings.items() if code in prices)
current_position = 1 - cash / current_total if current_total > 0 else 0
if current_position + delta * buy_price_adj / current_total > max_total_pos:
    # 缩减或跳过买入
```

### P0-2: `check_full_sell` 止盈取min与`_get_sl_tp_for_code`止盈取strategies[0]不一致

**文件**: sell_signal_checker.py L671-689 / portfolio_backtest.py L3813-3830  
**问题**: `SellSignalChecker.get_sl_tp_for_strategies()` 对止盈取 `min(所有策略)` (最严格),而 `portfolio_backtest._get_sl_tp_for_code()` 对止盈取 `strategies[0]` (买入策略)。两者语义矛盾。  
虽然 `check_full_sell` 标注为 DEPRECATED,但代码仍然存在且可被调用,如果有人误用会导致止盈线偏低。  
**影响**: 当龙头低吸(TP=30%)和跌停翘板(TP=20%)同选一股时:
- `_get_sl_tp_for_code` → TP=30% (取strategies[0]=龙头低吸)
- `get_sl_tp_for_strategies` → TP=20% (取min)  
止盈线差10%,可能导致过早止盈或过晚止盈。  
**建议修复**: 统一为 `strategies[0]` (买入策略TP),在 `get_sl_tp_for_strategies` 中也改为取第一个策略的TP,或添加注释明确说明差异原因。

### P0-3: `apply_slippage` 方法中策略级滑点逻辑未完成

**文件**: sell_signal_checker.py L641-657  
**问题**: `apply_slippage()` 方法中,当 `code` 参数非空时,有一段注释说要获取策略级滑点,但实际代码块为空——只有注释没有逻辑,直接 `return fallback_slippage`。  
```python
if code:
    strategies = self._strategy_risk_params  # 简化:外部可传入
    # 这里需要stock_to_strategy映射,由调用方提供
    # 如果不提供,使用全局滑点
return fallback_slippage if fallback_slippage is not None else self._global_slippage
```
**影响**: 当前 `portfolio_backtest.py` 中**未调用**此方法(改用 `should_apply_slippage()` + `_get_slippage_for_code()` 的组合),所以实际不生效。但如果将来有人使用 `apply_slippage()` 代替当前逻辑,策略级滑点(首板打板0.5%/跌停翘板0.3%)会被忽略,全部使用全局0.2%滑点,导致回测结果偏差。  
**建议修复**: 要么完善此方法的策略级滑点逻辑,要么删除此方法并在文档中说明应使用 `should_apply_slippage()` + `_get_slippage_for_code()` 组合。

### P0-4: 强制空仓恢复后无冷却期

**文件**: portfolio_backtest.py L1071-1612  
**问题**: 强制空仓触发后,次日如果涨跌停数恢复正常,引擎立即恢复全仓位买入。但在实际极端行情中,暴跌次日往往是反弹+继续下跌的混合状态,立即满仓可能遭遇二次暴跌。  
例如: Day1 跌停150只→强制空仓,Day2 跌停30只→不触发空仓→正常调仓→Day3 再次暴跌。  
**影响**: 3月28日-34.5%单日回撤后,如果有冷却期限制(如强制空仓后2-3天内仓位上限50%),可以在二次暴跌中减少损失。  
**建议修复**: 在 `_risk_config` 中添加 `force_empty_cooldown_days: 2`,强制空仓后N天内 `position_multiplier` 上限为0.5。

### P0-5: `_sell_code_details` 中T+1限制的股票卖出价设为None,后续可能被当作有效价格

**文件**: portfolio_backtest.py L4006  
**问题**: `_sell_code_details` 中,T+1限制的股票被标记为 `(None, '调仓卖出')`。后续在 `pos_mgr.mark_sold()` 时会传入这个 `best_reason`,但 `best_price` 是 `None`。虽然 `pos_mgr.mark_sold` 不直接使用价格,卖出循环中通过 `resolve_sell_price_and_reason` 重新计算价格,但如果代码逻辑变更可能导致 `None` 价格被使用。  
**影响**: 当前不影响结果(卖出循环有兜底逻辑),但代码脆弱,后续修改容易引入bug。  
**建议修复**: 将T+1限制的股票从 `_sell_code_details` 中排除,或用 `(0, 'T+1限制')` 明确标记。

---

## P1: 影响回测效率或稳定性的问题

### P1-1: `_rebalance` 方法超过500行,可读性极差

**文件**: portfolio_backtest.py L3935-4570  
**问题**: `_rebalance` 方法含卖出决策、买入决策、减仓、T+1、持仓保护、超时强卖、停牌处理等7个逻辑段,总计530+行。虽然注释说明"不可拆分",但实际上已有多个子方法(`_calc_total_value`, `_calc_position_multiplier`, `_apply_limit_up_hit_probability`),说明拆分是可行的。  
**影响**: 代码审查困难,bug修复容易引入新bug(已有20+轮修复历史),新人无法理解。  
**建议修复**: 将卖出决策(含止损/冲高回落)、买入决策、减仓逻辑分别提取为 `_rebalance_sell_phase`, `_rebalance_buy_phase`, `_rebalance_reduce_phase`。

### P1-2: 非调仓日强卖检查每天查询全市场5万条聚合统计

**文件**: portfolio_backtest.py L563-641 ( `_print_market_environment` )  
**问题**: `_print_market_environment` 使用MongoDB聚合管道统计涨跌停数,每次查询约5万条数据。调仓日必须调用,但非调仓日通过缓存跳过。然而缓存只在调仓日设置(`_cached_sentiment_level`等),如果连续2天非调仓日,第2天仍然使用第1天调仓日的缓存。  
**影响**: 非调仓日的强制空仓判断基于可能过期的缓存(最多滞后1天),可能错过非调仓日的极端行情触发。  
**建议修复**: 非调仓日也应检查是否需要更新缓存,或者将涨跌停统计改为轻量查询(只count,不聚合其他字段)。

### P1-3: 首板打板成交概率使用MD5 hash模拟随机性,不同运行可能结果不同

**文件**: portfolio_backtest.py L3908-3958  
**问题**: `seed_str = f"{code}_{trade_date}"` 用MD5 hash模拟成交概率。虽然同一seed始终产生相同结果(确定性),但如果代码中其他地方也使用类似的hash逻辑,或者有人修改了hash算法,可能导致回测结果不可复现。  
**影响**: 当前可复现,但依赖hash函数的稳定性。  
**建议修复**: 使用更明确的伪随机数生成方式,如 `random.Random(seed).random()`,避免依赖hash碰撞的统计均匀性。

### P1-4: 止盈/止损检查在 `_rebalance` 和 `_check_and_execute_forced_sells` 中逻辑重复

**文件**: portfolio_backtest.py L4050-4105 / L265-410  
**问题**: 调仓日的止损/止盈/冲高回落检查在 `_rebalance` 中内联执行(约100行),非调仓日通过 `_check_and_execute_forced_sells` 执行。两处逻辑虽然目标一致,但实现细节不同:
- `_rebalance` 中冲高回落检查使用 `_check_early_sell_signals` + 手动止损判断
- `_check_and_execute_forced_sells` 也调用 `_check_early_sell_signals` + 手动止损判断,但顺序和边界处理略有差异  
**影响**: 维护成本高,两处修改容易遗漏,历史bug多次因不同步导致。  
**建议修复**: 将调仓日的SL/TP/冲高回落也委托给 `_check_and_execute_forced_sells`,统一入口。

### P1-5: 利润锁定参数来源链过长,三个层级(GLOBAL_RISK → risk_config → 策略级)

**文件**: portfolio_backtest.py L220-245 / sell_signal_checker.py L325-350  
**问题**: `_check_intraday_profit_lock` 中参数读取链:
1. `self._risk_config.get('intraday_lock_min_high_rise', GLOBAL_RISK.get(...))` 
2. 如果有 `code`,进一步从 `STRATEGY_PULLBACK_PARAMS` + `_strategy_risk_params` 合并覆盖
3. `sell_signal_checker.check_intraday_profit_lock` 也有自己的参数读取逻辑  
两个方法对同一参数的读取路径不同,可能导致同一股票在两个方法中得到不同的利润锁定参数。  
**影响**: 代码审查发现 `_check_intraday_profit_lock` (portfolio_backtest.py L194) 和 `check_intraday_profit_lock` (sell_signal_checker.py L297) 都会检查利润锁定,但参数可能不同。  
**建议修复**: 统一参数读取为单一方法,如 `_get_intraday_lock_params(code)`,返回 `(min_high_rise, pullback_pct, min_profit)`。

### P1-6: `strategy_defaults.py` 中 `max_position_per_stock=0.35` 但 `risk_config` 默认值为1.0

**文件**: strategy_defaults.py L21 / portfolio_backtest.py L1134  
**问题**: `GLOBAL_RISK.max_position_per_stock=0.35`,但 `_init_run_config` 中 `risk_config["max_position_per_stock"] = config.get("max_position_per_stock", config.get("max_position_percent", 1.0))`,默认值是1.0而非0.35。如果前端不传此参数,单票仓位上限=100%,远超GLOBAL_RISK的35%。  
**影响**: 某些回测场景下单票仓位可能超过35%,与预期不符。  
**建议修复**: 将默认值改为 `GLOBAL_RISK.get("max_position_per_stock", 0.35)`:
```python
"max_position_per_stock": config.get("max_position_per_stock", GLOBAL_RISK.get("max_position_per_stock", 0.35))
```

### P1-7: 每日价格缓存 `_daily_price_cache` 在跨日时只在新日期清空,但如果 `_get_prices` 在同一日被调用两次且第二次股票列表不同,缺失的股票会触发额外查询

**文件**: portfolio_backtest.py L4400-4480  
**问题**: 每日价格缓存的命中逻辑是"如果缓存中已有该股票则不查询"。但如果同一天内第一次查了10只,第二次查另外5只(其中3只已缓存),则只查2只。这个行为是正确的,但如果缓存和数据库数据不一致(极端情况),可能返回混合来源的数据。  
**影响**: 极低,当前逻辑正确。仅标注为潜在风险。

### P1-8: `_build_run_result` 中 `strategy_results` 对同一策略重复计算 `total_return`

**文件**: portfolio_backtest.py L3065-3070  
**问题**: 零交易策略的结果中,`"total_return": 0` 被写了两次:
```python
strategy_results[sname] = {
    "strategy_name": sname,
    "win_rate": 0, "total_return": 0,
    "trades_count": 0, "total_return": 0,  # 重复key
    "warning": warning,
}
```
**影响**: 功能上无影响(Python字典后值覆盖前值,都是0),但代码不规范,可能是复制粘贴错误。  
**建议修复**: 删除重复的 `"total_return": 0`。

---

## P2: 代码质量和可维护性问题

### P2-1: `_get_sl_tp_for_code` 方法被定义了两次(代码重复)

**文件**: portfolio_backtest.py L3813 和 L3760 (两处完全相同的方法定义)  
**问题**: `_get_sl_tp_for_code` 方法在文件中出现了两次,代码完全相同。Python类中后定义的会覆盖先定义的,所以功能不受影响,但这是明显的代码重复/遗漏。  
**建议修复**: 删除其中一个定义,保留一个即可。

### P2-2: `_get_slippage_for_code` 方法也被定义了两次

**文件**: portfolio_backtest.py L3836 和 L3789  
**问题**: 与P2-1相同,方法重复定义。  
**建议修复**: 删除重复定义。

### P2-3: `sell_signal_checker.py` 中 `check_early_sell` 不传入 `high_price`,导致利润锁定信号在此入口不可用

**文件**: sell_signal_checker.py L509-538  
**问题**: `check_early_sell` 的 `market_data` 只包含 `open` 和 `close`,不包含 `high`。因此 `check_intraday_profit_lock` (需要 `high_price`) 在 `check_early_sell` 路径中永远不会触发。  
这是设计意图(利润锁定只在 `check_full_sell` 和 `_check_and_execute_forced_sells` 中检查),但注释不够清晰,容易误导。  
**建议修复**: 在 `check_early_sell` 的docstring中明确说明不包含利润锁定信号,如需利润锁定请使用 `_check_and_execute_forced_sells`。

### P2-4: `STRATEGY_CONFIGS` 中首板打板 `hit_probability_slow` 与 `_apply_limit_up_hit_probability` 中的fallback值不一致

**文件**: strategy_defaults.py L87 / portfolio_backtest.py L3920-3924  
**问题**: `STRATEGY_CONFIGS.first_limit_up.params.hit_probability_slow=0.50`,但 `_apply_limit_up_hit_probability` 中的fallback链:
```python
sp = self._strategy_params.get('首板打板', {})
_first_limit_defaults = STRATEGY_CONFIGS.get('first_limit_up', {}).get('params', {})
hit_prob_slow = sp.get('hit_probability_slow', _first_limit_defaults.get('hit_probability_slow', 0.45))
```
最终fallback是0.45而非0.50。虽然正常流程中 `_strategy_params` 会包含正确值,但如果参数缺失,会fallback到0.45,与STRATEGY_CONFIGS中的0.50不一致。  
**建议修复**: 将fallback值统一为0.50,或直接去掉fallback(依赖strategy_defaults的完整性)。

### P2-5: `portfolio_backtest.py` 中 `from datetime import datetime as dt_now` 在文件顶部,但注释说"避免局部import导致UnboundLocalError"

**文件**: portfolio_backtest.py L14  
**问题**: 这个import别名 `dt_now` 命名不当,它实际是 `datetime` 类,用于 `dt_now.strptime()`,但名称暗示是当前时间。  
**建议修复**: 改为 `from datetime import datetime as datetime_cls` 或直接 `import datetime`,使用 `datetime.datetime.strptime()`。

### P2-6: `_compute_weights` 中 `import math` 在方法内部

**文件**: portfolio_backtest.py L4278  
**问题**: `import math` 在方法内部执行,每次调用 `_compute_weights` 都会执行一次import(虽然Python有缓存,但不规范)。  
**建议修复**: 将 `import math` 移到文件顶部。

### P2-7: `strategy_defaults.py` 中 `ALL_STRATEGIES` 列表在模块加载时构建,如果STRATEGY_CONFIGS被动态修改,ALL_STRATEGIES不会更新

**文件**: strategy_defaults.py L100-107  
**问题**: `ALL_STRATEGIES` 是在模块加载时一次性构建的,不会响应 `STRATEGY_CONFIGS` 的后续修改。  
**影响**: 极低(STRATEGY_CONFIGS目前不被动态修改),但设计上不够健壮。  
**建议修复**: 改为函数 `def get_all_strategies(): return [...]`,或添加注释说明是静态快照。

### P2-8: 回测引擎缺少幸存者偏差过滤

**文件**: portfolio_backtest.py (全局)  
**问题**: 股票池 (`universe`) 没有排除已退市股票。在回测2025Q1时,如果某股票在2025年3月退市,它仍然会出现在1-2月的股票池中,但如果它因为退市停牌,后续无法卖出,可能导致净值虚高或虚低。  
**影响**: 对超短线回测(持仓3-7天)影响较小,因为退市前通常有风险提示期。但长期看可能导致选股池偏高(退市股通常表现差,但已被排除在当前池外)。  
**建议修复**: 在 `UniverseManager` 中添加退市股票过滤(根据 `stock_basic` 表的 `list_status` 字段)。

### P2-9: `_sell_code_details` 中 `best_price > best_price` 比较逻辑可能选错卖出价

**文件**: portfolio_backtest.py L4030-4044  
**问题**: 对不在目标池的股票,代码比较不同卖出信号的卖出价,选"更优"价格(`if early_sell_price > best_price`)。但"更优"的定义应该是:对卖出方来说,价格越高越优。然而止损价(cost*(1-SL))通常低于close价,所以止损价永远不会被选为"更优"——这与预期矛盾(止损应该在跌破时触发,不管close价多高)。  
实际上代码逻辑是:先默认 `best_price = close_p`,然后如果冲高回落open价 > close价则选open,如果止损价 > close价则选止损价,如果止盈价 > close价则选止盈价。这个逻辑在大多数场景下正确,但当close价远低于止损价时(如跳空低开),止损价可能高于close价,但此时应该用open价(跳空止损),而不是止损价。  
**影响**: 当前代码中,跳空止损的情况(open<=stop_price)已经在上方 `_check_and_execute_forced_sells` 中处理了,在 `_rebalance` 的 `_sell_code_details` 中没有处理跳空止损场景。但由于 `_rebalance` 中后续卖出循环会再次检查止损,所以最终结果是正确的——只是 `_sell_code_details` 记录的原因可能不准确。  
**建议修复**: 在 `_sell_code_details` 中也加入跳空止损的判断逻辑,与 `_check_and_execute_forced_sells` 保持一致。

---

## 审计总结

| 级别 | 数量 | 关键发现 |
|------|------|---------|
| P0 | 5 | max_total_position从未执行(最严重)、止盈参数不一致、apply_slippage未完成、强制空仓无冷却期、None价格风险 |
| P1 | 8 | _rebalance 500+行不可维护、非调仓日缓存滞后、首板hash随机性、SL/TP逻辑重复、利润锁定参数链过长、max_position_per_stock默认值1.0 |
| P2 | 9 | 方法重复定义、参数fallback不一致、import命名、幸存者偏差 |

### 最高优先级修复建议

1. **P0-1**: 实现 `max_total_position` 限制——这是3月28日-34.5%回撤的直接原因(6只重仓=仓位过高)
2. **P1-6**: 修复 `max_position_per_stock` 默认值1.0→0.35
3. **P0-2**: 统一止盈参数读取策略
4. **P0-4**: 添加强制空仓冷却期

### 审计确认:无未来函数新增问题

之前V25-V39审查中已标注的已知未来函数(半路追涨pct_chg≥5%、龙头低吸volume_ratio)仍在代码中保留,并有详细注释说明。本次审查未发现新的未标注未来函数。所有策略筛选条件中的T日因子均已标注或使用_prev版本替代。
