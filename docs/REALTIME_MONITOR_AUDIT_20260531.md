# 实时监听 WEB 功能复盘审查报告

> 审查时间: 2026-05-31 21:50 CST
> 审查范围: 后端(web节点) + 前端(monitor视图) + 数据流完整性
> 约束: 不得影响回测功能模块

---

## 🔴 严重Bug (P0 - 必须修复)

### 1. Redis→WebSocket 桥接从未启动
- **文件**: `nodes/web/app.py` lifespan函数
- **问题**: `init_bridge()` 和 `bridge.start()` 从未在lifespan中调用
- **影响**: 整个实时数据推送链路(Redis Pub/Sub → WebSocket → 前端)完全不工作
  - scanner信号/持仓/时间线不会通过WS推送
  - 前端只能依赖REST轮询(5s/60s间隔)
  - 回测日志也不会WS推送
- **证据**: `websocket.py` 文件头注释写明了调用方式，但lifespan中无对应代码
- **修复方案**:
```python
# app.py lifespan 启动部分添加:
from nodes.web.redis_ws_bridge import init_bridge
from .websocket import manager
bridge = init_bridge(manager)
await bridge.start()

# 关闭部分添加:
from nodes.web.redis_ws_bridge import get_bridge
bridge = get_bridge()
if bridge:
    await bridge.stop()
```

### 2. signal_persistence 使用未定义的集合常量
- **文件**: `nodes/web/signal_persistence.py`
- **问题**: `COLLECTION_REVIEW`、`COLLECTION_EXECUTION_LOG`、`COLLECTION_POOL` 三常量
  只有注释"not in C"但从未定义，Python运行时会 NameError
- **影响**: 以下方法调用会崩溃:
  - `initialize()` — 启动时创建索引必崩
  - `save_postmarket_review()` — 保存盘后复盘
  - `save_premarket_pool()` — 保存盘前池
  - `mark_signal_executed()` — 标记信号已执行(portfolio_tracker调用)
  - `cleanup_old_signals()` — 清理旧数据
  - `get_pool_by_date()` — 查询盘前池
- **修复方案**:
```python
# 在 signal_persistence.py 顶部定义:
COLLECTION_REVIEW = "daily_postmarket_review"
COLLECTION_EXECUTION_LOG = "signal_execution_log"
COLLECTION_POOL = "premarket_pool"
```

### 3. daily_settlement() 函数无路由装饰器
- **文件**: `nodes/web/api/scanner.py` L888
- **问题**: `async def daily_settlement()` 定义了但没有 `@router.post("/daily-settlement")` 装饰器
- **影响**: 前端 `dailySettlement()` 调用 POST `/scanner/daily-settlement` 返回 404
- **修复方案**: 添加路由装饰器
```python
@router.post("/daily-settlement")
async def daily_settlement():
```

---

## 🟡 中等问题 (P1 - 应当修复)

### 4. RedisWSBridge._log_cache 在 get_stats() 中引用但未初始化
- **文件**: `nodes/web/redis_ws_bridge.py` L482
- **问题**: `__init__` 中注释"日志不再缓存"但 `get_stats()` 仍引用 `self._log_cache`
- **影响**: 调用 `get_stats()` 时 NameError（但当前bridge未启动，暂未触发）
- **修复方案**:
```python
# __init__ 中添加:
self._log_cache: Dict[str, Any] = {}

# 或删除 get_stats 中的引用:
"cached_tasks": 0,  # 日志不再缓存
```

### 5. 前端 WS 连接未复用统一 hook
- **文件**: `MarketMonitorView.vue` L812
- **问题**: MarketMonitorView 自己 new WebSocket 管理，未使用 `useWebSocket` hook
- **影响**: 
  - 两套WS连接可能同时存在(如果其他页面用useWebSocket)
  - useWebSocket hook的心跳/重连逻辑被绕过
  - 维护成本高（3135行的巨文件中WS逻辑内嵌）
- **建议**: 长期重构，短期可接受（功能独立，暂不冲突）

