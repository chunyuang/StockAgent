# 回测模块V9审查报告

**日期**: 2026-05-19 23:30  
**分支**: feature/live-trading  
**基线commit**: 6b46928  
**审查范围**: 回测引擎全链路(后端+前端+数据流)

---

## 🔴 P0级问题 (必须修复)

### P0-1: 因子自动计算导致OOM/阻塞
**文件**: `factor_auto_compute.py:148-170`  
**问题**: `_compute_and_write_factors`将整月全市场数据(~5370股×22天=118K行)加载到内存,
再按股票groupby计算,内存峰值~2GB+。且计算是同步CPU密集型,阻塞asyncio事件循环,
导致Web服务器回测期间完全无响应(health check超时)。
**影响**: 24个缺失因子→3个月×118K行→~3分钟阻塞→前端无法查询进度/结果
**修复**: 
1. 因子自动计算改为`asyncio.to_thread`或`run_in_executor`避免阻塞事件循环
2. 添加内存限制:仅计算核心策略必需的因子(如opening_pct_chg),非核心因子跳过
3. 大区间回测(>100天)跳过因子预检测,依赖已补算的数据

### P0-2: 调仓日分支逻辑错误 — 非调仓日代码在`else`分支内
**文件**: `portfolio_backtest.py:1393-1420`  
**问题**: `_process_rebalance_day`方法中,调仓执行成功后的代码结构:
```python
if len(records) > 0:
    # 打印调仓记录...
else:  # ← BUG: 这不是"非调仓日",而是"调仓日无交易"
    run_state = await self._process_non_rebalance_day(...)
```
`else`分支语义是"调仓日无交易记录",但调用了`_process_non_rebalance_day`(含止损止盈检查)。
当调仓日产生了交易但`records`为0时(如全部现金不足),止损止盈检查被跳过。
更严重的是,`_process_non_rebalance_day`的返回值可能覆盖调仓日已更新的run_state。
**修复**: 将`else`改为独立的止损止盈检查,不委托给`_process_non_rebalance_day`

### P0-3: 盈亏比(profit_loss_ratio)基于日收益而非交易收益
**文件**: `portfolio_backtest.py:2196-2197`  
**问题**: 盈亏比计算用的是`daily_profit_list`(每日组合盈亏),而非交易级盈亏。
日收益模式: 10只持仓,5只涨5只跌,日收益为正→只算"1次盈利";
交易模式: 5笔赚5笔亏→正确反映策略选股能力。
**当前**: `total_profit / total_loss` (日维度,高频)
**应为**: 交易维度 `avg_win_trade_pct / avg_loss_trade_pct`
**影响**: 盈亏比虚高(日收益正的天数多),误导策略评估

### P0-4: 净值计算在调仓日双写
**文件**: `portfolio_backtest.py:1421-1427`  
**问题**: 调仓日正常流程:
1. `_process_rebalance_day`内部: 如果跳过(无候选/强制空仓等),函数末尾已调用`_record_daily_net_value`
2. `_process_rebalance_day`正常流程末尾(line 1421-1427): 又调用`_record_daily_net_value`
3. 如果调仓日走else分支(无交易),`_process_non_rebalance_day`返回后,又调`_record_daily_net_value`

而强制空仓/无候选等提前return的路径,只调了一次`_record_daily_net_value`。
→ 同一天的净值可能被记录2次(一次在非调仓日处理,一次在统一净值记录),导致:
- `net_value_series`长度与`all_trade_dates`不一致
- 前端图表日期错位
- 月度收益计算偏移

**修复**: 统一净值记录点,删除`_process_non_rebalance_day`中的净值记录,
只在`_run_impl`主循环中每日结束时统一调用一次。

---

## 🟠 P1级问题 (影响准确性/体验)

### P1-1: 冲高回落/高开即卖在调仓日和非调仓日重复检查
**文件**: `portfolio_backtest.py:1572-1592` (非调仓日) + `portfolio_backtest.py:3410-3428` (调仓日_rebalance)  
**问题**: 同一只股票同一天可能同时被两个路径检查:
1. `_process_rebalance_day`中`_rebalance`卖出时检查冲高回落
2. `_process_non_rebalance_day`中也检查冲高回落(调仓日无交易的else分支)

