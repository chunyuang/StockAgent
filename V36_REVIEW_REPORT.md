# 回测引擎深度审查报告 V36

**审查日期**: 2026-05-24  
**审查范围**: 13个文件, ~9400行代码  
**基线版本**: V41 (147.22%收益/3.03%回撤/73.47%胜率/13.00夏普/3.03盈亏比)  
**审查员**: AI Code Reviewer (逐行深度审查)

---

## 📊 审查概览

| 严重级别 | 数量 | 说明 |
|---------|------|------|
| **P0** | 2 | 逻辑bug,影响回测结果准确性 |
| **P1** | 5 | 重要问题,影响代码健壮性或可维护性 |
| **P2** | 8 | 改进建议,不影响当前功能正确性 |

### 已知问题确认状态

| 编号 | 描述 | 状态 |
|------|------|------|
| P0-1 | 首板打板turnover_rate用T日(未来函数) | ✅ 已修复(用turnover_rate_prev) |
| P0-2 | 首板打板circ_mv用T日(未来函数) | ✅ 已修复(用circ_mv_prev) |
| P1-1 | 龙头低吸volume_ratio用T日(未来函数) | ⚠️ 已知保留(改为_prev收益降90%,盘中可近似观测) |
| P1-2 | 持仓保护可能阻止必要止损 | ✅ V35已修复(止损检查不保护) |
| P1-5 | 超时强卖日志缺少策略信息 | ✅ 已修复(统一日志格式) |

---

## 🔴 P0级问题 (2个)

### P0-NEW-1: monthly_profit计算使用daily_profit_list而非net_value_series,与V36修复声明矛盾

**文件**: `portfolio_backtest.py`  
**行号**: ~2760-2790 (`_build_run_result`中的monthly_profit计算)  
**严重级别**: P0  

**问题描述**:

V36审查报告声称"monthly_profit改用net_value_series计算(更可靠)",但当前代码仍然使用`daily_profit_list`累加:

```python
monthly_profit = {}
if daily_profit_list and all_trade_dates:
    current_value = self._initial_cash
    monthly_start_value = current_value
    current_month = None
    for i, profit in enumerate(daily_profit_list):
        if i < len(all_trade_dates):
            date_str = str(all_trade_dates[i])
            ...
            current_value += profit  # ← 用daily_profit_list累加
```

问题在于`daily_profit_list`存储的是**绝对收益金额(元)**,而非归一化收益率。当V32修复将`insert(0, 0.0)`移到计算之后,`daily_profit_list`和`all_trade_dates`的对齐是正确的,但`current_value`的累加方式在以下场景可能出错:

1. `_need_initial_insert=True`时,`daily_profit_list`被`insert(0, 0.0)`,而monthly_profit计算在insert之后执行 → 多了1个0不影响累加,但索引i与all_trade_dates[i]的对应关系正确
2. 关键问题:**`daily_profit_list`可能包含`_record_daily_net_value`中的浮点累积误差**。对于长回测(>100天),逐日累加的浮点误差可能使月度收益总和与总收益不一致

**建议修复**:

使用`net_value_series`直接计算月度收益,避免浮点累加误差:

```python
monthly_profit = {}
if net_value_series and all_trade_dates:
    current_month = None
    month_start_nv = 1.0  # 归一化净值起始
    for i, nv_point in enumerate(net_value_series):
        nv = nv_point.get('net_value', 1.0)
        date_str = str(nv_point.get('trade_date', ''))
        month_key = date_str[:6]
        formatted_key = f"{month_key[:4]}-{month_key[4:]}"
        if current_month is not None and month_key != current_month:
            # 月末,计算该月收益 = 月末净值/月初净值 - 1
            m_return = nv / month_start_nv - 1 if month_start_nv > 0 else 0
            formatted_prev = f"{current_month[:4]}-{current_month[4:]}"
            monthly_profit[formatted_prev] = m_return
            month_start_nv = nv
        elif current_month is None:
            month_start_nv = nv
        current_month = month_key
    # 最后一月
    if current_month:
        m_return = nv / month_start_nv - 1 if month_start_nv > 0 else 0
        formatted_last = f"{current_month[:4]}-{current_month[4:]}"
        monthly_profit[formatted_last] = m_return
```

**影响**: 月度收益统计可能存在小数点级别的偏差,对前端展示有影响,但不影响核心回测逻辑

---

### P0-NEW-2: 非调仓日强制空仓检查使用缓存的情绪评分,可能错过当日极端行情

**文件**: `portfolio_backtest.py`  
**行号**: ~948-975 (`_run_impl`中强制空仓判断)  
**严重级别**: P0  

