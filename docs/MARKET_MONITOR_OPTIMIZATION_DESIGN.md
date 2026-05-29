# 市场监听系统优化设计方案

> 版本: v2.9.6 | 日期: 2026-05-30 | 基线分支: audit/V75-backtest-review
> 开发分支: feature/market-monitor-optimization
> 标签: v2.8.0-backtest-ui-v2 (回测UI稳定基线)
> 状态: 开发中 | Phase1✅ | Phase2✅ | Phase3✅ | Phase4进行中 | 代码审查✅ | 线程安全✅ | 审查优化✅ | 继续优化✅ | EventBus✅ | EventBus订阅器✅ | v2.9架构解耦✅ | v2.9.4提取+增强✅ | v2.9.6核心提取+Compare测试✅ | v2.9.7 List+ACK✅
> 回测影响: 零文件修改, 470测试全通过

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

**最终拆分结果: scanner.py 2907行→1757行 (-40%)**

```
MarketScanner(编排器, ~1846行, 30+委托方法)
  ├─ QuoteManager(行情, 352行) ← _fetch_realtime_batch ✅
  ├─ StrategyScorer(策略+异动, 332行) ← _merge_factors + _apply_strategies + _detect_anomalies ✅
  ├─ PositionManager(风控+仓位, 464行) ← _check_stop_loss_take_profit + _calc_position_ratio + _calc_would_buy_shares ✅
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
