# 市场监听系统优化设计方案

> 版本: v1.0 | 日期: 2026-05-28 | 分支: audit/V75-backtest-review
> 标签: v2.8.0-backtest-ui-v2 (回测UI稳定基线)
> 状态: 待开发

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
│  守护进程：自动重启、心跳、IPC桥接                      │
└───────────────────────┬─────────────────────────────┘
                        │ 内部调用
┌───────────────────────┴─────────────────────────────┐
│              MarketScanner (核心引擎, 2907行)          │
│  信号扫描 + 持仓管理 + 止损止盈 + 信号执行              │
└─────────────────────────────────────────────────────┘
```

### 1.2 核心代码量

| 模块 | 文件 | 行数 | 职责 |
|---|---|---|---|
| MarketScanner | scanner.py | 2907 | 信号扫描+持仓+风控+执行(全部耦合) |
| ScannerDaemon | scanner_daemon.py | 921 | 子进程守护 |
| LiveFilterPipeline | live_filter_pipeline.py | 645 | 9层过滤管道 |
| RiskWatchdog | risk_watchdog.py | 621 | 风控看门狗 |
| TieredScanner | tiered_scanner.py | 890 | 分级行情 |
| Broker | broker.py | 729 | 交易执行 |
| SignalDispatcher | signal_dispatcher.py | 333 | 信号分发 |
| StrategyParamCenter | strategy_param_center.py | 330 | 参数中心 |
| EmotionCycleManager | emotion_cycle.py | 323 | 情绪周期 |
| DataSourceRouter | data_source_router.py | 303 | 数据源路由 |
| ExecutionQuality | execution_quality.py | 327 | 执行质量 |
| 回测引擎 | portfolio_backtest.py | 4929 | 回测 |
| 卖出检查 | sell_signal_checker.py | 876 | 卖出信号(回测+PositionManager共用) |
| 策略默认参数 | strategy_defaults.py | 216 | 共享参数 |
| **总计** | | **9379** | |

### 1.3 回测-实盘代码关系(关键)

```
                    strategy_defaults.py (共享参数)
                   /          |          \
                  ▼           ▼           ▼
    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
    │  回测引擎      │  │  Scanner      │  │ PositionMgr  │
    │              │  │  (实盘扫描)    │  │ (实盘持仓)    │
    │              │  │              │  │              │
    │ sell_signal  │  │ ❌ 不用       │  │ ✅ 用         │
    │ _checker.py  │  │ 自行内嵌实现   │  │              │
    └──────────────┘  └──────────────┘  └──────────────┘
