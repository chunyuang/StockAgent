# 市场监听系统优化设计方案

> 版本: v2.9.56 | 日期: 2026-06-02 | 基线分支: audit/V75-backtest-review
> 开发分支: feature/market-monitor-optimization
> 标签: v2.8.0-backtest-ui-v2 (回测UI稳定基线)
> 状态: 开发中 | Phase1✅ | Phase2✅ | Phase3✅ | Phase4✅ | 代码审查✅ | 线程安全✅ | 审查优化✅ | 继续优化✅ | EventBus✅ | EventBus订阅器✅ | v2.9架构解耦✅ | v2.9.4提取+增强✅ | v2.9.6核心提取+Compare测试✅ | v2.9.7 List+ACK✅ | v2.9.8 Phase4完善✅ | v2.9.9 委托存根消除+profit_pct修复✅ | v2.9.10 /health统一+版本缓存+线程安全✅ | v2.9.11 API端点线程安全✅ | v2.9.12 关键路径健壮性✅ | v2.9.13 _scan_loop提取+线程安全补全✅ | v2.9.14 Redis Stream升级+审计TTL+断线补发✅ | v2.9.15 错误遥测+参数预检+事件扩展✅ | v2.9.16 risk_watchdog线程安全+情绪卖出提取+配置方法简化✅ | v2.9.17 DelegateRouter提取+_with_state_lock统一+参数审计增强✅ | v2.9.18 stop()拆分+QuoteManager封装+pending_sells安全拷贝+_check_force_empty返回stats✅ | v2.9.19 _execute_risk_sell拆分+scan_once提取+_scan_loop回放提取+get_status简化✅ | v2.9.20 _liquidate_positions提取+_execute_force_empty T+1合规修复✅ | v2.9.22 分步计时+卖出统计分类修复+跨日一致性+错误恢复✅ | v2.9.24 diagnose+情绪调仓提取+DelegateRouter策略扩展✅ | v2.9.25 update_strategy_config bug修复+bare except清理+_init_modules拆分✅ | v2.9.26 全模块bare except清理+position_checker._execute_sell_list提取3子方法✅ | v2.9.27 方法提取到子模块5个+测试适配✅ | v2.9.28 风控线程拆分+filter合并提取+scan_loop错误恢复✅ | v2.9.31 _safe_read_state统一+RuntimeWarning修复+get_positions提取✅ | v2.9.34 情绪得分+收盘同步提取→子模块✅ | v2.9.35 卖出执行提取到PositionManager✅ | v2.9.36 审查P0/P1修复+WS断线补发+前端错误提示 | v2.9.37 _save_param_snapshot提取+_init_state类属性瘦身+start()30行 | v2.9.38 _run_checker_on_positions提取+compare差异持久化+_post_sell_state_cleanup统一 | v2.9.39 _scan_loop_settlement提取→RuntimePersistence+_emit_risk_thread_error委托RiskWatchdog+MarketPhase.is_trading_active+position_checker except修复 | v2.9.42 参数管理6方法DELEGATE_MAP委托+StrategyParamCenter路由策略+scanner 1382行 | v2.9.43 signal_manager方法提取7子方法(execute_signals 161→24行+update_signals 96→9行)+版本同步+1000测试全通过 | v2.9.44 _SubprocessRuntime提取(scanner_daemon 303行闭包→独立类+命令路由表5子handler+_send_ack统一+16新增测试) | v2.9.46 bare except清理(web API)+版本同步+_check_stop_loss_take_profit简化+section合并 | v2.9.47 getattr/hasattr防御消除+关键路径日志级别提升+18新增测试 | v2.9.48 pipeline.apply提取(187→103)+broker.place_order提取(182→109)+33新增测试 | v2.9.49 审查P0安全修复(WS Token首条消息认证+Trading API越权访问)+P1修复(Stream consumer动态化+持仓批量价格查询)+P2修复(System API同步MongoDB→异步)+19新增测试 | v2.9.50 🔴Daemon方法名Bug修复(update_strategy_params→update_strategy_config/run_once→scan_once)+hasattr防御清理6处+except Exception收窄9处+15新增测试 | v2.9.51 getattr防御清理18处+broker正式接口(get_limit_prices/get_realtime_prices)+🔴_daily_start_asset日内回撤永远为0bug修复+_last_scan_duration_ms初始化+22新增测试 | v2.9.52 getattr/hasattr清理(broker/position_manager/runtime_persistence/strategy_scorer/risk_watchdog 5文件)+DELEGATE_MAP外提到scanner_delegate_router(scanner 1391→1308 -83行)+@classmethod@property兼容别名+7测试文件更新+1177测试全通过 |
| v2.9.53 返回类型注解补全(14个核心模块0.3%缺失,总体9.6%)+scanner_delegate_router Any导入修复+1177测试全通过 |
| v2.9.54 _init_broker拆分(_init_broker_gm/_init_broker_sim提取)+_scan_loop_trading健壮性(scan_once异常不传播)+_restart_risk_thread_if_dead看门狗提取+_try_recover_quote_source行情恢复提取+25新增测试+1151全通过 |
> 回测影响: 零文件修改, 1228测试全通过(scanner 1177+backtest 51)

---

## 四十六、v2.9.56 _init_state分组提取 + _risk_tick_body提取 + ScannerDaemon方法提取 (2026-06-02)

### 46.1 设计目标

1. **🟡 _init_state分组提取**: 42行→7行, 提取4个子方法(_init_risk_state/_init_execution_state/_init_cache_state/_init_signal_state)
2. **🟡 _risk_tick_body提取**: _risk_loop_sync 52行→32行(-38%), 循环体提取为独立方法
3. **🟡 ScannerDaemon._handle_subscription_message**: _subscribe_loop 49行→29行(-41%), 消息处理提取
4. **🟡 ScannerDaemon._restart_subprocess**: _watchdog_loop 45行→32行(-29%), 重启逻辑提取
5. **🟡 ScannerDaemon._wait_for_ack**: send_command 46行→39行(-15%), ACK等待提取
6. **🟡 ScannerDaemon._terminate_process**: stop() 42行→34行(-19%), 进程终止提取

### 46.2 _init_state分组提取

**问题**: _init_state 42行, 9个注释分组(风控/执行/缓存/信号)混在一个方法中。

**修复**: 按注释分组提取为4个子方法:

| 方法 | 职责 | 包含状态 |
|---|---|---|
| `_init_risk_state()` | 风控+交易 | trailing_stops, pending_sells, SELL_LOGIC_MODE |
| `_init_execution_state()` | 执行质量 | execution_stats |
| `_init_cache_state()` | 数据缓存 | realtime_cache, daily_factors_df, all_codes |
| `_init_signal_state()` | 信号+统计 | active_signals, timeline, stats |

### 46.3 _risk_tick_body提取

**问题**: _risk_loop_sync 52行, 循环体(阶段判断→行情读取→过期检测→止损→周期检查)与异常处理混在一起。

**修复**: 循环体提取为`_risk_tick_body(tick)`, _risk_loop_sync只保留循环+异常处理+sleep:
- _risk_loop_sync: 52行→32行(-38%)
- _risk_tick_body: 27行(新)

### 46.4 ScannerDaemon方法提取

| 方法 | 来源 | 行数变化 |
|---|---|---|
| `_handle_subscription_message` | _subscribe_loop消息处理 | 27行(新), _subscribe_loop 49→29(-41%) |
| `_restart_subprocess` | _watchdog_loop重启逻辑 | 18行(新), _watchdog_loop 45→32(-29%) |
| `_wait_for_ack` | send_command ACK等待 | 14行(新), send_command 46→39(-15%) |
| `_terminate_process` | stop()进程终止 | 14行(新), stop 42→34(-19%) |

### 46.5 变更文件

| 文件 | 变更 |
|---|---|
| scanner.py | _init_state分组+_risk_tick_body提取 |
| scanner_daemon.py | 4个方法提取 |
| web/api/scanner.py | _DESIGN_DOC_VERSION→v2.9.56 |
| test_v2956_init_state_risk_tick_daemon.py | 新增30测试 |
| test_v2921/test_v2937 | 测试适配(MarketPhase委托+init_state分组) |
| 12个版本断言文件 | v2.9.55→v2.9.56 |

### 46.6 方法行数改善

| 方法 | v2.9.55 | v2.9.56 | 变化 |
|---|---|---|---|
| _init_state | 42行 | 7行 | -83% |
| _risk_loop_sync | 52行 | 32行 | -38% |
| **新增** | | | |
| _init_risk_state | - | 9行 | 风控状态初始化 |
| _init_execution_state | - | 10行 | 执行质量初始化 |
| _init_cache_state | - | 7行 | 数据缓存初始化 |
| _init_signal_state | - | 15行 | 信号+统计初始化 |
| _risk_tick_body | - | 27行 | 风控单次循环体 |

**ScannerDaemon方法行数改善:**

| 方法 | v2.9.55 | v2.9.56 | 变化 |
|---|---|---|---|
| _subscribe_loop | 49行 | 29行 | -41% |
| _watchdog_loop | 45行 | 32行 | -29% |
| send_command | 46行 | 39行 | -15% |
| stop | 42行 | 34行 | -19% |
| **新增** | | | |
| _handle_subscription_message | - | 27行 | 订阅消息处理 |
| _restart_subprocess | - | 18行 | 子进程重启 |
| _wait_for_ack | - | 14行 | ACK等待 |
| _terminate_process | - | 14行 | 进程终止 |

### 46.7 测试覆盖 (30新增)

| 测试类 | 用例数 | 覆盖点 |
|---|---|---|
| TestInitStateDecomposition | 9 | 4个子方法存在+调用+内容+行数 |
| TestRiskTickBodyExtraction | 4 | 存在+调用+内容+行数 |
| TestDaemonSubscriptionMessageExtraction | 3 | 存在+调用+行数 |
| TestDaemonRestartSubprocessExtraction | 3 | 存在+调用+内容 |
| TestDaemonWaitForAckExtraction | 3 | 存在+调用+超时处理 |
| TestDaemonTerminateProcessExtraction | 3 | 存在+调用+三阶段终止 |
| TestNoBacktestRegressionV2956 | 5 | 导入+文件+版本常量 |

**全量测试**: 1350 passed (0 failed)

### 46.8 回测影响

零。所有变更仅影响market_monitor模块内部重构和测试, 回测引擎零文件修改。

---

## 四十五、v2.9.55 _StepTimer提取 + scan_loop阶段处理程序 + start初始化序列提取 (2026-06-02)

### 45.1 设计目标

1. **🟡 _StepTimer上下文管理器**: scan_once 7个手动计时变量→`with timer.step()`模式,消除step1_ms~step5_ms和t1~t5变量
2. **🟡 _scan_loop阶段处理提取**: WEEKEND→`_handle_weekend_phase()`, PREMARKET/AUCTION→`_handle_premarket_phase()`, 使_scan_loop更清晰
3. **🟡 _start_init_sequence提取**: start()中参数校验+策略加载+漂移检测+盘前准备+资产记录+状态恢复+事件注册→独立方法
4. **🟢 6个测试文件路径修复**: test_v2950的`open("AgentServer/nodes/...")`→基于`__file__`的绝对路径

### 45.2 _StepTimer上下文管理器

**问题**: scan_once中7个计时变量(t1~t5, step1_ms~step5_ms)+5行耗时计算+5元素列表传给`_format_slow_steps`, 占64行方法中约15行纯计时样板代码。

**修复**: 提取`_StepTimer`类:
- `__slots__`优化内存
- `timer.step(name)`上下文管理器自动记录耗时(ms)
- `timer.get_slow_info()`生成慢步骤摘要(>500ms)
- 异常安全: 步骤中异常仍记录耗时

```python
timer = _StepTimer()
with timer.step("行情"):
    realtime_data = await self._fetch_realtime_batch(force=force)
with timer.step("因子"):
    merged_df = self._merge_factors(realtime_data)
# ...
slow_info = timer.get_slow_info()
```

### 45.3 _scan_loop阶段处理提取

**问题**: _scan_loop中WEEKEND和PREMARKET/AUCTION的分支处理(各5-8行)混在主循环的if/elif链中,影响可读性。

**修复**: 提取2个独立方法:

| 方法 | 职责 | 来源 |
|---|---|---|
| `_handle_weekend_phase(trade_date)` | 周末持仓检查+60秒休眠 | 原WEEKEND分支 |
| `_handle_premarket_phase(trade_date)` | 盘前竞价+120秒休眠 | 原PREMARKET/AUCTION分支 |

_scan_loop: 56行→38行(-32%)

### 45.4 _start_init_sequence提取

**问题**: start()中14行初始化步骤(参数校验→策略加载→漂移检测→盘前准备→资产记录→状态恢复→事件订阅)与启动流程控制混在一起。

**修复**: 提取为`_start_init_sequence(trade_date)`, start()只负责:
1. 状态检查(已在运行?)
2. 线程锁初始化
3. 交易日期设置
4. 调用`_start_init_sequence`
5. 启动主循环+风控线程+分级行情+时间线

start(): 57行→29行(-49%)

### 45.5 测试路径修复

**问题**: test_v2950_audit_fixes.py中6个测试使用`open("AgentServer/nodes/...")`,但pytest工作目录是`AgentServer/`,导致FileNotFoundError。

**修复**: 改用`os.path.dirname(os.path.abspath(__file__))`计算绝对路径,不再依赖工作目录。

### 45.6 变更文件

| 文件 | 变更 |
|---|---|
| scanner.py | _StepTimer类+scan_once重构+_scan_loop阶段处理提取+_start_init_sequence提取 |
| web/api/scanner.py | _DESIGN_DOC_VERSION→v2.9.55 |
| test_v2955_step_timer_phase_handlers.py | 新增24测试 |
| test_v2950_audit_fixes.py | 6个测试路径修复 |
| test_v2918/22/2933/37/38/39/40/41/43/47/54 | 版本断言v2.9.54→v2.9.55 |
| MARKET_MONITOR_OPTIMIZATION_DESIGN.md | v2.9.55记录 |

### 45.7 scanner.py行数变化

| 阶段 | 行数 | 变化 |
|---|---|---|
| v2.9.54 | 1335 | 基线 |
| **v2.9.55** | **1395** | **+60行(_StepTimer 52行+5个提取方法39行, scan_once -9行, _scan_loop -9行, start -22行, premarket_prepare -21行, stop -15行)** |

### 45.8 方法行数改善

| 方法 | v2.9.54 | v2.9.55 | 变化 |
|---|---|---|---|
| scan_once | 64行 | 55行 | -14% |
| _scan_loop | 56行 | 47行 | -16% |
| start | 57行 | 35行 | -39% |
| premarket_prepare | 41行 | 20行 | -51% |
| stop | 40行 | 25行 | -38% |
| **新增** | | | |
| _StepTimer | - | 52行 | 分步计时器 |
| _handle_weekend_phase | - | 7行 | 周末处理 |
| _handle_premarket_phase | - | 5行 | 盘前处理 |
| _start_init_sequence | - | 17行 | 初始化序列 |
| _load_premarket_data | - | 9行 | 盘前数据加载 |
| _check_premarket_auction | - | 6行 | 竞价检查 |
| _stop_cleanup | - | 12行 | 停止清理 |

### 45.9 测试覆盖 (33新增)

| 测试类 | 用例数 | 覆盖点 |
|---|---|---|
| TestStepTimer | 6 | 类存在+记录步骤+慢步骤+空慢步骤+__slots__+异常处理 |
| TestScanOnceRefactoring | 3 | _StepTimer使用+行数+get_slow_info |
| TestScanLoopPhaseHandlers | 7 | 方法存在+调用+行数+内容验证 |
| TestStartInitSequence | 4 | 方法存在+调用+关键步骤+行数 |
| TestPremarketPrepareExtraction | 5 | 方法存在+调用+内容+行数 |
| TestStopCleanupExtraction | 4 | 方法存在+调用+内容+行数 |
| TestNoBacktestRegressionV2955 | 5 | 导入+文件+版本常量 |

**全量测试**: 1184 passed (0 failed) + 50 backtest passed

### 45.10 回测影响

零。所有变更仅影响market_monitor模块内部重构和测试, 回测引擎零文件修改。

---

## 四十四、v2.9.54 _init_broker拆分 + _scan_loop_trading健壮性 + 看门狗/行情恢复提取 (2026-06-02)

### 44.1 设计目标

1. **🟡 _init_broker拆分**: 42行→15行, 提取`_init_broker_gm()`和`_init_broker_sim()`两个独立方法
2. **🔴 _scan_loop_trading健壮性**: `scan_once`异常不向上传播,返回False让主循环继续(避免一次扫描失败导致整个循环退出)
3. **🟡 _restart_risk_thread_if_dead提取**: 风控看门狗逻辑从_scan_loop_trading提取为独立方法
4. **🟡 _try_recover_quote_source提取**: 行情恢复逻辑从_scan_loop_trading提取为独立方法

### 44.2 _init_broker拆分

**问题**: `_init_broker` 42行, 包含4个分支(GM/dry_run/replay/标准),每个分支独立初始化不同类型的Broker,混杂在一个方法中。

**修复**: 提取2个独立方法:

| 方法 | 职责 | 来源 |
|---|---|---|
| `_init_broker_gm()` | 创建GmBroker实例,设broker=None | 原GM分支 |
| `_init_broker_sim(trade_mode)` | 创建SimulatedBroker+replay/dry_run/标准3种模式 | 原else分支 |

**_init_broker主方法**: 15行,仅判断GM/非GM后委托。

### 44.3 _scan_loop_trading健壮性

**问题**: `_scan_loop_trading`中`await self.scan_once(trade_date)`无try/except保护。scan_once抛异常时,异常传播到`_scan_loop`的外层except,触发`_scan_loop_error_recovery`。但error_recovery会增加`_scan_loop_error_count`,连续3次异常会杀掉整个scanner。一次MongoDB抖动导致的scan_once失败不应直接计入错误计数。

**修复**: scan_once调用加try/except,异常时仅记录error并返回False(让主循环继续下一轮):

```python
try:
    await self.scan_once(trade_date)
    return True
except Exception as e:
    logger.error(f"[SCAN_TRADING] scan_once异常: {e}")
    self._scan_loop_error_count += 1
    return False
```

**注意**: 仍增加`_scan_loop_error_count`,但不会触发`_is_running = False`(连续3次杀循环的逻辑在_scan_loop的error_recovery中,此处仅计数+返回False)。

### 44.4 _restart_risk_thread_if_dead提取

**问题**: `_scan_loop_trading`中15行风控看门狗逻辑(检测线程退出+重启+告警)与扫描逻辑无关,应独立方法。

**修复**: 提取为`_restart_risk_thread_if_dead()`方法:
- 早期返回: 线程存活时直接return
- 重启: 创建新风控线程并启动
- 告警: 重启≥3次时发射事件(用try/except保护,事件循环可能未就绪)

### 44.5 _try_recover_quote_source提取

**问题**: `_scan_loop_trading`中10行行情恢复逻辑与扫描逻辑无关。

**修复**: 提取为`_try_recover_quote_source()`方法:
- 早期返回: `should_try_recover()`为False时直接return
- 尝试恢复: 调用`try_recover()`+更新降级等级+发射恢复事件
- 异常保护: `except (ConnectionError, OSError, TimeoutError)`

### 44.6 变更文件

| 文件 | 变更 |
|---|---|
| scanner.py | _init_broker拆分+_scan_loop_trading健壮性+2个方法提取 |
| web/api/scanner.py | _DESIGN_DOC_VERSION→v2.9.54 |
| test_v2954_init_broker_scan_robust.py | 新增25测试 |
| test_v295_stability.py | 看门狗测试适配(_restart_risk_thread_if_dead) |
| test_v2916_risk_watchdog_thread_safety.py | 版本断言v2.9.51→v2.9.54 |
| test_v2933/37/38/39/40/41/47/43 | 版本断言统一v2.9.54 |
| MARKET_MONITOR_OPTIMIZATION_DESIGN.md | v2.9.54记录 |

### 44.7 scanner.py行数变化

| 阶段 | 行数 | 变化 |
|---|---|---|
| v2.9.53 | 1308 | 基线 |
| **v2.9.54** | **1335** | **+27行(2个提取方法+scan_once异常保护, _init_broker减少27行但新方法+28行, _scan_loop_trading减少24行但新方法+25行)** |

### 44.8 方法行数改善

| 方法 | v2.9.53 | v2.9.54 | 变化 |
|---|---|---|---|
| _init_broker | 42行 | 15行 | -64% |
| _scan_loop_trading | 46行 | 22行 | -52% |
| **新增** | | | |
| _init_broker_gm | - | 14行 | 掘金Broker初始化 |
| _init_broker_sim | - | 23行 | 仿真Broker初始化 |
| _restart_risk_thread_if_dead | - | 18行 | 风控看门狗 |
| _try_recover_quote_source | - | 12行 | 行情恢复 |

### 44.9 测试覆盖 (25新增)

| 测试类 | 用例数 | 覆盖点 |
|---|---|---|
| TestInitBrokerDecomposition | 8 | _init_broker_gm/sim存在+委托+行数+内容 |
| TestScanLoopTradingRobustness | 3 | try/except包裹+返回False+行数 |
| TestRestartRiskThreadExtraction | 5 | 存在+创建线程+重启计数+早期返回+委托 |
| TestTryRecoverQuoteSourceExtraction | 4 | 存在+should_try_recover+try_recover+委托 |
| TestNoBacktestRegressionV2954 | 5 | 回测零影响 |

**全量测试**: 1151 passed (0 failed)

### 44.10 回测影响

零。所有变更仅影响market_monitor模块内部重构和测试, 回测引擎零文件修改。

---