**问题描述**:

在非调仓日路径中,强制空仓判断使用的是**缓存的**`limit_up_count`/`limit_down_count`/`index_change`:

```python
if is_rebalance_day:
    sentiment_level, market_sentiment_score, limit_up_count, limit_down_count, index_change = \
        await self._print_market_environment(prev_trade_date)
else:
    # 复用上一次计算的结果(情绪评分在非调仓日不会变化太多,1天差异可忽略)
    sentiment_level = getattr(self, '_cached_sentiment_level', '震荡期,仓位系数0.7')
    market_sentiment_score = getattr(self, '_cached_sentiment_score', 50)
    limit_up_count = getattr(self, '_cached_limit_down_count', 0)  # ⚠️ BUG!
    limit_down_count = getattr(self, '_cached_limit_down_count', 0)
    index_change = getattr(self, '_cached_index_change', 0.0)
```

**Bug**: `limit_up_count`读取的是`_cached_limit_down_count`,变量名错误!

实际影响:
1. 非调仓日`limit_up_count`被错误赋值为`_cached_limit_down_count`的值
2. 强制空仓条件`limit_up_count <= FORCE_EMPTY_LIMIT_UP(10)`在跌停数少时不会触发,但如果跌停数>10(常见),limit_up_count会被错误赋值,可能导致非调仓日强制空仓误触发
3. 但实际上非调仓日路径**不执行强制空仓**——强制空仓只在`_process_rebalance_day`中执行。非调仓日的`limit_up_count`仅用于日志和条件变量赋值

**实际风险评估**: 中等。虽然当前非调仓日不执行强制空仓清仓,但:
- 如果未来有人在非调仓日路径加入强制空仓逻辑,此bug会直接导致误清仓
- 日志输出中limit_up_count值会是错误的

**修复**:

```python
limit_up_count = getattr(self, '_cached_limit_up_count', 0)  # 修复变量名
```

---

## 🟠 P1级问题 (5个)

### P1-NEW-1: check_full_sell的TP/SL参数取min与_rebalance中取strategies[0]的TP不一致

**文件**: `sell_signal_checker.py`  
**行号**: ~580-600 (`check_full_sell`方法)  
**严重级别**: P1  

**问题描述**:

`check_full_sell`中止损取min、止盈取min:
```python
sl = min(self._strategy_risk_params.get(s, {}).get('stop_loss_pct', global_sl) for s in strategies)
tp = min(self._strategy_risk_params.get(s, {}).get('take_profit_pct', global_tp) for s in strategies)
```

但`portfolio_backtest.py`的`_get_sl_tp_for_code`中止盈取`strategies[0]`(第一个策略):
```python
tp = strategy_rp.get(strategies[0], {}).get('take_profit_pct', global_tp)
```

V31修复说明TP应取"买入策略"的TP,而非min。但`check_full_sell`仍取min,导致两个路径止盈价不一致。虽然`check_full_sell`标注为DEPRECATED,但如果未来有人调用它,会产生与`_rebalance`不同的卖出行为。

**建议**: 在`check_full_sell`方法注释中明确标注此不一致性,或统一为strategies[0]

---

### P1-NEW-2: 持仓保护逻辑在_rebalance中检查close_p>=open_p(阳线),但未考虑一字涨停

**文件**: `portfolio_backtest.py`  
**行号**: ~3830-3860 (`_rebalance`中持仓保护逻辑)  
**严重级别**: P1  

**问题描述**:

持仓保护条件之一是"收阳线"(`close_p >= open_p`):
```python
is_yang_line = close_p >= open_p  # 收阳线
if profit_pct >= hold_protection_pct and is_yang_line and should_still_protect:
    protected_codes.append(code)
```

但一字涨停板(`open == close == high == low`)也满足`close_p >= open_p`,会被保护。一字涨停板**无法买入**(已在`_get_limit_up_price`中返回0),但已持仓的一字涨停板被保护会导致:
- 一字涨停次日可能大幅低开(涨停开板),此时被保护会错过最佳卖出时机
- V35修复了"止损检查不保护",但未处理一字涨停特殊场景

**建议**: 添加一字涨停排除:
```python
is_yizi = (open_p == close_p == price_info.get('high', 0) == price_info.get('low', 0)) and open_p > 0
if profit_pct >= hold_protection_pct and is_yang_line and should_still_protect and not is_yizi:
```

---

### P1-NEW-3: _record_daily_net_value中停牌折价计算使用_calc_trade_days_held但参数语义不一致

**文件**: `portfolio_backtest.py`  
**行号**: ~795-810  
**严重级别**: P1  

**问题描述**:

