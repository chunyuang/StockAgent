# V65 回测引擎代码审查报告

**审查日期**: 2026-05-27
**审查范围**: 7个核心文件, ~7800行代码
**基线(2周回测 20260511-20260525)**: Total Return 28.85%, Max DD 0.44%, Win Rate 70%, Sharpe 18.26, P/L 2.85, Trades 20
**Sell Reasons**: stop_loss=6, take_profit=2, profit_lock=3, pullback=7, force_empty=1, rebalance=1

---

## P0 - 必须修复(影响回测正确性)

| ID | 文件 | 行号 | 问题 | 影响 | 修复方案 |
|----|------|------|------|------|----------|
| P0-1 | portfolio_backtest.py | ~L251-640 `_check_and_execute_forced_sells` | **止损6次中可能有跳空止损误杀——止损价用cost*(1-sl)但实际成交用open价，当open远低于止损价时亏损被放大**。跳空止损以open价成交(V29逻辑正确),但统计时"止损"和"跳空止损"合并为stop_loss=6,无法区分跳空亏损严重程度。6次30%止损率是否合理无法判断。 | 止损占比30%过高,无法区分正常止损vs跳空误杀,影响参数调优方向 | 1) sell_reason_stats中拆分"跳空止损"为独立类别 2) 基线6次stop_loss中统计有多少是跳空止损 3) 跳空止损>3次时考虑提高SL或增加open跳空保护 |
| P0-2 | sell_signal_checker.py | L244 `check_pullback` | **冲高回落7次可能过早退出——pullback_mid_fallback_pct=0.01(1%)过于敏感**。半路追涨/龙头低吸在中间区间(2%-5%高开)只需回落1%即触发,这几乎是正常日内波动。2周回测7次冲高回落中,可能有3-4次是正常波动被误判。 | 利润被过早截断,7次pullback占比35%,远高于止盈2次(10%),说明大量利润在冲高回撤中被放弃 | 1) 半路追涨pullback_mid_fallback从1%→1.5% 2) 龙头低吸从1.5%→2.0% 3) 添加pullback最小利润保护:open_rise<3%时不触发冲高回落(太小不算"冲高") |
| P0-3 | portfolio_backtest.py | ~L2848 Sharpe计算 | **夏普比率计算中daily_rf使用GLOBAL_RISK.risk_free_rate/252,但这是日化无风险利率,可能不准确**。当前risk_free_rate=0.03(3%),日化=0.03/252≈0.000119。对于2周(10交易日)回测,年化因子sqrt(252)≈15.87导致Sharpe虚高(18.26在正常市场中极不合理)。2周回测的Sharpe不具备统计显著性。 | 前端显示Sharpe=18.26误导性强,真实年化Sharpe可能在2-4之间 | 1) 短回测(<60天)时Sharpe标注"参考性低" 2) 添加trading_days<30时annual_return_reliable类似的sharpe_reliable标志 3) 考虑使用滚动窗口Sharpe替代全期Sharpe |
| P0-4 | portfolio_backtest.py | ~L2151 `_process_rebalance_day` 强制空仓后净值 | **强制空仓日跳过选股后,`last_prices`未更新(仍用前日价格),导致净值计算用旧价格**。虽然`_record_daily_net_value`会尝试用last_prices计算持仓市值,但强制空仓后holdings为空所以不影响现金净值。然而,如果T+1限制导致强制空仓日有股票未卖出,`last_prices`为空字典,这些股票市值按0计算,净值突然下降。 | 强制空仓日T+1遗留股票净值失真 | 强制空仓日也需要调用`_get_prices`获取T+1遗留股票价格,更新last_prices后再记录净值 |

---

## P1 - 建议修复(影响回测质量/性能)