```

**核心问题**: Scanner的卖出逻辑是独立内嵌实现，与回测的sell_signal_checker.py是两套代码。
历史上V62审计让PositionManager对齐了sell_signal_checker，但Scanner自身的卖出逻辑仍未对齐。

### 1.4 P0问题清单

| # | 问题 | 影响 | 根因 |
|---|---|---|---|
| P0-1 | God Class 2907行 | 改一处坏全局 | 单一职责违反 |
| P0-2 | 盘中崩溃状态丢失 | 重启后风控失效 | 运行时状态无持久化 |
| P0-3 | 扫描和风控抢时间 | 止损延迟 | 风控无独立调度 |
| P0-4 | Redis Pub/Sub无保障 | 信号/状态丢失 | 无ACK机制 |
| P0-5 | 实盘-回测卖出逻辑分叉 | 回测结果不可信 | Scanner内嵌卖出逻辑 |

---

## 二、优化目标

1. **资金安全**: 盘中任何时刻崩溃，风控1秒内恢复；止损永远优先于扫描
2. **实盘-回测一致**: 卖出逻辑统一为sell_signal_checker.py，消除代码分叉
3. **消息可靠**: 信号和持仓变更不丢失
4. **数据不断**: 行情API故障时自动降级，风控不中断
5. **可维护性**: 逐步拆分God Class，清理死代码，补充测试

---

## 三、分阶段实施计划

### Phase 1: 资金安全保障 + 消除代码分叉（2周）

> 最高优先级，直接关系到资金安全

#### 1.1 持仓状态实时持久化（3天）

**目标**: Scanner每次状态变更立即写MongoDB，重启后1秒内恢复完整状态

**当前问题**:
- 持仓/追踪止损价/利润保护触发记录全在内存
- ScannerDaemon自动重启后，Scanner回到盘初状态
- 追踪止损丢失 → 持仓无保护 → 亏损放大

**设计方案**:

```python
# 新增 MongoDB 集合: scanner_position_snapshot
{
    "_id": "default",               # account_id
    "positions": [                   # 完整持仓列表
        {
            "ts_code": "600036.SH",
            "name": "招商银行",
            "shares": 300,
            "buy_price": 38.50,
            "buy_date": "20260528",
            "strategy": "dragon_head",
            "cost_price": 38.50,    # 含手续费
            "stop_loss_price": 37.35,  # 当前止损价(动态)
            "trailing_stop": {         # 追踪止损
                "highest_price": 41.20,
                "callback_pct": 0.025,
                "activated": True
            },
            "profit_protect": {        # 利润保护
                "triggered": False,
                "high_water_mark": 0,
                "callback_pct": 0.02
            },
            "profit_lock": {           # 利润锁定
                "triggered": False,
                "peak_profit_pct": 0,
                "callback_pct": 0.025
            },
            "hold_days": 3,
            "updated_at": "2026-05-28T10:30:00"
        }
    ],
    "emotion_state": {                  # 情绪仓位状态
        "score": 65,
        "phase": "differentiation",
        "position_ratio": 0.7
    },
    "circuit_breaker": {                # 熔断器状态
        "consecutive_losses": 2,
        "is_triggered": False
    },
    "updated_at": "2026-05-28T10:30:00",
    "trade_date": "20260528"
}
```

**修改文件**: `scanner.py`

```python
# 新增方法
async def _save_position_snapshot(self):
    """持仓状态变更后立即持久化"""
    snapshot = {
        "_id": self.account_id,
        "positions": [self._position_to_dict(p) for p in self.positions],
        "emotion_state": {...},
        "circuit_breaker": {...},
        "updated_at": datetime.now().isoformat(),
        "trade_date": self.trade_date,
    }
    await mongo_manager.db.scanner_position_snapshot.replace_one(
        {"_id": self.account_id}, snapshot, upsert=True
    )

# 修改 _load_positions()
async def _load_positions(self):
    """启动时从快照恢复完整状态(含追踪止损等)"""
    snapshot = await mongo_manager.db.scanner_position_snapshot.find_one(
        {"_id": self.account_id}
    )
    if snapshot and snapshot.get("trade_date") == self.trade_date:
        # 同一天内重启 → 完整恢复
        self.positions = self._restore_positions(snapshot["positions"])
        self._restore_trailing_stops(snapshot["positions"])
        self._restore_circuit_breaker(snapshot.get("circuit_breaker", {}))
        logger.info(f"从快照恢复 {len(self.positions)} 个持仓")
    else:
        # 新的一天 → 从Broker重建
        await self._load_positions_from_broker()

# 调用点(在以下方法末尾加 await self._save_position_snapshot())
#   - _execute_signals()     买入/卖出后
#   - _check_positions()     风控触发后
#   - _update_trailing_stops() 追踪止损更新后
```

**回测影响**: ❌ 无。纯实盘运行时状态，回测不读此集合。

**验证方法**:
1. 启动Scanner，买入一个信号
2. kill Scanner进程
3. ScannerDaemon自动重启
4. 确认持仓和追踪止损价位恢复正确

---

#### 1.2 风控独立线程（4天）

**目标**: 止损检查与信号扫描解耦，风控每1秒检查一次，不受扫描延迟影响

**当前问题**:
```python
# _scan_loop 伪代码
while market_open:
    scan_signals()        # 耗时2-8秒(API拉取+因子+策略)
    check_positions()     # 被延迟，止损可能晚几秒触发
    sleep(interval)       # 固定间隔