`_calc_trade_days_held`的语义是"持仓交易日数(不含买入日,含卖出日)",用于计算持仓天数。但在停牌折价中被用来计算"停牌天数":
```python
suspended_days = self._calc_trade_days_held(int(lvp_date), int(trade_date)) if lvp_date != trade_date else 0
if suspended_days > 3:
    discount = (0.99 ** (suspended_days - 3))
```

这里`lvp_date`是"最后有效价格日期",不是"买入日期"。语义上是正确的(两个日期之间的交易日数),但方法名`_calc_trade_days_held`暗示是"持仓天数",容易造成混淆。

更重要的是:如果`lvp_date`不在`_trade_date_index_map`中(如:停牌前的最后交易日在回测区间外),fallback的O(N)遍历`_all_trade_dates`在每日对每只停牌股都会执行,形成O(N*M)的潜在性能问题。

**建议**: 
1. 重命名为`_calc_trade_days_between`或提取通用方法
2. 增加lvp_date不在映射中的特殊处理(如直接用日历天数/1.5)

---

### P1-NEW-4: strategy_defaults.py的GLOBAL_RISK.max_position_per_stock=0.2与回测引擎的max_stocks=3席位制矛盾

**文件**: `strategy_defaults.py`  
**行号**: 14  
**严重级别**: P1  

**问题描述**:

`GLOBAL_RISK.max_position_per_stock = 0.2`(单票最大仓位20%),但回测引擎使用`max_stocks=3`的席位制分配:
- 3只股票等权分配,每只占33.3%
- 但`max_position_per_stock`限制为20%,实际每只只能买20%
- 在`_rebalance`中: `effective_weight = min(weight * position_multiplier, max_pos_per_stock)`
- weight=0.333, position_multiplier=1.0 → effective_weight=0.2 → 实际只用了60%资金

然而,当`position_multiplier=0.3`(冰点期)时:
- effective_weight = min(0.333*0.3, 0.2) = 0.1 → 每只10%,3只30%

这在正常情况下合理,但可能导致:
1. 高潮期资金利用率只有60%(20%*3),浪费40%现金
2. 实际持仓数可能少于3只(资金不足时按比例缩减)

**建议**: 在日志中明确显示实际资金利用率,或让max_stocks和max_position_per_stock联动

---

### P1-NEW-5: ultra_short.py中首板打板成交概率日志打印的默认值与strategy_defaults不一致

**文件**: `ultra_short.py`  
**行号**: ~230-240  
**严重级别**: P1  

**问题描述**:

`ultra_short.py`日志中打印首板打板成交概率时:
```python
hit_fast = strategy_params_local.get('hit_probability_fast', _defaults.get('hit_probability_fast', 0.3))
hit_normal = strategy_params_local.get('hit_probability_normal', _defaults.get('hit_probability_normal', 0.5))
hit_slow = strategy_params_local.get('hit_probability_slow', _defaults.get('hit_probability_slow', 0.7))
```

但`strategy_defaults.py`中实际定义的值是:
```python
"hit_probability_fast": 0.20,
"hit_probability_normal": 0.45,
"hit_probability_slow": 0.65,
```

日志fallback值(0.3/0.5/0.7)与strategy_defaults实际值(0.20/0.45/0.65)不一致。如果`_defaults`读取成功,不影响实际值,但fallback值是错误的。用户如果对比日志和实际行为会发现不一致。

**修复**: 将fallback值与strategy_defaults.py对齐:
```python
hit_fast = strategy_params_local.get('hit_probability_fast', _defaults.get('hit_probability_fast', 0.20))
hit_normal = strategy_params_local.get('hit_probability_normal', _defaults.get('hit_probability_normal', 0.45))
hit_slow = strategy_params_local.get('hit_probability_slow', _defaults.get('hit_probability_slow', 0.65))
```

---

## 🟡 P2级问题 (8个)

### P2-NEW-1: _check_and_execute_forced_sells中利润锁定参数硬编码fallback,与strategy_defaults不一致

**文件**: `portfolio_backtest.py`  
**行号**: ~245-250  
**严重级别**: P2  

**问题描述**:

利润锁定参数从`_risk_config`读取,但fallback值与`strategy_defaults.py`中的`GLOBAL_RISK`一致(0.06/0.025/0.02),因为`_risk_config`在`_init_run_config`中已从`GLOBAL_RISK`初始化。但注释说"V46:参数从strategy_defaults读取",实际读取路径是`_risk_config`而非直接从`GLOBAL_RISK`,如果`_risk_config`被前端传入值覆盖,可能不一致。

**风险**: 低。参数传递路径正确,仅注释可能引起误解。

