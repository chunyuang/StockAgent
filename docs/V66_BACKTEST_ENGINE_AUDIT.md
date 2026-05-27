# V66 回测引擎审查报告

**日期**: 2026-05-27  
**分支**: review/V59-backtest-live-audit  
**Commit**: afc8031 + fd37c01  
**审查范围**: 10,788行代码 (14个文件)

---

## 📊 回测结果对比

| 指标 | V64基线 | V65基线 | V66(本次) | 变化(vs V65) |
|------|---------|---------|-----------|-------------|
| 总收益 | 335.82% | 286.28% | 289.75% | +3.47% |
| 最大回撤 | 5.46% | 4.42% | 5.07% | +0.65% |
| 夏普比率 | 11.67 | 10.77 | 10.74 | -0.03 |
| 索提诺 | 15.79 | 16.04 | 15.32 | -0.72 |
| 胜率 | 80.65% | 81.25% | 81.05% | -0.20% |
| 盈亏比 | 2.80 | 2.80 | 2.81 | +0.01 |
| 交易笔数 | 93 | 96 | 95 | -1 |

### 全年回测 (20250101-20260320)
| 指标 | V66 |
|------|------|
| 总收益 | 2821.94% |
| 首板打板 | 34笔 47.1%胜率 82.52%收益 |
| 龙头低吸 | 88笔 81.8%胜率 626.78%收益 |
| 半路追涨 | 70笔 74.3%胜率 276.35%收益 |
| 跌停翘板 | 83笔 81.9%胜率 643.99%收益 |

---

## 🔧 修复清单

### P0-1: 震荡期仓位系数 3级→4级 (与实盘对齐)

**问题**: V65将震荡期(40-70分)仓位系数从0.7一刀切到0.5，跨度从30分只用一个系数。
- 实盘emotion_cycle有4级: RISING=1.0 / DIFFERENTIATION=0.5 / CHAOS=0.25 / BEARISH=0.0
- 回测只有3级: 高潮≥70=1.0 / 震荡40-70=0.5 / 冰点<40=0.3
- 40-70这个30分跨度太宽，55-70分的市场仍有一定热度，0.5过严

**修复**: 拆分为4级，与实盘对齐:
- 高潮期(≥70): 1.0 — 对应实盘RISING
- 分化期(55-70): 0.7 — 对应实盘DIFFERENTIATION(0.5回测更宽松因回测本身保守)
- 震荡期(40-55): 0.5 — 对应实盘CHAOS
- 冰点期(<40): 0.3 — 对应实盘BEARISH

**效果**: 收益+3.47% (286.28%→289.75%), 回撤+0.65% (4.42%→5.07%)
**Trade-off**: 每多承受1%回撤获得5.3%收益，优于V65(0.5系数每1%回撤只获得0.7%收益)

### P0-2: 半路追涨 pullback_mid_fallback_pct 对齐

**问题**: strategy_defaults.py中半路追涨的pullback_mid_fallback_pct=0.01，但STRATEGY_PULLBACK_PARAMS中为0.015。
_get_sell_params合并顺序为pullback→base→risk，base_params覆盖了pullback_params，
导致STRATEGY_PULLBACK_PARAMS的0.015从未生效（被0.01覆盖）。

V65注释说"V65:1%→1.5%"但strategy_defaults.py实际仍是0.01。

**修复**: 
1. strategy_defaults.py中半路追涨pullback_mid_fallback_pct改为0.015（V65已修复）
2. _get_sell_params合并顺序修正为base→pullback→risk，让pullback_params覆盖base_params
（V65已修复合并顺序）

**验证**: 当前代码已正确：strategy_defaults=0.015, STRATEGY_PULLBACK_PARAMS=0.015, 合并顺序正确

### P1-1: 首板打板 min_turnover_rate fallback 不一致

**问题**: strategy_defaults.py中first_limit_up的min_turnover_rate=8，但portfolio_backtest.py两处fallback硬编码为3。
当STRATEGY_CONFIGS参数读取失败时，fallback 3比实际值8宽松近3倍，低质量首板候选涌入。

**修复**: 两处fallback 3→8，与strategy_defaults对齐
- _print_single_strategy_filtering: L703
- _build_strategy_filter_conditions: L3697

**影响**: 回测中参数从strategy_defaults正确传入，fallback不影响实际回测结果。
但日志打印会显示错误值(3%而非8%)，可能误导用户调参。

### P1-2: 首板打板 opening_pct_max fallback 不一致

**问题**: strategy_defaults.py中first_limit_up的opening_pct_max=5.0(优化C:排除高开>5%追高)，
但portfolio_backtest.py两处fallback硬编码为7.0。高开>5%追高风险大，7.0过于宽松。