```

**设计方案**:

```python
class MarketScanner:
    def __init__(self):
        # ...existing...
        self._realtime_cache = {}        # 共享行情缓存
        self._realtime_cache_lock = asyncio.Lock()
        self._position_lock = asyncio.Lock()  # 持仓操作锁
        self._risk_task = None            # 风控协程
        self._scan_task = None            # 扫描协程

    async def start(self, trade_date=None):
        # ... 原有初始化 ...
        # 启动两个独立协程
        self._scan_task = asyncio.create_task(self._scan_loop(trade_date))
        self._risk_task = asyncio.create_task(self._risk_loop(trade_date))

    async def _scan_loop(self, trade_date: str):
        """信号扫描主循环(3-10秒一轮)"""
        while self._running:
            try:
                realtime_data = await self._fetch_realtime_batch()
                # 写入共享缓存
                async with self._realtime_cache_lock:
                    self._realtime_cache = realtime_data

                # 扫描逻辑(不变)
                merged_df = self._merge_factors(realtime_data)
                signals = await self._apply_strategies(merged_df, trade_date)
                filtered = await self._apply_filter_pipeline(signals, ...)
                await self._update_signals(filtered, ...)
                await self._push_signals(filtered)
                await self._execute_signals(filtered)

            except Exception as e:
                logger.error(f"扫描异常: {e}")

            interval = self._get_smart_scan_interval()
            await asyncio.sleep(interval)

    async def _risk_loop(self, trade_date: str):
        """风控独立循环(1秒一轮，优先级最高)"""
        while self._running:
            try:
                # 读共享行情缓存
                async with self._realtime_cache_lock:
                    realtime_data = dict(self._realtime_cache)  # 浅拷贝

                if not realtime_data:
                    await asyncio.sleep(0.5)
                    continue

                # 持仓风控检查(核心，优先级最高)
                async with self._position_lock:
                    sell_signals = await self._check_positions(realtime_data, trade_date)
                    if sell_signals:
                        await self._execute_sell_signals(sell_signals)
                        await self._save_position_snapshot()

            except Exception as e:
                logger.error(f"风控异常: {e}")

            await asyncio.sleep(1)  # 固定1秒间隔
```

**关键设计**:
- `_realtime_cache`: 行情数据共享，scan_loop写入，risk_loop读取
- `_position_lock`: 持仓变更互斥，防止scan和risk同时修改
- 风控循环1秒固定间隔，不受扫描耗时影响
- 风控循环异常不影响扫描，反之亦然

**回测影响**: ❌ 无。回测有自己的时间循环，不走asyncio多协程。

---

#### 1.3 Scanner卖出逻辑迁移到sell_signal_checker.py（5天）

> **最重要的改动——消除实盘-回测代码分叉**

**目标**: Scanner不再内嵌卖出逻辑，统一调用sell_signal_checker.py

**当前问题**:
```
Scanner._check_stop_loss_take_profit()  ← 独立实现
Scanner._check_positions()               ← 独立实现，含追踪止损/利润保护等
vs
sell_signal_checker.py check_early_sell() ← 回测和PositionManager共用

两套代码，参数和逻辑可能不同步
```

**设计方案**:

**Step 1: 在sell_signal_checker.py中增加优先级表和实时行情接口**

```python
# sell_signal_checker.py 新增

# 卖出原因优先级(数字越大越优先)
SELL_PRIORITY = {
    'stop_loss':          10,   # 固定止损
    'gap_stop_loss':       9,   # 跳空止损
    'trailing_stop':       8,   # 追踪止损
    'profit_lock':         7,   # 利润锁定
    'profit_protect':      6,   # 利润保护
    'pullback':            5,   # 冲高回落
    'high_open_sell':      4,   # 高开即卖
    'take_profit':         3,   # 止盈
    'dragon_head_low_profit': 3, # 龙头5天低利润
    'max_hold':            2,   # 到期
    'rebalance':           1,   # 调仓
    'force_empty':         0,   # 强制空仓
}

class SellSignalChecker:
    def __init__(self, strategy_config=None, realtime_data=None):
        # ... 原有初始化 ...
        self._realtime_data = realtime_data or {}   # 新增：实时行情数据

    def check_realtime_sell(self, position, realtime_price, high_price, open_price) -> Optional[Dict]:
        """
        实盘专用：检查单只持仓是否需要卖出
        与回测的check_early_sell()使用相同的核心逻辑

        Args:
            position: 持仓对象(含ts_code/shares/buy_price/strategy等)
            realtime_price: 当前实时价格
            high_price: 当日最高价(用于冲高回落)
            open_price: 当日开盘价(用于高开即卖)

        Returns:
            None 或 {'reason': 'trailing_stop', 'price': 39.50, 'priority': 8}
        """
        triggered = []

        # 1. 固定止损 (与回测逻辑一致)
        sl_result = self._check_fixed_stop_loss(position, realtime_price)
        if sl_result: triggered.append(sl_result)

        # 2. 追踪止损
        ts_result = self._check_trailing_stop(position, realtime_price)
        if ts_result: triggered.append(ts_result)

        # 3. 利润锁定
        pl_result = self._check_profit_lock(position, realtime_price)
        if pl_result: triggered.append(pl_result)

        # 4. 利润保护
        pp_result = self._check_profit_protect(position, realtime_price, high_price)
        if pp_result: triggered.append(pp_result)

        # 5. 冲高回落
        pb_result = self._check_pullback(position, realtime_price, high_price)
        if pb_result: triggered.append(pb_result)

        # 6. 高开即卖
        ho_result = self._check_high_open_sell(position, open_price)
        if ho_result: triggered.append(ho_result)

        # 7. 固定止盈
        tp_result = self._check_fixed_take_profit(position, realtime_price)
        if tp_result: triggered.append(tp_result)

        # 8. 持仓到期
        mh_result = self._check_max_hold(position)
        if mh_result: triggered.append(mh_result)

        if not triggered: return None

        # 按优先级排序，返回最高的
        triggered.sort(key=lambda x: SELL_PRIORITY.get(x['reason'], 0), reverse=True)
        return triggered[0]