## 〇、修订记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v2.0 | 2026-05-28 | 初版 |
| v2.0 | 2026-05-28 | 纳入28项深度审查修正(架构/数据/金融/运维/安全5维度) |
| v2.1 | 2026-05-29 | Phase1.3 API修复: PositionChecker→SellSignalChecker签名对齐 |
| v2.2 | 2026-05-29 | 代码审查: 8空委托桩+3隐式None+2回测契约+pending_sells统一+SellSignalChecker缓存 |
| v2.3 | 2026-05-29 | 线程安全: _state_lock保护共享状态+SELL_PRIORITY排序+2并发测试 |
| v2.4 | 2026-05-29 | 深度审查: 情绪调仓委托修复+风控卖出加锁+compare补trade_days_held+2回归测试 |
| v2.5 | 2026-05-29 | 审查优化: PositionManager线程安全trailing_stops读取+PortfolioBacktester缓存+因子测试修复+13回归测试 |
| v2.6 | 2026-05-29 | 继续优化: _trade_date/_nav_peak初始化bug修复+异动检测提取到StrategyScorer+仓位计算提取到PositionManager+策略配置管理提取到StrategyParamCenter+22集成测试+limit_up_count字段修复 |
| v2.7 | 2026-05-29 | EventBus: ScannerEventBus内部事件总线+Scanner集成5个发射点+StrategyScorer NaN防御修复+107新增测试(33 EventBus+22 StrategyScorer+52 FilterPipeline) |
| v2.8 | 2026-05-29 | EventBus订阅器: 8组事件处理器(审计日志/快照触发/Redis推送/健康指标)+行情降级恢复事件发射+盘后结算事件+EventBus API端点(/event-bus/stats+history)+23集成测试 |
| v2.9 | 2026-05-29 | 架构解耦: QuoteManager回调消除循环依赖+盘后结算EventBus解耦+跌停检查去重+运行时快照跨日校验+22新增测试(253总计) |
| v2.9.1 | 2026-05-29 | _apply_filter_pipeline拆分: 提取_signals_to_candidates/_execute_force_empty/_merge_filter_result |
| v2.9.2 | 2026-05-29 | EventBus事件完整性: PositionChecker/SignalManager买入卖出均发射事件+4新增测试(257总计) |
| v2.9.3 | 2026-05-29 | __init__拆分5个_init_*+__getattr__动态委托消除27个存根方法(方法数74→54,行数1836→1780)+9新增测试(266总计) |
| v2.9.4 | 2026-05-29 | 健康度评分提取ScannerUtils+情绪调仓规则迁移EmotionCycle+pending_sells超时恢复增强+跌停挂起价格更新+21新增测试(344总计) |
| v2.9.5 | 2026-05-29 | 内部迭代(scanner行数1813→1780, 54方法) |
| v2.9.6 | 2026-05-30 | CircuitBreaker提取RiskWatchdog+情绪卖出列表提取_build_emotion_sell_list+绩效快照/飞书日报提取RuntimePersistence+_calc_stop_loss/_calc_take_profit加入DELEGATE_MAP移除fallback+Compare模式一致性验证测试+_execute_risk_sell/_execute_sell_list漏调_record_trade_result修复+_is_limit_down移除fallback加入DELEGATE_MAP+bare except修复+24新增测试(471总计,scanner 1710行53方法) |
| v2.9.7 | 2026-05-30 | Phase2.1完善: scanner:cmd从Pub/Sub升级为List+ACK(RPUSH/BLPOP+ACK确认+超时处理)+Daemon告警Redis事件发布+/health集成Daemon状态+EventBus handler耗时统计+/daemon/status+/daemon/restart端点+scan-traces性能优化(rejected摘要)+25新增测试(496总计) |
| v2.9.8 | 2026-05-30 | Phase4完善: /health新增version字段(git_hash/branch/设计文档版本)+WS断线重连3秒(设计文档规范)+Scanner Store集成验证+13新增测试(514总计) |
| v2.9.9 | 2026-05-30 | 委托存根消除: 10个显式委托桩移至DELEGATE_MAP+__getattr__动态委托(_merge_factors/_get_effective_strategy_config/_get_strategy_risk/_detect_anomalies/_compute_health_score/_check_circuit_breaker/_record_trade_result/reset_circuit_breaker/_save_performance_snapshot/_push_daily_summary)+profit_pct转换修复(移除启发式,统一/100.0)+_is_limit_down死条目清理+__getattr__扩展(_risk_watchdog_class静态方法绑定/_strategy_scorer fallback+async wrapper)+安全审查: _execute_force_empty的broker.sell()→broker.place_order()修复+get_status()/get_positions() broker None guard+_ASYNC_DELEGATE_METHODS清理+514测试全通过(scanner 1716行44方法39 DELEGATE_MAP条目) |
| v2.9.10 | 2026-05-30 | /health端点优化: 健康度统一(API层100扣减+scanner_health绿黄红→base_score映射green=100/yellow=60/red=30+金融扣减)+版本常量_DESIGN_DOC_VERSION=v2.9.9(不再硬编码)+版本缓存_version_cache(5分钟TTL,避免每次git子进程)+pending_sells线程安全读取(加state_lock)+合并warnings(scanner_health+金融指标)+16新增测试(530总计) |
| v2.9.11 | 2026-05-30 | API端点线程安全: _safe_read_shared辅助函数(统一state_lock保护共享状态读取)+7处unsafe getattr(_trailing_stops/_position_risk_levels)替换+set_trailing_stop写操作在state_lock内完成(读拷贝/写引用模式)+12新增测试(542总计) |
| v2.9.12 | 2026-05-30 | 关键路径健壮性: _execute_force_empty单票异常不中断强制空仓+stop()清仓单票try/except+_execute_risk_sell place_order独立异常保护+EventBus/publish事件包裹try/except+卖出失败warning日志 |
| v2.9.13 | 2026-05-30 | _scan_loop提取: 128行拆分为_scan_loop_trading/_scan_loop_settlement+线程安全补全(4处无锁修复)+.bak清理+27新增测试(433总计) |
| v2.9.14 | 2026-05-30 | Redis Stream升级: scanner:position从Pub/Sub→xadd(maxlen=5000)+signal订阅器Stream(maxlen=1000)+_push_to_redis双模式+审计日志TTL索引(90天)+WS断线补发catchup_scanner_stream+Stream消费API(/stream/signals+/stream/positions)+消费兼容扁平字段+33新增测试+测试路径修复(472总计) |
| v2.9.16 | 2026-05-30 | 🔴risk_watchdog pause_reason元组bug修复 + circuit_breaker线程安全(check/record/reset均持_state_lock) + 🟡_build_emotion_sell_list提取为EmotionCycleManager.build_emotion_sell_list静态方法(回调解耦) + 🟡strategy配置方法简化(Except替代ImportError/直接持久化) + emergency_liquidate线程安全审查(文档注释) + 23新增测试(644总计) |
| v2.9.17 | 2026-05-30 | DelegateRouter提取(scanner.py __getattr__ 95行→8行) + _with_state_lock统一加锁辅助(3个RiskWatchdog方法+2个scanner方法消除if/else重复) + 参数审计增强(PARAM_UPDATED事件含old_values) + scanner.py 1766→1672行(-5.3%) + 35新增测试(682总计) |
| v2.9.15 | 2026-05-30 | 错误遥测: SCANNER_ERROR事件(扫描异常+风控线程异常→EventBus→Redis→前端弹窗)+HEALTH_CHANGED事件枚举+参数预检API(/params/validate, 5项检查, is_safe字段)+Stream消息含_stream_id+前端追踪lastSignalStreamId/lastPositionStreamId(断线补发)+16新增测试(488总计) |
| v2.9.18 | 2026-05-30 | stop()拆分+QuoteManager封装+pending_sells安全拷贝+_check_force_empty返回stats |
| v2.9.19 | 2026-05-30 | _execute_risk_sell拆分+scan_once提取+_scan_loop回放提取+get_status简化 |
| v2.9.20 | 2026-05-31 | _liquidate_positions提取+_execute_force_empty T+1合规修复 |
| v2.9.21 | 2026-05-31 | MarketPhase时间分类提取+循环门控统一 |
| v2.9.22 | 2026-05-31 | 分步计时+卖出统计分类修复+跨日一致性+错误恢复 |
| v2.9.23 | 2026-05-31 | 行情缓存过期检测+异常日志增强+跌停恢复重试+提取重构 |
| v2.9.24 | 2026-05-31 | diagnose提取到ScannerUtils+情绪调仓提取到EmotionCycleManager+DelegateRouter策略3.5+scanner 2103→1966行(-6.5%)+13新增测试 |
| v2.9.25 | 2026-05-31 | 🔴update_strategy_config双except bug修复(更新只在异常路径执行)+缺少本地import修复+🟡6个bare except Exception:→except Exception as _e:+🟡_init_modules拆分4子方法(_init_event_and_quote/_init_signal_and_risk/_init_core_modules/_init_execution_quality)+17新增测试(726总计) |
| v2.9.26 | 2026-05-31 | 🟡30个bare except全模块清理(12个market_monitor子模块)+🟡position_checker._execute_sell_list 106行→4方法(主方法27行+_handle_limit_down_pending 15行+_place_sell_order 22行+_post_sell_processing 62行)+726scanner+51backtest零回归 |
| v2.9.27 | 2026-05-31 | 🟡5个方法提取到子模块(_build_account_info→ScannerUtils/_build_timeline_entry→RuntimePersistence/_post_sell_cleanup→RuntimePersistence/_retry_pending_sells→PositionManager/_execute_sell_list_from_risk→PositionManager)+13个源码检查测试适配+scanner 1966→1810行(-7.9%)+726+51全通过 |
| v2.9.28 | 2026-05-31 | 🟡风控线程拆分(_risk_non_trading_sleep/_check_stale_quote_cache/_risk_error_backoff)+_merge_filter_result→LiveFilterPipeline+_scan_loop_error_recovery提取+scan_once慢步骤日志→ScannerUtils.format_slow_steps+_init_state注释分组9域+DELEGATE_MAP+2条目+scanner 1810→1769行(-2.3%)+777全通过 |
| v2.9.29 | 2026-05-31 | 🟢冗余注释清理+section合并 | 777全通过 |
| v2.9.30 | 2026-05-31 | 🟡_risk_periodic_checks提取(风控线程周期性检查60s/30s)+缩进修复 | 777全通过 |
| v2.9.31 | 2026-05-31 | 🔴RuntimeWarning修复(ensure_future→create_task+call_soon_threadsafe)
| v2.9.32 | 2026-05-31 | 🔴3处ensure_future→loop.create_task修复(scanner.py)+🟡2处ensure_future→loop.create_task修复(quote_manager.py)+🟡7个方法提取到RuntimePersistence(load_stock_list/load_daily_factors/load_stock_name_map/warm_weekend_cache/persist_stop_state/restore_start_state/load_positions)+🟡1个方法提取到RiskWatchdog(reset_daily_risk_state)+🟡8个DELEGATE_MAP新增条目+scanner 1742→1538行(-11.7%)+940全通过(747scanner+193backtest) |+🟡_safe_read_state统一(4个_safe_copy_*方法共享state_lock读取)+🟡get_positions提取→ScannerUtils.build_position_dict+🟡_apply_filter_pipeline拆分_process_filter_result+scanner 1742→1742行(行数不变, 职责更清晰)+777全通过 |
| v2.9.33 | 2026-05-31 | 🟡scan_once Step3提取_apply_strategies_and_filters(策略+筛选+异动合并)+🟡_risk_loop_sync异常事件发射提取_emit_risk_thread_error+🟡get_status子模块状态提取_build_module_status+scanner 1538→1568行(+30,3个提取方法)+767scanner+51backtest全通过 |
| v2.9.34 | 2026-05-31 | 🟡_update_sentiment_score提取到EmotionCycleManager(58行→3行委托)+🟡_sync_close_data_to_mongo提取到RuntimePersistence(67行→3行委托)+DELEGATE_MAP新增2条目+DelegateRouter _EMOTION_BINDINGS+async注册+scanner 1701→1579行(-7.2%)+844全通过(793scanner+51backtest) |
| v2.9.35 | 2026-05-31 | 🟡_execute_risk_sell提取到PositionManager.execute_risk_sell(25行→3行委托)+🟡_liquidate_positions提取到PositionManager.liquidate_positions(38行→3行委托)+execute_sell_list_from_risk改调self.execute_risk_sell+DELEGATE_MAP新增2条目+scanner 1574→1513行(-3.9%)+845全通过(794scanner+51backtest) |

v2.0关键修正:
- ❶ 风控独立线程: asyncio协程→threading.Thread(真并行不受GIL影响)
- ❷ 误读双层节奏: 当前是5分钟full+30秒quick,不是简单串行
- ❸ 持仓快照与Broker冲突: Broker为唯一权威,快照只存Scanner独有状态
- ❹ 卖出迁移会丢功能: Scanner缺利润锁定,checker缺追踪止损/移动止损,必须先补齐
- ❺ 行情降级无恢复: 加5分钟自动恢复机制
- ❻ 灰度上线: 加compare双跑对比模式,环境变量一键回滚
- ❼ MongoDB故障: 快照写失败降级本地文件
- ❽ 跌停不可卖: 风控循环必须考虑
- ❾ 追踪止损状态: 留在Scanner,checker只做判断(与回测一致)
- ❿ 两层仓位逻辑: 策略仓位×情绪仓位,公式明确

---

## 一、现状与问题

### 1.1 系统架构现状

```
┌─────────────────────────────────────────────────────┐
│                   Web Node (FastAPI :8000)           │
│  /api/v1/scanner/*  /api/v1/market/*  /api/v1/ws    │
└───────────────────────┬─────────────────────────────┘
                        │ Redis Pub/Sub (fire-and-forget)
┌───────────────────────┴─────────────────────────────┐
│              ScannerDaemon (独立子进程)                │
│  守护进程：自动重启(max 3次)、心跳、IPC桥接             │
└───────────────────────┬─────────────────────────────┘
                        │ 内部调用
┌───────────────────────┴─────────────────────────────┐
│              MarketScanner (核心引擎, 2907行)          │
│  信号扫描 + 持仓管理 + 止损止盈 + 信号执行              │
└─────────────────────────────────────────────────────┘
```

### 1.2 当前双层扫描节奏(关键)

> **v2.0修正**: 原设计误读为"扫描→风控串行"，实际是双层节奏

```
当前 _scan_loop 实际架构:

  5分钟: scan_once() ─→ _check_positions(full, 量脉实时行情)
  30秒:  _check_positions_quick(quick, 东财免费缓存)
         └─ 东财3秒全市场5400只，不消耗量脉额度
         └─ 含跌停不可卖检查、跳空止损
  盘前:  _premarket_auction (9:00-9:30, 2分钟间隔)
  盘后:  daily_settlement + save_state + 推送日报
  深夜:  30分钟极低频
```

风控循环设计必须基于这个双层节奏，不能简单拆为"1秒风控循环"。

### 1.3 核心代码量

| 模块 | 文件 | 行数 | 职责 |
|---|---|---|---|
| MarketScanner | scanner.py | 1568 | 信号扫描+持仓+风控+执行(委托模式+DelegateRouter) |
| ScannerDaemon | scanner_daemon.py | 1113 | 子进程守护(含_SubprocessRuntime) |
| LiveFilterPipeline | live_filter_pipeline.py | 645 | 9层过滤管道 |
| RiskWatchdog | risk_watchdog.py | 763 | 风控看门狗 + _with_state_lock |
| TieredScanner | tiered_scanner.py | 890 | 分级行情 |
| Broker | broker.py | 729 | 交易执行(含0.2%滑点) |
| SignalDispatcher | signal_dispatcher.py | 333 | 信号分发 |
| StrategyParamCenter | strategy_param_center.py | 330 | 参数中心 |
| EmotionCycleManager | emotion_cycle.py | 323 | 情绪周期 |
| 回测引擎 | portfolio_backtest.py | 4929 | 回测 |
| 卖出检查 | sell_signal_checker.py | 876 | 卖出信号(回测+PositionManager共用) |
| 策略默认参数 | strategy_defaults.py | 216 | 共享参数 |

### 1.4 回测-实盘代码关系

```
                    strategy_defaults.py (共享参数)
                   /          |          \
                  ▼           ▼           ▼
    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
    │  回测引擎      │  │  Scanner      │  │ PositionMgr  │
    │ sell_signal  │  │ ❌ 不用       │  │ ✅ 用         │
    │ _checker.py  │  │ 自行内嵌实现   │  │              │
    └──────────────┘  └──────────────┘  └──────────────┘
```

### 1.5 Scanner卖出 vs sell_signal_checker 卖出条件对比

> **v2.0新增**: 之前设计遗漏了结构性差异

| 卖出条件 | Scanner | checker | 差异 |
|---|---|---|---|
| 固定止损 | ✅ | ✅ | 一致 |
| 跳空止损 | ✅ | ✅ | 一致 |
| 追踪止损 | ✅ `_trailing_stops` | ❌ | **Scanner独有,迁移前补到checker** |
| 冲高回落 | ✅ | ✅ | 参数可能不同 |
| 利润保护 | ✅ | ✅ | 参数可能不同 |
| 高开即卖 | ✅ | ✅ | 一致 |
| **利润锁定** | **❌缺失** | ✅ | **Scanner漏了!盘中冲高8%回撤3%不触发** |
| 固定止盈 | ✅ | ✅ | 一致 |
| 超时强卖 | ✅ | ✅ | 一致 |
| 移动止损(保本) | ✅(盈利>2SL→保本) | ❌ | **Scanner独有,迁移前补到checker** |
| 龙头5天低利润 | ❌ | ✅ | **Scanner漏了** |
| 跌停不可卖 | ✅ `_is_limit_down` | N/A | Broker层逻辑,checker不管 |

### 1.6 仓位计算：两层逻辑

> **v2.0新增**: 原设计只提情绪仓位，遗漏策略仓位

```
单票买入金额 = available_cash × strategy_ratio × emotion_ratio × dynamic_ratio

strategy_ratio: 涨停40%/半路25%/跌停15%/龙头15%
emotion_ratio:  高潮1.0/分化0.7/震荡0.5/冰点0.3
dynamic_ratio:  持仓>50%时递减(已有逻辑)

总仓位上限: 70% (MAX_TOTAL_RATIO)
单票上限: 15% (占总资产)
```

### 1.7 P0问题清单

| # | 问题 | 影响 | 根因 |
|---|---|---|---|
| P0-1 | God Class 2907行 | 改一处坏全局 | 单一职责违反 |
| P0-2 | 盘中崩溃状态丢失 | 重启后风控失效 | 运行时状态无持久化 |
| P0-3 | 扫描和风控抢时间 | 止损延迟 | 风控无独立调度 |
| P0-4 | Redis Pub/Sub无保障 | 信号/状态丢失 | 无ACK机制 |
| P0-5 | 实盘-回测卖出逻辑分叉 | 回测结果不可信 | Scanner内嵌卖出逻辑 |
| P0-6 | Scanner缺利润锁定 | 盘中利润回吐 | V42对齐不完整 |
| P0-7 | 追踪止损/移动止损迁移后会丢 | 迁移后风控退化 | checker无状态 |

---

## 二、优化目标

1. **资金安全**: 盘中崩溃风控1秒恢复;止损永远优先于扫描
2. **实盘-回测一致**: 卖出逻辑统一为sell_signal_checker.py
3. **消息可靠**: 信号和持仓变更不丢失
4. **数据不断**: 行情故障自动降级+自动恢复
5. **可维护性**: 逐步拆分God Class，补充测试
6. **可观测性**: 健康度评分、审计日志、参数变更追踪
7. **灰度上线**: 高风险改动有compare双跑模式,环境变量一键回滚

---

## 三、Phase 1 — 资金安全保障 + 消除代码分叉（2-3周）

### 1.1 持仓状态实时持久化（3天）

**目标**: Scanner运行时状态变更立即持久化，重启后1秒内恢复

**v2.0修正: Broker是持仓唯一权威,快照只存Scanner独有状态**

Broker已有`save_state()`(30秒节流),Scanner快照不应重复存持仓:

```
Broker.save_state()  → 持仓+账户 [权威,已有]
Scanner快照          → 追踪止损+风险等级+情绪+熔断器+挂起卖出 [补充,新增]
```

**新增集合: scanner_runtime_snapshot**

```python
{
    "_id": "default",
    "trailing_stops": {"600036.SH": {"highest_price":41.2,"stop_price":40.17,"activated":True}},
    "position_risk_levels": {"600036.SH": "high"},
    "position_risk_overrides": {},
    "emotion_state": {"score":65,"phase":"differentiation","position_ratio":0.7},
    "circuit_breaker": {"consecutive_losses":2,"is_triggered":False},
    "pending_sells": {},     # 跌停挂起的卖出
    "updated_at": "...",
    "trade_date": "20260528"
}
```

**恢复流程(原子性)**:
1. Broker先恢复(权威持仓)
2. Scanner从快照恢复运行时状态
3. 一致性校验: 清理Broker已无持仓的追踪止损

**写入节流**:
- force=True(资金变动): 卖出后/买入后/停止时
- force=False(5秒节流): 追踪止损更新/情绪变更
- MongoDB不可用: 降级写`/tmp/scanner_snapshot_{account_id}.json`

**验证**: kill进程→Daemon重启→Broker持仓+Scanner追踪止损均恢复

---

### 1.2 风控独立线程（4天）

**v2.0关键修正**:
- ❌ 原设计用asyncio协程 → CPU密集操作会饿死风控
- ✅ 改用threading.Thread(真并行,不受asyncio事件循环影响)
- ❌ 原设计1秒循环 → 东财缓存3秒更新,1秒读同一份数据
- ✅ 改为分级节奏: 1秒止损检查(缓存) + 30秒完整quick check

**职责划分**:
```
risk_thread:  只负责卖出(止损/追踪止损/保护性卖出)
scan_loop:   只负责买入(信号扫描+执行) + 全量扫描(5分钟)
```

**设计**:
```python
class MarketScanner:
    def __init__(self):
        self._cache_lock = threading.Lock()    # 线程安全(非asyncio.Lock)
        self._position_lock = threading.Lock()
        self._risk_thread = None
        self._risk_running = False

    def _risk_loop_sync(self):
        tick = 0
        while self._risk_running:
            tick += 1
            with self._cache_lock:
                realtime_data = dict(self._realtime_cache)
            
            # 每1秒: 止损检查(缓存数据,零成本)
            self._check_stop_loss_only(realtime_data)
            
            # 每30秒: 完整quick check(东财缓存)
            if tick % 30 == 0:
                future = asyncio.run_coroutine_threadsafe(
                    self._check_positions_quick(self.trade_date), self._loop)
                future.result(timeout=10)
            
            time.sleep(1)  # 真sleep,不受asyncio影响

    def _check_stop_loss_only(self, realtime_data):
        """1秒级止损检查(轻量,含跌停不可卖)"""
        for pos in self._broker.get_positions():
            if pos.available_qty <= 0: continue  # T+1
            # ...止损/追踪止损检查...
            # 跌停不可卖 → 挂起到_pending_sells
            if self._is_limit_down(pos.ts_code):
                self._pending_sells[pos.ts_code] = (reason, price)
                continue
```

**关键**:
- threading.Lock(非asyncio.Lock)
- 跌停不可卖: 挂起到`_pending_sells`,不丢追踪止损
- 卖出通过`run_coroutine_threadsafe`提交到asyncio主循环
- 盘前/盘后: risk_loop加market_status判断

---

### 1.3 Scanner卖出逻辑迁移到sell_signal_checker.py（5天）

**v2.0修正: 迁移前先补齐checker缺失的3个条件**

| 功能 | 来源 | 处理 |
|---|---|---|
| 追踪止损 | Scanner独有 | checker新增`_check_trailing_stop`,状态由Scanner传入 |
| 移动止损(保本) | Scanner独有 | checker新增`_check_moving_stop` |
| 利润锁定 | checker独有 | Scanner接入`check_intraday_profit_lock` |

**追踪止损状态管理**: 状态留在Scanner(与回测一致),checker只做判断:
```python
result = checker.check_realtime_sell(
    position=pos,
    trailing_stop_state=self._trailing_stops.get(code),  # 传入状态
)
```

**卖出优先级表(可按策略覆盖)**:
```python
SELL_PRIORITY = {
    'stop_loss':10, 'gap_stop_loss':9, 'trailing_stop':8,
    'profit_lock':7, 'profit_protect':6, 'pullback':5,
    'high_open_sell':4, 'take_profit':3, 'moving_stop':3,
    'max_hold':2, 'rebalance':1, 'force_empty':0,
}
```

**灰度开关(可独立回滚)**:
```python
SELL_LOGIC_MODE = os.getenv("SELL_LOGIC_MODE", "legacy")
# "legacy"=旧逻辑 | "checker"=新逻辑 | "compare"=双跑对比(只执行旧)
```

**上线步骤**: compare跑3天→差异0→checker→1周→删除旧代码

---

## 四、Phase 2 — 可靠性提升（2-3周）

### 2.1 Redis通信升级（4天）

| 通道 | 改为 | 原因 |
|---|---|---|
| scanner:signal | **Redis Stream**(maxlen=1000) | 不可丢 |
| scanner:position | **Redis Stream**(maxlen=5000) | 不可丢 |
| scanner:cmd | **List + ACK** | 必须确认 |
| scanner:status/health | Pub/Sub(不变) | 允许丢 |

### 2.2 行情数据降级策略（3天）

三级降级+**自动恢复**(v2.0修正):
```
量脉实时 → 东财实时 → 东财日线缓存
  ↑每5分钟尝试恢复    ↑每5分钟尝试恢复
```

### 2.3 参数单一权威来源（2天）

启动时: MongoDB → strategy_defaults.py补全 → 写回MongoDB
运行时: 只读MongoDB
新增: `detect_drift()`配置漂移检测 + **参数变更审计**(v2.0修正)
- 危险参数告警: SL>10%/TP<3%等超出合理范围
- 审计日志: 谁/何时/改了什么

### 2.4 情绪仓位动态调整（3天）

phase转换时动态调仓(需回测同步):
- 高潮→分化: 新信号降仓
- 分化→震荡: 已有仓位减30%(分批,max_per_round=2,间隔0.5秒)
- 震荡→冰点: 低利润(<3%)清仓

---

## 五、Phase 3 — 架构治理（3-4周）

### 3.1 God Class拆分 ✅ 已完成（2周→3天）

**最终拆分结果: scanner.py 2907行→1757行 (-40%)**

```
MarketScanner(编排器, ~1846行, 30+委托方法)
  ├─ QuoteManager(行情, 352行) ← _fetch_realtime_batch ✅
  ├─ StrategyScorer(策略+异动, 332行) ← _merge_factors + _apply_strategies + _detect_anomalies ✅
  ├─ PositionManager(风控+仓位, 464行) ← _check_stop_loss_take_profit + _calc_position_ratio + _calc_would_buy_shares ✅
  ├─ PositionChecker(卖出, 497行) ← _check_positions(legacy/checker/compare) ✅
  ├─ SignalManager(信号, 382行) ← _update_signals + _execute_signals ✅
  ├─ ScannerUtils(工具, 274行) ← _safe_round + _publish + 序列化 + 报告 ✅
  ├─ RuntimePersistence(持久化, 777行) ← 快照/时间线/链路追踪/盘前竞价 ✅
  ├─ LiveFilterPipeline(过滤, 645行) ← _apply_filter_pipeline (已有)
  ├─ EmotionCycle(情绪, 323行) ← _update_emotion (已有)
  └─ RiskWatchdog(看门狗, 621行) ← 风控熔断 (已有)
```

