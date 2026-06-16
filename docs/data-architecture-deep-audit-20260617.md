# 市场监听数据架构深度审查报告
> 2026-06-17 | 账户已重置，零持仓零交易状态

---

## 一、数据全景：3层 × 4类 × 27个集合

### 3层数据架构

```
┌─────────────────────────────────────────────────────┐
│                    前端 (7个Tab)                      │
│  AccountTab  AnalysisTab  ReviewTab  OpsTab          │
│  SentimentTab  ScanTraceTab  PremarketTab            │
│     │            │           │         │              │
│     ├─useUnified  ├─useScannerMonitor  ├─useScanner  │
│     │  (3 API)    │  (12+ API)          │  (8+ API)  │
└─────┼─────────────┼─────────────────────┼────────────┘
      │             │                     │
┌─────┼─────────────┼─────────────────────┼────────────┐
│     ▼             ▼                     ▼            │
│  12个 API 端点 (FastAPI)                              │
│  /unified/*  /scanner/*  /market/*                    │
│     │             │                     │            │
│     ├─ broker_orders (真相源)                         │
│     ├─ broker_positions (真相源)                      │
│     ├─ broker_accounts (缓存)                         │
│     └─ scanner_timeline (决策日志)                    │
└─────┼───────────────────────────────────────────────┘
      │
┌─────┼───────────────────────────────────────────────┐
│     ▼                                                │
│  MongoDB (stock_agent)                               │
│  27个集合, 5,628,523条记录                            │
│                                                      │
│  ┌─ 交易真相源 ─────────────────────┐               │
│  │ broker_orders    (0条, 重置后)   │               │
│  │ broker_positions (0条, 重置后)   │               │
│  │ broker_accounts  (2条, 含test)   │               │
│  └──────────────────────────────────┘               │
│  ┌─ 业务日志 ──────────────────────┐               │
│  │ scanner_timeline (0条)           │               │
│  │ scan_traces      (3,471条)       │               │
│  │ audit_log        (3,734条)       │               │
│  │ sentiment_scores (518条)         │               │
│  │ param_snapshots  (16条)          │               │
│  │ performance_snapshots            │               │
│  └──────────────────────────────────┘               │
│  ┌─ 行情数据 ──────────────────────┐               │
│  │ stock_daily_ak_full (2.75M)      │               │
│  │ daily_basic         (2.79M)      │               │
│  │ limit_list          (55K)        │               │
│  │ stock_basic         (6,155)      │               │
│  │ index_daily         (2,008)      │               │
│  └──────────────────────────────────┘               │
│  ┌─ 配置/状态 ─────────────────────┐               │
│  │ scanner_config, strategy_params  │               │
│  │ scanner_runtime_snapshot         │               │
│  │ scanner_state, system_config     │               │
│  └──────────────────────────────────┘               │
└──────────────────────────────────────────────────────┘
```

---

## 二、核心数据通路详解

### 2.1 交易写入链路（最关键）

```
信号触发 (signal_manager.py)
  │
  ├─ _post_buy_success() ─→ Broker.place_order()
  │                          │
  │                          ├─ Broker._execute_buy()
  │                          │    ├─ 更新内存 Account (扣现金)
  │                          │    ├─ 更新内存 Position (新建/加仓)
  │                          │    └─ 创建 Order 对象
  │                          │
  │                          └─ save_state(force=True)  ← 异步! 不保证完成
  │                               ├─ broker_orders.upsert (by order_id)
  │                               ├─ broker_positions.upsert (by ts_code)
  │                               └─ broker_accounts.update (整份覆盖)
  │
  └─ scanner_timeline.append("buy") ← 内存追加
       └─ save_timeline() ← 只写blocked, buy/sell被过滤(v2.9.97c)
```

**⚠️ 关键风险：`save_state(force=True)` 是 `create_task` 异步的**

```python
# broker.py line 715
loop.create_task(self.save_state(force=True))
```

这意味着：
- 进程在 `create_task` 后、`save_state` 执行前崩溃 → 交易丢失
- 000608 事故就是因此：崩溃时持仓全部丢失

### 2.2 持仓读取链路（3条不同路径）