```

**Step 2: Scanner._check_positions()改为调用sell_signal_checker**

```python
# scanner.py 修改
async def _check_positions(self, realtime_data, trade_date):
    """持仓风控检查(调用统一的sell_signal_checker)"""
    sell_signals = []
    for pos in list(self.positions):
        ts_code = pos.ts_code
        rt = realtime_data.get(ts_code, {})
        current_price = rt.get('price', 0)
        high_price = rt.get('high', 0)
        open_price = rt.get('open', 0)
        if current_price <= 0: continue

        checker = SellSignalChecker(
            strategy_config=self._get_effective_strategy_config(pos.strategy),
            realtime_data=realtime_data
        )
        result = checker.check_realtime_sell(
            position=pos, realtime_price=current_price,
            high_price=high_price, open_price=open_price
        )
        if result:
            sell_signals.append((pos, result['reason'], result.get('price', current_price)))
    return sell_signals
```

**Step 3: 删除Scanner中内嵌的卖出逻辑**

删除以下方法(功能已迁移到sell_signal_checker.py):
- `_check_stop_loss_take_profit()` → checker.check_realtime_sell()
- `_calc_stop_loss_price()` → checker._check_fixed_stop_loss()
- `_calc_take_profit_price()` → checker._check_fixed_take_profit()
- `_update_trailing_stops()` → 追踪止损状态改为在checker内部管理，通过持仓快照持久化

**Step 4: 回测验证**
```bash
# 运行基线回测，确认结果不变
# 期望: total_return差异 < 0.1%, 交易笔数相同, 卖出原因分布一致
```

**回测影响**: ✅ 正面。sell_signal_checker.py是回测自己的模块，Scanner开始共用它。

**验证方法**:
1. 跑一次回测基线(不改动scanner.py)，记录结果
2. 改完后跑同样的回测，确认sell_signal_checker.py的逻辑未变
3. 实盘模式启动Scanner，观察卖出信号是否与预期一致
4. 对比同一天Scanner和回测对同一持仓的卖出判断

---

### Phase 2: 可靠性提升（2-3周）

#### 2.1 Redis通信升级（4天）

**目标**: 信号和持仓变更不丢失

| 通道 | 当前 | 改为 | 原因 |
|---|---|---|---|
| scanner:status | Pub/Sub | Pub/Sub | 允许丢，1秒后还有下一帧 |
| scanner:signal | Pub/Sub | **Redis Stream** | 不可丢，低频但关键 |
| scanner:position | Pub/Sub | **Redis Stream** | 持仓变更不可丢 |
| scanner:cmd | Pub/Sub | **List + ACK** | 命令必须确认 |
| scanner:health | Pub/Sub | Pub/Sub | 看门狗心跳，允许丢 |

```python
# 信号推送改用Stream
async def _push_signals(self, signals):
    for sig in signals:
        await redis_manager.redis.xadd(
            "scanner:signal",
            {"data": json.dumps(self._signal_to_dict(sig))}
        )

# Web Node消费端用消费组
async def consume_signals():
    while True:
        entries = await redis_manager.redis.xreadgroup(
            "scanner_signal_group", "web-node-1",
            {"scanner:signal": ">"}, count=10, block=1000
        )
        for stream, messages in entries:
            for msg_id, data in messages:
                await process_signal(data)
                await redis_manager.redis.xack("scanner:signal", "scanner_signal_group", msg_id)