**设计原则:**
1. 所有提取的方法在scanner.py中保留委托存根, 不破坏外部接口
2. 不影响策略回测模块(SellSignalChecker仍独立)
3. 灰度开关不变: SELL_LOGIC_MODE=legacy/checker/compare
4. 追踪止损状态留在Scanner, checker只做判断(与回测一致)
5. Broker为唯一持仓权威, 快照只存Scanner独有状态

**v2.0修正: 加ScannerEventBus事件总线解耦(待Phase2.1完成)**
```python
class ScannerEventBus:
    async def emit(self, event, data): ...
    def on(self, event, handler): ...
# 事件: position_changed / signal_generated / emotion_changed
```

### 3.2 死代码清理（1天）

删除: _deprecated/(6650行) + listener/(3912行) + .bak文件

### 3.3 核心模块测试（1周）

优先级: sell_signal_checker(30+) > FilterPipeline(20+) > StrategyScorer(15+)
含回测-实盘对齐自动化测试(v2.0修正)

### 3.4 审计日志（3天）

新增audit_log集合(append-only, TTL 90天)
记录信号→执行→成交端到端链路

---

## 六、Phase 4 — 运维体验（1-2周）

### 4.1 前端状态管理统一

Pinia Store + WS主通道 + REST fallback + 数据新鲜度(3s绿/5s黄/>5s红)

### 4.2 构建部署自动化

npm run deploy + .gitignore静态资源 + 健康检查API返回版本号

### 4.3 Scanner健康度(v2.0新增)

```python
health_score = {
    "scan_lag": time.time() - last_scan_ts,
    "risk_check_lag": time.time() - last_risk_check_ts,
    "quote_staleness": quote_manager.get_staleness(),
    "is_healthy": scan_lag<60 and risk_lag<5 and staleness<10,
    "warnings": [重启次数, 行情降级, 跌停挂起...]
}
```

### 4.4 Daemon重启3次后告警升级(v2.0新增)

3次重启失败→飞书紧急告警→可选紧急减仓

---

## 七、回测影响汇总

| 改动 | 影响 | 处理 |
|---|---|---|
| 1.1 持仓持久化 | ❌ 无 | — |
| 1.2 风控独立线程 | ❌ 无 | — |
| 1.3 卖出逻辑迁移 | ✅ 正面 | 消除分叉,灰度上线 |
| 2.1 Redis升级 | ❌ 无 | — |
| 2.2 行情降级 | ❌ 无 | — |
| 2.3 参数单一来源 | ⚠️ 轻度 | 回测仍读defaults |
| 2.4 情绪动态调仓 | ⚠️ 需同步 | 回测也要加 |
| 3.1 God Class拆分 | ⚠️ 需注意 | 不改共享模块路径 |

**核心原则**: 每次改动后跑回测基线,确认total_return差异<0.1%

---

## 八、代码审查修复记录 (v2.2)

### 8.1 空委托桩修复 (8个方法)

Phase3.1拆分后,scanner.py中8个委托方法只有docstring没有实现体,调用时静默返回None:

| 方法 | 修复前 | 修复后 |
|---|---|---|
| `_save_timeline` | 空 | → RuntimePersistence.save_timeline() |
| `_save_scan_traces` | 空 | → RuntimePersistence.save_scan_traces() |
| `_load_timeline` | 空 | → RuntimePersistence.load_timeline() |
| `_publish_scanner_event` | 空 | → ScannerUtils.publish_scanner_event() |
| `_position_to_dict` | 空 | → ScannerUtils.position_to_dict() |
| `_signal_to_dict` | 空 | → ScannerUtils.signal_to_dict() |
| `_extract_key_factors` | 空 | → ScannerUtils.extract_key_factors() |
| `generate_summary_report` | 空 | → ScannerUtils.generate_summary_report() |

### 8.2 隐式None返回修复 (3个方法)

委托方法fallback路径缺少返回值,调用方解引用可能crash:

| 方法 | 修复前 | 修复后 |
|---|---|---|
| `_merge_factors` | 隐式None | → pd.DataFrame() |
| `_get_effective_strategy_config` | 隐式None | → {} |
| `_get_strategy_risk` | 隐式None | → 默认风控参数 |

### 8.3 _is_limit_down fallback

原代码: `_is_limit_down` 只检查 `_position_checker`, 无fallback。修复: 从缓存读取pct_chg判断跌停。

### 8.4 pending_sells类型统一

原问题: scanner.py写入Tuple, position_checker.py写入Dict, 类型不一致。
修复: 统一为Dict格式 `{reason, price, added_at, source}`, 读取时兼容旧Tuple。

### 8.5 SellSignalChecker缓存

原问题: checker/compare模式每次调用都重建SellSignalChecker实例(遍历STRATEGY_CONFIGS)。
修复: 懒初始化缓存到 `_sell_checker`, 减少重复对象创建。

### 8.6 跌停恢复去重

原问题: scanner.py和PositionManager都有跌停恢复逻辑,可能导致重复执行。
修复: 移除scanner.py的恢复逻辑, 统一由PositionManager.check_stop_loss_only处理。

### 8.7 回测契约测试修复

| 测试 | 问题 | 修复 |
|---|---|---|
| `test_strategy_results_has_avg_profit_pct` | 0交易策略无avg_profit_pct字段 | 补充字段+旧数据软断言 |
| `test_total_return_is_percentage` | 接近0的合法百分比(如-0.94%)被误判为小数 | 改用策略量级对比启发式 |

### 8.8 线程安全修复 (v2.3)

**问题**: 风控独立线程(_risk_loop_sync)与asyncio主循环并发读写共享状态(trailing_stops/pending_sells/position_risk_levels)无锁保护,存在竞态条件:
- PositionManager.check_stop_loss_only: 风控线程读/写pending_sells无锁
- PositionManager.update_trailing_stops: 主循环写trailing_stops无锁
- PositionChecker._check_positions_checker: 读trailing_stops无锁
- RuntimePersistence.save_runtime_snapshot: 读共享状态无锁
- scanner._compute_health_score: 读pending_sells无锁
- 情绪调仓: 写pending_sells无锁

**修复**: 新增`_state_lock`(threading.Lock),保护所有共享可变状态读写:

| 模块 | 修复内容 |
|---|---|
| scanner.py | 新增`_state_lock`, risk_thread写pending_sells加锁, health_score读pending_sells加锁, 情绪调仓写pending_sells加锁 |
| position_manager.py | `check_stop_loss_only`中pending_sells/trailing_stops/position_risk_overrides读写加锁; `update_trailing_stops`读写加锁 |
| position_checker.py | trailing_stops读取加锁(深拷贝); pending_sells写入加锁; state清理加锁; `state_lock`属性代理 |
| runtime_persistence.py | `save_runtime_snapshot`读取共享状态加锁(深拷贝); `load_runtime_snapshot`恢复加锁; 盘前竞价写入加锁 |

**原则**: 锁粒度最小化——每个状态操作单独加锁,不跨方法持锁;读操作深拷贝后释放锁

### 8.9 SELL_PRIORITY排序 (v2.3)

**问题**: PositionChecker的checker模式返回的卖出信号未按优先级排序,可能先执行低优先级(如止盈)再执行高优先级(如止损)。

**修复**: checker模式结果按`SELL_PRIORITY`降序排序(止损10>追踪止损8>利润锁定7>止盈3),确保高优先级卖出先执行。

### 8.10 并发测试 (v2.3)

新增2个线程安全测试:
- `test_concurrent_trailing_stop_update`: 4线程×50只并发更新追踪止损,验证无crash/数据丢失
- `test_concurrent_pending_sells_access`: 2读+2写线程并发访问pending_sells,验证无crash

## 九、已知风险 (原八)

| 风险 | 缓解 |
|---|---|
| 卖出迁移后回测不一致 | compare灰度+逐笔对比 |
| 风控独立线程并发bug | threading.Lock+单线程测试 |
| 情绪减仓过度交易 | 保守参数+1周观察 |
| **除权除息成本调整缺失** | **profit_pct除权后失真可能误触发止损,P2优先级** |
| 滑点模型未对齐 | checker返回理想价,Broker执行加滑点0.2% |

---

## 十、时间线

```
Week 1-3:   Phase 1 (资金安全+消除分叉)
  Day 1-3:    1.1 持仓状态持久化
  Day 4-7:    1.2 风控独立线程
  Day 8-14:   1.3 卖出逻辑迁移(含灰度)
Week 4-6:   Phase 2 (可靠性)
Week 7-10:  Phase 3 (架构治理)
Week 11-12: Phase 4 (运维)
```

---

## 十一、验收标准

| Phase | 验收项 |
|---|---|
| 1 | kill进程→Broker持仓+追踪止损1秒恢复 + 风控1秒止损检查 + 回测差异<0.1% |
| 2 | Redis重启信号不丢 + 量脉429自动切东财+5分钟恢复 + 参数漂移告警 |
| 3 | MarketScanner<400行 + 测试30+用例 + 审计日志可查交易链路 |
| 4 | WS断线3秒重连 + 健康度评分(绿/黄/红) + Daemon3次失败有告警 |

**回退基线**: `git checkout v2.8.0-backtest-ui-v2`

---

## 十二、深度审查修复记录 (v2.4)

### 12.1 情绪调仓委托修复 (🔴 严重)

**问题**: `_handle_emotion_phase_change` 调用 `self._execute_sell_list()` 但 MarketScanner 无此方法,运行时会抛 AttributeError 导致情绪调仓完全失效。

**修复**: 改为委托 `self._position_checker._execute_sell_list(batch, trade_date, source="emotion")`, 与其他卖出路径保持一致。

### 12.2 风控卖出状态清理加锁 (🔴 严重)

**问题**: `_execute_risk_sell` 中 `self._trailing_stops.pop()` 和 `self._position_risk_levels.pop()` 未加 `_state_lock` 保护,与风控线程存在竞态条件。

**修复**: 在 `_execute_risk_sell` 卖出成功后的状态清理中加入 `with self._state_lock:` 块。

### 12.3 Compare模式补trade_days_held (🟡 中等)

**问题**: `_check_positions_compare` 调用 `checker.check_realtime_sell()` 时缺少 `trade_days_held` 参数,而 `_check_positions_checker` 有传,导致 compare 模式与 checker 模式可能产生超时强卖的误差异。

**修复**: 在 compare 模式中补充与 checker 模式一致的 `trade_days_held` 计算逻辑。

### 12.4 回归测试 (2个新增)

- `test_emotion_delegates_to_position_checker`: 验证情绪调仓委托到 PositionChecker
- `test_trailing_stops_cleanup_uses_lock`: 验证源码中 _execute_risk_sell 的 trailing_stops.pop 受 _state_lock 保护

---

## 十三、审查优化记录 (v2.5)

### 13.1 PositionManager线程安全读取 (🔴 严重)

**问题**: `PositionManager.check_stop_loss_take_profit` 直接调用 `self.trailing_stops.get(pos.ts_code)` 读取追踪止损状态,无锁保护。而风控线程(`_risk_loop_sync`)同时通过 `PositionManager.check_stop_loss_only` 和 `update_trailing_stops` 写入 `trailing_stops`,存在数据竞争:
- 主循环(5分钟full)调用 `check_stop_loss_take_profit` → 读 `trailing_stops` 无锁
- 风控线程(1秒)调用 `check_stop_loss_only` → 写 `pending_sells`/读 `trailing_stops` 有锁
- 风控线程调用 `update_trailing_stops` → 写 `trailing_stops` 有锁

在CPython中dict.get()是原子操作,但嵌套读取(`trailing.get("activated")`)和后续逻辑依赖读取一致性,可能导致:
1. 读取到半更新状态(activated=True但stop_price=旧值)
2. 迭代过程中dict被修改导致RuntimeError

**修复**: 新增 `_get_trailing_stop_safe()` 方法,使用 `state_lock` 深拷贝后释放锁,确保读取一致性:
```python
def _get_trailing_stop_safe(self, ts_code: str) -> Optional[Dict]:
    with self.state_lock:
        if ts_code in self.trailing_stops:
            return dict(self.trailing_stops[ts_code])
    return None
```

同时修复 `check_stop_loss_take_profit` 和 `check_moving_stop` 中 `position_risk_overrides` 的无锁读取:
```python
with self.state_lock:
    pos_overrides = dict(self.position_risk_overrides.get(pos.ts_code, {}))
```

### 13.2 PortfolioBacktester缓存 (🟡 中等)

**问题**: `PositionChecker` 的3个方法(`_check_positions_legacy`/`_check_positions_checker`/`_check_positions_compare`)每次调用都创建新的 `PortfolioBacktester()` 实例来计算 `trade_days_held`。在全量持仓检查(5分钟)中,如果有10个持仓,就创建10个实例。

**修复**: 新增 `_get_backtester()` 懒初始化缓存和 `_calc_trade_days_held()` 统一方法:
```python
def _get_backtester(self):
    if self._backtester is not None:
        return self._backtester
    from nodes.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester
    self._backtester = PortfolioBacktester()
    return self._backtester

def _calc_trade_days_held(self, buy_date, trade_date) -> Optional[int]:
    bt = self._get_backtester()
    if bt is None:
        return None
    try:
        return bt._calc_trade_days_held(int(buy_date), int(trade_date))
    except (ValueError, TypeError):
        return None
```

3处内联 `PortfolioBacktester()` 实例化替换为 `self._calc_trade_days_held()` 调用。

### 13.3 PositionChecker属性文档 (🟢 低)

**问题**: `trailing_stops` 和 `realtime_cache` 属性返回对内部可变dict的直接引用,调用方可能无意中绕过锁直接修改状态。

**修复**: 为两个属性添加文档说明,明确仅用于内部加锁场景:
```python
@property
def trailing_stops(self) -> Dict:
    """读取追踪止损状态(直接引用,仅用于内部加锁场景)"""
    return self._scanner._trailing_stops
```

### 13.4 因子单元测试修复 (🟢 低, 回测模块)

**问题**: `tests/test_strategies.py` 中4个测试失败(KeyError: 'limit_up_yesterday'/'first_limit_up'/'open_below_limit'),原因是测试DataFrame缺少因子列,直接调用 `compute_func=lambda df: df["column_name"]` 时触发KeyError。同时 `test_strategy_logic_consistency` 因模块导入失败而ModuleNotFoundError。

**修复**: 重写测试,不依赖 `compute_func` 的直传模式,改为本地计算函数验证因子逻辑:
- `_compute_limit_up_yesterday()`: 从close/up_limit列计算昨日涨停标记
- `_compute_first_limit_up()`: 从close/up_limit列计算首次涨停标记
- `_compute_open_below_limit()`: 从open/up_limit列计算开盘低于涨停价
- 新增 `test_factor_library_registration()`: 验证因子注册完整性
- `test_strategy_logic_consistency` 改为try/except处理模块不可用

### 13.5 回归测试 (13个新增)

新增 `test_thread_safety_v2.py` 测试文件:

| 测试类 | 测试项 | 验证内容 |
|---|---|---|
| PositionManagerThreadSafety | `_get_trailing_stop_safe_returns_copy` | 深拷贝不影响原始数据 |
| PositionManagerThreadSafety | `_get_trailing_stop_safe_missing_key` | 不存在的key返回None |
| PositionManagerThreadSafety | `concurrent_trailing_stop_reads` | 4线程并发读取不crash |
| PositionManagerThreadSafety | `check_stop_loss_take_profit_trailing_safe` | 追踪止损通过深拷贝触发 |
| PositionManagerThreadSafety | `check_moving_stop_locks_overrides` | 覆盖参数读取加锁 |
| PositionCheckerBacktesterCache | `backtester_cached` | 多次调用返回同一实例 |
| PositionCheckerBacktesterCache | `calc_trade_days_held` | 正常计算交易日天数 |
| PositionCheckerBacktesterCache | `calc_trade_days_held_invalid` | 无效输入返回None |
| PositionCheckerBacktesterCache | `calc_trade_days_held_cached` | 多次调用使用缓存实例 |
| PositionCheckerPropertiesSafety | `trailing_stops_property_documented` | 属性文档说明加锁场景 |
| PositionCheckerPropertiesSafety | `realtime_cache_property_documented` | 属性文档说明直接引用 |
| NoBacktestRegression | `sell_signal_checker_api_unchanged` | 回测API未变 |
| NoBacktestRegression | `strategy_defaults_importable` | 默认参数正常导入 |

---

## 十四、继续优化记录 (v2.6)

### 14.1 _trade_date未初始化Bug修复 (🔴 严重)

**问题**: `_handle_emotion_phase_change` 使用 `self._trade_date` 获取交易日,但该属性从未在 `__init__` 或 `start()` 中设置,导致总是回退到 `datetime.now()`,午夜后调用会产生错误的交易日期。

**修复**: 
1. `__init__` 中初始化 `self._trade_date: str = ""`
2. `start()` 中设置 `self._trade_date = trade_date`

### 14.2 _nav_peak未初始化修复 (🟡 中等)

**问题**: `_save_performance_snapshot` 使用 `getattr(self, "_nav_peak", 1.0)`,虽然安全但不够规范。

**修复**: `__init__` 中显式初始化 `self._nav_peak: float = 1.0`,移除 `getattr` 防御代码。

### 14.3 异动检测提取到StrategyScorer (🟡 架构优化)

**问题**: `_detect_anomalies` (~70行) 仍在scanner.py中,属于策略筛选逻辑,应归入StrategyScorer。

**修复**: 
- 新增 `StrategyScorer.detect_anomalies(realtime_data, active_signals, prev_cache)` 方法
- scanner.py 保留 `async _detect_anomalies` 委托存根(3行)
- 方法签名从async改为sync(纯计算无需IO)

### 14.4 仓位计算提取到PositionManager (🟡 架构优化)

**问题**: `_calc_position_ratio` (~40行) 和 `_calc_would_buy_shares` (~8行) 属于仓位管理逻辑,应归入PositionManager。

**修复**:
- 新增 `PositionManager.calc_position_ratio(signal)` 和 `PositionManager.calc_would_buy_shares(signal)` 方法
- scanner.py 保留委托存根
- signal_manager.py 引用改为 `scanner._position_manager.calc_position_ratio()`
- 修复 `limit_up_count` 字段名兼容: `getattr(signal, 'limit_up_count', None) or getattr(signal, 'limit_times', 0)`

### 14.5 策略配置管理提取到StrategyParamCenter (🟡 架构优化)

**问题**: `update_strategy_config`/`_persist_strategy_overrides`/`_load_strategy_overrides`/`_validate_live_params` (~75行) 属于参数管理逻辑,应归入StrategyParamCenter。

**修复**:
- 新增4个静态方法: `validate_live_params`/`update_scanner_config`/`persist_scanner_overrides`/`load_scanner_overrides`
- scanner.py 保留委托存根(每个3-5行)
- 不影响功能,仅代码归属更合理

### 14.6 Scanner行数变化

| 阶段 | scanner.py行数 | 变化 |
|---|---|---|
| Phase3.1前 | 2907 | 基线 |
| Phase3.1后 | 1922 | -34% |
| v2.6继续优化后 | 1757 | -40% |

### 14.7 回归测试 (22个新增)

新增 `test_extraction_integration.py` 测试文件:

| 测试类 | 测试项 | 验证内容 |
|---|---|---|
| TestAnomalyDetection | `detect_anomalies_broken_board` | 涨停炸板信号检测 |
| TestAnomalyDetection | `detect_anomalies_strong_limit` | 强势涨停信号检测 |
| TestAnomalyDetection | `detect_anomalies_surge` | 急速拉升信号检测 |
| TestAnomalyDetection | `detect_anomalies_skip_existing_signal` | 已有信号不重复生成 |
| TestAnomalyDetection | `detect_anomalies_empty_data` | 空行情无信号 |
| TestPositionSizing | `position_ratio_halfway_chase` | 半路追涨仓位计算 |
| TestPositionSizing | `position_ratio_limit_up_consecutive` | 连板涨停仓位 |
| TestPositionSizing | `position_ratio_limit_down` | 跌停翘板仓位 |
| TestPositionSizing | `position_ratio_reduced_when_half_full` | 半仓以上减仓 |
| TestPositionSizing | `position_ratio_with_emotion` | 情绪低迷降仓 |
| TestPositionSizing | `calc_would_buy_shares` | 买入股数计算 |
| TestPositionSizing | `calc_would_buy_shares_zero_price` | 零价格边界 |
| TestStrategyParamCenterStatic | `update_scanner_config_params` | 参数更新 |
| TestStrategyParamCenterStatic | `update_scanner_config_merge` | 参数合并 |
| TestStrategyParamCenterStatic | `validate_live_params_low_slippage` | 低滑点告警 |
| TestStrategyParamCenterStatic | `validate_live_params_high_position` | 高仓位告警 |
| TestScannerInit | `trade_date_initialized` | _trade_date初始化 |
| TestScannerInit | `nav_peak_initialized` | _nav_peak初始化 |
| TestScannerInit | `state_lock_not_none_after_check` | _state_lock延迟初始化 |
| TestNoBacktestRegression | `sell_signal_checker_api_unchanged` | 回测API不变 |
| TestNoBacktestRegression | `strategy_defaults_importable` | 默认参数正常导入 |
| TestNoBacktestRegression | `portfolio_backtester_importable` | 回测引擎正常导入 |

## 十五、EventBus内部事件总线 (v2.7)

### 15.1 设计目标

Scanner内部组件(QuoteManager/PositionManager/StrategyScorer/FilterPipeline/SignalManager等)之间存在隐式耦合，通过直接调用scanner实例方法通信。引入EventBus实现发布-订阅解耦，便于:
- 组件间松耦合: 模块只依赖事件接口，不依赖scanner实例
- 可观测性: 事件统计+历史记录，便于调试和监控
- 可扩展性: 新功能只需订阅事件，无需修改已有代码

### 15.2 ScannerEventBus 实现

**文件**: `AgentServer/nodes/market_monitor/scanner_event_bus.py` (8679 bytes)

**核心特性**:
- 纯Python异步事件总线，零外部依赖
- 异步handler优先，同步handler自动包装为协程
- 异常隔离: 单个handler失败不影响其他handler和发布者
- 全局单例 `get_event_bus()` + 测试用 `reset_event_bus()`
- 事件统计(emit/handled/errors) + 历史记录(默认100条,可配置)
- enable/disable开关 + clear清理
- once一次性订阅 + on_many/off_many批量操作

**标准事件类型** (`ScannerEvents`类):
| 事件 | 触发场景 |
|---|---|
| `position_changed` | 持仓变更(买入/卖出/风控卖出) |
| `signal_generated` | 新信号生成 |
| `emotion_changed` | 情绪周期变化 |
| `risk_triggered` | 风控触发 |
| `quote_degraded` | 行情降级 |
| `quote_recovered` | 行情恢复 |
| `param_updated` | 策略参数热更新 |
| `scan_completed` | 单次扫描完成 |
| `circuit_breaker` | 熔断触发/解除 |
| `daily_settled` | 日终结算 |
| `risk_sell_executed` | 风控卖出执行 |

### 15.3 Scanner集成

**5个发射点** (最小侵入，不修改现有逻辑):
1. `scan_once` → `SCAN_COMPLETED` (扫描完成)
2. `_execute_risk_sell` → `RISK_SELL_EXECUTED` + `POSITION_CHANGED` (风控卖出)
3. `_apply_filter_pipeline` → `EMOTION_CHANGED` (情绪变化，在调仓前发射)
4. `_check_circuit_breaker` → `CIRCUIT_BREAKER` (熔断触发)
5. `update_strategy_config` → `PARAM_UPDATED` (参数更新，用ensure_future非阻塞)

**只读属性**: `scanner.event_bus` (property)

### 15.4 Bug修复: StrategyScorer NaN防御

**问题**: `merge_factors`中涨停判断使用 `rt.get("pct_chg", 0)` 但None值不触发默认值(`or 0`正确，`dict.get(key, default)`对None无效)。

**修复**: `pct = rt.get("pct_chg") or 0` 替代 `rt.get("pct_chg", 0)`

### 15.5 测试覆盖 (107新增)

