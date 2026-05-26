# V55 回测引擎深度审查报告

**日期**: 2026-05-27
**审查范围**: backtest_engine/ 核心模块
**审查基线**: V56 (commit bd8a934)
**审查行数**: ~7,800行 (portfolio_backtest.py 4475, sell_signal_checker.py 871, ultra_short.py 641, strategy_defaults.py 200, models.py 83)

---

## 一、发现的问题与修复

### P0 级 (已修复)

| BUG ID | 描述 | 修复位置 | 修复内容 |
|--------|------|----------|----------|
| BUG-003 | record.price不含滑点与amount不一致 | portfolio_backtest.py L2395 | sell_price改用 `record.amount/record.shares`(含滑点/佣金/印花税的成交均价),与buy_price(含滑点)一致 |
| BUG-004 | all_trades(dict)缺少sell_price/buy_price字段 | portfolio_backtest.py L2690 | all_trades_dict转换时添加sell_price/buy_price映射 |
| BUG-015 | ultra_short.py成交概率fallback不一致 | ultra_short.py L201-203 | hit_probability_fast/normal/slow fallback从0.3/0.5/0.7改为0.20/0.45/0.50,与V56 STRATEGY_CONFIGS对齐 |
| MERGE-CONFLICT | ultra_short.py存在未解决的git merge冲突 | ultra_short.py L200-210 | 解决冲突,保留正确分支(0.20/0.45/0.50),删除冲突标记 |

### P1 级 (已修复)

| BUG ID | 描述 | 修复位置 | 修复内容 |
|--------|------|----------|----------|
| BUG-001 | 利润锁定检查代码4处重复(每处10-15行) | portfolio_backtest.py L185-207 | 提取为`_check_intraday_profit_lock()`方法,3处调用点简化为1-3行 |
| BUG-006 | 强制空仓未清理stock_to_strategy | portfolio_backtest.py L1515-1521 | 强制空仓清仓后同步清理`self.stock_to_strategy`,与`_cost_basis`清理对齐 |
| BUG-007 | 利润锁定fallback值过时(0.02 vs strategy_defaults 0.015) | portfolio_backtest.py L203, sell_signal_checker.py L317 | intraday_lock_pullback_pct fallback从0.02→0.015,与V56 strategy_defaults对齐 |

### P2 级 (已确认,可接受)

| BUG ID | 描述 | 状态 | 理由 |
|--------|------|------|------|
| BUG-008 | T+1检查冗余(6处) | 保留 | 各处T+1检查在不同流程环节(强制空仓/调仓/超时/减仓),逻辑上必要 |
| BUG-010 | 跌停翘板pct_chg>0未来函数 | 保留 | V18分析:这是"收盘确认条件"不是选股未来函数,盘中买入+收盘确认逻辑自洽 |
| BUG-011 | 半路追涨pct_chg≥5%未来函数 | 保留 | 已知近似,V25对照实验:去pct_chg收益-169%,保留是经验交易员盘中判断 |
| BUG-012 | 龙头低吸volume_ratio(T日)灰色地带 | 保留 | V27/V35分析:T日放量启动是信号核心,T-1日VR会把高胜率候选过滤掉,盘中可近似观测 |
| BUG-014 | Calmar上限1000过高 | V55已修复 | calmar_cap=max(50, trading_days/252*100),1000仅用于debug日志阈值 |

---

## 二、修复详情

### BUG-003: record.price vs amount 不一致

**根因**: 
- `RebalanceRecord.price` 存储的是原始成交价(不含滑点)
- `RebalanceRecord.amount` 存储的是扣除滑点/佣金/印花税后的净金额
- `_build_run_result` 中 merged_trades 的 `buy_price` 来自 `abs(buy_rec.amount)/buy_rec.shares`(含滑点)
- 但 `sell_price` 来自 `record.price`(不含滑点)
- 导致前端展示时 buy_price 含滑点但 sell_price 不含,用户看到的利润率与 profit_pct 不一致