```

**回测影响**: ❌ 无。回测不经过Redis。

---

#### 2.2 行情数据降级策略（3天）

**目标**: 量脉故障时自动切换东财，风控不中断

```
正常模式:  量脉实时(120/min) ──→ 全功能扫描+风控
           │ 429或超时3次
降级模式1: 东财实时快照(3秒/次, 无限流) ──→ 风控正常，扫描延迟~5秒
           │ 连续失败3次
降级模式2: 东财日线缓存(收盘价) ──→ 只做止损检查，不生成新信号
           + 前端黄色警告"行情降级模式"
```

```python
class QuoteManager:
    def __init__(self):
        self._degrade_level = 0      # 0=正常, 1=东财实时, 2=东财日线
        self._fail_count = 0
        self._last_quote_ts = 0

    async def fetch_realtime(self, codes: List[str]) -> Dict:
        if self._degrade_level == 0:
            try:
                data = await self._fetch_liangmai(codes)
                self._fail_count = 0
                self._last_quote_ts = time.time()
                return data
            except Exception:
                self._fail_count += 1
                if self._fail_count >= 3:
                    self._degrade_level = 1
                    logger.warning("量脉连续3次失败，降级到东财实时")
        if self._degrade_level == 1:
            try:
                data = await self._fetch_eastmoney_rt(codes)
                self._last_quote_ts = time.time()
                return data
            except Exception:
                self._degrade_level = 2
                logger.warning("东财实时失败，降级到日线缓存")
        # Level 2: 日线缓存
        data = await self._fetch_eastmoney_daily_cache(codes)
        self._last_quote_ts = time.time()
        return data

    def is_degraded(self) -> bool: return self._degrade_level > 0
    def is_severely_degraded(self) -> bool: return self._degrade_level >= 2
    def get_staleness(self) -> int:
        """行情数据陈旧度(秒)"""
        return int(time.time() - self._last_quote_ts) if self._last_quote_ts else 999
```

**回测影响**: ❌ 无。回测从MongoDB读历史数据。

---

#### 2.3 参数单一权威来源（2天）

**目标**: 消除三层fallback导致的配置漂移

**启动流程(修改后)**:
1. 读MongoDB(ParamCenter)
2. 对比strategy_defaults.py，缺失的字段补全
3. 补全后写回MongoDB
4. 之后运行时只读MongoDB，不再有fallback路径
5. 启动时检测配置差异，有差异则告警

```python
class StrategyParamCenter:
    async def ensure_complete(self):
        """启动时确保MongoDB参数完整，缺失的从strategy_defaults.py补全"""
        defaults = self._load_defaults()
        for strategy_key, config in defaults.items():
            existing = await self._db.find_one({"strategy": strategy_key})
            if not existing:
                await self._db.insert_one({"strategy": strategy_key, **config})
                logger.info(f"参数补全: {strategy_key}")
            else:
                new_fields = set(config.keys()) - set(existing.keys())
                if new_fields:
                    await self._db.update_one(
                        {"strategy": strategy_key},
                        {"$set": {k: config[k] for k in new_fields}}
                    )
                    logger.info(f"参数新字段补全: {strategy_key} +{new_fields}")

    async def detect_drift(self) -> List[str]:
        """检测MongoDB与strategy_defaults.py的差异"""
        drifts = []
        defaults = self._load_defaults()
        for strategy_key, config in defaults.items():
            existing = await self._db.find_one({"strategy": strategy_key})
            if existing:
                for k, v in config.items():
                    if k in existing and existing[k] != v:
                        drifts.append(f"{strategy_key}.{k}: MongoDB={existing[k]}, defaults={v}")
        return drifts
```

**回测影响**: ⚠️ 轻度。回测在无MongoDB环境下仍读strategy_defaults.py，不受影响。

---

#### 2.4 情绪仓位动态调整（3天）

**目标**: 情绪降级时已有仓位按比例减仓

```python
class EmotionCycleManager:
    PHASE_TRANSITIONS = {
        ('climax', 'differentiation'): 'reduce_new_signals',  # 新信号降仓
        ('differentiation', 'chaos'):   'reduce_existing',     # 已有仓位减30%
        ('chaos', 'freezing'):          'sell_low_profit',     # 低利润清仓
    }

    async def on_phase_change(self, old_phase, new_phase, score):
        transition = (old_phase, new_phase)
        action = self.PHASE_TRANSITIONS.get(transition)
        if action == 'reduce_new_signals': pass  # 已有逻辑
        elif action == 'reduce_existing':
            await self._reduce_positions_to_ratio(new_phase)
        elif action == 'sell_low_profit':
            await self._sell_low_profit_positions(threshold=0.03)
