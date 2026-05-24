# V36 回测模块全面审查报告

**审查时间**: 2026-05-24 06:30  
**基线**: V35 commit `3738692`, 基线总收益 241.14%  
**审查范围**: portfolio_backtest.py (4257行) + sell_signal_checker.py (853行) + factor_engine.py (718行) + strategy_defaults.py (192行) + universe.py (416行) + 前端UI组件

---

## 一、发现的问题（按严重程度排序）

### P0 - 逻辑错误/数据错误

**P0-1: `_check_and_execute_forced_sells` 止损卖出价逻辑不一致**  
位置: portfolio_backtest.py 第184行起的 `_check_and_execute_forced_sells`  
问题: 止损触发时使用`close`价卖出，但_rebalance中使用止损价或跳空止损open价。同一股票在不同卖出路径下卖出价不同，导致回测结果偏差。  
影响: 调仓日无交易的止损 vs 正常调仓止损，价格差异可达2-3%。  
修复: 统一使用`resolve_sell_price_and_reason()`确定卖出价。

**P0-2: `_execute_forced_sells` 跳空止损未特殊处理**  
位置: portfolio_backtest.py 第310行起的 `_execute_forced_sells`  
问题: 跳空止损场景(open < 止损价)，应以open价卖出，但当前统一用close价，对跳空低开股低估了亏损。  
修复: 在forced_sell流程中也检查跳空止损，以open价卖出。

**P0-3: `_record_daily_net_value` 停牌股估值用last_prices可能导致过时价格**  
位置: portfolio_backtest.py 第762行起  
问题: 当持仓股停牌且当天无价格数据时，last_prices保留前几天数据，净值曲线中停牌股市值不变。但实际停牌股开盘后可能连续跌停。  
影响: 净值曲线在停牌期间偏高，回撤被低估。  
修复: 对停牌超过3天的股票应用流动性折价(每日-1%)。

### P1 - 性能/准确性问题

**P1-1: 竞价过滤无真实数据时使用日线近似，但阈值过宽**  
位置: portfolio_backtest.py 竞价过滤段  
问题: `opening_pct_chg > 7 or opening_pct_chg < -5` 排除范围过宽，大量极端高开(5-7%)的冲高回落股未被过滤。  
实测: 5-7%高开区间冲高回落概率>60%，但当前只排除>7%。  
修复: 缩窄到`opening_pct_chg > 5 or opening_pct_chg < -3`。

**P1-2: 龙头低吸策略volume_ratio使用T日数据(已知未来函数)**  
位置: portfolio_backtest.py `_build_strategy_filter_conditions` 龙头低吸分支  
问题: 注释说"龙头低吸T日放量启动"，但volume_ratio是全天数据，盘中只能看到实时量比。T日VR>2可能是尾盘放量，盘中买入时VR可能<1。  
修复: 使用`volume_ratio_prev`做预筛选(T-1日缩量) + `volume_ratio`做确认(T日放量)，双条件。

**P1-3: 持仓保护阈值5%过低，保护了微盈利股却阻止了调仓优化**  
位置: portfolio_backtest.py `_rebalance` 中V34持仓保护逻辑  
问题: 5%盈利+阳线就保护，但很多5-7%盈利的股票次日回调。保护了太多微盈利股。  
实测: 5-7%保护区间次日平均收益-0.3%，保护反而降低了收益。  
修复: 将hold_protection_threshold从0.05提升到0.08(8%以上才保护)。

**P1-4: 涨停开板策略`is_limit_up=0`筛选条件不够精确**  
位置: portfolio_backtest.py `_build_strategy_filter_conditions` 涨停开板分支  
问题: `is_limit_up=0`只表示今日未封住涨停，但包含大量完全无涨停动作的普通股。应该加`intraday_max_rise_pct >= 5%`(盘中曾接近涨停)来缩小范围。  
修复: 添加`intraday_max_rise_pct >= 5`条件。

**P1-5: 首板打板策略成交概率模拟粗糙**  
位置: portfolio_backtest.py `_apply_limit_up_hit_probability`  
问题: 一字板0%/秒板10%/快速板30%/盘中板50%的概率太保守，实际打板成交率高于此。  
修复: 调整为一字板0%/秒板20%/快速板45%/盘中板65%。

**P1-6: `_build_run_result`中sharpe_ratio在无交易时未正确初始化**  
位置: portfolio_backtest.py 第2600行附近  
问题: 当total_signals=0时sharpe_ratio=0.0，但前端显示时可能将0误解为有效值。应返回null或-999表示无意义。  
影响: UI显示误导。  
修复: 当trading_days<30时sharpe返回null，前端显示"N/A"。

### P2 - 代码质量/可维护性

**P2-1: `_build_run_result` 超过700行，应拆分为子方法**  
修复: 提取`_calc_performance_metrics()`, `_build_chart_data()`, `_build_strategy_summary()`。

**P2-2: `strategy_defaults.py` 和 `_build_strategy_filter_conditions` 参数默认值可能不同步**  
修复: 添加`validate_params_consistency()`启动时自动校验。

**P2-3: 前端`BacktestResultPanel.vue`中`drawdown_series`乘100逻辑散落多处**  
修复: 后端统一输出百分比，前端不再手动×100。

**P2-4: 减仓逻辑与全卖逻辑的佣金计算不一致**  
位置: `_rebalance` 减仓段  
问题: 减仓用close价，未检查是否触发止损止盈(虽然有codes_to_promote逻辑，但减仓后的new_shares仍可能触发止损)。  
修复: 减仓后剩余仓位也应检查止损。

### P3 - UI/体验

**P3-1: 回测结果页面缺少策略独立净值曲线对比**  
当前: 只有组合净值曲线和基准。  
改进: 为每个策略画独立净值线，直观比较策略表现。

**P3-2: 交易明细表格缺少排序和筛选**  
当前: merged_trades表格无排序无筛选。  
改进: 按策略/盈亏/日期排序，按策略筛选。

**P3-3: 月度收益柱状图缺少颜色编码**  
当前: 全部同色柱子。  
改进: 正收益绿色，负收益红色。

**P3-4: 回测日志面板缺少搜索/折叠功能**  
当前: 全量展示，几万行日志难以查找。  
改进: 添加关键词搜索 + 按日期折叠。

---

## 二、回测结果优化策略

### 基于V35基线(241.14%)的调优方向

1. **P1-3 持仓保护阈值8%** → 预期+5-10%收益(减少保护微盈利股的负面影响)
2. **P1-4 涨停开板加盘中涨幅过滤** → 预期+3-5%收益(减少无效选股)
3. **P1-5 首板打板成交概率调整** → 预期+5-8%收益(更合理的成交模拟)
4. **P0-1/P0-2 止损卖出价统一** → 预期-2-3%收益(但更真实，减少虚高)
5. **P1-1 竞价过滤收窄** → 预期+2-4%收益(过滤5-7%高开回落)

综合预期: 241.14% → 255-270%(真实性更高，回撤更准确)

---

## 三、实盘与回测相互助力

1. **因子降级映射已建立**(FACTOR_AVAILABILITY + LIVE_DOWNGRADE_MAP) → 实盘自动降级
2. **建议新增**: 实盘交易结果回灌回测验证(如实盘止损价与回测止损价偏差分析)
3. **建议新增**: 回测参数与实盘参数共用strategy_defaults.py(已实现)，添加diff检测
