# V16回测模块审查报告

**审查日期**: 2026-05-20
**审查范围**: portfolio_backtest.py (3963行) + factor_engine.py (631行) + strategy_defaults.py + strategy_filter.py + ultra_short.py
**基线版本**: commit a6d5b21 (V15)
**基线结果**: 2策略(半路追涨+跌停翘板) 收益70.12% 夏普8.81 回撤3.00% 胜率69.23% 104笔

---

## 审查发现 (按优先级)

### P0级 (数据正确性/逻辑错误)

**P0-1: 非调仓日未记录净值**
- 位置: `_process_non_rebalance_day` 末尾
- 问题: 方法未调用 `_record_daily_net_value`，导致非每日调仓模式下净值序列有空洞
- 影响: 当前每日强制调仓不受影响，但代码架构有隐患
- 修复: 末尾添加 `_record_daily_net_value` 调用

**P0-2: 非调仓日 `last_prices` 未更新**
- 位置: `_process_non_rebalance_day`
- 问题: `last_prices` 从run_state解包后从未赋新值，非调仓日价格是前次调仓日的过期数据
- 影响: 非每日调仓模式下，后续净值计算使用过期价格
- 修复: 用当天获取的 `_sl_tp_prices` 或 `_prices_for_display` 更新 `last_prices`

**P0-3: 冲高回落卖出reason未统一分类**
- 位置: `_check_early_sell_signals` 和 `_rebalance` 的卖出逻辑
- 问题: 冲高回落reason含价格细节如 `冲高回落(开40.05涨9.7%)`，导致前端统计时每条都是独立分类
- 影响: 前端卖出原因统计有12个冲高回落条目，无法聚合
- 修复: reason改为固定分类 `冲高回落`/`高开即卖`/`利润保护`，价格细节存入record扩展字段

**P0-4: 强制空仓卖出价格逻辑不一致**
- 位置: `_process_rebalance_day` 强制空仓分支
- 问题: 注释说"用open价(开盘看到极端行情立即卖出)"，但代码 `price = prices_for_sell[code].get('open', 0) or prices_for_sell[code]['close']` 在open=0时回退到close
- 影响: 停牌股open=0时回退到close也=0，最终走_last_valid_price，逻辑正确但注释误导
- 修复: 注释修正 + open=0时统一用_last_valid_price

### P1级 (逻辑/模拟精度)

**P1-1: 半路追涨收盘确认pct_chg存在轻微未来函数**
- 位置: `_build_strategy_filter_conditions` 半路追涨的 `pct_chg` 条件
- 问题: `pct_chg >= 5` 是收盘涨跌幅，实盘需等到收盘才确认。但14:50后可预判是否站稳5%，回测近似可接受
- 影响: 回测信号可能比实盘早几小时确认
- 建议: 可接受，不修改(已在V11注释中说明)

**P1-2: 跌停翘板min_circulation_market_cap默认20亿偏小**
- 位置: `strategy_defaults.py` limit_down_qiao params
- 问题: 20亿流通市值仍可能包含小盘操纵风险股。30亿更安全
- 影响: 可能选到被操纵的小盘翘板股
- 建议: 提升至30亿（与龙头低吸一致）

**P1-3: _build_run_result中持仓天数计算用日历天数不准确**
- 位置: `_build_run_result` merged_trades构建
- 问题: `hold_days = (sd - bd).days` 是日历天数，非交易日。3天持仓=1交易日+2周末
- 影响: 前端显示持仓天数偏大
- 修复: 用all_trade_dates计算交易日天数

**P1-4: 减仓后cost_basis未按比例更新**
- 位置: `_rebalance` 减仓分支
- 问题: 部分减仓时保留原cost_basis不变。如果多次减仓，剩余持仓的成本不变是正确的（卖出不影响剩余持仓成本）
- 结论: 逻辑正确，不需修改

**P1-5: 策略筛选条件strategy_filter.py与portfolio_backtest.py不同步**
- 位置: `strategy_filter.py` vs `portfolio_backtest.py._build_strategy_filter_conditions`
- 问题: strategy_filter.py是拆分产物但未被调用，且跌停翘板条件缺少pct_chg>0和sentiment_period_in
- 影响: 无直接影响（未被调用），但代码维护性差
- 建议: 后续Phase统一，当前不修改

**P1-6: _check_early_sell_signals中跌停翘板冲高回落阈值取strategy的next_day_open_sell_pct**
- 位置: `_check_early_sell_signals` 跌停翘板分支
- 问题: 跌停翘板用 `sp.get('next_day_open_sell_pct', 0.03)` 取阈值，但跌停翘板策略的riskParams未定义此参数
- 影响: 始终用默认值0.03(3%)，这对跌停翘板来说可能偏低（翘板股波动大，3%高开很常见）
- 修复: 跌停翘板的冲高回落阈值应更高(5%)，因为翘板股次日波动大

### P2级 (代码质量/性能)

**P2-1: _print_single_strategy_filtering 方法过长(~150行)**
- 问题: 包含5个策略的参数显示逻辑，每个策略约30行
- 建议: 后续提取为策略参数显示策略模式，当前不动

**P2-2: 买入价模拟可考虑盘中波动率**
- 位置: `_get_buy_price_for_stock`
- 问题: 半路追涨买入价 open*(1+min_rise*0.8) 是固定系数，未考虑个股波动率
- 建议: 可用ATR或amplitude因子调整系数，但增加复杂度，当前不动

**P2-3: MongoDB查询优化**
- `_print_market_environment` 的聚合查询已在V8优化为单次
- `_get_prices` 已在V12优化为$in过滤
- 当前查询模式合理，无明显优化空间

**P2-4: factor_df内存释放**
- 位置: `_process_rebalance_day` 末尾
- 当前已做 `del factor_df` + `gc.collect()`，合理

---

## 修复计划

| 编号 | 优先级 | 修复内容 | 预期影响 |
|------|--------|----------|----------|
| P0-1 | P0 | 非调仓日添加_record_daily_net_value | 非每日调仓模式净值完整 |
| P0-2 | P0 | 非调仓日last_prices更新 | 非每日调仓模式价格正确 |
| P0-3 | P0 | 冲高回落/高开即卖/利润保护reason统一分类 | 前端统计正确聚合 |
| P0-4 | P0 | 强制空仓卖出注释+逻辑统一 | 代码清晰 |
| P1-2 | P1 | 跌停翘板min_circ_mv 20→30亿 | 减少小盘操纵风险 |
| P1-3 | P1 | 持仓天数改用交易日 | 显示准确 |
| P1-6 | P1 | 跌停翘板冲高回落阈值3%→5% | 减少过早卖出 |