### 6. MarketMonitorView 单文件3135行，过于庞大
- **文件**: `frontend/src/views/monitor/MarketMonitorView.vue`
- **问题**: 单个Vue文件3135行，包含WS连接、REST API调用、业务逻辑、模板、样式
- **影响**: 维护困难，容易引入bug，加载性能差
- **建议**: 按功能拆分为composables（useScannerWS, useScannerTrade, useScannerStrategy等）

---

## 🟢 低风险问题 (P2 - 可优化)

### 7. ScannerStore 的 refreshFromApi 与 MarketMonitorView 本地状态重复
- **文件**: `stores/scanner.ts` + `MarketMonitorView.vue`
- **问题**: 两者都维护了 signals/positions/timeline 的ref，容易不同步
- **现状**: MarketMonitorView 通过 `scannerStore.updateFromWs()` 写Store，但自身用 `signals.value` (本地ref) 渲染
- **建议**: 统一使用Store的响应式状态，去掉本地重复ref

### 8. WS断线重连后Stream ID补发逻辑不完整
- **文件**: `MarketMonitorView.vue` L835-839
- **问题**: 记录了 `lastSignalStreamId` / `lastPositionStreamId` 但断线重连后未使用
- **建议**: 重连后调用 `/scanner/stream/signals?after={lastSignalStreamId}` 补发缺失数据

### 9. onMounted 错误处理过于简单
- **文件**: `MarketMonitorView.vue` L807
- **问题**: `catch(e) { console.error(...) }` 只打日志，用户不知道初始化失败
- **建议**: 关键初始化失败时显示错误提示

---

## ✅ 回测模块隔离性检查

| 检查项 | 结果 | 说明 |
|--------|------|------|
| scanner是否调用回测RPC | ✅ 无 | scanner无任何回测RPC调用 |
| scanner是否依赖回测代码 | ✅ 低 | 仅引用strategy_defaults常量(只读配置) |
| WS桥接是否影响回测 | ✅ 无 | 桥接仅转发Redis消息，不影响回测节点 |
| 回测API路由是否独立 | ✅ 是 | `/api/v1/backtest/*` 独立路由树 |
| 修复是否影响回测 | ✅ 否 | 所有修复限于web节点scanner模块 |

---

## 📊 前后端API完整性对照

### 前端调用的所有API端点状态