```

**回测影响**: ⚠️ 需要同步。回测也有情绪周期逻辑，必须加上相同的动态调仓才能对齐。
**同步方案**: 在portfolio_backtest.py的_rebalance()中加入相同的phase transition检查。

---

### Phase 3: 架构治理（3-4周）

#### 3.1 God Class拆分（2周）

**拆分方案**:

```
MarketScanner(编排器，~300行)
  ├─ QuoteManager(行情管理，~400行)        ← 从_fetch_realtime_batch拆出
  ├─ FactorEngine(因子合并，~300行)        ← 从_merge_factors拆出
  ├─ StrategyScorer(策略打分，~500行)      ← 从_apply_strategies拆出
  ├─ FilterPipeline(过滤管道，~400行)      ← 从_apply_filter_pipeline拆出
  ├─ PositionManager(持仓风控，~600行)     ← 从_check_positions拆出
  └─ OrderExecutor(订单执行，~300行)       ← 从_execute_signals拆出
```

**拆分原则**:
- 每个模块独立文件，放在`nodes/market_monitor/scanner_modules/`目录
- 通过MarketScanner实例传递共享状态(realtime_cache, positions等)
- 逐步拆分，每次拆一个模块，跑回测验证
- 优先拆PositionManager(已在Phase 1.3中完成逻辑迁移)
- 不改sell_signal_checker.py和strategy_defaults.py的import路径

**回测影响**: ⚠️ 需注意。确保共享模块的路径不变。

---

#### 3.2 死代码清理（1天）

删除以下目录/文件(已确认0外部引用):
```
rm -rf core/managers/live/_deprecated/           # 8模块 6650行
rm -rf nodes/listener/                            # 3912行(V54已废弃)
rm nodes/backtest_engine/factor_selection/strategy_defaults.py.bak
rm nodes/backtest_engine/factor_selection/portfolio_backtest.py.bak
```

**回测影响**: ❌ 无。

---

#### 3.3 核心模块测试（1周）

| 模块 | 用例数 | 方法 |
|---|---|---|
| sell_signal_checker.py | 30+ | 用录制的真实行情数据做fixture |
| FilterPipeline | 20+ | 每层过滤器各3-5个测试 |
| StrategyScorer | 15+ | 4策略各3-4个典型场景 |
| QuoteManager降级 | 8+ | 模拟API失败 |
| 端到端集成 | 5+ | 信号→执行→风控 |

```python
# 测试示例
def test_trailing_stop_triggered():
    """追踪止损: 最高价41.20，回调2.5%触发线=40.17，当前40.10 → 触发"""
    checker = SellSignalChecker(strategy_config={...})
    position = MockPosition(buy_price=38.50, trailing_highest=41.20)
    result = checker.check_realtime_sell(position, realtime_price=40.10, ...)
    assert result['reason'] == 'trailing_stop'
    assert result['priority'] == 8

def test_stop_loss_beats_take_profit():
    """优先级: 同时触发止损和止盈，止损优先"""
    result = checker.check_realtime_sell(position, ...)
    assert result['reason'] == 'stop_loss'  # 优先级10 > 止盈优先级3
