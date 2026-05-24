# V47 优化变更日志

**日期**: 2026-05-24
**基线**: V41 (total_return=147.22%, max_drawdown=3.03%, win_rate=73.47%, sharpe=13.00)
**最新结果**: V47d (total_return≈190%, max_drawdown≈4.7%, win_rate≈75%, sharpe≈10.4)

---

## 📊 回测结果对比

| 指标 | V41基线 | V47d | 变化 |
|------|---------|------|------|
| 总收益 | 147.22% | ~190% | **+42.8%** ✅ |
| 最大回撤 | 3.03% | ~4.7% | +1.7% ⚠️ |
| 胜率 | 73.47% | ~75% | **+1.5%** ✅ |
| 夏普 | 13.00 | ~10.4 | -2.6 ⚠️ |
| 盈亏比 | 3.03 | ~2.7 | -0.3 ⚠️ |
| 交易笔数 | 98 | ~101 | +3 |

**注**: 回测结果有±3%的非确定性波动(字典迭代顺序)

---

## 🔧 回测模块优化

### V47 核心优化 (commit 3e1cd86)
1. **龙头低吸max_hold_days 5→7天**: 51.69%和33.55%的超时退出说明5天太短截断大牛
2. **利润锁定阈值放宽**: intraday_lock_min_high_rise 0.06→0.05, intraday_lock_pullback_pct 0.025→0.02 (此前0触发,需降低门槛)
3. **龙头低吸冲高回落利润>8%不触发**: pullback_profit_lock_threshold=0.08, 避免冲高回落过早截断大牛
4. **实盘position_manager新增SellSignalChecker**: 与回测对齐冲高回落/利润保护/利润锁定/高开即卖信号

### V47b (commit 7920699)
1. **P0-NEW-1修复**: monthly_profit改用net_value_series计算,避免daily_profit_list浮点累加误差
2. **P1-NEW-2修复**: 持仓保护排除一字涨停(涨停开板风险大)
3. **实盘止损区分跳空止损**: position_manager.daily_check区分跳空止损(open≤stop_loss)和正常止损
4. **paper_trading止损/止盈用对应价格**: 旧bug用current_price(收盘价),现在止损用stop_loss_price,止盈用take_profit_price

### V47c (commit 9390c56)
1. **max_position_per_stock 20%→35%**: 3只均分=33%,留2%buffer,避免资金闲置(旧20%*3=60%仅用60%资金)

### V47d (commit 61da6cc)
1. **strategy_filter添加filter方法**: generate_daily_signals依赖,修复ImportError
2. **sell_signal_checker TP保持min**: check_full_sell是DEPRECATED,保持min与现有逻辑一致
3. **generate_daily_signals用策略级风控参数**: 从STRATEGY_CONFIGS读取stop_loss_pct/take_profit_pct,移除sentiment adjust

---

## 🎨 UI优化

### MarketMonitorView暗色模式 (commit 9390c56)
- **150处硬编码颜色→CSS变量**: 从150个降至10个(仅保留策略品牌色)
- 全面支持暗色模式,不再白底白字不可用

### StockDetailView/BacktestHistoryPanel/DbAdminView (commit b1de4f7)
- **66处硬编码颜色→CSS变量**
- StockDetailView 19处→基本清除
- BacktestHistoryPanel 24处→基本清除
- DbAdminView 部分修复

### BacktestResultPanel/DataStatusPanel (pending backtest-panel-darkmode子代理)
- **72处硬编码颜色→CSS变量**
- BacktestResultPanel 39处
- DataStatusPanel 33处
- StrategyFactorPanel 12处
- UltraShortBacktestViewV2 12处

---

## 🔄 回测-实盘协同

1. **卖出信号代码共享**: 实盘position_manager新增_check_early_sell_signals,与回测SellSignalChecker逻辑一致
2. **止损/止盈价格对齐**: 实盘止损用止损价而非收盘价,跳空止损区分并提示
3. **策略级风控参数对齐**: generate_daily_signals从strategy_defaults读取策略级参数,不再用全局参数
4. **strategy_filter.filter()**: 统一筛选方法,generate_daily_signals不再依赖硬编码

---

## 🐛 Bug修复

1. **monthly_profit浮点误差**: 改用net_value_series计算(P0-NEW-1)
2. **一字涨停被持仓保护**: 排除一字涨停(P1-NEW-2)
3. **实盘止损价不一致**: paper_trading用收盘价→改用止损价/跳空用open
4. **generate_daily_signals ImportError**: strategy_filter.py缺少filter_stocks_by_strategies
5. **实盘止损/止盈显示不一致**: 显示文本改用策略级参数(P0-4)
6. **首板打板turnover_rate/circ_mv未来函数**: 已用_prev版本(前次修复)

---

## ⚠️ 已知限制

1. **首板打板策略胜率低(42.9%)**: 跳空止损-10.96%/-7.86%是固有的策略风险,无法通过参数调优避免
2. **回测非确定性**: MongoDB查询顺序导致±3%的结果波动
3. **max_drawdown增加(3.03%→4.7%)**: 主要由首板打板跳空止损驱动
4. **check_full_sell TP不一致**: 与_get_sl_tp_for_code用strategies[0]不同,但check_full_sell是DEPRECATED暂不修复

---

## 📋 待办事项

- [ ] 首板打板策略质量提升(更严格的筛选条件或降低仓位)
- [ ] ECharts图表暗色模式(BacktestResultPanel中itemStyle硬编码颜色)
- [ ] FactorReferencePanel CSS颜色→变量(20处)
- [ ] paper_trading.daily_settlement完整对齐SellSignalChecker(冲高回落等)
- [ ] 实盘T+1约束(P1-5)
- [ ] 回测确定性改进(排序因子DataFrame)
