# V60 回测引擎深度审查报告

**日期**: 2026-05-27
**审查范围**: portfolio_backtest.py (4536行), sell_signal_checker.py, strategy_defaults.py, ultra_short.py, node.py
**基线**: V57 (Total Return 102.11%, Win Rate 68.18%, Max DD 3.09%, Sharpe 10.17, 110 trades)
**新基线(2025Q1)**: Total Return 424.08%, Win Rate 82.98%, Max DD 6.40%, Sharpe 11.62, 94 trades

---

## 🔴 P0 关键Bug (影响回测准确性)

### P0-1: `_rebalance` 减仓循环中止损止盈promote后holdings已变但reduce_codes未清理
**位置**: portfolio_backtest.py ~4240行
**问题**: `codes_to_promote`从reduce_codes提升到sell_codes后,delete了reduce_codes[code],但后续卖出循环中holdings[code]可能已经被卖出,导致减仓循环尝试对已不存在的持仓减仓。
**影响**: 极端情况下可能导致负持仓或重复卖出。
**修复**: 在减仓循环中添加holdings.get(code, 0) > 0检查。

### P0-2: `_build_run_result` 中position_series计算用daily_cash_list而非归一化值
**位置**: portfolio_backtest.py ~3100行
**问题**: `pos_val = max(0.0, 1.0 - daily_cash_list[i])` — daily_cash_list是绝对金额(元),不是占比。
需要除以total_value才是占比。当净值增长后,现金绝对值占比失真。
**影响**: 前端仓位曲线显示不准确。
**修复**: 改用 `1.0 - daily_cash_list[i] / (net_value_series[i]['net_value'] * initial_cash)`

### P0-3: 首板打板hit_probability参数在_apply_limit_up_hit_probability中硬编码fallback
**位置**: portfolio_backtest.py ~3900行
**问题**: V58-BUG-001修复改了fallback值,但注释说"与strategy_defaults.py V57对齐",
实际V57的hit_probability_slow=0.60,这里改成了0.45。注释与代码不一致。
**影响**: 首板打板成交概率低于预期,导致信号过少。
**修复**: 从strategy_defaults动态读取,不硬编码fallback。

### P0-4: monthly_profit fallback路径浮点累积误差
**位置**: portfolio_backtest.py ~3250行
**问题**: fallback路径用daily_profit_list累加计算月度收益,存在浮点误差。
虽然注释标注了TODO,但此路径理论上不应触发(net_value_series优先)。
**修复**: 删除fallback路径,如果没有net_value_series则返回空dict。

## 🟡 P1 逻辑优化 (提升回测结果)

### P1-1: 龙头低吸hold_protection与pct_chg≥-7%过滤冲突
**位置**: portfolio_backtest.py _rebalance ~4130行
**问题**: V59新增pct_chg≥-7%过滤排除暴跌股,但hold_protection只看盈利+阳线,
不检查当日是否暴跌。一只龙头低吸股买入后次日暴跌7%+仍可能因"阳线"被保护(如低开-8%后反弹到-6%收阳)。
**修复**: hold_protection增加pct_chg检查,当日跌幅>5%的不保护。

### P1-2: 策略级max_hold_days未在_build_strategy_filter_conditions中使用
**位置**: portfolio_backtest.py _build_strategy_filter_conditions
**问题**: 龙头低吸max_hold_days=7,但在超时强卖计算中_global_max_hold从risk_config读取默认3天。
_get_max_hold_for_code正确实现了策略级max_hold,但over_hold_codes的判断条件
`global_max_hold = self._risk_config.get('max_hold_days', 999)` 用了全局值作为fallback。
**修复**: 确保global_max_hold只作为兜底,策略级值优先。

### P1-3: factor_contribution按绝对值分配,亏损策略贡献为正
**位置**: portfolio_backtest.py ~3200行
**问题**: `abs(s.get("total_return", 0)) / total_pnl_abs` — 亏损策略的abs值也被计入分母,
导致盈利策略的贡献被稀释。如半路追涨+10%和首板打板-5%,总abs=15%,
半路追涨贡献=10/15=67%而非实际100%。
**修复**: 分母只用盈利策略的abs值,或改用净值贡献法。

