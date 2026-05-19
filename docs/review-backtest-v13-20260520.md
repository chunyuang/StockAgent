# 回测V13审查报告 - 全面代码审查+优化

## 基线(V12): 收益23.86% 夏普4.42 回撤3.72% 胜率49.09% 盈亏比2.11 交易110笔 耗时17.9s

---

## P0级(影响结果正确性)

### P0-1: `_process_non_rebalance_day`中`_prices_for_display`变量作用域泄漏
- **文件**: portfolio_backtest.py:1859
- **问题**: `_prices_for_display`在if分支(forced_sell_codes)内赋值，但在if/else之后使用时
  用`try: _prices_for_display`检查存在性。但如果holdings为空(不进入if也不进入else)，
  后面引用`_prices_for_display`会NameError
- **修复**: 在方法开头初始化`_prices_for_display = {}`

### P0-2: 调仓日冲高回落/利润保护检查中`_close_p`变量未定义
- **文件**: portfolio_backtest.py:1552-1558
- **问题**: 调仓日无交易记录时的冲高回落检查中，`_close_p`在`elif sname == '半路追涨' and open_rise >= 0.05`
  分支内引用，但未在循环外定义。如果第一个策略不是跌停翘板/首板打板，
  `_close_p`变量不存在→NameError
- **修复**: 在循环前初始化`_close_p = p.get('close', 0)`

### P0-3: `_rebalance`卖出时减仓股的cost_basis未按FIFO分摊
- **文件**: portfolio_backtest.py:3840-3860
- **问题**: 减仓时直接删除cost_basis(如果holdings降为0)，但部分减仓时保留原成本。
  这在增仓后减仓场景下，cost_basis是加权平均成本，但amount字段是买入时的总金额，
  FIFO匹配时用amount/shares计算每股成本可能不准确
- **影响**: 低概率(减仓场景少)，但合并交易盈亏可能计算偏差

### P0-4: `factor_engine.py`中pre_close为0时intraday因子产生inf
- **文件**: factor_engine.py:119-126
- **问题**: `result["pre_close"].replace(0, np.nan)`在replace后直接做除法，
  但如果pre_close整列为0(新上市首日等)，结果全是NaN→半路追涨条件筛选时
  intraday_max_rise_pct为NaN→该股被过滤掉
- **修复**: 在计算后用fillna(0)填充NaN，避免正常股票因0值被误杀

---

## P1级(影响结果质量/可维护性)

### P1-1: `enable_force_empty`参数读取路径过于复杂(5层fallback)
- **文件**: ultra_short.py:74-80
- **问题**: `enable_force_empty = params.get("enable_force_empty", req_params.get("enable_force_empty", req_params.get("params", {}).get("enable_force_empty", True)))`
  5层嵌套fallback，极易出错且难以调试
- **修复**: 简化为2层: params顶层→默认值

### P1-2: `_print_market_environment`返回sentiment_level含中文逗号+仓位系数
- **文件**: portfolio_backtest.py:247
- **问题**: 返回值sentiment_level="高潮期,仓位系数1.0"，调用方需要用
  `_extract_position_multiplier`解析出仓位系数。但_process_rebalance_day中
  用sentiment_level做条件判断(如`if "depression" in sentiment_level`)，
  语义不清晰
- **修复**: 分离返回值: (sentiment_period, position_multiplier, sentiment_score, limit_up_count, limit_down_count)

### P1-3: `_strategy_signal_stats`按策略名统计但策略筛选时按strategy_id
- **文件**: portfolio_backtest.py:1285
- **问题**: signal_stats的key是strategy_name(中文)，但策略配置按strategy_id(英文)
  查找。如果中文策略名改了，统计就断了
- **影响**: 低(当前中文名稳定)，但代码耦合不必要

### P1-4: `_get_prices`每日缓存只生效1次就被覆盖
- **文件**: portfolio_backtest.py:2905
- **问题**: `_get_prices`在同一天被调用2-3次(调仓日: 获取价格→止损止盈→净值记录)。
  缓存逻辑是`if cache_date == trade_date`，但第二次调用时cache已包含第一次结果，
  只查missing stocks。第三次调用时cache仍然有效，可以完全命中。
  但有个问题: `_daily_price_cache_date`是int，而trade_date在_run_impl循环中
  已转为int，所以缓存应该正常工作。
  **实际测试确认缓存生效**，此项降级为确认OK。

### P1-5: 涨停开板策略默认关闭但仍在ALL_STRATEGIES中
- **文件**: strategy_defaults.py:73
- **问题**: `limit_up_open`的enabled=False，但ALL_STRATEGIES包含所有5个策略。
  当前端不传selected_strategies时，兜底用ALL_STRATEGIES会包含未启用的涨停开板
- **修复**: ALL_STRATEGIES只包含enabled=True的策略

### P1-6: 跌停翘板circ_mv硬编码200000(20亿)而非从参数读取
- **文件**: portfolio_backtest.py:3348
- **问题**: `{"name": "circ_mv", "target": 200000, ...}` 硬编码了20亿门槛，
  但STRATEGY_CONFIGS中定义了`min_circulation_market_cap: 20`。参数未生效
- **修复**: 从params读取min_circulation_market_cap并×10000转换

### P1-7: 半路追涨max_open_rise_pct条件用intraday_open_rise_pct但
  因子计算依赖pre_close，而pre_close在stock_daily_ak_full中经常为0
- **文件**: portfolio_backtest.py:3188, factor_engine.py:119
- **问题**: pre_close=0→intraday_open_rise_pct=NaN→开盘涨幅条件跳过→
  高开>3%的股票未被过滤(半路追涨核心过滤条件失效)
- **修复**: factor_engine中pre_close为0时用前一日close替代

### P1-8: daily_profit序列在result顶层和metrics.positions中格式不一致
- **文件**: portfolio_backtest.py:2610-2612
- **问题**: result["daily_profit"]归一化为小数(÷initial_cash)，
  但metrics.positions.daily_profit是原始daily_profit_list(绝对值)。
  前端如果从不同路径读取会显示不同结果
- **修复**: 统一为归一化小数格式

---

## P2级(代码质量/性能优化)

### P2-1: `_process_rebalance_day`和`_process_non_rebalance_day`中
  止损止盈检查代码大量重复(约120行)
- **修复**: 提取为_check_stop_loss_take_profit方法

### P2-2: ultra_short.py中参数读取的5层fallback重复6个enable_*变量
- **修复**: 提取为辅助函数

### P2-3: `_build_run_result`方法960行过长
- **说明**: 暂不拆分(涉及run_state dict传递复杂度)，仅标注

### P2-4: GC频率过高(每5天一次)，可降低为每10天
- **文件**: portfolio_backtest.py:613
- **影响**: 5天一次GC在51天回测中触发10次，改为10天→5次，预计节省1-2秒

---

## 结果优化建议

### R1: 半路追涨策略信号过滤条件优化
- 当前pct_chg≥3%(收盘确认)在日线回测中是未来函数
- 但因子intraday_max_rise_pct已解决盘中最高涨幅问题
- 建议: 将pct_chg收盘确认条件改为intraday_max_rise_pct≥3% AND close≥open
  (收盘价≥开盘价=阳线，确认涨势持续到收盘，比pct_chg≥3%更宽松更合理)

### R2: 跌停翘板增加circ_mv参数化(见P1-6)
