# 回测模块全面审查报告

审查时间: 2026-05-16
审查范围: AgentServer/nodes/web/api/backtest/ + nodes/backtest_engine/ + frontend/

---

## [P0] 严重Bug（结果错误）

### P0-1: 前端GLOBAL_RISK与后端不一致 — 止损/止盈默认值错位
**文件**: frontend/src/config/strategyDefaults.ts:2-4 | nodes/backtest_engine/strategy_defaults.py:8-9
**问题**: 前端 `GLOBAL_RISK.stop_loss_pct=0.05, take_profit_pct=0.10`，后端 `stop_loss_pct=0.03, take_profit_pct=0.07`。前端注释声称"与后端完全对齐"但实际不对齐。
**影响**: 用户打开页面看到的全局默认止损5%/止盈10%，但若前端没提交params（走兜底逻辑），后端实际使用3%/7%。回测结果与用户预期不一致。
**建议修复**: 运行 `scripts/sync_strategy_defaults.py` 同步，或直接将前端 GLOBAL_RISK 改为与后端一致。

### P0-2: PortfolioBacktester 两个__init__方法 — 第一个是死代码
**文件**: nodes/backtest_engine/factor_selection/portfolio_backtest.py:113-117
**问题**: 类定义了两个`__init__`方法。第一个（113-115行）初始化`_risk_config/_slippage_pct/_strategy_risk_params`，随后被第二个`__init__`（119行起）完全覆盖。第二个`__init__`也初始化了这些属性，所以目前不会报错，但 `FORCE_EMPTY_LIMIT_UP = 10` 被夹在两个 `__init__` 之间（117行），代码结构混乱，维护风险极高。
**影响**: 当前不影响功能（第二个init覆盖了第一个），但极易在维护中引入bug。
**建议修复**: 删除第一个`__init__`（113-115行）和其注释，将 `FORCE_EMPTY_LIMIT_UP` 移到 `FORCE_EMPTY_LIMIT_DOWN` 下面。

### P0-3: opening_pct_min/max单位在策略筛选中不一致
**文件**: nodes/backtest_engine/factor_selection/portfolio_backtest.py:3091-3097
**问题**: `首板打板`策略的`opening_pct_min/max`在strategy_defaults.py中是百分比形式（-1.0, 7.0，含义是-1%, 7%），数据库`opening_pct_chg`也是百分比形式（如-0.338表示-0.338%）。但当这些值传到`_build_strategy_filter_conditions`时（3091行），作为`target`直接与数据库百分比列比较，逻辑上是正确的。**然而**，3091行的fallback默认值是2.0和5.0，与strategy_defaults.py的-1.0和7.0不同，如果参数未传入会导致过滤条件错误。
**影响**: 当`selected_strategies`中没有传params时（兜底路径），首板打板的竞价涨幅范围从[-1%,7%]变成[2%,5%]，大幅缩小候选池。
**建议修复**: 将3091-3092行的fallback改为从`STRATEGY_CONFIGS`读取，而非硬编码。

---

## [P1] 前后端不一致（配置无效/数据错位）

### P1-1: 前端GLOBAL_RISK.stop_loss_pct=0.05 vs 后端0.03 — 用户初始表单错误
**文件**: frontend/src/config/strategyDefaults.ts:3
**问题**: 如P0-1所述。用户首次打开回测页面，表单默认止损5%，但提交到后端时如果走兜底路径就是3%。
**影响**: 配置参数名义上被前端展示但实际无效。
**建议修复**: 同P0-1。

### P1-2: 策略ID命名分裂 — dragon_head vs leader_buy_dip
**文件**: 
- nodes/backtest_engine/strategy_defaults.py: `dragon_head`
- core/managers/signal_generator.py:41: `leader_buy_dip`
- scripts/run_2year_backtest.py:39: `leader_buy_dip`
**问题**: 同一策略"龙头低吸"在回测系统用`dragon_head`，在实盘信号系统用`leader_buy_dip`。如果用`run_2year_backtest.py`提交回测（用leader_buy_dip），在`ultra_short.py`的`strategy_name_map`中找不到映射，会被当成原始字符串传递，导致策略名匹配失败。
**影响**: `run_2year_backtest.py`等旧脚本使用`leader_buy_dip`作为策略ID，回测时可能匹配不到正确策略。
**建议修复**: 统一为`dragon_head`，在signal_generator.py中添加别名映射。

### P1-3: 前端提交的forceEmpty/sentimentCycle/auctionFilter配置未完整传到引擎
**文件**: nodes/web/api/backtest/ultra_short.py:68-75 | nodes/backtest_engine/ultra_short.py:67-76
**问题**: 前端表单有`forceEmpty.index_drop_pct`、`sentimentCycle.weight_limit_up`等细粒度参数，但API层只传了`enable_force_empty`（布尔值），未传`index_drop_pct`/`limit_down_count`等阈值参数。引擎层的强制空仓判断用类常量`FORCE_EMPTY_LIMIT_DOWN=50`，用户在前端配置的`limit_down_count`无法生效。
**影响**: 用户修改强制空仓阈值不生效，配置形同虚设。
**建议修复**: 在`task_info`构建中，将forceEmpty/sentimentCycle/auctionFilter的完整参数传递给引擎。

