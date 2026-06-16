# StockAgent 数据架构完整梳理
> 2026-06-21 21:10 | 触发：持仓数据不一致 + 数据源混乱

---

## 一、问题全景

**当前状态**：同一笔交易的数据散落在 3 个地方（内存 + 2个MongoDB集合），6个API端点各选不同数据源读取，没有统一规则。

**后果**：
- 15只持仓 vs 10笔交易 vs 昨日6只应卖未卖 — 前端Tab之间数据打架
- broker_orders 说卖了，scanner_timeline 还在说持有 → 界面混乱
- 修一个端点漏三个 → 永远修不完

---

## 二、数据集合职责定义（唯一真相源体系）

### 🟢 第一层：交易真相源 — broker_*

| 集合 | 职责 | 唯一写入者 | 读取消费者 |
|------|------|-----------|-----------|
| `broker_orders` | 成交记录（买/卖） | `broker.execute_buy()` / `execute_sell()` | 所有需要交易数据的API |
| `broker_positions` | 当前持仓快照 | `broker.save_state()` / `runtime_persistence` | 所有需要持仓的API |
| `broker_accounts` | 账户资金快照 | `broker.save_state()` | `/account` (资金部分) |

**规则**：
- ✅ broker_orders 是 buy/sell 的**唯一真相源**
- ✅ broker_positions 是持仓的**唯一真相源**
- ⚠️ broker_accounts.position_count **不可信**（可能为0），持仓数量从 broker_positions 实查

### 🟡 第二层：决策日志 — scanner_timeline

| 集合 | 职责 | 写入者 | 读取消费者 |
|------|------|--------|-----------|
| `scanner_timeline` | 决策日志（blocked/rejected） | `runtime_persistence.save_timeline()` | `/timeline/history` (OpsTab) |

**规则**：
- ✅ 只写 blocked/rejected 等非交易决策
- ❌ **不再写 buy/sell**（v2.9.97c起）
- 历史遗留的 buy/sell 保留但不再新增

### 🔵 第三层：扫描追踪 — scan_traces

| 集合 | 职责 | 写入者 | 读取消费者 |
|------|------|--------|-----------|
| `scan_traces` | 每轮扫描的候选→9层过滤→通过/拦截 | `runtime_persistence.save_scan_traces()` | ScanTraceTab, 执行质量 |

### 🔴 第四层：行情数据 — stock_daily_ak_full / daily_basic / limit_list

| 集合 | 职责 | 来源 |
|------|------|------|
| `stock_daily_ak_full` | 日线OHLCV | 东财API / AKShare |
| `daily_basic` | PE/PB/换手率/市值 | 东财API / AKShare |
| `limit_list` | 涨跌停/炸板 | 东财API |
| `stock_basic` | 股票基础信息 | AKShare |
| `index_daily` | 指数日线 | AKShare |

---

## 三、数据写入路径 — 谁在写什么

### 交易执行（唯一入口）
```
信号触发 / 手动下单
    │
    ▼
broker.place_order()
    ├─ broker_orders.insert()     ← 成交记录
    ├─ broker_positions.update()  ← 持仓更新（内存）
    ├─ broker_accounts.update()   ← 资金更新（内存）
    └─ scanner._timeline.append() ← 内存时间线（运行时）
         │
         ▼ (save_timeline)
    scanner_timeline.insert()     ← 只写 blocked 等决策
```

### 定期持久化
```
scanner.stop() / risk_loop / 定时save
    │
    ▼
runtime_persistence.save_state()
    ├─ broker_orders → MongoDB
    ├─ broker_positions → MongoDB
    └─ broker_accounts → MongoDB
```

### 启动恢复
```
scanner.start()
    │
    ▼
runtime_persistence.load_state()
    ├─ broker_orders → MongoDB (read)
    ├─ broker_positions → MongoDB (read)
    ├─ broker_accounts → MongoDB (read)
    └─ load_timeline()
         ├─ scanner_timeline → 只读 blocked
         └─ broker_orders → 读 buy/sell → 恢复到内存timeline
```

---

## 四、数据读取路径 — 前端Tab到MongoDB

### AccountTab（账户+持仓+风控）
```
AccountTab.vue
  └─ fetchAccount() → GET /scanner/analysis?period=30d
       └─ scanner_analysis.py::get_analysis()
            ├─ broker_orders → KPI (total_trades, win_rate, profit_loss_ratio)
            ├─ broker_orders → daily_detail (每日交易明细)
            ├─ broker_positions → positions (持仓列表+止损状态)
            └─ broker_accounts → account (资金)
```

### AnalysisTab（分析）
```
AnalysisTab.vue
  └─ inject('scanner-monitor')
       └─ useScannerMonitor → GET /scanner/analysis
            └─ 同 AccountTab 数据源
```

### ReviewTab（复盘+逐笔归因）
```
ReviewTab.vue
  └─ inject('scanner-monitor')
       └─ useReviewMonitor
            ├─ GET /unified/trades?date=X → broker_orders (buy+sell配对)
            ├─ GET /scanner/discipline-check → scan_traces
            └─ GET /scanner/daily-report → broker_orders + sentiment_scores
```