```

**回测影响**: ✅ 正面。

---

#### 3.4 审计日志（3天）

**新增 MongoDB 集合: audit_log (append-only)**

```python
{
    "timestamp": "2026-05-28T10:30:00",
    "event_type": "stop_triggered",       # signal_generated / order_submitted / order_filled / stop_triggered
    "ts_code": "600036.SH",
    "stock_name": "招商银行",
    "strategy": "dragon_head",
    "price": 37.35,
    "quantity": 300,
    "reason": "trailing_stop",
    "reason_detail": "最高价41.20, 回调2.5%=40.17, 当前37.35",
    "emotion_score": 65,
    "emotion_phase": "differentiation",
    "params_snapshot": {"stop_loss_pct": 0.03, "trailing_callback_pct": 0.025},
    "scanner_version": "v2.8.0",
}
```

- 索引: `(timestamp, ts_code, event_type)`
- TTL: 90天自动过期
- 不可修改(应用层保护，无update API)
- 前端可查询某只股票的完整交易链路

**回测影响**: ❌ 无。

---

### Phase 4: 运维体验（1-2周）

#### 4.1 前端状态管理统一（1周）

- WebSocket为主通道，REST为fallback
- 新增Pinia Store: `useScannerStore()`
- 数据新鲜度: 3秒内=绿, 5秒内=黄, >5秒=红
- WS断线自动重连 + 重连后全量同步

**回测影响**: ❌ 无。

---

#### 4.2 构建部署自动化（2天）

- package.json增加 `deploy` 脚本: build + sync + 重启web
- .gitignore添加 `AgentServer/static/assets/`
- 健康检查API返回构建版本号(git hash)

**回测影响**: ✅ 正面。

---

## 四、回测影响汇总

| Phase | 改动 | 回测影响 | 处理方式 |
|---|---|---|---|
| 1.1 | 持仓持久化 | ❌ 无 | — |
| 1.2 | 风控独立线程 | ❌ 无 | — |
| 1.3 | 卖出逻辑迁移 | ✅ 正面 | Scanner共用回测的checker，消除分叉 |
| 2.1 | Redis升级 | ❌ 无 | — |
| 2.2 | 行情降级 | ❌ 无 | — |
| 2.3 | 参数单一来源 | ⚠️ 轻度 | 回测仍读strategy_defaults.py |
| 2.4 | 情绪动态调仓 | ⚠️ 需同步 | 回测也要加相同的动态调仓 |
| 3.1 | God Class拆分 | ⚠️ 需注意 | 不改共享模块的import路径 |
| 3.2 | 死代码清理 | ❌ 无 | — |
| 3.3 | 核心测试 | ✅ 正面 | — |
| 3.4 | 审计日志 | ❌ 无 | — |
| 4.1 | 前端状态统一 | ❌ 无 | — |
| 4.2 | 构建自动化 | ✅ 正面 | — |

**核心原则**: 每次改动后跑一次回测基线，确认total_return差异 < 0.1%

---

## 五、实施时间线

```
Week 1-2:  Phase 1 (资金安全)
  Day 1-3:   1.1 持仓状态持久化
  Day 4-7:   1.2 风控独立线程
  Day 8-12:  1.3 卖出逻辑迁移(含回测验证)

Week 3-5:  Phase 2 (可靠性)
  Day 13-16: 2.1 Redis通信升级
  Day 17-19: 2.2 行情降级策略
  Day 20-21: 2.3 参数单一来源
  Day 22-24: 2.4 情绪动态调仓(含回测同步)

Week 6-9:  Phase 3 (架构治理)
  Day 25-38: 3.1 God Class拆分(逐模块)
  Day 39:    3.2 死代码清理
  Day 40-46: 3.3 核心模块测试
  Day 47-49: 3.4 审计日志

Week 10-11: Phase 4 (运维)
  Day 50-56: 4.1 前端状态统一
  Day 57-58: 4.2 构建部署自动化
```

---

## 六、验收标准

| Phase | 验收项 |
|---|---|
| Phase 1 | ① kill Scanner进程后重启，持仓+追踪止损1秒内恢复 ② 风控循环独立1秒间隔，扫描卡顿不影响 ③ 回测基线差异 < 0.1% |
| Phase 2 | ① Redis重启后信号不丢(Stream持久化) ② 量脉429后自动切东财，前端显示降级状态 ③ 参数漂移检测有告警 |
| Phase 3 | ① MarketScanner < 400行 ② 测试覆盖30+用例 ③ 审计日志可查完整交易链路 |
| Phase 4 | ① WS断线3秒内重连+全量同步 ② npm run deploy一键部署 |

---

## 七、风险与回退

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| 卖出逻辑迁移后回测结果不一致 | 中 | 高 | 迁移前跑基线，迁移后逐笔对比卖出原因 |
| 风控独立线程引入并发bug | 中 | 高 | 加持仓锁，单线程测试通过后再上线 |
| God Class拆分引入import错误 | 低 | 中 | 逐步拆分，每步跑回测验证 |
| 情绪动态调仓导致过度交易 | 中 | 中 | 先用保守参数(减仓比例20%而非30%)，观察1周 |

**回退基线**: `git checkout v2.8.0-backtest-ui-v2` 可回到当前稳定版本