### P1-4: 前端globalFilter参数未传到引擎
**文件**: frontend/src/views/backtest/UltraShortBacktestViewV2.vue:130-135 | nodes/backtest_engine/ultra_short.py:237-242
**问题**: 前端表单有`exclude_st`、`exclude_delisting`、`exclude_new_stock_days`、`min_turnover_rate`等全局筛选参数，但`submitBacktest`只传了`exclude_st`布尔值和`liquidity_threshold`/`volume_threshold`，其余参数未传入。引擎的`universe_mgr`硬编码`exclude_rules = [ExcludeRule.ST, ExcludeRule.NEW_STOCK]`，用户无法自定义次新股市值天数和最低换手率。
**影响**: `exclude_new_stock_days`和`min_turnover_rate`等参数配置后不生效。
**建议修复**: 将globalFilter完整参数传入engine的universe_mgr配置。

### P1-5: 首板打板策略存在死参数 — min_seal_amount/max_limit_up_time/max_blast_count/require_hot_sector
**文件**: nodes/backtest_engine/strategy_defaults.py:62-71
**问题**: `first_limit_up`的strategy_defaults中**没有**`min_seal_amount`/`max_limit_up_time`/`max_blast_count`/`require_hot_sector`这4个参数，但`ultra_short.py:153-158`的日志打印代码和`portfolio_backtest.py:321-329`的参数显示代码都读取这些参数（使用硬编码fallback）。这些参数在策略筛选逻辑中完全未使用（日线回测无法获取盘中封单数据），但前端StrategyConfigPanel也没有这些字段。
**影响**: 无功能影响，但日志打印的参数与实际筛选条件不一致，误导用户。
**建议修复**: 删除ultra_short.py和portfolio_backtest.py中对这4个参数的日志输出，或标注为"仅供实盘参考"。

### P1-6: 前端strategy_risk_params未通过API提交到后端
**文件**: frontend/src/views/backtest/UltraShortBacktestViewV2.vue:122-128
**问题**: 前端通过`selected_strategies`提交了每个策略的`riskParams`（止损/止盈/持仓天数/滑点），但在API层`models.py`的`UltraShortBacktestRequest`中没有`strategy_risk_params`字段。`root_validator`中虽然解析了`riskParams`并放到`strategy_risk_params`，但最终只通过`selected_strategies`透传到引擎。
**影响**: 当前通过selected_strategies传了riskParams，引擎也能正确解析，但如果前端改为只传strategy_params而不传selected_strategies，策略级风控参数会丢失。
**建议修复**: 在UltraShortBacktestRequest中正式声明strategy_risk_params字段，确保参数传递路径明确。

---

## [P2] 代码质量问题（死代码/命名不一致/缺失校验）

### P2-1: 重复的__init__方法 — 代码结构混乱
**文件**: nodes/backtest_engine/factor_selection/portfolio_backtest.py:113-119
**问题**: 同P0-2。两个`__init__`定义，第一个是死代码。

### P2-2: UltraShortBacktestRequest中enable_force_empty在两层重复定义
**文件**: nodes/web/api/backtest/models.py:131,170,216-217
**问题**: `enable_force_empty`既在`UltraShortParams`（131行）中定义，又在`UltraShortBacktestRequest`（170行）顶层定义。root_validator中又从params读取覆盖（216-217行），三重定义容易混乱。
**影响**: 代码可读性差，容易出错。
**建议修复**: 只在一处定义enable_force_empty，推荐保留顶层字段，从params中移除。

### P2-3: ultra_short.py中策略参数默认值与strategy_defaults.py不一致
**文件**: nodes/backtest_engine/ultra_short.py:153-191
**问题**: 龙头低吸日志打印：`min_consecutive_limit`默认3（179行），但strategy_defaults.py中默认1。龙头低吸`min_correction_pct`默认0.15（180行），但strategy_defaults.py中默认0.05。跌停翘板`min_consecutive_limit`默认3（189行），但strategy_defaults.py中默认2。跌停翘板`require_high_sentiment`默认True（192行），但strategy_defaults.py中默认False。
**影响**: 日志打印的默认值与strategy_defaults.py不一致，误导用户。虽然实际参数从selected_strategies传入，但兜底路径（前端没传params时）会使用这些硬编码默认值。
**建议修复**: 统一使用strategy_defaults.py的默认值，或从`STRATEGY_CONFIGS`读取。

### P2-4: API层task_info参数嵌套结构混乱
**文件**: nodes/web/api/backtest/ultra_short.py:68-85
**问题**: `task_info["params"]`中既有`params`子对象，又在顶层重复放置`enable_force_empty`/`selected_strategies`等字段。例如`selected_strategies`既在`params.params.selected_strategies`又在`params.selected_strategies`。引擎侧取参数时需要同时处理两种路径。
**影响**: 增加维护复杂度，容易导致参数丢失。
**建议修复**: 扁平化参数结构，或在文档中明确嵌套规范。