如果调仓日有交易,`_rebalance`已处理冲高回落卖出;
但如果else分支也被执行(代码结构问题P0-2),同一股票可能被尝试重复卖出。
**修复**: 冲高回落检查只在`_rebalance`中执行一次,`_process_non_rebalance_day`不重复检查

### P1-2: 止损止盈不扣滑点导致实际收益偏高
**文件**: `portfolio_backtest.py:1616-1617` + `portfolio_backtest.py:3430-3431`  
**问题**: 止损/止盈卖出时不扣滑点(`slippage_pct = 0`),理由是"止损价已含保守估计"。
但止盈价=成本*(1+止盈%),不含保守估计;且止损价用stop_price而非close,
已经是保守价了,不扣滑点意味着实盘必然达不到回测的止盈价。
**影响**: 回测收益系统性偏高(尤其高频止损止盈策略)
**修复**: 止损仍不扣滑点(止损价已保守),但止盈应扣滑点(止盈价不含保守)

### P1-3: 策略级profit_loss_ratio计算错误
**文件**: `portfolio_backtest.py:2541-2542`  
**问题**: `strategy_losses_pnl = sum(t.get('profit_pct', 0) for t in completed if t.get('profit_pct', 0) < 0)`
`profit_pct`是负数,所以`strategy_losses_pnl`也是负数。
然后: `strategy_wins_pnl / abs(strategy_losses_pnl)` — abs后除,正确。
但当`strategy_losses_pnl < 0`时(总是),条件`strategy_losses_pnl < 0`永远True,
所以`else`分支(99.99/0.0)只在无亏损时触发 — 逻辑正确,但`strategy_losses_pnl == 0`的
判断条件应该是`strategy_losses_pnl == 0`(浮点数),不是`< 0`。
**修复**: 改为 `if abs(strategy_losses_pnl) > 0.001`

### P1-4: 调仓日`records`为空时跳过持仓显示
**文件**: `portfolio_backtest.py:1393-1420`  
**问题**: `if len(records) > 0`的else分支内,调用了`_process_non_rebalance_day`,
但该方法的日志输出与调仓日不匹配(显示"调仓日无交易"而非调仓结果)。
更关键的是,调仓日成功执行了买卖但`records`为0(不应发生但防御性编程),
此时持仓显示被跳过。
**修复**: 持仓显示和日终汇总应在所有路径都执行,不受`records`长度影响

### P1-5: 月度收益计算基于daily_profit_list(绝对值),与净值序列不一致
**文件**: `portfolio_backtest.py:2608-2630`  
**问题**: 月度收益从`daily_profit_list`(绝对盈亏额)计算,
但前端期望的是与净值序列一致的收益率。
如果`daily_profit_list`未归一化(某些路径写入绝对值),月度收益可能>100%或<0异常。
**修复**: 月度收益统一从`net_value_series`计算(归一化净值),确保一致性

### P1-6: 基准数据查询4次回退过于冗余
**文件**: `portfolio_backtest.py:2302-2356`  
**问题**: `_load_benchmark_data`有4级回退:index_daily(int) → index_daily(str) → 
000001.SH → stock_daily_ak_full → 510050/510300/510500 ETF。
每次回退都是一次完整MongoDB查询,最坏情况7次查询。
**修复**: 第一次查询用`$or`同时查int和string格式的trade_date,减少到1次

---

## 🟡 P2级问题 (代码质量/可维护性)

### P2-1: run_state dict传递37个字段,极易出错
**问题**: `_process_rebalance_day`/`_process_non_rebalance_day`/`_build_run_result`
三个方法都要从run_state解包37个字段,每次修改新增字段需同步4处代码。
**建议**: 改用dataclass或namedtuple,IDE可检查字段遗漏