---

### P2-NEW-2: sell_signal_checker.py中check_intraday_profit_lock使用params而非holding传递参数

**文件**: `sell_signal_checker.py`  
**行号**: ~285-310  
**严重级别**: P2  

**问题描述**:

`check_intraday_profit_lock`需要`high_price`来判断盘中冲高,但`check_early_sell`只传入`open_price`和`close_price`,不传`high`。因此利润锁定信号只能在`check_full_sell`中使用(有high_price),不能在早盘保护性卖出中使用。

这是设计决策而非bug,但代码中缺少明确的文档说明为什么`STRATEGY_SELL_SIGNALS`中不包含利润锁定信号。

**建议**: 在`INTRADAY_PROFIT_LOCK_SIGNALS`定义处添加注释说明原因

---

### P2-NEW-3: _build_run_result方法过长(~700行),违反单一职责原则

**文件**: `portfolio_backtest.py`  
**行号**: ~2200-2900  
**严重级别**: P2  

**问题描述**:

`_build_run_result`方法内部已有注释说明不可拆分的原因(run_state是dict而非对象),但从可维护性角度,建议至少提取以下子方法:
1. `_calc_performance_metrics` — 绩效统计(sharpe/sortino/calmar/volatility)
2. `_merge_trades` — 交易合并(FIFO匹配)
3. `_build_output_format` — 输出格式化(嵌套metrics+兼容层)

每个子方法约200行,独立测试更容易。

---

### P2-NEW-4: special_period_filter.py的假期/会议日期硬编码,无自动更新机制

**文件**: `special_period_filter.py`  
**行号**: ~60-130  
**严重级别**: P2  

**问题描述**:

所有假期和会议日期硬编码在`DEFAULT_CONFIG`中,仅覆盖2025-2026年。代码中有warning提示超出范围,但没有自动从外部数据源(如国务院公告)更新的机制。

**建议**: 
1. 添加配置文件加载路径(如`/etc/openclaw/special_periods.json`)
2. 考虑从MongoDB配置集合读取,支持动态更新

---

### P2-NEW-5: factor_engine.py回测模式中daily_basic合并时,未对齐索引可能导致数据丢失

**文件**: `factor_engine.py`  
**行号**: ~250-280  
**严重级别**: P2  

**问题描述**:

daily_basic合并使用`set_index("ts_code")`后`intersection`,但如果daily_basic的日期与stock_daily不同(如数据同步延迟),合并结果可能少行。代码中使用了`intersection`处理,但缺少日志警告合并后行数减少的情况。

**建议**: 添加合并前后的行数对比日志

---

### P2-NEW-6: universe.py的_tradable_stocks_cache是类变量(dict),多回测并行时可能冲突

**文件**: `universe.py`  
**行号**: ~48  
**严重级别**: P2  

**问题描述**:

`_tradable_stocks_cache: dict[str, set[str]] = {}`是类变量,所有`UniverseManager`实例共享。如果同时运行两个回测任务(不同日期范围),缓存会互相覆盖。

当前`_worker_count=1`(单任务)不会触发此问题,但如果未来启用并行回测,需要改为实例变量或加锁。

---

### P2-NEW-7: _get_limit_up_price中非涨停日返回值可能超过high_price

**文件**: `portfolio_backtest.py`  
**行号**: ~3350-3360  
**严重级别**: P2  

**问题描述**:

非涨停日的估算涨停价:
```python
base_price = pre_close if pre_close > 0 else open_price
return min(base_price * (1 + limit_pct), high_price)
```

`min(..., high_price)`确保不超过当日最高价,这是正确的。但在一字涨停场景(open=close=high=low)中,前面已返回0(不可买入)。对于"几乎涨停但未封住"的场景(如涨幅9.9%的10%板),返回值是`min(pre_close*1.10, high_price)`,如果high_price恰好是涨停价,则返回涨停价,买入后无法卖出(当日涨停不能卖,T+1),次日可能开板亏损。这是已知风险而非bug。

---

### P2-NEW-8: node.py中worker循环的_close_log_handles在finally和except中重复调用

**文件**: `node.py`  
**行号**: ~180-195  
**严重级别**: P2  

**问题描述**:

代码注释说"此处重复调用是安全的(幂等)",但实际上`_close_log_handles`内部执行`file.close()`,对已关闭的文件调用close()在Python中是安全的(幂等),所以确实没有问题。但双重关闭的代码模式不够优雅。

**建议**: 移除except块中的`_close_log_handles`调用,只在finally中保留

---

## 📋 审查文件清单