| 前端API | 后端路由 | 状态 |
|---------|----------|------|
| GET /scanner/all | @router.get("/all") | ✅ |
| GET /scanner/status | @router.get("/status") | ✅ |
| GET /scanner/health | @router.get("/health") | ✅ |
| GET /scanner/signals | @router.get("/signals") | ✅ |
| GET /scanner/positions | @router.get("/positions") | ✅ |
| GET /scanner/timeline | @router.get("/timeline") | ✅ |
| GET /scanner/timeline/history | @router.get("/timeline/history") | ✅ |
| GET /scanner/orders | @router.get("/orders") | ✅ |
| GET /scanner/limit-pools | @router.get("/limit-pools") | ✅ |
| GET /scanner/daily-report | @router.get("/daily-report") | ✅ |
| GET /scanner/historical-review | @router.get("/historical-review") | ✅ |
| GET /scanner/sentiment-timeline | @router.get("/sentiment-timeline") | ✅ |
| GET /scanner/sentiment-strategy-matrix | @router.get("/sentiment-strategy-matrix") | ✅ |
| GET /scanner/position-risk-matrix | @router.get("/position-risk-matrix") | ✅ |
| GET /scanner/system-health-detail | @router.get("/system-health-detail") | ✅ |
| GET /scanner/strategy-performance | @router.get("/strategy-performance") | ✅ |
| GET /scanner/kline/{code} | @router.get("/kline/{ts_code}") | ✅ |
| GET /scanner/trade-detail/{code} | @router.get("/trade-detail/{ts_code}") | ✅ |
| GET /scanner/trade-audit | @router.get("/trade-audit") | ✅ |
| GET /scanner/backtest-compare | @router.get("/backtest-compare") | ✅ |
| GET /scanner/debug/layers | @router.get("/debug/layers") | ✅ |
| GET /scanner/debug/scan-trace/{code} | @router.get("/debug/scan-trace/{ts_code}") | ✅ |
| GET /scanner/performance-history | @router.get("/performance-history") | ✅ |
| GET /scanner/stream/signals | @router.get("/stream/signals") | ✅ |
| GET /scanner/stream/positions | @router.get("/stream/positions") | ✅ |
| GET /scanner/premarket-status | @router.get("/premarket-status") | ✅ |
| GET /scanner/scan-config | @router.get("/scan-config") | ✅ |
| GET /scanner/scan-dates | @router.get("/scan-dates") | ✅ |
| GET /scanner/scan-traces | @router.get("/scan-traces") | ✅ |
| GET /scanner/quote/{code} | @router.get("/quote/{ts_code}") | ✅ |
| GET /scanner/audit-log | @router.get("/audit-log") | ✅ |
| GET /scanner/auto-trades | @router.get("/auto-trades") | ✅ |
| GET /scanner/execution-quality | @router.get("/execution-quality") | ✅ |
| GET /scanner/trade-attribution | @router.get("/trade-attribution") | ✅ |
| GET /scanner/strategy-params-compare | @router.get("/strategy-params-compare") | ✅ |
| GET /scanner/weekly-report | @router.get("/weekly-report") | ✅ |
| GET /scanner/trade-log | @router.get("/trade-log") | ✅ |
| GET /scanner/market-sentiment | @router.get("/market-sentiment") | ✅ |
| GET /scanner/snapshot | @router.get("/snapshot") | ✅ |
| POST /scanner/start | @router.post("/start") | ✅ |
| POST /scanner/stop | @router.post("/stop") | ✅ |
| POST /scanner/scan-once | @router.post("/scan-once") | ✅ |
| POST /scanner/trade | @router.post("/trade") | ✅ |
| POST /scanner/sell-all | @router.post("/sell-all") | ✅ |
| POST /scanner/sell | @router.post("/sell") | ✅ |
| POST /scanner/circuit-breaker/reset | @router.post("/circuit-breaker/reset") | ✅ |
| POST /scanner/circuit-breaker/pause | @router.post("/circuit-breaker/pause") | ✅ |
| POST /scanner/emergency-liquidate | @router.post("/emergency-liquidate") | ✅ |
| POST /scanner/debug/dry-run | @router.post("/debug/dry-run") | ✅ |
| POST /scanner/params/validate | @router.post("/params/validate") | ✅ |
| POST /scanner/reset | @router.post("/reset") | ✅ |
| PUT /scanner/trailing-stop/{code} | @router.put("/trailing-stop/{ts_code}") | ✅ |
| PUT /strategy-config/strategies/{id} | (strategy_config路由) | ✅ |
| GET /strategy-config/strategies | (strategy_config路由) | ✅ |
| GET /strategy-config/global-risk | (strategy_config路由) | ✅ |
| POST /strategy-config/reset/{id} | (strategy_config路由) | ✅ |
| GET /datasource/sources | (datasource路由) | ✅ |
| GET /datasource/brokers | (datasource路由) | ✅ |
| **POST /scanner/daily-settlement** | **❌ 无路由装饰器** | **🔴 404** |

---

## 🔧 修复优先级建议

| 优先级 | Bug | 预计工作量 | 风险 |
|--------|-----|-----------|------|
| P0 | #1 Bridge未启动 | 5行代码 | 低 — 仅在lifespan添加启动/关闭 |
| P0 | #2 集合常量未定义 | 3行代码 | 低 — 添加常量定义即可 |
| P0 | #3 daily_settlement无路由 | 1行代码 | 低 — 添加装饰器 |
| P1 | #4 _log_cache未初始化 | 1行代码 | 低 |
| P1 | #5-6 前端重构 | 中等工作量 | 中 — 需充分测试 |

**P0修复总代码量约10行，风险极低，建议立即修复。**
