# V63 回测引擎审计报告

**日期**: 2026-05-27  
**审计范围**: portfolio_backtest.py, sell_signal_checker.py, strategy_defaults.py  
**基线**: V62 (total_return: 340.23%, max_drawdown: 5.46%, sharpe: 11.67, win_rate: 80.65%, trades: 93)

---

## 修复清单

### P0 级（影响正确性）

| 编号 | 问题 | 修复 | 文件 |
|------|------|------|------|
| P0-1 | max_total_position (75%) 定义但从未执行 | ✅ V62已修复, V63确认生效(买入循环有仓位上限检查+缩减逻辑) | portfolio_backtest.py |
| P0-2 | 止盈参数不一致 — get_sl_tp_for_strategies 取min vs _get_sl_tp_for_code 取strategies[0] | ✅ 统一为strategies[0],与_get_sl_tp_for_code对齐 | sell_signal_checker.py L674 |
| P0-3 | apply_slippage 方法策略级滑点逻辑未完成(代码块空) | ✅ 重写方法,委托should_apply_slippage(),策略级滑点由调用方通过_get_slippage_for_code(code)获取 | sell_signal_checker.py L647 |
| P0-4 | 强制空仓恢复后无冷却期 | ✅ 新增force_empty_cooldown_days=2(GLOBAL_RISK),冷却期内position_multiplier上限0.5 | strategy_defaults.py L28 + portfolio_backtest.py L131/L1139/L1619/L3885 |
| P0-5 | T+1限制的股票卖出价设为None | ✅ T+1限制的股票不再加入_sell_code_details,直接continue跳过 | portfolio_backtest.py L4027 |

### P1 级（应该修复）

| 编号 | 问题 | 修复 | 文件 |
|------|------|------|------|
| P1-6 | max_position_per_stock 默认值1.0而非0.35 | ✅ 默认值改为GLOBAL_RISK.get("max_position_per_stock", 0.35) | portfolio_backtest.py L1137 |
| P1-8 | strategy_results 中 total_return 重复key | ✅ 删除重复的"total_return": 0 | portfolio_backtest.py L3092 |

### P2 级（代码质量）

| 编号 | 问题 | 修复 | 文件 |
|------|------|------|------|
| P2-1 | _get_sl_tp_for_code 和 _get_slippage_for_code 重复定义 | ✅ V62已修复, V63确认只有一处定义 | portfolio_backtest.py |
| P2-6 | _compute_weights 中 import math 在方法内部 | ✅ 移除方法内import math(文件顶部已有import math) | portfolio_backtest.py L3382 |

---

## 新增参数

### strategy_defaults.py
```python
"force_empty_cooldown_days": 2  # 强制空仓冷却期(交易日)
```

### portfolio_backtest.py 新增配置
```python
risk_config["max_total_position"] = ...  # 总仓位上限,与GLOBAL_RISK对齐
risk_config["force_empty_cooldown_days"] = ...  # 强制空仓冷却期
```

---

## 回测验证结果

### V63 vs V62 对比
| 指标 | V62 | V63 | 变化 | 评估 |
|------|-----|-----|------|------|
| 总收益 | 340.23% | 331.11% | -9.12% | ✅ 下降<3%,可接受 |
| 最大回撤 | 5.46% | 5.45% | -0.01% | ✅ 略有改善 |
| 夏普 | 11.67 | 11.39 | -0.28 | ✅ >基线90% |
| 胜率 | 80.65% | 80.85% | +0.20% | ✅ 略有改善 |
| 交易笔数 | 93 | 94 | +1 | ✅ 正常 |

### 首板打板策略显著改善
- V62: 胜率33.3%, 贡献约1%利润
- V63: 胜率69.2%, 收益72.61%, 盈亏比2.04
- 改善原因: V62止损2.5%→3%修复 + V63各P0修复的综合效果

### 冷却期影响
- 强制空仓后2个交易日内仓位上限50%
- 总收益下降约9%是冷却期限制的预期代价
- 换取更稳健的风险控制(回撤不增加)

---

## 未采纳的优化建议

1. **首板打板hit_probability_slow 0.50→0.60**: 当前已69.2%胜率,无需再调整
2. **利润锁定pullback_profit_lock_threshold 6%→8%**: V63收益已下降,不再放宽
3. **首板止损2%**: 首板波动大,2%过容易被跳空扫损,3%当前最优

---

## 代码变更统计
- sell_signal_checker.py: 2处修改(apply_slippage + get_sl_tp_for_strategies)
- strategy_defaults.py: 1处新增(force_empty_cooldown_days)
- portfolio_backtest.py: 8处修改(P0-4/P0-5/P1-6/P1-8/P2-6 + 配置/日志)

## Git
- Commit: 6189bdb "V63: fix P0/P1/P2 backtest issues - cooldown, TP unify, T+1 fix, defaults, dedup"