```
┌─────────────────────────────────────────────────────┐
│                    前端需要持仓                        │
│                                                      │
│   ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
│   │ AccountTab│  │AnalysisTab│  │useScannerMonitor │  │
│   │          │  │          │  │  (4个Tab共用)      │  │
│   └────┬─────┘  └────┬─────┘  └────────┬─────────┘  │
│        │              │                  │            │
│        ▼              ▼                  ▼            │
│   /analysis      /analysis        /scanner/all       │
│        │              │                  │            │
│        ▼              ▼                  ▼            │
│   broker_positions  broker_positions  scanner内存     │
│   + broker_orders   + broker_orders   + broker_positions│
│   + broker_accounts + broker_accounts (一致性检查)     │
│                                                      │
│   ✅ v2.9.97统一后   ✅ 同左         ⚠️ 仍以内存为主 │
└─────────────────────────────────────────────────────┘
```

**问题：3条路径读3个不同数据源，字段可能不一致**

| 字段 | /analysis | /unified/positions | /all (scanner内存) |
|------|-----------|-------------------|-------------------|
| shares | ✅ | ✅ | ✅ |
| profit_pct | ✅ 重算 | ✅ 重算 | ⚠️ 内存缓存 |
| stop_loss_price | ✅ 从策略算 | ✅ 从策略算 | ✅ 内存字段 |
| risk_monitor | ✅ 实查 | ❌ 无 | ✅ 内存字段 |
| current_price | ✅ broker>历史close | ✅ broker>历史close | ⚠️ scanner缓存 |

### 2.3 现价(current_price)更新链路

```
盘中:
  量脉API / 东财API → QuoteManager.fetch_realtime_batch()
    → _realtime_cache (内存dict)
    → scanner._realtime_prices.get(ts_code)
    → broker.Position.current_price (内存)
    → save_state → broker_positions.current_price (MongoDB)

收盘后:
  scanner._refresh_close_prices()
    → stock_daily_ak_full.find_one(close)
    → broker.Position.current_price (内存)
    → save_state → broker_positions.current_price (MongoDB)

API读取:
  broker_positions.current_price > 0 ? 用它 : stock_daily_ak_full.close
```

**问题：盘中实时价格依赖scanner运行。scanner未运行时，所有持仓的current_price是0或旧值，API fallback到历史close——这可能是几天前的价格。**

---

## 三、存在的7个问题

### 🔴 P0：save_state 异步不保证持久化

**位置**：`broker.py:715`
```python
loop.create_task(self.save_state(force=True))
```

**风险**：进程崩溃时，已执行的交易可能未写入MongoDB。
**历史事故**：000608止损事故——scanner崩溃→save_state未执行→持仓全丢→7只持仓无人止损→亏¥36,362。

**根因**：Python的`create_task`只是把协程加入事件循环，不保证在下一个await点之前执行完。如果进程在`create_task`和实际MongoDB写入之间被kill，数据就丢了。

**修复难度**：中。需要在`place_order`中做同步MongoDB写入（不依赖事件循环）。

### 🔴 P0：持仓数据3源不一致

**现状**：
| 数据源 | 用途 | 读路径 |
|--------|------|--------|
| scanner内存 | `/all`主路径 | `scanner.get_positions()` |
| broker_positions | `/analysis`, `/unified` | MongoDB直读 |
| broker_accounts | `/account`缓存 | MongoDB直读 |

**不一致场景**：
- scanner买入后save_state未完成 → scanner内存有但MongoDB没有
- scanner崩溃后重启 → 内存清空，但MongoDB有旧数据
- `/all`有幽灵持仓检测，但其他端点没有

**修复方向**：所有持仓查询统一走`/unified/positions`，废弃scanner内存持仓读取。

### 🟡 P1：current_price 盘后过期

**现状**：scanner未运行时，`broker_positions.current_price`停在最后一次save_state的值。

**场景**：
- 周五收盘scanner停止
- 周末查看持仓 → current_price是周五收盘价
- 周一开盘前查看 → current_price仍是周五收盘价
- API fallback到stock_daily_ak_full → 也是周五收盘价（正确但不够实时）

**影响**：盈亏计算依赖current_price，过时价格导致盈亏显示错误。

**修复方向**：非交易时间用stock_daily_ak_full的最新close作为current_price，不需要scanner运行。

### 🟡 P1：前端3份持仓数据冗余

**现状**：
```
useScannerMonitor.positions ← /scanner/all (scanner内存)
useUnifiedData.positions    ← /unified/positions (MongoDB)
AccountTab.positions        ← /scanner/analysis (MongoDB)
```

3个composable各自维护一份持仓ref，数据可能不同步。

**修复方向**：所有Tab统一使用useUnifiedData.positions，删除useScannerMonitor中的positions ref。

### 🟡 P1：broker_accounts 是不可信缓存