| 测试文件 | 测试数 | 覆盖范围 |
|---|---|---|
| `test_event_bus.py` | 33 | 基础API/异常隔离/once/统计/历史/enable/disable/全局单例/Scanner集成 |
| `test_strategy_scorer.py` | 22 | merge_factors/涨跌停判断/属性代理/边界条件(NaN/缺失/5000只) |
| `test_live_filter_pipeline.py` | 52 | L1-L8全层测试/追踪/层开关/策略优先级/全管道apply |

**总测试**: 325 passed (scanner模块207 + 其他118)

### 15.6 scanner.py行数变化

| 阶段 | scanner.py行数 | 变化 |
|---|---|---|
| Phase3.1前 | 2907 | 基线 |
| Phase3.1后 | 1922 | -34% |
| v2.6继续优化后 | 1757 | -40% |
| v2.7 EventBus后 | ~1770 | +13行(EventBus初始化+5个emit) |
| v2.8 EventBus订阅器后 | ~1811 | +41行(订阅器注册+盘后结算emit+行情降级/恢复emit) |

---

## 十六、EventBus订阅器完善 (v2.8)

### 16.1 设计目标

EventBus v2.7只实现了emit(发射)侧, 8个标准事件类型中仅5个有发射点, 且无任何订阅者。
这导致EventBus变为"fire-and-forget"空管道, 解耦和可观测性目标未实现。

v2.8目标:
- 补全缺失的发射点(行情降级/恢复 + 盘后结算)
- 实现8组事件订阅器, 连接事件与实际副作用
- 新增Web API端点暴露EventBus状态
- 不侵入scanner核心逻辑(handler通过EventBus.on注册)

### 16.2 新增发射点

| 事件 | 触发位置 | 数据 |
|---|---|---|
| `quote_degraded` | QuoteManager._fetch_realtime_batch | level, source, error |
| `quote_recovered` | QuoteManager._fetch_realtime_batch | level, degrade_duration_s, source |
| `daily_settled` | Scanner._scan_loop (15:05+结算) | trade_date, total_profit, total_assets |

加上v2.7的5个发射点, 共8个标准事件全部有发射点。

### 16.3 EventBus订阅器 (scanner_event_subscribers.py, 279行)

| 订阅器 | 事件 | 副作用 |
|---|---|---|
| on_risk_sell | risk_sell_executed | MongoDB审计日志 + Redis状态推送 |
| on_position_changed | position_changed | 运行时快照自动保存(force=True) + Redis持仓推送 |
| on_circuit_breaker | circuit_breaker | MongoDB审计日志 + Redis紧急推送 |
| on_scan_completed | scan_completed | 更新_last_scan_ts + Redis状态推送 |
| on_quote_degraded | quote_degraded | Redis状态推送(前端显示降级警告) |
| on_quote_recovered | quote_recovered | Redis状态推送 |
| on_param_updated | param_updated | MongoDB审计日志(合规) |
| on_emotion_changed | emotion_changed | Redis状态推送(前端情绪面板) |
| on_daily_settled | daily_settled | MongoDB审计日志 + Redis状态推送 |

**设计原则**:
- 审计日志: 关键事件(风控卖出/熔断/参数变更/盘后结算)写入MongoDB audit_log集合
- Redis推送: 所有事件转发Redis Pub/Sub, 供Web节点WebSocket广播到前端
- 快照触发: 持仓变更自动保存运行时快照(force=True), 避免崩溃丢状态
- 异常隔离: handler内异常被EventBus捕获, 不影响其他handler和发布者
- 非阻塞: handler内用ensure_future异步化, 不阻塞scanner主循环

### 16.4 Web API端点

| 端点 | 方法 | 功能 |
|---|---|---|
| `/api/v1/scanner/event-bus/stats` | GET | 事件统计(emitted/handled/errors) + 订阅者数量 |
| `/api/v1/scanner/event-bus/history` | GET | 事件历史(支持event过滤+limit) |

### 16.5 注册时机

`register_subscribers(scanner)` 在 `Scanner.start()` 中调用, 在 `_scan_loop` 启动前完成注册。
使用try/except包裹, 注册失败不影响scanner启动。

### 16.6 测试覆盖 (23新增)

| 测试类 | 测试数 | 覆盖范围 |
|---|---|---|
| TestSubscriberRegistration | 2 | 注册完整性+幂等性 |
| TestRiskSellHandler | 2 | 审计日志+Redis推送 |
| TestPositionChangedHandler | 2 | 快照触发+异常不crash |
| TestCircuitBreakerHandler | 2 | 审计日志+Redis推送 |
| TestScanCompletedHandler | 1 | _last_scan_ts更新 |
| TestQuoteDegradeHandler | 2 | 降级+恢复Redis推送 |
| TestParamUpdatedHandler | 1 | 审计日志 |
| TestEmotionChangedHandler | 1 | Redis推送 |
| TestDailySettledHandler | 1 | 审计日志 |
| TestSafeSerialize | 5 | 序列化工具(基础/嵌套/深度/自定义类型) |
| TestNoBacktestRegression | 4 | 回测模块不受影响 |

**总测试**: 330 passed (scanner模块230 + 其他100)

### 16.7 回测影响

零。EventBus订阅器仅在实盘scanner启动时注册, 回测引擎无任何引用。

---

## 十七、v2.9 架构解耦优化

### 17.1 QuoteManager循环依赖消除

**问题**: QuoteManager直接持有`_scanner`引用来发射EventBus事件, 造成Scanner↔QuoteManager循环依赖。

**修复**: 改用回调函数解耦:
- QuoteManager新增 `_event_emitter` 回调属性(默认None)
- Scanner通过 `set_event_emitter(callback)` 注入回调
- 回调签名: `async(event_name: str, data: dict)`
- QuoteManager完全不知道Scanner存在, 只依赖回调接口

```python
# Before (v2.8)
self._quote_manager._scanner = self  # 循环引用!

# After (v2.9)
self._quote_manager.set_event_emitter(self._make_quote_event_emitter())
# callback → scanner._event_bus.emit(event_name, data)
```

### 17.2 盘后结算EventBus解耦

**问题**: `_save_performance_snapshot`和`_push_daily_summary`在`_scan_loop`中直接调用, 与主循环耦合。

**修复**: 移到`daily_settled`事件订阅器:
- scanner._scan_loop只发射`daily_settled`事件
- 订阅器内部调用`scanner._save_performance_snapshot(trade_date)`
- 订阅器内部调用`scanner._push_daily_summary(trade_date)`
- 异常隔离: 绩效快照失败不影响飞书日报

### 17.3 跌停检查去重

**问题**: `_check_stop_loss_only`中scanner和PositionManager都检查跌停, 导致:
- PM已处理跌停挂起, scanner又重复检查
- 跌停恢复后, PM返回的to_sell可能被scanner的跌停检查再拦截

**修复**: scanner不再重复检查跌停:
- PositionManager.check_stop_loss_only已处理: 跌停→挂起pending_sells, 恢复→返回to_sell
- scanner._check_stop_loss_only只执行PM返回的to_sell

### 17.4 运行时快照跨日校验

**问题**: 重启时加载昨天的快照, trailing_stops/pending_sells可能指向已不在的持仓。

**修复**: `load_runtime_snapshot`增加跨日校验:
- 快照包含`trade_date`字段
- 同日快照: 恢复全部状态(trailing_stops/pending_sells/风控/统计)
- 跨日快照: 只恢复跨日持久状态(风控consecutive_losses), 跳过日间状态
- 新增`quote_degrade_level`字段保存/恢复行情降级状态

### 17.5 变更文件

| 文件 | 变更 |
|---|---|
| scanner.py | 回调创建+盘后结算EventBus发射+跌停去重 |
| quote_manager.py | set_event_emitter回调+_event_emitter替代_scanner |
| scanner_event_subscribers.py | daily_settled扩展(绩效快照+飞书日报) |
| runtime_persistence.py | 跨日校验+trade_date/quote_degrade_level字段 |
| test_v29_optimizations.py | 22新增测试 |

### 17.6 测试覆盖

| 测试类 | 用例数 | 覆盖点 |
|---|---|---|
| TestQuoteManagerCallbackInterface | 6 | emitter属性/回调存储/无_scanner引用/源码验证/无回调降级/签名验证 |
| TestDailySettledEventBusDecouple | 4 | 绩效快照触发/飞书日报触发/失败隔离/scan_loop解耦验证 |
| TestLimitDownDedup | 3 | PM跌停处理/PM恢复处理/scanner去重验证 |
| TestRuntimeSnapshotCrossDayValidation | 4 | 同日恢复/跨日跳过/trade_date字段/源码验证 |
| TestNoBacktestRegressionV29 | 5 | 回测模块不受影响 |

**总测试**: 253 passed (scanner模块253)

---

## 18. v2.9.5 稳定性增强 (2026-05-29)

### 18.1 问题

| # | 问题 | 严重度 | 影响 |
|---|---|---|---|
| 1 | 风控线程崩溃后无看门狗, 线程死亡→风控失效 | 🔴高 | 止损/追踪止损全部失效, 可能巨亏 |
| 2 | `_execute_risk_sell`超时5秒后丢弃卖出指令 | 🔴高 | 风控卖出丢失, 持仓风险暴露 |
| 3 | `__getattr__`异步委托未初始化→sync noop | 🟡中 | `await`调用报TypeError |
| 4 | `pending_sells`恢复无`_state_lock` | 🟡中 | 与风控线程竞态 |
| 5 | 健康评分不含风控线程状态 | 🟡中 | 线程已死但前端显示绿 |
| 6 | `_risk_loop_sync`硬编码trade_date | 🟢低 | 与主循环可能不一致 |
| 7 | `scanner_event_subscribers` MongoDB导入不一致 | 🟢低 | 维护性差 |

### 18.2 解决方案

#### 风控线程看门狗

```python
# _scan_loop中每轮检测(交易时段)
if self._risk_running and self._risk_thread and not self._risk_thread.is_alive():
    self._risk_thread_restarts += 1
    self._risk_thread = threading.Thread(target=self._risk_loop_sync, daemon=True)
    self._risk_thread.start()
    if self._risk_thread_restarts >= 3:
        await self._publish_scanner_event("status", {"event": "risk_thread_unstable"})
```

特性:
- 检测到风控线程退出立即重启
- 重启计数器 `_risk_thread_restarts` (init=0, start重置)
- ≥3次重启→推送告警事件
- `_scan_loop`主循环即看门狗(不新增定时器)

#### 卖出超时兜底

```python
# _check_stop_loss_only中
future.result(timeout=5)
# 超时→不丢弃,加入pending_sells待下次执行
except asyncio.TimeoutError:
    with self._state_lock:
        if pos.ts_code not in self._pending_sells:
            self._pending_sells[pos.ts_code] = {
                "reason": reason, "price": price,
                "added_at": time.time(),
                "source": "risk_thread_timeout",
            }
```

- 已有pending_sell(如跌停挂起)不覆盖
- 下次风控循环会重新检查pending_sells

#### __getattr__异步noop

```python
_ASYNC_DELEGATE_METHODS = {
    "_save_timeline", "_load_runtime_snapshot", "_apply_strategies",
    "_update_signals", "_push_signals", "_execute_signals", "_write_audit_log",
    "_check_positions", "_check_positions_quick", "_publish_scanner_event",
    "_save_scan_traces", "_load_timeline", "_save_runtime_snapshot", "_premarket_auction",
}
if name in _ASYNC_DELEGATE_METHODS:
    async def _async_noop(*args, **kwargs): return None
    return _async_noop
else:
    return lambda *args, **kwargs: None
```

#### 健康评分升级

新增维度: `risk_thread_alive` / `risk_thread_restarts`

- `is_healthy`要求风控线程存活
- `is_warning`至少风控线程存活
- 线程停止→红, 3次+重启→warnings告警

### 18.3 变更文件

| 文件 | 变更 |
|---|---|
| scanner.py | 看门狗+超时兜底+__getattr__异步noop+_risk_thread_restarts+trade_date一致性 |
| scanner_utils.py | 健康评分加risk_thread_alive/restarts |
| scanner_event_subscribers.py | MongoDB导入统一为`from core.managers import` |
| runtime_persistence.py | pending_sells恢复加_state_lock |
| test_v295_stability.py | 22新增测试 |
| test_sell_signal_checker.py | 旧健康评分测试适配风控线程维度 |

### 18.4 测试覆盖

| 测试类 | 用例数 | 覆盖点 |
|---|---|---|
| TestRiskThreadWatchdog | 5 | 初始化/重启计数/看门狗源码/死线程重启/3次告警 |
| TestRiskSellTimeoutFallback | 3 | 超时pending_sells/不覆盖已有/源码验证 |
| TestHealthScoreRiskThread | 5 | alive字段/restarts字段/死线程warning/健康判定/源码验证 |
| TestMongoImportConsistency | 2 | runtime_persistence/event_subscribers |
| TestRiskThreadTradeDateConsistency | 2 | _trade_date使用/fallback |
| TestNoBacktestRegressionV295 | 5 | 回测零影响 |

**总测试**: 447 passed (全量)

---

## 十九、v2.9.7 List+ACK升级 (2026-05-30)

### 19.1 设计目标

Phase 2.1完善: scanner:cmd通道从Redis Pub/Sub升级为List+ACK模式, 解决命令丢失问题:

**原问题**: Pub/Sub是fire-and-forget, 子进程重启/网络抖动期间命令会丢失。start/stop/emergency_liquidate等关键命令不可丢失。

**升级方案**:
- 主进程: `RPUSH` 到 `scanner:cmd` List (命令持久化到Redis)
- 子进程: `BLPOP` 从 List 消费 (即使离线, 命令也不丢)
- ACK确认: 子进程收到命令后发布到 `scanner:ack` (Pub/Sub)
- 超时: 主进程等待ACK, 超时返回None

### 19.2 IPC通道升级

| 通道 | v2.9.6 | v2.9.7 | 升级原因 |
|---|---|---|---|
| scanner:cmd | Pub/Sub | **List+ACK** | 命令不可丢 |
| scanner:ack | 无 | **Pub/Sub(新增)** | 命令确认 |
| scanner:signal | Redis Stream | Redis Stream(不变) | 已不可丢 |
| scanner:position | Redis Stream | Redis Stream(不变) | 已不可丢 |
| scanner:status | Pub/Sub | Pub/Sub(不变) | 允许丢 |
| scanner:health | Pub/Sub | Pub/Sub(不变) | 允许丢 |

### 19.3 send_command升级

```python
async def send_command(cmd, params, timeout=None) -> Optional[dict]:
    # 1. 生成cmd_id (uuid[:8])
    # 2. 注册pending_ack Future
    # 3. RPUSH到scanner:cmd List
    # 4. 等待ACK Future (超时默认10秒)
    # 5. 返回ACK结果或None(超时)
```

**返回值变化**: None → Optional[dict]
- `None`: 超时或Redis不可用
- `dict`: ACK结果 `{cmd_id, status, ts}`

### 19.4 ACK状态流转

```
主进程 RPUSH → 子进程 BLPOP → ACK "received" → 执行命令 → ACK "done"
                                    ↑立即确认          ↑执行完成
```

- `received`: 命令已被子进程接收(1秒内)
- `done`: 命令执行完成(stop/start等)
- 超时(默认10秒): 主进程不再等待, 记录warning

### 19.5 Daemon告警增强

**新增**: 告警触发时同步发布到Redis health通道, 前端可实时感知:
```python
alert_data = {
    "event": "daemon_emergency",
    "message": "重启3次失败",
    "restart_count": 3,
    "max_restart_count": 3,
    "ts": time.time(),
}
await redis_client.publish("scanner:health", json.dumps(alert_data))
```

### 19.6 /health API增强

新增 `daemon` 字段, 包含:
- `alive`: 子进程是否存活
- `pid`: 进程PID
- `state`: 当前状态
- `restart_count`: 重启次数
- `max_restart_count`: 最大重启次数
- `pending_acks`: 等待ACK的命令数
- `cmd_ack_timeout`: ACK超时配置

### 19.7 ScannerDaemonConfig新增

| 字段 | 默认值 | 说明 |
|---|---|---|
| `cmd_ack_timeout` | 10.0 | 命令ACK超时(秒) |

### 19.8 变更文件

| 文件 | 变更 |
|---|---|
| scanner_daemon.py | send_command改RPUSH+ACK; 子进程改BLPOP; handle_command加ACK; _ack_listener; _send_emergency_alert加Redis发布; get_status加pending_acks |
| scanner.py (web/api) | /health加daemon字段 |
| test_v297_list_ack.py | 22新增测试 |

### 19.9 测试覆盖

| 测试类 | 用例数 | 覆盖点 |
|---|---|---|
| TestSendCommandUsesList | 3 | RPUSH替代publish/cmd_id/pending_ack注册 |
| TestACKMechanism | 3 | Future resolve/超时None/成功返回 |
| TestSubprocessBLPOP | 2 | 源码验证blpop/cmd_id |
| TestDaemonStatusACK | 2 | get_status含ACK维度/max_restart_count |
| TestEmergencyAlertRedisEvent | 2 | Redis发布/数据格式 |
| TestDaemonConfigACK | 2 | 默认值/自定义值 |
| TestNoBacktestRegressionV297 | 5 | 回测零影响 |
| TestConvenienceMethodsReturnACK | 3 | start/stop/emergency返回ACK |

**总测试**: 493 passed (全量)

### 19.10 回测影响

零。scanner_daemon.py是实盘独立进程, 回测引擎无任何引用。

---

## 二十、v2.9.8 Phase4完善 (2026-05-30)

### 20.1 设计目标

Phase4运维体验完善, 补齐设计文档中定义但未实现的验收项:

1. **/health版本信息**: 部署验证需要知道当前运行的git版本
2. **WS重连间隔**: 设计文档规定3秒, 代码实际5秒
3. **Scanner Store集成验证**: 确保Pinia Store与组件正确集成

### 20.2 /health版本信息 (Phase4.2)

**问题**: 健康检查API不返回版本信息, 无法验证部署是否成功。

**修复**: 新增`_get_version_info()`辅助函数, 在`/health`响应中增加`version`字段:

```python
def _get_version_info() -> dict:
    """【Phase4.2】获取版本信息(部署验证)"""
    return {
        "git_hash": "cc11121",       # git rev-parse --short HEAD
        "git_branch": "feature/...",  # git rev-parse --abbrev-ref HEAD
        "design_doc_version": "v2.9.8",
        "baseline_tag": "v2.8.0-backtest-ui-v2",
    }
```

**位置**: Scanner未运行(dead)和运行时两条路径均返回`version`字段。

### 20.3 WS重连间隔修正 (Phase4.1)

**问题**: `ws.onclose`中`setTimeout(connectWS, 5000)`为5秒, 设计文档Phase4.1验收标准要求3秒重连。

**修复**: 改为`setTimeout(connectWS, 3000)`。

### 20.4 Scanner Store集成验证

确认Pinia Store与组件集成状态:
- ✅ `useScannerStore`已在MarketMonitorView中导入使用
- ✅ WS数据通过`scannerStore.updateFromWs()`分发
- ✅ 数据新鲜度`scannerStore.dataFreshness`在状态栏显示
- ✅ WS连接状态`scannerStore.isWsConnected`已跟踪
- ✅ 健康数据`scannerStore.health`通过fetchHealth写入

### 20.5 变更文件

| 文件 | 变更 |
|---|---|
| AgentServer/nodes/web/api/scanner.py | 新增`_get_version_info()`+/health返回version字段(2处) |
| frontend/src/views/monitor/MarketMonitorView.vue | WS重连5秒→3秒 |
| AgentServer/tests/scanner/test_phase4_health_version.py | 新增13测试 |
| docs/MARKET_MONITOR_OPTIMIZATION_DESIGN.md | 更新至v2.9.8 |

### 20.6 测试覆盖 (13新增)

| 测试类 | 用例数 | 覆盖点 |
|---|---|---|
| TestVersionInfo | 4 | 必要字段/git失败降级/dead状态含version/运行时含version |
| TestWSReconnect | 1 | 重连间隔3秒(源码验证) |
| TestScannerStoreIntegration | 3 | dataFreshness/updateFromWs/组件使用Store |
| TestNoBacktestRegressionPhase4 | 5 | checker API/参数中心/回测引擎/版本函数未侵入回测/Daemon未侵入回测 |

**总测试**: 514 passed (全量)

### 20.7 Phase4验收对照

| 验收项 | 状态 | 说明 |
|---|---|---|
| WS断线3秒重连 | ✅ | setTimeout 3000ms |
| 健康度评分(绿/黄/红) | ✅ | _compute_health_score + /health |
| Daemon 3次失败有告警 | ✅ | v2.9.7 Redis事件发布 |
| 健康API返回版本号 | ✅ | v2.9.8 _get_version_info |
| Pinia Store数据新鲜度 | ✅ | 3s绿/5s黄/>5s红 |
| REST fallback | ✅ | WS断线时REST轮询 |

### 20.8 回测影响

零。版本信息和WS重连均在前端/Web API层, 回测引擎无任何引用。

---

## 二十一、v2.9.10 /health端点优化 (2026-05-30)

### 21.1 问题

| # | 问题 | 严重度 | 影响 |
|---|---|---|---|
| 1 | /health双重健康度计算: API层自算health_score(100扣减)+scanner_health(绿黄红) | 🟡中 | 两套逻辑可能不一致,前端混乱 |
| 2 | _get_version_info()写死v2.9.7,与设计文档v2.9.9不同步 | 🟡中 | 部署验证误判 |
| 3 | /health读取_pending_sells无state_lock | 🔴高 | 与风控线程竞态,可能读到半更新状态 |
| 4 | _get_version_info()每次请求调git子进程 | 🟢低 | 不必要的系统调用开销 |

### 21.2 解决方案

#### 健康度统一

之前: API层独立计算`health_score = 100`后扣减, 同时又调`scanner._compute_health_score()`返回绿黄红。两套逻辑阈值不同, 可能出现`scanner_health.status=green`但`health_score=50`的矛盾。

修复: 以`scanner._compute_health_score()`为权威来源, API层只补充金融指标(日回撤/熔断/跌停挂起):

```python
# 统一健康分数(基于scanner_health绿/黄/红 + 金融扣减)
base_score = {"green": 100, "yellow": 60, "red": 30}.get(scanner_health.get('status', 'red'), 30)
health_score = base_score
if daily_drawdown >= 3:
    health_score -= 15
if daily_drawdown >= 5:
    health_score -= 20
if consecutive_losses >= 2:
    health_score -= 10
if trading_paused:
    health_score -= 25
health_score = max(0, health_score)
```

合并warnings:
```python
merged_warnings = list(scanner_health.get('warnings', []))
if daily_drawdown >= 3:
    merged_warnings.append(f"日回撤{daily_drawdown:.1f}%")
if consecutive_losses >= 2:
    merged_warnings.append(f"连续亏损{consecutive_losses}次")
```

#### 版本常量+缓存

```python
# 模块级常量(与docs/MARKET_MONITOR_OPTIMIZATION_DESIGN.md同步)
_DESIGN_DOC_VERSION = "v2.9.9"
_BASELINE_TAG = "v2.8.0-backtest-ui-v2"

# 版本缓存(5分钟TTL)
_version_cache = {"value": None, "ts": 0}
_VERSION_CACHE_TTL = 300

def _get_version_info() -> dict:
    now = time.time()
    if _version_cache["value"] and (now - _version_cache["ts"]) < _VERSION_CACHE_TTL:
        return _version_cache["value"]
    # ... git子进程调用 ...
    _version_cache["value"] = result
    _version_cache["ts"] = now
    return result
```

#### pending_sells线程安全读取

```python
# 之前: 无锁读取
pending_sells = getattr(scanner, '_pending_sells', {})

# 修复: 加state_lock保护
state_lock = getattr(scanner, '_state_lock', None)
if state_lock:
    with state_lock:
        pending_sells_count = len(scanner._pending_sells)
else:
    pending_sells_count = len(getattr(scanner, '_pending_sells', {}))
```

### 21.3 变更文件

| 文件 | 变更 |
|---|---|
| AgentServer/nodes/web/api/scanner.py | 健康度统一+版本常量+版本缓存+pending_sells加锁 |
| AgentServer/tests/scanner/test_v2910_health_unification.py | 16新增测试 |
| AgentServer/tests/scanner/test_phase4_health_version.py | 版本号断言更新+缓存污染修复 |
| docs/MARKET_MONITOR_OPTIMIZATION_DESIGN.md | v2.9.10记录 |

### 21.4 测试覆盖