| ID | 文件 | 行号 | 问题 | 影响 | 修复方案 |
|----|------|------|------|------|----------|
| P1-1 | portfolio_backtest.py | ~L1151 `_init_run_config` | **max_position_per_stock默认fallback不一致**: risk_config初始化用`config.get("max_position_per_stock", config.get("max_position_percent", GLOBAL_RISK.get("max_position_per_stock", 0.35)))`,但ultra_short.py传的是`strategy_params.get("max_position_per_stock", 0.2)`。如果前端不传此参数,默认值0.2 vs 0.35不一致 | 单票仓位可能被限制在20%而非35%,导致频繁现金不足缩减 | ultra_short.py的fallback改为`GLOBAL_RISK.get("max_position_per_stock", 0.35)` |
| P1-2 | sell_signal_checker.py | L670 `get_sl_tp_for_strategies` | **TP取strategies[0]与portfolio_backtest._get_sl_tp_for_code一致,但注释仍说"买入策略决定止盈线"**。如果同股多策略且首策略TP很低(如首板打板10%),而次策略TP很高(如龙头低吸30%),首策略的10%会截断龙头低吸的利润。虽然这在V63-P0-2中已统一,但当首板打板+龙头低吸同股时仍有问题。 | 多策略同股时止盈线被首个策略限制 | 考虑TP取max(所有策略)而非strategies[0],或至少对"持仓中策略"取max |
| P1-3 | portfolio_backtest.py | ~L4048 `_rebalance` | **_sell_code_details中best_price可能为None**: 当`cost<=0`或`p.get('close',0)<=0`时,`_sell_code_details[code]=(None, '调仓卖出')`。后续V48d遍历`_sell_code_details`时,如果best_reason!='调仓卖出'则调用pos_mgr.mark_sold,但best_price=None的股票不会被mark_sold(因为best_reason='调仓卖出')。这导致这些股票在卖出循环中使用close价而非更优价格。 | 停牌股/数据缺失股卖出价可能不是最优 | 将None的情况也纳入卖出循环,使用最后有效价格作为fallback |
| P1-4 | portfolio_backtest.py | ~L651 `_print_market_environment` | **涨跌停统计使用pct_chg阈值9.8%/19.6%/29.8%,但实际涨跌停幅度可能因四舍五入略有不同**。例如ST股5%涨停、注册制新股首日不设涨跌幅。当前未排除这些特殊情况 | 涨跌停统计略有误差,影响强制空仓判断 | 添加is_limit_up/is_limit_down字段作为辅助判断,或排除上市首日/次新股 |
| P1-5 | factor_engine.py | ~L240 V18 _prev因子 | **_prev因子生成后不再fillna(0)(V33修复),导致NaN值在筛选时被跳过**。但如果某因子_prev全为NaN(如新股无T-1数据),该股票会被所有使用_prev因子的条件过滤掉,即使其他条件都满足。这意味着新股永远无法被选入。 | 新股(上市<2天)被所有策略排除 | 对_prev因子使用更合理的默认值: circ_mv_prev用T日值(差异<1%),volume_ratio_prev用1.0(中等),而非NaN |
| P1-6 | ultra_short.py | ~L350 | **max_position_per_stock和max_total_position的fallback值与strategy_defaults.py不一致**: ultra_short传max_position_per_stock=0.2,但GLOBAL_RISK=0.35;max_total_position传的是`strategy_params.get("max_position", strategy_params.get("max_total_position", 0.7))`两层fallback | 回测可能使用错误的仓位限制 | 统一为GLOBAL_RISK的值,删除ultra_short.py中的硬编码fallback |
| P1-7 | portfolio_backtest.py | ~L3348 `_get_prices` | **pre_close fallback使用_prev_day_close,但_prev_day_close在同一天多次调用_get_prices时会被覆盖为当日close**。注释说"次日首次调用时读的doc已有正确的pre_close",但如果某天MongoDB文档缺少pre_close字段,则fallback用的是前次调用记录的close(可能不是真正的pre_close) | pre_close不准确影响intraday_max_rise_pct计算 | 使用专门的pre_close缓存而非_prev_day_close,或在daily_price_cache中缓存每个code的pre_close |

---