**现状**：`broker_accounts`存储的是某次save_state时的快照：
- `position_count`可能是错的（v2.9.97c修复为从broker_positions实查）
- `market_value`基于当时的current_price，过时
- `total_profit`累加逻辑可能和broker_orders不一致

**修复方向**：broker_accounts应改为从broker_orders + broker_positions实时计算，不再做缓存。或者只在save_state时更新，读取时明确标注"快照时间"。

### 🟡 P2：trade_date 类型不统一

**现状**：MongoManager写入归一化（v2.9.95d）确保新数据为int，但历史数据可能是string。

**已修复**：unified.py和scanner_trading.py已用$or兼容两种格式。
**残留风险**：其他端点（如scanner_report.py）可能仍有$gte/$lte单类型查询。

### 🟢 P3：scanner_timeline 职责已收窄但旧数据未清理

**现状**：v2.9.97c后只写blocked决策日志，buy/sell从broker_orders恢复。但历史70条buy/sell记录仍在MongoDB中。

**影响**：无功能影响，但可能误导开发者以为timeline仍存交易。

---

## 四、数据写入时序图

```
时间 ──────────────────────────────────────────────→

买入信号触发:
  t0: signal_manager._post_buy_success()
  t1: broker.place_order() → 内存 Account/Position/Order 更新
  t2: create_task(save_state(force=True)) ← 异步!
  t3: scanner._timeline.append({action:"buy"}) ← 内存
  t4: [异步] save_state → broker_orders.upsert ✅
  t5: [异步] save_state → broker_positions.upsert ✅
  t6: [异步] save_state → broker_accounts.update ✅
  
  ⚠️ 如果进程在 t2~t4 之间崩溃:
     - 内存有交易记录 (但进程已死)
     - MongoDB没有交易记录
     - 重启后交易丢失！

卖出信号触发:
  同上结构, 但还额外:
  t7: scanner._timeline.append({action:"sell"}) ← 内存
  t8: [异步] save_timeline → scanner_timeline (只写blocked, sell被过滤)

风控止损触发:
  t0: position_checker._check_risk() 
  t1: _execute_sell_list() → broker.execute_sell()
  t2: 同买入流程 (内存更新 + 异步save_state)
  
  ⚠️ 风控线程是独立的, 与扫描循环并发
  ⚠️ 风控线程的save_state可能与扫描循环的save_state竞争
  ⚠️ save_state有30秒节流(force=False时), 可能丢失中间状态
```

---

## 五、前端数据源映射（7个Tab × 数据来源）

| Tab | 持仓 | 交易 | 账户 | KPI/风控 | 实时更新 |
|-----|------|------|------|----------|----------|
| **AccountTab** | /analysis | /unified/trades | /analysis | /analysis | 手动刷新 |
| **AnalysisTab** | /analysis | /unified/trades | - | /analysis | 手动刷新 |
| **ReviewTab** | - | /scanner/review/* | - | - | 手动刷新 |
| **OpsTab** | /scanner/all | /scanner/all | /scanner/all | /scanner/all | WS+轮询 |
| **SentimentTab** | - | - | - | /scanner/sentiment | WS+轮询 |
| **ScanTraceTab** | - | - | - | /scanner/scan-traces | WS+轮询 |
| **PremarketTab** | - | - | - | /scanner/premarket | 手动刷新 |

**问题**：
- AccountTab持仓来自`/analysis`，OpsTab持仓来自`/all` → 数据源不同
- 只有OpsTab/SentimentTab/ScanTraceTab有WS实时更新
- AccountTab/AnalysisTab/ReviewTab依赖手动刷新
- 同一个页面可能同时发5+个API请求（如AnalysisTab: /analysis + /unified/trades + /analysis/stock/{code}）

---

## 六、修复优先级路线图

### Phase 1: 紧急（本周）
1. **save_state同步化**：买入/卖出后同步写MongoDB，不依赖create_task
2. **前端统一数据源**：所有Tab持仓统一用useUnifiedData，删除冗余ref

### Phase 2: 重要（下周）
3. **current_price自动刷新**：非交易时间从stock_daily_ak_full取最新close
4. **broker_accounts改为实时计算**：不再做缓存，从broker_positions+broker_orders重算
5. **scanner_timeline历史数据清理**：删除70条buy/sell记录

### Phase 3: 优化（后续）
6. **API请求合并**：前端Tab切换时避免重复请求同一数据
7. **trade_date全量归一化**：一次性脚本把所有string转int
8. **WS推送扩展**：AccountTab/AnalysisTab也接入WS实时更新