| 测试类 | 用例数 | 覆盖点 |
|---|---|---|
| TestVersionConstantSync | 3 | _DESIGN_DOC_VERSION=v2.9.9/无硬编码/_BASELINE_TAG |
| TestVersionCache | 4 | 缓存变量/TTL=300/使用缓存/缓存命中 |
| TestHealthScoreUnification | 3 | 无重复逻辑/scanner_health权威/合并warnings |
| TestPendingSellsThreadSafety | 2 | state_lock保护/不直接getattr |
| TestNoBacktestRegressionV2910 | 3 | 回测不导入API/scanner.py不变/scanner_utils不变 |
| TestDeadStatusVersionInfo | 1 | dead状态含version字段 |
| **总计** | **16** | |

**全量测试**: 530 passed

### 21.5 回测影响

零。只修改web/api/scanner.py和测试文件, 回测引擎无任何引用。

---

## 二十二、v2.9.13 _scan_loop提取 + 线程安全补全 (2026-05-30)

### 22.1 设计目标

1. **_scan_loop方法拆分**: 128行的_scan_loop方法拆分出`_scan_loop_trading`(交易时间逻辑)和`_scan_loop_settlement`(盘后结算逻辑)，主循环行数<100
2. **线程安全补全**: 修复3处共享状态无锁访问，消除与风控线程的竞态条件
3. **死代码清理**: 删除2个.bak文件

### 22.2 _scan_loop时间段提取

**问题**: `_scan_loop`是scanner.py最大方法(128行)，包含5个时间段的完整处理逻辑，阅读和维护困难。

**修复**: 提取2个独立方法:

| 方法 | 职责 | 来源 |
|---|---|---|
| `_scan_loop_trading(trade_date, last_full_scan) -> bool` | 交易时间(9:30-15:00): 风控看门狗+行情恢复+全量扫描/等待 | 原_scan_loop中"交易时间"分支 |
| `_scan_loop_settlement(trade_date)` | 盘后结算(15:05+): Broker结算+EventBus+Timeline | 原_scan_loop中"收盘后"分支 |

**_scan_loop主循环变化**:
- 128行 → ~85行 (减少33%)
- 5个时间段分支保留在主循环中(盘前/深夜/其他较简单，不值得提取)
- `_scan_loop_trading`返回`bool`(True=全量扫描完成, False=等待中)，主循环据此更新`last_full_scan`

### 22.3 线程安全修复

| # | 位置 | 问题 | 修复 |
|---|---|---|---|
| 1 | PositionManager.get_effective_stop_price | 直接`trailing_stops.get()`无锁 | 改用`_get_trailing_stop_safe()`深拷贝读取 |
| 2 | scanner.premarket_prepare | `_circuit_breaker`5个字段赋值无锁 | 加`_state_lock`保护写入 |
| 3 | scanner.premarket_prepare | `_pending_sells.clear()`无锁 | 加`_state_lock`保护写入 |
| 4 | scanner._load_positions | `len(self._trailing_stops)`无锁读取 | 改用`len(self._safe_copy_trailing_stops())` |

**风险评估**:
- #1 🔴高: 风控线程通过`check_stop_loss_take_profit`→`get_effective_stop_price`调用，并发概率高
- #2 🟡中: premarket_prepare在风控线程启动后调用，但写入频率低(每日一次)
- #3 🟡中: 同#2，clear()操作与风控线程的pending_sells写入可能竞态
- #4 🟢低: 仅日志输出，但原则上共享状态读取应统一安全模式

### 22.4 死代码清理

| 文件 | 大小 | 说明 |
|---|---|---|
| scanner.py.bak | 76KB | 旧版scanner备份，已通过git版本控制 |
| position_checker.py.bak | 25KB | 旧版备份，同上 |

### 22.5 变更文件

| 文件 | 变更 |
|---|---|
| scanner.py | _scan_loop拆分+_scan_loop_trading/_scan_loop_settlement提取+circuit_breaker/pending_sells加锁+trailing_stops安全读取 |
| position_manager.py | get_effective_stop_price使用_get_trailing_stop_safe |
| test_v295_stability.py | 看门狗源码测试适配(检查_scan_loop_trading而非_scan_loop) |
| test_v2913_scan_loop_extraction.py | 27新增测试 |
| MARKET_MONITOR_OPTIMIZATION_DESIGN.md | v2.9.13记录 |

### 22.6 测试覆盖 (27新增)

| 测试类 | 用例数 | 覆盖点 |
|---|---|---|
| TestScanLoopTradingExtraction | 5 | 存在性/async/返回bool/签名 |
| TestScanLoopTradingLogic | 2 | 全量扫描返回True/等待返回False |
| TestScanLoopSettlementLogic | 5 | 结算/持久化/事件/timeline/异常安全 |
| TestPositionManagerEffectiveStopPriceThreadSafety | 2 | 使用safe方法/深拷贝验证 |
| TestScannerPremarketLocks | 2 | circuit_breaker加锁/pending_sells加锁 |
| TestTrailingStopsSafeRead | 1 | _load_positions安全读取 |
| TestBakFileCleanup | 2 | .bak文件已删除 |
| TestScanLoopStructure | 3 | 引用提取方法/行数<100 |
| TestNoBacktestRegressionV2913 | 5 | API不变/回测不引用新方法 |

**全量测试**: 433 passed (scanner模块)

### 22.7 scanner.py行数变化

| 阶段 | scanner.py行数 | 变化 |
|---|---|---|
| Phase3.1前 | 2907 | 基线 |
| Phase3.1后 | 1922 | -34% |
| v2.6继续优化后 | 1757 | -40% |
| v2.9.13后 | 1779 | +22行(2个提取方法+锁保护) |

### 22.8 回测影响

零。仅修改scanner.py/position_manager.py内部逻辑和测试文件，回测引擎无任何引用。18项回测契约测试全通过。

---

## 二十三、v2.9.14 Redis Stream升级 + 审计TTL + 断线补发 (2026-05-30)

### 23.1 设计目标

Phase2.1完善: 将scanner:position通道从Pub/Sub升级为Redis Stream, 实现信号/持仓消息零丢失;
补齐审计日志TTL索引(Phase3.4); 新增WS断线重连Stream补发能力。

### 23.2 Redis Stream升级

**问题**: `_push_to_redis`对所有通道使用`publish()`(Pub/Sub, fire-and-forget), 
但设计文档Phase2.1明确规定scanner:signal和scanner:position应使用Redis Stream(不可丢)。
signal_dispatcher.py已单独用xadd, 但EventBus订阅器的position/signal推送仍走Pub/Sub。

**修复**: `_push_to_redis`新增`use_stream`和`maxlen`参数:

```python
async def _push_to_redis(scanner, channel, data, use_stream=False, maxlen=1000):
    if use_stream:
        await redis_manager._client.xadd(channel, payload, maxlen=maxlen, approximate=True)
    else:
        await redis_manager._client.publish(channel, json.dumps(payload))
```

通道模式对照:

| 通道 | 模式 | maxlen | 原因 |
|---|---|---|---|
| scanner:signal | Redis Stream | 1000 | 不可丢(signal_dispatcher.xadd + EventBus订阅器.xadd) |
| scanner:position | Redis Stream | 5000 | 不可丢(持仓变更关键数据) |
| scanner:status | Pub/Sub | N/A | 允许丢(状态更新频繁) |
| scanner:health | Pub/Sub | N/A | 允许丢(健康检查轮询) |

### 23.3 Stream消费兼容修复

**问题**: `redis_ws_bridge.py`的`_redis_stream_consumer`仅处理`fields.get("data")`格式(JSON字符串),
但`signal_dispatcher`和`_push_to_redis`的xadd使用扁平字段字典, 不包含`data`键, 导致Stream消息被静默丢弃。

**修复**: Stream消费者兼容两种格式:
1. 旧格式: `fields = {"data": "{...}"}` → `json.loads(fields["data"])`
2. 新格式: `fields = {"ts_code": "...", "action": "..."}` → 直接使用fields

### 23.4 审计日志TTL索引 (Phase3.4)

**问题**: `audit_log`集合无TTL索引, 数据无限增长。

**修复**: `_write_audit_log`首次写入时创建TTL索引:
```python
await mongo_manager.db["audit_log"].create_index(
    "timestamp", name="ttl_90d", expireAfterSeconds=90 * 86400
)
```
幂等操作(已存在不报错), 90天后自动清理。

### 23.5 WS断线补发 (catchup_scanner_stream)

**问题**: WS断线重连后, 断线期间的Stream消息只被消费组ACK了但未推送到前端。

**修复**: 新增`catchup_scanner_stream(stream, last_id, websocket)`方法:
- 使用`XRANGE (last_id + count=100`从上次位置读取未消费消息
- 前端重连时传`last_stream_id`(从实时消息的`_stream_id`字段获取)
- 最多补发100条(防止大量积压阻塞WS)

### 23.6 Stream消费API端点

| 端点 | 方法 | 功能 |
|---|---|---|
| `/api/v1/scanner/stream/signals` | GET | 从Redis Stream读取最近信号(支持count参数) |
| `/api/v1/scanner/stream/positions` | GET | 从Redis Stream读取最近持仓变更(支持count参数) |

返回格式: `{success, count, data: [{id, data}]}`, id为Stream entry ID(用于断线回补)。

### 23.7 变更文件

| 文件 | 变更 |
|---|---|
| scanner_event_subscribers.py | _push_to_redis新增use_stream/maxlen参数; position用Stream(maxlen=5000); signal用Stream(maxlen=1000); audit_log TTL索引 |
| redis_ws_bridge.py | Stream消费兼容扁平字段; 新增catchup_scanner_stream方法 |
| web/api/scanner.py | 新增/stream/signals和/stream/positions端点; 版本→v2.9.14 |
| test_v2910_health_unification.py | 修复路径(使用os.path而非硬编码) |
| test_v2911_thread_safety.py | 修复路径(使用os.path而非硬编码) |
| test_v2914_redis_stream.py | 20新增测试 |
| test_v2914b_stream_compat.py | 19新增测试 |
| test_phase4_health_version.py | 版本号断言更新v2.9.13→v2.9.14 |
| MARKET_MONITOR_OPTIMIZATION_DESIGN.md | v2.9.14记录 |

### 23.8 测试覆盖

| 测试文件 | 用例数 | 覆盖点 |
|---|---|---|
| test_v2914_redis_stream.py | 20 | Stream模式/Pub/Sub模式/position maxlen/signal maxlen/版本同步/回测零影响 |
| test_v2914b_stream_compat.py | 19 | 扁平字段兼容/JSON兼容/bytes解码/TTL索引/TTL 90天/幂等/catchup方法/xrange/开区间/返回count/_stream_id/limit 100 |

**全量测试**: 472 passed (0 failed)

### 23.9 回测影响