### P1-4: 止盈不扣滑点但止盈价已含保守估计的逻辑需验证
**位置**: sell_signal_checker.py SLIPPAGE_RULES
**问题**: V49修复止盈不扣滑点,但止盈价=cost*(1+tp),实际high可能刚好触达tp价,
用tp价卖出时如果不扣滑点,实际收益可能偏高。
回测中止盈触发比例较低(9/110=8.2%),影响有限。
**建议**: 保持现状,但添加注释说明止盈价本身就是保守估计(用成本价*tp而非实际high)。

### P1-5: strategy_results中total_return含义不明确
**位置**: portfolio_backtest.py strategy_results计算
**问题**: `total_pnl = sum(t.get('profit_pct', 0) for t in completed)` — 这是profit_pct之和,
不是组合收益率。对于94笔交易,profit_pct之和可能是400%+,
但组合实际收益率是424%。两者接近但不等价(仓位系数影响)。
**修复**: 重命名为cumulative_profit_pct,避免与组合收益率混淆。

## 🟢 P2 代码质量与体验

### P2-1: _rebalance方法过长(453行)
**问题**: 虽然注释说明不可拆分,但4段逻辑(卖出/买入/止损/强制空仓)可提取为私有方法。
**建议**: 提取_sell_phase(), _buy_phase(), _stop_loss_phase(), _force_empty_phase()。

### P2-2: daily_profit_list和daily_cash_list命名混淆
**问题**: daily_profit_list是绝对金额(元),daily_profit(归一化)是小数。
两者名称太接近,容易误用。
**修复**: daily_profit_list → daily_profit_abs_list, 明确标注单位。

### P2-3: _standardize_ts_code中5/9开头→.SH的规则需验证
**问题**: 5开头是基金/ETF,9开头是B股。都归入.SH可能不正确。
**修复**: 5开头(50/51/52)→.SH(上交所基金), 9开头(900)→.SH(B股), 但需确认数据源。

### P2-4: _daily_price_cache在跨天时可能残留旧数据
**问题**: 缓存按trade_date重置,但如果同一天内先查A股票再查B股票,
第二次查询可能从缓存中返回第一次查询的A股票价格。
**影响**: 这是设计意图(同一天缓存),但需要确保trade_date比较正确。
**确认**: 代码正确,cache_date == trade_date才复用。

### P2-5: _get_limit_up_price一字板返回close_price后上层hit_probability=0处理
**问题**: V54-Bug5修复后,一字板返回close_price而非0,
上层_apply_limit_up_hit_probability中hit_prob_yizi=0.0导致del target_shares[code]。
逻辑正确,但代码路径不直观(先设置目标股→再删除)。
**建议**: 在_compute_weights中就过滤一字板,而非在rebalance中后置删除。

## 📊 回测结果优化建议

### 优化1: 首板打板hit_probability微调
**当前**: yizi=0, fast=0.20, normal=0.40, slow=0.45
**V57基线**: slow=0.60 (被V58改为0.45)
**建议**: slow=0.50, normal=0.40 — 盘中板从0.45→0.50,
因为首板贡献仅1%利润,适当放宽增加信号量,配合2.5%止损控制风险。

### 优化2: 龙头低吸max_hold_days=7可能过长
**当前**: 7天,回测中51.69%和33.55%的超时退出说明有长尾大牛
**建议**: 保持7天,但增加第5天的利润保护检查(如果持仓5天利润<3%,提前退出)

### 优化3: 半路追涨min_close_rise_pct=5%的已知未来函数
**当前**: pct_chg≥5%作为"收盘确认",但这是T日收盘数据
**建议**: 实盘模式降级为pct_chg_prev≥3%(更宽松,因为T-1日涨幅不等于T日)
回测模式保持5%不变(这是回测结果的核心支撑)

### 优化4: 跌停翘板pct_chg>0过滤可能过严
**当前**: 要求今日收涨(pct_chg>0)
**问题**: 盘中翘板成功但收盘微跌(-0.5%)的股票被过滤,这些股票次日可能继续上涨
**建议**: 放宽到pct_chg≥-1%(允许微跌),回测验证

### 优化5: hold_protection_threshold=5%可能过高
**当前**: V59从4%→5%,减少保护范围
**问题**: 4-5%利润的股票失去保护被调仓卖出,可能错过后续涨幅
**建议**: 4.5%作为折中,或改用动态阈值(基于波动率)