| # | 文件 | 行数 | 审查状态 | 发现问题 |
|---|------|------|---------|---------|
| 1 | portfolio_backtest.py | 4292 | ✅ 逐行 | P0-NEW-1, P0-NEW-2, P1-NEW-2, P1-NEW-3, P2-NEW-1, P2-NEW-7 |
| 2 | sell_signal_checker.py | 853 | ✅ 逐行 | P1-NEW-1, P2-NEW-2 |
| 3 | strategy_filter.py | 179 | ✅ 审查 | 已标注过时(V39确认) |
| 4 | universe.py | 416 | ✅ 审查 | P2-NEW-6 |
| 5 | factor_engine.py | 718 | ✅ 审查 | P2-NEW-5 |
| 6 | factor_library.py | 797 | ✅ 扫描 | 无新问题 |
| 7 | factor_auto_compute.py | 574 | ✅ 扫描 | 已标注跳过(已知卡死) |
| 8 | factor_quality_checker.py | 231 | ✅ 审查 | 无新问题 |
| 9 | special_period_filter.py | 373 | ✅ 审查 | P2-NEW-4 |
| 10 | strategy_defaults.py | 192 | ✅ 逐行 | P1-NEW-4, P1-NEW-5 |
| 11 | models.py | 127 | ✅ 审查 | 无新问题 |
| 12 | node.py | 587 | ✅ 审查 | P2-NEW-8 |
| 13 | ultra_short.py | 632 | ✅ 审查 | P1-NEW-5 |

---

## ✅ 关键确认项 (无新问题)

1. **T+1约束**: 6处全部正确应用(调仓日卖出、非调仓日卖出、强制空仓、减仓、超时强卖、首板打板成交概率)
2. **PositionManager防震荡bug**: V33修复验证通过,买入循环使用`pos_mgr.target_shares`而非局部变量
3. **TP取strategies[0]**: V31修复验证通过(仅`_get_sl_tp_for_code`),`check_full_sell`仍取min(已标注P1-NEW-1)
4. **Sortino上限50, Calmar上限200**: 验证通过
5. **V32月度收益偏移修复**: insert(0,...)已移到计算之后,对齐正确
6. **V44强制空仓大盘跌幅条件**: 已修复并验证
7. **V42利润锁定信号**: 代码实现正确,参数从strategy_defaults读取
8. **V45策略参数**: 半路追涨SL4%/TP12%/hold3; 龙头低吸SL3%/TP30%/hold5; 跌停翘板SL5%/TP20%/hold3 — 与strategy_defaults.py一致

---

## 🔬 未来函数详细审查

| 策略 | 因子 | 时间点 | 状态 | 说明 |
|------|------|--------|------|------|
| 半路追涨 | pct_chg≥5% | T_close | ⚠️ 已知 | 过滤冲高回落假信号,去pct_chg收益降48%(V25验证),保留近似 |
| 半路追涨 | volume_ratio_prev | T_prev | ✅ | V27修复 |
| 龙头低吸 | volume_ratio | T_day | ⚠️ 已知 | 保留T日(改为_prev收益降90%,盘中可近似观测) |
| 龙头低吸 | circ_mv_prev | T_prev | ✅ | V35修复 |
| 首板打板 | turnover_rate_prev | T_prev | ✅ | V27修复 |
| 首板打板 | circ_mv_prev | T_prev | ✅ | V27修复 |
| 跌停翘板 | pct_chg>0 | T_close | ✅ | 收盘确认(盘中买入逻辑自洽) |
| 跌停翘板 | turnover_rate_prev | T_prev | ✅ | V27修复 |
| 跌停翘板 | circ_mv_prev | T_prev | ✅ | V27修复 |

---

## 📝 修复优先级建议

| 优先级 | 编号 | 修复难度 | 预计耗时 |
|--------|------|---------|---------|
| **立即** | P0-NEW-2 (变量名错误) | 1行 | 1分钟 |
| **本次** | P1-NEW-5 (fallback值不一致) | 3行 | 5分钟 |
| **本次** | P0-NEW-1 (monthly_profit改用net_value_series) | 20行 | 30分钟 |
| **下次** | P1-NEW-2 (一字涨停保护) | 3行 | 15分钟(需回测验证) |
| **下次** | P1-NEW-1 (check_full_sell TP一致性) | 5行+注释 | 15分钟 |
| **低优** | P1-NEW-3 (方法名语义) | 重命名 | 30分钟(需全量替换) |
| **低优** | P1-NEW-4 (仓位利用率日志) | 5行 | 15分钟 |
| **低优** | P2全部 | — | 按需 |

---

*报告结束。所有问题均未修改代码,仅做审查和报告。*