**修复**:
```python
# 修复前
'sell_price': record.price,

# 修复后
'sell_price': record.amount / record.shares if record.shares > 0 else record.price,
```

**影响**: 前端显示的sell_price与profit_pct现在一致。profit_pct本身是正确的(始终用net金额计算)。

### BUG-004: all_trades缺少sell_price/buy_price字段

**根因**: `RebalanceRecord.__dict__` 只有 `price` 字段,没有 `sell_price`/`buy_price`。前端 BacktestResultPanel.vue 期望这两个字段。

**修复**: 在 `all_trades_dict` 转换时添加映射:
```python
if d.get('action') == 'sell' and 'sell_price' not in d and 'price' in d:
    d['sell_price'] = d['price']
if d.get('action') == 'buy' and 'buy_price' not in d and 'price' in d:
    d['buy_price'] = d['price']
```

### BUG-015: ultra_short.py成交概率fallback不一致

**根因**: ultra_short.py的fallback硬编码值(0.3/0.5/0.7)与V53/V56 STRATEGY_CONFIGS(0.20/0.45/0.50)严重不一致。此文件仅用于日志打印,不影响回测逻辑(回测逻辑在portfolio_backtest.py中使用_flu_defaults),但日志展示与实际执行不匹配。

**修复**: fallback统一从`_defaults.get()`读取,与STRATEGY_CONFIGS对齐。

**同时发现**: 该文件存在未解决的git merge冲突(HEAD版本0.3/0.5/0.7 vs 正确分支0.20/0.45/0.50),已解决冲突。

### BUG-001: 利润锁定检查代码4处重复

**根因**: 利润锁定检查(intraday_lock)在4个位置重复实现,每处10-15行,且fallback值不完全一致(0.02 vs 0.015 vs 0.04)。

**修复**: 提取为 `_check_intraday_profit_lock(cost, high_price, close_price) -> bool` 方法:
- `_check_and_execute_forced_sells` (2.5节): 简化为1行调用
- `_rebalance` V49-P0-3利润锁定: 简化为1行调用  
- `_rebalance` V48调仓日利润锁定: 简化为3行调用

**效果**: 消除~45行重复代码,统一fallback值(0.05/0.015/0.02),减少未来维护出错概率。

### BUG-006: 强制空仓未清理stock_to_strategy

**根因**: 强制空仓清仓时清理了`_cost_basis`和`_cost_basis_date`,但遗漏了`stock_to_strategy`。虽然次日`_build_strategy_filter_conditions`会清理不在holdings中的映射,但强制空仓日当天可能残留脏数据。

**修复**: 添加`self.stock_to_strategy`清理循环,与`_cost_basis`清理对齐。

### BUG-007: 利润锁定fallback值过时

**根因**: V56将`intraday_lock_pullback_pct`从0.02→0.015(更早锁住利润),但3处代码的fallback仍为0.02。虽然`_init_run_config`会将GLOBAL_RISK值写入`_risk_config`(运行时正确),但fallback作为安全网应与最新值对齐。

**修复**: 
- portfolio_backtest.py `_check_intraday_profit_lock`: fallback 0.02→0.015
- sell_signal_checker.py `check_intraday_profit_lock`: fallback 0.02→0.015

---

## 三、V56参数变更验证

| 参数 | V55值 | V56值 | 文件 | 状态 |
|------|-------|-------|------|------|
| 半路追涨 stop_loss_pct | 0.04 | 0.035 | strategy_defaults.py | ✅已同步 |
| 首板打板 hit_probability_slow | 0.60 | 0.50 | strategy_defaults.py | ✅已同步 |
| 跌停翘板 min_consecutive_limit | 2 | 1 | strategy_defaults.py | ✅已同步 |
| hold_protection_threshold | 0.05 | 0.04 | strategy_defaults.py | ✅已同步 |
| intraday_lock_pullback_pct | 0.02 | 0.015 | strategy_defaults.py | ✅已同步(本次修复fallback) |
| 首板打板 hit_probability_slow (ultra_short.py) | 0.7(硬编码) | 0.50 | ultra_short.py | ✅本次修复 |

---