## P2 - 优化建议(代码质量/体验)

| ID | 文件 | 行号 | 问题 | 影响 | 修复方案 |
|----|------|------|------|------|----------|
| P2-1 | portfolio_backtest.py | 全文 | **_build_run_result约700行,逻辑复杂**。虽然有注释说明不拆分原因,但FIFO匹配+绩效计算+策略分解+图表数据+元数据5段完全独立,可拆分为5个私有方法 | 可维护性差 | 将5段逻辑提取为_build_metrics/_build_trades/_build_strategy_summary/_build_chart_data/_build_metadata |
| P2-2 | sell_signal_checker.py | L100-130 | **should_apply_slippage三层匹配(精确→前缀→包含)可能误匹配**。如"超时(3交易日≥2交易日)"会先前缀匹配"超时"=False,正确;但"跳空止损(V62调整)"如果写了"跳空止损(宽)"会前缀匹配"跳空止损"=False,也正确。但自定义reason如"止盈后回买"会前缀匹配"止盈"=False,语义不对 | 滑点判断可能对非标准reason错误 | 添加reason白名单校验,未知reason应默认扣滑点(SLIPPAGE_DEFAULT=True已处理) |
| P2-3 | strategy_defaults.py | L36-37 | **force_empty_cooldown_position_cap=0.6与force_empty_cooldown_days=2在不同位置定义**。GLOBAL_RISK中cooldown_days=2,cooldown_cap=0.6,但portfolio_backtest.py中读取cap时有fallback 0.5的注释残留(V63说是0.5→0.6) | 历史注释残留,可能误导 | 清理注释,统一fallback为GLOBAL_RISK值 |
| P2-4 | portfolio_backtest.py | ~L1651 | **universe_mgr.get_universe调用两次(一次raw一次filtered)**,且_get_st_stocks/_get_new_stocks每次调都查MongoDB,无缓存 | 调仓日每天多2-3次MongoDB查询 | 缓存ST股列表和次新股列表(日频更新即可) |
| P2-5 | factor_engine.py | ~L250 | **V18 _prev因子查询使用codes_list(所有universe股票),但实际只需要factor_df中的股票**。当universe很大时(5000+),查T-1数据查全量 | MongoDB查询量过大 | 只查factor_df中实际存在的ts_code,减少_prev因子查询量 |
| P2-6 | portfolio_backtest.py | ~L2348 `_process_non_rebalance_day` | **非调仓日每次都调用_get_prices查所有持仓价格**。对于每日调仓模式,非调仓日只有周末/节假日(极少),但若改为周频调仓,每次都查MongoDB | 性能浪费 | 使用_daily_price_cache避免重复查询(已实现,但非调仓日未复用调仓日的缓存) |
| P2-7 | node.py | ~L201 | **_worker_loop中worker_count=1,但_start_workers创建worker时未传worker_id给execute_ultra_short_backtest**。日志中[Worker-0]标签无实际区分意义 | 代码冗余 | 当worker_count=1时可简化为直接调用,不走队列 |
| P2-8 | sell_signal_checker.py | L630 `check_full_sell` | **check_full_sell被标记为DEPRECATED但代码仍然完整**。注释说"never called in portfolio_backtest.py",但如果实盘模块调用就会与回测路径不一致 | 死代码 | 删除check_full_sell或在方法头添加DeprecationWarning |

---

## 回测结果优化建议

### 1. 止损6次(30%)改进方案

**分析**: 2周20笔交易中6次止损,止损率30%偏高。可能原因:
- 跳空低开导致止损价无法成交,实际亏损超过止损线(跳空误杀)
- 首板打板/半路追涨的3%止损在波动市中过窄

**建议**:
1. **拆分止损统计**: 将"跳空止损"从"止损"中独立出来,统计6次中各有几次
2. **跳空止损保护**: 当open低于止损价超过1%时(open < cost*(1-sl-0.01)),标记为"极端跳空",不触发SL而等待盘中反弹(仅适用于非跌停股)
3. **策略级SL微调**: 半路追涨SL从3%→3.5%可能减少1-2次跳空误杀,但盈亏比可能微降