### P2-5: BacktestConfig(engine/models.py)与实际配置不匹配
**文件**: nodes/backtest_engine/models.py:19-35
**问题**: `BacktestConfig`定义了`entry_threshold`/`exit_threshold`/`factor_weights`等字段，但实际回测用的是`PortfolioBacktester`，配置通过dict传入而非`BacktestConfig`。`BacktestConfig`是旧版单股回测的遗留，当前超短回测完全不使用。
**影响**: 死代码，混淆开发者。
**建议修复**: 删除或标注为`@deprecated`，避免新代码误用。

### P2-6: BacktestRequest和FactorSelectionRequest — 旧版API模型无人使用
**文件**: nodes/web/api/backtest/models.py:17-57
**问题**: `BacktestRequest`是单股回测模型，但单股回测路由在`__init__.py`中虽然定义了，从未有前端页面使用。`FactorSelectionRequest`同理。
**影响**: 死代码。
**建议修复**: 标注为deprecated或移除未使用的路由。

### P2-7: 前端submitBacktest中传了commission_rate/stamp_duty_rate但API的UltraShortParams也定义了
**文件**: frontend/src/views/backtest/UltraShortBacktestViewV2.vue:130-135 | nodes/web/api/backtest/models.py:118-119
**问题**: 前端在params中传了`commission_rate`和`stamp_duty_rate`，但API层`UltraShortParams`的`commission_rate`默认值0.0003与前端传的`GLOBAL_RISK.commission_rate`（也是0.0003）一致。但前端没有在params中传`commission_rate`！前端传的是`volume_threshold`/`stop_loss_pct`等字段，`commission_rate`和`stamp_duty_rate`实际不在params中。
**影响**: 佣金和印花税参数不会从前端params传入，但引擎的config直接读params，如果未传则用类常量0.0003。恰好类常量与前端默认值一致，所以当前不影响结果，但如果用户在前端修改佣金费率，修改不会生效。
**建议修复**: 在前端submitBacktest的params中添加commission_rate/stamp_duty_rate/slippage_pct传递。

### P2-8: 涨停开板策略min_turnover_rate单位不一致
**文件**: nodes/backtest_engine/strategy_defaults.py:96 | frontend/src/components/ultrashort/StrategyConfigPanel.vue
**问题**: `limit_up_open`的`min_turnover_rate=0.15`（小数，15%），而`first_limit_up`的`min_turnover_rate=3`（整数百分比，3%）。前端StrategyConfigPanel中两者使用不同的输入范围（limit_up_open用0~1，first_limit_up用1~30），但策略名相同`min_turnover_rate`含义不同。引擎中涨停开板的处理（portfolio_backtest.py:333行）做了`* 100 if < 1`的转换，但首板打板没有。
**影响**: 单位不一致增加维护风险，若未来复用代码容易混淆。
**建议修复**: 统一为百分比形式（15.0），或在参数名中加后缀区分。

### P2-9: strategy_defaults.py注释声称前端同步但实际未同步
**文件**: frontend/src/config/strategyDefaults.ts:1-4
**问题**: 前端文件注释"⚠️ 此文件必须与后端 strategy_defaults.py 保持同步！修改策略参数请改后端...然后重新同步。同步命令: cd AgentServer && python3 scripts/sync_strategy_defaults.py"。但P0-1已证明GLOBAL_RISK不一致，且该同步脚本可能不存在或未运行。
**影响**: 前后端默认值不同步，违反"单一来源"原则。
**建议修复**: 确认sync脚本存在并运行，或在前端完全从后端API加载默认值（已部分实现但fallback到本地）。

### P2-10: mock_tasks内存泄漏防护不完整
**文件**: nodes/web/api/backtest/ultra_short.py:139-155
**问题**: 成功路径中，mock_tasks[task_id]被设置为running状态后，不再删除（只在失败路径删除）。随着回测任务增多，mock_tasks会持续增长。虽然有`cleanup_old_backtest_tasks`清理MongoDB，但mock_tasks是内存字典不受影响。
**影响**: 长时间运行后内存缓慢泄漏。
**建议修复**: 在任务完成后（status接口读取到completed/failed时）从mock_tasks中删除。

---

## 问题汇总

| 级别 | 数量 | 关键问题 |
|------|------|----------|
| P0 | 3 | 前后端GLOBAL_RISK不一致、双__init__、fallback默认值 |
| P1 | 6 | 策略ID分裂、forceEmpty/GlobalFilter参数未透传、死参数、riskParams路径 |
| P2 | 10 | 默认值硬编码不一致、参数嵌套混乱、死代码、单位不统一、内存泄漏 |

### 最需优先修复的Top 3:
1. **P0-1**: GLOBAL_RISK前后端不同步 — 影响所有用户的默认止损/止盈配置
2. **P1-3+P1-4**: forceEmpty/GlobalFilter细粒度参数未透传 — 前端配置形同虚设
3. **P1-2**: leader_buy_dip vs dragon_head策略ID分裂 — 旧脚本无法正确运行