零。只修改scanner_event_subscribers.py(redis_ws_bridge.py/web/api/scanner.py和测试文件, 回测引擎无任何引用。

---

## 二十四、v2.9.15 错误遥测 + 参数预检 + 事件扩展 (2026-05-30)

### 24.1 设计目标

完善运行时可观测性: 扫描器异常实时感知(EventBus→Redis→前端弹窗);
新增参数预检API(前端提交前验证,减少误操作); 扩展事件枚举。

### 24.2 SCANNER_ERROR事件

**问题**: 扫描器主循环或风控线程异常时, 仅日志记录, 前端无感知。
运维人员需主动查看日志才能发现, 延迟响应时间。

**修复**: 新增`ScannerEvents.SCANNER_ERROR`事件, 从两个关键错误路径发射:

1. `_scan_loop`主循环except块 → `emit(SCANNER_ERROR, {error, error_type})`
2. `_risk_thread`风控线程except块 → `emit(SCANNER_ERROR, {error, error_type})`

事件订阅器`_make_scanner_error_handler`:
- 推送`scanner:status`到Redis(Pub/Sub, 含`event: "scanner_error"`标记)
- 写入审计日志`_write_audit_log(scanner, "scanner_error", {...})`

前端WS接收: `scanner_status`消息中`event === "scanner_error"`时弹出ElMessage错误提示(8秒)。

### 24.3 HEALTH_CHANGED事件枚举

**问题**: 健康度变化时无EventBus事件, 未来难以触发告警。

**修复**: 预留`ScannerEvents.HEALTH_CHANGED`枚举值。
当前健康度通过`/health` API和daemon的health_pusher提供, 
后续可从compute_health_score内部发射。

### 24.4 参数预检API

**问题**: 前端直接提交参数更新, 无前置验证。极端参数(如止损0.1%或仓位100%)可导致实盘风险。

**修复**: 新增`POST /api/v1/scanner/params/validate`端点:

```json
// 请求
{ "strategy_id": "半路追涨", "params": { "stop_loss_pct": 0.001, "max_position_ratio": 0.9 } }

// 响应
{ "success": true, "warnings": ["止损0.1%过紧, 实盘建议≥2%", "单票仓位90%过高, 实盘建议≤15%"], "is_safe": false }
```

验证项:
1. 止损: >10%过宽, <2%过紧
2. 止盈: <3%过低
3. 单票仓位: >80%过高
4. 追踪止损步长: <1%过紧
5. 情绪调仓比例: >50%过高

前端工作流: 先调用validate → warnings为空则直接提交 → 非空则弹出确认对话框。

### 24.5 Stream消息含_stream_id

v2.9.14已实现WS断线补发(catchup_scanner_stream), 但实时消息不含Stream entry ID,
前端无法记录last_id用于断线回补。

**修复**: 
- `_handle_scanner_signal_message`/`_handle_scanner_position_message`新增`stream_id`参数
- Stream消费时传入`msg_id`, WS广播消息包含`_stream_id`字段
- 前端记录`lastSignalStreamId`/`lastPositionStreamId`

### 24.6 变更文件

| 文件 | 变更 |
|---|---|
| scanner_event_bus.py | 新增SCANNER_ERROR/HEALTH_CHANGED事件枚举 |
| scanner_event_subscribers.py | 新增scanner_error订阅器(handler+审计日志); 注册10组 |
| scanner.py | scan_loop/risk_thread异常时发射SCANNER_ERROR事件 |
| web/api/scanner.py | 新增/params/validate端点; 版本→v2.9.15 |
| redis_ws_bridge.py | signal/position handler含stream_id参数; WS广播含_stream_id |
| MarketMonitorView.vue | 前端记录lastSignalStreamId; scanner_error弹窗 |
| test_v2915_error_telemetry.py | 16新增测试 |
| test_phase4_health_version.py | 版本断言v2.9.14→v2.9.15 |
| MARKET_MONITOR_OPTIMIZATION_DESIGN.md | v2.9.15记录 |

### 24.7 测试覆盖

| 测试文件 | 用例数 | 覆盖点 |
|---|---|---|
| test_v2915_error_telemetry.py | 16 | SCANNER_ERROR枚举/发射/订阅/Redis推送/审计日志/参数预检5项/回测零影响 |

**全量测试**: 488 passed (0 failed)

### 24.8 回测影响

零。SCANNER_ERROR事件和参数预检API仅影响scanner/前端/WS桥接, 回测引擎无引用。

## 二十五、v2.9.16 RiskWatchdog线程安全 + 情绪卖出提取 + 配置方法简化 (2026-05-30)

### 25.1 问题背景

1. **🔴 risk_watchdog.py `pause_reason`元组bug**: L633 `pause_reason = f"..."`行尾有逗号,Python将其解释为tuple而非str
2. **🔴 circuit_breaker线程安全**: 风控线程写`_circuit_breaker`, Scanner主循环读, 无锁保护→并发读写风险
3. **🟡 `_build_emotion_sell_list`耦合**: 30行逻辑硬编码在scanner.py中,依赖`_is_limit_down`/`_pending_sells`/`_state_lock`/`_get_strategy_risk`
4. **🟡 strategy配置方法异常处理粗糙**: `except ImportError`过于窄,其他异常(如AttributeError)会泄漏
5. **🟡 emergency_liquidate线程安全审查**: 需确认紧急平仓操作的并发安全性

### 25.2 修复方案

| # | 修复项 | 方案 | 文件 |
|---|---|---|---|
| 1 | pause_reason元组bug | 删除尾随逗号 | risk_watchdog.py L633 |
| 2 | circuit_breaker线程安全 | check/record/reset均持`_state_lock`读写 | risk_watchdog.py |
| 3 | _build_emotion_sell_list提取 | 静态方法`EmotionCycleManager.build_emotion_sell_list(回调解耦)` | emotion_cycle.py + scanner.py |
| 4 | strategy配置简化 | `except Exception` + 直接调用StrategyParamCenter | scanner.py |
| 5 | emergency_liquidate审查 | asyncio协程安全,添加线程安全文档注释 | risk_watchdog.py |

### 25.3 EmotionCycleManager.build_emotion_sell_list签名

```python
@staticmethod
def build_emotion_sell_list(
    positions, rule: Dict, old_phase: str, new_phase: str,
    is_limit_down_fn=None,  # Callable[[str], bool]
    pending_sells=None,      # Dict[str, dict]
    state_lock=None,         # threading.Lock
    strategy_risk_fn=None,   # Callable[[str], dict]
) -> List[Tuple]:
```

回调解耦: scanner内部依赖通过函数参数注入,EmotionCycleManager不持有scanner引用。

### 25.4 scanner委托调用

```python
def _build_emotion_sell_list(self, positions, rule, old_phase, new_phase):
    return EmotionCycleManager.build_emotion_sell_list(
        positions=positions, rule=rule, old_phase=old_phase, new_phase=new_phase,
        is_limit_down_fn=self._is_limit_down,
        pending_sells=self._pending_sells,
        state_lock=self._state_lock,
        strategy_risk_fn=self._get_strategy_risk,
    )
```

### 25.5 测试覆盖

| 测试文件 | 用例数 | 覆盖点 |
|---|---|---|
| test_v2916_risk_watchdog_thread_safety.py | 23 | pause_reason类型检查/circuit_breaker线程安全(源码+并发)/build_emotion_sell_list(5场景)/strategy配置简化/emergency_liquidate审查/版本同步/回测零影响 |

**全量测试**: 644 passed (0 failed)

### 25.6 回测影响

零。所有变更仅影响market_monitor模块,回测引擎零文件修改。

## 二十六、v2.9.17 DelegateRouter提取 + _with_state_lock统一 + 参数审计增强 (2026-05-30)

### 26.1 设计目标

1. **__getattr__方法提取**: 95行→8行(-91%), 消除scanner.py中最大的单一方法
2. **_with_state_lock统一加锁**: 消除RiskWatchdog和scanner中5处`if state_lock: with state_lock: else:`重复模式
3. **参数审计增强**: PARAM_UPDATED事件新增old_values字段,审计日志可追溯变更前后值

### 26.2 DelegateRouter提取

**问题**: `scanner.py.__getattr__` 95行, 包含6种委托策略的特殊处理逻辑(QuoteManager/RiskWatchdog/ScannerUtils/StrategyScorer/AsyncNoop/Simple), 每种有独立的导入、绑定、fallback逻辑。方法过长且与scanner类耦合。

**修复**: 提取为独立的`scanner_delegate_router.py`模块(136行):

```python
# __getattr__ 从95行简化为8行:
def __getattr__(self, name):
    delegate = self._DELEGATE_MAP.get(name)
    if delegate is None:
        raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")
    from nodes.market_monitor.scanner_delegate_router import resolve_delegate
    return resolve_delegate(self, name, delegate)
```

**6种路由策略**:

| 策略 | 模块属性 | 特殊处理 |
|---|---|---|
| QuoteManager类方法 | `_quote_manager_class` | 直接getattr类方法 |
| RiskWatchdog静态方法 | `_risk_watchdog_class` | 绑定scanner实例参数 |
| ScannerUtils(部分上下文绑定) | `_scanner_utils` | position_to_dict/signal_to_dict等4方法需要scanner上下文 |
| StrategyScorer(含fallback) | `_strategy_scorer` | 未初始化时4个fallback返回值 + _detect_anomalies异步绑定 |
| Async noop fallback | 无/未初始化 | `_ASYNC_DELEGATE_METHODS`中的方法返回coroutine noop |
| Simple转发 | 其他 | 直接getattr模块实例 |

**数据驱动**: 4个配置字典替代if/elif链:
- `_ASYNC_DELEGATE_METHODS`: frozenset(不可变), 17个async方法名
- `_SCORER_FALLBACKS`: 4个StrategyScorer未初始化时的fallback返回值
- `_UTILS_CONTEXT_METHODS`: 4个ScannerUtils方法的上下文绑定闭包
- `_WATCHDOG_BINDINGS`: 3个RiskWatchdog静态方法的参数绑定

### 26.3 _with_state_lock统一加锁辅助

**问题**: RiskWatchdog的3个静态方法和scanner的2处代码中, `if state_lock: with state_lock: fn() else: fn()` 模式重复5次, 每处6-12行冗余代码。

**修复**: 新增`RiskWatchdog._with_state_lock(scanner, fn, *, fallback=None)`静态方法:

```python
@staticmethod
def _with_state_lock(scanner, fn, *, fallback=None):
    """线程安全执行circuit_breaker读写操作"""
    state_lock = getattr(scanner, '_state_lock', None)
    if state_lock:
        with state_lock:
            return fn()
    return (fallback or fn)()
```

**消除的重复代码**:

| 位置 | 修复前行数 | 修复后行数 |
|---|---|---|
| `check_circuit_breaker` 读circuit_breaker | 12行 | 9行 |
| `check_circuit_breaker` 写circuit_breaker | 6行 | 5行 |
| `record_trade_result` | 16行 | 9行 |
| `reset_circuit_breaker` | 12行 | 7行 |
| `premarket_prepare` circuit_breaker重置 | 12行 | 5行 |
| `premarket_prepare` pending_sells清除 | 5行 | 3行 |
| `stop()` pending_sells保存 | 5行 | 4行 |

### 26.4 参数审计增强

**问题**: `update_strategy_config`的PARAM_UPDATED事件只包含新值, 无法追溯变更前后的差异。

**修复**: 在更新前读取旧值, 传入EventBus事件:

```python
old_values = {}
try:
    strategy_config = self.config.get("strategies", {}).get(strategy_key, {})
    for k in updates:
        if k in strategy_config:
            old_values[k] = strategy_config[k]
except Exception:
    pass

# EventBus事件新增old_values字段
await self._event_bus.emit(ScannerEvents.PARAM_UPDATED, {
    "strategy_key": strategy_key, "updates": updates,
    "old_values": old_values,  # 审计增强
})
```

审计日志示例:
```json
{
    "event": "param_updated",
    "strategy_key": "半路追涨",
    "updates": {"stop_loss_pct": 0.05},
    "old_values": {"stop_loss_pct": 0.04}
}
```

### 26.5 变更文件

| 文件 | 变更 |
|---|---|
| scanner_delegate_router.py | 新增136行(DelegateRouter模块) |
| scanner.py | __getattr__ 95→8行 + _with_state_lock替代2处if/lock + 参数审计增强 |
| risk_watchdog.py | _with_state_lock新增 + 3个方法使用helper + _set_cb_paused辅助 |
| test_v2917_delegate_router.py | 新增35测试 |
| test_v2913_scan_loop_extraction.py | 2处测试适配_with_state_lock |

### 26.6 scanner.py行数变化

| 阶段 | scanner.py行数 | 变化 |
|---|---|---|
| Phase3.1前 | 2907 | 基线 |
| Phase3.1后 | 1922 | -34% |
| v2.6继续优化后 | 1757 | -40% |
| v2.9.13后 | 1779 | +22行 |
| v2.9.16后 | 1766 | -13行 |
| **v2.9.17后** | **1672** | **-94行(-5.3%)** |

### 26.7 测试覆盖

| 测试文件 | 用例数 | 覆盖点 |
|---|---|---|
| test_v2917_delegate_router.py | 35 | 6种路由策略/async noop/sync noop/AttributeError/_with_state_lock(6项)/源码验证(4项)/回测零影响(5项) |

**全量测试**: 682 passed (0 failed)

### 26.8 回测影响

零。DelegateRouter和_with_state_lock仅影响market_monitor模块, 回测引擎零文件修改。51个回测测试全通过。

## 二十七、v2.9.18 stop()拆分 + QuoteManager封装 + pending_sells安全拷贝 (2026-05-30)

### 27.1 设计目标

1. **stop()方法拆分**: 110行→3个方法(stop 30行+_sell_all_positions 35行+_persist_stop_state 30行)
2. **QuoteManager封装**: 消除scanner.py直接访问_quote_manager私有属性(5处→0处)
3. **pending_sells安全拷贝**: _build_emotion_sell_list传深拷贝+lock=None,防止回调修改内部状态
4. **_check_force_empty返回stats**: 修复L1描述NameError(limit_up_count未定义)

### 27.2 stop()方法拆分

**问题**: `stop()` 110行,包含清仓逻辑(~40行)、状态保存(~30行)、资源清理(~20行),职责混杂。

**修复**: 提取2个独立方法:

| 方法 | 职责 | 来源 |
|---|---|---|
| `_sell_all_positions()` | 清仓所有持仓(遍历+place_order+timeline) | stop()中清仓分支 |
| `_persist_stop_state()` | 持久化状态(broker保存+快照+timeline+pending_sells) | stop()中保存分支 |

**stop()主方法**: 30行,仅编排3个步骤(停止线程→清仓→保存)。

### 27.3 QuoteManager属性封装

**问题**: scanner.py通过`_quote_manager._cache_lock`/`_realtime_cache`/`_prev_realtime_cache`/`_data_router`/`_quote_degrade_level`直接访问QuoteManager私有属性,破坏封装。

**修复**: QuoteManager新增5个属性(只读):

| 属性 | 类型 | 说明 |
|---|---|---|
| `cache_lock_initialized` | bool | 缓存锁是否已设置 |
| `realtime_cache` | Dict | 实时行情缓存(直接引用) |
| `prev_realtime_cache` | Dict | 上一帧行情缓存 |
| `data_router` | DataSourceRouter | 数据源路由器 |
| `quote_degrade_level` | int | 行情降级等级 |

新增`warm_sources_cache(realtime)`方法,封装缓存预热写入(替代scanner直接遍历`_data_router._sources`)。

### 27.4 _build_emotion_sell_list安全性

**问题**: `_build_emotion_sell_list`直接传入`self._pending_sells`可变引用+`self._state_lock`,EmotionCycleManager静态方法可意外修改scanner内部状态。

**修复**: 传深拷贝+lock=None:
```python
pending_copy = self._safe_copy_pending_sells()
EmotionCycleManager.build_emotion_sell_list(
    ..., pending_sells=pending_copy, state_lock=None, ...
)
```

新增`_safe_copy_pending_sells()`方法(与`_safe_copy_trailing_stops`/`_safe_copy_position_risk_levels`一致模式)。

### 27.5 _check_force_empty返回stats

**问题**: `_check_force_empty`返回`(bool, str)`,但L1描述行引用`limit_up_count`/`limit_down_count`/`index_drop_pct`未定义变量→NameError。

**修复**: 返回3元组`(bool, str, dict)`:
```python
stats = {"limit_up_count": N, "limit_down_count": N, "index_drop_pct": N}
return True, f"跌停{N}只≥80", stats
```

L1描述行从stats字典取值,不再依赖未定义变量。

### 27.6 变更文件

| 文件 | 变更 |
|---|---|
| scanner.py | stop()拆分+_safe_copy_pending_sells+_build_emotion_sell_list深拷贝+QuoteManager属性替代私有访问 |
| quote_manager.py | 5个只读属性+warm_sources_cache方法 |
| live_filter_pipeline.py | _check_force_empty返回3元组+L1描述从stats取值 |
| test_v2918_review_optimization.py | 23新增测试 |
| test_live_filter_pipeline.py | 适配3元组返回值 |
| test_phase4_health_version.py | 前端store断言更新 |
| MARKET_MONITOR_OPTIMIZATION_DESIGN.md | v2.9.18记录 |

### 27.7 测试覆盖

| 测试文件 | 用例数 | 覆盖点 |
|---|---|---|
| test_v2918_review_optimization.py | 23 | stop拆分(4)+QuoteManager封装(6)+warm_sources_cache(3)+pending_sells安全(4)+情绪卖出安全(1)+回测零影响(5) |

**全量测试**: 569 passed (0 failed)

### 27.8 scanner.py行数变化

| 阶段 | scanner.py行数 | 变化 |
|---|---|---|
| Phase3.1前 | 2907 | 基线 |
| v2.9.17后 | 1672 | -42% |
| **v2.9.18后** | **1822** | +150行(stop拆分+新增方法+pending_sells安全+QuoteManager属性访问, 但方法数增加2个,整体结构更清晰) |

### 27.9 回测影响

零。所有变更仅影响market_monitor模块, 回测引擎零文件修改。回测测试全通过。

### 27.10 start()方法拆分(补充)

**问题**: `start()` 103行,包含参数校验、漂移检测、盘前准备、状态恢复、EventBus注册、线程启动等多个职责。

**修复**: 提取3个独立方法:

| 方法 | 职责 | 类型 |
|---|---|---|
| `_detect_param_drift()` | 参数漂移检测+告警 | async |
| `_restore_start_state()` | 审计TTL索引+pending_sells恢复 | async |
| `_start_risk_thread()` | 启动风控独立线程 | sync |

**start()主方法**: 51行,仅编排8个步骤。

### 27.11 PositionChecker公开接口(补充)

**问题**: scanner.py通过`_position_checker._is_limit_down()`和`_position_checker._execute_sell_list()`直接调用PositionChecker私有方法。

**修复**: PositionChecker新增2个公开代理方法:

| 方法 | 委托到 | 说明 |
|---|---|---|
| `is_limit_down(ts_code)` | `_is_limit_down` | 跌停判断 |
| `execute_sell_list(to_sell, trade_date, source)` | `_execute_sell_list` | 卖出列表执行 |

scanner.py改用公开接口调用。

### 27.12 最终统计

| 指标 | v2.9.17 | v2.9.18 | 变化 |
|---|---|---|---|
| scanner.py行数 | 1672 | 1823 | +151(新增方法+测试) |
| scanner.py方法数 | 48 | 53 | +5(拆分+新增) |
| >50行方法数 | 14 | 13 | -1(start 103→51) |
| QuoteManager私有访问 | 5处 | 0处 | 全部消除 |
| PositionChecker私有访问 | 2处 | 0处 | 全部消除 |
| 测试用例数 | 546 | 579 | +33(新测试) |
| 回测影响 | 零 | 零 | 无变化 |

## 二十八、v2.9.19 _execute_risk_sell拆分 + scan_once提取 + _scan_loop回放提取 + get_status简化 (2026-05-30)

### 28.1 设计目标

1. **_execute_risk_sell拆分**: 82行→40行, 提取_post_sell_cleanup(timeline+统计+状态清理+事件+持久化)
2. **scan_once提取**: 80行→50行, 提取_sync_broker_prices + _update_scan_stats + _persist_scan_result
3. **_scan_loop回放模式提取**: 提取_scan_loop_replay, 主循环更清晰
4. **get_status简化**: 提取_build_account_info, 减少条件分支

### 28.2 _execute_risk_sell拆分

**问题**: `_execute_risk_sell` 82行, 包含下单+timeline+统计+状态清理+事件+持久化, 职责混杂。卖出后清理逻辑(timeline/统计/状态/事件/持久化)在多个卖出路径中重复。

**修复**: 提取`_post_sell_cleanup`方法:

```python
async def _execute_risk_sell(self, pos, reason, price, quantity):
    # 1. 下单(职责1)
    ok, msg, order = self._broker.place_order(...)
    # 2. 成功后委托清理
    if ok:
        await self._post_sell_cleanup(pos, reason, order, quantity, profit_pct, profit_amount, source="risk_sell")

async def _post_sell_cleanup(self, pos, reason, order, quantity, profit_pct, profit_amount, *, source="sell"):
    # timeline + 统计 + 状态清理(加锁) + 事件 + 持久化
```

**好处**: 
- `_post_sell_cleanup`可被其他卖出路径(如强制空仓)复用
- 职责清晰: 下单vs善后分离
- `source`参数标记卖出来源(risk_sell/force_empty等)

### 28.3 scan_once提取

**问题**: `scan_once` 80行, Step6(行情同步)和持久化逻辑混在核心扫描流程中。

**修复**: 提取3个方法:

| 方法 | 职责 | 类型 |
|---|---|---|
| `_sync_broker_prices(realtime_data)` | 更新broker实时价格(ST判断+价格同步) | sync |
| `_update_scan_stats(scan_time, stocks_count, elapsed)` | 更新扫描统计+看门狗心跳 | sync |
| `_persist_scan_result()` | save_state+timeline+运行时快照 | async |

### 28.4 _scan_loop回放模式提取

**问题**: `_scan_loop`中回放模式5行逻辑嵌入主方法, 影响阅读主循环流程。

**修复**: 提取`_scan_loop_replay`方法, 主循环仅保留一行`await self._scan_loop_replay(); return`。

### 28.5 get_status简化

**问题**: `get_status` 51行, 含掘金/模拟broker两种账户构建逻辑(15行), 混在状态字典构建中。

**修复**: 提取`_build_account_info`方法, `get_status`仅构建字典引用。

### 28.6 变更文件

| 文件 | 变更 |
|---|---|
| scanner.py | 4个方法提取 + _execute_risk_sell委托_post_sell_cleanup |
| scanner.py (web/api) | _DESIGN_DOC_VERSION→v2.9.19 |
| test_v2919_review_optimization.py | 36新增测试 |
| test_position_checker_integration.py | 锁测试适配_post_sell_cleanup |
| test_v296_compare_consistency.py | circuit_breaker测试适配 |
| test_v29_optimizations.py | EventBus事件测试适配 |
| test_v2918_review_optimization.py | 行数断言更新(1825→1835) |
| MARKET_MONITOR_OPTIMIZATION_DESIGN.md | v2.9.19记录 |

### 28.7 测试覆盖

| 测试文件 | 用例数 | 覆盖点 |
|---|---|---|
| test_v2919_review_optimization.py | 36 | _execute_risk_sell拆分(9)+scan_once提取(10)+_scan_loop回放(4)+get_status简化(5)+方法行数回归(3)+回测零影响(5) |

**全量测试**: 615 passed (0 failed)

### 28.8 scanner.py行数变化

| 阶段 | scanner.py行数 | 变化 |
|---|---|---|
| Phase3.1前 | 2907 | 基线 |
| v2.9.17后 | 1672 | -42% |
| v2.9.18后 | 1823 | +151(拆分+封装) |
| **v2.9.19后** | **1831** | **+8(4个提取方法签名,但3个大方法大幅简化)** |

### 28.9 方法行数改善

| 方法 | v2.9.18 | v2.9.19 | 变化 |
|---|---|---|---|
| _execute_risk_sell | 82行 | 40行 | -51% |
| scan_once | 80行 | 50行 | -38% |
| get_status | 51行 | 30行 | -41% |
| _scan_loop | 88行 | 84行 | -5% |
| **新增** | | | |
| _post_sell_cleanup | - | 50行 | 卖出善后统一 |
| _sync_broker_prices | - | 10行 | 行情同步 |
| _update_scan_stats | - | 8行 | 统计更新 |
| _persist_scan_result | - | 9行 | 持久化 |
| _scan_loop_replay | - | 6行 | 回放循环 |
| _build_account_info | - | 15行 | 账户信息 |

### 28.10 回测影响

零。所有变更仅影响market_monitor模块, 回测引擎零文件修改。

## 二十九、v2.9.20 _liquidate_positions提取 + T+1合规修复 (2026-05-31)

### 29.1 设计目标

1. **🔴 T+1合规Bug修复**: `_execute_force_empty`使用`pos.total_qty`忽略T+1限制,会尝试卖出当日买入的锁定股份
2. **🟡 代码冗余消除**: `_sell_all_positions`和`_execute_force_empty`逻辑几乎相同(遍历持仓→place_order→_post_sell_cleanup),应提取公共方法
3. **🟡 多余检查移除**: `_execute_force_empty`中`hasattr(p, 'stock_name')`检查多余(Position数据类必有stock_name)

### 29.2 T+1合规Bug

**问题**: `_execute_force_empty`使用`pos.total_qty`(总持仓量), 但A股T+1规则规定当日买入的股票不可卖出。

对比:
| 方法 | 下单数量 | T+1合规 |
|---|---|---|
| `_execute_risk_sell` | `pos.available_qty` | ✅ 合规 |
| `_sell_all_positions` | `pos.available_qty` | ✅ 合规 |
| `_execute_force_empty` | `pos.total_qty` | 🔴 **不合规** |

**影响**: 强制空仓时,当日买入的股票会被尝试卖出,但Broker层会拒绝(或产生错误)。

**修复**: 统一使用`pos.available_qty`。

### 29.3 _liquidate_positions公共方法提取

**问题**: 两个清仓方法逻辑几乎相同(30+行重复代码), 仅source和reason不同。

**修复**: 提取`_liquidate_positions(reason, source)`公共方法:

```python
async def _liquidate_positions(self, reason: str, source: str) -> Tuple[int, int]:
    """批量清仓: 卖出所有可用持仓(v2.9.20提取)"""
    if not self._broker:
        return 0, 0
    positions = self._broker.get_positions()
    sold, failed = 0, 0
    for p in positions:
        if p.available_qty <= 0:
            continue  # T+1: 不可卖跳过
        try:
            # place_order + _post_sell_cleanup
        except Exception:
            failed += 1
    return sold, failed
```

两个调用方简化为3行:
```python
async def _sell_all_positions(self):
    """停止时清仓"""
    await self._liquidate_positions(reason="停止清仓", source="stop_sell")

async def _execute_force_empty(self, reason: str):
    """强制空仓"""
    await self._liquidate_positions(reason=f"强制空仓: {reason}", source="force_empty")
```

### 29.4 变更文件

| 文件 | 变更 |
|---|---|
| scanner.py | 新增`_liquidate_positions`; `_sell_all_positions`/`_execute_force_empty`简化为委托; 移除`hasattr(stock_name)` |
| web/api/scanner.py | `_DESIGN_DOC_VERSION`→v2.9.20 |
| test_v2920_liquidate_positions.py | 22新增测试 |
| test_v2919_review_optimization.py | 委托链测试适配(_post_sell_cleanup→_liquidate_positions) |
| test_v2916_risk_watchdog_thread_safety.py | 版本断言更新 |

### 29.5 测试覆盖 (22新增)

| 测试类 | 用例数 | 覆盖点 |
|---|---|---|
| TestLiquidatePositionsExtraction | 5 | 存在性/委托/无重复循环 |
| TestT1ComplianceFix | 3 | available_qty/无total_qty/无hasattr |
| TestLiquidatePositionsBehavior | 5 | T+1合规/零可用跳过/单票失败不中断/返回值/无broker |
| TestLiquidatePositionsConsistency | 3 | 双方法委托/source一致性 |
| TestScannerLineCountV2920 | 1 | 行数合理 |
| TestNoBacktestRegressionV2920 | 5 | 回测零影响 |

**全量测试**: 639 passed (0 failed)

### 29.6 scanner.py行数变化

| 阶段 | scanner.py行数 | 变化 |
|---|---|---|
| v2.9.19后 | 1831 | +8(提取方法签名) |
| **v2.9.20后** | **1817** | **-14行(-0.8%)** |

### 29.7 回测影响

零。所有变更仅影响market_monitor模块, 回测引擎零文件修改。

## 三十、v2.9.21 MarketPhase时间分类提取 + 循环门控统一 (2026-05-31)

### 30.1 设计目标

1. **🟡 时间门控重复消除**: `_scan_loop`和`_risk_loop_sync`各自内联时间判断(5处+3处硬编码字符串比较),逻辑相似但分散
2. **🟡 可维护性**: 新增/修改交易时段只需改一处,而非两个方法各改一次
3. **🟡 新增竞价阶段**: 原来盘前9:00-9:30笼统处理,现拆分为PREMARKET(9:00-9:25)和AUCTION(9:25-9:30)

### 30.2 MarketPhase类设计

```python
class MarketPhase:
    """市场时间阶段分类【v2.9.21】"""
    WEEKEND = "weekend"          # 周末(调试模式)
    DEEP_NIGHT = "deep_night"    # 23:00-08:00 极低频
    PREMARKET = "premarket"      # 09:00-09:25 竞价前
    AUCTION = "auction"          # 09:25-09:30 竞价
    TRADING = "trading"          # 09:30-15:00 交易时间
    AFTER_CLOSE = "after_close"  # 15:05+ 收盘结算
    OFF_HOURS = "off_hours"      # 其他非交易时间

    @staticmethod
    def classify() -> str:
        """分类当前时间阶段(零副作用, 可随时调用)"""
        ...
```

**设计决策**:
- 使用纯字符串常量(非Enum), 与现有代码风格一致,避免import复杂度
- `classify()`是纯函数:零副作用,可被任意线程随时调用
- 不持有状态,不需要实例化

### 30.3 _scan_loop重构

| Before | After |
|---|---|
| 5处硬编码字符串比较 | `MarketPhase.classify()` + 6个phase分支 |
| `now.weekday() >= 5` | `phase == MarketPhase.WEEKEND` |
| `"09:30" <= ct <= "15:00"` | `phase == MarketPhase.TRADING` |
| `"09:00" <= ct < "09:30"` | `phase in (PREMARKET, AUCTION)` |

### 30.4 _risk_loop_sync重构

| Before | After |
|---|---|
| `(ct < "09:25" or ct > "15:05") and not is_weekend` | `phase not in (TRADING, AUCTION)` |
| `if is_weekend` | `phase == MarketPhase.WEEKEND` |
| 无深夜逻辑 | 新增`DEEP_NIGHT`→5分钟检查一次 |

### 30.5 测试覆盖 (21新增)

| 测试类 | 用例数 | 覆盖点 |
|---|---|---|
| TestMarketPhaseClassify | 12 | 7阶段分类+零副作用+7阶段唯一 |
| TestScanLoopUsesMarketPhase | 2 | 无硬编码比较+使用MarketPhase |
| TestRiskLoopUsesMarketPhase | 2 | 无硬编码比较+使用MarketPhase |
| TestMarketPhaseEdgeCases | 4 | 边界时间(9:30/15:00/9:25/15:01) |
| TestNoBacktestRegressionV2921 | 2 | 回测零影响+模块可导入 |

**全量测试**: 660 passed (0 failed)

### 30.6 scanner.py行数变化

| 阶段 | 行数 | 变化 |
|---|---|---|
| v2.9.20 | 1817 | -14行(提取_liquidate_positions) |
| **v2.9.21** | **1849** | **+32行(MarketPhase类)** |

### 30.7 回测影响

零。所有变更仅影响market_monitor模块, 回测引擎零文件修改。

### 30.8 追加重构: _reset_daily_risk_state提取

**问题**: `premarket_prepare`中26行风控重置代码(circuit_breaker重置+pending_sells清除+执行统计重置)与盘前准备逻辑混在一起。

**修复**: 提取`_reset_daily_risk_state()`方法(26行), `premarket_prepare`从66行→41行(-39%)。

**影响**: 仅代码组织优化, 行为完全不变。

## 三十一、v2.9.22 分步计时+卖出统计分类修复+跨日一致性+错误恢复 (2026-05-31)

### 31.1 设计目标

1. **🔴 卖出统计分类bug**: `_post_sell_cleanup`中所有卖出都`_stats["stop_losses"] += 1`,无论止损/止盈/情绪调仓,导致`get_status()`中`stop_losses`虚高
2. **🟡 scan_once性能可观测**: 扫描7个步骤无耗时追踪,性能瓶颈难以定位
3. **🟡 跨日pending_sells一致性**: 跨日后Broker持仓已恢复,但旧`_pending_sells`可能引用已卖出的票(当日跌停挂起→次日已卖出但pending_sells仍在)
4. **🟡 _scan_loop瞬态错误恢复**: 单次异常直接`_is_running = False`杀死scanner,MongoDB临时抖动也会导致整个扫描退出
5. **🟡 _risk_loop_sync连续错误空转**: 风控线程异常时1秒循环刷日志,连续错误无退避

### 31.2 变更详情

#### A. scan_once分步计时

```python
# 新增5个步骤计时(step1_ms~step5_ms)
t1 = time.time()
realtime_data = await self._fetch_realtime_batch(force=force)
step1_ms = (time.time() - t1) * 1000
# ... 同理step2-step5

# 慢步骤标记: ⚠️>100ms / 🔴>1s
slow_marks = []
for label, ms in [("行情", step1_ms), ("因子", step2_ms), ...]:
    if ms > 1000: slow_marks.append(f"🔴{label}={ms:.0f}ms")
    elif ms > 100: slow_marks.append(f"⚠️{label}={ms:.0f}ms")
```

**效果**: 日志中可直接看到哪步慢,如`[SCAN] 完成: 4500只 | 3信号 | 8.2秒 | 慢步骤: 🔴行情=5200ms`

#### B. _post_sell_cleanup统计分类修复

| 卖出原因 | 修复前 | 修复后 |
|---|---|---|
| stop_loss/gap_stop_loss/trailing_stop | stop_losses | ✅ stop_losses |
| take_profit/profit_lock/profit_protect | stop_losses | ✅ take_profits |
| moving_stop/emotion/max_hold/force_empty/stop_sell | stop_losses | ✅ trades_executed |

#### C. _reset_daily_risk_state跨日一致性

```python
# 清理已无持仓的pending_sells(跨日后Broker已恢复)
with self._state_lock:
    if self._pending_sells and self._broker:
        held_codes = {p.ts_code for p in self._broker.get_positions()}
        stale = [c for c in self._pending_sells if c not in held_codes]
        for c in stale:
            del self._pending_sells[c]
    self._pending_sells.clear()
```

#### D. _scan_loop瞬态错误恢复

```python
# 3次连续异常才退出,中间30秒重试
self._scan_loop_error_count = getattr(self, '_scan_loop_error_count', 0) + 1
if self._scan_loop_error_count >= 3:
    self._is_running = False
else:
    await asyncio.sleep(30)  # 30秒后重试
```

scan_once成功时重置: `self._scan_loop_error_count = 0`

#### E. _risk_loop_sync连续错误退避

| consecutive_errors | sleep | 说明 |
|---|---|---|
| 1-2 | 1秒 | 正常重试 |
| 3-9 | 5秒 | 避免空转刷日志 |
| ≥10 | 30秒 | 严重问题,降频检查 |

成功时重置: `consecutive_errors = 0`

### 31.3 测试覆盖 (18新增)

| 测试类 | 用例数 | 覆盖点 |
|---|---|---|
| TestScanOnceTiming | 3 | 分步计时变量+慢步骤标记+行数 |
| TestPostSellCleanupStats | 3 | 分类逻辑+统计键+3类计数 |
| TestCrossDayPendingSells | 2 | 跨日清理+空后重置 |
| TestScanLoopErrorRecovery | 4 | 初始化+恢复逻辑+重置+3次限制 |
| TestRiskLoopErrorBackoff | 4 | 退避逻辑+阈值+重置+事件 |
| TestGetStatusV2922 | 1 | scan_loop_errors字段 |
| TestNoBacktestRegressionV2922 | 2 | 回测零影响+模块可导入 |

**全量测试**: 814 passed (0 failed)

### 31.4 scanner.py行数变化

| 阶段 | 行数 | 变化 |
|---|---|---|
| v2.9.21 | 1851 | +2行(MarketPhase类) |
| v2.9.22 | 1922 | 分步计时+卖出统计分类修复+跨日一致性+错误恢复 |
| v2.9.23 | 2017 | 行情缓存过期检测+异常日志增强+跌停恢复重试+提取重构 |
| **v2.9.22** | **1922** | **+71行(分步计时30行+统计分类12行+跨日一致性10行+错误恢复19行)** |

### 31.5 回测影响

零。所有变更仅影响market_monitor模块, 回测引擎零文件修改。

## 三十二、v2.9.23 行情缓存过期检测+异常日志增强+跌停恢复重试+提取重构 (2026-05-31)

### 32.1 设计目标

1. **🟡 行情缓存过期检测**: 交易时间内行情源故障时,风控线程使用过期数据做止损判断,可能导致误判
2. **🔴 关键路径异常静默吞没**: `_post_sell_cleanup`等关键卖出路径4个`except Exception: pass`,问题不可观测
3. **🟡 跌停恢复后卖出遗忘**: 跌停挂起的pending_sells在跌停恢复后没有被自动重试

### 32.2 变更详情

#### A. 行情缓存过期检测

```python
# 新增_last_realtime_update_ts字段
self._last_realtime_update_ts: float = 0.0

# _risk_loop_sync中检测
if phase == MarketPhase.TRADING:
    cache_age = time.time() - (self._last_realtime_update_ts or 0)
    if cache_age > 120:  # 2分钟未更新
        logger.warning(f"[RISK_THREAD] 行情缓存过期({cache_age:.0f}秒)")
        # 每5分钟发射一次事件(避免刷日志)
```

#### B. 异常日志增强

| 位置 | 修复前 | 修复后 |
|---|---|---|
| _post_sell_cleanup timeline事件 | `except: pass` | `except: logger.debug(...)` |
| _post_sell_cleanup 卖出事件 | `except: pass` | `except: logger.debug(...)` |
| _post_sell_cleanup broker持久化 | `except: pass` | `except: logger.warning(...)` |
| _post_sell_cleanup 运行时快照 | `except: pass` | `except: logger.debug(...)` |
| _scan_loop_settlement 3处 | `except: pass` | `except: logger.debug/warning(...)` |
| _persist_stop_state 2处 | `except: pass` | `except: logger.warning(...)` |
| _restore_start_state 审计索引 | `except: pass` | `except: logger.debug(...)` |
| update_strategy_config 3处 | `except: pass` | `except: logger.debug(...)` |
| _load/persist_strategy_overrides | `except: pass` | `except: logger.debug(...)` |

保留5个bare except(均有注释): 事件发射失败不应影响主流程/风控线程/行情推送/参数校验

#### C. 跌停恢复后卖出重试

```python
def _retry_pending_sells(self, realtime_data: Dict):
    """跌停恢复后重试挂起的卖出指令"""
    with self._state_lock:
        pending = dict(self._pending_sells)
    for ts_code, info in pending.items():
        # 已无持仓→清除
        # 仍在跌停→跳过
        # 跌停恢复→重新执行卖出
```

#### D. 方法提取

| 新方法 | 来源 | 行数 |
|---|---|---|
| `_retry_pending_sells` | `_check_stop_loss_only`拆分 | 50行 |
| `_execute_sell_list_from_risk` | `_check_stop_loss_only`拆分 | 26行 |
| `_build_timeline_entry` | `_post_sell_cleanup`拆分(staticmethod) | 24行 |

### 32.3 测试覆盖

v2.9.22测试28个 + v2.9.23无新增(纯增强), 全量822 passed。

### 32.4 回测影响

零。所有变更仅影响market_monitor模块。

## 三十三、v2.9.24 diagnose+情绪调仓提取 + DelegateRouter策略扩展 (2026-05-31)

### 33.1 设计目标

1. **🟡 diagnose()提取**: 83行运行时诊断方法,纯读取scanner状态,语义归属ScannerUtils
2. **🟡 _handle_emotion_phase_change提取**: 66行情绪调仓逻辑,语义归属EmotionCycleManager
3. **🟡 DelegateRouter策略扩展**: 新增`_emotion_cycle_class`路由策略,支持EmotionCycleManager静态方法绑定

### 33.2 变更详情

#### A. diagnose()提取到ScannerUtils

```python
# scanner.py → 删除diagnose()方法(83行)
# scanner_utils.py → 新增ScannerUtils.diagnose(scanner)静态方法
# DELEGATE_MAP注册: "diagnose": ("_scanner_utils", "diagnose")
# 委托路由: _UTILS_CONTEXT_METHODS["diagnose"] = lambda scanner, method: lambda: method(scanner)
```

#### B. _handle_emotion_phase_change提取到EmotionCycleManager

```python
# scanner.py → 删除_handle_emotion_phase_change()方法(66行)
# emotion_cycle.py → 新增EmotionCycleManager.handle_emotion_phase_change(scanner, old_phase, new_phase)静态方法
# DELEGATE_MAP注册: "_handle_emotion_phase_change": ("_emotion_cycle_class", "handle_emotion_phase_change")
```

#### C. DelegateRouter新增策略

| 策略 | 模块属性 | 绑定器 |
|---|---|---|
| 策略3.5: EmotionCycleManager | `_emotion_cycle_class` | `_EMOTION_BINDINGS` |

```python
# scanner_delegate_router.py
_EMOTION_BINDINGS = {
    "handle_emotion_phase_change": lambda method, scanner: lambda old_phase, new_phase: method(scanner, old_phase, new_phase),
}
# _ASYNC_DELEGATE_METHODS新增: "_handle_emotion_phase_change"
```

### 33.3 文件变更

| 文件 | 变更 |
|---|---|
| nodes/market_monitor/scanner.py | 删除diagnose()83行+删除_handle_emotion_phase_change()66行, 2103→1966行(-6.5%) |
| nodes/market_monitor/scanner_utils.py | 新增ScannerUtils.diagnose()83行, 376→465行 |
| nodes/market_monitor/emotion_cycle.py | 新增EmotionCycleManager.handle_emotion_phase_change()66行, 434→500行 |
| nodes/market_monitor/scanner_delegate_router.py | 新增_EMOTION_BINDINGS+策略3.5+_ASYNC_DELEGATE_METHODS, 136→153行 |
| tests/scanner/test_v2924_extraction.py | 新增13个测试 |
| tests/scanner/test_position_checker_integration.py | 更新: MarketScanner._handle_emotion_phase_change→EmotionCycleManager.handle_emotion_phase_change |
| tests/scanner/test_v29_optimizations.py | 更新: inspect源码检查指向EmotionCycleManager |

### 33.4 scanner.py行数变化

| 阶段 | 行数 | 变化 |
|---|---|---|
| v2.9.23 | 2017 | 行情缓存过期检测+异常日志增强+跌停恢复重试+提取重构(实际git: 2103) |
| **v2.9.24** | **1966** | **-137行(-6.5%) diagnose提取83行+情绪调仓提取66行-注释12行** |

### 33.5 测试覆盖

新增13个测试(diagnose委托5+情绪调仓委托4+DelegateRouter策略3+行数回归1):
- TestDiagnoseDelegation: 5个(委托调用/直接调用一致性/缓存过期/DELEGATE_MAP注册)
- TestEmotionPhaseChangeDelegation: 4个(无规则调仓/有持仓调仓/DELEGATE_MAP注册)
- TestDelegateRouterEmotionStrategy: 3个(binder注册/async注册/resolve可调用)
- TestScannerLineCount: 1个(scanner.py < 2000行回归)

全量696 scanner测试 + 50 backtest测试通过。

### 33.6 回测影响

零。所有变更仅影响market_monitor模块委托路由, 回测引擎零文件修改。

## 三十四、v2.9.36 审查P0/P1修复 + WS断线补发 + 前端错误提示 (2026-05-31)

### 34.1 设计目标

根据 REALTIME_MONITOR_AUDIT_20260531.md 审查报告, 修复3个P0严重Bug + 1个P1问题, 并补齐WS断线重连后的Stream消息补发能力。

### 34.2 P0#1: Redis→WebSocket桥接未启动 (🔴 严重)

**问题**: `nodes/web/app.py` lifespan函数中从未调用`init_bridge()`和`bridge.start()`, 导致整个实时数据推送链路(Redis Pub/Sub → WebSocket → 前端)完全不工作。

**影响**: scanner信号/持仓/时间线不会通过WS推送, 前端只能依赖REST轮询。

**修复**: 在lifespan启动部分添加bridge初始化和启动, 关闭部分添加bridge停止:
```python
# 启动
from .websocket import manager as ws_manager
from .redis_ws_bridge import init_bridge
bridge = init_bridge(ws_manager)
await bridge.start()

# 关闭
from .redis_ws_bridge import get_bridge
bridge = get_bridge()
if bridge:
    await bridge.stop()
```

### 34.3 P0#2: signal_persistence集合常量未定义 (🔴 严重)

**问题**: `signal_persistence.py`中`COLLECTION_REVIEW`/`COLLECTION_EXECUTION_LOG`/`COLLECTION_POOL`三常量只有注释但从未定义, 运行时NameError。

**修复**: 添加常量定义:
```python
COLLECTION_REVIEW = "daily_postmarket_review"
COLLECTION_EXECUTION_LOG = "signal_execution_log"
COLLECTION_POOL = "premarket_pool"
```

### 34.4 P0#3: daily_settlement无路由装饰器 (🔴 严重)

**问题**: `daily_settlement()`函数定义了但没有`@router.post`装饰器, 前端POST请求返回404。

**修复**: 添加路由装饰器:
```python
@router.post("/scanner/daily-settlement")
async def daily_settlement():
```

### 34.5 P1#4: RedisWSBridge._log_cache未初始化 (🟡 中等)

**问题**: `get_stats()`中`len(self._log_cache)`引用已移除的属性, 运行时NameError。

**修复**: 替换为整数常量`0`:
```python
"cached_tasks": 0,  # _log_cache不再缓存
```

### 34.6 P2#8: WS断线重连后Stream ID补发 (🟢 低风险)

**问题**: 前端记录了`lastSignalStreamId`/`lastPositionStreamId`但断线重连后未使用, 断线期间的信号/持仓变更丢失。

**修复**: `ws.onopen`回调中, 如果有上次的Stream ID, 调用REST API补发:
```javascript
// 断线重连后补发缺失的Stream消息
if (lastSignalStreamId) {
  fetch(`/api/v1/scanner/stream/signals?after=${lastSignalStreamId}&count=50`)
    .then(r => r.json()).then(j => {
      if (j.success && j.data?.length) {
        for (const msg of j.data) {
          if (msg.data) scannerStore.updateFromWs('signal', { item: msg.data.signals?.[0] || msg.data.item })
        }
        fetchScanner() // 刷新全量状态
      }
    }).catch(() => {})
}
```

### 34.7 P2#9: onMounted错误提示 (🟢 低风险)

**问题**: `onMounted`中catch只打console.error, 用户不知道初始化失败。

**修复**: 关键初始化失败时显示ElMessage提示:
```javascript
catch(e) {
  console.error('[Mount] fetch error:', e);
  ElMessage.warning('数据加载失败，请检查连接后刷新')
}
```

### 34.8 变更文件

| 文件 | 变更 |
|---|---|
| nodes/web/app.py | lifespan添加bridge启动/停止 |
| nodes/web/signal_persistence.py | 添加3个集合常量定义 |
| nodes/web/api/scanner.py | daily_settlement添加路由装饰器 + 版本→v2.9.36 |
| nodes/web/redis_ws_bridge.py | get_stats修复_log_cache引用 |
| frontend/src/views/monitor/MarketMonitorView.vue | WS断线补发 + onMounted错误提示 |
| tests/scanner/test_v2936_audit_p0_fixes.py | 新增15测试 |
| docs/MARKET_MONITOR_OPTIMIZATION_DESIGN.md | v2.9.36记录 |

### 34.9 测试覆盖

| 测试类 | 用例数 | 覆盖点 |
|---|---|---|
| TestBridgeStartedInLifespan | 4 | init_bridge导入/bridge.start/bridge.stop/try-except保护 |
| TestSignalPersistenceCollections | 4 | 3常量定义+引用验证 |
| TestDailySettlementRoute | 2 | 路由装饰器+路径 |
| TestLogCacheReference | 2 | 无_log_cache引用/常量整数 |
| TestNoBacktestRegressionV2936 | 3 | 回测模块零影响 |

**全量测试**: 834 passed (0 failed)

### 34.10 回测影响

零。所有修复限于web层(app.py/signal_persistence/scanner API/redis_ws_bridge)和前端, 回测引擎零文件修改。

## 三十五、v2.9.37 _save_param_snapshot提取 + _init_state类属性瘦身 (2026-06-01)

### 35.1 设计目标

1. **start()方法瘦身**: 参数快照保存逻辑(16行)提取为`_save_param_snapshot()`, start()有效代码43→30行
2. **_init_state类属性默认值**: 21个标量默认值提升为类属性声明, _init_state有效代码70→30行
3. **修复失败测试**: `test_start_line_count`阈值更新(<40→<35)
4. **版本同步**: 3个旧测试的版本断言更新(v2.9.36→v2.9.37)

### 35.2 _save_param_snapshot提取

**问题**: `start()`中16行参数快照保存逻辑(STRATEGY_CONFIGS遍历+MongoDB upsert)与启动编排无关, 应独立方法。

**修复**: 提取为`_save_param_snapshot(trade_date)`方法, start()仅保留一行`await self._save_param_snapshot(trade_date)`。

### 35.3 _init_state类属性默认值

**问题**: `_init_state()`中21个标量赋值(`self._is_running = False`, `self._scan_count = 0`等)每次实例化都执行, 但值始终相同。

**修复**: 将不可变标量默认值提升为类属性:

```python
class MarketScanner:
    # 类属性默认值(不可变/标量)【v2.9.37】
    _risk_thread = None
    _risk_running: bool = False
    _risk_thread_restarts: int = 0
    _is_running: bool = False
    _scan_count: int = 0
    _nav_peak: float = 1.0
    _trade_date: str = ""
    # ... 共21个
```

**设计原则**:
- 不可变标量(数字/字符串/None/bool) → 类属性默认值
- 可变容器(dict/list) → 仍必须在`__init__`中初始化, 避免实例间共享
- 每个实例设置属性时自动创建实例属性, 不影响类默认值

### 35.4 scanner.py行数变化

| 阶段 | 行数 | 变化 |
|---|---|---|
| v2.9.36 | 1531 | 基线 |
| **v2.9.37** | **1529** | **-2行(start瘦身+类属性替代_init_state赋值, 新增_save_param_snapshot 16行被删除覆盖)** |

### 35.5 方法有效行数改善

| 方法 | v2.9.36 | v2.9.37 | 变化 |
|---|---|---|---|
| start() | 43行 | 30行 | -30% |
| _init_state() | 70行 | 30行 | -57% |

### 35.6 变更文件

| 文件 | 变更 |
|---|---|
| nodes/market_monitor/scanner.py | _save_param_snapshot提取 + 21个类属性默认值 + _init_state瘦身 |
| nodes/web/api/scanner.py | _DESIGN_DOC_VERSION→v2.9.37 |
| tests/scanner/test_v2937_init_state_class_attrs.py | 新增20测试 |
| tests/scanner/test_v2918_review_optimization.py | start()行数阈值<40→<35 |
| tests/scanner/test_v2916_risk_watchdog_thread_safety.py | 版本断言v2.9.36→v2.9.37 |
| tests/scanner/test_v2933_extraction_optimization.py | 版本断言v2.9.36→v2.9.37 |
| tests/scanner/test_v295_stability.py | _risk_thread_restarts检查改为类属性验证 |
| docs/MARKET_MONITOR_OPTIMIZATION_DESIGN.md | v2.9.37记录 |

### 35.7 测试覆盖 (20新增)

| 测试类 | 用例数 | 覆盖点 |
|---|---|---|
| TestSaveParamSnapshotExtraction | 4 | 存在性/async/start调用/无内联逻辑 |
| TestClassAttributeDefaults | 3 | 类属性值/实例继承/实例覆盖不影响类 |
| TestInitStateSlimmed | 4 | 无冗余赋值/仍初始化可变默认值/行数<35 |
| TestStartMethodSlimmed | 1 | start()<35行 |
| TestSaveParamSnapshotBehavior | 3 | MongoDB写入/包含date/失败不影响启动 |
| TestScannerLineCount | 1 | <1550行 |
| TestNoBacktestRegressionV2937 | 5 | 回测零影响+类属性隔离+版本常量 |

**全量测试**: 851 passed (0 failed), 回测214 passed (0 failed)

### 35.8 回测影响

零。所有变更仅影响market_monitor模块scanner.py内部重构和测试, 回测引擎零文件修改。

## 三十六、v2.9.38 _run_checker_on_positions提取 + compare差异持久化 + _post_sell_state_cleanup统一 (2026-06-01)

### 36.1 设计目标

1. **🟡 checker/compare重复遍历消除**: `_check_positions_checker`和`_check_positions_compare`中各有30+行几乎相同的持仓遍历+checker调用逻辑, 应提取公共方法
2. **🟡 卖出后清理3处重复**: legacy/checker模式的卖出后trailing_stops/position_risk_levels清理+持久化逻辑完全相同(15行), 应提取统一方法
3. **🟡 compare差异持久化**: compare模式只记录日志和EventBus事件, 无MongoDB持久化, 差异数据重启后丢失, 不利于审计分析

### 36.2 变更详情

#### A. _run_checker_on_positions提取

**问题**: `_check_positions_checker`和`_check_positions_compare`各有一段30+行几乎相同的代码:遍历持仓→加锁读trailing_state→计算trade_days_held→调用checker.check_realtime_sell→收集结果。仅返回格式不同(checker返回5元组含priority, compare只收集ts_code)。

**修复**: 提取`_run_checker_on_positions(checker, positions, realtime_data, trade_date)`公共方法, 返回统一的5元组列表`[(pos, reason, sell_price, risk, priority)]`:

- checker模式: 调用后按priority排序→去掉第5元→执行卖出
- compare模式: 调用后只取ts_code集合→记录差异

**代码减少**: ~60行重复代码消除

#### B. _post_sell_state_cleanup提取

**问题**: `_check_positions_legacy`和`_check_positions_checker`中卖出后清理逻辑完全相同:
1. `with self.state_lock: trailing_stops.pop / position_risk_levels.pop`
2. `if to_sell and self.broker: await self.broker.save_state(force=True)`
3. `await scanner._save_runtime_snapshot(force=True)`

**修复**: 提取为`_post_sell_state_cleanup(to_sell)`方法:
- 空列表提前返回(`if not to_sell: return`)
- 加锁清理trailing_stops/position_risk_levels
- broker.save_state + _save_runtime_snapshot (均有try/except保护)

**调用方变更**:
- `_check_positions_legacy`: 删除15行内联清理→1行`await self._post_sell_state_cleanup(to_sell)`
- `_check_positions_checker`: 删除15行内联清理→1行`await self._post_sell_state_cleanup(to_sell)`

#### C. compare差异MongoDB持久化

**问题**: compare模式发现差异时只记录日志和EventBus事件, 运维人员需要手动收集日志才能分析。重启后历史差异丢失。

**修复**: 新增`_persist_compare_diff()`方法, 将差异记录写入MongoDB `sell_compare_diff`集合:

```python
{
    "trade_date": "20260601",
    "time": "10:30:15",
    "only_legacy": ["600036.SH"],
    "only_checker": ["000001.SZ"],
    "both": ["300750.SZ"],
    "diff_details": {
        "600036.SH": {
            "code": "600036.SH",
            "legacy_reason": "止损 -3.5%",
            "checker_reason": None,
            "legacy_profit_pct": -3.5,
            "strategy": "半路追涨",
            "price": 38.5,
            "pct_chg": -2.1,
        },
        ...
    },
    "summary": {
        "total_legacy": 3,
        "total_checker": 2,
        "agreement_rate": 33.3,
    },
}
```

**特性**:
- TTL索引: 30天自动过期(`ttl_30d_compare`)
- 幂等: create_index已存在不报错
- 安全: try/except保护, MongoDB不可用不影响主流程
- 详情: 每只差异股票记录两侧原因+行情上下文
- 统计: 自动计算一致率(agreement_rate)

### 36.3 变更文件

| 文件 | 变更 |
|---|---|
| nodes/market_monitor/position_checker.py | 新增3个方法; checker/compare模式用提取方法; legacy用_post_sell_state_cleanup |
| nodes/web/api/scanner.py | _DESIGN_DOC_VERSION→v2.9.38 |
| tests/scanner/test_v2938_checker_extraction.py | 新增32测试 |
| tests/scanner/test_v2937_init_state_class_attrs.py | 版本断言更新 |
| docs/MARKET_MONITOR_OPTIMIZATION_DESIGN.md | v2.9.38记录 |

### 36.4 position_checker.py行数变化

| 阶段 | 行数 | 变化 |
|---|---|---|
| v2.9.37 | 606 | 基线 |
| **v2.9.38** | **688** | **+82行(3个新方法共约110行, 消除约60行重复, 净增+82行但逻辑更清晰)** |

### 36.5 测试覆盖 (32新增)

| 测试类 | 用例数 | 覆盖点 |
|---|---|---|
| TestRunCheckerOnPositions | 8 | 存在性/5元组返回/checker模式调用/compare模式调用/无重复循环/加锁/trade_days_held |
| TestPostSellStateCleanup | 10 | 存在性/trailing_stops_pop/position_risk_levels_pop/state_lock/broker_save/runtime_snapshot/legacy调用/checker调用/无内联pop/空列表提前返回 |
| TestCompareDiffPersistence | 7 | 存在性/集合名/TTL索引/差异详情字段/compare调用/try/except保护 |
| TestCodeReduction | 2 | 行数合理/无重复for循环 |
| TestVersionSync | 2 | API版本/文档版本 |
| TestNoBacktestRegression | 5 | 引入/签名/默认参数/无回测引用/无外部依赖 |

**全量测试**: 883 passed (0 failed)

### 36.6 回测影响

零。所有变更仅影响position_checker.py内部重构, 回测引擎零文件修改。SellSignalChecker.check_realtime_sell API签名不变。

## 三十七、v2.9.43 signal_manager方法提取7子方法 (2026-06-01)

### 37.1 设计目标

1. **🟡 execute_signals 161行→24行**: 信号执行逻辑拆分为4个子方法(dry_run/eligibility/single_buy/post_buy_success)
2. **🟡 update_signals 96行→9行**: 信号更新逻辑拆分为3个子方法(expire/merge/process)
3. **🟡 熔断检查同步化**: `_check_signal_eligibility`改为sync方法(直接读取circuit_breaker字典),避免每个信号都await

### 37.2 execute_signals拆分

**问题**: `execute_signals` 161行,包含dry_run处理(8行)+5种前置检查(40行)+PositionSizer(30行)+滑点+下单+善后(83行),职责混杂。

**修复**: 提取4个方法:

| 方法 | 职责 | 行数 | 类型 |
|---|---|---|---|
| `_handle_dry_run(signals)` | 调试模式:记录不执行 | 14行 | sync |
| `_check_signal_eligibility(sig)→(eligible, reason)` | 5种前置检查(异动/持仓/熔断/最大持仓/价格) | 35行 | sync |
| `_execute_single_buy(sig)` | PositionSizer+质量检查+滑点+下单+善后 | 60行 | async |
| `_post_buy_success(sig, order, ...)` | 买入成功后timeline+统计+事件推送 | 45行 | async |

**execute_signals主方法**: 24行,仅编排循环+eligibility判断+single_buy调用。

**关键改进**:
- `_check_signal_eligibility`改为sync: 直接读取`circuit_breaker`字典(主循环已持有锁),避免每个信号await `_check_circuit_breaker()`
- 返回`(eligible, reason)`元组: reason区分全局阻挡(circuit_breaker/max_positions→break)和单票阻挡(anomaly/duplicate/invalid_price→continue)

### 37.3 update_signals拆分

**问题**: `update_signals` 96行,包含过期清理(20行)+增量合并(25行)+推送执行(51行),三个独立步骤混在一起。

**修复**: 提取3个方法:

| 方法 | 职责 | 行数 | 类型 |
|---|---|---|---|
| `_expire_old_signals()` | 过期信号清理+状态标记+事件推送 | 20行 | async |
| `_merge_new_signals(new_signals)→List` | 增量合并(新增/更新已有),返回added列表 | 22行 | sync |
| `_process_new_signals(added, scan_time)` | 推送+EventBus+执行+持久化 | 38行 | async |

**update_signals主方法**: 9行,仅编排3个步骤。

**设计决策**:
- `_merge_new_signals`为sync(纯数据计算), 可被同步测试
- `_expire_old_signals`为async(含事件推送)
- `_process_new_signals`为async(含broker/EventBus)

### 37.4 变更文件

| 文件 | 变更 |
|---|---|
| nodes/market_monitor/signal_manager.py | 7个新方法; execute_signals 161→24行; update_signals 96→9行; 410→425行(+3.7%) |
| nodes/web/api/scanner.py | _DESIGN_DOC_VERSION→v2.9.43 |
| tests/scanner/test_v2943_signal_manager_extraction.py | 新增28测试 |
| tests/scanner/test_v2916_risk_watchdog_thread_safety.py | 版本断言v2.9.41→v2.9.43 |
| tests/scanner/test_v2933_extraction_optimization.py | 版本断言v2.9.41→v2.9.43 |
| tests/scanner/test_v2937_init_state_class_attrs.py | 版本断言v2.9.41→v2.9.43 |
| tests/scanner/test_v2938-v2942_*.py | 版本断言统一v2.9.43 |
| docs/MARKET_MONITOR_OPTIMIZATION_DESIGN.md | v2.9.43记录 |

### 37.5 方法行数改善

| 方法 | v2.9.42 | v2.9.43 | 变化 |
|---|---|---|---|
| execute_signals | 161行 | 24行 | -85% |
| update_signals | 96行 | 9行 | -91% |
| **新增** | | | |
| _handle_dry_run | - | 14行 | 调试模式处理 |
| _check_signal_eligibility | - | 35行 | 前置检查(5种) |
| _execute_single_buy | - | 60行 | 单票买入 |
| _post_buy_success | - | 45行 | 买入善后 |
| _expire_old_signals | - | 20行 | 过期清理 |
| _merge_new_signals | - | 22行 | 增量合并(sync) |
| _process_new_signals | - | 38行 | 推送+执行+持久化 |

### 37.6 测试覆盖 (28新增)

| 测试类 | 用例数 | 覆盖点 |
|---|---|---|
| TestSignalManagerMethodExtraction | 7 | 7个新方法存在性 |
| TestSignalManagerUpdateSignalsSplit | 4 | 调用3子方法+行数<20 |
| TestSignalManagerExecuteSignalsSplit | 6 | 行数<30/调用eligibility/调用single_buy/返回元组/无async检查/break条件 |
| TestSignalManagerMergeNewSignals | 3 | merge为sync/expire为async/process为async |
| TestSignalManagerLineCount | 1 | 行数<460 |
| TestVersionSyncV2943 | 2 | API版本v2.9.43/DELEGATE_MAP条目 |
| TestNoBacktestRegressionV2943 | 5 | 文件存在/不导入signal_manager/回测测试非空 |

**全量测试**: 1000 passed (0 failed)

### 37.7 回测影响

零。所有变更仅影响signal_manager.py内部重构, 回测引擎零文件修改。SignalManager.execute_signals/update_signals API签名不变。

---

## 38. v2.9.45: 方法提取+bug修复+委托对齐

### 38.1 关键bug修复

**Daemon._cmd_emergency_liquidate路径断裂**:
- 问题: `_cmd_emergency_liquidate`调用`scanner.emergency_liquidate()`和`scanner.close_all_positions()`，但scanner上两个方法均不存在
- 影响: 通过Daemon IPC发送紧急清仓命令会静默失败(GUI红色按钮/Daemon模式)
- 修复: scanner新增`emergency_liquidate()`方法,委托给RiskWatchdog

### 38.2 方法提取

| 源方法 | 原行数 | 提取后 | 提取子方法 |
|---|---|---|---|
| risk_watchdog.emergency_liquidate | 80行 | 35行 | 复用post_sell_cleanup |
| runtime_persistence.load_runtime_snapshot | 78行 | 15行 | _load_snapshot_doc + _restore_snapshot_data |
| position_checker._persist_compare_diff | 71行 | 8行 | 委托RuntimePersistence.persist_compare_diff |
| position_checker._post_sell_processing | 63行 | 30行 | 委托post_sell_cleanup |
| position_manager.check_stop_loss_take_profit | 85行 | 18行 | _get_risk_with_overrides + _check_trailing_stop + _check_regular_stop_profit + _check_intraday_rules |
| position_manager.check_stop_loss_only | 78行 | 30行 | _handle_limit_down + _check_quick_stop_loss |

### 38.3 委托对齐

卖出后处理统一委托RuntimePersistence.post_sell_cleanup:
- scanner._execute_risk_sell → post_sell_cleanup (v2.9.27)
- position_checker._post_sell_processing → post_sell_cleanup (v2.9.45)
- risk_watchdog.emergency_liquidate → post_sell_cleanup (v2.9.45)

好处: timeline/统计/EventBus/持久化逻辑统一,新增卖出路径自动获得完整后处理。

### 38.4 文件行数变化

| 文件 | v2.9.44 | v2.9.45 | 变化 |
|---|---|---|---|
| position_manager.py | 708 | 767 | +59(提取方法增加签名+doc) |
| position_checker.py | 627 | 603 | -24(委托减少内联) |
| risk_watchdog.py | 841 | 841 | 0(复用替代内联) |
| runtime_persistence.py | 1017 | 1017 | 0(新增persist_compare_diff+snapshot提取抵消) |
| scanner.py | 1382 | 1393 | +11(emergency_liquidate方法) |
| scanner_daemon.py | 1113 | 1114 | +1(路径修复) |

### 38.5 线程安全审查结论

✅ 共享状态(trailing_stops/pending_sells/position_risk_levels/position_risk_overrides/circuit_breaker):
- asyncio主循环内访问: 安全(单线程)
- 风控线程内访问: 全部通过state_lock保护
- 无嵌套锁风险(所有锁获取是顺序的)

### 38.6 测试覆盖

新增/更新测试:
- TestCompareDiffPersistence: 更新为检查runtime_persistence实现
- test_position_checker_delegates_to_rp: 新增(position_checker委托验证)
- test_position_checker_emits_events: 更新(委托post_sell_cleanup)
- test_compare_diff_index_uses_as: 更新(检查runtime_persistence)

**全量测试**: 960 passed (0 failed), 回测50 passed (0 failed)

### 38.7 回测影响

零。所有变更仅影响market_monitor模块内部重构,回测引擎零文件修改。

## 三十九、v2.9.47 getattr/hasattr防御消除 + 关键路径日志级别提升 (2026-06-01)

### 39.1 设计目标

1. **🟡 getattr/hasattr防御消除**: `_scan_loop_error_count`和`_last_realtime_update_ts`已在v2.9.37提升为类属性默认值,但代码中仍有6处getattr/hasattr防御调用,可简化
2. **🟡 hasattr防御消除**: `_risk_watchdog`和`_signal_dispatcher`在`_init_modules`中保证初始化,`_build_module_status`中hasattr多余
3. **🔴 关键路径日志级别提升**: runtime_persistence中6处盘后结算/快照/飞书推送失败用`logger.debug`,运维不可见,应提升为`logger.warning`

### 39.2 变更详情

#### A. getattr/hasattr防御消除

| 位置 | 修复前 | 修复后 |
|---|---|---|
| get_status | `getattr(self, '_scan_loop_error_count', 0)` | `self._scan_loop_error_count` |
| get_status | `getattr(self, '_last_realtime_update_ts', 0)` | `self._last_realtime_update_ts` |
| _scan_loop_error_recovery | `getattr(self, '_scan_loop_error_count', 0) + 1` | `self._scan_loop_error_count += 1` |
| scan_once | `hasattr(self, '_scan_loop_error_count') and ...` | `self._scan_loop_error_count > 0` |
| _check_stale_quote_cache | `hasattr(self, '_last_realtime_update_ts')` | `self._last_realtime_update_ts` |
| _update_scan_stats | `hasattr(self, '_risk_watchdog')` | `self._risk_watchdog` |
| _build_module_status | `hasattr(self, '_risk_watchdog')` | `self._risk_watchdog` |
| _build_module_status | `hasattr(self, '_signal_dispatcher')` | `self._signal_dispatcher` |

**设计原则**: 类属性默认值(v2.9.37)保证了实例化后这些属性始终存在,getattr/hasattr防御不再必要。

#### B. 关键路径日志级别提升

| 位置 | 修复前 | 修复后 | 理由 |
|---|---|---|---|
| sync_close_data_to_mongo | logger.debug | logger.warning | 数据同步失败影响MongoDB完整性 |
| post_sell_cleanup 快照 | logger.debug | logger.warning | 快照失败影响崩溃恢复 |
| daily_settlement 事件 | logger.debug | logger.warning | 结算事件失败影响前端状态 |
| daily_settlement 情绪 | logger.debug | logger.warning | 情绪预计算影响次日策略 |
| push_daily_summary 飞书 | logger.debug | logger.warning | 飞书推送失败运维不可见 |
| _cleanup_local_fallback | logger.debug | logger.warning | 降级文件残留影响下次恢复 |

**原则**: 影响运维可观测性或数据完整性的失败应warning; 纯辅助操作(如timeline事件发射失败)保留debug。

### 39.3 变更文件

| 文件 | 变更 |
|---|---|
| nodes/market_monitor/scanner.py | 8处getattr/hasattr消除 |
| nodes/market_monitor/runtime_persistence.py | 6处logger.debug→logger.warning |
| nodes/web/api/scanner.py | _DESIGN_DOC_VERSION→v2.9.47 |
| tests/scanner/test_v2947_getattr_loglevel.py | 新增18测试 |
| tests/scanner/test_v2916_risk_watchdog_thread_safety.py | 版本断言v2.9.46→v2.9.47 |
| tests/scanner/test_v2933_extraction_optimization.py | 版本断言v2.9.46→v2.9.47 |
| tests/scanner/test_v2937_init_state_class_attrs.py | 版本断言v2.9.46→v2.9.47 |
| tests/scanner/test_v2938_checker_extraction.py | 版本断言v2.9.46→v2.9.47 |
| tests/scanner/test_v2939_extraction_delegation.py | 版本断言v2.9.46→v2.9.47 |
| tests/scanner/test_v2940_filter_pipeline_auto_fetch.py | 版本断言v2.9.46→v2.9.47 |
| tests/scanner/test_v2941_stoploss_persist_delegation.py | 版本断言v2.9.46→v2.9.47 |
| tests/scanner/test_v2943_signal_manager_extraction.py | 版本断言v2.9.46→v2.9.47 |
| docs/MARKET_MONITOR_OPTIMIZATION_DESIGN.md | v2.9.47记录 |

### 39.4 测试覆盖 (18新增)

| 测试类 | 用例数 | 覆盖点 |
|---|---|---|
| TestGetattrHasattrElimination | 8 | 无getattr防御(4)+无hasattr防御(4) |
| TestRuntimePersistenceLogLevels | 6 | 关键路径warning级别(6) |
| TestVersionSync | 1 | API版本v2.9.47 |
| TestNoBacktestRegression | 3 | 回测零影响 |

**全量测试**: 1035 scanner + 51 backtest = 1086 passed (0 failed)

### 39.5 回测影响

零。getattr/hasattr消除和日志级别提升不影响回测模块,回测引擎零文件修改。

## 四十、v2.9.48 pipeline.apply提取 + broker.place_order提取 (2026-06-01)

### 40.1 设计目标

1. **🔴 live_filter_pipeline.apply提取**: 187行大方法拆分为4个子方法,消除L4/L5/L7重复过滤模式
2. **🔴 broker.place_order提取**: 182行大方法拆分为4个验证子方法,消除重复拒绝模式
3. **🟢 修复docstring问题**: broker.place_order中的docstring被拆成两段(Args被分离)

### 40.2 变更详情

#### A. live_filter_pipeline.apply提取

| 新方法 | 行数 | 职责 |
|---|---|---|
| `_resolve_positions_account` | 22 | 自动获取持仓/账户(从scanner._broker) |
| `_apply_L1_force_empty` | 39 | L1强制空仓检查,返回bool(是否触发) |
| `_apply_L3_sentiment` | 47 | L3情绪+冰点过滤,返回更新后ratio |
| `_apply_filter_layer` | 18 | L4/L5/L7共享过滤模式(before/after/dropped) |
| **apply(重构后)** | **103** | **从187→103行, 减少45%** |

**设计亮点**: `_apply_filter_layer` 消除了L4/L5/L7的重复 before_ids→after_ids→dropped→_record_layer_drop→layer_details 模式。

#### B. broker.place_order提取

| 新方法 | 行数 | 职责 |
|---|---|---|
| `_reject_order` | 6 | 拒绝委托+记录(消除6处重复3行模式) |
| `_validate_prechecks` | 37 | 停牌+行情+整手前置检查 |
| `_validate_and_adjust_buy` | 38 | 涨停+现金+单票+总仓位检查(含数量调整) |
| `_validate_sell` | 20 | 持仓+跌停+可卖数量检查 |
| **place_order(重构后)** | **109** | **从182→109行, 减少40%** |

**设计亮点**: `_validate_and_adjust_buy` 和 `_validate_sell` 返回 `(ok, reason, adjusted_quantity)`, 买入侧支持数量缩减(资金不足→缩小买入量), 卖出侧支持截断(可卖<委托→截断)。

### 40.3 变更文件

| 文件 | 变更 |
|---|---|
| nodes/market_monitor/live_filter_pipeline.py | apply提取4子方法(187→103行) |
| nodes/market_monitor/broker.py | place_order提取4子方法(182→109行) |
| nodes/web/api/scanner.py | _DESIGN_DOC_VERSION→v2.9.48 |
| tests/scanner/test_v2948_pipeline_apply_extraction.py | 新增19测试 |
| tests/scanner/test_v2948_broker_validation_extraction.py | 新增14测试 |
| docs/MARKET_MONITOR_OPTIMIZATION_DESIGN.md | v2.9.48记录 |

### 40.4 测试覆盖 (33新增)

| 测试文件 | 用例数 | 覆盖点 |
|---|---|---|
| test_v2948_pipeline_apply_extraction | 19 | apply大小+4子方法存在+调用+参数+契约 |
| test_v2948_broker_validation_extraction | 14 | place_order大小+4子方法存在+调用+参数 |

**全量测试**: 1068 scanner + 51 backtest = 1119 passed (0 failed)

### 40.5 回测影响

零。方法提取仅影响market_monitor模块内部,回测引擎零文件修改。

---

## 四十一、v2.9.49 审查P0/P1/P2修复 (2026-06-01)

> 基于全面审计报告 `docs/audit-realtime-monitor-2026-06-01.md` 的修复

### 41.1 修复清单

| 编号 | 优先级 | 问题 | 修复方案 | 文件 |
|------|--------|------|----------|------|
| #1 | P0 | WS Token泄漏到URL | 改为首条消息认证(`{"type":"auth","token":"xxx"}`) | websocket.py, useWebSocket.ts, MarketMonitorView.vue |
| #3 | P0 | Trading API越权访问 | signals/positions/trades查询加user_id过滤 | trading.py |
| #4 | P1 | 事件类型不匹配(scanner_signal vs signal) | useWebSocket添加scanner_*→Store映射 | useWebSocket.ts |
| #6 | P1 | 持仓N+1价格查询 | 改为$group聚合管道批量查询 | trading.py |
| #7 | P1 | Stream consumer_name硬编码 | 改为`f"web-node-{hostname}"` | redis_ws_bridge.py |
| #10 | P2 | System API同步pymongo阻塞 | health_check+data-status全部改async motor | system.py |
| #12 | P2 | useWebSocket无引用计数 | 添加acquire/release引用计数机制 | useWebSocket.ts |
| #13 | P2 | fetchScanner无并发控制 | 添加AbortController+running锁 | MarketMonitorView.vue |

### 41.2 P0安全修复详情

**WS Token首条消息认证**:
- 后端: `websocket.py` 增加`msg_type == "auth"`处理, 调用`verify_token`, 成功后加入`authenticated`集合
- 前端: `useWebSocket.ts` `getWsUrl()`不再拼token, `onopen`后发送`{"type":"auth","token":"xxx"}`
- 前端: `MarketMonitorView.vue` `connectWS()`同样发送auth消息
- 向后兼容: 仍保留URL Query参数方式(已连接后auth优先)

**Trading API越权访问修复**:
- `get_trading_signals()`: query增加`user_id`条件
- `get_positions()`: 验证account归属当前用户
- `get_trade_records()`: 验证account归属当前用户

### 41.3 P1修复详情

**事件类型映射**: useWebSocket.ts的`handleMessage()`增加4个case:
- `scanner_signal` → `scannerStore.updateFromWs('signal', ...)`
- `scanner_position` → `scannerStore.updateFromWs('position', ...)`
- `scanner_timeline` → `scannerStore.updateFromWs('timeline', ...)`
- `scanner_status` → `scannerStore.updateFromWs('status', ...)`

**持仓批量价格查询**: `$group`聚合管道一次查询所有持仓股票的最新价格:
```python
cursor = db.stock_daily_ak_full.aggregate([
    {"$match": {"ts_code": {"$in": codes}}},
    {"$sort": {"trade_date": -1}},
    {"$group": {"_id": "$ts_code", ...}},
])
```

**Stream consumer_name动态化**: `f"web-node-{socket.gethostname()}"` 替代硬编码 `"web-node-1"`

### 41.4 P2修复详情

**System API异步MongoDB**:
- `health_check()`: 删除SyncClient, 改用mongo_manager异步查询
- `get_data_status()`: 删除SyncClient, 改用mongo_manager + `await cursor.to_list()`
- `_get_factor_detail()`: 从同步改为`async`, 所有调用方加`await`
- `data_alignment`: 异步查询ts_code集合
- 线程内sync pymongo(`_run_sync_index`等)保留—线程中sync是安全的

**useWebSocket引用计数**: 添加`acquire()`/`release()`, subscribe时acquire, unsubscribe时release, 最后一个subscriber释放时自动断开连接。

**fetchScanner并发控制**: 添加`AbortController`+`fetchScannerRunning`锁, 防止请求叠加。

### 41.5 变更文件

| 文件 | 变更 |
|---|---|
| nodes/web/websocket.py | auth消息处理(verify_token+响应) |
| nodes/web/api/trading.py | user_id过滤+批量价格查询 |
| nodes/web/redis_ws_bridge.py | consumer_name动态化 |
| nodes/web/api/system.py | health_check+data-status异步化+_get_factor_detail异步 |
| frontend/src/hooks/useWebSocket.ts | auth消息+scanner映射+引用计数 |
| frontend/src/views/monitor/MarketMonitorView.vue | auth消息+fetchScanner并发控制 |
| tests/scanner/test_v2949_audit_fixes.py | 19新增测试 |
| tests/scanner/test_v2940_filter_pipeline_auto_fetch.py | 修复过时断言 |
| docs/MARKET_MONITOR_OPTIMIZATION_DESIGN.md | v2.9.49记录 |

### 41.6 测试覆盖 (19新增)

| 测试文件 | 用例数 | 覆盖点 |
|---|---|---|
| test_v2949_audit_fixes | 18 | P0 WS auth+越权访问, P1 批量查询+consumer_name, P2 async mongo+await+回归 |

**全量测试**: 1086 scanner passed (0 failed)

### 41.7 回测影响

零。所有修改限于web API层和前端, scanner核心和回测引擎零修改。

---

## 四十二、v2.9.50 Daemon方法名Bug修复+hasattr防御清理+except收窄 (2026-06-01)

### 42.1 🔴 关键Bug修复 (2个)

| Bug | 修复前 | 修复后 | 影响 |
|---|---|---|---|
| `_cmd_update_params` | 调用`scanner.update_strategy_params()`(不存在)→hasattr返回False→命令永远不执行 | 调用`scanner.update_strategy_config(strategy_key, updates)` | **策略参数热更新完全失效!** |
| `_cmd_scan` | 调用`scanner.run_once()`(不存在)→hasattr返回False→手动扫描永远不触发 | 调用`scanner.scan_once(trade_date, force=True)` | **手动扫描命令完全失效!** |

**根因**: v2.9.44提取`_SubprocessRuntime`时,闭包中的方法名未与scanner实际接口对齐。hasattr防御掩盖了错误,导致静默失败。

### 42.2 🟡 hasattr防御清理 (6处)

| 位置 | 修复前 | 修复后 | 原因 |
|---|---|---|---|
| `_cmd_emergency_liquidate` | `hasattr(scanner, "emergency_liquidate")` + elif hasattr fallback | 直接调用`scanner.emergency_liquidate()` | v2.9.45已添加该方法 |
| `_run_scanner_loop` | `hasattr(scanner, "run")` / `hasattr(scanner, "start")` 双分支 | 直接调用`scanner.start()` | scanner统一用start()接口 |
| `status_pusher` | 4个hasattr链(get_status/account/total_assets/available_cash/positions) | 直接调用`scanner.get_status()` | get_status()已存在且返回完整状态 |
| `_emergency_reduce_positions` | 直接访问`scanner._broker.get_positions()` + `scanner._is_limit_down()` | 用`scanner.get_positions()`统一接口 | 不应直接访问内部属性 |
| `_signal_to_dict` | `hasattr(sig, "__dataclass_fields__")` → `asdict()` | try/except TypeError + isinstance(dict) | 更Pythonic的EAFP模式 |
| `_cmd_update_params` | `hasattr(scanner, "update_strategy_params")` | 移除hasattr, 直接调用 | 方法已确认存在 |

### 42.3 🟡 except Exception收窄 (9处)

**scanner.py (7处)**:

| 位置 | 修复前 | 修复后 | 理由 |
|---|---|---|---|
| 回放数据加载 | `except Exception` | `except (ImportError, OSError, ValueError)` | 加载失败只可能这3种 |
| EventBus订阅器注册 | `except Exception` | `except (ImportError, AttributeError)` | 导入+属性错误 |
| 数据源关闭 | `except Exception` | `except (OSError, RuntimeError)` | close()只可能I/O或运行时错误 |
| 周末持仓检查 | `except Exception` | `except (RuntimeError, KeyError, ValueError)` | 检查逻辑错误类型有限 |
| 行情恢复尝试 | `except Exception` | `except (ConnectionError, OSError, TimeoutError)` | 网络恢复只可能连接错误 |
| pending_sells超时检查 | `except Exception` | `except (RuntimeError, KeyError, AttributeError)` | 风控检查错误类型有限 |
| quick check(risk线程) | `except Exception` | `except (RuntimeError, KeyError, TimeoutError, asyncio.TimeoutError)` | 超时+运行时错误 |

**scanner_daemon.py (2处)**:

| 位置 | 修复前 | 修复后 | 理由 |
|---|---|---|---|
| ACK监听器 | `except (json.JSONDecodeError, Exception)` | 分开: `json.JSONDecodeError` + `(KeyError, TypeError, AttributeError)` | ACK解析错误类型有限 |
| BLPOP主循环 | `except Exception` | 分开: `(ConnectionError, OSError, TimeoutError)` + `Exception` | 连接错误单独处理 |

### 42.4 变更文件

| 文件 | 变更 |
|---|---|
| scanner_daemon.py | 2个Bug修复+6处hasattr清理+2处except收窄 |
| scanner.py | 7处except收窄 |
| test_v2950_audit_fixes.py | 15新增测试 |
| docs/MARKET_MONITOR_OPTIMIZATION_DESIGN.md | v2.9.50记录 |

### 42.5 测试覆盖 (15新增)

| 测试类 | 用例数 | 覆盖点 |
|---|---|---|
| TestCmdUpdateParamsFix | 2 | 方法名修复+无scanner时warning |
| TestCmdScanFix | 1 | scan_once方法名修复 |
| TestCmdEmergencyLiquidateFix | 1 | 直接调用emergency_liquidate |
| TestRunScannerLoopFix | 1 | 直接调用start() |
| TestStatusPusherFix | 1 | 用get_status()替代hasattr链 |
| TestScannerExceptNarrowing | 4 | scanner.py 4处except收窄源码验证 |
| TestDaemonExceptNarrowing | 2 | daemon.py 2处except收窄源码验证 |
| TestNoBacktestRegression | 3 | 回测模块零影响 |

**全量测试**: 1152 passed (scanner 1101 + backtest 51)

### 42.6 回测影响

零。所有修改限于scanner_daemon.py(子进程IPC)和scanner.py的异常处理, 不影响回测引擎和sell_signal_checker。

---

## 四十三、v2.9.52 getattr/hasattr清理+DELEGATE_MAP外提 (2026-06-02)

### 43.1 getattr/hasattr防御消除(5文件)

内部dataclass(Order/Position/Account/ScanSignal)属性已知且有默认值,移除防御式编程:

| 文件 | 修改 | 原因 |
|------|------|------|
| broker.py | `o.fill_time`/`o.source`替代getattr | Order dataclass属性已知 |
| broker.py | `_last_save_time`在__init__初始化为0 | 消除hasattr检查 |
| position_manager.py | 新增`_extract_cost()`用isinstance替代hasattr | 区分Position对象和float值 |
| position_manager.py | `pos.strategy`/`signal.limit_up_count`直接访问 | dataclass属性已知 |
| runtime_persistence.py | `account.today_profit`/`account.total_assets` | Account dataclass属性已知 |
| strategy_scorer.py | `self.param_center._initialized`直接访问 | 内部属性已知 |
| risk_watchdog.py | `isinstance(buy_date, datetime)`替代hasattr | 类型判断更清晰 |

保留getattr的文件(外部对象/duck typing):
- `gm_broker.py`: 掘金SDK外部对象,属性不可预测
- `data_source_router.py`: duck typing检查adapter能力

### 43.2 DELEGATE_MAP外提

将67个委托映射从scanner.py移至scanner_delegate_router.py:

```
scanner.py: 1391行 → 1308行 (-83行)
scanner_delegate_router.py: 184行 → 271行 (+87行)
```

**设计决策**:
- `__getattr__`直接import DELEGATE_MAP(无运行时差异)
- `MarketScanner._DELEGATE_MAP`保留为`@classmethod@property`兼容别名(7个测试文件引用)
- 7个测试文件更新:源码字符串检查→运行时DELEGATE_MAP检查(更健壮)

### 43.3 测试

- 全量通过: 1177 passed, 1 skipped
- 回测零影响: 51 passed
- bare except残留: 0处