### OpsTab（操作+时间线）
```
OpsTab.vue
  └─ inject('scanner-monitor')
       ├─ GET /scanner/timeline/history
       │    ├─ scanner_timeline → blocked 记录
       │    └─ broker_orders → buy/sell 记录
       └─ GET /scanner/trade-audit → broker_orders (交易审查)
```

### SentimentTab（情绪周期）
```
SentimentTab.vue
  └─ useSentimentMonitor
       ├─ GET /scanner/market-sentiment → sentiment_scores
       └─ GET /scanner/sentiment-strategy-matrix → broker_orders
```

### ScanTraceTab（扫描追踪）
```
ScanTraceTab.vue
  └─ useScanTraceMonitor
       ├─ GET /scanner/scan-traces → scan_traces
       └─ GET /scanner/execution-quality → broker_orders + scan_traces
```

---

## 五、已知问题 & 残留风险

### P0: 昨日遗留6只持仓（应卖未卖）
| 代码 | 现价 | 止损价 | 盈亏 | 状态 |
|------|------|--------|------|------|
| 000608.SZ | 6.52 | 6.80 | -7.0% | 🔴破止损 |
| 000890.SZ | 9.62 | 10.28 | -9.2% | 🔴破止损 |
| 002057.SZ | 12.10 | 12.13 | -3.3% | 🔴破止损 |
| 002081.SZ | 5.12 | 5.60 | -11.3% | 🔴破止损 |
| 002181.SZ | 12.30 | 15.53 | -23.2% | 🔴破止损 |
| 300586.SZ | 13.82 | 13.36 | +0.4% | ⚠️接近止损 |

**根因**: scanner进程崩溃 → save_state()未执行 → broker_positions丢失 → 止损监控失效
**影响**: 今天9笔新买入是在6只"死仓"基础上建的，总持仓=15只(6死+9新)，远超风控上限10只

### P1: scanner进程崩溃时 save_state 不可靠
- Python的graceful shutdown不保证执行
- 需要在买入成功后立即 save_state(force=True)
- 或者在risk_loop中增加持仓丢失检测

### P2: 前端 useScannerMonitor 持有两份持仓
- `positions` (来自 /all → scanner内存)
- `unified.positions` (来自 /unified/positions → broker_positions)
- 目前各Tab各自选读，未统一

### P3: broker_accounts.position_count 缓存不可信
- save_state时可能不更新此字段
- 已修复为从 broker_positions 实查

---

## 六、架构改进方向

### 短期（已实施 v2.9.97c）
- ✅ broker_orders = 交易唯一真相源
- ✅ broker_positions = 持仓唯一真相源
- ✅ scanner_timeline 不再写 buy/sell
- ✅ /account position_count 实查

### 中期
- 🔲 统一前端数据层：所有Tab通过 useUnifiedData 获取数据
- 🔲 scanner 内部持仓也从 broker_positions 读取（目前是内存维护）
- 🔲 买入成功后立即 save_state(force=True)，不依赖 stop()

### 长期
- 🔲 scanner_timeline 重命名为 scanner_decision_log（职责更清晰）
- 🔲 增加 MongoDB 事务保证 broker_orders + broker_positions 原子写入
- 🔲 增加跨端点数据一致性测试（CI/CD 门槛）

---

## 七、今日交易流时间线

```
09:25  scanner_autoheal 启动scanner
09:28  第1轮扫描: 78个候选, 多个被集中度过滤拦截
09:39  🟢 BUY 000012.SZ 南玻A 4700@4.53 (新开仓)
10:30  🟢 BUY 000510.SZ 新金路 4400@23.06 (新开仓)
10:30  🔴 SELL 001269.SZ 欧晶科技 1400@27.0 (跳空止损)
10:30  🟢 BUY 000636.SZ 风华高科 1200@71.48 (新开仓)
10:49  🟢 BUY 000032.SZ 深桑达A 3200@22.96 (新开仓)
11:18  🟢 BUY 000029.SZ 深深房A 2200@27.70 (新开仓)
11:18  🟢 BUY 000048.SZ 京基智农 1800@19.17 (新开仓)
11:18  🟢 BUY 000733.SZ 振华科技 500@55.99 (新开仓)
11:18  🟢 BUY 000541.SZ 佛山照明 5300@5.33 (新开仓)
11:18  🟢 BUY 000679.SZ 大连友谊 1900@6.40 (新开仓)

结果: 7(旧仓) - 1(卖) + 9(新买) = 15只持仓
其中5只旧仓已破止损, 1只接近止损
```

---

## 八、一致性自动检查清单

| 检查 | 方法 | 频率 | 状态 |
|------|------|------|------|
| /all == /analysis == /unified positions | API对比 | 每次部署 | ✅ 已通过 |
| /account position_count == broker_positions count | API测试 | 每次部署 | ✅ 已通过 |
| unified buys == timeline buys | API对比 | 每次部署 | ✅ 已通过 |
| broker_positions qty == broker_orders 净买入 | MongoDB聚合 | 每日 | ✅ 已通过 |
| scanner_timeline 无新 buy/sell | count_documents | 每日 | ✅ 已验证 |
| 破止损持仓是否被监控 | 逻辑检查 | 盘中实时 | ❌ 需关注 |
