# 市场监听系统优化设计方案

> 版本: v2.4 | 日期: 2026-05-29 | 基线分支: audit/V75-backtest-review
> 开发分支: feature/market-monitor-optimization
> 标签: v2.8.0-backtest-ui-v2 (回测UI稳定基线)
> 状态: 开发中 | Phase1✅ | Phase2✅ | Phase3✅ | Phase4✅ | 代码审查✅ | 线程安全✅
> 回测影响: 零文件修改(仅portfolio_backtest补充0交易策略字段), 65测试全通过

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
| MarketScanner | scanner.py | 1846 | 信号扫描+持仓+风控+执行(委托模式) |
| ScannerDaemon | scanner_daemon.py | 921 | 子进程守护 |
| LiveFilterPipeline | live_filter_pipeline.py | 645 | 9层过滤管道 |
| RiskWatchdog | risk_watchdog.py | 621 | 风控看门狗 |
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

**最终拆分结果: scanner.py 3348行→1846行 (-45%)**

```
MarketScanner(编排器, ~1846行, 30+委托方法)
  ├─ QuoteManager(行情, 352行) ← _fetch_realtime_batch ✅
  ├─ StrategyScorer(策略, 248行) ← _merge_factors + _apply_strategies ✅
  ├─ PositionManager(风控, 356行) ← _check_stop_loss_take_profit ✅
  ├─ PositionChecker(卖出, 497行) ← _check_positions(legacy/checker/compare) ✅
  ├─ SignalManager(信号, 382行) ← _update_signals + _execute_signals ✅
  ├─ ScannerUtils(工具, 274行) ← _safe_round + _publish + 序列化 + 报告 ✅
  ├─ RuntimePersistence(持久化, 268行) ← 快照/时间线/链路追踪/盘前竞价 ✅
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