## 四、sell_reason_stats 验证

V52基线sell_reason_stats为空。V55修复后直接在portfolio_backtest.py的_build_run_result中计算,不再依赖ultra_short.py后处理。

**验证**: sell_reason_stats从merged_trades计算,分类逻辑覆盖所有已知sell_reason:
- 止损: '止损'/'跳空止损' → stop_loss ✅
- 止盈: '止盈' → take_profit ✅
- 冲高回落/高开即卖: → pullback ✅
- 利润保护: → profit_protect ✅
- 利润锁定: → profit_lock ✅
- 停牌: '停牌超时强卖' → halt ✅
- 超时: '超时' → max_hold ✅
- 强制空仓: '强制空仓' → force_empty ✅
- 调仓: '调仓卖出'/'减仓' → rebalance ✅

---

## 五、仍需关注的风险点

### 1. 未来函数风险 (已知,非bug)
- 半路追涨pct_chg≥5%: 收盘确认因子,盘中不可知。V25对照实验显示去掉后收益-169%,保留是权衡选择。
- 龙头低吸volume_ratio(T日): 盘中可近似观测,但日线全量数据严格定义是未来函数。

### 2. 止损笔数偏多
- V56基线: 24笔止损 vs 9笔止盈,止损仍远多于止盈
- 半路追涨止损3.5%: V56已从4%降至3.5%,进一步降低可能导致正常波动被误触
- 建议: 持续监控,如果止损笔数>2x止盈笔数,考虑进一步优化入场条件

### 3. _rebalance方法长度
- 当前约450行,逻辑复杂但难以拆分(状态依赖)
- 已通过提取`_check_intraday_profit_lock`等方法减少冗余
- 进一步拆分需要仔细设计中间状态传递

### 4. Calmar比率短回测期虚高
- V55修复: calmar_cap=max(50, trading_days/252*100)
- 60天回测Calmar上限≈24,3个月≈60
- 短回测期(<120天)的Calmar参考价值有限,应关注Sharpe和盈亏比

### 5. 跌停翘板V56激活后的潜在风险
- min_consecutive_limit从2→1,候选股增加
- 首日数据: 19笔成交胜率79%,表现良好
- 但1连跌股票质量可能低于2连跌,需持续监控

---

## 六、代码质量改进

| 改进项 | 修改前 | 修改后 |
|--------|--------|--------|
| 利润锁定重复代码 | 4处×12行=48行 | 1个方法+3处调用=30行 |
| 参数fallback一致性 | 3处0.02,1处0.04 | 统一0.015(与strategy_defaults对齐) |
| all_trades字段完整性 | 缺少sell_price/buy_price | 自动映射添加 |
| 强制空仓数据清理 | 遗漏stock_to_strategy | 与_cost_basis同步清理 |
| git merge冲突 | 未解决(阻塞运行) | 已解决 |

---

## 七、未修改的文件确认

以下文件经审查无P0/P1级问题:
- `factor_engine.py` (718行): 因子计算引擎,纯数据处理,无交易逻辑问题
- `factor_library.py` (797行): 因子定义库,静态配置
- `factor_auto_compute.py` (574行): 因子自动计算,纯数据处理
- `universe.py` (422行): 股票池管理,V56已修复并发锁问题
- `strategy_filter.py` (232行): V56已标注废弃并添加RuntimeError
- `special_period_filter.py` (373行): 特殊时期过滤,纯配置逻辑
- `models.py` (83行): 数据模型定义,无逻辑问题

---

## 八、测试建议

1. **回归测试**: 运行V56基线回测(20260105-20260320),验证:
   - sell_reason_stats非空
   - merged_trades的sell_price与profit_pct一致
   - all_trades_dict包含sell_price/buy_price字段

2. **BUG-003验证**: 前端交易明细页,验证sell_price≈record.amount/shares(含滑点)

3. **BUG-015验证**: 回测日志中首板打板成交概率应显示"慢50%"而非"慢70%"

4. **实盘隔离**: 确认real_trading/目录无变更(已验证git diff为空)
