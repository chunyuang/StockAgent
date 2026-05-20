# 回测模块V19审查报告

**审查时间**: 2026-05-20 22:30  
**基线数据**: 2策略(半路追涨+跌停翘板) 20250105-20260516  
**基线结果**: 收益1025.75% / 夏普7.92 / 回撤3.01% / 胜率73.68% / 盈亏比2.17

---

## P0级修复(严重bug/数据错误)

### P0-1: _rebalance中止损止盈冲高回落价格未传入forced_sell_prices
**位置**: portfolio_backtest.py L3584-3625 (_rebalance方法)  
**问题**: _rebalance的sell_codes循环中，当目标池内持仓触发冲高回落/止损/止盈时，只将code加入sell_codes，但未将对应的sell_price写入forced_sell_prices(此方法无forced_sell_prices机制)。后续卖出循环中，这些股票走到else分支(不在目标池→调仓卖出)用close价卖出，而非止损价/冲高回落价。  
**影响**: 止损应以止损价卖出，实际以close卖出→close可能低于止损价(多亏)或高于止损价(少亏)，价格不精确  
**修复**: 在_rebalance的sell_codes循环中，记录每个code对应的sell_price和sell_reason，后续卖出时使用

### P0-2: 减仓逻辑中del holdings[code]后继续用holdings[code]
**位置**: portfolio_backtest.py L1793-1797 (_process_non_rebalance_day)  
**问题**: 非调仓日强卖时先`del holdings[code]`，但后续`if code in self._cost_basis_date`仍然引用code。虽然不影响正确性(cost_basis_date在del后自然跳过)，但逻辑上应在同一步骤清理。  
**影响**: 无实际bug但代码不清晰

### P0-3: _process_non_rebalance_day中超时强卖重复计算
**位置**: portfolio_backtest.py L1923-1950  
**问题**: 超时强卖检查的`trade_days_held`计算逻辑在_process_non_rebalance_day和_rebalance中重复实现，且_rebalance中也有相同逻辑(L3640)。三处代码几乎完全一致。  
**影响**: 维护困难，容易出现不一致

---

## P1级修复(逻辑优化/性能)

### P1-1: _get_prices日志过多(每只股票的查询都打印)
**位置**: portfolio_backtest.py _get_prices方法  
**问题**: 每次调用_get_prices都打印"🔍 _get_prices: 查询 N 只股票"和"✅ _get_prices: 查询到 N 只股票有价格"。调仓日有3次调用(持仓+目标+止损止盈)，非调仓日1-2次。5000行日志中大量此类重复信息。  
**修复**: 降为debug级别，或只打印总数汇总

### P1-2: 板块集中度过滤中factor_df逐行查询效率低
**位置**: portfolio_backtest.py L1281-1295  
**问题**: `factor_df[factor_df['ts_code'] == code]` 对每个候选股都做一次全表扫描，O(N*M)。应先用isin过滤再map。  
**修复**: 预计算volume_ratio映射dict，O(N)查找

### P1-3: _check_early_sell_signals中跌停翘板逻辑有gap
**位置**: portfolio_backtest.py L162-173  
**问题**: 跌停翘板的冲高回落检查：`open_rise_from_cost >= _open_sell_pct`(默认0.03)且`close < open`。但如果open_rise_from_cost在3%-5%之间，且close<open但跌幅<2%，代码会跳过(不满足3%-5%区间条件也不满足>5%条件)。这意味着3%-5%高开低收但跌幅<2%的情况不会被保护。  
**分析**: 这是设计意图(避免3%-5%区间小幅回落误杀)，但5%以上保护阈值可能过高。跌停翘板次日3%-5%高开已算强势，如果明显回落(close跌幅>1.5%)也应保护。  
**修复**: 将3%-5%区间的回落阈值从2%降至1.5%，更积极保护利润

### P1-4: 减仓逻辑中止损止盈检查使用p.get('low', p['close'])而非p.get('low', p.get('close',0))
**位置**: portfolio_backtest.py L3695-3700  
**问题**: `low_p = p.get('low', p['close'])` — 如果p中没有'close'键会KeyError。虽然实际上prices字典总包含close，但写法不一致(L1749用p.get('low', p['close']) vs L1884用p.get('low', p['close']))  
**修复**: 统一为 `p.get('low', p.get('close', 0))`

### P1-5: 首板打板涨停价买入但一字板返回0后不重试
**位置**: portfolio_backtest.py _get_buy_price_for_stock  
**问题**: 首板打板一字板时_get_limit_up_price返回0(不可买入)。但非一字板涨停日也可能无法确定涨停价(如pre_close=0且close未达阈值)，此时也返回0导致该股被跳过。  
**修复**: 非涨停日时fallback到close价(如果close>open)或open价，而非直接返回0

### P1-6: strategy_filter.py未被引用（代码尸体）
**位置**: strategy_filter.py  
**问题**: 文件开头注释说明"尚未被主引擎引用"，与portfolio_backtest.py的_build_strategy_filter_conditions完全重复。增加维护负担。  
**修复**: 暂不删除（未来Phase 6-8拆分需要），但添加deprecation警告

### P1-7: 净值曲线首日可能不精确
**位置**: portfolio_backtest.py _build_run_result  
**问题**: 在net_value_series开头插入{net_value: 1.0, daily_profit: 0}作为首日。但如果回测首日就有交易，首日净值可能已经是1.0+收益。插入的1.0首日是"回测前"的状态，而daily_profit_list[0]是首日实际收益。两者时间点不一致。  
**修复**: 插入的首日用start_date的前一个交易日标注(如"回测初始")

---

## P2级修复(代码质量/体验)

### P2-1: _print_market_environment返回值过多(4个)
**位置**: portfolio_backtest.py _print_market_environment  
**问题**: 返回(sentiment_level, sentiment_score, limit_up_count, limit_down_count)4个值。sentiment_level包含仓位系数文字(如"高潮期,仓位系数1.0")，需要_extract_position_multiplier再解析。  
**修复**: 返回一个namedtuple/dict，更清晰

### P2-2: daily_profit单位不一致
**位置**: portfolio_backtest.py _record_daily_net_value vs _build_run_result  
**问题**: _record_daily_net_value中daily_profit = daily_profit / _initial_cash (归一化小数)。但_build_run_result中的daily_profit_list是绝对值(元)。最后在result中再次归一化。容易混淆。  
**修复**: 统一为归一化小数，在输出时按需×100转百分比

### P2-3: _get_stock_names中的_standardize_code重复定义
**位置**: portfolio_backtest.py _get_stock_names 和 _get_prices  
**问题**: 两处有几乎相同的代码标准化逻辑。  
**修复**: 提取为类方法_standardize_ts_code

---

## 回测结果优化建议

### R1: 半路追涨min_close_rise_pct 5%→3%?
**分析**: 当前5%收盘确认太严格，过滤掉了很多3%-5%区间收盘的优质信号。但V14测试时5%胜率66.2% vs 3%胜率40.5%。**不建议修改**。

### R2: 跌停翘板止损7%是否过宽？
**分析**: 当前止损7%，3天max_hold。跌停翘板次日如果跌5-6%不止损，第3天可能继续跌到-10%。但7%止损避免了翘板股正常波动的误杀。**观察数据后决定**。

### R3: max_stocks=3可能过保守
**分析**: 3只持仓对应3个策略席位(半路2+跌停1)，每只仓位约20%。总仓位60%，现金40%。可以尝试max_stocks=4(半路2+跌停2)，增加跌停翘板的参与度。