**预期效果**: 止损次数从6→4-5次,止损率从30%→20-25%

### 2. 冲高回落7次(35%)改进方案

**分析**: 7次冲高回落远超止盈2次,说明大量利润在"冲高回撤"中被放弃。核心问题:
- pullback_mid_fallback_pct=1%(半路追涨)过于敏感,日内1%波动即触发
- 高开2%-5%区间只需回落1%即判定为"冲高回落",但2%高开+1%回落=仍盈利1%,不应该急于退出

**建议**:
1. **半路追涨mid_fallback从1%→1.5%**: 减少正常波动误触发
2. **添加最小冲高阈值**: open_rise<3%时不触发冲高回落(太小不算"冲高")
3. **冲高回落利润保护**: 如果close仍盈利≥3%,不触发冲高回落(让利润锁定/超时处理)
4. **龙头低吸mid_fallback从1.5%→2.0%**: 龙头低吸波动更大,需要更宽的回落阈值

**预期效果**: 冲高回落从7→3-4次,被截断的利润释放可提升总收益5-10%

### 3. 夏普比率18.26的合理性

**分析**: 2周(10交易日)回测,Sharpe=18.26极不合理:
- 年化因子sqrt(252)≈15.87,放大了短期的低波动
- 10天数据计算标准差自由度仅9,统计上不可靠
- 真实年化Sharpe可能在2-4之间

**建议**:
1. 短回测(<60天)Sharpe标注⚠️参考性低
2. 使用`annual_return_reliable`类似的`sharpe_reliable`标志
3. 添加最小交易日数限制: trading_days<20时不输出Sharpe

### 4. 止盈仅2次的改进

**分析**: 2次止盈 vs 7次冲高回落,说明大部分盈利交易被冲高回落提前截断,未到达止盈线。这是冲高回落过于敏感的直接证据。

**建议**: 先修复冲高回落(建议2),止盈次数自然会增加

### 5. 强制空仓冷却期参数调优

**分析**: 当前cooldown_days=2,cooldown_cap=0.6。V64从0.5→0.6,但2周回测中仅1次强制空仓,样本不足。

**建议**: 保持当前参数,等更长时间回测验证

---

## 回测-实盘一致性检查

| 检查项 | portfolio_backtest | sell_signal_checker | 实盘position_manager | 状态 |
|--------|-------------------|---------------------|----------------------|------|
| 止损价 | cost*(1-sl) | cost*(1-sl) | cost*(1-sl) | ✅一致 |
| 止盈价 | cost*(1+tp) | cost*(1+tp) | cost*(1+tp) | ✅一致 |
| 跳空止损 | open价 | open价 | open价 | ✅一致 |
| 冲高回落价 | open价 | open价 | open价 | ✅一致 |
| 利润保护价 | close价 | close价 | close价 | ✅一致 |
| 利润锁定价 | close价 | close价 | close价 | ✅一致 |
| 滑点规则 | should_apply_slippage | SLIPPAGE_RULES表 | should_apply_slippage | ✅一致 |
| SL取值 | min(所有策略) | min(所有策略) | SellSignalChecker | ✅一致 |
| TP取值 | strategies[0] | strategies[0] | strategies[0] | ✅一致 |
| next_day_open_sell_pct | 2%(V53) | 2%(V53) | 2%(V53) | ✅一致 |
| intraday_lock参数 | GLOBAL_RISK | GLOBAL_RISK | GLOBAL_RISK | ✅一致 |
| dragon_head_early_exit | GLOBAL_RISK可配 | N/A | GLOBAL_RISK可配 | ✅一致 |

**总体结论**: 回测-实盘参数已完全对齐(V62修复后)。主要风险点在P0-1(止损细分)和P0-2(冲高回落过早退出),不影响一致性但影响回测结果质量。