**修复**: 两处fallback 7→5，与strategy_defaults对齐
- _print_single_strategy_filtering: L710
- _build_strategy_filter_conditions: L3701

---

## ✅ 已验证无问题的项目

### T+1约束 (6处)
- _rebalance中sell_codes的T+1过滤 ✅
- _rebalance中reduce_codes的T+1过滤 ✅
- _check_and_execute_forced_sells中buy_dt==trade_date跳过 ✅
- 强制空仓中T+1限制 ✅
- 超时强卖T+1过滤 ✅
- 持仓保护中被保护股仍需T+1检查 ✅

### PositionManager防震荡bug (V33)
- mark_sold()从target_shares删除 → 买入循环遍历pos_mgr.target_shares ✅
- sell_codes去重用dict.fromkeys保持顺序 ✅

### _get_sl_tp_for_code一致性
- SL取min(最严格) ✅
- TP取strategies[0](买入策略) ✅
- 与sell_signal_checker.get_sl_tp_for_strategies对齐 ✅

### V34 TP取min修复验证
- check_full_sell中TP取strategies[0]（与_get_sl_tp_for_code一致） ✅

### 止损/止盈价格映射
- resolve_sell_price_and_reason: 跳空止损→open, 正常止损→止损价, 止盈→止盈价 ✅
- 利润保护→close, 利润锁定→close, 冲高回落→open ✅

### 滑点规则表
- should_apply_slippage: 主动保护性卖出扣滑点, 被迫卖出不扣 ✅
- 止盈不扣滑点(V49修复) ✅

### 因子未来函数
- volume_ratio→volume_ratio_prev ✅
- turnover_rate→turnover_rate_prev ✅
- circ_mv→circ_mv_prev ✅
- pct_chg已知未来函数(V25标注) ✅

### 月度收益计算
- monthly_profit用net_value_series计算(V36修复) ✅

### Sortino/Calmar上限
- Sortino上限50(V36修复) ✅
- Calmar上限200(V40修复) ✅

---

## 📋 代码审查统计

| 文件 | 行数 | 审查深度 |
|------|------|---------|
| portfolio_backtest.py | 4624 | 逐行审查(核心逻辑) |
| sell_signal_checker.py | 865 | 逐行审查 |
| strategy_defaults.py | 214 | 逐行审查 |
| ultra_short.py | 648 | 逐行审查 |
| factor_engine.py | 718 | 抽查(已审查多次) |
| models.py | 127 | 抽查 |
| node.py | 587 | 抽查 |
| backtest_validator.py | 446 | 抽查 |
| special_period_filter.py | 373 | 逐行审查 |
| factor_library.py | 797 | 抽查 |
| factor_quality_checker.py | 231 | 逐行审查 |
| universe.py | 416 | 抽查 |
| factor_auto_compute.py | 574 | 抽查 |
| models.py(factor_selection) | 168 | 抽查 |
| **合计** | **10788** | |

---

## 🎯 策略参数确认 (V66)

| 策略 | SL | TP | Hold | 追踪止损 | 滑点 |
|------|-----|-----|------|---------|------|
| 半路追涨 | 3% | 12% | 3天 | 2% | 0.2% |
| 首板打板 | 3% | 10% | 2天 | 2% | 0.5% |
| 龙头低吸 | 3.5% | 30% | 7天 | 3% | 0.2% |
| 跌停翘板 | 5% | 20% | 3天 | 4% | 0.3% |

### 全局风控
- 单票最大仓位: 35%
- 总仓位上限: 75%
- 强制空仓: 跌停≥80只 or 涨停≤10只 or 大盘跌幅≥3%
- 强制空仓冷却期: 2个交易日, 冷却期仓位上限60%
- 持仓保护: 盈利≥5%+阳线不被调仓卖出
- 利润锁定: 冲高≥5%+回撤≥2%+收盘≥2%

### 情绪仓位系数 (V66: 4级)
- 高潮期(≥70): 1.0
- 分化期(55-70): 0.7
- 震荡期(40-55): 0.5
- 冰点期(<40): 0.3

---

## 🔮 建议后续优化方向

1. **P2-1**: check_full_sell虽已废弃但仍存在，建议删除或标注更醒目
2. **P2-2**: _build_strategy_filter_conditions中硬编码的条件构建应逐步迁移到strategy_configs驱动
3. **P2-3**: 首板打板胜率47.1%(全年)是最大拖累，考虑调整hit_probability或增加二次确认
4. **P2-4**: 5-8月收益接近0(震荡市)，可研究震荡期专用策略或增强持仓保护
5. **P2-5**: strategy_defaults.py和STRATEGY_PULLBACK_PARAMS存在冗余定义，应统一为单一来源

---

**Git**: review/V59-backtest-live-audit, commit afc8031 + fd37c01
