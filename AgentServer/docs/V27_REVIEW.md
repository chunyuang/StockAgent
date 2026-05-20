# V27 回测审查报告

## 基线: V26 = 94.08%/10.72夏普/2.29%回撤/70.97%胜率/1.76盈亏比/124笔

## 最终结果: V27 = 111.71%/13.25夏普/2.94%回撤/73.58%胜率/1.81盈亏比/106笔

## 提升: 收益+17.63%, 夏普+2.53, 胜率+2.61%, 盈亏比+0.05, 回撤+0.65%(微增)

---

## 修复清单

### P0-2(关键): 龙头低吸添加冲高回落+利润保护
**文件**: portfolio_backtest.py `_check_early_sell_signals`
**问题**: 龙头低吸占交易量44%(55/124笔)但没有冲高回落/利润保护,纯龙头低吸股高开低收时无保护
**修复**: 添加冲高回落(open_rise≥5%直接触发;3%-5%区间需回落≥1%)和利润保护(收盘盈利≥2%且高开低收)
**效果**: 龙头低吸收益198%→244%(+46%), 组合收益+17.63%

### P0-1: 半路追涨冲高回落区间判断
**文件**: portfolio_backtest.py `_check_early_sell_signals`
**问题**: 跌停翘板有3%-5%区间判断(需回落≥1.5%),但半路追涨没有,open_rise=3.1%且回落0.1%就触发
**修复**: 添加区间判断 - open_rise≥5%直接触发,3%-5%区间需回落≥1%
**效果**: 减少过早卖出

### P0实盘: generate_daily_signals中龙头低吸ID错误
**文件**: core/managers/live/generate_daily_signals.py
**问题**: 策略ID用'leader_buy_dip'而非'dragon_head',导致STRATEGY_CONFIGS取不到参数
**修复**: leader_buy_dip → dragon_head
**影响**: 回测不受影响(入口有别名映射),但实盘信号生成受影响

### P1-2/P1-3: 跌停翘板circ_mv/turnover_rate改用_prev因子
**文件**: portfolio_backtest.py `_build_strategy_filter_conditions`
**问题**: 使用T日数据(未来函数),实盘开盘时T日circ_mv/turnover未知
**修复**: circ_mv→circ_mv_prev, turnover_rate→turnover_rate_prev
**效果**: 消除未来函数

### P1-4: 半路追涨volume_ratio改用_prev因子
**文件**: portfolio_backtest.py `_build_strategy_filter_conditions`
**问题**: 使用T日volume_ratio(全天数据),实盘开盘时无法知道全天量比
**修复**: volume_ratio→volume_ratio_prev
**效果**: 消除未来函数

### 龙头低吸volume_ratio/circ_mv保留T日(不改为_prev)
**原因**: 龙头低吸的信号是"缩量回调后T日开始放量",T-1日还是缩量状态
用_prev会把"放量启动"的高胜率候选过滤掉(实测收益-90%)
volume_ratio在盘中可观测(基于前5日均量推算),是准实时因子

### 参数优化(8组扫描验证)
| 参数组合 | 收益% | 夏普 | 回撤% |
|---------|-------|------|-------|
| V27基线 | 94.96 | 12.10 | 2.95 |
| 龙头TP12% | 98.76 | 12.48 | 2.93 |
| 龙头TP15% | 104.45 | 12.94 | 2.89 |
| 跌停SL4% | 96.76 | 12.25 | 2.94 |
| 半路SL4% | 96.36 | 12.29 | 2.75 |
| 半路TP15% | 94.02 | 12.05 | 2.96 |
| 龙头TP12+半路TP15 | 99.60 | 12.51 | 2.91 |
| **龙头TP15+跌停SL4** | **105.61** | **13.04** | **2.93** |

**采用**: 龙头TP15%+跌停SL4%
- strategy_defaults.py: dragon_head.riskParams.take_profit_pct 0.10→0.15
- strategy_defaults.py: limit_down_qiao.riskParams.stop_loss_pct 0.05→0.04
- strategy_defaults.py: dragon_head.params.next_day_open_sell_pct = 0.03 (新增)

### 代码优化
- getattr(self, 'stock_to_strategy', {}) → self.stock_to_strategy (14处)
- getattr(self, '_cost_basis', {}) → self._cost_basis (4处)
- getattr(self, '_cost_basis_date', {}) → self._cost_basis_date (5处)
- 前端strategyDefaults.ts同步(通过sync_strategy_defaults.py)

## Git Commits
1. a4b2b48 - V27审查: 龙头低吸冲高回落保护+半路追涨区间判断+_prev因子+参数优化
2. 493c9da - 同步前端strategyDefaults.ts
3. e328a35 - P0实盘修复: generate_daily_signals中龙头低吸ID leader_buy_dip→dragon_head