### P2-2: 净值序列初始化插入1.0的首日记录可能重复
**文件**: `portfolio_backtest.py:1957-1964`  
**问题**: `_build_run_result`中,如果首日净值已经是1.0(调仓第一天cash未变),
`net_value_series[0].net_value == 1.0` → 不插入 → 正确。
但如果首日有交易(如买入),净值可能不是1.0 → 插入1.0记录 → 
net_value_series长度 = all_trade_dates + 1 → 前端日期错位1天。
**修复**: 检查首条记录的trade_date是否等于start_date,如果是则修改而非插入

### P2-3: 日志推送每10条让出事件循环不够
**文件**: `node.py:272`  
**问题**: `self._log_count % 10 == 0: await asyncio.sleep(0)` — 
回测每天约20-30条日志,50天回测约1000-1500条日志,仅让出100-150次。
因子自动计算期间完全阻塞,无法让出。
**修复**: 在CPU密集型计算(factor_auto_compute/factor_engine)中也定期让出

### P2-4: _print_market_environment中combined_pipeline每次重建
**文件**: `portfolio_backtest.py:205-240`  
**问题**: 每个交易日都重建相同的聚合管道,可在初始化时构建一次复用。
**修复**: 将pipeline模板存为类常量或实例变量

### P2-5: 前端BacktestResultPanel未检查backtest结果的daily_profit归一化
**问题**: 后端`daily_profit`已归一化为小数(÷initial_cash),但前端可能仍按绝对值显示。
需验证前端是否正确处理了归一化后的值。

### P2-6: 策略筛选条件`is_limit_up`因子可能不存在于factor_df
**文件**: `portfolio_backtest.py:3165`  
**问题**: 涨停开板策略筛选条件`{"name": "is_limit_up", "target": 0}`,
但`is_limit_up`不在`ultra_short_factors`列表中(factor_engine未计算)。
`_print_single_strategy_filtering`会输出"因子缺失跳过"。
**修复**: 在ultra_short_factors中添加`is_limit_up`,或在涨停开板筛选条件中
用`pct_chg < 9.8`替代`is_limit_up == 0`

---

## 📊 回测结果优化建议

### R1: 冲高回落保护应增加"盘中回落实锤"条件
当前: 次日高开3%即卖(仅看open vs cost)  
问题: 高开后可能继续涨,过早卖出丢失利润  
建议: 增加`close < open`条件(高开低收=确认回落),或`low < cost * 1.01`(回落到成本附近)

### R2: 首板打板成交概率模型可优化
当前: 一字0%/秒板30%/正常50%/慢板70% (hash确定性模拟)  
问题: 概率固定不考虑市场环境(牛市成交率高/熊市低)  
建议: 乘以情绪系数(rising*1.2, chaos*0.8, depression*0.5)

### R3: 跌停翘板筛选条件过于宽松
当前: 昨日跌停 + 今日不继续跌停 + 市值≥20亿 + 换手率≥10%  
问题: 无翘板金额/翘板后涨幅要求(日线数据无法精确计算)  
建议: 用`pct_chg > 0`(今日收涨)替代rise_after_limit_down,
避免选到"不跌停但也没涨"的弱势股

### R4: 仓位管理优化 — 动态仓位根据回撤调整
当前: 情绪系数*特殊时期系数*单票上限 = 固定乘积  
建议: 引入"回撤调仓"——组合回撤>5%时,整体仓位降50%;回撤>10%时降80%

---

## 🔧 修复优先级

| 优先级 | 编号 | 预估工时 | 影响 |
|--------|------|----------|------|
| P0-1 | 因子自动计算阻塞 | 1h | 回测不可用 |
| P0-2 | 调仓日else分支逻辑 | 0.5h | 交易逻辑错误 |
| P0-3 | 盈亏比计算维度 | 0.5h | 指标失真 |
| P0-4 | 净值双写 | 1h | 数据不一致 |
| P1-1 | 冲高回落重复检查 | 0.5h | 潜在重复卖出 |
| P1-2 | 止盈扣滑点 | 0.5h | 收益偏高 |
| P1-3 | 策略级PLR边界 | 0.2h | 边界case |
| P1-5 | 月度收益一致性 | 0.5h | 图表偏移 |
| P2-6 | is_limit_up因子缺失 | 0.3h | 涨停开板0候选 |
